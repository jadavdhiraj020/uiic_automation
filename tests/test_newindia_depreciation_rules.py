"""New India Maruti rows: Depreciation column rules and full painting amount.

Run from the project folder:
    uv run pytest tests/test_newindia_depreciation_rules.py -v

All values are synthetic; no browser is started.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data import excel_reader as er  # noqa: E402
from app.data.data_model import ClaimData  # noqa: E402
from app.data.excel_parts_extractor import _detect_labour_header, extract_painting_rows  # noqa: E402
from app.portals.newindia.automation.maruti_rows import (  # noqa: E402
    DepreciationRules,
    build_depreciation_rules,
    read_maruti_items,
)
from app.portals.newindia.scan_outputs import ASSESSMENT_SHEET, ASSESSMENT_WORKBOOK  # noqa: E402


class _Sheet:
    """Minimal stand-in for the reader's sheet wrapper."""

    def __init__(self, rows):
        self._rows = rows

    def rows(self):
        return self._rows


# ── Excel cells → percentage ────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    (12.5, "12.5"), ("12.50", "12.5"), (3.6305555555555555, "3.63"), (25, "25"), (0, "0"), ("12.5%", "12.5"),
    (-119.88, None), (100, None), ("abc", None), (None, None), ("", None),
])
def test_parse_depreciation_pct(raw, expected):
    assert er._parse_depreciation_pct(raw) == expected


def test_paint_pct_is_read_from_the_cell_left_of_label():
    sheet = _Sheet([[12.5, "% LESS COST OF PAINT MATERIAL / PAINT DEP.", None, 3750]])
    value, coord = er._search_label(
        sheet, "LESS COST OF PAINT MATERIAL", 0, -1,
        exact_offset=True, cell_parser=er._parse_depreciation_pct,
    )
    assert value == "12.5" and coord == "R1C1"


def test_metal_pct_uses_only_the_left_cell():
    # Value only on the right of the label: exact left-cell reading must not pick it up.
    right_only = _Sheet([["Life", None, "SO, DEP. ON METAL (IN %)", None, 25]])
    assert er._search_label(
        right_only, "DEP. ON METAL (IN %)", 0, -1,
        exact_offset=True, cell_parser=er._parse_depreciation_pct,
    ) == (None, None)
    left = _Sheet([[None, 25, "SO, DEP. ON METAL (IN %)", None]])
    value, _ = er._search_label(
        left, "DEP. ON METAL (IN %)", 0, -1,
        exact_offset=True, cell_parser=er._parse_depreciation_pct,
    )
    assert value == "25"


# ── Rules ───────────────────────────────────────────────────────────────────

def _claim(nil="No", metal="25", paint="12.5"):
    claim = ClaimData(portal_id="newindia")
    claim.nil_depreciation = nil
    claim.metal_depreciation_pct = metal
    claim.paint_depreciation_pct = paint
    return claim


def test_nil_depreciation_yes_makes_every_row_zero():
    rules = build_depreciation_rules(_claim(nil="Yes"), {"plastic_depreciation_pct": "50"})
    assert {rules.for_item(k) for k in ("Plastic", "Metal", "Painting", "Glass", "Labour")} == {Decimal("0")}
    assert rules.missing() == []


def test_nil_depreciation_no_uses_plastic_default_and_excel_values():
    rules = build_depreciation_rules(_claim(nil="No"), {"plastic_depreciation_pct": "50"})
    assert rules.for_item("Plastic") == Decimal("50")
    assert rules.for_item("Metal") == Decimal("25")
    assert rules.for_item("Painting") == Decimal("12.5")
    assert rules.for_item("Glass") == Decimal("0")
    assert rules.for_item("Labour") == Decimal("0")


def test_missing_nil_depreciation_counts_as_no():
    rules = build_depreciation_rules(_claim(nil=""), {})
    assert rules.for_item("Plastic") == Decimal("50")
    assert rules.for_item("Metal") == Decimal("25")


def test_missing_excel_percentages_use_zero_and_are_reported():
    rules = build_depreciation_rules(_claim(metal="", paint=""), {})
    assert rules.for_item("Metal") == Decimal("0")
    assert rules.for_item("Painting") == Decimal("0")
    assert rules.missing() == ["Metal", "Painting"]


def test_plastic_setting_is_used_and_bad_values_fall_back_to_50():
    assert build_depreciation_rules(_claim(), {"plastic_depreciation_pct": "40"}).plastic == Decimal("40")
    bad = build_depreciation_rules(_claim(), {"plastic_depreciation_pct": "abc"})
    assert bad.plastic == Decimal("50") and bad.plastic_setting_invalid


