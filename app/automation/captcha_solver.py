"""
captcha_solver.py
Solves the canvas-based CAPTCHA on the UIIC and other insurance portals.

Updated:
- Direct in-memory OCR via RapidOCR (zero disk I/O, ~20ms latency)
- No temporary file creation
- Always returns ONLY the exact OCR result
- Cleaner, faster, deterministic behavior
"""

import logging
import traceback
from typing import Optional

logger = logging.getLogger(__name__)

# ── RapidOCR shared engine in-memory solver ──────────────────────────────────
from app.automation.ocr_engine import solve_captcha_bytes


# ── PUBLIC API ─────────────────────────────────────────────────────────────

def solve_captcha_from_bytes(img_bytes: bytes) -> Optional[str]:
    """
    Returns ONLY the exact OCR result directly from in-memory image bytes.
    No disk writes, no fallback guesswork, no case modification.
    """
    try:
        result = solve_captcha_bytes(img_bytes)

        if not result:
            logger.error("CAPTCHA solve failed: empty result")
            return None

        return result

    except Exception as exc:
        logger.error(f"CAPTCHA solve FAILED: {exc}")
        logger.error(traceback.format_exc())
        return None

