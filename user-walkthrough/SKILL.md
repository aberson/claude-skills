---
name: user-walkthrough
description: Attended, operator-driven acceptance of a just-built tool or feature. Establishes a persistent operating contract on entry, then YIELDS each turn to the operator — you ask questions or point at problems, the agent answers from primary source, fixes small things in-tree on the spot, logs big ones without rabbit-holing, marks UAT coverage as a byproduct, and hands the turn back. Use for post-/build-phase exploration where the operator wants to drive. Invoke as "/user-walkthrough <tool/feature>".
user-invocable: true
---

# User walkthrough

Attended, **operator-driven** UAT. You (the operator) drive; the agent rides along. Each turn
you ask a question or point at a problem; the agent answers from PRIMARY SOURCE (reads the
actual code/artifact, cites `file:line` — never vibes), marks any coverage the exchange earned,
routes issues to fix-now or log-for-later, then **stops and hands the turn back**. Coverage
accrues as a byproduct of poking the build, not as a script you march through.

The ledger it reads and writes is defined once in
[`.claude/references/shakedown-engine.md`](../../references/shakedown-engine.md) — this skill
never redefines the row grammar, slug rule, or status vocabulary; it cites the engine.

## When to use / not

- **Use:** a tool or feature was just built (post-`/build-phase`, post-`/build-step`, or a
  fresh `/bug-fix`) and you want to poke it yourself — ask how it works, try things, surface
  issues — with the agent answering from source, fixing small breakage live, and tracking what
  got covered. You want to be in the driver's seat.
- **Don't use** when you want the agent to close out UAT autonomously (that is
  `/user-shakedown`), to execute an already-written UAT block for you (`/user-uat`), or to
  refine a fuzzy UAT script (`/review-uat`). If you have no build to poke yet, there is nothing
  to walk through.

## Invocation

```text
/user-walkthrough <tool/feature>     # attended walkthrough of the named build
/user-walkthrough export-button      # slug resolves the ledger per the engine's slug rule
```

## Flow

### 1. Entry — orient, establish the contract

1. **Resolve or derive the ledger** per the engine reference: compute the feature-slug, resolve
   the ledger path via `git rev-parse --show-toplevel`, and **load it if it already exists**
   (never re-seed — a prior walkthrough or shakedown may have started it). If absent, derive it
   per the engine's checklist-derivation rules (seed from the plan's `## Manual UAT` /
   `Type: operator` M-steps when present; else a lightweight derived expectation set).
2. **State the operating contract once**, then yield: "I'll answer from source with `file:line`,
   fix small things in-tree and show you, log big ones, and mark coverage as we go. You drive —
   ask or point at anything." Optionally kick off the tool and show its output to seed the first
   turn.

### 2. Loop — one operator turn at a time

Per turn the operator asks a question or reports a problem. The agent:

1. **Answers from PRIMARY SOURCE.** Read the actual code/artifact and cite `file:line`. Never
   answer a "does it / how does it" question from memory or inference — open the file. A
   confidently-wrong answer from vibes is worse than "let me check."
2. **Marks coverage earned this turn.** If the exchange exercised a behavior matching a ledger
   row, mark that row `satisfied` with concrete evidence (the command output / observed result /
   `file:line`) per the engine's coverage-marking rule — never a bare status flip.
3. **Routes any issue** by size, per the engine's two paths:
   - **Small + unambiguous → fix it now, in the live tree.** Edit in place (uncommitted), run
     the NARROWEST test, mark the row `fixed` with evidence. Do **not** spin a `/build-step`
     worktree; the fix must be visible to the running tool immediately. **Never block on a
     (y/n) for your own small fix — just make it and report what you did.**
   - **Big → log it, don't rabbit-hole.** Append the row `logged` with a one-line diagnosis and
     move on; it becomes a sibling issue at wrap.
