import asyncio
import logging
from typing import Callable
from app.automation.automation_logger import AutomationLogger, _ts

logger = logging.getLogger(__name__)

SEL_USERNAME  = "input#userName"
SEL_PASSWORD  = "input#password"
SEL_LOGIN_BTN = "button.ncr_lp-btn"

# reCAPTCHA v2 selectors (from DOM analysis)
_CAPTCHA_IFRAME_SEL = 'iframe[src*="recaptcha/api2/anchor"]'
_CAPTCHA_ANCHOR_SEL = '#recaptcha-anchor'
_CAPTCHA_SOLVED_SEL = '#recaptcha-anchor[aria-checked="true"]'


# ══════════════════════════════════════════════════════════════════════════════
# CAPTCHA AUTO-SOLVE
# ══════════════════════════════════════════════════════════════════════════════

async def _try_auto_solve_captcha(page, log) -> bool:
    """
    Click the reCAPTCHA checkbox and check if Google auto-approves it.
    Returns True if CAPTCHA is solved (aria-checked="true" detected).
    Returns False if an image challenge appears or any error occurs.
    """
    try:
        # Wait for reCAPTCHA iframe to load
        await page.wait_for_selector(_CAPTCHA_IFRAME_SEL, state="attached", timeout=5000)

        captcha_frame = page.frame_locator(_CAPTCHA_IFRAME_SEL)
        anchor = captcha_frame.locator(_CAPTCHA_ANCHOR_SEL)
        await anchor.wait_for(state="visible", timeout=4000)
        await anchor.click()

        if isinstance(log, AutomationLogger):
            log.info("reCAPTCHA checkbox clicked — waiting for Google evaluation (4s)...")
        else:
            log(f"[{_ts()}]   ℹ️ reCAPTCHA clicked — evaluating...")

        # Poll up to 4s for aria-checked="true"
        for _ in range(8):
            await asyncio.sleep(0.5)
            try:
                if await captcha_frame.locator(_CAPTCHA_SOLVED_SEL).count() > 0:
                    if isinstance(log, AutomationLogger):
                        log.success("reCAPTCHA auto-solved ✅")
                    else:
                        log(f"[{_ts()}]   ✅ reCAPTCHA auto-solved.")
                    return True
            except Exception:
                pass

        if isinstance(log, AutomationLogger):
            log.warning("reCAPTCHA image challenge appeared — manual solve required.")
        else:
            log(f"[{_ts()}]   ⚠️ reCAPTCHA image challenge — manual solve required.")
        return False

    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.warning(f"reCAPTCHA auto-click error ({str(exc)[:80]}) — manual solve required.")
        else:
            log(f"[{_ts()}]   ⚠️ reCAPTCHA auto-click error — manual solve required.")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN BUTTON CLICK (after CAPTCHA solved)
# ══════════════════════════════════════════════════════════════════════════════

async def _wait_for_login_btn_enabled_and_click(page, log) -> bool:
    """
    After CAPTCHA is auto-solved, Angular removes 'disabled' from the Login
    button. Poll up to 3s for it to become enabled, then click it.
    """
    try:
        login_btn = page.locator(SEL_LOGIN_BTN)
        await login_btn.wait_for(state="visible", timeout=3000)

        # Poll up to 3s for Angular to enable the button
        for _ in range(6):
            if not await login_btn.is_disabled():
                await login_btn.click()
                if isinstance(log, AutomationLogger):
                    log.info("Login button clicked automatically.")
                else:
                    log(f"[{_ts()}]   ℹ️ Login button clicked automatically.")
                return True
            await asyncio.sleep(0.5)

        if isinstance(log, AutomationLogger):
            log.warning("Login button still disabled after CAPTCHA solve — please click manually.")
        else:
            log(f"[{_ts()}]   ⚠️ Login button still disabled — please click manually.")
        return False

    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.warning(f"Login button click error: {str(exc)[:80]}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# URL CHANGE DETECTION (login success)
# ══════════════════════════════════════════════════════════════════════════════

async def _wait_for_url_change(page, log, stop_cb: Callable[[], bool],
                                timeout_seconds: int = 30) -> bool:
    """
    Poll for URL to move away from IntermediaryLogin.html.
    Works for both auto-login (short timeout) and manual login (30s timeout).
    """
    poll_interval = 1.0
    iterations = int(timeout_seconds / poll_interval)

    for _ in range(iterations):
        if stop_cb(): return False
        try:
            if "IntermediaryLogin.html" not in page.url:
                if isinstance(log, AutomationLogger):
                    log.success("Login detected (URL changed).")
                else:
                    log("✅ Login detected (URL changed).")
                return True
        except Exception:
            pass
        await asyncio.sleep(poll_interval)

    return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN LOGIN FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

async def do_login(
    page,
    settings: dict,
    log=print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    """
    Full login flow:

    AUTO path (CAPTCHA solved by bot):
      Fill credentials → click reCAPTCHA checkbox → wait for Google approval
      → wait for Login button to become enabled → click Login → detect URL change

    MANUAL fallback (image challenge or auto-click failed):
      Fill credentials → wait 30s for user to solve CAPTCHA + click Login
      → detect URL change

    Returns True on successful login, False otherwise.
    """
    portal_url = settings["portal_url"]
    username   = settings["username"]
    password   = settings["password"]

    if isinstance(log, AutomationLogger):
        log.info("Opening New India login page...")
        log.indent()
    else:
        log("🌐 Opening New India login page...")

    # ── 1. Open Login Page ────────────────────────────────────────────────────
    try:
        await page.goto(portal_url, wait_until="domcontentloaded", timeout=30000)
        await page.locator(SEL_USERNAME).wait_for(state="visible", timeout=12000)
        if isinstance(log, AutomationLogger):
            log.success("Login page loaded.")
        else:
            log("✅ Login page loaded successfully")
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Page load failure: {str(exc)[:100]}")
            log.outdent()
        else:
            log(f"❌ Login page did not load: {exc}")
        return False

    if stop_cb(): return False

    # ── 2. Auto-fill Username & Password ─────────────────────────────────────
    if isinstance(log, AutomationLogger):
        log.info("Filling credentials...")
    else:
        log("✍️  Filling username/password...")

    try:
        await page.locator(SEL_USERNAME).fill("")
        await asyncio.sleep(0.3)
        await page.locator(SEL_USERNAME).fill(username)
        await asyncio.sleep(0.4)

        await page.locator(SEL_PASSWORD).fill("")
        await asyncio.sleep(0.25)
        await page.locator(SEL_PASSWORD).fill(password)
        await asyncio.sleep(0.4)

        if isinstance(log, AutomationLogger):
            log.success("Credentials populated.")
        else:
            log("✅ Credentials populated.")
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Credential fill failure: {str(exc)[:100]}")
            log.outdent()
        else:
            log(f"❌ Error filling credentials: {exc}")
        return False

    if stop_cb(): return False

    # ── 3. Wait for Manual Login ──────────────────────────────────────────────
    if isinstance(log, AutomationLogger):
        log.wait("manual CAPTCHA + login (up to 30s)...")
    else:
        log("⏳ Waiting for manual CAPTCHA + login (up to 30s)...")

    success = await _wait_for_url_change(page, log, stop_cb, timeout_seconds=45)

    if success:
        if isinstance(log, AutomationLogger):
            log.wait("session stabilization (3s)")
        else:
            log("⏳ Waiting 3s for post-login scripts...")
        await asyncio.sleep(3)

    if isinstance(log, AutomationLogger):
        log.outdent()

    return success
