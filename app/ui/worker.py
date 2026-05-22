import asyncio
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

    def run(self):
        from app.automation.engine import AutomationEngine
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._engine = AutomationEngine(
            log_cb    = lambda msg: self.log_signal.emit(msg),
            step_cb   = lambda i, s: self.step_signal.emit(i, s),
            portal_id = self.portal_id,
        )
        try:
            result = loop.run_until_complete(
                self._engine.run_automation(self.claim, self.settings_override)
            )
            success = bool(getattr(result, "success", False))
            message = getattr(result, "message", "Automation finished.")
            self.done_signal.emit(success, message)
        except BaseException as e:
            self.done_signal.emit(False, str(e))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            asyncio.set_event_loop(None)
            loop.close()

    def stop(self):
        if self._engine:
            self._engine.request_stop()


class FolderScanWorker(QObject):
    done_signal = pyqtSignal(object)  # ClaimFolderProcessResult

    def __init__(self, folder: str, config_dir: str, portal_id: str = "uiic"):
        super().__init__()
        self.folder = folder
        self.config_dir = config_dir
        self.portal_id = portal_id

    def run(self):
        from app.ui.services.claim_folder_service import ClaimFolderService
        try:
            service = ClaimFolderService(config_dir=self.config_dir, portal_id=self.portal_id)
            result = service.process_folder(self.folder)
            self.done_signal.emit(result)
        except Exception as e:
            from app.ui.services.claim_folder_service import ClaimFolderProcessResult
            # Fail-safe backup result construction
            result = ClaimFolderProcessResult(
                success=False,
                scan_result=None,
                claim=None,
                log_lines=[f"❌ Folder scanning crashed: {e}"],
                error=str(e),
            )
            self.done_signal.emit(result)

