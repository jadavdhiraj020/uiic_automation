"""One dummy queued case, using the exact deployed function contract."""
import asyncio
import hashlib
import json
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PyQt6.QtWidgets import QLabel

from app.web_sync.client import APP_ID, ApiError, Client
from app.web_sync.downloads import download_case, flat_name, safe_canonical_name
from app.web_sync.storage import AutoPickupPreference, CaseState, CompletedCaseStore, CredentialStore, portal_for
from app.web_sync.submission import SubmissionMonitor, confirms_submission


JOB = {"case_id": "case_dummy_001", "case_ref": "JDB/2026-27/PORTAL/4895",
       "automation_dispatch_id": "dispatch-dummy-001",
       "automation_dispatched_at": "2026-09-12T09:00:00Z",
       "vehicle_no": "PB00XX0000", "insurer": "United India Insurance",
       "surveyor_profile_id": "profile_dummy_001", "drive_folder_id": "drive_folder_dummy_001",
       "drive_folder_link": "https://drive.google.com/drive/folders/drive_folder_dummy_001",
       "status": "queued_for_automation"}


class Response:
    def __init__(self, status=200, data=None, binary=None, headers=None):
        self.status_code, self.data, self.binary = status, data, binary
        self.headers = headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def close(self):
        pass
    def json(self):
        assert self.binary is None, "Raw binary must never be JSON-decoded"
        return self.data
    def iter_content(self, size):
        yield self.binary[:3]
        yield self.binary[3:]


class DummyServer:
    def __init__(self):
        self.calls = []
        self.logins = 0
        self.expire_once = True
        self.claimed = False
        self.reports = []
        self.queued_jobs = [dict(JOB)]
        self.files = [
            {"file_id": "excel", "name": "Corrected.xlsx", "path": "Corrected.xlsx", "is_latest_corrected_excel": True},
            {"file_id": "rc", "name": "RC.pdf", "path": "RC.pdf", "is_latest_corrected_excel": False},
            {"file_id": "rc2", "name": "RC.pdf", "path": "Individual/RC.pdf", "is_latest_corrected_excel": False},
        ]
        for entry in self.files:
            payload = b"\x00\xff\x01RAW\x00" + entry["file_id"].encode()
            entry["size_bytes"] = len(payload)
            entry["md5_checksum"] = hashlib.md5(payload).hexdigest()
    def post(self, url, **kwargs):
        operation = url.rsplit("/", 1)[-1]
        body = kwargs["json"]
        self.calls.append((operation, body, kwargs["headers"]))
        assert kwargs["headers"]["X-App-Id"] == APP_ID
        assert kwargs["allow_redirects"] is False
        if operation == "login":
            assert body == {"email": "dummy@example.invalid", "password": "operator-test-secret"}
            self.logins += 1
            return Response(data={"access_token": f"dummy-token-{self.logins}"})
        assert kwargs["headers"]["Authorization"] == f"Bearer dummy-token-{self.logins}"
        if self.expire_once:
            self.expire_once = False
            return Response(401)
        if operation == "getAutomationJobs":
            assert body == {"limit": 25}
            return Response(data={"jobs": [dict(job) for job in self.queued_jobs]})
        if operation == "claimAutomationCase":
            assert body == {
                "case_id": JOB["case_id"],
                "automation_dispatch_id": JOB["automation_dispatch_id"],
            }
            if self.claimed:
                return Response(409)
            self.claimed = True
            return Response(data={"claimed": True, "job": {**JOB, "status": "automation_in_progress"}})
        if operation == "getAutomationCaseZip":
            return Response(501, data={"error": "ZIP unavailable in legacy mock"})
        if operation == "getAutomationCaseFiles":
            if "file_id" not in body:
                return Response(data={
                    "case_id": body["case_id"],
                    "automation_dispatch_id": body["automation_dispatch_id"],
                    "latest_corrected_excel": self.files[0], "files": self.files,
                })
            return Response(binary=b"\x00\xff\x01RAW\x00" + body["file_id"].encode(), headers={"Content-Type": "application/octet-stream", "X-Case-File-Path": "Individual%2FRC.pdf"})
        if operation == "reportAutomationResult":
            assert body["status"] in ("success", "failed")
            assert set(body) <= {"case_id", "automation_dispatch_id", "status", "portal_message", "confirmation_no"}
            self.reports.append(body)
            return Response(data={"ok": True, **body, "status": "uploaded" if body["status"] == "success" else "ready_for_upload"})
        raise AssertionError(operation)


def client_server():
    server = DummyServer()
    return Client("dummy@example.invalid", "operator-test-secret", session=server), server


class ImmediateExecutor:
    """Runs staging inline so UI state assertions do not depend on thread timing."""
    def submit(self, function):
        future = Future()
        try:
            future.set_result(function())
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **_kwargs):
        pass


def test_dummy_case_contract_binary_flat_and_relogin(tmp_path):
    client, server = client_server()
    assert client.jobs() == [JOB]
    assert server.logins == 2
    client.claim(JOB["case_id"], JOB["automation_dispatch_id"])
    latest = download_case(client, JOB["case_id"], tmp_path, automation_dispatch_id=JOB["automation_dispatch_id"])
    manifest = json.loads((tmp_path / "web_sync_manifest.json").read_text())
    assert manifest["latest_excel"] == latest
    assert len({f["local_name"].lower() for f in manifest["files"]}) == 3
    for item in manifest["files"]:
        assert (tmp_path / item["local_name"]).read_bytes() == b"\x00\xff\x01RAW\x00" + item["file_id"].encode()
        assert item["remote_path"] == "Individual/RC.pdf"
    assert all(p.is_file() for p in tmp_path.iterdir())
    client.report({"case_id": JOB["case_id"], "automation_dispatch_id": JOB["automation_dispatch_id"], "status": "success", "portal_message": "Report submitted successfully"})
    assert server.reports[0]["status"] == "success"
    with pytest.raises(ApiError) as conflict:
        client.claim(JOB["case_id"], JOB["automation_dispatch_id"])
    assert conflict.value.status == 409


