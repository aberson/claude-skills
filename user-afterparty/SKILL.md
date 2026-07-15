---
name: user-afterparty
description: "The milestone workspace-hygiene front door — invoke at a milestone or any time to run the whole cleanup sweep: 'milestone hygiene', 'workspace cleanup', 'run the sweep', 'afterparty', 'tidy up the workspace', 'sprint wrap'. A THIN orchestrator that CHAINS the existing hygiene skills via the Skill tool and owns no hygiene logic of its own: it runs the 2 autonomous ones (lesson-harvest --dry-run, context-slim) plus the tier-drift + meta-tool-prune checks unattended into ONE consolidated report, then WALKS the operator through the 3 conversational ones (memory-distill, test-prune, plan-trim) one at a time, yielding at each confirmation gate and never force-deciding. Report-first / apply-on-confirm — nothing mutates without a per-skill go-ahead. Promotes the monthly sprint-wrap ritual to an on-demand front door. NOT for wrapping a single session (use /session-wrap) or the sit-back-down verdict (use /user-wrap). Invoke as '/user-afterparty [--only <csv>] [--skip <csv>] [--dry-run] [--all-projects]'."
user-invocable: true
---

# user-afterparty

A THIN front door for the milestone-hygiene moment. The operator has just hit a
milestone — a phase shipped, a sprint closed, the month rolled over — and wants the
whole workspace-hygiene sweep run from one memorable place instead of remembering five
scattered skills. This skill composes existing contracts and owns ZERO hygiene logic of
its own; it only SEQUENCES the skills the workspace already has, via the Skill tool.

It promotes the monthly **sprint-wrap** ritual
([`../../../docs/seeds/seed_sprint_wrap.md`](../../../docs/seeds/seed_sprint_wrap.md) §B)
into an on-demand front door: afterparty is both what the `dev-sprint-wrap-monthly`
scheduled task fires AND what the operator runs at any milestone.

**The swept set** — each is an existing skill with its own owned contract; afterparty
never restates or reimplements it:

- **Autonomous (run unattended, in report mode, collected into ONE report):**
  - `tier-drift` — invoke [`/tier-escalate`](../tier-escalate/SKILL.md) then
    [`/tier-offload`](../tier-offload/SKILL.md) (both discovery-only; they write maps,
    never edit a skill), then diff the maps against live pins and report the deltas.
  - [`/lesson-harvest --dry-run`](../lesson-harvest/SKILL.md) — un-codified regressions
    from recent history. **`--dry-run` is mandatory here:** bare lesson-harvest opens a
    draft PR (mutating); afterparty runs it report-only.
  - [`/context-slim`](../context-slim/SKILL.md) — auto-loaded-context audit, bare
    (report-only by default).
  - `meta-tool-prune` — list the usage-logging meta-tools due for their periodic prune
    (CLAUDE.md working rules); report-first, each prune confirmed later.
