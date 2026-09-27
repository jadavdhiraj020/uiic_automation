"""No insurer login or real Base44 case is used by these helper contract tests."""

from dataclasses import replace
from hashlib import md5
from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import threading
import time
import zipfile

import pytest

from app.helper_v1.api import HelperServer, ORIGIN
from app.helper_v1.base44 import RemoteError
from app.helper_v1.contracts import ContractError, RunContext, StartRequest, parse_redemption
from app.helper_v1.coordinator import BusyError, RunCoordinator
from app.helper_v1.intake import ZipIntake
from app.helper_v1 import outbox as outbox_module


def start_body(**changes):
    body = {"command": "START_RUN", "contract_version": 1, "run_id": "TEST-001",
            "dispatch_id": "D-001", "portal_id": "uiic", "case_ref": "TEST-CASE",
            "launch_token": "launch-secret", "api_base": ORIGIN}
    body.update(changes)
    return body


def context():
    return RunContext("TEST-001", "D-001", "uiic", "TEST-CASE", ORIGIN,
        "run-secret", "tester", "test-password", "SURV",
        ORIGIN + "/functions/helperDownloadRunZip",
        ORIGIN + "/functions/helperRunCallback")


def redemption_body():
    c = context()
    return {"ok": True, "contract_version": 1, "run_id": c.run_id,
            "dispatch_id": c.dispatch_id, "run_token": c.run_token,
            "portal_username": c.portal_username, "portal_password": c.portal_password,
            "surveyor_code": c.surveyor_code, "zip_endpoint": c.zip_endpoint,
            "callback_endpoint": c.callback_endpoint}


