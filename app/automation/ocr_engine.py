"""
ocr_engine.py
Shared singleton engine for PaddleOCR, used for both CAPTCHA solving and document/cheque OCR.
Loads models in a thread-safe manner, supports eager background warmup.
"""

import logging
import os
import sys
import threading
import time

logger = logging.getLogger(__name__)

# Shared globals
_ocr = None
_init_error = None
_ocr_lock = threading.Lock()
_ocr_run_lock = threading.Lock()


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

                # ── Resolve model directories ─────────────────────────────────────
                # Authoritative source: PADDLEOCR_HOME env var set by runtime_hook.py.
                # In the frozen EXE, runtime_hook.py sets it to _MEIPASS/.paddleocr.
                # In source runs, fall back to ~/.paddleocr (standard PaddleOCR default).
                # This single code path covers both environments without duplication
                # and correctly handles the case where the user overrides PADDLEOCR_HOME.
                is_frozen = getattr(sys, "frozen", False)
                if is_frozen:
                    paddleocr_home = os.environ.get(
                        "PADDLEOCR_HOME",
                        os.path.join(sys._MEIPASS, ".paddleocr"),
                    )
                else:
                    from pathlib import Path
                    paddleocr_home = os.environ.get("PADDLEOCR_HOME")
                    if not paddleocr_home:
                        repo_root = Path(__file__).resolve().parents[2]
                        build_assets_ocr = repo_root / "build_assets" / "paddleocr"
                        user_home_ocr = Path.home() / ".paddleocr"
                        if (user_home_ocr / "whl" / "det").is_dir():
                            paddleocr_home = str(user_home_ocr)
                        elif (build_assets_ocr / "whl" / "det").is_dir():
                            paddleocr_home = str(build_assets_ocr)
                        else:
                            paddleocr_home = str(user_home_ocr)

                model_root = os.path.join(paddleocr_home, "whl")
                logger.info("[OCR] model_root resolved to: %s", model_root)

                det_dir = os.path.join(model_root, "det", "en", "en_PP-OCRv3_det_infer")
                rec_dir = os.path.join(model_root, "rec", "en", "en_PP-OCRv4_rec_infer")
                cls_dir = os.path.join(model_root, "cls", "ch_ppocr_mobile_v2.0_cls_infer")

                _missing = [n for n, d in [("det", det_dir), ("rec", rec_dir), ("cls", cls_dir)] if not os.path.isdir(d)]
                if _missing:
                    if is_frozen:
                        msg = (
                            f"PaddleOCR models missing: {', '.join(_missing)}. "
                            f"Expected in: {model_root}. "
                            "Re-run the build with models cached in build_assets/paddleocr "
                            "or pre-populate ~/.paddleocr/whl/ before first run."
                        )
                        logger.error(f"[OCR] {msg}")
                        raise RuntimeError(msg)
                    else:
                        logger.warning(
                            f"[OCR] PaddleOCR models missing ({', '.join(_missing)}) in {model_root}. "
                            "Auto-downloading required models for source run..."
                        )
                        os.environ["PADDLEOCR_HOME"] = paddleocr_home
                        kwargs["download"] = True

                if os.path.isdir(det_dir):
                    kwargs["det_model_dir"] = det_dir
                if os.path.isdir(rec_dir):
                    kwargs["rec_model_dir"] = rec_dir
                if os.path.isdir(cls_dir):
                    kwargs["cls_model_dir"] = cls_dir

                if "download" not in kwargs:
                    kwargs["download"] = False  # Never re-download if cached models are already present
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


def is_ocr_ready() -> bool:
    """
    Non-blocking check: returns True if the PaddleOCR singleton is already
    initialized and ready to use.

    Safe to call from any thread at any time — never acquires any lock.
    Use this before eager OCR calls during folder scan so the scan worker
    never blocks waiting for background warmup to complete.

    Returns False if:
      - Warmup thread is still running (models not loaded yet).
      - Initialization previously failed (_init_error is set).
      - OCR was never requested.
    """
    return _ocr is not None


def run_shared_ocr(image_path: str, *, cls: bool = False, timeout: float = 180.0):
    """
    Run OCR through the shared PaddleOCR instance.

    PaddleOCR is not treated as re-entrant here: all CAPTCHA, cheque, and
    invoice OCR calls share one execution lock so local runs and frozen EXE
    runs behave consistently even when background OCR is active.

    Args:
        image_path: Absolute path to the image file.
        cls:        Whether to run text direction classification.
        timeout:    Maximum seconds to wait for the run lock before raising
                    TimeoutError.  Prevents indefinite hangs when background
                    warmup is still loading models (default: 180 s).

    Raises:
        TimeoutError: If the run lock cannot be acquired within ``timeout`` seconds.
        RuntimeError: If OCR initialization previously failed.
    """
    ocr_engine = get_shared_ocr()
    acquired = _ocr_run_lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(
            f"[OCR] run_shared_ocr: could not acquire execution lock within "
            f"{timeout:.0f}s — another OCR call is still running. "
            "This may indicate a hung warmup thread or a very large image."
        )
    try:
        return ocr_engine.ocr(image_path, cls=cls)
    finally:
        _ocr_run_lock.release()


def get_ocr_init_error() -> str | None:
    """Return the cached OCR initialization error, if initialization failed."""
    return _init_error


def ensure_ocr_ready():
    """
    Forces the initialization of PaddleOCR.
    Safe to call; handles and catches errors internally without blocking app flow.
    On failure, the error is recorded in _init_error and will be re-raised
    on any subsequent call to get_shared_ocr() so callers always see it.
    """
    try:
        get_shared_ocr()
        return True
    except Exception as exc:
        logger.warning(
            "[OCR] Background warmup failed: %s. "
            "Captcha solving and document OCR will be unavailable. "
            "Ensure PaddleOCR models are present under ~/.paddleocr/whl/ "
            "(source run) or bundled under .paddleocr/whl/ (EXE build). "
            "Check startup.log for the full traceback.",
            exc,
        )
        return False


def warmup_ocr_background():
    """
    Call once at app startup. Spawns a daemon thread to pre-load models in the background.
    """
    logger.info("[OCR] Starting background daemon thread to pre-load PaddleOCR models...")
    thread = threading.Thread(target=ensure_ocr_ready, name="PaddleOCR-Warmup", daemon=True)
    thread.start()
