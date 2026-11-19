# app/portals/oic/automation/basic_details_module.py
"""
basic_details_module.py — OIC Surveyor Assessment: Basic Details (Step 2).

Fills 6 subsections on a single long-form page:
  1. Policy & Claim Details   → SKIP (read-only / pre-populated)
  2. Vehicle Details           → Fill mandatory + optional fields
  3. Loss Details              → Radio buttons + text fields
  4. Surveyor Details          → SKIP (all fields disabled/read-only)
  5. Driver Details            → Fill mandatory + optional fields
  6. Workshop Details          → Fill mandatory + optional fields

Then clicks "Next" to advance to the next step.
"""

import asyncio
import re
from contextlib import suppress
from datetime import datetime
from typing import Callable, Optional

from playwright.async_api import Error as PlaywrightError, Page

from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults
from app.portals.oic.automation.selectors import (
    # Vehicle
    SEL_REG_NUMBER, SEL_MAKE, SEL_VARIANT,
    SEL_REGISTRATION_DATE_LABEL,
    SEL_MANUFACTURING_YEAR,
    SEL_CHASSIS_NUMBER, SEL_ENGINE_NUMBER, SEL_CUBIC_CAPACITY,
    SEL_TYPE_OF_BODY, SEL_CLASS_OF_VEHICLE, SEL_UNLADEN_WEIGHT,
    SEL_ROAD_TAX_PAID_UPTO_LABEL,
    SEL_COLOR_OF_VEHICLE, SEL_TYPE_OF_FUEL,
    SEL_RTO_DROPDOWN, SEL_REGISTERED_LADEN_WEIGHT,
    SEL_SEATING_CAPACITY, SEL_FITNESS_VALID_UPTO_LABEL,
    SEL_PERMIT_NUMBER, SEL_TYPE_OF_PERMIT, SEL_PERMIT_VALID_UPTO_LABEL,
    SEL_AUTH_NUMBER, SEL_VALIDITY_AUTH, SEL_ROAD_AREA,
    # Loss
    SEL_CLOSE_PROXIMITY_YES, SEL_CLOSE_PROXIMITY_NO,
    SEL_VB_CONFIRMED_YES, SEL_VB_CONFIRMED_NO,
    SEL_NIL_DEP_COVER_YES, SEL_NIL_DEP_COVER_NO,
    SEL_VEHICLE_AGE, SEL_LOSS_DESCRIPTION,
    # Surveyor
    SEL_SURVEYOR_NAME, SEL_SURVEYOR_EMAIL, SEL_SURVEYOR_MOBILE,
    SEL_SURVEYOR_ADDRESS, SEL_SURVEYOR_PAN,
    # Driver
    SEL_DRIVER_NAME,
    SEL_DOB_OF_DRIVER_LABEL,
    SEL_LICENSE_TYPE_DROPDOWN,
    SEL_LICENSE_VALID_FROM_LABEL,
    SEL_LICENSE_VALID_UPTO_LABEL,
    SEL_LICENSE_NO_1, SEL_LICENSE_NO_2, SEL_LICENSE_NO_3,
    SEL_BADGE_NO, SEL_BADGE_ISSUE_DATE_LABEL,
    SEL_OWNER_DRIVER_YES, SEL_OWNER_DRIVER_NO, SEL_RELATION_OF_DRIVER,
    SEL_QUALIFICATION,
    SEL_TP_INVOLVED_YES, SEL_TP_INVOLVED_NO,
    # SEL_COUNTRY is intentionally excluded here — the OIC portal pre-fills
    # Country as "INDIA" and marks the field read-only. Import it only when
    # the portal re-enables manual Country entry (see selectors.py #country).
    SEL_STATE_DROPDOWN, SEL_CITY_DROPDOWN, SEL_PINCODE_DROPDOWN,
    SEL_DRIVER_ADDRESS, SEL_CHARGES_FILED,
    # Workshop
    SEL_WORKSHOP_NAME, SEL_WORKSHOP_ESTIMATE_AMT,
    SEL_WORKSHOP_ESTIMATE_DATE_LABEL, SEL_WORKSHOP_GST,
    # Next
    SEL_BASIC_DETAILS_NEXT,
)
from app.portals.oic.automation.ui_utils import (
    fill_input_with_delay,
    click_primeng_radio,
    select_primeng_dropdown,
    fill_primeng_inputnumber,
    fill_mui_datepicker,
    capture_error_screenshot,
    advance_form,
    _get_oic_fill_settings,
)
from app.portals.oic.automation.date_formatter import format_oic_date
from app.portals.oic.city_mapping import city_from_licence
from app.portals.oic.license_type_mapping import resolve_license_type
from app.portals.oic.rto_mapping import resolve_rto_choice
from app.portals.oic.automation.dropdowns import dropdown_is_available, select_dropdown_option
from app.portals.oic.automation.recovery import (
    confirm_field_values, field_decision, field_problem, field_was_handled, run_field, wait_until_ready,
)


