import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay,
)

async def fill_claim_assessment_details(page: Page, data: ClaimData, log_cb, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    log_cb("Opening Claim Assessment Details section...")

    # 0. Handle Alert Popup (if any)
    try:
        # Wait briefly for the modal
        modal_sel = 'div.modal-content.alrt-ncr-brdr'
        try:
            modal = page.locator(modal_sel).first
            await modal.wait_for(state="visible", timeout=3000)
            
            ok_btn = modal.locator('button:has-text("OK")').first
            if await ok_btn.is_visible():
                log_cb("  ℹ️ Handling alert popup before Claim Assessment...")
                await ok_btn.click()
                await asyncio.sleep(1.0)
                log_cb("  ✅ Alert popup dismissed.")
        except Exception:
            pass # No modal appeared, completely fine
    except Exception as e:
        log_cb(f"  ⚠️ Error handling Claim Assessment popup: {e}")

    if stop_cb(): return False

    # Wait for the main panel to be visible to ensure page loaded
    try:
        await page.wait_for_selector('select[data-ng-model*="isPaymentInvoice"]', state="visible", timeout=10000)
    except Exception as e:
        log_cb(f"  ⚠️ Claim Assessment form not found or timed out: {e}")
        # Proceed anyway just in case

    if stop_cb(): return False

    # 1. Whether Payment invoice is in the name of NIA (Yes/No)
    # Behavior: ALWAYS select YES
    try:
        sel = 'select[data-ng-model*="isPaymentInvoice"]'
        await select_dropdown_with_delay(page, sel, "Yes", "Payment Invoice in NIA Name", log_cb, field_delay_ms)
    except Exception as e:
        log_cb(f"  ⚠️ Error selecting Payment Invoice in NIA Name: {e}")

    if stop_cb(): return False

    # 2. Is GST Applicable
    # Behavior: READONLY, safely skip
    log_cb("  ℹ️ Skipping 'Is GST Applicable' (Readonly field).")

    if stop_cb(): return False

    # 3. Vendor/Tax Invoice Date
    try:
        val = getattr(data, 'vendor_invoice_date', '')
        if val:
            sel = 'input[data-ng-model*="vendorTaxInvoiceDate"]'
            await fill_input_with_delay(page, sel, val, "Vendor/Tax Invoice Date", log_cb, field_delay_ms)
        else:
            log_cb("  ⚠️ Vendor/Tax Invoice Date missing (Not extracted from PDF).")
    except Exception as e:
        log_cb(f"  ⚠️ Error filling Vendor/Tax Invoice Date: {e}")

    if stop_cb(): return False

    # 4. Vendor/Tax Invoice Number
    try:
        val = getattr(data, 'vendor_invoice_number', '')
        if val:
            sel = 'input[data-ng-model*="vendorTaxInvoiceNumber"]'
            await fill_input_with_delay(page, sel, val, "Vendor/Tax Invoice Number", log_cb, field_delay_ms)
        else:
            log_cb("  ⚠️ Vendor/Tax Invoice Number missing (Not extracted from PDF).")
    except Exception as e:
        log_cb(f"  ⚠️ Error filling Vendor/Tax Invoice Number: {e}")

    log_cb("Phase 10 (Claim Assessment Details) partial fill completed successfully.")
    return True
