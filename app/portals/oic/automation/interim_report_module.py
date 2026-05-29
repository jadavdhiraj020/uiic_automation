# app/portals/oic/automation/interim_report_module.py
"""
interim_report_module.py — OIC Interim Report (Step 3) automation.

Fills the three subsections of the Interim Report form:
  1. Survey Details
  2. Documentation Verification
  3. Claim Assessment and Contact Information

Then clicks "Next" to advance to Assessment of Loss (Step 4).

Architecture mirrors basic_details_module.py:
  • One public async entry point: fill_interim_report()
  • Private _fill_* helpers per subsection
  • All selectors from selectors.py
  • All UI helpers from ui_utils.py
  • Hardcoded defaults loaded from automation_defaults.json
"""

from __future__ import annotations

import asyncio
import re
from typing import Callable

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts
from app.utils import load_automation_defaults

from app.portals.oic.automation.ui_utils import (
    fill_input_with_delay,
    click_primeng_radio,
    fill_primeng_inputnumber,
    fill_mui_datepicker,
    fill_textarea_primeng,
    capture_error_screenshot,
)
from app.portals.oic.automation import selectors as S


# ── Public API ───────────────────────────────────────────────────────────────


async def fill_interim_report(
    page: Page,
    claim,
    *,
    log: AutomationLogger,
    stop_cb: Callable[[], bool],
    field_delay_ms: int = 30,
) -> bool:
    """Fill the complete Interim Report form (Step 3) on the OIC portal.

    Three subsections on a single page:
      1. Survey Details         → 2 hardcoded radios + 3 Excel fields + 1 skip
      2. Documentation Verification → 3 hardcoded radios + 2 configurable textareas
      3. Claim Assessment & Contact → 4 Excel fields + 2 hardcoded + 1 optional

    Then clicks "Next" to advance to Assessment of Loss (Step 4).

    Returns True on success, False on failure or stop.
    """
    log.section_start("Interim Report")

    # Load automation defaults once for all subsections
    defaults = load_automation_defaults(portal_id="oic")
    delay = field_delay_ms

    try:
        # ── Subsection 1: Survey Details ─────────────────────────────────
        if stop_cb():
            log.warning("Stop requested before Survey Details.")
            return False

        await _fill_survey_details(page, claim, defaults, log, delay)

        # ── Subsection 2: Documentation Verification ─────────────────────
        if stop_cb():
            log.warning("Stop requested before Documentation Verification.")
            return False

        await _fill_documentation_verification(page, claim, defaults, log, delay)

        # ── Subsection 3: Claim Assessment & Contact ─────────────────────
        if stop_cb():
            log.warning("Stop requested before Claim Assessment.")
            return False

        await _fill_claim_assessment_contact(page, claim, defaults, log, delay)

        # ── Click Next ───────────────────────────────────────────────────
        if stop_cb():
            log.warning("Stop requested before clicking Next.")
            return False

        if not await _click_next_button(page, log):
            return False

        log.section_done("Interim Report")
        return True

    except Exception as exc:
        log.error(f"Interim Report failed: {exc}")
        await capture_error_screenshot(page, "interim_report", log)
        return False


# ── Subsection 1: Survey Details ─────────────────────────────────────────────


