"""
login_module.py
Handles login to the UIIC Surveyor portal.
Verified selectors (April 2026):
  - Username:  #login-username
  - Password:  #login-password
  - CAPTCHA canvas: canvas#captcha
  - CAPTCHA input:  input[name='captchaInput']
  - Login button:   button with ng-click="login()" or #btn-login
Success detection: login form (#login-username) disappears from the DOM.
"""

import asyncio
import logging
import os
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SEL_USERNAME = "#login-username"
SEL_PASSWORD = "#login-password"
SEL_CAPTCHA_IN = "input[name='captchaInput']"
SEL_CAPTCHA_CVS = "canvas#captcha, canvas"
SEL_LOGIN_BTN = "#btn-login, button[ng-click*='login'], button:has-text('Login'), button:has-text('Sign In')"
SEL_REFRESH_BTN = "button[title='Refresh Captcha'], a[ng-click*='captcha'], .captcha-refresh"
SEL_ERROR_MSG = ".alert-danger, .text-danger, .ng-scope .alert, #errorMsg"
SEL_DASHBOARD_MARKERS = (
    "a:has-text('Worklist'), "
    "a:has-text('Logout'), "
    "a:has-text('Claim Documents'), "
    "a:has-text('Claim Assessment'), "
    "a:has-text('Interim Report')"
)


async def _get_captcha_bytes(page) -> bytes:
    await asyncio.sleep(1.0)
    try:
        canvas = page.locator("canvas#captcha").first
        await canvas.wait_for(state="visible", timeout=8000)
        return await canvas.screenshot()
    except Exception:
        canvas = page.locator("canvas").first
        await canvas.wait_for(state="visible", timeout=5000)
        return await canvas.screenshot()


async def _is_logged_in(page) -> bool:
    try:
        login_el = page.locator(SEL_USERNAME).first
        visible = await login_el.is_visible(timeout=2000)
        return not visible
    except Exception:
        return True


