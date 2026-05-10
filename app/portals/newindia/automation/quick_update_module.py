"""
quick_update_module.py
Phase 3 implementation of New India Assurance (NIA) portal automation.
Fills the "Quick Update Details" section.
"""

import asyncio
import logging
from typing import Callable

from app.data.data_model import ClaimData
from app.automation.form_helpers import safe_fill, format_date_for_uiic

logger = logging.getLogger(__name__)

async def _select_yes_no(page, name_attr: str, value: str = "Y", log_cb: Callable = print) -> bool:
    """Helper to click a Yes/No radio button by name and value."""
    sel = f"input[name='{name_attr}'][value='{value}']"
    try:
        radio = page.locator(sel).first
        await radio.wait_for(state="attached", timeout=5000)
        # Use Javascript click because custom radio buttons might block regular clicks
        await radio.evaluate("node => node.click()")
        # Dispatch change event for Angular
        await radio.evaluate("node => node.dispatchEvent(new Event('change', {bubbles: true}))")
        await asyncio.sleep(0.5) # Wait for ng-change to trigger conditional fields
        return True
    except Exception as exc:
        log_cb(f"  ❌ Failed to select {value} for {name_attr}: {exc}")
        return False

async def fill_quick_update_details(
    page,
    claim: ClaimData,
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False
) -> bool:
    """
    Fills the Quick Update Details form.
    """
    log_cb("  📂 Opening Quick Update Details section...")
    if stop_cb(): return False
    required_ok = True

    # 1. Date of Survey Logic
    formatted_date = format_date_for_uiic(claim.date_of_survey) if claim.date_of_survey else ""
    log_cb(f"  📅 Handling Date Of Survey selection (Extracted: {formatted_date})...")
    
    if formatted_date:
        log_cb("  🔍 Matching survey date with available options...")
        radio_sel = f"input[name='dateOfSurveyRadio'][value='{formatted_date}']"
        count = await page.locator(radio_sel).count()
        if count > 0:
            log_cb("  ✅ Matching option found. Selecting directly...")
            try:
                await page.locator(radio_sel).first.evaluate("node => node.click()")
                await page.locator(radio_sel).first.evaluate("node => node.dispatchEvent(new Event('change', {bubbles: true}))")
                await asyncio.sleep(0.5)
            except Exception as exc:
                log_cb(f"  ❌ Failed to select matching Date Of Survey: {exc}")
                required_ok = False
        else:
            log_cb("  ⚠️ No matching option found. Selecting 'Others'...")
            others_sel = "input[name='dateOfSurveyRadio'][value='Others']"
            try:
                await page.locator(others_sel).first.evaluate("node => node.click()")
                await page.locator(others_sel).first.evaluate("node => node.dispatchEvent(new Event('change', {bubbles: true}))")
                await asyncio.sleep(1) # wait for text field to appear
            except Exception as exc:
                log_cb(f"  ❌ Failed to select 'Others' for Date Of Survey: {exc}")
                required_ok = False
            
            # Fill the text field that appears
            date_input_sel = "input[name='dateOfSurvey'], input[data-ng-model*='surveyDate']:not([type='radio'])"
            if not await safe_fill(page, date_input_sel, formatted_date, "Date of Survey Input", log_cb=log_cb):
                required_ok = False
    else:
        log_cb("  ❌ No Date of Survey extracted from Excel.")
        required_ok = False

    if stop_cb(): return False

    # 2. Time of Survey
    time_val = f"{claim.time_hh or '10'}:{claim.time_mm or '00'}"
    log_cb("  ⌚ Filling Time Of Survey...")
    required_ok = await safe_fill(page, "input[name='timeOfSurvey']", time_val, "Time of Survey", log_cb=log_cb) and required_ok
    
    if stop_cb(): return False

    # 3. Place of Survey
    log_cb("  📍 Filling Place Of Survey...")
    required_ok = await safe_fill(page, "textarea[name='placeOfSurvey']", claim.place_of_survey or "Workshop", "Place of Survey", log_cb=log_cb) and required_ok

    if stop_cb(): return False

    # 4. Survey Completed -> ALWAYS YES
    log_cb("  ✅ Selecting mandatory Yes options...")
    required_ok = await _select_yes_no(page, "radioDataCompleted", "Y", log_cb) and required_ok

    # 5. Mandatory Yes/No fields
    for radio_name in [
        "radioDrivingLicenseApplicable",
        "radioDrivingLicense",
        "radioRCbook",
        "radioDrivingLicensePar",
        "radioRCbookPar",
        "isCloseProximityBreakIn",
        "inspectionReportUploaded",
    ]:
        required_ok = await _select_yes_no(page, radio_name, "Y", log_cb) and required_ok

    if stop_cb(): return False

    # 6. Remarks
    log_cb("  📝 Filling Remarks...")
    remarks_text = claim.surveyor_observation or "Survey completed. All documents verified."
    required_ok = await safe_fill(page, "textarea[name='remarks']", remarks_text, "Remarks", log_cb=log_cb) and required_ok

    if stop_cb(): return False

    # 7. Mobile Number
    log_cb("  📱 Filling Claimant Mobile Number...")
    if claim.mobile_no:
        await safe_fill(page, "input[name='mobileNo']", claim.mobile_no, "Mobile Number", log_cb=log_cb)

    # 8. Email ID
    log_cb("  📧 Filling Claimant Email ID...")
    if claim.email_id:
        await safe_fill(page, "input[name='emailId']", claim.email_id, "Email ID", log_cb=log_cb)

    if stop_cb(): return False

    # 9. Expected Date of Completion
    log_cb("  📅 Filling Expected Completion Date (using Date of Survey)...")
    if formatted_date:
        required_ok = await safe_fill(page, "input[name='expectedDateOfRepair']", formatted_date, "Expected Completion Date", log_cb=log_cb) and required_ok

    if not required_ok:
        log_cb("  ❌ Phase 3 completed with required field failures.")
        return False

    log_cb("  🏁 Phase 3 completed successfully.")
    return True
