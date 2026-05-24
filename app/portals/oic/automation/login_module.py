"""
login_module.py — Robust login module for Oriental Insurance (OIC) portal.
Handles multi-variant best-of-n captcha solver, popup suppression, and resilient credentials fill.
"""

import asyncio
import base64
import logging
import os
import random
import re
import sys
import time
from typing import Callable, Optional
import cv2
import numpy as np

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts
from app.portals.oic.automation import popup_service
from app.portals.oic.automation.ui_utils import fill_input_with_delay, capture_error_screenshot

logger = logging.getLogger(__name__)

from app.portals.oic.automation.selectors import (
    SEL_USERNAME,
    SEL_PASSWORD,
    SEL_CAPTCHA_IN,
    SEL_CAPTCHA_CVS,
    SEL_LOGIN_BTN,
    SEL_REFRESH_BTN,
    SEL_ERROR_MSG,
    SEL_HEADER_LOGIN_BTN,
    SEL_LOGIN_FORM_CONTAINER,
    SEL_STARTUP_DIALOG_CLOSE,
)

# ── Captcha Utilities ─────────────────────────────────────────────────────────

def _to_grayscale(img) -> np.ndarray:
    """Helper to convert to grayscale, handling potential alpha composite transparent backgrounds."""
    if len(img.shape) == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3]
        rgb = img[:, :, :3]
        white_bg = np.ones_like(rgb, dtype=np.uint8) * 255
        alpha_factor = (alpha / 255.0)[:, :, np.newaxis]
        composited = (rgb * alpha_factor + white_bg * (1.0 - alpha_factor)).astype(np.uint8)
        return cv2.cvtColor(composited, cv2.COLOR_BGR2GRAY)
    if len(img.shape) == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def get_variants(img_bytes: bytes):
    """
    Generate binarization variants of the captcha image for OCR.
    Uses 3 high-value variants (gray + otsu + adaptive) for optimal speed/accuracy.
    """
    try:
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        if img is None:
            return []

        gray = _to_grayscale(img)
        variants = []

        # 1. Raw grayscale — baseline for clean captchas
        variants.append(("gray", gray))

        # 2. Otsu thresholding — best for bimodal intensity captchas
        _, thresh_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(("otsu", thresh_otsu))

        # 3. Adaptive Thresholding — handles uneven lighting/noise
        thresh_adapt = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        variants.append(("adaptive", thresh_adapt))

        # Convert back to bytes
        byte_variants = []
        for name, var_img in variants:
            _, buf = cv2.imencode(".png", var_img)
            byte_variants.append((name, buf.tobytes()))

        return byte_variants
    except Exception as e:
        logger.warning(f"Error generating binarization variants: {e}")
        return []


def score_candidate(cand: str) -> float:
    """Helper to score a single OCR candidate string."""
    text = re.sub(r"[^A-Za-z0-9]", "", cand).strip()
    if not text:
        return 0.0
    
    score = 1.0 # base score
    if len(text) == 5:
        score += 2.0 # Prioritize 5-character string lengths with weight 2.0
    elif len(text) in (4, 6):
        score += 0.5
    elif len(text) < 3 or len(text) > 8:
        score -= 0.5
        
    has_alpha = any(c.isalpha() for c in text)
    has_digit = any(c.isdigit() for c in text)
    if has_alpha and has_digit:
        score += 0.5
        
    return score


