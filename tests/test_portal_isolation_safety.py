import json
from types import SimpleNamespace

import pytest


def test_scan_folder_never_uses_invoice_as_cancelled_cheque(tmp_path):
    from app.data.folder_scanner import scan_folder

    (tmp_path / "claim.xlsx").write_text("placeholder", encoding="utf-8")
    (tmp_path / "final_invoice.pdf").write_bytes(b"%PDF-1.4\n")

    result = scan_folder(str(tmp_path), portal_id="newindia")

    assert "Cancelled Cheque / Bank Details" not in result.claim_doc_files
    assert not (tmp_path / "cancel_check_fallback.pdf").exists()
    assert any("Invoice fallback is disabled" in msg for msg in result.policy_warnings)
    assert result.policy_events[0]["event"] == "bank_proof_missing_no_fallback"
    assert result.policy_events[0]["policy_decision"] == "no_fallback_used"
    assert result.policy_events[0]["portal_id"] == "newindia"
    assert result.assessment_files["invoice"].endswith("final_invoice.pdf")


def test_scan_folder_cleans_only_current_scan_generated_files(tmp_path):
    from app.data.folder_scanner import scan_folder

    source = tmp_path / "vehicle.jpg"
    source.write_bytes(b"image")
    preexisting = tmp_path / "vehicle_photo_2.jpg"
    preexisting.write_bytes(b"user file")

    calls = {"count": 0}

    def stop_cb():
        calls["count"] += 1
        return calls["count"] >= 4

    result = scan_folder(str(tmp_path), portal_id="uiic", stop_cb=stop_cb)

    assert result.cancelled
    assert not (tmp_path / "vehicle_photo_1.jpg").exists()
    assert preexisting.exists()
    assert preexisting.read_bytes() == b"user file"
    assert any(
        event["event"] == "scan_generated_files_cleaned"
        for event in result.policy_events
    )


def test_claim_folder_service_attaches_scan_context(monkeypatch, tmp_path):
    from app.data.data_model import ClaimData
    from app.ui.services.claim_folder_service import ClaimFolderService

    excel_path = tmp_path / "claim.xlsx"
    excel_path.write_text("placeholder", encoding="utf-8")

    fake_scan = SimpleNamespace(
        claim_doc_files={},
        assessment_files={},
        upload_doc_files={},
        expected_docs=[],
        skipped_files=[],
        unknown_files=[],
        excel_path=str(excel_path),
        policy_warnings=[],
        temporary_files=[],
    )

    fake_claim = ClaimData(portal_id="uiic")
    fake_claim.claim_no = "CLAIM-1"

    monkeypatch.setattr(
        "app.data.folder_scanner.scan_folder",
        lambda _folder, portal_id="uiic", stop_cb=None: fake_scan,
    )
    monkeypatch.setattr(
        "app.data.excel_reader.extract_claim_data",
        lambda _path, portal_id="uiic": fake_claim,
    )
    monkeypatch.setattr(
        "app.ui.services.claim_folder_service.AutomationLogger",
        None,
        raising=False,
    )

    service = ClaimFolderService(config_dir="", portal_id="newindia")
    result = service.process_folder(str(tmp_path))

    assert result.success
    assert result.claim._scan_context.portal_id == "newindia"
    assert result.scan_result.scan_context.portal_id == "newindia"
    assert result.claim.portal_id == "newindia"


def test_claim_folder_service_returns_cancelled_scan(monkeypatch, tmp_path):
    from app.ui.services.claim_folder_service import ClaimFolderService

    fake_scan = SimpleNamespace(
        claim_doc_files={},
        assessment_files={},
        upload_doc_files={},
        expected_docs=[],
        skipped_files=[],
        unknown_files=[],
        excel_path=None,
        policy_warnings=[],
        policy_events=[],
        temporary_files=[],
        cancelled=True,
        cancellation_reason="before_upload_compression",
    )

    monkeypatch.setattr(
        "app.data.folder_scanner.scan_folder",
        lambda _folder, portal_id="uiic", stop_cb=None: fake_scan,
    )

    service = ClaimFolderService(config_dir="", portal_id="newindia")
    result = service.process_folder(str(tmp_path))

    assert not result.success
    assert result.error == "Cancelled"
    assert result.scan_result.scan_context.portal_id == "newindia"
    assert any("before_upload_compression" in line for line in result.log_lines)


