"""Fill the active New India Claim Assessment page, then review it at Next."""

import asyncio
import json
import os
import re
from contextlib import suppress

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger
from app.data.data_model import ClaimData
from app.portals.newindia.automation.maruti_rows import (
    ROWS as _MARUTI_ROWS,
    add_row,
    assign_existing_rows,
    dealer_not_allowed,
    dealer_row_problems,
    fill_item,
    mark_dealer_group,
    read_maruti_items,
    row_problems,
    row_snapshot,
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.portals.newindia.automation.recovery import _BLOCKING_DIALOGS, _TAB_STATE, current_recovery
from app.portals.newindia.automation.ui_utils import (
    CHANNEL_NON_TIE_UP,
    _JS_FIELD_STATE,
    _JS_TRIGGER_ELEMENT_CHANGE,
    _text_matches_field,
    click_radio_with_delay,
    fill_input_with_delay,
    open_additional_section,
    record_additional_issue as record_review_issue,
    resolve_newindia_channel,
    select_dropdown_with_delay,
    update_field_hud,
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
_MARUTI_HEADER_SAVE = (
    'button#saveClaimAssesment[data-ng-click*="saveDetailsMaruti("], '
    'button#saveClaimAssesment[ng-click*="saveDetailsMaruti("]'
)
_MARUTI_EXTRA_SAVE = (
    'button#saveClaimAssesment[data-ng-click*="saveMarutiExtraDeatils("], '
    'button#saveClaimAssesment[ng-click*="saveMarutiExtraDeatils("]'
)
_MARUTI_SAVE_CONFIRMED = re.compile(
    r"\A\s*(?![\s\S]*\b(?:not|cannot|unable|failed|failure|invalid|error|rejected|"
    r"unsuccessful|mandatory|required|please\s+(?:enter|select|fill))\b)"
    r"[\s\S]*\b(?:saved|updated|submitted|success|successfully|draft)\b",
    re.I,
)
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
_MARUTI_DEALER_GROUP_SIZE = 20

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


async def _close_maruti_action_popup(page: Page, log, *, context: str, max_wait_s: float = 4.0) -> tuple[bool, str]:
    detail: dict = {}
    await dismiss_portal_popup(
        page, log, max_wait_s=max_wait_s, context=context,
        expected_message=_MARUTI_SAVE_CONFIRMED, detail_out=detail,
    )
    if not await page.locator(_BLOCKING_DIALOGS).count():
        return True, ""
    body = " ".join(str(detail.get("body") or "").split())[:160]
    return False, body or f"New India showed a message after {context}. Review Chrome and continue."


async def _click_maruti_button(
    page: Page, log, button, label: str, *, context: str, stop_cb, wait_enabled_s: float = 3.0,
) -> bool:
    recovery = current_recovery.get()
    if recovery is not None:
        await recovery.wait_if_manually_paused(page, log)
    deadline = asyncio.get_running_loop().time() + wait_enabled_s
    ready = False
    while not stop_cb():
        with suppress(Exception):
            if await button.count() and await button.is_visible() and not await button.is_disabled():
                ready = True
                break
        if asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.25)

    if stop_cb():
        return False

    hud_counts = dict(
        filled=getattr(recovery, "fields_filled", 0) if recovery is not None else 0,
        failed=getattr(recovery, "fields_failed", 0) if recovery is not None else 0,
        skipped=getattr(recovery, "fields_skipped", 0) if recovery is not None else 0,
    )
    if not ready:
        record_review_issue(log, label, f"New India did not enable the {label} button.")
        await update_field_hud(page, "Claim Assessment", label, "error", **hud_counts)
        return False

    try:
        await update_field_hud(page, "Claim Assessment", label, "active", **hud_counts)
        await button.scroll_into_view_if_needed()
        await button.click(timeout=5000)
    except Exception:
        record_review_issue(log, label, f"App3 could not click {label} in Chrome.")
        await update_field_hud(page, "Claim Assessment", label, "error", **hud_counts)
        return False

    ok, err_msg = await _close_maruti_action_popup(page, log, context=context)
    if not ok:
        record_review_issue(log, label, err_msg)
        await update_field_hud(page, "Claim Assessment", label, "error", **hud_counts)
        return False

    await update_field_hud(page, "Claim Assessment", label, "ok", **hud_counts)
    if isinstance(log, AutomationLogger):
        log.success(f"{label} completed.")
    else:
        log(f"  [OK] {label} completed.")
    return True


async def _fill_nil_depreciation_radio(page: Page, data: ClaimData, log, delay_ms: int) -> None:
    radios = page.locator(_in_assessment(
        'input[type="radio"][name="Nil Depreciation"]:visible, '
        'input[type="radio"][data-ng-model$=".nilDepreciation"]:visible'
    ))
    if not await radios.count():
        return

    raw = str(getattr(data, "nil_depreciation", "") or "").strip().lower()
    if raw in {"yes", "y"}:
        code, display = "Y", "Yes"
    elif raw in {"no", "n"}:
        code, display = "N", "No"
    else:
        msg = "Nil Depreciation (Yes/No) was not found in Excel. Select or verify Yes/No in Chrome."
        if isinstance(log, AutomationLogger):
            log.warning(msg)
        else:
            log(f"  [WARN] {msg}")
        record_review_issue(log, "Nil Depreciation", msg)
        return

    radio_name = (await radios.first.get_attribute("name")) or "Nil Depreciation"
    scope = page.locator(_TAB)
    named_target = scope.locator(f'input[type="radio"][name={json.dumps(radio_name)}][value={json.dumps(code)}]')
    try:
        if await named_target.count() == 1:
            await click_radio_with_delay(
                page, radio_name, code, "Nil Depreciation", log, delay_ms, source="Excel", scope=scope,
            )
            return
        fallback_target = scope.locator(
            f'input[type="radio"][data-ng-model$=".nilDepreciation"][value={json.dumps(code)}]:visible'
        ).first
        await fallback_target.scroll_into_view_if_needed()
        if not await fallback_target.is_checked():
            await fallback_target.click(timeout=3000)
            with suppress(Exception):
                await fallback_target.evaluate(_JS_TRIGGER_ELEMENT_CHANGE, timeout=1500)
        if not await fallback_target.is_checked():
            raise RuntimeError("Nil Depreciation radio stayed unchecked")
        if isinstance(log, AutomationLogger):
            log.field_filled("Nil Depreciation", display, source="Excel")
    except Exception:
        record_review_issue(log, "Nil Depreciation", f"Could not select '{display}' for Nil Depreciation in Chrome.")


async def _fill_invoice_fields(page, data, log, defaults, delay_ms, stop_cb, *, is_maruti: bool = False):
    workshop = 'select[data-ng-model$=".isWorkshopGstRegistered"], select#isWorkshopGstRegistered'
    if await page.locator(f"{_in_assessment(workshop)}:visible").count():
        # One GST amount belongs to the first invoice.
        await _select(page, log, workshop, "Whether the Workshop is GST Registered",
                      workshop_gst_registered(data.workshop_gst_amount), delay_ms,
                      source="Excel GST amount" if data.workshop_gst_amount else "GST amount absent", index=0)

    if stop_cb():
        return

    count = await page.locator(f"{_in_assessment(_PAYMENT_INVOICE)}:visible").count()
    for index in range(count):
        if stop_cb():
            return
        label = "Payment Invoice in NIA Name?"
        if count > 1:
            label = f"Invoice {index + 1} / {label}"
        await _select(page, log, _PAYMENT_INVOICE, label, str(defaults.get("payment_invoice_in_company_name") or "Yes"),
                      delay_ms, source="Default", index=index)

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

    if stop_cb():
        return
    await _fill_nil_depreciation_radio(page, data, log, delay_ms)
    if is_maruti and not stop_cb():
        save_btn = page.locator(f"{_in_assessment(_MARUTI_HEADER_SAVE)}:visible").first
        await _click_maruti_button(
            page, log, save_btn, "Claim Assessment Save", context="Header Save", stop_cb=stop_cb,
        )


async def _fill_estimate(page, log, data, delay_ms, stop_cb, *, primary):
    kind = "Primary" if primary else "Supplementary"
    label = f"{kind} Assessment Excel"
    name = "Is there any primary estimate" if primary else "Is there any supplementary estimate"
    dropdown = _PRIMARY_ESTIMATE if primary else f'select[name^="{name}"]'
    target = page.locator(f"{_in_assessment(dropdown)}:visible").first
    if not await target.count():
        return

    path = data.assessment_files.get("assessment_excel" if primary else "estimate_excel", "")
    preparation_error = getattr(data, "_newindia_primary_assessment_error", "")
    if primary and not path and preparation_error:
        record_review_issue(log, label, preparation_error)
        return
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


async def _fill_additional_towing(page, log, defaults, delay_ms):
    towing = 'input#additionalTowingCharges:not(:disabled):not([readonly])'
    if await page.locator(f"{_in_assessment(towing)}:visible").count():
        amount = parse_amount(str(defaults.get("additional_towing_charges") or "0"))
        if amount is None or amount < 0:
            record_review_issue(log, "Additional Towing Charges", "Automation Defaults needs a non-negative amount.")
        else:
            await _fill_text(page, log, towing, "Additional Towing Charges", format(amount, "f"), delay_ms,
                             source="Default", numeric=True)


async def _fill_reinspection(page, data, log, delay_ms):
    reinspection = "select#whetherReinspectionRequired"
    if await page.locator(f"{_in_assessment(reinspection)}:visible").count():
        await _select(page, log, reinspection, "Whether Re-Inspection Required?",
                      "Yes" if reinspection_document(data) else "No", delay_ms, source="Folder scan")


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
    await _fill_additional_towing(page, log, defaults, delay_ms)
    if stop_cb():
        return
    await _fill_reinspection(page, data, log, delay_ms)
    if not stop_cb():
        await _fill_text(page, log, "textarea#recommendations", "Recommendations",
                         str(defaults.get("recommendations") or "Approved"), delay_ms, source="Default")


async def _is_maruti_partwise(page: Page, data: ClaimData | None = None) -> bool:
    if await page.locator(f"{_in_assessment(_PRIMARY_ESTIMATE)}:visible").count():
        return False
    marker = (
        f"{_MARUTI_HEADER_SAVE}, {_MARUTI_EXTRA_SAVE}, "
        'select[data-ng-model$=".vAllowedServiceType"], select#sel1'
    )
    if await page.locator(f"{_in_assessment(marker)}:visible").count():
        return True
    if resolve_newindia_channel(page, data) == CHANNEL_NON_TIE_UP:
        return False
    return bool(
        await page.locator(_in_assessment(".panel-heading:visible"))
        .filter(has_text=re.compile(r"Claim\s+Version", re.I))
        .count()
    )


async def _expand_panel_matching(container, patterns: tuple[re.Pattern[str], ...], label: str, log):
    page = container.page
    with suppress(Exception):
        if await page.locator(_BLOCKING_DIALOGS).count():
            await dismiss_portal_popup(page, log, max_wait_s=1.0)
    panels = container.locator(".panel")
    count = await panels.count()
    for pattern in patterns:
        for idx in range(count):
            panel = panels.nth(idx)
            heading = panel.locator(":scope > .panel-heading").first
            if not await heading.count() or not await heading.is_visible():
                continue
            heading_text = " ".join((await heading.inner_text()).split())
            if not pattern.search(heading_text):
                continue
            collapse = panel.locator(":scope > .panel-collapse").first
            if not await collapse.count():
                continue
            is_open = False
            with suppress(Exception):
                is_open = await collapse.evaluate(
                    "el => el.classList.contains('in') || (el.clientHeight > 0 && window.getComputedStyle(el).display !== 'none')"
                )
            if not is_open:
                toggle = heading.locator("a.accordion-toggle").first
                click_target = toggle if await toggle.count() and await toggle.is_visible() else heading
                with suppress(Exception):
                    await click_target.scroll_into_view_if_needed()
                clicked = False
                with suppress(Exception):
                    await click_target.evaluate("el => el.click()")
                    clicked = True
                if not clicked:
                    with suppress(Exception):
                        await click_target.click(force=True, timeout=2000)

                async def is_expanded():
                    return await collapse.evaluate(
                        "el => el.classList.contains('in') || (el.clientHeight > 0 && window.getComputedStyle(el).display !== 'none')"
                    )

                if not await wait_until_ready(is_expanded, seconds=3):
                    with suppress(Exception):
                        await heading.evaluate("el => el.click()")
                    if not await wait_until_ready(is_expanded, seconds=2):
                        with suppress(Exception):
                            await heading.click(force=True, timeout=1500)
                        await wait_until_ready(is_expanded, seconds=2)
            return collapse
    record_review_issue(log, label, f"App3 could not open '{label}' in Chrome.")
    return None


async def _retry_maruti_not_allowed(select):
    with suppress(Exception):
        value = await select.evaluate("""field => {
            if (field.disabled || !field.getClientRects().length) return null;
            const options = [...field.options].filter(option => !option.matches(':disabled') &&
                (option.value === 'Not Allowed' || option.textContent.trim() === 'Not Allowed'));
            return options.length === 1 ? options[0].value : null;
        }""", timeout=1000)
        if value is not None:
            await select.select_option(value=value, timeout=1500)


async def _retry_maruti_dealer_item(select):
    with suppress(Exception):
        value = await select.evaluate("""field => {
            if (field.disabled || !field.getClientRects().length) return null;
            const validItems = new Set(['labour', 'glass', 'painting', 'plastic', 'metal', 'denting', 'misc', 'spare', 'other']);
            const cur = (field.value || '').trim().toLowerCase();
            if (validItems.has(cur)) return null;
            const options = [...field.options].filter(option => !option.matches(':disabled') &&
                (option.value === 'Spare' || option.textContent.trim() === 'Spare'));
            return options.length === 1 ? options[0].value : null;
        }""", timeout=1000)
        if value is not None:
            await select.select_option(value=value, timeout=1500)


async def _mark_maruti_dealer_rows(page, rows, initial, dealers, log, stop_cb):
    recovery = current_recovery.get()
    pending = [idx for idx in dealers if not dealer_not_allowed(initial[idx])]
    if not pending:
        return

    for start in range(0, len(pending), _MARUTI_DEALER_GROUP_SIZE):
        if stop_cb():
            return
        if recovery is not None:
            await recovery.wait_if_manually_paused(page, log)
        if stop_cb():
            return
        group = pending[start:start + _MARUTI_DEALER_GROUP_SIZE]
        identities = [(idx, initial[idx]["part"], initial[idx]["values"]["description"]) for idx in group]
        with suppress(Exception):
            await mark_dealer_group(rows, identities)

    current = await row_snapshot(rows)
    for idx in pending:
        if stop_cb():
            return
        if idx >= len(current) or dealer_not_allowed(current[idx]):
            continue
        if (current[idx]["added"] or current[idx]["part"] != initial[idx]["part"]
                or current[idx]["values"]["description"] != initial[idx]["values"]["description"]):
            continue
        if recovery is not None:
            await recovery.wait_if_manually_paused(page, log)
        if stop_cb():
            return
        select = rows.nth(idx).locator('select[id="sel1"]:visible')
        if await select.count() == 1:
            await _retry_maruti_not_allowed(select)
        item_select = rows.nth(idx).locator('select[id="vItem"]:visible')
        if await item_select.count() == 1:
            await _retry_maruti_dealer_item(item_select)


async def _open_maruti_pending_assessment(page, log, stop_cb):
    tab = page.locator(_TAB)
    v1_body = await _expand_panel_matching(
        tab,
        (
            re.compile(r"Claim\s+Version\s*1\b.*Primary\s+Estimates|Claim\s+Version\s*1\b(?!\s*:?\s*Sub\s*version)", re.I),
            re.compile(r"Claim\s+Version\b(?!\s*:?\s*Sub\s*version)", re.I),
        ),
        "Claim Version 1 (Primary Estimates)",
        log,
    )
    if v1_body is None or stop_cb():
        return

    sv1_body = await _expand_panel_matching(
        v1_body,
        (re.compile(r"Sub\s*version\s*1\b", re.I), re.compile(r"Sub\s*version\b", re.I)),
        "Claim Version 1 : Subversion 1",
        log,
    )
    if sv1_body is None or stop_cb():
        return

    return await _expand_panel_matching(
        sv1_body,
        (re.compile(r"Assessment\s*1\b.*\bPending\b", re.I),),
        "Assessment 1 (Pending)",
        log,
    )


async def _review_maruti_rows(page, log, recovery, issues_for_table):
    issues = await issues_for_table()
    if not issues:
        return True
    for issue in issues:
        if isinstance(log, AutomationLogger):
            log.warning(issue)
        elif log:
            log(issue)
    if recovery is None:
        return False

    async def ready():
        return (await recovery._same_step(page, "three")
                and not await page.locator(_BLOCKING_DIALOGS).count()
                and not await issues_for_table())

    async def describe():
        return "", "\n".join(await issues_for_table())

    return await recovery.pause(
        page, log, "Review Maruti assessment rows", "\n".join(issues),
        ready=ready, require_original=True, describe=describe,
        instruction="Fix the listed rows in Chrome, then click Continue.",
        confirmation_button="Continue",
    )


async def _save_maruti_draft(page, body, log, stop_cb):
    draft = body.locator(
        'button[data-ng-click*=".saveMarutiAssesment(1,"]:visible, '
        'button[ng-click*=".saveMarutiAssesment(1,"]:visible'
    ).filter(has_text=re.compile(r"^\s*Save as Draft\s*$", re.I))
    expand = body.locator(
        'button[data-ng-click*=".expandMarutiTable("]:visible, '
        'button[ng-click*=".expandMarutiTable("]:visible'
    )
    table = body.locator('table[id="example"]:visible')
    if await draft.count() != 1 or await table.count() != 1 or stop_cb():
        return False
    try:
        original = await table.element_handle(timeout=1500)
    except Exception:
        return False
    if original is None:
        return False
    was_draft = await expand.count() == 1
    try:
        try:
            await draft.click(timeout=3500)
        except Exception:
            # A timed-out click can still reach the portal. Check for confirmation once.
            pass
        if stop_cb():
            return False
        confirmed = re.compile(r"\b(?:saved\s+successfully|successfully\s+saved|saved\s+as\s+draft)\b", re.I)
        outcome = await dismiss_portal_popup(
            page, log, max_wait_s=3, classify=True, context="Maruti Save as Draft",
            expected_message=confirmed, success_message=confirmed,
        )
        if outcome == "success" and not await page.locator(_BLOCKING_DIALOGS).count():
            return True

        async def draft_visible():
            if await page.locator(_BLOCKING_DIALOGS).count() or await expand.count() != 1:
                return False
            return not was_draft or not await original.evaluate("table => table.isConnected")

        return await wait_until_ready(draft_visible, seconds=6, stopped=stop_cb)
    finally:
        with suppress(Exception):
            await original.dispose()


async def _fill_maruti_assessment_rows(page, items, data, defaults, log, stop_cb):
    recovery = current_recovery.get()
    if await page.locator(_BLOCKING_DIALOGS).count():
        if recovery is None:
            return False

        async def message_closed():
            return (await recovery._same_step(page, "three")
                    and not await page.locator(_BLOCKING_DIALOGS).count())

        if not await recovery.pause(
            page, log, "Review Maruti header", "New India is showing a message before row entry.",
            instruction="Review and close the portal message in Chrome, then click Continue.",
            confirmation_button="Continue", ready=message_closed, require_original=True,
        ):
            return False
    body = await _open_maruti_pending_assessment(page, log, stop_cb)
    if body is None or stop_cb():
        return False
    rows = body.locator(_MARUTI_ROWS)
    table = body.locator('table[id="example"]:visible')
    if await table.count() != 1:
        record_review_issue(log, "Part-wise Assessment", "New India did not show a single Pending assessment table.")
        return False

    headers = [re.sub(r"[^a-z]", "", text.casefold()) for text in await table.locator("thead th").all_text_contents()]
    if len(headers) < 15 or headers[1:4] != ["item", "partno", "partdescription"]:
        record_review_issue(log, "Part-wise Assessment", "New India did not show the expected Maruti item columns.")
        return False
    initial = await row_snapshot(rows)
    if any(state["columns"] < 15 for state in initial):
        record_review_issue(log, "Part-wise Assessment", "The visible assessment columns differ from the Maruti table.")
        return False
    assigned, dealers, blanks = assign_existing_rows(initial, items)
    labels = [f"Survey item {idx + 1} ({item.description})" for idx, item in enumerate(items)]

    await _mark_maruti_dealer_rows(page, rows, initial, dealers, log, stop_cb)

    count = len(initial)
    gst_pending = []
    for idx, item in enumerate(items):
        if stop_cb():
            return False
        if idx in assigned:
            continue
        if recovery is not None:
            await recovery.wait_if_manually_paused(page, log)
        if stop_cb():
            return False
        if blanks:
            row_index = blanks.pop(0)
        elif await add_row(body, rows, count, stop_cb):
            row_index = count
            count += 1
        else:
            # A late Add Row must be inspected before any further click.
            break
        assigned[idx] = row_index
        if await fill_item(rows.nth(row_index), item, stop_cb):
            gst_pending.append(row_index)

    if gst_pending:
        async def gst_ready():
            current = await row_snapshot(rows)
            return all(idx < len(current) and parse_amount(current[idx]["values"]["gst"]) is not None
                       for idx in gst_pending)

        await wait_until_ready(gst_ready, seconds=2.5, stopped=stop_cb)

    if recovery is not None:
        await recovery.wait_if_manually_paused(page, log)

    async def issues_for_table():
        current = await row_snapshot(rows)
        dealer_issues = {}
        for idx in dealers:
            state = current[idx] if idx < len(current) else None
            for problem in dealer_row_problems(state):
                dealer_issues.setdefault(problem, []).append(str(idx + 1))
        issues = [
            f"Dealer {'row' if len(numbers) == 1 else 'rows'} {', '.join(numbers)} — {problem}."
            for problem, numbers in dealer_issues.items()
        ]
        matches, _, _ = assign_existing_rows(current, items)
        reserved = set(matches.values())
        for idx, item in enumerate(items):
            row_index = matches.get(idx)
            if row_index is None:
                candidate = assigned.get(idx)
                if (candidate is not None and candidate < len(current)
                        and candidate not in reserved and current[candidate]["added"]):
                    row_index = candidate
                    reserved.add(candidate)
            state = current[row_index] if row_index is not None else None
            problems = row_problems(state, item)
            if problems:
                issues.append(f"{labels[idx]} — " + ", ".join(problems))
        for idx, state in enumerate(current):
            if state["added"] and idx not in reserved:
                issues.append(f"Portal row {idx + 1} — extra or unmatched row. Review it before saving.")
        return issues

    issues = await issues_for_table()
    if issues:
        for issue in issues:
            if isinstance(log, AutomationLogger):
                log.warning(issue)
            elif log:
                log(issue)

    if stop_cb() or (recovery is not None and not await recovery._same_step(page, "three")):
        return False

    # Attempt an opportunistic draft save if the button is present, without blocking
    # or pausing the automation run if the portal does not show an explicit modal.
    with suppress(Exception):
        await _save_maruti_draft(page, body, log, stop_cb)

    return True


async def _fill_maruti_bottom_summary(page: Page, data: ClaimData, log, defaults: dict, delay_ms: int, stop_cb) -> None:
    for field, selector, label in (
        ("net_salvage", "input#netSlavage", "Net Salvage"),
        ("towing_additional_charges", "input#towingCharges", "Towing Charges"),
    ):
        if stop_cb():
            return
        value = str(getattr(data, field) or "").strip()
        if value != "0":
            await _fill_text(page, log, selector, label, value, delay_ms)

    if stop_cb():
        return
    await _fill_additional_towing(page, log, defaults, delay_ms)
    if stop_cb():
        return
    await _fill_text(page, log, "textarea#recommendations", "Recommendations",
                     str(defaults.get("recommendations") or "Approved"), delay_ms, source="Default")
    if stop_cb():
        return
    await _fill_reinspection(page, data, log, delay_ms)
    if stop_cb():
        return
    save_btn = page.locator(f"{_in_assessment(_MARUTI_EXTRA_SAVE)}:visible").first
    await _click_maruti_button(
        page, log, save_btn, "Claim Assessment Details Save", context="Bottom Details Save", stop_cb=stop_cb,
    )


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

        is_maruti = await _is_maruti_partwise(page, data)
        if is_maruti:
            try:
                items = read_maruti_items(
                    data.assessment_files.get("assessment_excel"),
                    source_excel_path=getattr(data, "source_excel_path", None),
                )
            except Exception as exc:
                reason = getattr(data, "_newindia_primary_assessment_error", "") or str(exc)
                record_review_issue(log, "Primary Assessment", reason)
                if recovery is not None:
                    await recovery.pause(
                        page, log, "Primary Assessment needs review", reason,
                        instruction="Stop this run, correct the report or workbook, and rescan the folder.",
                        require_original=True, stop_only=True,
                    )
                return False
        await _fill_invoice_fields(page, data, log, defaults, field_delay_ms, stop_cb, is_maruti=is_maruti)
        if stop_cb():
            return False

        if is_maruti:
            # 1. Fill bottom summary fields (Net Salvage, Towing, Recommendations, Re-Inspection)
            await _fill_maruti_bottom_summary(page, data, log, defaults, 0, stop_cb)
            if stop_cb():
                return False
            # 2. Open accordions and fill rows from Excel
            if not await _fill_maruti_assessment_rows(page, items, data, defaults, log, stop_cb) or stop_cb():
                return False
            # 3. Ensure bottom summary fields remain intact and saved
            await _fill_maruti_bottom_summary(page, data, log, defaults, 0, stop_cb)
            if stop_cb():
                return False
            # 4. Advance to Document Upload via bottom Next button
            return await _advance_assessment(page, log, stop_cb)

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
        return await _advance_assessment(page, log, stop_cb)
    finally:
        if isinstance(log, AutomationLogger):
            log.outdent()
