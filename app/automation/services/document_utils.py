import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

def _compress_pdf_for_upload(pdf_path: str, output_path: str, target_dpi: int = 96) -> bool:
    """
    Re-render every page of a PDF at target_dpi using pypdfium2 + Pillow.
    Scanned image-PDFs compress dramatically; text PDFs compress moderately.
    Returns True on success, False on failure.
    """
    try:
        import pypdfium2 as pdfium  # type: ignore
        from PIL import Image  # type: ignore

        src = pdfium.PdfDocument(pdf_path)
        if len(src) == 0:
            return False

        scale = target_dpi / 72.0  # pypdfium2: scale=1.0 → 72 DPI
        dest = pdfium.PdfDocument.new()
        page_tmps: List[str] = []

        try:
            for i in range(len(src)):
                page = src[i]
                bitmap = page.render(scale=scale)
                pil_img = bitmap.to_pil()
                if pil_img.mode not in ("RGB",):
                    pil_img = pil_img.convert("RGB")
                # Pillow saves RGB PDFs with DCT (JPEG) compression internally
                tf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix=f"_cmp{i}_")
                tf.close()
                pil_img.save(tf.name, "PDF")
                page_tmps.append(tf.name)
                dest.import_pages(pdfium.PdfDocument(tf.name))

            dest.save(output_path)
            return True
        finally:
            for t in page_tmps:
                try:
                    os.remove(t)
                except OSError:
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
