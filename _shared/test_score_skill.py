"""Integration test for the composite scoring procedure (./score-skill.md).

Exercises the full composite procedure on a real SKILL.md (session-wrap's
current text). Per SIHC.2 Option A (2026-05-26) composite mode now composes
structural + the absolute-grader aggregator; the differential grader is
preserved for direct invocation via ``mode="differential"`` but no longer
called from composite mode.

Tests are real-not-mocked except for the absolute-grader verdict payload
(which is the documented orchestrator-LLM hand-off — the absolute
aggregator's own tests cover the per-assertion math) and the differential
dispatcher (the documented LLM seam).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

# Sibling import - this test file lives in the same dir as the module.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from score_skill_composite import (  # noqa: E402  (sys.path tweak above)
    ABSOLUTE_WEIGHT,
    GRADER_SYCOPHANCY_CRASH_CLASS,
    STRUCTURAL_WEIGHT,
    CompositeScore,
    GoldensStatus,
    main,
    score_composite,
    verify_goldens,
)

# Path to the real session-wrap SKILL.md in the workspace. The integration
# test reads this file for the structural axis; absolute verdicts are
# injected via a synthetic payload so the test is hermetic on the absolute
# side.
WORKSPACE_ROOT = THIS_DIR.parent.parent.parent
SESSION_WRAP_SKILL_MD = (
    WORKSPACE_ROOT / ".claude" / "skills" / "session-wrap" / "SKILL.md"
)


# --- Absolute-axis fixtures -------------------------------------------------


def _write_minimal_evals(parent: Path) -> Path:
    """Write a tiny v2.0 evals.json fixture (2 categories, 2 assertions).

    Equal weights so weighted_score collapses to simple_score; tests that
    care about the weighting math live in test_score_skill_absolute.py.
    """
    evals_path = parent / "evals.json"
    evals_path.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "name": "alpha",
                        "weight": 0.5,
                        "evals": [
                            {
                                "id": 1,
                                "statement": "stub-1",
                                "source": "src",
                                "defect_type": "x",
                            }
                        ],
                    },
                    {
                        "name": "beta",
                        "weight": 0.5,
                        "evals": [
                            {
                                "id": 2,
                                "statement": "stub-2",
                                "source": "src",
                                "defect_type": "y",
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return evals_path


def _all_pass_verdicts() -> dict:
    """Synthetic absolute-grader payload: both assertions pass in one trial.

    Pairs with :func:`_write_minimal_evals` (assertion ids 1 + 2).
    """
    return {
        "trials": [
            {
                "scenario_id": "scenario_synth",
                "verdicts": {
                    "1": {"verdict": True, "reason": "pass"},
                    "2": {"verdict": True, "reason": "pass"},
                },
            }
        ]
    }


def _stub_same(_baseline: str, _modified: str, scenario: dict) -> object:
    """Inline stub dispatcher that returns 'same' for every scenario.

    Used by the differential-only mode tests. Avoids needing to import
    ScenarioVerdict at module-top by deferring to a local import.
    """
    from differential_grader import ScenarioVerdict

    return ScenarioVerdict(
        scenario_id=str(scenario.get("id", "<no-id>")),
        verdict="same",
        reason="test stub",
    )


# --- Composite-mode integration (SIHC.2 Option A: structural + absolute) ---


class CompositeScoreOnRealSessionWrapTest(unittest.TestCase):
    """Smoke gate per build-step done-when criterion + plan §7 Step 5."""

    @classmethod
    def setUpClass(cls) -> None:
        # If session-wrap is missing from the workspace this test cannot
        # run - surface as a skip rather than a hard failure so the test
        # suite still passes in odd workspace layouts.
        if not SESSION_WRAP_SKILL_MD.is_file():
            raise unittest.SkipTest(
                f"session-wrap SKILL.md missing at {SESSION_WRAP_SKILL_MD} - "
                "test requires the real workspace SKILL.md to integration-test"
            )

    def test_composite_score_on_session_wrap_returns_documented_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=_all_pass_verdicts(),
                evals_path=evals_path,
            )

        # Shape contract from ./score-skill.md § Output contract.
        self.assertIsInstance(result, CompositeScore)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.passed, 2)
        self.assertEqual(result.total, 2)
        self.assertIsNotNone(result.score)
        # score must be in [0, 1]; the integration test pins the bounds and
        # also a non-trivial floor so a future refactor that returns 0.0 or
        # 1.0 silently is caught.
        assert result.score is not None  # mypy/type narrowing
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)

    def test_composite_score_matches_predicted_smoke_value(self) -> None:
        # Per ./score-skill.md § Composite-mode worked example:
        #   structural ≈ 0.91, absolute_weighted = 1.0 (all-pass payload) ->
        #   final = 0.4 * structural + 0.6 * 1.0
        # Asserts the composition arithmetic is wired correctly.
        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=_all_pass_verdicts(),
                evals_path=evals_path,
            )

        assert result.score is not None
        # All-pass payload → absolute_weighted = 1.0 deterministically;
        # structural is whatever session-wrap currently scores. Compute the
        # expected composite from the structural axis directly and compare
        # with a tight tolerance so this test doesn't drift when session-wrap
        # is edited (the structural delta flows through unchanged).
        from structural_metrics import score_skill as run_structural

        structural_for_compare = run_structural(SESSION_WRAP_SKILL_MD).score
        expected = STRUCTURAL_WEIGHT * structural_for_compare + ABSOLUTE_WEIGHT * 1.0
        self.assertAlmostEqual(result.score, expected, places=9)

    def test_structural_only_mode_skips_absolute_and_differential(self) -> None:
        # Structural-only mode must not invoke any axis other than structural.
        sentinel = {"called": False}

        def _explode(*_a, **_kw) -> object:
            sentinel["called"] = True
            raise AssertionError("dispatcher must not be called in structural mode")

        result = score_composite(
            skill_md_path=SESSION_WRAP_SKILL_MD,
            baseline_skill_md=SESSION_WRAP_SKILL_MD,
            modified_skill_md=SESSION_WRAP_SKILL_MD,
            scenarios_path=None,
            mode="structural",
            dispatch_comparison=_explode,
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.total, 1)
        assert result.score is not None
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)
        self.assertFalse(sentinel["called"])

    def test_structural_only_mode_missing_skill_md_returns_harness_error(self) -> None:
        # In single-axis modes there is no other axis to partial-succeed
        # through; structural-only with a missing SKILL.md must still emit
        # harness-error with total=1.
        result = score_composite(
            skill_md_path=THIS_DIR / "definitely-does-not-exist.md",
            baseline_skill_md=SESSION_WRAP_SKILL_MD,
            modified_skill_md=SESSION_WRAP_SKILL_MD,
            scenarios_path=None,
            mode="structural",
        )
        self.assertEqual(result.status, "harness-error")
        self.assertIsNone(result.score)
        self.assertEqual(result.passed, 0)
        self.assertEqual(result.total, 1)


class CompositeWeightsContractTest(unittest.TestCase):
    def test_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(STRUCTURAL_WEIGHT + ABSOLUTE_WEIGHT, 1.0, places=9)

    def test_absolute_weight_dominant(self) -> None:
        # Per SIHC.2 Option A: absolute_weighted should weight higher because
        # it's the discriminating axis.
        self.assertGreater(ABSOLUTE_WEIGHT, STRUCTURAL_WEIGHT)

    def test_weight_constants_in_doc_match_python(self) -> None:
        """score-skill.md must agree with score_skill_composite.py on weights.

        Pins the doc-vs-code sync so future edits to either side that drift
        the documented weights fail loudly. The wrapper is the canonical
        source per ./score-skill.md § Composition weights ("To rebalance the
        mix, edit both constants in score_skill_composite.py"); this test
        keeps the doc in lockstep.
        """
        import re

        # score-skill.md sits as a sibling of test_score_skill.py.
        doc_path = THIS_DIR / "score-skill.md"
        self.assertTrue(
            doc_path.is_file(),
            f"score-skill.md must exist as sibling of this test: {doc_path}",
        )
        doc = doc_path.read_text(encoding="utf-8")
        struct_match = re.search(r"STRUCTURAL_WEIGHT\s*=\s*([0-9]+(?:\.[0-9]+)?)", doc)
        abs_match = re.search(r"ABSOLUTE_WEIGHT\s*=\s*([0-9]+(?:\.[0-9]+)?)", doc)
        self.assertIsNotNone(
            struct_match,
            "score-skill.md must document STRUCTURAL_WEIGHT = <num>",
        )
        self.assertIsNotNone(
            abs_match,
            "score-skill.md must document ABSOLUTE_WEIGHT = <num>",
        )
        self.assertEqual(float(struct_match.group(1)), STRUCTURAL_WEIGHT)
        self.assertEqual(float(abs_match.group(1)), ABSOLUTE_WEIGHT)


class CompositePartialSuccessTest(unittest.TestCase):
    """Per-axis exception scoping for the composite mode (SIHC.2 Option A).

    Composite mode tolerates one axis failing with a documented harness
    exception (FileNotFoundError on structural; FileNotFoundError, KeyError,
    or ValueError on the absolute aggregator) and still emits status="ok"
    with passed=1, total=2. Both axes failing emits harness-error.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not SESSION_WRAP_SKILL_MD.is_file():
            raise unittest.SkipTest(
                f"session-wrap SKILL.md missing at {SESSION_WRAP_SKILL_MD}"
            )

    def test_structural_ok_absolute_broken_returns_partial(self) -> None:
        # Pass a non-existent evals_path → FileNotFoundError inside the
        # absolute branch's _load_evals; structural still scores.
        with tempfile.TemporaryDirectory() as td:
            missing_evals = Path(td) / "no-such-evals.json"

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=_all_pass_verdicts(),
                evals_path=missing_evals,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.total, 2)
        assert result.score is not None
        from structural_metrics import score_skill as run_structural

        structural_expected = run_structural(SESSION_WRAP_SKILL_MD).score
        self.assertAlmostEqual(result.score, structural_expected, places=9)

    def test_absolute_ok_structural_broken_returns_partial(self) -> None:
        # Inverse: structural raises (missing SKILL.md), absolute succeeds.
        # Result should be absolute_weighted (=1.0 for the all-pass payload)
        # with passed=1, total=2.
        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))

            result = score_composite(
                skill_md_path=THIS_DIR / "definitely-does-not-exist.md",
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=_all_pass_verdicts(),
                evals_path=evals_path,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.total, 2)
        assert result.score is not None
        self.assertAlmostEqual(result.score, 1.0, places=9)

    def test_both_axes_broken_returns_harness_error(self) -> None:
        # Missing SKILL.md + missing evals → both axes raise → harness-error.
        with tempfile.TemporaryDirectory() as td:
            missing_evals = Path(td) / "no-such-evals.json"

            result = score_composite(
                skill_md_path=THIS_DIR / "definitely-does-not-exist.md",
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=_all_pass_verdicts(),
                evals_path=missing_evals,
            )

        self.assertEqual(result.status, "harness-error")
        self.assertIsNone(result.score)
        self.assertEqual(result.passed, 0)
        self.assertEqual(result.total, 2)

    def test_malformed_verdicts_payload_returns_partial(self) -> None:
        # KeyError from the absolute aggregator on a malformed payload is in
        # the documented harness-exception list for the absolute axis;
        # structural still scores → partial success.
        bogus_verdicts = {
            "trials": [
                {
                    "scenario_id": "synth",
                    "verdicts": {
                        # Missing both 'verdict' and 'result' keys → KeyError.
                        "1": {"reason": "malformed"},
                    },
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=bogus_verdicts,
                evals_path=evals_path,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.passed, 1)
        self.assertEqual(result.total, 2)


# --- New composite-mode contract tests (SIHC.2 Option A) ---


class CompositeAbsoluteRequiredInputsTest(unittest.TestCase):
    """Composite mode requires absolute_verdicts + evals_path per SIHC.2."""

    @classmethod
    def setUpClass(cls) -> None:
        if not SESSION_WRAP_SKILL_MD.is_file():
            raise unittest.SkipTest(
                f"session-wrap SKILL.md missing at {SESSION_WRAP_SKILL_MD}"
            )

    def test_composite_with_absolute_verdicts_produces_weighted_score(self) -> None:
        # Synthesize a tiny evals.json + an all-pass payload; assert the
        # composite math is 0.4 * structural + 0.6 * 1.0.
        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=_all_pass_verdicts(),
                evals_path=evals_path,
            )

        from structural_metrics import score_skill as run_structural

        structural_expected = run_structural(SESSION_WRAP_SKILL_MD).score
        expected = STRUCTURAL_WEIGHT * structural_expected + ABSOLUTE_WEIGHT * 1.0
        assert result.score is not None
        self.assertAlmostEqual(result.score, expected, places=9)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.passed, 2)
        self.assertEqual(result.total, 2)

    def test_composite_without_absolute_verdicts_returns_harness_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=None,
                evals_path=evals_path,
            )

        self.assertEqual(result.status, "harness-error")
        self.assertIsNone(result.score)
        self.assertEqual(result.passed, 0)
        self.assertEqual(result.total, 2)

    def test_composite_without_evals_path_returns_harness_error(self) -> None:
        result = score_composite(
            skill_md_path=SESSION_WRAP_SKILL_MD,
            baseline_skill_md=SESSION_WRAP_SKILL_MD,
            modified_skill_md=SESSION_WRAP_SKILL_MD,
            scenarios_path=None,
            mode="composite",
            absolute_verdicts=_all_pass_verdicts(),
            evals_path=None,
        )

        self.assertEqual(result.status, "harness-error")
        self.assertIsNone(result.score)
        self.assertEqual(result.passed, 0)
        self.assertEqual(result.total, 2)


