"""
claim_assessment.py
Fills the "Claim Assessment" tab completely:
  - Parts depreciation fields
  - Labour charges
  - Workshop invoice, towing, excess, salvage
  - Invoice + report details
  - Surveyor charges
  - Surveyor declaration (Yes)
  - Uploads 5 assessment documents
  - STOPS — does NOT submit
"""
import asyncio
import logging
import os
from typing import Callable
from app.data.data_model import ClaimData

logger = logging.getLogger(__name__)

SEL_TAB_ASSESSMENT = "a:has-text('Claim Assessment'), .nav-tabs a:has-text('Assessment')"

# Upload input selectors (in order they appear on page)
UPLOAD_SLOTS = {
    "assessment_report":  0,
    "survey_report":      1,
    "estimate":           2,
    "invoice":            3,
    "reinspection_report":4,
}


async def _fill_field(page, ng_models: list, value: str, label: str, log_cb: Callable):
    """Fill a numeric/text field. Tries multiple ng-model selectors."""
    if not value or value in ("0", ""):
        return
    for ng in ng_models:
        sel = f"input[ng-model*='{ng}'], #{ ng }"
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=3000)
            await el.triple_click()
            await el.fill(value)
            await el.press("Tab")
            await asyncio.sleep(0.4)
            log_cb(f"  ✅ {label}: {value}")
            return
        except Exception:
            continue
    # Fallback: search by placeholder or nearby label
    try:
        el = page.get_by_label(label, exact=False).first
        await el.triple_click()
        await el.fill(value)
        await el.press("Tab")
        await asyncio.sleep(0.4)
        log_cb(f"  ✅ {label} (by label): {value}")
    except Exception as e:
        log_cb(f"  ⚠️  Could not fill '{label}': {e}")


async def _fill_date(page, ng_models: list, value: str, label: str, log_cb: Callable):
    await _fill_field(page, ng_models, value, label, log_cb)


async def _click_yes_radio(page, label_text: str, log_cb: Callable):
    strategies = [
        f"tr:has-text('{label_text}') input[value='Y']",
        f"tr:has-text('{label_text}') input[value='Yes']",
        f"tr:has-text('{label_text}') label:has-text('Yes')",
        f"div:has-text('{label_text}') input[value='Y']",
    ]
    for sel in strategies:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                log_cb(f"  ✅ Yes: {label_text[:50]}")
                return
        except Exception:
            continue
    log_cb(f"  ⚠️  Could not set Yes for: {label_text[:50]}")


