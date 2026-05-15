import asyncio
import logging
from typing import Callable
from app.automation.automation_logger import AutomationLogger, _ts

logger = logging.getLogger(__name__)

SEL_USERNAME = "input#userName"
SEL_PASSWORD = "input#password"
SEL_LOGIN_BTN = "button.ncr_lp-btn"


async def _wait_for_manual_login(page, log, stop_cb: Callable[[], bool], timeout_seconds: int = 30) -> bool:
    """
    Waits for the user to manually solve the CAPTCHA and log in.
    Success is detected when the login URL changes.
    """
    if isinstance(log, AutomationLogger):
        log.wait(f"manual CAPTCHA + login (up to {timeout_seconds}s)")
    else:
        log(f"⏳ Waiting for manual CAPTCHA + login (up to {timeout_seconds}s)...")
    
    poll_interval = 3.0
    iterations = int(timeout_seconds / poll_interval)

    for _ in range(iterations):
        if stop_cb(): return False

        try:
            # If the URL changes away from IntermediaryLogin.html, login likely succeeded
            current_url = page.url
            if "IntermediaryLogin.html" not in current_url:
                if isinstance(log, AutomationLogger):
                    log.success("Login detected (URL changed).")
                else:
                    log("✅ Login detected (URL changed).")
                return True
        except Exception:
            pass

        await asyncio.sleep(poll_interval)

    if isinstance(log, AutomationLogger):
        log.error(f"Login timed out ({timeout_seconds}s).")
    else:
        log(f"❌ Login wait timed out after {timeout_seconds}s. URL never changed.")
    return False


async def do_login(
    page,
    settings: dict,
    log = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    """
    Navigate to the New India portal, auto-fill credentials, and wait for manual login.
    Returns True on successful login detection, False otherwise.
    """
    portal_url = settings["portal_url"]
    username = settings["username"]
    password = settings["password"]
    
    if isinstance(log, AutomationLogger):
        log.info("Opening New India login page...")
        log.indent()
    else:
        log("🌐 Opening New India login page...")

    # 1. Open Login Page
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

    # 2. Auto-fill Username & Password
    if isinstance(log, AutomationLogger):
        log.info("Filling credentials...")
    else:
        log("✍️  Filling username/password...")
        
    try:
        # Fill username
        await page.locator(SEL_USERNAME).fill("")
        await asyncio.sleep(0.3)
        await page.locator(SEL_USERNAME).fill(username)
        await asyncio.sleep(0.4)

        # Fill password
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

    # 3. Wait for Manual Login
    success = await _wait_for_manual_login(page, log, stop_cb, timeout_seconds=30)
    
    # Wait an extra 3 seconds after successful login to let the session stabilize
    if success:
        if isinstance(log, AutomationLogger):
            log.wait("session stabilization (3s)")
        else:
            log("⏳ Waiting 3s for post-login scripts to finish...")
        await asyncio.sleep(3)
        
    if isinstance(log, AutomationLogger):
        log.outdent()
        
    return success