def wait_for(predicate, seconds=2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    assert predicate()


@pytest.fixture(autouse=True)
def fake_dpapi(monkeypatch):
    # Production uses win32crypt; tests replace only the OS encryption boundary.
    monkeypatch.setattr(outbox_module, "_protect", lambda s: "sealed:" + s)
    monkeypatch.setattr(outbox_module, "_unprotect", lambda s: s.removeprefix("sealed:"))


def test_start_contract_and_redemption_identity():
    start = StartRequest.parse(start_body())
    assert parse_redemption(start, redemption_body()).portal_password == "test-password"
    for change in ({"contract_version": 2}, {"portal_id": "oic"},
                   {"api_base": "http://evil.example"}, {"run_id": "../x"}):
        with pytest.raises(ContractError):
            StartRequest.parse(start_body(**change))
    with pytest.raises(ContractError):
        parse_redemption(start, {**redemption_body(), "dispatch_id": "wrong"})


def test_base44_redemption_uses_exact_v1_body_and_never_retries_invalid_token():
    from app.helper_v1.base44 import Base44V1Client

    class Response:
        status_code = 200
        def json(self):
            return redemption_body()

    class Session:
        def __init__(self):
            self.calls = []
            self.response = Response()

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self.response

    session = Session()
    client = Base44V1Client(session)
    request = StartRequest.parse(start_body())
    assert client.redeem(request).run_token == "run-secret"
    assert session.calls[0][0] == ORIGIN + "/functions/validateLaunchToken"
    assert session.calls[0][1]["json"] == {"run_id": "TEST-001",
        "dispatch_id": "D-001", "launch_token": "launch-secret"}
    session.response = type("Expired", (), {"status_code": 410, "reason": "Gone",
        "json": lambda self: {"error": "expired"}})()
    with pytest.raises(RemoteError):
        client.redeem(request)
    assert len(session.calls) == 2


class FakeClient:
    def __init__(self, archive=None):
        self.archive = archive
        self.events = []
        self.redeem_error = None
        self.callback_error = None

    def redeem(self, start):
        if self.redeem_error:
            raise self.redeem_error
        return context()

    def download_zip(self, _context, destination, stop_requested=lambda: False):
        if stop_requested():
            raise InterruptedError()
        Path(destination).write_bytes(self.archive)

    def callback(self, _context, event):
        if self.callback_error:
            raise self.callback_error
        self.events.append(dict(event))
        return {"ok": True}


def make_zip(manifest=True, unsafe=False):
    data = bytes(range(256)) * 4
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        name = "../unsafe.xlsx" if unsafe else "case.xlsx"
        archive.writestr(name, data)
        if manifest:
            archive.writestr("manifest.json", json.dumps({
                "case_id": "CASE-1", "automation_dispatch_id": "D-001",
                "files": [{"archive_name": name, "canonical_name": "case.xlsx",
                    "file_id": "file-1", "mime_type": "application/vnd.ms-excel",
                    "size_bytes": len(data), "md5_checksum": md5(data).hexdigest(),
                    "is_latest_corrected_excel": True}],
            }))
    return buffer.getvalue()


@pytest.mark.parametrize("has_manifest", [True, False])
def test_drive_and_local_zip(tmp_path, has_manifest):
    staged = ZipIntake(tmp_path, FakeClient(make_zip(has_manifest))).stage(context())
    assert staged.file_count == 1
    assert (staged.folder / "case.xlsx").exists()
    assert staged.case_id == ("CASE-1" if has_manifest else "TEST-CASE")
    assert (staged.folder / "web_sync_manifest.json").exists()


def test_unsafe_or_corrupt_zip_never_promotes(tmp_path):
    for archive in (make_zip(unsafe=True), b"not-a-zip"):
        with pytest.raises(Exception):
            ZipIntake(tmp_path, FakeClient(archive)).stage(context())
    assert not list((tmp_path / "cases").glob("TEST-001_*"))


def test_drive_zip_wrong_dispatch_is_rejected(tmp_path):
    bad = context()
    bad = replace(bad, dispatch_id="D-WRONG")
    with pytest.raises(Exception, match="dispatch"):
        ZipIntake(tmp_path, FakeClient(make_zip())).stage(bad)


def test_outbox_starts_at_two_and_survives_lost_response(tmp_path):
    class LostResponse(FakeClient):
        def __init__(self):
            super().__init__()
            self.first = True

        def callback(self, ctx, event):
            self.events.append(dict(event))
            if self.first:
                self.first = False
                raise RemoteError("callback", 0, "response lost")
            return {"ok": True, "duplicate": True}

    client = LostResponse()
    box = outbox_module.CallbackOutbox(tmp_path / "run.json", context(), client)
    box.enqueue("running", "start")
    box.enqueue("awaiting_final_submit", "review")
    box.enqueue("completed", "submitted")
    wait_for(lambda: not box.has_pending())
    assert [x["seq"] for x in client.events] == [2, 2, 3, 4]
    assert client.events[0]["event_id"] == client.events[1]["event_id"]
    assert json.loads((tmp_path / "run.json").read_text())["acknowledged_seq"] == 4
    box.stop()


def test_callback_409_abandons_and_requests_stop(tmp_path):
    client = FakeClient()
    client.callback_error = RemoteError("callback", 409, "stale_dispatch")
    stopped = threading.Event()
    box = outbox_module.CallbackOutbox(tmp_path / "run.json", context(), client, on_stale=stopped.set)
    box.enqueue("running", "start")
    wait_for(stopped.is_set)
    assert json.loads((tmp_path / "run.json").read_text())["abandoned"] is True
    box.stop()


def test_launch_failure_releases_slot(tmp_path):
    client = FakeClient()
    client.redeem_error = RemoteError("redeem", 410, "expired")
    coordinator = RunCoordinator(tmp_path, client=client)
    with pytest.raises(RemoteError):
        coordinator.start(StartRequest.parse(start_body()))
    assert coordinator.active is None


def test_one_active_run_and_matching_stop(tmp_path):
    class SlowIntake:
        def __init__(self):
            self.entered = threading.Event()

        def stage(self, _context, stop_requested):
            self.entered.set()
            while not stop_requested():
                time.sleep(.01)
            raise InterruptedError("stopped")

    client = FakeClient()
    intake = SlowIntake()
    coordinator = RunCoordinator(tmp_path, client=client, intake=intake)
    request = StartRequest.parse(start_body())
    assert coordinator.start(request) == "accepted"
    wait_for(intake.entered.is_set)
    assert coordinator.start(request) == "accepted"
    with pytest.raises(BusyError):
        coordinator.start(StartRequest.parse(start_body(run_id="TEST-002")))
    with pytest.raises(BusyError):
        coordinator.stop("OTHER", "D-001")
    assert coordinator.stop("TEST-001", "D-001") == "accepted"
    wait_for(lambda: coordinator.active is None)
    wait_for(lambda: any(event["status"] == "stopped" for event in client.events))


def test_duplicate_start_after_run_finished_never_redeems_again(tmp_path):
    class StoppedIntake:
        def stage(self, _context, _stop_requested):
            raise InterruptedError("stopped")

    client = FakeClient()
    coordinator = RunCoordinator(tmp_path, client=client, intake=StoppedIntake())
    request = StartRequest.parse(start_body())
    coordinator.start(request)
    wait_for(lambda: coordinator.active is None)
    client.redeem_error = AssertionError("duplicate run must not redeem again")
    assert coordinator.start(request) == "accepted"
    with pytest.raises(BusyError):
        coordinator.start(StartRequest.parse(start_body(dispatch_id="D-002")))


def test_recovery_marks_interrupted_run_failed_without_repeating_portal(tmp_path):
    client = FakeClient()
    box = outbox_module.CallbackOutbox(tmp_path / "runs" / "old.json", context(), client)
    box.enqueue("running", "browser active")
    wait_for(lambda: not box.has_pending())
    box.stop()
    restarted = RunCoordinator(tmp_path, client=client)
    wait_for(lambda: any(e["status"] == "failed" for e in client.events))
    assert "restarted" in client.events[-1]["message"]
    for recovered in restarted.recovered_outboxes:
        recovered.stop()


def test_manual_submit_is_only_completed_boundary(tmp_path):
    from app.helper_v1.intake import PreparedCase

    class Intake:
        def stage(self, _ctx, _stop):
            return PreparedCase(tmp_path, "CASE-1", "case.xlsx", 1)

    class Prepared:
        claim = object()

    class Engine:
        def request_stop(self):
            pass

    class Adapter:
        def run(self, _ctx, _staged, _progress, review, submission, set_engine, _stop):
            set_engine(Engine())
            review()
            submission({"automation_dispatch_id": "D-001", "confirmed_success": True,
                        "portal_message": "Submitted successfully"})
            return type("Result", (), {"success": True, "message": "done"})()

    client = FakeClient()
    coordinator = RunCoordinator(tmp_path, client=client, intake=Intake(),
                                 prepare=lambda staged, stopped: Prepared(), adapter=Adapter())
    coordinator.start(StartRequest.parse(start_body()))
    wait_for(lambda: coordinator.active is None)
    wait_for(lambda: client.events and client.events[-1]["status"] == "completed")
    statuses = [e["status"] for e in client.events]
    assert statuses[0] == "running"
    assert statuses[-2:] == ["awaiting_final_submit", "completed"]
    assert [e["seq"] for e in client.events] == list(range(2, len(client.events) + 2))


def test_browser_closed_without_confirmed_submit_is_failed(tmp_path):
    from app.helper_v1.intake import PreparedCase

    class Intake:
        def stage(self, _ctx, _stop):
            return PreparedCase(tmp_path, "CASE-1", "case.xlsx", 1)

    class Adapter:
        def run(self, _ctx, _staged, _progress, review, _submission, _engine, _stop):
            review()
            return type("Result", (), {"success": True, "message": "Automation finished"})()

    client = FakeClient()
    coordinator = RunCoordinator(tmp_path, client=client, intake=Intake(),
                                 prepare=lambda staged, stopped: type("Ready", (), {"claim": object()})(),
                                 adapter=Adapter())
    coordinator.start(StartRequest.parse(start_body()))
    wait_for(lambda: coordinator.active is None)
    wait_for(lambda: client.events and client.events[-1]["status"] == "failed")
    assert "before a confirmed manual Final Submit" in client.events[-1]["message"]


def test_uiic_adapter_uses_redeemed_credentials_and_visible_browser(monkeypatch, tmp_path):
    from app.helper_v1 import portal
    from app.helper_v1.intake import PreparedCase

    captured = {}
    class Engine:
        def __init__(self, portal_id, log_cb, step_cb):
            captured["portal"] = portal_id
            self.step_cb = step_cb

        async def run_automation(self, claim, settings):
            captured["settings"] = settings
            self.step_cb(5, "Complete")
            return type("Result", (), {"success": True})()

    monkeypatch.setattr(portal, "AutomationEngine", Engine)
    monkeypatch.setattr(portal, "load_settings", lambda portal_id: {"username": "old", "password": "old"})
    staged = PreparedCase(tmp_path, "CASE-1", "case.xlsx", 1)
    staged.claim = object()
    reviewed = []
    portal.UiicAdapter().run(context(), staged, lambda _: None, lambda: reviewed.append(True),
                             lambda _: None, lambda _: None, lambda: False)
    assert captured["portal"] == "uiic"
    assert captured["settings"]["username"] == "tester"
    assert captured["settings"]["password"] == "test-password"
    assert captured["settings"]["browser_headless"] is False
    assert captured["settings"]["_web_submission"]["case_id"] == "CASE-1"
    assert reviewed == [True]


def test_http_ping_preflight_and_bad_commands(tmp_path):
    coordinator = RunCoordinator(tmp_path, client=FakeClient())
    server = HelperServer(coordinator, ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def call(method, path, data=None, origin=ORIGIN, extra=None):
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            headers = {"Origin": origin, "Content-Type": "application/json", **(extra or {})}
            connection.request(method, path, json.dumps(data).encode() if data is not None else None, headers)
            response = connection.getresponse()
            payload = response.read()
            status = response.status
            headers = dict(response.getheaders())
            connection.close()
            return status, payload, headers

        status, _, headers = call("OPTIONS", "/v1/start", extra={
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
            "Access-Control-Request-Private-Network": "true"})
        assert status == 204 and headers["Access-Control-Allow-Private-Network"] == "true"
        status, payload, _ = call("POST", "/ping", {"command": "PING"})
        assert status == 200 and json.loads(payload)["contract_version"] == 1
        assert call("POST", "/v1/start", start_body(contract_version=2))[0] == 400
        assert call("POST", "/v1/stop", {"command": "STOP_RUN", "contract_version": 1,
            "run_id": "bad", "dispatch_id": "bad"})[0] == 409
        assert call("POST", "/ping", {"command": "PING"}, origin="https://evil.example")[0] == 403
    finally:
        server.shutdown()
        server.server_close()