- **Conversational (WALKED one at a time, yielding at each skill's own gate):**
  - [`/memory-distill`](../memory-distill/SKILL.md) — post-mortem of recent feedback
    memories (**formerly `/review-memories`** — the swept set uses the new name).
  - [`/test-prune`](../test-prune/SKILL.md) — redundant/mock-theater test triage.
  - [`/plan-trim`](../plan-trim/SKILL.md) — cut/fold plan cruft.

It additionally owns two orphans with no other home — **orphan-owner duties** (workspace
stray / orphan-worktree cleanup) and the **current.md rollup commit/archive seam** — each
filled by a later build step (Steps 3-4 below).

**Pinned posture: SEQUENCE, DON'T REIMPLEMENT.** Per the CLAUDE.md meta-tooling rule
(cheapest artifact that removes a named friction), afterparty is glue. Any hygiene logic
authored here that a swept skill already owns — a lesson-detection heuristic, a
test-triage rule, a plan-cut policy, a context-audit pass — is a DEFECT. afterparty
invokes, collects, sequences, and reports; it decides nothing the chained skills decide.

**Report-first / apply-on-confirm.** Nothing mutates without the operator's per-skill
go-ahead. The only confirmation gates in a run are the 3 conversational skills' OWN gates;
afterparty adds no bare `(y/n)` gate of its own (autonomous-by-default).

---

## When to use / when NOT to use

**Use** at a milestone or any time the workspace wants a tidy: "run the sweep", "milestone
hygiene", "workspace cleanup", "afterparty", "sprint wrap", "tidy up the workspace". Also
the target of the monthly `dev-sprint-wrap-monthly` scheduled task.

**Do NOT use:**

- **Wrapping a single session / a transition moment** (task boundary, heavy context, end
  of day) → bare [`/session-wrap`](../session-wrap/SKILL.md). afterparty is workspace
  hygiene across projects, not this-session state.
- **The sit-back-down verdict** ("keep going or wrap up?") → [`/user-wrap`](../user-wrap/SKILL.md).
- **One hygiene skill in isolation** → invoke that skill directly. afterparty earns its
  overhead only when you want the whole sweep.

---

## The swept set (interface map)

Verified invocation facts for the 5 skills afterparty chains — state them accurately so a
fresh-context model chains them correctly. Each skill owns its own behavior; this table is
afterparty's read of that contract, not a second copy of it.

| Skill | Invocation | Bare default | Interactivity | Scope | Output |
|---|---|---|---|---|---|
| `lesson-harvest` | `/lesson-harvest [--dry-run] [--since <sha>]` | MUTATE (opens draft PR); `--dry-run` = report-only | **autonomous** | workspace | draft PR `memory/harvest-<date>` + `.claude/task-state/.last-harvest-sha` |
| `context-slim` | `/context-slim [--project <p>] [--apply]` | **REPORT** only | **autonomous** | per-project | stdout report; `--apply` edits-in-tree |
| `memory-distill` | `/memory-distill` | mutate-on-approval, per round | **conversational** | per-project memory | edits `feedback_*.md` + `MEMORY.md` |
| `test-prune` | `/test-prune` | REPORT until confirm | **conversational** | per-project | triage table → edits-in-tree on confirm |
| `plan-trim` | `/plan-trim` | investigate → confirm → mutate | **conversational** | per-project | plan-doc edits + commit |

The two non-skill workspace items — `tier-drift` (runs `/tier-escalate` + `/tier-offload`,
both discovery-only) and `meta-tool-prune` (a list-what's-due pass) — are report-only and
carry no gate.

---

## Default scope and flags

**Default scope** (no flags):

- **Workspace-wide items — ALWAYS run, once:** `tier-drift`, `lesson-harvest`,
  `meta-tool-prune`, `orphan-cleanup` (Step 3), `rollup-commit` (Step 4).
- **Per-project items — the CURRENT project only:** `context-slim`, `memory-distill`,
  `test-prune`, `plan-trim`. **"Current project" = the nearest ancestor directory of cwd
  that contains a CLAUDE.md** — the same resolution `context-slim` itself already uses —
  NOT the cwd's git root. Monorepo sub-projects with no nested `.git` (`switchboard`,
  `dev-observatory`, `songs`) would resolve to the whole `dev/` workspace under a
  git-root definition; the CLAUDE.md-ancestor walk correctly isolates the sub-project.

**Flags:**

- **`--only <csv>`** — run only the named swept items (e.g. `--only lesson-harvest,context-slim`).
- **`--skip <csv>`** — run everything EXCEPT the named items (e.g. `--skip test-prune`).
  Item names are the swept-set identifiers: `tier-drift`, `lesson-harvest`, `context-slim`,
  `meta-tool-prune`, `memory-distill`, `test-prune`, `plan-trim`, `orphan-cleanup`,
  `rollup-commit`. `--only` and `--skip` are mutually exclusive; if both are given, `--only`
  wins and a one-line note says so.
- **`--dry-run`** — applies NOTHING anywhere. The autonomous items already only report;
  the conversational items are teed up (afterparty lists what each WOULD review) but are
  never invoked into their apply/confirm phase; orphan-cleanup lists but never deletes; the
  rollup seam runs report-only (Step 4's detection + a `Get-DerivedRollup` preview + a
  listing of archive candidates — no regen-write, no archive move, no force-add/commit).
  Every autonomous report is still produced.
- **`--all-projects`** — fans the per-project items (`context-slim`, `memory-distill`,
  `test-prune`, `plan-trim`) across the MEMORY.md active-project list instead of the
  current project only. Workspace-wide items still run once. Each item's targeting
  mechanism (there is no shared switch — use each skill's own contract; invocation detail
  lives in Step 1 / Step 2):
  - `context-slim` owns a `--project <name-or-path>` flag — invoke `/context-slim
    --project <p>` once per active project. NEVER bare in this loop: a bare call always
    re-audits the ambient cwd project regardless of loop position, so N bare calls
    silently produce N duplicate reports for the same project instead of N distinct ones.
  - `memory-distill` / `test-prune` / `plan-trim` own NO project flag (verified against
    each SKILL.md) — they are cwd-scoped only. Target them by setting cwd to each
    project's root (the nearest ancestor with a CLAUDE.md, per the "current project"
    definition above) before invoking each via the Skill tool, once per active project.

