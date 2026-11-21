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
from app.automation.services.document_utils import (
    _prepare_files_for_merge,
    _compress_pdf_for_upload,
    _compress_image_for_upload,
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.portals.newindia.automation.recovery import _BLOCKING_DIALOGS, current_recovery


logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_MERGED_PDF_BYTES = 15 * 1024 * 1024   # 15 MB portal limit (merged PDF)
MAX_MANDATORY_FILE_BYTES = 1536 * 1024    # 1.5 MB portal limit per individual file

# Supports both Tie-Up / Maruti (uploadFile) and Non-Tie-Up (uploadFileNonTieUp)
_MANDATORY_UPLOAD_BTN_SELECTOR = (
    'ng-form[name="mandatoryDocForm"] button[data-ng-click="uploadFile(\'mandatory\')"], '
    'ng-form[name="mandatoryDocForm"] button[ng-click="uploadFile(\'mandatory\')"], '
    'ng-form[name="mandatoryDocForm"] button[data-ng-click="uploadFileNonTieUp(\'mandatory\')"], '
    'ng-form[name="mandatoryDocForm"] button[ng-click="uploadFileNonTieUp(\'mandatory\')"]'
)
_MANDATORY_UPLOAD_SUCCESS_MSG = re.compile(
    r"\b(?:documents?\s+uploaded\s+suc+essfully|uploaded\s+suc+essfully)\b", re.I
)
_INLINE_SUCCESS_COUNT_RE = re.compile(
    r"\b(\d+)\s+documents?\s+uploaded\s+suc+essfully\b", re.I
)

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

async def _find_mandatory_upload_button(page: Page, timeout_ms: int = 8000):
    """Locate the visible Mandatory Documents Upload button for Tie-Up or Non-Tie-Up pages."""
    candidates = page.locator(_MANDATORY_UPLOAD_BTN_SELECTOR)
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000.0)
    while True:
        count = await candidates.count()
        for idx in range(count):
            btn = candidates.nth(idx)
            try:
                if await btn.is_visible():
                    return btn
            except Exception:
                continue
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.25)


async def _count_mandatory_upload_statuses(page: Page, expected_rows: int) -> tuple[int, int]:
    """Return (successful_rows, failed_rows) across mandatory rows 0..expected_rows-1."""
    successful = 0
    failed = 0
    for i in range(expected_rows):
        # Note: input#mandatoryFiles{i} is removed by Angular data-ng-if when uploadDocSucess == 0,
        # so anchor each <li> row on #uploadedFileTxt{i} / #docType{i} (avoid ancestor <div> matches).
        row_loc = page.locator(
            f'ng-form[name="mandatoryDocForm"] li:has(#uploadedFileTxt{i}), '
            f'ng-form[name="mandatoryDocForm"] li:has(#docType{i}), '
            f'tr:has(input#mandatoryFiles{i})'
        ).first
        if await row_loc.locator(
            ':is(span:has-text("Successful"), td:has-text("Successful")):visible'
        ).count():
            successful += 1
        elif await row_loc.locator(
            ':is(span:has-text("Failed"), td:has-text("Failed")):visible'
        ).count():
            failed += 1
    return successful, failed


