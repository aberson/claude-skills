---
name: goblin-suggest
description: Produce a grounded, ranked improvement shortlist for a workspace project and persist it to goblin's brain/ atom store. Three mutually-exclusive modes: --small (default — small, purely-additive, non-disruptive quick wins), --big (full-fidelity improvement ideas), and --uat (triage the project's operator-asks for AI takeover). Reads the project's real state, generates anchored candidates, scores/triages them with parallel LLM judges, ranks, and writes mode-discriminated atoms.
user-invocable: true
---

# goblin-suggest

> **Reference skill — requires a private "second brain" + the `goblin` CLI, both omitted here.**
> Published as a **design reference**, not runnable as-is: it reads/writes a per-project
> second-brain atom store (`brain/suggestions/*.md`) that is **not included, for privacy**, and it
> is driven by the **`goblin` CLI** (a separate project) that is likewise not part of this repo. To
> reconstruct a working version, see [`_shared/goblin-second-brain.md`](../_shared/goblin-second-brain.md)
> — it documents the atom shape and how to build your own second brain. The design below is unedited.

Run goblin's full project-improvement pipeline against one workspace project. The skill
grounds in the project's REAL state (CLAUDE.md + plan + open issues + memory), generates
candidate improvements anchored to real artifacts, scores each candidate with a parallel
four-axis LLM-judge rubric, ranks the survivors, and persists them as git-tracked
suggestion atoms under `brain/suggestions/`.

This is the v1 keystone (Phase D). When invoked from a Claude Code session, the LLM
steps run via the `Workflow` tool (`goblin_suggest.workflow.js`) — all `agent()` calls
stay on subscription OAuth (`CLAUDE_CODE_OAUTH_TOKEN`), not per-token billing. The
CLI fallback (`uv run goblin suggest <project>`) shells to `claude -p` subprocess calls
and remains available for non-session/offline use.

## Prerequisites

- `CLAUDE_CODE_OAUTH_TOKEN` is set in the environment (subscription OAuth — NOT an API
  key; the API key would double-bill).
- `gh auth status` shows you are logged in. Grounding reads the target project's open
  issues via `gh`; a project with no remote / no auth just yields zero issues (the run
  still works, with less context).
- `uv sync` has been run in the `b2_project_goblin` directory (installs the `goblin`
  console script + deps).
- The target project is a direct child of the dev workspace root and has a `CLAUDE.md`
  and a discoverable plan doc (grounding fails loud otherwise).

## How to invoke

**Session path (recommended — runs via Workflow, stays on subscription OAuth):**

```javascript
// From a Claude Code session — invoke the Workflow directly:
Workflow({
  scriptPath: ".claude/skills/goblin-suggest/goblin_suggest.workflow.js",  // part of the goblin CLI project (not in this repo)
  args: { project: "toybox", mode: "small", n_candidates: 5, n_judges: 3 }
})
```

Or via the `/goblin-suggest` skill shorthand when invoked interactively.

**CLI fallback path (non-session / offline use — shells to `claude -p`):**

From the `b2_project_goblin` directory:

```powershell
uv run goblin suggest <project>
```

Examples:

```powershell
uv run goblin suggest toybox                     # --small (default): additive quick wins
uv run goblin suggest void_furnace --big --n-candidates 5 --n-judges 3
uv run goblin suggest toybox --uat               # triage operator-asks for AI takeover
```

Flags:

- `--small` / `--big` / `--uat` — the generation mode (mutually exclusive; default
  `--small`). See **Modes** below. Supplying two at once is an argparse error.
- `--n-candidates N` — how many candidates to generate (default 5). Applies to
  `--small` / `--big` only; `--uat` emits one task per distinct operator-ask, so it
  ignores this flag.
- `--n-judges N` — judge runs per candidate/task (default 3). Each candidate (or UAT
  task) must clear N valid verdicts or it is dropped (the partial-verdict guard).
