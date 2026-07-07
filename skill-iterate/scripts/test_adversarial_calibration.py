"""Self-contained unit tests for adversarial_calibration.

Covers per-mutation behavior on a realistic SKILL.md fixture, the calibrate_skill
orchestrator's verdict / catch-rate logic (with a fully injected score_fn so no
LLM dispatch is needed), fleet aggregation, and a CLI smoke that the JSON shape
documented in the module docstring lands on stdout.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import adversarial_calibration
from adversarial_calibration import (
    DEFAULT_CATCH_RATE_THRESHOLD,
    DEFAULT_NUM_MUTATIONS,
    GRADER_BROKEN_CRASH_CLASS,
    MUTATION_KINDS,
    MutationNotApplicable,
    _TRAILING_GARBAGE_MARKER,
    apply_mutation,
    calibrate_fleet,
    calibrate_skill,
    enumerate_mutations,
    main,
)

SCRIPTS_DIR = Path(__file__).resolve().parent


# A realistic SKILL.md fixture with at least one instance of every mutation
# target so apply_mutation tests can probe every kind without hitting
# MutationNotApplicable. Kept as a module-level constant so individual tests
# can read + mutate without filesystem touchpoints.
RICH_SKILL_MD = """\
---
name: example-skill
description: Example skill for adversarial_calibration tests.
---

# /example-skill

You MUST do the right thing. Do not skip the steps.

## Steps

1. Read the inputs.
2. Validate the schema.
3. Emit the output.

## Constraints

- **Input:** never null.
- **Output:** required JSON shape with at least one key.
- **Mode:** must be one of `dry-run`, `apply`.

## Procedure

The skill operates by walking the inputs in order. Each input is validated
against the schema before being emitted to the output stream.

```python
def example():
    return {"status": "ok"}
```

## Limitations

Some failure modes are not yet handled. See the open issues for the current
gap list.
"""


# A minimal SKILL.md that has NO code fences, NO numbered steps, NO list
# bullets, NO constraint markers, NO headings beyond H1. Used to verify
# MutationNotApplicable raises for the kinds that have no target here.
MINIMAL_SKILL_MD = """\
# Tiny

