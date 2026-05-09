"""
login_module.py
Phase 1 implementation of New India Assurance (NIA) portal login.

This module only handles:
1. Opening the login page
2. Auto-filling username and password
3. Waiting for manual CAPTCHA solving and manual login button click

It does NOT attempt to solve the CAPTCHA or click the login button automatically.
"""

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

SEL_USERNAME = "input#userName"
SEL_PASSWORD = "input#password"
SEL_LOGIN_BTN = "button.ncr_lp-btn"


async def _wait_for_manual_login(page, log_cb: Callable[[str], None], stop_cb: Callable[[], bool], timeout_seconds: int = 30) -> bool:
    """
    Waits for the user to manually solve the CAPTCHA and log in.
    Success is detected when the login URL changes.
    """
    log_cb(f"  ⏳ Waiting for user to solve CAPTCHA and login manually (up to {timeout_seconds}s)...")
    
    poll_interval = 3.0
    iterations = int(timeout_seconds / poll_interval)

    for _ in range(iterations):
        if stop_cb():
            return False

        try:
            # If the URL changes away from IntermediaryLogin.html, login likely succeeded
            current_url = page.url
            if "IntermediaryLogin.html" not in current_url:
                log_cb("  ✅ Login detected successfully (URL changed).")
                return True
        except Exception:
            # If we can't check the page, it might be navigating or closed
            pass

        await asyncio.sleep(poll_interval)

    log_cb(f"  ❌ Login wait timed out after {timeout_seconds} seconds. URL never changed.")
    return False


async def do_login(
    page,
    portal_url: str,
    username: str,
    password: str,
    max_retries: int = 5,  # Ignored for manual CAPTCHA, kept for signature compatibility
    log_cb: Callable[[str], None] = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    """
    Navigate to the New India portal, auto-fill credentials, and wait for manual login.
    Returns True on successful login detection, False otherwise.
    """
    # 1. Open Login Page
    log_cb("  🌐 Opening New India login page...")
    try:
        await page.goto(portal_url, wait_until="domcontentloaded", timeout=30000)
        await page.locator(SEL_USERNAME).wait_for(state="visible", timeout=12000)
        log_cb("  ✅ Login page loaded successfully")
    except Exception as exc:
        log_cb(f"  ❌ Login page did not load: {exc}")
        return False

    if stop_cb():
        return False

    # 2. Auto-fill Username & Password
    log_cb("  ✍️  Filling username/password...")
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
    except Exception as exc:
        log_cb(f"  ❌ Error filling credentials: {exc}")
        return False

    if stop_cb():
        return False

    # 3. Wait for Manual Login
    success = await _wait_for_manual_login(page, log_cb, stop_cb, timeout_seconds=30)
    
    # Wait an extra 3 seconds after successful login to let the session stabilize
    if success:
        log_cb("  ⏳ Waiting 3 seconds for post-login scripts to finish...")
        await asyncio.sleep(3)
        
    return success
