@AGENTS.md

# UIIC Surveyor Automation — codebase guide

Windows desktop app (PyQt6 + Playwright) that fills insurer surveyor portals from a claim folder (Excel/PDF reports + documents). It automates data entry and uploads, then leaves the browser open: **a human always does the final review and Final Submit.** Everything runs locally (OCR included).

Supported portals (registered in [app/portals/registry.py](app/portals/registry.py)): **UIIC** (United India, legacy/original), **New India Assurance (NIA)**, **Oriental Insurance Company (OIC)**.

## Commands

```powershell
uv venv --python 3.10; uv sync                # setup (Python >=3.10,<3.13)
uv run playwright install chromium            # browser engine
uv run python main.py                         # run the app
uv run pytest -v                              # tests (pytest + pytest-asyncio); no tests/ dir is currently committed
.\build.bat                                   # PyInstaller onedir build -> dist\UIIC_Surveyor_Automation (--rebuild skips install)
uv run python scripts/verify_packaged_runtime.py   # sanity-check a packaged build
```

CI ([.github/workflows/release.yml](.github/workflows/release.yml)) builds/releases the EXE on code pushes; it ignores `*.md`, `docs/`, and the sample-data folders.

Constraints that matter: `paddlepaddle` must stay `<3.0.0` (3.x crashes on Windows Intel CPUs), `numpy<2.0.0`. OCR uses PaddleOCR and RapidOCR (ONNX).

## Layout

| Path | Role |
|:--|:--|
| [main.py](main.py) | Entry point; logging, frozen-env setup (bundled Playwright browsers), preflight check of bundled resources, license gate, launches main window |
| [app/utils.py](app/utils.py) | `resource_path` (read-only bundle) vs `user_data_dir` (writable AppData) — works frozen and from source |
| [app/portals/](app/portals/) | Portal registry + per-portal packages: `uiic/` (config only; code lives in shared `app/automation`), `newindia/`, `oic/` |
| [app/automation/](app/automation/) | Shared/UIIC automation: [engine.py](app/automation/engine.py) (`AutomationEngine.run_automation`, orchestrates login→navigate→interim report→assessment→documents), captcha solver, OCR engine, login/navigation, claim_assessment, claim_documents, selectors, `services/` (upload, PDF merge, cheque OCR) |
| `app/portals/<id>/automation/` | Portal-specific step modules (NIA: claim_assessment, document_upload, driver_details, fir_details, neft, survey_fee_bill, work_approval, recovery…; OIC: basic_details, assessment_of_loss, interim_report, workflow, review_browser, validation…) |
| `app/portals/<id>/config/` | Per-portal `settings.json`, `field_mapping.json`, `doc_mapping.json`, `automation_defaults.json` (OIC also city/RTO/licence maps) |
| [app/data/](app/data/) | Claim data layer: `data_model.py` (claim model), `excel_reader.py` (label-driven extraction — finds values by label text, not cell position), `pdf_report_reader.py` / `report_reader.py`, `folder_scanner.py` (classifies claim-folder files, merges leftovers when `requires_document_merge`), assessment/printable-Excel generators |
| [app/ui/](app/ui/) | PyQt6 UI: `main_window.py`, components (home/workspace/progress/settings pages, recovery dialog), `worker.py` (runs automation off the UI thread), `claim_folder_service.py`, `styles.qss` |
| [app/web_sync/](app/web_sync/) | "App-3 Web Queue": polls Base44 DocWriter API, downloads/verifies case zips into local folders (see [docs/WEB_SYNC.md](docs/WEB_SYNC.md)); no results are sent back to Base44 |
| [app/licensing/](app/licensing/) | Hardware-fingerprint license verification (public key bundled); generator tools in [tools/](tools/) |
| [logic_field_documention/](logic_field_documention/) | **Authoritative field/logic guides** for NIA and OIC (see AGENTS.md — must be updated with code changes) |
| [docs/](docs/) | Case journey, NIA DOM reference, universal report reader, web sync docs |

Sample/test data folders (`AAA/`, `ATTACHMENT/`, `OIC DOCS/`, `SendAnywhere_746022/`, `UIIC_TEST/`, `benchmark_25_pdfs/`) are fixtures — treat as synthetic-ish claim data; don't copy values from them into docs or commits.

## Architecture notes

- **Portal-aware config resolution:** each config file has a bundled default (`app/portals/<id>/config/`) and a per-user override in AppData. UIIC falls back to legacy `app/config/` when its portal files are absent. Docs must distinguish shipped defaults from workspace overrides. When a build's shipped `field_mapping.json`, `doc_mapping.json` or `automation_defaults.json` differ from what a PC last saw, [app/config_sync.py](app/config_sync.py) moves that PC's saved copies to `config_backups` at startup (packaged EXE only) (never `settings.json`, which holds credentials). Settings → "Export as Shared Defaults" (source runs only) writes a PC's config into the shipped files.
- **Capability flags on `PortalInfo`** (e.g. `requires_document_merge`) keep portal-specific behavior out of shared code like the folder scanner. Add flags there rather than branching on portal id in shared modules.
- **Pipeline:** claim folder → `folder_scanner` + Excel/PDF readers → claim data model → validation gate in UI → worker thread runs portal automation via Playwright → pause/recovery dialogs on failure → browser left open for manual final submit.
- Only one insurer automation runs at a time; Web Queue cases stay staged until selected in Workspace.
- Frozen builds: read bundled files via `resource_path`, write only under `user_data_dir`.

## Conventions

- Changes affecting NIA or OIC fields/behavior **must** update the matching guide in `logic_field_documention/` in the same change (rules in AGENTS.md).
- Use portal labels as shown on screen; use synthetic examples; no credentials or personal data in code, docs, or logs.
- Branch naming seen in history: `nov-21-<name>-<topic>`; commit style `fix(newindia): …`.
- Project response style (`.agents/rules/output-style.md`): when reporting to the user, keep it brief, plain-language and outcome-focused (what changed / what was checked / what to do next) rather than code walkthroughs, unless asked for technical detail.