async def fill_claim_assessment(
    page,
    claim: ClaimData,
    log_cb: Callable[[str], None] = print,
):
    log_cb("📊 Clicking 'Claim Assessment' tab...")
    await page.locator(SEL_TAB_ASSESSMENT).first.click()
    await asyncio.sleep(2)

    # ── PARTS ─────────────────────────────────────────────────────────────────
    log_cb("🔩 Filling Parts depreciation fields...")

    await _fill_field(page, ["vehicleAgeParts", "ageBasedParts", "metalParts"],
                      claim.parts_age_dep_excl_gst, "Age-Based Parts (Excl GST)", log_cb)
    await asyncio.sleep(0.5)

    await _fill_field(page, ["parts50Dep", "rubberParts", "fiftyPercent"],
                      claim.parts_50_dep_excl_gst, "50% Dep Parts (Excl GST)", log_cb)
    await asyncio.sleep(0.5)

    await _fill_field(page, ["parts30Dep", "fiberParts", "thirtyPercent"],
                      claim.parts_30_dep_excl_gst, "30% Dep Parts (Excl GST)", log_cb)
    await asyncio.sleep(0.5)

    await _fill_field(page, ["partsNilDep", "glassParts", "nilDepreciation"],
                      claim.parts_nil_dep_excl_gst, "Nil Dep Parts (Excl GST)", log_cb)
    await asyncio.sleep(1)  # Allow GST table to auto-calculate

    # ── LABOUR ────────────────────────────────────────────────────────────────
    log_cb("👷 Filling Labour fields...")
    await _fill_field(page, ["labourCharges", "labourAmount", "labour"],
                      claim.labour_excl_gst, "Labour Charges (Excl GST)", log_cb)
    await asyncio.sleep(1)

    # ── WORKSHOP INVOICE ──────────────────────────────────────────────────────
    log_cb("🧾 Filling Workshop Invoice details...")
    await _fill_field(page, ["workshopInvoiceNo", "workshopInvNo", "invoiceNo"],
                      claim.workshop_invoice_no, "Workshop Invoice No", log_cb)
    await _fill_date(page, ["workshopInvoiceDate", "workshopInvDate", "invoiceDate"],
                     claim.workshop_invoice_date, "Workshop Invoice Date", log_cb)

    # ── OTHER CHARGES ─────────────────────────────────────────────────────────
    log_cb("💰 Filling Other Charges...")
    await _fill_field(page, ["towingCharges", "towing"],
                      claim.towing_charges, "Towing Charges", log_cb)
    await _fill_field(page, ["spotRepairs", "spot"],
                      claim.spot_repairs, "Spot Repairs", log_cb)
    await _fill_field(page, ["voluntaryExcess", "volExcess"],
                      claim.voluntary_excess, "Voluntary Excess", log_cb)
    await _fill_field(page, ["compulsoryExcess", "compExcess"],
                      claim.compulsory_excess, "Compulsory Excess", log_cb)
    await _fill_field(page, ["imposedExcess", "impExcess"],
                      claim.imposed_excess, "Imposed Excess", log_cb)
    await _fill_field(page, ["salvageValue", "salvage"],
                      claim.salvage_value, "Salvage Value", log_cb)
    await asyncio.sleep(1)  # Allow Net Assessment to auto-calculate

    # ── INVOICE DETAILS ───────────────────────────────────────────────────────
    log_cb("📋 Filling Invoice Details...")
    # Use invoice_no = workshop_invoice_no as fallback
    inv_no   = claim.invoice_no   or claim.workshop_invoice_no
    inv_date = claim.invoice_date or claim.workshop_invoice_date
    await _fill_field(page, ["finalInvoiceNo", "invNo"],
                      inv_no, "Invoice No", log_cb)
    await _fill_date(page, ["finalInvoiceDate", "invDate"],
                     inv_date, "Invoice Date", log_cb)

    # ── REPORT DETAILS ────────────────────────────────────────────────────────
    log_cb("📝 Filling Report Details...")
    await _fill_field(page, ["finalReportNo", "reportNo"],
                      claim.final_report_no, "Final Report No", log_cb)
    # Final Report Date is usually pre-filled with today — only set if value given
    if claim.final_report_date:
        await _fill_date(page, ["finalReportDate", "reportDate"],
                         claim.final_report_date, "Final Report Date", log_cb)

    # ── SURVEYOR CHARGES ──────────────────────────────────────────────────────
    log_cb("💼 Filling Surveyor Charges...")
    await _fill_field(page, ["travelingExpenses", "conveyance"],
                      claim.traveling_expenses, "Traveling Expenses", log_cb)
    await _fill_field(page, ["professionalFee", "surveyFee"],
                      claim.professional_fee, "Professional Fee", log_cb)
    await _fill_field(page, ["dailyAllowance", "da"],
                      claim.daily_allowance, "Daily Allowance", log_cb)
    await _fill_field(page, ["photoCharges", "photo"],
                      claim.photo_charges, "Photo Charges", log_cb)
    await _fill_field(page, ["totalClaimedAmount", "totalFee"],
                      claim.total_claimed_amount, "Total Claimed Amount", log_cb)

    # ── SURVEYOR DECLARATION ──────────────────────────────────────────────────
    log_cb("✍️  Setting Surveyor Declaration to Yes...")
    await _click_yes_radio(page, "perused the bills", log_cb)

    # ── UPLOAD ASSESSMENT DOCUMENTS ───────────────────────────────────────────
    log_cb(f"📤 Uploading {len(claim.assessment_files)} assessment documents...")
    for slot_key, slot_idx in UPLOAD_SLOTS.items():
        file_path = claim.assessment_files.get(slot_key)
        if not file_path:
            log_cb(f"  ⏭️  No file for slot '{slot_key}' — skipping")
            continue
        if not os.path.isfile(file_path):
            log_cb(f"  ⚠️  File not found: {file_path}")
            continue
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 2.0:
            log_cb(f"  ⚠️  File too large ({file_size_mb:.1f}MB), skipping: {os.path.basename(file_path)}")
            continue
        try:
            inputs = page.locator("input[type='file']")
            await inputs.nth(slot_idx).set_input_files(file_path)
            await asyncio.sleep(1.5)
            log_cb(f"  ✅ [{slot_key}]: {os.path.basename(file_path)}")
        except Exception as e:
            log_cb(f"  ❌ Failed to upload [{slot_key}]: {e}")

    log_cb("🛑 Claim Assessment complete — STOPPING before Final Submit.")
    log_cb("👀 Please review all filled data and click 'Final Submit' manually.")
