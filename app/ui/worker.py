import asyncio
from PyQt6.QtCore import QObject, pyqtSignal

class AutomationWorker(QObject):
    log_signal  = pyqtSignal(str)
    step_signal = pyqtSignal(int, str)
    done_signal = pyqtSignal(bool, str)

    def __init__(self, claim, settings_override):
        super().__init__()
        self.claim             = claim
        self.settings_override = settings_override
        self._engine           = None

    def run(self):
        from app.automation.engine import AutomationEngine
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._engine = AutomationEngine(
            log_cb  = lambda msg: self.log_signal.emit(msg),
            step_cb = lambda i, s: self.step_signal.emit(i, s),
        )
        try:
            result = loop.run_until_complete(
                self._engine.run(self.claim, self.settings_override)
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
