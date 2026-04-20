"""
engine.py - Master automation orchestrator.

Post-login strategy:
  1. Capture any newly opened tabs after login.
  2. Prefer an existing Surveyor.html page when it appears.
  3. If the portal closes the login tab before the new tab is usable,
     open a fresh page inside the same browser context and navigate
     directly to Worklist using the authenticated session cookies.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from app.automation.claim_assessment import fill_claim_assessment
from app.automation.claim_documents import fill_claim_documents
from app.automation.interim_report import fill_interim_report
from app.automation.login_module import do_login
from app.automation.navigation_module import WORKLIST_URL, navigate_to_claim
from app.data.data_model import ClaimData

from app.utils import load_settings, resource_path

logger = logging.getLogger(__name__)
CONFIG_DIR = resource_path("app", "config")


def _load_settings() -> dict:
    # Production reliability: in a frozen EXE, bundled config is read-only.
    # The UI writes user settings into a writable per-user location, so we
    # must read that (and merge with defaults) here too.
    return load_settings()


@dataclass
class AutomationRunResult:
    success: bool
    message: str


def _collect_alive_pages(context: BrowserContext, captured_pages: List[Page]) -> List[Page]:
    pages: List[Page] = []
    seen = set()

    candidates: List[Page] = []
    candidates.extend(captured_pages)
    try:
        candidates.extend(context.pages)
    except Exception as e:
        logger.error(f"Error collecting pages: {e}")
        raise e

    for page in candidates:
        marker = id(page)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            if page.is_closed():
                continue
            pages.append(page)
        except Exception:
            continue
    return pages


def _pick_best_page(pages: List[Page], log_cb: Callable[[str], None]) -> Page:
    for page in reversed(pages):
        try:
            url = page.url
            if "Surveyor.html" in url or ("surveyor" in url.lower() and "home.jsp" not in url.lower()):
                log_cb(f"Found Surveyor page: {url}")
                return page
        except Exception:
            continue

    for page in reversed(pages):
        try:
            url = page.url
            if "home.jsp" not in url.lower():
                log_cb(f"Using non-login page: {url}")
                return page
        except Exception:
            continue

    log_cb(f"Using last open page: {pages[-1].url}")
    return pages[-1]


def _find_surveyor_page(pages: List[Page]) -> Optional[Page]:
    for page in reversed(pages):
        try:
            url = page.url
            if "Surveyor.html" in url or ("surveyor" in url.lower() and "home.jsp" not in url.lower()):
                return page
        except Exception:
            continue
    return None


async def _page_has_login_form(page: Page) -> bool:
    try:
        return await page.locator("#login-username").first.is_visible(timeout=1500)
    except Exception:
        return False


async def _get_active_page(
    context: BrowserContext,
    log_cb: Callable[[str], None],
    captured_pages: List[Page],
    stop_cb: Callable[[], bool],
) -> Optional[Page]:
    """
    Acquire a usable authenticated page after login.

    The portal can close the login tab and open Surveyor.html in a new tab
    almost simultaneously. Instead of waiting indefinitely for that tab,
    we briefly look for it and then fall back to opening Worklist directly
    in the same authenticated browser context.
    """
    log_cb("Locating dashboard/worklist page...")

    for tick in range(6):
        if stop_cb():
            return None

        pages = _collect_alive_pages(context, captured_pages)
        surveyor_page = _find_surveyor_page(pages)
        if surveyor_page is not None:
            log_cb(f"Found Surveyor page: {surveyor_page.url}")
            page = surveyor_page
            await page.bring_to_front()
            return page

        if tick in {1, 3, 5}:
            elapsed = (tick + 1) * 0.5
            log_cb(f"  No dashboard tab yet ({elapsed:.1f}s).")
        await asyncio.sleep(0.5)

    for attempt in range(1, 4):
        if stop_cb():
            return None

        new_page: Optional[Page] = None
        try:
            log_cb(f"Opening authenticated Worklist page (attempt {attempt}/3)...")
            new_page = await context.new_page()
            await new_page.goto(WORKLIST_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            if await _page_has_login_form(new_page):
                log_cb("Login form is still visible after direct navigation; waiting for session to settle.")
                await new_page.close()
                await asyncio.sleep(1)
                continue

            log_cb(f"Worklist page ready: {new_page.url}")
            await new_page.bring_to_front()
            return new_page
        except Exception as exc:
            log_cb(f"Direct navigation attempt {attempt} failed: {exc}")
            if new_page is not None:
                try:
                    if not new_page.is_closed():
                        await new_page.close()
                except Exception:
                    pass
            await asyncio.sleep(1)

    pages = _collect_alive_pages(context, captured_pages)
    if pages:
        page = _pick_best_page(pages, log_cb)
        await page.bring_to_front()
        return page

    log_cb("No active dashboard page could be established.")
    return None


class AutomationEngine:
    def __init__(
        self,
        log_cb: Callable[[str], None] = print,
        step_cb: Callable[[int, str], None] = None,
    ):
        self.log_cb = log_cb
        self.step_cb = step_cb or (lambda i, s: None)
        self._stop_requested = False

    def request_stop(self):
        if not self._stop_requested:
            self.log_cb("Stop requested. Closing automation safely...")
            self._stop_requested = True

    def _check_stop(self) -> bool:
        return self._stop_requested

    async def _wait_for_manual_review(self, browser) -> None:
        self.log_cb("Browser left open for manual review. Click Stop in the app when you are done.")
        while True:
            if self._check_stop():
                return
            try:
                if not browser.is_connected():
                    self.log_cb("Browser window was closed manually.")
                    return
            except Exception:
                return
            await asyncio.sleep(1)

    async def run(self, claim: ClaimData, settings_override: dict = None) -> AutomationRunResult:
        settings = _load_settings()
        if settings_override:
            settings.update(settings_override)

        portal_url = settings["portal_url"]
        username = settings["username"]
        password = settings["password"]
        claim_type = settings.get("claim_type", "Non Maruti")
        headless = settings.get("browser_headless", False)
        slow_mo = settings.get("browser_slow_mo_ms", 200)  # 200ms = visible but not sluggish
        max_retries = settings.get("captcha_max_retries", 5)

        steps = ["Login", "Navigate to Claim", "Interim Report", "Claim Documents", "Claim Assessment"]
        browser = None

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=headless,
                slow_mo=slow_mo,
                args=[
                    "--start-maximized",
                    "--window-size=1920,1080",      # fallback if --start-maximized ignored
                    "--disable-infobars",           # no "Chrome is controlled by..." bar
                    "--disable-features=TranslateUI",
                ]
            )
            context = await browser.new_context(
                no_viewport=True,                  # let OS window size dictate
                accept_downloads=True,
            )
            page = await context.new_page()
            await page.bring_to_front()            # ensure browser is on top from start

            # ── Auto-accept JS dialogs (alert/confirm/prompt) ─────────────────
            # Portal may show alerts during upload — auto-dismiss them.
            # (Proven approach from Doc_uploader.py)
            async def _on_dialog(dialog):
                self.log_cb(f"Dialog detected ({dialog.type}): {dialog.message} — auto-accepting.")
                try:
                    await dialog.accept()
                except Exception:
                    pass  # already dismissed / stale — ignore
            page.on("dialog", _on_dialog)

            captured_pages: List[Page] = []
            context.on("page", lambda p: captured_pages.append(p))

            try:
                self.step_cb(0, steps[0])
                self.log_cb("-" * 36)
                self.log_cb("STEP 1 - Login")
                self.log_cb("-" * 36)

                success = await do_login(
                    page,
                    portal_url,
                    username,
                    password,
                    max_retries=max_retries,
                    log_cb=self.log_cb,
                    stop_cb=self._check_stop,
                )
                if not success:
                    message = "Automation stopped by user." if self._check_stop() else "Login failed."
                    return AutomationRunResult(False, message)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                page = await _get_active_page(context, self.log_cb, captured_pages, self._check_stop)
                if page is None:
                    message = "Automation stopped by user." if self._check_stop() else "Could not find an authenticated Worklist page."
                    return AutomationRunResult(False, message)

                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=12000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)

                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                self.step_cb(1, steps[1])
                self.log_cb("-" * 36)
                self.log_cb(f"STEP 2 - Navigate to Claim: {claim.claim_no}")
                self.log_cb("-" * 36)

                claim_page = await navigate_to_claim(page, claim.claim_no, claim_type, log_cb=self.log_cb)
                if claim_page is None:
                    return AutomationRunResult(False, f"Claim '{claim.claim_no}' was not found in Worklist.")
                # Switch to the claim details page (may be a new tab)
                page = claim_page
                self.log_cb(f"📌 Working on page: {page.url}")
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                await asyncio.sleep(1.5)

                self.step_cb(2, steps[2])
                self.log_cb("-" * 36)
                self.log_cb("STEP 3 - Fill Interim Report")
                self.log_cb("-" * 36)
                await page.bring_to_front()
                await page.evaluate("window.scrollTo(0, 0)")
                await fill_interim_report(page, claim, log_cb=self.log_cb)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                await asyncio.sleep(1.0)
                await page.bring_to_front()

                self.step_cb(3, steps[3])
                self.log_cb("-" * 36)
                self.log_cb("STEP 4 - Upload Claim Documents")
                self.log_cb("-" * 36)
                await page.evaluate("window.scrollTo(0, 0)")
                await fill_claim_documents(page, claim, log_cb=self.log_cb)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                await asyncio.sleep(1.0)
                await page.bring_to_front()

                self.step_cb(4, steps[4])
                self.log_cb("-" * 36)
                self.log_cb("STEP 5 - Fill Claim Assessment")
                self.log_cb("-" * 36)
                await page.evaluate("window.scrollTo(0, 0)")
                await fill_claim_assessment(page, claim, log_cb=self.log_cb)
                if self._check_stop():
                    return AutomationRunResult(False, "Automation stopped by user.")

                self.step_cb(5, "Complete")
                self.log_cb("")
                self.log_cb("AUTOMATION COMPLETE")
                self.log_cb("Please review all tabs in the browser, then click Final Submit manually.")
                self.log_cb("")

                await self._wait_for_manual_review(browser)
                return AutomationRunResult(True, "Automation finished and browser session was closed.")

            except asyncio.CancelledError:
                self.log_cb("Automation cancelled.")
                return AutomationRunResult(False, "Automation cancelled.")
            except Exception as exc:
                self.log_cb(f"ERROR: {exc}")
                logger.exception("Automation error")
                return AutomationRunResult(False, f"Automation failed: {exc}")
            finally:
                # B7 FIX: Do NOT call browser.close() here.
                # The 'async with async_playwright()' context manager closes
                # the browser automatically when the block exits.
                # Explicit close() here caused double-close RuntimeWarning.
                pass