def test_401_retries_only_once():
    client, server = client_server()
    original = server.post
    def always_expired(url, **kwargs):
        return original(url, **kwargs) if url.endswith("login") else Response(401)
    server.post = always_expired
    with pytest.raises(ApiError):
        client.jobs()
    assert server.logins == 2


@pytest.mark.parametrize("message", ["DL verification pending", "Voucher pending", "Wrong amount", "Missing document", "Report submitted successfully but DL pending", "Document uploaded successfully", "Saved successfully", "Confirm report submitted successfully?", "Report not submitted successfully"])
def test_validation_and_intermediate_messages_are_not_success(message):
    assert not confirms_submission(message)


def test_credentials_dpapi_isolated_by_surveyor_and_insurer(tmp_path):
    store = CredentialStore(tmp_path / "credentials.dpapi")
    store.save("surveyor-A", "uiic", "A-user", "A-secret", "A-code")
    store.save("surveyor-B", "uiic", "B-user", "B-secret", "B-code")
    store.save("surveyor-A", "oic", "O-user", "O-secret", "O-code")
    assert store.get("surveyor-A", "uiic")["password"] == "A-secret"
    assert store.get("surveyor-B", "uiic")["surveyor_code"] == "B-code"
    assert store.get("surveyor-A", "oic")["username"] == "O-user"
    assert b"A-secret" not in store.path.read_bytes()
    with pytest.raises(ValueError):
        store.get("missing", "uiic")


def test_restart_keeps_current_case_and_pending_result(tmp_path):
    path = tmp_path / "state.json"
    state = CaseState(path)
    state.set({"job": JOB, "phase": "ready", "folder": str(tmp_path), "portal": "uiic"})
    state.update(pending_report={"case_id": JOB["case_id"], "status": "failed", "portal_message": "DL verification pending"})
    assert CaseState(path).current["pending_report"]["status"] == "failed"


@pytest.mark.parametrize("name,expected", [("../../RC.pdf", "RC.pdf"), ("Individual%2FRC.pdf", "RC.pdf"), ("CON.pdf", "_CON.pdf")])
def test_flat_names(name, expected):
    assert flat_name(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("rc_book.pdf", "rc_book.pdf"),
    ("", None),
    ("../../rc_book.pdf", None),
    ("folder%2Frc_book.pdf", None),
    ("bad:name.pdf", None),
])
def test_safe_canonical_names(name, expected):
    assert safe_canonical_name(name) == expected


def test_partial_download_and_bad_manifest_never_become_ready(tmp_path):
    client, server = client_server()
    client.claim(JOB["case_id"], JOB["automation_dispatch_id"])
    server.files[0]["is_latest_corrected_excel"] = False
    with pytest.raises(ValueError, match="exactly one"):
        download_case(client, JOB["case_id"], tmp_path, automation_dispatch_id=JOB["automation_dispatch_id"])
    assert not (tmp_path / "web_sync_manifest.json").exists()


def test_each_file_retries_network_and_integrity_failures(tmp_path, monkeypatch):
    import app.web_sync.downloads as downloads

    payloads = {"excel": b"valid-excel", "photo": b"valid-photo"}
    files = [
        {"file_id": "excel", "name": "claim.xlsx", "is_latest_corrected_excel": True},
        {"file_id": "photo", "name": "vehicle_photo_01.jpg", "doc_type": "CLAIM_PHOTOS"},
    ]
    for entry in files:
        payload = payloads[entry["file_id"]]
        entry["size_bytes"] = len(payload)
        entry["md5_checksum"] = hashlib.md5(payload).hexdigest()

    class RetryClient:
        attempts = {"excel": 0, "photo": 0}

        def call(self, _function, body, destination=None):
            if destination is None:
                return {"case_id": "retry", "latest_corrected_excel": files[0], "files": files}
            file_id = body["file_id"]
            self.attempts[file_id] += 1
            if file_id == "excel" and self.attempts[file_id] == 1:
                raise requests.exceptions.ReadTimeout("temporary timeout")
            if file_id == "photo" and self.attempts[file_id] == 1:
                Path(destination).write_bytes(b"bad-content")
            else:
                Path(destination).write_bytes(payloads[file_id])
            return {"X-Case-File-Path": body["file_id"]}

    monkeypatch.setattr(downloads, "RETRY_DELAYS", (0, 0))
    client = RetryClient()
    events = []
    download_case(
        client, "retry", tmp_path, progress=events.append,
        automation_dispatch_id="dispatch-retry",
    )
    assert client.attempts == {"excel": 2, "photo": 2}
    assert (tmp_path / "claim.xlsx").read_bytes() == payloads["excel"]
    assert (tmp_path / "vehicle_photo_01.jpg").read_bytes() == payloads["photo"]
    assert len([event for event in events if "Retrying the same file" in event.get("message", "")]) == 2


def test_failed_stage_keeps_verified_files_and_resume_skips_them(tmp_path, monkeypatch):
    import app.web_sync.downloads as downloads

    payloads = {"excel": b"verified-excel", "photo": b"eventual-photo"}
    files = [
        {"file_id": "excel", "name": "claim.xlsx", "is_latest_corrected_excel": True},
        {"file_id": "photo", "name": "vehicle_photo_01.jpg", "doc_type": "CLAIM_PHOTOS"},
    ]
    for entry in files:
        payload = payloads[entry["file_id"]]
        entry["size_bytes"] = len(payload)
        entry["md5_checksum"] = hashlib.md5(payload).hexdigest()

    class ResumeClient:
        attempts = {"excel": 0, "photo": 0}
        photo_available = False

        def call(self, _function, body, destination=None):
            if destination is None:
                return {"case_id": "resume", "latest_corrected_excel": files[0], "files": files}
            file_id = body["file_id"]
            self.attempts[file_id] += 1
            if file_id == "photo" and not self.photo_available:
                raise requests.exceptions.ReadTimeout("temporary timeout")
            Path(destination).write_bytes(payloads[file_id])
            return {}

    monkeypatch.setattr(downloads, "RETRY_DELAYS", (0, 0))
    client = ResumeClient()
    with pytest.raises(requests.exceptions.ReadTimeout):
        download_case(client, "resume", tmp_path, automation_dispatch_id="dispatch-resume")
    assert client.attempts == {"excel": 1, "photo": 3}
    assert (tmp_path / "claim.xlsx").read_bytes() == payloads["excel"]
    assert not (tmp_path / "vehicle_photo_01.jpg").exists()
    assert not list(tmp_path.glob("*.download"))

    client.photo_available = True
    events = []
    download_case(
        client, "resume", tmp_path, progress=events.append,
        automation_dispatch_id="dispatch-resume",
    )
    assert client.attempts == {"excel": 1, "photo": 4}
    assert any(event.get("kind") == "file_skipped" and event.get("file_id") == "excel" for event in events)
    assert (tmp_path / "vehicle_photo_01.jpg").read_bytes() == payloads["photo"]


