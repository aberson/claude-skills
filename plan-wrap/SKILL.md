---
name: plan-wrap
description: Check whether a document (plan, spec, README) is self-contained for a model with no prior conversation history. Finds anything a fresh model would need but can't derive from the document alone. Use after plan-init or plan-review, or any time a document will be handed to a new model or agent.
user-invocable: true
---

# Clean-Context Check

Read a document (ask the user for the path if not obvious) and determine whether a model
with **zero prior context** — no conversation history, no other files — could read it and
act on it correctly.

Note this differs from `plan-review`, which checks for technical gaps. This skill checks
for *self-sufficiency*: everything needed to understand and act on the document must be
present inside it.

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--autofix` | no | true (default ON) | Auto-apply fixes that don't need user judgment (missing schema summaries, bare `<id>` placeholders, operator+code splits, placeholder Condition:). Findings requiring judgment are still surfaced under "Needs your input:". |
| `--no-autofix` | no | -- | Opt out of autofix. Surface ALL findings as recommendations; do not modify plan.md. For operators who want to review before applying. |

---

## Proof discipline

Always cite the specific section, line, or phrase in the document that triggered the finding:

- Do not state "schemas are missing" without quoting the entity name that lacks a schema.
- Do not state "this term is unexplained" without quoting the term and where it first appears.
- Findings without citations will be treated as unsubstantiated.

Use this three-line shape for findings:

```markdown
**[Severity]** §<n> — <what is missing>
Found at: "<quoted phrase>" (Step N, <subsection>)
Fix: <concrete suggestion>
```

## Completion gate (run first)

Plan-wrap is a *forward* check: "could a fresh-context model **build** this document?" When every
build unit is already shipped, that question has no target -- there is nothing left to build, so the
fresh-context buildability check is moot. Run this gate before the Checklist to decide which pass to run.

**Check:** First pick the *build unit* -- the most granular completion-markable heading the document
actually uses: `### Step N:` headings if present, otherwise `## Phase` / `### Phase` headings. A plan that
marks phases rather than steps is classified over its phase headings. Then scan those headings (and their
adjacent status lines) for a completion marker, reusing the vocabulary `/build-phase` keys on:

- **Canonical:** the markdown-bold line `- **Status:** DONE` (optionally suffixed ` (YYYY-MM-DD)` when
  `/build-phase` wrote it on a step PASS) -- this is the proven form `/build-phase` Step 0 actually scans.
- **Operator-authored variants** (recognized for hand-written master plans): a bold status line whose
  value is `DONE` or `COMPLETE` (`**Status:** COMPLETE`, `**Status: COMPLETE**`), or a `✅` attached to a
  step/phase heading or a markdown table row enumerating that unit.

A marker counts only when it attaches to a build-unit heading or its `Status:` line. **Never** treat the
`**Done when:**` acceptance-criteria field, or the words "complete" / "done" / "shipped" appearing inside
narrative prose, as a completion marker -- those are different tokens and would false-positive. Classify
the document into exactly one of three states, then branch:

1. **All build units complete** -- every Step (or, for a phase-marked plan, every Phase) the document
   defines carries a recognized completion marker, AND the document defines at least one such unit. The
   forward buildability check is moot. Emit exactly one preamble line --
   `Completion gate: plan fully executed; fresh-context buildability check N/A -- running reduced doc-accuracy pass.`
   -- then **downshift to the reduced doc-accuracy pass** below instead of the full forward Checklist.

2. **Some units complete, at least one still unbuilt** (the common multi-phase case: Phase N shipped,
   Phase N+1 pending; or a step missing a marker while siblings have one) -- the document is still a build
   target for the unbuilt units. Run the **FULL Checklist** as today, focusing self-sufficiency scrutiny on
   the unbuilt units -- those are what a fresh model will actually build. Emit:
   `Completion gate: N of M build units (steps/phases) complete; <M-N> still unbuilt -- running full check, focused on unbuilt units.`

