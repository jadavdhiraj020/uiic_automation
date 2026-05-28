import os
import re
import tempfile
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Set, Union

from app.automation.automation_logger import AutomationLogger, _ts
from app.data.data_model import ClaimData
import app.data.folder_scanner


@dataclass
class MergeConfig:
    max_bytes: int
    label: str = "Documents"
    only_extensions: Set[str] = field(default_factory=lambda: {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp"})
    exclude_filenames: Set[str] = field(default_factory=set)
    exclude_prefixes: Set[str] = field(default_factory=set)


class PdfMergeService:
    """
    Unified PDF merging service for UIIC automation portals.
    Handles size limits, format conversion, and multi-library fallback strategies.
    """

    @staticmethod
    def merge(
        file_paths: List[str],
        output_path: str,
        config: MergeConfig,
        log: Optional[Union[AutomationLogger, Callable]] = None,
    ) -> Optional[str]:
        """
        Merge multiple files (PDFs, images) into a single PDF.
        Returns the output path if successful and within size limit, None otherwise.
        """
        if not file_paths:
            PdfMergeService._log(log, f"   ℹ️ No remaining files to merge for {config.label}.")
            return None

        _image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}
        _pdf_exts = {".pdf"}

        # ── Pre-flight: compress largest files first until total fits in limit ────
        compression_tmps: List[str] = []
        
        # Determine the log callable for the pre-flight
        preflight_log = PdfMergeService._get_callable_logger(log)

        file_paths, compression_tmps = app.data.folder_scanner._prepare_files_for_merge(
            file_paths, config.max_bytes, log_fn=preflight_log
        )
        if not file_paths:
            PdfMergeService._log(log, f"   ⚠️ No valid files to merge after pre-flight for {config.label}.")
            return None

        # ── Remove previous output if exists ──────────────────────────────────────
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass

        result = None

        # ── Strategy 1: pypdfium2 (Primary choice) ───────────
        try:
            import pypdfium2 as pdfium
            try:
                result = PdfMergeService._merge_with_pypdfium2(
                    file_paths, output_path, config.max_bytes, log, _image_exts, _pdf_exts, pdfium
                )
            except Exception as e:
                PdfMergeService._log(log, f"   ⚠️ pypdfium2 merge failed ({e}). Trying PyPDF2...")
        except ImportError:
            PdfMergeService._log(log, f"   ℹ️ pypdfium2 not available. Trying PyPDF2...")

        # ── Strategy 2: PyPDF2 (Legacy choice) ───────────────────────────────────
        if result is None:
            try:
                from PyPDF2 import PdfMerger, PdfReader
                try:
                    result = PdfMergeService._merge_with_pypdf2(
                        file_paths, output_path, config.max_bytes, log,
                        _image_exts, _pdf_exts, PdfMerger, PdfReader
                    )
                except Exception as e:
                    PdfMergeService._log(log, f"   ⚠️ PyPDF2 merge failed ({e}). Using Pillow fallback...")
            except ImportError:
                PdfMergeService._log(log, f"   ℹ️ PyPDF2 not available. Using Pillow fallback for merge.")

        # ── Strategy 3: Pillow-only fallback ──────────────────────────────────────
        if result is None:
            try:
                result = PdfMergeService._merge_with_pillow_fallback(
                    file_paths, output_path, config.max_bytes, log, _image_exts, _pdf_exts
                )
            except Exception as e:
                PdfMergeService._log(log, f"   ❌ Pillow fallback merge failed: {e}")

        # Cleanup compression temps
        for t in compression_tmps:
            try: os.remove(t)
            except OSError: pass

        return result

    @staticmethod
    def get_folder_path(data: ClaimData) -> Optional[str]:
        """Derive the claim folder path from any known file in the data model."""
        for pool_name in ("claim_doc_files", "assessment_files", "upload_doc_files"):
            pool = getattr(data, pool_name, {}) or {}
            for fpath in pool.values():
                if fpath and os.path.isfile(fpath):
                    return os.path.dirname(fpath)
        return None

    @staticmethod
    def collect_remaining(
        data: ClaimData,
        used_files: Set[str],
        config: MergeConfig,
    ) -> List[str]:
        """
        Collect all files from the user's folder that haven't been used yet.
        """
        folder_path = PdfMergeService.get_folder_path(data)
        if not folder_path or not os.path.isdir(folder_path):
            return []

        remaining: List[str] = []
        for fname in sorted(os.listdir(folder_path)):
            full_path = os.path.join(folder_path, fname)
            if not os.path.isfile(full_path):
                continue

            fname_lower = fname.lower()
            
            # Skip by explicit filename
            if fname_lower in {f.lower() for f in config.exclude_filenames}:
                continue
            
            # Skip by prefix
            skip_by_prefix = False
            for prefix in config.exclude_prefixes:
                if fname_lower.startswith(prefix.lower()):
                    skip_by_prefix = True
                    break
            if skip_by_prefix:
                continue
                
            # Skip temp files
            if fname.startswith("~$"):
                continue

            # Check extension
            ext = Path(fname).suffix.lower()
            if ext not in config.only_extensions:
                continue

            norm_path = os.path.normpath(full_path)
            if norm_path not in used_files:
                remaining.append(full_path)

        return remaining

    # ══════════════════════════════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ══════════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _log(log: Optional[Union[AutomationLogger, Callable]], msg: str) -> None:
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
            # Callable like logger.info
            log(msg)
            
    @staticmethod
    def _get_callable_logger(log: Optional[Union[AutomationLogger, Callable]]) -> Callable:
        if isinstance(log, AutomationLogger):
            return lambda m: PdfMergeService._log(log, m)
        if log:
            return log
        import logging
        return logging.getLogger(__name__).info

    @staticmethod
    def _convert_image_to_pdf_page(img_path: str):
        from PIL import Image
        img = Image.open(img_path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        return img

    @staticmethod
    def _validate_merged_pdf(
        output_path: str, max_bytes: int, merged_count: int,
        skipped_files: List[str], log: Optional[Union[AutomationLogger, Callable]]
    ) -> Optional[str]:
        if not os.path.isfile(output_path):
            PdfMergeService._log(log, "   ❌ Merged PDF was not created.")
            return None

        file_size = os.path.getsize(output_path)
        mb = file_size / (1024 * 1024)
        max_mb = max_bytes / (1024 * 1024)

        if file_size > max_bytes:
            if isinstance(log, AutomationLogger):
                log.upload_failed("Merged PDF", f"Exceeds {max_mb:.0f}MB limit ({mb:.1f}MB).")
            else:
                PdfMergeService._log(log, f"   ❌ Merged PDF exceeds {max_mb:.0f}MB limit ({mb:.1f}MB). Cannot upload.")
            try:
                os.remove(output_path)
            except OSError:
                pass
            return None

        if isinstance(log, AutomationLogger):
            log.success(f"Merged PDF created: {Path(output_path).name} ({mb:.1f}MB, {merged_count} files)")
        else:
            PdfMergeService._log(log, f"   ✅ Merged PDF created: {Path(output_path).name} ({mb:.1f}MB, {merged_count} files)")

        if skipped_files:
            if isinstance(log, AutomationLogger):
                log.warning(f"Skipped {len(skipped_files)} non-mergeable files: {', '.join(skipped_files)}")
            else:
                PdfMergeService._log(log, f"   ⏭️ Skipped {len(skipped_files)} non-mergeable files: {', '.join(skipped_files)}")

        return output_path

    @staticmethod
    def _merge_with_pypdfium2(
        file_paths, output_path, max_bytes, log,
        _image_exts, _pdf_exts, pdfium
    ) -> Optional[str]:
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
                        try:
                            if len(src) > 0:
                                dest.import_pages(src)
                                merged_count += 1
                                PdfMergeService._log(log, f"✅ Merged: {fname}")
                        finally:
                            src.close()
                    except Exception as e:
                        PdfMergeService._log(log, f"   ⚠️ Could not read PDF {fname}, skipping: {e}")
                        skipped_files.append(fname)

                elif ext in _image_exts:
                    try:
                        img = PdfMergeService._convert_image_to_pdf_page(fpath)
                        try:
                            tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="_upld_img_")
                            tmp_pdf_path = tmp_pdf.name
                            tmp_pdf.close()
                            img.save(tmp_pdf_path, "PDF")
                        finally:
                            img.close()
                            
                        image_pdfs.append(tmp_pdf_path)

                        src = pdfium.PdfDocument(tmp_pdf_path)
                        try:
                            dest.import_pages(src)
                            merged_count += 1
                            PdfMergeService._log(log, f"✅ Converted & merged: {fname}")
                        finally:
                            src.close()
                    except Exception as e:
                        PdfMergeService._log(log, f"   ⚠️ Could not convert image {fname}, skipping: {e}")
                        skipped_files.append(fname)
                else:
                    PdfMergeService._log(log, f"   ℹ️ Skipping non-mergeable file: {fname}")
                    skipped_files.append(fname)

            if merged_count == 0:
                PdfMergeService._log(log, "   ⚠️ No files were successfully merged.")
                return None

            dest.save(output_path)
            
        finally:
            try:
                dest.close()
            except Exception:
                pass
            for tpath in image_pdfs:
                try: os.remove(tpath)
                except OSError: pass

        return PdfMergeService._validate_merged_pdf(output_path, max_bytes, merged_count, skipped_files, log)

    @staticmethod
    def _merge_with_pypdf2(
        file_paths, output_path, max_bytes, log,
        _image_exts, _pdf_exts, PdfMerger, PdfReader
    ) -> Optional[str]:
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
                            if isinstance(log, AutomationLogger):
                                log.info(f"Added PDF: {fname} ({len(reader.pages)} pages)")
                            else:
                                PdfMergeService._log(log, f"     📄 Added PDF: {fname} ({len(reader.pages)} pages)")
                        else:
                            if isinstance(log, AutomationLogger):
                                log.warning(f"Empty PDF skipped: {fname}")
                            else:
                                PdfMergeService._log(log, f"     ⚠️ Empty PDF skipped: {fname}")
                    except Exception as e:
                        if isinstance(log, AutomationLogger):
                            log.error(f"Could not read PDF {fname}: {e}")
                        else:
                            PdfMergeService._log(log, f"     ⚠️ Could not read PDF {fname}: {e}")
                        skipped_files.append(fname)

                elif ext in _image_exts:
                    try:
                        img = PdfMergeService._convert_image_to_pdf_page(fpath)
                        try:
                            temp_pdf = tempfile.NamedTemporaryFile(
                                suffix=".pdf", delete=False, prefix=f"img_{Path(fpath).stem}_"
                            )
                            temp_pdf_path = temp_pdf.name
                            temp_pdf.close()
                            img.save(temp_pdf_path, "PDF")
                        finally:
                            img.close()
                            
                        image_pdfs.append(temp_pdf_path)
                        merger.append(temp_pdf_path)
                        merged_count += 1
                        PdfMergeService._log(log, f"[{_ts()}]     🖼️ Converted image to PDF: {fname}")
                    except Exception as e:
                        PdfMergeService._log(log, f"[{_ts()}]     ⚠️ Could not convert image {fname}: {e}")
                        skipped_files.append(fname)
                else:
                    PdfMergeService._log(log, f"[{_ts()}]     ⏭️ Skipping non-mergeable file: {fname} ({ext})")
                    skipped_files.append(fname)

            if merged_count == 0:
                PdfMergeService._log(log, f"[{_ts()}]   ⚠️ No files could be merged into PDF.")
                return None

            merger.write(output_path)
            merger.close()

        finally:
            for tmp in image_pdfs:
                try: os.remove(tmp)
                except OSError: pass

        return PdfMergeService._validate_merged_pdf(output_path, max_bytes, merged_count, skipped_files, log)

    @staticmethod
    def _merge_with_pillow_fallback(
        file_paths, output_path, max_bytes, log, _image_exts, _pdf_exts
    ) -> Optional[str]:
        pdf_files = [f for f in file_paths if Path(f).suffix.lower() in _pdf_exts]
        image_files = [f for f in file_paths if Path(f).suffix.lower() in _image_exts]
        skipped = [f for f in file_paths if f not in pdf_files and f not in image_files]

        for sf in skipped:
            PdfMergeService._log(log, f"[{_ts()}]     ⏭️ Skipping non-mergeable: {Path(sf).name}")

        merged_count = 0

        # Case 1: Only images → merge with Pillow
        if image_files and not pdf_files:
            images = []
            try:
                from PIL import Image
                for img_path in image_files:
                    try:
                        img = Image.open(img_path)
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")
                        images.append(img)
                        merged_count += 1
                        PdfMergeService._log(log, f"[{_ts()}]     🖼️ Added image: {Path(img_path).name}")
                    except Exception as e:
                        PdfMergeService._log(log, f"[{_ts()}]     ⚠️ Could not open image {Path(img_path).name}: {e}")

                if images:
                    first = images[0]
                    rest = images[1:] if len(images) > 1 else []
                    first.save(output_path, "PDF", save_all=True, append_images=rest)
                    return PdfMergeService._validate_merged_pdf(
                        output_path, max_bytes, merged_count, [Path(s).name for s in skipped], log
                    )
            finally:
                for img in images:
                    try: img.close()
                    except Exception: pass
            
            return None

        # Case 2: Single PDF (with or without images) → just copy the PDF
        if len(pdf_files) == 1 and not image_files:
            shutil.copy2(pdf_files[0], output_path)
            merged_count = 1
            PdfMergeService._log(log, f"[{_ts()}]     📄 Copied single PDF: {Path(pdf_files[0]).name}")
            return PdfMergeService._validate_merged_pdf(
                output_path, max_bytes, merged_count, [Path(s).name for s in skipped], log
            )

        # Case 3: Multiple PDFs or mix → copy first PDF only, warn about rest
        if pdf_files:
            shutil.copy2(pdf_files[0], output_path)
            merged_count = 1
            PdfMergeService._log(log, f"[{_ts()}]     📄 Copied first PDF: {Path(pdf_files[0]).name}")
            if len(pdf_files) > 1:
                PdfMergeService._log(log, f"[{_ts()}]     ⚠️ Cannot merge {len(pdf_files)-1} additional PDFs without PyPDF2.")
                PdfMergeService._log(log, f"[{_ts()}]     ℹ️ Install PyPDF2 for full merge: pip install PyPDF2")
            return PdfMergeService._validate_merged_pdf(
                output_path, max_bytes, merged_count, [Path(s).name for s in skipped], log
            )

        PdfMergeService._log(log, f"[{_ts()}]   ⚠️ No mergeable files found.")
        return None
