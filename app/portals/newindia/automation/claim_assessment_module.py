import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay,
    upload_file_via_input,
)
from app.automation.automation_logger import _ts

async def fill_claim_assessment_details(page: Page, data: ClaimData, log_cb, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    log_cb(f"[{_ts()}] Opening Claim Assessment Details section...")

    # 0. Handle Alert Popup (if any)
    try:
        # Wait briefly for the modal
        modal_sel = 'div.modal-content.alrt-ncr-brdr'
        try:
            modal = page.locator(modal_sel).first
            await modal.wait_for(state="visible", timeout=3000)
            
            ok_btn = modal.locator('button:has-text("OK")').first
            if await ok_btn.is_visible():
                log_cb(f"[{_ts()}]   ℹ️ Handling alert popup before Claim Assessment...")
                await ok_btn.click()
                await asyncio.sleep(1.0)
                log_cb(f"[{_ts()}]   ✅ Alert popup dismissed.")
        except Exception:
            pass # No modal appeared, completely fine
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error handling Claim Assessment popup: {e}")

    if stop_cb(): return False

    # Wait for the main panel to be visible to ensure page loaded
    try:
        await page.wait_for_selector('select[data-ng-model*="isPaymentInvoice"]', state="visible", timeout=10000)
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Claim Assessment form not found or timed out: {e}")
        # Proceed anyway just in case

    if stop_cb(): return False

    # 1. Whether Payment invoice is in the name of NIA (Yes/No)
    # Behavior: ALWAYS select YES
    try:
        sel = 'select[data-ng-model*="isPaymentInvoice"]'
        await select_dropdown_with_delay(page, sel, "Yes", "Payment Invoice in NIA Name", log_cb, field_delay_ms)
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error selecting Payment Invoice in NIA Name: {e}")

    if stop_cb(): return False

    # 2. Is GST Applicable
    # Behavior: READONLY, safely skip
    log_cb(f"[{_ts()}]   ℹ️ Skipping 'Is GST Applicable' (Readonly field).")

    if stop_cb(): return False

    # 3. Vendor/Tax Invoice Date
    try:
        val = getattr(data, 'vendor_invoice_date', '')
        if val:
            sel = 'input[data-ng-model*="vendorTaxInvoiceDate"]'
            await fill_input_with_delay(page, sel, val, "Vendor/Tax Invoice Date", log_cb, field_delay_ms)
        else:
            log_cb(f"[{_ts()}]   ⚠️ Vendor/Tax Invoice Date missing (Not extracted from PDF).")
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error filling Vendor/Tax Invoice Date: {e}")

    if stop_cb(): return False

    # 4. Vendor/Tax Invoice Number
    try:
        val = getattr(data, 'vendor_invoice_number', '')
        if val:
            sel = 'input[data-ng-model*="vendorTaxInvoiceNumber"]'
            await fill_input_with_delay(page, sel, val, "Vendor/Tax Invoice Number", log_cb, field_delay_ms)
        else:
            log_cb(f"[{_ts()}]   ⚠️ Vendor/Tax Invoice Number missing (Not extracted from PDF).")
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error filling Vendor/Tax Invoice Number: {e}")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — PRIMARY ASSESSMENT
    # ══════════════════════════════════════════════════════════════════════════
    log_cb("")
    log_cb(f"[{_ts()}]   ── Section 1: Primary Assessment ──")

    # Field 1: Primary Assessment dropdown → ALWAYS "Yes"
    try:
        sel = 'select[name="Is there any primary estimate"]'
        await select_dropdown_with_delay(page, sel, "Yes", "Primary Assessment", log_cb, field_delay_ms)
        await asyncio.sleep(1.5)  # Wait for conditional sections to appear
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error selecting Primary Assessment: {e}")

    if stop_cb(): return False

    # Field 2: Attach Assessment Excel (file only — user clicks Upload/Validate manually)
    assessment_path = data.assessment_files.get("assessment_excel", "")
    if assessment_path:
        await upload_file_via_input(
            page,
            file_input_selector='input#chooseFilePrim',
            file_path=assessment_path,
            label="Primary Assessment Excel",
            log=log_cb,
        )
        log_cb(f"[{_ts()}]   ℹ️ [Primary Assessment] File attached. Click Upload → Validate manually.")
    else:
        log_cb(f"[{_ts()}]   ⚠️ No assessment Excel file found in folder (expected: assessment.xlsx / primary_assessment.xlsx).")

    if stop_cb(): return False

    # Field 3: Garage Bill dropdown → ALWAYS "Garage Bill"
    try:
        sel = 'select#pDocTypeOCR'
        await select_dropdown_with_delay(page, sel, "Garage Bill", "Garage Bill Dropdown", log_cb, field_delay_ms)
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error selecting Garage Bill: {e}")

    if stop_cb(): return False

    # Field 4: Attach Garage Bill (Invoice — file only, user clicks Populate Data manually)
    invoice_path = data.assessment_files.get("invoice", "")
    if invoice_path:
        await upload_file_via_input(
            page,
            file_input_selector='input#priOcr',
            file_path=invoice_path,
            label="Garage Bill (Invoice)",
            log=log_cb,
        )
        log_cb(f"[{_ts()}]   ℹ️ [Garage Bill] File attached. Click Populate Data manually.")
    else:
        log_cb(f"[{_ts()}]   ⚠️ No invoice file found in folder (expected: invoice.pdf / final_invoice.pdf).")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — SUPPLEMENTARY ASSESSMENT
    # ══════════════════════════════════════════════════════════════════════════
    log_cb("")
    log_cb(f"[{_ts()}]   ── Section 2: Supplementary Assessment ──")

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
        await select_dropdown_with_delay(page, sel, supp_value, "Supplementary Estimate", log_cb, field_delay_ms)
        await asyncio.sleep(1.5)
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error selecting Supplementary Estimate: {e}")

    if stop_cb(): return False

    if supp_value == "Yes":
        # Attach Supplementary Estimate Excel (file only — user clicks Upload/Validate manually)
        estimate_path = data.assessment_files.get("estimate_excel", "")
        if estimate_path:
            await upload_file_via_input(
                page,
                file_input_selector='input#chooseFileSup',
                file_path=estimate_path,
                label="Supplementary Estimate Excel",
                log=log_cb,
            )
            log_cb(f"[{_ts()}]   ℹ️ [Supplementary Excel] File attached. Click Upload → Validate manually.")
        else:
            log_cb(f"[{_ts()}]   ⚠️ Supplementary Estimate set to Yes but no estimate Excel found.")

        if stop_cb(): return False

        # Attach Supplementary Garage Bill (file only — user clicks Populate Data manually)
        estimate_inv_path = data.assessment_files.get("estimate_invoice", "")
        if estimate_inv_path:
            # Select Garage Bill in supplementary OCR dropdown
            sel = 'select#sDocTypeOCR'
            await select_dropdown_with_delay(page, sel, "Garage Bill", "Supp Garage Bill Dropdown", log_cb, field_delay_ms)

            await upload_file_via_input(
                page,
                file_input_selector='input#supOcr',
                file_path=estimate_inv_path,
                label="Supplementary Garage Bill",
                log=log_cb,
            )
            log_cb(f"[{_ts()}]   ℹ️ [Supp Garage Bill] File attached. Click Populate Data manually.")
        else:
            log_cb(f"[{_ts()}]   ℹ️ No estimate invoice file found (optional). Skipping.")
    else:
        log_cb(f"[{_ts()}]   ℹ️ Supplementary Estimate = No. Section complete.")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — PAINTING CHARGES
    # ══════════════════════════════════════════════════════════════════════════
    log_cb("")
    log_cb(f"[{_ts()}]   ── Section 3: Painting Charges ──")

    # Labour Charges — READONLY, skip
    log_cb(f"[{_ts()}]   ℹ️ Skipping 'Labour Charges' (Readonly field).")

    # Paint Material Charges — READONLY, skip
    log_cb(f"[{_ts()}]   ℹ️ Skipping 'Paint Material Charges' (Readonly field).")

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
            await select_dropdown_with_delay(page, sel, dropdown_val, "Painting Work Details", log_cb, field_delay_ms)
            await asyncio.sleep(1.0)  # Wait for painting table to update
        else:
            log_cb(f"[{_ts()}]   ⚠️ Painting Work Details not found in ClaimData. Skipping.")
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error selecting Painting Work Details: {e}")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — DELIVERY ORDER DETAILS
    # ══════════════════════════════════════════════════════════════════════════
    log_cb("")
    log_cb(f"[{_ts()}]   ── Section 4: Delivery Order Details ──")

    # Net Salvage — Optional
    try:
        val = getattr(data, 'net_salvage', '0')
        if val and val.strip() and val.strip() != "0":
            sel = 'input#netSlavage'
            await fill_input_with_delay(page, sel, val.strip(), "Net Salvage", log_cb, field_delay_ms)
        else:
            log_cb(f"[{_ts()}]   ℹ️ Net Salvage = 0 or empty. Skipping.")
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error filling Net Salvage: {e}")

    if stop_cb(): return False

    # Net Salvage to map with Invoice — READONLY, skip
    log_cb(f"[{_ts()}]   ℹ️ Skipping 'Net Salvage to map with Invoice' (Readonly field).")

    # Less Compulsory Excess — READONLY, skip
    log_cb(f"[{_ts()}]   ℹ️ Skipping 'Less Compulsory Excess' (Readonly field).")

    # Less Voluntary Excess — READONLY, skip
    log_cb(f"[{_ts()}]   ℹ️ Skipping 'Less Voluntary Excess' (Readonly field).")

    # Less Any Other Deductions — Optional
    try:
        val = getattr(data, 'less_other_deductions', '0')
        if val and val.strip() and val.strip() != "0":
            sel = 'input#lessOtherDeductions'
            await fill_input_with_delay(page, sel, val.strip(), "Less Any Other Deductions", log_cb, field_delay_ms)
        else:
            log_cb(f"[{_ts()}]   ℹ️ Less Any Other Deductions = 0 or empty. Skipping.")
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error filling Less Any Other Deductions: {e}")

    if stop_cb(): return False

    # Less Imposed Excess — READONLY, skip
    log_cb(f"[{_ts()}]   ℹ️ Skipping 'Less Imposed Excess' (Readonly field).")

    # Towing Charges — Optional
    try:
        val = getattr(data, 'towing_additional_charges', '0')
        # towing_additional_charges may contain combined value; check for separate towing field
        towing_val = val if val and val.strip() and val.strip() != "0" else "0"
        if towing_val != "0":
            sel = 'input#towingCharges'
            await fill_input_with_delay(page, sel, towing_val.strip(), "Towing Charges", log_cb, field_delay_ms)
        else:
            log_cb(f"[{_ts()}]   ℹ️ Towing Charges = 0 or empty. Skipping.")
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error filling Towing Charges: {e}")

    if stop_cb(): return False

    # Additional Towing Charges — Optional (separate field)
    try:
        val = getattr(data, 'additional_towing_charges', '0')
        if val and val.strip() and val.strip() != "0":
            sel = 'input#additionalTowingCharges'
            await fill_input_with_delay(page, sel, val.strip(), "Additional Towing Charges", log_cb, field_delay_ms)
        else:
            log_cb(f"[{_ts()}]   ℹ️ Additional Towing Charges = 0 or empty. Skipping.")
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error filling Additional Towing Charges: {e}")

    if stop_cb(): return False

    # Whether Re-Inspection Required — ALWAYS "No"
    try:
        sel = 'select#whetherReinspectionRequired'
        await select_dropdown_with_delay(page, sel, "No", "Whether Re-Inspection Required", log_cb, field_delay_ms)
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Error selecting Whether Re-Inspection Required: {e}")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 5 — ADD-ON COVER WISE ASSESSMENT
    # ══════════════════════════════════════════════════════════════════════════
    log_cb("")
    log_cb(f"[{_ts()}]   ── Section 5: Add-On Cover Wise Assessment ──")

    # These are all optional — fill only if values exist and are non-zero
    addon_fields = [
        ("nil_depreciation_amount",  "input#nilDepreciationCover",  "Nil Depreciation Cover Amount"),
        ("engine_protect_amount",    "input#engineProtectCover",    "Engine Protect Extension Amount"),
        ("consumable_items_amount",  "input#consumableItemsCover",  "Consumable Items Amount"),
        ("key_protect_amount",       "input#keyProtectCover",       "Key Protect Amount"),
    ]

    for attr_name, selector, label in addon_fields:
        if stop_cb(): return False
        try:
            val = getattr(data, attr_name, '0')
            if val and val.strip() and val.strip() != "0":
                # Check if the field is visible on the page (conditional rendering)
                try:
                    el = page.locator(selector).first
                    is_visible = await el.is_visible()
                    if is_visible:
                        await fill_input_with_delay(page, selector, val.strip(), label, log_cb, field_delay_ms)
                    else:
                        log_cb(f"[{_ts()}]   ℹ️ [{label}] field not visible on page (add-on not applicable). Skipping.")
                except Exception:
                    log_cb(f"[{_ts()}]   ℹ️ [{label}] field not found on page. Skipping.")
            else:
                log_cb(f"[{_ts()}]   ℹ️ [{label}] = 0 or empty. Skipping.")
        except Exception as e:
            log_cb(f"[{_ts()}]   ⚠️ Error filling {label}: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP: Click "Next" button to proceed to next page
    # ═══════════════════════════════════════════════════════════════════════════
    if stop_cb(): return False
    log_cb("")
    log_cb(f"[{_ts()}] ── Clicking Next button ──")
    try:
        next_btn = page.locator('button.success-blue:has-text("Next")').first
        await next_btn.wait_for(state="visible", timeout=5000)
        await next_btn.click()
        log_cb(f"[{_ts()}]   ✅ Clicked 'Next' button — proceeding to next page.")
        await page.wait_for_timeout(2000)  # Allow page transition
    except Exception as e:
        log_cb(f"[{_ts()}]   ⚠️ Could not click Next button: {e}")

    log_cb("")
    log_cb(f"[{_ts()}] ✅ Phase 10 (Claim Assessment Details — All 5 Sections) completed successfully.")
    return True