def test_main_excel_override_is_local_and_resets():
    from app.utils import load_doc_mapping, scan_main_excel
    original = load_doc_mapping("uiic")
    token = scan_main_excel.set("websync_example.xlsx")
    try:
        assert load_doc_mapping("uiic")["main_excel_keywords"] == ["websync_example.xlsx"]
    finally:
        scan_main_excel.reset(token)
    assert load_doc_mapping("uiic") == original


def test_submission_monitor_browser_error_then_retry(tmp_path):
    from playwright.async_api import async_playwright
    async def scenario():
        records = []
        monitor = SubmissionMonitor(JOB["case_id"], tmp_path, records.append)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            await monitor.install(context)
            page = await context.new_page()
            await page.goto("data:text/html,<button>Final Submit</button><button>Save</button><div id='result'></div>")
            await page.evaluate("""() => {
              window.message = 'DL verification pending';
              document.querySelector('button').onclick = () => {
                document.querySelector('#result').innerHTML = '<div role="alert">' + window.message + '</div>';
              };
            }""")
            await page.get_by_role("button", name="Final Submit", exact=True).click()
            await page.wait_for_timeout(250)
            await page.evaluate("() => window.__app3Capture()")
            assert records[-1]["portal_message"] == "DL verification pending"
            assert not records[-1]["confirmed_success"]
            assert not page.is_closed()
            await page.get_by_role("button", name="Save", exact=True).click()
            await page.evaluate("() => document.querySelector('#result').innerHTML = '<div role=alert>Report submitted successfully</div>'")
            await page.wait_for_timeout(100)
            assert len(records) == 1
            await page.evaluate("() => { window.message = 'Report submitted successfully'; document.querySelector('#result').innerHTML = ''; }")
            await page.get_by_role("button", name="Final Submit", exact=True).click()
            await page.evaluate("() => window.__app3Capture()")
            assert records[-1]["confirmed_success"]
            saved = json.loads((tmp_path / "Portal_Submission_Result.json").read_text())
            assert saved["portal_message"] == "Report submitted successfully"
            assert saved["timestamp"]
            assert list(tmp_path.glob("Portal_Submission_Result_*.png"))
            await browser.close()
    asyncio.run(scenario())


def test_native_dialog_exact_text_saved_before_accept(tmp_path):
    from playwright.async_api import async_playwright
    from app.web_sync.submission import capture_native_before_dismiss
    async def scenario():
        records, accepted = [], []
        monitor = SubmissionMonitor(JOB["case_id"], tmp_path, records.append)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            await monitor.install(context)
            page = await context.new_page()
            async def on_dialog(dialog):
                await capture_native_before_dismiss(page, dialog)
                saved = json.loads((tmp_path / "Portal_Submission_Result.json").read_text())
                accepted.append(saved["portal_message"])
                await dialog.accept()
            page.on("dialog", on_dialog)
            message = "DL verification pending: " + "details " * 60
            await page.goto("data:text/html,<button>Final Submit</button>")
            await page.evaluate("message => document.querySelector('button').onclick = () => alert(message)", message)
            await page.get_by_role("button", name="Final Submit").click()
            for _ in range(50):
                if accepted:
                    break
                await page.wait_for_timeout(100)
            assert accepted == [message]
            assert records[0]["portal_message"] == message
            assert not records[0]["confirmed_success"]
            await browser.close()
    asyncio.run(scenario())


def test_portal_mapping():
    assert portal_for(" UNITED  INDIA INSURANCE COMPANY LIMITED ") == "uiic"
    assert portal_for("The New India Assurance Company Limited") == "newindia"
    assert portal_for("newindia") == "newindia"
    assert portal_for("Oriental Insurance Company Limited") == "oic"
    assert portal_for(" UIIC ") == "uiic"
    assert portal_for("nia") == "newindia"
    assert portal_for("OIC") == "oic"
    assert portal_for("United India Insurance") == "uiic"
    assert portal_for("New India Assurance") == "newindia"
    assert portal_for("Oriental Insurance") == "oic"
    with pytest.raises(ValueError):
        portal_for("unknown")


def test_operator_login_saved_restored_and_forgotten(qapp, tmp_path, monkeypatch):
    import app.web_sync.page as module
    page, server, opened = queue_page(qapp, tmp_path)
    monkeypatch.setattr(module, "Client", lambda email, password: Client(email, password, session=server))
    try:
        page.email.setText("dummy@example.invalid")
        page.password.setText("operator-test-secret")
        page.connect_client()
        assert page.connection.text() == "Connected to DocWriter"
        assert page.operator_store.get() == {"email": "dummy@example.invalid", "password": "operator-test-secret"}
        encrypted = page.operator_store.path.read_bytes()
        assert b"operator-test-secret" not in encrypted
        assert "access_token" not in page.operator_store.get()
        logins = server.logins
        page.client = None  # Simulate a new process without a token.
        page.restore_login()
        assert server.logins == logins + 1
        assert page.jobs == [JOB]
        assert not opened and not server.claimed
        portal_bytes = page.store.path.read_bytes()
        page.forget_login()
        assert page.operator_store.get() is None
        assert page.store.path.read_bytes() == portal_bytes
        assert page.client is None and not page.jobs
        page.restore_login()
        assert page.client is None
    finally:
        page.shutdown()
        page.close()


