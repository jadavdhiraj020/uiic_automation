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
from datetime import datetime
from typing import Callable, Optional

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger
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
    _get_oic_fill_settings,
)
from app.portals.oic.automation.date_formatter import format_oic_date
from app.portals.oic.city_mapping import city_from_licence
from app.portals.oic.rto_mapping import match_rto_name


async def _select_rto(page: Page, excel_value: str, log: AutomationLogger, delay: int) -> None:
    """Match the Excel RTO against the currently available portal options."""
    opened = False
    try:
        dropdown = page.locator(SEL_RTO_DROPDOWN).first
        await dropdown.wait_for(state="visible", timeout=10000)
        await dropdown.scroll_into_view_if_needed()
        await dropdown.click()
        opened = True
        panel = page.locator(".p-dropdown-panel:visible").last
        await panel.wait_for(state="visible", timeout=5000)
        items = panel.locator("li[role='option'], .p-dropdown-item")
        await items.first.wait_for(state="attached", timeout=10000)
        options = []
        for _ in range(10):
            options = [text.strip() for text in await items.all_text_contents()]
            if options and options[0].casefold() not in {"loading", "loading...", "fetching..."}:
                break
            await asyncio.sleep(0.3)
        name = match_rto_name(excel_value, options)
        if not name:
            await page.keyboard.press("Escape")
            opened = False
            log.warning(f"No RTO matched the Excel value '{excel_value}'; review it manually.")
            return
        exact = items.filter(has_text=re.compile(r"^\s*" + re.escape(name) + r"\s*$", re.IGNORECASE))
        count = await exact.count()
        if not count:
            await page.keyboard.press("Escape")
            opened = False
            log.warning(f"RTO '{name}' is no longer available in the portal; review it manually.")
            return
        if name.casefold() != excel_value.strip().casefold() or count > 1:
            log.warning(f"RTO from Excel '{excel_value}' matched portal option '{name}'"
                        + (f" ({count} identical labels; using the first)" if count > 1 else "")
                        + "; review the selected office.")
        await exact.first.click()
        opened = False
        log.field_selected("RTO", name, source="RTO name from Excel")
    except Exception as exc:
        if opened:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
        log.field_failed("RTO", str(exc))
    finally:
        await asyncio.sleep(delay / 1000.0)


