---
name: build-queue
description: Queue N pending phase plans and run them unattended overnight. For each item invoke /plan-expedite then /build-phase via the Skill tool, isolating each in its own worktree. On any halt, park the phase by filing a GitHub issue with halt context and proceed to the next queue item. Polls a kill-switch file between items. Emits a morning summary. Invoke as "/build-queue --queue <path>".
user-invocable: true
---

# Build Queue

`/build-queue --queue <path>` runs an unattended overnight orchestration of multiple phase plans. Each queue item gets the full `/plan-expedite` -> `/build-phase` chain. Halts are converted to GitHub issues, not retries — the operator triages in the morning from the summary report.

---

## Constraints

Execution model: autonomous, queue-driven, halt-then-proceed (HEAVY). This skill exists so the operator can stage 3-5 pending phase plans, kick off `/build-queue` before bed, and wake up to a triage list. The whole point is that no halt — even a reviewer-gate failure on a code step — pulls the operator out of bed. Therefore:

1. **Halt-then-proceed, not halt-then-retry.** This is the load-bearing design choice. When any queue item halts (via the `/build-phase` halt contract — see [`.claude/rules/code-quality.md` § "Build-phase halt contract"](../../rules/code-quality.md)), this skill does NOT auto-retry, does NOT mutate the plan, does NOT try a different approach. It captures the halt context, files a single GitHub issue on the plan's repo titled `[build-queue parked] <plan name>: <halt class>`, marks the queue item as `PARKED`, and proceeds to the next item. Auto-retry would fight the halt contract (5 legitimate halts, anything else is a defect) and burn tokens on undiagnosable failures. The operator's morning triage IS the retry decision.

2. **Sequential, never parallel.** Queue items run one at a time. Parallel `/build-phase` on different plans has burned tokens in the past (memory: `feedback_parallel_buildphase_same_plan`). The queue's whole value is honest, sequential, surviveable execution.

3. **Kill-switch is the only mid-run control.** Between queue items, this skill checks for a `.build-queue-killswitch` file in the queue file's directory. If present (any contents, any size), it stops cleanly after the current item: writes a partial morning summary noting the kill-switch was hit, persists state for resume, and exits. The operator creates it with `touch <queue-dir>/.build-queue-killswitch`. The skill never asks "should I continue?" — the file is the answer.

4. **Final output is the morning summary, verbatim.** When the queue drains (or the kill-switch stops it), the morning summary IS the final output. It is also written to `.build-queue-report-<timestamp>.md` next to the queue file for later reference.

This is by strong operator preference; treat any deviation as a defect.

---

## When to use

- 3+ phase plans are staged across one or more projects and can ship overnight unattended.
- The operator has time to triage parked items in the morning but does not want to babysit reviewer gates at 3am.
- Plans have already been through `/plan-expedite` once (issues minted) OR are fresh and want the full prep chain — `/build-queue` calls `/plan-expedite` per item, so either is fine.

## When NOT to use

- Single phase: use `/build-phase` directly (or `/plan-expedite` + `/build-phase` if not yet prepped).
- Plans with `Type: wait` steps as the only remaining work — `/build-phase` will halt on wait steps and `/build-queue` will park them; nothing useful happens overnight.
- Mid-day interactive work where the operator wants to react to each halt — the park-then-proceed posture is wrong for that mode.
- When the queue's plans are not yet through `/plan-review` and `/plan-wrap` — let `/plan-expedite` (invoked per-item by this skill) handle it.

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--queue` | yes | -- | Path to queue file (see "Queue file format" below) |
| `--dry-run` | no | -- | Parse queue + print resolved item list + exit. No `/plan-expedite` or `/build-phase` calls. |
| `--resume` | no | -- | Resume from a prior partial run. Skips queue items already marked DONE or PARKED in `.build-queue-state`. |

No other flags. Per-item flags (which `/build-phase` to run, phase number, etc.) live in the queue file, not on the `/build-queue` invocation.

---

## Queue file format

Plain text. One queue item per non-blank, non-comment line. Comments start with `#`.

```text
# Each line: <plan-path-relative-or-absolute> [--phase N] [extra build-phase flags]
# Plan paths resolve relative to the queue file's directory if not absolute.

documentation/phase-g-plan.md
documentation/phase-2.1-plan.md --phase 1
../toybox/documentation/phase-n-plan.md
../alpha4gate/documentation/phase-4.7-plan.md --phase 2 --steps 1,2,3
```

Parse rules:

- Lines starting with `#` are comments; ignored.
- Blank lines ignored.
- First whitespace-separated token is the plan path; everything else is forwarded to `/build-phase` as flags.
- A plan path containing whitespace must be wrapped in double quotes (rare on this workspace).
- Order = execution order. No reordering.

At Step 0 pre-flight, resolve every plan path to an absolute path and verify the file exists. Any missing plan path is a queue-level pre-flight error: print all missing paths and exit without running anything. (Halting mid-queue on a typo would waste the night.)

