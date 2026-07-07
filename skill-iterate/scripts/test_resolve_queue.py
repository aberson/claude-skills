"""Tests for resolve_queue.py — the /skill-iterate Phase 1 --project-rebased
queue resolver."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import resolve_queue as rq


def _make_skill(project: Path, name: str, *, scenarios: bool = True, results_mtime: float | None = None) -> None:
    evals_dir = project / ".claude" / "skills" / name / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)
    (evals_dir / "evals.json").write_text("{}", encoding="utf-8")
    if scenarios:
        (evals_dir / "test_scenarios.json").write_text("{}", encoding="utf-8")
    if results_mtime is not None:
        tsv = evals_dir / "results.tsv"
        tsv.write_text("commit\tscore\tstatus\tdescription\twall_seconds\n", encoding="utf-8")
        import os

        os.utime(tsv, (results_mtime, results_mtime))


def test_discovery_basic(tmp_path: Path) -> None:
    _make_skill(tmp_path, "target-retro")
    _make_skill(tmp_path, "package-uat")
    res = rq.resolve(tmp_path, now=1_000_000.0)
    assert res["queue"] == ["package-uat", "target-retro"]  # alphabetical
    assert res["excluded_skip_list"] == []
    assert res["excluded_fresh"] == []


def test_half_bootstrapped_dropped(tmp_path: Path) -> None:
    _make_skill(tmp_path, "good-skill")
    _make_skill(tmp_path, "half-skill", scenarios=False)
    res = rq.resolve(tmp_path, now=1_000_000.0)
    assert res["queue"] == ["good-skill"]
    assert res["excluded_half_bootstrapped"] == ["half-skill"]


def test_embedded_skip_list_excluded(tmp_path: Path) -> None:
    _make_skill(tmp_path, "verify")  # embedded skip-list member
    _make_skill(tmp_path, "target-retro")
    res = rq.resolve(tmp_path, now=1_000_000.0)
    assert res["queue"] == ["target-retro"]
    assert res["excluded_skip_list"] == [{"skill": "verify", "reason": "embedded"}]


def test_skip_list_extension(tmp_path: Path) -> None:
    _make_skill(tmp_path, "improve-bot")
    _make_skill(tmp_path, "target-retro")
    res = rq.resolve(tmp_path, skip_list_extension=frozenset({"improve-bot"}), now=1_000_000.0)
    assert res["queue"] == ["target-retro"]
    assert res["excluded_skip_list"] == [{"skill": "improve-bot", "reason": "--skip-list extension"}]


def test_cross_night_freshness_filter(tmp_path: Path) -> None:
    now = 1_000_000.0
    # fresh: ran 1h ago -> excluded; stale: ran 25h ago -> eligible
    _make_skill(tmp_path, "fresh-skill", results_mtime=now - 3600)
    _make_skill(tmp_path, "stale-skill", results_mtime=now - 25 * 3600)
    res = rq.resolve(tmp_path, now=now)
    assert res["queue"] == ["stale-skill"]
    assert [e["skill"] for e in res["excluded_fresh"]] == ["fresh-skill"]


def test_freshness_cliff_boundary(tmp_path: Path) -> None:
    now = 1_000_000.0
    # exactly 24h -> NOT within window (strict <), so eligible
    _make_skill(tmp_path, "edge-skill", results_mtime=now - 24 * 3600)
    res = rq.resolve(tmp_path, now=now)
    assert res["queue"] == ["edge-skill"]


def test_explicit_skill_overrides_discovery(tmp_path: Path) -> None:
    _make_skill(tmp_path, "a-skill")
    _make_skill(tmp_path, "b-skill")
    res = rq.resolve(tmp_path, explicit_skill="b-skill", now=1_000_000.0)
    assert res["queue"] == ["b-skill"]


def test_missing_skills_root(tmp_path: Path) -> None:
    res = rq.resolve(tmp_path, now=1_000_000.0)
    assert res["queue"] == []
    assert res["excluded_half_bootstrapped"] == []


def test_project_rebasing_independent_trees(tmp_path: Path) -> None:
    proj_a = tmp_path / "Alpha4Gate"
    proj_b = tmp_path / "void_furnace"
    _make_skill(proj_a, "improve-bot-triage")
    _make_skill(proj_b, "target-retro")
    res_a = rq.resolve(proj_a, now=1_000_000.0)
    res_b = rq.resolve(proj_b, now=1_000_000.0)
    assert res_a["queue"] == ["improve-bot-triage"]
    assert res_b["queue"] == ["target-retro"]
    # each project sees ONLY its own skills
    assert "target-retro" not in res_a["queue"]
    assert "improve-bot-triage" not in res_b["queue"]


def test_queue_file_parsing(tmp_path: Path) -> None:
    qf = tmp_path / "queue.txt"
    qf.write_text(
        "# a comment line\n"
        "  target-retro   # inline comment\n"
        "\n"
        "package-uat\n",
        encoding="utf-8",
    )
    assert rq._parse_queue_file(qf) == ["target-retro", "package-uat"]


def test_dry_run_text_shape(tmp_path: Path) -> None:
    _make_skill(tmp_path, "target-retro")
    _make_skill(tmp_path, "verify")
    res = rq.resolve(tmp_path, now=1_000_000.0)
    text = rq.format_dry_run(res)
    assert "Resolved queue (1 skill):" in text
    assert "target-retro -> ~/worktree_skill-iterate-target-retro-<epoch>" in text
    assert "budget=1h iterations=12" in text
    assert "verify  (skip-list: embedded)" in text


def test_cli_json_output(tmp_path: Path) -> None:
    _make_skill(tmp_path, "target-retro")
    out = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "resolve_queue.py"),
         "--project", str(tmp_path), "--now", "1000000"],
        capture_output=True, text=True, check=True,
    )
    parsed = json.loads(out.stdout)
    assert parsed["queue"] == ["target-retro"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
