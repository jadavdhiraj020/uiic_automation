"""Fill the active New India Claim Assessment page, then review it at Next."""

import os
import re
from contextlib import suppress

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger
from app.data.data_model import ClaimData
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.portals.newindia.automation.recovery import _BLOCKING_DIALOGS, _TAB_STATE, current_recovery
from app.portals.newindia.automation.ui_utils import (
    _JS_FIELD_STATE,
    _text_matches_field,
    fill_input_with_delay,
    open_additional_section,
    record_additional_issue as record_review_issue,
    select_dropdown_with_delay,
    upload_file_via_input,
)
from app.portals.newindia.field_values import parse_amount, reinspection_document, workshop_gst_registered
from app.portals.oic.automation.recovery import wait_until_ready
from app.utils import load_automation_defaults


_TAB = 'form[name="workListForm"] .tab-pane.active'
_NEXT_BUTTON = (
    'button[data-ng-click*=".docUploadCall("], button[ng-click*=".docUploadCall("], '
    'button#saveClaimAssesment[data-ng-click*=".saveAssesment("], '
    'button#saveClaimAssesment[ng-click*=".saveAssesment("]'
)
_NEXT = f"{_TAB} :is({_NEXT_BUTTON})"
_SAVE_CONFIRMED = re.compile(
    r"^\s*claim\s+(?:job\s+details|assessment(?:\s+details)?)\s+"
    r"(?:(?:have|has)\s+been\s+)?"
    r"(?:updated\s+successfully|saved\s+successfully|successfully\s+(?:updated|saved))[.!]?"
    r"(?:\s+(?:you\s+(?:may|can)\s+(?:now\s+)?(?:proceed|continue)"
    r"(?:\s+to\s+(?:(?:the\s+)?next\s+(?:page|step)|document\s+upload))?|"
    r"(?:please\s+)?click\s+(?:ok|close)\s+to\s+(?:continue|proceed))[.!]?)?\s*$",
    re.I,
)
_WORKBOOK_IMPORTED = re.compile(
    r"\A\s*(?![\s\S]*\b(?:not|cannot|unable|failed|failure|invalid|error|rejected|unsuccessful|"
    r"duplicate|too\s+large|exceeds?)\b)"
    r"(?:(?:the\s+)?(?:(?:primary|supplementary)\s+)?"
    r"(?:assessment(?:\s+excel)?(?:\s+(?:file|workbook))?|excel(?:\s+(?:file|sheet|workbook))?|"
    r"file|workbook|spreadsheet|data)\s+(?:(?:has|have)\s+been\s+|(?:was|were)\s+)?)?"
    r"(?:successfully\s+(?:uploaded|imported)|(?:uploaded|imported)\s+successfully|"
    r"(?:upload|import)\s+(?:was\s+)?(?:successful|completed\s+successfully))\b",
    re.I,
)
_PAYMENT_INVOICE = 'select[data-ng-model$=".isPaymentInvoice"], select#PaymentInvoiceName'
_FORM_READY = f"{_TAB} :is({_PAYMENT_INVOICE}, {_NEXT_BUTTON}):visible"
_FORM_LOAD_TIMEOUT = 10
_PRIMARY_ESTIMATE = 'select[name^="Is there any primary estimate"]'

# Use the repeater to distinguish primary and supplementary rows on the same page.
_ASSESSMENT_ROWS = r"""
(root, [listName, fileId]) => {
    const table = 'table[id="myTable"]';
    const fileInputs = root.querySelectorAll('input[id="' + fileId + '"]');
    let scope = root;
    if (fileInputs.length > 1) {
        // The workbook belongs to the first invoice. Ignore rows from other invoices.
        for (let node = fileInputs[0].parentElement; node !== root; node = node.parentElement) {
            if (node.contains(fileInputs[1])) return [];
            if (node.querySelector(table)) {
                scope = node;
                break;
            }
        }
        if (scope === root) return [];
    }
    return [...scope.querySelectorAll(table + ' tbody tr')].flatMap(row => {
        const repeat = row.getAttribute('data-ng-repeat') || row.getAttribute('ng-repeat') || '';
        if (!repeat.split(/\W+/).includes(listName)) return [];
        const name = row.querySelector('input[data-ng-model*="partName" i], input[name^="Part Name" i]');
        if (!name?.value.trim()) return [];
        return [[...row.querySelectorAll('input:not([type=hidden]), select')].map(el => el.value)];
    });
}
"""


def _in_assessment(selector):
    return f"{_TAB} :is({selector})"


