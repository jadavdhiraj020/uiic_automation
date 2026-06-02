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

import logging
import ntpath
import os
import json  # noqa: F401 (mock target in unit tests)
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app.automation.services.document_utils import (
    _compress_pdf_for_upload,
    _compress_image_for_upload,
)

logger = logging.getLogger(__name__)

_SKIP_FILES = {"all_pdf_text.txt", "extracted_documents_data.md"}
_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
_DOC_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".txt",
    ".tiff",
}
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB portal limit


def _join_export_path(folder_path: str, filename: str) -> str:
    """Join report export paths while preserving Windows-style paths on non-Windows hosts."""
    if folder_path and (
        ntpath.splitdrive(folder_path)[0] or folder_path.startswith("\\\\")
    ):
        return ntpath.join(folder_path, filename)
    return os.path.join(folder_path, filename)


def get_doc_mapping_tuple(
    portal_id: str = "uiic",
) -> Tuple[
    Dict[str, List[str]],
    Dict[str, List[str]],
    List[str],
    List[str],
    Dict[str, List[str]],
    List[str],
]:
    """Load doc_mapping.json from app settings and return tuple."""
    from app.utils import load_doc_mapping

    raw = load_doc_mapping(portal_id=portal_id)
    claim_map = raw.get("claim_documents_tab", {})
    assessment_map = raw.get("claim_assessment_tab", {})
    other_slots = raw.get("other_slots", ["Other 1", "Other 2", "Other 3"])
    expected_docs = raw.get("expected_claim_docs", [])
    upload_map = raw.get("document_upload_tab", {})
    # Remove _comment key from upload_map if present
    upload_map = {k: v for k, v in upload_map.items() if not k.startswith("_")}
    main_excel_keywords = raw.get("main_excel_keywords", [])
    return (
        claim_map,
        assessment_map,
        other_slots,
        expected_docs,
        upload_map,
        main_excel_keywords,
    )


def _match_keyword(filename_lower: str, mapping: Dict[str, List[str]]) -> Optional[str]:
    """
    Match filename against keyword mapping.
    Tries longest keywords first so 'veh_front' wins over 'front'.
    For short keywords (<= 3 chars like 'fir', 'rc', 'pan'), requires word boundaries
    to prevent false matches (e.g. 'confirm.pdf' matching 'fir').
    """
    # Create a version of the filename with only alphanumeric chars separated by spaces
    spaced_name = " " + re.sub(r"[^a-z0-9]", " ", filename_lower) + " "

    # Flatten into (keyword, doc_type) and sort by length of keyword
    flattened = []
    for doc_type, keywords in mapping.items():
        for kw in keywords:
            flattened.append((kw, doc_type))

    flattened.sort(key=lambda x: len(x[0]), reverse=True)

    for keyword, doc_type in flattened:
        if len(keyword) <= 3:
            # Strict word boundary match for short keywords
            spaced_kw = " " + re.sub(r"[^a-z0-9]", " ", keyword.lower()) + " "
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
        self.upload_doc_files: Dict[
            str, str
        ] = {}  # For document upload section (DL, RC, Claim Form)
        self.claim_related_files: List[
            str
        ] = []  # Source files going into the merged PDF
        self.claim_related_merged_pdf: Optional[str] = (
            None  # Pre-merged claim_others_documents.pdf path
        )
        self.unknown_files: List[str] = []
        self.skipped_files: List[Tuple[str, str]] = []
        self.expected_docs: List[str] = []
        self.compressed_upload_doc_files: Set[str] = (
            set()
        )  # Keys compressed at scan time (e.g. 'driving_license')
        self.original_upload_doc_paths: Dict[
            str, str
        ] = {}  # key → original path before compression (excluded from claim_related)
        self.temporary_files: List[str] = []
        self.policy_warnings: List[str] = []
        self.policy_events: List[dict] = []
        self.generated_files: List[str] = []
        self.cancelled: bool = False
        self.cancellation_reason: str = ""

    def summary_lines(self) -> List[str]:
        lines = []
        if self.excel_path:
            lines.append(f"Excel: {Path(self.excel_path).name}")
        for key, value in self.claim_doc_files.items():
            lines.append(f"[{key}] -> {Path(value).name}")
        for key, value in self.assessment_files.items():
            lines.append(f"[{key}] -> {Path(value).name}")
        for key, value in self.upload_doc_files.items():
            lines.append(f"[Upload:{key}] -> {Path(value).name}")
        if self.claim_related_merged_pdf:
            lines.append(
                f"[claim_related] -> {Path(self.claim_related_merged_pdf).name} (pre-merged)"
            )
        elif self.claim_related_files:
            lines.append(
                f"[claim_related] -> {len(self.claim_related_files)} file(s) pending merge"
            )
        for file_path in self.unknown_files:
            lines.append(f"Unknown: {Path(file_path).name}")
        for file_path, reason in self.skipped_files:
            lines.append(f"Skipped: {Path(file_path).name} ({reason})")
        return lines


