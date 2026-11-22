from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay,
    open_additional_section, record_additional_issue,
)
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

async def fill_fir_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False
    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))
    missing_text_default = str(defaults.get("missing_text_default", "NA") or "NA")

    if isinstance(log, AutomationLogger):
        log._section = "FIR Details"
        log.info("Opening FIR Details section...")
        log.indent()
    else:
        log(f"Opening FIR Details section...")
    
    if not await open_additional_section(page, "FIR Details", log):
        if isinstance(log, AutomationLogger):
            log.outdent()
        return not stop_cb()

    if stop_cb():
        return False

    # 1. Is there any TP claim? (Row 1 Col 1 - Mandatory)
    try:
        raw_val = data.is_there_any_tp_claim
        val = raw_val or str(defaults.get("is_there_any_tp_claim") or "No")
        source = "Excel" if raw_val else "Default"
        normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
        await select_dropdown_with_delay(
            page, 'select[name="Is there any TP claim?"]', normalized,
            "TP Claim", log, field_delay_ms, source=source,
        )
    except Exception:
        record_additional_issue(log, "Is there any TP claim?")

    if stop_cb(): return False

    # 2. FIR Number
    try:
        val = data.fir_number or missing_text_default
        src = "Excel" if data.fir_number else "Default"
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.firNo"]', val, "FIR Number", log, field_delay_ms, source=src)
    except Exception:
        record_additional_issue(log, "FIR Number")

    if stop_cb(): return False

    # 2. FIR Date
    try:
        val = data.fir_date
        if val:
            await fill_input_with_delay(page, 'input[name="firDate"]', val, "FIR Date", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("FIR Date", reason="Missing from Excel")
            else:
                log(f"   ⏭️ [FIR Date] — Optional, not in Excel. Skipping.")
    except Exception:
        record_additional_issue(log, "FIR Date")

    if stop_cb(): return False

    # 3. Police Station Name
    try:
        val = data.police_station_name or missing_text_default
        src = "Excel" if data.police_station_name else "Default"
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.policeStation"]', val, "Station Name", log, field_delay_ms, source=src)
    except Exception:
        record_additional_issue(log, "Police Station")

    if stop_cb(): return False

    # 4. Charged U/S Motor Vehicle act
    try:
        val = data.charged_us_motor_vehicle_act or missing_text_default
        src = "Excel" if data.charged_us_motor_vehicle_act else "Default"
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.chargedUSMotorVehAct"]', val, "Charged U/S MV Act", log, field_delay_ms, source=src)
    except Exception:
        record_additional_issue(log, "Charged Under Motor Vehicle Act")

    if stop_cb(): return False

    # 5. Charged U/S IPC
    try:
        val = data.charged_us_ipc or missing_text_default
        src = "Excel" if data.charged_us_ipc else "Default"
        await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.chargedUSIPC"]', val, "Charged U/S IPC", log, field_delay_ms, source=src)
    except Exception:
        record_additional_issue(log, "Charged Under IPC")

    if stop_cb(): return False

    # 6. Whether driver without license ? (Mandatory)
    try:
        value = str(defaults.get("driver_without_license") or "No")
        await select_dropdown_with_delay(
            page, 'select[name="Whether driver without license ?"]', value,
            "Whether driver without license?", log, field_delay_ms, source="Default",
        )
    except Exception:
        record_additional_issue(log, "Whether driver without license?")

    if stop_cb(): return False

    # 7. Any Previous Police Records ? (Optional)
    try:
        val = data.any_previous_police_records
        if val:
            normalized = "Yes" if str(val).strip().lower() == "yes" else "No"
            await select_dropdown_with_delay(page, 'select[data-ng-model="surveyorData.worklist.additionalDetails.prevPoliceRecords"]', normalized, "Police Records", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Police Records", reason="Missing from Excel")
            else:
                log(f"   ⏭️ [Previous Police Records] — Optional, not in Excel. Skipping.")
    except Exception:
        record_additional_issue(log, "Previous Police Records")

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("FIR Details phase completed.")
    else:
        log(f" ✅ FIR Details completed successfully.")
    return True