---

## Steps

### Step 0: Pre-flight

Before invoking any sub-skill, do all of the following. Halt the entire run on any failure here — these are setup errors that compound if ignored.

1. **Kill-switch check.** If `.build-queue-killswitch` exists in the queue file's directory at startup, print `kill-switch present at startup; refusing to run. rm <path> to clear.` and exit. The operator may have forgotten it from a prior session.

2. **Parse queue file.** Apply the parse rules above. Emit a resolved table of `(item-index, abs-plan-path, forwarded-flags)`.

3. **Verify plan files exist.** For each resolved plan path, check the file exists and is readable. Collect all failures; if any, print the full list and exit.

4. **State file check.** Look for `.build-queue-state` in the queue file's directory (schema below). If `--resume` was passed:
   - If the file exists AND its `queue_path` matches AND its `queue_mtime` matches the current queue file's mtime (1-second tolerance): use the existing state, skip items already marked DONE or PARKED.
   - If the file exists BUT the queue file has been edited since: discard and start fresh (print a warning).
   - If the file does not exist: start fresh.
   - If `--resume` was NOT passed and the state file exists: rename it to `.build-queue-state.prior-<timestamp>` and start fresh. (Resume is opt-in to avoid silent surprises.)

5. **Dry-run exit.** If `--dry-run` was passed, print the resolved item list (including which items would be skipped under `--resume`) and exit without invoking any sub-skill.

### Step 1: Per-item loop

For each queue item in order (skipping those already DONE or PARKED under `--resume`):

1. **Kill-switch poll (between items).** Check for `.build-queue-killswitch`. If present: write a partial morning summary noting the kill-switch was hit before item N, persist state, exit.

2. **`cd` to plan's project root.** This is the directory containing the plan file. All subsequent `gh` and worktree calls must run from here, not from the queue file's directory. (`gh` repo context — see [`.claude/rules/windows-shell.md`](../../rules/windows-shell.md).)

3. **Invoke `/plan-expedite` via the Skill tool** with `args: "--plan <abs-plan-path>"`.
   - Success: proceed to step 4.
   - Halt: park this item (see "Park procedure" below). Proceed to next item.

4. **Invoke `/build-phase` via the Skill tool** with `args: "--plan <abs-plan-path> <forwarded-flags>"`.
   - Success: append the DONE entry below to `.build-queue-state`'s `items[]`. Proceed to next item.
   - Halt: park this item (PARKED entry shape below). Proceed to next item.

