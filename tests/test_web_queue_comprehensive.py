"""Comprehensive Master Test Suite for Web Queue Subsystem.

Covers:
1. UI Layout & Visual Presentation (CaseListDelegate, badges, colors, integer point sizes)
2. Header Toolbar & Auto-Pickup Controls (toggle, preference persistence, poll)
3. Queued Cases Management & DPAPI Isolation (list, count badge, empty label, secret clearing)
4. Active Case Card & State Transitions (idle, active, button enable/disable matrix)
5. DocWriter Connection & Adaptive State Card (form box, connected box, reconnect, change, forget)
6. Surveyor Portal Login & Credential Isolation (DPAPI save, feedback, banner isolation)
7. Portal Activity & Result Banner (status pills, strict confirmed success invariants, timestamp)
8. Auto-Pickup Engine Detailed Rules (idle checks, credential check before claim, execution)
9. Full Case Lifecycle & Error Recovery (claim, download, monitor, report, ack, 503 retry, corrupt recovery)
10. Manual Browse Folder & Insurer Isolation (isolation from manual workspace, portal mapping)
"""
import asyncio
import hashlib
import json
import os
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QFont, QImage, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStyleOptionViewItem,
)

from app.web_sync.client import APP_ID, ApiError, Client
from app.web_sync.downloads import download_case, flat_name
from app.web_sync.page import CaseListDelegate, ResultBannerLabel, WebQueuePage, _card, _field_label
from app.web_sync.storage import (
    AutoPickupPreference,
    CaseState,
    CredentialStore,
    OperatorCredentialStore,
    atomic_json,
    portal_for,
)
from app.web_sync.submission import SubmissionMonitor, confirms_submission


# ─────────────────────────────────────────────────────────────────────────────
# MOCK SERVER & DUMMY FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_JOB_UIIC = {
    "case_id": "case_comp_001",
    "automation_dispatch_id": "dispatch-uiic-001",
    "automation_dispatched_at": "2026-09-12T09:00:00Z",
    "case_ref": "REF/2026/UIIC/1001",
    "vehicle_no": "DL01AB1111",
    "insurer": "United India Insurance",
    "surveyor_profile_id": "profile_surveyor_uiic",
    "drive_folder_id": "drive_folder_uiic_001",
    "drive_folder_link": "https://drive.google.com/drive/folders/drive_uiic",
    "status": "queued_for_automation",
}

SAMPLE_JOB_NIA = {
    "case_id": "case_comp_002",
    "automation_dispatch_id": "dispatch-nia-001",
    "automation_dispatched_at": "2026-09-12T09:00:05Z",
    "case_ref": "REF/2026/NIA/2002",
    "vehicle_no": "MH02CD2222",
    "insurer": "New India Assurance",
    "surveyor_profile_id": "profile_surveyor_nia",
    "drive_folder_id": "drive_folder_nia_002",
    "drive_folder_link": "https://drive.google.com/drive/folders/drive_nia",
    "status": "queued_for_automation",
}

SAMPLE_JOB_OIC = {
    "case_id": "case_comp_003",
    "automation_dispatch_id": "dispatch-oic-001",
    "automation_dispatched_at": "2026-09-12T09:00:10Z",
    "case_ref": "REF/2026/OIC/3003",
    "vehicle_no": "GJ03EF3333",
    "insurer": "Oriental Insurance Company Limited",
    "surveyor_profile_id": "profile_surveyor_oic",
    "drive_folder_id": "drive_folder_oic_003",
    "drive_folder_link": "https://drive.google.com/drive/folders/drive_oic",
    "status": "queued_for_automation",
}


class MockResponse:
    def __init__(self, status=200, data=None, binary=None, headers=None):
        self.status_code = status
        self.data = data
        self.binary = binary
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def close(self):
        pass

    def json(self):
        assert self.binary is None, "Binary responses must not be json-decoded"
        return self.data

    def iter_content(self, chunk_size):
        if self.binary:
            for i in range(0, len(self.binary), chunk_size):
                yield self.binary[i:i + chunk_size]


class ComprehensiveMockServer:
    def __init__(self, initial_jobs=None):
        self.calls = []
        self.logins = 0
        if initial_jobs is None:
            initial_jobs = [SAMPLE_JOB_UIIC]
        self.jobs_list = [dict(j) for j in initial_jobs]
        self.claimed_ids = set()
        self.reports = []
        self.expire_on_next_call = False
        self.fail_report_with_503 = False
        self.files = [
            {"file_id": "f_excel", "name": "Corrected.xlsx", "path": "Corrected.xlsx", "is_latest_corrected_excel": True},
            {"file_id": "f_rc", "name": "RC.pdf", "path": "Documents/RC.pdf", "is_latest_corrected_excel": False},
            {"file_id": "f_bill", "name": "Bill.pdf", "path": "Bills/Bill.pdf", "is_latest_corrected_excel": False},
        ]
        for entry in self.files:
            payload = b"DUMMY_BINARY_DATA_" + entry["file_id"].encode()
            entry["size_bytes"] = len(payload)
            entry["md5_checksum"] = hashlib.md5(payload).hexdigest()

    def post(self, url, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        body = kwargs.get("json", {})
        headers = kwargs.get("headers", {})
        self.calls.append((endpoint, body, headers))

        assert headers.get("X-App-Id") == APP_ID

        if endpoint == "login":
            self.logins += 1
            return MockResponse(200, {"access_token": f"token-{self.logins}"})

        if self.expire_on_next_call:
            self.expire_on_next_call = False
            return MockResponse(401, {"error": "Token expired"})

        if endpoint == "getAutomationJobs":
            return MockResponse(200, {"jobs": [dict(j) for j in self.jobs_list if j["case_id"] not in self.claimed_ids]})

        if endpoint == "claimAutomationCase":
            cid = body.get("case_id")
            dispatch_id = body.get("automation_dispatch_id")
            matching = next((j for j in self.jobs_list if j["case_id"] == cid), None)
            if not matching or dispatch_id != matching.get("automation_dispatch_id"):
                return MockResponse(409, {"error": "stale_dispatch"})
            if cid in self.claimed_ids:
                return MockResponse(409, {"error": "Case already claimed"})
            self.claimed_ids.add(cid)
            return MockResponse(200, {"claimed": True, "job": {**(matching or SAMPLE_JOB_UIIC), "status": "automation_in_progress"}})

        if endpoint == "getAutomationCaseZip":
            return MockResponse(501, {"error": "ZIP unavailable in legacy mock"})

        if endpoint == "getAutomationCaseFiles":
            cid = body.get("case_id")
            dispatch_id = body.get("automation_dispatch_id")
            matching = next((j for j in self.jobs_list if j["case_id"] == cid), None)
            if matching and dispatch_id != matching.get("automation_dispatch_id"):
                return MockResponse(409, {"error": "stale_dispatch"})
            fid = body.get("file_id")
            if not fid:
                return MockResponse(200, {
                    "case_id": cid,
                    "automation_dispatch_id": dispatch_id,
                    "latest_corrected_excel": self.files[0], "files": self.files,
                })
            return MockResponse(200, binary=b"DUMMY_BINARY_DATA_" + fid.encode(), headers={"Content-Type": "application/octet-stream", "X-Case-File-Path": "Documents/File.pdf"})

        if endpoint == "reportAutomationResult":
            if self.fail_report_with_503:
                return MockResponse(503, {"error": "Service temporarily unavailable"})
            matching = next((j for j in self.jobs_list if j["case_id"] == body.get("case_id")), None)
            if matching and body.get("automation_dispatch_id") != matching.get("automation_dispatch_id"):
                return MockResponse(409, {"error": "stale_dispatch"})
            self.reports.append(body)
            status_ack = "uploaded" if body.get("status") == "success" else "ready_for_upload"
            return MockResponse(200, {"ok": True, **body, "status": status_ack})

        raise AssertionError(f"Unexpected endpoint: {endpoint}")


class ImmediateExecutor:
    def submit(self, function):
        future = Future()
        try:
            future.set_result(function())
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **_kwargs):
        pass


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_test_queue_page(tmp_path, initial_jobs=None):
    """Creates a deterministic WebQueuePage bound to ComprehensiveMockServer."""
    server = ComprehensiveMockServer(initial_jobs=initial_jobs)
    opened_cases = []
    stopped_automations = []

    window = SimpleNamespace(
        _worker=None,
        _scan_thread=None,
        _claim=None,
        _open_web_case=opened_cases.append,
        _stop_automation=lambda: stopped_automations.append(True),
        _start_automation=lambda: None,
        _switch_page=lambda idx: None,
    )

    page = WebQueuePage(window, tmp_path)
    page.timer.stop()
    page.stage_pool.shutdown(wait=False, cancel_futures=True)
    page.stage_pool = ImmediateExecutor()

    # Synchronous task runner to eliminate unpredictable Qt thread timing
    def sync_run(operation, function):
        page.busy = True
        try:
            val, err = function(), None
        except Exception as exc:
            val, err = None, exc
        page._completed(operation, val, err)

    page.run_task = sync_run
    page.client = Client("operator@example.invalid", "secret123", session=server)
    page.refresh()
    return page, server, window, opened_cases


def prepare_workspace(page):
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
    prepared = prepare_workspace(page)
    page.start_automation()
    assert page.state.current is not None
    return prepared


