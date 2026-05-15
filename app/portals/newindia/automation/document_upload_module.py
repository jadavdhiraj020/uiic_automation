"""
document_upload_module.py — Phase 9: Document Upload Section Automation
New India Assurance portal.

Handles:
  1. Skip "Uploaded Documents" section (informational only)
  2. Open "Upload New Documents" accordion
  3. Upload mandatory documents one-by-one:
       - Driving License
       - Registration Certificate
       - Claim Form
       - Claim Related Documents (merged remaining files as single PDF)
  4. Skip "Non-Mandatory Documents" section
  5. Skip "Reminder to Insured" section

IMPORTANT:
  - Files are only ATTACHED (via Browse button), NOT submitted.
  - The user will manually click Upload on the live website.
  - PDF merge respects 15MB max size limit.
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from playwright.async_api import Page

from app.data.data_model import ClaimData
from app.portals.newindia.automation.ui_utils import (
    select_dropdown_with_delay,
    upload_file_via_input,
)
from app.automation.automation_logger import AutomationLogger, _ts

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_MERGED_PDF_BYTES = 15 * 1024 * 1024  # 15 MB portal limit

# Maps our internal keys → portal dropdown option values
_UPLOAD_DOC_TYPE_MAP = {
    "driving_license":          "DRIVING LICENSE",
    "registration_certificate": "REGISTRATION CERTIFICATE",
    "claim_form":               "CLAIM FORM",
    "claim_related":            "CLAIM RELATED DOCUMENTS",
}


# ══════════════════════════════════════════════════════════════════════════════
# PDF MERGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_all_folder_files(data: ClaimData) -> List[str]:
    """
    Collect ALL uploadable file paths from the scan results.
    Includes claim_doc_files, assessment_files, upload_doc_files, and any
    files in the folder that were scanned.
    """
    all_files: Set[str] = set()

    for fpath in data.claim_doc_files.values():
        if fpath and os.path.isfile(fpath):
            all_files.add(os.path.normpath(fpath))

    for fpath in data.assessment_files.values():
        if fpath and os.path.isfile(fpath):
            all_files.add(os.path.normpath(fpath))

    for fpath in data.upload_doc_files.values():
        if fpath and os.path.isfile(fpath):
            all_files.add(os.path.normpath(fpath))

    return sorted(all_files)


def _get_used_files(data: ClaimData, uploaded_keys: Set[str]) -> Set[str]:
    """
    Return the set of file paths that have already been used/uploaded
    in previous phases or in the current upload sequence.
    """
    used: Set[str] = set()

    # Files used in claim documents tab (previous phases)
    for fpath in data.claim_doc_files.values():
        if fpath and os.path.isfile(fpath):
            used.add(os.path.normpath(fpath))

    # Files used in assessment tab (previous phases)
    for fpath in data.assessment_files.values():
        if fpath and os.path.isfile(fpath):
            used.add(os.path.normpath(fpath))

    # Files already uploaded in this module
    for key in uploaded_keys:
        fpath = data.upload_doc_files.get(key, "")
        if fpath and os.path.isfile(fpath):
            used.add(os.path.normpath(fpath))

    return used


def _collect_remaining_files(data: ClaimData, used_files: Set[str]) -> List[str]:
    """
    Collect all files from the user's folder that haven't been used yet.
    These will be merged into a single PDF for "Claim Related Documents".
    """
    remaining: List[str] = []

    # Derive the folder path from any known file
    folder_path = _get_folder_path(data)
    if not folder_path or not os.path.isdir(folder_path):
        return remaining

    # Allowed file extensions for upload
    _uploadable_exts = {
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp",
        ".doc", ".docx", ".xls", ".xlsx", ".txt",
    }
    _skip_files = {
        "all_pdf_text.txt", "extracted_documents_data.md",
        "re-inspection report format.pdf", "re-inspection report format.xlsx",
        "claim_related_document_merged.pdf",
    }

    for fname in sorted(os.listdir(folder_path)):
        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue

        # Skip system/generated files
        if fname.lower() in _skip_files:
            continue
        if fname.startswith("~$"):
            continue

        ext = Path(fname).suffix.lower()
        if ext not in _uploadable_exts:
            continue

        norm_path = os.path.normpath(full_path)
        if norm_path not in used_files:
            remaining.append(full_path)

    return remaining


def _get_folder_path(data: ClaimData) -> Optional[str]:
    """Derive folder path from any file in the data model."""
    for fpath in list(data.claim_doc_files.values()) + list(data.assessment_files.values()) + list(data.upload_doc_files.values()):
        if fpath and os.path.isfile(fpath):
            return os.path.dirname(fpath)
    return None


def _convert_image_to_pdf_page(img_path: str):
    """Convert an image file to a PDF page using Pillow."""
    from PIL import Image
    img = Image.open(img_path)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    return img


def merge_files_to_pdf(
    file_paths: List[str],
    output_path: str,
    max_bytes: int = MAX_MERGED_PDF_BYTES,
    log: Optional[Callable] = None,
) -> Optional[str]:
    """
    Merge multiple files (PDFs, images) into a single PDF.
    Returns the output path if successful and within size limit, None otherwise.

    Strategy (in priority order):
      1. Try PyPDF2 (best: merges PDF pages + image-converted pages)
      2. Fallback: Pillow-only (images → PDF pages, copy single PDFs)
      3. Other file types (doc, xls, xlsx) → skip with warning
    """
    if not file_paths:
        if isinstance(log, AutomationLogger):
            log.info("No remaining files to merge.")
        elif log:
            log(f"   ℹ️ No remaining files to merge.")
        return None

    _log = log or (lambda msg: None)
    _image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
    _pdf_exts = {".pdf"}
    _skip_exts = {".doc", ".docx", ".xls", ".xlsx", ".txt"}

    # ── Strategy 1: PyPDF2 (full merge) ───────────────────────────────────────
    try:
        from PyPDF2 import PdfMerger, PdfReader
        return _merge_with_pypdf2(
            file_paths, output_path, max_bytes, _log,
            _image_exts, _pdf_exts, PdfMerger, PdfReader
        )
    except ImportError:
        if isinstance(log, AutomationLogger):
            log.info("PyPDF2 not available. Using Pillow fallback for merge.")
        else:
            _log(f"   ℹ️ PyPDF2 not available. Using Pillow fallback for merge.")

    # ── Strategy 2: Pillow-only fallback ──────────────────────────────────────
    return _merge_with_pillow_fallback(
        file_paths, output_path, max_bytes, _log, _image_exts, _pdf_exts
    )


def _merge_with_pypdf2(
    file_paths, output_path, max_bytes, _log,
    _image_exts, _pdf_exts, PdfMerger, PdfReader
):
    """Full PDF merge using PyPDF2 + Pillow for images."""
    merger = PdfMerger()
    image_pdfs: List[str] = []
    merged_count = 0
    skipped_files: List[str] = []

    try:
        for fpath in file_paths:
            ext = Path(fpath).suffix.lower()
            fname = Path(fpath).name

            if ext in _pdf_exts:
                try:
                    reader = PdfReader(fpath)
                    if len(reader.pages) > 0:
                        merger.append(fpath)
                        merged_count += 1
                        if isinstance(_log, AutomationLogger):
                            _log.info(f"Added PDF: {fname} ({len(reader.pages)} pages)")
                        else:
                            _log(f"     📄 Added PDF: {fname} ({len(reader.pages)} pages)")
                    else:
                        if isinstance(_log, AutomationLogger):
                            _log.warning(f"Empty PDF skipped: {fname}")
                        else:
                            _log(f"     ⚠️ Empty PDF skipped: {fname}")
                except Exception as e:
                    if isinstance(_log, AutomationLogger):
                        _log.error(f"Could not read PDF {fname}: {e}")
                    else:
                        _log(f"     ⚠️ Could not read PDF {fname}: {e}")
                    skipped_files.append(fname)

            elif ext in _image_exts:
                try:
                    img = _convert_image_to_pdf_page(fpath)
                    temp_pdf = tempfile.NamedTemporaryFile(
                        suffix=".pdf", delete=False, prefix=f"img_{Path(fpath).stem}_"
                    )
                    img.save(temp_pdf.name, "PDF")
                    image_pdfs.append(temp_pdf.name)
                    merger.append(temp_pdf.name)
                    merged_count += 1
                    _log(f"[{_ts()}]     🖼️ Converted image to PDF: {fname}")
                except Exception as e:
                    _log(f"[{_ts()}]     ⚠️ Could not convert image {fname}: {e}")
                    skipped_files.append(fname)
            else:
                _log(f"[{_ts()}]     ⏭️ Skipping non-mergeable file: {fname} ({ext})")
                skipped_files.append(fname)

        if merged_count == 0:
            _log(f"[{_ts()}]   ⚠️ No files could be merged into PDF.")
            return None

        merger.write(output_path)
        merger.close()

        return _validate_merged_pdf(output_path, max_bytes, merged_count, skipped_files, _log)

    except Exception as e:
        _log(f"[{_ts()}]   ❌ PDF merge failed: {e}")
        return None
    finally:
        for tmp in image_pdfs:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _merge_with_pillow_fallback(
    file_paths, output_path, max_bytes, _log, _image_exts, _pdf_exts
):
    """
    Fallback merge using only Pillow.
    - Images → converted to PDF pages and saved as multi-page PDF
    - PDFs → if only one, just copy it; if multiple, copy first and warn
    - Does NOT merge PDF pages from multiple PDFs (requires PyPDF2)
    """
    import shutil

    pdf_files = [f for f in file_paths if Path(f).suffix.lower() in _pdf_exts]
    image_files = [f for f in file_paths if Path(f).suffix.lower() in _image_exts]
    skipped = [f for f in file_paths if f not in pdf_files and f not in image_files]

    for sf in skipped:
        _log(f"[{_ts()}]     ⏭️ Skipping non-mergeable: {Path(sf).name}")

    merged_count = 0

    # Case 1: Only images → merge with Pillow
    if image_files and not pdf_files:
        try:
            from PIL import Image
            images = []
            for img_path in image_files:
                try:
                    img = Image.open(img_path)
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    images.append(img)
                    merged_count += 1
                    _log(f"[{_ts()}]     🖼️ Added image: {Path(img_path).name}")
                except Exception as e:
                    _log(f"[{_ts()}]     ⚠️ Could not open image {Path(img_path).name}: {e}")

            if images:
                first = images[0]
                rest = images[1:] if len(images) > 1 else []
                first.save(output_path, "PDF", save_all=True, append_images=rest)
                return _validate_merged_pdf(output_path, max_bytes, merged_count, [Path(s).name for s in skipped], _log)
        except Exception as e:
            _log(f"[{_ts()}]   ❌ Pillow image merge failed: {e}")
            return None

    # Case 2: Single PDF (with or without images) → just copy the PDF
    if len(pdf_files) == 1 and not image_files:
        try:
            shutil.copy2(pdf_files[0], output_path)
            merged_count = 1
            _log(f"[{_ts()}]     📄 Copied single PDF: {Path(pdf_files[0]).name}")
            return _validate_merged_pdf(output_path, max_bytes, merged_count, [Path(s).name for s in skipped], _log)
        except Exception as e:
            _log(f"[{_ts()}]   ❌ Could not copy PDF: {e}")
            return None

    # Case 3: Multiple PDFs or mix → copy first PDF only, warn about rest
    if pdf_files:
        try:
            shutil.copy2(pdf_files[0], output_path)
            merged_count = 1
            _log(f"[{_ts()}]     📄 Copied first PDF: {Path(pdf_files[0]).name}")
            if len(pdf_files) > 1:
                _log(f"[{_ts()}]     ⚠️ Cannot merge {len(pdf_files)-1} additional PDFs without PyPDF2.")
                _log(f"[{_ts()}]     ℹ️ Install PyPDF2 for full merge: pip install PyPDF2")
            return _validate_merged_pdf(output_path, max_bytes, merged_count, [Path(s).name for s in skipped], _log)
        except Exception as e:
            _log(f"[{_ts()}]   ❌ Could not copy PDF: {e}")
            return None

    _log(f"[{_ts()}]   ⚠️ No mergeable files found.")
    return None


def _validate_merged_pdf(
    output_path: str, max_bytes: int, merged_count: int,
    skipped_files: List[str], _log: Callable
) -> Optional[str]:
    """Validate merged PDF size and log results."""
    file_size = os.path.getsize(output_path)
    mb = file_size / (1024 * 1024)

    if file_size > max_bytes:
        if isinstance(_log, AutomationLogger):
            _log.upload_failed("Merged PDF", f"Exceeds 15MB limit ({mb:.1f}MB).")
        else:
            _log(f"   ❌ Merged PDF exceeds 15MB limit ({mb:.1f}MB). Cannot upload.")
        try:
            os.remove(output_path)
        except OSError:
            pass
        return None

    if isinstance(_log, AutomationLogger):
        _log.success(f"Merged PDF created: {Path(output_path).name} ({mb:.1f}MB, {merged_count} files)")
    else:
        _log(f"   ✅ Merged PDF created: {Path(output_path).name} ({mb:.1f}MB, {merged_count} files)")

    if skipped_files:
        if isinstance(_log, AutomationLogger):
            _log.warning(f"Skipped {len(skipped_files)} non-mergeable files: {', '.join(skipped_files)}")
        else:
            _log(f"   ⏭️ Skipped {len(skipped_files)} non-mergeable files: {', '.join(skipped_files)}")

    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# MAIN UPLOAD FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

async def fill_document_upload_section(
    page: Page,
    data: ClaimData,
    log,
    stop_cb: Callable,
    field_delay_ms: int = 600,
) -> bool:
    if stop_cb(): return False

    if isinstance(log, AutomationLogger):
        log.info("Starting Document Upload Section phase...")
        log.indent()
    else:
        log("")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log("  📝 Phase 9: Document Upload Section")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — UPLOADED DOCUMENTS (SKIP — Informational only)
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section 1: Uploaded Documents (Informational)")
        log.info("Skipping display-only section.")
    else:
        log("")
        log(f"[{_ts()}]   ── Section 1: Uploaded Documents (Informational) ──")
        log(f"[{_ts()}]   ℹ️ Skipping — display-only section, no interaction needed.")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — UPLOAD NEW DOCUMENTS
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section 2: Upload New Documents")
        log.indent()
    else:
        log("")
        log(f"[{_ts()}]   ── Section 2: Upload New Documents ──")

    # 2a. Open the "Upload New Documents" accordion
    try:
        accordion_link = page.locator('a.accordion-toggle:has(span:text("Upload New Documents"))').first
        is_collapsed = await page.locator(
            'div.accordion-surv:has(a.accordion-toggle span:text("Upload New Documents")) '
            'div.panel-heading.collapsed'
        ).first.is_visible()

        if is_collapsed:
            await accordion_link.click()
            await asyncio.sleep(1.5)
            if isinstance(log, AutomationLogger):
                log.success("Accordion expanded.")
            else:
                log(f"[{_ts()}]   ✅ Opened 'Upload New Documents' accordion.")
        else:
            if isinstance(log, AutomationLogger):
                log.info("Accordion already open.")
            else:
                log(f"[{_ts()}]   ℹ️ 'Upload New Documents' accordion already open.")
    except Exception as e:
        if isinstance(log, AutomationLogger):
            log.warning(f"Accordion interaction warning: {str(e)[:100]}")
        else:
            log(f"   ⚠️ Could not open accordion (may already be open): {e}")

    if stop_cb(): return False

    # Wait for the mandatory document form to be visible
    try:
        await page.wait_for_selector('ng-form[name="mandatoryDocForm"]', state="visible", timeout=5000)
    except Exception:
        if isinstance(log, AutomationLogger):
            log.warning("Mandatory document form not visible; attempting to proceed.")
        else:
            log(f"[{_ts()}]   ⚠️ Mandatory document form not visible. Attempting to proceed...")

    # ── Track which files have been uploaded in this section ──────────────────
    uploaded_keys: Set[str] = set()

    # ── Define the upload sequence ────────────────────────────────────────────
    upload_sequence = [
        ("driving_license",          "Driving License",          "Driving License"),
        ("registration_certificate", "Registration Certificate", "Registration Certificate"),
        ("claim_form",               "Claim Form",               "Claim Form"),
    ]

    # Filter to only docs that actually have files in the folder
    active_docs = []
    for doc_key, dropdown_text, label in upload_sequence:
        file_path = data.upload_doc_files.get(doc_key, "")
        if file_path and os.path.isfile(file_path):
            active_docs.append((doc_key, dropdown_text, label, file_path))
        else:
            if isinstance(log, AutomationLogger):
                log.info(f"Skipping '{label}' (File not found).")
            else:
                log(f"[{_ts()}]   ℹ️ No '{label}' file found in folder. Skipping.")

    # ── Upload each document in its own row ───────────────────────────────────
    current_row = 0
    for idx, (doc_key, dropdown_text, label, file_path) in enumerate(active_docs):
        if stop_cb(): return False

        if isinstance(log, AutomationLogger):
            log.info(f"Processing mandatory row {current_row}: {label}")
            log.indent()
        else:
            log(f"")
            log(f"[{_ts()}]   📎 Uploading: {label} (row {current_row})")

        # If not the first row, click "+" to add a new row
        if idx > 0:
            try:
                add_btn = page.locator('span.fa-plus-circle[data-ng-click="surveyorWorklistSurvey.addRow(\'man\')"]').first
                if not await add_btn.is_visible():
                    add_btn = page.locator('ng-form[name="mandatoryDocForm"] span.fa-plus-circle').first
                await add_btn.click()
                await asyncio.sleep(1.0)
                if isinstance(log, AutomationLogger):
                    log.success("New row added.")
                else:
                    log(f"[{_ts()}]     ✅ Added new row (row {current_row})")
            except Exception as e:
                if isinstance(log, AutomationLogger):
                    log.warning(f"Row addition failed: {str(e)[:100]}")
                else:
                    log(f"[{_ts()}]     ⚠️ Could not add new row: {e}. Trying to use row {current_row} anyway.")

        # Step 1: Select document type in dropdown for this row
        dropdown_sel = f'select#docType{current_row}'
        try:
            await select_dropdown_with_delay(
                page, dropdown_sel, dropdown_text,
                f"Row {current_row} Type", log, field_delay_ms
            )
            await asyncio.sleep(0.5)
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Dropdown selection failed: {str(e)[:100]}")
                log.outdent()
            else:
                log(f"[{_ts()}]     ⚠️ Could not select dropdown for {label}: {e}")
            current_row += 1
            continue

        # Step 2: Attach file via Browse input for this row
        file_input_sel = f'input#mandatoryFiles{current_row}'
        try:
            success = await upload_file_via_input(
                page,
                file_input_selector=file_input_sel,
                file_path=file_path,
                label=f"Row {current_row} File",
                log=log,
            )
            if success:
                uploaded_keys.add(doc_key)
            else:
                if isinstance(log, AutomationLogger):
                    log.error("File attachment failed.")
        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Attachment error: {str(e)[:100]}")

        if isinstance(log, AutomationLogger):
            log.outdent()
        
        current_row += 1
        await asyncio.sleep(0.8)

    if stop_cb(): return False

    # ── CLAIM RELATED DOCUMENTS — Merge remaining files ──────────────────────
    if isinstance(log, AutomationLogger):
        log.info("Processing 'Claim Related Documents' (Merged PDF)")
        log.indent()
    else:
        log("")
        log(f"[{_ts()}]   📎 Preparing: Claim Related Documents (merged PDF)")

    # Collect used files
    used_files = _get_used_files(data, uploaded_keys)
    if isinstance(log, AutomationLogger):
        log.info(f"Context: {len(used_files)} files already used.")
    else:
        log(f"[{_ts()}]     📊 Already used/uploaded: {len(used_files)} files")

    # Collect remaining files from folder
    remaining_files = _collect_remaining_files(data, used_files)
    if isinstance(log, AutomationLogger):
        log.info(f"Unmatched files found: {len(remaining_files)}")
    else:
        log(f"[{_ts()}]     📊 Remaining unmatched files: {len(remaining_files)}")

    if remaining_files:
        if isinstance(log, AutomationLogger):
            for rf in remaining_files:
                log.info(f"Merging: {Path(rf).name}")
        else:
            for rf in remaining_files:
                log(f"[{_ts()}]       • {Path(rf).name}")

        # Determine output path for merged PDF
        folder_path = _get_folder_path(data) or tempfile.gettempdir()
        merged_pdf_path = os.path.join(folder_path, "CLAIM_RELATED_DOCUMENT_merged.pdf")

        # Remove old merged file if exists
        if os.path.exists(merged_pdf_path):
            try: os.remove(merged_pdf_path)
            except OSError: pass

        # Merge files
        if isinstance(log, AutomationLogger):
            log.wait("Creating consolidated PDF...")
        else:
            log(f"[{_ts()}]     🔄 Merging remaining files into single PDF...")
        
        merged_path = merge_files_to_pdf(
            file_paths=remaining_files,
            output_path=merged_pdf_path,
            max_bytes=MAX_MERGED_PDF_BYTES,
            log=log,
        )

        if merged_path:
            # Add a new row if we already used row(s) for other docs
            if current_row > 0:
                try:
                    add_btn = page.locator('span.fa-plus-circle[data-ng-click="surveyorWorklistSurvey.addRow(\'man\')"]').first
                    if not await add_btn.is_visible():
                        add_btn = page.locator('ng-form[name="mandatoryDocForm"] span.fa-plus-circle').first
                    await add_btn.click()
                    await asyncio.sleep(1.0)
                    if isinstance(log, AutomationLogger):
                        log.success("New row added for merged document.")
                    else:
                        log(f"[{_ts()}]     ✅ Added new row (row {current_row}) for Claim Related Documents")
                except Exception as e:
                    if isinstance(log, AutomationLogger):
                        log.warning(f"Row addition failed: {str(e)[:100]}")
                    else:
                        log(f"[{_ts()}]     ⚠️ Could not add new row: {e}")

            # Select "Claim Related Documents" in dropdown
            dropdown_sel = f'select#docType{current_row}'
            try:
                await select_dropdown_with_delay(
                    page, dropdown_sel, "Claim Related Documents",
                    f"Row {current_row} Type", log, field_delay_ms
                )
                await asyncio.sleep(0.5)
            except Exception as e:
                if isinstance(log, AutomationLogger):
                    log.error(f"Dropdown selection failed: {str(e)[:100]}")
                else:
                    log(f"[{_ts()}]     ⚠️ Could not select dropdown for Claim Related Documents: {e}")

            # Attach merged PDF
            file_input_sel = f'input#mandatoryFiles{current_row}'
            try:
                success = await upload_file_via_input(
                    page,
                    file_input_selector=file_input_sel,
                    file_path=merged_path,
                    label=f"Row {current_row} Merged File",
                    log=log,
                )
                if success:
                    mb = os.path.getsize(merged_path) / (1024 * 1024)
                    if not isinstance(log, AutomationLogger):
                        log(f"[{_ts()}]     ✅ Merged PDF attached ({mb:.1f}MB)")
                else:
                    if isinstance(log, AutomationLogger):
                        log.error("Merged PDF attachment failed.")
                    else:
                        log(f"[{_ts()}]     ⚠️ Merged PDF attachment failed.")
            except Exception as e:
                if isinstance(log, AutomationLogger):
                    log.error(f"Attachment error: {str(e)[:100]}")
                else:
                    log(f"[{_ts()}]     ⚠️ Error attaching merged PDF: {e}")

            current_row += 1
        else:
            if isinstance(log, AutomationLogger):
                log.error("PDF merge failed; no output generated.")
            else:
                log(f"[{_ts()}]     ⚠️ PDF merge produced no output. Claim Related Documents not attached.")
    else:
        if isinstance(log, AutomationLogger):
            log.info("No remaining files to merge.")
        else:
            log(f"[{_ts()}]     ℹ️ No remaining files to merge. Skipping Claim Related Documents.")

    if isinstance(log, AutomationLogger):
        log.outdent()

    # ── Summary: prompt user to click Upload ──────────────────────────────────
    if current_row > 0:
        if isinstance(log, AutomationLogger):
            log.success(f"All {current_row} documents attached. USER ACTION: Click 'Upload' on portal.")
        else:
            log("")
            log(f"[{_ts()}]   📋 All {current_row} document(s) attached in mandatory rows.")
            log(f"[{_ts()}]   ℹ️ Click the 'Upload' button on the website to save all documents.")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # NON-MANDATORY DOCUMENTS — SKIP ENTIRELY
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section: Non-Mandatory Documents")
        log.info("Skipping — handled via merged PDF.")
    else:
        log("")
        log(f"[{_ts()}]   ── List of Non-Mandatory Documents ──")
        log(f"[{_ts()}]   ℹ️ Skipping — all remaining docs already merged into Claim Related Documents.")

    if stop_cb(): return False

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — REMINDER TO INSURED (SKIP)
    # ══════════════════════════════════════════════════════════════════════════
    if isinstance(log, AutomationLogger):
        log.info("Section: Reminder to Insured")
        log.info("Skipping — no action required.")
    else:
        log("")
        log(f"[{_ts()}]   ── Section 3: Reminder to Insured ──")
        log(f"[{_ts()}]   ℹ️ Skipping — no automation interaction needed.")

    if isinstance(log, AutomationLogger):
        log.outdent()
        log.success("Document Upload phase completed.")
    else:
        log("")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        log("  ✅ Phase 9 (Document Upload Section) complete")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return True
