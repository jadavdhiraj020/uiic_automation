"""Extract OIC parts, labour and GST summaries from a survey PDF."""

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
    for table in tables:
        section = ""
        columns = {}
        for index, row in enumerate(table.rows):
            title = _gst_section(_heading(row))
            if title:
                section, columns = title, {}
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
            errors.setdefault(section, f"{section.title()} GST summary total is missing from the survey PDF.")
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
            if any(compact(cell) in {"subtotal", "total", "subtotalbeforegst", "totalbeforegst", "grandtotal"}
                   for cell in row):
                totals = {key: amount(row[positions[key]]) for key in known_total_keys}
                if table.source not in sources:
                    sources.append(table.source)
                continue
            if not name:
                continue

            # Serial numbers are only printed row markers; they are not sent
            # to the OIC portal. OCR commonly mistakes 18/78/88 etc. Do not
            # reject a financially valid table because of that marker.
            #
            # We still require a real detail row: at least one amount column
            # must contain a numeric value. Any missing/duplicated physical row
            # is caught later by the strict subtotal reconciliation.
            numeric_cells = [
                amount(row[positions[key]])
                for key in known_total_keys
                if positions.get(key) is not None and positions[key] < len(row)
            ]
            if not any(value is not None for value in numeric_cells):
                continue

            expected_serial = serials[-1] + 1 if serials else 1
            serial_no = int(serial) if serial.isdecimal() else expected_serial
            if serial_no != expected_serial:
                serial_no = expected_serial
            serials.append(serial_no)
            values = {}
            for key in known_total_keys:
                raw = row[positions[key]]
                value = amount(raw)
                if value is None and compact(raw) not in {"", "na", "nil"}:
                    # A single unreadable Spares estimate is recoverable when
                    # the printed subtotal is readable: subtotal minus every
                    # other verified estimate gives one exact remainder.
                    # Keep the unresolved value as None for now and reconcile
                    # only after the whole table has been read.
                    if kind == "Spares" and key == "estimate":
                        values[key] = None
                        continue
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

    if kind == "Spares":
        unreadable_estimates = [
            (name, values, source)
            for name, values, source in details
            if values.get("estimate") is None
        ]
        if unreadable_estimates:
            expected = totals.get("estimate")
            if len(unreadable_estimates) != 1 or expected is None:
                source = unreadable_estimates[0][2]
                raise ValueError(f"Check estimate in spares row on {source}.")
            known = sum(
                (values["estimate"] for _, values, _ in details if values.get("estimate") is not None),
                ZERO,
            )
            recovered = expected - known
            if recovered < ZERO:
                raise ValueError(
                    f"The spares estimate subtotal is smaller than the readable detail rows on {', '.join(sources)}."
                )
            unreadable_estimates[0][1]["estimate"] = recovered

    for key in known_total_keys:
        expected = totals[key]
        actual = sum((values[key] for _, values, _ in details), ZERO)
        if expected is None or abs(actual - expected) > TOLERANCE:
            raise ValueError(f"The {kind.lower()} {key} total does not match its detail rows on {', '.join(sources)}.")
    return details, ", ".join(sources)


def read_assessment(pages):
    """Return the same item inputs as Excel, plus traceable GST and review errors."""
    tables = tuple(table for page in pages for table in page.tables)
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
