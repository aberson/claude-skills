"""Morning summary writer for /skill-iterate.

A deterministic markdown writer invoked by the /skill-iterate orchestrator-LLM
once per overnight run (at clean queue completion, kill-switch graceful stop, or
exception path via finally). Emits a single markdown file at
<runs_dir>/<date_str>.md with per-skill scores, top keeps, excluded skills, and
run metadata. Filenames are auto-disambiguated (b/c/d/... suffix) per the
workspace memory feedback_auto_disambiguate_filenames.

Stdlib-only, ASCII-only source.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

VALID_SHIP_STATUSES: frozenset[str] = frozenset(
    {"keep", "no-improvement", "defect-park", "dirty-master-skip"}
)


@dataclass
class SkillResult:
    """One per processed skill. Mirrors the SkillResult shape in the step prompt."""

    skill: str
    baseline_score: float | None
    final_score: float | None
    delta: float | None
    iterations_run: int
    wall_seconds_total: float
    ship_status: str
    top_keep_descriptions: list[str] = field(default_factory=list)
    parked_issue_url: str | None = None


def _fmt_score(value: float | None) -> str:
    """Format a score with 2-decimal precision; '--' for None."""
    if value is None:
        return "--"
    return f"{value:.2f}"


def _fmt_delta(value: float | None) -> str:
    """Format a delta as signed 2-decimal; '--' for None.

    +0.06 / 0.00 / -0.03; the leading '+' is explicit on positive values.
    """
    if value is None:
        return "--"
    if value > 0:
        return f"+{value:.2f}"
    if value == 0:
        return "0.00"
    # Negative values: Python's default format already prints the '-'.
    return f"{value:.2f}"


def _fmt_wall(value: float) -> str:
    """Format wall seconds as an integer (rounded)."""
    return str(int(round(value)))


def _fmt_link(result: SkillResult) -> str:
    """Render the link cell for the per-skill table.

    GitHub issue number (#142) when parked_issue_url is a #N URL.
    Relative path for local fallback (anything not starting with '#').
    '--' when no parked_issue_url is present (any ship_status).
    """
    if result.parked_issue_url is None:
        return "--"
    return result.parked_issue_url


def _format_total_wall(total_seconds: float) -> str:
    """Format a total-wall duration as 'Xh Ym'.

    Used for the run-metadata footer line.
    """
    seconds = int(round(total_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def _now_iso8601_utc() -> str:
    """Return the current UTC time as an ISO8601 string with seconds precision."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_output_path(runs_dir: Path, date_str: str) -> Path:
    """Auto-disambiguate <runs_dir>/<date_str>.md to .../<date_str>{b,c,d,...}.md.

    Returns the first non-existing path: original, then b, then c, ... through z.
    If all 26 letter-suffixes are taken, raises FileExistsError.
    """
    base = runs_dir / f"{date_str}.md"
    if not base.exists():
        return base
    # Try b, c, d, ..., z
    for code in range(ord("b"), ord("z") + 1):
        candidate = runs_dir / f"{date_str}{chr(code)}.md"
        if not candidate.exists():
            return candidate
    raise FileExistsError(
        f"all 26 letter-suffix filenames exhausted under {runs_dir} for {date_str}"
    )


def _render_per_skill_table(skill_results: list[SkillResult]) -> list[str]:
    """Render the per-skill results table as a list of lines (no trailing newlines)."""
    lines: list[str] = []
    lines.append("## Per-skill results")
    lines.append("")
    lines.append("| skill | baseline | final | delta | iters | wall_s | status | link |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in skill_results:
        lines.append(
            "| {skill} | {baseline} | {final} | {delta} | {iters} | {wall} | {status} | {link} |".format(
                skill=r.skill,
                baseline=_fmt_score(r.baseline_score),
                final=_fmt_score(r.final_score),
                delta=_fmt_delta(r.delta),
                iters=r.iterations_run,
                wall=_fmt_wall(r.wall_seconds_total),
                status=r.ship_status,
                link=_fmt_link(r),
            )
        )
    return lines


def _render_top_keeps(skill_results: list[SkillResult]) -> list[str]:
    """Render the 'Top keeps per skill' section.

    Skips skills with no resolvable scores (baseline/final both None) - those
    are crash/defect skills with nothing to show.

    For skills with `top_keep_descriptions` empty AND ship_status in
    {keep, no-improvement}, emits '(no keeps this run)' to keep the structure
    visible. For defect-park rows, emits the 'parked after N consecutive crashes'
    line so the operator can find the parked issue.
    """
    lines: list[str] = []
    lines.append("## Top keeps per skill")
    lines.append("")
    for r in skill_results:
        if r.baseline_score is None and r.final_score is None and r.ship_status != "defect-park":
            # Nothing to report for an unscored, non-park skill.
            continue
        if r.ship_status == "defect-park":
            lines.append(f"### {r.skill} (parked after consecutive crashes)")
            lines.append("See parked issue or local fallback file.")
            lines.append("")
            continue
        kept = len(r.top_keep_descriptions)
        # Header line: include iters count to give the reader a kept-vs-total signal.
        lines.append(f"### {r.skill} (kept {kept} of {r.iterations_run})")
        if not r.top_keep_descriptions:
            lines.append("(no keeps this run)")
        else:
            for i, desc in enumerate(r.top_keep_descriptions, start=1):
                lines.append(f"{i}. {desc}")
        lines.append("")
    # Strip trailing blank if present.
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _render_excluded_section(
    skipped_by_skip_list: list[str] | None,
    skipped_by_cross_night: list[dict] | None,
) -> list[str]:
    """Render the 'Skills excluded' section.

    Returns [] if both lists are empty/None - caller omits the section entirely.
    """
    skip_list = skipped_by_skip_list or []
    cross = skipped_by_cross_night or []
    if not skip_list and not cross:
        return []
    lines: list[str] = []
    lines.append("## Skills excluded")
    lines.append("")
    if skip_list:
        names = ", ".join(skip_list)
        lines.append(f"- {names}: skip-list (per Embedded skip-list)")
    if cross:
        for entry in cross:
            name = entry.get("skill", "?")
            mtime = entry.get("mtime_iso", "?")
            lines.append(
                f"- {name}: cross-night-resume (results.tsv mtime {mtime} within 24h)"
            )
    return lines


def _render_run_metadata(
    started_at: str,
    ended_at: str,
    skill_results: list[SkillResult],
    skipped_by_skip_list: list[str] | None,
    skipped_by_cross_night: list[dict] | None,
    lock_path: str = "<workspace>/.skill-iterate.lock",
) -> list[str]:
    """Render the 'Run metadata' footer section."""
    total_wall = sum(r.wall_seconds_total for r in skill_results)
    excluded_count = len(skipped_by_skip_list or []) + len(skipped_by_cross_night or [])
    lines: list[str] = []
    lines.append("## Run metadata")
    lines.append("")
    lines.append(f"- Started: {started_at}")
    lines.append(f"- Ended: {ended_at}")
    lines.append(f"- Total wall time: {_format_total_wall(total_wall)}")
    lines.append(f"- Skills processed: {len(skill_results)}")
    lines.append(f"- Skills excluded: {excluded_count}")
    lines.append(f"- Lock file path: {lock_path} (released)")
    return lines


def write_morning_summary(
    runs_dir: Path,
    skill_results: list[SkillResult],
    started_at: str,
    ended_at: str,
    date_str: str | None = None,
    partial: bool = False,
    skipped_by_skip_list: list[str] | None = None,
    skipped_by_cross_night: list[dict] | None = None,
) -> Path:
    """Write the markdown morning summary to <runs_dir>/<date_str>.md.

    Auto-disambiguates filenames per workspace memory feedback_auto_disambiguate_filenames:
    if <date_str>.md exists, append b/c/d/... suffix and write to that path instead.
    Returns the path actually written to.

    `partial=True` adds a header line '(partial -- kill-switch hit at <iso8601>)'
    and processes only skill_results provided (caller is responsible for passing
    the subset that completed before kill-switch).

    All ASCII; the en-dash compromise in the markdown body is '--' (per
    .claude/rules/windows-shell.md em-dash rule).
    """
    if date_str is None:
        date_str = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    runs_dir.mkdir(parents=True, exist_ok=True)
    out_path = _resolve_output_path(runs_dir, date_str)

    lines: list[str] = []
    lines.append(f"# /skill-iterate morning summary -- {date_str}")
    lines.append("")
    if partial:
        # The partial header line is trigger-agnostic: covers kill-switch,
        # exception, and finally-path stops. Caller passes ended_at as the
        # stop-detection time.
        lines.append(f"(partial -- stopped at {ended_at})")
        lines.append("")

    lines.extend(_render_per_skill_table(skill_results))
    lines.append("")
    lines.extend(_render_top_keeps(skill_results))
    lines.append("")

    excluded = _render_excluded_section(skipped_by_skip_list, skipped_by_cross_night)
    if excluded:
        lines.extend(excluded)
        lines.append("")

    lines.extend(
        _render_run_metadata(
            started_at=started_at,
            ended_at=ended_at,
            skill_results=skill_results,
            skipped_by_skip_list=skipped_by_skip_list,
            skipped_by_cross_night=skipped_by_cross_night,
        )
    )
    lines.append("")  # trailing newline

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _skill_result_from_dict(d: dict) -> SkillResult:
    """Build a SkillResult from a JSON-decoded dict.

    Tolerates missing optional fields (top_keep_descriptions, parked_issue_url).
    Raises KeyError if a required field is missing.
    """
    return SkillResult(
        skill=d["skill"],
        baseline_score=d.get("baseline_score"),
        final_score=d.get("final_score"),
        delta=d.get("delta"),
        iterations_run=int(d.get("iterations_run", 0)),
        wall_seconds_total=float(d.get("wall_seconds_total", 0.0)),
        ship_status=d["ship_status"],
        top_keep_descriptions=list(d.get("top_keep_descriptions") or []),
        parked_issue_url=d.get("parked_issue_url"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="morning_summary.py",
        description=(
            "Write a /skill-iterate morning summary markdown file.\n"
            "Reads a JSON payload (file or stdin) describing the run and emits\n"
            "<runs_dir>/<date_str>.md (auto-disambiguated b/c/d if it exists)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "runs_dir",
        type=Path,
        help="absolute path to docs/skill-iterate-runs/",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="path to JSON payload (see schema below); '-' or omit for stdin",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="YYYY-MM-DD; defaults to today UTC",
    )
    parser.add_argument(
        "--partial",
        action="store_true",
        help="add a partial-summary header line (kill-switch hit)",
    )
    parser.add_argument(
        "--started-at",
        type=str,
        default=None,
        help="ISO8601 start time; defaults to now UTC",
    )
    parser.add_argument(
        "--ended-at",
        type=str,
        default=None,
        help="ISO8601 end time; defaults to now UTC",
    )

    args = parser.parse_args(argv)

    # Load the JSON payload: skill_results list + optional excluded lists.
    # Schema:
    #   {
    #     "skill_results": [ {skill, baseline_score, final_score, delta, iterations_run,
    #                         wall_seconds_total, ship_status,
    #                         top_keep_descriptions, parked_issue_url}, ... ],
    #     "skipped_by_skip_list": [skill_name, ...],
    #     "skipped_by_cross_night": [{"skill": ..., "mtime_iso": ...}, ...]
    #   }
    if args.input is None or str(args.input) == "-":
        payload_raw = sys.stdin.read()
    else:
        if not args.input.is_file():
            print(f"error: --input file not found: {args.input}", file=sys.stderr)
            return 3
        payload_raw = args.input.read_text(encoding="utf-8")

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON payload: {exc}", file=sys.stderr)
        return 1

    try:
        skill_results = [
            _skill_result_from_dict(d) for d in payload.get("skill_results", [])
        ]
    except (KeyError, TypeError, ValueError) as exc:
        print(f"error: malformed skill_results: {exc}", file=sys.stderr)
        return 1

    skipped_by_skip_list = payload.get("skipped_by_skip_list") or None
    skipped_by_cross_night = payload.get("skipped_by_cross_night") or None

    # Validate ship_status values before writing - fail loudly on bad input.
    for r in skill_results:
        if r.ship_status not in VALID_SHIP_STATUSES:
            print(
                f"error: invalid ship_status {r.ship_status!r} for skill {r.skill!r}; "
                f"must be one of {sorted(VALID_SHIP_STATUSES)}",
                file=sys.stderr,
            )
            return 1

    started_at = args.started_at or _now_iso8601_utc()
    ended_at = args.ended_at or _now_iso8601_utc()

    try:
        out_path = write_morning_summary(
            runs_dir=args.runs_dir,
            skill_results=skill_results,
            started_at=started_at,
            ended_at=ended_at,
            date_str=args.date,
            partial=args.partial,
            skipped_by_skip_list=skipped_by_skip_list,
            skipped_by_cross_night=skipped_by_cross_night,
        )
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
