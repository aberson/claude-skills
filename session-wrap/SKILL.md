---
name: session-wrap
description: "The session-transition front door. Bare invocation TRIAGES the session — context utilization, task-boundary state from current.md, git state, armed /goal — announces one route, then ACTS: continue (checkpoint + one line), clear-next (durable state to disk, git verb, emit /clear), or end-window (full wrap, handoff rendered to handoff-prompt.md, Pick-up-here block). Use at any transition moment: task boundary, heavy context, or end of day. /task-handoff is the checkpoint library this skill calls."
user-invocable: true
---

# session-wrap

One decision-making front door for session transitions. Invoked bare, it TRIAGES the
session against mechanical signals, announces the chosen route in one line, then ACTS.
No mid-run (y/n) gates — bare invocation is the safest mode. The single ask-first
exception is a detected parallel-session anomaly before the git verb; the detection
pre-flight is the Git-verb router's Step A (section below).

Division of labor: `/task-handoff` is the checkpoint *library* this skill calls; the
`current.md` file contract is owned by
`.claude/references/task-state-schema.md` (workspace reference, not published in this mirror)
(cite it, never restate it). Phase-shipping territory (README/plan updates, issue
closing, push-everything) belongs to `/repo-update` — the git-verb router delegates
there; this skill never duplicates it.

---

## Threshold constants (operator-tunable)

Defaults from community threshold doctrine (proactive boundary at ~60% utilization,
~120k-token quality "dumb zone", 95% auto-compact "too late"). The internal
degradation floor is unmeasured — these are defaults, not findings; when the floor
gets measured, one edit here moves them.

| Constant | Value | Raw-token proxy | Meaning |
|---|---|---|---|
| `CONTINUE_MAX_UTIL` | 60% | <=120k tokens | Below this and mid-task -> `continue` |
| `CLEARNEXT_UTIL` | 60% | >120k tokens | At or near a task boundary -> `clear-next` |
| `CLEARNEXT_FORCE_UTIL` | 75% | >150k tokens | Take the next boundary aggressively, regardless of task state |
| (end-window) | — | — | No threshold. Operator intent only ("done", "end of day", explicit `--end`), or no agent-completable next action exists |

Raw tokens are not a percentage: a percentage needs a model-aware window size, and
extended (>200k) windows exist on this machine. When the window size is unknown, apply
the raw-token proxies directly and, if a percentage is reported at all, SAY the
denominator is assumed — e.g. `162,340 tokens (~78% assuming a 200k window)`. Never
present an assumed percentage as a measurement.

---

## Step 0 — triage: collect, score, announce

**Read `current.md` first.** Before deriving any next action or route, read
`<git-root>/.claude/task-state/current.md` (path resolution per the schema doc; absent
file = no recorded task — it gets created from the template on the first route write).
`current.md` plus git is the state; conversation prose is not. Every next action this
skill writes or renders derives from `current.md`, never in parallel from prose.

Collect four signals:

**(a) Context utilization.** Chosen signal (decision doc:
`docs/investigations/context-signal-spike.md`):
the `message.usage` sum (`input_tokens + cache_creation_input_tokens +
cache_read_input_tokens`) of the LAST top-level main-chain assistant entry in the
session transcript JSONL. Run the reference implementation rather than reimplementing
the guarded recipe: `docs/investigations/high-context-usage-tools/read-context-signal.ps1`.
Skill-mode transcript resolution: glob `~/.claude/projects/<project-slug>/*.jsonl` and
require EXACTLY ONE file modified within the last ~2 minutes — zero or more than one
candidate is ambiguous and means signal absent (sibling-session risk; never blindly
take the newest). When the signal is absent for ANY reason, print exactly this line
(ASCII hyphen — this exact wording is the contract) and triage on (b)-(d) alone:

    context signal unavailable - boundary-only triage

Never guess, estimate, or fabricate a token count or percentage — a fabricated number
is indistinguishable from a real one and steers the route wrong (measurement-validity
rule).

**(b) Task-boundary state.** From the `current.md` read above: Status + Next Action.
Plus the active plan's step `**Status:**` lines (plan located per CLAUDE.md § Plan
location — `plan.md`/`master_plan.md` at the project root or under
`plans/`/`docs/`/`documentation/`; descriptor-contract §4), and whether the
just-finished turn completed a step or phase. At/near a boundary = Status COMPLETE, a step just flipped
DONE, or the turn closed a task. Mid-task = everything else.

