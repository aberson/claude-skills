"""Pytest sibling tests for calibrate_judge.py.

Covers the Phase-2 calibration matrix with inline fixtures via tmp_path:
- Cohen's kappa hand-computed fixture (known 2x2 -> kappa == 0.40);
- compute_agreement edge cases (empty -> ValueError; perfect-chance degenerate);
- position-consistency (basic + empty -> 1.0);
- calibrate(ci) PASS on a healthy seed;
- mislabeled-gold FAIL (agreement check);
- stale-snapshot FAIL (freshness check, injected `now`);
- bad>=good discrimination FAIL (discrimination teeth);
- calibrate(mode="full") raises NotImplementedError;
- verify_discrimination makes NO LLM call (pure function of recorded scores).

Pure stdlib + pytest. No fixture files; everything is built inline under
tmp_path. Mirrors the sibling-import convention from
test_score_skill_absolute.py.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

# Sibling import - same dir as the module under test.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from calibrate_judge import (  # noqa: E402  (sys.path tweak above)
    FRESHNESS_MAX_AGE_DAYS,
    _write_synthetic_skill,
    calibrate,
    check_freshness,
    compute_agreement,
    compute_position_consistency,
    load_gold,
    verify_discrimination,
)


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------


def _kappa_lists() -> tuple[list[str], list[str]]:
    """50-pair lists matching the hand-computed fixture.

    both-YES=20, both-NO=15, judged-YES/gold-NO=5, judged-NO/gold-YES=10.
    -> p_o = 0.70, p_e = 0.50, kappa = 0.40.
    """
    judged = ["YES"] * 20 + ["NO"] * 15 + ["YES"] * 5 + ["NO"] * 10
    gold = ["YES"] * 20 + ["NO"] * 15 + ["NO"] * 5 + ["YES"] * 10
    return judged, gold


def test_kappa_hand_computed_fixture_is_0_40() -> None:
    judged, gold = _kappa_lists()
    out = compute_agreement(judged, gold)
    assert abs(out["agreement_pct"] - 0.70) < 1e-9
    assert abs(out["cohen_kappa"] - 0.40) < 1e-9


def test_compute_agreement_empty_raises() -> None:
    with pytest.raises(ValueError):
        compute_agreement([], [])


def test_compute_agreement_unequal_length_raises() -> None:
    with pytest.raises(ValueError):
        compute_agreement(["PASS"], ["PASS", "PASS"])


def test_compute_agreement_perfect_chance_degenerate() -> None:
    # Single category on both sides: p_e == 1.0, (1 - p_e) == 0. Convention:
    # kappa == 1.0 when observed agreement is also perfect.
    out = compute_agreement(["PASS", "PASS"], ["PASS", "PASS"])
    assert out["agreement_pct"] == 1.0
    assert out["cohen_kappa"] == 1.0


def test_compute_agreement_perfect_real_agreement() -> None:
    # Two categories, all-equal -> p_o == 1.0, kappa == 1.0 (non-degenerate).
    out = compute_agreement(["PASS", "NEEDS-WORK"], ["PASS", "NEEDS-WORK"])
    assert out["agreement_pct"] == 1.0
    assert abs(out["cohen_kappa"] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# position consistency
# ---------------------------------------------------------------------------


def test_position_consistency_basic() -> None:
    assert compute_position_consistency([("PASS", "PASS"), ("PASS", "PASS")]) == 1.0
    assert compute_position_consistency([("PASS", "PASS"), ("PASS", "FAIL")]) == 0.5
    assert compute_position_consistency([("PASS", "FAIL")]) == 0.0


def test_position_consistency_empty_is_one() -> None:
    assert compute_position_consistency([]) == 1.0


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------


def test_check_freshness_fresh_and_stale() -> None:
    now = date(2026, 6, 22)
    # 10 days old -> fresh.
    assert check_freshness("2026-06-12T00:00:00Z", now=now) is True
    # Exactly at the boundary -> fresh (age <= max).
    boundary = date(2026, 6, 22).toordinal() - FRESHNESS_MAX_AGE_DAYS
    assert check_freshness(date.fromordinal(boundary).isoformat(), now=now) is True
    # Well past the boundary -> stale.
    assert check_freshness("2023-01-01", now=now) is False


# ---------------------------------------------------------------------------
# load_gold
# ---------------------------------------------------------------------------


def test_load_gold_round_trip(tmp_path: Path) -> None:
    _write_synthetic_skill(tmp_path)
    gold = load_gold(tmp_path)
    fixtures = {g["fixture"] for g in gold}
    assert fixtures == {"good.md", "bad_1.md", "bad_2.md"}
    good = next(g for g in gold if g["fixture"] == "good.md")
    assert good["verdict"] == "PASS"


def test_load_gold_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_gold(tmp_path)  # no evals/golden/verdicts.jsonl


# ---------------------------------------------------------------------------
# calibrate(ci) -- the gate matrix
# ---------------------------------------------------------------------------


def test_calibrate_ci_pass_on_healthy_seed(tmp_path: Path) -> None:
    _write_synthetic_skill(tmp_path)
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is True
    assert res["reasons"] == []
    assert res["checks"]["freshness"]["passed"] is True
    assert res["checks"]["discrimination"]["passed"] is True
    assert res["checks"]["agreement"]["passed"] is True
    # A correct seed yields perfect agreement -> kappa 1.0 by construction.
    assert res["checks"]["agreement"]["cohen_kappa"] == 1.0


def test_calibrate_ci_mislabeled_gold_fails(tmp_path: Path) -> None:
    _write_synthetic_skill(tmp_path)
    gold_path = tmp_path / "evals" / "golden" / "verdicts.jsonl"
    lines = gold_path.read_text(encoding="utf-8").splitlines()
    flipped = []
    for line in lines:
        obj = json.loads(line)
        if obj["fixture"] == "good.md":
            obj["verdict"] = "NEEDS-WORK"  # flip away from recorded PASS
        flipped.append(json.dumps(obj))
    gold_path.write_text("\n".join(flipped) + "\n", encoding="utf-8")

    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert res["checks"]["agreement"]["passed"] is False
    assert res["checks"]["agreement"]["agreement_pct"] < 1.0


def test_calibrate_ci_stale_fails(tmp_path: Path) -> None:
    _write_synthetic_skill(tmp_path, generated_at="2023-01-01T00:00:00Z")
    res = calibrate(tmp_path, mode="ci", now=date(2026, 6, 22))
    assert res["passed"] is False
    assert res["checks"]["freshness"]["passed"] is False


def test_calibrate_ci_bad_ge_good_discrimination_fails(tmp_path: Path) -> None:
    _write_synthetic_skill(
        tmp_path,
        good_score=0.5,
        bad_scores={"bad_1.md": 0.6, "bad_2.md": 0.2},
    )
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    disc = res["checks"]["discrimination"]
    assert disc["passed"] is False
    assert "bad_1.md" in disc["sycophantic_bads"]


def test_calibrate_ci_missing_artifacts_fail_closed(tmp_path: Path) -> None:
    # No evals/golden at all -> fail closed, no uncaught crash.
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert res["reasons"]  # at least one reason recorded


def test_calibrate_full_raises_not_implemented(tmp_path: Path) -> None:
    _write_synthetic_skill(tmp_path)
    with pytest.raises(NotImplementedError):
        calibrate(tmp_path, mode="full")


def test_calibrate_unknown_mode_raises(tmp_path: Path) -> None:
    _write_synthetic_skill(tmp_path)
    with pytest.raises(ValueError):
        calibrate(tmp_path, mode="bogus")


# ---------------------------------------------------------------------------
# calibrate(ci) -- fail-closed paths (the contract's central promise: a
# malformed / missing / surprising artifact never crashes; it returns
# passed:False with a recorded reason).
# ---------------------------------------------------------------------------


def test_calibrate_ci_malformed_verdicts_jsonl_fail_closed(tmp_path: Path) -> None:
    # An invalid JSON line in verdicts.jsonl -> json.JSONDecodeError during
    # load_gold -> caught by the artifact-load guard -> passed False, no crash.
    _write_synthetic_skill(tmp_path)
    gold_path = tmp_path / "evals" / "golden" / "verdicts.jsonl"
    gold_path.write_text(
        '{"fixture": "good.md", "verdict": "PASS"}\n{not valid json\n',
        encoding="utf-8",
    )
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert any("artifact load failed" in r for r in res["reasons"])


def test_calibrate_ci_malformed_recorded_scores_fail_closed(tmp_path: Path) -> None:
    # Invalid JSON in recorded_scores.json -> json.JSONDecodeError during load
    # -> caught -> passed False, no crash.
    _write_synthetic_skill(tmp_path)
    rec_path = tmp_path / "evals" / "golden" / "recorded_scores.json"
    rec_path.write_text("{ this is not json", encoding="utf-8")
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert any("artifact load failed" in r for r in res["reasons"])


def test_calibrate_ci_missing_generated_at_fail_closed(tmp_path: Path) -> None:
    # recorded_scores.json without 'generated_at' -> KeyError inside the
    # freshness check -> caught there -> passed False, no uncaught crash.
    _write_synthetic_skill(tmp_path)
    rec_path = tmp_path / "evals" / "golden" / "recorded_scores.json"
    recorded = json.loads(rec_path.read_text(encoding="utf-8"))
    del recorded["generated_at"]
    rec_path.write_text(json.dumps(recorded), encoding="utf-8")
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert res["checks"]["freshness"]["passed"] is False
    assert "error" in res["checks"]["freshness"]


def test_calibrate_ci_scores_not_dict_fail_closed(tmp_path: Path) -> None:
    # FIX #1 REGRESSION GUARD (the most important new test): 'scores' is a list
    # (could equally be null). Without the structural validation, the
    # discrimination lambda would raise TypeError INSIDE verify_goldens and
    # escape uncaught. With the guard, calibrate fails closed at artifact load.
    _write_synthetic_skill(tmp_path)
    rec_path = tmp_path / "evals" / "golden" / "recorded_scores.json"
    recorded = json.loads(rec_path.read_text(encoding="utf-8"))
    recorded["scores"] = ["good.md", "bad_1.md"]  # a list, not a dict
    rec_path.write_text(json.dumps(recorded), encoding="utf-8")
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert any(
        "malformed recorded_scores" in r for r in res["reasons"]
    ), res["reasons"]

    # Also exercise the null variant -> same fail-closed path, no crash.
    recorded["scores"] = None
    rec_path.write_text(json.dumps(recorded), encoding="utf-8")
    res_null = calibrate(tmp_path, mode="ci")
    assert res_null["passed"] is False
    assert any(
        "malformed recorded_scores" in r for r in res_null["reasons"]
    ), res_null["reasons"]


def test_calibrate_ci_missing_fixture_in_scores_fail_closed(tmp_path: Path) -> None:
    # good.md exists on disk but is absent from the 'scores' map. The
    # discrimination lambda raises KeyError inside verify_goldens -> caught by
    # the broadened discrimination except -> passed False, no uncaught crash.
    _write_synthetic_skill(tmp_path)
    rec_path = tmp_path / "evals" / "golden" / "recorded_scores.json"
    recorded = json.loads(rec_path.read_text(encoding="utf-8"))
    del recorded["scores"]["good.md"]  # on disk but missing from scores map
    rec_path.write_text(json.dumps(recorded), encoding="utf-8")
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert res["checks"]["discrimination"]["passed"] is False
    assert "error" in res["checks"]["discrimination"]


def test_calibrate_ci_empty_verdicts_fail_closed(tmp_path: Path) -> None:
    # verdicts.jsonl with only blank lines -> load_gold returns [] -> the
    # agreement check calls compute_agreement([], []) which raises ValueError
    # -> caught by the agreement except -> passed False, no crash.
    _write_synthetic_skill(tmp_path)
    gold_path = tmp_path / "evals" / "golden" / "verdicts.jsonl"
    gold_path.write_text("\n   \n\n", encoding="utf-8")
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    assert res["checks"]["agreement"]["passed"] is False
    assert "error" in res["checks"]["agreement"]


def test_check_freshness_future_dated_fails() -> None:
    # FIX #2 GUARD: a future generated_at yields negative age_days; treat it as
    # NOT fresh. Both the unit (check_freshness) and the integrated path
    # (calibrate(ci) with a future-dated seed -> freshness fails).
    now = date(2026, 6, 22)
    future = date(2026, 7, 22).isoformat()  # ~30 days in the future
    assert check_freshness(future, now=now) is False


def test_calibrate_ci_future_dated_seed_fails_freshness(tmp_path: Path) -> None:
    _write_synthetic_skill(tmp_path, generated_at="2026-07-22T00:00:00Z")
    res = calibrate(tmp_path, mode="ci", now=date(2026, 6, 22))
    assert res["passed"] is False
    assert res["checks"]["freshness"]["passed"] is False


def test_calibrate_ci_bad_equals_good_tie_fails(tmp_path: Path) -> None:
    # Exact tie bad_score == good_score: verify_goldens uses strict `<`, so a
    # tie is NOT discriminated -> discrimination fails (the strict-< teeth).
    _write_synthetic_skill(
        tmp_path,
        good_score=0.5,
        bad_scores={"bad_1.md": 0.5, "bad_2.md": 0.2},  # bad_1 ties good
    )
    res = calibrate(tmp_path, mode="ci")
    assert res["passed"] is False
    disc = res["checks"]["discrimination"]
    assert disc["passed"] is False
    assert "bad_1.md" in disc["sycophantic_bads"]


# ---------------------------------------------------------------------------
# verify_discrimination is pure (no LLM / network / subprocess)
# ---------------------------------------------------------------------------


def test_verify_discrimination_pure_no_llm(tmp_path: Path, monkeypatch) -> None:
    """verify_discrimination's verdict is a pure function of recorded scores.

    Construction proof: the discrimination outcome is fully determined by the
    injected recorded scores and the fixture files on disk. We assert this two
    ways:

    1. Hard-fail any attempt to open a network socket or spawn a subprocess
       during the call (if the path secretly invoked an LLM, it would need
       one of these and the test would error).
    2. Mutating ONLY the recorded-scores dict (no file/LLM change) flips the
       verdict deterministically -- proving the function reads nothing but its
       inputs.
    """
    import socket
    import subprocess

    def _no_network(*_a, **_k):
        raise AssertionError("verify_discrimination opened a socket -- not pure")

    def _no_subprocess(*_a, **_k):
        raise AssertionError("verify_discrimination spawned a subprocess -- not pure")

    # The RIGOROUS proof of purity is part 2 below: mutating ONLY the injected
    # `scores` dict (no file/LLM/disk change) deterministically flips the
    # verdict, which is only possible if the function reads nothing but its
    # inputs. These socket/subprocess monkeypatches are cheap belt-and-
    # suspenders: they add no value against the current pure implementation but
    # would catch a FUTURE verify_goldens that regressed into a network or
    # subprocess (e.g. live-LLM) call.
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(subprocess, "Popen", _no_subprocess)

    _write_synthetic_skill(tmp_path)

    # Discriminating recorded scores -> status "ok".
    good_scores = {
        "scores": {"good.md": 0.9, "bad_1.md": 0.3, "bad_2.md": 0.2},
    }
    status_ok = verify_discrimination(tmp_path, good_scores)
    assert status_ok.status == "ok"
    assert status_ok.sycophantic_bads == []

    # Same files on disk; ONLY the injected scores change -> verdict flips.
    syco_scores = {
        "scores": {"good.md": 0.5, "bad_1.md": 0.6, "bad_2.md": 0.2},
    }
    status_bad = verify_discrimination(tmp_path, syco_scores)
    assert status_bad.status == "harness-error"
    assert "bad_1.md" in status_bad.sycophantic_bads
