#!/usr/bin/env python3
"""M2 per-skill /skill-iterate launcher (script-driven overnight mode).

Spawns `claude -p` per skill in serial so each per-skill /skill-iterate
invocation gets a fresh context window. Each spawn takes-and-releases the
.skill-iterate.lock cleanly, satisfying the concurrent-run contract.

This is the recommended execution mode for M2 fleet observation per the
2026-05-27 M2-halt findings (docs/skill-iterate-runs/2026-05-27.md):
single Claude Code interactive sessions burn context too quickly across
N skills; per-skill fresh-context spawns let the harness scale.

Usage:
    python m2_launcher.py [--queue <file>] [--budget 2h] [--iters 5]
                          [--skip-list "a,b,c"] [--dry-run]

If --queue is omitted, auto-discovers scorable skills via
`.claude/skills/*/evals/evals.json` + `test_scenarios.json` and applies
the same skip-list + 24h cross-night-resume filter that /skill-iterate's
Phase 1 uses.

Outputs:
    docs/skill-iterate-runs/m2-launcher-<date>/
        <skill>.log       - claude -p stdout/stderr for the skill
        <skill>.exit-code - subprocess exit code
        _summary.md       - manifest of all spawns + their status

After completion, operator can run /skill-iterate's morning_summary.py
manually if needed (this launcher does not auto-invoke it because each
spawn already wrote its own per-skill results.tsv).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Per-skill /skill-iterate's embedded skip-list (side-effect skills).
EMBEDDED_SKIP_LIST = {
    "verify", "run", "loop", "schedule", "update-config",
    "fewer-permission-prompts", "claude-oauth-auth",
}

CROSS_NIGHT_WINDOW_SECONDS = 24 * 3600  # 24h


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M2 per-skill /skill-iterate launcher")
    p.add_argument(
        "--queue", type=Path, default=None,
        help="Path to a queue file (one skill name per line). Omit to auto-discover.",
    )
    p.add_argument(
        "--budget", default="2h",
        help="--per-skill-budget passed to each /skill-iterate (default: 2h).",
    )
    p.add_argument(
        "--iters", type=int, default=5,
        help="--per-skill-iterations passed to each /skill-iterate (default: 5).",
    )
    p.add_argument(
        "--skip-list", default="",
        help="Extra skip-list (comma-separated) extending the embedded list.",
    )
    p.add_argument(
        "--workspace", type=Path, default=Path("<workspace>"),
        help="Workspace root containing .claude/skills/ (default: <workspace>).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Resolve queue and print planned commands; do not spawn anything.",
    )
    # Workflow bridges — mutually exclusive with each other and with normal execution.
    wf_group = p.add_mutually_exclusive_group()
    wf_group.add_argument(
        "--export-queue", action="store_true",
        help=(
            "Workflow bridge: resolve the skill queue and emit "
            '{\"queue\": [...], \"excluded\": [...]} as JSON to stdout; do not spawn.'
        ),
    )
    wf_group.add_argument(
        "--write-manifest", nargs=2, metavar=("RESULTS_JSON", "LOGS_DIR"),
        help=(
            "Workflow bridge: read a JSON results array from RESULTS_JSON and write "
            "_summary.md to LOGS_DIR. Results array shape: "
            "[{skill, exit_code, duration_seconds, status, log}]."
        ),
    )
    return p.parse_args()


def resolve_queue(
    workspace: Path,
    queue_file: Path | None,
    user_skip_list: set[str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (queue, excluded). Mirrors /skill-iterate Phase 1 logic."""
    merged_skip = EMBEDDED_SKIP_LIST | user_skip_list
    skills_dir = workspace / ".claude" / "skills"

    if queue_file:
        candidates = []
        for line in queue_file.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                candidates.append(line)
    else:
        candidates = sorted(
            ej.parent.parent.name
            for ej in skills_dir.glob("*/evals/evals.json")
            if (ej.parent / "test_scenarios.json").exists()
        )

    excluded: list[tuple[str, str]] = []
    after_skip = []
    for c in candidates:
        if c in merged_skip:
            excluded.append((c, "skip-list"))
        else:
            after_skip.append(c)

    now = time.time()
    queue = []
    for c in after_skip:
        rt = skills_dir / c / "evals" / "results.tsv"
        if rt.exists():
            age = now - rt.stat().st_mtime
            if age < CROSS_NIGHT_WINDOW_SECONDS:
                excluded.append((c, f"24h-fresh ({age / 3600:.1f}h)"))
                continue
        queue.append(c)
    return queue, excluded


def spawn_skill_iterate(
    skill: str, budget: str, iters: int, log_path: Path,
) -> int:
    """Spawn `claude -p` for one /skill-iterate invocation. Returns exit code."""
    prompt = (
        f"/skill-iterate --skill {skill} "
        f"--per-skill-iterations {iters} "
        f"--per-skill-budget {budget}"
    )
    cmd = ["claude", "-p", prompt]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"# m2-launcher spawn for /{skill}\n")
        log.write(f"# started: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n")
        log.write(f"# cmd: {' '.join(cmd)}\n")
        log.write("# " + "-" * 60 + "\n\n")
        log.flush()
        try:
            result = subprocess.run(
                cmd, stdout=log, stderr=subprocess.STDOUT,
                check=False, encoding="utf-8",
            )
            return result.returncode
        except FileNotFoundError:
            log.write("\n# ERROR: claude executable not on PATH\n")
            return 127
        except KeyboardInterrupt:
            log.write("\n# INTERRUPTED by operator (Ctrl+C)\n")
            raise


