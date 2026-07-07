# score-skill — composite skill-scoring procedure

Shared scoring fragment referenced by `/skill-iterate` Phase 2 Step D and any
other skill-pipeline tooling that needs a single, reproducible scoring axis
for a SKILL.md. Composes two scoring axes — deterministic structural metrics
(Step 3 of the hill-climbing plan) and LLM-driven absolute per-assertion
grading (SIHC.2 Option A) — into one composite score in `[0.0, 1.0]`.

NOTE on history: composite mode previously used the differential pair
grader (Step 4 of the SIHC.1 plan) as its second axis. SIHC.2 Option A
(decision 2026-05-26) replaces differential with the absolute grader for
prose-skill hill-climbing because absolute produces a tractable
assertion-targeted gradient that differential's "is A better than B?"
verdicts could not. Differential code is preserved (see §Differential-only
mode) for possible Option B revisit per the REVISIT TRIGGER block in
`score_skill_absolute.py`'s module docstring.

The orchestrator-LLM reads this file at score time. The thin Python wrapper at
`./score_skill_composite.py` exposes the same procedure programmatically for
tests and non-LLM callers; the wrapper is the canonical implementation, this
doc is its specification.

---

## Inputs

| Name | Type | Required | Description |
|---|---|---|---|
| `skill_md_path` | path | yes | Path to the `SKILL.md` being scored. Used for structural metrics and as the source of `evals_dir` (its sibling `evals/` directory). |
| `evals_dir` | path | yes | Path to the skill's `evals/` directory. Must contain `test_scenarios.json` AND `evals.json` for `absolute` / `composite` modes. |
| `mode` | enum | yes | One of `composite`, `structural`, `absolute`, `differential` (default: `composite`). |
| `verdicts_payload` | dict | absolute/composite mode | Canonical absolute-grader verdict JSON built by the orchestrator-LLM. See §Absolute grading § Canonical verdict JSON shape. |
| `baseline_skill_md` | path | differential mode only | Path to the BASELINE `SKILL.md` (last kept iteration). Used by the preserved-but-unwired differential grader. |
| `modified_skill_md` | path | differential mode only | Path to the MODIFIED (candidate) `SKILL.md`. Used by the differential grader. |
| `dispatcher` | callable | differential mode | LLM sub-agent dispatcher for pair comparisons. See `differential_grader.score_differential`'s `dispatch_comparison=` argument. Differential is no longer invoked by composite mode per SIHC.2 Option A. |

---

## Output contract

The procedure produces a single-trial JSON document with the shape documented
in `skill-iterate/SKILL.md` § Scoring — the same shape `append_result.py` has
always accepted unchanged:

```json
{"score": <float>, "passed": <int>, "total": <int>, "status": "ok" | "unparseable" | "harness-error"}
```

Field semantics:

- `score` — float in `[0.0, 1.0]`. The composite for `composite` mode; the
  raw structural score for `structural`; the raw differential score for
  `differential`. Null/missing when `status != "ok"`.
- `passed` — count of scoring components or scenarios that produced a usable
  result. For `composite`: 2 if both axes scored cleanly, 1 if only one did,
  0 if neither. For `differential`: the count of scenarios whose dispatcher
  returned a valid verdict.
- `total` — total scoring components or scenarios attempted. For `composite`:
  always 2. For `differential`: `len(test_scenarios)`.
- `status` — `"ok"` on successful score; `"unparseable"` if the dispatcher
  returned malformed output; `"harness-error"` on any other failure
  (FileNotFoundError, importable script crashes, etc.).

Per `skill-iterate/SKILL.md` § Phase 2 Step E: callers map `status != "ok"`
to a `crash` outcome per the §Autonomy contract iteration outcome taxonomy.

---

## Composite mode procedure (default)

The default mode per the hill-climbing plan §6 D6. Composes structural and
absolute-grader scores with configurable weights.

### Composition weights

Two top-of-procedure constants in `score_skill_composite.py` control the
weight mix:

```
STRUCTURAL_WEIGHT = 0.4
ABSOLUTE_WEIGHT   = 0.6
```

`ABSOLUTE_WEIGHT` was renamed from `DIFFERENTIAL_WEIGHT` per SIHC.2 Option
A (the LLM-driven axis is now the absolute grader, not the differential
grader). The value (0.6) did not change.

