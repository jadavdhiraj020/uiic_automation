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
    rows = tuple(
        (*row, "Charges Filed: Case 12") if row[0].startswith("Driver Address:") else row
        for row in SUMMARY
    )
    _write_pdf(path, (rows, ITEMS))
    claim = extract_claim_data_from_report(str(path), portal_id="oic")

    assert claim.policy_number == "POL555555"
    assert claim.claim_no == "DEMO1234"
    assert claim.driver_name == "Sample Driver"
    assert claim.driver_address == "Sample Road, Vadodara 390001"
    assert not claim.charges_filed
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


def test_oic_finds_scan_with_a_cover_before_the_survey_report(tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    path = tmp_path / "Document 08.pdf"
    _write_pdf(path, ((("Cover Page",),), SUMMARY), scan=True)

    assert find_oic_report(tmp_path) == str(path)


def test_sparse_native_letterhead_does_not_hide_a_full_page_scan():
    from app.portals.oic.pdf_layout import Line, _scan_regions

    page = SimpleNamespace(width=600, height=800, images=[{"x0": 0, "top": 0, "x1": 600, "bottom": 800}])
    native = [Line(1, top, ((10, 90, "Letterhead"),)) for top in (25, 100, 480, 750)]

    assert _scan_regions(page, native) == [(0, 0, 600, 800)]


def test_oic_rejects_fee_bill_with_conflicting_claim_numbers(tmp_path):
    from app.portals.oic.pdf_report import supplement_oic_pdf_fees

    report = tmp_path / "Final Survey Report.pdf"
    _write_pdf(report, (SUMMARY, ITEMS))
    claim = extract_claim_data_from_report(str(report), portal_id="oic")
    rows = (
        ("Claim No: WRONG1234",),
        ("Registration No: GJ06AB1234",),
        ("Claim No: DEMO1234",),
        ("Professional Fee: 4321",),
    )
    _write_pdf(tmp_path / "Survey Fee Bill.pdf", (rows,))

    supplement_oic_pdf_fees(claim, tmp_path)

    assert claim.professional_fee == ""
    assert not claim._excel_coords.get("professional_fee")
    assert any("Conflicting claim" in warning for warning in claim._oic_pdf_review_warnings)


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


def test_oic_prefers_survey_pdf_over_generated_printable_copy(tmp_path):
    report = tmp_path / "Excel Export.pdf"
    printable = tmp_path / "survey_report_printable_copy.pdf"
    stale = tuple(tuple(value.replace("DEMO1234", "OLD1234") for value in row) for row in SUMMARY)
    _write_pdf(report, (SUMMARY, ITEMS))
    _write_pdf(printable, (stale, ITEMS))

    assert find_oic_report(tmp_path, preferred=printable) == str(report)

    other = printable.rename(tmp_path / "Other Final Report.pdf")
    with pytest.raises(ValueError, match="More than one claim report"):
        find_oic_report(tmp_path)
    report.unlink()
    other.rename(printable)
    assert find_oic_report(tmp_path) == str(printable)


@pytest.mark.parametrize("separate_bill", [False, True])
@pytest.mark.parametrize("photo_line, expected_charge", [
    ("Photographs 20 Rs 200", "200"),
    ("Photographs 20", ""),
])
def test_oic_reads_fee_amount_beside_photo_count(tmp_path, separate_bill, photo_line, expected_charge):
    from app.portals.oic.pdf_report import supplement_oic_pdf_fees

    report = tmp_path / "Final Survey Report.pdf"
    fee_rows = (
        ("Survey Fee Bill",),
        ("Insured Details",),
        ("Vehicle/Item: GJ06AB1234",),
        ("C Note/Policy No.: POL555555",),
        ("Professional Fee Rs 4260.97",),
        ("Conveyance Charges Rs 1000",),
        (photo_line,),
    )
    if separate_bill:
        _write_pdf(report, (SUMMARY, ITEMS))
        _write_pdf(tmp_path / "Survey Fee Bill.pdf", (fee_rows,))
    else:
        _write_pdf(report, (SUMMARY, ITEMS, fee_rows))
    claim = extract_claim_data_from_report(str(report), portal_id="oic")
    supplement_oic_pdf_fees(claim, tmp_path)

    assert claim.professional_fee == "4260.97"
    assert claim.traveling_expenses == "1000"
    assert claim.photo_charges == expected_charge
    assert any("Fee amounts missing" in warning for warning in claim._oic_pdf_review_warnings) == (not expected_charge)


def test_oic_does_not_use_embedded_fee_bill_for_a_different_vehicle(tmp_path):
    report = tmp_path / "Final Survey Report.pdf"
    fee_rows = (
        ("Survey Fee Bill",),
        ("Vehicle/Item: GJ13AB1234",),
        ("C Note/Policy No.: POL555555",),
        ("Professional Fee Rs 4260.97",),
    )
    _write_pdf(report, (SUMMARY, ITEMS, fee_rows))
    claim = extract_claim_data_from_report(str(report), portal_id="oic")

    assert not claim.professional_fee
    assert any("different claim or vehicle details" in warning for warning in claim._oic_pdf_review_warnings)


def _ruled_table(page, rows, edges):
    from app.portals.oic.pdf_layout import Table

    tops = tuple(10 + 20 * index for index in range(len(rows)))
    boxes = tuple(tuple((left, top, right, top + 20) for left, right in zip(edges, edges[1:]))
                  for top in tops)
    return Table(page, tops, rows, row_boxes=boxes)


@pytest.mark.parametrize("printed_serial", ["2", "3", ""])
def test_oic_preserves_continuation_rows_only_with_printed_serial(printed_serial):
    from dataclasses import replace
    from app.portals.oic.pdf_assessment import read_assessment
    from app.portals.oic.pdf_layout import Line, Page

    edges = (10, 25, 100, 160, 210, 260, 310, 365, 400)
    start = _ruled_table(1, (
        ("S.N.", "DESCRIPTION", "Estimate", "R/R", "DENTING", "C/W", "PAINT", "GST"),
        ("1", "Door", "", "100", "0", "0", "500", "18"),
    ), edges)
    continuation = _ruled_table(2, (
        ("", "Bonnet", "", "500", "100", "0", "900", "18"),
        ("SUB TOTAL", "", "", "600", "100", "0", "1400", ""),
    ), edges)
    first, second = continuation.row_boxes
    continuation = replace(continuation, row_boxes=(
        (None, *first[1:]),
        ((edges[0], second[0][1], edges[2], second[0][3]), None, *second[2:]),
    ))
    line = Line(2, 20, ((15, 50, f"{printed_serial} Bonnet".strip()), (180, 200, "500")))
    _, labour, _, sources, errors = read_assessment((
        Page((), (start,), 400), Page((line,), (continuation,), 400),
    ))

    if printed_serial == "2":
        assert labour == {"rr": 600, "denting": 100, "cw": 0, "painting": 1400}
        assert sources["labour"] == "PDF p1 + p2"
    else:
        assert not any(labour.values())
        assert any("labour" in error for error in errors)


@pytest.mark.parametrize("total, next_left, accepted", [
    ("1000", 10, True),
    ("1100", 10, False),
    ("1000", 25, False),
])
def test_oic_gst_total_continuation_requires_matching_columns_and_amounts(total, next_left, accepted):
    from app.portals.oic.pdf_assessment import read_assessment
    from app.portals.oic.pdf_layout import Page

    edges = (10, 75, 170, 230, 290, 350, 410)
    summary = _ruled_table(1, (
        ("GST Summary Spares", "", "", "", "", ""),
        ("Tax %", "Taxable Amount", "CGST", "SGST", "IGST", "Total Amount"),
        ("18", "1000", "90", "90", "", "1180"),
    ), edges)
    # Both possible totals are internally valid at 18%. Only 1000 agrees with the breakdown.
    half_tax = "90" if total == "1000" else "99"
    continuation = _ruled_table(2, (
        ("Total", total, half_tax, half_tax, "0", ""),
    ), (next_left, *edges[1:]))
    _, _, gst, _, errors = read_assessment((
        Page((), (summary,), 420), Page((), (continuation,), 420),
    ))

    if accepted:
        assert gst["spares"][0]["taxable"] == 1000
        assert gst["spares"][1] == "PDF p1 + p2"
    else:
        assert "spares" not in gst
        assert any("Spares GST summary total" in error for error in errors)
