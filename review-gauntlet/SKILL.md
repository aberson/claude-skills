---
name: review-gauntlet
description: Four-pass code review gauntlet. Takes a developer prompt and code diff, then spawns four parallel sub-agent reviewers (correctness, bugs, test quality, style/conventions). Use after a developer agent produces a diff, or any time you want a thorough multi-lens review.
user-invocable: true
---

# Review Gauntlet

Run four independent review passes over a code diff in parallel. Each pass uses a
dedicated sub-agent so the reviews are isolated and unbiased by each other.

---

## Inputs

The invoker must provide two things:

1. **Prompt** — the developer's intent (what the diff is supposed to accomplish).
2. **Diff** — the code diff to review. Can be provided as:
   - A `git diff` output (staged, unstaged, or between commits)
   - A PR number (the skill will fetch the diff via `gh pr diff`)
   - An explicit paste of the changed code

If the user doesn't provide these, ask for them before proceeding.

---

## Gathering context

Before spawning reviewers, collect the inputs:

```bash
# If a PR number is given:
gh pr diff <NUMBER>

# If reviewing staged changes:
git diff --cached

# If reviewing working tree:
git diff

# If reviewing a branch vs base:
git diff <base>..HEAD
```

Also read the surrounding source files that the diff touches so reviewers have
context on existing code patterns and conventions.

---

## The four reviewers

Spawn all four as **parallel sub-agents** using the Agent tool. Each agent receives:
- The developer prompt (intent)
- The full diff
- The content of files touched by the diff (for surrounding context)

**Proof discipline (applies to all four reviewers):** Every finding MUST open with a
concrete citation in the form `<file_path>:<line_number>` or
`<file_path>:<line_start>-<line_end>`. File path without a numeric line is INVALID.

Valid: `src/foo.py:42`, `src/foo.py:10-20`, `tests/test_foo.py:55-72`.
Invalid: `src/foo.py:function_name` (function name is not a line number),
`src/foo.py` (no line), `src/foo.py:test_x` (test name is not a line).

Derive line numbers from the diff's `@@ -X,Y +A,B @@` hunk headers — the `+A` is
the post-image starting line and `+A+B-1` is the last line of the hunk. For
surrounding-code citations (files referenced but not in the diff), read the file
and cite the actual line. A finding without both file AND numeric line is
invalid and will be discarded during aggregation.

Do not state "this could cause a null access" without pointing to the exact line.
Do not state "this breaks existing behavior" without citing the existing code
that would break. Do not state "this test is redundant" without citing the other
test (by file:line) that covers the same behavior.