async def _select_driver_city(page: Page, city: str, log: AutomationLogger, delay: int) -> bool:
    """Select the exact district from the live city dropdown."""
    opened = False
    try:
        dropdown = page.locator(SEL_CITY_DROPDOWN).first
        await dropdown.wait_for(state="visible", timeout=10000)
        await dropdown.scroll_into_view_if_needed()
        await dropdown.click()
        opened = True
        panel = page.locator(".p-dropdown-panel:visible").last
        await panel.wait_for(state="visible", timeout=5000)
        items = panel.locator("li[role='option'], .p-dropdown-item")
        exact = items.filter(has_text=re.compile(r"^\s*" + re.escape(city) + r"\s*$", re.IGNORECASE))
        count = 0
        for _ in range(15):
            count = await exact.count()
            if count:
                break
            await asyncio.sleep(0.3)
        if count != 1:
            log.warning(f"City '{city}' has {count} matching portal options; review it manually.")
            return False
        await exact.first.click()
        opened = False
        log.field_selected("City", city, source="Driver licence prefix")
        return True
    except Exception as exc:
        log.field_failed("City", str(exc))
        return False
    finally:
        if opened:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
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
    from app.utils import load_automation_defaults as _load_defaults
    _automation_defaults: dict = _load_defaults(
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
        next_clicked = await _click_next_button(page, log)
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

    # 15. Match the RTO value extracted from Excel to the portal's options.
    rto = str(claim.rto_name or "").strip()
    if rto:
        await _select_rto(page, rto, log, delay)
    else:
        log.warning("RTO name was not found in Excel; review it manually.")

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

async def _fill_driver_details(page: Page, claim, log, delay: int, automation_defaults: dict | None = None):
    """Fill Driver Details subsection — all 19 fields."""
    log._section = "Driver Details"

    # Row 1 ─────────────────────────────────────────────────────────────────

    # 1. Driver Name * (mandatory)
    if claim.driver_name:
        await fill_input_with_delay(
            page, SEL_DRIVER_NAME, claim.driver_name,
            "Driver Name", log, delay
        )

    # 2. Date of Birth * (mandatory) — MUI DatePicker (DD-MM-YYYY)
    _dob = format_oic_date(claim.dob_of_driver)
    if _dob:
        await fill_mui_datepicker(
            page, SEL_DOB_OF_DRIVER_LABEL, _dob,
            "Date of Birth", log, delay
        )

    # 3. License Type * (mandatory) — PrimeNG dropdown
    if claim.license_type_of_driver:
        await select_primeng_dropdown(
            page, SEL_LICENSE_TYPE_DROPDOWN, claim.license_type_of_driver,
            "License Type", log, delay
        )

    # 4. Valid From * (mandatory) — MUI DatePicker (DL issue date, DD-MM-YYYY)
    _dl_issue = format_oic_date(claim.driver_license_issue_date)
    if _dl_issue:
        await fill_mui_datepicker(
            page, SEL_LICENSE_VALID_FROM_LABEL, _dl_issue,
            "Valid From (DL Issue Date)", log, delay
        )

    # Row 2 ─────────────────────────────────────────────────────────────────

    # 5. Valid Up To * (mandatory) — MUI DatePicker (DL expiry date, DD-MM-YYYY)
    _dl_expiry = format_oic_date(claim.driver_license_expiry_date)
    if _dl_expiry:
        await fill_mui_datepicker(
            page, SEL_LICENSE_VALID_UPTO_LABEL, _dl_expiry,
            "Valid Up To (DL Expiry Date)", log, delay
        )

    # 6-8. License Number * (mandatory) — split into 3 parts
    if claim.driver_license_number:
        parts = _split_license_number(claim.driver_license_number)
        if parts[0]:
            await select_primeng_dropdown(
                page, SEL_LICENSE_NO_1, parts[0],
                "License No. Field 1", log, delay
            )
        if parts[1]:
            await fill_input_with_delay(
                page, SEL_LICENSE_NO_2, parts[1],
                "License No. Field 2", log, delay
            )
        if parts[2]:
            await fill_input_with_delay(
                page, SEL_LICENSE_NO_3, parts[2],
                "License No. Field 3", log, delay
            )

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
        # Wait briefly for the portal to reveal the "Relation of Driver" field
        await asyncio.sleep(0.4)
        # Fill "Relation of Driver" with the configurable hardcoded default.
        # Prefer the pre-loaded defaults dict passed from fill_basic_details();
        # fall back to a fresh load only if called standalone (e.g. from tests).
        _defaults = automation_defaults or {}
        _relation = str(
            _defaults.get("driver_relation_default", "Self") or "Self"
        ).strip()
        try:
            rel_loc = page.locator(SEL_RELATION_OF_DRIVER).first
            rel_visible = await rel_loc.is_visible(timeout=3000)
            if rel_visible:
                await fill_input_with_delay(
                    page, SEL_RELATION_OF_DRIVER, _relation,
                    "Relation of Driver", log, delay
                )
            else:
                log.info(f"  ℹ️ [Relation of Driver] field not visible — skipped")
        except Exception:
            log.info(f"  ℹ️ [Relation of Driver] field not found — skipped")

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

    # 15. State * (mandatory) — use the driving licence's issuing-state prefix.
    state = _state_from_driver_license(claim.driver_license_number)
    if state:
        await select_primeng_dropdown(
            page, SEL_STATE_DROPDOWN, state,
            "State", log, delay
        )
    else:
        log.warning("Driver State could not be determined from the driving licence prefix; review it manually.")

    # 16. Use the issuing-office code in the driver's licence for the district.
    # Do not continue with a stale city or PIN if state/city selection failed.
    if not state:
        return False
    state_label = page.locator(f"{SEL_STATE_DROPDOWN} .p-dropdown-label").first
    if (await state_label.inner_text()).strip().casefold() != state.casefold():
        log.warning("Driver State was not selected; city and PIN require manual review.")
        return False
    city = city_from_licence(claim.driver_license_number)
    if not city:
        log.warning("No city mapping exists for the driver licence prefix; review it manually.")
        return False
    if not await _select_driver_city(page, city, log, delay):
        return False

    # Row 5 ─────────────────────────────────────────────────────────────────

    # 17. Pincode * (mandatory) — PrimeNG dropdown
    # NOTE: Pincode options load dynamically after State & City are selected.
    # We use a dedicated helper that waits for the dropdown to populate before
    # attempting to match the 6-digit code.
    #
    # F4 — Explicit settle delay: Angular triggers an async XHR after City
    # selection to fetch pincodes for the chosen city. The dropdown transitions
    # through disabled → enabled once the XHR resolves. Without this sleep the
    # _select_pincode_dropdown poll can start while the DOM update is still
    # in-flight, causing the first few p-disabled checks to be unreliable.
    # 800 ms gives Angular one full change-detection cycle (typically ~400 ms)
    # plus a safety margin, without adding significant wall-clock cost.
    await asyncio.sleep(0.8)
    if not await _select_pincode_dropdown(page, SEL_PINCODE_DROPDOWN, log, delay):
        return False

    # 18. Address * (mandatory) — textarea
    address = claim.driver_address or claim.place_of_survey or ""
    if address:
        await fill_input_with_delay(
            page, SEL_DRIVER_ADDRESS, address,
            "Address", log, delay
        )

    # Row 6 ─────────────────────────────────────────────────────────────────

    # 19. Charges Filed (optional) — textarea
    if claim.charges_filed:
        await fill_input_with_delay(
            page, SEL_CHARGES_FILED, claim.charges_filed,
            "Charges Filed", log, delay
        )

    log.success("  ✅ Driver Details subsection done.")
    return True


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
        await fill_input_with_delay(
            page, SEL_WORKSHOP_GST, claim.gst_number,
            "GST Number", log, delay
        )

    log.success("  ✅ Workshop Details subsection done.")


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — NEXT BUTTON
# ══════════════════════════════════════════════════════════════════════════════

async def _click_next_button(page: Page, log) -> bool:
    """Click the Next button to advance from Basic Details to Interim Report.

    Strategy (mirrors interim_report_module._click_next_button):
      1. Try selectors in priority order until one is visible & clickable.
      2. After clicking, verify the page actually transitioned by checking:
         - Strategy A: URL changed (most reliable)
         - Strategy B: An Interim Report heading appeared in the DOM
      3. If neither fired, the page likely stayed on Step 2 due to a
         validation error (e.g. empty "Relationship of Driver").  Scan for
         visible .error-message elements, log them, take a screenshot,
         and return False — so automation stops immediately instead of
         cascading into 15+ timeout errors on the next step.

    Returns True on success, False on failure.
    """
    candidates = [
        SEL_BASIC_DETAILS_NEXT,
        "button:has-text('Next')",
        "button.p-button:has-text('Next')",
        "button[type='button']:has-text('Next')",
    ]

    # Capture URL before clicking so we can detect navigation.
    url_before = page.url

    for selector in candidates:
        try:
            loc = page.locator(selector).first
            if not await loc.is_visible():
                continue

            await loc.scroll_into_view_if_needed()
            await asyncio.sleep(0.3)
            await loc.click()
            log.info("  ✅ Next button clicked — waiting for page transition...")

            # ── Post-click verification ──────────────────────────────────
            transitioned = False

            # Strategy A: URL changed (most reliable)
            try:
                await page.wait_for_function(
                    "url => window.location.href !== url",
                    arg=url_before,
                    timeout=8000,
                )
                transitioned = True
            except Exception:
                pass

            # Strategy B: An Interim Report heading appeared in DOM
            if not transitioned:
                try:
                    await page.wait_for_selector(
                        "text=Interim Report",
                        state="visible",
                        timeout=5000,
                    )
                    transitioned = True
                except Exception:
                    pass

            if transitioned:
                log.info("  ✅ Page transitioned to Interim Report (Step 3)")
                return True

            # ── Transition failed — likely form validation error ─────────
            # Scan the page for visible .error-message elements and log them
            # so the user knows exactly which field(s) blocked progression.
            error_msgs = []
            try:
                error_locs = page.locator(".error-message:visible")
                count = await error_locs.count()
                for i in range(min(count, 10)):  # Cap at 10 to avoid spam
                    txt = (await error_locs.nth(i).inner_text()).strip()
                    if txt:
                        error_msgs.append(txt)
            except Exception:
                pass

            if error_msgs:
                log.warning(
                    f"  ⚠️ Next clicked but page did not transition — "
                    f"{len(error_msgs)} validation error(s) found:"
                )
                for msg in error_msgs:
                    log.warning(f"     • {msg}")
            else:
                log.warning(
                    "  ⚠️ Next clicked but page did not transition — "
                    "possible validation error on Basic Details form"
                )

            await capture_error_screenshot(page, "basic_details_next_no_transition", log)
            return False

        except Exception:
            continue  # Try next selector

    log.warning("  ⚠️ Next button not found with any selector strategy.")
    await capture_error_screenshot(page, "basic_details_next_not_found", log)
    return False


# ══════════════════════════════════════════════════════════════════════════════
# PRIVATE — PINCODE DROPDOWN HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def _select_pincode_dropdown(
    page: Page,
    selector: str,
    log,
    delay: int,
) -> bool:
    """Select the first available six-digit PIN for the selected city."""
    opened = False
    try:
        dropdown = page.locator(selector).first
        enabled = False
        for _ in range(20):
            await asyncio.sleep(0.3)
            try:
                is_disabled = await dropdown.evaluate(
                    "el => el.classList.contains('p-disabled') || "
                    "!!el.closest('.p-disabled')"
                )
                if not is_disabled:
                    enabled = True
                    break
            except Exception:
                pass

        if not enabled:
            log.warning("Pincode dropdown is unavailable; review it manually.")
            return False

        await dropdown.wait_for(state="visible", timeout=5000)
        await dropdown.scroll_into_view_if_needed()
        await dropdown.click()
        opened = True
        panel = page.locator(".p-dropdown-panel:visible").last
        await panel.wait_for(state="visible", timeout=5000)
        items = panel.locator("li[role='option']:not([aria-disabled='true']):not(.p-disabled)")

        for _ in range(15):
            await asyncio.sleep(0.3)
            labels = await items.all_text_contents()
            for index, text in enumerate(labels):
                value = text.strip()
                if re.match(r"^\d{6}(?!\d)", value):
                    await items.nth(index).click()
                    opened = False
                    log.field_selected("Pincode", value, source="First available portal option")
                    return True
        log.warning("No PIN options loaded for the selected city; review it manually.")
        return False

    except Exception as exc:
        log.field_failed("Pincode", str(exc))
        return False
    finally:
        if opened:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
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


