"""Deterministic queue resolver for /skill-iterate Phase 1 discovery.

Resolves which skills under a project's ``.claude/skills/`` tree are eligible
for hill-climb iteration, applying the embedded skip-list, any operator
``--skip-list`` extension, and the 24h cross-night-resume freshness filter.

This script is the concrete, unit-testable implementation of the discovery
prose in ``skill-iterate/SKILL.md`` Phase 1, parameterized by ``--project`` so
the same loop can iterate skills living in ANY git repo (the dev/ workspace,
Alpha4Gate, void_furnace, ...) rather than only the workspace root the skill
is invoked from. Path resolution is rebased onto ``--project``; the scoring /
append / summary helper scripts continue to run from their canonical home
under ``<dev>/.claude/skills/`` regardless of ``--project``.

CLI:
    python resolve_queue.py --project <path>
        [--skill <name>]            # explicit single skill (overrides discovery)
        [--queue <path>]            # explicit queue file (overrides discovery)
        [--skip-list <csv>]         # EXTENDS the embedded skip-list
        [--freshness-hours <float>] # cross-night-resume window (default 24)
        [--now <epoch-seconds>]     # override "now" for deterministic tests
        [--dry-run]                 # emit the human-readable plan instead of JSON

Default output is machine-consumable JSON on stdout:

    {
      "project": "<abs path>",
      "queue": ["skill-a", "skill-b"],
      "excluded_skip_list": [{"skill": "verify", "reason": "embedded"}],
      "excluded_fresh": [{"skill": "fix-bug", "mtime_iso": "..."}],
      "excluded_half_bootstrapped": ["partial-skill"]
    }

``--dry-run`` emits the Phase 1 plan text (resolved queue + per-skill worktree
paths + budget + exclusions) and exits 0 without touching any lock file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Embedded skip-list — side-effect-driven skills whose output is not
# text-gradable in a fresh-context Claude session. MUST stay in sync with
# skill-iterate/SKILL.md § Embedded skip-list. Operators EXTEND (never shrink)
# this via --skip-list.
EMBEDDED_SKIP_LIST: frozenset[str] = frozenset(
    {
        "verify",
        "run",
        "loop",
        "schedule",
        "update-config",
        "fewer-permission-prompts",
        "claude-oauth-auth",
    }
)

DEFAULT_FRESHNESS_HOURS: float = 24.0
WORKTREE_PARENT: str = "~"  # worktree_skill-iterate-<skill>-<epoch> lives here


def _skills_root(project: Path) -> Path:
    return project / ".claude" / "skills"


def discover_candidates(project: Path) -> tuple[list[str], list[str]]:
    """Return (fully_bootstrapped, half_bootstrapped) skill-name lists.

    A candidate is any ``<skills_root>/<name>/evals/evals.json``. It is fully
    bootstrapped only when the sibling ``test_scenarios.json`` also exists;
    half-bootstrapped candidates are dropped from the queue (surfaced
    separately for observability, matching the SKILL.md "dropped SILENTLY"
    contract — the caller decides whether to log them).
    """
    skills_root = _skills_root(project)
    full: list[str] = []
    half: list[str] = []
    if not skills_root.is_dir():
        return full, half
    for evals in sorted(skills_root.glob("*/evals/evals.json")):
        name = evals.parent.parent.name
        if (evals.parent / "test_scenarios.json").is_file():
            full.append(name)
        else:
            half.append(name)
    return full, half


def _results_mtime(project: Path, name: str) -> float | None:
    p = _skills_root(project) / name / "evals" / "results.tsv"
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return None


def resolve(
    project: Path,
    *,
    explicit_skill: str | None = None,
    explicit_queue: list[str] | None = None,
    skip_list_extension: frozenset[str] | None = None,
    freshness_hours: float = DEFAULT_FRESHNESS_HOURS,
    now: float | None = None,
) -> dict:
    """Resolve the ordered queue + exclusion sets for a project.

    Mirrors SKILL.md Phase 1: discovery (or explicit list) -> skip-list filter
    -> 24h cross-night-resume filter -> alphabetical order.
    """
    project = project.resolve()
    now = time.time() if now is None else now
    merged_skip = EMBEDDED_SKIP_LIST | (skip_list_extension or frozenset())

    excluded_half: list[str] = []
    if explicit_skill is not None:
        candidates = [explicit_skill]
    elif explicit_queue is not None:
        candidates = list(explicit_queue)
    else:
        candidates, excluded_half = discover_candidates(project)

    excluded_skip: list[dict] = []
    excluded_fresh: list[dict] = []
    queue: list[str] = []

    for name in candidates:
        if name in merged_skip:
            reason = "embedded" if name in EMBEDDED_SKIP_LIST else "--skip-list extension"
            excluded_skip.append({"skill": name, "reason": reason})
            continue
        mtime = _results_mtime(project, name)
        if mtime is not None and (now - mtime) < freshness_hours * 3600:
            excluded_fresh.append(
                {
                    "skill": name,
                    "mtime_iso": datetime.fromtimestamp(mtime, timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
            continue
        queue.append(name)

    queue.sort()  # alphabetical, deterministic
    return {
        "project": str(project),
        "queue": queue,
        "excluded_skip_list": excluded_skip,
        "excluded_fresh": excluded_fresh,
        "excluded_half_bootstrapped": sorted(excluded_half),
    }


def format_dry_run(result: dict, *, per_skill_budget: str = "1h", iterations: int = 12) -> str:
    """Render the Phase 1 --dry-run plan text from a resolve() result."""
    q = result["queue"]
    lines: list[str] = []
    lines.append(f"Resolved queue ({len(q)} skill{'s' if len(q) != 1 else ''}):")
    for name in q:
        lines.append(f"  {name}")
    lines.append("")
    lines.append("Per-skill worktrees:")
    for name in q:
        lines.append(f"  {name} -> {WORKTREE_PARENT}/worktree_skill-iterate-{name}-<epoch>")
    lines.append("")
    lines.append("Per-skill budget:")
    lines.append(f"  budget={per_skill_budget} iterations={iterations}")
    lines.append("")
    lines.append("Excluded by skip-list:")
    for e in result["excluded_skip_list"]:
        lines.append(f"  {e['skill']}  (skip-list: {e['reason']})")
    lines.append("")
    lines.append("Excluded by cross-night-resume filter:")
    for e in result["excluded_fresh"]:
        lines.append(f"  {e['skill']}  (results.tsv mtime: {e['mtime_iso']})")
    if result["excluded_half_bootstrapped"]:
        lines.append("")
        lines.append("Excluded (half-bootstrapped, missing test_scenarios.json):")
        for name in result["excluded_half_bootstrapped"]:
            lines.append(f"  {name}")
    return "\n".join(lines)


def _parse_queue_file(path: Path) -> list[str]:
    """Parse a --queue file per SKILL.md Phase 0: strip, drop blanks/#comments,
    honor inline # comments."""
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Resolve the /skill-iterate Phase 1 queue.")
    ap.add_argument("--project", default=".", help="Project root whose .claude/skills/ tree to scan.")
    ap.add_argument("--skill", default=None, help="Explicit single skill (overrides discovery).")
    ap.add_argument("--queue", default=None, help="Explicit queue file (overrides discovery).")
    ap.add_argument("--skip-list", default="", help="Comma-separated names that EXTEND the embedded skip-list.")
    ap.add_argument("--freshness-hours", type=float, default=DEFAULT_FRESHNESS_HOURS)
    ap.add_argument("--now", type=float, default=None, help="Override now() epoch-seconds (tests).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    ext = frozenset(s.strip() for s in args.skip_list.split(",") if s.strip())
    explicit_queue = None
    if args.queue:
        explicit_queue = _parse_queue_file(Path(args.queue))

    result = resolve(
        Path(args.project),
        explicit_skill=args.skill,
        explicit_queue=explicit_queue,
        skip_list_extension=ext,
        freshness_hours=args.freshness_hours,
        now=args.now,
    )

    if args.dry_run:
        print(format_dry_run(result))
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
