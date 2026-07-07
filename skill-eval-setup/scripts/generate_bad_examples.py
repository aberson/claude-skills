"""Golden bad-example generation for `/skill-iterate` corpora.

Produces one ``bad_<defect-slug>.md`` file per discrimination assertion in a
skill's ``evals/evals.json``, together with a single ``good.md`` (auto-generated
from the target skill on a canonical scenario, OR copied from a hand-crafted
source if one exists) and a ``manifest.json`` index. The output directory is
``<skill-dir>/evals/golden/``.

The script's only LLM couplings are the ``dispatch_generator`` and
``score_bad_against_evals`` seams — every other function is pure and
unit-testable. Tests inject fakes for both seams so the suite runs offline.

CLI:
    python generate_bad_examples.py <skill-name>
    python generate_bad_examples.py --skill <skill-name> [--dry-run]
    python generate_bad_examples.py --fleet [--batch-size N]
    python generate_bad_examples.py --verify-only <skill-name>

JSON summary is written to stdout (machine-consumed by orchestrators);
human-readable progress is written to stderr.

Step 9 adds the verification gate: each generated bad is scored against the
current grader; if the grader fails to distinguish bad-from-good, the bad is
regenerated (up to ``max_regen_attempts`` total tries); if the grader still
passes it after the final attempt, the bad is marked INERT in the manifest
(file is still written for operator inspection).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

# --- Constants ----------------------------------------------------------------

# Defect-type values that mark "not a real discrimination assertion" — sanity
# checks (valid JSON, sequential ids) and aggregate coverage assertions are
# excluded from bad-example generation per investigation file 02 procedure §1.
NON_DISCRIMINATION_DEFECT_TYPES: frozenset[str] = frozenset(
    {
        "n/a-sanity",
        "n/a-coverage",
    }
)

SLUG_MAX_LEN: int = 60
DEFAULT_FLEET_BATCH_SIZE: int = 3

# Maximum total dispatch attempts per bad assertion (1 initial + retries).
# Per investigation file 03 § How to apply, the regenerate-vs-mark-inert
# choice is the per-skill calibration trade-off; 3 is the documented default.
DEFAULT_MAX_REGEN_ATTEMPTS: int = 3

# Manifest schema version. Step 8 shipped placeholder fields (``verified_fails:
# null``, ``regen_attempts: 0``) — that was effectively v1. Step 9 populates
# real values and adds ``verification_summary`` + ``manifest_version`` keys.
MANIFEST_SCHEMA_VERSION: int = 2

# Workspace layout: <workspace>/.claude/skills/<skill-name>/scripts/<file.py>.
# This file lives at .claude/skills/skill-eval-setup/scripts/generate_bad_examples.py,
# so parents[2] is .claude/skills/ (the skills root). Resolve directly from
# __file__ rather than going via a workspace-root intermediary; the latter is
# easy to get off-by-one with (the prior pattern computed `.claude/.claude/skills`
# and auto_discover_skills silently returned []).
_SKILLS_ROOT: Path = Path(__file__).resolve().parents[2]


# --- I/O helpers -------------------------------------------------------------


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically (write-temp + os.replace).

    An interrupt (Ctrl-C, OOM, power loss) mid-``write_text`` can leave the
    target file truncated/corrupt — particularly load-bearing for
    ``manifest.json`` since downstream tooling (``/skill-iterate``,
    operator audit scripts) parses it as JSON and a partial file is harder
    to diagnose than a missing one.

    Strategy: write to ``<path>.tmp`` first, then ``os.replace`` it onto the
    target. ``os.replace`` is atomic on both POSIX (rename(2)) and Windows
    (MoveFileEx with REPLACE_EXISTING) for same-volume writes — which the
    manifest always is, since the temp file is in the same directory.
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding=encoding)
    os.replace(tmp_path, path)


# --- Pure helpers -------------------------------------------------------------


def derive_slug(defect_type: str) -> str:
    """Slugify a ``defect_type`` string for use in ``bad_<slug>.md``.

    Rule (documented in SKILL.md Step 5):
      1. lowercase
      2. replace any run of non-alphanumeric characters with a single ``_``
      3. strip leading/trailing ``_``
      4. truncate at :data:`SLUG_MAX_LEN` (60) characters

    Examples:
        "structural — missing required output part"
            -> "structural_missing_required_output_part"
        "anti-pattern — explicit-rule violation"
            -> "anti_pattern_explicit_rule_violation"
        ""                              -> ""
        "!!!"                           -> ""
        "already_clean"                 -> "already_clean"

    Pure / no I/O. Importable in isolation for unit tests.
    """
    if not isinstance(defect_type, str):
        defect_type = str(defect_type)
    lower = defect_type.lower()
    collapsed = re.sub(r"[^a-z0-9]+", "_", lower)
    stripped = collapsed.strip("_")
    return stripped[:SLUG_MAX_LEN]


def load_evals(skill_dir: Path) -> dict[str, Any]:
    """Read ``<skill_dir>/evals/evals.json`` and return the parsed dict.

    Raises ``FileNotFoundError`` with the resolved path if the file is missing.
    Raises ``json.JSONDecodeError`` (unchanged) if the file is malformed.
    """
    path = skill_dir / "evals" / "evals.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"evals.json not found at {path}; expected <skill-dir>/evals/evals.json"
        )
    # utf-8-sig tolerates a stray BOM (Win PS 5.1 Set-Content -Encoding utf8).
    return json.loads(path.read_text(encoding="utf-8-sig"))


def extract_discrimination_assertions(evals: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the list of discrimination assertions from a parsed evals.json.

    Walks every ``categories[*].evals[*]`` entry and keeps those whose
    ``defect_type`` is NOT in :data:`NON_DISCRIMINATION_DEFECT_TYPES`. Each
    returned dict is the assertion verbatim plus a ``_category`` key naming the
    category it came from (purely for debugging / manifest provenance).

    Tolerant of:
      - missing ``categories`` key       -> []
      - missing ``defect_type`` field    -> treated as discrimination (safer
        default — a missing tag is more likely a real assertion than an n/a).
      - non-list ``categories`` value    -> []
    """
    categories = evals.get("categories")
    if not isinstance(categories, list):
        return []

    out: list[dict[str, Any]] = []
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        cat_name = cat.get("name", "")
        cat_evals = cat.get("evals")
        if not isinstance(cat_evals, list):
            continue
        for assertion in cat_evals:
            if not isinstance(assertion, dict):
                continue
            defect_type = assertion.get("defect_type", "")
            if defect_type in NON_DISCRIMINATION_DEFECT_TYPES:
                continue
            enriched = dict(assertion)
            enriched["_category"] = cat_name
            out.append(enriched)
    return out


