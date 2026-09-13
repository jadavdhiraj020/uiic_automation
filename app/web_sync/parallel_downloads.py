"""Bounded parallel Web Sync downloader used between ZIP and sequential modes."""
from contextlib import nullcontext
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
import json
import logging
from pathlib import Path
import threading
import time
from urllib.parse import unquote

import requests

from .client import ApiError
from .downloads import FileIntegrityError, _file_integrity, _matches_integrity
from .manifest import latest_corrected, plan_local_files
from .storage import atomic_json


logger = logging.getLogger(__name__)
MAX_WORKERS = 3
RETRY_DELAYS = (3, 7)


class ParallelDownloadError(RuntimeError):
    """Parallel transfer failed and may be retried by the sequential fallback."""


class ParallelIdentityError(ValueError):
    """The manifest belongs to another case or dispatch; fallback is forbidden."""


class ParallelCancelledError(RuntimeError):
    """A sibling worker stopped this transfer before local promotion."""


def _notify(progress, **event):
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        logger.exception("Parallel Web Sync progress callback failed")


def _stale(error):
    return bool(
        isinstance(error, ApiError)
        and error.status == 409
        and str(getattr(error, "code", "")).strip().lower() == "stale_dispatch"
    )


def _retryable(error):
    return bool(
        isinstance(error, (requests.exceptions.RequestException, FileIntegrityError))
        or (isinstance(error, ApiError) and (error.status == 429 or error.status >= 500))
    )


def _load_prior_mapping(folder, case_id, dispatch_id):
    try:
        manifest = json.loads((folder / "web_sync_manifest.json").read_text(encoding="utf-8"))
        if manifest.get("case_id") != case_id or manifest.get("automation_dispatch_id") != dispatch_id:
            return {}
        return {
            item.get("file_id"): item
            for item in manifest.get("files", [])
            if isinstance(item, dict) and item.get("file_id")
        }
    except (OSError, ValueError, AttributeError):
        return {}


def _plan_files(manifest, case_id, dispatch_id):
    if manifest.get("case_id") != case_id:
        raise ParallelIdentityError("Manifest case_id does not match the requested case")
    if manifest.get("automation_dispatch_id") != dispatch_id:
        raise ParallelIdentityError("Manifest automation_dispatch_id does not match the requested dispatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Manifest contains no files")
    latest_entry = latest_corrected(
        files,
        manifest.get("latest_corrected_excel", {}).get("file_id"),
    )

    def photo_fallback(_entry, file_id, canonical_name):
            logger.warning(
                "Ignored scanner-incompatible photo canonical_name %s for %s; using original filename",
                canonical_name,
                file_id,
            )

    def collision(requested_name, file_id, local_name):
        logger.warning("Web Sync filename collision for %s (%s); saved as %s", requested_name, file_id, local_name)

    def excel_renamed(_entry, file_id, local_name):
        logger.warning("Unflagged Excel %s requested the latest workbook name; saved as %s", file_id, local_name)

    return plan_local_files(
        files,
        latest_entry,
        fallback_name=lambda entry: entry.get("name") or entry.get("path") or "",
        file_id=lambda entry: entry.get("file_id"),
        on_photo_fallback=photo_fallback,
        on_collision=collision,
        on_excel_renamed=excel_renamed,
    )


def _mapping(item, remote_path):
    entry = item["entry"]
    return {
        "original_name": entry.get("name") or "",
        "original_path": entry.get("path") or "",
        "doc_type": entry.get("doc_type") or "",
        "canonical_name": entry.get("canonical_name") or "",
        "local_name": item["local_name"],
        "file_id": item["file_id"],
        "remote_path": remote_path,
        "size_bytes": item["expected_size"],
        "md5_checksum": item["expected_md5"],
    }


def _download_one(client, request_identity, folder, item, stop_event, progress):
    if stop_event.is_set():
        raise ParallelCancelledError("Parallel transfer cancelled")
    entry = item["entry"]
    file_id = item["file_id"]
    local_name = item["local_name"]
    target = folder / local_name
    temporary = folder / f"{local_name}.download"
    _notify(
        progress,
        kind="file_start",
        index=item["index"],
        total=item["total"],
        file_id=file_id,
        original_name=entry.get("name") or "",
        local_name=local_name,
        doc_type=entry.get("doc_type") or "",
        message=f"Parallel download {item['index']} of {item['total']}: {local_name}",
    )
    headers = {}
    for attempt in range(1, 4):
        if stop_event.is_set():
            temporary.unlink(missing_ok=True)
            raise ParallelCancelledError("Parallel transfer cancelled")
        temporary.unlink(missing_ok=True)
        try:
            slot = getattr(client, "individual_download_slot", None)
            with (slot() if slot else nullcontext()):
                headers = client.call(
                    "getAutomationCaseFiles",
                    {**request_identity, "file_id": file_id},
                    destination=temporary,
                )
            actual = _file_integrity(temporary)
            expected = (item["expected_size"], item["expected_md5"])
            if actual != expected:
                raise FileIntegrityError(
                    f"integrity mismatch: expected {expected[0]} bytes/{expected[1]}, "
                    f"received {actual[0]} bytes/{actual[1]}"
                )
            if stop_event.is_set():
                raise ParallelCancelledError("Parallel transfer cancelled")
            temporary.replace(target)
            return _mapping(
                item,
                unquote(headers.get("X-Case-File-Path", entry.get("path") or local_name)),
            )
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if _stale(exc):
                stop_event.set()
                raise
            if isinstance(exc, ApiError) and exc.status in (401, 403, 409):
                stop_event.set()
                raise
            if isinstance(exc, ParallelCancelledError):
                raise
            if _retryable(exc) and attempt < 3:
                wait_seconds = RETRY_DELAYS[attempt - 1]
                _notify(
                    progress,
                    kind="warning",
                    index=item["index"],
                    total=item["total"],
                    file_id=file_id,
                    local_name=local_name,
                    message=(
                        f"Parallel attempt {attempt} of 3 failed for {local_name}: {exc}. "
                        f"Retrying in {wait_seconds} seconds"
                    ),
                )
                getattr(client, "wait_before_retry", time.sleep)(wait_seconds)
                continue
            raise ParallelDownloadError(
                f"Parallel download failed after {attempt} attempt(s) for {local_name}: {exc}"
            ) from exc
    raise ParallelDownloadError(f"Parallel download failed for {local_name}")


