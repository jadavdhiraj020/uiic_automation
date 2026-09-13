"""Production-safety coverage for bounded parallel Web Sync fallback."""
import hashlib
import json
from pathlib import Path
import threading
import time

import pytest

from app.web_sync.client import ApiError
import app.web_sync.parallel_downloads as parallel_downloads


CASE_ID = "parallel-case"
DISPATCH_ID = "parallel-dispatch"


def _files(count=7):
    values = []
    for index in range(count):
        payload = f"payload-{index}".encode()
        extension = ".xlsx" if index == 0 else ".pdf"
        entry = {
            "file_id": f"file-{index}",
            "name": f"source-{index}{extension}",
            "path": f"Drive/source-{index}{extension}",
            "canonical_name": "corrected_claim.xlsx" if index == 0 else f"document-{index}.pdf",
            "doc_type": "CORRECTED_EXCEL" if index == 0 else "DOCUMENT",
            "is_latest_corrected_excel": index == 0,
            "size_bytes": len(payload),
            "md5_checksum": hashlib.md5(payload).hexdigest(),
        }
        values.append((entry, payload))
    return values


class ParallelClient:
    def __init__(self, files=None):
        self.files = files or _files()
        self.attempts = {entry["file_id"]: 0 for entry, _payload in self.files}
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.failures = {}

    def call(self, function, body, destination=None):
        assert function == "getAutomationCaseFiles"
        if destination is None:
            entries = [entry for entry, _payload in self.files]
            return {
                "case_id": CASE_ID,
                "automation_dispatch_id": DISPATCH_ID,
                "latest_corrected_excel": entries[0],
                "files": entries,
            }
        file_id = body["file_id"]
        self.attempts[file_id] += 1
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.015)
            failure = self.failures.get(file_id)
            if callable(failure):
                failure = failure(self.attempts[file_id])
            if failure:
                if isinstance(failure, Exception):
                    raise failure
                Path(destination).write_bytes(failure)
            else:
                payload = next(payload for entry, payload in self.files if entry["file_id"] == file_id)
                Path(destination).write_bytes(payload)
            return {"X-Case-File-Path": f"Drive/{file_id}"}
        finally:
            with self.lock:
                self.active -= 1


def test_parallel_download_is_bounded_verified_and_deterministic(tmp_path):
    client = ParallelClient()
    latest = parallel_downloads.download_case_parallel(
        client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    )
    audit = json.loads((tmp_path / "web_sync_manifest.json").read_text(encoding="utf-8"))
    assert latest == "corrected_claim.xlsx"
    assert client.max_active == 3
    assert audit["complete"] is True
    assert audit["download_mode"] == "parallel_individual"
    assert [item["file_id"] for item in audit["files"]] == [
        entry["file_id"] for entry, _payload in client.files
    ]
    for item in audit["files"]:
        local = tmp_path / item["local_name"]
        assert local.stat().st_size == item["size_bytes"]
        assert hashlib.md5(local.read_bytes()).hexdigest() == item["md5_checksum"]


def test_parallel_integrity_failure_retries_only_same_file(tmp_path, monkeypatch):
    monkeypatch.setattr(parallel_downloads, "RETRY_DELAYS", (0, 0))
    client = ParallelClient(_files(3))
    client.failures["file-1"] = lambda attempt: b"bad" if attempt == 1 else None
    parallel_downloads.download_case_parallel(
        client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    )
    assert client.attempts == {"file-0": 1, "file-1": 2, "file-2": 1}


def test_parallel_resume_skips_valid_existing_file(tmp_path):
    files = _files(3)
    first_entry, first_payload = files[0]
    (tmp_path / "corrected_claim.xlsx").write_bytes(first_payload)
    (tmp_path / "web_sync_manifest.json").write_text(json.dumps({
        "case_id": CASE_ID,
        "automation_dispatch_id": DISPATCH_ID,
        "latest_excel": "corrected_claim.xlsx",
        "complete": False,
        "files": [{"file_id": first_entry["file_id"], "remote_path": first_entry["path"]}],
    }), encoding="utf-8")
    client = ParallelClient(files)
    parallel_downloads.download_case_parallel(
        client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
    )
    assert client.attempts == {"file-0": 0, "file-1": 1, "file-2": 1}


def test_parallel_stale_dispatch_stops_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(parallel_downloads, "RETRY_DELAYS", (0, 0))
    client = ParallelClient(_files(3))
    stale = ApiError(409, "getAutomationCaseFiles", "stale_dispatch")
    client.failures["file-0"] = stale
    with pytest.raises(ApiError) as caught:
        parallel_downloads.download_case_parallel(
            client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
        )
    assert caught.value is stale
    audit = json.loads((tmp_path / "web_sync_manifest.json").read_text(encoding="utf-8"))
    assert audit["complete"] is False
    assert not list(tmp_path.glob("*.download"))


@pytest.mark.parametrize(
    "case_id,dispatch_id",
    [("wrong-case", DISPATCH_ID), (CASE_ID, "wrong-dispatch")],
)
def test_parallel_rejects_wrong_manifest_identity(tmp_path, case_id, dispatch_id):
    client = ParallelClient(_files(2))
    original = client.call

    def wrong_manifest(function, body, destination=None):
        value = original(function, body, destination)
        if destination is None:
            value["case_id"] = case_id
            value["automation_dispatch_id"] = dispatch_id
        return value

    client.call = wrong_manifest
    with pytest.raises(parallel_downloads.ParallelIdentityError):
        parallel_downloads.download_case_parallel(
            client, CASE_ID, tmp_path, automation_dispatch_id=DISPATCH_ID,
        )
