"""Deterministic structural-metric scoring over a SKILL.md path.

Computes 8 lint-style structural metrics (defined in skill-iterate-hill-climbing-plan
section 5 and investigation file 08) and emits a composite score in [0.0, 1.0]
together with per-metric detail. The score is fully reproducible across re-runs and
is immune to LLM grader variance, so it serves as a deterministic backbone alongside
the differential grader (Step 4) and composite scoring (Step 5).

CLI:
    python structural_metrics.py <skill-md-path> [--max-line-length N]

The CLI prints a JSON document of the shape:
    {
      "score": <float in [0, 1]>,
      "metrics": {
        "section_depth_consistency": {"score": ..., ...},
        "required_sections": {...},
        "banned_phrases": {...},
        "link_integrity": {...},
        "code_fence_balance": {...},
        "max_line_length": {...},
        "cross_reference_resolution": {...},
        "rules_to_rationale_ratio": {...}
      }
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

# --- Defaults -----------------------------------------------------------------

DEFAULT_REQUIRED_SECTIONS: tuple[str, ...] = ("Steps", "Constraints", "Limitations")
DEFAULT_BANNED_PHRASES: tuple[str, ...] = ("as an AI", "I think", "I cannot")
DEFAULT_MAX_LINE_LENGTH: int = 150
SHOULD_OVERUSE_THRESHOLD: int = 10  # >this many "should" occurrences = soft signal
IMPERATIVE_TARGET_RATIO: float = 0.4  # tent function peaks here

IMPERATIVE_VERBS: frozenset[str] = frozenset({
    "Use", "Write", "Run", "Avoid", "Add", "Remove", "Do", "Don't", "Dont",
    "Check", "Verify", "Set", "Read", "Call", "Create", "Delete", "Update",
    "Replace", "Prefer", "Ensure", "Always", "Never", "Skip", "Apply",
    "Edit", "Open", "Close", "Save", "Commit", "Push", "Pull", "Fetch",
    "Build", "Test", "Confirm", "Document", "Note", "Pass", "Return",
    "Stop", "Start", "Halt", "Continue", "Mark", "Tag", "Pin", "Default",
})

# Markdown link with relative-path target: [text](path). Excludes URLs.
_RELATIVE_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
# Headings: ^# / ## / ### / ####
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# Wiki-style cross-reference: [[slug]]
_CROSSREF_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
# Code fence opener: ``` optionally followed by language tag.
# CommonMark: a fence indented 4+ spaces is part of an indented code block, NOT
# a fence — so cap the leading-whitespace capture at 3.
_FENCE_RE = re.compile(r"^(\s{0,3})(`{3,})(\s*)(\S*)?\s*$")


# --- Helpers ------------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    """Return text with content inside triple-backtick fences removed.

    Used for metrics that should not count occurrences inside fenced code blocks
    (e.g. banned phrases, imperative-verb counts, line-length checks live in their
    own metric). Fence markers themselves are preserved as blank lines so line
    numbers stay aligned for downstream callers if they care.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def _is_external_url(target: str) -> bool:
    """Return True if the link target is an http(s) URL or mailto."""
    lower = target.strip().lower()
    return lower.startswith(("http://", "https://", "mailto:", "ftp://"))


def _is_anchor_only(target: str) -> bool:
    """Return True if the link target is anchor-only (e.g. '#section')."""
    return target.strip().startswith("#")


# --- Per-metric implementations ----------------------------------------------


