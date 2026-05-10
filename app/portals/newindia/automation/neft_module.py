import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay
)
from app.portals.newindia.automation.ocr_helper import ChequeExtractor

def _find_cheque_document(data: ClaimData) -> str:
    """Scans uploaded documents to find the cheque image/PDF."""
    for doc_name, file_path in data.claim_doc_files.items():
        if "cheque" in doc_name.lower() or "check" in doc_name.lower():
            return file_path
    return ""

async def fill_neft_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    log("Opening NEFT Details section...")
    
    try:
        acc_heading = page.locator('a.accordion-toggle:has-text("NEFT Details")').first
        await acc_heading.wait_for(state="visible", timeout=10000)
        
        parent_div = page.locator('div.panel-heading').filter(has=acc_heading).first
        is_collapsed = 'collapsed' in await parent_div.get_attribute('class')
        if is_collapsed:
            await acc_heading.click()
            await asyncio.sleep(1.5)
            log("  ✅ Expanded NEFT Details.")
        else:
            log("  ℹ️ NEFT Details already expanded.")
    except Exception as e:
        log(f"  ⚠️ Could not expand NEFT Details: {e}")

    if stop_cb(): return False

    log("Scanning uploaded documents for cheque...")
    cheque_path = _find_cheque_document(data)
    
    if cheque_path:
        log("  ✅ Cheque document detected.")
        
        # OCR Extraction
        log("  ℹ️ Extracting details from cheque...")
        extractor = ChequeExtractor(cheque_path)
        cheque_details = extractor.extract_details()
        
        ifsc = cheque_details.get("ifsc") or data.ifsc_code
        acc_no = cheque_details.get("account_number") or data.account_number
        acc_type = cheque_details.get("account_type") or data.account_type
        
        if not cheque_details.get("ifsc"):
            log("  ⚠️ IFSC not found in cheque. Falling back to Excel.")
        if not cheque_details.get("account_number"):
            log("  ⚠️ Account Number not found in cheque. Falling back to Excel.")
            
    else:
        log("  ⚠️ Cheque document NOT detected.")
        ifsc = data.ifsc_code
        acc_no = data.account_number
        acc_type = data.account_type

    # Single Source of Truth: Read payment type established during extraction
    payment_to_value = data.bank_payment_to or "Dealer"
    log(f"  ℹ️ Using pre-calculated Payment Type: '{payment_to_value}'")

    # 1. Provide bank details for payment to
    try:
        await select_dropdown_with_delay(
            page, 
            'select[data-ng-model="surveyorData.worklist.additionalDetails.paymentTo"]',
            payment_to_value, 
            "Payment To", 
            log, 
            field_delay_ms
        )
    except Exception as e:
        log(f"  ⚠️ Error selecting Payment To: {e}")

    if stop_cb(): return False

    # 2. If Dealer, fill Dealer Name
    if payment_to_value == "Dealer":
        try:
            val = getattr(data, 'dealer_name', getattr(data, 'registered_owner_name', ''))
            if val:
                await fill_input_with_delay(page, 'input[name="Dealer Name"]', val, "Dealer Name", log, field_delay_ms)
        except Exception as e:
            log(f"  ⚠️ Error filling Dealer Name: {e}")

    if stop_cb(): return False

    # 3. IFSC Code
    try:
        if ifsc:
            await fill_input_with_delay(page, 'input[name="IFSC Code"]', ifsc, "IFSC Code", log, field_delay_ms)
            # Click the 'Find' button to trigger bank details fetch using its specific ng-click action
            find_btn = page.locator('button[data-ng-click="surveyorWorklistSurvey.getIFSCDetails_nt()"]')
            if await find_btn.count() > 0:
                await find_btn.click()
                await asyncio.sleep(1.5)  # Wait for AJAX to populate readonly fields
                log("  ✅ Clicked 'Find' to fetch bank details.")
        else:
            log("  ⚠️ IFSC Code missing from both Cheque and Excel.")
    except Exception as e:
        log(f"  ⚠️ Error filling IFSC Code: {e}")

    if stop_cb(): return False

    # 4. Readonly fields: Bank Name, Bank Branch Name, Bank Addess
    # We skip filling these as they are populated by the Find button.
    log("  ℹ️ Skipping readonly fields (Bank Name, Branch Name, Bank Address).")

    # 5. Account Number
    try:
        if acc_no:
            await fill_input_with_delay(page, 'input[name="Account Number"]', acc_no, "Account Number", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error filling Account Number: {e}")

    if stop_cb(): return False

    # 6. Re-Enter Account Number
    try:
        if acc_no:
            await fill_input_with_delay(page, 'input[name="Re-Enter Account Number"]', acc_no, "Re-Enter Account Number", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error filling Re-Enter Account Number: {e}")

    if stop_cb(): return False

    # 7. Account Type
    try:
        if acc_type:
            await select_dropdown_with_delay(page, 'select[name="Account Type"]', acc_type.upper(), "Account Type", log, field_delay_ms)
        else:
            log("  ⚠️ Account Type missing from both Cheque and Excel.")
    except Exception as e:
        log(f"  ⚠️ Error selecting Account Type: {e}")

    if stop_cb(): return False

    # 8. Party Payment Method
    try:
        # Default is NEFT, just ensuring it is set.
        await select_dropdown_with_delay(page, 'select[name="Party Payment Method"]', "NEFT", "Payment Method", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error selecting Payment Method: {e}")

    log("Phase 7 (NEFT Details) completed successfully.")
    return True
