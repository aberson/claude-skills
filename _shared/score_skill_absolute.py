"""Absolute grader aggregator for SIHC Phase SIHC.2 prototype.

The LLM dispatch (rendering each scenario's output + grading 21 assertions) is
done by the orchestrator-LLM. This module just takes the verdicts as input,
aggregates them against evals.json's category weights, and produces a
brainstorm-ready output: ranked failed_assertions + passing_assertion_ids
("do not break" list) + composite score.

ARCHITECTURAL CHOICE — Option A (2026-05-26 decision):
This module REPLACES the differential grader (`differential_grader.py`) entirely
for prose-skill hill-climbing, not augments it. Composite becomes
`0.4 * structural + 0.6 * absolute_weighted` (mirroring the prior split).
REVISIT TRIGGER: if assertion-targeted iteration produces clear local-optima
behavior (loop passes the 21 evals but produces measurably worse outputs in
ways the rubric doesn't capture), reintroduce the differential grader as a
third axis or as a ship-gate validator. The decision to drop differential
trades subjective-quality signal for tractable hill-climbing gradient.

Single-trial input shape:

    {
      "trials": [
        {
          "scenario_id": "scenario_single_project_with_friction",
          "verdicts": {
            "1": {"verdict": true,  "reason": "..."},
            "2": {"verdict": false, "reason": "Fence label was 'plain' not 'text'"},
            ...all 21 assertion ids...
          }
        },
        ...3 scenarios
      ]
    }

For N-trial median (saturation confirmation): pass N copies of `trials`, the
aggregator collapses verdicts via per-(scenario,assertion) majority vote.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _load_evals(evals_path: Path) -> dict[str, Any]:
    """Load evals.json and build an assertion lookup keyed by id.

    Handles both v2.0 schema (category.weight present) and v1.x schema (no
    weight field). When weight is missing, assigns equal weight = 1/n_categories
    so weighted_score collapses to simple equal-weight aggregation. The
    brainstorm-ranking layer still gets a deterministic ordering (categories
    tied at equal weight rank by category name asc, then assertion id asc).
    """
    raw = evals_path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    n_cats = len(data["categories"])
    default_weight = 1.0 / n_cats if n_cats > 0 else 0.0
    by_id: dict[int, dict[str, Any]] = {}
    categories_normalized: list[dict[str, Any]] = []
    for cat in data["categories"]:
        weight = cat.get("weight", default_weight)
        cat_norm = {**cat, "weight": weight}
        categories_normalized.append(cat_norm)
        for ev in cat["evals"]:
            by_id[ev["id"]] = {
                "id": ev["id"],
                "statement": ev["statement"],
                "source": ev["source"],
                "defect_type": ev.get("defect_type", "unspecified"),
                "category_name": cat["name"],
                "category_weight": weight,
            }
    return {"by_id": by_id, "categories": categories_normalized, "raw": data}


def _median_verdict(verdicts: list[bool]) -> bool:
    """Majority-vote on bool verdicts. Ties (even count, 50/50) resolve to False
    (strict — the assertion only passes if a majority say so)."""
    c = Counter(verdicts)
    return c[True] > c[False]


def aggregate(payload: dict[str, Any], evals_data: dict[str, Any]) -> dict[str, Any]:
    """Aggregate verdicts → composite score + failure list ranked by category weight.

    Multi-trial support: payload["trials"] is a flat list of per-scenario
    verdict-blocks. Multiple blocks for the same scenario are combined via
    per-assertion median vote.
    """
    by_id = evals_data["by_id"]
    categories = evals_data["categories"]

    # Group trials by scenario_id; collect per-(scenario, assertion) verdicts.
    per_scenario_assertion: dict[tuple[str, int], list[bool]] = {}
    per_scenario_assertion_reasons: dict[tuple[str, int], list[str]] = {}
    for trial in payload["trials"]:
        sid = trial["scenario_id"]
        for aid_str, v in trial["verdicts"].items():
            aid = int(aid_str)
            key = (sid, aid)
            # Tolerate both "verdict" (canonical) and "result" (some grader
            # sub-agents emit this) keys — the aggregator is downstream of
            # heterogeneous grader prompts and shouldn't be brittle to that.
            raw = v.get("verdict", v.get("result"))
            if raw is None:
                raise KeyError(
                    f"trial scenario={sid} assertion={aid}: missing 'verdict' or 'result' key"
                )
            per_scenario_assertion.setdefault(key, []).append(bool(raw))
            per_scenario_assertion_reasons.setdefault(key, []).append(v.get("reason", ""))

    # Collapse via median.
    final_verdicts: dict[tuple[str, int], tuple[bool, str]] = {}
    for key, votes in per_scenario_assertion.items():
        verdict = _median_verdict(votes)
        # Reason from a vote that matched the median (first one).
        reasons = per_scenario_assertion_reasons[key]
        matching_reason = next(
            (r for r, v in zip(reasons, votes) if v == verdict),
            reasons[0] if reasons else "",
        )
        final_verdicts[key] = (verdict, matching_reason)

    # Tally per-category and overall.
    total = len(final_verdicts)
    passed = sum(1 for v, _ in final_verdicts.values() if v)

    # Per-category aggregation for weighted score.
    cat_tally: dict[str, dict[str, Any]] = {}
    for cat in categories:
        name = cat["name"]
        cat_tally[name] = {
            "name": name,
            "weight": cat["weight"],
            "passed": 0,
            "applicable": 0,
            "score": 0.0,
        }
    for (sid, aid), (verdict, _reason) in final_verdicts.items():
        cat_name = by_id[aid]["category_name"]
        cat_tally[cat_name]["applicable"] += 1
        if verdict:
            cat_tally[cat_name]["passed"] += 1
    for cat in cat_tally.values():
        if cat["applicable"] > 0:
            cat["score"] = cat["passed"] / cat["applicable"]
        else:
            cat["score"] = 0.0  # no data → 0 contribution

    weighted_score = sum(cat["weight"] * cat["score"] for cat in cat_tally.values())
    simple_score = passed / total if total > 0 else 0.0

    # Failed assertions, enriched + ranked by category weight (desc), then by
    # assertion id (asc, for determinism).
    failures: list[dict[str, Any]] = []
    passing_pairs: list[dict[str, Any]] = []
    for (sid, aid), (verdict, reason) in sorted(final_verdicts.items()):
        meta = by_id[aid]
        entry = {
            "assertion_id": aid,
            "scenario_id": sid,
            "category_name": meta["category_name"],
            "category_weight": meta["category_weight"],
            "statement": meta["statement"],
            "source": meta["source"],
            "defect_type": meta["defect_type"],
            "grader_reason": reason,
        }
        if verdict:
            passing_pairs.append({"assertion_id": aid, "scenario_id": sid})
        else:
            failures.append(entry)

    failures.sort(key=lambda f: (-f["category_weight"], f["assertion_id"]))
    # passing_pairs lex-sorted by (assertion_id, scenario_id) per SIHC.2 spec.
    # Without this explicit sort the order leaks the (sid, aid) iteration order
    # of final_verdicts above, which sorts scenario_id first — wrong axis.
    passing_pairs.sort(key=lambda p: (p["assertion_id"], p["scenario_id"]))

    return {
        "weighted_score": round(weighted_score, 6),
        "simple_score": round(simple_score, 6),
        "passed": passed,
        "total": total,
        "status": "ok",
        "category_scores": list(cat_tally.values()),
        "failed_assertions": failures,
        "passing_pairs": passing_pairs,
        "n_trials_per_scenario": {
            sid: len([t for t in payload["trials"] if t["scenario_id"] == sid])
            for sid in set(t["scenario_id"] for t in payload["trials"])
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate absolute grader verdicts into composite score + ranked failures",
    )
    parser.add_argument("--evals", type=Path, required=True, help="Path to evals.json")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Path to verdicts JSON. Use '-' or omit for stdin.",
    )
    args = parser.parse_args(argv)

    if args.input is None or str(args.input) == "-":
        payload_raw = sys.stdin.read()
    else:
        payload_raw = args.input.read_text(encoding="utf-8")
    payload = json.loads(payload_raw)

    evals_data = _load_evals(args.evals)
    result = aggregate(payload, evals_data)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
