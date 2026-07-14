---
name: review-gauntlet
description: Lean code-review profile over review-deep's engine. Takes a developer prompt and code diff (positional args), runs review-deep's code lenses (correctness, bugs, security, test quality, style) with deterministic aggregation, and emits a terse PASS / NEEDS-WORK verdict — no JSON sidecar. Use after a developer agent produces a diff for a fast multi-lens gate; use review-deep directly when you need the full audit trail, plan-conformance, or runtime lenses.
user-invocable: true
---

# Review Gauntlet

> **Judging doctrine:** the producer-grader split, evidence-on-every-verdict,
> deterministic-aggregation, and primary-owner dedup rules this profile runs on
> live in [`_shared/judge-core.md`](../_shared/judge-core.md). review-gauntlet
> does not re-implement them — it inherits them through review-deep's engine
> (review-deep is one of judge-core's reference implementations, §10).

review-gauntlet is a **thin profile over [`review-deep`](../review-deep/SKILL.md)** —
not a separate review engine. It runs review-deep's **code lenses** (the
`--reviewers code` set) with review-deep's deterministic aggregation, but in a
**LEAN configuration**: positional args instead of named flags, and a terse
PASS / NEEDS-WORK report instead of review-deep's JSON audit-trail sidecar.

It exists so the common case — "review this diff, fast, give me a verdict" — has
a one-line invocation with no sidecar bookkeeping, while the heavy case
(high-stakes substrate / schema / key-shape diffs that want the full audit
trail, plan-conformance, runtime lenses, or `--prior-sidecar` persistent-
disagreement tracking) reaches for `review-deep` directly.

**review-gauntlet does NOT define its own reviewer prompts.** The lens
definitions, severity rubric, anti-pattern catalog, evidence discipline, and
aggregation rules are review-deep's — review-gauntlet points at them so the two
never drift as a duplicate pair. If you need to change how a lens reasons, edit
review-deep; the change flows through here automatically.

---

## Invocation contract

```
/review-gauntlet <prompt> <diff>
```

**Positional args (this is review-gauntlet's contract — NOT review-deep's named
`--prompt` / `--diff`):**

1. **`<prompt>`** — the developer's intent (what the diff is supposed to accomplish).
2. **`<diff>`** — the code diff to review. Same three accepted forms as review-deep:
   - A `git diff` output (staged, unstaged, or between commits)
   - A PR number (the skill fetches the diff via `gh pr diff <NUMBER>`)
   - An explicit paste of the changed code

If the invoker doesn't supply both a prompt and a diff, ask for them before
proceeding.

**No sidecar.** Unlike review-deep (which writes a JSON audit-trail sidecar to
`.review-deep/<timestamp>.json` by default), review-gauntlet writes **NO sidecar
and NO output file**. Its only output is the terse markdown verdict below,
printed to stdout. This is the lean contract — a fast gate, not an archived
audit trail. If you want the audit trail, run `review-deep` instead.

---

## What runs: review-deep's code lenses, lean

review-gauntlet maps to exactly this review-deep configuration:

| review-deep arg | review-gauntlet value | Why |
|---|---|---|
| `--prompt` | positional `<prompt>` | lean positional contract |
| `--diff` | positional `<diff>` | lean positional contract |
| `--reviewers` | `code` (the code-lens lane) | gauntlet is a static code gate |
| `--plan-step` | *(never passed)* | plan-conformance is review-deep's job; gauntlet's lens set is the 5 always-on code lenses |
| `--output-dir` / sidecar | *(suppressed)* | LEAN: no JSON sidecar written |

So an operator running `/review-gauntlet <prompt> <diff>` gets review-deep's
**five always-on code lenses** with deterministic aggregation:

1. **Correctness** — diff vs stated intent
2. **Bugs** — defects in the diff itself
3. **Security** — adversarial-input / secrets / unsafe-config defects (a free
   upgrade over the historical four-pass gauntlet, which had no Security lens)
4. **Test quality** — focus, trim, missing critical coverage
5. **Style and conventions** — surrounding-code conformance

The sixth review-deep lens, **plan-conformance**, only runs when `--plan-step`
is supplied; review-gauntlet never passes it, so plan-conformance reports
`SKIPPED` and does not affect the verdict (use `review-deep --plan-step ...` when
you want it). Runtime lenses (`--reviewers runtime|full`) are likewise out of
scope for the lean gate — reach for `review-deep` when a diff needs them.

**Lens definitions are review-deep's, verbatim.** Read review-deep's SKILL.md
for the authoritative per-lens Scope / Coverage / Non-coverage / evidence-shape /
severity-rubric / verdict-threshold sub-sections:

