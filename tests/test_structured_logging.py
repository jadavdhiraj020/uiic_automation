import os
import json
from app.automation.automation_logger import AutomationLogger


def test_automation_logger_structured_json(tmp_path, monkeypatch):
    # Mock user_data_dir to point to a temp directory
    monkeypatch.setattr(
        "app.utils.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    log_lines = []

    def log_cb(msg):
        log_lines.append(msg)

    logger = AutomationLogger(
        section="TEST_SECTION",
        log_cb=log_cb,
        portal_id="newindia",
        claim_no="TEST_CLAIM_123",
    )

    # Verify correlation ID is generated
    assert logger.correlation_id is not None

    # Emit info and success logs
    logger.info("Hello world")
    logger.success("Completed successfully")

    # Verify visual log callback received logs
    assert len(log_lines) == 2
    assert "ℹ️ Hello world" in log_lines[0]
    assert "✅ Completed successfully" in log_lines[1]

    # Verify claim JSON log file is created
    assert logger._json_log_file is not None
    assert os.path.isfile(logger._json_log_file)

    # Read the JSON file lines
    with open(logger._json_log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])

    assert entry1["claim_no"] == "TEST_CLAIM_123"
    assert entry1["portal_id"] == "newindia"
    assert entry1["section"] == "TEST_SECTION"
    assert entry1["level"] == "INFO"
    assert entry1["message"] == "Hello world"
    assert entry1["correlation_id"] == logger.correlation_id

    assert entry2["level"] == "INFO"  # success maps to py_level INFO
    assert entry2["message"] == "Completed successfully"


def test_automation_logger_exception_tracking(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.utils.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    logger = AutomationLogger(
        section="TEST_EXC",
        log_cb=lambda msg: None,
        portal_id="uiic",
        claim_no="CLAIM_456",
    )

    try:
        raise ValueError("Something went wrong")
    except Exception as e:
        logger.exception("Database query", e)

    assert os.path.isfile(logger._json_log_file)
    with open(logger._json_log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 1
    entry = json.loads(lines[0])

    assert entry["level"] == "ERROR"
    assert "Database query FAILED: ValueError: Something went wrong" in entry["message"]
    assert entry["extra"]["error_type"] == "ValueError"
    assert "Something went wrong" in entry["extra"]["error_message"]
    assert "traceback" in entry["extra"]
    assert "test_automation_logger_exception_tracking" in entry["extra"]["traceback"]


def test_oic_multiline_and_enhanced_logging(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.utils.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    log_lines = []

    def log_cb(msg):
        log_lines.append(msg)

    logger = AutomationLogger(
        section="Vehicle Details",
        log_cb=log_cb,
        portal_id="oic",
        claim_no="OIC_CLAIM_999",
    )

    # 1. Test field_filled with default source
    logger.field_filled("Registration Number", "GJ05AB1234")
    # 2. Test field_selected with custom source
    logger.field_selected("State", "Gujarat", source="Calculated")
    # 3. Test field_skipped
    logger.field_skipped("Mobile Number", "No value extracted from Excel")
    # 4. Test validation_failed
    logger.validation_failed(
        "License Expiry Date", "31-02-2025", "Invalid date", retry="2/3"
    )
    # 5. Test upload_start
    logger.upload_start("Final Invoice", "final_invoice.pdf")
    # 6. Test upload_attached
    logger.upload_attached("Final Invoice", "final_invoice.pdf")
    # 7. Test upload_failed
    logger.upload_failed("Claim Form", "File size too large")

    # Assertions on visual log lines
    # Check field_filled formatting
    assert any(
        "Vehicle Details] — Filling Registration Number" in line for line in log_lines
    )
    assert any("Source: Excel" in line for line in log_lines)
    assert any("Value:  GJ05AB1234" in line for line in log_lines)

    # Check field_selected formatting
    assert any("Vehicle Details] — Selecting State" in line for line in log_lines)
    assert any("Source: Calculated" in line for line in log_lines)
    assert any("Value:  Gujarat" in line for line in log_lines)

    # Check field_skipped formatting
    assert any("Vehicle Details] — Mobile Number skipped" in line for line in log_lines)
    assert any("Reason: No value extracted from Excel" in line for line in log_lines)

    # Check validation_failed formatting
    assert any(
        "Vehicle Details] — License Expiry Date validation failed" in line
        for line in log_lines
    )
    assert any("Value:  31-02-2025" in line for line in log_lines)
    assert any("Reason: Invalid date" in line for line in log_lines)
    assert any("Retry:  2/3" in line for line in log_lines)

    # Check upload_start formatting
    assert any(
        "Document Upload] — Uploading Final Invoice" in line for line in log_lines
    )
    assert any("File:   final_invoice.pdf" in line for line in log_lines)
    assert any("Status: In Progress" in line for line in log_lines)

    # Check upload_attached formatting
    assert any("Status: Success" in line for line in log_lines)

    # Check upload_failed formatting
    assert any("Status: Failed" in line for line in log_lines)
    assert any("Reason: File size too large" in line for line in log_lines)
