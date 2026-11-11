from app.data.pdf_report_reader import (
    after_label,
    cut_next_label,
    extract_time,
    parse_value,
)


def test_combined_date_and_time_without_space():
    hh, mm = extract_time("Date & Time of Accident : 11/04/202610:30 AM")
    assert (hh, mm) == ("10", "30")


def test_separate_time_on_same_line():
    hh, mm = extract_time("Date and Time of Survey : 15/10/2026 Time 03:10")
    assert (hh, mm) == ("03", "10")


def test_multiple_label_value_pairs_on_one_line():
    line = "Policy / Cover Note No. : 6021003125001    IDV : 864000    Claim No. : 6021009999"
    remainder = after_label(line, "Claim No.")
    assert parse_value(remainder, "id") == "6021009999"


def test_cut_before_second_label():
    remainder = "6021003125001 IDV : 864000"
    value = cut_next_label(remainder, "Policy / Cover Note No.", ["IDV"])
    assert value == "6021003125001"


def test_amount_prefers_rightmost_number():
    assert parse_value("S-1 35.00", "amount") == "35"

def test_uiic_pdf_missing_time_stays_blank_for_manual_review():
    from app.data.data_model import ClaimData

    claim = ClaimData(
        portal_id="uiic",
        date_of_survey="15/10/2026",
        source_report_path=r"C:\\test\\survey_report.pdf",
    )
    claim.calculate_derived_fields()

    assert claim.time_hh == ""
    assert claim.time_mm == ""
    assert claim.time_of_survey == ""


def test_uiic_excel_keeps_legacy_missing_time_fallback():
    from app.data.data_model import ClaimData

    claim = ClaimData(
        portal_id="uiic",
        date_of_survey="15/10/2026",
        source_excel_path=r"C:\\test\\survey_report.xlsx",
    )
    claim.calculate_derived_fields()

    assert claim.time_hh == "11"
    assert claim.time_mm == "00"
    assert claim.time_of_survey == "11:00"

def test_uiic_pdf_missing_manual_fields_are_warnings_not_errors():
    from app.data.data_model import ClaimData

    claim = ClaimData(
        portal_id="uiic",
        source_report_path=r"C:\\test\\survey_report.pdf",
    )
    errors, warnings = claim.validate()

    assert errors == []
    assert any("Date of Survey" in w for w in warnings)
    assert any("Place of Survey" in w for w in warnings)
    assert any("Initial Loss Amount" in w for w in warnings)
    assert any("Final Report No" in w for w in warnings)


def test_uiic_excel_missing_required_fields_remain_blocking():
    from app.data.data_model import ClaimData

    claim = ClaimData(
        portal_id="uiic",
        source_excel_path=r"C:\\test\\survey_report.xlsx",
    )
    errors, warnings = claim.validate()

    assert "Date of Survey is missing" in errors
    assert "Place of Survey is missing" in errors
    assert "Initial Loss Amount is missing" in errors
    assert "Final Report No is missing" in errors

def test_blank_claim_label_does_not_steal_next_line_value():
    from app.data.pdf_report_reader import PdfLine, find_value

    lines = [
        PdfLine(1, 1, "Claim No. :"),
        PdfLine(1, 2, "Vehicle No. : CH01CN0405"),
    ]
    value, source, label = find_value(
        lines,
        "claim_no",
        {"search_labels": ["Claim No."]},
        ["Claim No.", "Vehicle No."],
    )

    assert value is None
    assert source is None
    assert label is None


def test_blank_amount_label_does_not_steal_page_footer_number():
    from app.data.pdf_report_reader import PdfLine, find_value

    lines = [
        PdfLine(4, 1, "PHOTOGRAPHS :"),
        PdfLine(4, 2, "Page 4 of 4"),
    ]
    value, source, label = find_value(
        lines,
        "photo_charges",
        {"search_labels": ["PHOTOGRAPHS"]},
        ["PHOTOGRAPHS"],
    )

    assert value is None
    assert source is None
    assert label is None

def test_uiic_structured_docwriter_parts_and_gst_summary():
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine, _apply_uiic_structured_fields

    lines = [
        PdfLine(5, 1, "PARTS DETAILS:"),
        PdfLine(5, 2, "S.N. Parts Name Estimated M-Age P-50% G-0% Extra Bill Sr. No. GST"),
        PdfLine(5, 3, "SUB TOTAL 100000.00 6779.00 17008.75 0.00 0.00 0.00 18"),
        PdfLine(7, 1, "GST SUMMARY – SPARES"),
        PdfLine(7, 2, "Tax Percentage Taxable Amount CGST SGST IGST Total Amount"),
        PdfLine(7, 3, "18 12571.77 1131.46 1131.46 0 14834.69"),
        PdfLine(7, 5, "GST SUMMARY – LABOUR"),
        PdfLine(7, 6, "Tax Percentage Taxable Amount CGST SGST IGST Total Amount"),
        PdfLine(7, 7, "18 24887.50 2239.88 2239.87 0 29367.25"),
        PdfLine(6, 2, "TOTAL AMOUNT OF LABOUR ASSESSED 29367.25"),
    ]
    claim = ClaimData(portal_id="uiic", source_report_path=r"C:\\test\\survey_report.pdf")
    _apply_uiic_structured_fields(lines, claim)

    assert claim.parts_age_dep_excl_gst == "6779"
    assert claim.parts_50_dep_excl_gst == "17008.75"
    assert claim.parts_nil_dep_excl_gst == "0"
    assert claim.parts_gst18_amount == "12571.77"
    assert claim.labour_gst18_amount == "24887.5"


