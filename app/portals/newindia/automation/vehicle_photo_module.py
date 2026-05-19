import asyncio
import os
from typing import Callable, Optional
from playwright.async_api import Page
from app.portals.newindia.automation.ui_utils import select_dropdown_with_delay
from app.portals.newindia.automation.popup_service import dismiss_portal_popup, quick_check_and_dismiss
from app.automation.automation_logger import AutomationLogger

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

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _attach_file(page: Page, idx: int, file_path: str, log) -> bool:
    """Attach file to the file input for row idx."""
    name = f"mandatoryFiles{idx}"
    fname = os.path.basename(file_path)
    abs_path = os.path.abspath(file_path)

    if not os.path.isfile(abs_path):
        if isinstance(log, AutomationLogger):
            log.upload_failed(f"Row {idx} Photo", f"File not found: {fname}")
        else:
            log(f"  ❌ [Row {idx}] File not found: {fname}")
        return False

    try:
        file_input = page.locator(f'input[type="file"][name="{name}"]').first
        await file_input.wait_for(state="attached", timeout=6000)
        await file_input.set_input_files(abs_path)
        await asyncio.sleep(0.8)
        if isinstance(log, AutomationLogger):
            log.upload_attached(f"Row {idx} Photo", fname)
        else:
            log(f"  ✅ [Row {idx}] File attached → '{fname}'")
        return True
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.upload_failed(f"Row {idx} Photo", str(e))
        else:
            log(f"  ⚠️  [Row {idx}] File attach failed: {e}")
        return False


