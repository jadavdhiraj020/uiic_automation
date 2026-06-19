import asyncio
import logging
import os
from typing import Callable, Optional
from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

SEL_USERNAME = "#login-username, input[name='username']"
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


async def _dismiss_alert(page, log, timeout: int = 4000):
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
            if isinstance(log, AutomationLogger):
                log.info("Modal alert dismissed.")
            else:
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


async def _wait_for_login_outcome(page, log) -> tuple[bool, str]:
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


async def _accept_dialog(dialog, log):
    try:
        message = (dialog.message or "").strip()
        if message:
            if isinstance(log, AutomationLogger):
                log.info(f"Portal dialog: {message[:120]}")
            else:
                log(f"  Portal dialog: {message[:120]}")
        await dialog.accept()
        await asyncio.sleep(0.5)
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.warning(f"Could not accept portal dialog: {exc}")
        else:
            log(f"  Warning: could not accept portal dialog: {exc}")


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


async def _try_login_with_captcha(page, username, password, captcha_text, log):
    await page.locator(SEL_USERNAME).fill("")
    await asyncio.sleep(0.3)
    await page.locator(SEL_USERNAME).fill(username)
    if isinstance(log, AutomationLogger):
        log.raw(f"[{log._portal_tag}][Login]\nUsername Entered")
    await asyncio.sleep(0.4)

    await page.locator(SEL_PASSWORD).fill("")
    await asyncio.sleep(0.25)
    await page.locator(SEL_PASSWORD).fill(password)
    if isinstance(log, AutomationLogger):
        log.raw(f"[{log._portal_tag}][Login]\nPassword Entered")
    await asyncio.sleep(0.4)

    captcha_input = page.locator(SEL_CAPTCHA_IN).first
    await captcha_input.fill("")
    await asyncio.sleep(0.2)
    await captcha_input.fill(captcha_text)
    if isinstance(log, AutomationLogger):
        log.raw(f"[{log._portal_tag}][Login]\nCaptcha Entered")
    await asyncio.sleep(0.6)

    for btn_sel in SEL_LOGIN_BTN.split(", "):
        try:
            btn = page.locator(btn_sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                if isinstance(log, AutomationLogger):
                    log.raw(f"[{log._portal_tag}][Login]\nLogin Button Clicked")
                    log.info("Clicked login button")
                else:
                    log("  Clicked login button")
                return True
        except Exception:
            continue

    if isinstance(log, AutomationLogger):
        log.raw(f"[{log._portal_tag}][Login]\nLogin Button Not Found")
        log.error("Login button not found.")
    else:
        log("  Login button not found.")
    return False


async def do_login(
    page,
    settings: dict,
    log = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    """
    Navigate to the portal and perform login.
    Returns True on success, False otherwise.
    """
    if isinstance(log, AutomationLogger):
        log.section = "Login"

    portal_url = settings["portal_url"]
    username = settings["username"]
    password = settings["password"]
    max_retries = settings.get("captcha_max_retries", 5)

    from app.automation.captcha_solver import solve_captcha_from_bytes

    async def handle_login_dialog(dialog):
        await _accept_dialog(dialog, log)

    try:
        page.remove_all_listeners("dialog")
    except Exception:
        pass
    page.on("dialog", handle_login_dialog)

    try:
        if isinstance(log, AutomationLogger):
            log.raw(f"[{log._portal_tag}][Login]\nLoading Login Page")
            log.info("Navigating to portal...")
            log.indent()
        else:
            log("  🌐 Navigating to portal...")
            
        await page.goto(portal_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        try:
            await page.locator(SEL_USERNAME).wait_for(state="visible", timeout=12000)
            if isinstance(log, AutomationLogger):
                log.raw(f"[{log._portal_tag}][Login]\nLogin Page Loaded")
                log.success("Login page loaded successfully")
            else:
                log("  ✅ Login page loaded successfully")
        except Exception as exc:
            if isinstance(log, AutomationLogger):
                log.raw(f"[{log._portal_tag}][Login]\nLogin Page Load Failed")
                log.error(f"Login page did not load: {exc}")
                log.outdent()
            else:
                log(f"  ❌ Login page did not load: {exc}")
            return False

        for attempt in range(1, max_retries + 1):
            if stop_cb():
                if isinstance(log, AutomationLogger): log.outdent()
                return False

            if isinstance(log, AutomationLogger):
                log.raw(f"[{log._portal_tag}][Login]\nAttempt {attempt}/{max_retries}")
                log.info(f"Login Attempt {attempt}/{max_retries}")
                log.indent()
            else:
                log(f"\n  🔄 Attempt {attempt}/{max_retries}")
                
            if isinstance(log, AutomationLogger):
                log.raw(f"[{log._portal_tag}][Login]\nCaptcha OCR Started")
                log.wait("Reading CAPTCHA from canvas")
            else:
                log("    📷 Reading CAPTCHA from canvas...")

            try:
                img_bytes = await _get_captcha_bytes(page)
                captcha_text = solve_captcha_from_bytes(img_bytes)
            except Exception as exc:
                if isinstance(log, AutomationLogger):
                    log.raw(f"[{log._portal_tag}][Login]\nCaptcha Capture Failed")
                    log.error(f"CAPTCHA screenshot error: {exc}")
                else:
                    log(f"    ⚠️  CAPTCHA screenshot error: {exc}")
                await _refresh_captcha(page)
                if isinstance(log, AutomationLogger): log.outdent()
                continue

            if not captcha_text or len(captcha_text) < 3:
                from app.automation.ocr_engine import get_ocr_init_error
                init_error = get_ocr_init_error()
                if init_error:
                    if isinstance(log, AutomationLogger):
                        log.raw(f"[{log._portal_tag}][Login]\nOCR Engine Initialization Failed")
                        log.error(f"OCR ENGINE FAILED: {init_error}")
                    else:
                        log(f"⚠️ OCR ENGINE FAILED: {init_error}")
                else:
                    if isinstance(log, AutomationLogger):
                        log.raw(f"[{log._portal_tag}][Login]\nCaptcha Unreadable")
                        log.warning("CAPTCHA unreadable. Refreshing...")
                    else:
                        log(f"CAPTCHA unreadable (OCR returned empty/short text). Refreshing...")
                await _refresh_captcha(page)
                if isinstance(log, AutomationLogger): log.outdent()
                continue

            if isinstance(log, AutomationLogger):
                log.raw(f"[{log._portal_tag}][Login]\nCaptcha Value Extracted: {captcha_text}")
                log.info(f"CAPTCHA text: '{captcha_text}'")
            else:
                log(f"    🔑 CAPTCHA text: '{captcha_text}'")

            if stop_cb():
                if isinstance(log, AutomationLogger): 
                    log.outdent()
                    log.outdent()
                return False

            clicked = await _try_login_with_captcha(page, username, password, captcha_text, log)
            if not clicked:
                if isinstance(log, AutomationLogger):
                    log.raw(f"[{log._portal_tag}][Login]\nLogin Click Failed")
                    log.error(f"Could not click login button on attempt {attempt}")
                else:
                    log(f"    ⚠️  Could not click login button on attempt {attempt}")
                await _refresh_captcha(page)
                if isinstance(log, AutomationLogger): log.outdent()
                continue

            await asyncio.sleep(2)
            if stop_cb():
                if isinstance(log, AutomationLogger):
                    log.outdent()
                    log.outdent()
                return False

            login_ok, outcome = await _wait_for_login_outcome(page, log)
            if login_ok:
                if isinstance(log, AutomationLogger):
                    log.raw(f"[{log._portal_tag}][Login]\nLogin Successful")
                    log.success("Login successful!")
                    log.info(f"Signal: {outcome}")
                else:
                    log(f"    ✅ Login successful!")
                    log(f"    ℹ️  Signal: {outcome}")
                await _dismiss_alert(page, log)
                await asyncio.sleep(1.5)
                if isinstance(log, AutomationLogger):
                    log.outdent()
                    log.outdent()
                return True

            err = outcome.strip()
            if err:
                if isinstance(log, AutomationLogger):
                    log.raw(f"[{log._portal_tag}][Login]\nLogin Failed\nReason: {err[:140]}")
                    log.error(f"Login failed: {err[:140]}")
                else:
                    log(f"    ❌ Login failed: {err[:140]}")
                    
                if "password" in err.lower() and "captcha" not in err.lower():
                    if isinstance(log, AutomationLogger):
                        log.raw(f"[{log._portal_tag}][Login]\nWrong Password stopping retries")
                        log.error("Wrong password detected — stopping retries")
                    else:
                        log("    ❌ Wrong password detected — stopping retries")
                    if isinstance(log, AutomationLogger): log.outdent()
                    break

            if stop_cb():
                if isinstance(log, AutomationLogger):
                    log.outdent()
                    log.outdent()
                return False

            if isinstance(log, AutomationLogger):
                log.info("Refreshing CAPTCHA for next attempt...")
            else:
                log(f"    🔄 Refreshing CAPTCHA for next attempt...")
            await _refresh_captcha(page)
            await asyncio.sleep(1)
            if isinstance(log, AutomationLogger): log.outdent()

        if isinstance(log, AutomationLogger):
            log.raw(f"[{log._portal_tag}][Login]\nLogin Failed (Attempts Exhausted)")
            log.error(f"Login failed after {max_retries} attempts")
            log.outdent()
        else:
            log(f"  ❌ Login failed after {max_retries} attempts")
        return False
    finally:
        try:
            page.remove_all_listeners("dialog")
        except Exception:
            pass
