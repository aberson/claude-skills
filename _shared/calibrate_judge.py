#!/usr/bin/env python3
"""Pure-Python, zero-live-LLM judge-calibration harness.

Gives the judging doctrine per-commit teeth: a deterministic CI gate that
verifies a recorded judge snapshot still (1) is fresh, (2) discriminates the
golden good fixture from the golden bad fixtures, and (3) agrees with the
hand-authored gold labels. NO LLM is invoked anywhere in this module: every
check runs against *recorded* artifacts that a prior judge run snapshotted.
The single live-judge piece (the stochastic position-swap / kappa sweep) is a
Phase-3 concern and is stubbed via ``mode="full"`` raising
``NotImplementedError``.

This module's docstring is the SINGLE SOURCE OF TRUTH for the calibration
data model (per dev/.claude/rules/code-quality.md "one source of truth for
data-shape constants"). The two on-disk artifacts below are the contract.

Gold artifacts (per skill, under ``<skill_dir>/evals/golden/``)
--------------------------------------------------------------
``verdicts.jsonl`` -- GOLD labels, one JSON object per non-blank line::

    {"fixture": "<name>.md", "verdict": "<enum>",
     "expected_block_anti_pattern": "<optional>"}

The ``verdict`` enum mirrors review-deep's lens verdict set:
``PASS | NEEDS-WORK | NO-EVIDENCE | FAILED | SKIPPED | NEEDS-CLARIFICATION``
(see review-deep/scripts/aggregate.py ``LensVerdict.overall_verdict``).
``expected_block_anti_pattern`` is OPTIONAL provenance carried for Phase-3 use
and is not consumed by the Phase-2 CI gate.

``recorded_scores.json`` -- the recorded judge snapshot::

    {
      "generated_at": "<ISO-8601 UTC>",        # freshness anchor
      "scorer": "<skill name>",
      "scores": { "<fixture>": <float> },        # recorded numeric score per
                                                 # fixture -> drives DISCRIMINATION
      "recorded_verdicts": { "<fixture>": "<verdict-enum>" }
                                                 # the categorical verdict the judge
                                                 # produced when snapshotted -> drives
                                                 # AGREEMENT/kappa vs gold
    }

The ``scores`` map is consumed by :func:`verify_discrimination`, which injects
``score_single_fn = lambda p: recorded_scores["scores"][p.name]`` into the
EXISTING :func:`score_skill_composite.verify_goldens`. That makes the
discrimination check pure (no LLM) -- it replays recorded numbers through the
same strict ``bad_score < good_score`` rule the live grader uses. The
``recorded_verdicts`` map is consumed by the AGREEMENT check, aligned to gold
by fixture name.

CI gate (mode="ci") -- all deterministic
----------------------------------------
1. FRESHNESS    -- ``recorded_scores["generated_at"]`` age <= FRESHNESS_MAX_AGE_DAYS.
2. DISCRIMINATION -- ``verify_goldens`` over recorded scores returns status
                   ``"ok"`` with empty ``sycophantic_bads`` (good outscores
                   every bad strictly).
3. AGREEMENT    -- recorded_verdicts aligned to gold; perfect agreement
                   (agreement_pct == 1.0, hence cohen_kappa == 1.0) is required
                   on the curated seed. The seed is hand-authored to be
                   perfectly consistent, so a strict 1.0 floor is correct -- a
                   mislabeled ``verdicts.jsonl`` (gold flipped) drops agreement
                   below 1.0 and fails the gate.

Any failing check -> ``passed: False`` with a reason. Missing or malformed
artifacts fail closed (caught, returned as ``passed: False``, never an
uncaught crash).

mode="full" -- PHASE-3 STUB
---------------------------
The live stochastic kappa sweep (re-running the judge N times over
position-swapped pairs to measure inter-run agreement + self-consistency)
needs live LLM judge runs and is therefore out of Phase-2 scope. It raises
``NotImplementedError`` so a caller that asks for it fails loudly rather than
silently getting a degenerate result.

:func:`compute_position_consistency` is implemented + unit-tested here with
INLINE fixtures only; it is NOT wired into ``mode="ci"`` because live
position-swap data needs live judge runs (Phase 3). It ships now as the
harness API Phase 3 will call.

Pure stdlib only: json, math, datetime, pathlib. No scipy, no numpy, no LLM.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Sibling import: score_skill_composite.py lives in the SAME directory as this
# module. Insert this dir on sys.path so ``from score_skill_composite import
# verify_goldens`` resolves regardless of cwd (mirrors how the sibling test
# files set up their imports). score_skill_composite performs its own sys.path
# tweak to reach skill-iterate/scripts, so importing it pulls in only stdlib
# transitive deps (no scipy/numpy/LLM).
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from score_skill_composite import (  # noqa: E402  (sys.path tweak above)
    GoldensStatus,
    verify_goldens,
)

# Recorded judge snapshots older than this are considered stale: the gate fails
# so the operator re-snapshots against the current judge doctrine.
FRESHNESS_MAX_AGE_DAYS = 180

# Sentinel for a recorded verdict that is ABSENT during agreement alignment. A
# fresh ``object()`` is identity-unique and never ``==`` any string, so a missing
# recorded verdict can NEVER spuriously equal a gold label -> guaranteed mismatch
# -> agreement < 1.0 -> fail-closed. (A string sentinel like "<MISSING>" could in
# principle collide with a gold label; an object instance cannot.)
_MISSING = object()

# Mirror of review-deep's lens-verdict enum (aggregate.py LensVerdict). Kept for
# documentation / potential validation use; the Phase-2 gate compares verdict
# strings by exact equality and does not enforce membership (the seed is
# hand-authored), so this set is informational.
VALID_VERDICTS = frozenset(
    {
        "PASS",
        "NEEDS-WORK",
        "NO-EVIDENCE",
        "FAILED",
        "SKIPPED",
        "NEEDS-CLARIFICATION",
    }
)


# ---------------------------------------------------------------------------
# Agreement / kappa
# ---------------------------------------------------------------------------


def compute_agreement(judged: list[str], gold: list[str]) -> dict[str, float]:
    """Observed agreement + Cohen's kappa between two equal-length label lists.

    ``judged`` and ``gold`` are parallel label lists (the i-th judged label is
    paired with the i-th gold label). Returns
    ``{"agreement_pct": float, "cohen_kappa": float}`` where:

    - ``agreement_pct`` = fraction of positions where the labels are exactly
      equal (the observed agreement, ``p_o``).
    - ``cohen_kappa`` = ``(p_o - p_e) / (1 - p_e)`` where ``p_e`` is the
      chance-agreement probability: ``sum over each category c of
      freq_judged(c) * freq_gold(c)`` (each frequency is that category's count
      in its own list divided by N).

    Edge cases:
    - ``len == 0`` -> raises ``ValueError`` (no labels to compare).
    - ``(1 - p_e) == 0`` (the "perfect chance" degenerate -- a single category
      present on BOTH sides, so chance agreement is already 1.0): kappa is
      undefined by the formula (0/0). By convention this function returns
      ``1.0`` when ``p_o == 1.0`` (the judge and gold agree perfectly, which is
      the only outcome possible when both lists are a single constant category)
      and ``0.0`` otherwise. In practice ``p_o`` is always ``1.0`` in that
      degenerate case, but the ``else 0.0`` branch keeps the contract total.
    """
    n = len(judged)
    if n != len(gold):
        raise ValueError(
            f"judged and gold must be equal-length; got {n} and {len(gold)}"
        )
    if n == 0:
        raise ValueError("cannot compute agreement on empty label lists")

    agree = sum(1 for j, g in zip(judged, gold) if j == g)
    p_o = agree / n

    # Chance agreement p_e = sum_c freq_judged(c) * freq_gold(c).
    categories = set(judged) | set(gold)
    p_e = 0.0
    for c in categories:
        freq_j = judged.count(c) / n
        freq_g = gold.count(c) / n
        p_e += freq_j * freq_g

    denom = 1.0 - p_e
    if denom == 0.0:
        # Perfect-chance degenerate (single category on both sides). Document
        # convention: kappa is 1.0 iff observed agreement is also perfect.
        cohen_kappa = 1.0 if p_o == 1.0 else 0.0
    else:
        cohen_kappa = (p_o - p_e) / denom

    return {"agreement_pct": p_o, "cohen_kappa": cohen_kappa}


def compute_position_consistency(pairs: list[tuple[str, str]]) -> float:
    """Fraction of order-swapped judging pairs whose verdict is order-invariant.

    Each pair is ``(verdict_AB, verdict_BA)``: the verdict the judge produced
    with the two items in order A-then-B, and the verdict with the order
    swapped to B-then-A. A position-consistent judge returns the same verdict
    regardless of order, so this returns
    ``count(verdict_AB == verdict_BA) / len(pairs)``.

    EMPTY list -> returns ``1.0`` (vacuously consistent: no inconsistency can
    be observed). Documented convention.

    PHASE-2 SCOPE: this is implemented + unit-tested with INLINE fixtures only.
    It is NOT wired into ``calibrate(mode="ci")`` -- gathering real
    position-swap data requires live judge runs (Phase 3). It ships now as the
    harness API Phase 3 will call.
    """
    if not pairs:
        return 1.0
    consistent = sum(1 for ab, ba in pairs if ab == ba)
    return consistent / len(pairs)


# ---------------------------------------------------------------------------
# Gold + recorded-snapshot loading
# ---------------------------------------------------------------------------


def load_gold(skill_dir: str | Path) -> list[dict[str, Any]]:
    """Load the gold labels from ``<skill_dir>/evals/golden/verdicts.jsonl``.

    Parses each non-blank line as a JSON object and returns the list, in file
    order. Fail-closed: a missing file raises ``FileNotFoundError`` (the CI
    gate catches it and reports ``passed: False``); a malformed line raises
    ``json.JSONDecodeError`` (likewise caught by the gate).
    """
    gold_path = Path(skill_dir) / "evals" / "golden" / "verdicts.jsonl"
    if not gold_path.is_file():
        raise FileNotFoundError(f"gold labels not found at {gold_path}")
    out: list[dict[str, Any]] = []
    for line in gold_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def _load_recorded_scores(skill_dir: str | Path) -> dict[str, Any]:
    """Load ``<skill_dir>/evals/golden/recorded_scores.json``.

    Fail-closed: missing file raises ``FileNotFoundError``; malformed JSON
    raises ``json.JSONDecodeError``. Both are caught by :func:`calibrate`.
    """
    rec_path = Path(skill_dir) / "evals" / "golden" / "recorded_scores.json"
    if not rec_path.is_file():
        raise FileNotFoundError(f"recorded scores not found at {rec_path}")
    return json.loads(rec_path.read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------------------
# Discrimination (thin wrapper over verify_goldens -- NO LLM)
# ---------------------------------------------------------------------------


def verify_discrimination(
    skill_dir: str | Path, recorded_scores: dict[str, Any]
) -> GoldensStatus:
    """Replay recorded scores through ``verify_goldens`` -- pure, no LLM.

    Thin wrapper: injects ``score_single_fn = lambda p: recorded_scores
    ["scores"][p.name]`` into the EXISTING
    :func:`score_skill_composite.verify_goldens`. ``verify_goldens`` walks
    ``<skill_dir>/evals/golden/`` for ``good.md`` + ``bad_*.md``, looks each
    recorded score up by filename, and applies its strict
    ``bad_score < good_score`` discrimination rule (a tie fails). No LLM,
    network, or subprocess is touched: the verdict is a pure function of the
    recorded numbers and which fixture files exist on disk.

    A fixture whose recorded bad score is >= the recorded good score makes
    ``verify_goldens`` report ``status="harness-error"`` with that fixture in
    ``sycophantic_bads`` -> the CI gate FAILS (discrimination teeth).

    Returns the :class:`GoldensStatus` ``verify_goldens`` produces, unchanged.
    """
    return verify_goldens(
        Path(skill_dir),
        score_single_fn=lambda p: recorded_scores["scores"][p.name],
    )


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


def check_freshness(
    generated_at: str,
    max_age_days: int = FRESHNESS_MAX_AGE_DAYS,
    now: date | None = None,
) -> bool:
    """True iff a recorded-snapshot timestamp is within ``max_age_days``.

    ``generated_at`` is parsed as ISO-8601 (date or datetime; a trailing 'Z'
    UTC designator is tolerated). ``now`` defaults to ``datetime.date.today()``
    and is INJECTABLE so tests are deterministic. Returns ``True`` when the age
    in days is ``<= max_age_days``, ``False`` otherwise.

    FAIL-CLOSED on FUTURE timestamps: a ``generated_at`` AFTER ``now`` yields a
    negative ``age_days``; such a snapshot is treated as NOT fresh (returns
    ``False``). A future stamp is a clock-skew / tamper / bad-write signal, and
    accepting it would defeat the anti-coast freshness guard (a far-future stamp
    would never expire). It is not a valid fresh snapshot.
    """
    if now is None:
        now = date.today()
    parsed = _parse_iso_date(generated_at)
    age_days = (now - parsed).days
    if age_days < 0:
        # Future-dated snapshot (clock skew / tamper) -> not a valid fresh one.
        return False
    return age_days <= max_age_days


def _parse_iso_date(value: str) -> date:
    """Parse an ISO-8601 date or datetime string to a ``date``.

    Tolerates a trailing 'Z' (UTC designator that ``datetime.fromisoformat``
    rejects before Py3.11) by swapping it for ``+00:00``. Accepts a bare
    ``YYYY-MM-DD`` date too. Raises ``ValueError`` on anything unparseable
    (caught by :func:`calibrate`).
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        # Bare date (no time component).
        return date.fromisoformat(text)


