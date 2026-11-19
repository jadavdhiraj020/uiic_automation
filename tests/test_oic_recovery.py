import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from app.automation.automation_logger import AutomationLogger
from app.automation.engine import AutomationEngine
from app.portals.oic.automation import assessment_of_loss_module, document_upload_module, ui_utils
from app.portals.oic.automation.invoice_upload import invoice_import_is_ready
from app.portals.oic.automation.popup_service import dismiss_portal_popup
from app.portals.oic.automation.recovery import (
    OperatorRecovery, RecoveryPrompt, action_problem, current_recovery, form_step_is_open,
    run_field, wait_until_ready,
)
from app.portals.oic.automation.validation import portal_validation_summary


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is unavailable")
        browser = await playwright.chromium.launch(headless=True)
        try:
            tab = await browser.new_page()
            await tab.route("http://oic.test/**", lambda route: route.fulfill(body="<html><body></body></html>"))
            await tab.goto("http://oic.test/assessment")
            yield tab
        finally:
            await browser.close()


class RecoveryRun:
    def __init__(self):
        self.prompts = asyncio.Queue()
        self.stopped = False
        self.recovery = OperatorRecovery(self.prompts.put_nowait, lambda: self.stopped)
        self.log_lines = []
        self.log = AutomationLogger("Test OIC step", self.log_lines.append, portal_id="oic")

    async def next_prompt(self):
        return await asyncio.wait_for(self.prompts.get(), timeout=8)


@pytest.mark.asyncio
async def test_field_resume_keeps_completed_work_and_rejects_the_next_step(page):
    await page.set_content("""
        <span aria-current="step">Basic Details</span>
        <div id="first">
            <input id="regNumber"><input id="manual"><input id="remaining">
            <input readonly id="claimNumber" value="EXPECTED0001">
        </div>
        <div id="second" hidden><input id="placeOfSurvey"></div>
    """)
    run = RecoveryRun()
    run.recovery.claim_number = "EXPECTED0001"
    await run.recovery.bind_form(page, "basic")
    completed = []

    async def put(selector, value):
        await page.locator(selector).fill(value)
        completed.append(selector)

    async def fail():
        raise RuntimeError("Password=password-from-test; Authorization: bearer-token")

    async def fill():
        token = current_recovery.set(run.recovery)
        try:
            await run_field(page, run.log, "Registration", lambda: put("#regNumber", "complete"))
            await run_field(page, run.log, "Driver Name", fail)
            await run_field(page, run.log, "Driver Name", lambda: put("#manual", "overwrite"))
            await run_field(page, run.log, "Vehicle details field", lambda: put("#remaining", "done"))
        finally:
            current_recovery.reset(token)

    task = asyncio.create_task(fill())
    first = await run.next_prompt()
    assert first.action == "Driver Name"
    assert completed == ["#regNumber"]
    run.recovery.respond("stale-id", "fixed")
    await page.evaluate("""() => {
        document.querySelector('[aria-current]').textContent = 'Interim Report';
        document.querySelector('#first').hidden = true;
        document.querySelector('#second').hidden = false;
    }""")
    run.recovery.respond(first.id, "fixed")
    retry = await run.next_prompt()
    assert retry.id == first.id
    assert "original OIC step" in retry.reason
    assert completed == ["#regNumber"]
    await page.evaluate("""() => {
        document.querySelector('[aria-current]').textContent = 'Basic Details';
        document.querySelector('#first').hidden = false;
        document.querySelector('#second').hidden = true;
        document.querySelector('#claimNumber').value = 'DIFFERENT0002';
    }""")
    run.recovery.respond(first.id, "fixed")
    wrong_claim = await run.next_prompt()
    assert wrong_claim.id == first.id
    assert "different claim" in wrong_claim.reason
    await page.evaluate("document.querySelector('#claimNumber').value = 'EXPECTED0001'")
    await page.locator("#manual").fill("operator edit")
    run.recovery.respond(first.id, "fixed")
    await asyncio.wait_for(task, timeout=6)

    assert completed == ["#regNumber", "#remaining"]
    assert await page.locator("#manual").input_value() == "operator edit"
    assert await run.next_prompt() is None
    assert sum("OIC paused at" in line for line in run.log_lines) == 1
    assert sum("OIC resumed at" in line for line in run.log_lines) == 1
    assert "password-from-test" not in "\n".join(run.log_lines)


