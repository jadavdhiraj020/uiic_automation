"""Keep New India's working files out of the claim folder."""

from pathlib import Path

import openpyxl

from app.data.assessment_generator import (
    generate_primary_assessment_from_pdf_result,
    generate_primary_assessment_result,
)
from app.portals.newindia.scan_outputs import refresh_printable_output
from app.portals.oic import generated_files


def _owners(monkeypatch, tmp_path):
    monkeypatch.setattr(generated_files, "user_data_dir", lambda *parts: str(tmp_path.joinpath("app", *parts)))


def test_printable_pdf_is_published_without_a_workbook_copy(tmp_path, monkeypatch):
    _owners(monkeypatch, tmp_path)
    folder = tmp_path / "claim"
    folder.mkdir()
    source = folder / "main.xlsx"
    source.write_bytes(b"original")
    existing_copy = folder / "Printable_Assessment.xlsx"
    existing_copy.write_bytes(b"existing user file")

    def render(source_excel_path, output_folder, settings, logs, stop_cb=None):
        excel = Path(output_folder) / "Printable_Assessment.xlsx"
        pdf = Path(output_folder) / "Printable_Assessment.pdf"
        excel.write_bytes(b"temporary workbook")
        pdf.write_bytes(b"%PDF-1.4\nnew")
        return str(excel), str(pdf)

    monkeypatch.setattr("app.data.printable_excel_service.process_printable_output", render)
    refresh_printable_output(str(source), str(folder), {}, [])
    assert (folder / "Printable_Assessment.pdf").read_bytes().endswith(b"new")
    assert existing_copy.read_bytes() == b"existing user file"
    assert source.read_bytes() == b"original"
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
    assert not (tmp_path / "Printable_Assessment.pdf").exists()
    assert any("Warning: Printable survey PDF" in line for line in logs)


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
