import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay,
    upload_file_via_input,
)
from app.automation.automation_logger import AutomationLogger

async def fill_claim_assessment_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.info("Starting Claim Assessment Details phase...")
        log.indent()
    else:
        log(f"Opening Claim Assessment Details section...")

    # 0. Handle Alert Popup (if any)
    try:
        # Wait briefly for the modal
        modal_sel = 'div.modal-content.alrt-ncr-brdr'
        try:
            modal = page.locator(modal_sel).first
            await modal.wait_for(state="visible", timeout=3000)
            
            ok_btn = modal.locator('button:has-text("OK")').first
            if await ok_btn.is_visible():
                if isinstance(log, AutomationLogger):
                    log.info("Handling alert popup...")
                else:
                    log(f"   ℹ️ Handling alert popup before Claim Assessment...")
                await ok_btn.click()
                await asyncio.sleep(1.0)
                if isinstance(log, AutomationLogger):
                    log.success("Alert popup dismissed.")
                else:
                    log(f"   ✅ Alert popup dismissed.")
        except Exception:
            pass # No modal appeared, completely fine
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Popup dismissal error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error handling Claim Assessment popup: {e}")

    if stop_cb(): return False

    # Wait for the main panel to be visible to ensure page loaded
    try:
        await page.wait_for_selector('select[data-ng-model*="isPaymentInvoice"]', state="visible", timeout=10000)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.warning(f"Form load timeout: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Claim Assessment form not found or timed out: {e}")

    if stop_cb(): return False

    # 1. Whether Payment invoice is in the name of NIA (Yes/No)
    # Behavior: ALWAYS select YES
    try:
        sel = 'select[data-ng-model*="isPaymentInvoice"]'
        await select_dropdown_with_delay(page, sel, "Yes", "Payment Invoice NIA", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Payment Invoice dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Payment Invoice in NIA Name: {e}")

    if stop_cb(): return False

    # 2. Is GST Applicable
    # Behavior: READONLY, safely skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Is GST Applicable' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Is GST Applicable' (Readonly field).")

    if stop_cb(): return False

    # 3. Vendor/Tax Invoice Date
    try:
        val = getattr(data, 'vendor_invoice_date', '')
        if val:
            sel = 'input[data-ng-model*="vendorTaxInvoiceDate"]'
            await fill_input_with_delay(page, sel, val, "Invoice Date", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Vendor Invoice Date missing from data.")
            else:
                log(f"   ⚠️ Vendor/Tax Invoice Date missing (Not extracted from PDF).")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Invoice Date field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Vendor/Tax Invoice Date: {e}")

    if stop_cb(): return False

    # 4. Vendor/Tax Invoice Number
    try:
        val = getattr(data, 'vendor_invoice_number', '')
        if val:
            sel = 'input[data-ng-model*="vendorTaxInvoiceNumber"]'
            await fill_input_with_delay(page, sel, val, "Invoice Number", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Vendor Invoice Number missing from data.")
            else:
                log(f"   ⚠️ Vendor/Tax Invoice Number missing (Not extracted from PDF).")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Invoice Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Vendor/Tax Invoice Number: {e}")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — PRIMARY ASSESSMENT
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section 1: Primary Assessment")
        log.indent()
    else:
        log("")
        log(f"   ── Section 1: Primary Assessment ──")

    # Field 1: Primary Assessment dropdown → ALWAYS "Yes"
    try:
        sel = 'select[name="Is there any primary estimate"]'
        await select_dropdown_with_delay(page, sel, "Yes", "Primary Assessment", log, field_delay_ms)
        await asyncio.sleep(1.5)  # Wait for conditional sections to appear
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Primary Assessment dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Primary Assessment: {e}")

    if stop_cb(): return False

    # Field 2: Attach Assessment Excel (file only — user clicks Upload/Validate manually)
    assessment_path = data.assessment_files.get("assessment_excel", "")
    if assessment_path:
        await upload_file_via_input(
            page,
            file_input_selector='input#chooseFilePrim',
            file_path=assessment_path,
            label="Assessment Excel",
            log=log,
        )
        if isinstance(log, AutomationLogger):
            log.info("[Primary Assessment] File attached. User must Upload → Validate.")
        else:
            log(f"   ℹ️ [Primary Assessment] File attached. Click Upload → Validate manually.")
    else:
        if isinstance(log, AutomationLogger):
            log.warning("No Primary Assessment Excel found.")
        else:
            log(f"   ⚠️ No assessment Excel file found in folder (expected: assessment.xlsx / primary_assessment.xlsx).")

    if stop_cb(): return False

    # Field 3: Garage Bill dropdown → ALWAYS "Garage Bill"
    try:
        sel = 'select#pDocTypeOCR'
        await select_dropdown_with_delay(page, sel, "Garage Bill", "Bill Type Dropdown", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Bill Type dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Garage Bill: {e}")

    if stop_cb(): return False

    # Field 4: Attach Garage Bill (Invoice — file only, user clicks Populate Data manually)
    invoice_path = data.assessment_files.get("invoice", "")
    if invoice_path:
        await upload_file_via_input(
            page,
            file_input_selector='input#priOcr',
            file_path=invoice_path,
            label="Garage Bill PDF",
            log=log,
        )
        if isinstance(log, AutomationLogger):
            log.info("[Garage Bill] File attached. User must Populate Data.")
        else:
            log(f"   ℹ️ [Garage Bill] File attached. Click Populate Data manually.")
    else:
        if isinstance(log, AutomationLogger):
            log.warning("No Garage Bill PDF found.")
        else:
            log(f"   ⚠️ No invoice file found in folder (expected: invoice.pdf / final_invoice.pdf).")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 2: Supplementary Assessment")
        log.indent()
    else:
        log("")
        log(f"   ── Section 2: Supplementary Assessment ──")

    has_estimate = bool(data.assessment_files.get("estimate_excel", ""))
    supp_value = "Yes" if has_estimate else "No"

    # Also check ClaimData for user override
    is_supp = getattr(data, 'is_supplementary_estimate', '')
    if is_supp and is_supp.strip().lower() in ('yes', 'y'):
        supp_value = "Yes"
    elif is_supp and is_supp.strip().lower() in ('no', 'n'):
        supp_value = "No"

    try:
        sel = 'select[name*="Is there any supplementary estimate"]'
        await select_dropdown_with_delay(page, sel, supp_value, "Supplementary Estimate", log, field_delay_ms)
        await asyncio.sleep(1.5)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Supplementary dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Supplementary Estimate: {e}")

    if stop_cb(): return False

    if supp_value == "Yes":
        # Attach Supplementary Estimate Excel (file only — user clicks Upload/Validate manually)
        estimate_path = data.assessment_files.get("estimate_excel", "")
        if estimate_path:
            await upload_file_via_input(
                page,
                file_input_selector='input#chooseFileSup',
                file_path=estimate_path,
                label="Supp Estimate Excel",
                log=log,
            )
            if isinstance(log, AutomationLogger):
                log.info("[Supp Excel] Attached. User must Upload → Validate.")
            else:
                log(f"   ℹ️ [Supplementary Excel] File attached. Click Upload → Validate manually.")
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Estimate Excel missing for supplementary phase.")
            else:
                log(f"   ⚠️ Supplementary Estimate set to Yes but no estimate Excel found.")

        if stop_cb(): return False

        # Attach Supplementary Garage Bill (file only — user clicks Populate Data manually)
        estimate_inv_path = data.assessment_files.get("estimate_invoice", "")
        if estimate_inv_path:
            # Select Garage Bill in supplementary OCR dropdown
            sel = 'select#sDocTypeOCR'
            await select_dropdown_with_delay(page, sel, "Garage Bill", "Supp Bill Type", log, field_delay_ms)

            await upload_file_via_input(
                page,
                file_input_selector='input#supOcr',
                file_path=estimate_inv_path,
                label="Supp Garage Bill",
                log=log,
            )
            if isinstance(log, AutomationLogger):
                log.info("[Supp Bill] Attached. User must Populate Data.")
            else:
                log(f"   ℹ️ [Supp Garage Bill] File attached. Click Populate Data manually.")
        else:
            if isinstance(log, AutomationLogger):
                log.info("No supplementary invoice found; skipping (Optional).")
            else:
                log(f"   ℹ️ No estimate invoice file found (optional). Skipping.")
    else:
        if isinstance(log, AutomationLogger):
            log.info("Supplementary estimate skipped.")
        else:
            log(f"   ℹ️ Supplementary Estimate = No. Section complete.")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 3: Painting Charges")
        log.indent()
    else:
        log("")
        log(f"   ── Section 3: Painting Charges ──")

    # Labour Charges — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Labour Charges' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Labour Charges' (Readonly field).")

    # Paint Material Charges — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Paint Material Charges' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Paint Material Charges' (Readonly field).")

    # Painting Work Details — Dropdown from ClaimData
    try:
        raw_val = getattr(data, 'painting_work_details', '')
        if raw_val:
            # Normalize: map Excel values to dropdown values
            normalized = raw_val.strip().lower()
            if "break" in normalized or "labor" in normalized or "labour" in normalized:
                dropdown_val = "Break-up"
            elif "consol" in normalized:
                dropdown_val = "Consolidated"
            else:
                dropdown_val = raw_val.strip()

            sel = 'select[name*="Painting work details"]'
            await select_dropdown_with_delay(page, sel, dropdown_val, "Painting Work Details", log, field_delay_ms)
            await asyncio.sleep(1.0)  # Wait for painting table to update
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Painting details missing from data.")
            else:
                log(f"   ⚠️ Painting Work Details not found in ClaimData. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Painting details dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Painting Work Details: {e}")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 4: Delivery Order Details")
        log.indent()
    else:
        log("")
        log(f"   ── Section 4: Delivery Order Details ──")

    # Net Salvage — Optional
    try:
        val = getattr(data, 'net_salvage', '0')
        if val and val.strip() and val.strip() != "0":
            sel = 'input#netSlavage'
            await fill_input_with_delay(page, sel, val.strip(), "Net Salvage", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Net Salvage is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Net Salvage = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Net Salvage field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Net Salvage: {e}")

    if stop_cb(): return False

    # Net Salvage to map with Invoice — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Net Salvage Map' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Net Salvage to map with Invoice' (Readonly field).")

    # Less Compulsory Excess — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Compulsory Excess' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Less Compulsory Excess' (Readonly field).")

    # Less Voluntary Excess — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Voluntary Excess' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Less Voluntary Excess' (Readonly field).")

    # Less Any Other Deductions — Optional
    try:
        val = getattr(data, 'less_other_deductions', '0')
        if val and val.strip() and val.strip() != "0":
            sel = 'input#lessOtherDeductions'
            await fill_input_with_delay(page, sel, val.strip(), "Other Deductions", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Other Deductions is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Less Any Other Deductions = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Other Deductions field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Less Any Other Deductions: {e}")

    if stop_cb(): return False

    # Less Imposed Excess — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Imposed Excess' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Less Imposed Excess' (Readonly field).")

    # Towing Charges — Optional
    try:
        val = getattr(data, 'towing_additional_charges', '0')
        towing_val = val if val and val.strip() and val.strip() != "0" else "0"
        if towing_val != "0":
            sel = 'input#towingCharges'
            await fill_input_with_delay(page, sel, towing_val.strip(), "Towing Charges", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Towing Charges is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Towing Charges = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Towing field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Towing Charges: {e}")

    if stop_cb(): return False

    # Additional Towing Charges — Optional (separate field)
    try:
        val = getattr(data, 'additional_towing_charges', '0')
        if val and val.strip() and val.strip() != "0":
            sel = 'input#additionalTowingCharges'
            await fill_input_with_delay(page, sel, val.strip(), "Addl Towing", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Additional Towing is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Additional Towing Charges = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Addl Towing field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Additional Towing Charges: {e}")

    if stop_cb(): return False

    # Whether Re-Inspection Required — ALWAYS "No"
    try:
        sel = 'select#whetherReinspectionRequired'
        await select_dropdown_with_delay(page, sel, "No", "Re-Inspection", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Re-Inspection dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Whether Re-Inspection Required: {e}")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 5: Add-On Cover Wise Assessment")
        log.indent()
    else:
        log("")
        log(f"   ── Section 5: Add-On Cover Wise Assessment ──")

    # These are all optional — fill only if values exist and are non-zero
    addon_fields = [
        ("nil_depreciation_amount",  "input#nilDepreciationCover",  "Nil Dep Amount"),
        ("engine_protect_amount",    "input#engineProtectCover",    "Engine Protect Amount"),
        ("consumable_items_amount",  "input#consumableItemsCover",  "Consumable Items Amount"),
        ("key_protect_amount",       "input#keyProtectCover",       "Key Protect Amount"),
    ]

    for attr_name, selector, label in addon_fields:
        if stop_cb(): return False
        try:
            val = getattr(data, attr_name, '0')
            if val and val.strip() and val.strip() != "0":
                try:
                    el = page.locator(selector).first
                    is_visible = await el.is_visible()
                    if is_visible:
                        await fill_input_with_delay(page, selector, val.strip(), label, log, field_delay_ms)
                    else:
                        if isinstance(log, AutomationLogger):
                            log.info(f"Field {label} not visible; skipping.")
                        else:
                            log(f"   ℹ️ [{label}] field not visible on page (add-on not applicable). Skipping.")
                except Exception:
                    if isinstance(log, AutomationLogger):
                        log.info(f"Field {label} not found; skipping.")
                    else:
                        log(f"   ℹ️ [{label}] field not found on page. Skipping.")
            else:
                if isinstance(log, AutomationLogger):
                    log.info(f"{label} is 0 or empty; skipping.")
                else:
                    log(f"   ℹ️ [{label}] = 0 or empty. Skipping.")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Add-on {label} field error: {str(e)[:100]}")
            else:
                log(f"   ⚠️ Error filling {label}: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP: Click "Next" button to proceed to next page
    # ═══════════════════════════════════════════════════════════════════════════
    if stop_cb(): return False
    
    if isinstance(log, AutomationLogger):
        log.wait("Proceeding to final submission page...")
    else:
        log(f" ── Clicking Next button ──")
    try:
        next_btn = page.locator('button.success-blue:has-text("Next")').first
        await next_btn.wait_for(state="visible", timeout=5000)
        await next_btn.click()
        if isinstance(log, AutomationLogger):
            log.success("Navigation to final page successful.")
        else:
            log(f"   ✅ Clicked 'Next' button — proceeding to next page.")
        await page.wait_for_timeout(2000)  # Allow page transition
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Navigation error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Could not click Next button: {e}")

    if isinstance(log, AutomationLogger):
        log.outdent() # outdent Section 5
        log.outdent() # outdent main module
        log.success("Claim Assessment Details phase completed.")
    else:
        log("")
        log(f" ✅ Phase 10 (Claim Assessment Details — All 5 Sections) completed successfully.")
    return True
