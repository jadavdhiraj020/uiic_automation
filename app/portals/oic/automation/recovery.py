"""Pause an OIC run in place until the desktop operator responds."""

import asyncio
import re
import threading
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4
from urllib.parse import urlsplit

from app.portals.oic.automation import selectors as S
from app.portals.oic.automation.review_browser import bring_browser_window_to_front, focus_chrome


class _NullLogger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


current_recovery = ContextVar("oic_recovery", default=None)


STEP_MARKERS = {
    "search": ("Search", S.SEL_CLAIM_TYPE_DROPDOWN),
    "basic": ("Basic Details", f"{S.SEL_REG_NUMBER}, {S.SEL_MAKE}, {S.SEL_CHASSIS_NUMBER}"),
    "interim": ("Interim Report", f"{S.SEL_PLACE_OF_SURVEY}, {S.SEL_INITIAL_LOSS_AMOUNT}"),
    "loss": ("Assessment of Loss", f"{S.SEL_LOSS_INV_NO}, {S.SEL_LOSS_SALVAGE_AMT_INPUT}"),
    "upload": ("Document Upload", S.SEL_UPLOAD_REMARKS),
}
VISIBLE_STEP_MARKERS = {
    step: ", ".join(f"{selector.strip()}:visible" for selector in markers.split(","))
    for step, (_, markers) in STEP_MARKERS.items()
}

ACTIVE_STEP = (
    '.p-steps-item.p-highlight:visible, '
    '.p-steps-item.ui-state-highlight:visible, .p-steps-item:has([aria-selected="true"]):visible'
)
BLOCKING_DIALOG = '[role="dialog"][aria-modal="true"]:visible, .p-dialog-mask .p-dialog:visible, .swal2-popup:visible'


async def active_form_step(page):
    known_titles = {name.casefold(): step for step, (name, _) in STEP_MARKERS.items()}
    for selector in ('[aria-current="step"]:visible', ACTIVE_STEP):
        active = await page.locator(selector).all_inner_texts()
        titles = {re.sub(r"^[\W\d]+", "", text).strip().casefold() for text in active}
        active_steps = {known_titles[title] for title in titles if title in known_titles}
        if len(active_steps) == 1:
            return active_steps.pop()
    return None


async def form_step_is_open(page, step):
    if page.is_closed() or await page.locator(BLOCKING_DIALOG).count():
        return False
    active = await active_form_step(page)
    if active is not None and active != step:
        return False
    if await page.locator(VISIBLE_STEP_MARKERS[step]).count():
        if active is not None:
            return True
        others = ", ".join(markers for other, markers in VISIBLE_STEP_MARKERS.items() if other != step)
        return not await page.locator(others).count()
    if active != step:
        return False
    if step == "loss":
        return bool(await page.locator('input[type=file][name=excel]').count())
    return step == "upload" and bool(await page.locator(f"input[type=file]{S.SEL_UPLOAD_WORKSHOP_ESTIMATE}").count())


async def assessment_claim_mismatch(page, expected, policy_number=None):
    identifier = lambda value: re.sub(r"[\W_]", "", str(value or "")).casefold()
    for selector, wanted in ((S.SEL_CLAIM_NUMBER_INPUT, expected), (S.SEL_POLICY_NUMBER_INPUT, policy_number)):
        wanted = identifier(wanted)
        if wanted:
            control = page.locator(f'input{selector}:is([readonly], [disabled]):visible').first
            if await control.is_visible():
                shown = identifier(await control.input_value(timeout=1000))
                if shown and shown != wanted:
                    return True
    return False


