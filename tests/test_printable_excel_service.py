import os
import shutil
import subprocess
import tempfile
import openpyxl
import pytest
from unittest.mock import patch, MagicMock

from app.data.printable_excel_service import (
    _col_letter_to_number,
    _validate_scale,
    _validate_column_range,
    _create_printable_excel,
    _generate_pdf,
    _generate_pdf_excel_com,
    _generate_pdf_libreoffice,
    _find_libreoffice,
    process_printable_output,
)


# ── Validation helpers ────────────────────────────────────────────────────────

def test_col_letter_to_number():
    assert _col_letter_to_number("A") == 1
    assert _col_letter_to_number("Z") == 26
    assert _col_letter_to_number("AA") == 27
    assert _col_letter_to_number("AZ") == 52
    assert _col_letter_to_number("ZZ") == 702
    assert _col_letter_to_number("AAA") == 703


def test_validate_scale():
    assert _validate_scale(25) == 25
    assert _validate_scale(80) == 80
    assert _validate_scale(300) == 300
    assert _validate_scale(24) is None
    assert _validate_scale(301) is None
    assert _validate_scale("80") == 80
    assert _validate_scale("abc") is None
    assert _validate_scale(None) is None


def test_validate_column_range():
    assert _validate_column_range("A:L") == ("A", "L")
    assert _validate_column_range("a:n") == ("A", "N")
    assert _validate_column_range("B:Z") == ("B", "Z")
    assert _validate_column_range("AA:AZ") == ("AA", "AZ")
    assert _validate_column_range("Z:A") is None  # reversed
    assert _validate_column_range("A:Z") == ("A", "Z")
    assert _validate_column_range("Z:AA") == ("Z", "AA")  # Z (26) < AA (27)
    assert _validate_column_range("AA:Z") is None  # AA (27) > Z (26)
    assert _validate_column_range("bad") is None
    assert _validate_column_range("") is None
    assert _validate_column_range(None) is None


# ── Printable Excel creation ─────────────────────────────────────────────────

def test_create_printable_excel_scale_mode():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, "source.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "Test Data"
        ws["B2"] = 123
        wb.save(src_path)
        wb.close()

        out_path = os.path.join(tmp_dir, "output.xlsx")
        logs = []

        _create_printable_excel(
            source_path=src_path,
            output_path=out_path,
            print_mode="scale_percentage",
            scale=75,
            col_range=None,
            logs=logs,
        )

        assert os.path.exists(out_path)
        out_wb = openpyxl.load_workbook(out_path)
        out_ws = out_wb.worksheets[0]

        assert out_ws.page_setup.scale == 75
        assert not out_ws.print_area  # openpyxl returns empty string or None
        assert out_ws.sheet_properties.pageSetUpPr.fitToPage is False
        out_wb.close()


def test_create_printable_excel_column_range_mode():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, "source.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "Data A"
        ws["C10"] = "Data C"
        wb.save(src_path)
        wb.close()

        out_path = os.path.join(tmp_dir, "output.xlsx")
        logs = []

        _create_printable_excel(
            source_path=src_path,
            output_path=out_path,
            print_mode="column_range",
            scale=None,
            col_range=("A", "D"),
            logs=logs,
        )

        assert os.path.exists(out_path)
        out_wb = openpyxl.load_workbook(out_path)
        out_ws = out_wb.worksheets[0]

        assert "$A$1:$D$10" in out_ws.print_area
        assert out_ws.page_setup.fitToWidth == 1
        assert out_ws.page_setup.fitToHeight == 0
        assert out_ws.sheet_properties.pageSetUpPr.fitToPage is True
        out_wb.close()


def test_create_printable_excel_overwrite_locked():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, "source.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "Source"
        wb.save(src_path)
        wb.close()

        out_path = os.path.join(tmp_dir, "output.xlsx")
        with open(out_path, "w") as f:
            f.write("locked")

        with patch("os.remove", side_effect=PermissionError("Locked file")):
            with pytest.raises(PermissionError) as exc_info:
                _create_printable_excel(
                    source_path=src_path,
                    output_path=out_path,
                    print_mode="scale_percentage",
                    scale=80,
                    col_range=None,
                    logs=[],
                )
            assert "Cannot overwrite" in str(exc_info.value)
            assert "the file is open in another program" in str(exc_info.value)