The constants sum to `1.0`. The split mirrors the SIHC.1 structural/
differential `0.4 / 0.6` ratio: `absolute_weighted` carries more weight
because it's the discriminating axis (differential graded all prose edits
as "same" per the SIHC.1 evidence) and structural metrics are easily
Goodharted (serve as a tie-breaker plus cheap deterministic signal).
SIHC.2 Option A swapped the LLM axis from differential to absolute without
rebalancing.

To rebalance the mix, edit both constants in `score_skill_composite.py`.
Anything other than a pair summing to 1.0 is a programming error.

### Procedure

1. **Run structural metrics.** Shell out to or import-call
   `.claude/skills/skill-iterate/scripts/structural_metrics.py
   <skill_md_path>`. Capture the `score` field from the returned JSON (a
   float in `[0.0, 1.0]`). Cache the full metrics dict for downstream
   reporting.

2. **Run absolute grader.** The orchestrator-LLM dispatches per-scenario
   grader sub-agents per §Absolute grading § Per-scenario sub-agent dispatch
   contract below, collects verdicts, and assembles the canonical JSON
   payload. Then shell out to or import-call
   `.claude/skills/_shared/score_skill_absolute.py::aggregate(payload,
   evals_data)` passing the orchestrator-built payload + the result of
   `_load_evals(<evals_dir>/evals.json)`. Capture `weighted_score` from the
   returned dict (a float in `[0.0, 1.0]`); also cache `failed_assertions`
   and `passing_pairs` for downstream brainstorm targeting.

3. **Compose.** Compute:

   ```
   final_score = STRUCTURAL_WEIGHT * structural_score + ABSOLUTE_WEIGHT * weighted_score
   ```

   (`ABSOLUTE_WEIGHT` was renamed from `DIFFERENTIAL_WEIGHT` per SIHC.2
   Option A — see §Composition weights above. The arithmetic did not
   change.)

   The result is in `[0.0, 1.0]` by linearity (each input is in `[0, 1]` and
   the weights are non-negative reals summing to 1). Defensively clamp to
   `[0.0, 1.0]` so future weight tweaks can't quietly produce out-of-range
   scores.

4. **Emit the single-trial JSON.** Return one of:

   - Both axes scored: `{"score": <final_score>, "passed": 2, "total": 2, "status": "ok"}`
   - Only one axis scored (the other raised `FileNotFoundError` or
     `NotImplementedError`): emit that axis's score directly with
     `passed=1, total=2, status="ok"`. Per the §Output contract `passed`
     semantics ("components that scored cleanly"), partial success is a
     legitimate `ok` outcome, not a harness-error.
   - Neither axis scored, OR evals/scenarios load failed (malformed JSON,
     unrecognized shape) before either axis ran: emit
     `{"score": null, "passed": 0, "total": 2, "status": "harness-error"}`.

   The per-axis exception scope is intentionally narrow — only
   `FileNotFoundError` and `NotImplementedError` are mapped to harness-error
   (plus the evals loader's `ValueError` on malformed JSON, before
   either axis runs). All other exceptions (`KeyError`, `TypeError`,
   `AttributeError`, generic `ValueError` elsewhere) propagate so that
   programmer bugs surface loudly rather than being silently misreported as
   harness errors.

---

## Absolute grading

The LLM-driven axis as of SIHC.2 Option A. Replaces the differential pair
grader in composite mode (see §Composite mode procedure step 2). The
aggregator is `score_skill_absolute.py::aggregate()` — a pure-Python module
with no LLM inside; the orchestrator-LLM does all sub-agent dispatch and
hands the aggregator a fully-formed verdict JSON.

### Per-scenario sub-agent dispatch contract

One grader sub-agent is dispatched per `scenario_id` in `test_scenarios.json`.
For a typical 3-scenario skill this is 3 parallel sub-agents per trial.

Each sub-agent receives ONLY:

1. Its assigned scenario block (the single matching entry from
   `test_scenarios.json`).
2. The rendered SKILL.md output for that scenario (the orchestrator-LLM
   pre-runs the skill under test against the scenario input and captures
   the SKILL.md output verbatim).
3. The full `evals.json` (all ~21 assertions across all categories — the
   sub-agent grades the SAME assertion set for every scenario; per-scenario
   applicability is handled via the §Vacuous-TRUE convention below).

Each sub-agent produces a `verdicts` dict keyed by assertion id (as a
string), one entry per assertion in `evals.json`. The orchestrator-LLM
collects all per-scenario verdict dicts and assembles them into the
canonical JSON payload (next subsection).

