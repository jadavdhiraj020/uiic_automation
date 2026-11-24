"""New India: skip the review card when documents are already on the portal, and type the
Depreciation % on Maruti rows the portal already holds.

Run from the project folder:
    uv run pytest tests/test_newindia_already_applied_and_existing_depreciation.py -v

All values are synthetic. The depreciation tests open a local page in headless Chromium and
never contact New India.
"""

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.portals.newindia.automation import document_upload_module as upload  # noqa: E402
from app.portals.newindia.automation.maruti_rows import MarutiItem, fill_existing_depreciation  # noqa: E402

FILES = (
    "dl merged.pdf",
    "Rc registration certificate merged.pdf",
    "Motor_Claim_Form.pdf",
    "claim_others_documents_current.pdf",
)
ALERT = (
    "dl merged.pdf,Rc registration certificate merged.pdf,Motor_Claim_Form.pdf,"
    "claim_others_documents_current.pdf is already applied for this claim"
)


# ── "already applied" alert ──────────────────────────────────────────────────

def test_alert_naming_every_file_counts_as_already_applied():
    assert upload.alert_says_already_applied(ALERT, FILES)


def test_alert_match_ignores_case_and_extra_spaces():
    assert upload.alert_says_already_applied("  DL   MERGED.PDF is Already  Applied ", ("dl merged.pdf",))


def test_alert_missing_one_file_is_not_enough():
    assert not upload.alert_says_already_applied(ALERT, FILES + ("Invoice.pdf",))


def test_other_alerts_do_not_count():
    assert not upload.alert_says_already_applied("Duplicate document name: dl merged.pdf", ("dl merged.pdf",))
    assert not upload.alert_says_already_applied("dl merged.pdf uploaded successfully", ("dl merged.pdf",))
    assert not upload.alert_says_already_applied("", FILES)
    assert not upload.alert_says_already_applied(ALERT, ())


def test_file_name_is_not_found_inside_a_longer_name():
    assert not upload.alert_says_already_applied("data.pdf is already applied for this claim", ("a.pdf",))
    assert not upload.alert_says_already_applied("my-a.pdf is already applied for this claim", ("a.pdf",))


def test_all_files_listed_needs_every_name():
    listed = {upload._file_key(name) for name in FILES}
    assert upload.all_files_listed(FILES, listed)
    assert upload.all_files_listed((" DL  Merged.pdf ",), listed)
    assert not upload.all_files_listed(FILES + ("Invoice.pdf",), listed)
    assert not upload.all_files_listed((), listed)


def _run_outcome(monkeypatch, alert_body, listed_files):
    """Run the upload-outcome wait with a fake portal that shows one alert."""

    async def fake_popup(page, log, **kwargs):
        kwargs["detail_out"].update({"body": alert_body, "tag": "other"})
        return "other"

    async def no_banner(page, previous):
        return "", ""

    async def no_rows(page, indices):
        return 0, 0

    async def fake_listed(page):
        return {upload._file_key(name) for name in listed_files}

    monkeypatch.setattr(upload, "dismiss_portal_popup", fake_popup)
    monkeypatch.setattr(upload, "_new_inline_upload_text", no_banner)
    monkeypatch.setattr(upload, "_count_mandatory_upload_statuses", no_rows)
    monkeypatch.setattr(upload, "_uploaded_document_names", fake_listed)
    logs = []
    result = asyncio.run(upload._wait_for_mandatory_upload_outcome(
        None, (1, 2, 3, 4), logs.append, lambda: False, None, expected_files=FILES,
    ))
    return result, logs


def test_already_applied_alert_with_files_listed_continues_without_a_card(monkeypatch):
    (ok, reason), logs = _run_outcome(monkeypatch, ALERT, FILES)
    assert ok is True and reason == ""
    assert any("already holds" in line for line in logs)


def test_already_applied_alert_without_the_list_still_pauses(monkeypatch):
    (ok, reason), _ = _run_outcome(monkeypatch, ALERT, FILES[:3])
    assert ok is False
    assert "0/4 succeeded" in reason