def write_summary(manifest: list[dict], logs_dir: Path, date: str | None = None) -> Path:
    """Write _summary.md to logs_dir from a list of result dicts and return the path.

    Each result dict must have: skill, exit_code (int|None), duration_seconds (float),
    status (str), log (str). This is the Workflow bridge counterpart to the inline summary
    write in main() — extracted so --write-manifest and the normal run share one writer.
    """
    if date is None:
        date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    logs_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    summary_path = logs_dir / "_summary.md"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(f"# M2 launcher run -- {date}\n\n")
        f.write(f"- written: {started_at}\n")
        f.write(f"- attempted: {len(manifest)}\n\n")
        f.write("| # | skill | status | duration (s) | log |\n")
        f.write("|---|---|---|---|---|\n")
        for i, m in enumerate(manifest, 1):
            f.write(
                f"| {i} | `{m['skill']}` | {m['status']} | "
                f"{m['duration_seconds']:.0f} | `{m['log']}` |\n"
            )
    return summary_path


def main() -> int:
    args = parse_args()
    user_skip = {s.strip() for s in args.skip_list.split(",") if s.strip()}

    # Workflow bridge: --export-queue emits JSON without spawning anything.
    if args.export_queue:
        queue, excluded = resolve_queue(args.workspace, args.queue, user_skip)
        payload = {
            "queue": queue,
            "excluded": [{"skill": s, "reason": r} for s, r in excluded],
        }
        print(json.dumps(payload))
        return 0

    # Workflow bridge: --write-manifest reads results JSON and writes _summary.md.
    if args.write_manifest:
        results_json_path = Path(args.write_manifest[0])
        logs_dir = Path(args.write_manifest[1])
        try:
            manifest = json.loads(results_json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"--write-manifest: cannot read {results_json_path}: {exc}", file=sys.stderr)
            return 1
        if not isinstance(manifest, list):
            print(
                f"--write-manifest: expected JSON array, got {type(manifest).__name__}",
                file=sys.stderr,
            )
            return 1
        summary_path = write_summary(manifest, logs_dir)
        print(f"Manifest written: {summary_path}")
        return 0

    queue, excluded = resolve_queue(args.workspace, args.queue, user_skip)

    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    logs_dir = args.workspace / "docs" / "skill-iterate-runs" / f"m2-launcher-{date}"

    print(f"M2 per-skill launcher")
    print(f"  workspace: {args.workspace}")
    print(f"  budget per skill: {args.budget}")
    print(f"  iter cap per skill: {args.iters}")
    print(f"  logs: {logs_dir}")
    print()
    print(f"Resolved queue ({len(queue)} skill{'s' if len(queue) != 1 else ''}):")
    for s in queue:
        print(f"  {s}")
    if excluded:
        print()
        print(f"Excluded ({len(excluded)}):")
        for s, reason in excluded:
            print(f"  {s}  ({reason})")
    print()

    if not queue:
        print("Queue empty -- nothing to launch.")
        return 0

    if args.dry_run:
        print("--dry-run: not spawning. Planned commands:")
        for s in queue:
            print(
                f"  claude -p '/skill-iterate --skill {s} "
                f"--per-skill-iterations {args.iters} "
                f"--per-skill-budget {args.budget}'"
            )
        return 0

    logs_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"Starting {len(queue)}-skill serial launch at {started_at}")
    print()

    for i, skill in enumerate(queue, 1):
        print(f"[{i}/{len(queue)}] {skill} ...", flush=True)
        skill_started = time.time()
        log_path = logs_dir / f"{skill}.log"
        try:
            exit_code = spawn_skill_iterate(skill, args.budget, args.iters, log_path)
        except KeyboardInterrupt:
            print(f"  INTERRUPTED at {skill}")
            manifest.append({
                "skill": skill, "exit_code": None, "duration_seconds": time.time() - skill_started,
                "log": str(log_path), "status": "interrupted",
            })
            break
        elapsed = time.time() - skill_started
        status = "ok" if exit_code == 0 else f"nonzero-exit ({exit_code})"
        (logs_dir / f"{skill}.exit-code").write_text(str(exit_code), encoding="utf-8")
        manifest.append({
            "skill": skill, "exit_code": exit_code, "duration_seconds": elapsed,
            "log": str(log_path), "status": status,
        })
        print(f"  -> {status}  ({elapsed:.0f}s)")

    summary_path = write_summary(manifest, logs_dir, date)
    print()
    print(f"Manifest: {summary_path}")
    print(f"Per-skill logs: {logs_dir}")
    print()
    print("Each spawn wrote its own .claude/skills/<skill>/evals/results.tsv (gitignored).")
    print("Run a fresh /skill-iterate-style morning-summary pass over those if desired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
