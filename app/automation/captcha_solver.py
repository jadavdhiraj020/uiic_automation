"""
captcha_solver.py
Solves the canvas-based CAPTCHA on the UIIC portal.
Input: raw PNG bytes from Playwright canvas.screenshot().

Engine: PaddleOCR v2 (stable branch, paddlepaddle <3.0.0)
PaddleOCR is highly accurate for mixed-case alphanumeric CAPTCHAs —
it natively detects case, so no manual case-restoration heuristics needed.
"""

import re
import os
import logging
import tempfile
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── PaddleOCR lazy singleton ─────────────────────────────────────────────────
# Loaded on first use (not at import time) to avoid ~3-5s startup delay.
# lang='en': English model
# use_angle_cls=False: CAPTCHA text is never upside-down
# show_log=False: Suppress noisy PaddlePaddle internals
_ocr = None


def _get_ocr():
    """Return the PaddleOCR singleton, creating it on first call."""
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        _ocr = PaddleOCR(use_angle_cls=False, lang='en', show_log=False)
    return _ocr


def _extract_text(img_bytes: bytes) -> str:
    """
    Run PaddleOCR on raw image bytes and return cleaned text.

    PaddleOCR requires a file path, so we write bytes to a temp file,
    run OCR, then clean up.  Only alphanumeric characters survive.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(img_bytes)

        result = _get_ocr().ocr(tmp_path, cls=False)

        if not result or result[0] is None:
            logger.warning("PaddleOCR returned no result")
            return ""

        # Concatenate all detected text boxes (already left-to-right order)
        raw = "".join(box[1][0] for box in result[0])
        clean = re.sub(r"[^A-Za-z0-9]", "", raw).strip()

        logger.info(f"PaddleOCR: raw='{raw}'  clean='{clean}'")
        return clean

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Public API ────────────────────────────────────────────────────────────────

def get_captcha_candidates(img_bytes: bytes) -> List[str]:
    """
    Return up to 3 CAPTCHA candidates in priority order:
      [0]  PaddleOCR result (case-accurate — best guess)
      [1]  ALL UPPERCASE    (fallback if portal is case-insensitive)
      [2]  all lowercase    (last resort)

    Duplicates are removed so the caller never retries the same string.
    Returns [] if OCR produced nothing.
    """
    try:
        base = _extract_text(img_bytes)
        if not base:
            return []

        seen: set = set()
        candidates: List[str] = []
        for variant in (base, base.upper(), base.lower()):
            if variant not in seen:
                seen.add(variant)
                candidates.append(variant)

        logger.info(f"CAPTCHA candidates: {candidates}")
        return candidates

    except Exception as exc:
        logger.error(f"CAPTCHA solve error: {exc}")
        return []


def solve_captcha_from_bytes(img_bytes: bytes) -> Optional[str]:
    """Return the single best guess, or None on failure."""
    candidates = get_captcha_candidates(img_bytes)
    return candidates[0] if candidates else None
