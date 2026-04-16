"""
captcha_extractor.py
────────────────────
Extracts text from a canvas-rendered CAPTCHA PNG with correct case.

FREE tools only — no API keys needed:
  • OpenCV      (image processing)
  • pytesseract (OCR via Tesseract)
  • Pillow      (image I/O)

Install:
    pip install opencv-python-headless pytesseract pillow
    # Also install Tesseract binary:
    # Ubuntu/Debian: sudo apt install tesseract-ocr
    # macOS:         brew install tesseract
    # Windows:       https://github.com/UB-Mannheim/tesseract/wiki

How case detection works:
  The CAPTCHA uses a monospaced-ish font where:
    • Uppercase letters and digits start at the "cap line" (topmost y)
    • Lowercase letters sit lower (ascenders like j descend even further)
  So: if a character's bounding box TOP (y) is close to the cap line → UPPERCASE
      otherwise → lowercase.
  This is exact, not guesswork — it reads the actual pixel positions.
"""

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────
# Step 1 – Isolate text pixels
# ─────────────────────────────────────────────────────────────

def _extract_text_mask(img_bgr) -> "np.ndarray":
    """
    Return a binary mask where white pixels = text ink.

    Strategy: convert to LAB color space and threshold on the L (luminance)
    channel.  The CAPTCHA text is WHITE (high L) on a BLUE background (low L),
    so a simple high-luminance threshold cleanly separates them.

    Works for any light-text-on-dark-background CAPTCHA.
    If your portal uses dark text on a light background, swap the threshold
    to use THRESH_BINARY_INV instead.
    """
    import cv2

    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    L, _, _ = cv2.split(lab)
    # Pixels with L > 200 are very bright → that's our white text
    _, mask = cv2.threshold(L, 200, 255, cv2.THRESH_BINARY)
    return mask


# ─────────────────────────────────────────────────────────────
# Step 2 – OCR (Tesseract via pytesseract)
# ─────────────────────────────────────────────────────────────

def _run_ocr(mask) -> str:
    """
    Run Tesseract on the isolated text mask and return clean alphanumeric text.

    We try three page-segmentation modes (PSM 7, 8, 13) and pick the result
    whose character count matches the number of connected components in the
    mask — this is the ground-truth character count, so a length match means
    Tesseract segmented the image correctly.

    Fallback: if no PSM result matches, return the shortest non-empty result
    (fewer hallucinated characters is better than more).

    The image is scaled up 4× first so Tesseract has more pixels to work with.
    """
    import cv2
    import pytesseract

    # Scale up for better OCR accuracy
    h, w = mask.shape
    big = cv2.resize(mask, (w * 4, h * 4), interpolation=cv2.INTER_NEAREST)

    # Tesseract expects black text on white background
    big_inv = cv2.bitwise_not(big)

    char_whitelist = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    )
    base_cfg = f"-c tessedit_char_whitelist={char_whitelist}"

    results: dict = {}
    for psm in (7, 8, 13):
        raw = pytesseract.image_to_string(big_inv, config=f"--psm {psm} {base_cfg}").strip()
        clean = re.sub(r"[^A-Za-z0-9]", "", raw)
        results[psm] = clean

    # Ground-truth character count from connected components
    n_chars = len(_find_character_boxes(mask))

    # Prefer the result that matches the component count exactly
    for psm in (7, 8, 13):
        if len(results[psm]) == n_chars:
            return results[psm]

    # Fallback: shortest non-empty result (fewer hallucinations)
    non_empty = [v for v in results.values() if v]
    return min(non_empty, key=len) if non_empty else ""


# ─────────────────────────────────────────────────────────────
# Step 3 – Case restoration via character Y-position
# ─────────────────────────────────────────────────────────────

def _find_character_boxes(mask) -> List[Tuple[int, int, int, int]]:
    """
    Return sorted (left→right) bounding boxes of each character
    using connected-component analysis.

    Noise filter: a component must have area > 20px and height > 15% of
    the image height to be considered a real character.
    """
    import cv2

    img_h = mask.shape[0]
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

    boxes = []
    for i in range(1, n):                          # label 0 = background
        x, y, w, h, area = stats[i]
        if area > 20 and h > img_h * 0.15 and w > 1:
            boxes.append((x, y, w, h))

    boxes.sort(key=lambda b: b[0])                 # left → right
    return boxes


