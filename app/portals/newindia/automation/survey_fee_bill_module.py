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
from app.utils import load_automation_defaults


def _find_survey_fee_bill_document(data: ClaimData) -> str:
    """Locate the Survey Fee Bill document.
    Enforces PDF format and uses dynamic doc mapping configuration keywords.
    """
    import os
    try:
        from app.utils import load_doc_mapping
        # Explicitly pass portal_id to ensure New India's doc_mapping.json is
        # loaded, not the currently active portal's mapping (which may be "uiic"
        # if the registry global is unset at test time or during a startup race).
        raw_mapping = load_doc_mapping(portal_id="newindia")
        sfb_map = (raw_mapping.get("survey_fee_bill", {}) or {}).get("survey_fee_bill_doc", [])
    except Exception:
        sfb_map = []

    if not sfb_map:
        sfb_map = ["final_invoice", "invoice", "survey_fee_bill", "survey_fee", "fee_bill"]

    # Direct mapping from assessment_files
    raw = getattr(data, "assessment_files", {})
    if isinstance(raw, dict):
        for key in ["invoice", "final_invoice"]:
            path = raw.get(key, "")
            path = os.path.normpath(path) if path else ""
            if path and os.path.isfile(path) and path.lower().endswith(".pdf"):
                return path

    # Fallback: scan upload_doc_files or claim_doc_files for mapped keywords
    for pool in [data.upload_doc_files, data.claim_doc_files]:
        if not isinstance(pool, dict):
            continue
        for _key, path in pool.items():
            path = os.path.normpath(path) if path else ""
            if path and os.path.isfile(path) and path.lower().endswith(".pdf"):
                lower_name = os.path.basename(path).lower()
                if any(kw in lower_name for kw in sfb_map):
                    return path

    return ""


async def _expand_survey_fee_bill_accordion(page: Page, log) -> bool:
    """Expand the 'Survey Fee bill' accordion if collapsed.

    The portal uses an Angular accordion. When collapsed the inner panel has
    ``collapse`` CSS but NOT ``in``.  We click the heading toggle to open it.
    """
    _structured = isinstance(log, AutomationLogger)

    # Check if already expanded — look for a visible field inside the accordion
    try:
        visible = await page.locator("#isInvoiceInNameOfNIA").first.is_visible()
        if visible:
            if _structured:
                log.info("Survey Fee Bill accordion already expanded.")
            else:
                log("   ℹ️ Survey Fee Bill accordion already expanded.")
            return True
    except Exception:
        pass

    # Find the accordion toggle — heading with text "Survey Fee bill"
    # Use pure Playwright locator chains (not hybrid CSS+text pseudo-selectors)
    # to avoid fragility across Playwright engine versions.
    toggle_locators = [
        page.locator("a.accordion-toggle").filter(has=page.locator("span", has_text="Survey Fee bill")).first,
        page.locator("a.accordion-toggle").filter(has=page.locator("span", has_text="Survey Fee Bill")).first,
        page.locator('a[ng-click="toggleOpen()"]').filter(has=page.locator("span", has_text="Survey Fee")).first,
    ]

    for toggle in toggle_locators:
        try:
            if await toggle.is_visible():
                await toggle.scroll_into_view_if_needed()
                await asyncio.sleep(0.3)
                await toggle.click()
                await asyncio.sleep(1.0)

                # Verify it expanded
                try:
                    await page.wait_for_selector(
                        "#isInvoiceInNameOfNIA",
                        state="visible",
                        timeout=5000,
                    )
                    if _structured:
                        log.success("Survey Fee Bill accordion expanded.")
                    else:
                        log("   ✅ Survey Fee Bill accordion expanded.")
                    return True
                except Exception:
                    pass
        except Exception:
            continue

    # JS fallback: click any accordion heading that contains "Survey Fee"
    try:
        result = await page.evaluate(
            """
            () => {
                const headings = Array.from(document.querySelectorAll(
                    'a.accordion-toggle'
                ));
                const target = headings.find(a => {
                    const text = (a.textContent || '').trim().toLowerCase();
                    return text.includes('survey fee');
                });
                if (target) {
                    target.click();
                    return { ok: true };
                }
                return { ok: false, reason: 'No Survey Fee Bill accordion found' };
            }
            """
        )
        if result.get("ok"):
            await asyncio.sleep(1.0)
            if _structured:
                log.success("Survey Fee Bill accordion expanded via JS fallback.")
            else:
                log("   ✅ Survey Fee Bill accordion expanded (JS fallback).")
            return True
    except Exception:
        pass

    if _structured:
        log.warning("Could not expand Survey Fee Bill accordion — fields may already be visible.")
    else:
        log("   ⚠️ Could not expand Survey Fee Bill accordion.")
    return True  # Non-fatal — fields might already be visible