**(c) Git state.** Per touched repo — a multi-project session (2+ distinct project
dirs edited, or a project repo plus `dev/` workspace-root files) checks EACH repo:
branch, short SHA, dirty-file count, ahead-of-origin count.

**(d) Armed `/goal`.** An unmet agent-completable goal biases `continue`.

**Score — first match wins:**

1. Operator intent ("done", "end of day", explicit `--end`), or no agent-completable
   next action exists -> `end-window`.
2. Utilization >= `CLEARNEXT_FORCE_UTIL` -> `clear-next` now (finish only the
   in-flight edit, not the task).
3. Utilization >= `CLEARNEXT_UTIL` and at/near a boundary -> `clear-next`.
4. Everything else — below `CONTINUE_MAX_UTIL` and mid-task, signal absent with no
   operator intent, armed unmet `/goal`, or any uncertainty -> `continue`.
   `continue` is the bias because it is the cheapest wrong answer.

**Announce, then act.** Print exactly ONE triage line BEFORE acting, so a wrong route
is visible and correctable immediately:

    triage: <route> | context: <N tokens (~X% assuming 200k)> | boundary: <mid-task | at boundary (<what>)> | git: <n dirty, m ahead[, per-repo]> | goal: <armed | none>

(substitute the fail-loud contract line for the context segment when the signal is
absent).

---

## Route: `continue`

Invoke `task-handoff --loop` via the Skill tool. Screen output is ONE composed line
total — the library's own `Checkpoint written.` line is subsumed into it, never
printed separately:

    Checkpoint written — continuing (<one-clause reason from the triage>).

Nothing else — no summary, no rendered prompt, no wall of text.

## Route: `clear-next`

Durable state to disk, then the git verb, then hand the operator `/clear`. Execute in
this exact order — `current.md` first, render second, screen last:

