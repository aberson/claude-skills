---
name: build-phase
description: Orchestrate a multi-step build phase end-to-end. Reads step definitions from a plan doc, runs /build-step for each in order, posts live progress to GitHub issues, verifies quality gates between steps, and reports. Invoke as "/build-phase --plan <path> [--phase N]".
user-invocable: true
---

# Build Phase

Thin orchestrator that reads step definitions from a plan document and runs
`/build-step` for each one in sequence. Does not classify steps or decide flags --
those are declared in the plan. Posts comprehensive progress updates to GitHub
issues so long-running builds are visible in real time.

## When to use

- When you have 2+ build steps to run sequentially from a plan
- When the user says "run all steps", "build phase N", or "run the whole phase"

## When NOT to use

- For a single step: use `/build-step` directly

---

## Operator preference — autonomous + bundled UI + parallel (HEAVY)

This skill's default posture, by strong operator preference:

1. **Autonomous end-to-end.** On parse-success the phase begins immediately — no operator confirmation prompt. The operator opted into autonomous execution by invoking `/build-phase`; if they wanted a preview, they would have used `--dry-run` (see Arguments table). build-phase then runs through dev → review → iterate → checkpoint without checking back in between code steps. Halts are reserved for the structural cases the skill already defines: BLOCKED verdicts, operator/wait/conditional step types, quality-gate failures, test-count regressions, or genuine architectural ambiguity. Do **not** insert "should I continue?" gates beyond those — wall-clock and context-window cost is real, and the operator has opted in to "let it run."

2. **Bundle UI verification with frontend-touching code.** Any step whose `Files` touch `frontend/`, change a `/api/...` endpoint shape consumed by the dashboard, or affect WebSocket payloads should declare `/build-step --ui` (or call out any project-specific UI/dashboard smoke command defined in the project's CLAUDE.md as part of the step's flags) at plan-authoring time. If the plan declares such a step without `--ui`, build-phase surfaces this as a **UI-MISSING** summary note during Step 0 parse — and again in the final phase report — but does **not** prompt and does **not** mutate the step's flags; the phase proceeds with the plan's declared flags. The operator is expected to review the note and rearrange `plan.md` for any future invocation. Code-only verification on UI work is a known gap the operator wants closed, but autonomy beats gating.

3. **Parallel work whenever it exists.** Within each step's execution: when build-phase is dispatching independent reads (gh status, baseline gates, plan parsing), batch them in one tool message. When posting GitHub comments to multiple issues with no ordering dependency, dispatch in parallel. When the plan's steps form an obvious DAG with independent leaves, surface this in the Step 0 parse output (and the final report) as a **PARALLELIZABLE** summary note — but do **not** prompt; the phase runs sequentially per the plan. Default to scanning for parallelism before starting any sequence so the operator has the information for the next invocation.

---

## Halt contract

The 5 conditions under which `/build-phase` is permitted to halt mid-run. Anything else is a defect — surface it as a finding upstream (`/plan-review`, `/plan-wrap`), not a mid-run halt. Long-form rationale + the workspace-wide source-of-truth lives in `dev/.claude/rules/code-quality.md § "Build-phase halt contract"`; this section inlines a 1-sentence summary per item so an operator reading SKILL.md cold doesn't have to navigate out. Reference investigation `02-halt-contract.md`.

