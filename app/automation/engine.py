import asyncio
import logging
import time
import os
import threading
from contextlib import suppress
from datetime import datetime
from typing import Callable, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.automation.automation_logger import AutomationLogger
from app.automation.claim_assessment import fill_claim_assessment
from app.automation.claim_documents import fill_claim_documents
from app.automation.interim_report import fill_interim_report
from app.automation.selectors import TABS, TAB_SEL
from app.data.data_model import ClaimData
from app.portals.registry import get_portal


logger = logging.getLogger(__name__)

DEFERRED_OCR_TIMEOUT_SECONDS = 180.0


def _setting_int(settings: dict, primary_key: str, legacy_key: str, default: int) -> int:
    value = settings.get(primary_key)
    if value in (None, ""):
        value = settings.get(legacy_key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setting_bool(settings: dict, key: str, default: bool = False) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


class AutomationRunResult:
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message


def _pick_best_page(pages: List[Page], log) -> Page:
    """Helper to find the best page to use for automation (Surveyor page vs Login page)."""
    # 1. Prioritize any page that is definitely on the Surveyor app
    for p in pages:
        try:
            url = p.url
            if "Surveyor.html" in url:
                if isinstance(log, AutomationLogger):
                    log.info(f"Found Surveyor page: {url}")
                else:
                    log(f"Found Surveyor page: {url}")
                return p
        except Exception:
            continue

    # 2. Prefer any page that isn't the login page
    for p in pages:
        try:
            url = p.url
            if "home.jsp" not in url.lower():
                if isinstance(log, AutomationLogger):
                    log.info(f"Using non-login page: {url}")
                else:
                    log(f"Using non-login page: {url}")
                return p
        except Exception:
            continue

    # 3. Fallback to the last open page
    if isinstance(log, AutomationLogger):
        log.info(f"Using last open page: {pages[-1].url}")
    else:
        log(f"Using last open page: {pages[-1].url}")
    return pages[-1]


async def _page_has_login_form(page: Page, portal_id: str = "uiic") -> bool:
    """Return True if the page is still showing the login form."""
    try:
        login_sel = page.locator("#login-username, input[name='username']").first
        return await login_sel.is_visible(timeout=1500)
    except Exception:
        return False


async def _get_active_page(
    context: BrowserContext,
    log = None,
    captured_pages: List[Page] = None,
    stop_cb: Callable[[], bool] = lambda: False,
    portal_id: str = "uiic",
    log_cb = None,   # backwards-compat alias for log
) -> Optional[Page]:
    """
    Establish which page to work on after login.
    If the portal is UIIC, it usually opens a new tab 'Surveyor.html'.
    If the portal is NIA, it usually navigates in-place or opens a worklist.
    """
    # Resolve log — accept either `log` or `log_cb` (legacy alias)
    if log is None:
        log = log_cb if log_cb is not None else print
    if captured_pages is None:
        captured_pages = []
    if portal_id in ("newindia", "oic"):
        # New India & OIC usually don't open a new tab immediately after login.
        # We just return the last active page in the context.
        await asyncio.sleep(1.0)
        return context.pages[-1] if context.pages else None

    # UIIC specific logic: wait for the Surveyor tab
    start_t = time.time()
    
    if isinstance(log, AutomationLogger):
        log.wait("Locating dashboard/worklist page...")
        log.indent()
    else:
        log("Locating dashboard/worklist page...")
        
    while time.time() - start_t < 25:
        if stop_cb():
            if isinstance(log, AutomationLogger): log.outdent()
            return None

        pages = context.pages
        surveyor_page = next((p for p in pages if "Surveyor.html" in p.url), None)
        if surveyor_page:
            if isinstance(log, AutomationLogger):
                log.success(f"Found Surveyor page: {surveyor_page.url}")
                log.outdent()
            else:
                log(f"Found Surveyor page: {surveyor_page.url}")
            try:
                await surveyor_page.bring_to_front()
            except Exception:
                pass
            return surveyor_page

        elapsed = time.time() - start_t

        # Short-circuit: if all open pages are on the login URL, skip the 15s wait
        all_on_login_url = bool(pages) and all(
            "home.jsp" in p.url.lower() or p.url in ("about:blank", "")
            for p in pages if not p.is_closed()
        )

        if elapsed > 10 and int(elapsed) % 5 == 0 and not all_on_login_url:
            if isinstance(log, AutomationLogger):
                log.info(f"No dashboard tab yet ({elapsed:.1f}s)...")
            else:
                log(f"  No dashboard tab yet ({elapsed:.1f}s).")

        # Attempt direct navigation if tab doesn't open OR all pages still on login
        if elapsed > 15 or all_on_login_url:
            if isinstance(log, AutomationLogger): log.outdent()
            for attempt in range(1, 4):
                try:
                    if isinstance(log, AutomationLogger):
                        log.wait(f"Direct navigation attempt {attempt}/3...")
                    else:
                        log(f"Opening authenticated Worklist page (attempt {attempt}/3)...")
                    new_page = await context.new_page()
                    await new_page.goto(WORKLIST_URL, timeout=20000)
                    await asyncio.sleep(0.5)

                    # Use _page_has_login_form to verify the new page is authenticated
                    still_login = await _page_has_login_form(new_page, portal_id)
                    if still_login or "home.jsp" in new_page.url.lower():
                        await new_page.close()
                        if isinstance(log, AutomationLogger):
                            log.warning("Session not settled; retrying...")
                        else:
                            log("Login form is still visible after direct navigation; waiting for session to settle.")
                        await asyncio.sleep(2)
                        continue

                    if isinstance(log, AutomationLogger):
                        log.success("Worklist page ready")
                        log.outdent()
                    else:
                        log(f"Worklist page ready: {new_page.url}")
                    return new_page
                except Exception as exc:
                    if isinstance(log, AutomationLogger):
                        log.error(f"Attempt {attempt} failed: {str(exc)[:100]}")
                    else:
                        log(f"Direct navigation attempt {attempt} failed: {exc}")
            break

        await asyncio.sleep(1)

    # Fallback: scan all pages again
    pages = context.pages
    if pages:
        page = _pick_best_page(pages, log)
        if isinstance(log, AutomationLogger): log.outdent()
        return page

    if isinstance(log, AutomationLogger):
        log.error("No active dashboard page could be established")
        log.outdent()
    else:
        log("No active dashboard page could be established.")
    return None


class AutomationEngine:
    def __init__(
        self,
        portal_id: str,
        log_cb: Callable[[str], None] = print,
        step_cb: Callable[[int, str], None] = lambda i, s: None,
    ):
        self.portal_id = portal_id
        self.log_cb = log_cb
        self.step_cb = step_cb
        self._stop_requested = False
        self.log = AutomationLogger("ENGINE", self.log_cb, portal_id=self.portal_id)

    def request_stop(self):
        """Set a flag to stop automation at the next check point."""
        self._stop_requested = True

    def _check_stop(self) -> bool:
        """Internal callback passed to modules."""
        if self._stop_requested:
            self.log_cb("⛔ Stop requested. Closing automation safely...")
            return True
        return False

    def _start_deferred_ocr_jobs(self, claim: ClaimData) -> None:
        """Start invoice and cheque OCR jobs requested during folder processing."""
        if getattr(claim, "_deferred_ocr_started", False):
            return
        claim._deferred_ocr_started = True
        claim_lock = getattr(claim, "_deferred_ocr_claim_lock", None)
        if claim_lock is None:
            claim_lock = threading.RLock()
            claim._deferred_ocr_claim_lock = claim_lock

        def _mark_source(field: str, value: str, source: str) -> None:
            if not value:
                return
            with claim_lock:
                if hasattr(claim, "_excel_coords"):
                    claim._excel_coords[field] = source
                if hasattr(claim, "_excel_logs"):
                    claim._excel_logs.append(f"  📊 {field}: '{value}' (Source: {source})")

        def _set_claim_field(field: str, value: str, source: str) -> None:
            if not value:
                return
            with claim_lock:
                setattr(claim, field, value)
                _mark_source(field, value, source)

        def _set_claim_status(field: str, value) -> None:
            with claim_lock:
                setattr(claim, field, value)

        def _start_job(kind: str, target: Callable[[], None]) -> None:
            event = threading.Event()
            setattr(claim, f"_deferred_{kind}_ocr_event", event)

            def _runner() -> None:
                try:
                    target()
                finally:
                    event.set()

            thread = threading.Thread(
                target=_runner,
                name=f"Deferred-{kind.title()}-OCR",
                daemon=True,
            )
            setattr(claim, f"_deferred_{kind}_ocr_thread", thread)
            thread.start()

        if getattr(claim, "_pending_invoice_ocr", False) and getattr(claim, "_pending_invoice_pdf_path", None):
            def _invoice_job() -> None:
                self.log.info("Deferred Workshop Invoice OCR started in background.")
                try:
                    from app.ui.services.claim_folder_service import ClaimFolderService
                    from app.utils import resource_path

                    config_dir = resource_path("app", "portals", self.portal_id, "config")
                    service = ClaimFolderService(config_dir=config_dir, portal_id=self.portal_id)

                    class MockScanResult:
                        def __init__(self, invoice_path: str):
                            self.assessment_files = {"invoice": invoice_path}

                    ocr_logs: List[str] = []
                    mock_scan = MockScanResult(claim._pending_invoice_pdf_path)
                    from copy import copy
                    with claim_lock:
                        ocr_claim = copy(claim)
                        ocr_claim._excel_coords = dict(getattr(claim, "_excel_coords", {}) or {})
                        ocr_claim._excel_logs = []

                    service._extract_pdf_invoice_data(mock_scan, ocr_claim, ocr_logs, stop_cb=self._check_stop)

                    with claim_lock:
                        for attr in (
                            "workshop_invoice_no",
                            "vendor_invoice_number",
                            "workshop_invoice_date",
                            "vendor_invoice_date",
                        ):
                            value = getattr(ocr_claim, attr, None)
                            if value:
                                setattr(claim, attr, value)
                        if hasattr(claim, "_excel_coords"):
                            claim._excel_coords.update(getattr(ocr_claim, "_excel_coords", {}) or {})
                        if hasattr(claim, "_excel_logs"):
                            claim._excel_logs.extend(getattr(ocr_claim, "_excel_logs", []) or [])

                    for line in ocr_logs:
                        self.log_cb(f"[Background OCR] {line.strip()}")

                    missing = [
                        label for label, attr in (
                            ("invoice number", "vendor_invoice_number"),
                            ("invoice date", "vendor_invoice_date"),
                        )
                        if not str(getattr(claim, attr, "") or "").strip()
                    ]
                    if missing:
                        message = f"Workshop Invoice OCR finished but missing: {', '.join(missing)}"
                        _set_claim_status("_deferred_invoice_ocr_error", message)
                        self.log.warning(message)
                    else:
                        _set_claim_status("_deferred_invoice_ocr_error", "")
                        self.log.success("Deferred Workshop Invoice OCR completed.")
                except Exception as exc:
                    _set_claim_status("_deferred_invoice_ocr_error", str(exc))
                    self.log.warning(f"Deferred Workshop Invoice OCR failed: {exc}")
                finally:
                    _set_claim_status("_pending_invoice_ocr", False)

            _start_job("invoice", _invoice_job)

        if getattr(claim, "_pending_cheque_ocr", False) and getattr(claim, "_pending_cheque_path", None):
            def _cheque_job() -> None:
                self.log.info("Deferred Cheque OCR started in background.")
                try:
                    from app.portals.newindia.automation.ocr_helper import ChequeExtractor

                    extractor = ChequeExtractor(claim._pending_cheque_path)
                    ocr_logs: List[str] = []

                    def ocr_log_fn(msg: str) -> None:
                        clean_msg = msg.encode("ascii", errors="ignore").decode("ascii")
                        if clean_msg.strip():
                            ocr_logs.append(f"  • {clean_msg.strip()}")

                    cheque_details = extractor.extract_details(
                        log=ocr_log_fn,
                        excel_ifsc=getattr(claim, "ifsc_code", None) or "",
                        excel_account=getattr(claim, "account_number", None) or "",
                        stop_cb=self._check_stop,
                    )

                    if cheque_details.get("ifsc"):
                        _set_claim_field("ifsc_code", cheque_details["ifsc"], "Cheque OCR")
                        self.log_cb(f"  ✅ [Background OCR] IFSC Code: {cheque_details['ifsc']}")
                    if cheque_details.get("account_number"):
                        _set_claim_field("account_number", cheque_details["account_number"], "Cheque OCR")
                        self.log_cb(f"  ✅ [Background OCR] Account Number: {cheque_details['account_number']}")
                    if cheque_details.get("account_type"):
                        _set_claim_field("account_type", cheque_details["account_type"], "Cheque OCR")
                        self.log_cb(f"  ✅ [Background OCR] Account Type: {cheque_details['account_type']}")

                    for line in ocr_logs:
                        self.log_cb(f"[Background OCR] {line}")

                    missing = [
                        label for label, attr in (
                            ("IFSC code", "ifsc_code"),
                            ("account number", "account_number"),
                        )
                        if not str(getattr(claim, attr, "") or "").strip()
                    ]
                    if missing:
                        message = f"Cheque OCR finished but missing: {', '.join(missing)}"
                        _set_claim_status("_deferred_cheque_ocr_error", message)
                        self.log.warning(message)
                    else:
                        _set_claim_status("_deferred_cheque_ocr_error", "")
                        self.log.success("Deferred Cheque OCR completed.")
                except Exception as exc:
                    _set_claim_status("_deferred_cheque_ocr_error", str(exc))
                    self.log.warning(f"Deferred Cheque OCR failed: {exc}")
                finally:
                    _set_claim_status("_pending_cheque_ocr", False)

            _start_job("cheque", _cheque_job)

    async def _wait_for_deferred_ocr(
        self,
        claim: ClaimData,
        *,
        kind: str,
        label: str,
        required_fields: tuple[tuple[str, str], ...],
        timeout_s: float = DEFERRED_OCR_TIMEOUT_SECONDS,
    ) -> bool:
        """Wait until a deferred OCR job finishes before dependent form fill."""
        event = getattr(claim, f"_deferred_{kind}_ocr_event", None)
        if event is None:
            return True

        if not event.is_set():
            self.log.wait(f"deferred {label} OCR", f"timeout {int(timeout_s)}s")
            deadline = time.monotonic() + timeout_s
            next_progress_log = time.monotonic() + 30.0

            while not event.is_set():
                if self._check_stop():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.log.error(f"Deferred {label} OCR timed out after {int(timeout_s)} seconds.")
                    return False
                if time.monotonic() >= next_progress_log:
                    self.log.info(f"Still waiting for deferred {label} OCR ({int(remaining)}s left).")
                    next_progress_log = time.monotonic() + 30.0
                await asyncio.sleep(0.5)

        missing = [
            label_name for label_name, attr in required_fields
            if not str(getattr(claim, attr, "") or "").strip()
        ]
        if missing:
            detail = getattr(claim, f"_deferred_{kind}_ocr_error", "") or "OCR produced no usable value."
            self.log.warning(
                f"Deferred {label} OCR did not resolve: {', '.join(missing)}. "
                f"{detail} Continuing with Excel/manual-entry fallback."
            )
            return True

        self.log.success(f"Deferred {label} OCR data is ready.")
        return True

    async def _wait_for_manual_review(self, browser: Browser):
        """
        Wait for either the user to close the browser manually OR
        the 'request_stop' flag to be set via the UI.
        """
        self.log_cb("⏳ Browser left open for manual review. Click Stop when done.")
        while not self._stop_requested:
            try:
                # If all contexts are closed, user closed browser
                if len(browser.contexts) == 0:
                    self.log_cb("Browser window was closed manually.")
                    break
                # If all pages in all contexts are closed, user closed browser
                all_pages = []
                for ctx in browser.contexts:
                    all_pages.extend(ctx.pages)
                if len(all_pages) == 0:
                    self.log_cb("Browser window was closed manually.")
                    break
            except Exception:
                break
            await asyncio.sleep(1)

    async def run_automation(self, claim: ClaimData, settings: Optional[dict] = None) -> AutomationRunResult:
        """Main entry point for claim automation."""
        if settings is None:
            settings = {}
        self._stop_requested = False
        
        # Determine steps based on portal
        if self.portal_id == "newindia":
            steps = [
                "Login", "Navigate", "Quick Update", "Photo Graph", "RC Details",
                "Driver Details", "FIR Details", "NEFT Details", "Work Approval",
                "Claim Assessment", "Document Upload", "Survey Fee Bill"
            ]
        elif self.portal_id == "oic":
            steps = ["Login", "Navigate", "Claim Search", "Basic Details", "Interim Report", "Assessment of Loss", "Document Upload"]
        else:
            steps = ["Login", "Navigate", "Interim Report", "Claim Documents", "Claim Assessment"]

        # No pre-run validation hard abort for OIC. Errors will be shown in the UI but the engine will proceed and launch the browser.

        field_delay = _setting_int(settings, "field_wait_ms", "field_delay_ms", 400)
        
        async with async_playwright() as p:
            # 1. Launch Browser
            browser_type = p.chromium
            launch_args = ["--start-maximized"]
            if settings.get("proxy_url"):
                launch_args.append(f"--proxy-server={settings['proxy_url']}")

            browser = await browser_type.launch(
                headless=_setting_bool(settings, "browser_headless", False),
                args=launch_args,
                slow_mo=_setting_int(settings, "browser_slow_mo_ms", "slow_mo_ms", 0)
            )

            # Create context without viewport to allow --start-maximized to work
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()

            # --- CIRCUIT BREAKER MONITOR ---
            health_state = {
                "empty_pages_since": None,
                "authenticated_page_ready": False
            }

            async def _monitor_health():
                """Closes automation if the user manually closes the tab mid-run."""
                while not self._stop_requested:
                    try:
                        alive = [p for p in context.pages if not p.is_closed()]
                        if not alive:
                            now = time.time()
                            if health_state["empty_pages_since"] is None:
                                health_state["empty_pages_since"] = now

                            grace_seconds = 2.0 if health_state["authenticated_page_ready"] else 10.0
                            if now - health_state["empty_pages_since"] >= grace_seconds:
                                self.log.error("CIRCUIT BREAKER: All pages were closed. Aborting run.")
                                self.request_stop()
                                break
                            await asyncio.sleep(0.5)
                            continue
                        health_state["empty_pages_since"] = None
                            
                        active = alive[-1]
                        if active.url.startswith("chrome-error://"):
                            self.log.error("CIRCUIT BREAKER: Network disconnected or 502/504 error. Aborting run.")
                            self.request_stop()
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(2)

            health_task = asyncio.create_task(_monitor_health())

            try:
                t_start = time.time()
                claim_type = settings.get("claim_type", "Non Maruti")

                self.log.startup_banner(
                    claim_no=claim.claim_no,
                    claim_type=claim_type,
                    survey_date=claim.date_of_survey or "—",
                    loss_amount=claim.initial_loss_amount or "—"
                )

                total_steps = len(steps)

                self.step_cb(0, steps[0])
                self.log.phase_banner(1, total_steps, "Login to Portal")

                if self.portal_id == "newindia":
                    from app.portals.newindia.automation.login_module import do_login
                elif self.portal_id == "oic":
                    from app.portals.oic.automation.login_module import do_login
                else:
                    from app.automation.login_module import do_login

                success = await do_login(
                    page,
                    settings=settings,
                    log=self.log,
                    stop_cb=self._check_stop,
                )
                if not success:
                    message = "Automation stopped by user." if self._check_stop() else "Login failed."
                    return AutomationRunResult(False, message)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                page = await _get_active_page(context, self.log, [], self._check_stop, portal_id=self.portal_id)
                if page is None:
                    message = "Automation stopped by user." if self._check_stop() else "Could not find an authenticated Worklist page."
                    return AutomationRunResult(False, message)
                health_state["authenticated_page_ready"] = True

                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=12000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)

                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                self.step_cb(1, steps[1])
                self.log.phase_banner(2, total_steps, f"Navigate to Claim ({claim.claim_no})")

                if self.portal_id == "newindia":
                    from app.portals.newindia.automation.navigation_module import navigate_to_claim
                    claim_page = await navigate_to_claim(page, claim.claim_no, settings=settings, log=self.log, stop_cb=self._check_stop)
                elif self.portal_id == "oic":
                    from app.portals.oic.automation.navigation_module import navigate_to_claim
                    claim_page = await navigate_to_claim(page, claim.claim_no, settings=settings, log=self.log, stop_cb=self._check_stop)
                else:
                    from app.automation.navigation_module import navigate_to_claim
                    claim_page = await navigate_to_claim(page, claim.claim_no, settings=settings, log=self.log)

                if claim_page is None:
                    return AutomationRunResult(False, f"Claim '{claim.claim_no}' was not found in Worklist or navigation failed.")
                
                page = claim_page
                self.log.info(f"Working on page: {page.url}")
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                self._start_deferred_ocr_jobs(claim)

                await asyncio.sleep(1.5)

                # --- NEW INDIA PORTAL PHASES ---
                if self.portal_id == "newindia":
                    # (Quick Update, Vehicle Photo, RC, Driver, FIR, NEFT, Work Approval, Assessment, Upload)
                    # I'll omit the full NIA block for brevity as I'm focused on UIIC refactor,
                    # but I'll ensure the existing NIA logic remains compatible with 'log=self.log'
                    
                    from app.portals.newindia.automation.quick_update_module import fill_quick_update_details
                    from app.portals.newindia.automation.vehicle_photo_module import fill_vehicle_photo_graph
                    from app.portals.newindia.automation.registration_cert_module import fill_registration_cert_details
                    from app.portals.newindia.automation.driver_details_module import fill_driver_details
                    from app.portals.newindia.automation.fir_details_module import fill_fir_details
                    from app.portals.newindia.automation.neft_module import fill_neft_details
                    from app.portals.newindia.automation.work_approval_module import fill_work_approval_details
                    from app.portals.newindia.automation.claim_assessment_module import fill_claim_assessment_details
                    from app.portals.newindia.automation.survey_fee_bill_module import fill_survey_fee_bill
                    from app.portals.newindia.automation.document_upload_module import fill_document_upload_section

                    # Phase 3: Quick Update
                    self.step_cb(2, steps[2])
                    self.log.phase_banner(3, total_steps, "Fill Quick Update Details")
                    if not await fill_quick_update_details(page, claim, log=self.log, stop_cb=self._check_stop):
                        return AutomationRunResult(False, "Phase 3 failed.")

                    # Phase 4: Vehicle Photo
                    self.step_cb(3, steps[3])
                    self.log.phase_banner(4, total_steps, "Vehicle Photo Graph")
                    if not await fill_vehicle_photo_graph(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 4 failed.")

                    # Phase 5: RC Details
                    self.step_cb(4, steps[4])
                    self.log.phase_banner(5, total_steps, "Registration Certificate Details")
                    if not await fill_registration_cert_details(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 5 failed.")

                    # Phase 6: Driver Details
                    self.step_cb(5, steps[5])
                    self.log.phase_banner(6, total_steps, "Driver Details")
                    if not await fill_driver_details(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 6 failed.")

                    # Phase 7: FIR Details
                    self.step_cb(6, steps[6])
                    self.log.phase_banner(7, total_steps, "FIR Details")
                    if not await fill_fir_details(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 7 failed.")

                    # Phase 8: NEFT Details
                    self.step_cb(7, steps[7])
                    self.log.phase_banner(8, total_steps, "NEFT Details")
                    if not await self._wait_for_deferred_ocr(
                        claim,
                        kind="cheque",
                        label="Cheque",
                        required_fields=(
                            ("IFSC Code", "ifsc_code"),
                            ("Account Number", "account_number"),
                        ),
                    ):
                        return AutomationRunResult(False, "Phase 8 failed: cheque OCR data not ready.")
                    if not await fill_neft_details(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 8 failed.")

                    # Phase 9: Work Approval
                    self.step_cb(8, steps[8])
                    self.log.phase_banner(9, total_steps, "Work Approval")
                    if not await fill_work_approval_details(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 9 failed.")

                    # Phase 10: Claim Assessment
                    self.step_cb(9, steps[9])
                    self.log.phase_banner(10, total_steps, "Claim Assessment")
                    if not await self._wait_for_deferred_ocr(
                        claim,
                        kind="invoice",
                        label="Workshop Invoice",
                        required_fields=(
                            ("Vendor Invoice Date", "vendor_invoice_date"),
                            ("Vendor Invoice Number", "vendor_invoice_number"),
                        ),
                    ):
                        return AutomationRunResult(False, "Phase 10 failed: invoice OCR data not ready.")
                    if not await fill_claim_assessment_details(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 10 failed.")

                    # Phase 11: Document Upload
                    # (Runs before Survey Fee Bill to match the portal's
                    #  top-to-bottom accordion order on the Document Upload tab)
                    self.step_cb(10, steps[10])
                    self.log.phase_banner(11, total_steps, "Document Upload")
                    if not await fill_document_upload_section(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 11 failed.")

                    # Phase 12: Survey Fee Bill
                    self.step_cb(11, steps[11])
                    self.log.phase_banner(12, total_steps, "Survey Fee Bill")
                    if not await fill_survey_fee_bill(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 12 failed.")

                    t_total = time.time() - t_start
                    self.log.section_done("Total New India Workflow", show_duration=True)
                    await self._wait_for_manual_review(browser)
                    return AutomationRunResult(True, "New India phases complete.")

                # --- OIC PORTAL PHASES ---
                if self.portal_id == "oic":
                    from app.portals.oic.automation.claim_search_module import fill_claim_search
                    from app.portals.oic.automation.basic_details_module import fill_basic_details

                    # Phase 3: Claim Search (Generate Assessment form)
                    self.step_cb(2, steps[2])
                    self.log.phase_banner(3, total_steps, "Claim Search")
                    if not await fill_claim_search(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 3 (Claim Search) failed.")

                    # Phase 4: Basic Details
                    self.step_cb(3, steps[3])
                    self.log.phase_banner(4, total_steps, "Basic Details")
                    if not await fill_basic_details(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 4 (Basic Details) failed.")

                    # Phase 5: Interim Report
                    self.step_cb(4, steps[4])
                    self.log.phase_banner(5, total_steps, "Interim Report")
                    from app.portals.oic.automation.interim_report_module import fill_interim_report
                    if not await fill_interim_report(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 5 (Interim Report) failed.")

                    # Phase 6: Assessment of Loss
                    self.step_cb(5, steps[5])
                    self.log.phase_banner(6, total_steps, "Assessment of Loss")
                    if not await self._wait_for_deferred_ocr(
                        claim,
                        kind="invoice",
                        label="Workshop Invoice",
                        required_fields=(
                            ("Workshop Invoice No", "workshop_invoice_no"),
                            ("Workshop Invoice Date", "workshop_invoice_date"),
                        ),
                    ):
                        return AutomationRunResult(False, "Phase 6 failed: invoice OCR timed out or stopped.")
                    from app.portals.oic.automation.assessment_of_loss_module import fill_assessment_of_loss
                    if not await fill_assessment_of_loss(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 6 (Assessment of Loss) failed.")

                    # Phase 7: Document Upload
                    self.step_cb(6, steps[6])
                    self.log.phase_banner(7, total_steps, "Document Upload")
                    from app.portals.oic.automation.document_upload_module import fill_document_upload_section
                    if not await fill_document_upload_section(page, claim, log=self.log, stop_cb=self._check_stop, field_delay_ms=field_delay):
                        return AutomationRunResult(False, "Phase 7 (Document Upload) failed.")

                    t_total = time.time() - t_start
                    self.log.section_done("Total Oriental Insurance Workflow", show_duration=True)
                    await self._wait_for_manual_review(browser)
                    return AutomationRunResult(True, "Oriental Insurance phases complete.")

                # --- UIIC PORTAL PHASES ---
                self.step_cb(2, steps[2])
                self.log.phase_banner(3, total_steps, "Fill Interim Report")
                await page.bring_to_front()
                await page.evaluate("window.scrollTo(0, 0)")
                await fill_interim_report(page, claim, log_cb=self.log, settings=settings)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                await asyncio.sleep(1.0)
                await page.bring_to_front()

                self.step_cb(3, steps[3])
                self.log.phase_banner(4, total_steps, "Upload Claim Documents")
                await page.evaluate("window.scrollTo(0, 0)")
                await fill_claim_documents(page, claim, log_cb=self.log, settings=settings)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                await asyncio.sleep(1.0)
                await page.bring_to_front()

                self.step_cb(4, steps[4])
                self.log.phase_banner(5, total_steps, "Fill Claim Assessment")
                if not await self._wait_for_deferred_ocr(
                    claim,
                    kind="invoice",
                    label="Workshop Invoice",
                    required_fields=(
                        ("Workshop Invoice No", "workshop_invoice_no"),
                        ("Workshop Invoice Date", "workshop_invoice_date"),
                    ),
                ):
                    return AutomationRunResult(False, "Phase 5 failed: invoice OCR timed out or stopped.")
                await page.evaluate("window.scrollTo(0, 0)")
                await fill_claim_assessment(page, claim, log_cb=self.log, settings=settings)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                t_total = time.time() - t_start
                self.step_cb(5, "Complete")
                self.log.section_done("Total UIIC Workflow", show_duration=True)

                await self._wait_for_manual_review(browser)
                return AutomationRunResult(True, "Automation finished.")

            except asyncio.CancelledError:
                self.log.error("Automation cancelled.")
                return AutomationRunResult(False, "Automation cancelled.")
            except Exception as exc:
                self.log.error(f"Automation failed: {exc}")
                logger.exception("Automation error")
                return AutomationRunResult(False, f"Automation failed: {exc}")
            finally:
                if health_task and not health_task.done():
                    health_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await health_task
                await browser.close()