async def _select_rto(page: Page, registration_number: str, report_value: str, log: AutomationLogger, delay: int, *, from_pdf=False) -> None:
    """Select an RTO using the registration, report, or a known same-state office."""
    if field_was_handled(page, log, "RTO"):
        return
    choice = resolve_rto_choice(registration_number, report_value, ())
    if from_pdf and choice.possible_mismatch:
        await field_problem(page, log, "RTO", "The registration code and the RTO name in the PDF point to different places. Select the correct RTO in Chrome.")
        return
    preview = resolve_rto_choice(registration_number, report_value)
    expected = preview.name if preview.source == "registration code" else ""
    if expected:
        choice = preview

    def choose(options):
        nonlocal choice
        choice = resolve_rto_choice(registration_number, report_value, options)
        if from_pdf and choice.possible_mismatch:
            return ""
        return choice.name

    try:
        selected = await select_dropdown_option(page, SEL_RTO_DROPDOWN, choose, expected=expected, allow_duplicate=True)
        if choice.source in ("same-state fallback", "district fallback"):
            log.warning(
                f"OIC did not offer the exact RTO for {choice.registration_code}. "
                f"Selected '{selected}' using the {choice.source} ({choice.state_code}). Review the selected office."
            )
        elif choice.source == "Excel RTO name":
            source = "PDF" if from_pdf else "Excel"
            log.warning(f"RTO registration code '{choice.registration_code or 'unavailable'}' did not match a portal option; using {source} RTO '{report_value}' → '{selected}'.")
        if choice.possible_mismatch:
            log.warning(f"RTO registration code '{choice.registration_code}' maps to '{choice.mapped_location}', which may differ from Excel RTO '{report_value}'.")
        log.field_selected("RTO", selected, source=choice.source.replace("Excel", "PDF") if from_pdf else choice.source)
    except Exception as exc:
        reason = str(exc)
        if not choice.name and choice.registration_code:
            reason = f"No compatible RTO found in OIC for {choice.registration_code}. Select the correct office in Chrome."
        log.field_failed("RTO", reason)
        await field_problem(page, log, "RTO", reason)
    finally:
        await asyncio.sleep(delay / 1000.0)


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

