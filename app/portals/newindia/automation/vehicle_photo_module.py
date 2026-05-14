import asyncio
import os
from typing import Callable, Optional
from playwright.async_api import Page
from app.portals.newindia.automation.ui_utils import select_dropdown_with_delay
from app.automation.automation_logger import _ts

# Dropdown values exactly as they appear in the portal HTML option[value]
_DOCTYPE_CHASSIS  = "CHASSIS NUMBER PHOTOGRAPH"
_DOCTYPE_ODOMETER = "ODOMETER READING PHOTOGRAPH"

# ── JS helpers ────────────────────────────────────────────────────────────────

# Click the + (plus) icon to add a new row
_JS_CLICK_PLUS = r"""
() => {
    const plus = document.querySelector(
        'span.fa-plus-circle[data-ng-click*="addRow"], span.fa-plus-circle[ng-click*="addRow"]'
    );
    if (!plus) return { ok: false, err: 'plus not found' };
    plus.click();
    return { ok: true };
}
"""

# Count current rows
_JS_ROW_COUNT = r"""
() => document.querySelectorAll('select[name^="docType"]').length
"""

# Detect any visible modal/popup overlay and return info about it
_JS_DETECT_POPUP = r"""
() => {
    // Check for angular-ui-bootstrap modal (most common in NIA portal)
    const modal = document.querySelector('.modal.in, .modal[style*="display: block"], .modal[style*="display:block"]');
    if (modal) {
        const header = modal.querySelector('.modal-header, .modal-title');
        const body   = modal.querySelector('.modal-body');
        return {
            found: true,
            type: 'modal',
            title: header ? header.innerText.trim() : '',
            body:  body   ? body.innerText.trim().substring(0, 120) : ''
        };
    }
    // Check for any swal / custom overlay
    const swal = document.querySelector('.swal2-container, .sweet-overlay');
    if (swal) return { found: true, type: 'swal' };
    // Check for NG-dialog
    const ngd = document.querySelector('.ngdialog.ngdialog-open');
    if (ngd) return { found: true, type: 'ngdialog' };
    return { found: false };
}
"""

