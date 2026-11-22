---
name: user-ask-question
description: Clarify project decisions before implementation. Ask clear, detailed questions that explain the current flow, the proposed flow, and two or three realistic examples. Use when the user requests clarification or when a choice about scope, behavior, or the deliverable would change the result.
---

# UserAskQuestion

Give the user enough information to make a decision without having to read the code. Use the same names they see in the app, spreadsheet, files, or workflow.

## Decide what to ask

1. Read the request, prior decisions, and available evidence. Check the current code or UI when that can answer a question. Say when the current behavior is unknown or when there is no existing flow.
2. Identify the decision that affects the most downstream work. Ask it first. Prefer one question at a time and group up to three if they are independent. Ask about scope, missing values, errors, or output only when the answer would meaningfully change the work.
3. Ask before changing anything that depends on the answer. Continue any useful investigation or work that can proceed independently. When the request is already clear, proceed unless the user asked you to confirm a specific choice. If the user asks you to clarify and wait for approval, wait. If the user asks for no questions, follow their instructions for unresolved choices and report those choices in the final response.

## Write the question

Use the following structure for every decision question. Keep the words simple and the behavior specific.

1. **Current flow** — Explain what happens today in one or two sentences. Name where it happens and what the user sees. If you could not verify it, say so.
2. **After the change** — Explain what would happen under the proposed choices. Describe the trigger, what the app does, and when the user needs to act. Include specific values, files, buttons, or outputs wherever they help the user choose.
3. **Two or three examples** — Give a normal case and a case where the choices lead to different results. Add a third case when a repeat run, missing value, or failed action matters. For each, state the input or situation and what the user would see under the applicable choices. Use realistic sample values and mark them as examples.
4. **The decision** — Ask one direct question at the end. Offer two or three clearly distinct choices when there is a real choice. Put the recommended option first and explain its main benefit or tradeoff in plain words. Use free text when the answer is a specific name, value, or rule you cannot predict.

Use the available user-question tool, such as `request_user_input_async` or `request_user_input`. Put the flow and examples in the question itself when the tool supports detailed prompts. If the tool limits the prompt to one sentence, provide the context immediately before asking. Keep button labels short enough to scan. Treat a suggested or preselected option as a recommendation until the user answers.

After the user answers, apply that answer and continue within the approved scope. Ask another question only if the answer reveals a new decision that materially affects the result. If you proceed under a reasonable assumption the user authorized you to make, disclose it in the final response.

## Sample questions

Use these as patterns. Check the actual behavior and use examples from the task at hand.

### When should App3 show a popup?

**Current flow**

App3 stops on the first field it cannot fill on the Quick Update page. The user fixes that field, then returns to App3 to continue.

**After the change**

App3 would try every field on the page, then show one popup before clicking **Next**. The popup can list issues with required fields only, or it can also show issues with optional fields.

**Examples**

- The required **Date of Survey** and **Mobile Number** are both missing. Either choice shows both fields together in one popup.
- All required fields are correct, but the portal rejects an optional **Email ID**. **Required fields only** lets App3 click **Next**. **All failed fields** shows the email issue first.
- All fields fill correctly. App3 clicks **Next** without a popup under either choice.

**Question**

Which issues should App3 show before clicking **Next**?

- **Required fields only (Recommended)** — Review issues that can prevent moving to the next page.
- **All failed fields** — Review every failed entry, including optional fields.

### What should happen when the upload workbook is open during a rescan?

**Current flow**

App3 creates a new workbook with a numbered name on each scan, such as `auto_oic_upload_1.xlsx`.

**After the change**

App3 would write the latest scan to one workbook named `auto_oic_upload.xlsx`. If Excel is holding that file open, App3 can ask the user to close it and rescan, or prepare the latest workbook in a temporary folder.

**Examples**

- The workbook is closed and the scan succeeds. App3 replaces `auto_oic_upload.xlsx` with the latest workbook under either choice.
- The workbook is open in Excel and the new scan has a different invoice total. **Close Excel and rescan** keeps the previous file and shows what to do. **Use a temporary workbook** gives the run the new invoice total from the temporary file.

**Question**

If Excel prevents App3 from replacing the workbook, what should App3 do?

- **Close Excel and rescan (Recommended)** — Keeps the claim folder workbook as the file the user reviews before uploading.
- **Use a temporary workbook** — Lets the run continue with fresh values from a different location.