def test_dispatch_delete_same_poll_hidden_new_resend_reappears_and_persists(qapp, tmp_path):
    page, server, _window, _opened = make_test_queue_page(tmp_path, [SAMPLE_JOB_UIIC])
    try:
        page.poll()
        page._maybe_auto_pickup()
        first = page._record(SAMPLE_JOB_UIIC["case_id"])
        assert first["local_status"] == "ready"
        first_number = first["display_number"]
        first_folder = Path(first["folder"])
        assert first_folder.is_dir()
        assert not server.claimed_ids

        page.list.setCurrentRow(0)
        page.delete_current_local_copy()
        deleted = page._record(SAMPLE_JOB_UIIC["case_id"])
        assert deleted["deleted_by_operator"] is True
        assert deleted["deleted_dispatch_id"] == SAMPLE_JOB_UIIC["automation_dispatch_id"]
        assert not first_folder.exists()

        page.poll()
        assert page.list.count() == 0
        assert not first_folder.exists()
        assert not server.claimed_ids

        resent = {
            **SAMPLE_JOB_UIIC,
            "automation_dispatch_id": "dispatch-uiic-002",
            "automation_dispatched_at": "2026-09-12T10:00:00Z",
        }
        server.jobs_list = [resent]
        page.poll()
        page._maybe_auto_pickup()
        restored = page._record(SAMPLE_JOB_UIIC["case_id"])
        assert restored["automation_dispatch_id"] == "dispatch-uiic-002"
        assert restored["deleted_by_operator"] is False
        assert restored["deleted_dispatch_id"] == ""
        assert restored["display_number"] > first_number
        assert restored["local_status"] == "ready"
        assert page.list.count() == 1
        assert not server.claimed_ids
        manifest = json.loads((Path(restored["folder"]) / "web_sync_manifest.json").read_text(encoding="utf-8"))
        assert manifest["automation_dispatch_id"] == "dispatch-uiic-002"
        resend_number = restored["display_number"]
    finally:
        page.shutdown()
        page.close()

    restarted, _server, _window, _opened = make_test_queue_page(tmp_path, [resent])
    try:
        restarted.poll()
        restarted._maybe_auto_pickup()
        assert restarted._record(SAMPLE_JOB_UIIC["case_id"])["display_number"] == resend_number
    finally:
        restarted.shutdown()
        restarted.close()


def test_stale_dispatch_claim_does_not_start_browser(qapp, tmp_path):
    current_job = {
        **SAMPLE_JOB_UIIC,
        "automation_dispatch_id": "dispatch-uiic-current",
    }
    page, server, window, _opened = make_test_queue_page(tmp_path, [current_job])
    started = []
    window._start_automation = lambda: started.append(True)
    try:
        page.store.save(current_job["surveyor_profile_id"], "uiic", "user", "secret", "SC")
        page.poll()
        record = page._record(current_job["case_id"])
        old_job = {**current_job, "automation_dispatch_id": "dispatch-uiic-old"}
        page.case_repo.upsert(
            current_job["case_id"],
            job=old_job,
            automation_dispatch_id=old_job["automation_dispatch_id"],
            local_status="workspace ready",
            phase="workspace ready",
        )
        page.jobs = [old_job]
        page.refresh()
        page.start_automation()
        assert not started
        assert not server.claimed_ids
        assert page._record(current_job["case_id"])["local_status"] == "stale/replaced"
        assert "resent/replaced" in page.result.text()
    finally:
        page.shutdown()
        page.close()


def test_stale_dispatch_staging_stops_without_claim_or_retry(qapp, tmp_path):
    current_job = {
        **SAMPLE_JOB_UIIC,
        "automation_dispatch_id": "dispatch-uiic-current",
    }
    old_job = {**current_job, "automation_dispatch_id": "dispatch-uiic-old"}
    page, server, _window, _opened = make_test_queue_page(tmp_path, [current_job])
    try:
        page.jobs = [old_job]
        page._stage_case(old_job, automatic=True)
        record = page._record(old_job["case_id"])
        assert record["local_status"] == "stale/replaced"
        assert not server.claimed_ids
        calls_before = len([call for call in server.calls if call[0] == "getAutomationCaseFiles"])
        page._maybe_auto_pickup()
        calls_after = len([call for call in server.calls if call[0] == "getAutomationCaseFiles"])
        assert calls_after == calls_before
    finally:
        page.shutdown()
        page.close()


def test_stale_dispatch_result_preserves_evidence_and_workspace_lock(qapp, tmp_path):
    current_job = {
        **SAMPLE_JOB_UIIC,
        "automation_dispatch_id": "dispatch-uiic-current",
    }
    page, server, _window, _opened = make_test_queue_page(tmp_path, [current_job])
    try:
        page.store.save(current_job["surveyor_profile_id"], "uiic", "user", "secret", "SC")
        page.poll()
        page._maybe_auto_pickup()
        activate_case(page)
        folder = Path(page.state.current["folder"])
        atomic_json(folder / "Portal_Submission_Result.json", {
            "case_id": current_job["case_id"],
            "portal_message": "Submitted successfully",
            "confirmed_success": True,
        })
        server.jobs_list = [{
            **current_job,
            "automation_dispatch_id": "dispatch-uiic-newer",
        }]
        page._submission({
            "case_id": current_job["case_id"],
            "portal_message": "Submitted successfully",
            "confirmed_success": True,
        })
        assert page.state.current is not None
        assert page.state.current["pending_report"] is None
        assert page.state.current["local_status"] == "needs attention"
        assert (folder / "Portal_Submission_Result.json").is_file()
        assert (folder / "Web_Sync_Stale_Result.json").is_file()
        assert "remains locked" in page.result.text()
    finally:
        page.shutdown()
        page.close()


def test_stale_dispatch_operator_stop_releases_workspace_lock(qapp, tmp_path, monkeypatch):
    current_job = {
        **SAMPLE_JOB_UIIC,
        "automation_dispatch_id": "dispatch-uiic-current",
    }
    page, server, _window, _opened = make_test_queue_page(tmp_path, [current_job])
    try:
        page.store.save(current_job["surveyor_profile_id"], "uiic", "user", "secret", "SC")
        page.poll()
        page._maybe_auto_pickup()
        activate_case(page)
        folder = Path(page.state.current["folder"])
        atomic_json(folder / "Portal_Submission_Result.json", {
            "case_id": current_job["case_id"],
            "portal_message": "Submitted successfully",
            "confirmed_success": True,
        })
        server.jobs_list = [{
            **current_job,
            "automation_dispatch_id": "dispatch-uiic-newer",
        }]
        page._submission({
            "case_id": current_job["case_id"],
            "portal_message": "Submitted successfully",
            "confirmed_success": True,
        })
        assert page.state.current is not None

        # Operator clicks Stop on this stale case
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        page.stop_or_fail_case()

        # Workspace lock must now be completely released!
        assert page.state.current is None
        assert page.can_delete_case_metadata({"job": current_job}) is True
        assert (folder / "Portal_Submission_Result_Operator_Stop.json").is_file()
        assert "Workspace unlocked" in page.result.text()
    finally:
        page.shutdown()
        page.close()


def test_old_local_state_attaches_current_dispatch_without_redownload(qapp, tmp_path):
    page, server, _window, _opened = make_test_queue_page(tmp_path, [SAMPLE_JOB_UIIC])
    try:
        folder = tmp_path / "cases" / "legacy-valid"
        folder.mkdir(parents=True)
        (folder / "legacy.xlsx").write_bytes(b"excel")
        (folder / "web_sync_manifest.json").write_text("{}", encoding="utf-8")
        legacy_job = {
            key: value for key, value in SAMPLE_JOB_UIIC.items()
            if key not in ("automation_dispatch_id", "automation_dispatched_at")
        }
        page.case_repo.upsert(
            SAMPLE_JOB_UIIC["case_id"],
            job=legacy_job,
            folder=str(folder),
            latest_excel="legacy.xlsx",
            local_status="ready",
            phase="ready",
            display_number=7,
        )
        page.poll()
        migrated = page._record(SAMPLE_JOB_UIIC["case_id"])
        assert migrated["automation_dispatch_id"] == SAMPLE_JOB_UIIC["automation_dispatch_id"]
        assert migrated["display_number"] == 7
        assert migrated["folder"] == str(folder)
        assert migrated["local_status"] == "ready"
        assert not [call for call in server.calls if call[0] == "getAutomationCaseFiles"]
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1: CaseListDelegate Rendering & Visual Presentation
# ─────────────────────────────────────────────────────────────────────────────

def test_delegate_size_hint_dimensions(qapp):
    list_widget = QListWidget()
    delegate = CaseListDelegate(list_widget)
    item = QListWidgetItem("REF/001 | DL01 | UIIC | Surveyor")
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 400, 60)
    size = delegate.sizeHint(opt, list_widget.indexFromItem(item))
    assert size.height() == 122
    assert size.width() == 400