# ---------------------------------------------------------------------------
# CI gate
# ---------------------------------------------------------------------------


def calibrate(
    skill_dir: str | Path, mode: str = "ci", now: date | None = None
) -> dict[str, Any]:
    """Run the calibration gate for a skill and return a structured result.

    Phase-2 implements ``mode == "ci"`` only. ``mode == "full"`` raises
    ``NotImplementedError`` (the Phase-3 live stochastic kappa sweep -- it
    needs live LLM judge runs, which are out of Phase-2 scope).

    The CI gate is fully deterministic and runs three checks (see the module
    docstring for the contract): FRESHNESS, DISCRIMINATION, AGREEMENT. It
    returns::

        {
          "passed": bool,
          "skill": <skill_dir name>,
          "mode": "ci",
          "checks": {"freshness": {...}, "discrimination": {...},
                     "agreement": {...}},
          "reasons": [<reason strings for each failing check>],
        }

    Missing or malformed artifacts fail closed: the gate catches the error,
    sets ``passed: False``, and records the reason -- it never raises an
    uncaught exception out of the ``ci`` path. ``now`` is injectable for
    deterministic freshness tests.
    """
    skill_path = Path(skill_dir)

    if mode == "full":
        raise NotImplementedError(
            "calibrate(mode='full') is a Phase-3 stub: the live stochastic "
            "kappa / position-swap sweep needs live LLM judge runs, which are "
            "out of Phase-2 scope. Use mode='ci' for the deterministic gate."
        )
    if mode != "ci":
        raise ValueError(f"unknown mode {mode!r}; expected 'ci' or 'full'")

    checks: dict[str, Any] = {}
    reasons: list[str] = []
    passed = True

    # --- Load artifacts (fail-closed) ------------------------------------
    try:
        recorded = _load_recorded_scores(skill_path)
        gold = load_gold(skill_path)
        # Structural validation of the recorded snapshot. Both maps MUST be
        # objects (dicts). If ``scores`` were None/a list/a non-dict, the
        # discrimination lambda ``recorded["scores"][p.name]`` would raise
        # AttributeError/TypeError INSIDE verify_goldens and escape as an
        # uncaught crash; if ``recorded_verdicts`` were a non-dict, the
        # agreement check's ``.get(...)`` would do the same. Validate here,
        # inside the same fail-closed try, so a malformed snapshot returns
        # passed:False rather than crashing (the "never an uncaught crash;
        # always fail-closed" contract).
        if not isinstance(recorded.get("scores"), dict) or not isinstance(
            recorded.get("recorded_verdicts"), dict
        ):
            raise ValueError(
                "malformed recorded_scores: 'scores'/'recorded_verdicts' must "
                "be objects"
            )
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        return {
            "passed": False,
            "skill": skill_path.name,
            "mode": "ci",
            "checks": {},
            "reasons": [f"artifact load failed: {exc}"],
        }

    # --- Check 1: FRESHNESS ----------------------------------------------
    try:
        generated_at = recorded["generated_at"]
        fresh = check_freshness(generated_at, now=now)
        checks["freshness"] = {
            "passed": fresh,
            "generated_at": generated_at,
            "max_age_days": FRESHNESS_MAX_AGE_DAYS,
        }
        if not fresh:
            passed = False
            reasons.append(
                f"freshness: snapshot generated_at={generated_at!r} is older "
                f"than {FRESHNESS_MAX_AGE_DAYS} days"
            )
    except (KeyError, ValueError) as exc:
        passed = False
        checks["freshness"] = {"passed": False, "error": str(exc)}
        reasons.append(f"freshness check errored: {exc}")

    # --- Check 2: DISCRIMINATION -----------------------------------------
    try:
        status = verify_discrimination(skill_path, recorded)
        discriminated = (
            status.status == "ok" and not status.sycophantic_bads
        )
        checks["discrimination"] = {
            "passed": discriminated,
            "status": status.status,
            "good_score": status.good_score,
            "sycophantic_bads": status.sycophantic_bads,
            "reason": status.reason,
        }
        if not discriminated:
            passed = False
            reasons.append(
                f"discrimination: verify_goldens status={status.status!r}, "
                f"sycophantic_bads={status.sycophantic_bads} -- {status.reason}"
            )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        # KeyError: a fixture on disk is absent from the recorded scores map.
        # TypeError/AttributeError: defense-in-depth -- any future structural
        # surprise in ``recorded["scores"]`` still fails closed, never crashes.
        passed = False
        checks["discrimination"] = {"passed": False, "error": str(exc)}
        reasons.append(f"discrimination check errored: {exc}")

    # --- Check 3: AGREEMENT ----------------------------------------------
    try:
        recorded_verdicts = recorded["recorded_verdicts"]
        # Align recorded verdicts to gold by fixture name, in gold order.
        judged_labels: list[str] = []
        gold_labels: list[str] = []
        for entry in gold:
            fixture = entry["fixture"]
            gold_labels.append(entry["verdict"])
            # Missing recorded verdict -> identity-unique sentinel that can
            # never ``==`` any gold string, forcing disagreement (fail-closed).
            # ``_MISSING`` is an ``object()``; compute_agreement compares with
            # ``==``, so a missing verdict is a guaranteed mismatch.
            judged_labels.append(recorded_verdicts.get(fixture, _MISSING))
        agreement = compute_agreement(judged_labels, gold_labels)
        agrees = agreement["agreement_pct"] == 1.0
        checks["agreement"] = {
            "passed": agrees,
            "agreement_pct": agreement["agreement_pct"],
            "cohen_kappa": agreement["cohen_kappa"],
            "threshold": 1.0,
        }
        if not agrees:
            passed = False
            reasons.append(
                f"agreement: recorded verdicts agree with gold at "
                f"{agreement['agreement_pct']:.4f} (kappa="
                f"{agreement['cohen_kappa']:.4f}); the curated seed requires "
                f"perfect 1.0 agreement"
            )
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        # KeyError: a gold entry is missing 'fixture'/'verdict'. ValueError:
        # compute_agreement on empty/mismatched lists. TypeError/AttributeError:
        # defense-in-depth so any future structural surprise fails closed.
        passed = False
        checks["agreement"] = {"passed": False, "error": str(exc)}
        reasons.append(f"agreement check errored: {exc}")

    return {
        "passed": passed,
        "skill": skill_path.name,
        "mode": "ci",
        "checks": checks,
        "reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Synthetic fixture builder (shared by --unit-test and --self-test)
# ---------------------------------------------------------------------------


def _write_synthetic_skill(
    root: Path,
    *,
    good_verdict: str = "PASS",
    bad_verdict: str = "NEEDS-WORK",
    good_score: float = 0.9,
    bad_scores: dict[str, float] | None = None,
    generated_at: str = "2026-06-01T00:00:00Z",
    recorded_verdicts: dict[str, str] | None = None,
) -> Path:
    """Build a synthetic skill dir with golden artifacts under ``root``.

    Writes ``evals/golden/{good.md, bad_1.md, bad_2.md, recorded_scores.json,
    verdicts.jsonl}``. Returns the skill dir path (== ``root``). Defaults
    describe a HEALTHY seed (good outscores bads, fresh timestamp, recorded
    verdicts matching gold). Callers override individual fields to construct
    the failure cases.
    """
    if bad_scores is None:
        bad_scores = {"bad_1.md": 0.3, "bad_2.md": 0.2}
    golden = root / "evals" / "golden"
    golden.mkdir(parents=True, exist_ok=True)

    (golden / "good.md").write_text("# good fixture\n", encoding="utf-8")
    for bad_name in bad_scores:
        (golden / bad_name).write_text(f"# {bad_name}\n", encoding="utf-8")

    scores = {"good.md": good_score}
    scores.update(bad_scores)

    if recorded_verdicts is None:
        recorded_verdicts = {"good.md": good_verdict}
        for bad_name in bad_scores:
            recorded_verdicts[bad_name] = bad_verdict

    recorded = {
        "generated_at": generated_at,
        "scorer": "synthetic-skill",
        "scores": scores,
        "recorded_verdicts": recorded_verdicts,
    }
    (golden / "recorded_scores.json").write_text(
        json.dumps(recorded, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    gold_lines = [
        json.dumps({"fixture": "good.md", "verdict": good_verdict}),
    ]
    for bad_name in bad_scores:
        gold_lines.append(
            json.dumps({"fixture": bad_name, "verdict": bad_verdict})
        )
    (golden / "verdicts.jsonl").write_text(
        "\n".join(gold_lines) + "\n", encoding="utf-8"
    )
    return root


def _kappa_fixture_lists() -> tuple[list[str], list[str]]:
    """Build the hand-computed 50-pair kappa validation lists.

    Cell counts (judged x gold): both-YES=20, both-NO=15,
    judged-YES/gold-NO=5, judged-NO/gold-YES=10. Total = 50.
    -> p_o = (20+15)/50 = 0.70
    -> judged YES = 25 (0.5), NO = 25 (0.5); gold YES = 30 (0.6), NO = 20 (0.4)
    -> p_e = 0.5*0.6 + 0.5*0.4 = 0.50
    -> kappa = (0.70 - 0.50) / (1 - 0.50) = 0.40
    """
    judged: list[str] = []
    gold: list[str] = []
    judged += ["YES"] * 20
    gold += ["YES"] * 20  # both-YES
    judged += ["NO"] * 15
    gold += ["NO"] * 15  # both-NO
    judged += ["YES"] * 5
    gold += ["NO"] * 5  # judged-YES / gold-NO
    judged += ["NO"] * 10
    gold += ["YES"] * 10  # judged-NO / gold-YES
    return judged, gold


# ---------------------------------------------------------------------------
# --unit-test (in-process asserts, synthetic skill in a tempdir)
# ---------------------------------------------------------------------------


def run_unit_tests() -> int:
    """In-process unit tests. Prints ``UNIT TESTS PASSED`` + returns 0 on success.

    Coverage (per issue #230 Done-when):
    (a) kappa fixture == 0.40 (hand-computed 2x2);
    (b) position_consistency basic + empty -> 1.0;
    (c) calibrate(ci) on a healthy synthetic seed -> passed True;
    (d) MISLABELED gold (good's gold verdict flipped) -> passed False;
    (e) STALE generated_at -> passed False;
    (f) bad-score >= good-score -> passed False (discrimination teeth);
    (g) calibrate(mode="full") raises NotImplementedError.
    """
    try:
        # (a) Cohen's kappa hand-computed fixture == 0.40.
        judged, gold = _kappa_fixture_lists()
        agreement = compute_agreement(judged, gold)
        assert abs(agreement["cohen_kappa"] - 0.40) < 1e-9, (
            f"kappa fixture: expected 0.40, got {agreement['cohen_kappa']!r}"
        )
        assert abs(agreement["agreement_pct"] - 0.70) < 1e-9, (
            f"kappa fixture: expected p_o 0.70, got {agreement['agreement_pct']!r}"
        )

        # (b) position_consistency basic + empty -> 1.0.
        assert compute_position_consistency([("PASS", "PASS"), ("PASS", "PASS")]) == 1.0, (
            "position_consistency: all-equal pairs must score 1.0"
        )
        assert compute_position_consistency([("PASS", "PASS"), ("PASS", "FAIL")]) == 0.5, (
            "position_consistency: one-of-two-equal must score 0.5"
        )
        assert compute_position_consistency([]) == 1.0, (
            "position_consistency: empty list must be vacuously 1.0"
        )

        # (g) full mode is a Phase-3 stub.
        try:
            calibrate(Path(tempfile.gettempdir()), mode="full")
            raise AssertionError("calibrate(mode='full') must raise NotImplementedError")
        except NotImplementedError:
            pass

        # (c)-(f) calibrate(ci) over synthetic seeds.
        with tempfile.TemporaryDirectory() as td:
            # (c) healthy seed -> passed True.
            good_dir = Path(td) / "good_seed"
            _write_synthetic_skill(good_dir)
            res_good = calibrate(good_dir, mode="ci")
            assert res_good["passed"] is True, (
                f"healthy seed must pass, got {res_good!r}"
            )

            # (d) mislabeled gold: flip good.md's gold verdict so recorded
            # verdict ('PASS') no longer matches gold -> agreement < 1.0.
            mis_dir = Path(td) / "mislabeled"
            _write_synthetic_skill(mis_dir)
            mis_gold = mis_dir / "evals" / "golden" / "verdicts.jsonl"
            lines = mis_gold.read_text(encoding="utf-8").splitlines()
            flipped = []
            for line in lines:
                obj = json.loads(line)
                if obj["fixture"] == "good.md":
                    obj["verdict"] = "NEEDS-WORK"  # flip away from recorded PASS
                flipped.append(json.dumps(obj))
            mis_gold.write_text("\n".join(flipped) + "\n", encoding="utf-8")
            res_mis = calibrate(mis_dir, mode="ci")
            assert res_mis["passed"] is False, (
                f"mislabeled gold must fail, got {res_mis!r}"
            )
            assert res_mis["checks"]["agreement"]["passed"] is False, (
                f"mislabeled gold must fail the AGREEMENT check, got "
                f"{res_mis['checks']!r}"
            )

            # (e) stale generated_at -> freshness fails.
            stale_dir = Path(td) / "stale"
            _write_synthetic_skill(
                stale_dir, generated_at="2023-01-01T00:00:00Z"
            )
            # Inject a fixed 'now' two+ years after the stale timestamp so the
            # test is deterministic regardless of wall-clock.
            res_stale = calibrate(
                stale_dir, mode="ci", now=date(2026, 6, 22)
            )
            assert res_stale["passed"] is False, (
                f"stale snapshot must fail, got {res_stale!r}"
            )
            assert res_stale["checks"]["freshness"]["passed"] is False, (
                f"stale snapshot must fail the FRESHNESS check, got "
                f"{res_stale['checks']!r}"
            )

            # (f) bad-score >= good-score -> discrimination fails.
            syco_dir = Path(td) / "sycophantic"
            _write_synthetic_skill(
                syco_dir,
                good_score=0.5,
                bad_scores={"bad_1.md": 0.6, "bad_2.md": 0.2},
            )
            res_syco = calibrate(syco_dir, mode="ci")
            assert res_syco["passed"] is False, (
                f"bad>=good must fail discrimination, got {res_syco!r}"
            )
            assert res_syco["checks"]["discrimination"]["passed"] is False, (
                f"bad>=good must fail the DISCRIMINATION check, got "
                f"{res_syco['checks']!r}"
            )
            assert "bad_1.md" in res_syco["checks"]["discrimination"][
                "sycophantic_bads"
            ], (
                f"bad_1.md must be flagged sycophantic, got "
                f"{res_syco['checks']['discrimination']!r}"
            )

    except AssertionError as e:
        sys.stdout.write(f"UNIT TEST FAILED: {e}\n")
        return 1
    except Exception as e:  # noqa: BLE001 - any other crash is a test failure
        sys.stdout.write(f"UNIT TEST FAILED: unexpected exception: {e!r}\n")
        return 1
    sys.stdout.write("UNIT TESTS PASSED\n")
    return 0


# ---------------------------------------------------------------------------
# --self-test (calibration-report round-trip)
# ---------------------------------------------------------------------------


def run_self_test(path: Path) -> int:
    """Round-trip a calibration report through json and assert key stability.

    If ``path`` points at an existing skill dir (one with
    ``evals/golden/recorded_scores.json``), calibrate it; otherwise build a
    synthetic healthy seed under a tempdir and calibrate that. Serialize the
    report via ``json.dumps(..., ensure_ascii=False)``, parse it back, and
    assert the load-bearing fields survive intact. Prints ``SELF-TEST PASSED``
    + returns 0 on success; ``SELF-TEST FAILED ...`` + 1 on failure.
    """
    try:
        recorded = path / "evals" / "golden" / "recorded_scores.json"
        if recorded.is_file():
            report = calibrate(path, mode="ci")
        else:
            with tempfile.TemporaryDirectory() as td:
                skill_dir = Path(td) / "selftest_seed"
                _write_synthetic_skill(skill_dir)
                report = calibrate(skill_dir, mode="ci")

        serialized = json.dumps(report, indent=2, ensure_ascii=False)
        round_tripped = json.loads(serialized)

        for key in ("passed", "skill", "mode", "checks", "reasons"):
            assert key in round_tripped, f"round-trip dropped key {key!r}"
        assert round_tripped["passed"] == report["passed"], (
            "round-trip altered 'passed'"
        )
        assert round_tripped["mode"] == report["mode"] == "ci", (
            "round-trip altered 'mode'"
        )
        assert round_tripped["checks"] == report["checks"], (
            "round-trip altered 'checks'"
        )
    except AssertionError as e:
        sys.stdout.write(f"SELF-TEST FAILED: {e}\n")
        return 1
    except Exception as e:  # noqa: BLE001 - any other crash is a self-test failure
        sys.stdout.write(f"SELF-TEST FAILED: unexpected exception: {e!r}\n")
        return 1
    sys.stdout.write("SELF-TEST PASSED\n")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="calibrate_judge.py",
        description=(
            "Pure-Python, zero-live-LLM judge-calibration harness. Verifies a "
            "recorded judge snapshot stays fresh, discriminating, and in "
            "agreement with the hand-authored gold labels."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--unit-test",
        action="store_true",
        help="Run in-process unit tests (kappa, position-consistency, ci gate); exits after",
    )
    parser.add_argument(
        "--self-test",
        type=Path,
        default=None,
        help=(
            "Round-trip a calibration report for a skill dir (or a synthetic "
            "seed if the path has no recorded_scores.json); exits after"
        ),
    )
    parser.add_argument(
        "--skill",
        default=None,
        help=(
            "Skill name to calibrate; resolved to <skills>/<name> where "
            "<skills> is this file's parent dir's parent (.claude/skills/)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("ci", "full"),
        default="ci",
        help="Calibration mode (default: ci; 'full' is a Phase-3 stub)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Reconfigure stdout to UTF-8 with replacement on Windows so non-ASCII
    # content does not crash under cp1252 (mirrors aggregate.py).
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass  # Python < 3.7 lacks reconfigure

    args = _parse_args(argv)

    # Mode routing: unit-test first, self-test second, normal flow third.
    if args.unit_test:
        return run_unit_tests()

    if args.self_test is not None:
        return run_self_test(args.self_test)

    if args.skill is None:
        sys.stderr.write(
            "error: --skill <name> is required (or pass --unit-test / --self-test)\n"
        )
        return 2

    # Resolve --skill to <skills>/<name>. _THIS_DIR is .claude/skills/_shared;
    # its parent is the skills root.
    skills_root = _THIS_DIR.parent
    skill_dir = skills_root / args.skill

    report = calibrate(skill_dir, mode=args.mode)

    verdict = "PASS" if report["passed"] else "FAIL"
    sys.stdout.write(f"calibrate-judge: {verdict} ({report['skill']}, mode={report['mode']})\n")
    for name, detail in report["checks"].items():
        state = "ok" if detail.get("passed") else "FAIL"
        sys.stdout.write(f"  - {name}: {state}\n")
    for reason in report["reasons"]:
        sys.stdout.write(f"  ! {reason}\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