### Sub-agent prompt template

The canonical prompt the orchestrator-LLM dispatches to each grader
sub-agent. The verbatim template lives in
[`grader_prompt.py`](grader_prompt.py)'s `TEMPLATE` constant, and the
substitution helper is `build_grader_prompt(...)`. Orchestrators MUST
call this helper rather than hand-constructing the prompt — drift breaks
score reproducibility across runs (the 2026-05-27 M2 launch surfaced
this: consolidated render+grade sub-agents paraphrased the
VACUOUS-TRUE CONVENTION and 2 of 3 baseline graders misgraded
non-firing assertions as FALSE).

The template has four placeholders, all substituted by the helper:

| Placeholder | Source |
|---|---|
| `{{scenario_id}}` | The current scenario id from `test_scenarios.json` |
| `{{rendered_output}}` | The rendered SKILL.md output for this scenario |
| `{{evals_json}}` | The full `evals.json` as a string |
| `{{expected_assertions}}` | The scenario's `expected_assertions` list (or the secondary-rule sentinel when absent) |

The template's VACUOUS-TRUE handling has two rules:

- **PRIMARY RULE** (deterministic): an assertion ID NOT in the scenario's
  `expected_assertions` list grades `verdict: true` automatically with
  reason "ID <N> not in expected_assertions for <scenario_id>; trigger
  not firing; vacuously satisfied". No LLM judgment for non-firing
  assertions — the firing classification is made at scenario authoring
  time.

- **SECONDARY RULE** (fallback): when `expected_assertions` is empty or
  absent, fall back to "trigger condition not present in rendered
  output → vacuous true". This is the pre-2026-05-27 rule; preserved
  for scenarios whose authors did not populate the firing list.

The non-droppable contract for orchestrators: preserve the role statement,
the four-placeholder substitution contract, the output shape, BOTH
vacuous-true rules, the non-sycophancy line, and the EXAMPLES section
that specifically calls out "DO NOT grade an out-of-expected-assertions
ID as false just because you cannot find evidence — absence of evidence
is exactly the vacuous-true case." Drift in any of these breaks score
reproducibility.

Orchestrators MAY add minor adjustments BEFORE the role statement (e.g.,
scenario-specific context hints, project-internal acronym clarifications)
but MUST NOT modify the template body. Render and grade are SEPARATE
sub-agent roles by design — do not consolidate them into a single
sub-agent (a grader that just rendered is biased toward its own
output).

### Canonical verdict JSON shape

The input to `score_skill_absolute.py::aggregate()`:

```json
{
  "trials": [
    {
      "scenario_id": "scenario_single_project_with_friction",
      "verdicts": {
        "1":  {"verdict": true,  "reason": "Both Part 1 and Part 2 headings present"},
        "2":  {"verdict": false, "reason": "Used 'plain' fence label instead of 'text'"},
        "...": "all N assertion ids must be graded"
      }
    },
    {"scenario_id": "scenario_multi_project_build_phase", "verdicts": {"...": "all N"}}
  ]
}
```

Per-key semantics:

| Key | Meaning |
|---|---|
| `trials` | Flat list of per-scenario verdict blocks. For N-trial median (saturation confirmation), N blocks per `scenario_id` are appended in any order; the aggregator groups + collapses by `(scenario_id, assertion_id)`. |
| `trials[].scenario_id` | Must match a `scenario_id` in `test_scenarios.json`. Cross-scenario verdicts are kept separate by the aggregator (per-(scenario, assertion) majority vote). |
| `trials[].verdicts` | Dict keyed by assertion id as a STRING (JSON object keys are strings; the aggregator coerces to int). Every assertion id in `evals.json` must appear in the payload handed to the aggregator — completeness is enforced by the orchestrator's §Malformed grader output handling (missing ids are backfilled as failures before the aggregator sees the payload), NOT by the aggregator itself. The aggregator raises only when an entry is present but lacks BOTH `verdict` and `result` keys. |
| `verdicts[id].verdict` | Canonical bool key. Tolerated legacy alias: `result` (some grader sub-agent prompts in the field still emit `result`; the aggregator accepts either, preferring `verdict`). |
| `verdicts[id].reason` | Short one-sentence justification per assertion. Surfaced in the aggregator's `failed_assertions` output for brainstorm-prompt targeting. |