async def _dismiss_alert(page, timeout: int = 4000):
    for sel in [
        "div.modal.in button:has-text('OK')",
        ".modal-footer .btn-primary",
        ".modal button.btn-primary",
        "button:has-text('OK')",
    ]:
        try:
            btn = page.locator(sel).first
            await btn.wait_for(state="visible", timeout=timeout // 4)
            await btn.click()
            await asyncio.sleep(0.6)
            logger.info("Modal alert dismissed.")
            return
        except Exception:
            continue


async def _get_error_text(page) -> str:
    try:
        err = (await page.locator(SEL_ERROR_MSG).first.inner_text()).strip()
        return err
    except Exception:
        return ""


async def _has_dashboard_marker(page) -> bool:
    for sel in [part.strip() for part in SEL_DASHBOARD_MARKERS.split(",")]:
        try:
            if await page.locator(sel).first.is_visible(timeout=400):
                return True
        except Exception:
            continue
    return False


async def _login_form_gone_stably(page) -> bool:
    """
    Guard against transient DOM rerenders after submit.
    Treat the form as gone only if it stays absent for multiple polls.
    """
    for _ in range(4):
        try:
            user_visible = await page.locator(SEL_USERNAME).first.is_visible(timeout=250)
        except Exception:
            user_visible = False

        try:
            captcha_visible = await page.locator(SEL_CAPTCHA_IN).first.is_visible(timeout=250)
        except Exception:
            captcha_visible = False

        if user_visible or captcha_visible:
            return False
        await asyncio.sleep(0.35)
    return True


async def _wait_for_login_outcome(page, log_cb: Callable[[str], None]) -> tuple[bool, str]:
    """
    Wait for a confirmed login success or a confirmed failure signal.
    This avoids false positives when the login form briefly rerenders.
    """
    context = page.context

    for _ in range(20):
        try:
            pages = context.pages
        except Exception:
            pages = []

        for open_page in pages:
            try:
                url = open_page.url
            except Exception:
                continue
            if "Surveyor.html" in url or ("surveyor" in url.lower() and "home.jsp" not in url.lower()):
                return True, f"Dashboard tab detected: {url}"

        try:
            current_url = page.url
        except Exception:
            current_url = ""

        if current_url and "home.jsp" not in current_url.lower():
            return True, f"Navigated away from login page: {current_url}"

        if await _has_dashboard_marker(page):
            return True, "Dashboard navigation links detected on page."

        if await _login_form_gone_stably(page):
            return True, "Login form disappeared and stayed absent."

        err = await _get_error_text(page)
        if err:
            return False, err

        await asyncio.sleep(0.5)

    return False, "Login was not confirmed within the expected time."


async def _accept_dialog(dialog, log_cb: Callable[[str], None]):
    try:
        message = (dialog.message or "").strip()
        if message:
            log_cb(f"  Portal dialog: {message[:120]}")
        await dialog.accept()
        await asyncio.sleep(0.5)
    except Exception as exc:
        log_cb(f"  Warning: could not accept portal dialog: {exc}")


async def _refresh_captcha(page):
    for sel in SEL_REFRESH_BTN.split(", "):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await asyncio.sleep(1.2)
                return
        except Exception:
            continue


async def _try_login_with_captcha(page, username, password, captcha_text, log_cb):
    await page.locator(SEL_USERNAME).fill("")
    await asyncio.sleep(0.3)
    await page.locator(SEL_USERNAME).fill(username)
    await asyncio.sleep(0.4)

    await page.locator(SEL_PASSWORD).fill("")
    await asyncio.sleep(0.25)
    await page.locator(SEL_PASSWORD).fill(password)
    await asyncio.sleep(0.4)

    captcha_input = page.locator(SEL_CAPTCHA_IN).first
    await captcha_input.fill("")
    await asyncio.sleep(0.2)
    await captcha_input.fill(captcha_text)
    await asyncio.sleep(0.6)

    for btn_sel in SEL_LOGIN_BTN.split(", "):
        try:
            btn = page.locator(btn_sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                log_cb("  Clicked login button")
                return True
        except Exception:
            continue

    log_cb("  Login button not found.")
    return False


async def do_login(
    page,
    portal_url: str,
    username: str,
    password: str,
    max_retries: int = 5,
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    """
    Navigate to the portal and perform login.
    Returns True on success, False otherwise.
    """
    from app.automation.captcha_solver import get_captcha_candidates

    page.on("dialog", lambda dialog: asyncio.create_task(_accept_dialog(dialog, log_cb)))

    log_cb("Navigating to portal...")
    await page.goto(portal_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(2)

    try:
        await page.locator(SEL_USERNAME).wait_for(state="visible", timeout=12000)
        log_cb("Login page loaded.")
    except Exception as exc:
        log_cb(f"Login page did not load properly: {exc}")
        return False

    for attempt in range(1, max_retries + 1):
        if stop_cb():
            return False

        log_cb(f"Login attempt {attempt}/{max_retries}...")
        log_cb("Reading CAPTCHA from canvas...")

        try:
            img_bytes = await _get_captcha_bytes(page)
            candidates = get_captcha_candidates(img_bytes)
        except Exception as exc:
            log_cb(f"CAPTCHA screenshot error: {exc}")
            await _refresh_captcha(page)
            continue

        if not candidates or len(candidates[0]) < 3:
            log_cb("CAPTCHA unreadable. Refreshing...")
            await _refresh_captcha(page)
            continue

        log_cb(f"CAPTCHA candidates: {candidates}")

        logged_in = False
        for variant_idx, captcha_text in enumerate(candidates):
            if stop_cb():
                return False

            if captcha_text == captcha_text.upper() and any(c.isalpha() for c in captcha_text):
                case_label = "ALL-UPPER"
            elif captcha_text == captcha_text.lower() and any(c.isalpha() for c in captcha_text):
                case_label = "all-lower"
            else:
                case_label = "Mixed-Case"

            variant_label = f"{'primary' if variant_idx == 0 else 'fallback'} / {case_label}"
            log_cb(f"Trying CAPTCHA [{variant_label}]: '{captcha_text}'")

            clicked = await _try_login_with_captcha(page, username, password, captcha_text, log_cb)
            if not clicked:
                break

            await asyncio.sleep(2)
            if stop_cb():
                return False

            login_ok, outcome = await _wait_for_login_outcome(page, log_cb)
            if login_ok:
                log_cb(f"Login confirmed. CAPTCHA variant: {variant_label}")
                log_cb(f"  Success signal: {outcome}")
                await _dismiss_alert(page)
                await asyncio.sleep(1.5)
                logged_in = True
                break

            err = outcome.strip()
            if err:
                log_cb(f"  Login not confirmed: {err[:140]}")
                if "password" in err.lower() and "captcha" not in err.lower():
                    log_cb("  Wrong password detected. Not retrying more CAPTCHA variants.")
                    break

            if variant_idx < len(candidates) - 1:
                log_cb("  Variant failed, trying the next candidate...")
                try:
                    await page.locator(SEL_CAPTCHA_IN).fill("")
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

        if logged_in:
            return True

        if stop_cb():
            return False

        log_cb(f"All variants failed on attempt {attempt}. Refreshing CAPTCHA...")
        await _refresh_captcha(page)
        await asyncio.sleep(1)

    log_cb("Login failed after all retries.")
    return False
