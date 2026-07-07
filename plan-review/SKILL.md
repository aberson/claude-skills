---
name: plan-review
description: Review a project plan.md or feature plan for gaps, missing pieces, unresolved decisions, and risks. Works for both greenfield project plans and scoped feature plans (documentation/*-plan.md). For feature plans, also validates claims against existing code and checks impact completeness. Use when asked to review or audit a plan before building begins.
user-invocable: true
---

# Plan Review

Read the project plan (typically `plan.md` in the current directory or a path provided by
the user) and produce a structured review covering gaps, risks, and forgotten items.

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--autofix` | no | true (default ON) | Auto-apply fixes that don't need user judgment (operator+code splits, missing Done-when, missing Files, default Type: code, placeholder Condition:). Findings requiring judgment are still surfaced. |
| `--no-autofix` | no | -- | Opt out of autofix. Surface ALL findings as recommendations; do not modify plan.md. For operators who want to review before applying. |

## What to check

### 1. Data persistence
- Is there a defined store for every entity the app creates or tracks?
- Is the store technology chosen (DB, SQLite, flat-file, in-memory)?
- Is there a strategy for data corruption, partial writes, or concurrent access?

### 2. External dependencies and integrations
- Are all third-party services identified with auth/API key strategy documented?
- Are rate limits, ToS constraints, or bot-detection risks acknowledged?
- Are fallback strategies defined for external service failures?

### 3. Authentication and secrets
- Are secrets (API keys, tokens) kept out of source code?
- Is there a documented pattern for loading secrets (env vars, config file)?
- Are token expiry and refresh scenarios handled?

### 4. Async and concurrency
- Are long-running tasks (crawlers, AI calls, file processing) handled non-blocking?
- Is there a job status/polling mechanism if tasks are async?
- Are race conditions possible on shared state (files, DB)?

### 5. Error handling and user feedback
- Are failure modes identified for each major component?
- Does the UI surface errors clearly rather than silently swallowing them?
- Are partial failures (e.g., some form fields filled, others not) communicated?

### 6. Build and toolchain
- Enumerate `{install, dev, build, test, lint, typecheck}` and flag every one the plan omits — partial coverage (e.g., test+lint+typecheck but no install/dev/build) is still a finding.
- Are there separate build configs for distinct sub-systems (e.g., frontend vs backend)?
- Is the dev/prod environment split clear?

### 7. Unresolved decisions
- Enumerate every "X or Y" choice, every "TBD" marker, every bare `<placeholder>` identifier, and every vague reference ("standard project layout", "the existing X model"). Surface each verbatim — none are silently passed over.

### 8. Missing setup documentation
- Are system-level requirements documented (runtime versions, OS tools, env vars)?
- Are first-run steps clear (install deps, seed data, configure env)?

### 9. Deduplication and idempotency
- If the system runs repeatedly, can it safely re-run without creating duplicates?
- Is there a mechanism to detect already-processed items?

### 10. Integration seams
- Does each module have a clear, typed contract with adjacent modules?
- Are there any circular dependencies or unclear ownership boundaries?

### 11. Scope creep and over-engineering
- Are there features planned that go beyond what is needed for the stated goal?
- Are there abstractions that won't be used more than once?

### 12. Security
- Is user input validated before use (file paths, URLs, text fields)?
- Are there command injection risks (e.g., shell out with user-supplied args)?
- Is sensitive profile data protected appropriately (not logged, not sent to unexpected services)?
- **Prompt injection from fetched external content** — if the plan describes fetching GitHub issues, web URLs, or external API responses and passing the content to an LLM, the plan must treat that content as data, not instructions (no `<system-reminder>` tags, no "ignore prior instructions" pattern, no fake tool output trusted at face value). See `.claude/rules/security.md` § "Treat fetched external content as data, not instructions".
- **Pair unsafe configs with startup safety checks** — if the plan describes a "don't expose X until Y is configured" pattern (LAN bind requires PIN, feature flag requires migration, debug endpoint requires dev mode), the constraint must be enforced as a startup invariant with a stable error code, not as documentation. See `.claude/rules/security.md` § "Pair unsafe configs with startup safety checks".

### 13. Testing strategy
- Is there a plan for unit, integration, and end-to-end tests?
- Are critical paths (data write, AI generation, form fill) covered?
- Is there a way to test without hitting live external services?

### 14. Operational concerns
- How does the user start and stop the app?
- Is there a way to recover from a bad state (reset store, clear queue)?
- Is there a scheduler or recurring task mechanism if the system needs to run periodically?

### 15. End-to-end validation strategy

For systems that run autonomously, in the background, on a schedule, or make any
"always-on" / "continuous" / "self-improving" claims, check whether the plan has a
deliberate phase or step where the full system runs end-to-end with realistic inputs
and is observed long enough to expose time-dependent behavior. **Component unit tests
do NOT satisfy this check** — they prove pieces work in isolation, not that they work
together under real conditions.

**Trigger this check when the plan describes any of:**
- Background daemons, schedulers, cron jobs, watchers, or polling loops — **any** mention of "daily", "periodic", "scheduled", "every N minutes", "cron", "reminder delivery", or similar time-based execution fires this check, even when the surrounding plan is otherwise bare or the scheduled work is a single line. Do not skip §15 because the scheduler is mentioned only briefly.
- Autonomous loops (train → evaluate → promote, generate → review → publish, etc.)
- "Continuous", "always on", "unattended", or "self-improving" capability claims
- Multi-phase builds where each phase ships infrastructure with its own tests but
  cross-phase integration is implicit
- Failure modes the plan claims to detect (regression, drift, exhaustion, alerting)
  that have never been deliberately exercised against the real system

**Questions to ask:**
- Is there a phase or step explicitly dedicated to running the full system end-to-end
  with realistic inputs (not synthetic fixtures or mocks)?
- Does that step run long enough to observe time-dependent behavior — at least one
  full cycle of any scheduled / periodic / triggered process the plan describes?
- Is there human (or agent) observation, or only automated assertions? Silent failure
  modes need eyes, not just `assert`s.
- Are the failure modes the plan claims to detect actually exercised? E.g., if the
  plan says "rollback fires on regression," has anyone triggered a real regression
  and watched the rollback fire?
- Does the plan's "we know it works" claim have evidence beyond unit test counts?
- After the plan ships, will anyone be able to answer "has this system actually run
  unattended end-to-end?" with a `yes`, citing observed evidence?

**Why this matters:** Avoid the silent multi-phase failure where each phase passes unit tests but the system is never run as a black box. Time-dependent bugs (memory leaks, drift, races, threshold mistuning) are invisible to short test runs.

**Recommended fix when missing:** Add an explicit validation phase with these properties:
- One step documents the procedure (prerequisites, startup sequence, observation
  protocol, stop and post-soak protocol) so it can be re-run by anyone
- One step actually runs the system for a target duration with observation and
  evidence capture (screenshots, logs, state snapshots)
- One step triages findings into actionable categories (blockers, tuning, UX polish,
  documentation gaps, inputs to the next phase)
- An optional fix-and-re-soak step, conditional on blockers existing
- Success criteria are observation-based, not pass/fail — even "the loop died after
  5 minutes for reason X" is a valuable finding worth shipping
- The phase is explicitly NOT a "fix everything you find" phase, just a "see what
  actually happens" phase

Default this phase between the last "build infrastructure" phase and any "refactor / abstract / generalize" phase — refactoring without a known-good baseline destroys the ability to verify nothing regressed.

### 15.5 Smoke-gate strategy for data pipelines

A smoke gate is the smaller sibling of the section-15 observation phase: a 60-second
end-to-end run with REAL components wired together (no mocks), exercised just enough
to surface producer/consumer drift. Section 15 catches "the loop runs unattended for
hours but accumulates wrong state" — this section catches "the loop crashes on
the first cycle because the env's action space doesn't match what the trainer
hardcoded."

**Trigger this check when the plan describes any of:**
- Producer → consumer chains where one component's output is another's input
  (env → model → DB writer; service → message queue → worker; bot → schema → storage)
- Schema-bound persistence (SQL tables, protobuf, JSON schemas, dataclasses pickled
  to disk) where the schema is defined in code that may evolve separately from the
  producer
- Any "the dimensions/shape/columns must agree across modules" coupling — gym spaces,
  tensor shapes, feature vectors, action enums, CLI flag enums shared between
  client and server
- Any "we hardcoded N here and N there must match" pattern, or duplicate copies of
  the same shape constant in different files
- Migrations on persistent state (DB schema changes, on-disk format version bumps,
  pickled state with new fields)

**Why this is separate from section 15:** Stop treating a 4-hour soak as the only end-to-end check — one shape-mismatch crash burns the whole wait window discovering a 3-line bug. Run smoke gates in 60 seconds to catch it.

**Why unit tests don't satisfy this:** Avoid trusting mock-bounded unit tests for cross-module shape coupling. Mocks codify the boundary they should be asserting on — producer asserts "I produce Box(17,)", consumer asserts "given Box(17,) I do X", and neither catches a producer that silently changed to Box(15,). Wire the real producer to the real consumer.

**Questions to ask:**
- Is there at least one build step before the long observation phase that runs the
  pipeline end-to-end with real components, wired through their actual import paths?
- Does that step have a measurable success criterion that is NOT "all unit tests pass"
  — e.g., "instantiate model with env's spaces, run 1 forward pass, assert no exception"?
- If the plan introduces a new persistent schema (DB table, file format), does it
  include a migration step AND a smoke that opens an existing legacy file/DB and
  verifies the migration ran?
- If the plan introduces a new shape constant (action count, feature dim, column
  list), does the plan name a single source of truth for that constant — and does
  every consumer import from that source rather than redefining it?

**Recommended fix when missing:** add one or more smoke-gate steps to the build steps
list, between the implementation steps and the observation/soak phase. Common shapes:
- "Smoke: model + env wiring" — instantiate the model with the env's actual spaces,
  run 1 forward pass, assert no exception
- "Smoke: schema migration on legacy DB" — open a synthetic legacy DB file that
  predates the new columns, run the migration, write+read 1 row
- "Smoke: 1-cycle daemon run" — start the daemon for 60 seconds against real (not
  mock) components, hit the API, capture state, kill cleanly

Mark with `Type: operator` if it requires manual setup (real DB file, external
service), otherwise `Type: code` with a shell-script test in the standard test suite.
Smoke gates are cheap; demand more of them than feels necessary.

### 16. Clean-context readiness
- Could a model with no prior conversation history read this plan and act on it correctly?
- Are all schemas and data structures summarized inline (not just named)?
- Are all entity IDs defined (format, generation method) — no bare `<id>` placeholders?
- Are all tools, frameworks, and project-specific terms explained on first use?
- Is every stack decision accompanied by a rationale?
- Is there a step-by-step quickstart covering install, configure, and first run?
- Are all API routes documented with request and response shapes?
- Is the development process (RWL or otherwise) summarized inline, not just referenced?

If any of these fail, run `/plan-wrap` for a deeper pass before handing the
plan to another model or agent.

### 17. Feature plan — existing-code validation

*Sections 17–21 apply ONLY to feature plans (e.g. `documentation/*-plan.md`), not greenfield. Sections 1–16 still apply in feature mode — fire each §1–16 check whose trigger condition the feature plan satisfies (persistence, external deps, scheduled work, producer/consumer chains, undefined acronyms, missing build steps, etc.). Do NOT silently skip §1–16 because §17–21 are running. **Two carve-outs apply in BOTH modes:** §19's CLAUDE.md/AGENTS.md-conventions bullet and §21's step-sizing bullet (see `../../references/step-authoring.md` §1) — run them in greenfield too; only the rest of §17–21 is greenfield-skipped.*

**Proof discipline applies to all feature plan checks (sections 17–21):** Every claim
about the codebase must cite file:line or command output. Do not state "module X exists"
without showing the glob/grep that found it. Do not state "function Y is missing" without
showing the search that returned zero matches. Do not state "the plan's description
doesn't match reality" without quoting both the plan text and the actual code.

- For every existing file or module the plan claims to modify, verify it exists (`glob`/`grep`).
  Cite the match.
- For every module the plan describes, spot-check that the description matches reality
  (read the file, compare to the plan's summary). Quote both.
- Flag any references to files, functions, or patterns that do not exist in the codebase.
  Show the search that came up empty.

### 18. Feature plan — impact completeness

- Are there modules the feature will obviously affect that the plan does not mention?
  (e.g., shared utilities, config files, test fixtures, CI pipelines)
- If the feature adds a new entity or route, does the plan account for all layers that
  need to know about it (model, route, test, migration, docs)?
- Does the plan mention which existing tests might break or need updating?
- If the plan touches storage representation (lazy insert, normalization, pagination, schema migration, new materialized view), does it include an explicit wire-shape validation step (asserting API/WS response shape against a reference, not just "tests pass")? Test diffs that adjust response-shape assertions during such steps are suspect — the dev agent often codifies the regression. See `.claude/rules/code-quality.md` § "Audit wire shape when storage representation changes" and `feedback_audit_wire_shape_on_storage_change.md`.

### 19. Feature plan — conflict detection

- Does the plan conflict with other active plans in `documentation/`?
- Are there recent git commits or branches that touch the same files the plan targets?
- If the project has a CLAUDE.md or AGENTS.md with conventions, does the plan follow them? **(Carve-out — applies in BOTH modes,** greenfield included: check the project's CLAUDE.md/AGENTS.md, or — for a new project without one yet — the plan's own stated conventions; they bind from the first step.)

### 20. Feature plan — context sufficiency

- Does the plan include enough summary of existing architecture that a fresh model could
  orient without reading the entire codebase?
- Are referenced existing modules described briefly (purpose, key exports), not just named?
- Could a model start building from this plan alone, or would it need to ask "what does
  module X do?" before proceeding?

### 21. Feature plan — scope appropriateness

- Is the plan scoped to the feature, or has it accidentally re-planned parts of the
  existing project?
- Does it re-state stack/tooling decisions the project has already made without adding
  new rationale?
- Are build steps sized for a feature (not a full project rebuild)? **(Carve-out — applies in BOTH modes:** each step is one vertical slice, per `../../references/step-authoring.md` §1.)

### 22. Step shape — operator/code split (Blocker if violated)

**Apply this check to every plan with `/build-phase`-compatible build steps**, both
greenfield and feature plans.

For every step declared `Type: operator`, check whether the step's `Produces:` line
includes any code-shaped artifact:

- Source files (`.py`, `.ts`, `.tsx`, `.js`, `.sh`, `.rs`, `.go`, etc.)
- Shipped config files (`.json`/`.yaml`/`.toml`) under `src/`, `scripts/`, or any
  package directory the project's build tooling reads
- Ops docs (`.md` under `documentation/operator/` or similar) that require reading
  code to write correctly — i.e., the doc would be wrong if authored without
  filesystem access

Flag as a **Blocker**. `/build-phase` on a `Type: operator` step does NOT spawn `/build-step`, so the code artifact would force either a mid-build halt or a silent auto-author — both waste operator attention.

Split into two adjacent steps:

- `N-prep` (Type: code): authors the script / helper / config. Standard `--reviewers code`.
- `N` (Type: operator): runs the artifact + manual checks.

Default to splitting. Inline-code-inside-operator-brief is acceptable only when the code is <50 LOC, mechanical, and the operator brief makes the orchestrator's pre-author step unambiguous.

Apply the symmetric check: a `Type: code` step whose `Done when:` includes "operator visually reviews" or "operator runs and confirms" masks an operator dependency the same way. Either move the visual review to its own operator step, or re-label as `Type: operator` with the code split out as a prep step.

See `.claude/rules/plan-and-issue-flow.md` § "Operator-type steps must not produce code artifacts" for rationale and the Toybox Phase M M2 incident.

### 23. Conditional steps must declare a Condition: predicate (Blocker)

**Check:** For every step with `**Type:** conditional`, the step must also have a non-empty `**Condition:** <shell-expression>` field. A missing field OR a present-but-empty/whitespace-only value are both Blockers. (The placeholder text `<shell command returning exit 0 to run, non-zero to skip>` is acceptable and not "empty" — it signals planning is in-progress.)

**Why:** Prevent the mid-run halt where `/build-phase` evaluates a missing predicate and stops with "no predicate to evaluate". Catch at plan-review time so the fix lands BEFORE `/repo-sync` mints N issue bodies carrying the defect.

**Severity:** Blocker — plan cannot be synced to GitHub without this fix.

**Fix template:** Add a line immediately after the `**Type:** conditional` line:

```markdown
- **Condition:** <shell-expression that returns exit 0 to run the step, non-zero to skip>
```

**Examples of valid predicates:** Predicates are evaluated as bash expressions via `bash -c`. Use bash syntax even on Windows.

- `test -s documentation/findings/step-4-blockers.md` (file exists and is non-empty → run blocker-fix step)
- `test "$(jq '.failed | length' results.json)" -gt 0` (any failed items → run remediation step)
- `git diff --quiet HEAD~1 -- src/api/ || true` (always run; predicate is documentation-only)

If the operator does not yet know the predicate, the placeholder `**Condition:** <shell command returning exit 0 to run, non-zero to skip>` is acceptable for the planning conversation — `plan-review --autofix` (when implemented in Step 7) can auto-fill this placeholder.

### 24. Reviewer flag matches step shape (Significant Gap)

**Check:** For every `/build-phase`-compatible step whose `**Flags:**` line contains `--reviewers full` or `--reviewers runtime`, require an accompanying `**Start-cmd:** <command>` AND `**URL:** <url>` field (or equivalent indication of a running app available at review time). Skip this check for steps declared `**Type:** conditional` — their start-cmd applicability depends on the predicate outcome (the conditional may not run; see plan §8 Risk row).

**Why:** Avoid wasting `/build-phase` dispatch + worktree setup on a step that will fail `/build-step` pre-flight. SKILL.md edits, backend-only logic, and unit-test-only changes have no running UI to review — use `--reviewers code` instead. Per `.claude/rules/plan-and-issue-flow.md` § "Reviewer flag must match step shape" + Alpha4Gate Phase 4.6 incident.

**Severity:** Significant Gap (not Blocker — operator may have intentionally omitted runtime fields for a fast-iteration step). Surface so the operator either downgrades the flag or adds the runtime fields before `/repo-sync` mints the issue body.

**Fix template:** Either (a) downgrade the flag to match the step's actual shape:

```markdown
- **Flags:** --reviewers code
```

or (b) add the missing runtime fields beneath the existing `**Flags:**` line, citing `.claude/rules/plan-and-issue-flow.md` § "Reviewer flag must match step shape":

```markdown
- **Flags:** --reviewers full
- **Start-cmd:** <shell command that launches the app, e.g. `uv run python -m bots.current.runner --serve`>
- **URL:** <url the runtime reviewers will probe, e.g. `http://localhost:8766`>
```

**Example finding:**

> Step 5 declares `**Flags:** --reviewers full` but has no `**Start-cmd:** ` / `**URL:** ` fields. Either downgrade to `--reviewers code` (if the step's work is SKILL.md-only / backend-only / unit-test-only and has no running app to review) or add the runtime fields. Per `.claude/rules/plan-and-issue-flow.md` § "Reviewer flag must match step shape".

### 25. Plan format readiness for /build-phase (Blocker if table-only)

**Check:** Verify the plan is structurally parseable by `/build-phase`'s heading-based walker:

- (a) The plan contains at least one step heading matching the regex `^#{3,4} Step \d+:` (i.e., `### Step N: <name>` or `#### Step N: <name>`).
- (b) For each step heading found, the required fields `**Problem:**`, `**Type:**`, and `**Issue:**` are present somewhere in the step block (regex `^\s*-?\s*\*\*Problem:\*\*`, `^\s*-?\s*\*\*Type:\*\*`, `^\s*-?\s*\*\*Issue:\*\*`).
- (c) Note: a blank `**Issue:** #` (field present with no number filled in yet) is **expected** pre-`/repo-sync` — `/repo-sync` mints the issue and back-fills the number. This is a Reminder, not a defect.

**Why:** Catch table-only plans BEFORE `/repo-sync`. `/build-phase` walks `### Step N:` headings and fails Step 0 parse with "no steps found" on a table-only plan. Toybox Phase A incident: a 70-line mid-orchestration plan-extension was required to convert table-only → heading format after `/build-phase` halted.

**Severity matrix:**

- **Blocker:** plan is entirely table-only (no `### Step N:` or `#### Step N:` headings on any step) — incompatible with `/build-phase`.
- **Significant Gap (informational):** an individual step lacks a `**Type:**` field. This is already addressed by the existing **Default Type: code** autofix class (see the Autofix mode section's fix-class table below) — surfacing it here makes the defect visible in `--no-autofix` runs and in autofix output as the "auto-applied" line.
- **Reminder (Nice-to-have):** an individual step has a blank `**Issue:** #` field. This is **expected** pre-`/repo-sync`; not a defect, just a reminder that `/repo-sync` must run before `/build-phase`.

**Fix template (table-only Blocker case):** Convert each table row into a heading-format step block:

```markdown
### Step N: <step name>

- **Problem:** <one-line problem statement>
- **Type:** code
- **Issue:** #<N>
- **Files:** <files this step touches>
- **Done when:** <how to verify the step is done>
```

**Cross-reference note:** §25 checks **structural format** (heading regex + required field presence). §22 (operator+code split) and §23 (conditional `Condition:` predicate) check **content semantics**. Findings from these sections are distinct and may both fire on the same step.

### 26. Substrate-smoke step required when the plan touches deployment seams (Significant Gap)

**Check:** If any step in the plan modifies a **deployment seam** — production-invoked role/workflow wiring, model/harness/prompt configs read at runtime, deploy or install scripts, service units (systemd timers/services, scheduled tasks), or auth/secrets plumbing — the plan must contain at least one step (`Type: operator` or `Type: wait`) that runs the change against the **live substrate/environment** (real services, real CLIs, real scheduler — no mocks) before the phase can be declared done.

**Why:** Unit-green + review-pass is provably insufficient at these seams. Anchors: void_furnace's inert `models.toml` (the config was loaded but never consulted) survived 1,874 green unit tests and was caught only by a live soak (2026-06-04); four V1 substrate-only bugs survived 176 tests + 4-pass review (see `void_furnace/.claude/rules/substrate-testing.md`). The seam between the code and its environment cannot be exercised by tests that mock the environment.

**Severity:** Significant Gap — not a Blocker, because some plans genuinely have no deployment seam (pure-library changes, docs). But when the trigger matches and no smoke step exists, surface it with a proposed step the operator can accept.

**Distinct from §15.5:** §15.5 covers producer→consumer *data-shape* smoke gates (real components wired in-process). This check covers the *environment* seam — the change must be observed running under the real scheduler/service/CLI on the deployment target at least once.

**Fix template:**

```markdown
### Step N: Substrate smoke (Tier 1)
- **Problem:** Deploy the phase's changes to the live substrate and observe one real cycle end-to-end (doctor + one tick/invocation + verify the changed behavior in the journal/logs).
- **Type:** operator
- **Done when:** the changed behavior is observed in the live environment's own evidence (journal excerpt, service log, scheduler run history) — not inferred from tests.
```

---

## Output format

### Mode declaration (first line of every review)

The very first line of every review output declares which mode the skill is operating in:

```text
Reviewing as: feature plan. Sections 17–21 apply.
```

or

```text
Reviewing as: greenfield plan. Sections 17–21 skipped.
```

Use these EXACT strings (no rewording, no extra punctuation). The mode line is metadata about the review, not a finding — placing it before the severity-grouped findings prevents confusion (it would otherwise look like a "missing item" entry).

**Carve-out note (separate from the locked string above):** even when the declaration reads "Sections 17–21 skipped", §19's CLAUDE.md/AGENTS.md-conventions bullet and §21's step-sizing bullet still run in greenfield (per the §17–21 intro carve-out). This note is metadata beneath the declaration — the two EXACT mode strings are byte-unchanged.

**Sequencing with the Repo-sync-already-ran detection warning:** When BOTH the mode declaration AND the repo-sync warning fire, the warning is line 1 and the mode declaration is line 2 (warning sits ABOVE mode declaration). When ONLY the mode declaration fires (no populated `**Issue:**` fields), it is line 1.

### Repo-sync-already-ran detection (warning at top of output)

At the start of every review, scan the plan for non-blank `**Issue:** #<number>` lines (regex `^\s*-?\s*\*\*Issue:\*\*\s*#\d+`). If any step has a non-blank Issue field, emit this warning as the very first line of output, before any other content:

```text
[!] Detected non-blank Issue fields — repo-sync appears to have already run. Findings applied to plan.md will require corresponding `gh issue edit` updates (N+1 rework). See `feedback_plan_review_before_repo_sync.md`.
```

Use ASCII `[!]` (locked per plan §8 OQ1 + `feedback_python_unicode_print_windows` — do NOT use the Unicode warning glyph; it crashes on Windows cp1252 consoles).

This detection is a warning, not a Blocker — the review continues normally. The warning makes the N+1 rework cost observable so the operator can decide whether to proceed with edits (e.g., a small post-sync plan tweak) or roll the plan back to pre-sync state before running.

Group findings by severity:

**Blockers** — Must be resolved before implementation begins. Missing data store, unresolved
architecture, security hole, etc.

**Significant gaps** — Not blockers but will cause rework if not addressed early. Missing
error handling, ambiguous module contracts, undocumented setup steps.

**Missing items** — Concrete things that should exist but don't (files, configs, env vars,
docs sections).

**Nice-to-haves** — Improvements worth noting but not required for a working first version.

Include all four tiers in every review. If a tier has no findings, include the heading
followed by "None."

---

## Autofix mode (default ON)

`plan-review` runs in autofix mode by default. After producing severity-grouped findings, fixes that don't require operator judgment are auto-applied to plan.md. Findings that need operator judgment are still surfaced — autofix narrows the operator's attention to the items that genuinely need their input.

### Auto-applied fix classes

| Fix class | What it does | Source check |
|---|---|---|
| Operator+code split | Splits a `Type: operator` step whose `Produces:` includes a code-shaped artifact into adjacent `N-prep (code)` + `N (operator)` per §22. | §22 |
| Missing Done-when | Adds a `**Done when:** <TBD — operator fills in>` placeholder line to any step lacking the field. | (existing Done-when check) |
| Missing Files list | Greps the project tree for producer files matching the step's `**Files:**` declared paths; fills missing `**Files:**` from grep results. | (existing Files check) |
| Default Type: code | Adds `**Type:** code` to any step lacking a Type: field. | (existing Type check) |
| Placeholder Condition: | Adds `**Condition:** <shell command returning exit 0 to run, non-zero to skip>` placeholder to any `Type: conditional` step missing the field. | §23 (added in Step 2 of BPA plan) |

**Present-but-vague Done-when (surfaced Significant Gap — NOT autofixed).** Extends the missing-Done-when check above: a `Done when:` that is present but non-falsifiable / vague (e.g. `"it works"`, `"done"`) or not mapped to the step's `Problem:` is a **Significant Gap** surfaced for operator judgment — never auto-rewritten (the wording is theirs). EXEMPT the deferred sentinels in `../../references/step-authoring.md` §3 (they mean "not yet filled in", not "vague") — those stay silent in both modes.

Each fix applied adds an HTML comment `<!-- autofix-applied: YYYY-MM-DD -->` immediately above the modified step heading in plan.md. `/plan-expedite` uses these markers for resume detection — re-runs scan for these markers to skip already-applied fixes.

The `YYYY-MM-DD` portion is strict ISO 8601 calendar-date format (no time, no timezone, no whitespace, e.g., `2026-05-18`). Both `/plan-review --autofix` (when writing) and `/plan-expedite` (when grepping for resume detection) must match the literal regex `<!-- autofix-applied: \d{4}-\d{2}-\d{2} -->`.

### `--no-autofix` opt-out

When `/plan-review --no-autofix` is invoked, the skill surfaces ALL findings as recommendations without modifying plan.md. The output uses the original "Want me to update the plan to address these, or discuss any first?" trailing line (preserved verbatim from the pre-autofix flow). Use this when:
- You want to review fixes manually before applying
- You're auditing the plan and don't want side effects
- A previous autofix run produced unexpected changes you want to compare against fresh recommendations

### Output template (autofix ON)

After the severity-grouped findings, the report ends with:

```text
Auto-applied N fixes:
  - <fix class>: <step N>
  - ...

M items need your input:
  - <finding 1 + clarifying question>
  - ...
```

If N = 0 (no auto-fixable items), omit the "Auto-applied" block — the report ends with the "M items need your input" block only (or the existing "Want me to update the plan to address these, or discuss any first?" line if also no clarifying items). **Exception:** on a re-run where all defects were already-applied in a prior run (skipped via marker-detection), emit "Auto-applied 0 fixes. Plan is ready for `/plan-wrap` and `/repo-sync`." instead of omitting — the explicit 0-count signals successful idempotent re-run to `/plan-expedite` and the operator. See **Re-run behavior** below.

If M = 0 (no items need input but >=1 autofix applied), the report ends with "Auto-applied N fixes. Plan is ready for `/plan-wrap` and `/repo-sync`."

### Re-run behavior

`/plan-review --autofix` is **idempotent** on already-applied fixes. Before applying any fix class to a step, scan for an `<!-- autofix-applied: <ISO-date> -->` HTML comment immediately above the step's `### Step N:` heading. If present, skip ALL autofix classes for that step (the step has already been processed in a prior run). New fixes (different steps) still apply normally.

Re-running on a plan with no new defects emits "Auto-applied 0 fixes. Plan is ready for `/plan-wrap` and `/repo-sync`." (the N=0/M=0 trailing line).

### Relationship to `/build-phase` runtime safety-net

`/plan-review --autofix` is the **plan-time** preferred path for the §22 operator+code split. `/build-phase` includes a complementary **runtime safety-net** that auto-splits any `Type: operator` step whose `Produces:` includes a code artifact at orchestration time (so an un-autofixed plan still won't halt mid-build). The two are complementary; fixing at plan time keeps issue bodies and the audit trail consistent (per `feedback_plan_review_before_repo_sync`).

---

## Clarifying questions

After presenting findings, check whether any require user input to resolve. Common cases:

- Unresolved "X or Y" decisions (e.g., "NextAuth or Clerk?")
- Vague requirements where multiple valid approaches exist
- Missing context that only the user can provide (target users, scale, deployment env)
- Ambiguous scope boundaries ("probably X" or "maybe Y")

**Trailing-line selection (autofix-mode-dependent):**

- **Default (autofix ON):** Use the "Auto-applied N fixes. M items need your input:" output template from the **Autofix mode** section above. The clarifying-question list is rendered under the "M items need your input:" bullet block instead of the standalone "Clarifying questions" heading. The legacy "Want me to update..." line is NOT emitted.
- **`--no-autofix`:** Use the legacy flow below — render the **Clarifying questions** heading + numbered list, then emit the exact closing line "Want me to update the plan to address these, or discuss any first?" verbatim and unchanged.

If there are clarifying questions (legacy `--no-autofix` flow):

1. Present a numbered list of clarifying questions under a **Clarifying questions** heading (skip this step if there are none).
2. After the list (or in its absence), end every review with this EXACT closing line as its own paragraph, verbatim and unchanged: "Want me to update the plan to address these, or discuss any first?"
3. Wait for the user's answers (if any).
4. After receiving answers, update the plan file directly to resolve each answered item — replace TBDs with decisions, add missing sections, and tighten vague wording.
5. After updating, briefly summarize what was changed (file path, sections modified) so the user can verify.

If there are NO clarifying questions (all findings can be resolved without user input):

1. Skip step 1 above and go straight to the closing line in step 2

---

## Usage

When invoked, read the plan file (ask the user for the path if not obvious), then determine
which mode applies:

- **Greenfield plan** — the file is `plan.md` or describes a full project from scratch.
  Apply sections 1–16 AND sections 22–25. Skip sections 17–21, EXCEPT §19's conventions bullet and §21's step-sizing bullet (both apply in greenfield — see `../../references/step-authoring.md` §1).
- **Feature plan** — the file is in `documentation/*-plan.md` or describes a scoped change
  to an existing project. Apply sections 1–16 (skipping those irrelevant to the feature's
  scope) AND sections 17–25. For sections 17–21, actively read the codebase to validate
  the plan's claims.

**Pre-review detection (repo-sync state):** Before applying any mode-specific checks, scan the plan for non-blank `**Issue:** #<number>` fields per the "Repo-sync-already-ran detection" clause in the Output format section above. If any are present, emit the `[!]` warning as the first line of output; the review continues normally.

**Mode declaration:** After (or before, if no warning fires) the repo-sync detection, the skill emits the mode declaration line per the "Mode declaration" clause in the Output format section. This makes the mode selection observable — silent wrong-mode selection is no longer possible.

Section 22 (operator/code step-shape integrity), Section 23 (conditional-step Condition predicate), Section 24 (reviewer flag matches step shape), and Section 25 (plan format readiness for /build-phase) run on **every** plan that contains
`/build-phase`-compatible build steps — both modes apply them.

Work through the checklist sections that are relevant to the plan's architecture. Skip
sections that do not apply (e.g., do not raise async/concurrency concerns for a purely
synchronous CLI tool, do not raise UI error surfacing for a headless service). Cite
specific plan sections by name when raising an issue. Be direct — name the gap, explain
why it matters, suggest the fix.

After the severity-grouped findings, follow the clarifying questions flow above. The goal
is to leave the plan in a better state after every review — not just list problems.


---

## dev-observatory hook (additive; see [`.claude/rules/descriptor-contract.md`](../../rules/descriptor-contract.md))

**Control-plane checks (additive).** Confirm: (1) the plan lives at a **discoverable canonical path** — `plan.md` or `master_plan.md` in the project root or `plans/`/`docs/`/`documentation/` (per [`.claude/rules/descriptor-contract.md`](../../rules/descriptor-contract.md) §4) so the control-plane observer + tooling can find it; (2) it carries a **scrapable goal** (a `## 1. What This Is` section or labeled objective); (3) for a built-vs-planned signal, it has **scrapable step/phase units** inline (`### Step N:` with `**Status:**` markers, or `## Phase` headings) — a pure pointer/index plan that only links to sub-plans yields a goal but no progress ratio (the observer shows `gap = -`); (4) declared ports don't collide with the registry (`observatory ports`). All Nice-to-have findings, not blockers.
