"""
tab_utils.py — Shared tab-navigation helper.

Previously each module (interim_report, claim_documents, claim_assessment)
had its own copy of _click_tab — identical code duplicated 3×.

This module provides a single, parameterised click_tab() used by all.
"""
import asyncio
import logging
from typing import Callable

from app.automation.selectors import TABS, TAB_SEL
from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

# How long to wait after clicking a tab for Angular to fully re-render
_TAB_RENDER_WAIT = 1.2   # seconds


async def click_tab(page, tab_key: str, log = print) -> None:
    """
    Click the portal tab identified by tab_key (one of: 'interim', 'documents', 'assessment').
    Falls back to index-based click if text-matching fails.
    Always waits _TAB_RENDER_WAIT seconds for Angular digest cycle to complete.
    """
    tab_cfg = TABS[tab_key]
    search_text = tab_cfg["text"]
    fallback_idx = tab_cfg["index"]
    label = tab_key.replace("_", " ").title()

    if isinstance(log, AutomationLogger):
        log.info(f"Clicking '{label}' tab...")
    else:
        log(f"📑 Clicking '{label}' tab...")
        
    tabs = page.locator(TAB_SEL)
    count = await tabs.count()

    for i in range(count):
        try:
            txt = (await tabs.nth(i).inner_text()).strip().lower()
            if search_text in txt:
                await tabs.nth(i).click()
                await asyncio.sleep(_TAB_RENDER_WAIT)
                await page.bring_to_front()
                await page.evaluate("window.scrollTo(0, 250)")
                if isinstance(log, AutomationLogger):
                    log.success(f"'{label}' tab selected (idx {i})")
                else:
                    log(f"  ✅ '{label}' tab (idx {i})")
                return
        except Exception:
            continue

    # Fallback: click by index
    try:
        await tabs.nth(fallback_idx).click()
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.error(f"Tab click by index failed: {e}")
        else:
            log(f"  ⚠️  Tab click by index failed: {e}")
        return

    await asyncio.sleep(_TAB_RENDER_WAIT)
    await page.bring_to_front()
    await page.evaluate("window.scrollTo(0, 250)")
    
    if isinstance(log, AutomationLogger):
        log.success(f"'{label}' tab selected (fallback idx {fallback_idx})")
    else:
        log(f"  ✅ '{label}' tab (fallback idx {fallback_idx})")