async def _review_failed_field(log, label, target, value, *, dropdown=False, numeric=False):
    async def read_field():
        if await target.count() != 1:
            return None
        return await target.evaluate(_JS_FIELD_STATE, timeout=1000)

    original = None
    with suppress(Exception):
        original = await read_field()

    def matches_value(state):
        if not state or not state["valid"]:
            return False
        if dropdown:
            return bool(state["value"] and state["option"].strip().casefold() == str(value).strip().casefold())
        return _text_matches_field(state, value, numeric=numeric)

    async def matches():
        return matches_value(await read_field())

    async def manual_value():
        state = await read_field()
        return matches_value(state) or bool(
            state and state["valid"] and state["value"].strip()
            and (original is None or state["value"] != original["value"])
            and (dropdown or _text_matches_field(state, state["value"], numeric=numeric))
        )

    record_review_issue(
        log, label, matches=matches, manual_value=manual_value,
        identity=tuple(original["identity"]) if original else None,
    )


async def _fill_text(page, log, selector, label, value, delay_ms, *, source="Excel", numeric=False):
    if value is None or str(value).strip() == "":
        return
    editable = f":is({selector}):not(:disabled):not([readonly])"
    selector = _in_assessment(editable)
    target = page.locator(f"{selector}:visible")
    try:
        if await target.count():
            await fill_input_with_delay(page, selector, str(value).strip(), label, log, delay_ms,
                                        source=source, numeric=numeric)
    except Exception:
        await _review_failed_field(log, label, target, value, numeric=numeric)


async def _select(page, log, selector, label, value, delay_ms, *, source, index=None):
    selector = _in_assessment(selector)
    try:
        await select_dropdown_with_delay(page, selector, value, label, log, delay_ms, source=source, index=index)
    except Exception:
        target = page.locator(f"{selector}:visible")
        if index is not None:
            target = target.nth(index)
        await _review_failed_field(log, label, target, value, dropdown=True)


async def _fill_invoice_fields(page, data, log, defaults, delay_ms, stop_cb):
    count = await page.locator(f"{_in_assessment(_PAYMENT_INVOICE)}:visible").count()
    for index in range(count):
        if stop_cb():
            return
        label = "Payment Invoice in NIA Name?"
        if count > 1:
            label = f"Invoice {index + 1} / {label}"
        await _select(page, log, _PAYMENT_INVOICE, label, str(defaults.get("payment_invoice_in_company_name") or "Yes"),
                      delay_ms, source="Default", index=index)

    if stop_cb():
        return
    workshop = 'select[data-ng-model$=".isWorkshopGstRegistered"], select#isWorkshopGstRegistered'
    if await page.locator(f"{_in_assessment(workshop)}:visible").count():
        # One GST amount belongs to the first invoice.
        await _select(page, log, workshop, "Whether the Workshop is GST Registered",
                      workshop_gst_registered(data.workshop_gst_amount), delay_ms,
                      source="Excel GST amount" if data.workshop_gst_amount else "GST amount absent", index=0)

    for field, model, label in (
        ("vendor_invoice_date", "vendorTaxInvoiceDate", "Vendor/Tax Invoice Date"),
        ("vendor_invoice_number", "vendorTaxInvoiceNumber", "Vendor/Tax Invoice Number"),
    ):
        if stop_cb():
            return
        # The report supplies one invoice. The multiple-invoice form appends its zero-based index.
        suffix = '[name$="0"]' if count > 1 else ""
        await _fill_text(page, log, f'input[data-ng-model$=".{model}"]{suffix}',
                         label, getattr(data, field), delay_ms)


