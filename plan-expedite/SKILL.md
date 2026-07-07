---
name: plan-expedite
description: Chain plan-review-autofix, plan-wrap-autofix, repo-sync, and task-handoff into one autonomous prep step before /build-phase. Required arg --plan <path>. Default continues in-window — emits a /goal + /build-phase command pair (the /goal arms the Stop hook over the agent-completable build span); auto-compaction handles context (no forced /compact). Use --new-window to restore the session-wrap copy-paste prompt.
user-invocable: true
---

# Plan Expedite

`/plan-expedite --plan <path>` runs the full plan -> sync -> handoff pipeline as one
autonomous step. Default output: TWO continue commands in order — first a `/goal
"<condition>"` line that arms the Stop hook over the agent-completable span, then the
`/build-phase --plan <path>` command — both to run **in the same window** — no forced
`/compact`, because auto-compaction handles
context on its own when it fills and the `SessionStart` re-inject hook reloads `current.md`
afterward. (A focused `/compact` before the long build is optional — see step 4.) Add
`--new-window` to get the old session-wrap copy-paste prompt for a fresh window instead.

---

## Execution model — autonomous, invoke sub-skills via the Skill tool (HEAVY)

This skill's whole reason to exist is that the operator does not want to type `/plan-review` → wait → `/plan-wrap` → wait → `/repo-sync` → wait → `/session-wrap`. They invoked `/plan-expedite` to have those four happen as one autonomous run. Therefore:

1. **Execute, do not advise.** When invoked, you MUST invoke each sub-skill via the `Skill` tool in the order specified in the "Sub-skill chain" section. Do NOT respond by emitting the chain as text (e.g. "Next: `/plan-review` → `/plan-wrap` → `/repo-sync` → `/session-wrap` → `/build-phase`"). That listing-the-steps response is the single most common failure mode for this skill — if you find yourself about to type that sentence, stop and call the `Skill` tool instead.

2. **No mid-run confirmations.** Do not ask "Should I run /plan-review now?", "Apply autofixes?", "Proceed to /plan-wrap?", "Ready to sync issues?", or any other (y/n) gate. The operator opted into the chain by invoking `/plan-expedite`. Halt only on the cases the "Halt template" section enumerates — sub-skill non-zero exit, genuine ambiguity surfaced under "Needs your input:" requiring operator judgment, or missing sub-skill. Everything else proceeds.

3. **Minimal between-step narration.** Between sub-skill invocations, one brief sentence is enough ("plan-review returned READY with 3 autofixes applied; invoking plan-wrap"). Do not re-describe what the next sub-skill is going to do — its SKILL.md handles that.

4. **Final output is the continue command(s) (or, with `--new-window`, the transition prompt), verbatim.** On default success, the final output is TWO lines in order — a `/goal "<condition>"` line (scoped to the agent-completable automated span, per Step 4 of the chain) followed by the `/build-phase --plan <path>` command — no summary, paraphrase, or "here's what to do next" preamble. With `--new-window`, the `/session-wrap` output (with the same `/goal` line surfaced above the build line) IS the final output; emit the code-fence block as-is.

---

## When to use

- After `/plan-init` or `/plan-feature` produces a plan.md, before `/build-phase` runs.
- When you want one command instead of remembering plan-review -> plan-wrap -> repo-sync -> session-wrap in order.
- Re-running is safe: each sub-skill is idempotent on already-applied state (per autofix-applied markers from Steps 7-8) and `/plan-expedite` skips already-completed sub-skills (per `.plan-expedite-state` resume detection).

## When NOT to use

