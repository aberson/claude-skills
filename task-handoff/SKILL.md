---
name: task-handoff
description: "Checkpoint library — orchestrators call this (build-phase, build-step, plan-expedite, user-draft); operators usually want /session-wrap. Modes: --loop [--no-commit] (write current.md), --next-task [label] (durable task-boundary save), --resume (read current.md + orient), --end (delegates to /session-wrap)."
user-invocable: true
---

# task-handoff

Checkpoint library for `current.md` writes and reads. Its callers are orchestrating
skills — `build-phase`, `build-step`, `plan-expedite`, `user-draft` — that need a durable
checkpoint or an in-window resume. Operators wanting a session transition should use
`/session-wrap`. Bare `/task-handoff` (no flag) defaults to `--resume`.

**current.md contract:** file format, field definitions, overwrite-vs-append rules, path
resolution, staleness, and lifecycle are owned by
`.claude/references/task-state-schema.md` (workspace reference, not published in this mirror) — follow
it for every read and write. Safety-critical minimum: resolve the path via
`git rev-parse --show-toplevel`, never cwd-relative (worktree writes are deleted on cleanup).

None of these modes emits `/compact` or `/clear` — auto-compaction plus the `SessionStart`
re-inject hook handle context in-window (CLAUDE.md § Session wrap & commit discipline).

---

## `--loop` — checkpoint write

**Cost:** ~5 seconds, no user interaction. Output one line: `"Checkpoint written."`

Read-merge-write `current.md` — read the existing file first, then apply the schema doc's
per-field append-vs-overwrite rules (it owns that split; do not re-derive it here). Then
commit: `chore: task-state checkpoint [task] [status]`.

Callers invoke it after each meaningful action — tests pass, a hypothesis is ruled out,
before a new iteration. It should feel nearly zero-cost.

**`--loop --no-commit`** — same write, NO git commit. Required inside `build-phase`: its
Step 2e checkpoint commit picks up `current.md`, so a separate commit here would double-commit
and break 2d/2e race detection (which compares HEAD against origin before committing).

---

## `--next-task [label]` — task-boundary save

**Cost:** ~30 seconds. Durable boundary write when switching tasks within the same goal
(e.g. plan-expedite → build-phase): the same read-merge-write as `--loop` — the finished
task's entries land in Completed (append); WIP, Next Action, and Status are overwritten to
point at the next task (`[label]`) — plus a MEMORY.md update, commit, and push.

Then **keep working in-window**. No manual `/compact` is needed to cross a task boundary.
If a *deliberate* focused reset is genuinely wanted (not the default), emit a
`/compact [focus]` line for the user to type — `/compact` has no programmatic trigger.

---

## `--resume` — in-window orient

Reads `current.md` (path per the schema doc) plus git state and outputs an orientation
block — no window switch. Use after a compaction or `/clear`.

```
Resuming [Task field]: [Status]
[Next Action field verbatim]
```

Then proceed with the next action — do NOT ask for confirmation.

---

## `--end` — true session end

Delegates to `/session-wrap`, which triages.