def metric_section_depth_consistency(text: str) -> dict[str, Any]:
    """No H4 (####) immediately under H2 (##) without an intervening H3.

    Per plan §5 + investigation 08: ONLY H2→H4 (skipping H3) is a violation.
    H1→H4 jumps are legitimate (common in concise SKILL.md files) and H4 under
    H3 is fine. We track the nearest preceding ancestor heading; if it's H2,
    flag the H4 as a depth violation. H1/H5/H6 do not reset the H2/H3 context.

    A pure violation count is normalized via 1 / (1 + violations) so the metric
    degrades gracefully as more violations accumulate.
    """
    violations: list[str] = []
    last_h2_or_h3: int = 0  # depth of last H2/H3 seen (0 = none yet)
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if not m:
            continue
        depth = len(m.group(1))
        title = m.group(2)
        if depth == 2:
            last_h2_or_h3 = 2
        elif depth == 3:
            last_h2_or_h3 = 3
        elif depth == 4:
            # Strict: only H2→H4 (skipping H3) is a violation. H1→H4 and
            # H4 with no prior H2/H3 (e.g. under H1 or at top of file) are
            # NOT violations — the prior implementation over-flagged these.
            if last_h2_or_h3 == 2:
                violations.append(f"H4 under H2: {title!r}")
        # H1/H5/H6 don't change the H2/H3 context
    score = 1.0 / (1.0 + len(violations))
    return {
        "score": score,
        "violations": len(violations),
        "detail": violations,
    }


def _normalize_section_name(name: str) -> str:
    """Lowercase + strip trailing punctuation so ``## Steps:`` matches ``Steps``."""
    return name.strip().rstrip(":.?!").lower()


def metric_required_sections(
    text: str,
    required: list[str],
    *,
    from_config: bool = False,
) -> dict[str, Any]:
    """Each required section name must appear as a heading anywhere in the doc.

    Score = fraction present. Matching is case-insensitive and tolerant of
    trailing punctuation (so ``## steps`` and ``## Steps:`` both match ``Steps``).

    Neutral-default behavior: when ``from_config`` is False (no
    ``evals/required_sections.json`` was supplied) AND none of the defaults
    appear in the doc, return score=1.0 with a ``no_config`` marker. This
    metric should only penalize skills that explicitly opted in via a config
    file, OR happen to use the default names.

    If ``required`` is empty, score = 1.0.
    """
    if not required:
        return {"score": 1.0, "present": [], "missing": [], "required": []}

    headings: set[str] = set()
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            headings.add(_normalize_section_name(m.group(2)))

    present: list[str] = []
    missing: list[str] = []
    for s in required:
        if _normalize_section_name(s) in headings:
            present.append(s)
        else:
            missing.append(s)

    # Neutral default: skill didn't opt in via config AND uses none of the
    # default section names — don't drag its composite down.
    if not from_config and not present:
        return {
            "score": 1.0,
            "present": [],
            "missing": list(missing),
            "required": list(required),
            "no_config": True,
        }

    score = len(present) / len(required)
    return {
        "score": score,
        "present": present,
        "missing": missing,
        "required": list(required),
    }


def metric_banned_phrases(text: str, banned: list[str]) -> dict[str, Any]:
    """Count occurrences of banned phrases (case-insensitive) + 'should' overuse.

    Score = 1 / (1 + total_hits) so 0 hits = 1.0 and it degrades smoothly.
    'should' overuse counts as 1 hit if count > SHOULD_OVERUSE_THRESHOLD; the
    actual count is reported in the detail.
    """
    body = _strip_code_fences(text)
    lower = body.lower()

    per_phrase: dict[str, int] = {}
    total_phrase_hits = 0
    for phrase in banned:
        n = lower.count(phrase.lower())
        per_phrase[phrase] = n
        total_phrase_hits += n

    # Count 'should' as a whole word in the body (excluding fenced code).
    should_count = len(re.findall(r"\bshould\b", body, flags=re.IGNORECASE))
    should_hit = 1 if should_count > SHOULD_OVERUSE_THRESHOLD else 0

    total_hits = total_phrase_hits + should_hit
    score = 1.0 / (1.0 + total_hits)
    return {
        "score": score,
        "total_hits": total_hits,
        "per_phrase": per_phrase,
        "should_count": should_count,
        "should_overuse_threshold": SHOULD_OVERUSE_THRESHOLD,
    }