---

## Steps

### Step 0 — resolve scope + flags, announce the plan

Resolve the swept set from the flags (default scope above; apply `--only`/`--skip`;
mutually-exclusive note if both). Resolve the target project(s): the current project (see
"Default scope and flags" above — nearest ancestor of cwd with a CLAUDE.md, NOT the git
root), or — under `--all-projects` — the active-project list from
your workspace memory index (`MEMORY.md`). Note the mode
(apply-on-confirm, or `--dry-run` = nothing mutates).

Announce ONE plan line before acting, so a wrong scope is visible immediately:

    afterparty: <N> items | scope: <current project | M active projects> | mode: <apply-on-confirm | dry-run> | autonomous: <list> | walk: <list>

### Step 1 — autonomous sweep (report mode), one consolidated report

For each selected autonomous item, invoke it via the Skill tool and capture its output.
Run these unattended; there are NO gates here.

- **`tier-drift`** — invoke `/tier-escalate` then `/tier-offload` via the Skill tool
  (both write their maps to their own out-dirs; neither edits a skill). Diff the fresh
  maps against the live pins and report the deltas (new/changed skills since the last
  cycle). Report-only — APPLYING any pin delta is a separate confirmed follow-up, never
  automatic.
- **`lesson-harvest`** — invoke `/lesson-harvest --dry-run` via the Skill tool. The
  `--dry-run` is load-bearing: it prints the report + the draft-PR body and creates
  nothing. Capture the candidate count and the report pointer.
- **`context-slim`** — invoke via the Skill tool: bare for the current project, or —
  under `--all-projects` — once per active project with `/context-slim --project <p>`
  (never bare inside the loop; see the `--all-projects` targeting mechanism above).
  Report-only. Capture the top-priority stub/extract/prune recommendations per project.
- **`meta-tool-prune`** — list the usage-logging meta-tools due for their periodic prune
  (CLAUDE.md working rules). Report which are due; each actual prune is confirmed later,
  never auto-run.

Collect all of the above into ONE consolidated hygiene report (shape below). Per
[`../../rules/subagent-economy.md`](../../rules/subagent-economy.md): keep each captured
result to its load-bearing verdict + counts + a pointer to the skill's full output — do
not inline the full dumps.

### Step 2 — conversational walk (one skill at a time)

Walk the selected conversational items in order (`memory-distill` → `test-prune` →
`plan-trim`), ONE AT A TIME:

1. Invoke the skill via the Skill tool.
2. YIELD to the operator at that skill's own confirmation gate. Do NOT answer for them, do
   NOT force-decide, do NOT auto-confirm — the whole point of the autonomous/conversational
   split is that these three need the operator's judgment.