def build_generator_prompt(
    assertion: dict[str, Any],
    good_md: str,
    skill_md: str,
    *,
    subtlety: str = "subtle",
) -> str:
    """Assemble the sub-agent prompt for one bad-example generation.

    Inputs per Step 5 contract:
      (a) assertion text + defect_type
      (b) the good.md content
      (c) the target SKILL.md content
      (d) an instruction to produce a minimal bad.md violating exactly that
          defect_type, preferably a single-line diff against good.md.

    The ``subtlety`` parameter (``"subtle"`` | ``"obvious"``) tunes the
    diff-size instruction; per investigation file 11 the default is ``"subtle"``
    because LLMs default to obvious-bad. Operators can request obvious-tier
    variants for sanity-check anchors.
    """
    statement = assertion.get("statement", "<no statement field>")
    defect_type = assertion.get("defect_type", "<no defect_type field>")
    source = assertion.get("source", "<no source field>")
    assertion_id = assertion.get("id", "<no id>")

    if subtlety == "obvious":
        subtle_clause = (
            "Make the violation OBVIOUS — delete or negate the relevant content "
            "outright. This is a sanity-check anchor that any competent grader "
            "must catch; do not try to disguise the defect."
        )
    else:
        subtle_clause = (
            "Stay in the subtle zone — preserve surface plausibility, violate only "
            "the underlying rule. Prefer a single-line diff against good.md. A "
            "sycophantic grader doing a substring or paraphrase-tolerant check "
            "should still mistakenly pass this output; only a strict assertion "
            "tied to the named defect_type should catch it."
        )

    return f"""\
You are generating one BAD example for a golden corpus used to evaluate a skill.

# Defect to plant
- assertion_id: {assertion_id}
- defect_type: {defect_type}
- assertion statement: {statement}
- source citation: {source}

# Task
Modify the GOOD output below into a BAD output that violates EXACTLY the named
defect_type. Every OTHER rule in the SKILL.md must remain satisfied — the only
defect a grader should be able to find is the one named above.

{subtle_clause}

Prepend an HTML comment header to your output naming the defect and the SKILL.md
line range it violates. Example shape:

    <!-- BAD OUTPUT — DEFECT: <one-line defect summary> -->
    <!-- Violates SKILL.md lines <N-M>: "<quoted rule fragment>" -->

# GOOD output (reference — modify minimally)
{good_md}

# Target SKILL.md (rules to satisfy except for the planted defect)
{skill_md}

Respond with ONLY the bad.md content (HTML comment header + body). No surrounding
prose, no JSON envelope, no explanation outside the file content.
"""


# --- Sub-agent dispatch seam --------------------------------------------------


def dispatch_generator(prompt: str) -> str:
    """Production sub-agent dispatcher. Returns the generated bad.md content.

    NOT WIRED in Step 8 — raises ``NotImplementedError`` so callers that forget
    to inject ``dispatch_fn`` get a loud error instead of silently writing
    empty bad files. Step 9's verification gate is the first real consumer; the
    wiring lives in ``_shared/score-skill.md`` alongside the differential
    grader's dispatcher.

    Tests inject a fake via the ``dispatch_fn`` parameter of
    :func:`generate_for_skill` / :func:`generate_fleet`.
    """
    raise NotImplementedError(
        "generate_bad_examples sub-agent dispatch not yet wired; "
        "supply dispatch_fn= when calling generate_for_skill/generate_fleet"
    )