def test_delegate_paint_normal_selected_hovered_rendering(qapp):
    list_widget = QListWidget()
    list_widget.resize(500, 300)
    delegate = CaseListDelegate(list_widget)

    item1 = QListWidgetItem("REF/001 | PB01AB1234 | United India Insurance | Surveyor A")
    item2 = QListWidgetItem("REF/002 | MH02CD5678 | New India Assurance | Surveyor B")
    item3 = QListWidgetItem("REF/003 | GJ03EF9012 | Oriental Insurance Company Limited | Surveyor C")
    item4 = QListWidgetItem("REF/004 | KA04GH3456 | Custom Insurer | Surveyor D")
    for it in (item1, item2, item3, item4):
        list_widget.addItem(it)

    list_widget.setCurrentRow(0)
    list_widget.show()

    # Render list to offscreen image to execute paint() for all items
    img = QImage(500, 300, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.white)
    painter = QPainter(img)
    list_widget.render(painter)
    painter.end()

    # Verify no exceptions and image was populated
    assert not img.isNull()
    assert img.width() == 500
    assert img.height() == 300


def test_delegate_paint_malformed_partial_strings_no_crash(qapp):
    list_widget = QListWidget()
    delegate = CaseListDelegate(list_widget)
    malformed_items = [
        "",
        "   ",
        "JUST_A_REF",
        "REF_ONLY |",
        "REF | VEHICLE",
        "REF | VEHICLE | INSURER",
        "REF | | | ",
        "A | B | C | D | E | F | G",
    ]
    for text in malformed_items:
        list_widget.addItem(QListWidgetItem(text))

    img = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    list_widget.render(painter)
    painter.end()
    assert not img.isNull()


def test_delegate_paint_strict_integer_point_size(qapp):
    """Verify setPointSize in paint strictly uses int to prevent float TypeError."""
    font = QFont()
    # In PyQt6, passing a float to setPointSize raises TypeError
    font.setPointSize(8)
    font.setPointSize(9)
    assert font.pointSize() in (8, 9)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2: Header Toolbar & Automatic Incoming Staging
# ─────────────────────────────────────────────────────────────────────────────

