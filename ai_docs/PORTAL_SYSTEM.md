# Portal System

## Purpose

The portal system allows the app to run different insurance portal workflows while preserving the original UIIC Website 1 behavior.

## Registry

Module: `app/portals/registry.py`

Core objects/functions:

- `PortalInfo`
- `register_portal(info)`
- `list_portals()`
- `set_active_portal(portal_id)`
- `get_active_portal()`
- `get_active_portal_id()`
- `portal_settings_paths()`
- `portal_field_mapping_paths()`
- `portal_doc_mapping_paths()`

Registered portals:

```text
uiic
  display: UIIC (United India)
  url: https://portal.uiic.in/surveyor/home.jsp
  config: app/portals/uiic/config

newindia
  display: New India Assurance
  url: https://web.newindia.co.in/NIABancsPortal/IntermediaryLogin.html
  config: app/portals/newindia/config
```

## Config Path Resolution

For an active portal:

```text
bundled default:
  app/portals/<portal_id>/config/<file>.json

user override:
  LOCALAPPDATA/UIIC_Surveyor_Automation/portals/<portal_id>/config/<file>.json
```

If no portal is active, the legacy fallback is:

```text
bundled default:
  app/config/<file>.json

user override:
  LOCALAPPDATA/UIIC_Surveyor_Automation/config/<file>.json
```

## Portal Switching Runtime

Portal switching affects:

- Settings loaded in UI and engine.
- Field mappings used by Excel extraction.
- Document mappings used by folder scanner.
- `ClaimData.validate()`.
- `ClaimData.all_fields_for_preview()`.
- Login/navigation branches in `AutomationEngine`.
- New India phase branch inside engine.

Portal switching does not mutate existing bundled config files. User edits are saved under the active portal's AppData config path.

## Portal Isolation Strategy

Use this rule:

```text
Shared only when behavior is truly common.
Portal-specific by default when DOM, selectors, forms, or business flow differ.
```

Safe portal-specific locations:

- `app/portals/<portal_id>/automation/`
- `app/portals/<portal_id>/config/`
- portal-specific validation/preview methods in `ClaimData`

Avoid putting New India selectors or assumptions in UIIC modules such as `app/automation/selectors.py` unless the helper is explicitly generalized.

## Website 1 Protection

Website 1 means the existing UIIC workflow. Do not break:

- `app/automation/login_module.py`
- `app/automation/navigation_module.py`
- `app/automation/interim_report.py`
- `app/automation/claim_documents.py`
- `app/automation/claim_assessment.py`
- `app/automation/selectors.py`
- `app/portals/uiic/config/*`
- legacy `app/config/*` fallback

When changing shared helpers, run UIIC-oriented tests or at minimum reason through:

- Does `"0"` still fill?
- Are dates still formatted for UIIC Angular inputs?
- Are Angular change/input events still dispatched?
- Are upload rows still added and verified?
- Does browser still stay open after run?

## New India Current State

Implemented:

- Portal registry entry.
- Portal-specific settings, field mapping, doc mapping.
- Login module with manual CAPTCHA.
- Navigation module through Worklist and edit icon.
- Quick Update module draft.
- New India `ClaimData` fields, preview, validation.

Incomplete or risky:

- New India Phase 3 selectors and required-field behavior still need live portal verification.
- Automation stops after Phase 3 by design.
- Later New India form sections are not implemented.
- New India document upload flow is not implemented.
- New India selectors are not centralized in a selector registry yet.
- Validation requires many mandatory fields, but actual Phase 3 uses only a smaller subset.
