import asyncio
import re
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.field_values import (
    DEFAULT_TYPE_OF_BODY,
    configured_pre_accident_condition,
    normalize_vehicle_color,
    resolve_newindia_vehicle_type,
)
from app.portals.newindia.automation.ui_utils import (
    CHANNEL_MARUTI,
    check_checkbox_with_delay, fill_input_with_delay, select_dropdown_with_delay, format_date_ddmmyyyy,
    open_additional_section, record_additional_issue, resolve_newindia_channel,
)
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

async def _select_with_fallback(
    page: Page,
    primary_selector: str,
    fallback_selector: str,
    value: str,
    label: str,
    log,
    field_delay_ms: int,
    *,
    source: str = "Excel",
) -> None:
    """Select a dropdown value using the primary selector or an Angular ng-model fallback."""
    try:
        if not value:
            if isinstance(log, AutomationLogger):
                log.field_skipped(label, reason="Missing from Excel")
            else:
                log(f"   ⚠️ {label} missing from Excel.")
            return

        sel_to_use = primary_selector
        try:
            await page.locator(f":is({primary_selector}):visible").first.wait_for(state="visible", timeout=4000)
        except Exception:
            try:
                await page.locator(f":is({fallback_selector}):visible").first.wait_for(state="visible", timeout=4000)
                sel_to_use = fallback_selector
                if isinstance(log, AutomationLogger):
                    log.info(f"Using ng-model fallback for {label}.")
                else:
                    log(f"   ℹ️ [{label}] using ng-model fallback selector.")
            except Exception:
                sel_to_use = primary_selector

        await select_dropdown_with_delay(page, sel_to_use, value, label, log, field_delay_ms, source=source)
    except Exception:
        record_additional_issue(log, label)


async def _fill_optional_rc_field(
    page: Page,
    selector: str,
    fallback_selector: str,
    value: str,
    label: str,
    log,
    field_delay_ms: int,
    *,
    kind: str = "text",
    max_len: int | None = None,
) -> None:
    """Format and optionally fill a verified RC detail box if present on the current claim form."""
    raw = str(value or "").strip()
    if kind == "digits":
        num_match = re.match(r"(\d[\d,]*)(?:\.\d+)?", raw)
        formatted = re.sub(r"\D", "", num_match.group(1) if num_match else raw)
        if max_len:
            formatted = formatted[:max_len]
    elif kind == "date":
        formatted = format_date_ddmmyyyy(raw) if raw else ""
    else:
        formatted = raw[:max_len] if max_len else raw

    if not formatted:
        if isinstance(log, AutomationLogger):
            log.field_skipped(label, reason="Missing from Excel")
        else:
            log(f"   ℹ️ {label} missing from data, skipping (Optional).")
        return

    chosen = None
    for candidate in (selector, fallback_selector):
        if not candidate:
            continue
        loc = page.locator(candidate).first
        try:
            if await loc.is_visible():
                chosen = candidate
                break
        except Exception:
            continue

    if not chosen:
        if isinstance(log, AutomationLogger):
            log.field_skipped(label, reason="Not shown on this claim")
        else:
            log(f"   ⏭️ Skipped '{label}' — Not shown on this claim")
        return

    try:
        await fill_input_with_delay(page, chosen, formatted, label, log, field_delay_ms, source="Excel")
    except Exception:
        record_additional_issue(log, label)


