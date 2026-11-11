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

