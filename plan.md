# skill-mesh Multi-Model Execution Plan

**Goal:** Decouple the skill-mesh system from single-provider dependency by adding GPT-5.6 Sol fallback (plus local `code-30b` tertiary fallback), improving resilience against service interruptions while preserving existing Claude-first workflows.

**Scope:** 47 skills ported to GPT (3 explicitly excluded as Claude-native â€” see below). Phased: backbone first, then support/gateways, then specialists.

**Target model:** GPT-5.6 Sol as the default fallback for all skills. Long-term goal is per-skill routing to the best-suited GPT model variant (Sol, Luna, Terra) based on skill family capability profiles â€” that is a post-Phase 5 enhancement once dual-model infrastructure is proven.

**Architecture:** Hybrid â€” unified `SKILL-core.md` (model-agnostic logic) + thin `SKILL-claude.md` and `SKILL-gpt.md` entry points per skill. GPT variants live under `.claude/skills-gpt/<skill-name>/` (sibling to `.claude/skills/`).

**Routing approach (resolved):**
1. **Explicit flag** â€” `--model gpt` on invocation (or per-session config) as primary dispatch.
2. **Health-check fallback** â€” if Anthropic API returns 5xx or times out, auto-retry on GPT-5.6 Sol.
3. **Fail-open** â€” any router error falls back to Claude and never halts.
4. **Future** â€” per-skill soft defaults in `.claude/references/model-mapping.md` (Phase 5+).
5. **Both-clouds-down fallback** â€” if both Anthropic and OpenAI are unavailable, route text-only skills to local `code-30b`; for unsupported classes (vision/sub-agent-heavy), halt with explicit operator-visible error.

**Exit criteria:** At least 40 of 47 in-scope skills have a verified GPT variant; router correctly falls back to Claude on simulated GPT outage and vice versa; cost-per-invocation data exists for all Phase 2 backbone skills; CLAUDE.md updated with multi-model conventions.

## Builder Quickstart

1. Configure credentials: export Anthropic + OpenAI keys using the same env-var pattern already used by this workspace; set local `code-30b` endpoint config.
2. Confirm router wiring: run `pwsh .claude/lib/skill-router.ps1 --model gpt --skill plan-init --dry-run`.
3. Run baseline calibration: execute the Step 6 harness for `plan-init`, `build-step`, and `review-gauntlet`; verify `documentation/multi-model/calibration-baseline.json` is produced.
4. If cloud APIs are unavailable, confirm fallback chain behavior: Claude â†” GPT retry, then `code-30b` for text-only lanes, explicit halt for unsupported lanes.

---

## Claude-Native Skills (excluded from GPT porting)

| Skill | Reason |
|-------|--------|
| claude-oauth-auth | Uses Claude-specific OAuth token flow â€” no GPT equivalent |
| context-slim | Claude runtime feature (context compaction) â€” not applicable to GPT |
| judge-motion | GPT has materially weaker video/motion understanding; accept Claude-only for now. Re-evaluate when GPT video capabilities mature. |

---

## Phase 1: Foundation

### Step 1: Build full skill inventory and dependency graph

- **Problem:** No formal DAG of which skills call which exists. Without it we cannot identify which conversions are independent vs. require coordinated changes, or which are blocked on dependencies being ported first.
- **Type:** code
- **Issue:** #6
- **Files:** `.claude/skills/` (read-only scan), `documentation/multi-model/DEPENDENCIES.md` (new)
- **Produces:** `DEPENDENCIES.md` with (a) a table of all 50 skills: family, Claude-specific API usage (Y/N), sub-agent spawning (Y/N), filesystem dependency (Y/N), portability rating (Easy/Medium/Hard/Claude-native); (b) a skillâ†’skill call dependency DAG in text or mermaid; (c) the 3 Claude-native exclusions confirmed.
- **Done when:** DEPENDENCIES.md exists covering all three items above.
- **Flags:** --reviewers code

### Step 2: Approve routing and fallback design

