from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pypdfium2
import pytest

from app.data import folder_scanner
from app.data.assessment_generator import generate_primary_assessment
from app.data.report_reader import find_main_report_source
from app.portals.newindia import scan_outputs
from app.portals.oic import generated_files


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app_data"))


def _write_claim(path, item):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Claim No.", "DEMO1234"])
    sheet.append(["S.No", "Description", "Estimated", "Metal", "Plastic", "Glass"])
    sheet.append([1, item, 1000, 800])
    sheet.append(["Sub Total"])
    workbook.save(path)
    workbook.close()


def _write_pdf(path, width):
    with pypdfium2.PdfDocument.new() as pdf:
        pdf.new_page(width, 100).close()
        pdf.save(path)


def _reject_replacement(monkeypatch, locked):
    replace = generated_files.os.replace

    def guarded_replace(source, destination):
        if Path(destination) in locked:
            raise PermissionError(f"{Path(destination).name} is open")
        return replace(source, destination)

    monkeypatch.setattr(generated_files.os, "replace", guarded_replace)


def test_primary_assessment_uses_same_path_and_skips_locked_workbook(tmp_path, monkeypatch):
    source = tmp_path / "main.xlsx"
    _write_claim(source, "Bonnet")
    output = Path(generate_primary_assessment(str(source), str(tmp_path)))
    assert output.name == scan_outputs.ASSESSMENT_WORKBOOK

    _write_claim(source, "Bumper")
    assert generate_primary_assessment(str(source), str(tmp_path)) == str(output)
    with output.open("rb") as stream:
        workbook = openpyxl.load_workbook(stream, read_only=True)
        assert workbook.active["D2"].value == "Bumper"
        workbook.close()

    previous_output = output.read_bytes()
    _write_claim(source, "Door")
    _reject_replacement(monkeypatch, {output})
    with pytest.raises(PermissionError, match="is open"):
        generate_primary_assessment(str(source), str(tmp_path))
    assert output.read_bytes() == previous_output
    assert list(tmp_path.glob("auto_primary_assessment*.xlsx")) == [output]


def test_folder_service_does_not_attach_old_locked_assessment(tmp_path, monkeypatch):
    from app.ui.services.claim_folder_service import ClaimFolderService

    source = tmp_path / "main.xlsx"
    _write_claim(source, "Bonnet")
    output = Path(generate_primary_assessment(str(source), str(tmp_path)))
    _write_claim(source, "Bumper")
    _reject_replacement(monkeypatch, {output})
    monkeypatch.setattr(scan_outputs, "refresh_printable_output", lambda **kwargs: None)

    result = ClaimFolderService(portal_id="newindia").process_folder(str(tmp_path), sync_generation=True)

    assert result.success
    assert "assessment_excel" not in result.claim.assessment_files
    assert any("Primary assessment Excel skipped" in line for line in result.log_lines)
    assert list(tmp_path.glob("auto_primary_assessment*.xlsx")) == [output]


