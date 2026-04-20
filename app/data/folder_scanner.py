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
"""

import json
import logging
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


def load_doc_mapping(config_dir: str) -> Tuple[Dict[str, str], Dict[str, str], List[str]]:
    """Load doc_mapping.json. Returns (claim_map, assessment_map, other_slots)."""
    path = os.path.join(config_dir, "doc_mapping.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    claim_map = raw.get("claim_documents_tab", {})
    assessment_map = raw.get("claim_assessment_tab", {})
    other_slots = raw.get("other_slots", ["Other 1", "Other 2", "Other 3"])
    return claim_map, assessment_map, other_slots


def _match_keyword(filename_lower: str, mapping: Dict[str, str]) -> Optional[str]:
    """
    Match filename against keyword mapping.
    Tries longest keywords first so 'veh_front' wins over 'front'.
    Returns the mapped doc_type value, or None.
    """
    for keyword in sorted(mapping.keys(), key=len, reverse=True):
        if keyword in filename_lower:
            return mapping[keyword]
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
    claim_map, assessment_map, other_slots = load_doc_mapping(config_dir)

    if not os.path.isdir(folder_path):
        logger.error("Folder not found: %s", folder_path)
        return result

    # Collect files starting with "other" for sequential Other 1/2/3 assignment
    other_files: List[str] = []

    for fname in sorted(os.listdir(folder_path)):
        if fname in _SKIP_FILES:
            result.skipped_files.append(fname)
            continue

        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue

        ext = Path(fname).suffix.lower()

        # ── Excel file ────────────────────────────────────────────────────────
        if ext in _EXCEL_EXTENSIONS:
            if result.excel_path is None:
                result.excel_path = full_path
                logger.info("Excel found: %s", fname)
            else:
                logger.warning("Multiple Excel files found. Keeping first: %s", result.excel_path)
                result.skipped_files.append(full_path)
            continue

        # ── Non-document files ────────────────────────────────────────────────
        if ext not in _DOC_EXTENSIONS:
            result.unknown_files.append(full_path)
            continue

        # ── File size check ───────────────────────────────────────────────────
        file_size = os.path.getsize(full_path)
        if file_size > MAX_FILE_BYTES:
            mb = file_size / (1024 * 1024)
            logger.warning("File too large (%.1fMB > 2MB), skipping: %s", mb, fname)
            result.skipped_files.append(full_path)
            continue

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
                result.skipped_files.append(full_path)
                continue
            result.assessment_files[assessment_key] = full_path
            logger.info("Assessment file [%s]: %s", assessment_key, fname)
            continue

        # ── Try Claim Documents tab match ─────────────────────────────────────
        claim_type = _match_keyword(fname_lower, claim_map)
        if claim_type:
            if claim_type in result.claim_doc_files:
                logger.warning("Duplicate claim document mapping for [%s], keeping first file.", claim_type)
                result.skipped_files.append(full_path)
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
            result.skipped_files.append(other_path)

    return result
