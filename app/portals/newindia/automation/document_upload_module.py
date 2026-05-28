"""
document_upload_module.py — Phase 11: Document Upload Section Automation
New India Assurance portal.

Handles:
  1. Skip "Uploaded Documents" section (informational only)
  2. Open "Upload New Documents" accordion
  3. Upload mandatory documents one-by-one:
       - Driving License
       - Registration Certificate
       - Claim Form
       - Claim Related Documents (pre-merged PDF from folder scan)
  4. Click Upload button and wait for all rows to show "Successful"
  5. Dismiss the post-upload alert popup
  6. Skip "Non-Mandatory Documents" section
  7. Skip "Reminder to Insured" section

IMPORTANT:
  - Files are attached through the portal Browse controls.
  - The portal Upload button is clicked after attachments are ready.
  - Claim Related Documents uses ONLY the pre-merged PDF from folder_scanner.
    No runtime merging is performed — all merging happens at scan time.
  - Final claim review/submission remains manual.
"""

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from playwright.async_api import Page

from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    select_dropdown_with_delay,
    upload_file_via_input,
)
from app.automation.automation_logger import AutomationLogger, _ts
from app.data.folder_scanner import (
    _prepare_files_for_merge,
    _compress_pdf_for_upload,
    _compress_image_for_upload,
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.automation.services.pdf_merge_service import PdfMergeService, MergeConfig


logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_MERGED_PDF_BYTES = 15 * 1024 * 1024   # 15 MB portal limit (merged PDF)
MAX_MANDATORY_FILE_BYTES = 1536 * 1024    # 1.5 MB portal limit per individual file

# Maps our internal keys → portal dropdown option values
_UPLOAD_DOC_TYPE_MAP = {
    "driving_license":          "DRIVING LICENSE",
    "registration_certificate": "REGISTRATION CERTIFICATE",
    "claim_form":               "CLAIM FORM",
    "claim_related":            "CLAIM RELATED DOCUMENTS",
}


def _compress_mandatory_file_if_needed(
    file_path: str,
    label: str,
    log,
    limit_bytes: int = MAX_MANDATORY_FILE_BYTES,
) -> str:
    """
    Check if a mandatory document (DL, RC, Claim Form) exceeds the portal's
    per-file 1.5MB limit.  If it does, attempt to compress it into a temporary
    file and return the compressed path.  If compression fails or the file is
    already within limit, return the original path.

    The caller is responsible for nothing — temp files are cleaned up
    automatically when the process exits, as they use tempfile with delete=False
    but are written to the OS temp dir (short-lived).
    """
    if not file_path or not os.path.isfile(file_path):
        return file_path

    file_size = os.path.getsize(file_path)
    if file_size <= limit_bytes:
        return file_path  # already within limit — no compression needed

    ext = Path(file_path).suffix.lower()
    size_kb = file_size / 1024
    limit_kb = limit_bytes / 1024

    if isinstance(log, AutomationLogger):
        log.warning(
            f"{label}: file is {size_kb:.0f} KB > {limit_kb:.0f} KB limit — compressing..."
        )
    else:
        log(
            f"[{_ts()}]     ⚠️ {label}: {size_kb:.0f} KB > {limit_kb:.0f} KB limit — compressing..."
        )

    try:
        suffix = ext if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp") else ".pdf"
        tmp = tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False, prefix=f"_mand_{Path(file_path).stem}_"
        )
        tmp.close()
        out_path = tmp.name

        if ext == ".pdf":
            ok = _compress_pdf_for_upload(file_path, out_path)
        elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp"):
            ok = _compress_image_for_upload(file_path, out_path)
        else:
            ok = False  # unsupported format — use original

        if ok and os.path.isfile(out_path):
            compressed_size = os.path.getsize(out_path)
            compressed_kb = compressed_size / 1024
            if compressed_size <= limit_bytes:
                if isinstance(log, AutomationLogger):
                    log.success(
                        f"{label}: compressed to {compressed_kb:.0f} KB — within {limit_kb:.0f} KB limit."
                    )
                else:
                    log(
                        f"[{_ts()}]     ✅ {label}: compressed to {compressed_kb:.0f} KB."
                    )
                return out_path
            else:
                # Compression helped but still over limit — warn and use original
                if isinstance(log, AutomationLogger):
                    log.warning(
                        f"{label}: still {compressed_kb:.0f} KB after compression — "
                        "portal size alert may appear; will be dismissed automatically."
                    )
                else:
                    log(
                        f"[{_ts()}]     ⚠️ {label}: still {compressed_kb:.0f} KB after compression. "
                        "Portal size alert will be dismissed."
                    )
                return out_path  # use compressed (smaller) even if still over
        else:
            if isinstance(log, AutomationLogger):
                log.warning(f"{label}: compression failed — using original file.")
            else:
                log(f"[{_ts()}]     ⚠️ {label}: compression failed — using original.")
            return file_path

    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.warning(f"{label}: compression error ({exc}) — using original file.")
        else:
            log(f"[{_ts()}]     ⚠️ {label}: compression error — using original.")
        return file_path


