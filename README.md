<div align="center">

# 🏛️ UIIC Surveyor Automation

**Intelligent Desktop Automation for UIIC Insurance Claim Processing**

[![Python](https://img.shields.io/badge/Python-3.10--3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt6](https://img.shields.io/badge/UI-PyQt6-41CD52?style=for-the-badge&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![Playwright](https://img.shields.io/badge/Automation-Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev)
[![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://microsoft.com)

---

A professional-grade desktop application that automates repetitive UIIC surveyor portal
data entry — from **CAPTCHA solving** to **document uploading** — while preserving
full human control over final submission.

</div>

---

## 📋 Table of Contents

- [✨ Features](#-features)
- [🖥️ Screenshots](#️-screenshots)
- [⚡ Quick Start](#-quick-start)
- [📦 Installation (Detailed)](#-installation-detailed)
- [🚀 Usage Guide](#-usage-guide)
- [📁 Folder Structure Requirements](#-folder-structure-requirements)
- [📊 Excel Label Mapping](#-excel-label-mapping)
- [⚙️ Configuration Reference](#️-configuration-reference)
- [🔨 Building the Windows EXE](#-building-the-windows-exe)
- [🧪 Testing](#-testing)
- [🗂️ Project Architecture](#️-project-architecture)
- [🔧 Troubleshooting](#-troubleshooting)
- [🔒 Security](#-security)
- [👨‍💻 Maintainer Notes](#-maintainer-notes)

---

## ✨ Features

| Feature | Description |
|:--------|:------------|
| 🤖 **Smart CAPTCHA Solver** | Local PaddleOCR engine with multi-candidate case restoration — no external API calls |
| 📝 **Auto Form Filling** | Fills interim report, claim assessment, and all portal fields from Excel data |
| 📄 **Document Upload** | Automatically uploads claim documents, assessment files, and re-inspection reports |
| 🔍 **Label-Driven Extraction** | Finds data by searching for text labels in Excel — works with any cell layout |
| 🎨 **Professional UI** | Modern dark/light themed interface with real-time progress tracking and status indicators |
| 🛡️ **Popup Shield** | Auto-detects and closes blocking UIIC portal modals (feedback/maintenance popups) |
| ✅ **Validation Gate** | Pre-flight data validation with clear warnings before automation starts |
| 📊 **Live Progress** | Step-by-step pipeline view with granular per-file upload logging |
| 🔐 **Local-First** | All data processing happens on your machine — credentials never leave your computer |
| 🖐️ **Human Final Submit** | Browser stays open at the end for manual review — you always have the final say |

---

## 🖥️ Screenshots

> The application features a clean, modern interface designed for daily professional use.

**Home Page** — Configure credentials, select claim folder, preview extracted data  
**Progress Page** — Real-time step pipeline, live log output, and automation status

---

## ⚡ Quick Start

> **Prerequisites:** Windows 10/11, Python 3.10+ installed, internet for first-time setup

```powershell
# 1. Install the uv package manager
winget install --id=astral-sh.uv -e

# 2. Clone and enter the project
git clone https://github.com/jadavdhiraj020/uiic_automation.git
cd uiic_automation

# 3. Create virtual environment (Python 3.10 recommended)
uv venv --python 3.10

# 4. Install all dependencies
uv pip install -r requirements.txt

# 5. Install the browser engine
uv run playwright install chromium

# 6. Launch the application
uv run python main.py
```

> **💡 Tip:** After initial setup, you only need `uv run python main.py` to launch.

---

## 📦 Installation (Detailed)

### Step 1 — Install `uv` Package Manager

Choose one method:

```powershell
# Option A: Via Windows Package Manager (recommended)
winget install --id=astral-sh.uv -e

# Option B: Via pip
pip install uv
```

### Step 2 — Clone the Repository

```powershell
git clone <your-repo-url>
cd uiic_automation
```

### Step 3 — Create Virtual Environment

```powershell
uv venv --python 3.10
```

> **📌 Note:** Python 3.10 is the preferred version for maximum compatibility with PaddleOCR and PyInstaller builds. Python 3.11 and 3.12 are also supported.

### Step 4 — Install Runtime Dependencies

```powershell
uv pip install -r requirements.txt
```

### Step 5 — Install Browser Engine

```powershell
uv run playwright install chromium
```

### Step 6 — Verify Installation

```powershell
uv run python -c "import PyQt6,playwright,paddleocr,pandas; print('✅ Environment OK')"
```

### Step 7 — Launch

```powershell
uv run python main.py
```

---

## 🚀 Usage Guide

### For Surveyors (End Users)

```
┌─────────────────────────────────────────────────────────┐
│  1. 🔑  Enter portal Username & Password                │
│  2. 📂  Browse and select the claim folder              │
│  3. 👀  Review the extracted data preview table          │
│  4. ▶️  Click "Start Automation"                         │
│  5. ⏳  Wait for all steps to complete                   │
│  6. 🔍  Review values in the portal browser              │
│  7. ✅  Click final Submit MANUALLY in the portal        │
└─────────────────────────────────────────────────────────┘
```

### What the Automation Does (Step by Step)

| Step | Action | Details |
|:----:|:-------|:--------|
| 1 | 🔐 **Login** | Opens UIIC portal, solves CAPTCHA using local OCR, enters credentials |
| 2 | 📋 **Navigate** | Opens Worklist, filters by claim number, enters the claim |
| 3 | 📝 **Interim Report** | Fills settlement type, dates, survey details, initial loss amount |
| 4 | 📄 **Claim Documents** | Uploads all matched claim documents (PDFs, images) |
| 5 | 💰 **Claim Assessment** | Fills parts depreciation, labour, GST, towing, professional fees |
| 6 | 📊 **Assessment Files** | Uploads assessment supporting documents |
| 7 | 🖐️ **Handoff** | Browser stays open — you review and submit manually |

> **⚠️ Important:** The final submit is **intentionally manual** for safety. The automation fills everything but never clicks the final submit button.

---

## 📁 Folder Structure Requirements

Each claim should have its **own dedicated folder** containing:

```
📂 Your_Claim_Folder/
├── 📊 survey_report.xlsx              ← Excel data file (required, .xls or .xlsx)
├── 📄 Driving_License.pdf             ← Claim documents
├── 📄 Registration_Certificate.pdf
├── 📄 Discharge_Voucher.pdf
├── 📄 Final_Invoice.pdf
├── 📄 Survey_Report.pdf
├── 📄 Re-Inspection_Report.pdf        ← Auto-extracted from Sheet 7
└── 📄 other-Additional_Doc.pdf        ← Any additional files
```

### Document Naming Convention

The application uses intelligent filename matching defined in `config/doc_mapping.json`:

| Filename Contains | Portal Category |
|:-----------------|:----------------|
| `driving` or `license` | Driving License |
| `registration` or `rc` | Registration Certificate |
| `discharge` or `voucher` | Discharge Voucher |
| `invoice` or `bill` | Final Invoice |
| `survey` or `report` | Survey Report |
| `photo` or `image` | Photographs |

> **💡 Tip:** Name your files clearly (e.g., `Driving_License.pdf`) for automatic matching. Unrecognized files are uploaded under "Additional Documents".

---

## 📊 Excel Label Mapping

The parser is **label-driven, not cell-position-driven**. It scans all sheets for known text labels and reads the value from a nearby cell (typically to the right).

### How It Works

```
Excel Cell: "Date and Time of Survey"  →  col_offset: 4  →  Value: "16/02/2026"
Excel Cell: "Workshop"                 →  col_offset: 4  →  Value: "Plot No. 177-H..."
Excel Cell: "Mobile:"                  →  col_offset: 1  →  Value: "9876135253"
```

### Common Labels Recognized

| Category | Labels |
|:---------|:-------|
| 🔢 **Claim Info** | `Claim no`, `Ref:`, `Date:` |
| 📅 **Survey Details** | `Date and Time of Survey`, `Workshop`, `Mobile:`, `e-mail:-` |
| 💰 **Financial** | `initial loss assessment`, `SUB TOTAL`, `TOTAL (R/R, DENTING...)` |
| 📋 **Assessment** | `TOWING CHARGES`, `LESS SALVAGE VALUE`, `Less Compulsory Excess` |
| 🧾 **Fees** | `SURVEY FEE`, `CONVEYANCE CHARGES`, `DAILY ALLOWANCE`, `PHOTOGRAPHS` |
| 📝 **Observations** | `OBERVATIONS/COMMENTS` |

> **📌 If your Excel uses different labels:** Edit `app/config/field_mapping.json` to match your surveyor's template. See the [Configuration Reference](#️-configuration-reference) below.

---

## ⚙️ Configuration Reference

All configuration lives in `app/config/`. These files control how the application reads data and interacts with the portal.

### 📄 `settings.json` — Application Settings

| Key | Default | Description |
|:----|:--------|:------------|
| `portal_url` | `https://portal.uiic.in/...` | UIIC portal login URL |
| `browser_headless` | `false` | Run browser visibly (`false`) or hidden (`true`) |
| `browser_slow_mo_ms` | `100` | Delay between browser actions (ms) — increase for stability |
| `captcha_max_retries` | `5` | Maximum CAPTCHA solve attempts before failing |

### 📄 `field_mapping.json` — Excel → Portal Field Mapping

Each entry maps a portal field to an Excel label:

```json
{
  "date_of_survey": {
    "sheet": "ALL",                              // Which sheet to search ("ALL" = every sheet)
    "search_label": "Date and Time of Survey",   // Text to find in Excel
    "row_offset": 0,                             // Rows below the label
    "col_offset": 4                              // Columns to the right of the label
  }
}
```

### 📄 `doc_mapping.json` — Document Filename → Portal Upload Category

Maps filename patterns to UIIC portal document types for automatic upload categorization.

### 🗂️ Runtime User Settings

User-specific settings (credentials, last-used paths) are stored at:

```
%LOCALAPPDATA%\UIIC_Surveyor_Automation\config\settings.json
```

> **💡 Reset to defaults:** Delete the above folder and restart the app. Factory defaults are restored automatically from the bundled config.

---

## 🔨 Building the Windows EXE

### Option A — One-Command Build (Recommended)

```powershell
.\build.bat
```

This automated script handles everything:

| Step | Action |
|:----:|:-------|
| 1/7 | Creates or reuses `.venv` with Python 3.10 |
| 2/7 | Verifies Python version compatibility |
| 3/7 | Installs pinned build dependencies from `requirements-build.txt` |
| 4/7 | Downloads and bundles Playwright Chromium browser |
| 5/7 | Downloads and bundles PaddleOCR models |
| 6/7 | Cleans previous build artifacts |
| 7/7 | Runs PyInstaller with `uiic_automation.spec` |

**Output:**

```
dist\UIIC_Surveyor_Automation\UIIC_Surveyor_Automation.exe
```

### Option B — Python Build Script

```powershell
uv pip install -r requirements-build.txt
uv run python build.py
```

### Option C — Quick Rebuild (Skip Dependency Install)

```powershell
.\build.bat --rebuild
```

> **📌 Note:** The EXE bundles everything needed — Python runtime, Chromium browser, OCR models, and all config files. End users don't need Python installed.

---

## 🧪 Testing

### Setup

```powershell
uv pip install pytest
```

### Run Full Test Suite

```powershell
uv run pytest -v
```

### Run Specific Module Tests

```powershell
# Automation tests only
uv run pytest tests/test_automation.py -v

# Data extraction tests only
uv run pytest tests/test_data.py -v
```

---

## 🗂️ Project Architecture

```
uiic_automation/
│
├── 📂 app/                          # Application source code
│   ├── 📂 automation/               # Browser automation modules
│   │   ├── engine.py                #   → Main orchestrator (runs the full workflow)
│   │   ├── login_module.py          #   → Portal login + CAPTCHA handling
│   │   ├── navigation_module.py     #   → Worklist navigation + claim lookup
│   │   ├── interim_report.py        #   → Interim Report tab automation
│   │   ├── claim_documents.py       #   → Document upload automation
│   │   ├── claim_assessment.py      #   → Claim Assessment tab automation
│   │   ├── captcha_solver.py        #   → PaddleOCR CAPTCHA solver
│   │   ├── form_helpers.py          #   → Smart form fill utilities
│   │   ├── tab_utils.py             #   → Portal tab switching helpers
│   │   └── selectors.py             #   → All CSS/DOM selectors (single source of truth)
│   │
│   ├── 📂 config/                   # Configuration files
│   │   ├── field_mapping.json       #   → Excel label → portal field mapping
│   │   ├── doc_mapping.json         #   → Filename → upload category mapping
│   │   └── settings.json            #   → Default application settings
│   │
│   ├── 📂 data/                     # Data extraction layer
│   │   ├── data_model.py            #   → ClaimData dataclass + validation
│   │   ├── excel_reader.py          #   → Label-driven Excel parser
│   │   └── folder_scanner.py        #   → Folder analysis + document detection
│   │
│   ├── 📂 ui/                       # Desktop interface
│   │   ├── main_window.py           #   → Full PyQt6 UI (topbar, cards, tables, log)
│   │   ├── styles.qss               #   → Global stylesheet (dark navbar, light cards)
│   │   └── worker.py                #   → Background thread for automation
│   │
│   └── utils.py                     # Path resolution + settings I/O
│
├── 📂 tests/                        # Pytest test suite
├── 📂 build_assets/                 # Bundled runtime (Chromium, OCR models)
├── 📂 pyinstaller_hooks/            # Custom PyInstaller hooks
│
├── main.py                          # 🚀 Application entry point
├── build.bat                        # 🔨 Windows EXE build script
├── build.py                         # 🔨 Python build script
├── uiic_automation.spec             # 📦 PyInstaller spec file
│
├── requirements.txt                 # Runtime dependencies
├── requirements-build.txt           # Build/packaging dependencies
├── pyproject.toml                   # Project metadata
└── README.md                        # 📖 This file
```

### Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                    main.py                          │
│              (App Entry Point)                      │
└───────────────────┬─────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────┐
│              UI Layer (PyQt6)                        │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ TopBar   │  │ Home     │  │ Progress Page     │  │
│  │ (Nav)    │  │ Page     │  │ (Steps + Log)     │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
└───────────────────┬─────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────┐
│            Data Layer                                │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Excel    │  │ Folder   │  │ ClaimData         │  │
│  │ Reader   │  │ Scanner  │  │ Model             │  │
│  └──────────┘  └──────────┘  └───────────────────┘  │
└───────────────────┬─────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────┐
│          Automation Layer (Playwright)               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌─────────────┐  │
│  │ Login  │ │ Nav    │ │Interim │ │ Documents   │  │
│  │+CAPTCHA│ │+Filter │ │ Report │ │ + Assess.   │  │
│  └────────┘ └────────┘ └────────┘ └─────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## 🔧 Troubleshooting

### 🔴 Playwright browser missing

```powershell
uv run playwright install chromium
```

### 🔴 OCR/CAPTCHA fails on first run

- Ensure **internet access** for the first launch (PaddleOCR downloads models automatically).
- Keep PaddlePaddle on the **2.x branch** (`<3.0.0`) — defined in `requirements.txt`.
- For packaged EXE builds, re-run `.\build.bat` to rebundle OCR models.

### 🔴 "Module not found" errors

Reset the environment completely:

```powershell
Remove-Item -Recurse -Force .venv
uv venv --python 3.10
uv pip install -r requirements.txt
uv run playwright install chromium
```

Verify:

```powershell
uv run python -c "import PyQt6,playwright,paddleocr,pandas; print('✅ OK')"
```

### 🔴 App cannot find settings or config files

- **From source:** Ensure `app/config/` folder has all three JSON files.
- **From EXE:** Bundled configs are inside the EXE. User overrides are at:
  ```
  %LOCALAPPDATA%\UIIC_Surveyor_Automation\config\
  ```
- **Factory reset:** Delete the above folder and restart the app.

### 🔴 Excel field shows as "MISS" in preview

The label in your Excel doesn't match what's in `field_mapping.json`. To debug:

```python
# Run this to find the exact label text in your Excel
import openpyxl
wb = openpyxl.load_workbook("your_file.xlsx", data_only=True)
for ws in wb.worksheets:
    for row in ws.iter_rows():
        for cell in row:
            if cell.value and "your_keyword" in str(cell.value).lower():
                print(f"Sheet: {ws.title}, Cell: {cell.coordinate}, Value: '{cell.value}'")
```

Then update the `search_label` in `app/config/field_mapping.json` to match exactly.

### 🔴 Portal layout changed

If UIIC updates their portal HTML:

1. Update CSS selectors in `app/automation/selectors.py`
2. Update label mappings in `app/config/field_mapping.json`
3. Update document types in `app/config/doc_mapping.json`

---

## 🔒 Security

| Aspect | Implementation |
|:-------|:---------------|
| 🔐 **Credentials** | Stored locally in user's AppData — never transmitted to external servers |
| 🖥️ **Processing** | All data extraction and OCR runs 100% locally on your machine |
| 🧹 **Sanitization** | All text inputs are sanitized before injection into portal fields |
| 🔑 **No External APIs** | CAPTCHA solving uses local PaddleOCR — no cloud OCR services |
| 🖐️ **Human Control** | Final submission is always manual — automation never auto-submits |

---

## 👨‍💻 Maintainer Notes

### Development Best Practices

1. **Python Version:** Use Python 3.10 for release builds. 3.11–3.12 work for development.
2. **Dependencies:** Always install from `requirements.txt` (runtime) and `requirements-build.txt` (packaging). Keep both aligned with `pyproject.toml`.
3. **Selectors:** All portal DOM selectors live in `selectors.py` — never hardcode selectors in other modules.
4. **Config vs Code:** Data mappings go in `config/*.json`. Infrastructure (selectors, automation logic) stays in Python.
5. **Testing:** Run `uv run pytest -v` before any release.

### Key Architectural Decisions

| Decision | Rationale |
|:---------|:----------|
| Label-driven Excel parsing | Works with any cell layout — surveyors use different Excel templates |
| QPainter-drawn UI icons | Unicode/emoji characters render inconsistently on Windows — painted icons are pixel-perfect everywhere |
| Copy-and-prune for Sheet 7 | Preserves all Excel formatting (merged cells, logos, styles) for compliant document uploads |
| Validation warns, doesn't block | Portal may already have pre-filled values — blocking would prevent legitimate submissions |
| Browser stays open after automation | Human final review and submit is mandatory for compliance |

---

<div align="center">

**Built with ❤️ for UIIC Surveyors**

*Automate the repetitive. Keep control of the important.*

</div>