def test_claim_folder_service_writes_scan_policy_audit(
    monkeypatch, tmp_path
):
    from app.ui.services.claim_folder_service import ClaimFolderService

    event = {
        "event": "bank_proof_missing_no_fallback",
        "portal_id": "newindia",
        "folder_path": str(tmp_path),
        "missing_document": "Cancelled Cheque / Bank Details",
        "document_category": "bank_proof",
        "policy_decision": "no_fallback_used",
        "action": "mark_missing_only",
    }
    fake_scan = SimpleNamespace(
        claim_doc_files={},
        assessment_files={},
        upload_doc_files={},
        expected_docs=[],
        skipped_files=[],
        unknown_files=[],
        excel_path=None,
        policy_warnings=["Cancelled Cheque / Bank Details missing."],
        policy_events=[event],
        temporary_files=[],
    )

    monkeypatch.setattr(
        "app.data.folder_scanner.scan_folder",
        lambda _folder, portal_id="uiic", stop_cb=None: fake_scan,
    )
    monkeypatch.setattr(
        "app.ui.services.claim_folder_service.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    service = ClaimFolderService(config_dir="", portal_id="newindia")
    result = service.process_folder(str(tmp_path))

    assert not result.success
    audit_file = tmp_path / "app_data" / "logs/newindia" / "scan_policy_audit.jsonl"
    with open(audit_file, "r", encoding="utf-8") as f:
        audit = json.loads(f.readline())
    assert audit["event"] == "bank_proof_missing_no_fallback"
    assert audit["policy_decision"] == "no_fallback_used"


def test_cancelled_service_scan_cleans_generated_assessment_files(
    monkeypatch, tmp_path
):
    from app.data.data_model import ClaimData
    from app.ui.services.claim_folder_service import ClaimFolderService

    excel_path = tmp_path / "claim.xlsx"
    excel_path.write_text("placeholder", encoding="utf-8")
    generated_path = tmp_path / "auto_primary_assessment.xlsx"
    audit_path = tmp_path / "auto_primary_assessment_audit.txt"

    fake_scan = SimpleNamespace(
        claim_doc_files={},
        assessment_files={},
        upload_doc_files={},
        expected_docs=[],
        skipped_files=[],
        unknown_files=[],
        excel_path=str(excel_path),
        policy_warnings=[],
        policy_events=[],
        temporary_files=[],
        generated_files=[],
    )
    fake_claim = ClaimData(portal_id="newindia")
    fake_claim.claim_no = "CLAIM-CANCEL"

    def fake_generate(_source, _output_dir):
        generated_path.write_text("new assessment", encoding="utf-8")
        audit_path.write_text("audit", encoding="utf-8")
        return SimpleNamespace(
            output_path=str(generated_path),
            status="generated",
            generated_files=[str(generated_path), str(audit_path)],
            message="Primary assessment generated.",
        )

    calls = {"count": 0}

    def stop_cb():
        calls["count"] += 1
        return calls["count"] >= 4

    monkeypatch.setattr(
        "app.data.folder_scanner.scan_folder",
        lambda _folder, portal_id="uiic", stop_cb=None: fake_scan,
    )
    monkeypatch.setattr(
        "app.data.excel_reader.extract_claim_data",
        lambda _path, portal_id="uiic": fake_claim,
    )
    monkeypatch.setattr(
        "app.data.assessment_generator.generate_primary_assessment_result",
        fake_generate,
    )
    monkeypatch.setattr(
        "app.ui.services.claim_folder_service.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    service = ClaimFolderService(config_dir="", portal_id="newindia")
    result = service.process_folder(str(tmp_path), stop_cb=stop_cb)

    assert not result.success
    assert result.error == "Cancelled"
    assert not generated_path.exists()
    assert not audit_path.exists()
    assert any("Generated files cleaned: 2" in line for line in result.log_lines)
    assert any(
        event["event"] == "scan_generated_files_cleaned"
        for event in result.scan_result.policy_events
    )


def test_generated_assessment_replacement_deletes_old_after_new_succeeds(
    monkeypatch, tmp_path
):
    from app.data.data_model import ClaimData
    from app.ui.services.claim_folder_service import ClaimFolderService

    excel_path = tmp_path / "claim.xlsx"
    excel_path.write_text("placeholder", encoding="utf-8")
    old_path = tmp_path / "auto_primary_assessment.xlsx"
    old_path.write_text("old assessment", encoding="utf-8")
    old_audit_path = tmp_path / "auto_primary_assessment_audit.txt"
    old_audit_path.write_text("old audit", encoding="utf-8")
    new_path = tmp_path / "auto_primary_assessment_1.xlsx"
    new_audit_path = tmp_path / "auto_primary_assessment_1_audit.txt"

    fake_scan = SimpleNamespace(
        claim_doc_files={},
        assessment_files={"assessment_excel": str(old_path)},
        upload_doc_files={},
        expected_docs=[],
        skipped_files=[],
        unknown_files=[],
        excel_path=str(excel_path),
        policy_warnings=[],
        policy_events=[],
        temporary_files=[],
        generated_files=[],
    )
    fake_claim = ClaimData(portal_id="newindia")
    fake_claim.claim_no = "CLAIM-REPLACE"
    fake_claim.ifsc_code = "HDFC0000001"
    fake_claim.account_number = "1234567890"

    def fake_generate(_source, _output_dir):
        new_path.write_text("new assessment", encoding="utf-8")
        new_audit_path.write_text("audit", encoding="utf-8")
        return SimpleNamespace(
            output_path=str(new_path),
            status="generated",
            generated_files=[str(new_path), str(new_audit_path)],
            message="Primary assessment generated.",
        )

    monkeypatch.setattr(
        "app.data.folder_scanner.scan_folder",
        lambda _folder, portal_id="uiic", stop_cb=None: fake_scan,
    )
    monkeypatch.setattr(
        "app.data.excel_reader.extract_claim_data",
        lambda _path, portal_id="uiic": fake_claim,
    )
    monkeypatch.setattr(
        "app.data.assessment_generator.generate_primary_assessment_result",
        fake_generate,
    )
    monkeypatch.setattr(
        "app.ui.services.claim_folder_service.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    service = ClaimFolderService(config_dir="", portal_id="newindia")
    result = service.process_folder(str(tmp_path))

    assert result.success
    assert not old_path.exists()
    assert not old_audit_path.exists()
    assert result.claim.assessment_files["assessment_excel"] == str(new_path)
    assert str(new_path) in result.scan_result.generated_files
    assert str(new_audit_path) in result.scan_result.generated_files
    assert any(
        event["event"] == "generated_assessment_replaced"
        and event["old_path"] == str(old_path)
        and event["new_path"] == str(new_path)
        for event in result.scan_result.policy_events
    )
    assert any(
        event["event"] == "old_generated_assessment_deleted"
        and str(old_path) in event["deleted_files"]
        and str(old_audit_path) in event["deleted_files"]
        for event in result.scan_result.policy_events
    )


def test_cancelled_service_scan_cleans_skipped_assessment_audit(
    monkeypatch, tmp_path
):
    from app.data.data_model import ClaimData
    from app.ui.services.claim_folder_service import ClaimFolderService

    excel_path = tmp_path / "claim.xlsx"
    excel_path.write_text("placeholder", encoding="utf-8")
    skipped_audit = tmp_path / "primary_assessment_skipped_audit.txt"

    fake_scan = SimpleNamespace(
        claim_doc_files={},
        assessment_files={},
        upload_doc_files={},
        expected_docs=[],
        skipped_files=[],
        unknown_files=[],
        excel_path=str(excel_path),
        policy_warnings=[],
        policy_events=[],
        temporary_files=[],
        generated_files=[],
    )
    fake_claim = ClaimData(portal_id="newindia")
    fake_claim.claim_no = "CLAIM-SKIP"

    def fake_generate(_source, _output_dir):
        skipped_audit.write_text("skipped", encoding="utf-8")
        return SimpleNamespace(
            output_path=None,
            status="skipped_no_data",
            generated_files=[str(skipped_audit)],
            message="Assessment generation skipped: no parts/labour data found.",
        )

    calls = {"count": 0}

    def stop_cb():
        calls["count"] += 1
        return calls["count"] >= 4

    monkeypatch.setattr(
        "app.data.folder_scanner.scan_folder",
        lambda _folder, portal_id="uiic", stop_cb=None: fake_scan,
    )
    monkeypatch.setattr(
        "app.data.excel_reader.extract_claim_data",
        lambda _path, portal_id="uiic": fake_claim,
    )
    monkeypatch.setattr(
        "app.data.assessment_generator.generate_primary_assessment_result",
        fake_generate,
    )
    monkeypatch.setattr(
        "app.ui.services.claim_folder_service.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    service = ClaimFolderService(config_dir="", portal_id="newindia")
    result = service.process_folder(str(tmp_path), stop_cb=stop_cb)

    assert not result.success
    assert result.error == "Cancelled"
    assert not skipped_audit.exists()
    assert any("Generated files cleaned: 1" in line for line in result.log_lines)


def test_unsupported_cheque_ocr_is_info_and_policy_audited(
    monkeypatch, tmp_path
):
    import openpyxl
    from app.data.data_model import ClaimData
    from app.ui.services.claim_folder_service import ClaimFolderService

    excel_path = tmp_path / "claim.xlsx"
    wb = openpyxl.Workbook()
    wb.save(excel_path)
    wb.close()

    cheque_path = tmp_path / "cancelled_cheque.pdf"
    cheque_path.write_bytes(b"%PDF-1.4\n")

    fake_scan = SimpleNamespace(
        claim_doc_files={"Cancelled Cheque / Bank Details": str(cheque_path)},
        assessment_files={},
        upload_doc_files={},
        expected_docs=[],
        skipped_files=[],
        unknown_files=[],
        excel_path=str(excel_path),
        policy_warnings=[],
        policy_events=[],
        temporary_files=[],
        generated_files=[],
    )
    fake_claim = ClaimData(portal_id="uiic")
    fake_claim.claim_no = "CLAIM-OCR-UNSUPPORTED"

    monkeypatch.setattr(
        "app.data.folder_scanner.scan_folder",
        lambda _folder, portal_id="uiic", stop_cb=None: fake_scan,
    )
    monkeypatch.setattr(
        "app.data.excel_reader.extract_claim_data",
        lambda _path, portal_id="uiic": fake_claim,
    )
    monkeypatch.setattr(
        "app.ui.services.claim_folder_service.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )
    monkeypatch.setattr(
        "app.utils.load_automation_defaults",
        lambda portal_id="uiic": {"eager_folder_ocr": True},
    )
    monkeypatch.setattr(
        "app.automation.ocr_engine.is_ocr_ready",
        lambda: True,
    )

    service = ClaimFolderService(config_dir="", portal_id="uiic")
    result = service.process_folder(str(tmp_path))

    assert result.success
    assert any(
        "Info: Cheque OCR is not configured for portal 'uiic'." in line
        for line in result.log_lines
    )
    assert any(
        event["event"] == "cheque_ocr_unsupported"
        and event["ocr_status"] == "unsupported"
        for event in result.scan_result.policy_events
    )


def test_claim_folder_service_scan_logs_do_not_contain_mojibake():
    from pathlib import Path

    text = Path("app/ui/services/claim_folder_service.py").read_text(
        encoding="utf-8"
    )
    suspicious = ("Ã", "Â", "â", "ð", "ï")

    assert not any(token in text for token in suspicious)


def test_main_window_ignores_stale_scan_result(monkeypatch):
    from app.portals.registry import set_active_portal
    from app.ui.main_window import MainWindow

    class FakeButton:
        def __init__(self):
            self.enabled = None

        def setEnabled(self, enabled):
            self.enabled = enabled

    class FakeWorkspace:
        def __init__(self):
            self.btn_start = FakeButton()

        def findChild(self, *_args):
            return FakeButton()

    logs = []
    audits = []
    statuses = []
    set_active_portal("oic")
    window = MainWindow.__new__(MainWindow)
    window._active_scan_token = None
    window._active_scan_portal_id = None
    window._active_scan_folder = "old-folder"
    window.workspace_page = FakeWorkspace()
    window._append_log = logs.append
    window._write_portal_audit_event = lambda event, **extra: audits.append(
        {"event": event, **extra}
    )
    window._set_status = lambda status, text: statuses.append((status, text))

    result = SimpleNamespace(
        scan_token=1,
        scan_portal_id="newindia",
        scan_folder="old-folder",
        log_lines=["old scan log"],
        success=True,
    )

    MainWindow._on_scan_completed(window, result)

    assert any("Ignored stale scan result" in line for line in logs)
    assert audits[0]["event"] == "stale_scan_result_ignored"
    assert statuses == [("ready", "Rescan Required")]
    assert window._active_scan_folder == ""


def test_portal_audit_write_failure_logs_visible_warning(monkeypatch):
    from app.ui.main_window import MainWindow

    logs = []
    window = MainWindow.__new__(MainWindow)
    window._append_log = logs.append
    monkeypatch.setattr(
        "app.ui.main_window.ensure_dir",
        lambda _path: (_ for _ in ()).throw(OSError("locked")),
    )

    MainWindow._write_portal_audit_event(window, "portal_changed", action="test")

    assert any("Portal audit JSON write failed" in line for line in logs)
    assert any("portal_changed" in line for line in logs)


def test_uiic_cheque_ocr_adapter_is_unsupported_without_newindia_import():
    from app.automation.services.cheque_ocr_adapter import get_cheque_ocr_adapter

    adapter = get_cheque_ocr_adapter("uiic")
    logs = []
    result = adapter.extract_details(
        "cheque.pdf",
        log=logs.append,
        excel_ifsc="",
        excel_account="",
    )

    assert result.status == "unsupported"
    assert result.details == {}
    assert "uiic" in result.message
    assert logs == [result.message]


def test_ocr_incomplete_writes_structured_warn_only_event(tmp_path, monkeypatch):
    from app.automation.automation_logger import AutomationLogger

    monkeypatch.setattr(
        "app.utils.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    logger = AutomationLogger(
        section="ENGINE",
        log_cb=lambda _msg: None,
        portal_id="newindia",
        claim_no="CLAIM-OCR",
    )

    logger.ocr_incomplete(
        "Cheque",
        ["IFSC Code", "Account Number"],
        source_file="cheque.pdf",
        dependent_step="New India NEFT Details",
    )

    with open(logger._json_log_file, "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())

    assert entry["level"] == "WARNING"
    assert entry["extra"]["ocr_status"] == "failed_or_incomplete"
    assert entry["extra"]["policy"] == "warn_only_continue"
    assert entry["extra"]["dependent_step"] == "New India NEFT Details"


@pytest.mark.asyncio
async def test_deferred_ocr_missing_fields_continues_with_warn_only_policy(tmp_path, monkeypatch):
    import threading

    from app.automation.engine import AutomationEngine
    from app.data.data_model import ClaimData

    monkeypatch.setattr(
        "app.utils.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    claim = ClaimData(portal_id="newindia", claim_no="CLAIM-DEFERRED")
    event = threading.Event()
    event.set()
    claim._deferred_cheque_ocr_event = event
    claim._pending_cheque_path = "cheque.pdf"

    engine = AutomationEngine(portal_id="newindia", log_cb=lambda _msg: None)
    engine.log.set_claim_context(claim.claim_no, "newindia")

    ok = await engine._wait_for_deferred_ocr(
        claim,
        kind="cheque",
        label="Cheque",
        required_fields=(
            ("IFSC Code", "ifsc_code"),
            ("Account Number", "account_number"),
        ),
        dependent_step="New India NEFT Details",
    )

    assert ok is True
    with open(engine.log._json_log_file, "r", encoding="utf-8") as f:
        entries = [json.loads(line) for line in f]
    assert any(
        entry.get("extra", {}).get("ocr_status") == "failed_or_incomplete"
        for entry in entries
    )
