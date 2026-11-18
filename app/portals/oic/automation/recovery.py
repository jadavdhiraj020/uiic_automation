"""Pause an OIC run in place until the desktop operator responds."""

import asyncio
import re
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4
from urllib.parse import urlsplit

from app.portals.oic.automation import selectors as S


current_recovery = ContextVar("oic_recovery", default=None)


STEP_MARKERS = {
    "search": ("Search", S.SEL_CLAIM_TYPE_DROPDOWN),
    "basic": ("Basic Details", f"{S.SEL_REG_NUMBER}, {S.SEL_MAKE}, {S.SEL_CHASSIS_NUMBER}"),
    "interim": ("Interim Report", f"{S.SEL_PLACE_OF_SURVEY}, {S.SEL_INITIAL_LOSS_AMOUNT}"),
    "loss": ("Assessment of Loss", f"{S.SEL_LOSS_INV_NO}, {S.SEL_LOSS_SALVAGE_AMT_INPUT}"),
    "upload": ("Document Upload", S.SEL_UPLOAD_REMARKS),
}

ACTIVE_STEP = (
    '.p-steps-item.p-highlight:visible, '
    '.p-steps-item.ui-state-highlight:visible, .p-steps-item:has([aria-selected="true"]):visible'
)
BLOCKING_DIALOG = '[role="dialog"][aria-modal="true"]:visible, .p-dialog-mask .p-dialog:visible, .swal2-popup:visible'


async def form_step_is_open(page, step):
    if page.is_closed() or await page.locator(BLOCKING_DIALOG).count():
        return False
    title, markers = STEP_MARKERS[step]
    known_titles = {name.casefold() for name, _ in STEP_MARKERS.values()}
    for selector in ('[aria-current="step"]:visible', ACTIVE_STEP):
        active = await page.locator(selector).all_inner_texts()
        active_titles = {re.sub(r"^[\W\d]+", "", text).strip().casefold() for text in active} & known_titles
        if len(active_titles) == 1:
            return title.casefold() in active_titles
    visible_markers = ", ".join(f"{selector.strip()}:visible" for selector in markers.split(","))
    if await page.locator(visible_markers).count():
        return True
    return step == "upload" and bool(await page.locator(f"input[type=file]{S.SEL_UPLOAD_WORKSHOP_ESTIMATE}").count())


async def assessment_claim_mismatch(page, expected):
    identifier = lambda value: re.sub(r"[\W_]", "", str(value or "")).casefold()
    if not identifier(expected):
        return False
    control = page.locator('input#claimNumber:is([readonly], [disabled]):visible').first
    if not await control.is_visible():
        return False
    shown = identifier(await control.input_value(timeout=1000))
    return bool(shown and shown != identifier(expected))


async def wait_until_ready(ready, *, seconds, stopped=lambda: False):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not stopped() and loop.time() < deadline:
        with suppress(Exception):
            if await asyncio.wait_for(ready(), timeout=min(2, deadline - loop.time())):
                return True
        await asyncio.sleep(0.2)
    return False


def same_origin(page, portal_url):
    expected = urlsplit(portal_url)
    actual = urlsplit(page.url)
    return actual.scheme in ("https", "http") and (actual.scheme, actual.netloc) == (expected.scheme, expected.netloc)


async def portal_messages(page):
    return await page.locator(
        ".p-dialog-content:visible, .p-toast-detail:visible, .swal2-html-container:visible, "
        ".modal-body:visible, .error-message:visible, [role='alert']:visible"
    ).all_inner_texts()


def operator_reason(reason, fallback):
    text = " ".join(str(reason or "").split())
    if not text or re.search(r"(?:Call log:|Timeout \d+ms|^Locator\.|^Page\.|^Browser|Traceback|\[WinError|\[Errno)", text, re.I):
        return fallback
    if len(text) > 180:
        return fallback
    if text.casefold().startswith("empty"):
        return "No usable value was found for this field."
    return text


@dataclass(frozen=True)
class RecoveryPrompt:
    id: str
    section: str
    action: str
    reason: str
    can_skip: bool
    instruction: str = ""
    stop_only: bool = False


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
        if prompt.stop_only or prompt_id != prompt.id or decision not in ("fixed", "skip"):
            return
        if decision == "skip" and not prompt.can_skip:
            return

        def deliver():
            if not result.done():
                result.set_result(decision)

        with suppress(RuntimeError):
            loop.call_soon_threadsafe(deliver)

    async def pause(
        self, page, log, action, reason, *, ready=None, instruction=None, describe=None, section=None, stop_only=False,
    ):
        section = section or getattr(log, "_section", None) or "OIC"
        # Record the document before anyone edits the form. A reload can discard
        # earlier unsaved work even if the address in Chrome looks the same.
        marker = uuid4().hex
        if ready is None and not stop_only and page and not page.is_closed():
            with suppress(Exception):
                await asyncio.wait_for(
                    page.evaluate("""(marker) => {
                        const step = document.querySelector('.p-steps-item.p-highlight, [aria-current="step"]');
                        window.__oicManualRecovery = {marker, href: location.href, step: step?.textContent};
                    }""", marker),
                    timeout=2,
                )
        detail = operator_reason(reason, "")
        guidance = instruction or ""
        title = action
        while not self.stopped():
            if describe:
                with suppress(Exception):
                    description = await asyncio.wait_for(describe(), timeout=2)
                    if description:
                        title, detail = description
            if ready is not None and await wait_until_ready(ready, seconds=0.4, stopped=self.stopped):
                self.notify(None)
                return True
            if self.stopped():
                break
            if page and not page.is_closed():
                with suppress(Exception):
                    await asyncio.wait_for(page.bring_to_front(), timeout=2)
            prompt = RecoveryPrompt(uuid4().hex, section, title, detail, ready is None and not stop_only, guidance, stop_only)
            loop = asyncio.get_running_loop()
            result = loop.create_future()
            self.pending = (prompt, loop, result)
            try:
                log.warning(f"OIC paused at {section} / {title}. {detail}")
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
                if await wait_until_ready(ready, seconds=3, stopped=self.stopped):
                    log.info(f"OIC manual recovery: {action} completed by operator.")
                    self.notify(None)
                    return True
                title, detail = action, "The expected page hasn’t opened yet."
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
                    self.notify(None)
                    return True
            title = "The OIC form changed"
            detail = "App3 can no longer resume at this field."
            guidance = "Stop this run. Any open Chrome tab stays available for review."
            stop_only = True
        raise asyncio.CancelledError


async def field_problem(page, log, label, reason):
    recovery = current_recovery.get()
    if recovery is None:
        return False
    detail = operator_reason(reason, "App3 could not fill this field in OIC.")
    return await recovery.pause(page, log, label, detail)


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


async def action_problem(page, log, label, reason, ready, instruction=None, *, describe=None):
    recovery = current_recovery.get()
    if recovery is None:
        return False
    return await recovery.pause(page, log, label, reason, ready=ready, instruction=instruction, describe=describe)
