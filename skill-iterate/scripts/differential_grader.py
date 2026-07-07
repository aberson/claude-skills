"""Pair-comparison ("differential") scoring for skill-iterate.

UNWIRED FROM COMPOSITE AS OF SIHC.2 (2026-05-26). Preserved for possible
Option B revisit (see ``_shared/score_skill_absolute.py``'s module docstring
REVISIT TRIGGER block — reintroduce as a third axis or as a ship-gate
validator if assertion-targeted iteration produces clear local-optima
behavior). Differential mode in
``_shared/score_skill_composite.score_composite()`` still exposes this
grader directly via ``mode="differential"``; composite mode no longer calls
it.

Closes the "good vs better" gap that spec-compliance grading misses. For each
entry in a skill's ``test_scenarios.json`` we dispatch a comparison sub-agent
that judges the BASELINE output vs the MODIFIED output and returns a verdict
(``"better"`` | ``"worse"`` | ``"same"``). The verdicts are then aggregated
into a single ``DifferentialScore`` in ``[0.0, 1.0]``.

This module owns the **aggregation logic** (pure, fully unit-tested) plus the
sub-agent dispatch *seam*. The real LLM dispatcher is wired up in Step 5
(see ``_shared/score-skill.md``); Step 4 ships a stub that raises
``NotImplementedError`` so production callers fail loudly until they inject a
dispatcher explicitly.

Score formula (plan §5):

    raw_score = (better_count - worse_count) / total_scenarios     # in [-1, 1]
    score     = (raw_score + 1) / 2                                 # in [0, 1]

Edge cases handled in :func:`aggregate_verdicts`:
    - total_scenarios == 0     -> raw=0.0, score=0.5 (neutral, no signal)
    - all "same"               -> raw=0.0, score=0.5 (neutral)
    - all "better"             -> raw=1.0, score=1.0
    - all "worse"              -> raw=-1.0, score=0.0
    - final score clamped to [0, 1] defensively

CLI:
    python differential_grader.py <baseline.md> <modified.md> <scenarios.json>
                                  [--stub-verdict {better,worse,same}]

The ``--stub-verdict`` flag swaps in a deterministic dispatcher that returns the
named verdict for every scenario (used for smoke checks until Step 5 wires the
real sub-agent dispatcher).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

VALID_VERDICTS: frozenset[str] = frozenset({"better", "worse", "same"})


# --- Module-level constants ---------------------------------------------------

# The prompt template the real sub-agent dispatcher (Step 5, ``_shared/
# score-skill.md``) will use when comparing the baseline output to the modified
# output. Kept as a module-level constant so Step 5 and tests reference one
# canonical string instead of redefining it.
#
# IMPORTANT: callers MUST use :func:`format_comparison_prompt` rather than
# invoking ``.format(...)`` directly. Real ``baseline_output`` /
# ``modified_output`` strings are entire SKILL.md files that routinely contain
# literal ``{`` / ``}`` (JSON examples, dict literals, format strings); Python's
# ``str.format()`` would raise ``KeyError`` on those braces. The helper uses
# ``str.replace()`` on the four named placeholders below, which is brace-safe.
#
# Required substitutions (handled by :func:`format_comparison_prompt`):
#   - {scenario_prompt}    -> the scenario's prompt text
#   - {scenario_criteria}  -> evaluation criteria for this scenario
#   - {baseline_output}    -> output produced with baseline SKILL.md
#   - {modified_output}    -> output produced with modified SKILL.md
COMPARISON_PROMPT_TEMPLATE: str = """\
You are evaluating two outputs from the same skill, one based on a BASELINE version
of SKILL.md and one based on a MODIFIED version.

Scenario: {scenario_prompt}
Evaluation criteria: {scenario_criteria}

BASELINE OUTPUT:
{baseline_output}

MODIFIED OUTPUT:
{modified_output}

Which output better satisfies the criteria? Respond with strict JSON:
  {{"verdict": "better" | "worse" | "same", "reason": "<one sentence>"}}

