# app/portals/oic/automation/claim_search_module.py
"""
claim_search_module.py — Generate Assessment: Search Step (Step 1 of 5)
Oriental Insurance Company (OIC) portal.

Handles:
  1. Select Claim Type dropdown (Cashless / Reimbursement)
     - Uses same payment_to logic as Website 1 (UIIC)
     - REPAIRER → Cashless, INSURED → Reimbursement
  2. Fill Claim Number (always — never Policy Number)
  3. Click Next button

DOM References (from HTML_DOM.txt):
  - Claim Type: PrimeNG p-dropdown #claimType
  - Claim Number: PrimeNG p-inputtext #claimNumber
  - Next button: button.next-btn[aria-label="Next"] (disabled until valid)
"""

import asyncio
import logging
from typing import Callable

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts
from app.data.data_model import ClaimData
from app.portals.oic.automation import popup_service
from app.portals.oic.automation.ui_utils import capture_error_screenshot, fill_input_with_delay
from app.utils import load_automation_defaults

logger = logging.getLogger(__name__)


def _resolve_claim_type(claim: ClaimData, defaults: dict | None = None) -> str:
    """
    Resolve Claim Type for OIC dropdown using same logic as Website 1 (UIIC).

    payment_to values from Excel scanning:
      - "REPAIRER" or "DEALER" → Cashless
      - "INSURED" → Reimbursement
      - Empty/unknown → defaults to Cashless (most common motor claim scenario)

    Returns: "CASHLESS" or "REIMBURSEMENT" (matching OIC dropdown option text).
    """
    payment_raw = str(claim.payment_to).strip().lower()

    if "insured" in payment_raw or "reimbursement" in payment_raw:
        return "REIMBURSEMENT"

    # Default: REPAIRER, DEALER, empty, or any other value → Cashless
    defaults = defaults or {}
    return str(defaults.get("unknown_claim_type_default", "CASHLESS") or "CASHLESS")