**Missing-coverage findings** (e.g., "no test exercises X", "needs a float-input
test") MUST cite the file:line of the UNCOVERED production code they would test
— `src/foo.py:42` for an untested branch at that line, not a bare prose
reference. The file:line of the gap, not the file:line of the (nonexistent)
test, is what makes the finding actionable.

**Cross-section dedup:** A single defect (same file:line + same root cause)
belongs in exactly ONE reviewer section. Before emitting a finding, scan the
sections you have already written for an overlapping file:line citation. If one
exists and the root cause is the same, fold the new angle into the existing
finding instead of filing a second one. Pick the section whose lane the defect
best fits — Correctness: intent mismatch; Bugs: latent error or anti-pattern;
Test Quality: test-shape issue; Style: naming/convention deviation. Do not echo
the same defect across multiple sections even when it touches multiple lanes;
note any cross-lane angle inline within the chosen section's finding.

### 1. Correctness Reviewer

> Given the stated intent, does this diff actually accomplish what it claims to?

Check for:
- Logic that doesn't match the described goal
- Missing edge cases that the prompt implies should be handled
- Incomplete implementations (TODO left behind, partial feature)
- Off-by-one errors, wrong operator, inverted condition
- Changes that silently break existing behavior not covered by the prompt

Output: list of findings, each with file, line range, and explanation.
If no issues: "No correctness issues found."

### 2. Bug Reviewer

> Ignoring intent — does this diff introduce bugs?

Check for:
- Null/undefined access, unhandled exceptions
- Resource leaks (open files, connections, listeners)
- Race conditions, deadlocks, or shared mutable state issues
- Type mismatches or implicit coercions that lose data
- Security issues (injection, path traversal, unvalidated input at boundaries)
- Broken error propagation (swallowed exceptions, wrong error type)

**Three high-priority anti-patterns** that ship past unit tests because each test
mocks the boundary it would have asserted on. Grep for these explicitly on every
diff that touches a loop, a producer/consumer chain, or persistent storage:

1. **Silent exception fallthrough in a loop.** If the diff has a `try/except` (or
   `try/catch`) inside a `for`/`while` loop, read the code BELOW the try block. If
   any code below the try assumes the work in the try succeeded — reads a result,
   advances state, saves a checkpoint, increments a counter — that is a finding.
   The catch path must either re-raise, or set a `failed = True` flag and `continue`
   before the success-path code. **Severity: HIGH** because the failure mode is
   "the loop runs forever silently producing wrong output." Example shape that's
   almost always wrong:

       for item in items:
           try:
               result = expensive_op(item)
           except Exception:
               log.exception("crashed")
               # NOTHING ELSE — falls through
           # BUG: this runs even when expensive_op crashed
           save_checkpoint(result)
           advance_curriculum(result)

2. **Duplicate shape constants.** If the diff introduces a literal that defines the
   shape of data — `Discrete(N)`, `Box(shape=(N,))`, a list of column names, an
   action enum, a feature dimension, a schema definition — grep the diff's
   transitive imports for the same value or name. If it exists in two places, that
   is a finding. The fix is single-source-of-truth: pick a leaf module that both
   sites can import from, define the constant there once, import it from both
   sides. Tests should assert object identity (`is`), not just value equality
   (`==`), so a future re-introduction of a duplicate copy fails CI even if the
   values happen to match at first. **Severity: HIGH** because producer/consumer
   drift is invisible to unit tests with mocks. Examples: a model's hardcoded
   `Discrete(5)` paired with an env's `Discrete(6)`; an `_ACTION_TO_STATE` list in
   one module with 5 entries and the canonical list elsewhere with 6.

3. **CREATE TABLE without migration.** If the diff modifies a SQL `CREATE TABLE`
   statement (adding a column, changing a type, adding a constraint) AND that
   table is opened against EXISTING database files in production, the diff must
   ALSO add migration code that ALTERs existing tables. SQLite's
   `CREATE TABLE IF NOT EXISTS` is a no-op for existing tables — it does NOT add
   new columns. This is also true for any persistent format with a versioned
   schema (pickled state, JSON files with structured shape, protobuf, etc.). The
   diff should include either an explicit migration call OR a generic migration
   walker that compares declared columns to live columns and ALTERs the diff.
   **Severity: HIGH** because the bug only fires against pre-existing databases,
   not the empty test fixtures unit tests create.

Output: list of findings, each with file, line range, severity (high/medium/low),
and explanation. If no issues: "No bugs found." For the three anti-patterns above,
include "anti-pattern: <name>" in the finding so it's grep-able.

### 3. Test Quality Reviewer

> Are the tests asking specific, valuable questions? Which tests should be deleted?

This reviewer's goal is to **trim**, not add. Check for:
- Tests that assert implementation details rather than behavior
- Duplicate tests that verify the same invariant in different words
- Tests with vague or tautological assertions (e.g., `assert result is not None`
  when the function can never return None)
- Tests that mock so heavily they test nothing real
- Tests that would pass even if the feature were completely broken
- Missing test: a critical behavior the diff introduces that has zero coverage
  (only flag if clearly important — do not request tests for trivial code)

Output for each test: keep / delete / rewrite, with a one-line reason.
If all tests are good: "All tests are focused and valuable."

### 4. Style and Conventions Reviewer

> Does this diff follow the conventions already present in the surrounding code?

Read the existing files touched by the diff. Check for:
- Naming conventions (casing, prefixes, suffixes) that the diff breaks
- Import ordering or grouping that differs from neighbors
- Error handling patterns (e.g., surrounding code raises, diff returns None)
- Structural patterns (e.g., surrounding code uses dataclasses, diff uses raw dicts)
- Comment style, docstring format if the file already has a convention
- Line length, formatting patterns if not enforced by a formatter

Do NOT apply generic "best practices." Only flag deviations from the **actual
conventions in the surrounding code**.

Output: list of deviations with file, line, convention observed in surrounding
code, and what the diff does differently. If consistent: "Diff follows existing
conventions."

**Optional local-judge offload (switchboard, INERT BY DEFAULT).** The Style reviewer is the
ONLY one of the four cheap enough to route to a local model (offload-scan task_class
`review-gauntlet-style`; Switchboard Decision 9). The Correctness, Bug, and Test-Quality
reviewers are deep-reasoning drift-catchers (`code-quality.md`) and ALWAYS stay on Claude —
never route them local. The Style offload is **off unless switchboard offload is enabled for
`review-gauntlet-style`**. When enabled, dispatch the Style reviewer's judgment through the
switchboard judge entrypoint:
`python -m switchboard judge --site review-gauntlet-style --prompt-file <style-reviewer-prompt-file>`
(prints one JSON object, always exits 0). On a **verdict**, treat it as the Style reviewer's
ADVISORY result. On a **defer** (`{"defer": true, ...}`) — ALWAYS returned when offload is
off, the slice is disabled, or the model is down/slow/wrong-shaped — fall back to the Claude
Style reviewer above. When offload is OFF (the default), the entrypoint returns a defer
immediately with NO network call, so the Style reviewer runs on Claude **exactly as before**.
Critically: a local Style verdict is **advisory only** — the Aggregation step's Claude final
judge (below) makes the pass/fail decision, so the local model is never the gate (Decision 3).

---

## Aggregation

**This step is the Claude final judge — the consolidating gate (Switchboard Decision 9).**
The four reviewers ADVISE; this aggregation makes the single pass/fail call, and it ALWAYS
runs on Claude. When the Style reviewer's findings came from the local-judge offload above
(a `review-gauntlet-style` verdict), they enter here as advisory input only: Claude reads the
local Style verdict alongside the three Claude reviewers and decides the gate. The local model
never sets the verdict directly — if its Style advice would flip the gate on its own, Claude
re-examines the underlying diff before accepting it. This keeps the weak model off the gate
(Decision 3) even when its Style advice is in play.

After all four agents return, compile a single report:

```
## Review Gauntlet Results

### Correctness
<findings or "No issues">

### Bugs
<findings or "No bugs found">

### Test Quality
<per-test verdicts or "All tests are focused and valuable">

### Style & Conventions
<findings or "Diff follows existing conventions">

---

**Verdict: PASS / NEEDS WORK**
```

Verdict logic:
- **PASS** — no findings across any reviewer, or only minor style notes
- **NEEDS WORK** — any correctness issue, any medium/high bug, any test flagged
  for deletion, or significant convention deviations

If NEEDS WORK, end with: "Want me to fix these issues, or discuss any findings first?"

---

## What NOT to do

- Do not suggest new features or refactors beyond what the diff touches
- Do not flag style issues based on generic best practices — only flag deviations
  from the actual surrounding code
- Do not request new tests for trivial getters, simple delegation, or boilerplate
- Do not re-review the same issue in multiple reviewers — each has its own lane
- Do not block on minor style issues — they don't make the verdict NEEDS WORK alone