async def _fill_estimate(page, log, data, delay_ms, stop_cb, *, primary):
    kind = "Primary" if primary else "Supplementary"
    label = f"{kind} Assessment Excel"
    name = "Is there any primary estimate" if primary else "Is there any supplementary estimate"
    dropdown = _PRIMARY_ESTIMATE if primary else f'select[name^="{name}"]'
    target = page.locator(f"{_in_assessment(dropdown)}:visible").first
    if not await target.count():
        return

    path = data.assessment_files.get("assessment_excel" if primary else "estimate_excel", "")
    expected = "Yes" if primary or path else "No"
    await _select(page, log, dropdown, name, expected, delay_ms, source="Calculated", index=0)
    if stop_cb() or expected == "No":
        return

    try:
        choice = await target.input_value(timeout=1500)
    except Exception:
        # The dropdown attempt already records a missing control.
        return
    if choice.rsplit(":", 1)[-1].casefold() not in {"yes", "y"}:
        return

    list_name = "addList" if primary else "addListSup"
    file_id = "chooseFilePrim" if primary else "chooseFileSup"
    active_tab = page.locator(_TAB)

    async def imported_rows():
        return await active_tab.evaluate(_ASSESSMENT_ROWS, [list_name, file_id], timeout=1000)

    async def rows_present():
        return bool(await imported_rows())

    previous_rows = None

    async def rows_changed():
        rows = await imported_rows()
        return bool(rows and previous_rows is not None and rows != previous_rows)

    recheck = rows_changed
    try:
        if not path:
            if not await rows_present():
                reason = ("App3 could not prepare the workbook from the survey PDF."
                          if getattr(data, "_newindia_pdf_assessment_error", "")
                          else "The claim folder has no Primary Assessment workbook.")
                record_review_issue(log, label, reason, matches=rows_present)
            return

        previous_rows = await imported_rows()
        if isinstance(log, AutomationLogger):
            log.upload_start(label, os.path.basename(path))
        if not await upload_file_via_input(page, _in_assessment(f"input#{file_id}"), path, label, log):
            record_review_issue(log, label, "App3 could not attach the workbook.", matches=rows_changed)
            return
        if stop_cb():
            return

        method = "readExcel" if primary else "readExcelSup"
        button = _in_assessment(f'button[data-ng-click*="{method}("], button[ng-click*="{method}("]')
        await page.locator(f"{button}:visible").first.click(timeout=5000)
        outcome = await dismiss_portal_popup(
            page, log, max_wait_s=8.0, classify=True, context=label, success_message=_WORKBOOK_IMPORTED,
        )
        if stop_cb():
            return

        if outcome == "size_error":
            reason = "New India rejected the workbook size."
        elif outcome == "duplicate_error":
            reason = "New India reported a duplicate workbook."
        else:
            if outcome == "success":
                # A confirmed re-import can leave the existing rows identical.
                recheck = rows_present
            if await wait_until_ready(recheck, seconds=5, stopped=stop_cb):
                if isinstance(log, AutomationLogger):
                    log.success(f"{label} imported into the assessment rows.")
                return
            reason = "New India did not confirm that the workbook populated the assessment rows."
        if stop_cb():
            return
        if outcome in ("size_error", "duplicate_error"):
            # Only a later operator correction clears an explicit rejection.
            previous_rows = await imported_rows()
        record_review_issue(log, label, reason, matches=recheck)
    except Exception:
        record_review_issue(log, label, "App3 could not complete the workbook import.", matches=recheck)


async def _fill_delivery_order_fields(page, data, log, delay_ms, stop_cb):
    values = (("Delivery Order Date", data.delivery_order_date), ("Delivery Order Time", data.delivery_order_time))
    if not any(value for _, value in values):
        return
    order_form = 'ng-form[name="deliveryOrderDocForm"]'
    if not await page.locator(_in_assessment(order_form)).is_visible() and not await open_additional_section(
        page, "Delivery Order Details", log, optional=True,
    ):
        return

    for label, value in values:
        if stop_cb():
            return
        await _fill_text(page, log, f'{order_form} input[name="{label}"]', label, value, delay_ms)


async def _review_part_wise_assessment(page, log):
    # Maruti uses its part-wise editor and does not expose the Non-Tie-Up workbook import.
    if await page.locator(f"{_in_assessment(_PRIMARY_ESTIMATE)}:visible").count():
        return
    editor = ('button#saveClaimAssesment[data-ng-click*=".saveDetailsMaruti("], '
              'button#saveClaimAssesment[ng-click*=".saveDetailsMaruti("]')
    if not await page.locator(f"{_in_assessment(editor)}:visible").count():
        return
    rows = page.locator(_in_assessment("table#example tbody tr")).filter(
        has=page.locator('select[id="vItem"], input[data-ng-model*="approvalAmount" i]'),
    )

    async def rows_present():
        return bool(await rows.count())

    if not await rows_present():
        record_review_issue(
            log, "Part-wise Assessment",
            "New India shows no part-wise rows. Review or enter the assessment items in Chrome.",
            matches=rows_present,
        )


async def _fill_amounts(page, data, log, defaults, delay_ms, stop_cb):
    for field, selector, label in (
        ("net_salvage", "input#netSlavage", "Net Salvage"),
        ("less_other_deductions", "input#lessOtherDeductions", "Other Deductions"),
        ("towing_additional_charges", "input#towingCharges", "Towing Charges"),
        ("nil_depreciation_amount", "input#nilDepreciationCover", "Nil Depreciation Cover Amount"),
        ("engine_protect_amount", "input#engineProtectCover", "Engine Protect Amount"),
        ("consumable_items_amount", "input#consumableItemsCover", "Consumable Items Amount"),
        ("key_protect_amount", "input#keyProtectCover", "Key Protect Amount"),
    ):
        if stop_cb():
            return
        value = str(getattr(data, field) or "").strip()
        if value != "0":
            await _fill_text(page, log, selector, label, value, delay_ms)

    if stop_cb():
        return
    towing = 'input#additionalTowingCharges:not(:disabled):not([readonly])'
    if await page.locator(f"{_in_assessment(towing)}:visible").count():
        amount = parse_amount(str(defaults.get("additional_towing_charges") or "0"))
        if amount is None or amount < 0:
            record_review_issue(log, "Additional Towing Charges", "Automation Defaults needs a non-negative amount.")
        else:
            await _fill_text(page, log, towing, "Additional Towing Charges", format(amount, "f"), delay_ms,
                             source="Default", numeric=True)

    if stop_cb():
        return
    reinspection = "select#whetherReinspectionRequired"
    if await page.locator(f"{_in_assessment(reinspection)}:visible").count():
        await _select(page, log, reinspection, "Whether Re-Inspection Required?",
                      "Yes" if reinspection_document(data) else "No", delay_ms, source="Folder scan")

    if not stop_cb():
        await _fill_text(page, log, "textarea#recommendations", "Recommendations",
                         str(defaults.get("recommendations") or "Approved"), delay_ms, source="Default")