@pytest.mark.asyncio
async def test_navigation_resume_uses_the_destination_without_replaying_next(page, monkeypatch):
    await page.set_content("""
        <span aria-current="step">Basic Details</span>
        <input id="regNumber">
        <label for="missing">Driver Name</label><input id="missing" required>
        <button id="next" onclick="window.clicks = (window.clicks || 0) + 1">Next</button>
    """)
    run = RecoveryRun()
    await run.recovery.bind_form(page, "basic")
    engine = AutomationEngine("oic", run.log_lines.append)
    engine._oic_recovery = run.recovery

    async def quick_ready(ready, *, seconds, stopped=lambda: False):
        return await wait_until_ready(ready, seconds=min(seconds, 0.3), stopped=stopped)

    monkeypatch.setattr(ui_utils, "wait_until_ready", quick_ready)
    monkeypatch.setattr(ui_utils, "capture_error_screenshot", AsyncMock())

    async def advance():
        token = current_recovery.set(run.recovery)
        try:
            return await ui_utils.advance_form(page, run.log, "#next", "Next", "interim", lambda: False, "test")
        finally:
            current_recovery.reset(token)

    task = asyncio.create_task(engine._run_oic_phase(
        page, "Next", advance, lambda: form_step_is_open(page, "interim"),
        "Fix the form in Chrome and click Continue.", section="Basic Details",
        describe=lambda: portal_validation_summary(page, "Next"), form_transition=True,
    ))
    prompt = await run.next_prompt()
    assert prompt.action == "Next"
    assert "Driver Name" in prompt.reason
    assert not prompt.can_skip
    assert await page.evaluate("window.clicks") == 1
    await page.evaluate("""() => {
        document.querySelector('[aria-current]').textContent = 'Interim Report';
        document.querySelector('#regNumber').remove();
        document.body.insertAdjacentHTML('beforeend', '<input id="placeOfSurvey">');
    }""")
    run.recovery.respond(prompt.id, "fixed")
    assert await asyncio.wait_for(task, timeout=6)
    assert await page.evaluate("window.clicks") == 1


@pytest.mark.asyncio
async def test_later_page_cannot_complete_a_phase_interrupted_before_next(page):
    run = RecoveryRun()
    engine = AutomationEngine("oic", run.log_lines.append)
    engine._oic_recovery = run.recovery
    ready = AsyncMock(return_value=True)
    task = asyncio.create_task(engine._run_oic_phase(
        page, "Next", AsyncMock(return_value=False), ready, "Open next step.", form_transition=True,
    ))
    prompt = await run.next_prompt()
    assert prompt.stop_only
    assert "before App3 reached the next button" in prompt.reason
    ready.assert_not_awaited()
    run.stopped = True
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=4)
    assert not page.is_closed()


@pytest.mark.asyncio
async def test_reload_while_paused_requires_stop_and_keeps_the_tab_open(page):
    await page.set_content('<span aria-current="step">Basic Details</span><input id="regNumber">')
    run = RecoveryRun()
    await run.recovery.bind_form(page, "basic")
    task = asyncio.create_task(run.recovery.pause(page, run.log, "Vehicle Make", "The field did not save."))
    prompt = await run.next_prompt()
    await page.reload()
    run.recovery.respond(prompt.id, "fixed")
    retry = await run.next_prompt()
    assert retry.id == prompt.id
    assert retry.action == "Vehicle Make"
    assert retry.stop_only
    run.stopped = True
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=4)
    assert not page.is_closed()


