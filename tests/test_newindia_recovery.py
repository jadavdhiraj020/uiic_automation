import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.automation.automation_logger import AutomationLogger
from app.data.data_model import ClaimData
from app.portals.newindia.automation import claim_assessment_module
from app.portals.newindia.automation.recovery import NewIndiaRecovery, current_recovery
from app.portals.newindia.automation.survey_fee_bill_module import _fill_hsn_code_typeahead
from app.portals.newindia.automation.ui_utils import (
    check_checkbox_with_delay, click_radio_with_delay, fill_input_with_delay, select_dropdown_with_delay,
)


@pytest_asyncio.fixture
async def session():
    async with async_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is unavailable")
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.route("http://newindia.test/**", lambda request: request.fulfill(
                body="""<ul><li id="claim">Claim No. <span>TEST1001</span> /</li>
                    <li class="active" id="one">Quick Update</li>
                    <li id="two">Additional Details</li>
                    <li id="three">Claim Assessment</li>
                    <li id="four">Document Upload</li></ul><main></main>""",
                content_type="text/html",
            ))
            await page.goto("http://newindia.test/Surveyor.html#/WorklistSurvey")
            prompts = asyncio.Queue()
            logs = []
            log = AutomationLogger("Test", logs.append, portal_id="newindia")
            log._section = "Quick Update"
            stop = asyncio.Event()
            recovery = NewIndiaRecovery(prompts.put_nowait, stop.is_set)
            await recovery.bind_claim(page, "TEST1001")
            yield page, recovery, prompts, log, stop
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_kept_values_are_accepted_without_rewriting_them(session):
    page, recovery, prompts, log, _ = session
    await page.locator("main").evaluate("""el => el.innerHTML = `
        <input name="surveyTime" hidden value="10:00">
        <input name="surveyTime" value="11:32:00" aria-invalid="true"
          oninput="window.rewrote = true">
        <select id="type" onchange="window.rewrote = true"><option value="M" selected>Motor</option></select>
        <input type="radio" name="surveyDone" value="Y" checked onchange="window.rewrote = true">
        <input id="verified" type="checkbox" checked onchange="window.rewrote = true">
    `""")
    await page.evaluate("""window.angular = {element: () => ({controller: () => ({$error: {}})})}""")
    token = current_recovery.set(recovery)
    try:
        await fill_input_with_delay(page, 'input[name="surveyTime"]', "11:32", "Survey Time", log, 0)
        await select_dropdown_with_delay(page, "#type", "Motor", "Vehicle Type", log, 0)
        await click_radio_with_delay(page, "surveyDone", "Y", "Survey Done", log, 0)
        await check_checkbox_with_delay(page, "#verified", "Physically Verified", log, 0)
    finally:
        current_recovery.reset(token)
    assert not await page.evaluate("Boolean(window.rewrote)")
    assert prompts.empty()


