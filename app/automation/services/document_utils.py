import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

def _compress_pdf_for_upload(
    pdf_path: str,
    output_path: str,
    target_dpi: int = 72,
    quality: int = 70,
    max_pages: int = 100,
) -> bool:
    """
    Re-render PDF pages into memory and save directly as a compressed multi-page PDF via Pillow.
    Avoids slow per-page disk I/O and temporary files.
    Returns True on success, False on failure.
    """
    try:
        import pypdfium2 as pdfium  # type: ignore
        from PIL import Image  # type: ignore

        src = pdfium.PdfDocument(pdf_path)
        total_pages = len(src)
        if total_pages == 0:
            return False

        if total_pages > max_pages:
            logger.warning(
                "_compress_pdf_for_upload: %s has %d pages (exceeds safety limit of %d); compressing first %d pages",
                Path(pdf_path).name, total_pages, max_pages, max_pages,
            )

        render_count = min(total_pages, max_pages)
        scale = target_dpi / 72.0  # pypdfium2: scale=1.0 -> 72 DPI
        images: List[Image.Image] = []

        try:
            for i in range(render_count):
                page = src[i]
                bitmap = page.render(scale=scale)
                pil_img = bitmap.to_pil()
                if pil_img.mode != "RGB":
                    pil_img = pil_img.convert("RGB")
                images.append(pil_img)

            if not images:
                return False

            # Direct in-memory multi-page PDF export via Pillow — zero temp files on disk!
            images[0].save(
                output_path,
                "PDF",
                save_all=True,
                append_images=images[1:],
                resolution=float(target_dpi),
                quality=quality,
                optimize=True,
            )
            return True
        finally:
            for im in images:
                try:
                    im.close()
                except Exception:
                    pass
            try:
                src.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning("_compress_pdf_for_upload failed for %s: %s", Path(pdf_path).name, e)
        return False


def _compress_image_for_upload(img_path: str, output_path: str, quality: int = 75) -> bool:
    """Re-save an image as JPEG at the given quality to reduce file size."""
    try:
        from PIL import Image  # type: ignore
        img = Image.open(img_path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=quality, optimize=True)
        return True
    except Exception as e:
        logger.warning("_compress_image_for_upload failed for %s: %s", Path(img_path).name, e)
        return False


def compress_uiic_document_if_needed(
    file_path: str,
    log=None,
    max_mb: float = 2.0,
    target_mb: float = 1.9,
) -> "tuple[str, bool]":
    """
    UIIC document compression profile:
    If a document exceeds max_mb (2.0 MB), compresses it into a temporary
    file aiming for <= target_mb (1.9 MB).
    The original file in the claim folder remains completely untouched.
    Returns (path_to_upload, was_compressed).
    """
    if not file_path or not os.path.isfile(file_path):
        return file_path, False

    file_size = os.path.getsize(file_path)
    limit_bytes = int(max_mb * 1024 * 1024)
    target_bytes = int(target_mb * 1024 * 1024)

    if file_size <= limit_bytes:
        return file_path, False

    fname = os.path.basename(file_path)
    ext = Path(file_path).suffix.lower()
    orig_mb = file_size / (1024 * 1024)

    msg = f"Document {fname} ({orig_mb:.2f}MB > {max_mb}MB limit) — compressing for UIIC (target <= {target_mb}MB)..."
    if log:
        if hasattr(log, "warning"):
            log.warning(msg)
        elif callable(log):
            log(f"  ⚠️ {msg}")
    logger.info(msg)

    # Place in a unique temp directory while preserving the original filename
    temp_dir = tempfile.mkdtemp(prefix="_uiic_upload_")
    out_path = os.path.join(temp_dir, fname)

    try:
        ok = False
        if ext == ".pdf":
            # Fast in-memory PDF compression passes targeting <= 1.9 MB
            for dpi, q in ((72, 70), (50, 50), (36, 40)):
                ok = _compress_pdf_for_upload(file_path, out_path, target_dpi=dpi, quality=q)
                if ok and os.path.isfile(out_path) and os.path.getsize(out_path) <= target_bytes:
                    break
        elif ext in (".jpg", ".jpeg", ".png", ".gif", ".bmp"):
            # Multi-pass image compression targeting <= 1.9 MB
            for q in (75, 50, 30):
                ok = _compress_image_for_upload(file_path, out_path, quality=q)
                if ok and os.path.isfile(out_path) and os.path.getsize(out_path) <= target_bytes:
                    break
            # If still over limit, resize dimensions
            if ok and os.path.isfile(out_path) and os.path.getsize(out_path) > target_bytes:
                try:
                    from PIL import Image  # type: ignore
                    with Image.open(file_path) as im:
                        if im.mode in ("RGBA", "P"):
                            im = im.convert("RGB")
                        w, h = im.size
                        im_resized = im.resize((int(w * 0.7), int(h * 0.7)), Image.Resampling.LANCZOS)
                        im_resized.save(out_path, "JPEG", quality=40, optimize=True)
                except Exception:
                    pass

        if ok and os.path.isfile(out_path):
            comp_mb = os.path.getsize(out_path) / (1024 * 1024)
            success_msg = f"Compressed {fname}: {orig_mb:.2f}MB → {comp_mb:.2f}MB"
            if log:
                if hasattr(log, "success"):
                    log.success(success_msg)
                elif callable(log):
                    log(f"  ✅ {success_msg}")
            logger.info(success_msg)
            return out_path, True
        else:
            fail_msg = f"Compression failed for {fname} — using original file"
            if log:
                if hasattr(log, "warning"):
                    log.warning(fail_msg)
                elif callable(log):
                    log(f"  ⚠️ {fail_msg}")
            logger.warning(fail_msg)
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            return file_path, False

    except Exception as exc:
        logger.warning("Compression error for %s (%s) — using original file", fname, exc)
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        return file_path, False


