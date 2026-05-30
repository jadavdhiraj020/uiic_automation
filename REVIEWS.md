Carefully and deeply review: {{ TARGET — specify what to review: files, commits, staged/unstaged changes, pull request diff, etc. }}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TASK TYPE: STRICT READ-ONLY AUDIT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is a code review and analysis task only. No changes of any kind must be made.

──────────────────────────────
MANDATORY SCOPE OF REVIEW
──────────────────────────────

You MUST:
  • Read every changed file in full.
  • Inspect every modified section line by line.
  • Review all related dependencies and affected flows.
  • Assess the behavioral impact of every change.

──────────────────────────────
HARD CONSTRAINTS — DO NOT:
──────────────────────────────

  ✗ Modify, refactor, or auto-fix any code.
  ✗ Remove or optimize any code.
  ✗ Generate replacement implementations.
  ✗ Apply patches or suggest inline edits.
  ✗ Produce any code output of any kind.

──────────────────────────────
REVIEW DEPTH
──────────────────────────────

Perform a structured review at each of these levels:

  → File level     — overall structure and purpose
  → Function level — logic correctness, edge cases
  → Line level     — changed lines inspected individually

──────────────────────────────
REVIEW CHECKLIST
──────────────────────────────

Cover all of the following:

  [ ] Logic correctness and validation flow
  [ ] Import usage and unused/dead code
  [ ] Removed or changed logic — downstream impact
  [ ] Dependency consistency
  [ ] Runtime and regression risk
  [ ] Architecture and design consistency
  [ ] Frontend/backend synchronization
  [ ] Settings, mappings, and config impact
  [ ] Portal or module isolation
  [ ] Packaging and build-time impact
  [ ] Async/threading safety (if applicable)
  [ ] UI state consistency (if applicable)
  [ ] Document upload/extraction flow (if applicable)

──────────────────────────────
FINDINGS TO IDENTIFY
──────────────────────────────

Flag any of the following:

  • Bugs and broken logic
  • Risky or unsafe changes
  • Hidden regressions
  • Broken control flows
  • Unsafe assumptions
  • Inconsistent or unpredictable behavior
  • Dependency or sync issues
  • Production and runtime risks

──────────────────────────────
ISSUE REPORT FORMAT (per finding)
──────────────────────────────

For each issue found, report:

  | Field            | Detail                         |
  |------------------|-------------------------------|
  | Issue            | Short summary of the problem  |
  | File / Module    | Affected location              |
  | Risk Level       | Low / Medium / High / Critical|
  | Root Cause       | Likely underlying reason       |
  | Approaches       | 2–3 options, including one    |
  |                  | production-grade recommendation|

Use table format. Keep each finding short and clear.

──────────────────────────────
OUTPUT REQUIREMENTS
──────────────────────────────

Final output must be:
  • Short, clean, and structured
  • Engineering-review style
  • Actionable — each finding includes fix approaches
  • Prefer tables over paragraphs

Do NOT produce:
  • Lengthy explanations
  • Code, patches, or fixes
  • Verbose summaries

──────────────────────────────
IF NO ISSUES FOUND
──────────────────────────────

State exactly:

  "No significant issues detected. Read-only audit complete. No code was modified."

──────────────────────────────
PRE-RESPONSE CHECKLIST
──────────────────────────────

Before submitting your review, confirm:

  ✓ Every changed file was reviewed.
  ✓ Every changed line was inspected.
  ✓ No code was modified, generated, or fixed.
  ✓ Output contains findings only.