@pytest.mark.asyncio
async def test_invoice_checkpoint_resumes_only_after_expected_items_are_present(page):
    await page.set_content("""
        <span aria-current="step">Assessment of Loss</span><input id="invoiceNumber">
        <div class="p-accordion-tab">
            <div class="p-accordion-header"><h6>Invoice Number <b>EXPECTED</b></h6></div>
            <div class="p-accordion-header"><h6>Item Sub Type <b>Wrong part</b></h6></div>
        </div>
    """)
    run = RecoveryRun()
    await run.recovery.bind_form(page, "loss")
    token = current_recovery.set(run.recovery)
    try:
        task = asyncio.create_task(action_problem(
            page, run.log, "Import invoice workbook", "Invoice rejected with token=secret-token",
            lambda: invoice_import_is_ready(page, "EXPECTED", ["Bonnet"]), "Finish this import in Chrome.",
        ))
    finally:
        current_recovery.reset(token)
    prompt = await run.next_prompt()
    assert not prompt.can_skip
    assert "secret-token" not in prompt.reason
    await page.locator(".p-accordion-header b").last.evaluate("el => el.textContent = 'Bonnet'")
    run.recovery.respond(prompt.id, "fixed")
    assert await asyncio.wait_for(task, timeout=6)


@pytest.mark.asyncio
async def test_manual_attachment_requires_success_from_the_failed_slot(page, monkeypatch):
    await page.set_content("""
        <span aria-current="step">Document Upload</span><textarea id="remarks"></textarea>
        <section><input type="file" id="fileInput0"><div id="receipt0"></div></section>
        <section><input type="file" id="fileInput1"><div>File Uploaded Successfully</div></section>
    """)
    run = RecoveryRun()
    await run.recovery.bind_form(page, "upload")
    attach = AsyncMock(return_value=False)
    monkeypatch.setattr(document_upload_module, "upload_file_via_input", attach)
    token = current_recovery.set(run.recovery)
    try:
        task = asyncio.create_task(document_upload_module._attach_document(
            page, file_input_selector="#fileInput0", file_path="synthetic.pdf",
            label="Workshop Repair Estimate", log=run.log,
        ))
    finally:
        current_recovery.reset(token)
    prompt = await run.next_prompt()
    assert not prompt.can_skip
    run.recovery.respond(prompt.id, "fixed")
    retry = await run.next_prompt()
    assert retry.id == prompt.id
    await page.locator("#receipt0").evaluate("el => el.textContent = 'File attached successfully for upload'")
    run.recovery.respond(prompt.id, "fixed")
    assert await asyncio.wait_for(task, timeout=6)
    attach.assert_awaited_once()


@pytest.mark.asyncio
async def test_working_field_and_attachment_run_without_pausing(page, tmp_path):
    await page.set_content("""
        <span aria-current="step">Document Upload</span><textarea id="remarks"></textarea>
        <section>
            <input type="file" id="fileInput0" onchange="window.attachments = (window.attachments || 0) + 1">
        </section>
    """)
    sample = tmp_path / "synthetic.pdf"
    sample.write_bytes(b"Local attachment test")
    run = RecoveryRun()
    await run.recovery.bind_form(page, "upload")
    token = current_recovery.set(run.recovery)
    try:
        await ui_utils.fill_input_with_delay(page, "#remarks", "Reviewed attachments", "Remarks", run.log, 0)
        assert await document_upload_module._attach_document(
            page, file_input_selector="#fileInput0", file_path=str(sample),
            label="Workshop Repair Estimate", log=run.log,
        )
    finally:
        current_recovery.reset(token)
    assert await page.locator("#remarks").input_value() == "Reviewed attachments"
    assert await page.evaluate("window.attachments") == 1
    assert run.prompts.empty()


@pytest.mark.asyncio
async def test_expense_row_is_added_once(page):
    await page.set_content("""
        <button aria-label="Add Expenses +" onclick="
            window.adds = (window.adds || 0) + 1;
            document.body.insertAdjacentHTML('beforeend',
                '<div class=p-accordion-tab><div class=p-accordion-header>Professional Fee</div></div>');">
            Add
        </button>
    """)
    run = RecoveryRun()
    await assessment_of_loss_module._ensure_expense_row(page, "Professional Fee", run.log)
    await assessment_of_loss_module._ensure_expense_row(page, "Professional Fee", run.log)
    assert await page.evaluate("window.adds") == 1


