"""Self-contained unit tests for structural_metrics.

Covers per-metric behavior on constructed inputs, the integration assertion
that the well-structured fixture out-scores the degraded fixture, and a CLI
smoke that the JSON-output shape is as documented.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from structural_metrics import (
    DEFAULT_BANNED_PHRASES,
    DEFAULT_MAX_LINE_LENGTH,
    DEFAULT_REQUIRED_SECTIONS,
    StructuralScore,
    main,
    metric_banned_phrases,
    metric_code_fence_balance,
    metric_cross_reference_resolution,
    metric_link_integrity,
    metric_max_line_length,
    metric_required_sections,
    metric_rules_to_rationale_ratio,
    metric_section_depth_consistency,
    score_skill,
)


SCRIPTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = SCRIPTS_DIR / "fixtures"


class SectionDepthConsistencyTest(unittest.TestCase):
    def test_h4_under_h2_is_a_violation(self) -> None:
        text = "## Section\n\n#### Deep\n\nbody\n"
        result = metric_section_depth_consistency(text)
        self.assertEqual(result["violations"], 1)
        self.assertLess(result["score"], 1.0)

    def test_h4_under_h3_is_fine(self) -> None:
        text = "## Section\n\n### Sub\n\n#### Deep\n\nbody\n"
        result = metric_section_depth_consistency(text)
        self.assertEqual(result["violations"], 0)
        self.assertEqual(result["score"], 1.0)

    def test_h1_followed_by_h4_is_not_violation(self) -> None:
        # Strict rule: only H2→H4 (skipping H3) is a violation. H1→H4 is fine,
        # as is H4 at the very top of a doc with no preceding H2/H3.
        text = "# Title\n\n#### Detail\n\nbody\n"
        result = metric_section_depth_consistency(text)
        self.assertEqual(result["violations"], 0)
        self.assertEqual(result["score"], 1.0)


class RequiredSectionsTest(unittest.TestCase):
    def test_all_present_scores_one(self) -> None:
        text = "## Steps\n\n## Constraints\n\n## Limitations\n"
        result = metric_required_sections(text, list(DEFAULT_REQUIRED_SECTIONS))
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["missing"], [])

    def test_partial_presence_scores_fraction(self) -> None:
        text = "## Steps\n\n## Other\n"
        result = metric_required_sections(text, ["Steps", "Constraints", "Limitations"])
        self.assertAlmostEqual(result["score"], 1.0 / 3.0)
        self.assertEqual(result["missing"], ["Constraints", "Limitations"])

    def test_empty_required_list_is_passing(self) -> None:
        result = metric_required_sections("anything\n", [])
        self.assertEqual(result["score"], 1.0)

    def test_required_sections_case_insensitive(self) -> None:
        # Lowercase heading should match capitalized requirement.
        result = metric_required_sections("## steps\n", ["Steps"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["present"], ["Steps"])
        # Trailing colon on heading should also match.
        result = metric_required_sections("## Steps:\n", ["Steps"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["present"], ["Steps"])

    def test_required_sections_neutral_when_no_config_and_no_defaults(self) -> None:
        # When caller did NOT opt in via config AND none of the defaults
        # appear, the metric should return score=1.0 with no_config marker.
        # This stops dragging down skills that don't follow the default
        # section-name convention.
        text = "# Some Skill\n\n## Overview\n\nbody only, no Steps/Constraints/Limitations\n"
        result = metric_required_sections(
            text, list(DEFAULT_REQUIRED_SECTIONS), from_config=False
        )
        self.assertEqual(result["score"], 1.0)
        self.assertTrue(result.get("no_config"))

    def test_required_sections_penalizes_when_config_supplied(self) -> None:
        # Inverse of the neutral-default case: when from_config=True, a fully
        # missing required list scores 0.0 — the skill opted in and failed.
        text = "no required sections here\n"
        result = metric_required_sections(
            text, ["Steps", "Constraints"], from_config=True
        )
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["missing"], ["Steps", "Constraints"])


class BannedPhrasesTest(unittest.TestCase):
    def test_no_hits_scores_one(self) -> None:
        result = metric_banned_phrases("clean prose\n", list(DEFAULT_BANNED_PHRASES))
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["total_hits"], 0)

    def test_case_insensitive_phrase_count(self) -> None:
        text = "As an AI I think this is fine. I CANNOT proceed.\n"
        result = metric_banned_phrases(text, list(DEFAULT_BANNED_PHRASES))
        # 3 phrases (as an AI, I think, I cannot) all matched once each.
        self.assertEqual(result["total_hits"], 3)
        self.assertLess(result["score"], 1.0)

    def test_should_overuse_counts_as_one_extra_hit(self) -> None:
        # 11 'should' occurrences > threshold (10) triggers +1.
        text = " ".join(["you should do it"] * 11) + "\n"
        result = metric_banned_phrases(text, [])
        self.assertEqual(result["should_count"], 11)
        self.assertEqual(result["total_hits"], 1)

    def test_phrases_in_code_fences_are_ignored(self) -> None:
        text = "```python\n# As an AI I think this is code\n```\nclean prose\n"
        result = metric_banned_phrases(text, list(DEFAULT_BANNED_PHRASES))
        self.assertEqual(result["total_hits"], 0)


class LinkIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.skill_md = self.root / "SKILL.md"

    def test_external_urls_are_not_checked(self) -> None:
        self.skill_md.write_text(
            "[anthropic](https://anthropic.com) [mail](mailto:x@y) [anchor](#section)\n",
            encoding="utf-8",
        )
        result = metric_link_integrity(self.skill_md.read_text(encoding="utf-8"), self.skill_md)
        self.assertEqual(result["total_relative_links"], 0)
        self.assertEqual(result["score"], 1.0)

    def test_valid_and_broken_relative_links(self) -> None:
        (self.root / "exists.md").write_text("hi", encoding="utf-8")
        self.skill_md.write_text(
            "[ok](exists.md) [bad](does-not-exist.md)\n", encoding="utf-8"
        )
        result = metric_link_integrity(self.skill_md.read_text(encoding="utf-8"), self.skill_md)
        self.assertEqual(result["total_relative_links"], 2)
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["broken"], ["does-not-exist.md"])
        self.assertAlmostEqual(result["score"], 0.5)

    def test_anchor_in_relative_path_is_stripped(self) -> None:
        (self.root / "page.md").write_text("hi", encoding="utf-8")
        self.skill_md.write_text("[ok](page.md#section)\n", encoding="utf-8")
        result = metric_link_integrity(self.skill_md.read_text(encoding="utf-8"), self.skill_md)
        self.assertEqual(result["valid"], 1)

    def test_link_integrity_url_decoded(self) -> None:
        # [doc](my%20file.md) should resolve against the real `my file.md`.
        (self.root / "my file.md").write_text("hi", encoding="utf-8")
        self.skill_md.write_text("[doc](my%20file.md)\n", encoding="utf-8")
        result = metric_link_integrity(
            self.skill_md.read_text(encoding="utf-8"), self.skill_md
        )
        self.assertEqual(result["total_relative_links"], 1)
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["broken"], [])


class CodeFenceBalanceTest(unittest.TestCase):
    def test_balanced_with_tags_scores_one(self) -> None:
        text = "```bash\nls\n```\n\n```python\nx = 1\n```\n"
        result = metric_code_fence_balance(text)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["unbalanced"], 0)
        self.assertEqual(result["missing_language_tag"], 0)

    def test_missing_tag_deducts(self) -> None:
        text = "```\nno tag\n```\n"
        result = metric_code_fence_balance(text)
        self.assertEqual(result["missing_language_tag"], 1)
        self.assertEqual(result["score"], 0.0)

    def test_unbalanced_fence_deducts(self) -> None:
        text = "```bash\nopen but never closed\n"
        result = metric_code_fence_balance(text)
        self.assertEqual(result["unbalanced"], 1)
        self.assertEqual(result["score"], 0.0)

    def test_unclosed_fence_with_missing_tag_counts_once(self) -> None:
        # Regression: a single unclosed fence with no language tag is ONE
        # issue (the unclosed-ness), not two (unclosed + missing-tag). The
        # prior implementation double-counted; the missing_language_tag
        # bucket should only register for openers we observe being closed.
        text = "```\nopen, untagged, never closed\n"
        result = metric_code_fence_balance(text)
        self.assertEqual(result["total_open_fences"], 1)
        self.assertEqual(result["unbalanced"], 1)
        self.assertEqual(result["missing_language_tag"], 0)
        # Score: 1 - (1 + 0)/1 = 0.0 (one issue, max deduction).
        self.assertEqual(result["score"], 0.0)

    def test_indented_fence_is_not_a_fence(self) -> None:
        # CommonMark: a fence with 4+ leading spaces is part of an indented
        # code block, NOT a fence opener. It must not toggle in_fence state.
        text = "    ```bash\n    ls\n    ```\n"
        result = metric_code_fence_balance(text)
        self.assertEqual(result["total_open_fences"], 0)
        self.assertEqual(result["unbalanced"], 0)
        self.assertEqual(result["score"], 1.0)


class MaxLineLengthTest(unittest.TestCase):
    def test_all_short_scores_one(self) -> None:
        text = "short\nlines\nonly\n"
        result = metric_max_line_length(text, max_len=150)
        self.assertEqual(result["overlong_count"], 0)
        self.assertEqual(result["score"], 1.0)

    def test_overlong_lines_deduct_proportionally(self) -> None:
        long_line = "x" * 160
        text = f"{long_line}\nshort\n"
        result = metric_max_line_length(text, max_len=150)
        self.assertEqual(result["overlong_count"], 1)
        self.assertAlmostEqual(result["score"], 0.5)

    def test_configurable_max_length(self) -> None:
        text = "0123456789\n"
        result = metric_max_line_length(text, max_len=5)
        self.assertEqual(result["overlong_count"], 1)


class CrossReferenceResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.skill_md = self.root / "SKILL.md"

    def test_no_refs_scores_one(self) -> None:
        self.skill_md.write_text("no cross refs here\n", encoding="utf-8")
        result = metric_cross_reference_resolution(
            self.skill_md.read_text(encoding="utf-8"), self.skill_md
        )
        self.assertEqual(result["total_refs"], 0)
        self.assertEqual(result["score"], 1.0)

    def test_resolved_sibling_ref(self) -> None:
        (self.root / "real-slug.md").write_text("hi", encoding="utf-8")
        self.skill_md.write_text("see [[real-slug]] for details\n", encoding="utf-8")
        result = metric_cross_reference_resolution(
            self.skill_md.read_text(encoding="utf-8"), self.skill_md
        )
        self.assertEqual(result["total_refs"], 1)
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["score"], 1.0)

    def test_unresolved_ref_deducts(self) -> None:
        self.skill_md.write_text("see [[nope]] and [[also-nope]]\n", encoding="utf-8")
        result = metric_cross_reference_resolution(
            self.skill_md.read_text(encoding="utf-8"), self.skill_md
        )
        self.assertEqual(result["total_refs"], 2)
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["score"], 0.0)


class RulesToRationaleRatioTest(unittest.TestCase):
    def test_balanced_doc_scores_high(self) -> None:
        # 4 imperative sentences out of 10 eligible lines = ratio 0.4 → score 1.0
        lines = (
            ["Use this script daily.", "Run the build before lunch.",
             "Verify outputs match.", "Check the log file."]  # 4 imperative
            + ["The rationale is that determinism matters.",
               "Sub-agent dispatch costs money in tokens.",
               "Reproducibility outranks novelty here.",
               "Determinism beats novelty for grading.",
               "The grader noise floor is the real risk.",
               "Goodhart pressure is real and observed."]  # 6 rationale
        )
        text = "\n".join(lines) + "\n"
        result = metric_rules_to_rationale_ratio(text)
        self.assertAlmostEqual(result["ratio"], 0.4)
        self.assertAlmostEqual(result["score"], 1.0)

    def test_all_imperative_scores_lower(self) -> None:
        text = "\n".join(["Run x.", "Use y.", "Verify z.", "Check q."]) + "\n"
        result = metric_rules_to_rationale_ratio(text)
        self.assertEqual(result["ratio"], 1.0)
        # ratio 1.0 → |1.0 - 0.4| = 0.6 → 1 - 1.2 = -0.2 → clamped to 0.0
        self.assertEqual(result["score"], 0.0)

    def test_no_eligible_lines_scores_one(self) -> None:
        text = "# Heading only\n\n- bullet\n- bullet\n"
        result = metric_rules_to_rationale_ratio(text)
        self.assertEqual(result["eligible_lines"], 0)
        self.assertEqual(result["score"], 1.0)


class IntegrationFixtureTest(unittest.TestCase):
    """Plan §7 Step 3 Done-when condition: well-structured > degraded composite."""

    def test_well_structured_outscores_degraded(self) -> None:
        well = score_skill(FIXTURES_DIR / "well_structured.md")
        bad = score_skill(FIXTURES_DIR / "degraded.md")
        self.assertIsInstance(well, StructuralScore)
        self.assertIsInstance(bad, StructuralScore)
        self.assertGreater(well.score, bad.score,
                           msg=f"well={well.score:.4f} bad={bad.score:.4f}")
        # Both must be in [0, 1].
        self.assertGreaterEqual(well.score, 0.0)
        self.assertLessEqual(well.score, 1.0)
        self.assertGreaterEqual(bad.score, 0.0)
        self.assertLessEqual(bad.score, 1.0)
        # Every metric reports a score key.
        for name, m in well.metrics.items():
            self.assertIn("score", m, msg=f"metric {name} missing 'score'")

    def test_eight_metrics_reported(self) -> None:
        result = score_skill(FIXTURES_DIR / "well_structured.md")
        self.assertEqual(len(result.metrics), 8)
        expected = {
            "section_depth_consistency",
            "required_sections",
            "banned_phrases",
            "link_integrity",
            "code_fence_balance",
            "max_line_length",
            "cross_reference_resolution",
            "rules_to_rationale_ratio",
        }
        self.assertEqual(set(result.metrics.keys()), expected)


class BOMHandlingTest(unittest.TestCase):
    """Windows PowerShell `Set-Content -Encoding utf8` writes a UTF-8 BOM
    on PS 5.1 (see workspace memory `feedback_set_content_utf8_adds_bom`).
    score_skill must transparently strip the BOM via utf-8-sig so headings
    on line 1 still match the heading regex.
    """

    def test_bom_prefixed_file_headings_still_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_md = Path(tmp) / "SKILL.md"
            # Write BOM (UTF-8 EF BB BF) followed by `## Steps` on line 1.
            content = "## Steps\n\nbody line\n"
            with open(skill_md, "wb") as f:
                f.write(b"\xef\xbb\xbf")
                f.write(content.encode("utf-8"))
            result = score_skill(skill_md, required_sections=["Steps"])
            # If BOM survived as U+FEFF prefix, heading would be "U+FEFF## Steps"
            # and the regex `^(#{1,6})\s+` would fail to match — required_sections
            # would report 0/1 present. With utf-8-sig the BOM is stripped.
            rs = result.metrics["required_sections"]
            self.assertEqual(rs["score"], 1.0, msg=f"required_sections detail: {rs}")
            self.assertEqual(rs["present"], ["Steps"])
            self.assertEqual(rs["missing"], [])


class CrossReferenceHeadingAnchorTest(unittest.TestCase):
    """[[file#section]] should look up `file`, not the literal `file#section`."""

    def test_heading_anchor_slug_strips_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_md = root / "SKILL.md"
            (root / "other-doc.md").write_text("hi", encoding="utf-8")
            skill_md.write_text(
                "see [[other-doc#section-name]] for context\n", encoding="utf-8"
            )
            result = metric_cross_reference_resolution(
                skill_md.read_text(encoding="utf-8"), skill_md
            )
            self.assertEqual(result["total_refs"], 1)
            self.assertEqual(result["resolved"], 1)
            self.assertEqual(result["score"], 1.0)


class CLITest(unittest.TestCase):
    def test_main_emits_valid_json(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(FIXTURES_DIR / "well_structured.md")])
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertIn("score", parsed)
        self.assertIn("metrics", parsed)
        self.assertIsInstance(parsed["score"], float)
        self.assertEqual(len(parsed["metrics"]), 8)

    def test_main_missing_file_returns_3(self) -> None:
        rc = main([str(FIXTURES_DIR / "definitely-not-a-real-file.md")])
        self.assertEqual(rc, 3)

    def test_subprocess_invocation_emits_json(self) -> None:
        """Smoke: real `python structural_metrics.py <path>` end-to-end."""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "structural_metrics.py"),
             str(FIXTURES_DIR / "well_structured.md")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        parsed = json.loads(result.stdout)
        self.assertIn("score", parsed)
        self.assertEqual(len(parsed["metrics"]), 8)


if __name__ == "__main__":
    unittest.main()