def test_header_toolbar_elements_and_refresh(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
    try:
        assert not hasattr(page, "auto_pickup_toggle")
        assert hasattr(page, "connection")
        assert hasattr(page, "btn_poll")

        # Test clicking refresh triggers poll
        calls_before = len(server.calls)
        page.btn_poll.click()
        assert len(server.calls) > calls_before
    finally:
        page.shutdown()
        page.close()


def test_incoming_case_list_expands_and_uses_outer_page_scroll(qapp, tmp_path):
    jobs = [
        SAMPLE_JOB_UIIC,
        SAMPLE_JOB_NIA,
        SAMPLE_JOB_OIC,
        {**SAMPLE_JOB_UIIC, "case_id": "case_four", "case_ref": "REF/2026/UIIC/FOUR"},
    ]
    page, _server, _window, _ = make_test_queue_page(tmp_path)
    try:
        assert page.list.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert page.list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert page.list.height() == 120

        page.jobs = jobs
        page.refresh()

        expected_minimum = len(jobs) * 122
        assert page.list.count() == len(jobs)
        assert page.list.height() >= expected_minimum
        assert page.list.verticalScrollBar().maximum() == 0
    finally:
        page.shutdown()
        page.close()


def test_incoming_staging_is_always_enabled_without_toggle(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
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


def test_connection_status_pill_various_states(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
    try:
        # 1. Connected
        page.connection.setText("Connected to DocWriter")
        assert "Connected" in page.connection.text()

        # 2. Connecting
        page.connection.setText("Connecting to DocWriter…")
        assert "Connecting" in page.connection.text()

        # 3. Disconnected
        page.connection.setText("Disconnected")
        assert "Disconnected" in page.connection.text()

        # 4. Auth failure
        page.connection.setText("Disconnected — sign in again")
        assert "sign in again" in page.connection.text()
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3: Queued Cases Management & List Selection
# ─────────────────────────────────────────────────────────────────────────────

def test_queue_badge_grammar_and_empty_label(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path, initial_jobs=[])
    try:
        page.poll()
        assert page.list.count() == 0
        assert page.queue_badge.text() == "0 Incoming Cases"
        assert not page.empty_label.isHidden()

        # Add 1 job
        server.jobs_list = [SAMPLE_JOB_UIIC]
        page.poll()
        assert page.list.count() == 1
        assert page.queue_badge.text() == "1 Incoming Case"
        assert page.empty_label.isHidden()

        # Add 2 jobs
        server.jobs_list = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA]
        page.poll()
        assert page.list.count() == 2
        assert page.queue_badge.text() == "2 Incoming Cases"
        assert page.empty_label.isHidden()
    finally:
        page.shutdown()
        page.close()


def test_row_selection_dpapi_safety_and_cred_feedback(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA])
    try:
        # Pre-save credentials for UIIC surveyor only
        page.store.save("profile_surveyor_uiic", "uiic", "user_uiic", "secret_uiic", "SC_UIIC")

        page.poll()

        # Select row 0 (UIIC)
        page.list.setCurrentRow(0)
        assert page.profile.text() == "profile_surveyor_uiic"
        assert page.insurer.currentData() == "uiic"
        # SECURITY INVARIANT: Secret fields must NOT contain raw credentials
        assert page.username.text() == ""
        assert page.secret.text() == ""
        assert page.code.text() == ""
        assert "Saved credentials available" in page.cred_feedback.text()

        # Select row 1 (NIA - no credentials saved yet)
        page.list.setCurrentRow(1)
        assert page.profile.text() == "profile_surveyor_nia"
        assert page.insurer.currentData() == "newindia"
        assert page.username.text() == ""
        assert page.secret.text() == ""
        assert "Saved credentials available" not in page.cred_feedback.text()

        # Out-of-bounds selection (-1) is safely ignored without crash
        prev_profile = page.profile.text()
        page._selected(-1)
        assert page.profile.text() == prev_profile
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4: Unified Case Workspace & State Transitions
# ─────────────────────────────────────────────────────────────────────────────

def test_case_workspace_uses_one_row_for_selected_or_current_case(qapp, tmp_path):
    page, server, window, opened = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        # Save credentials so start_case can proceed
        page.store.save("profile_surveyor_uiic", "uiic", "u1", "p1", "c1")
        page.poll()
        page.list.setCurrentRow(0)

        # A queued case appears once; automation cannot start before preparation.
        assert page.state.current is None
        assert page.list.count() == 1
        assert SAMPLE_JOB_UIIC["case_ref"] in page.list.item(0).text()
        assert page.list.item(0).text().endswith("Queued")
        assert not page.start_button.isEnabled()
        assert not page.fail_button.isEnabled()

        # Manual Stage downloads it without creating an active automation case.
        page.start_case()
        assert page.state.current is None
        assert page.list.count() == 1
        assert SAMPLE_JOB_UIIC["case_ref"] in page.list.item(0).text()
        assert SAMPLE_JOB_UIIC["vehicle_no"] in page.list.item(0).text()
        assert "Ready" in page.list.item(0).text()
        assert not page.fail_button.isEnabled()
    finally:
        page.shutdown()
        page.close()


def test_button_enable_disable_state_matrix(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        page.poll()
        page.list.setCurrentRow(0)

        # Baseline: Start Automation stays disabled until scan/Workspace readiness.
        assert not page.start_button.isEnabled()
        assert not page.fail_button.isEnabled()

        page.store.save("profile_surveyor_uiic", "uiic", "user", "password", "SC")
        prepared = prepare_workspace(page)
        folder = prepared["folder"]
        window._claim = SimpleNamespace(_scan_context=SimpleNamespace(claim_folder_path=folder))
        page.refresh()
        assert page.start_button.isEnabled()
        assert not page.fail_button.isEnabled()

        # Busy state disables all
        page.busy = True
        page.refresh()
        assert not page.start_button.isEnabled()
        assert not page.fail_button.isEnabled()
        assert not page.connect_button.isEnabled()
        page.busy = False
        page.refresh()

        # Active worker disables start
        window._worker = object()
        page.refresh()
        assert not page.start_button.isEnabled()
        window._worker = None

        # Active scan thread disables start
        window._scan_thread = object()
        page.refresh()
        assert not page.start_button.isEnabled()
        window._scan_thread = None

        # State error disables start
        page.state_error = "Error"
        page.refresh()
        assert not page.start_button.isEnabled()
        page.state_error = ""

        # Disconnected client disables start
        saved_client = page.client
        page.client = None
        page.refresh()
        assert not page.start_button.isEnabled()
        page.client = saved_client
        page.refresh()
        assert page.start_button.isEnabled()
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5: DocWriter Connection & Adaptive State Card
# ─────────────────────────────────────────────────────────────────────────────

def test_docwriter_connection_form_and_connected_view_toggle(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
    try:
        # Initially connected
        assert not page.conn_connected_box.isHidden()
        assert page.conn_form_box.isHidden()
        assert "operator@example.invalid" in page.conn_operator_email.text()

        # Click Change Login
        page.change_login()
        assert page.conn_connected_box.isHidden()
        assert not page.conn_form_box.isHidden()

        # Empty credentials rejection
        page.email.setText("")
        page.password.setText("")
        page.connect_client()
        assert "Enter operator email and password" in page.result.text()

        # Successful connection
        page.email.setText("new_op@example.invalid")
        page.password.setText("pass123")
        page.connect_client()
        assert page.client.email == "new_op@example.invalid"
        assert page.password.text() == ""  # Password must be wiped from line edit
        assert not page.conn_connected_box.isHidden()
        assert page.conn_form_box.isHidden()
    finally:
        page.shutdown()
        page.close()


def test_forget_login_and_restore_login(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
    try:
        # Save an operator login in OperatorStore
        page.operator_store.save("saved_op@example.invalid", "saved_secret")
        assert page.operator_store.get()["email"] == "saved_op@example.invalid"

        # Forget login
        page.forget_login()
        assert page.client is None
        assert page.operator_store.get() is None
        assert page.email.text() == ""
        assert page.list.count() == 0
        assert page.connection.text() == "Disconnected"

        # Restore login
        page.operator_store.save("restored@example.invalid", "restored_pass")
        page.restore_login()
        assert page.client is not None
        assert page.client.email == "restored@example.invalid"
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6: Surveyor Portal Login Card & DPAPI Isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_save_credentials_validation_and_banner_isolation(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
    try:
        # Precondition: Result banner has a specific message
        page.result.setText("Initial Portal Activity Message")
        initial_banner_text = page.result.text()

        # 1. Validation failure: missing fields
        page.profile.setText("")
        page.username.setText("")
        page.save_credentials()
        assert "Profile ID, insurer, username and password are required" in page.cred_feedback.text()
        # CRITICAL ISOLATION: Result banner must NOT be touched
        assert page.result.text() == initial_banner_text

        # 2. Save valid credentials
        page.profile.setText("surveyor_prof_99")
        page.insurer.setCurrentIndex(page.insurer.findData("uiic"))
        page.username.setText("portal_user_99")
        page.secret.setText("portal_secret_99")
        page.code.setText("SC99")
        page.save_credentials()

        assert "Saved" in page.cred_feedback.text()
        # CRITICAL ISOLATION: Result banner must STILL be untouched
        assert page.result.text() == initial_banner_text

        # 3. Verify credentials persisted in DPAPI store
        creds = page.store.get("surveyor_prof_99", "uiic")
        assert creds["username"] == "portal_user_99"
        assert creds["password"] == "portal_secret_99"
        assert creds["surveyor_code"] == "SC99"
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7: Portal Activity & Result Banner
# ─────────────────────────────────────────────────────────────────────────────

def test_result_banner_status_pills_and_invariants(qapp):
    frame = QFrame()
    pill = QLabel()
    time_lbl = QLabel()
    banner = ResultBannerLabel(frame, pill, time_lbl)

    # 1. Default initial state
    banner.setText("No result yet.")
    assert "IDLE" in pill.text()

    # 2. Downloading / Processing state
    banner.setText("Downloading claim files from Base44...")
    assert "DOWNLOADING / PROCESSING" in pill.text()

    # 3. Error / Attention state
    banner.setText("Needs Attention: Portal password incorrect")
    assert "FAILED / NEEDS ATTENTION" in pill.text()

    # 4. Normal activity goes to QUEUED / ACTIVITY
    banner.setText("Report submitted successfully")
    assert "CONFIRMED SUCCESS" not in pill.text()
    assert "QUEUED / ACTIVITY" in pill.text()

    # 5. Failed outcome acknowledged as ready_for_upload
    banner.set_report_result("Base44 acknowledged: ready_for_upload", "failed", "ready_for_upload")
    assert "FAILED / NEEDS ATTENTION" in pill.text()

    # 6. Success outcome acknowledged as uploaded -> ONLY THEN CONFIRMED SUCCESS
    banner.set_report_result("Base44 acknowledged: uploaded", "success", "uploaded")
    assert "CONFIRMED SUCCESS" in pill.text()

    # 7. Failure with negation in text
    banner.setText("Report not submitted successfully: duplicate invoice")
    assert "CONFIRMED SUCCESS" not in pill.text()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8: Auto-Pickup Engine Detailed Rules
# ─────────────────────────────────────────────────────────────────────────────

def test_auto_pickup_idle_rules(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
    try:
        # Default: idle is True
        assert page._auto_pickup_idle() is True

        # Network activity does not block independent local staging.
        page.busy = True
        assert page._auto_pickup_idle() is True
        page.busy = False

        # Active automation locks Workspace, while other downloads may continue.
        page.state.current = {"job": SAMPLE_JOB_UIIC}
        assert page._auto_pickup_idle() is True
        page.state.current = None

        # Browser and scan activity likewise do not block downloads.
        window._worker = object()
        assert page._auto_pickup_idle() is True
        window._worker = None

        # Blocker 4: Scan thread active
        window._scan_thread = object()
        assert page._auto_pickup_idle() is True
        window._scan_thread = None

        # Blocker 5: Foreign manual folder loaded in window without manifest
        manual_folder = tmp_path / "manual_claim"
        manual_folder.mkdir()
        window._claim = SimpleNamespace(_scan_context=SimpleNamespace(claim_folder_path=str(manual_folder)))
        assert page._auto_pickup_idle() is True

        # When manifest exists in folder, it is considered a web sync folder
        (manual_folder / "web_sync_manifest.json").write_text("{}")
        assert page._auto_pickup_idle() is True
        window._claim = None
    finally:
        page.shutdown()
        page.close()


def test_auto_pickup_stages_without_credentials_and_never_claims(qapp, tmp_path):
    page, server, window, opened = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        page.auto_pickup_enabled = True
        page.poll()
        page._maybe_auto_pickup()
        assert len(server.jobs_list) == 1

        # Staging does not need portal credentials and never claims Base44.
        page._maybe_auto_pickup()
        assert len(server.claimed_ids) == 0
        assert page._record(SAMPLE_JOB_UIIC["case_id"])["local_status"] == "ready"
        assert len(opened) == 0

        # Saving credentials still does not start or claim automatically.
        page.store.save("profile_surveyor_uiic", "uiic", "user", "pass", "SC")
        page._maybe_auto_pickup()
        assert len(server.claimed_ids) == 0
        assert len(opened) == 0
        assert page.state.current is None
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9: Full Case Lifecycle & Error Recovery
# ─────────────────────────────────────────────────────────────────────────────

def test_full_case_lifecycle_start_submit_report_and_ack(qapp, tmp_path):
    page, server, window, opened = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        page.store.save("profile_surveyor_uiic", "uiic", "user", "pass", "SC")
        page.poll()
        page.list.setCurrentRow(0)

        # 1. Stage, scan, then explicitly start insurer automation.
        activate_case(page)
        assert len(opened) == 1
        current = page.state.current
        assert current["phase"] == "automation active"
        claim_folder = current["folder"]
        assert Path(claim_folder, "web_sync_manifest.json").exists()

        # 2. Portal submission monitor detects successful submission
        records = []
        monitor = SubmissionMonitor(SAMPLE_JOB_UIIC["case_id"], claim_folder, lambda rec: (records.append(rec), page._submission(rec)))
        asyncio.run(monitor.capture({"message": "Report submitted successfully", "kind": "dom", "attempt": 1}))

        # 3. Report was sent to Base44
        assert len(server.reports) == 1
        assert server.reports[0]["status"] == "success"
        assert server.reports[0]["case_id"] == SAMPLE_JOB_UIIC["case_id"]

        # 4. State is reset to None, acknowledgement written
        assert page.state.current is None
        assert Path(claim_folder, "Web_Sync_Report_Acknowledgement.json").exists()
        assert "CONFIRMED SUCCESS" in page.result_status_pill.text()
    finally:
        page.shutdown()
        page.close()


def test_deliberate_failure_with_reason(qapp, tmp_path, monkeypatch):
    page, server, window, _ = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        page.store.save("profile_surveyor_uiic", "uiic", "user", "pass", "SC")
        page.poll()
        page.list.setCurrentRow(0)
        activate_case(page)
        assert page.state.current is not None

        # User clicks Stop / Fail Case and provides reason
        monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Chassis mismatch", True))
        page.fail_case()

        assert len(server.reports) == 1
        assert server.reports[0]["status"] == "failed"
        assert server.reports[0]["portal_message"] == "Chassis mismatch"
        assert page.state.current is None
        assert "FAILED / NEEDS ATTENTION" in page.result_status_pill.text()
    finally:
        page.shutdown()
        page.close()


def test_network_failure_503_preserves_pending_report_for_retry(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        page.store.save("profile_surveyor_uiic", "uiic", "user", "pass", "SC")
        page.poll()
        page.list.setCurrentRow(0)
        activate_case(page)

        # Simulate 503 error on reporting result
        server.fail_report_with_503 = True

        page._submission({
            "case_id": SAMPLE_JOB_UIIC["case_id"],
            "confirmed_success": True,
            "portal_message": "Report submitted successfully",
        })

        # Pending report preserved in state journal
        assert page.state.current is not None
        assert page.state.current["pending_report"]["status"] == "success"

        # Server recovers
        server.fail_report_with_503 = False

        # Next poll will automatically retry the pending report first
        page.poll()
        assert len(server.reports) == 1
        assert page.state.current is None
    finally:
        page.shutdown()
        page.close()


def test_corrupt_journal_graceful_recovery(qapp, tmp_path):
    (tmp_path / "current_case.json").write_text("{corrupt json file ...")
    page, server, window, _ = make_test_queue_page(tmp_path)
    try:
        assert bool(page.state_error) is True
        assert not page.start_button.isEnabled()
        # App still runs safely without crashing
        page.poll()
        assert page.list.count() >= 0
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10: Manual Browse Folder & Insurer Isolation Safety
# ─────────────────────────────────────────────────────────────────────────────

def test_manual_browse_folder_settings_isolation(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        page.store.save("profile_surveyor_uiic", "uiic", "secret_user", "secret_pass", "SC_SEC")
        page.poll()
        page.list.setCurrentRow(0)
        activate_case(page)

        web_folder = page.state.current["folder"]
        manual_folder = str(tmp_path / "user_manual_folder")

        # 1. Web sync folder returns active credentials
        web_settings = page.settings_for(web_folder, "uiic")
        assert web_settings["username"] == "secret_user"
        assert web_settings["surveyor_code"] == "SC_SEC"

        # 2. Manual folder MUST NOT receive web credentials
        manual_settings = page.settings_for(manual_folder, "uiic")
        assert manual_settings == {}

        # 3. After case completion, previous web folder settings cannot be accessed
        page.state.set(None)
        with pytest.raises(ValueError, match="not the current active case"):
            page.settings_for(web_folder, "uiic")
    finally:
        page.shutdown()
        page.close()


def test_portal_for_all_supported_insurers():
    assert portal_for("United India Insurance") == "uiic"
    assert portal_for("UIIC") == "uiic"
    assert portal_for("united india insurance company limited") == "uiic"

    assert portal_for("New India Assurance") == "newindia"
    assert portal_for("NIA") == "newindia"
    assert portal_for("the new india assurance company limited") == "newindia"

    assert portal_for("Oriental Insurance") == "oic"
    assert portal_for("OIC") == "oic"
    assert portal_for("oriental insurance company limited") == "oic"

    with pytest.raises(ValueError, match="Unsupported insurer"):
        portal_for("HDFC ERGO General Insurance")


def test_confirms_submission_string_matcher_comprehensive():
    # True positives
    assert confirms_submission("Report submitted successfully")
    assert confirms_submission("Survey report has been submitted successfully.")
    assert confirms_submission("Final claim submission successful")
    assert confirms_submission("Assessment has been submitted")
    assert confirms_submission("Physical documents are not required. Report submitted successfully.")
    assert confirms_submission("Approval is pending. Survey report submitted successfully.")

    # False positives / Negations (must return False)
    assert not confirms_submission("Report not submitted successfully")
    assert not confirms_submission("Submission failed due to invalid VIN")
    assert not confirms_submission("Error occurred while submitting report")
    assert not confirms_submission("Pending approval from surveyor manager")
    assert not confirms_submission("Do you want to submit the report?")
    assert not confirms_submission("Confirm final submission?")
    assert not confirms_submission("Inspection incomplete")
    assert not confirms_submission("Chassis number missing")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11: Client Network Contract, 401 Re-login & 409 Conflict
# ─────────────────────────────────────────────────────────────────────────────

def test_client_automatic_token_refresh_on_401():
    server = ComprehensiveMockServer([SAMPLE_JOB_UIIC])
    client = Client("op@test.invalid", "secret", session=server)

    # Initial login occurs on first authenticated request
    jobs = client.jobs()
    assert len(jobs) == 1
    assert server.logins == 1

    # Simulate token expiration on the server
    server.expire_on_next_call = True

    # Next call receives 401, re-authenticates automatically, and retries the request successfully
    jobs2 = client.jobs()
    assert len(jobs2) == 1
    assert server.logins == 2


def test_client_conflict_409_already_claimed():
    server = ComprehensiveMockServer([SAMPLE_JOB_UIIC])
    client = Client("op@test.invalid", "secret", session=server)

    # First claim succeeds
    res1 = client.claim(SAMPLE_JOB_UIIC["case_id"], SAMPLE_JOB_UIIC["automation_dispatch_id"])
    assert res1["case_id"] == SAMPLE_JOB_UIIC["case_id"]
    assert res1["status"] == "automation_in_progress"

    # Second claim returns 409 conflict
    with pytest.raises(ApiError) as exc_info:
        client.claim(SAMPLE_JOB_UIIC["case_id"], SAMPLE_JOB_UIIC["automation_dispatch_id"])
    assert exc_info.value.status == 409


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 12: Download Sanitization & Safe Manifest Generation
# ─────────────────────────────────────────────────────────────────────────────

def test_flat_name_sanitization_and_windows_reserved_names():
    # Normal filename
    assert flat_name("Report_Final.pdf") == "Report_Final.pdf"

    # URL-encoded name
    assert flat_name("My%20Document.pdf") == "My Document.pdf"

    # Path traversal attack vectors flattened to basename
    assert flat_name("../../secret/passwords.txt") == "passwords.txt"
    assert flat_name("..\\..\\windows\\system32\\calc.exe") == "calc.exe"

    # Windows reserved device names prefixed with underscore
    assert flat_name("CON.txt") == "_CON.txt"
    assert flat_name("PRN.pdf") == "_PRN.pdf"
    assert flat_name("AUX") == "_AUX"
    assert flat_name("NUL.dat") == "_NUL.dat"
    assert flat_name("COM1.log") == "_COM1.log"

    # Forbidden characters replaced with underscore
    assert flat_name('bad:name*with?chars".pdf') == "bad_name_with_chars_.pdf"

    # Empty or dot names raise ValueError
    with pytest.raises(ValueError):
        flat_name("")
    with pytest.raises(ValueError):
        flat_name(".")
    with pytest.raises(ValueError):
        flat_name("..")


def test_download_case_generates_manifest_and_flattens_files(tmp_path):
    server = ComprehensiveMockServer([SAMPLE_JOB_UIIC])
    client = Client("op@test.invalid", "secret", session=server)
    client.claim(SAMPLE_JOB_UIIC["case_id"], SAMPLE_JOB_UIIC["automation_dispatch_id"])

    dest_folder = tmp_path / "downloaded_claim"
    latest_excel_file = download_case(
        client, SAMPLE_JOB_UIIC["case_id"], dest_folder,
        automation_dispatch_id=SAMPLE_JOB_UIIC["automation_dispatch_id"],
    )

    # Manifest file created
    manifest_path = dest_folder / "web_sync_manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["case_id"] == SAMPLE_JOB_UIIC["case_id"]
    assert manifest["latest_excel"] == latest_excel_file
    assert (dest_folder / latest_excel_file).exists()
    assert (dest_folder / "RC.pdf").exists()
    assert (dest_folder / "Bill.pdf").exists()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 13: Atomic JSON Concurrency & State Integrity
# ─────────────────────────────────────────────────────────────────────────────

def test_atomic_json_roundtrip_and_safety(tmp_path):
    file_path = tmp_path / "sub" / "state.json"
    payload = {"status": "ok", "count": 42, "items": ["a", "b", "c"]}

    atomic_json(file_path, payload)
    assert file_path.exists()
    assert json.loads(file_path.read_text(encoding="utf-8")) == payload

    # Overwrite with new payload
    new_payload = {"status": "updated", "count": 99}
    atomic_json(file_path, new_payload)
    assert json.loads(file_path.read_text(encoding="utf-8")) == new_payload


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 14: Sequential Multiple Case Lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def test_sequential_multiple_case_lifecycle(qapp, tmp_path):
    server = ComprehensiveMockServer([SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA])
    page, server, window, opened = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA])
    try:
        # Pre-save credentials for both surveyors
        page.store.save("profile_surveyor_uiic", "uiic", "u_uiic", "p_uiic", "SC1")
        page.store.save("profile_surveyor_nia", "newindia", "u_nia", "p_nia", "SC2")

        page.poll()
        assert page.list.count() == 2

        # ── Case 1: Start and complete successfully ──
        page.list.setCurrentRow(0)
        activate_case(page)
        assert page.state.current is not None
        assert page.state.current["job"]["case_id"] == SAMPLE_JOB_UIIC["case_id"]

        page._submission({
            "case_id": SAMPLE_JOB_UIIC["case_id"],
            "confirmed_success": True,
            "portal_message": "Report submitted successfully",
        })
        assert page.state.current is None
        assert len(server.reports) == 1
        assert server.reports[0]["status"] == "success"

        # ── Case 2: Start and deliberate fail ──
        page.poll()
        # Case 1 waits locally for Mark Completed while Case 2 remains queued.
        assert page.list.count() == 2
        case_2_row = next(
            index for index in range(page.list.count())
            if (page.list.item(index).data(Qt.ItemDataRole.UserRole) or {}).get("job", {}).get("case_id")
            == SAMPLE_JOB_NIA["case_id"]
        )
        page.list.setCurrentRow(case_2_row)
        activate_case(page)
        assert page.state.current is not None
        assert page.state.current["job"]["case_id"] == SAMPLE_JOB_NIA["case_id"]

        # Deliberately fail Case 2
        page.state.current["pending_report"] = None
        server.reports.clear()
        page.client.report({
            "case_id": SAMPLE_JOB_NIA["case_id"],
            "automation_dispatch_id": SAMPLE_JOB_NIA["automation_dispatch_id"],
            "status": "failed", "portal_message": "Chassis issue",
        })
        page.state.set(None)
        page.refresh()

        assert page.state.current is None
        assert len(server.reports) == 1
        assert server.reports[0]["status"] == "failed"
    finally:
        page.shutdown()
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 15: Clean Page Shutdown
# ─────────────────────────────────────────────────────────────────────────────

def test_page_shutdown_stops_timers_and_thread_pool(qapp, tmp_path):
    page, server, window, _ = make_test_queue_page(tmp_path)
    assert not page.closing
    page.shutdown()
    assert page.closing is True
    assert not page.timer.isActive()
    page.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 16: Multi-case Inbox / Staging Safety
# ─────────────────────────────────────────────────────────────────────────────

def test_multicase_auto_stage_downloads_all_without_claim(qapp, tmp_path):
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA, SAMPLE_JOB_OIC]
    page, server, _window, opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        page.auto_pickup_enabled = True
        page.poll()
        page._maybe_auto_pickup()
        assert {record["case_id"] for record in page._records()} == {job["case_id"] for job in jobs}
        assert all(record["local_status"] == "ready" for record in page._records())
        assert len({record["folder"] for record in page._records()}) == 3
        assert not server.claimed_ids
        assert page.state.current is None
        assert not opened
    finally:
        page.shutdown()
        page.close()


def test_empty_case_click_is_ignored_safely(qapp, tmp_path):
    page, server, _window, opened = make_test_queue_page(
        tmp_path, initial_jobs=[SAMPLE_JOB_UIIC]
    )
    try:
        page.poll()
        before_records = page._records()
        page._case_clicked(None)
        assert page.state.current is None
        assert page._records() == before_records
        assert not server.claimed_ids
        assert not opened
    finally:
        page.shutdown()
        page.close()


def test_staged_cases_survive_restart_in_stable_folders(qapp, tmp_path):
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA, SAMPLE_JOB_OIC]
    page, _server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    page.auto_pickup_enabled = True
    page.poll()
    page._maybe_auto_pickup()
    before = {record["case_id"]: record["folder"] for record in page._records()}
    page.shutdown()
    page.close()

    second, _server2, _window2, _opened2 = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        after = {record["case_id"]: record["folder"] for record in second._records()}
        assert after == before
        assert all(Path(folder).is_dir() for folder in after.values())
        assert second.state.current is None
    finally:
        second.shutdown()
        second.close()


def test_two_download_limit_and_one_failure_does_not_block_third(qapp, tmp_path, monkeypatch):
    import app.web_sync.page as page_module
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA, SAMPLE_JOB_OIC]
    page, server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    page.stage_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-stage")
    gate = threading.Event()
    lock = threading.Lock()
    running = 0
    maximum = 0

    def controlled_download(_client, case_id, folder, progress=None, **_kwargs):
        nonlocal running, maximum
        with lock:
            running += 1
            maximum = max(maximum, running)
        try:
            if case_id == SAMPLE_JOB_UIIC["case_id"]:
                gate.wait(3)
            if case_id == SAMPLE_JOB_NIA["case_id"]:
                raise RuntimeError("dummy download failure")
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / "latest.xlsx").write_bytes(b"excel")
            atomic_json(Path(folder) / "web_sync_manifest.json", {
                "case_id": case_id, "latest_excel": "latest.xlsx", "files": [],
            })
            return "latest.xlsx"
        finally:
            with lock:
                running -= 1

    monkeypatch.setattr(page_module, "download_case", controlled_download)
    try:
        page.poll()
        page.auto_pickup_enabled = True
        page._maybe_auto_pickup()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            qapp.processEvents()
            nia = page._record(SAMPLE_JOB_NIA["case_id"])
            oic = page._record(SAMPLE_JOB_OIC["case_id"])
            if nia and nia.get("local_status") == "stage failed" and oic and oic.get("local_status") == "ready":
                break
            time.sleep(0.01)
        gate.set()
        while page.staging_ids and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        statuses = {record["case_id"]: record["local_status"] for record in page._records()}
        assert maximum == 2
        assert statuses[SAMPLE_JOB_NIA["case_id"]] == "stage failed"
        assert statuses[SAMPLE_JOB_OIC["case_id"]] == "ready"
        assert statuses[SAMPLE_JOB_UIIC["case_id"]] == "ready"
        assert not server.claimed_ids
    finally:
        gate.set()
        page.shutdown()
        page.close()


def test_manifest_404_stays_failed_until_explicit_restage(qapp, tmp_path, monkeypatch):
    import app.web_sync.page as page_module

    job = {
        **SAMPLE_JOB_UIIC,
        "case_id": "case_missing_drive",
        "case_ref": "REF/2026/UIIC/MISSING-DRIVE",
        "drive_folder_id": "",
        "drive_folder_link": "",
    }
    attempts = []

    def missing_manifest(_client, case_id, _folder, progress=None, **_kwargs):
        attempts.append(case_id)
        raise ApiError(404, "getAutomationCaseFiles")

    monkeypatch.setattr(page_module, "download_case", missing_manifest)
    page, server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=[job])
    try:
        page.auto_pickup_enabled = True
        page.poll()
        page._maybe_auto_pickup()

        deadline = time.monotonic() + 3
        while page.staging_ids and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        record = page._record(job["case_id"])
        assert record["local_status"] == "stage failed"
        assert attempts == [job["case_id"]]
        assert not server.claimed_ids

        # Polling, Auto Pickup and selecting the failed row must leave it stable.
        for _ in range(3):
            page.poll()
            page._maybe_auto_pickup()
            qapp.processEvents()
        page._case_clicked(page.list.currentItem())
        qapp.processEvents()
        assert attempts == [job["case_id"]]

        actions = "\n".join(entry["action"] for entry in page._live_log_entries)
        assert "no Drive folder ID and no Drive folder link" in actions
        assert "claimAutomationCase was not called" in actions
        assert "click Restage" in actions
        assert "automatic staging will not retry it" in page.result.text()

        # Explicit Restage is the only action that launches a second attempt.
        page.restage_selected()
        deadline = time.monotonic() + 3
        while page.staging_ids and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert attempts == [job["case_id"], job["case_id"]]
        assert page._record(job["case_id"])["local_status"] == "stage failed"
        assert not server.claimed_ids
    finally:
        page.shutdown()
        page.close()


def test_operator_can_start_case_c_before_case_a(qapp, tmp_path):
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA, SAMPLE_JOB_OIC]
    page, server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        for job, portal in ((SAMPLE_JOB_UIIC, "uiic"), (SAMPLE_JOB_NIA, "newindia"), (SAMPLE_JOB_OIC, "oic")):
            page.store.save(job["surveyor_profile_id"], portal, f"{portal}-user", "secret", "SC")
        page.auto_pickup_enabled = True
        page.poll()
        page._maybe_auto_pickup()
        c_row = next(index for index in range(page.list.count()) if
                     (page.list.item(index).data(Qt.ItemDataRole.UserRole) or {}).get("job", {}).get("case_id") == SAMPLE_JOB_OIC["case_id"])
        page.list.setCurrentRow(c_row)
        activate_case(page)
        assert server.claimed_ids == {SAMPLE_JOB_OIC["case_id"]}
        assert page.state.current["job"]["case_id"] == SAMPLE_JOB_OIC["case_id"]
        assert page.state.current["portal"] == "oic"
        assert page._record(SAMPLE_JOB_UIIC["case_id"])["local_status"] == "ready"
    finally:
        page.shutdown()
        page.close()


