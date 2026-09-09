import os
import openpyxl
from decimal import Decimal
from pathlib import Path
from app.data.data_model import ClaimData
from app.data.excel_reader import _calculate_professional_fee
from app.data.folder_scanner import scan_folder, _extract_sheet_for_reinspection
from app.utils import load_doc_mapping, load_field_mapping, load_automation_defaults


def test_survey_report_auto_copies_to_assessment_report(tmp_path):
    """
    Requirement 1:
    - User only configures/uploads Survey Report.
    - Assessment report setting is removed from doc_mapping claim_assessment_tab.
    - When Survey Report is detected, create a physical copy assessment_report.pdf,
      keep original as survey_report, and map both to assessment_files.
    """
    doc_map = load_doc_mapping(portal_id="uiic")
    assert "assessment_report" not in doc_map.get("claim_assessment_tab", {})
    assert "survey_report" in doc_map.get("claim_assessment_tab", {})

    # Create dummy survey report
    survey_file = tmp_path / "survey_report_final.pdf"
    survey_file.write_bytes(b"%PDF-1.4 dummy survey content")

    result = scan_folder(str(tmp_path), portal_id="uiic")

    # Verify both are mapped in assessment_files
    assert "survey_report" in result.assessment_files
    assert "assessment_report" in result.assessment_files
    assert os.path.basename(result.assessment_files["survey_report"]) == "survey_report_final.pdf"
    assert os.path.basename(result.assessment_files["assessment_report"]) == "assessment_report.pdf"

    # Verify physical file was created and contains identical bytes
    copied_path = Path(result.assessment_files["assessment_report"])
    assert copied_path.exists()
    assert copied_path.read_bytes() == b"%PDF-1.4 dummy survey content"
    assert str(copied_path) in result.generated_files


def test_vehicle_photographs_single_prefix_maps_to_4_slots(tmp_path):
    """
    Requirement 2:
    - doc_mapping has single 'Vehicle Photographs' key under claim_documents_tab.
    - Single photo_sheet.jpg is detected and duplicated into 4 files.
    - Mapped to the 4 angle slots required by portal automation.
    """
    doc_map = load_doc_mapping(portal_id="uiic")
    claim_tab = doc_map.get("claim_documents_tab", {})
    assert "Vehicle Photographs" in claim_tab
    assert "Vehicle Photograph (Front)" not in claim_tab
    assert "Vehicle Photograph(Rear)" not in claim_tab

    # Create single photo
    photo_file = tmp_path / "photo_sheet_damaged_car.jpg"
    photo_file.write_bytes(b"JPEG dummy image data")

    result = scan_folder(str(tmp_path), portal_id="uiic")

    expected_slots = [
        "Vehicle Photograph (Front)",
        "Vehicle Photograph(Rear)",
        "Vehicle Photograph (Left)",
        "Vehicle Photograph (Right)",
    ]

    for slot in expected_slots:
        assert slot in result.claim_doc_files
        slot_file = Path(result.claim_doc_files[slot])
        assert slot_file.exists()
        assert slot_file.read_bytes() == b"JPEG dummy image data"

    # Verify 4 physical copy files exist
    for i in range(1, 5):
        assert (tmp_path / f"vehicle_photo_{i}.jpg").exists()


def test_reinspection_3rd_sheet_extraction_and_manual_priority(tmp_path):
    """
    Requirement 3:
    - Extracts 3rd sheet (index 2) from main Excel into reinspection.xlsx.
    - Prioritizes user-provided manual reinspection file if present.
    - Ensures reinspection.xlsx is excluded from main Excel candidates.
    """
    # 1. Create a 3-sheet workbook
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Summary"
    ws1["A1"] = "Main Data"

    ws2 = wb.create_sheet(title="Estimate")
    ws2["A1"] = "Estimate Details"

    ws3 = wb.create_sheet(title="Re-inspection")
    ws3["A1"] = "Reinspection Data Content"
    ws3["B2"] = 12345

    excel_path = tmp_path / "claim_main_data.xlsx"
    wb.save(str(excel_path))

    # Scan folder without user manual reinspection
    result = scan_folder(str(tmp_path), portal_id="uiic")

    assert result.excel_path == str(excel_path)
    assert "reinspection_report" in result.assessment_files
    reinspection_path = Path(result.assessment_files["reinspection_report"])
    assert reinspection_path.name == "reinspection.xlsx"
    assert reinspection_path.exists()

    # Verify extracted sheet content
    wb_extracted = openpyxl.load_workbook(str(reinspection_path))
    assert len(wb_extracted.sheetnames) == 1
    assert wb_extracted.active["A1"].value == "Reinspection Data Content"
    assert wb_extracted.active["B2"].value == 12345

    # 2. Test manual reinspection file priority
    manual_pdf = tmp_path / "manual_reinspection_report.pdf"
    manual_pdf.write_bytes(b"%PDF manual reinspection")

    result2 = scan_folder(str(tmp_path), portal_id="uiic")
    assert result2.excel_path == str(excel_path)
    assert "reinspection_report" in result2.assessment_files
    assert Path(result2.assessment_files["reinspection_report"]).name == "manual_reinspection_report.pdf"


