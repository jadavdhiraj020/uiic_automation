# 🏢 UIIC Surveyor Automation

> **Automate insurance claim submissions** on the [UIIC Surveyor Portal](https://portal.uiic.in/surveyor/) — from login to final document upload — in under 2 minutes.

![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/GUI-PyQt6-green?logo=qt)
![Playwright](https://img.shields.io/badge/Browser-Playwright-orange?logo=microsoftedge)
![Tests](https://img.shields.io/badge/Tests-93%20passed-brightgreen)

---

## 👥 For Non-Technical Users (Surveyors)

### 1. Installation
1. You will receive a ZIP file containing the application.
2. Extract the ZIP file to a folder on your computer (e.g., your Desktop).
3. Open the extracted folder `UIIC_Surveyor_Automation` and double-click the **`UIIC_Surveyor_Automation.exe`** application to run it.

### 2. How to Use
1. Place all your claim files (the Excel report and all PDF/Image documents) into a single folder for that specific claim.
2. Open the application.
3. Enter your **Portal Username** and **Password**.
4. Click the **Browse** button and select the folder containing your claim files.
5. Click **Start Automation**.
6. The application will automatically:
   - Read your Excel file.
   - Open a browser and automatically log you in (it solves the CAPTCHA for you).
   - Navigate to the specific claim.
   - Fill out the Interim Report, upload all your Documents, and fill the Claim Assessment.
7. **Important:** The browser will stay open at the end. You must manually review the filled data and click the final **Submit** button on the portal yourself.

### 3. Adjusting the Typing Speed
If you want the bot to type faster or slower to prevent the website from blocking you:
1. Open File Explorer and paste this into the address bar: `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config`
2. Open `settings.json` with Notepad.
3. Find `"browser_slow_mo_ms": 500`.
4. Change the number. `500` means a half-second delay between every click and keystroke. Change it to `200` to make it faster, or `1000` for a very slow, human-like speed.
5. Save the file and restart the application.

---

## 💻 For Developers

### 1. Prerequisites
- **Python 3.12** (required for PaddleOCR compatibility on Windows)
- **Windows 10/11**

### 2. Setup & Installation
```bash
# 1. Clone the repo
git clone https://github.com/your-username/uiic_automation.git
cd uiic_automation

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
pip install -r requirements-build.txt

# 4. Install Playwright browser
playwright install chromium
```

### 3. Running Locally
```bash
python main.py
```

### 4. Building the Standalone `.exe`
We use PyInstaller to compile the app into a standalone Windows executable. 

To build the executable, simply run the included batch script:
```bash
.\build.bat
```

This script will:
1. Bundle the Python app and its GUI.
2. Extract and bundle the Playwright Chromium browser so the end-user doesn't need to download it.
3. Extract and bundle the PaddleOCR Deep Learning models.
4. Output the final, production-ready `.exe` and its dependencies inside the `dist\UIIC_Surveyor_Automation` folder.

You can zip the `UIIC_Surveyor_Automation` folder inside `dist/` and send it to your end users!

### 5. Testing
Run the full test suite (93 unit tests covering Excel parsing, cleaning, and formatting):
```bash
python -m pytest tests/test_automation.py -v
```

---

## ✨ Key Features

| Feature | Description |
|---|---|
| 🔐 **Auto CAPTCHA Solver** | PaddleOCR-powered CAPTCHA reading (Deterministic, Fallback-free logic) |
| 📊 **Excel Data Extraction** | Position-independent label search — works with ANY Excel layout |
| 📑 **4-Tab Auto Fill** | Interim Report → Claim Documents → Claim Assessment → done |
| 📎 **Smart Document Upload** | Auto-maps files to portal categories using `doc_mapping.json` |
| 💰 **Payment Detection** | Reads Excel for REPAIRER (Cashless) or INSURED (Reimbursement) |
| 📱 **Mobile Sanitization** | Strips dashes/country codes, enforces 10-digit limit |
| 🛡️ **JS Injection Protection** | All Excel values are escaped before browser injection |
| 📋 **Full Audit Trail** | Every field logs its exact Excel source (Row/Column/Sheet) |
| 🖥️ **Modern Desktop UI** | Clean PyQt6 interface with live log, data preview, and progress |

---

## ⚙️ Configuration Overrides

### `field_mapping.json` — Excel Field Mapping
This file maps each `ClaimData` field to a label in your Excel file. The reader scans the entire sheet for the label text, then reads the value to its right.

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

## 🔒 Security Notes
- **Credentials** are stored locally in `%LOCALAPPDATA%\UIIC_Surveyor_Automation\config\settings.json` (plaintext).
- **JS Injection** is prevented — all Excel values are escaped via `_js_escape()` before browser injection.

---

<p align="center">
  <b>Built with ❤️ for Insurance Surveyors</b><br>
  <i>Automate the boring stuff. Focus on what matters.</i>
</p>
