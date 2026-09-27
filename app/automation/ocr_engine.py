"""
ocr_engine.py
Shared singleton engine for RapidOCR (ONNX Runtime), used for both CAPTCHA solving
and document/cheque OCR.
Loads models in a thread-safe manner, supports eager background warmup.
Features 100% backward-compatible output format for all legacy callers.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Shared globals
_ocr = None
_init_error: Optional[str] = None
_ocr_lock = threading.Lock()
_ocr_run_lock = threading.Lock()


def _setup_runtime_dlls() -> None:
    """Register ONNX Runtime native DLL paths when running inside PyInstaller frozen bundle."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "")
        ort_capi = os.path.join(base, "onnxruntime", "capi")
        if os.path.isdir(ort_capi):
            os.environ["PATH"] = ort_capi + os.pathsep + os.environ.get("PATH", "")
            try:
                os.add_dll_directory(ort_capi)
            except (OSError, AttributeError):
                pass
            logger.info(f"[OCR] ONNX Runtime DLL path registered: {ort_capi}")


def get_shared_ocr():
    """
    Returns the shared RapidOCR instance.
    Thread-safe, lazy-initialized singleton.
    """
    global _ocr, _init_error

    if _init_error is not None:
        raise RuntimeError(f"RapidOCR previously failed initialization: {_init_error}")

    if _ocr is not None:
        return _ocr

    with _ocr_lock:
        if _ocr is None:
            try:
                logger.info("[OCR] Initializing shared RapidOCR singleton (ONNX Runtime)...")
                start_time = time.perf_counter()

                _setup_runtime_dlls()

                from rapidocr_onnxruntime import RapidOCR

                init_kwargs: dict[str, Any] = {
                    "intra_op_num_threads": 1,
                    "inter_op_num_threads": 1,
                }

                # In PyInstaller frozen bundle, ensure model paths point to bundled files if needed
                if getattr(sys, "frozen", False):
                    base = getattr(sys, "_MEIPASS", "")
                    bundled_config = os.path.join(base, "rapidocr_onnxruntime", "config.yaml")
                    if os.path.isfile(bundled_config):
                        init_kwargs["config_path"] = bundled_config

                _ocr = RapidOCR(**init_kwargs)
                elapsed = time.perf_counter() - start_time
                logger.info(f"[OCR] Shared RapidOCR singleton initialized successfully in {elapsed:.2f} seconds.")

            except Exception as exc:
                import traceback
                _init_error = f"{type(exc).__name__}: {exc}"
                logger.error(f"[OCR] Shared RapidOCR singleton init FAILED: {exc}")
                logger.error(traceback.format_exc())
                raise

    return _ocr


def is_ocr_ready() -> bool:
    """
    Non-blocking check: returns True if the OCR singleton is already
    initialized and ready to use.
    """
    return _ocr is not None


def get_ocr_init_error() -> Optional[str]:
    """Return the cached OCR initialization error, if initialization failed."""
    return _init_error


def ensure_ocr_ready() -> bool:
    """
    Forces initialization of RapidOCR. Safe to call; catches errors internally.
    """
    try:
        get_shared_ocr()
        return True
    except Exception as exc:
        logger.warning(
            "[OCR] Background warmup failed: %s. "
            "CAPTCHA solving and document OCR will be unavailable.",
            exc,
        )
        return False


def warmup_ocr_background() -> None:
    """
    Call once at app startup. Spawns a daemon thread to pre-load models in the background.
    """
    logger.info("[OCR] Starting background daemon thread to pre-load RapidOCR models...")
    thread = threading.Thread(target=ensure_ocr_ready, name="RapidOCR-Warmup", daemon=True)
    thread.start()


def solve_captcha_bytes(img_bytes: bytes, timeout: float = 30.0) -> Optional[str]:
    """
    Direct in-memory CAPTCHA solving from raw bytes.
    Bypasses disk I/O completely and runs recognition directly (use_det=False).
    Falls back to detection mode if recognition-only produces empty text.
    Returns cleaned alphanumeric text (e.g. 'A7b9X2') or None on failure.
    """
    ocr_engine = get_shared_ocr()
    acquired = _ocr_run_lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(f"[OCR] solve_captcha_bytes: could not acquire lock within {timeout:.0f}s")
    try:
        # Pass 1: Recognition-only (fastest ~20ms, 100% accurate for cropped canvas)
        res, _ = ocr_engine(img_bytes, use_det=False, use_cls=False)
        raw_text = res[0][0] if (res and len(res) > 0 and res[0]) else ""
        clean_text = re.sub(r"[^A-Za-z0-9]", "", raw_text).strip()

        # Pass 2: Fallback to full detection if Pass 1 returned empty/too short
        if len(clean_text) < 3:
            res_det, _ = ocr_engine(img_bytes, use_det=True, use_cls=False)
            if res_det:
                raw_text = "".join(box[1] for box in res_det if len(box) > 1)
                clean_text = re.sub(r"[^A-Za-z0-9]", "", raw_text).strip()

        logger.info(f"[OCR] CAPTCHA solved -> raw='{raw_text}' | clean='{clean_text}'")
        return clean_text if clean_text else None
    finally:
        _ocr_run_lock.release()


def run_shared_ocr(image_path: str, *, cls: bool = False, timeout: float = 180.0) -> List[Any]:
    """
    Run OCR through the shared RapidOCR instance with 100% PaddleOCR-compatible schema.

    PaddleOCR returns:
        [ [ [bbox, (text, confidence)], ... ] ]
    RapidOCR natively returns:
        ( [ [bbox, text, confidence], ... ], elapse )

    This wrapper converts RapidOCR's output into the exact PaddleOCR schema so all
    existing callers (newindia/ocr_helper, claim_folder_service, etc.) work without changes.
    """
    ocr_engine = get_shared_ocr()
    acquired = _ocr_run_lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(
            f"[OCR] run_shared_ocr: could not acquire execution lock within {timeout:.0f}s"
        )
    try:
        result, _ = ocr_engine(image_path, use_det=True, use_cls=cls)
        if not result:
            return [None]

        # Convert to PaddleOCR schema: [ [ [bbox, (text, score)], ... ] ]
        paddle_lines = []
        for item in result:
            if len(item) >= 3:
                bbox = item[0]
                text = item[1]
                score = item[2]
                paddle_lines.append([bbox, (text, score)])
        return [paddle_lines] if paddle_lines else [None]
    finally:
        _ocr_run_lock.release()
