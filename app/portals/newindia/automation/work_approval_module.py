import asyncio
import logging
import os
from playwright.async_api import Page, Locator
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay
)
from app.automation.automation_logger import _ts

logger = logging.getLogger(__name__)

def _find_approval_document(data: ClaimData, is_cashless: bool) -> str:
    """Scans uploaded assessment and claim documents to find the approval document."""
    keywords_non_cashless = ["non_cashless", "non-cashless", "noncashless", "non cashless", "non_caseless", "non-caseless"]
    keywords_cashless = ["cashless", "caseless"]
    
    # Extract folder path from any known document
    folder_path = None
    if data.claim_doc_files:
        folder_path = os.path.dirname(next(iter(data.claim_doc_files.values())))
    elif data.assessment_files:
        folder_path = os.path.dirname(next(iter(data.assessment_files.values())))
        
    if not folder_path or not os.path.isdir(folder_path):
        return ""
        
    # Scan all files in the folder directly to avoid missing files skipped by the mapper
    try:
        all_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    except Exception as e:
        logger.error(f"Failed to read folder for approval documents: {e}")
        return ""
        
    if not is_cashless:
        # Looking for Non-Cashless Document
        for file_path in all_files:
            fname_lower = os.path.basename(file_path).lower()
            if any(k in fname_lower for k in keywords_non_cashless):
                return file_path
    else:
        # Looking for Cashless Document
        for file_path in all_files:
            fname_lower = os.path.basename(file_path).lower()
            # Must contain cashless but NOT non-cashless
            if any(k in fname_lower for k in keywords_cashless) and not any(k in fname_lower for k in keywords_non_cashless):
                return file_path
    return ""

async def fill_work_approval_details(
    page: Page,
    data: ClaimData,
    log_cb,
    stop_cb,
    field_delay_ms: int = 500
) -> bool:
    """
    Phase 8: Fills the Work Approval Details section.
    
    Logic:
    1. Determine Approval Type based on NEFT payment logic (Cheque present -> Insured -> Non-cashless).
    2. Upload matching approval document.
    3. Fill Work Approval Date & Time.
    4. Click Submit.
    5. Fill Vehicle Details Matching & Cause of Accident.
    """
    if stop_cb(): return False

    def log(msg: str):
        logger.info(msg)
        if log_cb:
            log_cb(f"[{_ts()}]   [WA] {msg}")

    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log("  📝 STEP 9/9 ─ Work Approval Details")
    log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 1. Expand the Work Approval Details accordion
    log("Opening Work Approval Details section...")
    try:
        accordion_header = page.locator('a.accordion-toggle:has-text("Work Approval Details")')
        if await accordion_header.count() > 0:
            is_expanded = await accordion_header.evaluate('el => el.parentElement.parentElement.classList.contains("collapsed") == false')
            if not is_expanded:
                await accordion_header.click()
                await asyncio.sleep(1.0)
                log("  ✅ Expanded Work Approval Details.")
    except Exception as e:
        log(f"  ⚠️ Error expanding Work Approval Details: {e}")

    # 2. Determine Approval Type from internal extracted state
    payment_to_val = getattr(data, 'bank_payment_to', '') or ""
    # Dealer means Cashless, Insured means Non-Cashless
    is_cashless = ("Dealer" in payment_to_val)
    log(f"  ℹ️ Using existing Payment Type from extraction: '{payment_to_val}'")

    try:
        if is_cashless:
            await select_dropdown_with_delay(page, 'select[name="Approval Type"]', "Cashless approved", "Approval Type", log, field_delay_ms)
        else:
            await select_dropdown_with_delay(page, 'select[name="Approval Type"]', "Non-cashless approved", "Approval Type", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error selecting Approval Type: {e}")

    if stop_cb(): return False

    # 3. Upload Document
    #   a. How document is searched: _find_approval_document checks dictionary keys and filenames
    #   b. How matching file is selected: Returns the first file matching "cashless" or "non_cashless"
    log("  ℹ️ Searching for approval document...")
    doc_path = _find_approval_document(data, is_cashless)
    
    if doc_path and os.path.exists(doc_path):
        try:
            # c. How upload input/button is handled: We bypass the visual 'Browse' button
            #    and interact directly with the hidden HTML file input element.
            file_input = page.locator('input[id="workApprovalFile"][type="file"]')
            
            # d. How file path is passed: Using Playwright's set_input_files native handler
            await file_input.set_input_files(doc_path)
            log(f"  ✅ Uploaded Approval Document: {os.path.basename(doc_path)}")
            await asyncio.sleep(1.0)
            
            # e. How upload completion is verified: Check the readonly text input that displays the file name
            uploaded_name = await page.locator('input[name="Work Approval Document"]').input_value()
            if uploaded_name:
                log(f"  ✅ Verified upload completion (UI registered: {uploaded_name}).")
            else:
                log("  ⚠️ Document upload input remained empty after upload attempt.")
        except Exception as e:
            log(f"  ⚠️ Error uploading Approval Document: {e}")
    else:
        log(f"  ⚠️ No matching {'Cashless' if is_cashless else 'Non-Cashless'} document found. Skipping upload.")

    if stop_cb(): return False

    # 4. Work Approval Date
    try:
        val = getattr(data, 'work_approval_date', '')
        if val:
            await fill_input_with_delay(page, 'input[name="Work Approval Date"]', val, "Work Approval Date", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error filling Work Approval Date: {e}")

    if stop_cb(): return False

    # 5. Work Approval Time
    try:
        val = getattr(data, 'work_approval_time', '')
        if val:
            # Portal expects strictly HH:MM (24-hour format). Remove seconds if present.
            formatted_time = str(val).strip()
            if len(formatted_time) >= 5 and ":" in formatted_time:
                formatted_time = formatted_time[:5]
            await fill_input_with_delay(page, 'input[name="Work Approval Time"]', formatted_time, "Work Approval Time", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error filling Work Approval Time: {e}")

    if stop_cb(): return False

    # 6. Whether Vehicle Details are matching with policy (Always YES)
    try:
        await select_dropdown_with_delay(page, 'select[name="Whether Vehicle Details are matching with policy ?"]', "Yes", "Matching Details with Policy", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error selecting Vehicle Details Matching: {e}")

    if stop_cb(): return False

    # 7. Cause and Nature of Accident
    try:
        val = getattr(data, 'cause_nature_of_accident', '')
        if val:
            await fill_input_with_delay(page, 'textarea[name="Cause and Nature of Accident"]', val, "Cause and Nature of Accident", log, field_delay_ms)
    except Exception as e:
        log(f"  ⚠️ Error filling Cause and Nature of Accident: {e}")

    if stop_cb(): return False

    # 8. Click Next button
    try:
        log("  ℹ️ Clicking 'Next' to proceed to Claim Assessment...")
        next_btn = page.locator('button#toClaimAssessment').first
        await next_btn.wait_for(state="visible", timeout=5000)
        await next_btn.click()
        await asyncio.sleep(2.0)  # Wait for transition
        log("  ✅ Clicked 'Next' successfully.")
    except Exception as e:
        log(f"  ⚠️ Error clicking 'Next' button: {e}")

    if stop_cb(): return False

    log("Phase 8 (Work Approval Details) completed successfully.")
    return True
