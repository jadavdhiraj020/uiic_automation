"""
folder_scanner.py
Scans a user-selected folder and categorises every file into:
  - Excel file (the data source)
  - Claim-document uploads (Claim Documents tab)
  - Assessment uploads (Claim Assessment tab)
  - Unknown / ignored

Uses doc_mapping.json for name-to-type resolution.

UPDATED 2026-04-20:
  - Longest-keyword-first matching (so 'veh_front' wins over 'front')
  - Hyphens and spaces normalised to underscores before matching
  - Files starting with 'other' auto-assigned to Other 1/2/3 slots
  - Max file size check (2MB portal limit)
  - Assessment keywords also use longest-first matching
  - Comprehensive scan summary log for client visibility
"""

import json
import logging
import ntpath
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SKIP_FILES = {"all_pdf_text.txt", "extracted_documents_data.md"}
_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
_DOC_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".doc", ".docx", ".xls", ".xlsx", ".txt", ".tiff",
}
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB portal limit


def _join_export_path(folder_path: str, filename: str) -> str:
    """Join report export paths while preserving Windows-style paths on non-Windows hosts."""
    if folder_path and (ntpath.splitdrive(folder_path)[0] or folder_path.startswith("\\\\")):
        return ntpath.join(folder_path, filename)
    return os.path.join(folder_path, filename)


def get_doc_mapping_tuple() -> Tuple[Dict[str, List[str]], Dict[str, List[str]], List[str]]:
    """Load doc_mapping.json from app settings and return tuple."""
    from app.utils import load_doc_mapping
    raw = load_doc_mapping()
    claim_map = raw.get("claim_documents_tab", {})
    assessment_map = raw.get("claim_assessment_tab", {})
    other_slots = raw.get("other_slots", ["Other 1", "Other 2", "Other 3"])
    return claim_map, assessment_map, other_slots


import re

def _match_keyword(filename_lower: str, mapping: Dict[str, List[str]]) -> Optional[str]:
    """
    Match filename against keyword mapping.
    Tries longest keywords first so 'veh_front' wins over 'front'.
    For short keywords (<= 3 chars like 'fir', 'rc', 'pan'), requires word boundaries
    to prevent false matches (e.g. 'confirm.pdf' matching 'fir').
    """
    # Create a version of the filename with only alphanumeric chars separated by spaces
    spaced_name = " " + re.sub(r'[^a-z0-9]', ' ', filename_lower) + " "

    # Flatten into (keyword, doc_type) and sort by length of keyword
    flattened = []
    for doc_type, keywords in mapping.items():
        for kw in keywords:
            flattened.append((kw, doc_type))

    flattened.sort(key=lambda x: len(x[0]), reverse=True)

    for keyword, doc_type in flattened:
        if len(keyword) <= 3:
            # Strict word boundary match for short keywords
            spaced_kw = " " + re.sub(r'[^a-z0-9]', ' ', keyword.lower()) + " "
            if spaced_kw in spaced_name:
                return doc_type
        else:
            # Normal substring match for longer keywords
            if keyword in filename_lower:
                return doc_type
    return None


class FolderScanResult:
    def __init__(self):
        self.excel_path: Optional[str] = None
        self.claim_doc_files: Dict[str, str] = {}
        self.assessment_files: Dict[str, str] = {}
        self.unknown_files: List[str] = []
        self.skipped_files: List[Tuple[str, str]] = []

    def summary_lines(self) -> List[str]:
        lines = []
        if self.excel_path:
            lines.append(f"Excel: {Path(self.excel_path).name}")
        for key, value in self.claim_doc_files.items():
            lines.append(f"[{key}] -> {Path(value).name}")
        for key, value in self.assessment_files.items():
            lines.append(f"[{key}] -> {Path(value).name}")
        for file_path in self.unknown_files:
            lines.append(f"Unknown: {Path(file_path).name}")
        for file_path, reason in self.skipped_files:
            lines.append(f"Skipped: {Path(file_path).name} ({reason})")
        return lines