1. **Write `current.md`** — invoke `task-handoff --loop --no-commit` via the Skill
   tool (read-merge-write per the schema doc, which owns the per-field
   append-vs-overwrite rules). Next Action = the exact command or skill invocation.
   **No-regress clause:** the read-merge-write must never regress a Next Action that
   is already the exact next command from a boundary write made earlier this same
   turn/step (e.g. plan-expedite's `--next-task` write) — preserve it verbatim; the
   render carries Next Action verbatim (rendering contract item 4), so an overwrite
   here would silently drop it.
   The route's own git verb (step 5) carries the commit — same no-double-commit
   rationale as build-phase Step 2e. Do NOT use `--next-task` here: it commits and
   pushes itself, doubling up with the route's git verb.
2. **Decisions log + salvage sweep** (section below) — bounded; results land in
   `current.md` (§ Parked / Critical Gotchas) and the render, not on screen.
3. **Cheap memory subset only:** correct the project's MEMORY.md status pointer line
   if this session made it wrong, and park unfiled TODOs; the full
   memory/lessons/friction passes are end-window-only.
4. **Render `handoff-prompt.md`** from `current.md` + the decisions log (rendering
   contract below).
5. **Execute the git verb** — run the Git-verb router (section below): anomaly
   pre-flight, commit-owner decision, additive recommendation, one-line report.
   The router's base commit is the carrying commit step 1 deferred; when it
   delegates, `/repo-update`'s commit sweeps `current.md` in.
6. **Screen: the Pick-up-here block** (contract below), exact next command =
   `/clear`. The next window resumes via the SessionStart hook re-injecting
   `current.md`.

## Route: `end-window`

Everything in `clear-next`, same order — including step 1's
`task-handoff --loop --no-commit` write — with these passes inserted after step 3
(before the render, so their outcomes are renderable):

- **Full memory pass — read-then-report (invariants 1 and 4).** Read MEMORY.md
  (`~\.claude\projects\<workspace>\memory\MEMORY.md`) fully
  (if the first Read reports a partial load, continue with offset reads until the
  whole file is covered — a partial read cannot honestly claim "Read MEMORY.md"). For
  every topic touched this session, state `existing entry for <topic> was
  current|stale` or `no existing entry for <topic>` BEFORE describing any change.
  Update stale entries in place; never append a duplicate. Multi-project sessions
  check each touched project's heading. If MEMORY.md exceeds 200 lines or any line
  exceeds 200 chars, add a `MEMORY.md over budget (X lines)` invariant flag to the
  digest — do not auto-trim.
- **Lessons-learned sync.** Any feedback memory created or edited this session syncs
  both layers: long form in `docs/lessons-learned.md` (matching `### Title` heading +
  ToC entry), thin pointer in the `feedback_*.md`, index line in MEMORY.md. Never
  leave the long form duplicated in both layers. Project-scoped memories do not sync
  there.
- **Friction review.** Scan the session for patterns that would slow future sessions:
  failed commands that needed rework, wrong assumptions, missing context, clunky
  workflows. Actionable friction becomes a feedback memory (then syncs per the bullet
  above). Skip one-off flukes entirely and never record retry counts (invariant 6). A
  clean session reports nothing.
- **Docs staleness.** If plan.md or a session doc no longer reflects what shipped,
  update it now or name it in the digest — never silently leave a stale doc. Cheap
  side-check: if `docs/friction-catalog.md` exists and any `feedback_*.md` is newer
  than its indexed date, add a `friction catalog stale` digest flag (do not
  regenerate it).

The Pick-up-here block's exact next command becomes the fresh-window opener instead
of `/clear` (contract below) — the SessionStart hook does not fire on plain startup,
so the opener must carry the pointer. With opt-in `--spawn` (section below), the deep
link then auto-opens the next window pre-filled with that opener; the block on screen
stays the baseline.

---

## Git-verb router (clear-next + end-window, step 5)

The single owner of the route's git verb. Four steps, in order: A anomaly
pre-flight, B commit owner, C additive recommendation, D report. Multi-project
sessions run Steps A-C independently PER TOUCHED REPO — mixed outcomes across
repos are legal — and Step D joins the segments.

**Step A — anomaly pre-flight (before ANY verb, delegation included).**
CLAUDE.md § Parallel session safety and § Session wrap & commit discipline stay
senior to execute-by-default. Run all four checks BEFORE Step B
(PowerShell-first). Scope: check 1 runs at the workspace root — a trigger
there downgrades ALL repos; checks 2-4 run per touched repo — a trigger
downgrades that repo only.

On a trigger, the downgraded scope's Steps B/C are WITHHELD — the route is
not: the render and the Step D report still run, the pending repo's segment
reads `ask-first pending`, and route step 6 does NOT emit `/clear` while any
segment is pending. The Pick-up-here block's exact next command becomes the
ask response — approve or adjust the presented plan — never `/clear` past an
open gate (never co-locate a gate and an action; rendering-contract item 4).
Presentation: base-action path = the scoped add list + the commit message;
delegate path = the intended `/repo-update` invocation + the trigger evidence.
This ask is the single sanctioned (y/n) gate in this skill. The checks:

    # 1. Foreign state file at the workspace root
    Get-ChildItem -Force <git-root>\.plan-expedite-state.* | Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-24) }
    # 2. Worktrees beyond the main checkout, then two activity probes per hit
    git worktree list
    git log -1 --format=%cr <worktree-branch>
    Get-Item <git-root>\.git\worktrees\*\index -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-24) }
    # 3. Cross-repo/foreign edits
    git status --porcelain
    # 4. Foreign commits: reachable from other refs, not from this HEAD
    git log --all --not HEAD --since='1 hour ago' --oneline

Trigger tests, one per check:

1. **Foreign state file** — a hit whose plan path does not match this
   session's active plan (from `current.md`'s Task / plan reference).
   Plan-mismatch or unknown = foreign = trigger.
2. **ACTIVE foreign worktree** — a worktree beyond the main checkout whose
   branch tip committed within ~24h OR whose git index mtime is within ~24h
   (index mtime moves on staging/checkout activity before any commit exists —
   a tip-only test reads an uncommitted parallel session as stale). A worktree
   failing both probes is stale: ONE digest note line, never an ask.