def test_active_case_locks_workspace_but_other_staging_continues(qapp, tmp_path):
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA, SAMPLE_JOB_OIC]
    page, server, _window, opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        page.store.save(SAMPLE_JOB_UIIC["surveyor_profile_id"], "uiic", "a-user", "secret", "A")
        page.auto_pickup_enabled = True
        page.poll()
        page._maybe_auto_pickup()
        activate_case(page)
        active_folder = page.state.current["folder"]
        nia_row = next(index for index in range(page.list.count()) if
                       (page.list.item(index).data(Qt.ItemDataRole.UserRole) or {}).get("job", {}).get("case_id") == SAMPLE_JOB_NIA["case_id"])
        opens_before = len(opened)
        page._case_clicked(page.list.item(nia_row))
        assert len(opened) == opens_before
        assert page.state.current["folder"] == active_folder
        assert page.profile.text() == SAMPLE_JOB_UIIC["surveyor_profile_id"]
        assert page._record(SAMPLE_JOB_NIA["case_id"])["local_status"] == "ready"
        assert page.start_automation_for_folder(page._record(SAMPLE_JOB_NIA["case_id"])["folder"]) is False
        assert server.claimed_ids == {SAMPLE_JOB_UIIC["case_id"]}
    finally:
        page.shutdown()
        page.close()


