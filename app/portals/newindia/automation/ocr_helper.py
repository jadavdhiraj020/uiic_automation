"""
ocr_helper.py — Production-grade cheque OCR for NEFT bank detail extraction.

Extraction strategy per file:
  PDF  → pdfplumber text first; if empty, render pages at 300 DPI and OCR
  Image → Preprocess (grayscale, upscale, sharpen, binarize) then multi-PSM Tesseract

Fields extracted (all optional, fallback to Excel if missing):
  - ifsc          : 11-char IFSC code (with O→0 OCR correction)
  - account_number: 9–18 digit bank account number
  - account_type  : "Savings" | "Current"
"""

import os
import re
import logging
from typing import Dict, List, Optional

from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

# ── Regex patterns ─────────────────────────────────────────────────────────────

# IFSC: 4 alpha + 0 + 6 alphanumeric (loose allows O in position 4 for OCR errors)
_IFSC_STRICT  = re.compile(r'\b([A-Z]{4}0[A-Z0-9]{6})\b')
_IFSC_LOOSE   = re.compile(r'\b([A-Z]{4}[O0][A-Z0-9]{6})\b')

# Account number: labeled first, then bare fallback
_ACNO_LABELED = re.compile(
    r'(?:A[/\-.]?C(?:\s*NO?\.?)?|ACCOUNT\s*(?:NO?\.?|NUMBER|#)|ACCT\.?\s*(?:NO?\.?)?)'
    r'[^\d]{0,10}(\d[\d\s\-]{7,19}\d)',
    re.IGNORECASE,
)
_ACNO_BARE    = re.compile(r'\b(\d{9,18})\b')

# Account type keyword lists
_SAVINGS_KW  = ["saving", "savings", "sb a/c", "s.b.", "s b a/c", "savings bank"]
_CURRENT_KW  = ["current", "ca a/c", "c.a.", "current account", "ca acct", "cash credit", "cc a/c"]


