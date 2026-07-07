---
name: user-uat
description: Run an already-clear UAT block FOR the operator — execute each step, capture the real output, and auto-judge only the mechanically-checkable ones (exit code, output match, refusal text, DB/HTTP/file/log); escalate every judgment call with evidence. Removes the run-command → paste-output → relay loop. Use when the operator has a concrete UAT/manual-smoke block (a plan M-step, a "commands + what to look for" table, or ad-hoc "run these, expect these") and wants the mechanical tier done for them. Invoke as "/user-uat [source] [--deep] [--dry-run] [--yes-side-effects]".
user-invocable: true
---

# User UAT

Execute an **already-clear** UAT block so the operator doesn't have to be the mechanical
relay (run command → eyeball output → paste it back). The skill runs each step, captures
the real result, and **auto-judges only the deterministically-checkable steps**; everything
that needs judgment is escalated with the evidence attached.

It does **two things deliberately NOT**: it does not *refine* a fuzzy script (that is
`/review-uat`), and it does not *replace the operator* for checks that genuinely need a
human. The win is the mechanical tier — which is most of the volume.

## When to use / not

- **Use:** a concrete UAT exists — a `Type: operator` plan M-step, a build-phase "Manual UAT"
  bundle, the "commands + what to look for" table from a handoff, or the operator pasting
  "run these and tell me what happens." Steps have commands and observable expectations.
- **Don't use** to write or refine a UAT. If steps are ambiguous (verb with no object, "expect
  X" with no observable, no pass criteria), **STOP and delegate to `/review-uat`** — do not
  guess what a step means. A run built on a guessed expectation is worse than no run.

## Invocation

```text
/user-uat                       # use the UAT block from the current conversation
/user-uat path/to/plan.md#M4    # run the M-step at this anchor
/user-uat --dry-run             # classify + print what WOULD run (mechanical / side-effectful / escalated); run nothing
/user-uat --deep                # also agent-JUDGE the judgment-class checks; each flagged 'agent-judged: <verdict> — confirm?'
/user-uat --yes-side-effects    # auto-run side-effectful steps too (trusted flow); default gates them
```

## The partition (the load-bearing rule)

Operator UAT exists to catch what agent self-checks miss (agents grading agent-written work
codify regressions — toybox G2; the audit-wire-shape rule). So **never auto-PASS a check that
isn't deterministic.** Classify every step's *action* and *verify* (separately) into:

| Tier | The verify is… | Default behavior |
|---|---|---|
| **Mechanical** | exit code, "stdout contains X", "refuses with Y", a DB row / count, HTTP status, file on disk, a log line | **Auto-judge** PASS/FAIL — show the observed value as evidence |
| **Agent-judgeable** | "output looks grounded", "the ship-vs-park call was right", a diff reads sensibly | **Escalate** with evidence (default). With `--deep`: agent assesses too, labeled `agent-judged: <verdict> — confirm?` |
| **Human** | visual / layout / animation, audio, real-device, kid-facing feel, anything credentialed or physical the agent can't drive | **Always escalate** — a crisp one-line ask, never a verdict |

**When classification is ambiguous, treat the verify as human and escalate.** A
mechanical-judgement applied to a judgment-class check is exactly how the blind spot leaks
back in.

## Flow

1. **Ground + classify (no guessing).** For each step emit a classification line:
   `Step N (source: file:line / M-anchor) — action: <command>; verify: <expectation>; Tier: Mechanical / Agent-judgeable / Human`
   The source citation must appear on the per-step classification line, not just in a header.
   Valid tiers are exactly three: **Mechanical**, **Agent-judgeable**, **Human** — there is no
   "Ungroundable" category. If a step can't be grounded or is ambiguous → stop, report it,
   and point at `/review-uat`.
2. **Safety gate.** Tag each command read-only/preview vs **side-effectful** (mutates state,
   is outward-facing, or is hard to reverse — e.g. a real `goblin do` that auto-ships into a
   sibling repo, a deploy, an external send, a DB write/drop, a `git push`, starting a process
   that writes or sends anything). Auto-run the safe ones; **pause and confirm before each
   side-effectful one** (unless `--yes-side-effects`). **Never rationalize a side-effectful step
   as "probably read-only" to skip the confirmation gate.** If reversibility / outward-facing-ness
   is unclear, treat it as side-effectful and confirm (fail safe). Prefer the step's own
   `--dry-run`/preview when it has one.
3. **Run the auto-tier.** For each step, run its *action* (subject to the step-2 side-effect
   gate — the action may be agent-run, or a human/side-effectful one you've confirmed), capture
   stdout/stderr + exit code, then **auto-judge only the mechanical-tier verify** against its
   concrete expectation. Show the **actual observed value** inline — data, not editorializing. A
   mechanical **FAIL stops the run** (don't barrel past a failure into dependent steps), then
   still emit the step-5 report for the steps that ran + which step failed (observed-vs-expected).
4. **Judgment tier.** For agent-judgeable / human steps: present the captured evidence + the
   expectation and **escalate** (default). With `--deep`, also give the agent's assessment for
   the agent-judgeable ones — flagged `agent-judged: <verdict> — confirm?`, with any uncertainty named.
   Human-tier steps always escalate regardless of `--deep`.
5. **Report (terse).** One line per step — **plain text, not a markdown table**:
   `step → AUTO-PASS / AUTO-FAIL / ESCALATED → one-line evidence`
   Example: `M4 row 1 → AUTO-PASS → exit 0, stdout contains "shipped"`
   Then a **"Needs you"** section (use that exact heading) listing each escalated item as a
   **terse single-sentence ask** — no captured output blocks, no interpretive framing. End by
   naming what's left (e.g. "Please eyeball M4 row 3 and M4 row 5; the rest passed").

## Safety + discipline

- **Never auto-PASS a non-mechanical check.** Mechanical = auto; agent-judgeable = escalate
  (or `--deep` + label); human = always escalate.
- **Gate side effects.** Read-only/dry-run/preview auto-run; destructive or outward-facing
  steps confirm first. `--yes-side-effects` only for a flow the operator has declared trusted.
- **Delegate, don't guess.** Fuzzy/ungroundable script → `/review-uat`, not a guessed run.
- **Push back on state mismatch.** If the operator (or `--deep`) calls something PASS but the
  mechanical check disagrees, surface the discrepancy verbatim (`observed X, expected Y`) plus
  ONE disambiguating question — don't rubber-stamp (per `feedback_uat_pushback_on_state_mismatch`).
- **Show the data.** Every verdict cites the observed value; a verdict with no evidence is a
  defect.

## Relationship to other skills

- **`/review-uat`** — the refinement partner. It tightens a fuzzy UAT (and can `--exec` a
  refined one); `user-uat` is the terse *run-an-already-clear-one* path and hands fuzzy input
  back to it. Refine with review-uat, then run with user-uat.
- **`/verify`** — runs the app to confirm a code change works; `user-uat` runs a *defined UAT
  script*, partitioning auto-vs-human across its steps.
- **`/build-phase`, `/build-step`** — their `Type: operator` / "Manual UAT" outputs are exactly
  the blocks `user-uat` is built to execute.
- **`/user-walkthrough`, `/user-shakedown`** — the two operator-acceptance siblings for a
  just-built feature with no clear script yet. `/user-uat` EXECUTES an already-clear script;
  `/user-walkthrough` is operator-DRIVEN exploration (you drive, the agent answers from source /
  fixes small / logs big); `/user-shakedown` AUTONOMOUSLY CLOSES the resulting UAT ledger to zero
  open items. Poke a fresh build with a walkthrough/shakedown; run a defined block with user-uat.