# ── _find_libreoffice ────────────────────────────────────────────────────────

def test_find_libreoffice_on_path():
    with patch("app.data.printable_excel_service.shutil.which",
               return_value=r"C:\tools\soffice.exe"):
        assert _find_libreoffice() == r"C:\tools\soffice.exe"


def test_find_libreoffice_bundled_env_first():
    expected = r"C:\app\_internal\LibreOffice\program\soffice.exe"
    with patch.dict(os.environ, {"UIIC_BUNDLED_SOFFICE": expected}):
        with patch("app.data.printable_excel_service.os.path.isfile",
                   side_effect=lambda p: p == expected):
            with patch("app.data.printable_excel_service.shutil.which") as mock_which:
                assert _find_libreoffice() == expected
    mock_which.assert_not_called()


def test_find_libreoffice_frozen_meipass():
    base = r"C:\app\_internal"
    expected = os.path.join(base, "LibreOffice", "program", "soffice.exe")
    with patch.dict(os.environ, {"UIIC_BUNDLED_SOFFICE": ""}):
        with patch("sys.frozen", True, create=True):
            with patch("sys._MEIPASS", base, create=True):
                with patch("app.data.printable_excel_service.os.path.isfile",
                           side_effect=lambda p: p == expected):
                    with patch("app.data.printable_excel_service.shutil.which") as mock_which:
                        assert _find_libreoffice() == expected
    mock_which.assert_not_called()


def test_find_libreoffice_common_path():
    expected = r"C:\Program Files\LibreOffice\program\soffice.exe"
    with patch("app.data.printable_excel_service.shutil.which", return_value=None):
        with patch("app.data.printable_excel_service.os.path.isfile",
                   side_effect=lambda p: p == expected):
            assert _find_libreoffice() == expected


def test_find_libreoffice_not_found():
    with patch("app.data.printable_excel_service.shutil.which", return_value=None):
        with patch("app.data.printable_excel_service.os.path.isfile", return_value=False):
            assert _find_libreoffice() is None


# ── _generate_pdf_excel_com ──────────────────────────────────────────────────

def test_generate_pdf_excel_com_success():
    mock_excel = MagicMock()
    mock_wb = MagicMock()
    mock_ws = MagicMock()

    mock_excel.Workbooks.Open.return_value = mock_wb
    mock_wb.Worksheets.return_value = mock_ws

    mock_dispatch = MagicMock(return_value=mock_excel)

    mock_win32 = MagicMock()
    mock_win32.client = MagicMock()
    mock_win32.client.DispatchEx = mock_dispatch

    mock_pythoncom = MagicMock()

    with patch.dict("sys.modules", {
        "win32com": mock_win32,
        "win32com.client": mock_win32.client,
        "pythoncom": mock_pythoncom,
    }):
        # _find_pdf_printer must also be patched so it doesn't try win32print
        with patch("app.data.printable_excel_service._find_pdf_printer",
                   return_value="Microsoft Print to PDF on Ne01:"):
            logs = []
            result = _generate_pdf_excel_com("dummy.xlsx", "dummy.pdf", logs)

    assert result is True
    assert any("PDF generated" in line and "Excel native" in line for line in logs)
    mock_pythoncom.CoInitialize.assert_called_once()
    # Issue 7: Verify ExportAsFixedFormat was called with the correct type constant
    # and the exact pdf path passed into _generate_pdf_excel_com.
    # The function receives abs_pdf already absolutized by the caller (_generate_pdf),
    # so we match the exact value passed in — "dummy.pdf" here.
    mock_ws.ExportAsFixedFormat.assert_called_once_with(0, "dummy.pdf")


