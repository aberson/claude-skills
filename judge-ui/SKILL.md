---
name: judge-ui
description: Drive a web UI through a defined flow, capture stage screenshots + a structured read-back, and have an independent vision-judge sub-agent render a PASS / FAIL / UNCERTAIN verdict cross-checked against the read-back — turning "look at the screen" UAT from a human task into an agent-judged one, with a mandatory fall-back to human escalation on low confidence. Use when a UAT step needs someone to drive a browser and judge what renders ("does the screen look right?"), or when user-uat's Visual tier delegates here. Project specifics (server bring-up, auth, testids) come from a project adapter. Invoke as "/judge-ui [flow-or-spec] [--adapter <name>] [--dry-run]".
user-invocable: true
---

# UI Judge

> **Judging doctrine:** invariants, archetypes, and the judge↔advisor spectrum live in [`_shared/judge-core.md`](../_shared/judge-core.md) — this skill instantiates them (it is the §10 reference implementation for separate-vision-judge + read-back + escalate).

The generic engine for the **visual tier** of UAT. It drives a real browser through a flow,
captures a screenshot at each stage, and dispatches an **independent vision-judge sub-agent**
that views the pixels, cross-checks them against a structured read-back (API JSON / DB query),
and returns a per-stage verdict with evidence.

The point: "did the screen render correctly?" has always been a human's job. A browser driver
plus a vision model can now *do* most of it — but only safely if the judgment is disciplined.
This skill is that discipline. It is **project-agnostic**: everything project-specific (how to
start the app, how to reach an authed state, which testids to click) comes from a **project
adapter** (e.g. toybox's `/uat-ui`). Without an adapter it runs an inline flow spec you supply.

## When to use / not

- **Use:** a UI flow needs driving + visual judgment — a parent dashboard renders a list, a
  wizard advances through screens, a form's result must look right. Or `/user-uat --ui` routed a
  visual-tier step here. Or a project adapter calls you with a named flow.
- **Don't use** for things a still frame can't judge: **animation/motion, audio/sfx, real-device
  input, or subjective "does it feel right"** — those stay human (a screenshot is one frame; it
  cannot see a countdown tick or hear a sound). Don't use it to *refine* a fuzzy UAT (that is
  `/review-uat`) or to run shell-only checks (that is `/user-uat`'s mechanical tier).

## Invocation

```text
/judge-ui --adapter toybox --flow room-import   # run a named flow from a project adapter
/judge-ui <path-to-flow-spec>                    # run an inline flow spec (no adapter)
/judge-ui --adapter toybox --flow room-import --dry-run   # print the plan + the stages; drive nothing
```

## The flow-spec contract (what a flow must provide)

A flow is the parametrized input the engine drives. A project adapter supplies the first three;
the caller or the adapter supplies the rest.

1. **Bring-up** — how to get the app running + reachable: start command(s), a readiness probe,
   and the base URL. Skipped if the app is already up. *Usually project-specific → adapter.*
2. **Reach state** — how to get from cold to the flow's starting UI state: auth (login / PIN),
   seed fixtures, feature-flag values. *Usually project-specific → adapter.*
3. **Read-back handle** — how to read the ground truth out of band (an authed API call, a DB
   query) so the judge can cross-check pixels against data. *Adapter provides the auth.*
4. **Stages** — an ordered list. Each stage = an **action** (navigate / click / fill), a
   **screenshot** target path, optional **mechanical DOM asserts** (testid present, heading
   text, row count, URL), and an optional **read-back** call.
5. **Rubric** — per-stage natural-language pass criteria for the vision judge, in *observable*
   terms ("review table shows 7 rows; first row name is editable; a Create button is present").
   Borrow these verbatim from a `Verify (human)` block if `/review-uat` produced one.

## The run loop

1. **Ensure the app is up.** Run the adapter's bring-up (or verify an already-running instance
   with the readiness probe). For Windows / port-collision / parallel-session hazards, defer to
   the adapter — it owns the safe bring-up + teardown.
2. **Drive the flow.** Prefer a **parametrized Playwright spec** (it gives DOM asserts *and*
   screenshots in one pass; see toybox's `frontend/playwright/room-import.spec.ts` as the
   reference shape). Run the **mechanical DOM/API asserts FIRST** at each stage — they're cheap,
   deterministic, and they *ground* the screenshot (a green DOM assert + a screenshot beats a
   screenshot alone). Capture each stage's screenshot to the agreed path and call the read-back.
   A mechanical assert failure stops the flow and is itself a FAIL (no vision call needed).