5. **State file update.** After each item (DONE or PARKED), rewrite `.build-queue-state` (exact filename, in the queue file's directory) as a complete, valid JSON document — not an incremental append — BEFORE moving to the next item. The full `items[]` array (all entries so far) must be present. Each entry must include `item`, `plan`, `verdict`, and `timestamp` keys; DONE entries additionally include `commits` and `issues_closed`; PARKED entries additionally include `halt_reason` and `issue` (number or null). If the process is killed mid-loop, the next `--resume` run starts from the right place.

   DONE entry appended to `.build-queue-state`:

   ```json
   {"item": 1, "plan": "C:/.../phase-g-plan.md", "verdict": "DONE", "timestamp": "2026-05-23T22:47:00Z", "commits": 7, "issues_closed": [41, 42, 43]}
   ```

   PARKED entry appended to `.build-queue-state`:

   ```json
   {"item": 2, "plan": "C:/.../phase-2.1-plan.md", "verdict": "PARKED", "timestamp": "2026-05-23T23:18:00Z", "halt_reason": "Quality-gate hard fail", "issue": 99}
   ```

   When narrating per-item completion in the run output, refer to the state file as `.build-queue-state` (exact filename — not "the state file" or "state was updated") and include the appended JSON entry verbatim, so the appended shape and the filename are both visible per item.

### Park procedure (on any halt)

When `/plan-expedite` or `/build-phase` halts for any reason — halt contract, autofix failure, missing plan field, anything:

1. **Capture context.** Grab:
   - The halt message verbatim (from the sub-skill's final output).
   - The plan path (absolute).
   - The queue item index.
   - Current branch + last commit on the worktree, if a worktree exists (`git worktree list` shows it).
   - Timestamp.

2. **File a GitHub issue.** From the plan's project root (cwd from Step 1.2), use `gh issue create` with `--body-file <tmp-file>` (NOT inline `--body` — workspace rule). Title: `[build-queue parked] <plan-filename>: <halt-class-or-first-line>`. Body:

   ```markdown
   ## Parked by /build-queue

   - Queue item: <N> of <total>
   - Plan: <abs-path>
   - Timestamp: <iso>
   - Worktree: <path or "none">
   - Branch: <branch or "n/a">
   - Last commit: <sha + subject, or "n/a">

   ## Halt output

   <verbatim halt message from /plan-expedite or /build-phase>

   ## Resume

   Triage this halt, then either:
   - Fix and re-run the single plan: `/plan-expedite --plan <abs-path>` then `/build-phase --plan <abs-path>`
   - Remove the item from the queue (or mark it DONE in the queue file via comment) and resume the overnight: `/build-queue --queue <queue-path> --resume`
   ```

   On `gh` failure (rate limit, auth, repo not found): print the captured context to stdout AND write it to `.build-queue-park-item-<N>.md` next to the queue file. The item still gets marked PARKED in state — the issue filing is best-effort observability, not a halt condition.

3. **State file update.** Append `{"item": N, "verdict": "PARKED", "plan": "<path>", "halt_reason": "<halt-class>", "issue": <number or null>, "timestamp": "<iso>"}` to `items[]`.

4. **Proceed.** Continue the loop. Do NOT halt the overnight run on a park — that's the whole design.

### Step 2: Morning summary

After the loop drains (or the kill-switch stops it), emit the morning summary to stdout AND write it to `.build-queue-report-<timestamp>.md` in the queue file's directory.

```markdown
# /build-queue summary

Queue: <queue-path>
Started: <iso>
Ended: <iso>
Duration: <Hh Mm>
Status: <COMPLETE | KILL-SWITCH | PRE-FLIGHT-FAILED>

## Items

| # | Plan | Verdict | Commits | Issues closed | Park issue |
|---|------|---------|---------|---------------|------------|
| 1 | phase-g-plan.md | DONE | 7 | #41, #42, #43 | -- |
| 2 | phase-2.1-plan.md | PARKED | 2 | #44 | #99 |
| 3 | phase-n-plan.md | DONE | 5 | #50, #51 | -- |
| 4 | phase-4.7-plan.md | SKIPPED (kill-switch) | -- | -- | -- |

## Triage list (parked items)

- #99 (phase-2.1, item 2): <halt-class summary> — see issue for context.

## Numbers

- Items attempted: 3 of 4
- Items DONE: 2
- Items PARKED: 1
- Items SKIPPED: 1 (kill-switch)
- Total commits landed: 12
- Total issues closed: 5
- Total park issues filed: 1
```

When there are zero parked items, the "Triage list" section is omitted. When there are zero DONE items, that's worth surfacing prominently at the top of the summary ("Status: COMPLETE (0 of N items DONE — investigate").

---

## State file schema

`.build-queue-state` in the queue file's directory, JSON. Gitignored.

```json
{
  "queue_path": "queue.txt",
  "queue_mtime": 1779200000.0,
  "started": "2026-05-23T22:00:00Z",
  "items": [
    {
      "item": 1,
      "plan": "C:/.../phase-g-plan.md",
      "verdict": "DONE",
      "commits": 7,
      "issues_closed": [41, 42, 43],
      "timestamp": "2026-05-23T22:47:00Z"
    },
    {
      "item": 2,
      "plan": "C:/.../phase-2.1-plan.md",
      "verdict": "PARKED",
      "halt_reason": "Quality-gate hard fail (test count regressed)",
      "issue": 99,
      "timestamp": "2026-05-23T23:18:00Z"
    }
  ],
  "kill_switch_hit_before_item": null
}
```

Comparison uses 1-second tolerance for `queue_mtime` (same NTFS/FAT32 reasoning as `/plan-expedite`'s state file).

Malformed state file under `--resume`: rename to `.build-queue-state.malformed-<timestamp>` and start fresh with a warning. Do NOT halt — this is observability state, not load-bearing.

---

## Relationship to other skills

| Skill | Role |
|---|---|
| `/plan-expedite` | Invoked per-item to prep each plan (plan-review-autofix + plan-wrap-autofix + repo-sync + session-wrap) |
| `/build-phase` | Invoked per-item to execute the plan's build steps; the halt contract here is the source of truth for what halts mean |
| `/loop` | Different shape — `/loop` repeats one prompt on an interval; `/build-queue` drains a queue of distinct plans once |
| `/repo-update` | Not invoked by this skill; each `/build-phase` step closes its own issue, but the post-phase docs+README+commit pass is left for the operator to run per-project in the morning |

## Limitations

- One queue at a time per directory. Two `/build-queue` runs on the same queue file have undefined behavior (state file races). Don't do that.
- Per-item halts file an issue on the plan's repo — requires `gh auth status` to be valid for every distinct repo in the queue. Pre-flight does NOT verify `gh auth` per repo; first halt on a non-authed repo falls back to the local `.build-queue-park-item-N.md` file.
- No cross-item dependencies. If item 2's plan depends on item 1 landing first, that's an ordering responsibility of the operator (and the queue ordering preserves it). The skill does not detect dependency violations.
- No auto-rollback. If a `/build-phase` lands partial commits then halts mid-step, those commits remain on the branch. `/build-phase` itself does not roll back; `/build-queue` does not either. The morning triage owns rollback decisions.
- The morning summary's "commits landed" and "issues closed" counts come from `/build-phase`'s own state output, NOT a separate `git log` scan. If `/build-phase` lies or under-reports, the summary inherits that.
