"""Extract OIC parts, labour and GST summaries from a survey PDF."""

from dataclasses import replace
from decimal import Decimal
import re

from .pdf_layout import Table, compact


PART_COLUMNS = {
    "serial": ("sn", "sno", "srno", "slno", "serialno"),
    "name": ("partsname", "partname", "partdescription", "partsdescription", "description", "itemdescription"),
    "estimate": ("estimated", "estimate", "estimatedamount", "estimateamount"),
    "metal": ("mage", "magewise", "metal", "metallic", "metalamount", "metallicparts"),
    "plastic": ("p50", "plastic", "plastic50", "plasticamount", "plasticrubber"),
    "glass": ("g0", "glass", "glass0", "glassamount"),
}
LABOUR_COLUMNS = {
    "serial": PART_COLUMNS["serial"],
    "name": ("description", "labourdescription", "labordescription", "particulars", "itemdescription"),
    "rr": ("rr", "removerefit", "removalrefitting", "removalreplacement"),
    "denting": ("denting", "dent"),
    "cw": ("cw", "cuttingwelding", "cuttingandwelding"),
    "paint": ("paint", "painting", "paintingcharges", "paintamount"),
}
GST_COLUMNS = {
    "taxable": ("taxableamount", "taxablevalue", "amountbeforegst", "taxable"),
    "cgst": ("cgst", "centralgst", "cgstamount"),
    "sgst": ("sgst", "stategst", "sgstamount"),
    "igst": ("igst", "integratedgst", "igstamount"),
}
MATERIALS = ("metal", "plastic", "glass")
LABOUR_TYPES = ("rr", "denting", "cw", "paint")
ZERO = Decimal(0)
TOLERANCE = Decimal(".02")
TOTAL_LABELS = {"subtotal", "total", "subtotalbeforegst", "totalbeforegst", "grandtotal"}
AMOUNT = re.compile(r"(?:\d+|\d{1,3}(?:,\d{2,3})*,\d{3})(?:\.\d{1,2})?")


def amount(value):
    text = re.sub(r"^(?:INR|Rs\.?|₹)\s*", "", str(value or "").strip(), flags=re.I)
    text = re.sub(r"(?<=\d)\s+(?=[.,])|(?<=[.,])\s+(?=\d)", "", text)
    return Decimal(text.replace(",", "")) if AMOUNT.fullmatch(text) else None


def _columns(row, aliases):
    normalized = [compact(value) for value in row]
    positions = {}
    for key, options in aliases.items():
        matches = [i for i, value in enumerate(normalized) if value in options]
        if key == "serial" and "name" in aliases:
            descriptions = [i for i, value in enumerate(normalized) if value in aliases["name"]]
            if len(descriptions) == 1:
                matches = [i for i in matches if i < descriptions[0]]
        if len(matches) == 1:
            positions[key] = matches[0]
    return positions


def _heading(row):
    return " ".join(value for value in row if value)


def _gst_section(text):
    marker = compact(text)
    for section, words in (("spares", ("spares", "parts", "spareparts")), ("labour", ("labour", "labor"))):
        if any(marker in {f"gstsummary{word}", f"{word}gstsummary", f"gstsummaryfor{word}"} for word in words):
            return section
    return ""


def _open_header(table):
    for index in range(len(table.rows) - 1, -1, -1):
        row = table.rows[index]
        if any(compact(cell) in TOTAL_LABELS for cell in row):
            break
        for aliases in (PART_COLUMNS, LABOUR_COLUMNS, GST_COLUMNS):
            positions = _columns(row, aliases)
            if aliases is GST_COLUMNS:
                if (len(positions) >= 2 and "taxable" in positions and 0 not in positions.values()
                        and any(_gst_section(_heading(title)) for title in table.rows[:index])):
                    return index, positions
            elif len(positions) == len(aliases):
                return index, positions
    return None


def _aligned_cell(box, boxes):
    if box is None:
        return None
    matches = [i for i, cell in enumerate(boxes) if cell is not None
               and abs(cell[0] - box[0]) <= 2 and abs(cell[2] - box[2]) <= 2]
    return matches[0] if len(matches) == 1 else None


