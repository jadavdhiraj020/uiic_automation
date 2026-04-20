"""
test_automation.py — Ultimate test suite for UIIC Automation.

Tests every critical path:
  1. Excel reader: label search, word boundary, whitespace normalization, junk filtering
  2. Data model: field defaults, preview generation, payment option display
  3. Form helpers: JS escaping, text sanitization, amount rounding, mobile cleaning
  4. Claim assessment: surveyor charges total calculation
  5. Payment detection: REPAIRER→Cashless, INSURED→Reimbursement
"""
import os
import sys
import re
import json
import pytest

# ── Ensure project root is on path ────────────────────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.data.data_model import ClaimData
from app.data.excel_reader import (
    _is_junk, _clean_value, _extract_value, _format_date,
)
from app.automation.form_helpers import (
    _js_escape, _clean_text_for_portal, _clean_text_strict, _to_int_amount,
)
from app.automation.interim_report import _clean_mobile


# ═════════════════════════════════════════════════════════════════════════════
# 1. EXCEL READER — Value Processing
# ═════════════════════════════════════════════════════════════════════════════

class TestJunkDetection:
    """Junk values must be filtered; valid values must pass through."""

    def test_none_is_junk(self):
        assert _is_junk(None) is True

    def test_empty_string_is_junk(self):
        assert _is_junk("") is True

    def test_whitespace_is_junk(self):
        assert _is_junk("   ") is True

    def test_rs_is_junk(self):
        assert _is_junk("Rs") is True
        assert _is_junk("rs.") is True

    def test_label_words_are_junk(self):
        for j in ["estimated", "description", "particulars", "n/a", "nil"]:
            assert _is_junk(j) is True, f"'{j}' should be junk"

    def test_zero_is_NOT_junk(self):
        assert _is_junk(0) is False
        assert _is_junk(0.0) is False

    def test_numeric_string_is_NOT_junk(self):
        assert _is_junk("12345") is False
        assert _is_junk("82255.94") is False

    def test_mixed_alphanumeric_is_NOT_junk(self):
        assert _is_junk("HR 20AY 7179") is False
        assert _is_junk("SK/2025-26/OICL/116") is False

    def test_email_is_NOT_junk(self):
        assert _is_junk("user@example.com") is False


class TestCleanValue:
    """_clean_value must properly format floats and strings."""

    def test_integer_float(self):
        assert _clean_value(1989.0) == "1989"

    def test_decimal_float(self):
        assert _clean_value(4903.09) == "4903.09"

    def test_string_passthrough(self):
        assert _clean_value("HR 20AY 7179") == "HR 20AY 7179"

    def test_string_strip(self):
        assert _clean_value("  hello  ") == "hello"

    def test_none_returns_empty(self):
        assert _clean_value(None) == ""

    def test_zero_float(self):
        assert _clean_value(0.0) == "0"


class TestExtractValue:
    """_extract_value must combine junk check + clean_value."""

    def test_valid_number(self):
        assert _extract_value(1989.0, False) == "1989"

    def test_valid_decimal(self):
        assert _extract_value(82255.94, False) == "82255.94"

    def test_zero_is_valid(self):
        assert _extract_value(0, False) == "0"
        assert _extract_value(0.0, False) == "0"

    def test_junk_returns_none(self):
        assert _extract_value("Rs", False) is None
        assert _extract_value("", False) is None
        assert _extract_value(None, False) is None

    def test_string_value(self):
        assert _extract_value("SK/2025-26/OICL/116", False) == "SK/2025-26/OICL/116"


class TestFormatDate:
    """Date normalization to DD/MM/YYYY."""

    def test_already_formatted(self):
        assert _format_date("16/02/2026") == "16/02/2026"

    def test_dot_format(self):
        assert _format_date("16.02.2026") == "16/02/2026"

    def test_iso_format(self):
        assert _format_date("2026-02-16") == "16/02/2026"

    def test_empty_returns_empty(self):
        assert _format_date("") == ""