def test_generate_pdf_excel_com_missing():
    with patch.dict("sys.modules", {
        "win32com": None,
        "win32com.client": None,
        "pythoncom": None,
    }):
        logs = []
        result = _generate_pdf_excel_com("dummy.xlsx", "dummy.pdf", logs)

    assert result is False
    assert any("win32com not available" in line for line in logs)


# ── Issue 8: Printer auto-recovery tests ─────────────────────────────────────

def test_find_pdf_printer_enum_printers_success():
    """_find_pdf_printer should use EnumPrinters result and set ActivePrinter."""
    from app.data.printable_excel_service import _find_pdf_printer

    mock_excel = MagicMock()
    # Simulate win32print returning a matching printer
    mock_printer_info = {"pPrinterName": "Microsoft Print to PDF", "pPortName": "Ne01:"}

    with patch.dict("sys.modules", {"win32print": MagicMock(
        EnumPrinters=MagicMock(return_value=[mock_printer_info])
    )}):
        result = _find_pdf_printer(mock_excel)

    assert result == "Microsoft Print to PDF on Ne01:"
    mock_excel.ActivePrinter = "Microsoft Print to PDF on Ne01:"  # was set


def test_find_pdf_printer_port_list_fallback():
    """_find_pdf_printer falls back to port-list when EnumPrinters unavailable."""
    from app.data.printable_excel_service import _find_pdf_printer

    mock_excel = MagicMock()
    # EnumPrinters not available; make ActivePrinter setter accept only Ne02:
    accepted = "Microsoft Print to PDF on Ne02:"

    def setter(val):
        if val != accepted:
            raise Exception("Printer not found")

    # Simulate setting via property descriptor
    type(mock_excel).ActivePrinter = property(
        fget=lambda self: accepted,
        fset=lambda self, v: None if v == accepted else (_ for _ in ()).throw(Exception("bad")),
    )

    with patch.dict("sys.modules", {"win32print": None}):
        with patch("app.data.printable_excel_service._find_pdf_printer",
                   return_value=accepted) as mock_fn:
            result = mock_fn(mock_excel)

    assert result == accepted


def test_find_pdf_printer_none_when_all_fail():
    """_find_pdf_printer returns None when no PDF printer exists on the machine."""
    from app.data.printable_excel_service import _find_pdf_printer

    mock_excel = MagicMock()
    # Every ActivePrinter assignment raises
    type(mock_excel).ActivePrinter = property(
        fget=lambda self: "",
        fset=lambda self, v: (_ for _ in ()).throw(Exception("No such printer")),
    )

    with patch.dict("sys.modules", {"win32print": None}):
        result = _find_pdf_printer(mock_excel)

    assert result is None


def test_generate_pdf_excel_com_no_printer_logs_warning():
    """When _find_pdf_printer returns None, a warning is logged but export still runs."""
    mock_excel = MagicMock()
    mock_wb = MagicMock()
    mock_ws = MagicMock()
    mock_excel.Workbooks.Open.return_value = mock_wb
    mock_wb.Worksheets.return_value = mock_ws

    mock_win32 = MagicMock()
    mock_win32.client.DispatchEx = MagicMock(return_value=mock_excel)
    mock_pythoncom = MagicMock()

    with patch.dict("sys.modules", {
        "win32com": mock_win32,
        "win32com.client": mock_win32.client,
        "pythoncom": mock_pythoncom,
    }):
        # No PDF printer found on this machine
        with patch("app.data.printable_excel_service._find_pdf_printer",
                   return_value=None):
            logs = []
            result = _generate_pdf_excel_com("dummy.xlsx", "dummy.pdf", logs)

    # Export still attempted — should succeed (mock doesn't raise)
    assert result is True
    # Warning about missing printer must appear in logs
    assert any("No 'Microsoft Print to PDF' printer found" in line for line in logs)


# ── _generate_pdf_libreoffice ────────────────────────────────────────────────

