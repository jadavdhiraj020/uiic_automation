import asyncio
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay
)
from app.automation.automation_logger import AutomationLogger, _ts

def _find_cheque_document(data: ClaimData) -> str:
    """Scans claim and upload doc dicts to find the cheque image/PDF."""
    import os
    all_docs = {**data.claim_doc_files, **(data.upload_doc_files or {})}
    for doc_name, file_path in all_docs.items():
        if "cheque" in doc_name.lower() or "check" in doc_name.lower():
            if "fallback" not in os.path.basename(file_path).lower():
                return file_path
    return ""

async def fill_neft_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.info("Opening NEFT Details section...")
        log.indent()
    else:
        log(f"Opening NEFT Details section...")

    try:
        return await _fill_neft_details_inner(page, data, log, stop_cb, field_delay_ms)
    finally:
        if isinstance(log, AutomationLogger):
            log.outdent()


async def _fill_neft_details_inner(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    try:
        acc_heading = page.locator('a.accordion-toggle:has-text("NEFT Details")').first
        await acc_heading.wait_for(state="visible", timeout=10000)
        
        parent_div = page.locator('div.panel-heading').filter(has=acc_heading).first
        is_collapsed = 'collapsed' in await parent_div.get_attribute('class')
        if is_collapsed:
            await acc_heading.click()
            await asyncio.sleep(1.5)
            if isinstance(log, AutomationLogger):
                log.success("Accordion expanded.")
            else:
                log(f"   ✅ Expanded NEFT Details.")
        else:
            if isinstance(log, AutomationLogger):
                log.info("Accordion already expanded.")
            else:
                log(f"   ℹ️ NEFT Details already expanded.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Expansion attempt failed: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Could not expand NEFT Details: {e}")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.info("Scanning uploaded documents for cheque...")
    else:
        log(f"Scanning uploaded documents for cheque...")
    cheque_path = _find_cheque_document(data)
    
    ifsc = data.ifsc_code
    acc_no = data.account_number
    acc_type = data.account_type

    if cheque_path:
        # Run OCR only if fields are missing in data (e.g. if extraction failed or excel was empty)
        if not ifsc or not acc_no:
            if isinstance(log, AutomationLogger):
                log.success("Cheque document detected. Running OCR for missing bank details...")
                import os
                log.extraction(f"Starting Cheque OCR: {os.path.basename(cheque_path)}")
            else:
                log(f"   ✅ Cheque document detected. Running OCR for missing bank details...")
                log(f"   ℹ️ Extracting details from cheque...")
            
            from app.portals.newindia.automation.ocr_helper import ChequeExtractor
            extractor = ChequeExtractor(cheque_path)
            cheque_details = extractor.extract_details(
                log=log,
                excel_ifsc=data.ifsc_code or "",
                excel_account=data.account_number or "",
            )
            
            if not ifsc:
                ifsc = cheque_details.get("ifsc")
            if not acc_no:
                acc_no = cheque_details.get("account_number")
            if not acc_type:
                acc_type = cheque_details.get("account_type")
            
            if isinstance(log, AutomationLogger):
                log.success("Cheque OCR completed successfully.")
                log.extracted("IFSC", ifsc)
                log.extracted("Account", acc_no)
                if not cheque_details.get("ifsc"):
                    log.warning("IFSC not found in cheque; using Excel fallback.")
                if not cheque_details.get("account_number"):
                    log.warning("Account Number not found in cheque; using Excel fallback.")
            else:
                if not cheque_details.get("ifsc"):
                    log(f"   ⚠️ IFSC not found in cheque. Falling back to Excel.")
                if not cheque_details.get("account_number"):
                    log(f"   ⚠️ Account Number not found in cheque. Falling back to Excel.")
        else:
            if isinstance(log, AutomationLogger):
                log.success("Cheque document detected. Using pre-extracted and reviewed bank details.")
                log.extracted("IFSC", ifsc)
                log.extracted("Account", acc_no)
            else:
                log(f"   ✅ Cheque document detected. Using pre-extracted bank details: IFSC={ifsc}, Acc={acc_no}")
    else:
        if isinstance(log, AutomationLogger):
            log.warning("Cheque document NOT detected; strictly using Excel data.")
        else:
            log(f"   ⚠️ Cheque document NOT detected.")
        ifsc = data.ifsc_code
        acc_no = data.account_number
        acc_type = data.account_type

    # Single Source of Truth: Read payment type established during extraction
    payment_to_value = (data.bank_payment_to or "Dealer").strip()
    if isinstance(log, AutomationLogger):
        log.info(f"Target Payment Entity: '{payment_to_value}'")
    else:
        log(f"   ℹ️ Using pre-calculated Payment Type: '{payment_to_value}'")

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
        if isinstance(log, AutomationLogger):
            log.error(f"Payment To field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Payment To: {e}")

    if stop_cb(): return False

    # 2. If Dealer, fill Dealer Name
    if payment_to_value == "Dealer":
        try:
            val = str(getattr(data, 'dealer_name', '') or getattr(data, 'registered_owner_name', '') or '').strip()
            if val:
                await fill_input_with_delay(page, 'input[name="Dealer Name"]', val, "Dealer Name", log, field_delay_ms)
            else:
                if isinstance(log, AutomationLogger):
                    log.warning("Dealer Name not found in data; skipping.")
                else:
                    log("   ⚠️ Dealer Name missing from data; skipping.")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Dealer Name field error: {str(e)[:100]}")
            else:
                log(f"   ⚠️ Error filling Dealer Name: {e}")

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
                if isinstance(log, AutomationLogger):
                    log.success("Bank details fetched via 'Find' button.")
                else:
                    log(f"[{_ts()}]   ✅ Clicked 'Find' to fetch bank details.")
        else:
            if isinstance(log, AutomationLogger):
                log.warning("IFSC Code missing from all sources.")
            else:
                log(f"   ⚠️ IFSC Code missing from both Cheque and Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"IFSC lookup error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling IFSC Code: {e}")

    if stop_cb(): return False

    # 4. Readonly fields: Bank Name, Bank Branch Name, Bank Address
    # We skip filling these as they are auto-populated by the Find button.
    if isinstance(log, AutomationLogger):
        log.info("Readonly bank fields auto-populated by IFSC Find button; skipping manual entry.")
    else:
        log(f"   ℹ️ Skipping readonly fields (Bank Name, Branch Name, Bank Address) — populated by Find.")

    # 5. Account Number
    try:
        if acc_no:
            await fill_input_with_delay(page, 'input[name="Account Number"]', acc_no, "Account Number", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Account Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Account Number: {e}")

    if stop_cb(): return False

    # 6. Re-Enter Account Number
    try:
        if acc_no:
            await fill_input_with_delay(page, 'input[name="Re-Enter Account Number"]', acc_no, "Account Re-entry", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Account Re-entry field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Re-Enter Account Number: {e}")

    if stop_cb(): return False

    # 7. Account Type
    try:
        if acc_type:
            await select_dropdown_with_delay(page, 'select[name="Account Type"]', acc_type.upper(), "Account Type", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Account Type missing from all sources.")
            else:
                log(f"   ⚠️ Account Type missing from both Cheque and Excel.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Account Type dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Account Type: {e}")

    if stop_cb(): return False

    # 8. Party Payment Method
    try:
        await select_dropdown_with_delay(page, 'select[name="Party Payment Method"]', "NEFT", "Payment Method", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Payment Method dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Payment Method: {e}")

    if isinstance(log, AutomationLogger):
        log.success("NEFT Details phase completed.")
    else:
        log(f" Phase 7 (NEFT Details) completed successfully.")
    return True
