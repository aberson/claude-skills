---
name: review-uat
description: "Refine a user-acceptance-test (UAT) script so every step is unambiguous, every prerequisite is explicit, and only the things that genuinely need a human stay on the human's plate. Use when a UAT/manual-test/handoff doc reads like 'wipe → expect setup screen' and the operator has to guess what to do or what counts as pass."
user-invocable: true
---

# Review UAT

Take a draft UAT script (manual smoke list, M-step in a plan, "things to test before ship" doc) and produce a tightened version where:

1. Every step is **unambiguous** — one valid reading, not three.
2. Every step has **explicit prerequisites** (what state the system must be in first).
3. Every step has **explicit pass criteria** (what the operator looks for, in observable terms).
4. Only the steps that **genuinely need a human** remain on the human's plate. Setup, teardown, and anything verifiable from logs / DB / HTTP gets split out so an agent can do it.

Iteration goal: a future operator (or a fresh Claude session) can execute the UAT cold, without asking clarifying questions or guessing.

---

## Invocation

```
/review-uat                          # ask user for the draft
/review-uat path/to/plan.md#step-21  # refine the M-step at this anchor
/review-uat --apply                  # after refinement, write the result back to the source doc
/review-uat --exec                   # after refinement, delegate execution of the refined script to /user-uat
/review-uat --exec --dry-run         # delegate with --dry-run: /user-uat prints what WOULD run; nothing executes
```

`--apply` and `--exec` are opt-in. Default behavior is read-only describe-only: produce the refined version in chat, do NOT modify the source and do NOT run anything.

---

## When to use

- A plan has a "Manual M*" step or "bundled UI smoke" handoff that reads as a terse bullet list.
- The user pastes a UAT script and asks "can you test this?" — the right first move is often to refine the script before running it.
- After a UAT pass that surfaced "wait, what did you mean by X?" — feed the ambiguity back into the doc.
- Before a release-gate handoff to a non-author operator.

Do **not** use to write a UAT from scratch — this skill refines existing drafts. For a brand-new UAT, start with the relevant `--ui` test pass conventions in the project's plan doc.

---

## Inputs

Ask the user for:

1. **The UAT draft** — paste, file path, or pointer to a section of a plan doc.
2. **The feature under test** — one sentence so the skill can ground each step in real code (e.g., "Phase D Step 21 parent PIN gate").
3. **Operator profile** — is the operator the author of the feature, or a fresh pair of hands? (Defaults to "fresh" — assume nothing.)

If the conversation already contains the draft (e.g., user pasted it as the trigger), skip the ask.

---

## Process

### Step 1 — Ground each step in primary source

For every line in the draft, before critiquing it, find the code / config / doc it implicitly references. Cite `file:line`. This is non-negotiable: a critique built on guesses is worse than the original draft.

If a step references behavior whose source you cannot locate, flag it as **Blocker: cannot ground**. The fix is usually a missing link or a stale reference, not a wording change.

### Step 2 — Classify each step on four axes

For each step, score:

| Axis | Question | Output |
|------|----------|--------|
| **Ambiguity** | How many valid readings does this have? | Count + list the readings |
| **Prereq completeness** | What state must hold before this step that isn't stated? | List missing prereqs |
| **Action — human or agent?** | Does the *doing* need a human? (button press, voice, hardware, out-of-band) | "human" / "agent" |
| **Verify — human, vision-judge, or agent?** | Does the *checking* need a human, or can a browser-driven vision-judge do it, or is it a machine probe? | "human" / "vision-judge" / "agent" / "split" |

**Action and Verify are separate decisions.** They almost always split differently. A step can have human action + agent verify (the most common shape). Pure-human verify is rare and should be defended: "why can't this be an HTTP probe / sqlite query / log grep — or, for a *rendered screen*, a `/judge-ui` vision check?" Reserve pure-human verify for motion, audio, and subjective feel.

**Action needs a human when it requires:**