@pytest.mark.asyncio
async def test_document_upload_keeps_manual_final_submit(monkeypatch):
    module = document_upload_module
    for helper in ("dismiss_portal_popup", "_upload_section", "_upload_driving_license",
                   "_upload_photographs", "_upload_other_documents", "_fill_remarks"):
        monkeypatch.setattr(module, helper, AsyncMock(return_value=True))
    submit = AsyncMock()
    monkeypatch.setattr(module, "_click_submit", submit)
    monkeypatch.setattr(module, "load_automation_defaults", lambda **_: {"auto_submit_documents": False})
    claim = SimpleNamespace(assessment_files={}, claim_doc_files={}, upload_doc_files={})
    assert await module.fill_document_upload_section(
        object(), claim, log=RecoveryRun().log, stop_cb=lambda: False,
    )
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_popup_dismissal_never_clicks_manual_submit_or_its_confirmation(page):
    await page.set_content("""
        <button id="submit" onclick="window.submitted = true">Submit</button>
        <div class="p-dialog"><p>The attachment needs review.</p></div>
    """)
    run = RecoveryRun()
    assert not await dismiss_portal_popup(page, run.log, max_wait_s=0.5)
    assert not await page.evaluate("Boolean(window.submitted)")

    await page.locator(".p-dialog").evaluate("""el => {
        el.innerHTML = '<p>Are you sure you want to submit?</p><button onclick="window.submitted = true">Yes</button>';
    }""")
    assert not await dismiss_portal_popup(page, run.log, max_wait_s=0.5)
    assert not await page.evaluate("Boolean(window.submitted)")

    await page.locator(".p-dialog").evaluate("""el => {
        el.innerHTML = '<p>The file was attached.</p><button onclick="this.parentElement.remove()">OK</button>';
    }""")
    assert await dismiss_portal_popup(page, run.log, max_wait_s=0.5)
    assert not await page.evaluate("Boolean(window.submitted)")


def test_desktop_updates_the_same_popup_and_only_sends_one_response(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QWidget
    from app.ui.main_window import MainWindow

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    class Harness(QWidget):
        _show_oic_recovery = MainWindow._show_oic_recovery
        _raise_oic_recovery = MainWindow._raise_oic_recovery
        _dismiss_oic_recovery = MainWindow._dismiss_oic_recovery

    window = Harness()
    window._worker = SimpleNamespace(resume_oic=Mock())
    window._automation_stopping = window._close_requested = False
    window._review_oic_button = QWidget(window)
    window._set_status = Mock()
    window._stop_automation = Mock()
    prompt = RecoveryPrompt("prompt", "Basic Details", "Driver Name", "Check the field.", True)
    window._show_oic_recovery(prompt)
    dialog = window._oic_recovery_dialog
    try:
        dialog.fixed_button.click()
        dialog.fixed_button.click()
        app.processEvents()
        assert dialog.isVisible()
        window._worker.resume_oic.assert_called_once_with("prompt", "fixed")
        window._show_oic_recovery(replace(prompt, reason="Return to Basic Details."))
        assert window._oic_recovery_dialog is dialog
        assert dialog.fixed_button.isEnabled()
        assert "Return to Basic Details." in dialog.informativeText()
        window._show_oic_recovery(None)
        assert not dialog.isVisible()
    finally:
        window._dismiss_oic_recovery()
        window.close()


def test_recovery_log_keeps_browser_errors_and_credentials_private():
    run = RecoveryRun()
    run.log.field_failed("Login", "Locator.fill: Timeout 5000ms. Password = do-not-log")
    run.log.upload_failed("Invoice", "upload request Cookie=private-token; file size too large")
    text = "\n".join(run.log_lines)
    assert "did not respond in time" in text
    assert "File size too large" in text
    assert "do-not-log" not in text
    assert "private-token" not in text
