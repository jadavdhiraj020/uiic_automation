"""
captcha_solver.py
Solves the canvas-based CAPTCHA on the UIIC portal.

Updated:
- Removed ALL fallback logic (uppercase/lowercase)
- Always returns ONLY the exact OCR result
- Cleaner, faster, deterministic behavior
"""

import re
import os
import logging
import tempfile
import traceback
from typing import Optional
import sys
import threading

logger = logging.getLogger(__name__)

# ── PaddleOCR shared engine singleton ────────────────────────────────────────
from app.automation.ocr_engine import get_shared_ocr as _get_ocr


def _extract_text(img_bytes: bytes) -> str:
    """
    Run OCR and return clean alphanumeric text ONLY.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")

    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(img_bytes)

        ocr_engine = _get_ocr()
        with _ocr_lock:
            result = ocr_engine.ocr(tmp_path, cls=False)

        if not result or result[0] is None:
            logger.warning("PaddleOCR returned no result")
            return ""

        raw = "".join(box[1][0] for box in result[0])
        clean = re.sub(r"[^A-Za-z0-9]", "", raw).strip()

        logger.info(f"OCR RESULT → raw='{raw}' | clean='{clean}'")

        return clean

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── PUBLIC API (SIMPLIFIED) ────────────────────────────────────────────────

def solve_captcha_from_bytes(img_bytes: bytes) -> Optional[str]:
    """
    Returns ONLY the exact OCR result.
    No fallback, no retries, no case modification.
    """
    try:
        result = _extract_text(img_bytes)

        if not result:
            logger.error("CAPTCHA solve failed: empty result")
            return None

        return result

    except Exception as exc:
        logger.error(f"CAPTCHA solve FAILED: {exc}")
        logger.error(traceback.format_exc())
        return None