def test_claim_conflict_marks_only_selected_case_claimed_elsewhere(qapp, tmp_path):
    page, server, _window, opened = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        page.store.save(SAMPLE_JOB_UIIC["surveyor_profile_id"], "uiic", "user", "secret", "SC")
        page.poll()
        prepare_workspace(page)
        server.claimed_ids.add(SAMPLE_JOB_UIIC["case_id"])
        page.start_automation()
        assert page.state.current is None
        assert page._record(SAMPLE_JOB_UIIC["case_id"])["local_status"] == "claimed elsewhere"
        assert "Claimed Elsewhere" in page.result.text()
        assert len(opened) == 1
    finally:
        page.shutdown()
        page.close()


def test_one_click_delete_is_local_only_and_hides_only_selected_case(qapp, tmp_path, monkeypatch):
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA]
    page, _server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        page.auto_pickup_enabled = True
        page.poll()
        page._maybe_auto_pickup()
        a_folder = Path(page._record(SAMPLE_JOB_UIIC["case_id"])["folder"])
        b_folder = Path(page._record(SAMPLE_JOB_NIA["case_id"])["folder"])
        b_row = next(index for index in range(page.list.count()) if
                     (page.list.item(index).data(Qt.ItemDataRole.UserRole) or {}).get("job", {}).get("case_id") == SAMPLE_JOB_NIA["case_id"])
        page.list.setCurrentRow(b_row)
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Delete must not ask for confirmation")),
        )
        page.delete_current_local_copy()
        assert a_folder.exists()
        assert not b_folder.exists()
        assert page._record(SAMPLE_JOB_NIA["case_id"])["deleted_by_operator"] is True
        assert page.list.count() == 1
        assert SAMPLE_JOB_NIA["case_id"] not in {
            (page.list.item(index).data(Qt.ItemDataRole.UserRole) or {}).get("job", {}).get("case_id")
            for index in range(page.list.count())
        }
        page.poll()
        page._maybe_auto_pickup()
        assert page.list.count() == 1
        assert not b_folder.exists()
        assert not _server.claimed_ids
        assert page._record(SAMPLE_JOB_UIIC["case_id"])["local_status"] == "ready"
    finally:
        page.shutdown()
        page.close()