For N=3 median trials, three trial blocks are appended with the SAME
`scenario_id` (the aggregator collapses via per-(scenario, assertion)
majority vote; ties resolve to `False` — strict, an assertion only passes
when a majority of trials say so).

### Malformed grader output

Grader sub-agents are LLMs and occasionally emit non-conforming output.
The orchestrator-LLM is responsible for repairing or surfacing each
malformation BEFORE the verdict payload reaches the aggregator. The
aggregator is strict and not defensive; pre-aggregator cleanup is the
contract.

- **Non-parseable text (JSON parse fails).** The orchestrator re-dispatches
  the SAME scenario's grader sub-agent ONCE with the same inputs. If the
  retry also fails to parse, the orchestrator stops and emits
  `{"score": null, "passed": 0, "total": 2, "status": "unparseable"}` for
  the WHOLE composite (per §Output contract). One scenario's unparseable
  grader is fatal — the composite cannot be computed without all scenarios.

- **Omitted assertion id (id is in `evals.json` but missing from
  `verdicts`).** The orchestrator backfills the entry as
  `{"verdict": false, "reason": "grader omitted"}` and proceeds. Grader
  silence is a defect, not a non-firing trigger — vacuous-TRUE is reserved
  for assertions the sub-agent EXPLICITLY graded with a vacuous-satisfied
  reason. Surfacing the omission as a failure puts the assertion on the
  brainstorm's target list, where it belongs.

- **Extra assertion id (id is in `verdicts` but not in `evals.json`).**
  The orchestrator drops the entry silently. Graders sometimes hallucinate
  ids; if these reach the aggregator's per-(scenario, assertion) lookup it
  would raise. Filtering pre-aggregator preserves the rest of the verdict
  set.

- **Non-bool verdict value (e.g., `"maybe"`, `"n/a"`, `null`).** The
  orchestrator coerces: `"true"` / `"yes"` / `True` → `True`;
  `"false"` / `"no"` / `False` → `False`; anything else → `False`. Strict
  coercion surfaces the ambiguity to the brainstorm as the assertion
  failing, rather than silently passing on a hedged grade.

After these repairs the payload satisfies the aggregator's input contract
(every assertion id present with a bool `verdict` and a `reason` string)
and `aggregate()` runs without raising.

### Vacuous-TRUE convention

When an assertion's trigger condition does not fire in the scenario — e.g.,
assertion #14 only applies if the rendered output contains a "Decisions"
section, and this scenario's output doesn't — the sub-agent grades
`verdict: true` with a reason like `"Decisions section not present in
output; vacuously satisfied"`.

Rationale: vacuous-truth keeps non-applicable conditionals from polluting
the failure list and from suppressing the composite score for skills whose
scenarios don't exercise every assertion. The aggregator does NOT model
applicability separately; vacuous-TRUE is graded at the sub-agent layer.

### N=3 median trigger (saturation-only)

N=1 by default. ONLY when a single-trial aggregate reports all-pass
(`passed == total`, saturation), the orchestrator dispatches 2 additional
trials of the same single-trial pipeline.

| Iteration outcome | Sub-agent count (3-scenario skill) |
|---|---|
| Normal iter (some failures expected) | 1 trial x 3 scenarios = 3 sub-agents |
| Saturated iter (all-pass at N=1) | 3 trials x 3 scenarios = 9 sub-agents |

The aggregator collapses via per-(scenario, assertion) majority vote across
the 3 trials. If median confirms saturation, the loop enters simplification
mode for the iteration. If median surfaces any failures, those become the
targeting anchor for the next brainstorm.

Cost rationale: N=3 only on saturated iters means the 3x sub-agent cost is
paid at most once per skill (the iter that first reports all-pass), not on
every iter. The 2026-05-26 user-pm prototype confirmed N=3 median
saturation at 75/75 unanimous across all three trials (baseline was 71/75
at iter 1 -> 75/75 at iter 2 -> N=3 confirmed 75/75).

### Orchestrator-LLM as dispatcher

The Python wrapper (`score_skill_absolute.py`) cannot inject sub-agent
callables — LLM dispatch is the harness's job, not the aggregator's. The
orchestrator-LLM (i.e., the LLM running `/skill-iterate`) is the
dispatcher:

1. For each `scenario_id` in `test_scenarios.json`, render the skill under
   test against the scenario input (the orchestrator-LLM runs the skill
   itself or via a render sub-agent).