Just one paragraph of prose with no structure to mutate.
"""


# --- apply_mutation per-kind tests ------------------------------------------


class ApplyMutationPerKindTest(unittest.TestCase):
    """For each MUTATION_KIND, assert the mutation runs + has its signature."""

    def _seeded_rng(self) -> random.Random:
        return random.Random(42)

    def test_delete_required_bullet(self) -> None:
        out = apply_mutation(
            RICH_SKILL_MD, "delete_required_bullet", self._seeded_rng()
        )
        self.assertNotEqual(out, RICH_SKILL_MD)
        # At least one "- **Field:**" bullet should be gone.
        before_count = RICH_SKILL_MD.count("- **")
        after_count = out.count("- **")
        self.assertEqual(after_count, before_count - 1)

    def test_paraphrase_heading(self) -> None:
        out = apply_mutation(RICH_SKILL_MD, "paraphrase_heading", self._seeded_rng())
        self.assertNotEqual(out, RICH_SKILL_MD)
        self.assertIn("Renamed Section", out)

    def test_remove_code_fence(self) -> None:
        out = apply_mutation(RICH_SKILL_MD, "remove_code_fence", self._seeded_rng())
        self.assertNotEqual(out, RICH_SKILL_MD)
        # The original has exactly one opening + one closing fence; removing
        # the opener leaves the closing fence as a now-unbalanced singleton.
        original_fences = RICH_SKILL_MD.count("```")
        out_fences = out.count("```")
        self.assertEqual(out_fences, original_fences - 1)

    def test_swap_must_with_should(self) -> None:
        out = apply_mutation(RICH_SKILL_MD, "swap_must_with_should", self._seeded_rng())
        self.assertNotEqual(out, RICH_SKILL_MD)
        # At least one "MUST"/"must" must be gone (one was replaced).
        before_must = sum(RICH_SKILL_MD.count(w) for w in ("MUST", "must", "Must"))
        after_must = sum(out.count(w) for w in ("MUST", "must", "Must"))
        self.assertEqual(after_must, before_must - 1)

    def test_delete_section(self) -> None:
        out = apply_mutation(RICH_SKILL_MD, "delete_section", self._seeded_rng())
        self.assertNotEqual(out, RICH_SKILL_MD)
        # One of {Steps, Constraints, Procedure, Limitations} headings is gone.
        deleted = sum(
            1
            for h in ("## Steps", "## Constraints", "## Procedure", "## Limitations")
            if h in RICH_SKILL_MD and h not in out
        )
        self.assertGreaterEqual(deleted, 1)

    def test_duplicate_paragraph(self) -> None:
        out = apply_mutation(RICH_SKILL_MD, "duplicate_paragraph", self._seeded_rng())
        self.assertNotEqual(out, RICH_SKILL_MD)
        # The output is strictly longer than the input.
        self.assertGreater(len(out.splitlines()), len(RICH_SKILL_MD.splitlines()))

    def test_remove_leading_imperative(self) -> None:
        out = apply_mutation(
            RICH_SKILL_MD, "remove_leading_imperative", self._seeded_rng()
        )
        self.assertNotEqual(out, RICH_SKILL_MD)
        # One of "Read", "Validate", "Emit" leading verbs should be gone.
        before = sum(
            RICH_SKILL_MD.count(f"{n}. {v}")
            for n, v in (("1", "Read"), ("2", "Validate"), ("3", "Emit"))
        )
        after = sum(
            out.count(f"{n}. {v}")
            for n, v in (("1", "Read"), ("2", "Validate"), ("3", "Emit"))
        )
        self.assertLess(after, before)

    def test_remove_constraint_line(self) -> None:
        out = apply_mutation(
            RICH_SKILL_MD, "remove_constraint_line", self._seeded_rng()
        )
        self.assertNotEqual(out, RICH_SKILL_MD)
        # Output should have strictly fewer lines than input.
        self.assertLess(len(out.splitlines()), len(RICH_SKILL_MD.splitlines()))

    def test_add_trailing_garbage(self) -> None:
        out = apply_mutation(RICH_SKILL_MD, "add_trailing_garbage", self._seeded_rng())
        self.assertNotEqual(out, RICH_SKILL_MD)
        self.assertIn(_TRAILING_GARBAGE_MARKER, out)
        # The marker should be near the end of the output.
        self.assertGreater(
            out.index(_TRAILING_GARBAGE_MARKER),
            len(RICH_SKILL_MD) - 100,
        )

    def test_shuffle_steps(self) -> None:
        out = apply_mutation(RICH_SKILL_MD, "shuffle_steps", self._seeded_rng())
        self.assertNotEqual(out, RICH_SKILL_MD)
        # The output should still contain "1.", "2.", "3." (renumbering preserves
        # sequential indexes) but the body order should have changed.
        self.assertIn("1.", out)
        self.assertIn("2.", out)
        self.assertIn("3.", out)

    def test_every_kind_is_exercised(self) -> None:
        # Belt-and-suspenders: ensure the test class above covers all kinds in
        # MUTATION_KINDS. If a new kind is added without a test, this fails.
        test_method_names = {
            m
            for m in dir(self)
            if m.startswith("test_") and m != "test_every_kind_is_exercised"
        }
        for kind in MUTATION_KINDS:
            self.assertIn(
                f"test_{kind}",
                test_method_names,
                f"Mutation kind {kind!r} has no per-kind test in this class",
            )


# --- apply_mutation error paths ---------------------------------------------


class ApplyMutationNotApplicableTest(unittest.TestCase):
    def test_remove_code_fence_raises_when_no_fences(self) -> None:
        with self.assertRaises(MutationNotApplicable):
            apply_mutation(MINIMAL_SKILL_MD, "remove_code_fence", random.Random(0))

    def test_swap_must_raises_when_no_must(self) -> None:
        text = "# Tiny\n\nNo capitalized rule words at all here.\n"
        with self.assertRaises(MutationNotApplicable):
            apply_mutation(text, "swap_must_with_should", random.Random(0))

    def test_unknown_kind_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            apply_mutation(RICH_SKILL_MD, "not-a-real-kind", random.Random(0))


# --- apply_mutation determinism ---------------------------------------------


class ApplyMutationDeterminismTest(unittest.TestCase):
    def test_same_seed_same_output_for_each_kind(self) -> None:
        # For every applicable kind, two runs with the same seed produce
        # identical output. Drives out non-determinism creeping into the
        # _mutate_* helpers (the catch-rate stat is only meaningful if the
        # mutation step itself is reproducible).
        for kind in MUTATION_KINDS:
            try:
                out_a = apply_mutation(RICH_SKILL_MD, kind, random.Random(7))
                out_b = apply_mutation(RICH_SKILL_MD, kind, random.Random(7))
            except MutationNotApplicable:
                continue
            self.assertEqual(
                out_a,
                out_b,
                f"non-deterministic mutation for kind={kind!r}",
            )


# --- enumerate_mutations ----------------------------------------------------


class EnumerateMutationsTest(unittest.TestCase):
    def test_returns_exactly_num_when_all_applicable(self) -> None:
        out = enumerate_mutations(RICH_SKILL_MD, num=3, rng=random.Random(1))
        self.assertEqual(len(out), 3)
        # Each entry is (kind, mutated_content).
        for kind, mutated in out:
            self.assertIn(kind, MUTATION_KINDS)
            self.assertNotEqual(mutated, RICH_SKILL_MD)

    def test_returns_fewer_when_some_kinds_inapplicable(self) -> None:
        # MINIMAL_SKILL_MD has no fences, no numbered steps, no list bullets,
        # no constraint markers, no MUST/must, no 2+ numbered-step sections.
        # add_trailing_garbage is always applicable; paraphrase_heading is
        # applicable (one H1); delete_section needs a depth>=2 heading which
        # MINIMAL_SKILL_MD does NOT have.
        out = enumerate_mutations(MINIMAL_SKILL_MD, num=20, rng=random.Random(1))
        self.assertGreater(len(out), 0)
        self.assertLess(len(out), 20)
        # add_trailing_garbage should always be in the result.
        kinds = {k for k, _ in out}
        self.assertIn("add_trailing_garbage", kinds)

    def test_num_zero_returns_empty(self) -> None:
        out = enumerate_mutations(RICH_SKILL_MD, num=0, rng=random.Random(0))
        self.assertEqual(out, [])

    def test_negative_num_raises(self) -> None:
        with self.assertRaises(ValueError):
            enumerate_mutations(RICH_SKILL_MD, num=-1, rng=random.Random(0))


# --- calibrate_skill --------------------------------------------------------


def _write_rich_skill(tmp_root: Path, name: str = "example-skill") -> Path:
    """Materialize a skill dir under tmp_root with the RICH fixture as SKILL.md."""
    skill_dir = tmp_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(RICH_SKILL_MD, encoding="utf-8")
    return skill_dir


class CalibrateSkillTest(unittest.TestCase):
    def _calibrate(
        self,
        score_fn,
        *,
        num_mutations: int = 5,
        threshold: float = DEFAULT_CATCH_RATE_THRESHOLD,
    ) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = _write_rich_skill(Path(tmpdir))
            return calibrate_skill(
                skill_dir,
                score_fn,
                num_mutations=num_mutations,
                threshold=threshold,
                rng=random.Random(5),
            )

    def test_all_caught_returns_ok(self) -> None:
        # baseline 0.5; every mutation 0.1 -> caught for all -> catch_rate 1.0.
        def score_fn(content: str) -> float:
            return 0.1 if content != RICH_SKILL_MD else 0.5

        result = self._calibrate(score_fn, num_mutations=5)
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(result["catch_rate"], 1.0)
        self.assertEqual(result["baseline_score"], 0.5)
        for mutation in result["mutations"]:
            self.assertTrue(mutation["caught"])

    def test_none_caught_returns_broken(self) -> None:
        # Constant 0.5 for everything -> bad mutations tie baseline (not strict
        # less-than) -> not caught -> catch_rate 0.0.
        def score_fn(_content: str) -> float:
            return 0.5

        result = self._calibrate(score_fn, num_mutations=5)
        self.assertEqual(result["verdict"], GRADER_BROKEN_CRASH_CLASS)
        self.assertEqual(result["catch_rate"], 0.0)
        for mutation in result["mutations"]:
            self.assertFalse(mutation["caught"])

    def test_at_threshold_boundary_passes(self) -> None:
        # Exactly 7 of 10 mutations catch (catch_rate == 0.70 == threshold);
        # strict-greater-than-equal means verdict=ok.
        counter = {"i": 0}

        def score_fn(content: str) -> float:
            if content == RICH_SKILL_MD:
                return 0.8
            counter["i"] += 1
            # First 7 calls catch (return below 0.8); last 3 do not.
            return 0.3 if counter["i"] <= 7 else 0.9

        result = self._calibrate(score_fn, num_mutations=10, threshold=0.70)
        # The fixture is rich enough to enumerate 10 mutations.
        self.assertEqual(len(result["mutations"]), 10)
        self.assertEqual(result["catch_rate"], 0.7)
        self.assertEqual(result["verdict"], "ok")

    def test_just_below_threshold_returns_broken(self) -> None:
        counter = {"i": 0}

        def score_fn(content: str) -> float:
            if content == RICH_SKILL_MD:
                return 0.8
            counter["i"] += 1
            return 0.3 if counter["i"] <= 6 else 0.9

        result = self._calibrate(score_fn, num_mutations=10, threshold=0.70)
        self.assertEqual(len(result["mutations"]), 10)
        self.assertEqual(result["catch_rate"], 0.6)
        self.assertEqual(result["verdict"], GRADER_BROKEN_CRASH_CLASS)

    def test_score_fn_exception_treated_as_not_caught(self) -> None:
        # score_fn raises for half the mutations; raised → not caught.
        counter = {"i": 0}

        def score_fn(content: str) -> float:
            if content == RICH_SKILL_MD:
                return 0.5
            counter["i"] += 1
            if counter["i"] % 2 == 0:
                raise RuntimeError("simulated grader crash")
            return 0.1

        result = self._calibrate(score_fn, num_mutations=6, threshold=0.99)
        # Even-numbered calls raised → 3 of 6 not caught.
        not_caught = [m for m in result["mutations"] if not m["caught"]]
        caught = [m for m in result["mutations"] if m["caught"]]
        self.assertEqual(len(caught), 3)
        self.assertEqual(len(not_caught), 3)
        for m in not_caught:
            self.assertIsNotNone(m["error"])
            self.assertIn("RuntimeError", m["error"])

    def test_reason_string_contains_count_and_percentage(self) -> None:
        def score_fn(content: str) -> float:
            return 0.1 if content != RICH_SKILL_MD else 0.5

        result = self._calibrate(score_fn, num_mutations=4)
        # Should contain "N/M" and a percentage marker for operator at-a-glance.
        self.assertIn(f"{4}/{4}", result["reason"])
        self.assertIn("%", result["reason"])
        # And the threshold comparison phrasing.
        self.assertTrue(
            "ok" in result["verdict"] or GRADER_BROKEN_CRASH_CLASS in result["verdict"]
        )

    def test_missing_skill_md_raises_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "no-skill-md"
            skill_dir.mkdir()
            with self.assertRaises(FileNotFoundError):
                calibrate_skill(skill_dir, lambda c: 0.5)


# --- calibrate_fleet --------------------------------------------------------


class CalibrateFleetTest(unittest.TestCase):
    def test_aggregates_two_ok_one_broken(self) -> None:
        # Set up a synthetic skills_root with 3 skills that each have an
        # evals/evals.json (so auto_discover_skills finds them) + SKILL.md.
        # The injected score_fn maps baseline content -> 0.5 and any mutation
        # -> 0.1, EXCEPT for the third skill where every score is 0.5
        # (every mutation ties baseline -> broken).
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / ".claude" / "skills"
            for name in ("alpha", "beta", "gamma"):
                skill_dir = root / name
                (skill_dir / "evals").mkdir(parents=True, exist_ok=True)
                (skill_dir / "evals" / "evals.json").write_text("{}", encoding="utf-8")
                (skill_dir / "SKILL.md").write_text(RICH_SKILL_MD, encoding="utf-8")

            def score_fn(content: str) -> float:
                # NB: cannot key on skill name from inside score_fn because the
                # signature only gets content; instead we use a flag in the
                # content. Use the third skill's name as a marker by re-writing
                # one skill's SKILL.md with an embedded marker.
                if "GAMMA_MARKER" in content:
                    return 0.5  # baseline AND any mutation → 0.5 → broken
                return 0.1 if content != RICH_SKILL_MD else 0.5

            # Re-write gamma's SKILL.md with the marker so the score_fn can
            # tell which skill it's grading.
            gamma_skill = RICH_SKILL_MD + "\nGAMMA_MARKER\n"
            (root / "gamma" / "SKILL.md").write_text(gamma_skill, encoding="utf-8")

            result = calibrate_fleet(
                score_fn,
                num_mutations=4,
                threshold=DEFAULT_CATCH_RATE_THRESHOLD,
                rng=random.Random(3),
                skills_root=root,
            )

        self.assertTrue(result["fleet"])
        self.assertEqual(result["summary"]["total"], 3)
        self.assertEqual(result["summary"]["calibrated"], 2)
        self.assertEqual(result["summary"]["broken"], 1)
        # per_skill is in auto_discover_skills's sorted order.
        names = [r["skill"] for r in result["per_skill"]]
        self.assertEqual(names, ["alpha", "beta", "gamma"])
        self.assertEqual(result["per_skill"][2]["verdict"], GRADER_BROKEN_CRASH_CLASS)


# --- CLI smoke --------------------------------------------------------------


class CliSmokeTest(unittest.TestCase):
    def test_calibrate_single_skill_cli_emits_valid_json(self) -> None:
        # Build an isolated workspace at <tmpdir>/.claude/skills/example-skill/
        # with the RICH fixture, then invoke the CLI as a subprocess so its
        # argparse path is exercised. The default score_fn (structural-only)
        # is deterministic so this should always exit 0 with valid JSON.
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            # adversarial_calibration.py computes _SKILLS_ROOT relative to its
            # own __file__; running it as a module without copying it would
            # find the real workspace's skills. Easier path: invoke the
            # underlying calibrate_skill via -c so the test stays scoped.
            cmd = [
                sys.executable,
                "-c",
                "import sys, json; "
                f"sys.path.insert(0, {str(SCRIPTS_DIR)!r}); "
                "from adversarial_calibration import calibrate_skill, _default_structural_score_fn; "
                "from pathlib import Path; "
                f"result = calibrate_skill(Path({str(workspace / 'example-skill')!r}), "
                "_default_structural_score_fn, num_mutations=3); "
                "print(json.dumps(result))",
            ]
            skill_dir = workspace / "example-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(RICH_SKILL_MD, encoding="utf-8")

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["skill"], "example-skill")
            self.assertIn("baseline_score", payload)
            self.assertIn("catch_rate", payload)
            self.assertIn("threshold", payload)
            self.assertIn("verdict", payload)
            self.assertIn("mutations", payload)
            self.assertEqual(len(payload["mutations"]), 3)

    def test_main_with_no_args_returns_nonzero(self) -> None:
        # Calling main() with no skill name and no --fleet should fail
        # argparse-validation and exit non-zero. Use the in-process main() so
        # we don't fork.
        rc = main([])
        self.assertNotEqual(rc, 0)

    def test_main_fleet_and_skill_mutually_exclusive(self) -> None:
        rc = main(["--fleet", "session-wrap"])
        self.assertEqual(rc, 2)


# --- Constants surface ------------------------------------------------------


class ConstantsTest(unittest.TestCase):
    def test_default_constants_match_plan(self) -> None:
        # Lock the defaults documented in the module docstring + SKILL.md so a
        # future change has to be deliberate (and re-document).
        self.assertEqual(DEFAULT_NUM_MUTATIONS, 10)
        self.assertEqual(DEFAULT_CATCH_RATE_THRESHOLD, 0.70)
        self.assertEqual(GRADER_BROKEN_CRASH_CLASS, "grader-broken-for-skill")
        self.assertEqual(len(MUTATION_KINDS), 10)


# --- Module-level invariants (regression guards) ----------------------------


class SkillsRootResolutionTest(unittest.TestCase):
    """Pin the workspace-layout invariant for ``_SKILLS_ROOT``.

    Catches the off-by-one drift that bit ``generate_bad_examples.py`` Step 8
    (``parents[3]`` resolved to ``.claude`` instead of the workspace root, so
    ``_SKILLS_ROOT`` evaluated to a nonexistent ``.claude/.claude/skills``).
    Iter-2 fixes both modules to use ``parents[2]`` directly; this test pins
    the fix.
    """

    def test_skills_root_resolves_to_real_directory(self) -> None:
        self.assertTrue(
            adversarial_calibration._SKILLS_ROOT.is_dir(),
            f"_SKILLS_ROOT does not exist: {adversarial_calibration._SKILLS_ROOT}",
        )
        self.assertEqual(adversarial_calibration._SKILLS_ROOT.name, "skills")
        self.assertEqual(adversarial_calibration._SKILLS_ROOT.parent.name, ".claude")


# --- Fleet auto-discover default-arg coverage -------------------------------


class CalibrateFleetAutoDiscoverDefaultTest(unittest.TestCase):
    """Exercise the default-arg path of ``calibrate_fleet`` (skills_root=None).

    The existing ``CalibrateFleetTest::test_aggregates_two_ok_one_broken``
    injects ``skills_root=root`` and bypasses the cross-skill
    ``sys.path.insert`` + ``from generate_bad_examples import auto_discover_skills``
    wiring. This test calls ``calibrate_fleet(score_fn=...)`` with NO
    ``skills_root`` argument so the production import path is exercised end-to-end.
    Catches silent breakage of the cross-skill wiring (the Step 8 path bug
    would have made this fail with ``total == 0``).
    """

    def test_calibrate_fleet_uses_auto_discover_when_skills_root_default(self) -> None:
        def score_fn(content: str) -> float:
            # Cheap stub: 1.0 for baseline, 0.5 for anything different. Half
            # the mutations may be caught depending on layout — verdict isn't
            # what we're testing here, only that auto-discover found skills.
            return 1.0 if "GAMMA_MARKER" in content else 0.5

        result = calibrate_fleet(score_fn=score_fn, num_mutations=1)
        # Production workspace has dozens of scorable skills; if auto-discover
        # silently returned [] (Step 8 path bug shape), total would be 0.
        self.assertGreaterEqual(result["summary"]["total"], 1)
        self.assertTrue(result["fleet"])
        self.assertEqual(
            result["summary"]["total"],
            result["summary"]["calibrated"] + result["summary"]["broken"],
        )


# --- Constraint-marker word-boundary regression -----------------------------


class ConstraintLineWordBoundaryTest(unittest.TestCase):
    """Pin word-boundary semantics for ``_mutate_remove_constraint_line``.

    Iter-1 used case-sensitive substring matching, so "Neverending story"
    matched the "never" marker, "I love mustard" matched "must", and so on.
    Iter-2 replaces the substring scan with ``\\b<marker>\\b`` + ``re.IGNORECASE``.
    """

    def test_remove_constraint_line_respects_word_boundaries(self) -> None:
        # SKILL.md with three lines where the constraint markers appear ONLY
        # as substrings of larger words (no word-boundary match). With the
        # iter-1 case-sensitive substring scan, "mustard" matched "must",
        # "Neverending" matched "never", "prerequiredness" matched "required".
        # Iter-2's ``\b<marker>\b`` regex must NOT flag any of these — so the
        # mutation should raise MutationNotApplicable.
        no_real_constraints = (
            "# Tiny\n"
            "\n"
            "Neverending story is a great film.\n"
            "I love mustard on my sandwich.\n"
            "The prerequiredness flag was deprecated.\n"
        )
        with self.assertRaises(MutationNotApplicable):
            apply_mutation(
                no_real_constraints, "remove_constraint_line", random.Random(0)
            )

    def test_remove_constraint_line_still_matches_real_constraints(self) -> None:
        # Sanity-check: a SKILL.md with REAL constraint markers (as words)
        # should still trigger the mutation. Prevents the word-boundary fix
        # from over-tightening and accidentally disabling the mutator.
        with_real_constraints = (
            "# Tiny\n\nYou MUST do the right thing.\nDo not skip the steps.\n"
        )
        out = apply_mutation(
            with_real_constraints, "remove_constraint_line", random.Random(0)
        )
        self.assertNotEqual(out, with_real_constraints)
        self.assertLess(len(out.splitlines()), len(with_real_constraints.splitlines()))


if __name__ == "__main__":
    unittest.main()