@pytest.mark.asyncio
async def test_page_review_lists_failures_after_filling_other_fields(session):
    page, recovery, prompts, log, _ = session
    await page.locator("main").evaluate("""el => el.innerHTML = `
        <input id="first" oninput="window.firstEdits = (window.firstEdits || 0) + 1">
        <input id="blocked" required pattern="[A-Z]{2}" value="">
        <select id="type"><option value="">Select</option>
          <option value="P">Light Passenger</option><option value="G">Light Goods</option>
        </select>
        <label for="missing">Driver Licence Number</label><input id="missing" required>
        <div class="ng-hide"><input name="Not Applicable" required></div>
        <input name="Optional Note">
        <input id="last">
        <button id="next" onclick="window.nextClicks = (window.nextClicks || 0) + 1;
          document.querySelector('#one').classList.remove('active');
          document.querySelector('#two').classList.add('active');">Next</button>
    `""")

    async def fill_form():
        token = current_recovery.set(recovery)
        try:
            await fill_input_with_delay(page, "#first", "Garage", "Place of Survey", log, 0)
            await fill_input_with_delay(page, "#blocked", "bad", "Office Code", log, 0)
            await select_dropdown_with_delay(page, "#type", "Light", "Vehicle Type", log, 0)
            await fill_input_with_delay(page, "#last", "Review complete", "Remarks", log, 0)
            assert prompts.empty()
            return await recovery.advance_next(
                page, log, "#next", source="one", destination="two", title="Additional Details",
            )
        finally:
            current_recovery.reset(token)

    run = asyncio.create_task(fill_form())
    prompt = await asyncio.wait_for(prompts.get(), 8)
    assert prompt.section == "Quick Update"
    assert prompt.action == "Review fields before Next"
    assert not prompt.can_skip
    assert "Office Code" in prompt.reason
    assert "Vehicle Type" in prompt.reason
    assert "Driver Licence Number" in prompt.reason
    assert "Not Applicable" not in prompt.reason
    assert "Optional Note" not in prompt.reason
    assert prompt.reason.count("•") == 3
    assert await page.locator("#last").input_value() == "Review complete"
    assert await page.evaluate("window.nextClicks || 0") == 0
    await page.locator("#blocked").fill("AB")
    recovery.respond(prompt.id, "fixed")
    retry = await asyncio.wait_for(prompts.get(), 6)
    assert retry.id == prompt.id
    assert "Driver Licence Number" in retry.reason and "Office Code" not in retry.reason
    # Some portal variants let Next open the following tab even with blanks.
    await page.locator("#next").click()
    recovery.respond(prompt.id, "fixed")
    retry = await asyncio.wait_for(prompts.get(), 6)
    assert retry.id == prompt.id and "Return to Quick Update" in retry.reason
    assert "Driver Licence Number" in retry.reason
    await page.evaluate("""() => {
        document.querySelector('#two').classList.remove('active');
        document.querySelector('#one').classList.add('active');
    }""")
    await page.locator("#type").select_option("G")
    await page.locator("#missing").fill("AB1234")
    await page.locator("#next").click()
    recovery.respond(prompt.id, "fixed")
    assert await asyncio.wait_for(run, 7)
    assert await page.locator("#blocked").input_value() == "AB"
    assert await page.locator("#last").input_value() == "Review complete"
    assert await page.evaluate("window.firstEdits") == 1
    assert await page.evaluate("window.nextClicks") == 2
    assert not recovery.field_issues


@pytest.mark.asyncio
async def test_page_review_cannot_resume_on_a_different_claim_and_stop_keeps_chrome_open(session):
    page, recovery, prompts, log, stop = session
    await page.locator("main").evaluate("""el => { el.innerHTML = `
        <input id="blocked" name="Office Code" required>
        <button id="next" onclick="document.querySelector('#one').classList.remove('active');
          document.querySelector('#two').classList.add('active')">Next</button>`;
    }""")
    run = asyncio.create_task(recovery.advance_next(
        page, log, "#next", source="one", destination="two", title="Additional Details",
    ))
    prompt = await asyncio.wait_for(prompts.get(), 8)
    await page.locator("#claim span").evaluate("el => el.textContent = 'TEST1002'")
    await page.locator("#next").click()
    recovery.respond(prompt.id, "fixed")
    retry = await asyncio.wait_for(prompts.get(), 5)
    assert retry.id == prompt.id and "original claim" in retry.reason
    stop.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(run, 5)
    assert not page.is_closed()