async def _fill_survey_details(page, claim, defaults, log, delay):
    """Fill the Survey Details subsection.

    Fields:
      1. Whether Vehicle is Inspected Personally  → hardcoded radio (YES)
      2. Is Survey Completed                      → hardcoded radio (YES)
      3. Type of Settlement                       → SKIP (read-only / p-disabled)
      4. Date of Survey                           → MUI DatePicker (from Excel)
      5. Place of Survey                          → text input (from Excel)
      6. Surveyor Appointed Date                  → MUI DatePicker (from Excel)
    """
    log.info("▸ Filling Survey Details subsection")

    # 1. Whether Vehicle is Inspected Personally
    inspected = defaults.get("whether_vehicle_inspected", "YES").upper()
    sel = S.SEL_VEHICLE_INSPECTED_YES if inspected == "YES" else S.SEL_VEHICLE_INSPECTED_NO
    await click_primeng_radio(
        page, sel, "Whether Vehicle Inspected", log, delay_ms=delay
    )

    # 2. Is Survey Completed
    completed = defaults.get("is_survey_completed", "YES").upper()
    sel = S.SEL_SURVEY_COMPLETED_YES if completed == "YES" else S.SEL_SURVEY_COMPLETED_NO
    await click_primeng_radio(
        page, sel, "Is Survey Completed", log, delay_ms=delay
    )

    # 3. Type of Settlement — READ-ONLY (p-disabled), skip
    log.info("   ℹ️ [Type of Settlement] read-only field — skipped")

    # 4. Date of Survey (MUI DatePicker)
    date_of_survey = getattr(claim, "date_of_survey", "")
    if date_of_survey:
        await fill_mui_datepicker(
            page, "Date of Survey", date_of_survey,
            "Date of Survey", log, delay_ms=delay
        )
    else:
        log.field_failed("Date of Survey", "empty — no value from Excel")

    # 5. Place of Survey
    place_of_survey = getattr(claim, "place_of_survey", "")
    if place_of_survey:
        await fill_input_with_delay(
            page, S.SEL_PLACE_OF_SURVEY, place_of_survey,
            "Place of Survey", log, delay_ms=delay
        )
    else:
        log.field_failed("Place of Survey", "empty — no value from Excel")

    # 6. Surveyor Appointed Date (MUI DatePicker)
    date_of_allotment = getattr(claim, "date_of_allotment", "")
    if date_of_allotment:
        await fill_mui_datepicker(
            page, "Surveyor Appointed Date", date_of_allotment,
            "Surveyor Appointed Date", log, delay_ms=delay
        )
    else:
        log.field_failed("Surveyor Appointed Date", "empty — no value from Excel")


# ── Subsection 2: Documentation Verification ─────────────────────────────────


async def _fill_documentation_verification(page, claim, defaults, log, delay):
    """Fill the Documentation Verification subsection.

    Fields:
      1. Is Driving License Applicable                            → hardcoded radio (YES)
      2. Are DL, RC Book and Other Vehicular Documents Verified?   → hardcoded radio (YES)
      3. Remarks (for docs verified)                               → configurable textarea
      4. Is Spot Survey Done?                                      → hardcoded radio (YES)
      5. Remarks (for spot survey)                                 → configurable textarea
    """
    log.info("▸ Filling Documentation Verification subsection")

    # Each remarks field has its own key to allow independent configuration.
    docs_remarks = defaults.get("docs_verified_remarks", "okay")
    spot_remarks = defaults.get("spot_survey_remarks", "okay")

    # 1. Is Driving License Applicable
    dl_applicable = defaults.get("is_driving_license_applicable", "YES").upper()
    sel = S.SEL_DL_APPLICABLE_YES if dl_applicable == "YES" else S.SEL_DL_APPLICABLE_NO
    await click_primeng_radio(
        page, sel, "DL Applicable", log, delay_ms=delay
    )

    # 2. Are DL, RC Book and Other Vehicular Documents Verified?
    docs_verified = defaults.get("documents_verified", "YES").upper()
    sel = S.SEL_DOCS_VERIFIED_YES if docs_verified == "YES" else S.SEL_DOCS_VERIFIED_NO
    await click_primeng_radio(
        page, sel, "Documents Verified", log, delay_ms=delay
    )

    # 3. Remarks (for Documents Verified)
    await fill_textarea_primeng(
        page, S.SEL_DOCS_VERIFIED_REMARKS, docs_remarks,
        "Docs Verified Remarks", log, delay_ms=delay
    )

    # 4. Is Spot Survey Done?
    spot_survey = defaults.get("spot_survey_done", "YES").upper()
    sel = S.SEL_SPOT_SURVEY_YES if spot_survey == "YES" else S.SEL_SPOT_SURVEY_NO
    await click_primeng_radio(
        page, sel, "Spot Survey Done", log, delay_ms=delay
    )

    # 5. Remarks (for Spot Survey)
    await fill_textarea_primeng(
        page, S.SEL_SPOT_SURVEY_REMARKS, spot_remarks,
        "Spot Survey Remarks", log, delay_ms=delay
    )


