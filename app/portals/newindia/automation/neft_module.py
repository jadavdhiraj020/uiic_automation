import asyncio
from playwright.async_api import Error as PlaywrightError, Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay, select_dropdown_with_delay,
    additional_section, open_additional_section, record_additional_issue,
)
from app.automation.automation_logger import AutomationLogger, _ts
from app.utils import load_automation_defaults

async def _fill_ifsc(page, value, log, delay_ms, source):
    await fill_input_with_delay(page, 'input[name="IFSC Code"]', value, "IFSC Code", log, delay_ms, source=source)
    find_btn = page.locator('button[data-ng-click="surveyorWorklistSurvey.getIFSCDetails_nt()"]:visible')
    if await find_btn.count() == 1:
        await find_btn.click(timeout=5000)
        await asyncio.sleep(1.5)  # Allow the bank lookup to populate the read-only fields.
        if isinstance(log, AutomationLogger):
            log.success("Bank details fetched via 'Find' button.")
        else:
            log(f"[{_ts()}]   ✅ Clicked 'Find' to fetch bank details.")


async def fill_ready_cheque_details(page, data, log, stop_cb, field_delay_ms):
    """Use a completed background result to fill bank fields still blank at Next."""
    event = getattr(data, "_deferred_cheque_ocr_event", None)
    if stop_cb() or event is None or not event.is_set():
        return

    heading = additional_section(page, "NEFT Details")
    if await heading.count() != 1:
        return
    panel = heading.locator("xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' panel ')][1]")
    account = str(data.account_number or "").strip()
    fields = (
        ("IFSC Code", str(data.ifsc_code or "").strip()),
        ("Account Number", account),
        ("Re-Enter Account Number", account),
    )
    pending = []
    for name, value in fields:
        if not value:
            continue
        selector = f'input[name="{name}"]'
        field = panel.locator(selector)
        if await field.count() != 1:
            continue
        try:
            existing = (await field.input_value(timeout=1000)).strip()
            # A manual edit may indicate a different bank account. Avoid mixing the two.
            if existing and existing.casefold() != value.casefold():
                return
            if not existing and await field.is_editable(timeout=1000):
                pending.append((name, selector, value))
        except PlaywrightError:
            return

    if not pending or not await open_additional_section(page, "NEFT Details", log, optional=True):
        return

    previous_section = getattr(log, "_section", None)
    if isinstance(log, AutomationLogger):
        log._section = "NEFT Details"
    try:
        for name, selector, value in pending:
            if stop_cb():
                return
            field = panel.locator(f"{selector}:visible")
            try:
                if await field.count() != 1 or not await field.is_editable(timeout=1000):
                    continue
                if (await field.input_value(timeout=1000)).strip():
                    continue
                if name == "IFSC Code":
                    await _fill_ifsc(page, value, log, field_delay_ms, "Cheque OCR")
                else:
                    await fill_input_with_delay(page, selector, value, name, log, field_delay_ms, source="Cheque OCR")
            except PlaywrightError:
                record_additional_issue(log, name)
    finally:
        if isinstance(log, AutomationLogger):
            log._section = previous_section


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
        log._section = "NEFT Details"
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
    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))

    if not await open_additional_section(page, "NEFT Details", log, optional=True):
        return not stop_cb()

    if stop_cb():
        return False

    if isinstance(log, AutomationLogger):
        log.info("Scanning uploaded documents for cheque...")
    else:
        log(f"Scanning uploaded documents for cheque...")
    cheque_path = _find_cheque_document(data)
    
    ifsc = data.ifsc_code
    acc_no = data.account_number
    acc_type = data.account_type or defaults.get("account_type", "")

    # Establish data source descriptors
    ifsc_source = "Excel" if data.ifsc_code else "Default"
    acc_no_source = "Excel" if data.account_number else "Default"
    acc_type_source = "Excel" if data.account_type else "Default"

    if cheque_path:
        deferred_cheque = getattr(data, "_deferred_cheque_ocr_event", None)
        # Run OCR only if fields are missing in data (e.g. if extraction failed or excel was empty)
        if (not ifsc or not acc_no) and deferred_cheque is None:
            if isinstance(log, AutomationLogger):
                log.success("Cheque document detected. Running OCR for missing bank details...")
                import os
                log.extraction(f"Starting Cheque OCR: {os.path.basename(cheque_path)}")
            else:
                log(f"   ✅ Cheque document detected. Running OCR for missing bank details...")
                log(f"   ℹ️ Extracting details from cheque...")
            
            try:
                from app.portals.newindia.automation.ocr_helper import ChequeExtractor
                cheque_details = ChequeExtractor(cheque_path).extract_details(
                    log=log, excel_ifsc=data.ifsc_code or "", excel_account=data.account_number or "",
                ) or {}
            except Exception:
                cheque_details = {}
                message = "Cheque OCR failed. Using the available bank details."
                log.warning(message) if isinstance(log, AutomationLogger) else log(message)
            
            if not ifsc:
                ifsc = cheque_details.get("ifsc")
                if ifsc:
                    ifsc_source = "OCR"
            if not acc_no:
                acc_no = cheque_details.get("account_number")
                if acc_no:
                    acc_no_source = "OCR"
            if not acc_type or acc_type == defaults.get("account_type", ""):
                ocr_type = cheque_details.get("account_type")
                if ocr_type:
                    acc_type = ocr_type
                    acc_type_source = "OCR"
            
            if isinstance(log, AutomationLogger):
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
        elif not ifsc or not acc_no:
            message = "Using available bank details from the scan."
            log.warning(message) if isinstance(log, AutomationLogger) else log(message)
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
            field_delay_ms,
            source="Calculated"
        )
    except Exception:
        record_additional_issue(log, "Payment To")

    if stop_cb(): return False

    # 2. If Dealer, fill Dealer Name
    if payment_to_value == "Dealer":
        try:
            val = str(getattr(data, 'dealer_name', '') or getattr(data, 'registered_owner_name', '') or '').strip()
            if val:
                await fill_input_with_delay(
                    page, 'input[name="Dealer Name"]', val, "Dealer Name", log, field_delay_ms,
                    source="Excel" if getattr(data, 'dealer_name', '') else "Calculated"
                )
            else:
                if isinstance(log, AutomationLogger):
                    log.field_skipped("Dealer Name", reason="Missing from source data")
                else:
                    log("   ⚠️ Dealer Name missing from data; skipping.")
        except Exception:
            record_additional_issue(log, "Dealer Name")

    if stop_cb(): return False

    # 3. IFSC Code
    try:
        if ifsc:
            await _fill_ifsc(page, ifsc, log, field_delay_ms, ifsc_source)
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("IFSC Code", reason="Missing from both Cheque and Excel")
            else:
                log(f"   ⚠️ IFSC Code missing from both Cheque and Excel.")
    except Exception:
        record_additional_issue(log, "IFSC Code")

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
            await fill_input_with_delay(page, 'input[name="Account Number"]', acc_no, "Account Number", log, field_delay_ms, source=acc_no_source)
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Account Number", reason="Missing from both Cheque and Excel")
    except Exception:
        record_additional_issue(log, "Account Number")

    if stop_cb(): return False

    # 6. Re-Enter Account Number
    try:
        if acc_no:
            await fill_input_with_delay(page, 'input[name="Re-Enter Account Number"]', acc_no, "Re-Enter Account Number", log, field_delay_ms, source="Calculated")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Re-Enter Account Number", reason="Missing account number")
    except Exception:
        record_additional_issue(log, "Re-Enter Account Number")

    if stop_cb(): return False

    # 7. Account Type
    try:
        if acc_type:
            await select_dropdown_with_delay(page, 'select[name="Account Type"]', acc_type.upper(), "Account Type", log, field_delay_ms, source=acc_type_source)
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Account Type", reason="Missing from both Cheque and Excel")
            else:
                log(f"   ⚠️ Account Type missing from both Cheque and Excel.")
    except Exception:
        record_additional_issue(log, "Account Type")

    if stop_cb(): return False

    # 8. Party Payment Method
    try:
        payment_method = str(defaults.get("payment_method", "NEFT") or "NEFT")
        await select_dropdown_with_delay(page, 'select[name="Party Payment Method"]', payment_method, "Payment Method", log, field_delay_ms, source="Default")
    except Exception:
        record_additional_issue(log, "Payment Method")

    if isinstance(log, AutomationLogger):
        log.success("NEFT Details phase completed.")
    else:
        log(f" Phase 7 (NEFT Details) completed successfully.")
    return True
