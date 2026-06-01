"""
ocr_helper.py — Production-grade cheque OCR for NEFT bank detail extraction.

Engine: PaddleOCR v2 (same engine used for CAPTCHA solving).
Strategy:
  PDF  → pdfplumber text first; if empty, render pages at 300 DPI and OCR
  Image → OpenCV preprocess (grayscale, CLAHE, denoise, adaptive threshold,
          skew correction) then PaddleOCR with spatial-aware extraction

Fields extracted (all optional, fallback to Excel if missing):
  - ifsc          : 11-char IFSC code (with multi-char OCR confusion correction)
  - account_number: 9–18 digit bank account number (MICR-filtered, scored)
  - account_type  : "Savings" | "Current"
"""

import os
import re
import logging
import tempfile
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from app.automation.automation_logger import AutomationLogger

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Regex patterns
# ══════════════════════════════════════════════════════════════════════════════

# IFSC: 4 alpha + 0 + 6 alphanumeric (loose allows common OCR confusions)
_IFSC_STRICT = re.compile(r'\b([A-Z]{4}0[A-Z0-9]{6})\b')
_IFSC_LOOSE  = re.compile(r'\b([A-Z]{4}[O0][A-Z0-9]{6})\b')

# Account number: labeled first, then bare fallback
_ACNO_LABELED = re.compile(
    r'(?:A[/\-.]?C(?:\s*NO?\.?)?|ACCOUNT\s*(?:NO?\.?|NUMBER|#)|ACCT\.?\s*(?:NO?\.?)?)'
    r'[^\d]{0,10}(\d[\d\s\-]{7,19}\d)',
    re.IGNORECASE,
)
_ACNO_BARE = re.compile(r'\b(\d{9,18})\b')

# Account type keyword lists
_SAVINGS_KW = ["saving", "savings", "sb a/c", "s.b.", "s b a/c", "savings bank", "sb account"]
_CURRENT_KW = ["current", "ca a/c", "c.a.", "current account", "ca acct", "cash credit", "cc a/c"]

# Negative anchors — numbers near these keywords are NOT account numbers
_NEGATIVE_ANCHORS = [
    "date", "phone", "mobile", "pin", "micr", "serial", "cheque no",
    "chq no", "chq.", "ch. no", "sr no", "sr.", "ifsc", "ifs code",
    "cif", "customer id", "pan", "gstin", "gst",
    "prefix",   # Branch prefix code — not an account number
    "swift",    # SWIFT code
    "tel", "fax",  # Phone/fax numbers
    "valid",    # Valid upto / Valid for
]

# Positive anchors — numbers near these keywords ARE likely account numbers
_POSITIVE_ANCHORS = [
    "a/c", "acct", "a.c.", "ac no", "acc no", "account number",
    "account no", "a/c no",
    # NOTE: "account" alone is NOT here — "SB ACCOUNT" describes account TYPE,
    # not an account number label. Use specific patterns only.
]

# Fuzzy OCR-tolerant patterns for spatial A/c No. label detection
# PaddleOCR often garbles "A/c No." to "Ac N9J", "Alc No", "A/C NO" etc.
_ACNO_LABEL_FUZZY = re.compile(
    r'(?:a[/\\.]?c|ac|alc)[\s.]*(?:n[o0-9][.:]?|no\.?)',
    re.IGNORECASE,
)

# Account TYPE keywords — these are NOT account number labels
_ACCOUNT_TYPE_KEYWORDS = [
    "sb account", "savings", "current", "cash credit", "sb a/c",
    "ca a/c", "c.a.", "s.b.", "cc a/c",
]

# Known Indian bank IFSC prefixes (top ~100 banks)
_KNOWN_BANK_PREFIXES = {
    "SBIN", "HDFC", "ICIC", "BARB", "PUNB", "CNRB", "UBIN", "IOBA",
    "BKID", "MAHB", "CORP", "SYNB", "ANDB", "IDIB", "ALLA", "UTIB",
    "KKBK", "INDB", "YESB", "CBIN", "FDRL", "KARB", "BKDN", "UCBA",
    "VIJB", "PSIB", "ORBC", "SIBL", "RATN", "TMBL", "JAKA", "CSBK",
    "KVBL", "SRCB", "NKGS", "DLXB", "ESFB", "AUBL", "BDBL", "IBKL",
    "BNPA", "CIUB", "DCBL", "HSBC", "SCBL", "CITI", "DEUT", "STBP",
    "SBHY", "SBMY", "SBBJ", "SBTR", "LAVB", "DNSB", "NSPB", "GSCB",
    "KSAB", "MSCI", "ABHY", "APGB", "ARBL", "BACB", "BBKM", "BBRB",
    "CCBL", "COSB", "DBSS", "DCCB", "DICG", "DLSC", "DMKB", "FINO",
    "ESMF", "HDCB", "HPSC", "IDFB", "JSFB", "KCUB", "KUCB", "MDBK",
    "MGCB", "MUBL", "NESF", "PRTH", "RNSB", "SURY", "SVCB", "TBSB",
    "TSAB", "URCB", "VARA", "WBSC", "YESB", "ZURB",
}


