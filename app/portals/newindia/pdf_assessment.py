"""Extract New India spare parts, labour charges, and GST from a survey PDF."""

from dataclasses import replace
from decimal import Decimal
import re
from typing import Optional

from app.data.excel_parts_extractor import coerce_hsn_code
from app.portals.oic.pdf_layout import Table, compact
from app.utils import load_automation_defaults


PART_COLUMNS = {
    "serial": ("sn", "sno", "srno", "slno", "serialno", "sr", "no", "sl"),
    "name": (
        "partsname",
        "partname",
        "partdescription",
        "partsdescription",
        "partdiscription",
        "partsdiscription",
        "nameofdamagedpartswhichareassessednew",
        "nameofdamagedparts",
        "description",
        "discription",
        "particular",
        "particulars",
        "itemdescription",
    ),
    "estimate": ("estimated", "estimate", "estimatedamount", "estimateamount", "estamount", "estamt"),
    "metal": (
        "mage",
        "magewise",
        "metal",
        "metallic",
        "metalamount",
        "metallicparts",
        "metalparts",
        "metalparts0dep",
        "metalparts35dep",
    ),
    "plastic": (
        "p50",
        "plastic",
        "plastic50",
        "plasticamount",
        "plasticrubber",
        "rubberplastic",
        "rubberplastic50dep",
    ),
    "fiber": ("fiber", "fibre", "fibber", "fiber30", "fibre30", "fibber30", "fibber30dep", "fiber30dep", "fibre30dep"),
    "glass": (
        "g0",
        "glass",
        "glass0",
        "glassamount",
        "glassparts",
        "glasspartsnilldep",
        "glasspartsnildep",
    ),
}

LABOUR_COLUMNS = {
    "serial": PART_COLUMNS["serial"],
    "name": (
        "description",
        "particularsoflabourcharges",
        "labourdescription",
        "labordescription",
        "particulars",
        "itemdescription",
    ),
    "estimate": PART_COLUMNS["estimate"],
    "rr": ("rr", "removerefit", "removalrefitting", "removalreplacement", "openingfitting"),
    "denting": ("denting", "dent"),
    "cw": ("cw", "cuttingwelding", "cuttingandwelding"),
    "paint": ("paint", "painting", "paintingcharges", "paintamount"),
}

GST_COLUMNS = {
    "tax_pct": ("taxpercentage", "tax", "gstpercentage", "gst"),
    "taxable": ("taxableamount", "taxableamt", "taxablevalue", "amountbeforegst", "taxable"),
    "cgst": ("cgst", "centralgst", "cgstamount"),
    "sgst": ("sgst", "stategst", "sgstamount"),
    "igst": ("igst", "integratedgst", "igstamount"),
    "total": ("totalamount", "total"),
}

MATERIAL_DESCRIPTIONS = {
    "metal": "Parts at Agewise Depreciation",
    "plastic": "Parts at 50% Depreciation",
    "fiber": "Parts at 30% Depreciation",
    "glass": "Parts at Cost",
}
MATERIAL_ORDER = ("metal", "plastic", "fiber", "glass")
REQUIRED_PART_KEYS = ("serial", "name", "metal", "plastic", "glass")
REQUIRED_LABOUR_KEYS = ("serial", "name", "rr", "denting", "cw")
ZERO = Decimal(0)
TOLERANCE = Decimal(".02")
TOTAL_LABELS = {
    "subtotal",
    "total",
    "subtotalbeforegst",
    "totalbeforegst",
    "totalbeforediscount",
    "grandtotal",
}
STOP_TOTAL_LABELS = {
    "addgst",
    "gst",
    "lessdepreciation",
    "nettotal",
    "netforparts",
    "totalnetforparts",
    "netforlabour",
    "totalamountoflabourassessed",
}
SECTION_BREAK_PREFIXES = (
    "labourcharges",
    "labordetails",
    "spareparts",
    "partsdetails",
    "summaryofassessment",
    "gstsummary",
    "finalsurveybill",
    "surveyfeebill",
)
AMOUNT_RX = re.compile(r"(?:\d+|\d{1,3}(?:,\d{2,3})*,\d{3})(?:\.\d{1,2})?")


def amount(value) -> Optional[Decimal]:
    """Parse a clean monetary/numeric amount, supporting Indian commas and currency prefixes."""
    text = re.sub(r"^(?:INR|Rs\.?|₹)\s*", "", str(value or "").strip(), flags=re.I)
    text = re.sub(r"(?<=\d)\s+(?=[.,])|(?<=[.,])\s+(?=\d)", "", text)
    if not text or not AMOUNT_RX.fullmatch(text):
        return None
    return Decimal(text.replace(",", ""))