- **Problem:** The routing approach is documented in the plan preamble but needs operator confirmation before the router is built.
- **Type:** operator
- **Issue:** #7
- **Done when:** Operator has confirmed or amended the routing approach (explicit flag â†’ health-check fallback â†’ fail-open, plus both-clouds-down behavior to local `code-30b` for text-only skills, as in the preamble). Decision annotated in `documentation/multi-model/Framework-Design.md` Â§1 before Step 3 begins.

### Step 3: Write hybrid framework design document

- **Problem:** No documented contract exists for the SKILL-core / SKILL-claude / SKILL-gpt split â€” what belongs in each, how they compose, and what the entry-point invocation contract looks like.
- **Type:** code
- **Issue:** #8
- **Files:** `documentation/multi-model/Framework-Design.md` (new)
- **Produces:** Framework-Design.md covering: (a) entry-point template for SKILL-core/claude/gpt; (b) split rule (model-agnostic logic â†’ core; model-specific prompt tuning + output normalization â†’ entry points); (c) escalation contract (GPT fails/low-quality â†’ automatic single retry on Claude, then surface to operator); (d) rollback design (bad GPT result mid-build-phase â†’ fail-open to Claude, log to telemetry); (e) router error behavior (fail-open to Claude, never halt); (f) API key storage approach (env vars consistent with existing Anthropic key pattern); (g) per-session spend ceiling mechanism; (h) both-clouds-down policy (local `code-30b` path for text-only skills and explicit halt conditions for unsupported lanes).
- **Done when:** Framework-Design.md exists covering all eight items.
- **Flags:** --reviewers code

### Step 4: Set up directory structure and router skeleton

- **Problem:** No `.claude/skills-gpt/` directory or `skill-router.ps1` exists. File placement must be resolved: skills live under `.claude/skills-gpt/` (not repo root `/skills-gpt/`), consistent with workspace conventions.
- **Type:** code
- **Issue:** #9
- **Files:** `.claude/skills-gpt/README.md` (new), `.claude/lib/skill-router.ps1` (new), `.claude/references/model-mapping.md` (new stub)
- **Produces:** (a) `.claude/skills-gpt/README.md` explaining structure and conventions; (b) `skill-router.ps1` with argument parsing (`--model`, `--skill`, `--fallback-model`), health-check stub, fail-open Claude fallback, local `code-30b` tertiary fallback for text-only skills, telemetry call stub, and explicit exit codes (`0` = success on requested model, `1` = skill error, `2` = fallback model used successfully, `3` = both cloud providers failed and no supported local fallback path exists); (c) `model-mapping.md` stub with column headers (skill, default-model, claude-capable, gpt-capable, local-capable, notes).
- **Done when:** Directory and files exist; router parses `--model gpt` and `--model claude`; fail-open fallback returns control to Claude on any router error; local `code-30b` fallback is attempted when both cloud providers are unavailable and the skill is local-capable; `skill-router.ps1` passes a basic invocation smoke test.
- **Flags:** --reviewers code

### Step 5: Configure API credentials and cost safeguards

- **Problem:** The router needs OpenAI credentials alongside Anthropic credentials. No key storage, rotation strategy, or spend-ceiling safeguards exist for OpenAI.
- **Type:** operator
- **Issue:** #10
- **Done when:** OpenAI API key is stored using the same secrets mechanism as the Anthropic key (env var or secrets file); a per-session spend ceiling is configured (hard-stop threshold documented and wired); approach documented in Framework-Design.md Â§2; credentials verified by running a minimal test call through `skill-router.ps1 --model gpt --skill plan-init --dry-run`.

### Step 6: Build calibration test harness and capture pilot baseline

