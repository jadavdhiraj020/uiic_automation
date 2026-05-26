"""
ocr_engine.py
Shared singleton engine for PaddleOCR, used for both CAPTCHA solving and document/cheque OCR.
Loads models in a thread-safe manner, supports eager background warmup.
"""

import os
import sys
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Shared globals
_ocr = None
_init_error = None
_ocr_lock = threading.Lock()


def get_shared_ocr():
    """
    Returns the shared PaddleOCR instance.
    Thread-safe, lazy-initialized singleton.
    Uses: use_angle_cls=True, lang='en', show_log=False
    """
    global _ocr, _init_error

    if _init_error is not None:
        raise RuntimeError(f"PaddleOCR previously failed initialization: {_init_error}")

    if _ocr is not None:
        return _ocr

    with _ocr_lock:
        if _ocr is None:
            try:
                logger.info("[OCR] Initializing shared PaddleOCR singleton...")
                start_time = time.perf_counter()

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
                        logger.info(f"[OCR] Paddle DLL path registered: {paddle_libs}")

                from paddleocr import PaddleOCR

                kwargs = dict(use_angle_cls=True, lang='en', show_log=False)

                # Resolve model directories — prefer bundled (EXE), then local cache
                if getattr(sys, "frozen", False):
                    model_root = os.path.join(sys._MEIPASS, ".paddleocr", "whl")
                else:
                    # Running from source: use models already cached in user home
                    from pathlib import Path
                    model_root = str(Path.home() / ".paddleocr" / "whl")

                det_dir = os.path.join(model_root, "det", "en", "en_PP-OCRv3_det_infer")
                rec_dir = os.path.join(model_root, "rec", "en", "en_PP-OCRv4_rec_infer")
                cls_dir = os.path.join(model_root, "cls", "ch_ppocr_mobile_v2.0_cls_infer")

                _missing = [n for n, d in [("det", det_dir), ("rec", rec_dir), ("cls", cls_dir)] if not os.path.isdir(d)]
                if _missing:
                    msg = (
                        f"PaddleOCR models missing: {', '.join(_missing)}. "
                        f"Expected in: {model_root}. "
                        "Re-run the build with models cached in build_assets/paddleocr "
                        "or pre-populate ~/.paddleocr/whl/ before first run."
                    )
                    logger.error(f"[OCR] {msg}")
                    raise RuntimeError(msg)

                if os.path.isdir(det_dir):
                    kwargs["det_model_dir"] = det_dir
                if os.path.isdir(rec_dir):
                    kwargs["rec_model_dir"] = rec_dir
                if os.path.isdir(cls_dir):
                    kwargs["cls_model_dir"] = cls_dir

                kwargs["download"] = False  # Never download — use bundled/cached models only
                _ocr = PaddleOCR(**kwargs)
                elapsed = time.perf_counter() - start_time
                logger.info(f"[OCR] Shared PaddleOCR singleton initialized successfully in {elapsed:.2f} seconds.")

            except Exception as exc:
                import traceback
                _init_error = f"{type(exc).__name__}: {exc}"
                logger.error(f"[OCR] Shared PaddleOCR singleton init FAILED: {exc}")
                logger.error(traceback.format_exc())
                raise

    return _ocr


def ensure_ocr_ready():
    """
    Forces the initialization of PaddleOCR.
    Safe to call; handles and catches errors internally without blocking app flow.
    """
    try:
        get_shared_ocr()
        return True
    except Exception as exc:
        logger.error(f"[OCR] Eager background warming failed: {exc}")
        return False


def warmup_ocr_background():
    """
    Call once at app startup. Spawns a daemon thread to pre-load models in the background.
    """
    logger.info("[OCR] Starting background daemon thread to pre-load PaddleOCR models...")
    thread = threading.Thread(target=ensure_ocr_ready, name="PaddleOCR-Warmup", daemon=True)
    thread.start()
