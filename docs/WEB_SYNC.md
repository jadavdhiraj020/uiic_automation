# App-3 Web Queue

App-3 communicates directly with the authenticated Base44 functions for app
`6a906023a09ef23a2e1dfcaf`. It never opens the Base44 website. Manual Browse Folder
still calls the existing `MainWindow._scan_folder(folder)` method unchanged.

## Test one Base44 case end-to-end

1. Run App-3 using the existing development or executable startup method. In
   App-2, queue **one test case** containing its insurer, `surveyor_profile_id`,
   the latest corrected Excel, and the required documents/photos. Use actual
   accessible test records: the contract's `case_dummy_001` identifiers are examples.
2. Open **Web Queue** in App-3. On the first run, enter the operator's Base44
   email/password and click **Connect**. A successful login is saved with Windows
   DPAPI. Later startups automatically obtain a fresh access token and load the
   queue. Access tokens remain in process memory and are never saved.
3. Select the queued case. Its profile ID and insurer populate the local
   credential editor. Enter that surveyor's insurer username/password and any
   surveyor code, then click **Save Local Credentials**. Repeat this setup for
   each surveyor/insurer pair you intend to use.
4. With Auto Pickup off, select the case and use **Download / Restage** (or click
   the incoming row) to stage it. App-3 fetches the manifest and downloads every
   file as binary without claiming the case. Select the Ready row to pass its flat
   folder to the existing scanner and open Workspace.

Optional **AUTO PICKUP** is OFF by default and remembers its last setting. When ON,
App-3 stages all incoming jobs into independent folders, with at most two downloads
running together. Staging does not require portal credentials, does not claim the
case, and does not open or replace Workspace. A failed download affects only that
case. Other cases may continue downloading while an insurer automation is active.
5. Select any Ready case, review the extracted data/documents, and click the existing
   **Start Automation**. At this point App-3 validates the insurer and the matching
   local surveyor credentials, then calls `claimAutomationCase`. A confirmed claim
   starts the existing automation; a 409 marks the case Claimed Elsewhere and does
   not open an insurer browser. The matching local credentials override the login
   settings for this run only.
   CAPTCHA, document uploads and the existing insurer workflow continue normally.
6. Perform the usual human review and click the insurer's **Final Submit**.
   Verify that a validation message such as `DL verification pending` is saved
   exactly and does **not** mark the Base44 case uploaded. Correct the issue in
   the still-open browser and click Final Submit again.
7. On a recognized successful submission message, inspect the local
   `Portal_Submission_Result.json` and timestamped result files. App-3 reports
   `status: "success"`; Base44 should acknowledge `status: "uploaded"`.
   `Web_Sync_Report_Acknowledgement.json` records that acknowledgement.
8. Stop/close the previous browser before starting another queued case. If the
   case cannot presently be completed, use **Stop / Fail Current Case** in Web
   Queue and enter the reason. Only that deliberate action sends `status: "failed"`.

The ordinary Workspace Stop button or browser closure alone does not imply a
successful submission and does not silently fail the web case. While one case is
active or unresolved, all other staged cases remain visible and downloads may
continue, but they cannot replace Workspace or start insurer automation.

## Local storage and surveyor isolation

The root is `%LOCALAPPDATA%\UIIC_Surveyor_Automation\web_sync`.

- `portal_credentials.dpapi`: Windows DPAPI encrypted JSON, indexed first by
  `surveyor_profile_id`, then `uiic`, `newindia`, or `oic`. It contains username,
  password and surveyor code. Only the same Windows user can normally decrypt it.
  There is no plaintext fallback and no automatic import from legacy settings.
- `active_case.json`: the one active insurer automation case and any pending result
  report. This contains
  no insurer passwords or Base44 token.
- `state\<case-hash>.json`: one atomic local status record for each incoming/staged
  case. These records restore the Ready inbox after restart.
- `cases\<case-ref>__<vehicle>__<case-hash>`: one stable flat working folder per
  case. Downloads first use a separate temporary staging folder; only a complete,
  validated download replaces the final Ready folder.

Existing App-3 login settings were per insurer, with username/password stored in
JSON. The current portal login implementations consume username/password and have
no separate surveyor-code input. Web Queue stores the optional code and includes
it in the run's settings override without adding or changing portal selectors.
  Legacy manual settings remain unchanged; saving a Web Queue profile does not
  copy secrets into those JSON files.