- **Problem:** No test harness exists to compare skill output quality between Claude and GPT. Without baseline metrics, there is no way to tell whether a GPT port meets quality bar.
- **Type:** code
- **Issue:** #11
- **Files:** `.claude/lib/calibration/` (new), `documentation/multi-model/calibration-baseline.json` (new)
- **Produces:** (a) Harness that takes (skill, input-prompt, expected-output-spec) and runs on both models, recording (tokens, latency-ms, cost-usd, pass/fail verdict); (b) quality methodology: deterministic outputs (exit codes, counts, structured JSON) use automated diff; prose outputs (plans, reviews) use a section-coverage rubric checklist; (c) baseline metrics for 3 pilots: plan-init, build-step, review-gauntlet.
- **Done when:** Harness runs against both models (requires Step 5 credentials); baseline JSON exists with metrics for all 3 pilots; quality methodology documented.
- **Flags:** --reviewers code

---

## Phase 2: Backbone Skills

### Step 7: Port plan-init (pilot â€” validate framework)

- **Problem:** plan-init is the entry point to the entire planning pipeline. Porting it first validates the SKILL-core/SKILL-gpt split framework on a real, frequently-used skill before scaling to 40+ others.
- **Type:** code
- **Issue:** #12
- **Files:** `.claude/skills-gpt/plan-init/SKILL-core.md` (new), `.claude/skills-gpt/plan-init/SKILL-gpt.md` (new), `.claude/skills/plan-init/SKILL-claude.md` (new thin wrapper)
- **Done when:** All three files exist; `plan-init --model gpt` produces a structurally valid plan.md covering all 7 conversation phases on a test greenfield project; calibration harness passes on the pilot rubric; any framework gaps found are fed back to Framework-Design.md before Step 8 begins.
- **Flags:** --reviewers code

### Step 8: Port plan-feature, plan-review, plan-wrap

- **Problem:** These three skills form the backbone of the plan pipeline with plan-init and are the most frequently invoked after it.
- **Type:** code
- **Issue:** #13
- **Files:** `.claude/skills-gpt/plan-feature/`, `.claude/skills-gpt/plan-review/`, `.claude/skills-gpt/plan-wrap/` (new)
- **Done when:** All three have SKILL-core.md + SKILL-gpt.md; each produces correct output on a test input via `--model gpt`; calibration harness passes for all three.
- **Flags:** --reviewers code

### Step 9: Port plan-redline, plan-expedite, plan-merge, plan-trim

- **Problem:** plan-redline and plan-expedite complete the post-init pipeline chain; plan-expedite specifically chains plan-review â†’ plan-wrap â†’ repo-sync â†’ session-wrap and must work cross-model end-to-end.
- **Type:** code
- **Issue:** #14
- **Files:** `.claude/skills-gpt/plan-redline/`, `.claude/skills-gpt/plan-expedite/`, `.claude/skills-gpt/plan-merge/`, `.claude/skills-gpt/plan-trim/` (new)
- **Done when:** All four have SKILL-core.md + SKILL-gpt.md; plan-expedite chain runs successfully via `--model gpt` on a test plan; calibration passes for all four.
- **Flags:** --reviewers code

### Step 10: Port build-step

- **Problem:** build-step is the atomic execution unit. It must work on GPT before build-phase (the orchestrator) can be ported. Halt contract must trigger identically.
- **Type:** code
- **Issue:** #15
- **Files:** `.claude/skills-gpt/build-step/` (new)
- **Done when:** SKILL-core.md + SKILL-gpt.md exist; a single test step (code generation + review gate) runs via `--model gpt`; simulated test-count regression halts correctly; simulated typecheck error halts correctly; calibration passes.
- **Flags:** --reviewers code

### Step 11: Port build-phase

- **Problem:** build-phase is the primary orchestrator with a complex halt contract (5 halt classes + 3 defect-of-input classes). All halt classes must trigger identically on GPT.
- **Type:** code
- **Issue:** #16
- **Files:** `.claude/skills-gpt/build-phase/` (new)
- **Done when:** SKILL-core.md + SKILL-gpt.md exist; a 2-step test phase runs end-to-end via `--model gpt`; all 5 halt classes verified to fire on simulated inputs; quality gate parity confirmed via calibration harness.
- **Flags:** --reviewers code

### Step 12: Port build-queue

