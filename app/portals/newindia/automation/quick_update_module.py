import asyncio
from contextlib import contextmanager
from typing import Callable
from playwright.async_api import Page
from app.portals.newindia.automation.ui_utils import (
    click_radio_with_delay, fill_input_with_delay, format_date_ddmmyyyy,
)
from app.portals.newindia.automation.recovery import current_recovery
from app.automation.automation_logger import AutomationLogger
from app.data.data_model import clean_mobile_number
from app.portals.newindia.field_values import configured_quick_update_remarks, parse_survey_time
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

    date_of_survey = format_date_ddmmyyyy(getattr(claim_data, "date_of_survey", ""))
    if date_of_survey:
        with _review_field_failure(log, "Date of Survey"):
            options = await _radio_options(form, "dateOfSurveyRadio")
            option = next((item for item in options if item["value"] == date_of_survey), None)
            if option is None:
                option = next(item for item in options if item["value"] == "Others")
            await click_radio_with_delay(page, option["name"], option["value"], "Date of Survey",
                                         log, field_delay_ms, source="Excel", scope=form)
            if option["value"] == "Others":
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

    bool_fields = [
        ("radioDataCompleted", "Survey Completed", "survey_completed", "Yes"),
        ("radioDrivingLicenseApplicable", "DL Applicable", None, "Yes"),
        ("radioDrivingLicense", "Driving License verified with original", "dl_verified_with_original", "Yes"),
        ("radioRCbook", "RC Book verified with original", "rc_verified_with_original", "Yes"),
        ("radioDrivingLicensePar", "Driving License verified through Parivahan", "dl_verified_via_parivahan", "Yes"),
        ("radioRCbookPar", "RC Book verified through Parivahan", "rc_verified_via_parivahan", "Yes"),
        ("isCloseProximityBreakIn", "Close Proximity / Break-In", "close_proximity_break_in", "No"),
        ("inspectionReportUploaded", "Inspection Report Uploaded", None, "Yes"),
        ("radioAllowCashless", "Allow Cashless Claim", "allow_cashless_claim", "Yes"),
    ]
    for group, label, setting, default_answer in bool_fields:
        if stop_cb():
            return False
        if group == "inspectionReportUploaded":
            await asyncio.sleep(0.5)
        with _review_field_failure(log, label):
            options = await _radio_options(form, group)
            names = {item["name"] for item in options}
            answer = defaults.get(setting, default_answer) if setting else default_answer
            value = {"yes": "Y", "no": "N"}.get(str(answer).strip().casefold())
            if len(names) == 1 and value is not None:
                source = "Automation Defaults" if setting else "Default"
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

    await fill_text('textarea[name="remarks"]', configured_quick_update_remarks(defaults),
                    "Remarks", source="Automation Defaults")
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

    await fill_text('textarea[name="placeOfSurvey"]', getattr(claim_data, "place_of_survey", ""),
                    "Place of Survey", only_if_shown=True)

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Quick Update field entry finished.")
    elif log:
        log("Quick Update field entry finished.")
    return True