def test_professional_fee_calculation_and_field_mapping():
    """
    Requirement 4:
    - field_mapping.json defines survey_fee and reinspection_fee.
    - ClaimData model has survey_fee, reinspection_fee, and professional_fee.
    - professional_fee = survey_fee + reinspection_fee via safe Decimal arithmetic.
    """
    fm = load_field_mapping(portal_id="uiic")
    assert "survey_fee" in fm
    assert "reinspection_fee" in fm
    assert "professional_fee" not in fm

    # Test fee addition
    claim = ClaimData()
    claim.survey_fee = "1500.50"
    claim.reinspection_fee = "500.25"
    claim.professional_fee = _calculate_professional_fee(claim.survey_fee, claim.reinspection_fee)
    assert claim.professional_fee == "2000.75"

    # Test edge cases (missing, comma formatting, invalid)
    assert _calculate_professional_fee("2,500.00", "500") == "3000"
    assert _calculate_professional_fee("1200", "") == "1200"
    assert _calculate_professional_fee(None, "450.50") == "450.50"
    assert _calculate_professional_fee("N/A", "invalid") == "0"
    assert _calculate_professional_fee("", "") == "0"

    # Verify preview fields include all 3 fees
    preview_fields = dict((f[0], f[1]) for f in claim.all_fields_for_preview())
    assert "Survey Fee (₹)" in preview_fields
    assert "Reinspection Fee (₹)" in preview_fields
    assert "Prof. Fee (Total ₹)" in preview_fields
    assert preview_fields["Survey Fee (₹)"] == "1500.50"
    assert preview_fields["Reinspection Fee (₹)"] == "500.25"
    assert preview_fields["Prof. Fee (Total ₹)"] == "2000.75"


def test_email_id_regex_first_and_fallback(tmp_path):
    """
    Test Email ID discovery:
    1. Regex-first finds .com email (e.g. cell I4 or anywhere on Sheet1) without requiring labels.
    2. Fallback to standard label-based search if no .com regex match is present.
    """
    from app.data.excel_reader import extract_claim_data

    # Scenario 1: Email at cell I4 (Row 4, Column I -> index r=3, c=8) without any label
    wb1 = openpyxl.Workbook()
    ws1 = wb1.active
    ws1.title = "Sheet1"
    ws1["A1"] = "Claim Number"
    ws1["B1"] = "CLM-998877"
    # Row 4, Column I is I4
    ws1["I4"] = "surveyor_office@gmail.com"
    file1 = tmp_path / "email_test_i4.xlsx"
    wb1.save(str(file1))

    claim1 = extract_claim_data(str(file1), portal_id="uiic")
    assert claim1.email_id == "surveyor_office@gmail.com"
    assert "I4 (Sheet1)" in claim1._excel_coords.get("email_id", "")

    # Scenario 2: Embedded email inside text cell without explicit "email" label
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2.title = "Sheet1"
    ws2["C2"] = "Head Office Contact: support.survey@insurance-audit.com (Direct)"
    file2 = tmp_path / "email_test_regex_embedded.xlsx"
    wb2.save(str(file2))

    claim2 = extract_claim_data(str(file2), portal_id="uiic")
    assert claim2.email_id == "support.survey@insurance-audit.com"

    # Scenario 3: No .com email, but standard label "email" exists with non-.com email (fallback)
    wb3 = openpyxl.Workbook()
    ws3 = wb3.active
    ws3.title = "Sheet1"
    ws3["A5"] = "email"
    ws3["B5"] = "surveyor@portal.gov.in"
    file3 = tmp_path / "email_test_fallback_label.xlsx"
    wb3.save(str(file3))

    claim3 = extract_claim_data(str(file3), portal_id="uiic")
    assert claim3.email_id == "surveyor@portal.gov.in"

    # Scenario 4: No email anywhere in workbook
    wb4 = openpyxl.Workbook()
    ws4 = wb4.active
    ws4.title = "Sheet1"
    ws4["A1"] = "Some Header"
    file4 = tmp_path / "email_test_empty.xlsx"
    wb4.save(str(file4))

    claim4 = extract_claim_data(str(file4), portal_id="uiic")
    assert claim4.email_id == ""