def test_alert_naming_only_some_files_still_pauses(monkeypatch):
    partial = "dl merged.pdf,Motor_Claim_Form.pdf is already applied for this claim"
    (ok, reason), _ = _run_outcome(monkeypatch, partial, FILES)
    assert ok is False
    assert "0/4 succeeded" in reason


def test_other_alert_still_pauses_even_when_files_are_listed(monkeypatch):
    (ok, reason), _ = _run_outcome(monkeypatch, "Maximum file size is 1536 KB", FILES)
    assert ok is False
    assert "portal alert" in reason.lower()


# ── Depreciation on rows the portal already holds ────────────────────────────

ROW_PAGE = """
<table id="example"><tbody>
{rows}
</tbody></table>
"""


def _row(item, desc, dep="0", mrp="1000", amount="900", disabled=False):
    flag = " disabled" if disabled else ""
    return (
        f'<tr><td>1</td><td>{item}</td><td></td><td>{desc}</td><td>{mrp}</td>'
        f'<td><input id="deprePercent" maxlength="5" value="{dep}"{flag}></td>'
        f'<td>1</td><td></td><td></td><td>Replace</td><td>Replace</td><td>{amount}</td>'
        f'<td>8708</td><td>28</td><td></td></tr>'
    )


async def _enter(item, html_row):
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as exc:  # Chromium not installed on this PC
            pytest.skip(f"Chromium is not available: {exc}")
        try:
            page = await browser.new_page()
            await page.set_content(ROW_PAGE.format(rows=html_row))
            row = page.locator("tr").first
            entered = await fill_existing_depreciation(row, item, lambda: False)
            shown = await row.locator("input#deprePercent").input_value()
            cells = await row.evaluate("r => [...r.cells].map(c => c.textContent.trim())")
            return entered, shown, cells
        finally:
            await browser.close()


@pytest.mark.parametrize(
    "kind, pct, expected",
    [("Metal", "40", "40"), ("Painting", "12.5", "12.5"), ("Plastic", "50", "50")],
)
def test_metal_plastic_painting_rows_get_their_percentage(kind, pct, expected):
    item = MarutiItem(kind, "Bonnet", Decimal("900"), "8708", mrp=Decimal("1000"), depreciation=Decimal(pct))
    entered, shown, cells = asyncio.run(_enter(item, _row(kind, "Bonnet")))
    assert entered is True
    assert shown == expected
    # Nothing else on the row changes.
    assert cells[4] == "1000" and cells[11] == "900" and cells[3] == "Bonnet"


def test_a_value_already_on_the_row_is_left_alone():
    item = MarutiItem("Metal", "Bonnet", Decimal("900"), "8708", depreciation=Decimal("40"))
    entered, shown, _ = asyncio.run(_enter(item, _row("Metal", "Bonnet", dep="40")))
    assert entered is False and shown == "40"


def test_locked_box_is_not_touched():
    item = MarutiItem("Metal", "Bonnet", Decimal("900"), "8708", depreciation=Decimal("40"))
    entered, shown, _ = asyncio.run(_enter(item, _row("Metal", "Bonnet", disabled=True)))
    assert entered is False and shown == "0"


@pytest.mark.parametrize("kind", ["Labour", "Glass", "Spare", "Denting"])
def test_other_kinds_are_never_touched(kind):
    item = MarutiItem(kind, "Part", Decimal("900"), "8708", depreciation=Decimal("40"))
    entered, shown, _ = asyncio.run(_enter(item, _row(kind, "Part")))
    assert entered is False and shown == "0"


def test_zero_rule_value_clears_a_wrong_percentage_on_a_metal_row():
    item = MarutiItem("Metal", "Bonnet", Decimal("900"), "8708", depreciation=Decimal("0"))
    entered, shown, _ = asyncio.run(_enter(item, _row("Metal", "Bonnet", dep="25")))
    assert entered is True and shown == "0"