def _printed_serial(lines, serial_box, row_box, name):
    """Read an orphaned native digit from the printed row at the page break."""
    candidates = set()
    for line in lines:
        if (line.confidence < 1 or not row_box[1] <= line.top < row_box[3]
                or not serial_box[0] <= line.cells[0][0] < serial_box[2]):
            continue
        match = re.match(r"^(\d+)\s+(.+)$", line.text)
        if match and match[2].startswith(name + " "):
            candidates.add(match[1])
    return candidates.pop() if len(candidates) == 1 else ""


def _project_continuation(table, index, header_boxes, positions, lines):
    row, boxes = table.rows[index], table.row_boxes[index]
    projected = [""] * len(header_boxes)
    serial_column, name_column = positions.get("serial"), positions.get("name")
    name_box = header_boxes[name_column] if name_column is not None else None
    serial_box = header_boxes[serial_column] if serial_column is not None else None
    # The subtotal label typically spans the serial and description columns.
    subtotal = next((cell for cell, box in zip(row, boxes)
                     if name_box and serial_box and box and compact(cell) in TOTAL_LABELS
                     and abs(box[0] - serial_box[0]) <= 2 and abs(box[2] - name_box[2]) <= 2), "")
    # The native grid can grow empty columns when other sections on the page
    # have vertical dividers. Use the printed column boundaries from the header.
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
    if compact(projected[name_column]) in TOTAL_LABELS:
        return tuple(projected)
    match = _aligned_cell(serial_box, boxes)
    if match is not None:
        projected[serial_column] = row[match]
    elif index == 0:
        physical_name_box = boxes[_aligned_cell(name_box, boxes)]
        projected[serial_column] = _printed_serial(lines, serial_box, physical_name_box, projected[name_column])
    return tuple(projected) if projected[serial_column].isdecimal() else None


def _continue_native_table(table, following, lines_by_page):
    header = _open_header(table)
    if header is None:
        return table
    header_index, positions = header
    header_boxes = table.row_boxes[header_index]
    page = table.page
    rows = []
    tops = []
    for next_table in following:
        # Only connect the last grid on one page to the first on the next.
        if not next_table.row_boxes or next_table.page != page + 1:
            break
        page = next_table.page
        for index in range(len(next_table.rows)):
            row = _project_continuation(next_table, index, header_boxes, positions, lines_by_page.get(page, ()))
            if row is None:
                return table
            tops.append(next_table.tops[index])
            if any(compact(cell) in TOTAL_LABELS for cell in row):
                if "serial" not in positions:
                    detail = (*table.rows[header_index + 1:], *rows)
                    if not detail or any(amount(entry[0]) is None for entry in detail):
                        return table
                    for column in positions.values():
                        amounts = [amount(entry[column]) if entry[column] else ZERO for entry in detail]
                        total = amount(row[column]) if row[column] else ZERO
                        if total is None or None in amounts or abs(sum(amounts, ZERO) - total) > TOLERANCE:
                            return table
                return replace(table, rows=(*table.rows, *rows, row), tops=(*table.tops, *tops),
                               extra_page=page, row_boxes=())
            rows.append(row)
    return table


def _assessment_tables(pages):
    tables = tuple(table for page in pages for table in page.tables)
    lines_by_page = {page.lines[0].page: page.lines for page in pages if page.lines}
    for index, table in enumerate(tables):
        if (table.row_boxes and index + 1 < len(tables)
                and tables[index + 1].page == table.page + 1):
            table = _continue_native_table(table, tables[index + 1:], lines_by_page)
        yield table


def _positional_tables(pages):
    """Recover columns from OCR boxes where the PDF has no readable table grid."""
    for page in pages:
        for index, line in enumerate(page.lines):
            if len(line.cells) < 4:
                continue
            heading = tuple(cell[2] for cell in line.cells)
            is_items = any(len(_columns(heading, names)) >= 5 for names in (PART_COLUMNS, LABOUR_COLUMNS))
            is_gst = len(_columns(heading, GST_COLUMNS)) >= 2
            if not is_items and not is_gst:
                continue
            title = page.lines[index - 1] if is_gst and index else None
            if is_gst and (title is None or not _gst_section(title.text)):
                continue
            rows = [heading]
            tops = [line.top]
            scores = [line.confidence]
            if title:
                rows.insert(0, (title.text,))
                tops.insert(0, title.top)
                scores.append(title.confidence)
            anchors = [(x0 + x1) / 2 for x0, x1, _ in line.cells]
            for entry in page.lines[index + 1:]:
                row = [""] * len(anchors)
                for x0, x1, value in entry.cells:
                    center = (x0 + x1) / 2
                    column = min(range(len(anchors)), key=lambda i: abs(anchors[i] - center))
                    row[column] = f"{row[column]} {value}".strip()
                rows.append(tuple(row))
                tops.append(entry.top)
                scores.append(entry.confidence)
                if re.search(r"\b(?:sub\s*)?total\b", entry.text, re.I):
                    break
            yield Table(line.page, tuple(tops), tuple(rows), min(scores), line.extra_page)