@pytest.mark.asyncio
async def test_correct_value_that_settles_before_checkpoint_does_not_trigger_popup(session):
    page, recovery, prompts, log, _ = session
    await page.locator("main").evaluate("""el => { el.innerHTML = `
      <input id=office value=AB><button id=next onclick="
      document.querySelector('#one').classList.remove('active');
      document.querySelector('#two').classList.add('active')">Next</button>
    `; }""")
    await page.evaluate("""() => {
        window.model = {$viewValue: '', $error: {}};
        window.angular = {element: () => ({controller: () => window.model})};
    }""")
    token = current_recovery.set(recovery)
    try:
        await fill_input_with_delay(page, "#office", "AB", "Office Code", log, 0)
    finally:
        current_recovery.reset(token)
    assert list(recovery.field_issues) == [("Quick Update", "Office Code")]
    assert await page.locator("#office").input_value() == "AB"
    await page.evaluate("setTimeout(() => { window.model.$viewValue = 'AB'; }, 150)")
    assert await recovery.advance_next(
        page, log, "#next", source="one", destination="two", title="Additional Details",
    )
    assert prompts.empty()


@pytest.mark.asyncio
async def test_ambiguous_dropdown_keeps_field_for_page_review(session):
    page, recovery, prompts, log, _ = session
    await page.locator("main").evaluate("""el => el.innerHTML = `
        <select id="type"><option value="">Select</option>
          <option value="P">Light Passenger</option><option value="G">Light Goods</option>
        </select>
    `""")
    token = current_recovery.set(recovery)
    try:
        await select_dropdown_with_delay(page, "#type", "Light", "Vehicle Type", log, 0)
    finally:
        current_recovery.reset(token)
    assert prompts.empty()
    assert "More than one option" in recovery.field_issues["Quick Update", "Vehicle Type"].reason
    assert await page.locator("#type").input_value() == ""


@pytest.mark.asyncio
async def test_required_custom_radios_are_reported_once_under_the_field_name(session):
    page, recovery, _, _, _ = session
    await page.locator("main").evaluate("""el => el.innerHTML = `
        <input id="nilYes" type="radio" name="Nil Depreciation" required style="display:none">
        <label for="nilYes">Yes</label>
        <input id="nilNo" type="radio" name="Nil Depreciation" required style="display:none">
        <label for="nilNo">No</label>`""")
    assert await recovery._issues_on_page(page, "one") == [
        ("", "Nil Depreciation", "Required value is missing."),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_next_requires_the_actual_click_and_verified_destination(session, blocked):
    page, recovery, prompts, log, _ = session
    await page.locator("main").evaluate("""el => {
        el.innerHTML = `<button id="next">Next</button>`;
        window.showStep = id => {
            document.querySelectorAll('li.active').forEach(tab => tab.classList.remove('active'));
            document.querySelector(id).classList.add('active');
        };
        document.querySelector('#next').onclick = () => {
            window.nextClicks = (window.nextClicks || 0) + 1;
            window.showStep('#two');
        };
    }""")
    if blocked:
        await page.locator("#next").evaluate("el => { el.disabled = true; }")
    task = asyncio.create_task(recovery.advance_next(
        page, log, "button#next", source="one", destination="two", title="Additional Details",
    ))
    if blocked:
        prompt = await asyncio.wait_for(prompts.get(), 6)
        assert prompt.action == "Next" and not prompt.can_skip
        await page.evaluate("window.showStep('#two')")
        recovery.respond(prompt.id, "fixed")
        retry = await asyncio.wait_for(prompts.get(), 5)
        assert retry.id == prompt.id
        await page.evaluate("window.showStep('#one')")
        await page.locator("#next").evaluate("el => { el.disabled = false; }")
        await page.locator("#next").click()
        await page.locator("main").evaluate("""el => el.insertAdjacentHTML('beforeend',
            '<div id="saved" class="modal in">Saved</div>')""")
        recovery.respond(prompt.id, "fixed")
        retry = await asyncio.wait_for(prompts.get(), 5)
        assert retry.id == prompt.id
        await page.locator("#saved").evaluate("el => el.remove()")
        recovery.respond(prompt.id, "fixed")
    assert await asyncio.wait_for(task, 6)
    assert await page.evaluate("window.nextClicks") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [True, False])
