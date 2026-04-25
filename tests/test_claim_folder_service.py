from types import SimpleNamespace

from app.ui.services.claim_folder_service import ClaimFolderService


def test_process_folder_success_with_excel(monkeypatch, tmp_path):
    excel_file = tmp_path / "report.xlsx"
    excel_file.write_text("dummy", encoding="utf-8")

    fake_scan = SimpleNamespace(
        excel_path=str(excel_file),
        claim_doc_files={"PAN Card": str(excel_file)},
        assessment_files={},
        skipped_files=[],
        unknown_files=[],
    )

    fake_claim = SimpleNamespace(
        claim_no="123",
        claim_doc_files={},
        assessment_files={},
        _excel_logs=["  📊 claim_no: '123' (Source: R1C1)"],
        _excel_coords={},
    )

    monkeypatch.setattr("app.data.folder_scanner.scan_folder", lambda _folder: fake_scan)
    monkeypatch.setattr("app.data.excel_reader.read_excel", lambda _path, _cfg: fake_claim)

    service = ClaimFolderService(config_dir="app/config")
    result = service.process_folder(str(tmp_path))

    assert result.success is True
    assert result.scan_result is fake_scan
    assert result.claim is fake_claim
    assert any("Excel:" in line for line in result.log_lines)


def test_process_folder_without_excel(monkeypatch, tmp_path):
    fake_scan = SimpleNamespace(
        excel_path=None,
        claim_doc_files={},
        assessment_files={},
        skipped_files=[],
        unknown_files=[],
    )

    monkeypatch.setattr("app.data.folder_scanner.scan_folder", lambda _folder: fake_scan)

    service = ClaimFolderService(config_dir="app/config")
    result = service.process_folder(str(tmp_path))

    assert result.success is False
    assert result.scan_result is fake_scan
    assert result.claim is None
    assert "No Excel file found" in result.error
    assert any("No Excel file found" in line for line in result.log_lines)