# ── Workbook rows ───────────────────────────────────────────────────────────

_HEADER = (
    "SlNo", "category", "description", "partName", "serviceType", "estimatedAmount",
    "billedAmount", "assessedAmount", "depreciationPercentage", "hsnCode", "gstPercentage",
)


def _workbook(tmp_path):
    path = tmp_path / ASSESSMENT_WORKBOOK
    wb = Workbook()
    ws = wb.active
    ws.title = ASSESSMENT_SHEET
    ws.append(_HEADER)
    ws.append((1, "Spare Parts", "Parts at Agewise Depreciation", "Fender", "REPLACE", 0, 6000, 6000, 0, "", 0))
    ws.append((2, "Spare Parts", "Parts at 50% Depreciation", "Grille", "REPLACE", 0, 2000, 2000, 0, "", 0))
    ws.append((3, "Spare Parts", "Parts at Cost", "Windshield", "REPLACE", 0, 8000, 8000, 0, "", 0))
    ws.append((4, "Labor Charges", "Labor charges for Repairing and Alignment", "Fender R/R", "ALLOW", 0, 700, 700, 0, "", 0))
    ws.append((5, "Painting", "Painting", "Bonnet (N)", "REPAIR", 0, 5000, 5000, 0, "", 0))
    wb.save(path)
    return str(path)


def test_workbook_rows_get_depreciation_by_item_and_keep_full_amount(tmp_path):
    rules = build_depreciation_rules(_claim(nil="No"), {"plastic_depreciation_pct": "50"})
    items = {item.description: item.values() for item in read_maruti_items(_workbook(tmp_path), rules=rules)}
    assert items["Fender"]["depreciation"] == "25" and items["Fender"]["amount"] == "6000"
    assert items["Grille"]["depreciation"] == "50" and items["Grille"]["amount"] == "2000"
    assert items["Windshield"]["depreciation"] == "0"
    assert items["Fender R/R"]["depreciation"] == "0" and items["Fender R/R"]["amount"] == "700"
    assert items["Bonnet (N)"]["depreciation"] == "12.5" and items["Bonnet (N)"]["amount"] == "5000"


def test_nil_depreciation_yes_zeroes_workbook_rows_but_not_amounts(tmp_path):
    rules = build_depreciation_rules(_claim(nil="Yes"), {})
    values = [item.values() for item in read_maruti_items(_workbook(tmp_path), rules=rules)]
    assert {v["depreciation"] for v in values} == {"0"}
    assert "5000" in {v["amount"] for v in values}


def test_without_rules_every_row_keeps_depreciation_zero(tmp_path):
    values = [item.values() for item in read_maruti_items(_workbook(tmp_path))]
    assert {v["depreciation"] for v in values} == {"0"}


# ── Painting rows from the source Excel ─────────────────────────────────────

def test_painting_rows_use_full_excel_paint_value():
    wb = Workbook()
    ws = wb.active
    ws.append(["S.N.", "DESCRIPTION", "Estimate", "R/R", "DENTING", "C/W", "PAINT", "GST"])
    ws.append([1, "Labour", 35000, 0, 0, 0, 0, 18])
    ws.append([2, "RH F/R door (R)", None, 450, 0, 0, 4500, 18])
    ws.append([3, "Bonnet (N)", None, 500, 0, 0, 5000, 18])
    ws.append([4, "RH H/Light (N)", None, 200, 0, 0, 0, 18])
    ws.append(["SUB TOTAL", None, 35000, 1150, 0, 0, 9500])
    ws.append([12.5, "% LESS COST OF PAINT MATERIAL / PAINT DEP."])
    detection = _detect_labour_header(ws)
    rows = extract_painting_rows(ws, detection.row, detection.col_map)
    assert [(r["part_name"], r["assessed_amount"]) for r in rows] == [
        ("RH F/R door (R)", 4500.0), ("Bonnet (N)", 5000.0),
    ]


# ── Extraction Review chips ─────────────────────────────────────────────────

def _depreciation_warnings(claim):
    _errors, warnings = claim._validate_newindia()
    return [w for w in warnings if "Depreciation %" in w]


def test_warning_chip_when_percentages_missing_and_nil_dep_not_yes():
    warnings = _depreciation_warnings(_claim(nil="No", metal="", paint=""))
    assert any(w.startswith("Metal Depreciation % not found") for w in warnings)
    assert any(w.startswith("Painting Depreciation % not found") for w in warnings)


def test_no_warning_when_nil_depreciation_yes_or_values_found():
    assert _depreciation_warnings(_claim(nil="Yes", metal="", paint="")) == []
    assert _depreciation_warnings(_claim(nil="No", metal="25", paint="12.5")) == []