"better" = modified is better than baseline. "worse" = modified is worse. "same" = no meaningful difference.
"""


def format_comparison_prompt(
    scenario: dict[str, Any],
    baseline_output: str,
    modified_output: str,
) -> str:
    """Brace-safe rendering of :data:`COMPARISON_PROMPT_TEMPLATE`.

    Python's ``str.format()`` chokes on literal ``{`` / ``}`` in
    ``baseline_output`` / ``modified_output`` content (SKILL.md files routinely
    contain JSON examples, dict literals, or other format-string-ish text).
    This helper substitutes via ``str.replace()`` on the four named
    placeholders, which is immune to that failure mode.

    Required scenario keys: ``'prompt'``, ``'criteria'``. Missing keys raise
    ``KeyError`` immediately rather than silently leaving an unsubstituted
    placeholder in the prompt.
    """
    prompt = COMPARISON_PROMPT_TEMPLATE
    prompt = prompt.replace("{scenario_prompt}", scenario["prompt"])
    prompt = prompt.replace("{scenario_criteria}", scenario["criteria"])
    prompt = prompt.replace("{baseline_output}", baseline_output)
    prompt = prompt.replace("{modified_output}", modified_output)
    return prompt


# --- Value objects ------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioVerdict:
    """One comparison sub-agent's verdict for a single scenario."""

    scenario_id: str
    verdict: str  # "better" | "worse" | "same"
    reason: str


@dataclass(frozen=True)
class DifferentialScore:
    """Aggregated differential score across all scenarios.

    Attributes:
        score: Composite in ``[0.0, 1.0]``. 0.5 is neutral / no-signal.
        raw_score: Pre-normalization in ``[-1.0, 1.0]`` (better-worse / total).
        counts: ``{"better": N, "worse": N, "same": N}``.
        verdicts: Per-scenario detail in the order received.
        total_scenarios: ``len(verdicts)`` — sample size for the score.
    """

    score: float
    raw_score: float
    counts: dict[str, int] = field(default_factory=dict)
    verdicts: list[ScenarioVerdict] = field(default_factory=list)
    total_scenarios: int = 0


# --- Aggregation (pure) -------------------------------------------------------


def aggregate_verdicts(verdicts: list[ScenarioVerdict]) -> DifferentialScore:
    """Convert per-scenario verdicts to a DifferentialScore. Pure function.

    Score formula (plan §5):
        raw_score = (better - worse) / total_scenarios
        score     = (raw_score + 1) / 2          # map [-1, 1] -> [0, 1]

    Empty input is treated as "no signal" (score=0.5), not an error — the
    caller's test_scenarios.json may legitimately be empty during early skill
    bootstrapping. Unknown verdict strings are counted but contribute nothing
    to the better/worse arithmetic (they pull the denominator up like a
    "same"). The final score is defensively clamped to ``[0, 1]``.
    """
    counts: dict[str, int] = {"better": 0, "worse": 0, "same": 0}
    for v in verdicts:
        if v.verdict in counts:
            counts[v.verdict] += 1
        # Unknown verdicts: not counted in better/worse/same buckets but
        # still part of total_scenarios so they dilute the signal (treated
        # like a "same" for raw-score math). Surfaced via len(verdicts) -
        # sum(counts.values()) if a caller wants to detect them.

    total = len(verdicts)
    if total == 0:
        raw = 0.0
    else:
        raw = (counts["better"] - counts["worse"]) / total

    score = (raw + 1.0) / 2.0
    # Defensive clamp. With the formula above and total > 0 this is a no-op,
    # but keeps the invariant explicit so future formula tweaks can't quietly
    # produce out-of-range scores.
    score = max(0.0, min(1.0, score))

    return DifferentialScore(
        score=score,
        raw_score=raw,
        counts=counts,
        verdicts=list(verdicts),
        total_scenarios=total,
    )


# --- Sub-agent dispatch -------------------------------------------------------


def _real_dispatch_stub(
    baseline_output: str,
    modified_output: str,
    scenario: dict[str, Any],
) -> ScenarioVerdict:
    """Production-stub dispatcher. Always raises NotImplementedError.

    Step 4 ships only the aggregation logic. Step 5's ``_shared/score-skill.md``
    wires a real LLM sub-agent into this seam. Until then, production callers
    that forget to inject ``dispatch_comparison=`` get a loud error instead of
    silent default-to-zero behavior.
    """
    raise NotImplementedError(
        "differential grader sub-agent dispatch not yet wired; "
        "supply dispatch_comparison= for testing"
    )


