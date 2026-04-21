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
import traceback
from typing import List, Optional

import sys

logger = logging.getLogger(__name__)

# ── PaddleOCR lazy singleton ─────────────────────────────────────────────────
_ocr = None
_init_error = None  # Store init error so we don't retry forever


def _get_ocr():
    """Return the PaddleOCR singleton, creating it on first call.

    In frozen exe mode: registers paddle DLL paths so import works,
    then lets PaddleOCR handle models normally (downloads to ~/.paddleocr
    on first run, cached for all subsequent runs).
    """
    global _ocr, _init_error
    if _init_error is not None:
        raise RuntimeError(f"PaddleOCR previously failed: {_init_error}")

    if _ocr is None:
        try:
            logger.info("Initializing PaddleOCR...")

            # ── Frozen EXE: register paddle DLL paths ────────────────────
            if getattr(sys, "frozen", False):
                base = sys._MEIPASS
                paddle_libs = os.path.join(base, 'paddle', 'libs')
                if os.path.isdir(paddle_libs):
                    os.environ['PATH'] = paddle_libs + os.pathsep + os.environ.get('PATH', '')
                    try:
                        os.add_dll_directory(paddle_libs)
                    except (OSError, AttributeError):
                        pass
                    logger.info(f"Paddle DLL path registered: {paddle_libs}")
                    # Also register the _internal dir itself (some DLLs land there)
                    try:
                        os.add_dll_directory(base)
                    except (OSError, AttributeError):
                        pass
                else:
                    logger.warning(f"Paddle libs dir NOT found: {paddle_libs}")

            from paddleocr import PaddleOCR

            kwargs = dict(use_angle_cls=False, lang='en', show_log=False)

            # If bundled models exist, use them (avoids download)
            if getattr(sys, "frozen", False):
                model_root = os.path.join(sys._MEIPASS, ".paddleocr", "whl")
                det_dir = os.path.join(model_root, "det", "en", "en_PP-OCRv3_det_infer")
                rec_dir = os.path.join(model_root, "rec", "en", "en_PP-OCRv4_rec_infer")
                cls_dir = os.path.join(model_root, "cls", "ch_ppocr_mobile_v2.0_cls_infer")

                if os.path.isdir(det_dir):
                    kwargs["det_model_dir"] = det_dir
                if os.path.isdir(rec_dir):
                    kwargs["rec_model_dir"] = rec_dir
                if os.path.isdir(cls_dir):
                    kwargs["cls_model_dir"] = cls_dir

                if os.path.isdir(model_root):
                    logger.info(f"Using bundled OCR models from: {model_root}")
                else:
                    logger.info("No bundled models — PaddleOCR will download on first run.")

            _ocr = PaddleOCR(**kwargs)
            logger.info("PaddleOCR initialized successfully.")
        except Exception as exc:
            _init_error = f"{type(exc).__name__}: {exc}"
            logger.error(f"PaddleOCR initialization FAILED: {exc}")
            logger.error(traceback.format_exc())
            raise
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
        # CRITICAL: Log the full error so it appears in the UI log panel
        logger.error(f"CAPTCHA solve FAILED: {exc}")
        logger.error(traceback.format_exc())
        return []


def solve_captcha_from_bytes(img_bytes: bytes) -> Optional[str]:
    """Return the single best guess, or None on failure."""
    candidates = get_captcha_candidates(img_bytes)
    return candidates[0] if candidates else None