async def test_hsn_requires_portal_selection_and_keeps_already_committed_code(session, committed):
    page, recovery, prompts, log, _ = session
    await page.locator("main").evaluate("""(el, committed) => {
        el.innerHTML = `<input id="hSNCode" value="8512">
            <ul class="dropdown-menu" typeahead-popup hidden>
              <li><a href="#">8512 - Motor equipment</a></li>
            </ul>`;
        window.model = {$valid: committed, $modelValue: committed ? '8512' : undefined};
        window.angular = {element: () => ({controller: () => window.model})};
        document.querySelector('#hSNCode').oninput = () => {
            window.edited = true;
            document.querySelector('ul[typeahead-popup]').hidden = false;
        };
        document.querySelector('ul[typeahead-popup] a').onclick = event => {
            event.preventDefault();
            window.clicked = true;
            window.model = {$valid: true, $modelValue: '8512'};
        };
    }""", committed)
    token = current_recovery.set(recovery)
    try:
        assert await _fill_hsn_code_typeahead(page, log, field_delay_ms=0)
    finally:
        current_recovery.reset(token)
    assert await page.evaluate("Boolean(window.edited)") is not committed
    assert await page.evaluate("Boolean(window.clicked)") is not committed
    assert prompts.empty()


@pytest.mark.asyncio
async def test_hsn_typed_text_requires_selection_before_fee_bill_save(session):
    page, recovery, prompts, log, _ = session
    await page.locator("main").evaluate("""el => {
        el.innerHTML = '<input id=hSNCode>';
        window.model = {$valid: false};
        window.angular = {element: () => ({controller: () => window.model})};
    }""")
    await page.evaluate("""() => {
        document.querySelector('#one').classList.remove('active');
        document.querySelector('#four').classList.add('active');
    }""")
    token = current_recovery.set(recovery)
    try:
        assert not await _fill_hsn_code_typeahead(page, log, field_delay_ms=0)
    finally:
        current_recovery.reset(token)
    assert prompts.empty()
    task = asyncio.create_task(recovery.review_before_save(page, log, source="four"))
    prompt = await asyncio.wait_for(prompts.get(), 8)
    assert prompt.action == "Review fields before saving" and not prompt.can_skip
    assert "HSN Code" in prompt.reason
    assert await page.locator("#hSNCode").input_value() == "8512"
    recovery.respond(prompt.id, "fixed")
    assert (await asyncio.wait_for(prompts.get(), 6)).id == prompt.id
    await page.evaluate("window.model = {$valid: true, $modelValue: '8512'}")
    recovery.respond(prompt.id, "fixed")
    assert await asyncio.wait_for(task, 6)


