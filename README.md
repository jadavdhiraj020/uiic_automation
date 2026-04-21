<div align="center">
  
# 🏢 UIIC Surveyor Automation 🚀

**An enterprise-grade, zero-click automation suite for UIIC Insurance Surveyors.**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](#)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green?logo=qt)](#)
[![Playwright](https://img.shields.io/badge/Browser-Playwright-orange?logo=microsoftedge)](#)
[![PaddleOCR](https://img.shields.io/badge/AI-PaddleOCR-red?logo=paddlepaddle)](#)

*Automate claim submissions on the [UIIC Surveyor Portal](https://portal.uiic.in/surveyor/) — from auto-solving CAPTCHAs to final document uploads — in under 2 minutes.*

</div>

<br>

---

## ✨ Why This Exists
Manually filling out insurance claims on the UIIC Surveyor Portal takes time and is prone to human error. This application reads your Excel survey reports, solves the portal's login CAPTCHA using deep learning, and automatically fills out all complex web forms identically to how a human would (but flawlessly and much faster).

<br>

---

## 👥 For Surveyors (Non-Technical Users)

### 1️⃣ Installation & Setup

1. **Download** the provided ZIP file containing the compiled `.exe` application.
   <br>
2. **Extract** the ZIP file to a safe location on your computer (e.g., your Desktop).
   <br>
3. Open the extracted `UIIC_Surveyor_Automation` folder.
   <br>
4. Double-click the **`UIIC_Surveyor_Automation.exe`** application icon to launch it.

<br>

### 2️⃣ Setting Up Your Claim Folder

Before starting the bot, you must place all files for a single claim into **one single folder**.

```text
📁 Your_Claim_Folder/
│
├── 📊 new_sample.xlsx                    ← Your Surveyor Report (Excel file)
│
├── 📄 Discharge_Voucher.pdf              ← Claim Documents
├── 📄 Driving_License.pdf
├── 📄 Registration_Certificate.pdf
│
├── 📄 Final_Invoice.pdf                  ← Assessment Documents
├── 📄 Survey_Report.pdf
│
└── 📄 other-Payment_Receipt.pdf          ← Extra docs (auto-numbered)
```

<br>

### 3️⃣ Running the Automation (Step-by-Step)

1. **Open** the application window.
   <br>
2. **Enter Credentials:** Type your UIIC Portal Username and Password into the top boxes.
   <br>
3. **Select Folder:** Click the **Browse** button and select the folder you organized in the step above.
   <br>
4. **Start:** Click **Start Automation**.

**What the bot will do automatically:**
* **Login:** Solves the CAPTCHA image and securely logs into the portal.
* **Navigate:** Finds your specific claim number in your worklist.
* **Interim Report:** Fills out survey dates, locations, and your observations.
* **Documents:** Uploads all your PDFs and images to the correct UIIC portal categories.
* **Assessment:** Calculates and fills out parts depreciation, labour charges, towing fees, and surveyor fees.

> ⚠️ **CRITICAL STEP:** The bot will intentionally stop and leave the browser open at the very end. You must manually review the filled data and click the final **Submit** button on the portal yourself!

<br>

### ⚙️ Adjusting the Typing Speed (Humanizer)

To prevent the website from blocking the bot, it is programmed to type at a human speed. You can easily make it faster or slower:

1. Open **File Explorer** and paste this into the address bar at the top:
   `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config`
   <br>
2. Open the `settings.json` file in Notepad.
   <br>
3. Find the line that says `"browser_slow_mo_ms": 500`.
   * Change `500` to `200` to make it type **faster**.
   * Change `500` to `1000` to make it type **very slowly** (1 full second between actions).
   <br>
4. Save the file (Ctrl+S) and restart the application.

<br>

---

## 📊 Excel Formatting Requirements

Your Excel file (`.xls` or `.xlsx`) can be designed however you like! The bot scans the entire sheet for specific text labels, meaning **no fixed row/column positions are required**. 

As long as the following text labels exist somewhere in your sheet, the bot will find the value directly next to them:

### Claim Details & Observations
| Label to write in Excel | What it fills on the Portal |
| :--- | :--- |
| `Claim no` | Claim Number |
| `Date and Time of Survey` | Survey Date + Time |
| `Workshop` | Place of Survey |
| `Mobile:` | Mobile Number *(auto-sanitized to 10 digits)* |
| `e-mail:-` | Email Address |
| `OBERVATIONS/COMMENTS` | Surveyor Observation |
| `PAYMENT MADE IN THE FAVOUR OF` | Payment Option *(REPAIRER or INSURED)* |

### Claim Assessment & Financials
| Label to write in Excel | What it fills on the Portal |
| :--- | :--- |
| `NET PAYABLE` | Initial Loss Amount |
| `SUB TOTAL` | Parts Depreciation *(Metal/Plastic/Glass columns)* |
| `LABOUR ESTIMATED` | Labour Charges |
| `TOWING CHARGES` | Towing Charges |
| `LESS SALVAGE VALUE` | Salvage Value |

### Surveyor Fees
| Label to write in Excel | What it fills on the Portal |
| :--- | :--- |
| `CONVEYANCE CHARGES` | Traveling Expenses |
| `PROFESSIONAL FEE` | Professional Fee |
| `DAILY ALLOWANCE` | Daily Allowance |
| `PHOTOGRAPHS` | Photo Charges |
| `Ref:` | Final Report Number |

<br>

---

## 💻 For Developers

### 🛠️ Prerequisites
* **Python 3.12** *(Required for PaddleOCR compatibility on Windows)*
* **Windows 10/11**

<br>

### 📦 Setup & Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/uiic_automation.git
cd uiic_automation

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install all dependencies
pip install -r requirements.txt
pip install -r requirements-build.txt

# 4. Install Playwright browser
playwright install chromium
```

<br>

### ▶️ Running Locally

```bash
python main.py
```

<br>

### 🏗️ Building the Standalone `.exe`

We use PyInstaller to compile the application into a standalone Windows executable. 

To build the executable, simply run the included batch script:

```bash
.\build.bat
```

This script will bundle the Python app, the Playwright Chromium browser, and the PaddleOCR deep-learning models into a single portable folder. The final production-ready output will be located in `dist\UIIC_Surveyor_Automation`.

<br>

### 🧪 Testing

Run the full suite of 93 unit tests covering Excel parsing, cleaning, and formatting:

```bash
python -m pytest tests/test_automation.py -v
```

<br>

---

## 🏗️ Architecture & Core Modules

| Module | Description |
| :--- | :--- |
| `captcha_solver.py` | Uses a local, bundled PaddleOCR model to instantly extract text from the portal's login canvas. Uses deterministic logic with zero external API calls. |
| `engine.py` | The master orchestrator. Uses `asyncio` and `playwright` to seamlessly move through the UIIC portal tabs. |
| `excel_reader.py` | A robust pandas-based parser that scans all sheets for label coordinates rather than relying on hardcoded cell positions. |
| `login_module.py` | Handles portal navigation, dialog boxes, and login form submission securely. |

<br>

---

## 🔒 Security & Privacy Notes

* **Local Only:** This application runs entirely on your local machine. No claim data, documents, or credentials are ever sent to a third-party server.
* **Credentials:** Passwords are stored purely on your local hard drive in `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config\settings.json`.
* **JS Injection Protection:** All data extracted from Excel is strictly sanitized and escaped before being injected into the Playwright browser to prevent cross-site scripting (XSS) errors on the portal.

<br>

---

<div align="center">
  <b>Built with ❤️ for Insurance Surveyors</b><br>
  <i>Automate the boring stuff. Focus on what matters.</i>
</div>