def _cell_matches_alias(text: str, options: tuple[str, ...]) -> bool:
    if not text:
        return False
    if text in options:
        return True
    # Classic two-row headers include depreciation suffixes like "metalparts35dep" or "glasspartsnilldep".
    for prefix in ("metalparts", "rubberplastic", "plasticrubber", "glassparts", "fibber", "fibre", "fiber"):
        if prefix in options and text.startswith(prefix):
            return True
    return False


def _columns(row: tuple[str, ...], aliases: dict[str, tuple[str, ...]]) -> dict[str, int]:
    normalized = [compact(value) for value in row]
    positions = {}
    for key, options in aliases.items():
        matches = [i for i, value in enumerate(normalized) if _cell_matches_alias(value, options)]
        if key == "serial" and "name" in aliases:
            descriptions = [i for i, value in enumerate(normalized) if _cell_matches_alias(value, aliases["name"])]
            if len(descriptions) == 1:
                matches = [i for i in matches if i < descriptions[0]]
        if len(matches) == 1:
            positions[key] = matches[0]
    return positions


def _merged_header_row(row: tuple[str, ...], next_row: Optional[tuple[str, ...]]) -> tuple[str, ...]:
    if not next_row or len(next_row) != len(row):
        return row
    combined = []
    for top, bottom in zip(row, next_row):
        top_text = str(top or "").strip()
        bottom_text = str(bottom or "").strip()
        # Group-span headers like "Assessed" sit above sub-columns ("Glass Parts",
        # "Opening/Fitting"); keep the specific sub-column label when present.
        if bottom_text and (not top_text or compact(top_text) in {"assessed", "estimated"}):
            combined.append(bottom_text)
        elif top_text and bottom_text:
            combined.append(f"{top_text} {bottom_text}")
        else:
            combined.append(top_text or bottom_text)
    return tuple(combined)


def _infer_serial_column(
    row: tuple[str, ...],
    next_first_cell: str,
    cols: dict[str, int],
    required: tuple[str, ...],
) -> dict[str, int]:
    """Infer column 0 as serial when OCR corrupts its short header (e.g. 'NS') before row '1'."""
    if "serial" in cols:
        return cols
    if not all(key in cols for key in required if key != "serial"):
        return cols
    if cols.get("name") != 1 or 0 in cols.values() or len(row) <= 1 or len(compact(row[0])) > 6:
        return cols
    first = str(next_first_cell or "").strip()
    if first.rstrip(".") == "1" or re.match(r"^1\s*[.)]?\s+\S", first):
        return {**cols, "serial": 0}
    return cols


def _match_header(
    rows: tuple[tuple[str, ...], ...],
    index: int,
    aliases: dict[str, tuple[str, ...]],
    required: tuple[str, ...],
) -> Optional[tuple[dict[str, int], int]]:
    """Match a single-row or two-row merged header starting at `index`."""
    row = rows[index]
    direct = _columns(row, aliases)
    next_first = rows[index + 1][0] if index + 1 < len(rows) and rows[index + 1] else ""
    direct = _infer_serial_column(row, next_first, direct, required)
    if all(key in direct for key in required):
        return direct, index

    if index + 1 < len(rows):
        nxt = rows[index + 1]
        # Only merge when row `index+1` actually contributes sub-column labels
        # and does not start with a serial number or subtotal.
        first_cell = compact(nxt[0]) if nxt else ""
        if not first_cell.isdecimal() and first_cell not in TOTAL_LABELS:
            merged = _merged_header_row(row, nxt)
            merged_cols = _columns(merged, aliases)
            after_merged_first = rows[index + 2][0] if index + 2 < len(rows) and rows[index + 2] else ""
            merged_cols = _infer_serial_column(merged, after_merged_first, merged_cols, required)
            if all(key in merged_cols for key in required) and len(merged_cols) > len(direct):
                return merged_cols, index + 1
    return None


def _total_cell_label(cell_text: str) -> str:
    """Return canonical total/stop label if `cell_text` is a subtotal/total row marker."""
    raw = str(cell_text or "").strip()
    if not raw:
        return ""
    first_line = raw.splitlines()[0].strip()
    comp = compact(first_line)
    if comp in TOTAL_LABELS or comp in STOP_TOTAL_LABELS:
        return comp
    for prefix in ("totalbeforediscount", "totalbeforegst", "subtotalbeforegst", "subtotal", "grandtotal"):
        if comp.startswith(prefix):
            return prefix
    for prefix in ("totalafterdiscount", "netforparts", "totalnetforparts", "netforlabour", "totalamountoflabourassessed"):
        if comp.startswith(prefix):
            return prefix
    return ""


