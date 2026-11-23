"""Checks for the AI debug report (Logs tab switch) and password masking.

Step 1: report from App3's own logs. Step 2: browser errors and failed portal calls
(read-only listeners, never a dialog listener). Step 3: read-only page snapshots.
Step 4: size limit, merged snapshots and Export.

Run from the project folder:
    uv run pytest tests/test_ai_debug_report.py -v

All values below are synthetic. UI tests are skipped when PyQt6 is not installed,
browser tests are skipped when Playwright or its Chromium cannot start (set
APP3_TEST_CHROMIUM to a Chromium path to use another browser build).
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.automation import debug_recorder as dr  # noqa: E402
from app.automation.automation_logger import AutomationLogger  # noqa: E402

SECRET = "Synthetic-Secret-123"  # not a real credential
PORTALS = ("uiic", "oic", "newindia")


def _logger(tmp_path, portal_id, lines):
    log = AutomationLogger("TEST", lines.append, portal_id=portal_id)
    log.set_claim_context("TESTCLAIM001", portal_id, log_file_path=str(tmp_path / "TESTCLAIM001_run.json"))
    return log


def _all_files_text(folder):
    return "\n".join(p.read_text(encoding="utf-8") for p in Path(folder).iterdir() if p.is_file())


def _fake_app_function():
    """A function whose code file looks like it lives under app/ (no real source on disk)."""
    namespace = {}
    source = "def choose_body_type():\n    raise ValueError(\"Synthetic dropdown value 'Coupe' not found\")\n"
    exec(compile(source, "/synthetic/app/portals/oic/automation/fake_step.py", "exec"), namespace)
    return namespace["choose_body_type"]


def _log_problem(log, section, message):
    """Log an error from here, so the report's code snippet shows these lines, not a test's data."""
    log.error(section, message)


@pytest.mark.parametrize("portal_id", PORTALS)
def test_password_and_captcha_values_never_reach_logs(tmp_path, portal_id):
    lines = []
    log = _logger(tmp_path, portal_id, lines)
    log.field_filled("Password", SECRET)
    log.field_filled("Captcha", "AB12CD")
    log.field_selected("Vehicle Class", "LMV")
    log.field_filled("Registration Number", "XX00YY0000")
    log.field_failed("Password", f'Locator.fill: Timeout 5000ms exceeded. Call log: - fill("{SECRET}")')

    everything = "\n".join(lines) + "\n" + _all_files_text(tmp_path)
    assert SECRET not in everything
    assert "AB12CD" not in everything
    assert dr.MASK in everything
    # Normal claim values are untouched.
    assert "XX00YY0000" in everything
    assert "LMV" in everything


@pytest.mark.parametrize("portal_id", PORTALS)
def test_switch_off_creates_no_report(tmp_path, portal_id):
    lines = []
    log = _logger(tmp_path, portal_id, lines)
    log.warning("Synthetic warning")
    log.error("Synthetic step", "synthetic failure")
    log.record_step_result("Login", True, 1.0)
    log.write_run_summary("Completed", "All steps finished.")

    assert log._debug_recorder is None
    assert log.debug_report_path is None
    assert not list(tmp_path.glob("*" + dr.REPORT_SUFFIX))
    assert not any("AI debug report" in line for line in lines)


@pytest.mark.parametrize("portal_id", PORTALS)
def test_report_shows_real_error_code_place_and_hides_secrets(tmp_path, portal_id):
    lines, announced = [], []
    log = _logger(tmp_path, portal_id, lines)
    recorder = dr.AIDebugRecorder(portal_id, "TESTCLAIM001", log._json_log_file, on_report_path=announced.append)
    recorder.set_context(
        settings={
            "username": "synthetic-user",
            "password": SECRET,
            "portal_url": "https://portal.example.invalid/login?token=abc123",
            "field_wait_ms": 250,
        },
        claim=None,
    )
    log.attach_debug_recorder(recorder)

    log.field_filled("Password", SECRET)
    try:
        _fake_app_function()()
    except ValueError as exc:
        log.exception("Body Type dropdown", exc)
    log.record_step_result("Basic Details", False, 2.5, reason="Body Type could not be selected")
    log.write_run_summary("Failed", "Body Type could not be selected")

    report = Path(recorder.report_path)
    assert report.is_file()
    assert report.name == "TESTCLAIM001_run" + dr.REPORT_SUFFIX
    assert announced == [recorder.report_path]  # the UI is told once
    text = report.read_text(encoding="utf-8")

    assert "Status: **Failed**" in text
    assert "## 2. Problems in detail" in text
    # Where the error was really raised, and where it was logged (with code lines).
    assert "Error raised at: `app/portals/oic/automation/fake_step.py:2` in `choose_body_type`" in text
    assert "Logged at: `" in text and "test_ai_debug_report.py" in text
    assert "```python" in text and ">>>" in text
    # The real error text and the traceback.
    assert "ValueError" in text and "Coupe" in text
    assert "Python traceback" in text
    # Steps, settings and the run log tail are included.
    assert "Step 'Basic Details' FAILED" in text
    assert "field_wait_ms" in text
    assert "## 10. End of the readable run log" in text
    assert "## 3. Browser errors and failed portal calls" in text
    # Secrets are hidden everywhere in the report.
    assert SECRET not in text
    assert "synthetic-user" not in text
    assert "abc123" not in text
    # The summary line tells the user where the report is.
    assert any("AI debug report:" in line for line in lines)


def test_masking_and_redaction_helpers():
    assert dr.mask_sensitive_value("Login Password", "x") == dr.MASK
    assert dr.mask_sensitive_value("CAPTCHA", "x") == dr.MASK
    assert dr.mask_sensitive_value("Pin Code", "380001") == "380001"
    assert dr.mask_sensitive_value("Password", "") == ""

    clean = dr.redact_secrets(
        {
            "password": "p",
            "api_key": "k",
            "empty_token": "",
            "nested": {"Authorization": "Bearer abc"},
            "claim_type": "Motor",
            "_web_submission": {"token": "t"},
        }
    )
    assert clean["password"] == dr.MASK and clean["api_key"] == dr.MASK
    assert clean["empty_token"] == "(empty)"
    assert clean["nested"]["Authorization"] == dr.MASK
    assert clean["claim_type"] == "Motor"
    assert clean["_web_submission"] == "(internal value omitted)"

    assert dr.redact_text("Authorization: Bearer abc.def") == "Authorization: [REDACTED]"
    assert "s3cr3t" not in dr.redact_text("https://x.invalid/?password=s3cr3t&a=1")
    assert dr.scrub_typed_values('- fill("abc")') == f'- fill("{dr.MASK}")'


def test_code_place_falls_back_when_source_is_missing():
    try:
        _fake_app_function()()
    except ValueError as exc:
        where = dr.capture_code_context(exc)
    assert where["raised_at"]["file"] == "app/portals/oic/automation/fake_step.py"
    assert where["raised_at"]["line"] == 2
    assert where["raised_at"]["snippet"] == ""  # like a packaged EXE: no source on disk
    assert where["logged_at"]["snippet"]  # this test file is on disk


def test_report_problems_never_break_the_run(tmp_path):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    recorder = dr.AIDebugRecorder("oic", "TESTCLAIM001", str(blocker / "sub" / "run.json"))
    recorder.snapshot_fn = lambda: 1 / 0  # a broken snapshot must not raise either
    recorder.note_log("ERROR", "x", "Login", "synthetic", {"raw_error": "boom"})
    recorder.note_step("Login", False, 1.0, "boom")
    recorder.finalize("Failed", "boom")
    assert not Path(recorder.report_path).exists()


def test_engine_defaults_ai_debug_report_on():
    pytest.importorskip("playwright.async_api")
    from app.automation.engine import AutomationEngine

    assert AutomationEngine(portal_id="uiic")._debug_mode is True
    assert AutomationEngine(portal_id="oic", debug_mode=False)._debug_mode is False


def test_logs_panel_switch_starts_on_every_portal():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])  # noqa: F841
    from app.ui.components.workspace_page import StructuredLogsPanel

    panel = StructuredLogsPanel()
    toggled = []
    panel.debug_mode_toggled.connect(toggled.append)
    for portal_id in PORTALS:
        panel.set_portal(portal_id)
        assert panel.debug_mode_check.isChecked()
        assert not panel.debug_mode_check.isHidden()
    assert not panel.btn_copy_ai_debug.isEnabled()

    panel.debug_mode_check.setChecked(False)
    assert toggled == [False]
    panel.set_ai_debug_report("C:/synthetic/TESTCLAIM001_run_ai_debug.md")
    assert panel.btn_copy_ai_debug.isEnabled()
    panel.set_debug_switch_locked(True)
    assert not panel.debug_mode_check.isEnabled()
    panel.set_debug_switch_locked(False)
    assert panel.debug_mode_check.isEnabled()


# ── Step 2: browser errors and failed portal calls ───────────────────────────

class _FakeEmitter:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def remove_listener(self, event, handler):
        self.handlers.get(event, []).remove(handler)

    def emit(self, event, *args):
        for handler in list(self.handlers.get(event, [])):
            handler(*args)


class _FakeLocator:
    def __init__(self, page, count=1):
        self.page = page
        self._count = count

    async def count(self):
        return self._count

    @property
    def first(self):
        return self

    async def wait_for(self, **_kwargs):
        raise TimeoutError("Synthetic: field not found")

    async def evaluate(self, script, *_args, **_kwargs):
        self.page.evaluations.append(script)
        if self.page.delay:
            await asyncio.sleep(self.page.delay)
        return dict(self.page.element) if script == dr._JS_ELEMENT_STATE else None


class _FakePage(_FakeEmitter):
    def __init__(self, url="https://portal.example.invalid/claim", page_state=None, element=None, delay=0.0, count=1):
        super().__init__()
        self.url = url
        self.page_state = page_state or {"url": url, "title": "Synthetic Claim", "ready": "complete"}
        self.element = element or {}
        self.delay = delay
        self.count = count
        self.evaluations = []
        self.screenshots = []

    def is_closed(self):
        return False

    def locator(self, _selector):
        return _FakeLocator(self, self.count)

    async def evaluate(self, script, *_args, **_kwargs):
        self.evaluations.append(script)
        if self.delay:
            await asyncio.sleep(self.delay)
        return dict(self.page_state) if script == dr._JS_PAGE_STATE else None

    async def screenshot(self, path, **_kwargs):
        Path(path).write_bytes(b"synthetic")
        self.screenshots.append(path)

    def snapshot_reads(self):
        return [s for s in self.evaluations if s in (dr._JS_PAGE_STATE, dr._JS_ELEMENT_STATE)]


class _FakeContext(_FakeEmitter):
    def __init__(self, pages):
        super().__init__()
        self.pages = list(pages)


class _FakeResponse:
    def __init__(self, status, url, body, content_type="application/json", resource_type="xhr", method="POST"):
        self.status = status
        self.url = url
        self.status_text = "Internal Server Error" if status >= 500 else "Not Found"
        self.headers = {"content-type": content_type}
        self.request = SimpleNamespace(method=method, resource_type=resource_type)
        self._body = body

    async def text(self):
        return self._body


def _debug_logger(tmp_path, portal_id="oic"):
    lines = []
    log = _logger(tmp_path, portal_id, lines)
    recorder = dr.AIDebugRecorder(portal_id, "TESTCLAIM001", log._json_log_file)
    recorder.set_context(settings={"password": SECRET}, claim=None)
    log.attach_debug_recorder(recorder)
    return log, recorder, lines


def test_browser_capture_only_listens_and_never_adds_a_dialog_listener(tmp_path):
    _log, recorder, _lines = _debug_logger(tmp_path)
    first = _FakePage()
    context = _FakeContext([first])
    recorder.attach_browser(context)
    recorder.attach_browser(context)  # a second call changes nothing

    expected = {"console", "pageerror", "requestfailed", "response", "framenavigated"}
    assert set(first.handlers) == expected
    assert all(len(h) == 1 for h in first.handlers.values())
    assert "dialog" not in first.handlers
    assert list(context.handlers) == ["page"]

    popup = _FakePage(url="https://portal.example.invalid/popup")
    context.emit("page", popup)  # a tab opened later is watched too
    assert set(popup.handlers) == expected and "dialog" not in popup.handlers

    recorder.stop_browser_capture()
    assert all(not h for h in first.handlers.values())
    assert all(not h for h in popup.handlers.values())
    assert not context.handlers["page"]


def test_browser_events_are_grouped_redacted_and_linked_to_the_problem(tmp_path):
    log, recorder, _lines = _debug_logger(tmp_path)
    page = _FakePage()

    async def run():
        recorder.attach_browser(_FakeContext([page]))
        page.emit("framenavigated", SimpleNamespace(url="https://portal.example.invalid/claim", parent_frame=None))
        page.emit("framenavigated", SimpleNamespace(url="https://ads.example.invalid/frame", parent_frame=object()))
        msg = SimpleNamespace(type="error", text="Synthetic save failed token=abc123",
                              location={"url": "https://portal.example.invalid/app.js", "lineNumber": 42})
        page.emit("console", msg)
        page.emit("console", msg)  # repeated: counted, not listed twice
        page.emit("console", SimpleNamespace(type="log", text="ordinary log line", location={}))
        page.emit("console", SimpleNamespace(type="warning", text="Synthetic deprecated call", location={}))
        page.emit("pageerror", SimpleNamespace(name="TypeError", message="Synthetic undefined value",
                                               stack="TypeError: x\n    at save (app.js:10:5)"))
        page.emit("requestfailed", SimpleNamespace(url="https://portal.example.invalid/logo.png", method="GET",
                                                   failure="net::ERR_ABORTED", resource_type="image"))
        page.emit("requestfailed", SimpleNamespace(url="https://portal.example.invalid/api/lookup", method="GET",
                                                   failure="net::ERR_CONNECTION_RESET", resource_type="xhr"))
        page.emit("response", _FakeResponse(200, "https://portal.example.invalid/api/ok", "{}"))
        page.emit("response", _FakeResponse(
            500, "https://portal.example.invalid/api/save?password=s3cr3t",
            '{"error": "Synthetic server failure", "password": "%s"}' % SECRET,
        ))
        await asyncio.sleep(0.05)  # let the reply body be read
        _log_problem(log, "Save Claim", "Synthetic save failed")
        log.write_run_summary("Failed", "Synthetic save failed")
        page.emit("console", SimpleNamespace(type="error", text="after " + "the run", location={}))  # ignored

    asyncio.run(run())
    text = Path(recorder.report_path).read_text(encoding="utf-8")

    assert "## 3. Browser errors and failed portal calls" in text
    assert "Console error" in text and "x2 |" in text
    assert "Console warning" in text
    assert "ordinary log line" not in text
    assert "Page script error" in text and "Synthetic undefined value" in text
    assert "ERR_CONNECTION_RESET" in text and "logo.png" not in text
    assert "HTTP 5xx reply" in text and "Synthetic server failure" in text
    assert "/api/ok" not in text
    assert "after the run" not in text
    assert "### Pages visited" in text and "ads.example.invalid" not in text
    # The problem lists what the browser did just before it.
    assert "Browser events in the 12 s before" in text
    assert "- Browser: 2 console error(s), 1 console warning(s), 1 page script error(s), 1 failed request(s)" in text
    for secret in (SECRET, "abc123", "s3cr3t"):
        assert secret not in text
    # Finished runs stop listening.
    assert all(not h for h in page.handlers.values())


def test_browser_handlers_swallow_their_own_errors(tmp_path):
    _log, recorder, _lines = _debug_logger(tmp_path)
    page = _FakePage()
    recorder.attach_browser(_FakeContext([page]))

    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("synthetic broken event")

    for event in ("console", "pageerror", "requestfailed", "response", "framenavigated"):
        page.emit(event, Broken())  # must not raise into Playwright's event loop
        page.emit(event, None)
    recorder.attach_browser(Broken())
    recorder.stop_browser_capture()
    recorder.stop_browser_capture()


# ── Step 3: read-only page snapshots ─────────────────────────────────────────

_FIELD_ELEMENT = {
    "tag": "select", "type": "select-one", "id": "bodyType", "name": "bodyType", "label": "Body Type",
    "classes": "form-control ng-invalid", "visible": True, "required": True, "value": "",
    "options": [{"text": "Select", "value": "", "selected": True}, {"text": "Sedan", "value": "S"}],
    "options_total": 2, "selected_text": "Select", "validation": "Please select an item in the list.",
    "angular": {"errors": ["required"], "view_value": "", "invalid": True},
    "html": '<select id="bodyType" data-app3-field-state="error"><option>Select</option></select>',
    "container_html": '<div class="form-group"><label>Body Type</label><select id="bodyType"></select>'
                      '<script>var x = 1;</script></div>',
}
_PAGE_STATE = {
    "url": "https://portal.example.invalid/claim?id=1", "title": "Synthetic Claim", "ready": "complete",
    "popups": ["Synthetic popup: please check the form"], "messages": ["Body Type is required"],
    "headings": ["Vehicle Details"], "invalid_total": 2,
    "invalid": [
        {"label": "Body Type", "tag": "select", "id": "bodyType", "name": "", "value": "", "message": "required"},
        {"label": "Password", "tag": "input", "id": "pwd", "name": "pwd", "value": SECRET, "message": ""},
    ],
}


def test_field_snapshot_shows_field_state_and_hides_passwords(tmp_path):
    log, recorder, lines = _debug_logger(tmp_path)
    page = _FakePage(page_state=_PAGE_STATE, element=_FIELD_ELEMENT)
    secret_page = _FakePage(element={
        "tag": "input", "type": "password", "id": "pwd", "label": "Password", "value": SECRET, "secret": True,
        "html": f'<input id="pwd" type="password" value="{SECRET}">',
    })

    async def run():
        first = await dr.debug_snapshot(log, page, selector="#bodyType", label="Body Type",
                                        reason="Not in dropdown list", extra={"Tried value": "Coupe"})
        second = await dr.debug_snapshot(log, secret_page, selector="#pwd", label="Password",
                                         reason="Login failed", extra={"Tried value": SECRET})
        return first, second

    first, second = asyncio.run(run())
    assert (first, second) == ("S1", "S2")
    _log_problem(log, "Body Type", "Not in dropdown list")
    recorder.finalize("Failed", "synthetic")
    text = Path(recorder.report_path).read_text(encoding="utf-8")

    assert "## 4. Page snapshots" in text
    assert "### S1" in text and "Body Type — Not in dropdown list" in text
    assert "Popups on screen" in text and "Body Type is required" in text
    assert "Fields the page marks invalid (2)" in text
    assert "`Sedan`" in text and "Options (2 of 2 shown)" in text
    assert "Angular model: errors required" in text
    assert "Tried value: Coupe" in text
    assert "data-app3-field-state" not in text and "var x = 1" not in text
    assert "Page snapshot: S1 (section 4)" in text  # the failed field points to its snapshot
    assert SECRET not in text
    assert any("page snapshot S1 saved" in line for line in lines)


def test_snapshot_gives_up_after_about_one_second(tmp_path):
    log, recorder, _lines = _debug_logger(tmp_path)
    slow = _FakePage(delay=5.0, element=_FIELD_ELEMENT)

    async def run():
        started = time.monotonic()
        snap_id = await dr.debug_snapshot(log, slow, selector="#bodyType", label="Body Type", reason="slow page")
        return snap_id, time.monotonic() - started

    snap_id, took = asyncio.run(run())
    assert snap_id == "S1"
    assert took < 2.0
    recorder.finalize("Failed", "synthetic")
    assert "only the parts read by then are shown" in Path(recorder.report_path).read_text(encoding="utf-8")


def test_snapshot_does_nothing_when_switch_is_off(tmp_path):
    lines = []
    log = _logger(tmp_path, "uiic", lines)
    page = _FakePage(element=_FIELD_ELEMENT)
    from app.automation.chrome_hud import emit_field_hud

    async def run():
        assert await dr.debug_snapshot(log, page, selector="#bodyType", label="Body Type") == ""
        await emit_field_hud(page, log, "Body Type", "failed", value="Coupe", selector="#bodyType")

    asyncio.run(run())
    assert page.snapshot_reads() == []


def test_snapshots_close_together_are_merged(tmp_path):
    log, recorder, _lines = _debug_logger(tmp_path)
    page = _FakePage(page_state=_PAGE_STATE)

    async def run():
        a = await dr.debug_snapshot(log, page, label="paused_Basic Details", reason="Body Type", screenshot="shot.png")
        b = await dr.debug_snapshot(log, page, label="Body Type", reason="Paused at Basic Details")
        return a, b

    assert asyncio.run(run()) == ("S1", "S1")
    assert page.snapshot_reads().count(dr._JS_PAGE_STATE) == 1  # the page was read once
    recorder.finalize("Paused", "synthetic")
    text = Path(recorder.report_path).read_text(encoding="utf-8")
    assert "Also used for: Body Type — Paused at Basic Details" in text
    assert "Screenshot: `shot.png`" in text


def test_failed_field_and_failure_screenshot_take_a_snapshot(tmp_path, monkeypatch):
    from app.automation import run_diagnostics
    from app.automation.chrome_hud import emit_field_hud

    monkeypatch.setattr(run_diagnostics, "automation_logs_dir", lambda *_a: str(tmp_path / "shots"))
    log, recorder, _lines = _debug_logger(tmp_path, "uiic")
    field_page = _FakePage(element=_FIELD_ELEMENT)
    step_page = _FakePage(url="https://portal.example.invalid/step")

    async def run():
        await emit_field_hud(field_page, log, "Body Type", "failed", value="Coupe", selector="#bodyType")
        shot = await run_diagnostics.capture_portal_screenshot(
            step_page, "uiic", "Claim Assessment", log, reason="Synthetic step failure", claim_no="TESTCLAIM001",
        )
        return shot

    shot = asyncio.run(run())
    assert shot and Path(shot).is_file()  # the screenshot still works as before
    assert dr._JS_ELEMENT_STATE in field_page.snapshot_reads()
    assert dr._JS_PAGE_STATE in step_page.snapshot_reads()
    recorder.finalize("Failed", "synthetic")
    text = Path(recorder.report_path).read_text(encoding="utf-8")
    assert "### S1" in text and "Field failed" in text
    assert "### S2" in text and f"Screenshot: `{Path(shot).name}`" in text


def test_new_india_failed_field_takes_a_snapshot(tmp_path):
    pytest.importorskip("playwright.async_api")
    from app.portals.newindia.automation import ui_utils

    log, recorder, lines = _debug_logger(tmp_path, "newindia")
    page = _FakePage(page_state=_PAGE_STATE)
    target = _FakeLocator(page, count=0)

    asyncio.run(ui_utils._check_entry(page, target, "Vehicle Make", "Maruti", "() => null", "dropdown", log, 0, "Excel"))
    assert dr._JS_PAGE_STATE in page.snapshot_reads()
    recorder.finalize("Failed", "synthetic")
    text = Path(recorder.report_path).read_text(encoding="utf-8")
    assert "Vehicle Make — Could not find this field on this page." in text
    assert "Target field: 0 element(s) matched" in text
    assert "Tried value: Maruti" in text and "Source: Excel" in text


# ── Real browser check (skipped when Chromium cannot start) ──────────────────

_TEST_PAGE = """<!doctype html><html><head><title>Synthetic Claim Form</title></head><body>
<h2>Vehicle Details</h2>
<div class="form-group has-error"><label for="make">Vehicle Make</label>
<select id="make" name="make" required><option value="">Select</option><option value="M1">Maruti</option>
<option value="H1">Hyundai</option></select><span class="help-block">Vehicle Make is required</span></div>
<div class="form-group"><label for="pwd">Password</label><input id="pwd" type="password" value="%s"></div>
<script>
console.error("Synthetic console error token=abc123");
fetch("/api/save", {method: "POST", body: "{}"});
setTimeout(() => { throw new Error("Synthetic page crash"); }, 10);
</script></body></html>""" % SECRET


def _serve_test_page():
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, status, body, ctype):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self._send(200, _TEST_PAGE, "text/html; charset=utf-8")
            else:
                self._send(404, "not here", "text/plain")

        def do_POST(self):
            self._send(500, '{"error": "Synthetic server failure", "password": "%s"}' % SECRET, "application/json")

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_real_chromium_capture_snapshot_and_alerts_still_auto_close(tmp_path):
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright

    log, recorder, _lines = _debug_logger(tmp_path, "uiic")
    server = _serve_test_page()
    url = f"http://127.0.0.1:{server.server_address[1]}/"

    async def run():
        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(
                    headless=True, executable_path=os.environ.get("APP3_TEST_CHROMIUM") or None,
                )
            except Exception as exc:
                pytest.skip(f"Chromium could not start here: {exc}")
            try:
                context = await browser.new_context()
                page = await context.new_page()
                recorder.attach_browser(context)
                await page.goto(url)
                await page.wait_for_timeout(800)
                # No dialog listener was added, so Playwright still closes alerts by itself.
                assert await asyncio.wait_for(page.evaluate("() => { alert('Synthetic alert'); return 'after'; }"), 5) == "after"
                assert await dr.debug_snapshot(log, page, selector="#make", label="Vehicle Make",
                                               reason="Not in dropdown list") == "S1"
                assert await dr.debug_snapshot(log, page, selector="#pwd", label="Password",
                                               reason="Synthetic check") == "S2"
                assert await page.locator("#pwd").input_value() == SECRET  # the page itself is unchanged
                _log_problem(log, "Save Claim", "Synthetic save failed")
                recorder.finalize("Failed", "synthetic")
            finally:
                await browser.close()

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
    text = Path(recorder.report_path).read_text(encoding="utf-8")
    assert "Console error" in text and "Synthetic console error" in text
    assert "HTTP 5xx reply" in text and "Synthetic server failure" in text
    assert "Page script error" in text and "Synthetic page crash" in text
    assert "`Maruti`" in text and "Vehicle Make is required" in text
    assert "### S2" in text and dr.MASK in text
    for secret in (SECRET, "abc123"):
        assert secret not in text


# ── Step 4: size limit and Export ────────────────────────────────────────────

def test_report_stays_under_the_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "_MAX_REPORT_BYTES", 60_000)
    recorder = dr.AIDebugRecorder("oic", "TESTCLAIM001", str(tmp_path / "run.json"))
    for number in range(200):
        recorder.note_log("ERROR", "x", "Synthetic", f"Synthetic problem {number} " + "x" * 300,
                          {"traceback": "Traceback line\n" * 300})
    recorder.finalize("Failed", "synthetic")
    data = Path(recorder.report_path).read_bytes()
    assert len(data) <= 60_000
    assert b"shortened form" in data or b"size limit" in data


def test_export_also_saves_the_ai_debug_report(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt6.QtWidgets", exc_type=ImportError)
    try:
        from app.ui.main_window import MainWindow
    except ImportError as exc:
        pytest.skip(f"main window needs extra packages: {exc}")

    report = tmp_path / "TESTCLAIM001_run_ai_debug.md"
    report.write_text("# AI Debug Report (synthetic)\n", encoding="utf-8")
    messages = []
    fake = SimpleNamespace(_latest_ai_debug_path=str(report), log=messages.append)
    MainWindow._export_ai_debug_copy(fake, str(tmp_path / "exported_log.txt"))
    copy = tmp_path / "exported_log_ai_debug.md"
    assert copy.read_text(encoding="utf-8") == "# AI Debug Report (synthetic)\n"
    assert any("AI debug report exported" in m for m in messages)

    fake_none = SimpleNamespace(_latest_ai_debug_path="", log=messages.append)
    MainWindow._export_ai_debug_copy(fake_none, str(tmp_path / "other.txt"))
    assert not (tmp_path / "other_ai_debug.md").exists()


def test_oic_pause_takes_one_snapshot_and_works_as_before(tmp_path, monkeypatch):
    pytest.importorskip("playwright.async_api")
    from app.automation import run_diagnostics
    from app.portals.oic.automation import recovery as oic_recovery

    monkeypatch.setattr(run_diagnostics, "automation_logs_dir", lambda *_a: str(tmp_path / "shots"))
    log, recorder, _lines = _debug_logger(tmp_path, "oic")
    page = _FakePage(page_state=_PAGE_STATE)
    page.bring_to_front = lambda: asyncio.sleep(0)
    prompts = []
    recovery = oic_recovery.OperatorRecovery(prompts.append, lambda: False)
    confirmed = {"done": False}

    async def ready():
        return confirmed["done"]

    async def run():
        async def operator():
            while not any(p is not None for p in prompts):
                await asyncio.sleep(0.05)
            confirmed["done"] = True
            recovery.respond(next(p for p in prompts if p is not None).id, "fixed")

        helper = asyncio.create_task(operator())
        result = await asyncio.wait_for(
            recovery.pause(page, log, "Select Body Type", "Synthetic: portal did not keep the value",
                           ready=ready, section="Basic Details"),
            timeout=20,
        )
        await helper
        return result

    assert asyncio.run(run()) is True  # the pause was answered exactly as it is without the report
    recorder.finalize("Paused", "synthetic")
    text = Path(recorder.report_path).read_text(encoding="utf-8")
    assert "Select Body Type — Paused at Basic Details: Synthetic: portal did not keep the value" in text
    assert text.count("### S") == 1  # the pause screenshot and the snapshot share one look at the page
    assert "Screenshot: `" in text


def test_new_india_step_failure_screenshot_also_takes_a_snapshot(tmp_path, monkeypatch):
    from app.automation import run_diagnostics
    from app.portals.newindia.automation.logging_utils import capture_newindia_screenshot

    monkeypatch.setattr(run_diagnostics, "automation_logs_dir", lambda *_a: str(tmp_path / "shots"))
    log, recorder, _lines = _debug_logger(tmp_path, "newindia")
    page = _FakePage(page_state=_PAGE_STATE)
    shot = asyncio.run(capture_newindia_screenshot(page, "Driver Details", log, reason="Synthetic step failure"))
    assert shot and Path(shot).is_file()
    assert dr._JS_PAGE_STATE in page.snapshot_reads()
    recorder.finalize("Failed", "synthetic")
    assert "Driver Details — Synthetic step failure" in Path(recorder.report_path).read_text(encoding="utf-8")
