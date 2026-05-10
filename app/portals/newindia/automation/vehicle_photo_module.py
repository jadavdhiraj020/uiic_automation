"""
vehicle_photo_module.py — Phase 4: New India Assurance Portal
Handles the "Vehicle Photo Graph" section:
  Row 1 → Chassis Number Photograph  → chassis file
  Row 2 → Odometer Reading Photograph → odometer file

DOM notes:
  - Each row is an ng-repeat item: <li data-ng-repeat="manDoc in ...mandatoryFilesList">
  - Dropdown:   select[name="docType{idx}"]      (AngularJS ng-options)
  - File input: input[type="file"][name="mandatoryFiles{idx}"]
  - Plus (+):   span.fa-plus-circle[data-ng-click*="addRow"]
  - Upload btn: NOT clicked — stopped before that per user requirement.
"""

import asyncio
import logging
import os
from typing import Callable, Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Dropdown values exactly as they appear in the portal HTML option[value]
_DOCTYPE_CHASSIS  = "CHASSIS NUMBER PHOTOGRAPH"
_DOCTYPE_ODOMETER = "ODOMETER READING PHOTOGRAPH"

# ── JS helpers ────────────────────────────────────────────────────────────────

# Set a <select> via AngularJS-aware approach (triggers ng-change)
_JS_SELECT_OPTION = """
([name, value]) => {
    const sel = document.querySelector(`select[name="${name}"]`);
    if (!sel) return { ok: false, err: 'select not found: ' + name };
    // Find the option whose text or value contains our string
    const target = Array.from(sel.options).find(
        o => o.value.includes(value) || o.text.toLowerCase().includes(value.toLowerCase())
    );
    if (!target) return { ok: false, err: 'option not found: ' + value };
    sel.value = target.value;
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    // Trigger AngularJS ng-change if available
    try {
        const s = angular.element(sel).scope();
        if (s && s.$apply) s.$apply();
    } catch(e) {}
    return { ok: true, selected: target.text };
}
"""

# Click the + (plus) icon to add a new row
_JS_CLICK_PLUS = """
() => {
    // The plus icon: span.fa-plus-circle with ng-click containing addRow
    const plus = document.querySelector(
        'span.fa-plus-circle[data-ng-click*="addRow"], span.fa-plus-circle[ng-click*="addRow"]'
    );
    if (!plus) return { ok: false, err: 'plus not found' };
    plus.click();
    return { ok: true };
}
"""

