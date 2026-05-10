import asyncio
import re
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay, format_date_ddmmyyyy
)

async def fill_registration_cert_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    log("Opening Registration Certificate Details section...")
    
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
            log("  ✅ Expanded Registration Certificate Details.")
        else:
            log("  ℹ️ Registration Certificate Details already expanded.")
    except Exception as e:
        log(f"  ⚠️ Could not expand Registration Certificate Details: {e}")

    if stop_cb(): return False

    # 0. Reference No. (Optional)
    try:
        val = getattr(data, 'reference_no', '')
        if val:
            # The exact name attribute from the DOM is "Reference No" without a period
            # Or fallback to the angular model data-ng-model="surveyorData.worklist.additionalDetails.refernceNo"
            ref_sel = 'input[name="Reference No"]'
            try:
                await page.wait_for_selector(ref_sel, state="attached", timeout=2000)
                sel_to_use = ref_sel
            except Exception:
                sel_to_use = 'input[data-ng-model="surveyorData.worklist.additionalDetails.refernceNo"]'
            
            await fill_input_with_delay(page, sel_to_use, val, "Reference No", log, field_delay_ms)
        else:
            log("  ℹ️ Reference No missing from Excel, skipping (Optional).")
    except Exception as e:
        log(f"  ⚠️ Error filling Reference No: {e}")

    if stop_cb(): return False

    # 1. Registered Owner Name (Mandatory)
    try:
        val = data.registered_owner_name
        if val:
            await fill_input_with_delay(page, 'input[name="Registered Owner Name"]', val, "Owner Name", log, field_delay_ms)
        else:
            log("  ⚠️ Registered Owner Name missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling owner name: {e}")

    if stop_cb(): return False

    # 2. Vehicle Registration Number (Optional, split into 4)
    try:
        reg_no = data.vehicle_registration_number or ""
        # Clean: remove spaces, special chars
        reg_no = re.sub(r'[^A-Z0-9]', '', str(reg_no).upper())
        if reg_no:
            # Simple regex to split: 2 letters, 1-2 digits, 1-3 letters, 1-4 digits
            m = re.match(r'^([A-Z]{2})(\d{1,2})([A-Z]{1,3})?(\d{1,4})$', reg_no)
            if m:
                p1, p2, p3, p4 = m.groups()
                p3 = p3 or ""
                log(f"Filling Registration Number: {p1}-{p2}-{p3}-{p4}")
                await fill_input_with_delay(page, 'input[name="registrationNo1"]', p1, "Reg1", log, field_delay_ms)
                await fill_input_with_delay(page, 'input[name="registrationNo2"]', p2, "Reg2", log, field_delay_ms)
                if p3:
                    await fill_input_with_delay(page, 'input[name="registrationNo3"]', p3, "Reg3", log, field_delay_ms)
                await fill_input_with_delay(page, 'input[name="registrationNo4"]', p4, "Reg4", log, field_delay_ms)
            else:
                log(f"  ⚠️ Regex failed to match standard format for {reg_no}. Automation skipping fields.")
        else:
            log("  ℹ️ Vehicle Registration Number missing, skipping (Optional).")
    except Exception as e:
        log(f"  ⚠️ Error filling Registration Number: {e}")

    if stop_cb(): return False

    # 3. Date of Registration (Optional)
    try:
        val = data.date_of_registration
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="registrationDate"]', formatted_date, "Reg Date", log, field_delay_ms)
        else:
            log("  ℹ️ Date of Registration missing, skipping (Optional).")
    except Exception as e:
        log(f"  ⚠️ Error filling Date of Registration: {e}")

    if stop_cb(): return False

    # 4. Engine Number (Mandatory)
    try:
        val = data.engine_no
        if val:
            await fill_input_with_delay(page, 'input[name="Engine no"]', val, "Engine No", log, field_delay_ms)
        else:
            log("  ⚠️ Engine Number missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling Engine Number: {e}")

    if stop_cb(): return False

    # 5. Chassis Number (Mandatory)
    try:
        val = data.chassis_no
        if val:
            await fill_input_with_delay(page, 'input[name="Chassis no"]', val, "Chassis No", log, field_delay_ms)
        else:
            log("  ⚠️ Chassis Number missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling Chassis Number: {e}")

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
                log("  ✅ Physically Verified set to YES")
    except Exception as e:
        log(f"  ⚠️ Error checking Physically Verified: {e}")

    if stop_cb(): return False

    # 8. Type of Body (Dropdown - Mandatory)
    try:
        val = data.type_of_body
        if val:
            await select_dropdown_with_delay(page, 'select[name="Type of Body"]', val, "Type of Body", log, field_delay_ms)
        else:
            log("  ⚠️ Type Of Body missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error selecting Type Of Body: {e}")

    if stop_cb(): return False

    # 9. Class of Vehicle (Text field - Mandatory)
    try:
        val = data.class_of_vehicle
        if val:
            await fill_input_with_delay(page, 'input[name="Class of Vehicle"]', val, "Class of Vehicle", log, field_delay_ms)
        else:
            log("  ⚠️ Class of Vehicle missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling Class of Vehicle: {e}")

    if stop_cb(): return False

    # 10. Pre-Accident Condition (Text field - Mandatory)
    try:
        val = data.pre_accident_condition
        if val:
            await fill_input_with_delay(page, 'input[name="Pre-Accident Condition"]', val, "Pre-Accident Condition", log, field_delay_ms)
        else:
            log("  ⚠️ Pre-Accident Condition missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling Pre-Accident Condition: {e}")

    if stop_cb(): return False

    # 11. Route/Area of Operation (Optional)
    try:
        val = data.route_area_of_operation
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.routeOfOprtn"]', val, "Route/Area", log, field_delay_ms)
        else:
            log("  ℹ️ Route/Area of Operation missing, skipping (Optional).")
    except Exception as e:
        log(f"  ⚠️ Error filling Route/Area of Operation: {e}")

    if stop_cb(): return False

    # 12. Tax Paid Upto (Optional)
    try:
        val = data.tax_paid_upto
        if val:
            await fill_input_with_delay(page, 'input[name="taxPaidUpto"]', val, "Tax Paid Upto", log, field_delay_ms)
        else:
            log("  ℹ️ Tax Paid Upto missing, skipping (Optional).")
    except Exception as e:
        log(f"  ⚠️ Error filling Tax Paid Upto: {e}")

    if stop_cb(): return False

    # 13. RTO Name (Mandatory)
    try:
        val = data.rto_name
        if val:
            await fill_input_with_delay(page, 'input[name="RTO Name"]', val, "RTO Name", log, field_delay_ms)
        else:
            log("  ⚠️ RTO Name missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling RTO Name: {e}")

    if stop_cb(): return False

    # 14. Transfer Date (Optional)
    try:
        val = data.transfer_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="transferDate"]', formatted_date, "Transfer Date", log, field_delay_ms)
        else:
            log("  ℹ️ Transfer Date missing, skipping (Optional).")
    except Exception as e:
        log(f"  ⚠️ Error filling Transfer Date: {e}")

    if stop_cb(): return False

    # 15. Odometer Reading (Mandatory)
    try:
        val = data.odometer_reading
        if val:
            # Clean: extract ONLY numeric digits (removes 'KM', 'kilometers', etc.)
            cleaned_val = re.sub(r'\D', '', str(val))
            if cleaned_val:
                await fill_input_with_delay(page, 'input[name="Odometer Reading"]', cleaned_val, "Odometer Reading", log, field_delay_ms)
            else:
                log(f"  ⚠️ Odometer value '{val}' contained no digits. Skipping.")
        else:
            log("  ⚠️ Odometer Reading missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling Odometer Reading: {e}")

    if stop_cb(): return False

    # 16. Vehicle Color (Mandatory)
    try:
        val = data.vehicle_color
        if val:
            await fill_input_with_delay(page, 'input[name="Vehicle Color"]', val, "Vehicle Color", log, field_delay_ms)
        else:
            log("  ⚠️ Vehicle Color missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling Vehicle Color: {e}")

    if stop_cb(): return False

    # 17. Vehicle Color Type (Mandatory)
    try:
        val = data.vehicle_color_type
        if val:
            await fill_input_with_delay(page, 'input[name="Vehicle Color Type"]', val, "Color Type", log, field_delay_ms)
        else:
            log("  ⚠️ Vehicle Color Type missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling Vehicle Color Type: {e}")

    if stop_cb(): return False

    # 18. Type of Vehicle (Dropdown - Mandatory)
    # FIX: Try primary selector first, then ng-model fallback.
    #      Also dump available options when no match found to aid debugging.
    try:
        val = data.type_of_vehicle
        if val:
            # Primary selector (name attribute)
            _veh_sel = 'select[name="Type of Vehicle"]'
            # Fallback selector (ng-model)
            _veh_sel_fb = 'select[data-ng-model*="typeOfVehicle"], select[ng-model*="typeOfVehicle"]'

            # Try primary
            try:
                await page.wait_for_selector(_veh_sel, state="visible", timeout=4000)
                sel_to_use = _veh_sel
            except Exception:
                # Try fallback
                try:
                    await page.wait_for_selector(_veh_sel_fb, state="visible", timeout=4000)
                    sel_to_use = _veh_sel_fb
                    log("  ℹ️ [Type of Vehicle] using ng-model fallback selector.")
                except Exception:
                    sel_to_use = _veh_sel  # let select_dropdown log the error

            # Debug: log available options
            try:
                opts = await page.evaluate(f"""
                    () => {{
                        const s = document.querySelector('{sel_to_use}');
                        if (!s) return [];
                        return Array.from(s.options).map(o => o.text.trim());
                    }}
                """)
                log(f"  ℹ️ [Type of Vehicle] available options: {opts}")
            except Exception:
                pass

            await select_dropdown_with_delay(page, sel_to_use, val, "Type of Vehicle", log, field_delay_ms)
        else:
            log("  ⚠️ Type Of Vehicle missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error selecting Type Of Vehicle: {e}")

    if stop_cb(): return False

    # 19. Type of Fuel (Dropdown - Mandatory)
    # FIX: Same dual-selector strategy as Type of Vehicle.
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
                    log("  ℹ️ [Type of Fuel] using ng-model fallback selector.")
                except Exception:
                    sel_to_use = _fuel_sel

            # Debug: log available options
            try:
                opts = await page.evaluate(f"""
                    () => {{
                        const s = document.querySelector('{sel_to_use}');
                        if (!s) return [];
                        return Array.from(s.options).map(o => o.text.trim());
                    }}
                """)
                log(f"  ℹ️ [Type of Fuel] available options: {opts}")
            except Exception:
                pass

            await select_dropdown_with_delay(page, sel_to_use, val, "Type of Fuel", log, field_delay_ms)
        else:
            log("  ⚠️ Type Of Fuel missing from Excel.")
    except Exception as e:
        log(f"  ⚠️ Error selecting Type Of Fuel: {e}")

    log("Phase 5 (Registration Certificate Details) completed successfully.")
    return True