async def _wait_for_upload_success(page: Page, expected_rows: int, log, max_wait_s: float = 30.0) -> bool:
    """
    Poll until all expected mandatory rows display "Successful" (or fail early if "Failed" shows).
    Returns True only when all expected_rows show "Successful".
    """
    if expected_rows <= 0:
        return True

    poll_interval = 1.0
    elapsed = 0.0

    if isinstance(log, AutomationLogger):
        log.wait(f"Waiting for {expected_rows} document(s) to show 'Successful' (max {max_wait_s:.0f}s)...")
    else:
        log(f"[{_ts()}]   ⏳ Waiting for {expected_rows} doc(s) to upload successfully (max {max_wait_s:.0f}s)...")

    successful_count = 0
    failed_count = 0
    while elapsed < max_wait_s:
        try:
            successful_count, failed_count = await _count_mandatory_upload_statuses(page, expected_rows)
            if successful_count >= expected_rows:
                if isinstance(log, AutomationLogger):
                    log.success(f"All {expected_rows} document(s) uploaded successfully ({elapsed:.0f}s).")
                else:
                    log(f"[{_ts()}]   ✅ All {expected_rows} doc(s) uploaded successfully ({elapsed:.0f}s).")
                return True
            if failed_count > 0 and (successful_count + failed_count) >= expected_rows:
                break
            if elapsed > 0 and elapsed % 3 < poll_interval:
                if isinstance(log, AutomationLogger):
                    log.info(f"Upload progress: {successful_count}/{expected_rows} rows successful ({elapsed:.0f}s)...")
                else:
                    log(f"[{_ts()}]   ⏳ {successful_count}/{expected_rows} successful ({elapsed:.0f}s)...")
        except Exception as exc:
            if isinstance(log, AutomationLogger):
                log.warning(f"Upload status check error: {str(exc)[:80]}")

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    msg = f"Mandatory upload finished with {successful_count}/{expected_rows} successful" + (
        f" and {failed_count} failed." if failed_count else "."
    )
    if isinstance(log, AutomationLogger):
        log.warning(msg)
    else:
        log(f"[{_ts()}]   ⚠️ {msg}")
    return False


async def _first_visible_text(page: Page, selectors: tuple[str, ...]) -> str:
    """Return normalized visible text for the first visible element matching any selector."""
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for idx in range(count):
            item = loc.nth(idx)
            try:
                if await item.is_visible():
                    text = " ".join((await item.inner_text()).split())
                    if text:
                        return text
            except Exception:
                continue
    return ""


async def _read_inline_upload_banners(page: Page) -> tuple[str, str]:
    """Return (success_text, error_text) from visible New India inline upload alert banners."""
    success_text = await _first_visible_text(
        page,
        (".accordion-surv .up-new-rvmp div.alert-success:visible", "div.alert-success:visible"),
    )
    error_text = await _first_visible_text(
        page,
        (".accordion-surv .up-new-rvmp div.alert-danger:visible", "div.alert-danger:visible"),
    )
    return success_text, error_text


def _inline_banner_confirms(success_text: str, error_text: str, expected_rows: int) -> tuple[bool, Optional[int]]:
    """Return (confirmed, reported_count) for visible inline upload banners."""
    if error_text or not success_text or not _MANDATORY_UPLOAD_SUCCESS_MSG.search(success_text):
        return False, None
    count_match = _INLINE_SUCCESS_COUNT_RE.search(success_text)
    if count_match:
        reported = int(count_match.group(1))
        return reported >= expected_rows, reported
    return True, None


