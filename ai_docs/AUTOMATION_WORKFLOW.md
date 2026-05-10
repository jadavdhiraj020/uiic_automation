# Automation Workflow

## Purpose

This document explains how the Playwright automation run is started, how each portal branches, and how the browser lifecycle works.

## Worker and Engine Lifecycle

```text
MainWindow._start_automation()
  -> validate ClaimData
  -> create AutomationWorker(claim, settings, portal_id)
  -> move worker to QThread
  -> thread.started -> worker.run()
  -> worker creates new asyncio event loop
  -> AutomationEngine.run()
  -> signals emit logs/steps/done back to UI
```

The worker isolates async Playwright work from the Qt UI thread. UI updates happen through Qt signals, not direct calls from the automation coroutine.

## Engine Setup

Module: `app/automation/engine.py`

`AutomationEngine.run()`:

1. Loads settings through `load_settings()`.
2. Applies runtime overrides from the UI.
3. Launches Chromium with:
   - `headless` from settings
   - `slow_mo` from settings
   - maximized window args
   - `no_viewport=True`
   - `accept_downloads=True`
4. Creates one initial page.
5. Registers dialog auto-accept handling.
6. Captures newly opened pages through `context.on("page", ...)`.

## UIIC Flow

```text
STEP 1 Login
  app/automation/login_module.py
  -> open portal_url
  -> OCR CAPTCHA from canvas
  -> fill credentials and captcha
  -> click login
  -> confirm dashboard/session

STEP 2 Navigate to Claim
  app/automation/navigation_module.py
  -> Worklist
  -> claim type
  -> claim number
  -> Filter
  -> find row
  -> click Action
  -> detect new tab or same page

STEP 3 Interim Report
  app/automation/interim_report.py

STEP 4 Claim Documents
  app/automation/claim_documents.py

STEP 5 Claim Assessment
  app/automation/claim_assessment.py

Manual review
  browser remains open until Stop or manual browser close
```

## New India Flow

Current implemented flow:

```text
STEP 1 Login
  app/portals/newindia/automation/login_module.py
  -> open login page
  -> fill username/password
  -> user manually solves CAPTCHA and clicks login
  -> success detected by URL change

STEP 2 Navigate to Claim
  app/portals/newindia/automation/navigation_module.py
  -> Worklist nav
  -> select "Claim No."
  -> type claim number
  -> click Filter
  -> click edit icon

STEP 3 Quick Update Details
  app/portals/newindia/automation/quick_update_module.py

STEP 4 Vehicle Photo
  app/portals/newindia/automation/vehicle_photo_module.py

STEP 5 Registration Certificate
  app/portals/newindia/automation/registration_cert_module.py

STEP 6 Driver Details
  app/portals/newindia/automation/driver_details_module.py

STEP 7 FIR Details
  app/portals/newindia/automation/fir_details_module.py

STEP 8 NEFT Details
  app/portals/newindia/automation/neft_module.py

STEP 9 Work Approval
  app/portals/newindia/automation/work_approval_module.py

STEP 10 Claim Assessment
  app/portals/newindia/automation/claim_assessment_module.py
```

All 10 phases are now fully implemented and stable. The bot automatically pauses at the end of Phase 10 for manual review before final submission.

## Stop Behavior

`MainWindow._stop_automation()` calls `AutomationWorker.stop()`, which calls `AutomationEngine.request_stop()`. The engine checks `_stop_requested` between major actions and in manual review loops.

Stop is cooperative, not an immediate browser kill. This avoids leaving portal state half-mutated during sensitive actions.

## Manual Review Contract

After a successful UIIC run:

- Engine sets step to complete.
- Browser is left open.
- User reviews portal tabs manually.
- User clicks final submit manually.
- User clicks Stop or closes browser when done.

This is a business safety boundary. Do not automate final submit without explicit approval and a separate safety design.

## Dialog Handling

UIIC:

- Engine registers a general dialog auto-accept handler.
- Login module also accepts portal dialogs.
- Claim document upload registers upload-specific dialog handling.
- Upload service actively closes modals/popups and presses Escape.

This is necessary because UIIC can show size alerts, modal confirmations, or blocking feedback/maintenance dialogs.

## Step/Progress Mapping

The progress UI has six visual states:

1. Login
2. Navigate to Claim
3. Interim Report
4. Claim Documents
5. Claim Assessment
6. Complete

Engine steps list has five named execution steps, then emits index `5` for complete.