# --- Verification gate (Step 9) ----------------------------------------------

# Default score_fn for the verification gate. Wired at module load against the
# composite scoring procedure from ``_shared/score_skill_composite.py``. If
# that import fails (transient sys.path issue, missing sibling skill, etc.) we
# install a loud stub so tests / callers that forget to inject ``score_fn``
# get a clear ImportError-shaped failure rather than a silent pass.

try:
    # The composite scorer lives in a sibling skill directory; add it to
    # sys.path the same way the test harness does.
    _COMPOSITE_DIR = Path(__file__).resolve().parents[2] / "_shared"
    if str(_COMPOSITE_DIR) not in sys.path:
        sys.path.insert(0, str(_COMPOSITE_DIR))
    from score_skill_composite import score_composite as _composite_score  # type: ignore

    _COMPOSITE_IMPORT_ERROR: Exception | None = None
except Exception as _exc:  # noqa: BLE001 - any import failure → install stub
    _composite_score = None  # type: ignore[assignment]
    _COMPOSITE_IMPORT_ERROR = _exc


def _default_score_fn(
    bad_md: str, good_md: str, skill_md: str, evals: dict[str, Any]
) -> tuple[float, float]:
    """Default scoring callable wired to the composite scoring procedure.

    Returns ``(good_score, bad_score)``. Raises an ImportError-shaped
    exception if the composite scorer is unavailable (callers that need to
    run the gate offline must inject their own ``score_fn``).

    The composite scorer's natural input is two SKILL.md paths, not raw
    bad/good content strings. For the bad-example verification gate, the
    convention is: ``good_score`` represents the grader's verdict on the
    well-formed reference and ``bad_score`` represents its verdict on the
    planted-defect output. The orchestrator-LLM is expected to dispatch the
    composite scorer with appropriate fixture paths and inject the resulting
    pair here. In Step 9 (no production LLM wiring), this default raises so
    test-only callers must inject a deterministic ``score_fn``.
    """
    if _composite_score is None:
        raise ImportError(
            "score_skill_composite not importable from "
            f"{_COMPOSITE_DIR}; cannot run verification gate without an "
            f"injected score_fn. Original error: {_COMPOSITE_IMPORT_ERROR!r}"
        )
    raise NotImplementedError(
        "score_bad_against_evals default score_fn requires an orchestrator-"
        "LLM-supplied dispatcher that maps (bad_md, good_md, skill_md, evals)"
        " to a (good_score, bad_score) pair. Inject score_fn= explicitly."
    )


def score_bad_against_evals(
    bad_md: str,
    good_md: str,
    skill_md: str,
    evals: dict[str, Any],
    score_fn: Callable[[str, str, str, dict[str, Any]], tuple[float, float]]
    | None = None,
) -> dict[str, Any]:
    """Score one bad example against the current grader.

    Returns a dict with three keys:

    - ``verdict``: ``"fails"`` (bad scored strictly LOWER than good — grader
      correctly distinguishes them; gate accepts), ``"passes"`` (bad scored
      EQUAL OR HIGHER than good — grader did NOT distinguish; gate rejects,
      regenerate), or ``"indeterminate"`` (grader threw an exception or
      returned an invalid shape — treated as ``"passes"`` for safety).
    - ``score``: float, the bad's grader score (NaN if indeterminate).
    - ``good_score``: float, the good's grader score (NaN if indeterminate).

    ``score_fn`` is the injectable scoring callable. Default delegates to
    :func:`_default_score_fn` which uses the composite scoring procedure from
    ``_shared/score_skill_composite.py``. Tests inject deterministic stubs.

    Pure modulo the ``score_fn`` call. No file I/O. The grader call is
    wrapped in a broad try/except — any exception (ImportError,
    NotImplementedError, ValueError, programmer bug in the injected fn) is
    treated as indeterminate. The contract is "safety first": an unverifiable
    bad is treated as not-yet-verified-as-failing, so the caller will
    regenerate.
    """
    fn = score_fn if score_fn is not None else _default_score_fn
    try:
        result = fn(bad_md, good_md, skill_md, evals)
    except Exception:  # noqa: BLE001 - any failure → indeterminate
        return {
            "verdict": "indeterminate",
            "score": float("nan"),
            "good_score": float("nan"),
        }
    # Validate return shape: must be a 2-tuple of (good, bad) floats.
    if (
        not isinstance(result, tuple)
        or len(result) != 2
        or not all(isinstance(x, (int, float)) for x in result)
    ):
        return {
            "verdict": "indeterminate",
            "score": float("nan"),
            "good_score": float("nan"),
        }
    good_score, bad_score = float(result[0]), float(result[1])
    # Accept criterion: bad scores STRICTLY LOWER than good. Ties count as
    # passes (the grader didn't distinguish) per the §How to apply contract.
    if bad_score < good_score:
        verdict = "fails"
    else:
        verdict = "passes"
    return {
        "verdict": verdict,
        "score": bad_score,
        "good_score": good_score,
    }


