from __future__ import annotations
from app.automation.services.pdf_merge_service import PdfMergeService, MergeConfig

import asyncio
import logging
import os
import random
import re
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts
from app.data.data_model import ClaimData
from app.utils import load_automation_defaults
from app.portals.oic.automation.ui_utils import (
    upload_file_via_input,
    capture_error_screenshot,
)
from app.portals.oic.automation import selectors as S
from app.portals.oic.automation.popup_service import dismiss_portal_popup

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024   # 5 MB portal limit per file
_DL_MAX_FILE_BYTES = 10 * 1024 * 1024       # 10 MB for Driving License
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_UPLOADABLE_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"}

# Section definitions: (section_num, label, selector, required, source_priority)
_UPLOAD_SECTIONS = [
    (1, "Workshop Repair Estimate", S.SEL_UPLOAD_WORKSHOP_ESTIMATE, True),
    (2, "Discharge cum Satisfaction Voucher", S.SEL_UPLOAD_DISCHARGE_VOUCHER, True),
    (3, "Invoice", S.SEL_UPLOAD_INVOICE, True),
    (4, "Re-Inspection Report", S.SEL_UPLOAD_REINSPECTION, False),
    # Section 5 (DL) and 6 (Photographs) handled separately
    # Section 7 (Other Docs) handled separately
]