# ══════════════════════════════════════════════════════════════════════════════
# PaddleOCR Document-OCR Lazy Singleton
# ══════════════════════════════════════════════════════════════════════════════

from app.automation.ocr_engine import ensure_ocr_ready, run_shared_ocr


# ══════════════════════════════════════════════════════════════════════════════
# Data structures for scored candidates
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class OCRTextBlock:
    """A single text block from PaddleOCR with spatial info."""
    text: str
    confidence: float
    bbox: List[List[float]]  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    y_center: float = 0.0
    x_center: float = 0.0

    def __post_init__(self):
        if self.bbox:
            ys = [p[1] for p in self.bbox]
            xs = [p[0] for p in self.bbox]
            self.y_center = sum(ys) / len(ys)
            self.x_center = sum(xs) / len(xs)


@dataclass
class ScoredCandidate:
    """A candidate extraction result with scoring breakdown."""
    value: str
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    ocr_confidence: float = 0.0
    source_text: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Main Extractor Class
# ══════════════════════════════════════════════════════════════════════════════

class ChequeExtractor:
    """Production-grade cheque OCR extractor using PaddleOCR."""

    SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

    def __init__(self, doc_path: str):
        self.doc_path = doc_path
        self._image_height = 0  # Set during OCR for MICR zone detection

    # ── Public entry point ────────────────────────────────────────────────────

    def extract_details(self, log=None, excel_ifsc: str = "", excel_account: str = "", stop_cb: Optional[callable] = None) -> Dict[str, Optional[str]]:
        """
        Extract IFSC, account_number, and account_type from the cheque file.
        Returns dict with None for any field that could not be extracted.

        Args:
            log: AutomationLogger or callable for UI logging
            excel_ifsc: IFSC from Excel for cross-validation (optional)
            excel_account: Account number from Excel for cross-validation (optional)
            stop_cb: Cooperative cancel callback from worker thread
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

        if stop_cb and stop_cb():
            self._log(log, "warning", "Cheque OCR cancelled by user.")
            return result

        # --- Step 1: Extract text blocks with spatial info ---
        if ext == ".pdf":
            candidates = self._extract_pdf(log, excel_ifsc, excel_account, stop_cb)
        elif ext in self.SUPPORTED_IMAGE_EXTS:
            candidates = self._extract_image(self.doc_path, log, excel_ifsc, excel_account, stop_cb)
        else:
            self._log(log, "warning", f"Unsupported file type '{ext}'; skipping OCR.")
            return result

        if stop_cb and stop_cb():
            self._log(log, "warning", "Cheque OCR cancelled by user.")
            return result

        if not candidates:
            self._log(log, "error", "No text could be extracted from cheque; using Excel fallback.")
            return result

        # --- Step 2: Parse using scored extraction ---
        # Try structured (spatial-aware) extraction first
        structured_blocks = getattr(self, '_last_structured_blocks', [])
        if structured_blocks:
            self._log(log, "info", f"Using spatial-aware extraction on {len(structured_blocks)} text blocks.")
            result["ifsc"] = self._find_ifsc_scored(structured_blocks, excel_ifsc, log)
            result["account_number"] = self._find_account_number_scored(structured_blocks, excel_account, log)
            result["account_type"] = self._find_account_type_from_blocks(structured_blocks, log)

        # Fallback: parse flat text candidates for any remaining missing fields
        for i, raw in enumerate(candidates):
            if stop_cb and stop_cb():
                self._log(log, "warning", "Cheque OCR cancelled by user.")
                break
            clean = self._normalize(raw)
            if not result["ifsc"]:
                result["ifsc"] = self._find_ifsc(clean, log)
            if not result["account_number"]:
                result["account_number"] = self._find_account_number(clean, log)
            if not result["account_type"]:
                result["account_type"] = self._find_account_type(clean, log)
            if all(result.values()):
                self._log(log, "info", f"All 3 fields found on pass {i + 1}.")
                break

        # --- Step 3: Report results ---
        for fld, val in result.items():
            if val:
                self._log(log, "success", f"Extracted {fld}: {val}")
            else:
                self._log(log, "warning", f"{fld} NOT found in cheque — Excel fallback will apply.")

        if isinstance(log, AutomationLogger) and log._portal_id == "newindia":
            ocr_fields = {}
            if result.get("ifsc"):
                ocr_fields["IFSC"] = result["ifsc"]
            if result.get("account_number"):
                ocr_fields["Account Number"] = result["account_number"]
            if result.get("account_type"):
                ocr_fields["Account Type"] = result["account_type"]
            log.ocr_processed(fname, ocr_fields)

        return result

    # ══════════════════════════════════════════════════════════════════════════
    # PDF extraction
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_pdf(self, log, excel_ifsc: str = "", excel_account: str = "", stop_cb: Optional[callable] = None) -> List[str]:
        """Try pdfplumber text; if empty (scanned), render pages and OCR."""
        texts: List[str] = []
        try:
            import pdfplumber
            if stop_cb and stop_cb():
                return texts
            with pdfplumber.open(self.doc_path) as pdf:
                full = ""
                # Cheques are strictly 1-page documents. Limit to first page to avoid hanging on large multi-page PDFs.
                for page in pdf.pages[:1]:
                    if stop_cb and stop_cb():
                        return texts
                    t = page.extract_text() or ""
                    full += t + "\n"
                if full.strip():
                    self._log(log, "info", f"pdfplumber: extracted {len(full)} chars from first page.")
                    texts.append(full)
                else:
                    self._log(log, "info", "pdfplumber returned no text (scanned PDF); trying image OCR on page 1.")
                    for i, page in enumerate(pdf.pages[:1]):
                        if stop_cb and stop_cb():
                            return texts
                        try:
                            pil_img = page.to_image(resolution=300).original
                            texts.extend(self._ocr_pil(pil_img, log, excel_ifsc, excel_account, stop_cb))
                        except Exception as e:
                            exc_name = type(e).__name__
                            if "PDFInfoNotInstalledError" in exc_name or "pdfinfo" in str(e).lower():
                                self._log(log, "warning", "Poppler system binary is missing. PDF page rendering is not available.")
                                self._log(log, "warning", "👉 Solution: Install Poppler (e.g. via Scoop: 'scoop install poppler') and add to PATH.")
                            else:
                                self._log(log, "warning", f"Page {i} OCR failed: {str(e)[:80]}")
        except ImportError:
            self._log(log, "warning", "pdfplumber not installed; attempting image OCR directly on PDF.")
            texts.extend(self._extract_image(self.doc_path, log, excel_ifsc, excel_account, stop_cb))
        except Exception as e:
            exc_name = type(e).__name__
            if "PDFInfoNotInstalledError" in exc_name or "pdfinfo" in str(e).lower():
                self._log(log, "warning", "Poppler system binary is missing. PDF page rendering is not available.")
                self._log(log, "warning", "👉 Solution: Install Poppler (e.g. via Scoop: 'scoop install poppler') and add to PATH.")
            else:
                self._log(log, "error", f"PDF extraction error: {str(e)[:100]}")
        return texts

    # ══════════════════════════════════════════════════════════════════════════
    # Image extraction with OpenCV preprocessing
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_image(self, path: str, log, excel_ifsc: str = "", excel_account: str = "", stop_cb: Optional[callable] = None) -> List[str]:
        """Load an image file and run preprocessed OCR."""
        try:
            from PIL import Image
            if stop_cb and stop_cb():
                return []
            img = Image.open(path)
            return self._ocr_pil(img, log, excel_ifsc, excel_account, stop_cb)
        except ImportError:
            self._log(log, "warning", "Pillow not installed; cannot process image.")
            return []
        except Exception as e:
            self._log(log, "error", f"Image load error: {str(e)[:100]}")
            return []

    def _preprocess_opencv(self, pil_image, log, stop_cb: Optional[callable] = None) -> list:
        """
        Advanced OpenCV preprocessing pipeline.
        Returns a list of PIL Image variants to OCR.
        """
        if stop_cb and stop_cb():
            return [pil_image]
        try:
            import cv2
            import numpy as np
            from PIL import Image
        except ImportError:
            self._log(log, "warning", "OpenCV not available; using raw image only.")
            return [pil_image]

        variants = []

        try:
            # Convert PIL → OpenCV (numpy array)
            img_array = np.array(pil_image.convert("RGB"))
            img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

            h, w = gray.shape[:2]
            self._image_height = h  # Store for MICR zone detection

            # --- 1. Upscale if too small ---
            if w < 1200:
                scale = max(2, 1500 // max(w, 1))
                gray = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
                h, w = gray.shape[:2]
                self._image_height = h
                self._log(log, "info", f"Image upscaled {scale}x → {w}x{h}")

            # --- 2. Denoise ---
            denoised = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

            # --- 3. CLAHE contrast enhancement ---
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(denoised)

            # --- 4. Adaptive threshold ---
            adaptive = cv2.adaptiveThreshold(
                enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 21, 10
            )

            # --- 5. Skew correction ---
            corrected = self._correct_skew(adaptive, log)

            # Build variant list: corrected (primary), enhanced grayscale (secondary)
            variants.append(Image.fromarray(corrected))
            variants.append(Image.fromarray(enhanced))

            # Also add original grayscale as fallback
            variants.append(Image.fromarray(gray))

            self._log(log, "info", f"Preprocessing: denoise→CLAHE→adaptive threshold→skew correction. {len(variants)} variants.")

        except Exception as e:
            self._log(log, "warning", f"OpenCV preprocessing failed ({str(e)[:80]}); using raw image.")
            variants = [pil_image]

        return variants

    @staticmethod
    def _correct_skew(image, log, max_angle: float = 15.0):
        """Detect and correct document skew using Hough lines."""
        try:
            import cv2
            import numpy as np

            # Detect edges
            edges = cv2.Canny(image, 50, 200, apertureSize=3)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                    minLineLength=image.shape[1] // 4,
                                    maxLineGap=10)

            if lines is None or len(lines) == 0:
                return image

            # Calculate median angle from detected lines
            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                if abs(x2 - x1) > 0:
                    angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    if abs(angle) < max_angle:
                        angles.append(angle)

            if not angles:
                return image

            median_angle = np.median(angles)
            if abs(median_angle) < 0.5:
                return image  # Negligible skew

            # Rotate to correct
            h, w = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            corrected = cv2.warpAffine(image, M, (w, h),
                                        flags=cv2.INTER_CUBIC,
                                        borderMode=cv2.BORDER_REPLICATE)
            return corrected

        except Exception:
            return image  # Silently return original on any error

    def _ocr_pil(self, pil_image, log, excel_ifsc: str = "", excel_account: str = "", stop_cb: Optional[callable] = None) -> List[str]:
        """
        Preprocess PIL image then OCR with PaddleOCR.
        Returns list of concatenated text strings (one per variant).
        Also stores structured blocks in self._last_structured_blocks.
        """
        self._last_structured_blocks = []
        results: List[str] = []

        # Get preprocessed variants
        variants = self._preprocess_opencv(pil_image, log, stop_cb)

        for var_idx, variant_img in enumerate(variants):
            if stop_cb and stop_cb():
                self._log(log, "warning", "Cheque OCR cancelled by user.")
                break
            try:
                blocks = self._run_paddleocr(variant_img, log, stop_cb)
                if blocks:
                    # Merge structured blocks (prefer first variant's blocks)
                    if not self._last_structured_blocks:
                        self._last_structured_blocks = blocks

                    # Concatenate all text
                    full_text = " ".join(b.text for b in blocks)
                    if len(full_text.strip()) > 10:
                        results.append(full_text)
                        self._log(log, "info",
                                  f"Variant {var_idx + 1}: {len(blocks)} blocks, "
                                  f"{len(full_text)} chars, "
                                  f"avg confidence {sum(b.confidence for b in blocks)/len(blocks):.2f}")
                        
                        # Early termination check
                        if self._is_extraction_complete(blocks, full_text, excel_ifsc, excel_account, log):
                            self._log(log, "success", f"⚡ Early termination: valid IFSC and Account Number extracted from variant {var_idx + 1}.")
                            break
            except Exception as e:
                self._log(log, "warning", f"OCR variant {var_idx + 1} failed: {str(e)[:80]}")

        if not results:
            self._log(log, "warning", "All OCR variants produced no usable text.")

        # Deduplicate spatially: merge blocks from multiple variants
        if len(results) > 1:
            self._deduplicate_blocks()

        self._log(log, "info", f"OCR produced {len(results)} text candidates from image.")
        return results

    def _is_extraction_complete(self, blocks: List[OCRTextBlock], full_text: str, excel_ifsc: str, excel_account: str, log) -> bool:
        """Check if both IFSC and Account Number can be successfully extracted from the given blocks/text."""
        ifsc = self._find_ifsc_scored(blocks, excel_ifsc, log)
        if not ifsc:
            clean = self._normalize(full_text)
            ifsc = self._find_ifsc(clean, log)
            
        acno = self._find_account_number_scored(blocks, excel_account, log)
        if not acno:
            clean = self._normalize(full_text)
            acno = self._find_account_number(clean, log)
            
        return bool(ifsc and acno)

    def _run_paddleocr(self, pil_image, log, stop_cb: Optional[callable] = None) -> List[OCRTextBlock]:
        """Run PaddleOCR on a PIL image and return structured text blocks."""
        blocks: List[OCRTextBlock] = []
        if stop_cb and stop_cb():
            return blocks

        try:
            if not ensure_ocr_ready():
                raise RuntimeError("shared PaddleOCR initialization failed")
        except Exception as e:
            self._log(log, "error", f"PaddleOCR not available: {str(e)[:100]}")
            # Fallback to pytesseract if available (backward compat)
            return self._run_tesseract_fallback(pil_image, log, stop_cb)

        # Save PIL image to temp file (PaddleOCR needs a file path)
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(tmp_fd)
        try:
            if stop_cb and stop_cb():
                return blocks
            pil_image.save(tmp_path)
            if stop_cb and stop_cb():
                return blocks
            result = run_shared_ocr(tmp_path, cls=True)

            if not result or result[0] is None:
                return blocks

            for line in result[0]:
                if stop_cb and stop_cb():
                    return blocks
                bbox = line[0]           # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                text = line[1][0]        # recognized text
                confidence = line[1][1]  # confidence score (0.0–1.0)

                if text and len(text.strip()) > 0:
                    blocks.append(OCRTextBlock(
                        text=text.strip(),
                        confidence=confidence,
                        bbox=bbox,
                    ))

        except Exception as e:
            self._log(log, "warning", f"PaddleOCR execution error: {str(e)[:100]}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return blocks

    def _run_tesseract_fallback(self, pil_image, log, stop_cb: Optional[callable] = None) -> List[OCRTextBlock]:
        """Last-resort fallback to pytesseract if PaddleOCR is unavailable."""
        try:
            import pytesseract
            from PIL import ImageFilter
        except ImportError:
            self._log(log, "warning", "Neither PaddleOCR nor pytesseract available; cannot OCR.")
            return []

        blocks: List[OCRTextBlock] = []
        try:
            if stop_cb and stop_cb():
                return blocks
            # Simple grayscale + sharpen
            img = pil_image.convert("L")
            sharpened = img.filter(ImageFilter.SHARPEN)
            threshold = 140
            binary = sharpened.point(lambda x: 255 if x > threshold else 0, "L")

            for cfg in ["--psm 6 --oem 3", "--psm 3 --oem 3"]:
                if stop_cb and stop_cb():
                    break
                for variant in [binary, sharpened]:
                    if stop_cb and stop_cb():
                        break
                    try:
                        text = pytesseract.image_to_string(variant, config=cfg, lang="eng")
                        if text and len(text.strip()) > 10:
                            blocks.append(OCRTextBlock(
                                text=text.strip(),
                                confidence=0.5,  # Unknown confidence for tesseract
                                bbox=[[0, 0], [0, 0], [0, 0], [0, 0]],
                            ))
                    except Exception as e:
                        exc_name = type(e).__name__
                        if "TesseractNotFoundError" in exc_name or "tesseract is not installed" in str(e).lower():
                            self._log(log, "warning", "Tesseract binary is not installed or not in PATH. OCR fallback skipped.")
                            self._log(log, "warning", "👉 Solution: Install Tesseract-OCR (https://github.com/UB-Mannheim/tesseract/wiki) and add to PATH.")
                            return blocks
                        pass

            self._log(log, "info", f"Tesseract fallback: {len(blocks)} text blocks.")
        except Exception as e:
            self._log(log, "warning", f"Tesseract fallback failed: {str(e)[:80]}")

        return blocks

    def _deduplicate_blocks(self):
        """Remove near-duplicate text blocks from multiple OCR passes."""
        if not self._last_structured_blocks:
            return

        seen = {}
        unique = []
        for block in self._last_structured_blocks:
            # Normalize text for dedup comparison
            key = re.sub(r'\s+', '', block.text.upper())
            if key not in seen or block.confidence > seen[key].confidence:
                seen[key] = block

        self._last_structured_blocks = list(seen.values())

    # ══════════════════════════════════════════════════════════════════════════
    # IFSC Extraction (Scored, with cross-validation)
    # ══════════════════════════════════════════════════════════════════════════

    def _find_ifsc_scored(self, blocks: List[OCRTextBlock], excel_ifsc: str, log) -> Optional[str]:
        """
        Find IFSC code using scored candidate ranking with spatial awareness.
        """
        candidates: List[ScoredCandidate] = []
        excel_prefix = excel_ifsc[:4].upper() if excel_ifsc and len(excel_ifsc) >= 4 else ""

        for block in blocks:
            text = block.text.upper()
            text_fixed = self._fix_ocr_confusions(text)

            # Search in both original and OCR-corrected text
            for search_text in [text_fixed, text]:
                for m in _IFSC_STRICT.finditer(search_text):
                    raw = m.group(1)
                    candidate = ScoredCandidate(value=raw, ocr_confidence=block.confidence, source_text=text)
                    self._score_ifsc(candidate, block, blocks, excel_prefix)
                    candidates.append(candidate)

                for m in _IFSC_LOOSE.finditer(search_text):
                    raw = self._fix_ifsc(m.group(1))
                    # Avoid duplicate with strict match
                    if not any(c.value == raw for c in candidates):
                        candidate = ScoredCandidate(value=raw, ocr_confidence=block.confidence, source_text=text)
                        candidate.reasons.append("loose match (O→0 corrected)")
                        self._score_ifsc(candidate, block, blocks, excel_prefix)
                        candidates.append(candidate)

        if not candidates:
            return None

        # Sort by score descending, pick best
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Log all candidates
        for i, c in enumerate(candidates):
            marker = "→ SELECTED" if i == 0 else ""
            self._log(log, "info",
                      f"IFSC candidate: {c.value} (score={c.score:.2f}, "
                      f"conf={c.ocr_confidence:.2f}) {' | '.join(c.reasons)} {marker}")

        return candidates[0].value

    def _score_ifsc(self, candidate: ScoredCandidate, block: OCRTextBlock,
                    all_blocks: List[OCRTextBlock], excel_prefix: str):
        """Score an IFSC candidate based on multiple heuristics."""
        score = 1.0  # Base score
        val = candidate.value

        # 1. Known bank prefix bonus
        prefix = val[:4]
        if prefix in _KNOWN_BANK_PREFIXES:
            score += 0.3
            candidate.reasons.append(f"known bank: {prefix}")

        # 2. Keyword proximity bonus — is "IFSC" or similar nearby?
        ifsc_keywords = ["IFSC", "IFS CODE", "IFSC CODE", "IFS"]
        for other_block in all_blocks:
            other_text = other_block.text.upper()
            if any(kw in other_text for kw in ifsc_keywords):
                # Check spatial proximity (within ~200px vertically)
                if abs(other_block.y_center - block.y_center) < 200:
                    score += 0.3
                    candidate.reasons.append("near IFSC keyword")
                    break

        # 3. Excel cross-validation
        if excel_prefix:
            if prefix == excel_prefix:
                score += 0.3
                candidate.reasons.append(f"matches Excel prefix ({excel_prefix})")
            else:
                score -= 0.1
                candidate.reasons.append(f"differs from Excel prefix ({excel_prefix})")

        # 4. OCR confidence
        score += min(candidate.ocr_confidence * 0.2, 0.2)

        # 5. Structural validation: position 4 must be 0
        if len(val) == 11 and val[4] == '0':
            score += 0.1
            candidate.reasons.append("valid structure")

        candidate.score = score

    # ══════════════════════════════════════════════════════════════════════════
    # Account Number Extraction (Scored, MICR-filtered)
    # ══════════════════════════════════════════════════════════════════════════

    def _find_account_number_scored(self, blocks: List[OCRTextBlock],
                                     excel_account: str, log) -> Optional[str]:
        """
        Find account number using scored candidate ranking with MICR filtering.
        """
        candidates: List[ScoredCandidate] = []
        image_h = self._image_height or 1000  # Default if not set

        for block in blocks:
            text = block.text.upper()

            # Join digit groups split by spaces/hyphens
            joined = re.sub(r'(\d)[\s\-](\d)', r'\1\2', text)

            # Strategy 1: labeled keyword match
            for search_src in [joined, text]:
                for m in _ACNO_LABELED.finditer(search_src):
                    acno = re.sub(r'[\s\-]', '', m.group(1))
                    if 9 <= len(acno) <= 18:
                        candidate = ScoredCandidate(
                            value=acno, ocr_confidence=block.confidence, source_text=text)
                        candidate.reasons.append("labeled match")
                        self._score_account(candidate, block, blocks, image_h, excel_account)
                        candidates.append(candidate)

            # Strategy 2: bare number candidates
            for m in _ACNO_BARE.finditer(joined):
                acno = m.group(1)
                # Skip if already found as labeled
                if any(c.value == acno for c in candidates):
                    continue
                candidate = ScoredCandidate(
                    value=acno, ocr_confidence=block.confidence, source_text=text)
                candidate.reasons.append("bare number")
                self._score_account(candidate, block, blocks, image_h, excel_account)
                if candidate.score > 0:  # Only add if not disqualified
                    candidates.append(candidate)

        if not candidates:
            return None

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)

        # Log all candidates
        for i, c in enumerate(candidates[:8]):  # Top 8 for visibility
            marker = "→ SELECTED" if i == 0 else ""
            self._log(log, "info",
                      f"Account candidate: {c.value} (score={c.score:.2f}, "
                      f"conf={c.ocr_confidence:.2f}, len={len(c.value)}) "
                      f"{' | '.join(c.reasons)} {marker}")

        return candidates[0].value

    def _score_account(self, candidate: ScoredCandidate, block: OCRTextBlock,
                        all_blocks: List[OCRTextBlock], image_h: int, excel_account: str):
        """Score an account number candidate with MICR exclusion and anchor detection."""
        score = 1.0
        val = candidate.value

        # 1. MICR zone penalty — bottom 15% of image is typically MICR band
        micr_threshold = image_h * 0.85
        if block.y_center > micr_threshold:
            score -= 2.0  # Strong disqualification
            candidate.reasons.append("MICR zone (bottom 15%)")

        # 2. Length-based scoring (Indian accounts are typically 9–18 digits)
        length = len(val)
        if 11 <= length <= 16:
            score += 0.2
            candidate.reasons.append(f"optimal length ({length})")
        elif length == 9 or length == 10:
            score += 0.05  # Slightly less common
        elif length > 18 or length < 9:
            score -= 1.0
            candidate.reasons.append("invalid length")

        # 3. Positive anchor proximity — check for A/c No. label nearby
        #    Use BOTH exact keyword matching AND fuzzy OCR-tolerant regex
        #    IMPORTANT: Filter out "SB ACCOUNT" / account TYPE words that
        #    describe the type, not label the number.
        found_positive = False
        for other_block in all_blocks:
            if other_block is block:
                continue  # Don't match self
            other_text = other_block.text.lower()
            # Skip if this block is actually an account TYPE label
            if any(kw in other_text for kw in _ACCOUNT_TYPE_KEYWORDS):
                continue
            # Check exact positive anchors
            if any(kw in other_text for kw in _POSITIVE_ANCHORS):
                if abs(other_block.y_center - block.y_center) < 150:
                    score += 0.5
                    candidate.reasons.append("near Account keyword")
                    found_positive = True
                    break
            # Check fuzzy OCR-tolerant A/c No. pattern (e.g., "Ac N9J")
            if _ACNO_LABEL_FUZZY.search(other_block.text):
                if abs(other_block.y_center - block.y_center) < 150:
                    score += 0.5
                    candidate.reasons.append("near A/c label (fuzzy)")
                    found_positive = True
                    break

        # 4. Negative anchor proximity
        for other_block in all_blocks:
            other_text = other_block.text.lower()
            if any(kw in other_text for kw in _NEGATIVE_ANCHORS):
                if abs(other_block.y_center - block.y_center) < 100:
                    score -= 0.5
                    candidate.reasons.append(f"near negative keyword")
                    break

        # 4b. Account TYPE word nearby penalty
        #     "SB ACCOUNT", "SAVINGS", "CURRENT" etc. near a number means
        #     the number is likely the PREFIX code, not the account number.
        for other_block in all_blocks:
            if other_block is block:
                continue
            other_text = other_block.text.lower()
            if any(kw in other_text for kw in _ACCOUNT_TYPE_KEYWORDS):
                if abs(other_block.y_center - block.y_center) < 120:
                    score -= 0.3
                    candidate.reasons.append("near account-type label")
                    break

        # 5. Excel length cross-validation
        if excel_account:
            excel_len = len(re.sub(r'[^\d]', '', excel_account))
            if excel_len > 0 and len(val) == excel_len:
                score += 0.2
                candidate.reasons.append("matches Excel length")

        # 6. All-same-digit penalty (e.g., 000000000)
        if len(set(val)) <= 2:
            score -= 1.0
            candidate.reasons.append("repetitive digits")

        # 7. OCR confidence bonus
        score += min(candidate.ocr_confidence * 0.15, 0.15)

        # 8. Labeled match bonus (already in reasons)
        if "labeled match" in candidate.reasons:
            score += 0.3

        candidate.score = score

    # ══════════════════════════════════════════════════════════════════════════
    # Account Type Detection
    # ══════════════════════════════════════════════════════════════════════════

    def _find_account_type_from_blocks(self, blocks: List[OCRTextBlock], log) -> Optional[str]:
        """Detect account type from structured blocks."""
        for block in blocks:
            result = self._find_account_type(block.text, log)
            if result:
                return result
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # Original flat-text field parsers (backward compatible, used as fallback)
    # ══════════════════════════════════════════════════════════════════════════

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

    @staticmethod
    def _fix_ocr_confusions(text: str) -> str:
        """
        Apply common OCR confusion corrections for IFSC detection.
        Only applied to uppercase text for IFSC-like patterns.
        """
        # Find potential IFSC-like patterns (4 alpha + 1 char + 6 alphanum)
        # and correct common OCR confusions within them
        def _fix_match(m):
            s = m.group(0)
            # Position 4: O → 0
            if len(s) >= 5 and s[4] == 'O':
                s = s[:4] + '0' + s[5:]
            # In numeric portions (positions 5–10): I → 1, S → 5, B → 8, l → 1
            if len(s) == 11:
                suffix = list(s[5:])
                for i, ch in enumerate(suffix):
                    if ch == 'I':
                        suffix[i] = '1'
                    elif ch == 'l':
                        suffix[i] = '1'
                s = s[:5] + ''.join(suffix)
            return s

        # Apply to potential IFSC patterns
        result = re.sub(r'\b[A-Z]{4}[O0][A-Z0-9I1l]{6}\b', _fix_match, text)
        return result

    def _find_ifsc(self, text: str, log) -> Optional[str]:
        """Find IFSC from flat text (backward compatible fallback)."""
        # Apply OCR confusion fixes first
        fixed = self._fix_ocr_confusions(text)

        # Strict match
        m = _IFSC_STRICT.search(fixed)
        if m:
            return m.group(1)
        m = _IFSC_STRICT.search(text)
        if m:
            return m.group(1)

        # Loose match with correction
        m = _IFSC_LOOSE.search(fixed)
        if m:
            return self._fix_ifsc(m.group(1))
        m = _IFSC_LOOSE.search(text)
        if m:
            return self._fix_ifsc(m.group(1))

        return None

    def _find_account_number(self, text: str, log) -> Optional[str]:
        """Find account number from flat text (backward compatible fallback)."""
        # Join digit groups split by spaces/hyphens for matching
        joined = re.sub(r'(\d)[\s\-](\d)', r'\1\2', text)

        # Strategy 1: labeled keyword
        for src in [joined, text]:
            m = _ACNO_LABELED.search(src)
            if m:
                acno = re.sub(r'[\s\-]', '', m.group(1))
                if 9 <= len(acno) <= 18:
                    return acno

        # Strategy 2: largest bare number (with basic filtering)
        candidates = _ACNO_BARE.findall(joined)
        if candidates:
            # Filter out repetitive-digit numbers
            valid = [c for c in candidates if len(set(c)) > 2]
            if valid:
                return sorted(valid, key=len, reverse=True)[0]
            return sorted(candidates, key=len, reverse=True)[0]

        return None

    @staticmethod
    def _find_account_type(text: str, log) -> Optional[str]:
        """Detect account type from text keywords."""
        low = text.lower()
        if any(kw in low for kw in _CURRENT_KW):
            return "Current"
        if any(kw in low for kw in _SAVINGS_KW):
            return "Savings"
        return None

    # ══════════════════════════════════════════════════════════════════════════
    # Logging helper
    # ══════════════════════════════════════════════════════════════════════════

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