def test_expected_completion_date_calculation_and_preview():
    """
    Requirement (Point 14):
    - expected_completion_date is dependent ONLY and ONLY on date_of_survey.
    - If date_of_survey is present: expected_completion_date = date_of_survey + 1 calendar month.
    - Handles leap years and month-end clamping (e.g. 31/01/2024 -> 29/02/2024, 31/01/2026 -> 28/02/2026).
    - If date_of_survey is not present / empty: both date_of_survey and expected_completion_date remain blank.
    """
    from app.data.data_model import _add_one_calendar_month, ClaimData

    # 1. Calendar math tests
    # User's actual date from UI screenshot: 27/04/2023 -> 27/05/2023
    assert _add_one_calendar_month("27/04/2023") == "27/05/2023"
    assert _add_one_calendar_month("15/05/2026") == "15/06/2026"
    # Non-leap year February month-end (28 days)
    assert _add_one_calendar_month("31/01/2026") == "28/02/2026"
    assert _add_one_calendar_month("29/01/2026") == "28/02/2026"
    # Leap year February month-end (29 days in 2024)
    assert _add_one_calendar_month("31/01/2024") == "29/02/2024"
    assert _add_one_calendar_month("29/01/2024") == "29/02/2024"
    # 31st to 30-day month
    assert _add_one_calendar_month("31/03/2026") == "30/04/2026"
    assert _add_one_calendar_month("31/08/2026") == "30/09/2026"
    assert _add_one_calendar_month("31/10/2026") == "30/11/2026"
    # Year rollover (December -> January)
    assert _add_one_calendar_month("15/12/2026") == "15/01/2027"
    assert _add_one_calendar_month("31/12/2026") == "31/01/2027"
    # Empty or invalid inputs
    assert _add_one_calendar_month("") == ""
    assert _add_one_calendar_month(None) == ""
    assert _add_one_calendar_month("invalid-date") == ""

    # 2. ClaimData integration: When date_of_survey is present
    claim = ClaimData()
    claim.date_of_survey = "27/04/2023"
    claim._excel_coords["date_of_survey"] = "R65C6 (Survey report)"
    claim.final_report_date = "01/09/2026"  # Should NOT affect expected_completion_date
    claim.calculate_derived_fields()

    assert claim.expected_completion_date == "27/05/2023"
    assert claim._excel_coords.get("expected_completion_date") == "R65C6 (Survey report)"

    # Verify preview dictionary for UIIC
    preview_dict = dict((item[0], item[1]) for item in claim.all_fields_for_preview())
    assert preview_dict["Date of Survey"] == "27/04/2023"
    assert preview_dict["Expected Compl. Date"] == "27/05/2023"

    # 3. ClaimData integration: When date_of_survey is NOT present (both blank)
    claim_empty = ClaimData()
    claim_empty.date_of_survey = ""
    claim_empty.final_report_date = "01/09/2026"  # Even if report date exists, must stay blank!
    claim_empty.calculate_derived_fields()

    assert claim_empty.date_of_survey == ""
    assert claim_empty.expected_completion_date == ""
    assert "expected_completion_date" not in claim_empty._excel_coords

    preview_empty = dict((item[0], item[1]) for item in claim_empty.all_fields_for_preview())
    assert preview_empty["Date of Survey"] == ""
    assert preview_empty["Expected Compl. Date"] == ""