# ── Subsection 3: Claim Assessment & Contact ─────────────────────────────────


async def _fill_claim_assessment_contact(page, claim, defaults, log, delay):
    """Fill the Claim Assessment and Contact Information subsection.

    Fields:
      1. Initial Loss Assessment Amount  → PrimeNG InputNumber (from Excel)
      2. Mobile Number of The Claimant   → text input (optional, from Excel)
      3. Email ID of The Claimant        → text input (optional, from Excel)
      4. Submission Date of Final Doc    → MUI DatePicker (from Excel / derived)
      5. Surveyor's Observation          → textarea (configurable default)
      6. Cause and Nature of Accident    → text input (from Excel)
      7. Particulars of Loss/Damage      → text input (configurable default)
    """
    log.info("▸ Filling Claim Assessment & Contact subsection")

    # 1. Initial Loss Assessment Amount (PrimeNG InputNumber)
    initial_loss = _clean_amount(getattr(claim, "initial_loss_amount", ""))
    if initial_loss:
        await fill_primeng_inputnumber(
            page, S.SEL_INITIAL_LOSS_AMOUNT, initial_loss,
            "Initial Loss Assessment Amount", log, delay_ms=delay
        )
    else:
        log.field_failed("Initial Loss Assessment Amount", "empty — no value from Excel")

    # 2. Mobile Number of The Claimant (optional)
    mobile = getattr(claim, "mobile_no", "")
    if mobile:
        await fill_input_with_delay(
            page, S.SEL_MOBILE_CLAIMANT, mobile,
            "Mobile Number (Claimant)", log, delay_ms=delay
        )
    else:
        log.info("   ℹ️ [Mobile Number (Claimant)] optional — skipped (empty)")

    # 3. Email ID of The Claimant (optional)
    email = getattr(claim, "email_id", "")
    if email:
        await fill_input_with_delay(
            page, S.SEL_EMAIL_CLAIMANT, email,
            "Email ID (Claimant)", log, delay_ms=delay
        )
    else:
        log.info("   ℹ️ [Email ID (Claimant)] optional — skipped (empty)")

    # 4. Submission Date of Final Document (MUI DatePicker)
    #    Priority: expected_completion_date from Excel → fall back to date_of_survey
    submission_date = (
        getattr(claim, "expected_completion_date", "") or
        getattr(claim, "date_of_survey", "")
    )
    if submission_date:
        await fill_mui_datepicker(
            page, "Submission Date of Final Document", submission_date,
            "Submission Date of Final Document", log, delay_ms=delay
        )
    else:
        log.field_failed("Submission Date of Final Document", "empty — no value available")

    # 5. Surveyor's Observation (textarea)
    #    Priority: Excel value if available → configurable default
    observation = (
        getattr(claim, "surveyor_observation", "") or
        defaults.get("surveyor_observation_default", "okay")
    )
    if await _is_editable(page, S.SEL_SURVEYOR_OBSERVATION):
        await fill_textarea_primeng(
            page, S.SEL_SURVEYOR_OBSERVATION, observation,
            "Surveyor's Observation", log, delay_ms=delay
        )
    else:
        log.info("   ℹ️ [Surveyor's Observation] field not editable — skipped")

    # 6. Cause and Nature of Accident (text input, from Excel)
    cause = getattr(claim, "cause_nature_of_accident", "")
    if cause:
        await fill_input_with_delay(
            page, S.SEL_CAUSE_NATURE_ACCIDENT, cause,
            "Cause and Nature of Accident", log, delay_ms=delay
        )
    else:
        log.field_failed("Cause and Nature of Accident", "empty — no value from Excel")

    # 7. Particulars of Loss/Damage (text input, configurable default)
    particulars = defaults.get("particulars_of_loss_damage", "As per estimate")
    await fill_input_with_delay(
        page, S.SEL_PARTICULARS_LOSS, particulars,
        "Particulars of Loss/Damage", log, delay_ms=delay
    )


# ── Navigation ───────────────────────────────────────────────────────────────