_UPLOAD_NEW_DOCUMENTS_RE = re.compile(r"^\s*Upload New Documents\s*$", re.IGNORECASE)


def _upload_new_documents_container(page: Page):
    return page.locator(".accordion-surv").filter(
        has=page.locator("a.accordion-toggle").filter(has_text=_UPLOAD_NEW_DOCUMENTS_RE)
    ).first


async def _is_upload_new_documents_open(page: Page) -> bool:
    """Return True only when the Upload New Documents accordion content is visible."""
    container = _upload_new_documents_container(page)
    try:
        await container.wait_for(state="attached", timeout=4000)
    except Exception:
        return False

    for selector in (
        'ng-form[name="mandatoryDocForm"]',
        'select#docType0',
        'input#mandatoryFiles0',
    ):
        try:
            if await container.locator(selector).first.is_visible():
                return True
        except Exception:
            pass

    try:
        collapsed_heading = container.locator("div.panel-heading.collapsed").first
        if await collapsed_heading.is_visible():
            return False
    except Exception:
        pass

    try:
        panel_body = container.locator("div.panel-collapse.in, div.panel-collapse[style*='height: auto']").first
        return await panel_body.is_visible()
    except Exception:
        return False


async def _open_upload_new_documents_section(page: Page, log) -> bool:
    """Open Upload New Documents exactly once if collapsed, then verify its form."""
    container = _upload_new_documents_container(page)
    try:
        await container.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Upload New Documents accordion not found: {str(exc)[:120]}")
        else:
            log(f"[{_ts()}]   ❌ Upload New Documents accordion not found: {exc}")
        return False

    if await _is_upload_new_documents_open(page):
        if isinstance(log, AutomationLogger):
            log.info("'Upload New Documents' accordion already open.")
        else:
            log(f"[{_ts()}]   ℹ️ 'Upload New Documents' accordion already open.")
        return True

    heading = container.locator("a.accordion-toggle").filter(has_text=_UPLOAD_NEW_DOCUMENTS_RE).first
    for attempt in range(2):
        try:
            await heading.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            if await _is_upload_new_documents_open(page):
                return True
            await heading.click()
            await asyncio.sleep(1.0)
            if await _is_upload_new_documents_open(page):
                if isinstance(log, AutomationLogger):
                    log.success("'Upload New Documents' accordion opened.")
                else:
                    log(f"[{_ts()}]   ✅ Opened 'Upload New Documents' accordion.")
                return True
        except Exception as exc:
            if isinstance(log, AutomationLogger):
                log.warning(f"Accordion open attempt {attempt + 1} failed: {str(exc)[:100]}")
            else:
                log(f"[{_ts()}]   ⚠️ Accordion open attempt {attempt + 1} failed: {exc}")

    if isinstance(log, AutomationLogger):
        log.error("Mandatory document form not visible after opening Upload New Documents.")
    else:
        log(f"[{_ts()}]   ❌ Mandatory document form not visible after opening Upload New Documents.")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# POST-UPLOAD VERIFICATION — Wait for "Successful" status on all rows
# ══════════════════════════════════════════════════════════════════════════════