def _gst_summaries(tables):
    results = {}
    errors = {}
    sources = {}
    for table in tables:
        section = ""
        columns = {}
        for index, row in enumerate(table.rows):
            title = _gst_section(_heading(row))
            if title:
                section, columns = title, {}
                sources.setdefault(section, table.source)
                continue
            if not section:
                continue
            headers = _columns(row, GST_COLUMNS)
            if len(headers) >= 2 and "taxable" in headers:
                columns = headers
                continue
            if not columns or not any(compact(cell) in {"total", "subtotal", "grandtotal"} for cell in row):
                continue
            values = {key: amount(row[i]) if i < len(row) else None for key, i in columns.items()}
            split_present = values.get("cgst") is not None and values.get("sgst") is not None
            integrated = values.get("igst")
            if (values.get("taxable") is None or not (split_present or integrated is not None)
                    or (not split_present and any(values.get(key) for key in ("cgst", "sgst")))
                    or (integrated and any(values.get(key) for key in ("cgst", "sgst")))
                    or table.score(index) < .78):
                errors[section] = f"Check the {section} GST total on {table.source}."
                continue
            full = {key: values.get(key) if values.get(key) is not None else ZERO for key in GST_COLUMNS}
            gst_total = full["cgst"] + full["sgst"] + full["igst"]
            if abs(full["taxable"] * Decimal(".18") - gst_total) > TOLERANCE:
                errors[section] = f"The {section} GST total on {table.source} does not reconcile with OIC's 18% item rate."
                continue
            if section in results and results[section][0] != full:
                errors[section] = f"Conflicting {section} GST totals found on {results[section][1]} and {table.source}."
            else:
                results[section] = full, table.source
    for section in ("spares", "labour"):
        if section not in results:
            source = sources.get(section)
            issue = (f"{section.title()} GST summary total could not be verified for the table on {source}."
                     if source else f"{section.title()} GST summary total is missing from the survey PDF.")
            errors.setdefault(section, issue)
    if results:
        has_split = any(values["cgst"] or values["sgst"] for values, _ in results.values())
        has_integrated = any(values["igst"] for values, _ in results.values())
        if has_split and has_integrated:
            errors["types"] = "The GST summaries mix CGST/SGST and IGST. Check the invoice tax amounts before uploading."
    return results, list(errors.values())


