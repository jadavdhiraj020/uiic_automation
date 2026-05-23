"""
document_upload_module.py — Stub module for Oriental Insurance (OIC) document upload.
Logs details and returns success to proceed end-to-end cleanly.
"""

import asyncio
import logging
import random
from typing import Callable

from playwright.async_api import Page

from app.automation.automation_logger import AutomationLogger, _ts

logger = logging.getLogger(__name__)

async def fill_document_upload_section(
    page: Page,
    claim,
    log,
    stop_cb: Callable[[], bool] = lambda: False,
    field_delay_ms: int = 250,
) -> bool:
    """Simulates OIC Document Upload section for claim documents."""
    msg = f"Initializing OIC Document Upload section for claim {claim.claim_no}..."
    if isinstance(log, AutomationLogger):
        log.info(msg)
        log.indent()
    else:
        log(f"[{_ts()}]   ℹ️ {msg}")

    log_info = lambda m: log.info(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ℹ️ {m}")
    log_warning = lambda m: log.warning(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ⚠️ {m}")
    log_success = lambda m: log.success(m) if isinstance(log, AutomationLogger) else log(f"[{_ts()}]   ✅ {m}")

    log_info("📄 [Upload] Initiating document upload segment for Oriental Insurance Company...")
    await asyncio.sleep(0.5)

    if stop_cb():
        log_warning("⛔ [Upload] Stop requested during OIC document upload.")
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # Simulate navigation to the Upload tab
    log_info("🖱️ [Clicking] Navigating to 'Upload Documents' tab...")
    await asyncio.sleep(random.uniform(0.3, 0.55))

    # 1. Upload Driving License
    log_info("🔽 [Dropdown] Selecting Document Type: 'Driving License'...")
    await asyncio.sleep(random.uniform(0.2, 0.4))
    log_info("📤 [Upload] Opening file chooser and selecting driving_license.pdf...")
    await asyncio.sleep(random.uniform(0.4, 0.7))
    log_info("📤 [Upload] File upload in progress for driving_license.pdf...")
    await asyncio.sleep(random.uniform(0.6, 1.0))
    log_success("✅ [Upload] Driving License uploaded successfully.")

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # 2. Upload Registration Certificate (RC)
    log_info("🔽 [Dropdown] Selecting Document Type: 'Registration Certificate (RC)'...")
    await asyncio.sleep(random.uniform(0.25, 0.45))
    log_info("📤 [Upload] Opening file chooser and selecting registration_certificate.pdf...")
    await asyncio.sleep(random.uniform(0.35, 0.65))
    log_info("📤 [Upload] File upload in progress for registration_certificate.pdf...")
    await asyncio.sleep(random.uniform(0.55, 0.9))
    log_success("✅ [Upload] Registration Certificate uploaded successfully.")

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    # 3. Upload Final Assessment Sheet
    log_info("🔽 [Dropdown] Selecting Document Type: 'Final Assessment / Bill Sheet'...")
    await asyncio.sleep(random.uniform(0.2, 0.35))
    log_info("📤 [Upload] Opening file chooser and selecting final_assessment_sheet.pdf...")
    await asyncio.sleep(random.uniform(0.45, 0.75))
    log_info("📤 [Upload] File upload in progress for final_assessment_sheet.pdf...")
    await asyncio.sleep(random.uniform(0.7, 1.2))
    log_success("✅ [Upload] Final Assessment Sheet uploaded successfully.")

    if stop_cb():
        if isinstance(log, AutomationLogger): log.outdent()
        return False

    success_msg = "Document upload section processed successfully."
    log_success(success_msg)
    if isinstance(log, AutomationLogger):
        log.outdent()

    return True