def test_uiic_structured_classic_parts_summary_and_fee_bill():
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine, _apply_uiic_structured_fields

    lines = [
        PdfLine(3, 1, "SPARE PARTS"),
        PdfLine(3, 2, "Glass Parts Metal Parts Fibber 30% Rubber/Plastic 50% Dep. GST %"),
        PdfLine(4, 1, "Total Before GST 515,928.00 0.00 156,621.00 0.00 274,419.00"),
        PdfLine(4, 10, "SUMMARY OF ASSESSMENT"),
        PdfLine(4, 11, "Less Excess Rs. 2,000.00"),
        PdfLine(4, 12, "Less Salvage Value Rs. 10,000.00"),
        PdfLine(6, 1, "FINAL SURVEY BILL"),
        PdfLine(6, 2, "Professional Fees Rs. : 6,544.00"),
        PdfLine(6, 3, "Photograph (@ Rs. 10.00 x 20 Copy) Rs. : 200.00"),
        PdfLine(6, 4, "Conveyance () Rs. : 1,000.00"),
        PdfLine(6, 5, "re-inspection fee Rs. : 1,000.00"),
    ]
    claim = ClaimData(portal_id="uiic", source_report_path=r"C:\\test\\main.pdf")
    _apply_uiic_structured_fields(lines, claim)

    assert claim.parts_age_dep_excl_gst == "156621"
    assert claim.parts_50_dep_excl_gst == "274419"
    assert claim.parts_nil_dep_excl_gst == "0"
    assert claim.compulsory_excess == "2000"
    assert claim.salvage_value == "10000"
    assert claim.survey_fee == "6544"
    assert claim.photo_charges == "200"
    assert claim.traveling_expenses == "1000"
    assert claim.reinspection_fee == "1000"


def test_uiic_header_date_used_for_report_and_invoice_date():
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine, _apply_uiic_structured_fields

    lines = [
        PdfLine(1, 1, "MOTOR FINAL SURVEY REPORT"),
        PdfLine(1, 2, "Ref. No. : JDB/1165 Date : 18/07/2023"),
    ]
    claim = ClaimData(portal_id="uiic", source_report_path=r"C:\\test\\main.pdf")
    _apply_uiic_structured_fields(lines, claim)

    assert claim.final_report_date == "18/07/2023"
    assert claim.invoice_date == "18/07/2023"

def test_uiic_folder_supplement_rejects_different_claim(tmp_path, monkeypatch):
    import app.data.pdf_report_reader as reader
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine

    other = tmp_path / "other_survey.pdf"
    other.write_bytes(b"placeholder")
    fake_lines = [
        PdfLine(1, 1, "MOTOR FINAL SURVEY REPORT"),
        PdfLine(1, 2, "Claim No. : OTHER123"),
        PdfLine(2, 1, "FINAL SURVEY BILL"),
        PdfLine(2, 2, "Professional Fees Rs. : 6,544.00"),
    ]
    monkeypatch.setattr(reader, "read_lines", lambda _path, max_pages=None: fake_lines)

    claim = ClaimData(
        portal_id="uiic",
        claim_no="ACTIVE123",
        source_report_path=str(tmp_path / "survey_report.pdf"),
    )
    reader.supplement_uiic_claim_from_folder(str(tmp_path), claim, claim.source_report_path)

    assert claim.survey_fee == "0"
    assert claim.professional_fee == "0"