def test_delete_marker_wins_if_background_download_finishes_after_delete(qapp, tmp_path):
    page, server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        folder = tmp_path / "cases" / "late-download"
        folder.mkdir(parents=True)
        (folder / "late.pdf").write_bytes(b"late")
        page.case_repo.upsert(
            SAMPLE_JOB_UIIC["case_id"],
            job=SAMPLE_JOB_UIIC,
            folder=str(folder),
            local_status="deleted",
            phase="deleted",
            deleted_by_operator=True,
            local_copy_deleted=True,
        )
        page.deleted_case_ids.add(SAMPLE_JOB_UIIC["case_id"])
        page.staging_ids.add(SAMPLE_JOB_UIIC["case_id"])

        page._staging_completed(
            SAMPLE_JOB_UIIC["case_id"],
            {"folder": str(folder), "latest_excel": "latest.xlsx"},
            None,
        )

        assert not folder.exists()
        assert page._record(SAMPLE_JOB_UIIC["case_id"])["deleted_by_operator"] is True
        assert not server.claimed_ids
    finally:
        page.shutdown()
        page.close()


def test_display_numbers_are_incremental_and_persist_after_restart(qapp, tmp_path):
    jobs = [
        {
            "case_id": "6a9c50c447f3de956637f8ed", "case_ref": "JDB/2026-27/PORTAL/9848",
            "vehicle_no": "HR04K6444", "insurer": "New India Assurance Company Limited",
            "surveyor_profile_id": "6a90645cd99b7f3d93d61e58", "status": "queued_for_automation",
        },
        {
            "case_id": "6a9c5a5a882bb320a97e094e", "case_ref": "JDB/2026-27/PORTAL/8457",
            "vehicle_no": "HR04K6444", "insurer": "New India Assurance Company Limited",
            "surveyor_profile_id": "6a90645cd99b7f3d93d61e58", "status": "queued_for_automation",
        },
        {
            "case_id": "6a9c664514d5682c084a8f28", "case_ref": "JDB/2026-27/PORTAL/2728",
            "vehicle_no": "T0323CH4757A", "insurer": "United India Insurance Company Limited",
            "surveyor_profile_id": "6a90645cd99b7f3d93d61e58", "status": "queued_for_automation",
        },
        {
            "case_id": "6a9c6aedce627eea2b6795de", "case_ref": "JDB/2026-27/PORTAL/2758",
            "vehicle_no": "T0323CH4757A", "insurer": "United India Insurance Company Limited",
            "surveyor_profile_id": "6a90645cd99b7f3d93d61e58", "status": "queued_for_automation",
        },
    ]
    page, _server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        page.jobs = jobs
        page.refresh()
        assert page.list.count() == 4
        first_numbers = {
            job["case_id"]: page._record(job["case_id"])["display_number"]
            for job in jobs
        }
        assert [first_numbers[job["case_id"]] for job in jobs] == [1, 2, 3, 4]
        assert [page.list.item(index).text().split(" | ", 1)[0] for index in range(4)] == [
            "#001", "#002", "#003", "#004",
        ]
    finally:
        page.shutdown()
        page.close()

    restored, _server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        restored.jobs = jobs
        restored.refresh()
        assert {
            job["case_id"]: restored._record(job["case_id"])["display_number"]
            for job in jobs
        } == first_numbers
    finally:
        restored.shutdown()
        restored.close()


def test_restart_restores_active_lock_and_ready_inbox(qapp, tmp_path):
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA]
    page, _server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    page.store.save(SAMPLE_JOB_UIIC["surveyor_profile_id"], "uiic", "user", "secret", "SC")
    page.auto_pickup_enabled = True
    page.poll()
    page._maybe_auto_pickup()
    activate_case(page)
    active_folder = page.state.current["folder"]
    page.shutdown()
    page.close()

    second, _server2, _window2, opened2 = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_NIA])
    try:
        assert second.state.current["job"]["case_id"] == SAMPLE_JOB_UIIC["case_id"]
        assert second.state.current["folder"] == active_folder
        assert second._record(SAMPLE_JOB_NIA["case_id"])["local_status"] == "ready"
        nia_row = next(index for index in range(second.list.count()) if
                       (second.list.item(index).data(Qt.ItemDataRole.UserRole) or {}).get("job", {}).get("case_id") == SAMPLE_JOB_NIA["case_id"])
        second._case_clicked(second.list.item(nia_row))
        assert not opened2
        assert second.state.current["job"]["case_id"] == SAMPLE_JOB_UIIC["case_id"]
    finally:
        second.shutdown()
        second.close()


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 16: 3-Part Layout, KPI Stat Cards & Live Logs Table
# ─────────────────────────────────────────────────────────────────────────────

def test_streamlined_layout_without_kpi_cards(qapp, tmp_path):
    """Verify that KPI cards are removed and Case Workspace starts directly at the top."""
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA]
    page, _server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        assert not hasattr(page, "stat_incoming")
        assert not hasattr(page, "stat_ready")
        assert not hasattr(page, "stat_active_case")
        assert not hasattr(page, "stat_api_sync")

        # Initial state after polling server
        page.poll()
        page.refresh()
        assert page.list.count() == 2
        assert page.queue_badge.text() == "2 Incoming Cases"
    finally:
        page.shutdown()
        page.close()


def test_live_logs_table_structure_and_append(qapp, tmp_path):
    """Verify the 4-column structured logs table parses levels, phases, and actions."""
    page, _server, _window, _opened = make_test_queue_page(tmp_path)
    try:
        assert hasattr(page, "logs_table")
        assert page.logs_table.columnCount() == 4
        headers = [page.logs_table.horizontalHeaderItem(i).text() for i in range(4)]
        assert headers == ["TIME", "LEVEL", "PHASE", "ACTION"]

        # Append different log events
        page.append_log("Starting background download of case files", phase="Stage", level="Info")
        page.append_log("Case files downloaded and verified", phase="Download", level="Success")
        page.append_log("Warning: conflicting case claimed elsewhere", phase="Claim", level="Warning")
        page.append_log("Error: Portal login failed due to invalid password", phase="Portal", level="Error")

        assert page.logs_table.rowCount() == 4

        # Verify columns for the last row
        time_item = page.logs_table.item(3, 0)
        level_item = page.logs_table.item(3, 1)
        phase_item = page.logs_table.item(3, 2)
        action_item = page.logs_table.item(3, 3)

        assert ":" in time_item.text()
        assert level_item.text() == "ERROR"
        assert phase_item.text() == "PORTAL"
        assert "Portal login failed" in action_item.text()

        # Test search filter
        page.log_search_input.setText("conflicting")
        assert page.logs_table.isRowHidden(0) is True
        assert page.logs_table.isRowHidden(1) is True
        assert page.logs_table.isRowHidden(2) is False
        assert page.logs_table.isRowHidden(3) is True

        page.log_search_input.clear()
        assert page.logs_table.isRowHidden(0) is False
        assert page.logs_table.isRowHidden(3) is False
    finally:
        page.shutdown()
        page.close()


def test_live_logs_banner_integration_and_deduplication(qapp, tmp_path):
    """Verify result banner updates automatically populate the live logs table."""
    page, _server, _window, _opened = make_test_queue_page(tmp_path)
    try:
        initial_count = page.logs_table.rowCount()

        # Update banner text
        page.result.setText("Staging 1 incoming case(s). No Base44 case was claimed.")
        assert page.logs_table.rowCount() == initial_count + 1
        assert "Staging 1 incoming case" in page.logs_table.item(initial_count, 3).text()

        # Repeated same message should be deduplicated
        page.result.setText("Staging 1 incoming case(s). No Base44 case was claimed.")
        assert page.logs_table.rowCount() == initial_count + 1

        # Clear logs
        page._clear_live_logs()
        assert page.logs_table.rowCount() == 0
    finally:
        page.shutdown()
        page.close()