async def _fill_hsn_code_typeahead(page: Page, log, field_delay_ms: int = 600, hsn_code: str = "8512") -> bool:
    """Fill the HSN Code typeahead field with the configured default.

    The field uses Angular typeahead with editable=false, so we must:
    1. Clear existing value
    2. Type the configured HSN code to trigger the dropdown
    3. Wait for the dropdown list to appear
    4. Select the matching item from the dropdown
    """
    _structured = isinstance(log, AutomationLogger)
    selector = "#hSNCode"
    hsn_code = str(hsn_code or "8512")

    try:
        field = page.locator(selector).first
        if not await field.is_visible():
            if _structured:
                log.info("HSN Code field not visible; skipping.")
            else:
                log("   ℹ️ HSN Code field not visible; skipping.")
            return True

        await field.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)

        # Clear and type the HSN code
        await field.click()
        await asyncio.sleep(0.2)
        await field.fill("")
        await asyncio.sleep(0.2)
        await field.type(hsn_code, delay=80)  # Slow typing to trigger typeahead
        await asyncio.sleep(1.5)  # Wait for typeahead dropdown to populate

        # Try to select the first matching item from the typeahead dropdown
        typeahead_item = page.locator(
            'ul.dropdown-menu[typeahead-popup] li a, '
            'ul.dropdown-menu li a'
        ).filter(has_text=re.compile(re.escape(hsn_code)))

        item_count = await typeahead_item.count()
        if item_count > 0:
            await typeahead_item.first.click()
            await asyncio.sleep(0.5)
            if _structured:
                log.success(f"HSN Code '{hsn_code}' selected from typeahead.")
            else:
                log(f"   ✅ HSN Code '{hsn_code}' selected from typeahead dropdown.")
            return True

        # Fallback: try pressing Enter or Down+Enter if dropdown is open
        await field.press("ArrowDown")
        await asyncio.sleep(0.3)
        await field.press("Enter")
        await asyncio.sleep(0.5)

        # Verify the value was set
        current_val = await field.input_value()
        if hsn_code in str(current_val):
            if _structured:
                log.success(f"HSN Code '{hsn_code}' set via keyboard navigation.")
            else:
                log(f"   ✅ HSN Code '{hsn_code}' set via keyboard.")
            return True

        # Last resort: JS direct model set
        await page.evaluate(
            """
            (hsnCode) => {
                const el = document.querySelector('#hSNCode');
                if (el) {
                    const scope = angular.element(el).scope();
                    if (scope && scope.surveyorData && scope.surveyorData.worklist && scope.surveyorData.worklist.surveyFeeBill) {
                        scope.surveyorData.worklist.surveyFeeBill.hsnCode = hsnCode;
                        scope.$apply();
                        // Trigger the onSelect callback to populate GST %
                        const ctrl = angular.element(el).controller('ngModel');
                        if (ctrl) ctrl.$setViewValue(hsnCode);
                    }
                }
            }
            """,
            hsn_code,
        )
        await asyncio.sleep(0.5)

        if _structured:
            log.warning("HSN Code set via Angular scope injection (JS fallback).")
        else:
            log("   ⚠️ HSN Code set via JS fallback — verify GST % is populated.")
        return True

    except Exception as e:
        if _structured:
            log.error(f"HSN Code typeahead error: {str(e)[:120]}")
        else:
            log(f"   ❌ HSN Code typeahead error: {e}")
        return False


