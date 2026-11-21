"""Page geometry for OIC survey reports from native PDF text or local OCR."""

from dataclasses import dataclass, replace
from bisect import bisect_right
from pathlib import Path
import re
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class Line:
    page: int
    top: float
    cells: tuple[tuple[float, float, str], ...]
    confidence: float = 1
    extra_page: int = 0

    @property
    def text(self):
        return " ".join(cell[2] for cell in self.cells)

    @property
    def source(self):
        suffix = f" + p{self.extra_page}" if self.extra_page else ""
        return f"PDF p{self.page}{suffix}" + (" (OCR)" if self.confidence < 1 else "")


@dataclass(frozen=True)
class Table:
    page: int
    tops: tuple[float, ...]
    rows: tuple[tuple[str, ...], ...]
    confidence: float = 1
    extra_page: int = 0
    row_scores: tuple[float, ...] = ()
    row_boxes: tuple[tuple[tuple[float, float, float, float] | None, ...], ...] = ()

    @property
    def source(self):
        suffix = f" + p{self.extra_page}" if self.extra_page else ""
        return f"PDF p{self.page}{suffix}" + (" (OCR)" if self.confidence < 1 else "")

    def score(self, row):
        return self.row_scores[row] if self.row_scores else self.confidence


@dataclass(frozen=True)
class Page:
    lines: tuple[Line, ...]
    tables: tuple[Table, ...]
    width: float


