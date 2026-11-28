"""Tests for New India Work Approval Time and Tax Paid Upto normalization and portal entry."""

import asyncio
from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from app.data.data_model import ClaimData
from app.data.excel_reader import extract_claim_data
from app.portals.newindia.automation import registration_cert_module, work_approval_module
from app.portals.newindia.automation.ui_utils import format_date_ddmmyyyy
from app.portals.newindia.field_values import normalize_work_approval_time


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4:30 PM", "16:30"),
        ("04:30 pm", "16:30"),
        ("12:05 AM", "00:05"),
        ("12:30 PM", "12:30"),
        ("11:30:00", "11:30"),
        ("4:30", "04:30"),
        ("16.30", "16:30"),
        ("1899-12-30 16:30:00", "16:30"),
        (time(16, 30), "16:30"),
        (datetime(2026, 11, 28, 16, 45), "16:45"),
        (0.6875, "16:30"),
        ("0.6875", "16:30"),
        ("", None),
        (None, None),
        ("NA", None),
    ],
)
def test_normalize_work_approval_time_variants(raw, expected):
    assert normalize_work_approval_time(raw) == expected


@pytest.mark.parametrize(
    ("raw_date", "expected"),
    [
        ("2025-03-31 00:00:00", "31/03/2025"),
        ("2025-03-31", "31/03/2025"),
        ("31-03-2025", "31/03/2025"),
        ("31.03.2025", "31/03/2025"),
        ("2025.03.31", "31/03/2025"),
        ("31/03/2025", "31/03/2025"),
        ("31-Mar-2025", "31/03/2025"),
    ],
)
def test_format_date_ddmmyyyy_supports_tax_paid_upto_formats(raw_date, expected):
    assert format_date_ddmmyyyy(raw_date) == expected


def test_excel_extraction_normalizes_work_approval_time_and_tax_paid_upto(tmp_path):
    wb_path = tmp_path / "claim.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Survey report"
    ws.append(["Work Approval Time", "4:30 PM"])
    ws.append(["Tax Paid Upto", datetime(2025, 3, 31, 0, 0, 0)])
    wb.save(wb_path)
    wb.close()

    claim = extract_claim_data(str(wb_path), portal_id="newindia")
    assert claim.work_approval_time == "16:30"
    assert claim.tax_paid_upto == "31/03/2025"


def test_excel_extraction_handles_fractional_time_and_string_timestamp_tax_date(tmp_path):
    wb_path = tmp_path / "claim_alt.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Survey report"
    ws.append(["Approval Time", 0.6875])
    ws.append(["Tax Paid Up to", "2025-03-31 00:00:00"])
    wb.save(wb_path)
    wb.close()

    claim = extract_claim_data(str(wb_path), portal_id="newindia")
    assert claim.work_approval_time == "16:30"
    assert claim.tax_paid_upto == "31/03/2025"


def test_calculate_derived_fields_normalizes_pdf_work_approval_time():
    claim = ClaimData(portal_id="newindia", work_approval_time="4:30 PM")
    claim.calculate_derived_fields()
    assert claim.work_approval_time == "16:30"


def test_work_approval_module_enters_24h_hhmm_for_pm_time(monkeypatch):
    filled = []

    async def fake_fill(page, selector, value, label, log, delay_ms, **kwargs):
        filled.append((label, value))

    monkeypatch.setattr(work_approval_module, "open_additional_section", AsyncMock(return_value=True))
    monkeypatch.setattr(work_approval_module, "fill_ready_cheque_details", AsyncMock(return_value=True))
    monkeypatch.setattr(work_approval_module, "select_dropdown_with_delay", AsyncMock())
    monkeypatch.setattr(work_approval_module, "_find_final_invoice_document", lambda data: "")
    monkeypatch.setattr(work_approval_module, "fill_input_with_delay", fake_fill)
    monkeypatch.setattr(work_approval_module, "check_checkbox_with_delay", AsyncMock())
    monkeypatch.setattr(work_approval_module, "load_automation_defaults", lambda **kwargs: {})

    page = MagicMock()
    page.locator.return_value = MagicMock()
    data = ClaimData(portal_id="newindia", work_approval_time="4:30 PM")

    asyncio.run(work_approval_module._fill_work_approval_section(page, data, MagicMock(), lambda: False, 0))
    assert ("Work Approval Time", "16:30") in filled


def test_registration_cert_module_formats_tax_paid_upto_as_ddmmyyyy(monkeypatch):
    filled = []

    async def fake_fill(page, selector, value, label, log, delay_ms, **kwargs):
        filled.append((label, value))

    monkeypatch.setattr(registration_cert_module, "open_additional_section", AsyncMock(return_value=True))
    monkeypatch.setattr(registration_cert_module, "resolve_newindia_channel", lambda page, data: "non_tie_up")
    monkeypatch.setattr(registration_cert_module, "_fill_type_of_body_if_visible", AsyncMock())
    monkeypatch.setattr(registration_cert_module, "_fill_type_of_vehicle", AsyncMock())
    monkeypatch.setattr(registration_cert_module, "fill_input_with_delay", fake_fill)
    monkeypatch.setattr(registration_cert_module, "check_checkbox_with_delay", AsyncMock())
    monkeypatch.setattr(registration_cert_module, "_select_with_fallback", AsyncMock())
    monkeypatch.setattr(registration_cert_module, "select_dropdown_with_delay", AsyncMock())
    monkeypatch.setattr(registration_cert_module, "load_automation_defaults", lambda **kwargs: {})

    locator_mock = MagicMock()
    locator_mock.count = AsyncMock(return_value=0)
    page = MagicMock()
    page.locator.return_value = locator_mock
    data = ClaimData(
        portal_id="newindia",
        tax_paid_upto="2025-03-31 00:00:00",
        pre_accident_condition="always good",
    )

    asyncio.run(registration_cert_module._fill_registration_cert_inner(page, data, MagicMock(), lambda: False, 0))
    assert ("Tax Paid Upto", "31/03/2025") in filled