def _extract_sheet_for_reinspection(
    full_path: str, folder_path: str, sheet_index: int
) -> str | None:
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
        ws = None
        temp_wb = None
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
                    logger.info(
                        f"✅ Generated {pdf_path} via win32com worksheet export"
                    )

                    if wb:
                        wb.Close(SaveChanges=False)
                        wb = None
                    ws = None
                    if excel:
                        excel.Quit()
                        excel = None
                    import gc

                    gc.collect()
                    pythoncom.CoUninitialize()
                    return pdf_path
                except Exception as e:
                    logger.warning(f"PDF strategy 1 failed (worksheet export): {e}")
                    attempt_failures.append(f"Strategy 1 error: {e}")

                # Strategy 2: Export workbook after isolating target sheet visibility
                try:
                    logger.info("Reinspection PDF strategy 2: workbook export started")
                    for i in range(1, wb.Worksheets.Count + 1):
                        wb.Worksheets(i).Visible = i == (sheet_index + 1)
                    wb.Worksheets(sheet_index + 1).Select()
                    wb.ExportAsFixedFormat(0, os.path.abspath(pdf_path))
                    logger.info(f"✅ Generated {pdf_path} via win32com workbook export")

                    if wb:
                        wb.Close(SaveChanges=False)
                        wb = None
                    ws = None
                    if excel:
                        excel.Quit()
                        excel = None
                    import gc

                    gc.collect()
                    pythoncom.CoUninitialize()
                    return pdf_path
                except Exception as e:
                    logger.warning(f"PDF strategy 2 failed (workbook export): {e}")
                    attempt_failures.append(f"Strategy 2 error: {e}")

                # Strategy 3: Copy target sheet to temp workbook and export
                try:
                    logger.info(
                        "Reinspection PDF strategy 3: temp workbook export started"
                    )
                    ws.Copy()
                    temp_wb = excel.ActiveWorkbook
                    try:
                        temp_wb.ExportAsFixedFormat(0, os.path.abspath(pdf_path))
                        logger.info(
                            f"✅ Generated {pdf_path} via win32com temp workbook export"
                        )

                        temp_wb.Close(SaveChanges=False)
                        temp_wb = None
                        if wb:
                            wb.Close(SaveChanges=False)
                            wb = None
                        ws = None
                        if excel:
                            excel.Quit()
                            excel = None
                        import gc

                        gc.collect()
                        pythoncom.CoUninitialize()
                        return pdf_path
                    finally:
                        if temp_wb:
                            try:
                                temp_wb.Close(SaveChanges=False)
                            except Exception:
                                pass
                            temp_wb = None
                except Exception as e:
                    logger.warning(f"PDF strategy 3 failed (temp workbook export): {e}")
                    attempt_failures.append(f"Strategy 3 error: {e}")

                logger.warning(
                    "All PDF strategies failed for reinspection report. Falling back to Excel extraction."
                )
            else:
                logger.warning(
                    f"Excel file does not have {sheet_index + 1} sheets. Cannot export PDF."
                )
                attempt_failures.append(
                    f"Workbook has only {wb.Worksheets.Count} sheets"
                )
        finally:
            if temp_wb:
                try:
                    temp_wb.Close(SaveChanges=False)
                except Exception:
                    pass
                temp_wb = None
            if wb:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass
                wb = None
            ws = None
            if excel:
                try:
                    excel.Quit()
                except Exception:
                    pass
                excel = None
            import gc

            gc.collect()
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
            logger.info(
                f"Fallback: Extracting Sheet {sheet_index + 1} ('{target_sheet}') as Excel..."
            )
            for sheet_name in all_sheets:
                if sheet_name != target_sheet:
                    wb.remove(wb[sheet_name])
            wb.save(excel_path)
            logger.warning(
                f"⚠️  Generated {excel_path} (fallback Excel extraction used because PDF generation failed)"
            )
            if attempt_failures:
                logger.warning(
                    "Reinspection PDF generation failure details: %s",
                    " | ".join(attempt_failures),
                )
            return excel_path
    except Exception as e:
        logger.warning(f"openpyxl fallback extraction failed: {e}")
        attempt_failures.append(f"openpyxl fallback error: {e}")

    if attempt_failures:
        logger.warning(
            "Reinspection extraction failed. Attempt details: %s",
            " | ".join(attempt_failures),
        )
    else:
        logger.warning(
            "Reinspection extraction failed with no detailed attempt output."
        )

    return None


