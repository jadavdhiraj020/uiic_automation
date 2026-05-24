"""
document_upload_module.py — Phase 11: Document Upload Section Automation
New India Assurance portal.

Handles:
  1. Skip "Uploaded Documents" section (informational only)
  2. Open "Upload New Documents" accordion
  3. Upload mandatory documents one-by-one:
       - Driving License
       - Registration Certificate
       - Claim Form
       - Claim Related Documents (pre-merged PDF from folder scan)
  4. Click Upload button and wait for all rows to show "Successful"
  5. Dismiss the post-upload alert popup
  6. Skip "Non-Mandatory Documents" section
  7. Skip "Reminder to Insured" section

IMPORTANT:
  - Files are attached through the portal Browse controls.
  - The portal Upload button is clicked after attachments are ready.
  - Claim Related Documents uses ONLY the pre-merged PDF from folder_scanner.
    No runtime merging is performed — all merging happens at scan time.
  - Final claim review/submission remains manual.
"""

import asyncio
import logging
import os
import re
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
from app.data.folder_scanner import (
    _prepare_files_for_merge,
    _compress_pdf_for_upload,
    _compress_image_for_upload,
)
from app.portals.newindia.automation.popup_service import dismiss_portal_popup

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_MERGED_PDF_BYTES = 15 * 1024 * 1024   # 15 MB portal limit (merged PDF)
MAX_MANDATORY_FILE_BYTES = 1536 * 1024    # 1.5 MB portal limit per individual file

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

    # Files already uploaded in this module (temp compressed paths)
    for key in uploaded_keys:
        fpath = data.upload_doc_files.get(key, "")
        if fpath and os.path.isfile(fpath):
            used.add(os.path.normpath(fpath))

    # Also exclude original pre-compression paths (scan-time compressed files are in temp dir;
    # the originals remain in the folder and must not end up in claim_related)
    orig_paths: Dict[str, str] = getattr(data, "original_upload_doc_paths", {}) or {}
    for fpath in orig_paths.values():
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

    # Only PDF and image files can be merged into a PDF — skip .doc/.xlsx/.txt
    _uploadable_exts = {
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    }
    _skip_files = {
        "all_pdf_text.txt", "extracted_documents_data.md",
        "re-inspection report format.pdf", "re-inspection report format.xlsx",
        "claim_others_documents.pdf",
        "claim_related_document_merged.pdf",
    }

    for fname in sorted(os.listdir(folder_path)):
        full_path = os.path.join(folder_path, fname)
        if not os.path.isfile(full_path):
            continue

        # Skip system/generated files
        fname_lower = fname.lower()
        if fname_lower in _skip_files:
            continue
        if fname_lower.startswith("claim_others_documents_"):
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
      1. Try pypdfium2 (best available runtime merger)
      2. Fallback: PyPDF2
      3. Fallback: Pillow-only for image-heavy sets
      4. Other file types (doc, xls, xlsx) → skip with warning
    """
    if not file_paths:
        if isinstance(log, AutomationLogger):
            log.info("No remaining files to merge.")
        elif log:
            log(f"   ℹ️ No remaining files to merge.")
        return None

    def _log(msg: str) -> None:
        if not log:
            return
        if isinstance(log, AutomationLogger):
            clean_msg = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", msg)
            if "❌" in clean_msg or "error" in clean_msg.lower():
                log.error(clean_msg)
            elif "⚠️" in clean_msg or "warning" in clean_msg.lower() or "skipped" in clean_msg.lower():
                log.warning(clean_msg)
            elif "✅" in clean_msg or "success" in clean_msg.lower() or "created" in clean_msg.lower():
                log.success(clean_msg)
            else:
                log.info(clean_msg)
        else:
            log(msg)

    _image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
    _pdf_exts = {".pdf"}

    # ── Pre-flight: compress largest files first until total fits in limit ────
    compression_tmps: List[str] = []
    file_paths, compression_tmps = _prepare_files_for_merge(
        file_paths, max_bytes, log_fn=_log
    )
    if not file_paths:
        if isinstance(log, AutomationLogger):
            log.warning("No valid files to merge after pre-flight.")
        return None

    # ── Strategy 1: pypdfium2 (Primary choice, actually installed) ───────────
    try:
        import pypdfium2 as pdfium
        try:
            return _merge_with_pypdfium2(
                file_paths, output_path, max_bytes, _log, _image_exts, _pdf_exts, pdfium
            )
        finally:
            for t in compression_tmps:
                try: os.remove(t)
                except OSError: pass
    except ImportError:
        if isinstance(log, AutomationLogger):
            log.info("pypdfium2 not available. Trying PyPDF2...")
        else:
            _log(f"   ℹ️ pypdfium2 not available. Trying PyPDF2...")

    # ── Strategy 2: PyPDF2 (Legacy choice) ───────────────────────────────────
    try:
        from PyPDF2 import PdfMerger, PdfReader
        try:
            return _merge_with_pypdf2(
                file_paths, output_path, max_bytes, _log,
                _image_exts, _pdf_exts, PdfMerger, PdfReader
            )
        finally:
            for t in compression_tmps:
                try: os.remove(t)
                except OSError: pass
    except ImportError:
        if isinstance(log, AutomationLogger):
            log.info("PyPDF2 not available. Using Pillow fallback for merge.")
        else:
            _log(f"   ℹ️ PyPDF2 not available. Using Pillow fallback for merge.")

    # ── Strategy 3: Pillow-only fallback ──────────────────────────────────────
    try:
        return _merge_with_pillow_fallback(
            file_paths, output_path, max_bytes, _log, _image_exts, _pdf_exts
        )
    finally:
        for t in compression_tmps:
            try: os.remove(t)
            except OSError: pass


def _merge_with_pypdfium2(
    file_paths, output_path, max_bytes, _log,
    _image_exts, _pdf_exts, pdfium
):
    """Full PDF merge using pypdfium2 + Pillow for images."""
    dest = pdfium.PdfDocument.new()
    image_pdfs: List[str] = []
    merged_count = 0
    skipped_files: List[str] = []

    try:
        for fpath in file_paths:
            ext = Path(fpath).suffix.lower()
            fname = Path(fpath).name

            if ext in _pdf_exts:
                try:
                    src = pdfium.PdfDocument(fpath)
                    if len(src) > 0:
                        dest.import_pages(src)
                        merged_count += 1
                        _log(f"✅ Merged: {fname}")
                except Exception as e:
                    _log(f"   ⚠️ Could not read {fname}, skipping: {e}")
                    skipped_files.append(fname)

            elif ext in _image_exts:
                try:
                    img = _convert_image_to_pdf_page(fpath)
                    tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="_upld_img_")
                    tmp_pdf_path = tmp_pdf.name
                    tmp_pdf.close()
                    img.save(tmp_pdf_path, "PDF")
                    image_pdfs.append(tmp_pdf_path)

                    src = pdfium.PdfDocument(tmp_pdf_path)
                    dest.import_pages(src)
                    merged_count += 1
                    _log(f"✅ Converted & merged: {fname}")
                except Exception as e:
                    _log(f"   ⚠️ Could not convert {fname}, skipping: {e}")
                    skipped_files.append(fname)
            else:
                _log(f"   ℹ️ Skipping non-mergeable file: {fname}")
                skipped_files.append(fname)

        if merged_count == 0:
            _log(f"   ⚠️ No files were successfully merged.")
            return None

        dest.save(output_path)
        
    except Exception as e:
        _log(f"   ❌ Merge error with pypdfium2: {e}")
        return None
    finally:
        for tpath in image_pdfs:
            try:
                os.remove(tpath)
            except OSError:
                pass

    if not os.path.isfile(output_path):
        _log(f"   ❌ Merged PDF was not created.")
        return None

    # Validate size
    actual_bytes = os.path.getsize(output_path)
    if actual_bytes > max_bytes:
        mb = actual_bytes / (1024 * 1024)
        max_mb = max_bytes / (1024 * 1024)
        _log(f"   ❌ Merged PDF too large ({mb:.1f}MB). Limit is {max_mb:.1f}MB.")
        try:
            os.remove(output_path)
        except OSError:
            pass
        return None

    return output_path


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




def _compress_mandatory_file_if_needed(
    file_path: str,
    label: str,
    log,
    limit_bytes: int = MAX_MANDATORY_FILE_BYTES,
) -> str:
    """
    Check if a mandatory document (DL, RC, Claim Form) exceeds the portal's
    per-file 1.5MB limit.  If it does, attempt to compress it into a temporary
    file and return the compressed path.  If compression fails or the file is
    already within limit, return the original path.

    The caller is responsible for nothing — temp files are cleaned up
    automatically when the process exits, as they use tempfile with delete=False
    but are written to the OS temp dir (short-lived).
    """
    if not file_path or not os.path.isfile(file_path):
        return file_path

    file_size = os.path.getsize(file_path)
    if file_size <= limit_bytes:
        return file_path  # already within limit — no compression needed

    ext = Path(file_path).suffix.lower()
    size_kb = file_size / 1024
    limit_kb = limit_bytes / 1024

    if isinstance(log, AutomationLogger):
        log.warning(
            f"{label}: file is {size_kb:.0f} KB > {limit_kb:.0f} KB limit — compressing..."
        )
    else:
        log(
            f"[{_ts()}]     ⚠️ {label}: {size_kb:.0f} KB > {limit_kb:.0f} KB limit — compressing..."
        )

    try:
        suffix = ext if ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp") else ".pdf"
        tmp = tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False, prefix=f"_mand_{Path(file_path).stem}_"
        )
        tmp.close()
        out_path = tmp.name

        if ext == ".pdf":
            ok = _compress_pdf_for_upload(file_path, out_path)
        elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp"):
            ok = _compress_image_for_upload(file_path, out_path)
        else:
            ok = False  # unsupported format — use original

        if ok and os.path.isfile(out_path):
            compressed_size = os.path.getsize(out_path)
            compressed_kb = compressed_size / 1024
            if compressed_size <= limit_bytes:
                if isinstance(log, AutomationLogger):
                    log.success(
                        f"{label}: compressed to {compressed_kb:.0f} KB — within {limit_kb:.0f} KB limit."
                    )
                else:
                    log(
                        f"[{_ts()}]     ✅ {label}: compressed to {compressed_kb:.0f} KB."
                    )
                return out_path
            else:
                # Compression helped but still over limit — warn and use original
                if isinstance(log, AutomationLogger):
                    log.warning(
                        f"{label}: still {compressed_kb:.0f} KB after compression — "
                        "portal size alert may appear; will be dismissed automatically."
                    )
                else:
                    log(
                        f"[{_ts()}]     ⚠️ {label}: still {compressed_kb:.0f} KB after compression. "
                        "Portal size alert will be dismissed."
                    )
                return out_path  # use compressed (smaller) even if still over
        else:
            if isinstance(log, AutomationLogger):
                log.warning(f"{label}: compression failed — using original file.")
            else:
                log(f"[{_ts()}]     ⚠️ {label}: compression failed — using original.")
            return file_path

    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.warning(f"{label}: compression error ({exc}) — using original file.")
        else:
            log(f"[{_ts()}]     ⚠️ {label}: compression error — using original.")
        return file_path


_UPLOAD_NEW_DOCUMENTS_RE = re.compile(r"^\s*Upload New Documents\s*$", re.IGNORECASE)


def _upload_new_documents_container(page: Page):
    return page.locator(".accordion-surv").filter(
        has=page.locator("a.accordion-toggle").filter(has_text=_UPLOAD_NEW_DOCUMENTS_RE)
    ).first


async def _is_upload_new_documents_open(page: Page) -> bool:
    """Return True only when the Upload New Documents accordion content is visible."""
    container = _upload_new_documents_container(page)
    try:
        await container.wait_for(state="attached", timeout=4000)
    except Exception:
        return False

    for selector in (
        'ng-form[name="mandatoryDocForm"]',
        'select#docType0',
        'input#mandatoryFiles0',
    ):
        try:
            if await container.locator(selector).first.is_visible():
                return True
        except Exception:
            pass

    try:
        collapsed_heading = container.locator("div.panel-heading.collapsed").first
        if await collapsed_heading.is_visible():
            return False
    except Exception:
        pass

    try:
        panel_body = container.locator("div.panel-collapse.in, div.panel-collapse[style*='height: auto']").first
        return await panel_body.is_visible()
    except Exception:
        return False


async def _open_upload_new_documents_section(page: Page, log) -> bool:
    """Open Upload New Documents exactly once if collapsed, then verify its form."""
    container = _upload_new_documents_container(page)
    try:
        await container.wait_for(state="visible", timeout=8000)
    except Exception as exc:
        if isinstance(log, AutomationLogger):
            log.error(f"Upload New Documents accordion not found: {str(exc)[:120]}")
        else:
            log(f"[{_ts()}]   ❌ Upload New Documents accordion not found: {exc}")
        return False

    if await _is_upload_new_documents_open(page):
        if isinstance(log, AutomationLogger):
            log.info("'Upload New Documents' accordion already open.")
        else:
            log(f"[{_ts()}]   ℹ️ 'Upload New Documents' accordion already open.")
        return True

    heading = container.locator("a.accordion-toggle").filter(has_text=_UPLOAD_NEW_DOCUMENTS_RE).first
    for attempt in range(2):
        try:
            await heading.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            if await _is_upload_new_documents_open(page):
                return True
            await heading.click()
            await asyncio.sleep(1.0)
            if await _is_upload_new_documents_open(page):
                if isinstance(log, AutomationLogger):
                    log.success("'Upload New Documents' accordion opened.")
                else:
                    log(f"[{_ts()}]   ✅ Opened 'Upload New Documents' accordion.")
                return True
        except Exception as exc:
            if isinstance(log, AutomationLogger):
                log.warning(f"Accordion open attempt {attempt + 1} failed: {str(exc)[:100]}")
            else:
                log(f"[{_ts()}]   ⚠️ Accordion open attempt {attempt + 1} failed: {exc}")

    if isinstance(log, AutomationLogger):
        log.error("Mandatory document form not visible after opening Upload New Documents.")
    else:
        log(f"[{_ts()}]   ❌ Mandatory document form not visible after opening Upload New Documents.")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# POST-UPLOAD VERIFICATION — Wait for "Successful" status on all rows
# ══════════════════════════════════════════════════════════════════════════════

async def _wait_for_upload_success(page: Page, expected_rows: int, log, max_wait_s: float = 30.0) -> bool:
    """
    After clicking the Upload button, the portal takes 5–10s (variable) to
    process all files.  Each row transitions to show a green "Successful ✓"
    status text once its file is accepted.

    This function polls until ALL expected rows display "Successful", or
    until the timeout expires.

    Returns True if all rows show Successful, False on timeout.
    """
    if expected_rows <= 0:
        return True

    poll_interval = 1.0
    elapsed = 0.0

    if isinstance(log, AutomationLogger):
        log.wait(f"Waiting for {expected_rows} document(s) to show 'Successful' (max {max_wait_s:.0f}s)...")
    else:
        log(f"[{_ts()}]   ⏳ Waiting for {expected_rows} doc(s) to upload successfully (max {max_wait_s:.0f}s)...")

    while elapsed < max_wait_s:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        try:
            # Count how many rows currently show "Successful" text
            successful_count = 0
            for i in range(expected_rows):
                row_loc = page.locator(f'tr:has(input#mandatoryFiles{i}), div:has(input#mandatoryFiles{i})').first
                has_success = await row_loc.locator(
                    'span:has-text("Successful"), td:has-text("Successful"), div:has-text("Successful")'
                ).first.is_visible()
                if has_success:
                    successful_count += 1

            if successful_count >= expected_rows:
                if isinstance(log, AutomationLogger):
                    log.success(f"All {expected_rows} document(s) uploaded successfully ({elapsed:.0f}s).")
                else:
                    log(f"[{_ts()}]   ✅ All {expected_rows} doc(s) uploaded successfully ({elapsed:.0f}s).")
                return True

            # Log progress every 3 seconds
            if elapsed % 3 < poll_interval:
                if isinstance(log, AutomationLogger):
                    log.info(f"Upload progress: {successful_count}/{expected_rows} rows successful ({elapsed:.0f}s)...")
                else:
                    log(f"[{_ts()}]   ⏳ {successful_count}/{expected_rows} successful ({elapsed:.0f}s)...")

        except Exception as exc:
            if isinstance(log, AutomationLogger):
                log.warning(f"Upload status check error: {str(exc)[:80]}")

    # Timeout — log how many actually succeeded
    try:
        final_count = 0
        for i in range(expected_rows):
            row_loc = page.locator(f'tr:has(input#mandatoryFiles{i}), div:has(input#mandatoryFiles{i})').first
            has_success = await row_loc.locator(
                'span:has-text("Successful"), td:has-text("Successful"), div:has-text("Successful")'
            ).first.is_visible()
            if has_success:
                final_count += 1
    except Exception:
        final_count = 0

    if isinstance(log, AutomationLogger):
        log.warning(
            f"Upload timeout after {max_wait_s:.0f}s: {final_count}/{expected_rows} rows successful. "
            "Continuing anyway..."
        )
    else:
        log(
            f"[{_ts()}]   ⚠️ Upload timeout ({max_wait_s:.0f}s): {final_count}/{expected_rows} successful. "
            "Continuing..."
        )
    return final_count > 0  # partial success is still acceptable


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
        log("  📝 Phase 11: Document Upload Section")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    await dismiss_portal_popup(page, log, max_wait_s=1.5)
    if stop_cb(): return False

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

    if not await _open_upload_new_documents_section(page, log):
        if isinstance(log, AutomationLogger):
            log.outdent()
            log.outdent()
        return False

    if stop_cb(): return False

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
        # Note: file_path already points to compressed version if it was over
        # 1.5 MB (compression happens at scan time in folder_scanner.py)
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

        # Step 4: Dismiss any portal alert that appeared after attaching
        # (file size alert — in case compression was insufficient)
        alert_tag = await dismiss_portal_popup(page, log, classify=True, max_wait_s=3.0)
        if alert_tag == "size_error":
            # File is truly too large and portal rejected it — log and skip
            if isinstance(log, AutomationLogger):
                log.warning(
                    f"{label}: portal rejected file as too large — row will be empty. "
                    "Check file size manually."
                )

        if isinstance(log, AutomationLogger):
            log.outdent()

        current_row += 1
        await asyncio.sleep(0.8)

    if stop_cb(): return False

    # ── CLAIM RELATED DOCUMENTS — Use pre-merged PDF from folder scan ────────
    if isinstance(log, AutomationLogger):
        log.info("Processing 'Claim Related Documents' (Pre-merged PDF)")
        log.indent()
    else:
        log("")
        log(f"[{_ts()}]   📎 Preparing: Claim Related Documents (pre-merged PDF)")

    # Strictly use the pre-merged PDF generated by folder_scanner at scan time.
    # No runtime merging is performed — all merging happens before automation starts.
    scan_result = getattr(data, "_scan_result", None)
    precomputed_pdf = getattr(scan_result, "claim_related_merged_pdf", None) if scan_result else None

    # Failsafe: if not provided by scan_result, search the folder directly for pre-merged PDFs
    if not precomputed_pdf or not os.path.isfile(precomputed_pdf):
        folder_path = _get_folder_path(data)
        if folder_path and os.path.isdir(folder_path):
            import glob
            pattern = os.path.join(folder_path, "claim_others_documents_*.pdf")
            found_files = sorted(glob.glob(pattern))
            if found_files:
                precomputed_pdf = found_files[-1]
            else:
                std_path = os.path.join(folder_path, "claim_others_documents.pdf")
                if os.path.isfile(std_path):
                    precomputed_pdf = std_path

    if precomputed_pdf and os.path.isfile(precomputed_pdf):
        merged_path = precomputed_pdf
        precomputed = getattr(scan_result, "claim_related_files", None) if scan_result else None
        n = len(precomputed) if precomputed else "?"
        mb = os.path.getsize(merged_path) / (1024 * 1024)
        if isinstance(log, AutomationLogger):
            log.success(f"Using pre-merged PDF: {Path(merged_path).name} ({n} source file(s), {mb:.1f}MB)")
        else:
            log(f"[{_ts()}]     ✅ Using pre-merged: {Path(merged_path).name} ({n} source file(s), {mb:.1f}MB)")
    else:
        merged_path = None
        if isinstance(log, AutomationLogger):
            log.warning(
                "No pre-merged PDF available. Claim Related Documents will not be uploaded. "
                "Ensure folder scan completes before automation starts."
            )
        else:
            log(f"[{_ts()}]     ⚠️ No pre-merged PDF available. Skipping Claim Related Documents.")

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
            log.warning("No merged PDF available. Claim Related Documents not attached.")
        else:
            log(f"[{_ts()}]     ⚠️ No merged PDF. Claim Related Documents not attached.")

    if isinstance(log, AutomationLogger):
        log.outdent()

    # ══════════════════════════════════════════════════════════════════════════
    # CLICK UPLOAD BUTTON → WAIT FOR "SUCCESSFUL" → DISMISS ALERT
    # ══════════════════════════════════════════════════════════════════════════
    if current_row > 0:
        if isinstance(log, AutomationLogger):
            log.info(f"All {current_row} documents attached. Clicking Upload button...")
        else:
            log("")
            log(f"[{_ts()}]   📋 All {current_row} document(s) attached. Clicking Upload...")

        try:
            upload_btn = page.locator('button[data-ng-click="uploadFileNonTieUp(\'mandatory\')"]').first
            await upload_btn.wait_for(state="visible", timeout=8000)

            # Wait up to 5s for Angular to enable the button after file attachment
            for _ in range(10):
                if not await upload_btn.is_disabled():
                    break
                await asyncio.sleep(0.5)

            if await upload_btn.is_disabled():
                if isinstance(log, AutomationLogger):
                    log.warning("Upload button still disabled; files may not be attached correctly.")
                else:
                    log(f"[{_ts()}]   ⚠️ Upload button is still disabled. Skipping upload click.")
            else:
                await upload_btn.click()
                if isinstance(log, AutomationLogger):
                    log.success("Upload button clicked.")
                    log.wait("Waiting for portal to process upload...")
                else:
                    log(f"[{_ts()}]   ✅ Upload button clicked.")

                # ── Wait for the post-upload alert popup ───────────────────────
                # The portal shows a loading spinner and performs heavy network I/O.
                # To prevent tab crashes and CPU overhead, we wait 20 seconds
                # without executing any JS or Playwright actions.
                if isinstance(log, AutomationLogger):
                    log.wait("Waiting 20 seconds for upload processing quiet period...")
                else:
                    log(f"[{_ts()}]   ⏳ Waiting 20 seconds for upload processing quiet period...")
                
                await asyncio.sleep(20.0)

                # After the quiet period, we poll for the popup modal (max 30s)
                # to dismiss the "already applied/uploaded successfully" alert.
                await dismiss_portal_popup(page, log, max_wait_s=30.0, context="Post-upload processing")

        except Exception as e:
            if isinstance(log, AutomationLogger):
                log.error(f"Upload button error: {str(e)[:100]}")
            else:
                log(f"[{_ts()}]   ⚠️ Error clicking Upload button: {e}")

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
        log("  ✅ Phase 11 (Document Upload Section) complete")
        log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return True
