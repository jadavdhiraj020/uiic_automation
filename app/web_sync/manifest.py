"""Shared manifest validation and deterministic local filename planning."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote


EXCEL_SUFFIXES = (".xlsx", ".xls", ".xlsm")


class StagedCaseValidationError(ValueError):
    """The promoted local case no longer matches its verified manifest."""


def flat_name(value):
    name = unquote(str(value)).replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    if not name or name in (".", ".."):
        raise ValueError("File has no usable local name")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
    if name.split(".")[0].upper() in reserved:
        name = "_" + name
    if len(name) > 160:
        name = name[:120] + hashlib.sha256(name.encode()).hexdigest()[:12] + Path(name).suffix
    return name


def safe_canonical_name(value):
    if not isinstance(value, str) or not value.strip():
        return None
    decoded = unquote(value.strip())
    if "/" in decoded or "\\" in decoded or decoded in (".", ".."):
        return None
    try:
        safe = flat_name(decoded)
    except ValueError:
        return None
    return safe if safe == decoded else None


def is_photo(entry):
    doc_type = str(entry.get("doc_type") or "").lower()
    return "photo" in doc_type or "vehicle_image" in doc_type


def photo_compatible(name):
    normalized = name.lower().replace(" ", "_").replace("-", "_")
    return normalized.startswith(("photo_sheet", "vehicle", "vehical"))


def integrity(entry):
    size = entry.get("size_bytes")
    checksum = str(entry.get("md5_checksum") or "").strip().lower()
    if isinstance(size, bool):
        raise ValueError("Manifest file has invalid size_bytes")
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise ValueError("Manifest file is missing valid size_bytes") from None
    if size < 0 or not re.fullmatch(r"[0-9a-f]{32}", checksum):
        raise ValueError("Manifest file is missing valid size_bytes/md5_checksum")
    return size, checksum


def file_integrity(path):
    """Return a local file's exact byte count and MD5 digest."""
    digest = hashlib.md5()
    size = 0
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def matches_integrity(path, expected_size, expected_md5):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != expected_size:
        return False
    return file_integrity(path) == (expected_size, expected_md5)


def validate_staged_case(folder, case_id, automation_dispatch_id, latest_excel, *, verify_md5=False):
    """Validate one promoted flat case folder without changing any files."""
    folder = Path(folder or "")
    if not folder.is_dir():
        raise StagedCaseValidationError("local case folder is missing")
    manifest_path = folder / "web_sync_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StagedCaseValidationError(f"local manifest cannot be read: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("complete") is not True:
        raise StagedCaseValidationError("local manifest is not marked complete")
    if manifest.get("case_id") != case_id:
        raise StagedCaseValidationError("local manifest case_id does not match this case")
    if not automation_dispatch_id or manifest.get("automation_dispatch_id") != automation_dispatch_id:
        raise StagedCaseValidationError("local manifest dispatch does not match this case")
    if not isinstance(latest_excel, str) or not latest_excel:
        raise StagedCaseValidationError("latest corrected Excel is not recorded")

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise StagedCaseValidationError("local manifest contains no files")
    seen = set()
    latest_seen = False
    for entry in entries:
        if not isinstance(entry, dict):
            raise StagedCaseValidationError("local manifest contains an invalid file entry")
        local_name = entry.get("local_name")
        if (
            not isinstance(local_name, str) or not local_name
            or Path(local_name).name != local_name or "/" in local_name or "\\" in local_name
        ):
            raise StagedCaseValidationError("local manifest contains an unsafe filename")
        folded = local_name.casefold()
        if folded in seen:
            raise StagedCaseValidationError(f"local manifest repeats filename {local_name}")
        seen.add(folded)
        latest_seen = latest_seen or folded == latest_excel.casefold()
        try:
            expected_size, expected_md5 = integrity(entry)
        except ValueError as exc:
            raise StagedCaseValidationError(f"{local_name}: {exc}") from exc
        path = folder / local_name
        if not path.is_file():
            raise StagedCaseValidationError(f"required staged file is missing: {local_name}")
        if path.stat().st_size != expected_size:
            raise StagedCaseValidationError(f"staged file size changed: {local_name}")
        if verify_md5 and file_integrity(path)[1] != expected_md5:
            raise StagedCaseValidationError(f"staged file checksum changed: {local_name}")

    if not latest_seen or Path(latest_excel).suffix.lower() not in EXCEL_SUFFIXES:
        raise StagedCaseValidationError("latest corrected Excel does not match the completed manifest")
    return manifest


def unique_name(name, used, file_id, on_collision=None):
    candidate = name
    number = 2
    while candidate.lower() in used or candidate.lower() == "web_sync_manifest.json":
        candidate = f"{Path(name).stem}__{number}{Path(name).suffix}"
        number += 1
    if candidate != name and on_collision:
        on_collision(name, file_id, candidate)
    return candidate


def latest_corrected(files, expected_file_id=None):
    latest = [entry for entry in files if isinstance(entry, dict) and entry.get("is_latest_corrected_excel") is True]
    if len(latest) != 1:
        raise ValueError("Manifest must identify exactly one latest corrected Excel")
    if expected_file_id is not None and latest[0].get("file_id") != expected_file_id:
        raise ValueError("Manifest latest corrected Excel identity does not match")
    return latest[0]


def plan_local_files(
    files, latest_entry, *, fallback_name, file_id,
    on_photo_fallback=None, on_collision=None, on_excel_renamed=None,
):
    """Return one deterministic flat-folder plan shared by every transport."""
    latest_canonical = safe_canonical_name(latest_entry.get("canonical_name"))
    used_names, file_ids, planned = set(), set(), []
    for index, entry in enumerate(files, start=1):
        if not isinstance(entry, dict):
            raise ValueError("Manifest contains an invalid file entry")
        entry_file_id = str(file_id(entry) or "").strip()
        if not entry_file_id or entry_file_id in file_ids:
            raise ValueError("Missing or duplicate file_id")
        file_ids.add(entry_file_id)
        canonical = entry.get("canonical_name") or ""
        safe_canonical = safe_canonical_name(canonical)
        if safe_canonical and is_photo(entry) and not photo_compatible(safe_canonical):
            if on_photo_fallback:
                on_photo_fallback(entry, entry_file_id, canonical)
            safe_canonical = None
        requested = safe_canonical or flat_name(fallback_name(entry))
        if (
            entry is not latest_entry and latest_canonical
            and requested.lower() == latest_canonical.lower()
            and Path(requested).suffix.lower() in EXCEL_SUFFIXES
        ):
            requested = f"websync_attachment_{hashlib.sha256(entry_file_id.encode()).hexdigest()[:12]}{Path(requested).suffix}"
            if on_excel_renamed:
                on_excel_renamed(entry, entry_file_id, requested)
        local_name = unique_name(requested, used_names, entry_file_id, on_collision)
        used_names.add(local_name.lower())
        expected_size, expected_md5 = integrity(entry)
        if entry is latest_entry and Path(local_name).suffix.lower() not in EXCEL_SUFFIXES:
            raise ValueError("Latest corrected file is not an Excel workbook")
        planned.append({
            "index": index, "total": len(files), "entry": entry,
            "file_id": entry_file_id, "local_name": local_name,
            "expected_size": expected_size, "expected_md5": expected_md5,
            "is_latest": entry is latest_entry,
        })
    return planned, next(item["local_name"] for item in planned if item["is_latest"])