3. Resume to the next item only after the operator finishes the current one.

Never batch them and never collapse two gates into one. Under `--all-projects`, walk each
per-project item across each active project from the MEMORY.md list: none of the three
own a project flag (see the `--all-projects` targeting mechanism above), so set cwd to
that project's root (nearest ancestor with a CLAUDE.md) BEFORE invoking the skill via the
Skill tool, then move cwd to the next project before its turn — still one skill, one
project, one gate at a time. Under `--dry-run`, tee each up (state what it WOULD review)
but do NOT invoke it into its apply phase.

### Step 3 — orphan-owner duties (workspace stray / orphan-worktree cleanup)

Workspace-wide, report-first. Registry-checked detection of orphaned `worktree_*` dirs
(rule owned by [`../../references/worktree-hygiene.md`](../../references/worktree-hygiene.md)
§4) plus task-state stray triage; list for confirmation, never auto-`rm`. Note: the
command blocks in this step are POSIX/bash (Git Bash / the Bash tool) — `ls -d`,
`2>/dev/null`, `du -sh`, `cat <wt>/.git`, and `git check-ignore` are bash idioms, run them
there even though the operator's default shell is PowerShell.

**Duty 1 — orphaned `worktree_*` dirs (report-first, delete-on-confirm-only).** The
AUTHORITATIVE orphan signal is a per-candidate, format-independent GITDIR-METADATA check —
NOT a string-diff of `git worktree list` against an `ls` listing. The two print different
path formats (`git worktree list` prints absolute forward-slash paths, e.g.
`<abs>/worktree_foo`; `ls -d ../worktree_* worktree_*` prints the parent-level
ones as relative paths, e.g. `../worktree_foo`), so comparing them as strings never
matches and will over-flag live worktrees as orphans. Treat `git worktree list` as
INFORMATIONAL context (git's own live registry, NOT the observatory `registry.toml` — do
not consult registry.toml here) alongside the on-disk candidates, never as the pass/fail
test itself. `/build-step` creates these one level ABOVE the dev/ root (`../worktree_*`,
i.e. `<workspace-parent>/worktree_*`); §4 also sees them at the dev/ root (`dev/worktree_*`).
Scan BOTH locations:

    git worktree list                              # git's own registry -- context only
    ls -d ../worktree_* worktree_* 2>/dev/null     # on-disk candidates, BOTH locations
    git worktree prune -n -v                       # DRY-RUN listing; mutates nothing

`git worktree prune` reconciles the OPPOSITE direction from what this duty targets: it
removes registry entries whose on-disk dir is GONE. The husk case this duty targets is the
reverse (on-disk dir PRESENT, registry entry already gone), so prune typically has nothing
to act on for these candidates — it tidies dangling registry metadata, it does not remove
an on-disk husk. `rm -rf` (after corroboration below) is what reclaims a husk. A REAL
(non-dry-run) `git worktree prune` only ever runs in the post-confirmation removal phase
below, never during this detection pass and never under `--dry-run`.

For EVERY on-disk `worktree_*` candidate, run the authoritative gitdir check and measure
the reclaim (they cost gigabytes — a 512 MB `node_modules` husk is cited in §4):

    cat <wt>/.git 2>/dev/null                        # gitdir line: <repo>/.git/worktrees/<name>
    ls -d <repo>/.git/worktrees/<name> 2>/dev/null   # absent output: gitdir metadata is gone
    du -sh <wt> 2>/dev/null                          # reclaimable size

A candidate is a confirmed ORPHAN HUSK iff it has NO `.git` file, OR its `.git` gitdir
pointer targets a `<repo>/.git/worktrees/<name>` directory that no longer exists. LIST
every orphan candidate as one row — path, size, reason (gitdir file absent, or gitdir
target directory gone). NEVER auto-`rm`; under `--dry-run` stop here (list only, touch
nothing).