class CompositeNoLongerInvokesGoldensTest(unittest.TestCase):
    """Per SIHC.2 Option A: composite mode no longer auto-invokes verify_goldens."""

    @classmethod
    def setUpClass(cls) -> None:
        if not SESSION_WRAP_SKILL_MD.is_file():
            raise unittest.SkipTest(
                f"session-wrap SKILL.md missing at {SESSION_WRAP_SKILL_MD}"
            )

    def test_composite_no_longer_invokes_verify_goldens(self) -> None:
        # Wire a skill_dir that would normally trigger sycophancy detection
        # (good + bad both score 0.5 via the injected score_single_fn).
        # If composite still auto-invoked verify_goldens, halt_requested
        # would be True. SIHC.2 Option A says NO.
        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))
            skill_dir = _make_skill_dir_with_goldens(
                Path(td), bad_files={"bad_sneaky.md": "sneaky"}
            )

            def _sycophantic(_path: Path) -> float:
                raise AssertionError(
                    "verify_goldens must NOT be invoked from composite mode per SIHC.2"
                )

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=None,
                mode="composite",
                absolute_verdicts=_all_pass_verdicts(),
                evals_path=evals_path,
                skill_dir=skill_dir,
                score_single_fn=_sycophantic,
            )

        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.goldens_status)
        self.assertFalse(result.halt_requested)


