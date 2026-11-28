"""Keep New India's working files out of the claim folder."""

from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pypdfium2

from app.data import folder_scanner
from app.data.assessment_generator import (
    generate_primary_assessment_from_pdf_result,
    generate_primary_assessment_result,
)
from app.portals.newindia.pdf_report import find_newindia_report
from app.portals.newindia.scan_outputs import is_scan_output, refresh_printable_output
from app.portals.oic import generated_files


def _owners(monkeypatch, tmp_path):
    monkeypatch.setattr(generated_files, "user_data_dir", lambda *parts: str(tmp_path.joinpath("app", *parts)))


def _write_pdf(path):
    document = pypdfium2.PdfDocument.new()
    page = document.new_page(width=100, height=100)
    page.close()
    document.save(str(path))
    document.close()


def test_printable_pdf_is_published_as_survey_report_without_a_workbook_copy(tmp_path, monkeypatch):
    _owners(monkeypatch, tmp_path)
    folder = tmp_path / "claim"
    folder.mkdir()
    source = folder / "main.xlsx"
    source.write_bytes(b"original")
    existing_copy = folder / "Printable_Assessment.xlsx"
    existing_copy.write_bytes(b"existing user file")

    def render(source_excel_path, output_folder, settings, logs, stop_cb=None):
        excel = Path(output_folder) / "Printable_Assessment.xlsx"
        pdf = Path(output_folder) / settings["printable_output_pdf_name"]
        excel.write_bytes(b"temporary workbook")
        pdf.write_bytes(b"%PDF-1.4\nnew")
        return str(excel), str(pdf)

    monkeypatch.setattr("app.data.printable_excel_service.process_printable_output", render)
    # Even when an older saved config still carries Printable_Assessment.pdf, New India outputs survey_report.pdf.
    refresh_printable_output(
        str(source), str(folder), {"printable_output_pdf_name": "Printable_Assessment.pdf"}, [],
    )
    assert (folder / "survey_report.pdf").read_bytes().endswith(b"new")
    assert not (folder / "Printable_Assessment.pdf").exists()
    assert existing_copy.read_bytes() == b"existing user file"
    assert source.read_bytes() == b"original"
    assert is_scan_output(folder / "survey_report.pdf", {})
    assert not list(folder.glob(".nia-scan-*"))


def test_failed_pdf_does_not_leave_a_printable_workbook(tmp_path, monkeypatch):
    _owners(monkeypatch, tmp_path)
    source = tmp_path / "main.xlsx"
    source.write_bytes(b"original")

    def render(source_excel_path, output_folder, settings, logs, stop_cb=None):
        excel = Path(output_folder) / "Printable_Assessment.xlsx"
        excel.write_bytes(b"temporary workbook")
        return (str(excel),)

    monkeypatch.setattr("app.data.printable_excel_service.process_printable_output", render)
    logs = []
    refresh_printable_output(str(source), str(tmp_path), {}, logs)
    assert not (tmp_path / "Printable_Assessment.xlsx").exists()
    assert not (tmp_path / "survey_report.pdf").exists()
    assert any("Warning: Printable survey PDF" in line for line in logs)


def test_user_supplied_survey_report_is_preserved_and_readable(tmp_path, monkeypatch):
    _owners(monkeypatch, tmp_path)
    folder = tmp_path / "claim"
    folder.mkdir()
    source = folder / "main.xlsx"
    source.write_bytes(b"original")
    user_pdf = folder / "survey_report.pdf"
    _write_pdf(user_pdf)
    original_bytes = user_pdf.read_bytes()

    def render(source_excel_path, output_folder, settings, logs, stop_cb=None):
        pdf = Path(output_folder) / settings["printable_output_pdf_name"]
        pdf.write_bytes(b"%PDF-1.4\napp generated")
        return (str(pdf),)

    monkeypatch.setattr("app.data.printable_excel_service.process_printable_output", render)
    monkeypatch.setattr("app.portals.newindia.pdf_report.load_automation_defaults", lambda **kwargs: {})
    monkeypatch.setattr(
        "app.portals.newindia.pdf_report.read_lines",
        lambda path, **kwargs: [SimpleNamespace(page=1, line=1, text="FINAL MOTOR SURVEY REPORT")],
    )
    logs = []
    refresh_printable_output(str(source), str(folder), {}, logs)
    assert user_pdf.read_bytes() == original_bytes
    assert any("survey_report.pdf skipped" in line for line in logs)
    assert not is_scan_output(user_pdf, {})
    assert find_newindia_report(str(folder)) == str(user_pdf)

    # An App3-owned survey_report.pdf is skipped by PDF-only report discovery.
    staged = tmp_path / "staged.pdf"
    _write_pdf(staged)
    user_pdf.unlink()
    generated_files.publish_generated(staged, user_pdf, portal_id="newindia")
    assert is_scan_output(user_pdf, {})
    assert find_newindia_report(str(folder)) is None