def _item_tables(tables, aliases, value_keys, kind):
    """Read numbered detail rows up to the first subtotal, including continuations."""
    positions = {}
    details = []
    serials = []
    header = None
    header_width = 0
    totals = None
    sources = []
    partial = ""
    known_total_keys = ("estimate", *value_keys) if kind == "Spares" else value_keys
    for table in tables:
        for index, row in enumerate(table.rows):
            header_columns = _columns(row, aliases)
            if len(header_columns) >= len(aliases) - 1 and {"serial", "name"} <= header_columns.keys():
                if len(header_columns) != len(aliases):
                    partial = table.source
                    continue
                if header is not None and totals is not None:
                    raise ValueError(f"More than one {kind.lower()} table was found on {header.source} and {table.source}.")
                header, positions, header_width = table, header_columns, len(row)
                if table.source not in sources:
                    sources.append(table.source)
                continue
            if header is None or totals is not None:
                continue
            if (table.confidence < 1 and len(row) + 1 == header_width
                    and positions["serial"] == 0 and positions["name"] == 1):
                # A page break can leave the serial/name divider visible in
                # only one printed row. OCR then sees a single physical cell.
                merged = re.fullmatch(r"(\d+)\s+(.+)", row[0])
                if merged:
                    row = (*merged.groups(), *row[1:])
                elif compact(row[0]) in {"subtotal", "subtotalbeforegst", "total", "totalbeforegst"}:
                    row = (row[0], "", *row[1:])
            if len(row) <= max(positions.values()):
                continue
            serial = row[positions["serial"]].strip()
            name = row[positions["name"]].strip()
            if any(compact(cell) in TOTAL_LABELS for cell in row):
                totals = {key: amount(row[positions[key]]) for key in known_total_keys}
                if table.source not in sources:
                    sources.append(table.source)
                continue
            if not serial.isdecimal() or not name:
                continue
            if table.score(index) < .78:
                raise ValueError(f"Check the low-confidence {kind.lower()} row {serial} on {table.source}.")
            serial_no = int(serial)
            if serials and serial_no != serials[-1] + 1:
                # An OCR digit can be wrong even though the printed grid
                # has exactly one physical row between the two known serials.
                next_serial = table.rows[index + 1][positions["serial"]].strip() if index + 1 < len(table.rows) else ""
                amounts = [amount(row[positions[key]]) for key in value_keys]
                if (table.confidence < 1 and table.score(index) < .90
                        and next_serial == str(serials[-1] + 2)
                        and all(value == ZERO for value in amounts)):
                    serial_no = serials[-1] + 1
                else:
                    raise ValueError(f"Check the {kind.lower()} row sequence near row {serial} on {table.source}.")
            if not serials and serial_no != 1:
                raise ValueError(f"The {kind.lower()} table appears to start partway through on {table.source}.")
            serials.append(serial_no)
            values = {}
            for key in known_total_keys:
                raw = row[positions[key]]
                value = amount(raw)
                if value is None and compact(raw) not in {"", "na", "nil"}:
                    raise ValueError(f"Check {key} in {kind.lower()} row {serial} on {table.source}.")
                values[key] = value if value is not None else ZERO
            if table.source not in sources:
                sources.append(table.source)
            details.append((name, values, table.source))

    if header is None:
        if partial:
            raise ValueError(f"The {kind.lower()} table is missing a column on {partial}.")
        return None, ""
    if totals is None:
        raise ValueError(f"The {kind.lower()} subtotal is missing after the header on {header.source}.")
    for key in known_total_keys:
        expected = totals[key]
        actual = sum((values[key] for _, values, _ in details), ZERO)
        if expected is None or abs(actual - expected) > TOLERANCE:
            raise ValueError(f"The {kind.lower()} {key} total does not match its detail rows on {', '.join(sources)}.")
    return details, ", ".join(sources)


def read_assessment(pages):
    """Return the same item inputs as Excel, plus traceable GST and review errors."""
    tables = tuple(_assessment_tables(pages))
    layout_fallback = tuple(_positional_tables(pages))
    gst, errors = _gst_summaries(tables + layout_fallback)
    parts = []
    labour = dict.fromkeys(("rr", "denting", "cw", "painting"), ZERO)
    item_sources = {}
    for columns, keys, kind, section in (
        (PART_COLUMNS, MATERIALS, "Spares", "spares"),
        (LABOUR_COLUMNS, LABOUR_TYPES, "Labour", "labour"),
    ):
        native_error = None
        try:
            rows, source = _item_tables(tables, columns, keys, kind)
        except ValueError as exc:
            rows, source = None, ""
            native_error = str(exc)
        if rows is None and layout_fallback:
            try:
                rows, source = _item_tables(layout_fallback, columns, keys, kind)
            except ValueError as exc:
                errors.append(native_error or str(exc))
                continue
        if rows is None:
            if native_error:
                errors.append(native_error)
            elif section not in gst or gst[section][0]["taxable"]:
                errors.append(f"The {kind.lower()} detail table could not be read from the survey PDF.")
            continue
        item_sources[section] = source
        for name, values, row_source in rows:
            if section == "labour":
                for key in keys:
                    labour["painting" if key == "paint" else key] += values[key]
                continue
            materials = [key for key in MATERIALS if values[key] > 0]
            if len(materials) > 1:
                errors.append(f"Spares item {name} has amounts in more than one material column on {row_source}.")
            elif materials:
                material = materials[0]
                parts.append({
                    "material_type": material, "part_name": name,
                    "billed_amount": values[material], "estimated_amount": values["estimate"],
                })
    return parts, labour, gst, item_sources, list(dict.fromkeys(errors))