def _open_header(table: Table) -> Optional[tuple[int, dict[str, int]]]:
    for index in range(len(table.rows) - 1, -1, -1):
        row = table.rows[index]
        if any(_total_cell_label(cell) in TOTAL_LABELS for cell in row):
            break
        for aliases, required in (
            (PART_COLUMNS, REQUIRED_PART_KEYS),
            (LABOUR_COLUMNS, REQUIRED_LABOUR_KEYS),
        ):
            matched = _match_header(table.rows, index, aliases, required)
            if matched is not None:
                positions, end_index = matched
                return end_index, positions
        headers = _columns(row, GST_COLUMNS)
        if len(headers) >= 2 and "taxable" in headers and 0 not in headers.values():
            if any(_gst_section(" ".join(v for v in prev if v)) for prev in table.rows[:index]):
                return index, headers
    return None


def _aligned_cell(box, boxes) -> Optional[int]:
    if box is None:
        return None
    matches = [
        i
        for i, cell in enumerate(boxes)
        if cell is not None and abs(cell[0] - box[0]) <= 2 and abs(cell[2] - box[2]) <= 2
    ]
    return matches[0] if len(matches) == 1 else None


def _printed_serial(lines, serial_box, row_box, name: str) -> str:
    """Recover an orphaned printed serial digit on the same row as a page break."""
    candidates = set()
    for line in lines:
        if (
            line.confidence < 1
            or not row_box[1] <= line.top < row_box[3]
            or not serial_box[0] <= line.cells[0][0] < serial_box[2]
        ):
            continue
        match = re.match(r"^(\d+)\s+(.+)$", line.text)
        if match and match[2].startswith(name + " "):
            candidates.add(match[1])
    return candidates.pop() if len(candidates) == 1 else ""


def _split_merged_line_to_boxes(line_cells, header_boxes, positions) -> Optional[list[str]]:
    """Project `Page.lines` cells into `header_boxes` when a continuation row lost column rules."""
    projected = [""] * len(header_boxes)
    serial_col = positions.get("serial")
    name_col = positions.get("name")
    for x0, x1, text in line_cells:
        center = (x0 + x1) / 2
        if (
            serial_col is not None
            and name_col is not None
            and header_boxes[serial_col] is not None
            and header_boxes[name_col] is not None
            and x0 < header_boxes[name_col][0] + 4
        ):
            merged = re.match(r"^\s*(\d+)\s*[.)]?\s+(.+)$", text)
            if merged:
                projected[serial_col] = merged.group(1)
                projected[name_col] = f"{projected[name_col]} {merged.group(2).strip()}".strip()
                continue
        best_col = None
        for col_idx, box in enumerate(header_boxes):
            if box is None:
                continue
            if box[0] - 4 <= center <= box[2] + 4:
                best_col = col_idx
                break
        if best_col is None:
            valid_boxes = [(idx, box) for idx, box in enumerate(header_boxes) if box is not None]
            if valid_boxes:
                best_col = min(valid_boxes, key=lambda item: abs((item[1][0] + item[1][2]) / 2 - center))[0]
        if best_col is not None:
            projected[best_col] = f"{projected[best_col]} {text}".strip()
    return projected if any(projected) else None


def _project_continuation(table: Table, index: int, header_boxes, positions, lines) -> Optional[tuple[str, ...]]:
    row, boxes = table.rows[index], table.row_boxes[index]
    # Repair rows whose top border was unclosed in the source PDF so pdfplumber merged
    # all cells into column 0, while `Page.lines` retains exact x coordinates.
    if row and row[0] and all(not cell for cell in row[1:]) and lines and index < len(table.tops):
        row_box = boxes[0]
        matching_lines = [
            line
            for line in lines
            if (row_box[1] <= line.top <= row_box[3] if row_box else abs(line.top - table.tops[index]) <= 10.0)
            and re.match(r"^\s*\d+\s*[.)]?\s+\S", line.text)
        ]
        if len(matching_lines) == 1:
            repaired = _split_merged_line_to_boxes(matching_lines[0].cells, header_boxes, positions)
            if repaired is not None:
                return tuple(repaired)

    projected = [""] * len(header_boxes)
    serial_column, name_column = positions.get("serial"), positions.get("name")
    name_box = header_boxes[name_column] if name_column is not None else None
    serial_box = header_boxes[serial_column] if serial_column is not None else None
    subtotal = next(
        (
            cell
            for cell, box in zip(row, boxes)
            if name_box
            and serial_box
            and box
            and _total_cell_label(cell) in TOTAL_LABELS
            and abs(box[0] - serial_box[0]) <= 2
            and abs(box[2] - name_box[2]) <= 2
        ),
        "",
    )
    if not subtotal:
        subtotal = next(
            (cell for cell in row if _total_cell_label(cell) in TOTAL_LABELS),
            "",
        )
    for key, column in positions.items():
        if key == "serial":
            continue
        if key == "name" and subtotal:
            projected[column] = subtotal
            continue
        match = _aligned_cell(header_boxes[column], boxes)
        if match is None:
            return None
        projected[column] = row[match]

    if "serial" not in positions:
        match = _aligned_cell(header_boxes[0], boxes)
        if match is None or (compact(row[match]) not in TOTAL_LABELS and amount(row[match]) is None):
            return None
        projected[0] = row[match]
        return tuple(projected)

    if serial_box is None or not projected[name_column]:
        return None
    if _row_total_label(projected, positions) in TOTAL_LABELS:
        return tuple(projected)
    match = _aligned_cell(serial_box, boxes)
    if match is not None:
        projected[serial_column] = row[match]
    elif index == 0:
        name_match = _aligned_cell(name_box, boxes)
        if name_match is not None:
            projected[serial_column] = _printed_serial(lines, serial_box, boxes[name_match], projected[name_column])
    serial_clean = projected[serial_column].strip().rstrip(".")
    if not serial_clean.isdecimal():
        return None
    projected[serial_column] = serial_clean
    return tuple(projected)


