"""Safety and fallback coverage for ZIP-preferred Web Sync staging."""
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import warnings
import zipfile

import pytest
import requests

from app.web_sync.client import ApiError, DownloadLimitError
import app.web_sync.zip_downloads as zip_downloads


CASE_ID = "case-9848"
DISPATCH_ID = "dispatch-9848"


def _entry(archive_name, canonical_name, payload, *, latest=False, doc_type=""):
    return {
        "file_id": f"id-{archive_name}",
        "archive_name": archive_name,
        "original_name": Path(archive_name).name,
        "original_path": archive_name,
        "canonical_name": canonical_name,
        "mime_type": "application/octet-stream",
        "doc_type": doc_type,
        "size_bytes": len(payload),
        "md5_checksum": hashlib.md5(payload).hexdigest(),
        "is_latest_corrected_excel": latest,
    }


def _standard_files():
    return [
        (_entry("source/latest.xlsx", "corrected_claim.xlsx", b"excel", latest=True), b"excel"),
        (_entry("source/rc.pdf", "rc_book.pdf", b"rc", doc_type="RC"), b"rc"),
        (
            _entry(
                "photos/14_5.jpg", "vehicle_photo_01.jpg", b"photo",
                doc_type="CLAIM_PHOTOS",
            ),
            b"photo",
        ),
    ]


def _zip_bytes(files=None, *, case_id=CASE_ID, dispatch_id=DISPATCH_ID, extra_members=()):
    files = files or _standard_files()
    manifest = {
        "case_id": case_id,
        "automation_dispatch_id": dispatch_id,
        "files": [entry for entry, _payload in files],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for entry, payload in files:
            archive.writestr(entry["archive_name"], payload)
        for name, payload in extra_members:
            archive.writestr(name, payload)
    return output.getvalue()


def _manifest_only_zip(manifest):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    return output.getvalue()


class ZipClient:
    def __init__(self, payload=None, errors=()):
        self.payload = payload if payload is not None else _zip_bytes()
        self.errors = list(errors)
        self.calls = []

    def call(self, function, body, destination=None, max_bytes=None):
        self.calls.append((function, dict(body), destination, max_bytes))
        if self.errors:
            raise self.errors.pop(0)
        assert function == "getAutomationCaseZip"
        assert body == {"case_id": CASE_ID, "automation_dispatch_id": DISPATCH_ID}
        Path(destination).write_bytes(self.payload)
        return {"Content-Type": "application/zip"}

    def jobs(self):
        return [{"case_id": CASE_ID, "automation_dispatch_id": DISPATCH_ID}]


def _forbid_fallback(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("individual fallback must not run")
    monkeypatch.setattr(zip_downloads, "download_case", forbidden)


def _capture_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(zip_downloads, "ENABLE_FALLBACK", True)

    def parallel_failure(*_args, **_kwargs):
        raise zip_downloads.ParallelDownloadError("parallel unavailable in ZIP unit test")

    def fallback(client, case_id, folder, progress=None, automation_dispatch_id=None):
        calls.append((client, case_id, Path(folder), progress, automation_dispatch_id))
        return "fallback.xlsx"

    monkeypatch.setattr(zip_downloads, "download_case_parallel", parallel_failure)
    monkeypatch.setattr(zip_downloads, "download_case", fallback)
    return calls


def test_valid_zip_corrected_excel_and_photo_names(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)
    events = []

    latest = zip_downloads.download_case_preferred(
        ZipClient(), CASE_ID, tmp_path, progress=events.append,
        automation_dispatch_id=DISPATCH_ID,
    )

    assert latest == "corrected_claim.xlsx"
    assert (tmp_path / "corrected_claim.xlsx").read_bytes() == b"excel"
    assert (tmp_path / "rc_book.pdf").read_bytes() == b"rc"
    assert (tmp_path / "vehicle_photo_01.jpg").read_bytes() == b"photo"
    audit = json.loads((tmp_path / "web_sync_manifest.json").read_text(encoding="utf-8"))
    assert audit["download_mode"] == "zip"
    assert audit["latest_excel"] == "corrected_claim.xlsx"
    assert sum(item["is_latest_corrected_excel"] for item in audit["files"]) == 1
    assert any(item["local_name"] == "vehicle_photo_01.jpg" for item in audit["files"])
    assert events[-1]["kind"] == "complete"


@pytest.mark.parametrize(
    "wrong_case,wrong_dispatch,match",
    [("another-case", DISPATCH_ID, "case_id"), (CASE_ID, "another-dispatch", "dispatch")],
)
def test_wrong_zip_identity_never_falls_back(
    tmp_path, monkeypatch, wrong_case, wrong_dispatch, match,
):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)
    client = ZipClient(_zip_bytes(case_id=wrong_case, dispatch_id=wrong_dispatch))
    with pytest.raises(zip_downloads.ZipIdentityError, match=match):
        zip_downloads.download_case_preferred(
            client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
        )


def test_stale_dispatch_stops_without_retry_or_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)
    error = ApiError(409, "getAutomationCaseZip", "stale_dispatch")
    client = ZipClient(errors=[error])
    with pytest.raises(ApiError) as caught:
        zip_downloads.download_case_preferred(
            client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
        )
    assert caught.value is error
    assert len(client.calls) == 1