def test_incoming_staging_has_no_user_toggle(qapp, tmp_path):
    page, _, _ = queue_page(qapp, tmp_path)
    try:
        assert not hasattr(page, "auto_pickup_enabled")
        assert not hasattr(page, "auto_pickup_toggle")
        assert any(
            "Incoming cases download automatically" in label.text()
            for label in page.findChildren(QLabel)
        )
    finally:
        page.shutdown()
        page.close()


def test_auto_pickup_stages_all_cases_without_claim_or_workspace(qapp, tmp_path):
    page, server, opened = queue_page(qapp, tmp_path)
    try:
        second = {**JOB, "case_id": "case_dummy_002", "case_ref": "SECOND"}
        server.queued_jobs = [dict(JOB), dict(second)]
        page.jobs = [JOB, second]
        page.list.clear()
        for job in page.jobs:
            page.list.addItem(job["case_ref"])
        page.auto_pickup_enabled = True
        page._maybe_auto_pickup()
        qapp.processEvents()
        assert not server.claimed
        assert page.state.current is None
        assert {r["case_id"] for r in page._records()} == {JOB["case_id"], second["case_id"]}
        statuses = {r["case_id"]: r["local_status"] for r in page._records()}
        assert statuses == {JOB["case_id"]: "ready", second["case_id"]: "ready"}
        assert not opened
        assert page.window._worker is None
        assert not any(call[0] == "reportAutomationResult" for call in server.calls)
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("change, expected_status", [
    ({"surveyor_profile_id": "unsaved-profile"}, "ready"),
    ({"insurer": "Unknown Insurance Ltd"}, "stage failed"),
])
def test_auto_pickup_validates_insurer_but_not_start_credentials(qapp, tmp_path, change, expected_status):
    page, server, opened = queue_page(qapp, tmp_path)
    try:
        page.jobs = [{**JOB, **change}]
        page.list.clear()
        page.list.addItem("oldest")
        page.auto_pickup_enabled = True
        page._maybe_auto_pickup()
        assert not server.claimed
        assert page.state.current is None
        assert page._records()[0]["local_status"] == expected_status
        assert not opened
    finally:
        page.shutdown()
        page.close()


def test_auto_pickup_continues_staging_while_workspace_or_browser_is_busy(qapp, tmp_path):
    page, server, opened = queue_page(qapp, tmp_path)
    try:
        page.auto_pickup_enabled = True
        page.window._worker = object()
        page._maybe_auto_pickup()
        assert not server.claimed
        assert page._record(JOB["case_id"])["local_status"] == "ready"
        page.case_repo.remove(JOB["case_id"])
        page.window._worker = None
        page.window._scan_thread = object()
        page._maybe_auto_pickup()
        assert not server.claimed
        assert page._record(JOB["case_id"])["local_status"] == "ready"
        page.case_repo.remove(JOB["case_id"])
        page.window._scan_thread = None
        manual = tmp_path / "manual"
        manual.mkdir()
        page.window._claim = SimpleNamespace(
            _scan_context=SimpleNamespace(claim_folder_path=str(manual))
        )
        page._maybe_auto_pickup()
        assert not server.claimed and not opened
        assert page._record(JOB["case_id"])["local_status"] == "ready"
    finally:
        page.shutdown()
        page.close()


def test_incoming_staging_downloads_without_claim_or_workspace(qapp, tmp_path, monkeypatch):
    import app.web_sync.page as module
    page, server, opened = queue_page(qapp, tmp_path)
    try:
        def stage(_client, _case_id, folder, progress=None, **_kwargs):
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / "web_sync_manifest.json").write_text("{}", encoding="utf-8")
            return "latest.xlsx"
        monkeypatch.setattr(module, "download_case", stage)
        page._maybe_auto_pickup()
        assert not server.claimed and not opened
        assert page._record(JOB["case_id"])["local_status"] == "ready"
    finally:
        page.shutdown()
        page.close()


def test_corrupt_saved_operator_login_does_not_crash(qapp, tmp_path):
    page, _, _ = queue_page(qapp, tmp_path)
    try:
        page.operator_store.path.write_bytes(b"invalid DPAPI")
        page.client = None
        page.restore_login()
        assert page.client is None
        assert "Unable to read saved DocWriter login" in page.result.text()
    finally:
        page.shutdown()
        page.close()


def test_failed_login_does_not_replace_saved_operator(qapp, tmp_path, monkeypatch):
    import app.web_sync.page as module
    page, _, _ = queue_page(qapp, tmp_path)
    try:
        page.operator_store.save("old@example.invalid", "old-secret")
        original = page.operator_store.path.read_bytes()
        class RejectedClient:
            def __init__(self, *args):
                pass
            def login(self):
                raise ApiError(401, "Login")
        monkeypatch.setattr(module, "Client", RejectedClient)
        page.email.setText("wrong@example.invalid")
        page.password.setText("wrong-secret")
        page.connect_client()
        assert page.operator_store.path.read_bytes() == original
        assert "Disconnected" in page.connection.text()
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("message,expected", [
    ("Survey report submitted successfully. Physical documents are not required.", True),
    ("Report submitted successfully. Approval pending.", True),
    ("Report submitted successfully. DL pending.", False),
    ("Report submitted successfully. Voucher pending.", False),
    ("Report submitted successfully. Amount incorrect.", False),
    ("Submission failed. Report not submitted successfully.", False),
])
def test_success_qualifications_preserve_validation_errors(message, expected):
    assert confirms_submission(message) is expected


