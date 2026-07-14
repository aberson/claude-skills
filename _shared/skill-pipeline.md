# Skill pipeline — the routing web

This file is the routing web: the 8 rails an operator fragment can land on (entry
condition + skill chain), the re-route edges between them, and the re-route contract.
It is the ONE owner of the rails and of the `re-route:` line format — `/user-gateway` consults this web to route intake fragments, and rail
skills cite this section; no skill hardcodes its own routing table.

---

## The 8 rails

Entry condition = what the operator's fragment sounds like.

| Rail | Sounds like | Chain |
|---|---|---|
| **bug** | "X is broken / erroring / behaving wrong" — a symptom in hand | `/user-debug --symptom '...'` |
| **do** | "just do X" — a resolved atom / small concrete task | `/goblin-do` (atoms come from `/goblin-suggest`) |
| **plan** | "add / build capability X" — multi-step work needing steps + review | `/plan-feature` (or `/plan-init` for a brand-new project) → `/plan-expedite` → `/build-phase` → `/repo-update` (the build rail — detail below) |
| **investigate** | "what's true about X? why does X happen?" — a question, not yet work | `/deep-research` for external/multi-source; an Explore-agent sweep for codebase-local questions |
| **verify** | "does X actually work? / I don't trust X" — distrust without a reproducible symptom | `/review-uat` (refine a fuzzy block) / `/user-uat` (mechanical tier) / `/user-shakedown` (autonomous closure) / `/user-walkthrough` (attended) — four-mode detail below |
| **trim** | "the plan feels bloated / what can we cut" — plan-borne cruft-smell | `/plan-trim` (plan documents only; non-plan cruft-smell routes **investigate** first — assess, then `investigate→plan` or `investigate→do`) |
| **decide** | "should we do A or B?" — an operator-only choice | surfaced-only: parked with the open question stated; never ground through autonomously |
| **draft** | "here are rough thoughts" — wants a usable prompt or goal, not work done | `/user-draft` → `/goal` |

**Tiebreak:** when a fragment plausibly fits two rails, pick the rail with the cheaper
commitment and let a re-route edge correct it. The common tie — **bug vs verify** — splits
on evidence: a reproducible symptom in hand → **bug**; distrust without one → **verify**
(and `verify→bug` upgrades it the moment a check fails).

---

## Re-route edges (9)

A rail is a starting guess, not a cage. The sanctioned edges, each with its trigger:

- **do→plan** — the atom's scope grows past a small concrete task mid-execution.
- **do→bug** — the thing being improved turns out to be broken.
- **bug→plan** — diagnosis concludes the symptom is not a defect; the ask is designed, multi-step work.
- **investigate→plan** — findings imply real multi-step work.
- **investigate→do** — findings imply one small concrete action.
- **plan→trim** — the plan has accreted cruft; cut before building.
- **plan→do** — scoping collapses the "feature" to one small concrete action.
- **verify→bug** — verification fails; the failing check is now a symptom in hand.
- **any→decide** — an operator-only choice surfaces; park it, never ground through.

---

## Re-route contract (ONE owner: this section)

When a rail skill discovers mid-run that the work is on the wrong rail, it:

1. **Emits one standard line** — format (owned here; skills cite it, never restate it):
   `re-route: <from-rail> → <to-rail> — <one-clause reason>`
2. **Emits the seed for the correct rail** — the `/plan-feature` seed, the
   `/user-debug --symptom` line, the parked decision question, etc.
3. **Writes back to the intake ledger when one exists**
   ([`intake-engine.md`](intake-engine.md)): the row's status stays
   `routed`, with a disposition note recording the re-route.
4. **STOPS** instead of grinding through on the wrong rail.

`/goblin-do`'s small→big handoff — a `big` atom gets the `/plan-feature` seed + the
build-rail next step printed, then the skill deliberately stops — is the codified
template for this contract.

---

## The build rail (plan) in detail

First-time setup: `/repo-init` once before first `/plan-expedite`.