4. **STOP and hand the turn back.** One operator ask → one agent response → stop. Do not keep
   working, do not chain into the next check unprompted, do not march a script. Yielding is the
   whole point of the attended mode.

### 3. Wrap — "did I miss anything?"

When the operator signals they're done (or asks for a wrap), report coverage in three buckets:
`satisfied` (with evidence), still-`open`, and `logged` bigs. Then **offer** — do not execute —
three closers:

1. **Batch-commit the live fixes** as one reviewable diff, using scoped `git add <paths>` of
   only the files this walkthrough touched (never `git add -A`).
2. **File the logged bigs** as GitHub sibling issues (via `gh` with `--body-file`) that feed
   `/plan-feature` or `/build-step`.
3. **Emit the canonical `/goal` string** from the engine to hand autonomous closure to
   `/user-shakedown`:
   `/goal "shakedown ledger for <feature-slug> has zero open items"`

The operator picks which closers to run — this is the attended mode; the operator decides.

## Constraints

- **MUST NOT arm a `/goal` DURING the loop.** A `/goal` arms a Stop hook that re-prompts the
  *agent* every turn until its condition holds — which makes the session agent-paced and
  destroys the operator-driven dynamic (the agent would keep working instead of yielding to
  you). The `/goal` string is **emitted at wrap only**, opt-in, for the operator to paste. This
  is the single hardest rule in this skill.
- **Never block on a (y/n) for the skill's own small fixes.** Make the fix, run the narrowest
  test, report it. The operator is already in the loop every turn; a confirmation gate is noise.
- **Never write into any plan's `## Manual UAT` block.** That block is append-only and owned by
  `/build-phase`. The ledger is a SEPARATE task-state artifact (per the engine's path formula) —
  status lives there, never in plan.md.
- **Answer from primary source, always.** Every substantive claim cites `file:line`. No vibes.
- **Small fixes stay in the live tree, uncommitted until wrap.** No worktree; scoped commit at
  wrap only.

## Limitations — four-mode disambiguation

Four sibling UAT modes; pick by who drives and what shape the input is:

| Skill | What it does |
|---|---|
| `/user-uat` | EXECUTES an already-clear UAT script FOR you (mechanical tier auto-judged). |
| `/review-uat` | REFINES a fuzzy UAT script until every step is unambiguous. |
| `/user-walkthrough` | **This skill.** The operator DRIVES exploration; the agent answers, fixes small, logs big. |
| `/user-shakedown` | The agent AUTONOMOUSLY CLOSES the ledger to zero open items (same engine). |

`/user-walkthrough` and `/user-shakedown` share the same ledger file (same slug rule → same
path), so a walkthrough can hand a half-filled ledger to a shakedown mid-stream.

## Canonical example — one loop turn

> **Operator:** "Does the CSV export respect the active date filter?"
>
> **Agent:** Reads `src/export/csv.py:41-58` — the query is built from `request.filters` and the
> date range is applied at line 47. Cites it: "Yes — `csv.py:47` folds `filters.date_range`
> into the WHERE clause before serialization." Marks ledger row `M1` **satisfied** with
> evidence `csv.py:47 applies date_range`. **Stops, hands the turn back.**
>
> **Operator:** "The export button label says 'Exprot'."
>
> **Agent:** Small + unambiguous → fixes it in the live tree (`templates/export.html:12`), runs
> the narrowest test (`pytest tests/test_export_template.py -k label` → 1 passed), marks the row
> **fixed** with that evidence. No (y/n). **Stops.**
>
> **Operator:** "Export of a 2M-row table times out."
>
> **Agent:** Big → does NOT rabbit-hole. Appends a **logged** row with the one-line diagnosis
> "streaming/pagination needed for large exports; synchronous path blocks." **Stops.**
>
> At wrap: reports `M1` satisfied, the label fixed, the timeout logged; offers to batch-commit
> the label fix, file the timeout as a sibling issue, and emit the `/goal` string for shakedown.
