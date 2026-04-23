"""
claim_documents.py — Fills the "Claim Documents" tab.

REWRITTEN 2026-04-20 — Based on proven Doc_uploader.py (Playwright sync approach
adapted to async automation engine).

UPLOAD FLOW:
  Portal renders a yellow "Upload Document" panel with:
    - Rows of: <select name^="docType"> + <input type="file" name^="fileToUpload">
    - A plus button (img[src*="plus-4-xxl"]) to add new rows
    - Row 0 is pre-existing; rows 1+ need a PLUS click first

  For each document:
    Row 0: Use the pre-existing row (no PLUS click)
    Row 1+: Click PLUS to add a new row
    Then: Set dropdown to matching doc type + upload the file

KEY FIXES from Doc_uploader.py:
  - Scope all locators to the yellow panel (avoids hitting assessment file inputs)
  - Use select[name^="docType"] and input[type="file"][name^="fileToUpload"]
  - Click PLUS via img[src*="plus-4-xxl"] (the proven selector)
  - select_option(label=...) with fallback to value="string:Label"
  - Auto-accept JS dialogs (alert/confirm/prompt)
"""
import asyncio
import logging
import os
from typing import Callable, List, Optional, Tuple

from app.data.data_model import ClaimData
from app.automation.selectors import DOCUMENTS
from app.automation.tab_utils import click_tab
from app.utils import load_settings

logger = logging.getLogger(__name__)

MAX_FILE_MB = 2.0  # Portal warns above this but still allows upload

# Radio names for Claim Documents verification section
DOC_RADIO_NAMES = [
    "ynRCBookVerified",
    "ynRelevantDamage",
    "ynDrivingLicense",
]
# Fallback dropdown index when file is missing (0-based option index)
FALLBACK_OPTION_INDEX = 3


async def _click_doc_radios(page, log_cb: Callable) -> None:
    """
    Click all 'Yes' radios on the Claim Documents tab.

    BUG FIX (B2): The old click_all_yes_radios helper searched by 'name' attr.
    These radios may only have 'ng-model' attr on the Claim Documents tab.
    This implementation tries all three selector patterns and uses the
    AngularJS-correct 'change' event dispatch.
    """
    radio_names = [
        "ynRCBookVerified",
        "ynRelevantDamage",
        "ynDrivingLicense",
    ]
    js_result = await page.evaluate("""
        (function() {
            var names = ['ynRCBookVerified', 'ynRelevantDamage', 'ynDrivingLicense'];
            var clicked = [];
            names.forEach(function(name) {
                // Strategy A: exact attribute selectors
                var selectors = [
                    'input[name="' + name + '"][value="Y"]',
                    'input[ng-model*="' + name + '"][value="Y"]',
                    'input[data-ng-model*="' + name + '"][value="Y"]',
                    'input[name="' + name + '"]',
                    'input[ng-model*="' + name + '"]',
                ];
                var found = false;
                for (var s of selectors) {
                    var r = document.querySelector(s);
                    if (r) {
                        r.checked = true;
                        r.dispatchEvent(new Event('change', {bubbles: true}));
                        try { r.click(); } catch(e) {}
                        clicked.push(name);
                        found = true;
                        break;
                    }
                }
                if (!found) {
                    // Strategy B: case-insensitive partial name scan
                    var nameLower = name.toLowerCase();
                    var allRadios = document.querySelectorAll('input[type="radio"]');
                    for (var radio of allRadios) {
                        var rname = (radio.name || radio.getAttribute('ng-model') || '').toLowerCase();
                        if (rname.includes(nameLower.substring(2).toLowerCase()) && radio.value === 'Y') {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            try { radio.click(); } catch(e) {}
                            clicked.push(name + '(partial)');
                            break;
                        }
                    }
                }
            });
            // Strategy C: click ALL unset Y-value radios in the verification section
            // (catches any that have different ng-model names than expected)
            var allRadios = document.querySelectorAll('input[type="radio"][value="Y"]');
            var extraClicked = 0;
            for (var radio of allRadios) {
                if (!radio.checked) {
                    // Only click if it looks like a verification radio (near yes/no pair)
                    var parent = radio.closest('tr,div.row,div.form-group');
                    if (parent) {
                        var hasNo = parent.querySelector('input[value="N"],input[value="n"]');
                        if (hasNo) {
                            radio.checked = true;
                            radio.dispatchEvent(new Event('change', {bubbles: true}));
                            try { radio.click(); } catch(e) {}
                            extraClicked++;
                        }
                    }
                }
            }
            return {clicked: clicked, extra: extraClicked};
        })();
    """)
    result = js_result or {}
    clicked = result.get('clicked', []) if isinstance(result, dict) else (result or [])
    extra = result.get('extra', 0) if isinstance(result, dict) else 0
    log_cb(f"  🔘 Doc radios: {len(clicked)}/{len(radio_names)} named + {extra} auto-YES")



