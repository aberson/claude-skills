---
name: review-deep
description: Six-lens code review (correctness, bugs, security, tests, style, plan-conformance) with anti-pattern catalog, severity+evidence, JSON audit trail. Use for high-stakes diffs; use the leaner review-gauntlet profile for routine diffs.
user-invocable: true
---

# Review Deep

> **Judging doctrine:** the producer-grader split, evidence-on-every-verdict, deterministic-aggregation, and primary-owner dedup rules this skill runs on live in [`_shared/judge-core.md`](../_shared/judge-core.md) — this skill is one of its reference implementations (§10). It instantiates the doctrine for the code-review domain.

The full-depth engine behind `review-gauntlet`'s lean profile. Runs six standing
review lenses (correctness, bugs, **security**, test quality, style,
plan-conformance), with explicit Tier-1 anti-pattern detection, per-lens model-tier selection,
severity tiers + cited evidence on every finding, an auth-gated runtime
downgrade, a scope-boundary `DEFERRED-TO-UAT` verdict for things only an
operator can confirm, and a JSON sidecar that captures the full audit trail.
`review-gauntlet` is a lean profile over this engine — use this
skill when the diff is high-stakes (substrate changes, schema/key-shape
changes, producer-consumer chains, anything where a silent miss is expensive)
and the leaner gauntlet profile when the diff is routine.

---

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--prompt` | yes | -- | Developer intent: what the diff is supposed to accomplish (may be passed inline) |
| `--diff` | yes | -- | The diff to review: PR number, `git diff` mode, or explicit paste |
| `--plan-step` | no | -- | `<plan-file-path>:<step-id>` — enables the plan-conformance lens |
| `--reviewers` | no | `code` | `code`, `runtime`, or `full` — review lane selection |
| `--model-override` | no | -- | `<lens>=<tier>` — per-lens model tier override (repeatable) |
| `--force-runtime` | no | false | Skip the auth-gate downgrade probe and run runtime reviewers anyway |
| `--url` | no | -- | Base URL for runtime probe (required when `--reviewers runtime` or `full`) |
| `--start-cmd` | no | -- | Shell command to start the app (required when `--reviewers runtime` or `full`) |
| `--output-dir` | no | `.review-deep/` | Where to write the JSON audit-trail sidecar |
| `--prior-sidecar` | no | -- | Path to the previous run's audit-trail JSON sidecar. Enables aggregator rule 6 (persistent disagreement escalation). When absent, rule 6 never fires. |

---

## Inputs

The invoker must provide three categories of input (the third is optional):

1. **Prompt** — the developer's intent (what the diff is supposed to accomplish).
2. **Diff** — the code diff to review. Can be provided as:
   - A `git diff` output (staged, unstaged, or between commits)
   - A PR number (the skill will fetch the diff via `gh pr diff`)
   - An explicit paste of the changed code
3. **Plan step (optional)** — `--plan-step <plan-file-path>:<step-id>` points at
   a plan document and a step number, where `<step-id>` matches the integer N
   from a `### Step N:` heading inside the plan file. When supplied, the
   plan-conformance lens reads that step as ground truth and checks the diff
   against its Problem / Done-when / Produces fields. If `--plan-step` is
   omitted, the plan-conformance lens is **skipped gracefully** — the
   aggregated report notes the skip but does NOT treat it as an error.

If the user doesn't provide a prompt or diff, ask before proceeding.

---

## Gathering context

Before spawning reviewers, collect the inputs:

```bash
# If a PR number is given:
gh pr diff <NUMBER>

# If reviewing staged changes:
git diff --cached

# If reviewing working tree:
git diff

# If reviewing a branch vs base:
git diff <base>..HEAD
```

Also read the surrounding source files that the diff touches so reviewers have
context on existing code patterns, conventions, and the producer/consumer
chain. When `--plan-step` is supplied, also read the referenced plan file and
extract the matching `### Step N:` section as ground-truth input for the
plan-conformance lens.

---

## Reviewer lenses

The skill spawns six fresh-context sub-agents, one per lens, **all in ONE tool message** (a single assistant turn carrying the lens calls in parallel — serial spawning only adds wall-clock for zero independence gain; independence comes from the context isolation below, not serial order; see `dev/.claude/rules/subagent-economy.md`). Dispatch each lens with its table-assigned tier (§ Model-tier selection) — arms never inherit an escalated session (tier policy, CLAUDE.md model paragraph). Each lens is a
single-shot pass; iteration is the orchestrator's job (`/build-step --max-iter`).
Each lens runs in isolation (no cross-lens chatter) so verdicts aren't biased
by sibling findings (see `docs/investigations/review-agents/02-reviewer-dimensions.md`
and `docs/investigations/review-agents/32-prompt-scoping.md`).

**Standing lens list:**