def metric_link_integrity(text: str, skill_md_path: Path) -> dict[str, Any]:
    """Every relative-path markdown link resolves to an existing file.

    Skips http(s)/mailto/ftp URLs and anchor-only fragments. If a link target
    has its own anchor (path#anchor), only the path portion is checked.

    Score = valid / total. If no relative links exist, score = 1.0.
    """
    base = skill_md_path.parent
    matches = _RELATIVE_LINK_RE.findall(text)

    total = 0
    valid = 0
    broken: list[str] = []
    for _label, target in matches:
        target = target.strip()
        if not target:
            continue
        if _is_external_url(target) or _is_anchor_only(target):
            continue
        # Strip ?query and #fragment for filesystem resolution.
        path_part = target.split("#", 1)[0].split("?", 1)[0]
        if not path_part:
            continue
        # URL-decode so `[doc](my%20file.md)` resolves against `my file.md`.
        path_part = unquote(path_part)
        total += 1
        # Resolve relative to the SKILL.md's directory.
        candidate = (base / path_part).resolve()
        if candidate.exists():
            valid += 1
        else:
            broken.append(target)

    if total == 0:
        score = 1.0
    else:
        score = valid / total
    return {
        "score": score,
        "total_relative_links": total,
        "valid": valid,
        "broken": broken,
    }


def metric_code_fence_balance(text: str) -> dict[str, Any]:
    """Every ``` opens and closes; opening fences should have a language tag.

    Score = 1 - (unbalanced_count + missing_tag_count) / max(1, total_open_fences).
    `unbalanced_count` is 1 if the document ends mid-fence, else 0.

    A single unclosed fence with no language tag is one issue, not two — so
    we only count ``missing_language_tag`` for openers that were eventually
    closed. The trailing unclosed opener contributes via ``unbalanced`` only.
    """
    total_open = 0
    missing_tag = 0
    in_fence = False
    # Track whether the current open fence had a language tag so we only
    # charge missing-tag for openers we observe being closed.
    pending_missing_tag = False
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if not m:
            continue
        if not in_fence:
            total_open += 1
            lang = (m.group(4) or "").strip()
            pending_missing_tag = not lang
            in_fence = True
        else:
            # Closing this opener — only now do we record a missing-tag issue
            # against it (so unclosed openers don't double-count).
            if pending_missing_tag:
                missing_tag += 1
            pending_missing_tag = False
            in_fence = False
    unbalanced = 1 if in_fence else 0

    denom = max(1, total_open)
    score = max(0.0, 1.0 - (unbalanced + missing_tag) / denom)
    return {
        "score": score,
        "total_open_fences": total_open,
        "missing_language_tag": missing_tag,
        "unbalanced": unbalanced,
    }


def metric_max_line_length(text: str, max_len: int) -> dict[str, Any]:
    """Score = 1 - overlong / total. Empty file scores 1.0.

    Counts every line in the source verbatim (including code-fence content;
    overlong code lines are a real readability hit).
    """
    lines = text.splitlines() or [""]
    overlong_lines: list[int] = []
    for i, line in enumerate(lines, start=1):
        if len(line) > max_len:
            overlong_lines.append(i)
    total = len(lines)
    score = 1.0 - (len(overlong_lines) / total)
    return {
        "score": score,
        "max_length": max_len,
        "total_lines": total,
        "overlong_count": len(overlong_lines),
        "overlong_line_numbers": overlong_lines[:10],  # cap detail size
    }


