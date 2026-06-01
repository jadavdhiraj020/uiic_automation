import asyncio
import re
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay, format_date_ddmmyyyy
)
from app.automation.automation_logger import AutomationLogger

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Reference No field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Reference No: {e}")

    if stop_cb(): return False

    # Click to expand Registration Certificate Details accordion
    try:
        acc_heading = page.locator('a.accordion-toggle:has-text("Registration Certificate Details")').first
        await acc_heading.wait_for(state="visible", timeout=10000)
        
        # Check if collapsed
        parent_div = page.locator('div.panel-heading').filter(has=acc_heading).first
        is_collapsed = 'collapsed' in await parent_div.get_attribute('class')
        if is_collapsed:
            await acc_heading.click()
            await asyncio.sleep(1.0)
            if isinstance(log, AutomationLogger):
                log.success("Accordion expanded.")
            else:
                log(f"   ✅ Expanded Registration Certificate Details.")
        else:
            if isinstance(log, AutomationLogger):
                log.info("Accordion already expanded.")
            else:
                log(f"   ℹ️ Registration Certificate Details already expanded.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Expansion failed: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Could not expand Registration Certificate Details: {e}")

    if stop_cb(): return False

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Owner Name field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling owner name: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Registration Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Registration Number: {e}")

    if stop_cb(): return False

    # 3. Date of Registration (Optional)
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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Registration Date field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Date of Registration: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Engine Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Engine Number: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Chassis Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Chassis Number: {e}")

    if stop_cb(): return False

    # 6. Physically Verified (ALWAYS YES)
    try:
        cb_loc = page.locator('input[name="Physically Verified -checkBox"]').first
        if await cb_loc.count() > 0:
            is_checked = await cb_loc.is_checked()
            if not is_checked:
                await page.evaluate("""
                    () => {
                        const cb = document.querySelector('input[name="Physically Verified -checkBox"]');
                        if (cb) {
                            cb.click();
                        }
                    }
                """)
                await asyncio.sleep(field_delay_ms / 1000.0)
                if isinstance(log, AutomationLogger):
                    log.field_filled("Physically Verified", "Y", source="Calculated")
                else:
                    log(f"   ✅ Physically Verified set to YES")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Verification toggle error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error checking Physically Verified: {e}")

    if stop_cb(): return False

    # 8. Type of Body (Dropdown - Mandatory)
    try:
        val = data.type_of_body
        if val:
            await select_dropdown_with_delay(page, 'select[name="Type of Body"]', val, "Type of Body", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Type of Body", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Type Of Body missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Body Type field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Type Of Body: {e}")

    if stop_cb(): return False

    # 9. Class of Vehicle (Text field - Mandatory)
    try:
        val = data.class_of_vehicle
        if val:
            await fill_input_with_delay(page, 'input[name="Class of Vehicle"]', val, "Class of Vehicle", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Class of Vehicle", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Class of Vehicle missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Vehicle Class field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Class of Vehicle: {e}")

    if stop_cb(): return False

    # 10. Pre-Accident Condition (Text field - Mandatory)
    try:
        val = data.pre_accident_condition
        if val:
            await fill_input_with_delay(page, 'input[name="Pre-Accident Condition"]', val, "Condition", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Condition", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Pre-Accident Condition missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Condition field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Pre-Accident Condition: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Route field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Route/Area of Operation: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Tax field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Tax Paid Upto: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"RTO field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling RTO Name: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Transfer Date field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Transfer Date: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Odometer field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Odometer Reading: {e}")

    if stop_cb(): return False

    # 16. Vehicle Color (Mandatory)
    try:
        val = data.vehicle_color
        if val:
            await fill_input_with_delay(page, 'input[name="Vehicle Color"]', val, "Color", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Color", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Vehicle Color missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Color field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Vehicle Color: {e}")

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
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Color Type field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Vehicle Color Type: {e}")

    if stop_cb(): return False

    # 18. Type of Vehicle (Dropdown - Mandatory)
    try:
        val = data.type_of_vehicle
        if val:
            _veh_sel = 'select[name="Type of Vehicle"]'
            _veh_sel_fb = 'select[data-ng-model*="typeOfVehicle"], select[ng-model*="typeOfVehicle"]'

            try:
                await page.wait_for_selector(_veh_sel, state="visible", timeout=4000)
                sel_to_use = _veh_sel
            except Exception:
                try:
                    await page.wait_for_selector(_veh_sel_fb, state="visible", timeout=4000)
                    sel_to_use = _veh_sel_fb
                    if isinstance(log, AutomationLogger):
                        log.info("Using ng-model fallback for Vehicle Type.")
                    else:
                        log(f"   ℹ️ [Type of Vehicle] using ng-model fallback selector.")
                except Exception:
                    sel_to_use = _veh_sel 

            await select_dropdown_with_delay(page, sel_to_use, val, "Type of Vehicle", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Type of Vehicle", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Type Of Vehicle missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Vehicle Type field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Type Of Vehicle: {e}")

    if stop_cb(): return False

    # 19. Type of Fuel (Dropdown - Mandatory)
    try:
        val = data.type_of_fuel
        if val:
            _fuel_sel    = 'select[name="Type of fuel"]'
            _fuel_sel_fb = 'select[data-ng-model*="typeOfFuel"], select[ng-model*="typeOfFuel"]'

            try:
                await page.wait_for_selector(_fuel_sel, state="visible", timeout=4000)
                sel_to_use = _fuel_sel
            except Exception:
                try:
                    await page.wait_for_selector(_fuel_sel_fb, state="visible", timeout=4000)
                    sel_to_use = _fuel_sel_fb
                    if isinstance(log, AutomationLogger):
                        log.info("Using ng-model fallback for Fuel Type.")
                    else:
                        log(f"   ℹ️ [Type of Fuel] using ng-model fallback selector.")
                except Exception:
                    sel_to_use = _fuel_sel

            await select_dropdown_with_delay(page, sel_to_use, val, "Type of Fuel", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Type of Fuel", reason="Missing from Excel")
            else:
                log(f"   ⚠️ Type Of Fuel missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Fuel Type field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Type Of Fuel: {e}")

    if isinstance(log, AutomationLogger):
        log.success("Registration Certificate Details phase completed.")
    else:
        log(f" Phase 5 (Registration Certificate Details) completed successfully.")
    return True
