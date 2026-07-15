# goblin's "second brain" (and why goblin-suggest / goblin-do ship as reference only)

`/goblin-suggest` and `/goblin-do` are published here as **design references**. They are
not runnable as-is, because each depends on two pieces that are **not** part of this repo:

1. **A per-project "second brain" — an atom store.** goblin persists its ranked improvement
   ideas and UAT tasks as git-tracked markdown+YAML files under `brain/suggestions/`. That
   store holds the operator's real, project-specific notes, so it is **omitted for privacy**.
   The skills are meaningless without one — `goblin-suggest` *writes* atoms into it and
   `goblin-do` *reads* one back out to act on.
2. **The `goblin` CLI.** The pipeline itself (grounding, candidate generation, the parallel
   LLM-judge rubric, ranking, persistence, and the `/build-step` lease in `goblin-do`) lives
   in a separate project that exposes a `goblin` console script (`goblin suggest`, `goblin
   do`) plus the two `*.workflow.js` bridges. That project is **not published here**; the two
   `SKILL.md` files are the full, unedited description of what it does.

Everything below is what you need to **build your own second brain** so the two skills'
design is reproducible in your own workspace.

## What an "atom" is

One idea = one file. Dateless `id` (the filename stem) so a re-run **updates in place**
instead of creating dated duplicates. Two kinds share the `brain/suggestions/` directory and
never collide, because their filename prefixes differ (`sugg-` vs `uat-`).

### Suggestion atom — `brain/suggestions/sugg-<project>-<slug>.md`

Produced by `/goblin-suggest --small` (additive quick wins) or `--big` (larger ideas).

```yaml
---
id: sugg-<project>-<slug>
type: suggestion
mode: small          # small | big
status: proposed     # proposed -> accepted (flipped when goblin-do acts on it)
project: <project>
title: <short title>
anchor: <a REAL artifact>     # file path | issue #N | plan line — ungrounded ideas are rejected
scores:                        # 4-axis rubric, each 1-5, the median over N judge runs
  feasibility: 4
  fit: 4
  leverage: 3
  reversibility: 5
composite: 4.0                 # mean of the four axis-medians (drives the ranking)
provenance: []                 # e.g. [goblin-do:<branch>, goblin-land:<branch>]
---
<the suggestion body: what to change and why, grounded in `anchor`>
```

### UAT atom — `brain/suggestions/uat-<project>-<slug>.md`

Produced by `/goblin-suggest --uat` (triage of operator-asks for AI takeover). Carries **no
`scores`** — the triage fields *are* the score.

```yaml
---
id: uat-<project>-<slug>
type: uat
mode: uat
status: proposed
project: <project>
description: <the operator-ask this task covers>
anchor: <where the ask came from: a plan M-step, a `Type: operator` step, a handoff cue>
ai_doable: true                # can an AI do this end-to-end, no human?
clarifying_question: none      # none | one | many (the consensus ordinal) — or the single Q to start
human_residual_steps: []       # what a human must still do; empty => fully AI-doable ("safe" subset)
---
<task detail>
```

## Minimal DIY setup

1. Make the store: a git-tracked `brain/suggestions/` directory (a `brain/SCHEMA.md`
   documenting the frontmatter above is optional but recommended — goblin keeps its schema
   there as the one source of truth).
2. Write the pipeline the `SKILL.md` files describe: **ground** (read the target project's
   CLAUDE.md + plan + open issues, enveloped as untrusted data), **generate** anchored
   candidates via one model call, **grade** each with N parallel judge calls (drop any with
   fewer than N valid verdicts — the partial-verdict guard), **rank** by `composite`, and
   **persist** one atom per survivor (atomic write, update-not-duplicate).
3. For the `goblin-do` execute path, lease your own build harness (this repo's
   [`/build-step`](../build-step/SKILL.md)) on a scratch branch and auto-ship only on a
   clean PASS + confined diff; otherwise park.

The two `SKILL.md` files spell out the modes, the safe-auto-execute subset, the auto-ship
floor, and the read-back output format in full.
