"""
claim_assessment.py — Fills the "Claim Assessment" tab.

PRODUCTION REWRITE 2026-04-18:
  - Declaration radio: now uses AngularJS-compatible JS (set .checked + 'change' event)
  - Invoice no/date fallback: strict empty-string check (not falsy) to avoid "0" override
  - Upload wait: replaced sleep(2.5) with network-idle wait → faster and reliable
  - _click_tab: unified shared helper (no longer duplicated)
  - Each section isolated in try/except — one bad field cannot crash the whole tab
"""
import asyncio
import logging
import os
from typing import Callable

from app.data.data_model import ClaimData
from app.automation.form_helpers import (
    safe_fill, safe_fill_amount, safe_fill_date, safe_fill_text,
    safe_fill_portal_text,
)
from app.automation.selectors import ASSESSMENT, TABS, TAB_SEL
from app.automation.tab_utils import click_tab

logger = logging.getLogger(__name__)

MAX_FILE_MB = 2.0

# Portal upload section label → assessment_files dict key
ASSESSMENT_UPLOAD_LABELS = {
    "assessment_report":   "Upload Assessment Report",
    "survey_report":       "Upload Survey Report",
    "estimate":            "Upload Estimate",
    "invoice":             "Upload Invoice",
    "reinspection_report": "Upload Re-Inspection Report",
}


async def _click_declaration_radio(page, log_cb: Callable) -> None:
    """
    Click the Yes radio for Declaration (ynPerused).
    Uses JS only — avoids f-string quoting issues with CSS selectors.
    """
    result = await page.evaluate("""
        (function() {
            // Try all known selector patterns for the declaration radio
            var selectors = [
                'input[name="ynPerused"][value="Y"]',
                'input[ng-model*="ynPerused"][value="Y"]',
                'input[data-ng-model*="ynPerused"][value="Y"]'
            ];
            for (var s of selectors) {
                var r = document.querySelector(s);
                if (r) {
                    r.checked = true;
                    r.dispatchEvent(new Event('change', {bubbles: true}));
                    try { r.click(); } catch(e) {}
                    return 'ok:' + s;
                }
            }
            // Broader scan: any radio with value Y near text 'perused'/'declaration'
            var radios = document.querySelectorAll('input[type="radio"][value="Y"]');
            for (var radio of radios) {
                var label = '';
                if (radio.id) {
                    var lbl = document.querySelector('label[for="' + radio.id + '"]');
                    if (lbl) label = lbl.textContent.toLowerCase();
                }
                if (!label) {
                    var parent = radio.closest('td,div,span,li');
                    if (parent) label = parent.textContent.toLowerCase();
                }
                if (label.includes('perused') || label.includes('declaration') ||
                    label.includes('verified') || label.includes('confirm')) {
                    radio.checked = true;
                    radio.dispatchEvent(new Event('change', {bubbles: true}));
                    try { radio.click(); } catch(e) {}
                    return 'broad:' + label.substring(0, 30);
                }
            }
            return null;
        })();
    """)
    if result:
        log_cb(f"  ✅ Declaration: Yes ({result})")
    else:
        # Playwright fallback
        try:
            r = page.locator(ASSESSMENT["radio_declaration"]).first
            if await r.is_visible(timeout=2000):
                await r.click(force=True)
                log_cb("  ✅ Declaration: Yes (Playwright force)")
            else:
                log_cb("  ⚠️  Declaration radio: not found on page")
        except Exception as e:
            log_cb(f"  ⚠️  Declaration radio: {str(e)[:80]}")