async def _click_payment_option(page, claim: ClaimData, log_cb: Callable) -> None:
    """
    Select the Payment Option radio based on Excel data:
      - payment_to contains 'repairer' → Cashless
      - payment_to contains 'insured'  → Reimbursement
      - default (no data)              → Cashless
    """
    payment_raw = str(claim.payment_to).strip().lower()
    source = claim._excel_coords.get("payment_to", "")
    src_tag = f" (Source: {source})" if source else ""

    if "insured" in payment_raw:
        target = "reimbursement"
    else:
        target = "cashless"  # default: repairer → cashless

    result = await page.evaluate(f"""
        (function() {{
            var target = '{target}';
            // Try exact value match first
            var vals = target === 'cashless'
                ? ['CASHLESS', 'Cashless', 'cashless', 'C']
                : ['REIMBURSEMENT', 'Reimbursement', 'reimbursement', 'R'];
            for (var v of vals) {{
                var r = document.querySelector('input[type="radio"][value="' + v + '"]');
                if (r) {{
                    r.checked = true;
                    r.click();
                    r.dispatchEvent(new Event('change', {{bubbles:true}}));
                    return v;
                }}
            }}
            // Try checkbox fallback (portal uses checkboxes for Cashless/Reimbursement)
            var checkboxes = document.querySelectorAll('input[type="checkbox"]');
            for (var cb of checkboxes) {{
                var label = '';
                var parent = cb.closest('label,td,div');
                if (parent) label = parent.textContent.trim().toLowerCase();
                if (label.includes(target)) {{
                    if (!cb.checked) {{
                        cb.click();
                        cb.dispatchEvent(new Event('change', {{bubbles:true}}));
                    }}
                    return 'checkbox:' + target;
                }}
            }}
            // Try label click
            var labels = document.querySelectorAll('label');
            for (var l of labels) {{
                if (l.textContent.trim().toLowerCase().includes(target)) {{
                    l.click();
                    return 'label:' + target;
                }}
            }}
            return null;
        }})();
    """)
    display = target.capitalize()
    if result:
        log_cb(f"  ✅ Payment: {display}{src_tag}")
    else:
        log_cb(f"  ⚠️  Payment: {display} not found on page")


# ─────────────────────────────────────────────────────────────────────────────
# Upload panel helpers — scoped to the yellow "Upload Document" panel
# (Proven approach from Doc_uploader.py)
# ─────────────────────────────────────────────────────────────────────────────

async def _get_upload_panel(page):
    """
    Scope locators to the yellow 'Upload Document' panel.
    This prevents accidentally hitting file inputs in other sections.
    """
    panel = page.locator(".panel.panel-yellow").filter(
        has=page.locator(".panel-title", has_text="Upload Document")
    ).first
    return panel


async def _wait_for_upload_section(page, timeout_ms: int) -> None:
    """Wait for the upload panel, dropdown and file input to appear."""
    panel = await _get_upload_panel(page)
    await panel.wait_for(state="visible", timeout=timeout_ms)
    await panel.locator('select[name^="docType"]').first.wait_for(
        state="visible", timeout=timeout_ms
    )
    await panel.locator('input[type="file"][name^="fileToUpload"]').first.wait_for(
        state="attached", timeout=timeout_ms
    )


async def _get_row_handles(page, row_index: int, timeout_ms: int = 10000):
    """
    Return the select, nearest row container, and file input for a visible upload row.
    Using a row-scoped file input is safer than relying on the global nth() file input
    list because the portal appears to create/re-render extra hidden inputs.
    """
    panel = await _get_upload_panel(page)
    row_select = panel.locator('select[name^="docType"]').nth(row_index)
    await row_select.wait_for(state="visible", timeout=timeout_ms)
    row_container = row_select.locator(
        "xpath=ancestor::*[.//input[@type='file' and starts-with(@name,'fileToUpload')]][1]"
    )
    row_file = row_container.locator('input[type="file"][name^="fileToUpload"]').first
    await row_file.wait_for(state="attached", timeout=timeout_ms)
    return panel, row_select, row_container, row_file


