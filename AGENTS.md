# Asking the user questions

Before you ask, clarify, confirm, or offer a choice, read and follow [`.agents/skills/ClarifyBeforeAsk/SKILL.md`](.agents/skills/ClarifyBeforeAsk/SKILL.md).

- Always ask the user when a choice about scope, behavior, values, errors, output, or the deliverable is not explicitly stated. Do not guess, infer, or fill gaps from docs or code.
- State your understanding of the request first so the user can confirm it is correct.
- Use the skill's format: current flow, after the change, 2–3 examples with synthetic values, then one question with a recommended option first.

# Portal field and logic documentation

Keep the New India Assurance and Oriental Insurance Company portal guides aligned with the implementation.

- New India Assurance (NIA/New India) uses [`logic_field_documention/nia.md`](logic_field_documention/nia.md).
- Oriental Insurance Company (OIC) uses [`logic_field_documention/oic.md`](logic_field_documention/oic.md).

For every change that affects a field or behavior in either portal:

1. Read the affected guide before editing. Check both guides when changing shared code such as Excel or PDF extraction, claim data, folder scanning, settings, the automation engine, or recovery.
2. Update the affected guide in the **same change** as the implementation. Cover changes to mappings, defaults, calculations, validation, field entry, navigation, uploads, generated files, review prompts, and manual handoff. A direct NIA change belongs in the NIA guide, an OIC change belongs in the OIC guide, and a change that affects both belongs in both guides.
3. Describe what the current code does. For a changed field, include its portal step, input source and priority, transformation or default, and what happens if the value is missing or rejected. For a workflow change, describe what triggers it, what App3 does, and what the user sees or does next. Link to the relevant code or configuration and use a synthetic example when it clarifies the rule.
4. Before finishing, review the code and documentation diffs together. Correct stale text in the affected section and identify unverified portal behavior as such. Include the relevant guide in the same commit or pull request when publishing the code.

Use the labels shown in the portal and distinguish shipped defaults from workspace overrides. Use synthetic examples and omit credentials, claim records, and personal data. A behavior-preserving refactor needs a guide edit only if it changes a documented reference or exposes inaccurate guidance.