async def _close_save_confirmation(page, log, *, context="Claim Assessment Next", max_wait_s=5.0):
    return await dismiss_portal_popup(
        page, log, max_wait_s=max_wait_s, context=context, expected_message=_SAVE_CONFIRMED,
    )


async def _wait_for_assessment_form(page, log, recovery, stop_cb):
    if await page.locator(_BLOCKING_DIALOGS).count():
        await _close_save_confirmation(page, log, context="Opening Claim Assessment", max_wait_s=1)

    async def form_ready():
        return (not await page.locator(_BLOCKING_DIALOGS).count()
                and await page.locator(_FORM_READY).first.is_visible()
                and (recovery is None or await recovery._same_step(page, "three")))

    if await wait_until_ready(form_ready, seconds=_FORM_LOAD_TIMEOUT, stopped=stop_cb):
        return True
    if stop_cb():
        return False

    reason = ("A New India message is covering the form."
              if await page.locator(_BLOCKING_DIALOGS).count() else "The Claim Assessment form is still loading.")
    if recovery is None:
        record_review_issue(log, "Open Claim Assessment", reason)
        return False
    return await recovery.pause(
        page, log, "Open Claim Assessment", reason, ready=form_ready, require_original=True,
        instruction="Wait for Claim Assessment to open in Chrome and close any portal message, then click Continue here.",
    )


async def _advance_assessment(page, log, stop_cb):
    recovery = current_recovery.get()
    if recovery is not None:
        return await recovery.advance_next(
            page, log, _NEXT, source="three", destination="four", title="Document Upload",
            button_text="Next", after_click=lambda: _close_save_confirmation(page, log), confirm_before_transition=True,
        )

    button = page.locator(f"{_NEXT}:visible").filter(has_text=re.compile(r"^\s*Next\s*$", re.I))
    try:
        await button.click(timeout=5000)
        await _close_save_confirmation(page, log)
    except Exception:
        record_review_issue(log, "Next", "App3 could not click Next. Check the Claim Assessment page in Chrome.")
        return False

    async def opened_document_upload():
        return await page.evaluate(_TAB_STATE) == "four" and not await page.locator(_BLOCKING_DIALOGS).count()

    if await wait_until_ready(opened_document_upload, seconds=5, stopped=stop_cb):
        return True
    record_review_issue(log, "Next", "New India did not open Document Upload.")
    return False


async def fill_claim_assessment_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb():
        return False

    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))
    if isinstance(log, AutomationLogger):
        log.section = "Claim Assessment"
        log.info("Filling Claim Assessment.")
        log.indent()

    try:
        recovery = current_recovery.get()
        if recovery is not None and not await recovery._same_step(page, "three"):
            return await _advance_assessment(page, log, stop_cb)
        if not await _wait_for_assessment_form(page, log, recovery, stop_cb) or stop_cb():
            return False
        await _fill_invoice_fields(page, data, log, defaults, field_delay_ms, stop_cb)
        for primary in (True, False):
            if stop_cb():
                return False
            await _fill_estimate(page, log, data, field_delay_ms, stop_cb, primary=primary)

        if stop_cb():
            return False
        painting = 'select[name^="Painting work details"]'
        raw = str(data.painting_work_details or "").strip()
        if raw and await page.locator(f"{_in_assessment(painting)}:visible").count():
            normalized = raw.casefold()
            value = "Break Up" if any(term in normalized for term in ("break", "labor", "labour")) else raw
            if "consol" in normalized:
                value = "Consolidated"
            await _select(page, log, painting, "Painting Work Details", value, field_delay_ms, source="Excel", index=0)

        await _fill_delivery_order_fields(page, data, log, field_delay_ms, stop_cb)
        await _fill_amounts(page, data, log, defaults, field_delay_ms, stop_cb)
        if stop_cb():
            return False
        await _review_part_wise_assessment(page, log)
        return await _advance_assessment(page, log, stop_cb)
    finally:
        if isinstance(log, AutomationLogger):
            log.outdent()
