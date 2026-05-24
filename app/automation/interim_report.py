import asyncio
import logging
from typing import Callable

from app.data.data_model import ClaimData
from app.automation.form_helpers import (
    safe_fill, safe_fill_amount, safe_fill_date, safe_fill_text,
    safe_fill_portal_text, safe_select,
)
from app.automation.selectors import INTERIM
from app.automation.tab_utils import click_tab
from app.automation.automation_logger import AutomationLogger

import re

logger = logging.getLogger(__name__)


from app.data.data_model import clean_mobile_number
_clean_mobile = clean_mobile_number


# ── Radio name attributes confirmed from live portal DOM ──────────────────────
INTERIM_RADIO_NAMES = [
    "ynVehicleInspected",
    "ynSurveyCompleted",
    "ynDLApplicable",
    "ynDLVerified",
    "ynRCBookVerified",
]


async def _click_yes_radios(page, log) -> None:
    """
    Click all 'Yes' radio buttons on the Interim Report tab.
    """
    if isinstance(log, AutomationLogger):
        log.info("Setting 'Yes' radios...")
    else:
        log("  🔘 Setting Yes radios...")

    # Strategy 1: Pure JS — set checked + fire 'change' for Angular ng-model
    js_result = await page.evaluate("""
        (function() {
            var names = [
                'ynVehicleInspected',
                'ynSurveyCompleted',
                'ynDLApplicable',
                'ynDLVerified',
                'ynRCBookVerified'
            ];
            var clicked = [];
            names.forEach(function(name) {
                // Try multiple selector patterns
                var selectors = [
                    'input[name="' + name + '"][value="Y"]',
                    'input[ng-model*="' + name + '"][value="Y"]',
                    'input[data-ng-model*="' + name + '"][value="Y"]',
                ];
                for (var s of selectors) {
                    var r = document.querySelector(s);
                    if (r) {
                        r.checked = true;
                        // AngularJS listens to 'change' for ng-model updates
                        r.dispatchEvent(new Event('change', {bubbles: true}));
                        // Also try click() as a secondary signal
                        try { r.click(); } catch(e) {}
                        clicked.push(name);
                        break;
                    }
                }
            });
            return clicked;
        })();
    """)
    clicked_names = js_result or []
    if isinstance(log, AutomationLogger):
        log.success(f"JS radios set: {len(clicked_names)}/{len(INTERIM_RADIO_NAMES)}")
    else:
        log(f"  🔘 JS radios set: {len(clicked_names)}/{len(INTERIM_RADIO_NAMES)} → {clicked_names}")

    # Strategy 2: Playwright click fallback for any radio that JS missed
    if len(clicked_names) < len(INTERIM_RADIO_NAMES):
        radio_sel_map = {
            "ynVehicleInspected": INTERIM["radio_vehicle"],
            "ynSurveyCompleted":  INTERIM["radio_survey_done"],
            "ynDLApplicable":     INTERIM["radio_dl_appl"],
            "ynDLVerified":       INTERIM["radio_dl_ver"],
            "ynRCBookVerified":   INTERIM["radio_rc_book"],
        }
        for name in INTERIM_RADIO_NAMES:
            if name in clicked_names:
                continue
            sel = radio_sel_map.get(name, "")
            if not sel:
                continue
            try:
                r = page.locator(sel).first
                if await r.is_visible(timeout=800):
                    await r.click(force=True)
                    await asyncio.sleep(0.1)
                    if isinstance(log, AutomationLogger):
                        log.success(f"Radio fallback clicked: {name}")
                    else:
                        log(f"  ✅ Radio fallback clicked: {name}")
                else:
                    # Final resort: force JS click
                    await page.evaluate(f"""
                        (function() {{
                            var r = document.querySelector('{sel}');
                            if (r) {{
                                r.checked = true;
                                r.dispatchEvent(new Event('change', {{bubbles: true}}));
                            }}
                        }})();
                    """)
                    if isinstance(log, AutomationLogger):
                        log.success(f"Radio force-JS: {name}")
                    else:
                        log(f"  ✅ Radio force-JS: {name}")
            except Exception as e:
                if isinstance(log, AutomationLogger):
                    log.warning(f"Radio {name}: {str(e)[:60]}")
                else:
                    log(f"  ⚠️  Radio {name}: {str(e)[:60]}")


