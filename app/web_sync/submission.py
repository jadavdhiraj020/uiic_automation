"""Observe human Final Submit attempts, retaining full messages before dismissal."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import re
import uuid

from .storage import atomic_json


def confirms_submission(message):
    text = " ".join(message.lower().split())
    # These informational qualifications do not negate a completed submission.
    # Remove only the known harmless wording, then retain the error veto below.
    text = re.sub(r"\b(?:physical\s+)?documents?\s+(?:are\s+|is\s+)?not\s+required\b", "", text)
    text = re.sub(r"\bapproval\s+(?:is\s+)?pending\b", "", text)
    if re.search(r"\b(pending|failed|failure|error|wrong|incorrect|missing|invalid|incomplete|required|not|cannot|unable|unsuccessful|outstanding|rejected|blocked)\b", text):
        return False
    if "?" in text or re.search(r"\b(confirm|are you sure|do you want|please submit)\b", text):
        return False
    return bool(re.search(
        r"\b(?:report|claim|survey|assessment|submission)\b.{0,100}\b(?:submitted successfully|successfully submitted|submission successful|submission is successful)\b"
        r"|\b(?:report|claim|survey|assessment)\b.{0,60}\bhas been submitted\b"
        r"|^\s*(?:submitted successfully|successfully submitted|submission successful)[.!\s]*$", text))


# Runs before site scripts in every frame. Capture-phase click tracking distinguishes
# final submission from intermediate Save/Upload success. No clicks are generated.
OBSERVER_JS = r"""
(() => {
  if (window.__app3Capture) return;
  let armed = false, attempt = 0;
  const seen = new Map();
  const send = (message, kind) => {
    if (!armed || !message || !message.trim()) return;
    const key = attempt + ':' + kind + ':' + message;
    if (seen.has(key)) return seen.get(key);
    const pending = window.app3Submission({message, kind, attempt}).catch(() => {});
    seen.set(key, pending);
    return pending;
  };
  const selector = '[role="alert"], [role="dialog"], .modal.in, .modal[style*="display: block"], .modal[style*="display:block"], .swal2-popup, .sweet-alert, .swal-modal, .ngdialog-open, .p-dialog, .gwt-DialogBox, .gwt-PopupPanel';
  const capture = () => {
    if (!armed) return;
    for (const node of document.querySelectorAll(selector)) {
      if (!node.getClientRects().length || getComputedStyle(node).visibility === 'hidden') continue;
      const body = node.querySelector('.modal-body, .swal2-html-container, .swal-text, .p-dialog-content');
      send((body || node).innerText, 'dom');
    }
    return Promise.all([...seen.values()]);
  };
  window.__app3Capture = capture;
  window.__app3FinalArmed = () => armed;
  window.app3Submission({restore:true}).then(value => {
    if (value != null && attempt === 0) { armed = true; attempt = value; capture(); }
  }).catch(() => {});
  document.addEventListener('click', event => {
    const button = event.target.closest('button, input[type="submit"], input[type="button"], a, [role="button"]');
    if (!button || !event.isTrusted) return;
    const label = (button.innerText || button.value || button.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    // A bare Submit is ambiguous. Require final-submission wording in its
    // accessible label or a local form/section heading or confirmation dialog.
    const container = button.closest(selector + ', fieldset, section, form');
    const heading = container && container.querySelector('legend, h1, h2, h3, h4, .modal-title');
    const contextText = [button.getAttribute('aria-label'), button.title,
      heading && heading.innerText,
      container && container.matches(selector) ? container.innerText : ''].filter(Boolean).join(' ');
    const finalContext = /\bfinal\s+(?:submit|submission|report)\b|\bsubmit\s+(?:the\s+)?(?:final\s+)?(?:survey\s+)?report\b/i.test(contextText);
    if (/^(final submit(?: report)?|submit final(?: report)?|final submission|confirm (?:&|and) submit|proceed to submit)$/i.test(label)
        || (/^submit$/i.test(label) && finalContext)) {
      armed = true; attempt++; seen.clear();
      window.app3Submission({armed:true, attempt}).catch(() => {});
    } else if (armed && /^(yes|confirm|yes[, ]+confirm|yes[, ]+submit|submit)$/i.test(label)
               && (button.closest(selector) || /^(yes|confirm|yes[, ]+confirm|yes[, ]+submit)$/i.test(label))) {
      // Preserve an already identified final attempt across a second confirmation.
    } else if (/^(cancel|no)$/i.test(label)) {
      armed = false;
      window.app3Submission({armed:false, attempt}).catch(() => {});
    } else if (!button.closest(selector)) {
      // An intermediate Save/Upload after an error cannot confirm the final attempt.
      armed = false;
      window.app3Submission({armed:false, attempt}).catch(() => {});
    }
  }, true);
  for (const kind of ['alert', 'confirm']) {
    const original = window[kind];
    window[kind] = function(message) {
      send(String(message), kind);
      const result = original.call(this, message);
      if (kind === 'confirm' && result === false) {
        armed = false;
        window.app3Submission({armed:false, attempt}).catch(() => {});
      }
      return result;
    };
  }
  new MutationObserver(capture).observe(document, {subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['class','style','hidden']});
})();
"""


class SubmissionMonitor:
    def __init__(self, case_id, folder, callback, automation_dispatch_id=None, **kwargs):
        self.case_id = case_id
        self.folder = Path(folder)
        self.callback = callback
        self.automation_dispatch_id = str(automation_dispatch_id or "").strip()
        self.seen = set()
        self.confirmed = False
        self.lock = asyncio.Lock()
        self.armed = {}

    async def install(self, context):
        async def receive(source, event):
            page = source.get("page")
            if event.get("restore"):
                if page not in self.armed:
                    opener = await page.opener()
                    self.armed[page] = self.armed.get(opener)
                return self.armed.get(page)
            elif "armed" in event:
                self.armed[page] = event["attempt"] if event["armed"] else None
            else:
                await self.capture(event, page)
        await context.expose_binding("app3Submission", receive)
        await context.add_init_script(OBSERVER_JS)
        async def on_dialog(dialog):
            await self.native(dialog.page, dialog)
            # Installing a context listener prevents Playwright's default dismissal
            # from racing persistence. Confirmation remains a human choice.
            if dialog.type == "alert":
                try:
                    await dialog.accept()
                except Exception:
                    pass  # The portal's existing page handler may already accept it.
        context.on("dialog", on_dialog)
        # The injected wrappers survive UIIC replacing page dialog listeners.
        context._app3_submission_monitor = self

    async def capture(self, event, page=None):
        async with self.lock:
            await self._capture(event, page)

    async def native(self, page, dialog):
        attempt = self.armed.get(page)
        if attempt is not None:
            await self.capture({"attempt": attempt, "message": dialog.message, "kind": dialog.type}, page)

    async def _capture(self, event, page=None):
        message = event.get("message", "")
        key = (event.get("attempt"), event.get("kind"), message)
        if not message or key in self.seen or self.confirmed:
            return
        success = confirms_submission(message) and event.get("kind") != "confirm"
        record = {
            "case_id": self.case_id,
            "portal_message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confirmed_success": success,
            "source": event.get("kind"),
            "attempt": event.get("attempt"),
        }
        if self.automation_dispatch_id:
            record["automation_dispatch_id"] = self.automation_dispatch_id
        stem = "Portal_Submission_Result_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f") + "_" + uuid.uuid4().hex[:6]
        record_path = self.folder / (stem + ".json")
        atomic_json(record_path, record)
        atomic_json(self.folder / "Portal_Submission_Result.json", record)
        self.seen.add(key)
        self.confirmed = success
        # Save text first: a native dialog may prevent screenshots until dismissed.
        if page is not None:
            try:
                await page.screenshot(path=str(self.folder / (stem + ".png")), timeout=1500)
                record["screenshot"] = stem + ".png"
                atomic_json(record_path, record)
                atomic_json(self.folder / "Portal_Submission_Result.json", record)
            except Exception:
                pass
        self.callback(record)


async def capture_before_dismiss(page):
    if not getattr(page.context, "_app3_submission_monitor", None):
        return
    for frame in page.frames:
        try:
            await frame.evaluate("() => window.__app3Capture && window.__app3Capture()")
        except Exception:
            pass


async def capture_native_before_dismiss(page, dialog):
    monitor = getattr(page.context, "_app3_submission_monitor", None)
    if monitor:
        await monitor.native(page, dialog)