3. **No build units defined, OR markers absent, OR markers inconsistent** -- if the document defines no
   step/phase headings carrying a recognized marker, treat markers as ABSENT (never as vacuously
   all-done); or if the markers cannot be read as a clean all-done state -- **default to the FULL
   Checklist.** Fail safe toward checking, never toward silent skipping: any doubt about completeness
   resolves HERE, not into branch 1. Emit:
   `Completion gate: no consistent completion markers found -- running full check (fail-safe default).`

**Why:** A fully-shipped plan run through the forward Checklist produces spurious "not self-contained for
a fresh builder" findings against a document nobody will build from again -- wasted attention on a moot
question. But under-checking is worse than over-checking, so any doubt resolves to the FULL pass. This
mirrors `/build-phase` Step 0's already-done detection; reusing its marker vocabulary keeps the two skills
from disagreeing about what "done" means.

### Reduced doc-accuracy pass (branch 1 only)

When the gate downshifts, the question flips from "could a fresh model build this?" to *"does this
document accurately record what was built?"* -- a **backward-looking** pass. Check only these criteria and
fold them into the existing Checklist taxonomy; do NOT invent new numbered sections:

- **(a) Referenced files still exist** and **(b) no dangling references to deleted artifacts** -- report
  under **§9 Referenced external files**. For each concrete file path the document names, confirm it
  still exists (`test -f` / `ls`); a path pointing at a since-deleted or renamed artifact is a §9 **Gap**
  (the doc now misrecords reality). Paths containing glob or template segments (`*`, `{...}`, `<...>`, `vN`)
  are not file-existence-checkable -- note them as N/A; do NOT flag them as dangling §9 Gaps and do NOT
  silently skip them.
- **(c) Status markers internally consistent** -- report under **§5 Unresolved decisions** (or as a
  gate-preamble Minor line if no §5 content applies): flag contradictory or partial markers (e.g. a unit
  marked complete while a later sentence calls it pending) as **Minor**, or **Gap** if it would mislead a
  future maintainer.

Emit the output exactly as **Output format** specifies: still print all twelve `§N` summary lines, in
order, with verbatim section names. Mark every forward-only section moot with
`§N <name> -- N/A: plan fully executed`, and record reduced-pass findings on the §9 / §5 lines
where they belong. Still print all three severity tiers (Blocker / Gap / Minor, `None` under empty tiers).
Resolve to one of the four existing verdicts -- the reduced pass has no Blocker classes (all Blocker checks
are forward-only §11 / §12), so it lands on `READY` (clean) or `READY WITH GAPS: M gaps` (a stale
§9 reference or §5 marker inconsistency surfaced). The gate introduces no fifth verdict and no
§13+ section. `--autofix` applies no writes in branch 1.

---

## Checklist

### 1. Schemas and data structures
- Every data structure mentioned by name has its fields defined or summarized inline.
- Arrays like `jobs[]` or `CandidateProfile` have their shape shown — even a summary table.
- External files referenced (JSON configs, profile files, seed data) are described, not
  just named.

Use this minimum-acceptable inline summary template (markdown table; only fields the plan step uses):

```markdown
`<TypeName>` shape:
| field | type | note |
|---|---|---|
| <field-name> | <type-string> | <constraint/range/role> |
```

Note that a one-row summary table counts; the full schema does not need to be inlined. Anchor incident: Alpha4Gate Phase 4 planning named the reward schema verbatim but mis-paraphrased its shape, producing a wrong reward-schema Blocker (B1) and missing API response shapes (Gaps G1-G3, G7). All were preventable with one Read tool call to the producer file. See `.claude/rules/plan-and-issue-flow.md` § "Read producers before drafting plan content".

### 2. Identifiers
- Every entity ID (job ID, user ID, record key) has its format explicitly defined:
  what it is (UUID, hash, slug), how it is generated, and what it is used for.
- No bare `<id>` or `<job-id>` placeholders without a definition.

Use this identifier definition template (one bullet per ID):

```markdown
- `<id-name>`: `<format>: <example>`. Generated by: `<fn-or-module>`. Used by: `<consumer>`.
```