**Hard safety precondition — re-check per item, immediately before touching `<path>`.**
Re-run both checks fresh, for the SPECIFIC `<path>` about to be acted on, right before
acting on it:

- (a) is `<path>` ABSENT from `git worktree list`?
- (b) is its gitdir metadata `<repo>/.git/worktrees/<name>` absent (or the `.git` file
  itself absent)?

BOTH must hold for `<path>` to be a confirmed husk. If (a) does NOT hold — `<path>` still
appears in `git worktree list` — it is NOT an orphan husk; it is at most a still-tracked,
locked tree (the §4 failure mode where a prior `git worktree remove` half-failed, e.g. a
file lock). NEVER run `rm -rf` on it. If neither reading is clean, STOP — do not remove
anything for this `<path>`.

ONLY on explicit, per-item operator confirmation, run the ONE block below that matches
`<path>`'s corroborated class from the precondition above — never copy-paste both blocks
together against the same candidate:

Block A — still-tracked, locked tree (precondition check (a) failed: `git worktree list`
still prints `<path>`). Reconcile through git itself, from the dev/ root (removal fails if
cwd is inside the worktree):

    cd <workspace-root>
    git worktree remove <path> --force
    git worktree prune                             # REAL prune: reconcile the registry after

Block B — confirmed true husk (precondition BOTH (a) and (b) held for this `<path>`; git
has no entry left, so `git worktree remove` here would be a no-op). Reclaim directly, as
its own separately-confirmed step, only after the husk corroboration above passed for THIS
`<path>`:

    cd <workspace-root>
    rm -rf <path>