def test_bad_queue_job_does_not_hide_valid_case():
    client, server = client_server()
    original = server.post
    def mixed(url, **kwargs):
        response = original(url, **kwargs)
        if url.endswith("getAutomationJobs") and response.status_code == 200:
            response.data["jobs"] += [{"case_id": "incomplete"}, None]
        return response
    server.post = mixed
    assert client.jobs() == [JOB]
    assert "Skipped 2" in client.queue_warning


def test_corrupt_dpapi_is_caught_by_queue_ui(qapp, tmp_path):
    page, _, _ = queue_page(qapp, tmp_path)
    try:
        page.store.path.write_bytes(b"not a DPAPI file")
        page._selected(0)
        assert "Unable to read" in page.cred_feedback.text()
        page.start_case()
        assert page.state.current is None
    finally:
        page.shutdown()
        page.close()


def test_final_button_variants_and_confirmation_chain(tmp_path):
    from playwright.async_api import async_playwright
    async def scenario():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for number, (label, heading, expected) in enumerate([
                ("Final Submit Report", "", True),
                ("Confirm & Submit", "", True),
                ("Proceed to Submit", "", True),
                ("Submit", "Final Submission", True),
                ("Submit", "Driver Details", False),
                ("Save", "Final Submission", False),
                ("Next", "Final Submission", False),
            ]):
                folder = tmp_path / str(number)
                records = []
                monitor = SubmissionMonitor(JOB["case_id"], folder, records.append)
                context = await browser.new_context()
                await monitor.install(context)
                page = await context.new_page()
                await page.goto("data:text/html,<section><h2>" + heading + "</h2><button id='start'>" + label.replace('&', '&amp;') + "</button></section><button id='confirm'>Yes</button><div id='result'></div>")
                await page.evaluate("""() => {
                    document.querySelector('#confirm').onclick = () => {
                        document.querySelector('#result').innerHTML = '<div role="alert">Report submitted successfully</div>';
                    };
                }""")
                await page.locator('#start').click()
                await page.locator('#confirm').click()
                await page.evaluate("() => window.__app3Capture()")
                assert bool(records and records[-1]['confirmed_success']) is expected, (label, heading)
                await context.close()
            await browser.close()
    asyncio.run(scenario())


def test_credential_editor_clears_unsaved_values_without_changing_store(qapp, tmp_path):
    page, server, _ = queue_page(qapp, tmp_path)
    try:
        before = page.store.path.read_bytes()
        page.jobs.append({**JOB, "case_id": "second-case"})
        page.username.setText("unsaved-user")
        page.secret.setText("unsaved-password")
        page.code.setText("unsaved-code")
        page._selected(1)
        assert page.profile.text() == JOB["surveyor_profile_id"]
        assert page.insurer.currentData() == "uiic"
        assert not page.username.text() and not page.secret.text() and not page.code.text()
        assert page.cred_feedback.text() == "Saved credentials available"
        assert page.store.path.read_bytes() == before
        page.jobs.append({**JOB, "surveyor_profile_id": "another-surveyor"})
        page._selected(2)
        assert "Saved credentials available" not in page.cred_feedback.text()
        assert page.store.path.read_bytes() == before
    finally:
        page.shutdown()
        page.close()


def test_banner_requires_success_report_and_uploaded_ack(qapp):
    from PyQt6.QtWidgets import QFrame, QLabel
    from app.web_sync.page import ResultBannerLabel
    frame, pill, timestamp = QFrame(), QLabel(), QLabel()
    banner = ResultBannerLabel(frame, pill, timestamp)
    banner.setText("Report submitted successfully")
    assert "CONFIRMED SUCCESS" not in pill.text()
    banner.setText("Base44 acknowledged: ready_for_upload")
    assert pill.text().strip() == "FAILED / NEEDS ATTENTION"
    banner.set_report_result("Base44 acknowledged: ready_for_upload", "failed", "ready_for_upload")
    assert pill.text().strip() == "FAILED / NEEDS ATTENTION"
    banner.set_report_result("Base44 acknowledged: uploaded", "failed", "uploaded")
    assert "CONFIRMED SUCCESS" not in pill.text()
    banner.set_report_result("Base44 acknowledged: uploaded", "success", "uploaded")
    assert pill.text().strip() == "CONFIRMED SUCCESS"
    banner.setText("Report not submitted successfully: DL pending")
    assert "CONFIRMED SUCCESS" not in pill.text()


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def queue_page(qapp, tmp_path):
    from app.web_sync.page import WebQueuePage
    opened = []
    window = SimpleNamespace(
        _worker=None, _scan_thread=None, _claim=None,
        _open_web_case=opened.append, _stop_automation=lambda: None,
        _start_automation=lambda: None,
    )
    page = WebQueuePage(window, tmp_path)
    page.timer.stop()
    page.stage_pool.shutdown(wait=False, cancel_futures=True)
    page.stage_pool = ImmediateExecutor()
    # Deterministically execute the same network operations without Qt thread timing.
    def run(operation, function):
        page.busy = True
        try:
            value, error = function(), None
        except Exception as exc:
            value, error = None, exc
        page._completed(operation, value, error)
    page.run_task = run
    page.client, server = client_server()
    page.store.save(JOB["surveyor_profile_id"], "uiic", "local-portal-user", "local-portal-secret", "SC-1")
    page.poll()
    page.list.setCurrentRow(0)
    return page, server, opened


def prepare_workspace(page):
    """Stage and scan the selected case without claiming it in Base44."""
    page.start_case()
    page.refresh()
    record = page._selected_case_record()
    assert record["local_status"] == "ready"
    page._case_clicked(page.list.currentItem())
    page.window._claim = SimpleNamespace(
        _scan_context=SimpleNamespace(claim_folder_path=record["folder"])
    )
    page.workspace_scan_completed(record["folder"], True)
    page.refresh()
    return page._record(record["case_id"])


def activate_case(page):
    """Prepare Workspace, then cross the claim boundary via Start Automation."""
    prepared = prepare_workspace(page)
    page.start_automation()
    assert page.state.current is not None
    return prepared


