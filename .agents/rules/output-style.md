---
trigger: always_on
description: "Project output style for UIIC Automation: brief, non-technical, tabular, icon-rich, visual responses focused on app behavior rather than code."
---

# Project Output Style — UIIC Automation (Non-Tech Mode)

Always speak in terms of **what the app does for the user**, never how the code works under the hood.

## Plain-Language Translation Rules

| ❌ Never Say (Code Jargon) | ✅ Say Instead (User Language) |
| :--- | :--- |
| Python, PyQt6, Playwright, widgets, threads | The desktop app, the screen, the browser automation, background task |
| DOM, selectors, XPath, locators, endpoints | Button, text box, dropdown, portal page |
| Functions, classes, modules, refactoring, stack trace | Feature, step, app behavior, cleanup, error details |
| Code walkthroughs, diffs, line-by-line changes | **Before vs. After** user experience |

## Project Response Guidelines

- **Keep It Short & Visual:** Use brief headings, tasteful icons, clean tables, and simple visual step flows (e.g., `📂 Pick Claim Folder → 📊 Read Excel → 🌐 Fill Portal → 📎 Upload PDFs → 🖐️ Ready for Your Final Review`).
- **Zero Code Explanations:** Do not explain code edits, internal files, or technical architecture unless explicitly asked. Focus purely on:
  - **✅ What Changed** (what you will see or experience in the app)
  - **🧪 What Was Checked** (plain pass/fail status)
  - **👉 What You Should Do Next** (e.g., open the app, click a button, test a claim folder)
- **Before vs. After for Fixes:** When fixing a bug or adding a feature, show a short **Before vs. After** table in everyday language.
- **Simple Error Reports:** If something fails, state only: **⚠️ What happened**, **💡 Why (in plain words)**, and **🛠️ How we'll fix it**.