- Mid-build-phase (this skill is a PRE-build prep; /build-phase has its own flow).
- For ad-hoc plan edits without intent to ship (use individual skills directly).
- If you want to manually review autofix changes before applying (use individual skills with --no-autofix).

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--plan` | yes | -- | Path to the plan.md file (e.g., `documentation/foo-plan.md`) |
| `--new-window` | no | false | Use `session-wrap` as the final step instead of `task-handoff --next-task`. Produces a 300-word copy-paste prompt for a fresh window. Use when you always want the old behavior. |

## Flow

### Stale-plan check (per BPA plan section 5 D9)

Check `plan.md`'s mtime before invoking any sub-skill. If >30 days old, print a warning but CONTINUE — do not bail:

```text
warning: plan.md was last modified <N> days ago (<date>). Autofix may reshape stale plans significantly. Continuing — review the auto-applied fixes before /build-phase if drift is a concern.
```

### Resume detection

Check for `.plan-expedite-state` JSON file in the project root (sibling to plan.md). Schema:

```json
{
  "plan_path": "documentation/foo-plan.md",
  "plan_mtime": 1779167384.42,
  "handoff_mode": "in-window",
  "completed": [
    {"skill": "plan-review", "verdict": "READY", "timestamp": "..."},
    {"skill": "plan-wrap", "verdict": "READY", "timestamp": "..."}
  ],
  "halted_at": null
}
```

`handoff_mode` is `"in-window"` (default — `task-handoff --next-task`) or `"new-window"`
(`--new-window` flag — `session-wrap`). Recorded at run start; used by resume logic to
invoke the correct final sub-skill on re-entry.

`plan_mtime` is a numeric float — seconds since the Unix epoch, as returned by `os.path.getmtime(plan_path)` or `stat -c %Y`. No timezone, no string parsing. Comparison uses a 1-second tolerance: `abs(current_mtime - state_mtime) <= 1.0`. The tolerance accommodates filesystems with different mtime precision (NTFS records to 100ns, FAT32 rounds to 2s) and avoids spurious "plan changed" detections from format-only round-trips.

Logic:
- If file does not exist: fresh run, execute all 4 sub-skills sequentially.
- If file exists AND `abs(current_mtime - state.plan_mtime) <= 1.0`: skip every sub-skill in `completed[]`. Start from the first uncompleted (or from where `halted_at` left off).
- If file exists BUT the mtime difference exceeds 1 second: plan was edited since last run; discard the resume state and start fresh.
- **Malformed state file:** if `.plan-expedite-state` exists but is invalid JSON, missing required keys (`plan_path`, `plan_mtime`, `completed`, `halted_at`), or has the wrong shape (e.g., `plan_mtime` not numeric, `completed` not a list), log a warning citing the malformation, rename the bad file to `.plan-expedite-state.malformed-<timestamp>` for forensics, and treat as a fresh run (proceed with all 4 sub-skills). Do NOT halt — an autonomous prep skill should self-heal from corrupted resume state, not require operator intervention to clear it.

Update `completed[]` with the sub-skill name and write the file back after each successful sub-skill. On halt, set `halted_at` to the sub-skill name that failed and persist.

### Sub-skill chain

Call each sub-skill below via the `Skill` tool, in order. Before the first invocation, `cd` to the project root containing `<plan-path>` (use the Bash tool). Between invocations, one brief progress sentence ("plan-review returned READY; invoking plan-wrap") is enough — do NOT re-emit the chain as prose.

**Path-passing contract:** only `/repo-sync` documents a `--plan` CLI flag in its Arguments table; `/plan-review`, `/plan-wrap`, and `/session-wrap` operate on the plan via conversation context (they read the plan path from the invoking turn's prose or from cwd). Pass the path via the `args` parameter of the `Skill` call so the sub-skill picks it up.

Read the exit code and final verdict line after each `Skill` call returns. On success, append to `completed[]` in `.plan-expedite-state` and proceed to the next sub-skill. On halt, write the halt template (see below) and stop.

1. **Invoke `plan-review` via the Skill tool** with `args: "--autofix <plan-path>"`.
   - Success criteria: verdict READY, or "READY (auto-fixed N items)", or NEEDS WORK with only clarifying questions auto-answerable.
   - Halt criteria: genuine ambiguity surfaced under "Needs your input:" requiring operator judgment, OR sub-skill non-zero exit, OR sub-skill missing.

2. **Invoke `plan-wrap` via the Skill tool** with `args: "--autofix <plan-path>"`.
   - Success criteria: verdict READY, "READY (auto-fixed N items)", "READY WITH GAPS: M gaps" (plan-wrap-only — 0 Blockers, M≥1 Gaps, /repo-sync may proceed), or NEEDS WORK with only clarifying questions auto-answerable.
   - Halt criteria: same as plan-review (genuine ambiguity under "Needs your input:" requiring operator judgment, OR sub-skill non-zero exit, OR sub-skill missing).

3. **Invoke `repo-sync` via the Skill tool** with `args: "--plan <plan-path>"` (autonomous default per Step 6 — no `--dry-run`).
   - Same success / halt criteria.

4. **Invoke the final sub-skill, then emit the continue command** — depends on `--new-window`:

   **Default (no `--new-window`):** Invoke `task-handoff` via the Skill tool with
   `args: "--next-task build-phase"` (it writes current.md + MEMORY + push — the durable
   handoff state).
   - Then emit the two continue commands VERBATIM as the `/plan-expedite` final output,
     BOTH inside ONE fenced code block (goal first, build command second) so the operator
     copies both in a single action — continue in the SAME window (auto-compaction handles
     context, no forced `/compact`). No preamble, no summary — the final output IS this one
     block. The `/goal` arms the Stop hook over the automated span and is user-typed (a
     skill cannot arm `/goal` itself), so it sits above `/build-phase`:
     ```
     /goal "<condition>"
     /build-phase --plan <plan-path>
     ```
   - **Derive the `<condition>` from the plan, scoped to the AGENT-COMPLETABLE slice.**
     plan-expedite has already read the plan, so enumerate its steps. The agent-completable
     (automated) steps are the ones the agent builds end-to-end with its own tools:
     `Type: code` and `Type: conditional`. NOT agent-completable: every `Type: operator`
     step, every Manual M-step (M1/M2/M3), AND every `Type: wait` step — a `Type: wait`
     step is an intentional build-phase halt (halt-contract class #4: the orchestrator
     stops and the operator resumes in a fresh session after the clock-gated wait), so its
     finish line is not reachable by the agent in-session. Build the condition over ONLY
     the contiguous automated (`code`/`conditional`) steps up to the FIRST
     operator / Manual-M / wait boundary — a goal that spans an operator, Manual M-step,
     or wait step busy-loops forever, because the Stop hook re-fires against a finish line
     the agent's own tools cannot reach. Form:
     `"<plan-name> automated steps <N..M> are all marked Status: DONE in <plan-path>
     (issues #<a>-#<b> closed), and `<test-cmd>` / `<typecheck-cmd>` / `<lint-cmd>` exit 0
     — STOP before the operator/wait/Manual steps (M1/M2/M3, issues #<x>-#<y>); those are an
     operator handoff, not part of this goal"`. Cite the GitHub issue numbers for the
     automated steps and for the closing/quality-gate conditions wherever the plan makes
     them derivable; omit a clause only if the plan genuinely lacks it. If the plan is
     all-automated (no `Type: operator` steps, no `Type: wait` steps, and no Manual
     M-steps), target ALL steps and drop the STOP-before clause.
   - Record `handoff_mode: "in-window"` in `.plan-expedite-state`.
   - **Optional focused reset.** A proactive `/compact` before a long build-phase gives
     cleaner context than auto-compaction's best-guess summary — but it is the operator's
     choice, not the default, and is never auto-emitted as the mandated output (there is no
     way to trigger `/compact` programmatically). If they want it, they type it first:
     `/compact Focus on build-phase for [plan-name]: step list in plan.md, issue numbers
     filled, current.md has next action`.

   **`--new-window` mode:** Invoke `session-wrap` via the Skill tool with
   `args: "<plan-path>"`.
   - Output: 300-word copy-paste transition prompt for a fresh window.
   - Surface the SAME agent-completable `/goal "<condition>"` line (derived per the
     Default-branch bullet above) inside that prompt, ABOVE the `/build-phase --plan
     <plan-path>` line, so the fresh window arms the Stop hook before starting the build.
     If `session-wrap` does not already include it, prepend the `/goal` line to the paste
     block (prepending one line is not paraphrasing the prompt body).
   - Emit the prompt VERBATIM as the `/plan-expedite` final output. Do not paraphrase,
     do not summarize, do not add a preamble.
   - Record `handoff_mode: "new-window"` in `.plan-expedite-state`.

   The `--new-window` flag is the escape hatch for users who want the old fresh-window
   copy-paste flow instead of continuing in-window.

### Halt template (per BPA plan section 5 D8 — generic, no per-skill enumeration)

Write the following template verbatim on any sub-skill non-success exit:

```text
/plan-expedite halted at: <sub-skill name>
Reason: <captured stderr / verdict line>
Plan state: <unchanged | partially autofixed (cite which fixes applied per the autofix-applied markers in plan.md)>
GitHub state: <unchanged | issues created/updated (cite count if repo-sync ran)>
To resume: fix the cited issue, then re-run /plan-expedite --plan <path>
           (already-completed sub-skills are skipped via state inference from .plan-expedite-state)
```

Stop without producing the final continue command / transition prompt after printing. The `.plan-expedite-state` records `halted_at: <sub-skill name>` for resume.

Use the same five-line template regardless of which sub-skill fails (plan-review, plan-wrap, repo-sync, session-wrap); per-sub-skill diagnostic detail belongs in the cited stderr, not in `/plan-expedite`'s template.

## Relationship to other skills

| Skill | Role |
|---|---|
| `/plan-init`, `/plan-feature` | Produce the plan.md `/plan-expedite` operates on |
| `/plan-review`, `/plan-wrap` | Autofix sub-skills (Steps 7-8 of BPA plan) |
| `/repo-sync` | Issue-sync sub-skill (Step 6) |
| `/session-wrap` | Transition-prompt sub-skill (existing) |
| `/build-phase` | Continues in-window from the `/goal` + `/build-phase` commands /plan-expedite emits (the `/goal` arms the Stop hook over the automated span; or, with `--new-window`, the session-wrap transition prompt carrying both) |

## Limitations

- Resume state lives in a single `.plan-expedite-state` file in the project root. Multiple concurrent `/plan-expedite` invocations on the same plan have undefined behavior — don't do that.
- Concurrent operator edits to `.plan-expedite-state` during a run have undefined behavior. Don't edit the file while `/plan-expedite` is running.
- Sub-skill failures halt the chain; resume requires manual operator inspection. By design — autofix's promise is to handle the boring cases, not the surprising ones.