def _extract_sheet_for_reinspection(full_path: str, folder_path: str, sheet_index: int) -> str | None:
    """
    Attempts to export a specific Excel sheet to PDF using multiple native
    MS Excel COM strategies. If all PDF strategies fail, falls back to
    openpyxl to extract the sheet as a new Excel file.
    Returns the path to the generated file, or None if extraction failed entirely.
    """
    pdf_path = _join_export_path(folder_path, "Re-Inspection Report format.pdf")
    excel_path = _join_export_path(folder_path, "Re-Inspection Report format.xlsx")
    attempt_failures: List[str] = []

    # Clean up existing generated files to avoid stale data
    for p in (pdf_path, excel_path):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    # 1. PDF Strategies via win32com
    try:
        import win32com.client
        import pythoncom
        pythoncom.CoInitialize()

        excel = None
        wb = None
        try:
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False

            wb = excel.Workbooks.Open(os.path.abspath(full_path), ReadOnly=True)
            if wb.Worksheets.Count >= sheet_index + 1:
                ws = wb.Worksheets(sheet_index + 1)  # COM uses 1-based indexing

                # Strategy 1: Export selected worksheet directly
                try:
                    logger.info("Reinspection PDF strategy 1: worksheet export started")
                    ws.Select()
                    # 0 = xlTypePDF
                    ws.ExportAsFixedFormat(0, os.path.abspath(pdf_path))
                    logger.info(f"✅ Generated {pdf_path} via win32com worksheet export")
                    return pdf_path
                except Exception as e:
                    logger.warning(f"PDF strategy 1 failed (worksheet export): {e}")
                    attempt_failures.append(f"Strategy 1 error: {e}")

                # Strategy 2: Export workbook after isolating target sheet visibility
                try:
                    logger.info("Reinspection PDF strategy 2: workbook export started")
                    for i in range(1, wb.Worksheets.Count + 1):
                        wb.Worksheets(i).Visible = (i == (sheet_index + 1))
                    wb.Worksheets(sheet_index + 1).Select()
                    wb.ExportAsFixedFormat(0, os.path.abspath(pdf_path))
                    logger.info(f"✅ Generated {pdf_path} via win32com workbook export")
                    return pdf_path
                except Exception as e:
                    logger.warning(f"PDF strategy 2 failed (workbook export): {e}")
                    attempt_failures.append(f"Strategy 2 error: {e}")

                # Strategy 3: Copy target sheet to temp workbook and export
                try:
                    logger.info("Reinspection PDF strategy 3: temp workbook export started")
                    ws.Copy()
                    temp_wb = excel.ActiveWorkbook
                    try:
                        temp_wb.ExportAsFixedFormat(0, os.path.abspath(pdf_path))
                        logger.info(f"✅ Generated {pdf_path} via win32com temp workbook export")
                        return pdf_path
                    finally:
                        temp_wb.Close(SaveChanges=False)
                except Exception as e:
                    logger.warning(f"PDF strategy 3 failed (temp workbook export): {e}")
                    attempt_failures.append(f"Strategy 3 error: {e}")

                logger.warning("All PDF strategies failed for reinspection report. Falling back to Excel extraction.")
            else:
                logger.warning(f"Excel file does not have {sheet_index + 1} sheets. Cannot export PDF.")
                attempt_failures.append(f"Workbook has only {wb.Worksheets.Count} sheets")
        finally:
            if wb:
                wb.Close(SaveChanges=False)
            if excel:
                excel.Quit()
            pythoncom.CoUninitialize()
    except ImportError:
        logger.warning("win32com not installed, skipping PDF export.")
        attempt_failures.append("win32com/pythoncom not installed")
    except Exception as e:
        logger.warning(f"win32com PDF export failed (fallback to Excel): {e}")
        attempt_failures.append(f"win32com setup/runtime error: {e}")

    # 2. Fallback Strategy: Extract to XLSX via openpyxl
    try:
        import openpyxl
        wb = openpyxl.load_workbook(full_path, data_only=True)
        all_sheets = wb.sheetnames
        if len(all_sheets) > sheet_index:
            target_sheet = all_sheets[sheet_index]
            logger.info(f"Fallback: Extracting Sheet {sheet_index + 1} ('{target_sheet}') as Excel...")
            for sheet_name in all_sheets:
                if sheet_name != target_sheet:
                    wb.remove(wb[sheet_name])
            wb.save(excel_path)
            logger.warning(f"⚠️  Generated {excel_path} (fallback Excel extraction used because PDF generation failed)")
            if attempt_failures:
                logger.warning("Reinspection PDF generation failure details: %s", " | ".join(attempt_failures))
            return excel_path
    except Exception as e:
        logger.warning(f"openpyxl fallback extraction failed: {e}")
        attempt_failures.append(f"openpyxl fallback error: {e}")

    if attempt_failures:
        logger.warning("Reinspection extraction failed. Attempt details: %s", " | ".join(attempt_failures))
    else:
        logger.warning("Reinspection extraction failed with no detailed attempt output.")

    return None


