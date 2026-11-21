import asyncio
from contextlib import contextmanager
from typing import Callable
from playwright.async_api import Page
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, click_radio_with_delay
)
from app.portals.newindia.automation.recovery import current_recovery
from app.automation.automation_logger import AutomationLogger
from app.data.data_model import clean_mobile_number
from app.portals.newindia.field_values import parse_survey_time
from app.utils import load_automation_defaults

# ── JavaScript helpers ────────────────────────────────────────────────────────

_FORM = '[name="quickUpdateForm"]'
_RADIO_OPTIONS = r"""
(radios, group) => radios.filter(radio => radio.name === group || /^\d*$/.test(radio.id.slice(group.length)))
    .filter(radio => radio.getClientRects().length || [...radio.labels].some(label => label.getClientRects().length))
    .map(radio => ({name: radio.name, value: radio.value}))
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

@contextmanager
def _review_field_failure(log, label):
    """Keep an unexpected field error for the Next review."""
    try:
        yield
    except Exception:
        reason = "App3 could not fill this field."
        recovery = current_recovery.get()
        if recovery is not None:
            recovery.record_field_issue(log, label, reason)
        elif isinstance(log, AutomationLogger):
            log.field_failed(label, reason)
        elif log:
            log(f"{label} — {reason}")


async def _radio_options(form, name):
    # The same group has a descriptive name on some claims and a short name on others.
    radios = form.locator(f'input[type="radio"]:is([name="{name}"], [id^="{name}"])')
    return await radios.evaluate_all(_RADIO_OPTIONS, name)


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
        log._section = "Quick Update"
        log.indent()
    elif log:
        log("Starting Quick Update Details")

    try:
        await page.wait_for_selector(
            'h4.headerClip:has-text("Quick Update Details")',
            state="visible", timeout=20000
        )
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error("Quick Update section did not load", str(e)[:120])
        else:
            log(f"Quick Update section did not load: {e}")
        return False

    await asyncio.sleep(1.5)
    form = page.locator(_FORM)

    async def fill_text(selector, value, label, *, source="Excel", only_if_shown=False):
        with _review_field_failure(log, label):
            if only_if_shown and not await form.locator(f"{selector}:visible").count():
                if isinstance(log, AutomationLogger):
                    log.field_skipped(label, reason="Not shown on this claim")
                return
            if value:
                await fill_input_with_delay(page, f"{_FORM} {selector}", value, label, log,
                                            field_delay_ms, source=source)
            elif isinstance(log, AutomationLogger):
                log.field_skipped(label, reason="No usable source value")

    if stop_cb():
        return False

    date_of_survey = str(getattr(claim_data, "date_of_survey", "") or "").strip()
    if date_of_survey:
        with _review_field_failure(log, "Date of Survey"):
            options = await _radio_options(form, "dateOfSurveyRadio")
            option = next((item for item in options if item["value"] == date_of_survey), None)
            if option:
                await click_radio_with_delay(page, option["name"], date_of_survey, "Date of Survey",
                                             log, field_delay_ms, source="Excel", scope=form)
            else:
                await click_radio_with_delay(page, "dateOfSurveyRadio", "Others", "Date of Survey (Others)",
                                             log, field_delay_ms, source="Default", scope=form)
                await asyncio.sleep(0.8)
                await fill_text('input[name="dateOfSurvey"]', date_of_survey, "Date of Survey")
    elif isinstance(log, AutomationLogger):
        log.field_skipped("Date of Survey", reason="Missing from Excel")

    await asyncio.sleep(0.5)
    if stop_cb():
        return False

    with _review_field_failure(log, "Time of Survey"):
        time_raw = getattr(claim_data, "time_of_survey", "")
        if time_raw in (None, ""):
            hh = getattr(claim_data, "time_hh", "")
            mm = getattr(claim_data, "time_mm", "")
            time_raw = f"{hh}:{mm}" if hh and mm else hh
        survey_time = parse_survey_time(time_raw)
        time_input = 'input[name="timeOfSurvey"]'
        if survey_time:
            maxlength = await form.locator(f"{time_input}:visible").get_attribute("maxlength", timeout=5000)
            await fill_text(time_input, survey_time[:5] if maxlength == "5" else survey_time, "Time of Survey")
        elif time_raw not in (None, ""):
            raise ValueError("Invalid survey time")
        elif isinstance(log, AutomationLogger):
            log.field_skipped("Time of Survey", reason="No usable source value")

    await asyncio.sleep(0.4)
    if stop_cb():
        return False

    await fill_text('textarea[name="placeOfSurvey"]', getattr(claim_data, "place_of_survey", ""),
                    "Place of Survey", only_if_shown=True)
    await asyncio.sleep(0.4)

    cashless = str(defaults.get("allow_cashless_claim", "Yes")).strip().casefold()
    bool_fields = [
        ("radioDataCompleted", "Survey Completed", "Y"),
        ("radioDrivingLicenseApplicable", "DL Applicable", "Y"),
        ("radioDrivingLicense", "Driving License verified with original", "Y"),
        ("radioRCbook", "RC Book verified with original", "Y"),
        ("radioDrivingLicensePar", "Driving License verified through Parivahan", "Y"),
        ("radioRCbookPar", "RC Book verified through Parivahan", "Y"),
        ("isCloseProximityBreakIn", "Close Proximity / Break-In", "Y"),
        ("inspectionReportUploaded", "Inspection Report Uploaded", "Y"),
        ("radioAllowCashless", "Allow Cashless Claim", {"yes": "Y", "no": "N"}.get(cashless)),
    ]
    for group, label, value in bool_fields:
        if stop_cb():
            return False
        if group == "inspectionReportUploaded":
            await asyncio.sleep(0.5)
        with _review_field_failure(log, label):
            options = await _radio_options(form, group)
            names = {item["name"] for item in options}
            if len(names) == 1 and value is not None:
                source = "Automation Defaults" if group == "radioAllowCashless" else "Default"
                await click_radio_with_delay(page, names.pop(), value, label, log, field_delay_ms,
                                             source=source, scope=form)
            elif names:
                recovery = current_recovery.get()
                if recovery is not None:
                    recovery.record_field_issue(log, label, "Select the correct option in Chrome.")
                elif isinstance(log, AutomationLogger):
                    log.field_failed(label, "Select the correct option in Chrome.")
            elif isinstance(log, AutomationLogger):
                log.field_skipped(label, reason="Not shown on this claim")

    await asyncio.sleep(0.4)
    if stop_cb():
        return False

    remarks = getattr(claim_data, "remarks", "") or getattr(claim_data, "surveyor_observation", "")
    await fill_text('textarea[name="remarks"]', remarks or str(defaults.get("remarks_default") or "Ok"),
                    "Remarks", source="Excel" if remarks else "Default")
    await asyncio.sleep(0.4)
    if stop_cb():
        return False

    with _review_field_failure(log, "Mobile No of the Claimant"):
        raw_mobile = getattr(claim_data, "mobile_no", "")
        await fill_text('input[data-ng-model$=".quickUpdate.claimantMobileNo"]',
                        clean_mobile_number(raw_mobile) if raw_mobile else "",
                        "Mobile No of the Claimant")
    await asyncio.sleep(0.4)
    if stop_cb():
        return False

    await fill_text('input[name="emailId"]', getattr(claim_data, "email_id", ""), "Email ID")
    await asyncio.sleep(0.4)
    if stop_cb():
        return False

    await fill_text('input[data-ng-model$=".quickUpdate.expectedDateOfRepair"]', date_of_survey,
                    "Expected date of completion of repair")
    await asyncio.sleep(0.4)
    if stop_cb():
        return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Quick Update field entry finished.")
    elif log:
        log("Quick Update field entry finished.")
    return True