@pytest.mark.asyncio
@pytest.mark.parametrize("amount,expected_gst,has_report", [("89.70", "Y", True), ("0", "N", False)])
async def test_claim_assessment_fills_defaults_and_excel_values(
    session, tmp_path, monkeypatch, amount, expected_gst, has_report,
):
    page, recovery, prompts, log, stop = session
    monkeypatch.setattr(claim_assessment_module, "dismiss_portal_popup", AsyncMock())
    monkeypatch.setattr(claim_assessment_module, "load_automation_defaults", lambda **_: {
        "payment_invoice_in_company_name": "No",
        "invoice_in_company_name": "Yes",
        "additional_towing_charges": "0",
        "recommendations": "Approved",
        "reinspection_required": "No",
    })
    await page.locator("main").evaluate("""el => {
        document.querySelector('#one').classList.remove('active');
        document.querySelector('#three').classList.add('active');
        const choices = '<option value="">Select</option><option value="Y">Yes</option><option value="N">No</option>';
        el.innerHTML = `
            <select id="invoiceName" data-ng-model="claim.isPaymentInvoice">${choices}</select>
            <select id="workshopGST" data-ng-model="claim.isWorkshopGstRegistered">${choices}</select>
            <select name="Is there any primary estimate">${choices}</select>
            <select name="Is there any supplementary estimate">${choices}</select>
            <div class="panel">
                <div class="panel-heading"><a href="#" class="accordion-toggle"
                  onclick="document.querySelector('ng-form').hidden = false; return false;">Delivery Order Details</a></div>
                <ng-form name="deliveryOrderDocForm" hidden>
                    <input name="Delivery Order Date" required>
                    <input name="Delivery Order Time" required maxlength="5">
                </ng-form>
            </div>
            <input id="additionalTowingCharges" value="999">
            <select id="whetherReinspectionRequired">${choices}</select>
            <textarea id="recommendations" required></textarea>
            <button id="saveClaimAssesment" data-ng-click="surveyorWorklistSurvey.saveAssesment()"
              onclick="document.querySelector('#three').classList.remove('active');
                       document.querySelector('#four').classList.add('active')">Next</button>`;
    }""")
    if not has_report:
        await page.locator("#saveClaimAssesment").evaluate("""el => {
            el.id = "next";
            el.setAttribute("data-ng-click", "surveyorWorklistSurvey.docUploadCall()");
        }""")
    report = tmp_path / "Vehicle Re-inspection report.pdf"
    if has_report:
        report.touch()
    claim = ClaimData(
        portal_id="newindia", delivery_order_date="20/11/2026", delivery_order_time="14:35",
        workshop_gst_amount=amount, additional_towing_charges="999",
    )
    claim._scan_result = SimpleNamespace(source_reinspection_path=str(report) if has_report else None)

    token = current_recovery.set(recovery)
    try:
        assert await asyncio.wait_for(claim_assessment_module.fill_claim_assessment_details(
            page, claim, log, stop.is_set, field_delay_ms=0,
        ), timeout=14)
    finally:
        current_recovery.reset(token)

    assert await page.locator("#invoiceName").input_value() == "N"
    assert await page.locator("#workshopGST").input_value() == expected_gst
    assert await page.locator('[name="Delivery Order Date"]').input_value() == "20/11/2026"
    assert await page.locator('[name="Delivery Order Time"]').input_value() == "14:35"
    assert await page.locator("#additionalTowingCharges").input_value() == "0"
    assert await page.locator("#recommendations").input_value() == "Approved"
    assert await page.locator("#whetherReinspectionRequired").input_value() == ("Y" if has_report else "N")
    assert prompts.empty()


def test_newindia_page_review_popup_has_continue_and_stop(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QWidget

    from app.portals.oic.automation.recovery import RecoveryPrompt
    from app.ui.main_window import MainWindow

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    class Harness(QWidget):
        _show_oic_recovery = MainWindow._show_oic_recovery
        _raise_oic_recovery = MainWindow._raise_oic_recovery
        _dismiss_oic_recovery = MainWindow._dismiss_oic_recovery

    window = Harness()
    window._worker = SimpleNamespace(portal_id="newindia", resume_oic=Mock())
    window._automation_stopping = window._close_requested = False
    window._review_oic_button = QWidget(window)
    window._set_status = Mock()
    window._stop_automation = Mock()
    prompt = RecoveryPrompt(
        "test", "Additional Details", "Review fields before Next",
        "• Licence Type — Select a valid option.\n• Driver Name — Required value is missing.", False,
        "Fix both fields in Chrome and click Next.", confirmation_button="I fixed all fields — continue",
    )
    window._show_oic_recovery(prompt)
    dialog = window._oic_recovery_dialog
    try:
        assert dialog.windowTitle() == "New India automation paused"
        assert dialog.fixed_button.text() == "I fixed all fields — continue"
        assert dialog.skip_button.isHidden()
        assert "Driver Name" in dialog.informativeText()
        assert {button.text() for button in dialog.buttons() if not button.isHidden()} == {
            "I fixed all fields — continue", "Stop automation",
        }
        dialog.fixed_button.click()
        dialog.fixed_button.click()
        window._worker.resume_oic.assert_called_once_with("test", "fixed")
    finally:
        window._dismiss_oic_recovery()
        window.close()
        app.processEvents()
