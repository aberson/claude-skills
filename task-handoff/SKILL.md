# task-handoff

Handles all in-window context transition types with the minimum work each requires.
Replaces `session-wrap` for transitions that do NOT end the session — only use
`session-wrap` (via `--end`) for true session endings where a new window is needed.

**current.md path contract (all write modes):** Always resolve via
`git rev-parse --show-toplevel` before reading or writing. Never use cwd-relative paths.
Writes inside a build-step worktree are deleted on cleanup.

```powershell
$gitRoot = git rev-parse --show-toplevel
$statePath = "$gitRoot/.claude/task-state/current.md"
```

---

## Native context management comes first

Most "transitions" are unnecessary — the harness already manages context for you:

- **Auto-compaction** (`autoCompactEnabled`, default on) fires automatically at the context
  threshold. You never need to type `/compact` to keep working; it summarizes and continues
  in the same session.
- **A `SessionStart` hook (matcher `compact|resume|clear`)** re-injects `current.md`'s Task /
  Status / Next Action automatically after any compaction, resume, or `/clear` — so resume is
  deterministic, not dependent on anyone remembering to re-read the file.
- **`/goal <condition>`** keeps the session working toward a goal across turns *and* across
  auto-compactions (it wraps a session-scoped Stop hook; a small fast model checks the
  condition each turn). Use it instead of `--new-goal`/`/clear` when the goal is pursued in
  one window.

What this means for task-handoff: **default to just keep working.** Reach for a mode only when
you need durable disk state (`--loop`), a *deliberate* focused compaction (`--next-task`), a
true context-pollution reset (`--new-goal`), or a real session end / new window (`--end`).
`current.md` (written by `--loop`) is the durable backstop auto-compaction lacks — it is what
the `SessionStart` hook re-injects.

There is **no** way to programmatically *force* `/compact` or trigger `/clear` from a skill
(hooks are reactive-only; no CLI/SDK trigger exists). So the modes that emit a `/compact` or
`/clear` command do so **only when a deliberate transition is genuinely wanted** — that is not
the default path.

---

## Natural language args

When args do **not** start with `--`, parse intent from the free-text phrase and route to
the matching mode. If no flag is invoked bare (e.g. `/task-handoff`), default to `--resume`.

### Phrase → mode table

| NL pattern | Maps to | Notes |
|---|---|---|
| "checkpoint", "save", "save state", "quick save", "write state" | `--loop` | |
| "next task [X]", "switching to [X]", "moving on to [X]", "then [X]", "after this [X]" | `--next-task X` | Extract label from trailing words |
| "resume", "orient", "what was I doing", "continue", "where was I" | `--resume` | |
| "new goal [X]", "pivot to [X]", "switch to [X]" (implies new project) | `--new-goal X` | Use when context implies project/goal change, not task change |
| "done", "end", "wrap up", "finish", "session over", "I'm done" | `--end` | |
| "wait for [cmd] every [N]", "poll [cmd] every [N]", "watching [cmd]" | `--wait cmd N` | |
| "run [X] then [Y]", "do [X] then [Y]", "execute [X] then [Y]" | in-place sequential | See below |

### "run X then Y" — in-place sequential execution

"run X then Y" (and equivalents: "do X then Y", "execute X and Y", "walk me through X and Y")
means **execute X and Y in this session without a NEW window.** This is a work-execution
request — task-handoff itself does NOT write current.md or emit a /compact command.

**Exception — transition-producing run-targets.** When X (or Y) is itself a skill whose own
contract ends in a transition (`plan-expedite`, `session-wrap`, or `task-handoff
--next-task`/`--new-goal`/`--end`), that skill WILL write current.md and/or emit a transition
prompt as *its* final step — task-handoff does not suppress it. The dispatch is still in-place
(no new window), but the net turn DOES transition. In that case the interpretation notice below
must NOT claim "(no transition)" — that would contradict the net outcome.

**Resolution steps:**

1. Look up X and Y in the active plan:
   - Check `current.md` for the plan path (Key Files section)
   - Otherwise search `docs/*-plan.md` files for steps whose titles match X or Y
   - Labels like "M1", "M2", "Step 3" match plan step names and Manual UAT entries