def test_queue_one_case_error_correction_success_and_manual_isolation(qapp, tmp_path):
    page, server, opened = queue_page(qapp, tmp_path)
    try:
        activate_case(page)
        assert len(opened) == 1
        current = page.state.current
        assert current["phase"] == "automation active"
        assert page.excel_for(current["folder"]) == current["latest_excel"]
        settings = page.settings_for(current["folder"], "uiic")
        assert settings["username"] == "local-portal-user"
        assert settings["surveyor_code"] == "SC-1"
        assert page.settings_for(str(tmp_path / "manual-folder"), "uiic") == {}
        records = []
        def callback(record):
            records.append(record)
            page._submission(record)
        monitor = SubmissionMonitor(JOB["case_id"], current["folder"], callback)
        asyncio.run(monitor.capture({"message": "DL verification pending", "kind": "dom", "attempt": 1}))
        assert not server.reports
        assert page.state.current["last_message"] == "DL verification pending"
        # A second Start resumes the current case rather than claiming another.
        page.start_automation()
        assert len([c for c in server.calls if c[0] == "claimAutomationCase"]) == 1
        asyncio.run(monitor.capture({"message": "Report submitted successfully", "kind": "dom", "attempt": 2}))
        assert server.reports == [{
            "case_id": JOB["case_id"],
            "automation_dispatch_id": JOB["automation_dispatch_id"],
            "status": "success", "portal_message": "Report submitted successfully",
        }]
        assert page.state.current is None
        assert Path(current["folder"], "Web_Sync_Report_Acknowledgement.json").exists()
        with pytest.raises(ValueError, match="not the current"):
            page.settings_for(current["folder"], "uiic")
        assert all("local-portal-secret" not in json.dumps(c[1]) for c in server.calls)
        page.window._worker = object()
        page.start_case()
        assert len([c for c in server.calls if c[0] == "claimAutomationCase"]) == 1
    finally:
        page.shutdown()
        page.close()


def test_failed_report_stays_pending_until_retry(qapp, tmp_path):
    page, server, opened = queue_page(qapp, tmp_path)
    try:
        activate_case(page)
        original = page.client.report
        def unavailable(payload):
            raise ApiError(503, "reportAutomationResult")
        page.client.report = unavailable
        page._submission({"case_id": JOB["case_id"], "confirmed_success": True, "portal_message": "Report submitted successfully"})
        assert page.state.current["pending_report"]["status"] == "success"
        page.start_automation()
        assert len(opened) == 1
        page.client.report = original
        page.poll()
        assert page.state.current is None
        assert len(server.reports) == 1
    finally:
        page.shutdown()
        page.close()


def test_deliberate_failure_exact_status(qapp, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QInputDialog
    page, server, _ = queue_page(qapp, tmp_path)
    try:
        activate_case(page)
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Voucher pending", True))
        page.fail_case()
        assert server.reports == [{
            "case_id": JOB["case_id"],
            "automation_dispatch_id": JOB["automation_dispatch_id"],
            "status": "failed", "portal_message": "Voucher pending",
        }]
        assert page.state.current is None
    finally:
        page.shutdown()
        page.close()


def test_main_window_manual_browse_unchanged_and_web_handoff(qapp, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog
    from app.ui.main_window import MainWindow
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    window = MainWindow()
    window.web_queue.timer.stop()
    assert window.settings_page.btn_change_docwriter_login.text() == "Change Login"
    assert window.settings_page.btn_forget_docwriter_login.text() == "Forget Login"
    calls = []
    window._scan_folder = calls.append
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path / "manual"))
    try:
        window._browse_folder()
        assert calls == [str(tmp_path / "manual")]
        window._open_web_case({"portal": "oic", "folder": str(tmp_path / "web")})
        assert calls[-1] == str(tmp_path / "web")
        assert window.portal_combo.currentData() == "oic"
        window._switch_page(2)
        window.show()
        qapp.processEvents()
        assert window.stack.currentWidget() is window.web_queue
        assert window.grab().save(str(tmp_path / "web_queue.png"))
    finally:
        window.close()


def test_real_scanner_uses_marked_workbook_with_old_excel_present(tmp_path):
    from openpyxl import Workbook
    from app.data.folder_scanner import scan_folder
    from app.utils import scan_main_excel
    for name in ("old_claim.xlsx", "websync_deadbeef1234.xlsx"):
        workbook = Workbook()
        workbook.active["A1"] = "Dummy claim"
        workbook.save(tmp_path / name)
    token = scan_main_excel.set("websync_deadbeef1234.xlsx")
    try:
        result = scan_folder(str(tmp_path), portal_id="uiic")
        assert result.excel_path == str(tmp_path / "websync_deadbeef1234.xlsx")
    finally:
        scan_main_excel.reset(token)


def test_final_submission_survives_page_navigation(tmp_path):
    from playwright.async_api import async_playwright
    async def scenario():
        records = []
        monitor = SubmissionMonitor(JOB["case_id"], tmp_path, records.append)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            await monitor.install(context)
            await context.route("https://dummy.invalid/**", lambda route: route.fulfill(
                content_type="text/html", body=("<div role='alert'>Report submitted successfully</div>" if route.request.url.endswith("result") else "<button onclick=\"location.href='/result'\">Final Submit</button>")))
            page = await context.new_page()
            await page.goto("https://dummy.invalid/start")
            await page.get_by_role("button", name="Final Submit").click()
            await page.wait_for_url("**/result")
            for _ in range(30):
                if records:
                    break
                await page.wait_for_timeout(100)
            assert records[-1]["confirmed_success"]
            await browser.close()
    asyncio.run(scenario())


def test_corrupt_sync_journal_does_not_break_manual_ui(qapp, tmp_path):
    from app.web_sync.page import WebQueuePage
    (tmp_path / "current_case.json").write_text("{broken")
    window = SimpleNamespace(_worker=None, _scan_thread=None)
    page = WebQueuePage(window, tmp_path)
    try:
        assert page.state_error
        assert not page.start_button.isEnabled()
        assert page.settings_for(str(tmp_path / "manual"), "uiic") == {}
    finally:
        page.shutdown()
        page.close()


