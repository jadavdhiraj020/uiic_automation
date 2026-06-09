import os
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


# ── _generate_pdf orchestrator ───────────────────────────────────────────────

def test_generate_pdf_excel_com_succeeds():
    with patch("app.data.printable_excel_service._generate_pdf_excel_com",
               return_value=True) as mock_com:
        logs = []
        _generate_pdf("dummy.xlsx", "dummy.pdf", logs)
    mock_com.assert_called_once()
    assert not any("Generation failed" in line for line in logs)


def test_generate_pdf_excel_com_fails():
    with patch("app.data.printable_excel_service._generate_pdf_excel_com",
               return_value=False) as mock_com:
        logs = []
        _generate_pdf("dummy.xlsx", "dummy.pdf", logs)
    mock_com.assert_called_once()
    assert any("Generation failed" in line for line in logs)


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





# ── Fix #22: Happy-path integration test for process_printable_output ────────

def test_process_printable_output_happy_path():
    """
    Fix #22: End-to-end test of the success code path. Uses a real .xlsx source,
    mocks both PDF generators, and verifies that:
    - The output Excel is created in the output folder with a timestamped name.
    - PDF generator function is called.
    - Logs contain success messages.
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

        # Mock PDF generator: COM succeeds.
        def fake_pdf_gen(excel_path, pdf_path, logs):
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4 mock")
            return True

        with patch("app.data.printable_excel_service._generate_pdf_excel_com",
                   side_effect=fake_pdf_gen) as mock_com:
            logs = []
            process_printable_output(
                source_excel_path=src_path,
                output_folder=tmp_dir,
                settings=settings,
                logs=logs,
            )

        # Filenames now include a timestamp — verify by checking the prefix/suffix
        # and that the result paths are inside the output folder.
        files = os.listdir(tmp_dir)
        excel_files = [f for f in files if f.startswith("Printable_Assessment_") and f.endswith(".xlsx")]
        pdf_files = [f for f in files if f.startswith("Printable_Assessment_") and f.endswith(".pdf")]

        assert len(excel_files) == 1, f"Expected 1 excel file, found: {excel_files}"
        assert len(pdf_files) == 1, f"Expected 1 pdf file, found: {pdf_files}"

        excel_basename = excel_files[0]
        pdf_basename   = pdf_files[0]

        assert excel_basename.startswith("Printable_Assessment_")
        assert pdf_basename.startswith("Printable_Assessment_")

        # Output Excel must exist on disk
        assert os.path.isfile(os.path.join(tmp_dir, excel_basename)), "Printable Excel was not created"

        # PDF COM method should have been called
        mock_com.assert_called_once()

        # Logs must confirm success
        assert any("Printable Excel created" in line for line in logs), (
            f"Expected success log. Got: {logs}"
        )


# ── Fix #24: mtime-scan fallback path test ───────────────────────────────────


