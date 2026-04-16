"""
claim_documents.py
Fills the "Claim Documents" tab:
  - Sets verification Yes/No radios to Yes
  - Sets Payment Option to Cashless
  - Uploads all mapped documents from ClaimData.claim_doc_files
"""

import asyncio
import logging
import os
from typing import Callable

from app.data.data_model import ClaimData

logger = logging.getLogger(__name__)

SEL_TAB_DOCS = "a:has-text('Claim Documents'), .nav-tabs a:has-text('Claim Doc')"
SEL_DOC_TYPE = "select[ng-model*='documentType'], select[ng-model*='docType'], #docType"
SEL_FILE_INPUT = "input[type='file']"
SEL_ADD_ROW = "button.btn-warning, img[src*='add'], button:has-text('+')"
SEL_CASHLESS = "input[type='checkbox'][value*='Cashless'], input[type='checkbox'][ng-model*='cashless']"


async def _set_radio_yes(page, label_text: str, log_cb: Callable):
    strategies = [
        f"tr:has-text('{label_text}') input[value='Y']",
        f"tr:has-text('{label_text}') input[value='Yes']",
        f"tr:has-text('{label_text}') label:has-text('Yes')",
        f"div:has-text('{label_text}') input[value='Y']",
        f"div:has-text('{label_text}') input[value='Yes']",
    ]
    for sel in strategies:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                await el.click()
                await asyncio.sleep(0.2)
                log_cb(f"  Verified Yes: {label_text[:40]}...")
                return
        except Exception:
            continue
    log_cb(f"  Could not set Yes for: {label_text[:40]}...")


async def _select_doc_type(page, doc_type: str, row_index: int):
    dropdowns = page.locator(SEL_DOC_TYPE)
    try:
        await dropdowns.nth(row_index).wait_for(state="visible", timeout=4000)
        await dropdowns.nth(row_index).select_option(label=doc_type)
        await asyncio.sleep(0.3)
        return True
    except Exception:
        try:
            await dropdowns.nth(row_index).select_option(value=doc_type)
            await asyncio.sleep(0.3)
            return True
        except Exception as exc:
            logger.warning("Could not select doc type '%s': %s", doc_type, exc)
            return False


async def fill_claim_documents(
    page,
    claim: ClaimData,
    log_cb: Callable[[str], None] = print,
):
    log_cb("Clicking 'Claim Documents' tab...")
    await page.locator(SEL_TAB_DOCS).first.click()
    await asyncio.sleep(2)

    log_cb("Setting verification radios to Yes...")
    await _set_radio_yes(page, "physically verified", log_cb)
    await _set_radio_yes(page, "natures of damages", log_cb)
    await _set_radio_yes(page, "vehicular documents", log_cb)

    try:
        cashless = page.locator(SEL_CASHLESS).first
        if not await cashless.is_checked(timeout=2000):
            await cashless.click()
        log_cb("  Payment Option: Cashless")
    except Exception:
        try:
            await page.locator("label:has-text('Cashless')").first.click()
            log_cb("  Payment Option: Cashless (label click)")
        except Exception as exc:
            log_cb(f"  Could not set Cashless: {exc}")

    upload_queue = []
    for doc_type, file_path in claim.claim_doc_files.items():
        if not os.path.isfile(file_path):
            log_cb(f"  File not found, skipping: {file_path}")
            continue

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 2.0:
            log_cb(f"  File too large ({file_size_mb:.1f}MB > 2MB), skipping: {os.path.basename(file_path)}")
            continue

        upload_queue.append((doc_type, file_path))

    log_cb(f"Uploading {len(upload_queue)} claim documents...")
    for idx, (doc_type, file_path) in enumerate(upload_queue):
        log_cb(f"  [{idx + 1}] Uploading '{doc_type}': {os.path.basename(file_path)}")

        await _select_doc_type(page, doc_type, idx)

        try:
            file_inputs = page.locator(SEL_FILE_INPUT)
            await file_inputs.nth(idx).wait_for(state="attached", timeout=4000)
            await file_inputs.nth(idx).set_input_files(file_path)
            await asyncio.sleep(1.5)
            log_cb("      Uploaded successfully")
        except Exception as exc:
            log_cb(f"      Upload failed: {exc}")
            continue

        if idx < len(upload_queue) - 1:
            try:
                add_btn = page.locator(SEL_ADD_ROW).last
                await add_btn.click()
                await asyncio.sleep(0.8)
            except Exception:
                pass

    log_cb("Claim Documents tab complete.")
    await asyncio.sleep(0.5)
