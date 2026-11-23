"""Checks for the AI debug report (Logs tab switch, step 1) and password masking.

Run from the project folder:
    uv run pytest tests/test_ai_debug_report.py -v

All values below are synthetic. The Logs-panel test is skipped when PyQt6 is not
installed and the engine test is skipped when Playwright is not installed.
"""

import os
import sys
from pathlib import Path

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
    assert "## 8. End of the readable run log" in text
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


def test_engine_keeps_report_off_unless_asked():
    pytest.importorskip("playwright.async_api")
    from app.automation.engine import AutomationEngine

    assert AutomationEngine(portal_id="uiic")._debug_mode is False
    assert AutomationEngine(portal_id="oic", debug_mode=True)._debug_mode is True


def test_logs_panel_switch_starts_off_on_every_portal():
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
        assert not panel.debug_mode_check.isChecked()
        assert not panel.debug_mode_check.isHidden()
    assert not panel.btn_copy_ai_debug.isEnabled()

    panel.debug_mode_check.setChecked(True)
    assert toggled == [True]
    panel.set_ai_debug_report("C:/synthetic/TESTCLAIM001_run_ai_debug.md")
    assert panel.btn_copy_ai_debug.isEnabled()
    panel.set_debug_switch_locked(True)
    assert not panel.debug_mode_check.isEnabled()
    panel.set_debug_switch_locked(False)
    assert panel.debug_mode_check.isEnabled()
