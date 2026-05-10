# Project Overview

## Purpose

This project is a desktop automation application for motor claim surveyor portal work. It reads a selected claim folder, extracts claim data from Excel/PDF/files, previews that data in a PyQt UI, and uses Playwright to fill insurance portal forms while leaving final submission under human control.

The original production workflow is Website 1, the UIIC Surveyor portal. A newer portal layer adds New India Assurance support without replacing UIIC logic.

## Business Flow

```text
Surveyor claim folder
  -> Excel survey report
  -> scanned documents and PDFs
  -> folder scan and document classification
  -> Excel/PDF data extraction
  -> ClaimData model
  -> PyQt preview and validation
  -> Playwright browser automation
  -> manual review and final submit
```

The app automates repetitive entry only. It intentionally does not click final submit.

## Runtime Entry Points

- `main.py` configures logging, frozen PyInstaller environment, QApplication, QSS, icon, and opens `MainWindow`.
- `app/ui/main_window.py` owns portal selection, folder scanning, UI state, worker-thread lifecycle, and start/stop actions.
- `app/ui/worker.py` creates a dedicated asyncio event loop inside a `QThread` and runs `AutomationEngine`.
- `app/automation/engine.py` launches Chromium, logs in, navigates to the claim, runs portal-specific automation, and keeps the browser open for manual review.

## Main Architectural Objects

- `ClaimData`: central in-memory object passed through extraction, UI preview, validation, and automation.
- `FolderScanResult`: result of classifying folder contents into Excel, claim documents, assessment files, skipped files, and unknown files.
- `PortalInfo`: registry descriptor for each supported portal.
- `AutomationWorker`: Qt signal bridge between UI thread and async automation.
- `DocumentUploadService`: reusable upload-row lifecycle service for UIIC claim document uploads.

## Current Portal Status

| Portal | ID | Status | Main Modules |
| --- | --- | --- | --- |
| UIIC / Website 1 | `uiic` | Production baseline. Full login, navigation, interim report, claim documents, claim assessment. | `app/automation/*`, `app/portals/uiic/config/*` |
| New India | `newindia` | Partial phased implementation. Login and navigation exist. Phase 3 Quick Update imports successfully but still needs live DOM validation. Later sections are not implemented. | `app/portals/newindia/automation/*`, `app/portals/newindia/config/*` |

## Core Safety Principles

- UIIC behavior must remain backward compatible.
- Portal-specific behavior must be isolated under `app/portals/<portal_id>/`.
- Shared helpers may be changed only when both UIIC and New India impacts are understood.
- Excel data is source of truth where possible. Avoid inventing claim values.
- Amount `"0"` is valid and must not be skipped as falsy.
- Browser stays open after automation so a human reviews and submits.

## High-Level File Map

```text
app/
  automation/              Shared/UIIC automation modules
    engine.py              Main orchestrator
    login_module.py        UIIC login and OCR CAPTCHA
    navigation_module.py   UIIC worklist navigation
    interim_report.py      UIIC interim tab fill
    claim_documents.py     UIIC claim documents workflow
    claim_assessment.py    UIIC claim assessment workflow
    form_helpers.py        Shared Playwright field helpers
    selectors.py           UIIC selector registry
    services/              Upload service
  data/
    data_model.py          ClaimData model, validation, preview rows
    excel_reader.py        Label-driven Excel extraction
    folder_scanner.py      Folder and document classification
  portals/
    registry.py            Active portal and config path routing
    uiic/config/           UIIC portal configs
    newindia/              New India configs and portal-specific modules
  ui/
    main_window.py         Main PyQt shell
    worker.py              QThread/asyncio bridge
    components/            Home, progress, settings widgets
    services/              Folder service, log formatting
```

## What Future AI Should Read First

1. `docs/AI_WORKFLOW_RULES.md`
2. `docs/ARCHITECTURE.md`
3. `docs/CLAIMDATA_MODEL.md`
4. `docs/EXTRACTION_PIPELINE.md`
5. Portal-specific docs for the target work.
