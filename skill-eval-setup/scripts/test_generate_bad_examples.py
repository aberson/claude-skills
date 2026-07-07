"""Self-contained unit tests for generate_bad_examples.

Tests run offline — every sub-agent dispatch is mocked via the ``dispatch_fn``
seam. Covers:
  - derive_slug edge cases
  - extract_discrimination_assertions over constructed dicts
  - build_generator_prompt content contract
  - generate_for_skill end-to-end with mocked dispatch (file shapes, manifest,
    duplicate-defect_type suffixing, dry-run behavior)
  - auto_discover_skills against a tempdir skills layout
  - generate_fleet parallel-batch behavior (counter + Lock detect concurrency)
  - CLI smoke via subprocess with --dry-run
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any

# Import under test. Tests live alongside the module in scripts/.
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_bad_examples  # noqa: E402  (import-after-path-mutation is intentional)
from generate_bad_examples import (  # noqa: E402  (import-after-path-mutation is intentional)
    DEFAULT_FLEET_BATCH_SIZE,
    DEFAULT_MAX_REGEN_ATTEMPTS,
    MANIFEST_SCHEMA_VERSION,
    NON_DISCRIMINATION_DEFECT_TYPES,
    SLUG_MAX_LEN,
    _assign_slugs,
    _resolve_skill_dir,
    auto_discover_skills,
    build_generator_prompt,
    build_retry_prompt,
    derive_slug,
    dispatch_generator,
    extract_discrimination_assertions,
    generate_fleet,
    generate_for_skill,
    load_evals,
    main,
    score_bad_against_evals,
)


# --- Step 9 helpers ----------------------------------------------------------


def _always_fails_score_fn(
    bad_md: str, good_md: str, skill_md: str, evals: dict[str, Any]
) -> tuple[float, float]:
    """Score fn that always returns good=0.9, bad=0.3 (bad strictly lower)."""
    return (0.9, 0.3)


def _always_passes_score_fn(
    bad_md: str, good_md: str, skill_md: str, evals: dict[str, Any]
) -> tuple[float, float]:
    """Score fn that always returns good=0.5, bad=0.8 (bad higher = grader misses)."""
    return (0.5, 0.8)


# --- Helpers -----------------------------------------------------------------


def _fake_dispatch(prompt: str) -> str:
    """Deterministic fake dispatcher: returns content that echoes the prompt.

    The returned string is unique per prompt (so different assertions get
    different file contents) but predictable enough to assert on in tests.
    """
    digest = str(abs(hash(prompt)) % 10_000)
    return f"<!-- BAD OUTPUT — DEFECT: fake #{digest} -->\nfake body for prompt with {len(prompt)} chars\n"


def _make_evals(defect_types: list[str]) -> dict[str, Any]:
    """Build a minimal evals.json dict with one assertion per defect_type."""
    return {
        "skill": "test-skill",
        "version": "1.0",
        "passing_threshold": "1/1",
        "categories": [
            {
                "name": "Discrimination",
                "evals": [
                    {
                        "id": i + 1,
                        "statement": f"assertion for {dt}",
                        "source": f"SKILL.md line {10 * (i + 1)}",
                        "defect_type": dt,
                        "result": None,
                    }
                    for i, dt in enumerate(defect_types)
                ],
            }
        ],
    }


def _make_skill_tree(
    skills_root: Path,
    skill_name: str,
    evals: dict[str, Any] | None = None,
    skill_md: str | None = None,
    good_md: str | None = None,
) -> Path:
    """Lay out a synthetic skill dir under ``skills_root``.

    Returns the skill directory path. Writes ``SKILL.md``, ``evals/evals.json``,
    and optionally ``evals/golden/good.md`` to simulate a hand-crafted anchor.
    """
    skill_dir = skills_root / skill_name
    (skill_dir / "evals").mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        skill_md if skill_md is not None else f"# {skill_name}\n\nfake skill body.\n",
        encoding="utf-8",
    )
    if evals is not None:
        (skill_dir / "evals" / "evals.json").write_text(
            json.dumps(evals), encoding="utf-8"
        )
    if good_md is not None:
        (skill_dir / "evals" / "golden").mkdir(parents=True, exist_ok=True)
        (skill_dir / "evals" / "golden" / "good.md").write_text(
            good_md, encoding="utf-8"
        )
    return skill_dir


# --- derive_slug -------------------------------------------------------------


class DeriveSlugTest(unittest.TestCase):
    def test_lowercases(self) -> None:
        self.assertEqual(derive_slug("StructuralMissing"), "structuralmissing")

    def test_collapses_non_alphanumeric_runs_to_single_underscore(self) -> None:
        self.assertEqual(
            derive_slug("structural — missing required output part"),
            "structural_missing_required_output_part",
        )

    def test_hyphens_and_em_dash_both_collapse(self) -> None:
        # em-dash plus hyphens; em-dash is multi-byte UTF-8 but still non-alphanumeric
        self.assertEqual(
            derive_slug("anti-pattern — explicit-rule violation"),
            "anti_pattern_explicit_rule_violation",
        )

    def test_empty_string(self) -> None:
        self.assertEqual(derive_slug(""), "")

    def test_all_special_chars(self) -> None:
        # Pure non-alphanumeric input collapses to one underscore, then stripping
        # leading/trailing underscores leaves empty string.
        self.assertEqual(derive_slug("!!!---???"), "")

    def test_already_clean_input(self) -> None:
        self.assertEqual(
            derive_slug("already_clean_lowercase"), "already_clean_lowercase"
        )

    def test_mixed_case_with_spaces(self) -> None:
        self.assertEqual(derive_slug("Foo Bar Baz"), "foo_bar_baz")

    def test_length_exactly_60_passes_through(self) -> None:
        s = "a" * 60
        self.assertEqual(derive_slug(s), s)
        self.assertEqual(len(derive_slug(s)), 60)

    def test_length_100_is_truncated_to_60(self) -> None:
        s = "a" * 100
        out = derive_slug(s)
        self.assertEqual(len(out), SLUG_MAX_LEN)
        self.assertEqual(out, "a" * SLUG_MAX_LEN)

    def test_slug_length_61_truncates_to_60(self) -> None:
        # Boundary exactly one over the cap — guards against off-by-one in the
        # SLUG_MAX_LEN truncation slice.
        s = "a" * 61
        out = derive_slug(s)
        self.assertEqual(len(out), SLUG_MAX_LEN)
        self.assertEqual(out, "a" * SLUG_MAX_LEN)

    def test_strips_leading_and_trailing_underscores(self) -> None:
        # Leading/trailing non-alphanumeric runs leave a leading/trailing _;
        # strip rule applies after collapse.
        self.assertEqual(derive_slug("---foo---"), "foo")

    def test_non_string_input_coerced(self) -> None:
        # Defensive: caller passes None or numeric — we coerce via str().
        self.assertEqual(derive_slug(None), "none")  # type: ignore[arg-type]


# --- extract_discrimination_assertions ---------------------------------------


class ExtractDiscriminationAssertionsTest(unittest.TestCase):
    def test_filters_out_n_a_sanity(self) -> None:
        evals = {
            "categories": [
                {
                    "name": "Discrimination",
                    "evals": [
                        {"id": 1, "defect_type": "structural — missing part"},
                        {"id": 2, "defect_type": "n/a-sanity"},
                        {"id": 3, "defect_type": "n/a-coverage"},
                        {"id": 4, "defect_type": "anti-pattern — explicit-rule"},
                    ],
                }
            ]
        }
        out = extract_discrimination_assertions(evals)
        self.assertEqual([a["id"] for a in out], [1, 4])

    def test_handles_missing_categories_key(self) -> None:
        self.assertEqual(extract_discrimination_assertions({}), [])

    def test_handles_non_list_categories(self) -> None:
        self.assertEqual(extract_discrimination_assertions({"categories": "oops"}), [])

    def test_handles_missing_defect_type_field(self) -> None:
        # Missing defect_type → treated as discrimination (safer default).
        evals = {
            "categories": [
                {"name": "X", "evals": [{"id": 1}]},
            ]
        }
        out = extract_discrimination_assertions(evals)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 1)

    def test_assertion_enriched_with_category_marker(self) -> None:
        evals = _make_evals(["structural — missing part"])
        out = extract_discrimination_assertions(evals)
        self.assertEqual(out[0]["_category"], "Discrimination")

    def test_non_discrimination_set_documented_constant(self) -> None:
        # Lock the contract so silent expansion of the set is caught.
        self.assertEqual(
            NON_DISCRIMINATION_DEFECT_TYPES,
            frozenset({"n/a-sanity", "n/a-coverage"}),
        )


# --- build_generator_prompt --------------------------------------------------


class BuildGeneratorPromptTest(unittest.TestCase):
    def _assertion(
        self, defect_type: str = "structural — missing part"
    ) -> dict[str, Any]:
        return {
            "id": 42,
            "statement": "Output contains Part 1 and Part 2.",
            "source": "SKILL.md line 327",
            "defect_type": defect_type,
        }

    def test_includes_assertion_text(self) -> None:
        prompt = build_generator_prompt(
            self._assertion(), "good content", "skill content"
        )
        self.assertIn("Output contains Part 1 and Part 2.", prompt)

    def test_includes_defect_type(self) -> None:
        prompt = build_generator_prompt(
            self._assertion("anti-pattern — explicit-rule"), "g", "s"
        )
        self.assertIn("anti-pattern — explicit-rule", prompt)

    def test_includes_good_md_content(self) -> None:
        prompt = build_generator_prompt(
            self._assertion(), "GOOD-MD-SENTINEL", "skill content"
        )
        self.assertIn("GOOD-MD-SENTINEL", prompt)

    def test_includes_skill_md_content(self) -> None:
        prompt = build_generator_prompt(self._assertion(), "good", "SKILL-MD-SENTINEL")
        self.assertIn("SKILL-MD-SENTINEL", prompt)

    def test_default_subtlety_is_subtle(self) -> None:
        prompt = build_generator_prompt(self._assertion(), "g", "s")
        self.assertIn("subtle zone", prompt)

    def test_obvious_subtlety_flips_instruction(self) -> None:
        prompt = build_generator_prompt(self._assertion(), "g", "s", subtlety="obvious")
        self.assertIn("OBVIOUS", prompt)
        self.assertNotIn("subtle zone", prompt)

    def test_html_comment_header_instruction_present(self) -> None:
        prompt = build_generator_prompt(self._assertion(), "g", "s")
        self.assertIn("<!-- BAD OUTPUT", prompt)


# --- generate_for_skill ------------------------------------------------------


class GenerateForSkillTest(unittest.TestCase):
    def _fixed_now(self) -> _dt.datetime:
        return _dt.datetime(2026, 5, 25, 12, 0, 0)

    def test_writes_one_bad_file_per_assertion_plus_good_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(
                [
                    "structural — missing part",
                    "anti-pattern — explicit-rule",
                    "quantity-constraint violation",
                ]
            )
            _make_skill_tree(root, "demo", evals=evals)
            result = generate_for_skill(
                "demo",
                dispatch_fn=_fake_dispatch,
                skills_root=root,
                now=self._fixed_now,
            )

            golden = root / "demo" / "evals" / "golden"
            self.assertTrue((golden / "good.md").is_file())
            self.assertTrue((golden / "manifest.json").is_file())
            bad_files = sorted(p.name for p in golden.glob("bad_*.md"))
            self.assertEqual(len(bad_files), 3)
            self.assertEqual(result["assertions"], 3)
            self.assertEqual(len(result["bads"]), 3)

    def test_manifest_schema(self) -> None:
        # With Step 9's verification gate wired, the manifest carries populated
        # verified_fails (never null post-gate) and regen_attempts >= 1.
        # Inject a score_fn that always-fails so the gate accepts on first try.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(["structural — missing part"])
            _make_skill_tree(root, "demo", evals=evals)
            generate_for_skill(
                "demo",
                dispatch_fn=_fake_dispatch,
                score_fn=_always_fails_score_fn,
                skills_root=root,
                now=self._fixed_now,
            )
            manifest = json.loads(
                (root / "demo" / "evals" / "golden" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["skill"], "demo")
            self.assertEqual(manifest["good_source"], "auto-generated")
            self.assertIn("generated_at", manifest)
            self.assertEqual(manifest["manifest_version"], MANIFEST_SCHEMA_VERSION)
            self.assertIn("verification_summary", manifest)
            self.assertEqual(len(manifest["bads"]), 1)
            entry = manifest["bads"][0]
            self.assertEqual(entry["defect_type"], "structural — missing part")
            self.assertEqual(entry["assertion_id"], 1)
            # Post-Step-9: verified_fails is bool, never None.
            self.assertIsInstance(entry["verified_fails"], bool)
            self.assertTrue(entry["verified_fails"])
            self.assertEqual(entry["regen_attempts"], 1)
            self.assertTrue(entry["file"].startswith("bad_"))

    def test_duplicate_defect_type_gets_numeric_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(
                [
                    "duplicate constants",
                    "duplicate constants",
                    "duplicate constants",
                ]
            )
            _make_skill_tree(root, "demo", evals=evals)
            result = generate_for_skill(
                "demo",
                dispatch_fn=_fake_dispatch,
                skills_root=root,
                now=self._fixed_now,
            )
            filenames = sorted(b["file"] for b in result["bads"])
            self.assertEqual(
                filenames,
                [
                    "bad_duplicate_constants.md",
                    "bad_duplicate_constants_2.md",
                    "bad_duplicate_constants_3.md",
                ],
            )

    def test_existing_hand_crafted_good_md_is_preserved_as_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(["structural — missing part"])
            _make_skill_tree(
                root,
                "demo",
                evals=evals,
                good_md="<!-- HAND CRAFTED -->\nbody\n",
            )
            result = generate_for_skill(
                "demo",
                dispatch_fn=_fake_dispatch,
                skills_root=root,
                now=self._fixed_now,
            )
            self.assertEqual(result["good_source"], "hand-crafted")
            # good.md content unchanged
            content = (root / "demo" / "evals" / "golden" / "good.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("HAND CRAFTED", content)

    def test_dry_run_does_not_call_dispatcher(self) -> None:
        # Critical: dry-run must never invoke the LLM dispatcher (would burn
        # tokens silently). Inject a dispatcher that raises if called.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(
                [
                    "structural — missing part",
                    "anti-pattern — explicit-rule",
                    "quantity-constraint violation",
                ]
            )
            _make_skill_tree(root, "demo", evals=evals)

            call_count = {"value": 0}

            def _exploding_dispatch(prompt: str) -> str:
                call_count["value"] += 1
                raise AssertionError("dispatcher must NOT be called when dry_run=True")

            result = generate_for_skill(
                "demo",
                dispatch_fn=_exploding_dispatch,
                skills_root=root,
                dry_run=True,
                now=self._fixed_now,
            )
            self.assertEqual(call_count["value"], 0)
            self.assertTrue(result["dry_run"])
            # Summary still reports the planned files so operators can preview.
            self.assertEqual(result["assertions"], 3)
            self.assertEqual(len(result["bads"]), 3)

    def test_dry_run_writes_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(["structural — missing part"])
            _make_skill_tree(root, "demo", evals=evals)
            result = generate_for_skill(
                "demo",
                dispatch_fn=_fake_dispatch,
                skills_root=root,
                dry_run=True,
                now=self._fixed_now,
            )
            self.assertTrue(result["dry_run"])
            golden = root / "demo" / "evals" / "golden"
            # No directory created, or if it exists it's empty.
            if golden.exists():
                self.assertEqual(list(golden.iterdir()), [])

    def test_missing_skill_dir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            root.mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                generate_for_skill(
                    "no-such-skill",
                    dispatch_fn=_fake_dispatch,
                    skills_root=root,
                )

    def test_missing_evals_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            # Skill dir exists but no evals.json
            (root / "demo").mkdir(parents=True)
            (root / "demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                generate_for_skill(
                    "demo",
                    dispatch_fn=_fake_dispatch,
                    skills_root=root,
                )


# --- _resolve_skill_dir ------------------------------------------------------


class ResolveSkillDirTest(unittest.TestCase):
    def test_resolve_skill_dir_rejects_path_traversal(self) -> None:
        # Defense in depth: skill_name values that escape skills_root via
        # parent-dir components or absolute paths must be rejected with a
        # ValueError before any I/O happens.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            root.mkdir()
            # Also create a sibling dir outside the skills root that a traversal
            # attempt might land in, so we can prove the resolver refuses it.
            (Path(td) / "other-skill").mkdir()

            # Relative traversal: ../other-skill
            with self.assertRaises(ValueError) as ctx:
                _resolve_skill_dir("../other-skill", skills_root=root)
            self.assertIn("escapes skills_root", str(ctx.exception))

            # Round-trip traversal: foo/../../other-skill
            with self.assertRaises(ValueError):
                _resolve_skill_dir("foo/../../other-skill", skills_root=root)

            # Deep traversal: ../../etc/passwd
            with self.assertRaises(ValueError):
                _resolve_skill_dir("../../etc/passwd", skills_root=root)

            # Absolute path: /abs/path (Windows or POSIX). On Windows, an
            # absolute POSIX-style path may be normalized; pass a real absolute
            # path that's clearly outside the skills root.
            abs_outside = str((Path(td) / "other-skill").resolve())
            with self.assertRaises(ValueError):
                _resolve_skill_dir(abs_outside, skills_root=root)

    def test_resolve_skill_dir_accepts_valid_skill_name(self) -> None:
        # Sanity: well-formed names that stay inside the root resolve cleanly.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            (root / "demo").mkdir(parents=True)
            resolved = _resolve_skill_dir("demo", skills_root=root)
            self.assertEqual(resolved.resolve(), (root / "demo").resolve())

    def test_resolve_skill_dir_rejects_root_itself(self) -> None:
        # Empty / "." / "./" should not be treated as a skill dir even though
        # they're trivially "inside" the root.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            root.mkdir()
            for name in (".", "./"):
                with self.assertRaises(ValueError):
                    _resolve_skill_dir(name, skills_root=root)


# --- load_evals --------------------------------------------------------------


class LoadEvalsTest(unittest.TestCase):
    def test_loads_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = Path(td) / "demo"
            (skill_dir / "evals").mkdir(parents=True)
            (skill_dir / "evals" / "evals.json").write_text(
                json.dumps({"skill": "demo", "categories": []}), encoding="utf-8"
            )
            evals = load_evals(skill_dir)
            self.assertEqual(evals["skill"], "demo")

    def test_missing_file_raises_with_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            skill_dir = Path(td) / "demo"
            skill_dir.mkdir()
            with self.assertRaises(FileNotFoundError) as ctx:
                load_evals(skill_dir)
            self.assertIn("evals.json not found", str(ctx.exception))


# --- auto_discover_skills ----------------------------------------------------


class AutoDiscoverSkillsTest(unittest.TestCase):
    def test_finds_skills_with_evals_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "alpha", evals=_make_evals(["x"]))
            _make_skill_tree(root, "beta", evals=_make_evals(["y"]))
            # Skill with no evals.json is excluded.
            (root / "no-evals").mkdir()
            (root / "no-evals" / "SKILL.md").write_text("# x\n", encoding="utf-8")
            names = auto_discover_skills(skills_root=root)
            self.assertEqual(names, ["alpha", "beta"])

    def test_skips_underscore_prefixed_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "alpha", evals=_make_evals(["x"]))
            _make_skill_tree(root, "_shared", evals=_make_evals(["x"]))
            names = auto_discover_skills(skills_root=root)
            self.assertEqual(names, ["alpha"])

    def test_returns_empty_list_when_root_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(auto_discover_skills(skills_root=Path(td) / "nope"), [])


# --- Module-level invariants (regression guards) ----------------------------


class SkillsRootResolutionTest(unittest.TestCase):
    """Pin the workspace-layout invariant for ``_SKILLS_ROOT``.

    Step 8 originally shipped with ``parents[3]`` resolving to ``.claude``
    rather than the workspace root, so ``_SKILLS_ROOT`` evaluated to a
    nonexistent ``.claude/.claude/skills`` and ``auto_discover_skills()``
    silently returned ``[]``. Iter-2 fixes the path to resolve via
    ``parents[2]`` directly; this test pins the fix so any future drift fails
    in unit tests rather than at operator-fleet-run time.
    """

    def test_skills_root_resolves_to_real_directory(self) -> None:
        self.assertTrue(
            generate_bad_examples._SKILLS_ROOT.is_dir(),
            f"_SKILLS_ROOT does not exist: {generate_bad_examples._SKILLS_ROOT}",
        )
        self.assertEqual(generate_bad_examples._SKILLS_ROOT.name, "skills")
        self.assertEqual(generate_bad_examples._SKILLS_ROOT.parent.name, ".claude")


# --- generate_fleet ----------------------------------------------------------


class GenerateFleetTest(unittest.TestCase):
    def test_processes_all_discovered_skills(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            for name in ("alpha", "beta", "gamma", "delta"):
                _make_skill_tree(root, name, evals=_make_evals(["structural"]))
            result = generate_fleet(
                dispatch_fn=_fake_dispatch,
                batch_size=2,
                skills_root=root,
            )
            self.assertTrue(result["fleet"])
            self.assertEqual(result["skills_processed"], 4)
            names = [r["skill"] for r in result["results"]]
            self.assertEqual(sorted(names), ["alpha", "beta", "delta", "gamma"])

    def test_batch_size_caps_concurrency(self) -> None:
        # Use a counter + Lock that records peak concurrency observed by the
        # fake dispatcher. The fleet must never exceed batch_size in flight.
        peak = {"value": 0}
        in_flight = {"value": 0}
        lock = threading.Lock()

        def _slow_dispatch(prompt: str) -> str:
            with lock:
                in_flight["value"] += 1
                if in_flight["value"] > peak["value"]:
                    peak["value"] = in_flight["value"]
            time.sleep(0.02)
            with lock:
                in_flight["value"] -= 1
            return "<!-- bad -->\nbody\n"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            # 6 skills with 2 assertions each = 12 dispatches; batch_size=3
            # means at most 3 skills concurrently. Per-assertion dispatches
            # within one skill are sequential in generate_for_skill, so peak
            # concurrency observed at the dispatcher equals the number of
            # parallel skills, capped by batch_size.
            for i in range(6):
                _make_skill_tree(
                    root,
                    f"s{i}",
                    evals=_make_evals(["structural", "anti-pattern"]),
                )
            generate_fleet(
                dispatch_fn=_slow_dispatch,
                batch_size=3,
                skills_root=root,
            )
            self.assertLessEqual(peak["value"], 3)
            # Sanity: at least some parallelism happened (else the test is
            # toothless). With 6 skills + 0.02s/dispatch we expect peak >= 2.
            self.assertGreaterEqual(peak["value"], 2)

    def test_per_skill_error_is_captured_not_raised(self) -> None:
        # If one skill blows up (e.g. malformed evals.json), the fleet result
        # records the error and keeps processing the rest.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "good", evals=_make_evals(["structural"]))
            # Bad skill: malformed JSON
            bad_dir = root / "bad"
            (bad_dir / "evals").mkdir(parents=True)
            (bad_dir / "evals" / "evals.json").write_text("{not json", encoding="utf-8")
            result = generate_fleet(
                dispatch_fn=_fake_dispatch,
                batch_size=2,
                skills_root=root,
            )
            errored = [r for r in result["results"] if "error" in r]
            succeeded = [r for r in result["results"] if "error" not in r]
            self.assertEqual([r["skill"] for r in errored], ["bad"])
            self.assertEqual([r["skill"] for r in succeeded], ["good"])

    def test_empty_skill_root_returns_zero_processed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            root.mkdir()
            result = generate_fleet(
                dispatch_fn=_fake_dispatch,
                batch_size=DEFAULT_FLEET_BATCH_SIZE,
                skills_root=root,
            )
            self.assertEqual(result["skills_processed"], 0)


# --- _assign_slugs (internal helper covered for the duplicate-suffix contract) ---


class AssignSlugsTest(unittest.TestCase):
    def test_first_occurrence_no_suffix(self) -> None:
        slugs = [s for _a, s in _assign_slugs([{"defect_type": "foo"}])]
        self.assertEqual(slugs, ["foo"])

    def test_subsequent_occurrences_get_numeric_suffix(self) -> None:
        slugs = [
            s
            for _a, s in _assign_slugs(
                [
                    {"defect_type": "foo"},
                    {"defect_type": "foo"},
                    {"defect_type": "foo"},
                ]
            )
        ]
        self.assertEqual(slugs, ["foo", "foo_2", "foo_3"])

    def test_empty_defect_type_becomes_unnamed(self) -> None:
        slugs = [s for _a, s in _assign_slugs([{"defect_type": ""}])]
        self.assertEqual(slugs, ["unnamed"])

    def test_assign_slugs_suffix_respects_max_len(self) -> None:
        # When the raw slug is already at SLUG_MAX_LEN (60) and a duplicate
        # arrives, the suffix ("_2") must NOT push the filename past 60 chars.
        # The base is trimmed by len(suffix) so base + suffix == SLUG_MAX_LEN.
        long_defect = "x" * 60  # already at the cap
        pairs = _assign_slugs(
            [
                {"defect_type": long_defect, "id": 1},
                {"defect_type": long_defect, "id": 2},
            ]
        )
        slugs = [s for _a, s in pairs]
        # First: full 60-char slug, no suffix.
        self.assertEqual(slugs[0], "x" * 60)
        self.assertEqual(len(slugs[0]), SLUG_MAX_LEN)
        # Second: 58-char base + "_2" = exactly 60 chars.
        self.assertEqual(slugs[1], "x" * 58 + "_2")
        self.assertEqual(len(slugs[1]), SLUG_MAX_LEN)


# --- dispatch_generator stub contract ----------------------------------------


class DispatchGeneratorStubTest(unittest.TestCase):
    def test_default_dispatcher_raises_until_step_9(self) -> None:
        # Production stub. Step 9 wires the real sub-agent. Until then,
        # forgetting to inject dispatch_fn yields a loud failure.
        with self.assertRaises(NotImplementedError):
            dispatch_generator("any prompt")


# --- Step 9: score_bad_against_evals -----------------------------------------


class ScoreBadAgainstEvalsTest(unittest.TestCase):
    """Step 9: verification-gate scoring contract.

    Covers Done-when criteria: gate accepts a bad that fails the grader on
    first try; gate retries up to 3x; gate marks INERT after 3 failures.
    The four cases below pin the per-verdict contract that the gate loop
    depends on.
    """

    def test_score_bad_against_evals_fails_when_bad_lower_than_good(self) -> None:
        # Verdict "fails" means the grader correctly distinguished bad-from-
        # good: bad scored strictly LOWER than good. Gate accepts.
        def _score(bad_md, good_md, skill_md, evals):
            return (0.9, 0.3)

        result = score_bad_against_evals("bad", "good", "skill", {}, score_fn=_score)
        self.assertEqual(result["verdict"], "fails")
        self.assertEqual(result["good_score"], 0.9)
        self.assertEqual(result["score"], 0.3)

    def test_score_bad_against_evals_passes_when_bad_equal(self) -> None:
        # Tie counts as "passes" — the grader didn't distinguish them. The
        # contract is strict-lower for accept.
        def _score(bad_md, good_md, skill_md, evals):
            return (0.5, 0.5)

        result = score_bad_against_evals("bad", "good", "skill", {}, score_fn=_score)
        self.assertEqual(result["verdict"], "passes")

    def test_score_bad_against_evals_passes_when_bad_higher(self) -> None:
        # Bad scored higher than good — the grader is being sycophantic on
        # this fixture pair. Verdict "passes" (gate will regenerate).
        def _score(bad_md, good_md, skill_md, evals):
            return (0.5, 0.8)

        result = score_bad_against_evals("bad", "good", "skill", {}, score_fn=_score)
        self.assertEqual(result["verdict"], "passes")

    def test_score_bad_against_evals_indeterminate_on_score_fn_exception(self) -> None:
        # Any exception from score_fn → indeterminate. The gate treats this
        # as "passes" for safety (regenerate rather than accept an unverified
        # bad).
        def _score(bad_md, good_md, skill_md, evals):
            raise RuntimeError("scorer blew up")

        result = score_bad_against_evals("bad", "good", "skill", {}, score_fn=_score)
        self.assertEqual(result["verdict"], "indeterminate")


# --- Step 9: gate loop in generate_for_skill ---------------------------------


class GateLoopTest(unittest.TestCase):
    """Step 9: verification-gate retry-and-INERT contract inside generate_for_skill."""

    def _fixed_now(self) -> _dt.datetime:
        return _dt.datetime(2026, 5, 25, 12, 0, 0)

    def test_gate_accepts_on_first_try_when_grader_fails(self) -> None:
        # Done-when: gate accepts a bad that fails the grader on first try.
        dispatch_calls: list[str] = []

        def _dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            return "<!-- bad #1 -->\nbody\n"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "demo", evals=_make_evals(["structural"]))
            result = generate_for_skill(
                "demo",
                dispatch_fn=_dispatch,
                score_fn=_always_fails_score_fn,
                skills_root=root,
                now=self._fixed_now,
            )
            self.assertEqual(len(dispatch_calls), 1)
            entry = result["bads"][0]
            self.assertTrue(entry["verified_fails"])
            self.assertEqual(entry["regen_attempts"], 1)

    def test_gate_retries_up_to_3x_when_grader_passes(self) -> None:
        # Done-when: gate retries up to 3x for a bad the grader passes; if
        # the 3rd attempt succeeds, the bad is accepted with regen_attempts=3.
        dispatch_calls: list[str] = []

        def _dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            return f"<!-- bad attempt {len(dispatch_calls)} -->\nbody\n"

        verdicts = iter([(0.5, 0.8), (0.5, 0.8), (0.9, 0.3)])  # passes, passes, fails

        def _score(bad_md, good_md, skill_md, evals):
            return next(verdicts)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "demo", evals=_make_evals(["structural"]))
            result = generate_for_skill(
                "demo",
                dispatch_fn=_dispatch,
                score_fn=_score,
                skills_root=root,
                now=self._fixed_now,
            )
            self.assertEqual(len(dispatch_calls), 3)
            entry = result["bads"][0]
            self.assertTrue(entry["verified_fails"])
            self.assertEqual(entry["regen_attempts"], 3)

    def test_gate_marks_inert_after_3_failed_regens(self) -> None:
        # Done-when: gate marks INERT after 3 failed regenerations; file is
        # still written; dispatch called exactly 3 times (not 4).
        dispatch_calls: list[str] = []

        def _dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            return f"<!-- inert attempt {len(dispatch_calls)} -->\nbody\n"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "demo", evals=_make_evals(["structural"]))
            result = generate_for_skill(
                "demo",
                dispatch_fn=_dispatch,
                score_fn=_always_passes_score_fn,
                skills_root=root,
                now=self._fixed_now,
            )
            self.assertEqual(len(dispatch_calls), 3)
            entry = result["bads"][0]
            self.assertFalse(entry["verified_fails"])
            self.assertEqual(entry["regen_attempts"], 3)
            # File still written for operator inspection.
            bad_path = root / "demo" / "evals" / "golden" / entry["file"]
            self.assertTrue(bad_path.is_file())
            content = bad_path.read_text(encoding="utf-8")
            # The LAST attempt's content is what gets written.
            self.assertIn("inert attempt 3", content)
            # Verification summary reflects the INERT count.
            self.assertEqual(result["verification_summary"]["inert"], 1)
            self.assertEqual(result["verification_summary"]["accepted"], 0)

    def test_manifest_v2_schema(self) -> None:
        # Done-when: manifest.json schema validates against the fixed shape
        # documented in plan §5 New Components: manifest_version=2,
        # verification_summary present, per-bad verified_fails populated
        # (bool, never null) and regen_attempts populated (int in [1,3]).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(
                root,
                "demo",
                evals=_make_evals(["structural", "anti-pattern", "quantity"]),
            )
            generate_for_skill(
                "demo",
                dispatch_fn=_fake_dispatch,
                score_fn=_always_fails_score_fn,
                skills_root=root,
                now=self._fixed_now,
            )
            manifest = json.loads(
                (root / "demo" / "evals" / "golden" / "manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["manifest_version"], 2)
            self.assertIn("verification_summary", manifest)
            summary = manifest["verification_summary"]
            self.assertEqual(set(summary.keys()), {"accepted", "inert", "total"})
            self.assertEqual(summary["total"], summary["accepted"] + summary["inert"])
            for entry in manifest["bads"]:
                self.assertIsInstance(entry["verified_fails"], bool)
                self.assertIsNotNone(entry["verified_fails"])
                self.assertIsInstance(entry["regen_attempts"], int)
                self.assertGreaterEqual(entry["regen_attempts"], 1)
                self.assertLessEqual(
                    entry["regen_attempts"], DEFAULT_MAX_REGEN_ATTEMPTS
                )

    def test_build_retry_prompt_appends_subtler_directive(self) -> None:
        # Helper contract: at attempts 2 and 3 the returned string contains
        # the original prompt AND a subtler-directive phrase.
        orig = "GENERATE A BAD EXAMPLE FOR DEFECT FOO"
        attempt1 = build_retry_prompt(orig, 1)
        # Attempt 1: no modification (this is the first dispatch).
        self.assertEqual(attempt1, orig)
        attempt2 = build_retry_prompt(orig, 2)
        self.assertIn(orig, attempt2)
        self.assertIn("subtler", attempt2.lower())
        attempt3 = build_retry_prompt(orig, 3)
        self.assertIn(orig, attempt3)
        # Either "subtler" or "more subtle" is acceptable per the spec.
        self.assertTrue(
            "subtler" in attempt3.lower() or "more subtle" in attempt3.lower(),
            msg=f"attempt 3 prompt missing subtler directive: {attempt3!r}",
        )

    def test_verify_only_skips_dispatch(self) -> None:
        # Pre-populate a tempdir with existing bad files + manifest; run
        # generate_for_skill(..., verify_only=True); assert dispatch_fn was
        # NEVER called and the manifest's verified_fails was updated based
        # on the injected score_fn.
        dispatch_calls: list[str] = []

        def _exploding_dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            raise AssertionError("dispatch_fn must NOT be called in verify-only mode")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "demo", evals=_make_evals(["structural"]))
            # Pre-create the golden dir with a bad file + (optionally) prior manifest.
            golden = root / "demo" / "evals" / "golden"
            golden.mkdir(parents=True, exist_ok=True)
            (golden / "good.md").write_text("good content\n", encoding="utf-8")
            (golden / "bad_structural.md").write_text(
                "<!-- bad -->\nbody\n", encoding="utf-8"
            )
            prior_manifest = {
                "manifest_version": 2,
                "skill": "demo",
                "generated_at": "2026-05-24T00:00:00Z",
                "good_source": "auto-generated",
                "verification_summary": {"accepted": 0, "inert": 1, "total": 1},
                "bads": [
                    {
                        "file": "bad_structural.md",
                        "defect_type": "structural",
                        "assertion_id": 1,
                        "verified_fails": False,
                        "regen_attempts": 3,
                    }
                ],
            }
            (golden / "manifest.json").write_text(
                json.dumps(prior_manifest) + "\n", encoding="utf-8"
            )

            result = generate_for_skill(
                "demo",
                dispatch_fn=_exploding_dispatch,
                score_fn=_always_fails_score_fn,
                skills_root=root,
                verify_only=True,
                now=self._fixed_now,
            )
            # Dispatcher must NEVER be called in verify-only mode.
            self.assertEqual(dispatch_calls, [])
            # Manifest updated: now verified_fails should be True (always-fails).
            entry = result["bads"][0]
            self.assertTrue(entry["verified_fails"])
            # Prior regen_attempts (3) preserved when bad file exists.
            self.assertEqual(entry["regen_attempts"], 3)
            # Verification summary recomputed.
            self.assertEqual(result["verification_summary"]["accepted"], 1)
            self.assertEqual(result["verification_summary"]["inert"], 0)
            # Manifest file on disk has the updated values.
            written = json.loads((golden / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(written["bads"][0]["verified_fails"])

    def test_max_regen_attempts_flag_honored(self) -> None:
        # Pass max_regen_attempts=1; mock score_fn returning passes; assert
        # dispatch called exactly 1 time and INERT marker appears.
        dispatch_calls: list[str] = []

        def _dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            return "<!-- bad -->\nbody\n"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "demo", evals=_make_evals(["structural"]))
            result = generate_for_skill(
                "demo",
                dispatch_fn=_dispatch,
                score_fn=_always_passes_score_fn,
                skills_root=root,
                max_regen_attempts=1,
                now=self._fixed_now,
            )
            self.assertEqual(len(dispatch_calls), 1)
            entry = result["bads"][0]
            self.assertFalse(entry["verified_fails"])
            self.assertEqual(entry["regen_attempts"], 1)
            self.assertEqual(result["verification_summary"]["inert"], 1)

    def test_verification_summary_counts_correct(self) -> None:
        # Generate with 5 assertions: 3 accept on first try, 1 needs retry
        # then accepts, 1 marks INERT. Verify summary shows accepted: 4,
        # inert: 1, total: 5.
        #
        # Schedule of (good, bad) score pairs returned by score_fn, in
        # dispatch-order. Each assertion is processed sequentially within a
        # single skill so we know the call ordering. 5 assertions:
        #   assertion 1: (fails)                         → 1 attempt
        #   assertion 2: (fails)                         → 1 attempt
        #   assertion 3: (fails)                         → 1 attempt
        #   assertion 4: (passes, fails)                 → 2 attempts
        #   assertion 5: (passes, passes, passes)        → 3 attempts, INERT
        schedule = iter(
            [
                (0.9, 0.3),
                (0.9, 0.3),
                (0.9, 0.3),
                (0.5, 0.8),
                (0.9, 0.3),
                (0.5, 0.8),
                (0.5, 0.8),
                (0.5, 0.8),
            ]
        )

        def _score(bad_md, good_md, skill_md, evals):
            return next(schedule)

        dispatch_calls: list[str] = []

        def _dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            return f"<!-- bad #{len(dispatch_calls)} -->\nbody\n"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(
                root,
                "demo",
                evals=_make_evals(["a", "b", "c", "d", "e"]),
            )
            result = generate_for_skill(
                "demo",
                dispatch_fn=_dispatch,
                score_fn=_score,
                skills_root=root,
                now=self._fixed_now,
            )
            summary = result["verification_summary"]
            self.assertEqual(summary["accepted"], 4)
            self.assertEqual(summary["inert"], 1)
            self.assertEqual(summary["total"], 5)
            # Total dispatches across all assertions: 1+1+1+2+3 = 8.
            self.assertEqual(len(dispatch_calls), 8)

    def test_verify_only_bad_file_deleted_from_disk(self) -> None:
        # Iter 2 HIGH coverage gap: --verify-only must surface missing
        # bad files via the regen_attempts=0 sentinel so the operator can
        # spot a corpus that lost a file out-of-band (rm, git clean,
        # half-finished move). Other entries still re-score normally.
        dispatch_calls: list[str] = []

        def _exploding_dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            raise AssertionError("dispatch_fn must NOT be called in verify-only mode")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(
                root,
                "demo",
                evals=_make_evals(["alpha", "beta", "gamma"]),
            )
            golden = root / "demo" / "evals" / "golden"
            golden.mkdir(parents=True, exist_ok=True)
            (golden / "good.md").write_text("good content\n", encoding="utf-8")
            # Pre-populate all three bad files + manifest.
            (golden / "bad_alpha.md").write_text(
                "<!-- bad alpha -->\n", encoding="utf-8"
            )
            (golden / "bad_beta.md").write_text("<!-- bad beta -->\n", encoding="utf-8")
            (golden / "bad_gamma.md").write_text(
                "<!-- bad gamma -->\n", encoding="utf-8"
            )
            prior_manifest = {
                "manifest_version": 2,
                "skill": "demo",
                "generated_at": "2026-05-24T00:00:00Z",
                "good_source": "auto-generated",
                "verification_summary": {"accepted": 3, "inert": 0, "total": 3},
                "bads": [
                    {
                        "file": "bad_alpha.md",
                        "defect_type": "alpha",
                        "assertion_id": 1,
                        "verified_fails": True,
                        "regen_attempts": 2,
                    },
                    {
                        "file": "bad_beta.md",
                        "defect_type": "beta",
                        "assertion_id": 2,
                        "verified_fails": True,
                        "regen_attempts": 1,
                    },
                    {
                        "file": "bad_gamma.md",
                        "defect_type": "gamma",
                        "assertion_id": 3,
                        "verified_fails": True,
                        "regen_attempts": 1,
                    },
                ],
            }
            (golden / "manifest.json").write_text(
                json.dumps(prior_manifest) + "\n", encoding="utf-8"
            )
            # Operator deletes bad_beta.md out-of-band.
            (golden / "bad_beta.md").unlink()

            result = generate_for_skill(
                "demo",
                dispatch_fn=_exploding_dispatch,
                score_fn=_always_fails_score_fn,
                skills_root=root,
                verify_only=True,
                now=self._fixed_now,
            )
            self.assertEqual(dispatch_calls, [])
            by_file = {entry["file"]: entry for entry in result["bads"]}
            # alpha + gamma re-scored normally — present on disk, score_fn
            # marks them as fails, prior regen_attempts preserved.
            self.assertTrue(by_file["bad_alpha.md"]["verified_fails"])
            self.assertEqual(by_file["bad_alpha.md"]["regen_attempts"], 2)
            self.assertTrue(by_file["bad_gamma.md"]["verified_fails"])
            self.assertEqual(by_file["bad_gamma.md"]["regen_attempts"], 1)
            # beta missing on disk → operator-detectable sentinel.
            self.assertFalse(by_file["bad_beta.md"]["verified_fails"])
            self.assertEqual(by_file["bad_beta.md"]["regen_attempts"], 0)
            # Manifest on disk reflects the same.
            written = json.loads((golden / "manifest.json").read_text(encoding="utf-8"))
            written_by_file = {e["file"]: e for e in written["bads"]}
            self.assertEqual(written_by_file["bad_beta.md"]["regen_attempts"], 0)
            self.assertFalse(written_by_file["bad_beta.md"]["verified_fails"])

    def test_verify_only_migrates_v1_manifest_to_v2(self) -> None:
        # Iter 2 HIGH coverage gap: --verify-only must migrate a pre-Step-9
        # (v1) manifest — no manifest_version, no verification_summary, bads
        # with verified_fails: null — to v2 in-place. After verify-only, the
        # manifest must have manifest_version=2, a verification_summary
        # dict, and verified_fails as a real bool.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "demo", evals=_make_evals(["structural"]))
            golden = root / "demo" / "evals" / "golden"
            golden.mkdir(parents=True, exist_ok=True)
            (golden / "good.md").write_text("good content\n", encoding="utf-8")
            (golden / "bad_structural.md").write_text(
                "<!-- bad structural -->\n", encoding="utf-8"
            )
            # v1 manifest shape: no manifest_version, no verification_summary,
            # verified_fails:null, regen_attempts:0 placeholders.
            v1_manifest = {
                "skill": "demo",
                "generated_at": "2026-05-20T00:00:00Z",
                "good_source": "auto-generated",
                "bads": [
                    {
                        "file": "bad_structural.md",
                        "defect_type": "structural",
                        "assertion_id": 1,
                        "verified_fails": None,
                        "regen_attempts": 0,
                    }
                ],
            }
            (golden / "manifest.json").write_text(
                json.dumps(v1_manifest) + "\n", encoding="utf-8"
            )

            result = generate_for_skill(
                "demo",
                score_fn=_always_fails_score_fn,
                skills_root=root,
                verify_only=True,
                now=self._fixed_now,
            )
            # Returned summary is v2-shaped.
            self.assertEqual(result["manifest_version"], 2)
            self.assertIn("verification_summary", result)
            entry = result["bads"][0]
            self.assertIsInstance(entry["verified_fails"], bool)
            self.assertTrue(entry["verified_fails"])
            # On-disk manifest migrated to v2.
            written = json.loads((golden / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(written["manifest_version"], 2)
            self.assertIn("verification_summary", written)
            self.assertEqual(written["verification_summary"]["accepted"], 1)
            self.assertEqual(written["verification_summary"]["inert"], 0)
            written_entry = written["bads"][0]
            self.assertIsInstance(written_entry["verified_fails"], bool)
            self.assertTrue(written_entry["verified_fails"])

    def test_gate_indeterminate_triggers_retry(self) -> None:
        # Iter 2 MEDIUM coverage gap: an indeterminate verdict (score_fn
        # raised) must trigger the retry loop, not be accepted. Pins the
        # production code's `if verdict == "fails"` semantics against a
        # future refactor that swaps to `verdict != "passes"` — which would
        # silently accept indeterminate as "don't retry", breaking the
        # safety-first design.
        dispatch_calls: list[str] = []

        def _dispatch(prompt: str) -> str:
            dispatch_calls.append(prompt)
            return f"<!-- bad #{len(dispatch_calls)} -->\nbody\n"

        def _raising_score_fn(bad_md, good_md, skill_md, evals):
            raise RuntimeError("grader explodes — indeterminate verdict")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "skills"
            _make_skill_tree(root, "demo", evals=_make_evals(["structural"]))
            result = generate_for_skill(
                "demo",
                dispatch_fn=_dispatch,
                score_fn=_raising_score_fn,
                skills_root=root,
                now=self._fixed_now,
            )
            # Exactly DEFAULT_MAX_REGEN_ATTEMPTS (3) dispatches, then INERT.
            self.assertEqual(len(dispatch_calls), DEFAULT_MAX_REGEN_ATTEMPTS)
            entry = result["bads"][0]
            self.assertFalse(entry["verified_fails"])
            self.assertEqual(entry["regen_attempts"], DEFAULT_MAX_REGEN_ATTEMPTS)
            self.assertEqual(result["verification_summary"]["inert"], 1)
            self.assertEqual(result["verification_summary"]["accepted"], 0)


# --- CLI ---------------------------------------------------------------------


class CLITest(unittest.TestCase):
    def test_main_dry_run_returns_zero_and_emits_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(["structural — missing part"])
            _make_skill_tree(root, "demo", evals=evals)
            # Point the script at our tempdir layout via SKILLS_ROOT override.
            # The module defaults to the workspace skills root; for in-process
            # CLI tests we patch the module attribute.
            import generate_bad_examples as gbe

            old = gbe._SKILLS_ROOT
            gbe._SKILLS_ROOT = root
            try:
                buf_out = io.StringIO()
                buf_err = io.StringIO()
                with redirect_stdout(buf_out), redirect_stderr(buf_err):
                    rc = main(["demo", "--dry-run"])
                self.assertEqual(rc, 0)
                payload = json.loads(buf_out.getvalue())
                self.assertEqual(payload["skill"], "demo")
                self.assertTrue(payload["dry_run"])
                self.assertEqual(payload["assertions"], 1)
            finally:
                gbe._SKILLS_ROOT = old

    def test_main_rejects_fleet_with_skill_name(self) -> None:
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            rc = main(["--fleet", "demo"])
        self.assertEqual(rc, 2)
        self.assertIn("mutually exclusive", buf_err.getvalue())

    def test_main_rejects_neither_skill_nor_fleet(self) -> None:
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            rc = main([])
        self.assertEqual(rc, 2)

    def test_main_single_skill_handles_malformed_evals_json(self) -> None:
        # Single-skill mode must exit with a clean error (not a traceback) when
        # the target skill's evals.json is malformed. Fleet mode catches this
        # in _one()'s broad except; single-skill mode needs explicit handling.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            (root / "demo" / "evals").mkdir(parents=True)
            (root / "demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
            # Malformed JSON
            (root / "demo" / "evals" / "evals.json").write_text(
                "{not json", encoding="utf-8"
            )
            import generate_bad_examples as gbe

            old = gbe._SKILLS_ROOT
            gbe._SKILLS_ROOT = root
            try:
                buf_out = io.StringIO()
                buf_err = io.StringIO()
                with redirect_stdout(buf_out), redirect_stderr(buf_err):
                    rc = main(["demo"])
                # Distinct exit code from the existing 0/2/3/4 scheme.
                self.assertEqual(rc, 5)
                self.assertIn("malformed evals.json", buf_err.getvalue())
                # No JSON payload written on the error path.
                self.assertEqual(buf_out.getvalue(), "")
            finally:
                gbe._SKILLS_ROOT = old

    def test_subprocess_smoke_dry_run(self) -> None:
        # End-to-end: spawn the script as a real process with --dry-run on a
        # synthetic skill. The script is workspace-aware so we have to mock
        # the workspace layout by re-pointing _SKILLS_ROOT via an env override
        # that the script reads. Since the script doesn't support env override
        # natively, we use an inline python -c invocation to import and call
        # main() with our tempdir patched in.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".claude" / "skills"
            evals = _make_evals(["structural — missing part"])
            _make_skill_tree(root, "demo", evals=evals)

            harness = (
                "import sys, json, generate_bad_examples as gbe;"
                f"gbe._SKILLS_ROOT = __import__('pathlib').Path(r'{root}');"
                "sys.exit(gbe.main(['demo', '--dry-run']))"
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = (
                str(SCRIPTS_DIR) + os.pathsep + env.get("PYTHONPATH", "")
            )
            proc = subprocess.run(
                [sys.executable, "-c", harness],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["skill"], "demo")
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["assertions"], 1)


if __name__ == "__main__":
    unittest.main()
