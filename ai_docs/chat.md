# 📋 PROJECT CONTEXT HAND-OFF: UIIC / NEW INDIA AUTOMATION

## 🎯 Project Overview
An automated form-filling desktop application built with Python (PyQt for GUI, Playwright for browser automation) designed to extract data from local Claim folders (Excel sheets, PDFs, Images) and autonomously fill out Surveyor claims on two strictly isolated insurance portals:

*   **Website 1:** UIIC (United India) - Legacy, stable.
*   **Website 2:** New India Assurance - Newly implemented and hardened.

## 🏗️ Core Architectural Principles
1.  **Strict Portal Isolation:** UIIC and New India workflows are 100% decoupled. They use independent JSON mappings (`doc_mapping.json`, `field_mapping.json`), independent Python automation modules (`app/portals/<portal_id>/automation`), and branch entirely at the Playwright Engine level. Updating one will never break the other.
2.  **Single Source of Truth (SSOT):** Automation modules **do not** make logical state decisions. All core logic (e.g., determining if a claim is Cashless vs Non-Cashless based on the presence of a "cancelled cheque" file) is calculated exactly *once* during folder extraction by `claim_folder_service.py`. This state is locked into the `ClaimData` object (e.g., `claim.bank_payment_to = "Insured"`) ensuring the UI Preview and the Bot always agree.
3.  **Unified PDF Extraction:** Invoice Dates and Numbers are extracted from uploaded PDFs via `pdfplumber`/OCR regex in `claim_folder_service.py`. To maintain isolation, successful extraction populates *both* `workshop_invoice_no` (UIIC) and `vendor_invoice_number` (New India) as separate variables.

## 🚀 New India (Website 2) - Current Implementation State
The New India workflow has just been structurally hardened and completed through **Phase 10**. The bot automatically and stably executes:

1.  **Login** (Manual CAPTCHA bypass).
2.  **Navigate** (Searches Worklist and clicks edit).
3.  **Quick Update Details**.
4.  **Vehicle Photo**.
5.  **Registration Certificate** (Includes handling a specific `Reference No.` alert popup and utilizing precise Angular model fallback selectors).
6.  **Driver Details**.
7.  **FIR Details**.
8.  **NEFT Details** (Relies entirely on the SSOT `bank_payment_to` decision).
9.  **Work Approval** (Includes logic to sanitize time strings strictly to `HH:MM`, bypasses duplicate file issues, and auto-clicks the "Next" button to ensure HTTP transition safety).
10. **Claim Assessment** (Handles entry alert popups, hardcodes "Yes" for NIA Name, safely ignores disabled/Readonly GST fields to prevent Playwright crashes, and automatically fills the dynamically extracted Vendor Invoice Number & Date).

At the end of Phase 10, the engine intentionally drops into a **Manual Review Pause Loop** leaving the browser open for the user to review all 10 tabs and click final submit.

## 📂 Key Files Roadmap
*   **`app/ui/services/claim_folder_service.py`**: The extraction brain. Scans folders, parses PDFs, calculates SSOT variables.
*   **`app/data/data_model.py`**: Contains `ClaimData`, the master class for all portal variables and the `_preview_newindia()` UI table logic.
*   **`app/automation/engine.py`**: The Playwright runner. Controls the overarching loop and explicitly branches UIIC vs New India logic.
*   **`app/portals/newindia/automation/*`**: Contains all 10 modular step scripts for New India.
*   **`ai_docs/*.md`**: Highly detailed, up-to-date documentation on the entire project architecture and rules.

## 🚧 Next Immediate Steps / Pending Items
*   **New India Document Upload:** While data entry (Phases 1-10) is fully automated, the actual physical attachment of files (Document Upload module) for New India is currently bypassed/not implemented. This is the next logical major feature to tackle.