async def _row_shows_expected_file(
    page, row_index: int, expected_name: str, timeout_ms: int = 3000
) -> bool:
    """
    Verify against the visible row text, not only input.files.
    This catches cases where a hidden input retained the file but the rendered row
    still says "No file chosen".
    """
    try:
        _, _, row_container, row_file = await _get_row_handles(page, row_index, timeout_ms=timeout_ms)
        row_text = (await row_container.inner_text(timeout=1000)).strip().lower()
        if expected_name.lower() in row_text and "no file chosen" not in row_text:
            return True
        try:
            selected_name = await row_file.evaluate("""
                el => {
                    if (!el || !el.files || !el.files.length) return '';
                    return el.files[0].name || '';
                }
            """)
            return bool(selected_name and selected_name.lower() == expected_name.lower())
        except Exception:
            return False
    except Exception:
        return False


async def _dismiss_upload_popup(page, log_cb: Callable, timeout_ms: int = 4000) -> bool:
    """
    Close any DOM popup/modal that appears after upload.
    The portal sometimes shows an in-page OK dialog after the first file upload,
    which blocks the PLUS button and makes the flow look stuck.
    """
    dismiss_selectors = [
        "div.modal.in button:has-text('OK')",
        "div.modal.show button:has-text('OK')",
        "div[role='dialog'] button:has-text('OK')",
        ".modal-dialog button:has-text('OK')",
        ".modal-footer .btn-primary",
        ".modal-footer button",
        ".bootbox button:has-text('OK')",
        ".swal-button",
        ".swal2-confirm",
        "button:has-text('OK')",
        "button:has-text('Yes')",
        "button:has-text('Close')",
    ]

    dismissed = False
    end_time = asyncio.get_running_loop().time() + max(timeout_ms, 1000) / 1000.0
    while asyncio.get_running_loop().time() < end_time:
        for sel in dismiss_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=250):
                    label = (await btn.inner_text(timeout=250)).strip() or "button"
                    await btn.click(force=True, timeout=1000)
                    log_cb(f"    ℹ️  Closed upload popup via '{label[:40]}'")
                    dismissed = True
                    await asyncio.sleep(0.6)
                    break
            except Exception:
                continue
        else:
            try:
                clicked = await page.evaluate("""
                    () => {
                        const isVisible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.visibility !== 'hidden' &&
                                   style.display !== 'none' &&
                                   rect.width > 0 &&
                                   rect.height > 0;
                        };

                        const candidates = Array.from(document.querySelectorAll('button, a, span'))
                            .filter(isVisible)
                            .filter(el => /^(ok|yes|close)$/i.test((el.textContent || '').trim()));

                        candidates.sort((a, b) => {
                            const az = Number(window.getComputedStyle(a).zIndex) || 0;
                            const bz = Number(window.getComputedStyle(b).zIndex) || 0;
                            return bz - az;
                        });

                        const target = candidates[0];
                        if (!target) return null;
                        target.click();
                        return (target.textContent || '').trim();
                    }
                """)
                if clicked:
                    log_cb(f"    ℹ️  Closed upload popup via DOM '{clicked[:40]}'")
                    dismissed = True
                    await asyncio.sleep(0.6)
                    continue
            except Exception:
                pass
            break

    # Safety fallback: Escape often closes stray overlays/datepickers/modals.
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.2)
    except Exception:
        pass

    return dismissed


async def _wait_after_upload(page, row_index: int, log_cb: Callable, wait_ms: int) -> None:
    """
    Let the portal finish handling a file upload before we touch the next row.
    This covers JS dialogs, DOM popups, and Angular rerenders.
    """
    deadline = asyncio.get_running_loop().time() + max(wait_ms, 2000) / 1000.0

    while asyncio.get_running_loop().time() < deadline:
        await _dismiss_upload_popup(page, log_cb, timeout_ms=900)
        try:
            await page.wait_for_load_state("networkidle", timeout=1000)
        except Exception:
            pass
        try:
            _, _, _, file_input = await _get_row_handles(page, row_index, timeout_ms=1000)
            await file_input.wait_for(state="attached", timeout=500)
        except Exception:
            pass
        await asyncio.sleep(0.4)

    await _dismiss_upload_popup(page, log_cb, timeout_ms=1200)