# ══════════════════════════════════════════════════════════════════════════════
# FILE RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_file(
    data: ClaimData,
    *keys: str,
    pools: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Resolve a file path from multiple data pools in priority order.

    Args:
        data: The ClaimData instance.
        *keys: One or more mapping keys to try (e.g. "workshop_estimate", "invoice").
        pools: List of attribute names to search, in order.
               Defaults to ["upload_doc_files", "assessment_files", "claim_doc_files"].

    Returns:
        The first valid file path found, or None.
    """
    if pools is None:
        pools = ["upload_doc_files", "assessment_files", "claim_doc_files"]

    for pool_name in pools:
        pool: Dict[str, str] = getattr(data, pool_name, {}) or {}
        for key in keys:
            fpath = pool.get(key, "")
            if fpath and os.path.isfile(fpath):
                return fpath
    return None


def _find_first_vehicle_photo(data: ClaimData) -> Optional[str]:
    """Find the first vehicle photo file (jpg/png) in the claim folder."""
    folder = PdfMergeService.get_folder_path(data)
    if not folder or not os.path.isdir(folder):
        return None

    # Priority 1: Look for vehicle_photo_1.* files
    for fname in sorted(os.listdir(folder)):
        if fname.lower().startswith("vehicle_photo_1"):
            ext = Path(fname).suffix.lower()
            if ext in _PHOTO_EXTENSIONS:
                return os.path.join(folder, fname)

    # Priority 2: Any vehicle photo
    for fname in sorted(os.listdir(folder)):
        fname_lower = fname.lower()
        if ("vehicle" in fname_lower or "vehical" in fname_lower or "photo" in fname_lower):
            ext = Path(fname).suffix.lower()
            if ext in _PHOTO_EXTENSIONS:
                return os.path.join(folder, fname)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# COMPRESSION HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _compress_if_needed(
    file_path: str,
    label: str,
    log: AutomationLogger,
    limit_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> str:
    """
    Compress a file if it exceeds the portal's per-file limit.
    Returns the (possibly compressed) file path.
    """
    if not file_path or not os.path.isfile(file_path):
        return file_path

    file_size = os.path.getsize(file_path)
    if file_size <= limit_bytes:
        return file_path

    from app.data.folder_scanner import _compress_pdf_for_upload, _compress_image_for_upload

    ext = Path(file_path).suffix.lower()
    size_kb = file_size / 1024
    limit_kb = limit_bytes / 1024
    log.warning(f"{label}: {size_kb:.0f} KB > {limit_kb:.0f} KB limit — compressing...")

    try:
        suffix = ext if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp") else ".pdf"
        tmp = tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False, prefix=f"_oic_upload_{Path(file_path).stem}_"
        )
        tmp.close()
        out_path = tmp.name

        if ext == ".pdf":
            ok = _compress_pdf_for_upload(file_path, out_path)
        elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp"):
            ok = _compress_image_for_upload(file_path, out_path)
        else:
            ok = False

        if ok and os.path.isfile(out_path):
            comp_kb = os.path.getsize(out_path) / 1024
            log.success(f"{label}: compressed to {comp_kb:.0f} KB")
            return out_path
        else:
            log.warning(f"{label}: compression failed — using original file")
            return file_path

    except Exception as exc:
        log.warning(f"{label}: compression error ({exc}) — using original file")
        return file_path

# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL SECTION HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def _upload_section(
    page: Page,
    section_num: int,
    label: str,
    selector: str,
    file_path: Optional[str],
    required: bool,
    log: AutomationLogger,
    used_files: Set[str],
    max_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> bool:
    """Upload a file for a single numbered section. Returns True if file was uploaded."""
    log.info(f"▸ Section {section_num}: {label}")

    if not file_path:
        if required:
            log.warning(f"  Section {section_num} ({label}): REQUIRED but no file found — skipping")
        else:
            log.info(f"  Section {section_num} ({label}): Optional, no file found — skipping")
        return False

    # Track used file
    used_files.add(os.path.normpath(file_path))

    # Compress if oversized
    upload_path = _compress_if_needed(file_path, label, log, limit_bytes=max_bytes)

    # Locate and upload (no scroll on hidden input)
    try:
        file_input = page.locator(selector).first
        await asyncio.sleep(random.uniform(0.3, 0.7))

        success = await upload_file_via_input(
            page,
            file_input_selector=selector,
            file_path=upload_path,
            label=f"Section {section_num} ({label})",
            log=log,
        )

        if success:
            log.success(f"  Section {section_num} ({label}): uploaded '{Path(upload_path).name}'")
        else:
            log.warning(f"  Section {section_num} ({label}): upload_file_via_input returned False")

        # Dismiss any portal popup (file size alert, etc.)
        await dismiss_portal_popup(page, log, max_wait_s=2.0, context=f"Section {section_num}")

        return success

    except Exception as exc:
        log.error(f"  Section {section_num} ({label}): upload error: {exc}")
        return False


async def _upload_driving_license(
    page: Page,
    data: ClaimData,
    log: AutomationLogger,
    used_files: Set[str],
) -> bool:
    """Handle Section 5: Driving License (front + back with duplicate IDs)."""
    log.info("▸ Section 5: Driving License")

    dl_path = _resolve_file(data, "driving_license", pools=["upload_doc_files"])
    if not dl_path:
        log.info("  Section 5 (Driving License): Optional, no file found — skipping")
        return False

    used_files.add(os.path.normpath(dl_path))

    # Compress if needed (DL has 10MB limit)
    upload_path = _compress_if_needed(dl_path, "Driving License", log, limit_bytes=_DL_MAX_FILE_BYTES)

    uploaded_any = False

    # Front side
    try:
        front_input = page.locator(S.SEL_UPLOAD_DL_FRONT).first
        await asyncio.sleep(random.uniform(0.3, 0.6))

        front_ok = await upload_file_via_input(
            page,
            file_input_selector=S.SEL_UPLOAD_DL_FRONT,
            file_path=upload_path,
            label="DL Front Side",
            log=log,
        )
        if front_ok:
            log.success(f"  DL Front Side: uploaded '{Path(upload_path).name}'")
            uploaded_any = True
        else:
            log.warning("  DL Front Side: upload failed")
    except Exception as exc:
        log.warning(f"  DL Front Side: error: {exc}")

    await dismiss_portal_popup(page, log, max_wait_s=1.5, context="DL Front")
    await asyncio.sleep(random.uniform(0.5, 1.0))

    # Back side (same file)
    try:
        back_input = page.locator(S.SEL_UPLOAD_DL_BACK).first
        await asyncio.sleep(random.uniform(0.3, 0.6))

        back_ok = await upload_file_via_input(
            page,
            file_input_selector=S.SEL_UPLOAD_DL_BACK,
            file_path=upload_path,
            label="DL Back Side",
            log=log,
        )
        if back_ok:
            log.success(f"  DL Back Side: uploaded '{Path(upload_path).name}'")
            uploaded_any = True
        else:
            log.warning("  DL Back Side: upload failed")
    except Exception as exc:
        log.warning(f"  DL Back Side: error: {exc}")

    await dismiss_portal_popup(page, log, max_wait_s=1.5, context="DL Back")

    return uploaded_any


async def _upload_photographs(
    page: Page,
    data: ClaimData,
    log: AutomationLogger,
    used_files: Set[str],
) -> bool:
    """Handle Section 6: Photographs (only jpg/png/jpeg accepted)."""
    log.info("▸ Section 6: Photographs")

    # Try upload_doc_files first, then find vehicle photo in folder
    photo_path = _resolve_file(data, "photographs", pools=["upload_doc_files"])
    if not photo_path:
        photo_path = _find_first_vehicle_photo(data)

    if not photo_path:
        log.warning("  Section 6 (Photographs): REQUIRED but no photo file found — skipping")
        return False

    # Validate extension — portal only accepts jpg/png/jpeg
    ext = Path(photo_path).suffix.lower()
    if ext not in _PHOTO_EXTENSIONS:
        log.warning(
            f"  Section 6 (Photographs): file '{Path(photo_path).name}' has unsupported extension "
            f"'{ext}'. Portal only accepts: {', '.join(_PHOTO_EXTENSIONS)}"
        )
        return False

    used_files.add(os.path.normpath(photo_path))

    # Compress if needed
    upload_path = _compress_if_needed(photo_path, "Photographs", log)

    try:
        await asyncio.sleep(random.uniform(0.3, 0.7))

        success = await upload_file_via_input(
            page,
            file_input_selector=S.SEL_UPLOAD_PHOTOGRAPHS,
            file_path=upload_path,
            label="Section 6 (Photographs)",
            log=log,
        )
        if success:
            log.success(f"  Section 6 (Photographs): uploaded '{Path(upload_path).name}'")
        else:
            log.warning("  Section 6 (Photographs): upload failed")

        await dismiss_portal_popup(page, log, max_wait_s=2.0, context="Photographs")
        return success

    except Exception as exc:
        log.error(f"  Section 6 (Photographs): upload error: {exc}")
        return False


async def _upload_other_documents(
    page: Page,
    data: ClaimData,
    log: AutomationLogger,
    used_files: Set[str],
    max_bytes: int = _DEFAULT_MAX_FILE_BYTES,
) -> bool:
    """Handle Section 7: Other Documents.

    Priority:
      1. Use pre-merged PDF from folder scan time (claim_related_merged_pdf on
         scan_result, or claim_others_documents_*.pdf glob in the claim folder).
      2. Fall back to runtime merge of remaining unmatched files.
    """
    log.info("▸ Section 7: Other Documents")

    # ── Priority 1: Use pre-merged PDF from scan time ─────────────────────────
    scan_result = getattr(data, "_scan_result", None)
    precomputed_pdf = getattr(scan_result, "claim_related_merged_pdf", None) if scan_result else None

    # Failsafe: scan folder directly for claim_others_documents_*.pdf
    if not precomputed_pdf or not os.path.isfile(precomputed_pdf):
        folder = PdfMergeService.get_folder_path(data)
        if folder and os.path.isdir(folder):
            import glob as _glob
            pattern = os.path.join(folder, "claim_others_documents_*.pdf")
            found = sorted(_glob.glob(pattern))
            if found:
                precomputed_pdf = found[-1]  # use the latest timestamped file
                log.info(f"  Found pre-merged PDF via glob: {Path(precomputed_pdf).name}")
            else:
                # Also check legacy name without timestamp
                legacy = os.path.join(folder, "claim_others_documents.pdf")
                if os.path.isfile(legacy):
                    precomputed_pdf = legacy
                    log.info(f"  Found pre-merged PDF (legacy): {Path(precomputed_pdf).name}")

    if precomputed_pdf and os.path.isfile(precomputed_pdf):
        precomputed_files = getattr(scan_result, "claim_related_files", None) if scan_result else None
        n = len(precomputed_files) if precomputed_files else "?"
        mb = os.path.getsize(precomputed_pdf) / (1024 * 1024)
        log.success(
            f"  Using pre-merged PDF from scan: {Path(precomputed_pdf).name} "
            f"({n} source file(s), {mb:.1f}MB)"
        )
        upload_path = _compress_if_needed(
            precomputed_pdf, "Other Documents (pre-merged)", log, limit_bytes=max_bytes
        )
        # Track so _collect_remaining_files won't re-include this file
        used_files.add(os.path.normpath(precomputed_pdf))

        try:
            await asyncio.sleep(random.uniform(0.3, 0.7))
            success = await upload_file_via_input(
                page,
                file_input_selector=S.SEL_UPLOAD_OTHER_DOCS,
                file_path=upload_path,
                label="Section 7 (Other Documents)",
                log=log,
            )
            if success:
                log.success(
                    f"  Section 7 (Other Documents): uploaded pre-merged PDF "
                    f"({n} source files, {os.path.getsize(upload_path) / (1024 * 1024):.1f} MB)"
                )
            else:
                log.warning("  Section 7 (Other Documents): upload failed")
            await dismiss_portal_popup(page, log, max_wait_s=2.0, context="Other Documents")
            return success
        except Exception as exc:
            log.error(f"  Section 7 (Other Documents): upload error: {exc}")
            return False

    # ── Priority 2: Runtime merge fallback ───────────────────────────────────
    log.info("  No pre-merged PDF found — falling back to runtime merge.")
    config = MergeConfig(max_bytes=max_bytes, label="Other Documents", exclude_filenames={"all_pdf_text.txt", "extracted_documents_data.md", "re-inspection report format.pdf", "re-inspection report format.xlsx", "claim_others_documents.pdf", "claim_related_document_merged.pdf", "oic_other_documents_merged.pdf"}, exclude_prefixes={"claim_others_documents_", "oic_other_documents_merged"})
    remaining = PdfMergeService.collect_remaining(data, used_files, config)
    if not remaining:
        log.info("  Section 7 (Other Documents): No remaining files to merge — skipping")
        return False

    log.info(
        f"  Found {len(remaining)} remaining file(s) for merge: "
        f"{[Path(f).name for f in remaining[:5]]}{'...' if len(remaining) > 5 else ''}"
    )

    folder = PdfMergeService.get_folder_path(data)
    if folder:
        output_path = os.path.join(folder, "oic_other_documents_merged.pdf")
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="_oic_other_merged_")
        tmp.close()
        output_path = tmp.name

    merged_path = PdfMergeService.merge(remaining, output_path, config, log=log)
    if not merged_path or not os.path.isfile(merged_path):
        log.warning("  Section 7 (Other Documents): Merge failed — skipping")
        return False

    # Compress if needed
    upload_path = _compress_if_needed(merged_path, "Other Documents (merged)", log, limit_bytes=max_bytes)

    try:
        other_input = page.locator(S.SEL_UPLOAD_OTHER_DOCS).first
        await asyncio.sleep(random.uniform(0.3, 0.7))

        success = await upload_file_via_input(
            page,
            file_input_selector=S.SEL_UPLOAD_OTHER_DOCS,
            file_path=upload_path,
            label="Section 7 (Other Documents)",
            log=log,
        )
        if success:
            mb = os.path.getsize(upload_path) / (1024 * 1024)
            log.success(
                f"  Section 7 (Other Documents): uploaded merged PDF "
                f"({len(remaining)} source files, {mb:.1f} MB)"
            )
        else:
            log.warning("  Section 7 (Other Documents): upload failed")

        await dismiss_portal_popup(page, log, max_wait_s=2.0, context="Other Documents")
        return success

    except Exception as exc:
        log.error(f"  Section 7 (Other Documents): upload error: {exc}")
        return False


async def _fill_remarks(
    page: Page,
    log: AutomationLogger,
    remarks_text: str,
    delay_ms: int = 150,
) -> bool:
    """Fill the remarks textarea (required field)."""
    log.info("▸ Filling Remarks")

    try:
        remarks = page.locator(S.SEL_UPLOAD_REMARKS).first
        await remarks.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        await remarks.wait_for(state="visible", timeout=5000)
        await remarks.focus()
        await remarks.fill("")

        # Type character-by-character for human-like behavior
        for char in str(remarks_text):
            await remarks.type(char, delay=random.randint(15, 35))

        # Dispatch events for Angular/PrimeNG binding
        await remarks.evaluate(
            "el => { "
            "el.dispatchEvent(new Event('input', { bubbles: true })); "
            "el.dispatchEvent(new Event('change', { bubbles: true })); "
            "el.dispatchEvent(new Event('blur', { bubbles: true })); "
            "}"
        )

        log.field_filled("Remarks", remarks_text)
        await asyncio.sleep(delay_ms / 1000.0)
        return True

    except Exception as exc:
        log.error(f"Remarks fill failed: {exc}")
        return False


async def _click_submit(
    page: Page,
    log: AutomationLogger,
) -> bool:
    """Click the Submit button and handle confirmation popup."""
    log.info("▸ Clicking Submit button")

    try:
        submit_btn = page.locator(S.SEL_UPLOAD_SUBMIT_BTN).first
        await submit_btn.wait_for(state="visible", timeout=8000)
        await submit_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.5)

        # Wait for button to be enabled
        for _ in range(10):
            if not await submit_btn.is_disabled():
                break
            await asyncio.sleep(0.5)

        if await submit_btn.is_disabled():
            log.warning("Submit button is still disabled — cannot click")
            return False

        await submit_btn.click()
        log.success("Submit button clicked")

        # Wait for portal to process
        log.wait("Waiting for submission processing...")
        await asyncio.sleep(5.0)

        # Dismiss any confirmation/success popup
        await dismiss_portal_popup(page, log, max_wait_s=15.0, context="Post-Submit")

        return True

    except Exception as exc:
        log.error(f"Submit button error: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

async def fill_document_upload_section(
    page: Page,
    claim: ClaimData,
    *,
    log: AutomationLogger,
    stop_cb: Callable[[], bool],
    field_delay_ms: int = 150,
) -> bool:
    """
    Fill the complete Document Upload form (Step 5) on the OIC portal.

    Uploads files for all 7 sections, fills remarks, and optionally submits.

    Returns True on success, False on critical failure or stop.
    """
    log.section_start("Document Upload")

    defaults = load_automation_defaults(portal_id="oic")
    max_file_bytes = int(defaults.get("upload_max_file_bytes", _DEFAULT_MAX_FILE_BYTES))

    # Track which files have been uploaded in sections 1-6 (to exclude from "Other Documents" merge)
    section_used: Set[str] = set()

    try:
        # Dismiss any stale popups from previous step
        await dismiss_portal_popup(page, log, max_wait_s=1.5, context="Document Upload Start")

        if stop_cb():
            return False

        # ── Sections 1–4: Standard file uploads ──────────────────────────────
        file_resolution_map = {
            1: ("workshop_estimate", "estimate"),
            2: ("discharge_voucher",),
            3: ("invoice", "final_invoice"),
            4: ("reinspection_report",),
        }

        required_failures = []

        for section_num, label, selector, required in _UPLOAD_SECTIONS:
            if stop_cb():
                return False

            keys = file_resolution_map.get(section_num, ())
            file_path = _resolve_file(claim, *keys)

            success = await _upload_section(
                page, section_num, label, selector,
                file_path, required, log, section_used,
                max_bytes=max_file_bytes,
            )
            if required and not success:
                required_failures.append(f"Section {section_num} ({label})")
            await asyncio.sleep(random.uniform(0.5, 1.2))

        if required_failures:
            log.error(f"Required uploads failed: {', '.join(required_failures)}")
            return False

        if stop_cb():
            return False

        # ── Section 5: Driving License ────────────────────────────────────────
        await _upload_driving_license(page, claim, log, section_used)
        await asyncio.sleep(random.uniform(0.5, 1.0))

        if stop_cb():
            return False

        # ── Section 6: Photographs ────────────────────────────────────────────
        await _upload_photographs(page, claim, log, section_used)
        await asyncio.sleep(random.uniform(0.5, 1.0))

        if stop_cb():
            return False

        # ── Section 7: Other Documents (merge remaining) ──────────────────────
        await _upload_other_documents(page, claim, log, section_used, max_bytes=max_file_bytes)
        await asyncio.sleep(random.uniform(0.5, 1.0))

        if stop_cb():
            return False

        # ── Remarks ───────────────────────────────────────────────────────────
        remarks_text = defaults.get("upload_remarks", "okay")
        await _fill_remarks(page, log, remarks_text, delay_ms=field_delay_ms)

        if stop_cb():
            return False

        # ── Submit (configurable) ─────────────────────────────────────────────
        auto_submit = defaults.get("auto_submit_documents", False)
        if auto_submit:
            if not await _click_submit(page, log):
                log.warning("Submit failed — documents may need manual submission")
        else:
            log.info("auto_submit_documents is disabled — stopping before Submit for manual review")

        log.section_done("Document Upload")
        return True

    except Exception as exc:
        log.error(f"Document Upload failed: {exc}")
        await capture_error_screenshot(page, "document_upload", log)
        return False


def _collect_remaining_files(data: ClaimData, used_files: Set[str]) -> List[str]:
    config = MergeConfig(
        max_bytes=15 * 1024 * 1024,
        label="Other Documents",
        exclude_filenames={
            "all_pdf_text.txt",
            "extracted_documents_data.md",
            "re-inspection report format.pdf",
            "re-inspection report format.xlsx",
            "claim_others_documents.pdf",
            "claim_related_document_merged.pdf",
            "oic_other_documents_merged.pdf"
        },
        exclude_prefixes={"claim_others_documents_", "oic_other_documents_merged"}
    )
    return PdfMergeService.collect_remaining(data, used_files, config)

