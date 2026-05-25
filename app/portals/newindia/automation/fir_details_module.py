import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay
)
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

async def fill_fir_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False
    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))
    missing_text_default = str(defaults.get("missing_text_default", "NA") or "NA")

    if isinstance(log, AutomationLogger):
        log.info("Opening FIR Details section...")
        log.indent()
    else:
        log(f"Opening FIR Details section...")
    
    # Click to expand FIR Details accordion
    try:
        acc_heading = page.locator('a.accordion-toggle:has-text("FIR Details")').first
        await acc_heading.wait_for(state="visible", timeout=10000)
        
        # Check if collapsed
        parent_div = page.locator('div.panel-heading').filter(has=acc_heading).first
        is_collapsed = 'collapsed' in await parent_div.get_attribute('class')
        if is_collapsed:
            await acc_heading.click()
            await asyncio.sleep(1.5)
            if isinstance(log, AutomationLogger):
                log.success("Accordion expanded.")
            else:
                log(f"   ✅ Expanded FIR Details.")
        else:
            if isinstance(log, AutomationLogger):
                log.info("Accordion already expanded.")
            else:
                log(f"   ℹ️ FIR Details already expanded.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Expansion attempt failed: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Could not expand FIR Details: {e}")

    if stop_cb(): return False

    # 1. FIR Number
    try:
        val = data.fir_number or missing_text_default
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.firNo"]', val, "FIR Number", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"FIR Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling FIR Number: {e}")

    if stop_cb(): return False

    # 2. FIR Date
    try:
        val = data.fir_date
        if val:
            await fill_input_with_delay(page, 'input[name="firDate"]', val, "FIR Date", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("FIR Date missing; skipping (Optional).")
            else:
                log(f"   ⏭️ [FIR Date] — Optional, not in Excel. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"FIR Date field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling FIR Date: {e}")

    if stop_cb(): return False

    # 3. Police Station Name
    try:
        val = data.police_station_name or missing_text_default
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.policeStation"]', val, "Station Name", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Police Station field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Police Station Name: {e}")

    if stop_cb(): return False

    # 4. Charged U/S Motor Vehicle act
    try:
        val = data.charged_us_motor_vehicle_act or missing_text_default
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.chargedUSMotorVehAct"]', val, "Charged U/S MV Act", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"MV Act field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Charged U/S Motor Vehicle Act: {e}")

    if stop_cb(): return False

    # 5. Charged U/S IPC
    try:
        val = data.charged_us_ipc or missing_text_default
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.chargedUSIPC"]', val, "Charged U/S IPC", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"IPC field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Charged U/S IPC: {e}")

    if stop_cb(): return False

    # 6. Whether driver without license ? (Mandatory)
    try:
        val = data.whether_driver_without_license
        if val:
            normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
            await select_dropdown_with_delay(page, 'select[name="Whether driver without license ?"]', normalized, "Driver w/o License", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Driver Without License status missing from source data.")
            else:
                log("   ⚠️ Whether driver without license missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"License Status dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Whether Driver Without License: {e}")

    if stop_cb(): return False

    # 7. Any Previous Police Records ? (Optional)
    try:
        val = data.any_previous_police_records
        if val:
            normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
            await select_dropdown_with_delay(page, 'select[data-ng-model="surveyorData.worklist.additionalDetails.prevPoliceRecords"]', normalized, "Police Records", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Police Records missing; skipping (Optional).")
            else:
                log(f"   ⏭️ [Previous Police Records] — Optional, not in Excel. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Police Records dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Previous Police Records: {e}")

    if stop_cb(): return False

    # 8. Is there any TP claim? (Mandatory)
    try:
        val = data.is_there_any_tp_claim
        if val:
            normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
            await select_dropdown_with_delay(page, 'select[name="Is there any TP claim?"]', normalized, "TP Claim", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("TP Claim status missing from source data.")
            else:
                log("   ⚠️ Is there any TP claim missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"TP Claim dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting TP Claim: {e}")

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("FIR Details phase completed.")
    else:
        log(f" ✅ FIR Details completed successfully.")
    return True