async def _select_doc_and_set_file(
    page, row_index: int, doc_label: str, file_path: str,
    timeout_ms: int, log_cb: Callable
) -> bool:
    """
    Set the doc type dropdown and upload file for a specific row index.
    Uses the proven approach: select[name^="docType"] nth + input[type="file"] nth
    scoped to the yellow upload panel.
    """
    panel, row_select, row_container, row_file = await _get_row_handles(
        page, row_index, timeout_ms=timeout_ms
    )

    # Wait for the dropdown to be visible
    await row_select.wait_for(state="visible", timeout=timeout_ms)

    # Set dropdown — try label first, then value="string:Label" fallback
    dropdown_set = False
    try:
        await row_select.select_option(label=doc_label, timeout=5000)
        log_cb(f"      ✅ Doc type (label): {doc_label}")
        dropdown_set = True
    except Exception as e1:
        logger.debug("Label select failed for '%s': %s", doc_label, str(e1)[:60])
        try:
            await row_select.select_option(value=f"string:{doc_label}", timeout=5000)
            log_cb(f"      ✅ Doc type (value): {doc_label}")
            dropdown_set = True
        except Exception as e2:
            logger.debug("Value select failed for '%s': %s", doc_label, str(e2)[:60])
            # JS fallback: partial text match on option text
            js_ok = await page.evaluate(f"""
                (function() {{
                    var selects = document.querySelectorAll('select[name^="docType"]');
                    var target = selects[{row_index}];
                    if (!target) return null;
                    var opts = Array.from(target.options);
                    var search = '{doc_label.lower()[:30]}';
                    var match = opts.find(o => o.text.toLowerCase().includes(search));
                    if (!match) {{
                        var words = search.split(' ');
                        for (var w of words) {{
                            if (w.length > 3) {{
                                match = opts.find(o => o.text.toLowerCase().includes(w));
                                if (match) break;
                            }}
                        }}
                    }}
                    if (match) {{
                        target.value = match.value;
                        target.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return match.text;
                    }}
                    return null;
                }})();
            """)
            if not js_ok:
                log_cb(f"      ❌ Doc type FAILED for '{doc_label}' — not found in portal dropdown")
                logger.error("Dropdown set failed: '%s' not found in portal options", doc_label)
                return False
            log_cb(f"      ✅ Doc type (JS fallback): '{js_ok}'")
            dropdown_set = True

    if not dropdown_set:
        return False

    abs_path = str(os.path.abspath(file_path))
    expected_name = os.path.basename(file_path)

    # Important: the portal may rerender the file input after doc type selection.
    # Re-acquire the row's current file input and verify the filename actually sticks.
    # For oversized files, avoid repeated retries because each retry reopens the size warning.
    is_large_file = os.path.getsize(file_path) / (1024 * 1024) > MAX_FILE_MB
    max_attempts = 1 if is_large_file else 2

    for attempt in range(1, max_attempts + 1):
        try:
            _, _, row_container, row_file = await _get_row_handles(page, row_index, timeout_ms=timeout_ms)
            await row_file.set_input_files(abs_path)

            # Large files trigger a DOM warning modal but are still accepted by the site.
            # Close it immediately before verifying the row state.
            await asyncio.sleep(0.4)
            await _dismiss_upload_popup(page, log_cb, timeout_ms=2500)
            await asyncio.sleep(0.8)
            row_text = (await row_container.inner_text(timeout=1000)).strip().lower()
            selected_name = await row_file.evaluate("""
                el => {
                    if (!el || !el.files || !el.files.length) return '';
                    return el.files[0].name || '';
                }
            """)
            if (
                expected_name.lower() in row_text and "no file chosen" not in row_text
            ) or (selected_name and selected_name.lower() == expected_name.lower()):
                if attempt > 1:
                    log_cb(f"      ℹ️  File attach succeeded on retry {attempt}")
                return True

            log_cb(
                f"      ⚠️  File attach did not stick for '{doc_label}' "
                f"(attempt {attempt}/{max_attempts}, got '{selected_name or 'empty'}')"
            )
        except Exception as exc:
            log_cb(f"      ⚠️  File attach retry {attempt}/{max_attempts} failed: {str(exc)[:70]}")

        await asyncio.sleep(0.8)

    log_cb(f"      ❌ File input did not retain '{expected_name}'")
    logger.error("File input did not retain file for row %d (%s)", row_index, doc_label)
    return False



