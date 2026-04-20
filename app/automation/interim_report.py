"""
interim_report.py — Fills the "Interim Report" tab.

PRODUCTION FIX 2026-04-18:
  - Radios: Use JS to set .checked + dispatch 'change' (AngularJS listens to 'change' not 'click')
  - Datepickers: JS injection of value + input/change events, then Tab to confirm
  - Time dropdowns: Angular 'number:X' / 'string:HH' option value prefix support
  - Place of Survey: commas now preserved in address (fixed _clean_text_for_portal)
  - Mobile/Email: filled unconditionally when present; skipped gracefully when absent
  - Robust wait after tab-click so Angular re-renders all fields before filling
"""
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

logger = logging.getLogger(__name__)

# ── Radio name attributes confirmed from live portal DOM ──────────────────────
INTERIM_RADIO_NAMES = [
    "ynVehicleInspected",
    "ynSurveyCompleted",
    "ynDLApplicable",
    "ynDLVerified",
    "ynRCBookVerified",
]


# ─────────────────────────────────────────────────────────────────────────────
# Radio button handling (AngularJS-compatible)
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# Radio button handling (AngularJS-compatible)
# ─────────────────────────────────────────────────────────────────────────────

async def _click_yes_radios(page, log_cb: Callable) -> None:
    """
    Click all 'Yes' radio buttons on the Interim Report tab.

    AngularJS does NOT respond to native .click() on hidden/styled radios.
    The reliable approach:
      1. JS: find the radio, set .checked = true, dispatch 'change' event.
      2. Fallback: Playwright locator click on visible radios.
    """
    log_cb("  🔘 Setting Yes radios...")

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
    log_cb(f"  🔘 JS radios set: {len(clicked_names)}/{len(INTERIM_RADIO_NAMES)} → {clicked_names}")

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
                    log_cb(f"  ✅ Radio fallback clicked: {name}")
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
                    log_cb(f"  ✅ Radio force-JS: {name}")
            except Exception as e:
                log_cb(f"  ⚠️  Radio {name}: {str(e)[:60]}")


# ─────────────────────────────────────────────────────────────────────────────
# Main fill function
# ─────────────────────────────────────────────────────────────────────────────

async def fill_interim_report(page, claim: ClaimData,
                               log_cb: Callable[[str], None] = print) -> None:
    await click_tab(page, "interim", log_cb)
    # Brief additional wait for Angular digest cycle
    await asyncio.sleep(0.2)

    log_cb("✏️  Filling Interim Report...")

    T = 5000  # field timeout ms — use 5s for safety after tab switch

    # ── 1. Type of Settlement (dropdown) ─────────────────────────────────────
    await safe_select(page, INTERIM["settlement_type"],
                      claim.type_of_settlement, "Type of Settlement", log_cb, T)

    # ── 2. Date of Survey (Angular datepicker — text input) ──────────────────
    await safe_fill_date(page, INTERIM["survey_date"],
                         claim.date_of_survey, "Date of Survey", log_cb, T)

    # ── 3. Time of Survey — HH and MM dropdowns ──────────────────────────────
    # These are Angular <select> elements with options like:
    #   <option value="string:HH">HH</option>
    #   <option value="number:0">00</option>  ... <option value="number:23">23</option>
    if claim.time_hh:
        await safe_select(page, INTERIM["time_hours"],
                          claim.time_hh, "Time HH", log_cb, T)
    else:
        log_cb("  ⏭️  Time HH: skipped (not set in Excel)")

    if claim.time_mm:
        await safe_select(page, INTERIM["time_minutes"],
                          claim.time_mm, "Time MM", log_cb, T)
    else:
        log_cb("  ⏭️  Time MM: skipped (not set in Excel)")

    # ── 4. Odometer reading (READ ONLY - skip unconditionally) ─────────────────
    # Portal field is read-only. Attempting to fill it wastes 30s timeout.
    log_cb("  ⏭️  Odometer Reading: skipped (portal field is read-only)")

    # ── 5. Place of Survey (portal: no special chars incl commas) ────────────────
    await safe_fill_portal_text(page, INTERIM["place"],
                                claim.place_of_survey, "Place of Survey", log_cb, T)

    # ── 6. Yes/No Radio buttons ───────────────────────────────────────────────
    await _click_yes_radios(page, log_cb)

    # ── 7. Initial Loss Assessment Amount ────────────────────────────────────
    await safe_fill_amount(page, INTERIM["initial_loss"],
                           claim.initial_loss_amount, "Initial Loss Amount", log_cb, T)

    # ── 8. Mobile No (mandatory on portal — fill from Excel or skip) ─────────
    if claim.mobile_no and str(claim.mobile_no).strip():
        await safe_fill(page, INTERIM["mobile"],
                        str(claim.mobile_no).strip(), "Mobile No", log_cb, T)
    else:
        log_cb("  ⏭️  Mobile No: not in Excel (fill manually if required)")

    # ── 9. Email ID (optional) ────────────────────────────────────────────────
    if claim.email_id and str(claim.email_id).strip():
        await safe_fill(page, INTERIM["email"],
                        str(claim.email_id).strip(), "Email ID", log_cb, T)
    else:
        log_cb("  ⏭️  Email ID: not in Excel")

    # ── 10. Expected date of completion of repair (Angular datepicker) ────────
    if claim.expected_completion_date and str(claim.expected_completion_date).strip():
        await safe_fill_date(page, INTERIM["repair_date"],
                             claim.expected_completion_date,
                             "Expected Completion Date", log_cb, T)
    else:
        log_cb("  ⏭️  Expected Completion Date: not in Excel")

    # ── 11. Surveyor's Observation (portal: no special chars incl commas) ────────────
    await safe_fill_portal_text(page, INTERIM["observation"],
                                claim.surveyor_observation,
                                "Surveyor's Observation", log_cb, T)

    log_cb("✅ Interim Report complete.")
