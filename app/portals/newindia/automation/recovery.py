"""Pause the New India run in place and verify its claim before continuing."""

import asyncio
import re
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from uuid import uuid4

from app.portals.oic.automation.recovery import OperatorRecovery, wait_until_ready


current_recovery = ContextVar("newindia_recovery", default=None)

_BLOCKING_DIALOGS = (
    '.modal.in:visible, .modal[style*="display"]:visible, .swal2-popup:visible, '
    '.ngdialog.ngdialog-open:visible, [role="dialog"][aria-modal="true"]:visible'
)

_TAB_STATE = r"""
() => {
    const tabs = [...document.querySelectorAll('li:is(#one,#two,#three,#four)')];
    const claimCrumb = [...document.querySelectorAll('li')].find(li =>
        li.getClientRects().length && /^Claim\s+No\.?\s*:?\s*\d+\s*\/?$/i.test(li.textContent.trim()) &&
        tabs.some(tab => tab.textContent.trim() === li.nextElementSibling?.textContent.trim()));
    if (claimCrumb) {
        return tabs.find(tab => tab.textContent.trim() === claimCrumb.nextElementSibling.textContent.trim()).id;
    }
    const active = tabs.find(tab =>
        tab.classList.contains('active') || tab.querySelector('[aria-selected=true], a.active'));
    if (active) return active.id;
    return [...document.querySelectorAll('h4.headerClip')].filter(heading =>
        heading.getClientRects().length).map(heading => heading.textContent.trim()).join('|');
}
"""

_STEP_NAMES = {"one": "Quick Update", "two": "Additional Details",
               "three": "Claim Assessment", "four": "Document Upload"}
_CONTINUE_BUTTON = "I fixed all fields — continue"

_INVALID_FIELDS = r"""
(includeCheckboxes = true) => {
    const root = document.querySelector('form[name="workListForm"]') || document;
    const invalid = [];
    for (const field of root.querySelectorAll('input, select, textarea')) {
        if (field.type === 'hidden' || field.type === 'file' ||
            (!includeCheckboxes && field.type === 'checkbox') ||
            field.matches(':disabled, [readonly]') ||
            field.closest('.ng-hide, [hidden], [aria-hidden=true], .tab-pane:not(.active), .modal')) continue;

        // Closed accordions still belong to the current tab and can block Next.
        const collapsed = field.closest('.panel-collapse.collapse:not(.in)');
        const visibleGroup = collapsed?.closest('.panel')?.querySelector('.panel-heading');
        const visibleRadioLabel = field.type === 'radio' &&
            [...(field.labels || [])].some(el => el.getClientRects().length);
        if (!field.getClientRects().length && !visibleGroup?.getClientRects().length && !visibleRadioLabel) continue;

        const model = window.angular?.element(field)?.controller('ngModel');
        if (model?.$pending) continue;
        const errors = model?.$error || {};
        const missing = Boolean(errors.required || field.validity?.valueMissing);
        const failed = model?.$invalid || (field.willValidate && !field.validity.valid);
        if (!missing && !failed) continue;

        const section = field.closest('.panel')?.querySelector('.panel-heading');
        const title = field.closest('.form-group')?.querySelector('.datagrid-title:not(.hidden)');
        const label = [...(field.labels || [])].find(el => !el.closest('.hidden'));
        const name = (title?.textContent || (field.type === 'radio' && field.name) ||
                      label?.textContent || field.name || field.id || '')
            .replace(/\s*\*\s*$/, '').replace(/\s+/g, ' ').trim();
        if (!name) continue;
        invalid.push({
            name, section: (section?.textContent || '').replace(/\s+/g, ' ').trim(),
            identity: [field.type === 'radio' ? '' : field.id, field.name],
            reason: missing ? 'Required value is missing.' : 'New India marked this value invalid.'
        });
    }
    return invalid;
}
"""