def _continue_native_table(table: Table, following: tuple[Table, ...], lines_by_page: dict) -> Table:
    header = _open_header(table)
    if header is None:
        return table
    header_index, positions = header
    header_boxes = table.row_boxes[header_index]
    # For two-row headers, take sub-column boxes from the lower row where available.
    if header_index > 0 and len(table.row_boxes[header_index - 1]) == len(header_boxes):
        merged_boxes = []
        for top_box, sub_box in zip(table.row_boxes[header_index - 1], header_boxes):
            merged_boxes.append(sub_box or top_box)
        header_boxes = tuple(merged_boxes)

    page = table.page
    rows = []
    tops = []
    for next_table in following:
        if not next_table.row_boxes or next_table.page != page + 1:
            break
        page = next_table.page
        for index in range(len(next_table.rows)):
            row = _project_continuation(next_table, index, header_boxes, positions, lines_by_page.get(page, ()))
            if row is None:
                return table
            tops.append(next_table.tops[index])
            total_lbl = _row_total_label(row, positions)
            if total_lbl in TOTAL_LABELS:
                if "serial" not in positions:
                    detail = (*table.rows[header_index + 1 :], *rows)
                    if not detail or any(amount(entry[0]) is None for entry in detail):
                        return table
                    for column in positions.values():
                        amounts = [_cell_line_amount(entry[column], 0) if entry[column] else ZERO for entry in detail]
                        total = _cell_line_amount(row[column], 0) if row[column] else ZERO
                        if total is None or None in amounts or abs(sum(amounts, ZERO) - total) > TOLERANCE:
                            return table
                return replace(
                    table,
                    rows=(*table.rows, *rows, row),
                    tops=(*table.tops, *tops),
                    extra_page=page,
                    row_boxes=(),
                )
            rows.append(row)
    return table


def _assessment_tables(pages) -> tuple[Table, ...]:
    tables = tuple(table for page in pages for table in page.tables)
    lines_by_page = {page.lines[0].page: page.lines for page in pages if page.lines}
    result = []
    for index, table in enumerate(tables):
        if table.row_boxes and index + 1 < len(tables) and tables[index + 1].page == table.page + 1:
            table = _continue_native_table(table, tables[index + 1 :], lines_by_page)
        result.append(table)
    return tuple(result)


def _gst_section(text: str) -> str:
    marker = compact(text)
    if "gstsummary" not in marker:
        return ""
    if "spare" in marker or "part" in marker:
        return "spares"
    if "labour" in marker or "labor" in marker:
        return "labour"
    return ""


