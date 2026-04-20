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

logger = logging.getLogger(__name__)

MAX_FILE_MB = 2.0

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



async def _click_cashless(page, log_cb: Callable) -> None:
    """Click the Cashless payment option via JS."""
    result = await page.evaluate("""
        (function() {
            var vals = ['CASHLESS', 'Cashless', 'cashless', 'C'];
            for (var v of vals) {
                var r = document.querySelector('input[type="radio"][value="' + v + '"]');
                if (r) {
                    r.checked = true;
                    r.click();
                    r.dispatchEvent(new Event('change', {bubbles:true}));
                    return v;
                }
            }
            // Try label
            var labels = document.querySelectorAll('label');
            for (var l of labels) {
                if (l.textContent.trim().toLowerCase() === 'cashless') {
                    l.click();
                    return 'label';
                }
            }
            return null;
        })();
    """)
    if result:
        log_cb(f"  ✅ Payment: Cashless")
    else:
        log_cb("  ⚠️  Payment: Cashless not found")


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


async def _select_doc_and_set_file(
    page, row_index: int, doc_label: str, file_path: str,
    timeout_ms: int, log_cb: Callable
) -> bool:
    """
    Set the doc type dropdown and upload file for a specific row index.
    Uses the proven approach: select[name^="docType"] nth + input[type="file"] nth
    scoped to the yellow upload panel.
    """
    panel = await _get_upload_panel(page)
    row_select = panel.locator('select[name^="docType"]').nth(row_index)
    row_file = panel.locator('input[type="file"][name^="fileToUpload"]').nth(row_index)

    # Wait for the dropdown to be visible
    await row_select.wait_for(state="visible", timeout=timeout_ms)

    # Set dropdown — try label first, then value="string:Label" fallback
    try:
        await row_select.select_option(label=doc_label, timeout=5000)
    except Exception:
        try:
            await row_select.select_option(value=f"string:{doc_label}", timeout=5000)
        except Exception as e:
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
                log_cb(f"      ⚠️  Doc type failed: {str(e)[:60]}")
                return False
            log_cb(f"      ✅ Doc type (JS): '{js_ok}'")
            # Set file after JS selection
            await row_file.set_input_files(str(os.path.abspath(file_path)))
            return True

    log_cb(f"      ✅ Doc type: {doc_label}")

    # Upload the file
    await row_file.set_input_files(str(os.path.abspath(file_path)))
    return True


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
            # Wait for new row to appear
            try:
                await panel.locator('select[name^="docType"]').nth(before_count).wait_for(
                    state="attached", timeout=5000
                )
            except Exception:
                await asyncio.sleep(0.5)
            log_cb("    ➕ New row added (plus img)")
            return True
    except Exception:
        pass

    # Strategy 2: JS ng-click handler (fallback)
    clicked = await page.evaluate("""
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
    if clicked:
        await asyncio.sleep(1.0)
        log_cb(f"    ➕ New row added (JS ng-click)")
        return True

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
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await asyncio.sleep(1.0)
                log_cb(f"    ➕ New row added (CSS)")
                return True
        except Exception:
            continue

    # Strategy 4: Find img[src*=plus] and click parent
    try:
        ok = await page.evaluate("""
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
        if ok:
            await asyncio.sleep(1.0)
            log_cb("    ➕ New row added (img parent)")
            return True
    except Exception:
        pass

    log_cb("    ⚠️  PLUS button not found")
    return False


def _build_queue(claim: ClaimData, log_cb: Callable) -> List[Tuple[str, Optional[str]]]:
    """
    Build list of (doc_type, file_path_or_None) for every document in claim_doc_files.
    file_path is None if file doesn't exist or is too large.
    """
    queue = []
    for doc_type, file_path in claim.claim_doc_files.items():
        fname = os.path.basename(file_path) if file_path else "?"
        if not file_path or not os.path.isfile(file_path):
            log_cb(f"  ⚠️  Not found: {fname} → will set fallback dropdown")
            queue.append((doc_type, None))
            continue
        mb = os.path.getsize(file_path) / (1024 * 1024)
        if mb > MAX_FILE_MB:
            log_cb(f"  ⚠️  Too large ({mb:.1f}MB): {fname} → will set fallback dropdown")
            queue.append((doc_type, None))
            continue
        log_cb(f"  📎 [{doc_type}]: {fname} ({mb:.1f}MB)")
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
    await _click_cashless(page, log_cb)

    # ── Build queue (includes docs with missing/oversized files as None) ──────
    log_cb("\n📎 Building upload queue...")
    queue = _build_queue(claim, log_cb)
    if not queue:
        log_cb("  ℹ️  No documents to process.")
        return

    log_cb(f"\n📤 Processing {len(queue)} document rows...")

    # ── Wait for upload section to be ready ───────────────────────────────────
    try:
        await _wait_for_upload_section(page, 15000)
        log_cb("  ✅ Upload panel ready")
    except Exception as e:
        log_cb(f"  ⚠️  Upload panel wait failed: {str(e)[:80]}")
        log_cb("  ℹ️  Proceeding anyway...")

    for idx, (doc_type, file_path) in enumerate(queue):
        fname = os.path.basename(file_path) if file_path else "[no file]"
        log_cb(f"\n  [{idx+1}/{len(queue)}] '{doc_type}' → {fname}")

        # ── PLUS click: only for rows after the first pre-existing row ────────
        if idx == 0:
            panel = await _get_upload_panel(page)
            existing = await panel.locator('select[name^="docType"]').count()
            if existing == 0:
                log_cb("    ⚠️  No pre-existing row found — adding first row")
                await _click_plus(page, log_cb)
            else:
                log_cb(f"    ℹ️  Using pre-existing row (row count: {existing})")
        else:
            # Add a new row for every subsequent document
            log_cb("    ➕ Clicking PLUS for new row...")
            added = await _click_plus(page, log_cb)
            if not added:
                log_cb(f"    ❌ Could not add row — skipping '{doc_type}'")
                continue

        # ── Row index = idx (we target the idx-th row) ────────────────────────
        row_idx = idx

        # ── Set doc type + upload file ────────────────────────────────────────
        if file_path:
            try:
                ok = await _select_doc_and_set_file(
                    page, row_idx, doc_type, file_path, 10000, log_cb
                )
                if ok:
                    # Wait for upload to process
                    try:
                        await page.wait_for_load_state("networkidle", timeout=4000)
                    except Exception:
                        await asyncio.sleep(1.5)
                    log_cb(f"    ✅ Uploaded: {fname}")
                else:
                    log_cb(f"    ❌ Upload FAILED for: {fname}")
            except Exception as e:
                log_cb(f"    ❌ Upload error: {str(e)[:80]}")
        else:
            # No file scenario: set fallback option index 3
            await _set_doc_type_by_index(page, row_idx, FALLBACK_OPTION_INDEX, log_cb)

    log_cb(f"\n✅ Claim Documents complete — {len(queue)} rows processed.")
