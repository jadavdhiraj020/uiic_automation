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

logger = logging.getLogger(__name__)

# ── PaddleOCR lazy singleton ────────────────────────────────────────────────
_ocr = None
_init_error = None


def _get_ocr():
    """Initialize PaddleOCR once (singleton)."""
    global _ocr, _init_error

    if _init_error is not None:
        raise RuntimeError(f"PaddleOCR previously failed: {_init_error}")

    if _ocr is None:
        try:
            logger.info("Initializing PaddleOCR...")

            # Handle EXE mode (PyInstaller)
            if getattr(sys, "frozen", False):
                base = sys._MEIPASS
                paddle_libs = os.path.join(base, 'paddle', 'libs')

                if os.path.isdir(paddle_libs):
                    os.environ['PATH'] = paddle_libs + os.pathsep + os.environ.get('PATH', '')

                    try:
                        os.add_dll_directory(paddle_libs)
                    except (OSError, AttributeError):
                        pass

                    try:
                        os.add_dll_directory(base)
                    except (OSError, AttributeError):
                        pass

                    logger.info(f"Paddle DLL path registered: {paddle_libs}")
                else:
                    logger.warning(f"Paddle libs dir NOT found: {paddle_libs}")

            from paddleocr import PaddleOCR

            kwargs = dict(use_angle_cls=False, lang='en', show_log=False)

            # Use bundled models if available
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
                    logger.info("No bundled models — will download on first run.")

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
    Run OCR and return clean alphanumeric text ONLY.
    """
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")

    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(img_bytes)

        result = _get_ocr().ocr(tmp_path, cls=False)

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