def _positional_tables(pages) -> list[Table]:
    """Recover borderless/OCR assessment and GST tables across one or consecutive pages."""
    out: list[Table] = []
    # 1. GST summary tables (single-page or immediately below heading)
    for page in pages:
        for index, line in enumerate(page.lines):
            if len(line.cells) < 4:
                continue
            heading = tuple(cell[2] for cell in line.cells)
            if len(_columns(heading, GST_COLUMNS)) < 2 or index == 0:
                continue
            title = page.lines[index - 1]
            if not _gst_section(title.text):
                continue
            rows = [(title.text,), heading]
            tops = [title.top, line.top]
            scores = [title.confidence, line.confidence]
            anchors = [(x0 + x1) / 2 for x0, x1, _ in line.cells]
            for entry in page.lines[index + 1 :]:
                row = [""] * len(anchors)
                for x0, x1, value in entry.cells:
                    center = (x0 + x1) / 2
                    col = min(range(len(anchors)), key=lambda i: abs(anchors[i] - center))
                    row[col] = f"{row[col]} {value}".strip()
                rows.append(tuple(row))
                tops.append(entry.top)
                scores.append(entry.confidence)
                if re.search(r"\b(?:sub\s*)?total\b", entry.text, re.I) or _gst_section(entry.text):
                    break
            out.append(Table(line.page, tuple(tops), tuple(rows), min(scores), line.extra_page, row_scores=tuple(scores)))

    # 2. Parts / Labour positional tables — allow multi-page continuation across
    #    pages lacking repeating headers (common in Excel-exported PDFs).
    flat_lines = [(page_idx, line) for page_idx, page in enumerate(pages) for line in page.lines]
    cursor = 0
    while cursor < len(flat_lines):
        _, line = flat_lines[cursor]
        if len(line.cells) < 4:
            cursor += 1
            continue
        heading = tuple(cell[2] for cell in line.cells)
        next_first = (
            flat_lines[cursor + 1][1].cells[0][2]
            if cursor + 1 < len(flat_lines) and flat_lines[cursor + 1][1].cells
            else ""
        )
        part_cols = _infer_serial_column(heading, next_first, _columns(heading, PART_COLUMNS), REQUIRED_PART_KEYS)
        labour_cols = _infer_serial_column(heading, next_first, _columns(heading, LABOUR_COLUMNS), REQUIRED_LABOUR_KEYS)
        is_parts = all(k in part_cols for k in REQUIRED_PART_KEYS)
        is_labour = all(k in labour_cols for k in REQUIRED_LABOUR_KEYS)
        if not is_parts and not is_labour:
            cursor += 1
            continue

        # Build column intervals / anchors from header cells
        col_bounds = [(x0, x1) for x0, x1, _ in line.cells]
        anchors = [(x0 + x1) / 2 for x0, x1 in col_bounds]
        rows = [heading]
        tops = [line.top]
        scores = [line.confidence]
        end_page = line.page
        cursor += 1

        while cursor < len(flat_lines):
            _, entry = flat_lines[cursor]
            text_compact = compact(entry.text)
            if any(text_compact.startswith(prefix) for prefix in SECTION_BREAK_PREFIXES):
                break
            # Skip repeated page headers/footers on continuation pages
            if re.match(r"^(?:page\s+\d+|ref\.?\s*no|vehicle\s*no|surveyor|by\s+autocare|cont\.\.\.)", entry.text.strip(), re.I):
                cursor += 1
                continue

            row = [""] * len(anchors)
            for cell_idx, (x0, x1, value) in enumerate(entry.cells):
                # Split leading "serial name" when serial+name are merged in cell 0
                if cell_idx == 0 and x0 < anchors[1]:
                    merged = re.match(r"^\s*(\d+)\s*[.)]?\s+(.+)$", value)
                    if merged and abs(x0 - col_bounds[0][0]) <= 25:
                        row[0] = merged.group(1)
                        row[1] = f"{row[1]} {merged.group(2).strip()}".strip()
                        continue
                center = (x0 + x1) / 2
                col = min(range(len(anchors)), key=lambda i: abs(anchors[i] - center))
                row[col] = f"{row[col]} {value}".strip()

            end_page = entry.page
            rows.append(tuple(row))
            tops.append(entry.top)
            scores.append(entry.confidence)
            cursor += 1
            if re.search(r"\b(?:sub\s*total|total\s+before\s+gst|total\s+before\s+discount|grand\s+total)\b", entry.text, re.I) or (
                re.match(r"^\s*total\b", entry.text, re.I)
            ):
                break

        extra_page = end_page if end_page != line.page else line.extra_page
        out.append(Table(line.page, tuple(tops), tuple(rows), min(scores), extra_page, row_scores=tuple(scores)))

    return out


def _cell_line_amount(cell_text: str, line_index: int = 0) -> Optional[Decimal]:
    raw = str(cell_text or "").strip()
    if not raw:
        return None
    lines = [part.strip() for part in raw.splitlines() if part.strip()]
    if len(lines) > 1 and 0 <= line_index < len(lines):
        parsed = amount(lines[line_index])
        if parsed is not None:
            return parsed
    tokens = [tok.strip() for tok in raw.split() if tok.strip()]
    if 0 <= line_index < len(tokens):
        parsed = amount(tokens[line_index])
        if parsed is not None:
            return parsed
    return amount(lines[0])


def _row_total_label(row: tuple[str, ...], positions: dict[str, int]) -> str:
    """Return canonical subtotal label if this row represents a pre-GST/pre-discount subtotal."""
    candidate_indices = []
    for key in ("serial", "name"):
        if key in positions and positions[key] < len(row):
            candidate_indices.append(positions[key])
    for idx in range(len(row)):
        if idx not in candidate_indices:
            candidate_indices.append(idx)

    for idx in candidate_indices:
        lbl = _total_cell_label(row[idx])
        if lbl in TOTAL_LABELS or lbl in STOP_TOTAL_LABELS:
            return lbl
    return ""


def _row_subtotal_line_index(row: tuple[str, ...], positions: dict[str, int]) -> int:
    name_idx = positions.get("name", 0)
    raw = str(row[name_idx] or "") if name_idx < len(row) else ""
    lines = [part.strip() for part in raw.splitlines() if part.strip()]
    for idx, text in enumerate(lines):
        if compact(text) in TOTAL_LABELS:
            return idx
    return 0


