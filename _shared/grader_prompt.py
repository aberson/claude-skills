"""Build the canonical absolute-grader sub-agent prompt.

Verbatim implementation of the spec template at `score-skill.md` § Absolute
grading § Sub-agent prompt template. Drift from this helper across orchestrator
implementations breaks score reproducibility — different orchestrators would
write meaningfully different prompts and the resulting verdicts could not be
compared trial-to-trial.

The 2026-05-27 M2 launch surfaced what happens when orchestrator-LLMs paraphrase
the VACUOUS-TRUE CONVENTION text: 2 of 3 graders misgraded "trigger not present"
assertions as FALSE instead of vacuous-TRUE. The fix moves vacuous-true from
LLM judgment to a deterministic list lookup against `expected_assertions` from
`test_scenarios.json` whenever that field is present.

Uses `.replace()` not `.format()` — rendered output and evals JSON routinely
contain literal `{`/`}` (JSON examples, dict literals) that would raise KeyError
under `str.format()`. Same pattern as `differential_grader.format_comparison_prompt`.
"""

from __future__ import annotations

TEMPLATE = """You are a strict grader. Your job is to evaluate a rendered skill output
against a fixed set of assertions and return JSON only.

ASSIGNED SCENARIO ID: {{scenario_id}}

RENDERED SKILL.MD OUTPUT (the artifact under evaluation):
{{rendered_output}}

EVALS.JSON (the full assertion set -- grade every id below for THIS scenario):
{{evals_json}}

EXPECTED_ASSERTIONS FOR THIS SCENARIO (from test_scenarios.json):
{{expected_assertions}}

These are the assertion IDs whose trigger conditions FIRE in this scenario.
All OTHER assertion IDs in evals.json have non-firing triggers and grade
vacuous-true deterministically (no LLM judgment required -- see VACUOUS-TRUE
CONVENTION below).

VACUOUS-TRUE CONVENTION (deterministic when expected_assertions provided)

PRIMARY RULE: an assertion ID NOT in the expected_assertions list above
grades verdict: true with reason "ID <N> not in expected_assertions for
{{scenario_id}}; trigger not firing; vacuously satisfied". Apply this WITHOUT
analyzing the rendered output for that ID -- the firing classification was
made at scenario authoring time. This eliminates LLM judgment for vacuous-
true cases.

SECONDARY RULE (fallback when expected_assertions is empty/missing): if an
assertion's trigger condition is NOT present in the rendered output (e.g.,
an assertion about a "Decisions" section, when the output contains no
Decisions section at all), grade `verdict: true` with reason "<trigger>
not present in output; vacuously satisfied". Do this ONLY for non-firing
conditional assertions. If the trigger IS present but the assertion's
content requirement is unmet, grade `verdict: false`.

OUTPUT SHAPE -- JSON only, no prose, no markdown fences:
{
  "verdicts": {
    "<id>": {"verdict": true | false, "reason": "<one short sentence>"},
    ...
  }
}

Every assertion id in evals.json above MUST appear as a key in `verdicts`.

DO NOT BE SYCOPHANTIC. If an assertion fails, mark `verdict: false` and
explain the specific defect; do not soften a clear failure to `true` to
make the output look better. The grader's job is to surface defects so
the next brainstorm has real targets -- false-positive passes break the
hill-climb.

EXAMPLES of vacuous-true vs real-fail:
- Assertion ID in expected_assertions: trigger fires; if the rendered
  output meets the content requirement, grade true; else grade false
  (real failure, surfaces to brainstorm).
- Assertion ID NOT in expected_assertions: trigger does not fire; grade
  true vacuously without examining the rendered output for that ID.
- DO NOT grade an out-of-expected-assertions ID as false just because
  you cannot find evidence in the rendered output -- absence of evidence
  is exactly the vacuous-true case.
"""


def build_grader_prompt(
    *,
    scenario_id: str,
    rendered_output: str,
    evals_json: str,
    expected_assertions: list[int] | None,
) -> str:
    """Construct the verbatim grader sub-agent prompt.

    Args:
        scenario_id: Scenario id from test_scenarios.json (e.g., "scenario_1").
        rendered_output: The rendered skill output text to grade.
        evals_json: Full evals.json as a serialized string (typically the file
            contents read as text).
        expected_assertions: List of assertion IDs that FIRE in this scenario.
            None or empty list activates the SECONDARY RULE (LLM judgment).

    Returns:
        Fully-substituted grader prompt. Pass this verbatim as the Agent
        tool's `prompt` parameter.
    """
    if expected_assertions:
        expected_str = (
            "[" + ", ".join(str(i) for i in sorted(expected_assertions)) + "]"
        )
    else:
        expected_str = "(not provided -- apply SECONDARY RULE manually below)"

    return (
        TEMPLATE
        .replace("{{scenario_id}}", scenario_id)
        .replace("{{rendered_output}}", rendered_output)
        .replace("{{evals_json}}", evals_json)
        .replace("{{expected_assertions}}", expected_str)
    )
