"""Receipt-only handoff uses a verified local Ready case."""
import hashlib
import json
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

from app.web_sync.client import ApiError, Client
from app.web_sync import page as page_module
from app.web_sync.storage import CaseRepository, atomic_json


JOB = {
    "case_id": "receipt-test-case",
    "case_ref": "TEST/RECEIPT/1",
    "automation_dispatch_id": "dispatch-1",
    "vehicle_no": "PB00AA0001",
    "insurer": "United India",
    "portal_id": "uiic",
    "surveyor_profile_id": "surveyor-1",
    "status": "queued_for_automation",
}


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


class ReceiptClient:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.receipts = []
        self.queue_warning = ""

    def acknowledge_receipt(self, case_id, dispatch_id, receipt_status="received"):
        self.receipts.append((case_id, dispatch_id, receipt_status))
        outcome = self.outcomes.pop(0) if self.outcomes else False
        if isinstance(outcome, Exception):
            raise outcome
        return {
            "ok": True, "case_id": case_id,
            "automation_dispatch_id": dispatch_id,
            "receipt_status": receipt_status,
            **({"app3_received_at": "2026-09-26T10:00:00Z"} if receipt_status == "received" else {}),
            "duplicate": outcome,
        }

    def claim(self, *_):
        raise AssertionError("receipt_v1 must not claim")

    def report(self, *_):
        raise AssertionError("receipt_v1 must not report portal results")

    def close(self):
        pass


