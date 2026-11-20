"""Create a structured Excel working copy from an OIC survey PDF.

The original PDF is never modified or removed.  The generated workbook is an
app-owned intermediate source so the existing Excel reader and OIC assessment
upload builder can be reused for PDF-only claim folders.
"""

import os
import tempfile
from pathlib import Path

import openpyxl

from app.portals.oic.generated_files import publish_generated
from app.portals.oic.pdf_layout import read_pages


_OUTPUT_FILENAME = "auto_oic_pdf_source_current.xlsx"


def output_path_for(folder: str) -> str:
    return os.path.abspath(os.path.join(folder, _OUTPUT_FILENAME))


def _clean_cell(value) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split())


def convert_oic_pdf_to_excel(pdf_path: str, output_folder: str, *, stop_cb=None) -> str:
    """Convert PDF layout/tables into an Excel working copy.

    The PDF remains the authoritative document in the claim folder.  This
    workbook exists only to let the proven Excel extraction path read fields
    and to let the existing OIC upload-sheet builder read parts/labour tables.
    """
    source = Path(pdf_path)
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise FileNotFoundError(f"OIC survey PDF not found: {pdf_path}")

    pages = read_pages(str(source), stop_cb=stop_cb)
    if not pages:
        raise ValueError("The OIC survey PDF contains no readable pages")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Survey Report"

    written = 0
    for page in pages:
        if stop_cb and stop_cb():
            wb.close()
            raise InterruptedError("PDF to Excel conversion cancelled")

        # Keep each visual PDF line as one Excel row.  pdf_layout has already
        # split visibly separated text into cells, so labels and values remain
        # in their natural left-to-right order for excel_reader.
        for line in page.lines:
            values = [_clean_cell(cell[2]) for cell in line.cells]
            if any(values):
                ws.append(values)
                written += 1

        # Also append detected tables.  They preserve assessment columns more
        # reliably than plain text on many survey-report exports.  Duplicate
        # rows are intentional: the existing extractors choose the best header.
        if page.tables:
            ws.append([])
            for table in page.tables:
                for row in table.rows:
                    values = [_clean_cell(value) for value in row]
                    if any(values):
                        ws.append(values)
                        written += 1

        ws.append([])

    if not written:
        wb.close()
        raise ValueError("No readable OIC survey data could be converted to Excel")

    ws.freeze_panes = "A1"
    for column in ws.columns:
        width = max((len(str(cell.value or "")) for cell in column), default=0)
        ws.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 60)

    os.makedirs(output_folder, exist_ok=True)
    target = output_path_for(output_folder)
    fd, staged = tempfile.mkstemp(prefix="oic-pdf-source-", suffix=".xlsx", dir=output_folder)
    os.close(fd)
    try:
        wb.save(staged)
        wb.close()
        return publish_generated(staged, target)
    finally:
        try:
            wb.close()
        except Exception:
            pass
        if os.path.exists(staged):
            os.unlink(staged)
