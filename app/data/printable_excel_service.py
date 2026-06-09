"""
printable_excel_service.py - Printable Excel & PDF generation service.

Creates a printable Excel copy and a PDF from the source Excel file detected
by the folder scanner.  This is independent of the portal automation flow.

Two print modes:
  - Scale Percentage (25-300): applies uniform scaling to Sheet 1
  - Column Range (e.g. A:L): restricts the print area to the given columns

Filename policy:
  Every generation appends a timestamp suffix so older files are NEVER
  overwritten or deleted.  Example output names:
    Printable_Assessment_20260607_231751.xlsx
    Printable_Assessment_20260607_231751.pdf

PDF generation uses Microsoft Excel COM automation (ExportAsFixedFormat)
for pixel-perfect native print output.
If this is unavailable, the PDF step is skipped with a log message.
No cell-by-cell rendering (ReportLab, FPDF, HTML, canvas, etc.) is used.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_OUTPUT_EXCEL_NAME = "Printable_Assessment.xlsx"
DEFAULT_OUTPUT_PDF_NAME = "Printable_Assessment.pdf"
DEFAULT_PRINT_MODE = "scale_percentage"   # "scale_percentage" | "column_range"
DEFAULT_SCALE_PERCENTAGE = 80
DEFAULT_COLUMN_RANGE = "A:L"

# ── Validation ────────────────────────────────────────────────────────────────

_COL_RANGE_RE = re.compile(
    r"^([A-Z]{1,3})\s*:\s*([A-Z]{1,3})$", re.IGNORECASE
)


def _validate_scale(value) -> Optional[int]:
    """Validate scale percentage is an integer between 25 and 300."""
    try:
        scale = int(str(value).strip())
    except (ValueError, TypeError):
        return None
    if 25 <= scale <= 300:
        return scale
    return None


def _validate_column_range(value: str) -> Optional[Tuple[str, str]]:
    """Validate column range like 'A:L' or 'A:N'.  Returns (start, end) or None."""
    if not value:
        return None
    m = _COL_RANGE_RE.match(str(value).strip())
    if not m:
        return None
    start, end = m.group(1).upper(), m.group(2).upper()
    # Compare numeric column indices, not strings.
    # String comparison breaks for multi-letter columns:
    # e.g. "Z" > "AA" is True in Python but Z(26) < AA(27) numerically.
    if _col_letter_to_number(start) > _col_letter_to_number(end):
        return None
    return start, end


def _col_letter_to_number(col: str) -> int:
    """Convert Excel column letter(s) to 1-based index (A=1, Z=26, AA=27)."""
    result = 0
    for ch in col.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def process_printable_output(
    source_excel_path: str,
    output_folder: str,
    settings: dict,
    logs: List[str],
) -> None:
    """
    Orchestrates creation of printable Excel + PDF.

    Called from claim_folder_service.py right after folder scan succeeds.
    Reads print settings from automation_defaults, validates them,
    creates the printable copy, and generates the PDF via Excel COM.

    Args:
        source_excel_path: Absolute path to the original claim Excel.
        output_folder:     Folder where outputs are saved (same as claim folder).
        settings:          Automation defaults dict for the active portal.
        logs:              Mutable log list — appends status lines.
    """
    if not source_excel_path or not os.path.isfile(source_excel_path):
        logs.append("⚠️  Printable Excel: Source Excel not found — skipping generation.")
        return

    logs.append(f"🖨️  Printable Excel/PDF: Source detected — {Path(source_excel_path).name}")

    # ── Read settings ─────────────────────────────────────────────────────
    output_excel_name = str(
        settings.get("printable_output_excel_name", DEFAULT_OUTPUT_EXCEL_NAME) or DEFAULT_OUTPUT_EXCEL_NAME
    ).strip()
    output_pdf_name = str(
        settings.get("printable_output_pdf_name", DEFAULT_OUTPUT_PDF_NAME) or DEFAULT_OUTPUT_PDF_NAME
    ).strip()
    print_mode = str(
        settings.get("printable_print_mode", DEFAULT_PRINT_MODE) or DEFAULT_PRINT_MODE
    ).strip().lower()

    # Ensure correct extensions (strip them before adding timestamp)
    if output_excel_name.lower().endswith(".xlsx"):
        output_excel_stem = output_excel_name[:-5]
    else:
        output_excel_stem = output_excel_name
    if output_pdf_name.lower().endswith(".pdf"):
        output_pdf_stem = output_pdf_name[:-4]
    else:
        output_pdf_stem = output_pdf_name

    # Timestamp suffix — ensures every run keeps its own file; nothing is overwritten.
    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_excel_name = f"{output_excel_stem}_{_ts}.xlsx"
    output_pdf_name   = f"{output_pdf_stem}_{_ts}.pdf"

    output_excel_path = os.path.join(output_folder, output_excel_name)
    output_pdf_path = os.path.join(output_folder, output_pdf_name)

    # ── Validate mode-specific settings ───────────────────────────────────
    scale = None
    col_range = None

    if print_mode == "column_range":
        raw_range = str(settings.get("printable_column_range", DEFAULT_COLUMN_RANGE) or DEFAULT_COLUMN_RANGE).strip()
        col_range = _validate_column_range(raw_range)
        if col_range is None:
            logs.append(
                f"⚠️  Printable Excel: Invalid Column Range '{raw_range}' "
                f"(expected format like 'A:L'). Skipping generation."
            )
            return
        logs.append(f"  📐 Print Mode: Column Range → {col_range[0]}:{col_range[1]}")
    else:
        # Default mode: scale_percentage
        print_mode = "scale_percentage"
        raw_scale = settings.get("printable_scale_percentage", DEFAULT_SCALE_PERCENTAGE)
        scale = _validate_scale(raw_scale)
        if scale is None:
            logs.append(
                f"⚠️  Printable Excel: Invalid Scale Percentage '{raw_scale}' "
                f"(must be an integer between 25 and 300). Skipping generation."
            )
            return
        logs.append(f"  📐 Print Mode: Scale Percentage → {scale}%")

    # ── Step 1: Create printable Excel copy ───────────────────────────────
    try:
        _create_printable_excel(
            source_excel_path, output_excel_path,
            print_mode, scale, col_range, logs,
        )
    except Exception as exc:
        logs.append(f"  ❌ Printable Excel creation failed: {exc}")
        logger.exception("Printable Excel creation error")
        return

    # ── Step 2: Generate PDF (Excel COM) ────────────────────────────────
    try:
        _generate_pdf(output_excel_path, output_pdf_path, logs)
    except Exception as exc:
        logs.append(f"  ❌ PDF generation failed: {exc}")
        logger.exception("PDF generation error")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _create_printable_excel(
    source_path: str,
    output_path: str,
    print_mode: str,
    scale: Optional[int],
    col_range: Optional[Tuple[str, str]],
    logs: List[str],
) -> None:
    """
    Copy source Excel and apply print settings to Sheet 1 using openpyxl.

    Only print-related properties are modified:
      - Scale percentage
      - Print area (column range)
      - Page setup for fit-to-page

    No other formatting is changed (fonts, widths, borders, etc.).
    """
    import openpyxl

    # Each run uses a unique timestamped filename so the file never exists yet.
    # We still guard against the (unlikely) same-second collision or a stale
    # leftover from a crashed previous run.
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except PermissionError as exc:
            raise PermissionError(
                f"Cannot overwrite '{os.path.basename(output_path)}' — "
                f"the file is open in another program (e.g. Excel). "
                f"Please close it and scan the folder again."
            )

    # Copy source → output (preserves all original formatting).
    try:
        shutil.copy2(source_path, output_path)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot write '{os.path.basename(output_path)}' — "
            f"the file was locked by another process during copy. "
            f"Please close any open files in the claim folder and scan again."
        ) from exc

    # Wrap workbook lifecycle in try/finally so the file handle is
    # always released even if save() or any intermediate step raises.
    wb = openpyxl.load_workbook(output_path)
    try:
        ws = wb.worksheets[0]  # Sheet 1 only

        if print_mode == "scale_percentage" and scale is not None:
            ws.page_setup.scale = scale
            # Clear any existing print area so scaling applies to the full sheet
            ws.print_area = None
            ws.sheet_properties.pageSetUpPr.fitToPage = False
            logs.append(f"  ✅ Printable Excel created: {Path(output_path).name} (Scale: {scale}%)")

        elif print_mode == "column_range" and col_range is not None:
            start_col, end_col = col_range
            max_row = ws.max_row or 1
            # Set print area to cover all rows within the specified column range
            print_area = f"{start_col}1:{end_col}{max_row}"
            ws.print_area = print_area
            # Use fit-to-page width=1 so all specified columns fit on one page width
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 0  # 0 = auto-fit height (no limit)
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            logs.append(
                f"  ✅ Printable Excel created: {Path(output_path).name} "
                f"(Columns: {start_col}:{end_col}, Rows: 1–{max_row})"
            )

        wb.save(output_path)
    finally:
        wb.close()

    logger.info("Printable Excel saved: %s", output_path)


def _generate_pdf(excel_path: str, pdf_path: str, logs: List[str]) -> None:
    """
    Generate PDF from the printable Excel using Microsoft Excel COM.

    If generation fails, a diagnostic message is logged.
    """
    abs_excel = os.path.abspath(excel_path)
    abs_pdf = os.path.abspath(pdf_path)

    # Each PDF has a unique timestamped name so it should not exist yet.
    # Guard against the rare same-second collision or stale leftover.
    if os.path.exists(abs_pdf):
        try:
            os.remove(abs_pdf)
        except PermissionError:
            logs.append(
                f"  ⚠️  PDF skipped: '{os.path.basename(abs_pdf)}' is open in another "
                f"program. Please close it and scan again."
            )
            return

    # ── Excel COM ─────────────────────────────────────────────────
    if _generate_pdf_excel_com(abs_excel, abs_pdf, logs):
        return

    # ── Failed ───────────────────────────────────────────────────────
    logs.append(
        "  ❌ PDF: Generation failed. "
        "Ensure Microsoft Excel is installed and a PDF printer (like 'Microsoft Print to PDF') is available."
    )


def _find_pdf_printer(excel) -> Optional[str]:
    """
    Auto-detect the 'Microsoft Print to PDF' printer name+port string.

    Strategy (in order):
      1. win32print.EnumPrinters() — asks Windows for the actual installed
         name, so the port suffix is always correct regardless of machine.
      2. Port-list brute-force — tries all common Ne0x: and PORTPROMPT:
         variants, as a fallback when win32print is unavailable.

    Returns the full ActivePrinter string (e.g. 'Microsoft Print to PDF on Ne01:')
    or None if no matching printer is found.
    """
    # ── Strategy 1: EnumPrinters (most robust) ────────────────────────────
    try:
        import win32print
        # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS = 6
        for flags in (6, 2):  # 2 = PRINTER_ENUM_LOCAL only, as fallback
            printers = win32print.EnumPrinters(flags, None, 2)
            for info in printers:
                name = info.get("pPrinterName", "") if isinstance(info, dict) else info[2]
                if "Microsoft Print to PDF" in name or "Microsoft XPS" in name:
                    # Excel's ActivePrinter format is "Name on Port:"
                    port = info.get("pPortName", "") if isinstance(info, dict) else info[3]
                    full = f"{name} on {port}"
                    # Verify Excel accepts this string
                    try:
                        excel.ActivePrinter = full
                        logger.debug("Printer set via EnumPrinters: %s", full)
                        return full
                    except Exception:
                        pass  # try next printer
    except Exception as enum_exc:
        logger.debug("win32print.EnumPrinters unavailable: %s", enum_exc)

    # ── Strategy 2: Port-list brute-force ─────────────────────────────────
    _CANDIDATES = (
        [f"Microsoft Print to PDF on Ne{i:02d}:" for i in range(10)]
        + ["Microsoft Print to PDF on PORTPROMPT:"]
        + [f"Microsoft XPS Document Writer on Ne{i:02d}:" for i in range(10)]
        + ["Microsoft XPS Document Writer on PORTPROMPT:"]
    )
    for candidate in _CANDIDATES:
        try:
            excel.ActivePrinter = candidate
            logger.debug("Printer set via port-list: %s", candidate)
            return candidate
        except Exception:
            continue

    return None


def _generate_pdf_excel_com(
    abs_excel: str, abs_pdf: str, logs: List[str]
) -> bool:
    """
    Generate PDF via Microsoft Excel COM automation (ExportAsFixedFormat).

    Returns True on success, False on failure.
    """
    try:
        import win32com.client
        import pythoncom
    except ImportError as exc:
        logs.append(
            f"  ℹ️  Excel COM: win32com not available ({exc})."
        )
        return False

    excel = None
    wb = None
    com_initialized = False  # Issue 2: track init state to guard CoUninitialize
    try:
        if getattr(sys, "frozen", False):
            try:
                import win32com.client.gencache as gencache
                gencache.is_readonly = False
            except Exception as cache_exc:
                # Surface as WARNING (not debug) — if gencache is read-only in the
                # frozen EXE, COM dispatch will still work but may generate spurious
                # TypeErrors for complex COM objects. Visible in production logs.
                logger.warning(
                    "win32com gencache setup failed in frozen EXE (non-fatal): %s. "
                    "COM dispatch will proceed without gen-cache optimisation.",
                    cache_exc,
                )

        pythoncom.CoInitialize()
        com_initialized = True
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        # Issue 1: Auto-detect working PDF printer via EnumPrinters + port-list.
        # ExportAsFixedFormat requires a working printer driver even for PDF.
        # Excel caches the last-used printer which may be unavailable
        # (e.g. 'AnyDesk Printer' when remote desktop is disconnected).
        printer_set = _find_pdf_printer(excel)
        if printer_set:
            logger.debug("ActivePrinter resolved to: %s", printer_set)
        else:
            logs.append(
                "  ⚠️  No 'Microsoft Print to PDF' printer found — "
                "export will use Excel's current printer."
            )
            logger.warning("No PDF printer found; ExportAsFixedFormat may fail.")

        wb = excel.Workbooks.Open(abs_excel, ReadOnly=True)

        # Export only Sheet 1
        ws = wb.Worksheets(1)
        ws.Select()

        # xlTypePDF = 0 — native Excel PDF rendering engine
        ws.ExportAsFixedFormat(0, abs_pdf)

        logs.append(f"  ✅ PDF generated (Excel native): {Path(abs_pdf).name}")
        logger.info("PDF generated via Excel COM: %s", abs_pdf)
        return True

    except Exception as exc:
        # COM errors are tuples: (hresult, description, excepinfo, ...).
        # excepinfo[2] holds the human-readable Excel error message.
        exc_args = getattr(exc, "args", ())
        if (exc_args and isinstance(exc_args[0], int)
                and len(exc_args) >= 3
                and isinstance(exc_args[2], tuple)
                and len(exc_args[2]) >= 3
                and exc_args[2][2]):
            readable = str(exc_args[2][2])
        else:
            readable = str(exc)[:200]
        logs.append(f"  ⚠️  Excel COM failed: {readable}.")
        logger.warning("Excel COM PDF export failed: %s", exc)
        return False

    finally:
        if wb:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if excel:
            try:
                excel.Quit()
            except Exception:
                pass
        # Drop Python references before GC collect so refcount hits 0.
        del wb, excel
        # Issue 2: run gc and CoUninitialize in independent try/except blocks
        # so a gc failure cannot shadow a CoUninitialize call, and
        # CoUninitialize is only called if CoInitialize actually succeeded.
        try:
            import gc
            gc.collect()
        except Exception as gc_exc:
            logger.debug("gc.collect warning (non-fatal): %s", gc_exc)
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception as uninit_exc:
                logger.warning("CoUninitialize warning (non-fatal): %s", uninit_exc)