- `--brain-dir <path>` — override the atom store (default: the goblin repo's `brain/`).

## Modes

`goblin suggest` has three mutually-exclusive modes. Each produces a SEPARATE ranked
list and persists its own atom kind; you pick at most one (the default is `--small`).

- **`--small` (NEW DEFAULT)** — small, purely-additive, non-disruptive quick wins: edits
  that need no- or at-most-one clarifying question to start and don't disrupt existing
  behavior. The cheap/fast path for a bare `goblin suggest <project>`.
- **`--big`** — the original full-fidelity, bigger-improvement-idea behavior (today's
  single-prompt generation). Use when you want substantial improvement proposals, not
  just additive quick wins.
- **`--uat`** — a DIFFERENT activity, not a different-sized suggestion. It scans the
  project's **operator-asks** — `## Manual UAT` / `### M<n>:` plan blocks,
  `**Type:** operator|wait` steps, and operator-handoff cue phrases ("please run",
  "operator confirms/runs", "run X next") — and triages each one for AI takeover (could
  an AI do this end-to-end? what's the single question to start? what human-only residual
  remains?). It persists `uat-*.md` atoms, NOT suggestion atoms.

`--small` and `--big` share the 4-axis rubric and the suggestion pipeline; `--uat` runs
a DISTINCT pipeline with its own triage (no 4-axis scores). See **What it does** below.

## What it does (pipeline stages)

### `--small` / `--big` (the suggestion pipeline)

1. **ground** — validate the project arg, read its real CLAUDE.md + plan + open issues +
   memory atoms. All fetched content is enveloped as untrusted DATA (prompt-injection
   defense) before any model sees it.
2. **generate** — build one generation prompt (`goblin suggest --export-prompts`), then
   call ONE `agent()` (session path) or `claude -p` (CLI fallback). Parse the model's
   JSON array into candidates. The prompt's instruction framing branches on the mode:
   `--small` asks for small, purely-additive, non-disruptive quick wins; `--big` asks for
   the original bigger-improvement ideas. Each candidate must be anchored to a REAL
   artifact (file path / issue number / plan line); ungrounded ones are rejected at parse
   time.
3. **grade** — for EACH candidate, fan out `--n-judges` judge agent calls IN PARALLEL
   (session path: `parallel()` in the Workflow; CLI path: a ThreadPoolExecutor per
   candidate), each scoring the four rubric axes (feasibility, fit, leverage,
   reversibility) 1–5. Per-axis median over the valid verdicts; composite = mean of the
   four axis-medians. Grading does NOT branch on mode — the 4-axis rubric is shared across
   `--small` and `--big`. A candidate with fewer than `--n-judges` valid verdicts is
   DROPPED, never scored on a partial set.

   **Optional local-judge offload (switchboard, INERT BY DEFAULT).** This judge fan-out is
   the one role this skill may route to a local model (tier-offload task_class
   `goblin-suggest-judge`; Switchboard Decision 9 — a cheap parallel rubric-scoring array).
   It is **off unless switchboard offload is enabled for this slice**. For each judge call,
   first consult the switchboard judge entrypoint with the rubric prompt:
   `python -m switchboard judge --site goblin-suggest-judge --prompt-file <judge-prompt-file>`
   (prints one JSON object, always exits 0). On a **verdict**, use it as that judge's
   advisory vote. On a **defer** (`{"defer": true, ...}`) — ALWAYS the case when offload is
   off, the slice is disabled, or the model is down/slow/wrong-shaped — fall back to the
   normal Claude judge agent for that vote. When offload is OFF (the default), the entrypoint
   returns a defer immediately with no network call, so grading runs on Claude **exactly as
   before**. The local model only advises an axis vote; the median/rank/persist logic is
   unchanged and never gated by the local model.
4. **rank** — order the survivors by composite score, descending (deterministic
   tie-break by title).
5. **discrimination guard** — if every candidate scored nearly the same, the rubric
   measured nothing; the run flags the ranking as non-discriminating.
6. **persist** — write each ranked candidate as a `brain/suggestions/sugg-<project>-<slug>.md`
   atom (atomic write, update-not-duplicate — a re-run updates the same file rather than
   creating a dated duplicate). Each atom is tagged with the `mode` it was produced under.

### `--uat` (the operator-ask triage pipeline)

A DISTINCT pipeline with its own triage — no 4-axis rubric, no discrimination guard:

1. **ground (uat)** — scan the project's already-neutralized sources for **operator-asks**
   (`## Manual UAT` / `### M<n>:` plan blocks, `**Type:** operator|wait` steps, and
   operator-handoff cue phrases like "please run" / "operator confirms/runs" / "run X
   next"); emit one ask per detected unit of operator work.
2. **generate (uat)** — call ONE `agent()` (session path) or `claude -p` (CLI fallback)
   to turn the operator-asks into UAT tasks (one task per distinct ask; `--n-candidates`
   does NOT apply). Each task is anchored to the source ask; ungrounded ones are rejected
   at parse time.
3. **assess (uat)** — for EACH task, fan out `--n-judges` judge agent calls IN PARALLEL. Each
   judge votes just two consensus fields: `ai_doable` (can an AI do this end-to-end with
   the project's substrate, no human?) and a 3-valued clarifying-question-count ordinal
   (`none` < `one` < `many`). Consensus = bool MAJORITY (a tie resolves to **needs-human**,
   the conservative default) + ordinal MEDIAN. A task with fewer than `--n-judges` valid
   verdicts is DROPPED.
4. **rank (uat)** — order AI-doable-with-fewest-questions first (so an AI-doable task that
   needs ≤1 question to start floats to the top); human-residual tasks last.
5. **persist (uat)** — write each ranked task as a `brain/suggestions/uat-<project>-<slug>.md`
   atom (same dir as suggestion atoms, distinct `uat-` prefix + `mode: uat` discriminator;
   atomic write, update-not-duplicate). These atoms carry NO `scores` field — the triage
   (`ai_doable` + `clarifying_question` + `human_residual_steps`) IS the score.

## How to read the output

The output view depends on the mode.

### `--small` / `--big` (suggestion view)

The CLI prints, in order:

- **Grounding confirmation** — a line confirming untrusted-data framing was applied:
  `Grounding: all fetched content (CLAUDE.md, issues, atoms) treated as untrusted data.`
- **Ranked shortlist** — one line per surviving candidate: rank, composite score, title,
  anchor, and the four per-axis scores. Top of the list = best per the rubric.
- **Discrimination flag** — `OK` means the composite scores have real spread (the
  ranking is meaningful). `WARN — NOT discriminating` means the rubric scored everything
  the same; treat the ranking as LOW-CONFIDENCE and re-run or inspect the candidates
  manually before acting on the order.
- **Dropped count** — how many candidates the partial-verdict guard dropped (a judge
  call returned malformed output for them). A high count means the judge calls are flaky.
- **Persisted atom paths** — one line per atom written: `brain/suggestions/sugg-<slug>.md (mode: small|big, status: proposed)`.

### `--uat` (triage view)

A `--uat` run prints the UAT triage shortlist instead (no discrimination line — the UAT
triage is not a 4-axis rubric). Per ranked task, in AI-doable-with-fewest-questions-first
order:

- A verdict line: `ai_doable=yes|no`, the consensus question-count (`none` / `one` /
  `many`), and the `anchor`, followed by the task `description`.
- Then ONE actionable line keyed to the triage:
  - **AI-doable AND exactly one consensus question** → the single clarifying question an
    AI needs answered to START the work.
  - **NOT AI-doable** → the exact `human_residual_steps` the human must still do (or
    "(none listed)").
  - (An AI-doable task with `none` / `many` questions surfaces neither — just the verdict
    line: a single question is not the actionable next step there.)
- **Dropped count** — how many tasks the partial-verdict guard dropped.
- **Persisted atom paths** — the `brain/suggestions/uat-*.md` files written.

## Where atoms are persisted

All atoms land in `brain/suggestions/`, one git-tracked markdown+YAML file each (the
dateless id means a re-run updates in place). The filename prefix is mode-discriminated:

- `--small` / `--big` → `sugg-<project>-<slug>.md` (slug from the candidate title).
- `--uat` → `uat-<project>-<slug>.md` (slug from the task `description`).

Both kinds share the directory but never collide — the distinct `sugg-` / `uat-` prefix
keeps the readers isolated. The frontmatter spec is in `brain/SCHEMA.md` (mirrors
`src/goblin/models.py`). A suggestion atom carries `status: proposed`, `type: suggestion`,
and the `mode` it was produced under (`small` / `big`); a UAT atom carries
`status: proposed`, `mode: uat`, and its triage fields (no `scores`).

## Next step

To act on a persisted atom:

```text
/goblin-do <id>
```

`/goblin-do` is the single front door for a resolved atom: a `small` suggestion or safe
`uat` task is EXECUTED via /build-step; a `big` suggestion or not-safe task is HANDED OFF
(it prints the `/plan-feature` seed). The id is the atom filename stem, e.g.
`sugg-toybox-add-a-smoke-test`. (`goblin handoff` survives only as a deprecated CLI alias —
see [Relationship to other skills](../goblin-do/SKILL.md#relationship-to-other-skills).)
