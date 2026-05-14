import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay
)
from app.automation.automation_logger import _ts

async def fill_fir_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    log(f"[{_ts()}]  📝 Opening FIR Details section...")
    
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
            log(f"[{_ts()}]   ✅ Expanded FIR Details.")
        else:
            log(f"[{_ts()}]   ℹ️ FIR Details already expanded.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Could not expand FIR Details: {e}")

    if stop_cb(): return False

    # 1. FIR Number
    try:
        val = data.fir_number
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.firNo"]', val, "FIR Number", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⏭️ [FIR Number] — Optional, not in Excel. Skipping.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling FIR Number: {e}")

    if stop_cb(): return False

    # 2. FIR Date
    try:
        val = data.fir_date
        if val:
            await fill_input_with_delay(page, 'input[name="firDate"]', val, "FIR Date", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⏭️ [FIR Date] — Optional, not in Excel. Skipping.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling FIR Date: {e}")

    if stop_cb(): return False

    # 3. Police Station Name
    try:
        val = data.police_station_name
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.policeStation"]', val, "Police Station", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⏭️ [Police Station] — Optional, not in Excel. Skipping.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling Police Station Name: {e}")

    if stop_cb(): return False

    # 4. Charged U/S Motor Vehicle act
    try:
        val = data.charged_us_motor_vehicle_act
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.chargedUSMotorVehAct"]', val, "Charged U/S MV Act", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⏭️ [Charged U/S MV Act] — Optional, not in Excel. Skipping.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling Charged U/S Motor Vehicle Act: {e}")

    if stop_cb(): return False

    # 5. Charged U/S IPC
    try:
        val = data.charged_us_ipc
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.chargedUSIPC"]', val, "Charged U/S IPC", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⏭️ [Charged U/S IPC] — Optional, not in Excel. Skipping.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling Charged U/S IPC: {e}")

    if stop_cb(): return False

    # 6. Whether driver without license ? (Mandatory)
    try:
        val = data.whether_driver_without_license
        if val:
            normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
            await select_dropdown_with_delay(page, 'select[name="Whether driver without license ?"]', normalized, "Driver Without License", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ Whether driver without license missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error selecting Whether Driver Without License: {e}")

    if stop_cb(): return False

    # 7. Any Previous Police Records ? (Optional)
    try:
        val = data.any_previous_police_records
        if val:
            normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
            await select_dropdown_with_delay(page, 'select[data-ng-model="surveyorData.worklist.additionalDetails.prevPoliceRecords"]', normalized, "Previous Records", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⏭️ [Previous Police Records] — Optional, not in Excel. Skipping.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error selecting Previous Police Records: {e}")

    if stop_cb(): return False

    # 8. Is there any TP claim? (Mandatory)
    try:
        val = data.is_there_any_tp_claim
        if val:
            normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
            await select_dropdown_with_delay(page, 'select[name="Is there any TP claim?"]', normalized, "TP Claim", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ Is there any TP claim missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error selecting TP Claim: {e}")

    log(f"[{_ts()}]  ✅ FIR Details completed successfully.")
    return True
