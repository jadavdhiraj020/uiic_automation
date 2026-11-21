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
([includeCheckboxes, step]) => {
    const claimForm = document.querySelector('form[name="workListForm"]');
    const quickUpdate = step === 'one';
    const additionalDetails = step === 'two';
    const root = quickUpdate ? [...document.querySelectorAll('[name="quickUpdateForm"]')].find(form =>
        !form.closest('.ng-hide, [hidden], [aria-hidden=true], .tab-pane:not(.active)')) :
        additionalDetails ? claimForm?.querySelector('.tab-pane.active') : claimForm || document;
    if (!root) return [];
    const invalid = [];
    for (const field of root.querySelectorAll('input, select, textarea')) {
        if (field.type === 'hidden' || field.type === 'file' ||
            (!includeCheckboxes && field.type === 'checkbox') ||
            field.matches(':disabled, [readonly]') ||
            field.closest('.ng-hide, .hidden, [hidden], [aria-hidden=true], .tab-pane:not(.active), .modal')) continue;

        // Closed accordions still belong to the current tab and can block Next.
        const collapsed = field.closest('.panel-collapse.collapse:not(.in)');
        const visibleGroup = collapsed?.closest('.panel')?.querySelector('.panel-heading');
        const visibleRadioLabel = field.type === 'radio' &&
            [...(field.labels || [])].some(el => el.getClientRects().length);
        if (!field.getClientRects().length && !visibleGroup?.getClientRects().length && !visibleRadioLabel) continue;

        const model = window.angular?.element(field)?.controller('ngModel');
        if (model?.$pending) continue;
        const errors = model?.$error || {};
        const pageReview = quickUpdate || additionalDetails;
        const useNative = !pageReview || !model;
        const missing = Boolean(errors.required || (useNative && field.validity?.valueMissing));
        const failed = model?.$invalid || (useNative && field.willValidate && !field.validity.valid) ||
            (pageReview && !model && field.getAttribute('aria-invalid') === 'true');
        if (!missing && !failed) continue;

        const section = field.closest('.panel')?.querySelector('.panel-heading');
        // Additional Details uses one .form-group for a row with many controls.
        const group = (additionalDetails && field.closest('.checkbox, [class*="col-md-"], li')) ||
            field.closest('.form-group');
        const title = group?.querySelector('.datagrid-title:not(.hidden)') ||
            (pageReview && group?.querySelector('label:not(.hidden)'));
        const label = [...(field.labels || [])].find(el => !el.closest('.hidden'));
        const name = (title?.textContent || (field.type === 'radio' && field.name) ||
                      label?.textContent || field.name || field.id || '')
            .replace(/\s*\*\s*$/, '').replace(/\s+/g, ' ').trim();
        if (!name) continue;
        const sectionName = (section?.textContent || '').replace(/\s+/g, ' ').trim();
        invalid.push({
            name, section: additionalDetails ? sectionName.replace(/\s+\d+$/, '') : sectionName,
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
        watch.invalid = invalidFields([true, source]);
        if (['one', 'two'].includes(source) || !watch.invalid.length) watch.clicks += 1;
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
        if hasattr(log, "field_failed"):
            log.field_failed(label, reason)

    async def pause(
        self, page, log, action, reason, *, ready=None, instruction=None, describe=None, section=None, stop_only=False,
        confirmation_button="", require_original=False, field_ready=None, skip_button="", on_skip=None,
    ):
        from app.portals.newindia.automation.logging_utils import capture_newindia_screenshot

        sec_name = section or getattr(log, "_section", None) or "New India"
        summary_reason = " | ".join(line.strip() for line in str(reason or "").splitlines() if line.strip())
        if hasattr(log, "warning"):
            log.warning(f"Paused at '{sec_name}' ({action}) — {summary_reason[:220]}")
        await capture_newindia_screenshot(
            page, f"paused_{sec_name}", log, reason=action, claim_no=self.claim_number or ""
        )
        result = await super().pause(
            page, log, action, reason,
            ready=ready, instruction=instruction, describe=describe, section=section,
            stop_only=stop_only, confirmation_button=confirmation_button,
            require_original=require_original, field_ready=field_ready, skip_button=skip_button, on_skip=on_skip,
        )
        if result and not self.stopped() and hasattr(log, "info"):
            log.info(f"Resumed automation after '{sec_name}'.")
        return result

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

        for field in await page.evaluate(_INVALID_FIELDS, [step != "four", step]):
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
        page_review = source in {"one", "two"}
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

        reason = "New India stayed on the current step after Next."
        skip_tried = False

        async def click_next():
            nonlocal reason
            if self.stopped() or not await self._same_step(page, source):
                return
            button = page.locator(f":is({selector}):visible")
            previous_clicks = await click_count()
            try:
                if page_review and await page.locator(_BLOCKING_DIALOGS).count():
                    reason = "Close the New India message in Chrome before trying Next."
                    return
                if await button.count() != 1:
                    reason = "App3 could not identify the Next button. Check the current page in Chrome."
                    return
                if not await button.is_enabled(timeout=1000):
                    reason = "New India has disabled Next. Fix the required fields in Chrome."
                    return
                reason = "New India stayed on the current step after Next."
                await button.click(timeout=3500)
            except Exception:
                reason = "App3 could not click Next. Check Chrome."

            if after_click is not None and await click_count() > previous_clicks:
                if not page_review or await wait_until_ready(
                    lambda: self._same_step(page, destination), seconds=4, stopped=self.stopped,
                ):
                    with suppress(Exception):
                        await after_click()

        async def skip_and_try_next():
            nonlocal skip_tried
            skip_tried = True
            await click_next()

        try:
            issues = await self._checkpoint_issues(page, source)
            if not await self._same_step(page, source):
                return await self.pause(
                    page, log, "Next", "App3 could not verify the original claim and page.",
                    section=section, instruction="Stop automation and check Chrome.", stop_only=True,
                )

            if not issues:
                await click_next()
                if await click_count():
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
                        detail = self._format_issues(current)
                        return "", f"{reason}\n\n{detail}" if skip_tried else detail
                    return "", "Click Next in Chrome to save this page." if issues and not skip_tried else reason
                if await self._same_step(page, destination):
                    if page_review and await page.locator(_BLOCKING_DIALOGS).count():
                        return "", "Close the New India message in Chrome, then continue here."
                    invalid = await page.evaluate("key => window[key]?.invalid || []", key)
                    if invalid:
                        remaining = self._format_issues([(field["section"], field["name"], field["reason"])
                                                        for field in invalid])
                        return "", f"Return to {section} in Chrome and fix these fields before clicking Next.\n\n{remaining}"
                return "", f"Wait for {title} to open for the original claim."

            advanced = await self.pause(
                page, log, f"Review {section}" if page_review else "Review fields before Next" if issues else "Next",
                self._format_issues(issues) if issues else reason, ready=at_destination,
                require_original=True, section=section, describe=describe,
                instruction=("Fix the listed fields and click Next in Chrome. "
                             "Close any confirmation message, then continue here. "
                             "Or let App3 try Next with the current values.") if page_review else (
                    f"Fix any listed fields in Chrome and click Next. "
                    f"When {title} opens, close any save message and click Continue here."
                ),
                confirmation_button="I fixed it — continue" if page_review else _CONTINUE_BUTTON if issues else "",
                skip_button="Skip and try Next" if page_review else "",
                on_skip=skip_and_try_next if page_review else None,
            )
            self.field_issues.clear()
            return advanced
        finally:
            if not page.is_closed():
                with suppress(Exception):
                    await page.evaluate("key => { window[key]?.controller.abort(); delete window[key]; }", key)