2. For each label in order (X first, then Y):
   - Extract the step's **Commands** and **What you're looking for** table from the plan
   - Walk through the step: run what can be automated, present what requires user interaction
   - For operator/UAT steps: set up any prerequisites, then pause with exact interactive
     commands for the user to run, and a verification table showing expected vs. actual

3. After X completes: proceed to Y without asking for confirmation.

**Emit a one-line interpretation notice before starting** — pick the variant matching the run-target:
- Default (X/Y are work-execution steps with no transition contract):
  ```
  task-handoff: NL args "run X then Y" → in-place execution; task-handoff writes no state. Starting X.
  ```
- When X (or Y) is a transition-producing skill (plan-expedite / session-wrap / task-handoff mode):
  ```
  task-handoff: NL args "run X" → in-place execution; X owns the final transition. Starting X.
  ```
Never emit a flat "(no transition)" when the run-target itself transitions — it contradicts the net outcome.
If the mapping is wrong, the user can re-invoke with an explicit flag.

### Ambiguous or unrecognized NL

If the phrase doesn't match any pattern and can't be confidently resolved:
1. Emit: `task-handoff: couldn't parse "[args]" — did you mean one of: [list top 2 closest modes]?`
2. If the phrase contains a recognizable label (project name, step number), bias toward `--next-task`.
3. Do NOT halt waiting for confirmation — make the best guess and note it inline.

---

## Modes

| Flag | Conditions | What it does | User action after |
|------|-----------|--------------|-------------------|
| `--loop` | 1, 6, 9 | Write/update current.md + git commit. ~5 sec. | None — continue |
| `--loop --no-commit` | Inside build-phase | Same write but NO git commit. Build-phase's Step 2e commit picks up current.md. Avoids double-commits and race-detection interference. | None — continue |
| `--next-task [label]` | 2, 11 | Durable task-boundary save: write current.md + MEMORY.md + commit + push. Then **keep working** on the next task in-window. ~30 sec. | None — continue. Optional: `/compact [focus]` for a focused reset (auto-compact handles it otherwise). |
| `--next-task [label] --no-push` | 2, 11 | Same as above but skips MEMORY.md update + push. For mid-task compress without pushing. | Type `/compact [output]` |
| `--resume` | 6, 8, 13 | Read current.md + git state + output orientation block in-window. No window switch. | None — continue |
| `--new-goal [name]` | 3, 7, 10 | Full state save + MEMORY update + commit + push. For a true context-pollution reset only. | Prefer `/goal <condition>` to pursue a new goal in-window. `/clear` only if a hard reset is needed. |
| `--end` | 4 | Delegate to `session-wrap` unchanged. | Copy-paste to new window (existing behavior) |
| `--wait [cmd] [interval]` | 9 | Write current.md + output `/loop [interval] [cmd]` invocation. | Invoke `/loop` |

---

## Conditions reference

| # | Condition | Description |
|---|-----------|-------------|
| 1 | Loop iteration | Same task retrying (build-step, soak poll, eval loop) |
| 2 | Sequential chain | Change tasks, same goal (plan-init → build-phase) |
| 3 | Change goal + task | Switch to planning something new mid-session |
| 4 | End session | True session end — no next window needed yet |
| 6 | Resume after interrupt | Crash, /stop, power loss mid-build |
| 7 | Parallel goal management | Two active plans / worktrees simultaneously |
| 8 | Reactive debug pivot | Build fails catastrophically → investigation mode |
| 9 | Observation/wait | Soak test running, polling for external result |
| 10 | Multi-project switch | Alpha4Gate → brickomancer context swap |
| 11 | Research-then-build | Discovery phase → implementation phase |
| 13 | Skill state leak | Hook blocked push, partial session-wrap interrupted |

---

## current.md write contract

All modes that write MUST follow this contract:

1. **Read existing file first** (if present) — to append Completed/Dead Ends, not overwrite them
2. **Overwrite:** WIP (Current + Approach), Next Action, Status, Session SHA, Last written
3. **Append:** Completed entries (since last write), Dead Ends, Critical Gotchas, Key Files
4. **Commit message:** `chore: task-state checkpoint [task] [status]`
5. **Timestamp format:** UTC ISO 8601 — e.g. `2026-06-15T14:30:00Z`
6. **SHA:** `git rev-parse --short HEAD` at write time

