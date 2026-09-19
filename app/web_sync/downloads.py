"""Stage every manifest file as binary into one flat folder."""
from contextlib import nullcontext
import json
import logging
from pathlib import Path
import time
from urllib.parse import unquote

import requests

from .client import ApiError
from .manifest import (
    file_integrity as _file_integrity,
    flat_name,
    latest_corrected,
    matches_integrity as _matches_integrity,
    plan_local_files,
    safe_canonical_name,
)
from .storage import atomic_json


logger = logging.getLogger(__name__)
RETRY_DELAYS = (3, 7)


class FileIntegrityError(ValueError):
    pass


def _notify(progress, **event):
    """Report optional download progress without allowing logging to break a download."""
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        logger.exception("Web Sync download progress callback failed")


def _retryable_file_error(error):
    return bool(
        isinstance(error, (requests.exceptions.RequestException, FileIntegrityError))
        or (isinstance(error, ApiError) and error.status >= 500)
    )


def download_case(client, case_id, folder, progress=None, automation_dispatch_id=None):
    if not isinstance(automation_dispatch_id, str) or not automation_dispatch_id.strip():
        raise ValueError("Download requires automation_dispatch_id")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    _notify(progress, kind="manifest_start", message="Requesting the Base44 file manifest")
    request_identity = {
        "case_id": case_id,
        "automation_dispatch_id": automation_dispatch_id,
    }
    manifest = client.call("getAutomationCaseFiles", request_identity)
    if manifest.get("case_id") != case_id:
        raise ValueError("Manifest case_id mismatch")
    if manifest.get("automation_dispatch_id") and manifest.get("automation_dispatch_id") != automation_dispatch_id:
        raise ValueError("Manifest automation_dispatch_id mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Manifest contains no files")
    latest = latest_corrected(files, manifest.get("latest_corrected_excel", {}).get("file_id"))
    _notify(
        progress, kind="manifest_ready", total=len(files),
        message=f"File manifest received: {len(files)} file(s) to download",
    )
    prior_mapping = {}
    prior_manifest_path = folder / "web_sync_manifest.json"
    try:
        prior_manifest = json.loads(prior_manifest_path.read_text(encoding="utf-8"))
        if (
            prior_manifest.get("case_id") == case_id
            and prior_manifest.get("automation_dispatch_id") == automation_dispatch_id
        ):
            prior_mapping = {
                item.get("file_id"): item for item in prior_manifest.get("files", [])
                if isinstance(item, dict) and item.get("file_id")
            }
    except (OSError, ValueError, AttributeError):
        pass

    total_files = len(files)
    def photo_fallback(entry, file_id, canonical_name):
        logger.warning(
            "Ignored scanner-incompatible photo canonical_name %s for %s; using original filename",
            canonical_name, file_id,
        )
        _notify(
            progress, kind="warning", total=total_files,
            file_id=file_id, original_name=entry.get("name") or "",
            message=(
                f"Photo filename kept scanner-compatible: ignored canonical name "
                f"{canonical_name!r} and used the original filename"
            ),
        )

    def collision(requested_name, file_id, name):
        logger.warning("Web Sync filename collision for %s (%s); saved as %s", requested_name, file_id, name)
        _notify(
            progress, kind="warning", total=total_files,
            file_id=file_id, local_name=name,
            message=f"Filename collision: {requested_name} saved safely as {name}",
        )

    def excel_renamed(_entry, file_id, name):
        logger.warning("Unflagged Excel %s requested the latest workbook name; saved as %s", file_id, name)

    planned, latest_name = plan_local_files(
        files,
        latest,
        fallback_name=lambda entry: entry.get("name") or entry.get("path") or "",
        file_id=lambda entry: entry.get("file_id"),
        on_photo_fallback=photo_fallback,
        on_collision=collision,
        on_excel_renamed=excel_renamed,
    )
    mapping = []

    def save_manifest(complete=False):
        atomic_json(folder / "web_sync_manifest.json", {
            "case_id": case_id,
            "automation_dispatch_id": automation_dispatch_id,
            "latest_excel": latest_name,
            "complete": bool(complete),
            "files": mapping,
        })

    save_manifest(False)
    for item in planned:
        index, entry, name = item["index"], item["entry"], item["local_name"]
        expected_size, expected_md5 = item["expected_size"], item["expected_md5"]
        file_id = item["file_id"]
        original_name = entry.get("name") or ""
        original_path = entry.get("path") or ""
        canonical_name = entry.get("canonical_name") or ""
        target = folder / name
        previous = prior_mapping.get(file_id, {})
        remote_path = previous.get("remote_path") or original_path or name
        item_mapping = {
            "original_name": original_name,
            "original_path": original_path,
            "doc_type": entry.get("doc_type") or "",
            "canonical_name": canonical_name,
            "local_name": name,
            "file_id": file_id,
            "remote_path": remote_path,
            "size_bytes": expected_size,
            "md5_checksum": expected_md5,
        }
        if _matches_integrity(target, expected_size, expected_md5):
            mapping.append(item_mapping)
            save_manifest(False)
            _notify(
                progress, kind="file_skipped", index=index, total=total_files,
                file_id=file_id, original_name=original_name, local_name=name,
                doc_type=entry.get("doc_type") or "", size=expected_size,
                message=f"Verified existing file {index} of {total_files}; download skipped: {name}",
            )
            continue
        if target.exists():
            target.unlink()

        temporary = folder / (name + ".download")
        _notify(
            progress, kind="file_start", index=index, total=total_files,
            file_id=file_id, original_name=original_name, local_name=name,
            doc_type=entry.get("doc_type") or "",
            message=f"Downloading file {index} of {total_files}: {name}",
        )
        headers = {}
        for attempt in range(1, 4):
            temporary.unlink(missing_ok=True)
            try:
                slot = getattr(client, "individual_download_slot", None)
                with (slot() if slot else nullcontext()):
                    headers = client.call(
                        "getAutomationCaseFiles",
                        {**request_identity, "file_id": file_id},
                        destination=temporary,
                    )
                actual_size, actual_md5 = _file_integrity(temporary)
                if (actual_size, actual_md5) != (expected_size, expected_md5):
                    raise FileIntegrityError(
                        f"integrity mismatch: expected {expected_size} bytes/{expected_md5}, "
                        f"received {actual_size} bytes/{actual_md5}"
                    )
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                if _retryable_file_error(exc) and attempt < 3:
                    wait_seconds = RETRY_DELAYS[attempt - 1]
                    _notify(
                        progress, kind="warning", index=index, total=total_files,
                        file_id=file_id, original_name=original_name, local_name=name,
                        message=(
                            f"Download attempt {attempt} of 3 failed for {name}: {exc}. "
                            f"Retrying the same file in {wait_seconds} seconds"
                        ),
                    )
                    getattr(client, "wait_before_retry", time.sleep)(wait_seconds)
                    continue
                _notify(
                    progress, kind="file_error", index=index, total=total_files,
                    file_id=file_id, original_name=original_name, local_name=name,
                    message=f"Download failed after {attempt} attempt(s) for file {index} of {total_files}: {name} — {exc}",
                )
                raise
            else:
                break
        # Keep the manifest basename stable for scanner matching. Remote paths
        # are decoded for provenance only and never joined onto the local root.
        remote_path = unquote(headers.get("X-Case-File-Path", original_path or name))
        temporary.replace(target)
        item_mapping["remote_path"] = remote_path
        mapping.append(item_mapping)
        save_manifest(False)
        _notify(
            progress, kind="file_complete", index=index, total=total_files,
            file_id=file_id, original_name=original_name, local_name=name,
            doc_type=entry.get("doc_type") or "", size=expected_size,
            message=f"Downloaded file {index} of {total_files}: {name} ({expected_size:,} bytes)",
        )
    save_manifest(True)
    _notify(
        progress, kind="complete", total=total_files, latest_excel=latest_name,
        message=f"Download complete: {total_files} file(s) saved; latest Excel: {latest_name}",
    )
    return latest_name