2. Dispatch one grader sub-agent per scenario (Agent tool) with the
   per-scenario inputs from §Per-scenario sub-agent dispatch contract.
3. Collect verdict dicts from all sub-agents.
4. On a saturated single-trial result, dispatch 2 more trial rounds of
   steps 1-3 (one per added trial).
5. Assemble the canonical verdict JSON (§Canonical verdict JSON shape).
6. Shell out to `score_skill_absolute.py --evals <evals_dir>/evals.json
   --input <verdicts_payload>` (or import-call
   `aggregate(payload, evals_data)`).

The Python script is pure-Python; no LLM inside, no sub-agent dispatch.
This separation keeps the aggregator unit-testable with deterministic
verdict fixtures (see `test_score_skill_absolute.py`).

---

## Structural-only mode

For skills without `test_scenarios.json` (early bootstrap, structural-only
audits). Steps:

1. Run structural metrics on `skill_md_path` per Step 1 of composite mode.
2. Emit `{"score": <structural_score>, "passed": 1, "total": 1, "status": "ok"}`.

The procedure does not invoke the absolute grader at all in this mode —
no LLM dispatch, no scenarios required. Cheap and deterministic.

---

## Differential-only mode

NOTE: differential is no longer invoked by composite mode as of SIHC.2
Option A (decision 2026-05-26). The differential grader code is preserved
for possible Option B revisit per the REVISIT TRIGGER block in
`score_skill_absolute.py`'s module docstring (reintroduce differential as a
third axis or as a ship-gate validator if assertion-targeted iteration
produces clear local-optima behavior — loop passes the 21 evals but
produces measurably worse outputs in ways the rubric doesn't capture).

For skills with hand-curated scenarios but no structural baseline to compare
against (rare; used by skills whose SKILL.md is intentionally terse and would
score poorly on the rules-to-rationale-ratio metric). Steps:

1. Run differential grader per the prior composite-mode Step 2 contract:
   shell out to or import-call
   `.claude/skills/skill-iterate/scripts/differential_grader.py
   <baseline_skill_md> <modified_skill_md> <evals_dir>/test_scenarios.json`.
   The dispatcher argument is the production LLM sub-agent dispatch — pass
   `dispatch_comparison=` per the differential_grader docstring. Use
   :func:`differential_grader.format_comparison_prompt` to render the
   comparison prompt template (see §Brace-safe substitution requirement
   below — `str.format()` is NOT safe here).
2. Emit `{"score": <differential_score>, "passed": <scenarios_scored>, "total": <len(scenarios)>, "status": "ok"}`.

The procedure does not invoke structural metrics at all in this mode.

---

## Brace-safe substitution requirement

When invoking the differential grader's comparison sub-agent, **always use
`differential_grader.format_comparison_prompt(scenario, baseline_output,
modified_output)`** rather than calling `COMPARISON_PROMPT_TEMPLATE.format(...)`
directly.

Rationale: real `baseline_output` and `modified_output` strings are entire
SKILL.md files that routinely contain literal `{` / `}` (JSON examples, dict
literals, format strings). Python's `str.format()` raises `KeyError` on those
braces because it tries to interpret them as format-spec syntax. The
`format_comparison_prompt` helper uses `str.replace()` on the four named
placeholders, which is immune to that failure mode.

This was a Step 4 reviewer carry-forward — the original template was
documented as `.format()`-able, but real-world SKILL.md inputs would break it
on first contact. The helper centralizes the safety in one place; never
re-introduce the direct `.format()` call.

---

## Goldens verification

After the regular composite/structural/differential score is computed,
`score_composite` ALSO runs a per-skill goldens-verification pass when the
caller supplies a `skill_dir` and does not pass `--skip-goldens`. This is the
SIHC Step 12 anti-sycophancy guard: if the grader cannot tell the
hand-curated `good.md` apart from any `bad_*.md` in the same corpus, the
grader is structurally sycophantic for this skill and the /skill-iterate loop
should park the skill rather than burning N iterations against meaningless
deltas. The design rationale lives at
[`docs/investigations/skill-iterate-hill-climbing/01-score-against-golden-bad-examples.md`](../../../docs/investigations/skill-iterate-hill-climbing/01-score-against-golden-bad-examples.md).

### When it runs

