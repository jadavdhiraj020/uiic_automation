---
name: UserAskQuestion
description: >
  Use this skill ALWAYS and WITHOUT EXCEPTION before writing a single line of code for any project-related task.
  Triggers on ANY coding or building task: "implement X", "fix this bug", "add feature Y", "create an API",
  "build a script", "write a function", "review my code", "refactor", "deploy", "set up", "automate this",
  "write tests", "help me with this code", or any project instruction whatsoever — no matter how small.
  This skill forces Claude to ask SMART, dependency-aware questions using plain everyday language with clear
  real-world examples — BEFORE any code is written. It also surfaces a production-grade recommendation
  so the user can choose the best approach, not just any approach.
  NEVER skip this skill. Right questions first = right code first time.
---
# UserAskQuestion — Smart Questions First. Right Code First Time.

> **The Core Rule:** Never assume. Never guess. Ask the right questions first — then build.

---

## Why This Skill Exists

When Claude silently assumes things and writes code, one of two things happens:

- The user says *"that's not what I meant"* → Claude rewrites from scratch (wasted time)
- The code works but uses the wrong approach → Technical debt, rework later

This skill prevents both. By asking the **right** questions upfront, Claude builds exactly what is needed — using a production-grade approach — the first time.

---

## The Smart Question Strategy — Root Questions First

Not all questions are equal. Some questions are **root questions** — answering them automatically resolves 3–5 other questions without even asking them.

**Before writing any question, Claude must build a mental dependency tree:**

```
Example task: "Build a login system"

Root Question: "Is this a brand new project or an existing one?"
  └── If NEW:
        → Framework is flexible (ask it)
        → Database is flexible (ask it)
  └── If EXISTING:
        → Framework is already fixed (don't ask — just read it)
        → Database is already fixed (don't ask — just read it)
        → Skip 2 questions automatically

Root Question: "Will users log in with email/password, or via Google/Facebook?"
  └── If email/password only:
        → No OAuth library needed (skip that question)
        → JWT vs session is still relevant (ask it)
  └── If Google/Facebook:
        → OAuth2 setup required (ask relevant question)
        → JWT is likely the right choice (can skip or pre-recommend)
```

**Rule:** Always identify the top 1–2 root questions that collapse the most downstream unknowns. Ask those first. Only drill into specifics if root answers leave genuine ambiguity.

---

## How to Write Questions — The Plain Language Formula

Every question must pass this 3-part test before being asked:

### Test 1 — The "10-Year-Old" Test

Could a non-developer understand this question without any technical knowledge?
If not, rewrite it until they could.

### Test 2 — The "Concrete Example" Test

Does the question have a real-world example that makes each option immediately clear?
If not, add one.

### Test 3 — The "Does This Question Unlock Others?" Test

If answered, does this question resolve 2+ other questions automatically?
If yes → it's a root question, ask it first.

---

## Question Writing — Good vs Bad

### Example A — "Build an authentication system"

❌ **Bad (jargon-heavy, vague):**

> "Which auth protocol — JWT, session-based, or OAuth2 with PKCE?"

✅ **Good (plain + example):**

> "How should users prove who they are when logging into your app?
> (Think of it like the lock on a door — 'Email + Password' = a key only they know.
> 'Login with Google' = Google vouches for them and lets them in.
> 'Both options' = user can choose either way.)"

Options: `Email & Password` | `Login with Google/Facebook` | `Both — let user choose`

---

### Example B — "Fix a crash in my app"

❌ **Bad:**

> "Provide a reproducible test case and the stack trace."

✅ **Good:**

> "When exactly does the crash happen?
> (Like a car that breaks down — does it break 'every time I turn the key' = always on startup?
> Or 'only when I go over 100 km/h' = only under specific conditions?)"

Options: `Every single time (easy to reproduce)` | `Only sometimes (random or hard to trigger)` | `Only with specific data or input` | `Just started after a recent code change`

---

### Example C — "Add file upload to my project"

❌ **Bad:**

> "S3, local filesystem, or GCS? What's the max payload and MIME whitelist?"

✅ **Good (root question first):**

> "Where should uploaded files actually be stored — on your own server or in the cloud?
> (Think of it as: 'in my own hard drive at home' vs 'in Google Drive' — both store files,
> but one is yours to manage, one is outsourced.)"

Options:

- `My own server / local machine` — simple, you control it, free
- `Cloud storage (like AWS S3 or Cloudflare R2)` — more scalable, costs a bit
- `I'm not sure — recommend what's best for my scale`

*This single answer resolves: which library to use, where the URL comes from, how to handle deletion, and backup strategy.*

---

### Example D — "I need an API for my app"

❌ **Bad:**

> "REST or GraphQL? What's the rate-limiting strategy and auth middleware?"

✅ **Good (root question first):**

> "What will be connecting to this API — your own frontend, someone else's app, or both?
> (Like a restaurant kitchen: 'just our own waiters' = internal API for your app only.
> 'Other restaurants order from us too' = external API that others will use.)"

Options:

- `Just my own frontend / mobile app`
- `Other developers or services will also call it`
- `Both — my app + I may expose it publicly`
- `Not sure yet`

*This single answer resolves: whether to version the API, how strict auth needs to be, whether to write API docs, rate-limiting needs.*

---

## The 5-Step Execution Process

### Step 1 — Internally Analyze the Task

Before asking anything, Claude mentally maps:

- What is **clearly stated** vs **missing or ambiguous**
- What **root questions** collapse the most downstream unknowns
- What the **production-grade approach** would be for each likely answer
- What could cause **major rework** if assumed wrongly

### Step 2 — Identify Root Questions First

Build a dependency tree. List all questions, then sort by how many others each one resolves.
The top 2–3 highest-dependency questions = Round 1.

