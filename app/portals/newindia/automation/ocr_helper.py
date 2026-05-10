import os
import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class ChequeExtractor:
    """Standalone helper for extracting NEFT details from a cheque document."""

    def __init__(self, doc_path: str):
        self.doc_path = doc_path
        self.raw_text = ""

    def _extract_text(self):
        """Extract text from the document (PDF or Image)."""
        if not self.doc_path or not os.path.exists(self.doc_path):
            logger.warning(f"[OCR] Document not found: {self.doc_path}")
            return

        ext = os.path.splitext(self.doc_path)[1].lower()
        
        if ext == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(self.doc_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            self.raw_text += text + "\n"
                logger.info("[OCR] Successfully extracted text from PDF using pdfplumber.")
            except ImportError:
                logger.warning("[OCR] pdfplumber not installed. Cannot extract text from PDF.")
            except Exception as e:
                logger.warning(f"[OCR] Error extracting text from PDF: {e}")
        elif ext in [".jpg", ".jpeg", ".png"]:
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(self.doc_path)
                self.raw_text = pytesseract.image_to_string(img)
                logger.info("[OCR] Successfully extracted text from Image using pytesseract.")
            except ImportError:
                logger.warning("[OCR] pytesseract or PIL not installed. Cannot extract text from Image.")
            except Exception as e:
                logger.warning(f"[OCR] Error extracting text from Image: {e}")
        else:
            logger.warning(f"[OCR] Unsupported file type for OCR: {ext}")

    def extract_details(self) -> Dict[str, Optional[str]]:
        """
        Extracts IFSC, Account Number, and Account Type.
        Returns a dictionary with the extracted values.
        """
        self._extract_text()
        
        details = {
            "ifsc": None,
            "account_number": None,
            "account_type": None
        }

        if not self.raw_text:
            return details

        text = self.raw_text.upper()

        # 1. Extract IFSC Code
        # Usually 4 letters, 1 zero, 6 alphanumeric (e.g. SBIN0001234)
        ifsc_match = re.search(r'\b([A-Z]{4}0[A-Z0-9]{6})\b', text)
        if ifsc_match:
            details["ifsc"] = ifsc_match.group(1)
            logger.info(f"[OCR] Extracted IFSC: {details['ifsc']}")

        # 2. Extract Account Number
        # Usually preceded by A/C, ACC, ACCOUNT NO, etc., followed by 9-18 digits
        ac_match = re.search(r'(?:A/C|ACC|ACCOUNT NO|A/C NO)[^0-9]*([0-9]{9,18})\b', text)
        if ac_match:
            details["account_number"] = ac_match.group(1)
            logger.info(f"[OCR] Extracted Account Number: {details['account_number']}")
        else:
            # Fallback: look for any 9-18 digit number that is not an IFSC or date
            long_num_match = re.search(r'\b([0-9]{9,18})\b', text)
            if long_num_match:
                details["account_number"] = long_num_match.group(1)
                logger.info(f"[OCR] Extracted Account Number (Fallback): {details['account_number']}")

        # 3. Extract Account Type
        if "SAVING" in text or "SB A/C" in text or "S B A/C" in text:
            details["account_type"] = "Savings"
            logger.info("[OCR] Extracted Account Type: Savings")
        elif "CURRENT" in text or "CA A/C" in text or "C A A/C" in text:
            details["account_type"] = "Current"
            logger.info("[OCR] Extracted Account Type: Current")

        return details
