import asyncio
import re
from playwright.async_api import Page
from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    fill_input_with_delay,
    select_dropdown_with_delay,
    upload_file_via_input,
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup
from app.automation.automation_logger import AutomationLogger




async def _visible_invalid_required_fields(page: Page, limit: int = 8) -> list[str]:
    """Return visible Angular required fields that may block Claim Assessment save."""
    try:
        return await page.evaluate(
            """
            (limit) => Array.from(document.querySelectorAll(
                '.ng-invalid-required[name], [required].ng-invalid[name]'
            ))
            .filter((el) => {
                const style = window.getComputedStyle(el);
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && el.getClientRects().length > 0;
            })
            .map((el) => el.getAttribute('name') || el.id || el.getAttribute('data-ng-model') || el.tagName)
            .filter(Boolean)
            .slice(0, limit)
            """,
            limit,
        )
    except Exception:
        return []


async def _document_upload_ready(page: Page, timeout_ms: int = 5000) -> bool:
    """
    Detect whether the portal has reached the Document Upload tab.

    Uses a tiered selector list: fast checks first (elements that appear as
    soon as the tab loads, before accordions are expanded), then progressively
    deeper ones. Each selector gets at most `timeout_ms` on the first try;
    subsequent selectors use a much shorter 800ms to fail-fast.
    """
    # Tier 1: Elements visible immediately when the Document Upload tab loads
    # (these exist in the DOM and are visible WITHOUT needing accordion expansion)
    fast_selectors = [
        'button[data-ng-click*="uploadFileNonTieUp"]',  # Upload button (always rendered)
        'span.fa-plus-circle[data-ng-click*="addRow"]',  # + Add Row button
        'ng-form[name="mandatoryDocForm"]',              # mandatory form wrapper
    ]
    # Tier 2: Deeper elements that may need accordion to be open
    deep_selectors = [
        'select[id^="docType"]',
        'input[type="file"][id^="chooseFile"]',
        'input[type="file"][id^="mandatoryFiles"]',
    ]

    first = True
    for selector in fast_selectors + deep_selectors:
        try:
            await page.wait_for_selector(
                selector,
                state="attached",  # 'attached' is faster than 'visible' for hidden accordions
                timeout=timeout_ms if first else 800,
            )
            return True
        except Exception:
            pass
        first = False
    return False


async def _click_claim_assessment_next(page: Page, log) -> bool:
    """
    Click the visible Claim Assessment Next button.

    The portal may keep duplicate tab DOM in memory, so first-match selectors and
    document.querySelector can target a hidden button. This helper explicitly
    chooses a visible, enabled docUploadCall button before falling back to DOM JS.
    """
    selector = (
        'button[data-ng-click="surveyorWorklistSurvey.docUploadCall()"], '
        'button[ng-click="surveyorWorklistSurvey.docUploadCall()"], '
        'button[data-ng-click*="docUploadCall"], '
        'button[ng-click*="docUploadCall"]'
    )

    candidates = page.locator(selector).filter(has_text=re.compile(r"\bNext\b", re.IGNORECASE))
    count = await candidates.count()
    if count == 0:
        candidates = page.locator(selector)
        count = await candidates.count()

    last_error = None
    for idx in range(count):
        btn = candidates.nth(idx)
        try:
            if not await btn.is_visible():
                continue
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
            for _ in range(20):
                if not await btn.is_disabled():
                    break
                await asyncio.sleep(0.25)
            if await btn.is_disabled():
                invalid = await _visible_invalid_required_fields(page)
                if isinstance(log, AutomationLogger):
                    log.warning(
                        "Visible Claim Assessment Next button is disabled."
                        + (f" Blocking required fields: {', '.join(invalid)}" if invalid else "")
                    )
                else:
                    log(
                        "   ⚠️ Visible Next button disabled."
                        + (f" Blocking fields: {', '.join(invalid)}" if invalid else "")
                    )
                continue

            try:
                await btn.click(timeout=5000)
            except Exception as click_error:
                last_error = click_error
                await btn.click(timeout=5000, force=True)
            return True
        except Exception as exc:
            last_error = exc

    # DOM fallback: only click a visible enabled button, not querySelector's first match.
    try:
        result = await page.evaluate(
            """
            () => {
                const buttons = Array.from(document.querySelectorAll(
                    'button[data-ng-click*="docUploadCall"], button[ng-click*="docUploadCall"]'
                ));
                const target = buttons.find((btn) => {
                    const style = window.getComputedStyle(btn);
                    const text = (btn.textContent || '').toLowerCase();
                    return text.includes('next')
                        && !btn.disabled
                        && style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && btn.getClientRects().length > 0;
                });
                if (!target) {
                    return { ok: false, reason: 'no visible enabled docUploadCall button' };
                }
                target.scrollIntoView({ block: 'center', inline: 'center' });
                target.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true, view: window }));
                target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
                target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
                target.click();
                return { ok: true, text: target.textContent.trim() };
            }
            """
        )
        if result.get("ok"):
            return True
        if isinstance(log, AutomationLogger):
            log.warning(f"JS Next fallback did not find clickable button: {result.get('reason')}")
        else:
            log(f"   ⚠️ JS Next fallback did not find clickable button: {result.get('reason')}")
    except Exception as exc:
        last_error = exc

    if isinstance(log, AutomationLogger):
        log.error(f"Could not click visible Claim Assessment Next button: {str(last_error)[:140]}")
    else:
        log(f"   ❌ Could not click visible Claim Assessment Next button: {last_error}")
    return False

