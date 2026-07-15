# Skill role taxonomy — tags + fan-out classification protocol

Direction-NEUTRAL source of truth for classifying the LLM-bearing roles inside a skill's
`SKILL.md`. It defines the tag set (§1) and the parallel classification protocol (§2–§3) that
produces a per-skill role table. It deliberately says nothing about where any role should
*route* — see §4.

Cited by: `tier-offload` (down-direction — which roles can route to a cheaper model) and
`tier-escalate` (up-direction — which roles warrant a stronger model), both as
`../_shared/skill-role-taxonomy.md`. Each consuming skill layers its own verdict rules
on top of the neutral classification this file produces.

---

## §1 The role taxonomy

Tag every role in a skill that performs — or replaces — LLM work with exactly one of these
seven tags. MECH exists precisely for steps that need no LLM reasoning: tag them, don't drop
them, or the classification is incomplete.

| Tag | Role definition | Character (direction-neutral) |
|---|---|---|
| **ORCH** | Orchestration — drives a multi-step pipeline, dispatches sub-agents | Stateful coordinating spine; holds cross-step context |
| **AUTHOR** | Authorship — writes code, prose, docs, plans, notebook cells | Produces content; each pass creates rather than scores |
| **PLAN** | Planning — designs a plan, sequences steps, makes architecture calls | Open-ended design reasoning; decisions ripple downstream |
| **JUDGES** | A fan-out **array** of judges/graders scoring N items in parallel | Parallel array of cheap scorers; arms are independent and individually low-stakes |
| **GATE** | The final/consolidating judgment — the merge/ship/keep decision | Single decision point consuming upstream findings; correctness-critical |
| **MECH** | Mechanically checkable — exit code, valid JSON, regex/refusal match, `goal_condition` | Mechanically checkable; no LLM reasoning required |
| **SOLO** | A single-pass reasoning call, not a fan-out array | One call, one context; not a parallel array |

**Tag boundaries (common mis-tags).** These are classification rules only — they carry no
routing verdict:

- A fan-out whose arms each **produce** content is AUTHOR, not JUDGES. JUDGES requires every
  arm to be *scoring*, not *creating*.
- A checklist enumerated in prose but executed as **one pass** at runtime is SOLO, not JUDGES.
  JUDGES requires a genuinely parallel array.
- The consolidating decision over a JUDGES array is a separate GATE role — when a skill has
  both, tag both.

---

## §2 Fan-out classification protocol

A fresh model citing this file runs a complete pass over a skills directory as follows:

1. **Discover.** Glob `<skills-dir>/*/SKILL.md`. Skip non-skill entries (e.g. a `_shared/`
   helper dir with no `SKILL.md`).
2. **`ls` before quoting.** `ls` the matched filenames before quoting any into a sub-agent
   prompt — filenames with spaces or odd casing break the prompt otherwise.
3. **Batch.** Roughly **6–8 skills per agent**, using **read-only Explore agents** (read-only
   by construction — they never edit or write any file), each dispatched with an explicit
   cheap-tier pin (`model: sonnet`) — the scan must not inherit an escalated session, or it
   violates the very tier policy it audits.
4. **Dispatch in parallel.** Send a batch's agents in **one message** so they run concurrently.
5. **Same rules per agent.** Each agent's prompt must contain: the absolute `SKILL.md` paths
   in its batch, and the §1 taxonomy (table + tag boundaries) **verbatim** — every batch must
   apply the SAME rules, or the classification drifts per-batch.
6. **Tag.** Each agent, per skill: read its `SKILL.md`, identify every role that performs or
   replaces LLM work (including MECH — mechanically-checkable steps count), tag each role with
   exactly one §1 tag, and return the compact per-skill table (§3).
7. **Collect.** Merge all agent tables into one classification before any downstream use.

Discipline: agents are **read-only, classify-only** — they never edit or write a file.

---

## §3 Classification output shape

Each agent returns, and the merged result keeps, exactly this per-skill shape:

| Skill | Roles (tags) | Notes |
|---|---|---|

No verdict columns. Verdicts are per-direction — the consuming skill adds its own verdict
column(s) when it applies its rules to this table.

---

## §4 What this file deliberately does NOT contain

- **No routing verdict rules**, in either direction — nothing here says which tag routes to a
  cheaper or a stronger model.
- **No routing corrections** (e.g. tier-offload's "three corrections" — those encode a
  direction and live in the consuming skill).
- **No gate-precondition or safety invariants** (those live in `tier-offload`).

Consuming skills add all of the above on top of the neutral classification. Do not re-inline
them here — that re-creates the drift this single source exists to prevent (per
[`code-quality.md § "One source of truth for data-shape constants"`](../rules/code-quality.md)).
When changing the tag set or the §3 output shape, grep all consumers (`tier-offload`,
`tier-escalate`) before landing.