_JS_INSPECT_BODY_DROPDOWN = r"""
(select, [rawVal, fallbackVal]) => {
    if (!select) return { disabled: false, currentValue: '', optionCount: 0, rawMatched: false, fallbackMatched: false };
    const options = [...select.options].filter(option => option.value && !option.disabled);
    const label = option => option.text.trim().toLowerCase();
    const hasUniqueMatch = (txt) => {
        const search = String(txt || '').trim().toLowerCase();
        if (!search) return false;
        const words = search.split(/\s+/).filter(word => word.length > 2);
        const matches = options.filter(option => label(option) === search);
        if (!matches.length) {
            matches.push(...options.filter(option => label(option) && (label(option).includes(search) || search.includes(label(option)))));
        }
        if (!matches.length && words.length) {
            matches.push(...options.filter(option => words.some(word => label(option).includes(word))));
        }
        return matches.length === 1;
    };
    const fb = String(fallbackVal || '').trim().toLowerCase();
    let fallbackMatched = false;
    if (fb) {
        const exactFb = options.filter(option => label(option) === fb);
        if (exactFb.length === 1) {
            fallbackMatched = true;
        } else {
            const subFb = options.filter(option => label(option) && (label(option).includes(fb) || fb.includes(label(option))));
            fallbackMatched = subFb.length === 1;
        }
    }
    return {
        disabled: Boolean(select.disabled),
        currentValue: String(select.value || ''),
        optionCount: options.length,
        rawMatched: Boolean(rawVal && hasUniqueMatch(rawVal)),
        fallbackMatched,
    };
}
"""


async def _fill_type_of_vehicle(
    page: Page,
    data: ClaimData,
    log,
    field_delay_ms: int,
) -> None:
    val = str(getattr(data, "type_of_vehicle", "") or "").strip()
    derived_inline = False
    if not val:
        val, inline_src = resolve_newindia_vehicle_type(
            getattr(data, "class_of_vehicle", ""),
            getattr(data, "registered_laden_weight", ""),
        )
        derived_inline = bool(inline_src)
    coord = str(getattr(data, "_excel_coords", {}).get("type_of_vehicle", "") or "")
    source = "Calculated" if (derived_inline or coord.startswith(("Mapped", "Derived"))) else "Excel"
    await _select_with_fallback(
        page,
        'select[name="Type of Vehicle"]',
        'select[data-ng-model*="typeOfVehicle"], select[ng-model*="typeOfVehicle"]',
        val,
        "Type of Vehicle",
        log,
        field_delay_ms,
        source=source,
    )


async def _fill_type_of_body_if_visible(
    page: Page,
    data: ClaimData,
    log,
    field_delay_ms: int,
) -> None:
    body_loc = page.locator(
        'select[name="Type of Body"]:visible, '
        'select[data-ng-model*="typeOfBody"]:visible, '
        'select[ng-model*="typeOfBody"]:visible'
    )
    if not await body_loc.count():
        if isinstance(log, AutomationLogger):
            log.field_skipped("Type of Body", reason="Not shown on this claim")
        return

    raw_body = str(getattr(data, "type_of_body", "") or "").strip()
    info = None
    for step in range(4):
        try:
            info = await body_loc.first.evaluate(_JS_INSPECT_BODY_DROPDOWN, [raw_body, DEFAULT_TYPE_OF_BODY])
        except Exception:
            info = None
            break
        if info and info.get("optionCount", 0) > 0:
            break
        if step < 3:
            await asyncio.sleep(0.15)

    primary = 'select[name="Type of Body"]'
    fallback = 'select[data-ng-model*="typeOfBody"], select[ng-model*="typeOfBody"]'

    if info:
        if info.get("disabled") and info.get("currentValue"):
            if isinstance(log, AutomationLogger):
                log.field_skipped("Type of Body", reason="Read-only on this claim")
            return
        if raw_body and info.get("rawMatched"):
            await _select_with_fallback(
                page, primary, fallback, raw_body, "Type of Body", log, field_delay_ms, source="Excel",
            )
            return
        if info.get("fallbackMatched"):
            msg = (
                f"Type of Body '{raw_body}' not in dropdown — using '{DEFAULT_TYPE_OF_BODY}'."
                if raw_body
                else f"Type of Body blank — using '{DEFAULT_TYPE_OF_BODY}'."
            )
            if isinstance(log, AutomationLogger):
                log.info(msg)
            else:
                log(f"   ℹ️ {msg}")
            await _select_with_fallback(
                page, primary, fallback, DEFAULT_TYPE_OF_BODY, "Type of Body", log, field_delay_ms, source="Fallback",
            )
            return

    attempt = raw_body or DEFAULT_TYPE_OF_BODY
    src = "Excel" if raw_body else "Fallback"
    await _select_with_fallback(
        page, primary, fallback, attempt, "Type of Body", log, field_delay_ms, source=src,
    )


