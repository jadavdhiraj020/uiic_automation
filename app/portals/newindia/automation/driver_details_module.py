import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay, format_date_ddmmyyyy
)
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

async def fill_driver_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False
    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))

    if isinstance(log, AutomationLogger):
        log.info("Opening Driver Details section...")
        log.indent()
    else:
        log(f"Opening Driver Details section...")
    
    # Click to expand Driver Details accordion
    try:
        acc_heading = page.locator('a.accordion-toggle:has-text("Driver Details")').first
        await acc_heading.wait_for(state="visible", timeout=10000)
        
        # Check if collapsed
        parent_div = page.locator('div.panel-heading').filter(has=acc_heading).first
        is_collapsed = 'collapsed' in await parent_div.get_attribute('class')
        if is_collapsed:
            await acc_heading.click()
            await asyncio.sleep(1.5)
            if isinstance(log, AutomationLogger):
                log.success("Accordion expanded.")
            else:
                log("   ✅ Expanded Driver Details.")
        else:
            if isinstance(log, AutomationLogger):
                log.info("Accordion already expanded.")
            else:
                log("   ℹ️ Driver Details already expanded.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.warning(f"Expansion attempt failed: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Could not expand Driver Details: {e}")

    if stop_cb(): return False

    # 1. Was Vehicle Parked During Accident (ALWAYS NO)
    try:
        if isinstance(log, AutomationLogger):
            log.info("Setting Parked Status to 'No'...")
        else:
            log(f"  ✏️ Selecting Vehicle Parked During Accident = NO...")
            
        await select_dropdown_with_delay(
            page, 'select[name="Was the vehicle parked during accident ?"]',
            "No", "Vehicle Parked", log, field_delay_ms
        )

        # Wait for the Relationship dropdown to become VISIBLE
        if isinstance(log, AutomationLogger):
            log.wait("Waiting for conditional fields to appear...")
        else:
            log(f"  ⏳ Waiting for Relationship dropdown to become visible...")
            
        try:
            await page.wait_for_selector(
                'select[name="Relationship of the driver with the Insured"]',
                state="visible", timeout=10000
            )
        except Exception:
            await page.wait_for_selector(
                'select[data-ng-model*="driverRelationship"], select[ng-model*="driverRelationship"]',
                state="visible", timeout=6000
            )
        await asyncio.sleep(0.8) 
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Parked Status dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Vehicle Parked During Accident: {e}")

    if stop_cb(): return False

    # 2. Relationship with Insured (Dynamic from Excel)
    try:
        val = data.driver_relationship_with_insured

        if val:
            await select_dropdown_with_delay(
                page,
                'select[name="Relationship of the driver with the Insured"]',
                val, "Relationship", log, field_delay_ms
            )
        else:
            relationship_default = str(defaults.get("relationship_with_insured", "Self") or "Self")
            if isinstance(log, AutomationLogger):
                log.warning(f"Relationship missing from data; defaulting to '{relationship_default}'.")
            else:
                log(f"   ⚠️ Relationship with Insured missing from Excel, defaulting to '{relationship_default}'")
            await select_dropdown_with_delay(
                page,
                'select[name="Relationship of the driver with the Insured"]',
                relationship_default, "Relationship", log, field_delay_ms
            )
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Relationship field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Relationship With Insured: {e}")

    if stop_cb(): return False

    # 3. License Type of Driver
    try:
        val = data.license_type_of_driver
        if val:
            await select_dropdown_with_delay(page, 'select[name="License Type of Driver"]', val, "License Type", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("License Type missing from source data.")
            else:
                log("   ⚠️ License Type of Driver missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"License Type field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting License Type of Driver: {e}")

    if stop_cb(): return False

    # 4. DOB of Driver
    try:
        val = data.dob_of_driver
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="DOB of Driver"]', formatted_date, "Driver DOB", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Driver DOB missing from source data.")
            else:
                log("   ⚠️ DOB of Driver missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"DOB field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling DOB of Driver: {e}")

    if stop_cb(): return False

    # 5. Driver Name
    try:
        val = data.driver_name
        if val:
            await fill_input_with_delay(page, 'input[name="Driver Name"]', val, "Driver Name", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Driver Name missing from source data.")
            else:
                log("   ⚠️ Driver Name missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Driver Name field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Driver Name: {e}")

    if stop_cb(): return False

    # 6. Age of Driver
    try:
        val = data.age_of_driver
        if val:
            await fill_input_with_delay(page, 'input[name="Age of Driver"]', val, "Driver Age", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Driver Age missing from source data.")
            else:
                log("   ⚠️ Age of Driver missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Age field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Age of Driver: {e}")

    if stop_cb(): return False

    # 7. Is the motor driving license valid for type of vehicle (ALWAYS YES)
    try:
        rb_loc = page.locator('input[name="Is the motor driving license valid for the type of vehicle on the date of accident?"][value="Y"]').first
        if await rb_loc.count() > 0:
            is_checked = await rb_loc.is_checked()
            if not is_checked:
                await page.evaluate("""
                    () => {
                        const rb = document.querySelector('input[name="Is the motor driving license valid for the type of vehicle on the date of accident?"][value="Y"]');
                        if (rb) {
                            rb.click();
                        }
                    }
                """)
                await asyncio.sleep(field_delay_ms / 1000.0)
                if isinstance(log, AutomationLogger):
                    log.success("License Validation set to YES")
                else:
                    log(f"   ✅ License Valid set to YES")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"License Validation toggle error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting License Valid: {e}")

    if stop_cb(): return False

    # 8. License Issuing Authority
    try:
        val = data.license_issuing_authority
        if val:
            await fill_input_with_delay(page, 'input[name="License Issuing Authority"]', val, "Issuing Authority", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Issuing Authority missing from source data.")
            else:
                log("   ⚠️ License Issuing Authority missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Issuing Authority field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling License Issuing Authority: {e}")

    if stop_cb(): return False

    # 9. Driver driving License Number
    try:
        val = data.driver_license_number
        if val:
            await fill_input_with_delay(page, 'input[name="Driver driving License Number"]', val, "License No", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("License Number missing from source data.")
            else:
                log("   ⚠️ License Number missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"License Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling License Number: {e}")

    if stop_cb(): return False

    # 10. Driver driving License Issue Date
    try:
        val = data.driver_license_issue_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="Driver driving License Issue Date"]', formatted_date, "Issue Date", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("License Issue Date missing from source data.")
            else:
                log("   ⚠️ License Issue Date missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Issue Date field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling License Issue Date: {e}")

    if stop_cb(): return False

    # 11. Driver driving License Expiry Date
    try:
        val = data.driver_license_expiry_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="Driver driving License Expiry Date"]', formatted_date, "Expiry Date", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("License Expiry Date missing from source data.")
            else:
                log("   ⚠️ License Expiry Date missing from Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Expiry Date field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling License Expiry Date: {e}")

    if stop_cb(): return False

    # 12. Badge Number (Optional)
    try:
        val = data.badge_number
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.badgeNo"]', val, "Badge No", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Badge Number missing; skipping (Optional).")
            else:
                log("   ⏭️ [Badge Number] — Optional, not in Excel. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Badge Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Badge Number: {e}")

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("Driver Details phase completed.")
    else:
        log(f" ✅ Driver Details completed successfully.")
    return True
