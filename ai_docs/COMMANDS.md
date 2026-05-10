# Project Commands

## Purpose

This is the canonical command reference for future AI and developer sessions. Use these commands instead of inventing different variants.

## Mandatory Rule

Use `uv` for Python execution in this project.

Do not use random alternatives such as:

```bash
python main.py
python3 main.py
pytest
pip install ...
pyinstaller ...
```

Use the `uv` commands below unless there is a clear reason and the reason is documented.

## Working Directory

Run commands from the repository root:

```bash
cd /mnt/c/Users/jadav/Coding/Automation/UIIC/uiic_automation
```

## Environment Setup

Preferred Python for local setup and Windows EXE builds is Python 3.10.

```bash
uv venv --python 3.10
uv pip install -r requirements.txt
uv run playwright install chromium
```

For build dependencies:

```bash
uv pip install -r requirements-build.txt
```

If using `pyproject.toml`/`uv.lock` sync instead of requirements files:

```bash
uv sync --dev
uv run playwright install chromium
```

Use only one setup path per environment. Do not mix multiple install strategies casually.

## Run The App

Canonical app launch:

```bash
uv run python main.py
```

Use this for normal development verification after code changes that affect UI, extraction, settings, or automation startup.

## Run Tests

Run the full test suite:

```bash
uv run pytest
```

Run one test file:

```bash
uv run pytest tests/test_automation.py
```

Run one test by name:

```bash
uv run pytest tests/test_automation.py -k "ClaimData"
```

Run with verbose output:

```bash
uv run pytest -v
```

Stop after first failure:

```bash
uv run pytest -x
```

## Build Windows App

Install build dependencies first:

```bash
uv pip install -r requirements-build.txt
```

Canonical build command:

```bash
uv run python build.py
```

The build script uses `uiic_automation.spec` when present and handles bundled config, QSS, icon, Playwright, and PaddleOCR assets.

Expected output:

```text
dist/UIIC_Surveyor_Automation/UIIC_Surveyor_Automation.exe
```

## Playwright Browser Install

Install Chromium for Playwright:

```bash
uv run playwright install chromium
```

Use this if browser launch fails because Playwright cannot find Chromium.

## Quick Import Checks

Check core imports:

```bash
uv run python -c "import PyQt6, playwright, openpyxl, xlrd, pdfplumber; print('core imports ok')"
```

Check PaddleOCR import separately because it is heavier:

```bash
uv run python -c "import paddleocr; print('paddleocr import ok')"
```

Check app module import:

```bash
uv run python -c "from app.ui.main_window import MainWindow; print('app import ok')"
```

## Useful Read-Only Inspection Commands

List project files:

```bash
rg --files
```

Find text:

```bash
rg "search text"
```

Check git status:

```bash
git status --short
```

Inspect changes:

```bash
git diff -- path/to/file.py
```

Use git inspection commands only for review. Do not revert user changes unless explicitly requested.

## Logs And Runtime Files

Local project logs:

```bash
ls logs
```

AppData logs are written by the app under:

```text
LOCALAPPDATA/UIIC_Surveyor_Automation/logs/
```

AppData config is written under:

```text
LOCALAPPDATA/UIIC_Surveyor_Automation/
```

## Clean Build Artifacts

Only clean build outputs when the user asks or when rebuilding requires it:

```bash
rm -rf build dist
```

Do not delete claim folders, AppData settings, or generated user documents.

## Command Selection Rules For AI

- For app launch, always use `uv run python main.py`.
- For tests, always use `uv run pytest`.
- For builds, always use `uv run python build.py`.
- For browser install, always use `uv run playwright install chromium`.
- For dependency install, prefer `uv pip install -r requirements.txt`.
- For build dependency install, use `uv pip install -r requirements-build.txt`.
- For searching files/text, use `rg`.
- Do not run destructive git commands.
- Do not run multiple different command variants just to see what works.

