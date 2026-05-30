# app/portals/oic/automation/assessment_of_loss_module.py
"""
assessment_of_loss_module.py — OIC Assessment of Loss (Step 4) automation.

Fills the subsections of the Assessment of Loss form:
  1. Invoice Section
  2. Excess Section
  3. Salvage Charges Section
  4. Survey Charges Section
  5. Final Recommendation & Declaration

Then clicks "Save and Next" to advance to Document Upload.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults
from app.data.data_model import _parse_amount_for_total

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
    await asyncio.sleep(0.3) # wait for addition / transition


async def _fill_excess_section(page: Page, claim, defaults, log: AutomationLogger, delay: int):
    log.info("▸ Filling Excess Section")

    # Check Excel for imposed excess and voluntary excess.
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

    # ── Portal label mapping ─────────────────────────────────────────────
    # The OIC portal uses specific label text for each excess amount input.
    # Our internal names (from Excel) don't always match the portal labels:
    #   "Imposed Excess"   → portal label: "Imposed Excess Amount"
    #   "Voluntary Excess"  → portal label: "Voluntarily Excess Amount"  (typo in portal)
    #   "Compulsory Excess" → portal label: "Compulsory Excess Amount"   (always present)
    _PORTAL_LABEL_MAP = {
        "Imposed Excess":    "Imposed Excess",
        "Voluntary Excess":  "Voluntarily Excess",
        "Compulsory Excess": "Compulsory Excess",
    }
    portal_label = _PORTAL_LABEL_MAP.get(excess_type, excess_type)

    # 1. Select excess type in dropdown (use portal_label for correct match)
    await select_primeng_dropdown(page, S.SEL_LOSS_EXCESS_DROPDOWN, portal_label, "Excess Dropdown", log, delay_ms=delay)

    # 2. Click Add Excess + button
    log.info(f"   Clicking 'Add Excess +' for {excess_type}")
    await page.locator(S.SEL_LOSS_ADD_EXCESS_BTN).click()
    await asyncio.sleep(0.5)  # Wait for accordion / dynamic subsection to appear and mount

    # 3. Locate the new input field by its portal label text.
    #    All excess inputs share id="amount", so we MUST locate by the
    #    surrounding <label> text to target the correct one.
    input_locator = page.locator(
        "span.p-float-label",
        has=page.locator("label", has_text=portal_label),
    ).locator("input").first

    # Wait for the input to be visible and type value
    try:
        await input_locator.wait_for(state="visible", timeout=5000)
    except Exception:
        # Fallback: try finding by exact label text match
        log.warning(f"   Label '{portal_label}' not found via has_text. Trying text= selector...")
        input_locator = page.locator(
            f"span.p-float-label:has(label:text-is('{portal_label} Amount'))"
        ).locator("input").first
        await input_locator.wait_for(state="visible", timeout=5000)

    await input_locator.scroll_into_view_if_needed()
    await input_locator.focus()

    # PrimeNG components use custom event handlers that do not bind properly
    # with direct page.fill() under instant_fill. We must type character-by-character
    # to trigger all internal value/mask formatting listeners.
    instant_fill, typing_delay = _get_oic_fill_settings()
    delay_to_use = 5 if instant_fill else typing_delay

    await input_locator.fill("")
    for char in str(amount_val):
        await input_locator.press_sequentially(char, delay=delay_to_use)

    # Dispatch change events
    await input_locator.evaluate(
        "el => { el.dispatchEvent(new Event('input', { bubbles: true })); "
        "el.dispatchEvent(new Event('change', { bubbles: true })); "
        "el.dispatchEvent(new Event('blur', { bubbles: true })); }"
    )
    log.info(f"   Successfully filled {excess_type} with amount {amount_val}")
    await asyncio.sleep(0.1)


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

    # 2. Declaration Checkbox (always checked/enabled)
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
        # Wait for file input or something unique to the Document Upload section
        await page.wait_for_selector("input[type='file']", state="visible", timeout=15000)
        log.success("   Document Upload section successfully loaded")
        return True
    except Exception as e:
        log.error(f"   Transition to Document Upload failed or timed out: {e}")
        return False
