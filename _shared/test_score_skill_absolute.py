"""Unit tests for the absolute grader aggregator (SIHC.2 prototype).

Covers six contracts from the SIHC.2 plan:
(a) v2.0 schema - per-category weights respected in weighted_score math.
(b) v1.x equal-weight fallback - missing category.weight defaults to 1/n_cats.
(c) N=3 median collapse - per-(scenario, assertion) majority vote, ties False.
(d) Ranking determinism - failures sorted by (-category_weight, assertion_id).
(e) passing_pairs is lex-sorted by (assertion_id, scenario_id).
(f) Malformed payload (missing 'verdict' AND 'result') raises informative KeyError.

Uses unittest TestCases (consistent with sibling test_score_skill.py); runs
under pytest. Inline JSON dicts keep the test surface minimal - no fixture
files.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Sibling import - same dir as the module under test.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from score_skill_absolute import (  # noqa: E402  (sys.path tweak above)
    _load_evals,
    _median_verdict,
    aggregate,
)


def _evals_v2(weights: tuple[float, float]) -> dict:
    """Build a v2.0-shape evals_data dict for two categories with given weights.

    Mirrors what _load_evals would produce: assertion 1 in cat A, assertion 2
    in cat B. Side-steps the file I/O so tests stay hermetic.
    """
    w_a, w_b = weights
    return {
        "by_id": {
            1: {
                "id": 1,
                "statement": "A1",
                "source": "src",
                "defect_type": "x",
                "category_name": "alpha",
                "category_weight": w_a,
            },
            2: {
                "id": 2,
                "statement": "B2",
                "source": "src",
                "defect_type": "y",
                "category_name": "beta",
                "category_weight": w_b,
            },
        },
        "categories": [
            {"name": "alpha", "weight": w_a, "evals": [{"id": 1}]},
            {"name": "beta", "weight": w_b, "evals": [{"id": 2}]},
        ],
        "raw": {},
    }


def _single_trial(sid: str, verdicts: dict) -> dict:
    return {"scenario_id": sid, "verdicts": verdicts}


class WeightedScoreV2SchemaTest(unittest.TestCase):
    """(a) v2.0 schema - category weights respected in weighted_score math."""

    def test_weighted_score_uses_per_category_weights(self) -> None:
        # cat alpha weight=0.8 (pass), cat beta weight=0.2 (fail).
        # Expected weighted = 0.8*1.0 + 0.2*0.0 = 0.8.
        evals = _evals_v2((0.8, 0.2))
        payload = {
            "trials": [
                _single_trial(
                    "s1",
                    {
                        "1": {"verdict": True, "reason": ""},
                        "2": {"verdict": False, "reason": ""},
                    },
                )
            ]
        }
        result = aggregate(payload, evals)
        self.assertAlmostEqual(result["weighted_score"], 0.8, places=6)
        # simple_score is just 1/2 - proves weighted != simple under v2.0.
        self.assertAlmostEqual(result["simple_score"], 0.5, places=6)
        self.assertNotAlmostEqual(result["weighted_score"], result["simple_score"])


class WeightedScoreV1FallbackTest(unittest.TestCase):
    """(b) v1.x - missing weight -> 1/n_cats, weighted collapses to simple."""

    def test_equal_weight_fallback_collapses_to_simple(self) -> None:
        # Two categories, weights default to 0.5 each => weighted == simple.
        evals = _evals_v2((0.5, 0.5))  # what _load_evals would produce
        payload = {
            "trials": [
                _single_trial(
                    "s1",
                    {
                        "1": {"verdict": True, "reason": ""},
                        "2": {"verdict": False, "reason": ""},
                    },
                )
            ]
        }
        result = aggregate(payload, evals)
        self.assertAlmostEqual(
            result["weighted_score"], result["simple_score"], places=6
        )
        self.assertAlmostEqual(result["weighted_score"], 0.5, places=6)

    def test_load_evals_fills_missing_weight_with_one_over_n_cats(self) -> None:
        # End-to-end exercise of _load_evals's `cat.get("weight", default_weight)`
        # branch. Tautological-test guard: if someone replaces .get(...) with
        # cat["weight"] (KeyError) or hard-codes 0.5, this test catches it where
        # the inline _evals_v2 helper cannot.
        v1_evals_doc = {
            "categories": [
                {
                    # No "weight" key - v1.x shape.
                    "name": "alpha",
                    "evals": [
                        {
                            "id": 1,
                            "statement": "A1",
                            "source": "src",
                            "defect_type": "x",
                        },
                    ],
                },
                {
                    # No "weight" key - v1.x shape.
                    "name": "beta",
                    "evals": [
                        {
                            "id": 2,
                            "statement": "B2",
                            "source": "src",
                            "defect_type": "y",
                        },
                    ],
                },
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as fh:
            json.dump(v1_evals_doc, fh)
            evals_path = Path(fh.name)
        try:
            evals = _load_evals(evals_path)
            # (i) Each assertion's category_weight is 1/n_cats = 1/2 = 0.5.
            self.assertAlmostEqual(evals["by_id"][1]["category_weight"], 0.5, places=6)
            self.assertAlmostEqual(evals["by_id"][2]["category_weight"], 0.5, places=6)
            # Normalized categories also carry the filled-in weight.
            for cat in evals["categories"]:
                self.assertAlmostEqual(cat["weight"], 0.5, places=6)
            # (ii) Downstream aggregate() produces weighted == simple under
            # the equal-weight fallback.
            payload = {
                "trials": [
                    _single_trial(
                        "s1",
                        {
                            "1": {"verdict": True, "reason": ""},
                            "2": {"verdict": False, "reason": ""},
                        },
                    )
                ]
            }
            result = aggregate(payload, evals)
            self.assertAlmostEqual(
                result["weighted_score"], result["simple_score"], places=6
            )
            self.assertAlmostEqual(result["weighted_score"], 0.5, places=6)
        finally:
            evals_path.unlink(missing_ok=True)


class MedianTrialCollapseTest(unittest.TestCase):
    """(c) N=3 median - per-(scenario, assertion) majority vote; ties -> False."""

    def test_three_trials_majority_true_passes(self) -> None:
        evals = _evals_v2((0.5, 0.5))
        # Same scenario s1, assertion 1: True, True, False → median True.
        payload = {
            "trials": [
                _single_trial("s1", {"1": {"verdict": True, "reason": "t1"}}),
                _single_trial("s1", {"1": {"verdict": True, "reason": "t2"}}),
                _single_trial("s1", {"1": {"verdict": False, "reason": "f1"}}),
            ]
        }
        result = aggregate(payload, evals)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["failed_assertions"], [])

    def test_three_trials_majority_false_fails(self) -> None:
        evals = _evals_v2((0.5, 0.5))
        payload = {
            "trials": [
                _single_trial("s1", {"1": {"verdict": False, "reason": "f1"}}),
                _single_trial("s1", {"1": {"verdict": False, "reason": "f2"}}),
                _single_trial("s1", {"1": {"verdict": True, "reason": "t1"}}),
            ]
        }
        result = aggregate(payload, evals)
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["total"], 1)
        self.assertEqual(len(result["failed_assertions"]), 1)

    def test_even_count_tie_resolves_to_false(self) -> None:
        # N=2 tie (1 True, 1 False) → strict resolves to False.
        self.assertFalse(_median_verdict([True, False]))
        self.assertFalse(_median_verdict([False, True]))
        # Symmetric N=4 tie.
        self.assertFalse(_median_verdict([True, True, False, False]))

    def test_legacy_result_key_tolerated(self) -> None:
        # Aggregator must tolerate {'result': bool} as well as {'verdict': bool}.
        evals = _evals_v2((0.5, 0.5))
        payload = {
            "trials": [
                _single_trial(
                    "s1",
                    {
                        "1": {"result": True, "reason": "legacy-key"},
                        "2": {"verdict": True, "reason": "canonical-key"},
                    },
                )
            ]
        }
        result = aggregate(payload, evals)
        self.assertEqual(result["passed"], 2)
        self.assertEqual(result["total"], 2)


class RankingDeterminismTest(unittest.TestCase):
    """(d) failures sorted by (-category_weight DESC, assertion_id ASC)."""

    def test_higher_weight_category_first_then_aid_ascending(self) -> None:
        # cat alpha (w=0.7) holds aid 2; cat beta (w=0.3) holds aid 1 and 3.
        # All fail. Expected failure order: aid 2 (high weight) first,
        # then aid 1 then aid 3 (lower weight, ascending aid).
        evals = {
            "by_id": {
                1: {
                    "id": 1,
                    "statement": "s1",
                    "source": "src",
                    "defect_type": "x",
                    "category_name": "beta",
                    "category_weight": 0.3,
                },
                2: {
                    "id": 2,
                    "statement": "s2",
                    "source": "src",
                    "defect_type": "x",
                    "category_name": "alpha",
                    "category_weight": 0.7,
                },
                3: {
                    "id": 3,
                    "statement": "s3",
                    "source": "src",
                    "defect_type": "x",
                    "category_name": "beta",
                    "category_weight": 0.3,
                },
            },
            "categories": [
                {"name": "alpha", "weight": 0.7, "evals": [{"id": 2}]},
                {"name": "beta", "weight": 0.3, "evals": [{"id": 1}, {"id": 3}]},
            ],
            "raw": {},
        }
        payload = {
            "trials": [
                _single_trial(
                    "sX",
                    {
                        "1": {"verdict": False, "reason": ""},
                        "2": {"verdict": False, "reason": ""},
                        "3": {"verdict": False, "reason": ""},
                    },
                )
            ]
        }
        # Run twice to pin determinism across re-runs.
        r1 = aggregate(payload, evals)
        r2 = aggregate(payload, evals)
        order1 = [f["assertion_id"] for f in r1["failed_assertions"]]
        order2 = [f["assertion_id"] for f in r2["failed_assertions"]]
        self.assertEqual(order1, [2, 1, 3])
        self.assertEqual(order1, order2)


class PassingPairsSortTest(unittest.TestCase):
    """(e) passing_pairs lex-sorted by (assertion_id, scenario_id)."""

    def test_passing_pairs_sorted_by_assertion_then_scenario(self) -> None:
        evals = _evals_v2((0.5, 0.5))
        # Two scenarios, both pass both assertions. Expected lex order:
        # (1, s_alpha), (1, s_beta), (2, s_alpha), (2, s_beta).
        payload = {
            "trials": [
                _single_trial(
                    "s_beta",
                    {
                        "1": {"verdict": True, "reason": ""},
                        "2": {"verdict": True, "reason": ""},
                    },
                ),
                _single_trial(
                    "s_alpha",
                    {
                        "1": {"verdict": True, "reason": ""},
                        "2": {"verdict": True, "reason": ""},
                    },
                ),
            ]
        }
        result = aggregate(payload, evals)
        pairs = [(p["assertion_id"], p["scenario_id"]) for p in result["passing_pairs"]]
        self.assertEqual(
            pairs,
            [(1, "s_alpha"), (1, "s_beta"), (2, "s_alpha"), (2, "s_beta")],
        )


class MalformedPayloadTest(unittest.TestCase):
    """(f) Missing both 'verdict' AND 'result' raises informative KeyError."""

    def test_missing_both_keys_raises_keyerror_with_ids(self) -> None:
        evals = _evals_v2((0.5, 0.5))
        payload = {
            "trials": [
                _single_trial(
                    "the_scenario",
                    {"1": {"reason": "neither verdict nor result key present"}},
                )
            ]
        }
        with self.assertRaises(KeyError) as ctx:
            aggregate(payload, evals)
        msg = str(ctx.exception)
        # Informative: must name both scenario_id and assertion_id.
        # Anchor on "assertion=1" so unrelated "1" tokens (counts, line
        # numbers, schema versions) can't satisfy the contract.
        self.assertIn("the_scenario", msg)
        self.assertIn("assertion=1", msg)


if __name__ == "__main__":
    unittest.main()
