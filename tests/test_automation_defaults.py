from types import SimpleNamespace

import pytest

from app.utils import load_automation_defaults, reset_automation_defaults, save_automation_defaults
from app.portals.oic.automation.claim_search_module import _resolve_claim_type
from app.portals.newindia.automation.survey_fee_bill_module import _fill_hsn_code_typeahead


def test_automation_defaults_load_save_reset(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    bundled = load_automation_defaults(portal_id="newindia")
    assert bundled["hsn_code"] == "8512"
    assert bundled["payment_method"] == "NEFT"
    assert bundled["photo_charges_default"] == "200"
    assert bundled["assessment_parts_hsn_code"] == "8512"
    assert bundled["assessment_labour_hsn_code"] == "8729"

    save_automation_defaults(
        {
            "hsn_code": "9988",
            "remarks_default": "Reviewed",
            "photo_charges_default": "250",
            "assessment_parts_hsn_code": "1111",
            "assessment_labour_hsn_code": "2222",
        },
        portal_id="newindia",
    )
    edited = load_automation_defaults(portal_id="newindia")
    assert edited["hsn_code"] == "9988"
    assert edited["remarks_default"] == "Reviewed"
    assert edited["payment_method"] == "NEFT"
    assert edited["photo_charges_default"] == "250"
    assert edited["assessment_parts_hsn_code"] == "1111"
    assert edited["assessment_labour_hsn_code"] == "2222"

    reset_automation_defaults(portal_id="newindia")
    reset = load_automation_defaults(portal_id="newindia")
    assert reset["hsn_code"] == "8512"
    assert reset["remarks_default"] == "Ok"
    assert reset["photo_charges_default"] == "200"
    assert reset["assessment_parts_hsn_code"] == "8512"
    assert reset["assessment_labour_hsn_code"] == "8729"


def test_oic_unknown_claim_type_uses_configured_default():
    claim = SimpleNamespace(payment_to="")
    assert _resolve_claim_type(claim, {"unknown_claim_type_default": "REIMBURSEMENT"}) == "REIMBURSEMENT"

    claim.payment_to = "INSURED"
    assert _resolve_claim_type(claim, {"unknown_claim_type_default": "CASHLESS"}) == "REIMBURSEMENT"


def test_newindia_photo_charges_uses_configured_hardcoded_default(monkeypatch, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app.data.excel_reader import extract_claim_data

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_automation_defaults({"photo_charges_default": "250"}, portal_id="newindia")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.cell(row=1, column=1, value="Photos Amount")
    sheet.cell(row=1, column=2, value="999")

    excel_path = tmp_path / "claim.xlsx"
    workbook.save(excel_path)

    claim = extract_claim_data(str(excel_path), portal_id="newindia")

    assert claim.photo_charges == "250"
    assert claim._excel_coords["photo_charges"] == "Hardcoded"


def test_newindia_reads_delivery_and_gst_fields_with_old_mapping_and_new_settings(monkeypatch, tmp_path):
    from datetime import date, time

    import openpyxl

    from app.data.excel_reader import extract_claim_data
    from app.utils import load_field_mapping, save_field_mapping

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_field_mapping({
        "whether_driver_without_license": {"search_labels": ["Driver without license"]},
        "additional_towing_charges": {"search_labels": ["Additional Towing Charges"]},
    }, portal_id="newindia")
    assert "whether_driver_without_license" not in load_field_mapping("newindia")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Delivery Order Date:", date(2026, 11, 20)])
    sheet.append(["Delivery Order Time", time(14, 35)])
    sheet.append(["Work Approval Time", "09:00"])
    sheet.append([18, "% ADD GST (9%CGST+9%SGST)", None, None, 89.70])
    sheet.append(["Driver without license", "Yes"])
    sheet.append(["Additional Towing Charges", 999])
    excel = tmp_path / "claim.xlsx"
    workbook.save(excel)
    workbook.close()

    claim = extract_claim_data(str(excel), portal_id="newindia")
    assert (claim.delivery_order_date, claim.delivery_order_time, claim.work_approval_time) == (
        "20/11/2026", "14:35", "09:00",
    )
    assert claim.workshop_gst_amount == "89.7"
    assert claim._excel_coords["workshop_gst_amount"].startswith("R4C5")
    assert not claim.whether_driver_without_license
    assert claim.additional_towing_charges == "0"
    assert claim.towing_additional_charges == "0"

    rows = {label: value for label, value, *_ in claim.all_fields_for_preview()}
    assert rows["Driver Without License?"] == "No"
    assert rows["Vehicle Details Match Policy?"] == "Yes"
    assert rows["Payment Invoice in NIA Name?"] == "Yes"
    assert rows["Is Invoice in Name of NIA?"] == "Yes"
    assert rows["Recommendations"] == "Approved"
    assert rows["Addl. Towing (₹)"] == "0"
    assert rows["Workshop GST Registered?"] == "Yes"

    save_automation_defaults({"invoice_in_company_name": "No", "additional_towing_charges": "500"},
                             portal_id="newindia")
    rows = {label: value for label, value, *_ in claim.all_fields_for_preview()}
    assert rows["Is Invoice in Name of NIA?"] == "No"
    assert rows["Payment Invoice in NIA Name?"] == "Yes"
    assert rows["Addl. Towing (₹)"] == "500"


@pytest.mark.parametrize("stored,expected", [
    (0.625, "15:00"), ("2.35 pm", "14:35"), ("00:00:00", "00:00"),
    ("25:10:00", None), ("18:70", None), ("2:35", "02:35"),
])
def test_newindia_delivery_order_excel_time(stored, expected):
    from app.data.excel_reader import _parse_delivery_order_time

    assert _parse_delivery_order_time(stored) == expected


def test_newindia_uses_scanned_reinspection_document_not_generated_pdf(monkeypatch, tmp_path):
    from PIL import Image

    from app.data.data_model import ClaimData
    from app.data.folder_scanner import scan_folder
    from app.portals.newindia.field_values import reinspection_document

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "settings"))
    folder = tmp_path / "claim"
    folder.mkdir()

    (folder / "reinspection_report.pdf").touch()
    Image.new("RGB", (72, 72)).save(folder / "Inspection Report.png")
    claim = ClaimData(portal_id="newindia")
    claim._scan_result = scan_folder(str(folder), portal_id="newindia")
    assert reinspection_document(claim) == ""

    Image.new("RGB", (72, 72)).save(folder / "Vehicle Re-Inspection Report.png")
    claim._scan_result = scan_folder(str(folder), portal_id="newindia")
    assert reinspection_document(claim) == "Vehicle Re-Inspection Report.png"


