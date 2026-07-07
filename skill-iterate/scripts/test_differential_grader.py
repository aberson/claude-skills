"""Self-contained unit tests for differential_grader.

Covers aggregation arithmetic across the full verdict matrix (all-better,
all-worse, mixed, all-same, empty, single, unknown), the production-stub
NotImplementedError contract, the injectable-dispatcher seam, and a CLI smoke
that the JSON-output shape is as documented.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from differential_grader import (
    COMPARISON_PROMPT_TEMPLATE,
    ScenarioVerdict,
    _make_fixed_verdict_dispatcher,
    aggregate_verdicts,
    format_comparison_prompt,
    main,
    score_differential,
)


SCRIPTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = SCRIPTS_DIR / "fixtures"


def _v(idx: int, verdict: str) -> ScenarioVerdict:
    """Compact helper: build a ScenarioVerdict for test scaffolding."""
    return ScenarioVerdict(
        scenario_id=f"s{idx}",
        verdict=verdict,
        reason=f"test fixture {idx}",
    )


# --- Aggregation arithmetic ---------------------------------------------------


class AggregateVerdictsTest(unittest.TestCase):
    def test_all_better_scores_one(self) -> None:
        result = aggregate_verdicts([_v(1, "better"), _v(2, "better"), _v(3, "better")])
        self.assertEqual(result.raw_score, 1.0)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.counts, {"better": 3, "worse": 0, "same": 0})
        self.assertEqual(result.total_scenarios, 3)

    def test_all_worse_scores_zero(self) -> None:
        result = aggregate_verdicts([_v(1, "worse"), _v(2, "worse"), _v(3, "worse")])
        self.assertEqual(result.raw_score, -1.0)
        self.assertEqual(result.score, 0.0)
        self.assertEqual(result.counts, {"better": 0, "worse": 3, "same": 0})

    def test_mixed_one_each_is_neutral(self) -> None:
        # 1 better + 1 worse + 1 same -> raw = 0.0, score = 0.5
        result = aggregate_verdicts([_v(1, "better"), _v(2, "worse"), _v(3, "same")])
        self.assertEqual(result.raw_score, 0.0)
        self.assertEqual(result.score, 0.5)
        self.assertEqual(result.counts, {"better": 1, "worse": 1, "same": 1})

    def test_all_same_is_neutral(self) -> None:
        result = aggregate_verdicts([_v(1, "same"), _v(2, "same")])
        self.assertEqual(result.raw_score, 0.0)
        self.assertEqual(result.score, 0.5)
        self.assertEqual(result.counts, {"better": 0, "worse": 0, "same": 2})

    def test_empty_is_neutral_no_signal(self) -> None:
        # Empty test_scenarios is a legitimate early-bootstrap case, not an error.
        result = aggregate_verdicts([])
        self.assertEqual(result.raw_score, 0.0)
        self.assertEqual(result.score, 0.5)
        self.assertEqual(result.total_scenarios, 0)
        self.assertEqual(result.counts, {"better": 0, "worse": 0, "same": 0})

    def test_single_better_no_divzero(self) -> None:
        # N=1 must use the same formula as N>1 (no special-case branch).
        result = aggregate_verdicts([_v(1, "better")])
        self.assertEqual(result.raw_score, 1.0)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.total_scenarios, 1)

    def test_single_worse_no_divzero(self) -> None:
        result = aggregate_verdicts([_v(1, "worse")])
        self.assertEqual(result.raw_score, -1.0)
        self.assertEqual(result.score, 0.0)

    def test_clamp_invariant_holds(self) -> None:
        # The formula (better - worse) / total cannot exceed |1| when both
        # better and worse are non-negative integers bounded by total. So a
        # legitimate input cannot push score outside [0, 1]. Verify that even
        # with the heaviest skews the clamp is a no-op (defensive) and not
        # accidentally squashing valid values.
        for verdicts, expected_score in [
            ([_v(i, "better") for i in range(100)], 1.0),
            ([_v(i, "worse") for i in range(100)], 0.0),
        ]:
            result = aggregate_verdicts(verdicts)
            self.assertEqual(result.score, expected_score)
            self.assertGreaterEqual(result.score, 0.0)
            self.assertLessEqual(result.score, 1.0)

    def test_unknown_verdict_dilutes_signal(self) -> None:
        # Unknown verdicts aren't bucketed into better/worse/same but still
        # bump total_scenarios (denominator). With 1 better + 1 unknown, raw
        # score is 1/2 = 0.5, score = 0.75 — not 1.0 as it would be if the
        # unknown were silently dropped.
        result = aggregate_verdicts([_v(1, "better"), _v(2, "neutral")])
        self.assertEqual(result.raw_score, 0.5)
        self.assertEqual(result.score, 0.75)
        self.assertEqual(result.counts, {"better": 1, "worse": 0, "same": 0})
        self.assertEqual(result.total_scenarios, 2)

    def test_verdicts_preserved_in_order(self) -> None:
        inputs = [_v(1, "better"), _v(2, "same"), _v(3, "worse")]
        result = aggregate_verdicts(inputs)
        self.assertEqual([v.scenario_id for v in result.verdicts], ["s1", "s2", "s3"])
        self.assertEqual([v.verdict for v in result.verdicts], ["better", "same", "worse"])


# --- score_differential (dispatch seam) ---------------------------------------


def _write_tmp_skill(tmpdir: Path, name: str, body: str) -> Path:
    p = tmpdir / name
    p.write_text(body, encoding="utf-8")
    return p


class ScoreDifferentialTest(unittest.TestCase):
    def test_with_mocked_dispatcher_matches_aggregation(self) -> None:
        # 3 scenarios; stub returns better/worse/same in order. Result should
        # equal aggregate_verdicts on the same verdicts.
        scenarios = [
            {"id": "a", "prompt": "p1", "criteria": "c1"},
            {"id": "b", "prompt": "p2", "criteria": "c2"},
            {"id": "c", "prompt": "p3", "criteria": "c3"},
        ]
        sequence = iter(["better", "worse", "same"])

        def stub(
            _baseline: str, _modified: str, scenario: dict[str, Any]
        ) -> ScenarioVerdict:
            return ScenarioVerdict(
                scenario_id=str(scenario["id"]),
                verdict=next(sequence),
                reason="mock",
            )

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            baseline = _write_tmp_skill(tdp, "baseline.md", "# baseline\n")
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            result = score_differential(
                baseline, modified, scenarios, dispatch_comparison=stub
            )

        # Expected: 1 better + 1 worse + 1 same = raw 0.0, score 0.5
        self.assertEqual(result.score, 0.5)
        self.assertEqual(result.counts, {"better": 1, "worse": 1, "same": 1})
        self.assertEqual(
            [v.scenario_id for v in result.verdicts], ["a", "b", "c"]
        )

    def test_default_dispatcher_raises_not_implemented(self) -> None:
        # The production stub must fail loudly so callers don't silently get
        # zero-signal scores. Verify both the exception type and the
        # documented message text.
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            baseline = _write_tmp_skill(tdp, "baseline.md", "# baseline\n")
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            with self.assertRaises(NotImplementedError) as cm:
                score_differential(
                    baseline,
                    modified,
                    [{"id": "x", "prompt": "p", "criteria": "c"}],
                )
        self.assertIn("differential grader sub-agent dispatch", str(cm.exception))
        self.assertIn("dispatch_comparison=", str(cm.exception))

    def test_empty_scenarios_does_not_call_dispatcher(self) -> None:
        # With zero scenarios the dispatcher (including the raising stub)
        # should never be invoked; score is the neutral 0.5.
        sentinel = {"called": False}

        def stub(
            _baseline: str, _modified: str, _scenario: dict[str, Any]
        ) -> ScenarioVerdict:
            sentinel["called"] = True
            return ScenarioVerdict(scenario_id="x", verdict="same", reason="")

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            baseline = _write_tmp_skill(tdp, "baseline.md", "# baseline\n")
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            # Default dispatcher would raise NotImplementedError; passing
            # the stub here also lets us assert it's not invoked.
            result = score_differential(
                baseline, modified, [], dispatch_comparison=stub
            )

        self.assertEqual(result.score, 0.5)
        self.assertFalse(sentinel["called"])

    def test_missing_baseline_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            with self.assertRaises(FileNotFoundError):
                score_differential(
                    tdp / "no-such-baseline.md",
                    modified,
                    [],
                    dispatch_comparison=lambda b, m, s: _v(1, "same"),
                )


# --- CLI ----------------------------------------------------------------------


class CLITest(unittest.TestCase):
    def test_cli_with_stub_verdict_same_produces_neutral_score(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            baseline = _write_tmp_skill(tdp, "baseline.md", "# baseline\n")
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            scenarios_path = tdp / "scenarios.json"
            scenarios_path.write_text(
                json.dumps([{"id": "s1", "prompt": "p", "criteria": "c"}]),
                encoding="utf-8",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        str(baseline),
                        str(modified),
                        str(scenarios_path),
                        "--stub-verdict",
                        "same",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["score"], 0.5)
            self.assertEqual(payload["raw_score"], 0.0)
            self.assertEqual(payload["total_scenarios"], 1)
            self.assertEqual(
                payload["counts"], {"better": 0, "worse": 0, "same": 1}
            )

    def test_cli_with_stub_verdict_better_scores_one(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            baseline = _write_tmp_skill(tdp, "baseline.md", "# baseline\n")
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            scenarios_path = tdp / "scenarios.json"
            scenarios_path.write_text(
                json.dumps(
                    [
                        {"id": "s1", "prompt": "p", "criteria": "c"},
                        {"id": "s2", "prompt": "p", "criteria": "c"},
                    ]
                ),
                encoding="utf-8",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        str(baseline),
                        str(modified),
                        str(scenarios_path),
                        "--stub-verdict",
                        "better",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["score"], 1.0)
            self.assertEqual(payload["total_scenarios"], 2)

    def test_cli_scenarios_wrapped_object_shape(self) -> None:
        # Forward-compat: {"scenarios": [...]} also accepted.
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            baseline = _write_tmp_skill(tdp, "baseline.md", "# baseline\n")
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            scenarios_path = tdp / "scenarios.json"
            scenarios_path.write_text(
                json.dumps(
                    {"scenarios": [{"id": "s1", "prompt": "p", "criteria": "c"}]}
                ),
                encoding="utf-8",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        str(baseline),
                        str(modified),
                        str(scenarios_path),
                        "--stub-verdict",
                        "same",
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["total_scenarios"], 1)

    def test_cli_without_stub_verdict_exits_nonzero(self) -> None:
        # No --stub-verdict + scenarios present -> production stub raises
        # NotImplementedError -> main() returns non-zero (4).
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            baseline = _write_tmp_skill(tdp, "baseline.md", "# baseline\n")
            modified = _write_tmp_skill(tdp, "modified.md", "# modified\n")
            scenarios_path = tdp / "scenarios.json"
            scenarios_path.write_text(
                json.dumps([{"id": "s1", "prompt": "p", "criteria": "c"}]),
                encoding="utf-8",
            )

            # Suppress the error message during the test run.
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        str(baseline),
                        str(modified),
                        str(scenarios_path),
                    ]
                )
            self.assertNotEqual(rc, 0)


# --- Helpers + constants ------------------------------------------------------


class StubDispatcherFactoryTest(unittest.TestCase):
    def test_factory_returns_callable_with_fixed_verdict(self) -> None:
        dispatcher = _make_fixed_verdict_dispatcher("better")
        result = dispatcher("base", "mod", {"id": "s1"})
        self.assertEqual(result.verdict, "better")
        self.assertEqual(result.scenario_id, "s1")

    def test_factory_rejects_invalid_verdict(self) -> None:
        with self.assertRaises(ValueError):
            _make_fixed_verdict_dispatcher("bogus")


class ComparisonPromptTemplateTest(unittest.TestCase):
    def test_template_has_all_required_placeholders(self) -> None:
        # Step 5's real dispatcher will substitute these four keys via
        # format_comparison_prompt; if any disappear during refactor, tests
        # catch it before downstream callers break.
        required = (
            "{scenario_prompt}",
            "{scenario_criteria}",
            "{baseline_output}",
            "{modified_output}",
        )
        for placeholder in required:
            self.assertIn(placeholder, COMPARISON_PROMPT_TEMPLATE)

    def test_template_formats_without_error(self) -> None:
        # Sanity: the literal `{"verdict": ...}` JSON example in the template
        # is double-braced so .format doesn't choke on it.
        formatted = COMPARISON_PROMPT_TEMPLATE.format(
            scenario_prompt="p",
            scenario_criteria="c",
            baseline_output="b",
            modified_output="m",
        )
        self.assertIn("BASELINE OUTPUT:", formatted)
        self.assertIn("MODIFIED OUTPUT:", formatted)
        # The literal JSON example survived single-brace escaping correctly.
        self.assertIn('{"verdict"', formatted)


class FormatComparisonPromptTest(unittest.TestCase):
    """Pin the brace-safe substitution contract.

    Real SKILL.md content routinely contains literal ``{`` / ``}`` (JSON
    examples, dict literals, format strings). The helper must survive that
    where Python's ``str.format()`` would raise ``KeyError``.
    """

    def _scenario(self) -> dict[str, Any]:
        return {"id": "s1", "prompt": "test prompt", "criteria": "test criteria"}

    def test_format_comparison_prompt_with_braces_in_content(self) -> None:
        # Baseline + modified both contain literal { and } - this is the
        # primary failure mode str.format() would hit.
        baseline = 'Example: {"score": 1.0, "passed": 18, "total": 18}'
        modified = 'Example: {"score": 0.94, "passed": 17, "total": 18}'
        result = format_comparison_prompt(self._scenario(), baseline, modified)

        # The literal brace-bearing content survived intact.
        self.assertIn('{"score": 1.0, "passed": 18, "total": 18}', result)
        self.assertIn('{"score": 0.94, "passed": 17, "total": 18}', result)
        # Both scenario fields also substituted.
        self.assertIn("test prompt", result)
        self.assertIn("test criteria", result)
        # None of the four placeholder tokens remain.
        for placeholder in (
            "{scenario_prompt}",
            "{scenario_criteria}",
            "{baseline_output}",
            "{modified_output}",
        ):
            self.assertNotIn(placeholder, result)

    def test_format_comparison_prompt_raises_on_missing_scenario_key(self) -> None:
        # Missing required key surfaces immediately rather than leaving a
        # half-rendered placeholder in the prompt.
        scenario = {"id": "s1", "prompt": "p"}  # 'criteria' missing
        with self.assertRaises(KeyError):
            format_comparison_prompt(scenario, "baseline", "modified")

    def test_format_comparison_prompt_str_format_baseline_would_have_failed(self) -> None:
        # Pin the contract: substituting via str.format() after the template
        # placeholders are already filled would re-interpret literal `{x}`
        # tokens in the baseline as new format keys and raise KeyError. The
        # safer .replace()-based helper survives this exact payload.
        # Realistic failure case: a SKILL.md fragment that contains `{name}`
        # in a code-fence example (e.g. a Python format-string demo).
        baseline_with_format_token = (
            'Example: f"hello {name}" produces "hello world" when name is set.'
        )
        # Demonstrate that the naive approach (substitute placeholders, then
        # try to .format the result) would explode on the embedded {name}.
        substituted = COMPARISON_PROMPT_TEMPLATE.format(
            scenario_prompt="p",
            scenario_criteria="c",
            baseline_output=baseline_with_format_token,
            modified_output="m",
        )
        with self.assertRaises((KeyError, IndexError, ValueError)):
            # If anything downstream re-runs .format on the substituted
            # prompt, the embedded `{name}` token explodes.
            substituted.format()
        # The brace-safe helper sidesteps this entirely because it doesn't
        # use .format() to substitute.
        safe = format_comparison_prompt(
            self._scenario(), baseline_with_format_token, "m"
        )
        self.assertIn("{name}", safe)


if __name__ == "__main__":
    unittest.main()