async def _click_next_button(page, log) -> bool:
    """Click the Next button to advance from Interim Report to Assessment of Loss.

    Strategy:
      1. Try selectors from selectors.py (SEL_INTERIM_NEXT constants) first,
         then fall back to common patterns from basic_details_module.
      2. After clicking, verify the page actually transitioned by waiting for
         a URL or DOM change — prevents false-True returns when validation
         errors keep the browser on Step 3.

    Returns True on success, False on failure.
    """
    log.info("▸ Clicking Next to advance to Assessment of Loss (Step 4)")

    # Ordered list of selectors to try.  The first two come from selectors.py
    # constants; the remaining are extra safety fallbacks.
    candidates = [
        S.SEL_INTERIM_NEXT,          # "button.next-btn[aria-label='Next'], button:has-text('Next')"
        "button[aria-label='Next']",
        "button.next-btn",
        "button.p-button:has-text('Next')",
        "button[type='button']:has-text('Next')",
    ]

    # Capture the URL before clicking so we can detect navigation.
    url_before = page.url

    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if not await btn.is_visible():
                continue
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            await btn.click()
            log.info("   ✅ Next button clicked — waiting for page transition")

            # ── Post-click verification ──────────────────────────────────
            # Give the portal up to 8 seconds to either change the URL or
            # render a Step-4-specific element.  If neither happens the page
            # likely stayed on Step 3 due to a validation error.
            transitioned = False
            try:
                # Strategy A: URL changed (most reliable)
                await page.wait_for_function(
                    "url => window.location.href !== url",
                    arg=url_before,
                    timeout=8000,
                )
                transitioned = True
            except Exception:
                pass

            if not transitioned:
                # Strategy B: A Step-4 heading / breadcrumb appeared in DOM
                try:
                    await page.wait_for_selector(
                        "text='Assessment of Loss'",
                        state="visible",
                        timeout=5000,
                    )
                    transitioned = True
                except Exception:
                    pass

            if transitioned:
                log.info("   ✅ Page transitioned to Assessment of Loss (Step 4)")
                return True
            else:
                log.warning(
                    "   ⚠️ Next clicked but page did not transition — "
                    "possible validation error on Interim Report form"
                )
                await capture_error_screenshot(page, "interim_next_no_transition", log)
                return False

        except Exception:
            continue  # Try next selector

    log.error("   ❌ Next button not found or not clickable")
    await capture_error_screenshot(page, "interim_next_button", log)
    return False


# ── Internal Helpers ─────────────────────────────────────────────────────────


async def _is_editable(page: Page, selector: str) -> bool:
    """Return True if the element at *selector* is editable (not disabled/read-only).

    Mirrors the _is_field_editable helper in basic_details_module.py so that
    this module can skip locked fields gracefully rather than timing out.
    """
    try:
        loc = page.locator(selector).first
        if not await loc.is_visible():
            return False
        is_locked = await loc.evaluate(
            "el => el.disabled || el.readOnly || el.hasAttribute('readonly') || "
            "el.hasAttribute('disabled') || !!el.closest('.disabled') || "
            "!!el.closest('.p-disabled') || !!el.closest('.Mui-disabled') || "
            "!!el.closest('[disabled]')"
        )
        return not is_locked
    except Exception:
        return True  # If we can't determine, attempt the fill and let it fail naturally


def _clean_amount(raw_value) -> str:
    """Clean an amount string by removing currency symbols, commas, and whitespace.

    Always returns an integer string (no decimals) or empty string if unparseable.

    Examples:
      '₹2,200'     → '2200'
      '₹ 15,000.00' → '15000'
      '2200'        → '2200'
      2200.50       → '2200'
      ''            → ''
    """
    if raw_value is None or raw_value == "":
        return ""

    # Handle numeric types directly (int/float from Excel)
    if isinstance(raw_value, (int, float)):
        try:
            return str(int(raw_value))
        except (ValueError, OverflowError):
            return ""

    val = str(raw_value).strip()
    if not val:
        return ""

    # Remove currency symbols and whitespace
    val = re.sub(r'[₹$,\s]', '', val)
    # Remove trailing decimal (.00)
    val = re.sub(r'\.0+$', '', val)

    # If it's a valid number after cleaning, return integer
    try:
        num = int(float(val))
        return str(num)
    except (ValueError, TypeError):
        return ""

