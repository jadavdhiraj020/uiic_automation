"""
interim_report.py
Fills the "Interim Report" tab of the Claim Survey form.
All 14+ fields are filled from the ClaimData object.
"""
import asyncio
import logging
from typing import Callable
from app.data.data_model import ClaimData

logger = logging.getLogger(__name__)

SEL_TAB_INTERIM = "a:has-text('Interim Report'), li a[href*='interim'], .nav-tabs a:has-text('Interim')"


async def _click_tab(page, log_cb):
    log_cb("📑 Clicking 'Interim Report' tab...")
    await page.locator(SEL_TAB_INTERIM).first.click()
    await asyncio.sleep(2)


async def _fill_text(page, selectors: list, value: str, label: str, log_cb: Callable):
    """Try each selector until one works. Clears, types, and blurs."""
    if not value:
        return
    for sel in selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=3000)
            await el.triple_click()
            await el.fill(value)
            await el.press("Tab")
            await asyncio.sleep(0.3)
            log_cb(f"  ✅ {label}: {value}")
            return
        except Exception:
            continue
    log_cb(f"  ⚠️  Could not fill '{label}' — selector not found")


async def _select_option(page, selectors: list, value: str, label: str, log_cb: Callable):
    for sel in selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=3000)
            try:
                await el.select_option(label=value)
            except Exception:
                await el.select_option(value=value)
            await asyncio.sleep(0.3)
            log_cb(f"  ✅ {label}: {value}")
            return
        except Exception:
            continue
    log_cb(f"  ⚠️  Could not select '{label}'")


async def _click_radio_yes(page, field_label_contains: str, log_cb: Callable):
    """Find a Yes radio near a label containing field_label_contains."""
    try:
        # Strategy 1: label-adjacent radio
        label_el = page.locator(f"label:has-text('{field_label_contains}'), td:has-text('{field_label_contains}')").first
        parent = label_el.locator("xpath=ancestor::tr | ancestor::div[contains(@class,'form-group')]").first
        yes_radio = parent.locator("input[type='radio'][value='Y'], input[type='radio'][value='Yes'], input[type='radio']:near(label:has-text('Yes'))").first
        await yes_radio.click()
        await asyncio.sleep(0.2)
        log_cb(f"  ✅ {field_label_contains}: Yes")
        return
    except Exception:
        pass
    # Strategy 2: use ng-model attribute
    try:
        yes_radio = page.locator(
            f"[ng-model*='{field_label_contains.lower().replace(' ', '')}'] input[value='Y'],"
            f"[ng-model*='{field_label_contains.lower().replace(' ', '')}'] input[value='Yes']"
        ).first
        await yes_radio.click()
        await asyncio.sleep(0.2)
        log_cb(f"  ✅ {field_label_contains}: Yes (ng-model)")
    except Exception as e:
        log_cb(f"  ⚠️  Could not set Yes for '{field_label_contains}': {e}")


async def fill_interim_report(
    page,
    claim: ClaimData,
    log_cb: Callable[[str], None] = print,
):
    await _click_tab(page, log_cb)
    log_cb("✏️  Filling Interim Report fields...")

    # Type of Settlement
    await _select_option(
        page,
        ["select[ng-model*='settlement'], select[ng-model*='Settlement'], #typeOfSettlement"],
        claim.type_of_settlement,
        "Type of Settlement", log_cb
    )

    # Date of Survey
    await _fill_text(
        page,
        ["input[ng-model*='dateOfSurvey'], input[name*='dateOfSurvey'], #dateOfSurvey"],
        claim.date_of_survey,
        "Date of Survey", log_cb
    )

    # Time HH
    await _select_option(
        page,
        ["select[ng-model*='surveyTimeHH'], select[ng-model*='timeHH'], #surveyTimeHH"],
        claim.time_hh,
        "Time HH", log_cb
    )

    # Time MM
    await _select_option(
        page,
        ["select[ng-model*='surveyTimeMM'], select[ng-model*='timeMM'], #surveyTimeMM"],
        claim.time_mm,
        "Time MM", log_cb
    )

    # Odometer
    await _fill_text(
        page,
        ["input[ng-model*='odometer'], input[ng-model*='Odometer'], #odometerReading"],
        claim.odometer,
        "Odometer Reading", log_cb
    )

    # Place of Survey
    await _fill_text(
        page,
        ["input[ng-model*='placeOfSurvey'], input[ng-model*='PlaceOfSurvey'], #placeOfSurvey"],
        claim.place_of_survey,
        "Place of Survey", log_cb
    )

    # Yes/No radio fields
    radio_fields = [
        "vehicle is inspected",
        "Survey Completed",
        "driving license applicable",
        "Driving License verified",
        "RC Book verified",
    ]
    for field in radio_fields:
        await _click_radio_yes(page, field, log_cb)

    # Initial Loss Assessment Amount
    await _fill_text(
        page,
        ["input[ng-model*='initialLoss'], input[ng-model*='InitialLoss'], #initialLossAmount"],
        claim.initial_loss_amount,
        "Initial Loss Amount", log_cb
    )

    # Mobile No
    await _fill_text(
        page,
        ["input[ng-model*='mobileNo'], input[ng-model*='mobile'], #mobileNo"],
        claim.mobile_no,
        "Mobile No", log_cb
    )

    # Email ID
    await _fill_text(
        page,
        ["input[ng-model*='emailId'], input[ng-model*='email'], #emailId"],
        claim.email_id,
        "Email ID", log_cb
    )

    # Expected Date of Completion
    await _fill_text(
        page,
        ["input[ng-model*='expectedDate'], input[ng-model*='Expected'], #expectedCompletionDate"],
        claim.expected_completion_date,
        "Expected Completion Date", log_cb
    )

    # Surveyor's Observation
    await _fill_text(
        page,
        ["textarea[ng-model*='observation'], textarea[ng-model*='Observation'], #surveyorObservation"],
        claim.surveyor_observation,
        "Surveyor's Observation", log_cb
    )

    log_cb("✅ Interim Report tab complete.")
    await asyncio.sleep(0.5)
