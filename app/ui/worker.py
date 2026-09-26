import asyncio
import threading
from PyQt6.QtCore import QObject, pyqtSignal

class AutomationWorker(QObject):
    log_signal  = pyqtSignal(str)
    step_signal = pyqtSignal(int, str)
    done_signal = pyqtSignal(bool, str)

    def __init__(self, claim, settings_override=None, portal_id: str = "uiic"):
        super().__init__()
        self.claim             = claim
        self.settings_override = settings_override
        self.portal_id         = portal_id
        self._engine           = None
        self._stop_event       = threading.Event()

    def run(self):
        from app.automation.engine import AutomationEngine
        loop = None
        success = False
        message = "Automation stopped before it started."
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._engine = AutomationEngine(
                log_cb    = lambda msg: self.log_signal.emit(msg),
                step_cb   = lambda i, s: self.step_signal.emit(i, s),
                portal_id = self.portal_id,
            )
            if self._stop_event.is_set():
                self._engine.request_stop()
            result = loop.run_until_complete(
                self._engine.run_automation(self.claim, self.settings_override)
            )
            success = bool(getattr(result, "success", False))
            message = getattr(result, "message", "Automation finished.")
        except BaseException as e:
            message = f"{type(e).__name__}: {e}"
        finally:
            if loop is not None:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                finally:
                    asyncio.set_event_loop(None)
                    try:
                        loop.close()
                    except Exception as exc:
                        success = False
                        message = f"Automation event loop could not close cleanly ({type(exc).__name__}): {exc}"
            self.done_signal.emit(success, message)

    def stop(self):
        self._stop_event.set()
        if self._engine:
            self._engine.request_stop()


class FolderScanWorker(QObject):
    done_signal = pyqtSignal(object)  # ClaimFolderProcessResult

    def __init__(
        self,
        folder: str,
        config_dir: str,
        portal_id: str = "uiic",
        scan_token: int = 0,
        main_excel_name=None,
    ):
        super().__init__()
        self.folder = folder
        self.config_dir = config_dir
        self.portal_id = portal_id
        self.scan_token = scan_token
        self.main_excel_name = main_excel_name
        self._stop_requested = False

    def request_stop(self):
        """Cooperative cancel signal called from UI thread."""
        self._stop_requested = True

    def run(self):
        from app.ui.services.claim_folder_service import ClaimFolderService
        from app.utils import scan_main_excel
        token = scan_main_excel.set(self.main_excel_name)
        try:
            service = ClaimFolderService(config_dir=self.config_dir, portal_id=self.portal_id)
            result = service.process_folder(self.folder, stop_cb=lambda: self._stop_requested)
            result.scan_token = self.scan_token
            result.scan_portal_id = self.portal_id
            result.scan_folder = self.folder
            self.done_signal.emit(result)
        except Exception as e:
            from app.ui.services.claim_folder_service import ClaimFolderProcessResult
            # Fail-safe backup result construction
            result = ClaimFolderProcessResult(
                success=False,
                scan_result=None,
                claim=None,
                log_lines=[f"❌ Folder scanning crashed ({type(e).__name__}): {e}"],
                error=f"{type(e).__name__}: {e}",
            )
            result.scan_token = self.scan_token
            result.scan_portal_id = self.portal_id
            result.scan_folder = self.folder
            self.done_signal.emit(result)
        finally:
            scan_main_excel.reset(token)