def _solve_captcha_best_of_n(img_bytes: bytes, log) -> Optional[str]:
    """
    Solves CAPTCHA using multiple variants, scores candidate OCRs, and
    prioritizes exactly 5-character string lengths with weight length_score = 2.0.
    """
    from app.automation.captcha_solver import solve_captcha_from_bytes

    variants = get_variants(img_bytes)
    if not variants:
        return solve_captcha_from_bytes(img_bytes)

    candidates = {}
    for name, var_bytes in variants:
        try:
            cand_text = solve_captcha_from_bytes(var_bytes)
            if cand_text:
                cand_text = re.sub(r"[^A-Za-z0-9]", "", cand_text).strip()
                if cand_text:
                    candidates[cand_text] = candidates.get(cand_text, 0) + 1
        except Exception as e:
            logger.warning(f"OCR failed for variant '{name}': {e}")

    if not candidates:
        raw_res = solve_captcha_from_bytes(img_bytes)
        if raw_res:
            return re.sub(r"[^A-Za-z0-9]", "", raw_res).strip()
        return None

    # Score candidates
    scored_candidates = []
    for cand, count in candidates.items():
        base_score = float(count)
        # Apply score_candidate logic
        c_score = score_candidate(cand)
        # Maintain direct length check weight 2.0 logic
        length_score = 2.0 if len(cand) == 5 else 0.0
        
        total_score = base_score + length_score + (c_score - 1.0)
        scored_candidates.append((cand, total_score))

    # Sort descending by score
    scored_candidates.sort(key=lambda x: x[1], reverse=True)

    msg = f"CAPTCHA candidates scored: {scored_candidates}"
    if isinstance(log, AutomationLogger):
        log.info(msg)
    else:
        log(f"[{_ts()}]   ℹ️ {msg}")

    return scored_candidates[0][0]


async def _get_captcha_bytes(page) -> bytes:
    """Reads CAPTCHA from canvas using toDataURL or screenshot fallback."""
    await asyncio.sleep(0.5)
    try:
        # Evaluate toDataURL on canvas
        base64_data = await page.evaluate("""() => {
            const canvas = document.querySelector('canvas#captcha, canvas');
            return canvas ? canvas.toDataURL('image/png') : null;
        }""")
        if base64_data and "," in base64_data:
            return base64.b64decode(base64_data.split(",")[1])
    except Exception as e:
        logger.warning(f"toDataURL failed, falling back to screenshot: {e}")

    # Fallback: screenshot of locator
    for sel in ["canvas#captcha", "canvas", "img#captchaImg"]:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2000):
                return await loc.screenshot()
        except Exception:
            continue
    raise RuntimeError("Could not retrieve CAPTCHA image element.")


async def _refresh_captcha(page):
    """Trigger CAPTCHA refresh."""
    for sel in SEL_REFRESH_BTN.split(", "):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await asyncio.sleep(0.5)
                return True
        except Exception:
            continue
    return False


async def _try_fill_and_submit(page, username, password, captcha_text, log):
    """Populates fields and clicks submit."""
    # Username
    await fill_input_with_delay(page, SEL_USERNAME, username, "Username", log, delay_ms=150)
    # Password
    await fill_input_with_delay(page, SEL_PASSWORD, password, "Password", log, delay_ms=150)
    # Captcha
    await fill_input_with_delay(page, SEL_CAPTCHA_IN, captcha_text, "Captcha", log, delay_ms=150)

    # Click Submit
    for sel in SEL_LOGIN_BTN.split(", "):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                if isinstance(log, AutomationLogger):
                    log.info("Clicked login submit button.")
                else:
                    log(f"[{_ts()}]   Clicked login submit button.")
                return True
        except Exception:
            continue
    return False


async def _is_logged_in(page) -> bool:
    """Check if we have bypassed the login screen and reached the dashboard."""
    url = page.url.lower()
    if "/dashboard" in url or "/workspace" in url or "/home" in url:
        return True
    
    # Check if login form is gone
    try:
        user_visible = await page.locator(SEL_USERNAME).first.is_visible(timeout=500)
        return not user_visible
    except Exception:
        return True


async def _run_manual_login_fallback(page: Page, timeout_s: float, log, stop_cb: Callable[[], bool]) -> bool:
    """
    Waits for the user to solve the CAPTCHA and complete login manually.
    Returns True if login is detected, False otherwise.
    """
    msg = f"Entering manual login fallback. Please solve the CAPTCHA and click Login manually in the browser tab within {timeout_s} seconds..."
    if isinstance(log, AutomationLogger):
        log.warning(msg)
    else:
        log(f"[{_ts()}]   ⚠️ {msg}")
        
    await capture_error_screenshot(page, "manual_login_wait_start", log)
    
    elapsed = 0.0
    poll_interval = 1.0
    while elapsed < timeout_s:
        if stop_cb():
            return False
            
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        
        # Check if URL changed or username form is gone
        if await _is_logged_in(page):
            msg = "Manual login detected successfully!"
            if isinstance(log, AutomationLogger):
                log.success(msg)
            else:
                log(f"[{_ts()}]   ✅ {msg}")
            return True
            
    await capture_error_screenshot(page, "manual_login_timeout", log)
    err_msg = "Manual login fallback timed out."
    if isinstance(log, AutomationLogger):
        log.error(err_msg)
    else:
        log(f"[{_ts()}]   ❌ {err_msg}")
    return False