async def wait_until_ready(ready, *, seconds, stopped=lambda: False):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not stopped() and loop.time() < deadline:
        with suppress(Exception):
            if await asyncio.wait_for(ready(), timeout=min(2, deadline - loop.time())):
                return not stopped()
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
    if re.search(r"\b(?:required|mandatory|requires a value)\b", text, re.I):
        return "OIC requires a value here."
    if re.search(r"\b(?:empty|no usable value|no file|file not found)\b", text, re.I):
        return "No usable value was found for this field."
    if re.search(r"\b(?:file size|too large|maximum size|exceeds the limit)\b", text, re.I):
        return "File size too large"
    if re.search(r"\b(?:unsupported|file type|file format|did not accept this format)\b", text, re.I):
        return "OIC did not accept this format."
    if re.search(r"\b(?:invalid|validation errors|rejected)\b", text, re.I):
        return "OIC rejected the value. Check the portal message in Chrome."
    if re.search(r"\b(?:did not keep|did not stay|did not retain|did not persist)\b", text, re.I):
        return "The value did not stay in the field after entry."
    if re.search(r"\b(?:no match|could not match|did not offer|no .{1,20} mapping|not available in the picker)\b", text, re.I):
        return "App3 could not match this value to an OIC option."
    if re.search(r"\b(?:timeout|timed out|did not respond in time)\b", text, re.I):
        return "OIC did not respond in time."
    return fallback


@dataclass(frozen=True)
class RecoveryPrompt:
    id: str
    section: str
    action: str
    reason: str
    can_skip: bool
    instruction: str = ""
    stop_only: bool = False
    confirmation_button: str = ""
    skip_button: str = ""
    kind: str = "pause"


