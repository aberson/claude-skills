---
name: goblin-do
description: The single front door for a chosen goblin atom. Mode-dispatches a resolved suggestion or UAT task — a `small` suggestion or a safe `uat` task is EXECUTED via /build-step (auto-ship a genuinely-clean result, park the rest with a one-line --land to ship later); a `big` suggestion or a not-safe `uat` task is HANDED OFF (prints the /plan-feature seed + the build-rail next step). Collapses /goblin-handoff for the small path.
user-invocable: true
---

# goblin-do

> **Reference skill — requires a private "second brain" + the `goblin` CLI, both omitted here.**
> Published as a **design reference**, not runnable as-is: it reads a per-project second-brain atom
> store (`brain/suggestions/*.md`) that is **not included, for privacy**, and it is driven by the
> **`goblin` CLI** (a separate project) that is likewise not part of this repo. To reconstruct a
> working version, see [`_shared/goblin-second-brain.md`](../_shared/goblin-second-brain.md) — it
> documents the atom shape and how to build your own second brain. The design below is unedited.

Take ONE chosen goblin atom (a suggestion produced by `/goblin-suggest`, or a UAT task
produced by `/goblin-suggest --uat`, persisted under `brain/suggestions/`) and act on it.
`goblin do` is the single front door: it resolves the atom, reads its kind + mode, and
**mode-dispatches**:

