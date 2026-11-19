from ctypes import c_ushort
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.data.report_reader import extract_claim_data_from_report, find_main_report_source
from app.portals.oic.pdf_report import find_oic_report


SUMMARY = (
    ("Motor OD Final Survey Report",),
    ("Policy No: POL555555", "Claim No: DEMO1234"),
    ("Submission Date: 21/10/2026",),
    ("Surveyor Licence No: SLA-7777", "Expiry Date: 24/10/2027"),
    ("Vehicle Particulars",),
    ("Registration No: GJ06AB1234",),
    ("Make & Model: Sample Motors SUV",),
    ("Chassis No: AB1234567890", "Engine No: EN1234567"),
    ("Cubic Capacity: 1500", "Class of Vehicle: LMV"),
    ("Driver Details",),
    ("Name of Driver: Sample Driver", "DOB: 14/04/1990"),
    ("DL No: GJ062018001234",),
    ("Date of Issue: 16/04/2018", "Valid Till: 16/04/2038"),
    ("Driver Address: Sample Road, Vadodara 390001",),
    ("Accident Details",),
    ("Date of Accident: 17/10/2026",),
    ("Survey Details",),
    ("Date of Survey: 18/10/2026", "Place of Survey: Sample Garage"),
    ("Initial Loss Assessment Amount: 1500",),
    ("Workshop Details",),
    ("Workshop Name: Sample Garage", "Workshop Estimate Amount: 2000"),
    ("Claim Type: Cashless",),
)
ITEMS = (
    ("Assessment of Loss",),
    ("Nil Depreciation: Yes",),
    ("Workshop Invoice No: INV12345 Dated 19/10/2026",),
    ("SN", "Parts Name", "Estimated", "Metal", "Plastic", "Glass"),
    ("1", "Bonnet", "1450", "1300", "0", "0"),
    ("Total", "", "1450", "1300", "0", "0"),
    ("GST Summary Spares",),
    ("Tax %", "Taxable Amount", "CGST", "SGST", "IGST", "Total Amount"),
    ("Total", "1300", "117", "117", "0", "1534"),
    ("GST Summary Labour",),
    ("Tax %", "Taxable Amount", "CGST", "SGST", "IGST", "Total Amount"),
    ("Total", "0", "0", "0", "0", "0"),
)


@pytest.fixture(autouse=True)
def isolate_app_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


def _write_pdf(path, pages, *, scan=False, hybrid=False):
    import pypdfium2 as pdfium
    from pypdfium2 import raw

    with pdfium.PdfDocument.new() as document:
        for index, rows in enumerate(pages):
            page = document.new_page(595, 842)
            coordinates = [
                (x, 35 + i * 21, text)
                for i, row in enumerate(rows)
                for x, text in zip((22, 105, 225, 305, 382, 459) if len(row) > 2 else (22, 285), row)
                if text
            ]
            if scan or hybrid:
                from PIL import Image, ImageDraw, ImageFont

                scale = 3
                # Leave the cover heading and claim row as native text in the mixed case.
                top = 70 if hybrid and not index else 0
                raster = Image.new("RGB", (550 * scale, (660 - top) * scale), "white")
                draw = ImageDraw.Draw(raster)
                try:
                    font = ImageFont.truetype("arial.ttf", 30)
                except OSError:
                    font = ImageFont.truetype("DejaVuSans.ttf", 30)
                for x, y, text in coordinates:
                    if y >= top:
                        draw.text((x * scale, (y - top) * scale), text, font=font, fill="black", anchor="ls")
                image = pdfium.PdfImage.new(document)
                bitmap = pdfium.PdfBitmap.from_pil(raster)
                image.set_bitmap(bitmap)
                image.set_matrix(pdfium.PdfMatrix(550, 0, 0, 660 - top, 0, 182))
                page.insert_obj(image)
                bitmap.close()
                coordinates = [cell for cell in coordinates if cell[1] < top]
            for x, y, text in coordinates:
                obj = raw.FPDFPageObj_NewTextObj(document, b"Helvetica", 10)
                utf16 = (c_ushort * (len(text) + 1)).from_buffer_copy((text + "\0").encode("utf-16le"))
                assert raw.FPDFText_SetText(obj, utf16)
                text_object = pdfium.PdfTextObj(obj, pdf=document)
                text_object.set_matrix(pdfium.PdfMatrix(e=x, f=842 - y))
                page.insert_obj(text_object)
            page.gen_content()
            page.close()
        document.save(path)