Run `grep -nE '<id>|<uuid>|<step.id>|format:.*<id>' plan.md` to spot bare-ID references. Anchor incident: Alpha4Gate Phase 4.6 Step 1 changed `SC2Env._game_id` shape but missed the downstream caller `evaluator._get_game_result(base_id)`; soak-4 spent ~70 minutes with 12 eval games flagged "crashed" before DB forensics found the missed caller. Define the format once in the plan so all steps reference the same definition. See `.claude/rules/code-quality.md` § "Grep all downstream consumers when changing a key/id shape".

### 3. Acronyms and tool names
- Every tool, framework, acronym, or project-specific term is explained on first use.
- Do not assume the reader knows what "RWL", "OpenClaw", "Whisper", "Zod", etc. are
  without a one-line description.

### 4. Stack decisions with rationale
- Every technology choice has a stated reason ("why" column in a table, or an inline note).
- No orphaned tool choices like "use Fastify" without context.

### 5. Unresolved decisions
- No "X or Y" language remaining — every choice is resolved to a single answer.
- No "TBD", "to be decided", or "we may want to…" language.

Use this grep recipe — signal patterns to surface candidate unresolved decisions:

```bash
grep -nE 'TBD|to be decided|X or Y|we may want|optionally|consider using|might use|could use' plan.md
```

Note the range-vs-decision disambiguation: range values (e.g., "8-16 KB max body size", "accepts integer or string input") are deliberate parameterization, not deferred decisions. The patterns above target operator-judgment items: TBDs, undecided libraries/services, alternative-listing without commitment. Unresolved decisions are Gaps by default (`/repo-sync` may proceed) and always surface under "Needs your input:" — autofix cannot resolve them because they require operator judgment.

### 6. API contracts
- If the project has a backend API, every route is documented with method, path, request
  shape, and response shape.
- Route documentation uses concrete type names, not vague descriptions.

### 7. Development process
- The process for building, testing, and deploying is described in enough detail that
  a fresh model could execute it.
- If a special loop or framework (like RWL) is used, it is summarized inline — the reader
  should not need to look it up.

### 8. Quickstart / how to run
- There is a step-by-step section covering: install, configure, first run.
- First-run configuration steps (env vars, secrets, seed data) are explicit.
- Any one-time system-level setup (ffmpeg, Python packages, browser install) is called out.

### 9. Referenced external files
- Any file path mentioned in the document is either included, summarized inline, or
  described well enough that its absence is not a blocker.
- Secrets and credentials are documented by name and loading mechanism (not value).

### 10. Scope and constraints
- What is out of scope for the current version is stated clearly.
- Constraints (never submit forms, never duplicate data, never claim X experience) are
  explicit and findable.

### 11. Operator/code step-shape integrity (Blocker if violated)
- For every step declared `Type: operator`, the `Produces:` list must NOT include a
  code-shaped artifact (source file, shipped config, code-dependent ops doc).
- For every step declared `Type: code`, the `Done when:` list must NOT include an
  operator-presence requirement (visual review, run-and-confirm, manual spot-check).
- A fresh-context `/build-phase` agent reads `Type:` and dispatches accordingly. A
  step that's a code/operator hybrid forces the agent into either a mid-build halt
  (breaks the autonomous build) or a silent rule-break (violates plan shape).
- This is the deeper pass `/plan-review` Section 22 already runs. Plan-wrap repeats
  it because the gap is high-cost (mid-build operator interruption) and trivial to
  catch at doc-scan time.
- Fix at plan level: split into adjacent `N-prep (code) + N (operator)` steps.
- See `.claude/rules/plan-and-issue-flow.md` § "Operator-type steps must not produce
  code artifacts".

### 12. Conditional steps must declare a Condition: predicate (Blocker)

**Check:** For every step with `**Type:** conditional`, the step must also have a non-empty `**Condition:** <shell-expression>` field. A missing field OR a present-but-empty/whitespace-only value are both Blockers. (The placeholder text `<shell command returning exit 0 to run, non-zero to skip>` is acceptable and not "empty" — it signals planning is in-progress.)

**Why:** `/build-phase` evaluates this predicate at conditional-step dispatch time (exit 0 → run, non-zero → skip). A `Type: conditional` step without a `Condition:` field forces `/build-phase` to halt mid-run with "no predicate to evaluate" — exactly the kind of mid-build halt the autonomy contract aims to eliminate. Catching it at plan-wrap time means the plan can be fixed BEFORE `/repo-sync` mints N issue bodies that propagate the defect.