def test_newindia_skips_work_approval_fallback_and_excludes_app_survey_report_on_rescan(tmp_path, monkeypatch):
    _owners(monkeypatch, tmp_path)
    folder = tmp_path / "claim"
    folder.mkdir()
    _write_pdf(folder / "Invoice.pdf")
    _write_pdf(folder / "Estimate.pdf")
    legacy_fallback = folder / "work_approval_fallback.pdf"
    _write_pdf(legacy_fallback)

    # Simulate an App3-generated survey_report.pdf and legacy Printable_Assessment.pdf in the folder.
    staged = tmp_path / "staged.pdf"
    _write_pdf(staged)
    app_survey = folder / "survey_report.pdf"
    generated_files.publish_generated(staged, app_survey, portal_id="newindia")
    legacy_printable = folder / "Printable_Assessment.pdf"
    _write_pdf(legacy_printable)

    monkeypatch.setattr(
        folder_scanner, "get_doc_mapping_tuple",
        lambda **kwargs: (
            {"Work Approval Document": ["cashless"]},
            {"invoice": ["invoice"]},
            [],
            ["Chassis Number Photograph"],
            {},
            [],
        ),
    )
    monkeypatch.setattr("app.utils.load_automation_defaults", lambda **kwargs: {})
    monkeypatch.setattr(
        "app.portals.registry.get_portal",
        lambda portal_id: SimpleNamespace(requires_document_merge=(portal_id == "newindia")),
    )

    nia_scan = folder_scanner.scan_folder(str(folder), portal_id="newindia")
    assert "Work Approval Document" not in nia_scan.claim_doc_files
    assert nia_scan.assessment_files["invoice"] == str(folder / "Invoice.pdf")
    assert [Path(p).name for p in nia_scan.claim_related_files] == ["Estimate.pdf"]

    # Remove the legacy fallback and confirm New India does not recreate it, while UIIC still does.
    legacy_fallback.unlink()
    nia_clean = folder_scanner.scan_folder(str(folder), portal_id="newindia")
    assert not legacy_fallback.exists()
    assert "Work Approval Document" not in nia_clean.claim_doc_files

    uiic_scan = folder_scanner.scan_folder(str(folder), portal_id="uiic")
    assert legacy_fallback.is_file()
    assert uiic_scan.claim_doc_files["Work Approval Document"] == str(legacy_fallback)


def test_pdf_assessment_keeps_workbook_without_writing_audit(tmp_path, monkeypatch):
    _owners(monkeypatch, tmp_path)
    monkeypatch.setattr("app.data.assessment_generator.load_automation_defaults", lambda **kwargs: {})
    old_audit = tmp_path / "auto_primary_assessment_audit.txt"
    old_audit.write_text("existing audit", encoding="utf-8")
    rows = [{"category": "Spare Parts", "description": "Parts at Cost", "part_name": "Bumper",
             "service_type": "REPLACE", "estimated_amount": 500, "billed_amount": 500,
             "assessed_amount": 500, "depreciation_pct": 0, "hsn_code": "8512", "gst_pct": 18}]
    result = generate_primary_assessment_from_pdf_result(rows, [], "survey.pdf", str(tmp_path))
    assert Path(result.output_path).is_file()
    assert result.generated_files == [result.output_path]
    assert old_audit.read_text(encoding="utf-8") == "existing audit"
    assert not (tmp_path / "primary_assessment_skipped_audit.txt").exists()


def test_no_assessment_data_does_not_create_or_claim_an_audit_file(tmp_path, monkeypatch):
    _owners(monkeypatch, tmp_path)
    monkeypatch.setattr("app.data.assessment_generator.load_automation_defaults", lambda **kwargs: {})
    source = tmp_path / "main.xlsx"
    wb = openpyxl.Workbook()
    wb.save(source)
    wb.close()
    old = tmp_path / "primary_assessment_skipped_audit.txt"
    old.write_text("existing audit", encoding="utf-8")
    result = generate_primary_assessment_result(str(source), str(tmp_path))
    assert result.output_path is None
    assert result.generated_files == []
    assert old.read_text(encoding="utf-8") == "existing audit"
