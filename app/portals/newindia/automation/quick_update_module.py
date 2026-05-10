"""
quick_update_module.py — Phase 3: New India Assurance Portal
FIX: Use native JS label.click() for all radios — bypasses Playwright pointer
interception AND avoids AngularJS scope traversal failures.
"""
import asyncio
import re
from typing import Callable, Optional
from playwright.async_api import Page

# ── JavaScript helpers ────────────────────────────────────────────────────────

# Click radio via its <label for="id"> — native click, no Playwright events
_JS_CLICK_RADIO = """
([name, value]) => {
    const radio = document.querySelector(`input[name="${name}"][value="${value}"]`);
    if (!radio) return { ok: false, err: `not found: [name=${name}][value=${value}]` };
    if (radio.checked) return { ok: true, already: true };
    const lbl = document.querySelector(`label[for="${radio.id}"]`);
    if (lbl) { lbl.click(); return { ok: true }; }
    const outer = radio.closest('label');
    if (outer) { outer.click(); return { ok: true, via: 'outer' }; }
    radio.click();
    return { ok: true, via: 'direct' };
}
"""

# Read radio checked state without touching Angular scope
_JS_IS_CHECKED = """
([name, value]) => {
    const r = document.querySelector(`input[name="${name}"][value="${value}"]`);
    return r ? r.checked : null;
}
"""

# Get all date radio values
_JS_DATE_VALUES = """
() => Array.from(document.querySelectorAll('input[name="dateOfSurveyRadio"]'))
          .map(r => r.value)
"""

# Angular-aware text fill (works fine for inputs/textareas)
_JS_FILL = """
([sel, val]) => {
    const el = document.querySelector(sel);
    if (!el) return { ok: false };
    el.value = val;
    el.dispatchEvent(new Event('input',  { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    try {
        const s = angular.element(el).scope();
        if (s && s.$apply) s.$apply();
        else {
            // walk up to find scope with $apply
            let p = el.parentElement;
            while (p) {
                const ps = angular.element(p).scope();
                if (ps && ps.$apply) { ps.$apply(); break; }
                p = p.parentElement;
            }
        }
    } catch(e) {}
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return { ok: true };
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _click_radio(page: Page, name: str, value: str,
                       label: str, log_cb: Callable) -> bool:
    try:
        res = await page.evaluate(_JS_CLICK_RADIO, [name, value])
        if res and res.get("ok"):
            already = res.get("already", False)
            log_cb(f"  {'✔ ' if already else '✅'} [{label}] → '{value}'" +
                   (" (already set)" if already else ""))
            return True
        log_cb(f"  ⚠️  [{label}] click failed: {res}")
        return False
    except Exception as e:
        log_cb(f"  ⚠️  [{label}] error: {e}")
        return False


async def _ensure_yes(page: Page, name: str, label: str,
                      log_cb: Callable) -> None:
    """Check current state; only click Yes if not already checked."""
    try:
        count = await page.locator(f'input[name="{name}"]').count()
        if not count:
            log_cb(f"  ⏭  [{label}] not in DOM")
            return
        already = await page.evaluate(_JS_IS_CHECKED, [name, "Y"])
        if already:
            log_cb(f"  ✔  [{label}] already YES")
            return
        await _click_radio(page, name, "Y", label, log_cb)
        await asyncio.sleep(0.4)
    except Exception as e:
        log_cb(f"  ⚠️  [{label}] error: {e}")


async def _ng_fill(page: Page, selector: str, value: str,
                   label: str, log_cb: Callable,
                   timeout_ms: int = 8000) -> bool:
    try:
        await page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
        res = await page.evaluate(_JS_FILL, [selector, value])
        if res and res.get("ok"):
            log_cb(f"  ✅ [{label}] filled → '{value[:60]}'")
            return True
        log_cb(f"  ⚠️  [{label}] fill failed")
        return False
    except Exception as e:
        log_cb(f"  ⚠️  [{label}] error: {e}")
        return False


def _normalise_time(raw: str) -> str:
    m = re.match(r"(\d{1,2})[:\.\s](\d{2})", str(raw).strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else str(raw)[:5]


# ── Public entry point ────────────────────────────────────────────────────────

async def fill_quick_update_details(
    page: Page,
    claim_data,
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    def log(msg): log_cb(f"  [QU] {msg}")

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
                await _click_radio(page, "dateOfSurveyRadio", date_of_survey,
                                   "Date of Survey", log)
            else:
                log("  Not in options — selecting 'Others'")
                await _click_radio(page, "dateOfSurveyRadio", "Others",
                                   "Date of Survey (Others)", log)
                await asyncio.sleep(0.8)
                try:
                    await page.wait_for_selector('input[name="dateOfSurvey"]',
                                                 state="visible", timeout=5000)
                    await _ng_fill(page, 'input[name="dateOfSurvey"]',
                                   date_of_survey, "Date (manual)", log)
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
        await _ng_fill(page, 'input[name="timeOfSurvey"]',
                       _normalise_time(time_raw), "Time of Survey", log)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 3. Place Of Survey ───────────────────────────────────────────────────
    place = getattr(claim_data, "place_of_survey", "")
    if place:
        log(f"Place of Survey: {place}")
        await _ng_fill(page, 'textarea[name="placeOfSurvey"]',
                       place, "Place of Survey", log)
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
        await _ensure_yes(page, radio_name, label, log)
        if stop_cb(): return False

    # Conditional field — revealed after Close Proximity = Y
    await asyncio.sleep(0.5)
    await _ensure_yes(page, "inspectionReportUploaded", "Inspection Report Uploaded", log)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 11. Remarks ──────────────────────────────────────────────────────────
    remarks = getattr(claim_data, "remarks", "") or \
              getattr(claim_data, "surveyor_observation", "") or "Ok"
    log(f"Remarks: {remarks[:80]}")
    await _ng_fill(page, 'textarea[name="remarks"]', remarks, "Remarks", log)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 12. Mobile No ────────────────────────────────────────────────────────
    mobile = re.sub(r"\D", "", str(getattr(claim_data, "mobile_no", "")))[:10]
    if mobile:
        log(f"Mobile No: {mobile}")
        await _ng_fill(page, 'input[name="mobileNo"]', mobile, "Mobile No", log)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 13. Email ID ─────────────────────────────────────────────────────────
    email = getattr(claim_data, "email_id", "")
    if email:
        log(f"Email ID: {email}")
        await _ng_fill(page, 'input[name="emailId"]', email, "Email ID", log)
    await asyncio.sleep(0.4)
    if stop_cb(): return False

    # ── 14. Expected Date of Repair = Date of Survey ─────────────────────────
    if date_of_survey:
        log(f"Expected Date of Repair (= Survey Date): {date_of_survey}")
        await _ng_fill(page, 'input[name="expectedDateOfRepair"]',
                       date_of_survey, "Expected Date of Repair", log)
    await asyncio.sleep(0.4)

    log("Phase 3 complete — all fields filled.")
    return True