```
/plan-init  or  /plan-feature     Plan: produce plan.md with build steps
        │
        ▼
/plan-expedite                      Autonomous prep: chains plan-review --autofix → plan-wrap --autofix → repo-sync → task-handoff --next-task as one unattended pre-flight before /build-phase (--new-window: durable task-handoff --next-task write, then /session-wrap --end renders handoff-prompt.md + the Pick-up-here block)
        │
        ▼
/build-phase --plan <path>        Build: run each step via /build-step
        │                           └─ /build-step (single step, configurable)
        ▼
/repo-update                      Ship: commit, update docs, push
```

Task state schema (write-as-you-go): `.claude/references/task-state-schema.md` (workspace reference, not published in this mirror) — field definitions, write discipline, path resolution contract, lifecycle.

---

## Review routing (post-#227)

`/review-gauntlet` is the **lean profile over `/review-deep`'s engine** — same code
lenses and deterministic aggregation, terse PASS / NEEDS-WORK verdict, no JSON sidecar.
`/build-step` carries a `--reviewers deep` lane that dispatches `/review-deep` directly
for high-stakes steps; `/plan-review` §27 routes those steps at plan time.

---

## Session transitions & orientation

- `/session-wrap` — the transition front door: triages (context signal, task boundary,
  git state, armed `/goal`), announces one of 3 routes, then acts: `continue` /
  `clear-next` / `end-window`. `--advise` is the read-only variant: verdict banner
  (adds `SAFE TO CLOSE`) + loss report, never acts.
- `/user-wrap` — the return-moment front door ("sitting back down — keep going or
  close?"): orients, delegates the verdict to `/session-wrap --advise`, re-presents its
  banner + loss report, acts per verdict.
- `/task-handoff` — the checkpoint library orchestrators call (`--loop [--no-commit]`,
  `--next-task`, `--resume`; `--end` delegates to session-wrap).
- `/user-orient` — **session axis** (this thread's state; `--quick` tier = lightweight
  three-section summary) vs `/user-pm` — **project axis** (plan+git-derived shipped /
  planned / next / cuttable).

---

## Post-build operator acceptance (verify rail detail)

Four modes: `/user-uat` EXECUTES an already-clear UAT block; `/review-uat` REFINES a fuzzy one; `/user-walkthrough` lets the operator DRIVE exploration of a just-built feature (agent answers from source, fixes small, logs big, marks coverage); `/user-shakedown` AUTONOMOUSLY CLOSES the shared UAT ledger to zero open items (designed to run armed under `/goal`). The walkthrough/shakedown pair share one ledger contract: the workspace's `shakedown-engine.md` reference (not published in this mirror).

---

## Supporting skills

`/review-proof`, `/test-prune`, `/skill-eval-setup`, `/skill-iterate`,
`/goblin-suggest` (produces the atoms `/goblin-do` consumes), `/memory-distill`,
`/user-brainstorm`, `/user-learn`, `/context-slim`, `/lesson-harvest`.

`/build-queue --queue <path>` — meta-orchestrator: drains a queue of N pending plans, invokes `/plan-expedite` + `/build-phase` per item, parks halts as GitHub issues (does not retry), polls a kill-switch file between items, emits a morning summary.

`/skill-evolve --skill <name> --variants <path-or-inline>` — A/B-tests N variant mutations of a skill in parallel worktrees, scored against the skill's existing `evals/` suite. Winner branch is pushed and a `gh pr create` command is printed (no auto-PR); losers are cleaned up and analyzed under `docs/investigations/skill-evolve/`. Requires `/skill-eval-setup` to have set up the target skill's evals first.

dev-observatory hooks (additive, degradable — the control plane works on best-guess without them): `/plan-init` registers a new owned project (`observatory register`); `/repo-update` refreshes verbs/ports + tasks (`observatory sync`); `/build-step --ui` port pre-flight (`observatory ports`); `/user-pm` gains a `--json` mode; `/plan-review` + `/plan-wrap` check a scrapable goal + port collisions. Full contract: `.claude/rules/descriptor-contract.md` (workspace rule).
