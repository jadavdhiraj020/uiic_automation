import asyncio
import logging
import os
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay,
    open_additional_section,
    record_additional_issue,
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.portals.newindia.automation.recovery import _TAB_STATE, current_recovery
from app.portals.oic.automation.recovery import wait_until_ready
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

logger = logging.getLogger(__name__)
_NEXT = "button#toClaimAssessment"

def _find_final_invoice_document(data: ClaimData) -> str:
    """Finds final invoice document using tracked scan dicts, then falls back to folder scan.
    Only allows .pdf files as per portal requirement.
    """
    try:
        from app.utils import load_doc_mapping
        # Explicitly pass portal_id to ensure New India's doc_mapping.json is
        # loaded, not the currently active portal's mapping (which may be "uiic"
        # if the registry global is unset at test time or during a startup race).
        raw = load_doc_mapping(portal_id="newindia")
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
    invoice_path = os.path.normpath(invoice_path) if invoice_path else ""
    if invoice_path and os.path.isfile(invoice_path) and invoice_path.lower().endswith('.pdf'):
        return invoice_path

    for doc_name, file_path in all_tracked.items():
        if not file_path:
            continue
        file_path = os.path.normpath(file_path)
        if not os.path.isfile(file_path):
            continue
        fname_lower = os.path.basename(file_path).lower()
        if fname_lower.endswith('.pdf') and any(k in fname_lower for k in invoice_map):
            return file_path

    # Extract folder path from any known document
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
        
    # Scan all files in the folder directly to avoid missing files skipped by the mapper
    try:
        all_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
    except Exception as e:
        logger.error(f"Failed to read folder for final invoice documents: {e}")
        return ""
        
    for file_path in all_files:
        fname_lower = os.path.basename(file_path).lower()
        if fname_lower.endswith('.pdf') and any(k in fname_lower for k in invoice_map):
            return file_path

    # Secondary fallback for invoice keywords
    secondary_keywords = ["garage_bill", "garage bill", "garagebill", "bill"]
    for file_path in all_files:
        fname_lower = os.path.basename(file_path).lower()
        if fname_lower.endswith('.pdf') and any(k in fname_lower for k in secondary_keywords):
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
        log._section = "Work Approval Details"
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


