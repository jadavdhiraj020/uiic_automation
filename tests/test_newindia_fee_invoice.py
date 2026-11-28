"""The surveyor fee reference and date are independent of workshop invoices."""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from app.data.excel_reader import extract_claim_data
from app.portals.newindia.pdf_report import _fee_invoice_candidates
from app.portals.oic.pdf_layout import Line


@pytest.fixture
def mapping():
    config = Path(__file__).resolve().parents[1] / "app/portals/newindia/config/field_mapping.json"
    full = json.loads(config.read_text(encoding="utf-8"))
    return {name: full[name] for name in (
        "vendor_invoice_number", "vendor_invoice_date", "sfb_invoice_number", "sfb_invoice_date",
        "sfb_reinspection_charges", "sfb_misc_charge", "sfb_others",
    )}


def _source(path, ref, date):
    wb = openpyxl.Workbook()
    survey = wb.active
    survey.title = "Survey report"
    survey["A1"], survey["B1"] = "Vendor/Tax Invoice Number", "W-42"
    survey["A2"], survey["B2"] = "Vendor/Tax Invoice Date", datetime(2026, 11, 1)
    fee = wb.create_sheet("Survey fee Bill")
    fee["C7"], fee["D7"] = "Ref:", ref
    fee["K7"], fee["L7"] = "Date:", date
    fee["C33"], fee["C35"] = "RE-INSPECTION", "MISC."
    wb.save(path)
    wb.close()


def _extract(path, monkeypatch, mapping):
    monkeypatch.setattr("app.utils.load_field_mapping", lambda **kwargs: mapping)
    monkeypatch.setattr("app.utils.load_automation_defaults", lambda **kwargs: {})
    return extract_claim_data(str(path), portal_id="newindia")


def test_excel_keeps_workshop_and_fee_invoice_values_separate(tmp_path, monkeypatch, mapping):
    source = tmp_path / "main.xlsx"
    _source(source, "S-10", datetime(2026, 11, 12))
    claim = _extract(source, monkeypatch, mapping)
    assert claim.vendor_invoice_number == "W-42"
    assert claim.vendor_invoice_date == "01/11/2026"
    assert claim.sfb_invoice_number == "S-10"
    assert claim.sfb_invoice_date == "12/11/2026"
    assert "Survey fee Bill" in claim._excel_coords["sfb_invoice_number"]


@pytest.mark.parametrize("ref,date", [(None, None), ("=A1", "not a date")])
def test_missing_fee_values_are_not_replaced_with_workshop_values(tmp_path, monkeypatch, mapping, ref, date):
    source = tmp_path / "main.xlsx"
    _source(source, ref, date)
    claim = _extract(source, monkeypatch, mapping)
    assert claim.vendor_invoice_number == "W-42"
    assert claim.sfb_invoice_number == ""
    assert claim.sfb_invoice_date == ""
    assert set(claim._newindia_sfb_invoice_issues) == {"sfb_invoice_number", "sfb_invoice_date"}


def test_fee_invoice_column_mapping_can_be_changed(tmp_path, monkeypatch, mapping):
    source = tmp_path / "main.xlsx"
    _source(source, None, None)
    wb = openpyxl.load_workbook(source)
    wb.worksheets[1]["E7"] = "S-20"
    wb.worksheets[1]["M7"] = datetime(2026, 11, 20)
    wb.save(source)
    wb.close()
    mapping["sfb_invoice_number"]["col_offset"] = 2
    mapping["sfb_invoice_date"]["col_offset"] = 2
    claim = _extract(source, monkeypatch, mapping)
    assert (claim.sfb_invoice_number, claim.sfb_invoice_date) == ("S-20", "20/11/2026")


def test_later_uncached_date_formula_does_not_hide_top_date(tmp_path, monkeypatch, mapping):
    source = tmp_path / "main.xlsx"
    _source(source, "S-10", datetime(2026, 11, 12))
    wb = openpyxl.load_workbook(source)
    wb.worksheets[1]["K20"], wb.worksheets[1]["L20"] = "Date:", "=TODAY()"
    wb.save(source)
    wb.close()
    assert _extract(source, monkeypatch, mapping).sfb_invoice_date == "12/11/2026"


def test_pdf_reads_fee_bill_reference_and_date_on_same_line(mapping):
    rows = [Line(2, 15, ((0, 200, "Ref: S-10 Date: 12/11/2026"),))]
    found = _fee_invoice_candidates(rows, mapping)
    assert found["sfb_invoice_number"][0][0] == "S-10"
    assert found["sfb_invoice_date"][0][0] == "12/11/2026"


def test_uncertain_ocr_does_not_create_a_fee_invoice(mapping):
    rows = [Line(2, 15, ((0, 200, "Ref: S-10 Date: 12/11/2026"),), confidence=0.5)]
    assert not _fee_invoice_candidates(rows, mapping)


def test_conflicting_ocr_does_not_override_clear_reference(mapping):
    rows = [Line(2, 15, ((0, 100, "Ref: S-10"),)),
            Line(2, 25, ((0, 100, "Ref: S-20"),), confidence=0.5)]
    assert "sfb_invoice_number" not in _fee_invoice_candidates(rows, mapping)


def test_fee_bill_page_receives_fee_invoice_not_workshop_invoice(tmp_path, monkeypatch):
    from app.data.data_model import ClaimData
    from app.portals.newindia.automation import survey_fee_bill_module as module

    fee = tmp_path / "survey_fee_bill.pdf"
    fee.write_bytes(b"%PDF-1.4\n")
    claim = ClaimData(portal_id="newindia", vendor_invoice_number="W-42",
                      vendor_invoice_date="01/11/2026", sfb_invoice_number="S-10",
                      sfb_invoice_date="12/11/2026")
    claim.assessment_files = {"survey_fee_bill": str(fee)}
    claim._scan_result = SimpleNamespace(excel_path="main.xlsx")
    recovery = SimpleNamespace(record_field_issue=MagicMock(), review_before_save=AsyncMock(return_value=True))
    monkeypatch.setattr(module, "load_automation_defaults", lambda **kwargs: {})
    for name in ("_expand_survey_fee_bill_accordion", "select_dropdown_with_delay", "_fill_hsn_code_typeahead"):
        monkeypatch.setattr(module, name, AsyncMock())
    fill = AsyncMock()
    monkeypatch.setattr(module, "fill_input_with_delay", fill)
    monkeypatch.setattr(module, "dismiss_portal_popup", AsyncMock(side_effect=[None, None, "success", "success"]))
    monkeypatch.setattr(module, "upload_file_via_input", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "_click_visible_enabled_button", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(module, "_click_survey_fee_bill_submit", AsyncMock(return_value=True))
    token = module.current_recovery.set(recovery)
    try:
        assert asyncio.run(module._fill_survey_fee_bill_inner(None, claim, lambda message: None, lambda: False, 0))
    finally:
        module.current_recovery.reset(token)
    values = {call.args[3]: call.args[2] for call in fill.await_args_list}
    assert values["SFB Invoice Number"] == "S-10"
    assert values["SFB Invoice Date"] == "12/11/2026"