1. **Conditional-step predicate errored or returned non-binary.** A `Type: conditional` step's `Condition:` shell expression exited with a code build-phase cannot interpret as run-or-skip (command-not-found ≥126, syntax error, signal-terminated ≥128, or a predicate that outputs but never exits). See "Conditional step handling" below for the dispatch table.
2. **Quality-gate hard fail.** typecheck error count > 0, test count regressed below baseline, lint produced a blocker-class finding — OR (per Step 1's race-condition defense in sections 2d/2e) `origin` advanced with commits overlapping the step's modified file set. All four are integrity-class failures: the worktree's claim that "this step ships these changes against this baseline" no longer holds. The race-condition extension is documented as a sub-case of this halt class, NOT a new (6th) halt class — preserves the 5-item allowlist.
3. **Stop-and-audit triggered.** Third instance of the same bug-shape in this session, per `/build-step`'s stop-and-audit rule. Whack-a-mole is wasting time; STOP iterating and audit the codebase for siblings before continuing.
4. **Wait-type step reached.** A step declared `Type: wait` is long-running observation work (a soak test, a benchmark run). The orchestrator halts intentionally so wall-clock waiting doesn't burn context window. Resume in a fresh session via `--resume <next-step>` after the wait completes.
5. **Worktree merge conflict.** A surgical-edit conflict from earlier steps overlapping the current step's files. Requires human resolution before continuing.

**Defect-of-input class** (Step 0 pre-flight Blockers — caught BEFORE any step execution, so technically not "mid-run"):

- Plan has `Type: conditional` step without `**Condition:**` field (caught at Step 0 sub-bullet 6; upstream catches: `/plan-review` §23 + `/plan-wrap` §12).
- Plan has `Type: operator` step with code-shaped `Produces:` but plan-review/plan-wrap autofix didn't run (caught at Step 0 sub-bullet 7's runtime safety net).
- Plan step declares `--reviewers full|runtime` without `--start-cmd`+`--url` (caught at Step 0 sub-bullet 8's Step-flags pre-flight validation, per Step 2 of BP plan).

Mid-run halts outside this list are defects to fix upstream — examples that are NOT in the allowlist: mid-run `(y/n)` confirmation prompts, "Should I continue?" gates, operator-step halts for code-Produces steps (auto-split handles these), pure-observation operator-step halts mid-phase (deferred-UAT bundle handles these). See `dev/.claude/rules/code-quality.md § "Build-phase halt contract"` for the full anti-pattern list and the upstream-defect framing.

## Constraints

See `## Halt contract` above for the 5 halt classes + 3 defect-of-input classes. Autonomous-by-default per workspace `plan-and-issue-flow.md § "Autonomous-by-default skills"` — no mid-run prompts; preview-only behavior via `--dry-run`.

---

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--plan` | yes | -- | Path to plan doc (plan.md or documentation/*-plan.md) |
| `--phase` | no | -- | Phase number/name to run (if plan has multiple phases) |
| `--steps` | no | all | Comma-separated step numbers to run (e.g., `2,3,5`) |
| `--resume` | no | -- | Resume from step N (skip already-completed steps) |
| `--dry-run` | no | -- | Print parsed step list and summary notes, then exit without pre-flight or step execution (preview only) |

---

## Plan document format

`build-phase` expects each step in the plan to include:

```markdown
### Step 1: <name>
- **Problem:** <what to build or fix>
- **Type:** code (optional -- defaults to "code")
- **Condition:** <shell-expression> (required for `Type: conditional` steps)
- **Issue:** #<N> (optional -- created by /repo-init or manually)
- **Flags:** --isolation worktree --reviewers code (optional -- defaults to build-step defaults; see Step 0 sub-bullet 8 "Step-flags pre-flight validation" for required-combinations checks — `--reviewers full|runtime` requires `--start-cmd`+`--url` or Step 0 halts as a Blocker)
```

If `Flags` is omitted, `build-step` defaults apply (worktree + auto).
If `Issue` is omitted, no GitHub updates are posted for that step.

**Worked example — conditional step with `Condition:`:**

```markdown
### Step 5: Fix blockers and re-soak
- **Problem:** Address blockers found in Step 4 triage
- **Type:** conditional
- **Condition:** test -s documentation/findings/step-4-blockers.md
- **Issue:** #65
```

The shell-expression in `Condition:` is run from the project root at conditional-step dispatch time. Exit 0 means run; non-zero means skip. Steps with `Type: conditional` lacking a `Condition:` field are pre-flight Blockers (see Step 0 pre-flight detection).

### Step types

The `Type:` field tells build-phase what shape of work the step represents.
**Default is `code`** if omitted, preserving prior behavior. Valid values:

| Type | What it means | What build-phase does |
|---|---|---|
| `code` | Default. A normal coding step — write/modify source files, run tests. | Spawns `/build-step` with the step's flags. Standard reviewer/iteration loop. |
| `operator` | The work is observation, configuration, smoke testing, or other manual investigation that does not produce a code diff. Common for "verify X is wired" or "smoke test Y" steps. | **Does NOT spawn /build-step.** Halts orchestration, prints the step's problem statement to the user, and waits for the user to do the work and report back. The user runs the step manually (often outside any worktree) and tells build-phase the result. build-phase then updates plan/issue/checkpoint as if /build-step had returned PASS. |
| `wait` | Long-running observation. The step is mostly idle wall-clock time — a soak test, a benchmark run, a data-collection window. The deliverable is a run log or observation document, not a code diff. | **Halts orchestration entirely.** Prints the step problem and stops. The user runs the wait period manually and the orchestrator does not resume; instead a future build-phase invocation picks up at the next step via `--resume`. Burning context window on a 4-hour wait is wasteful — hand off cleanly. |
| `conditional` | The step only runs if a predicate from a prior step is true. Common shape: "Step 5: fix blockers (only if Step 4 found any)." Requires a `**Condition:** <shell-expression>` field. | **Evaluates the `Condition:` predicate.** Exit code 0 → run the step as a code step; non-zero (≤125) → skip with `Status: SKIPPED (condition false)` and continue; ≥126 or predicate errored → halt as a pre-flight defect. No y/n prompt — the predicate is the decision. |

**Why this exists:** prior to this field, build-phase blindly tried to run every step
through `/build-step`, which wastes time and context on operator/wait steps and produces
nonsense output for conditional steps. Phases that mix code and non-code work (validation
phases, soak-test phases, refactor-then-measure phases) need to declare the shape so the
orchestrator can do the right thing per step.

**Example mixed-type phase:**

```markdown
### Step 1: Document the procedure
- **Problem:** Write documentation/soak-test.md
- **Type:** code
- **Issue:** #61

### Step 2: Verify the daemon mode is wired
- **Problem:** Smoke-test the daemon CLI for 60 seconds, observe state transitions, document findings
- **Type:** operator
- **Issue:** #62

### Step 3: Run the 4-hour soak
- **Problem:** Execute the procedure from Step 1 unattended; capture observations
- **Type:** wait
- **Issue:** #63

### Step 4: Triage findings into a backlog
- **Problem:** Process Step 3 findings into actionable categories
- **Type:** code
- **Issue:** #64

### Step 5: Fix blockers and re-soak
- **Problem:** Only run if Step 4 found blockers
- **Type:** conditional
- **Issue:** #65
```

---

## Steps

build-phase walks 4 outer steps: Step 0 (parse), Step 1 (pre-flight), Step 2 (dispatch each plan step), Step 3 (final verification), Step 4 (report). See `## Flow` below for the full procedure.

## Flow

### Step 0 -- Parse plan

1. Read the plan document at `--plan` path.
2. If `--phase` is specified, extract only that phase's steps.
3. If `--steps` is specified, filter to those step numbers.
4. If `--resume` is specified, mark earlier steps as already done.
5. Scan for existing `- **Status:** DONE` lines — treat those steps as already done
   (so `--resume` is not required if previous runs already checkpointed).
6. For each step, extract: name, problem statement, **type** (default `code`),
   issue number, build-step flags, the optional `Done when:` acceptance target, and
   (for `Type: conditional` steps) the `Condition:` shell-expression.
   - **`Done when:` acceptance is optional and non-halting.** Extract the step's `Done when:` value when present. Treat it as ABSENT if the field is missing OR its value exactly matches a deferred sentinel in `../../references/step-authoring.md` §3 (`<TBD — operator fills in>` / `<how to verify the step is done>` / `<specific test or verification>`). A present, non-sentinel value is forwarded to `/build-step` as `--acceptance` at Step 2 dispatch (2b); a missing or sentinel value forwards nothing. This widens only what Step 0 reads and what Step 2 forwards — it adds no parse-halt, touches no gate, and leaves the 5-item halt contract and §2f gate text byte-unchanged.
   - **Conditional-step `Condition:` field is required.** If any parsed step has `Type: conditional` but no `**Condition:**` field (or the field is present but whitespace-only), halt Step 0 with the pre-flight Blocker message described under "Conditional step handling" below. Do not transition to step execution. This is a pre-flight defect-of-input — `/plan-review` §23 and `/plan-wrap` §12 should catch it before this point so the halt is rare. After this Step 2 work ships, Step 10 of the BPA plan codifies the legitimate-halt allowlist into `.claude/rules/code-quality.md`; until that lands, the inline rationale here is the source of truth for what `/build-phase` considers a legitimate halt.
7. **Classify each `Type: operator` step (runtime safety net + deferred-UAT triage).** For each parsed step with `Type: operator`, examine its `Produces:` field. The scan branches:

   - **Code-Produces branch (auto-split).** If any `Produces:` item ends with a code-shaped extension (`.py`, `.ts`, `.tsx`, `.js`, `.sh`, `.rs`, `.go`), is a shipped config (`.json`, `.yaml`, `.toml`) under `src/`, `scripts/`, or any package directory the project's build tooling reads, or is a code-dependent ops doc (`.md` under `documentation/operator/` or similar whose content depends on reading code), flag the step for **auto-split** per "Operator step auto-split — runtime safety net" in Step 2.
   - **Pure-observation branch (`defer-to-uat=true`).** If `Produces:` contains NO code-shaped artifact (e.g., "operator verifies dashboard responsiveness", "operator confirms screenshot looks right"), flag the step with `defer-to-uat=true`. During Step 2 dispatch, build-phase SKIPS the step (no started/result issue comment, no inline "Operator step handling" halt). The step's metadata (name, issue, commands extracted from the `Problem:`, expected-outcome table) is collected into an in-memory deferred-UAT bundle for the phase-end Manual UAT emit per "Deferred-UAT bundling — phase end" below and Step 4's final-report assembly.
   - **Missing `Produces:` field.** Treated as pure-observation (same as the second branch) — no split fires, the step gets `defer-to-uat=true`, and an audit-note line is added to the final report's `Manual UAT to run after build-phase` sub-block as a leading observability line so the inferred classification is visible right next to the deferred bundle the step contributed to (see "Operator step auto-split — runtime safety net" Edge cases for exact wording).

   The code-Produces branch is the runtime safety net complementary to `/plan-review` §22 and `/plan-wrap` §11, which catch the same shape at plan-time (Blocker class). The split only fires here if those upstream checks were skipped or their findings overridden. The pure-observation branch is the runtime counterpart to plan §5 D4's "Bundled UAT handling": observation work the operator must do is collected once at phase end rather than interrupting the autonomous run mid-phase. Cross-ref: `.claude/rules/plan-and-issue-flow.md` § "Operator-type steps must not produce code artifacts".

   This detection runs BEFORE the `--dry-run` exit (sub-bullet 9) so that the dry-run preview includes the Auto-split notes line AND the Deferred-UAT count line with accurate content (a `--dry-run` invocation against a plan containing a code-Produces operator step must show the would-be split in its summary, and a plan containing pure-observation operator steps must show the would-be deferred-UAT count, not "(none detected)" on either line).
8. **Step-flags pre-flight validation.** For each parsed step, validate the `Flags:` line against `/build-step` requirements BEFORE dispatch:

   - **`--reviewers full` requires `--start-cmd` AND `--url`.** If either is missing, surface as a pre-flight **Blocker** (NOT a runtime halt — surface BEFORE Step 1 pre-flight begins) using the same multi-line fenced format as sub-bullet 6's conditional-step Blocker:

     ```
     build-phase: pre-flight Blocker — Step N (#<issue>) declares --reviewers full without --start-cmd and --url.
     This must be fixed in plan.md before /build-phase can proceed: either change to --reviewers code (no UI/runtime needed) OR add --start-cmd <cmd> --url <url>.
     ```

     Do NOT proceed to Step 1 pre-flight or step execution. This is a defect-of-input Blocker (same class as the conditional-step missing-Condition Blocker in sub-bullet 6); the format match means an operator reading the halt template only learns one shape.
   - **`--reviewers runtime` requires `--start-cmd` AND `--url`.** Same check, same Blocker shape (runtime reviewers need a running app to capture evidence against).
   - **Flag inheritance defaults.** If a step's `Flags:` line is omitted entirely, `/build-step` defaults apply: `--isolation worktree --reviewers auto`. Surface this flag inheritance behavior as a one-line note in Step 0 output (after the step list) so the operator can see what each unflagged step will inherit — silent inheritance has bitten plans that assumed `--reviewers code` was the default. Per `/build-step` Arguments table.
   - **UI-AUTH note.** If a step's `--url` value points at an auth-gated route (default heuristic: naive URL-string substring match on `/admin` or `/dashboard`; the heuristic is intentionally narrow per plan §8 Q3 resolution and will false-positive on URLs containing those substrings as non-path segments — projects extend the list via their `CLAUDE.md`, per-project enumeration is a follow-up), emit a **UI-AUTH** summary note (informational, NOT a Blocker) suggesting the operator either (a) provide a `--start-cmd` that sets up an auth bypass OR (b) downgrade to `--reviewers code` if the UI portion is incidental. UI-AUTH is one of the always-print operator-preference checks (see the Step 0 output block below).

   This detection runs BEFORE the `--dry-run` exit (sub-bullet 9) so dry-run output includes any Blocker findings (with halt-style error message and non-zero exit) AND any UI-AUTH notes. The dry-run path is not a "preview anyway" escape from Blockers — a sub-bullet-8 Flag-Blocker halts Step 0 before the dry-run summary is even printed. Cross-reference workspace memory `feedback_plan_reviewer_flags` (the source incident: a `--reviewers full` step missing `--start-cmd` was failing deep in /build-step Step 2, wasting one full step's worth of context that pre-flight validation would have saved). Reference investigation `19-step-flags-inheritance.md`.
9. **If `--dry-run` is set:** after printing the step list, operator-preference summary notes (UI-MISSING, PARALLELIZABLE, Auto-split notes from sub-bullet 7, UI-AUTH notes from sub-bullet 8), and any detected step-type warnings, exit with status 0 and a single line: `Dry-run complete. No steps executed.` Do NOT proceed to Step 1 pre-flight. The dry-run path's only side effects are reads (plan parse, git status if shown); no commits, no dispatches, no GitHub posts.

Print the step list, showing each step's type. **Apply the operator-preference checks** as part of the Step 0 output:

- Scan each step's declared `Files`. If any step touches `frontend/`, alters a `/api/...` route shape consumed by the dashboard, or modifies WebSocket payloads AND its `Flags` line lacks `--ui`, flag it as **UI-MISSING** and emit a UI-MISSING summary note (no prompt).
- Scan step dependencies. If the plan declares no `Depends on` between two adjacent steps and their `Files` don't overlap, flag the pair as **PARALLELIZABLE** and emit a PARALLELIZABLE summary note (no prompt); the phase runs sequentially per the declared plan order.

```text
build-phase: 5 steps parsed from documentation/plan.md (Phase 4.5)
Already-done detection: scanned plan for `Status: DONE` lines -- found 0 (none to skip).

  Step 1: Document soak procedure   [code]         #61  --reviewers code
  Step 2: Verify daemon wiring      [operator]     #62  (manual smoke test)
  Step 3: Run 4-hour soak           [wait]         #63  (4h wall clock)
  Step 4: Triage findings           [code]         #64  --reviewers code
  Step 5: Fix blockers              [conditional]  #65  (if Step 4 found any)

Mixed-type phase detected. build-phase will:
  - Run code steps via /build-step
  - Halt on operator steps and prompt you to do them manually
  - Halt entirely on wait steps (resume with --resume after the wait)
  - Evaluate the `Condition:` predicate on conditional steps (run if exit 0, skip if non-zero)

Operator-preference checks (autonomous + UI-bundle + parallel):
  - UI-MISSING:        (none detected)   [or: "UI-MISSING: Steps N, M touch frontend/ but lack --ui. Continuing without it. Operator should review whether --ui flag is appropriate for the next phase invocation."]
  - PARALLELIZABLE:    (none detected)   [or: "PARALLELIZABLE pairs detected: (N, M). Running sequentially per plan; operator can rearrange in plan.md for future runs."]
  - Auto-split notes:  (none detected)   [or: "Step N (operator+code-Produces) will auto-split into N-prep + N for this run; backport to plan.md for symmetry."]
  - Deferred-UAT count: 0                [or: "2 pure-observation operator steps will be deferred to a phase-end Manual UAT bundle."]
  - UI-AUTH notes:     (none detected)   [or: "Step N: --url <url> matches auth-gated heuristic (/admin or /dashboard). Consider --start-cmd with auth bypass OR --reviewers code. Projects extend list via CLAUDE.md."]
  All five checks always print -- '(none detected)' / '0' is the explicit no-op output.
  Non-empty notes are repeated in the final phase report so the
  operator sees them after the run without scrolling Step 0 output.

Goal-drive (uninterrupted run) — emit ONE line for the operator to paste (build-phase cannot set
/goal itself; it is user-typed). Scope to the AGENT-COMPLETABLE span only: code/conditional steps
up to the next operator/wait boundary (a goal spanning an operator/wait step busy-loops). Emit a
fresh goal after each such boundary:
  To run this phase to completion without pausing, set:
    /goal "<plan-name> steps <N..M> are all marked Status: DONE in <plan-path>"
  Once set, the native /goal evaluator re-drives the session past any discretionary pause to the
  next step; pause otherwise only for the 5 halt-contract reasons.
```

After printing the step list and any summary notes, transition directly to Step 1 pre-flight with a one-line message like: `Starting Step 1 (#N) — <step name>.`

### Step 1 -- Pre-flight

1. **Detect project context:** language, test/lint/typecheck commands.
2. **Run baseline quality gates:**
   ```bash
   <typecheck_command> && <lint_command> && <test_command>
   ```
3. **Record baseline test count.**
4. **Verify git is clean** (or stash).

### Step 2 -- Run each step

For each step in order, **dispatch on the step's type**:

- **`code`** — proceed with the standard 2a-2g flow below.
- **`operator`** (code-Produces, flagged by Step 0 sub-bullet 7): apply "Operator step auto-split — runtime safety net" first, then the N-half routes through "Operator step handling" below. Skip 2b for the N-half (no /build-step).
- **`operator`** (pure-observation, `defer-to-uat=true` flag from Step 0 sub-bullet 7): SKIP this step during execution. Do NOT post a started/result comment to the issue. Do NOT run the inline "Operator step handling" halt. Collect the step's metadata (name, issue, problem-statement-extracted commands, expected-outcome table) into the in-memory deferred-UAT bundle for Step 4's "Deferred-UAT bundling — phase end" assembly. Continue to the next step without prompting.
- **`wait`** — see "Wait step handling" below. Halts the phase.
- **`conditional`** — see "Conditional step handling" below. Evaluates the `Condition:` shell predicate.

#### Operator step auto-split — runtime safety net

A `Type: operator` step flagged in Step 0 detection (sub-bullet 7) as having a code-shaped `Produces:` artifact is split in-memory before dispatch into TWO adjacent steps:

1. **`N-prep` (`Type: code`)** — authors the code artifact via the standard `/build-step` flow (2a–2g below). The `Problem:` for this prep step is auto-generated from the original step's brief, focused on the code artifact (e.g., "Author the script that step N runs"). All Files from the original step's `Files:` are carried over. The `Issue:` is the same as the original step (a single GitHub issue covers both halves — comments on the issue explain the split). When N-prep and N halves dispatch, build-phase's existing 2a "started" comment template (used for code steps) is extended with a `> Auto-split: Part 1 of 2 — code-prep half of Step N` (or `> Auto-split: Part 2 of 2 — operator half of Step N`) preamble line so issue archaeology shows both halves clearly; the 2d result comment uses the same preamble.
2. **`N` (`Type: operator`)** — runs the manual checks per the existing "Operator step handling" section below. The `Problem:` retains the manual portion of the original brief.

The split is **in-memory only** — `plan.md` is NOT modified. The phase's final report (Step 4) includes an `Auto-split notes:` line listing every split that fired with the original step's name, the code artifact path(s) detected, and a backport recommendation so the operator can mirror the structural split into `plan.md` for future runs.

Example: a Step M2 declared `Type: operator` with `Produces: scripts/generate_element_sprites.py + 14 canonical sprites + .gitignore update` is detected (sub-bullet 7) and split in-memory into:

- Step M2-prep (`Type: code`): "Author `scripts/generate_element_sprites.py`. Files: `scripts/generate_element_sprites.py`."
- Step M2 (`Type: operator`): "Run the script and spot-check 14 sprites; update `.gitignore`. Use the standard operator-step PASS/BLOCKED/SKIP response."

**Edge cases:**

- **Mixed Produces (some items code-shaped, some not):** N-prep takes only the code artifact(s); the N-half's brief preserves references to non-code items only (PDFs, run logs, spot-checks, config files outside `src/`/`scripts/`, etc.). The auto-generated N-prep `Files:` entry lists only the code artifacts. Example: `Produces: scripts/foo.py + 14 PDF reports` → N-prep authors `scripts/foo.py`; N-half's brief retains the "operator generates 14 PDF reports" portion only.
- **Missing `Produces:` field:** treat the step as pure-observation (no split, no error, no halt). Add an audit-note line to the final report's `Manual UAT to run after build-phase` sub-block, as a leading observability paragraph BEFORE the M<N> item list, with this wording: `Note: Step N (Type: operator) has no Produces: field — treated as pure-observation, no split fired. Review whether the step actually produces code; if so, plan needs a Produces: field for the runtime safety net to detect it.` This stays consistent with sub-bullet 7's "pure-observation operator steps are NOT flagged here" rule while making the inferred classification visible AND co-locating it with the deferred bundle the step contributed to (Auto-split notes is for splits that fired; this case fires no split, so routing the note there is misleading).
- **Path-less filenames (`foo.py` with no directory prefix):** use the bare name verbatim as the auto-generated N-prep `Files:` entry. `/build-step` decides placement based on project conventions (e.g., `foo.py` → `scripts/foo.py` for shell-script-shaped names, or `src/<package>/foo.py` for module-shaped names). build-phase does NOT invent a path during the split.

After this Step 3 lands, build-phase auto-splits the code-Produces operator step in-memory. The N-prep half (`Type: code`) runs autonomously through standard `/build-step` — the operator does NOT see the previous "halt and ask operator to write the script" scenario for the missing split, even if `/plan-review` was skipped. The N half (`Type: operator`) still routes through the existing "Operator step handling" section below and halts for the manual PASS/BLOCKED/SKIP response. BPA Step 4 (deferred-UAT bundling) replaces that inline operator-halt with a phase-end UAT bundle, completing the autonomy contract for code-Produces operator steps; until Step 4 lands, the operator only sees the inline manual halt for the N half — still strictly less invasive than the pre-Step-3 "halt and ask operator to author the code artifact" scenario. (After BPA Step 10 lands, the formal legitimate-halt allowlist will live in `.claude/rules/code-quality.md`; this auto-split is not on that list because the *split itself* never halts — it dispatches an extra prep step and proceeds; the N-half's operator-halt is the existing operator-step legitimate halt, not a new one.)

#### Deferred-UAT bundling — phase end

Pure-observation `Type: operator` steps (flagged by Step 0 sub-bullet 7 as having no code-shaped `Produces:` artifact) are deferred to a single bundled Manual UAT at phase end. The autonomy contract: the orchestrator never halts mid-phase for a pure-observation manual check; instead it accumulates them and surfaces the full list once when the code/conditional/wait-able steps have finished.

**Per-deferred-step in-memory collection (during Step 2 dispatch).** Build-phase extracts and stores:
- Source step name (from `### Step N: <name>`)
- Source step's `Issue:` number (if set; otherwise the `Issue:` field is omitted from the emitted entry)
- Commands to run: copy-paste-ready commands extracted from the step's `Problem:` statement, no prose mixed in (same extraction discipline as the existing "Operator step handling" Section 1)
- What you're looking for: rows mapping each command/check to its expected outcome (same shape as the existing "Operator step handling" Section 2)

**Final-report bundle assembly (at Step 4 final report).** Emit a `## Manual UAT` section listing each deferred step as `### M<N>:` (M1, M2, M3, ...). The numbering rule:

- **M-number continuation.** Parse `^### M(\d+):` headings under the `## Manual UAT` H2 section of `plan.md` (case-sensitive — `### M1:` matches, `### m1:` does not). Compute `max(N)` across those headings. The first newly-added item this run uses `max(N) + 1`; subsequent newly-added items increment from there. **Gaps are not filled** — if plan.md already has M1 and M3, a new item is M4, not M2. If no existing entries are found (no `## Manual UAT` section yet, or section present but empty of `### M<N>:` headings), numbering starts at M1.

**Plan.md write-back.** Append the same bundle to `plan.md` under a `## Manual UAT` section. Create the section if missing, with the canonical heading + the `*Generated by /build-phase on YYYY-MM-DD. Append-only; re-running the phase adds new items below, never modifies existing ones.*` italic preamble.

- **Plan.md placement.** The `## Manual UAT` section sits at H2 level (top-level), AFTER all `## Build Steps` / `## <other top-level>` sections and BEFORE any trailing single-line italic footer or horizontal rule. To locate the insertion point, find the last `## ` heading + its content; insert `## Manual UAT` immediately after it. If a trailing footer exists (e.g., `*Plan written YYYY-MM-DD...*` or a closing `---` rule), `## Manual UAT` sits BEFORE the footer so the footer remains the last thing in the doc. If plan.md has no `## Manual UAT` section yet, create one at this location. Within the section, new items go AFTER existing `### M<N>:` items (never before, never interleaved).
- **Idempotency (rename-stable).** BEFORE appending each `### M<N>:` entry, scan plan.md's `## Manual UAT` section for an existing entry whose `Source step Issue:` field (the `- **Issue:** #<N>` sub-field on the existing `### M<K>:` block) matches the current entry's source Issue. **Match-on-Issue is the primary key** — step names can drift across phase runs (rename refactors, tightened phrasing), but Issue numbers are stable. If a match is found, SKIP that entry (do not overwrite, do not duplicate). If neither side has an `Issue:` (operator step had no issue number; rare), fall back to matching on `M-number + step-name`. New items continue numbering per "M-number continuation" above.

**Canonical block format (mirrored from the BPA plan's §5 D4 — `docs/archived-plans/build-phase-autonomy-plan.md` if cross-reference is needed):**

```markdown
## Manual UAT

*Generated by /build-phase on YYYY-MM-DD. Append-only; re-running the phase adds new items below, never modifies existing ones.*

### M1: <step name from original Type: operator step>
- **Source step:** Step N (from this plan's §6)
- **Issue:** #<step-issue-N>
- **Commands to run:**
  ```powershell
  <copy-paste-ready commands from the source step, preserved verbatim>
  ```
- **What you're looking for:**

  | Check | Expected outcome |
  |---|---|
  | <check 1> | <outcome 1> |
  | <check 2> | <outcome 2> |

### M2: <step name from next deferred step>
...
```

Each H3 item is one deferred step. Sub-fields appear in FIXED order: `Source step`, `Issue`, `Commands to run`, `What you're looking for`. If a sub-field has no content (e.g., the step had no `Issue:`), omit that sub-field entirely rather than emitting an empty value.

**Final-report integration.** After the existing Step 4 final-report block (with `UI-MISSING notes:`, `PARALLELIZABLE notes:`, `Auto-split notes:`, `Quality gates:`, etc.), add a "Manual UAT to run after build-phase" sub-block. If the phase had any deferred steps, list each `M<N>:` entry there (name, issue, command count, check count). If none, omit the sub-block entirely.

**Final-line phrasing per [`feedback_name_manual_verification_handoff`](~/.claude/projects/<project>/memory/feedback_name_manual_verification_handoff.md):** when this phase run produces at least one newly-added deferred-UAT item (an `M<N>` not already in plan.md before this run — the idempotency match-on-Issue check decides this), the phase-end final report's last line MUST name that newly-added item explicitly. Example: if this run adds M5 and M6, the final line reads `Please run M5 next.` If plan.md already contained M1–M4 from prior runs and this run adds no new items (all candidate items match an existing `Source step Issue:` and are skipped per idempotency), the final line is the existing `Next: run /repo-update to commit, update docs, and push.` — no Manual UAT cue. The rule is "first NEWLY-ADDED item from this run", not "first item in plan.md"; this matters because the operator likely already ran M1–M4 from prior phase invocations and doesn't need to be re-cued to them.

#### Operator step handling

**Scope guard.** This section applies ONLY to `Type: operator` steps with a code-shaped `Produces:` artifact (the auto-split N-half from Step 2 dispatch). Pure-observation operator steps (`defer-to-uat=true` per Step 0 sub-bullet 7) are SKIPPED during Step 2 dispatch — no started/result issue comment, no inline halt. Do NOT enter this section for them.

For steps with `Type: operator`:

1. Post a "started" comment to the issue (2a) noting the step is operator-driven.
2. **Do NOT spawn /build-step.** Present the step in two-section format:

   **Section 1 — Commands to run:** Extract every verifiable action from the
   step's problem statement and present them as copy-paste-ready commands with
   no prose mixed in. Use the user's preferred shell (PowerShell on Windows).
   Include setup/teardown (e.g., staging a temp file, then resetting it).

   **Section 2 — What you're looking for:** A markdown table mapping each check
   to its expected outcome. One row per command/check from Section 1.

   Example:

   ```text
   ====================================
   build-phase: Step N is OPERATOR type
   ====================================

   ## Commands to run

   ```powershell
   # (a) Verify X blocks
   <command 1>
   <command 2>

   # (b) Verify Y passes
   <command 3>
   ```text

   ## What you're looking for

   | Check | Expected outcome |
   |-------|-----------------|
   | (a) X blocks | Error message mentioning "forbidden", exit code 1 |
   | (b) Y passes | "Passed", exit code 0 |

   Report the outcome:
     - PASS / DONE  → I'll mark the step done and continue to Step N+1
     - BLOCKED      → I'll mark the step blocked and halt the phase
     - SKIP         → I'll mark the step skipped and continue
   ====================================
   ```

   If the step has no runnable commands (pure observation), fall back to
   printing the problem statement and asking the user to report the outcome.

3. Wait for user response. Do not poll, do not spawn agents, do not assume.
4. On user response:
   - **DONE/PASS:** treat as build-step PASS. Update plan with `Status: DONE`,
     post result comment to issue, checkpoint commit, run 2f gates, continue to
     next step. The user may have produced a run log or other artifact — ask
     where it lives and reference it in the issue comment.
   - **BLOCKED:** halt the phase per 2g, post BLOCKED comment, await user.
   - **SKIP:** mark `Status: SKIPPED (operator)`, no commit, continue to next step.

Operator steps do NOT consume /build-step worktrees, do NOT run reviewers, and do
NOT iterate. The user is the entire dev+reviewer loop.

#### Wait step handling

For steps with `Type: wait`:

1. Post a "wait started" comment to the issue noting that orchestration is
   handing off and the user will resume the phase manually.
2. Print to the user:

   ```text
   ====================================
   build-phase: Step N is WAIT type — HALTING
   ====================================
   <step problem statement>

   ## Phase status so far

     Step 1 (<name>)   #<issue>  PASS  iter K/M  +X tests
     Step 2 (<name>)   #<issue>  DONE (operator)
     Step N (<name>)   #<issue>  WAIT -- halting here
     Step N+1, ...     pending

   Quality gates after last code step:
     typecheck: PASS, lint: PASS, test: <count>/<count> (was <baseline>, +<delta>)

   ---

   This step is long-running observation work. The orchestrator is halting
   so you do not burn context window on wall-clock waiting.

   Run the work yourself per the procedure in the step. When done, capture
   the run log / artifacts as the step's deliverable, then resume the phase
   in a fresh session with:

     /build-phase --plan <path> --resume <next-step-N+1>

   This step is NOT marked done by the orchestrator. After you resume,
   build-phase will skip it (because --resume points past it). Mark it done
   manually in the plan when the wait completes.
   ====================================
   ```

3. **Stop the orchestrator.** Do not continue to the next step in the same
   session. The whole point of the wait type is to avoid wasting context.

#### Conditional step handling

For steps with `Type: conditional`:

1. **Require `**Condition:**` field.** Conditional steps MUST declare a `**Condition:** <shell-expression>` field in the plan. If a `Type: conditional` step lacks `Condition:`, this is a **pre-flight Blocker**, NOT a runtime halt — `/plan-review` and `/plan-wrap` are responsible for catching this upstream. If the orchestrator detects it during Step 0 parse, halt with the error:

   ```text
   build-phase: pre-flight Blocker — Step N (`Type: conditional`) has no `**Condition:**` field.
   This must be fixed in plan.md before /build-phase can proceed.
   Run `/plan-review` (which has a §23 check for this) or `/plan-wrap` (which has a §12 check) to surface the fix.
   ```

   This is a legitimate halt: a defect-of-input the operator needs to see, not a "should I continue?" gate. (After BPA Step 10 lands, the formal legitimate-halt allowlist will live in `.claude/rules/code-quality.md`; until then, the inline rationale here is the source of truth.)

2. **Evaluate the predicate.** When a conditional step is reached during execution, exec the `Condition:` shell expression via `bash -c "<expr>"` from the project root (bash is universally invoked, even on Windows; the workspace's `CLAUDE.md` notes Git Bash is routinely available). Capture exit code only; ignore stdout/stderr unless the predicate errored. If `bash` itself is unavailable, halt as a pre-flight defect (this is a setup problem, not a predicate problem).

3. **Dispatch on exit code:**
   - **Exit 0:** the predicate is true — execute the step as a code step using the standard 2a-2g flow (same flags, same dev → review → merge cycle).
   - **Exit non-zero (but ≤ 125):** the predicate is false — mark the step `Status: SKIPPED (condition false)` in plan.md, no checkpoint commit (the skip itself is not a meaningful diff), no quality-gate run, continue to the next step. Post a brief skip comment to the GitHub issue if `Issue:` is set:
     ```
     ## build-phase: Step N skipped (condition false)

     Predicate: `<the Condition: expression>`
     Exit code: <code>
     Step skipped per Type: conditional handling.
     ```
   - **Exit ≥ 126 (command not found / not executable) OR predicate errored (unexpected behavior, e.g., signal, syntax error):** halt the phase with a `pre-flight-defect` style message — the predicate itself is broken (command-not-found, syntax error, or signal-terminated), which is a defect to surface, not a step to skip. Like the missing-Condition Blocker above, this is a legitimate halt: it represents a real defect the operator needs to see, not an autonomy gate.

#### Code step handling — standard flow

#### 2a. Post start comment to GitHub issue

If the step has an issue number:

Capture the baseline HEAD with `git rev-parse HEAD` immediately before posting and include it as `**Baseline HEAD:**` in the comment. The baseline HEAD is recorded so the recheck-git-state defense in sections 2d and 2e has a deterministic reference point — both subsequent ship gates compare `origin`'s state against this value to detect parallel-session commits that landed on master between step start and step finish.

Heredoc note: this template uses `<<EOF` (unquoted) so `$BASELINE_HEAD` interpolates at issue-comment time; backticks in the body are escaped (`\``) to render literally. The 2d PASS/BLOCKED templates below use `<<'EOF'` (single-quoted) because they have no shell variables to expand. The 2d HALT template (race-condition path) uses `<<EOF` (unquoted) for the same reason as 2a — it interpolates `$BASELINE_HEAD`, `$UPSTREAM`, `$OVERLAP`.

```bash
BASELINE_HEAD=$(git rev-parse HEAD)
gh issue comment $ISSUE --body "$(cat <<EOF
## build-phase: Step N started

<!-- AUTO-SPLIT GUARD: prepend the next line ONLY if this step came from an auto-split; otherwise omit it entirely. -->
> Auto-split: Part <1 of 2 — code-prep | 2 of 2 — operator> half of Step N.

**Step:** <step_name>
**Phase:** <phase_number>
**Flags:** <build-step flags being used>
**Baseline tests:** <test_count>
**Baseline HEAD:** $BASELINE_HEAD
**Started:** <timestamp>

Running \`/build-step\` now...
EOF
)"
```

#### 2b. Run build-step

Invoke `/build-step` with the step's problem statement, flags, and issue number. When the step's `Done when:` was extracted in Step 0 sub-bullet 6 as a present, non-sentinel value, forward it as `--acceptance "<done-when>"`; when it was absent or a §3 sentinel, forward NO `--acceptance` — the invocation is then byte-identical to today's (INV-2 no-op):

```text
/build-step --problem "<problem>" --issue <N> <flags> [--acceptance "<done-when>"]
```

The `[--acceptance ...]` is optional and advisory: `/build-step` (Step 5 of this plan) routes it into the developer prompt only; it feeds no verdict path, no gate, and no halt.

#### 2c. Capture result

After `/build-step` completes, capture:
- Verdict (PASS / BLOCKED)
- Iteration count (e.g., "iteration 2/3")
- Files changed
- Test results (count, pass/fail)
- If BLOCKED: remaining findings
- If PASS after iteration > 1: what changed between iterations

#### 2d. Post result comment to GitHub issue

If the step has an issue number, post a comprehensive update:

**Recheck git state before posting result comment.** Before posting the result comment (and before the 2e checkpoint commit), recheck `origin` for new commits that landed on the default branch since `BASELINE_HEAD` was captured in 2a. This is the **race-condition defense** against parallel `/build-phase` sessions both reaching ship gates on the same plan/issue. The Toybox K17 incident burned ~50 minutes of context after a parallel session's commit silently invalidated the local worktree's assumptions — see workspace memory `feedback_recheck_git_during_build_phase`.

**This halt is NOT a new halt class.** It extends existing halt class #2 (Quality-gate hard fail) per `dev/.claude/rules/code-quality.md § "Build-phase halt contract"` — git-state divergence from `origin` is a quality-gate failure in the integrity sense: the local worktree's claim that "this step ships these changes against this baseline" no longer holds. Treat the recheck like a typecheck or test-count regression — a measured value, surfaced as a defect.

Heuristic: `if git rev-parse --abbrev-ref @{u} 2>/dev/null returns a value, use HEAD..@{u}; else git fetch --quiet origin && git log --oneline HEAD..origin/<default-branch>`.

```bash
# Form A: upstream tracking is set
git log --oneline HEAD..@{u}
```

```bash
# Form B: no upstream — fetch and compare to default branch
git fetch --quiet origin
DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/||')
DEFAULT=${DEFAULT:-origin/master}  # Fallback if origin/HEAD isn't set (fresh clone without `git remote set-head`)
git log --oneline "HEAD..$DEFAULT"
```

If new commits exist on `origin`, compute the file-overlap:

```bash
# Files changed in the new origin commits (compare REMOTE to LOCAL — left side is the upstream)
UPSTREAM=$(git rev-parse --abbrev-ref @{u} 2>/dev/null || echo "$DEFAULT")
NEW_COMMIT_FILES=$(git diff --name-only "HEAD..$UPSTREAM")

# Files this step has modified since baseline
STEP_FILES=$(git diff --name-only "$BASELINE_HEAD..HEAD")

# Overlap = intersection
OVERLAP=$(comm -12 <(echo "$NEW_COMMIT_FILES" | sort -u) <(echo "$STEP_FILES" | sort -u))
```

**Dispatch on overlap:**

- **OVERLAP non-empty → HALT** (extension of halt class #2). Preserve the worktree state for operator inspection. Post a halt comment to the issue naming the conflicting commits (the `git log --oneline` output above) and the overlapping files; cross-link to `dev/.claude/rules/code-quality.md § "Build-phase halt contract"`. Do NOT proceed to the PASS/BLOCKED ship comment. Do NOT proceed to 2e.

  ```bash
  gh issue comment $ISSUE --body "$(cat <<EOF
  ## build-phase: Step N HALTED — race condition detected

  Recheck-git-state defense fired before the ship gate. New commits landed on \`origin\` since this step's baseline HEAD ($BASELINE_HEAD) and they touch files this step also modified.

  **Halt class:** #2 (Quality-gate hard fail — git-state integrity) per \`dev/.claude/rules/code-quality.md § "Build-phase halt contract"\`. Not a new halt class.

  **Conflicting commits on origin:**
  \`\`\`
  $(git log --oneline "HEAD..$UPSTREAM")
  \`\`\`

  **Overlapping files (this step ∩ new origin commits):**
  \`\`\`
  $OVERLAP
  \`\`\`

  **Worktree preserved.** Resolve the divergence (merge / rebase / re-plan) and re-run with \`/build-phase --plan <path> --resume N\`.

  Source: workspace memory \`feedback_recheck_git_during_build_phase\` (Toybox K17, ~50 minutes context burn).
  EOF
  )"
  ```

- **New commits exist but OVERLAP empty → informational note only, continue.** Emit a one-line note in the result comment ("Note: N new commits landed on `origin` during this step but touched no files in this step's scope — no halt.") and proceed to the PASS/BLOCKED ship comment below per plan §8 risk-table line 228.

- **No new commits → silent, continue to ship comment.**

**On PASS:**

```bash
gh issue comment $ISSUE --body "$(cat <<'EOF'
## build-phase: Step N complete

<!-- AUTO-SPLIT GUARD: prepend the next line ONLY if this step came from an auto-split; otherwise omit it entirely. -->
> Auto-split: Part <1 of 2 — code-prep | 2 of 2 — operator> half of Step N.

**Verdict:** PASS (iteration M/K)
**Files changed:** <list>
**Tests:** X/Y passing (+Z new)
**Gates:** typecheck OK, lint OK, test OK
**Reviewers:** <which reviewers ran and their verdicts>

### Changes made
<summary of what the developer agent built>

### Review summary
<key findings addressed, if iteration > 1>

**Duration:** ~Nm
EOF
)"
```

**On PASS after multiple iterations:**

```bash
gh issue comment $ISSUE --body "$(cat <<'EOF'
## build-phase: Step N complete (required M iterations)

<!-- AUTO-SPLIT GUARD: prepend the next line ONLY if this step came from an auto-split; otherwise omit it entirely. -->
> Auto-split: Part <1 of 2 — code-prep | 2 of 2 — operator> half of Step N.

**Verdict:** PASS (iteration M/K)

### Iteration history
- **Iteration 1:** NEEDS WORK
  - Findings: <summary of reviewer feedback>
- **Iteration 2:** PASS
  - Changes from iter 1: <what was fixed to address findings>

**Files changed:** <list>
**Tests:** X/Y passing (+Z new)
**Gates:** typecheck OK, lint OK, test OK

**Duration:** ~Nm
EOF
)"
```

**On BLOCKED:**

```bash
gh issue comment $ISSUE --body "$(cat <<'EOF'
## build-phase: Step N BLOCKED

<!-- AUTO-SPLIT GUARD: prepend the next line ONLY if this step came from an auto-split; otherwise omit it entirely. -->
> Auto-split: Part <1 of 2 — code-prep | 2 of 2 — operator> half of Step N.

**Verdict:** BLOCKED after M/K iterations

### Iteration history
- **Iteration 1:** NEEDS WORK -- <findings summary>
- **Iteration 2:** NEEDS WORK -- <what changed, what still fails>

### Remaining findings
<per-reviewer breakdown>

### Worktree preserved
Path: <worktree_path>
Branch: <branch_name>

**Phase paused.** Steps N+1 through <last> are pending.
Resolve findings and re-run with `/build-phase --plan <path> --resume N`.
EOF
)"
```

#### 2e. Update plan doc and checkpoint commit

After capturing the result (PASS or BLOCKED), update the plan document and commit:

**Recheck git state before the checkpoint commit.** Re-run the same recheck-git-state defense described in section 2d (race-condition defense) immediately before `git add -A && git commit`. The window between 2d's recheck and 2e's commit is small but non-zero, and a parallel session that committed in that window must still be detected. Heuristic + commands are identical:

```bash
# Form A: upstream tracking is set
git log --oneline HEAD..@{u}
```

```bash
# Form B: no upstream — fetch and compare to default branch
git fetch --quiet origin
DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/||')
DEFAULT=${DEFAULT:-origin/master}  # Fallback if origin/HEAD isn't set (fresh clone without `git remote set-head`)
git log --oneline "HEAD..$DEFAULT"
```

If new origin commits exist AND their changed files overlap `$BASELINE_HEAD..HEAD`, **halt before committing** as an extension of halt class #2 (Quality-gate hard fail) per `dev/.claude/rules/code-quality.md § "Build-phase halt contract"`. Preserve the worktree state for operator inspection — do NOT run `git add -A`, do NOT create the checkpoint commit. The same halt comment template from section 2d (naming the conflicting commits via `git log --oneline` and listing overlapping files) is posted to the issue. Non-overlapping new commits proceed silently (informational note already emitted by 2d). See workspace memory `feedback_recheck_git_during_build_phase` (Toybox K17).

1. **Mark the step in plan.md.** Find the step's `### Step N:` heading and append a
   status line immediately after the existing metadata:

   - On PASS: `- **Status:** DONE (YYYY-MM-DD)`
   - On BLOCKED: `- **Status:** BLOCKED (YYYY-MM-DD)`

   If a `Status` line already exists for the step, replace it.

2. **Create a checkpoint commit** with all current changes (merged worktree files +
   plan doc update):

   ```bash
   git add -A
   git commit -m "checkpoint: step N complete — <step_name>"
   ```

   On BLOCKED, use:

   ```bash
   git add -A
   git commit -m "checkpoint: step N blocked — <step_name>"
   ```

   These commits are intentionally small and frequent so that `--resume` can
   pick up cleanly and so progress is never lost if context runs out.

#### 2f. Verify quality gates

After each successful step:

```bash
<typecheck_command> && <lint_command> && <test_command>
```

- If gates pass and test count >= baseline: update baseline, continue.
- If gates fail: stop, report which gate failed, suggest fix.
- If test count decreased: stop, report which tests were lost.

#### 2g. Stop conditions

- **BLOCKED** from build-step: update plan, checkpoint commit, post to issue, stop, wait for user.
- **Quality gates fail after merge**: post to issue, stop, wait for user.
- **Test count decreased**: post to issue, stop, wait for user.

On stop, always report which steps completed and which are still pending.

### Step 3 -- Final verification

After all steps complete:

```bash
<typecheck_command> && <lint_command> && <test_command>
```

### Step 4 -- Report

```text
========================================
build-phase complete
========================================

Plan: documentation/plan.md (Phase 3)
Steps completed: 5/5

  Step 1 (User search)     #44  PASS  iter 1/3  +4 tests
  Step 2 (Results page)    #45  PASS  iter 1/3  +6 tests
  Step 3 (Pagination)      #46  PASS  iter 2/3  +3 tests
  Step 4 (Filter sidebar)  #47  PASS  iter 1/2  +5 tests
  Step 5 (E2E tests)       #48  PASS  iter 1/3  +8 specs

Quality gates:
  typecheck: PASS (0 errors)
  lint:      PASS (0 violations)
  test:      173/173 passing (was 147 at start, +26 new)

UI-MISSING notes:     (none detected)   [or: "Steps N, M touched frontend/ without --ui — review for next invocation"]
PARALLELIZABLE notes: (none detected)   [or: "Pairs (N, M) were independent — consider parallel worktrees for next invocation"]
Auto-split notes:     (none detected)   [or: "Step N (operator+code-Produces) auto-split into N-prep (code) + N (operator); artifact: path/to/file.py — backport to plan.md for future runs"]

Manual UAT to run after build-phase (2 newly-added items from pure-observation operator steps this run; M5–M6 — plan.md already contained M1–M4 from prior phase runs):
  Note: Step 7 (Type: operator) has no Produces: field — treated as pure-observation, no split fired. Review whether the step actually produces code; if so, plan needs a Produces: field for the runtime safety net to detect it.   [omit this Note line when every deferred step had an explicit Produces:; include one Note: line per missing-Produces case]
  M5: <step name>   #<issue>   commands: <count>, checks: <count>
  M6: <step name>   #<issue>   commands: <count>, checks: <count>

Full details: see plan.md `## Manual UAT` section (appended by this phase).

Please run M5 next.
========================================
```

The final-line cue names the first NEWLY-ADDED M<N> from this phase run, not literal M1. The example above shows the re-run case where plan.md already had M1–M4 from prior phases and this run added M5–M6, so the cue is `Please run M5 next.` — pick the lowest M-number among items this run actually appended (per the idempotency match-on-Issue check). For a first-ever run where plan.md had no `## Manual UAT` section, the first newly-added item is M1 and the cue would read `Please run M1 next.`

If zero pure-observation operator steps were deferred this run (none in the plan, OR all candidate items matched an existing `Source step Issue:` and were skipped per idempotency), the "Manual UAT to run after build-phase" sub-block is omitted entirely and `Next: run /repo-update to commit, update docs, and push.` remains the final line of the success-path report.

If any step was blocked:

```text
========================================
build-phase paused
========================================

Plan: documentation/plan.md (Phase 3)
Steps completed: 2/5

  Step 1 (User search)     #44  PASS     iter 1/3  +4 tests
  Step 2 (Results page)    #45  PASS     iter 1/3  +6 tests
  Step 3 (Pagination)      #46  BLOCKED  iter 3/3
  Step 4 (Filter sidebar)  #47  pending
  Step 5 (E2E tests)       #48  pending

Blocked on Step 3: <finding summary>
Worktree: <path>

UI-MISSING notes:     (none detected)   [or: "Steps N, M touched frontend/ without --ui — review for next invocation"]
PARALLELIZABLE notes: (none detected)   [or: "Pairs (N, M) were independent — consider parallel worktrees for next invocation"]
Auto-split notes:     (none detected)   [or: "Step N (operator+code-Produces) auto-split into N-prep (code) + N (operator); artifact: path/to/file.py — backport to plan.md for future runs"]

Manual UAT to run after build-phase (N newly-added items deferred from pure-observation operator steps encountered before the block — pure-observation steps are SKIPPED during dispatch, not run, so these were collected without producing a worktree or commits):
  Note: Step 7 (Type: operator) has no Produces: field — treated as pure-observation, no split fired. Review whether the step actually produces code; if so, plan needs a Produces: field for the runtime safety net to detect it.   [omit this Note line when every deferred step had an explicit Produces:; include one Note: line per missing-Produces case]
  M<first-new>: <step name>   #<issue>   commands: <count>, checks: <count>
  ...

Full details: see plan.md `## Manual UAT` section (appended by this phase).

Resume after fixing: /build-phase --plan <path> --resume 3
Please run M<first-new> next.
========================================
```

The Manual UAT bundle is NOT held back when the phase pauses — items deferred before the block still emit so the operator can run them in parallel with debugging the blocked step. `M<first-new>` is the lowest newly-added M-number from this run (same rule as success-path: per idempotency match-on-Issue, items that already lived in plan.md from prior runs are skipped and not re-cued).

If zero pure-observation operator steps had been deferred before the block (none encountered, OR all candidates matched an existing `Source step Issue:` and were skipped per idempotency), the "Manual UAT to run after build-phase" sub-block is omitted from the paused-path report and `Resume after fixing: ...` remains the final line.

---

## Error recovery

If a step fails and the user provides a fix:

1. User fixes the issue (in worktree or main project)
2. User runs `/build-phase --plan <path> --resume N`
3. build-phase re-runs step N, then continues with N+1, N+2, etc.
4. Already-completed steps are NOT re-run.

---

## Task-state integration

build-phase integrates with `current.md` at 3 points during execution. This enables
crash recovery without `session-wrap` and preserves phase progress across compaction events.

**The existing halt contract is unchanged.** `task-handoff --loop` is called only after
successful step completion — it does not replace or affect the 5 halt conditions.

### Integration point 1 — Phase start (Step 0 parse)

After parsing the step list, before running pre-flight:

1. Resolve `<git-root>/.claude/task-state/current.md` via `git rev-parse --show-toplevel`
2. If the file exists AND its `Task:` field contains the current plan path:
   - Read `current.md`
   - Output: `"Resuming phase from step N per task state."` (where N comes from the WIP
     field — the step in progress at the last checkpoint)
   - Pre-flight runs from that step; steps already marked DONE in the plan doc are skipped
3. If `current.md` is absent or does not match the current plan: proceed normally

### Integration point 2 — After each step completes (Step 2e)

**MUST use `task-handoff --loop --no-commit`** — build-phase's Step 2e checkpoint commit
picks up `current.md` naturally. Using `--loop` (with commit) creates a double-commit that
interferes with the 2d/2e race-detection ordering.

Call `task-handoff --loop --no-commit` BEFORE the `git add -A && git commit` in 2e,
with current.md reflecting:

```
## Completed
- [<commit-sha>] Step N <step-name>: PASS (<test-count> tests)

## WIP
**Current:** Step N+1: <next-step-name>
**Approach:** <next step's Problem field verbatim>

## Next Action
/build-phase --plan <plan-path> --resume N+1
```

The `--no-commit` write happens before 2e's `git add -A` so the checkpoint commit
includes both the plan's `Status: DONE` entry and the current.md update atomically.

### Integration point 3 — Phase end (Step 4 report)

After the final report, call `task-handoff --loop` (WITH commit — phase is done, no
subsequent 2e commit will pick up current.md):

```
## Completed
(all steps listed)

## Next Action
/repo-update — commit, update docs, push
```

Status: COMPLETE.

---

## Relationship to other skills

| Skill | Role |
|---|---|
| `/plan-init`, `/plan-feature` | Create the plan doc that build-phase reads |
| `/repo-init` | Create GitHub issues from plan steps (first time) |
| `/repo-sync` | Sync issues when plan evolves (create/update/close to match) |
| `/build-step` | Execute a single step (build-phase calls this) |
| `/repo-update` | Commit, update docs, push (run after build-phase completes) |
| `/review-gauntlet` | Code review (called by build-step when `--reviewers code\|full`) |
| `/task-handoff` | Task-state checkpoints (3 integration points — see Task-state integration above) |

---

## Limitations

- Does not create GitHub issues -- expects them to already exist (use `/repo-init` or `/repo-sync`)
- Creates checkpoint commits per step but does not push -- use `/repo-update` to push
- Does not infer step type -- the plan must declare `Type:` for non-code steps (defaults to `code` if omitted)
- Default execution is sequential, but parallelizable pairs are surfaced in Step 0 (operator preference). When the operator opts into parallel worktrees for an independent pair, dispatch the two `/build-step` calls in a single tool message. When in doubt about independence, stay sequential.
- **Run continuously — do NOT pause for "context budget."** A long phase is safe end-to-end in one window: auto-compaction fires on its own at the threshold, the `PreCompact` hook stamps + backs up `current.md`, each step ends with a checkpoint commit, and the `SessionStart` (matcher `compact`) hook re-injects `current.md`'s Next Action afterward — so a compaction *between* steps loses nothing and the orchestrator resumes from `--resume N`. **Pause ONLY for the 5 halt-contract reasons — NEVER because "context might fill."** Splitting a code-step phase mid-run for budget is the discretionary-pause anti-pattern that stranded a real run after Step 1 (see `feedback_build_phase_continuous_via_goal`). Practical aids:
  - **Guaranteed no-pause via `/goal` (structural, not advisory):** prose can be overridden, so the real anti-pause is the native `/goal` evaluator — a Stop hook that re-drives the session until the condition holds, overriding any discretionary pause. Step 0 emits a scoped `/goal` line for the operator to set once. **Scope it to the agent-completable span only** (code/conditional steps up to the next operator/wait boundary) per `feedback_goal_mode_only_agent_completable` — a goal of "all steps DONE" on a plan with an operator/wait step busy-loops forever. `/goal` is user-typed (build-phase cannot set it itself); emit it, the operator pastes it once.
  - **Tee log from phase start:** invoke the phase with output capture so the orchestrator's prose survives session compaction. Bash example: `tee phase-<plan>-$(date +%Y%m%d).log`. PowerShell: `Tee-Object -FilePath phase-<plan>-2026-05-23.log`. Without this, the operator can't reconstruct what happened in a prior session beyond what reached GitHub issue comments — and the halt-comment audit trail (per the race-condition defense in sections 2d/2e + halt contract above) only covers ship-gate events, not mid-step reasoning.
  - **The ONLY budget split point is a `Type: wait` step** (halt class #4 — the orchestrator halts there anyway): resume the next session with `--resume <next-step-N+1>`. **Code steps do NOT split for budget — they run continuously.** Mid-step caveat: a compaction during a build-step's uncommitted worktree work can disrupt that one step; `--resume` is idempotent, so worst case re-run it.
  - **Resume recovery procedure (inline):** `/build-phase --plan <path> --resume N` skips any step whose `Status: DONE` is already in the plan AND any step before N. To explicitly skip a BLOCKED step on resume, mark it `Status: SKIPPED (manual)` in the plan before resuming. The orchestrator does NOT re-run already-DONE steps even without `--resume` (per Step 0 sub-bullet 5's already-done detection). See also the "Error recovery" section above.
- **Worktree hygiene.** `/build-phase` delegates worktree lifecycle to `/build-step`, but three hazards have each cost the workspace a session — see `dev/.claude/rules/worktree-hygiene.md` for the long-form rationale + recovery procedures:
  - **Windows removal-lock risk** (`worktree-hygiene.md` §2): `git worktree remove` returns `Permission denied` when any shell cwd is inside the worktree OR a Python process holds open `.pyc` handles. Cleanup must `cd <project_root> && git worktree remove <path>` in one compound command; the orchestrator avoids this by never cd'ing into worktrees.
  - **Dep-rebuild requirement** (`worktree-hygiene.md` §1): fresh worktrees do NOT inherit `.venv/` (Windows often binds the wrong Python) or `frontend/node_modules/` (gitignored). `/build-step`'s pre-flight runs `uv sync` and `npm install` when relevant, but a step whose `Files` include Python/Node sources should be expected to incur ~30s of dep-rebuild before the first quality gate fires. See workspace memory `feedback_worktree_venv_rebuild`.
  - **Shared-file overwrite risk** (`worktree-hygiene.md` §6): adjacent code steps touching the same file (routes module, config) overwrite each other on merge if the dev agent rewrote the whole file rather than applying surgical edits. After each step's merge, re-run the project's test gate before launching the next step. See workspace memory `feedback_buildphase_worktree_merge` (Alpha4Gate Phase 2 incident).
