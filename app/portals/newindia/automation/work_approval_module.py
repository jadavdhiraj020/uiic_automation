import asyncio
import logging
import os
from playwright.async_api import Page, Locator
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay
)
from app.automation.automation_logger import AutomationLogger

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
    log,
    stop_cb,
    field_delay_ms: int = 500
) -> bool:
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.info("Starting Work Approval Details phase...")
        log.indent()
    else:
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log("  📝 STEP 9/9 ─ Work Approval Details")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 1. Expand the Work Approval Details accordion
    if isinstance(log, AutomationLogger):
        log.info("Opening Work Approval Details section...")
    else:
        log("Opening Work Approval Details section...")
    try:
        accordion_header = page.locator('a.accordion-toggle:has-text("Work Approval Details")')
        if await accordion_header.count() > 0:
            is_expanded = await accordion_header.evaluate('el => el.parentElement.parentElement.classList.contains("collapsed") == false')
            if not is_expanded:
                await accordion_header.click()
                await asyncio.sleep(1.0)
                if isinstance(log, AutomationLogger):
                    log.success("Accordion expanded.")
                else:
                    log("  ✅ Expanded Work Approval Details.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Expansion attempt failed: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error expanding Work Approval Details: {e}")

    # 2. Determine Approval Type from internal extracted state
    payment_to_val = getattr(data, 'bank_payment_to', '') or ""
    # Dealer means Cashless, Insured means Non-Cashless
    is_cashless = ("Dealer" in payment_to_val)
    
    if isinstance(log, AutomationLogger):
        log.info(f"Using payment context: '{payment_to_val}'")
    else:
        log(f"  ℹ️ Using existing Payment Type from extraction: '{payment_to_val}'")

    try:
        if is_cashless:
            await select_dropdown_with_delay(page, 'select[name="Approval Type"]', "Cashless approved", "Approval Type", log, field_delay_ms)
        else:
            await select_dropdown_with_delay(page, 'select[name="Approval Type"]', "Non-cashless approved", "Approval Type", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Approval Type dropdown error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error selecting Approval Type: {e}")

    if stop_cb(): return False

    # 3. Upload Document
    if isinstance(log, AutomationLogger):
        log.info("Searching for approval document...")
    else:
        log("  ℹ️ Searching for approval document...")
    doc_path = _find_approval_document(data, is_cashless)
    
    if doc_path and os.path.exists(doc_path):
        try:
            file_input = page.locator('input[id="workApprovalFile"][type="file"]')
            await file_input.set_input_files(doc_path)
            if isinstance(log, AutomationLogger):
                log.upload_attached("Approval Document", os.path.basename(doc_path))
            else:
                log(f"  ✅ Uploaded Approval Document: {os.path.basename(doc_path)}")
            await asyncio.sleep(1.0)
            
            uploaded_name = await page.locator('input[name="Work Approval Document"]').input_value()
            if uploaded_name:
                if isinstance(log, AutomationLogger):
                    log.success(f"Verified upload completion (UI registered: {uploaded_name}).")
                else:
                    log(f"  ✅ Verified upload completion (UI registered: {uploaded_name}).")
            else:
                if isinstance(log, AutomationLogger):
                    log.warning("Document upload input remained empty after attempt.")
                else:
                    log("  ⚠️ Document upload input remained empty after upload attempt.")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.upload_failed("Approval Document", str(e)[:100])
            else:
                log(f"  ⚠️ Error uploading Approval Document: {e}")
    else:
        if isinstance(log, AutomationLogger):
            log.warning(f"No matching {'Cashless' if is_cashless else 'Non-Cashless'} document found; skipping.")
        else:
            log(f"  ⚠️ No matching {'Cashless' if is_cashless else 'Non-Cashless'} document found. Skipping upload.")

    if stop_cb(): return False

    # 4. Work Approval Date
    try:
        val = getattr(data, 'work_approval_date', '')
        if val:
            await fill_input_with_delay(page, 'input[name="Work Approval Date"]', val, "Approval Date", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Approval Date field error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error filling Work Approval Date: {e}")

    if stop_cb(): return False

    # 5. Work Approval Time
    try:
        val = getattr(data, 'work_approval_time', '')
        if val:
            formatted_time = str(val).strip()
            if len(formatted_time) >= 5 and ":" in formatted_time:
                formatted_time = formatted_time[:5]
            await fill_input_with_delay(page, 'input[name="Work Approval Time"]', formatted_time, "Approval Time", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Approval Time field error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error filling Work Approval Time: {e}")

    if stop_cb(): return False

    # 6. Whether Vehicle Details are matching with policy (Always YES)
    try:
        await select_dropdown_with_delay(page, 'select[name="Whether Vehicle Details are matching with policy ?"]', "Yes", "Matching Policy", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Policy Match dropdown error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error selecting Vehicle Details Matching: {e}")

    if stop_cb(): return False

    # 7. Cause and Nature of Accident
    try:
        val = getattr(data, 'cause_nature_of_accident', '')
        if val:
            await fill_input_with_delay(page, 'textarea[name="Cause and Nature of Accident"]', val, "Nature of Accident", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Cause field error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error filling Cause and Nature of Accident: {e}")

    if stop_cb(): return False

    # 8. Click Next button
    try:
        if isinstance(log, AutomationLogger):
            log.wait("Proceeding to Claim Assessment...")
        else:
            log("  ℹ️ Clicking 'Next' to proceed to Claim Assessment...")
        next_btn = page.locator('button#toClaimAssessment').first
        await next_btn.wait_for(state="visible", timeout=5000)
        await next_btn.click()
        await asyncio.sleep(2.0)  # Wait for transition
        if isinstance(log, AutomationLogger):
            log.success("Navigation to Claim Assessment successful.")
        else:
            log("  ✅ Clicked 'Next' successfully.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Navigation error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error clicking 'Next' button: {e}")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("Work Approval Details phase completed.")
    elif log:
        log("Phase 8 (Work Approval Details) completed successfully.")
    return True