async def _click_survey_fee_bill_submit(page: Page, log) -> bool:
    """Click the Survey Fee Bill Submit button and handle the confirmation popup."""
    _structured = isinstance(log, AutomationLogger)

    selector = 'button[data-ng-click="saveSurveyFeeBill()"]'

    candidates = page.locator(selector)
    count = await candidates.count()

    if count == 0:
        if _structured:
            log.error("No Survey Fee Bill Submit button found.")
        else:
            log("   ❌ No Survey Fee Bill Submit button found.")
        return False

    last_error = None
    for idx in range(count):
        btn = candidates.nth(idx)
        try:
            if not await btn.is_visible():
                continue
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)

            # Wait for button to be enabled (Angular form validation)
            for _ in range(20):
                if not await btn.is_disabled():
                    break
                await asyncio.sleep(0.25)

            if await btn.is_disabled():
                if _structured:
                    log.warning("Survey Fee Bill Submit button is disabled — form may be incomplete.")
                else:
                    log("   ⚠️ Submit button disabled — check required fields.")
                continue

            try:
                await btn.click(timeout=5000)
            except Exception as click_error:
                last_error = click_error
                await btn.click(timeout=5000, force=True)

            if _structured:
                log.info("Submit button clicked — waiting for confirmation...")
            else:
                log("   ℹ️ Submit button clicked — waiting for confirmation popup...")
            return True

        except Exception as exc:
            last_error = exc

    # JS fallback
    try:
        result = await page.evaluate(
            """
            () => {
                const buttons = Array.from(document.querySelectorAll(
                    'button[data-ng-click="saveSurveyFeeBill()"]'
                ));
                const target = buttons.find(btn => {
                    const style = window.getComputedStyle(btn);
                    return !btn.disabled
                        && style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && btn.getClientRects().length > 0;
                });
                if (!target) return { ok: false, reason: 'no visible enabled submit button' };
                target.scrollIntoView({ block: 'center' });
                target.click();
                return { ok: true };
            }
            """
        )
        if result.get("ok"):
            if _structured:
                log.info("Submit clicked via JS fallback.")
            else:
                log("   ℹ️ Submit clicked (JS fallback).")
            return True
    except Exception as exc:
        last_error = exc

    if _structured:
        log.error(f"Could not click Submit button: {str(last_error)[:140]}")
    else:
        log(f"   ❌ Could not click Submit: {last_error}")
    return False


async def fill_survey_fee_bill(
    page: Page,
    data: ClaimData,
    log,
    stop_cb,
    field_delay_ms: int = 600,
) -> bool:
    """Fill the Survey Fee Bill section on the NIA portal.

    This is Phase 11 in the NIA workflow, between Claim Assessment and
    Document Upload.
    """
    if stop_cb():
        return False

    _structured = isinstance(log, AutomationLogger)
    if _structured:
        log._section = "Survey Fee Bill"
        log.info("Starting Survey Fee Bill phase...")
        log.indent()
    else:
        log("Opening Survey Fee Bill section...")

    _result = False
    try:
        _result = await _fill_survey_fee_bill_inner(page, data, log, stop_cb, field_delay_ms)
    finally:
        if _structured:
            log.outdent()
    return _result