- Real hardware input (mic, speaker, camera, physical button)
- Out-of-band action (second device, parent's phone, recovery procedure)
- A UI interaction the agent can't drive headlessly (or where Playwright would be more setup than the value justifies)

**Verify can be a VISION-JUDGE** (a browser-driven screenshot + vision model via `/judge-ui`, run by `/user-uat --ui`) **when it is:**

- A **rendered screen state** captured in a single frame — layout, a component present, heading/copy text, a list/table's contents, "the right screen showed, no error banner". Emit these as `Verify (visual — vision-judge)` (below) instead of punting to the human — always paired with the API/DB read-back that corroborates the pixels.

**Verify still needs a HUMAN when it requires:**

- **Motion / animation** ("did it flash?", "did the countdown tick?") — a screenshot is one frame, it can't see motion
- Auditory judgment (sfx fired, voice quality)
- Subjective UX (does this feel responsive? is this label clear?)
- Anything credentialed / physical / real-device a browser can't drive

**Verify does NOT need a human when it asks:**

- "Did the API return 200?" (curl + grep)
- "Does the DB row exist? With the right shape?" (sqlite query)
- "Is the file on disk? At the expected path? With the expected size/MIME?" (Read tool)
- "Did the log line appear?" (grep)
- "Does the WebSocket envelope arrive with the right fields?" (a small script)
- "Does the count of X equal Y after the action?" (sqlite COUNT)

When the action is a UI button-press but the *consequence* is recorded in the DB or surfaced via API, the verify is agent. The human's job is the click; the agent's job is the audit.

### Step 3 — Rewrite each step in the canonical format

```
### Step <N>: <one-line title>

**Setup (agent):**
- <command or action the agent runs to put the system in the required state>
- <command or action ...>
- **If the human's action will trigger a backend API call: include a direct probe of that endpoint here (before the human acts).** A 500/404/503 caught in Setup saves the operator from doing browser work that will just fail. Move the primary endpoint smoke-test from Verify into Setup for any step where the human drives a UI that calls the backend.

**Action (human):**
- <single, concrete thing the human does — only the irreducible part>

**Verify (agent):**
- <command + expected result, e.g., "curl /api/auth/parent/status → {pin_set: true, locked: false}">
- <sqlite query + expected row count, e.g., "SELECT count(*) FROM toys WHERE archived=0 → 1">
- <file check, e.g., "ls data/images/toys/ → exactly one .png file matching uuid pattern">
- <log grep, e.g., "grep 'pin_set' logs/backend.log → 1 INFO line, 0 WARNING">

**Verify (visual — vision-judge via `/judge-ui`):**
- <a rendered-state check a browser + vision model can judge, in observable terms — e.g., "PinSetup heading reads 'Set parent PIN' and two PIN input fields are visible; no flash of the login screen first" — PAIRED with the read-back that corroborates it (e.g., "and /api/auth/parent/status → pin_set:false")>
- Omit this block when there's no rendered-state check, or when the only visual checks are motion/audio/feel (those go to Verify (human)). Run via `/user-uat --ui`; on vision-judge uncertainty it falls back to a human ask.

**Verify (human):**
- <observation that genuinely requires eyes ON MOTION/AUDIO/FEEL — e.g., "countdown ticks once per second", "the chime sound fires", "the transition feels smooth">
- <auditory / motion / subjective check that a single screenshot can't settle ...>

**Fail signals (what to flag):**
- <what counts as a regression — e.g., "any flash of the login screen before setup", "countdown stops ticking">

**Source of truth:** <file:line> — link the code that defines the expected behavior. If the supplied project facts give you only a file and a function/section (no line number), write `<file>:<function-name>` or `<file>:<section-name>`; if even that is unavailable, write `<file> (line unknown)`. **Never** emit a bare filename, `TBD`, `the spec`, or a plan-level descriptor like `project-facts:bullet-N` — those are ungrounded and must instead be flagged as **Blocker: cannot ground** per Step 1.
```

If the agent setup or verify is non-trivial, the rewritten step may include short shell blocks. Keep them copy-pasteable AND executable by `/user-uat` (the `--exec` hand-off target — Step 5.5).

**Before writing any shell block, determine the target shell from the project's CLAUDE.md or workspace instructions.** Shell syntax must match the runtime environment:
- **Windows / PowerShell (default in many workspaces):** `curl.exe` not `curl` (`curl` aliases to `Invoke-WebRequest` and rejects standard curl flags); backtick (`` ` ``) for line continuation; `$env:VAR` not `$VAR`; `NUL` not `/dev/null`; `ConvertFrom-Json` instead of `python -m json.tool` when piping JSON. **`&&` and `||` chain operators are parser errors in PowerShell 5.1** — split into separate commands or use `; if ($?) { ... }` for conditional chaining; never put multiple install/setup commands in one block with `&&`. For Python projects managed with `uv`: use `uv pip install` not bare `pip` — `pip` is typically not on PATH in uv environments. See `.claude/rules/windows-shell.md` for the full landmine list.
- **bash / POSIX:** standard syntax, but on Windows hosts `gh.exe` and other native tools may not resolve POSIX paths — write temp files under `$TEMP` or an absolute Windows path.

If the target shell is ambiguous, default to PowerShell-safe syntax (no bash-isms) and note the assumption explicitly. A shell block that fails on the first operator run is worse than a verbose one.

If a step has no human-verify (everything is machine-checkable), omit the **Verify (human)** block and shrink **Action (human)** to "do the thing, then say 'done'". If a step has no human-action either, the whole step is a candidate for moving out of the UAT into an integration test.

### Step 4 — Surface cross-step issues

Some problems are not per-step:

- **Ordering dependencies** that aren't stated (step 3 assumes step 2's state).
- **Implicit teardown** that wasn't done (rate limiter still locked from step 4 leaks into step 5).
- **Missing reset path** between repeats (operator can't easily re-run from clean).
- **Coverage gaps** — features in the spec that no step exercises (e.g., "refresh during lockout" wasn't covered but the spec explicitly says it should work).

List these under a separate "Cross-cutting findings" section, grouped by severity.

### Step 5 — Output

Produce these, in this order:

1. **Findings, grouped by severity** (always print all three tiers — empty tiers print "None"):
   - **Blocker** — operator would do the wrong thing, get stuck, or report a false pass/fail. Cannot ship the UAT as-is.
   - **Gap** — operator could probably guess right, but shouldn't have to. Tighten before next handoff.
   - **Minor** — cosmetic, low-stakes, or coverage nice-to-have.
2. **Refined UAT** — the rewritten steps in the canonical format, in a fenced markdown block so the user can copy it back into the plan doc.
3. **Diff summary** — one line per original step: "Was: ... → Now: ..." with the most important change.

### Step 5.5 — Delegated execution (if `--exec` was passed)

Execution is [`/user-uat`](../user-uat/SKILL.md)'s whole job — this skill owns refinement only, and keeps zero execution procedure of its own. After producing the Step 5 output, hand the refined script off:

1. **What gets handed off:** the refined UAT from Step 5's fenced block. Invoke `/user-uat` via the Skill tool on it — bare (user-uat's default source is the UAT block just produced in this conversation), or as `path#anchor` when `--apply` already wrote it back to the source doc.
2. **Flag pass-through** (map only flags both skills actually declare; invent none):
   - `--exec --dry-run` → `/user-uat --dry-run` (user-uat classifies + prints what WOULD run; nothing executes).
   - Refined script contains `Verify (visual — vision-judge)` blocks → add `--ui`, so those steps are vision-judged via `/judge-ui` instead of escalated.
   - `--deep` and `--yes-side-effects` are user-uat flags with no review-uat equivalent — never pass them implicitly; user-uat's own defaults stay in force (see [`/user-uat`](../user-uat/SKILL.md)). An operator who wants them invokes `/user-uat` directly.
3. **What comes back:** user-uat's terse per-step report (`step → AUTO-PASS / AUTO-FAIL / ESCALATED → one-line evidence`) plus its "Needs you" section. Relay it verbatim — do not re-judge, re-run, or summarize away the evidence.

The execution procedure itself — tier partition, side-effect gating, mechanical auto-judging, stop-on-FAIL, escalation format — is owned by `/user-uat`; look there, not here.

### Step 6 — Clarifying-questions loop

After the output, check whether any findings need user input to resolve. Common cases:

- Genuine product decisions (does "wipe" mean PIN-row delete or full factory reset? — only the user can decide which one M2.5 should test).
- Ambiguous pass criteria with multiple defensible answers (does "expect setup screen" mean "renders eventually" or "renders within 200ms with no flash"?).
- Missing context that only the user can provide (which environments / browsers / accounts).

If there are clarifying questions:

1. End with a numbered list under a **Clarifying questions** heading.
2. Wait for answers.
3. After receiving answers, update the refined UAT to absorb them. If `--apply` was set, also write the result back to the source plan doc and report which file:line ranges changed.

If there are NO clarifying questions:

- End with: "No clarifying questions — refined UAT above is final. Run with `--apply` to write back to <source path>."

---

## Heuristics: common ambiguities to look for

These are the patterns that recur. Treat them as a checklist when scanning a draft.

| Pattern | Example | Tighten by |
|---------|---------|-----------|
| **Verb without object** | "wipe", "reset", "clear" | Specify the exact command / scope |
| **State noun without check** | "fresh boot", "clean state" | Specify what artifacts must / must not exist |
| **"Expect X"** | "expect setup screen" | Specify the observable: heading text, test id, URL, accessible role |
| **Loose number** | "5 wrong PINs" | Specify pacing (how fast?), order (matters or not?), and whether the 5th attempt itself is the lockout trigger |
| **Time-based assertion** | "15-min lock with countdown" | Specify what ticks, at what cadence, and how the operator confirms it (clock-watch? screenshot? log timestamp?) |
| **Implicit restart** | "first boot after wipe" | State the restart explicitly; call out which in-process state resets with it |
| **Implicit network / fixture state** | "type a PIN" | Note that the backend must be reachable, the frontend dev server must be up, the proxy must be wired |
| **Verification on faith** | "PIN survives refresh" | Specify the second observation (status probe returns `pin_set: true`) AND the first (token gone from store) |
| **Off-the-happy-path silence** | spec mentions "lock takes precedence" but UAT doesn't test it | Add the negative-path step explicitly |
| **Shell-platform mismatch** | `curl -s -o /dev/null -w "%{http_code}"` in a PowerShell context | Identify target shell first; on Windows/PS use `curl.exe` not `curl`; verify flags are valid for that shell's native tools |
| **`&&` in PowerShell 5.1** | `pip install A && pip install B` | `&&` is a parser error in PS 5.1; put each command in its own fenced block; never chain installs with `&&` |
| **Wrong package manager** | `pip install X` in a `uv`-managed project | `pip` is typically not on PATH; use `uv pip install X` instead |

---

## Principles

- **Refine, don't expand.** A tighter 4-step UAT is better than a fuzzy 12-step one. If the original under-specifies, fix the wording — don't bolt on extra checks the original didn't intend.
- **Cite the spec.** Every pass criterion should trace to a line in the plan, the code, or the spec. If it doesn't, the criterion may be invented.
- **Agent-run setup is free.** Use it generously. The human's time is the scarce resource; offload everything mechanical.
- **The agent does the verification too.** Setup is the obvious agent-doable part; verification is the less obvious one. If the spec says "X exists in the DB", the agent reads the DB. The human's verify list should shrink to things that genuinely require eyes on a screen.
- **Pass criteria are observations, not interpretations.** "Setup screen renders" is an interpretation. "Heading reads 'Set parent PIN' and two PIN input fields are visible" is an observation.
- **Negative-path coverage matters.** A UAT that only tests the happy path will miss invariants like "lock takes precedence over correct PIN."
- **Fresh-eyes test.** When done, ask yourself: could a Claude session with no prior context execute this? If not, keep tightening.

---

## What NOT to do

- **Do not run the UAT yourself — ever.** Default is refinement only. With `--exec`, execution happens by delegating the refined script to `/user-uat` (Step 5.5); this skill never executes Setup/Verify blocks inline and never runs human-action steps for the operator.
- **Do not write a UAT from scratch.** Refuse and point at the relevant `--ui` test conventions or existing M-steps for patterns. Exception: when the "draft" is a set of scattered references inside other steps' status notes, gathering those into one block is consolidation, not invention — but label the output as "drafted + refined from scattered status notes" rather than pretending it was pure refinement.
- **Do not modify the source plan doc** unless the user passed `--apply`. Default is propose-in-chat only.
- **Do not invent pass criteria.** If the spec doesn't define what "good" looks like, that's a clarifying question for the user — not a guess.
- **Do not delete coverage.** If the original draft tests something the refinement can't ground, flag it as a Blocker, don't drop it.
- **Do not mass-rewrite tone or voice.** Tighten ambiguity; preserve the author's framing.
- **Do not punt verification to the human when an agent can do it.** "Check the row exists", "confirm the file is on disk", "verify the API returned 200" are HTTP probes / sqlite queries / Read-tool calls — not human tasks. Reserve human-verify for visual / auditory / subjective judgment. Default verify is agent; human-verify needs justification.

---

## Interaction with other skills

- **`/user-uat` + `/judge-ui`** — the executors for what this skill writes: review-uat REFINES, user-uat EXECUTES, and `--exec` is refine-then-delegate (Step 5.5 invokes `/user-uat` on the refined script via the Skill tool). `review-uat` *emits* the `Verify (visual — vision-judge)` blocks; `/user-uat --ui` *runs* them via the `/judge-ui` engine (drives the screen, vision-judges it, cross-checks a read-back), reserving `Verify (human)` for motion / audio / feel. Refine here → execute there.
- **`/plan-wrap`** — same family (self-sufficiency check), but for plans, not UATs. Use both: plan-wrap on the plan, review-uat on its M-steps.
- **`/user-draft`** — overlapping ambiguity-hunting discipline; the heuristics table here borrows from user-draft's "weak verbs" finding.
- **`/plan-review`** — the build-step counterpart. plan-review covers what gets built; review-uat covers what humans verify after build.
- **`/repo-update`** — if the refined UAT gets applied (`--apply`), repo-update is the natural follow-up to commit + push the doc change.
- **`/user-walkthrough`, `/user-shakedown`** — the sibling operator-acceptance modes. `/review-uat` REFINES a fuzzy script; `/user-walkthrough` lets the operator DRIVE exploration of a fresh build (agent answers from source, fixes small, logs big); `/user-shakedown` AUTONOMOUSLY CLOSES the resulting ledger to zero open items. Refine a script with review-uat; poke a build with the walkthrough/shakedown pair.

---

## Future iterations (placeholder — to be expanded)

This is v1. Likely additions as the skill matures:

- A library of project-specific "what does '<term>' actually mean" definitions, sourced from operator runbooks (e.g., toybox's "wipe" → recovery-table row 1).
- Auto-generated agent-driven setup scripts for the common UAT prereqs (PIN reset, breaker reset, fresh DB).
- Coverage-gap detection by cross-referencing the spec's "Notable" lines against the UAT step list.
