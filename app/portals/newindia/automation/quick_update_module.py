import asyncio
import re
from typing import Callable, Optional
from playwright.async_api import Page
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, click_radio_with_delay
)
from app.automation.automation_logger import _ts

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
                      log_cb: Callable, delay_ms: int = 600) -> None:
    """Check current state; only click Yes if not already checked."""
    try:
        count = await page.locator(f'input[name="{name}"]').count()
        if not count:
            log_cb(f"[{_ts()}]   ⏭  [{label}] not in DOM")
            return
        already = await page.evaluate(_JS_IS_CHECKED, [name, "Y"])
        if already:
            log_cb(f"[{_ts()}]   ✔  [{label}] already YES")
            return
        await click_radio_with_delay(page, name, "Y", label, log_cb, delay_ms)
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️  [{label}] error: {e}")


def _normalise_time(raw: str) -> str:
    m = re.match(r"(\d{1,2})[:\.\s](\d{2})", str(raw).strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else str(raw)[:5]


# ── Public entry point ────────────────────────────────────────────────────────

async def fill_quick_update_details(
    page: Page,
    claim_data,
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False,
    field_delay_ms: int = 600
) -> bool:
    def log(msg): log_cb(f"[{_ts()}]   [QU] {msg}")

    log("Starting Phase 3 — Quick Update Details")

    try:
        await page.wait_for_selector(
            'h4.headerClip:has-text("Quick Update Details")',
            state="visible", timeout=20000
        )
        log("Section visible — waiting for Angular to finish rendering...")
    except Exception as e:
        log(f"Section not found: {e}")
        return False

    await asyncio.sleep(1.5)
    if stop_cb(): return False

    # ── 1. Date Of Survey ────────────────────────────────────────────────────
    date_of_survey = getattr(claim_data, "date_of_survey", "").strip()
    if date_of_survey:
        log(f"Date of Survey: {date_of_survey}")
        try:
            available = await page.evaluate(_JS_DATE_VALUES)
            log(f"  Options: {available}")
            if date_of_survey in (available or []):
                await click_radio_with_delay(page, "dateOfSurveyRadio", date_of_survey,
                                   "Date of Survey", log, field_delay_ms)
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
                    log(f"  ⚠️  Manual date input: {de}")
        except Exception as e:
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
        log(f"Time of Survey: {_normalise_time(time_raw)}")
        await fill_input_with_delay(page, 'input[name="timeOfSurvey"]',
                       _normalise_time(time_raw), "Time of Survey", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 3. Place Of Survey ───────────────────────────────────────────────────
    place = getattr(claim_data, "place_of_survey", "")
    if place:
        log(f"Place of Survey: {place}")
        await fill_input_with_delay(page, 'textarea[name="placeOfSurvey"]',
                       place, "Place of Survey", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 4-10. Boolean Yes/No fields — always ensure YES ──────────────────────
    log("Setting boolean fields to YES...")

    bool_fields = [
        ("radioDataCompleted",          "Survey Completed"),
        ("radioDrivingLicenseApplicable","Driving License Applicable"),
        ("radioDrivingLicense",         "DL Verified with Original"),
        ("radioRCbook",                 "RC Book Verified with Original"),
        ("radioDrivingLicensePar",      "DL Verified via Parivahan"),
        ("radioRCbookPar",              "RC Book Verified via Parivahan"),
        ("isCloseProximityBreakIn",     "Close Proximity / Break-In"),
    ]
    for radio_name, label in bool_fields:
        await _ensure_yes(page, radio_name, label, log, field_delay_ms)
        if stop_cb(): return False

    # Conditional field — revealed after Close Proximity = Y
    await asyncio.sleep(0.5)
    await _ensure_yes(page, "inspectionReportUploaded", "Inspection Report Uploaded", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 11. Remarks ──────────────────────────────────────────────────────────
    remarks = getattr(claim_data, "remarks", "") or \
              getattr(claim_data, "surveyor_observation", "") or "Ok"
    log(f"Remarks: {remarks[:80]}")
    await fill_input_with_delay(page, 'textarea[name="remarks"]', remarks, "Remarks", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 12. Mobile No ────────────────────────────────────────────────────────
    mobile = re.sub(r"\D", "", str(getattr(claim_data, "mobile_no", "")))[:10]
    if mobile:
        log(f"Mobile No: {mobile}")
        await fill_input_with_delay(page, 'input[name="mobileNo"]', mobile, "Mobile No", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 13. Email ID ─────────────────────────────────────────────────────────
    email = getattr(claim_data, "email_id", "")
    if email:
        log(f"Email ID: {email}")
        await fill_input_with_delay(page, 'input[name="emailId"]', email, "Email ID", log, field_delay_ms)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 14. Expected Date of Repair = Date of Survey ─────────────────────────
    if date_of_survey:
        log(f"Expected Date of Repair (= Survey Date): {date_of_survey}")
        await fill_input_with_delay(page, 'input[name="expectedDateOfRepair"]',
                       date_of_survey, "Expected Date of Repair", log, field_delay_ms)
    await asyncio.sleep(0.4)

    log("Phase 3 complete — all fields filled.")
    return True
