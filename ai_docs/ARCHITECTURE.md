# Architecture

## Scope

This document explains how the application is layered, how modules depend on one another, and where future changes should be made safely.

## Layer Diagram

```text
PyQt application shell
  main.py
  app/ui/main_window.py
  app/ui/components/*
          |
          v
Folder processing and preview
  app/ui/services/claim_folder_service.py
  app/data/folder_scanner.py
  app/data/excel_reader.py
  app/data/data_model.py
          |
          v
Portal-aware settings and mappings
  app/utils.py
  app/portals/registry.py
  app/config/*
  app/portals/<portal>/config/*
          |
          v
Automation worker boundary
  app/ui/worker.py
  QThread + asyncio event loop
          |
          v
Playwright automation
  app/automation/engine.py
  app/automation/* shared/UIIC modules
  app/portals/newindia/automation/*
```

## Dependency Direction

The intended dependency direction is:

```text
UI -> services -> data/config -> automation
```

Important exceptions:

- `ClaimData` lazily imports the portal registry to make validation and preview portal-aware.
- `utils.py` lazily imports the portal registry to route settings/mapping paths.
- `AutomationEngine` imports portal-specific login/navigation modules dynamically inside `run()`.

These lazy imports are deliberate circular-dependency avoidance mechanisms.

## Portal-Aware Architecture

Portal awareness is implemented with a global active portal ID in `app/portals/registry.py`.

```text
MainWindow portal dropdown
  -> set_active_portal(portal_id)
  -> utils.load_settings/load_field_mapping/load_doc_mapping
  -> registry portal_*_paths()
  -> app/portals/<portal_id>/config/*.json plus AppData override
```

If no portal is selected, registry path helpers fall back to legacy `app/config/`. `MainWindow` sets `uiic` on startup for compatibility, so normal UI use is portal-aware.

## Shared vs Portal-Specific Logic

### Shared or UIIC-Baseline

- `app/automation/form_helpers.py`
- `app/automation/engine.py`
- `app/automation/services/document_upload_service.py`
- `app/data/*`
- `app/ui/*`

### UIIC Website 1

- `app/automation/login_module.py`
- `app/automation/navigation_module.py`
- `app/automation/interim_report.py`
- `app/automation/claim_documents.py`
- `app/automation/claim_assessment.py`
- `app/automation/selectors.py`
- `app/portals/uiic/config/*`

### New India

- `app/portals/newindia/automation/login_module.py`
- `app/portals/newindia/automation/navigation_module.py`
- `app/portals/newindia/automation/quick_update_module.py`
- `app/portals/newindia/config/*`

## Orchestration Flow

```text
User selects folder
  MainWindow._scan_folder()
    ClaimFolderService.process_folder()
      scan_folder()
      extract_claim_data()
      _extract_pdf_invoice_data()
      attach document paths to ClaimData
    HomePage.update_data()

User clicks Start Automation
  MainWindow._start_automation()
    claim.validate()
    AutomationWorker in QThread
      AutomationEngine.run()
        Playwright launch
        portal-specific login
        portal-specific navigation
        portal-specific fill steps
        manual review wait loop
```

## Implementation Conventions

- Field values live on `ClaimData`, not in loose dictionaries during automation.
- Excel source coordinates are stored in `claim._excel_coords`.
- Preview rows come from `ClaimData.all_fields_for_preview()`.
- User-facing extraction logs are stored in `claim._excel_logs`.
- Portal config is JSON-driven: `settings.json`, `field_mapping.json`, `doc_mapping.json`.
- UIIC selectors should be centralized in `app/automation/selectors.py`.
- New portal selectors should stay under that portal package unless promoted deliberately.

## Architectural Warnings

- `app/automation/engine.py` still imports UIIC fill steps at module import time. That is okay for current behavior, but future portals should avoid adding more top-level portal imports there.
- `ClaimData` contains fields for all portals. This is convenient but can grow into a large shared object. Additive fields are safer than changing existing UIIC fields.
- `utils.load_doc_mapping()` returns user mapping wholesale if it exists, unlike field mapping which deep-merges defaults. Old user doc mappings can hide newly added default keys.
- Settings JSON files currently contain credentials. Treat them as sensitive.

## Safe Extension Points

- Add a new portal descriptor in `app/portals/registry.py`.
- Add config files under `app/portals/<portal_id>/config/`.
- Add portal-specific automation under `app/portals/<portal_id>/automation/`.
- Branch inside `AutomationEngine.run()` by portal ID only at step boundaries.
- Add portal-specific preview/validation methods in `ClaimData`.

