# UIIC Surveyor Automation

Desktop automation tool for processing UIIC surveyor claims using a PyQt6 UI, Playwright browser automation, and PaddleOCR-based CAPTCHA solving.

This project is designed for Windows workflows and can be run from source or packaged as a standalone EXE.

## What This Project Does

- Logs in to the UIIC surveyor portal.
- Solves portal CAPTCHA locally using PaddleOCR.
- Navigates to the target claim in worklist.
- Fills interim report fields.
- Uploads claim documents and assessment files.
- Fills claim assessment values from Excel data.
- Leaves browser open at the end for final manual review and submit.

## Key Tech Stack

- Python 3.10 to 3.12
- PyQt6 (desktop UI)
- Playwright (browser automation)
- PaddleOCR / PaddlePaddle (CAPTCHA OCR)
- pandas + openpyxl + xlrd (Excel ingestion)
- PyInstaller (Windows packaging)

## Requirements

- OS: Windows 10/11
- Python: 3.10 to 3.12
  - Preferred for release builds: Python 3.10
  - Supported for local development: Python 3.10/3.11/3.12
- Microsoft Edge/Chromium runtime support (installed automatically via Playwright command below)

## Package Manager: uv (Recommended)

This repository uses `uv` as the Python package manager, but installs from the repository requirement files for deterministic Windows behavior.

### 1. Install uv

Pick one method:

```powershell
winget install --id=astral-sh.uv -e
```

or

```powershell
pip install uv
```

### 2. Clone and enter project

```powershell
git clone <your-repo-url>
cd uiic_automation
```

### 3. Create environment and install dependencies (stable path)

```powershell
uv venv --python 3.10
uv pip install -r requirements.txt
```

Notes:
- This project currently relies on curated constraints in `requirements.txt` / `requirements-build.txt`.
- Avoid `uv sync` on fresh machines unless a validated lockfile is maintained for your target environment.

### 4. Install Playwright browser runtime

```powershell
uv run playwright install chromium
```

### 5. (Optional) Install test tooling

```powershell
uv pip install pytest
```

### 6. Verify installation quickly

```powershell
uv run python -c "import PyQt6,playwright,paddleocr,pandas; print('OK')"
```

## Run the App (Source)

```powershell
uv run python main.py
```

## End-User Usage Flow

1. Enter portal username/password.
2. Select a single claim folder.
3. Start automation.
4. Wait for the bot to complete all steps.
5. Perform final manual review and submit in portal.

Important:
- Automation intentionally keeps the browser open at the end.
- Final submit should be done manually after verification.

## Claim Folder Structure

Keep one claim per folder. Include:

- One Excel report file (`.xls` or `.xlsx`)
- Claim document files (PDF/images)
- Assessment-related files (invoice/report photos etc.)

Example:

```text
Your_Claim_Folder/
|-- survey_report.xlsx
|-- Driving_License.pdf
|-- Registration_Certificate.pdf
|-- Discharge_Voucher.pdf
|-- Final_Invoice.pdf
|-- Survey_Report.pdf
`-- other-Additional_Doc.pdf
```

## Excel Data Expectations

The parser is label-driven (not fixed-cell driven). It scans sheets and extracts values near known labels.

Typical labels used by the automation include:

- `Claim no`
- `Date and Time of Survey`
- `Workshop`
- `Mobile:`
- `e-mail:-`
- `OBERVATIONS/COMMENTS`
- `PAYMENT MADE IN THE FAVOUR OF`
- `NET PAYABLE`
- `SUB TOTAL`
- `LABOUR ESTIMATED`
- `TOWING CHARGES`
- `LESS SALVAGE VALUE`
- `CONVEYANCE CHARGES`
- `PROFESSIONAL FEE`
- `DAILY ALLOWANCE`
- `PHOTOGRAPHS`
- `Ref:`

If your organization uses a different wording pattern, update mapping files in the `config/` directory.

## Configuration

Project config files:

- `config/settings.json`
- `config/field_mapping.json`
- `config/doc_mapping.json`

Runtime user settings are stored in:

- `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config\settings.json`

Useful runtime keys:

- `portal_url`
- `browser_headless`
- `browser_slow_mo_ms`
- `captcha_max_retries`

## Build Windows EXE

Two supported build paths are available.

### Option A: Preferred scripted release build

```powershell
.\build.bat
```

What it does:

- Creates/reuses `.venv`
- Installs pinned build deps from `requirements-build.txt`
- Prepares Playwright runtime in `build_assets/ms-playwright`
- Prepares PaddleOCR models in `build_assets/paddleocr`
- Runs PyInstaller using `uiic_automation.spec`

Output:

- `dist/UIIC_Surveyor_Automation/UIIC_Surveyor_Automation.exe`

### Option B: uv-based Python build command

Before running this option, install build dependencies in the uv environment:

```powershell
uv pip install -r requirements-build.txt
```

Then run:

```powershell
uv run python build.py
```

This uses the Python build script and the PyInstaller spec fallback behavior implemented in the repository.

## Testing

Run full tests:

```powershell
uv pip install pytest
uv run pytest -v
```

Run the primary automation test module only:

```powershell
uv run pytest tests/test_automation.py -v
```

## Project Layout

```text
app/
  automation/      # Playwright steps, login, navigation, form filling
  data/            # Excel/data model/folder scanning
  ui/              # PyQt UI and worker threading
  utils.py         # resource and user-data path helpers
config/            # field/doc/settings mappings
tests/             # pytest test suite
build.py           # Python build entrypoint
build.bat          # Windows release build pipeline
main.py            # app startup entrypoint
```

## Troubleshooting

### 1) Playwright browser not found

Run:

```powershell
uv run playwright install chromium
```

### 2) CAPTCHA/OCR issues on first run

- Ensure internet is available for first model/runtime bootstrap if needed.
- Re-run build prep (`build.bat`) for release artifacts.
- Keep PaddlePaddle on 2.x branch (`<3.0.0`) as already constrained.

### 3) App starts but cannot find settings or mappings

- Verify `config/` files exist in source checkout.
- For packaged builds, ensure all bundled data from spec/build process is present.
- Check user settings path under `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config`.

### 4) Portal flow changed

- Update selectors and navigation logic in `app/automation/` modules.
- Adjust label mappings in `config/field_mapping.json` and `config/doc_mapping.json`.

### 5) Setup works on one machine but fails on another

- Prefer Python 3.10 for the most stable dependency behavior.
- Use the stable install path shown above (`uv pip install -r requirements.txt`) instead of `uv sync`.
- Recreate environment cleanly:

```powershell
Remove-Item -Recurse -Force .venv
uv venv --python 3.10
uv pip install -r requirements.txt
uv run playwright install chromium
```

## Security and Privacy

- Local-first execution: claim data processing happens on the local machine.
- Credentials are stored in local user settings unless your deployment process changes this behavior.
- Form input strings are sanitized before portal injection paths in automation helpers.

## Maintainer Notes

- Prefer `uv pip install -r requirements*.txt` in docs/onboarding until lockfile workflow is standardized.
- Use Python 3.10 for release reproducibility.
- Keep build/runtime dependencies aligned between `pyproject.toml`, `requirements.txt`, and `requirements-build.txt`.
