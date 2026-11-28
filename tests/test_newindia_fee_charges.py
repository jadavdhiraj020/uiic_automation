"""New India fee-bill charges must come from the two configured cells."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from app.data.excel_reader import extract_claim_data


@pytest.fixture
def fee_mapping():
    source = Path(__file__).resolve().parents[1] / "app/portals/newindia/config/field_mapping.json"
    mapping = json.loads(source.read_text(encoding="utf-8"))
    return {key: mapping[key] for key in ("sfb_reinspection_charges", "sfb_misc_charge", "sfb_others")}


def _workbook(path, reinspection, misc, *, shifted=False):
    wb = openpyxl.Workbook()
    # A sheet literally named Sheet2 may appear elsewhere; the fee bill is
    # still the second worksheet, by position.
    wb.active.title = "Sheet2"
    ws = wb.create_sheet("Survey fee Bill")
    row = 38 if shifted else 33
    ws.cell(row, 3, "RE-INSPECTION")
    ws.cell(row, 8, reinspection)
    ws.cell(row + 2, 3, "MISC.")
    ws.cell(row + 2, 8, misc)
    wb.save(path)
    wb.close()


@pytest.mark.parametrize(
    ("reinspection", "misc", "expected"),
    [(500, 150, "650"), (0, 200, "200"), (500, None, "500"),
     (None, None, "0"), ("₹1,200.50", "25.25", "1225.75")],
)
def test_excel_charge_sum_is_read_from_fee_sheet(
    tmp_path, monkeypatch, fee_mapping, reinspection, misc, expected,
):
    source = tmp_path / "main.xlsx"
    _workbook(source, reinspection, misc, shifted=True)
    monkeypatch.setattr("app.utils.load_field_mapping", lambda **kwargs: fee_mapping)
    monkeypatch.setattr("app.utils.load_automation_defaults", lambda **kwargs: {})

    claim = extract_claim_data(str(source), portal_id="newindia")
    assert claim.sfb_others == expected
    assert not getattr(claim, "_newindia_sfb_others_issue", "")
    assert "Survey fee Bill" in claim._excel_coords["sfb_misc_charge"]


@pytest.mark.parametrize("bad_value", ["?", "not known", "=1+2"])
def test_unreadable_charge_is_not_used_as_a_partial_total(tmp_path, monkeypatch, fee_mapping, bad_value):
    source = tmp_path / "main.xlsx"
    _workbook(source, 500, bad_value)
    monkeypatch.setattr("app.utils.load_field_mapping", lambda **kwargs: fee_mapping)
    monkeypatch.setattr("app.utils.load_automation_defaults", lambda **kwargs: {})

    claim = extract_claim_data(str(source), portal_id="newindia")
    assert claim.sfb_others == ""
    assert "Misc" in claim._newindia_sfb_others_issue
    assert any("Others needs review" in warning for warning in claim._validate_newindia()[1])


def test_configured_column_offset_is_honoured(tmp_path, monkeypatch, fee_mapping):
    source = tmp_path / "main.xlsx"
    _workbook(source, None, None)
    wb = openpyxl.load_workbook(source)
    wb.worksheets[1]["G33"] = 75
    wb.worksheets[1]["G35"] = 25
    wb.save(source)
    wb.close()
    fee_mapping["sfb_reinspection_charges"]["col_offset"] = 4
    fee_mapping["sfb_misc_charge"]["col_offset"] = 4
    monkeypatch.setattr("app.utils.load_field_mapping", lambda **kwargs: fee_mapping)
    monkeypatch.setattr("app.utils.load_automation_defaults", lambda **kwargs: {})
    assert extract_claim_data(str(source), portal_id="newindia").sfb_others == "100"


def test_unreadable_others_requests_review_before_fee_bill_save(tmp_path, monkeypatch):
    from app.data.data_model import ClaimData
    from app.portals.newindia.automation import survey_fee_bill_module as module

    pdf = tmp_path / "survey_fee_bill.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    claim = ClaimData(portal_id="newindia")
    claim.sfb_invoice_number = "S-10"
    claim.sfb_invoice_date = "12/11/2026"
    claim.assessment_files = {"survey_fee_bill": str(pdf)}
    claim._scan_result = SimpleNamespace(excel_path="main.xlsx")
    claim._newindia_sfb_others_issue = "Misc: amount is unreadable."
    recovery = SimpleNamespace(record_field_issue=MagicMock(), review_before_save=AsyncMock(return_value=False))
    monkeypatch.setattr(module, "load_automation_defaults", lambda **kwargs: {})
    for name in ("dismiss_portal_popup", "_expand_survey_fee_bill_accordion",
                 "select_dropdown_with_delay", "fill_input_with_delay", "_fill_hsn_code_typeahead"):
        monkeypatch.setattr(module, name, AsyncMock())
    monkeypatch.setattr(module, "upload_file_via_input", AsyncMock(return_value=True))
    monkeypatch.setattr(module, "_click_visible_enabled_button", AsyncMock(return_value=(True, "")))
    submit = AsyncMock()
    monkeypatch.setattr(module, "_click_survey_fee_bill_submit", submit)
    token = module.current_recovery.set(recovery)
    try:
        assert not asyncio.run(module._fill_survey_fee_bill_inner(None, claim, lambda message: None, lambda: False, 0))
    finally:
        module.current_recovery.reset(token)
    assert any(call.args[1] == "Others" for call in recovery.record_field_issue.call_args_list)
    submit.assert_not_awaited()