def scan_folder(folder_path: str) -> FolderScanResult:
    result = FolderScanResult()
    claim_map, assessment_map, other_slots = get_doc_mapping_tuple()

    if not os.path.isdir(folder_path):
        logger.error("Folder not found: %s", folder_path)
        return result

    # ── Pre-scan: Duplicate 'vehicle' files into 4 copies (Front/Rear/Left/Right)
    import shutil
    try:
        for fname in sorted(os.listdir(folder_path)):
            if fname in _SKIP_FILES or os.path.isdir(os.path.join(folder_path, fname)):
                continue
            fname_lower = fname.lower()
            if (fname_lower.startswith("vehical") or fname_lower.startswith("vehicle")) and "vehicle_photo_" not in fname_lower:
                ext = Path(fname).suffix
                source_path = os.path.join(folder_path, fname)

                # Check if all 4 copies already exist — skip duplication if so
                all_exist = all(
                    os.path.exists(os.path.join(folder_path, f"vehicle_photo_{n}{ext}"))
                    for n in range(1, 5)
                )
                if all_exist:
                    logger.info("All 4 vehicle_photo copies already exist — skipping duplication for %s", fname)
                    continue

                # Create 4 copies (Front, Rear, Left, Right)
                for copy_num in range(1, 5):
                    new_name = f"vehicle_photo_{copy_num}{ext}"
                    new_path = os.path.join(folder_path, new_name)
                    if os.path.exists(new_path):
                        continue  # Don't overwrite existing copies
                    try:
                        shutil.copy2(source_path, new_path)
                        logger.info("Generated %s from %s", new_name, fname)
                    except Exception as e:
                        logger.error("Failed to copy %s to %s: %s", fname, new_name, e)
    except Exception as e:
        logger.error("Error during vehicle photo duplication: %s", e)

    # Prefer a user-provided reinspection PDF, if present, before any Excel extraction.
    user_reinspection_pdf: Optional[str] = None
    reinspection_keywords = assessment_map.get("reinspection_report", [])
    for fname in sorted(os.listdir(folder_path)):
        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue
        if Path(fname).suffix.lower() != ".pdf":
            continue
        fname_lower = fname.lower().replace("-", "_").replace(" ", "_")
        if any(k in fname_lower for k in reinspection_keywords):
            user_reinspection_pdf = full_path
            break

    if user_reinspection_pdf:
        result.assessment_files["reinspection_report"] = user_reinspection_pdf
        logger.info(
            "Assessment file [reinspection_report]: %s (user-provided PDF, skipping extraction)",
            Path(user_reinspection_pdf).name,
        )

    # Collect files starting with "other" for sequential Other 1/2/3 assignment
    other_files: List[str] = []

    for fname in sorted(os.listdir(folder_path)):
        if fname in _SKIP_FILES:
            result.skipped_files.append((os.path.join(folder_path, fname), "Ignored system file"))
            continue

        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue

        ext = Path(fname).suffix.lower()
        fname_lower = fname.lower()

        # ── Handle our generated subset excel/pdf directly ────────────────────────
        if fname_lower in ["re-inspection report format.xlsx", "re-inspection report format.pdf"]:
            if os.path.exists(full_path) and "reinspection_report" not in result.assessment_files:
                result.assessment_files["reinspection_report"] = full_path
                logger.info(f"Assessment file [reinspection_report]: {fname} (previously generated)")
            continue

        # ── Excel file ────────────────────────────────────────────────────────
        if ext in _EXCEL_EXTENSIONS:
            if result.excel_path is None:
                result.excel_path = full_path
                logger.info("Excel found: %s", fname)

                # ── Auto-extract Sheet 7 for Re-Inspection Report ─────────────
                if "reinspection_report" in result.assessment_files:
                    logger.info(
                        "Reinspection report already available (%s); skipping extraction from Excel.",
                        Path(result.assessment_files["reinspection_report"]).name,
                    )
                else:
                    # Try to find an existing generated report first
                    pdf_path = os.path.join(folder_path, "Re-Inspection Report format.pdf")
                    excel_path = os.path.join(folder_path, "Re-Inspection Report format.xlsx")
                    spot_path = pdf_path if os.path.exists(pdf_path) else (excel_path if os.path.exists(excel_path) else None)

                    if not spot_path:
                        # User confirmed Sheet 7 (index 6) is the correct target
                        spot_path = _extract_sheet_for_reinspection(full_path, folder_path, sheet_index=6)

                    # If we successfully created/found a report, assign it!
                    if spot_path and os.path.exists(spot_path):
                        result.assessment_files["reinspection_report"] = spot_path
                        logger.info("Assessment file [reinspection_report]: %s", spot_path)
                    else:
                        logger.warning(
                            "Could not resolve reinspection_report from user PDF, existing generated files, or Excel extraction."
                        )
            else:
                logger.warning("Multiple Excel files found. Keeping first: %s", result.excel_path)
                result.skipped_files.append((full_path, "Multiple Excel files found"))
            continue

        # ── Non-document files ────────────────────────────────────────────────
        if ext not in _DOC_EXTENSIONS:
            result.unknown_files.append(full_path)
            continue

        # ── File size info (no skip — portal accepts >2MB with alert popup) ───
        file_size = os.path.getsize(full_path)
        if file_size > MAX_FILE_BYTES:
            mb = file_size / (1024 * 1024)
            logger.info("Large file (%.1fMB): %s — portal will show size alert", mb, fname)

        # ── Normalise filename: lowercase, hyphens/spaces → underscores ──────
        fname_lower = fname.lower().replace("-", "_").replace(" ", "_")
        stem_lower = Path(fname).stem.lower().replace("-", "_").replace(" ", "_")

        # ── Files starting with "other" → queue for Other 1/2/3 slots ────────
        if stem_lower.startswith("other"):
            other_files.append(full_path)
            continue

        # ── Try Assessment tab match first (more specific labels) ─────────────
        assessment_key = _match_keyword(fname_lower, assessment_map)
        if assessment_key:
            if assessment_key in result.assessment_files:
                logger.warning("Duplicate assessment mapping for [%s], keeping first file.", assessment_key)
                result.skipped_files.append((full_path, f"Duplicate assessment mapping [{assessment_key}]"))
                continue
            result.assessment_files[assessment_key] = full_path
            logger.info("Assessment file [%s]: %s", assessment_key, fname)
            continue

        # ── Try Claim Documents tab match ─────────────────────────────────────
        claim_type = _match_keyword(fname_lower, claim_map)
        if claim_type:
            if claim_type in result.claim_doc_files:
                logger.warning("Duplicate claim document mapping for [%s], keeping first file.", claim_type)
                result.skipped_files.append((full_path, f"Duplicate claim doc mapping [{claim_type}]"))
                continue
            result.claim_doc_files[claim_type] = full_path
            logger.info("Claim doc [%s]: %s", claim_type, fname)
            continue

        # ── No match ──────────────────────────────────────────────────────────
        result.unknown_files.append(full_path)
        logger.warning("Unrecognised file (no mapping): %s", fname)

    # ── Assign "other" files to Other 1/2/3 slots sequentially ────────────────
    for idx, other_path in enumerate(other_files):
        if idx < len(other_slots):
            slot_label = other_slots[idx]
            result.claim_doc_files[slot_label] = other_path
            logger.info("Claim doc [%s]: %s", slot_label, Path(other_path).name)
        else:
            logger.warning("No Other slot left for: %s (only %d slots)", Path(other_path).name, len(other_slots))
            result.skipped_files.append((other_path, "No 'Other' slots left"))

    # ── Fallback: Copy Invoice as Cancelled Cheque if missing ──────────────────
    if "Cancelled Cheque Or Bank Details" not in result.claim_doc_files and "invoice" in result.assessment_files:
        invoice_path = result.assessment_files["invoice"]
        ext = Path(invoice_path).suffix
        cancel_check_name = f"cancel_check_fallback{ext}"
        cancel_check_path = os.path.join(folder_path, cancel_check_name)
        
        try:
            if not os.path.exists(cancel_check_path):
                import shutil
                shutil.copy2(invoice_path, cancel_check_path)
            result.claim_doc_files["Cancelled Cheque Or Bank Details"] = cancel_check_path
            logger.info("Generated %s from invoice because cancelled cheque was missing", cancel_check_name)
        except Exception as e:
            logger.error("Failed to copy invoice to %s: %s", cancel_check_name, e)

    # ── Generate comprehensive scan summary log ──────────────────────────────
    _log_scan_summary(result, claim_map)

    return result