async def _click_plus_and_wait(page: Page, log,
                               before_count: int, timeout_s: float = 5.0) -> bool:
    """Click the + button and wait for a new row to appear in the DOM."""
    try:
        res = await page.evaluate(_JS_CLICK_PLUS)
        if not res or not res.get("ok"):
            if isinstance(log, AutomationLogger):
                log.error(f"Row addition failed: {res.get('err')}")
            else:
                log(f"  ⚠️  Plus click failed: {res}")
            return False
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Row addition error: {str(e)[:100]}")
        else:
            log(f"  ⚠️  Plus click error: {e}")
        return False

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.5)
        try:
            count = await page.evaluate(_JS_ROW_COUNT)
            if count > before_count:
                if isinstance(log, AutomationLogger):
                    log.info(f"Row added successfully (Total rows: {count})")
                else:
                    log(f"  ✅ New row added (total rows: {count})")
                return True
        except Exception:
            pass
    if isinstance(log, AutomationLogger):
        log.warning("Row count did not increase after click")
    else:
        log(f"  ⚠️  Row count did not increase after Plus click")
    return False


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
    log = None,
    stop_cb: Callable[[], bool] = lambda: False,
    field_delay_ms: int = 600
) -> bool:
    if isinstance(log, AutomationLogger):
        log.info("Starting Vehicle Photo Graph phase...")
        log.indent()
    elif log:
        log(f"Starting Phase 4 — Vehicle Photo Graph")

    try:
        await page.wait_for_selector(
            'h4.headerClip:has-text("Vehicle Photo Graph")',
            state="visible", timeout=15000
        )
        if isinstance(log, AutomationLogger):
            log.info("Phase container located.")
        else:
            log("Section visible.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Vehicle Photo section not found: {str(e)[:100]}")
        else:
            log(f"Section not found: {e}")
        return False

    await asyncio.sleep(0.8)
    if stop_cb(): return False

    chassis_file  = _find_file(claim_data, "Chassis Number Photograph",  ["chassis"])
    odometer_file = _find_file(claim_data, "Odometer Reading Photograph", ["odometer", "odo"])

    # ── ROW 0 — Chassis ──────────────────────────────────────────────────────
    # Attach chassis file first, then odometer. Upload is clicked ONCE after
    # both are attached. Each attachment is followed by an immediate popup check
    # so pre-upload alerts (file-size, duplicate) are dismissed before the
    # portal's Upload button is enabled.
    if isinstance(log, AutomationLogger):
        log.info("Row 0: Setting type → Chassis Number Photograph")
        log.indent()
    else:
        log("Setting Row 0 → Chassis...")

    await select_dropdown_with_delay(
        page, 'select[name="docType0"]', _DOCTYPE_CHASSIS,
        "Row 0 Type", log, field_delay_ms
    )

    chassis_attached = False
    if chassis_file:
        chassis_attached = await _attach_file(page, 0, chassis_file, log)
        # Dismiss any immediate portal alert (file-size / duplicate)
        await quick_check_and_dismiss(page, log, context="Chassis attach")
    else:
        if isinstance(log, AutomationLogger):
            log.warning("No Chassis photo found in source data.")
        else:
            log("  ⚠️ No Chassis file — row 0 will have empty file input.")

    if isinstance(log, AutomationLogger):
        log.outdent()

    if stop_cb(): return False

    # ── ROW 1 — Odometer (optional) ──────────────────────────────────────────
    odometer_attached = False
    if odometer_file:
        if isinstance(log, AutomationLogger):
            log.info("Row 1: Adding row for Odometer Reading Photograph")
            log.indent()
        else:
            log("Adding Row 1 for Odometer...")

        before_count = await page.evaluate(_JS_ROW_COUNT)
        if await _click_plus_and_wait(page, log, before_count):
            await select_dropdown_with_delay(
                page, 'select[name="docType1"]', _DOCTYPE_ODOMETER,
                "Row 1 Type", log, field_delay_ms
            )
            odometer_attached = await _attach_file(page, 1, odometer_file, log)
            # Dismiss any immediate portal alert after odometer attachment
            await quick_check_and_dismiss(page, log, context="Odometer attach")

        if isinstance(log, AutomationLogger):
            log.outdent()
    else:
        if isinstance(log, AutomationLogger):
            log.info("No Odometer photo found; skipping Row 1.")
        else:
            log("  ℹ️ No Odometer file found — skipping Row 1.")

    if stop_cb(): return False

    # ── Click Upload ONCE — after both chassis & odometer are attached ────────
    # A single Upload click submits all filled rows in one portal request.
    if chassis_attached or odometer_attached:
        attached_count = sum([chassis_attached, odometer_attached])
        if isinstance(log, AutomationLogger):
            log.wait(
                f"Uploading {attached_count} attached document(s) — single Upload click..."
            )
        else:
            log(f"Uploading {attached_count} attached document(s)...")

        try:
            # Give Angular a moment to register all file inputs
            await asyncio.sleep(1.0)

            upload_btn = page.locator(
                'button[data-ng-click*="uploadFileNonTieUp_quickUpdate"]'
            ).first
            await upload_btn.wait_for(state="visible", timeout=5000)

            # Poll up to 3s for Angular digest to enable the button
            for _ in range(6):
                if not await upload_btn.is_disabled():
                    break
                await asyncio.sleep(0.5)

            if await upload_btn.is_disabled():
                if isinstance(log, AutomationLogger):
                    log.warning(
                        "Upload button still disabled — files may already be "
                        "uploaded or attachment failed."
                    )
                else:
                    log("  ⚠️ Upload button is disabled.")
            else:
                await upload_btn.click()
                if isinstance(log, AutomationLogger):
                    log.success("Upload button clicked.")
                else:
                    log("  ✅ Upload button clicked.")

                # Poll for the portal's confirmation / error modal.
                # _handle_popup_after_next detects any visible modal
                # (success banner, duplicate warning, size error) and
                # dismisses it. Returns True whether or not a popup appeared.
                await dismiss_portal_popup(page, log, max_wait_s=8.0, context="Upload Multi-Row")
                await asyncio.sleep(1.0)

        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Upload button error: {str(e)[:100]}")
            else:
                log(f"  ⚠️ Error clicking Upload button: {e}")
    else:
        if isinstance(log, AutomationLogger):
            log.warning(
                "No files were successfully attached — skipping Upload click."
            )
        else:
            log("  ℹ️ No files attached — skipping upload.")

    if stop_cb(): return False

    # ── Click Next button ─────────────────────────────────────────────────────
    if isinstance(log, AutomationLogger):
        log.wait("Submitting step (Next)...")
    else:
        log("Clicking Next button...")
        
    try:
        # Use Playwright's trusted click (not JS inject) so the portal's
        # Angular click-handler fires correctly and produces the modal.
        next_btn = page.locator('#saveQuickUpdateNM')
        await next_btn.wait_for(state="visible", timeout=5000)
        await next_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        await next_btn.click()
        if isinstance(log, AutomationLogger):
            log.success("Next button clicked.")
        else:
            log("  ✅ Next button clicked.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.warning("Primary Next button not clickable; attempting JS fallback...")
        else:
            log(f"  ⚠️ Next button not found via locator, falling back to JS click: {e}")
        try:
            await page.evaluate("document.getElementById('saveQuickUpdateNM').click()")
            if isinstance(log, AutomationLogger):
                log.success("Next button clicked via JS.")
            else:
                log("  ✅ Next button clicked (JS fallback).")
        except Exception as e2:
            if isinstance(log, AutomationLogger):
                log.error(f"Next submission failed: {str(e2)[:100]}")
            else:
                log(f"  ❌ Next button click failed: {e2}")
            return False

    # ── Handle popup / modal that appears after Next ──────────────────────────
    await dismiss_portal_popup(page, log, max_wait_s=5.0, context="Vehicle Next")

    # ── Wait for page to stabilise before handing off to Phase 5 ─────────────
    if isinstance(log, AutomationLogger):
        log.wait("Waiting for page transition...")
    else:
        log("Waiting for page to stabilise after Next...")
        
    await asyncio.sleep(1.5)
    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("Vehicle Photo Graph phase completed.")
    elif log:
        log("Phase 4 complete.")
    return True
