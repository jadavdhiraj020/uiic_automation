# 🏢 UIIC Surveyor Automation

> **Automate insurance claim submissions** on the [UIIC Surveyor Portal](https://portal.uiic.in/surveyor/) — from login to final document upload — in under 2 minutes.

![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green?logo=qt)
![Playwright](https://img.shields.io/badge/Browser-Playwright-orange?logo=microsoftedge)
![Tests](https://img.shields.io/badge/Tests-93%20passed-brightgreen)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔐 **Auto CAPTCHA Solver** | PaddleOCR-powered CAPTCHA reading with multi-case candidate generation |
| 📊 **Excel Data Extraction** | Position-independent label search — works with ANY Excel layout |
| 📑 **4-Tab Auto Fill** | Interim Report → Claim Documents → Claim Assessment → done |
| 📎 **Smart Document Upload** | Auto-maps files to portal categories using `doc_mapping.json` |
| 💰 **Payment Detection** | Reads Excel for REPAIRER (Cashless) or INSURED (Reimbursement) |
| 📱 **Mobile Sanitization** | Strips dashes/country codes, enforces 10-digit limit |
| 🛡️ **JS Injection Protection** | All Excel values are escaped before browser injection |
| 📋 **Full Audit Trail** | Every field logs its exact Excel source (Row/Column/Sheet) |
| 🖥️ **Modern Desktop UI** | Clean PyQt6 interface with live log, data preview, and progress |
| 🧪 **93 Unit Tests** | Comprehensive test suite covering all modules |

---

## 📸 How It Works

```
📁 Your Claim Folder
├── new_sample.xlsx          ← Surveyor report (Excel)
├── Discharge_Voucher.pdf    ← Claim documents
├── Driving_License.pdf
├── Registration_Certificate.pdf
├── Final_Invoice.pdf        ← Assessment documents
├── Survey_Report.pdf
└── ...
```

**One click** → the automation:

1. **Logs in** to the UIIC portal (solves CAPTCHA automatically)
2. **Navigates** to the correct claim in the worklist
3. **Fills Interim Report** — survey date, place, mobile, observation, etc.
4. **Uploads Documents** — maps files to correct portal categories
5. **Fills Claim Assessment** — parts depreciation, labour, charges, report no.
6. **Leaves browser open** for your manual review before final submit

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.12** (required for PaddleOCR compatibility)
- **Windows 10/11** (tested on Windows)

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/your-username/uiic_automation.git
cd uiic_automation

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install Playwright browser
playwright install chromium
```

### Run

```bash
python main.py
```

This launches the desktop GUI. Enter your portal credentials, select your claim folder, and click **Start Automation**.

---

## 📁 Project Structure

```
uiic_automation/
├── main.py                          # Entry point — launches the GUI
├── requirements.txt                 # Python dependencies
├── pyproject.toml                   # Project metadata & build config
│
├── app/
│   ├── config/
│   │   ├── field_mapping.json       # Excel label → ClaimData field mapping
│   │   ├── doc_mapping.json         # Filename patterns → portal doc categories
│   │   └── settings.json            # Saved credentials (local only)
│   │
│   ├── data/
│   │   ├── data_model.py            # ClaimData dataclass — single source of truth
│   │   ├── excel_reader.py          # Position-independent Excel parser
│   │   └── folder_scanner.py        # Scans claim folder for Excel + documents
│   │
│   ├── automation/
│   │   ├── engine.py                # Main orchestrator — runs all 5 steps
│   │   ├── login_module.py          # Portal login + CAPTCHA handling
│   │   ├── captcha_solver.py        # PaddleOCR CAPTCHA reader (lazy-loaded)
│   │   ├── navigation_module.py     # Worklist search + claim navigation
│   │   ├── interim_report.py        # Fills the Interim Report tab
│   │   ├── claim_documents.py       # Uploads documents + sets payment option
│   │   ├── claim_assessment.py      # Fills parts, labour, charges, report
│   │   ├── form_helpers.py          # Low-level fill/select/upload helpers
│   │   ├── selectors.py             # All CSS/ID selectors for portal elements
│   │   └── tab_utils.py             # Tab clicking utility
│   │
│   └── ui/
│       ├── main_window.py           # PyQt6 main window + extracted data preview
│       ├── worker.py                # Background thread for automation
│       └── components/
│           └── widgets.py           # Reusable UI components
│
├── tests/
│   └── test_automation.py           # 93 unit tests
│
└── logs/
    └── automation.log               # Real-time log output (auto-rotated)
```

---

## ⚙️ Configuration

### `field_mapping.json` — Excel Field Mapping

This file maps each `ClaimData` field to a label in your Excel file. The reader scans the entire sheet for the label text, then reads the value to its right.

```json
{
  "claim_no":    { "sheet": "ALL",    "search_label": "Claim no",    "row_offset": 0, "col_offset": 1 },
  "mobile_no":   { "sheet": "Sheet1", "search_label": "Mobile:",     "row_offset": 0, "col_offset": 1 },
  "labour_excl_gst": { "sheet": "Sheet1", "search_label": "LABOUR ESTIMATED", "row_offset": 0, "col_offset": 7 }
}
```

| Key | Description |
|---|---|
| `sheet` | `"Sheet1"`, `"Sheet5"`, or `"ALL"` (scan every sheet) |
| `search_label` | Text to find in the Excel cell |
| `row_offset` | Rows below the label to read (0 = same row) |
| `col_offset` | Columns right of the label (hint — auto-scans if wrong) |

### `doc_mapping.json` — Document File Mapping

Maps filename patterns to portal document categories:

```json
{
  "Discharge_Voucher": "Discharge or Satisfaction Voucher",
  "Driving_License": "Driving License",
  "Registration_Certificate": "RC Book"
}
```

Files prefixed with `other-` or `other_` are automatically uploaded as "Other 1", "Other 2", etc.

---

## 📊 Excel Format Requirements

Your Excel file (`.xls` or `.xlsx`) should contain these labels somewhere in the sheets. The reader finds them automatically — **no fixed row/column positions required**.

### Sheet1 — Claim Details
| Label in Excel | Portal Field |
|---|---|
| `Claim no` | Claim Number |
| `Date and Time of Survey` | Survey Date + Time |
| `Workshop` | Place of Survey |
| `Mobile:` | Mobile Number (sanitized to 10 digits) |
| `e-mail:-` | Email Address |
| `OBERVATIONS/COMMENTS` | Surveyor Observation |
| `NET PAYABLE` | Initial Loss Amount |
| `SUB TOTAL` | Parts Depreciation (Metal/Plastic/Glass columns) |
| `LABOUR ESTIMATED` | Labour Charges |
| `TOWING CHARGES` | Towing Charges |
| `LESS SALVAGE VALUE` | Salvage Value |
| `PAYMENT MADE IN THE FAVOUR OF` | Payment Option (REPAIRER/INSURED) |

### Sheet5 — Surveyor Fee
| Label in Excel | Portal Field |
|---|---|
| `CONVEYANCE CHARGES` | Traveling Expenses |
| `PROFESSIONAL FEE` | Professional Fee |
| `DAILY ALLOWANCE` | Daily Allowance |
| `PHOTOGRAPHS` | Photo Charges |
| `Ref:` | Final Report Number |

---

## 📎 Claim Folder Setup

Place all files for one claim in a single folder:

```
📁 automationfolderuploading/
│
├── 📊 new_sample.xlsx                    ← Required: Excel report
│
├── 📄 Discharge_Voucher.pdf              ← Claim Documents
├── 📄 Driving_License.pdf
├── 📄 Fitness_Certificate.jpeg
├── 📄 PAN_Card.jpg
├── 📄 Registration_Certificate.pdf
├── 📄 Route_Permit.pdf
├── 📄 cancel_check.jpeg
│
├── 📄 Final_Invoice.pdf                  ← Assessment Documents
├── 📄 Repair_Estimate.pdf
├── 📄 Spot_report.pdf
├── 📄 Survey_Report.pdf
├── 📄 assessment.pdf
│
├── 📄 other-Partnership_Deed.pdf         ← Extra docs (auto-numbered)
├── 📄 other-Payment_Receipt.pdf
└── 📄 other_Tax_Report.jpeg
```

---

## 🧪 Testing

Run the full test suite:

```bash
python -m pytest tests/test_automation.py -v
```

**93 tests** covering:

| Category | Tests | What's Tested |
|---|---|---|
| Excel Reader | 24 | Junk detection, value cleaning, date formatting, word boundary, whitespace normalization |
| Data Model | 9 | Field defaults, preview table, payment option display |
| Form Helpers | 16 | JS escaping, text sanitization, amount rounding |
| Mobile Cleaning | 7 | 10-digit enforcement, dash/space/country code stripping |
| Surveyor Charges | 4 | Total calculation (sum of 4 fields) |
| Payment Logic | 5 | REPAIRER→Cashless, INSURED→Reimbursement |
| Config Integrity | 12 | field_mapping.json, selectors, doc_mapping validation |
| Date Calculation | 3 | Expected completion date (+10 days) |

---

## 🔒 Security Notes

- **Credentials** are stored locally in `app/config/settings.json` (plaintext). Do not commit this file.
- **JS Injection** is prevented — all Excel values are escaped via `_js_escape()` before browser injection.
- **`.gitignore`** excludes `settings.json`, logs, and virtual environments.

---

## 📋 Automation Log

Every run produces a detailed log in `logs/automation.log`:

```
[20:42:51]   📊 claim_no: '2012013126C050003001' (Source: R181C4 (Sheet1))
[20:42:51]   📊 parts_age_dep_excl_gst: '1989' (Source: R111C7 (Sheet1))
[20:42:51]   📊 payment_to: 'INSURED' (Source: R159C3 (Sheet1))
...
[20:44:45]   ✅ [Filled] Mobile No : '9876135253' (Source: R4C9 (Sheet1))
[20:44:51]   ✅ Payment: Reimbursement (Source: R159C3 (Sheet1))
[20:45:08]   ✅ [Filled] Age Dep (Metal) : '1989' (Source: R111C7 (Sheet1))
```

Every field includes its **exact Excel source** (Row/Column/Sheet) for full audit traceability.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Run tests (`python -m pytest tests/ -v`)
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

---

## 📄 License

This project is for **authorized UIIC surveyors** only. Use responsibly and in compliance with UIIC portal terms of service.

---

<p align="center">
  <b>Built with ❤️ for Insurance Surveyors</b><br>
  <i>Automate the boring stuff. Focus on what matters.</i>
</p>