async def fill_claim_assessment_details(page: Page, data: ClaimData, log, stop_cb, field_delay_ms: int = 600) -> bool:
    if stop_cb(): return False

    _using_structured_log = isinstance(log, AutomationLogger)
    if _using_structured_log:
        log.info("Starting Claim Assessment Details phase...")
        log.indent()
    else:
        log(f"Opening Claim Assessment Details section...")

    # try/finally guarantees log.outdent() always fires (prevents indentation drift
    # if any stop_cb() or navigation failure causes an early return)
    _result = False
    try:
        _result = await _fill_claim_assessment_details_inner(page, data, log, stop_cb, field_delay_ms)
    finally:
        if _using_structured_log:
            log.outdent()  # outdent Section (whichever was open)
            log.outdent()  # outdent main module
    return _result


async def _fill_claim_assessment_details_inner(page, data, log, stop_cb, field_delay_ms):
    """Inner body of fill_claim_assessment_details — called via try/finally wrapper."""

    # 0. Handle Alert Popup (if any)
    await dismiss_portal_popup(page, log, max_wait_s=3.0, context="Claim Assessment Start")

    if stop_cb(): return False

    # Wait for the main panel to be visible to ensure page loaded
    try:
        await page.wait_for_selector('select[data-ng-model*="isPaymentInvoice"]', state="visible", timeout=10000)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.warning(f"Form load timeout: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Claim Assessment form not found or timed out: {e}")

    if stop_cb(): return False

    # 1. Whether Payment invoice is in the name of NIA (Yes/No)
    # Behavior: ALWAYS select YES
    try:
        sel = 'select[data-ng-model*="isPaymentInvoice"]'
        await select_dropdown_with_delay(page, sel, "Yes", "Payment Invoice NIA", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Payment Invoice dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Payment Invoice in NIA Name: {e}")

    if stop_cb(): return False

    # 2. Is GST Applicable
    # Behavior: READONLY, safely skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Is GST Applicable' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Is GST Applicable' (Readonly field).")

    if stop_cb(): return False

    # 3. Vendor/Tax Invoice Date
    try:
        val = getattr(data, 'vendor_invoice_date', '') or ''
        if val:
            val = str(val).strip()
            sel = 'input[data-ng-model*="vendorTaxInvoiceDate"]'
            await fill_input_with_delay(page, sel, val, "Invoice Date", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Vendor Invoice Date missing from data.")
            else:
                log(f"   ⚠️ Vendor/Tax Invoice Date missing (Not extracted from PDF).")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Invoice Date field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Vendor/Tax Invoice Date: {e}")

    if stop_cb(): return False

    # 4. Vendor/Tax Invoice Number
    try:
        val = getattr(data, 'vendor_invoice_number', '') or ''
        if val:
            val = str(val).strip()
            sel = 'input[data-ng-model*="vendorTaxInvoiceNumber"]'
            await fill_input_with_delay(page, sel, val, "Invoice Number", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Vendor Invoice Number missing from data.")
            else:
                log(f"   ⚠️ Vendor/Tax Invoice Number missing (Not extracted from PDF).")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Invoice Number field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Vendor/Tax Invoice Number: {e}")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — PRIMARY ASSESSMENT
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section 1: Primary Assessment")
        log.indent()
    else:
        log("")
        log(f"   ── Section 1: Primary Assessment ──")

    # Field 1: Primary Assessment dropdown → ALWAYS "Yes"
    try:
        sel = 'select[name="Is there any primary estimate"]'
        await select_dropdown_with_delay(page, sel, "Yes", "Primary Assessment", log, field_delay_ms)
        await asyncio.sleep(1.5)  # Wait for conditional sections to appear
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Primary Assessment dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Primary Assessment: {e}")

    if stop_cb(): return False

    # Field 2: Attach Assessment Excel
    assessment_path = data.assessment_files.get("assessment_excel", "")
    if assessment_path:
        await upload_file_via_input(
            page,
            file_input_selector='input#chooseFilePrim',
            file_path=assessment_path,
            label="Assessment Excel",
            log=log,
        )
        try:
            upload_btn = page.locator('button[data-ng-click*="readExcel(invoiceIndex)"], button[name="uploadSupAss0"]').first
            await upload_btn.wait_for(state="visible", timeout=5000)
            if isinstance(log, AutomationLogger):
                log.info("Clicking Primary Assessment Excel Upload button...")
            else:
                log("   ℹ️ Clicking Primary Assessment Excel Upload button...")
            await upload_btn.click()
            # Wait for upload modal to appear and dismiss it (wait up to 8.0 seconds for slower server response)
            await dismiss_portal_popup(page, log, max_wait_s=8.0, context="Assessment Excel")
            await asyncio.sleep(0.5)
            
            if isinstance(log, AutomationLogger):
                log.success("Primary Assessment Excel Uploaded successfully.")
            else:
                log("   ✅ Primary Assessment Excel Uploaded successfully.")
        except Exception as ue:
            if isinstance(log, AutomationLogger):
                log.error(f"Primary Assessment Excel upload failed: {str(ue)[:100]}")
            else:
                log(f"   ⚠️ Primary Assessment Excel upload failed: {str(ue)[:100]}")
    else:
        if isinstance(log, AutomationLogger):
            log.warning("No Primary Assessment Excel found.")
        else:
            log(f"   ⚠️ No assessment Excel file found in folder (expected: assessment.xlsx / primary_assessment.xlsx).")

    if stop_cb(): return False

    # Field 3: Garage Bill dropdown → ALWAYS "Garage Bill" (COMMENTED OUT BY USER REQUEST)
    # try:
    #     sel = 'select#pDocTypeOCR'
    #     await select_dropdown_with_delay(page, sel, "Garage Bill", "Bill Type Dropdown", log, field_delay_ms)
    # except Exception as e:
    #     if isinstance(log, AutomationLogger):
    #         log.error(f"Bill Type dropdown error: {str(e)[:100]}")
    #     else:
    #         log(f"   ⚠️ Error selecting Garage Bill: {e}")
    # 
    # if stop_cb(): return False
    # 
    # # Field 4: Attach Garage Bill (Invoice)
    # invoice_path = data.assessment_files.get("invoice", "")
    # if invoice_path:
    #     await upload_file_via_input(
    #         page,
    #         file_input_selector='input#priOcr',
    #         file_path=invoice_path,
    #         label="Garage Bill PDF",
    #         log=log,
    #     )
    #     try:
    #         pop_btn = page.locator("button[data-ng-click*=\"uploadToOcr\"][data-ng-click*=\"'P'\"]").first
    #         await pop_btn.wait_for(state="visible", timeout=5000)
    #         
    #         # Wait for button to be enabled (Angular digest cycles)
    #         for _ in range(12):
    #             if not await pop_btn.is_disabled():
    #                 break
    #             await asyncio.sleep(0.5)
    #             
    #         if isinstance(log, AutomationLogger):
    #             log.info("Clicking Populate Data button for Garage Bill...")
    #         else:
    #             log("   ℹ️ Clicking Populate Data button for Garage Bill...")
    #         await pop_btn.click()
    #         # Wait for OCR populate modal to appear and dismiss it (handles variable 5 to 15+ seconds wait time)
    #         await dismiss_portal_popup(page, log, max_wait_s=25.0, context="Primary OCR")
    #         await asyncio.sleep(1.0)
    #         
    #         if isinstance(log, AutomationLogger):
    #             log.success("Garage Bill OCR Data Populated successfully.")
    #         else:
    #             log("   ✅ Garage Bill OCR Data Populated successfully.")
    #     except Exception as pe:
    #         if isinstance(log, AutomationLogger):
    #             log.error(f"Garage Bill OCR populate failed: {str(pe)[:100]}")
    #         else:
    #             log(f"   ⚠️ Garage Bill OCR populate failed: {str(pe)[:100]}")
    # else:
    #     if isinstance(log, AutomationLogger):
    #         log.warning("No Garage Bill PDF found.")
    #     else:
    #         log(f"   ⚠️ No invoice file found in folder (expected: invoice.pdf / final_invoice.pdf).")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 2: Supplementary Assessment")
        log.indent()
    else:
        log("")
        log(f"   ── Section 2: Supplementary Assessment ──")

    has_estimate = bool(data.assessment_files.get("estimate_excel", ""))
    supp_value = "Yes" if has_estimate else "No"

    try:
        sel = 'select[name*="Is there any supplementary estimate"]'
        await select_dropdown_with_delay(page, sel, supp_value, "Supplementary Estimate", log, field_delay_ms)
        await asyncio.sleep(1.5)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Supplementary dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Supplementary Estimate: {e}")

    if stop_cb(): return False

    if supp_value == "Yes":
        # Attach Supplementary Estimate Excel
        estimate_path = data.assessment_files.get("estimate_excel", "")
        if estimate_path:
            await upload_file_via_input(
                page,
                file_input_selector='input#chooseFileSup',
                file_path=estimate_path,
                label="Supp Estimate Excel",
                log=log,
            )
            try:
                upload_btn = page.locator('button[data-ng-click*="readExcelSup(invoiceIndex)"]').first
                await upload_btn.wait_for(state="visible", timeout=5000)
                if isinstance(log, AutomationLogger):
                    log.info("Clicking Supp Assessment Excel Upload button...")
                else:
                    log("   ℹ️ Clicking Supp Assessment Excel Upload button...")
                await upload_btn.click()
                # Wait for upload modal to appear and dismiss it (wait up to 8.0 seconds for slower server response)
                await dismiss_portal_popup(page, log, max_wait_s=8.0, context="Supp Excel")
                await asyncio.sleep(0.5)
                
                if isinstance(log, AutomationLogger):
                    log.success("Supp Assessment Excel Uploaded successfully.")
                else:
                    log("   ✅ Supp Assessment Excel Uploaded successfully.")
            except Exception as ue:
                if isinstance(log, AutomationLogger):
                    log.error(f"Supp Assessment Excel upload failed: {str(ue)[:100]}")
                else:
                    log(f"   ⚠️ Supp Assessment Excel upload failed: {str(ue)[:100]}")
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Estimate Excel missing for supplementary phase.")
            else:
                log(f"   ⚠️ Supplementary Estimate set to Yes but no estimate Excel found.")

        if stop_cb(): return False

        # Attach Supplementary Garage Bill (COMMENTED OUT BY USER REQUEST)
        # estimate_inv_path = data.assessment_files.get("estimate_invoice", "")
        # if estimate_inv_path:
        #     sel = 'select#sDocTypeOCR'
        #     await select_dropdown_with_delay(page, sel, "Garage Bill", "Supp Bill Type", log, field_delay_ms)
        # 
        #     await upload_file_via_input(
        #         page,
        #         file_input_selector='input#supOcr',
        #         file_path=estimate_inv_path,
        #         label="Supp Garage Bill",
        #         log=log,
        #     )
        #     await dismiss_portal_popup(page, log, max_wait_s=2.0, context="Supp Garage Bill Attach")
        #     if isinstance(log, AutomationLogger):
        #         log.info("Supplementary Garage Bill attached; skipping Populate Data by design.")
        #     else:
        #         log("   ℹ️ Supplementary Garage Bill attached; skipping Populate Data.")
        # else:
        #     if isinstance(log, AutomationLogger):
        #         log.info("No supplementary invoice found; skipping (Optional).")
        #     else:
        #         log(f"   ℹ️ No estimate invoice file found (optional). Skipping.")
    else:
        if isinstance(log, AutomationLogger):
            log.info("Supplementary estimate skipped.")
        else:
            log(f"   ℹ️ Supplementary Estimate = No. Section complete.")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 3: Painting Charges")
        log.indent()
    else:
        log("")
        log(f"   ── Section 3: Painting Charges ──")

    # Labour Charges — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Labour Charges' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Labour Charges' (Readonly field).")

    # Paint Material Charges — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Paint Material Charges' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Paint Material Charges' (Readonly field).")

    # Painting Work Details — Dropdown from ClaimData
    try:
        raw_val = str(getattr(data, 'painting_work_details', '') or '').strip()
        if raw_val:
            # Normalize: map Excel values to dropdown values
            normalized = raw_val.lower()
            if "break" in normalized or "labor" in normalized or "labour" in normalized:
                dropdown_val = "Break-up"
            elif "consol" in normalized:
                dropdown_val = "Consolidated"
            else:
                dropdown_val = raw_val

            sel = 'select[name*="Painting work details"]'
            await select_dropdown_with_delay(page, sel, dropdown_val, "Painting Work Details", log, field_delay_ms)
            await asyncio.sleep(1.0)  # Wait for painting table to update
        else:
            if isinstance(log, AutomationLogger):
                log.warning("Painting details missing from data.")
            else:
                log(f"   ⚠️ Painting Work Details not found in ClaimData. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Painting details dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Painting Work Details: {e}")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 4: Delivery Order Details")
        log.indent()
    else:
        log("")
        log(f"   ── Section 4: Delivery Order Details ──")

    # Net Salvage — Optional
    try:
        val = str(getattr(data, 'net_salvage', '') or '').strip()
        if val and val != "0":
            sel = 'input#netSlavage'
            await fill_input_with_delay(page, sel, val, "Net Salvage", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Net Salvage is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Net Salvage = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Net Salvage field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Net Salvage: {e}")

    if stop_cb(): return False

    # Net Salvage to map with Invoice — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Net Salvage Map' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Net Salvage to map with Invoice' (Readonly field).")

    # Less Compulsory Excess — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Compulsory Excess' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Less Compulsory Excess' (Readonly field).")

    # Less Voluntary Excess — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Voluntary Excess' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Less Voluntary Excess' (Readonly field).")

    # Less Any Other Deductions — Optional
    try:
        val = str(getattr(data, 'less_other_deductions', '') or '').strip()
        if val and val != "0":
            sel = 'input#lessOtherDeductions'
            await fill_input_with_delay(page, sel, val, "Other Deductions", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Other Deductions is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Less Any Other Deductions = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Other Deductions field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Less Any Other Deductions: {e}")

    if stop_cb(): return False

    # Less Imposed Excess — READONLY, skip
    if isinstance(log, AutomationLogger):
        log.info("Skipping 'Imposed Excess' (Readonly).")
    else:
        log(f"   ℹ️ Skipping 'Less Imposed Excess' (Readonly field).")

    # Towing Charges — Optional
    try:
        val = str(getattr(data, 'towing_additional_charges', '') or '').strip()
        if val and val != "0":
            sel = 'input#towingCharges'
            await fill_input_with_delay(page, sel, val, "Towing Charges", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Towing Charges is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Towing Charges = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Towing field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Towing Charges: {e}")

    if stop_cb(): return False

    # Additional Towing Charges — Optional (separate field)
    try:
        val = str(getattr(data, 'additional_towing_charges', '') or '').strip()
        if val and val != "0":
            sel = 'input#additionalTowingCharges'
            await fill_input_with_delay(page, sel, val, "Addl Towing", log, field_delay_ms)
        else:
            if isinstance(log, AutomationLogger):
                log.info("Additional Towing is 0 or empty; skipping.")
            else:
                log(f"   ℹ️ Additional Towing Charges = 0 or empty. Skipping.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Addl Towing field error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling Additional Towing Charges: {e}")

    if stop_cb(): return False

    # Whether Re-Inspection Required — ALWAYS "No"
    try:
        sel = 'select#whetherReinspectionRequired'
        await select_dropdown_with_delay(page, sel, "No", "Re-Inspection", log, field_delay_ms)
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Re-Inspection dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Whether Re-Inspection Required: {e}")

    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.info("Section 5: Add-On Cover Wise Assessment")
        log.indent()
    else:
        log("")
        log(f"   ── Section 5: Add-On Cover Wise Assessment ──")

    # These are all optional — fill only if values exist and are non-zero
    addon_fields = [
        ("nil_depreciation_amount",  "input#nilDepreciationCover",  "Nil Dep Amount"),
        ("engine_protect_amount",    "input#engineProtectCover",    "Engine Protect Amount"),
        ("consumable_items_amount",  "input#consumableItemsCover",  "Consumable Items Amount"),
        ("key_protect_amount",       "input#keyProtectCover",       "Key Protect Amount"),
    ]

    for attr_name, selector, label in addon_fields:
        if stop_cb(): return False
        try:
            val = str(getattr(data, attr_name, '') or '').strip()
            if val and val != "0":
                try:
                    el = page.locator(selector).first
                    is_visible = await el.is_visible()
                    if is_visible:
                        await fill_input_with_delay(page, selector, val.strip(), label, log, field_delay_ms)
                    else:
                        if isinstance(log, AutomationLogger):
                            log.info(f"Field {label} not visible; skipping.")
                        else:
                            log(f"   ℹ️ [{label}] field not visible on page (add-on not applicable). Skipping.")
                except Exception:
                    if isinstance(log, AutomationLogger):
                        log.info(f"Field {label} not found; skipping.")
                    else:
                        log(f"   ℹ️ [{label}] field not found on page. Skipping.")
            else:
                if isinstance(log, AutomationLogger):
                    log.info(f"{label} is 0 or empty; skipping.")
                else:
                    log(f"   ℹ️ [{label}] = 0 or empty. Skipping.")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Add-on {label} field error: {str(e)[:100]}")
            else:
                log(f"   ⚠️ Error filling {label}: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP: Click "Next" button → dismiss the success popup → wait for page load
    # ═══════════════════════════════════════════════════════════════════════════
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.wait("Clicking 'Next' to save and proceed...")
    else:
        log(f" ── Clicking Next button ──")
    try:
        clicked = await _click_claim_assessment_next(page, log)
        if not clicked:
            return False

        if isinstance(log, AutomationLogger):
            log.info("'Next' clicked — waiting for confirmation popup...")
        else:
            log(f"   ℹ️ Clicked 'Next' button — waiting for save confirmation popup...")

        # ── The portal shows "Claim job details updated successfully" popup ──
        # We MUST dismiss it (click OK) before the page transitions.
        # The popup may take 1–8 seconds to appear depending on server response.
        dismissed = await dismiss_portal_popup(page, log, max_wait_s=5.0, context="Assessment Next")
        if dismissed:
            if isinstance(log, AutomationLogger):
                log.success("Save confirmation popup dismissed — page proceeding.")
            else:
                log(f"   ✅ Confirmation popup dismissed successfully.")
        else:
            # No popup appeared — portal may have navigated directly
            if isinstance(log, AutomationLogger):
                log.warning("No confirmation popup detected after 'Next' — continuing anyway.")
            else:
                log(f"   ⚠️ No popup appeared after 'Next' click (may have navigated directly).")

        if not await _document_upload_ready(page, timeout_ms=5000):
            if isinstance(log, AutomationLogger):
                log.warning("Document Upload tab not visible after Next; retrying Next once.")
            else:
                log("   ⚠️ Document Upload tab not visible after Next; retrying once.")

            clicked = await _click_claim_assessment_next(page, log)
            if not clicked:
                return False
            # Give the server up to 8s to show the popup and navigate
            await dismiss_portal_popup(page, log, max_wait_s=8.0, context="Assessment Next Retry")
            if not await _document_upload_ready(page, timeout_ms=5000):
                invalid = await _visible_invalid_required_fields(page)
                message = "Claim Assessment did not navigate to Document Upload after clicking Next."
                if invalid:
                    message += f" Visible required fields still invalid: {', '.join(invalid)}"
                if isinstance(log, AutomationLogger):
                    log.error(message)
                else:
                    log(f"   ❌ {message}")
                return False

        # Short settle — page has navigated, Angular needs ~300ms to stabilise
        await page.wait_for_timeout(300)

    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Navigation error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Could not click Next button: {e}")
        return False


    if isinstance(log, AutomationLogger):
        log.success("Claim Assessment Details phase completed.")
    else:
        log("")
        log(f" ✅ Phase 10 (Claim Assessment Details — All 5 Sections) completed successfully.")
    return True
