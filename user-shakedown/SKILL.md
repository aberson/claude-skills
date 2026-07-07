---
name: user-shakedown
description: Autonomous UAT closure of a just-built tool or feature. Same ledger/engine as /user-walkthrough, but the agent drives itself — for each open item it verifies (with evidence), quick-fixes in-tree (narrowest test), or logs it (one-line diagnosis) until the ledger has zero open items. Designed to run armed under a /goal whose zero-open condition is mechanically checkable every turn. STOPS (logs, never guesses) on anything needing operator judgment. Invoke as "/user-shakedown <tool/feature>".
user-invocable: true
---

# User shakedown

Autonomous **ledger closure**. Where `/user-walkthrough` yields to the operator each turn, this
skill drives itself: it works down the ledger's open items — verifying, quick-fixing, or logging
each — until the ledger has zero open items. It is **pipeline-autonomous**: no confirmation
prompts, and at wrap it EXECUTES the closers rather than offering them. It STOPS (by logging,
never guessing) on anything that genuinely needs operator judgment.

The ledger it reads and writes is defined once in
[`.claude/references/shakedown-engine.md`](../../references/shakedown-engine.md) — this skill
never redefines the row grammar, slug rule, or status vocabulary; it cites the engine. Because
it uses the same slug rule, it resolves the **same** ledger file a `/user-walkthrough` may have
started, and picks up mid-stream (load-before-derive per the engine — never re-seed).

## When to use / not

- **Use:** UAT needs to be *closed out* on a just-built feature and you want the agent to do it
  autonomously — ideally armed under a `/goal` so it re-drives itself every turn until the
  ledger is clean. Good for draining a walkthrough's leftover open rows, or a fresh closure pass.
- **Don't use** when you want to drive the exploration yourself (that is `/user-walkthrough`),
  when you have an already-clear script to just execute (`/user-uat`), or to refine a fuzzy UAT
  (`/review-uat`).

## Invocation

```text
/user-shakedown <tool/feature>     # autonomous closure of the named build's ledger
```

## Flow

### 1. Entry — resolve or derive the ledger

Compute the feature-slug and resolve the ledger path via `git rev-parse --show-toplevel` per the
engine reference. **Load the ledger if it exists** (never re-seed); else derive it per the
engine's checklist-derivation rules. Because the slug rule is shared, this is the exact file a
`/user-walkthrough <same feature>` would have written.

### 2. Closure loop — one open item at a time

For each row still `open`, choose exactly one disposition and record evidence:

- **Verify → `satisfied`.** Exercise the behavior, capture the result, mark the row `satisfied`
  with concrete evidence (command output / observed result / `file:line`). Never a bare flip.
- **Quick-fix in-tree → `fixed`.** If the item is a small, unambiguous defect: edit the live
  tree (uncommitted), run the NARROWEST test, mark the row `fixed` with that evidence. No
  worktree (per the engine's small-fix path).
- **Log → `logged`.** If it is too big to fix inline, OR it needs operator judgment (see the
  STOP-not-guess rule), append a one-line diagnosis and mark the row `logged`. Do not
  rabbit-hole.

Repeat until the engine's zero-open check reports `UNSATISFIED == 0` — that is the **only**
termination condition. Re-run the check each pass; when it returns 0, the ledger is closed.

### 3. STOP-not-guess rule (the escape hatch)

Anything that needs operator judgment — an ambiguous expectation, a design call, a
visual/credentialed/real-device check the agent cannot drive — is **parked as `logged` with the
judgment question recorded in the evidence cell**, never auto-resolved with a fabricated verdict.
Logging IS the no-guess escape hatch: it keeps zero-open reachable without the agent inventing a
pass it can't stand behind. A guessed verdict is a contract violation; a logged question is
correct behavior.

### 4. Wrap — EXECUTE the closers (autonomous)

Because this mode is pipeline-autonomous and the operator's standing default is to file sibling
issues without asking, at wrap it EXECUTES rather than offers:

1. **Batch-commit the live fixes** as one reviewable diff, using scoped `git add <paths>` of
   only the files this shakedown touched (never `git add -A`).
2. **File each `logged` row as a GitHub sibling issue** via `gh` with `--body-file` (the body
   carries the one-line diagnosis / judgment question), feeding `/plan-feature` or `/build-step`.

Then report the final ledger state and confirm `UNSATISFIED == 0`.

## Designed for /goal

This skill is built to run **armed under a `/goal`**. The canonical arm command (copy-paste,
from the engine) is:

```text
/goal "shakedown ledger for <feature-slug> has zero open items"
```

The condition is checkable **every turn** by running the engine's zero-open check block and
asserting `UNSATISFIED == 0`. The Stop hook re-drives this skill each turn until the ledger is
clean — the termination condition IS the goal condition, which is exactly why the autonomous
mode is the one designed to be armed (the inverse of `/user-walkthrough`, which must never arm a
`/goal` mid-loop).

## Constraints

- **Zero confirmation prompts.** A `(y/n)` gate is a defect here (per
  [`plan-and-issue-flow.md`](../../references/plan-and-issue-flow.md) § autonomous-by-default).
  The skill decides and acts; it does not check in mid-run.
- **Never guess a verdict.** Judgment items are `logged` with the question, not auto-passed.
- **Evidence on every status change.** A flip with no evidence cell content is a contract
  violation (the engine's coverage-marking rule).
- **Never write into any plan's `## Manual UAT` block.** Append-only, owned by `/build-phase`;
  the ledger is a separate task-state artifact.
- **Small fixes in the live tree, no worktree; scoped commit at wrap.** Never `git add -A`.

## Limitations — four-mode disambiguation

| Skill | What it does |
|---|---|
| `/user-uat` | EXECUTES an already-clear UAT script FOR the operator (mechanical tier auto-judged). |
| `/review-uat` | REFINES a fuzzy UAT script until every step is unambiguous. |
| `/user-walkthrough` | The operator DRIVES exploration; the agent answers, fixes small, logs big. |
| `/user-shakedown` | **This skill.** The agent AUTONOMOUSLY CLOSES the ledger to zero open items. |

`/user-walkthrough` and `/user-shakedown` share one ledger file (same slug rule → same path), so
this skill can pick up a walkthrough's half-filled ledger and drive it to zero.