def test_timeout_retries_three_attempts_with_expected_waits(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)
    waits = []
    monkeypatch.setattr(zip_downloads.time, "sleep", waits.append)
    client = ZipClient(errors=[requests.ReadTimeout("one"), requests.ReadTimeout("two")])
    assert zip_downloads.download_case_preferred(
        client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    ) == "corrected_claim.xlsx"
    assert len(client.calls) == 3
    assert waits == [3, 7]


@pytest.mark.parametrize(
    "payload",
    [
        b"not-a-zip",
        _manifest_only_zip({
            "case_id": CASE_ID,
            "automation_dispatch_id": DISPATCH_ID,
            "files": [],
        }),
    ],
    ids=["corrupt-zip", "ordinary-archive-integrity"],
)
def test_corrupt_or_ordinary_integrity_failure_falls_back(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    calls = _capture_fallback(monkeypatch)
    assert zip_downloads.download_case_preferred(
        ZipClient(payload), CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    ) == "fallback.xlsx"
    assert len(calls) == 1


@pytest.mark.parametrize("unsafe_name", ["../escape.txt", "/absolute.txt", "C:/drive.txt"])
def test_unsafe_zip_paths_never_fall_back(tmp_path, monkeypatch, unsafe_name):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)
    payload = _zip_bytes(extra_members=((unsafe_name, b"unsafe"),))
    with pytest.raises(zip_downloads.UnsafeZipError):
        zip_downloads.download_case_preferred(
            ZipClient(payload), CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
        )
    assert not (tmp_path.parent / "escape.txt").exists()


def test_duplicate_zip_member_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", "{}")
            archive.writestr("same.txt", "one")
            archive.writestr("SAME.txt", "two")
    with pytest.raises(zip_downloads.UnsafeZipError, match="duplicate"):
        zip_downloads.download_case_preferred(
            ZipClient(output.getvalue()), CASE_ID, tmp_path,
            automation_dispatch_id=DISPATCH_ID,
        )


def _set_encrypted_flags(payload):
    data = bytearray(payload)
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while True:
            index = data.find(signature, start)
            if index < 0:
                break
            flags = struct.unpack_from("<H", data, index + offset)[0]
            struct.pack_into("<H", data, index + offset, flags | 1)
            start = index + 4
    return bytes(data)


@pytest.mark.parametrize("kind", ["encrypted", "special"])
def test_encrypted_or_special_members_never_fall_back(tmp_path, monkeypatch, kind):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)
    if kind == "encrypted":
        payload = _set_encrypted_flags(_zip_bytes())
    else:
        output = io.BytesIO()
        special = zipfile.ZipInfo("named-pipe")
        special.create_system = 3
        special.external_attr = (stat.S_IFIFO | 0o644) << 16
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(special, b"pipe")
        payload = output.getvalue()
    with pytest.raises(zip_downloads.UnsafeZipError, match=kind):
        zip_downloads.download_case_preferred(
            ZipClient(payload), CASE_ID, tmp_path,
            automation_dispatch_id=DISPATCH_ID,
        )


def test_compressed_limit_uses_individual_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    monkeypatch.setattr(zip_downloads, "MAX_COMPRESSED_BYTES", 10)
    calls = _capture_fallback(monkeypatch)
    assert zip_downloads.download_case_preferred(
        ZipClient(b"more-than-ten-bytes"), CASE_ID, tmp_path,
        automation_dispatch_id=DISPATCH_ID,
    ) == "fallback.xlsx"
    assert len(calls) == 1


class _Info:
    def __init__(self, name, compressed, uncompressed):
        self.filename = name
        self.compress_size = compressed
        self.file_size = uncompressed
        self.external_attr = (stat.S_IFREG | 0o644) << 16
        self.flag_bits = 0

    def is_dir(self):
        return False


class _Archive:
    def __init__(self, members):
        self.members = members

    def infolist(self):
        return self.members


def test_uncompressed_limit_rejected(monkeypatch):
    archive = _Archive([_Info("large.bin", 10 * 1024 * 1024, 100 * 1024 * 1024 + 1)])
    # Intentional design: By default (None), large cases are permitted without artificial limit
    assert zip_downloads._inspect_archive(archive) is not None
    # When explicitly configured, the safety limit is enforced
    monkeypatch.setattr(zip_downloads, "MAX_UNCOMPRESSED_BYTES", 100 * 1024 * 1024)
    with pytest.raises(zip_downloads.UnsafeZipError, match="100 MiB"):
        zip_downloads._inspect_archive(archive)


def test_expansion_ratio_rejected():
    archive = _Archive([_Info("bomb.bin", 100, 2001)])
    with pytest.raises(zip_downloads.UnsafeZipError, match="20:1"):
        zip_downloads._inspect_archive(archive)


