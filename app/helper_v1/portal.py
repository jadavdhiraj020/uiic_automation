"""Portal-adapter boundary; only the proven UIIC engine is enabled in V1."""

from abc import ABC, abstractmethod
import asyncio

from app.automation.engine import AutomationEngine
from app.utils import load_settings


class PortalAdapter(ABC):
    @abstractmethod
    def run(self, context, prepared, on_progress, on_review, on_submission, set_engine, stop_requested):
        raise NotImplementedError


class UiicAdapter(PortalAdapter):
    def run(self, context, prepared, on_progress, on_review, on_submission, set_engine, stop_requested):
        settings = load_settings(portal_id="uiic")
        settings.update({
            "username": context.portal_username,
            "password": context.portal_password,
            "surveyor_code": context.surveyor_code,
            "browser_headless": False,
            "_web_submission": {
                "case_id": prepared.case_id,
                "automation_dispatch_id": context.dispatch_id,
                "folder": str(prepared.folder),
                "callback": on_submission,
            },
        })
        def step(index, label):
            on_progress(f"UIIC: {label}")
            if index == 5:
                # Existing engine calls step 5 immediately before manual review.
                on_review()

        engine = AutomationEngine(portal_id="uiic", log_cb=on_progress, step_cb=step)
        set_engine(engine)
        if stop_requested():
            engine.request_stop()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(engine.run_automation(prepared.claim, settings))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                asyncio.set_event_loop(None)
                loop.close()
