import asyncio
import logging
import os
from playwright.async_api import Page, Locator
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

def _find_final_invoice_document(data: ClaimData) -> str:
    """Finds final invoice document using tracked scan dicts, then falls back to folder scan."""
    try:
        from app.utils import load_doc_mapping
        raw = load_doc_mapping()
        invoice_map = raw.get("claim_assessment_tab", {}).get("invoice", ["final_invoice", "invoice"])
    except Exception:
        invoice_map = ["final_invoice", "invoice"]

    # 1. Search tracked dicts first (respects compression — uses temp file paths)
    all_tracked: dict = {}
    all_tracked.update(getattr(data, 'claim_doc_files', {}) or {})
    all_tracked.update(getattr(data, 'assessment_files', {}) or {})
    all_tracked.update(getattr(data, 'upload_doc_files', {}) or {})

    # Check for direct mapping 'invoice' or 'final_invoice' in assessment_files
    invoice_path = (getattr(data, 'assessment_files', {}) or {}).get("invoice", "")
    if invoice_path and os.path.isfile(invoice_path):
        return invoice_path

    for doc_name, file_path in all_tracked.items():
        if not file_path or not os.path.isfile(file_path):
            continue
        fname_lower = os.path.basename(file_path).lower()
        if any(k in fname_lower for k in invoice_map):
            return file_path

    # 2. Fallback: raw folder scan (finds files not mapped by scanner)
    folder_path = None
    for d in (all_tracked,):
        for fp in d.values():
            if fp and os.path.isfile(fp):
                folder_path = os.path.dirname(fp)
                break
        if folder_path:
            break

    if not folder_path or not os.path.isdir(folder_path):
        return ""

    try:
        all_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    except Exception as e:
        logger.error(f"Failed to read folder for final invoice documents: {e}")
        return ""

    for file_path in all_files:
        fname_lower = os.path.basename(file_path).lower()
        if any(k in fname_lower for k in invoice_map):
            return file_path

    # Secondary fallback for invoice keywords
    secondary_keywords = ["garage_bill", "garage bill", "garagebill", "bill"]
    for file_path in all_files:
        fname_lower = os.path.basename(file_path).lower()
        if any(k in fname_lower for k in secondary_keywords):
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

    try:
        return await _fill_work_approval_inner(page, data, log, stop_cb, field_delay_ms)
    finally:
        if isinstance(log, AutomationLogger):
            log.outdent()


async def _fill_work_approval_inner(
    page: Page,
    data: ClaimData,
    log,
    stop_cb,
    field_delay_ms: int = 500
) -> bool:
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.info("Opening Work Approval Details section...")
    else:
        log("Opening Work Approval Details section...")
    try:
        accordion_header = page.locator('a.accordion-toggle:has-text("Work Approval Details")').first
        if await accordion_header.count() > 0:
            # Check <a> tag class (NIA portal sets 'collapsed' on the <a>, not div.panel-heading)
            acc_class = await accordion_header.get_attribute('class') or ''
            if 'collapsed' in acc_class:
                await accordion_header.click()
                await asyncio.sleep(1.0)
                if isinstance(log, AutomationLogger):
                    log.success("Accordion expanded.")
                else:
                    log("  ✅ Expanded Work Approval Details.")
            else:
                if isinstance(log, AutomationLogger):
                    log.info("Accordion already expanded.")
                else:
                    log("  ℹ️ Work Approval Details already expanded.")
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
        log.info("Searching for Final Invoice...")
    else:
        log("  ℹ️ Searching for Final Invoice...")
    doc_path = _find_final_invoice_document(data)
    
    if doc_path and os.path.exists(doc_path):
        try:
            file_input = page.locator('input[id="workApprovalFile"][type="file"]')
            await file_input.set_input_files(doc_path)
            if isinstance(log, AutomationLogger):
                log.upload_attached("Final Invoice", os.path.basename(doc_path))
            else:
                log(f"  ✅ Uploaded Final Invoice: {os.path.basename(doc_path)}")
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
                log.upload_failed("Final Invoice", str(e)[:100])
            else:
                log(f"  ⚠️ Error uploading Final Invoice: {e}")
    else:
        if isinstance(log, AutomationLogger):
            log.warning("No Final Invoice found; skipping.")
        else:
            log("  ⚠️ No Final Invoice found. Skipping upload.")

    if stop_cb(): return False

    # 4. Work Approval Date
    try:
        val = str(getattr(data, 'work_approval_date', '') or '').strip()
        if val:
            await fill_input_with_delay(page, 'input[name="Work Approval Date"]', val, "Approval Date", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Work Approval Date missing; skipping.")
            else:
                log("  ⚠️ Work Approval Date missing from data; skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Approval Date field error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error filling Work Approval Date: {e}")

    if stop_cb(): return False

    # 5. Work Approval Time
    try:
        val = str(getattr(data, 'work_approval_time', '') or '').strip()
        if val:
            # Normalise to HH:MM format
            if len(val) >= 5 and ":" in val:
                val = val[:5]
            await fill_input_with_delay(page, 'input[name="Work Approval Time"]', val, "Approval Time", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Work Approval Time missing; skipping.")
            else:
                log("  ⚠️ Work Approval Time missing from data; skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Approval Time field error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error filling Work Approval Time: {e}")

    if stop_cb(): return False

    # 5.1 Click Submit button for Work Approval (now Final Invoice)
    if doc_path and os.path.exists(doc_path):
        if isinstance(log, AutomationLogger):
            log.wait("Submitting Final Invoice (Work Approval Document)...")
        else:
            log("  ℹ️ Submitting Final Invoice (Work Approval Document)...")

        try:
            # Wait for Angular digest cycle to enable the Submit button
            await asyncio.sleep(1.0)
            
            submit_btn = page.locator('button[data-ng-click*="submitDocs"][data-ng-click*="WORK APPROVAL"]').first
            await submit_btn.wait_for(state="visible", timeout=5000)
            
            if await submit_btn.is_disabled():
                # Wait one more second
                await asyncio.sleep(1.0)
                
            if await submit_btn.is_disabled():
                if isinstance(log, AutomationLogger):
                    log.warning("Work Approval Submit button (for Final Invoice) is disabled; might already be submitted or invalid.")
                else:
                    log("  ⚠️ Work Approval Submit button (for Final Invoice) is disabled.")
            else:
                await submit_btn.click()
                if isinstance(log, AutomationLogger):
                    log.success("Final Invoice (Work Approval) submitted successfully.")
                else:
                    log("  ✅ Final Invoice (Work Approval) submitted.")
                
                # Handle the confirmation popup
                await dismiss_portal_popup(page, log, max_wait_s=6.0)
                await asyncio.sleep(1.0)
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Work Approval submit button error: {str(e)[:100]}")
            else:
                log(f"  ⚠️ Error clicking Work Approval Submit button: {e}")

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
        val = str(getattr(data, 'cause_nature_of_accident', '') or '').strip()
        if val:
            await fill_input_with_delay(page, 'textarea[name="Cause and Nature of Accident"]', val, "Nature of Accident", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Cause and Nature of Accident missing; skipping.")
            else:
                log("  ⚠️ Cause and Nature of Accident missing from data; skipping.")
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
        log.success("Work Approval Details phase completed.")
    elif log:
        log("Phase 8 (Work Approval Details) completed successfully.")
    return True