def test_professional_fee_cross_portal_isolation(tmp_path):
    """
    Ensure professional_fee calculation does NOT break New India or OIC portals:
    - New India: extracts professional_fee directly from Excel, must NOT be overwritten to 0.
    - OIC: extracts professional_fee directly from Excel, must NOT be overwritten to 0.
    - UIIC: derives professional_fee = survey_fee + reinspection_fee.
    """
    from app.data.excel_reader import extract_claim_data

    # 1. New India workbook with extracted professional_fee
    wb_nia = openpyxl.Workbook()
    ws_nia = wb_nia.active
    ws_nia.title = "Sheet1"
    ws_nia["A1"] = "professional fee"
    ws_nia["B1"] = "3500"
    file_nia = tmp_path / "nia_prof_fee.xlsx"
    wb_nia.save(str(file_nia))

    claim_nia = extract_claim_data(str(file_nia), portal_id="newindia")
    assert claim_nia.professional_fee == "3500", "New India professional_fee must not be overwritten to 0!"

    # 2. OIC workbook with extracted professional_fee
    wb_oic = openpyxl.Workbook()
    ws_oic = wb_oic.active
    ws_oic.title = "Sheet1"
    ws_oic["A1"] = "professional fee"
    ws_oic["B1"] = "4200"
    file_oic = tmp_path / "oic_prof_fee.xlsx"
    wb_oic.save(str(file_oic))

    claim_oic = extract_claim_data(str(file_oic), portal_id="oic")
    assert claim_oic.professional_fee == "4200", "OIC professional_fee must not be overwritten to 0!"

    # 3. UIIC workbook with survey_fee and reinspection_fee
    wb_uiic = openpyxl.Workbook()
    ws_uiic = wb_uiic.active
    ws_uiic.title = "Sheet1"
    ws_uiic["A1"] = "Survey Fee"
    ws_uiic["B1"] = "2000"
    ws_uiic["A2"] = "Reinspection Fee"
    ws_uiic["B2"] = "750"
    file_uiic = tmp_path / "uiic_prof_fee.xlsx"
    wb_uiic.save(str(file_uiic))

    claim_uiic = extract_claim_data(str(file_uiic), portal_id="uiic")
    assert claim_uiic.survey_fee == "2000"
    assert claim_uiic.reinspection_fee == "750"
    assert claim_uiic.professional_fee == "2750", "UIIC professional_fee must equal survey_fee + reinspection_fee"


def test_survey_time_extraction_and_fallback(tmp_path):
    """
    Test survey time extraction and fallback:
    1. Robust _parse_time_string for 12h and 24h formats.
    2. Extraction when time is in the date cell.
    3. Extraction when time is in an adjacent cell.
    4. Fallback to 11 HH and 00 MM when time is missing in Excel.
    5. Blank when date_of_survey is missing.
    """
    from app.data.excel_reader import _parse_time_string, extract_claim_data

    # 1. Parsing tests
    assert _parse_time_string("11:30 AM") == ("11", "30")
    assert _parse_time_string("11.30am") == ("11", "30")
    assert _parse_time_string("02:45 PM") == ("14", "45")
    assert _parse_time_string("2 PM") == ("14", "00")
    assert _parse_time_string("14:30") == ("14", "30")
    assert _parse_time_string("2023-04-27 15:45:00") == ("15", "45")
    assert _parse_time_string("") is None
    assert _parse_time_string("no time here") is None

    # 2. Time in date cell
    wb1 = openpyxl.Workbook()
    ws1 = wb1.active
    ws1.title = "Sheet1"
    ws1["A1"] = "Date and Time of Survey"
    ws1["E1"] = "27/04/2023 15:30"
    f1 = tmp_path / "time_in_cell.xlsx"
    wb1.save(str(f1))

    c1 = extract_claim_data(str(f1), portal_id="uiic")
    assert c1.time_hh == "15"
    assert c1.time_mm == "30"

    # 3. Time in adjacent cell
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2.title = "Sheet1"
    ws2["A1"] = "Date and Time of Survey"
    ws2["E1"] = "27/04/2023"
    ws2["F1"] = "02:15 PM"
    f2 = tmp_path / "time_adjacent.xlsx"
    wb2.save(str(f2))

    c2 = extract_claim_data(str(f2), portal_id="uiic")
    assert c2.time_hh == "14"
    assert c2.time_mm == "15"

    # 4. Missing time in Excel -> Fallback to 11:00
    wb3 = openpyxl.Workbook()
    ws3 = wb3.active
    ws3.title = "Sheet1"
    ws3["A1"] = "Date and Time of Survey"
    ws3["E1"] = "27/04/2023"
    f3 = tmp_path / "time_missing.xlsx"
    wb3.save(str(f3))

    c3 = extract_claim_data(str(f3), portal_id="uiic")
    assert c3.date_of_survey == "27/04/2023"
    assert c3.time_hh == "11"
    assert c3.time_mm == "00"
    preview3 = dict((item[0], item[1]) for item in c3.all_fields_for_preview())
    assert preview3["Time of Survey"] == "11:00"

    # 5. Missing date_of_survey -> both date and time remain blank
    wb4 = openpyxl.Workbook()
    ws4 = wb4.active
    ws4.title = "Sheet1"
    ws4["A1"] = "Claim Number"
    ws4["B1"] = "CLM-123"
    f4 = tmp_path / "no_date.xlsx"
    wb4.save(str(f4))

    c4 = extract_claim_data(str(f4), portal_id="uiic")
    assert c4.date_of_survey == ""
    assert c4.time_hh == ""
    assert c4.time_mm == ""
    preview4 = dict((item[0], item[1]) for item in c4.all_fields_for_preview())
    assert preview4["Time of Survey"] == ""