def test_member_count_limit_rejected(monkeypatch):
    archive = _Archive([_Info(f"file-{number}.bin", 1, 1) for number in range(201)])
    # Intentional design: By default (None), cases with many members are permitted without artificial limit
    assert zip_downloads._inspect_archive(archive) is not None
    # When explicitly configured, the member limit is enforced
    monkeypatch.setattr(zip_downloads, "MAX_MEMBERS", 200)
    with pytest.raises(zip_downloads.UnsafeZipError, match="200 members"):
        zip_downloads._inspect_archive(archive)


@pytest.mark.parametrize("problem", ["md5", "size"])
def test_extracted_size_or_md5_failure_falls_back(tmp_path, monkeypatch, problem):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    files = _standard_files()
    if problem == "md5":
        files[1][0]["md5_checksum"] = "0" * 32
    else:
        files[1][0]["size_bytes"] += 1
    calls = _capture_fallback(monkeypatch)
    assert zip_downloads.download_case_preferred(
        ZipClient(_zip_bytes(files)), CASE_ID, tmp_path,
        automation_dispatch_id=DISPATCH_ID,
    ) == "fallback.xlsx"
    assert len(calls) == 1


def test_fallback_reconfirms_dispatch_and_uses_existing_downloader(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    calls = _capture_fallback(monkeypatch)
    client = ZipClient(errors=[ApiError(501, "getAutomationCaseZip")])
    assert zip_downloads.download_case_preferred(
        client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    ) == "fallback.xlsx"
    assert len(calls) == 1
    assert calls[0][1:] == (CASE_ID, tmp_path, None, DISPATCH_ID)


def test_zip_failure_prefers_parallel_before_sequential(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "ENABLE_FALLBACK", True)
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    parallel_calls = []

    def parallel(client, case_id, folder, progress=None, automation_dispatch_id=None):
        parallel_calls.append((client, case_id, Path(folder), progress, automation_dispatch_id))
        return "parallel.xlsx"

    monkeypatch.setattr(zip_downloads, "download_case_parallel", parallel)
    _forbid_fallback(monkeypatch)
    client = ZipClient(errors=[ApiError(501, "getAutomationCaseZip")])
    assert zip_downloads.download_case_preferred(
        client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    ) == "parallel.xlsx"
    assert len(parallel_calls) == 1
    assert parallel_calls[0][1:] == (CASE_ID, tmp_path, None, DISPATCH_ID)


def test_individual_only_rollback_skips_zip_request(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "individual")
    calls = _capture_fallback(monkeypatch)
    client = ZipClient()
    assert zip_downloads.download_case_preferred(
        client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    ) == "fallback.xlsx"
    assert not client.calls
    assert len(calls) == 1


def test_local_zip_without_manifest_extracts_and_stages_safely(tmp_path, monkeypatch):
    from app.web_sync.manifest import validate_staged_case

    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    _forbid_fallback(monkeypatch)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Printable_Assessment_2026.xlsx", b"excel_bytes")
        archive.writestr("rc_document.pdf", b"rc_bytes")
        archive.writestr("subfolder/vehicle_photo.jpg", b"photo_bytes")

    client = ZipClient(output.getvalue())
    events = []
    latest = zip_downloads.download_case_preferred(
        client, CASE_ID, tmp_path, progress=events.append,
        automation_dispatch_id=DISPATCH_ID,
    )

    assert latest == "Printable_Assessment_2026.xlsx"
    assert (tmp_path / "Printable_Assessment_2026.xlsx").read_bytes() == b"excel_bytes"
    assert (tmp_path / "rc_document.pdf").read_bytes() == b"rc_bytes"
    assert (tmp_path / "vehicle_photo.jpg").read_bytes() == b"photo_bytes"

    manifest_data = validate_staged_case(
        tmp_path, CASE_ID, DISPATCH_ID, "Printable_Assessment_2026.xlsx", verify_md5=True,
    )
    assert manifest_data["complete"] is True
    assert manifest_data["latest_excel"] == "Printable_Assessment_2026.xlsx"
    assert len(manifest_data["files"]) == 3
    assert events[-1]["kind"] == "complete"


def test_local_zip_failure_skips_individual_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_downloads, "DOWNLOAD_MODE", "zip_preferred")
    calls = _capture_fallback(monkeypatch)

    # Local ZIP without Excel workbook fails verification and must NEVER call fallback
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("only_a_pdf.pdf", b"pdf_data")

    client = ZipClient(output.getvalue())
    with pytest.raises(zip_downloads.LocalCaseZipError):
        zip_downloads.download_case_preferred(
            client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
        )

    # Verify fallback was completely skipped
    assert len(calls) == 0


def test_drive_zip_failure_default_skips_fallback(tmp_path, monkeypatch):
    calls = []

    def fallback(*_args, **_kwargs):
        calls.append(True)
        return "fallback.xlsx"

    monkeypatch.setattr(zip_downloads, "download_case_parallel", fallback)
    monkeypatch.setattr(zip_downloads, "download_case", fallback)
    client = ZipClient(errors=[ApiError(500, "getAutomationCaseZip")] * 3)
    with pytest.raises(ApiError):
        zip_downloads.download_case_preferred(
            client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
        )
    assert len(calls) == 0