# ── Expected mandatory portal documents ──────────────────────────────────────
_EXPECTED_CLAIM_DOCS = [
    "PAN Card",
    "Aadhaar Card",
    "Cancelled Cheque Or Bank Details",
    "Driving License",
    "RC Book",
    "Vehicle Photograph (Front)",
    "Vehicle Photograph(Rear)",
    "Vehicle Photograph (Left)",
    "Vehicle Photograph (Right)",
    "Claim Form",
    "CKYC Form",
    "CSR and Certificate",
    "Discharge or Satisfaction Voucher",
]


def _log_scan_summary(result: FolderScanResult, claim_map: Dict[str, str]) -> None:
    """
    Generate a detailed summary of the folder scan results.
    This helps the client understand exactly what was found, what's missing,
    and what couldn't be matched.
    """
    lines = []
    lines.append("")
    lines.append("═" * 60)
    lines.append("📋 DOCUMENT SCAN SUMMARY")
    lines.append("═" * 60)

    # ── Excel ─────────────────────────────────────────────────────────────────
    if result.excel_path:
        lines.append(f"  ✅ Excel: {Path(result.excel_path).name}")
    else:
        lines.append("  ❌ Excel: NOT FOUND — data extraction will fail")

    # ── Claim Documents matched ───────────────────────────────────────────────
    lines.append("")
    lines.append("  📎 Claim Documents (matched):")
    if result.claim_doc_files:
        for doc_type, fpath in result.claim_doc_files.items():
            mb = os.path.getsize(fpath) / (1024 * 1024) if os.path.isfile(fpath) else 0
            lines.append(f"    ✅ [{doc_type}] → {Path(fpath).name} ({mb:.1f}MB)")
    else:
        lines.append("    ⚠️  No claim documents matched from folder")

    # ── Assessment files matched ──────────────────────────────────────────────
    lines.append("")
    lines.append("  📎 Assessment Files (matched):")
    if result.assessment_files:
        for doc_type, fpath in result.assessment_files.items():
            lines.append(f"    ✅ [{doc_type}] → {Path(fpath).name}")
    else:
        lines.append("    ⚠️  No assessment files matched from folder")

    # ── Missing mandatory documents ───────────────────────────────────────────
    matched_types = set(result.claim_doc_files.keys())
    missing = [d for d in _EXPECTED_CLAIM_DOCS if d not in matched_types]
    if missing:
        lines.append("")
        lines.append("  ⚠️  Missing expected documents (not found in folder):")
        for doc in missing:
            lines.append(f"    ❌ {doc}")

    # ── Skipped files ─────────────────────────────────────────────────────────
    if result.skipped_files:
        lines.append("")
        lines.append("  ⏭️  Skipped files:")
        for fpath, reason in result.skipped_files:
            lines.append(f"    ⚠️  {Path(fpath).name} — {reason}")

    # ── Unknown / unmatched files ─────────────────────────────────────────────
    if result.unknown_files:
        lines.append("")
        lines.append("  ❓ Unrecognised files (no mapping matched):")
        for fpath in result.unknown_files:
            lines.append(f"    ❓ {Path(fpath).name}")
        lines.append("    ℹ️  Tip: rename files to include keywords like")
        lines.append("       pan, aadhaar, vehicle_photo_1, claim_form, ckyc, csr, etc.")

    lines.append("═" * 60)
    summary = "\n".join(lines)
    logger.info(summary)
