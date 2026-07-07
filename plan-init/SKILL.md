---
name: plan-init
description: Guide the creation of a new project plan.md through a structured conversation. Asks the right questions up front — stack, auth, data storage, async patterns, build tooling, UI — before writing anything. Use at the start of any new project to avoid mid-plan discovery of architectural gaps.
user-invocable: true
---

# Plan Init

Run a structured planning conversation and produce a complete `plan.md` for a new project.
The goal is to surface all architectural decisions *before* writing the plan, so the
document is correct on the first pass rather than requiring a review cycle to patch gaps.

## Greenfield check

Before walking through the 7 conversation phases, confirm this is a
**greenfield** project. Run `git log --oneline | head -1` in the project
directory — if it returns any commit, STOP and recommend `/plan-feature`
instead. `/plan-feature` reads the existing codebase before drafting;
`/plan-init` does not, and using it on a project with committed code risks
proposing data models that conflict with the live schema (Phase 2 entities,
Phase 4 stack choices get answered from imagination rather than from the
existing producing files — see plan-init deep-dive investigation #17).
`/plan-init` is for wholly new projects with no committed code, no schema,
and no existing module structure. If uncertain (e.g., the directory has
stray files but no real codebase), ask the operator to confirm "greenfield"
before proceeding.

## Pipeline position

`/plan-init` is Step 1 of the plan pipeline:
`plan-init or plan-feature → plan-review → plan-wrap → repo-sync → build-phase`.
Always run `/plan-review` and `/plan-wrap` on the produced plan BEFORE
`/repo-sync` mints GitHub issues — a gap caught after sync is an
**N+1-edit** problem (1 plan-doc fix + N issue-body edits in GitHub to keep
the sync intact), whereas the same gap caught pre-sync is a single plan
edit. `/plan-expedite` is the autonomous pre-flight meta-skill that chains
`plan-review-autofix → plan-wrap-autofix → repo-sync → session-wrap` so
`/build-phase` gets a clean, sync'd plan to walk; operators in autonomous
mode should invoke `/plan-expedite --plan <path>` immediately after
`/plan-init` finishes. Close every `/plan-init` session by surfacing the
next step explicitly to the operator — e.g., "Plan written to <path>. Next:
run `/plan-expedite --plan <path>` to auto-prep, or `/plan-review` if you
want manual review first."

## Conversation phases

Work through these phases in order. Ask the questions as a conversation — not all at once.
Group related questions together. Listen for implied answers (e.g. "it's a local tool"
implies no cloud deployment, no multi-user auth). Do not ask questions the user has already
answered.

**If the user front-loads many answers in their first message**, still walk through every
phase explicitly: summarize what you understood for that phase, confirm it, and ask about
any gaps. This ensures all 7 phases are covered even when the user provides a dense
initial description.

---

### Phase 1 — Purpose and scope

- What does this project do in one sentence?
- Who uses it (just you, a small team, public users)?
- Is this a local tool, a hosted service, or a CLI?
- What is explicitly out of scope for the first version?

---

### Phase 2 — Data

- What entities does the system create or track? (jobs, users, documents, events…)
- How is each entity identified? (UUID, hash, slug, file path, composite key…)
  Pin down a concrete format — never leave IDs as generic placeholders.
- Where does that data live? (flat files, SQLite, Postgres, in-memory, external API…)
- Does any data come from an external source? If so, what and how (API, scrape, upload)?
- How should the system handle duplicate or re-processed data?
- Are there any files the user provides as input (JSON, CSV, audio, video)?

---

### Phase 3 — AI and external services

- Does this project call any AI models? Which ones?
- How is auth handled for those services? (API key, OAuth token, subscription CLI…)
- Are there any other third-party APIs or services involved?
- What happens if an external service is unavailable or returns an error?

---

### Phase 4 — Stack and build

- What language(s) and runtime(s)?
- Frontend: web UI, CLI, none? If web — framework preference?
- Backend: needed? If so — framework preference?
- How should the project be tested? (unit, integration, e2e — which matter most?)
- Any existing tooling or patterns from other projects to reuse?
- Read producing files first for any external artifact the plan will reference
  (library API, third-party CLI flag, sibling skill's SKILL.md, cross-project schema)
  — quote real values verbatim into the plan, don't trust docs or memory.

---

### Phase 5 — Async and concurrency

- Are there any long-running operations (crawls, AI calls, file processing, uploads)?
- Should those run in the background while the user does other things?
- If yes — how does the user know when they're done? (polling, notification, progress bar…)
- **Does this system run autonomously, on a schedule, or in any "always-on" mode?**
  If yes, ask the end-to-end validation follow-ups:
  - How will you know the autonomous loop works end-to-end, not just that each
    component passes unit tests? (Unit tests prove components work in isolation,
    not together over time.)
  - Will there be a deliberate observation phase where the full system runs with
    realistic inputs for long enough to expose time-dependent behavior (memory
    leaks, cumulative drift, alert thresholds, race conditions, scheduled-task
    triggers firing wrong — invisible to short test runs)?
  - If the answer is "we'll just run it after we're done and see," surface that
    as an explicit build step (e.g. "Step N: Soak test — run for 4 hours,
    observe, document findings") so it cannot be skipped.
  - This applies to any cron job, watcher, polling loop, or scheduled task —
    not just AI projects.

---

### Phase 6 — Auth and secrets

- Does the app have any concept of user login or sessions?
- What secrets does it need (API keys, tokens, passwords)?
- How should secrets be stored and loaded?

---

### Phase 7 — Development process

- Should this use `/build-phase` (multi-step orchestrator) for building?
- For each step, what `/build-step` flags make sense?
  - `--isolation`: `worktree` (default, fast) or `docker` (clean-room isolation)
  - `--reviewers`: **Default: `--reviewers code` for build steps.**
    `--reviewers code` runs the 4-agent code-review gauntlet (correctness,
    bugs, test quality, style) plus automated typecheck / lint / test gates
    — safe and fast for backend, library, and pure-docs / JSON changes.
    Escalate only when the step has a real runtime/UI surface to validate.
    Values:
    - `code` (default) — 4-agent diff review + gates. Use for backend
      logic, libraries, docs, scripts, JSON / YAML config edits, and
      unit-test-only changes.
    - `runtime` — 3 evidence-based agents (UI / backend / frontend).
      Requires `--start-cmd` + `--url`. Use when the step changes
      visible UI behavior with no backend logic.
    - `full` — all 7 agents (4 code + 3 runtime). Requires `--start-cmd`
      + `--url`. Use for full-stack steps spanning backend logic AND
      visible UI in the same change.
    - `auto` — gates only (no agent reviewers). Use for fast scaffolds
      or mechanical wiring where the test suite is the entire reviewer.
    - **Auth-gate downgrade:** if a step's `--url` points behind a PIN,
      login screen, session-bound token, or any auth flow a fresh
      Playwright session cannot satisfy, DOWNGRADE from `runtime` /
      `full` to `code` — the runtime reviewers cannot reach the URL,
      every screenshot shows the gate not the feature, and the step
      enters silent false-pass mode (Toybox K17 wasted ~50 minutes
      before the PIN gate was identified). Pair with `--exercise-cmd`
      that injects auth state (e.g., a Playwright snippet that does
      `localStorage.setItem('PIN', '1234')` before evidence capture)
      ONLY if such a script exists; otherwise downgrade.

    Rationale: `.claude/rules/plan-and-issue-flow.md § Reviewer flag must
    match step shape` (anchors: `feedback_plan_reviewer_flags.md`,
    `feedback_runtime_reviewers_skip_on_auth_gated_substrate.md`).
  - `--ui`: add if the step needs Playwright screenshots/evidence
- What are the natural step boundaries? (Size each step as one vertical slice — see `../../references/step-authoring.md` §1; don't over-split a coherent slice.)
- **Are there any manual checks, observation periods, or operator-driven
  verifications that must happen AFTER the automated build steps complete?**
  (E.g., visual UI spot-checks against a real client; a soak test the operator
  runs unattended; integration testing against a live external service.)
  Surfacing these up-front lets the produced plan split its Build Steps into
  labeled `Automated Steps` + `Manual Steps` subsections from the first draft,
  with named `M1`/`M2`/`M3` handoff entries — rather than mixing operator/wait
  steps into the automated numbering and forcing a re-shape later.
  All-automated plans skip the split. See output spec section 11 below for the
  template.
- **For any step identified as `Type: conditional`** (i.e. only runs if a predicate
  from a prior step is true), ask the operator:
  "What shell command can the orchestrator run to decide whether this step should
  execute? (Exit 0 → run; non-zero → skip. Use bash syntax — predicates are
  evaluated via `bash -c \"<expr>\"`.) If you don't know yet, I'll write a
  placeholder you can fill in later."
  The answer becomes the step's `**Condition:**` value. If the operator does not
  yet know, write the placeholder described in the plan-format section below
  rather than omitting the field.

---

## After the conversation

Once phases 1–7 are complete, produce `plan.md` with these sections.
Every numbered section below is **required** — adapt the *depth*, not the presence.
For example, a CLI tool with no database still gets a Data Store section describing how it
reads and writes data (filesystem layout, file formats). Only section 4 (domain-specific)
and section 6 (API Route Contract) may be omitted when genuinely not applicable.

1. **What This Is** — one-paragraph description
2. **Stack** — table of layer / tool / why
3. **Data Store** — schema, file layout, deduplication, corruption protection
4. **[Domain-specific sections]** — e.g. Candidate Profile, Core Loop, etc.
5. **Modules** — one subsection per `src/` directory with file-level descriptions
6. **API Route Contract** — full table if there is a backend API
7. **Project Structure** — annotated directory tree
8. **Key Design Decisions** — one paragraph per major decision with rationale
9. **Open Questions / Risks** — table with item / risk / mitigation
10. **How to Run** — step-by-step quickstart from clone to working app
11. **Development Process** — describe the build approach (e.g. `/build-phase`
    + `/build-step` flags, reviewer gates, isolation choices), then list the
    ordered build steps in `/build-phase`-compatible format:
    ```
    ### Step N: <name>
    - **Problem:** <what to build or fix — becomes the --problem arg>
    - **Type:** code | operator | wait | conditional   (default "code", omit if code)
    - **Condition:** <shell-expression>   (required when Type: conditional — see below)
    - **Issue:** #<N> (leave blank — created later by /repo-init or /repo-sync)
    - **Flags:** <build-step flags, e.g. --reviewers code --isolation worktree>
    - **Produces:** <files, behavior>
    - **Done when:** <specific test or verification>
    - **Depends on:** <step numbers, or "none">
    ```
    If no flags are needed, omit the Flags line (build-step defaults apply).
    Size each step as one vertical slice (`../../references/step-authoring.md` §1). Phrase
    `Done when:` however makes it falsifiable — EARS (`WHEN … SHALL …`) and Given/When/Then
    are OPTIONAL examples (`../../references/step-authoring.md` §2), never required grammar.
    Use `Type: operator` for manual smoke tests / observation work that won't
    produce a code diff. Use `Type: wait` for long-wall-clock observation steps
    (soak tests, benchmarks). Use `Type: conditional` for steps that only run
    if a predicate from a prior step is true.

    **`Type: operator` steps must not produce code artifacts.** If a step is
    declared `Type: operator`, its `Produces:` field must NOT include
    code-shaped artifacts:
    - `.py`, `.ts`, `.tsx`, `.js`, `.sh`, `.rs`, `.go` source files
    - `.json`, `.yaml`, `.toml` configs shipped in `src/` or `scripts/` or any
      package directory the project's build tooling reads
    - `.md` ops docs that depend on code-state (under `documentation/operator/`
      or similar)

    If a step would naturally produce both an operator action AND a code
    artifact, SPLIT into two adjacent steps: `N-prep` (Type: code) authors the
    artifact via the standard `/build-step` flow, and `N` (Type: operator)
    runs the manual checks. **Symmetric inverse:** if a step is declared
    `Type: code` but its `Done when:` field requires an operator visual
    review or manual confirmation (e.g., "operator visually reviews",
    "operator runs and confirms", "operator inspects output"), apply the
    same split in reverse — `N-prep` (Type: code) covers the automatable
    portion and `N` (Type: operator) covers the manual verification.
    Otherwise `/build-phase` halts mid-run asking the operator to do
    code/operator work the plan didn't budget for.

    Split pattern:

    ```markdown
    ### Step N-prep: <code work, author the artifact>
    - **Problem:** <author the script / helper / config>
    - **Type:** code
    - **Produces:** <code-shaped artifacts>
    - **Done when:** <automated gates pass>

    ### Step N: <operator action>
    - **Problem:** <run the artifact + manual checks>
    - **Type:** operator
    - **Produces:** <run output / observation log>
    - **Done when:** <operator confirms>
    ```

    **Step field reference — `**Condition:**`:**

    - **Condition:** `<shell-expression>` — required when `Type: conditional`.
      Build-phase evaluates this predicate via `bash -c "<expr>"` at
      step-dispatch time. Exit 0 → run the step; non-zero → skip with
      `Status: SKIPPED (condition false)`. Steps with `Type: conditional`
      lacking this field are pre-flight Blockers caught by `/plan-review` §23
      and `/plan-wrap` §12.

    Worked example of a conditional step:

    ```markdown
    ### Step 5: Fix blockers and re-soak
    - **Problem:** Address blockers found in Step 4 triage
    - **Type:** conditional
    - **Condition:** test -s documentation/findings/step-4-blockers.md
    - **Issue:** #65
    ```

    If the operator does not yet know the predicate during the planning
    conversation, emit `**Condition:** <shell command returning exit 0 to run,
    non-zero to skip>` as a placeholder. The operator (or
    `/plan-review --autofix` once Step 7 of the BPA plan lands) fills in the
    real predicate later. The placeholder is NOT considered "empty" by the
    upstream §23/§12 checks — it is a valid intermediate state.

    **Mixed-type plans split Build Steps into Automated + Manual subsections.**
    If the plan has any `Type: operator` or `Type: wait` steps mixed with
    `Type: code` steps, render Build Steps as two labeled subsections —
    `### Automated Steps` (all `Type: code` / `Type: conditional` / `Type: wait`
    steps that `/build-phase` walks unattended, numbered `1..N`) and
    `### Manual Steps` (operator-driven verifications that run AFTER
    `/build-phase` completes, named `M1`/`M2`/`M3`...). Each manual entry
    carries a `**Commands:**` code-fence block (copy-paste-ready) and a
    `**What to look for:**` table with `Check | Expected outcome` columns —
    keeping the commands separate from the checks so the operator can paste
    without scanning past prose. Close the section with an explicit handoff
    cue (e.g., the closing line of `/plan-init` and the orchestrator's
    end-of-phase report both surface "Please run M1 next." rather than
    dropping the command in passing prose).

    All-automated plans (no `Type: operator` / `Type: wait` steps) skip the
    split — render Build Steps as a flat numbered list, no subsection headers
    required.

    Sub-template:

    ````markdown
    ## Build Steps

    ### Automated Steps
    (These run unattended via /build-phase.)

    ### Step 1: <name>
    - **Problem:** ...
    - **Type:** code
    - **Issue:** #...
    - **Flags:** --reviewers code
    - **Produces:** ...
    - **Done when:** ...
    - **Depends on:** ...

    ### Step 2: <name>
    ... (all code/wait/conditional steps numbered 1..N)

    ### Manual Steps
    (These run after /build-phase completes. Operator drives.)

    ### Step M1: <name>
    - **Source step:** Step 5 (from §6 Build Steps)
    - **Issue:** #...
    - **Commands:**
      ```powershell
      <copy-paste-ready commands>
      ```
    - **What to look for:**
      | Check | Expected outcome |
      |---|---|
      | <check 1> | <outcome 1> |

    ### Step M2: <name>
    ... (each manual step numbered M1, M2, M3, ...)
    ````

    Closing handoff cue: after all Automated Steps complete, the orchestrator
    prints `Please run M1 next.` to surface the first manual handoff
    explicitly — not as ambiguous prose ("the slow run is X") that leaves the
    operator guessing whether the orchestrator already verified or wants a
    human to. Rationale: `.claude/rules/plan-and-issue-flow.md § Automated vs
    manual split` (anchors: `feedback_plan_auto_vs_manual_sections.md`,
    `feedback_name_manual_verification_handoff.md`).
12. **Appendix** — schema summaries, profile structures, or other reference material
    a clean-context model would need

## Quality bar before saving

Before writing the file, verify:

- Every "X or Y" choice from the conversation is resolved to a single answer with rationale.
- Every entity has a defined ID format (UUID, hash, slug — not just `<id>`).
- Every external file or schema referenced in the plan is summarized inline.
- **Every reference to an external artifact — a library API, third-party tool
  CLI, sibling skill's SKILL.md, or shared schema from another workspace
  project — was sourced by reading the producing file verbatim, not from docs
  or memory.** Quote the actual value (the real CLI flag, the real schema
  field name, the real `package.json` script) into the plan with a file-path
  citation, or mark it as TBD if unknown. Even on greenfield projects, plans
  typically reference at least a few existing artifacts the project will
  reuse — those references must come from the producing file. Rationale:
  `.claude/rules/plan-and-issue-flow.md § Read producers before drafting plan
  content` + `feedback_plan_read_producer_first.md`.
- A fresh model with no conversation history could read the plan and start building.
- **If the project has any autonomous, scheduled, background, or "always-on" behavior,
  the Build Steps section includes at least one explicit step dedicated to end-to-end
  observation** (run the system for a target duration, capture findings, triage). Unit
  tests on each component are not enough for systems whose value depends on running
  unattended. If Phase 5 surfaced autonomous behavior but the build steps are all
  component-implementation steps with no observation phase, add one before saving.
  **This rule has NO per-request escape hatch.** If Phase 5 surfaced any background
  work — even per-request task offload (FastAPI `BackgroundTasks`, Celery `.delay()`,
  RQ enqueue, `asyncio.create_task` fire-and-forget, thread-pool submit) — the plan
  STILL needs a dedicated end-to-end observation step. For always-on / scheduled work,
  name it e.g. "Step N: Soak test — run for 4 hours, capture findings". For per-request
  background work, name it e.g. "Step N: Observation run — exercise the background task
  happy path AND error path end-to-end (10 real invocations), capture timing + failure
  findings" with a target duration (e.g. 15 minutes) and a `capture findings`
  deliverable. The step must be DISTINCT from any component-implementation step —
  not folded into a "build the worker" step's `Done when:`. Rationale: per-request
  background tasks still hide time-dependent failures (queue backpressure, task
  cancellation on shutdown, silent exception-swallowing inside the executor) that
  unit tests on the producer endpoint miss.
- **If the project has a data pipeline (producer → consumer chains, schema-bound
  storage, env→model→storage flows, or any "the dimensions/shape/columns must agree
  across modules" coupling), the Build Steps section includes at least one explicit
  smoke-gate step BEFORE any long-running observation step.** A smoke gate is a
  60-second end-to-end run with REAL components wired together (no mocks), exercised
  just enough to surface producer/consumer drift. It is NOT the same as the
  observation phase — observation phases are hours long and document behavior;
  smoke gates are seconds long and surface schema/shape/wiring bugs that unit tests
  with mocks miss because each test mocks the boundary it would have asserted on.
  Example: "start the service, send 1 real request, assert no exception." Mark with
  `Type: operator` if it requires manual setup, otherwise `Type: code` with a
  shell-script test. The smoke gate's deliverable is "the pipeline can complete
  one real cycle without crashing" — pass/fail of any business logic is out of scope.
- Every `Type: operator` step's `Produces:` field is free of code-shaped
  artifacts (`.py`/`.ts`/`.js`/`.sh`/`.json`-or-`.yaml`-or-`.toml`-under-`src/`-or-`scripts/`/code-dependent
  `.md`). Steps that would naturally produce code AND require operator action
  are split into `N-prep` (code) + `N` (operator). Anchor: Toybox Phase M
  Step M2 mid-build-phase halt. See `.claude/rules/plan-and-issue-flow.md
  § "Operator-type steps must not produce code artifacts"`.
- Every `Type: code` step's `Done when:` field is automatable (no "operator
  visually reviews" / "operator runs and confirms"). Steps that mix
  automatable code completion with operator confirmation are split into
  `N-prep` (code) + `N` (operator). Symmetric to the operator+code-Produces
  rule above.
- Each step is one vertical slice (fits one agent context, one observable behavior via its production caller, no "and" to describe) per `../../references/step-authoring.md` §1 — neither too big nor over-split.
- If the plan has any `Type: operator` or `Type: wait` steps mixed with
  `Type: code` steps, the Build Steps section labels them under a Manual
  subsection separate from the Automated subsection, with named
  `M1`/`M2`/`M3` handoff entries (each containing a `**Commands:**`
  copy-paste block + a `**What to look for:**` Check | Expected outcome
  table) — and the plan's closing convention is a "Please run M1 next" cue.
  All-automated plans skip the split (no defect). Rationale:
  `feedback_plan_auto_vs_manual_sections.md` +
  `feedback_name_manual_verification_handoff.md`.

Run `/plan-wrap` on the draft before saving if any of the above is uncertain.

---

## After plan.md exists — bootstrap CLAUDE.md

A fresh project also needs a `CLAUDE.md` so any future session opens with the
right context without having to re-derive stack, layout, and commands from
scratch. Write one immediately after saving `plan.md` (skip if a `CLAUDE.md`
already exists — the user already owns the file).

Include all seven sections. Pull values directly from the plan conversation — every field below has an answer from phases 1–7.

1. **Project overview** — one or two sentences from Phase 1 (purpose + scope).
2. **Stack summary** — table from the plan's "Stack" section (Phase 4).
3. **Key commands** — install / run / test / lint / typecheck. Use the actual
   commands for the chosen tooling (e.g., `uv sync`, `uv run pytest`,
   `ruff check`, `mypy`). Don't write placeholders.
4. **Directory layout** — annotated tree matching the plan's "Project Structure" section.
5. **Architecture summary** — layers, key modules, patterns. One paragraph per layer, max.
6. **Current state** — at bootstrap this is "Plan written, no code yet." Update at the end of each phase via `/repo-update`.
7. **Environment requirements** — OS, runtimes, external services (SC2, Docker,
   specific Python/Node versions, API keys). Anything that would block a fresh
   clone from running the project.

Save to `CLAUDE.md` at the project root.

Report at the end of plan-init: "plan.md written (N sections) · CLAUDE.md bootstrapped (7 sections)".


---

## dev-observatory hook (additive; see [`.claude/rules/descriptor-contract.md`](../../rules/descriptor-contract.md))

On creating a new **owned** project, register it with the control plane so its ownership + tier become real (until registered, dev-observatory treats a tree as `owned=false`/write-blocked):

```
uv run --project dev-observatory observatory register <slug> --owned --path <rel-path>
```

Keep the new `CLAUDE.md`'s `## Commands`/`## Stack`/port mentions scrapable and the plan's objective clearly labeled (a `## 1. What This Is` section) so dev-observatory's verb + goal-vs-reality scrape works.