async def _wait_for_upload_success(page: Page, expected_rows: int, log, max_wait_s: float = 30.0) -> bool:
    """
    After clicking the Upload button, the portal takes 5–10s (variable) to
    process all files.  Each row transitions to show a green "Successful ✓"
    status text once its file is accepted.

    This function polls until ALL expected rows display "Successful", or
    until the timeout expires.

    Returns True if all rows show Successful, False on timeout.
    """
    if expected_rows <= 0:
        return True

    poll_interval = 1.0
    elapsed = 0.0

    if isinstance(log, AutomationLogger):
        log.wait(f"Waiting for {expected_rows} document(s) to show 'Successful' (max {max_wait_s:.0f}s)...")
    else:
        log(f"[{_ts()}]   ⏳ Waiting for {expected_rows} doc(s) to upload successfully (max {max_wait_s:.0f}s)...")

    while elapsed < max_wait_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            # Count how many rows currently show "Successful" text
            successful_count = 0
            for i in range(expected_rows):
                row_loc = page.locator(f'tr:has(input#mandatoryFiles{i}), div:has(input#mandatoryFiles{i})').first
                has_success = await row_loc.locator(
                    'span:has-text("Successful"), td:has-text("Successful"), div:has-text("Successful")'
                ).first.is_visible()
                if has_success:
                    successful_count += 1

            if successful_count >= expected_rows:
                if isinstance(log, AutomationLogger):
                    log.success(f"All {expected_rows} document(s) uploaded successfully ({elapsed:.0f}s).")
                else:
                    log(f"[{_ts()}]   ✅ All {expected_rows} doc(s) uploaded successfully ({elapsed:.0f}s).")
                return True

            # Log progress every 3 seconds
            if elapsed % 3 < poll_interval:
                if isinstance(log, AutomationLogger):
                    log.info(f"Upload progress: {successful_count}/{expected_rows} rows successful ({elapsed:.0f}s)...")
                else:
                    log(f"[{_ts()}]   ⏳ {successful_count}/{expected_rows} successful ({elapsed:.0f}s)...")

        except Exception as exc:
            if isinstance(log, AutomationLogger):
                log.warning(f"Upload status check error: {str(exc)[:80]}")

    # Timeout — log how many actually succeeded
    try:
        final_count = 0
        for i in range(expected_rows):
            row_loc = page.locator(f'tr:has(input#mandatoryFiles{i}), div:has(input#mandatoryFiles{i})').first
            has_success = await row_loc.locator(
                'span:has-text("Successful"), td:has-text("Successful"), div:has-text("Successful")'
            ).first.is_visible()
            if has_success:
                final_count += 1
    except Exception:
        final_count = 0

    if isinstance(log, AutomationLogger):
        log.warning(
            f"Upload timeout after {max_wait_s:.0f}s: {final_count}/{expected_rows} rows successful. "
            "Continuing anyway..."
        )
    else:
        log(
            f"[{_ts()}]   ⚠️ Upload timeout ({max_wait_s:.0f}s): {final_count}/{expected_rows} successful. "
            "Continuing..."
        )
    return final_count > 0  # partial success is still acceptable


# ══════════════════════════════════════════════════════════════════════════════
# MAIN UPLOAD FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