def test_newindia_rescans_exclude_old_outputs_and_skip_locked_pdf(tmp_path, monkeypatch):
    source = tmp_path / "main.xlsx"
    _write_claim(source, "Bonnet")
    legacy = tmp_path / "auto_primary_assessment_1.xlsx"
    legacy.write_bytes(b"older assessment")
    printable = tmp_path / "Printable_Assessment.pdf"
    _write_pdf(printable, 400)
    extra = tmp_path / "supporting_statement.pdf"
    invoice = tmp_path / "final_invoice.pdf"
    photo = tmp_path / "vehicle.pdf"
    _write_pdf(extra, 100)
    _write_pdf(invoice, 150)
    _write_pdf(photo, 200)
    reinspection = tmp_path / "reinspection_report.pdf"

    def export_reinspection(source_path, output_folder):
        target = Path(output_folder) / reinspection.name
        _write_pdf(target, 120)
        return str(target)

    monkeypatch.setattr(folder_scanner, "_extract_sheet_for_reinspection_pdf", export_reinspection)
    bundle = tmp_path / scan_outputs.CLAIM_RELATED_PDF
    for width in (100, 160, 220):
        _write_pdf(extra, width)
        result = folder_scanner.scan_folder(str(tmp_path), portal_id="newindia")
        assert Path(result.excel_path) == source
        assert Path(result.claim_related_merged_pdf) == bundle
        assert [Path(path) for path in result.claim_related_files] == [source, extra]
        assert result.assessment_files["reinspection_report"] == str(reinspection)
        assert Path(result.claim_doc_files["Work Approval Document"]).name == "work_approval_fallback.pdf"
        with pypdfium2.PdfDocument(bundle) as pdf:
            assert len(pdf) == 1
            assert pdf[0].get_width() == width

    old_bundle = bundle.read_bytes()
    old_reinspection = reinspection.read_bytes()
    _reject_replacement(monkeypatch, {bundle, reinspection})
    _write_pdf(extra, 250)
    result = folder_scanner.scan_folder(str(tmp_path), portal_id="newindia")
    assert result.claim_related_merged_pdf is None
    assert "reinspection_report" not in result.assessment_files
    assert any(bundle.name in warning and "skipped" in warning for warning in result.policy_warnings)
    assert any(reinspection.name in warning and "skipped" in warning for warning in result.policy_warnings)
    assert bundle.read_bytes() == old_bundle
    assert reinspection.read_bytes() == old_reinspection
    assert list(tmp_path.glob("claim_others_documents*.pdf")) == [bundle]
    assert len(list(tmp_path.glob("vehicle_photo_*.pdf"))) == 4
    assert legacy.read_bytes() == b"older assessment"


def test_newindia_pdf_fallback_excludes_generated_reports(tmp_path, monkeypatch):
    printable = tmp_path / "Printable_Assessment.pdf"
    _write_pdf(printable, 300)
    bundle = tmp_path / "claim_others_documents_20261121_150000.pdf"
    _write_pdf(bundle, 400)
    monkeypatch.setattr("app.data.pdf_report_reader.looks_like_survey_report", lambda path: 10)
    scan = SimpleNamespace(excel_path=None, assessment_files={"survey_report": str(printable)})

    assert find_main_report_source(str(tmp_path), scan, "newindia") is None
    original = tmp_path / "Final Survey Report.pdf"
    _write_pdf(original, 100)
    assert find_main_report_source(str(tmp_path), scan, "newindia") == str(original)


def test_printable_refresh_uses_fixed_names_and_continues_after_locked_excel(tmp_path, monkeypatch):
    def print_files(source, target, settings, logs, stop_cb):
        assert settings["printable_use_timestamp"] is False
        excel_path = Path(target) / settings["printable_output_excel_name"]
        pdf_path = Path(target) / settings["printable_output_pdf_name"]
        excel_path.write_bytes(b"new excel")
        pdf_path.write_bytes(b"%PDF-new")
        return str(excel_path), str(pdf_path)

    monkeypatch.setattr("app.data.printable_excel_service.process_printable_output", print_files)
    source = tmp_path / "main.xlsx"
    _write_claim(source, "Bonnet")
    excel = tmp_path / "Printable_Assessment.xlsx"
    excel.write_bytes(b"old excel")
    pdf = tmp_path / "Printable_Assessment.pdf"
    pdf.write_bytes(b"%PDF-old")
    _reject_replacement(monkeypatch, {excel})
    logs = []

    scan_outputs.refresh_printable_output(str(source), str(tmp_path), {"printable_use_timestamp": True}, logs)

    assert excel.read_bytes() == b"old excel"
    assert pdf.read_bytes() == b"%PDF-new"
    assert any("Printable_Assessment.xlsx skipped" in line for line in logs)
    assert not list(tmp_path.glob("Printable_Assessment_*"))


def test_printable_refresh_leaves_incomplete_stage_unpublished(tmp_path, monkeypatch):
    def failed_print(source, target, settings, logs, stop_cb):
        (Path(target) / settings["printable_output_excel_name"]).write_bytes(b"unfinished")

    monkeypatch.setattr("app.data.printable_excel_service.process_printable_output", failed_print)
    source = tmp_path / "main.xlsx"
    _write_claim(source, "Bonnet")
    printable = tmp_path / "Printable_Assessment.xlsx"
    printable.write_bytes(b"last complete copy")

    scan_outputs.refresh_printable_output(str(source), str(tmp_path), {}, [])

    assert printable.read_bytes() == b"last complete copy"
