import os
from pathlib import Path
from app.data.excel_reader import extract_claim_data

def test_dummy_uiic_excel_extraction():
    """Verify that dummy_uiic_testing.xlsx extracts all required and optional fields cleanly."""
    excel_path = "dummy_uiic_testing.xlsx" if os.path.exists("dummy_uiic_testing.xlsx") else "UIIC_TEST/dummy_uiic_testing.xlsx"
    assert os.path.exists(excel_path), f"File {excel_path} should exist"

    claim = extract_claim_data(excel_path, portal_id="uiic")
    claim.calculate_derived_fields()

    # 1. Validation must pass with 0 errors
    errors, warnings = claim.validate()
    assert len(errors) == 0, f"Expected 0 validation errors, got: {errors}"

    # 2. Mandatory Fields Check
    assert claim.claim_no == "2230003126C065430001"
    assert claim.date_of_survey == "20/04/2026"
    assert claim.time_hh == "11"
    assert claim.time_mm == "30"
    assert "Authorized Service Workshop" in claim.place_of_survey
    assert claim.initial_loss_amount == "75000"  # 75% of 100000
    assert claim.final_report_no == "JDB/2026-27/UIIC/8744"
    assert claim.labour_excl_gst == "12000"
    assert claim.payment_to == "REPAIRER"

    # 3. Derived Business Logic
    assert claim.expected_completion_date == "20/05/2026"
    assert claim.survey_fee == "2500"
    assert claim.reinspection_fee == "750"
    assert claim.professional_fee == "3250"  # 2500 + 750
    assert claim.traveling_expenses == "500"
    assert claim.daily_allowance == "250"
    assert claim.photo_charges == "300"
    assert claim.total_claimed_amount == "4300"  # 3250 + 500 + 250 + 300

    # 4. Optional Fields Check
    assert claim.mobile_no == "9814035162"
    assert claim.email_id == "jd.batta8810@gmail.com"
    assert claim.nil_depreciation == "Yes"
    assert claim.parts_age_dep_excl_gst == "15000"
    assert claim.parts_50_dep_excl_gst == "4500"
    assert claim.parts_nil_dep_excl_gst == "6000"
    assert claim.parts_gst18_amount == "4590"
    assert claim.gst_summary_parts == "25500"
    assert claim.gst_summary_labour == "12000"
    assert claim.towing_charges == "1500"
    assert claim.voluntary_excess == "0"
    assert claim.compulsory_excess == "1000"
    assert claim.imposed_excess == "0"
    assert claim.salvage_value == "1200"
    assert claim.invoice_no == "INV-2026-0042"
    assert claim.invoice_date == "25/04/2026"
    assert claim.final_report_date == "25/04/2026"
    assert "Vehicle inspected" in claim.surveyor_observation or claim.surveyor_observation == "Ok"