class OperatorRecovery:
    def __init__(self, notify, stopped, *, portal_name="OIC"):
        self.notify = notify
        self.stopped = stopped
        self.portal_name = portal_name
        self.pending = None
        self.handled = {}
        self.form_step = None
        self.form_marker = None
        self.transition_started = False
        self.claim_number = None
        self.policy_number = None
        self.browser_pid = None
        self.active_page = None
        self._loop = None
        self._manual_pause_requested = threading.Event()
        self._manual_paused = False

    def attach_browser(self, page, browser_pid=None):
        if page is not None:
            self.active_page = page
        if browser_pid is not None:
            self.browser_pid = browser_pid
        with suppress(RuntimeError):
            self._loop = asyncio.get_running_loop()

    def focus_chrome(self):
        bring_browser_window_to_front(self.browser_pid)
        loop = self._loop
        page = self.active_page
        if loop is None or loop.is_closed() or page is None:
            return

        def _raise_tab():
            if not page.is_closed():
                asyncio.ensure_future(focus_chrome(page, self.browser_pid))

        with suppress(RuntimeError):
            loop.call_soon_threadsafe(_raise_tab)

    def request_manual_pause(self) -> bool:
        if self.stopped() or self.pending is not None or self._manual_paused:
            return False
        self._manual_pause_requested.set()
        return True

    def resume_manual_pause(self) -> bool:
        self._manual_pause_requested.clear()
        pending = self.pending
        if pending is not None and pending[0].action == "Automation Paused":
            self.respond(pending[0].id, "fixed")
            return True
        return False

    async def wait_if_manually_paused(self, page=None, log=None, section=None) -> None:
        if not self._manual_pause_requested.is_set():
            return
        if self.stopped():
            raise asyncio.CancelledError
        if self._manual_paused or self.pending is not None:
            return
        self._manual_paused = True
        target_page = page if page is not None else self.active_page
        active_log = log or _NullLogger()
        sec_name = section or getattr(active_log, "_section", None) or "Paused by Operator"
        manual_confirmed = False

        async def manual_ready():
            return manual_confirmed and not (target_page and target_page.is_closed())

        async def clear_manual():
            nonlocal manual_confirmed
            manual_confirmed = True
            self._manual_pause_requested.clear()

        try:
            await self.pause(
                target_page,
                active_log,
                "Automation Paused",
                "You paused automation. Make any changes you need in Chrome.",
                section=sec_name,
                ready=manual_ready,
                instruction="Review or edit Chrome, then click Resume here or in the app.",
                confirmation_button="Resume",
                on_continue=clear_manual,
            )
        finally:
            self._manual_paused = False
            self._manual_pause_requested.clear()

    async def bind_form(self, page, step):
        """Remember this document before editing the form."""
        marker = uuid4().hex
        await page.evaluate("""marker => {
            window.__oicManualRecovery = {
                marker, route: location.origin + location.pathname + location.search
            };
        }""", marker)
        self.form_step = step
        self.form_marker = marker
        self.transition_started = False
        if step == "basic" and not self.claim_number:
            control = page.locator(f'input{S.SEL_CLAIM_NUMBER_INPUT}:is([readonly], [disabled]):visible').first
            if await control.is_visible():
                self.claim_number = await control.input_value(timeout=1000)

    async def is_original_document(self, page, *, allow_route_change=False):
        if page.is_closed() or not self.form_marker:
            return False
        return await page.evaluate("""([marker, allowRouteChange]) => {
            const saved = window.__oicManualRecovery;
            return saved?.marker === marker &&
                (allowRouteChange || saved.route === location.origin + location.pathname + location.search);
        }""", [self.form_marker, allow_route_change])

    def field_key(self, page, section, action):
        return (id(page), self.form_step, section, action)

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
        confirmation_button="", require_original=False, field_ready=None, skip_button="", on_skip=None, on_continue=None,
    ):
        portal = self.portal_name
        section = section or getattr(log, "_section", None) or portal
        detail = reason or f"{portal} did not confirm that this action finished."
        guidance = instruction or ""
        title = action
        prompt_id = uuid4().hex
        first_prompt = True
        with suppress(RuntimeError):
            self._loop = asyncio.get_running_loop()
        if page is not None:
            self.active_page = page
        while not self.stopped():
            if describe:
                with suppress(Exception):
                    description = await asyncio.wait_for(describe(), timeout=2)
                    if description:
                        _, detail = description
            if first_prompt and ready is not None and await wait_until_ready(ready, seconds=0.4, stopped=self.stopped):
                return True
            if self.stopped():
                break
            if first_prompt and page and not page.is_closed():
                if self.portal_name != "New India":
                    from app.automation.chrome_hud import current_field_tracker, update_field_hud
                    from app.automation.run_diagnostics import capture_portal_screenshot

                    tracker = current_field_tracker.get()
                    filled = getattr(tracker, "fields_filled", 0) if tracker else 0
                    failed = getattr(tracker, "fields_failed", 0) if tracker else 0
                    skipped = getattr(tracker, "fields_skipped", 0) if tracker else 0
                    await update_field_hud(
                        page, section, title or "Paused for review", "paused",
                        filled=filled, failed=failed, skipped=skipped,
                    )
                    if title != "Automation Paused" and not stop_only:
                        await capture_portal_screenshot(
                            page, "oic", f"paused_{section}", log, reason=title, claim_no=self.claim_number or "",
                        )
                await focus_chrome(page, self.browser_pid)
            prompt = RecoveryPrompt(
                prompt_id, section, title, detail,
                not stop_only and (on_skip is not None if ready is not None else not confirmation_button),
                guidance, stop_only, confirmation_button, skip_button,
            )
            loop = asyncio.get_running_loop()
            result = loop.create_future()
            self.pending = (prompt, loop, result)
            try:
                if first_prompt:
                    log.warning(f"{portal} paused at {section} — {action}. {detail}")
                first_prompt = False
                self.notify(prompt)
                while not self.stopped() and not result.done():
                    if require_original and page and page.is_closed():
                        break
                    await asyncio.wait({result}, timeout=0.2)
                if self.stopped():
                    break
                if not result.done():
                    detail = "The original tab was closed or reloaded."
                    guidance = "Stop this run and review Chrome."
                    stop_only = True
                    describe = None
                    log.warning(f"{portal} is still paused at {section} — {action}. {detail}")
                    continue
                decision = result.result()
            finally:
                self.pending = None
                if not result.done():
                    result.cancel()

            if ready is not None:
                if decision == "skip" and on_skip is not None:
                    try:
                        await on_skip()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        log.warning(f"{portal} skip action hit a temporary Chrome error: {exc}")
                elif decision == "fixed" and on_continue is not None:
                    try:
                        await on_continue()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        log.warning(f"{portal} continue action hit a temporary Chrome error: {exc}")
                if await wait_until_ready(ready, seconds=3, stopped=self.stopped):
                    log.info(f"{portal} resumed at {section} after confirming {action} in Chrome.")
                    self.notify(None)
                    return True
                same_document = True
                if require_original:
                    with suppress(Exception):
                        same_document = await self.is_original_document(page, allow_route_change=self.transition_started)
                detail = f"{portal} has not confirmed this action yet."
                if not same_document:
                    detail = "The original tab was closed or reloaded."
                    guidance = "Stop this run and review Chrome."
                    stop_only = True
                    describe = None
                log.warning(f"{portal} is still paused at {section} — {action}. {detail}")
                continue
            state = "unconfirmed"

            async def check_form():
                nonlocal state
                state = await self._field_resume_state(page)
                if state == "same" and decision == "fixed" and field_ready is not None:
                    state = "field_pending"
                    if await field_ready():
                        state = "same"
                return state in ("same", "closed", "reloaded", "different_step", "different_claim")

            await wait_until_ready(check_form, seconds=4, stopped=self.stopped)
            if self.stopped():
                break
            if state == "same":
                if confirmation_button:
                    label = "confirmed by operator"
                else:
                    self.handled[self.field_key(page, section, action)] = decision
                    label = "handled manually" if decision == "fixed" else "skipped by operator"
                log.info(f"{portal} resumed at {section} — {action} was {label}.")
                self.notify(None)
                return True
            if state in ("closed", "reloaded"):
                detail = "The tab was closed or reloaded. App3 couldn’t verify the original form."
                guidance = "Stop this run. Any open Chrome tab stays available for review."
                stop_only = True
            elif state == "different_claim":
                detail = "Chrome is showing a different claim."
                guidance = "Open the original claim and step in Chrome, then click Continue."
            elif state == "field_pending":
                if confirmation_button:
                    detail = "App3 could not verify that this action is complete in Chrome."
                    guidance = instruction or "Complete this action in Chrome, then click Continue."
                else:
                    detail = "The field is still empty or invalid."
                    guidance = "Correct it in Chrome, then click Continue. You can also skip this field."
            else:
                detail = f"App3 needs the original {portal} step to finish the remaining fields."
                guidance = "Return to the original step in Chrome, close any portal messages, then click Continue."
            log.warning(f"{portal} is still paused at {section} — {action}. {detail}")
        log.info(f"{portal} stopped while paused at {section} — {action}.")
        raise asyncio.CancelledError

    async def _field_resume_state(self, page):
        if page.is_closed():
            return "closed"
        if not await self.is_original_document(page):
            return "reloaded"
        if await assessment_claim_mismatch(page, self.claim_number, self.policy_number):
            return "different_claim"
        if self.form_step and await form_step_is_open(page, self.form_step):
            return "same"
        active = await active_form_step(page)
        if active and active != self.form_step:
            return "different_step"
        return "unconfirmed"