# ══════════════════════════════════════════════════════════════════════════════
class ChequeExtractor:
    """Production-grade cheque OCR extractor."""

    SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

    def __init__(self, doc_path: str):
        self.doc_path = doc_path

    # ── Public entry point ────────────────────────────────────────────────────

    def extract_details(self, log=None) -> Dict[str, Optional[str]]:
        """
        Extract IFSC, account_number, and account_type from the cheque file.
        Returns dict with None for any field that could not be extracted.
        Caller must fallback to Excel data for None values.
        """
        result: Dict[str, Optional[str]] = {
            "ifsc": None, "account_number": None, "account_type": None
        }

        if not self.doc_path or not os.path.exists(self.doc_path):
            self._log(log, "error", f"Cheque file not found: {self.doc_path}")
            return result

        ext = os.path.splitext(self.doc_path)[1].lower()
        fname = os.path.basename(self.doc_path)
        self._log(log, "info", f"Starting cheque OCR: {fname}")

        # --- Step 1: Extract candidate text strings ---
        if ext == ".pdf":
            candidates = self._extract_pdf(log)
        elif ext in self.SUPPORTED_IMAGE_EXTS:
            candidates = self._extract_image(self.doc_path, log)
        else:
            self._log(log, "warning", f"Unsupported file type '{ext}'; skipping OCR.")
            return result

        if not candidates:
            self._log(log, "error", "No text could be extracted from cheque; using Excel fallback.")
            return result

        # --- Step 2: Parse each candidate text until all fields found ---
        for i, raw in enumerate(candidates):
            clean = self._normalize(raw)
            if not result["ifsc"]:
                result["ifsc"] = self._find_ifsc(clean, log)
            if not result["account_number"]:
                result["account_number"] = self._find_account_number(clean, log)
            if not result["account_type"]:
                result["account_type"] = self._find_account_type(clean, log)
            if all(result.values()):
                self._log(log, "info", f"All 3 fields found on OCR pass {i + 1}.")
                break

        # --- Step 3: Report ---
        for field, val in result.items():
            if val:
                self._log(log, "success", f"Extracted {field}: {val}")
            else:
                self._log(log, "warning", f"{field} NOT found in cheque — Excel fallback will apply.")

        return result

    # ── PDF extraction ─────────────────────────────────────────────────────────

    def _extract_pdf(self, log) -> List[str]:
        """Try pdfplumber text; if empty (scanned), render pages and OCR."""
        texts: List[str] = []
        try:
            import pdfplumber
            with pdfplumber.open(self.doc_path) as pdf:
                full = ""
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    full += t + "\n"
                if full.strip():
                    self._log(log, "info", f"pdfplumber: extracted {len(full)} chars.")
                    texts.append(full)
                else:
                    self._log(log, "info", "pdfplumber returned no text (scanned PDF); trying image OCR on pages.")
                    for i, page in enumerate(pdf.pages):
                        try:
                            pil_img = page.to_image(resolution=300).original
                            texts.extend(self._ocr_pil(pil_img, log))
                        except Exception as e:
                            self._log(log, "warning", f"Page {i} OCR failed: {str(e)[:80]}")
        except ImportError:
            self._log(log, "warning", "pdfplumber not installed; attempting image OCR directly on PDF.")
            texts.extend(self._extract_image(self.doc_path, log))
        except Exception as e:
            self._log(log, "error", f"PDF extraction error: {str(e)[:100]}")
        return texts

    # ── Image extraction ───────────────────────────────────────────────────────

    def _extract_image(self, path: str, log) -> List[str]:
        """Load an image file and run preprocessed OCR."""
        try:
            from PIL import Image
            img = Image.open(path)
            return self._ocr_pil(img, log)
        except ImportError:
            self._log(log, "warning", "Pillow not installed; cannot process image.")
            return []
        except Exception as e:
            self._log(log, "error", f"Image load error: {str(e)[:100]}")
            return []

    def _ocr_pil(self, pil_image, log) -> List[str]:
        """
        Preprocess PIL image then OCR with multiple Tesseract PSM configs.
        Preprocessing: grayscale → upscale if small → sharpen → binarize
        """
        try:
            import pytesseract
            from PIL import Image, ImageFilter
        except ImportError:
            self._log(log, "warning", "pytesseract not installed; cannot OCR image.")
            return []

        results: List[str] = []
        try:
            # 1. Grayscale
            img = pil_image.convert("L")

            # 2. Upscale if too small (Tesseract needs ~300 DPI / 1000px wide)
            w, h = img.size
            if w < 1000:
                scale = max(2, 1500 // max(w, 1))
                img = img.resize((w * scale, h * scale), Image.LANCZOS)
                self._log(log, "info", f"Image upscaled {scale}x for OCR quality.")

            # 3. Sharpen
            sharpened = img.filter(ImageFilter.SHARPEN)

            # 4. Binarize (simple threshold)
            threshold = 140
            binary = sharpened.point(lambda x: 255 if x > threshold else 0, "L")

            # 5. Multi-PSM OCR
            psm_configs = ["--psm 6 --oem 3", "--psm 3 --oem 3", "--psm 11 --oem 3"]
            for cfg in psm_configs:
                for variant in [binary, sharpened]:
                    try:
                        text = pytesseract.image_to_string(variant, config=cfg, lang="eng")
                        if text and len(text.strip()) > 10:
                            results.append(text)
                    except Exception:
                        pass

            self._log(log, "info", f"OCR produced {len(results)} text candidates from image.")
        except Exception as e:
            self._log(log, "error", f"OCR preprocessing failed: {str(e)[:100]}")

        return results

    # ── Field parsers ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """Clean and uppercase OCR text for reliable pattern matching."""
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'[^\x20-\x7E\n]', ' ', text)  # strip non-ASCII noise
        return text.upper().strip()

    @staticmethod
    def _fix_ifsc(raw: str) -> str:
        """Correct common OCR error: O in position 4 must be 0."""
        s = raw.upper()
        if len(s) >= 5 and s[4] in ('O',):
            s = s[:4] + '0' + s[5:]
        return s

    def _find_ifsc(self, text: str, log) -> Optional[str]:
        # Strict match
        m = _IFSC_STRICT.search(text)
        if m:
            return m.group(1)
        # Loose match with correction
        m = _IFSC_LOOSE.search(text)
        if m:
            return self._fix_ifsc(m.group(1))
        return None

    def _find_account_number(self, text: str, log) -> Optional[str]:
        # Join digit groups split by spaces/hyphens for matching
        joined = re.sub(r'(\d)[\s\-](\d)', r'\1\2', text)

        # Strategy 1: labeled keyword
        for src in [joined, text]:
            m = _ACNO_LABELED.search(src)
            if m:
                acno = re.sub(r'[\s\-]', '', m.group(1))
                if 9 <= len(acno) <= 18:
                    return acno

        # Strategy 2: largest bare number
        candidates = _ACNO_BARE.findall(joined)
        if candidates:
            return sorted(candidates, key=len, reverse=True)[0]

        return None

    @staticmethod
    def _find_account_type(text: str, log) -> Optional[str]:
        low = text.lower()
        if any(kw in low for kw in _CURRENT_KW):
            return "Current"
        if any(kw in low for kw in _SAVINGS_KW):
            return "Savings"
        return None

    # ── Logging helper ─────────────────────────────────────────────────────────

    @staticmethod
    def _log(log, level: str, msg: str) -> None:
        _icons = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "success": "✅"}
        if not log:
            getattr(logger, "info" if level == "success" else level)(f"[OCR] {msg}")
            return
        if isinstance(log, AutomationLogger):
            getattr(log, level)(msg)
        else:
            log(f"   {_icons.get(level, '')} [OCR] {msg}")