async def _upload_by_label(page, upload_label: str, file_path: str,
                            log_cb: Callable, slot_key: str = "") -> bool:
    """
    Find the file input associated with the given upload label.

    REWRITTEN 2026-04-21 — Confirmed from live DOM:
      Portal uses name="fileToUploadN" where N = slot index (0-4).
      Strategy 0: Direct input[name='fileToUploadN'] — bulletproof
      Strategy 1: JS DOM scan — walks li.clearfix rows by text
      Strategy 2: li.clearfix Playwright filter
      Strategy 3: label parent/grandparent traversal
      Strategy 4: XPath following fallback

    Also handles Angular's data-ng-disabled by removing disabled attr via JS.
    """
    fname = os.path.basename(file_path)
    if not os.path.isfile(file_path):
        log_cb(f"  ⚠️  Not found: {fname}")
        return False
    mb = os.path.getsize(file_path) / (1024 * 1024)
    if mb > MAX_FILE_MB:
        log_cb(f"  ⚠️  Too large ({mb:.1f}MB): {fname}")
        return False

    log_cb(f"  ▶ [{upload_label}] ← {fname}")
    abs_path = str(os.path.abspath(file_path))

    # Strategy 0: Direct name selector — from confirmed DOM structure
    # Portal uses: <input type="file" name="fileToUploadN"> where N = slot index
    slot_idx = ASSESSMENT_SLOTS.get(slot_key)
    if slot_idx is not None:
        try:
            direct_sel = f'input[name="fileToUpload{slot_idx}"]'
            # Remove Angular disabled attribute first via JS
            await page.evaluate(f"""
                (() => {{
                    const inp = document.querySelector('{direct_sel}');
                    if (inp) {{
                        inp.removeAttribute('disabled');
                        inp.removeAttribute('ng-disabled');
                        inp.removeAttribute('data-ng-disabled');
                        inp.disabled = false;
                    }}
                }})();
            """)
            await asyncio.sleep(0.2)

            el = page.locator(direct_sel).first
            if await el.count() > 0:
                await el.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    await asyncio.sleep(1.5)
                log_cb(f"  ✅ Uploaded: {fname} (direct name=fileToUpload{slot_idx})")
                return True
        except Exception as e:
            log_cb(f"  ⚠️  Direct selector failed: {str(e)[:80]}")

    # Strategy 1: JS that finds the input, removes disabled, and returns it
    try:
        js_label = upload_label.replace("'", "\\'")
        input_handle = await page.evaluate_handle(f"""
            (() => {{
                const target = '{js_label}'.toLowerCase();
                const rows = document.querySelectorAll('li.clearfix');
                for (const row of rows) {{
                    const text = row.textContent.toLowerCase().replace(/\\s+/g, ' ');
                    if (text.includes(target)) {{
                        const inp = row.querySelector('input[type="file"]');
                        if (inp) {{
                            inp.removeAttribute('disabled');
                            inp.disabled = false;
                            return inp;
                        }}
                    }}
                }}
                // Fallback: scan labels
                const allLabels = document.querySelectorAll('label, span, td, b, strong');
                for (const lbl of allLabels) {{
                    const text = lbl.textContent.toLowerCase().replace(/\\s+/g, ' ');
                    if (text.includes(target)) {{
                        let el = lbl;
                        for (let i = 0; i < 5; i++) {{
                            el = el.parentElement;
                            if (!el) break;
                            const inp = el.querySelector('input[type="file"]');
                            if (inp) {{
                                inp.removeAttribute('disabled');
                                inp.disabled = false;
                                return inp;
                            }}
                        }}
                    }}
                }}
                return null;
            }})()
        """)
        if input_handle:
            element = input_handle.as_element()
            if element:
                await element.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    await asyncio.sleep(1.5)
                log_cb(f"  ✅ Uploaded: {fname} (JS DOM scan)")
                return True
    except Exception as e:
        log_cb(f"  ⚠️  JS strategy failed for [{upload_label}]: {str(e)[:80]}")

    # Strategy 2: Playwright li.clearfix filter
    try:
        row = page.locator("li.clearfix").filter(
            has=page.locator(f"*:has-text('{upload_label}')")
        ).filter(
            has=page.locator('input[type="file"]')
        ).first
        if await row.count() > 0:
            file_input = row.locator('input[type="file"]').first
            if await file_input.count() > 0:
                await file_input.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    await asyncio.sleep(1.5)
                log_cb(f"  ✅ Uploaded: {fname} (li.clearfix)")
                return True
    except Exception:
        pass

    # Strategy 3: label parent/grandparent traversal
    try:
        labels = page.locator(f"label:has-text('{upload_label}')")
        label_count = await labels.count()
        for i in range(label_count):
            lbl = labels.nth(i)
            parent = lbl.locator("xpath=..")
            sibling_input = parent.locator('input[type="file"]')
            if await sibling_input.count() > 0:
                await sibling_input.first.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    await asyncio.sleep(1.5)
                log_cb(f"  ✅ Uploaded: {fname} (label parent)")
                return True
            grandparent = parent.locator("xpath=..")
            gp_input = grandparent.locator('input[type="file"]')
            if await gp_input.count() > 0:
                await gp_input.first.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    await asyncio.sleep(1.5)
                log_cb(f"  ✅ Uploaded: {fname} (label grandparent)")
                return True
    except Exception:
        pass

    # Strategy 4: XPath following fallback
    label_selectors = [
        f"span:has-text('{upload_label}')",
        f"label:has-text('{upload_label}')",
        f"td:has-text('{upload_label}')",
        f"b:has-text('{upload_label}')",
        f"strong:has-text('{upload_label}')",
    ]
    for label_sel in label_selectors:
        try:
            fi = page.locator(label_sel).locator(
                "xpath=following::input[@type='file'][1]"
            ).first
            if await fi.count() > 0:
                await fi.wait_for(state="attached", timeout=4000)
                await fi.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    await asyncio.sleep(1.5)
                log_cb(f"  ✅ Uploaded: {fname} (XPath following)")
                return True
        except Exception:
            continue

    log_cb(f"  ❌ Upload input not found for: {upload_label}")
    return False


