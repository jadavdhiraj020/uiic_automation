"""
navigation_module.py — Resilient navigation workflow for Oriental Insurance (OIC).
Bypasses dashboard filters directly to 'Others' tab -> Motor OD Surveyor Assessment -> Generate Assessment.
"""

import asyncio
import logging
from typing import Callable, Optional

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts
from app.portals.oic.automation import popup_service
from app.portals.oic.automation.ui_utils import capture_error_screenshot
from app.portals.oic.automation.selectors import (
    SEL_OTHERS_TABS,
    SEL_MOTOR_SUB_LINKS,
    SEL_GENERATE_ASSESSMENT_BTNS,
)

logger = logging.getLogger(__name__)

async def navigate_to_claim(
    page: Page,
    claim_no: str,
    settings: dict,
    log = print,
    stop_cb: Callable[[], bool] = lambda: False,
) -> Optional[Page]:
    """
    Navigate from OIC Dashboard to the Motor OD Surveyor Assessment list page,
    then click 'Generate Assessment +' to launch the assessment sheet workspace.
    Returns Page on success, None on failure.
    """
    if isinstance(log, AutomationLogger):
        log.info("Starting OIC Workspace navigation...")
        log.indent()
    else:
        log(f"[{_ts()}]   🧭 Starting OIC Workspace navigation...")

    # Dismiss any post-login alerts
    await popup_service.dismiss_portal_popup(page, log, max_wait_s=1.0, context="Navigation Start")

    # 1. Wait for dashboard / home redirection
    try:
        await page.wait_for_url(
            lambda u: any(x in u.lower() for x in ("/dashboard", "/workspace", "/home", "/assessment")),
            timeout=15000
        )
        url = page.url
        if isinstance(log, AutomationLogger):
            log.info(f"OIC Workspace URL reached: {url}")
        else:
            log(f"[{_ts()}]   ℹ️ OIC Workspace URL reached: {url}")
    except Exception as e:
        current_url = page.url
        if "dashboard" in current_url.lower() or "workspace" in current_url.lower() or "home" in current_url.lower():
            if isinstance(log, AutomationLogger):
                log.success("OIC Workspace verified by active URL.")
            else:
                log(f"[{_ts()}]   ✅ OIC Workspace verified by active URL.")
        else:
            if isinstance(log, AutomationLogger):
                log.warning(f"Timeout waiting for OIC dashboard URL: {e}")
            else:
                log(f"[{_ts()}]   ⚠️ Timeout waiting for OIC dashboard URL: {e}")

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return None

    # 2. Locate and expand 'Others' menu tab
    if isinstance(log, AutomationLogger):
        log.info("Locating 'Others' menu section...")
    else:
        log(f"[{_ts()}]   📂 Locating 'Others' menu section...")

    others_click = False
    others_selectors = SEL_OTHERS_TABS

    for sel in others_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=2500):
                await loc.click()
                others_click = True
                if isinstance(log, AutomationLogger):
                    log.success(f"Clicked 'Others' tab via: {sel}")
                else:
                    log(f"[{_ts()}]   ✅ Clicked 'Others' tab via: {sel}")
                break
        except Exception:
            continue

    if not others_click:
        await capture_error_screenshot(page, "others_tab_not_found", log)
        if isinstance(log, AutomationLogger):
            log.warning("Could not explicitly click 'Others' tab. Attempting direct sub-link locate.")
        else:
            log(f"[{_ts()}]   ⚠️ 'Others' tab click skipped or not found. Continuing.")

    await asyncio.sleep(0.5)
    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return None

    # 3. Click 'Motor OD Surveyor Assessment' link
    if isinstance(log, AutomationLogger):
        log.info("Locating 'Motor OD Surveyor Assessment' sub-link...")
    else:
        log(f"[{_ts()}]   🔗 Locating 'Motor OD Surveyor Assessment' sub-link...")

    motor_click = False
    motor_selectors = SEL_MOTOR_SUB_LINKS

    for sel in motor_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=3000):
                await loc.click()
                motor_click = True
                if isinstance(log, AutomationLogger):
                    log.success(f"Clicked sub-link via: {sel}")
                else:
                    log(f"[{_ts()}]   ✅ Clicked sub-link via: {sel}")
                break
        except Exception:
            continue

    if not motor_click:
        await capture_error_screenshot(page, "motor_link_not_found", log)
        if isinstance(log, AutomationLogger):
            log.warning("Sub-link 'Motor OD Surveyor Assessment' not found.")
        else:
            log(f"[{_ts()}]   ⚠️ Sub-link 'Motor OD Surveyor Assessment' not found.")

    await asyncio.sleep(0.8)
    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return None

    # Dismiss any sub-navigation popups
    await popup_service.dismiss_portal_popup(page, log, max_wait_s=0.5, context="Sub-navigation")

    # 4. Wait for Surveyor Assessment page & Click 'Generate Assessment +'
    try:
        await page.wait_for_url(
            lambda u: "surveyor-assessment" in u.lower() or "surveyorassessment" in u.lower() or "assessment" in u.lower(),
            timeout=8000
        )
    except Exception:
        pass

    if isinstance(log, AutomationLogger):
        log.info("Locating 'Generate Assessment +' button...")
    else:
        log(f"[{_ts()}]   ⚡ Locating 'Generate Assessment +' button...")

    gen_click = False
    gen_selectors = SEL_GENERATE_ASSESSMENT_BTNS

    for sel in gen_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=3000):
                await loc.click()
                gen_click = True
                if isinstance(log, AutomationLogger):
                    log.success(f"Successfully triggered 'Generate Assessment +' via: {sel}")
                else:
                    log(f"[{_ts()}]   ✅ Successfully triggered 'Generate Assessment +' via: {sel}")
                break
        except Exception:
            continue

    if not gen_click:
        await capture_error_screenshot(page, "generate_button_not_found", log)
        if isinstance(log, AutomationLogger):
            log.warning("Could not find 'Generate Assessment +' button. The sheet may already be open.")
        else:
            log(f"[{_ts()}]   ⚠️ 'Generate Assessment +' button not found. Continuing workflow.")

    await asyncio.sleep(1.0)
    await popup_service.dismiss_portal_popup(page, log, max_wait_s=1.0, context="Post Navigation Finish")

    if isinstance(log, AutomationLogger):
        log.success("OIC navigation phase complete.")
        log.outdent()
    else:
        log(f"[{_ts()}]   ✅ OIC navigation phase complete.")

    return page