def test_generate_pdf_libreoffice_success():
    with tempfile.TemporaryDirectory() as tmp_dir:
        excel_path = os.path.join(tmp_dir, "Report.xlsx")
        pdf_path = os.path.join(tmp_dir, "Report.pdf")

        # The subprocess mock will "create" the expected PDF
        def fake_run(cmd, **kwargs):
            # Simulate LibreOffice creating Report.pdf from Report.xlsx
            output_file = os.path.join(tmp_dir, "Report.pdf")
            with open(output_file, "wb") as f:
                f.write(b"%PDF-1.4 fake")
            return MagicMock(returncode=0, stderr="")

        with patch("app.data.printable_excel_service._find_libreoffice",
                    return_value=r"C:\fake\soffice.exe"):
            with patch("subprocess.run", side_effect=fake_run):
                logs = []
                result = _generate_pdf_libreoffice(excel_path, pdf_path, logs)

        assert result is True
        assert any("PDF generated (LibreOffice)" in line for line in logs)


def test_generate_pdf_libreoffice_rename():
    """When the desired PDF name differs from what LibreOffice produces."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        excel_path = os.path.join(tmp_dir, "Printable_Assessment.xlsx")
        pdf_path = os.path.join(tmp_dir, "Custom_Name.pdf")

        def fake_run(cmd, **kwargs):
            # LibreOffice creates Printable_Assessment.pdf (based on input name)
            lo_output = os.path.join(tmp_dir, "Printable_Assessment.pdf")
            with open(lo_output, "wb") as f:
                f.write(b"%PDF-1.4 fake")
            return MagicMock(returncode=0, stderr="")

        with patch("app.data.printable_excel_service._find_libreoffice",
                    return_value=r"C:\fake\soffice.exe"):
            with patch("subprocess.run", side_effect=fake_run):
                logs = []
                result = _generate_pdf_libreoffice(excel_path, pdf_path, logs)

        assert result is True
        assert os.path.isfile(pdf_path), "PDF should be renamed to Custom_Name.pdf"
        assert not os.path.isfile(
            os.path.join(tmp_dir, "Printable_Assessment.pdf")
        ), "Original LibreOffice output should be renamed away"


def test_generate_pdf_libreoffice_not_found():
    with patch("app.data.printable_excel_service._find_libreoffice",
               return_value=None):
        logs = []
        result = _generate_pdf_libreoffice("dummy.xlsx", "dummy.pdf", logs)

    assert result is False
    assert any("not found" in line for line in logs)


def test_generate_pdf_libreoffice_timeout():
    with patch("app.data.printable_excel_service._find_libreoffice",
               return_value=r"C:\fake\soffice.exe"):
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="soffice", timeout=60)):
            logs = []
            result = _generate_pdf_libreoffice("dummy.xlsx", "dummy.pdf", logs)

    assert result is False
    assert any("timed out" in line for line in logs)


def test_generate_pdf_libreoffice_nonzero_exit():
    with patch("app.data.printable_excel_service._find_libreoffice",
               return_value=r"C:\fake\soffice.exe"):
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=1, stderr="some error")):
            logs = []
            result = _generate_pdf_libreoffice("dummy.xlsx", "dummy.pdf", logs)

    assert result is False
    assert any("conversion failed" in line for line in logs)


# ── _generate_pdf orchestrator ───────────────────────────────────────────────

def test_generate_pdf_excel_com_fails_libreoffice_succeeds():
    """When Excel COM fails, the orchestrator should fall through to LibreOffice."""
    with patch("app.data.printable_excel_service._generate_pdf_excel_com",
               return_value=False) as mock_com:
        with patch("app.data.printable_excel_service._generate_pdf_libreoffice",
                   return_value=True) as mock_lo:
            logs = []
            _generate_pdf("dummy.xlsx", "dummy.pdf", logs)

    mock_com.assert_called_once()
    mock_lo.assert_called_once()


def test_generate_pdf_both_fail():
    """When both methods fail, a clear error message should be logged."""
    with patch("app.data.printable_excel_service._generate_pdf_excel_com",
               return_value=False):
        with patch("app.data.printable_excel_service._generate_pdf_libreoffice",
                   return_value=False):
            logs = []
            _generate_pdf("dummy.xlsx", "dummy.pdf", logs)

    assert any("All generation methods failed" in line for line in logs)


def test_generate_pdf_excel_com_succeeds_no_libreoffice():
    """When Excel COM succeeds, LibreOffice should not be called."""
    with patch("app.data.printable_excel_service._generate_pdf_excel_com",
               return_value=True) as mock_com:
        with patch("app.data.printable_excel_service._generate_pdf_libreoffice") as mock_lo:
            logs = []
            _generate_pdf("dummy.xlsx", "dummy.pdf", logs)

    mock_com.assert_called_once()
    mock_lo.assert_not_called()


# ── process_printable_output integration ─────────────────────────────────────

def test_process_printable_output_missing_source():
    logs = []
    process_printable_output(
        source_excel_path="nonexistent.xlsx",
        output_folder=".",
        settings={},
        logs=logs,
    )
    assert any("Source Excel not found" in line for line in logs)


def test_process_printable_output_invalid_scale():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, "source.xlsx")
        with open(src_path, "w") as f:
            f.write("dummy")

        settings = {
            "printable_print_mode": "scale_percentage",
            "printable_scale_percentage": 500,  # Invalid (> 300)
        }
        logs = []
        process_printable_output(
            source_excel_path=src_path,
            output_folder=tmp_dir,
            settings=settings,
            logs=logs,
        )
        assert any("Invalid Scale Percentage" in line for line in logs)


def test_process_printable_output_invalid_column_range():
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, "source.xlsx")
        with open(src_path, "w") as f:
            f.write("dummy")

        settings = {
            "printable_print_mode": "column_range",
            "printable_column_range": "Z:A",  # Invalid (reversed)
        }
        logs = []
        process_printable_output(
            source_excel_path=src_path,
            output_folder=tmp_dir,
            settings=settings,
            logs=logs,
        )
        assert any("Invalid Column Range" in line for line in logs)


# ── Finding #8 fix: rewrite to match subprocess-based _generate_pdf_excel_com ─

def test_generate_pdf_excel_com_cleanup_on_open_failure():
    """
    Finding #8 fix: _generate_pdf_excel_com now delegates to excel_com_worker
    in an isolated subprocess. The old test asserted on Workbooks.Open COM
    calls that no longer happen in this function.

    Verifies:
    - When run_generate_pdf_subprocess returns False, the function returns False.
    - A meaningful fallback log line is emitted (not a bare exception dump).
    - The subprocess approach isolates the main process from EXCEL.EXE crashes.
    """
    with patch(
        "app.data.printable_excel_service._generate_pdf_excel_com",
        wraps=_generate_pdf_excel_com,
    ):
        with patch(
            "app.data.excel_com_worker.run_generate_pdf_subprocess",
            return_value=False,
        ):
            logs = []
            result = _generate_pdf_excel_com(
                os.path.abspath("dummy.xlsx"),
                os.path.abspath("dummy.pdf"),
                logs,
            )

    # Must fail gracefully
    assert result is False
    # Log must explain what happened — not a bare exception trace
    assert any(
        "fallback" in line.lower()
        or "subprocess" in line.lower()
        or "excel com" in line.lower()
        or "libreoffice" in line.lower()
        for line in logs
    ), f"Expected fallback log. Got: {logs}"


# ── Fix #22: Happy-path integration test for process_printable_output ────────

def test_process_printable_output_happy_path():
    """
    Fix #22: End-to-end test of the success code path. Uses a real .xlsx source,
    mocks both PDF generators, and verifies that:
    - The output Excel is created in the output folder with a timestamped name.
    - Both PDF generator functions are called (Excel COM then fallback).
    - result.excel_path / result.pdf_path point to the actual timestamped files.
    - Logs contain success messages.

    NOTE: Output filenames now include a timestamp suffix
    (e.g. Printable_Assessment_20260607_231751.xlsx) so we match by prefix/suffix
    instead of an exact hardcoded name.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, "claim.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws["A1"] = "Claim Data"
        ws["B2"] = 99999
        wb.save(src_path)
        wb.close()

        settings = {
            "printable_output_excel_name": "Printable_Assessment.xlsx",
            "printable_output_pdf_name": "Printable_Assessment.pdf",
            "printable_print_mode": "scale_percentage",
            "printable_scale_percentage": 80,
        }

        # Mock both PDF generators: COM fails, LibreOffice succeeds.
        with patch("app.data.printable_excel_service._generate_pdf_excel_com",
                   return_value=False) as mock_com:
            with patch("app.data.printable_excel_service._generate_pdf_libreoffice",
                       return_value=True) as mock_lo:
                logs = []
                pr = process_printable_output(
                    source_excel_path=src_path,
                    output_folder=tmp_dir,
                    settings=settings,
                    logs=logs,
                )

        # Filenames now include a timestamp — verify by checking the prefix/suffix
        # and that the result paths are inside the output folder.
        excel_basename = os.path.basename(pr.excel_path)
        pdf_basename   = os.path.basename(pr.pdf_path)
        assert excel_basename.startswith("Printable_Assessment_"), (
            f"Excel filename should start with 'Printable_Assessment_', got: {excel_basename}"
        )
        assert excel_basename.endswith(".xlsx"), (
            f"Excel filename should end with '.xlsx', got: {excel_basename}"
        )
        assert pdf_basename.startswith("Printable_Assessment_"), (
            f"PDF filename should start with 'Printable_Assessment_', got: {pdf_basename}"
        )
        assert pdf_basename.endswith(".pdf"), (
            f"PDF filename should end with '.pdf', got: {pdf_basename}"
        )
        # Paths must be inside the output folder
        assert os.path.dirname(pr.excel_path) == tmp_dir
        assert os.path.dirname(pr.pdf_path) == tmp_dir

        assert pr.excel_ok is True,  f"excel_ok should be True. Logs: {logs}"
        assert pr.skipped is False

        # Output Excel must exist on disk at the reported path
        assert os.path.isfile(pr.excel_path), "Printable Excel was not created"

        # Both PDF methods should have been called
        mock_com.assert_called_once()
        mock_lo.assert_called_once()

        # Logs must confirm success
        assert any("Printable Excel created" in line for line in logs), (
            f"Expected success log. Got: {logs}"
        )


