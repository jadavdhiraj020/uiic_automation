"""Prepare OIC's printable survey PDF without leaving an Excel copy behind."""

import os
import shutil
import tempfile

from app.data.printable_excel_service import (
    _create_printable_excel,
    _generate_pdf,
    _validate_column_range,
    _validate_scale,
)
from app.portals.oic.generated_files import publish_generated

OIC_PRINTABLE_PDF = "survey_report_printable_copy.pdf"


def process_oic_printable(source_excel_path, output_folder, settings, logs, stop_cb=None):
    """Render to temporary files and publish only a successfully generated PDF."""
    if not source_excel_path or not os.path.isfile(source_excel_path):
        logs.append("Printable survey PDF: source Excel not found.")
        return
    if stop_cb and stop_cb():
        return
    mode = str(settings.get("printable_print_mode", "scale_percentage") or "scale_percentage").strip().lower()
    scale = None
    col_range = None
    if mode == "column_range":
        col_range = _validate_column_range(str(settings.get("printable_column_range", "A:L")))
        if col_range is None:
            logs.append("Printable survey PDF: invalid column range; generation skipped.")
            return
    else:
        mode = "scale_percentage"
        scale = _validate_scale(settings.get("printable_scale_percentage", 80))
        if scale is None:
            logs.append("Printable survey PDF: invalid scale; generation skipped.")
            return
    try:
        with tempfile.TemporaryDirectory(prefix="oic-print-") as tmp:
            excel_path = os.path.join(tmp, "printable.xlsx")
            pdf_path = os.path.join(tmp, "printable.pdf")
            _create_printable_excel(source_excel_path, excel_path, mode, scale, col_range, logs)
            if stop_cb and stop_cb():
                logs.append("Printable survey PDF: generation cancelled.")
                return
            _generate_pdf(excel_path, pdf_path, logs, print_mode=mode, scale=scale, col_range=col_range)
            if stop_cb and stop_cb():
                logs.append("Printable survey PDF: generation cancelled.")
                return
            if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) == 0:
                logs.append("Printable survey PDF: generation failed; the previous PDF was kept.")
                return
            with open(pdf_path, "rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("Generated printable report is not a PDF")
            fd, staged = tempfile.mkstemp(prefix=".oic-print-", suffix=".tmp", dir=output_folder)
            os.close(fd)
            try:
                shutil.copyfile(pdf_path, staged)
                publish_generated(staged, os.path.join(output_folder, OIC_PRINTABLE_PDF))
            finally:
                if os.path.exists(staged):
                    os.unlink(staged)
            logs.append(f"Printable survey PDF ready: {OIC_PRINTABLE_PDF}; temporary Excel removed.")
    except Exception as exc:
        logs.append(f"Printable survey PDF could not be prepared: {exc}")
