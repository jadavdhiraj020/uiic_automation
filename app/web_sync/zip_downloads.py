"""ZIP-preferred Web Sync staging with the existing downloader as fallback."""
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time
import zipfile

import requests

from .client import ApiError, DownloadLimitError
from .downloads import download_case
from .manifest import (
    EXCEL_SUFFIXES,
    flat_name,
    integrity,
    latest_corrected,
    plan_local_files,
    unique_name,
)
from .parallel_downloads import (
    ParallelDownloadError,
    ParallelIdentityError,
    download_case_parallel,
)
from .storage import atomic_json


logger = logging.getLogger(__name__)
DOWNLOAD_MODE = os.environ.get("APP3_DOWNLOAD_MODE", "zip_preferred").strip().lower()
# Intentional product policy: ZIP-only by default. The legacy per-file path is
# retained for an explicit rollback, not as an automatic recovery path.
ENABLE_FALLBACK = os.environ.get("APP3_ENABLE_ZIP_FALLBACK", "0").strip().lower() in ("1", "true", "yes")
ZIP_FUNCTION = "getAutomationCaseZip"
ZIP_RETRY_DELAYS = (3, 7)
MAX_COMPRESSED_BYTES = None
# Intentional design: Insurance cases frequently contain dozens or hundreds of high-resolution
# inspection photographs, vehicle damage videos, and multi-page scanned PDF reports that easily
# exceed arbitrary byte and member count caps. Uncompressed size and member count limits are
# intentionally disabled (None) so complete cases are never blocked from staging. Path security
# (no absolute paths, no directory traversal, no symlinks) and expansion-ratio checks remain active.
MAX_UNCOMPRESSED_BYTES = None
MAX_MEMBERS = None
MAX_EXPANSION_RATIO = 20


class ZipIdentityError(ValueError):
    """The archive belongs to another case or dispatch; fallback is forbidden."""


class UnsafeZipError(ValueError):
    """The archive contains a path or member that must never be extracted."""


class ZipIntegrityError(ValueError):
    """The ordinary ZIP or an extracted member failed integrity validation."""


class LocalCaseZipError(ZipIntegrityError):
    """A local-case ZIP failed verification; individual-file fallback is forbidden."""


def _notify(progress, **event):
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        pass


def _stale(error):
    return bool(
        isinstance(error, ApiError)
        and error.status == 409
        and str(getattr(error, "code", "")).strip().lower() == "stale_dispatch"
    )


def _retryable_zip_request(error):
    return bool(
        isinstance(error, requests.exceptions.RequestException)
        or (isinstance(error, ApiError) and error.status >= 500)
    )


def _fallback_status(error):
    return bool(
        isinstance(error, DownloadLimitError)
        or (isinstance(error, ApiError) and error.status in (404, 413, 422, 501))
    )