3. **Dispatch the vision-judge sub-agent.** Hand a **separate** agent (Agent tool) the stage
   screenshots + the read-back JSON + the rubric + the flow's intent. It must (a) *view* each
   image, (b) cross-check what it sees against the read-back, (c) return a per-stage verdict
   `PASS / FAIL / UNCERTAIN` with the concrete evidence it used. The judge is independent eyes —
   never the orchestrator grading its own driving.
4. **Resolve the verdict.**
   - Every stage PASS **and** pixels agree with the read-back → **PASS**.
   - Any stage FAIL (with evidence) → **FAIL**.
   - Any stage **UNCERTAIN**, low confidence, or **pixels disagree with the read-back** →
     **escalate to Human** — degrade to today's behavior, present the evidence, ask the
     one-line question. **Never auto-PASS through uncertainty.**
5. **Write the verdict doc** (the durable artifact) and return a structured result to the
   caller. Doc structure — **all six sections always present, even on an early-exit run**:
   scope, environment, per-stage "what the judge saw" (legible observations, not vibes), the
   read-back summary, findings, verdict. On a fail-fast (a mechanical-gate FAIL that never
   reached the vision step), still emit every section — mark the unreached ones explicitly
   ("what the judge saw: not invoked — mechanical gate failed at <stage>"; "read-back: not
   reached — flow stopped") rather than dropping them, and capture a screenshot of the failing
   state to cite as evidence. **Last line is exactly `VERDICT: PASS` / `VERDICT: FAIL` /
   `VERDICT: ESCALATE`.**

## The honesty invariants (do not skip — these are why it's safe)

A vision-judge is an agent grading an agent-rendered surface — the same trap operator UAT
exists to prevent (agents grading agent work codify regressions: toybox G2 / the audit-wire-
shape rule). These five rules keep it honest:

1. **Read-back cross-check is mandatory.** The judge may not PASS on pixels alone — every PASS
   must be corroborated by the API/DB read-back. A pretty screen over a wrong DB is a FAIL.
2. **Low confidence → Human, not PASS.** Uncertainty degrades to escalation. The engine's job is
   to *remove the easy visual checks from the human's plate*, not to fabricate confidence.
3. **Mechanical asserts gate the judge.** Deterministic DOM/API checks run first and fail fast;
   the vision call only judges what they couldn't.
4. **The judge is a separate sub-agent.** Independent eyes. The orchestrator that drove the
   browser does not also render the verdict.
5. **Evidence on every verdict.** Each PASS/FAIL cites the screenshot path *and* the read-back
   value. A verdict with no evidence is a defect (inherited from `/user-uat`).

Side-effecting flows (form submits, real writes, sends) inherit `/user-uat`'s safety gate: tag
them side-effectful, confirm before running, prefer an isolated fixture/DB. The adapter should
run against an isolated store, never the operator's real data.

## Reuse — don't reimplement

`/build-step --ui` already owns app lifecycle + capture primitives:
`dev/.claude/skills/build-step/scripts/capture_evidence.py` (headless Chromium, full-page
screenshots, console/HAR, project-specific `--exercise-cmd`) plus Windows-aware
readiness-polling and `taskkill`/port-kill teardown. Reuse those primitives for capture/teardown
rather than rebuilding the Windows signal-handling. What build-step **lacks** — and what this
skill adds — is the *judgment*: a structured PASS/FAIL verdict against an acceptance rubric.
Capture there; judge here.

## Relationship to other skills

- **`/user-uat`** — its **Visual tier** (`--ui`) delegates here. `user-uat` owns the
  partition + the terse report; `judge-ui` owns the drive + the vision verdict. The
  `UNCERTAIN → Human` fallback feeds straight into `user-uat`'s `Needs you` section.
- **`/review-uat`** — emits the `Verify (visual — vision-judge)` blocks this skill consumes;
  its rubric *is* the per-stage pass criteria. Refine → judge.
- **`/build-step --ui`** — the capture/lifecycle primitives to reuse (above).
- **Project adapters** (e.g. toybox `/uat-ui`) — supply bring-up + auth + the flow library;
  this engine is the project-agnostic half they call.