- **Problem:** build-queue dispatches multiple phases in sequence. Logic is mostly orchestration but depends on build-phase working correctly (Step 11 must be done first).
- **Type:** code
- **Issue:** #17
- **Files:** `.claude/skills-gpt/build-queue/` (new)
- **Done when:** SKILL-gpt.md exists; build-queue correctly dispatches a 2-phase queue via `--model gpt`; calibration passes.
- **Flags:** --reviewers code

### Step 13: Port task-handoff and session-wrap

- **Problem:** These two skills manage session state and context transitions via filesystem checkpoints and hooks. The hook infrastructure is model-agnostic but must be verified to work correctly with GPT-routed sessions.
- **Type:** code
- **Issue:** #18
- **Files:** `.claude/skills-gpt/task-handoff/`, `.claude/skills-gpt/session-wrap/` (new)
- **Done when:** Both have SKILL-core.md + SKILL-gpt.md; task-handoff `--loop` correctly writes a session checkpoint when invoked via `--model gpt`; session-wrap correctly triages context and emits the right route; hook infrastructure verified to work regardless of routing model.
- **Flags:** --reviewers code

### Step 14: Reconcile skill-router with model-tiering.md

- **Problem:** `.claude/references/model-tiering.md` already defines when to use which Claude model tier. The new router and `model-mapping.md` must not duplicate or contradict it.
- **Type:** code
- **Issue:** #19
- **Files:** `.claude/references/model-tiering.md` (update), `.claude/references/model-mapping.md` (update), `.claude/lib/skill-router.ps1` (update)
- **Done when:** model-tiering.md remains the authority on Claude model selection; model-mapping.md adds only the GPT-variant column; no contradictions between the two files; skill-router.ps1 consults model-mapping.md for per-skill GPT model overrides.
- **Flags:** --reviewers code

### Step 15: Update workspace CLAUDE.md for multi-model

- **Problem:** The workspace CLAUDE.md has no mention of `.claude/skills-gpt/`, the router, or multi-model invocation conventions. Any agent or operator reading CLAUDE.md cold cannot discover the GPT path.
- **Type:** code
- **Issue:** #20
- **Files:** `CLAUDE.md` at workspace root (update â€” Skills section only)
- **Done when:** CLAUDE.md documents: location of `.claude/skills-gpt/`, how to invoke a skill with `--model gpt`, the router location (`.claude/lib/skill-router.ps1`), and a pointer to the multi-model guide (`documentation/multi-model/MULTI_MODEL_GUIDE.md`).
- **Flags:** --reviewers code

### Step 16: Backbone integration smoke test

- **Problem:** Individual skill ports have been verified in isolation but the end-to-end pipeline â€” plan-init â†’ plan-review â†’ plan-wrap â†’ plan-expedite â†’ build-phase (single step) â€” has not been run cross-model.
- **Type:** operator
- **Issue:** #21
- **Done when:** Operator has run the full planningâ†’build pipeline on a small test project using `--model gpt`; pipeline completes without unintended halts; Claude fallback works when GPT endpoint is simulated unavailable (mock 503 or key override); findings written to `documentation/multi-model/backbone-smoke-results.md`.

---

## Phase 3: Support & Gateway Skills

### Step 17: Port user-gateway, user-draft, user-debug

- **Problem:** Three high-frequency user-facing entry points. user-debug is especially important for resilience â€” when skills fail on either model, it is the first tool reached for.
- **Type:** code
- **Issue:** #22
- **Files:** `.claude/skills-gpt/user-gateway/`, `.claude/skills-gpt/user-draft/`, `.claude/skills-gpt/user-debug/` (new)
- **Done when:** All three have SKILL-core.md + SKILL-gpt.md; test invocations via `--model gpt` produce correct routing/output; calibration passes.
- **Flags:** --reviewers code

### Step 18: Port user-uat, user-walkthrough, user-shakedown

- **Problem:** UAT and walkthrough skills manage human-in-the-loop verification flows. Model-agnostic in logic; need output-format normalization for GPT's more verbose CoT style.
- **Type:** code
- **Issue:** #23
- **Files:** `.claude/skills-gpt/user-uat/`, `.claude/skills-gpt/user-walkthrough/`, `.claude/skills-gpt/user-shakedown/` (new)
- **Done when:** All three have SKILL-core.md + SKILL-gpt.md; calibration passes for each.
- **Flags:** --reviewers code

