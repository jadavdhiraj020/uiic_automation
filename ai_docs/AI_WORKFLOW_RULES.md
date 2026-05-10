# AI Workflow Rules

## Purpose

This file is mandatory context for future AI and developer sessions. Follow it before changing code.

## Mandatory First Reads

Before implementation, read:

1. `ai_docs/COMMANDS.md`
2. `ai_docs/PROJECT_OVERVIEW.md`
3. `ai_docs/ARCHITECTURE.md`
4. `ai_docs/CLAIMDATA_MODEL.md`
5. Relevant workflow/config/portal docs for the task

## Command Rules

- Use `uv` commands from `ai_docs/COMMANDS.md`.
- Run the app with `uv run python main.py`.
- Run tests with `uv run pytest`.
- Build with `uv run python build.py`.
- Do not try multiple different command variants unless the canonical command fails and the reason is documented.

## Website 1 Protection Rules

- Treat UIIC as the production baseline.
- Do not rewrite UIIC login/navigation/interim/documents/assessment modules for New India work.
- Preserve legacy `app/config/*` fallback behavior.
- Preserve `app/portals/uiic/config/*`.
- Preserve final-submit manual review.
- Run or reason through UIIC regression tests when changing shared helpers.

## Portal Isolation Rules

- Put portal-specific selectors and flows under `app/portals/<portal_id>/`.
- Branch in `AutomationEngine` only at major workflow steps.
- Do not mix New India selectors into UIIC selector registry.
- Do not add hidden portal conditionals to helpers unless documented and tested.
- Keep portal config separate.

## Safe Implementation Practices

- Make small, phase-wise changes.
- Prefer additive fields and selector fallbacks.
- Do not remove known working selector alternatives casually.
- Preserve `"0"` as a valid amount.
- Use `ClaimData` as the shared data contract.
- Update extraction mapping, preview, validation, and automation together.
- Log field fills with source coordinates when possible.
- Keep browser open for manual review.

## No-Large-Rewrite Policy

Avoid broad rewrites of:

- `AutomationEngine`
- `ClaimData`
- `form_helpers.py`
- UI shell
- folder scanner
- Excel reader

Refactor only when it removes a real risk and can be verified incrementally.

## Testing Philosophy

- Tests should focus on shared helpers, parser behavior, mapping integrity, and regression risks.
- Portal live DOM behavior often needs manual browser verification.
- If changing shared helpers, run `uv run pytest`.
- If tests cannot be run, document why and describe the manual reasoning.

## Debugging Rules

- Start from active portal and preview source coordinates.
- Check user AppData overrides before assuming bundled config.
- Inspect logs before changing code.
- Dump DOM only for diagnosis.
- Fix mapping/config before touching parser code when labels are the issue.

## New India Phase Rules

- Treat New India Phase 3 as under live DOM validation until selectors are confirmed.
- Keep Phase 3 as a manual-review milestone.
- Implement later sections one phase at a time.
- Do not implement document upload until field sections are stable.
- Keep validation aligned with the implemented phase, or clearly distinguish future mandatory fields.

## Security Rules

- Do not publish or repeat credentials from config files.
- Do not add external CAPTCHA or document APIs without explicit approval.
- Keep local-first processing unless explicitly changed.