async def fill_registration_cert_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log._section = "Registration Certificate Details"
        log.info("Opening Registration Certificate Details section...")
        log.indent()
    else:
        log(f"Opening Registration Certificate Details section...")

    try:
        return await _fill_registration_cert_inner(page, data, log, stop_cb, field_delay_ms)
    finally:
        if isinstance(log, AutomationLogger):
            log.outdent()


async def _fill_registration_cert_inner(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    
    # 0. Reference No. (Optional) - Filled BEFORE expanding accordion because it is outside
    try:
        val = getattr(data, 'reference_no', '')
        if val:
            ref_sel = 'input[name="Reference No"]'
            try:
                await page.wait_for_selector(ref_sel, state="attached", timeout=2000)
                sel_to_use = ref_sel
            except Exception:
                sel_to_use = 'input[data-ng-model="surveyorData.worklist.additionalDetails.refernceNo"]'
            
            await fill_input_with_delay(page, sel_to_use, val, "Reference No", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Reference No", reason="Missing from Excel")
            else:
                log(f"   ℹ️ Reference No missing from Excel, skipping (Optional).")
    except Exception:
        record_additional_issue(log, "Reference No.")

    if stop_cb(): return False

    if not await open_additional_section(page, "Registration Certificate Details", log):
        return not stop_cb()

    if stop_cb():
        return False

    # 1. Registered Owner Name (Mandatory)
    try:
        val = data.registered_owner_name
        if val:
            await fill_input_with_delay(page, 'input[name="Registered Owner Name"]', val, "Owner Name", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Owner Name", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Registered Owner Name missing from Excel.")
    except Exception:
        record_additional_issue(log, "Registered Owner Name")

    if stop_cb(): return False

    # 2. Vehicle Registration Number (Optional, split into 4)
    try:
        reg_no = data.vehicle_registration_number or ""
        reg_no = re.sub(r'[^A-Z0-9]', '', str(reg_no).upper())
        if reg_no:
            m = re.match(r'^([A-Z]{2})(\d{1,2})([A-Z]{1,3})?(\d{1,4})$', reg_no)
            if m:
                p1, p2, p3, p4 = m.groups()
                p3 = p3 or ""
                if isinstance(log, AutomationLogger):
                    log.info(f"Filling Registration Number: {p1}-{p2}-{p3}-{p4}")
                else:
                    log(f"Filling Registration Number: {p1}-{p2}-{p3}-{p4}")
                await fill_input_with_delay(page, 'input[name="registrationNo1"]', p1, "Reg1", log, field_delay_ms, source="Excel")
                await fill_input_with_delay(page, 'input[name="registrationNo2"]', p2, "Reg2", log, field_delay_ms, source="Excel")
                if p3:
                    await fill_input_with_delay(page, 'input[name="registrationNo3"]', p3, "Reg3", log, field_delay_ms, source="Excel")
                await fill_input_with_delay(page, 'input[name="registrationNo4"]', p4, "Reg4", log, field_delay_ms, source="Excel")
            else:
                if isinstance(log, AutomationLogger):
                    log.warning(f"Registration format {reg_no} not supported for split-field automation.")
                else:
                    log(f"   ⚠️ Regex failed to match standard format for {reg_no}. Automation skipping fields.")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Registration Number", reason="Missing from Excel")
            else:
                log(f"   ℹ️ Vehicle Registration Number missing, skipping (Optional).")
    except Exception:
        record_additional_issue(log, "Vehicle Registration Number")

    if stop_cb(): return False

    is_maruti = resolve_newindia_channel(page, data) == CHANNEL_MARUTI

    # 3. Type of Vehicle (Maruti: Row 1 Col 4 right after Reg No; Non-Tie-Up fills before Fuel)
    if is_maruti:
        await _fill_type_of_vehicle(page, data, log, field_delay_ms)
        if stop_cb():
            return False

    # 4. Date of Registration (Optional)
    try:
        val = data.date_of_registration
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="registrationDate"]', formatted_date, "Reg Date", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Reg Date", reason="Missing from Excel")
            else:
                log(f"   ℹ️ Date of Registration missing, skipping (Optional).")
    except Exception:
        record_additional_issue(log, "Date of Registration")

    if stop_cb(): return False

    # 4. Engine Number (Mandatory)
    try:
        val = data.engine_no
        if val:
            await fill_input_with_delay(page, 'input[name="Engine no"]', val, "Engine No", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Engine No", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Engine Number missing from Excel.")
    except Exception:
        record_additional_issue(log, "Engine No.")

    if stop_cb(): return False

    # 5. Chassis Number (Mandatory)
    try:
        val = data.chassis_no
        if val:
            await fill_input_with_delay(page, 'input[name="Chassis no"]', val, "Chassis No", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Chassis No", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Chassis Number missing from Excel.")
    except Exception:
        record_additional_issue(log, "Chassis No.")

    if stop_cb(): return False

    # 6. Physically Verified (ALWAYS YES)
    try:
        selector = 'input[name="Physically Verified -checkBox"]'
        if await page.locator(selector).count():
            await check_checkbox_with_delay(page, selector, "Physically Verified", log, field_delay_ms, source="Calculated")
    except Exception:
        record_additional_issue(log, "Physically Verified")

    if stop_cb(): return False

    await _fill_type_of_body_if_visible(page, data, log, field_delay_ms)

    if stop_cb(): return False

    # 8. Class of Vehicle (Text field - Mandatory)
    try:
        val = data.class_of_vehicle
        if val:
            await fill_input_with_delay(page, 'input[name="Class of Vehicle"]', val, "Class of Vehicle", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Class of Vehicle", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Class of Vehicle missing from Excel.")
    except Exception:
        record_additional_issue(log, "Class of Vehicle")

    if stop_cb(): return False

    # 10. Pre-Accident Condition (Text field - Mandatory)
    try:
        defaults = load_automation_defaults(portal_id="newindia")
        await fill_input_with_delay(
            page, 'input[name="Pre-Accident Condition"]', configured_pre_accident_condition(defaults),
            "Pre-Accident Condition", log, field_delay_ms, source="Default",
        )
    except Exception:
        record_additional_issue(log, "Pre-Accident Condition")

    optional_rc_fields = (
        (
            'input[data-ng-model="surveyorData.worklist.additionalDetails.regLadenWt"]',
            'input[ng-model="surveyorData.worklist.additionalDetails.regLadenWt"]',
            getattr(data, "registered_laden_weight", ""),
            "Registered Laden Weight",
            "digits",
            10,
        ),
        (
            'input[data-ng-model="surveyorData.worklist.additionalDetails.unLadenWt"]',
            'input[ng-model="surveyorData.worklist.additionalDetails.unLadenWt"]',
            getattr(data, "unladen_weight", ""),
            "Unladen Weight",
            "digits",
            10,
        ),
        (
            'input[name="Fitness Cert.No."]',
            'input[data-ng-model="surveyorData.worklist.additionalDetails.fitnessCertNo"]',
            getattr(data, "fitness_cert_no", ""),
            "Fitness Cert. No.",
            "text",
            20,
        ),
        (
            'input[name="Fitness Cert. valid Upto"]',
            'input[data-ng-model="surveyorData.worklist.additionalDetails.fitnessCertValidUpto"]',
            getattr(data, "fitness_valid_upto", ""),
            "Fitness Cert. Valid Upto",
            "date",
            None,
        ),
        (
            'input[name="Permit No."]',
            'input[data-ng-model="surveyorData.worklist.additionalDetails.permitNo"]',
            getattr(data, "permit_number", ""),
            "Permit No.",
            "text",
            20,
        ),
        (
            'input[name="Permit Valid Upto"]',
            'input[data-ng-model="surveyorData.worklist.additionalDetails.permitValidUpto"]',
            getattr(data, "permit_valid_upto", ""),
            "Permit Valid Upto",
            "date",
            None,
        ),
    )
    for primary_sel, fallback_sel, field_val, field_label, field_kind, max_len in optional_rc_fields:
        if stop_cb():
            return False
        await _fill_optional_rc_field(
            page,
            primary_sel,
            fallback_sel,
            field_val,
            field_label,
            log,
            field_delay_ms,
            kind=field_kind,
            max_len=max_len,
        )

    if stop_cb(): return False

    # 11. Route/Area of Operation (Optional)
    try:
        val = data.route_area_of_operation
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.routeOfOprtn"]', val, "Route/Area", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Route/Area", reason="Missing from Excel")
            else:
                log(f"   ℹ️ Route/Area of Operation missing, skipping (Optional).")
    except Exception:
        record_additional_issue(log, "Route or Area of Operation")

    if stop_cb(): return False

    # 12. Tax Paid Upto (Optional)
    try:
        val = data.tax_paid_upto
        if val:
            await fill_input_with_delay(page, 'input[name="taxPaidUpto"]', val, "Tax Paid Upto", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Tax Paid Upto", reason="Missing from Excel")
            else:
                log(f"   ℹ️ Tax Paid Upto missing, skipping (Optional).")
    except Exception:
        record_additional_issue(log, "Tax Paid Upto")

    if stop_cb(): return False

    # 13. RTO Name (Mandatory)
    try:
        val = data.rto_name
        if val:
            await fill_input_with_delay(page, 'input[name="RTO Name"]', val, "RTO Name", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("RTO Name", reason="Missing from Excel")
            else:
                log(f"   ⚠️ RTO Name missing from Excel.")
    except Exception:
        record_additional_issue(log, "RTO Name")

    if stop_cb(): return False

    # 14. Transfer Date (Optional)
    try:
        val = data.transfer_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="transferDate"]', formatted_date, "Transfer Date", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Transfer Date", reason="Missing from Excel")
            else:
                log(f"   ℹ️ Transfer Date missing, skipping (Optional).")
    except Exception:
        record_additional_issue(log, "Transfer Date")

    if stop_cb(): return False

    # 15. Odometer Reading (Mandatory)
    try:
        val = data.odometer_reading
        if val:
            cleaned_val = re.sub(r'\D', '', str(val))
            if cleaned_val:
                await fill_input_with_delay(page, 'input[name="Odometer Reading"]', cleaned_val, "Odometer Reading", log, field_delay_ms, source="Excel")
            else:
                if isinstance(log, AutomationLogger):
                    log.warning(f"Odometer value '{val}' contained no digits.")
                else:
                    log(f"   ⚠️ Odometer value '{val}' contained no digits. Skipping.")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Odometer Reading", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Odometer Reading missing from Excel.")
    except Exception:
        record_additional_issue(log, "Odometer Reading")

    if stop_cb(): return False

    # 16. Vehicle Color (Mandatory)
    try:
        val = normalize_vehicle_color(data.vehicle_color)
        if val:
            await fill_input_with_delay(page, 'input[name="Vehicle Color"]', val, "Color", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Color", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Vehicle Color missing from Excel.")
    except Exception:
        record_additional_issue(log, "Vehicle Color")

    if stop_cb(): return False

    # 17. Vehicle Color Type (Mandatory)
    try:
        val = data.vehicle_color_type
        if val:
            await fill_input_with_delay(page, 'input[name="Vehicle Color Type"]', val, "Color Type", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Color Type", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Vehicle Color Type missing from Excel.")
    except Exception:
        record_additional_issue(log, "Vehicle Color Type")

    if stop_cb(): return False

    if not is_maruti:
        await _fill_type_of_vehicle(page, data, log, field_delay_ms)
        if stop_cb():
            return False

    # 19. Type of Fuel (Dropdown - Mandatory)
    await _select_with_fallback(
        page,
        'select[name="Type of fuel"]',
        'select[data-ng-model*="typeOfFuel"], select[ng-model*="typeOfFuel"]',
        data.type_of_fuel,
        "Type of Fuel",
        log,
        field_delay_ms,
    )

    if isinstance(log, AutomationLogger):
        log.success("Registration Certificate Details phase completed.")
    else:
        log(f" Phase 5 (Registration Certificate Details) completed successfully.")
    return True