class DifferentialOnlyModeStillWorksTest(unittest.TestCase):
    """Differential-only mode (mode="differential") is preserved unchanged."""

    @classmethod
    def setUpClass(cls) -> None:
        if not SESSION_WRAP_SKILL_MD.is_file():
            raise unittest.SkipTest(
                f"session-wrap SKILL.md missing at {SESSION_WRAP_SKILL_MD}"
            )

    def test_differential_mode_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            scenarios_path = Path(td) / "test_scenarios.json"
            scenarios_path.write_text(
                json.dumps([{"id": "s1", "prompt": "p", "criteria": "c"}]),
                encoding="utf-8",
            )

            result = score_composite(
                skill_md_path=SESSION_WRAP_SKILL_MD,
                baseline_skill_md=SESSION_WRAP_SKILL_MD,
                modified_skill_md=SESSION_WRAP_SKILL_MD,
                scenarios_path=scenarios_path,
                mode="differential",
                dispatch_comparison=_stub_same,
            )

        # All-same stub on 1 scenario → neutral 0.5.
        self.assertEqual(result.status, "ok")
        assert result.score is not None
        self.assertAlmostEqual(result.score, 0.5, places=9)


# --- CLI smoke -------------------------------------------------------------


class CLITest(unittest.TestCase):
    def test_cli_smoke_with_absolute_verdicts_against_session_wrap(self) -> None:
        if not SESSION_WRAP_SKILL_MD.is_file():
            self.skipTest(f"session-wrap SKILL.md missing at {SESSION_WRAP_SKILL_MD}")

        with tempfile.TemporaryDirectory() as td:
            evals_path = _write_minimal_evals(Path(td))
            verdicts_path = Path(td) / "verdicts.json"
            verdicts_path.write_text(json.dumps(_all_pass_verdicts()), encoding="utf-8")

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "--skill-md",
                        str(SESSION_WRAP_SKILL_MD),
                        "--baseline",
                        str(SESSION_WRAP_SKILL_MD),
                        "--modified",
                        str(SESSION_WRAP_SKILL_MD),
                        "--mode",
                        "composite",
                        "--absolute-verdicts",
                        str(verdicts_path),
                        "--evals",
                        str(evals_path),
                    ]
                )

        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["passed"], 2)
        self.assertEqual(payload["total"], 2)
        self.assertGreaterEqual(payload["score"], 0.0)
        self.assertLessEqual(payload["score"], 1.0)