async def field_problem(page, log, label, reason):
    recovery = current_recovery.get()
    if recovery is None:
        return False
    if field_was_handled(page, log, label):
        return True
    detail = operator_reason(reason, "App3 could not fill this field in OIC.")
    return await recovery.pause(page, log, label, detail)


async def confirm_field_values(page, log, label, reason, instruction):
    """Require the operator's approval before filling values that need review."""
    recovery = current_recovery.get()
    if recovery is None:
        return False
    return await recovery.pause(
        page, log, label, reason, instruction=instruction,
        confirmation_button="Continue with these values",
    )


def field_was_handled(page, log, label):
    return field_decision(page, log, label) is not None


def field_decision(page, log, label):
    recovery = current_recovery.get()
    if recovery is not None:
        return recovery.handled.get(recovery.field_key(page, getattr(log, "_section", None) or "OIC", label))
    return None


async def run_field(page, log, label, operation):
    recovery = current_recovery.get()
    if recovery is not None:
        await recovery.wait_if_manually_paused(page, log)
    if field_was_handled(page, log, label):
        return None
    try:
        return await operation()
    except Exception as exc:
        if not await field_problem(page, log, label, str(exc)):
            raise
        return None


async def action_problem(page, log, label, reason, ready, instruction=None, *, describe=None, final=False):
    recovery = current_recovery.get()
    if recovery is None:
        return False
    origin = page.url

    async def verified():
        if final:
            return (same_origin(page, origin) and not await assessment_claim_mismatch(
                page, recovery.claim_number, recovery.policy_number,
            ) and await ready())
        return await recovery._field_resume_state(page) == "same" and await ready()

    detail = operator_reason(reason, "OIC did not confirm that this action finished. Check Chrome.")
    return await recovery.pause(page, log, label, detail, ready=verified, instruction=instruction,
                                describe=describe, require_original=not final)
