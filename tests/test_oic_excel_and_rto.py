import pytest
from openpyxl import Workbook

from app.data.excel_reader import extract_claim_data
from app.portals.oic.automation.basic_details_module import _resolve_charges_filed
from app.portals.oic.automation.date_formatter import format_oic_date
from app.portals.oic.city_mapping import _licence_cities
from app.portals.oic.rto_mapping import portal_rto_options, resolve_rto_choice
from app.utils import load_automation_defaults


def _extract(monkeypatch, tmp_path, rows, mapping, portal="oic"):
    monkeypatch.setattr("app.utils.load_field_mapping", lambda portal_id: mapping)
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    path = tmp_path / "claim.xlsx"
    workbook.save(path)
    return extract_claim_data(str(path), portal_id=portal)


@pytest.mark.parametrize("label", ["Date", "Date.", "Date:"])
@pytest.mark.parametrize("heading", ["Date", "Date.", "Date:"])
def test_oic_date_labels_match_with_or_without_punctuation(monkeypatch, tmp_path, label, heading):
    claim = _extract(
        monkeypatch, tmp_path, [["Date of Accident", "10/01/2026"], [heading, "17/09/2026"]],
        {"date_of_survey": {"search_labels": [label]}},
    )
    assert claim.date_of_survey == "17/09/2026"
    assert claim._excel_coords["date_of_survey"] == "R2C2 (Sheet)"


def test_oic_existing_date_label_wins_over_punctuation_fallback(monkeypatch, tmp_path):
    claim = _extract(
        monkeypatch, tmp_path, [["Date", "10/01/2026"], ["Survey Date:", "17/09/2026"]],
        {"date_of_survey": {"search_labels": ["Date.", "Survey Date:"]}},
    )
    assert claim.date_of_survey == "17/09/2026"


def test_oic_punctuation_preserves_survey_time_fitness_and_numeric_values(monkeypatch, tmp_path):
    claim = _extract(
        monkeypatch, tmp_path,
        [
            ["Date of Survey", "17/09/2026", "11:32 AM"],
            ["Fitness Cert Valid Upto", "17.09.2033"],
            ["Charges Filed.", "Case 17.05"],
            ["Misc. Charges: 123.45"],
        ],
        {
            "date_of_survey": {"search_labels": ["Date of Survey:"]},
            "fitness_valid_upto": {"search_labels": ["Fitness Cert. Valid Upto"]},
            "charges_filed": {"search_labels": ["Charges Filed"], "allow_text_values": True},
            "misc_charges": {
                "search_labels": ["Misc Charges"], "col_offset": 0, "inline_amount": True,
            },
        },
    )
    assert (claim.time_hh, claim.time_mm) == ("11", "32")
    assert claim.fitness_valid_upto == "17/09/2033"
    assert ("Fitness Valid Upto", "17/09/2033", False, "R2C2 (Sheet)") in claim._preview_oic()
    assert format_oic_date(claim.fitness_valid_upto) == "17-09-2033"
    assert claim.charges_filed == "Case 17.05"
    assert claim.misc_charges == "123.45"


def test_uiic_keeps_existing_punctuation_matching(monkeypatch, tmp_path):
    claim = _extract(
        monkeypatch, tmp_path, [["Date", "17/09/2026"]],
        {"date_of_survey": {"search_labels": ["Date:"]}}, portal="uiic",
    )
    assert not claim.date_of_survey


def test_oic_charges_filed_does_not_pick_up_unrelated_fees(monkeypatch, tmp_path):
    claim = _extract(
        monkeypatch, tmp_path, [["Re-inspection Charges", "1000"], ["Misc. Charges", "50"]],
        {"charges_filed": {"search_labels": ["Charges Filed", "Charges"], "allow_text_values": True}},
    )
    assert not claim.charges_filed


@pytest.mark.parametrize(
    ("registration", "report", "options", "name", "source"),
    [
        ("PB01AB1234", "PB01", ["CHALAKKUDY", "STA Punjab"], "STA Punjab", "registration code"),
        ("", "PB-01", ["CHALAKKUDY", "PB-01 STA Punjab"], "PB-01 STA Punjab", "report RTO code"),
        ("PB010002", "", ["CHALAKKUDY", "Chandigarh", "Nangal"], "Nangal", "same-state fallback"),
        ("PB99AB1234", "", ["Chandigarh", "Gurdaspur", "DINANAGAR"], "DINANAGAR", "registration code"),
        ("PB99AB1234", "", ["Chandigarh", "Gurdaspur"], "Gurdaspur", "district fallback"),
        ("GJ13AB1234", "PB01", ["Chandigarh", "VADODARA"], "VADODARA", "same-state fallback"),
        ("DL01AB1234", "", ["NORTH PAROOR", "NORTH DELHI"], "NORTH DELHI", "registration code"),
        ("OD19AB1234", "", ["CHALAKKUDY", "Cuttack"], "Cuttack", "same-state fallback"),
        ("TS99AB1234", "", ["CHALAKKUDY", "Karimnagar"], "Karimnagar", "same-state fallback"),
        ("GJ99AB1234", "", ["CHALAKKUDY"], "", ""),
    ],
)
def test_rto_uses_exact_office_or_same_state(registration, report, options, name, source):
    choice = resolve_rto_choice(registration, report, options)
    assert (choice.name, choice.source) == (name, source)


def test_rto_logs_conflicting_report_state_even_for_an_unknown_office_code():
    choice = resolve_rto_choice("GJ99AB1234", "Patiala", ["Patiala", "VADODARA"])
    assert choice.name == "VADODARA"
    assert choice.possible_mismatch


def test_saved_oic_dropdown_covers_every_state_and_territory_in_the_directory():
    prefixes = {code[:2] for code in _licence_cities()}
    options = portal_rto_options()
    for prefix in prefixes:
        choice = resolve_rto_choice(f"{prefix}00AB1234", "", options)
        assert choice.name, prefix
        assert choice.source == "same-state fallback", prefix


def test_charges_filed_uses_report_then_optional_oic_default(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert load_automation_defaults(portal_id="oic")["charges_filed_default"] == ""
    assert _resolve_charges_filed("", {"charges_filed_default": "  "}) == ("", "")
    assert _resolve_charges_filed("", {"charges_filed_default": " No charges "}) == (
        "No charges", "Automation Defaults",
    )
    assert _resolve_charges_filed(" Case 12 ", {"charges_filed_default": "No charges"}) == ("Case 12", "")
