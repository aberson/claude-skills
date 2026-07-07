---
name: test-prune
description: Audit a project's test suite for redundant, trivial, or mock-theater tests; relocate the ones that are the only coverage for a behavior; delete the rest. Use after a project has accumulated drift from many build phases, or when tests slow down the dev loop with no payoff. Read-only by default until cleanup phase.
user-invocable: true
---

# test-prune

Audit and trim a test suite. Finds tests that duplicate other coverage, test stdlib behavior, or only assert that a mock was called. Verifies before removing — a test cannot be declared redundant without showing the other test that covers the same behavior.

Run this skill when:
- A project has shipped several build phases and the test suite has grown faster than the source tree.
- Test runs are slow and a chunk of the slowness is integration tests that re-cover unit-test scenarios.
- The user says "prune the tests", "clean up the test suite", or "the integration tests are redundant".

This skill does NOT touch application code, README, plan docs, or git state. It edits tests/, runs the test gate, and reports.

---

## Phase 1 — Identify candidates

Always dispatch this phase as parallel Explore agents — never as a serial in-line scan, even for small test suites. Launch 1–3 parallel Explore agents (scale agent count to test-file count: 1 agent for ≤5 files, 2 for 6–20, 3 for >20) to read every test file under `tests/` (or the project's test directory) and flag:

1. **Redundant tests** — same behavior tested in multiple files (especially integration tests that duplicate unit tests).
2. **Trivial tests** — testing stdlib behavior (dict keys exist, dataclass defaults, `Path.mkdir()` works).
3. **Mock theater** — tests that only assert a mock was called, with no real logic under test.
4. **Duplicate coverage** — integration file that re-tests every unit-test scenario.

Return one list of `(file:line, category, brief)` tuples per Explore agent — not full transcripts.

---

## Phase 2 — Verify before removing

For each flagged test, check: **is this the only coverage for this behavior?**

Use `grep` to find if the function/class under test is tested elsewhere. **Cite every search result** — show the grep command and match count. A test cannot be declared "redundant" without showing the other test that covers the same behavior (file:line). A test cannot be declared "trivial" without quoting the assertion that proves it tests nothing meaningful.

Common false positives:
- A function tested only in an integration file — relocate, don't delete.
- Error-handling paths tested only via mocks — keep (prevents crash regressions).
- Wiring tests that look like unit-test duplicates but test the glue code.

Output a triage table to the user before any deletion:

| File:line | Category | Verdict | Evidence |
|---|---|---|---|
| `tests/test_foo.py:42` | redundant | delete | duplicated by `tests/unit/test_foo.py:80` (same input, same assertion) |
| `tests/test_bar.py:15` | trivial | delete | asserts `dict["k"] == "v"` after `dict["k"] = "v"` |
| `tests/integration/test_baz.py:120` | redundant | relocate | only coverage for `baz.compute()` — move to `tests/unit/test_baz.py` |
| `tests/test_qux.py:30` | mock theater | **keep** | wraps real `qux.dispatch()` call; mock asserts post-condition not call |

Stop and wait for explicit confirmation before executing. The triage table is the artifact — the user owns the verdict.

---

## Phase 3 — Execute cleanup

Once the user confirms:

1. **Relocate** tests that are the only coverage for a function (move to the appropriate unit test file).
2. **Delete** genuinely redundant/trivial tests.
3. **Run the project's test command** to verify nothing broke. Adapt to the project (`uv run pytest`, `npm test`, `pnpm test`, etc.).
4. **Run lint/typecheck** to verify no import errors from deletions.

If any gate fails, halt and surface the failure with the deletion that most likely caused it. Don't try to "fix forward" — the user opted into a pruning pass, not a refactor.

---

## Phase 4 — Report

```text
test-prune complete.

Before: X test files, Y tests
After:  X' test files, Y' tests
Removed: N tests (K files deleted)
Relocated: M tests (J files moved)

Quality gates: Y'/Y' tests · 0 type errors · 0 lint violations
```

---

## What NOT to do

- Do not remove tests without verifying coverage isn't lost (Phase 2 is mandatory).
- Do not rewrite application code — this skill is tests-only.
- Do not update README, plan docs, or memory.
- Do not commit, push, or create GitHub issues — that's `/repo-update`'s job.
- Do not delete a "trivial" test without quoting the assertion in the triage table.
- Do not auto-execute deletions — the triage table is the gate.

---

## See also

- [`/repo-update`](../repo-update/SKILL.md) — end-of-phase commit + push. Run this after `/test-prune` if you want the cleanup landed.
- [`.claude/rules/code-quality.md`](../../rules/code-quality.md) § "New components require an integration test through the production caller" — context on which tests are load-bearing and should not be pruned.