def compact(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _join_text(cell):
    return " ".join(str(cell or "").split())


def _native_lines(page, number):
    from pdfplumber.utils import extract_words

    for row in page.extract_text_lines(x_tolerance=2, y_tolerance=3):
        text = row["text"]
        if not text.strip() or text.count("\ufffd") > len(text) / 20:
            continue
        words = extract_words(row["chars"], x_tolerance=2, y_tolerance=3)
        cells = []
        for word in words:
            left, right = word["x0"], word["x1"]
            if cells and left - cells[-1][1] < 12:
                start, _, value = cells.pop()
                cells.append((start, right, f'{value} {word["text"]}'))
            else:
                cells.append((left, right, word["text"]))
        yield Line(number, (row["top"] + row["bottom"]) / 2,
                   tuple(cells) or ((row["x0"], row["x1"], text),))


def _scan_regions(page, lines):
    """Find substantial raster areas which lack a usable native text layer."""
    images = []
    regions = []
    page_area = page.width * page.height
    for image in page.images:
        left, top = max(0, image["x0"]), max(0, image["top"])
        right, bottom = min(page.width, image["x1"]), min(page.height, image["bottom"])
        if right <= left or bottom <= top:
            continue
        images.append((left, top, right, bottom))
        if (right - left) * (bottom - top) < page_area * .035:
            continue
        covered = [line for line in lines if top <= line.top <= bottom and any(
            left <= (x0 + x1) / 2 <= right for x0, x1, _ in line.cells
        )]
        bands = {min(3, int(4 * (line.top - top) / (bottom - top))) for line in covered}
        if len(covered) < 4 or len(bands) < 3:
            regions.append((left, top, right, bottom))
    # A short native letterhead/footer can be spread across a full-page scan.
    # Count its text as well as its positions, including PDFs stored as small raster tiles.
    sparse_native = sum(len(line.text.strip()) for line in lines) < 120
    if sparse_native and sum((right - left) * (bottom - top) for left, top, right, bottom in images) >= page_area * .35:
        return images

    areas = [(right - left) * (bottom - top) / page_area for left, top, right, bottom in regions]
    return regions if areas and (max(areas) >= .14 or sum(areas) >= .24) else []


def _merge_ocr_lines(native, recognized, regions):
    """Keep native text and add OCR boxes from uncovered raster regions."""
    merged = list(native)
    for line in recognized:
        cells = []
        nearby = [i for i, other in enumerate(native) if abs(other.top - line.top) <= 4]
        for x0, x1, text in line.cells:
            center = (x0 + x1) / 2
            if not any(left <= center <= right and top <= line.top <= bottom
                       for left, top, right, bottom in regions):
                continue
            if any(x0 < right and x1 > left for i in nearby for left, right, _ in native[i].cells):
                continue
            cells.append((x0, x1, text))
        if not cells:
            continue
        if len(nearby) == 1:
            i = nearby[0]
            original = merged[i]
            merged[i] = replace(original, cells=tuple(sorted((*original.cells, *cells))),
                                confidence=min(original.confidence, line.confidence))
        else:
            merged.append(replace(line, cells=tuple(cells)))
    return tuple(sorted(merged, key=lambda line: line.top))


def _ocr_page(page, number, image_path):
    from app.automation.ocr_engine import run_shared_ocr

    scale = min(3.2, 2400 / page.get_width())
    bitmap = page.render(scale=scale, rotation=0)
    try:
        with bitmap.to_pil() as image:
            image.save(image_path)
    finally:
        bitmap.close()
    groups = []
    result = run_shared_ocr(str(image_path), cls=True)
    for box, (text, confidence) in result[0] or []:
        text = _join_text(text)
        if not text:
            continue
        x0, x1 = min(p[0] for p in box) / scale, max(p[0] for p in box) / scale
        y = sum(p[1] for p in box) / (4 * scale)
        groups.append((y, x0, x1, text, min(float(confidence), .9999)))

    lines = []
    current = []
    for group in sorted(groups):
        if current and group[0] - current[0][0] > 4:
            lines.append(_ocr_line(number, current))
            current = []
        current.append(group)
    if current:
        lines.append(_ocr_line(number, current))
    return tuple(lines), _ocr_tables(image_path, number, scale, groups)


def _ocr_line(number, groups):
    cells = tuple((x0, x1, text) for _, x0, x1, text, _ in sorted(groups, key=lambda g: g[1]))
    return Line(number, sum(g[0] for g in groups) / len(groups), cells, min(g[4] for g in groups))


def _line_positions(lengths, minimum):
    positions = []
    start = None
    for index, length in enumerate([*lengths, 0]):
        if length >= minimum:
            if start is None:
                start = index
        elif start is not None:
            positions.append((start + index - 1) / 2)
            start = None
    return positions


def _ocr_tables(image_path, number, scale, groups):
    """Use printed ruling lines to place OCR tokens in scanned table cells."""
    import cv2

    # imdecode handles Windows paths with non-ASCII user names.
    import numpy as np
    pixels = np.frombuffer(image_path.read_bytes(), dtype=np.uint8)
    image = cv2.imdecode(pixels, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return []
    height, width = image.shape
    _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(12, width // 35), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(12, height // 65))))
    grid = cv2.bitwise_or(horizontal, vertical)
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables = []
    for x, y, w, h in sorted((cv2.boundingRect(contour) for contour in contours), key=lambda box: (box[1], box[0])):
        if w < width * .09 or h < height * .026:
            continue
        ys = [y + cut for cut in _line_positions(np.count_nonzero(horizontal[y:y+h, x:x+w], axis=1), w * .36)]
        xs = [x + cut for cut in _line_positions(np.count_nonzero(vertical[y:y+h, x:x+w], axis=0), h * .22)]
        if len(ys) < 3 or len(xs) < 2:
            continue
        row_count, column_count = len(ys) - 1, len(xs) - 1
        cells = [[[] for _ in range(column_count)] for _ in range(row_count)]
        scores = [0.9999] * row_count
        for center_y, left, right, value, score in groups:
            cy, cx = center_y * scale, (left + right) * scale / 2
            row, col = bisect_right(ys, cy) - 1, bisect_right(xs, cx) - 1
            if 0 <= row < row_count and 0 <= col < column_count:
                cells[row][col].append((center_y, left, value))
                if re.search(r"[A-Za-z0-9]", value):
                    scores[row] = min(scores[row], score)
        rows = tuple(tuple(" ".join(word[2] for word in sorted(cell, key=lambda item: (round(item[0] / 3), item[1])))
                           for cell in row) for row in cells)
        if any(any(row) for row in rows):
            tables.append(Table(number, tuple(top / scale for top in ys[:-1]), rows, .9999, row_scores=tuple(scores)))
    return tables


def read_pages(path, *, stop_cb=None, max_pages=None):
    import pdfplumber
    import pypdfium2

    with pdfplumber.open(path) as document, TemporaryDirectory(prefix="oic-pdf-") as temp:
        renderer = None
        try:
            pages = []
            for index, page in enumerate(document.pages[:max_pages], 1):
                if stop_cb and stop_cb():
                    raise InterruptedError("PDF reading cancelled")
                lines = tuple(_native_lines(page, index))
                regions = _scan_regions(page, lines)
                tables = []
                if lines:
                    for table in page.find_tables():
                        rows = tuple(tuple(_join_text(cell) for cell in row) for row in table.extract(x_tolerance=2))
                        if any(any(row) for row in rows):
                            tables.append(Table(index, tuple(row.bbox[1] for row in table.rows), rows,
                                                row_boxes=tuple(tuple(row.cells) for row in table.rows)))
                if regions or (not lines and bool(page.chars or page.images or page.curves)):
                    if renderer is None:
                        renderer = pypdfium2.PdfDocument(path)
                    rendered_page = renderer[index - 1]
                    try:
                        recognized, scanned_tables = _ocr_page(rendered_page, index, Path(temp) / "page.png")
                    finally:
                        rendered_page.close()
                    if stop_cb and stop_cb():
                        raise InterruptedError("PDF reading cancelled")
                    lines = _merge_ocr_lines(lines, recognized, regions) if lines else recognized
                    tables.extend(table for table in scanned_tables
                                  if not any(_aligned(table, other) for other in tables))
                pages.append(Page(lines, tuple(tables), page.width))
                page.close()
            return _join_print_tiles(pages)
        finally:
            if renderer is not None:
                renderer.close()


def _aligned(left, right):
    return len(left.tops) == len(right.tops) and all(
        abs(a - b) <= 2.5 for a, b in zip(left.tops, right.tops)
    )


def _print_evidence(left, right):
    left_labels = {compact(line.text) for line in left.lines}
    right_labels = {compact(line.text) for line in right.lines}
    if (any("partsname" in text and "estimated" in text for text in left_labels)
            and any(text in {"srnogst", "snogst"} for text in right_labels)):
        return "parts"
    if (any("denting" in text and text.endswith("cw") for text in left_labels)
            and any(text in {"paintgst", "paintinggst"} for text in right_labels)):
        return "labour"
    if (any("gstsummaryspares" in text for text in left_labels)
            and "totalamount" in right_labels):
        return "gst"
    return ""


def _join_print_tiles(pages):
    """Join Excel print overflow only when independent sections verify the same split."""
    candidates = []
    for offset in range(2, len(pages) // 2 + 1):
        pairs = list(zip(pages[:offset], pages[offset:2 * offset]))
        evidence = {_print_evidence(left, right) for left, right in pairs} - {""}
        if len(evidence) >= 2:
            candidates.append((len(evidence), offset, pairs))
    if not candidates:
        return pages
    candidates.sort(key=lambda item: item[0], reverse=True)
    count, offset, pairs = candidates[0]
    if len(candidates) > 1 and candidates[1][0] == count:
        return pages

    joined = []
    for left, right in pairs:
        if not right.lines:
            joined.append(left)
            continue
        right_number = right.lines[0].page
        lines = list(left.lines)
        for continuation in right.lines:
            if continuation.cells[-1][1] < 0:
                continue
            candidates = [i for i, line in enumerate(lines) if abs(line.top - continuation.top) <= 3.7]
            if len(candidates) == 1:
                index = candidates[0]
                original = lines[index]
                next_text = compact(continuation.text)
                if next_text in compact(original.text):
                    continue
                extra = tuple((x0 + left.width, x1 + left.width, text) for x0, x1, text in continuation.cells if x1 > 0)
                if extra:
                    cells = original.cells
                    # A vector continuation can retain a full value outside its
                    # visible crop while OCR sees only the left side's prefix.
                    if original.confidence < 1 and continuation.confidence == 1 and len(cells) > 1 and extra[0][0] < left.width:
                        prefix = compact(cells[-1][2])
                        if len(prefix) >= 8 and next_text.startswith(prefix):
                            cells = cells[:-1]
                    lines[index] = replace(original, cells=cells + extra, extra_page=right_number,
                                           confidence=min(original.confidence, continuation.confidence))
            elif not candidates and continuation.cells[0][0] >= 0:
                # Useful only when the right side has a labelled line of its
                # own. Loose amounts are handled by aligned table cells.
                if re.search(r"[A-Za-z]{3}", continuation.text):
                    lines.append(continuation)

        tables = []
        for table in left.tables:
            candidates = [extra for extra in right.tables if _aligned(table, extra)]
            if len(candidates) == 1:
                extra = candidates[0]
                rows = tuple(a + b for a, b in zip(table.rows, extra.rows))
                scores = tuple(min(table.score(i), extra.score(i)) for i in range(len(rows)))
                table = replace(table, rows=rows, extra_page=extra.page, row_boxes=(),
                                confidence=min(table.confidence, extra.confidence), row_scores=scores)
            tables.append(table)
        joined.append(Page(tuple(sorted(lines, key=lambda line: line.top)), tuple(tables), left.width + right.width))
    return joined + pages[2 * offset:]