def _gst_summaries(tables: tuple[Table, ...]) -> tuple[dict, list[str]]:
    results: dict[str, tuple[dict[str, Decimal], str]] = {}
    errors: dict[str, str] = {}
    sources: dict[str, str] = {}

    for table in tables:
        section = ""
        columns: dict[str, int] = {}
        fallback_rows: list[tuple[int, tuple[str, ...]]] = []

        def _process_summary_row(idx: int, r: tuple[str, ...], sec: str, cols: dict[str, int], tbl: Table):
            values = {key: amount(r[i]) if i < len(r) else None for key, i in cols.items() if key != "tax_pct"}
            split_present = values.get("cgst") is not None and values.get("sgst") is not None
            integrated = values.get("igst")
            if (
                values.get("taxable") is None
                or not (split_present or integrated is not None)
                or (not split_present and any(values.get(key) for key in ("cgst", "sgst")))
                or (integrated and any(values.get(key) for key in ("cgst", "sgst")))
                or tbl.score(idx) < 0.78
            ):
                errors[sec] = f"Check the {sec} GST total on {tbl.source}."
                return
            full = {
                key: values.get(key) if values.get(key) is not None else ZERO
                for key in ("taxable", "cgst", "sgst", "igst")
            }
            gst_total = full["cgst"] + full["sgst"] + full["igst"]
            if abs(full["taxable"] * Decimal(".18") - gst_total) > TOLERANCE:
                errors[sec] = f"The {sec} GST total on {tbl.source} does not reconcile with 18% GST."
                return
            if sec in results and results[sec][0] != full:
                errors[sec] = f"Conflicting {sec} GST totals found on {results[sec][1]} and {tbl.source}."
            else:
                results[sec] = (full, tbl.source)

        for index, row in enumerate(table.rows):
            # A merged top cell may hold "GST Summary - LABOUR CHARGES\nTAX Percentage ...\n18.00 ...".
            heading_text = " ".join(v for v in row if v)
            sub_lines = [part.strip() for part in str(row[0] or "").splitlines() if part.strip()] if row else []
            title = _gst_section(sub_lines[0] if len(sub_lines) > 1 else heading_text)
            if title:
                section, columns = title, {}
                fallback_rows = []
                sources.setdefault(section, table.source)
                # Also inspect trailing lines inside merged cell if present
                for sub in sub_lines[1:]:
                    tokens = sub.split()
                    if any(tok.lower() in {"taxable", "cgst", "sgst", "igst"} for tok in tokens):
                        # Wait for structured table row or handle inline
                        pass
                continue
            if not section:
                continue
            headers = _columns(row, GST_COLUMNS)
            if len(headers) >= 2 and "taxable" in headers:
                columns = headers
                fallback_rows = []
                continue
            if not columns:
                continue
            if any(compact(cell) in {"total", "subtotal", "grandtotal"} for cell in row):
                _process_summary_row(index, row, section, columns, table)
                fallback_rows = []
            elif any(amount(cell) is not None for cell in row):
                # Some classic PDFs omit the word "Total" on the summary total row
                # (e.g. ['', '6,508.48', '585.76', '585.76', '0.00', '7,680.01']).
                tax_pct_idx = columns.get("tax_pct")
                if tax_pct_idx is not None and tax_pct_idx < len(row) and not str(row[tax_pct_idx] or "").strip():
                    _process_summary_row(index, row, section, columns, table)
                    fallback_rows = []
                else:
                    fallback_rows.append((index, row))

        if section and section not in results and len(fallback_rows) == 1:
            idx, only_row = fallback_rows[0]
            _process_summary_row(idx, only_row, section, columns, table)

    if results:
        has_split = any(values["cgst"] or values["sgst"] for values, _ in results.values())
        has_integrated = any(values["igst"] for values, _ in results.values())
        if has_split and has_integrated:
            errors["types"] = "The GST summaries mix CGST/SGST and IGST. Check the invoice tax amounts."
    return results, list(errors.values())