def build_retry_prompt(original_prompt: str, attempt: int) -> str:
    """Append a subtler-directive suffix to a generator prompt for retries.

    ``attempt`` is the 1-indexed attempt number AFTER the first failure. So
    ``attempt=2`` is the second total dispatch (first retry), ``attempt=3``
    is the third (and by default final) dispatch.

    Returns a new prompt string containing the original prompt and an
    appended directive instructing the sub-agent to make the planted defect
    MORE subtle. Importable in isolation for unit tests.
    """
    if attempt <= 1:
        # No retry pressure on the first attempt; return as-is so callers can
        # use this helper uniformly inside a loop.
        return original_prompt
    if attempt == 2:
        suffix = (
            "\n\n# Retry directive (attempt 2 of N)\n"
            "Previous attempt was too obvious — the grader caught the defect "
            "easily. Try a SUBTLER defect: keep more of the good structure "
            "intact, violate the rule in a way that requires careful reading "
            "to spot. Single-line diff against good.md preferred.\n"
        )
    else:
        # attempt >= 3
        suffix = (
            f"\n\n# Retry directive (attempt {attempt} of N)\n"
            "Previous attempts were still too obvious — the grader keeps "
            "catching the defect. This is the FINAL retry; if you cannot "
            "produce a subtler bad example that still violates exactly the "
            "named defect_type, the example will be marked INERT and shipped "
            "for operator inspection. Make this attempt MORE SUBTLE than the "
            "last: preserve as much of good.md as possible, plant the defect "
            "in a way a paraphrase-tolerant grader would miss but a strict "
            "assertion would still catch.\n"
        )
    return original_prompt + suffix


# --- Skill discovery + filesystem helpers ------------------------------------


def auto_discover_skills(skills_root: Path | None = None) -> list[str]:
    """Return sorted list of skill names that have ``evals/evals.json`` present.

    Skips entries under ``_*`` (shared fragments like ``_shared/``). Returns an
    empty list if ``skills_root`` does not exist (callers handle gracefully).

    Pure-ish: only reads the directory tree, never writes.
    """
    root = skills_root if skills_root is not None else _SKILLS_ROOT
    if not root.is_dir():
        return []
    names: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):
            continue
        if (entry / "evals" / "evals.json").is_file():
            names.append(entry.name)
    return sorted(names)


def _resolve_skill_dir(skill_name: str, skills_root: Path | None = None) -> Path:
    """Resolve ``<skills_root>/<skill_name>/`` and verify it is a directory.

    Rejects ``skill_name`` values that escape ``skills_root`` via parent-dir
    components (``../foo``, ``foo/../../bar``) or absolute paths. This is a
    defense in depth — CLI callers shouldn't be able to coax the script into
    reading or writing outside the configured skills tree.
    """
    root = skills_root if skills_root is not None else _SKILLS_ROOT
    skill_dir = root / skill_name
    resolved_root = root.resolve()
    resolved_skill = skill_dir.resolve()
    # is_relative_to (Py 3.9+) cleanly rejects ../, absolute paths, and any
    # other traversal that ends up outside the skills root.
    if not resolved_skill.is_relative_to(resolved_root):
        raise ValueError(
            f"skill_name {skill_name!r} escapes skills_root "
            f"({resolved_root}); refusing to traverse outside the skills tree"
        )
    # The traversal check also rejects the root itself (resolved_skill ==
    # resolved_root, which IS relative-to). Guard against the empty / "." case
    # so we don't accidentally treat the skills root as a skill dir.
    if resolved_skill == resolved_root:
        raise ValueError(
            f"skill_name {skill_name!r} resolves to the skills root itself"
        )
    if not skill_dir.is_dir():
        raise FileNotFoundError(
            f"skill directory not found: {skill_dir} "
            "(check skill name and that skills_root is correct)"
        )
    return skill_dir


def _read_good_md(skill_dir: Path) -> tuple[str, str]:
    """Return ``(good_md_content, source_marker)``.

    Source-marker contract for the manifest:
      - ``"hand-crafted"``  if ``<skill_dir>/evals/golden/good.md`` already exists
      - ``"auto-generated"`` otherwise (Step 8 placeholder — Step 9's verification
        gate will run the target skill on a canonical scenario; for now we write
        a stub good.md so the generator prompt always has reference material).

    The stub good.md content is explicit about being a placeholder so any human
    reading the corpus before Step 9 lands knows what's going on.
    """
    existing = skill_dir / "evals" / "golden" / "good.md"
    if existing.is_file():
        return existing.read_text(encoding="utf-8-sig"), "hand-crafted"
    stub = (
        "<!-- GOOD OUTPUT — auto-generated placeholder (Step 8 of SIHC plan) -->\n"
        "<!-- Step 9 will replace this by running the target skill on a canonical scenario. -->\n"
    )
    return stub, "auto-generated"