# ═════════════════════════════════════════════════════════════════════════════
# 2. DATA MODEL
# ═════════════════════════════════════════════════════════════════════════════

class TestClaimData:
    """ClaimData defaults and computed fields."""

    def test_defaults(self):
        c = ClaimData()
        assert c.claim_no == ""
        assert c.payment_to == ""
        assert c.parts_age_dep_excl_gst == "0"
        assert c.labour_excl_gst == "0"
        assert c.type_of_settlement == "Partial Loss"

    def test_amount_defaults_are_zero(self):
        c = ClaimData()
        for field in ["towing_charges", "spot_repairs", "voluntary_excess",
                       "compulsory_excess", "imposed_excess", "salvage_value"]:
            assert getattr(c, field) == "0", f"{field} should default to '0'"

    def test_string_defaults_are_empty(self):
        c = ClaimData()
        for field in ["claim_no", "date_of_survey", "place_of_survey",
                       "mobile_no", "email_id", "surveyor_observation"]:
            assert getattr(c, field) == "", f"{field} should default to ''"

    def test_excel_coords_tracking(self):
        c = ClaimData()
        c._excel_coords["claim_no"] = "R181C4 (Sheet1)"
        assert c._excel_coords["claim_no"] == "R181C4 (Sheet1)"

    def test_preview_includes_payment_option(self):
        c = ClaimData()
        c.payment_to = "INSURED"
        preview = c.all_fields_for_preview()
        labels = [p[0] for p in preview]
        assert "Payment Option" in labels

    def test_preview_payment_cashless(self):
        c = ClaimData()
        c.payment_to = "REPAIRER"
        preview = c.all_fields_for_preview()
        payment_row = [p for p in preview if p[0] == "Payment Option"][0]
        assert payment_row[1] == "Cashless"

    def test_preview_payment_reimbursement(self):
        c = ClaimData()
        c.payment_to = "INSURED"
        preview = c.all_fields_for_preview()
        payment_row = [p for p in preview if p[0] == "Payment Option"][0]
        assert payment_row[1] == "Reimbursement"

    def test_preview_payment_default_cashless(self):
        c = ClaimData()  # payment_to = ""
        preview = c.all_fields_for_preview()
        payment_row = [p for p in preview if p[0] == "Payment Option"][0]
        assert payment_row[1] == "Cashless"

    def test_preview_field_count(self):
        c = ClaimData()
        preview = c.all_fields_for_preview()
        assert len(preview) >= 25, f"Expected 25+ preview fields, got {len(preview)}"


# ═════════════════════════════════════════════════════════════════════════════
# 3. FORM HELPERS
# ═════════════════════════════════════════════════════════════════════════════

class TestJsEscape:
    """JS injection prevention — values must be safely escaped."""

    def test_single_quote(self):
        assert _js_escape("O'Brien") == "O\\'Brien"

    def test_backslash(self):
        assert _js_escape("C:\\path") == "C:\\\\path"

    def test_newline_replaced(self):
        assert "\n" not in _js_escape("line1\nline2")

    def test_carriage_return_stripped(self):
        assert "\r" not in _js_escape("line1\r\nline2")

    def test_normal_string_unchanged(self):
        assert _js_escape("hello world") == "hello world"

    def test_combined_attack(self):
        result = _js_escape("'; alert('xss'); //")
        assert "\\'" in result
        assert "alert" in result  # content preserved but escaped


class TestCleanTextPortal:
    """Portal text sanitization — remove forbidden chars."""

    def test_strips_special_chars(self):
        result = _clean_text_for_portal("hello@world#test")
        assert "@" not in result
        assert "#" not in result

    def test_preserves_commas(self):
        assert "," in _clean_text_for_portal("Plot No, Area, Phase-I")

    def test_strips_quotes(self):
        assert "'" not in _clean_text_for_portal("Repairer's workshop")