async def _fill_survey_fee_bill_inner(page, data, log, stop_cb, field_delay_ms):
    """Inner body of fill_survey_fee_bill — called via try/finally wrapper."""

    _structured = isinstance(log, AutomationLogger)
    defaults = load_automation_defaults(portal_id=getattr(data, "portal_id", "newindia"))

    # 0. Pre-check: locate the Survey Fee Bill document. If missing, we still
    #    fill all form fields and only skip the document upload + submit.
    doc_path = _find_survey_fee_bill_document(data)
    if not doc_path:
        if _structured:
            log.field_skipped("Survey Fee Bill Document", reason="No PDF available in scan")
            log.warning(
                "Survey Fee Bill PDF not found in claim directories "
                "(expected: final_invoice.pdf or invoice.pdf). "
                "Will fill fields only — skipping document upload."
            )
        else:
            log(
                "   ⚠️ Survey Fee Bill PDF not found "
                "(expected: final_invoice.pdf or invoice.pdf). "
                "Will fill fields only — skipping document upload."
            )
    else:
        if _structured:
            log.document_mapped("Survey Fee Bill", os.path.basename(doc_path), "Matched Successfully")
            log.info(f"Survey Fee Bill document located: {doc_path}")
        else:
            import os as _os
            log(f"   ✅ Document pre-check passed: {_os.path.basename(doc_path)}")

    # Handle any stale popup
    await dismiss_portal_popup(page, log, max_wait_s=3.0, context="Survey Fee Bill Start")

    if stop_cb():
        return False

    # 1. Expand the accordion
    await _expand_survey_fee_bill_accordion(page, log)
    await asyncio.sleep(0.5)

    if stop_cb():
        return False

    # ══════════════════════════════════════════════════════════════════════════
    # MANDATORY FIELDS
    # ══════════════════════════════════════════════════════════════════════════

    if _structured:
        log.info("Section: Mandatory Fields")
        log.indent()
    else:
        log("")
        log("   ── Section: Mandatory Fields ──")

    # Field 1: Is Invoice in name of NIA
    try:
        sel = 'select#isInvoiceInNameOfNIA'
        invoice_in_company = str(defaults.get("invoice_in_company_name", "Yes") or "Yes")
        await select_dropdown_with_delay(page, sel, invoice_in_company, "Invoice in NIA Name", log, field_delay_ms, source="Default")
    except Exception as e:
        if _structured:
            log.error(f"Invoice NIA Name dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting Invoice in NIA Name: {e}")

    if stop_cb():
        return False

    # Field 2: Surveyor Fee Invoice Number
    try:
        val = getattr(data, 'vendor_invoice_number', '') or ''
        if val:
            val = str(val).strip()
            sel = 'input#surveyorFeeInvoiceNumber'
            await fill_input_with_delay(page, sel, val, "SFB Invoice Number", log, field_delay_ms, source="Excel")
        else:
            if _structured:
                log.field_skipped("SFB Invoice Number", reason="Missing from Excel")
                log.warning("Surveyor Fee Invoice Number missing — field is mandatory!")
            else:
                log("   ⚠️ Surveyor Fee Invoice Number missing from data (mandatory).")
    except Exception as e:
        if _structured:
            log.error(f"SFB Invoice Number error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling SFB Invoice Number: {e}")

    if stop_cb():
        return False

    # Field 3: Surveyor Fee Invoice Date
    try:
        val = getattr(data, 'vendor_invoice_date', '') or ''
        if val:
            val = str(val).strip()
            sel = 'input[name="surveyorFeeInvoiceDate"]'
            await fill_input_with_delay(page, sel, val, "SFB Invoice Date", log, field_delay_ms, source="Excel")
        else:
            if _structured:
                log.field_skipped("SFB Invoice Date", reason="Missing from Excel")
                log.warning("Surveyor Fee Invoice Date missing — field is mandatory!")
            else:
                log("   ⚠️ Surveyor Fee Invoice Date missing from data (mandatory).")
    except Exception as e:
        if _structured:
            log.error(f"SFB Invoice Date error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error filling SFB Invoice Date: {e}")

    if stop_cb():
        return False

    if _structured:
        log.outdent()

    # ══════════════════════════════════════════════════════════════════════════
    # OPTIONAL AMOUNT FIELDS (from Excel, skip if 0 or empty)
    # ══════════════════════════════════════════════════════════════════════════

    if _structured:
        log.info("Section: Amount Fields")
        log.indent()
    else:
        log("")
        log("   ── Section: Amount Fields ──")

    amount_fields = [
        ("professional_fee",     "input#professionalFee",   "Professional Fee"),
        ("photo_charges",        "input#photosAmount",      "Photos Amount"),
        ("traveling_expenses",   "input#conveyanceAmount",  "Conveyance Amount"),
        ("sfb_others",           "input#others",            "Others"),
    ]
    photo_charges_default = str(defaults.get("photo_charges_default", "200") or "200")

    for attr_name, selector, label in amount_fields:
        if stop_cb():
            return False
        try:
            val = photo_charges_default if attr_name == "photo_charges" else str(getattr(data, attr_name, '') or '').strip()
            src = "Default" if attr_name == "photo_charges" else "Excel"
            if val and val != "0":
                await fill_input_with_delay(page, selector, val, label, log, field_delay_ms, source=src)
            else:
                if _structured:
                    log.field_skipped(label, reason="Missing from Excel" if not val else "Value is 0")
                else:
                    log(f"   ℹ️ [{label}] = 0 or empty. Skipping.")
        except Exception as e:
            if _structured:
                log.error(f"{label} field error: {str(e)[:100]}")
            else:
                log(f"   ⚠️ Error filling {label}: {e}")

    if stop_cb():
        return False

    if _structured:
        log.outdent()

    # ══════════════════════════════════════════════════════════════════════════
    # GST SECTION
    # ══════════════════════════════════════════════════════════════════════════

    if _structured:
        log.info("Section: GST & HSN")
        log.indent()
    else:
        log("")
        log("   ── Section: GST & HSN ──")

    # Field 8: Is GST applicable
    try:
        sel = 'select#isGSTApplicable'
        gst_applicable = str(defaults.get("gst_applicable", "Yes") or "Yes")
        await select_dropdown_with_delay(page, sel, gst_applicable, "GST Applicable", log, field_delay_ms, source="Default")
    except Exception as e:
        if _structured:
            log.error(f"GST Applicable dropdown error: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Error selecting GST Applicable: {e}")

    if stop_cb():
        return False

    # Field 9: HSN Code (typeahead)
    await _fill_hsn_code_typeahead(
        page,
        log,
        field_delay_ms,
        hsn_code=str(defaults.get("hsn_code", "8512") or "8512"),
    )

    if stop_cb():
        return False

    # Fields 10, 11, 12: GST %, GST Amount, Total → READ-ONLY, skip
    if _structured:
        log.info("Skipping 'GST %' (Readonly — auto-populated from HSN Code).")
        log.info("Skipping 'GST Amount' (Readonly — auto-calculated).")
        log.info("Skipping 'Total' (Readonly — auto-calculated).")
    else:
        log("   ℹ️ Skipping GST %, GST Amount, Total (Readonly fields).")

    if stop_cb():
        return False

    if _structured:
        log.outdent()

    # ══════════════════════════════════════════════════════════════════════════
    # DOCUMENT UPLOAD (Survey Fee Bill document)
    #   Upload only if doc_path was found during pre-check.
    # ══════════════════════════════════════════════════════════════════════════

    if doc_path:
        if _structured:
            log.info("Section: Document Upload")
            log.indent()
        else:
            log("")
            log("   ── Section: Document Upload ──")

        try:
            if _structured:
                log.upload_start("Survey Fee Bill Document", os.path.basename(doc_path))
            
            await upload_file_via_input(
                page,
                file_input_selector='input#uploadDigSig',
                file_path=doc_path,
                label="Survey Fee Bill Document",
                log=log,
            )

            # Click the Upload button
            upload_btn = page.locator(
                'button[data-ng-click="uploadDigSignature1(\'mandatory\')"]'
            ).first
            try:
                await upload_btn.wait_for(state="visible", timeout=5000)
                await asyncio.sleep(0.5)
                await upload_btn.click()
                await asyncio.sleep(1.5)

                # Handle upload confirmation popup
                await dismiss_portal_popup(page, log, max_wait_s=8.0, context="SFB Upload")

                if _structured:
                    log.success("Survey Fee Bill document uploaded successfully.")
                else:
                    log("   ✅ Survey Fee Bill document uploaded.")
            except Exception as ue:
                if _structured:
                    log.error(f"Upload button click failed: {str(ue)[:100]}")
                else:
                    log(f"   ⚠️ Upload button error: {ue}")
        except Exception as e:
            if _structured:
                log.error(f"SFB document upload error: {str(e)[:100]}")
            else:
                log(f"   ⚠️ Error uploading Survey Fee Bill document: {e}")

        if stop_cb():
            return False

        if _structured:
            log.outdent()
    else:
        if _structured:
            log.warning("Document upload skipped — no Survey Fee Bill PDF available.")
        else:
            log("   ⚠️ Document upload skipped — no PDF available.")

    # ══════════════════════════════════════════════════════════════════════════
    # SUBMIT
    # ══════════════════════════════════════════════════════════════════════════

    if _structured:
        log.wait("Clicking 'Submit' to save Survey Fee Bill...")
    else:
        log("")
        log("   ── Clicking Submit ──")

    clicked = await _click_survey_fee_bill_submit(page, log)
    if not clicked:
        if _structured:
            log.error("Survey Fee Bill Submit failed — button may be disabled.")
        else:
            log("   ❌ Survey Fee Bill Submit failed.")
        return False

    # Dismiss the confirmation popup
    dismissed = await dismiss_portal_popup(page, log, max_wait_s=8.0, context="SFB Submit")
    if dismissed:
        if _structured:
            log.success("Survey Fee Bill saved successfully.")
        else:
            log("   ✅ Survey Fee Bill confirmation popup dismissed.")
    else:
        if _structured:
            log.warning("No confirmation popup after Submit — may have saved silently.")
        else:
            log("   ⚠️ No popup after Submit (may have saved directly).")

    await asyncio.sleep(1.0)

    if _structured:
        log.success("Survey Fee Bill phase completed.")
    else:
        log("")
        log(" ✅ Survey Fee Bill phase completed successfully.")

    return True