3. **Cross-repo/foreign edits** — a modified TRACKED file outside this
   session's edit set. The edit set = the files the executor knows it edited
   this session (its own history), corroborated by `current.md`'s Completed
   entries; Key Files is a CURATED subset (schema: populated only on notable
   discoveries), never the authoritative touched list. Untracked strays never
   fire — they are simply not added.
4. **Foreign commits** — any output line. `--not HEAD` excludes this session's
   own HEAD-lineage checkpoints; the session's own commits on OTHER refs (e.g.
   an unmerged build-step worktree branch) may still surface — that ask errs
   safe.

**Step B — commit owner (exactly one).** The scoped commit+push of session
files is the ALWAYS-RUN base action unless explicitly delegated:

- **Delegate to `/repo-update`** — phase/feature completed this session.
  Detection: the active plan (discovered per Step 0(b)) exists, has >= 1
  step, and every step reads `**Status:** DONE` (the >= 1-step guard blocks
  the vacuous all-DONE of a step-less pointer plan), OR a build-phase
  completion report was produced this session. Action: invoke `/repo-update`
  via the Skill tool — it owns shipping (README/docs updates, commit, push,
  posterity issue); this skill duplicates none of that work, and its commit
  sweeps in the `current.md` written at route step 1. If `/repo-update` fails
  partway, run the base action below so nothing is stranded, and surface the
  repo-update failure in the digest.