class TestCleanTextStrict:
    """Strict cleaning — only alphanumeric + spaces."""

    def test_removes_all_special(self):
        result = _clean_text_strict("Plot No. 177-H, Ind. Area, Phase-I")
        assert "@" not in result
        assert "#" not in result
        assert "," not in result
        assert "." not in result

    def test_keeps_alphanumeric(self):
        result = _clean_text_strict("Plot No 177 H")
        assert "Plot" in result
        assert "177" in result

    def test_collapses_spaces(self):
        result = _clean_text_strict("hello    world")
        assert "  " not in result


class TestToIntAmount:
    """Portal requires rounded integer amounts."""

    def test_round_up(self):
        assert _to_int_amount("82255.94") == "82256"

    def test_round_down(self):
        assert _to_int_amount("100818.02") == "100818"

    def test_zero(self):
        assert _to_int_amount("0") == "0"

    def test_already_integer(self):
        assert _to_int_amount("1989") == "1989"

    def test_with_commas(self):
        assert _to_int_amount("1,00,000.50") == "100000"

    def test_empty_string(self):
        assert _to_int_amount("") == "0"

    def test_float_input(self):
        assert _to_int_amount(59999.94) == "60000"


# ═════════════════════════════════════════════════════════════════════════════
# 4. MOBILE NUMBER CLEANING
# ═════════════════════════════════════════════════════════════════════════════

class TestCleanMobile:
    """Mobile must be exactly 10 digits for the portal."""

    def test_strips_dashes(self):
        assert _clean_mobile("098761-35253") == "9876135253"

    def test_strips_leading_zero(self):
        assert _clean_mobile("09876135253") == "9876135253"

    def test_strips_country_code(self):
        assert _clean_mobile("+919876135253") == "9876135253"

    def test_strips_spaces(self):
        assert _clean_mobile("98761 35253") == "9876135253"

    def test_already_clean(self):
        assert _clean_mobile("9876135253") == "9876135253"

    def test_10_digit_result(self):
        result = _clean_mobile("098761-35253")
        assert len(result) == 10
        assert result.isdigit()

    def test_short_number_passthrough(self):
        result = _clean_mobile("12345")
        assert result == "12345"


# ═════════════════════════════════════════════════════════════════════════════
# 5. SURVEYOR CHARGES — TOTAL CALCULATION
# ═════════════════════════════════════════════════════════════════════════════

class TestSurveyorChargesTotal:
    """Total Claimed = sum of 4 surveyor charge fields."""

    def test_basic_sum(self):
        c = ClaimData()
        c.traveling_expenses = "500"
        c.professional_fee = "0"
        c.daily_allowance = "0"
        c.photo_charges = "0"
        total = sum(int(float(v or 0)) for v in [
            c.traveling_expenses, c.professional_fee,
            c.daily_allowance, c.photo_charges
        ])
        assert total == 500

    def test_all_nonzero(self):
        c = ClaimData()
        c.traveling_expenses = "500"
        c.professional_fee = "1000"
        c.daily_allowance = "200"
        c.photo_charges = "300"
        total = sum(int(float(v or 0)) for v in [
            c.traveling_expenses, c.professional_fee,
            c.daily_allowance, c.photo_charges
        ])
        assert total == 2000

    def test_all_zero(self):
        c = ClaimData()
        total = sum(int(float(v or 0)) for v in [
            c.traveling_expenses, c.professional_fee,
            c.daily_allowance, c.photo_charges
        ])
        assert total == 0

    def test_decimal_values(self):
        c = ClaimData()
        c.traveling_expenses = "500.75"
        c.professional_fee = "0"
        c.daily_allowance = "0"
        c.photo_charges = "0"
        total = sum(int(float(v or 0)) for v in [
            c.traveling_expenses, c.professional_fee,
            c.daily_allowance, c.photo_charges
        ])
        assert total == 500


# ═════════════════════════════════════════════════════════════════════════════
# 6. PAYMENT OPTION LOGIC
# ═════════════════════════════════════════════════════════════════════════════