async def _fill_parts(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n🔩 Parts Depreciation:")
    try:
        await safe_fill_amount(page, ASSESSMENT["age_dep"],
                               claim.parts_age_dep_excl_gst, "Age Dep (Metal)", log_cb,
                               source=_src("parts_age_dep_excl_gst"))
        await safe_fill_amount(page, ASSESSMENT["dep_50"],
                               claim.parts_50_dep_excl_gst, "50% Dep (Plastic)", log_cb,
                               source=_src("parts_50_dep_excl_gst"))

        await safe_fill_amount(page, ASSESSMENT["nil_dep"],
                               claim.parts_nil_dep_excl_gst, "Nil Dep", log_cb,
                               source=_src("parts_nil_dep_excl_gst"))
        await safe_fill_amount(page, ASSESSMENT["gst_18_parts"],
                               claim.parts_gst18_amount, "Parts GST 18%", log_cb,
                               source=_src("parts_gst18_amount"))
    except Exception as e:
        log_cb(f"  ❌ Parts section error: {e}")


async def _fill_labour(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n👷 Labour:")
    try:
        await safe_fill_amount(page, ASSESSMENT["labour"],
                               claim.labour_excl_gst, "Labour (Excl GST)", log_cb,
                               source=_src("labour_excl_gst"))
        await safe_fill_amount(page, ASSESSMENT["gst_18_labour"],
                               claim.labour_excl_gst, "Labour GST 18%", log_cb,
                               source=_src("labour_excl_gst"))
    except Exception as e:
        log_cb(f"  ❌ Labour section error: {e}")


async def _fill_workshop_invoice(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n🧾 Workshop Invoice:")
    try:
        # Strip trailing "(CREDIT)" or anything after a space, and limit to 20 chars
        ws_no = str(claim.workshop_invoice_no).split(" ")[0].split("(")[0][:20]
        await safe_fill(page, ASSESSMENT["ws_invoice_no"],
                        ws_no, "WS Invoice No", log_cb,
                        source=_src("workshop_invoice_no"))
        await safe_fill_date(page, ASSESSMENT["ws_invoice_date"],
                             claim.workshop_invoice_date, "WS Invoice Date", log_cb,
                             source=_src("workshop_invoice_date"))
    except Exception as e:
        log_cb(f"  ❌ Workshop invoice error: {e}")


async def _fill_other_charges(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n💰 Other Charges:")
    try:
        await safe_fill_amount(page, ASSESSMENT["towing"],
                               claim.towing_charges, "Towing Charges", log_cb,
                               source=_src("towing_charges"))
        await safe_fill_amount(page, ASSESSMENT["spot_repairs"],
                               claim.spot_repairs, "Spot Repairs", log_cb,
                               source=_src("spot_repairs"))
        await safe_fill_amount(page, ASSESSMENT["vol_excess"],
                               claim.voluntary_excess, "Voluntary Excess", log_cb,
                               source=_src("voluntary_excess"))
        await safe_fill_amount(page, ASSESSMENT["comp_excess"],
                               claim.compulsory_excess, "Compulsory Excess", log_cb,
                               source=_src("compulsory_excess"))
        await safe_fill_amount(page, ASSESSMENT["imp_excess"],
                               claim.imposed_excess, "Imposed Excess", log_cb,
                               source=_src("imposed_excess"))
        await safe_fill_amount(page, ASSESSMENT["salvage"],
                               claim.salvage_value, "Salvage Value", log_cb,
                               source=_src("salvage_value"))
    except Exception as e:
        log_cb(f"  ❌ Other charges error: {e}")


async def _fill_invoice_details(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n📋 Invoice Details:")
    try:
        # BUG FIX (B6): Use explicit empty-string check, NOT falsy check.
        # claim.invoice_no == "0" is valid; only fall back when truly absent.
        inv_no   = claim.invoice_no   if claim.invoice_no.strip()   else claim.workshop_invoice_no
        inv_date = claim.invoice_date if claim.invoice_date.strip() else claim.workshop_invoice_date
        
        # Strip trailing "(CREDIT)" or anything after a space, and limit to 20 chars
        inv_no_clean = str(inv_no).split(" ")[0].split("(")[0][:20]
        
        await safe_fill(page, ASSESSMENT["invoice_no"],
                        inv_no_clean, "Invoice No", log_cb,
                        source=_src("invoice_no") or _src("workshop_invoice_no"))
        await safe_fill_date(page, ASSESSMENT["invoice_date"],
                             inv_date, "Invoice Date", log_cb,
                             source=_src("invoice_date") or _src("workshop_invoice_date"))
    except Exception as e:
        log_cb(f"  ❌ Invoice details error: {e}")


async def _fill_report_details(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n📝 Report Details:")
    try:
        import re
        raw_ref = claim.final_report_no or ""
        if len(claim.invoice_no or "") > len(raw_ref):
            raw_ref = claim.invoice_no
            
        # The user requested to only enter the last value after dash/slash (e.g., '116')
        clean_report_no = re.split(r'[/\\-]', raw_ref)[-1].strip() if raw_ref else ""
        
        await safe_fill(page, ASSESSMENT["report_no"],
                        clean_report_no, "Report No", log_cb,
                        source=_src("final_report_no"))
        if claim.final_report_date and claim.final_report_date.strip():
            await safe_fill_date(page, ASSESSMENT["report_date"],
                                 claim.final_report_date, "Report Date", log_cb,
                                 source=_src("final_report_date"))
        else:
            log_cb("  ⏭️  Report Date: skipped (portal auto-fills today's date)")
    except Exception as e:
        log_cb(f"  ❌ Report details error: {e}")


async def _fill_surveyor_charges(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n💼 Surveyor Charges:")
    try:
        await safe_fill_amount(page, ASSESSMENT["travel"],
                               claim.traveling_expenses, "Travel Expenses", log_cb,
                               source=_src("traveling_expenses"))
        await safe_fill_amount(page, ASSESSMENT["prof_fee"],
                               claim.professional_fee, "Professional Fee", log_cb,
                               source=_src("professional_fee"))
        await safe_fill_amount(page, ASSESSMENT["daily_allowance"],
                               claim.daily_allowance, "Daily Allowance", log_cb,
                               source=_src("daily_allowance"))
        await safe_fill_amount(page, ASSESSMENT["photo"],
                               claim.photo_charges, "Photo Charges", log_cb,
                               source=_src("photo_charges"))
        # Total Claimed = sum of the 4 surveyor charge fields
        total = sum(
            int(float(v or 0))
            for v in [claim.traveling_expenses, claim.professional_fee,
                      claim.daily_allowance, claim.photo_charges]
        )
        await safe_fill_amount(page, ASSESSMENT["total"],
                               str(total), "Total Claimed Amount", log_cb,
                               source="Calculated")
    except Exception as e:
        log_cb(f"  ❌ Surveyor charges error: {e}")


async def _upload_all(page, claim: ClaimData, log_cb: Callable) -> None:
    log_cb("\n📤 Uploading Assessment Documents...")
    count = 0
    for slot_key, file_path in claim.assessment_files.items():
        if not file_path:
            continue
        upload_label = ASSESSMENT_UPLOAD_LABELS.get(slot_key, slot_key)
        try:
            ok = await _upload_by_label(page, upload_label, file_path, log_cb,
                                         slot_key=slot_key)
            if ok:
                count += 1
        except Exception as e:
            log_cb(f"  ❌ [{slot_key}] upload error: {e}")
    log_cb(f"  📁 {count}/{len(claim.assessment_files)} files uploaded")


async def fill_claim_assessment(page, claim: ClaimData,
                                 log_cb: Callable[[str], None] = print) -> None:
    """
    Fill the entire Claim Assessment tab.
    Each section is isolated — a failure in one section does NOT stop others.
    """
    await click_tab(page, "assessment", log_cb)

    log_cb("📊 Filling Claim Assessment...")

    # Helper to look up Excel source coordinate for a field
    def _src(key: str) -> str:
        return claim._excel_coords.get(key, "")

    await _fill_parts(page, claim, log_cb, _src)
    await _fill_labour(page, claim, log_cb, _src)
    await _fill_workshop_invoice(page, claim, log_cb, _src)
    await _fill_other_charges(page, claim, log_cb, _src)
    await _fill_invoice_details(page, claim, log_cb, _src)
    await _fill_report_details(page, claim, log_cb, _src)
    await _fill_surveyor_charges(page, claim, log_cb, _src)

    # Declaration radio (AngularJS-compatible)
    log_cb("\n✍️  Declaration:")
    await _click_declaration_radio(page, log_cb)

    # Remarks (optional — same text as observation)
    try:
        await safe_fill_portal_text(page, ASSESSMENT["remarks"],
                             "OK", "Remarks", log_cb,
                             source="Hardcoded")
    except Exception as e:
        log_cb(f"  ⚠️  Remarks: {e}")

    await _upload_all(page, claim, log_cb)

    log_cb("\n✅ Claim Assessment complete.")
    log_cb("👀 Review all tabs then click 'Final Submit' manually.")