def _safe_member_name(name):
    if not isinstance(name, str) or not name or "\x00" in name:
        raise UnsafeZipError("ZIP contains an empty or invalid member name")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise UnsafeZipError(f"ZIP contains an absolute member path: {name}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise UnsafeZipError(f"ZIP member escapes the staging folder: {name}")
    if not path.parts or any(part in ("", ".") for part in path.parts):
        raise UnsafeZipError(f"ZIP contains an unsafe member path: {name}")
    return path.as_posix()


def _inspect_archive(archive):
    members = archive.infolist()
    if MAX_MEMBERS is not None and len(members) > MAX_MEMBERS:
        raise UnsafeZipError(f"ZIP contains more than {MAX_MEMBERS} members")
    seen = set()
    total_compressed = 0
    total_uncompressed = 0
    safe_members = {}
    for member in members:
        safe_name = _safe_member_name(member.filename)
        key = safe_name.casefold()
        if key in seen:
            raise UnsafeZipError(f"ZIP contains a duplicate member path: {safe_name}")
        seen.add(key)
        mode = (member.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise UnsafeZipError(f"ZIP contains a symbolic link: {safe_name}")
        member_type = stat.S_IFMT(mode)
        if member_type and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise UnsafeZipError(f"ZIP contains a special file: {safe_name}")
        if member.flag_bits & 0x1:
            raise UnsafeZipError(f"ZIP contains an encrypted member: {safe_name}")
        if member.file_size < 0 or member.compress_size < 0:
            raise UnsafeZipError(f"ZIP contains invalid member sizes: {safe_name}")
        total_compressed += member.compress_size
        total_uncompressed += member.file_size
        safe_members[key] = (safe_name, member)
    if MAX_UNCOMPRESSED_BYTES is not None and total_uncompressed > MAX_UNCOMPRESSED_BYTES:
        raise UnsafeZipError("ZIP exceeds the 100 MiB uncompressed safety limit")
    if total_uncompressed and total_uncompressed > max(total_compressed, 1) * MAX_EXPANSION_RATIO:
        raise UnsafeZipError("ZIP exceeds the 20:1 expansion-ratio safety limit")
    return safe_members


def _read_embedded_manifest(archive, members, case_id, dispatch_id):
    manifest_item = members.get("manifest.json")
    if not manifest_item or manifest_item[1].is_dir():
        raise ZipIntegrityError("ZIP contains no root manifest.json")
    try:
        with archive.open(manifest_item[1], "r") as source:
            manifest = json.loads(source.read().decode("utf-8"))
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ZipIntegrityError(f"ZIP manifest.json is invalid: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ZipIntegrityError("ZIP manifest.json must contain an object")
    if manifest.get("case_id") != case_id:
        raise ZipIdentityError("ZIP case_id does not match the requested case")
    if manifest.get("automation_dispatch_id") != dispatch_id:
        raise ZipIdentityError("ZIP automation_dispatch_id does not match the requested dispatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ZipIntegrityError("ZIP manifest contains no files")
    return manifest, files


def _plan_files(files, members):
    try:
        latest_entry = latest_corrected(files)
    except ValueError as exc:
        raise ZipIntegrityError(str(exc)) from exc
    archive_names = set()
    archive_details = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise ZipIntegrityError("ZIP manifest contains an invalid file entry")
        archive_name = _safe_member_name(entry.get("archive_name"))
        archive_key = archive_name.casefold()
        if archive_key == "manifest.json" or archive_key in archive_names:
            raise UnsafeZipError(f"ZIP manifest contains a duplicate archive_name: {archive_name}")
        archive_names.add(archive_key)
        member_item = members.get(archive_key)
        if not member_item or member_item[1].is_dir():
            raise ZipIntegrityError(f"ZIP member is missing: {archive_name}")
        try:
            expected_size, _expected_md5 = integrity(entry)
        except (TypeError, ValueError) as exc:
            raise ZipIntegrityError(
                f"ZIP manifest has invalid size/MD5 metadata for {archive_name}: {exc}"
            ) from exc
        if member_item[1].file_size != expected_size:
            raise ZipIntegrityError(f"ZIP member size disagrees with manifest: {archive_name}")

        archive_details[id(entry)] = (archive_name, member_item[1])

    archive_files = {
        key for key, (_name, member) in members.items()
        if not member.is_dir() and key != "manifest.json"
    }
    if archive_files != archive_names:
        raise UnsafeZipError("ZIP contains files that are not declared in manifest.json")
    try:
        def collision(requested_name, file_id, local_name):
            logger.warning(
                "Web Sync filename collision for %s (%s); saved as %s",
                requested_name, file_id, local_name,
            )

        def excel_renamed(_entry, file_id, local_name):
            logger.warning(
                "Unflagged Excel %s requested the latest workbook name; saved as %s",
                file_id, local_name,
            )

        common_plan, latest_name = plan_local_files(
            files,
            latest_entry,
            fallback_name=lambda entry: entry.get("original_name") or archive_details[id(entry)][0],
            file_id=lambda entry: entry.get("file_id") or archive_details[id(entry)][0],
            on_collision=collision,
            on_excel_renamed=excel_renamed,
        )
    except ValueError as exc:
        raise ZipIntegrityError(str(exc)) from exc
    planned = [
        (
            item["entry"], archive_details[id(item["entry"])][1],
            archive_details[id(item["entry"])][0], item["local_name"],
            item["expected_size"], item["expected_md5"], item["file_id"],
        )
        for item in common_plan
    ]
    return planned, latest_name


def _extract_verified(archive, planned, extraction_root, progress):
    extraction_root.mkdir(parents=True, exist_ok=False)
    mapping = []
    total = len(planned)
    for index, (entry, member, archive_name, local_name, expected_size, expected_md5, file_id) in enumerate(planned, start=1):
        destination = (extraction_root / local_name).resolve()
        if extraction_root.resolve() not in destination.parents:
            raise UnsafeZipError(f"ZIP destination escapes staging folder: {local_name}")
        temporary = destination.with_name(destination.name + ".download")
        try:
            digest = hashlib.md5()
            written = 0
            with archive.open(member, "r") as source, temporary.open("xb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > expected_size:
                        raise ZipIntegrityError(f"Extracted file exceeds manifest size: {archive_name}")
                    digest.update(chunk)
                    output.write(chunk)
            if written != expected_size or digest.hexdigest() != expected_md5:
                raise ZipIntegrityError(f"Extracted file failed size/MD5 verification: {archive_name}")
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        mapping.append({
            "original_name": entry.get("original_name") or Path(archive_name).name,
            "original_path": entry.get("original_path") or archive_name,
            "doc_type": entry.get("doc_type") or "",
            "canonical_name": entry.get("canonical_name") or "",
            "local_name": local_name,
            "file_id": file_id,
            "archive_name": archive_name,
            "mime_type": entry.get("mime_type") or "",
            "size_bytes": expected_size,
            "md5_checksum": expected_md5,
            "is_latest_corrected_excel": entry.get("is_latest_corrected_excel") is True,
        })
        _notify(
            progress, kind="file_complete", index=index, total=total,
            file_id=file_id, original_name=mapping[-1]["original_name"],
            local_name=local_name, doc_type=mapping[-1]["doc_type"], size=expected_size,
            message=f"Verified ZIP file {index} of {total}: {local_name} ({expected_size:,} bytes)",
        )
    return mapping


def _is_junk_zip_member(name):
    lower = name.lower()
    file_name = Path(name).name.lower()
    return (
        lower.startswith("__macosx/")
        or "/__macosx/" in lower
        or file_name.startswith("._")
        or file_name in (".ds_store", "thumbs.db", "desktop.ini")
    )


def _select_latest_excel_entry(excel_entries):
    if len(excel_entries) == 1:
        return excel_entries[0]
    for kw in ("printable", "corrected", "assessment", "survey", "report", "claim"):
        for entry in excel_entries:
            if kw in entry["local_name"].lower():
                return entry
    return max(excel_entries, key=lambda e: e.get("size_bytes", 0))


def _extract_local_case_zip(archive, members, extraction_root, progress):
    extraction_root.mkdir(parents=True, exist_ok=False)
    file_members = [
        (safe_name, member) for safe_name, member in members.values()
        if not member.is_dir() and not _is_junk_zip_member(safe_name)
    ]
    if not file_members:
        raise LocalCaseZipError("Local case ZIP contains no files")

    used_names = set()
    extraction_plan = []
    for safe_name, member in file_members:
        base = flat_name(safe_name)
        local_name = unique_name(base, used_names, safe_name)
        used_names.add(local_name.lower())
        extraction_plan.append((safe_name, member, local_name))

    mapping = []
    total = len(extraction_plan)
    for index, (safe_name, member, local_name) in enumerate(extraction_plan, start=1):
        destination = (extraction_root / local_name).resolve()
        if extraction_root.resolve() not in destination.parents:
            raise UnsafeZipError(f"ZIP destination escapes staging folder: {local_name}")
        temporary = destination.with_name(destination.name + ".download")
        digest = hashlib.md5()
        written = 0
        try:
            with archive.open(member, "r") as source, temporary.open("xb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        mapping.append({
            "original_name": Path(safe_name).name,
            "original_path": safe_name,
            "doc_type": "",
            "canonical_name": "",
            "local_name": local_name,
            "file_id": local_name,
            "archive_name": safe_name,
            "mime_type": "",
            "size_bytes": written,
            "md5_checksum": digest.hexdigest(),
            "is_latest_corrected_excel": False,
        })
        _notify(
            progress, kind="file_complete", index=index, total=total,
            file_id=local_name, original_name=Path(safe_name).name,
            local_name=local_name, doc_type="", size=written,
            message=f"Extracted local ZIP file {index} of {total}: {local_name} ({written:,} bytes)",
        )

    excel_entries = [
        entry for entry in mapping
        if Path(entry["local_name"]).suffix.lower() in EXCEL_SUFFIXES
        and not Path(entry["local_name"]).name.startswith(("~$", "."))
    ]
    if not excel_entries:
        raise LocalCaseZipError("Local case ZIP contains no Excel workbook")

    latest_entry = _select_latest_excel_entry(excel_entries)
    latest_entry["is_latest_corrected_excel"] = True
    return mapping, latest_entry["local_name"]


def _request_zip(client, case_id, dispatch_id, destination, progress):
    body = {"case_id": case_id, "automation_dispatch_id": dispatch_id}
    last_error = None
    for attempt in range(1, 4):
        destination.unlink(missing_ok=True)
        attempt_started = time.monotonic()
        try:
            _notify(progress, kind="zip_start", message=f"Requesting {ZIP_FUNCTION} ZIP (attempt {attempt} of 3)")
            client.call(
                ZIP_FUNCTION, body, destination=destination,
                max_bytes=MAX_COMPRESSED_BYTES,
            )
            if MAX_COMPRESSED_BYTES is not None and destination.stat().st_size > MAX_COMPRESSED_BYTES:
                raise DownloadLimitError(f"ZIP exceeds the {MAX_COMPRESSED_BYTES:,}-byte compressed safety limit")
            _notify(
                progress, kind="progress",
                message=(f"ZIP response received: {destination.stat().st_size:,} bytes in "
                         f"{time.monotonic() - attempt_started:.1f} seconds; validating archive"),
            )
            return
        except Exception as exc:
            destination.unlink(missing_ok=True)
            if _stale(exc) or _fallback_status(exc):
                raise
            last_error = exc
            if not _retryable_zip_request(exc) or attempt == 3:
                raise
            wait_seconds = ZIP_RETRY_DELAYS[attempt - 1]
            _notify(
                progress, kind="warning",
                message=(f"{ZIP_FUNCTION} attempt {attempt} of 3 failed after "
                         f"{time.monotonic() - attempt_started:.1f} seconds "
                         f"({type(exc).__name__}: {exc}). Retrying in {wait_seconds} seconds"),
            )
            getattr(client, "wait_before_retry", time.sleep)(wait_seconds)
    raise last_error


def _confirm_dispatch(client, case_id, dispatch_id):
    matching = next((job for job in client.jobs() if job.get("case_id") == case_id), None)
    if not matching or matching.get("automation_dispatch_id") != dispatch_id:
        raise ApiError(409, ZIP_FUNCTION, "stale_dispatch", "Dispatch changed before fallback")


def _download_fallback_chain(client, case_id, dispatch_id, folder, progress, reason):
    _notify(
        progress, kind="warning",
        message=f"ZIP unavailable ({reason}). Confirming dispatch before parallel-file fallback",
    )
    _confirm_dispatch(client, case_id, dispatch_id)
    _notify(progress, kind="warning", message="Using three-file parallel fallback")
    try:
        return download_case_parallel(
            client,
            case_id,
            folder,
            progress=progress,
            automation_dispatch_id=dispatch_id,
        )
    except ParallelIdentityError:
        raise
    except ApiError as exc:
        if _stale(exc) or exc.status in (401, 403, 409):
            raise
        if exc.status != 429 and exc.status < 500:
            raise
        parallel_error = exc
    except (ParallelDownloadError, requests.exceptions.RequestException) as exc:
        parallel_error = exc

    _notify(
        progress,
        kind="warning",
        message=(
            f"Parallel fallback unavailable ({parallel_error}). "
            "Confirming dispatch before sequential fallback"
        ),
    )
    _confirm_dispatch(client, case_id, dispatch_id)
    _notify(progress, kind="warning", message="Using existing sequential individual-file fallback")
    return download_case(
        client,
        case_id,
        folder,
        progress=progress,
        automation_dispatch_id=dispatch_id,
    )


def _download_zip_case(client, case_id, dispatch_id, folder, progress):
    started = time.monotonic()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    zip_path = folder / "case.zip.download"
    extraction_root = folder / ".zip_extract"
    shutil.rmtree(extraction_root, ignore_errors=True)
    _request_zip(client, case_id, dispatch_id, zip_path, progress)
    verify_started = time.monotonic()
    try:
        if not zipfile.is_zipfile(zip_path):
            raise ZipIntegrityError("Base44 response is not a valid ZIP archive")
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = _inspect_archive(archive)
            manifest_item = members.get("manifest.json")
            if manifest_item and not manifest_item[1].is_dir():
                _manifest, files = _read_embedded_manifest(archive, members, case_id, dispatch_id)
                planned, latest_excel = _plan_files(files, members)
                mapping = _extract_verified(archive, planned, extraction_root, progress)
            else:
                mapping, latest_excel = _extract_local_case_zip(
                    archive, members, extraction_root, progress
                )

        keep_log = folder / "case_activity.log"
        for existing in list(folder.iterdir()):
            if existing == extraction_root or existing == keep_log:
                continue
            if existing.is_dir():
                shutil.rmtree(existing)
            else:
                existing.unlink(missing_ok=True)
        for extracted in extraction_root.iterdir():
            extracted.replace(folder / extracted.name)
        extraction_root.rmdir()
        atomic_json(folder / "web_sync_manifest.json", {
            "case_id": case_id,
            "automation_dispatch_id": dispatch_id,
            "latest_excel": latest_excel,
            "complete": True,
            "download_mode": "zip",
            "files": mapping,
        })
        elapsed = time.monotonic() - started
        _notify(
            progress, kind="complete", total=len(mapping), latest_excel=latest_excel,
            message=(f"ZIP staging complete: {len(mapping)} file(s) verified; "
                     f"archive verification/extraction {time.monotonic() - verify_started:.1f} seconds; "
                     f"total {elapsed:.1f} seconds; latest Excel: {latest_excel}"),
        )
        return latest_excel
    finally:
        zip_path.unlink(missing_ok=True)
        if extraction_root.exists():
            shutil.rmtree(extraction_root, ignore_errors=True)


def download_case_preferred(client, case_id, folder, progress=None, automation_dispatch_id=None):
    """Use one verified ZIP when possible and preserve individual fallback."""
    dispatch_id = str(automation_dispatch_id or "").strip()
    if not dispatch_id:
        raise ValueError("Download requires automation_dispatch_id")
    if DOWNLOAD_MODE == "individual":
        _notify(progress, kind="progress", message="Download mode: individual rollback")
        return download_case(
            client, case_id, folder, progress=progress,
            automation_dispatch_id=dispatch_id,
        )
    if DOWNLOAD_MODE != "zip_preferred":
        raise ValueError(f"Unsupported APP3_DOWNLOAD_MODE: {DOWNLOAD_MODE}")

    # Fallback intentionally disabled for both Local and Drive cases, even
    # after ZIP retries or a corrupt/unsupported ZIP. Such a transfer fails
    # and is reported through the existing failed-receipt flow.
    # - Local cases: Base44 delivers stored case ZIPs and does not support individual-file downloads (HTTP 409).
    # - Drive cases: Delivered as full verified ZIP archives; individual-file fallback is not used.
    # The complete fallback chain (_download_fallback_chain, parallel, sequential) is preserved below
    # intact without deletion, and can be activated if APP3_ENABLE_ZIP_FALLBACK=1 is explicitly set.
    if not ENABLE_FALLBACK:
        return _download_zip_case(client, case_id, dispatch_id, folder, progress)

    try:
        return _download_zip_case(client, case_id, dispatch_id, folder, progress)
    except (ZipIdentityError, UnsafeZipError, LocalCaseZipError):
        raise
    except ApiError as exc:
        if _stale(exc) or exc.status == 401:
            raise
        if not (_fallback_status(exc) or exc.status >= 500):
            raise
        reason = str(exc)
    except (DownloadLimitError, ZipIntegrityError, zipfile.BadZipFile, requests.exceptions.RequestException) as exc:
        reason = str(exc)
    return _download_fallback_chain(client, case_id, dispatch_id, folder, progress, reason)