1. [Correctness](#correctness-lens) — diff vs stated intent
2. [Bugs](#bugs-lens) — defects in the diff itself
3. [Security](#security-lens) — adversarial-input / secrets / unsafe-config defects per `.claude/rules/security.md`
4. [Test quality](#test-quality-lens) — focus, trim, missing critical coverage
5. [Style and conventions](#style-and-conventions-lens) — surrounding-code conformance
6. [Plan-conformance](#plan-conformance-lens) — diff vs the named plan step (skipped if `--plan-step` absent)

**Universal evidence discipline (applies to all six lenses):** every finding
cites `file:line` + excerpt + reasoning. Findings without citations are dropped
during aggregation. See `docs/investigations/review-agents/13-evidence-requirements.md`
for the full discipline (the reviewer-side counterpart to `/review-proof`).

**Universal severity rubric** (`docs/investigations/review-agents/14-severity-tiers.md`):

| Severity | Meaning | Triggers |
|---|---|---|
| `Block` | Must fix before merge | Bug with high severity; correctness gap; plan Done-when not satisfied; producer-consumer drift; codifying-test-diff; silent-wiring; security finding (owned by the Security lens — injection-as-data, secret-dump, unsafe-config-without-startup-guard per `.claude/rules/security.md`); CREATE TABLE w/o migration |
| `Nit` | Should consider | Convention deviation; medium-severity bug; test redundancy; suboptimal but functional code |
| `FYI` | Observation, not action | Style preference; minor naming; observation outside lens scope; surfacing for operator awareness |

Findings demoted one severity tier when evidence is weak (Block→Nit, Nit→FYI, FYI→dropped). Evidence is considered weak when `file_line` is absent OR `excerpt` is empty. See § Aggregation > Per-finding shape for the canonical rule.

**`FYI` findings DO NOT trigger NEEDS-WORK.** A lens whose `findings` array contains only `FYI` entries (zero `Block`, zero `Nit`) still emits `Correctness verdict: PASS` (or the corresponding `<Lens> verdict: PASS`). `FYI` surfaces in the output for operator awareness; it is observation, not action. Only `Block` and `Nit` findings move a lens out of `PASS`. See the per-lens Output format sub-sections below for the explicit threshold rule applied uniformly across all six lenses.

Approval semantics — what each verdict obligates the orchestrator to do — live
in `docs/investigations/review-agents/18-approval-semantics.md`.

### Correctness lens

**Scope:** Given the stated intent (prompt + plan step if available), does the
diff actually accomplish what it claims?

**Coverage claim:** Detects logic that doesn't match the goal; missing edge
cases the prompt implies; incomplete implementations (TODO left behind);
inverted condition / wrong operator / off-by-one; silent breaks to existing
behavior not covered by the prompt.

**Non-coverage:** Does NOT cover bugs in the literal sense (null access, race
conditions — that's the Bugs lens). Does NOT cover style. Does NOT cover
whether the diff is a good design.

**Adversarial framing applies (see Anti-pattern catalog § verify-dev-claims framing wrapper):** when spawning the Correctness sub-agent, prepend its prompt with the verify-dev-claims framing so it verifies each diff claim against the code, not the prompt. The dev's stated intent is a hypothesis to test against the code, not ground truth.

**Evidence shape:** Each finding:

```text
file:line — <one-line summary>
  Excerpt: `<exact text>`
  Reasoning: <why this contradicts intent>
```

**Severity rubric:** `Block` if the diff fails to do what its prompt claims,
OR if a Done-when from `--plan-step` is unmet by the diff. `Nit` if the diff
does what's asked but misses an edge case the prompt implies. `FYI` for
observation-only ("the prompt is ambiguous about X; assumed Y").

**Output format:** A bulleted list of findings in evidence shape, ending with
one of:

- `Correctness verdict: PASS`
- `Correctness verdict: NEEDS-WORK (N findings)`
- `Correctness verdict: NO-EVIDENCE` (no diff content was visible to this lens — usually an inputs-gathering bug)

**Verdict threshold (uniform across all six lenses).** Emit `PASS` if and only if `findings` contains zero `Block` AND zero `Nit` entries (`FYI`-only is `PASS`). Emit `NEEDS-WORK` if findings contains any `Block` or any `Nit`. Emit `NO-EVIDENCE` when the lens could not see diff content (inputs-gathering bug). No hedging in the verdict line — count `Block` + `Nit` entries and emit deterministically.

### Bugs lens

**Scope:** Ignoring intent — does this diff introduce bugs?

**Linter pre-pass results** (read first; cite-by-reference, don't re-derive): if the orchestrator ran `scripts/lint_prepass.sh`, a deterministic linter sidecar lives at `<--output-dir>/lint-findings.json` (default `.review-deep/lint-findings.json`). When present, load it and enumerate findings relevant to this lens — **Bugs lens reads ALL findings** (every `tool` and `rule`) because any linter signal is potentially a bug. For each linter finding at `<path>:<line>`, the lens MUST NOT re-derive the same defect: instead, emit a single FYI-severity finding at that `file_line` with the rationale prefixed `Already-flagged by <tool> <rule> — surfacing for awareness only.` This forecloses double-counting at the lens level; aggregator rule 7's lint-dedup catches any escapees. If `lint-findings.json` is absent (orchestrator chose not to run the pre-pass, or every tool was skipped), proceed with the normal investigation below — the pre-pass is optional and its absence is not an error.

**Coverage claim:** Detects null/undefined access; resource leaks (open files,
connections, listeners); race conditions / deadlocks / shared mutable state;
type mismatches and implicit coercions that lose data; broken error
propagation (swallowed exceptions, wrong error type). Adversarial framing:
"find what breaks under unhappy paths, hostile inputs, race timing, concurrent
modification" (see `docs/investigations/review-agents/29-adversarial-reviewer.md`).

**Non-coverage:** Does NOT cover whether the diff matches intent (Correctness
lens). Does NOT cover style. Does NOT cover plan-conformance. Does NOT cover
adversarial-input / secrets / unsafe-config defects — injection-as-data,
secret-file dumps, unsafe configs missing a startup guard, path traversal, authz
gaps, unvalidated boundary input, bind-without-guard — that's the **Security**
lens (Bugs = generic robustness/crashes; Security = the `.claude/rules/security.md`
adversarial-input / secrets / unsafe-config failure modes). A bug that is ALSO a
security defect is owned by Security as primary and may be cross-tagged FYI here.

**Adversarial framing applies (see Anti-pattern catalog § verify-dev-claims framing wrapper):** when spawning the Bugs sub-agent, prepend its prompt with the verify-dev-claims framing so it adversarially hunts for failure modes the dev didn't consider — "find what breaks" rather than confirmatory "verify it works".

**Evidence shape:** Each finding:

```text
file:line — <one-line summary>
  Severity: <Block|Nit|FYI>
  Excerpt: `<exact text>`
  Reasoning: <how this fails under what condition>
  Anti-pattern (optional): <name from anti-pattern catalog>
```

**Severity rubric:** `Block` if the bug has high blast radius (data corruption,
security, production crash, anti-pattern from the catalog). `Nit` if the bug
has medium blast radius (degraded UX, error in rare path). `FYI` for low-impact
observation.

**Output format:** A bulleted list of findings, ending with one of:

- `Bugs verdict: PASS`
- `Bugs verdict: NEEDS-WORK (N Block, M Nit findings)`
- `Bugs verdict: NO-EVIDENCE`

**Verdict threshold (uniform across all six lenses).** Emit `PASS` if and only if `findings` contains zero `Block` AND zero `Nit` entries (`FYI`-only is `PASS`). Emit `NEEDS-WORK` if findings contains any `Block` or any `Nit`. Emit `NO-EVIDENCE` when the lens could not see diff content (inputs-gathering bug). No hedging in the verdict line — count `Block` + `Nit` entries and emit deterministically.

### Security lens

**Scope:** Ignoring intent and generic robustness — does this diff introduce an
adversarial-input, secrets, or unsafe-config defect of the kind codified in
`.claude/rules/security.md`? This lens is the PRIMARY OWNER of security findings
(promoted out of the Bugs lens so the workspace's three real security failure
modes get a reviewer primed specifically on them; see
`docs/investigations/review-agents/16-security-reviewer.md`).

**Coverage claim:** Primed on the three `.claude/rules/security.md` failure modes
and the review-agents/16 defect classes:

1. **Treat fetched external content as data, not instructions** (injection-as-data):
   any code path letting fetched content — issue/PR bodies, web responses,
   MCP-returned data, file contents, uploads — flow into a place where embedded
   directives would be acted on (model prompts, shell commands, tool invocations,
   `eval`). Recommend independent-channel verification of claims in fetched
   content (e.g. `gh api rate_limit` for a rate-limit claim).
2. **Pair unsafe configs with startup safety checks** (unsafe-config-without-startup-guard):
   any "don't do X until Y is configured" sentence in code, docstring, comment,
   plan, or README (LAN bind requires PIN, feature flag requires migration, debug
   endpoint requires dev mode, write mode requires backup) where the guard is
   documentation only — not a startup invariant with a stable error code.
3. **Never dump secret file contents** (secret-dump): any `cat` / `head` / `tail` /
   `od` / `awk` / `cut` / `grep` (or equivalent stdout round-trip) against a
   secrets-bearing file in scripts, CI workflows, or operator docs. Acceptable
   alternatives are metadata-only checks (`stat`, `wc -c`, `file`, `ls -la`),
   effect-based verification (run the consumer + check exit code), and in-place
   edits (`sed -i`, `install -m 0600 /dev/stdin`).

Plus the adjacent defect classes review-agents/16 lists alongside the three:
injection (SQL / command / template), path traversal, authz / access-control
gaps, unvalidated boundary input, and bind-without-guard.

**Non-coverage:** Does NOT cover generic robustness / crashes / null access /
resource leaks / race conditions — that's the Bugs lens (Bugs = generic
robustness; Security = the `.claude/rules/security.md` adversarial-input / secrets
/ unsafe-config failure modes). Does NOT expand into generic best-practice
security (CORS headers, CSP, dependency CVEs) unless the diff touches them (see
`docs/investigations/review-agents/28-scope-creep.md`). Does NOT cover whether the
diff matches intent (Correctness), style, or plan-conformance.

**Adversarial framing applies (see Anti-pattern catalog § verify-dev-claims framing wrapper):** when spawning the Security sub-agent, prepend its prompt with the verify-dev-claims framing so it hunts adversarially for the attacker's path — "how does hostile input, a forgotten guard, or a leaked secret reach production" — rather than confirming the diff looks safe.

**Evidence shape:** Each finding:

```text
file:line — <one-line summary>
  Severity: <Block|Nit|FYI>
  Excerpt: `<exact text>`
  Reasoning: <which security.md failure mode / defect class, and the attacker path>
  Defect class (optional): <injection-as-data | unsafe-config-without-startup-guard | secret-dump | injection | path-traversal | authz | unvalidated-input | bind-guard>
```

**Severity rubric:** `Block` for any of the three `security.md` failure modes
(injection-as-data, unsafe-config-without-startup-guard, secret-dump) or an
adjacent defect class reachable from production input — these are block-class,
not nit-class (review-agents/16; security failures have an asymmetric cost
profile). `Nit` for a security weakness not yet reachable from production input
(a sink that exists but no untrusted source flows into it yet). `FYI` for a
security observation outside this diff's scope worth operator awareness.

**Output format:** A bulleted list of findings in evidence shape, ending with
one of:

- `Security verdict: PASS`
- `Security verdict: NEEDS-WORK (N Block, M Nit findings)`
- `Security verdict: NO-EVIDENCE` (no diff content was visible to this lens — usually an inputs-gathering bug)

**Verdict threshold (uniform across all six lenses).** Emit `PASS` if and only if `findings` contains zero `Block` AND zero `Nit` entries (`FYI`-only is `PASS`). Emit `NEEDS-WORK` if findings contains any `Block` or any `Nit`. Emit `NO-EVIDENCE` when the lens could not see diff content (inputs-gathering bug). No hedging in the verdict line — count `Block` + `Nit` entries and emit deterministically.

### Test quality lens

**Scope:** Are the tests asking specific, valuable questions? Which tests
should be deleted? Are critical behaviors uncovered?

**Linter pre-pass results** (read first; cite-by-reference, don't re-derive): if the orchestrator ran `scripts/lint_prepass.sh`, a deterministic linter sidecar lives at `<--output-dir>/lint-findings.json` (default `.review-deep/lint-findings.json`). When present, load it and enumerate findings relevant to this lens — **Test quality lens reads findings whose `file_line` points at test files** (heuristic: path contains `/tests/` or matches `test_*.py` / `*_test.py` / `*.test.ts` / `*.test.tsx` / `*.spec.ts` shapes). For each linter finding at a test-file `<path>:<line>`, the lens MUST NOT re-derive the same defect: instead, emit a single FYI-severity finding at that `file_line` with the rationale prefixed `Already-flagged by <tool> <rule> — surfacing for awareness only.` This forecloses double-counting at the lens level; aggregator rule 7's lint-dedup catches any escapees. If `lint-findings.json` is absent (orchestrator chose not to run the pre-pass, or every tool was skipped), proceed with the normal investigation below — the pre-pass is optional and its absence is not an error.

**Coverage claim:** This lens's PRIMARY goal is to **trim**. Detects: tests
asserting implementation details instead of behavior; duplicate tests;
tautological assertions; over-mocked tests that test nothing real; tests that
would pass even if the feature were broken; **codifying-test-diff** (assertion
changes that mask new broken behavior — see
`docs/investigations/review-agents/06-codifying-test-diff-suspicion.md`); critical
behaviors with zero coverage.

**Non-coverage:** Does NOT request tests for trivial code. Does NOT cover
whether tests pass (the gates do that). Does NOT cover style.

**Evidence shape:** Each finding:

```text
file:line — <keep|delete|rewrite>
  Excerpt: `<test name and assertion>`
  Reasoning: <why>
  Anti-pattern (optional): codifying-test-diff
```

(For codifying-test-diff findings, cite the assertion change being suspect,
not endorsing.)

**Severity rubric:** `Block` if a codifying-test-diff is detected (tests
rewritten to mask broken behavior) OR if a critical Done-when behavior has
zero test coverage. `Nit` if tests are redundant or over-mocked. `FYI` for
observations ("this test would benefit from a property-style assertion").

**Output format:** Per-test verdicts (keep/delete/rewrite with one-line
reason), ending with one of:

- `Test quality verdict: PASS`
- `Test quality verdict: NEEDS-WORK (N delete, M rewrite, K Block)`
- `Test quality verdict: NO-EVIDENCE`

**Verdict threshold (uniform across all six lenses).** Emit `PASS` if and only if `findings` contains zero `Block` AND zero `Nit` entries (`FYI`-only is `PASS`). Emit `NEEDS-WORK` if findings contains any `Block` or any `Nit`. Emit `NO-EVIDENCE` when the lens could not see diff content (inputs-gathering bug). No hedging in the verdict line — count `Block` + `Nit` entries and emit deterministically.

### Style and conventions lens

**Scope:** Does this diff follow the conventions already present in the
surrounding code?

**Optional local-judge offload (switchboard, INERT BY DEFAULT).** The Style lens is the
ONLY review-deep lens cheap enough to route to a local model (tier-offload task_class
`review-deep-style`; Switchboard Decision 9). Correctness, Bugs, Test-quality, and
Plan-conformance are deep-reasoning drift-catchers (`code-quality.md`) and ALWAYS stay on
Claude — never route them local. The Style offload is **off unless switchboard offload is
enabled for `review-deep-style`**. When enabled, dispatch the Style judgment through the
switchboard judge entrypoint:
`python -m switchboard judge --site review-deep-style --prompt-file <style-lens-prompt-file>`
(prints one JSON object, always exits 0). On a **verdict**, treat it as the Style lens's
advisory result. On a **defer** (`{"defer": true, ...}`) — ALWAYS returned when offload is
off, the slice is disabled, or the model is down/slow/wrong-shaped — fall back to running the
Style lens on Claude per the model-tier table below. When offload is OFF (the default), the
entrypoint returns a defer immediately with NO network call, so the Style lens runs on its
configured Claude tier **exactly as before**. The local Style verdict only advises; the
aggregator's pass/fail decision stays a Claude judgment.

**Linter pre-pass results** (read first; cite-by-reference, don't re-derive): if the orchestrator ran `scripts/lint_prepass.sh`, a deterministic linter sidecar lives at `<--output-dir>/lint-findings.json` (default `.review-deep/lint-findings.json`). When present, load it and enumerate findings relevant to this lens — **Style lens reads style-class findings** (heuristic: ruff codes matching `^E\d+$` or `^W\d+$` or the ruff style families `D`/`I`/`N`/`Q`/`COM`/`ICN`; eslint rules in the `@stylistic/*` namespace or named in eslint's `style` category). For each style-class linter finding at `<path>:<line>`, the lens MUST NOT re-derive the same defect: instead, emit a single FYI-severity finding at that `file_line` with the rationale prefixed `Already-flagged by <tool> <rule> — surfacing for awareness only.` This forecloses double-counting at the lens level; aggregator rule 7's lint-dedup catches any escapees. If `lint-findings.json` is absent (orchestrator chose not to run the pre-pass, or every tool was skipped), proceed with the normal investigation below — the pre-pass is optional and its absence is not an error.

**Coverage claim:** Detects naming-convention deviations from surrounding
code; import ordering inconsistent with neighbors; error-handling patterns
that differ (raises vs returns None); structural patterns (dataclasses vs
raw dicts); comment / docstring style if the file has one. Reads the file's
own surrounding code as the convention source — does NOT apply generic best
practices.

**Non-coverage:** Does NOT flag generic best practices. Does NOT flag minor
whitespace if neighbors don't enforce it. Does NOT cover correctness or bugs.
Does NOT block the verdict — only Block-severity style issues do.

**Evidence shape:** Each finding:

```text
file:line — <one-line summary>
  Excerpt: `<diff text>`
  Surrounding convention: `<what neighbors do>`
  Reasoning: <why this is a deviation, not just a preference>
```

**Severity rubric:** `Block` only if the diff breaks a convention that's
enforced by tooling (linter, formatter) — i.e., the diff would fail CI. `Nit`
for hand-readable convention deviations. `FYI` for minor observations.

**Output format:** A bulleted list of deviations, ending with one of:

- `Style verdict: PASS`
- `Style verdict: NEEDS-WORK (N findings)`
- `Style verdict: NO-EVIDENCE` (no diff content was visible to this lens — usually an inputs-gathering bug)

**Verdict threshold (uniform across all six lenses).** Emit `PASS` if and only if `findings` contains zero `Block` AND zero `Nit` entries (`FYI`-only is `PASS`). Emit `NEEDS-WORK` if findings contains any `Block` or any `Nit`. Emit `NO-EVIDENCE` when the lens could not see diff content (inputs-gathering bug). No hedging in the verdict line — count `Block` + `Nit` entries and emit deterministically.

### Plan-conformance lens

**Scope:** Does the diff implement what the named plan step asked for? (See
`docs/investigations/review-agents/03-plan-conformance.md` and
`docs/investigations/review-agents/21-requirement-coverage.md`.)

**Coverage claim:** When `--plan-step <path>:<step-id>` is supplied, this lens
reads the referenced plan file, locates the step in either heading-format or
table-format (see **Plan format detection** below), extracts the step's
**Problem**, **Done when**, **Files**, and **Produces** fields, and produces
three per-field verdicts:

1. **Done-when satisfied?** Cite the file:line in the diff that satisfies each clause.
2. **Files honored?** Did the diff modify only the Files listed, or did it touch out-of-scope files?
3. **Out-of-scope additions?** Did the diff add features beyond what the step asked for (see `docs/investigations/review-agents/28-scope-creep.md`)?

**Plan format detection:** Workspace plans use two distinct formats; this lens MUST detect which one the referenced plan file uses and parse accordingly:

- **Heading-format** (canonical for `/plan-init` / `/plan-feature` output): scan the plan file for `^### Step <step-id>:` and extract the immediately-following block of `- **Problem:**` / `- **Done when:**` / `- **Files:**` / `- **Produces:**` bullets as the step's ground-truth. Example: a plan with `### Step 5a: Author A/B fixture set` followed by the four bullet fields.
- **Table-format** (canonical for Alpha4Gate phase-d-build-plan.md and other long-running Alpha4Gate phase plans): scan the plan file for a markdown table whose first column equals `<step-id>` (e.g., `| D.6 | #169 | code | ... |`). Extract the matched row's columns AS the step's ground-truth, AND additionally read any narrative section linked from the row's `Description` column (the Alpha4Gate convention is a one-line table row that points at a longer section heading later in the file via a section anchor). The lens combines the table row's column values with the linked narrative section's prose as a single ground-truth payload.
- **Both formats present:** if the plan file contains BOTH an `### Step <step-id>:` heading AND a table row with `<step-id>` in the first column, the lens prefers the HEADING form (heading is canonical-authority by `/plan-init` convention; table is typically a summary view of the heading-form plan). Note this preference in the output's plan-format-detected field.
- **Neither form locates the step:** the lens emits a single Block-severity finding tagged `Plan-conformance verdict: NEEDS-CLARIFICATION — could not locate step <step-id> in <plan-path> as either heading-format (### Step <step-id>:) or table-format (| <step-id> | ... |)`. This is treated as an inputs-gathering failure, NOT a silent skip — operator needs to verify the `--plan-step` argument or fix the plan file. Distinct from `SKIPPED` (which fires only when `--plan-step` is not provided at all).

**Non-coverage:** Does NOT cover whether the diff is bug-free (Bugs lens).
Does NOT cover correctness of implementation (Correctness lens). Does NOT
cover whether the plan ITSELF is good (that's `/plan-review`).

**Evidence shape:** Each finding:

```text
<plan-file>:Step <N> — <Done-when|Files|Out-of-scope>
  Plan excerpt: `<exact text from plan step>`
  Diff evidence: `<diff line or absence>`
  Reasoning: <why this satisfies or violates the field>
```

**Severity rubric:** `Block` if any Done-when is unmet OR if the diff includes
out-of-scope code beyond the step's stated `Produces`. `Nit` if the diff is
incomplete on a non-Done-when goal. `FYI` for plan-vs-diff observations the
operator should note.

**Output format:** Three per-field verdicts (Done-when / Files / Out-of-scope),
each with bulleted findings + a per-field `PASS`/`NEEDS-WORK`. Final line is
one of:

- `Plan-conformance verdict: PASS`
- `Plan-conformance verdict: NEEDS-WORK (Done-when, Files, Out-of-scope counts)`
- `Plan-conformance verdict: NO-EVIDENCE` (lens spawned but could not see diff content — inputs-gathering bug)
- `Plan-conformance verdict: NEEDS-CLARIFICATION — could not locate step <step-id> in <plan-path> as either heading-format or table-format` (Block-severity inputs-gathering finding — distinct from SKIPPED; operator must fix the `--plan-step` argument or the plan file)
- `Plan-conformance verdict: SKIPPED — no --plan-step provided`

**Verdict threshold (uniform across all six lenses).** Emit `PASS` if and only if `findings` contains zero `Block` AND zero `Nit` entries (`FYI`-only is `PASS`). Emit `NEEDS-WORK` if findings contains any `Block` or any `Nit`. Emit `NO-EVIDENCE` when the lens could not see diff content (inputs-gathering bug). No hedging in the verdict line — count `Block` + `Nit` entries and emit deterministically. Plan-conformance additionally emits `SKIPPED` when `--plan-step` is not provided at invocation (expected configuration, not a finding).

**Critical: graceful skip behavior.** If `--plan-step` is not provided at
invocation, this lens is NOT spawned, NOT marked failed, and NOT treated as
an error. The aggregated report (built in Step 5) notes the skip explicitly:
`Plan-conformance: SKIPPED (no --plan-step argument)`. This is not a finding —
it's an expected configuration.

---

## Anti-pattern catalog

The seven Tier-1 anti-patterns below are the explicit defect shapes this skill
hunts for. Each has its own H3 (prefixed with `anti-pattern:` so the catalog
is grep-able) with a fixed shape: **Shape**, **Why it ships past unit tests**,
**Detection prompt**, **Originating source**, **Severity**, **Lens routing**.
All seven are `Block` severity by definition — lower-severity defect shapes
belong in the lens-specific rubrics, not here. After the seven patterns, a
`verify-dev-claims framing wrapper` H3 captures the meta-principle behind
patterns 1–3 and is referenced by the Bugs + Correctness lens prompts.

### anti-pattern: silent-wiring

- **Shape:** A new module / function / class is added with full unit-test coverage, but never invoked from any production caller. The test passes, the gauntlet passes, and the production effect is zero forever.
- **Why it ships past unit tests:** Unit tests of the new module exercise it directly via import; they don't verify any production code path actually reaches it.
- **Detection prompt:** When the diff adds a new module, function, class, or entry point that's intended to be called from production, grep the entire codebase for the new name. If the only references are tests + the new module itself + its imports for testing, flag as `Block: anti-pattern: silent-wiring`. The fix is an integration test that exercises the production entry point and asserts the new component is reached end-to-end (caller-first, not callee-first).
- **Originating source:** `.claude/rules/code-quality.md` § "New components require an integration test through the production caller"; `docs/investigations/review-agents/04-silent-wiring-detection.md`; toybox step 15 iter 1 (developer built `schedule_judge_sample` and unit-tested it directly, never invoked from `_do_propose` — production effect would have been zero judge calls forever).
- **Severity:** Block.
- **Lens routing:** Bugs primary; Correctness secondary (the diff "fails to do what it claims" whenever the new code is never reached).

### anti-pattern: producer-consumer-drift

- **Shape:** A producer's primary key, cache key, id format, filename format, or shape constant changes, but downstream consumers are not all updated. Tests on either endpoint mock the other and pass; production crashes on the seam.
- **Why it ships past unit tests:** Endpoint tests mock the OTHER endpoint; the bug lives in the relationship between producer and consumer, not in either endpoint individually.
- **Detection prompt:** When the diff changes the shape of a key, id, schema, filename pattern, or any value referenced from multiple call sites, grep every consumer of the old shape. If any consumer still references the pre-change shape, flag as `Block: anti-pattern: producer-consumer-drift`. The fix attaches a grep-results table to the PR/issue (one row per call site, verdict `OK | needs fix | already handled`) AND adds an integration test that exercises the full producer → consumer round trip.
- **Originating source:** `.claude/rules/code-quality.md` § "Grep all downstream consumers when changing a key/id shape"; `docs/investigations/review-agents/05-producer-consumer-drift.md`; Alpha4Gate Phase 4.6 Step 1 (changed `SC2Env._game_id` shape but missed `evaluator._get_game_result(base_id)`; Soak-4 spent 70 minutes with 12 eval games flagged "crashed" before DB forensics found the missed caller; cost a whole Phase 4.7 plan-review-repo-sync-build-phase cycle).
- **Severity:** Block.
- **Lens routing:** Bugs primary; Correctness secondary.

### anti-pattern: codifying-test-diff

- **Shape:** A PR changes how data is persisted, narrows a response shape, or removes a field; existing tests start failing; the developer updates the failing tests to match the new (broken) behavior; tests now pass; the regression is codified into the suite.
- **Why it ships past unit tests:** Test diffs that adjust assertion shape look like normal test maintenance; reviewers approve the codifying diff because the test now passes against the new behavior.
- **Detection prompt:** When the diff includes BOTH (a) a change to storage representation / normalization / API response shape AND (b) modifications to existing test assertions, treat the test changes as **suspect**, NOT endorsing. Read the original assertion vs the modified one and ask: "did the new behavior change to match the new assertion, or did the assertion change to mask new behavior?" If the latter, the default severity is **Nit-suspicion**: surface the finding so the reviewer or operator can adjudicate.

  **Tie-breaker (escalation / downgrade):**
  - **Escalate to `Block: anti-pattern: codifying-test-diff`** when the assertion change masks behavior AND the dev provides no documenting context (no plan step asks for the shape change, no changelog entry, no migration note, no commit body explaining intent).
  - **Downgrade to `FYI: anti-pattern: codifying-test-diff (documented)`** when documenting context exists AND the assertion update is internally consistent with that documented change. Surface the verdict so it lands in the audit trail; do not block on it.

  When `--plan-step` is supplied, the plan-conformance lens is the natural tie-breaker: if the plan step's Problem / Done-when explicitly asks for the shape change, the assertion update is endorsed by the plan (downgrade applies). When the plan is silent on the shape change, escalation applies. Pay extra attention to endpoints the frontend renders directly without intermediate code (suggestion cards, dashboards, summaries).
- **Originating source:** `.claude/rules/code-quality.md` § "Audit wire shape when storage representation changes"; `docs/investigations/review-agents/06-codifying-test-diff-suspicion.md`; toybox G2 silently narrowed a propose response from 5 steps to 1; the G2 dev agent updated 6 integration tests to assert `len(steps) == 1`; four reviewers approved the codifying test diff; caught only when the operator hit the parent UI.
- **Severity:** Block.
- **Lens routing:** Test quality primary; Bugs secondary.

### anti-pattern: silent-fallthrough-in-loop

- **Shape:** A `try/except` (or `try/catch`) inside a `for` / `while` loop where code BELOW the try block assumes the work in the try succeeded (reads a result, advances state, saves a checkpoint, increments a counter). The catch path swallows the exception without `continue` or re-raise, so the success-path code runs on stale or missing data.
- **Why it ships past unit tests:** The exception path is rarely hit in tests; when hit, the loop appears to "keep running" which looks like resilience rather than silent corruption.
- **Detection prompt:** Detect `try`/`except` blocks whose **lexical parent is a `for` or `while` statement** (i.e., the try/except is directly inside the loop body, not inside a helper function called from the loop). The except clause logs but does not `continue`, `break`, or re-raise — and code BELOW the try block uses variables (a result, a checkpoint, a counter) that would be unbound or stale on the exception path. That's a finding. The catch path must either re-raise OR set a `failed = True` flag and `continue` BEFORE the success-path code. Flag as `Block: anti-pattern: silent-fallthrough-in-loop`. **Scope exclusion:** try/except inside helper functions called from a loop is the `silent-fallthrough-in-hot-path` variant — see the next catalog entry.

  Example shape that's almost always wrong:

  ```python
  for item in items:
      try:
          result = expensive_op(item)
      except Exception:
          log.exception("crashed")
          # NOTHING ELSE — falls through
      # BUG: this runs even when expensive_op crashed
      save_checkpoint(result)
      advance_curriculum(result)
  ```
- **Originating source:** `~/.claude/skills/review-gauntlet/SKILL.md` § "Bug Reviewer" anti-pattern 1; Alpha4Gate Phase 4.5 (found by a 4-minute smoke test, not by 682 unit tests — the most dangerous failure mode for autonomous loops is zero observable signal).
- **Severity:** Block.
- **Lens routing:** Bugs primary.

### anti-pattern: silent-fallthrough-in-hot-path

- **Shape:** A `try/except` (or `try/catch`) inside a function that is itself called ≥100 times per session — e.g., per RL step, per HTTP request, per render frame, per game tick. The except clause logs but does not re-raise; the function returns normally on the exception path; the caller has no signal that the call failed and proceeds as if the work succeeded.
- **Why it ships past unit tests:** Unit tests typically call the helper once with a working input; the silent-fail pathway never fires. The hot-path call site (RL training step, request handler, render loop) is not exercised in unit-test scope, so the caller's downstream assumptions about the helper's success are never tested against a thrown-and-swallowed exception.
- **Detection prompt:** Identify functions whose call sites are inside a `for`/`while` loop, an RL training step, an HTTP request handler, or a per-frame render path. For each such function, check whether its body contains `try`/`except` that logs without re-raising AND where the function returns normally on the exception path. If the caller's success-path semantics depend on the function having succeeded (the caller reads a return value, advances state, or commits side effects), flag as `Block: anti-pattern: silent-fallthrough-in-hot-path`. The fix is either re-raise on the exception path, or return a sentinel / `Result` that the caller MUST inspect, with the caller updated to branch on the sentinel before its success-path code runs. **Scope contrast:** `silent-fallthrough-in-loop` covers the lexical-loop case (try/except directly inside a for/while body); this entry covers the helper-function case where the loop is elsewhere.
- **Originating source:** review-deep M1 smoke (Alpha4Gate Phase D.6, 2026-05-22) — hot-path function `train_step()` contained a `try`/`except` that logged without re-raising; the per-RL-step caller had no signal that a step had silently failed, so curriculum advance and checkpoint writes proceeded against stale state. The v1 smoke surfaced this as a Block via the Bugs lens but used the `silent-fallthrough-in-loop` tag, which was a scope mismatch — the try/except was not in a literal loop body. Splitting the catalog entry per v2 plan Design decision 5.
- **Severity:** Block.
- **Lens routing:** Bugs primary; Correctness secondary (caller "fails to do what it claims" when the silent-fail path fires).

### anti-pattern: duplicate-shape-constants

- **Shape:** A literal that defines the shape of data — `Discrete(N)`, `Box(shape=(N,))`, a list of column names, an action enum, a feature dimension, a schema definition — exists in two or more places. Tests mock either side and pass; producer-consumer drift inevitably follows when one site updates and the other doesn't.
- **Why it ships past unit tests:** Tests with mocks can't see drift; `==` value-equality assertions pass even after one side drifts because both started from the same literal.
- **Detection prompt:** When the diff introduces a literal that defines data shape, grep the diff's transitive imports for the same value or name. If it exists in two places, that's a finding. Flag as `Block: anti-pattern: duplicate-shape-constants`. The fix is single-source-of-truth: pick a leaf module that both sites can import from, define the constant there once, import it from both sides. Regression tests should assert object identity (`is`), not just value equality (`==`), so a future re-introduction of a duplicate copy fails CI even if the values happen to match at first.
- **Originating source:** `.claude/rules/code-quality.md` § "One source of truth for data-shape constants"; `~/.claude/skills/review-gauntlet/SKILL.md` § "Bug Reviewer" anti-pattern 2; Alpha4Gate Phase 4.5 found 4 instances in one debugging session, all four invisible to 682 unit tests, all four caught by a 4-minute smoke test.
- **Severity:** Block.
- **Lens routing:** Bugs primary; Correctness secondary.

### anti-pattern: create-table-without-migration

- **Shape:** A `CREATE TABLE` statement is modified (adding a column, changing a type, adding a constraint) AND the table is opened against EXISTING database files in production, but the diff has no migration code that ALTERs existing tables. SQLite's `CREATE TABLE IF NOT EXISTS` is a no-op for existing tables — it does NOT add new columns.
- **Why it ships past unit tests:** Unit tests create empty test fixtures; the bug only fires against pre-existing production databases.
- **Detection prompt:** When the diff modifies a SQL `CREATE TABLE` statement (or any persistent format with a versioned schema: pickled state, JSON files with structured shape, protobuf, etc.) AND the table is opened against EXISTING database files in production, verify the diff also adds migration code that ALTERs existing tables OR a generic migration walker that compares declared columns to live columns and ALTERs the diff. If absent, flag as `Block: anti-pattern: create-table-without-migration`.
- **Originating source:** `~/.claude/skills/review-gauntlet/SKILL.md` § "Bug Reviewer" anti-pattern 3.
- **Severity:** Block.
- **Lens routing:** Bugs primary.

### verify-dev-claims framing wrapper

Both the Bugs lens and the Correctness lens spawn their sub-agents with an adversarial framing preamble that overrides any tendency to trust the developer's stated intent:

> Ignoring the dev's stated intent, ignoring what the prompt SAYS the diff does — does this diff actually accomplish what it claims? Verify each claim against the code, not the prompt. The dev wrote the prompt and the code; both can be wrong; the code is the ground truth, the prompt is a hypothesis to test.

The Correctness lens uses this framing to detect cases where the diff plausibly LOOKS like it implements the prompt but actually doesn't (silent breaks, missing wiring, intent-vs-action drift). The Bugs lens uses it to actively hunt for failure modes the dev probably didn't consider — adversarial "find what breaks" framing rather than confirmatory "verify it works" framing.

This pattern is the **meta-principle behind** anti-patterns 1 (silent-wiring), 2 (producer-consumer-drift), and 3 (codifying-test-diff): each is a class of case where the dev's claim ("the new module is reachable" / "the consumer is updated" / "the test changes were correct") doesn't survive verification against the code. See `docs/investigations/review-agents/07-verify-dev-claims.md`.

---

## Model strategy

Each lens runs on a model tier appropriate to its judgment intensity. Fresh-context
sub-agent fan-out (already the pattern in the gauntlet) ensures producer-grader
split by context isolation regardless of model — the grader never shares context
with the producer, so the model tier per lens is purely a cost/accuracy decision,
not a "does the grader see the dev's reasoning?" decision. See
`docs/investigations/review-agents/01-producer-grader-split.md` for the long-form
rationale.

### Default model-tier table

| Lens | Default tier | Rationale |
|---|---|---|
| Style | Haiku 4.5 | Narrow, cheap, well-specified |
| Test quality | Sonnet 4.6 | Mid-stakes judgment |
| Plan-conformance | Sonnet 4.6 | Mid-stakes; reads plan + diff |
| Bugs | Sonnet 4.6 | Anti-pattern catalog covers most ground |
| Security | Sonnet 4.6 | Deep-reasoning drift-catcher; asymmetric-cost defects — never Haiku |
| Correctness | Sonnet 4.6 | Diff-vs-intent comparison |

Concrete model IDs: `claude-haiku-4-5-20251001` (Haiku 4.5), `claude-sonnet-4-6`
(Sonnet 4.6), and `claude-opus-4-7` (Opus 4.7). Tier names in this skill always
refer to the latest model in each family; pin a specific snapshot via
`--model-override` if needed.

The `Style` row corresponds to the `### Style and conventions lens` H3; for
`--model-override` the flag name is `style` (the shorter form documented in the
syntax below). All other lens names map kebab-case identically: `Test quality`
→ `test-quality`, `Plan-conformance` → `plan-conformance`, `Bugs` → `bugs`,
`Security` → `security`, `Correctness` → `correctness`.

### `--model-override` flag semantics

The `--model-override` flag (declared in the Arguments table at the top of this
file) lets the operator swap the default tier for any single lens on a
per-invocation basis.

- **Syntax:** `--model-override <lens>=<tier>` where `<lens>` is one of
  `style | test-quality | plan-conformance | bugs | security | correctness` and `<tier>`
  is one of `haiku | sonnet | opus`. Tier names map to the latest model in each
  family: `haiku` → `claude-haiku-4-5-20251001`, `sonnet` → `claude-sonnet-4-6`,
  `opus` → `claude-opus-4-7`.
- **Repeatable:** the flag may be passed multiple times to override multiple
  lenses in one invocation (e.g., `--model-override bugs=opus --model-override correctness=opus`).
- **Effect:** overrides the default tier for the named lens for THIS invocation
  only. The default table above is unchanged; subsequent invocations without
  the flag return to defaults.
- **Example use cases:**
  - `--model-override bugs=opus` — bump the Bugs lens to Opus for a
    high-blast-radius diff (substrate refactor, schema change touching many
    consumers).
  - `--model-override style=sonnet` — bump Style to Sonnet when a diff touches
    a file with intricate conventions a Haiku reviewer might miss.
  - `--model-override correctness=haiku` — downgrade Correctness to Haiku for
    a known-trivial diff (rare; primarily for cost-tuning experiments).
- **Invalid input:**
  - Unknown lens name → exit with an error message listing the valid lens
    names (`style | test-quality | plan-conformance | bugs | security | correctness`).
    Do NOT silently skip.
  - Unknown tier name → exit with an error message listing the valid tier
    names (`haiku | sonnet | opus`).
  - Malformed flag (missing `=` or empty side) → exit with an error and the
    example syntax `--model-override <lens>=<tier>`.

### Overload-fallback behavior

When a lens's primary model returns `529 Overloaded` or times out (>180s without
first-token):

1. **Retry once at the same tier** with a 30-second backoff. The retry inherits the same 180s first-token timeout as the primary attempt — if the retry also exceeds 180s without first-token, treat it as failed and proceed to step 2.
2. **If the retry also fails** (529 or timeout), surface the lens as `FAILED`
   in aggregation — NOT silently skipped. The aggregated report includes
   `<Lens> verdict: FAILED — model overloaded after 1 retry at tier <tier>`.
   The JSON sidecar (Step 5) records `overall_verdict: "FAILED"` for that lens
   with a `failure_reason: "model_overloaded"` field.

   **Cross-step contract:** This field name (`failure_reason`) and its allowed
   values (currently `"model_overloaded"`; future additions documented here) are
   owned jointly by this section and the Step 5 aggregator's JSON schema. Step 5
   MUST adopt this exact field name in `lens_verdicts[]` entries when
   `overall_verdict == "FAILED"`. If Step 5 needs to rename the field, update
   this section in the same diff. Drift between this declaration and Step 5's
   schema is a `producer-consumer-drift` finding under the anti-pattern catalog.
3. **Do NOT auto-fall-back to a different tier** without operator instruction.
   Silent tier-fallback would mask cost / accuracy expectations and codify an
   "anything goes" review pass. The operator can re-invoke with
   `--model-override <lens>=<other-tier>` if they want to retry at a different
   tier.

This is the "fail loud, never silently degrade" principle from
`.claude/rules/code-quality.md` § "Audit wire shape when storage representation changes" applied to model-tier degradation.

**Per-lens `overall_verdict` enum (Cross-step contract):** The complete set of
values a lens can emit as `overall_verdict` is:

| Value | Set by | Meaning |
|---|---|---|
| `PASS` | lens sub-agent | No findings or only minor findings; lens approves |
| `NEEDS-WORK` | lens sub-agent | Lens found Block- or Nit-severity findings the dev should address |
| `NO-EVIDENCE` | lens sub-agent | Lens could not see diff content (usually an inputs-gathering bug) |
| `FAILED` | this section (overload-fallback) | Lens's model overloaded after 1 retry — see `failure_reason` field |
| `SKIPPED` | Plan-conformance lens only | `--plan-step` was not provided; lens deliberately skipped (NOT an error) |
| `NEEDS-CLARIFICATION` | Plan-conformance lens only | `--plan-step` was provided but the step could not be located in either heading-format or table-format; aggregator maps to NEEDS-WORK like a Block finding (inputs-gathering failure — distinct from SKIPPED) |

Step 5's aggregator MUST handle all six values explicitly — including the
`FAILED`, `SKIPPED`, and `NEEDS-CLARIFICATION` branches, which the happy-path `PASS / NEEDS-WORK /
NO-EVIDENCE` ladder does not cover. Mapping to the top-level
`aggregated_verdict.result` ladder (`PASS / NEEDS-WORK / DEFERRED-TO-UAT`) is
owned by Step 5 — `NEEDS-CLARIFICATION` maps to `NEEDS-WORK` at the aggregated level (it is a Block-severity inputs-gathering failure); this table is the source of truth for what each lens can emit
as its overall_verdict.

### Cost / latency note

Haiku 4.5 is roughly 5-10x cheaper and 2-3x faster per token than Sonnet 4.6 —
that gap is why Style (mechanical convention-matching) defaults to Haiku
while the five judgment-heavy lenses default to Sonnet. For large diffs,
context-window cost dominates tier choice; prefer shrinking the diff or
narrowing `--reviewers` over escalating tiers. Cost-modeling detail in
`docs/investigations/review-agents/23-context-window-cost.md` and
`docs/investigations/review-agents/24-cost-vs-risk.md`.

---

## Aggregation

After all spawned lens sub-agents return, the orchestrator collects each per-lens
verdict, applies the aggregator rules below, and emits both a JSON audit-trail
sidecar at `.review-deep/<timestamp>.json` and a human-readable markdown
summary. The aggregator is fully deterministic — given the same per-lens
verdicts, two invocations produce byte-identical sidecars (modulo the
`timestamp` field).

### Per-lens verdict shape

Each lens sub-agent emits one `LensVerdict` object that the orchestrator collects into the JSON sidecar's `lens_verdicts[]` array. The canonical schema lives in `scripts/aggregate.py` (`LensVerdict` dataclass) with per-field docstrings; the required fields are `lens_id` (one of `correctness | bugs | security | test-quality | style | plan-conformance` for code lenses), `model_tier` (`haiku | sonnet | opus`, post-`--model-override` resolution; stable even when the lens SKIPs so tier-mix queries don't need to handle nulls), `authority` and `coverage_claim` (one-line strings from the lens's Scope / Coverage claim sub-sections), `findings` (empty list when no findings — never `null`/absent), and `overall_verdict` (one of `PASS | NEEDS-WORK | NO-EVIDENCE | FAILED | SKIPPED | NEEDS-CLARIFICATION` per Model strategy § per-lens overall_verdict enum). The `failure_reason` field is present ONLY when `overall_verdict == "FAILED"`; current allowed value is `"model_overloaded"` (cross-step contract with Model strategy § Overload-fallback). A rename or new value MUST touch both `scripts/aggregate.py` AND this paragraph in the same diff — drift between the two sites is a `producer-consumer-drift` finding.

### Per-finding shape

Each entry in `lens_verdicts[].findings[]` is a `Finding` object whose canonical schema lives in `scripts/aggregate.py` (`Finding` dataclass) with per-field docstrings. The required fields are `severity` (`Block | Nit | FYI` per the universal rubric at the top of Reviewer lenses), `file_line` (`<path>:<line>` for a single line or `<path>:<start>-<end>` for a range; findings missing `file_line` are dropped during aggregation per the universal evidence discipline), `excerpt` (the exact cited text; empty excerpts demote one severity tier), and `rationale` (one sentence to one paragraph referencing the lens's coverage claim, the dev's stated intent, the named plan step, or a catalog anti-pattern). The optional `anti_pattern` field, when present, MUST be one of the seven catalog entries (`silent-wiring`, `producer-consumer-drift`, `codifying-test-diff`, `silent-fallthrough-in-loop`, `silent-fallthrough-in-hot-path`, `duplicate-shape-constants`, `create-table-without-migration`) plus the reserved wire-format marker `scope-boundary-deferral` (NOT a defect; signals a deferral hand-off — see Scope-boundary deferral). Any other value is invalid and causes the orchestrator to drop the finding. Two optional post-aggregation annotations may appear on a finding after rule 7 runs (mutated in place; NOT raw lens output): `also_flagged_by` (list of sibling lens_id strings, populated by the absence-dedup path when multiple lenses clustered on the same absence) and `also_flagged_by_linter` (a `{tool, rule}` dict, populated by the lint-dedup path when a lint finding's `file_line` overlaps the lens finding's `file_line`). Both are audit-trail annotations only — a fresh-context reader of a sidecar sees them on the primary surviving finding for each cluster, not on raw lens emissions.

### Aggregator rules

`scripts/aggregate.py` implements seven deterministic rules whose full per-rule docstrings are the canonical authority on edge cases — read `aggregate.py` for the source of truth. Invocation: `python scripts/aggregate.py --lens-dir <dir> --output-dir <dir> [--skill-version v3] [--prior-sidecar <path>] [--lint-findings <path>]`. The rule names map to functions (`apply_rule_N_<desc>`) and the contract summary is: rule 1 severity-dominance (Block outweighs any number of Nits; aggregated verdict tracks max severity across lenses, not finding count; per `docs/investigations/review-agents/14-severity-tiers.md`); rule 2 lens-owns-dimension (when two lenses flag the same `file_line`, the lens whose Scope covers that dimension or the catalog anti-pattern's `Lens routing` primary wins, others demote to `FYI` with rationale prefixed `Demoted per rule 2:` so rule 6 can detect persistent disagreement on re-run; per `docs/investigations/review-agents/12-disagreement-resolution.md`. **Security is the registered PRIMARY OWNER of security findings:** when both Bugs and Security flag the same security-class defect — `defect_class`/`anti_pattern` one of `injection-as-data`, `unsafe-config-without-startup-guard`, `secret-dump` (the three `.claude/rules/security.md` failure modes), mapped to `security` in `aggregate.py`'s `ANTI_PATTERN_PRIMARY` — Security wins as primary and the Bugs finding demotes to `FYI` cross-tag, so security findings are owned by Security, not Bugs); rule 3 SKIPPED-handling (plan-conformance SKIPPED when `--plan-step` absent; included in `lens_verdicts[]` for trace completeness, does NOT downgrade `aggregated_verdict.result`); rule 4 FAILED-handling (model-overloaded lens maps to `NEEDS-WORK` with `failure_reason` echoed in the aggregated rationale; no silent tier fallback; operator re-invokes with `--model-override <lens>=<other-tier>` to retry); rule 5 NO-EVIDENCE-handling (inputs-gathering bug; maps to `NEEDS-WORK` so the operator notices rather than accepting a vacuous PASS); rule 6 persistent-disagreement (when `--prior-sidecar <path>` supplied AND a current finding matches a prior demoted finding's identity — `file_line` + `anti_pattern` + `severity` — escalate severity by one tier and prefix rationale `Persistent disagreement:`; without `--prior-sidecar` the rule never fires); rule 7 absence-of-thing dedup AND lint-finding dedup (TWO independent dedup paths; both run inside `apply_rule_7_absence_dedup`). The absence path: when multiple lenses surface findings about the same absence — no concrete `path:line` anchor in the diff per `aggregate.py`'s `_is_absence_finding` heuristic — dedup by `(anti_pattern, summary fuzzy-match)` and demote duplicates to `FYI`; primary lens is the catalog `Lens routing` target or, absent an anti-pattern, the first lens to emit by `CODE_LENS_ORDER` correctness → bugs → security → test-quality → style → plan-conformance. The lint path: when a `lint-findings.json` is supplied (via `--lint-findings <path>` or auto-discovered at `<--output-dir>/lint-findings.json` / `.review-deep/lint-findings.json`), any lens finding sharing a concrete `file_line` with a lint finding demotes to `FYI` with the rationale prefixed `Cited-by-linter: <tool> <rule>` and an `also_flagged_by_linter: {tool, rule}` annotation for audit-trail completeness. The lint path is independent of the absence path; both run inside rule 7. Rule 7 fires BEFORE rule 6 in the pipeline so persistent-disagreement escalation applies only to the surviving primary; prevents cross-lens double-counting like the M1 smoke case where Bugs + Test quality both flagged "missing integration test" and inflated the Nit count to a noisy NEEDS-WORK.

Renames or shape changes to any rule MUST touch both `scripts/aggregate.py` AND this section in the same diff (producer-consumer-drift prevention per `dev/.claude/rules/code-quality.md`).

### Aggregated-verdict output ladder

The top-level `aggregated_verdict.result` is one of three values, computed
from the per-lens verdicts via the rules above.

| Verdict | Triggers |
|---|---|
| `PASS` | Zero `Block` findings across all lenses; zero `NEEDS-WORK` / `FAILED` / `NO-EVIDENCE` lens verdicts; `SKIPPED` lenses present but do not block |
| `NEEDS-WORK` | At least one `Block` finding; OR any lens `overall_verdict` is `NEEDS-WORK` / `FAILED` / `NO-EVIDENCE`; OR aggregated `Nit` count ≥ 3 across all lenses (soft-fail threshold to surface noisy diffs) |
| `DEFERRED-TO-UAT` | The skill structurally cannot evaluate part of the diff (Step 7 — Scope-boundary deferral — defines the trigger conditions); deferral takes priority over `PASS` but NOT over `NEEDS-WORK` on the same diff |

Interaction between `NEEDS-WORK` and `DEFERRED-TO-UAT`: if BOTH apply on the
same diff (one part has Block findings, another part is structurally
un-evaluable), the markdown summary names BOTH in the header line
(`# review-deep: NEEDS-WORK + DEFERRED-TO-UAT`), but the JSON sidecar uses
`aggregated_verdict.result == "NEEDS-WORK"` (the harder verdict wins for
gating purposes) and the deferred items still populate `deferred_uat_items[]`
regardless. This keeps machine-readable gating monotonic while preserving
the deferral signal for the operator.

When only `DEFERRED-TO-UAT` applies (zero `Block` findings, zero
`FAILED`/`NO-EVIDENCE` lenses, but Step 7's deferral fires for un-evaluable
parts of the diff), `aggregated_verdict.result == "DEFERRED-TO-UAT"` and the
markdown header reads `# review-deep: DEFERRED-TO-UAT`. This case is the
"pure deferral" path: lenses that could run all passed; lenses that couldn't
run surface as deferrals.

### Audit-trail JSON sidecar schema

After aggregation, the orchestrator writes one JSON file at `<--output-dir>/<timestamp>.json` (default `--output-dir` is `.review-deep/`). The canonical schema lives in `scripts/aggregate.py` (`write_sidecar` / `build_sidecar`); reading the script is the source of truth for field semantics. The top-level keys are, in this order: `timestamp` (filesystem-safe ISO 8601, `YYYY-MM-DDTHH-MM-SS`, MUST match the filename), `plan_step` (string `<path>:<step-id>` or `null`), `skill_version` (pinned string, `"v3"` for v3 sidecars; lets future schema migrations identify old sidecars), `invocation` (echoes the resolved argument values: `reviewers_flag`, `model_overrides`, `force_runtime`, `url`, `start_cmd`, `runtime_downgraded`, `runtime_downgrade_reason`), `lens_verdicts` (a 6-element stable prefix — one per code lens, including `SKIPPED` entries with `findings: []` — followed by 0..N runtime-lens entries at index 6+; SKIPPED lenses are present so the aggregator can rely on stable indexing), `aggregated_verdict` (`{result, rationale}`; result is one of `PASS | NEEDS-WORK | DEFERRED-TO-UAT` per the output-ladder rules below), `model_tiers_used` (a flat `lens_id → tier` map, separate from `lens_verdicts` to support quick queries without iterating findings), and `deferred_uat_items` (array of deferred-item dicts populated by the Scope-boundary deferral logic; empty array — not `null`, not absent — when no deferrals apply). The schema MUST be valid JSON (no comments). Any rename or new top-level key MUST touch both `scripts/aggregate.py` AND this paragraph in the same diff.

### Markdown output shape

After writing the sidecar, the aggregator prints a human-readable markdown summary to stdout (suitable for paste into PR comments). The canonical renderer lives in `scripts/aggregate.py` (`render_markdown`). Structure: a header line (`# review-deep: PASS` / `NEEDS-WORK` / `DEFERRED-TO-UAT` / `NEEDS-WORK + DEFERRED-TO-UAT`), a `## Lens verdicts` subsection with one line per lens (`- <lens_id>: <overall_verdict> (<finding-count> findings, model: <model_tier>)`; SKIPPED lenses are shown explicitly so the operator always sees the full 6-lens trace; a runtime-downgrade line follows when the auth-gate probe fired), a `## Findings` subsection grouped by severity (`### Block`, `### Nit`, `### FYI`) where each finding renders as `- **<file_line>** (<lens_id>[, anti-pattern: <name>]): <rationale>` followed by the `excerpt` as a fenced sub-block (severity subsections with zero findings are omitted), an optional `## Deferred to operator UAT` subsection present only when `deferred_uat_items[]` is non-empty (rendering per the Scope-boundary deferral § Markdown rendering contract — H3 per item, covered-lenses bullet, needs-verification bullet, commands fenced powershell block), an explicit `Please run M<N> next.` cue line when deferrals exist (lowest M-number in the sidecar), and a final `Audit-trail JSON: .review-deep/<timestamp>.json` pointer. Markdown shape changes MUST touch both `scripts/aggregate.py` AND this paragraph in the same diff.

---

## Calibration

This skill is the FIRST judge wired to the deterministic per-commit calibration gate that operationalizes [`_shared/judge-core.md`](../_shared/judge-core.md) §7's Discrimination guard. Run it as:

```bash
python .claude/skills/_shared/calibrate_judge.py --skill review-deep --mode ci
```

It prints `PASS` and exits 0 when the recorded judge snapshot is fresh, discriminating, and in agreement with the gold labels; it prints `FAIL` and exits 1 (fail-closed) otherwise. No LLM is invoked — every check replays *recorded* artifacts.

### The two gold artifacts

Both live under `evals/golden/` and are the calibration contract (schema source-of-truth is `calibrate_judge.py`'s module docstring):

- **`verdicts.jsonl`** — the hand-authored GOLD labels, one JSON object per fixture (`good.md` → `PASS`; each `bad_*.md` → `NEEDS-WORK` carrying its `defect_type` from `manifest.json` as `expected_block_anti_pattern` provenance). All 30 golden fixtures (1 good + 29 bads) appear here.
- **`recorded_scores.json`** — the recorded judge snapshot: `generated_at` (freshness anchor), `scores` (numeric score per fixture → drives the **discrimination** check: `good.md` must strictly out-score every `bad_*.md`), and `recorded_verdicts` (the categorical verdict the judge produced when snapshotted → drives the **agreement** check against `verdicts.jsonl`). All 30 fixtures appear in both maps; a missing fixture fails the gate closed.

### Operating rules

- **Label-edit-separate-commit (code-review discipline, not gate-enforced).** Any change to `verdicts.jsonl` gold labels SHOULD land in its OWN commit — never bundled with a SKILL.md or judge-logic change — so a reviewer can scrutinize the relabeling in isolation and confirm it is not masking a judge degradation. This is enforced by review practice: `calibrate_judge.py` inspects artifact *content*, not git commit history, so it cannot catch a bundled relabel on its own.
- **Freshness (timestamp age only).** The gate checks that `recorded_scores.json`'s `generated_at` is within `FRESHNESS_MAX_AGE_DAYS` (180 days) — a stale (or future-dated) timestamp fails. It checks the timestamp's AGE only; it cannot tell whether the snapshot was actually re-generated. When the seed ages out, honestly re-snapshot by re-running the judge — bumping `generated_at` without re-running is a code-review concern the gate cannot detect.

### Honest scope (what this gate does NOT catch)

The per-commit gate catches regressions in the **recorded snapshot and the fixture harness**: a fixture dropped from a map (fails closed), a non-discriminating recorded snapshot (`good.md` no longer out-scores the `bad_*.md` fixtures), or a mislabeled gold (recorded verdicts no longer match `verdicts.jsonl`). It does **NOT** exercise the live judge or the live aggregator (`aggregate.py`) — every check replays *recorded* numbers, so a bug introduced into the aggregator or judge logic AFTER the snapshot is invisible until `recorded_scores.json` is regenerated by re-running the judge. In particular it does **NOT** catch *judge-quality drift*: a judge that has silently gotten worse but whose old snapshot is still on disk will still pass. Detecting a degraded *live* judge needs the stochastic kappa-vs-gold sweep (re-running the judge over position-swapped pairs), which is **deferred to Phase 3** — a live LLM call cannot be made flake-free, so it must be a nightly-alerting signal, not a per-commit gate (`calibrate(mode="full")` is the Phase-3 stub for it and currently raises `NotImplementedError`).

---

## Flag selection

The `--reviewers code|runtime|full` flag picks which review lane runs against the diff. Three values are valid; the default is `code`.

### `--reviewers` flag values

| Value | What runs | Required deps |
|---|---|---|
| `code` (default) | The 6 code lenses (correctness, bugs, security, test-quality, style, plan-conformance) | None — diff input is sufficient |
| `runtime` | Runtime lenses (UI / Backend / Frontend per `review-gauntlet`'s runtime model, dispatched `model: sonnet` per the arm pin) | `--start-cmd` and `--url` |
| `full` | All 6 code lenses + the runtime lenses | `--start-cmd` and `--url` |

When `--reviewers runtime` is specified, the 6 code lenses do NOT run; only the runtime lenses do. When `--reviewers full` is specified, both fire. Per the cross-step `lens_verdicts[]` contract (Aggregation § Audit-trail JSON sidecar schema), the 6 code-lens entries appear at indices 0–5 always — with `overall_verdict: "SKIPPED"` and empty `findings: []` arrays when only runtime mode runs — and runtime-lens entries (if any) appear at index 6 and onward. This keeps the stable 6-element prefix consumers can rely on regardless of which lane was selected.

Selection rule of thumb: default to `code`. Add `runtime` only when the step's `Done when:` includes a visual, screenshot, or HTTP-response assertion the diff alone cannot evaluate AND a fresh Playwright context can actually reach the verifiable state. Use `full` when the step spans backend logic and frontend behavior and both lenses pay off.

### Static vs runtime authority

The two lanes have structurally different blast radii — neither one is a superset of the other. Per `docs/investigations/review-agents/20-static-vs-runtime-authority.md`:

| Authority | Can see | Cannot see |
|---|---|---|
| Static (code lenses) | Diff text; surrounding source files; plan step (if `--plan-step`); git history; project conventions | Whether the app actually starts; whether routes 200; visual regressions; backend log output; frontend console errors; network failures |
| Runtime (runtime lenses) | App startup behavior; HTTP status codes; rendered HTML; screenshots; backend logs; frontend console; HAR network capture | Logic in code paths not exercised by the runtime probe; test files (unless run); plan-conformance (Static owns this); subtle correctness in untaken branches |

Implication: static can't tell you whether the diff RUNS; runtime can't tell you whether the diff IS CORRECT in the parts that didn't execute. A `runtime`-only run on a logic-heavy diff can ship a correctness bug the screenshots happen to miss; a `code`-only run on a real visual diff can ship a layout break the diff text reads as fine. `full` mode is the union — pay for both lenses when the diff's blast radius justifies the cost. The choice is which bug surface is visible at all, not a calibration knob. See investigation 20 for the long-form rationale and the open question of whether `full` disagreements between a code-HIGH and a runtime-CONFIRMED should be resolved by aggregator rule 2.

### Auth-gated runtime downgrade

When `--reviewers runtime` or `--reviewers full` is specified, the skill probes `--url` BEFORE spawning runtime reviewers. The probe is a single HTTP GET with a 10-second timeout. The probe result determines whether to downgrade per the rationale in `docs/investigations/review-agents/11-auth-gated-runtime.md` (toybox K17 hit: `--url http://127.0.0.1:4000/child` sat behind a kiosk PIN gate; four screenshots all showed "Enter parent PIN" and the reviewer cleanly PASSed the gate while zero of the diff's behavior was exercised).

**Auth-gate detection (any of these triggers downgrade):**

1. **HTTP status 401** (Unauthorized) — explicit auth challenge.
2. **HTTP status 302** (Redirect) to a Location URL containing `/login`, `/signin`, `/auth`, or `/sso` in its path (case-insensitive) — typical auth redirect pattern. Other 3xx codes (301/303/307/308) follow the same rule when the redirect target matches the path heuristic. The reason-string format is `redirect_to_login:<full-Location-URL>` (the URL is included verbatim as curl reports it via `%{redirect_url}`).
3. **HTTP status 200 with login-shaped HTML** — body contains, case-insensitive, an `<form>` element and (`type="password"` OR `name="password"` OR `name="pin"`). The form opener and the password input may be on different lines (real-world HTML is typically multi-line); implementations MUST use a multi-line-aware matcher (e.g., `grep -iz`, `pcre2grep -M`, or whole-body matching in a non-line-oriented language). This catches single-page apps and server-rendered pages that show a login form at HTTP 200.
4. **Probe timeout** (no response within the 10s budget — covers both connect-timeout and total-transaction-time exhaustion). Treated as un-evaluable. Downgrade to code-only (do NOT assume auth-gated — the lenses can't run either way, and the timeout itself is the signal).

**On downgrade:**

- Runtime lenses are NOT spawned.
- The aggregated report's markdown summary includes a `Runtime downgrade: <reason-token> (<gloss>)` line in the `## Lens verdicts` subsection — where `<reason-token>` is the literal enum value from the JSON sidecar (`status_401` / `redirect_to_login:<url>` / `login_form_in_200_body` / `timeout`) and `<gloss>` is a human-readable expansion (e.g., `HTTP 401 Unauthorized`, `Redirected to /login`, `Login form detected in 200 body`, `Probe exceeded 10s timeout`). The enum token is the cross-step contract; the gloss is presentation.
- The JSON sidecar's `invocation.reviewers_flag` echoes the ORIGINALLY-requested value (`runtime` or `full`) — downgrades do NOT rewrite the requested flag, so the audit trail preserves operator intent. Two new fields are set: `invocation.runtime_downgraded = true` AND `invocation.runtime_downgrade_reason = "<reason>"`. The reason string is one of `"status_401"`, `"redirect_to_login:<full-Location-URL>"`, `"login_form_in_200_body"`, or `"timeout"`. (Cross-step contract with Aggregation § Audit-trail JSON sidecar schema: these two fields are part of the `invocation` object's REQUIRED schema and the example block above includes them.)
- For `--reviewers full`, the 6 code lenses still run — only the runtime lenses are dropped. `aggregated_verdict.result` is computed from the code-lens verdicts as usual.
- For `--reviewers runtime` (pure runtime mode), downgrade means runtime lenses are dropped AND the 6 code lenses do NOT run (they weren't selected). The 6-element-prefix contract is honored by emitting all 6 code-lens entries with `overall_verdict: "SKIPPED"` and `findings: []` (skipped because they weren't selected, not because of plan-conformance's gracefully-skip rule — the SKIPPED verdict shape is the same; the rationale string differentiates: `"Skipped: --reviewers runtime selected, code lenses not requested"`). The aggregator emits `aggregated_verdict.result == "NEEDS-WORK"` with rationale citing the runtime downgrade. The operator can re-invoke with `--force-runtime` if the probe was a false positive, or downgrade the invocation to `--reviewers code` if static review is sufficient.

**Cross-step schema parity (producer-consumer-drift prevention).** The two fields above (`runtime_downgraded` and `runtime_downgrade_reason`) are owned jointly by this section AND by the Aggregation § Audit-trail JSON sidecar schema example block. The example block has been updated in the same diff that introduced this section. If a future change renames either field, update both sites in the same diff — drift between the two sites is a `producer-consumer-drift` finding under the anti-pattern catalog (see Anti-pattern catalog § `anti-pattern: producer-consumer-drift`).

### `--force-runtime` override

`--force-runtime` is a boolean flag (declared in the Arguments table at the top of this file) that disables the auth-gate probe. When set:

- The probe is NOT run.
- Runtime lenses fire regardless of what `--url` returns.
- The JSON sidecar's `invocation.force_runtime` is `true`; `invocation.runtime_downgraded` stays `false`; `invocation.runtime_downgrade_reason` stays `null`.

`--force-runtime` is for two cases:

1. **Known-false-positive auth-gate detection.** The page renders a `<form type="password">` for an unrelated reason (e.g., a search filter, a password-strength demo, an embedded credential-rotation widget) and the operator knows the runtime reviewers can still reach useful content past it.
2. **The auth-gate IS the target of review.** The `--url` legitimately serves a login page that the diff is supposed to ship — the auth UI is the feature, and runtime reviewers SHOULD exercise the gate.

**Caveat:** `--force-runtime` skipping the probe means runtime lenses may produce `NO-EVIDENCE` verdicts if they encounter the actual auth gate. That's by design — the operator gets explicit signal that they overrode the safety net and the lenses couldn't see useful content, rather than a silent downgrade that hides the override decision from the audit trail.

### Probe script

The probe is implemented at `scripts/auth_gate_probe.sh` (see `scripts/README.md` for the full contract). Invocation pattern, run before spawning runtime lenses when `--reviewers runtime|full` and NOT `--force-runtime`:

```bash
if RUNTIME_DOWNGRADE_REASON="$(bash scripts/auth_gate_probe.sh --url "$URL")"; then
  echo "Auth-gate detected: $RUNTIME_DOWNGRADE_REASON. Downgrading to code-only."
  # Set sidecar fields: invocation.runtime_downgraded=true, invocation.runtime_downgrade_reason=$RUNTIME_DOWNGRADE_REASON
fi
```

Exit code 0 = downgrade-with-reason on stdout (one of `status_401`, `redirect_to_login:<url>`, `login_form_in_200_body`, `timeout`); exit code 1 = no downgrade. The 4 trigger conditions and their semantics are documented above in `### Auth-gated runtime downgrade`.

---

## Tools

Three mechanical helpers live under `scripts/` — extracted from the SKILL.md prose so their contracts are auditable in isolation and the SKILL.md context cost stays bounded. Full per-script contracts (usage, exit codes, dependencies, output schema) live in `scripts/README.md`; the canonical-prose cross-links below point at the SKILL.md section that owns the helper's semantics.

- **`scripts/auth_gate_probe.sh`** — Probes `--url` for auth-gate conditions (HTTP 401, 3xx redirect to `/login|/signin|/auth|/sso`, HTTP 200 with login-shaped HTML, or probe timeout) and signals whether to downgrade runtime lenses to code-only. Canonical prose: `### Auth-gated runtime downgrade` (above). Invocation: `bash scripts/auth_gate_probe.sh --url <url>`; exit 0 + reason token on stdout = downgrade, exit 1 = proceed.
- **`scripts/aggregate.py`** — Multi-lens verdict aggregator: reads per-lens JSON verdicts, applies aggregator rules 1-7 (severity dominance, lens-owns-dimension, SKIPPED/FAILED/NO-EVIDENCE handling, persistent-disagreement via `--prior-sidecar`, absence-of-thing dedup), writes the audit-trail sidecar, prints the markdown summary. Canonical prose: `## Aggregation` (above). Invocation: `python scripts/aggregate.py --lens-dir <dir> --output-dir <dir> [--skill-version v3] [--prior-sidecar <path>]`.
- **`scripts/lint_prepass.sh`** — Optional deterministic linter pre-pass. Auto-detects file extensions in `git diff --name-only HEAD` (or in a caller-supplied `--diff-paths <comma-or-space-separated>` list), runs `ruff` + `mypy` on `.py` files and `eslint` on `.ts/.tsx/.js/.jsx` files when each tool is both installed AND configured (mypy: `mypy.ini` or `pyproject.toml[tool.mypy]` in an ancestor of cwd up to git root; eslint: `.eslintrc*` likewise), and writes `lint-findings.json` to `--output-dir` with a unified `{tool, rule, file_line, message}` finding shape plus `tools_run` / `tools_skipped` provenance. Missing linters and missing configs are graceful skips, not failures (the script exits 0 and `findings: []` is valid). Full contract: `scripts/README.md` § `lint_prepass.sh`. Invocation: `bash scripts/lint_prepass.sh --output-dir <dir> [--diff-paths <comma-or-space-separated>]` — invoke from the project root (cwd), not from the script's directory.

**Optional by orchestrator choice.** `lint_prepass.sh` is not part of the default lens pipeline; the orchestrator decides whether to run it based on a cost/value tradeoff (a tiny doc-only diff doesn't benefit; a multi-file refactor does). The Bugs / Style / Test-quality lenses are wired in Step 4 to read `lint-findings.json` when it exists in the output directory, so running the pre-pass shifts deterministic noise off the LLM lenses' attention budget. The pre-pass never replaces a lens — it pre-files the cheap mechanical findings so the LLM can focus on the categories tools cannot detect.

---

## Scope-boundary deferral

The `DEFERRED-TO-UAT` verdict exists because some parts of a diff are structurally
un-evaluable by a sub-agent reviewer. Approving-by-omission ships bugs into
production; blocking-on-inability halts the autonomous build for things the
reviewer was never able to check. Deferral is the third path: the reviewer
explicitly hands those parts to the operator with named copy-paste commands so
the audit trail records that the un-evaluable slice was acknowledged, not
silently passed. See `docs/investigations/review-agents/15-scope-boundary-uat.md`
and `docs/investigations/review-agents/34-hitl-deferral.md` for the long-form
rationale.

### When deferral fires

The DEFERRED-TO-UAT verdict fires when the reviewer structurally cannot
evaluate part of the diff. Concrete trigger conditions:

1. **Auth-gated UI behind PIN/SSO/2FA the reviewer cannot bypass.** A fresh
   Playwright context only sees the auth page; runtime lenses report
   `NO-EVIDENCE`; code lenses see the diff but cannot verify the behind-auth UX
   matches the diff's claims. This overlaps with Flag selection §
   Auth-gated runtime downgrade (Step 6), but `DEFERRED-TO-UAT` is the
   verdict-level outcome when the downgrade leaves a structural coverage hole
   — the downgrade prevents `NO-EVIDENCE` from runtime lenses, but the
   behind-auth behavior remains un-evaluated.
2. **Kiosk-mode UX.** Tablet/phone-locked-down UX (e.g., toybox's child kiosk)
   where the runtime lens's desktop browser context cannot reach the actual
   UX the diff changes.
3. **Hardware integration.** Diffs that affect printer drivers, microphone
   capture, IoT sensors, USB peripherals, GPS — anything the reviewer cannot
   simulate.
4. **Multi-device flow.** Diffs where verification requires action on a second
   device (operator's phone scanning a QR code displayed on the screen,
   hardware fob, paired-device pairing).
5. **External-system handshake.** Diffs that depend on responses from
   third-party services (Stripe webhook receipts, OAuth provider redirects,
   email delivery confirmations) the reviewer cannot reliably reproduce.
6. **Multi-step user journeys with non-trivial state machines.** Diffs that
   require N>2 user actions to validate (login → navigate → upload → verify),
   where each step depends on prior step's actual result rather than
   synthetic state. Runtime lenses can chain ~2-3 actions reliably; beyond
   that, deferral.

The trigger conditions are NOT exhaustive — operator judgment applies. The
aggregator emits `DEFERRED-TO-UAT` (populating `deferred_uat_items[]` and
computing `aggregated_verdict.result` per `## Aggregation § Aggregated-verdict
output ladder`) based on TWO concrete producers:

1. **Step 6's auth-gate downgrade** (`invocation.runtime_downgraded == true`).
   When the runtime probe detected an auth gate AND the originally-requested
   `--reviewers` value was `runtime` or `full`, the aggregator synthesizes a
   deferred item with `reason: "Runtime downgraded:
   <runtime_downgrade_reason>"`, `covered_lenses: <lenses that did run>`,
   `needs_verification: "Operator must verify behavior past the auth gate."`,
   and `recommended_commands: []` (or a curated suggestion if the orchestrator
   knows enough — typically empty for downgrades).
2. **Lens-emitted defer-finding.** A lens MAY emit a finding with
   `severity: "Block"` AND `anti_pattern: "scope-boundary-deferral"` (a
   reserved anti-pattern name NOT in the standard catalog; this is the
   wire-format signal). The aggregator scans `lens_verdicts[].findings[]` for
   this specific marker, transforms each match into a `deferred_uat_items[]`
   entry using the finding's `rationale` as `reason` and `excerpt` as
   `needs_verification`, and demotes the original finding's severity to
   `FYI` (since it's now surfaced as a deferral, not a Block requiring a
   fix). The lens prompt that emits the finding MUST also provide
   `recommended_commands` in the `rationale` as a `Recommended verification:
   <command>` suffix; the aggregator extracts these into the entry's
   `recommended_commands[]`.

The reserved `anti_pattern: "scope-boundary-deferral"` marker is documented
here and is the ONLY way (besides the Step 6 auth-gate downgrade) for a lens
to surface a deferral. It is intentionally NOT in the anti-pattern catalog
because it's a wire-format signal, not a defect pattern.

Cross-reference `docs/investigations/review-agents/15-scope-boundary-uat.md`
and `docs/investigations/review-agents/34-hitl-deferral.md`.

### Deferred-item shape, M-numbering, and markdown rendering

Each entry in `deferred_uat_items[]` is a five-field dict — `reason` (one-sentence prose naming WHAT the reviewer cannot reach and WHY, operator-facing), `covered_lenses` (the lens_ids whose verdicts DID complete a useful review; empty `[]` when no lens covered any part of the deferred slice), `needs_verification` (one sentence specific enough that an operator coming in cold knows what to look at — not "verify it works" but "verify the new sprites render and FPS stays above 30 during the walkthrough"), `recommended_commands` (array of copy-paste-ready shell commands per the workspace's `feedback_copy_paste_commands.md` rule; `#`-prefixed lines are operator-facing comments inside the same fenced block, NOT executed), and `uat_id` (the M<N> handoff identifier per `feedback_name_manual_verification_handoff.md`). All five are REQUIRED; the orchestrator drops partial entries during aggregation.

M-numbering is implemented in `scripts/aggregate.py`'s `assign_m_numbers(deferred_items)` function, whose docstring is the canonical convention spec. Summary: within a single review-deep invocation, items are numbered starting at `M1` in lens-emission order (lens-spawn order is correctness → bugs → security → test-quality → style → plan-conformance → runtime lenses); across invocations the numbering RESETS to M1 (review-deep does NOT track prior invocations — that's `/build-phase`'s append-only Manual UAT block in `plan.md`); the operator-facing cue is an explicit `Please run M<N> next.` line as the last thing in the markdown summary, taking whichever is the lowest M-number in the current sidecar's `deferred_uat_items[]`. Operators who want review-deep's deferrals merged into the plan-level M-series copy them by hand into the plan's Manual section, re-numbering at the open slot (the M-naming-trap caveat in `feedback_name_manual_verification_handoff.md` applies — grep the plan's existing M-series first to find the free slot before reusing a number).

The markdown rendering for the `## Deferred to operator UAT` section is implemented in `scripts/aggregate.py`'s `render_markdown` function. Per item: H3 `### M<N>: <reason>`, bullet `- **Covered lenses:** <comma-separated names or "none">`, bullet `- **Needs verification:** <needs_verification>`, bullet `- **Commands to run:**` followed by a fenced powershell block (workspace default — operators on POSIX adapt) of the `recommended_commands` array one-per-line. The H2 section is PRESENT when the markdown header is `# review-deep: DEFERRED-TO-UAT` or `# review-deep: NEEDS-WORK + DEFERRED-TO-UAT`, and ABSENT otherwise. Section / field renames MUST touch both `scripts/aggregate.py` AND this paragraph in the same diff (producer-consumer-drift prevention).

### Example worked deferred item

A complete example with all fields populated, showing what a toybox
kiosk-mode review would emit:

```json
{
  "reason": "Auth-gated child kiosk UX at /child requires PIN-entry the runtime probe cannot reach.",
  "covered_lenses": ["correctness", "bugs", "security", "test-quality", "style", "plan-conformance"],
  "needs_verification": "After PIN entry, the child kiosk shows the new 'energy elements' sprites and the sprite-rendering performance does not drop below 30 FPS during the 60-second walk-through.",
  "recommended_commands": [
    "uv run python -m toybox serve --port 4000",
    "# In a separate terminal, open http://127.0.0.1:4000/child in the kiosk browser",
    "# Enter parent PIN, navigate to 'Activities' -> 'Energy Elements'",
    "# Observe sprite rendering and FPS via the dev-mode overlay (Cmd+Shift+D)"
  ],
  "uat_id": "M1"
}
```

The markdown rendering uses the same fields as the JSON shape above, ends
with `Please run M1 next.` (the cue line), and is followed by the
audit-trail pointer. The example is illustrative — actual deferred items
vary by diff. The shape is canonical; the content is realistic.

---

## Cross-references

- `~/.claude/skills/review-gauntlet/SKILL.md` — lean profile over this engine (terse PASS/NEEDS-WORK, no JSON sidecar)
- `~/.claude/skills/review-proof/SKILL.md` — primary-source verification discipline
- `dev/docs/investigations/review-agents/README.md` — the 35-file investigation set seeding this skill (paths shown from the dev/ workspace root)
- `dev/.claude/rules/code-quality.md` — anti-pattern catalog source (the bugs lens references it by name)
- `dev/.claude/rules/plan-and-issue-flow.md` — plan-step format source (the plan-conformance lens reads as ground truth)