async def fill_basic_details(
    page: Page,
    claim,
    *,
    log: AutomationLogger,
    stop_cb: Callable[[], bool],
    field_delay_ms: int = 30,
) -> bool:
    """
    Fill the complete Basic Details form (Step 2) on the OIC portal.

    Returns True on success, False on failure or stop.
    """
    section = "Basic Details"
    log.info(f"📝 Starting {section} — 6 subsections on single page")

    # ── F6: Load automation defaults ONCE here and pass down. ────────────────
    # load_automation_defaults() does raw JSON I/O on every call (no caching).
    # Calling it once at the entry point avoids redundant file reads during the
    # per-claim hot path, even when automation runs across multiple claims.
    _automation_defaults: dict = load_automation_defaults(
        portal_id=getattr(claim, "portal_id", "oic")
    )

    try:
        # Ensure page is loaded and stable
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await asyncio.sleep(0.5)

        # ── 1. Policy & Claim Details (skip — read-only) ─────────────────────
        log.info(f"ℹ️ Subsection 1/6: Policy & Claim Details → SKIP (read-only)")
        if stop_cb():
            return False

        # ── 2. Vehicle Details ────────────────────────────────────────────────
        log.info(f"🚗 Subsection 2/6: Vehicle Details")
        await _fill_vehicle_details(page, claim, log, field_delay_ms)
        if stop_cb():
            return False

        # ── 3. Loss Details ───────────────────────────────────────────────────
        log.info(f"📋 Subsection 3/6: Loss Details")
        await _fill_loss_details(page, claim, log, field_delay_ms)
        if stop_cb():
            return False

        # ── 4. Surveyor Details ───────────────────────────────────────────────
        log.info(f"ℹ️ Subsection 4/6: Surveyor Details")
        await _fill_surveyor_details(page, claim, log, field_delay_ms)
        if stop_cb():
            return False

        # ── 5. Driver Details ─────────────────────────────────────────────────
        log.info(f"🪪 Subsection 5/6: Driver Details")
        driver_ok = await _fill_driver_details(page, claim, log, field_delay_ms, _automation_defaults)
        if not driver_ok or stop_cb():
            return False

        # ── 6. Workshop Details ───────────────────────────────────────────────
        log.info(f"🔧 Subsection 6/6: Workshop Details")
        await _fill_workshop_details(page, claim, log, field_delay_ms)
        if stop_cb():
            return False

        # ── Click Next ────────────────────────────────────────────────────────
        log.info(f"➡️ Clicking Next to advance from Basic Details...")
        next_clicked = await _click_next_button(page, log, stop_cb)
        if not next_clicked:
            log.error(f"❌ Failed to click Next button on Basic Details page.")
            return False

        log.success(f"✅ Basic Details completed successfully.")
        return True

    except Exception as exc:
        log.error(f"❌ Basic Details failed: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — VEHICLE DETAILS
# ══════════════════════════════════════════════════════════════════════════════

async def _fill_vehicle_details(page: Page, claim, log, delay: int):
    """Fill Vehicle Details subsection fields — all 24 fields."""
    log._section = "Vehicle Details"

    # Row 1 ─────────────────────────────────────────────────────────────────

    # 1. Mandatory: Registration Number
    if claim.vehicle_registration_number:
        await fill_input_with_delay(
            page, SEL_REG_NUMBER, claim.vehicle_registration_number,
            "Registration Number", log, delay
        )

    # 2. Mandatory: Make (vehicle_make — e.g. "MARUTI ALTO K10 VXI")
    if claim.vehicle_make:
        await fill_input_with_delay(
            page, SEL_MAKE, claim.vehicle_make,
            "Make", log, delay
        )

    # 3. Optional: OIC Variant uses the same full value as Make.
    variant = _extract_variant(claim.vehicle_make)
    if variant:
        await fill_input_with_delay(
            page, SEL_VARIANT, variant,
            "Variant", log, delay
        )

    # 4. Optional: Registration Date — MUI DatePicker (DD-MM-YYYY)
    _reg_date = format_oic_date(claim.date_of_registration)
    if _reg_date:
        await fill_mui_datepicker(
            page, SEL_REGISTRATION_DATE_LABEL, _reg_date,
            "Registration Date", log, delay
        )

    # Row 2 ─────────────────────────────────────────────────────────────────

    # 5. Optional: Year of Manufacture — PrimeNG Calendar (year-only picker)
    yom = claim.year_of_manufacture or _extract_year_from_make(claim.vehicle_make)
    if yom:
        await _fill_year_picker(page, SEL_MANUFACTURING_YEAR, yom, "Year of Manufacture", log, delay)

    # 6. Mandatory: Chassis Number
    if claim.chassis_no:
        await fill_input_with_delay(
            page, SEL_CHASSIS_NUMBER, claim.chassis_no,
            "Chassis Number", log, delay
        )

    # 7. Mandatory: Engine Number
    if claim.engine_no:
        await fill_input_with_delay(
            page, SEL_ENGINE_NUMBER, claim.engine_no,
            "Engine Number", log, delay
        )

    # 8. Mandatory: Cubic Capacity — PrimeNG InputNumber
    if claim.cubic_capacity:
        cc = re.sub(r'[^\d]', '', str(claim.cubic_capacity))
        if cc:
            await fill_primeng_inputnumber(
                page, SEL_CUBIC_CAPACITY, cc,
                "Cubic Capacity", log, delay
            )

    # Row 3 ─────────────────────────────────────────────────────────────────

    # 9. Optional: Type of Body
    if claim.type_of_body:
        await fill_input_with_delay(
            page, SEL_TYPE_OF_BODY, claim.type_of_body,
            "Type of Body", log, delay
        )

    # 10. Optional: Class of Vehicle
    if claim.class_of_vehicle:
        await fill_input_with_delay(
            page, SEL_CLASS_OF_VEHICLE, claim.class_of_vehicle,
            "Class of Vehicle", log, delay
        )

    # 11. Optional: Unladen Weight — PrimeNG InputNumber
    if claim.unladen_weight:
        ulw = re.sub(r'[^\d]', '', str(claim.unladen_weight))
        if ulw:
            await fill_primeng_inputnumber(
                page, SEL_UNLADEN_WEIGHT, ulw,
                "Unladen Weight", log, delay
            )

    # 12. Optional: Road Tax Paid Upto — MUI DatePicker (DD-MM-YYYY)
    _road_tax_date = format_oic_date(claim.road_tax_paid_upto)
    if _road_tax_date:
        await fill_mui_datepicker(
            page, SEL_ROAD_TAX_PAID_UPTO_LABEL, _road_tax_date,
            "Road Tax Paid Upto", log, delay
        )

    # Row 4 ─────────────────────────────────────────────────────────────────

    # 13. Optional: Color of Vehicle
    if claim.vehicle_color:
        await fill_input_with_delay(
            page, SEL_COLOR_OF_VEHICLE, claim.vehicle_color,
            "Color of Vehicle", log, delay
        )

    # 14. Optional: Type of Fuel
    if claim.type_of_fuel:
        fuel = _clean_fuel_value(claim.type_of_fuel)
        if fuel:
            await fill_input_with_delay(
                page, SEL_TYPE_OF_FUEL, fuel,
                "Type of Fuel", log, delay
            )

    # 15. Resolve the RTO using the registration code and Excel RTO fallback.
    rto = str(claim.rto_name or "").strip()
    await _select_rto(
        page, str(claim.vehicle_registration_number or ""), rto, log, delay,
        from_pdf=str(getattr(claim, "source_report_path", "") or "").lower().endswith(".pdf"),
    )

    # 16. Optional: Registered Laden Weight — PrimeNG InputNumber
    if claim.registered_laden_weight:
        rlw = re.sub(r'[^\d]', '', str(claim.registered_laden_weight))
        if rlw:
            await fill_primeng_inputnumber(
                page, SEL_REGISTERED_LADEN_WEIGHT, rlw,
                "Registered Laden Weight", log, delay
            )

    # Row 5 ─────────────────────────────────────────────────────────────────

    # 17. Optional: Seating/Load Carrying Capacity — PrimeNG InputNumber
    if claim.seating_capacity:
        sc = re.sub(r'[^\d]', '', str(claim.seating_capacity))
        if sc:
            await fill_primeng_inputnumber(
                page, SEL_SEATING_CAPACITY, sc,
                "Seating Capacity", log, delay
            )

    # 18. Optional: Fitness Valid Upto — MUI DatePicker (DD-MM-YYYY)
    _fitness_date = format_oic_date(claim.fitness_valid_upto)
    if _fitness_date:
        await fill_mui_datepicker(
            page, SEL_FITNESS_VALID_UPTO_LABEL, _fitness_date,
            "Fitness Valid Upto", log, delay
        )

    # 19. Optional: Permit Number
    if claim.permit_number:
        await fill_input_with_delay(
            page, SEL_PERMIT_NUMBER, claim.permit_number,
            "Permit Number", log, delay
        )

    # 20. Optional: Type of Permit
    if claim.type_of_permit:
        await fill_input_with_delay(
            page, SEL_TYPE_OF_PERMIT, claim.type_of_permit,
            "Type of Permit", log, delay
        )

    # Row 6 ─────────────────────────────────────────────────────────────────

    # 21. Optional: Permit Valid Upto — MUI DatePicker (DD-MM-YYYY)
    _permit_date = format_oic_date(claim.permit_valid_upto)
    if _permit_date:
        await fill_mui_datepicker(
            page, SEL_PERMIT_VALID_UPTO_LABEL, _permit_date,
            "Permit Valid Upto", log, delay
        )

    # 22. Optional: Authorization Number
    if claim.authorization_number:
        await fill_input_with_delay(
            page, SEL_AUTH_NUMBER, claim.authorization_number,
            "Authorization Number", log, delay
        )

    # 23. Optional: Validity of Authorization
    if claim.validity_of_authorization:
        await fill_input_with_delay(
            page, SEL_VALIDITY_AUTH, claim.validity_of_authorization,
            "Validity of Authorization", log, delay
        )

    # 24. Optional: Road/Area of Operation
    if claim.road_area_of_operation:
        await fill_input_with_delay(
            page, SEL_ROAD_AREA, claim.road_area_of_operation,
            "Road/Area of Operation", log, delay
        )

    log.success("  ✅ Vehicle Details subsection done.")


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — LOSS DETAILS
# ══════════════════════════════════════════════════════════════════════════════

async def _fill_loss_details(page: Page, claim, log, delay: int):
    """Fill Loss Details subsection: 3 radios + optional text."""
    log._section = "Loss Details"

    # 1. Close Proximity (Accident date vs Allotment date > 10 days → YES)
    proximity = _resolve_loss_proximity(claim.date_of_accident, claim.date_of_allotment)
    if proximity:
        await click_primeng_radio(page, SEL_CLOSE_PROXIMITY_YES, "Close Proximity → YES", log, delay)
    else:
        await click_primeng_radio(page, SEL_CLOSE_PROXIMITY_NO, "Close Proximity → NO", log, delay)

    # 2. 64VB Confirmed — Always YES per business rule
    await click_primeng_radio(page, SEL_VB_CONFIRMED_YES, "64VB Confirmed → YES", log, delay)

    # 3. Nil Depreciation Cover — based on Excel keyword search
    has_nil_dep = _resolve_nil_depreciation(claim.nil_depreciation)
    if has_nil_dep:
        await click_primeng_radio(page, SEL_NIL_DEP_COVER_YES, "Nil Depreciation → YES", log, delay)
    else:
        await click_primeng_radio(page, SEL_NIL_DEP_COVER_NO, "Nil Depreciation → NO", log, delay)

    # 4. Age of Vehicle — text input
    if claim.age_of_vehicle:
        age = re.sub(r'[^\d.]', '', str(claim.age_of_vehicle))
        if age:
            await fill_input_with_delay(
                page, SEL_VEHICLE_AGE, age,
                "Age of Vehicle", log, delay
            )

    # 5. Loss Description — hardcoded per business rule
    await fill_input_with_delay(
        page, SEL_LOSS_DESCRIPTION, "As per estimate",
        "Loss Description", log, delay
    )

    log.success("  ✅ Loss Details subsection done.")


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — SURVEYOR DETAILS
# ══════════════════════════════════════════════════════════════════════════════

async def _fill_surveyor_details(page: Page, claim, log, delay: int):
    """Fill Surveyor Details subsection if fields are editable."""
    log._section = "Surveyor Details"
    
    # 1. Surveyor Name
    if claim.surveyor_name:
        if await _is_field_editable(page, SEL_SURVEYOR_NAME):
            await fill_input_with_delay(
                page, SEL_SURVEYOR_NAME, claim.surveyor_name,
                "Name Of The Surveyor", log, delay
            )
        else:
            log.info("  ℹ️ Surveyor Name is read-only/disabled. Skipping...")

    # 2. Surveyor Email
    if claim.surveyor_email:
        if await _is_field_editable(page, SEL_SURVEYOR_EMAIL):
            await fill_input_with_delay(
                page, SEL_SURVEYOR_EMAIL, claim.surveyor_email,
                "Surveyor Email", log, delay
            )
        else:
            log.info("  ℹ️ Surveyor Email is read-only/disabled. Skipping...")

    # 3. Surveyor Mobile
    if claim.surveyor_mobile:
        from app.data.data_model import clean_mobile_number
        cleaned_mobile = clean_mobile_number(claim.surveyor_mobile)
        if await _is_field_editable(page, SEL_SURVEYOR_MOBILE):
            await fill_input_with_delay(
                page, SEL_SURVEYOR_MOBILE, cleaned_mobile,
                "Surveyor Mobile Number", log, delay
            )
        else:
            log.info("  ℹ️ Surveyor Mobile is read-only/disabled. Skipping...")

    # 4. Surveyor Address
    if claim.surveyor_address:
        if await _is_field_editable(page, SEL_SURVEYOR_ADDRESS):
            await fill_input_with_delay(
                page, SEL_SURVEYOR_ADDRESS, claim.surveyor_address,
                "Surveyor Address", log, delay
            )
        else:
            log.info("  ℹ️ Surveyor Address is read-only/disabled. Skipping...")

    # 5. Surveyor PAN
    if claim.surveyor_pan:
        if await _is_field_editable(page, SEL_SURVEYOR_PAN):
            await fill_input_with_delay(
                page, SEL_SURVEYOR_PAN, claim.surveyor_pan,
                "PAN Number", log, delay
            )
        else:
            log.info("  ℹ️ Surveyor PAN is read-only/disabled. Skipping...")

    log.success("  ✅ Surveyor Details subsection done.")


async def _is_field_editable(page: Page, selector: str) -> bool:
    """Check if the input field at selector is editable (not read-only, not disabled)."""
    loc = page.locator(selector).first
    if not await loc.is_visible():
        return False

    # Check if element is disabled or readonly using JS evaluate
    is_locked = await loc.evaluate(
        "el => el.disabled || el.readOnly || el.hasAttribute('readonly') || el.hasAttribute('disabled') || "
        "!!el.closest('.disabled') || !!el.closest('.p-disabled') || !!el.closest('.Mui-disabled') || !!el.closest('[disabled]')"
    )
    return not is_locked


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — DRIVER DETAILS
# ══════════════════════════════════════════════════════════════════════════════

async def _fill_driver_name(page: Page, name: str, log, delay: int) -> None:
    if not name:
        await field_problem(page, log, "Driver Name", "No driver name was found in the claim data.")
        return

    locator = page.locator(f"input{SEL_DRIVER_NAME}:visible").or_(
        page.get_by_role("textbox", name=re.compile(r"^Driver Name\s*\*?$", re.IGNORECASE)),
    ).first

    async def fill_and_verify():
        instant_fill, typing_delay = _get_oic_fill_settings()
        typing_timeout = max(4000, len(name) * typing_delay + 1000)
        expected = name.casefold()
        matching_reads = 0

        async def kept_name():
            nonlocal matching_reads
            actual = (await locator.input_value(timeout=800)).strip().casefold()
            matching_reads = matching_reads + 1 if actual == expected else 0
            return matching_reads >= 2

        for type_each_character in (not instant_fill, True):
            with suppress(PlaywrightError):
                if type_each_character:
                    await locator.fill("", timeout=4000)
                    await locator.press_sequentially(name, delay=typing_delay, timeout=typing_timeout)
                else:
                    await locator.fill(name, timeout=4000)
                await locator.press("Tab", timeout=1500)

            matching_reads = 0
            if await wait_until_ready(kept_name, seconds=2):
                log.field_filled("Driver Name", name)
                return

        raise ValueError("OIC did not keep the driver name. Enter it in Chrome.")

    await run_field(page, log, "Driver Name", fill_and_verify)
    await asyncio.sleep(delay / 1000.0)


async def _fill_driver_license_number(page: Page, number: str, log, delay: int) -> None:
    parts = _split_license_number(number)
    if parts is None:
        await field_problem(
            page, log, "Driving Licence Number",
            "The licence needs a two-letter code and two groups of six digits. Enter the correct values in Chrome.",
        )
        return

    prefix, first_six, last_six, excess = parts
    if excess:
        omitted = excess if len(excess) <= 12 else f"{excess[:12]}…"
        confirmed = await confirm_field_values(
            page, log, "Review Driving Licence Number",
            f"The licence has {12 + len(excess)} digits after {prefix}. OIC uses 12 digits.",
            f"Continue will fill {prefix} / {first_six} / {last_six}. "
            f"It will omit the digits in between ({omitted}).",
        )
        if not confirmed:
            return

    prefix_label = "License No. Field 1"
    selected = await select_primeng_dropdown(page, SEL_LICENSE_NO_1, prefix, prefix_label, log, delay, exact=True)
    if not selected or field_decision(page, log, prefix_label) == "skip":
        return

    for selector, label, value in (
        (SEL_LICENSE_NO_2, "License No. Field 2", first_six),
        (SEL_LICENSE_NO_3, "License No. Field 3", last_six),
    ):
        await fill_input_with_delay(page, selector, value, label, log, delay)
        if field_was_handled(page, log, label):
            continue

        async def matches():
            return await page.locator(selector).first.input_value(timeout=1000) == value

        if not await wait_until_ready(matches, seconds=2):
            await field_problem(page, log, label, f"OIC did not keep the six digits {value}. Verify the field in Chrome.")


async def _fill_driver_details(page: Page, claim, log, delay: int, automation_defaults: dict | None = None):
    """Fill Driver Details subsection — all 19 fields."""
    log._section = "Driver Details"

    # Row 1 ─────────────────────────────────────────────────────────────────

    # 1. Driver Name * (mandatory)
    await _fill_driver_name(page, claim.oic_driver_name, log, delay)

    # 2. Date of Birth * (mandatory) — MUI DatePicker (DD-MM-YYYY)
    _dob = format_oic_date(claim.dob_of_driver)
    if _dob:
        await fill_mui_datepicker(
            page, SEL_DOB_OF_DRIVER_LABEL, _dob,
            "Date of Birth", log, delay
        )
    else:
        await field_problem(page, log, "Date of Birth", "No usable driver date of birth was found.")

    # 3. Prefer the vehicle-class mapping; keep Excel's licence type as a
    # fallback only when the class is not recognized, never when ambiguous.
    licence_type, licence_source = resolve_license_type(
        claim.class_of_vehicle, claim.license_type_of_driver
    )
    if licence_type:
        source = "Class of Vehicle" if licence_source == "class" else "Excel Licence Type"
        exact = licence_source == "class" or str(claim.license_type_of_driver or "").strip().casefold() == "lmv"
        await select_primeng_dropdown(
            page, SEL_LICENSE_TYPE_DROPDOWN, licence_type, "License Type", log, delay, source=source, exact=exact,
        )
    elif licence_source == "ambiguous":
        log.warning("Class of Vehicle does not identify one Licence Type; no new choice made. "
                    "OIC requires a manual selection before advancing if the field is blank.")
    else:
        log.warning("Licence Type could not be determined; continuing with the remaining fields.")

    # 4. Valid From * (mandatory) — MUI DatePicker (DL issue date, DD-MM-YYYY)
    _dl_issue = format_oic_date(claim.driver_license_issue_date)
    if _dl_issue:
        await fill_mui_datepicker(
            page, SEL_LICENSE_VALID_FROM_LABEL, _dl_issue,
            "Valid From (DL Issue Date)", log, delay
        )
    else:
        await field_problem(page, log, "Valid From (DL Issue Date)", "No usable licence issue date was found.")

    # Row 2 ─────────────────────────────────────────────────────────────────

    # 5. Valid Up To * (mandatory) — MUI DatePicker (DL expiry date, DD-MM-YYYY)
    _dl_expiry = format_oic_date(claim.driver_license_expiry_date)
    if _dl_expiry:
        await fill_mui_datepicker(
            page, SEL_LICENSE_VALID_UPTO_LABEL, _dl_expiry,
            "Valid Up To (DL Expiry Date)", log, delay
        )
    else:
        await field_problem(page, log, "Valid Up To (DL Expiry Date)", "No usable licence expiry date was found.")

    # 6-8. License Number * (mandatory) — split into 3 parts
    await _fill_driver_license_number(page, claim.driver_license_number, log, delay)

    # Row 3 ─────────────────────────────────────────────────────────────────

    # 9. Badge No. (optional)
    if claim.badge_number:
        await fill_input_with_delay(
            page, SEL_BADGE_NO, claim.badge_number,
            "Badge No.", log, delay
        )

    # 10. Badge Issue Date (optional) — MUI DatePicker (DD-MM-YYYY)
    _badge_date = format_oic_date(claim.badge_issue_date)
    if _badge_date:
        await fill_mui_datepicker(
            page, SEL_BADGE_ISSUE_DATE_LABEL, _badge_date,
            "Badge Issue Date", log, delay
        )

    # 11. Is Owner Driver? (radio) — derived from name comparison
    #
    # Logic: compare driver_name vs registered_owner_name (normalised, word-level).
    # If both names match  → YES (owner is the driver)
    # If they differ       → NO  → portal reveals "Relation of Driver" field
    # If either is blank   → YES (safe default — most motor claims are owner-driven)
    _is_owner = _is_owner_driver(claim.driver_name, claim.registered_owner_name)
    log.info(
        f"  ℹ️ [Owner Driver] driver='{claim.driver_name}' "
        f"owner='{claim.registered_owner_name}' → {'YES' if _is_owner else 'NO'}"
    )

    if _is_owner:
        await click_primeng_radio(page, SEL_OWNER_DRIVER_YES, "Owner Driver → YES", log, delay)
    else:
        await click_primeng_radio(page, SEL_OWNER_DRIVER_NO, "Owner Driver → NO", log, delay)
        defaults = automation_defaults
        if defaults is None:
            defaults = load_automation_defaults(portal_id="oic")
        relation = str(defaults.get("driver_relation_default") or "").strip() or "other"
        relation_input = page.locator(SEL_RELATION_OF_DRIVER).first
        try:
            await relation_input.wait_for(state="visible", timeout=3000)
        except PlaywrightError:
            log.info("Relationship with Driver is unavailable on this form.")
        else:
            await fill_input_with_delay(
                page, SEL_RELATION_OF_DRIVER, relation, "Relationship with Driver", log, delay,
                source="Automation Defaults",
            )

    # 12. Qualification (optional)
    if claim.driver_qualification:
        await fill_input_with_delay(
            page, SEL_QUALIFICATION, claim.driver_qualification,
            "Qualification", log, delay
        )

    # Row 4 ─────────────────────────────────────────────────────────────────

    # 13. Third Party Involved (radio) — Default NO
    await click_primeng_radio(page, SEL_TP_INVOLVED_NO, "Third Party Involved → NO", log, delay)

    # 14. Country — read-only/pre-filled by portal; skip filling
    # NOTE: The OIC portal pre-populates Country as "INDIA" and makes it
    # read-only. To re-enable if the portal changes behaviour:
    #   1. Uncomment the block below.
    #   2. Add SEL_COUNTRY back to the import from selectors (see line ~51).
    # await fill_input_with_delay(
    #     page, "#country", "INDIA",
    #     "Country", log, delay
    # )
    log.info("  ℹ️ [Country] → pre-filled by portal (read-only) — skipped")

    # 15–17. State, City and Pincode use dependent dropdowns.
    state = _state_from_driver_license(claim.driver_license_number)
    if state:
        if not await select_primeng_dropdown(page, SEL_STATE_DROPDOWN, state, "State", log, delay):
            return False
    elif not await field_problem(page, log, "State", "No state mapping exists for this driving licence prefix."):
        return False

    if field_decision(page, log, "State") == "skip" and not await dropdown_is_available(page, SEL_CITY_DROPDOWN):
        log.info("City and Pincode are unavailable until a State is selected.")
    else:
        city = city_from_licence(claim.driver_license_number)
        if city:
            if not await select_primeng_dropdown(
                page, SEL_CITY_DROPDOWN, city, "City", log, delay, source="Driver licence prefix", exact=True,
            ):
                return False
        elif not await field_problem(page, log, "City", "No district mapping exists for this driving licence prefix."):
            return False

        if field_decision(page, log, "City") == "skip" and not await dropdown_is_available(page, SEL_PINCODE_DROPDOWN):
            log.info("Pincode is unavailable until a City is selected.")
        elif not await _select_pincode_dropdown(
            page, log, delay,
            pdf_pin=str(claim.driver_pin_code or "") if str(getattr(claim, "source_report_path", "") or "").lower().endswith(".pdf") else None,
        ):
            return False

    # 18. Address * (mandatory) — textarea
    address = claim.driver_address or claim.place_of_survey or ""
    if address:
        await fill_input_with_delay(
            page, SEL_DRIVER_ADDRESS, address,
            "Address", log, delay
        )
    else:
        await field_problem(page, log, "Address", "No driver or survey address was found.")

    # Row 6 ─────────────────────────────────────────────────────────────────

    # 19. Charges Filed (optional) — textarea
    charges_filed, source = _resolve_charges_filed(claim.charges_filed, automation_defaults)
    if charges_filed:
        await fill_input_with_delay(
            page, SEL_CHARGES_FILED, charges_filed, "Charges Filed", log, delay, source=source
        )

    log.success("  ✅ Driver Details subsection done.")
    return True


def _resolve_charges_filed(value, automation_defaults=None):
    report_value = str(value or "").strip()
    if report_value:
        return report_value, ""
    defaults = load_automation_defaults(portal_id="oic") if automation_defaults is None else automation_defaults
    default_value = str(defaults.get("charges_filed_default") or "").strip()
    return default_value, "Automation Defaults" if default_value else ""


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — WORKSHOP DETAILS
# ══════════════════════════════════════════════════════════════════════════════

async def _fill_workshop_details(page: Page, claim, log, delay: int):
    """Fill Workshop Details subsection."""
    log._section = "Workshop Details"

    # 1. Workshop Name
    if claim.workshop_name:
        await fill_input_with_delay(
            page, SEL_WORKSHOP_NAME, claim.workshop_name,
            "Workshop Name", log, delay
        )

    # 2. Workshop Estimate Amount — PrimeNG InputNumber
    if claim.workshop_estimate_amount:
        amt = re.sub(r'[^\d.]', '', str(claim.workshop_estimate_amount))
        if amt:
            await fill_primeng_inputnumber(
                page, SEL_WORKSHOP_ESTIMATE_AMT, amt,
                "Workshop Estimate Amount", log, delay
            )

    # 3. Workshop Estimate Date — MUI DatePicker (DD-MM-YYYY)
    #    The portal field has a dynamic id (e.g. :r3g:), so we locate it
    #    by its visible label text using fill_mui_datepicker().
    #
    #    F2 — Normalise raw date BEFORE passing to fill_mui_datepicker.
    #    Excel can store dates as ISO strings ("2026-05-27"), serial floats
    #    (44977.0), slash-separated strings ("27/05/2026"), or plain text.
    #    fill_mui_datepicker internally calls format_date_for_mui() which now
    #    delegates to date_formatter.py, but only if the value it receives is
    #    already a string the formatter recognises. By calling format_oic_date()
    #    here we guarantee the value is always "DD-MM-YYYY" before hand-off.
    _est_date = format_oic_date(claim.workshop_estimate_date)
    if _est_date:
        await fill_mui_datepicker(
            page,
            SEL_WORKSHOP_ESTIMATE_DATE_LABEL,   # "Workshop Estimate Date"
            _est_date,
            "Workshop Estimate Date",
            log,
            delay_ms=delay,
        )
    else:
        log.info("  ℹ️ [Workshop Estimate Date] not found in Excel — skipped")

    # 4. GST Number (optional)
    if claim.gst_number:
        gst = page.locator(f"{SEL_WORKSHOP_GST}:visible").first
        if await gst.is_visible() and await gst.is_editable(timeout=1000):
            await fill_input_with_delay(
                page, SEL_WORKSHOP_GST, claim.gst_number,
                "GST Number", log, delay,
            )
        else:
            log.info("OIC did not offer an editable Workshop GST Number. Skipping this optional field.")

    log.success("  ✅ Workshop Details subsection done.")


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — NEXT BUTTON
# ══════════════════════════════════════════════════════════════════════════════

async def _click_next_button(page: Page, log, stop_cb) -> bool:
    return await advance_form(
        page, log, SEL_BASIC_DETAILS_NEXT, "Next", "interim", stop_cb, "basic_details_next_no_transition",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — PINCODE DROPDOWN HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def _select_pincode_dropdown(page: Page, log, delay: int, *, pdf_pin=None) -> bool:
    """Match the driver's PDF postcode, or use the existing Excel flow."""
    if field_was_handled(page, log, "Pincode"):
        return True

    if pdf_pin is not None and not re.fullmatch(r"[1-9]\d{5}", pdf_pin):
        return await field_problem(page, log, "Pincode", "The survey PDF does not contain a reliable driver pincode. Select the correct pincode in Chrome.")

    def choose(options):
        pattern = r"^\d{6}(?!\d)" if pdf_pin is None else rf"^{pdf_pin}(?!\d)"
        matches = [value for value in options if re.match(pattern, value)]
        return matches[0] if matches and (pdf_pin is None or len(set(matches)) == 1) else ""

    try:
        pin = await select_dropdown_option(
            page, SEL_PINCODE_DROPDOWN, choose, expected=pdf_pin or "", allow_duplicate=True,
        )
        log.field_selected("Pincode", pin, source="Survey PDF" if pdf_pin else "First available portal option")
        return True
    except Exception as exc:
        log.field_failed("Pincode", str(exc))
        return await field_problem(page, log, "Pincode", str(exc))
    finally:
        await asyncio.sleep(delay / 1000.0)


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — BUSINESS LOGIC HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_loss_proximity(date_of_accident: str, date_of_allotment: str) -> bool:
    """
    Determine if loss proximity is YES.
    YES if (date_of_allotment - date_of_accident) > 10 days.
    Returns False if dates are unavailable or invalid.
    """
    if not date_of_accident or not date_of_allotment:
        return False

    # Filter out "NA", "N/A", etc.
    if re.match(r'^(NA|N/A|nil|none|-)$', date_of_accident.strip(), re.IGNORECASE):
        return False
    if re.match(r'^(NA|N/A|nil|none|-)$', date_of_allotment.strip(), re.IGNORECASE):
        return False

    try:
        d_accident = _parse_date_flexibly(date_of_accident)
        d_allotment = _parse_date_flexibly(date_of_allotment)
        if d_accident and d_allotment:
            diff = abs((d_allotment - d_accident).days)
            return diff > 10
    except Exception:
        pass

    return False


def _resolve_nil_depreciation(nil_dep_value: str) -> bool:
    """
    Determine if the claim has nil depreciation cover.
    Returns True if the Excel contains affirmative keywords.
    """
    if not nil_dep_value:
        return False

    val = str(nil_dep_value).strip().lower()
    affirmative = {"yes", "y", "true", "1", "nil dep", "nil depreciation"}
    return val in affirmative or "yes" in val


def _is_owner_driver(driver_name: str, owner_name: str) -> bool:
    """
    Check if the driver is the vehicle owner.
    Uses normalized name comparison (case-insensitive, stripped).
    """
    if not driver_name or not owner_name:
        return True  # Default to YES if we can't determine

    d = re.sub(r'\s+', ' ', driver_name.strip().lower())
    o = re.sub(r'\s+', ' ', owner_name.strip().lower())

    # Exact match
    if d == o:
        return True

    # Partial match (any 2+ char word overlap)
    d_words = set(w for w in d.split() if len(w) > 1)
    o_words = set(w for w in o.split() if len(w) > 1)
    common = d_words & o_words
    return len(common) >= 2 or (len(common) >= 1 and len(d_words) == 1)


def _split_license_number(license_no: str) -> tuple[str, str, str, str] | None:
    """Return the 2/6/6 fields plus any intervening digits that require review."""
    normalized = re.sub(r"[\s/-]+", "", str(license_no or "")).upper()
    match = re.fullmatch(r"([A-Z]{2})([0-9]{6})([0-9]*)([0-9]{6})", normalized)
    if match:
        prefix, first_six, excess, last_six = match.groups()
        return prefix, first_six, last_six, excess
    return None


# Values match the state labels observed in the OIC portal dropdown.
_LICENSE_STATE_LABELS = {
    "AN": "ANDAMAN & NICOBAR ISLANDS",
    "AP": "ANDHRA PRADESH",
    "AR": "ARUNACHAL PRADESH",
    "AS": "ASSAM",
    "BR": "BIHAR",
    "CG": "CHATTISGARH",
    "CH": "CHANDIGARH",
    "DD": "DAMAN AND DIU AND DADRA AND NAGAR HAVELI",
    "DN": "DAMAN AND DIU AND DADRA AND NAGAR HAVELI",
    "DL": "DELHI",
    "GA": "GOA",
    "GJ": "GUJARAT",
    "HP": "HIMACHAL PRADESH",
    "HR": "HARYANA",
    "JH": "JHARKHAND",
    "JK": "JAMMU AND KASHMIR",
    "KA": "KARNATAKA",
    "KL": "KERALA",
    "LA": "LADAKH",
    "LD": "LAKSHADWEEP",
    "MH": "MAHARASHTRA",
    "ML": "MEGHALAYA",
    "MN": "MANIPUR",
    "MP": "MADHYA PRADESH",
    "MZ": "MIZORAM",
    "NL": "NAGALAND",
    "OD": "ODISHA",
    "OR": "ODISHA",
    "PB": "PUNJAB",
    "PY": "PONDICHERRY",
    "RJ": "RAJASTHAN",
    "SK": "SIKKIM",
    "TG": "TELANGANA",
    "TN": "TAMIL NADU",
    "TR": "TRIPURA",
    "TS": "TELANGANA",
    "UA": "UTTARAKHAND",
    "UK": "UTTARAKHAND",
    "UP": "UTTAR PRADESH",
    "WB": "WEST BENGAL",
}


def _state_from_driver_license(license_number: str) -> str:
    """Return the OIC state label for a recognized driving licence prefix."""
    match = re.match(r"^\s*([A-Za-z]{2})", str(license_number or ""))
    return _LICENSE_STATE_LABELS.get(match.group(1).upper(), "") if match else ""


def _extract_state(city_state: str) -> str:
    """
    Extract state from 'City, State' or 'City/State' string.
    E.g., "Panchkula, HR" → "HR"
    """
    if not city_state:
        return ""

    raw = str(city_state).strip()

    # "City, State" pattern
    if "," in raw:
        parts = [p.strip() for p in raw.split(",")]
        return parts[-1] if parts else ""

    # "City/State" pattern
    if "/" in raw:
        parts = [p.strip() for p in raw.split("/")]
        return parts[-1] if parts else ""

    return raw


def _extract_city(city_state: str) -> str:
    """
    Extract city from 'City, State' string.
    E.g., "Panchkula, HR" → "Panchkula"
    """
    if not city_state:
        return ""

    raw = str(city_state).strip()
    if "," in raw:
        parts = [p.strip() for p in raw.split(",")]
        return parts[0] if parts else ""
    if "/" in raw:
        parts = [p.strip() for p in raw.split("/")]
        return parts[0] if parts else ""
    return ""


def _extract_pin_code(address: str) -> str:
    """Extract 6-digit PIN code from address string."""
    if not address:
        return ""
    m = re.search(r'\b(\d{6})\b', str(address))
    return m.group(1) if m else ""


def _extract_variant(vehicle_make: str) -> str:
    """Use the complete Make value for the OIC Variant field and preview."""
    return vehicle_make or ""


def _extract_year_from_make(vehicle_make: str) -> str:
    """
    Try to extract a year from the "Make & Year" field.
    E.g., "MARUTI ALTO K10 VXI 2019" → "2019"
    """
    if not vehicle_make:
        return ""

    m = re.search(r'\b(19|20)\d{2}\b', str(vehicle_make))
    return m.group(0) if m else ""


def _clean_fuel_value(raw_fuel: str) -> str:
    """
    Clean fuel type from Excel format.
    E.g., "Fuel used: PETROL" → "PETROL"
    """
    if not raw_fuel:
        return ""
    val = str(raw_fuel).strip()
    # Remove prefix labels
    val = re.sub(r'(?i)fuel\s*(?:used|type)?\s*[:;-]\s*', '', val).strip()
    return val.upper() if val else ""


def _parse_date_flexibly(raw: str) -> Optional[datetime]:
    """Parse a date string flexibly from multiple formats."""
    if not raw:
        return None

    val = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y",
                "%m/%d/%Y", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


async def _fill_year_picker(page: Page, selector: str, year: str, label: str, log, delay: int):
    """
    Fill a PrimeNG Calendar year-only picker.
    Strategy: Click the calendar, navigate to year view, select the year.
    Fallback: Try direct input if calendar interaction fails.
    """
    try:
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=5000)
        await loc.scroll_into_view_if_needed()

        # Try direct input first (PrimeNG calendar often has an inner input)
        inner = page.locator(f"{selector} input").first
        if await inner.is_visible():
            await inner.focus()
            
            instant_fill, typing_delay = _get_oic_fill_settings()
            if instant_fill:
                await inner.fill(str(year))
            else:
                await inner.fill("")
                await inner.press_sequentially(str(year), delay=typing_delay)

            await inner.evaluate(
                "el => { el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); "
                "el.dispatchEvent(new Event('blur', {bubbles:true})); }"
            )
            if isinstance(log, AutomationLogger):
                log.field_filled(label, year)
            else:
                log(f"[{_ts()}]   ✅ [{label}] filled → '{year}'")
        else:
            # Click the calendar trigger and try to select year
            await loc.click()
            await asyncio.sleep(0.3)
            # Look for year text in the overlay
            year_item = page.locator(f".p-datepicker span:has-text('{year}')").first
            if await year_item.is_visible():
                await year_item.click()
                if isinstance(log, AutomationLogger):
                    log.field_filled(label, year)
                else:
                    log(f"[{_ts()}]   ✅ [{label}] selected → '{year}'")
            else:
                if isinstance(log, AutomationLogger):
                    log.field_failed(label, f"Year '{year}' not found in picker")
                else:
                    log(f"[{_ts()}]   ⚠️ [{label}] year '{year}' not in picker")
                await field_problem(page, log, label, "The year was not available in the picker.")

    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")
        await field_problem(page, log, label, str(e))

    await asyncio.sleep(delay / 1000.0)