def test_gst_summary_parts_and_labour_config_and_preview(tmp_path):
    """
    Verifies that gst_summary_parts and gst_summary_labour:
    1. Are defined in UIIC field_mapping.json with editable search_label, sheet, and offsets.
    2. Exist on ClaimData with case-insensitive property aliases (GST_summary_parts/GST_summary_labour).
    3. Appear in UI preview table for UIIC workspace.
    4. Automatically populate Net Assessed Parts (parts_nil_dep_excl_gst) and Labour (labour_excl_gst)
       when primary fields are 0/empty.
    5. Successfully extract from Excel via configured search labels and offsets.
    """
    from app.utils import load_field_mapping
    from app.data.data_model import ClaimData
    from app.data.excel_reader import extract_claim_data

    # 1. Config presence
    mapping = load_field_mapping(portal_id="uiic")
    assert "gst_summary_parts" in mapping
    assert "gst_summary_labour" in mapping
    assert "GST SUMMARY – SPARES" in mapping["gst_summary_parts"]["search_label"] or \
           "GST SUMMARY – SPARES" in mapping["gst_summary_parts"].get("search_labels", [])
    assert "GST SUMMARY – LABOUR" in mapping["gst_summary_labour"]["search_label"] or \
           "GST SUMMARY – LABOUR" in mapping["gst_summary_labour"].get("search_labels", [])

    # 2. Data model and property aliases
    claim = ClaimData(portal_id="uiic")
    assert claim.gst_summary_parts == "0"
    assert claim.gst_summary_labour == "0"
    assert claim.GST_summary_parts == "0"
    assert claim.GST_summary_labour == "0"

    claim.GST_summary_parts = "15420"
    claim.GST_summary_labour = "3850"
    assert claim.gst_summary_parts == "15420"
    assert claim.gst_summary_labour == "3850"

    # 3. UI preview table contains the fields
    preview = dict((item[0], item[1]) for item in claim.all_fields_for_preview())
    assert "GST Summary Parts (₹)" in preview
    assert preview["GST Summary Parts (₹)"] == "15420"
    assert "GST Summary Labour (₹)" in preview
    assert preview["GST Summary Labour (₹)"] == "3850"

    # 4. Fallback into Net Assessed Parts and Labour when 0
    claim.parts_nil_dep_excl_gst = "0"
    claim.labour_excl_gst = "0"
    claim.calculate_derived_fields()
    assert claim.parts_nil_dep_excl_gst == "15420"
    assert claim.labour_excl_gst == "3850"

    # Existing non-zero values are NOT overwritten
    claim2 = ClaimData(portal_id="uiic")
    claim2.parts_nil_dep_excl_gst = "8888"
    claim2.labour_excl_gst = "2222"
    claim2.gst_summary_parts = "15420"
    claim2.gst_summary_labour = "3850"
    claim2.calculate_derived_fields()
    assert claim2.parts_nil_dep_excl_gst == "8888"
    assert claim2.labour_excl_gst == "2222"

    # 5. Extraction from Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["D10"] = "GST SUMMARY – SPARES"
    # Row offset = 4, Col offset = 1 -> Row 14, Col E
    ws.cell(row=14, column=5, value=12550.0)

    ws["D20"] = "GST SUMMARY – LABOUR"
    ws.cell(row=24, column=5, value="₹ 4,300")

    f = tmp_path / "test_gst_summary.xlsx"
    wb.save(str(f))

    extracted = extract_claim_data(str(f), portal_id="uiic")
    assert extracted.gst_summary_parts == "12550"
    assert extracted.gst_summary_labour == "4300"
    assert extracted.parts_nil_dep_excl_gst == "12550"
    assert extracted.labour_excl_gst == "4300"