async def fill_claim_search(
    page: Page,
    claim: ClaimData,
    log,
    stop_cb: Callable[[], bool] = lambda: False,
    field_delay_ms: int = 30,
) -> bool:
    """
    Fill the Generate Assessment search form (Step 1):
      1. Select Claim Type from PrimeNG dropdown
      2. Fill Claim Number
      3. Click Next

    Returns True on success, False on failure.
    """
    _log_info = lambda m: log.info(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ℹ️ {m}")
    _log_success = lambda m: log.success(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ✅ {m}")
    _log_error = lambda m: log.error(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ❌ {m}")
    _log_warning = lambda m: log.warning(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ⚠️ {m}")

    msg = f"Initializing Generate Assessment search for claim {claim.claim_no}..."
    if isinstance(log, AutomationLogger):
        log._section = "Claim Search"
        log.info(msg)
        log.indent()
    else:
        log(f"[{_ts()}]   ℹ️ {msg}")

    if stop_cb():
        _log_warning("Stop requested before claim search.")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # ── Step 1: Select Claim Type from PrimeNG Dropdown ───────────────────────
    defaults = load_automation_defaults(portal_id=getattr(claim, "portal_id", "oic"))
    claim_type = _resolve_claim_type(claim, defaults)
    _log_info(f"🔽 [Dropdown] Selecting Claim Type: '{claim_type}' (payment_to='{claim.payment_to}')...")

    try:
        # Click the PrimeNG dropdown trigger to open the options panel
        dropdown = page.locator("#claimType")
        await dropdown.wait_for(state="visible", timeout=8000)
        await dropdown.click()
        await asyncio.sleep(0.3)

        # Wait for dropdown panel to render and select the matching option
        option = page.get_by_role("option", name=claim_type, exact=True)
        await option.wait_for(state="visible", timeout=3000)
        await option.click()
        await asyncio.sleep(0.3)

        # Verify the dropdown now shows the selected value
        selected_label = await dropdown.locator(".p-dropdown-label").inner_text()
        selected_text = selected_label.strip()

        if claim_type.lower() in selected_text.lower():
            _log_success(f"Claim Type selected → '{selected_text}'")
        else:
            _log_warning(f"Claim Type label shows '{selected_text}', expected '{claim_type}'. Continuing...")
    except Exception as exc:
        await capture_error_screenshot(page, "claim_type_select_failed", log)
        _log_error(f"Failed to select Claim Type dropdown: {exc}")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # ── Step 2: Fill Claim Number (always — skip Policy Number) ───────────────
    claim_no = str(claim.claim_no).strip()
    if not claim_no:
        _log_error("Claim Number is empty — cannot proceed.")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    _log_info(f"⌨️ [Typing] Entering Claim Number: '{claim_no}'...")

    try:
        await fill_input_with_delay(page, "#claimNumber", claim_no, "Claim Number", log, delay_ms=field_delay_ms)

        # Verify the input value
        claim_input = page.locator("#claimNumber").first
        actual_val = await claim_input.input_value()
        if actual_val.strip() == claim_no:
            _log_success(f"Claim Number filled → '{claim_no}'")
        else:
            _log_warning(f"Claim Number input shows '{actual_val}', expected '{claim_no}'.")
    except Exception as exc:
        await capture_error_screenshot(page, "claim_number_fill_failed", log)
        _log_error(f"Failed to fill Claim Number: {exc}")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # ── Step 3: Click Next Button ─────────────────────────────────────────────
    _log_info("🖱️ [Clicking] Clicking 'Next' button...")

    try:
        next_btn = page.get_by_role("button", name="Next")
        await next_btn.wait_for(state="visible", timeout=5000)

        # Wait for Next button to become enabled (disabled until form is valid)
        for attempt in range(1, 11):  # Max 10 checks over 5 seconds
            is_disabled = await next_btn.get_attribute("disabled")
            if is_disabled is None:
                break  # Button is enabled
            if attempt < 10:
                await asyncio.sleep(0.5)
        else:
            _log_warning("Next button still disabled after 5s. Attempting click anyway...")

        await next_btn.click()
        _log_info("Next button clicked. Waiting for Step 2 (Basic Details)...")
        await asyncio.sleep(1.0)

        # Dismiss any popups that appear after Next click
        await popup_service.dismiss_portal_popup(page, log, max_wait_s=1.5, context="Post-search Next")

        # M6 FIX: Verify the stepper actually advanced to Step 2
        # Check for: active step indicator change, or new form content loaded
        step2_verified = False
        for check in range(1, 7):  # Max 6 checks over 3 seconds
            try:
                # PrimeNG stepper marks the active step — check if step 2 is now active
                step2_active = await page.locator(
                    ".p-steps-item:nth-child(2).p-highlight, "
                    ".p-steps-item:nth-child(2) .p-steps-number[aria-selected='true'], "
                    ".p-steps-item:nth-child(2).ui-state-highlight"
                ).first.is_visible(timeout=500)
                if step2_active:
                    step2_verified = True
                    break
            except Exception:
                pass

            # Alternative: check if claim search form (#claimType) is gone
            try:
                search_form_gone = not await page.locator("#claimType").is_visible(timeout=300)
                if search_form_gone:
                    step2_verified = True
                    break
            except Exception:
                step2_verified = True  # Element not found = form changed
                break

            await asyncio.sleep(0.5)

        if step2_verified:
            _log_success("Generate Assessment search step completed — Step 2 (Basic Details) active.")
        else:
            _log_warning("Could not verify Step 2 activation. Search form may still be visible. Continuing...")
    except Exception as exc:
        await capture_error_screenshot(page, "next_button_click_failed", log)
        _log_error(f"Failed to click Next button: {exc}")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    if isinstance(log, AutomationLogger):
        log.outdent()

    return True
