# app/portals/oic/automation/claim_search_module.py
"""
claim_search_module.py — Generate Assessment: Search Step (Step 1 of 5)
Oriental Insurance Company (OIC) portal.

Handles:
  1. Select Claim Type dropdown (Cashless / Reimbursement)
     - Uses same payment_to logic as Website 1 (UIIC)
     - REPAIRER → Cashless, INSURED → Reimbursement
  2. Fill Policy Number, or Claim Number if the policy is unavailable
  3. Click Next button

DOM References (from HTML_DOM.txt):
  - Claim Type: PrimeNG p-dropdown #claimType
  - Policy Number: PrimeNG p-inputtext #policyNumber
  - Claim Number: PrimeNG p-inputtext #claimNumber
  - Next button: button.next-btn[aria-label="Next"] (disabled until valid)
"""

import logging
from typing import Callable

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts
from app.data.data_model import ClaimData
from app.portals.oic.automation.recovery import field_problem, field_was_handled
from app.portals.oic.automation.selectors import SEL_CLAIM_NUMBER_INPUT, SEL_CLAIM_TYPE_DROPDOWN, SEL_NEXT_BTN, SEL_POLICY_NUMBER_INPUT
from app.portals.oic.automation.ui_utils import advance_form, capture_error_screenshot, fill_input_with_delay, select_primeng_dropdown
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
      2. Fill Policy Number, or Claim Number if no policy number is available
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

    if not await select_primeng_dropdown(
        page, SEL_CLAIM_TYPE_DROPDOWN, claim_type, "Claim Type", log, field_delay_ms, exact=True,
    ):
        if isinstance(log, AutomationLogger):
            log.outdent()
        return False

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # ── Step 2: Search by policy first; use claim only when policy is absent ──
    policy_number = str(getattr(claim, "policy_number", "") or "").strip()
    claim_no = str(claim.claim_no or "").strip()
    if not policy_number and not claim_no:
        _log_error("Policy Number and Claim Number are both empty — cannot proceed.")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    field_name, selector, search_value = (
        ("Policy Number", SEL_POLICY_NUMBER_INPUT, policy_number)
        if policy_number else ("Claim Number", SEL_CLAIM_NUMBER_INPUT, claim_no)
    )
    _log_info(f"⌨️ [Typing] Entering {field_name}: '{search_value}'...")

    try:
        await fill_input_with_delay(page, selector, search_value, field_name, log, delay_ms=field_delay_ms)

        if not field_was_handled(page, log, field_name):
            actual_val = await page.locator(selector).first.input_value()
            if actual_val.strip() != search_value:
                raise ValueError(f"{field_name} did not retain the entered value.")
            _log_success(f"{field_name} filled → '{search_value}'")
    except Exception as exc:
        await capture_error_screenshot(page, "search_number_fill_failed", log)
        _log_error(f"App3 could not enter {field_name}.")
        if not await field_problem(page, log, field_name, str(exc)):
            if isinstance(log, AutomationLogger): log.outdent()
            return False

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # ── Step 3: Click Next Button ─────────────────────────────────────────────
    advanced = await advance_form(
        page, log, SEL_NEXT_BTN, "Next", "basic", stop_cb, "claim_search_next_no_transition",
    )
    if advanced:
        _log_success("Basic Details is open.")
    if isinstance(log, AutomationLogger):
        log.outdent()
    return advanced