def _item_tables(
    tables: tuple[Table, ...],
    aliases: dict[str, tuple[str, ...]],
    required_keys: tuple[str, ...],
    value_keys: tuple[str, ...],
    kind: str,
) -> tuple[Optional[list[tuple[str, dict[str, Decimal], str]]], str, Optional[Decimal]]:
    """Read numbered detail rows up to the pre-GST/pre-discount subtotal, verifying totals."""
    positions: dict[str, int] = {}
    details: list[tuple[str, dict[str, Decimal], str]] = []
    serials: list[int] = []
    header: Optional[Table] = None
    header_end_index = -1
    totals: Optional[dict[str, Optional[Decimal]]] = None
    active_keys: list[str] = []
    sources: list[str] = []
    partial = ""
    gst_from_table: Optional[Decimal] = None

    for table in tables:
        index = 0
        while index < len(table.rows):
            row = table.rows[index]
            # Check if a subtotal has already been collected; watch for Add GST row immediately after.
            if header is not None and totals is not None:
                lbl = _row_total_label(row, positions)
                if lbl in {"addgst", "gst"} and gst_from_table is None:
                    vals = [
                        _cell_line_amount(row[positions[k]], 0)
                        for k in value_keys
                        if k in positions and positions[k] < len(row)
                    ]
                    if any(v is not None for v in vals):
                        gst_from_table = sum((v for v in vals if v is not None), ZERO)
                index += 1
                continue

            matched = _match_header(table.rows, index, aliases, required_keys)
            if matched is not None:
                cols, end_idx = matched
                if header is not None and totals is not None:
                    raise ValueError(
                        f"More than one {kind.lower()} table was found on {header.source} and {table.source}."
                    )
                header = table
                positions = cols
                header_end_index = end_idx
                # Only reconcile value keys actually present in the detected header.
                active_keys = [k for k in ("estimate", *value_keys) if k in positions]
                if table.source not in sources:
                    sources.append(table.source)
                index = end_idx + 1
                continue

            # Partial header detection (e.g. missing a material column)
            partial_cols = _columns(row, aliases)
            if (
                header is None
                and len(partial_cols) >= len(required_keys) - 1
                and "name" in partial_cols
            ):
                if not all(k in partial_cols for k in required_keys):
                    partial = table.source

            if header is None or (table is header and index <= header_end_index):
                index += 1
                continue
            if len(row) <= max(positions.values()):
                index += 1
                continue

            total_lbl = _row_total_label(row, positions)
            if total_lbl in TOTAL_LABELS:
                line_idx = _row_subtotal_line_index(row, positions)
                totals = {
                    key: _cell_line_amount(row[positions[key]], line_idx)
                    for key in active_keys
                }
                if table.source not in sources:
                    sources.append(table.source)
                index += 1
                continue
            if total_lbl in STOP_TOTAL_LABELS:
                # Reached Add GST / Net Total without encountering a pre-GST subtotal.
                break

            serial_raw = row[positions["serial"]].strip()
            serial = serial_raw.rstrip(".")
            name = row[positions["name"]].strip()
            if not serial.isdecimal() or not name:
                index += 1
                continue
            if table.score(index) < 0.78:
                raise ValueError(f"Check the low-confidence {kind.lower()} row {serial} on {table.source}.")

            serial_no = int(serial)
            if serials and serial_no != serials[-1] + 1:
                next_serial = (
                    table.rows[index + 1][positions["serial"]].strip().rstrip(".")
                    if index + 1 < len(table.rows)
                    else ""
                )
                row_vals = [
                    amount(row[positions[key]])
                    for key in value_keys
                    if key in positions
                ]
                if (
                    table.confidence < 1
                    and table.score(index) < 0.90
                    and next_serial == str(serials[-1] + 2)
                    and all(val in (None, ZERO) for val in row_vals)
                ):
                    serial_no = serials[-1] + 1
                else:
                    raise ValueError(f"Check the {kind.lower()} row sequence near row {serial} on {table.source}.")
            if not serials and serial_no != 1:
                raise ValueError(f"The {kind.lower()} table appears to start partway through on {table.source}.")
            serials.append(serial_no)

            values: dict[str, Decimal] = {}
            for key in active_keys:
                raw = row[positions[key]]
                value = amount(raw)
                if value is None and compact(raw) not in {"", "na", "nil"}:
                    raise ValueError(f"Check {key} in {kind.lower()} row {serial} on {table.source}.")
                values[key] = value if value is not None else ZERO
            if table.source not in sources:
                sources.append(table.source)
            details.append((name, values, table.source))
            index += 1

    if header is None:
        if partial:
            raise ValueError(f"The {kind.lower()} table is missing a column on {partial}.")
        return None, "", None
    if totals is None:
        raise ValueError(f"The {kind.lower()} subtotal is missing after the header on {header.source}.")

    for key in active_keys:
        expected = totals[key]
        if expected is None:
            # Estimate column is occasionally blank on the subtotal row even when detail rows have estimates.
            if key == "estimate":
                continue
            raise ValueError(f"The {kind.lower()} {key} subtotal is unreadable on {', '.join(sources)}.")
        actual = sum((values[key] for _, values, _ in details), ZERO)
        if abs(actual - expected) > TOLERANCE:
            raise ValueError(
                f"The {kind.lower()} {key} total ({actual:.2f}) does not match subtotal ({expected:.2f}) on {', '.join(sources)}."
            )
    return details, ", ".join(sources), gst_from_table