# Count current rows
_JS_ROW_COUNT = """
() => document.querySelectorAll('select[name^="docType"]').length
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _select_doc_type(page: Page, idx: int, doc_type: str, log: Callable) -> bool:
    """Select dropdown value for row at index idx."""
    name = f"docType{idx}"
    try:
        # 1. Try Playwright select_option (handles label/value/text)
        sel = page.locator(f'select[name="{name}"]').first
        await sel.wait_for(state="visible", timeout=6000)
        try:
            await sel.select_option(label=doc_type, timeout=4000)
            log(f"  ✅ [Row {idx}] Dropdown → '{doc_type}' (by label)")
            return True
        except Exception:
            pass
        try:
            await sel.select_option(value=f"string:{doc_type}", timeout=4000)
            log(f"  ✅ [Row {idx}] Dropdown → '{doc_type}' (by value)")
            return True
        except Exception:
            pass

        # 2. JS fallback
        res = await page.evaluate(_JS_SELECT_OPTION, [name, doc_type])
        if res and res.get("ok"):
            log(f"  ✅ [Row {idx}] Dropdown → '{res.get('selected')}' (JS)")
            return True
        log(f"  ⚠️  [Row {idx}] Dropdown select failed: {res}")
        return False
    except Exception as e:
        log(f"  ⚠️  [Row {idx}] Dropdown error: {e}")
        return False


async def _attach_file(page: Page, idx: int, file_path: str, log: Callable) -> bool:
    """Attach file to the file input for row idx."""
    name = f"mandatoryFiles{idx}"
    fname = os.path.basename(file_path)
    abs_path = os.path.abspath(file_path)

    if not os.path.isfile(abs_path):
        log(f"  ❌ [Row {idx}] File not found: {abs_path}")
        return False

    size_mb = os.path.getsize(abs_path) / (1024 * 1024)
    if size_mb > 5.0:
        log(f"  ⚠️  [Row {idx}] File is {size_mb:.1f} MB — portal may reject if > 2 MB")

    try:
        file_input = page.locator(f'input[type="file"][name="{name}"]').first
        await file_input.wait_for(state="attached", timeout=6000)
        await file_input.set_input_files(abs_path)
        await asyncio.sleep(0.8)
        log(f"  ✅ [Row {idx}] File attached → '{fname}' ({size_mb:.2f} MB)")
        return True
    except Exception as e:
        log(f"  ⚠️  [Row {idx}] File attach failed: {e}")
        return False


async def _click_plus_and_wait(page: Page, log: Callable,
                               before_count: int, timeout_s: float = 5.0) -> bool:
    """Click the + button and wait for a new row to appear in the DOM."""
    try:
        res = await page.evaluate(_JS_CLICK_PLUS)
        if not res or not res.get("ok"):
            log(f"  ⚠️  Plus click failed: {res}")
            return False
    except Exception as e:
        log(f"  ⚠️  Plus click error: {e}")
        return False

    # Wait for DOM row count to increase
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.3)
        try:
            count = await page.evaluate(_JS_ROW_COUNT)
            if count > before_count:
                log(f"  ✅ New row added (total rows: {count})")
                return True
        except Exception:
            pass

    log(f"  ⚠️  Row count did not increase after Plus click (still {before_count})")
    return False


def _find_file(claim_data, key: str, fallback_keys: list[str]) -> Optional[str]:
    """Look up a file path from claim_doc_files dict by key or fallback keywords."""
    files: dict = getattr(claim_data, "claim_doc_files", {}) or {}
    # Direct key match
    if key in files and files[key]:
        return files[key]
    # Fallback keyword match against filenames
    for fpath in files.values():
        if not fpath:
            continue
        fname_lower = os.path.basename(fpath).lower()
        for kw in fallback_keys:
            if kw in fname_lower:
                return fpath
    return None


# ── Public entry point ────────────────────────────────────────────────────────

async def fill_vehicle_photo_graph(
    page: Page,
    claim_data,
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    """
    Fill the Vehicle Photo Graph section.
    - Row 0: Chassis Number Photograph
    - Row 1: Odometer Reading Photograph (added via + button)
    - Does NOT click Upload — stops just before that button.
    """
    def log(msg): log_cb(f"  [VP] {msg}")

    log("Starting Phase 4 — Vehicle Photo Graph")

    # ── Wait for section ─────────────────────────────────────────────────────
    try:
        await page.wait_for_selector(
            'h4.headerClip:has-text("Vehicle Photo Graph")',
            state="visible", timeout=15000
        )
        log("Section visible.")
    except Exception as e:
        log(f"Section not found: {e}")
        return False

    await asyncio.sleep(0.8)
    if stop_cb(): return False

    # ── Scroll section into view ──────────────────────────────────────────────
    try:
        await page.evaluate("""
            () => {
                const h = Array.from(document.querySelectorAll('h4.headerClip'))
                              .find(e => e.textContent.includes('Vehicle Photo Graph'));
                if (h) h.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        """)
        await asyncio.sleep(0.6)
    except Exception:
        pass

    # ── Locate file paths from claim scan ────────────────────────────────────
    chassis_file = _find_file(
        claim_data,
        key="Chassis Number Photograph",
        fallback_keys=["chassis", "chassis_number"]
    )
    odometer_file = _find_file(
        claim_data,
        key="Odometer Reading Photograph",
        fallback_keys=["odometer", "odo"]
    )

    if not chassis_file:
        log("  ⚠️  No chassis photo found in scanned files — will skip file for Row 0")
    else:
        log(f"  Chassis photo: {os.path.basename(chassis_file)}")

    if not odometer_file:
        log("  ⚠️  No odometer photo found in scanned files — will skip file for Row 1")
    else:
        log(f"  Odometer photo: {os.path.basename(odometer_file)}")

    if stop_cb(): return False

    # ── ROW 0: Chassis Number Photograph ─────────────────────────────────────
    log("Setting Row 0 → Chassis Number Photograph...")

    # Check how many rows already exist
    initial_count = await page.evaluate(_JS_ROW_COUNT)
    log(f"  Current row count: {initial_count}")

    # If no row exists yet, the portal should have 1 by default (ng-repeat init)
    if initial_count == 0:
        log("  ⚠️  No rows found. Waiting for portal to render...")
        await asyncio.sleep(2.0)
        initial_count = await page.evaluate(_JS_ROW_COUNT)
        if initial_count == 0:
            log("  ❌ Portal did not render upload rows. Skipping section.")
            return False

    await _select_doc_type(page, 0, _DOCTYPE_CHASSIS, log)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    if chassis_file:
        await _attach_file(page, 0, chassis_file, log)
        await asyncio.sleep(0.6)
    if stop_cb(): return False

    # ── ROW 1: Add row via + then set Odometer ────────────────────────────────
    log("Adding Row 1 via + button → Odometer Reading Photograph...")
    before_count = await page.evaluate(_JS_ROW_COUNT)
    added = await _click_plus_and_wait(page, log, before_count)

    if not added:
        log("  ⚠️  Could not add second row — odometer photo will be skipped")
        log("Phase 4 partial — only chassis row was filled.")
        return True  # Partial success — don't abort the whole run

    await asyncio.sleep(0.5)
    if stop_cb(): return False

    await _select_doc_type(page, 1, _DOCTYPE_ODOMETER, log)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    if odometer_file:
        await _attach_file(page, 1, odometer_file, log)
        await asyncio.sleep(0.6)
    if stop_cb(): return False

    log("Phase 4 document mapping complete. Upload button NOT clicked.")

    if stop_cb(): return False

    # ── Click Next Button ─────────────────────────────────────────────────────
    log("Clicking Next button to proceed...")
    try:
        next_btn = page.locator('button#saveQuickUpdateNM').first
        await next_btn.wait_for(state="visible", timeout=5000)
        is_disabled = await next_btn.is_disabled()
        if is_disabled:
            log("  ⚠️  Next button is disabled. Portal may require manual upload confirmation first.")
        else:
            # We use Javascript injection to click to avoid interception issues
            await page.evaluate("document.getElementById('saveQuickUpdateNM').click()")
            log("  ✅ Clicked Next button successfully.")
            await asyncio.sleep(2.0)
            
            # Handle the DOM modal popup ("Claim job details updated successfully")
            try:
                log("Waiting for confirmation popup...")
                ok_btn = page.locator('button[data-ng-click*="coverChangeObj.cancel"]').first
                await ok_btn.wait_for(state="visible", timeout=6000)
                
                # JS injection to click the OK button
                await page.evaluate("""
                    () => {
                        const btn = document.querySelector('button[data-ng-click*="coverChangeObj.cancel"]');
                        if (btn) btn.click();
                    }
                """)
                log("  ✅ Dismissed confirmation popup successfully.")
                await asyncio.sleep(1.0)
            except Exception:
                log("  ℹ️  Confirmation popup did not appear or timed out.")
                
    except Exception as e:
        log(f"  ⚠️  Could not click Next button: {e}")

    return True