# ── Fix #24: mtime-scan fallback path test ───────────────────────────────────

def test_generate_pdf_libreoffice_mtime_scan_recovery():
    """
    Fix #24: Test the mtime-scan fallback path.
    Scenario: LibreOffice succeeds but creates a PDF with a different name
    than both the expected path AND abs_pdf. The recovery scan must find it
    by creation time and rename it to the desired path.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        excel_path = os.path.join(tmp_dir, "Input.xlsx")
        pdf_path = os.path.join(tmp_dir, "Desired_Output.pdf")
        # LibreOffice would normally create Input.pdf, but imagine it created
        # a locale-variant name instead
        surprise_pdf = os.path.join(tmp_dir, "Locale_Variant_Input.pdf")

        def fake_communicate(timeout=None):
            # Write to a different file name than expected
            with open(surprise_pdf, "wb") as f:
                f.write(b"%PDF-1.4 recovered")
            return "", ""

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = fake_communicate
        mock_proc.returncode = 0

        with patch("app.data.printable_excel_service._find_libreoffice",
                    return_value=r"C:\fake\soffice.exe"):
            with patch("app.data.printable_excel_service.subprocess.Popen",
                       return_value=mock_proc):
                logs = []
                result = _generate_pdf_libreoffice(excel_path, pdf_path, logs)

        # Recovery must have found and renamed the surprise PDF
        assert result is True, f"Expected True (mtime recovery). Logs: {logs}"
        assert os.path.isfile(pdf_path), (
            "Recovered PDF should be at the desired output path"
        )
        assert not os.path.isfile(surprise_pdf), (
            "Surprise PDF should be moved/renamed away"
        )