def _read_skill_md(skill_dir: Path) -> str:
    """Read ``<skill_dir>/SKILL.md`` (utf-8-sig). Empty string if absent."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return ""
    return skill_md.read_text(encoding="utf-8-sig")


def _assign_slugs(
    assertions: Iterable[dict[str, Any]],
) -> list[tuple[dict[str, Any], str]]:
    """Pair each assertion with a unique slug.

    When two assertions share a ``defect_type`` (and therefore the same raw
    slug), the second gets ``_2`` appended, the third ``_3``, etc. Empty slugs
    (defect_type unset / all-punctuation) get a placeholder ``unnamed`` slug
    plus the numeric suffix scheme.
    """
    seen: dict[str, int] = {}
    out: list[tuple[dict[str, Any], str]] = []
    for assertion in assertions:
        raw = derive_slug(assertion.get("defect_type", "")) or "unnamed"
        seen[raw] = seen.get(raw, 0) + 1
        suffix = "" if seen[raw] == 1 else f"_{seen[raw]}"
        # Respect SLUG_MAX_LEN even after suffixing — trim base before append.
        base = raw[: SLUG_MAX_LEN - len(suffix)] if suffix else raw
        out.append((assertion, f"{base}{suffix}"))
    return out


# --- Per-skill orchestration --------------------------------------------------


def generate_for_skill(
    skill_name: str,
    *,
    dispatch_fn: Callable[[str], str] = dispatch_generator,
    score_fn: Callable[[str, str, str, dict[str, Any]], tuple[float, float]]
    | None = None,
    skills_root: Path | None = None,
    dry_run: bool = False,
    subtlety: str = "subtle",
    max_regen_attempts: int = DEFAULT_MAX_REGEN_ATTEMPTS,
    verify_only: bool = False,
    now: Callable[[], _dt.datetime] | None = None,
) -> dict[str, Any]:
    """Generate the golden corpus (good.md + bad_*.md + manifest.json) for one skill.

    Returns a summary dict suitable for JSON serialization:
        {
          "skill": "<name>",
          "skill_dir": "<absolute path>",
          "golden_dir": "<absolute path>",
          "good_source": "hand-crafted" | "auto-generated",
          "assertions": <int>,
          "bads": [{"file": ..., "defect_type": ..., "assertion_id": ...,
                    "verified_fails": <bool>, "regen_attempts": <int>}, ...],
          "verification_summary": {"accepted": N, "inert": M, "total": N+M},
          "manifest_version": 2,
          "dry_run": <bool>,
        }

    When ``dry_run=True``, no files are written; the summary still reports the
    planned filenames so an operator can preview the run. The verification
    gate is skipped in dry-run mode (it would require dispatching the
    generator, which dry-run forbids).

    When ``verify_only=True``, no new bads are generated; the existing
    ``bad_*.md`` files in the golden directory are re-scored against the
    current grader and the manifest's ``verified_fails`` / ``regen_attempts``
    fields are updated in place. ``dispatch_fn`` is NEVER called in this
    mode. Useful after a grader change to re-classify the existing corpus
    without burning sub-agent dispatches.

    ``max_regen_attempts`` caps the total dispatches per bad (1 initial +
    up to N-1 retries with progressively-more-subtle prompts). After
    ``max_regen_attempts`` consecutive grader-passes, the bad is marked
    INERT (``verified_fails: false``) but the most recent generated content
    is still written so operators can inspect it.

    ``now`` is injectable for deterministic timestamps in tests.
    """
    if max_regen_attempts < 1:
        raise ValueError(f"max_regen_attempts must be >= 1; got {max_regen_attempts}")

    skill_dir = _resolve_skill_dir(skill_name, skills_root=skills_root)
    evals = load_evals(skill_dir)
    assertions = extract_discrimination_assertions(evals)
    skill_md = _read_skill_md(skill_dir)
    good_md, good_source = _read_good_md(skill_dir)
    slugged = _assign_slugs(assertions)

    golden_dir = skill_dir / "evals" / "golden"
    bad_records: list[dict[str, Any]] = []

    # --- verify-only branch: re-score existing bads, no dispatch -----------
    if verify_only:
        if not golden_dir.is_dir():
            raise FileNotFoundError(
                f"verify_only=True but golden dir does not exist: {golden_dir}"
            )
        return _verify_existing_corpus(
            skill_name=skill_name,
            skill_dir=skill_dir,
            golden_dir=golden_dir,
            assertions=assertions,
            slugged=slugged,
            good_md=good_md,
            good_source=good_source,
            skill_md=skill_md,
            evals=evals,
            score_fn=score_fn,
            now=now,
        )

    # --- normal generate path -----------------------------------------------
    if not dry_run:
        golden_dir.mkdir(parents=True, exist_ok=True)
        # Always write good.md (placeholder or copy) so the directory is
        # self-contained even on first generation.
        (golden_dir / "good.md").write_text(good_md, encoding="utf-8")

    for assertion, slug in slugged:
        filename = f"bad_{slug}.md"
        record: dict[str, Any] = {
            "file": filename,
            "defect_type": assertion.get("defect_type"),
            "assertion_id": assertion.get("id"),
            "verified_fails": None,
            "regen_attempts": 0,
        }
        if not dry_run:
            base_prompt = build_generator_prompt(
                assertion, good_md, skill_md, subtlety=subtlety
            )
            content, verified_fails, attempts_used = _generate_with_gate(
                base_prompt=base_prompt,
                good_md=good_md,
                skill_md=skill_md,
                evals=evals,
                dispatch_fn=dispatch_fn,
                score_fn=score_fn,
                max_regen_attempts=max_regen_attempts,
            )
            (golden_dir / filename).write_text(content, encoding="utf-8")
            record["verified_fails"] = verified_fails
            record["regen_attempts"] = attempts_used
        else:
            # Dry-run reports the planned shape but cannot verify (no dispatch).
            record["verified_fails"] = None
            record["regen_attempts"] = 0
        bad_records.append(record)

    verification_summary = _compute_verification_summary(bad_records)

    # Timezone-aware UTC; strftime drops tzinfo so we keep the trailing "Z"
    # without doubling it. utcnow() is deprecated in Py 3.12+.
    _now_default = lambda: _dt.datetime.now(_dt.timezone.utc)  # noqa: E731
    timestamp = (now or _now_default)().strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "skill": skill_name,
        "generated_at": timestamp,
        "good_source": good_source,
        "verification_summary": verification_summary,
        "bads": bad_records,
    }
    if not dry_run:
        _atomic_write_text(
            golden_dir / "manifest.json",
            json.dumps(manifest, indent=2) + "\n",
        )

    return {
        "skill": skill_name,
        "skill_dir": str(skill_dir),
        "golden_dir": str(golden_dir),
        "good_source": good_source,
        "assertions": len(assertions),
        "bads": bad_records,
        "verification_summary": verification_summary,
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "dry_run": dry_run,
    }


# --- Gate orchestration helpers ----------------------------------------------


def _generate_with_gate(
    *,
    base_prompt: str,
    good_md: str,
    skill_md: str,
    evals: dict[str, Any],
    dispatch_fn: Callable[[str], str],
    score_fn: Callable[[str, str, str, dict[str, Any]], tuple[float, float]] | None,
    max_regen_attempts: int,
) -> tuple[str, bool, int]:
    """Run the dispatch + verify loop for one bad assertion.

    Returns ``(final_content, verified_fails, attempts_used)``.

    Loop semantics:
      - attempt 1: dispatch the base prompt, score the result.
      - if verdict == "fails" (bad strictly lower than good), accept and
        return immediately with verified_fails=True.
      - if verdict == "passes" or "indeterminate", re-dispatch with a
        subtler prompt up to ``max_regen_attempts`` total tries.
      - if all attempts pass, return the LAST generated content with
        verified_fails=False (INERT marker).

    The most-recent content is always returned — even on INERT the operator
    can inspect what the generator produced.
    """
    last_content: str = ""
    for attempt in range(1, max_regen_attempts + 1):
        prompt = build_retry_prompt(base_prompt, attempt)
        last_content = dispatch_fn(prompt)
        verdict_info = score_bad_against_evals(
            last_content, good_md, skill_md, evals, score_fn=score_fn
        )
        if verdict_info["verdict"] == "fails":
            return last_content, True, attempt
    # All attempts exhausted; bad is INERT.
    return last_content, False, max_regen_attempts


def _verify_existing_corpus(
    *,
    skill_name: str,
    skill_dir: Path,
    golden_dir: Path,
    assertions: list[dict[str, Any]],
    slugged: list[tuple[dict[str, Any], str]],
    good_md: str,
    good_source: str,
    skill_md: str,
    evals: dict[str, Any],
    score_fn: Callable[[str, str, str, dict[str, Any]], tuple[float, float]] | None,
    now: Callable[[], _dt.datetime] | None,
) -> dict[str, Any]:
    """Re-verify an existing on-disk corpus without dispatching the generator.

    For each ``bad_<slug>.md`` derived from the current evals.json:
      - if the file exists on disk, read it and re-score against the grader;
        update ``verified_fails`` based on the verdict.
      - if the file does NOT exist on disk, record verified_fails=False
        (cannot verify what isn't there) — operator should run a normal
        generation to backfill.

    ``regen_attempts`` is preserved from the prior manifest when available,
    otherwise defaults to 1 (the file exists, so at least one dispatch
    happened historically). The manifest is rewritten with updated
    verified_fails values and a fresh ``generated_at`` timestamp.
    """
    # Try to read prior manifest for regen_attempts preservation.
    prior_manifest: dict[str, Any] = {}
    manifest_path = golden_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            prior_manifest = {}
    prior_by_file: dict[str, dict[str, Any]] = {}
    for entry in prior_manifest.get("bads", []) or []:
        if isinstance(entry, dict) and "file" in entry:
            prior_by_file[entry["file"]] = entry

    bad_records: list[dict[str, Any]] = []
    for assertion, slug in slugged:
        filename = f"bad_{slug}.md"
        bad_path = golden_dir / filename
        prior_attempts = prior_by_file.get(filename, {}).get("regen_attempts")
        attempts_used = (
            prior_attempts
            if isinstance(prior_attempts, int) and prior_attempts >= 1
            else 1
        )
        if bad_path.is_file():
            bad_content = bad_path.read_text(encoding="utf-8-sig")
            verdict_info = score_bad_against_evals(
                bad_content, good_md, skill_md, evals, score_fn=score_fn
            )
            verified_fails = verdict_info["verdict"] == "fails"
        else:
            # Missing on disk — cannot verify; mark INERT and surface via
            # regen_attempts=0 so operator can spot the gap.
            verified_fails = False
            attempts_used = 0
        bad_records.append(
            {
                "file": filename,
                "defect_type": assertion.get("defect_type"),
                "assertion_id": assertion.get("id"),
                "verified_fails": verified_fails,
                "regen_attempts": attempts_used,
            }
        )

    verification_summary = _compute_verification_summary(bad_records)
    _now_default = lambda: _dt.datetime.now(_dt.timezone.utc)  # noqa: E731
    timestamp = (now or _now_default)().strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "skill": skill_name,
        "generated_at": timestamp,
        "good_source": good_source,
        "verification_summary": verification_summary,
        "bads": bad_records,
    }
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")

    return {
        "skill": skill_name,
        "skill_dir": str(skill_dir),
        "golden_dir": str(golden_dir),
        "good_source": good_source,
        "assertions": len(assertions),
        "bads": bad_records,
        "verification_summary": verification_summary,
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "dry_run": False,
        "verify_only": True,
    }


def _compute_verification_summary(
    bad_records: list[dict[str, Any]],
) -> dict[str, int]:
    """Tally accepted vs inert across the manifest's bad entries.

    ``accepted``: count of entries with ``verified_fails == True``.
    ``inert``: count of entries with ``verified_fails == False``.
    Entries with ``verified_fails is None`` (dry-run placeholders) are NOT
    counted in either bucket; ``total`` is ``accepted + inert``.
    """
    accepted = sum(1 for r in bad_records if r.get("verified_fails") is True)
    inert = sum(1 for r in bad_records if r.get("verified_fails") is False)
    return {"accepted": accepted, "inert": inert, "total": accepted + inert}


# --- Fleet orchestration ------------------------------------------------------


def generate_fleet(
    *,
    dispatch_fn: Callable[[str], str] = dispatch_generator,
    score_fn: Callable[[str, str, str, dict[str, Any]], tuple[float, float]]
    | None = None,
    batch_size: int = DEFAULT_FLEET_BATCH_SIZE,
    skills_root: Path | None = None,
    dry_run: bool = False,
    subtlety: str = "subtle",
    max_regen_attempts: int = DEFAULT_MAX_REGEN_ATTEMPTS,
    verify_only: bool = False,
    now: Callable[[], _dt.datetime] | None = None,
) -> dict[str, Any]:
    """Regenerate every auto-discovered scorable skill in parallel batches.

    Uses :class:`concurrent.futures.ThreadPoolExecutor` with ``max_workers =
    batch_size`` so at most that many sub-agent dispatches run concurrently.
    Per-skill failures are captured in the result (``"error"`` field) rather
    than raised — one broken skill must not abort fleet regeneration.
    """
    skills = auto_discover_skills(skills_root=skills_root)
    per_skill: list[dict[str, Any]] = []

    def _one(name: str) -> dict[str, Any]:
        try:
            return generate_for_skill(
                name,
                dispatch_fn=dispatch_fn,
                score_fn=score_fn,
                skills_root=skills_root,
                dry_run=dry_run,
                subtlety=subtlety,
                max_regen_attempts=max_regen_attempts,
                verify_only=verify_only,
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 - intentionally broad for fleet resilience
            return {
                "skill": name,
                "error": f"{type(exc).__name__}: {exc}",
            }

    if not skills:
        return {
            "fleet": True,
            "skills_processed": 0,
            "batch_size": batch_size,
            "results": [],
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
        futures = [pool.submit(_one, name) for name in skills]
        for fut in concurrent.futures.as_completed(futures):
            per_skill.append(fut.result())

    # Sort for stable JSON output (futures complete in arbitrary order).
    per_skill.sort(key=lambda r: r.get("skill", ""))
    return {
        "fleet": True,
        "skills_processed": len(per_skill),
        "batch_size": batch_size,
        "results": per_skill,
    }


# --- CLI ----------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_bad_examples.py",
        description=(
            "Generate the golden bad-example corpus for one skill or for every "
            "auto-discovered scorable skill. Outputs JSON summary to stdout; "
            "human-readable progress to stderr."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "skill_name_positional",
        nargs="?",
        default=None,
        metavar="<skill-name>",
        help="Skill name (e.g. session-wrap). Alternative to --skill.",
    )
    parser.add_argument(
        "--skill",
        dest="skill_name_flag",
        default=None,
        help="Skill name. Same as the positional argument; provided for explicit-flag callers.",
    )
    parser.add_argument(
        "--fleet",
        action="store_true",
        help="Regenerate every auto-discovered scorable skill in parallel batches.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_FLEET_BATCH_SIZE,
        help=f"Fleet batch size (default: {DEFAULT_FLEET_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing any files or dispatching sub-agents.",
    )
    parser.add_argument(
        "--subtlety",
        choices=("subtle", "obvious"),
        default="subtle",
        help="Bad-example difficulty tier (default: subtle).",
    )
    parser.add_argument(
        "--max-regen-attempts",
        type=int,
        default=DEFAULT_MAX_REGEN_ATTEMPTS,
        help=(
            f"Verification-gate retry cap (default: {DEFAULT_MAX_REGEN_ATTEMPTS}). "
            "1 initial dispatch + up to N-1 retries; after N consecutive "
            "grader-passes the bad is marked INERT in the manifest."
        ),
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help=(
            "Re-score existing on-disk bads against the current grader "
            "WITHOUT regenerating. Useful after a grader change. The "
            "manifest's verified_fails fields are updated in place; "
            "dispatch_fn is never called in this mode."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)

    skill_name = args.skill_name_flag or args.skill_name_positional

    if args.fleet and skill_name:
        print(
            "error: --fleet and <skill-name> are mutually exclusive",
            file=sys.stderr,
        )
        return 2
    if not args.fleet and not skill_name:
        parser.print_usage(sys.stderr)
        print(
            "error: provide <skill-name> (or --skill <name>) or use --fleet",
            file=sys.stderr,
        )
        return 2

    # In dry-run we still must not invoke the production stub, since it raises.
    # generate_for_skill / generate_fleet skip dispatch when dry_run=True, so
    # the default dispatch_fn is safe there.
    #
    # Operator footgun guard: the CLI never injects a score_fn (composite
    # scoring is wired in Step 12 of the SIHC plan). Outside --dry-run and
    # --verify-only, that means every generated bad will burn
    # max_regen_attempts dispatches and then be marked INERT. Warn loudly so
    # operators don't silently waste LLM tokens between Steps 9 and 12.
    if not args.dry_run and not args.verify_only:
        print(
            "warning: no score_fn wired and not in --dry-run or --verify-only mode.\n"
            "Every generated bad will be marked INERT after max_regen_attempts dispatches.\n"
            "This is expected between Steps 9 and 12 (composite scoring is wired in Step 12).\n"
            "To suppress: pass --dry-run for a preview or --verify-only to re-score existing bads.",
            file=sys.stderr,
        )

    try:
        if args.fleet:
            print(
                f"[generate_bad_examples] fleet mode, batch_size={args.batch_size}, "
                f"dry_run={args.dry_run}, verify_only={args.verify_only}, "
                f"max_regen_attempts={args.max_regen_attempts}",
                file=sys.stderr,
            )
            result = generate_fleet(
                batch_size=args.batch_size,
                dry_run=args.dry_run,
                subtlety=args.subtlety,
                max_regen_attempts=args.max_regen_attempts,
                verify_only=args.verify_only,
            )
            print(
                f"[generate_bad_examples] processed {result['skills_processed']} skills",
                file=sys.stderr,
            )
        else:
            print(
                f"[generate_bad_examples] skill={skill_name}, dry_run={args.dry_run}, "
                f"verify_only={args.verify_only}, "
                f"max_regen_attempts={args.max_regen_attempts}",
                file=sys.stderr,
            )
            result = generate_for_skill(
                skill_name,
                dry_run=args.dry_run,
                subtlety=args.subtlety,
                max_regen_attempts=args.max_regen_attempts,
                verify_only=args.verify_only,
            )
            print(
                f"[generate_bad_examples] {len(result['bads'])} bad files "
                f"planned/written for {skill_name}",
                file=sys.stderr,
            )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except NotImplementedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except json.JSONDecodeError as exc:
        print(f"error: malformed evals.json: {exc}", file=sys.stderr)
        return 5
    except ValueError as exc:
        # _resolve_skill_dir raises ValueError on path-traversal attempts.
        print(f"error: {exc}", file=sys.stderr)
        return 6

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
