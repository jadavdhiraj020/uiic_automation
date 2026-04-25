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

    def _extract_pdf_invoice_data(self, scan_result, claim, logs: List[str]) -> None:
        invoice_pdf = scan_result.assessment_files.get("invoice")
        if not invoice_pdf or not os.path.exists(invoice_pdf):
            return

        try:
            import pdfplumber

            logs.append("📄 Extracting Workshop Invoice details from PDF...")
            with pdfplumber.open(invoice_pdf) as pdf:
                text = pdf.pages[0].extract_text()
                if not text:
                    return

                settings = load_settings()
                inv_labels = settings.get("pdf_invoice_no_labels", ["Tax Invoice No.", "Invoice No", "Bill No"])
                date_labels = settings.get("pdf_invoice_date_labels", ["Invoice Date and Time", "Bill Date", "Invoice Date"])

                inv_match = None
                for label in inv_labels:
                    pattern = re.escape(label) + r"(.*?)\("
                    inv_match = re.search(pattern, text, re.IGNORECASE)
                    if inv_match:
                        break
                    pattern = re.escape(label) + r"?\s*([A-Za-z0-9-]+)"
                    inv_match = re.search(pattern, text, re.IGNORECASE)
                    if inv_match:
                        break

                date_match = None
                for label in date_labels:
                    pattern = re.escape(label) + r"\s*(\d{2}/\d{2}/\d{4})"
                    date_match = re.search(pattern, text, re.IGNORECASE)
                    if date_match:
                        break

                if inv_match:
                    ext_inv = inv_match.group(1).strip()
                    claim.workshop_invoice_no = ext_inv
                    claim._excel_coords["workshop_invoice_no"] = "PDF Source"
                    logs.append(f"  ✅ WS Invoice No (from PDF): {ext_inv}")

                if date_match:
                    ext_date = date_match.group(1).strip()
                    claim.workshop_invoice_date = ext_date
                    claim._excel_coords["workshop_invoice_date"] = "PDF Source"
                    logs.append(f"  ✅ WS Invoice Date (from PDF): {ext_date}")
        except Exception as exc:
            logs.append(f"  ⚠️ Could not parse invoice PDF: {exc}")