def _make_skill_dir_with_goldens(
    parent: Path,
    *,
    good_content: str = "good content",
    bad_files: dict[str, str] | None = None,
    extra_files: dict[str, str] | None = None,
    include_good: bool = True,
) -> Path:
    """Build a synthetic per-skill directory with an evals/golden/ corpus.

    Creates ``<parent>/synthetic-skill/evals/golden/`` populated with the
    requested good.md + bad_*.md fixtures. ``extra_files`` populates
    additional files alongside the goldens (manifest.json, random.txt, etc.)
    so tests can assert the goldens loader correctly skips non-bad files.
    """
    skill_dir = parent / "synthetic-skill"
    golden_dir = skill_dir / "evals" / "golden"
    golden_dir.mkdir(parents=True)
    if include_good:
        (golden_dir / "good.md").write_text(good_content, encoding="utf-8")
    for filename, content in (bad_files or {}).items():
        (golden_dir / filename).write_text(content, encoding="utf-8")
    for filename, content in (extra_files or {}).items():
        (golden_dir / filename).write_text(content, encoding="utf-8")
    return skill_dir


class VerifyGoldensTest(unittest.TestCase):
    """Unit tests for :func:`verify_goldens` (preserved per SIHC.2 Option A).

    Composite mode no longer auto-invokes :func:`verify_goldens`, but the
    function itself is preserved and remains importable + directly callable.
    These tests pin its behavior so direct callers (and the differential-
    only-mode path that still wires goldens) keep working.
    """

    def test_verify_goldens_returns_no_goldens_found_when_dir_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = Path(td) / "skill-with-no-goldens"
            skill_dir.mkdir()  # skill exists, but no evals/golden/

            def _explode(_path: Path) -> float:
                raise AssertionError(
                    "score_single_fn must NOT be called when goldens absent"
                )

            result = verify_goldens(skill_dir, _explode)

        self.assertIsInstance(result, GoldensStatus)
        self.assertEqual(result.status, "no-goldens-found")
        self.assertIsNone(result.good_score)
        self.assertIsNone(result.bad_scores)
        self.assertEqual(result.sycophantic_bads, [])
        self.assertIn("no goldens dir", result.reason)

    def test_verify_goldens_returns_no_goldens_found_when_good_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(
                Path(td),
                bad_files={"bad_x.md": "bad-only"},
                include_good=False,
            )

            def _explode(_path: Path) -> float:
                raise AssertionError(
                    "score_single_fn must NOT be called when good.md is missing"
                )

            result = verify_goldens(skill_dir, _explode)

        self.assertEqual(result.status, "no-goldens-found")
        self.assertIsNone(result.good_score)
        self.assertIsNone(result.bad_scores)
        self.assertEqual(result.sycophantic_bads, [])
        self.assertIn("good.md", result.reason)

    def test_verify_goldens_returns_ok_when_all_bads_discriminate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(
                Path(td),
                good_content="good",
                bad_files={
                    "bad_one.md": "bad1",
                    "bad_two.md": "bad2",
                    "bad_three.md": "bad3",
                },
            )

            score_map = {
                "good.md": 0.9,
                "bad_one.md": 0.1,
                "bad_two.md": 0.2,
                "bad_three.md": 0.3,
            }

            def _score(path: Path) -> float:
                return score_map[path.name]

            result = verify_goldens(skill_dir, _score)

        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.good_score, 0.9)
        self.assertEqual(result.sycophantic_bads, [])
        assert result.bad_scores is not None
        self.assertEqual(len(result.bad_scores), 3)
        for entry in result.bad_scores:
            self.assertTrue(entry["discriminated"], entry)

    def test_verify_goldens_detects_sycophantic_bad_at_equal_score(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(
                Path(td),
                bad_files={"bad_one.md": "tied"},
            )

            def _score(path: Path) -> float:
                return 0.5  # good == bad => tie => fail

            result = verify_goldens(skill_dir, _score)

        self.assertEqual(result.status, "harness-error")
        self.assertEqual(result.sycophantic_bads, ["bad_one.md"])
        self.assertIn("sycophantic", result.reason)
        assert result.bad_scores is not None
        self.assertFalse(result.bad_scores[0]["discriminated"])

    def test_verify_goldens_detects_sycophantic_bad_at_higher_score(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(
                Path(td),
                bad_files={"bad_one.md": "bad"},
            )

            def _score(path: Path) -> float:
                return 0.8 if path.name == "bad_one.md" else 0.5

            result = verify_goldens(skill_dir, _score)

        self.assertEqual(result.status, "harness-error")
        self.assertEqual(result.sycophantic_bads, ["bad_one.md"])
        assert result.bad_scores is not None
        self.assertAlmostEqual(result.bad_scores[0]["score"], 0.8)

    def test_verify_goldens_lists_all_sycophantic_bads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(
                Path(td),
                bad_files={
                    "bad_a.md": "a",
                    "bad_b.md": "b",
                    "bad_c.md": "c",
                    "bad_d.md": "d",
                    "bad_e.md": "e",
                },
            )

            score_map = {
                "good.md": 0.5,
                "bad_a.md": 0.1,
                "bad_b.md": 0.5,  # tie => fail
                "bad_c.md": 0.2,
                "bad_d.md": 0.7,  # higher => fail
                "bad_e.md": 0.3,
            }

            def _score(path: Path) -> float:
                return score_map[path.name]

            result = verify_goldens(skill_dir, _score)

        self.assertEqual(result.status, "harness-error")
        self.assertEqual(sorted(result.sycophantic_bads), ["bad_b.md", "bad_d.md"])
        self.assertIn("bad_b.md", result.reason)
        self.assertIn("bad_d.md", result.reason)
        assert result.bad_scores is not None
        flags = {entry["file"]: entry["discriminated"] for entry in result.bad_scores}
        self.assertFalse(flags["bad_b.md"])
        self.assertFalse(flags["bad_d.md"])
        self.assertTrue(flags["bad_a.md"])
        self.assertTrue(flags["bad_c.md"])
        self.assertTrue(flags["bad_e.md"])

    def test_verify_goldens_with_only_good_no_bads(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(Path(td), bad_files={})

            def _score(_path: Path) -> float:
                return 0.7

            result = verify_goldens(skill_dir, _score)

        self.assertEqual(result.status, "ok")
        self.assertAlmostEqual(result.good_score, 0.7)
        self.assertEqual(result.bad_scores, [])
        self.assertEqual(result.sycophantic_bads, [])
        self.assertIn("vacuously", result.reason)

    def test_verify_goldens_skips_manifest_json_and_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(
                Path(td),
                bad_files={"bad_x.md": "bad-x"},
                extra_files={
                    "manifest.json": '{"manifest_version": 2}',
                    "random.txt": "random",
                    "good_extra.md": "should-be-skipped",
                    "notes.md": "operator notes",
                },
            )

            scored: list[str] = []

            def _score(path: Path) -> float:
                scored.append(path.name)
                if path.name == "good.md":
                    return 0.9
                return 0.1

            result = verify_goldens(skill_dir, _score)

        self.assertEqual(result.status, "ok")
        self.assertEqual(sorted(scored), ["bad_x.md", "good.md"])
        assert result.bad_scores is not None
        self.assertEqual(len(result.bad_scores), 1)
        self.assertEqual(result.bad_scores[0]["file"], "bad_x.md")

    def test_verify_goldens_ignores_bad_md_without_underscore_and_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = _make_skill_dir_with_goldens(
                Path(td),
                bad_files={"bad_x.md": "legit-bad"},
                extra_files={
                    "bad.md": "no-underscore-must-be-excluded",
                    "bad_x.md.tmp": "atomic-write-artifact-must-be-excluded",
                    "bad_.md": "underscore-but-empty-slug-matches-current-glob",
                },
            )

            scored: list[str] = []

            def _score(path: Path) -> float:
                scored.append(path.name)
                if path.name == "good.md":
                    return 0.9
                return 0.1

            result = verify_goldens(skill_dir, _score)

        self.assertEqual(result.status, "ok")
        self.assertNotIn("bad.md", scored)
        self.assertNotIn("bad_x.md.tmp", scored)
        assert result.bad_scores is not None
        bad_filenames = {entry["file"] for entry in result.bad_scores}
        self.assertNotIn("bad.md", bad_filenames)
        self.assertNotIn("bad_x.md.tmp", bad_filenames)
        self.assertIn("bad_x.md", scored)
        self.assertIn("bad_x.md", bad_filenames)


class GraderSycophancyConstantTest(unittest.TestCase):
    """Pins the SIHC Step 12 crash-class constant — still imported by callers."""

    def test_crash_class_constant_is_wired(self) -> None:
        self.assertIn("harness-error", GRADER_SYCOPHANCY_CRASH_CLASS)
        self.assertIn("sycophancy", GRADER_SYCOPHANCY_CRASH_CLASS)


if __name__ == "__main__":
    unittest.main()