async def _fill_work_approval_section(page, data, log, stop_cb, field_delay_ms):
    # 2. Determine Approval Type
    #    Normalise to exact portal dropdown text so the JS selector hits the
    #    fast exact-match path (Pass 1) every time, regardless of source casing.
    raw_approval = (getattr(data, 'approval_type', '') or '').strip()
    if not raw_approval:
        # Derive from payment context: Dealer → Cashless, otherwise Non-cashless
        payment_to_val = getattr(data, 'bank_payment_to', '') or ""
        approval_val = "Cashless approved" if "Dealer" in payment_to_val else "Non-cashless approved"
        approval_source = "Calculated"
        if isinstance(log, AutomationLogger):
            log.info(f"Derived Approval Type from payment context: '{approval_val}'")
        else:
            log(f"  ℹ️ Derived Approval Type from payment context: '{approval_val}'")
    else:
        # Normalise extracted value to exact portal text (case-insensitive check)
        lower_approval = raw_approval.lower()
        if "non-cashless" in lower_approval or "non cashless" in lower_approval:
            approval_val = "Non-cashless approved"
        elif "cashless" in lower_approval:
            approval_val = "Cashless approved"
        else:
            # Unrecognised value — pass through and let the JS substring matcher handle it
            approval_val = raw_approval
        approval_source = "Excel"
        if isinstance(log, AutomationLogger):
            log.info(f"Normalised Approval Type: '{raw_approval}' → '{approval_val}'")
        else:
            log(f"  ℹ️ Normalised Approval Type: '{raw_approval}' → '{approval_val}'")

    try:
        await select_dropdown_with_delay(page, 'select[name="Approval Type"]', approval_val, "Approval Type", log, field_delay_ms, source=approval_source)
    except Exception:
        record_additional_issue(log, "Approval Type")

    if stop_cb(): return False

    # 3. Upload Document
    if isinstance(log, AutomationLogger):
        log.info("Searching for Final Invoice...")
    else:
        log("  ℹ️ Searching for Final Invoice...")
    doc_path = _find_final_invoice_document(data)
    document_attached = False
    
    if doc_path and os.path.exists(doc_path):
        try:
            fname = os.path.basename(doc_path)
            fsize = os.path.getsize(doc_path)
            if isinstance(log, AutomationLogger):
                log.document_mapped("Final Invoice", fname, "Matched Successfully")
                log.upload_start("Final Invoice", fname, fsize)

            file_input = page.locator('input[id="workApprovalFile"][type="file"]')
            await file_input.set_input_files(doc_path, timeout=5000)
            if isinstance(log, AutomationLogger):
                log.upload_attached("Final Invoice", fname)
            else:
                log(f"  ✅ Uploaded Final Invoice: {fname}")
            await asyncio.sleep(1.0)
            
            uploaded_name = await page.locator('input[name="Work Approval Document"]').input_value(timeout=4000)
            if uploaded_name:
                document_attached = True
                if isinstance(log, AutomationLogger):
                    log.success(f"Verified upload completion (UI registered: {uploaded_name}).")
                else:
                    log(f"  ✅ Verified upload completion (UI registered: {uploaded_name}).")
            else:
                record_additional_issue(log, "Work Approval Document", "New India did not show the attached invoice.")
        except Exception:
            record_additional_issue(log, "Work Approval Document", "App3 could not attach the invoice.")
    else:
        if isinstance(log, AutomationLogger):
            log.field_skipped("Final Invoice", reason="No matched PDF document found")
        else:
            log("  ⚠️ No Final Invoice PDF document found. Skipping upload.")

    if stop_cb(): return False

    # 4. Work Approval Date
    try:
        val = str(getattr(data, 'work_approval_date', '') or '').strip()
        if val:
            await fill_input_with_delay(page, 'input[name="Work Approval Date"]', val, "Approval Date", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Approval Date", reason="Missing from Excel")
            else:
                log("  ⚠️ Work Approval Date missing from data; skipping.")
    except Exception:
        record_additional_issue(log, "Work Approval Date")

    if stop_cb(): return False

    # 5. Work Approval Time
    try:
        val = str(getattr(data, 'work_approval_time', '') or '').strip()
        if val:
            # Normalise to HH:MM format
            if len(val) >= 5 and ":" in val:
                val = val[:5]
            selector = 'input[name="workApprovalTime"], input[name="Work Approval Time"]'
            await fill_input_with_delay(page, selector, val, "Work Approval Time", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Approval Time", reason="Missing from Excel")
            else:
                log("  ⚠️ Work Approval Time missing from data; skipping.")
    except Exception:
        record_additional_issue(log, "Work Approval Time")

    if stop_cb(): return False

    # 5.1 Click Submit button for Work Approval (Final Invoice)
    if document_attached:
        if isinstance(log, AutomationLogger):
            log.wait("Final Invoice submission")
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
                await submit_btn.click(timeout=5000)
                
                # Handle the confirmation popup
                result = await dismiss_portal_popup(page, log, max_wait_s=6.0, classify=True)
                if result == "size_error":
                    record_additional_issue(log, "Work Approval Document", "New India rejected the invoice file size.")
                await asyncio.sleep(1.0)
        except Exception:
            record_additional_issue(log, "Work Approval Document", "App3 could not complete the invoice upload.")

    if stop_cb(): return False
    return True


async def _fill_work_approval_inner(
    page: Page,
    data: ClaimData,
    log,
    stop_cb,
    field_delay_ms: int = 500,
) -> bool:
    if stop_cb():
        return False
    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))

    if await open_additional_section(page, "Work Approval Details", log, optional=True):
        if not await _fill_work_approval_section(page, data, log, stop_cb, field_delay_ms):
            return False
    if stop_cb():
        return False

    if isinstance(log, AutomationLogger):
        log._section = "Additional Details"

    try:
        value = str(defaults.get("vehicle_details_match_policy") or "Yes")
        await select_dropdown_with_delay(
            page, 'select[name="Whether Vehicle Details are matching with policy ?"]', value,
            "Whether Vehicle Details are matching with policy?", log, field_delay_ms, source="Default",
        )
    except Exception:
        record_additional_issue(log, "Whether Vehicle Details are matching with policy?")

    if stop_cb(): return False

    try:
        remarks = data.vehicle_details_mismatch_remarks
        selector = 'textarea[name="Vehicle Details Mismatch Remarks"]'
        if remarks and await page.locator(f"{selector}:visible").count():
            await fill_input_with_delay(
                page, selector, remarks, "Vehicle Details Mismatch Remarks", log, field_delay_ms, source="Excel",
            )
    except Exception:
        record_additional_issue(log, "Vehicle Details Mismatch Remarks")

    if stop_cb(): return False

    try:
        val = str(getattr(data, 'cause_nature_of_accident', '') or '').strip()
        if val:
            await fill_input_with_delay(page, 'textarea[name="Cause and Nature of Accident"]',
                                        val, "Cause and Nature of Accident", log, field_delay_ms, source="Excel")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Nature of Accident", reason="Missing from Excel")
            else:
                log("  ⚠️ Cause and Nature of Accident missing from data; skipping.")
    except Exception:
        record_additional_issue(log, "Cause and Nature of Accident")

    if stop_cb(): return False

    # 8. Click Next button
    recovery = current_recovery.get()
    if recovery is not None:
        advanced = await recovery.advance_next(
            page, log, _NEXT,
            source="two", destination="three", title="Claim Assessment",
            after_click=lambda: dismiss_portal_popup(page, log, max_wait_s=2.0, context="Additional Details Next"),
        )
        if advanced and isinstance(log, AutomationLogger):
            log.success("Work Approval Details phase completed.")
        return advanced

    try:
        if isinstance(log, AutomationLogger):
            log.wait("Proceeding to Claim Assessment...")
        else:
            log("  ℹ️ Clicking 'Next' to proceed to Claim Assessment...")
        await page.locator(f"{_NEXT}:visible").click(timeout=5000)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Navigation error: {str(e)[:100]}")
        else:
            log(f"  ⚠️ Error clicking 'Next' button: {e}")
        return False

    async def opened_assessment():
        return await page.evaluate(_TAB_STATE) == "three"

    if not await wait_until_ready(opened_assessment, seconds=4, stopped=stop_cb):
        return False

    if isinstance(log, AutomationLogger):
        log.success("Work Approval Details phase completed.")
    elif log:
        log("Phase 8 (Work Approval Details) completed successfully.")
    return True
