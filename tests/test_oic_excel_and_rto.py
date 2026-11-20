from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from openpyxl import Workbook

from app.data.data_model import ClaimData
from app.data.excel_reader import extract_claim_data
from app.portals.oic.automation import basic_details_module
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
            ["Misc. Charges: 123.45"],
        ],
        {
            "date_of_survey": {"search_labels": ["Date of Survey:"]},
            "fitness_valid_upto": {"search_labels": ["Fitness Cert. Valid Upto"]},
            "misc_charges": {
                "search_labels": ["Misc Charges"], "col_offset": 0, "inline_amount": True,
            },
        },
    )
    assert (claim.time_hh, claim.time_mm) == ("11", "32")
    assert claim.fitness_valid_upto == "17/09/2033"
    assert ("Fitness Valid Upto", "17/09/2033", False, "R2C2 (Sheet)") in claim._preview_oic()
    assert format_oic_date(claim.fitness_valid_upto) == "17-09-2033"
    assert claim.misc_charges == "123.45"


def test_uiic_keeps_existing_punctuation_matching(monkeypatch, tmp_path):
    claim = _extract(
        monkeypatch, tmp_path, [["Date", "17/09/2026"]],
        {"date_of_survey": {"search_labels": ["Date:"]}}, portal="uiic",
    )
    assert not claim.date_of_survey


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
        ("OR02AB1234", "OD02", ["OD99 - Other Office", "OD02 - Khordha"], "OD02 - Khordha", "registration code"),
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


def test_legacy_rto_prefix_and_current_office_code_do_not_conflict():
    choice = resolve_rto_choice("TS09AB1234", "TG09", ["TG09 - Hyderabad"])
    assert choice.name == "TG09 - Hyderabad"
    assert not choice.possible_mismatch


def test_saved_oic_dropdown_covers_every_state_and_territory_in_the_directory():
    prefixes = {code[:2] for code in _licence_cities()}
    options = portal_rto_options()
    for prefix in prefixes:
        choice = resolve_rto_choice(f"{prefix}00AB1234", "", options)
        assert choice.name, prefix
        assert choice.source == "same-state fallback", prefix


def test_charges_filed_ignores_excel_and_old_field_mappings(monkeypatch, tmp_path):
    from app.utils import load_field_mapping, save_field_mapping

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_field_mapping({
        "charges_filed": {"search_labels": ["Charges Filed", "Charges"], "allow_text_values": True},
    }, portal_id="oic")
    assert "charges_filed" not in load_field_mapping(portal_id="oic")
    workbook = Workbook()
    workbook.active.append(["Charges Filed", "Case 12"])
    path = tmp_path / "claim.xlsx"
    workbook.save(path)
    claim = extract_claim_data(str(path), portal_id="oic")
    assert not claim.charges_filed
    assert ("Charges Filed", "", False, "") in claim.all_fields_for_preview()

    assert load_automation_defaults(portal_id="oic")["charges_filed_default"] == ""
    assert _resolve_charges_filed({"charges_filed_default": "  "}) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", ["", "No charges"])
async def test_charges_filed_only_fills_from_automation_defaults(monkeypatch, configured):
    fill = AsyncMock()
    monkeypatch.setattr(basic_details_module, "fill_input_with_delay", fill)
    for name in ("_fill_driver_name", "field_problem", "_select_pincode_dropdown", "click_primeng_radio"):
        monkeypatch.setattr(basic_details_module, name, AsyncMock(return_value=True))
    page = Mock()
    claim = ClaimData(portal_id="oic", charges_filed="Case 12", driver_address="Driver Address")
    defaults = {"charges_filed_default": configured}
    monkeypatch.setattr(basic_details_module, "load_automation_defaults", lambda **_: defaults)

    assert await basic_details_module._fill_driver_details(page, claim, Mock(), 0, defaults)

    values = [call.args[2] for call in fill.await_args_list if call.args[3] == "Charges Filed"]
    assert values == ([configured] if configured else [])
    assert (
        "Charges Filed", configured, False, "Automation Defaults" if configured else "",
    ) in claim.all_fields_for_preview()


@pytest.mark.asyncio
async def test_vehicle_age_sends_the_same_years_and_months_as_preview(monkeypatch):
    claim = ClaimData(
        portal_id="oic", date_of_registration="14.03.2021", date_of_accident="2026-10-14T15:00:00.000",
    )
    claim.calculate_derived_fields()
    fill = AsyncMock()
    monkeypatch.setattr(basic_details_module, "fill_input_with_delay", fill)
    monkeypatch.setattr(basic_details_module, "click_primeng_radio", AsyncMock())
    page, log = Mock(), Mock()

    await basic_details_module._fill_loss_details(page, claim, log, 0)

    assert claim.age_of_vehicle == "5 years 7 months"
    assert ("Age of Vehicle", "5 years 7 months", False,
            "Calculated from Registration Date and Accident Date") in claim.all_fields_for_preview()
    fill.assert_any_await(page, "#vehicleAge", "5 years 7 months", "Age of Vehicle", log, 0)


@pytest.mark.parametrize(
    ("accident", "expected"),
    [("13/10/2026", "5 years 6 months"), ("14/03/2021", "0 years 0 months"), ("13/03/2021", "")],
)
def test_vehicle_age_uses_completed_months_and_skips_reversed_dates(accident, expected):
    claim = ClaimData(portal_id="oic", date_of_registration="14/03/2021", date_of_accident=accident)
    claim.calculate_derived_fields()
    assert claim.age_of_vehicle == expected


def test_uiic_calendar_dates_show_without_time_but_survey_time_is_retained(monkeypatch, tmp_path):
    claim = _extract(
        monkeypatch, tmp_path,
        [["Survey Date", datetime(2026, 10, 17, 11, 32)], ["Invoice Date", "2033-09-17T00:00:00.000"]],
        {
            "date_of_survey": {"search_labels": ["Survey Date"]},
            "invoice_date": {"search_labels": ["Invoice Date"]},
        },
        portal="uiic",
    )
    assert claim.date_of_survey == "17/10/2026"
    assert claim.invoice_date == "17/09/2033"
    assert (claim.time_hh, claim.time_mm) == ("11", "32")
    claim.workshop_invoice_date = "17-SEP-2033 00:00:00"
    preview = {row[0]: row[1] for row in claim.all_fields_for_preview()}
    assert preview["Date of Survey"] == "17/10/2026"
    assert preview["Time of Survey"] == "11:32"
    assert preview["Workshop Inv Date"] == "17/09/2033"
