"""Identify OIC vehicle photographs and prepare a portal-compatible image."""

import filecmp
import os
import re
import tempfile
from pathlib import Path


IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
PHOTO_SOURCE_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


def photo_sources(folder, mapped_path=None):
    """Return distinct photo files, preferring images accepted by the portal."""
    if not folder or not os.path.isdir(folder):
        return []
    candidates = []
    if mapped_path and os.path.isfile(mapped_path):
        candidates.append(str(mapped_path))
    for name in sorted(os.listdir(folder), key=str.casefold):
        path = os.path.join(folder, name)
        lower = name.casefold()
        if not os.path.isfile(path) or Path(name).suffix.lower() not in PHOTO_SOURCE_EXTENSIONS:
            continue
        if not ("photo" in lower or "vehicle" in lower or "vehical" in lower):
            continue
        if re.search(r"\b(?:rc|registration|license|licence)\b", re.sub(r"[_-]", " ", lower)):
            continue
        candidates.append(path)
    # Prefer original names over generated vehicle_photo_1..4 copies.
    candidates.sort(key=lambda p: (
        Path(p).suffix.lower() not in IMAGE_EXTENSIONS,
        bool(re.match(r"^vehicle_photo_[1-4]\.", Path(p).name, re.I)),
        Path(p).name.casefold(),
    ))
    unique = []
    for path in candidates:
        if Path(path).suffix.lower() not in PHOTO_SOURCE_EXTENSIONS:
            continue
        if any(os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(old))
               or filecmp.cmp(path, old, shallow=False) for old in unique):
            continue
        unique.append(path)
    return unique


def prepare_photo(source):
    """Return (upload path, temporary path); PDF images are extracted or rendered."""
    ext = Path(source).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return source, None
    from PIL import Image, ImageOps
    if ext == ".pdf":
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument(source)
        try:
            if not len(document):
                raise ValueError("Photo PDF has no pages")
            page = document[0]
            try:
                try:
                    images = []
                    for obj in page.get_objects():
                        if isinstance(obj, pdfium.PdfImage):
                            x0, y0, x1, y1 = obj.get_bounds()
                            images.append(((x1 - x0) * (y1 - y0), obj))
                    if not images:
                        raise ValueError("No embedded photo on first page")
                    image = max(images, key=lambda item: item[0])[1].get_bitmap(render=True).to_pil().copy()
                except Exception:
                    # A page may be a scanned collage or use unsupported image
                    # encodings. Preserve it as rendered rather than losing it.
                    image = page.render(scale=2).to_pil().copy()
            finally:
                page.close()
        finally:
            document.close()
    else:
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
    fd, path = tempfile.mkstemp(prefix="oic_vehicle_photo_", suffix=".jpg")
    os.close(fd)
    try:
        image.convert("RGB").save(path, "JPEG", quality=90, optimize=True)
    except Exception:
        os.unlink(path)
        raise
    finally:
        image.close()
    return path, path