Write order:
```
(read existing current.md if present)
→ merge: append Completed/Dead Ends/Gotchas/Key Files, overwrite WIP+Next Action+Status+SHA+timestamp
→ write merged content to <git-root>/.claude/task-state/current.md
→ [unless --no-commit] git add + git commit
```

---

## `--loop` — lightweight inner-loop primitive

**Cost:** ~5 seconds. No user interaction. One-line output: `"Checkpoint written."`.

Skills call `--loop` after each meaningful action — after tests pass, after a hypothesis is
ruled out, before starting a new iteration. It should feel nearly zero-cost.

**`--loop --no-commit`** — same write, no commit. Use this inside `build-phase` to avoid
double-commits with build-phase's Step 2e checkpoint commit. Also prevents interference
with build-phase's 2d/2e race-detection ordering (which compares HEAD against origin before
committing — an extra commit inside the window breaks the comparison).

```powershell
# Example write (--loop mode)
$gitRoot = (git rev-parse --show-toplevel).Trim()
$statePath = "$gitRoot/.claude/task-state/current.md"
$sha = (git -C $gitRoot rev-parse --short HEAD).Trim()
$utcNow = [System.DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

# Overwrite WIP + Next Action; append to Completed if step done
# (merge logic: read file, update sections, write back)
# ...

# Commit (omit this block when --no-commit is set)
git -C $gitRoot add ".claude/task-state/current.md"
git -C $gitRoot commit -m "chore: task-state checkpoint [task] [status]"
```

---

## `--next-task [label]` — sequential task chain

**Cost:** ~30 seconds. Writes the durable task-boundary checkpoint, then continues in-window.

Use when switching from one task to the next within the same goal (e.g., plan-expedite →
build-phase). The default is to **keep working** — auto-compaction fires on its own when
context fills, and the `SessionStart` re-inject hook reloads `current.md` afterward, so no
manual `/compact` is required to cross a task boundary.

**Optional focused reset.** If you specifically want a *proactive*, focused compaction before
the next task (cleaner context than auto-compaction's best-guess summary), emit this for the
user to type — but only when genuinely wanted, not as the default:
```
/compact Focus on build-phase for [label]: step list in plan.md,
issue numbers filled, current.md has next action
```
(There is no way to trigger `/compact` programmatically — hooks are reactive-only — so a
deliberate focused reset is the one case that still needs a user keystroke.)

**Without `--no-push`:** also updates MEMORY.md and pushes to remote (full handoff).
**With `--no-push`:** skips MEMORY.md update + push. Use for mid-task compress where
  pushing is premature (e.g., not all steps done, no commit ready to push yet).

---

## `--resume` — in-window resume

Reads current.md (path resolved via git root walk) and outputs an orientation block
without switching windows. Use after `/compact` fires automatically or after `/clear`.

Output format:
```
Resuming [Task field]: [Status]
[Next Action field verbatim]
```

Then proceed with the next action — do NOT ask for confirmation.

---

## `--new-goal [name]` — goal switch

**Prefer `/goal` for in-window goal pursuit.** `/goal <condition>` keeps the session working
toward a new objective across turns and across auto-compactions (it wraps a session-scoped
Stop hook; a small fast model checks the condition each turn). It needs no window reset and no
`/clear`. Reach for it whenever the new goal can be pursued in the same window.

Use `--new-goal` only for a **true context-pollution reset** — when the accumulated history is
actively harmful to the next goal and you want a hard wipe. It writes current.md with
Status: COMPLETE (or BLOCKED), updates MEMORY.md, commits, pushes, then outputs `/clear` (the
only way to clear context — there is no programmatic trigger). After `/clear`, the
`SessionStart` re-inject hook (and the CLAUDE.md Session Resume rule) reload current.md.

---

## `--end` — true session end

Delegates to `session-wrap` unchanged. Use only for Condition 4 (true session end) where
a copy-paste prompt for a new window is actually needed.

---

## `--wait [cmd] [interval]`

Writes current.md with Status: IN_PROGRESS and WIP showing the waiting state. Outputs
a `/loop [interval] [cmd]` invocation for the user to start. The interval is wall-clock
polling cadence (e.g., `5m`, `10m`).

```
Output: /loop 5m /check-soak-status
```
