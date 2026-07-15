# tier-offload inventory — sample output

> Sample produced by `/tier-offload` against a 38-skill `.claude/skills/` set (2026-06-19).
> 7 local-safe slices found (6 live, 1 gated pending a Claude final-judge). This is a realistic
> example of the skill's two artifacts: this inventory + the companion `sample-offload-config.json`.

A read of all 38 workspace skills, classified against the routing rule (authorship / planning /
orchestration / final-gate → Claude; only a *cheap fan-out judge/grader slice* → local;
mechanically-checkable → script). The three corrections were applied: (a) authorship fan-outs
write content → Claude; (b) only the *Style* reviewer lens is cheap, Correctness/Bugs stay Claude;
(c) plan-review/plan-wrap's checklist "sections" are one Claude pass today, not a real fan-out.

## The local surface — only these seven skills have a local slice

| Skill | Local slice (small model) | Everything else → Claude | task_class | Note |
|---|---|---|---|---|
| skill-iterate | structural/rubric grader | brainstorm, saturation gate | `skill-iterate-grader` | best fit — runs all night (the overnight quota case) |
| skill-evolve | per-scenario grader fan-out | mutator, winner gate | `skill-evolve-grader` | grader array is pure parallel scoring |
| review-gauntlet | Style lens (+ mech test-quality) | Correctness, Bugs, aggregator gate | `review-gauntlet-style` | aggregator stays a Claude final judge |
| review-deep | Style lens (already Haiku) | other lenses, gate | `review-deep-style` | smallest lift — tiering already exists |
| build-step | Style reviewer | dev, Correctness, Bugs | `build-step-style` | **gated** — reviewers gate directly today; activates only after a Claude final judge is inserted |
| goblin-suggest | N-judge scoring/voting fan-out | generation, ranking | `goblin-suggest-judge` | rubric scoring |
| context-slim | 3 parallel file-classifiers | synthesis | `context-slim-classifier` | low-stakes classification |

**Gate-preconditions:** `build-step-style` has an unmet `gate-precondition` — its reviewers gate
the merge directly today, so routing the Style lens local would make the weak model part of the
gate (forbidden, Decision 3). It is emitted in the config as `false` (configured but disabled) and
activates only after a Claude final-judge is inserted to consolidate. The other six route to a
non-gating advisory slice and are emitted `true`.

## All-Claude (authorship / planning / single-pass reasoning / orchestration)

plan-init, plan-feature, plan-merge, plan-trim, plan-review, plan-wrap, plan-expedite, build-phase,
build-queue, goblin-do, repo-init, repo-update, skill-eval-setup, user-brainstorm, user-learn,
user-draft, user-pm, user-orient, user-recap, session-wrap, review-proof, review-uat,
memory-distill, research-prospect, test-prune, user-debug.

## No LLM (scriptable / mechanical / doc — nothing to offload)

repo-sync, lesson-harvest, task-handoff, user-uat (mechanical tier; judgment escalates to operator),
claude-oauth-auth.

---

## Next (per-user, NOT done by tier-offload)

For each **live** slice (`true` in the config), wire the skill's grader/Style sub-task to call
`local_judge(task_class="<key>")`. For the **gated** slice (`build-step-style`, `false`), first
insert a Claude final-judge that consolidates the local findings, then flip the config entry from
`false` → `true`. This skill does NOT auto-wire — it only finds and configures the safe slices.
