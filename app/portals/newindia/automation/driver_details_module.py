import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay, format_date_ddmmyyyy
)
from app.automation.automation_logger import _ts

async def fill_driver_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    log(f"[{_ts()}]  📝 Opening Driver Details section...")
    
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
            log(f"[{_ts()}]   ✅ Expanded Driver Details.")
        else:
            log(f"[{_ts()}]   ℹ️ Driver Details already expanded.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Could not expand Driver Details: {e}")

    if stop_cb(): return False

    # 1. Was Vehicle Parked During Accident (ALWAYS NO)
    try:
        log(f"[{_ts()}]  ✏️ Selecting Vehicle Parked During Accident = NO...")
        await select_dropdown_with_delay(
            page, 'select[name="Was the vehicle parked during accident ?"]',
            "No", "Vehicle Parked", log, field_delay_ms
        )

        # Wait for the Relationship dropdown to become VISIBLE (not just attached)
        # 'attached' means it exists in the DOM but may be hidden by ng-show/ng-if
        log(f"[{_ts()}]  ⏳ Waiting for Relationship dropdown to become visible...")
        try:
            await page.wait_for_selector(
                'select[name="Relationship of the driver with the Insured"]',
                state="visible", timeout=10000
            )
        except Exception:
            # Some portal versions use ng-model instead of name
            await page.wait_for_selector(
                'select[data-ng-model*="driverRelationship"], select[ng-model*="driverRelationship"]',
                state="visible", timeout=6000
            )
        await asyncio.sleep(0.8)  # Safety wait for Angular to finish rendering
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error selecting Vehicle Parked During Accident: {e}")

    if stop_cb(): return False

    # 2. Relationship with Insured (Dynamic from Excel)
    try:
        val = data.driver_relationship_with_insured

        # Debug: log available options so we can verify the match
        try:
            opts = await page.evaluate("""
                () => {
                    const s = document.querySelector('select[name="Relationship of the driver with the Insured"]');
                    if (!s) return ['SELECTOR_NOT_FOUND'];
                    return Array.from(s.options).map(o => o.text.trim());
                }
            """)
            log(f"[{_ts()}]   🔍 [Relationship] available options: {opts}")
        except Exception:
            pass

        if val:
            await select_dropdown_with_delay(
                page,
                'select[name="Relationship of the driver with the Insured"]',
                val, "Relationship", log, field_delay_ms
            )
        else:
            log(f"[{_ts()}]   ⚠️ Relationship with Insured missing from Excel, defaulting to 'Self'")
            await select_dropdown_with_delay(
                page,
                'select[name="Relationship of the driver with the Insured"]',
                "Self", "Relationship", log, field_delay_ms
            )
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error selecting Relationship With Insured: {e}")

    if stop_cb(): return False

    # 3. License Type of Driver
    try:
        val = data.license_type_of_driver
        if val:
            await select_dropdown_with_delay(page, 'select[name="License Type of Driver"]', val, "License Type", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ License Type of Driver missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error selecting License Type of Driver: {e}")

    if stop_cb(): return False

    # 4. DOB of Driver
    try:
        val = data.dob_of_driver
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="DOB of Driver"]', formatted_date, "Driver DOB", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ DOB of Driver missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling DOB of Driver: {e}")

    if stop_cb(): return False

    # 5. Driver Name
    try:
        val = data.driver_name
        if val:
            await fill_input_with_delay(page, 'input[name="Driver Name"]', val, "Driver Name", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ Driver Name missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling Driver Name: {e}")

    if stop_cb(): return False

    # 6. Age of Driver
    try:
        val = data.age_of_driver
        if val:
            await fill_input_with_delay(page, 'input[name="Age of Driver"]', val, "Driver Age", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ Age of Driver missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling Age of Driver: {e}")

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
                log(f"[{_ts()}]   ✅ License Valid set to YES")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error selecting License Valid: {e}")

    if stop_cb(): return False

    # 8. License Issuing Authority
    try:
        val = data.license_issuing_authority
        if val:
            await fill_input_with_delay(page, 'input[name="License Issuing Authority"]', val, "Issuing Authority", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ License Issuing Authority missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling License Issuing Authority: {e}")

    if stop_cb(): return False

    # 9. Driver driving License Number
    try:
        val = data.driver_license_number
        if val:
            await fill_input_with_delay(page, 'input[name="Driver driving License Number"]', val, "License No", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ License Number missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling License Number: {e}")

    if stop_cb(): return False

    # 10. Driver driving License Issue Date
    try:
        val = data.driver_license_issue_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="Driver driving License Issue Date"]', formatted_date, "Issue Date", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ License Issue Date missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling License Issue Date: {e}")

    if stop_cb(): return False

    # 11. Driver driving License Expiry Date
    try:
        val = data.driver_license_expiry_date
        if val:
            formatted_date = format_date_ddmmyyyy(val)
            await fill_input_with_delay(page, 'input[name="Driver driving License Expiry Date"]', formatted_date, "Expiry Date", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⚠️ License Expiry Date missing from Excel.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling License Expiry Date: {e}")

    if stop_cb(): return False

    # 12. Badge Number (Optional)
    try:
        val = data.badge_number
        if val:
            await fill_input_with_delay(page, 'input[data-ng-model="surveyorData.worklist.additionalDetails.badgeNo"]', val, "Badge No", log, field_delay_ms)
        else:
            log(f"[{_ts()}]   ⏭️ [Badge Number] — Optional, not in Excel. Skipping.")
    except Exception as e:
        log(f"[{_ts()}]   ⚠️ Error filling Badge Number: {e}")

    log(f"[{_ts()}]  ✅ Driver Details completed successfully.")
    return True
