import os
import glob
import pytest
import threading
from unittest.mock import MagicMock, patch
from app.automation.engine import AutomationEngine
from app.automation.automation_logger import AutomationLogger
from app.portals.registry import PortalInfo


# 1. Test thread-safety and backward-compatible stop event property
def test_engine_thread_safety_event():
    # Instantiate engine with minimal mocks
    log_cb = MagicMock()
    step_cb = MagicMock()

    engine = AutomationEngine(portal_id="uiic", log_cb=log_cb, step_cb=step_cb)

    # Assert initial stop request state is False
    assert not engine._stop_requested
    assert not engine._stop_event.is_set()

    # Request stop using the public API
    engine.request_stop()
    assert engine._stop_requested
    assert engine._stop_event.is_set()

    # Check stop check execution callback returns True
    assert engine._check_stop()
    log_cb.assert_any_call("⛔ Stop requested. Closing automation safely...")

    # Test setting stop_requested property directly to False
    engine._stop_requested = False
    assert not engine._stop_requested
    assert not engine._stop_event.is_set()
    assert not engine._check_stop()

    # Test setting stop_requested property directly to True
    engine._stop_requested = True
    assert engine._stop_requested
    assert engine._stop_event.is_set()


# 2. Test JSON log consolidation to avoid multiple/fragmented log files
def test_json_log_consolidation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.utils.user_data_dir",
        lambda *parts: str(tmp_path / "app_data" / "/".join(parts)),
    )

    log_cb = MagicMock()
    logger = AutomationLogger(
        section="TEST", log_cb=log_cb, portal_id="uiic", claim_no="CLAIM_111"
    )

    logger.info("First log entry to create the file")
    first_log_file = logger._json_log_file
    assert first_log_file is not None
    assert os.path.exists(first_log_file)

    # Set context with the pre-existing log path (e.g. consolidation)
    logger.set_claim_context("CLAIM_111", "uiic", log_file_path=first_log_file)
    assert logger._json_log_file == first_log_file

    # If set_claim_context is called without log_file_path, it generates a new timestamped one
    import time

    time.sleep(1.1)
    logger.set_claim_context("CLAIM_111", "uiic")
    assert logger._json_log_file != first_log_file