### Step 19: Port remaining user/* skills

- **Problem:** Eight lower-stakes user interaction skills (user-pm, user-project, user-orient, user-wrap, user-afterparty, user-brainstorm, user-lavishify, user-learn) complete the user/* family.
- **Type:** code
- **Issue:** #24
- **Files:** `.claude/skills-gpt/user-pm/`, `.../user-project/`, `.../user-orient/`, `.../user-wrap/`, `.../user-afterparty/`, `.../user-brainstorm/`, `.../user-lavishify/`, `.../user-learn/` (new)
- **Done when:** All eight have SKILL-gpt.md; at least three spot-checked via `--model gpt` with passing output; calibration records exist for spot-checked skills.
- **Flags:** --reviewers code

### Step 20: Port review-gauntlet and review-deep

- **Problem:** Highest quality-bar review skills. judge-core.md honesty invariants (independence, evidence on every verdict, deterministic aggregation) must hold identically on GPT.
- **Type:** code
- **Issue:** #25
- **Files:** `.claude/skills-gpt/review-gauntlet/`, `.claude/skills-gpt/review-deep/` (new)
- **Done when:** Both have SKILL-core.md + SKILL-gpt.md; a test diff reviewed via `--model gpt` produces evidence-backed findings (zero evidence-free verdicts); deterministic aggregation produces the same verdict for the same input across 3 runs; calibration passes.
- **Flags:** --reviewers code

### Step 21: Port review-uat, review-proof

- **Problem:** Remaining review-family skills. Lower complexity than review-deep but need verification of GPT output format consistency.
- **Type:** code
- **Issue:** #26
- **Files:** `.claude/skills-gpt/review-uat/`, `.claude/skills-gpt/review-proof/` (new)
- **Done when:** Both have SKILL-gpt.md; test invocations via `--model gpt` produce correctly structured output; calibration passes.
- **Flags:** --reviewers code

### Step 22: Port repo-sync, repo-update, repo-init

- **Problem:** Repo management skills use GitHub CLI calls and filesystem writes. Model-agnostic in logic but need verification that GPT-routed invocations do not break the gh/git command sequences.
- **Type:** code
- **Issue:** #27
- **Files:** `.claude/skills-gpt/repo-sync/`, `.claude/skills-gpt/repo-update/`, `.claude/skills-gpt/repo-init/` (new)
- **Done when:** All three have SKILL-gpt.md; repo-sync runs via `--model gpt` on a test repo and produces correct issue bodies; calibration passes.
- **Flags:** --reviewers code

---

## Phase 4: Specialist Skills

### Step 23: Port judge-ui with vision rubric recalibration

- **Problem:** judge-ui uses a vision model to judge screenshots. GPT-4V-class vision and Claude's vision models have different artifact-reading behavior â€” the rubric anchors from judge-core.md Â§4 need recalibration before use on GPT.
- **Type:** code
- **Issue:** #28
- **Files:** `.claude/skills-gpt/judge-ui/SKILL-core.md`, `.claude/skills-gpt/judge-ui/SKILL-gpt.md`, `.claude/skills-gpt/judge-ui/calibration-notes.md` (new)
- **Done when:** SKILL-core.md and SKILL-gpt.md exist; rubric recalibration pass run (same 3 reference screenshots judged by both Claude and GPT; anchor descriptions updated where GPT diverges; swap-and-tie test run to check pairwise stability); judge-ui runs via `--model gpt` and returns PASS/FAIL/UNCERTAIN with screenshot evidence; calibration-notes.md documents GPT-specific divergences.
- **Flags:** --reviewers code

### Step 24: Port tier-offload, tier-escalate, research-prospect

- **Problem:** These skills spawn sub-agents or delegate to other model tiers. GPT's sub-agent/Actions API is structurally different from Claude's. Need to verify or redesign sub-agent spawning â€” if GPT cannot support the pattern, these skills stay Claude-native with a documented reason.
- **Type:** code
- **Issue:** #29
- **Files:** `.claude/skills-gpt/tier-offload/`, `.claude/skills-gpt/tier-escalate/`, `.claude/skills-gpt/research-prospect/` (new)
- **Done when:** All three have SKILL-gpt.md with explicit notes on sub-agent spawning limitations; tier-offload and tier-escalate either work via GPT or are marked Claude-native with justification; research-prospect works via `--model gpt`; calibration passes for whichever skills are ported.
- **Flags:** --reviewers code

### Step 25: Port skill-evolve, skill-iterate, skill-eval-setup

- **Problem:** Meta-skills that spawn agents for skill improvement and evaluation. Agent nesting behavior differs across models and needs explicit testing.
- **Type:** code
- **Issue:** #30
- **Files:** `.claude/skills-gpt/skill-evolve/`, `.claude/skills-gpt/skill-iterate/`, `.claude/skills-gpt/skill-eval-setup/` (new)
- **Done when:** All three have SKILL-gpt.md; skill-eval-setup runs end-to-end via `--model gpt` on a test skill; agent-nesting limitations documented.
- **Flags:** --reviewers code

### Step 26: Port memory-distill, lesson-harvest, observatory-doctor

- **Problem:** Observation and learning skills. Mostly filesystem reads and prose generation â€” low model sensitivity, straightforward to port.
- **Type:** code
- **Issue:** #31
- **Files:** `.claude/skills-gpt/memory-distill/`, `.claude/skills-gpt/lesson-harvest/`, `.claude/skills-gpt/observatory-doctor/` (new)
- **Done when:** All three have SKILL-gpt.md; spot-check via `--model gpt` produces correct output; calibration passes.
- **Flags:** --reviewers code

### Step 27: Port goblin-do, goblin-suggest, test-prune, and remaining niche skills

- **Problem:** Lower-frequency specialist skills. Port with spot-check verification against real project workloads.
- **Type:** code
- **Issue:** #32
- **Files:** `.claude/skills-gpt/goblin-do/`, `.../goblin-suggest/`, `.../test-prune/` (new); any remaining unported skills from inventory
- **Done when:** All three named skills have SKILL-gpt.md; spot-check on a real project workload passes for at least goblin-do and goblin-suggest; calibration records exist; total ported skill count is at least 40 of 47.
- **Flags:** --reviewers code

---

## Phase 5: Integration & Shipping

### Step 28: Write multi-model operator guide and troubleshooting runbook

- **Problem:** No documentation exists for operators on when to use which model, known divergences, cost/latency tradeoffs, or how to troubleshoot cross-model failures.
- **Type:** code
- **Issue:** #33
- **Files:** `documentation/multi-model/MULTI_MODEL_GUIDE.md` (new), `documentation/multi-model/TROUBLESHOOTING.md` (new)
- **Produces:** (a) MULTI_MODEL_GUIDE.md: when to use `--model gpt` vs Claude, known divergences per skill family, cost/latency tradeoffs, how to add a new skill to the GPT portfolio, version pinning strategy for GPT model names (pin to explicit version IDs; upgrade path requires re-running calibration harness); (b) TROUBLESHOOTING.md: common failure modes and fixes.
- **Done when:** Both documents exist and cover all items above.
- **Flags:** --reviewers code

### Step 29: Build cost and performance telemetry

- **Problem:** No mechanism exists to track which skills are faster or cheaper on which model, or to detect quality regressions after GPT model version changes.
- **Type:** code
- **Issue:** #34
- **Files:** `.claude/lib/telemetry/` (new), `documentation/multi-model/telemetry-schema.md` (new)
- **Produces:** (a) Telemetry log writer: appends (timestamp, skill, model, tokens-in, tokens-out, latency-ms, cost-usd, verdict) to a local JSONL file per invocation; (b) Summary script: reads JSONL and prints per-skill model comparison table; (c) Schema documented in telemetry-schema.md.
- **Done when:** Router calls telemetry writer on every invocation; summary script produces readable output from test data; schema documented.
- **Flags:** --reviewers code

### Step 30: End-to-end fallback smoke test

- **Problem:** The full system â€” GPT-5.6 Sol as primary, Claude as fallback â€” has never been run end-to-end with real service interruption simulation.
- **Type:** operator
- **Issue:** #35
- **Done when:** Operator has run the full pipeline on a real project using `--model gpt`; simulated OpenAI outage (env var key override) verifies fail-open fallback to Claude completes the run; simulated Anthropic outage verifies GPT-only path completes; telemetry log shows entries for both model paths; findings written to `documentation/multi-model/e2e-smoke-results.md`.

### Step 31: Annotate all ported SKILL.md files with multi-model footer

- **Problem:** Operators reading the original `.claude/skills/<name>/SKILL.md` files have no indication that a GPT variant exists or how it differs.
- **Type:** code
- **Issue:** #36
- **Files:** All 47 in-scope `.claude/skills/<name>/SKILL.md` files (append footer only â€” 2â€“3 lines each)
- **Done when:** Each in-scope SKILL.md has a `## Multi-model` footer section noting: GPT variant path, any known divergences (or "None identified").
- **Flags:** --reviewers code

### Step 32: Final health check and exit gate

- **Problem:** Need a verifiable exit gate against the plan's success criteria before declaring done.
- **Type:** operator
- **Issue:** #37
- **Done when:** (a) `.claude/skills-gpt/` contains at least 40 of 47 in-scope skills with SKILL-gpt.md; (b) calibration baseline shows passing quality for all Phase 2 backbone skills; (c) router fallback verified (Step 30 complete); (d) CLAUDE.md updated (Step 15 complete); (e) telemetry log has data from at least one real project run; (f) operator sign-off recorded in `documentation/multi-model/exit-gate.md`.

---

## Risk Mitigation & Non-Negotiables

### Hard requirements (must be identical on both models)
1. **Halt contract** (build-phase, build-step) â€” all 5 halt classes + 3 defect-of-input classes trigger identically (reference pointer acceptable: `.claude/skills/build-phase/SKILL.md`, Halt contract section).
2. **Judge-core honesty invariants** â€” evidence on every verdict, independence, deterministic aggregation (judge-core.md Â§5).
3. **Deterministic mechanical checks gate first** â€” exit codes, test counts, type error counts run before any LLM call, on both models.
4. **Escalation logic** â€” low-confidence verdicts escalate on both models; auto-pass is never acceptable.
5. **Fail-open router** â€” any router error falls back to Claude, never halts.

### Known and accepted divergences
1. **Latency** â€” accept variance; document in telemetry.
2. **Reasoning style** â€” GPT CoT is more verbose; output normalization in SKILL-gpt.md handles this where format matters.
3. **Vision tasks** â€” judge-ui rubric recalibration (Step 23) handles GPT-4V vs Claude vision differences.
4. **Sub-agent spawning** â€” tier-offload/tier-escalate may stay Claude-native if GPT cannot support the pattern (document in Step 24).
5. **Motion/animation** â€” judge-motion stays Claude-native (see excluded skills table).
6. **Partial rollout** â€” during the port, invoking `--model gpt` on a skill with no GPT variant yet must fail-open to Claude with a logged warning, not error. Router handles this via `model-mapping.md` lookup (Step 4).

---

## Execution Timeline

- **Phase 1 (Foundation, Steps 1â€“6):** 2 weeks (~12 hrs)
- **Phase 2 (Backbone, Steps 7â€“16):** 3 weeks (~22 hrs)
- **Phase 3 (Support, Steps 17â€“22):** 2 weeks (~14 hrs)
- **Phase 4 (Specialists, Steps 23â€“27):** 3 weeks (~18 hrs)
- **Phase 5 (Integration, Steps 28â€“32):** 1 week (~8 hrs)

**Total:** ~11 weeks, ~74 hours of focused work (part-time).
