---
name: code-review
description: >
  Use this skill when the user asks to review, audit, inspect, check, or analyze any code —
  including but not limited to: specific files, staged or unstaged changes, commits, pull request diffs,
  a function, a module, a feature branch, or any part of the codebase.
  Trigger phrases include: "review this", "audit this", "check my code", "look at this file",
  "what's wrong here", "review my PR", "review these changes", "inspect this diff",
  "is this safe to merge", "review before commit", or any intent to evaluate existing code.
  This skill enforces a strict READ-ONLY audit. No code changes, fixes, or patches are produced — ever.
  The output is a structured engineering report with findings, risk levels, and fix approaches only.
---
# Code Review — Strict Read-Only Audit

## Target

Specify what to review:

> Files / Commits / Staged changes / Unstaged changes / Pull request diff / Module / Function

---

## Ground Rules

This is a **read-only audit**. The agent's only job is to observe, analyze, and report.

**The agent MUST:**

- Read every changed or specified file in full
- Inspect every modified section line by line
- Review all related dependencies and affected flows
- Assess the behavioral impact of every change

**The agent MUST NOT — under any circumstance:**

- Modify, refactor, or auto-fix any code
- Remove or optimize any code
- Generate replacement implementations
- Apply patches or suggest inline edits
- Produce any code output of any kind

---

## Review Depth

Perform the analysis at three levels — in this order:

| Level              | Focus                                              |
| ------------------ | -------------------------------------------------- |
| **File**     | Overall structure, purpose, and role in the system |
| **Function** | Logic correctness, edge cases, control flow        |
| **Line**     | Each changed line inspected individually           |

---

## Review Checklist

Work through every item below before producing output:

- [ ] Logic correctness and validation flow
- [ ] Import usage — unused or dead imports
- [ ] Removed or changed logic — downstream impact
- [ ] Dependency consistency across modules
- [ ] Runtime and regression risk
- [ ] Architecture and design consistency
- [ ] Frontend/backend synchronization (if applicable)
- [ ] Settings, mappings, and config impact
- [ ] Portal or module isolation
- [ ] Packaging and build-time impact
- [ ] Async and threading safety (if applicable)
- [ ] UI state consistency (if applicable)
- [ ] Document upload or extraction flow (if applicable)

---

## What to Flag

Identify and report any of the following:

- Bugs and broken logic
- Risky or unsafe changes
- Hidden regressions
- Broken control flows
- Unsafe assumptions
- Inconsistent or unpredictable behavior
- Dependency or sync issues
- Production and runtime risks

---

## Issue Report Format

For **each finding**, produce one table block:

| Field                   | Detail                                           |
| ----------------------- | ------------------------------------------------ |
| **Issue**         | Short summary of the problem                     |
| **File / Module** | Affected file path or module name                |
| **Risk Level**    | `Low` / `Medium` / `High` / `Critical`   |
| **Root Cause**    | Most likely underlying reason                    |
| **Approaches**    | 2–3 fix options — one must be production-grade |

Keep each finding concise. One table per issue.

---

## Output Requirements

The final output must be:

- Short, structured, and clean — engineering review style
- Table-driven — prefer tables over paragraphs
- Actionable — every finding includes concrete fix approaches

The output must NOT contain:

- Lengthy explanations or summaries
- Any code, patches, or fixes
- Verbose descriptions of what the code does correctly

---

## If No Issues Found

Output exactly this line and nothing more:

> `No significant issues detected. Read-only audit complete. No code was modified.`

---

## Pre-Response Checklist

Before submitting the review output, confirm all four:

- ✅ Every specified file or change was reviewed
- ✅ Every changed line was individually inspected
- ✅ No code was modified, generated, or fixed
- ✅ Output contains findings only — no rewrites
