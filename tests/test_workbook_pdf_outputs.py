"""Regression coverage for the three worksheet PDF outputs."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pypdfium2
import pytest

from app.data import folder_scanner
from app.portals.newindia.automation.survey_fee_bill_module import (
    _find_survey_fee_bill_document,
)
from app.portals.oic import generated_files


def _write_pdf(path):
    document = pypdfium2.PdfDocument.new()
    page = document.new_page(width=100, height=100)
    page.close()
    document.save(str(path))
    document.close()


@pytest.fixture
def claim_folder(tmp_path, monkeypatch):
    folder = tmp_path / "claim"
    folder.mkdir()
    workbook = openpyxl.Workbook()
    workbook.active.title = "Survey report"
    workbook.create_sheet("Survey fee Bill")
    workbook.create_sheet("Re-inspection")
    workbook.save(folder / "main.xlsx")
    workbook.close()

    monkeypatch.setattr(
        generated_files, "user_data_dir",
        lambda *parts: str(tmp_path.joinpath("app", *parts)),
    )
    monkeypatch.setattr(
        folder_scanner, "get_doc_mapping_tuple",
        lambda **kwargs: ({}, {}, [], [], {}, []),
    )
    monkeypatch.setattr(
        "app.utils.load_automation_defaults",
        lambda **kwargs: {
            "printable_print_mode": "column_range",
            "printable_column_range": "A:L",
            "printable_scale_percentage": 80,
        },
    )
    monkeypatch.setattr(
        "app.portals.registry.get_portal",
        lambda portal_id: SimpleNamespace(requires_document_merge=False),
    )
    monkeypatch.setattr(
        "app.data.printable_excel_service._generate_pdf",
        lambda source, output, logs, **kwargs: (_write_pdf(output) or True),
    )
    return folder


@pytest.mark.parametrize("portal", ["uiic", "newindia", "oic"])
def test_fee_bill_and_reinspection_use_the_selected_range(claim_folder, monkeypatch, portal):
    calls = []

    def export(source, output, sheet_index, **settings):
        calls.append((sheet_index, settings))
        _write_pdf(output)
        return True

    monkeypatch.setattr(folder_scanner, "run_headless_reinspection_com", export)
    result = folder_scanner.scan_folder(str(claim_folder), portal_id=portal)

    assert Path(result.assessment_files["survey_fee_bill"]).name == "survey_fee_bill.pdf"
    assert not result.survey_fee_bill_error
    assert {index for index, _ in calls} == {1, 2}
    for _, settings in calls:
        assert settings == {
            "print_mode": "column_range", "scale": None, "col_range": ("A", "L"),
        }


def test_fee_bill_is_refreshed_across_portals_without_reusing_it_as_input(
    claim_folder, monkeypatch,
):
    calls = []

    def export(source, output, sheet_index, **settings):
        calls.append(sheet_index)
        _write_pdf(output)
        return True

    monkeypatch.setattr(folder_scanner, "run_headless_reinspection_com", export)
    for portal in ("newindia", "oic", "uiic", "newindia"):
        result = folder_scanner.scan_folder(str(claim_folder), portal_id=portal)
        fee_bill = claim_folder / "survey_fee_bill.pdf"
        assert result.assessment_files["survey_fee_bill"] == str(fee_bill)
        assert fee_bill not in map(Path, result.claim_related_files)
        assert result.excel_path == str(claim_folder / "main.xlsx")
        assert not result.survey_fee_bill_error
    assert calls.count(1) == 4
    assert len(list(claim_folder.glob("survey_fee_bill*.pdf"))) == 1


def test_generated_fee_bill_is_not_reused_as_pdf_source(tmp_path, monkeypatch):
    from app.data.data_model import ClaimData
    from app.data.report_reader import find_main_report_source
    from app.portals.newindia.scan_outputs import is_scan_output
    from app.portals.oic.pdf_report import supplement_oic_pdf_fees

    folder = tmp_path / "claim"
    folder.mkdir()
    monkeypatch.setattr(
        generated_files, "user_data_dir",
        lambda *parts: str(tmp_path.joinpath("app", *parts)),
    )
    staged = tmp_path / "staged.pdf"
    _write_pdf(staged)
    fee_bill = folder / "survey_fee_bill.pdf"
    generated_files.publish_generated(staged, fee_bill, portal_id="shared")

    # A generated fee bill is not a survey report or fresh fee input.
    assert is_scan_output(fee_bill, {})
    scan = SimpleNamespace(excel_path=None, assessment_files={})
    assert find_main_report_source(str(folder), scan, "uiic") is None
    read_pdf = MagicMock(side_effect=AssertionError("Generated fee bill was read again"))
    monkeypatch.setattr("app.data.pdf_report_reader.read_lines", read_pdf)
    claim = ClaimData(portal_id="oic")
    claim._oic_pdf_review_warnings = []
    supplement_oic_pdf_fees(claim, str(folder))
    read_pdf.assert_not_called()


def test_existing_user_fee_bill_is_preserved_for_review(claim_folder, monkeypatch):
    fee_bill = claim_folder / "survey_fee_bill.pdf"
    original = b"user supplied document"
    fee_bill.write_bytes(original)

    def export(source, output, sheet_index, **settings):
        _write_pdf(output)
        return True

    monkeypatch.setattr(folder_scanner, "run_headless_reinspection_com", export)
    result = folder_scanner.scan_folder(str(claim_folder), portal_id="newindia")

    assert fee_bill.read_bytes() == original
    assert "survey_fee_bill" not in result.assessment_files
    assert result.survey_fee_bill_error
    assert result.survey_fee_bill_error in result.policy_warnings


def test_locked_fee_bill_keeps_previous_copy_but_requires_review(claim_folder, monkeypatch):
    def export(source, output, sheet_index, **settings):
        _write_pdf(output)
        return True

    monkeypatch.setattr(folder_scanner, "run_headless_reinspection_com", export)
    first = folder_scanner.scan_folder(str(claim_folder), portal_id="newindia")
    fee_bill = Path(first.assessment_files["survey_fee_bill"])
    previous = fee_bill.read_bytes()

    def locked(*args, **kwargs):
        raise PermissionError("The fee bill is open.")

    monkeypatch.setattr(generated_files, "publish_generated", locked)
    second = folder_scanner.scan_folder(str(claim_folder), portal_id="newindia")
    assert fee_bill.read_bytes() == previous
    assert "survey_fee_bill" not in second.assessment_files
    assert second.survey_fee_bill_error


def test_missing_second_sheet_is_reported(claim_folder):
    workbook_path = claim_folder / "main.xlsx"
    workbook = openpyxl.load_workbook(workbook_path)
    workbook.remove(workbook["Survey fee Bill"])
    workbook.remove(workbook["Re-inspection"])
    workbook.save(workbook_path)
    workbook.close()

    result = folder_scanner.scan_folder(str(claim_folder), portal_id="newindia")
    assert "survey_fee_bill" not in result.assessment_files
    assert "sheet 2" in result.survey_fee_bill_error
    assert result.survey_fee_bill_error in result.policy_warnings


def test_newindia_uses_fee_bill_and_does_not_replace_it_with_workshop_invoice(tmp_path):
    fee_bill = tmp_path / "survey_fee_bill.pdf"
    invoice = tmp_path / "invoice.pdf"
    _write_pdf(fee_bill)
    _write_pdf(invoice)
    data = SimpleNamespace(
        assessment_files={"survey_fee_bill": str(fee_bill), "invoice": str(invoice)},
        upload_doc_files={}, claim_doc_files={},
        _scan_result=SimpleNamespace(excel_path="main.xlsx"),
    )
    assert _find_survey_fee_bill_document(data) == str(fee_bill)

    fee_bill.unlink()
    assert _find_survey_fee_bill_document(data) == ""

    data._scan_result.excel_path = None
    assert _find_survey_fee_bill_document(data) == str(invoice)


def test_missing_fee_bill_is_shown_during_extraction_review(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QLabel
    from app.ui.components.workspace_page import DataReviewPanel

    application = QApplication.instance() or QApplication([])
    panel = DataReviewPanel()
    claim = SimpleNamespace(
        source_report_path="main.xlsx",
        _scan_result=SimpleNamespace(survey_fee_bill_error="Check sheet 2."),
        validate=lambda: ([], []),
        all_fields_for_preview=lambda: [],
    )
    panel.update_data(claim, "newindia")
    labels = [label.text() for label in panel.validation_chips.findChildren(QLabel)]
    assert "Survey Fee Bill PDF" in labels
    assert application is not None


def test_newindia_requests_review_before_saving_without_fee_bill(tmp_path, monkeypatch):
    from app.data.data_model import ClaimData
    from app.portals.newindia.automation import survey_fee_bill_module as module

    invoice = tmp_path / "invoice.pdf"
    _write_pdf(invoice)
    claim = ClaimData(portal_id="newindia")
    claim.assessment_files = {"invoice": str(invoice)}
    claim._scan_result = SimpleNamespace(excel_path="main.xlsx")

    recovery = SimpleNamespace(
        record_field_issue=MagicMock(),
        review_before_save=AsyncMock(return_value=False),
    )
    monkeypatch.setattr(module, "load_automation_defaults", lambda **kwargs: {})
    for name in (
        "dismiss_portal_popup", "_expand_survey_fee_bill_accordion",
        "select_dropdown_with_delay", "fill_input_with_delay", "_fill_hsn_code_typeahead",
    ):
        monkeypatch.setattr(module, name, AsyncMock())
    submit = AsyncMock()
    monkeypatch.setattr(module, "_click_survey_fee_bill_submit", submit)
    token = module.current_recovery.set(recovery)
    try:
        result = asyncio.run(module._fill_survey_fee_bill_inner(
            None, claim, lambda message: None, lambda: False, 0,
        ))
    finally:
        module.current_recovery.reset(token)

    assert result is False
    assert recovery.record_field_issue.call_args.args[1] == "Survey Fee Bill Document"
    recovery.review_before_save.assert_awaited_once()
    submit.assert_not_awaited()


def test_newindia_attaches_generated_fee_bill(tmp_path, monkeypatch):
    from app.data.data_model import ClaimData
    from app.portals.newindia.automation import survey_fee_bill_module as module

    invoice = tmp_path / "invoice.pdf"
    fee_bill = tmp_path / "survey_fee_bill.pdf"
    _write_pdf(invoice)
    _write_pdf(fee_bill)
    claim = ClaimData(portal_id="newindia")
    claim.assessment_files = {"invoice": str(invoice), "survey_fee_bill": str(fee_bill)}
    claim._scan_result = SimpleNamespace(excel_path="main.xlsx")
    recovery = SimpleNamespace(
        record_field_issue=MagicMock(), review_before_save=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(module, "load_automation_defaults", lambda **kwargs: {})
    for name in (
        "_expand_survey_fee_bill_accordion", "select_dropdown_with_delay",
        "fill_input_with_delay", "_fill_hsn_code_typeahead",
    ):
        monkeypatch.setattr(module, name, AsyncMock())
    monkeypatch.setattr(
        module, "dismiss_portal_popup",
        AsyncMock(side_effect=[None, None, "success", "success"]),
    )
    monkeypatch.setattr(module, "_click_visible_enabled_button", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(module, "_click_survey_fee_bill_submit", AsyncMock(return_value=True))
    attach = AsyncMock(return_value=True)
    monkeypatch.setattr(module, "upload_file_via_input", attach)
    token = module.current_recovery.set(recovery)
    try:
        assert asyncio.run(module._fill_survey_fee_bill_inner(
            None, claim, lambda message: None, lambda: False, 0,
        ))
    finally:
        module.current_recovery.reset(token)
    assert attach.await_args.kwargs["file_path"] == str(fee_bill)
    recovery.record_field_issue.assert_not_called()


@pytest.mark.parametrize(
    ("mode", "scale", "col_range", "expected_area", "expected_zoom"),
    [
        ("column_range", None, ("A", "L"), "$A:$L", False),
        ("scale_percentage", 80, None, "", 80),
    ],
)
def test_reinspection_export_applies_the_print_setting(
    tmp_path, monkeypatch, mode, scale, col_range, expected_area, expected_zoom,
):
    import pythoncom
    import win32com.client
    from app.data import printable_excel_service

    sheet = MagicMock()
    sheet.PageSetup = SimpleNamespace(
        PrintArea="original", Zoom="original", FitToPagesWide=None, FitToPagesTall=None,
    )
    workbook = MagicMock()
    workbook.Worksheets.Count = 3
    workbook.Worksheets.return_value = sheet
    excel = MagicMock()
    excel.Workbooks.Open.return_value = workbook
    monkeypatch.setattr(win32com.client, "DispatchEx", lambda name: excel)
    monkeypatch.setattr(pythoncom, "CoInitialize", lambda: None)
    monkeypatch.setattr(pythoncom, "CoUninitialize", lambda: None)
    monkeypatch.setattr(printable_excel_service, "_get_excel_pid", lambda app: None)

    assert folder_scanner.run_headless_reinspection_com(
        str(tmp_path / "source.xlsx"), str(tmp_path / "output.pdf"), 2,
        print_mode=mode, scale=scale, col_range=col_range,
    )
    assert sheet.PageSetup.PrintArea == expected_area
    assert sheet.PageSetup.Zoom == expected_zoom
    if mode == "column_range":
        assert sheet.PageSetup.FitToPagesWide == 1
        assert sheet.PageSetup.FitToPagesTall is False
    workbook.Close.assert_called_with(SaveChanges=False)