def make_page(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(page_module.WebQueuePage, "restore_login", lambda _self: None)
    started = []
    window = SimpleNamespace(
        _worker=None, _scan_thread=None, _claim=None,
        _open_web_case=lambda record: None,
        _start_automation=lambda: started.append("started"),
        _stop_automation=lambda: None,
    )
    page = page_module.WebQueuePage(window, tmp_path)
    page.timer.stop()
    page.client = ReceiptClient()
    page.jobs = [dict(JOB)]
    return page, window, started


def ready_folder(tmp_path, dispatch_id="dispatch-1"):
    folder = tmp_path / "cases" / "UIIC" / "receipt-test-case"
    folder.mkdir(parents=True, exist_ok=True)
    workbook = b"locally verified workbook"
    (folder / "corrected_claim.xlsx").write_bytes(workbook)
    atomic_json(folder / "web_sync_manifest.json", {
        "case_id": JOB["case_id"],
        "automation_dispatch_id": dispatch_id,
        "complete": True,
        "latest_excel": "corrected_claim.xlsx",
        "files": [{
            "file_id": "excel-1", "local_name": "corrected_claim.xlsx",
            "size_bytes": len(workbook),
            "md5_checksum": hashlib.md5(workbook).hexdigest(),
            "is_latest_corrected_excel": True,
        }],
    })
    return folder


def stage_ready(page, tmp_path):
    folder = ready_folder(tmp_path)
    page.case_repo.upsert(
        JOB["case_id"], job=dict(JOB), handoff_mode="receipt_v1",
        automation_dispatch_id=JOB["automation_dispatch_id"],
        folder=str(folder), portal="uiic", latest_excel="corrected_claim.xlsx",
        local_status="staging", phase="staging",
    )
    page.staging_ids.add(JOB["case_id"])
    page.staging_dispatches[JOB["case_id"]] = JOB["automation_dispatch_id"]
    page._staging_completed(JOB["case_id"], {
        "folder": str(folder), "latest_excel": "corrected_claim.xlsx",
        "automation_dispatch_id": JOB["automation_dispatch_id"],
    }, None)
    return folder


def immediate_network(page):
    def run(operation, function):
        page.busy = True
        try:
            value, error = function(), None
        except Exception as exc:
            value, error = None, exc
        page._completed(operation, value, error)
    page.run_task = run


def test_receipt_client_requires_exact_ack_and_accepts_duplicate():
    class Response:
        status_code = 200
        headers = {}
        def __init__(self, payload):
            self.payload = payload
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.payload = {}
            self.calls = []
        def post(self, url, **kwargs):
            self.calls.append((url, kwargs["json"]))
            return Response(self.payload)

    session = Session()
    client = Client("operator@example.invalid", "not-used", session=session)
    client.token = "test-token"
    session.payload = {
        "ok": True, "case_id": "c", "automation_dispatch_id": "d",
        "receipt_status": "received", "app3_received_at": "2026-09-26T10:00:00Z",
        "duplicate": True,
    }
    assert client.acknowledge_receipt("c", "d")["duplicate"] is True
    assert session.calls[-1][0].endswith("/functions/acknowledgeApp3Receipt")
    assert session.calls[-1][1] == {"case_id": "c", "automation_dispatch_id": "d", "receipt_status": "received"}
    session.payload = {
        "ok": True, "case_id": "c", "automation_dispatch_id": "d",
        "receipt_status": "failed", "duplicate": False,
    }
    assert client.acknowledge_receipt("c", "d", "failed")["receipt_status"] == "failed"
    assert session.calls[-1][1] == {"case_id": "c", "automation_dispatch_id": "d", "receipt_status": "failed"}
    session.payload = {**session.payload, "automation_dispatch_id": "wrong"}
    with pytest.raises(ValueError, match="did not match"):
        client.acknowledge_receipt("c", "d")


def test_ready_precedes_receipt_and_ack_evidence_is_safe(qapp, tmp_path, monkeypatch):
    page, _, _ = make_page(qapp, tmp_path, monkeypatch)
    try:
        folder = stage_ready(page, tmp_path)
        record = page._record(JOB["case_id"])
        assert record["local_status"] == "ready"
        assert record["receipt_pending"] is True
        assert not page.client.receipts
        immediate_network(page)
        page._send_pending_receipt()
        record = page._record(JOB["case_id"])
        assert record["receipt_acknowledged"] is True
        assert record["receipt_pending"] is False
        assert record["local_status"] == "ready"
        evidence = json.loads((folder / "App3_Receipt_Acknowledgement.json").read_text())
        assert evidence["automation_dispatch_id"] == JOB["automation_dispatch_id"]
        assert set(evidence) == {"case_id", "automation_dispatch_id", "app3_received_at", "receipt_status", "duplicate"}
    finally:
        page.shutdown()
        page.close()


def test_lost_response_retries_same_dispatch_after_restart(qapp, tmp_path, monkeypatch):
    page, _, _ = make_page(qapp, tmp_path, monkeypatch)
    try:
        stage_ready(page, tmp_path)
        page.client = ReceiptClient([ApiError(503, "acknowledgeApp3Receipt")])
        immediate_network(page)
        page._send_pending_receipt()
        assert page._record(JOB["case_id"])["receipt_pending"] is True
        assert page._record(JOB["case_id"])["local_status"] == "ready"
    finally:
        page.shutdown()
        page.close()
    restarted, _, _ = make_page(qapp, tmp_path, monkeypatch)
    try:
        restarted.client = ReceiptClient([True])
        immediate_network(restarted)
        assert restarted._record(JOB["case_id"])["receipt_pending"] is True
        restarted._send_pending_receipt()
        assert restarted.client.receipts == [(JOB["case_id"], JOB["automation_dispatch_id"], "received")]
        assert restarted._record(JOB["case_id"])["receipt_acknowledged"] is True
    finally:
        restarted.shutdown()
        restarted.close()


def test_stale_receipt_disables_start(qapp, tmp_path, monkeypatch):
    page, _, started = make_page(qapp, tmp_path, monkeypatch)
    try:
        stage_ready(page, tmp_path)
        page.client = ReceiptClient([ApiError(409, "acknowledgeApp3Receipt", "stale_dispatch")])
        immediate_network(page)
        page._send_pending_receipt()
        record = page._record(JOB["case_id"])
        assert record["local_status"] == "stale/replaced"
        assert record["receipt_pending"] is False
        page.refresh()
        page.start_automation_by_index(0)
        assert not started
    finally:
        page.shutdown()
        page.close()


def test_corrupted_local_file_prevents_receipt(qapp, tmp_path, monkeypatch):
    page, _, _ = make_page(qapp, tmp_path, monkeypatch)
    try:
        folder = stage_ready(page, tmp_path)
        original = (folder / "corrected_claim.xlsx").read_bytes()
        (folder / "corrected_claim.xlsx").write_bytes(b"X" * len(original))
        immediate_network(page)
        page._send_pending_receipt()
        record = page._record(JOB["case_id"])
        assert record["local_status"] == "needs attention"
        assert record["receipt_pending"] is False
        assert "checksum" in record["receipt_last_error"]
        assert not page.client.receipts
    finally:
        page.shutdown()
        page.close()


def test_exhausted_stage_failure_cleans_partial_and_shows_one_popup(qapp, tmp_path, monkeypatch):
    page, _, _ = make_page(qapp, tmp_path, monkeypatch)
    popups = []
    monkeypatch.setattr(page_module.QMessageBox, "warning", lambda _parent, title, message: popups.append((title, message)))
    try:
        folder = tmp_path / "cases" / "UIIC" / "failed-case"
        partial_id = hashlib.sha256(
            f"{JOB['case_id']}:{JOB['automation_dispatch_id']}".encode("utf-8")
        ).hexdigest()[:16]
        temporary = folder.parent / f"{folder.name}.staging.{partial_id}"
        temporary.mkdir(parents=True)
        (temporary / "case.zip.download").write_bytes(b"partial")
        folder.mkdir()
        (folder / "case_activity.log").write_text("download started\n", encoding="utf-8")
        page.case_repo.upsert(JOB["case_id"], job=dict(JOB),
                              handoff_mode="receipt_v1", portal="uiic", folder=str(folder),
                              automation_dispatch_id=JOB["automation_dispatch_id"],
                              local_status="staging", phase="staging")
        page.staging_dispatches[JOB["case_id"]] = JOB["automation_dispatch_id"]
        page._staging_completed(JOB["case_id"], None, TimeoutError("ZIP and fallback exhausted"))
        assert page._record(JOB["case_id"])["local_status"] == "stage failed"
        assert not temporary.exists()
        assert not folder.exists()
        assert page.list.count() == 0
        assert len(popups) == 1
        assert not page.client.receipts
        assert page._record(JOB["case_id"])["receipt_pending"] is True
        assert page._record(JOB["case_id"])["receipt_status"] == "failed"
        page._maybe_auto_pickup()
        assert not page.staging_ids
        assert len(popups) == 1
        immediate_network(page)
        page._send_pending_receipt()
        assert page.client.receipts == [(JOB["case_id"], JOB["automation_dispatch_id"], "failed")]
        assert page._record(JOB["case_id"])["receipt_acknowledged"] is True
    finally:
        page.shutdown()
        page.close()


def test_old_failed_dispatch_folder_is_removed_without_losing_receipt_state(qapp, tmp_path, monkeypatch):
    folder = tmp_path / "cases" / "UIIC" / "old-incomplete-case"
    folder.mkdir(parents=True)
    (folder / "case_activity.log").write_text("old failure\n", encoding="utf-8")
    CaseRepository(tmp_path / "state").upsert(
        JOB["case_id"], job=dict(JOB), folder=str(folder),
        automation_dispatch_id=JOB["automation_dispatch_id"],
        local_status="stage failed", phase="stage failed",
        receipt_status="failed", receipt_pending=True,
    )
    page, _, _ = make_page(qapp, tmp_path, monkeypatch)
    try:
        record = page._record(JOB["case_id"])
        assert not folder.exists()
        assert record["folder"] == ""
        assert record["receipt_pending"] is True
        assert page.list.count() == 0
    finally:
        page.shutdown()
        page.close()


def test_new_dispatch_resets_old_receipt_without_claiming(qapp, tmp_path, monkeypatch):
    page, _, _ = make_page(qapp, tmp_path, monkeypatch)
    try:
        old_folder = stage_ready(page, tmp_path)
        (old_folder / "Portal_Submission_Result.json").write_text("old dispatch evidence", encoding="utf-8")
        page.case_repo.upsert(JOB["case_id"], receipt_pending=False,
                              receipt_acknowledged=True, receipt_acknowledged_at="old-time")
        page.jobs = [{**JOB, "automation_dispatch_id": "dispatch-2"}]
        page._reconcile_jobs()
        record = page._record(JOB["case_id"])
        assert record["automation_dispatch_id"] == "dispatch-2"
        assert record["handoff_mode"] == "receipt_v1"
        assert not record["receipt_acknowledged"]
        assert not record["receipt_pending"]
        assert record["folder"] == ""
        assert record["previous_dispatch_folders"][-1] == {
            "automation_dispatch_id": "dispatch-1", "folder": str(old_folder),
        }
        assert (old_folder / "Portal_Submission_Result.json").read_text(encoding="utf-8") == "old dispatch evidence"
    finally:
        page.shutdown()
        page.close()


def test_resend_uses_separate_folder_and_keeps_old_evidence(qapp, tmp_path, monkeypatch):
    page, _, _ = make_page(qapp, tmp_path, monkeypatch)
    try:
        old_folder = stage_ready(page, tmp_path)
        (old_folder / "Portal_Submission_Result.json").write_text("old evidence", encoding="utf-8")
        new_job = {**JOB, "automation_dispatch_id": "dispatch-2"}
        page.jobs = [new_job]
        page._reconcile_jobs()

        class InlineExecutor:
            def submit(self, function):
                future = Future()
                try:
                    future.set_result(function())
                except Exception as exc:
                    future.set_exception(exc)
                return future
            def shutdown(self, **_):
                pass

        page.stage_pool.shutdown(wait=False, cancel_futures=True)
        page.stage_pool = InlineExecutor()

        def download(_client, case_id, folder, *, progress, automation_dispatch_id):
            workbook = b"new dispatch workbook"
            (folder / "corrected_claim.xlsx").write_bytes(workbook)
            atomic_json(folder / "web_sync_manifest.json", {
                "case_id": case_id, "automation_dispatch_id": automation_dispatch_id,
                "latest_excel": "corrected_claim.xlsx", "complete": True,
                "files": [{"local_name": "corrected_claim.xlsx", "size_bytes": len(workbook),
                           "md5_checksum": hashlib.md5(workbook).hexdigest()}],
            })
            return "corrected_claim.xlsx"

        monkeypatch.setattr(page_module, "download_case", download)
        page._stage_case(new_job)
        new_folder = Path(page._record(JOB["case_id"])["folder"])
        assert new_folder != old_folder
        assert new_folder.is_dir()
        assert old_folder.is_dir()
        assert (old_folder / "Portal_Submission_Result.json").read_text(encoding="utf-8") == "old evidence"
        assert not (new_folder / "Portal_Submission_Result.json").exists()
    finally:
        page.shutdown()
        page.close()


@pytest.mark.parametrize("portal", ["uiic", "newindia", "oic"])
def test_start_uses_portal_settings_only_and_never_claims(qapp, tmp_path, monkeypatch, portal):
    page, window, started = make_page(qapp, tmp_path, monkeypatch)
    try:
        folder = stage_ready(page, tmp_path)
        job = {**JOB, "portal_id": portal}
        page.jobs = [job]
        page.case_repo.upsert(JOB["case_id"], job=job, portal=portal)
        page.store.save(JOB["surveyor_profile_id"], portal, "surveyor-user", "surveyor-password", "surveyor-code")
        monkeypatch.setattr(page_module, "load_settings", lambda portal_id=None: {
            "username": f"{portal_id}-settings-user", "password": "settings-password",
            "surveyor_code": "settings-code",
        })
        monkeypatch.setattr(page_module, "get_active_portal_id", lambda: portal)
        window._claim = SimpleNamespace(_scan_context=SimpleNamespace(claim_folder_path=str(folder), portal_id=portal))
        page.workspace_scan_completed(str(folder), True)
        page.refresh()
        assert page.start_automation() is True
        assert started == ["started"]
        assert page.settings_for(str(folder), portal)["username"] == f"{portal}-settings-user"
        page._submission({"case_id": JOB["case_id"], "portal_message": "DL pending", "confirmed_success": False})
        assert page.state.current is not None
        page._submission({"case_id": JOB["case_id"], "portal_message": "Report submitted successfully", "confirmed_success": True})
        assert page.state.current is None
        assert page._record(JOB["case_id"])["local_status"] == "submitted successfully"
    finally:
        page.shutdown()
        page.close()


def test_missing_settings_credentials_block_local_start(qapp, tmp_path, monkeypatch):
    page, window, started = make_page(qapp, tmp_path, monkeypatch)
    try:
        folder = stage_ready(page, tmp_path)
        page.store.save(JOB["surveyor_profile_id"], "uiic", "surveyor-user", "surveyor-password", "")
        monkeypatch.setattr(page_module, "load_settings", lambda portal_id=None: {})
        monkeypatch.setattr(page_module, "get_active_portal_id", lambda: "uiic")
        window._claim = SimpleNamespace(_scan_context=SimpleNamespace(claim_folder_path=str(folder), portal_id="uiic"))
        page.workspace_scan_completed(str(folder), True)
        page.refresh()
        assert page.start_automation() is False
        assert "configure" in page.result.text().lower()
        assert not started
    finally:
        page.shutdown()
        page.close()


def test_browser_close_without_final_submit_is_local_retry(qapp, tmp_path, monkeypatch):
    page, window, started = make_page(qapp, tmp_path, monkeypatch)
    try:
        folder = stage_ready(page, tmp_path)
        monkeypatch.setattr(page_module, "load_settings", lambda portal_id=None: {
            "username": "settings-user", "password": "settings-password",
        })
        monkeypatch.setattr(page_module, "get_active_portal_id", lambda: "uiic")
        window._claim = SimpleNamespace(_scan_context=SimpleNamespace(claim_folder_path=str(folder), portal_id="uiic"))
        page.workspace_scan_completed(str(folder), True)
        page.refresh()
        assert page.start_automation()
        assert started == ["started"]
        page.automation_finished(True, "Browser closed")
        assert page.state.current is None
        assert page._record(JOB["case_id"])["local_status"] == "workspace ready"
        assert "without confirmed Final Submit" in page.result.text()
    finally:
        page.shutdown()
        page.close()


def test_receipt_mode_hides_bottom_controls(qapp, tmp_path, monkeypatch):
    assert not hasattr(Client, "claim")
    assert not hasattr(Client, "report")
    receipt, _, _ = make_page(qapp, tmp_path / "receipt", monkeypatch)
    try:
        assert not hasattr(receipt, "rail_actions")
        assert receipt.handoff_mode == "receipt_v1"
    finally:
        receipt.shutdown()
        receipt.close()