async def fill_document_upload_section(
    page: Page,
    data: ClaimData,
    log,
    stop_cb: Callable,
    field_delay_ms: int = 600,
) -> bool:
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.info("Starting Document Upload Section phase...")
        log.indent()
    else:
        log("")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log("  📝 Phase 11: Document Upload Section")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    await dismiss_portal_popup(page, log, max_wait_s=1.5)
    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — UPLOADED DOCUMENTS (SKIP — Informational only)
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section 1: Uploaded Documents (Informational)")
        log.info("Skipping display-only section.")
    else:
        log("")
        log(f"[{_ts()}]   ── Section 1: Uploaded Documents (Informational) ──")
        log(f"[{_ts()}]   ℹ️ Skipping — display-only section, no interaction needed.")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — UPLOAD NEW DOCUMENTS
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section 2: Upload New Documents")
        log.indent()
    else:
        log("")
        log(f"[{_ts()}]   ── Section 2: Upload New Documents ──")

    if not await _open_upload_new_documents_section(page, log):
        if isinstance(log, AutomationLogger):
            log.outdent()
            log.outdent()
        return False

    if stop_cb(): return False

    # ── Track which files have been uploaded in this section ──────────────────
    uploaded_keys: Set[str] = set()

    # ── Define the upload sequence ────────────────────────────────────────────
    upload_sequence = [
        ("driving_license",          "Driving License",          "Driving License"),
        ("registration_certificate", "Registration Certificate", "Registration Certificate"),
        ("claim_form",               "Claim Form",               "Claim Form"),
    ]

    # Filter to only docs that actually have files in the folder
    active_docs = []
    for doc_key, dropdown_text, label in upload_sequence:
        file_path = data.upload_doc_files.get(doc_key, "")
        if file_path and os.path.isfile(file_path):
            active_docs.append((doc_key, dropdown_text, label, file_path))
        else:
            if isinstance(log, AutomationLogger):
                log.info(f"Skipping '{label}' (File not found).")
            else:
                log(f"[{_ts()}]   ℹ️ No '{label}' file found in folder. Skipping.")

    # ── Upload each document in its own row ───────────────────────────────────
    current_row = 0
    for idx, (doc_key, dropdown_text, label, file_path) in enumerate(active_docs):
        if stop_cb(): return False

        if isinstance(log, AutomationLogger):
            log.info(f"Processing mandatory row {current_row}: {label}")
            log.indent()
        else:
            log(f"")
            log(f"[{_ts()}]   📎 Uploading: {label} (row {current_row})")

        # If not the first row, click "+" to add a new row
        if idx > 0:
            try:
                add_btn = page.locator('span.fa-plus-circle[data-ng-click="surveyorWorklistSurvey.addRow(\'man\')"]').first
                if not await add_btn.is_visible():
                    add_btn = page.locator('ng-form[name="mandatoryDocForm"] span.fa-plus-circle').first
                await add_btn.click()
                await asyncio.sleep(1.0)
                if isinstance(log, AutomationLogger):
                    log.success("New row added.")
                else:
                    log(f"[{_ts()}]     ✅ Added new row (row {current_row})")
            except Exception as e:
                if isinstance(log, AutomationLogger):
                    log.warning(f"Row addition failed: {str(e)[:100]}")
                else:
                    log(f"[{_ts()}]     ⚠️ Could not add new row: {e}. Trying to use row {current_row} anyway.")

        # Step 1: Select document type in dropdown for this row
        dropdown_sel = f'select#docType{current_row}'
        try:
            await select_dropdown_with_delay(
                page, dropdown_sel, dropdown_text,
                f"Row {current_row} Type", log, field_delay_ms
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Dropdown selection failed: {str(e)[:100]}")
                log.outdent()
            else:
                log(f"[{_ts()}]     ⚠️ Could not select dropdown for {label}: {e}")
            current_row += 1
            continue

        # Step 2: Attach file via Browse input for this row
        # Note: file_path already points to compressed version if it was over
        # 1.5 MB (compression happens at scan time in folder_scanner.py)
        file_input_sel = f'input#mandatoryFiles{current_row}'
        try:
            success = await upload_file_via_input(
                page,
                file_input_selector=file_input_sel,
                file_path=file_path,
                label=f"Row {current_row} File",
                log=log,
            )
            if success:
                uploaded_keys.add(doc_key)
            else:
                if isinstance(log, AutomationLogger):
                    log.error("File attachment failed.")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Attachment error: {str(e)[:100]}")

        # Step 4: Dismiss any portal alert that appeared after attaching
        # (file size alert — in case compression was insufficient)
        alert_tag = await dismiss_portal_popup(page, log, classify=True, max_wait_s=3.0)
        if alert_tag == "size_error":
            # File is truly too large and portal rejected it — log and skip
            if isinstance(log, AutomationLogger):
                log.warning(
                    f"{label}: portal rejected file as too large — row will be empty. "
                    "Check file size manually."
                )

        if isinstance(log, AutomationLogger):
            log.outdent()

        current_row += 1
        await asyncio.sleep(0.8)

    if stop_cb(): return False

    # ── CLAIM RELATED DOCUMENTS — Use pre-merged PDF from folder scan ────────
    if isinstance(log, AutomationLogger):
        log.info("Processing 'Claim Related Documents' (Pre-merged PDF)")
        log.indent()
    else:
        log("")
        log(f"[{_ts()}]   📎 Preparing: Claim Related Documents (pre-merged PDF)")

    # Use the pre-merged PDF generated by folder_scanner at scan time if available.
    scan_result = getattr(data, "_scan_result", None)
    precomputed_pdf = getattr(scan_result, "claim_related_merged_pdf", None) if scan_result else None

    # Failsafe: if not provided by scan_result, search the folder directly for pre-merged PDFs
    if not precomputed_pdf or not os.path.isfile(precomputed_pdf):
        folder_path = PdfMergeService.get_folder_path(data)
        if folder_path and os.path.isdir(folder_path):
            import glob
            pattern = os.path.join(folder_path, "claim_others_documents_*.pdf")
            found_files = sorted(glob.glob(pattern))
            if found_files:
                precomputed_pdf = found_files[-1]
            else:
                std_path = os.path.join(folder_path, "claim_others_documents.pdf")
                if os.path.isfile(std_path):
                    precomputed_pdf = std_path

    # Runtime fallback merge if precomputed PDF is still not found/valid
    if not precomputed_pdf or not os.path.isfile(precomputed_pdf):
        folder_path = PdfMergeService.get_folder_path(data)
        if folder_path and os.path.isdir(folder_path):
            used_files = set()

            for pool_name in ("claim_doc_files", "assessment_files", "upload_doc_files"):
                pool = getattr(data, pool_name, {}) or {}
                for fpath in pool.values():
                    if fpath:
                        used_files.add(os.path.normpath(fpath))
            
            config = MergeConfig(
                max_bytes=15 * 1024 * 1024,
                label="Runtime Fallback Claim Related",
                exclude_filenames={
                    "all_pdf_text.txt", "extracted_documents_data.md",
                    "re-inspection report format.pdf", "re-inspection report format.xlsx",
                    "claim_others_documents.pdf", "claim_related_document_merged.pdf"
                },
                exclude_prefixes={"claim_others_documents_"}
            )
            remaining = PdfMergeService.collect_remaining(data, used_files, config)
            if remaining:
                if isinstance(log, AutomationLogger):
                    log.info(f"No pre-merged PDF found. Triggering runtime merge fallback for {len(remaining)} files...")
                else:
                    log(f"[{_ts()}]   ℹ️ No pre-merged PDF found. Triggering runtime merge fallback for {len(remaining)} files...")
                import time
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output_path = os.path.join(folder_path, f"claim_others_documents_{timestamp}.pdf")
                precomputed_pdf = PdfMergeService.merge(remaining, output_path, config, log=log)

    if precomputed_pdf and os.path.isfile(precomputed_pdf):
        merged_path = precomputed_pdf
        precomputed = getattr(scan_result, "claim_related_files", None) if scan_result else None
        n = len(precomputed) if precomputed else "?"
        mb = os.path.getsize(merged_path) / (1024 * 1024)
        if isinstance(log, AutomationLogger):
            log.success(f"Using pre-merged PDF: {Path(merged_path).name} ({n} source file(s), {mb:.1f}MB)")
        else:
            log(f"[{_ts()}]     ✅ Using pre-merged: {Path(merged_path).name} ({n} source file(s), {mb:.1f}MB)")
    else:
        merged_path = None
        if isinstance(log, AutomationLogger):
            log.warning(
                "No pre-merged PDF available. Claim Related Documents will not be uploaded. "
                "Ensure folder scan completes before automation starts."
            )
        else:
            log(f"[{_ts()}]     ⚠️ No pre-merged PDF available. Skipping Claim Related Documents.")

    if merged_path:
        # Add a new row if we already used row(s) for other docs
        if current_row > 0:
            try:
                add_btn = page.locator('span.fa-plus-circle[data-ng-click="surveyorWorklistSurvey.addRow(\'man\')"]').first
                if not await add_btn.is_visible():
                    add_btn = page.locator('ng-form[name="mandatoryDocForm"] span.fa-plus-circle').first
                await add_btn.click()
                await asyncio.sleep(1.0)
                if isinstance(log, AutomationLogger):
                    log.success("New row added for merged document.")
                else:
                    log(f"[{_ts()}]     ✅ Added new row (row {current_row}) for Claim Related Documents")
            except Exception as e:
                if isinstance(log, AutomationLogger):
                    log.warning(f"Row addition failed: {str(e)[:100]}")
                else:
                    log(f"[{_ts()}]     ⚠️ Could not add new row: {e}")

        # Select "Claim Related Documents" in dropdown
        dropdown_sel = f'select#docType{current_row}'
        try:
            await select_dropdown_with_delay(
                page, dropdown_sel, "Claim Related Documents",
                f"Row {current_row} Type", log, field_delay_ms
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Dropdown selection failed: {str(e)[:100]}")
            else:
                log(f"[{_ts()}]     ⚠️ Could not select dropdown for Claim Related Documents: {e}")

        # Attach merged PDF
        file_input_sel = f'input#mandatoryFiles{current_row}'
        try:
            success = await upload_file_via_input(
                page,
                file_input_selector=file_input_sel,
                file_path=merged_path,
                label=f"Row {current_row} Merged File",
                log=log,
            )
            if success:
                if not isinstance(log, AutomationLogger):
                    log(f"[{_ts()}]     ✅ Merged PDF attached ({mb:.1f}MB)")
            else:
                if isinstance(log, AutomationLogger):
                    log.error("Merged PDF attachment failed.")
                else:
                    log(f"[{_ts()}]     ⚠️ Merged PDF attachment failed.")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Attachment error: {str(e)[:100]}")
            else:
                log(f"[{_ts()}]     ⚠️ Error attaching merged PDF: {e}")

        current_row += 1
    else:
        if isinstance(log, AutomationLogger):
            log.warning("No merged PDF available. Claim Related Documents not attached.")
        else:
            log(f"[{_ts()}]     ⚠️ No merged PDF. Claim Related Documents not attached.")

    if isinstance(log, AutomationLogger):
        log.outdent()

    # ══════════════════════════════════════════════════════════════════════════
    # CLICK UPLOAD BUTTON → WAIT FOR "SUCCESSFUL" → DISMISS ALERT
    # ══════════════════════════════════════════════════════════════════════════
    if current_row > 0:
        if isinstance(log, AutomationLogger):
            log.info(f"All {current_row} documents attached. Clicking Upload button...")
        else:
            log("")
            log(f"[{_ts()}]   📋 All {current_row} document(s) attached. Clicking Upload...")

        try:
            upload_btn = page.locator('button[data-ng-click="uploadFileNonTieUp(\'mandatory\')"]').first
            await upload_btn.wait_for(state="visible", timeout=8000)

            # Wait up to 5s for Angular to enable the button after file attachment
            for _ in range(10):
                if not await upload_btn.is_disabled():
                    break
                await asyncio.sleep(0.5)

            if await upload_btn.is_disabled():
                if isinstance(log, AutomationLogger):
                    log.warning("Upload button still disabled; files may not be attached correctly.")
                else:
                    log(f"[{_ts()}]   ⚠️ Upload button is still disabled. Skipping upload click.")
            else:
                await upload_btn.click()
                if isinstance(log, AutomationLogger):
                    log.success("Upload button clicked.")
                    log.wait("Waiting for portal to process upload...")
                else:
                    log(f"[{_ts()}]   ✅ Upload button clicked.")

                # ── Wait for the post-upload alert popup ───────────────────────
                # The portal shows a loading spinner and performs heavy network I/O.
                # To prevent tab crashes and CPU overhead, we wait 20 seconds
                # without executing any JS or Playwright actions.
                if isinstance(log, AutomationLogger):
                    log.wait("Waiting 20 seconds for upload processing quiet period...")
                else:
                    log(f"[{_ts()}]   ⏳ Waiting 20 seconds for upload processing quiet period...")
                
                await asyncio.sleep(20.0)

                # After the quiet period, we poll for the popup modal (max 30s)
                # to dismiss the "already applied/uploaded successfully" alert.
                await dismiss_portal_popup(page, log, max_wait_s=30.0, context="Post-upload processing")

        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Upload button error: {str(e)[:100]}")
            else:
                log(f"[{_ts()}]   ⚠️ Error clicking Upload button: {e}")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # NON-MANDATORY DOCUMENTS — SKIP ENTIRELY
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section: Non-Mandatory Documents")
        log.info("Skipping — handled via merged PDF.")
    else:
        log("")
        log(f"[{_ts()}]   ── List of Non-Mandatory Documents ──")
        log(f"[{_ts()}]   ℹ️ Skipping — all remaining docs already merged into Claim Related Documents.")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — REMINDER TO INSURED (SKIP)
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section: Reminder to Insured")
        log.info("Skipping — no action required.")
    else:
        log("")
        log(f"[{_ts()}]   ── Section 3: Reminder to Insured ──")
        log(f"[{_ts()}]   ℹ️ Skipping — no automation interaction needed.")

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("Document Upload phase completed.")
    else:
        log("")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log("  ✅ Phase 11 (Document Upload Section) complete")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return True