def _split_license_number(license_no: str) -> tuple:
    """
    Split license number into 3 parts for the OIC form.

    Examples:
      "HR49 2016 0000013"       → ("HR49", "2016", "0000013")
      "HR49/PDL/0000013/2016"   → ("HR49", "PDL", "0000013")
      "DL1420110001234"         → ("DL14", "2011", "0001234")
      "HR49 20160000013"        → ("HR49", "2016", "0000013")
    """
    if not license_no:
        return ("", "", "")

    raw = str(license_no).strip()

    # Strategy 1: Space-separated (e.g., "HR49 2016 0000013")
    parts = raw.split()
    if len(parts) >= 3:
        return (parts[0], parts[1], parts[2])
    if len(parts) == 2:
        # Split second part if it's long enough
        p2 = parts[1]
        if len(p2) > 4:
            return (parts[0], p2[:4], p2[4:])
        return (parts[0], p2, "")

    # Strategy 2: Slash-separated (e.g., "HR49/PDL/0000013/2016")
    if "/" in raw:
        slash_parts = [p for p in raw.split("/") if p]
        if len(slash_parts) >= 3:
            return (slash_parts[0], slash_parts[1], slash_parts[2])

    # Strategy 3: Regex — state code + year + number
    m = re.match(r'^([A-Z]{2}\d{1,2})\s*(\d{4})\s*(\d+)$', raw, re.IGNORECASE)
    if m:
        return (m.group(1).upper(), m.group(2), m.group(3))

    # Fallback: first 4 chars, next 4 chars, rest
    if len(raw) > 8:
        return (raw[:4], raw[4:8], raw[8:])

    return (raw, "", "")


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

    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.field_failed(label, str(e))
        else:
            log(f"[{_ts()}]   ⚠️ [{label}] error: {e}")

    await asyncio.sleep(delay / 1000.0)