- [Correctness lens](../review-deep/SKILL.md#correctness-lens)
- [Bugs lens](../review-deep/SKILL.md#bugs-lens)
- [Security lens](../review-deep/SKILL.md#security-lens)
- [Test quality lens](../review-deep/SKILL.md#test-quality-lens)
- [Style and conventions lens](../review-deep/SKILL.md#style-and-conventions-lens)

The **anti-pattern catalog** (silent-wiring, producer-consumer-drift,
codifying-test-diff, silent-fallthrough-in-loop, silent-fallthrough-in-hot-path,
duplicate-shape-constants, create-table-without-migration), the **universal
evidence discipline** (every finding cites `file:line` + excerpt + reasoning),
the **`Block | Nit | FYI` severity rubric**, and the **cross-section dedup /
lens-owns-dimension** rules all live in review-deep's
[Anti-pattern catalog](../review-deep/SKILL.md#anti-pattern-catalog) and
[Aggregation](../review-deep/SKILL.md#aggregation) sections. review-gauntlet runs
them unchanged — it does not restate or fork them.

> **Lineage note.** review-deep's anti-pattern catalog cites this skill as the
> origin of its first three anti-patterns (silent-fallthrough-in-loop,
> duplicate-shape-constants, create-table-without-migration came from the
> historical review-gauntlet Bug Reviewer). Those definitions now live in
> review-deep as the single source of truth; review-gauntlet defers to them.

### Style-lens offload (switchboard, INERT BY DEFAULT)

review-gauntlet inherits review-deep's
[Style-lens local-judge offload](../review-deep/SKILL.md#style-and-conventions-lens):
the Style lens is the only code lens cheap enough to route to a local model, it
is **off unless switchboard offload is enabled**, and on a `defer` (the default)
it falls back to the Claude Style lens with no behavior change. The historical
`review-gauntlet-style` task_class remains a valid switchboard config slice
(tier-offload; Switchboard Decision 9) — it is the lean profile's name for the
same offload review-deep documents as `review-deep-style`. Either slice routes
ONLY the advisory Style judgment; the four deep-reasoning lenses (Correctness,
Bugs, Security, Test-quality) ALWAYS stay on Claude, and the aggregation step's
Claude final judge — never the local model — sets the gate (Decision 3).

---

## Aggregation and output (lean)

review-gauntlet uses review-deep's
[deterministic aggregation](../review-deep/SKILL.md#aggregation) over the five
code lenses' verdicts — the same severity-dominance, lens-owns-dimension,
NO-EVIDENCE-handling, and absence/lint dedup rules. The aggregation step is the
**Claude final judge** (Switchboard Decision 9): the lenses advise, this step
makes the single PASS / NEEDS-WORK call, and it always runs on Claude.

The **difference from review-deep is output only** — review-gauntlet emits a
terse report and **no JSON sidecar**:

```
## Review Gauntlet Results

### Correctness
<findings or "Correctness verdict: PASS">

### Bugs
<findings or "Bugs verdict: PASS">

### Security
<findings or "Security verdict: PASS">

### Test Quality
<per-test verdicts or "Test quality verdict: PASS">

### Style & Conventions
<findings or "Style verdict: PASS">

---

**Verdict: PASS / NEEDS-WORK**
```

Each finding renders in review-deep's evidence shape (`file:line` + excerpt +
reasoning). The five code-lens verdict lines (`Correctness verdict: …`, etc.)
are review-deep's, verbatim.

**Verdict logic** (review-deep's aggregated-verdict ladder, narrowed to the lean
code-lens gate — no `DEFERRED-TO-UAT`, since runtime/auth-gate deferral is a
review-deep-only path):

- **PASS** — zero `Block` findings and zero `Nit` findings across all five lenses
  (`FYI`-only is PASS), and no lens reported `NO-EVIDENCE`.
- **NEEDS-WORK** — any `Block` finding, any `Nit` finding, any lens at
  `NO-EVIDENCE`, or aggregated `Nit` count ≥ 3 (review-deep's soft-fail
  threshold).

If NEEDS-WORK, end with: "Want me to fix these issues, or discuss any findings first?"

---

## What NOT to do

- Do not re-define the reviewer prompts here — defer to review-deep's lens
  definitions (re-defining them is exactly the duplication this profile removes).
- Do not write a JSON sidecar or any output file — the lean contract is a terse
  stdout verdict. Use `review-deep` when you want the audit trail.
- Do not pass `--plan-step` or runtime flags — those are review-deep's lane.
- Do not let the local Style offload set the verdict — it is advisory; the Claude
  aggregation step is the gate.

---

## Cross-references

- [`review-deep/SKILL.md`](../review-deep/SKILL.md) — the engine this profile runs
  on (lens definitions, anti-pattern catalog, aggregation rules, severity rubric)
- [`_shared/judge-core.md`](../_shared/judge-core.md) — the judging doctrine both
  skills inherit
- [`review-proof/SKILL.md`](../review-proof/SKILL.md) — primary-source verification discipline
- `dev/.claude/rules/code-quality.md` — anti-pattern catalog source