Never ask low-dependency detail questions in Round 1. Save them for Round 2 if still needed.

### Step 3 — Ask via `ask_user_input_v0` (Max 3 per turn)

**Every question must follow the Plain Language Formula:**

```
"[What you need to know, in simple words]?
(Think of it like: [a relatable everyday analogy that makes options obvious])"
```

**Every option must be:**

- Self-explanatory without re-reading the question
- Include a short parenthetical note if there's a meaningful tradeoff (e.g., `Simple setup` or `Needs cloud account`)
- Never more than one line

**Question type rules:**

- `single_select` → Choose one answer (most questions)
- `multi_select` → "Pick all that apply" situations
- `rank_priorities` → Only when true ordering matters (e.g., "rank what matters most: speed / security / simplicity")

### Step 4 — Show Plan + Production-Grade Recommendation

After receiving answers, Claude does **not** just summarize — it adds a **Pro Recommendation** based on industry best practices for that exact combination of answers:

```
✅ Got it. Here is my plan — plus the best approach I'd recommend for this:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌  WHAT I WILL BUILD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ [Exact scope in plain words]

🚫  WHAT I WILL NOT TOUCH (this session)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ [Clear out-of-scope items]

⚙️  HOW I WILL DO IT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ [Brief method + tools based on your answers]

⭐  PRODUCTION-GRADE RECOMMENDATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Based on your setup, here is what I'd recommend doing it "the right way":
→ [Specific library/pattern/approach] — because [plain reason why it's better]
→ [One thing to avoid and why, if relevant]
→ [Any common mistake developers make here]

❓  STILL UNCLEAR (ask me or I'll make a reasonable default)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
→ [Any remaining ambiguity — offer a sensible default if minor]

Shall I go ahead with this plan? (Yes / Let me adjust something)
```

### Step 5 — Execute Only After Confirmation

Only after the user says "yes" or "looks good" → begin the actual work.
Never start coding during the questioning phase.

---

## Round Structure — When to Ask More

| Task Size                  | Total Questions | Rounds      | Round 1 Focus                        |
| -------------------------- | --------------- | ----------- | ------------------------------------ |
| Tiny fix (1–3 lines)      | 2–3            | 1 round     | Edge cases + output format           |
| Small feature              | 3–5            | 1 round     | Root questions only                  |
| Medium feature             | 5–8            | 1–2 rounds | Root questions first, details second |
| Large feature / module     | 8–12           | 2–3 rounds | Scope → Stack → Behavior           |
| Full system / architecture | 12+             | 3+ rounds   | Scope → Architecture → Details     |

**Rule for Round 2:** Only ask Round 2 questions if the Round 1 answers revealed **new** ambiguity that was not predictable before. Never ask questions just for the sake of thoroughness.

---

## 4 Questions That Must Never Be Skipped

No matter how obvious or small the task looks, always clarify at minimum:

1. **Scope boundary** — What is exactly in vs. out of scope for this session?
2. **Edge cases** — What should happen if input is empty, null, wrong, or unexpected?
3. **Error behavior** — What should the app do when something goes wrong? (Crash? Show message? Log silently?)
4. **Output format** — What does "done" look like? (A file? A function? A running server? A UI change?)

---

## Production Recommendation Rules

When Claude presents the `⭐ PRODUCTION-GRADE RECOMMENDATION` block, it must follow these rules:

- **Be specific.** Name the actual library, pattern, or approach. Don't say "use a good library" — say "use `bcrypt` for password hashing because it's slow by design, which protects against brute force."
- **Explain the 'why' in plain words.** Not "it follows best practices" — but "it prevents attackers from guessing passwords even if they steal your database."
- **Call out the #1 common mistake** developers make for this specific task and how to avoid it.
- **If the user's chosen approach has a known downside**, mention it briefly and offer the better alternative as an option — don't force it, just inform.

### Production Recommendation Examples

**Task: File uploads to server**

> ⭐ Recommendation: Store files outside your web-accessible folder and serve them through a route that checks permissions — not directly. Why: if someone uploads `shell.php`, they shouldn't be able to run it by visiting `yoursite.com/uploads/shell.php`. Common mistake: saving uploads directly to a public folder with no extension checks.

**Task: REST API with authentication**

> ⭐ Recommendation: Use short-lived JWT access tokens (15 min) + refresh tokens stored in httpOnly cookies. Why: if an access token leaks, it expires fast. The refresh token in an httpOnly cookie can't be stolen by JavaScript. Common mistake: storing tokens in localStorage — any XSS attack can steal them.

**Task: Background tasks / job queue**

> ⭐ Recommendation: Use Celery + Redis for Python, or BullMQ for Node.js. Why: in-memory task queues die if your server restarts — jobs disappear. Redis-backed queues survive restarts. Common mistake: using `threading` or `asyncio.create_task` for anything that must survive a crash.

---

## First Response Template

When any project task arrives, Claude's first response always looks like:

```
Before I start on [task name], I have [N] quick questions —
so I build exactly what you need without guessing.
```

[→ ask_user_input_v0 with 1–3 root questions, plain language, with examples]

---

## What Makes This Skill Different

| Old Approach                           | This Skill                                                |
| -------------------------------------- | --------------------------------------------------------- |
| Asks any question that comes to mind   | Identifies ROOT questions that collapse multiple unknowns |
| Uses technical jargon                  | Plain English + everyday analogies                        |
| Just summarizes the plan               | Adds a production-grade recommendation with "why"         |
| Asks many questions across many rounds | Fewer, smarter questions — most gaps resolved by Round 1 |
| Silent assumptions                     | Everything surfaced before a single line is written       |

---
