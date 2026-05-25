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
    audit_path = tmp_path / "auto_primary_assessment_audit.txt"
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