def test_uiic_folder_supplement_same_claim_recalculates_professional_fee(tmp_path, monkeypatch):
    import app.data.pdf_report_reader as reader
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine

    fee_pdf = tmp_path / "fee_bill.pdf"
    fee_pdf.write_bytes(b"placeholder")
    fake_lines = [
        PdfLine(1, 1, "MOTOR FINAL SURVEY REPORT"),
        PdfLine(1, 2, "Claim No. : ACTIVE123"),
        PdfLine(2, 1, "FINAL SURVEY BILL"),
        PdfLine(2, 2, "Professional Fees Rs. : 6,544.00"),
        PdfLine(2, 3, "re-inspection fee Rs. : 1,000.00"),
        PdfLine(2, 4, "Conveyance Rs. : 1,000.00"),
        PdfLine(2, 5, "Photograph Rs. : 200.00"),
    ]
    monkeypatch.setattr(reader, "read_lines", lambda _path, max_pages=None: fake_lines)

    claim = ClaimData(
        portal_id="uiic",
        claim_no="ACTIVE123",
        source_report_path=str(tmp_path / "survey_report.pdf"),
    )
    reader.supplement_uiic_claim_from_folder(str(tmp_path), claim, claim.source_report_path)

    assert claim.survey_fee == "6544"
    assert claim.reinspection_fee == "1000"
    assert claim.professional_fee == "7544"
    assert claim.traveling_expenses == "1000"
    assert claim.photo_charges == "200"

    claim.calculate_derived_fields()
    assert claim.total_claimed_amount == "8744"

def test_uiic_classic_pdf_fallbacks_for_labour_and_18pct_parts():
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine, _apply_uiic_structured_fields

    lines = [
        PdfLine(2, 1, "LABOUR CHARGES"),
        PdfLine(3, 1, "Total After Discount 20,000.00 0.00 0.00 10,500.00"),
        PdfLine(3, 2, "GST 3,600.00 0.00 0.00 1,890.00"),
        PdfLine(3, 3, "SPARE PARTS"),
        PdfLine(3, 4, "Glass Parts Metal Parts Fibber 30% Rubber/Plastic 50% Dep. GST %"),
        PdfLine(3, 5, "1 COOLANT RADIATOR 52,368.00 52,368.00 28.00"),
        PdfLine(3, 6, "10 DISTANCE SENSOR 18,524.00 18,524.00 18.00"),
        PdfLine(3, 7, "11 DECOUPLING RING 712.00 18.00"),
        PdfLine(4, 1, "Total Before GST 515,928.00 0.00 156,621.00 0.00 274,419.00"),
        PdfLine(4, 2, "SUMMARY OF ASSESSMENT"),
    ]
    claim = ClaimData(portal_id="uiic", source_report_path=r"C:\\test\\classic.pdf")
    _apply_uiic_structured_fields(lines, claim)

    assert claim.labour_gst18_amount == "30500"
    assert claim.parts_gst18_amount == "18524"

def test_uiic_explicit_nil_depreciation_policy_sets_yes_without_guessing_time():
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine, _apply_uiic_structured_fields

    lines = [
        PdfLine(2, 1, "Date & Time of Survey :"),
        PdfLine(2, 2, "Depreciation is not deducted being NIL DEPRECIATION policy."),
    ]
    claim = ClaimData(portal_id="uiic", source_report_path=r"C:\\test\\alternate.pdf")
    _apply_uiic_structured_fields(lines, claim)

    assert claim.nil_depreciation == "Yes"
    assert claim.date_of_survey == ""
    assert claim.time_hh == ""
    assert claim.time_mm == ""

def test_uiic_pdf_supplement_preserves_sourced_zero_value():
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine, _apply_uiic_structured_fields

    claim = ClaimData(
        portal_id="uiic",
        source_report_path=r"C:\\test\\survey_report.pdf",
        parts_nil_dep_excl_gst="0",
    )
    claim._excel_coords["parts_nil_dep_excl_gst"] = "PDF p5 line 3"

    supplemental_lines = [
        PdfLine(1, 1, "SPARE PARTS"),
        PdfLine(1, 2, "Glass Parts Metal Parts Fibber 30% Rubber/Plastic 50% Dep. GST %"),
        PdfLine(1, 3, "Total Before GST 1000.00 500.00 200.00 0.00 300.00"),
    ]
    _apply_uiic_structured_fields(supplemental_lines, claim, fill_only_missing=True)

    assert claim.parts_nil_dep_excl_gst == "0"
    assert claim._excel_coords["parts_nil_dep_excl_gst"] == "PDF p5 line 3"

def test_uiic_folder_supplement_rejects_same_claim_but_different_vehicle(tmp_path, monkeypatch):
    import app.data.pdf_report_reader as reader
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine

    other = tmp_path / "old_or_sample_report.pdf"
    other.write_bytes(b"placeholder")
    fake_lines = [
        PdfLine(1, 1, "MOTOR FINAL SURVEY REPORT"),
        PdfLine(1, 2, "Claim No. : ACTIVE123"),
        PdfLine(1, 3, "Registration No. : CH01CN0405"),
        PdfLine(2, 1, "FINAL SURVEY BILL"),
        PdfLine(2, 2, "Professional Fees Rs. : 6,544.00"),
    ]
    monkeypatch.setattr(reader, "read_lines", lambda _path, max_pages=None: fake_lines)

    claim = ClaimData(
        portal_id="uiic",
        claim_no="ACTIVE123",
        vehicle_registration_number="CH01BT4945",
        source_report_path=str(tmp_path / "survey_report.pdf"),
    )
    reader.supplement_uiic_claim_from_folder(str(tmp_path), claim, claim.source_report_path)

    assert claim.survey_fee == "0"
    assert claim.professional_fee == "0"