# Dismiss the modal by clicking the most likely "OK / Close / Cancel" button
_JS_DISMISS_POPUP = r"""
() => {
    // Priority 1: a "Cancel" / close button in the coverChange popup (NIA specific)
    const cancelBtn = document.querySelector(
        'button[data-ng-click*="coverChangeObj.cancel"], button[ng-click*="coverChangeObj.cancel"]'
    );
    if (cancelBtn && cancelBtn.offsetParent !== null) { cancelBtn.click(); return { ok: true, via: 'coverCancel' }; }

    // Priority 2: generic OK / Close / Yes button in any modal
    const selectors = [
        '.modal.in button[data-ng-click*="ok"]',
        '.modal.in button[ng-click*="ok"]',
        '.modal.in button[data-ng-click*="confirm"]',
        '.modal.in button[ng-click*="confirm"]',
        '.modal.in button[data-ng-click*="close"]',
        '.modal.in button[ng-click*="close"]',
        '.modal.in .modal-footer button:last-child',  // last footer button = OK
        '.modal[style*="display: block"] .modal-footer button:last-child',
        '.modal[style*="display:block"] .modal-footer button:last-child',
    ];
    for (const sel of selectors) {
        const btn = document.querySelector(sel);
        if (btn && btn.offsetParent !== null) { btn.click(); return { ok: true, via: sel }; }
    }

    // Priority 3: click the X (close icon) on any visible modal header
    const closeX = document.querySelector('.modal.in .close, .modal.in button.close');
    if (closeX && closeX.offsetParent !== null) { closeX.click(); return { ok: true, via: 'closeX' }; }

    return { ok: false, err: 'no dismissible button found' };
}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _attach_file(page: Page, idx: int, file_path: str, log: Callable) -> bool:
    """Attach file to the file input for row idx."""
    name = f"mandatoryFiles{idx}"
    fname = os.path.basename(file_path)
    abs_path = os.path.abspath(file_path)

    if not os.path.isfile(abs_path):
        log(f"  ❌ [Row {idx}] File not found: {abs_path}")
        return False

    try:
        file_input = page.locator(f'input[type="file"][name="{name}"]').first
        await file_input.wait_for(state="attached", timeout=6000)
        await file_input.set_input_files(abs_path)
        await asyncio.sleep(0.8)
        log(f"  ✅ [Row {idx}] File attached → '{fname}'")
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

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.5)
        try:
            count = await page.evaluate(_JS_ROW_COUNT)
            if count > before_count:
                log(f"  ✅ New row added (total rows: {count})")
                return True
        except Exception:
            pass
    log(f"  ⚠️  Row count did not increase after Plus click")
    return False


async def _handle_popup_after_next(page: Page, log: Callable, max_wait_s: float = 8.0) -> bool:
    """
    After clicking Next, poll for any modal/popup overlay and dismiss it.

    Returns True if popup was handled (or no popup appeared), False on error.

    Strategy:
      1. Poll up to max_wait_s for a popup to appear.
      2. Once detected, log what it is and dismiss it.
      3. Wait briefly for it to close.
      4. Return — caller is responsible for continuing.
    """
    log("Polling for popup/modal after Next...")
    poll_interval = 0.4
    elapsed = 0.0

    while elapsed < max_wait_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            popup_info = await page.evaluate(_JS_DETECT_POPUP)
        except Exception as e:
            log(f"  ⚠️ Popup detection error: {e}")
            continue

        if popup_info.get("found"):
            ptype = popup_info.get("type", "unknown")
            title = popup_info.get("title", "")
            body  = popup_info.get("body", "")
            log(f"  🔔 Popup detected! type={ptype} | title='{title}' | body='{body[:80]}'")

            # Dismiss it
            try:
                dismiss_res = await page.evaluate(_JS_DISMISS_POPUP)
                if dismiss_res.get("ok"):
                    log(f"  ✅ Popup dismissed via: {dismiss_res.get('via')}")
                else:
                    log(f"  ⚠️ Could not dismiss popup: {dismiss_res.get('err')}")
                    return False
            except Exception as e:
                log(f"  ⚠️ Popup dismiss error: {e}")
                return False

            # Wait for overlay to fade out
            await asyncio.sleep(1.0)

            # Verify popup is gone
            try:
                still_open = await page.evaluate(_JS_DETECT_POPUP)
                if still_open.get("found"):
                    log("  ⚠️ Popup still visible after dismiss — trying once more...")
                    await page.evaluate(_JS_DISMISS_POPUP)
                    await asyncio.sleep(1.0)
                else:
                    log("  ✅ Popup closed successfully.")
            except Exception:
                pass

            return True

    log("  ℹ️ No popup detected within timeout — continuing normally.")
    return True


def _find_file(claim_data, key: str, fallback_keys: list) -> Optional[str]:
    files: dict = getattr(claim_data, "claim_doc_files", {}) or {}
    if key in files and files[key]:
        return files[key]
    for fpath in files.values():
        if not fpath: continue
        fname_lower = os.path.basename(fpath).lower()
        for kw in fallback_keys:
            if kw in fname_lower: return fpath
    return None


# ── Public entry point ────────────────────────────────────────────────────────

async def fill_vehicle_photo_graph(
    page: Page,
    claim_data,
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False,
    field_delay_ms: int = 600
) -> bool:
    def log(msg): log_cb(f"[{_ts()}]   [VP] {msg}")

    log("Starting Phase 4 — Vehicle Photo Graph")

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

    chassis_file  = _find_file(claim_data, "Chassis Number Photograph",  ["chassis"])
    odometer_file = _find_file(claim_data, "Odometer Reading Photograph", ["odometer", "odo"])

    # ROW 0 — Chassis
    log("Setting Row 0 → Chassis...")
    await select_dropdown_with_delay(page, 'select[name="docType0"]', _DOCTYPE_CHASSIS, "Row 0 Type", log, field_delay_ms)
    if chassis_file:
        await _attach_file(page, 0, chassis_file, log)

    if stop_cb(): return False

    # ROW 1 — Odometer (optional)
    if odometer_file:
        log("Adding Row 1 for Odometer...")
        before_count = await page.evaluate(_JS_ROW_COUNT)
        if await _click_plus_and_wait(page, log, before_count):
            await select_dropdown_with_delay(page, 'select[name="docType1"]', _DOCTYPE_ODOMETER, "Row 1 Type", log, field_delay_ms)
            await _attach_file(page, 1, odometer_file, log)
    else:
        log("  ℹ️ No Odometer file found — skipping Row 1.")

    if stop_cb(): return False

    # ── Click Next button ─────────────────────────────────────────────────────
    log("Clicking Next button...")
    try:
        # Use Playwright's trusted click (not JS inject) so the portal's
        # Angular click-handler fires correctly and produces the modal.
        next_btn = page.locator('#saveQuickUpdateNM')
        await next_btn.wait_for(state="visible", timeout=5000)
        await next_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        await next_btn.click()
        log("  ✅ Next button clicked.")
    except Exception as e:
        log(f"  ⚠️ Next button not found via locator, falling back to JS click: {e}")
        try:
            await page.evaluate("document.getElementById('saveQuickUpdateNM').click()")
            log("  ✅ Next button clicked (JS fallback).")
        except Exception as e2:
            log(f"  ❌ Next button click failed: {e2}")
            return False

    # ── Handle popup / modal that appears after Next ──────────────────────────
    await _handle_popup_after_next(page, log, max_wait_s=10.0)

    # ── Wait for page to stabilise before handing off to Phase 5 ─────────────
    log("Waiting for page to stabilise after Next...")
    await asyncio.sleep(1.5)
    log("Phase 4 complete.")
    return True
