"""Append-only writer for skill-iterate results.tsv.

A small file-I/O helper invoked by the /skill-iterate orchestrator-LLM once per
iteration to record (commit, score, status, description, wall_seconds) in a
deterministic, tab-separated row. The file is append-only; this module never
seeks backwards, truncates, or rewrites prior rows.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

VALID_STATUSES: frozenset[str] = frozenset({"baseline", "keep", "revert", "crash"})
HEADER: str = "commit\tscore\tstatus\tdescription\twall_seconds\n"


def _sanitize_description(description: str) -> str:
    """Replace tab and newline characters with single spaces to preserve TSV integrity.

    Handles CRLF (\\r\\n) as a single terminator so Windows line-endings collapse to
    one space, not two.
    """
    return (
        description.replace("\r\n", " ")
        .replace("\t", " ")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def append_result(
    skill_path: Path,
    commit: str,
    score: float | None,
    status: str,
    description: str,
    wall_seconds: float,
) -> Path:
    """Append one row to <skill_path>/evals/results.tsv. Returns the file path written.

    Creates the file with a TSV header on first call. Subsequent calls append only.
    The file is append-only; this function MUST NOT seek backwards, truncate, or rewrite.

    Schema (5 columns, tab-separated):
        commit  score  status  description  wall_seconds

    - `commit`: passed verbatim (caller is responsible for "baseline" sentinel on iter-0).
    - `score`: formatted as 6 decimal places for float values (e.g. "0.812345"), or the literal
      string "NULL" if None (preserves the AMBIGUOUS/crash unscorable signaling).
    - `status`: must be one of {"baseline", "keep", "revert", "crash"} - raise ValueError otherwise.
    - `description`: tabs and newlines stripped (replaced with single space) to preserve TSV integrity.
    - `wall_seconds`: formatted as 3 decimal places (e.g. "8.142").
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid status {status!r}; must be one of {sorted(VALID_STATUSES)}"
        )

    if score is not None:
        if not math.isfinite(score):
            raise ValueError(
                f"invalid score {score!r}; must be finite (no NaN/Inf) and in [0.0, 1.0]"
            )
        if not (0.0 <= score <= 1.0):
            raise ValueError(
                f"invalid score {score!r}; must be in [0.0, 1.0]"
            )

    evals_dir = skill_path / "evals"
    if not evals_dir.is_dir():
        raise FileNotFoundError(f"evals directory does not exist: {evals_dir}")

    results_path = evals_dir / "results.tsv"
    score_field = "NULL" if score is None else f"{score:.6f}"
    desc_field = _sanitize_description(description)
    wall_field = f"{wall_seconds:.3f}"
    row = f"{commit}\t{score_field}\t{status}\t{desc_field}\t{wall_field}\n"

    # Single-writer assumption: caller must serialize append_result calls for a
    # given skill_path. /skill-iterate's per-skill serial loop guarantees this.
    file_existed = results_path.exists()
    with results_path.open("a", encoding="utf-8", newline="") as fh:
        if not file_existed:
            fh.write(HEADER)
        fh.write(row)

    return results_path


def _parse_score(raw: str) -> float | None:
    """Parse a CLI score argument: exact 'NULL' -> None, else float.

    Case-sensitive on the NULL sentinel to match the help text and avoid ambiguity
    with float strings like 'nan'/'Null'/'null' that should not silently round-trip
    to a None marker.
    """
    if raw == "NULL":
        return None
    return float(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="append_result.py",
        description=(
            "Append one row to <skill_path>/evals/results.tsv.\n"
            "Schema: commit\\tscore\\tstatus\\tdescription\\twall_seconds\n"
            "  score: float formatted to 6 decimals, or literal 'NULL' for None.\n"
            "  status: one of {baseline, keep, revert, crash}.\n"
            "  description: tabs/newlines replaced with single space.\n"
            "  wall_seconds: float formatted to 3 decimals."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("skill_path", type=Path, help="absolute path to .claude/skills/<name>/")
    parser.add_argument("commit", type=str, help="7-char short SHA or 'baseline'")
    parser.add_argument("score", type=str, help="float in [0.0, 1.0] or 'NULL'")
    parser.add_argument(
        "status",
        type=str,
        help="one of: baseline, keep, revert, crash",
    )
    parser.add_argument("description", type=str, help="one-line edit description")
    parser.add_argument("wall_seconds", type=float, help="elapsed wall-clock for iteration")

    args = parser.parse_args(argv)

    skill_path: Path = args.skill_path
    if not skill_path.is_dir():
        print(f"error: skill_path does not exist or is not a directory: {skill_path}", file=sys.stderr)
        return 3

    try:
        score = _parse_score(args.score)
    except ValueError as exc:
        print(f"error: invalid score {args.score!r}: {exc}", file=sys.stderr)
        return 1

    try:
        append_result(
            skill_path=skill_path,
            commit=args.commit,
            score=score,
            status=args.status,
            description=args.description,
            wall_seconds=args.wall_seconds,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