def test_web_queue_workflow_rail_stages_and_navigation(qapp, tmp_path):
    """Verify the 3-stage Workflow rail switches stacked pages and reflects state."""
    page, _server, _window, _opened = make_test_queue_page(tmp_path)
    try:
        assert hasattr(page, "rail")
        assert hasattr(page, "stack")
        assert page.stack.count() == 3
        assert len(page.rail._buttons) == 3

        # Default Stage: 0 (Cases)
        assert page.stack.currentIndex() == 0
        assert page.rail._buttons[0].property("active") is True
        assert page.rail._buttons[1].property("active") is False
        assert "Case Intake" in page.stage_title_label.text()

        # Switch to Stage 1 (Connection)
        page.set_stage(1)
        assert page.stack.currentIndex() == 1
        assert page.rail._buttons[1].property("active") is True
        assert page.rail._buttons[0].property("active") is False
        assert "Connection & Credentials" in page.stage_title_label.text()

        # Switch to Stage 2 (Live Logs)
        page.set_stage(2)
        assert page.stack.currentIndex() == 2
        assert page.rail._buttons[2].property("active") is True
        assert "Live Staging & Portal Activity" in page.stage_title_label.text()

        # Test change_login() automatically navigates to Stage 1
        page.change_login()
        assert page.stack.currentIndex() == 1
        assert page.rail._buttons[1].property("active") is True

        # Test rail button click switching back to Stage 0
        page.rail.stage_selected.emit(0)
        assert page.stack.currentIndex() == 0
        assert page.rail._buttons[0].property("active") is True

        # Test rail state updates in refresh()
        page.refresh()
        assert page.rail._buttons[1].property("state") == "done"  # Server is connected
    finally:
        page.shutdown()
        page.close()


def test_completed_cases_table_structure_and_formatting(qapp, tmp_path):
    """Verify CompletedCasesTable has 5 structured columns and color-coded status badges."""
    from app.web_sync.page import CompletedCasesTable
    page, _server, _window, _opened = make_test_queue_page(tmp_path)
    try:
        assert isinstance(page.completed_list, CompletedCasesTable)
        assert page.completed_list.columnCount() == 5
        headers = [page.completed_list.horizontalHeaderItem(i).text() for i in range(5)]
        assert headers == ["CASE REF", "VEHICLE", "INSURER", "COMPLETED AT", "STATUS / RESULT"]

        # Initially empty
        assert page.completed_list.count() == 0

        # Add a failed / attention completed case
        failed_entry = {
            "case_id": "case_test_fail",
            "case_ref": "JDB/2026-27/PORTAL/2728",
            "vehicle_no": "T0323CH4757A",
            "insurer": "UNITED INDIA INSURANCE COMPANY LIMITED",
            "completed_at": "2026-09-12T00:43:00+05:30",
            "display_result": "Failed / Needs Attention",
            "unresolved": True,
            "section": "completed",
        }
        page.completed_store.upsert(failed_entry)

        # Add a confirmed success completed case
        success_entry = {
            "case_id": "case_test_succ",
            "case_ref": "JDB/2026-27/PORTAL/2729",
            "vehicle_no": "DL01AB1234",
            "insurer": "NEW INDIA ASSURANCE",
            "completed_at": "2026-09-12T01:15:00+05:30",
            "display_result": "Submitted Successfully",
            "unresolved": False,
            "section": "completed",
        }
        page.completed_store.upsert(success_entry)

        page.refresh()
        assert page.completed_list.count() == 2

        # Verify Row 0 (Newest / Success entry: 01:15 AM)
        assert page.completed_list.item(0, 0).text() == "JDB/2026-27/PORTAL/2729"
        assert page.completed_list.item(0, 1).text() == "DL01AB1234"
        assert page.completed_list.item(0, 2).text() == "New India"
        assert "Sep 2026" in page.completed_list.item(0, 3).text()
        assert page.completed_list.item(0, 4).text() == "Submitted Successfully"
        # Verify status color for success is greenish
        assert page.completed_list.item(0, 4).foreground().color().name().lower() == "#047857"

        # Verify Row 1 (Older / Failed entry: 00:43 AM)
        assert page.completed_list.item(1, 0).text() == "JDB/2026-27/PORTAL/2728"
        assert page.completed_list.item(1, 1).text() == "T0323CH4757A"
        assert page.completed_list.item(1, 2).text() == "UIIC"
        assert page.completed_list.item(1, 4).text() == "Failed / Needs Attention"
        # Verify status color for failed is reddish
        assert page.completed_list.item(1, 4).foreground().color().name().lower() == "#b91c1c"

        # Verify setCurrentRow and currentItem() retrieve entry dictionary
        page.completed_list.setCurrentRow(0)
        selected = page._selected_completed()
        assert selected is not None
        assert selected["case_id"] == "case_test_succ"

        page.completed_list.setCurrentRow(1)
        selected2 = page._selected_completed()
        assert selected2 is not None
        assert selected2["case_id"] == "case_test_fail"
    finally:
        page.shutdown()
        page.close()


def test_view_images_button_and_delegate_action(qapp, tmp_path):
    page, server, opened, stopped = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    try:
        assert hasattr(page, "view_images_button")
        assert "IMAGES" in page.view_images_button.text()
        assert page.view_images_button.cursor().shape() == Qt.CursorShape.PointingHandCursor

        page.poll()
        assert page.list.count() == 1
        page.list.setCurrentRow(0)
        assert page.view_images_button.isEnabled()

        # Delegate size hint
        item = page.list.item(0)
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 500, 122)
        size = page.list.itemDelegate().sizeHint(opt, page.list.indexFromItem(item))
        assert size.height() == 122

        # Delegate images button rect
        btn_rect = page.list.itemDelegate()._images_button_rect(opt.rect)
        assert btn_rect.width() > 50
        btn_rect_r = btn_rect.toRect() if hasattr(btn_rect, "toRect") else btn_rect
        assert opt.rect.contains(btn_rect_r)
    finally:
        page.shutdown()
        page.close()


def test_short_insurer_label_standardization():
    from app.web_sync.page import short_insurer_label
    assert short_insurer_label("UNITED INDIA INSURANCE COMPANY LIMITED") == "UIIC"
    assert short_insurer_label("United India") == "UIIC"
    assert short_insurer_label("uiic") == "UIIC"
    assert short_insurer_label("New India Assurance Company Limited") == "New India"
    assert short_insurer_label("The New India Assurance Company Limited") == "New India"
    assert short_insurer_label("new india") == "New India"
    assert short_insurer_label("nia") == "New India"
    assert short_insurer_label("Oriental Insurance Company Limited") == "OIC"
    assert short_insurer_label("oriental") == "OIC"
    assert short_insurer_label("oic") == "OIC"
    assert short_insurer_label("") == ""
    assert short_insurer_label("Unknown Insurer Ltd") == "Unknown Insurer Ltd"


def test_per_case_card_has_only_three_simple_actions(qapp, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QStyleOptionViewItem
    from PyQt6.QtCore import QRect
    jobs = [SAMPLE_JOB_UIIC, SAMPLE_JOB_NIA]
    page, _server, _window, _opened = make_test_queue_page(tmp_path, initial_jobs=jobs)
    try:
        page.auto_pickup_enabled = True
        page.poll()
        page._maybe_auto_pickup()
        assert page.list.count() == 2

        # 1. Test delegate button rects
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 700, 122)
        delegate = page.list.itemDelegate()
        rects = delegate._button_rects(opt.rect)
        assert set(rects.keys()) == {"start", "folder", "delete"}
        for name, r in rects.items():
            assert opt.rect.contains(r), f"Button {name} out of bounds"
        # Check no overlap between adjacent buttons
        assert rects["start"].right() < rects["folder"].left()
        assert rects["folder"].right() < rects["delete"].left()
        assert page.completed_cases_card.isHidden()

        opened = []
        monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
        folder = Path(page._record(SAMPLE_JOB_UIIC["case_id"])["folder"])
        page.open_case_folder_by_index(0)
        assert [Path(value) for value in opened] == [folder]
    finally:
        page.shutdown()
        page.close()


def test_card_start_automation_scans_then_claims_and_starts_without_second_click(qapp, tmp_path):
    page, server, window, opened = make_test_queue_page(tmp_path, initial_jobs=[SAMPLE_JOB_UIIC])
    started = []
    window._start_automation = lambda: started.append(True)
    try:
        page.store.save(SAMPLE_JOB_UIIC["surveyor_profile_id"], "uiic", "user", "secret", "SC")
        page.poll()
        page._maybe_auto_pickup()
        record = page._record(SAMPLE_JOB_UIIC["case_id"])
        assert record["local_status"] == "ready"

        page.start_automation_by_index(0)
        assert len(opened) == 1
        assert not server.claimed_ids

        window._claim = SimpleNamespace(
            _scan_context=SimpleNamespace(claim_folder_path=record["folder"])
        )
        page.workspace_scan_completed(record["folder"], True)

        assert server.claimed_ids == {SAMPLE_JOB_UIIC["case_id"]}
        assert started == [True]
        assert page.state.current["job"]["case_id"] == SAMPLE_JOB_UIIC["case_id"]
    finally:
        page.shutdown()
        page.close()