async def _click_plus(page, log_cb: Callable, timeout_ms: int = 10000) -> bool:
    """
    Click the plus button to add a new document upload row.

    Uses the proven approach from Doc_uploader.py:
    Find img[src*="plus-4-xxl"] within the upload panel, click it,
    then wait for a new select[name^="docType"] to appear.
    """
    panel = await _get_upload_panel(page)
    before_count = await panel.locator('select[name^="docType"]').count()

    # Strategy 1: Click img[src*="plus-4-xxl"] directly (proven in Doc_uploader.py)
    try:
        plus_img = panel.locator('img[src*="plus-4-xxl"]').first
        if await plus_img.count() > 0:
            await plus_img.click(timeout=5000)
            await asyncio.sleep(0.8)
    except Exception:
        pass

    # Strategy 2: JS ng-click handler (fallback)
    try:
        await page.evaluate("""
            (function() {
                var all = document.querySelectorAll('[ng-click],[data-ng-click]');
                for (var el of all) {
                    var nc = (el.getAttribute('ng-click') || el.getAttribute('data-ng-click') || '').toLowerCase();
                    if (nc.includes('add') && (nc.includes('row') || nc.includes('document'))) {
                        el.click();
                        return nc;
                    }
                }
                return null;
            })();
        """)
        await asyncio.sleep(0.8)
    except Exception:
        pass

    # Strategy 3: CSS selectors for parent <a>/<button>
    css_selectors = [
        "a[ng-click*='addDocumentRow']",
        "a[ng-click*='addDocument']",
        "a[ng-click*='addRow']",
        "button[ng-click*='addDocument']",
        "button[ng-click*='addRow']",
        "button.btn-warning",
        "a:has(img[src*='plus'])",
    ]
    for sel in css_selectors:
        try:
            btn = page.locator(sel).last
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=3000)
                await asyncio.sleep(0.8)
                break
        except Exception:
            continue

    # Strategy 4: Find img[src*=plus] and click parent
    try:
        await page.evaluate("""
            (function() {
                var imgs = document.querySelectorAll('img[src*="plus"]');
                for (var img of imgs) {
                    var p = img.parentElement;
                    if (p && (p.tagName === 'A' || p.tagName === 'BUTTON')) {
                        p.click();
                        return true;
                    }
                }
                return false;
            })();
        """)
    except Exception:
        pass

    # Verification Step: strictly check if row was actually added
    await asyncio.sleep(1.0)
    after_count = await panel.locator('select[name^="docType"]').count()
    if after_count > before_count:
        log_cb("    ➕ New row added to DOM successfully")
        return True

    log_cb("    ⚠️  PLUS button click failed to add new row")
    return False


def _build_queue(claim: ClaimData, log_cb: Callable) -> List[Tuple[str, Optional[str]]]:
    """
    Build list of (doc_type, file_path_or_None) for every document in claim_doc_files.
    file_path is None only if file doesn't exist on disk.
    Large files (>2MB) are still included — portal shows an alert that we auto-accept.
    """
    queue = []
    for doc_type, file_path in claim.claim_doc_files.items():
        fname = os.path.basename(file_path) if file_path else "?"
        if not file_path or not os.path.isfile(file_path):
            log_cb(f"  ⚠️  Not found: {fname} → type '{doc_type}' will be skipped")
            logger.warning("Document file not found: %s (type: %s)", fname, doc_type)
            queue.append((doc_type, None))
            continue
        mb = os.path.getsize(file_path) / (1024 * 1024)
        size_warn = f" ⚠️ LARGE" if mb > MAX_FILE_MB else ""
        log_cb(f"  📎 [{doc_type}]: {fname} ({mb:.1f}MB){size_warn}")
        if mb > MAX_FILE_MB:
            logger.info("Large file (%.1fMB): %s — portal alert will be auto-accepted", mb, fname)
        queue.append((doc_type, file_path))
    return queue


