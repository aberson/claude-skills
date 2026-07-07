"""Thin Python wrapper around the composite skill-scoring procedure.

Implements the procedure documented at ``./score-skill.md`` programmatically.
For composite mode, delegates to the structural-metrics script under
``../skill-iterate/scripts/`` AND to the absolute aggregator at
``./score_skill_absolute.py``; this module is the composition + I/O wiring
only. The differential grader (``../skill-iterate/scripts/differential_grader.py``)
is preserved for direct invocation via ``mode="differential"`` but is no
longer invoked by composite mode as of SIHC.2 Option A (2026-05-26).

CLI:
    python score_skill_composite.py
        --skill-md <path>
        --baseline <path>
        --modified <path>
        --scenarios <path-or-empty>
        [--mode {composite, structural, differential}]
        [--absolute-verdicts <path>]   # composite mode: canonical verdict JSON
        [--evals <path>]               # composite mode: evals.json for aggregator
        [--stub-verdict {better, worse, same}]  # differential-only

The ``--stub-verdict`` flag swaps in a deterministic dispatcher (same one the
differential grader CLI exposes) for smoke checks and tests; production
callers pass a real ``dispatch_comparison`` callable to ``score_composite``.
``--absolute-verdicts`` + ``--evals`` are the composite-mode inputs the
orchestrator-LLM passes after dispatching per-scenario grader sub-agents.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

# Ensure the skill-iterate scripts/ dir is importable when running this file
# directly via the CLI (the differential_grader + structural_metrics modules
# live there, not on the Python path by default).
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skill-iterate" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from differential_grader import (  # noqa: E402  (sys.path tweak above)
    ScenarioVerdict,
    _make_fixed_verdict_dispatcher,
    score_differential,
)
from structural_metrics import score_skill as run_structural  # noqa: E402

# Sibling import: the absolute aggregator lives next to this module.
from score_skill_absolute import (  # noqa: E402
    _load_evals,
    aggregate as aggregate_absolute,
)

# --- Composition weights -----------------------------------------------------
#
# Per SIHC.2 Option A (decision 2026-05-26): absolute_weighted carries more
# weight because it's the discriminating axis (differential graded all prose
# edits as "same" per the SIHC.1 evidence). Structural metrics are easily
# Goodharted and serve as a tie-breaker + cheap deterministic signal.
# The two constants MUST sum to 1.0.

STRUCTURAL_WEIGHT: float = 0.4
# Renamed from `DIFFERENTIAL_WEIGHT` per SIHC.2 Option A (value unchanged).
ABSOLUTE_WEIGHT: float = 0.6

assert abs((STRUCTURAL_WEIGHT + ABSOLUTE_WEIGHT) - 1.0) < 1e-9, (
    "STRUCTURAL_WEIGHT + ABSOLUTE_WEIGHT must sum to 1.0; "
    f"got {STRUCTURAL_WEIGHT} + {ABSOLUTE_WEIGHT} = "
    f"{STRUCTURAL_WEIGHT + ABSOLUTE_WEIGHT}"
)

VALID_MODES: frozenset[str] = frozenset({"composite", "structural", "differential"})

# Crash sub-class string emitted when a per-skill goldens-verification run
# discovers the grader cannot distinguish bad_*.md from good.md (a bad scored
# >= good's score). The /skill-iterate loop maps this to autonomy-contract
# clause 3 (defect-park) so the sycophantic grader does not silently produce
# 12 iterations of garbage data.
GRADER_SYCOPHANCY_CRASH_CLASS: str = "harness-error: grader sycophancy detected"


# --- Output dataclass --------------------------------------------------------


@dataclass(frozen=True)
class GoldensStatus:
    """Result of the per-skill goldens-verification pass.

    Attached to every :class:`CompositeScore` for observability. See
    ``./score-skill.md`` § Goldens verification for the full contract.

    Fields:
      - ``status``: ``"no-goldens-found"`` (per-skill ``evals/golden/`` dir
        absent — skipped gracefully), ``"ok"`` (every bad scored strictly
        lower than good — grader is discriminating for this skill), or
        ``"harness-error"`` (at least one bad scored >= good — grader is
        sycophantic for this skill; caller should halt the iteration loop
        per :data:`GRADER_SYCOPHANCY_CRASH_CLASS`).
      - ``good_score``: grader's score on ``good.md`` (None when status is
        ``"no-goldens-found"``).
      - ``bad_scores``: per-bad-file scoring detail (None when status is
        ``"no-goldens-found"``; empty list when goldens dir exists but
        contains no ``bad_*.md`` files — vacuously ``"ok"``).
      - ``sycophantic_bads``: filenames of bads that scored >= good_score.
        Empty when status is ``"ok"`` or ``"no-goldens-found"``.
      - ``reason``: human-readable summary suitable for log lines.
    """

    status: str  # "no-goldens-found" | "ok" | "harness-error"
    good_score: float | None
    bad_scores: list[dict[str, Any]] | None
    sycophantic_bads: list[str]
    reason: str


@dataclass(frozen=True)
class CompositeScore:
    """Single-trial scoring JSON per ``./score-skill.md`` § Output contract.

    Matches the contract documented in ``skill-iterate/SKILL.md`` § Scoring
    that ``append_result.py`` has always accepted unchanged.

    ``goldens_status`` and ``halt_requested`` are observability extensions
    added in SIHC Step 12; default values preserve backwards-compatibility
    for callers that don't pass them. See ``./score-skill.md`` § Goldens
    verification.
    """

    score: float | None
    passed: int
    total: int
    status: str  # "ok" | "unparseable" | "harness-error"
    goldens_status: GoldensStatus | None = None
    halt_requested: bool = False


# --- Procedure ---------------------------------------------------------------


def _load_scenarios(scenarios_path: Path | None) -> list[dict[str, Any]]:
    """Load test_scenarios.json or return [] if path is None or empty.

    Tolerates either a top-level list or ``{"scenarios": [...]}`` wrapper for
    forward-compat with composite schemas (mirrors ``differential_grader``'s
    own loader).
    """
    if scenarios_path is None:
        return []
    if not scenarios_path.is_file():
        # Empty / missing scenarios -> neutral differential (no signal).
        return []
    raw = scenarios_path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("scenarios"), list):
        return data["scenarios"]
    raise ValueError(
        f"unrecognized scenarios JSON shape in {scenarios_path}: "
        "expected a list or an object with a 'scenarios' list"
    )


def verify_goldens(
    skill_dir: Path,
    score_single_fn: Callable[[Path], float],
) -> GoldensStatus:
    """Load per-skill goldens and verify the grader discriminates good from bad.

    NOTE: as of SIHC.2 Option A (2026-05-26), this function is no longer
    auto-invoked by :func:`score_composite`. Preserved for direct invocation
    by callers that want the discrimination check; the absolute grader
    handles its own sycophancy check via the N=3 median + the
    convergeability audit (per ``_shared/score-skill.md`` § Absolute
    grading).

    Resolves ``<skill_dir>/evals/golden/``. If the directory is absent (the
    common case until M3/M4 of the SIHC plan lands real fleet goldens),
    returns ``status="no-goldens-found"`` immediately — gracefully skipped,
    not an error.

    Otherwise loads ``good.md`` and every ``bad_*.md`` in the directory and
    scores each via the injected ``score_single_fn`` (which the caller wires
    to the same single-trial scoring function the composite procedure uses).
    Files other than ``good.md`` and ``bad_*.md`` (notably ``manifest.json``
    and any ad-hoc operator notes) are ignored.

    Accept criterion: every bad must score STRICTLY lower than good. A tie
    (``bad_score == good_score``) is a fail — the grader did not discriminate.

    Returns:
        :class:`GoldensStatus` with full per-bad detail. The function never
        raises on harness-error; the caller decides whether to halt.

    Args:
        skill_dir: Path to the skill's root (e.g. ``.claude/skills/session-wrap/``).
            Goldens are looked up under ``<skill_dir>/evals/golden/``.
        score_single_fn: Callable taking one Path argument (the .md file to
            score) and returning a float score. Dependency-injected so tests
            can stub deterministic verdicts; production callers wire this to
            their single-trial scoring routine.
    """
    goldens_dir = skill_dir / "evals" / "golden"
    if not goldens_dir.is_dir():
        return GoldensStatus(
            status="no-goldens-found",
            good_score=None,
            bad_scores=None,
            sycophantic_bads=[],
            reason=f"no goldens dir at {goldens_dir}; skipping verification",
        )

    good_path = goldens_dir / "good.md"
    if not good_path.is_file():
        # Goldens dir exists but good.md is missing - same graceful-skip
        # semantics as a fully-absent dir. The corpus is incomplete; treat
        # as not-yet-ready rather than a hard error so partially-bootstrapped
        # skills do not block /skill-iterate.
        return GoldensStatus(
            status="no-goldens-found",
            good_score=None,
            bad_scores=None,
            sycophantic_bads=[],
            reason=f"goldens dir present but good.md missing at {good_path}",
        )

    # Sorted for deterministic ordering across platforms (Path.glob order is
    # not specified). Manifest.json + other files are excluded by the glob.
    bad_paths = sorted(goldens_dir.glob("bad_*.md"))

    good_score = float(score_single_fn(good_path))
    bad_scores: list[dict[str, Any]] = []
    sycophantic_bads: list[str] = []
    for bad_path in bad_paths:
        bad_score = float(score_single_fn(bad_path))
        discriminated = bad_score < good_score
        bad_scores.append(
            {
                "file": bad_path.name,
                "score": bad_score,
                "discriminated": discriminated,
            }
        )
        if not discriminated:
            sycophantic_bads.append(bad_path.name)

    n_bads = len(bad_paths)
    if not sycophantic_bads:
        if n_bads == 0:
            reason = (
                f"goldens dir present, good.md scored {good_score:.6f}, "
                "no bad_*.md files found (vacuously ok)"
            )
        else:
            reason = (
                f"all {n_bads} bads discriminated below good (good={good_score:.6f})"
            )
        return GoldensStatus(
            status="ok",
            good_score=good_score,
            bad_scores=bad_scores,
            sycophantic_bads=[],
            reason=reason,
        )

    reason = (
        f"{len(sycophantic_bads)} of {n_bads} bads scored >= good "
        f"({good_score:.6f}); grader is sycophantic for this skill: "
        f"{', '.join(sycophantic_bads)}"
    )
    return GoldensStatus(
        status="harness-error",
        good_score=good_score,
        bad_scores=bad_scores,
        sycophantic_bads=sycophantic_bads,
        reason=reason,
    )


def _default_single_trial_score(path: Path) -> float:
    """Default single-trial scorer for :func:`verify_goldens`.

    Wraps the structural-metrics axis (cheap, deterministic, no LLM
    dispatch). Used when the caller does not inject a ``score_single_fn``.
    Returns the raw structural score in ``[0.0, 1.0]``.

    Production callers (the /skill-iterate orchestrator) should pass their
    own single-trial scorer that mirrors the composite procedure's full
    grading shape; the structural-only default is a deterministic placeholder
    that still lets the discrimination check run end-to-end.
    """
    return float(run_structural(path).score)


def score_composite(
    skill_md_path: Path,
    baseline_skill_md: Path,
    modified_skill_md: Path,
    scenarios_path: Path | None,
    *,
    mode: str = "composite",
    dispatch_comparison: (
        Callable[[str, str, dict[str, Any]], ScenarioVerdict] | None
    ) = None,
    absolute_verdicts: dict[str, Any] | None = None,
    evals_path: Path | None = None,
    skill_dir: Path | None = None,
    score_single_fn: Callable[[Path], float] | None = None,
    skip_goldens: bool = False,
) -> CompositeScore:
    """Run the composite scoring procedure and return a single-trial result.

    See ``./score-skill.md`` for the full specification. This function is the
    canonical Python implementation; the orchestrator-LLM may either invoke
    this directly or reproduce the procedure inline per the spec doc.

    As of SIHC.2 Option A (2026-05-26):
      - Composite mode composes ``structural`` with the ABSOLUTE grader
        axis (``score_skill_absolute.aggregate``). The orchestrator-LLM
        builds the canonical verdict JSON payload by dispatching per-scenario
        grader sub-agents (see ``./score-skill.md`` § Absolute grading) and
        passes it via ``absolute_verdicts`` along with the ``evals_path``.
      - Composite mode no longer auto-invokes :func:`verify_goldens`. The
        goldens-verification path is preserved but only fires from the
        differential-only mode call site (or any caller that invokes
        :func:`verify_goldens` directly).
      - Differential-only mode (``mode="differential"``) still calls
        :func:`score_differential` with the injected ``dispatch_comparison``
        and remains unchanged for callers that want pair-comparison scoring.

    Args:
        skill_md_path: SKILL.md to score (structural-metrics input).
        baseline_skill_md: BASELINE SKILL.md for differential mode.
        modified_skill_md: MODIFIED (candidate) SKILL.md for differential mode.
        scenarios_path: ``test_scenarios.json`` path; differential-only mode
            uses this; composite mode ignores it.
        mode: ``"composite"`` (default), ``"structural"``, or
            ``"differential"``.
        dispatch_comparison: LLM sub-agent dispatcher for the differential
            grader. Required when ``mode="differential"`` and the scenarios
            list is non-empty.
        absolute_verdicts: Canonical absolute-grader verdict JSON payload
            (see ``./score-skill.md`` § Canonical verdict JSON shape).
            Required for composite mode. Built by the orchestrator-LLM
            from per-scenario grader sub-agent outputs.
        evals_path: Path to the skill's ``evals.json``. Required for
            composite mode; loaded by :func:`score_skill_absolute._load_evals`.
        skill_dir: Path to the skill's root directory (e.g.
            ``.claude/skills/session-wrap/``). Retained for backwards
            compatibility with the differential-only flow's goldens
            attachment; no-op in composite mode.
        score_single_fn: Optional injectable single-trial scorer for the
            goldens-verification pass. No-op in composite mode (no longer
            auto-invoked). Retained for backwards compatibility.
        skip_goldens: No-op in composite mode (goldens no longer auto-
            invoked). Retained for backwards compatibility with callers
            that may still pass it.

    Returns:
        CompositeScore with the per-mode score and metadata fields per the
        output contract. In composite mode the ``goldens_status`` field is
        always ``None`` and ``halt_requested`` is always ``False`` (per
        SIHC.2 Option A — goldens no longer auto-invoked).
    """
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode {mode!r}; must be one of {sorted(VALID_MODES)}")

    # --- composite mode: structural + absolute aggregator (SIHC.2 Option A)
    if mode == "composite":
        return _compute_composite_absolute(
            skill_md_path=skill_md_path,
            absolute_verdicts=absolute_verdicts,
            evals_path=evals_path,
        )

    # --- non-composite modes use the legacy base composite path -----------
    base = _compute_base_composite(
        skill_md_path=skill_md_path,
        baseline_skill_md=baseline_skill_md,
        modified_skill_md=modified_skill_md,
        scenarios_path=scenarios_path,
        mode=mode,
        dispatch_comparison=dispatch_comparison,
    )

    # --- goldens verification (preserved for non-composite modes) ---------
    # As of SIHC.2 Option A, composite mode short-circuits above and does
    # NOT reach this branch. Differential/structural-only modes retain the
    # goldens attachment for backwards compatibility with callers that wire
    # skill_dir on those paths.
    if skip_goldens or skill_dir is None:
        return base

    scorer = (
        score_single_fn if score_single_fn is not None else _default_single_trial_score
    )
    goldens = verify_goldens(skill_dir, scorer)
    return CompositeScore(
        score=base.score,
        passed=base.passed,
        total=base.total,
        status=base.status,
        goldens_status=goldens,
        halt_requested=(goldens.status == "harness-error"),
    )


def _compute_composite_absolute(
    *,
    skill_md_path: Path,
    absolute_verdicts: dict[str, Any] | None,
    evals_path: Path | None,
) -> CompositeScore:
    """Composite mode per SIHC.2 Option A: structural + absolute axis.

    Both inputs are required; missing either yields ``harness-error``.
    Partial-success semantics: one axis fine + the other raising a known
    harness exception still emits ``status="ok"`` with the surviving axis's
    raw score and ``passed=1``.
    """
    # Composite mode requires the orchestrator-built absolute payload + evals.
    if absolute_verdicts is None or evals_path is None:
        # composite mode requires absolute_verdicts + evals_path per SIHC.2
        return CompositeScore(
            score=None,
            passed=0,
            total=2,
            status="harness-error",
        )

    structural_result = None
    try:
        structural_result = run_structural(skill_md_path)
    except (FileNotFoundError, NotImplementedError):
        pass

    absolute_weighted: float | None = None
    try:
        evals_data = _load_evals(evals_path)
        absolute_result = aggregate_absolute(absolute_verdicts, evals_data)
        absolute_weighted = float(absolute_result["weighted_score"])
    except (FileNotFoundError, KeyError, ValueError):
        pass

    if structural_result is None and absolute_weighted is None:
        return CompositeScore(
            score=None,
            passed=0,
            total=2,
            status="harness-error",
        )

    if structural_result is None:
        # Partial success: only absolute scored.
        assert absolute_weighted is not None  # narrowing
        return CompositeScore(
            score=max(0.0, min(1.0, absolute_weighted)),
            passed=1,
            total=2,
            status="ok",
        )

    if absolute_weighted is None:
        # Partial success: only structural scored.
        return CompositeScore(
            score=max(0.0, min(1.0, float(structural_result.score))),
            passed=1,
            total=2,
            status="ok",
        )

    # Both axes scored: compose with documented weights.
    raw = (
        STRUCTURAL_WEIGHT * float(structural_result.score)
        + ABSOLUTE_WEIGHT * absolute_weighted
    )
    # Defensive clamp - by linearity raw is already in [0, 1] when each
    # input is, but keeps the invariant explicit if future weight tweaks
    # ever drift the constants.
    final = max(0.0, min(1.0, raw))
    return CompositeScore(
        score=final,
        passed=2,
        total=2,
        status="ok",
    )


def _compute_base_composite(
    *,
    skill_md_path: Path,
    baseline_skill_md: Path,
    modified_skill_md: Path,
    scenarios_path: Path | None,
    mode: str,
    dispatch_comparison: (Callable[[str, str, dict[str, Any]], ScenarioVerdict] | None),
) -> CompositeScore:
    """Compute the structural-only or differential-only score, no goldens.

    Composite mode no longer routes through this function as of SIHC.2 Option
    A; see :func:`_compute_composite_absolute`. The differential branch is
    preserved so callers that explicitly request ``mode="differential"``
    continue to work; the differential grader itself is unchanged.
    """
    # --- structural-only mode ---------------------------------------------
    # Single axis; only the documented harness-failure exception classes are
    # caught. Programmer bugs (KeyError, TypeError, AttributeError, generic
    # ValueErrors raised somewhere unexpected) propagate so they surface as
    # real failures rather than being silently misreported as harness-error.
    if mode == "structural":
        try:
            structural = run_structural(skill_md_path)
        except (FileNotFoundError, NotImplementedError):
            return CompositeScore(
                score=None,
                passed=0,
                total=1,
                status="harness-error",
            )
        return CompositeScore(
            score=structural.score,
            passed=1,
            total=1,
            status="ok",
        )

    # --- scenarios load (differential only) -------------------------------
    # _load_scenarios raises ValueError on malformed input (legitimate
    # user-data failure). Catch it explicitly and map to harness-error;
    # other call sites' ValueErrors are NOT swallowed by this catch.
    try:
        scenarios = _load_scenarios(scenarios_path)
    except (FileNotFoundError, ValueError):
        return CompositeScore(
            score=None,
            passed=0,
            total=1,
            status="harness-error",
        )

    # --- differential-only mode -------------------------------------------
    if mode == "differential":
        try:
            differential = score_differential(
                baseline_skill_md,
                modified_skill_md,
                scenarios,
                dispatch_comparison=dispatch_comparison,
            )
        except (FileNotFoundError, NotImplementedError):
            return CompositeScore(
                score=None,
                passed=0,
                total=1,
                status="harness-error",
            )
        return CompositeScore(
            score=differential.score,
            passed=differential.total_scenarios,
            total=differential.total_scenarios,
            status="ok",
        )

    # Composite mode is handled by _compute_composite_absolute; reaching
    # here means an unhandled VALID_MODES value was added without wiring.
    raise AssertionError(
        f"_compute_base_composite reached for mode={mode!r}; composite mode "
        "should be handled by _compute_composite_absolute"
    )


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="score_skill_composite.py",
        description=(
            "Composite skill-scoring procedure. Composes structural + "
            "absolute-grader scores per ./score-skill.md (SIHC.2 Option A). "
            "Emits the single-trial JSON shape documented in "
            "skill-iterate/SKILL.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--skill-md",
        type=Path,
        required=True,
        help="Path to the SKILL.md to score (structural-metrics input)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help=(
            "Path to the BASELINE SKILL.md (differential-only mode input; "
            "unused by composite mode per SIHC.2 Option A)."
        ),
    )
    parser.add_argument(
        "--modified",
        type=Path,
        required=True,
        help=(
            "Path to the MODIFIED (candidate) SKILL.md (differential-only "
            "mode input; unused by composite mode per SIHC.2 Option A)."
        ),
    )
    parser.add_argument(
        "--scenarios",
        type=Path,
        default=None,
        help=(
            "Path to test_scenarios.json (differential-only mode input). "
            "Omit or pass a non-existent path for an empty scenarios list "
            "(differential neutral 0.5). Unused by composite mode."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=sorted(VALID_MODES),
        default="composite",
        help="Scoring mode (default: composite)",
    )
    parser.add_argument(
        "--absolute-verdicts",
        type=Path,
        default=None,
        help=(
            "Composite mode only: path to the canonical absolute-grader "
            "verdict JSON payload (see ./score-skill.md § Canonical verdict "
            "JSON shape). Required for composite mode to produce a real "
            "score; absence yields harness-error."
        ),
    )
    parser.add_argument(
        "--evals",
        type=Path,
        default=None,
        dest="evals_path",
        help=(
            "Composite mode only: path to the skill's evals.json. Required "
            "alongside --absolute-verdicts so the aggregator can resolve "
            "per-category weights."
        ),
    )
    parser.add_argument(
        "--stub-verdict",
        choices=("better", "worse", "same"),
        default=None,
        help=(
            "Differential-only mode: use a deterministic stub dispatcher "
            "for the differential grader. Unused by composite mode."
        ),
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=None,
        help=(
            "Path to the skill's root directory (e.g. "
            ".claude/skills/session-wrap/). Enables the goldens-verification "
            "pass against <skill-dir>/evals/golden/ for differential/"
            "structural-only modes only. Composite mode no longer auto-"
            "invokes goldens per SIHC.2 Option A; flag is a no-op there."
        ),
    )
    parser.add_argument(
        "--skip-goldens",
        action="store_true",
        help=(
            "Bypass the goldens-verification pass even when --skill-dir is "
            "supplied. No-op in composite mode."
        ),
    )
    args = parser.parse_args(argv)

    dispatcher = (
        _make_fixed_verdict_dispatcher(args.stub_verdict)
        if args.stub_verdict is not None
        else None
    )

    absolute_verdicts: dict[str, Any] | None = None
    if args.absolute_verdicts is not None:
        absolute_verdicts = json.loads(
            args.absolute_verdicts.read_text(encoding="utf-8-sig")
        )

    result = score_composite(
        skill_md_path=args.skill_md,
        baseline_skill_md=args.baseline,
        modified_skill_md=args.modified,
        scenarios_path=args.scenarios,
        mode=args.mode,
        dispatch_comparison=dispatcher,
        absolute_verdicts=absolute_verdicts,
        evals_path=args.evals_path,
        skill_dir=args.skill_dir,
        skip_goldens=args.skip_goldens,
    )

    print(json.dumps(asdict(result), indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
