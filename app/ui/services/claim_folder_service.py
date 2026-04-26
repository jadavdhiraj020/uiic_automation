import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.utils import load_settings


@dataclass
class ClaimFolderProcessResult:
    success: bool
    scan_result: Optional[object]
    claim: Optional[object]
    log_lines: List[str]
    error: str = ""


class ClaimFolderService:
    """Extracts and prepares claim + document data from a selected folder."""

    def __init__(self, config_dir: str):
        self.config_dir = config_dir

    def process_folder(self, folder: str) -> ClaimFolderProcessResult:
        from app.data.excel_reader import read_excel
        from app.data.folder_scanner import _EXPECTED_CLAIM_DOCS, scan_folder

        logs: List[str] = [f"📁 Scanning folder: {folder}"]
        try:
            scan_result = scan_folder(folder)
            claim_docs = scan_result.claim_doc_files
            assess_docs = scan_result.assessment_files

            if claim_docs:
                logs.append("📎 Claim Documents (matched):")
                for doc_type, fpath in claim_docs.items():
                    mb = os.path.getsize(fpath) / (1024 * 1024) if os.path.isfile(fpath) else 0
                    logs.append(f"  ✅ [{doc_type}] → {Path(fpath).name} ({mb:.1f}MB)")
            else:
                logs.append("⚠️  No claim documents matched from folder")

            if assess_docs:
                logs.append("📎 Assessment Files (matched):")
                for doc_type, fpath in assess_docs.items():
                    logs.append(f"  ✅ [{doc_type}] → {Path(fpath).name}")

            matched_types = set(claim_docs.keys())
            missing_docs = [d for d in _EXPECTED_CLAIM_DOCS if d not in matched_types]
            if missing_docs:
                logs.append("⚠️  Missing expected documents:")
                for doc in missing_docs:
                    logs.append(f"  ❌ {doc}")

            if scan_result.skipped_files:
                logs.append("⚠️  Skipped Files:")
                for path, reason in scan_result.skipped_files:
                    logs.append(f"  • {Path(path).name} — {reason}")

            if scan_result.unknown_files:
                logs.append("❓ Unrecognized Files (No Mapping):")
                for path in scan_result.unknown_files:
                    logs.append(f"  • {Path(path).name}")
                logs.append("  ℹ️  Tip: rename files to include keywords like pan, aadhaar, vehicle_photo_1, claim_form, ckyc, csr, etc.")

            if not scan_result.excel_path:
                logs.append("⚠️  No Excel file found in folder!")
                return ClaimFolderProcessResult(False, scan_result, None, logs, error="No Excel file found")

            logs.append(f"📊 Excel: {Path(scan_result.excel_path).name}")
            claim = read_excel(scan_result.excel_path, self.config_dir)
            claim.claim_doc_files = scan_result.claim_doc_files
            claim.assessment_files = scan_result.assessment_files

            self._extract_pdf_invoice_data(scan_result, claim, logs)

            if hasattr(claim, "_excel_logs") and claim._excel_logs:
                logs.append("📌 Excel Data Sources Map:")
                logs.extend(claim._excel_logs)

            if not claim.claim_no:
                logs.append("⚠️  Claim No not found in Excel.")

            return ClaimFolderProcessResult(True, scan_result, claim, logs)
        except Exception as exc:
            logs.append(f"❌ ERROR: Failed to read selected folder: {exc}")
            return ClaimFolderProcessResult(False, None, None, logs, error=str(exc))

    # ── Robust PDF Invoice Extraction Engine ────────────────────────────────

    # Date patterns ordered by specificity (most specific first)
    _DATE_PATTERNS = [
        # DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
        re.compile(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})'),
        # YYYY-MM-DD or YYYY/MM/DD
        re.compile(r'(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})'),
    ]

    @staticmethod
    def _normalise_date(raw: str) -> Optional[str]:
        """Convert any recognized date string to DD/MM/YYYY for the portal."""
        raw = raw.strip().rstrip('.')
        from datetime import datetime
        # Try DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
                     "%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d",
                     "%d %b %Y", "%d %B %Y", "%B %d, %Y",
                     "%b %d, %Y", "%d/%m/%y", "%d-%m-%y"):
            try:
                dt = datetime.strptime(raw, fmt)
                # Reject nonsensical dates (year before 2000 or after 2040)
                if 2000 <= dt.year <= 2040:
                    return dt.strftime("%d/%m/%Y")
            except ValueError:
                continue
        return None

    @staticmethod
    def _clean_invoice_no(raw: str) -> Optional[str]:
        """Clean and validate an extracted invoice number string."""
        # Remove surrounding punctuation, parenthetical suffixes
        val = re.sub(r'\(.*$', '', raw).strip()        # Remove "(Credit)" etc.
        val = val.strip(':;,. \t')
        # Must have at least one alphanumeric character
        if not val or not re.search(r'[A-Za-z0-9]', val):
            return None
        # Reject if it's just a common label word
        if val.lower() in {'no', 'number', 'date', 'time', 'invoice', 'bill',
                           'tax', 'na', 'nil', 'none', 'rs', 'inr', ':', '-'}:
            return None
        return val

    def _extract_pdf_invoice_data(self, scan_result, claim, logs: List[str]) -> None:
        invoice_pdf = scan_result.assessment_files.get("invoice")
        if not invoice_pdf or not os.path.exists(invoice_pdf):
            return

        try:
            import pdfplumber
        except ImportError:
            logs.append("  ⚠️ pdfplumber not installed — cannot extract invoice data")
            return

        settings = load_settings()
        inv_labels = settings.get("pdf_invoice_no_labels",
                                  ["Tax Invoice No.", "Invoice No", "Bill No", "Work shop invoice"])
        date_labels = settings.get("pdf_invoice_date_labels",
                                   ["Invoice Date and Time", "Bill Date", "Invoice Date", "date"])

        logs.append(f"📄 Extracting Workshop Invoice details from PDF: {Path(invoice_pdf).name}")

        ext_inv = None
        ext_date = None

        try:
            with pdfplumber.open(invoice_pdf) as pdf:
                # ── Collect text from ALL pages ──────────────────────────
                all_text = ""
                all_lines: List[str] = []
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text:
                        all_text += page_text + "\n"
                        all_lines.extend(page_text.splitlines())

                if not all_text.strip():
                    # PDF has no extractable text (scanned images)
                    logs.append("  ⚠️ PDF has no extractable text (scanned image?), trying OCR...")
                    ext_inv, ext_date = self._ocr_extract_invoice(invoice_pdf, inv_labels, date_labels, logs)
                else:
                    # ── Strategy 1: Label-based inline extraction ────────
                    ext_inv = self._find_invoice_no(all_text, all_lines, inv_labels)
                    ext_date = self._find_invoice_date(all_text, all_lines, date_labels)

            # ── Apply results ────────────────────────────────────────────
            if ext_inv:
                claim.workshop_invoice_no = ext_inv
                claim._excel_coords["workshop_invoice_no"] = "PDF Source"
                claim._excel_logs.append(f"  📊 workshop_invoice_no: '{ext_inv}' (Source: PDF Source)")
                logs.append(f"  ✅ WS Invoice No (from PDF): {ext_inv}")
            else:
                logs.append("  ⚠️ Invoice No not found in PDF")

            if ext_date:
                claim.workshop_invoice_date = ext_date
                claim._excel_coords["workshop_invoice_date"] = "PDF Source"
                claim._excel_logs.append(f"  📊 workshop_invoice_date: '{ext_date}' (Source: PDF Source)")
                logs.append(f"  ✅ WS Invoice Date (from PDF): {ext_date}")
            else:
                logs.append("  ⚠️ Invoice Date not found in PDF")

        except Exception as exc:
            logs.append(f"  ⚠️ Could not parse invoice PDF: {exc}")

    def _find_invoice_no(self, full_text: str, lines: List[str],
                         labels: List[str]) -> Optional[str]:
        """
        Multi-strategy invoice number extraction.

        Strategy 1: "Label<separator>VALUE" on the same line
        Strategy 2: "Label" on one line, value on the next
        Strategy 3: Regex scan for common invoice number patterns near label
        """
        # Sort labels longest-first so "Tax Invoice No." matches before "Invoice No"
        sorted_labels = sorted(labels, key=len, reverse=True)

        for label in sorted_labels:
            label_esc = re.escape(label)

            # ── Strategy 1: Same-line — Label[.:;]?\s*VALUE ─────────────
            # Handles: "Tax Invoice No.INZ25-01569(Credit)"
            #          "BILL NO : JDB/1336"
            #          "Invoice No: ABC-123"
            pattern = label_esc + r'[.:\s]*\s*([A-Za-z0-9][A-Za-z0-9/\-_. ]{1,40})'
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                val = self._clean_invoice_no(m.group(1))
                if val:
                    return val

            # ── Strategy 2: Next-line — label on line N, value on line N+1 ──
            for i, line in enumerate(lines):
                if re.search(label_esc, line, re.IGNORECASE):
                    # Check if value is on the same line AFTER the label
                    after = re.split(label_esc, line, flags=re.IGNORECASE, maxsplit=1)
                    if len(after) > 1:
                        remainder = after[1].strip().lstrip(':;.- ')
                        inv_m = re.match(r'([A-Za-z0-9][A-Za-z0-9/\-_. ]{1,40})', remainder)
                        if inv_m:
                            val = self._clean_invoice_no(inv_m.group(1))
                            if val:
                                return val
                    # Check next line
                    if i + 1 < len(lines):
                        next_line = lines[i + 1].strip()
                        inv_m = re.match(r'([A-Za-z0-9][A-Za-z0-9/\-_. ]{1,40})', next_line)
                        if inv_m:
                            val = self._clean_invoice_no(inv_m.group(1))
                            if val:
                                return val

        return None

    def _find_invoice_date(self, full_text: str, lines: List[str],
                           labels: List[str]) -> Optional[str]:
        """
        Multi-strategy invoice date extraction.

        Strategy 1: "Label<separator>DD/MM/YYYY" on the same line
        Strategy 2: "Label" on one line, date on the next
        Strategy 3: Find first plausible date anywhere near a label
        """
        sorted_labels = sorted(labels, key=len, reverse=True)

        # Date regex that matches many formats
        date_rx = r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})'

        for label in sorted_labels:
            label_esc = re.escape(label)

            # ── Strategy 1: Same-line extraction ────────────────────────
            # Handles: "Invoice Date and Time 27/01/2026 16:35"
            #          "Date : 16/12/2025"
            #          "Date:27-01-2026"
            pattern = label_esc + r'[.:\s]*\s*' + date_rx
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                normalised = self._normalise_date(m.group(1))
                if normalised:
                    return normalised

            # ── Strategy 2: Next-line — label on line N, date on line N+1 ──
            for i, line in enumerate(lines):
                if re.search(label_esc, line, re.IGNORECASE):
                    # Check same line after label
                    after = re.split(label_esc, line, flags=re.IGNORECASE, maxsplit=1)
                    if len(after) > 1:
                        dm = re.search(date_rx, after[1])
                        if dm:
                            normalised = self._normalise_date(dm.group(1))
                            if normalised:
                                return normalised
                    # Check next line
                    if i + 1 < len(lines):
                        dm = re.search(date_rx, lines[i + 1])
                        if dm:
                            normalised = self._normalise_date(dm.group(1))
                            if normalised:
                                return normalised

        return None

    def _ocr_extract_invoice(self, pdf_path: str, inv_labels: List[str],
                             date_labels: List[str],
                             logs: List[str]) -> tuple:
        """
        OCR fallback for scanned PDFs with no extractable text.
        Uses pdf2image + pytesseract if available, otherwise skips.
        """
        try:
            from pdf2image import convert_from_path
            import pytesseract
        except ImportError:
            logs.append("  ⚠️ OCR libraries (pdf2image/pytesseract) not installed — skipping OCR")
            return None, None

        try:
            images = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=3)
            all_text = ""
            for img in images:
                all_text += pytesseract.image_to_string(img) + "\n"

            if not all_text.strip():
                logs.append("  ⚠️ OCR produced no text from scanned PDF")
                return None, None

            logs.append("  📝 OCR text extracted successfully, searching for invoice data...")
            all_lines = all_text.splitlines()
            ext_inv = self._find_invoice_no(all_text, all_lines, inv_labels)
            ext_date = self._find_invoice_date(all_text, all_lines, date_labels)
            return ext_inv, ext_date
        except Exception as exc:
            logs.append(f"  ⚠️ OCR extraction failed: {exc}")
            return None, None