_WATCH_NEXT = r"""
([selector, key, source, claimNumber]) => {
    const tabState = """ + _TAB_STATE + r""";
    const invalidFields = """ + _INVALID_FIELDS + r""";
    const controller = new AbortController();
    const watch = {controller, clicks: 0, invalid: []};
    window[key] = watch;
    document.addEventListener('click', event => {
        const button = event.target.closest?.('button');
        if (!event.isTrusted || !button?.matches(selector) || button.disabled ||
            button.getAttribute('aria-disabled') === 'true' || !button.getClientRects().length ||
            tabState() !== source || ![...document.querySelectorAll('li')].some(li =>
                li.getClientRects().length &&
                /^Claim\s+No\.?\s*:?\s*([^\s/]+)\s*\/?$/i.exec(li.textContent.trim())?.[1] === claimNumber)) return;
        watch.invalid = invalidFields();
        if (!watch.invalid.length) watch.clicks += 1;
    }, {capture: true, signal: controller.signal});
}
"""


@dataclass
class _FieldIssue:
    section: str
    label: str
    reason: str
    matches: Callable[[], Awaitable[bool]] | None
    manual_value: Callable[[], Awaitable[bool]] | None
    identity: tuple[str, str] | None


class NewIndiaRecovery(OperatorRecovery):
    def __init__(self, notify, stopped):
        super().__init__(notify, stopped, portal_name="New India")
        self.field_issues = {}

    async def bind_claim(self, page, claim_number):
        self.field_issues.clear()
        self.claim_number = str(claim_number or "").strip()
        self.form_marker = uuid4().hex
        self.claim_url = page.url
        await page.evaluate("marker => { window.__app3NewIndiaClaim = marker; }", self.form_marker)

    async def is_original_document(self, page, *, allow_route_change=False):
        if page.is_closed():
            return False
        return await page.evaluate("marker => window.__app3NewIndiaClaim === marker", self.form_marker)

    async def _same_claim(self, page):
        if not self.claim_number or page.url != self.claim_url:
            return False
        number = re.escape(self.claim_number)
        label = re.compile(rf"^\s*Claim\s+No\.?\s*:?\s*{number}\s*/?\s*$", re.I)
        return bool(await page.locator("li:visible").filter(has_text=label).count())

    def record_field_issue(self, log, label, reason, *, matches=None, manual_value=None, identity=None):
        section = getattr(log, "_section", None) or ""
        self.field_issues[section, label] = _FieldIssue(section, label, reason, matches, manual_value, identity)

    def clear_field_issue(self, log, label):
        self.field_issues.pop((getattr(log, "_section", None) or "", label), None)

    async def _issues_on_page(self, page, step, *, accept_manual=False):
        if not await self._same_step(page, step):
            return []

        async def unresolved(issue):
            check = issue.manual_value if accept_manual and issue.manual_value else issue.matches
            if check:
                with suppress(Exception):
                    return not await check()
            return True

        recorded = list(self.field_issues.values())
        pending = await asyncio.gather(*(unresolved(issue) for issue in recorded))
        unresolved_issues = [issue for issue, needs_review in zip(recorded, pending) if needs_review]
        issues = [(issue.section, issue.label, issue.reason) for issue in unresolved_issues]
        identities = {issue.identity for issue in unresolved_issues if issue.identity and any(issue.identity)}

        for field in await page.evaluate(_INVALID_FIELDS, step != "four"):
            if tuple(field["identity"]) not in identities:
                issue = (field["section"], field["name"], field["reason"])
                if issue not in issues:
                    issues.append(issue)
        return issues

    async def _same_step(self, page, step):
        with suppress(Exception):
            return (await self.is_original_document(page) and await self._same_claim(page)
                    and await page.evaluate(_TAB_STATE) == step)
        return False

    async def _checkpoint_issues(self, page, step):
        # Allow Angular change handlers and the last control's validation to settle.
        await asyncio.sleep(0.25)
        if self.stopped():
            raise asyncio.CancelledError
        issues = await self._issues_on_page(page, step)
        if issues:
            await asyncio.sleep(0.25)
            issues = await self._issues_on_page(page, step)
        if self.stopped():
            raise asyncio.CancelledError
        return issues

    @staticmethod
    def _format_issues(issues):
        return "\n".join(f"• {section + ' / ' if section else ''}{label} — {reason}"
                         for section, label, reason in issues)

    async def review_before_save(self, page, log, *, source):
        """Review the last tab before the existing Fee Bill save action."""
        section = _STEP_NAMES[source]
        issues = await self._checkpoint_issues(page, source)
        if not await self._same_step(page, source):
            return await self.pause(
                page, log, "Review before saving", "App3 could not verify the original claim and page.",
                section=section, instruction="Stop automation and check Chrome.", stop_only=True,
            )
        if issues:
            remaining = issues

            async def ready():
                nonlocal remaining
                if not await self._same_step(page, source) or await page.locator(_BLOCKING_DIALOGS).count():
                    return False
                remaining = await self._issues_on_page(page, source, accept_manual=True)
                return not remaining

            async def describe():
                return "", self._format_issues(remaining)

            await self.pause(
                page, log, "Review fields before saving", self._format_issues(issues),
                section=section, ready=ready, require_original=True,
                describe=describe,
                instruction="Fix the listed fields in Chrome, then click Continue here.",
                confirmation_button=_CONTINUE_BUTTON,
            )
        self.field_issues.clear()
        return True

    async def advance_next(self, page, log, selector, *, source, destination, title, after_click=None):
        section = _STEP_NAMES[source]
        if self.stopped():
            raise asyncio.CancelledError
        if not await self._same_step(page, source):
            return await self.pause(
                page, log, "Next", "App3 could not verify the current claim and step.",
                instruction="Stop this run and check the claim in Chrome.", section=section, stop_only=True,
            )

        key = f"__app3NewIndiaNext_{uuid4().hex}"
        await page.evaluate(_WATCH_NEXT, [selector, key, source, self.claim_number])

        async def click_count():
            with suppress(Exception):
                return await page.evaluate("key => window[key]?.clicks ?? 0", key)
            return 0

        async def at_destination():
            return (await click_count() > 0 and await self._same_step(page, destination)
                    and not await page.locator(_BLOCKING_DIALOGS).count())

        try:
            issues = await self._checkpoint_issues(page, source)
            if not await self._same_step(page, source):
                return await self.pause(
                    page, log, "Next", "App3 could not verify the original claim and page.",
                    section=section, instruction="Stop automation and check Chrome.", stop_only=True,
                )

            reason = "New India stayed on the current step after Next."
            if not issues:
                button = page.locator(f":is({selector}):visible")
                try:
                    if await button.count() == 1 and await button.is_enabled(timeout=1000):
                        await button.click(timeout=3500)
                    else:
                        reason = "Next is unavailable. Check for required fields in Chrome."
                except Exception:
                    reason = "App3 could not confirm the Next click."

                if await click_count():
                    if after_click is not None:
                        with suppress(Exception):
                            await after_click()
                    if await wait_until_ready(at_destination, seconds=4, stopped=self.stopped):
                        log.info(f"{title} opened after Next.")
                        self.field_issues.clear()
                        return True
                issues = await self._issues_on_page(page, source)

            described = False

            async def describe():
                nonlocal described
                accept_manual = described
                described = True
                if await self._same_step(page, source):
                    current = await self._issues_on_page(page, source, accept_manual=True) if accept_manual else issues
                    if await page.locator(_BLOCKING_DIALOGS).count():
                        message = "New India is showing a message. Check it in Chrome."
                        return "", f"{message}\n\n{self._format_issues(current)}" if current else message
                    if current:
                        return "", self._format_issues(current)
                    return "", "Click Next in Chrome to save this page." if issues else reason
                if await self._same_step(page, destination):
                    invalid = await page.evaluate("key => window[key]?.invalid || []", key)
                    if invalid:
                        remaining = self._format_issues([(field["section"], field["name"], field["reason"])
                                                        for field in invalid])
                        return "", f"Return to {section} in Chrome and fix these fields before clicking Next.\n\n{remaining}"
                return "", f"Wait for {title} to open for the original claim."

            advanced = await self.pause(
                page, log, "Review fields before Next" if issues else "Next",
                self._format_issues(issues) if issues else reason, ready=at_destination,
                require_original=True, section=section, describe=describe,
                instruction=f"Fix any listed fields in Chrome and click Next. "
                            f"When {title} opens, close any save message and click Continue here.",
                confirmation_button=_CONTINUE_BUTTON if issues else "",
            )
            self.field_issues.clear()
            return advanced
        finally:
            if not page.is_closed():
                with suppress(Exception):
                    await page.evaluate("key => { window[key]?.controller.abort(); delete window[key]; }", key)
