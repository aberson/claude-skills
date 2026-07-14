# judge-core — the shared doctrine for judges & advisors

**One source of truth for every skill that renders a verdict, score, or grounded recommendation.** Judge/review/advisor skills MUST reference this file rather than restating its rules in their own prose — the same way skill-grading sources its one canonical prompt from [`grader_prompt.py`](grader_prompt.py) and its contract from [`score-skill.md`](score-skill.md). Drift between a skill's local rules and this doctrine is a defect.

> **Status note:** a doctrine only centralizes maintenance if skills *replace* their restated rules with a one-line pointer here (not add a pointer on top). The three §10 reference implementations (review-deep, review-gauntlet, judge-ui) now carry inbound doctrine pointers; the remaining lever is replacing their locally-restated invariants with pointers and keeping the calibration harness (`calibrate_judge.py`) in the loop. See the workspace's `docs/investigations/judging/07-rubrics-dimensions-and-judge-core-critique.md` §4 and the Wiring status note in §10.

Background, evidence, and the gap analysis that produced this file: the workspace's `docs/investigations/judging/` set. Code-review-specific depth (per-dimension reviewers, evidence/determinism/false-positive specs): the workspace's `docs/investigations/review-agents/` set.

---

## 1. What a "judge" is here

A judge evaluates an artifact and emits a verdict, score, or recommendation. Judges form ONE family on a spectrum whose dial is **how much state the role conditions on**:

```
JUDGE ───────────────────────────────────────────────────────► ADVISOR
verdict     critic        verifier      stateful critic    next-action
on one      (feedback to  (correct/     (Reflexion:        recommendation
output      improve)      incorrect)    memory across      (heavy grounding
(light)                                 episodes)          + iteration state)
```