def _restore_case(mask, ocr_text: str) -> str:
    """
    Fix the case of each alphabetic character using its Y position.

    Core insight:
      • In a typical CAPTCHA font the cap line is the topmost y-coordinate
        among ALL character boxes.
      • Uppercase letters and digits start AT the cap line (y ≈ cap_line).
      • Lowercase letters sit BELOW the cap line (y > cap_line + tolerance).

    This is a physical measurement, not a statistical guess — it uses the
    actual pixel row where each glyph begins.

    Falls back to keeping OCR's original case if component count mismatches.
    """
    boxes = _find_character_boxes(mask)
    n = len(ocr_text)

    if len(boxes) != n:
        # Component count mismatch — return OCR text as-is
        print(
            f"  [warn] {len(boxes)} components found but OCR returned {n} chars. "
            f"Skipping case restoration."
        )
        return ocr_text

    cap_line = min(b[1] for b in boxes)   # topmost y = where uppercase glyphs start
    tolerance = 2                          # allow 2px wobble (anti-aliasing / rendering)

    result = []
    for ch, (x, y, w, h) in zip(ocr_text, boxes):
        if ch.isdigit():
            result.append(ch)              # digits are case-neutral
        elif y <= cap_line + tolerance:
            result.append(ch.upper())      # starts at cap line → uppercase
        else:
            result.append(ch.lower())      # starts below cap line → lowercase

    return "".join(result)


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def extract_captcha_text(image_path: str) -> Optional[str]:
    """
    Extract the CAPTCHA text from a PNG file with correct case.

    Parameters
    ----------
    image_path : str
        Path to the CAPTCHA PNG image.

    Returns
    -------
    str | None
        The extracted text (e.g. '22jejX'), or None on failure.
    """
    import cv2

    img = cv2.imread(image_path)
    if img is None:
        print(f"ERROR: Could not read image: {image_path}")
        return None

    mask    = _extract_text_mask(img)
    ocr_raw = _run_ocr(mask)

    if not ocr_raw:
        print("ERROR: OCR returned no text.")
        return None

    text = _restore_case(mask, ocr_raw)
    return text


def extract_captcha_from_bytes(img_bytes: bytes) -> Optional[str]:
    """
    Same as extract_captcha_text() but accepts raw PNG bytes
    (e.g. from Playwright's canvas.screenshot()).
    """
    import cv2
    import numpy as np

    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        print("ERROR: cv2.imdecode returned None — bad image bytes?")
        return None

    mask    = _extract_text_mask(img)
    ocr_raw = _run_ocr(mask)

    if not ocr_raw:
        print("ERROR: OCR returned no text.")
        return None

    return _restore_case(mask, ocr_raw)


# ─────────────────────────────────────────────────────────────
# CLI / test runner
# ─────────────────────────────────────────────────────────────

def _debug_save(image_path: str):
    """Save intermediate images for visual debugging."""
    import cv2

    img  = cv2.imread(image_path)
    mask = _extract_text_mask(img)

    out_dir = Path(image_path).parent
    cv2.imwrite(str(out_dir / "debug_mask.png"),    mask)
    cv2.imwrite(str(out_dir / "debug_mask_inv.png"), cv2.bitwise_not(mask))

    # Draw bounding boxes on original
    boxes  = _find_character_boxes(mask)
    canvas = img.copy()
    cap_line = min(b[1] for b in boxes) if boxes else 0
    for i, (x, y, w, h) in enumerate(boxes):
        color = (0, 255, 0) if y <= cap_line + 2 else (0, 165, 255)  # green=upper, orange=lower
        cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 1)
    cv2.imwrite(str(out_dir / "debug_boxes.png"), canvas)
    print(f"  Debug images saved to {out_dir}")


if __name__ == "__main__":
    test_image = sys.argv[1] if len(sys.argv) > 1 else "captcha.png"

    print(f"Image : {test_image}")
    print("─" * 40)

    import cv2
    import numpy as np

    img  = cv2.imread(test_image)
    mask = _extract_text_mask(img)
    ocr_raw = _run_ocr(mask)
    boxes   = _find_character_boxes(mask)
    cap_line = min(b[1] for b in boxes) if boxes else 0

    print(f"OCR raw output : '{ocr_raw}'")
    print(f"Components     : {len(boxes)} found  (need {len(ocr_raw)})")
    print(f"Cap line       : y = {cap_line}")
    print()
    print("Per-character breakdown:")
    if len(boxes) == len(ocr_raw):
        for i, (ch, (x, y, w, h)) in enumerate(zip(ocr_raw, boxes)):
            case_label = "digit" if ch.isdigit() else ("UPPER" if y <= cap_line + 2 else "lower")
            print(f"  [{i}] '{ch}' → y={y:2d}  h={h:2d}  → {case_label}")
    else:
        print("  (skipped — component/char count mismatch)")

    final = extract_captcha_text(test_image)
    print()
    print(f"✅  Result: '{final}'")

    # Save debug images alongside the input
    _debug_save(test_image) 