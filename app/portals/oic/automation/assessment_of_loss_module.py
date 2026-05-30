# app/portals/oic/automation/assessment_of_loss_module.py
"""
assessment_of_loss_module.py — OIC Assessment of Loss (Step 4) automation.

Fills the subsections of the Assessment of Loss form:
  1. Invoice Section (with Excel-driven Spare Parts & Labour items)
  2. Excess Section
  3. Salvage Charges Section
  4. Survey Charges Section
  5. Final Recommendation & Declaration

Then clicks "Save and Next" to advance to Document Upload.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Callable, List

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults
from app.data.data_model import _parse_amount_for_total
from app.data.oic_assessment_generator import generate_oic_assessment, read_oic_assessment

from app.portals.oic.automation.ui_utils import (
    fill_input_with_delay,
    click_primeng_radio,
    fill_primeng_inputnumber,
    fill_mui_datepicker,
    select_primeng_dropdown,
    capture_error_screenshot,
    _get_oic_fill_settings,
)
from app.portals.oic.automation import selectors as S



# ── Public API ───────────────────────────────────────────────────────────────


async def fill_assessment_of_loss(
    page: Page,
    claim,
    *,
    log: AutomationLogger,
    stop_cb: Callable[[], bool],
    field_delay_ms: int = 30,
) -> bool:
    """Fill the complete Assessment of Loss form (Step 4) on the OIC portal.

    Subsections:
      1. Invoice Section
      2. Excess Section
      3. Salvage Charges
      4. Survey Charges
      5. Final Recommendation & Declaration

    Then clicks "Save and Next".

    Returns True on success, False on failure or stop.
    """
    log.section_start("Assessment of Loss")

    defaults = load_automation_defaults(portal_id="oic")
    delay = field_delay_ms

    try:
        # 1. Invoice Section
        if stop_cb():
            log.warning("Stop requested before Invoice Section.")
            return False
        await _fill_invoice_section(page, claim, defaults, log, delay)

        # 2. Excess Section
        if stop_cb():
            log.warning("Stop requested before Excess Section.")
            return False
        await _fill_excess_section(page, claim, defaults, log, delay)

        # 3. Salvage Charges Section
        if stop_cb():
            log.warning("Stop requested before Salvage Charges Section.")
            return False
        await _fill_salvage_section(page, claim, defaults, log, delay)

        # 4. Survey Charges Section
        if stop_cb():
            log.warning("Stop requested before Survey Charges Section.")
            return False
        expenses_filled = await _fill_survey_charges(page, claim, defaults, log, delay)

        # 5. Final Recommendation & Declaration Section
        if stop_cb():
            log.warning("Stop requested before Final Recommendation & Declaration Section.")
            return False
        await _fill_recommendation_declaration(page, claim, defaults, log, delay, expenses_filled=expenses_filled)

        # 6. Save and Next Button Flow
        if stop_cb():
            log.warning("Stop requested before Save and Next.")
            return False
        if not await _click_save_and_next_button(page, log):
            return False

        log.section_done("Assessment of Loss")
        return True

    except Exception as exc:
        log.error(f"Assessment of Loss failed: {exc}")
        await capture_error_screenshot(page, "assessment_of_loss", log)
        return False


# ── Private Subsection Handlers ──────────────────────────────────────────────


async def _fill_invoice_section(page: Page, claim, defaults, log: AutomationLogger, delay: int):
    log.info("▸ Filling Invoice Section")
    
    # 1. Invoice Number (Optional)
    # OCR is primary source: claim.workshop_invoice_no, then fallback to claim.invoice_no
    inv_no = getattr(claim, "workshop_invoice_no", "") or getattr(claim, "invoice_no", "")
    if inv_no:
        log.info(f"   OCR invoice number detected: '{inv_no}'")
        await fill_input_with_delay(page, S.SEL_LOSS_INV_NO, inv_no, "Invoice Number", log, delay_ms=delay)
    else:
        log.info("   Invoice Number is empty/not found (optional) — skipping")

    # 2. Invoice Date (Mandatory)
    # OCR is primary source: claim.workshop_invoice_date, then fallback to claim.invoice_date
    inv_date = getattr(claim, "workshop_invoice_date", "") or getattr(claim, "invoice_date", "")
    if inv_date:
        log.info(f"   OCR invoice date detected: '{inv_date}'")
        await fill_mui_datepicker(page, S.SEL_LOSS_INV_DATE_LABEL, inv_date, "Invoice Date", log, delay_ms=delay)
    else:
        log.field_failed("Invoice Date", "Missing invoice date (mandatory)")
        raise ValueError("Mandatory Invoice Date is missing")

    # 3. GST Type (Dropdown)
    gst_type = defaults.get("gst_type", "IGST")
    await select_primeng_dropdown(page, S.SEL_LOSS_GST_TYPE_DROPDOWN, gst_type, "GST Type", log, delay_ms=delay)

    # 4. Invoice Amount Without GST (Mandatory, from Excel)
    inv_amt = getattr(claim, "invoice_amount_without_gst", "0")
    await fill_primeng_inputnumber(page, S.SEL_LOSS_INV_AMT_NO_GST, inv_amt, "Invoice Amount Without GST", log, delay_ms=delay)

    # 5. Invoice GST Amount (Mandatory, from Excel)
    gst_amt = getattr(claim, "invoice_gst_amount", "0")
    await fill_primeng_inputnumber(page, S.SEL_LOSS_INV_GST_AMT, gst_amt, "Invoice GST Amount", log, delay_ms=delay)

    # Click Add Invoice +
    log.info("   Clicking 'Add Invoice +' button")
    await page.locator(S.SEL_LOSS_ADD_INV_BTN).click()
    await asyncio.sleep(0.5)  # wait for invoice row + Item Type dropdown to appear

    # Fill invoice items from Excel (Spare Parts + Labour Charges)
    await _fill_invoice_items(page, claim, defaults, log, delay)


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION: OIC Assessment Excel → Re-read → Portal Fill
#
# 1. Generates auto_oic_assessment.xlsx from the source Excel
# 2. Re-reads the generated Excel (source of truth)
# 3. Fills invoice items row-by-row into the OIC portal accordion
#
# Processing order: Glass → Plastic → Metallic Parts → Labour Charges
# New items appear at the TOP of the accordion (newest = .first).
# ─────────────────────────────────────────────────────────────────────────────


async def _type_in_text(
    locator, value: str, label: str, char_delay: int,
    log: AutomationLogger, item_label: str,
) -> None:
    """Clear + type character-by-character for plain text inputs.

    Dispatches input/change/blur events so PrimeNG bindings fire correctly.
    """
    await locator.wait_for(state="visible", timeout=5000)
    await locator.scroll_into_view_if_needed()
    await locator.focus()
    await locator.fill("")
    for ch in str(value):
        await locator.press_sequentially(ch, delay=char_delay)
    await locator.evaluate(
        "el => { "
        "el.dispatchEvent(new Event('input',  { bubbles: true })); "
        "el.dispatchEvent(new Event('change', { bubbles: true })); "
        "el.dispatchEvent(new Event('blur',   { bubbles: true })); "
        "}"
    )
    log.info(f"   [{item_label}] {label} = '{value}'")
    await asyncio.sleep(0.1)


async def _type_in_inputnumber_field(
    page: Page, locator, value: str, label: str, char_delay: int,
    log: AutomationLogger, item_label: str,
) -> None:
    """Clear + type for PrimeNG InputNumber fields.

    Uses triple-click + Ctrl+A + Delete to clear, then types character-by-character.
    """
    await locator.wait_for(state="visible", timeout=5000)
    await locator.scroll_into_view_if_needed()
    await locator.focus()
    await locator.click(click_count=3)
    await asyncio.sleep(0.1)
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.1)
    for ch in str(value):
        await locator.press_sequentially(ch, delay=char_delay)
    await locator.evaluate(
        "el => { "
        "el.dispatchEvent(new Event('input',  { bubbles: true })); "
        "el.dispatchEvent(new Event('change', { bubbles: true })); "
        "el.dispatchEvent(new Event('blur',   { bubbles: true })); "
        "}"
    )
    log.info(f"   [{item_label}] {label} = '{value}' ✅")
    await asyncio.sleep(0.15)


async def _fill_invoice_items(page: Page, claim, defaults: dict, log: AutomationLogger, delay: int) -> None:
    """Fill all invoice items from the OIC assessment Excel (Spare Parts + Labour Charges).

    Steps:
      1. Reuse pre-generated auto_oic_assessment.xlsx if available (from folder scan),
         otherwise generate it now from the source Excel
      2. Re-read the generated Excel (source of truth for portal filling)
      3. Group rows by Item Type and fill portal in order: Glass → Plastic → Metal → Labour
    """
    import os

    # ── 1. Resolve or generate OIC assessment Excel ───────────────────────────
    # Prefer pre-generated file from folder scanning (avoids duplicate generation)
    pre_generated = getattr(claim, "assessment_files", {}).get("oic_assessment_excel", "")
    if pre_generated and os.path.isfile(pre_generated):
        oic_excel_path = pre_generated
        log.info(f"   Using pre-generated OIC assessment Excel: {os.path.basename(oic_excel_path)}")
    else:
        # Fallback: generate now (e.g. folder scan was skipped or file was deleted)
        source_excel = getattr(claim, "source_excel_path", "")
        if not source_excel:
            log.error("   source_excel_path is empty — cannot extract parts/labour data")
            raise ValueError("source_excel_path is not set on claim object")

        output_folder = os.path.dirname(source_excel)
        log.info(f"   No pre-generated OIC Excel found — generating from: {source_excel}")

        try:
            oic_excel_path = generate_oic_assessment(source_excel, output_folder, defaults)
        except FileNotFoundError as e:
            log.error(f"   Source Excel not found: {e}")
            raise

        if not oic_excel_path:
            log.error("   No parts or labour data found in source Excel — generation returned None")
            raise ValueError("No spare parts or labour rows found in source Excel")

        log.info(f"   Generated OIC assessment Excel: {os.path.basename(oic_excel_path)}")

    # ── 2. Re-read from generated Excel (source of truth) ─────────────────────
    log.info(f"   Re-reading OIC assessment Excel for portal filling...")
    try:
        oic_rows = read_oic_assessment(oic_excel_path)
    except FileNotFoundError as e:
        log.error(f"   Generated OIC Excel not found: {e}")
        raise

    if not oic_rows:
        log.error("   OIC assessment Excel has no data rows — cannot fill invoice items")
        raise ValueError("No data rows found in generated OIC assessment Excel")

    log.info(f"   Re-read {len(oic_rows)} rows from OIC assessment Excel")

    # ── 3. Group by Item Type and fill portal (Glass → Plastic → Metal → Labour) ──
    items_filled = 0

    # Portal fill order: Glass first, then Plastic, then Metallic Parts, then Labour Charge
    _FILL_ORDER = ["Glass", "Plastic", "Metallic Parts", "Labour Charge"]

    for item_type_text in _FILL_ORDER:
        type_rows = [r for r in oic_rows if r["item_type"] == item_type_text]
        if not type_rows:
            continue

        log.info(f"   ── Processing {len(type_rows)} {item_type_text} items ──")

        for idx, row in enumerate(type_rows, 1):
            log.info(
                f"   [{item_type_text} {idx}/{len(type_rows)}] "
                f"'{row['item_sub_type']}' amt={row['item_amount']} est={row['estimated_amount']}"
            )

            await _create_and_fill_item(
                page, log, delay,
                item_type_text=item_type_text,
                sub_type=row["item_sub_type"],
                side_description=row["side_description"],
                item_amount=row["item_amount"],
                igst_rate=row["igst_rate"],
                estimated_amount=row["estimated_amount"],
                hsn_code=row["hsn_code"],
                item_label=f"{item_type_text} #{idx}",
            )
            items_filled += 1

    log.info(f"   ✅ Successfully filled {items_filled} invoice items from OIC assessment Excel")


async def _create_and_fill_item(
    page: Page,
    log: AutomationLogger,
    delay: int,
    *,
    item_type_text: str,
    sub_type: str,
    side_description: str,
    item_amount: str,
    igst_rate: str,
    estimated_amount: str,
    hsn_code: str,
    item_label: str,
) -> None:
    """Create a single invoice item: select Item Type, click Add Item+, fill fields.

    The portal stacks new items at the TOP of the accordion, so the newest
    item is always the FIRST .p-accordion-tab.
    """
    # ── 1. Select Item Type dropdown ──────────────────────────────────────────
    log.info(f"   [{item_label}] Selecting Item Type = '{item_type_text}'")
    item_type_opened = await page.evaluate("""
        () => {
            const allDropdowns = document.querySelectorAll('.p-dropdown');
            for (const dd of allDropdowns) {
                const container = dd.closest('.input-section')
                               || dd.closest('span.p-float-label')
                               || dd.parentElement;
                if (!container) continue;
                const text = (container.textContent || '').toLowerCase();
                // Must contain "item type" but must NOT be the "item sub type" field
                if (text.includes('item type') && !text.includes('sub type')) {
                    dd.click();
                    return true;
                }
            }
            return false;
        }
    """)
    await asyncio.sleep(0.4)

    if not item_type_opened:
        log.warning(f"   [{item_label}] JS label scan could not open Item Type dropdown — trying Playwright fallback")
        item_type_dd = page.locator(
            "div.p-dropdown:has(span.p-dropdown-label:text-is('Item Type'))"
        ).first
        await item_type_dd.scroll_into_view_if_needed()
        await item_type_dd.click()
        await asyncio.sleep(0.4)

    # Pick the matching option from the overlay
    panel = page.locator(".p-dropdown-panel:visible, .p-overlay:visible").last
    items = panel.locator(".p-dropdown-item, li[role='option']")

    # Poll until options load
    for _ in range(10):
        count = await items.count()
        if count > 0:
            first_text = (await items.first.inner_text()).strip().lower()
            if "loading" not in first_text and "fetching" not in first_text:
                break
        await asyncio.sleep(0.3)

    count = await items.count()
    matched = False
    search = item_type_text.strip().lower()
    for i in range(count):
        txt = (await items.nth(i).inner_text()).strip()
        if txt.strip().lower() == search or search in txt.strip().lower():
            await items.nth(i).click()
            matched = True
            log.info(f"   [{item_label}] Item Type = '{txt}' ✓")
            break

    if not matched:
        await page.keyboard.press("Escape")
        log.error(f"   [{item_label}] Could not find '{item_type_text}' in {count} Item Type options")
        raise RuntimeError(f"Item Type '{item_type_text}' not found in dropdown")

    await asyncio.sleep(0.3)

    # ── 2. Click "Add Item +" button ──────────────────────────────────────────
    log.info(f"   [{item_label}] Clicking 'Add Item +'")
    add_item_btn = page.locator(
        "button[aria-label='Add Item +'], "
        "button:has-text('Add Item +')"
    ).first

    clicked = False
    try:
        await add_item_btn.wait_for(state="attached", timeout=5000)
        await add_item_btn.scroll_into_view_if_needed()
        await add_item_btn.click(force=True)
        clicked = True
    except Exception as btn_err:
        log.warning(f"   [{item_label}] force click failed ({btn_err}) — using JS fallback")

    if not clicked:
        result = await page.evaluate("""
            () => {
                const btn = document.querySelector(
                    "button[aria-label='Add Item +'], button.add-item, button.addNew-btn"
                );
                if (btn) { btn.click(); return true; }
                return false;
            }
        """)
        if result:
            log.info(f"   [{item_label}] Add Item + clicked via JS")
        else:
            raise RuntimeError(f"[{item_label}] Add Item + button not found")

    await asyncio.sleep(0.6)  # wait for accordion tab to mount

    # ── 3. Locate the FIRST accordion tab (newest item, appears at TOP) ──────
    item_tab = page.locator(".p-accordion-tab").first
    await item_tab.wait_for(state="visible", timeout=6000)

    # Expand if collapsed
    class_attr = await item_tab.get_attribute("class") or ""
    if "p-accordion-tab-active" not in class_attr:
        log.info(f"   [{item_label}] Accordion is collapsed — expanding")
        await item_tab.locator(".p-accordion-header-link, .p-accordion-header").first.click()
        await asyncio.sleep(0.3)

    content = item_tab.locator(".p-accordion-content").first
    await content.wait_for(state="visible", timeout=5000)

    # ── 4. Fill fields inside the accordion ───────────────────────────────────
    instant_fill, typing_delay = _get_oic_fill_settings()
    char_delay = 5 if instant_fill else typing_delay

    # 4a. Item Sub Type (#itemSubType) — Plain text input
    item_sub_type_input = content.locator("input#itemSubType, input[name='itemSubType']").first
    await _type_in_text(item_sub_type_input, sub_type, "Item Sub Type", char_delay, log, item_label)

    # 4b. Side Description (#sideCode) — PrimeNG dropdown
    side_code_dropdown = content.locator("#sideCode.p-dropdown, div#sideCode").first
    await _select_dropdown_option_from_locator(page, side_code_dropdown, side_description, "Side Description", log, delay)

    # 4c. Item Amount (name="itemAmount") — PrimeNG InputNumber
    item_amt_input = content.locator("input[name='itemAmount'], #itemAmount input").first
    await _type_in_inputnumber_field(page, item_amt_input, item_amount, "Item Amount", char_delay, log, item_label)

    # 4d. IGST Rate (#igstRate) — PrimeNG dropdown
    igst_dropdown = content.locator("#igstRate.p-dropdown, div#igstRate").first
    await _select_igst_rate(page, igst_dropdown, igst_rate, log, delay)

    # 4e. Estimated Amount (name="estimatedAmount") — PrimeNG InputNumber
    est_input = content.locator("input[name='estimatedAmount'], #estimatedAmount input").first
    await _type_in_inputnumber_field(page, est_input, estimated_amount, "Estimated Amount", char_delay, log, item_label)

    # 4f. HSN Code (#hsnCode) — Plain text input
    hsn_input = content.locator("input#hsnCode, input[name='hsnCode']").first
    await _type_in_text(hsn_input, hsn_code, "HSN Code", char_delay, log, item_label)

    await asyncio.sleep(0.3)
    log.info(f"   [{item_label}] ✅ Item filled successfully")


async def _select_dropdown_option_from_locator(
    page: Page,
    dropdown_locator,
    option_text: str,
    label: str,
    log: AutomationLogger,
    delay: int,
    *,
    attempts: int = 3,
) -> None:
    search = str(option_text).strip().lower()
    last_count = 0

    for attempt in range(1, attempts + 1):
        await dropdown_locator.wait_for(state="visible", timeout=5000)
        await dropdown_locator.scroll_into_view_if_needed()
        await dropdown_locator.click(force=True)

        panel = page.locator(".p-dropdown-panel:visible, .p-overlay:visible").last
        items = panel.locator(".p-dropdown-item, li[role='option']")

        for _ in range(12):
            await asyncio.sleep(0.25)
            last_count = await items.count()
            if last_count == 0:
                continue
            first_text = (await items.first.inner_text()).strip().lower()
            if (
                "loading" not in first_text
                and "fetching" not in first_text
                and not (last_count == 1 and "no result" in first_text)
            ):
                break

        for i in range(last_count):
            item = items.nth(i)
            item_text = (await item.inner_text()).strip()
            item_search = item_text.lower()
            if search == item_search or search in item_search or item_search in search:
                await item.click()
                await asyncio.sleep(0.3)
                await _commit_dropdown_change(dropdown_locator)
                if await _dropdown_has_value(dropdown_locator, option_text):
                    if hasattr(log, "field_selected"):
                        log.field_selected(label, item_text)
                    else:
                        log.info(f"   {label} selected -> '{item_text}'")
                    state = await _dropdown_state(dropdown_locator)
                    log.info(f"   {label} state -> {_dropdown_state_summary(state)}")
                    await asyncio.sleep(delay / 1000.0)
                    return
                state = await _dropdown_state(dropdown_locator)
                log.warning(
                    f"   {label}: clicked '{item_text}' but value did not stick; "
                    f"{_dropdown_state_summary(state)}; retrying"
                )
                break

        await page.keyboard.press("Escape")
        if attempt < attempts:
            log.warning(
                f"   {label}: option '{option_text}' not available yet "
                f"({last_count} options); retrying"
            )
            await asyncio.sleep(0.4)

    raise RuntimeError(f"{label}: option '{option_text}' not found in {last_count} dropdown options")


async def _select_igst_rate(page: Page, dropdown_locator, rate_text: str, log: AutomationLogger, delay: int) -> None:
    """Select OIC Glass-row IGST using the portal-recorded exact option flow."""
    last_error = None
    for attempt in range(1, 4):
        try:
            await dropdown_locator.wait_for(state="visible", timeout=5000)
            await dropdown_locator.scroll_into_view_if_needed()
            await dropdown_locator.click(force=True)

            option = page.get_by_role("option", name=str(rate_text), exact=True).last
            await option.wait_for(state="visible", timeout=3500)
            await option.click()
            await asyncio.sleep(0.35)
            await _commit_dropdown_change(dropdown_locator)

            if await _dropdown_has_value(dropdown_locator, rate_text):
                if hasattr(log, "field_selected"):
                    log.field_selected("IGST Rate", rate_text)
                else:
                    log.info(f"   IGST Rate selected -> '{rate_text}'")
                state = await _dropdown_state(dropdown_locator)
                log.info(f"   IGST Rate state -> {_dropdown_state_summary(state)}")
                await asyncio.sleep(delay / 1000.0)
                return

            state = await _dropdown_state(dropdown_locator)
            log.warning(
                f"   IGST Rate: exact option click did not stick on attempt {attempt}; "
                f"{_dropdown_state_summary(state)}"
            )
        except Exception as exc:
            last_error = exc
            log.warning(f"   IGST Rate: exact role selection attempt {attempt} failed ({exc})")

        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await asyncio.sleep(0.4)

    log.warning(f"   IGST Rate: exact role flow failed; trying generic dropdown fallback ({last_error})")
    await _select_dropdown_option_from_locator(page, dropdown_locator, rate_text, "IGST Rate", log, delay)
    await _commit_dropdown_change(dropdown_locator)
    if not await _dropdown_has_value(dropdown_locator, rate_text):
        state = await _dropdown_state(dropdown_locator)
        raise RuntimeError(f"IGST Rate: '{rate_text}' not selected after fallback; {_dropdown_state_summary(state)}")


async def _commit_dropdown_change(dropdown_locator) -> None:
    await dropdown_locator.evaluate(
        """root => {
            const nodes = [
                root,
                root.querySelector("input[readonly]"),
                root.querySelector("select")
            ].filter(Boolean);
            for (const node of nodes) {
                node.dispatchEvent(new Event('input', { bubbles: true }));
                node.dispatchEvent(new Event('change', { bubbles: true }));
                node.dispatchEvent(new Event('blur', { bubbles: true }));
            }
        }"""
    )


async def _dropdown_state(dropdown_locator) -> dict:
    try:
        return await dropdown_locator.evaluate(
            """root => {
                const label = root.querySelector('.p-dropdown-label, span[data-pc-section="input"]');
                const hiddenInput = root.querySelector('input[readonly]');
                const select = root.querySelector('select');
                const expandedNode = root.querySelector('[aria-expanded]');
                const selected = select && select.selectedOptions && select.selectedOptions.length
                    ? select.selectedOptions[0]
                    : null;
                return {
                    label: (label && label.textContent || '').trim(),
                    hiddenInput: (hiddenInput && hiddenInput.value || '').trim(),
                    selectValue: (select && select.value || '').trim(),
                    selectedText: (selected && selected.textContent || '').trim(),
                    filled: root.classList.contains('p-inputwrapper-filled'),
                    expanded: expandedNode ? (expandedNode.getAttribute('aria-expanded') || '') : ''
                };
            }"""
        )
    except Exception:
        return {}


def _dropdown_state_summary(state: dict) -> str:
    return (
        f"label='{state.get('label', '')}', "
        f"hidden='{state.get('hiddenInput', '')}', "
        f"selected='{state.get('selectedText', '')}', "
        f"value='{state.get('selectValue', '')}', "
        f"filled={state.get('filled', False)}"
    )


async def _dropdown_has_value(dropdown_locator, expected_text: str) -> bool:
    expected = str(expected_text).strip().lower()
    state = await _dropdown_state(dropdown_locator)
    for value in state.values():
        if expected and expected in str(value).strip().lower():
            return True

    probes = [
        ".p-dropdown-label",
        "span[data-pc-section='input']",
        "input[readonly]",
        "select",
    ]
    for selector in probes:
        try:
            probe = dropdown_locator.locator(selector).first
            if await probe.count() == 0:
                continue
            text = ""
            try:
                text = (await probe.inner_text(timeout=500)).strip()
            except Exception:
                pass
            if not text:
                try:
                    text = (await probe.input_value(timeout=500)).strip()
                except Exception:
                    pass
            if expected and expected in text.lower():
                return True
        except Exception:
            continue
    return False


async def _fill_inputnumber_locator(page: Page, input_locator, value: str, label: str, log: AutomationLogger, delay: int) -> None:
    await input_locator.wait_for(state="visible", timeout=8000)
    await input_locator.scroll_into_view_if_needed()
    await input_locator.focus()
    await input_locator.click(click_count=3)
    await asyncio.sleep(0.1)
    await input_locator.press("Control+a")
    await input_locator.press("Delete")
    await asyncio.sleep(0.1)

    instant_fill, typing_delay = _get_oic_fill_settings()
    delay_to_use = 5 if instant_fill else typing_delay
    for ch in str(value):
        await input_locator.press_sequentially(ch, delay=delay_to_use)

    await input_locator.evaluate(
        "el => { "
        "el.dispatchEvent(new Event('input',  { bubbles: true })); "
        "el.dispatchEvent(new Event('change', { bubbles: true })); "
        "el.dispatchEvent(new Event('blur',   { bubbles: true })); }"
    )
    await asyncio.sleep(0.2)

    actual_value = await input_locator.input_value()
    clean_actual = actual_value.replace(",", "").replace("₹", "").strip() if actual_value else ""
    expected = str(value)
    if not clean_actual or clean_actual != expected:
        log.warning(f"   {label}: keyboard entry did not stick, applying native value setter")
        await input_locator.evaluate(
            """(el, expectedValue) => {
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(el, expectedValue);
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""",
            expected,
        )

    log.info(f"   {label} = {value} ✅")
    await asyncio.sleep(delay / 1000.0)


async def _click_add_excess_button(page: Page, log: AutomationLogger) -> None:
    clicked_info = await page.evaluate("""
        () => {
            const normalize = (text) => (text || '').replace(/\\s+/g, '').toLowerCase();
            const isVisible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
            const isEnabled = (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true';
            const isAddExcess = (button) => {
                const text = normalize(button.textContent);
                const aria = normalize(button.getAttribute('aria-label'));
                return (text.includes('addexcess') || aria.includes('addexcess'))
                    && !text.includes('addexpenses')
                    && !aria.includes('addexpenses');
            };
            const chooseVisible = (buttons) => buttons.find(
                (button) => isVisible(button) && isEnabled(button) && isAddExcess(button)
            );
            const excessDropdown = document.querySelector('#excess');
            if (excessDropdown) {
                let root = excessDropdown.closest('.input-section') || excessDropdown.parentElement;
                for (let depth = 0; root && depth < 8; depth += 1, root = root.parentElement) {
                    const buttons = Array.from(root.querySelectorAll('button'));
                    const exact = chooseVisible(buttons);
                    if (exact) {
                        exact.click();
                        return { clicked: true, method: 'scoped-exact', text: exact.textContent || exact.getAttribute('aria-label') || '' };
                    }
                    const visibleEnabled = buttons.filter((button) => isVisible(button) && isEnabled(button));
                    if (visibleEnabled.length === 1 && depth <= 3) {
                        visibleEnabled[0].click();
                        return { clicked: true, method: 'scoped-single', text: visibleEnabled[0].textContent || visibleEnabled[0].getAttribute('aria-label') || '' };
                    }
                }
            }
            const globalExact = chooseVisible(Array.from(document.querySelectorAll('button')));
            if (globalExact) {
                globalExact.click();
                return { clicked: true, method: 'global-exact', text: globalExact.textContent || globalExact.getAttribute('aria-label') || '' };
            }
            return { clicked: false, method: 'not-found', text: '' };
        }
    """)
    if clicked_info.get("clicked"):
        log.info(
            f"   Add Excess + clicked ({clicked_info.get('method')}: "
            f"{str(clicked_info.get('text') or '').strip()})"
        )
        await asyncio.sleep(0.8)
        return

    try:
        add_btn = page.get_by_role("button", name=re.compile(r"^\s*Add\s+Excess\s*\+\s*$", re.IGNORECASE)).last
        await add_btn.wait_for(state="visible", timeout=3000)
        await add_btn.scroll_into_view_if_needed()
        await add_btn.click(force=True)
        log.info("   Add Excess + clicked via role fallback")
    except Exception as btn_err:
        log.warning(f"   Add Excess + role fallback failed ({btn_err}); trying selector fallback")
        clicked = await page.evaluate("""
            () => {
                const normalize = (text) => (text || '').replace(/\\s+/g, '').toLowerCase();
                const btn = Array.from(document.querySelectorAll("button[aria-label='Add Excess +'], button")).find((candidate) => {
                    const text = normalize(candidate.textContent);
                    const aria = normalize(candidate.getAttribute('aria-label'));
                    const visible = !!(candidate.offsetWidth || candidate.offsetHeight || candidate.getClientRects().length);
                    const disabled = candidate.disabled || candidate.getAttribute('aria-disabled') === 'true';
                    return visible && !disabled
                        && (text.includes('addexcess') || aria.includes('addexcess'))
                        && !text.includes('addexpenses')
                        && !aria.includes('addexpenses');
                });
                if (!btn) return false;
                btn.click();
                return true;
            }
        """)
        if not clicked:
            raise RuntimeError("Add Excess + button not found")
        log.info("   Add Excess + clicked via JS")
    await asyncio.sleep(0.8)


async def _find_excess_amount_input(page: Page, portal_label: str, timeout: int = 2500):
    await _expand_excess_accordion_if_needed(page, portal_label)
    locators = [
        page.locator(
            "div.input-section",
            has=page.locator("label", has_text=portal_label),
        ).locator("input.p-inputnumber-input, input[name='amount']").last,
        page.locator(
            "span.p-float-label",
            has=page.locator("label", has_text=portal_label),
        ).locator("input.p-inputnumber-input, input[name='amount'], input").last,
        page.locator(
            f"span.p-float-label:has(label:text-is('{portal_label} Amount'))"
        ).locator("input.p-inputnumber-input, input[name='amount'], input").last,
    ]

    for locator in locators:
        try:
            await locator.wait_for(state="visible", timeout=timeout)
            return locator
        except Exception:
            continue
    raise RuntimeError(f"{portal_label} amount input not visible")


async def _expand_excess_accordion_if_needed(page: Page, portal_label: str) -> None:
    tab = page.locator(
        ".p-accordion-tab",
        has=page.locator(".p-accordion-header", has_text=re.compile(portal_label, re.IGNORECASE)),
    ).last
    try:
        await tab.wait_for(state="visible", timeout=1000)
    except Exception:
        return
    class_attr = await tab.get_attribute("class") or ""
    if "p-accordion-tab-active" not in class_attr:
        await tab.locator(".p-accordion-header-link, .p-accordion-header").first.click()
        await asyncio.sleep(0.3)


async def _ensure_compulsory_excess_and_fill(page: Page, amount_val: str, log: AutomationLogger, delay: int) -> None:
    portal_label = "Compulsory Excess"
    try:
        input_locator = await _find_excess_amount_input(page, portal_label, timeout=1500)
        log.info("   Compulsory Excess field already visible")
    except Exception:
        log.info("   Compulsory Excess field not visible; adding it from Select Excess")
        await _select_dropdown_option_from_locator(
            page,
            page.locator(S.SEL_LOSS_EXCESS_DROPDOWN).first,
            portal_label,
            "Excess Dropdown",
            log,
            delay,
        )
        await _click_add_excess_button(page, log)
        await page.wait_for_timeout(700)
        input_locator = await _find_excess_amount_input(page, portal_label, timeout=6000)

    await _fill_inputnumber_locator(page, input_locator, amount_val, "Compulsory Excess Amount", log, delay)


async def _fill_excess_section(page: Page, claim, defaults, log: AutomationLogger, delay: int):
    log.info("▸ Filling Excess Section")

    try:
        comp_val = _parse_amount_for_total(getattr(claim, "compulsory_excess", "0"))
    except ValueError:
        comp_val = 0

    log.info(f"   Filling Compulsory Excess Amount = {comp_val}")
    await _ensure_compulsory_excess_and_fill(page, str(comp_val), log, delay)

    # ── Imposed & Voluntary Excess (added via Select Excess dropdown + Add Excess+) ──
    try:
        imp_val = _parse_amount_for_total(getattr(claim, "imposed_excess", "0"))
    except ValueError:
        imp_val = 0

    try:
        vol_val = _parse_amount_for_total(getattr(claim, "voluntary_excess", "0"))
    except ValueError:
        vol_val = 0

    # Add Imposed Excess if found
    if imp_val > 0:
        await _add_and_fill_excess(page, "Imposed Excess", str(imp_val), log, delay)

    # Add Voluntary Excess if found
    if vol_val > 0:
        await _add_and_fill_excess(page, "Voluntary Excess", str(vol_val), log, delay)

    if imp_val == 0 and vol_val == 0:
        log.info("   No imposed or voluntary excess found in Excel — skipping excess addition")


async def _add_and_fill_excess(page: Page, excess_type: str, amount_val: str, log: AutomationLogger, delay: int):
    log.info(f"   Adding excess: {excess_type} with amount {amount_val}")

    _PORTAL_LABEL_MAP = {
        "Imposed Excess":    "Imposed Excess",
        "Voluntary Excess":  "Voluntarily Excess",
        "Compulsory Excess": "Compulsory Excess",
    }
    portal_label = _PORTAL_LABEL_MAP.get(excess_type, excess_type)

    # 1. Select excess type in dropdown
    await _select_dropdown_option_from_locator(
        page,
        page.locator(S.SEL_LOSS_EXCESS_DROPDOWN).first,
        portal_label,
        "Excess Dropdown",
        log,
        delay,
    )

    # 2. Click Add Excess + button
    log.info(f"   Clicking 'Add Excess +' for {excess_type}")
    await _click_add_excess_button(page, log)

    # 3. Locate the new input field by its portal label text.
    input_locator = await _find_excess_amount_input(page, portal_label, timeout=6000)
    await _fill_inputnumber_locator(page, input_locator, amount_val, f"{excess_type} Amount", log, delay)
    log.info(f"   Successfully filled {excess_type} with amount {amount_val}")


async def _fill_salvage_section(page: Page, claim, defaults, log: AutomationLogger, delay: int):
    log.info("▸ Filling Salvage Charges Section")
    salvage_amt = getattr(claim, "salvage_amount", "0")
    if (not salvage_amt or salvage_amt == "0") and getattr(claim, "salvage_value", "0") != "0":
        salvage_amt = getattr(claim, "salvage_value", "0")
        
    await fill_primeng_inputnumber(page, S.SEL_LOSS_SALVAGE_AMT_INPUT, salvage_amt, "Salvage Amount", log, delay_ms=delay)


async def _fill_survey_charges(page: Page, claim, defaults, log: AutomationLogger, delay: int) -> bool:
    log.info("▸ Filling Survey Charges Section")

    # 1. Is Survey GST Applicable (always choose NO)
    survey_gst = defaults.get("survey_gst_applicable", "No")
    sel = S.SEL_LOSS_SURVEY_GST_YES if survey_gst.upper() == "YES" else S.SEL_LOSS_SURVEY_GST_NO
    await click_primeng_radio(page, sel, "Is Surveyor GST Applicable", log, delay_ms=delay)

    # 2. License Number (Mandatory)
    lic_no = getattr(claim, "surveyor_license_number", "")
    if not lic_no:
        log.field_failed("Surveyor License Number", "Missing license number (mandatory)")
        raise ValueError("Mandatory Surveyor License Number is missing")
    await fill_input_with_delay(page, S.SEL_LOSS_SURVEY_LICENSE_NO, lic_no, "License Number", log, delay_ms=delay)

    # 3. License Expiry Date (Mandatory)
    lic_exp = getattr(claim, "surveyor_license_expiry_date", "")
    if not lic_exp:
        log.field_failed("Surveyor License Expiry Date", "Missing license expiry date (mandatory)")
        raise ValueError("Mandatory Surveyor License Expiry Date is missing")
    await fill_mui_datepicker(page, S.SEL_LOSS_SURVEY_LICENSE_EXP_LABEL, lic_exp, "License Expiry Date", log, delay_ms=delay)

    # 4. OICL GST Number (Optional)
    oicl_gst = getattr(claim, "oicl_gst_number", "")
    if oicl_gst:
        await fill_input_with_delay(page, S.SEL_LOSS_SURVEY_OICL_GST_NO, oicl_gst, "OICL GST Number", log, delay_ms=delay)
    else:
        log.info("   OICL GST Number is empty/not found (optional) — skipping")

    # 5. Expenses Subsection
    # Internal Excel field names → portal dropdown/accordion label text.
    # The OIC portal uses slightly different text in its accordion headers:
    #   "Daily Allowances" → portal: "Daily Allowance"  (no trailing 's')
    #   "Photo Charges"    → portal: "Photo Charge"     (no trailing 's')
    #   "Other Expenses"   → portal: "Others"           (completely different)
    _EXPENSE_PORTAL_LABEL_MAP = {
        "Traveling Expenses": "Traveling Expenses",
        "Professional Fee":   "Professional Fee",
        "Daily Allowances":   "Daily Allowance",
        "Photo Charges":      "Photo Charge",
        "Other Expenses":     "Others",
    }

    exp_map = {
        "Traveling Expenses": getattr(claim, "traveling_expenses", "0"),
        "Professional Fee":   getattr(claim, "professional_fee", "0"),
        "Daily Allowances":   getattr(claim, "daily_allowance", "0"),
        "Photo Charges":      getattr(claim, "photo_charges", "0"),
        "Other Expenses":     getattr(claim, "surveyor_other_expenses", "0"),
    }

    desc_val = defaults.get("expense_description", "conveyance")
    expenses_filled = False

    for expense_name, raw_amt in exp_map.items():
        try:
            amt = _parse_amount_for_total(raw_amt)
        except ValueError:
            amt = 0

        if amt > 0:
            expenses_filled = True
            portal_label = _EXPENSE_PORTAL_LABEL_MAP.get(expense_name, expense_name)
            log.info(f"   Adding expense: {expense_name} (portal: '{portal_label}') with amount {amt}")

            # Select dropdown using portal label (avoids mismatches like "Others" vs "Other Expenses")
            await select_primeng_dropdown(page, S.SEL_LOSS_EXPENSES_DROPDOWN, portal_label, "Expenses Dropdown", log, delay_ms=delay)

            # Click Add Expenses +
            await page.locator(S.SEL_LOSS_ADD_EXPENSES_BTN).click()
            await asyncio.sleep(0.3)  # Wait for dynamic section/accordion tab to render

            # Fill dynamic accordion section using portal label for the tab locator
            await _fill_dynamic_expense_accordion(page, portal_label, str(amt), desc_val, log, delay)

    return expenses_filled


async def _fill_dynamic_expense_accordion(
    page: Page,
    portal_label: str,  # Portal accordion header text (e.g. 'Daily Allowance', 'Others')
    amount_val: str,
    desc_val: str,
    log: AutomationLogger,
    delay: int,
):
    log.info(f"   Expanding and filling dynamic subsection for: {portal_label}")

    # Locate the accordion tab by its portal header text.
    # Use .last because new tabs are appended — the last one is the one just added.
    tab_locator = page.locator(
        ".p-accordion-tab",
        has=page.locator(".p-accordion-header", has_text=portal_label),
    ).last
    await tab_locator.wait_for(state="visible", timeout=5000)

    # Expand tab if collapsed
    class_attr = await tab_locator.get_attribute("class") or ""
    if "p-accordion-tab-active" not in class_attr:
        log.info(f"   Accordion tab for '{portal_label}' is collapsed — expanding")
        await tab_locator.locator(".p-accordion-header-link").click()
        await asyncio.sleep(0.2)  # Wait for expand animation

    # Locate description and amount inputs inside the expanded tab content
    content = tab_locator.locator(".p-accordion-content").first
    await content.wait_for(state="visible", timeout=5000)

    desc_input = content.locator("input#description, input[name='itemDesc']").first
    amt_input = content.locator("input[name='amount'], input[name='itemAmount'], #itemAmount input").first

    # Fill description
    await desc_input.wait_for(state="visible", timeout=5000)
    await desc_input.scroll_into_view_if_needed()
    await desc_input.focus()
    await desc_input.fill(str(desc_val))
    await desc_input.evaluate("el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); el.dispatchEvent(new Event('blur', { bubbles: true })); }")
    log.field_filled(f"{portal_label} Description", desc_val)

    # Fill amount
    await amt_input.wait_for(state="visible", timeout=5000)
    await amt_input.scroll_into_view_if_needed()
    await amt_input.focus()
    await amt_input.fill(str(amount_val))
    await amt_input.evaluate("el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); el.dispatchEvent(new Event('blur', { bubbles: true })); }")
    log.field_filled(f"{portal_label} Amount", amount_val)

    await asyncio.sleep(0.1)


async def _fill_recommendation_declaration(
    page: Page,
    claim,
    defaults,
    log: AutomationLogger,
    delay: int,
    expenses_filled: bool,
):
    log.info("▸ Filling Final Recommendation & Declaration")

    # 1. Final Recommendation (text, default agree)
    # Only fill if one or more surveyor expenses are filled, otherwise skip it
    if expenses_filled:
        rec_val = defaults.get("final_recommendation", "agree")
        log.info(f"   Surveyor expenses filled → populating Final Recommendation: '{rec_val}'")
        rec_box = page.locator(S.SEL_LOSS_FINAL_REC)
        await rec_box.wait_for(state="visible", timeout=5000)
        await rec_box.scroll_into_view_if_needed()
        await rec_box.focus()
        await rec_box.fill(str(rec_val))
        await rec_box.evaluate("el => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }")
    else:
        log.info("   No surveyor expenses filled → skipping Final Recommendation field")

    # 2. Declaration Checkbox (checked per declaration_checked setting)
    declaration_setting = defaults.get("declaration_checked", "Yes")
    if declaration_setting.strip().lower() != "yes":
        log.info(f"   Declaration checkbox skipped per settings (declaration_checked='{declaration_setting}')")
    else:
        dec_input = page.locator(S.SEL_LOSS_DECLARATION)
        await dec_input.wait_for(state="attached", timeout=5000)

        is_checked = await dec_input.is_checked()
        if not is_checked:
            log.info("   Declaration checkbox is not checked. Checking/enabling it now...")
            clicked_successfully = False

            try:
                # 1. Try robust label click first
                dec_label = page.locator(S.SEL_LOSS_DECLARATION_LABEL)
                await dec_label.wait_for(state="visible", timeout=3000)
                await dec_label.scroll_into_view_if_needed()
                await dec_label.click(timeout=3000)
                clicked_successfully = True
                log.info("   Successfully clicked declaration checkbox label")
            except Exception as label_err:
                log.warning(f"   Robust label click failed or timed out: {label_err}. Trying standard input click fallback.")

            if not clicked_successfully:
                try:
                    # 2. Fallback to standard input element click
                    await dec_input.scroll_into_view_if_needed()
                    await dec_input.click(timeout=3000)
                    clicked_successfully = True
                    log.info("   Successfully clicked declaration checkbox input directly")
                except Exception as input_err:
                    log.warning(f"   Input click fallback failed: {input_err}. Forcing checked state via JS.")

            # 3. Ultimate fallback: Force check state using JS evaluation
            if not clicked_successfully:
                await dec_input.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); }")
                log.info("   Forced checked state on declaration checkbox via JS evaluation")

            # Verify checked state
            await asyncio.sleep(0.3)
            is_checked_now = await dec_input.is_checked()
            if not is_checked_now:
                log.warning("   Declaration checkbox still not checked. Forcing checked state via JS.")
                await dec_input.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); }")
        else:
            log.info("   Declaration checkbox is already checked (enabled)")


async def _click_save_and_next_button(page: Page, log: AutomationLogger) -> bool:
    log.info("▸ Clicking 'Save and Next'")
    btn = page.locator(S.SEL_LOSS_SAVE_AND_NEXT_BTN)
    await btn.wait_for(state="visible", timeout=5000)
    await btn.scroll_into_view_if_needed()
    await btn.click()
    
    # Wait until "Document Upload" section/tab is active/visible
    log.info("   Waiting for 'Document Upload' section to load...")
    try:
        # OIC upload controls are hidden <input type=file> elements; attachment
        # of the first upload-specific input is the reliable transition signal.
        await page.wait_for_selector(S.SEL_UPLOAD_WORKSHOP_ESTIMATE, state="attached", timeout=15000)
        log.success("   Document Upload section successfully loaded")
        return True
    except Exception as e:
        log.error(f"   Transition to Document Upload failed or timed out: {e}")
        await _log_assessment_transition_blockers(page, log)
        await capture_error_screenshot(page, "assessment_next_no_transition", log)
        return False


async def _collect_visible_validation_messages(page: Page, limit: int = 12) -> list[str]:
    messages: list[str] = []
    seen: set[str] = set()
    selectors = (
        ".error-message:visible, "
        ".error-messageSeverity:visible, "
        ".p-error:visible, "
        ".p-message-error:visible, "
        ".p-toast-message-error:visible, "
        "[role='alert']:visible"
    )
    try:
        locs = page.locator(selectors)
        count = await locs.count()
        for i in range(min(count, limit)):
            txt = (await locs.nth(i).inner_text()).strip()
            txt = re.sub(r"\s+", " ", txt)
            if txt and txt not in seen:
                messages.append(txt)
                seen.add(txt)
    except Exception:
        pass
    return messages


async def _log_assessment_transition_blockers(page: Page, log: AutomationLogger) -> None:
    messages = await _collect_visible_validation_messages(page)
    if messages:
        log.warning(f"   Assessment validation messages after Save and Next ({len(messages)}):")
        for msg in messages:
            log.warning(f"     - {msg}")
    else:
        log.warning("   No visible validation message found after Save and Next.")

    try:
        glass_tab = page.locator(
            ".p-accordion-tab",
            has=page.locator(".p-accordion-header", has_text="Glass"),
        ).last
        igst_dropdown = glass_tab.locator("#igstRate.p-dropdown, div#igstRate").first
        if await igst_dropdown.count():
            state = await _dropdown_state(igst_dropdown)
            log.warning(f"   IGST Rate at Save/Next failure -> {_dropdown_state_summary(state)}")
    except Exception:
        pass

    try:
        excess_snapshot = await page.evaluate(
            """() => {
                const rows = [];
                for (const label of Array.from(document.querySelectorAll('label'))) {
                    const text = (label.textContent || '').trim();
                    if (!/excess amount/i.test(text)) continue;
                    const root = label.closest('.input-section') || label.closest('.p-float-label') || label.parentElement;
                    const input = root && root.querySelector('input');
                    rows.push(`${text}: ${input && input.value ? input.value : ''}`.trim());
                }
                return rows;
            }"""
        )
        if excess_snapshot:
            log.warning(f"   Excess amount snapshot -> {'; '.join(excess_snapshot)}")
    except Exception:
        pass