def metric_cross_reference_resolution(
    text: str, skill_md_path: Path
) -> dict[str, Any]:
    """Every [[slug]] resolves to a sibling skill file OR a workspace memory file.

    Resolution attempts, in order:
      1. <skill_md_path>.parent / <slug>.md  (sibling under skill dir)
      2. <skill_md_path>.parent / <slug>     (sibling without extension)
      3. <workspace>/.../memory/feedback_<slug>.md  (best-effort workspace lookup)

    If no [[slug]] tokens are present at all, score = 1.0 (nothing to break).
    """
    refs = _CROSSREF_RE.findall(text)
    if not refs:
        return {
            "score": 1.0,
            "total_refs": 0,
            "resolved": 0,
            "unresolved": [],
        }

    base = skill_md_path.parent
    # Walk upward accumulating ALL .claude/projects/.../memory dirs from every
    # ancestor — a workspace can have multiple project memory roots, and the
    # first ancestor hit may not contain the slug we're looking for.
    memory_dirs: list[Path] = []
    cursor = base
    for _ in range(8):
        cursor = cursor.parent
        if cursor == cursor.parent:
            break
        candidate = cursor / ".claude" / "projects"
        if candidate.is_dir():
            try:
                for proj in candidate.iterdir():
                    mem = proj / "memory"
                    if mem.is_dir():
                        memory_dirs.append(mem)
            except OSError:
                pass
            # NOTE: don't break — keep walking so a slug only available in a
            # deeper-ancestor memory root still resolves.

    resolved = 0
    unresolved: list[str] = []
    for raw_slug in refs:
        raw_slug = raw_slug.strip()
        # [[file#section]] should look up `file`, not `file#section`. Strip the
        # anchor before resolution so heading-anchor references work.
        slug = raw_slug.split("#", 1)[0].strip()
        if not slug:
            # Anchor-only reference like [[#section]] — treat as resolved
            # (it's an intra-doc anchor, not a cross-ref).
            resolved += 1
            continue
        sibling_md = base / f"{slug}.md"
        sibling_bare = base / slug
        if sibling_md.exists() or sibling_bare.exists():
            resolved += 1
            continue
        # Workspace memory fallback.
        hit = False
        for mem in memory_dirs:
            if (mem / f"feedback_{slug}.md").exists() or (mem / f"{slug}.md").exists():
                hit = True
                break
        if hit:
            resolved += 1
        else:
            unresolved.append(raw_slug)

    score = resolved / len(refs)
    return {
        "score": score,
        "total_refs": len(refs),
        "resolved": resolved,
        "unresolved": unresolved,
    }


def metric_rules_to_rationale_ratio(text: str) -> dict[str, Any]:
    """Imperative-line count / total-non-blank-non-heading-non-list-line count.

    Maps to score via a tent function peaking at IMPERATIVE_TARGET_RATIO (0.4):
        score = 1 - 2 * abs(ratio - 0.4), clamped to [0, 1]

    The tent shape rewards a healthy mix of rules and rationale; pure imperative
    (terse) and pure prose (discursive) both lose. Investigation file 08 calls
    0.4 the empirical sweet spot.
    """
    body = _strip_code_fences(text)
    imperative = 0
    eligible = 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Skip headings and list markers from the denominator since they're
        # neither "rules" nor "rationale" in this sense.
        if line.startswith("#") or line.startswith(("-", "*", "+")) or re.match(r"^\d+\.\s", line):
            continue
        eligible += 1
        first_word = re.match(r"^([A-Za-z']+)\b", line)
        if first_word and first_word.group(1) in IMPERATIVE_VERBS:
            imperative += 1

    if eligible == 0:
        # Degenerate doc (all blank / all headings / all bullets) — neutral score.
        return {
            "score": 1.0,
            "ratio": None,
            "imperative_lines": 0,
            "eligible_lines": 0,
            "target_ratio": IMPERATIVE_TARGET_RATIO,
        }

    ratio = imperative / eligible
    score = max(0.0, min(1.0, 1.0 - 2.0 * abs(ratio - IMPERATIVE_TARGET_RATIO)))
    return {
        "score": score,
        "ratio": ratio,
        "imperative_lines": imperative,
        "eligible_lines": eligible,
        "target_ratio": IMPERATIVE_TARGET_RATIO,
    }


# --- Composite ----------------------------------------------------------------


@dataclass(frozen=True)
class StructuralScore:
    """Composite structural score with per-metric breakdown.

    `score` is the simple arithmetic mean of the 8 per-metric scores. Each
    per-metric entry is a dict with at minimum a "score" key in [0.0, 1.0]
    plus metric-specific detail fields.
    """
    score: float
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)


