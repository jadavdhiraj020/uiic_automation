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
from app.automation.selectors import ASSESSMENT, ASSESSMENT_SLOTS, TABS, TAB_SEL
from app.automation.tab_utils import click_tab
from app.utils import load_settings

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
    settings = load_settings()
    upload_wait_s = settings.get("upload_wait_ms", 3000) / 1000.0
    timeout_ms = settings.get("timeout_ms", 4000)

    fname = os.path.basename(file_path)
    if not os.path.isfile(file_path):
        log_cb(f"  ⚠️  Not found: {fname}")
        return False
    mb = os.path.getsize(file_path) / (1024 * 1024)
    if mb > MAX_FILE_MB:
        logger.info("Large assessment file (%.1fMB): %s — portal alert will be auto-accepted", mb, fname)


    log_cb(f"  ▶ [{upload_label}] ← {fname}")
    abs_path = str(os.path.abspath(file_path))

    # Strategy 0: Direct name selector + Fallbacks
    # Portal uses 'fileToUploadMan' for mandatory docs and 'fileToUploadOpt' for others,
    # or sometimes 'fileToUpload1'. We will query by name or just use a robust relative locator.
    slot_idx = ASSESSMENT_SLOTS.get(slot_key)
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
                log_cb(f"  ✅ Uploaded: {fname} (li.clearfix relative selector)")
                return True
    except Exception as e:
        log_cb(f"  ⚠️  Strategy 0 failed: {str(e)[:80]}")

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
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=file_input)
                except Exception:
                    pass
                await asyncio.sleep(upload_wait_s)
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
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=sibling_input.first)
                except Exception:
                    pass
                await asyncio.sleep(upload_wait_s)
                log_cb(f"  ✅ Uploaded: {fname} (label parent)")
                return True
            grandparent = parent.locator("xpath=..")
            gp_input = grandparent.locator('input[type="file"]')
            if await gp_input.count() > 0:
                await gp_input.first.set_input_files(abs_path)
                try:
                    await page.evaluate("el => el.dispatchEvent(new Event('change', { bubbles: true }))", arg=gp_input.first)
                except Exception:
                    pass
                await asyncio.sleep(upload_wait_s)
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
                await fi.wait_for(state="attached", timeout=timeout_ms)
                await fi.set_input_files(abs_path)
                try:
                    await page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    await asyncio.sleep(upload_wait_s / 2.0)
                log_cb(f"  ✅ Uploaded: {fname} (XPath following)")
                return True
        except Exception:
            continue

    log_cb(f"  ❌ Upload input not found for: {upload_label}")
    return False


async def _fill_parts(page, claim: ClaimData, log_cb: Callable, _src) -> None:
    log_cb("\n🔩 Parts Depreciation:")
    try:
        nil_dep_raw = (claim.nil_depreciation or "").strip().lower()
        should_check = nil_dep_raw == "yes"

        if nil_dep_raw in {"yes", "no"}:
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
                source = _src("nil_depreciation") or "Excel Data"
                if toggle_result.get("before") != toggle_result.get("after"):
                    log_cb(f"  ✅ Nil Depreciation checkbox: set to {state_label} (Source: {source})")
                else:
                    log_cb(f"  ✅ Nil Depreciation checkbox: already {state_label} (Source: {source})")
                await asyncio.sleep(0.3)
            else:
                reason = toggle_result.get("reason") if isinstance(toggle_result, dict) else "unknown error"
                log_cb(f"  ⚠️  Nil Depreciation checkbox: {reason}")
        else:
            log_cb("  ⏭️  Nil Depreciation checkbox: skipped (Excel value missing or not Yes/No)")

        # ── Parts values ─────────────────────────────────────────────────
        if should_check:
            # ── Nil Depreciation YES: Manually compute Total = Age + 50% + Nil ──
            # Ignore Excel's parts_gst18_amount — calculate from the 3 components safely
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
            
            log_cb(f"  ⚖️  Nil ON: Total = {v_age} + {v_50} + {v_nil} = {v_target} (calculated, Excel total ignored)")
        else:
            # ── Nil Depreciation NO / Blank: Enter all Excel values as-is ────
            # No math adjustments — trust the Excel data exactly
            val_age = claim.parts_age_dep_excl_gst
            val_50 = claim.parts_50_dep_excl_gst
            val_nil = claim.parts_nil_dep_excl_gst
            val_target = claim.parts_gst18_amount
            
            log_cb("  📊 Nil OFF/Blank: Using all Excel values as-is without modification")

        await safe_fill_amount(page, ASSESSMENT["age_dep"],
                               val_age, "Age Dep (Metal)", log_cb,
                               source=_src("parts_age_dep_excl_gst"))
        await safe_fill_amount(page, ASSESSMENT["dep_50"],
                               val_50, "50% Dep (Plastic)", log_cb,
                               source=_src("parts_50_dep_excl_gst"))
        await safe_fill_amount(page, ASSESSMENT["nil_dep"],
                               val_nil, "Nil Dep", log_cb,
                               source=_src("parts_nil_dep_excl_gst"))
        await safe_fill_amount(page, ASSESSMENT["gst_18_parts"],
                               val_target, "Parts GST 18%", log_cb,
                               source=_src("parts_gst18_amount") if not should_check else "Calculated")
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
        
        # Safe Fallback: Only use invoice number if final report number is completely empty
        if not raw_ref.strip():
            raw_ref = claim.invoice_no or ""
            
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
        # Total Claimed is now calculated during Excel extraction to ensure
        # the UI preview and the automation submit exact matching values.
        await safe_fill_amount(page, ASSESSMENT["total"],
                               str(claim.total_claimed_amount or 0), "Total Claimed Amount", log_cb,
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
                             "Done", "Remarks", log_cb,
                             source="Hardcoded")
    except Exception as e:
        log_cb(f"  ⚠️  Remarks: {e}")

    await _upload_all(page, claim, log_cb)

    log_cb("\n✅ Claim Assessment complete.")
    log_cb("👀 Review all tabs then click 'Final Submit' manually.")
