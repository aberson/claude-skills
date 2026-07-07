---
name: plan-feature
description: Plan a new feature, phase, or significant change for an existing project. Reads the codebase and existing docs first, then runs a focused conversation to produce a scoped plan document at documentation/<feature>-plan.md. Use when adding capabilities to a project that already has code and architecture in place.
user-invocable: true
---

# Plan Feature

Run a structured planning conversation for a new feature or phase in an **existing** project,
then produce a scoped plan document. Unlike plan-init (greenfield), this skill starts by
reading what already exists so questions focus only on the delta.

## Invocation

```text
/plan-feature [optional: feature name or one-liner]
```

If the user provides a feature name or description inline, use it to seed Phase 2
and skip redundant questions.

## Pipeline position

Step 1 of the plan pipeline:
`plan-feature → plan-review → plan-wrap → repo-sync → build-phase`.
`/plan-expedite` autonomously chains the three intermediate stages
(`plan-review-autofix → plan-wrap-autofix → repo-sync → session-wrap`) so
`/build-phase` gets a clean, sync'd plan to walk. Always surface the
closing-message contract below so the chain can't be skipped accidentally.

After writing the plan file, end your turn by surfacing the recommended next
move: the produced plan must pass `/plan-review` and `/plan-wrap` BEFORE
`/repo-sync` mints GitHub issues — a gap caught after sync is an
**N+1-edit** problem (1 plan-doc fix + N issue-body edits). The autonomous
chain that handles this for you is
`/plan-expedite --plan documentation/<slug>-plan.md`, followed by
`/build-phase --plan documentation/<slug>-plan.md` once `/plan-expedite` returns
READY.

## Before the conversation — auto-discovery

Before asking anything, silently read and internalize:

1. **Producing files for any value the feature will reference** — open the
   actual source file (schemas, CLI flags, package scripts, endpoint paths,
   config values) BEFORE drafting the plan, not the docs that describe them.
   Stale docs are a recurring source of plan-level Blockers: wrong reward
   schema, missing API response shapes, `npm start` vs `npm run dev` have all
   bitten prior phases. Examples of what to read first: `rewards.py`,
   `package.json` scripts section, `pyproject.toml` dependencies, the actual
   route handler (not just the OpenAPI doc).
2. **Project docs** — README, CLAUDE.md, AGENTS.md, any existing `documentation/*.md` plans
3. **Master plan or multi-phase architecture document** — if the project has
   a master plan or roadmap defining its phase sequence (common shape: a
   `documentation/master-plan.md` or top-level architecture doc that splits
   work into Phase 1, 2, 3, …), locate the section for the phase you're
   planning and extract: scope boundaries already decided, design decisions
   already made upstream, and **the step-number range reserved for prior
   phases** (so this feature's build steps continue where the master plan
   expects rather than restarting at Step 1). Step-number collisions across
   sibling plans corrupt `/repo-sync` issue bodies — see
   `feedback_repo_sync_step_collision.md` for the failure mode.
4. **Project structure** — top-level directory tree, `src/` layout, test layout
5. **Existing patterns** — imports, frameworks, test tooling, build config (`pyproject.toml`,
   `package.json`, `Cargo.toml`, etc.)
6. **Git state** — current branch, recent commits (last 10-15), any open work
7. **Memory** — check project memory files for active work, past decisions, gotchas

This gives you the project baseline. Do NOT ask the user to re-explain things the code
already answers (language, framework, database, test runner, etc.).

## Conversation phases

Work through these phases in order. Ask questions as a conversation — group related ones,
skip what you already know from auto-discovery, and listen for implied answers.

**If the user front-loads many answers**, still walk through every phase: summarize what
you understood, confirm it, and ask about gaps.

---

### Phase 1 — Existing landscape

Summarize what you learned from auto-discovery in 3-5 bullet points:
- Project purpose and current state
- Key modules and their responsibilities
- Relevant existing patterns, conventions, or constraints
- Any active work or recent changes that might interact

**Cite the producing file each bullet came from** — e.g., "per `rewards.py`",
"per `package.json` scripts" — not "per the README". The README is allowed to
be stale; producing files are not.

Ask: "Does this summary look right, or is anything stale/missing?"

---

### Phase 2 — Feature goal

- What does this feature do in one sentence?
- Who benefits (same users, new users, developers, CI)?
- What is explicitly out of scope for this feature?
- Is there a triggering event — user request, bug, tech debt, new requirement?

