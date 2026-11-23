---
name: clarify-before-ask
description: MANDATORY before asking the user anything — any question, clarification, confirmation, choice between options, or "which do you prefer". Use whenever you are about to ask, clarify, confirm, or are unsure about scope, behavior, a missing value, an error path, or the deliverable. Never guess or infer from docs or code; ask the user, state your understanding, and give current flow, proposed flow, realistic examples, and a recommended choice.
---

# ClarifyBeforeAsk

Goal: the user always confirms the decision, so nothing is built on a guess. Make each decision easy to make without reading code.

Use the same names the user sees (portal labels, button text, spreadsheet columns, file names). Keep words simple. Follow `.agents/rules/output-style.md`: brief, plain, outcome-focused.

## Step 1 — Ask, don't assume (user's standing rule)

The user wants to see what you understand so they can confirm it is correct. So:

- **Do not guess, infer, or fill gaps from docs or code.** Reading code or guides is fine to describe the *current flow* accurately, but never use it to decide a behavior the user has not stated.
- **Do not skip a question because a default seems obvious.** If a choice about scope, behavior, values, errors, output, or the deliverable is not explicitly stated by the user, ask.
- **Show your understanding.** Begin with a short "My understanding" line restating the request in your own words, so the user can correct it.
- Only skip asking when the user's message states the choice explicitly, or the user says "don't ask" for that topic. Then list each decision you made in the final response.
- Never proceed on an unconfirmed assumption for anything irreversible or outward-facing (submitting, deleting, overwriting, sending, anything on a live portal), money, or claim values written to an insurer portal.

Wait for the answer before changing anything that depends on it. Independent read-only investigation may continue meanwhile.

## Step 2 — Pick the question(s)

- Ask the decision that unblocks the most downstream work first.
- One question per message by default; up to three only if independent.
- Do not bundle an approval ("is the plan OK?") with a decision. Do not ask permission for things already authorized.
- If a new answer reveals a new material decision, ask again; otherwise continue.

## Step 3 — Write the question

Use this exact structure. Keep each part short and specific.

1. **Current flow** — what happens today, where, and what the user sees. Say "not verified" if you could not confirm; say "no existing flow" if none.
2. **After the change** — what each choice would do: trigger, what the app does, when the user must act. Include concrete values, files, buttons.
3. **Examples (2–3)** — realistic, synthetic sample values, marked as examples (never real claim data). Cover: a normal case; a case where the choices give different results; and, when it matters, a missing value, repeat run, or failure. For each, say what the user sees under each choice.
4. **Question** — one direct sentence. Then 2–3 clearly different options:
   - Recommended option first, labelled `(Recommended)`, with its main benefit.
   - Each option: short bold label + one plain sentence of tradeoff.
   - Use free text only when the answer cannot be predicted (a specific value or rule).

Rules:
- Recommend, don't survey. Do not list options you would not pursue.
- State risks or irreversibility of an option when it applies.
- A preselected option is only a recommendation until the user answers.

## Step 4 — Use the tool correctly

- Use the available question tool (`AskUserQuestion`, `request_user_input`, or equivalent). Max 4 options, labels 1–5 words.
- If the tool only allows a one-line prompt, write Current flow / After the change / Examples in a message right before the call, then ask the short question.
- The user may see only the dialog: make the question stand on its own, naming the items it refers to.

## Step 5 — After the answer

Apply it and continue within the approved scope. Do not re-ask settled points. Any new unstated choice is a new question, not an assumption.

## Template

```
**Current flow**
<today's behavior, or "not verified" / "no existing flow">

**After the change**
<what each choice would do>

**Examples** (sample values)
- <normal case> → <result under each choice>
- <case where choices differ> → <result under each choice>
- <missing value / repeat / failure, if relevant> → <result>

**Question**
<one direct question>
- **<Recommended option> (Recommended)** — <benefit>
- **<Alternative>** — <tradeoff>
```

## Sample

**Current flow** — App3 stops at the first field it cannot fill on the Quick Update page; the user fixes it and returns to App3.

**After the change** — App3 tries every field, then shows one popup before clicking **Next**, listing either required-field issues only or all failed fields.

**Examples**
- Required **Date of Survey** and **Mobile Number** both missing → both choices list both in one popup.
- Only optional **Email ID** rejected → *Required only* clicks **Next**; *All failed fields* shows the email issue first.
- All fields fill → no popup under either choice.

**Question** — Which issues should App3 show before clicking **Next**?
- **Required fields only (Recommended)** — Shows only what can block the next page.
- **All failed fields** — Shows every failed entry, including optional ones.
