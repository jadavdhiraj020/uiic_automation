from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.field_values import normalize_driver_license_number
from app.portals.newindia.automation.ui_utils import (
    click_radio_with_delay, fill_input_with_delay, select_dropdown_with_delay, format_date_ddmmyyyy,
    open_additional_section, record_additional_issue,
)
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

_PARKED = 'select[name="Was the vehicle parked during accident ?"]'
_RELATIONSHIP = 'select#relationship, select[name="Relationship of the driver with the Insured"]'

async def fill_driver_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False
    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))

    if isinstance(log, AutomationLogger):
        log._section = "Driver Details"
        log.info("Opening Driver Details section...")
        log.indent()
    else:
        log(f"Opening Driver Details section...")
    
    try:
        return await _fill_driver_details(page, data, log, stop_cb, field_delay_ms, defaults)
    finally:
        if isinstance(log, AutomationLogger):
            log.outdent()


async def _fill_driver_details(page, data, log, stop_cb, field_delay_ms, defaults):
    if not await open_additional_section(page, "Driver Details", log):
        return not stop_cb()

    # Remaining driver fields are conditional on the portal keeping No.
    try:
        await select_dropdown_with_delay(
            page, _PARKED, "No", "Was the vehicle parked during accident?",
            log, field_delay_ms, source="Calculated",
        )
        parked = await page.locator(f'{_PARKED}:visible').input_value(timeout=1500)
    except Exception:
        record_additional_issue(log, "Was the vehicle parked during accident?")
        return not stop_cb()
    if parked.rsplit(":", 1)[-1].strip().casefold() != "no":
        return not stop_cb()

    if stop_cb(): return False

    # 2. Relationship with Insured (Dynamic from Excel)
    try:
        val = data.driver_relationship_with_insured

        if val:
            await select_dropdown_with_delay(
                page,
                _RELATIONSHIP, val, "Relationship with Insured", log, field_delay_ms, source="Excel"
            )
        else:
            relationship_default = str(defaults.get("relationship_with_insured", "Self") or "Self")
            if isinstance(log, AutomationLogger):
                log.warning(f"Relationship missing from data; defaulting to '{relationship_default}'.")
            else:
                log(f"   ⚠️ Relationship with Insured missing from Excel, defaulting to '{relationship_default}'")
            await select_dropdown_with_delay(
                page,
                _RELATIONSHIP, relationship_default, "Relationship with Insured", log, field_delay_ms, source="Default"
            )
    except Exception:
        record_additional_issue(log, "Relationship with Insured")

    if stop_cb(): return False

    # 3. License Type of Driver
    try:
        val = data.license_type_of_driver
        if val:
            await select_dropdown_with_delay(page, 'select[name="License Type of Driver"]', val, "License Type", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("License Type", reason="Missing from Excel")
            else:
                log("   ⚠️ License Type of Driver missing from Excel.")
    except Exception:
        record_additional_issue(log, "License Type of Driver")

    if stop_cb(): return False

    # 4. DOB of Driver
    try:
        val = data.dob_of_driver
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="DOB of Driver"]', formatted_date, "Driver DOB", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Driver DOB", reason="Missing from Excel")
            else:
                log("   ⚠️ DOB of Driver missing from Excel.")
    except Exception:
        record_additional_issue(log, "Date of Birth")

    if stop_cb(): return False

    # 5. Driver Name
    try:
        val = data.driver_name
        if val:
            await fill_input_with_delay(page, 'input[name="Driver Name"]', val, "Driver Name", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Driver Name", reason="Missing from Excel")
            else:
                log("   ⚠️ Driver Name missing from Excel.")
    except Exception:
        record_additional_issue(log, "Driver Name")

    if stop_cb(): return False

    # 6. Age of Driver
    try:
        val = data.age_of_driver
        if val:
            await fill_input_with_delay(page, 'input[name="Age of Driver"]', val, "Driver Age", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Driver Age", reason="Missing from Excel")
            else:
                log("   ⚠️ Age of Driver missing from Excel.")
    except Exception:
        record_additional_issue(log, "Age of Driver")

    if stop_cb(): return False

    # 7. Is the motor driving license valid for type of vehicle (ALWAYS YES)
    try:
        name = "Is the motor driving license valid for the type of vehicle on the date of accident?"
        if await page.locator(f'input[name="{name}"][value="Y"]').count():
            await click_radio_with_delay(page, name, "Y", "License Validation", log, field_delay_ms, source="Calculated")
    except Exception:
        record_additional_issue(log, "Driving License Valid for Vehicle Type")

    if stop_cb(): return False

    # 8. License Issuing Authority
    try:
        val = data.license_issuing_authority
        if val:
            await fill_input_with_delay(page, 'input[name="License Issuing Authority"]', val, "Issuing Authority", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Issuing Authority", reason="Missing from Excel")
            else:
                log("   ⚠️ License Issuing Authority missing from Excel.")
    except Exception:
        record_additional_issue(log, "License Issuing Authority")

    if stop_cb(): return False

    # 9. Driver driving License Number
    try:
        val = normalize_driver_license_number(data.driver_license_number)
        if val:
            await fill_input_with_delay(page, 'input[name="Driver driving License Number"]', val, "License No", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("License No", reason="Missing from Excel")
            else:
                log("   ⚠️ License Number missing from Excel.")
    except Exception:
        record_additional_issue(log, "Driver License Number")

    if stop_cb(): return False

    # 10. Driver driving License Issue Date
    try:
        val = data.driver_license_issue_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="Driver driving License Issue Date"]', formatted_date, "Issue Date", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Issue Date", reason="Missing from Excel")
            else:
                log("   ⚠️ License Issue Date missing from Excel.")
    except Exception:
        record_additional_issue(log, "Driver License Issue Date")

    if stop_cb(): return False

    # 11. Driver driving License Expiry Date
    try:
        val = data.driver_license_expiry_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="Driver driving License Expiry Date"]', formatted_date, "Expiry Date", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Expiry Date", reason="Missing from Excel")
            else:
                log("   ⚠️ License Expiry Date missing from Excel.")
    except Exception:
        record_additional_issue(log, "Driver License Expiry Date")

    if stop_cb(): return False

    # 12. Badge Number (Optional)
    try:
        val = data.badge_number
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.badgeNo"]', val, "Badge No", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Badge No", reason="Missing from Excel")
            else:
                log("   ⏭️ [Badge Number] — Optional, not in Excel. Skipping.")
    except Exception:
        record_additional_issue(log, "Badge Number")

    if isinstance(log, AutomationLogger):
        log.success("Driver Details phase completed.")
    else:
        log(f" ✅ Driver Details completed successfully.")
    return True