- **Judge** — backward verdict/score on an existing output (review-deep, review-gauntlet, judge-ui, the skill-eval grader).
- **Critic** — verdict + feedback to improve (review-uat refining a UAT; CriticGPT-style).
- **Verifier** — correctness check, ideally executable/deterministic (build-phase gates, user-uat mechanical tier, judge-ui's DOM asserts).
- **Advisor** — forward-looking, heavily-grounded recommendation of what to do next (Alpha4Gate `improve-bot-advised`/`-triage`, the goblin→`/goal` flow).

**Stance and grounding are separable but correlated:** a heavily-grounded judge can stay backward-looking (a retrieval/rubric-grounded judge is still a judge). But as grounding rises the stance *tends* to flip from verdict to recommendation. **Implication:** an advisor is a judge pushed right and *allowed to recommend* — it needs **more** discipline (§8), not less.

## 2. Pick the archetype (HOW it judges)

| Archetype | Use when | Notes / caveats |
|---|---|---|
| **Executable / ground-truth verifier** | correctness is programmatically checkable (exit code, count, schema, test) | **Prefer over any LLM judge** — deterministic, reproducible, bias-free. The MECH/mechanical-gate tier. |
| **Pointwise / absolute** | objective per-artifact checks (faithfulness, format, policy) | Default LLM-judge mode. Low-cardinality scale (§4), reason-before-score. |
| **Pairwise / preference** | "is A better than B?" — variant selection, subjective quality | More stable than pointwise for subjective tasks. **Always swap-and-tie** (judge both orders; flip ⇒ tie). |
| **Rubric / checklist** | multi-criterion quality against named standards | Grade each criterion in a **separate** call against its **own anchored scale** (§3, §4); aggregate by a fixed rule (§5). |
| **Critique-then-score** | high-accuracy single-artifact grading | Write reasoning/critique *before* the score (G-Eval). The default shape for any LLM verdict. |
| **Jury / cross-family panel** | high-stakes verdicts where bias-cancellation matters | A panel of *family-diverse* models cancels **bias, not shared jailbreak blind spots**. **Augmenting** a strong judge with a *weaker* one (e.g. Claude + local Qwen) only helps in a **cascade/advisory** shape, never as a naive equal vote — see `06-cross-family-judges`. |
| **Adversarial / refuter / debate** | high-severity findings; truth under uncertainty | Spawn a refuter prompted to *kill* the finding, **citing artifact evidence**; keep survivors. Strongest under information asymmetry; tune for precision or it manufactures objections. |

`archetype` (HOW) is **orthogonal** to `dimension` (WHAT, §3) — any method × any dimension is valid (pairwise-on-aesthetics, verifier-on-correctness, pointwise-on-security). When a programmatic verifier exists, it wins; the LLM judge is the fallback for what isn't deterministically checkable.

## 3. Pick the dimensions (WHAT it judges)

A judge's *dimension* is the quality aspect it scores — distinct from its archetype. Borrow from established taxonomies (ISO/IEC 25010; Nielsen usability heuristics; LLM-eval helpful/harmless/honest, faithfulness/relevance/coherence). For this workspace's **code-review** domain the defensible set (detailed per-dimension in the workspace's `review-agents/` investigation set):

> **Correctness** (spec/logic on intended inputs) · **Robustness/Bugs** (failure modes: edge cases, races, leaks, null/boundary) · **Security** · **Performance** · **Test-quality** · **Conventions & Maintainability** · **Plan-conformance**

Rules for a dimension set (perfect MECE is neither achievable nor desirable — engineer toward it as a *pressure*):

1. **Definitions mutually-exclusive** — the dominant rubric failure is overlapping dimensions that double-count/split severity (e.g. *correctness* vs *bugs*: split them as "meets spec" vs "failure modes"). Sharpen definitions until each judge has a crisp, non-redundant job.
2. **Set collectively-exhaustive for the risks that matter** — a *missing* dimension is worse than a duplicate where the cost of a miss is high (security, correctness). Security and performance deserve *owning* lenses, not incidental coverage.
3. **Deliberately keep overlapping lenses for recall** — a real defect surfaced by two independent lenses is more trustworthy; defense-in-depth beats strict orthogonality for expensive misses.
4. **De-duplicate at the findings layer** — assign each finding one **primary-owner** lens and **cross-tag** the rest; collapse the same defect flagged by multiple lenses into one severity-rated item. This buys overlap's recall without inflating the score. (review-deep's `aggregate.py` rules 2 + 7 are the reference implementation.)

## 4. Build the shared rubric (the method)

The scale *number* is an empty container — cross-judge agreement comes from **anchors + worked exemplars + a calibration pass**, not from picking a small integer.

1. **Decompose into independent criteria**; score each separately (no single global score) — kills halo/conflation.
2. **Default to binary (MET/UNMET) per criterion**; escalate to a **3-level named** scale (e.g. *Fully correct / Correct-but-incomplete / Incorrect*) only when a meaningful middle exists. **Avoid 1–10** (LLMs aren't calibrated to consistent scores on broad scales; central-tendency bias). *Default to low cardinality; reserve fine/float scales only for calibrated judges whose extra resolution is validated to add signal (the Tetlock granularity exception — this workspace has none today).*
3. **Anchor every scale point with a concrete behavioral description**, not a bare adjective. The anchor — identical across judges for a given criterion — carries the meaning. A "3" should mean the same thing across all *judges* of one criterion, but need not mean the same across *different* criteria.
4. **Attach 1–2 pre-graded worked examples per scale point** (few-shot anchors) — the frame-of-reference mechanism that gives every judge the same latent picture of each level.
5. **Run a calibration pass before deployment** — all judges score the same sample set; compare; rewrite divergent anchors; repeat.

> *Evidence note:* the "anchors + exemplars + calibration" mechanism is well-grounded; the always-safe lever per the bias-mitigation literature is **CoT/rubric-first scoring**. The Frame-of-Reference effect-size (d≈.77) is a directional analogy from *human-rater* studies, not a measured LLM-judge result; the "0–5 beats 0–10" scale finding is single-study. See the workspace's `07-rubrics-dimensions-and-judge-core-critique.md`.

## 5. The honesty invariants (non-negotiable)

A skill may *strengthen* these; it may not drop one.

1. **Independence — the producer never grades itself.** Spawn a separate sub-agent, or render the verdict one orchestration level up (a Workflow), because **agent nesting is depth-1** — a sub-agent can't spawn its own grader (see [`score_skill.workflow.js`](score_skill.workflow.js) header; [[agent-nesting-depth1-no-self-grade]]).
2. **Evidence on every verdict.** Each finding cites concrete evidence — `file:line` + excerpt, a screenshot path + read-back value, a command + output. No-evidence ⇒ **dropped**, not demoted-to-pass.
3. **Mechanical/deterministic checks gate first.** Cheap deterministic asserts run before any LLM call; a mechanical failure is itself a verdict — no LLM call needed.
4. **Cross-check against ground truth.** Never pass on surface appearance alone — corroborate against the read-back / reference / gold answer. A pretty screen over a wrong DB is a FAIL.
5. **Low confidence → escalate, never auto-pass.** Uncertainty degrades to a human ask (or a meta-judge tier), never a fabricated PASS. Provide an explicit abstain/UNCERTAIN option.
6. **Deterministic aggregation — and the right rule for the shape.** Given the same inputs, the final verdict is reproducible (a script or fixed rule, not orchestrator prose). For **heterogeneous** judge outputs, *type-segregate* rather than force one number:
   - categorical → **majority vote, ties escalate**;
   - graded → **mean + std** (std is the disagreement signal);
   - ranked → **rank fusion** (scale/length-invariant).
   When outputs don't share a decision surface (pass/fail + score + ranking + prose), or judges disagree, **don't aggregate numerically — escalate the raw outputs to one consolidating gate** (mapping a critique to a number discards its reasoning). **Do NOT use reliability-weighted EM / Dawid-Skene on a small correlated panel** — it underperforms plain majority vote there (single-study, mechanism-plausible). Deterministic aggregation **belongs orchestrator-side** — pure parse/aggregate code with no LLM is the *correct* home for it, not a self-grade risk (don't mistake a deterministic reducer for a judge grading itself). *Accepted exception:* a producer that shares a codebase with a **deterministic** matcher is fine when it falls through to a stronger judge on uncertainty and never auto-approves (e.g. toybox's offline QA matcher).

**Parse+aggregate "spine" conformance (document, don't merge).** The workspace has **four** separate-runtime scorers that all walk the same shape; they should *conform* to one spine but stay distinct code. The spine: **extract-JSON-robustly → validate-axes-present → coerce-types → deterministic-aggregate; a fixed verdict enum; parse-failure → `None` (drop, don't crash)**. The four conformers — keep them separate (separate runtimes; goblin's plan explicitly **forbids importing the shared scorer**):

   - goblin `src/goblin/grade.py` (median-of-N + discrimination guard),
   - the workspace `_shared/grader_prompt.py` + `score_skill_absolute.py` (majority-vote + vacuous-TRUE),
   - toybox `src/toybox/ai/rubric.py` (clamp-to-[1,5]),
   - brickomancer `tests/harness/judge.py` (single-dimension).

   **Rule:** document conformance to this spine; do **not** merge the code. The recommended add-on lifted from goblin is the **Discrimination guard** — already in §7; point there, don't duplicate it.
7. **Weak/local models never gate.** A local-offloaded or low-capability verdict is **advisory only**; a stronger GATE consolidates (see the workspace's `tier-offload` skill). The sanctioned way to *use* a weak judge is the **cascade**: it judges first, advisory-only, and *disagreement escalates* to the Claude gate (`06-cross-family-judges`).

## 6. Bias-control checklist (cheap, default-on)

- [ ] **Anchored scale points + 1–2 worked exemplars per point** (the highest-leverage control; §4) — gives every judge the same frame.
- [ ] **Reason before scoring** (critique-then-score) — the only *always-safe* debiasing lever; auditable rationale.
- [ ] **Per-criterion scoring, each with its own anchors** — kills halo/conflation.
- [ ] **Low-cardinality scale** (binary or 3-level named) — broad scales suffer central-tendency bias.
- [ ] **Abstain option** — explicit UNCERTAIN path (invariant 5).
- [ ] **Swap-and-tie** for any pairwise verdict — position bias is real and model-dependent.
- [ ] **Blind / randomized** identity & order where applicable — denies self-preference + slot bias.
- [ ] **Watch verbosity bias** — longer ≠ better.
- [ ] **Cross-family judge/jury** for the highest-stakes verdicts — decorrelates self-preference (esp. on artifacts the judging family also authored).

## 7. Calibration — prove the judge is any good

- **The acceptance precondition:** if **two trained humans can't independently reach the same verdict** from the rubric alone, the *rubric* is the defect, not the judge. Fix the rubric first.
- Keep a small **golden set** of `(input, expected_verdict)` per judge skill (the `evals/golden/` pattern).
- Measure **agreement** (% vs golden, Cohen's κ; **Krippendorff's α** for >2 raters; **Gwet's AC2** under skew) and **position consistency** (does the verdict survive an A-B swap?). Ceiling ≈ inter-human agreement (~80%).
- A judge below threshold is a regression — fix it before trusting it, exactly as a failing skill-eval blocks a skill edit. (The runnable follow-on — a CI-enforced calibration test — is what gives this doctrine teeth; see `04-ideas-and-recommendations.md` B1.)
- **Discrimination guard.** A rubric/grader must *separate* known-good from known-bad on a golden set by a margin — if `good.md` doesn't out-score the `bad_*.md` fixtures, the rubric is non-discriminating (structural-Goodhart) and is **parked, not trusted**. Reference implementations: skill-iterate's goldens check and goblin's inter-judge-spread floor (derive the floor from observed variance, not a magic constant).
- **The mechanized per-commit gate.** [`_shared/calibrate_judge.py`](calibrate_judge.py) (`--mode ci`) operationalizes the Discrimination guard above into a deterministic, zero-live-LLM CI gate: it replays a recorded judge snapshot (`evals/golden/recorded_scores.json` + gold `verdicts.jsonl`) through three checks — **freshness**, **discrimination** (the guard above, mechanized via `verify_goldens`), and **agreement** (recorded verdicts == gold) — and fails closed on any miss. `review-deep` is the first wired judge (see its `## Calibration` section). **Honest scope:** this gate catches regressions in the recorded snapshot + fixture harness (a dropped fixture → fails closed, a non-discriminating snapshot, a mislabeled gold). It replays RECORDED numbers, so it does **NOT** exercise the live judge or live aggregator (a bug introduced into either after the snapshot is invisible until the snapshot is regenerated), and it does **NOT** catch *judge-quality drift*. Detecting a degraded live judge is the **deferred Phase-3 live stochastic kappa sweep** (`calibrate(mode="full")`, currently a `NotImplementedError` stub) — a live LLM call can't be made flake-free, so it must be nightly-alerting, not a per-commit gate.

## 8. Extra discipline for ADVISORS (right end of the spectrum)

- **Separate signal from advice from validation.** Deterministic state signals (e.g. Alpha4Gate's `staleness.py`) are pure & unit-tested; the LLM produces advice; an empirical check validates the outcome.
- **Ground on a stable source of truth**, included explicitly (a principles corpus, the plan, memory) — the advisor scores *against* authority, it doesn't invent it.
- **Iteration memory** — carry what was already tried so the advisor deprioritizes repeats.
- **Gate the action, keep operator agency** — recommend, don't auto-execute irreversible changes; commit only behind an empirical/threshold gate. Workspace default is goal-mode: emit a checkable `/goal "<condition>"` ([[project_goal_model_in_window_continuity]]).
- **Start cheap.** A `triage`-style advisor (classify findings → recommend next action, ~100 lines of grounding) ports to any project; the 1000-line deep advisor needs a domain rubric + state signal + validator.

**Triage taxonomy (the shared classification three skills already use).** review-uat, Alpha4Gate `improve-bot-triage`, and goblin's UAT triage each independently classify items along the same three axes before recommending a next action. For each item decide:

| Axis | Buckets | Routes to |
|---|---|---|
| **action-tier** | agent-doable · human-needed | agent acts vs operator handoff |
| **verify-tier** | mechanical/agent · vision-judge · human | deterministic check vs a vision-judge (`judge-ui`) vs escalation |
| **ambiguity** | clear · needs-clarification | proceed vs escalate-to-clarify |

This is the cheap precursor a future **portable triage advisor** would formalize (extract only after grep-all-consumers; per `08-cross-project-census` §4 it's a P2 spike, taxonomy-prose-first). The three skills can reference this subsection rather than restating it.

## 9. Authoring checklist for a new judge or advisor

- [ ] Reference THIS file; don't restate its rules in local prose.
- [ ] State the **archetype** (§2, HOW) **and** the **dimension(s)** (§3, WHAT); confirm dimensions are orthogonal-by-definition + the set is exhaustive for the risks that matter.
- [ ] Producer ≠ grader (§5.1) — name where the separation happens.
- [ ] Rubric built per §4: criteria decomposed, scale points **anchored + exemplars attached**, passes the two-independent-experts bar (§7).
- [ ] Every verdict cites evidence (§5.2); no-evidence ⇒ dropped.
- [ ] Mechanical checks gate the LLM call (§5.3); ground-truth cross-check defined (§5.4); abstain/escalate path defined (§5.5).
- [ ] Aggregation is deterministic **and typed for the output shape** (§5.6); no reliability-weighted EM on small correlated panels.
- [ ] Any local/weak verdict is advisory; a strong GATE consolidates (§5.7).
- [ ] Bias-control defaults applied (§6); a golden set + agreement metric exists or is planned (§7).
- [ ] Findings de-duplicated via primary-owner + cross-tag (§3.4).
- [ ] (Advisors only) signal/advice/validation separated; grounded on a stable corpus; iteration memory; action gated (§8).

## 10. Where each invariant is already practiced (reference implementations)

- **Independence + deterministic aggregation + primary-owner dedup:** [`review-deep`](../review-deep/SKILL.md) (5 parallel lens sub-agents + `scripts/aggregate.py` rules 2/7).
- **Separate vision-judge + read-back + escalate:** the workspace's `judge-ui` skill (not published here).
- **No-self-grade via Workflow (depth-1):** [`score_skill.workflow.js`](score_skill.workflow.js), [`score-skill.md`](score-skill.md).
- **Independent reproduction (adversarial):** [`user-debug`](../user-debug/SKILL.md) (Explore agent given symptom but not the suspected cause).
- **Local-never-gates + the cascade:** the workspace's `tier-offload` skill; `06-cross-family-judges`.
- **Evidence discipline:** [`review-proof`](../review-proof/SKILL.md).
- **Per-dimension reviewer depth:** the workspace's `review-agents/` investigation set (security, performance, adversarial, evidence, determinism, false-positive budget).
- **Deep advisor (spectrum right end):** Alpha4Gate `improve-bot-advised` (811-line corpus + staleness signal + iteration memory); cheap portable slice: `improve-bot-triage`.

**Wiring status:** the three §10 reference implementations (review-deep, review-gauntlet, and the workspace's judge-ui) each carry an inbound doctrine pointer to this file. Remaining gap: [`review-gauntlet`](../review-gauntlet/SKILL.md) narrates its verdict ladder in prose rather than invoking review-deep's deterministic aggregation directly — bring it fully to that pattern as its own change.