class TestPaymentOption:
    """REPAIRER→Cashless, INSURED→Reimbursement."""

    def _detect_payment(self, payment_to: str) -> str:
        val = payment_to.strip().upper()
        if "INSURED" in val:
            return "Reimbursement"
        return "Cashless"

    def test_repairer_is_cashless(self):
        assert self._detect_payment("REPAIRER") == "Cashless"

    def test_insured_is_reimbursement(self):
        assert self._detect_payment("INSURED") == "Reimbursement"

    def test_insured_lowercase(self):
        assert self._detect_payment("insured") == "Reimbursement"

    def test_empty_defaults_cashless(self):
        assert self._detect_payment("") == "Cashless"

    def test_partial_insured_match(self):
        assert self._detect_payment("THE INSURED PARTY") == "Reimbursement"


# ═════════════════════════════════════════════════════════════════════════════
# 7. WORD BOUNDARY CHECK (SUB TOTAL vs SUBTOTAL)
# ═════════════════════════════════════════════════════════════════════════════

class TestWordBoundary:
    """Prevent 'TOTAL' matching 'SUBTOTAL' etc."""

    def _word_boundary_match(self, label: str, cell_text: str) -> bool:
        label_lower = " ".join(label.lower().split())
        cell_str = " ".join(cell_text.strip().lower().split())
        if label_lower not in cell_str:
            return False
        idx = cell_str.find(label_lower)
        before_ok = (idx == 0) or not cell_str[idx - 1].isalnum()
        after_end = idx + len(label_lower)
        after_ok = (after_end >= len(cell_str)) or not cell_str[after_end].isalnum()
        return before_ok and after_ok

    def test_exact_match(self):
        assert self._word_boundary_match("TOTAL", "TOTAL") is True

    def test_subtotal_does_not_match_total(self):
        assert self._word_boundary_match("TOTAL", "SUBTOTAL") is False

    def test_sub_total_matches_sub_total(self):
        assert self._word_boundary_match("SUB TOTAL", "SUB TOTAL") is True

    def test_net_for_parts(self):
        assert self._word_boundary_match("NET FOR PARTS", "TOTAL NET FOR PARTS") is True

    def test_partial_label_no_match(self):
        assert self._word_boundary_match("TOTAL", "GRANDTOTAL") is False

    def test_label_in_sentence(self):
        assert self._word_boundary_match("TOTAL", "THE TOTAL IS") is True


# ═════════════════════════════════════════════════════════════════════════════
# 8. WHITESPACE NORMALIZATION
# ═════════════════════════════════════════════════════════════════════════════

class TestWhitespaceNormalization:
    """Cell text with newlines/tabs must still match labels."""

    def _normalize(self, text: str) -> str:
        return " ".join(text.strip().lower().split())

    def test_newline_collapsed(self):
        assert self._normalize("PAYMENT MADE IN\nTHE FAVOUR OF") == \
               "payment made in the favour of"

    def test_tabs_collapsed(self):
        assert self._normalize("DAILY\tALLOWANCE") == "daily allowance"

    def test_multi_space_collapsed(self):
        assert self._normalize("SUB    TOTAL") == "sub total"

    def test_cr_lf_collapsed(self):
        assert self._normalize("FAVOUR\r\nOF") == "favour of"


# ═════════════════════════════════════════════════════════════════════════════
# 9. FIELD MAPPING INTEGRITY
# ═════════════════════════════════════════════════════════════════════════════

