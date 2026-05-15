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

    def _extract_text(self, log=None):
        """Extract text from the document (PDF or Image)."""
        if not self.doc_path or not os.path.exists(self.doc_path):
            msg = f"Document not found: {self.doc_path}"
            if isinstance(log, AutomationLogger):
                log.error(msg)
            else:
                logger.warning(f"[OCR] {msg}")
            return

        ext = os.path.splitext(self.doc_path)[1].lower()
        fname = os.path.basename(self.doc_path)
        
        if ext == ".pdf":
            try:
                import pdfplumber
                with pdfplumber.open(self.doc_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            self.raw_text += text + "\n"
                
                msg = f"Extracted text from PDF: {fname}"
                if isinstance(log, AutomationLogger):
                    log.info(msg)
                else:
                    logger.info(f"[OCR] {msg}")
            except ImportError:
                msg = "pdfplumber not installed. Cannot process PDF."
                if isinstance(log, AutomationLogger):
                    log.warning(msg)
                else:
                    logger.warning(f"[OCR] {msg}")
            except Exception as e:
                msg = f"PDF extraction error: {str(e)[:100]}"
                if isinstance(log, AutomationLogger):
                    log.error(msg)
                else:
                    logger.warning(f"[OCR] {msg}")
        elif ext in [".jpg", ".jpeg", ".png"]:
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(self.doc_path)
                self.raw_text = pytesseract.image_to_string(img)
                
                msg = f"Extracted text from image: {fname}"
                if isinstance(log, AutomationLogger):
                    log.info(msg)
                else:
                    logger.info(f"[OCR] {msg}")
            except ImportError:
                msg = "pytesseract/PIL not installed. Cannot process image."
                if isinstance(log, AutomationLogger):
                    log.warning(msg)
                else:
                    logger.warning(f"[OCR] {msg}")
            except Exception as e:
                msg = f"Image extraction error: {str(e)[:100]}"
                if isinstance(log, AutomationLogger):
                    log.error(msg)
                else:
                    logger.warning(f"[OCR] {msg}")
        else:
            msg = f"Unsupported file type: {ext}"
            if isinstance(log, AutomationLogger):
                log.warning(msg)
            else:
                logger.warning(f"[OCR] {msg}")

    def extract_details(self, log=None) -> Dict[str, Optional[str]]:
        """
        Extracts IFSC, Account Number, and Account Type.
        Returns a dictionary with the extracted values.
        """
        self._extract_text(log)
        
        details = {
            "ifsc": None,
            "account_number": None,
            "account_type": None
        }

        if not self.raw_text:
            return details

        text = self.raw_text.upper()

        # 1. Extract IFSC Code
        ifsc_match = re.search(r'\b([A-Z]{4}0[A-Z0-9]{6})\b', text)
        if ifsc_match:
            details["ifsc"] = ifsc_match.group(1)
            if isinstance(log, AutomationLogger):
                log.info(f"IFSC detected: {details['ifsc']}")
            else:
                logger.info(f"[OCR] Extracted IFSC: {details['ifsc']}")

        # 2. Extract Account Number
        ac_match = re.search(r'(?:A/C|ACC|ACCOUNT NO|A/C NO)[^0-9]*([0-9]{9,18})\b', text)
        if ac_match:
            details["account_number"] = ac_match.group(1)
            if isinstance(log, AutomationLogger):
                log.info(f"Account No detected: {details['account_number']}")
            else:
                logger.info(f"[OCR] Extracted Account Number: {details['account_number']}")
        else:
            # Fallback
            long_num_match = re.search(r'\b([0-9]{9,18})\b', text)
            if long_num_match:
                details["account_number"] = long_num_match.group(1)
                if isinstance(log, AutomationLogger):
                    log.info(f"Account No detected (fallback): {details['account_number']}")
                else:
                    logger.info(f"[OCR] Extracted Account Number (Fallback): {details['account_number']}")

        # 3. Extract Account Type
        if "SAVING" in text or "SB A/C" in text or "S B A/C" in text:
            details["account_type"] = "Savings"
        elif "CURRENT" in text or "CA A/C" in text or "C A A/C" in text:
            details["account_type"] = "Current"
        
        if details["account_type"]:
            if isinstance(log, AutomationLogger):
                log.info(f"Account type: {details['account_type']}")
            else:
                logger.info(f"[OCR] Extracted Account Type: {details['account_type']}")

        return details