def download_case_parallel(
    client,
    case_id,
    folder,
    progress=None,
    automation_dispatch_id=None,
    max_workers=MAX_WORKERS,
):
    """Download one manifest with at most three concurrent verified file transfers."""
    dispatch_id = str(automation_dispatch_id or "").strip()
    if not dispatch_id:
        raise ValueError("Download requires automation_dispatch_id")
    workers = int(max_workers)
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"Parallel workers must be between 1 and {MAX_WORKERS}")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    request_identity = {"case_id": case_id, "automation_dispatch_id": dispatch_id}
    _notify(progress, kind="manifest_start", message="Requesting manifest for parallel fallback")
    manifest = client.call("getAutomationCaseFiles", request_identity)
    planned, latest_name = _plan_files(manifest, case_id, dispatch_id)
    _notify(
        progress,
        kind="manifest_ready",
        total=len(planned),
        message=f"Parallel fallback manifest received: {len(planned)} file(s)",
    )

    prior = _load_prior_mapping(folder, case_id, dispatch_id)
    completed = {}

    def save_manifest(complete=False):
        ordered = [completed[item["file_id"]] for item in planned if item["file_id"] in completed]
        atomic_json(folder / "web_sync_manifest.json", {
            "case_id": case_id,
            "automation_dispatch_id": dispatch_id,
            "latest_excel": latest_name,
            "complete": bool(complete),
            "download_mode": "parallel_individual",
            "files": ordered,
        })

    pending = []
    for item in planned:
        target = folder / item["local_name"]
        previous = prior.get(item["file_id"], {})
        if _matches_integrity(target, item["expected_size"], item["expected_md5"]):
            completed[item["file_id"]] = _mapping(
                item,
                previous.get("remote_path") or item["entry"].get("path") or item["local_name"],
            )
            _notify(
                progress,
                kind="file_skipped",
                index=item["index"],
                total=item["total"],
                file_id=item["file_id"],
                local_name=item["local_name"],
                message=f"Verified existing file; parallel download skipped: {item['local_name']}",
            )
        else:
            target.unlink(missing_ok=True)
            pending.append(item)
    save_manifest(False)

    stop_event = threading.Event()
    errors = []
    if pending:
        with ThreadPoolExecutor(
            max_workers=min(workers, len(pending)),
            thread_name_prefix="web-sync-file",
        ) as executor:
            futures = {
                executor.submit(
                    _download_one,
                    client,
                    request_identity,
                    folder,
                    item,
                    stop_event,
                    progress,
                ): item
                for item in pending
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                except CancelledError:
                    continue
                except Exception as exc:
                    errors.append(exc)
                    if len(errors) == 1:
                        stop_event.set()
                        for other in futures:
                            if other is not future:
                                other.cancel()
                else:
                    if not errors:
                        completed[result["file_id"]] = result
                        save_manifest(False)
                        _notify(
                            progress,
                            kind="file_complete",
                            index=futures[future]["index"],
                            total=futures[future]["total"],
                            file_id=result["file_id"],
                            local_name=result["local_name"],
                            size=result["size_bytes"],
                            message=f"Parallel download verified: {result['local_name']}",
                        )
    if errors:
        protected_error = next(
            (
                error for error in errors
                if isinstance(error, ParallelIdentityError)
                or (
                    isinstance(error, ApiError)
                    and (_stale(error) or error.status in (401, 403, 409))
                )
            ),
            None,
        )
        substantive_error = next(
            (error for error in errors if not isinstance(error, ParallelCancelledError)),
            None,
        )
        raise protected_error or substantive_error or errors[0]
    if len(completed) != len(planned):
        raise ParallelDownloadError("Parallel download ended before every file was verified")
    save_manifest(True)
    _notify(
        progress,
        kind="complete",
        total=len(planned),
        latest_excel=latest_name,
        message=f"Parallel fallback complete: {len(planned)} file(s) verified",
    )
    return latest_name