**Duty 2 — task-state stray triage (gitignore-vs-keep, report-first).** Per the shipped
current.md write-race fix, `.claude/task-state/current.md`, `sessions/`, and intake are
GITIGNORED and `current.md` is a DERIVED rollup (never hand-edited). Two stray classes
accumulate: leftover `.plan-expedite-state.*` files at the dev/ root (~14 old
completed/stale ones) and stale `sessions/*.md` from long-dead sessions. List them, and
confirm each is gitignored before proposing it (a match means removal loses no tracked
content):

    ls -la .plan-expedite-state.* 2>/dev/null
    ls -la .claude/task-state/sessions/*.md 2>/dev/null
    git check-ignore -v <path>                       # a match: gitignored, safe-to-archive class
    grep -l '^\*\*Status:\*\* COMPLETE' .claude/task-state/sessions/*.md 2>/dev/null   # COMPLETE-marked sessions

Classify each stray with a SUGGESTED verdict — never blind-delete. Delete vocabulary in this
duty applies ONLY to `.plan-expedite-state.*`; no path through `sessions/*.md` here is a
delete candidate:

- `.plan-expedite-state.*` — the filename encodes state: `.completed-*` / `.stale-*`
  markers are archival candidates (delete-eligible on confirmation); a name with no such
  marker, or one modified within the last few hours, is keep/inspect.
- `sessions/*.md` — respect the per-session model: a file written in the last few hours may
  be a LIVE concurrent window, so do NOT propose ANYTHING for another session's ACTIVE
  state. For files past the 8h staleness window, gate on `**Status:**`:
  - `COMPLETE` — ARCHIVE-ONLY, never delete. COMPLETE sessions are archived by the Step 4
    rollup seam (Duty 2), not deleted here; classify it `deferred-to-step-4`.
  - anything else (a dead, non-COMPLETE husk) — `archive-candidate`, still never a blind
    delete.

Present the triage list — one row per stray: path, suggested verdict (delete-candidate |
archive-candidate | deferred-to-step-4 | keep/active), and why. Under `--dry-run`, stop
here. `.plan-expedite-state.*` strays may be deleted on explicit operator confirmation;
`sessions/*.md` files are never deleted in this step — archive-candidate and
deferred-to-step-4 rows route to Step 4 Duty 2's archive move. Both duties fold into the
Step 5 `Orphan cleanup:` line; nothing is removed in this step without a per-item go-ahead.

### Step 4 — current.md rollup commit/archive seam

Workspace-wide. The low-concurrency commit/archive of the DERIVED `current.md` rollup
(the seam the current-md write-race fix left to afterparty). Degrade gracefully — skip
with a one-line note — when the `sessions/` system is absent, so afterparty is usable
before the race fix ships.

**Detection + graceful degrade (run first).** The active path only makes sense once the
per-session system exists. SKIP the whole step with a one-line note when EITHER the
`sessions/` dir is absent OR the `Write-DerivedRollup` helper is missing from the derive
lib (a pre-race-fix repo, so afterparty stays usable before the fix ships):

    Test-Path .claude/task-state/sessions -PathType Container
    Select-String -Quiet -Path .claude/hooks/lib/task-state-derive.ps1 -Pattern '^function Write-DerivedRollup'

If EITHER returns `$false`, report `rollup-commit: sessions/ system not present
(pre-race-fix repo) -- skipped` and move on. (In THIS repo both are present, so the active
path below runs.) Note the two blocks in this step are PowerShell — this seam is genuinely
PowerShell work (the operator's default shell), unlike Step 3's bash blocks.

**Duty 1 — regenerate the derived rollup (low-concurrency refresh).** afterparty IS the
low-concurrency moment the race fix reserved for the rollup (per the design doc §6.4: the
derived rollup is "the only candidate for commit, and only at a low-concurrency moment").
Resolve the git root once and reuse it for the rest of this step (same idiom as the sibling
hooks `session-resume.ps1` / `pre-compact.ps1`), then dot-source the derive lib and call the
helper:

    $root = (git rev-parse --show-toplevel 2>$null).Trim()
    . .claude/hooks/lib/task-state-derive.ps1
    Write-DerivedRollup -GitRoot $root

`Write-DerivedRollup` rewrites `.claude/task-state/current.md` atomically (temp-sibling +
move) from the `sessions/*.md` files and is idempotent — a lost/raced write reproduces on
the next call. **Under `--dry-run`, do NOT call it** — the regen is itself a local write and
dry-run must touch nothing. For a read-only preview under `--dry-run`, `Get-DerivedRollup
-GitRoot $root` (the pure function the writer wraps) returns the same text WITHOUT writing
to disk. If either helper returns `$null` (zero parseable `sessions/*.md` files — e.g. all
already archived, or all fail the required-field check), report "no sessions to roll up" and
skip Duties 2-3 for this run; `current.md` is left untouched.

**Duty 2 — archive completed session files (design doc §6.2 step 5, archive-on-completion).**
Reuse the Step 3 Duty 2 per-session safety discipline verbatim: a session file written
inside the 8h staleness window may be a LIVE concurrent window — NEVER archive an active
session. An archive candidate is a `sessions/<id>.md` whose `**Status:**` is the completion
marker `COMPLETE` AND whose `**Last written:**` is well past the 8h window. This is the
counterpart Step 3 Duty 2 defers COMPLETE sessions to (Step 3 lists + defers, Step 4
archives). Reuse the parser already dot-sourced in Duty 1 — do NOT re-implement
field/timestamp parsing (one source of truth) — and reuse `$root` from Duty 1:

    $cutoff = (Get-Date).ToUniversalTime().AddHours(-8)
    Get-SessionStates $root | Where-Object { $_.Status -eq 'COMPLETE' -and $_.LastWrittenUtc -lt $cutoff } | Select-Object Path, Status, LastWritten

`Get-SessionStates` is non-recursive, so it already excludes `sessions/archive/`. LIST the
candidates — one row per file: id, status, last-written, age. On explicit per-item operator
confirmation (never under `--dry-run`), create the archive dir if missing and move each
confirmed file in:

    New-Item -ItemType Directory -Force -Path .claude/task-state/sessions/archive | Out-Null
    Move-Item -LiteralPath <path> -Destination .claude/task-state/sessions/archive/

Because `sessions/` (and thus `sessions/archive/`) is GITIGNORED, archiving is a LOCAL tidy —
it moves a file out of the derive set (the next regen drops it from the rollup), not a git
action. Under `--dry-run`, list only and move nothing.

**Duty 3 — milestone provenance commit (OPTIONAL, confirm-gated).** Routine per-session
state stays UNCOMMITTED by design — that is the whole point of the write-race fix (design
doc §9 Q2), and the load-bearing durable actions of this step are Duties 1-2, both purely
LOCAL. The derived rollup is regenerable, so it needs no per-wrap commit. But a milestone is
a natural provenance anchor for external readers (dev-observatory, git history), so
afterparty MAY — on explicit operator confirmation only — commit a snapshot of the rollup.

Duty 1's regen ran BEFORE Duty 2 archived sessions, so the current.md it wrote can still
list a session Duty 2 just archived as active. Re-regenerate before staging, so the snapshot
reflects the post-archive session set — only when the operator has opted into the snapshot,
and never under `--dry-run`:

    Write-DerivedRollup -GitRoot $root

`current.md` is GITIGNORED, so a naive `git add .claude/task-state/current.md` is REFUSED —
git prints an ignored-path hint ("Use -f") and exits non-zero; `git add -f` forces past the
ignore ON PURPOSE. Scope the commit itself to `current.md` (pathspec), so any other staged
work already in the index is left staged, uncommitted:

    git add -f .claude/task-state/current.md
    git commit -m "chore(task-state): milestone rollup provenance snapshot" -- .claude/task-state/current.md

This is optional and never automatic — skip it unless the operator asks for the snapshot. If
the regenerated current.md is byte-identical to the last committed snapshot, `git add -f`
stages no diff and `git commit` fails "nothing to commit" (non-zero) — this is expected and
benign; report "rollup unchanged since last snapshot; no commit" rather than treating the
non-zero exit as an error. Under `--dry-run`, commit nothing (no regen, no archive move, no
force-add).

Fold the outcome of all three duties into the Step 5 `Rollup commit:` line (e.g.
`rollup regenerated; N session(s) archived; provenance commit <sha | declined>`).

### Step 5 — the consolidated hygiene report

Present the consolidated report as the centerpiece of the output:

    ## afterparty sweep — <date>
    scope: <current project | M active projects> | mode: <apply-on-confirm | dry-run>

    Autonomous (report):
    - tier-drift:      <delta summary + map pointer>
    - lesson-harvest:  <N candidates (dry-run, nothing created) + report pointer>
    - context-slim:    <top recommendations + report pointer>
    - meta-tool-prune: <tools due, or none>

    Conversational (walked):
    - memory-distill:  <what the operator confirmed / deferred>
    - test-prune:      <same>
    - plan-trim:       <same>

    Orphan cleanup:    <one-line outcome (Step 3)>
    Rollup commit:     <one-line outcome (Step 4)>

    Nothing mutated without a per-skill go-ahead.

Keep it terse and pointer-first — full skill outputs live behind their pointers, not
re-quoted inline.

---

## Maintenance

afterparty owns NO hygiene logic — every swept item's behavior is owned by that item's own
SKILL.md (or, for `tier-drift`/`meta-tool-prune`, by the tier-scan skills + CLAUDE.md
working rules). When a chained skill's **invocation or flags** change (e.g. a rename like
`review-memories` → `memory-distill`, or a new report-only flag), update the swept-set
interface map above and the Step 1/2 invocations in the same diff — never restate the
chained skill's internal contract here.

Evals are a deferred follow-up: run `/skill-eval-setup user-afterparty` to scaffold an
`evals/` suite once the flow has stabilized through a couple of real sweeps (the
"see it work, then react" iteration). Until then, correctness is behavioral — verified by
an end-to-end observation run (plan Step 5), not a unit suite.