def _load_required_sections(
    skill_md_path: Path, default: list[str]
) -> tuple[list[str], bool]:
    """Look for <skill_dir>/evals/required_sections.json; fall back to default.

    Returns ``(sections, from_config)`` where ``from_config`` is True iff the
    JSON file existed and parsed successfully. Callers use the flag to apply
    the neutral-default rule in :func:`metric_required_sections`.

    Schema: {"required": ["Section A", "Section B", ...]}
    If the file exists but is malformed, fall back to default (do not crash).
    """
    candidate = skill_md_path.parent / "evals" / "required_sections.json"
    if not candidate.is_file():
        return list(default), False
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
        sections = data.get("required")
        if isinstance(sections, list) and all(isinstance(s, str) for s in sections):
            return sections, True
    except (OSError, json.JSONDecodeError):
        pass
    return list(default), False


def score_skill(
    skill_md_path: Path,
    *,
    required_sections: list[str] | None = None,
    banned_phrases: list[str] | None = None,
    max_line_length: int = DEFAULT_MAX_LINE_LENGTH,
) -> StructuralScore:
    """Run all 8 metrics on the SKILL.md at skill_md_path.

    Returns a StructuralScore with composite = arithmetic mean of per-metric
    scores. Each per-metric dict carries its own "score" key plus detail.

    Reads the file as UTF-8 (and strips an optional BOM via ``utf-8-sig``);
    raises FileNotFoundError if the path does not exist or is not a file.
    """
    if not skill_md_path.is_file():
        raise FileNotFoundError(f"SKILL.md not found or not a file: {skill_md_path}")

    # utf-8-sig strips a leading BOM if present. PowerShell `Set-Content
    # -Encoding utf8` writes a BOM on Win PS 5.1 (see workspace memory
    # feedback_set_content_utf8_adds_bom); without this, a BOM survives as
    # the literal U+FEFF prefix and breaks the heading regex on line 1.
    text = skill_md_path.read_text(encoding="utf-8-sig")
    if required_sections is not None:
        required = required_sections
        from_config = True  # caller explicitly supplied a list
    else:
        required, from_config = _load_required_sections(
            skill_md_path, list(DEFAULT_REQUIRED_SECTIONS)
        )
    banned = (
        list(banned_phrases) if banned_phrases is not None else list(DEFAULT_BANNED_PHRASES)
    )

    metrics: dict[str, dict[str, Any]] = {
        "section_depth_consistency": metric_section_depth_consistency(text),
        "required_sections": metric_required_sections(text, required, from_config=from_config),
        "banned_phrases": metric_banned_phrases(text, banned),
        "link_integrity": metric_link_integrity(text, skill_md_path),
        "code_fence_balance": metric_code_fence_balance(text),
        "max_line_length": metric_max_line_length(text, max_line_length),
        "cross_reference_resolution": metric_cross_reference_resolution(text, skill_md_path),
        "rules_to_rationale_ratio": metric_rules_to_rationale_ratio(text),
    }

    # Simple arithmetic mean of per-metric scores.
    per_metric_scores = [m["score"] for m in metrics.values()]
    composite = sum(per_metric_scores) / len(per_metric_scores)

    return StructuralScore(score=composite, metrics=metrics)


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="structural_metrics.py",
        description=(
            "Score a SKILL.md against 8 deterministic structural metrics. "
            "Emits JSON {\"score\": float, \"metrics\": {<name>: {...}}}."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "skill_md_path",
        type=Path,
        help="Path to the SKILL.md file to score",
    )
    parser.add_argument(
        "--max-line-length",
        type=int,
        default=DEFAULT_MAX_LINE_LENGTH,
        help=f"Max permitted line length (default: {DEFAULT_MAX_LINE_LENGTH})",
    )
    parser.add_argument(
        "--required-section",
        action="append",
        default=None,
        help="Required section name (repeatable). Overrides defaults if any are given.",
    )
    parser.add_argument(
        "--banned-phrase",
        action="append",
        default=None,
        help="Banned phrase (repeatable). Overrides defaults if any are given.",
    )

    args = parser.parse_args(argv)
    try:
        result = score_skill(
            args.skill_md_path,
            required_sections=args.required_section,
            banned_phrases=args.banned_phrase,
            max_line_length=args.max_line_length,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