def test_native_oic_pdf_keeps_label_and_amount_columns(tmp_path, monkeypatch):
    from app.portals.oic.automation.assessment_upload_excel import build_upload_workbook
    from app.utils import load_automation_defaults
    from app.portals.oic import pdf_layout

    def unexpected_ocr(*args, **kwargs):
        pytest.fail("A native text PDF should not use OCR")

    monkeypatch.setattr(pdf_layout, "_ocr_page", unexpected_ocr)
    path = tmp_path / "Final Survey Report.pdf"
    _write_pdf(path, (SUMMARY, ITEMS))
    claim = extract_claim_data_from_report(str(path), portal_id="oic")

    assert claim.policy_number == "POL555555"
    assert claim.claim_no == "DEMO1234"
    assert claim.driver_name == "Sample Driver"
    assert claim.engine_no == "EN1234567"
    assert claim.place_of_survey == "Sample Garage"
    assert claim.workshop_estimate_amount == "2000"
    assert claim._oic_pdf_assessment[0][0]["part_name"] == "Bonnet"
    assert claim._oic_pdf_assessment[0][0]["estimated_amount"] == 1450
    assert claim.invoice_gst_amount == "234.00"
    assert not claim._oic_pdf_review_errors
    upload, _, items = build_upload_workbook(claim, load_automation_defaults("oic"), output_folder=tmp_path)
    assert Path(upload).is_file()
    assert len(items) == 1


@pytest.mark.parametrize("hybrid", [False, True])
def test_oic_reads_raster_only_and_hybrid_pdf_with_real_ocr(tmp_path, hybrid):
    pytest.importorskip("rapidocr_onnxruntime")
    path = tmp_path / "Document 01.pdf"
    _write_pdf(path, (SUMMARY, ITEMS), scan=not hybrid, hybrid=hybrid)
    if not hybrid:
        assert find_oic_report(tmp_path) == str(path)
    claim = extract_claim_data_from_report(str(path), portal_id="oic")

    assert claim.claim_no == "DEMO1234"
    assert ("(OCR)" in claim._excel_coords["claim_no"]) is not hybrid
    assert claim.driver_name.replace(" ", "").casefold() == "sampledriver"
    assert claim.dob_of_driver == "14/04/1990"
    assert claim.driver_license_issue_date == "16/04/2018"
    assert claim.driver_license_expiry_date == "16/04/2038"
    assert "(OCR)" in claim._excel_coords["driver_name"]
    assert claim.invoice_gst_amount == "234.00"
    assert claim._oic_pdf_assessment[0][0]["billed_amount"] == 1300
    assert not claim._oic_pdf_review_errors


def test_oic_blocks_conflicting_required_fields_and_unaligned_totals(tmp_path):
    from app.portals.oic.automation.assessment_upload_excel import build_upload_workbook

    path = tmp_path / "Final Survey Report.pdf"
    rows = (*SUMMARY[:14], ("Valid Till: 16/04/2037",), *SUMMARY[14:])
    rows = tuple(tuple(text for text in row if not text.startswith("Workshop Estimate Amount"))
                 for row in rows)
    _write_pdf(path, (rows, (*ITEMS, ("Net Payable", "5000", "3000"))))
    claim = extract_claim_data_from_report(str(path), portal_id="oic")

    assert not claim.driver_license_expiry_date
    assert not claim.workshop_estimate_amount
    assert any("Conflicting values for Driving Licence Expiry Date" in issue
               for issue in claim._oic_pdf_review_errors)
    assert any("Workshop Estimate Amount is missing" in issue
               for issue in claim._oic_pdf_review_errors)
    with pytest.raises(ValueError, match="Review the PDF fields"):
        build_upload_workbook(claim, {}, output_folder=tmp_path)


def test_oic_intake_keeps_excel_priority_and_existing_field_mapping(tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Survey report"
    sheet.append(["Policy Number", "POL123456"])
    sheet.append(["Fitness Valid Upto", "17/09/2033"])
    excel_path = tmp_path / "Main.xlsx"
    book.save(excel_path)
    (tmp_path / "Final Survey Report.pdf").write_bytes(b"Conflicting report")

    chosen = find_main_report_source(tmp_path, SimpleNamespace(excel_path=str(excel_path)), portal_id="oic")
    claim = extract_claim_data_from_report(chosen, portal_id="oic")

    assert chosen == str(excel_path)
    assert claim.policy_number == "POL123456"
    assert claim.fitness_valid_upto == "17/09/2033"
    assert not getattr(claim, "_oic_pdf_review_errors", ())