def score_differential(
    baseline_skill_md: Path,
    modified_skill_md: Path,
    scenarios: list[dict[str, Any]],
    *,
    dispatch_comparison: Callable[[str, str, dict[str, Any]], ScenarioVerdict] | None = None,
) -> DifferentialScore:
    """Run pair-comparison for each scenario and aggregate.

    Reads both SKILL.md files (utf-8-sig to tolerate BOM — see Step 3 iter-2)
    and passes their *contents* as the baseline/modified output strings to the
    injected dispatcher. In Step 5 the dispatcher will produce real per-skill
    outputs first; for Step 4 we treat the SKILL.md text itself as the
    "output" so the seam is uniform.

    Args:
        baseline_skill_md: Path to the baseline SKILL.md.
        modified_skill_md: Path to the modified (candidate) SKILL.md.
        scenarios: List of scenario dicts. Each must have at minimum an ``id``;
            ``prompt`` / ``criteria`` are recommended but not enforced here.
        dispatch_comparison: Callable that takes
            ``(baseline_text, modified_text, scenario_dict)`` and returns a
            ``ScenarioVerdict``. If ``None``, falls back to the production
            stub which raises ``NotImplementedError``.

    Returns:
        ``DifferentialScore`` aggregating every verdict the dispatcher produced.
    """
    if not baseline_skill_md.is_file():
        raise FileNotFoundError(
            f"baseline SKILL.md not found or not a file: {baseline_skill_md}"
        )
    if not modified_skill_md.is_file():
        raise FileNotFoundError(
            f"modified SKILL.md not found or not a file: {modified_skill_md}"
        )

    # utf-8-sig strips a leading BOM if present (PowerShell Set-Content -Encoding
    # utf8 writes one on Win PS 5.1 — see workspace memory
    # feedback_set_content_utf8_adds_bom).
    baseline_text = baseline_skill_md.read_text(encoding="utf-8-sig")
    modified_text = modified_skill_md.read_text(encoding="utf-8-sig")

    dispatcher = dispatch_comparison if dispatch_comparison is not None else _real_dispatch_stub

    verdicts: list[ScenarioVerdict] = []
    for scenario in scenarios:
        verdict = dispatcher(baseline_text, modified_text, scenario)
        verdicts.append(verdict)

    return aggregate_verdicts(verdicts)


# --- CLI ----------------------------------------------------------------------


def _make_fixed_verdict_dispatcher(
    verdict: str,
) -> Callable[[str, str, dict[str, Any]], ScenarioVerdict]:
    """Build a deterministic dispatcher that returns ``verdict`` for everything.

    Used by the CLI's ``--stub-verdict`` flag for smoke checks before the real
    Step 5 dispatcher is wired. Also a useful test helper.
    """
    if verdict not in VALID_VERDICTS:
        raise ValueError(
            f"stub verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}"
        )

    def _dispatch(
        _baseline: str, _modified: str, scenario: dict[str, Any]
    ) -> ScenarioVerdict:
        return ScenarioVerdict(
            scenario_id=str(scenario.get("id", "<no-id>")),
            verdict=verdict,
            reason=f"stub dispatcher: fixed verdict {verdict!r}",
        )

    return _dispatch


def _load_scenarios(scenarios_path: Path) -> list[dict[str, Any]]:
    """Load test_scenarios.json; tolerate either a top-level list or
    ``{"scenarios": [...]}`` wrapper for forward-compat with composite schemas.
    """
    raw = scenarios_path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("scenarios"), list):
        return data["scenarios"]
    raise ValueError(
        f"unrecognized scenarios JSON shape in {scenarios_path}: "
        "expected a list or an object with a 'scenarios' list"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="differential_grader.py",
        description=(
            "Pair-comparison score between a BASELINE and MODIFIED SKILL.md "
            "across all entries in a test_scenarios.json. Emits a JSON "
            "DifferentialScore. Use --stub-verdict for smoke checks until the "
            "real sub-agent dispatcher is wired in Step 5."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "baseline_skill_md",
        type=Path,
        help="Path to the baseline SKILL.md",
    )
    parser.add_argument(
        "modified_skill_md",
        type=Path,
        help="Path to the modified (candidate) SKILL.md",
    )
    parser.add_argument(
        "scenarios_path",
        type=Path,
        help="Path to test_scenarios.json (list of scenario dicts)",
    )
    parser.add_argument(
        "--stub-verdict",
        choices=sorted(VALID_VERDICTS),
        default=None,
        help=(
            "Use a deterministic stub dispatcher that returns the named "
            "verdict for every scenario. Required until Step 5 wires the "
            "real sub-agent dispatcher; without it, the production stub "
            "raises NotImplementedError."
        ),
    )

    args = parser.parse_args(argv)

    try:
        scenarios = _load_scenarios(args.scenarios_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: failed to load scenarios: {exc}", file=sys.stderr)
        return 3

    dispatcher = (
        _make_fixed_verdict_dispatcher(args.stub_verdict)
        if args.stub_verdict is not None
        else None
    )

    try:
        result = score_differential(
            args.baseline_skill_md,
            args.modified_skill_md,
            scenarios,
            dispatch_comparison=dispatcher,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except NotImplementedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4

    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