async def fill_interim_report(page, claim: ClaimData,
                               log_cb = print,
                               settings: dict = None) -> None:
    log = log_cb
    if isinstance(log, AutomationLogger):
        log.section_start("PHASE 3: INTERIM REPORT")
    
    await click_tab(page, "interim", log)
    # Brief additional wait for Angular digest cycle
    await asyncio.sleep(0.2)

    if isinstance(log, AutomationLogger):
        log.info("Filling Interim Report section...")
        log.indent()
        log.step(1, 3, "Survey Details")
    else:
        log("📊 Filling Interim Report...")

    T = 5000  # field timeout ms — use 5s for safety after tab switch

    # Helper to look up Excel source coordinate for a field
    def _src(key: str) -> str:
        return claim._excel_coords.get(key, "")

    # ── 1. Type of Settlement (dropdown) ─────────────────────────────────────
    await safe_select(page, INTERIM["settlement_type"],
                      claim.type_of_settlement, "Type of Settlement", log, T,
                      source=_src("type_of_settlement"))

    # ── 2. Date of Survey (Angular datepicker — text input) ──────────────────
    await safe_fill_date(page, INTERIM["survey_date"],
                         claim.date_of_survey, "Date of Survey", log, T,
                         source=_src("date_of_survey"))

    # ── 3. Time of Survey — HH and MM dropdowns ──────────────────────────────
    if claim.time_hh:
        await safe_select(page, INTERIM["time_hours"],
                          claim.time_hh, "Time HH", log, T,
                          source=_src("date_of_survey"))
    else:
        if isinstance(log, AutomationLogger):
            log.info("Time HH: skipped (not set in Excel)")
        else:
            log("  ⏭️  Time HH: skipped (not set in Excel)")

    if claim.time_mm:
        await safe_select(page, INTERIM["time_minutes"],
                          claim.time_mm, "Time MM", log, T,
                          source=_src("date_of_survey"))
    else:
        if isinstance(log, AutomationLogger):
            log.info("Time MM: skipped (not set in Excel)")
        else:
            log("  ⏭️  Time MM: skipped (not set in Excel)")

    # ── 4. Odometer reading (READ ONLY - skip unconditionally) ─────────────────
    if isinstance(log, AutomationLogger):
        log.info("Odometer Reading: skipped (portal field is read-only)")
    else:
        log("  ⏭️  Odometer Reading: skipped (portal field is read-only)")

    # ── 5. Place of Survey (portal: no special chars incl commas) ────────────────
    await safe_fill_portal_text(page, INTERIM["place"],
                                claim.place_of_survey, "Place of Survey", log, T,
                                source=_src("place_of_survey"))

    # ── 6. Yes/No Radio buttons ───────────────────────────────────────────────
    await _click_yes_radios(page, log)

    # ── 7. Initial Loss Assessment Amount ────────────────────────────────────
    await safe_fill_amount(page, INTERIM["initial_loss"],
                           claim.initial_loss_amount, "Initial Loss Amount", log, T,
                           source=_src("initial_loss_amount"))

    # ── 8. Mobile No (mandatory on portal — clean to 10 digits) ──────────────
    if claim.mobile_no and str(claim.mobile_no).strip():
        clean_mobile = _clean_mobile(claim.mobile_no)
        await safe_fill(page, INTERIM["mobile"],
                        clean_mobile, "Mobile No", log, T,
                        source=_src("mobile_no"))
    else:
        if isinstance(log, AutomationLogger):
            log.warning("Mobile No: not in Excel (fill manually if required)")
        else:
            log("  ⏭️  Mobile No: not in Excel (fill manually if required)")

    # ── 9. Email ID (optional) ────────────────────────────────────────────────
    if claim.email_id and str(claim.email_id).strip():
        await safe_fill(page, INTERIM["email"],
                        str(claim.email_id).strip(), "Email ID", log, T,
                        source=_src("email_id"))
    else:
        if isinstance(log, AutomationLogger):
            log.info("Email ID: not in Excel")
        else:
            log("  ⏭️  Email ID: not in Excel")

    # ── 10. Expected date of completion of repair (same as Date of Survey) ────
    if claim.expected_completion_date and str(claim.expected_completion_date).strip():
        await safe_fill_date(page, INTERIM["repair_date"],
                             claim.expected_completion_date,
                             "Expected Completion Date", log, T,
                             source=_src("expected_completion_date") or _src("date_of_survey"))
    else:
        if isinstance(log, AutomationLogger):
            log.info("Expected Completion Date: not set")
        else:
            log("  ⏭️  Expected Completion Date: not set")

    # ── 11. Surveyor's Observation & Remarks (no special chars) ───────────────────
    if isinstance(log, AutomationLogger):
        log.step(2, 3, "Surveyor Observations")
    await safe_fill_portal_text(page, INTERIM["observation"],
                                claim.surveyor_observation,
                                "Surveyor's Observation", log, T,
                                source=_src("surveyor_observation"))
    
    # User requested 'Remarks *' field is blank on interim report
    await safe_fill_portal_text(page, "#remarks, textarea[ng-model*='remark'], textarea[name*='emarks']",
                                "Done",
                                "Remarks", log, T,
                                source="Hardcoded")

    if isinstance(log, AutomationLogger):
        log.step(3, 3, "Finalizing Interim Report")
        log.success("Interim Report section complete.")
        log.outdent()
    else:
        log("✅ Interim Report complete.")