async def _set_doc_type_by_index(page, row_idx: int, option_index: int,
                                  log_cb: Callable) -> None:
    """Select dropdown option at a specific index (0-based) for missing-file rows."""
    result = await page.evaluate(f"""
        (function() {{
            var selects = document.querySelectorAll('select[name^="docType"]');
            var target = selects[{row_idx}];
            if (!target || target.options.length <= {option_index}) return null;
            target.selectedIndex = {option_index};
            target.dispatchEvent(new Event('change', {{bubbles:true}}));
            return target.options[{option_index}].text;
        }})();
    """)
    if result:
        log_cb(f"      ℹ️  No file — set dropdown to option {option_index}: '{result}'")
    else:
        log_cb(f"      ⚠️  Could not set fallback dropdown option {option_index}")


async def fill_claim_documents(page, claim: ClaimData,
                                log_cb: Callable[[str], None] = print) -> None:
    await click_tab(page, "documents", log_cb)

    # ── Verification radios (AngularJS-compatible JS) ─────────────────────────
    log_cb("🔘 Setting verification radios...")
    await _click_doc_radios(page, log_cb)
    await _click_payment_option(page, claim, log_cb)

    # ── Build queue (includes docs with missing files as None) ─────────────────
    log_cb("\n📎 Building upload queue...")
    queue = _build_queue(claim, log_cb)
    if not queue:
        log_cb("  ℹ️  No documents to process.")
        logger.warning("No documents in upload queue — claim_doc_files was empty")
        return

    log_cb(f"\n📤 Processing {len(queue)} document rows...")

    # ── Auto-accept alert/confirm/prompt dialogs ─────────────────────────────
    # The portal shows a JS alert for files >2MB ("Maximum file size to be
    # upload 2MB"). We auto-click OK so the upload proceeds.
    async def _handle_dialog(dialog):
        dialog_msg = dialog.message[:80] if dialog.message else "(empty)"
        log_cb(f"    ℹ️  Portal alert: '{dialog_msg}' → auto-accepted")
        logger.info("Auto-accepted dialog: %s", dialog_msg)
        try:
            await dialog.accept()
        except Exception:
            pass

    page.on("dialog", _handle_dialog)

    # Load user config for timeouts
    settings = load_settings()
    # Support both legacy upload_wait_ms and newer upload_timeout_ms names.
    wait_timeout_ms = int(
        settings.get("upload_timeout_ms", settings.get("upload_wait_ms", 10000))
    )
    panel_ready_timeout = max(15000, wait_timeout_ms)

    # ── Wait for upload section to be ready ───────────────────────────────────
    try:
        await _wait_for_upload_section(page, panel_ready_timeout)
        log_cb("  ✅ Upload panel ready")
    except Exception as e:
        log_cb(f"  ⚠️  Upload panel wait failed: {str(e)[:80]}")
        logger.error("Upload panel not visible: %s", str(e)[:120])
        log_cb("  ℹ️  Proceeding anyway...")

    # Track results for summary
    upload_results = []  # List of (doc_type, filename, status, detail)
    uploaded_rows = []   # List of (row_idx, doc_type, file_path)

    for idx, (doc_type, file_path) in enumerate(queue):
        fname = os.path.basename(file_path) if file_path else "[no file]"
        log_cb(f"\n  [{idx+1}/{len(queue)}] '{doc_type}' → {fname}")

        # ── PLUS click: only for rows after the first pre-existing row ────────
        if idx == 0:
            panel = await _get_upload_panel(page)
            existing = await panel.locator('select[name^="docType"]').count()
            if existing == 0:
                log_cb("    ⚠️  No pre-existing row found — adding first row")
                await _click_plus(page, log_cb, timeout_ms=wait_timeout_ms)
            else:
                log_cb(f"    ℹ️  Using pre-existing row (row count: {existing})")
        else:
            # Add a new row for every subsequent document
            log_cb("    ➕ Clicking PLUS for new row...")
            added = await _click_plus(page, log_cb, timeout_ms=wait_timeout_ms)
            if not added:
                log_cb(f"    ❌ Could not add row — skipping '{doc_type}'")
                logger.error("PLUS button failed for row %d (doc: %s)", idx, doc_type)
                upload_results.append((doc_type, fname, "FAILED", "Could not add upload row"))
                continue

        # ── Row index = idx (we target the idx-th row) ────────────────────────
        row_idx = idx

        # ── Set doc type + upload file ────────────────────────────────────────
        if file_path:
            try:
                ok = await _select_doc_and_set_file(
                    page, row_idx, doc_type, file_path, wait_timeout_ms, log_cb
                )
                if ok:
                    # Wait for upload to process after the single file attach action.
                    await _wait_after_upload(page, row_idx, log_cb, wait_timeout_ms)
                    log_cb(f"    ✅ Uploaded: {fname}")
                    logger.info("Upload OK: [%s] → %s", doc_type, fname)
                    upload_results.append((doc_type, fname, "OK", "Uploaded successfully"))
                    uploaded_rows.append((row_idx, doc_type, file_path))
                else:
                    log_cb(f"    ❌ Upload FAILED for: {fname}")
                    logger.error("Upload FAILED: [%s] → %s — dropdown or file set failed", doc_type, fname)
                    upload_results.append((doc_type, fname, "FAILED", "Dropdown selection or file upload failed"))
            except Exception as e:
                log_cb(f"    ❌ Upload error: {str(e)[:80]}")
                logger.error("Upload exception: [%s] → %s — %s", doc_type, fname, str(e)[:120])
                upload_results.append((doc_type, fname, "FAILED", f"Exception: {str(e)[:80]}"))
        else:
            # No file scenario: set fallback option index 3
            await _set_doc_type_by_index(page, row_idx, FALLBACK_OPTION_INDEX, log_cb)
            logger.warning("No file for [%s] — set fallback dropdown", doc_type)
            upload_results.append((doc_type, fname, "SKIPPED", "File not found"))

    # ── Final visible-row verification pass ──────────────────────────────────
    if uploaded_rows:
        log_cb("\n🔎 Verifying visible upload rows...")
    corrected_rows = set()
    for row_idx, doc_type, file_path in uploaded_rows:
        expected_name = os.path.basename(file_path)
        if await _row_shows_expected_file(page, row_idx, expected_name, timeout_ms=2000):
            continue

        log_cb(f"  ⚠️  Row lost file after upload: [{doc_type}] → retrying visible row")
        retry_ok = await _select_doc_and_set_file(
            page, row_idx, doc_type, file_path, wait_timeout_ms, log_cb
        )
        if retry_ok:
            await _wait_after_upload(page, row_idx, log_cb, wait_timeout_ms)
            if await _row_shows_expected_file(page, row_idx, expected_name, timeout_ms=2000):
                corrected_rows.add((doc_type, expected_name))
                log_cb(f"  ✅ Row restored: [{doc_type}] → {expected_name}")
                continue

        for idx_result, (r_doc_type, r_fname, r_status, _) in enumerate(upload_results):
            if r_doc_type == doc_type and r_fname == expected_name and r_status == "OK":
                upload_results[idx_result] = (
                    r_doc_type, r_fname, "FAILED", "Visible row still shows no file after retry"
                )
                break
        logger.error("Visible row verification failed for [%s] → %s", doc_type, expected_name)

    # ── Upload Summary ────────────────────────────────────────────────────────
    ok_count = sum(1 for _, _, s, _ in upload_results if s == "OK")
    fail_count = sum(1 for _, _, s, _ in upload_results if s == "FAILED")
    skip_count = sum(1 for _, _, s, _ in upload_results if s == "SKIPPED")

    log_cb(f"\n{'═' * 50}")
    log_cb(f"📊 UPLOAD SUMMARY: {ok_count} uploaded, {fail_count} failed, {skip_count} skipped")
    log_cb(f"{'═' * 50}")
    for doc_type, fname, status, detail in upload_results:
        icon = "✅" if status == "OK" else "❌" if status == "FAILED" else "⏭️"
        log_cb(f"  {icon} [{doc_type}] → {fname} — {detail}")
    if fail_count > 0:
        log_cb(f"\n  ⚠️  {fail_count} document(s) failed to upload — check file names and portal dropdown values")
        logger.error("%d document(s) failed to upload", fail_count)
    if skip_count > 0:
        log_cb(f"  ℹ️  {skip_count} document(s) skipped (file not found or too large)")
    log_cb(f"{'═' * 50}")

    log_cb(f"\n✅ Claim Documents complete — {len(queue)} rows processed.")