def scan_folder(
    folder_path: str,
    portal_id: str = "uiic",
    stop_cb: Optional[callable] = None,
) -> FolderScanResult:
    # 1. Load keywords from doc_mapping.json
    result = FolderScanResult()
    _preexisting_paths: Set[str] = set()
    if os.path.isdir(folder_path):
        try:
            _preexisting_paths = {
                os.path.normcase(os.path.normpath(os.path.join(folder_path, fname)))
                for fname in os.listdir(folder_path)
            }
        except Exception:
            _preexisting_paths = set()

    def _is_cancelled() -> bool:
        try:
            return bool(stop_cb and stop_cb())
        except Exception:
            return False

    def _mark_generated(path: str) -> None:
        if not path:
            return
        norm = os.path.normcase(os.path.normpath(path))
        if norm not in _preexisting_paths and path not in result.generated_files:
            result.generated_files.append(path)

    def _cleanup_generated(reason: str) -> None:
        result.cancelled = True
        result.cancellation_reason = reason
        removed = []
        for path in reversed(result.generated_files):
            norm = os.path.normcase(os.path.normpath(path))
            if norm in _preexisting_paths:
                continue
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    removed.append(path)
                except OSError as exc:
                    logger.warning(
                        "Cancellation cleanup failed for generated file %s: %s",
                        path,
                        exc,
                    )
        if removed:
            result.policy_events.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "event": "scan_generated_files_cleaned",
                    "portal_id": portal_id,
                    "folder_path": os.path.abspath(folder_path),
                    "removed_files": removed,
                    "reason": reason,
                }
            )

    def _cancel_checkpoint(reason: str) -> bool:
        if _is_cancelled():
            _cleanup_generated(reason)
            logger.info("Folder scan cancelled: %s", reason)
            return True
        return False

    if _cancel_checkpoint("before_scan_start"):
        return result
    (
        claim_map,
        assessment_map,
        other_slots,
        expected_docs,
        upload_map,
        main_excel_keywords,
    ) = get_doc_mapping_tuple(portal_id=portal_id)
    result.expected_docs = expected_docs

    if not os.path.isdir(folder_path):
        logger.error("Folder not found: %s", folder_path)
        return result

    # ── Pre-scan: Duplicate 'vehicle' files into 4 copies (Front/Rear/Left/Right)
    import shutil

    _vehicle_source_paths: Set[str] = (
        set()
    )  # Track original vehicle files to exclude from claim_related
    try:
        for fname in sorted(os.listdir(folder_path)):
            if _cancel_checkpoint("before_vehicle_photo_duplication"):
                return result
            if fname in _SKIP_FILES or os.path.isdir(os.path.join(folder_path, fname)):
                continue
            fname_lower = fname.lower()
            if (
                fname_lower.startswith("vehical") or fname_lower.startswith("vehicle")
            ) and "vehicle_photo_" not in fname_lower:
                ext = Path(fname).suffix
                source_path = os.path.join(folder_path, fname)

                # Check if all 4 copies already exist — skip duplication if so
                all_exist = all(
                    os.path.exists(os.path.join(folder_path, f"vehicle_photo_{n}{ext}"))
                    for n in range(1, 5)
                )
                if all_exist:
                    logger.info(
                        "All 4 vehicle_photo copies already exist — skipping duplication for %s",
                        fname,
                    )
                    _vehicle_source_paths.add(os.path.normpath(source_path))
                    continue

                # Create 4 copies (Front, Rear, Left, Right)
                for copy_num in range(1, 5):
                    if _cancel_checkpoint("before_vehicle_photo_copy"):
                        return result
                    new_name = f"vehicle_photo_{copy_num}{ext}"
                    new_path = os.path.join(folder_path, new_name)
                    if os.path.exists(new_path):
                        continue  # Don't overwrite existing copies
                    try:
                        shutil.copy2(source_path, new_path)
                        _mark_generated(new_path)
                        logger.info("Generated %s from %s", new_name, fname)
                    except Exception as e:
                        logger.error("Failed to copy %s to %s: %s", fname, new_name, e)
                _vehicle_source_paths.add(os.path.normpath(source_path))
    except Exception as e:
        logger.error("Error during vehicle photo duplication: %s", e)

    # Prefer a user-provided reinspection PDF, if present, before any Excel extraction.
    user_reinspection_pdf: Optional[str] = None
    reinspection_keywords = assessment_map.get(
        "reinspection_report", []
    ) or upload_map.get("reinspection_report", [])
    for fname in sorted(os.listdir(folder_path)):
        if _cancel_checkpoint("before_reinspection_pdf_scan"):
            return result
        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue
        if Path(fname).suffix.lower() != ".pdf":
            continue
        # Skip previously generated report files to avoid scanner priority collision
        if fname.lower() in (
            "re-inspection report format.pdf",
            "re-inspection report format.xlsx",
        ):
            continue
        fname_lower = fname.lower().replace("-", "_").replace(" ", "_")
        if any(k in fname_lower for k in reinspection_keywords):
            user_reinspection_pdf = full_path
            break

    if user_reinspection_pdf:
        if "reinspection_report" in upload_map:
            result.upload_doc_files["reinspection_report"] = user_reinspection_pdf
            logger.info(
                "Upload doc file [reinspection_report]: %s (user-provided PDF, skipping extraction)",
                Path(user_reinspection_pdf).name,
            )
        else:
            result.assessment_files["reinspection_report"] = user_reinspection_pdf
            logger.info(
                "Assessment file [reinspection_report]: %s (user-provided PDF, skipping extraction)",
                Path(user_reinspection_pdf).name,
            )

    # Collect files starting with "other" for sequential Other 1/2/3 assignment
    other_files: List[str] = []

    # ── Pre-scan for the main data Excel file ───────────────────────────────
    excel_candidates = []
    for fname in sorted(os.listdir(folder_path)):
        if _cancel_checkpoint("before_main_excel_scan"):
            return result
        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue
        ext = Path(fname).suffix.lower()
        if ext not in _EXCEL_EXTENSIONS:
            continue
        if fname in _SKIP_FILES:
            continue
        fname_lower = fname.lower()
        if fname_lower == "claim_others_documents.pdf" or fname_lower.startswith(
            "claim_others_documents_"
        ):
            continue
        if fname_lower in [
            "re-inspection report format.xlsx",
            "re-inspection report format.pdf",
        ]:
            continue

        # Exclude Excels that match an assessment keyword (e.g. reinspection_report, estimate, etc.)
        fname_norm = fname.lower().replace("-", "_").replace(" ", "_")
        assessment_key = _match_keyword(fname_norm, assessment_map)
        if assessment_key:
            continue

        excel_candidates.append(full_path)

    # Now select the main Excel from candidate list using strict keyword priority
    main_excel_path = None
    _main_excel_matched_by_keyword = False

    if excel_candidates:
        if main_excel_keywords:
            # Look for keywords in strict order of user configuration
            for keyword in main_excel_keywords:
                keyword_lower = keyword.lower()
                for cand in excel_candidates:
                    cand_name_lower = Path(cand).name.lower()
                    if keyword_lower in cand_name_lower:
                        main_excel_path = cand
                        _main_excel_matched_by_keyword = True
                        logger.info(
                            "Main Excel matched by keyword '%s': %s",
                            keyword,
                            Path(cand).name,
                        )
                        break
                if main_excel_path:
                    break

            if not main_excel_path:
                logger.warning(
                    "Keywords configured %s but no candidate Excel matched. Skipping Excel processing as requested.",
                    main_excel_keywords,
                )
        else:
            # No keywords configured -> auto-pick the first Excel candidate
            main_excel_path = excel_candidates[0]
            logger.info(
                "No keywords configured. Auto-picked first Excel candidate: %s",
                Path(main_excel_path).name,
            )

    _main_excel_norm = (
        os.path.normcase(os.path.normpath(main_excel_path)) if main_excel_path else None
    )

    for fname in sorted(os.listdir(folder_path)):
        if _cancel_checkpoint("before_document_mapping"):
            return result
        if fname in _SKIP_FILES:
            result.skipped_files.append(
                (os.path.join(folder_path, fname), "Ignored system file")
            )
            continue

        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue

        ext = Path(fname).suffix.lower()
        fname_lower = fname.lower()

        # Skip claim-related PDFs generated by previous automation runs. They
        # must not be treated as unknown files or merged into the next output.
        if fname_lower == "claim_others_documents.pdf" or fname_lower.startswith(
            "claim_others_documents_"
        ):
            result.skipped_files.append(
                (full_path, "Generated claim-related merge output")
            )
            continue

        # ── Handle our generated subset excel/pdf directly ────────────────────────
        if fname_lower in [
            "re-inspection report format.xlsx",
            "re-inspection report format.pdf",
        ]:
            if (
                os.path.exists(full_path)
                and "reinspection_report" not in result.assessment_files
                and "reinspection_report" not in result.upload_doc_files
            ):
                if "reinspection_report" in upload_map:
                    result.upload_doc_files["reinspection_report"] = full_path
                    logger.info(
                        f"Upload doc file [reinspection_report]: {fname} (previously generated)"
                    )
                else:
                    result.assessment_files["reinspection_report"] = full_path
                    logger.info(
                        f"Assessment file [reinspection_report]: {fname} (previously generated)"
                    )
            continue

        # ── Excel file ────────────────────────────────────────────────────────
        if ext in _EXCEL_EXTENSIONS:
            # ── Check if this Excel matches an assessment keyword FIRST ────
            fname_norm = fname.lower().replace("-", "_").replace(" ", "_")
            assessment_key = _match_keyword(fname_norm, assessment_map)
            if assessment_key:
                if assessment_key not in result.assessment_files:
                    result.assessment_files[assessment_key] = full_path
                    logger.info("Assessment file [%s]: %s", assessment_key, fname)
                else:
                    logger.warning(
                        "Duplicate assessment mapping for [%s], keeping first file.",
                        assessment_key,
                    )
                    result.skipped_files.append(
                        (full_path, f"Duplicate assessment mapping [{assessment_key}]")
                    )
                continue

            # ── Otherwise treat as candidate for main Excel ────────────────
            _full_path_norm = os.path.normcase(os.path.normpath(full_path))
            if _main_excel_norm and _full_path_norm == _main_excel_norm:
                result.excel_path = full_path
                logger.info("Excel found (main): %s", fname)

                # ── Auto-extract Sheet 7 for Re-Inspection Report ─────────────
                if (
                    "reinspection_report" in result.assessment_files
                    or "reinspection_report" in result.upload_doc_files
                ):
                    existing_path = result.assessment_files.get(
                        "reinspection_report"
                    ) or result.upload_doc_files.get("reinspection_report")
                    logger.info(
                        "Reinspection report already available (%s); skipping extraction from Excel.",
                        Path(existing_path).name,
                    )
                else:
                    # Try to find an existing generated report first
                    pdf_path = os.path.join(
                        folder_path, "Re-Inspection Report format.pdf"
                    )
                    excel_path = os.path.join(
                        folder_path, "Re-Inspection Report format.xlsx"
                    )
                    spot_path = (
                        pdf_path
                        if os.path.exists(pdf_path)
                        else (excel_path if os.path.exists(excel_path) else None)
                    )

                    if not spot_path:
                        if _cancel_checkpoint("before_reinspection_generation"):
                            return result
                        # User confirmed Sheet 7 (index 6) is the correct target
                        spot_path = _extract_sheet_for_reinspection(
                            full_path, folder_path, sheet_index=6
                        )
                        if spot_path:
                            _mark_generated(spot_path)

                    # If we successfully created/found a report, assign it!
                    if spot_path and os.path.exists(spot_path):
                        if "reinspection_report" in upload_map:
                            result.upload_doc_files["reinspection_report"] = spot_path
                            logger.info(
                                "Upload doc file [reinspection_report]: %s", spot_path
                            )
                        else:
                            result.assessment_files["reinspection_report"] = spot_path
                            logger.info(
                                "Assessment file [reinspection_report]: %s", spot_path
                            )
                    else:
                        logger.warning(
                            "Could not resolve reinspection_report from user PDF, existing generated files, or Excel extraction."
                        )
            else:
                if main_excel_keywords:
                    logger.info(
                        "Skipped Excel file (not the main data Excel): %s", fname
                    )
                    result.skipped_files.append(
                        (
                            full_path,
                            "Multiple Excel files found — not the main data Excel",
                        )
                    )
                else:
                    logger.info("Skipped Excel file (multiple found): %s", fname)
                    result.skipped_files.append(
                        (full_path, "Multiple Excel files found")
                    )
            continue

        # ── Non-document files ────────────────────────────────────────────────
        if ext not in _DOC_EXTENSIONS:
            result.unknown_files.append(full_path)
            continue

        # ── File size info ────────────────────────────────────────────────────
        file_size = os.path.getsize(full_path)
        if file_size > MAX_FILE_BYTES:
            mb = file_size / (1024 * 1024)
            logger.info(
                "Large file (%.1fMB): %s — will compress if mapped as upload doc",
                mb,
                fname,
            )

        # ── Normalise filename: lowercase, hyphens/spaces → underscores ──────
        fname_lower = fname.lower().replace("-", "_").replace(" ", "_")
        stem_lower = Path(fname).stem.lower().replace("-", "_").replace(" ", "_")

        # ── Files starting with "other" → queue for Other 1/2/3 slots ────────
        if stem_lower.startswith("other"):
            other_files.append(full_path)
            continue

        # ── Try Upload Document tab match (DL, RC, Claim Form) ────────────────
        if upload_map:
            upload_key = _match_keyword(fname_lower, upload_map)
            if upload_key:
                if upload_key not in result.upload_doc_files:
                    result.upload_doc_files[upload_key] = full_path
                    logger.info("Upload doc [%s]: %s", upload_key, fname)
                else:
                    logger.info(
                        "Duplicate upload doc mapping for [%s], keeping first file.",
                        upload_key,
                    )
                # Don't skip — file could also match claim/assessment tabs

        # ── Try Assessment tab match first (more specific labels) ─────────────
        assessment_key = _match_keyword(fname_lower, assessment_map)
        if assessment_key:
            if (
                assessment_key in ["assessment_excel", "estimate_excel"]
                and ext not in _EXCEL_EXTENSIONS
            ):
                logger.info(
                    "Skipping non-Excel file %s for [%s].", fname, assessment_key
                )
                # Fall through to claim_map matching below
            else:
                if assessment_key in result.assessment_files:
                    logger.warning(
                        "Duplicate assessment mapping for [%s], keeping first file.",
                        assessment_key,
                    )
                    result.skipped_files.append(
                        (full_path, f"Duplicate assessment mapping [{assessment_key}]")
                    )
                    continue
                result.assessment_files[assessment_key] = full_path
                logger.info("Assessment file [%s]: %s", assessment_key, fname)
                continue

        # ── Try Claim Documents tab match ─────────────────────────────────────
        claim_type = _match_keyword(fname_lower, claim_map)
        if claim_type:
            if claim_type in result.claim_doc_files:
                logger.warning(
                    "Duplicate claim document mapping for [%s], keeping first file.",
                    claim_type,
                )
                result.skipped_files.append(
                    (full_path, f"Duplicate claim doc mapping [{claim_type}]")
                )
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
            logger.warning(
                "No Other slot left for: %s (only %d slots)",
                Path(other_path).name,
                len(other_slots),
            )
            result.skipped_files.append((other_path, "No 'Other' slots left"))

    # Bank proof policy: missing cancelled-cheque/bank proof stays missing.
    # Never substitute invoice or any unrelated document as bank proof.
    cancel_key = next(
        (
            k
            for k in claim_map.keys()
            if "cancel" in k.lower()
            and ("cheque" in k.lower() or "check" in k.lower() or "bank" in k.lower())
        ),
        None,
    )
    if cancel_key and cancel_key not in result.claim_doc_files:
        warning = (
            f"{cancel_key} missing. Invoice fallback is disabled; no substitute "
            "document was generated or mapped as bank proof."
        )
        result.policy_warnings.append(warning)
        policy_event = {
            "timestamp": datetime.now().isoformat(),
            "event": "bank_proof_missing_no_fallback",
            "portal_id": portal_id,
            "folder_path": os.path.abspath(folder_path),
            "missing_document": cancel_key,
            "document_category": "bank_proof",
            "policy_decision": "no_fallback_used",
            "action": "mark_missing_only",
        }
        result.policy_events.append(policy_event)
        logger.warning(warning, extra={"policy_event": policy_event})

    # ── Fallback: Copy Invoice as Work Approval Document if missing ────────────
    work_approval_key = next(
        (
            k
            for k in claim_map.keys()
            if "work approval" in k.lower() or "approval" in k.lower()
        ),
        None,
    )
    if (
        work_approval_key
        and work_approval_key not in result.claim_doc_files
        and "invoice" in result.assessment_files
    ):
        if _cancel_checkpoint("before_work_approval_fallback"):
            return result
        invoice_path = result.assessment_files["invoice"]
        ext = Path(invoice_path).suffix
        work_approval_name = f"work_approval_fallback{ext}"
        work_approval_path = os.path.join(folder_path, work_approval_name)

        try:
            if not os.path.exists(work_approval_path):
                import shutil

                shutil.copy2(invoice_path, work_approval_path)
                _mark_generated(work_approval_path)
            result.claim_doc_files[work_approval_key] = work_approval_path
            logger.info(
                "Generated %s from invoice because Work Approval Document was missing",
                work_approval_name,
            )
        except Exception as e:
            logger.error("Failed to copy invoice to %s: %s", work_approval_name, e)

    # ── Pre-compress mandatory upload files that exceed portal's 1.5 MB limit ─
    # This runs BEFORE automation starts so the UI shows the final file size
    # and the automation directly attaches the ready-to-use compressed file.
    _MANDATORY_LIMIT_BYTES = 1536 * 1024  # 1.5 MB — NIA portal per-file limit
    for _ukey, _upath in list(result.upload_doc_files.items()):
        if _cancel_checkpoint("before_upload_compression"):
            return result
        if not _upath or not os.path.isfile(_upath):
            continue
        _usz = os.path.getsize(_upath)
        if _usz <= _MANDATORY_LIMIT_BYTES:
            continue  # already within limit — skip
        _ext = Path(_upath).suffix.lower()
        _usz_kb = _usz / 1024
        logger.info(
            "Compressing upload doc [%s]: %s (%.0f KB > 1536 KB limit)",
            _ukey,
            Path(_upath).name,
            _usz_kb,
        )
        try:
            _tmp = tempfile.NamedTemporaryFile(
                suffix=_ext
                if _ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp")
                else ".pdf",
                delete=False,
                prefix=f"_mand_{Path(_upath).stem}_",
            )
            _tmp.close()
            _out_path = _tmp.name
            _mark_generated(_out_path)
            if _cancel_checkpoint("before_upload_compression_write"):
                return result
            if _ext == ".pdf":
                _ok = _compress_pdf_for_upload(_upath, _out_path)
            elif _ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp"):
                _ok = _compress_image_for_upload(_upath, _out_path)
            else:
                _ok = False
            if _ok and os.path.isfile(_out_path):
                _comp_kb = os.path.getsize(_out_path) / 1024
                result.original_upload_doc_paths[_ukey] = (
                    _upath  # keep original so it's excluded from claim_related
                )
                result.upload_doc_files[_ukey] = _out_path
                result.compressed_upload_doc_files.add(_ukey)
                result.temporary_files.append(_out_path)
                logger.info(
                    "Compressed [%s]: %.0f KB → %.0f KB — ready for upload.",
                    _ukey,
                    _usz_kb,
                    _comp_kb,
                )
            else:
                logger.warning(
                    "Compression failed for [%s]: %s — will use original (portal alert will be handled).",
                    _ukey,
                    Path(_upath).name,
                )
        except Exception as _ce:
            logger.warning("Compression error for [%s]: %s", _ukey, _ce)

    # ── Compute & pre-merge Claim Related Documents ───────────────────────────
    # ── Step 1: Resolve portal merge capability flag ──────────────────────────
    # Read the portal's feature flag from the registry instead of hardcoding
    # portal names here. This keeps the scanner decoupled from portal business
    # rules — adding a new portal only requires setting the flag in registry.py.
    _portal_requires_merge = False
    try:
        from app.portals.registry import get_portal

        _portal_info = get_portal(portal_id)
        if _portal_info is not None:
            _portal_requires_merge = _portal_info.requires_document_merge
    except Exception:
        pass  # Registry unavailable — safe default: no merge
    logger.info(
        "claim_related merge: portal='%s' requires_document_merge=%s",
        portal_id,
        _portal_requires_merge,
    )

    _skip_fnames = {
        "all_pdf_text.txt",
        "extracted_documents_data.md",
        "re-inspection report format.pdf",
        "re-inspection report format.xlsx",
        "claim_others_documents.pdf",  # skip our own output
        "claim_related_document_merged.pdf",  # skip legacy name
    }
    _uploadable_exts = {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".txt",
    }
    _used_paths: Set[str] = set()
    for _fp in (
        list(result.claim_doc_files.values())
        + list(result.assessment_files.values())
        + list(result.upload_doc_files.values())
        + list(
            result.original_upload_doc_paths.values()
        )  # exclude pre-compression originals too
    ):
        if _fp:
            _used_paths.add(os.path.normpath(_fp))
    _used_paths.update(
        _vehicle_source_paths
    )  # exclude vehicle source (orig before duplication)

    # ── Steps 2 & 3: Discover candidates + pre-merge (portal-gated) ──────────
    # Both candidate discovery and the PDF merge are gated on the portal's
    # requires_document_merge flag. If the portal doesn't need a merged PDF,
    # we skip both steps entirely:
    #   • No candidates collected  → claim_related_files stays empty
    #   • No merge executed        → no temp files, no disk I/O
    #   • No UI row rendered       → DocumentReviewPanel sees nothing to show
    #
    # This is the correct behaviour: collecting candidates and then silently
    # discarding them would leave claim_related_files populated, causing the UI
    # to render a misleading "PENDING" row even though no upload will happen.
    if not _portal_requires_merge:
        logger.info(
            "claim_related: portal '%s' does not require document merge — "
            "skipping candidate discovery and pre-merge.",
            portal_id,
        )
    else:
        # Discover unmatched files that didn't map to any known document slot
        if folder_path and os.path.isdir(folder_path):
            import re as _re

            for _fname in sorted(os.listdir(folder_path)):
                if _cancel_checkpoint("before_claim_related_discovery"):
                    return result
                _full = os.path.join(folder_path, _fname)
                if not os.path.isfile(_full):
                    continue
                _fname_lower = _fname.lower()
                if _fname_lower in _skip_fnames:
                    continue
                if _fname_lower.startswith("claim_others_documents_"):
                    continue
                if _fname.startswith("~$"):
                    continue
                if Path(_fname).suffix.lower() not in _uploadable_exts:
                    continue

                # Skip generated vehicle photo copies (4 identical large files)
                if _re.match(
                    r"^vehicle_photo_[1-4]\.(pdf|jpg|jpeg|png|bmp|gif)$", _fname_lower
                ):
                    continue

                if os.path.normpath(_full) not in _used_paths:
                    result.claim_related_files.append(_full)
                    logger.info("claim_related candidate: %s", _fname)

        # Pre-merge now so UI can show the real filename and size
        if result.claim_related_files and folder_path:
            if _cancel_checkpoint("before_claim_related_premerge"):
                return result
            import time

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            _out = os.path.join(folder_path, f"claim_others_documents_{timestamp}.pdf")
            _mergeable_exts = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"}
            _mergeable = [
                f
                for f in result.claim_related_files
                if Path(f).suffix.lower() in _mergeable_exts
            ]
            logger.info(
                "claim_related: %d candidates, %d mergeable → %s",
                len(result.claim_related_files),
                len(_mergeable),
                [Path(f).name for f in _mergeable],
            )
            if _mergeable:
                if _cancel_checkpoint("before_claim_related_merge_write"):
                    return result
                merged = _merge_claim_related_pdf(_mergeable, _out)
                if merged:
                    _mark_generated(merged)
                    result.claim_related_merged_pdf = merged
                    if os.path.isfile(merged):
                        logger.info(
                            "Pre-merged claim_related -> %s (%.1fMB)",
                            Path(merged).name,
                            os.path.getsize(merged) / (1024 * 1024),
                        )
                    else:
                        logger.warning(
                            "Pre-merge returned missing file path: %s", merged
                        )
                else:
                    logger.warning(
                        "Pre-merge failed; merge will be retried at automation runtime."
                    )
            else:
                logger.info(
                    "claim_related: no mergeable files (all are .doc/.xlsx/.txt) — skipping pre-merge."
                )
        else:
            logger.info(
                "claim_related: no candidate files found or folder_path is None."
            )

    # ── Generate comprehensive scan summary log ──────────────────────────────
    if _cancel_checkpoint("before_scan_summary"):
        return result

    _log_scan_summary(result, claim_map)

    return result


def _merge_claim_related_pdf(
    file_paths: List[str],
    output_path: str,
    max_bytes: int = 15 * 1024 * 1024,
) -> Optional[str]:
    """
    Compatibility wrapper delegating to PdfMergeService.
    """
    from app.automation.services.pdf_merge_service import PdfMergeService, MergeConfig

    config = MergeConfig(max_bytes=max_bytes, label="Pre-merge Claim Related")
    return PdfMergeService.merge(file_paths, output_path, config, log=logger)


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

    # ── Upload document files matched ─────────────────────────────────────────
    if result.upload_doc_files:
        lines.append("")
        lines.append("  📎 Upload Documents (matched):")
        for doc_type, fpath in result.upload_doc_files.items():
            lines.append(f"    ✅ [{doc_type}] → {Path(fpath).name}")

    # ── Missing mandatory documents ───────────────────────────────────────────
    matched_types = set(result.claim_doc_files.keys())
    missing = [d for d in result.expected_docs if d not in matched_types]
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
        lines.append("       chassis, odometer, cheque, caseless, non_caseless, etc.")

    lines.append("═" * 60)
    summary = "\n".join(lines)
    logger.info(summary)