- `operator_credentials.dpapi`: the DocWriter/Base44 operator email and password,
  encrypted for the current Windows user. Use **Settings → Change Login** to replace
  it after a successful connection, or **Forget Login** to remove it. Neither action
  changes surveyor credentials or the current case.

Insurer mappings: United India / United India Insurance → `uiic`; New India /
New India Assurance / New India Insurance → `newindia`; Oriental / Oriental
Insurance → `oic`. Unknown insurers or missing credentials block starting a case.

Files use safe flat basenames. Duplicate names receive a stable suffix instead
of overwriting one another. `X-Case-File-Path` is URL-decoded for provenance, never
used as a local directory path. `web_sync_manifest.json` records the mapping.
The marked corrected workbook receives a neutral unique filename. A context-local
main-Excel keyword override applies only inside that scan worker, so older Excel
files cannot replace it and saved manual mappings do not change.

## Submission evidence and recovery

The observer is installed before insurer page scripts and watches trusted clicks
labelled Final Submit, Submit Final, Submit Final Report, or Final Submission.
It observes native alert/confirm messages and visible DOM dialogs, including the
existing Angular, SweetAlert, PrimeNG and GWT dialog patterns. The attempt persists
across navigation and popup pages. Small hooks flush capture before existing popup
dismissal code. No submission clicks are automated.

Full text, UTC time, case ID and classification are saved before reporting.
Screenshots are attempted with a bounded timeout; native dialogs can prevent a
screenshot. Both the latest JSON result and timestamped history remain in the case
folder. A confirmation question, an intermediate Save/Upload message, or a
validation error never qualifies as final success. Unrecognized wording stays
unresolved rather than guessing. The browser remains available for corrections.
The current implementation does not extract a separate confirmation number.

The per-case journals and active-case journal survive restart. Automatic login
reconnects and refreshes the queue. A confirmed result waiting for Base44 acknowledgement
retries every 30 seconds and blocks another case. Reports use only `success` or
`failed` as input statuses; they never send `uploaded`. A request receiving 401
gets one re-login and one retry, including binary downloads.

If claiming fails without confirmation, App-3 does not open a browser and keeps the
local case ready for attention. An explicit 409 marks only that case Claimed
Elsewhere. A corrupted journal disables Web
Queue with an error while keeping manual startup usable. Restore the journal
before resuming; do not delete it to bypass an unresolved case.

Result retries are at least once: this API contract has no idempotency-key field.
A network interruption after server acceptance can cause the same report to be
sent again. Portal submission itself is never automatically repeated.

## Automated checks and changed files

Run from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_web_sync.py -q
```

The suite uses one dummy job and the exact request/response contract. It checks
401 limits, raw bytes, filename collisions, marked-workbook scanner selection,
DPAPI surveyor separation, queue locking, error/retry/success, reporting failures,
manual Browse Folder, native popup persistence before acceptance, navigation,
and damaged-state recovery. Browser tests use local synthetic pages; no Base44
or insurer credentials are used and no live case is submitted.

Added:

- `app/web_sync/__init__.py`
- `app/web_sync/client.py`
- `app/web_sync/storage.py`
- `app/web_sync/downloads.py`
- `app/web_sync/submission.py`
- `app/web_sync/page.py`
- `tests/test_web_sync.py`
- `docs/WEB_SYNC.md`

Changed:

- `app/ui/main_window.py`: Web Queue navigation, folder handoff and per-run settings.
- `app/ui/worker.py`, `app/utils.py`: scan-local corrected-workbook selection.
- `app/automation/engine.py`: install the submission observer for web cases only.
- `app/automation/login_module.py`, `app/automation/claim_documents.py`: capture
  native messages before existing dismissal.
- `app/portals/newindia/automation/popup_service.py`,
  `app/portals/oic/automation/popup_service.py`: capture before DOM popup dismissal.
- `uiic_automation.spec`: explicitly include `win32crypt` in executable packaging.

No `app/data/*`, CAPTCHA, portal selector, Excel extraction or upload algorithm
was changed. `build.py` is unchanged. The packaged executable has not been rebuilt
or tested as part of this change; the existing spec already collects `app` modules.
Live Base44-to-insurer verification still requires an operator to follow the steps
above with a real queued test case and perform human Final Submit.
