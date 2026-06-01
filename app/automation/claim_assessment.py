import asyncio
import logging
import os
from typing import Callable

from app.data.data_model import ClaimData
from app.automation.form_helpers import (
    safe_fill, safe_fill_amount, safe_fill_date, safe_fill_text,
    safe_fill_portal_text,
)
from app.automation.selectors import ASSESSMENT, ASSESSMENT_SLOTS, TABS, TAB_SEL
from app.automation.tab_utils import click_tab
from app.automation.automation_logger import AutomationLogger
from app.utils import load_automation_defaults

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


def _log_extraction(claim, log, field: str, value: str, key: str):
    if not isinstance(log, AutomationLogger):
        return
    coord = claim._excel_coords.get(key, "")
    sheet = "Summary"
    cell = coord
    if "|" in coord:
        parts = coord.split("|")
        sheet = parts[0].strip()
        cell = parts[1].strip()
    elif not coord:
        sheet = "N/A"
        cell = "N/A"
    log.excel_extracted(field, str(value), cell, sheet=sheet)


def _settings_int(settings, key: str, default: int) -> int:
    """Read integer settings safely when UI persistence stores values as strings."""
    value = (settings or {}).get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _click_declaration_radio(page, log) -> None:
    """
    Click the Yes radio for Declaration (ynPerused).
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
        if isinstance(log, AutomationLogger):
            log.success(f"Declaration set to 'Yes' ({result})")
        else:
            log(f"  ✅ Declaration: Yes ({result})")
    else:
        # Playwright fallback
        try:
            r = page.locator(ASSESSMENT["radio_declaration"]).first
            if await r.is_visible(timeout=2000):
                await r.click(force=True)
                if isinstance(log, AutomationLogger):
                    log.success("Declaration set to 'Yes' (Playwright force)")
                else:
                    log("  ✅ Declaration: Yes (Playwright force)")
            else:
                if isinstance(log, AutomationLogger):
                    log.warning("Declaration radio not found on page")
                else:
                    log("  ⚠️  Declaration radio: not found on page")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Declaration radio error: {str(e)[:80]}")
            else:
                log(f"  ⚠️  Declaration radio: {str(e)[:80]}")


async def _upload_by_label(page, upload_label: str, file_path: str,
                            log, settings: dict, slot_key: str = "") -> bool:
    """
    Find the file input associated with the given upload label and upload.
    """
    cfg = settings or {}
    upload_wait_s = _settings_int(cfg, "upload_wait_ms", 3000) / 1000.0
    timeout_ms = _settings_int(cfg, "timeout_ms", 4000)

    fname = os.path.basename(file_path)
    if not os.path.isfile(file_path):
        if isinstance(log, AutomationLogger):
            log.upload_failed(upload_label, "File not found")
            log.warning(f"File not found: {fname}")
        else:
            log(f"  ⚠️  Not found: {fname}")
        return False
        
    mb = os.path.getsize(file_path) / (1024 * 1024)
    if mb > MAX_FILE_MB:
        logger.info("Large assessment file (%.1fMB): %s — portal alert will be auto-accepted", mb, fname)

    if isinstance(log, AutomationLogger):
        log.upload_start(upload_label, fname)
    else:
        log(f"  ▶ [{upload_label}] ← {fname}")
        
    abs_path = str(os.path.abspath(file_path))

    # Strategy 0: Direct name selector + Fallbacks
    try:
        # First try to find the row by label, then find the input inside it
        row = page.locator("li.clearfix").filter(has_text=upload_label).first
        if await row.count() > 0:
            inp = row.locator('input[type="file"]').first
            if await inp.count() > 0:
                # Remove Angular disabled attributes
                await inp.evaluate('''el => {
                    el.removeAttribute('disabled');
                    el.removeAttribute('ng-disabled');
                    el.removeAttribute('data-ng-disabled');
                    el.disabled = false;
                }''')
                await asyncio.sleep(0.2)
                await inp.set_input_files(abs_path)
                try:
                    await inp.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))")
                except Exception:
                    pass
                await asyncio.sleep(upload_wait_s)
                if isinstance(log, AutomationLogger):
                    log.upload_attached(upload_label, fname)
                else:
                    log(f"  ✅ Uploaded: {fname} (li.clearfix relative selector)")
                return True
    except Exception as e:
        logger.debug(f"Strategy 0 failed: {e}")

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
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=element)
                except Exception:
                    pass
                await asyncio.sleep(upload_wait_s)
                if isinstance(log, AutomationLogger):
                    log.upload_attached(upload_label, fname)
                else:
                    log(f"  ✅ Uploaded: {fname} (JS DOM scan)")
                return True
    except Exception as e:
        logger.debug(f"Strategy 1 failed: {e}")

    # Strategy 4: XPath following fallback
    label_selectors = [
        f"span:has-text('{upload_label}')",
        f"label:has-text('{upload_label}')",
        f"td:has-text('{upload_label}')",
    ]
    for label_sel in label_selectors:
        try:
            fi = page.locator(label_sel).locator(
                "xpath=following::input[@type='file'][1]"
            ).first
            if await fi.count() > 0:
                await fi.wait_for(state="attached", timeout=timeout_ms)
                await fi.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    await asyncio.sleep(upload_wait_s / 2.0)
                if isinstance(log, AutomationLogger):
                    log.upload_attached(upload_label, fname)
                else:
                    log(f"  ✅ Uploaded: {fname} (XPath following)")
                return True
        except Exception:
            continue

    if isinstance(log, AutomationLogger):
        log.upload_failed(upload_label, "Upload input not found on page")
    else:
        log(f"  ❌ Upload input not found for: {upload_label}")
    return False


async def _fill_parts(page, claim: ClaimData, log, _src) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Filling Parts Depreciation section...")
        log.indent()
    else:
        log("\n🔩 Parts Depreciation:")
        
    try:
        nil_dep_raw = (claim.nil_depreciation or "").strip().lower()
        should_check = nil_dep_raw == "yes"

        if nil_dep_raw in {"yes", "no"}:
            _log_extraction(claim, log, "Nil Depreciation", claim.nil_depreciation, "nil_depreciation")
            toggle_result = await page.evaluate(
                """
                ({ shouldCheck }) => {
                    const selectors = [
                        "input[data-ng-model='surveyorClaimSurvey.ClaimEntry.claimAssessment.chkNilDep']",
                        "input[ng-model*='claimAssessment.chkNilDep']"
                    ];
                    let checkbox = null;
                    for (const sel of selectors) {
                        checkbox = document.querySelector(sel);
                        if (checkbox) break;
                    }
                    if (!checkbox) {
                        const labels = Array.from(document.querySelectorAll("label"));
                        const label = labels.find(l =>
                            (l.textContent || "").toLowerCase().includes("nil depreciation")
                        );
                        checkbox = label ? label.querySelector("input[type='checkbox']") : null;
                    }
                    if (!checkbox) return { ok: false, reason: "checkbox not found" };

                    const before = !!checkbox.checked;
                    if (before !== shouldCheck) {
                        checkbox.click();
                    }
                    checkbox.dispatchEvent(new Event('input', { bubbles: true }));
                    checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                    return { ok: true, before, after: !!checkbox.checked };
                }
                """,
                {"shouldCheck": should_check},
            )

            if toggle_result and toggle_result.get("ok"):
                state_label = "Yes" if should_check else "No"
                if toggle_result.get("before") != toggle_result.get("after"):
                    if isinstance(log, AutomationLogger):
                        log.success(f"Nil Depreciation checkbox set to {state_label}")
                    else:
                        log(f"  ✅ Nil Depreciation checkbox: set to {state_label}")
                else:
                    if isinstance(log, AutomationLogger):
                        log.info(f"Nil Depreciation already {state_label}")
                    else:
                        log(f"  ✅ Nil Depreciation checkbox: already {state_label}")
                await asyncio.sleep(0.3)
            else:
                reason = toggle_result.get("reason") if isinstance(toggle_result, dict) else "unknown error"
                if isinstance(log, AutomationLogger):
                    log.warning(f"Nil Depreciation checkbox: {reason}")
                else:
                    log(f"  ⚠️  Nil Depreciation checkbox: {reason}")
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Nil Depreciation", "Excel value missing or not Yes/No")
            else:
                log("  ⏭️  Nil Depreciation checkbox: skipped (Excel value missing or not Yes/No)")

        # ── Parts values ─────────────────────────────────────────────────
        if should_check:
            import re
            def parse_amt(val):
                clean = re.sub(r"[^\d.]", "", str(val or "0"))
                try:
                    return float(clean) if clean else 0.0
                except ValueError:
                    return 0.0

            v_age = parse_amt(claim.parts_age_dep_excl_gst)
            v_50  = parse_amt(claim.parts_50_dep_excl_gst)
            v_nil = parse_amt(claim.parts_nil_dep_excl_gst)
            v_target = v_age + v_50 + v_nil

            val_age = str(v_age)
            val_50 = str(v_50)
            val_nil = str(v_nil)
            val_target = str(v_target)
            
            if isinstance(log, AutomationLogger):
                log.info(f"Nil ON: Total = {v_age} + {v_50} + {v_nil} = {v_target}")
            else:
                log(f"  ⚖️  Nil ON: Total = {v_age} + {v_50} + {v_nil} = {v_target}")
        else:
            val_age = claim.parts_age_dep_excl_gst
            val_50 = claim.parts_50_dep_excl_gst
            val_nil = claim.parts_nil_dep_excl_gst
            val_target = claim.parts_gst18_amount
            
            if isinstance(log, AutomationLogger):
                log.info("Nil OFF/Blank: Using Excel values as-is")
            else:
                log("  📊 Nil OFF/Blank: Using all Excel values as-is without modification")

        _log_extraction(claim, log, "Age Dep (Metal)", val_age, "parts_age_dep_excl_gst")
        await safe_fill_amount(page, ASSESSMENT["age_dep"],
                               val_age, "Age Dep (Metal)", log,
                               source=_src("parts_age_dep_excl_gst"))
        
        _log_extraction(claim, log, "50% Dep (Plastic)", val_50, "parts_50_dep_excl_gst")
        await safe_fill_amount(page, ASSESSMENT["dep_50"],
                               val_50, "50% Dep (Plastic)", log,
                               source=_src("parts_50_dep_excl_gst"))
        
        _log_extraction(claim, log, "Nil Dep", val_nil, "parts_nil_dep_excl_gst")
        await safe_fill_amount(page, ASSESSMENT["nil_dep"],
                               val_nil, "Nil Dep", log,
                               source=_src("parts_nil_dep_excl_gst"))
        
        _log_extraction(claim, log, "Parts GST 18%", val_target, "parts_gst18_amount")
        await safe_fill_amount(page, ASSESSMENT["gst_18_parts"],
                               val_target, "Parts GST 18%", log,
                               source=_src("parts_gst18_amount") if not should_check else "Calculated")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Parts section error: {e}")
        else:
            log(f"  ❌ Parts section error: {e}")
    finally:
        if isinstance(log, AutomationLogger): log.outdent()


async def _fill_labour(page, claim: ClaimData, log, _src) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Filling Labour section...")
        log.indent()
    else:
        log("\n👷 Labour:")
        
    try:
        _log_extraction(claim, log, "Labour (Excl GST)", claim.labour_excl_gst, "labour_excl_gst")
        await safe_fill_amount(page, ASSESSMENT["labour"],
                               claim.labour_excl_gst, "Labour (Excl GST)", log,
                               source=_src("labour_excl_gst"))
        
        _log_extraction(claim, log, "Labour GST 18%", claim.labour_excl_gst, "labour_excl_gst")
        await safe_fill_amount(page, ASSESSMENT["gst_18_labour"],
                               claim.labour_excl_gst, "Labour GST 18%", log,
                               source=_src("labour_excl_gst"))
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Labour section error: {e}")
        else:
            log(f"  ❌ Labour section error: {e}")
    finally:
        if isinstance(log, AutomationLogger): log.outdent()


async def _fill_workshop_invoice(page, claim: ClaimData, log, _src) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Filling Workshop Invoice section...")
        log.indent()
    else:
        log("\n🧾 Workshop Invoice:")
        
    try:
        ws_no = str(claim.workshop_invoice_no).split(" ")[0].split("(")[0][:20]
        _log_extraction(claim, log, "WS Invoice No", ws_no, "workshop_invoice_no")
        await safe_fill(page, ASSESSMENT["ws_invoice_no"],
                        ws_no, "WS Invoice No", log,
                        source=_src("workshop_invoice_no"))
        
        _log_extraction(claim, log, "WS Invoice Date", claim.workshop_invoice_date, "workshop_invoice_date")
        await safe_fill_date(page, ASSESSMENT["ws_invoice_date"],
                             claim.workshop_invoice_date, "WS Invoice Date", log,
                             source=_src("workshop_invoice_date"))
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Workshop invoice error: {e}")
        else:
            log(f"  ❌ Workshop invoice error: {e}")
    finally:
        if isinstance(log, AutomationLogger): log.outdent()


async def _fill_other_charges(page, claim: ClaimData, log, _src) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Filling Other Charges section...")
        log.indent()
    else:
        log("\n💰 Other Charges:")
        
    try:
        _log_extraction(claim, log, "Towing Charges", claim.towing_charges, "towing_charges")
        await safe_fill_amount(page, ASSESSMENT["towing"],
                               claim.towing_charges, "Towing Charges", log,
                               source=_src("towing_charges"))
        
        _log_extraction(claim, log, "Spot Repairs", claim.spot_repairs, "spot_repairs")
        await safe_fill_amount(page, ASSESSMENT["spot_repairs"],
                               claim.spot_repairs, "Spot Repairs", log,
                               source=_src("spot_repairs"))
        
        _log_extraction(claim, log, "Voluntary Excess", claim.voluntary_excess, "voluntary_excess")
        await safe_fill_amount(page, ASSESSMENT["vol_excess"],
                               claim.voluntary_excess, "Voluntary Excess", log,
                               source=_src("voluntary_excess"))
        
        _log_extraction(claim, log, "Compulsory Excess", claim.compulsory_excess, "compulsory_excess")
        await safe_fill_amount(page, ASSESSMENT["comp_excess"],
                               claim.compulsory_excess, "Compulsory Excess", log,
                               source=_src("compulsory_excess"))
        
        _log_extraction(claim, log, "Imposed Excess", claim.imposed_excess, "imposed_excess")
        await safe_fill_amount(page, ASSESSMENT["imp_excess"],
                               claim.imposed_excess, "Imposed Excess", log,
                               source=_src("imposed_excess"))
        
        _log_extraction(claim, log, "Salvage Value", claim.salvage_value, "salvage_value")
        await safe_fill_amount(page, ASSESSMENT["salvage"],
                               claim.salvage_value, "Salvage Value", log,
                               source=_src("salvage_value"))
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Other charges error: {e}")
        else:
            log(f"  ❌ Other charges error: {e}")
    finally:
        if isinstance(log, AutomationLogger): log.outdent()


async def _fill_invoice_details(page, claim: ClaimData, log, _src) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Filling Invoice Details section...")
        log.indent()
    else:
        log("\n📋 Invoice Details:")
        
    try:
        inv_no   = claim.invoice_no   if claim.invoice_no.strip()   else claim.workshop_invoice_no
        inv_date = claim.invoice_date if claim.invoice_date.strip() else claim.workshop_invoice_date
        inv_no_clean = str(inv_no).split(" ")[0].split("(")[0][:20]
        
        _log_extraction(claim, log, "Invoice No", inv_no_clean, "invoice_no")
        await safe_fill(page, ASSESSMENT["invoice_no"],
                        inv_no_clean, "Invoice No", log,
                        source=_src("invoice_no") or _src("workshop_invoice_no"))
        
        _log_extraction(claim, log, "Invoice Date", inv_date, "invoice_date")
        await safe_fill_date(page, ASSESSMENT["invoice_date"],
                             inv_date, "Invoice Date", log,
                             source=_src("invoice_date") or _src("workshop_invoice_date"))
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Invoice details error: {e}")
        else:
            log(f"  ❌ Invoice details error: {e}")
    finally:
        if isinstance(log, AutomationLogger): log.outdent()


async def _fill_report_details(page, claim: ClaimData, log, _src) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Filling Report Details section...")
        log.indent()
    else:
        log("\n📝 Report Details:")
        
    try:
        import re
        raw_ref = claim.final_report_no or ""
        if not raw_ref.strip():
            raw_ref = claim.invoice_no or ""
        clean_report_no = re.split(r'[/\\-]', raw_ref)[-1].strip() if raw_ref else ""
        
        _log_extraction(claim, log, "Report No", clean_report_no, "final_report_no")
        await safe_fill(page, ASSESSMENT["report_no"],
                        clean_report_no, "Report No", log,
                        source=_src("final_report_no"))
        
        if claim.final_report_date and claim.final_report_date.strip():
            _log_extraction(claim, log, "Report Date", claim.final_report_date, "final_report_date")
            await safe_fill_date(page, ASSESSMENT["report_date"],
                                 claim.final_report_date, "Report Date", log,
                                 source=_src("final_report_date"))
        else:
            if isinstance(log, AutomationLogger):
                log.field_skipped("Report Date", "Report Date is missing in Excel (portal auto-fills today's date)")
            else:
                log("  ⏭️  Report Date: skipped (portal auto-fills today's date)")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Report details error: {e}")
        else:
            log(f"  ❌ Report details error: {e}")
    finally:
        if isinstance(log, AutomationLogger): log.outdent()


async def _fill_surveyor_charges(page, claim: ClaimData, log, _src) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Filling Surveyor Charges section...")
        log.indent()
    else:
        log("\n💼 Surveyor Charges:")
        
    try:
        _log_extraction(claim, log, "Travel Expenses", claim.traveling_expenses, "traveling_expenses")
        await safe_fill_amount(page, ASSESSMENT["travel"],
                               claim.traveling_expenses, "Travel Expenses", log,
                               source=_src("traveling_expenses"))
        
        _log_extraction(claim, log, "Professional Fee", claim.professional_fee, "professional_fee")
        await safe_fill_amount(page, ASSESSMENT["prof_fee"],
                               claim.professional_fee, "Professional Fee", log,
                               source=_src("professional_fee"))
        
        _log_extraction(claim, log, "Daily Allowance", claim.daily_allowance, "daily_allowance")
        await safe_fill_amount(page, ASSESSMENT["daily_allowance"],
                               claim.daily_allowance, "Daily Allowance", log,
                               source=_src("daily_allowance"))
        
        _log_extraction(claim, log, "Photo Charges", claim.photo_charges, "photo_charges")
        await safe_fill_amount(page, ASSESSMENT["photo"],
                               claim.photo_charges, "Photo Charges", log,
                               source=_src("photo_charges"))
        
        _log_extraction(claim, log, "Total Claimed Amount", str(claim.total_claimed_amount or 0), "total_claimed_amount")
        await safe_fill_amount(page, ASSESSMENT["total"],
                               str(claim.total_claimed_amount or 0), "Total Claimed Amount", log,
                               source="Calculated")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Surveyor charges error: {e}")
        else:
            log(f"  ❌ Surveyor charges error: {e}")
    finally:
        if isinstance(log, AutomationLogger): log.outdent()


async def _upload_all(page, claim: ClaimData, log, settings: dict) -> None:
    if isinstance(log, AutomationLogger):
        log.info("Uploading Assessment Documents...")
        log.indent()
    else:
        log("\n📤 Uploading Assessment Documents...")
        
    count = 0
    files_to_upload = [ (k, v) for k, v in claim.assessment_files.items() if v ]
    
    for slot_key, file_path in files_to_upload:
        upload_label = ASSESSMENT_UPLOAD_LABELS.get(slot_key, slot_key)
        try:
            ok = await _upload_by_label(page, upload_label, file_path, log,
                                         settings=settings, slot_key=slot_key)
            if ok:
                count += 1
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.upload_failed(upload_label, f"Upload error: {e}")
            else:
                log(f"  ❌ [{slot_key}] upload error: {e}")
                
    if isinstance(log, AutomationLogger):
        log.success(f"Assessment uploads complete: {count}/{len(files_to_upload)} files")
        log.outdent()
    else:
        log(f"  📁 {count}/{len(files_to_upload)} files uploaded")


async def fill_claim_assessment(page, claim: ClaimData,
                                 log_cb = print,
                                 settings: dict = None) -> None:
    """
    Fill the entire Claim Assessment tab.
    """
    log = log_cb
    defaults = load_automation_defaults(portal_id=getattr(claim, "portal_id", "uiic"))
    if isinstance(log, AutomationLogger):
        log.section = "Claim Assessment"
        log.section_start("PHASE 5: CLAIM ASSESSMENT")
    
    await click_tab(page, "assessment", log)

    if isinstance(log, AutomationLogger):
        log.info("Filling Claim Assessment tab...")
        log.indent()
        log.step(1, 4, "Parts & Labour Details")
    else:
        log("📊 Filling Claim Assessment...")

    # Helper to look up Excel source coordinate for a field
    def _src(key: str) -> str:
        return claim._excel_coords.get(key, "")

    await _fill_parts(page, claim, log, _src)
    await _fill_labour(page, claim, log, _src)
    
    if isinstance(log, AutomationLogger):
        log.step(2, 4, "Workshop & Invoice Details")
    await _fill_workshop_invoice(page, claim, log, _src)
    await _fill_other_charges(page, claim, log, _src)
    await _fill_invoice_details(page, claim, log, _src)
    await _fill_report_details(page, claim, log, _src)
    
    if isinstance(log, AutomationLogger):
        log.step(3, 4, "Surveyor Charges & Declaration")
    await _fill_surveyor_charges(page, claim, log, _src)

    # Declaration radio
    if isinstance(log, AutomationLogger):
        log.info("Filling Declaration...")
    else:
        log("\n✍️  Declaration:")
    await _click_declaration_radio(page, log)

    # Remarks
    try:
        remarks_default = str(defaults.get("remarks_default", "Done") or "Done")
        _log_extraction(claim, log, "Remarks", remarks_default, "")
        await safe_fill_portal_text(page, ASSESSMENT["remarks"],
                             remarks_default, "Remarks", log,
                             source="Automation Defaults")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.warning(f"Remarks error: {e}")
        else:
            log(f"  ⚠️  Remarks: {e}")

    if isinstance(log, AutomationLogger):
        log.step(4, 4, "Uploading Assessment Documents")
    await _upload_all(page, claim, log, settings=settings)

    if isinstance(log, AutomationLogger):
        log.success("Claim Assessment tab complete.")
        log.info("READY FOR FINAL SUBMISSION")
        log.outdent()
    else:
        log("\n✅ Claim Assessment complete.")
        log("👀 Review all tabs then click 'Final Submit' manually.")