def read_newindia_pdf_assessment(
    pages,
    *,
    defaults: Optional[dict] = None,
) -> tuple[list[dict], list[dict], dict[str, str], dict[str, tuple[Decimal, str]], list[str]]:
    """Extract verified New India parts/labour rows and GST from survey PDF pages."""
    defaults = defaults or load_automation_defaults(portal_id="newindia")
    parts_hsn = coerce_hsn_code(defaults.get("assessment_parts_hsn_code"), "8512")
    labour_hsn = coerce_hsn_code(defaults.get("assessment_labour_hsn_code"), "8729")

    tables = _assessment_tables(pages)
    layout_fallback = tuple(_positional_tables(pages))
    gst_summaries, gst_errors = _gst_summaries(tables + layout_fallback)

    errors: list[str] = []
    parts_rows: list[dict] = []
    labour_rows: list[dict] = []
    item_sources: dict[str, str] = {}
    table_gst_parts: Optional[Decimal] = None
    table_gst_labour: Optional[Decimal] = None

    specs = (
        (PART_COLUMNS, REQUIRED_PART_KEYS, MATERIAL_ORDER, "Spares", "spares"),
        (LABOUR_COLUMNS, REQUIRED_LABOUR_KEYS, ("rr", "denting", "cw", "paint"), "Labour", "labour"),
    )
    for columns, required, value_keys, kind, section in specs:
        native_error = None
        rows = None
        source = ""
        section_gst = None
        try:
            rows, source, section_gst = _item_tables(tables, columns, required, value_keys, kind)
        except ValueError as exc:
            native_error = str(exc)

        if rows is None and layout_fallback:
            try:
                rows, source, fb_gst = _item_tables(layout_fallback, columns, required, value_keys, kind)
                if section_gst is None:
                    section_gst = fb_gst
            except ValueError as exc:
                errors.append(native_error or str(exc))
                continue

        if rows is None:
            if native_error:
                errors.append(native_error)
            continue

        item_sources[section] = source
        if section == "spares":
            table_gst_parts = section_gst
        else:
            table_gst_labour = section_gst

        for name, values, row_source in rows:
            if section == "labour":
                # Painting is intentionally excluded from New India labour items
                # (matches excel_parts_extractor.py: only R/R, Denting, and C/W).
                total_billed = values.get("rr", ZERO) + values.get("denting", ZERO) + values.get("cw", ZERO)
                if total_billed <= ZERO:
                    continue
                labour_rows.append({
                    "category": "Labor Charges",
                    "description": "Labor charges for Repairing and Alignment",
                    "part_name": name,
                    "service_type": "ALLOW",
                    "estimated_amount": 0,
                    "billed_amount": float(total_billed),
                    "assessed_amount": float(total_billed),
                    "depreciation_pct": 0,
                    "hsn_code": labour_hsn,
                    "gst_pct": 0,
                })
                continue

            positive_materials = [mat for mat in MATERIAL_ORDER if values.get(mat, ZERO) > ZERO]
            if len(positive_materials) > 1:
                errors.append(
                    f"Spares item '{name}' has positive amounts in multiple material columns "
                    f"({', '.join(positive_materials)}) on {row_source}."
                )
                continue
            if not positive_materials:
                continue

            material = positive_materials[0]
            billed = values[material]
            estimated = values.get("estimate", ZERO)
            parts_rows.append({
                "category": "Spare Parts",
                "description": MATERIAL_DESCRIPTIONS[material],
                "part_name": name,
                "service_type": "REPLACE",
                "estimated_amount": float(estimated),
                "billed_amount": float(billed),
                "assessed_amount": float(billed),
                "depreciation_pct": 0,
                "hsn_code": parts_hsn,
                "gst_pct": 0,
            })

    gst_info: dict[str, tuple[Decimal, str]] = {}
    if gst_summaries and not any("mixes CGST/SGST and IGST" in err or "Conflicting" in err for err in gst_errors):
        total_gst = ZERO
        gst_sources = []
        for _sec, (vals, src) in gst_summaries.items():
            total_gst += vals["cgst"] + vals["sgst"] + vals["igst"]
            if src not in gst_sources:
                gst_sources.append(src)
        gst_info["workshop_gst_amount"] = (total_gst.quantize(Decimal("0.01")), ", ".join(gst_sources))
    elif not gst_errors and (table_gst_parts is not None or table_gst_labour is not None):
        total_gst = (table_gst_parts or ZERO) + (table_gst_labour or ZERO)
        gst_sources = [src for src in item_sources.values() if src]
        gst_info["workshop_gst_amount"] = (total_gst.quantize(Decimal("0.01")), ", ".join(gst_sources) or "PDF Assessment")

    # Surface GST conflicts only when they actually contradict or block GST reading;
    # keep parts/labour generation blocked only by parts/labour extraction errors.
    return parts_rows, labour_rows, item_sources, gst_info, list(dict.fromkeys(errors))