def test_newindia_settings_shows_defaults_and_excel_offsets(monkeypatch, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QComboBox

    from app.ui.components.settings_page import SettingsPage

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    page = SettingsPage()
    try:
        page.set_portal("newindia")
        table = page.defaults_table
        inputs = {table.item(i, 0).data(Qt.ItemDataRole.UserRole): table.cellWidget(i, 1)
                  for i in range(table.rowCount())}
        for key, default in {
            "driver_without_license": "No", "vehicle_details_match_policy": "Yes",
            "payment_invoice_in_company_name": "Yes", "invoice_in_company_name": "Yes",
        }.items():
            assert isinstance(inputs[key], QComboBox)
            assert [inputs[key].itemText(i) for i in range(inputs[key].count())] == ["Yes", "No"]
            assert inputs[key].currentText() == default
        assert inputs["additional_towing_charges"].text() == "0"
        assert inputs["recommendations"].text() == "Approved"
        assert "reinspection_required" not in inputs

        table = page.mapping_table
        offsets = {table.item(i, 0).text(): (table.cellWidget(i, 3).value(), table.cellWidget(i, 4).value())
                   for i in range(table.rowCount())}
        assert offsets["delivery_order_date"] == offsets["delivery_order_time"] == (0, 1)
        assert offsets["workshop_gst_amount"] == (0, 3)
    finally:
        page.close()
        app.processEvents()


def test_primary_assessment_generation_uses_defaults_and_audit(monkeypatch, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app.data.assessment_generator import generate_primary_assessment

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_automation_defaults(
        {"assessment_parts_hsn_code": "1111", "assessment_labour_hsn_code": "2222"},
        portal_id="newindia",
    )

    source_path = tmp_path / "claim.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Claim"
    sheet.append(["S.No", "Description", "Estimated", "Metal", "Plastic", "Glass"])
    sheet.append([1, "Front bumper", 1000, 800, None, None])
    sheet.append(["Sub Total", None, None, None, None, None])
    sheet.append(["S.No", "Description", "R/R", "Denting", "C/W"])
    sheet.append([1, "Repair labour", 100, 50, 25])
    sheet.append(["Total", None, None, None, None])
    workbook.save(source_path)

    output_path = generate_primary_assessment(str(source_path), str(tmp_path))

    assert output_path == str(tmp_path / "auto_primary_assessment.xlsx")
    assert (tmp_path / "auto_primary_assessment_audit.txt").exists()

    generated = openpyxl.load_workbook(output_path, data_only=True)
    output_sheet = generated.active
    assert output_sheet.cell(row=2, column=10).value == 1111
    assert output_sheet.cell(row=3, column=10).value == 2222
    generated.close()

    audit_text = (tmp_path / "auto_primary_assessment_audit.txt").read_text(encoding="utf-8")
    assert "Parts confidence:" in audit_text
    assert "Labour confidence:" in audit_text
    assert "Parts rows: 1" in audit_text
    assert "Labour rows: 1" in audit_text


def test_primary_assessment_generation_does_not_overwrite_existing_file(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app.data.assessment_generator import generate_primary_assessment

    existing = tmp_path / "auto_primary_assessment.xlsx"
    existing.write_text("keep me", encoding="utf-8")

    source_path = tmp_path / "claim.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["S.No", "Description", "Estimated", "Metal", "Plastic", "Glass"])
    sheet.append([1, "Front bumper", 1000, 800, None, None])
    sheet.append(["Sub Total", None, None, None, None, None])
    workbook.save(source_path)

    output_path = generate_primary_assessment(str(source_path), str(tmp_path))

    assert output_path == str(tmp_path / "auto_primary_assessment_1.xlsx")
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert (tmp_path / "auto_primary_assessment_1_audit.txt").exists()


def test_primary_assessment_low_confidence_header_is_skipped(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app.data.assessment_generator import generate_primary_assessment

    source_path = tmp_path / "claim.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["S.No", "Description", "Glass"])
    sheet.append([1, "Weak header part", 500])
    workbook.save(source_path)

    output_path = generate_primary_assessment(str(source_path), str(tmp_path))

    assert output_path is None
    audit_path = tmp_path / "primary_assessment_skipped_audit.txt"
    assert audit_path.exists()
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "Parts confidence:" in audit_text
    assert "Parts warning: Parts header confidence below minimum 80%" in audit_text
    assert "No parts or labour data found. Excel generation skipped." in audit_text


@pytest.mark.asyncio
async def test_newindia_hsn_typeahead_uses_configured_value():
    class FakeTypeahead:
        async def count(self):
            return 0

    class FakeLocator:
        def __init__(self):
            self.typed = ""

        @property
        def first(self):
            return self

        def filter(self, **_kwargs):
            return FakeTypeahead()

        async def is_visible(self):
            return True

        async def scroll_into_view_if_needed(self):
            pass

        async def click(self):
            pass

        async def fill(self, value):
            self.typed = value

        async def type(self, value, delay=0):
            self.typed += value

        async def press(self, _key):
            pass

        async def input_value(self):
            return self.typed

    class FakePage:
        def __init__(self):
            self.field = FakeLocator()

        def locator(self, _selector):
            return self.field

    page = FakePage()
    assert await _fill_hsn_code_typeahead(page, log=lambda _msg: None, field_delay_ms=0, hsn_code="9988")
    assert page.field.typed == "9988"
