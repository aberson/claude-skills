"""Unit tests for grader_prompt.build_grader_prompt.

Verifies the prompt-construction contract that fixes the 2026-05-27 M2 grader
drift defect: when expected_assertions is provided, vacuous-true becomes a
deterministic list lookup; when not, the secondary fallback rule applies.

The tests assert PROMPT STRUCTURE, not grader-LLM behavior — they ensure
operator orchestrators construct the same prompt across runs. LLM-behavior
verification requires a live dispatch and is the scenario suite's job.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from grader_prompt import TEMPLATE, build_grader_prompt


def test_returns_string():
    out = build_grader_prompt(
        scenario_id="scenario_1",
        rendered_output="# rendered output\nbody",
        evals_json='{"skill": "x"}',
        expected_assertions=[1, 2, 3],
    )
    assert isinstance(out, str)
    assert len(out) > 500  # non-trivial prompt


def test_substitutes_scenario_id():
    out = build_grader_prompt(
        scenario_id="scenario_42",
        rendered_output="x",
        evals_json="y",
        expected_assertions=[1],
    )
    # Both occurrences of {{scenario_id}} in template are substituted.
    assert "scenario_42" in out
    assert "{{scenario_id}}" not in out
    assert out.count("scenario_42") >= 2


def test_substitutes_rendered_output():
    rendered = "# foo\n## bar\n- baz"
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output=rendered,
        evals_json="{}",
        expected_assertions=[1],
    )
    assert rendered in out
    assert "{{rendered_output}}" not in out


def test_substitutes_evals_json():
    evals = json.dumps({"skill": "user-pm", "categories": []})
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json=evals,
        expected_assertions=[1],
    )
    assert evals in out
    assert "{{evals_json}}" not in out


def test_expected_assertions_list_lex_sorted():
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=[7, 3, 1, 5],
    )
    assert "[1, 3, 5, 7]" in out
    assert "{{expected_assertions}}" not in out


def test_expected_assertions_empty_falls_through_to_secondary_rule():
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=[],
    )
    assert "(not provided -- apply SECONDARY RULE manually below)" in out
    assert "{{expected_assertions}}" not in out


def test_expected_assertions_none_falls_through_to_secondary_rule():
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=None,
    )
    assert "(not provided -- apply SECONDARY RULE manually below)" in out


def test_contains_primary_rule_text():
    """The primary rule is the deterministic vacuous-true fix from 2026-05-27."""
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=[1, 2],
    )
    assert "PRIMARY RULE" in out
    assert "not in expected_assertions" in out
    assert "trigger not firing; vacuously satisfied" in out
    # The "without analyzing the rendered output" instruction is what kills
    # LLM judgment drift on non-firing assertions.
    assert "WITHOUT" in out and "analyzing the rendered output" in out


def test_contains_secondary_rule_text():
    """The secondary fallback is needed when expected_assertions is absent."""
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=None,
    )
    assert "SECONDARY RULE" in out
    assert "Decisions" in out  # canonical example in fallback rule


def test_contains_anti_sycophancy_clause():
    """The DO NOT BE SYCOPHANTIC clause is one of the five non-droppable lines."""
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=[1],
    )
    assert "DO NOT BE SYCOPHANTIC" in out


def test_contains_output_shape_section():
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=[1],
    )
    assert "OUTPUT SHAPE" in out
    assert '"verdicts"' in out


def test_contains_examples_section_with_failure_mode_callout():
    """The EXAMPLES section is what fixes the 2026-05-27 drift specifically.

    Without "DO NOT grade an out-of-expected-assertions ID as false just because
    you cannot find evidence", graders default to "cannot observe -> false" which
    is exactly the bug we're fixing.
    """
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json="{}",
        expected_assertions=[1],
    )
    assert "EXAMPLES of vacuous-true vs real-fail" in out
    assert "DO NOT grade an out-of-expected-assertions ID as false" in out
    assert "absence of evidence" in out


def test_handles_braces_in_rendered_output():
    """Rendered SKILL.md routinely contains literal {} (JSON examples, dict
    literals). The helper uses .replace() not .format() so braces survive.
    Regression test for the same hazard the differential_grader helper handles.
    """
    rendered_with_braces = '```json\n{"key": "value", "list": [{"a": 1}]}\n```'
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output=rendered_with_braces,
        evals_json="{}",
        expected_assertions=[1],
    )
    # No KeyError raised; the braces survived intact.
    assert rendered_with_braces in out


def test_handles_braces_in_evals_json():
    evals_with_braces = json.dumps(
        {"categories": [{"name": "X", "evals": [{"id": 1, "statement": "y"}]}]}
    )
    out = build_grader_prompt(
        scenario_id="s1",
        rendered_output="x",
        evals_json=evals_with_braces,
        expected_assertions=[1],
    )
    assert evals_with_braces in out


def test_template_has_no_unmatched_placeholders_after_full_substitution():
    """A passing run must leave NO {{...}} placeholders in the output."""
    out = build_grader_prompt(
        scenario_id="scenario_x",
        rendered_output="rendered",
        evals_json="evals",
        expected_assertions=[1, 2],
    )
    assert "{{" not in out
    assert "}}" not in out


def test_2026_05_27_regression_scenario_3_id_19():
    """Regression test for the M2 launch failure mode.

    On 2026-05-27, build-overnight scenario_3 had expected_assertions=[5, 7, 9,
    16, 17, 20, 21] -- ID 19 (zero-DONE prominent callout) was NOT firing
    because scenario_3 had 1 DONE item, not zero. The grader saw "1 of 3 DONE
    (not zero)" and marked ID 19 false with reason "precondition not triggered;
    cannot observe". That's the bug.

    With the new template + expected_assertions list, ID 19 is NOT in the list,
    so the grader applies PRIMARY RULE -> verdict: true without examining
    output. This test asserts the prompt structure that makes that outcome
    inevitable.
    """
    bo_scenario_3_expected = [5, 7, 9, 16, 17, 20, 21]
    out = build_grader_prompt(
        scenario_id="scenario_3",
        rendered_output="(rendered build-overnight output with 1 DONE)",
        evals_json="(full evals.json with 22 assertions)",
        expected_assertions=bo_scenario_3_expected,
    )
    # The list reaches the prompt.
    assert "[5, 7, 9, 16, 17, 20, 21]" in out
    # The PRIMARY RULE is explicit about not analyzing output for non-listed IDs.
    assert "PRIMARY RULE" in out
    assert "WITHOUT" in out
    # The EXAMPLES section nails the exact mistake we're preventing.
    assert "DO NOT grade an out-of-expected-assertions ID as false" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