**Severity:** Blocker — plan cannot be synced to GitHub without this fix.

**Fix template:** Add a line immediately after the `**Type:** conditional` line:

```markdown
- **Condition:** <shell-expression that returns exit 0 to run the step, non-zero to skip>
```

**Examples of valid predicates:** Predicates are evaluated as bash expressions via `bash -c`. Use bash syntax even on Windows.

- `test -s documentation/findings/step-4-blockers.md` (file exists and is non-empty → run blocker-fix step)
- `[ "$(jq '.failed | length' results.json)" -gt 0 ]` (any failed items → run remediation step)
- `git diff --quiet HEAD~1 -- src/api/ || true` (always run; predicate is documentation-only)

Use the placeholder `**Condition:** <shell command returning exit 0 to run, non-zero to skip>` when the operator does not yet know the predicate — acceptable for the planning conversation — and `plan-wrap --autofix` (when implemented in Step 8) can auto-fill it.

**Placeholder-only Condition: sub-check (Minor).** A `Condition:` whose value is the literal placeholder `<shell command returning exit 0 to run, non-zero to skip>` — or any angle-bracket-only content matching `<...>` with no real shell expression — is valid intermediate planning state but emits a **Minor** finding citing the step. Rationale: the operator can let it ride through `/repo-sync`, but should know that `/build-phase` will halt at dispatch unless the placeholder is replaced before then (see `.claude/rules/code-quality.md` § "Build-phase halt contract" — placeholder Condition: is one of the listed runtime halt classes). Minor: does NOT change the verdict tier (`READY` / `READY WITH GAPS` / `NEEDS WORK` unchanged) and does NOT trigger autofix (operator judgment required to write the real predicate).

Note this is the deeper pass `/plan-review` §23 already runs. Plan-wrap repeats it because the gap is high-cost (mid-build halt) and trivial to catch at doc-scan time — same rationale as §11.

### 13. Substrate-smoke step present when the plan touches deployment seams (Significant Gap)

**Check:** If any step modifies a **deployment seam** — production-invoked role/workflow wiring, model/harness/prompt configs read at runtime, deploy or install scripts, service units (systemd timers/services, scheduled tasks), or auth/secrets plumbing — the plan must contain at least one `Type: operator` or `Type: wait` step that observes the change running against the **live substrate/environment** (real services, real CLIs, real scheduler — no mocks) before the phase is declared done.

**Why:** Unit-green + review-pass is provably insufficient at the code↔environment seam: void_furnace's inert `models.toml` survived 1,874 green unit tests until a live soak caught it (2026-06-04), and four V1 substrate-only bugs survived 176 tests + 4-pass review (`void_furnace/.claude/rules/substrate-testing.md`). Tests that mock the environment cannot exercise the seam.

**Severity:** Significant Gap — some plans genuinely have no deployment seam (pure-library, docs-only); when the trigger matches and no smoke step exists, propose one.

Note this mirrors `/plan-review` §26 — plan-wrap repeats it for the same belt-and-suspenders rationale as §11/§12: the gap is high-cost (a whole phase declared done on unit-green alone) and trivial to catch at doc-scan time.

---

## Output format

Check **every** checklist item (1–13) in the output:
- Items with issues: state which section triggered it, what is missing, and a concrete suggestion.
- Items that pass: include a one-line note confirming no issues found (e.g., "**Schemas** — all data structures have fields defined. No issues.").
- Items not applicable to this document (e.g., API contracts for a CLI tool with no backend): note as N/A with a brief reason.

