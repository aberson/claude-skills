"""Self-contained unit tests for append_result.append_result."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from append_result import append_result


class AppendResultTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.skill_path = Path(self._tmp.name) / "skills" / "test-skill"
        (self.skill_path / "evals").mkdir(parents=True)
        self.results_path = self.skill_path / "evals" / "results.tsv"

    def test_append_creates_file_with_header_and_row(self) -> None:
        append_result(self.skill_path, "abc1234", 0.85, "keep", "test edit", 5.123)
        self.assertTrue(self.results_path.exists())
        lines = self.results_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "commit\tscore\tstatus\tdescription\twall_seconds")
        self.assertEqual(lines[1], "abc1234\t0.850000\tkeep\ttest edit\t5.123")

    def test_append_null_score_and_crash_status(self) -> None:
        append_result(self.skill_path, "abc1234", 0.85, "keep", "test edit", 5.123)
        append_result(self.skill_path, "xyz5678", None, "crash", "timeout fired", 600.5)
        lines = self.results_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[2], "xyz5678\tNULL\tcrash\ttimeout fired\t600.500")

    def test_invalid_status_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            append_result(self.skill_path, "abc1234", 0.5, "invalid", "x", 1.0)

    def test_description_tabs_and_newlines_replaced_with_space(self) -> None:
        append_result(self.skill_path, "deadbee", 0.5, "keep", "a\tb\nc", 1.0)
        lines = self.results_path.read_text(encoding="utf-8").splitlines()
        # Header on line 0, first data row on line 1.
        fields = lines[1].split("\t")
        self.assertEqual(fields[3], "a b c")

    def test_description_crlf_collapses_to_single_space(self) -> None:
        append_result(self.skill_path, "deadbee", 0.5, "keep", "a\r\nb", 1.0)
        lines = self.results_path.read_text(encoding="utf-8").splitlines()
        fields = lines[1].split("\t")
        self.assertEqual(fields[3], "a b")

    def test_out_of_range_score_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            append_result(self.skill_path, "abc1234", 1.5, "keep", "x", 1.0)
        with self.assertRaises(ValueError):
            append_result(self.skill_path, "abc1234", -0.1, "keep", "x", 1.0)

    def test_nan_score_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            append_result(self.skill_path, "abc1234", float("nan"), "keep", "x", 1.0)
        with self.assertRaises(ValueError):
            append_result(self.skill_path, "abc1234", float("inf"), "keep", "x", 1.0)

    def test_missing_evals_dir_raises_file_not_found(self) -> None:
        # Layout where <skill_path> exists but <skill_path>/evals does NOT.
        bare_skill = Path(self._tmp.name) / "skills" / "no-evals-skill"
        bare_skill.mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):
            append_result(bare_skill, "abc1234", 0.5, "keep", "x", 1.0)

    def test_baseline_status_is_valid(self) -> None:
        append_result(self.skill_path, "baseline", 0.7, "baseline", "initial measurement", 2.0)
        lines = self.results_path.read_text(encoding="utf-8").splitlines()
        fields = lines[1].split("\t")
        self.assertEqual(fields[2], "baseline")


if __name__ == "__main__":
    unittest.main()