def _prepare_files_for_merge(
    file_paths: List[str],
    max_bytes: int,
    log_fn,  # callable(str) -> None
) -> "tuple[List[str], List[str]]":
    """
    Pre-flight size check with largest-first, single-pass-per-file compression.

    Algorithm:
      1. If sum(file sizes) <= max_bytes → return originals unchanged.
      2. Sort files by size descending.
      3. Compress the largest uncompressed file (PDF: 96 DPI re-render;
         image: JPEG quality=75).  Each file is compressed at most once.
      4. After each compression, recalculate total.  Stop as soon as total
         drops below max_bytes — or when all files have been compressed once.
      5. Warn if still over limit after exhausting all compressions.

    Returns:
        (working_paths, temp_files)
        Caller MUST delete every path in temp_files when done.
    """
    _pdf_exts = {".pdf"}
    _image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}

    valid = [f for f in file_paths if os.path.isfile(f)]
    if not valid:
        return [], []

    orig_sizes = {f: os.path.getsize(f) for f in valid}
    total = sum(orig_sizes.values())
    limit_mb = max_bytes / (1024 * 1024)

    log_fn(
        f"[merge pre-flight] {len(valid)} files, "
        f"total {total / (1024*1024):.1f}MB (limit: {limit_mb:.0f}MB)"
    )

    if total <= max_bytes:
        log_fn("[merge pre-flight] Within limit — no compression needed.")
        return list(valid), []

    log_fn(
        f"[merge pre-flight] Exceeds limit by "
        f"{(total - max_bytes) / (1024*1024):.1f}MB — "
        f"starting targeted compression (largest-first, one pass each)."
    )

    # working_map: original_path → current path (may be a compressed tmp)
    working_map: Dict[str, str] = {f: f for f in valid}
    temp_files: List[str] = []
    compressed: Set[str] = set()  # originals already processed

    # Sort originals largest-first; this order is fixed for the whole loop
    sorted_by_size = sorted(valid, key=lambda f: orig_sizes[f], reverse=True)

    for original in sorted_by_size:
        # Recalculate current total using working paths
        current_total = sum(
            os.path.getsize(working_map[f])
            for f in valid
            if os.path.isfile(working_map[f])
        )
        if current_total <= max_bytes:
            log_fn(
                f"[merge pre-flight] Total now "
                f"{current_total / (1024*1024):.1f}MB — within limit. Done."
            )
            break

        if original in compressed:
            continue  # already had one compression pass

        ext = Path(original).suffix.lower()
        fname = Path(original).name
        orig_sz = orig_sizes[original]

        out_tmp = tempfile.NamedTemporaryFile(
            suffix=ext if ext in _image_exts else ".pdf",
            delete=False,
            prefix="_cmp_",
        )
        out_tmp.close()

        success = False
        if ext in _pdf_exts:
            success = _compress_pdf_for_upload(original, out_tmp.name)
        elif ext in _image_exts:
            success = _compress_image_for_upload(original, out_tmp.name)

        compressed.add(original)

        if success and os.path.isfile(out_tmp.name):
            new_sz = os.path.getsize(out_tmp.name)
            savings_mb = (orig_sz - new_sz) / (1024 * 1024)
            log_fn(
                f"[merge pre-flight] Compressed {fname}: "
                f"{orig_sz / 1024:.0f}KB → {new_sz / 1024:.0f}KB "
                f"(saved {savings_mb:.2f}MB)"
            )
            working_map[original] = out_tmp.name
            temp_files.append(out_tmp.name)
        else:
            log_fn(f"[merge pre-flight] Could not compress {fname} — keeping original.")
            try:
                os.remove(out_tmp.name)
            except OSError:
                pass

    # Final report
    final_total = sum(
        os.path.getsize(working_map[f])
        for f in valid
        if os.path.isfile(working_map[f])
    )
    if final_total > max_bytes:
        logger.warning(
            "[merge pre-flight] After compressing all files, total is still %.1fMB "
            "(limit %.0fMB). Proceeding — portal may reject if over limit.",
            final_total / (1024 * 1024),
            limit_mb,
        )
    else:
        log_fn(
            f"[merge pre-flight] Final total: "
            f"{final_total / (1024*1024):.1f}MB — within limit."
        )

    working_paths = [working_map[f] for f in valid]
    return working_paths, temp_files