Write findings one line per §N, in order. Each line has the form `§N <name> — [pass | findings: <count>]` (or `§N <name> — N/A: <reason>` when the section doesn't apply to this plan). Section names must match the Checklist verbatim:

```text
§1 Schemas and data structures — pass
§2 Identifiers — findings: 2
§3 Acronyms and tool names — pass
§4 Stack decisions with rationale — findings: 1
§5 Unresolved decisions — pass
§6 API contracts — N/A: CLI tool, no backend
§7 Development process — pass
§8 Quickstart / how to run — findings: 1
§9 Referenced external files — pass
§10 Scope and constraints — pass
§11 Operator/code step-shape integrity (Blocker if violated) — pass
§12 Conditional steps must declare a Condition: predicate (Blocker) — pass
```

Apply severity grouping (always show all three tiers, even if a tier has no findings — print "None" under empty tiers):
- **Blocker** — a fresh model would make a wrong decision or get stuck without this
- **Gap** — a fresh model could probably guess, but shouldn't have to
- **Minor** — cosmetic or low-stakes ambiguity

Always end with a one-line verdict. There are exactly four mutually-exclusive verdict variants, exhaustive over the (Blocker-count, Gap-count, autofix-applied-count) tuple:

- `READY` — 0 Blockers, 0 Gaps (autofix off, OR autofix on with 0 autofixes applied). Document is self-contained.
- `READY (auto-fixed N items)` — 0 Blockers, 0 Gaps (autofix on, N≥1 autofixes applied). Document is self-contained after autofix.
- `READY WITH GAPS: M gaps` — 0 Blockers, M≥1 Gaps (autofix on or off). `/repo-sync` may proceed; Gaps surface for operator awareness but are not halt-class ("a fresh model could probably guess, but shouldn't have to").
- `NEEDS WORK: N blockers, M gaps` — N≥1 Blockers (any Gap count). At least one Blocker autofix could not resolve, or autofix was off; operator must fix before `/repo-sync`.

(See **Verdict format (autofix-aware)** below for the emission rules per autofix state.)

---

## Autofix mode (default ON)

Run `plan-wrap` in autofix mode by default. After producing severity-grouped findings, fixes that don't require operator judgment are auto-applied to plan.md. Findings that need operator judgment are surfaced under a `Needs your input:` section — autofix narrows the operator's attention to the items that genuinely need their input.

### Auto-applied fix classes

| Fix class | What it does | Source check |
|---|---|---|
| Missing schema summary | Grep producer file for schema shape; paste in plan body | (existing schema check — §1) |
| Bare `<id>` placeholder | Replace with the project's convention (e.g., `kebab-case`, `snake_case`) inferred from sibling steps in the same plan | (existing placeholder check — §2) |
| Operator/code split | Splits a `Type: operator` step whose `Produces:` includes code into N-prep + N | §11 (added by commit 557b946) |
| Placeholder `**Condition:**` | Adds `**Condition:** <shell command returning exit 0 to run, non-zero to skip>` to any `Type: conditional` step missing it | §12 (added by Step 2 of BPA plan) |

Add an HTML comment `<!-- autofix-applied: YYYY-MM-DD -->` immediately above the modified step heading in plan.md for each applied fix. The `YYYY-MM-DD` portion is strict ISO 8601 calendar-date format (no time, no timezone, e.g., `2026-05-18`). Both `/plan-wrap --autofix` (when writing) and `/plan-expedite` (when grepping for resume detection) must match the literal regex `<!-- autofix-applied: \d{4}-\d{2}-\d{2} -->`. This is the same marker format used by `/plan-review --autofix` so the two skills' resume-detection contracts align.

### Re-run behavior

Run `/plan-wrap --autofix` idempotently on already-applied fixes. Before applying any fix class to a step, scan for an `<!-- autofix-applied: <ISO-date> -->` HTML comment immediately above the step's `### Step N:` heading. If present, skip ALL autofix classes for that step. New fixes (different steps) still apply normally.

**Cross-skill marker collision (known limitation):** `/plan-review --autofix` writes the SAME marker. If plan-review autofix already touched a step (e.g., for a Missing Done-when fix that plan-wrap doesn't cover), plan-wrap will see the marker and skip its OWN unique fix classes (Missing schema summary, Bare `<id>` placeholder) on that step. The finding still surfaces under "Needs your input:" — only the autofix WRITE is suppressed, the SURFACE check still runs. Operator can apply the plan-wrap-unique fix manually, or run plan-wrap before plan-review to reverse the order.

### Verdict format (autofix-aware)

Note the four variants are mutually exclusive and exhaustive over (Blocker-count, Gap-count, autofix-applied-count) tuples:

- **READY** — 0 Blockers, 0 Gaps, 0 autofixes applied. Pre-existing verdict, unchanged.
- **READY (auto-fixed N items)** — 0 remaining Blockers, 0 Gaps, N≥1 autofixes applied. Emit when --autofix is on and ≥1 fix was applied with zero remaining Blockers and zero Gaps.
- **READY WITH GAPS: M gaps** — 0 Blockers, M≥1 Gaps. Emit regardless of autofix state (Gap classes have no autofix mappings; Gaps remain Gaps in both autofix-on and --no-autofix runs). `/repo-sync` may proceed; surface the Gaps under "Needs your input:" for operator awareness.
- **NEEDS WORK: N blockers, M gaps** — ≥1 Blocker that autofix could not resolve (autofix-on) or any unresolved Blocker (--no-autofix). Surface remaining items under "Needs your input:" section.

Note that when --no-autofix is set, only three of the four variants are reachable: `READY` (0/0), `READY WITH GAPS: M gaps` (0/M≥1), and `NEEDS WORK: N blockers, M gaps` (N≥1). The `READY (auto-fixed N items)` variant requires --autofix to be on.

### `--no-autofix` opt-out

Use `/plan-wrap --no-autofix` to surface ALL findings as recommendations without modifying plan.md. Pick this mode when:
- You want to review fixes manually before applying
- You're auditing the plan and don't want side effects
- A previous autofix run produced unexpected changes you want to compare against fresh recommendations

### Output template (autofix ON)

```text
Verdict: READY | READY (auto-fixed N items) | READY WITH GAPS: M gaps | NEEDS WORK: N blockers, M gaps

Auto-applied fixes (N):
  - <fix class>: <step N>
  - ...

Needs your input (M):
  - <finding 1 + clarifying question>
  - ...

Next: <action recommendation>
```

Apply this verdict selection (one of the four; mutually exclusive and exhaustive):
- 0 Blockers, 0 Gaps, 0 autofixes applied → `READY`; omit both "Auto-applied fixes" and "Needs your input" sections.
- 0 remaining Blockers, 0 Gaps, N ≥ 1 autofixes applied → `READY (auto-fixed N items)`; omit the "Needs your input" section.
- 0 Blockers, M ≥ 1 Gaps → `READY WITH GAPS: M gaps`; surface the Gaps under "Needs your input"; `/repo-sync` may still proceed.
- N ≥ 1 Blockers → `NEEDS WORK: N blockers, M gaps`; surface remaining Blockers (and any Gaps) under "Needs your input".

---

## When to use

- After `/plan-init` produces a draft plan
- After `/plan-review` resolves technical issues
- Any time the document will be given to a new model, agent, or human collaborator
  with no prior context
- Before starting a long autonomous build session where clarification mid-way is costly

**Pipeline position matters: run plan-wrap AFTER `/plan-review` and BEFORE `/repo-sync`.**

Run plan-wrap before `/repo-sync` to collapse the N+1 edit cost to 1. Rationale:

- `/repo-sync` mints fresh-context-LLM issue bodies straight from the plan; any self-sufficiency defect that survives past that point becomes an **N+1 edit cost** — 1 edit to the plan plus N edits to the N already-minted issue bodies.
- Toybox iPad-Kiosk burned ~30 min on 6 issues.
- Alpha4Gate Phase 4 hit blank `Issue: #` lines mid-build.
- Cross-plan slug collisions only surface at plan-wrap time.
- `/plan-expedite` chains `plan-review → plan-wrap → repo-sync` in the correct order by default; see `.claude/rules/plan-and-issue-flow.md` § Order for the canonical sequence.


---

## dev-observatory hook (additive; see [`.claude/rules/descriptor-contract.md`](../../rules/descriptor-contract.md))

**Control-plane check (additive).** Confirm the plan carries a clearly-labeled, scrapable goal/objective near the top (dev-observatory's goal-vs-reality observer extracts it from `## 1. What This Is` + step `Problem:` fields). Minor finding, not a blocker.