def test_saved_success_is_reported_before_resume(qapp, tmp_path):
    from app.web_sync.storage import atomic_json
    page, server, opened = queue_page(qapp, tmp_path)
    try:
        activate_case(page)
        folder = page.state.current["folder"]
        atomic_json(Path(folder) / "Portal_Submission_Result.json", {
            "case_id": JOB["case_id"], "confirmed_success": True,
            "portal_message": "Report submitted successfully", "timestamp": "2026-09-10T10:00:00+00:00",
        })
        # Simulate browser shutdown between durable capture and the Qt callback.
        page.start_automation()
        assert page.state.current is None
        assert len(server.reports) == 1
        assert len(opened) == 1
        assert len([c for c in server.calls if c[0] == "claimAutomationCase"]) == 1
    finally:
        page.shutdown()
        page.close()


def test_completed_case_store_persists_and_updates_one_case(tmp_path):
    store = CompletedCaseStore(tmp_path / "completed_cases.json")
    store.upsert({"case_id": "one", "case_ref": "REF-1", "section": "workspace"})
    store.upsert({"case_id": "one", "section": "completed", "result": "Submitted successfully"})
    assert store.all() == [{
        "case_id": "one", "case_ref": "REF-1", "section": "completed",
        "result": "Submitted successfully",
    }]
    store.remove("one")
    assert store.all() == []


