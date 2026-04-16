"""
folder_scanner.py
Scans a user-selected folder and categorises every file into:
  - Excel file (the data source)
  - Claim-document uploads (Claim Documents tab)
  - Assessment uploads (Claim Assessment tab)
  - Unknown / ignored
Uses doc_mapping.json for name-to-type resolution.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SKIP_FILES = {"all_pdf_text.txt", "extracted_documents_data.md"}
_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}
_DOC_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff"}


def load_doc_mapping(config_dir: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    path = os.path.join(config_dir, "doc_mapping.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get("claim_documents_tab", {}), raw.get("claim_assessment_tab", {})


def _match_keyword(filename_lower: str, mapping: Dict[str, str]) -> Optional[str]:
    for keyword, doc_type in mapping.items():
        if keyword in filename_lower:
            return doc_type
    return None


class FolderScanResult:
    def __init__(self):
        self.excel_path: Optional[str] = None
        self.claim_doc_files: Dict[str, str] = {}
        self.assessment_files: Dict[str, str] = {}
        self.unknown_files: List[str] = []
        self.skipped_files: List[str] = []

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
        return lines


def scan_folder(folder_path: str, config_dir: str) -> FolderScanResult:
    result = FolderScanResult()
    claim_map, assessment_map = load_doc_mapping(config_dir)

    if not os.path.isdir(folder_path):
        logger.error("Folder not found: %s", folder_path)
        return result

    for fname in sorted(os.listdir(folder_path)):
        if fname in _SKIP_FILES:
            result.skipped_files.append(fname)
            continue

        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue

        ext = Path(fname).suffix.lower()
        fname_lower = fname.lower().replace("-", "_").replace(" ", "_")

        if ext in _EXCEL_EXTENSIONS:
            if result.excel_path is None:
                result.excel_path = full_path
                logger.info("Excel found: %s", fname)
            else:
                logger.warning("Multiple Excel files found. Keeping first: %s", result.excel_path)
                result.skipped_files.append(full_path)
            continue

        if ext not in _DOC_EXTENSIONS:
            result.unknown_files.append(full_path)
            continue

        assessment_key = _match_keyword(fname_lower, assessment_map)
        if assessment_key:
            if assessment_key in result.assessment_files:
                logger.warning("Duplicate assessment mapping for [%s], keeping first file.", assessment_key)
                result.skipped_files.append(full_path)
                continue
            result.assessment_files[assessment_key] = full_path
            logger.info("Assessment file [%s]: %s", assessment_key, fname)
            continue

        claim_type = _match_keyword(fname_lower, claim_map)
        if claim_type:
            if claim_type in result.claim_doc_files:
                logger.warning("Duplicate claim document mapping for [%s], keeping first file.", claim_type)
                result.skipped_files.append(full_path)
                continue
            result.claim_doc_files[claim_type] = full_path
            logger.info("Claim doc [%s]: %s", claim_type, fname)
            continue

        result.unknown_files.append(full_path)
        logger.warning("Unrecognised file (no mapping): %s", fname)

    return result