- **Base action** — everything else. Detection: the delegate test above did
  not match. Action: scoped `git add` of the session edit set (as defined in
  check 3) **plus `current.md` itself** + commit + push, EXECUTED by
  default — this is the carrying commit route step 1 deferred
  (`--loop --no-commit`). A clean tree is a LEGAL outcome — e.g. a boundary
  write earlier this turn (plan-expedite's `--next-task`) already carried the
  commit+push; skip the empty commit and report `nothing to commit` in Step D.
  Clean but AHEAD of origin (an earlier push failed): still push, and report
  `pushed <n> pending` as the verb outcome instead.
  Never `git add -A` — every add names explicit
  paths; never add `handoff-prompt.md`.

**Step C — additive recommendation (independent of Step B).** Step C runs
regardless of which owner committed (withheld only when Step A downgraded its
scope, like Step B) and NEVER changes the commit owner; the recommended
COMMAND is never run mid-wrap.
Detection: the plan doc structurally changed this session — `### Step`
headings added/removed/renumbered, or step fields (Type / Depends on /
Done when) edited; more than Status-line flips. Action: add ONE recommendation
line to the digest —

- plan-review ran this session (in `current.md` Completed or this
  conversation), or the plan carries a fresh review marker → recommend
  `/repo-sync`. Order guard: never repo-sync before plan-review
  (`.claude/rules/plan-and-issue-flow.md`).
- review status unknown or absent → treat as NOT reviewed; recommend
  `/plan-review` first.

**Step D — report.** One line total, one segment per touched repo,
` / `-joined. Invariant 3 owns the base segment shape (cross-reference, not
restated); Step D appends only the verb outcome, ONE shared shape whichever
Step-B path ran:

    <invariant-3 segment> — <repo-update | committed N files + pushed @ <short-sha> | nothing to commit | ask-first pending>

---

## Rendering contract — `handoff-prompt.md`

`<git-root>/.claude/task-state/handoff-prompt.md` is a **rendering of `current.md`
plus the session's decisions log — never independently derived.** Every state field
in it (task, status, next action, SHAs, key files, gotchas) comes from the
just-written `current.md`; if the render needs a fact `current.md` lacks, write
`current.md` first, then render. Write order on both routes: `current.md` -> render
-> screen. Lifecycle + staleness rows live in the schema doc.

- **Untracked-on-purpose.** Session-local; never `git add` it. `current.md` remains
  the committed durable state.
- **Self-contained for a zero-context reader**, in this shape:
  1. Identity — project name, working directory, one line on what it is.
  2. State — Status + one `HEAD @ <short-sha>` line per touched repo (invariant 3).
  3. Verify-first instruction (invariant 2, exact form below).
  4. Next action — verbatim from `current.md`. If it is gated on human review, split
     it into an **Investigate** block ending "post findings and STOP" and a separate
     **After approval** block — never co-locate a gate and an action (a zero-context
     reader executes a single block sequentially).
  5. Decisions log — N decisions = N bullets, rejected alternatives kept.
  6. Key files + critical gotchas from `current.md`; parked/salvage pointers.
- **No nested code fences anywhere in the render** (invariant 5): commands as
  2-space-indented plain lines, paths and inline code in single backticks.
- **No flukes, no retry counts** (invariant 6).

---

## Pick-up-here screen contract

The screen output of `clear-next` and `end-window` is exactly this — the ONLY
required reading (plus, when `--spawn` was typed, one trailing spawn-status line —
a fired-mechanism report, not part of the render):

    ## Pick up here
    <exact next command(s), verbatim>

    <digest: <=6 lines>
    Full handoff: .claude/task-state/handoff-prompt.md

- **Exact next command(s):** `clear-next` -> `/clear` — unless any router
  segment reads `ask-first pending`; then the next command is the ask response
  (Git-verb router Step A), never `/clear` past the open gate. `end-window` -> the
  fresh-window opener, verbatim with an absolute path, e.g.
  `Read <project-root>\.claude\task-state\handoff-prompt.md fully, verify git state per its first instruction, then execute its Next Action.`
- **Digest (<=6 lines):** route + signal values; the git verb executed (repo, branch,
  SHA); memory/docs updates by name; invariant flags (`MEMORY.md over budget`,
  `friction catalog stale`, ...).
- **One pointer line** to `handoff-prompt.md`. Everything longer lives in the render,
  not on screen.

There is NO minimum length anywhere in this skill — no word-count floor for the
digest, the render, or any block. Terseness and specificity are coupled constraints;
see the note under the invariants.

---

## `--spawn` — auto-open the next window (end-window only, opt-in)

**Opt-in only.** `--spawn` fires only when the operator typed it explicitly (e.g.
`/session-wrap --end --spawn`) AND the routed action is `end-window`. Bare
`/session-wrap`, plain `--end`, the `continue` and `clear-next` routes, and every
chaining skill never auto-open a window — no default path fires a deep link
(plan-expedite's `--new-window` invokes `--end` WITHOUT `--spawn`; build-phase and
build-queue never spawn). `--spawn` alongside a non-`end-window` route is ignored
with this exact line:

    --spawn ignored (route was <route>, not end-window).

Fire AFTER the Pick-up-here block is on screen — the baseline must exist whether or
not the link works — via `code --open-url` (PowerShell; re-derived from stranded
commit `1c241a7`, behavior verified 2026-06-22):

    # --spawn deep link: try/catch because a missing `code` on PATH raises a
    # terminating CommandNotFoundException in PS 5.1 (an unguarded call would
    # die before the spawn-failed line could print)
    try {
        $gitRoot = (git rev-parse --show-toplevel).Trim() -replace '/','\'
        $pointer = "Read $gitRoot\.claude\task-state\handoff-prompt.md fully, verify git state per its first instruction, then execute its Next Action."
        code --open-url "vscode://anthropic.claude-code/open?prompt=$([uri]::EscapeDataString($pointer))"
        if ($LASTEXITCODE -ne 0) { throw "code exited $LASTEXITCODE" }
        Write-Output "spawned next window - press Enter there"
    } catch {
        Write-Output "spawn failed ($($_.Exception.Message)) - use the Pick-up-here block above"
    }

- **The pointer IS the Pick-up-here fresh-window opener, verbatim** — one source of
  truth. Never pass the handoff text itself (protocol-URI args have a length
  ceiling); always the absolute git-root path, so the new session resolves it
  regardless of cwd.
- **URL-encoding:** `[uri]::EscapeDataString` percent-encodes spaces, backslashes,
  and colons, but leaves `(` `)` `'` un-encoded (live-verified on this machine's
  .NET) — so the pointer text must avoid parentheses and apostrophes. Never
  hand-build the query string.
- **`code --open-url`, NOT `Start-Process`** — `Start-Process "vscode://..."`
  silently no-ops here (the URI reaches the OS handler but never routes to the
  running extension's window).
- The deep link PRE-FILLS the prompt but does not auto-submit — the operator presses
  Enter once in the spawned window. This window does not auto-close; it stays open
  as a backup until the operator switches. First use shows a one-time OS trust
  prompt ("allow ... to open this URI").
- **Armed unmet `/goal`:** the Stop hook re-drives this window regardless of the
  spawn — true termination is blocked until the goal is met or cleared. The
  end-window digest must surface an armed goal (triage signal (d)) so the operator
  clears or meets it before the old window actually ends.

**Copy-paste remains the irreducible baseline** (command-presentation rule): with
`--spawn` absent, ignored, or failing, the Pick-up-here block already on screen is
the fully usable handoff — the deep link is best-effort enhancement, never a
replacement. After firing, report exactly ONE spawn-status line, ASCII hyphen, as
emitted by the snippet: `spawned next window - press Enter there`, or on any failure
(`code` missing from PATH, non-zero exit, headless/terminal session with no VS Code
extension) `spawn failed (<reason>) - use the Pick-up-here block above`.

---

## Decisions log + salvage sweep (clear-next + end-window)

Not a session summary. Two bounded passes:

1. **Decisions log.** Enumerate the decisions made this session and the alternatives
   REJECTED — N decisions = N bullets, keeping but/except constraints ("chose X over
   Y because Z, except in case W"). Rejected alternatives are the part a fresh window
   cannot re-derive; keep them.
2. **Salvage sweep.** List knowledge that dies with this window: investigation
   findings written nowhere, seed docs worth creating, TODOs discovered but not
   filed. Each item is either **written now** (if it takes <= a few minutes) or
   **parked** as a pointer in `current.md` § Parked plus the project's MEMORY.md
   entry. Nothing gets a third option.

---

## The six behavioral invariants

Explicit requirements — every `clear-next`/`end-window` run satisfies all that apply:

1. **Read-then-report memory discipline.** Read MEMORY.md and the touched memory
   files BEFORE updating them; report what was read and the per-topic
   current/stale/absent verdicts before describing changes (full form in the
   end-window route).
2. **Git-verify-first + SHA anchor.** The render states `HEAD @ <short-sha>` and its
   verify-first instruction reads: *"First action — verify git state matches this
   prompt: run `git log --oneline -5` and `git rev-parse --short HEAD`. If HEAD does
   not match the SHA above, this prompt is stale — re-orient against actual git state
   before doing any work."* (Saved prompts freeze a pre-execution view; git is the
   only live state.)
3. **Per-repo SHA lines in multi-project sessions.** Every touched repo gets its own
   ` / `-delimited status segment (name, branch, ahead-count, dirty state — e.g.
   `toybox master clean / dev master 2 unpushed, 1 dirty`) and its own
   `HEAD @ <sha>` line in the render. One combined SHA is non-conforming.
4. **Duplicate-memory guard + MEMORY.md budget warning.** Check for an existing
   memory before writing; update stale entries instead of appending duplicates.
   Over-budget MEMORY.md (>200 lines, or any line >200 chars) raises a digest flag,
   never an auto-trim.
5. **No nested code fences** in the render or any copy-paste block — indented command
   lines and single backticks only; a triple backtick inside a copy-paste block
   terminates it and breaks the paste.
6. **Fluke-exclusion.** Transient failures, one-off typos, and retry counts appear
   nowhere: not in the render, not in the digest, not in memory. Describe the
   pattern, never the episode.

**Coupled-constraint note (edit these together).** Invariants 5-6 plus the <=6-line
digest and the no-floor rule are the *terseness* side; invariants 1-3 plus the
verbatim next action are the *specificity* side. Edited in isolation they regress
each other — 4 of the first 8 eval iterations on the predecessor skill were discarded
for exactly that. Any future edit to one side must re-check the other.

---

## Flags

- **bare** — triage (Step 0), then the routed action. The default and safest mode.
  Never fires a deep link.
- **`--end`** — operator intent made explicit: skip threshold scoring, route
  `end-window`. (`/task-handoff --end` delegates here.) An optional trailing
  free-text token (e.g. the plan path plan-expedite passes) is an advisory focus
  hint only — every rendered next action still derives from `current.md`.
- **`--spawn`** — opt-in deep-link auto-open of the next window whenever the routed
  action is `end-window`: typically typed as `--end --spawn`, but bare `--spawn`
  also fires if triage itself routes `end-window`, and is otherwise ignored with the
  exact line in the `--spawn` section above. Nothing ever spawns without the
  explicit flag.
- **`--advise`** — triage (Step 0) + a read-only salvage-sweep preview, then the
  4-verdict banner + two-line loss report (section below) and STOP. Never writes,
  never runs a git verb, never emits `/clear`; `--end`/`--spawn` alongside it are
  ignored. `SAFE TO CLOSE` exists only here — bare triage still scores exactly
  three routes.

---

## `--advise` — verdict + loss report (read-only, never acts)

For the returning operator who wants the triage verdict WITHOUT the action — "can I
close this window without losing anything?".

- **Same triage, plus a preview.** `--advise` runs Step 0 triage exactly as bare mode
  does (same signals, same first-match-wins scoring) plus a READ-ONLY preview of the
  salvage sweep — what `end-window`'s sweep (section above) WOULD find: uncommitted
  work, unpushed commits, un-checkpointed or git-inconsistent `current.md` state,
  findings and TODOs written nowhere. Freshness follows the staleness threshold owned
  by `task-state-schema.md`; consistency is
  Step 0's own Session-SHA-vs-HEAD signal.
- **Prints, then STOPS.** The report below is the entire output. Zero writes, zero
  git mutations: no `current.md` write, no render, no git verb, no `task-handoff` or
  `/repo-update` invocation, no Pick-up-here block, no `/clear` emission, no spawn.
- **Bare mode untouched.** The 3-route triage-then-act contract runs only when
  `--advise` is absent, and `SAFE TO CLOSE` exists only here, never as a fourth bare
  route.
- **Flag interplay.** `--end`/`--spawn` alongside `--advise` are ignored (advise
  never acts, so there is nothing to force or spawn).

The triage line still prints first (Step 0's announce contract), with the route
segment marked as computed-not-acted:

    triage: advise (would route <route>) | context: <N tokens (~X% assuming 200k)> | boundary: <mid-task | at boundary (<what>)> | git: <n dirty, m ahead[, per-repo]> | goal: <armed | none>

Then the report — one verdict banner plus a two-line loss report, nothing else:

    ## <VERDICT>
    Already durable: <what is safe, with evidence - commits/pushes with short SHAs, current.md Last written timestamp + freshness verdict, Session SHA vs HEAD>
    Dies with this window: <each at-risk salvage-preview item with a count plus a path/SHA/identifier - or exactly `nothing` when the preview is empty>

**The four verdicts** — exactly one banner per run, from this closed set:

| Verdict | Condition |
|---|---|
| `KEEP GOING` | Triage would route `continue`. |
| `RECYCLE WINDOW` | Triage would route `clear-next`. |
| `WRAP & CLOSE` | Triage would route `end-window` AND something would die with the window. |
| `SAFE TO CLOSE` | `end-window` would be a NO-OP — ALL of: `current.md` fresh (schema-doc threshold) and consistent with git (Session SHA matches HEAD), clean tree in every touched repo, nothing unpushed/ahead anywhere, no armed `/goal`, salvage preview empty. |

The two end-window verdicts partition that route: every no-op condition holds ->
`SAFE TO CLOSE`; any single failure -> `WRAP & CLOSE`, and the failing item IS the
loss — it lands on the `Dies with this window:` line, named concretely. The loss
report is the centerpiece (the operator's real anxiety is losing work): hedged prose
("some work may be lost") is a defect — SHAs, counts, timestamps, and paths are the
contract, and an empty preview reads exactly `nothing`.

## Maintenance

The `evals/` suite targets THIS triage contract (rebuilt 2026-07-12, #297;
`--advise` category added 2026-07-13, #304): **26 assertions** across **6
categories** in `evals/evals.json` (passing threshold **24/26**), **5 scenarios** in
`evals/test_scenarios.json` (one per route, the signal-absent fail-loud path, and the
`--advise` SAFE-vs-WRAP close-check), and a golden corpus of 8 goods + 26
single-defect bads under `evals/golden/` (manifest.json maps each bad to the one
assertion it trips). Any edit that changes an output contract here (triage line,
route output, Pick-up-here block, render invariants, advise verdict banner or loss
report) must update the affected assertions and goldens in the same diff, keeping
this footer's numbers equal to `evals.json`'s. Terseness and specificity assertions
are coupled (see the invariants note) — re-check both sides after any one-sided
edit.