# ── PUBLIC API ────────────────────────────────────────────────────────────────

async def do_login(
    page: Page,
    settings: dict,
    log = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> bool:
    """
    Perform authentication workflow for OIC.
    Returns True on success, False on failure.
    """
    portal_url = settings["portal_url"]
    username = settings["username"]
    password = settings["password"]
    max_retries = settings.get("captcha_max_retries", 5)

    if isinstance(log, AutomationLogger):
        log.info("Navigating to OIC Portal...")
        log.indent()
    else:
        log(f"[{_ts()}]   🌐 Navigating to OIC Portal...")

    # Go to login page
    await page.goto(portal_url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(1.5)

    # Try to close OIC PrimeNG startup dialog banner if visible
    try:
        close_btn = page.locator(SEL_STARTUP_DIALOG_CLOSE).first
        if await close_btn.is_visible(timeout=3000):
            if isinstance(log, AutomationLogger):
                log.info("PrimeNG startup modal detected. Dismissing...")
            else:
                log(f"[{_ts()}]   ℹ️ PrimeNG startup modal detected. Dismissing...")
            await close_btn.click()
            await asyncio.sleep(0.5)
    except Exception:
        pass

    # Clean overlays / SweetAlerts / NgDialogs on startup (short wait — ad was already closed above)
    await popup_service.dismiss_portal_popup(page, log, max_wait_s=1.0, context="OIC Startup Dismissal")

    # Click the header 'Login' button to open the login dropdown/modal form
    try:
        login_btn = page.locator(SEL_HEADER_LOGIN_BTN).first
        await login_btn.wait_for(state="visible", timeout=5000)
        if isinstance(log, AutomationLogger):
            log.info("Clicking header Login button to open login form...")
        else:
            log(f"[{_ts()}]   ℹ️ Clicking header Login button to open login form...")
        await login_btn.click()
        await asyncio.sleep(1.0)
    except Exception as click_exc:
        if isinstance(log, AutomationLogger):
            log.warning(f"Could not click header Login button (might already be open): {click_exc}")
        else:
            log(f"[{_ts()}]   ⚠️ Could not click header Login button: {click_exc}")

    # Wait for the login form container (.login-formno) to appear first,
    # THEN wait for the username input inside it.
    try:
        await page.wait_for_selector(SEL_LOGIN_FORM_CONTAINER, state="visible", timeout=5000)
        if isinstance(log, AutomationLogger):
            log.info("Login form container (.login-formno) detected.")
        else:
            log(f"[{_ts()}]   ℹ️ Login form container detected.")
    except Exception:
        if isinstance(log, AutomationLogger):
            log.warning("Login form container not detected, checking for inputs directly...")
        else:
            log(f"[{_ts()}]   ⚠️ Login form container not detected, checking for inputs directly...")

    try:
        await page.wait_for_selector(SEL_USERNAME, state="visible", timeout=10000)
        if isinstance(log, AutomationLogger):
            log.success("OIC login page loaded successfully.")
        else:
            log(f"[{_ts()}]   ✅ OIC login page loaded successfully.")
    except Exception as exc:
        await capture_error_screenshot(page, "login_inputs_missing", log)
        if isinstance(log, AutomationLogger):
            log.error(f"Failed to find login inputs on page: {exc}")
            log.outdent()
        else:
            log(f"[{_ts()}]   ❌ Failed to find login inputs on page: {exc}")
        return False

    for attempt in range(1, max_retries + 1):
        if stop_cb():
            if isinstance(log, AutomationLogger): log.outdent()
            return False

        if isinstance(log, AutomationLogger):
            log.info(f"OIC Login Attempt {attempt}/{max_retries}")
            log.indent()
        else:
            log(f"\n[{_ts()}]   🔄 Attempt {attempt}/{max_retries}")

        # NOTE: Intentionally NOT running popup_service here.
        # The login form uses PrimeNG components that get falsely detected as popups.

        try:
            img_bytes = await _get_captcha_bytes(page)
            captcha_text = _solve_captcha_best_of_n(img_bytes, log)
        except Exception as exc:
            if isinstance(log, AutomationLogger):
                log.error(f"Error reading CAPTCHA: {exc}")
            else:
                log(f"[{_ts()}]   ⚠️ Error reading CAPTCHA: {exc}")
            await _refresh_captcha(page)
            if isinstance(log, AutomationLogger): log.outdent()
            continue

        if not captcha_text or len(captcha_text) < 3:
            if isinstance(log, AutomationLogger):
                log.warning("CAPTCHA text is missing or too short, refreshing...")
            else:
                log(f"[{_ts()}]   ⚠️ CAPTCHA text is missing or too short, refreshing...")
            await _refresh_captcha(page)
            if isinstance(log, AutomationLogger): log.outdent()
            continue

        if isinstance(log, AutomationLogger):
            log.info(f"Solved CAPTCHA text: '{captcha_text}'")
        else:
            log(f"[{_ts()}]   🔑 Solved CAPTCHA text: '{captcha_text}'")

        if stop_cb():
            if isinstance(log, AutomationLogger):
                log.outdent()
                log.outdent()
            return False

        # Attempt to fill form and submit
        success_fill = await _try_fill_and_submit(page, username, password, captcha_text, log)
        if not success_fill:
            if isinstance(log, AutomationLogger):
                log.error("Failed to populate credentials or click login button.")
            else:
                log(f"[{_ts()}]   ❌ Failed to populate credentials or click login button.")
            await _refresh_captcha(page)
            if isinstance(log, AutomationLogger): log.outdent()
            continue

        # Wait for login state change or error alerts
        await asyncio.sleep(1.5)
        
        # Check if login outcome triggers alert (incorrect password/captcha)
        popup_tag = await popup_service.dismiss_portal_popup(
            page, log, max_wait_s=2.0, classify=True, context="Post-login check"
        )
        
        if popup_tag == "credential_error":
            if isinstance(log, AutomationLogger):
                log.error("Wrong credentials detected. Retrying CAPTCHA/Login.")
            else:
                log(f"[{_ts()}]   ❌ Wrong credentials / wrong CAPTCHA detected.")
            await _refresh_captcha(page)
            if isinstance(log, AutomationLogger): log.outdent()
            continue

        # Check if form is gone or URL changed to dashboard
        if await _is_logged_in(page):
            if isinstance(log, AutomationLogger):
                log.success("Authenticated and redirected successfully!")
                log.outdent()
                log.outdent()
            else:
                log(f"[{_ts()}]   ✅ Authenticated and redirected successfully!")
            return True

        # Check error text directly on page
        try:
            err_el = page.locator(SEL_ERROR_MSG).first
            if await err_el.is_visible(timeout=500):
                err_txt = (await err_el.inner_text()).strip()
                if isinstance(log, AutomationLogger):
                    log.error(f"Login error text: {err_txt}")
                else:
                    log(f"[{_ts()}]   ❌ Login error text: {err_txt}")
        except Exception:
            pass

        await _refresh_captcha(page)
        await asyncio.sleep(0.5)
        if isinstance(log, AutomationLogger): log.outdent()

    # CAPTCHA retries exhausted. Capture final attempt screenshot.
    await capture_error_screenshot(page, "login_attempts_exhausted", log)

    # Fall back to manual login if configured/enabled.
    manual_timeout = settings.get("manual_login_timeout_s", 45)
    if manual_timeout > 0:
        success_manual = await _run_manual_login_fallback(page, manual_timeout, log, stop_cb)
        if success_manual:
            if isinstance(log, AutomationLogger):
                log.outdent()
            return True

    if isinstance(log, AutomationLogger):
        log.error(f"Login failed after {max_retries} attempts.")
        log.outdent()
    else:
        log(f"[{_ts()}]   ❌ Login failed after {max_retries} attempts.")
    return False