def test_mark_completed_unconfirmed_keeps_base44_lock_and_blocks_auto_pickup(qapp, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    page, server, _ = queue_page(qapp, tmp_path)
    try:
        activate_case(page)
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        page.mark_completed()
        assert page.state.current is not None
        assert page.state.current["locally_completed"] is True
        assert page.state.current["phase"] == "needs final resolution"
        assert page.state.current is not None
        assert server.reports == []
        entry = page.completed_store.all()[0]
        assert entry["section"] == "completed"
        assert entry["unresolved"] is True
        assert entry["display_result"] == "Completed Locally — Base44 Unresolved"
        assert page.completed_list.count() == 1
    finally:
        page.shutdown()
        page.close()


def test_delete_completed_copy_is_local_only_and_unresolved_lock_remains(qapp, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    page, server, _ = queue_page(qapp, tmp_path)
    try:
        activate_case(page)
        folder = Path(page.state.current["folder"])
        assert folder.exists()
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        page.mark_completed()
        page.completed_list.setCurrentRow(0)
        page.delete_completed_local_copy()
        assert not folder.exists()
        assert page.state.current is not None
        assert page.state.current["local_copy_deleted"] is True
        assert page.state.current is not None
        assert server.reports == []
        assert page.completed_store.all()[0]["folder"] == ""
    finally:
        page.shutdown()
        page.close()


def test_confirmed_success_waits_in_workspace_until_marked_completed(qapp, tmp_path):
    page, server, _ = queue_page(qapp, tmp_path)
    try:
        activate_case(page)
        page._submission({
            "case_id": JOB["case_id"], "confirmed_success": True,
            "portal_message": "Report submitted successfully",
        })
        assert page.state.current is None
        assert server.reports[-1]["status"] == "success"
        assert page.completed_store.all()[0]["section"] == "workspace"
        assert page._selected_kind() == "resolved"
        page.mark_completed()
        entry = page.completed_store.all()[0]
        assert entry["section"] == "completed"
        assert entry["base44_status"] == "uploaded"
        assert entry["display_result"] == "Submitted Successfully"
    finally:
        page.shutdown()
        page.close()


def test_web_queue_start_automation_waits_for_workspace_and_uses_existing_action(qapp, tmp_path):
    page, _, _ = queue_page(qapp, tmp_path)
    started = []
    page.window._start_automation = lambda: started.append(True)
    try:
        page.start_case()
        page.refresh()
        record = page._selected_case_record()
        folder = record["folder"]
        assert page.start_button.text().endswith("Start Automation")
        assert not page.start_button.isEnabled()
        page._case_clicked(page.list.currentItem())
        page.window._claim = SimpleNamespace(
            _scan_context=SimpleNamespace(claim_folder_path=folder)
        )
        page.workspace_scan_completed(folder, True)
        assert page.start_button.isEnabled()
        page.start_automation()
        assert started == [True]
    finally:
        page.shutdown()
        page.close()


def test_canonical_manifest_download_scans_with_existing_document_review(qapp, tmp_path):
    from io import BytesIO
    from openpyxl import Workbook
    from app.data.folder_scanner import scan_folder
    from app.ui.components.workspace_page import DocumentReviewPanel
    from app.utils import scan_main_excel

    workbook = Workbook()
    workbook.active["A1"] = "Dummy web claim"
    workbook_bytes = BytesIO()
    workbook.save(workbook_bytes)

    files = [
        {"file_id": "excel", "name": "Corrected Case 4895.xlsx", "path": "Final_Merged/Corrected Case 4895.xlsx", "doc_type": "CORRECTED_EXCEL", "canonical_name": "corrected_claim.xlsx", "is_latest_corrected_excel": True},
        {"file_id": "rc", "name": "RC Registration Certificate.pdf", "path": "Final_Merged/RC Registration Certificate.pdf", "doc_type": "RC", "canonical_name": "rc_book.pdf"},
        {"file_id": "dl", "name": "Driving Licence.pdf", "path": "Final_Merged/Driving Licence.pdf", "doc_type": "DL", "canonical_name": "driving_license.pdf"},
        {"file_id": "policy", "name": "Policy Copy.pdf", "path": "Final_Merged/Policy Copy.pdf", "doc_type": "POLICY", "canonical_name": "insurance_policy.pdf"},
        {"file_id": "estimate", "name": "Estimate.pdf", "path": "Final_Merged/Estimate.pdf", "doc_type": "ESTIMATE", "canonical_name": "repair_estimate.pdf"},
        {"file_id": "invoice", "name": "Invoice.pdf", "path": "Final_Merged/Invoice.pdf", "doc_type": "INVOICE", "canonical_name": "final_invoice.pdf"},
        {"file_id": "photos", "name": "Photo_Sheet_4895.pdf", "path": "Final_Merged/Photo_Sheet_4895.pdf", "doc_type": "CLAIM_PHOTOS", "canonical_name": "photo_sheet.pdf"},
    ]
    payloads = {entry["file_id"]: b"%PDF-1.4 dummy" for entry in files}
    payloads["excel"] = workbook_bytes.getvalue()
    for entry in files:
        entry["size_bytes"] = len(payloads[entry["file_id"]])
        entry["md5_checksum"] = hashlib.md5(payloads[entry["file_id"]]).hexdigest()

    class ManifestClient:
        def call(self, _function, body, destination=None):
            if destination is None:
                return {"case_id": "dummy", "latest_corrected_excel": files[0], "files": files}
            Path(destination).write_bytes(payloads[body["file_id"]])
            return {"X-Case-File-Path": next(item["path"] for item in files if item["file_id"] == body["file_id"])}

    latest = download_case(ManifestClient(), "dummy", tmp_path, automation_dispatch_id="dispatch-dummy")
    expected_names = {
        "corrected_claim.xlsx", "rc_book.pdf", "driving_license.pdf",
        "insurance_policy.pdf", "repair_estimate.pdf", "final_invoice.pdf",
        "photo_sheet.pdf", "web_sync_manifest.json",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected_names
    manifest = json.loads((tmp_path / "web_sync_manifest.json").read_text(encoding="utf-8"))
    assert manifest["latest_excel"] == "corrected_claim.xlsx" == latest
    assert all({
        "original_name", "original_path", "doc_type", "canonical_name", "local_name", "file_id",
    } <= set(item) for item in manifest["files"])

    token = scan_main_excel.set(latest)
    try:
        result = scan_folder(str(tmp_path), portal_id="uiic")
    finally:
        scan_main_excel.reset(token)
    assert Path(result.excel_path).name == "corrected_claim.xlsx"
    assert Path(result.claim_doc_files["RC Book"]).name == "rc_book.pdf"
    assert Path(result.claim_doc_files["Driving License"]).name == "driving_license.pdf"
    assert Path(result.assessment_files["estimate"]).name == "repair_estimate.pdf"
    assert Path(result.assessment_files["invoice"]).name == "final_invoice.pdf"
    for slot in (
        "Vehicle Photograph (Front)", "Vehicle Photograph(Rear)",
        "Vehicle Photograph (Left)", "Vehicle Photograph (Right)",
    ):
        assert slot in result.claim_doc_files

    review = DocumentReviewPanel()
    review.update_data(result)
    table = review._doc_tables[0][0]
    visible_text = {
        table.item(row, column).text()
        for row in range(table.rowCount()) for column in range(table.columnCount())
        if table.item(row, column)
    }
    assert {"RC Book", "Driving License", "Estimate", "Invoice"} <= visible_text
    review.close()


def test_canonical_collisions_use_suffixes_and_unflagged_excel_cannot_compete(tmp_path, caplog):
    files = [
        {"file_id": "main", "name": "latest.xlsx", "path": "latest.xlsx", "doc_type": "CORRECTED_EXCEL", "canonical_name": "corrected_claim.xlsx", "is_latest_corrected_excel": True},
        {"file_id": "other_excel", "name": "older.xlsx", "path": "older.xlsx", "doc_type": "OTHER_EXCEL", "canonical_name": "corrected_claim.xlsx"},
        {"file_id": "rc1", "name": "one.pdf", "path": "one.pdf", "doc_type": "RC", "canonical_name": "rc_book.pdf"},
        {"file_id": "rc2", "name": "two.pdf", "path": "two.pdf", "doc_type": "RC", "canonical_name": "rc_book.pdf"},
        {"file_id": "rc3", "name": "three.pdf", "path": "three.pdf", "doc_type": "RC", "canonical_name": "rc_book.pdf"},
        {"file_id": "photo1", "name": "Photo_Sheet_1.pdf", "path": "Photo_Sheet_1.pdf", "doc_type": "CLAIM_PHOTOS", "canonical_name": "photo_sheet.pdf"},
        {"file_id": "photo2", "name": "Photo_Sheet_2.pdf", "path": "Photo_Sheet_2.pdf", "doc_type": "CLAIM_PHOTOS", "canonical_name": "photo_sheet.pdf"},
    ]
    for entry in files:
        entry["size_bytes"] = len(b"file")
        entry["md5_checksum"] = hashlib.md5(b"file").hexdigest()

    class ManifestClient:
        def call(self, _function, body, destination=None):
            if destination is None:
                return {"case_id": "collision", "latest_corrected_excel": files[0], "files": files}
            Path(destination).write_bytes(b"file")
            return {}

    with caplog.at_level("WARNING"):
        latest = download_case(ManifestClient(), "collision", tmp_path, automation_dispatch_id="dispatch-collision")
    manifest = json.loads((tmp_path / "web_sync_manifest.json").read_text(encoding="utf-8"))
    names = [item["local_name"] for item in manifest["files"]]
    assert latest == "corrected_claim.xlsx"
    assert "corrected_claim__2.xlsx" not in names
    assert "older.xlsx" not in names
    assert {"rc_book.pdf", "rc_book__2.pdf", "rc_book__3.pdf"} <= set(names)
    assert {"photo_sheet.pdf", "photo_sheet__2.pdf"} <= set(names)
    assert len({name.lower() for name in names}) == len(names)
    assert "filename collision" in caplog.text


def test_submission_monitor_accepts_dispatch_id_and_kwargs(tmp_path):
    received = []
    monitor = SubmissionMonitor(
        case_id="case_abc",
        folder=tmp_path,
        callback=received.append,
        automation_dispatch_id="dispatch_123",
        extra_future_argument="safely_ignored",
    )
    assert monitor.case_id == "case_abc"
    assert monitor.automation_dispatch_id == "dispatch_123"
    assert monitor.folder == tmp_path

