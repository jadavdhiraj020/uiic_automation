# Future Portal Integration Guide

## Purpose

This guide defines a repeatable pattern for adding or extending portals while protecting the UIIC baseline.

## New Portal Checklist

1. Add `app/portals/<portal_id>/__init__.py`.
2. Add `app/portals/<portal_id>/config/settings.json`.
3. Add `field_mapping.json`.
4. Add `doc_mapping.json`.
5. Register portal in `app/portals/registry.py`.
6. Add portal-specific automation modules.
7. Add portal branch in `AutomationEngine.run()` at high-level step boundaries.
8. Add `ClaimData` fields only if shared model needs them.
9. Add portal validation and preview methods.
10. Verify folder scan, preview, and at least first browser phase.

## Recommended Portal Module Layout

```text
app/portals/<portal_id>/
  __init__.py
  config/
    settings.json
    field_mapping.json
    doc_mapping.json
  automation/
    login_module.py
    navigation_module.py
    selectors.py
    <phase>_module.py
```

New India currently lacks a separate selectors file. Adding one would improve maintainability.

## Engine Branching Pattern

Keep engine branching coarse:

```python
if self.portal_id == "newportal":
    from app.portals.newportal.automation.login_module import do_login
else:
    from app.automation.login_module import do_login
```

Do not scatter portal-specific DOM selectors through shared UIIC modules.

## Data Model Pattern

For each new field:

1. Add attribute to `ClaimData`.
2. Add extraction mapping.
3. Add preview row.
4. Add validation if required.
5. Use in automation.
6. Add tests for any shared parsing/conversion behavior.

## Browser Automation Pattern

Each portal phase should:

- accept `page`, `claim`, `log_cb`, and optionally `stop_cb`
- log start and end
- check `stop_cb` between major chunks
- use portal-specific selectors
- use shared helpers only when behavior matches
- fill from `ClaimData`
- avoid final submit

## Portal Isolation Rules

- Do not change UIIC configs when implementing another portal.
- Do not change `app/automation/selectors.py` for another portal.
- Do not import another portal's module at top level from shared modules.
- Do not make shared helper behavior portal-specific with hidden conditionals unless unavoidable.
- Prefer explicit portal module functions over clever generic frameworks.

## When To Generalize

Generalize only after seeing repeated behavior across portals:

- same field input mechanics
- same upload row lifecycle
- same date widget behavior
- same document classification behavior

Even then, preserve UIIC behavior with tests.

