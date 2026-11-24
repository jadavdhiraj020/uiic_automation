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
from typing import Callable, Iterable, Optional

from playwright.async_api import Page

from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    _JS_TRIGGER_ELEMENT_CHANGE,
    update_field_hud,
    upload_file_via_input,
)
from app.automation.automation_logger import AutomationLogger, _ts
from app.automation.services.document_utils import (
    _compress_pdf_for_upload,
    _compress_image_for_upload,
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.portals.newindia.automation.recovery import _BLOCKING_DIALOGS, current_recovery


logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_MERGED_PDF_BYTES = 15 * 1024 * 1024   # 15 MB portal limit (merged PDF)
MAX_MANDATORY_FILE_BYTES = 1536 * 1024    # 1.5 MB portal limit per individual file
_UPLOAD_STALL_S = 60.0       # give up when the upload count has not grown for this long
_UPLOAD_HARD_CAP_S = 300.0   # absolute ceiling for one mandatory-documents batch

# Supports both Tie-Up / Maruti (uploadFile) and Non-Tie-Up (uploadFileNonTieUp)
_MANDATORY_FORM = 'ng-form[name="mandatoryDocForm"]:visible'
_MANDATORY_UPLOAD_BTN_SELECTOR = (
    f'{_MANDATORY_FORM} button[data-ng-click*="uploadFile("], '
    f'{_MANDATORY_FORM} button[ng-click*="uploadFile("], '
    f'{_MANDATORY_FORM} button[data-ng-click*="uploadFileNonTieUp("], '
    f'{_MANDATORY_FORM} button[ng-click*="uploadFileNonTieUp("]'
)
_UPLOAD_NEW_DOCUMENTS_BTN_FALLBACK = (
    'button[data-ng-click*="uploadFile("], button[ng-click*="uploadFile("], '
    'button[data-ng-click*="uploadFileNonTieUp("], button[ng-click*="uploadFileNonTieUp("]'
)
_NEGATIVE_UPLOAD_RE = re.compile(
    r"\b(?:not|no|failed|failure|error|unable|cannot|invalid|exceed(?:ed|s)?|duplicate|"
    r"already\s+(?:applied|uploaded|exists?)|more\s+than\s+once|limit|maximum|size)\b",
    re.I,
)
_MANDATORY_UPLOAD_SUCCESS_MSG = re.compile(
    r"\b(?:\d+\s+)?(?:(?:mandatory|supporting)\s+)?(?:documents?\s+|files?\s+)?"
    r"(?:uploaded\s+suc+essfully|suc+essfully\s+uploaded|upload(?:ed)?\s+suc+ess(?:ful)?)\b",
    re.I,
)
_INLINE_SUCCESS_COUNT_RE = re.compile(
    r"\b(\d+)\s+(?:documents?|files?)\s+uploaded\s+suc+essfully\b", re.I,
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

_MANDATORY_CLICK_RE = re.compile(
    r"(?:^|\.)uploadFile(?:NonTieUp)?\s*\(\s*(['\"])mandatory\1\s*\)",
    re.I,
)
_FORBIDDEN_BTN_CLICK_RE = re.compile(
    r"(?:nonMandatory|nonmandatory|uploadDigSignature|clearDocList)",
    re.I,
)


async def _is_mandatory_upload_button(btn) -> bool:
    """Verify the candidate button strictly triggers Mandatory Upload (never Reset / Non-Mandatory / SFB)."""
    try:
        if not await btn.is_visible():
            return False
        attrs = await btn.evaluate(
            """el => ({
                click: (el.getAttribute('data-ng-click') || el.getAttribute('ng-click') || '').trim(),
                text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim()
            })""",
            timeout=1500,
        )
    except Exception:
        return False
    click_expr = attrs.get("click") or ""
    btn_text = (attrs.get("text") or "").strip().casefold()
    if _FORBIDDEN_BTN_CLICK_RE.search(click_expr):
        return False
    return bool(_MANDATORY_CLICK_RE.search(click_expr) and btn_text == "upload")


async def _find_mandatory_upload_button(page: Page, timeout_ms: int = 8000):
    """Locate the visible Mandatory Documents Upload button for Tie-Up or Non-Tie-Up pages."""
    primary = page.locator(_MANDATORY_UPLOAD_BTN_SELECTOR)
    container = _upload_new_documents_container(page)
    fallback = container.locator(_UPLOAD_NEW_DOCUMENTS_BTN_FALLBACK)
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000.0)
    while True:
        for group in (primary, fallback):
            count = await group.count()
            for idx in range(count):
                btn = group.nth(idx)
                if await _is_mandatory_upload_button(btn):
                    return btn
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(0.25)


async def _count_uploaded_documents(page: Page) -> int:
    """Count rows currently present in the Uploaded Documents accordion table."""
    try:
        return int(await page.evaluate("""() => {
            let count = 0;
            for (const row of document.querySelectorAll(
                'tr[data-ng-repeat*="uploadDocArray"], tr[ng-repeat*="uploadDocArray"], ' +
                'tr[data-ng-repeat*="uploadedDocuments"], tr[ng-repeat*="uploadedDocuments"]'
            )) {
                if ((row.textContent || '').trim()) count++;
            }
            return count;
        }"""))
    except Exception:
        return 0


async def _count_mandatory_upload_statuses(page: Page, row_indices: Iterable[int]) -> tuple[int, int]:
    """Count only the rows that were actually prepared for this upload."""
    successful = 0
    failed = 0
    for i in row_indices:
        # Note: input#mandatoryFiles{i} is removed by Angular data-ng-if when uploadDocSucess == 0,
        # so anchor each <li> row on #uploadedFileTxt{i} / #docType{i} (avoid ancestor <div> matches).
        row_loc = page.locator(
            f'ng-form[name="mandatoryDocForm"] li:has(#uploadedFileTxt{i}), '
            f'ng-form[name="mandatoryDocForm"] li:has(#docType{i}), '
            f'{_MANDATORY_FORM} tr:has(#uploadedFileTxt{i}, #docType{i}, #mandatoryFiles{i})'
        ).first
        if await row_loc.locator(
            ':is(span, td):visible'
        ).filter(has_text=re.compile(r"^\s*Successful\s*$", re.I)).count():
            successful += 1
        elif await row_loc.locator(
            ':is(span, td):visible'
        ).filter(has_text=re.compile(r"^\s*Failed\s*$", re.I)).count():
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
            successful_count, failed_count = await _count_mandatory_upload_statuses(page, range(expected_rows))
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


_UploadBanners = tuple[tuple[str, int], tuple[str, int]]


async def _read_inline_upload_banners(page: Page) -> _UploadBanners:
    """Read visible banner text and identity so an old result cannot confirm a new click."""
    success, error = await page.evaluate(r"""() => {
        const seen = window.__app3NewIndiaUploadBanners ??= { nodes: new WeakMap(), nextId: 0 };
        return ['div.alert-success', 'div.alert-danger'].map(selector => {
            for (const scope of ['.accordion-surv .up-new-rvmp ', '']) {
                for (const node of document.querySelectorAll(scope + selector)) {
                    if (!node.getClientRects().length || getComputedStyle(node).visibility !== 'visible') continue;
                    const text = node.innerText.trim().replace(/\s+/g, ' ');
                    if (!text) continue;
                    if (!seen.nodes.has(node)) seen.nodes.set(node, ++seen.nextId);
                    return [text, seen.nodes.get(node)];
                }
            }
            return ['', 0];
        });
    }""")
    return (success[0], success[1]), (error[0], error[1])


async def _new_inline_upload_text(page: Page, previous: _UploadBanners) -> tuple[str, str]:
    success, error = await _read_inline_upload_banners(page)
    success_text = success[0] if success != previous[0] else ""
    error_text = error[0] if error != previous[1] else ""
    return success_text, error_text


def _is_positive_upload_text(text: str) -> bool:
    return bool(
        text
        and _MANDATORY_UPLOAD_SUCCESS_MSG.search(text)
        and not _NEGATIVE_UPLOAD_RE.search(text)
    )


def _inline_banner_confirms(success_text: str, error_text: str, expected_rows: int) -> tuple[bool, Optional[int]]:
    """Return (confirmed, reported_count) for visible inline upload banners."""
    if error_text or not _is_positive_upload_text(success_text):
        return False, None
    count_match = _INLINE_SUCCESS_COUNT_RE.search(success_text)
    if count_match:
        reported = int(count_match.group(1))
        return reported >= expected_rows, reported
    return True, None


async def _wait_for_mandatory_upload_outcome(
    page: Page,
    row_indices: tuple[int, ...],
    log,
    stop_cb,
    previous_banners: _UploadBanners,
    uploaded_before: int = 0,
    max_wait_s: float = _UPLOAD_STALL_S,
) -> tuple[bool, str]:
    """
    Wait for mandatory upload completion across Tie-Up (inline banner / uploaded table)
    and Non-Tie-Up (row badges / modal / uploaded table).

    New India uploads the batch one file at a time and the inline banner counts up
    ("1 Documents Uploaded", then "3 ...", then "4 ..."). A partial count is therefore
    progress, not a failure: keep waiting while the count or the Successful rows keep
    growing, and give up only after ``max_wait_s`` with no progress (or a hard cap).
    Returns (upload_ok, failure_reason).
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    progress_at = started
    best_reported = 0
    best_successful = 0
    deadline = started + _UPLOAD_HARD_CAP_S
    expected_rows = len(row_indices)
    # A success dialog can report a partial upload. Only accept its count if it
    # agrees with the verified batch, or fall back to the per-row statuses.
    popup_success_message = re.compile(
        rf"^(?!.*\b(?!{expected_rows}\b)\d+\s+(?:documents?|files?)\s+uploaded\s+suc+essfully\b)"
        rf"(?![\s\S]*{_NEGATIVE_UPLOAD_RE.pattern})"
        rf".*{_MANDATORY_UPLOAD_SUCCESS_MSG.pattern}",
        re.I | re.S,
    )
    popup_tag = None
    popup_detail: dict = {}
    successful_count = 0
    failed_count = 0

    def note_progress(kind: str, done: int) -> None:
        if isinstance(log, AutomationLogger):
            log.info(f"Upload progress: {done}/{expected_rows} {kind}...")
        else:
            log(f"[{_ts()}]   ⏳ Upload progress: {done}/{expected_rows} {kind}...")

    while loop.time() < deadline and loop.time() - progress_at < max_wait_s:
        if stop_cb():
            return False, "Automation stopped by user."
        cur_detail: dict = {}
        tag = await dismiss_portal_popup(
            page,
            log,
            max_wait_s=0.4,
            classify=True,
            context="Post-upload processing",
            success_message=popup_success_message,
            detail_out=cur_detail,
        )
        if tag is not None:
            popup_tag = tag
            popup_detail = cur_detail

        success_text, error_text = await _new_inline_upload_text(page, previous_banners)
        if error_text:
            reason = f"New India upload error: {error_text[:120]}"
            if isinstance(log, AutomationLogger):
                log.warning(reason)
            else:
                log(f"[{_ts()}]   ⚠️ {reason}")
            return False, reason

        banner_ok, reported_count = _inline_banner_confirms(success_text, error_text, expected_rows)
        if reported_count is not None and not banner_ok and reported_count > best_reported:
            # Partial count: the portal is still uploading the remaining files.
            best_reported = reported_count
            progress_at = loop.time()
            note_progress("documents uploaded", reported_count)
        if banner_ok:
            if isinstance(log, AutomationLogger):
                log.success(f"Portal confirmed upload: {success_text[:120]}")
            else:
                log(f"[{_ts()}]   ✅ Portal confirmed upload: {success_text[:120]}")
            return True, ""

        successful_count, failed_count = await _count_mandatory_upload_statuses(page, row_indices)
        if successful_count > best_successful:
            best_successful = successful_count
            progress_at = loop.time()
            note_progress("rows Successful", successful_count)
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
            success_text, error_text = await _new_inline_upload_text(page, previous_banners)
            if error_text:
                return False, f"New India upload error: {error_text[:120]}"
            banner_ok, reported_count = _inline_banner_confirms(success_text, error_text, expected_rows)
            successful_count, failed_count = await _count_mandatory_upload_statuses(page, row_indices)
            if reported_count is not None and not banner_ok and failed_count == 0:
                # A per-file success popup arrived but the batch is not finished yet.
                best_reported = max(best_reported, reported_count)
                popup_tag = None
                continue
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

        if popup_tag in ("size_error", "duplicate_error") or popup_tag is not None:
            alert_body = " ".join(str(popup_detail.get("body") or "").split())[:140]
            if alert_body:
                return False, (
                    f"New India portal alert ({successful_count}/{expected_rows} succeeded): {alert_body}"
                )
            if popup_tag in ("size_error", "duplicate_error"):
                return False, (
                    "New India rejected one or more mandatory documents during upload "
                    f"({successful_count}/{expected_rows} succeeded)."
                )
            return False, (
                "New India showed a portal alert instead of confirming all mandatory uploads "
                f"({successful_count}/{expected_rows} succeeded)."
            )

        staged_now = await _staged_mandatory_files(page)
        if not staged_now and failed_count == 0:
            uploaded_now = await _count_uploaded_documents(page)
            if uploaded_now >= uploaded_before + expected_rows:
                if isinstance(log, AutomationLogger):
                    log.success(f"Uploaded Documents table confirmed {expected_rows} mandatory document(s).")
                else:
                    log(f"[{_ts()}]   ✅ Uploaded Documents confirmed {expected_rows} doc(s).")
                return True, ""

        await asyncio.sleep(0.15)

    if stop_cb():
        return False, "Automation stopped by user."
    if best_reported:
        return False, (
            f"Only {best_reported}/{expected_rows} mandatory documents uploaded "
            f"(no further progress for {int(max_wait_s)}s)."
        )
    return False, f"Mandatory document upload not confirmed ({successful_count}/{expected_rows} rows Successful)."


async def _staged_mandatory_files(page: Page) -> dict[int, tuple[str, tuple[str, ...]]]:
    """Read the category and filename(s) from each occupied Mandatory Documents row."""
    form = page.locator(_MANDATORY_FORM)
    rows = await form.evaluate(r"""form => {
        const rows = [];
        for (const input of form.querySelectorAll('input[type="file"][id^="mandatoryFiles"]')) {
            const index = input.id.slice('mandatoryFiles'.length);
            if (!/^\d+$/.test(index)) continue;
            const selected = form.querySelector('#docType' + index);
            const displayed = form.querySelector('input#uploadedFileTxt' + index)?.value.trim();
            const names = Array.from(input.files, file => file.name);
            if (displayed) names.push(displayed.split(/[\\/]/).pop());
            if (names.length) rows.push([Number(index), selected?.value, [...new Set(names)]]);
        }
        return rows;
    }""", timeout=2000)
    return {index: (value or "", tuple(names)) for index, value, names in rows}


def _normalize_document_type(value: str) -> str:
    normalized = " ".join(str(value or "").casefold().split())
    for prefix in ("string:", "object:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    normalized = normalized.replace("licence", "license")
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _match_document_type_option(options: list[list[str]], doc_type: str) -> tuple[str, str]:
    """Match a mandatory document type against portal option values and visible labels in 3 passes."""
    expected = _normalize_document_type(doc_type)
    val_exact = [
        value for value, _label in options
        if _normalize_document_type(value) == expected
    ]
    if len(val_exact) == 1:
        return val_exact[0], ""

    label_exact = [
        value for value, label in options
        if _normalize_document_type(label) == expected
    ]
    if len(label_exact) == 1:
        return label_exact[0], ""

    partial = [
        value for value, label in options
        if (
            (norm_val := _normalize_document_type(value))
            and (expected in norm_val or norm_val in expected)
        )
        or (
            (norm_lbl := _normalize_document_type(label))
            and (expected in norm_lbl or norm_lbl in expected)
        )
    ]
    if len(partial) == 1:
        return partial[0], ""

    sample = ", ".join(lbl.strip() for _, lbl in options[:4] if lbl and lbl.strip())
    if sample:
        return "", f"Could not match document type in New India dropdown (options: {sample})."
    return "", "The document type is unavailable or ambiguous in the New India dropdown."


async def _prepare_mandatory_row(
    page: Page,
    row: int,
    doc_type: str,
    file_path: str,
    log,
    field_delay_ms: int,
    *,
    local_temp_files: Optional[list[str]] = None,
) -> tuple[str, str, str]:
    """Return (verified_category_value, attached_filename, failure_reason)."""
    form = page.locator(_MANDATORY_FORM)
    dropdown = form.locator(f"select#docType{row}")
    if row and not await dropdown.count():
        add_candidates = form.locator(
            'span.fa-plus-circle[data-ng-click*="addRow"]:visible, '
            'span.fa-plus-circle[ng-click*="addRow"]:visible'
        )
        add_row = (add_candidates if await add_candidates.count() else form.locator("span.fa-plus-circle:visible")).last
        try:
            await add_row.scroll_into_view_if_needed()
            await add_row.click(timeout=3500)
            await dropdown.wait_for(state="visible", timeout=3500)
        except Exception:
            return "", os.path.basename(file_path), "New India did not open a new document row."
    if row in await _staged_mandatory_files(page):
        return "", os.path.basename(file_path), "The document row already has an attachment."

    try:
        await dropdown.scroll_into_view_if_needed()
    except Exception:
        pass

    options = await dropdown.evaluate("""select => Array.from(select.options)
        .filter(option => {
            if (!option.value || option.disabled || option.matches(':disabled')) return false;
            const txt = (option.textContent || option.label || option.text || '').trim();
            return !/^\\s*-*\\s*select\\s*-*\\s*$/i.test(txt);
        })
        .map(option => [option.value, (option.textContent || option.label || option.text || '').trim()])""", timeout=2500)

    selected, match_err = _match_document_type_option(options, doc_type)
    if not selected:
        return "", os.path.basename(file_path), match_err

    await dropdown.select_option(value=selected, timeout=2500)
    try:
        await dropdown.evaluate(_JS_TRIGGER_ELEMENT_CHANGE, timeout=1500)
    except Exception:
        pass
    await asyncio.sleep(field_delay_ms / 1000)
    if await dropdown.input_value(timeout=1500) != selected:
        return "", os.path.basename(file_path), "New India did not keep the selected document type."

    label = doc_type.title()
    limit_bytes = (
        MAX_MERGED_PDF_BYTES
        if _normalize_document_type(doc_type) == "claim related documents"
        else MAX_MANDATORY_FILE_BYTES
    )
    attach_path = _compress_mandatory_file_if_needed(file_path, label, log, limit_bytes=limit_bytes)
    if attach_path != file_path and local_temp_files is not None:
        local_temp_files.append(attach_path)

    filename = os.path.basename(attach_path)
    if isinstance(log, AutomationLogger):
        log.upload_start(label, filename)
    attached = await upload_file_via_input(
        page, f'{_MANDATORY_FORM} input#mandatoryFiles{row}', attach_path, label, log,
    )
    alert_detail: dict = {}
    alert = await dismiss_portal_popup(
        page, log, classify=True, max_wait_s=1.5, detail_out=alert_detail,
    )
    alert_text = " ".join(str(alert_detail.get("body") or "").split())[:120]
    if alert == "size_error":
        return "", filename, alert_text or "New India rejected the file size."
    if alert == "duplicate_error":
        return "", filename, alert_text or "New India reported a duplicate document."
    if alert == "other":
        return "", filename, alert_text or "New India showed an alert while attaching the file."
    if not attached or (await _staged_mandatory_files(page)).get(row) != (selected, (filename,)):
        return "", filename, "New India did not keep the expected file and document type on the same row."
    return selected, filename, ""


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

    scan_result = getattr(data, "_scan_result", None)
    merged_path = getattr(scan_result, "claim_related_merged_pdf", None)
    active_docs = []
    for key, doc_type in _UPLOAD_DOC_TYPE_MAP.items():
        file_path = merged_path if key == "claim_related" else data.upload_doc_files.get(key)
        if file_path:
            active_docs.append((doc_type, os.fspath(file_path)))
        elif isinstance(log, AutomationLogger):
            reason = "No merged PDF available" if key == "claim_related" else "File not found in folder scan"
            log.field_skipped(doc_type.title(), reason=reason)
        else:
            log(f"[{_ts()}]   No file found for {doc_type.title()}. Skipping.")

    prepared = {}
    review = []
    local_temp_files: list[str] = []
    row = 0
    total_docs = len(active_docs)
    recovery_ctx = current_recovery.get()

    try:
        for doc_type, file_path in active_docs:
            if stop_cb():
                return False
            label = doc_type.title()
            filename = os.path.basename(file_path)
            if recovery_ctx is not None:
                await update_field_hud(
                    page, "Document Upload", f"{label} ({row + 1}/{total_docs})", "active",
                    filled=recovery_ctx.fields_filled, failed=recovery_ctx.fields_failed,
                    skipped=recovery_ctx.fields_skipped,
                )
            reason = "The file from the folder scan is no longer available."
            if os.path.isfile(file_path):
                if isinstance(log, AutomationLogger):
                    log.document_mapped(label, filename, "Matched Successfully")
                try:
                    selected, attached_name, reason = await _prepare_mandatory_row(
                        page, row, doc_type, file_path, log, field_delay_ms,
                        local_temp_files=local_temp_files,
                    )
                    filename = attached_name or filename
                    if selected:
                        prepared[row] = (selected, (filename,))
                        row += 1
                        continue
                    # Reuse a failed row only if New India has left it empty.
                    if row in await _staged_mandatory_files(page):
                        row += 1
                except Exception as exc:
                    logger.debug("Could not prepare mandatory document row %s: %r", row, exc)
                    reason = "App3 could not verify the document row in New India."
            review.append(f"{label} ({filename}) — {reason}")

        if stop_cb():
            return False

        row_indices = tuple(prepared)
        previous_banners = None
        uploaded_before = 0
        upload_ok = False
        failure_reason = ""
        if active_docs:
            try:
                if await _staged_mandatory_files(page) != prepared:
                    failure_reason = "The files in the New India upload list could not all be verified."
                elif prepared:
                    upload_btn = await _find_mandatory_upload_button(page)
                    if upload_btn is None:
                        failure_reason = "App3 could not find the Mandatory Documents Upload button."
                    else:
                        for _ in range(10):
                            if stop_cb():
                                return False
                            if not await upload_btn.is_disabled():
                                break
                            await asyncio.sleep(0.5)
                        if await upload_btn.is_disabled():
                            failure_reason = "New India did not enable the Mandatory Documents Upload button."
                        else:
                            previous_banners = await _read_inline_upload_banners(page)
                            uploaded_before = await _count_uploaded_documents(page)
                            # Recheck after the button becomes ready. Upload submits the entire list.
                            if await _staged_mandatory_files(page) != prepared:
                                failure_reason = "The document types or attachments changed before Upload."
                            elif not stop_cb():
                                count = len(prepared)
                                message = f"Uploading {count} verified mandatory document(s)."
                                if isinstance(log, AutomationLogger):
                                    log.info(message)
                                else:
                                    log(f"[{_ts()}]   {message}")
                                if recovery_ctx is not None:
                                    await update_field_hud(
                                        page, "Document Upload", f"Uploading {count} documents", "active",
                                        filled=recovery_ctx.fields_filled, failed=recovery_ctx.fields_failed,
                                        skipped=recovery_ctx.fields_skipped,
                                    )
                                await upload_btn.scroll_into_view_if_needed()
                                await upload_btn.click(timeout=5000)
                                upload_ok, failure_reason = await _wait_for_mandatory_upload_outcome(
                                    page, row_indices, log, stop_cb, previous_banners,
                                    uploaded_before=uploaded_before,
                                )
            except Exception as exc:
                logger.debug("Mandatory Documents upload could not be verified: %r", exc)
                failure_reason = "App3 could not verify the Mandatory Documents upload in New India."
    finally:
        for tmp_path in local_temp_files:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    if stop_cb():
        return False

    if review or failure_reason:
        check_rows = not review and previous_banners is not None
        if failure_reason:
            review.append(failure_reason)
        message = "\n".join(review)
        if isinstance(log, AutomationLogger):
            log.warning(message)
        else:
            log(message)
        recovery = current_recovery.get()
        resumed = False
        if recovery is not None:
            overridden = False
            baseline = previous_banners if check_rows else await _read_inline_upload_banners(page)
            baseline_uploaded = uploaded_before if check_rows else await _count_uploaded_documents(page)
            expected = len(active_docs) - (len(prepared) if upload_ok else 0)

            async def _mandatory_upload_ready():
                if not await recovery._same_step(page, "four") or await page.locator(_BLOCKING_DIALOGS).count():
                    return False
                if overridden:
                    return True
                success_text, error_text = await _new_inline_upload_text(page, baseline)
                if _inline_banner_confirms(success_text, error_text, expected)[0]:
                    return True
                if check_rows:
                    ok_count, _ = await _count_mandatory_upload_statuses(page, row_indices)
                    if ok_count == expected:
                        return True
                    if not error_text and not await _staged_mandatory_files(page):
                        if await _count_uploaded_documents(page) >= baseline_uploaded + expected:
                            return True
                return False

            async def _on_skip_upload():
                nonlocal overridden
                overridden = True

            resumed = await recovery.pause(
                page,
                log,
                "Review mandatory documents",
                message,
                section="Document Upload",
                ready=_mandatory_upload_ready,
                require_original=True,
                instruction="Check the listed files in Chrome. Upload any missing files, close any portal popup, then click Continue.",
                confirmation_button="Continue",
                skip_button="Continue anyway",
                on_skip=_on_skip_upload,
            )
        if not resumed:
            if isinstance(log, AutomationLogger):
                log.outdent()
                log.outdent()
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