def test_uiic_folder_supplement_allows_same_claim_and_vehicle(tmp_path, monkeypatch):
    import app.data.pdf_report_reader as reader
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import PdfLine

    fee_pdf = tmp_path / "same_case_fee.pdf"
    fee_pdf.write_bytes(b"placeholder")
    fake_lines = [
        PdfLine(1, 1, "MOTOR FINAL SURVEY REPORT"),
        PdfLine(1, 2, "Claim No. : ACTIVE123"),
        PdfLine(1, 3, "Registration No. : CH01 BT 4945"),
        PdfLine(2, 1, "FINAL SURVEY BILL"),
        PdfLine(2, 2, "Professional Fees Rs. : 6,544.00"),
    ]
    monkeypatch.setattr(reader, "read_lines", lambda _path, max_pages=None: fake_lines)

    claim = ClaimData(
        portal_id="uiic",
        claim_no="ACTIVE123",
        vehicle_registration_number="CH01BT4945",
        source_report_path=str(tmp_path / "survey_report.pdf"),
    )
    reader.supplement_uiic_claim_from_folder(str(tmp_path), claim, claim.source_report_path)

    assert claim.survey_fee == "6544"
    assert claim.professional_fee == "6544"

def test_uiic_horizontal_overflow_pairs_rows_by_position(monkeypatch):
    import pdfplumber
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import _apply_uiic_overflow_fields

    def words_for_rows(rows):
        out = []
        for top, text in rows:
            x = 10.0
            for token in text.split():
                out.append({"text": token, "top": top, "x0": x})
                x += max(20.0, len(token) * 6.0)
        return out

    class FakePage:
        def __init__(self, rows):
            self._words = words_for_rows(rows)
        def extract_words(self):
            return list(self._words)

    class FakePdf:
        def __init__(self):
            self.pages = [
                FakePage([(100.0, "Ref: A/2026/002 MOTOR OD FINAL SURVEY REPORT Date:")]),
                FakePage([
                    (200.0, "LESS EXCESS CLAUSE"),
                    (300.0, "Workshop Invoice No. PAC26-27-100745 Dated"),
                ]),
                FakePage([(101.0, "05/11/2026")]),
                FakePage([
                    (201.0, "2,000.00"),
                    (301.0, "27/10/2026"),
                ]),
            ]
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pdfplumber, "open", lambda _path: FakePdf())

    claim = ClaimData(portal_id="uiic", source_report_path=r"C:\\test\\split.pdf")
    _apply_uiic_overflow_fields(claim.source_report_path, claim)

    assert claim.compulsory_excess == "2000"
    assert claim.workshop_invoice_date == "27/10/2026"
    assert claim.final_report_date == "05/11/2026"
    assert claim.invoice_date == "05/11/2026"

def test_uiic_pdf_unsourced_zero_is_skipped_but_sourced_zero_is_real():
    from app.automation.claim_assessment import _is_unsourced_pdf_zero
    from app.data.data_model import ClaimData

    pdf_claim = ClaimData(
        portal_id="uiic",
        source_report_path=r"C:\\test\\survey_report.pdf",
        towing_charges="0",
    )
    assert _is_unsourced_pdf_zero(pdf_claim, "towing_charges", pdf_claim.towing_charges) is True

    pdf_claim._excel_coords["towing_charges"] = "PDF p6 line 10"
    assert _is_unsourced_pdf_zero(pdf_claim, "towing_charges", pdf_claim.towing_charges) is False

    excel_claim = ClaimData(
        portal_id="uiic",
        source_excel_path=r"C:\\test\\Main.xlsx",
        towing_charges="0",
    )
    assert _is_unsourced_pdf_zero(excel_claim, "towing_charges", excel_claim.towing_charges) is False


def test_uiic_pdf_missing_fee_does_not_create_fake_professional_fee_source():
    from app.data.data_model import ClaimData
    from app.data.pdf_report_reader import supplement_uiic_claim_from_folder

    claim = ClaimData(
        portal_id="uiic",
        claim_no="ACTIVE123",
        vehicle_registration_number="CH01BT4945",
        source_report_path=r"C:\\test\\survey_report.pdf",
    )

    # Nonexistent folder exits without inventing a fee source.
    supplement_uiic_claim_from_folder(r"C:\\definitely_missing_folder", claim, claim.source_report_path)

    assert claim.professional_fee == "0"
    assert "professional_fee" not in claim._excel_coords