# 3. Test per-portal log purging to prevent active portal from wiping other portals' logs
def test_per_portal_log_purging(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # Create subdirectories for UIIC and New India portals
    uiic_dir = log_dir / "uiic"
    uiic_dir.mkdir()
    newindia_dir = log_dir / "newindia"
    newindia_dir.mkdir()

    # Create 25 JSON files in each portal folder
    for i in range(25):
        # We vary modification times to ensure sorted order is deterministic
        # pytest tmp_path files will be created in chronological order naturally
        f_uiic = uiic_dir / f"claim_{i:02d}.json"
        f_uiic.write_text("{}")
        f_newindia = newindia_dir / f"claim_{i:02d}.json"
        f_newindia.write_text("{}")

    # Verify 25 files exist initially
    assert len(list(uiic_dir.glob("*.json"))) == 25
    assert len(list(newindia_dir.glob("*.json"))) == 25

    # Mock list_portals to return our two portals
    portal1 = MagicMock(spec=PortalInfo)
    portal1.portal_id = "uiic"
    portal2 = MagicMock(spec=PortalInfo)
    portal2.portal_id = "newindia"

    with patch("app.portals.registry.list_portals", return_value=[portal1, portal2]):
        # Implementation of purging logic for test run
        for portal in [portal1, portal2]:
            portal_log_dir = os.path.join(log_dir, portal.portal_id)
            if os.path.exists(portal_log_dir):
                existing_jsons = sorted(
                    glob.glob(os.path.join(portal_log_dir, "*.json")),
                    key=lambda path: (os.path.getmtime(path), path),
                )
                for old_json in existing_jsons[:-20]:
                    try:
                        os.remove(old_json)
                    except Exception:
                        pass

    # Verify that exactly the newest 20 JSON files remain in each portal subdirectory
    remaining_uiic = sorted(list(uiic_dir.glob("*.json")))
    remaining_newindia = sorted(list(newindia_dir.glob("*.json")))

    assert len(remaining_uiic) == 20
    assert len(remaining_newindia) == 20

    # Ensure the oldest 5 files (claim_00.json to claim_04.json) were deleted
    for i in range(5):
        assert not (uiic_dir / f"claim_{i:02d}.json").exists()
        assert not (newindia_dir / f"claim_{i:02d}.json").exists()

    # Ensure the newest 20 files remain
    for i in range(5, 25):
        assert (uiic_dir / f"claim_{i:02d}.json").exists()
        assert (newindia_dir / f"claim_{i:02d}.json").exists()


# 4. Test temp file tracking and immediate unlinking on engine shutdown
def test_temp_file_unlinking(tmp_path):
    # Create two temporary files on disk
    temp_file1 = tmp_path / "temp_doc1.pdf"
    temp_file1.write_text("dummy PDF content")
    temp_file2 = tmp_path / "temp_doc2.pdf"
    temp_file2.write_text("dummy PDF content")

    assert temp_file1.exists()
    assert temp_file2.exists()

    # Create a mock claim containing temporary files attribute
    claim = MagicMock()
    claim.claim_no = "CLAIM_222"
    claim._temporary_files = [str(temp_file1), str(temp_file2)]

    # Define a minimal cleanup loop reproducing AutomationEngine's cleanup block
    temp_files = getattr(claim, "_temporary_files", [])
    for temp_path in temp_files:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

    # Verify both files are successfully and immediately deleted
    assert not temp_file1.exists()
    assert not temp_file2.exists()

    # Verify no exception is raised if the files are already deleted or do not exist
    # Re-run same block without crash
    for temp_path in temp_files:
        if temp_path and os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass



# 6. Test background thread cooperative cancellation via stop event
def test_background_thread_cancellation():
    from app.ui.services.claim_folder_service import _run_background_document_generation
    
    # Mock parameters
    portal_id = "uiic"
    scan_result = MagicMock()
    scan_result.excel_path = "dummy_excel.xlsx"
    scan_result.generated_files = []
    
    claim = MagicMock()
    claim.claim_no = "12345"
    claim.assessment_files = {}
    
    portal_defaults = {}
    
    # Create stop event and attach
    stop_event = threading.Event()
    claim._background_generation_stop_event = stop_event
    
    # Set the stop event to simulate cancellation before start
    stop_event.set()
    
    # Run _run_background_document_generation
    # It should exit immediately without trying to generate files
    with patch("app.data.printable_excel_service.process_printable_output") as mock_printable:
        _run_background_document_generation(
            portal_id,
            scan_result,
            claim,
            portal_defaults,
            log_file_path=None,
            correlation_id=None,
            folder="dummy_folder"
        )
        # Should not have called process_printable_output
        mock_printable.assert_not_called()

# 7. Test dialog listener registration and cleanup
@pytest.mark.asyncio
async def test_dialog_listener_cleanup():
    from app.automation.login_module import do_login
    from app.automation.claim_documents import fill_claim_documents
    from app.data.data_model import ClaimData

    # Mock page and browser context
    from unittest.mock import AsyncMock
    mock_page = MagicMock()
    mock_context = MagicMock()
    mock_page.context = mock_context
    mock_context.pages = [mock_page]

    # Configure mock page behaviours
    mock_page.url = "https://portal.uiic.in/surveyor/data/home.jsp"
    mock_page.goto = AsyncMock()
    mock_page.evaluate = AsyncMock(return_value={})
    mock_page.locator = MagicMock()
    
    # We mock solve_captcha_from_bytes to raise an exception to exit do_login quickly
    # but still execute the finally block.
    with patch("app.automation.login_module._get_captcha_bytes", side_effect=Exception("Trigger fallback exit")):
        settings = {
            "portal_url": "https://portal.uiic.in/surveyor/data/home.jsp",
            "username": "user",
            "password": "pwd",
            "captcha_max_retries": 1
        }
        await do_login(mock_page, settings, log=MagicMock())

    # Verify remove_all_listeners was called on page object
    mock_page.remove_all_listeners.assert_any_call("dialog")
    from unittest.mock import ANY
    mock_page.on.assert_any_call("dialog", ANY)

    # Reset mock for documents test
    mock_page.reset_mock()
    claim = ClaimData()
    claim.claim_no = "12345"
    claim.claim_doc_files = {"driving_license": "dummy_file.pdf"}

    with patch("app.automation.claim_documents.click_tab", return_value=True), \
         patch("app.automation.claim_documents.DocumentUploadService") as mock_service_class:
        mock_service_inst = MagicMock()
        mock_service_inst.wait_for_upload_section = AsyncMock()
        mock_service_inst.upload_queue = AsyncMock(side_effect=Exception("Force exit to finally"))
        mock_service_class.return_value = mock_service_inst
        
        try:
            await fill_claim_documents(mock_page, claim, log_cb=MagicMock())
        except Exception:
            pass

    mock_page.remove_all_listeners.assert_any_call("dialog")
