# UIIC Surveyor Automation

Reliable desktop automation for UIIC surveyor claim processing.

This app combines a PyQt6 desktop UI, Playwright browser automation, and PaddleOCR CAPTCHA solving to reduce repetitive claim-entry work while preserving final human review.

## At a glance

| Area | Details |
|---|---|
| Platform | Windows 10/11 |
| Python | 3.10 to 3.12 (3.10 preferred for release builds) |
| UI | PyQt6 |
| Automation | Playwright |
| OCR | PaddleOCR + PaddlePaddle 2.x |
| Packaging | PyInstaller |

## What the automation does

1. Logs in to the UIIC surveyor portal.
2. Solves CAPTCHA locally using OCR.
3. Opens worklist and navigates to the claim.
4. Fills interim report values.
5. Uploads claim and assessment documents.
6. Fills claim assessment amounts and fields.
7. Leaves browser open for manual final validation and submit.

## Quick start (recommended)

Use this exact flow on a fresh machine:

```powershell
winget install --id=astral-sh.uv -e
git clone <your-repo-url>
cd uiic_automation
uv venv --python 3.10
uv pip install -r requirements.txt
uv run playwright install chromium
uv run python main.py
```

## Why this setup path

This repository includes `pyproject.toml` and requirement files, but current production behavior is most stable when dependencies are installed from:

- `requirements.txt` for runtime
- `requirements-build.txt` for packaging/build

For now, avoid `uv sync` on fresh environments unless you maintain a validated lockfile for your target OS/Python combination.

## Installation and environment (detailed)

### 1) Install uv

Choose one:

```powershell
winget install --id=astral-sh.uv -e
```

or

```powershell
pip install uv
```

### 2) Clone repository

```powershell
git clone <your-repo-url>
cd uiic_automation
```

### 3) Create virtual environment

```powershell
uv venv --python 3.10
```

### 4) Install runtime dependencies

```powershell
uv pip install -r requirements.txt
```

### 5) Install browser runtime

```powershell
uv run playwright install chromium
```

### 6) Optional: test tools

```powershell
uv pip install pytest
```

### 7) Sanity check

```powershell
uv run python -c "import PyQt6,playwright,paddleocr,pandas; print('Environment OK')"
```

## Run from source

```powershell
uv run python main.py
```

## End-user operating flow

1. Enter portal username and password.
2. Browse and select one claim folder.
3. Start automation.
4. Wait for all steps to complete.
5. Review values in portal.
6. Click final submit manually.

Important:
- Browser is intentionally kept open at the end.
- Final submit is intentionally manual for safety.

## Input folder requirements

Use one folder per claim.

Required content:
- One Excel file (`.xls` or `.xlsx`)
- Claim documents (PDF/image files)
- Assessment supporting files

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

## Excel label mapping behavior

The parser is label-driven, not fixed-cell-driven. It scans sheets and extracts nearby values for known labels.

Common labels:

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

If your branch/region uses different text, update mapping files in `config`.

## Configuration files

Project mappings and defaults:

- `config/settings.json`
- `config/field_mapping.json`
- `config/doc_mapping.json`

Runtime user settings path:

- `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config\settings.json`

Common runtime keys:

- `portal_url`
- `browser_headless`
- `browser_slow_mo_ms`
- `captcha_max_retries`

## Build Windows EXE

### Option A: release build script (preferred)

```powershell
.\build.bat
```

This script:

1. Creates/reuses `.venv`.
2. Installs pinned build dependencies from `requirements-build.txt`.
3. Prepares Playwright browsers under `build_assets/ms-playwright`.
4. Prepares PaddleOCR model cache under `build_assets/paddleocr`.
5. Runs PyInstaller with `uiic_automation.spec`.

Expected output:

- `dist/UIIC_Surveyor_Automation/UIIC_Surveyor_Automation.exe`

### Option B: uv + Python build script

```powershell
uv pip install -r requirements-build.txt
uv run python build.py
```

## Testing

Install pytest if needed:

```powershell
uv pip install pytest
```

Run full suite:

```powershell
uv run pytest -v
```

Run primary module only:

```powershell
uv run pytest tests/test_automation.py -v
```

## Project structure

```text
app/
  automation/      # Login, navigation, form fill, upload workflow
  data/            # Data model, Excel reader, folder scanner
  ui/              # Desktop UI and worker orchestration
  utils.py         # Resource and user-data path utilities
config/            # Field/doc/settings mappings
tests/             # Pytest suite
build.py           # Python build entrypoint
build.bat          # Windows packaging pipeline
main.py            # App startup entrypoint
```

## Troubleshooting

### Playwright browser missing

```powershell
uv run playwright install chromium
```

### OCR/CAPTCHA startup issues

- Ensure internet access for first-time runtime/model bootstrap.
- Keep PaddlePaddle on 2.x branch (`<3.0.0`) as defined by project constraints.
- For packaged builds, rerun `build.bat` to repopulate bundled runtime assets.

### Works on one PC, fails on another

Reset environment fully:

```powershell
Remove-Item -Recurse -Force .venv
uv venv --python 3.10
uv pip install -r requirements.txt
uv run playwright install chromium
```

Then verify:

```powershell
uv run python -c "import PyQt6,playwright,paddleocr,pandas; print('Environment OK')"
```

### App cannot find settings/mappings

- Confirm `config` files exist in source workspace.
- For packaged app, ensure the built folder contains bundled data from spec/build process.
- Check user settings path under `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config`.

### Portal workflow changed

- Update selectors/navigation in `app/automation` modules.
- Update label mappings in `config/field_mapping.json` and `config/doc_mapping.json`.

## Security notes

- Data processing is local-first.
- Credentials are read from local user settings unless deployment policy overrides this.
- Text is sanitized before form-injection paths in automation helpers.

## Maintainer guidance

1. Prefer `uv pip install -r requirements*.txt` in onboarding docs until lockfile workflow is standardized.
2. Use Python 3.10 for release reproducibility.
3. Keep `pyproject.toml`, `requirements.txt`, and `requirements-build.txt` aligned.
