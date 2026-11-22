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
        li.getClientRects().length && /^Claim\s+No\.?\s*:?\s*[^\s/]+\s*\/?$/i.test(li.textContent.trim()) &&
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
_CONTINUE_BUTTON = "Continue"
_PAGE_REVIEW_STEPS = ("one", "two", "three")

_INVALID_FIELDS = r"""
([includeCheckboxes, step]) => {
    const claimForm = document.querySelector('form[name="workListForm"]');
    const quickUpdate = step === 'one';
    const additionalDetails = step === 'two';
    const assessment = step === 'three';
    const documentUpload = step === 'four';
    const activePane = claimForm?.querySelector('.tab-pane.active');
    const feeBillControl = documentUpload
        ? activePane?.querySelector('#isInvoiceInNameOfNIA, [data-ng-model*="surveyFeeBill"], [ng-model*="surveyFeeBill"]')
        : null;
    const feeBillPanel = feeBillControl ? (feeBillControl.closest('.panel') || activePane) : null;
    const root = quickUpdate ? [...document.querySelectorAll('[name="quickUpdateForm"]')].find(form =>
        !form.closest('.ng-hide, [hidden], [aria-hidden=true], .tab-pane:not(.active)')) :
        (additionalDetails || assessment) ? activePane :
        documentUpload ? feeBillPanel : claimForm || document;
    if (!root) return [];
    const invalid = [];
    for (const field of root.querySelectorAll('input, select, textarea')) {
        if (field.type === 'hidden' || field.type === 'file' ||
            (!includeCheckboxes && field.type === 'checkbox') ||
            field.matches(':disabled, [readonly]') ||
            field.closest('.ng-hide, .hidden, [hidden], [aria-hidden=true], .tab-pane:not(.active), .modal')) continue;

        // These fields can be required for a Delivery Order submission, but are optional at Claim Assessment Next.
        const deliveryOrderField = assessment && field.matches('input[name="Delivery Order Date"], input[name="Delivery Order Time"]');
        if (deliveryOrderField && !field.value.trim()) continue;

        // Closed accordions still belong to the current tab and can block Next.
        const collapsed = field.closest('.panel-collapse.collapse:not(.in)');
        const visibleGroup = collapsed?.closest('.panel')?.querySelector('.panel-heading');
        const visibleRadioLabel = field.type === 'radio' &&
            [...(field.labels || [])].some(el => el.getClientRects().length);
        if (!field.getClientRects().length && !visibleGroup?.getClientRects().length && !visibleRadioLabel) continue;

        const model = window.angular?.element(field)?.controller('ngModel');
        if (model?.$pending) continue;
        const errors = model?.$error || {};
        const pageReview = quickUpdate || additionalDetails || assessment;
        const useNative = !pageReview || !model;
        const missing = !deliveryOrderField && Boolean(errors.required || (useNative && field.validity?.valueMissing) ||
            (assessment && !model && field.classList.contains('ng-invalid-required')));
        const failed = model?.$invalid || (useNative && field.willValidate && !field.validity.valid) ||
            (assessment && !model && field.classList.contains('ng-invalid')) ||
            (pageReview && !model && field.getAttribute('aria-invalid') === 'true');
        if (!missing && !failed) continue;

        const section = field.closest('.panel')?.querySelector('.panel-heading');
        // Additional Details uses one .form-group for a row with many controls.
        const cell = assessment && field.closest('table:is(#myTable, #example) td');
        const group = cell || (additionalDetails && field.closest('.checkbox, [class*="col-md-"], li')) ||
            (assessment && field.closest('.form-group, .checkbox, [class*="col-"], li')) || field.closest('.form-group');
        const title = group?.querySelector('.datagrid-title:not(.hidden)') ||
            (pageReview && group?.querySelector('label:not(.hidden)'));
        const label = [...(field.labels || [])].find(el => !el.closest('.hidden'));
        const column = cell && cell.closest('table').tHead?.rows[0]?.cells[cell.cellIndex];
        let name = ((deliveryOrderField && field.name) ||
                      (assessment && field.id === 'recommendations' && 'Recommendations') ||
                      (assessment && field.type === 'radio' && field.name) || title?.textContent ||
                      column?.textContent || (field.type === 'radio' && field.name) ||
                      label?.textContent || field.name || field.id || '')
            .replace(/\s*\*\s*$/, '').replace(/\s+/g, ' ').trim();
        if (!name) continue;
        let sectionName = (section?.textContent || '').replace(/\s+/g, ' ').trim();
        if (assessment && !cell) {
            const invoice = field.name.match(
                /^(Whether the Workshop is GST Registered|Whether Payment invoice is in the name of NIA|Vendor\/Tax Invoice Date|Vendor\/Tax Invoice Number|Is there any supplementary estimate|Painting work details)(\d+)$/i
            );
            if (invoice) {
                if (name === field.name) name = invoice[1];
                sectionName = ['Invoice ' + (Number(invoice[2]) + 1), sectionName].filter(Boolean).join(' / ');
            }
        }
        if (assessment && cell) {
            const row = cell.parentElement;
            sectionName = [sectionName, 'Item row ' + (row.sectionRowIndex + 1)].filter(Boolean).join(' / ');
        }
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
([selector, key, source, claimNumber, pageReview, buttonText]) => {
    const tabState = """ + _TAB_STATE + r""";
    const invalidFields = """ + _INVALID_FIELDS + r""";
    const controller = new AbortController();
    const watch = {controller, clicks: 0, invalid: []};
    window[key] = watch;
    document.addEventListener('click', event => {
        const button = event.target.closest?.('button');
        if (!event.isTrusted || !button?.matches(selector) || button.disabled ||
            (buttonText && button.textContent.trim().toLowerCase() !== buttonText.toLowerCase()) ||
            button.getAttribute('aria-disabled') === 'true' || !button.getClientRects().length ||
            tabState() !== source || ![...document.querySelectorAll('li')].some(li =>
                li.getClientRects().length &&
                /^Claim\s+No\.?\s*:?\s*([^\s/]+)\s*\/?$/i.exec(li.textContent.trim())?.[1] === claimNumber)) return;
        watch.invalid = invalidFields([true, source]);
        if (pageReview || !watch.invalid.length) watch.clicks += 1;
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
    attempted_value: str = ""
    source: str = ""


class NewIndiaRecovery(OperatorRecovery):
    def __init__(self, notify, stopped, *, field_progress_cb=None):
        super().__init__(notify, stopped, portal_name="New India")
        self.field_issues = {}
        self._field_progress_cb = field_progress_cb
        self.fields_filled = 0
        self.fields_failed = 0
        self.fields_skipped = 0

    async def bind_claim(self, page, claim_number):
        self.field_issues.clear()
        self.fields_filled = 0
        self.fields_failed = 0
        self.fields_skipped = 0
        self.claim_number = str(claim_number or "").strip()
        self.form_marker = uuid4().hex
        self.claim_url = page.url
        await page.evaluate("marker => { window.__app3NewIndiaClaim = marker; }", self.form_marker)

    def report_field_progress(self, section: str, field: str, state: str, *, value: str = "") -> None:
        if state == "ok":
            self.fields_filled += 1
        elif state == "failed":
            self.fields_failed += 1
        elif state == "skipped":
            self.fields_skipped += 1
        if self._field_progress_cb is not None:
            with suppress(Exception):
                self._field_progress_cb({
                    "section": section or "",
                    "field": field or "",
                    "state": state,
                    "value": value or "",
                    "filled": self.fields_filled,
                    "failed": self.fields_failed,
                    "skipped": self.fields_skipped,
                })

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

    def record_field_issue(
        self, log, label, reason, *, matches=None, manual_value=None, identity=None,
        attempted_value="", source="",
    ):
        section = getattr(log, "_section", None) or ""
        attempted = str(attempted_value or "")
        src = str(source or "")
        self.field_issues[section, label] = _FieldIssue(
            section, label, reason, matches, manual_value, identity,
            attempted_value=attempted, source=src,
        )
        if hasattr(log, "field_failed"):
            log_reason = f"{reason} (tried '{attempted}')" if attempted else reason
            log.field_failed(label, log_reason)

    async def pause(
        self, page, log, action, reason, *, ready=None, instruction=None, describe=None, section=None, stop_only=False,
        confirmation_button="", require_original=False, field_ready=None, skip_button="", on_skip=None, on_continue=None,
    ):
        from app.portals.newindia.automation.logging_utils import capture_newindia_screenshot
        from app.portals.newindia.automation.ui_utils import update_field_hud

        sec_name = section or getattr(log, "_section", None) or "New India"
        summary_reason = " | ".join(line.strip() for line in str(reason or "").splitlines() if line.strip())
        if hasattr(log, "warning"):
            log.warning(f"Paused at '{sec_name}' ({action}) — {summary_reason[:220]}")
        await update_field_hud(
            page, sec_name, action or "Paused for review", "paused",
            filled=self.fields_filled, failed=self.fields_failed, skipped=self.fields_skipped,
        )
        if action != "Automation Paused":
            await capture_newindia_screenshot(
                page, f"paused_{sec_name}", log, reason=action, claim_no=self.claim_number or ""
            )
        result = await super().pause(
            page, log, action, reason,
            ready=ready, instruction=instruction, describe=describe, section=section,
            stop_only=stop_only, confirmation_button=confirmation_button,
            require_original=require_original, field_ready=field_ready,
            skip_button=skip_button, on_skip=on_skip, on_continue=on_continue,
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
            if check is None:
                return not accept_manual
            try:
                return not await check()
            except Exception:
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

    def _format_issues(self, issues):
        lines = []
        for item in issues:
            if len(item) >= 5:
                section, label, reason, attempted, source = item[:5]
            else:
                section, label, reason = item[:3]
                recorded = self.field_issues.get((section, label))
                attempted = recorded.attempted_value if recorded else ""
                source = recorded.source if recorded else ""
            val_tag = ""
            if str(attempted or "").strip():
                src = f" · {source}" if str(source or "").strip() else ""
                val_tag = f" [Value: {attempted}{src}]"
            prefix = f"{section} / " if section else ""
            lines.append(f"• {prefix}{label}{val_tag} — {reason}")
        return "\n".join(lines)

    async def review_before_save(self, page, log, *, source):
        """Review the last tab before the existing Fee Bill save action."""
        from app.portals.newindia.automation.ui_utils import clear_field_hud

        from app.portals.newindia.automation.ui_utils import clear_field_hud

        section = _STEP_NAMES[source]
        issues = await self._checkpoint_issues(page, source)
        if not await self._same_step(page, source):
            return await self.pause(
                page, log, "Review before saving", "App3 could not verify the original claim and page.",
                section=section, instruction="Stop automation and check Chrome.", stop_only=True,
            )
        if issues:
            remaining = issues
            confirmed = False
            overridden = False

            async def ready():
                nonlocal remaining
                if not await self._same_step(page, source) or await page.locator(_BLOCKING_DIALOGS).count():
                    return False
                if overridden:
                    return True
                remaining = await self._issues_on_page(page, source, accept_manual=confirmed)
                return not remaining

            async def confirm_review():
                nonlocal confirmed
                confirmed = True

            async def skip_review():
                nonlocal overridden
                overridden = True

            async def describe():
                return "", self._format_issues(remaining)

            await self.pause(
                page, log, "Review before saving", self._format_issues(issues),
                section=section, ready=ready, require_original=True,
                describe=describe,
                instruction="Fix the listed fields in Chrome, then click Continue.",
                confirmation_button=_CONTINUE_BUTTON,
                skip_button="Continue anyway",
                on_skip=skip_review,
                on_continue=confirm_review,
            )
        self.field_issues.clear()
        await clear_field_hud(page, clear_errors=True)
        return True

    async def advance_next(
        self, page, log, selector, *, source, destination, title, after_click=None, button_text="",
        confirm_before_transition=False,
    ):
        from app.portals.newindia.automation.ui_utils import clear_field_hud

        section = _STEP_NAMES[source]
        page_review = source in _PAGE_REVIEW_STEPS
        if self.stopped():
            raise asyncio.CancelledError
        if not await self._same_step(page, source):
            return await self.pause(
                page, log, "Next", "App3 could not verify the current claim and step.",
                instruction="Stop this run and check the claim in Chrome.", section=section, stop_only=True,
            )

        key = f"__app3NewIndiaNext_{uuid4().hex}"
        await page.evaluate(_WATCH_NEXT, [selector, key, source, self.claim_number, page_review, button_text])

        async def click_count():
            with suppress(Exception):
                return await page.evaluate("key => window[key]?.clicks ?? 0", key)
            return 0

        rejected_dialog_body = None

        async def at_destination():
            nonlocal rejected_dialog_body
            if not await self._same_step(page, destination):
                return False
            dialogs = page.locator(_BLOCKING_DIALOGS)
            if not await dialogs.count():
                rejected_dialog_body = None
                return True
            if after_click is not None:
                dialog_text = None
                with suppress(Exception):
                    dialog_text = " ".join((await dialogs.first.inner_text(timeout=500)).split())
                if dialog_text and dialog_text != rejected_dialog_body:
                    with suppress(Exception):
                        await after_click()
                    if not await dialogs.count():
                        return True
                    rejected_dialog_body = dialog_text
            return False

        reason = "New India stayed on the current step after Next."
        skip_tried = False
        retried = False

        async def dismiss_save_popup():
            dialogs = page.locator(_BLOCKING_DIALOGS)
            if not await dialogs.count():
                return
            if after_click is not None:
                with suppress(Exception):
                    await after_click()
            elif await dialogs.count():
                dialog = dialogs.first
                ok_btn = dialog.locator(
                    'button:visible, a.btn:visible, input[type="button"]:visible, input[type="submit"]:visible'
                ).filter(has_text=re.compile(r"^\s*(?:ok|okay|close|done|got it)\s*$", re.I))
                if await ok_btn.count():
                    with suppress(Exception):
                        await ok_btn.first.click(timeout=2000)
                else:
                    swal_confirm = dialog.locator(".swal2-confirm:visible")
                    if await swal_confirm.count():
                        with suppress(Exception):
                            await swal_confirm.first.click(timeout=2000)
                    else:
                        footer_btns = dialog.locator(".modal-footer button:visible, .modal-footer a.btn:visible")
                        if await footer_btns.count() == 1:
                            with suppress(Exception):
                                await footer_btns.first.click(timeout=2000)
            await wait_until_ready(
                lambda: _dialogs_cleared(), seconds=1.5, stopped=self.stopped,
            )

        async def _dialogs_cleared():
            return (not await page.locator(_BLOCKING_DIALOGS).count()
                    and not await page.locator(".modal-backdrop.in:visible").count())

        async def wait_after_next():
            loop = asyncio.get_running_loop()
            trans_deadline = loop.time() + 3.0
            while not self.stopped() and loop.time() < trans_deadline:
                if await self._same_step(page, destination):
                    break
                if await page.locator(_BLOCKING_DIALOGS).count():
                    return
                await asyncio.sleep(0.15)
            if not await self._same_step(page, destination) or self.stopped():
                return
            # Angular save modals can appear right after the tab switch renders.
            if not await page.locator(_BLOCKING_DIALOGS).count():
                popup_deadline = loop.time() + 0.6
                while not self.stopped() and loop.time() < popup_deadline:
                    if await page.locator(_BLOCKING_DIALOGS).count():
                        break
                    await asyncio.sleep(0.15)
            if await page.locator(_BLOCKING_DIALOGS).count():
                await dismiss_save_popup()

        async def click_next():
            nonlocal reason
            if self.stopped() or not await self._same_step(page, source):
                return
            button = page.locator(f":is({selector}):visible")
            if button_text:
                button = button.filter(has_text=re.compile(rf"^\s*{re.escape(button_text)}\s*$", re.I))
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
                if confirm_before_transition or not page_review or await wait_until_ready(
                    lambda: self._same_step(page, destination), seconds=4, stopped=self.stopped,
                ):
                    with suppress(Exception):
                        await after_click()

        async def continue_after_fix():
            nonlocal retried
            retried = True
            if await self._same_step(page, destination):
                if await page.locator(_BLOCKING_DIALOGS).count():
                    await dismiss_save_popup()
                return
            if not await self._same_step(page, source) or await page.locator(_BLOCKING_DIALOGS).count():
                return
            if await self._issues_on_page(page, source, accept_manual=True):
                return
            await click_next()
            await wait_after_next()

        async def skip_and_try_next():
            nonlocal skip_tried, retried
            skip_tried = True
            retried = True
            await click_next()
            await wait_after_next()

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
                    await wait_after_next()
                    if await wait_until_ready(at_destination, seconds=4, stopped=self.stopped):
                        log.info(f"{title} opened after Next.")
                        self.field_issues.clear()
                        await clear_field_hud(page, clear_errors=True)
                        return True
                issues = await self._issues_on_page(page, source)

            async def describe():
                if await self._same_step(page, source):
                    current = await self._issues_on_page(page, source, accept_manual=True) if retried else issues
                    if await page.locator(_BLOCKING_DIALOGS).count():
                        message = "New India is showing a message. Close it in Chrome, then click Continue."
                        return "", f"{message}\n\n{self._format_issues(current)}" if current else message
                    if current:
                        detail = self._format_issues(current)
                        return "", f"{reason}\n\n{detail}" if skip_tried else detail
                    return "", reason if (skip_tried or retried) else f"Click Next in Chrome or click Continue to move to {title}."
                if await self._same_step(page, destination):
                    if page_review and await page.locator(_BLOCKING_DIALOGS).count():
                        return "", "Close the New India message in Chrome, then click Continue."
                    invalid = await page.evaluate("key => window[key]?.invalid || []", key)
                    if invalid:
                        remaining = self._format_issues([(field["section"], field["name"], field["reason"])
                                                        for field in invalid])
                        return "", f"Return to {section} in Chrome and fix these fields before clicking Next.\n\n{remaining}"
                return "", f"Wait for {title} to open in Chrome, then click Continue."

            advanced = await self.pause(
                page, log, f"Review {section}" if (page_review or issues) else f"Move to {title}",
                self._format_issues(issues) if issues else reason, ready=at_destination,
                require_original=True, section=section, describe=describe,
                instruction=(
                    "Fix the listed fields in Chrome, then click Continue (automation will click Next for you)."
                    if issues else
                    f"Finish any popups or click Next in Chrome, then click Continue to move to {title}."
                ),
                confirmation_button=_CONTINUE_BUTTON,
                skip_button="Skip & Try Next" if page_review else "",
                on_skip=skip_and_try_next if page_review else None,
                on_continue=continue_after_fix,
            )
            self.field_issues.clear()
            if advanced:
                await clear_field_hud(page, clear_errors=True)
            return advanced
        finally:
            if not page.is_closed():
                with suppress(Exception):
                    await page.evaluate("key => { window[key]?.controller.abort(); delete window[key]; }", key)