---

### Phase 3 — Impact analysis

Based on the feature goal and your knowledge of the codebase:

- Which existing modules will be modified?
- What new modules or files need to be created?
- Are there any existing patterns this should follow (e.g. "add a new command like the
  existing ones in `src/commands/`")?
- Does this feature touch shared code that other features depend on?
- Any migration or backwards-compatibility concerns?
- **For each function signature, schema field, or shared constant being
  changed, grep ALL call sites in the codebase and list each in the impact
  table.** Don't trust "probably only file X uses this" without verifying.
  Anchor: Alpha4Gate Phase 4.6 Step 1 — an `SC2Env._game_id` shape change
  missed the `evaluator._get_game_result` consumer; 70-minute soak-4 DB
  forensics found the gap and cost a whole Phase 4.7 re-plan cycle. See
  `feedback_grep_all_downstream_when_fixing_key_shape.md`.

Present your analysis and ask the user to confirm or correct.

---

### Phase 4 — New design decisions

Only ask about decisions this feature introduces — not ones the project has already made.

- Does this feature need new data entities or schema changes?
- Does it introduce new external dependencies (APIs, libraries, services)?
- Are there new async/background operations?
- Are there new user-facing interfaces (CLI commands, API routes, UI pages)?
- Any new auth/permissions considerations?
- **Does this feature add or extend any autonomous, scheduled, background, or
  "always-on" behavior?** If yes:
  - How will you know the new behavior actually works end-to-end, beyond unit tests
    of each component? Time-dependent failures (cumulative drift, race conditions,
    scheduled-trigger logic, alert thresholds, integration with other autonomous
    components from prior phases) are invisible to short test runs.
  - Will the build steps include a deliberate observation phase where the full
    system runs with realistic inputs and is watched long enough to expose those
    failures? If not, surface this as a follow-up phase and flag it before saving.
  - This is especially important when the feature is observability infrastructure
    (dashboards, alerts, monitoring) for an existing autonomous system — it is
    very tempting to ship the observation tooling without ever actually running it
    against real autonomous behavior. Avoid that trap.
- Are there multiple valid approaches? If so, present options with tradeoffs and ask
  the user to pick.

Skip any category that genuinely doesn't apply.

---

### Phase 5 — Build steps

- **Step numbering inherits from the master plan when one exists.** If
  auto-discovery found a master plan / multi-phase roadmap, start this
  feature's step numbering in the range the master plan reserved for this
  phase — do NOT default to Step 1 if prior phases already used Steps 1-N.
  Step-number collisions across sibling plans break `/repo-sync` (see
  `feedback_repo_sync_step_collision.md`).
- What are the natural steps to build this feature? (Size each as one vertical slice — see `../../references/step-authoring.md` §1; don't over-split a coherent slice.)
- What order minimizes risk and maximizes testability at each step?
- Can any steps be built in parallel?
- What does "done" look like for each step? (specific test, behavior, output)
- What `/build-step` flags does each step need?
  - `--reviewers` **defaults to `--reviewers code`** in plans this skill
    produces. `code` runs the 4-agent gauntlet (correctness, bugs, test
    quality, style) over the diff — sufficient for backend logic, docs,
    scripts, and config edits. Escalate only when the step has a real
    runtime/UI surface to validate. Values:
    - `code` (default) — 4-agent diff review.
    - `runtime` — 3 evidence-based agents (UI / backend log / frontend).
      Requires `--start-cmd` + `--url`. Use when the step changes visible
      UI behavior.
    - `full` — all 7 agents. Requires `--start-cmd` + `--url`. Use for
      full-stack steps spanning backend logic AND visible UI.
    - `auto` — gates only (no agents). Use for mechanical scaffolding /
      wiring where the test suite is the entire reviewer.
    - **Auth-gate downgrade:** if the URL exposed by the step is behind a
      PIN, login screen, or any auth flow a fresh Playwright session
      cannot satisfy, downgrade `runtime`/`full` back to `code` — the
      runtime reviewers cannot reach the URL, so their evidence will be
      empty and they will produce false-negative blocks. Reference:
      Alpha4Gate Phase 4.6 reviewer-flag mismatch cost 2 iterations
      to correct `full` → `code` at `/build-phase` time.
    - **Decision tree for picking `--reviewers`:**
      1. Does the step expose a URL the reviewer could load? **No → `code`**.
      2. Is the URL auth-gated beyond a fresh Playwright session's reach?
         **Yes → `code`** (auth-gate downgrade).
      3. Does the step need clean-room isolation (environment pollution,
         OS-level installs)? **Yes → `--isolation docker`**.
      4. Does the step need Playwright UI evidence (screenshots / frontend
         logs)? **Backend-only → `code`. UI-only → `runtime`. Full-stack →
         `full`.**
  - `--isolation`: `worktree` (default, fast) or `docker` (clean-room isolation)
  - `--ui`: add if the step needs Playwright screenshots/evidence
- **For any step identified as `Type: conditional`** (i.e. only runs if a predicate
  from a prior step is true), ask the user:
  "What shell command can the orchestrator run to decide whether this step should
  execute? (Exit 0 → run; non-zero → skip. Use bash syntax — predicates are
  evaluated via `bash -c \"<expr>\"`.) If you don't know yet, I'll write a
  placeholder you can fill in later."
  The answer becomes the step's `**Condition:**` value. If the user doesn't yet
  know, write the placeholder described in the plan-format section below rather
  than omitting the field.
- **`Type: operator` steps must not produce code artifacts.** If a step is
  `Type: operator`, its `Produces:` must NOT include code-shaped artifacts
  (`.py`, `.ts`, `.tsx`, `.js`, `.sh`, `.json`/`.yaml`/`.toml` configs shipped
  in `src/` or `scripts/`, or `.md` ops docs that depend on code-state).
  Split into a `Type: code` prep step that authors the artifact + a
  `Type: operator` step that runs it. **Symmetric inverse:** if a step is
  `Type: code` but its `Done when:` requires an operator visual review or
  "operator runs and confirms", split the same way. Otherwise `/build-phase`
  halts mid-run asking the operator to do code/operator work the plan didn't
  budget for. Anchor: Toybox Phase M Step M2 — declared `Type: operator` with
  `Produces: scripts/generate_element_sprites.py + 14 canonical sprites`,
  forced `/build-phase` to halt mid-run. Split pattern:

  ```markdown
  ### Step N-prep: <author the artifact>
  - **Type:** code
  - **Flags:** --reviewers code

  ### Step N: <run the artifact + operator checks>
  - **Type:** operator
  ```

  See `.claude/rules/plan-and-issue-flow.md § "Operator-type steps must not
  produce code artifacts"` for the full rationale.

Propose a step order with flags and ask the user to adjust.

---

## After the conversation

Once phases 1-5 are complete, produce `documentation/<feature-slug>-plan.md` with these
sections. Every numbered section is **required** — adapt the depth, not the presence.

1. **What This Feature Does** — one-paragraph description, including why it's being built
2. **Existing Context** — brief summary of relevant existing architecture, modules, and
   patterns this feature builds on (so a fresh-context model can orient without reading
   the whole codebase)
3. **Scope** — what's in, what's explicitly out
4. **Impact Analysis** — table of existing files/modules affected. Required
   columns: `File`, `Change Type` (modify/extend/refactor/delete), `Reason`,
   and `Verified`. The `Verified` column records HOW the impact claim was
   confirmed (glob/grep + result) — for any function-signature, schema-field,
   or shared-constant change, the `Verified` entry must enumerate every call
   site found, not just confirm "file exists". Template:

   ```markdown
   | File | Change Type | Reason | Verified |
   |---|---|---|---|
   | src/foo.py | modify | adds method bar() | glob confirmed (12 lines, 3 callers grep'd) |
   | src/api.ts | extend | new route /widgets | grep'd routes table (1 caller updated) |
   ```
5. **New Components** — description of each new file/module/entity being introduced
6. **Design Decisions** — one paragraph per decision with rationale and alternatives
   considered
7. **Build Steps** — ordered list in `/build-phase`-compatible format:
   ```markdown
   ### Step N: <name>
   - **Problem:** <what to build or fix — this becomes the --problem arg>
   - **Type:** code | operator | wait | conditional   (default "code", omit if code)
   - **Condition:** <shell-expression>   (required when Type: conditional — see below)
   - **Issue:** #<N> (leave blank — created later by /repo-init or /repo-sync)
   - **Flags:** <build-step flags, e.g. --reviewers code --isolation worktree>
   - **Produces:** <files, behavior>
   - **Done when:** <specific test or verification>
   - **Depends on:** <step numbers, or "none">
   ```
   If no flags are needed, omit the Flags line (build-step defaults apply).
   Use `Type: operator` for manual smoke tests / observation work that won't
   produce a code diff. Use `Type: wait` for long-wall-clock observation steps
   (soak tests, benchmarks). Use `Type: conditional` for steps that only run
   if a predicate from a prior step is true.

   **Step field reference — `**Condition:**`:**

   - **Condition:** `<shell-expression>` — required when `Type: conditional`.
     Build-phase evaluates this predicate via `bash -c "<expr>"` at step-dispatch
     time. Exit 0 → run the step; non-zero → skip with
     `Status: SKIPPED (condition false)`. Steps with `Type: conditional` lacking
     this field are pre-flight Blockers caught by `/plan-review` §23 and
     `/plan-wrap` §12.

   Worked example of a conditional step:

   ```markdown
   ### Step 5: Fix blockers and re-soak
   - **Problem:** Address blockers found in Step 4 triage
   - **Type:** conditional
   - **Condition:** test -s documentation/findings/step-4-blockers.md
   - **Issue:** #65
   ```

   If the operator does not yet know the predicate during the planning
   conversation, emit
   `**Condition:** <shell command returning exit 0 to run, non-zero to skip>`
   as a placeholder. The operator (or `/plan-review --autofix` once Step 7 of
   the BPA plan lands) fills in the real predicate later. The placeholder is
   NOT considered "empty" by the upstream §23/§12 checks — it is a valid
   intermediate state.
8. **Risks and Open Questions** — table with item / risk / mitigation
9. **Testing Strategy** — what tests are needed, what existing tests might break,
   how to verify the feature end-to-end

## Quality bar before saving

Before writing the file, verify:

- Every "X or Y" choice from the conversation is resolved to a single answer.
- Impact analysis matches actual files in the codebase. **For each function
  signature, schema field, or shared constant being changed, grep all call
  sites and list each one in the Impact Analysis table's `Verified` column**
  — not just "probably only file X uses this." See
  `feedback_grep_all_downstream_when_fixing_key_shape.md`.
- Build steps are ordered so each step can be tested independently.
- A fresh model with no conversation history could read this plan and start building.
- **If the feature touches autonomous, scheduled, background, or "always-on" behavior
  — OR if it adds observability infrastructure (dashboard, alerts, monitoring) for
  any such behavior in the existing project — the Build Steps include at least one
  step dedicated to running the full system end-to-end with realistic inputs and
  observing it long enough to expose time-dependent failures.** If the build steps
  are all component-implementation work, surface this as a follow-up phase / step and
  add it before saving. Unit tests on each component are not enough for systems
  whose value depends on running unattended. "Background" here means runs unattended
  over wall-clock time (a daemon, scheduled job, soak loop, always-on watcher) — NOT
  parallel workers (threads, processes, async tasks) within a single user-invoked
  CLI run or HTTP request that completes and returns. When the feature is a one-shot
  invocation, state explicitly in the plan that the autonomous-behavior trigger does
  not fire so reviewers can confirm the classification.
- **If the feature touches a data pipeline (producer → consumer chains, schema-bound
  storage, env→model→storage flows, or any "the dimensions/shape/columns must agree
  across modules" coupling), the Build Steps include at least one explicit smoke-gate
  step BEFORE any long-running observation step.** A smoke gate is a 60-second
  end-to-end run with REAL components wired together (no mocks), exercised just
  enough to surface producer/consumer drift. Unit tests with mocks miss this entire
  class of bug because each test mocks the boundary it would have asserted on.
  Common shapes: "start the service, send 1 real request, assert no exception";
  "open the SQLite DB, write 1 row with the latest schema, read it back";
  "instantiate the model with the env's spaces, run 1 forward pass." Mark with
  `Type: operator` if it requires manual setup, otherwise `Type: code`. The smoke
  gate's deliverable is "the pipeline can complete one real cycle without crashing"
  — pass/fail of any business logic is out of scope.

- **No `Type: operator` step has a code-shaped `Produces:` field, and no
  `Type: code` step has an operator-review `Done when:`.** Both must be split
  per Phase 5's rule + split-pattern fence BEFORE `/repo-sync` mints issues.

Run `/plan-wrap` on the draft before saving if any of the above is uncertain.

## File naming

Use a URL-friendly slug derived from the feature name:
- `documentation/plugin-parsers-plan.md`
- `documentation/oauth-integration-plan.md`
- `documentation/batch-export-plan.md`

If `documentation/` doesn't exist, create it.