- a **`small` suggestion** or a **safe `uat` task** → **EXECUTED**: goblin leases the
  existing workspace `/build-step` rail against the TARGET project inside a
  `goblin/do/<slug>` scratch branch, then either **auto-ships** a genuinely-clean result
  (fast-forwards it into the target's default branch) or **parks** anything borderline on
  the scratch branch with a one-line `goblin do --land <id>` to ship later.
- a **`big` suggestion** or a **not-safe `uat` task** → **HANDED OFF**: prints the
  `/plan-feature` seed (or a UAT handoff block) + the build-rail next step. A big idea or a
  not-safe task needs real planning / human work — auto-executing it would be wrong, so
  `goblin do` deliberately stops at the handoff.

This **collapses `/goblin-handoff`** for the small path: where you previously ran
`/goblin-handoff <id>` then hand-built the result, the small/safe path is now one command.
The big/not-safe path still emits exactly the same seed `/goblin-handoff` did.

## Prerequisites

- A suggestion or UAT atom exists. Run `/goblin-suggest <project>` (or
  `/goblin-suggest <project> --uat`) first; it persists atoms under
  `brain/suggestions/` (`sugg-<project>-<slug>.md` or `uat-<project>-<slug>.md`). Pick one.
- `uv sync` has been run in the `b2_project_goblin` directory (installs the `goblin`
  console script).
- **For EXECUTION** (a `small`/safe-`uat` atom, NOT `--dry-run`):
  - `CLAUDE_CODE_OAUTH_TOKEN` is set (subscription OAuth — NOT an API key). The session
    path runs `/build-step` via a Workflow `agent()` call, which stays on subscription.
  - `gh` is authenticated (`gh auth status`). An issue-anchored atom re-checks the issue is
    still OPEN via `gh` before acting.
  - The target project is a **clean git repo** — `goblin do` refuses a dirty target working
    tree (it will not create a scratch branch on uncommitted changes).
- For a `--dry-run` preview, none of the execution prerequisites are needed (it touches
  nothing). For the `big`/not-safe handoff path, no OAuth/`gh`/clean-tree is needed either —
  it only reads the atom and renders text.

## How to invoke

**Session path (recommended — runs /build-step via Workflow agent(), stays on subscription OAuth):**

```javascript
// From a Claude Code session:
Workflow({
  scriptPath: ".claude/skills/goblin-do/goblin_do.workflow.js",  // part of the goblin CLI project (not in this repo)
  args: { id: "sugg-toybox-add-a-smoke-test" }
})
```

Or via the `/goblin-do` skill shorthand when invoked interactively.

**CLI fallback path (non-session / offline — shells to `claude -p` for the build-step dispatch):**

From the `b2_project_goblin` directory:

```powershell
uv run goblin do <id-or-text>
```

The argument is a suggestion/UAT atom id (the filename stem, e.g.
`sugg-toybox-add-a-smoke-test` or `uat-toybox-run-the-emulator-smoke`) OR free text that
fuzzy-matches one atom. Examples:

```powershell
uv run goblin do sugg-toybox-add-a-smoke-test
uv run goblin do "add a smoke test"
uv run goblin do sugg-void-furnace-tighten-plan-doc --brain-dir ./brain
```

Preview the dispatch without creating a branch or running anything (CLI or session):

```powershell
uv run goblin do sugg-toybox-add-a-smoke-test --dry-run
```

Ship a previously-parked item after you have glanced at its branch (CLI path):

```powershell
uv run goblin do --land sugg-toybox-add-a-smoke-test
```

Flags:

- `--dry-run` — preview the build-step dispatch (the resolved target, the
  `goblin/do/<slug>` scratch branch, and the EXACT `/build-step` command that WOULD be
  dispatched) without creating a branch or dispatching anything.
- `--land <id>` — ship a previously-parked item via fast-forward (FF-only; never `--force`).
- `--brain-dir <path>` — override the atom store (default: the goblin repo's `brain/`).
- `--land --dry-run` is **refused** (there is no meaningful preview of a land — landing does
  a real fast-forward + a real target test gate; the refusal points you at `git log` /
  `git diff` on the parked branch for an actual preview).

## What it does

### Mode dispatch

`goblin do` resolves the atom once across both kinds, then dispatches on kind + mode:

| Atom | Outcome |
|---|---|
| Suggestion `mode: small` | EXECUTE via `/build-step` (auto-ship-clean / park-rest) |
| Suggestion `mode: big` | HAND OFF — print the `/plan-feature` seed + build-rail next step |
| UatTask, **safe** subset | EXECUTE via `/build-step` (the executor re-applies the safe gate) |
| UatTask, **not** safe | HAND OFF — print the UAT handoff block + build-rail next step |

A UAT task is in the **safe-auto-execute subset** when it is `ai_doable`, has an empty
`clarifying_question`, and has no `human_residual_steps` (the `uat` analogue of a
suggestion's `small` mode). Anything else is handed off.

### The execute path (auto-ship-clean / park-rest)

For a `small` suggestion or a safe `uat` task, goblin:

1. Re-checks the anchor is still LIVE (an issue-ref anchor must be OPEN per `gh`; a
   file-path anchor must still be tracked in the target). A stale anchor refuses loudly.
2. Resolves the target, refuses a dirty target tree, computes the default branch + its SHA.
3. Creates the `goblin/do/<slug>` scratch branch and leases `/build-step` against the
   target inside a worktree `/build-step` creates (its developer agent does ALL source
   edits — goblin's own process never writes the target's source).
4. Decides **auto-ship vs park** against a four-part floor — it auto-ships ONLY when ALL of:
   - `/build-step` reported a clean **PASS** (not BLOCKED), AND
   - the target's **default-branch SHA is byte-unchanged** (no stray merge to default
     happened during the build), AND
   - the produced **diff is confined** to the anchored file(s) + its related test, AND
   - the **anchor is live** and the text resolved to **exactly one** atom.
   Any miss → **park** (the scratch branch + its commits are kept; the default is untouched).
5. On an auto-ship: fast-forwards the confined diff into the target's default branch and
   deletes the scratch branch.
6. On a PASS, flips the originating atom `status: proposed → accepted` and appends a
   `goblin-do:<branch>` provenance entry — goblin's ONLY authored write, into `brain/` only.

### The do → glance → --land flow for a parked item

When a result parks (e.g. `/build-step` left a borderline change, or the diff sprawled
beyond the anchor), goblin prints the parked branch + a one-line `goblin do --land <id>`.
The flow is:

1. `uv run goblin do <id>` → result PARKED on `goblin/do/<slug>`.
2. Glance at the parked work:
   ```powershell
   git -C <target> log --oneline <default>..goblin/do/<slug>
   git -C <target> diff <default>..goblin/do/<slug>
   ```
3. If it looks good, ship it (FF-only; re-runs the target's own test gate first):
   ```powershell
   uv run goblin do --land <id>
   ```

`--land` asserts a clean fast-forward (the default tip must be an ancestor of the branch
tip — a diverged branch is refused, never force-merged), re-runs the target's own tests as
the last guard, FF-merges, deletes the branch, and appends a `goblin-land:<branch>`
provenance entry.

### The dry-run preview

`--dry-run` resolves the target + scratch branch and prints the EXACT `/build-step` command
that WOULD be dispatched — but creates no branch, dispatches nothing, and writes nothing to
`brain/`. Use it to confirm the target + command before spending the real build.

## How to read the output

The CLI prints a labelled block keyed to the outcome (`action`):

- **`dry-run`** — a PREVIEW: `Project`, `Target`, a `Mode: DRY RUN (preview only ...)` line,
  the `Default branch`, the `Anchor` status (`<file> — live (tracked)` or refused), the
  `Scratch branch (would be created)`, the `Would dispatch /build-step:` command, and the
  `Reason`. Nothing was created or dispatched.
- **`shipped`** — `/build-step` built it and the result auto-shipped: `Project`, `Target`,
  `Default branch (fast-forwarded)`, `Scratch branch (built + merged, then deleted)`, the
  `Changed files`, the `Reason`, and the `Atom` field (`<id> → status: accepted`).
- **`parked`** (two sub-cases, same label):
  - *Built but parked* (failed a gate): `Project`, `Target`, `Default branch (unchanged)`,
    `Scratch branch (kept — its commits survive)`, `Changed files`, `Reason` (names every
    gate that missed), `Atom` (`<id> → status: accepted`), and — prominently — `PARKED —
    to ship it after a glance, run:` with the one-line `goblin do --land <id>` command.
  - *Big or not-safe handoff* (no build dispatched): `Project`, `Target`, and — prominently —
    `PARKED (handoff) — to plan this, paste this seed into /plan-feature:` followed by the
    `/plan-feature` seed text and the build-rail next step (`/plan-review → /repo-sync →
    /build-phase`). No scratch branch; no atom status change.
- **`landed`** — a previously-parked item shipped via `--land`: `Project`, `Target`,
  `Default branch (fast-forwarded)`, `Scratch branch (landed, then deleted)`, the `Changed
  files`, and the `Reason`.

A bad/ambiguous/unknown id, a bad target, or a guardrail refusal (mode/safe gate, stale
anchor, dirty tree, branch slip) prints `goblin do failed: <reason>` to stderr and exits
nonzero.

## Cost / latency note

Every EXECUTE runs a full `/build-step` (a worktree dependency rebuild + up to 3 build
iterations + 4 reviewers) via a Workflow `agent()` call (session path) or `claude -p`
subprocess (CLI fallback). Expect this to take **minutes and real token cost per fix** —
`goblin do` is not free the way `/goblin-suggest` reading-and-ranking is. Use `--dry-run`
first if you want to confirm the target + command before paying for the build. The session
path stays on subscription OAuth; the CLI fallback uses `claude -p`.

## Relationship to other skills

`goblin do` **collapses `/goblin-handoff`**: the small/safe path that previously needed a
separate handoff + hand-built result is now this one command, and the big/not-safe path
emits the exact same `/plan-feature` (or UAT handoff) seed `/goblin-handoff` did. The
`goblin handoff` CLI subcommand still works as a **deprecated alias** (it prints a
deprecation note to stderr, then the seed) so nothing breaks for an existing caller — but
prefer `goblin do <id>`.

This big/not-safe handoff is the codified template the routing web's re-route contract
was generalized from — the do→plan edge (the atom needs real planning), and likewise
do→bug when the thing being improved turns out to be broken (the correct-rail seed is
then a `/user-debug --symptom` line rather than a `/plan-feature` seed). The full
contract — the standard emit-line format and the write-back to the intake ledger when
one exists — is owned by
[`skill-pipeline.md § Re-route contract`](../_shared/skill-pipeline.md);
cite it there, never restate it.

For a handed-off `big`/not-safe atom, paste the emitted seed into `/plan-feature`, then run
the normal build rail: `/plan-review` → `/repo-sync` → `/build-phase`.
