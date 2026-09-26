# App-3 Web Queue

App-3 uses the authenticated Base44 app-ID API for DocWriter app
`6ab74380b9e0063628bc990a`. It does not open the Base44 website.
The Web Queue has one handoff flow: **receipt_v1**. The former Base44
claim and portal-result calls are no longer used.

## Case journey

1. The DocWriter operator sends a case to App-3. App-3's saved DocWriter
   email/password (Windows DPAPI) obtains a Bearer token. The queue is polled
   about every 30 seconds with `getAutomationJobs`.
2. App-3 stages each incoming dispatch in its own local case folder. It first
   tries `getAutomationCaseZip`; if that fails in an eligible way, it uses the
   existing individual-file downloader through `getAutomationCaseFiles`.
   Neither download method claims the case.
3. The existing downloader retries eligible failures, checks file sizes and
   MD5 checksums, validates the marked latest corrected Excel, and promotes
   the complete temporary folder to its final location. A case is Ready only
   after the final local folder verifies.
4. App-3 sends `acknowledgeApp3Receipt` with `case_id`,
   `automation_dispatch_id`, and `receipt_status: "received"` after successful
   verification. If the existing download/verification attempts are exhausted,
   it sends `receipt_status: "failed"`. A temporary receipt failure remains
   pending for retry. HTTP 409 means the dispatch was replaced; App-3 does not
   acknowledge an older dispatch.
5. The App-3 user selects any Ready case for Workspace. Its local folder goes
   through the existing `_scan_folder()` pipeline. Only one insurer automation
   can run at a time; other Ready cases stay staged.
6. When the App-3 user clicks **Start Automation**, App-3 verifies the local
   case again and uses the selected insurer's login saved in App-3 Settings.
   It starts the existing insurer automation locally. There is no Base44
   claim call. Human review and insurer Final Submit remain manual.
7. The insurer's exact Final Submit message and available screenshot are saved
   locally in the case folder. A confirmed success completes the case locally.
   A browser close or Workspace Stop leaves it available for a local retry.
   No portal start, stop, success, or failure result is sent to Base44.

## API messages App-3 sends

All functions use `https://base44.app/api/apps/6ab74380b9e0063628bc990a/functions/<name>`
with the operator Bearer token. An HTTP 401 causes one re-login and retry.

| Function | Purpose | App-3 sends |
| --- | --- | --- |
| `getAutomationJobs` | Find incoming work | Queue request |
| `getAutomationCaseZip` | Preferred case download | `case_id`, `automation_dispatch_id` |
| `getAutomationCaseFiles` | Individual-file fallback | `case_id`, `automation_dispatch_id`, and `file_id` for a file |
| `acknowledgeApp3Receipt` | Report verified transfer outcome | `case_id`, `automation_dispatch_id`, `receipt_status` (`received` or `failed`) |

App-3 never sends insurer portal passwords through these calls. Receipt
acknowledgement describes **case transfer to App-3**, not insurer submission.

## Local files and credentials

Encrypted DocWriter operator credentials and per-case state are under App-3's
`web_sync` application-data directory. Operator-visible case folders are under
the Windows user's `Automations` directory, separated by insurer and case.
Each case has its own `web_sync_manifest.json` and `case_activity.log`.
Submission messages and evidence remain in the local case folder.

The insurer portal login used by this flow comes from App-3 Settings for
`uiic`, `newindia`, or `oic`. The DocWriter operator login is separate and is
used only for Base44 API access. Manual **Browse Folder** continues to use
the existing scanner and Workspace behavior.

## Verification

Run `uv run pytest -q` from the repository root. Receipt tests use dummy
case IDs and responses; they do not submit a real insurer case. The retired
claim/report assertions have been removed. A live insurer submission still
requires a separate operator-run test.
