"""Pause an OIC run in place until the desktop operator responds."""

import asyncio
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4
from urllib.parse import urlsplit

from app.portals.oic.automation import selectors as S


current_recovery = ContextVar("oic_recovery", default=None)


STEP_MARKERS = {
    "search": S.SEL_CLAIM_TYPE_DROPDOWN,
    "basic": S.SEL_REG_NUMBER,
    "interim": S.SEL_INITIAL_LOSS_AMOUNT,
    "upload": S.SEL_UPLOAD_REMARKS,
}


async def form_step_is_open(page, step):
    if page.is_closed():
        return False
    if step == "loss":
        has_import = await page.locator('input[type="file"][name="excel"]').count() > 0
        return has_import and await page.locator(S.SEL_LOSS_SALVAGE_AMT_INPUT).first.is_visible()
    return await page.locator(STEP_MARKERS[step]).first.is_visible()


def same_origin(page, portal_url):
    expected = urlsplit(portal_url)
    actual = urlsplit(page.url)
    return actual.scheme in ("https", "http") and (actual.scheme, actual.netloc) == (expected.scheme, expected.netloc)


async def portal_messages(page):
    return await page.locator(
        ".p-dialog-content:visible, .p-toast-detail:visible, .swal2-html-container:visible, "
        ".modal-body:visible, .error-message:visible, [role='alert']:visible"
    ).all_inner_texts()


@dataclass(frozen=True)
class RecoveryPrompt:
    id: str
    section: str
    action: str
    reason: str
    can_skip: bool
    instruction: str = ""


class OperatorRecovery:
    def __init__(self, notify, stopped):
        self.notify = notify
        self.stopped = stopped
        self.pending = None
        self.handled = {}

    def respond(self, prompt_id, decision):
        pending = self.pending
        if pending is None:
            return
        prompt, loop, result = pending
        if prompt_id != prompt.id or decision not in ("fixed", "skip"):
            return
        if decision == "skip" and not prompt.can_skip:
            return

        def deliver():
            if not result.done():
                result.set_result(decision)

        with suppress(RuntimeError):
            loop.call_soon_threadsafe(deliver)

    async def pause(self, page, log, action, reason, *, ready=None, instruction=None):
        section = getattr(log, "_section", None) or "OIC"
        # Record the document before anyone edits the form. A reload can discard
        # earlier unsaved work even if the address in Chrome looks the same.
        marker = uuid4().hex
        if ready is None and page and not page.is_closed():
            with suppress(Exception):
                await asyncio.wait_for(
                    page.evaluate("""(marker) => {
                        const step = document.querySelector('.p-steps-item.p-highlight, [aria-current="step"]');
                        window.__oicManualRecovery = {marker, href: location.href, step: step?.textContent};
                    }""", marker),
                    timeout=2,
                )
        detail = str(reason)[:1200]
        guidance = instruction or ""
        while not self.stopped():
            if page and not page.is_closed():
                with suppress(Exception):
                    await asyncio.wait_for(page.bring_to_front(), timeout=2)
            prompt = RecoveryPrompt(uuid4().hex, section, action, detail, ready is None, guidance)
            loop = asyncio.get_running_loop()
            result = loop.create_future()
            self.pending = (prompt, loop, result)
            try:
                self.notify(prompt)
                while not self.stopped() and not result.done():
                    await asyncio.wait({result}, timeout=0.2)
                if self.stopped():
                    break
                decision = result.result()
            finally:
                self.pending = None
                if not result.done():
                    result.cancel()

            if ready is not None:
                with suppress(Exception):
                    if await asyncio.wait_for(ready(), timeout=5):
                        log.info(f"OIC manual recovery: {action} completed by operator.")
                        return True
                detail = f"OIC has not reached the expected state yet.\n\n{str(reason)[:1200]}"
                continue
            if page and not page.is_closed():
                try:
                    same_document = await asyncio.wait_for(
                        page.evaluate("""(marker) => {
                            const saved = window.__oicManualRecovery;
                            const step = document.querySelector('.p-steps-item.p-highlight, [aria-current="step"]');
                            return saved?.marker === marker && saved.href === location.href && saved.step === step?.textContent;
                        }""", marker),
                        timeout=2,
                    )
                except Exception:
                    same_document = False
                if same_document:
                    self.handled[(id(page), section, action)] = decision
                    label = "handled manually" if decision == "fixed" else "skipped by operator"
                    log.info(f"OIC manual recovery: {section} / {action} {label}.")
                    return True
            detail = ("The original form is no longer open. Chrome has been left open. "
                      "Use Stop to end this run and review the claim.")
            guidance = "Review the claim in the open Chrome window."
        raise asyncio.CancelledError


async def field_problem(page, log, label, reason):
    recovery = current_recovery.get()
    if recovery is None:
        return False
    return await recovery.pause(page, log, label, reason)


def field_was_handled(page, log, label):
    return field_decision(page, log, label) is not None


def field_decision(page, log, label):
    recovery = current_recovery.get()
    if recovery is not None:
        return recovery.handled.get((id(page), getattr(log, "_section", None) or "OIC", label))
    return None


async def run_field(page, log, label, operation):
    try:
        return await operation()
    except Exception as exc:
        if not await field_problem(page, log, label, str(exc)):
            raise
        return None


async def action_problem(page, log, label, reason, ready, instruction=None):
    recovery = current_recovery.get()
    if recovery is None:
        return False
    return await recovery.pause(page, log, label, reason, ready=ready, instruction=instruction)