After Step 4 (emit single-trial JSON) of the composite procedure, but before
returning the result. The verification pass is observability — it does NOT
change the regular composite score. The pass is skipped (status =
`no-goldens-found`) when the caller does not supply `skill_dir`, when the
caller passes `--skip-goldens`, or when the per-skill goldens directory does
not exist on disk (the dominant runtime path until SIHC plan M3/M4 land real
fleet goldens).

### What it loads

Per-skill location: `<skill_dir>/evals/golden/`. The loader reads `good.md`
and every file matching the glob `bad_*.md`. All other files in the
directory (notably `manifest.json` written by
[`skill-eval-setup/scripts/generate_bad_examples.py`](../skill-eval-setup/scripts/generate_bad_examples.py)
and any ad-hoc operator notes) are ignored.

### Accept criterion

Every bad must score STRICTLY lower than good (`bad_score < good_score`). A
tie counts as a fail — this mirrors the per-bad verification semantics in
`generate_bad_examples.py::score_bad_against_evals` (a sycophantic grader
that produces identical scores on good and bad has not actually
discriminated them). The bad's per-trial score is the value returned by the
injected `score_single_fn(path)` — production callers wire this to the same
single-trial scorer the composite procedure uses; tests inject deterministic
stubs.

### The harness-error halt (grader sycophancy)

If one or more bads scores `>= good_score`, the verification pass returns
`status="harness-error"` and the returned `CompositeScore` has
`halt_requested=True`. The wrapping `/skill-iterate` loop should treat this
as the crash sub-class `harness-error: grader sycophancy detected` (per the
`GRADER_SYCOPHANCY_CRASH_CLASS` constant in `score_skill_composite.py`) and
park the skill via §Autonomy contract clause 3 in
[`../skill-iterate/SKILL.md`](../skill-iterate/SKILL.md) Phase 2 Step D.

The verification function itself does NOT raise on harness-error — it always
returns a `GoldensStatus` value. The CALLER decides whether to halt; this
keeps `score_composite` pure (no control-flow side effects from goldens
verification) and lets the orchestrator-LLM log + park the skill before
continuing to the next one in the queue.

### Skip-when-absent fallback

The dominant runtime path until SIHC M3/M4 land: `<skill_dir>/evals/golden/`
does not exist. The loader returns `status="no-goldens-found"` immediately
with `good_score=None` and `bad_scores=None`. Composite scoring proceeds
normally; downstream callers do NOT treat this as an error. The
`reason` field names the missing path so operators reading log lines can
see where to scaffold the goldens.

### Return-shape extension

The composite procedure's return is extended with two fields, both with
defaults that preserve backwards compatibility for callers that don't pass
`skill_dir`:

- `goldens_status: GoldensStatus | None` — the verification verdict, or
  `None` when the pass was skipped entirely (no `skill_dir` supplied OR
  `--skip-goldens` set).
- `halt_requested: bool` — `True` iff `goldens_status.status ==
  "harness-error"`. The /skill-iterate loop reads this flag to decide
  whether to park the skill.

The original `score`, `passed`, `total`, `status` fields are unchanged —
existing consumers (`append_result.py`, the CLI JSON output, the
`/skill-iterate` orchestrator's score-extraction in Phase 2 Step E) continue
to work without modification.

### CLI

The CLI exposes `--skill-dir <path>` to enable the verification pass and
`--skip-goldens` to bypass it even when `--skill-dir` is set (useful for
smoke checks where the discrimination verdict is not the signal under
test). When neither flag is passed, goldens verification is skipped
entirely (the default — preserves pre-Step-12 behavior).

---

## Composite-mode worked example (smoke gate)

Running the procedure on `.claude/skills/session-wrap/SKILL.md` with a
saturated absolute-grader verdict payload (all assertions pass under N=3
median) yields:

```
structural_score    ≈ 0.91   # from structural_metrics.py on session-wrap
weighted_score      = 1.0    # all-pass under N=3 median across all scenarios

final_score = 0.4 * 0.91 + 0.6 * 1.0
            ≈ 0.964
```

The exact numbers above were re-validated in Step 3 of the SIHC.2 plan
(differential → absolute swap in `score_skill_composite.py`); the
absolute-grader composite math itself was validated on the user-pm baseline
2026-05-26 (iter 1 baseline 71/75 → iter 2 75/75 → N=3 median confirmed
75/75 unanimous).

A deviation larger than ± 0.01 from the re-validated smoke gate indicates
either a session-wrap edit drifted the structural score, or a regression
in the composition arithmetic.