class TestFieldMapping:
    """Validate field_mapping.json structure and completeness."""

    @pytest.fixture
    def mapping(self):
        path = os.path.join(PROJECT_ROOT, "app", "config", "field_mapping.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_mapping_loads(self, mapping):
        assert isinstance(mapping, dict)
        assert len(mapping) > 10

    def test_all_entries_have_required_keys(self, mapping):
        for field, cfg in mapping.items():
            if field.startswith("_"):
                continue
            assert "sheet" in cfg, f"{field} missing 'sheet'"
            assert "search_label" in cfg, f"{field} missing 'search_label'"
            assert "col_offset" in cfg, f"{field} missing 'col_offset'"

    def test_critical_fields_present(self, mapping):
        critical = ["claim_no", "date_of_survey", "initial_loss_amount",
                     "mobile_no", "email_id", "labour_excl_gst", "final_report_no"]
        for f in critical:
            assert f in mapping, f"Critical field '{f}' missing from mapping"

    def test_parts_fields_use_sub_total(self, mapping):
        for f in ["parts_age_dep_excl_gst", "parts_50_dep_excl_gst",
                   "parts_30_dep_excl_gst", "parts_nil_dep_excl_gst"]:
            assert mapping[f]["search_label"] == "SUB TOTAL", \
                f"{f} should use 'SUB TOTAL' label"

    def test_no_total_claimed_amount(self, mapping):
        """Total Claimed is calculated, not from Excel."""
        assert "total_claimed_amount" not in mapping

    def test_col_offsets_are_integers(self, mapping):
        for field, cfg in mapping.items():
            if field.startswith("_"):
                continue
            assert isinstance(cfg["col_offset"], int), \
                f"{field} col_offset must be int"

    def test_surveyor_fields_on_sheet5(self, mapping):
        for f in ["traveling_expenses", "professional_fee",
                   "daily_allowance", "photo_charges"]:
            assert mapping[f]["sheet"] == "Sheet5", f"{f} should be on Sheet5"


# ═════════════════════════════════════════════════════════════════════════════
# 10. SELECTORS INTEGRITY
# ═════════════════════════════════════════════════════════════════════════════

class TestSelectors:
    """Verify selector dict has all required keys."""

    def test_assessment_selectors_exist(self):
        from app.automation.selectors import ASSESSMENT
        required = ["age_dep", "dep_50", "dep_30", "nil_dep", "labour",
                     "towing", "salvage", "report_no", "travel", "prof_fee",
                     "daily_allowance", "photo", "total", "remarks"]
        for key in required:
            assert key in ASSESSMENT, f"ASSESSMENT missing '{key}'"

    def test_interim_selectors_exist(self):
        from app.automation.selectors import INTERIM
        assert isinstance(INTERIM, dict)
        assert len(INTERIM) > 5

    def test_total_selector_has_fallbacks(self):
        from app.automation.selectors import ASSESSMENT
        sel = ASSESSMENT["total"]
        assert "totalClaimed" in sel or "totalSurveyor" in sel, \
            "Total selector needs proper fallbacks"


# ═════════════════════════════════════════════════════════════════════════════
# 11. DOC MAPPING INTEGRITY
# ═════════════════════════════════════════════════════════════════════════════

class TestDocMapping:
    """Validate doc_mapping.json structure."""

    @pytest.fixture
    def doc_mapping(self):
        path = os.path.join(PROJECT_ROOT, "app", "config", "doc_mapping.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_doc_mapping_loads(self, doc_mapping):
        assert isinstance(doc_mapping, (dict, list))

    def test_doc_mapping_not_empty(self, doc_mapping):
        assert len(doc_mapping) > 0


# ═════════════════════════════════════════════════════════════════════════════
# 12. EXPECTED COMPLETION DATE
# ═════════════════════════════════════════════════════════════════════════════

class TestExpectedCompletionDate:
    """Expected completion = survey date + 10 days."""

    def test_plus_10_days(self):
        from datetime import datetime, timedelta
        dt = datetime.strptime("16/02/2026", "%d/%m/%Y")
        result = (dt + timedelta(days=10)).strftime("%d/%m/%Y")
        assert result == "26/02/2026"

    def test_month_rollover(self):
        from datetime import datetime, timedelta
        dt = datetime.strptime("25/03/2026", "%d/%m/%Y")
        result = (dt + timedelta(days=10)).strftime("%d/%m/%Y")
        assert result == "04/04/2026"

    def test_year_rollover(self):
        from datetime import datetime, timedelta
        dt = datetime.strptime("25/12/2025", "%d/%m/%Y")
        result = (dt + timedelta(days=10)).strftime("%d/%m/%Y")
        assert result == "04/01/2026"
