import asyncio
import re
from typing import Callable, Optional
from playwright.async_api import Page
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, click_radio_with_delay
)
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

# ── JavaScript helpers ────────────────────────────────────────────────────────

# Get all date radio values
_JS_DATE_VALUES = """
() => Array.from(document.querySelectorAll('input[name="dateOfSurveyRadio"]'))
          .map(r => r.value)
"""

# Read radio checked state
_JS_IS_CHECKED = """
([name, value]) => {
    const r = document.querySelector(`input[name="${name}"][value="${value}"]`);
    return r ? r.checked : null;
}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

async def _ensure_yes(page: Page, name: str, label: str,
                      log, delay_ms: int = 600) -> None:
    """Check current state; only click Yes if not already checked."""
    try:
        count = await page.locator(f'input[name="{name}"]').count()
        if not count:
            if isinstance(log, AutomationLogger):
                log.info(f"[{label}] field not found in DOM.")
            else:
                log(f"   ⏭  [{label}] not in DOM")
            return
        already = await page.evaluate(_JS_IS_CHECKED, [name, "Y"])
        if already:
            if isinstance(log, AutomationLogger):
                log.info(f"[{label}] already set to YES.")
            else:
                log(f"   ✔  [{label}] already YES")
            return
        await click_radio_with_delay(page, name, "Y", label, log, delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"[{label}] toggle error: {str(e)[:100]}")
        else:
            log(f"   ⚠️  [{label}] error: {e}")


from app.data.data_model import clean_mobile_number as _clean_mobile_10


def _normalise_time(raw: str) -> str:
    """Normalize time to HH:MM (24-hour format) for Website 2."""
    s = str(raw).strip()
    # Check for AM/PM format first
    time_match = re.search(r"(\d{1,2})[.:\s]?(\d{2})?\s*([aA]\.?[mM]\.?|[pP]\.?[mM]\.?)", s)
    if time_match:
        h = int(time_match.group(1))
        m = time_match.group(2) or "00"
        ampm = time_match.group(3).replace(".", "").lower()
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{int(m):02d}"
    
    # Check for direct HH:MM 24-hour format
    m24 = re.search(r"\b([01]?\d|2[0-3])[.:\s]([0-5]\d)\b", s)
    if m24:
        return f"{int(m24.group(1)):02d}:{int(m24.group(2)):02d}"
        
    # Fallback to standard regex match or first 5 chars
    m = re.match(r"(\d{1,2})[:\.\s](\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return s[:5]


# ── Public entry point ────────────────────────────────────────────────────────

async def fill_quick_update_details(
    page: Page,
    claim_data,
    log = None,
    stop_cb: Callable[[], bool] = lambda: False,
    field_delay_ms: int = 600
) -> bool:
    defaults = load_automation_defaults(portal_id=getattr(claim_data, "portal_id", "newindia"))

    if isinstance(log, AutomationLogger):
        log.info("Starting Quick Update Details phase...")
        log.indent()
    elif log:
        log(f"Starting Phase 3 — Quick Update Details")

    try:
        await page.wait_for_selector(
            'h4.headerClip:has-text("Quick Update Details")',
            state="visible", timeout=20000
        )
        if isinstance(log, AutomationLogger):
            log.info("Phase container located.")
        else:
            log("Section visible — waiting for Angular to finish rendering...")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Quick Update section not found: {str(e)[:100]}")
        else:
            log(f"Section not found: {e}")
        return False

    await asyncio.sleep(1.5)
    if stop_cb(): return False

    # ── 1. Date Of Survey ────────────────────────────────────────────────────
    date_of_survey = getattr(claim_data, "date_of_survey", "").strip()
    if date_of_survey:
        if isinstance(log, AutomationLogger):
            log.info(f"Filling Survey Date: {date_of_survey}")
        else:
            log(f"Date of Survey: {date_of_survey}")

        try:
            available = await page.evaluate(_JS_DATE_VALUES)
            if date_of_survey in (available or []):
                await click_radio_with_delay(page, "dateOfSurveyRadio", date_of_survey,
                                   "Date of Survey", log, field_delay_ms)
            else:
                if isinstance(log, AutomationLogger):
                    log.info("Target date not in radio options; selecting 'Others' for manual input.")
                else:
                    log("  Not in options — selecting 'Others'")
                await click_radio_with_delay(page, "dateOfSurveyRadio", "Others",
                                   "Date of Survey (Others)", log, field_delay_ms)
                await asyncio.sleep(0.8)
                try:
                    await page.wait_for_selector('input[name="dateOfSurvey"]',
                                                 state="visible", timeout=5000)
                    await fill_input_with_delay(page, 'input[name="dateOfSurvey"]',
                                   date_of_survey, "Date (manual)", log, field_delay_ms)
                except Exception as de:
                    if isinstance(log, AutomationLogger):
                        log.error(f"Manual date input failed: {str(de)[:100]}")
                    else:
                        log(f"  ⚠️  Manual date input: {de}")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Date selection process failed: {str(e)[:100]}")
            else:
                log(f"  ⚠️  Date error: {e}")

    await asyncio.sleep(0.5)
    if stop_cb(): return False

    # ── 2. Time Of Survey ────────────────────────────────────────────────────
    time_raw = getattr(claim_data, "time_of_survey", "")
    if not time_raw:
        hh = getattr(claim_data, "time_hh", "")
        mm = getattr(claim_data, "time_mm", "")
        if hh and mm:
            time_raw = f"{hh}:{mm}"
    if time_raw:
        n_time = _normalise_time(time_raw)
        if isinstance(log, AutomationLogger):
            log.info(f"Filling Survey Time: {n_time}")
        else:
            log(f"Time of Survey: {n_time}")
        await fill_input_with_delay(page, 'input[name="timeOfSurvey"]',
                       n_time, "Time of Survey", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 3. Place Of Survey ───────────────────────────────────────────────────
    place = getattr(claim_data, "place_of_survey", "")
    if place:
        if isinstance(log, AutomationLogger):
            log.info(f"Filling Survey Place: {place[:50]}...")
        else:
            log(f"Place of Survey: {place}")
        await fill_input_with_delay(page, 'textarea[name="placeOfSurvey"]',
                       place, "Place of Survey", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 4-10. Boolean Yes/No fields — always ensure YES ──────────────────────
    if isinstance(log, AutomationLogger):
        log.info("Setting compliance toggles to 'Yes'...")
        log.indent()
    else:
        log("Setting boolean fields to YES...")

    bool_fields = [
        ("radioDataCompleted",          "Survey Completed"),
        ("radioDrivingLicenseApplicable","DL Applicable"),
        ("radioDrivingLicense",         "DL Verified (Original)"),
        ("radioRCbook",                 "RC Verified (Original)"),
        ("radioDrivingLicensePar",      "DL Verified (Parivahan)"),
        ("radioRCbookPar",              "RC Verified (Parivahan)"),
        ("isCloseProximityBreakIn",     "Close Proximity / Break-In"),
    ]
    for radio_name, label in bool_fields:
        await _ensure_yes(page, radio_name, label, log, field_delay_ms)
        if stop_cb():
            if isinstance(log, AutomationLogger): log.outdent()
            return False

    # Conditional field — revealed after Close Proximity = Y
    await asyncio.sleep(0.5)
    await _ensure_yes(page, "inspectionReportUploaded", "Inspection Report Uploaded", log, field_delay_ms)
    
    if isinstance(log, AutomationLogger):
        log.outdent()
        
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 11. Remarks ──────────────────────────────────────────────────────────
    remarks = (
        getattr(claim_data, "remarks", "")
        or getattr(claim_data, "surveyor_observation", "")
        or str(defaults.get("remarks_default", "Ok") or "Ok")
    )
    if isinstance(log, AutomationLogger):
        log.info(f"Filling Remarks: {remarks[:50]}...")
    else:
        log(f"Remarks: {remarks[:80]}")
    await fill_input_with_delay(page, 'textarea[name="remarks"]', remarks, "Remarks", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 12. Mobile No ────────────────────────────────────────────────────────
    raw_mobile = getattr(claim_data, "mobile_no", "")
    mobile = _clean_mobile_10(raw_mobile) if raw_mobile else ""
    if mobile:
        if isinstance(log, AutomationLogger):
            log.info(f"Filling Mobile No: {mobile}")
        else:
            log(f"Mobile No: {mobile}")
        await fill_input_with_delay(page, 'input[name="mobileNo"]', mobile, "Mobile No", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 13. Email ID ─────────────────────────────────────────────────────────
    email = getattr(claim_data, "email_id", "")
    if email:
        if isinstance(log, AutomationLogger):
            log.info(f"Filling Email ID: {email}")
        else:
            log(f"Email ID: {email}")
        await fill_input_with_delay(page, 'input[name="emailId"]', email, "Email ID", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 14. Expected Date of Repair = Date of Survey ─────────────────────────
    if date_of_survey:
        if isinstance(log, AutomationLogger):
            log.info(f"Filling Expected Repair Date: {date_of_survey}")
        else:
            log(f"Expected Date of Repair (= Survey Date): {date_of_survey}")
        await fill_input_with_delay(page, 'input[name="expectedDateOfRepair"]',
                       date_of_survey, "Expected Date of Repair", log, field_delay_ms)
    await asyncio.sleep(0.4)

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("Quick Update Details phase completed.")
    elif log:
        log("Phase 3 complete — all fields filled.")
    return True