async def _wait_for_mandatory_upload_outcome(
    page: Page, expected_rows: int, log, max_wait_s: float = 45.0
) -> tuple[bool, str]:
    """
    Wait for mandatory upload completion across Tie-Up (inline banner) and Non-Tie-Up (row badges / modal).
    Returns (upload_ok, failure_reason).
    """
    deadline = asyncio.get_running_loop().time() + max_wait_s
    popup_tag = None
    successful_count = 0
    failed_count = 0

    while asyncio.get_running_loop().time() < deadline:
        tag = await dismiss_portal_popup(
            page,
            log,
            max_wait_s=0.4,
            classify=True,
            context="Post-upload processing",
            success_message=_MANDATORY_UPLOAD_SUCCESS_MSG,
        )
        if tag is not None:
            popup_tag = tag

        success_text, error_text = await _read_inline_upload_banners(page)
        if error_text:
            reason = f"New India upload error: {error_text[:120]}"
            if isinstance(log, AutomationLogger):
                log.warning(reason)
            else:
                log(f"[{_ts()}]   ⚠️ {reason}")
            return False, reason

        banner_ok, reported_count = _inline_banner_confirms(success_text, error_text, expected_rows)
        if reported_count is not None and not banner_ok:
            return False, f"Only {reported_count}/{expected_rows} mandatory documents uploaded."
        if banner_ok:
            if isinstance(log, AutomationLogger):
                log.success(f"Portal confirmed upload: {success_text[:120]}")
            else:
                log(f"[{_ts()}]   ✅ Portal confirmed upload: {success_text[:120]}")
            return True, ""

        successful_count, failed_count = await _count_mandatory_upload_statuses(page, expected_rows)
        if successful_count >= expected_rows:
            if isinstance(log, AutomationLogger):
                log.success(f"All {expected_rows} document(s) uploaded successfully.")
            else:
                log(f"[{_ts()}]   ✅ All {expected_rows} doc(s) uploaded successfully.")
            return True, ""
        if failed_count > 0 and (successful_count + failed_count) >= expected_rows:
            return False, (
                f"Mandatory document upload failed ({successful_count}/{expected_rows} rows Successful, "
                f"{failed_count} failed)."
            )

        if popup_tag == "success":
            await asyncio.sleep(0.8)
            success_text, error_text = await _read_inline_upload_banners(page)
            if error_text:
                return False, f"New India upload error: {error_text[:120]}"
            banner_ok, reported_count = _inline_banner_confirms(success_text, error_text, expected_rows)
            if reported_count is not None and not banner_ok:
                return False, f"Only {reported_count}/{expected_rows} mandatory documents uploaded."
            successful_count, failed_count = await _count_mandatory_upload_statuses(page, expected_rows)
            if failed_count == 0:
                if isinstance(log, AutomationLogger):
                    log.success(f"Portal confirmed mandatory upload ({expected_rows} document(s)).")
                else:
                    log(f"[{_ts()}]   ✅ Portal confirmed mandatory upload ({expected_rows} doc(s)).")
                return True, ""
            return False, (
                f"Mandatory document upload failed ({successful_count}/{expected_rows} rows Successful, "
                f"{failed_count} failed)."
            )

        if popup_tag in ("size_error", "duplicate_error"):
            return False, (
                "New India rejected one or more mandatory documents during upload "
                f"({successful_count}/{expected_rows} succeeded)."
            )
        if popup_tag is not None:
            return False, (
                "New India showed a portal alert instead of confirming all mandatory uploads "
                f"({successful_count}/{expected_rows} succeeded)."
            )

        await asyncio.sleep(0.15)

    return False, f"Mandatory document upload not confirmed ({successful_count}/{expected_rows} rows Successful)."


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
        log._section = "Document Upload"
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
            if isinstance(log, AutomationLogger):
                log.document_mapped(label, os.path.basename(file_path), "Matched Successfully")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped(label, reason="File not found in folder scan")
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
                label, log, field_delay_ms, source="Calculated"
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
            if isinstance(log, AutomationLogger):
                log.upload_start(label, os.path.basename(file_path))
            
            success = await upload_file_via_input(
                page,
                file_input_selector=file_input_sel,
                file_path=file_path,
                label=label,
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

    if precomputed_pdf and os.path.isfile(precomputed_pdf):
        merged_path = precomputed_pdf
        precomputed = getattr(scan_result, "claim_related_files", None) if scan_result else None
        n = len(precomputed) if precomputed else "?"
        mb = os.path.getsize(merged_path) / (1024 * 1024)
        if isinstance(log, AutomationLogger):
            log.document_mapped("Claim Related Documents", Path(merged_path).name, f"Matched Successfully (Pre-merged, {n} files, {mb:.1f}MB)")
            log.success(f"Using pre-merged PDF: {Path(merged_path).name} ({n} source file(s), {mb:.1f}MB)")
        else:
            log(f"[{_ts()}]     ✅ Using pre-merged: {Path(merged_path).name} ({n} source file(s), {mb:.1f}MB)")
    else:
        merged_path = None
        if isinstance(log, AutomationLogger):
            log.field_skipped("Claim Related Documents", reason="No merged PDF available")
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
                "Claim Related Documents", log, field_delay_ms, source="Calculated"
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
            if isinstance(log, AutomationLogger):
                log.upload_start("Claim Related Documents", os.path.basename(merged_path))
            
            success = await upload_file_via_input(
                page,
                file_input_selector=file_input_sel,
                file_path=merged_path,
                label="Claim Related Documents",
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

        upload_ok = False
        failure_reason = ""
        try:
            upload_btn = await _find_mandatory_upload_button(page, timeout_ms=8000)
            if upload_btn is None:
                failure_reason = "Mandatory Documents Upload button was not found on the page."
                if isinstance(log, AutomationLogger):
                    log.error(failure_reason)
                else:
                    log(f"[{_ts()}]   ❌ {failure_reason}")
            else:
                # Wait up to 5s for Angular to enable the button after file attachment
                for _ in range(10):
                    if not await upload_btn.is_disabled():
                        break
                    await asyncio.sleep(0.5)

                if await upload_btn.is_disabled():
                    failure_reason = "Mandatory Documents Upload button stayed disabled; files may not be attached."
                    if isinstance(log, AutomationLogger):
                        log.warning(failure_reason)
                    else:
                        log(f"[{_ts()}]   ⚠️ {failure_reason}")
                else:
                    await upload_btn.click()
                    if isinstance(log, AutomationLogger):
                        log.success("Upload button clicked.")
                        log.wait("Waiting for portal to finish mandatory document upload...")
                    else:
                        log(f"[{_ts()}]   ✅ Upload button clicked. Waiting for upload confirmation...")

                    upload_ok, failure_reason = await _wait_for_mandatory_upload_outcome(
                        page, current_row, log, max_wait_s=45.0
                    )
        except Exception as e:
            failure_reason = f"Upload button error: {str(e)[:100]}"
            if isinstance(log, AutomationLogger):
                log.error(failure_reason)
            else:
                log(f"[{_ts()}]   ⚠️ {failure_reason}")

        if not upload_ok:
            recovery = current_recovery.get()
            if recovery is not None:
                skip_upload_wait = False

                async def _mandatory_upload_ready():
                    if skip_upload_wait:
                        return True
                    if not await recovery._same_step(page, "four") or await page.locator(_BLOCKING_DIALOGS).count():
                        return False
                    success_text, error_text = await _read_inline_upload_banners(page)
                    banner_ok, _ = _inline_banner_confirms(success_text, error_text, current_row)
                    if banner_ok:
                        return True
                    ok_count, _ = await _count_mandatory_upload_statuses(page, current_row)
                    return ok_count >= current_row

                async def _on_skip_upload():
                    nonlocal skip_upload_wait
                    skip_upload_wait = True

                resumed = await recovery.pause(
                    page,
                    log,
                    "Upload Mandatory Documents",
                    failure_reason or "Mandatory document upload did not finish cleanly.",
                    section="Document Upload",
                    ready=_mandatory_upload_ready,
                    require_original=True,
                    instruction="Click Upload under List of Mandatory Documents in Chrome, close any popup, then click Continue.",
                    confirmation_button="I uploaded the documents — continue",
                    skip_button="Continue anyway",
                    on_skip=_on_skip_upload,
                )
                if not resumed:
                    if isinstance(log, AutomationLogger):
                        log.outdent()
                        log.outdent()
                    return False
            else:
                if isinstance(log, AutomationLogger):
                    log.error(failure_reason or "Mandatory document upload failed.")
                    log.outdent()
                    log.outdent()
                else:
                    log(f"[{_ts()}]   ❌ {failure_reason or 'Mandatory document upload failed.'}")
                return False

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
        log.outdent()
        log.success("Document Upload phase completed.")
    else:
        log("")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log("  ✅ Phase 11 (Document Upload Section) complete")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return True
