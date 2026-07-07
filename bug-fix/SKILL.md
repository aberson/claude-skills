---
name: bug-fix
description: Diagnose and fix a bug end-to-end with forced primary-source investigation before any code change. Independently reproduces the bug, designs a fix, delegates implementation to build-step, then verifies the original symptom is gone. Built to break the command-paste loop with the user. Invoke as "/bug-fix --symptom '...' [flags]".
user-invocable: true
---

# Bug Fix

Run a bug report end-to-end: investigate, reproduce, design, fix, verify.
Avoid the command-paste loop with the user.
Run diagnostic commands yourself, read logs yourself, and verify CLI
suggestions against argparse before invoking them.
## When to use

Use `/bug-fix` when:
- Something is broken and you want a fix, not just a discussion.
- You have a symptom (log line, error, screenshot) but not a confirmed root
  cause.
- You want the LLM to do the triage instead of pasting commands back and
  forth.

Use something else when:
- The fix is a one-character typo you can do faster yourself.
- You want to discuss the design before committing — use a regular
  conversation.
- The work is forward-feature, not a bug — use `/build-step`.

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--symptom` | yes | -- | What's broken. Quote the error, log line, or describe the misbehavior precisely. |
| `--repro` | no | -- | Command or steps to reproduce. If omitted, the skill derives one from the symptom. |
| `--issue` | no | -- | GitHub issue number to link/close. |
| `--triage` | no | `quick` | `quick` (worktree + reviewers) or `investigate-only` (Diagnosis Block then stop). `full` is accepted as a deprecated synonym for `quick` — the prior TDD-driven `full` mode delegated to `/build-step-tdd`, which was archived 2026-05-24 after 0 invocations. |
| `--review` | no | `code` | `none`, `code` (4-pass review-gauntlet), `auto` (gates only). Applies to both quick and full. |
| `--max-iter` | no | 3 | Max developer iterations inside the delegated build skill. |
| `--skip-verify` | no | false | Skip Step 5 (verify-against-original-repro). DANGEROUS — only use when the repro is too expensive or impossible from the skill's environment (multi-hour soak, hardware-bound, live opponent required). The skill prints a loud warning and records the skip in the final report. |

## Steps

### Step 0 — Pre-flight & memory citation

1. **Detect platform.** Check `$env:OS` / `uname` / git config to identify Windows vs Linux/Mac.
   State the detected platform in chat output ("Platform: Windows 11" or "Platform: Linux").
   Use PowerShell syntax (no `&&`, no `export`, use `$env:VAR`) for user-facing commands on Windows; bash on Linux/Mac.
   Note that the skill's own Bash tool calls are unaffected — this is for commands the user might run.
2. **Cite relevant memory.** Read MEMORY.md AND all project_*.md files in the same memory directory BEFORE Step 1 begins.
   Do this before any diagnostic commands run.
   Do not defer this scan into Step 1; it is a pre-investigation check.
   Check each entry against five categories:
   (1) **symptom keywords** (the exact error text or its component words),
   (2) **file paths** mentioned in the symptom,
   (3) **module names** (Python/JS imports referenced),
   (4) **command/tool names** (the executable that produced the error), and
   (5) **failure-mode patterns** (e.g., `silent`, `encoding`, `corrupt`, `stale path`, `subprocess`, `hang`, `race`).
   Add **every matching entry** by `feedback_*.md` filename inline — no paraphrase, cite all as the default.
   Apply the runaway-match carve-out when ≥10 entries match across all five categories combined:
   cite the most-recent 8 by file mtime plus a one-line footer ``N additional matches truncated, see `grep -l <pattern> <memory-dir>` for full list``.
   If none apply, say so explicitly.
3. **Detect project context.** Stack, test command, lint, typecheck,
   dependency install. Same detection logic as `/build-step` Step 0.
4. **Stash uncommitted changes** (only if `--triage` is `quick` or `full`):
   ```bash
   git status --porcelain
   # If changes exist:
   git stash push -m "fix-bug pre-run state" --include-untracked
   ```

### Step 1 — Investigation (forced; output is a Diagnosis Block, not a fix)

Do not skip this step. Output structured diagnosis with primary-source citations.

1. **Read the symptom carefully.** Note that a log line, error message, or file path in the symptom is the entry point.
2. **Pull primary sources directly:**
   - Error message → grep for the exact string in source.
   - Log line → grep for the format string that would produce it.
   - Misbehavior → read the code path that should handle it (don't guess
     from name — read it).
   - CLI failure → read the script's argparse and confirm the flag/module
     path exists. **Never invoke a command without verifying its argparse
     first** — covers the rename-trap (e.g., `alpha4gate.runner` →
     `bots.v0.runner`).
3. **Run diagnostic commands yourself with the Bash tool.** Do NOT ask the
   user to paste output for things you can run.
4. **For commands that must run on the user's interactive terminal** (GUI app, SC2 client, anything platform-bound):
   Write the verified PowerShell command.
   Use Write-then-`bash <path>` for WSL multi-line scripts (inline `bash -lc 'multi-line'` is unreliable).
   Always quote `/mnt/c/...` args from Git Bash inside `bash -lc '...'` to prevent MSYS rewrite.
5. **Reproduce the bug.** Run `--repro` if given; else derive one (the failing test, the failing endpoint, the code path) and run that.
   Write the bad output verbatim — Step 5 compares against this exact text.

Use the Diagnosis Block as an **output gate**, not just a template.
Do not mark Step 1 done until all six required fields are filled:
**Symptom**, **Reproduction**, **Primary sources**, **Suspected root
cause**, **Confidence**, and **Memory entries that apply**.

Write after Step 1:

```markdown
## Diagnosis

**Symptom (verbatim from input or observed):**
<exact text>

**Reproduction:**
$ <command>
<observed output, quoted>

**Primary sources:**
- <file:line>: `<code snippet>`
- <log file:line>: `<log line>`
- <argparse line>: `<flag/module>`

**Suspected root cause:**
<paragraph with file:line citations inline>

**Confidence:** high | medium | low

**Ruled out (when applicable):**
- <hypothesis 1> — <why ruled out, with file:line evidence>
- <hypothesis 2> — <why ruled out, with file:line evidence>

**Memory entries that apply:**
- `<feedback_*.md>` — <one-line gloss>
```

Stop on `--triage investigate-only`: hand to user.

### Step 2 — Independent reproduction (always)

Run an Explore sub-agent in parallel and give it the symptom and repro
instructions, but **NOT** the suspected root cause.
Pass it one job: come to its own conclusion, then we compare:
- Diagnoses match → confidence becomes high, proceed; **but matching
  MEDIUM confidence does NOT upgrade to high**.
  Mark the combined confidence as medium.
- Diverge → do not proceed to Step 3. First classify the divergence shape,
  then present a Diagnosis Comparison block.
  Apply one of the four resolution options below.
  Never synthesize a hybrid third diagnosis.

Write a Diagnosis Comparison block when diagnoses diverge:

```markdown
## Diagnosis Comparison

**Orchestrator:** <root cause: file:line — mechanism; confidence>
**Independent sub-agent:** <root cause: file:line — mechanism; confidence>
**Divergence type:** <one of the four shapes below>
```

Mark the divergence as one of four shapes before choosing a
resolution:
- **Different file:line** — different root cause at a different code
  location.
- **Same location, different mechanism** — same code site, different
  theory about why it fails.
- **Same root cause, different confidence** — agreement on what,
  disagreement on how sure.
- **One can reproduce, the other cannot** — reproduction divergence is
  itself a real diagnostic.

Apply one resolution:
1. **Re-investigate** — run diagnostic commands targeting the divergence point itself.
   Re-grep the contested file, re-read the contested code, re-run the repro with extra logging.
   Apply when divergence is "different file:line" or "same location, different mechanism" and one extra command might resolve it.
2. **Surface to user** — present both diagnoses side-by-side using the
   Diagnosis Comparison block above and ask the user to disambiguate
   using domain knowledge the LLMs lack. Best when re-investigation has
   not yielded convergence after one extra round, or the divergence
   requires domain-specific intuition.
3. **Proceed with confidence marked low/medium** — only when the
   divergence is minor (same mechanism, different call site; or same
   root cause, different confidence) and the fix design is robust to
   either interpretation. The Diagnosis Block's **Confidence** field
   must be set to low/medium and the Fix Design's **Risk** field must
   explicitly acknowledge the divergence.
4. **Tie-breaker third sub-agent** — only after Option 1 re-investigation
   has been tried and the two diagnoses still diverge. Spawn a FRESH
   sub-agent given only the symptom + repro instructions and NEITHER
   prior diagnosis (same constraint as Step 2's original independent
   sub-agent). Its independent verdict breaks the tie or confirms the
   divergence is genuine (in which case escalate to Option 2 — surface
   to user — with all three diagnoses laid out).

### Step 3 — Fix design (no code yet)

Write output:

```markdown
## Fix Design

**Change:** <one paragraph on what changes>
**Files touched:** <list with line ranges>
**Regression test:** <path, what it asserts, how it would fail today>
**Risk:** <what else this could break, why it won't>
**Rollback:** <how to undo>
```

Confirm the design with the user before delegating to Step 4.

### Step 4 — Implement (delegate)

Build a combined problem statement from the Diagnosis Block + Fix Design
Block.
Write the full combined text inline in your chat output before invoking
the delegated skill.
Do NOT collapse the blocks to a placeholder like `<combined problem>` or
`<Diagnosis Block from Step 1>`.
Ensure the actual prose of the Diagnosis and Fix Design blocks appears in
the message so the user sees the prompt the developer agent will receive.
Template:

```markdown
PROBLEM (bug fix):

<Diagnosis Block from Step 1>

<Fix Design Block from Step 3>

REQUIREMENTS:
- Add the regression test described in the Fix Design Block. The test must
  fail against the current code (before the fix is applied).
- Implement the fix described in the Fix Design Block.
- Touch only the files listed under "Files touched"; if you need to touch
  another file, stop and report why.
- Make surgical edits, not whole-file rewrites: in a multi-step phase,
  whole-file rewrites overwrite shared files modified by prior steps and
  cause worktree merge conflicts (see `feedback_buildphase_worktree_merge.md`;
  rule-file home: `.claude/rules/worktree-hygiene.md § "Shared-file merges across steps"`).
```

Delegate to `/build-step` (both `quick` and the deprecated `full` synonym
route here):

```bash
/build-step --problem "<combined problem>" --reviewers <--review value> --max-iter <--max-iter> [--issue <N>]
```

Stop on `/build-step` BLOCKED: do not proceed to Step 5.
Pass the block to the user with the underlying reason (failing test,
max iterations exhausted, etc.).

### Step 5 — Verify the fix (against the ORIGINAL repro)

Run the **original reproduction from Step 1** again against the fixed code.

```text
**Before (Step 1):**
$ <repro command>
<bad output>

**After (Step 5):**
$ <same repro command>
<output now>
```

Check the two outputs verbatim.
Mark BLOCKED if the after-output still shows the symptom.
Do not merge to main.
Pass the gap to the user with options: re-investigate, accept partial
improvement, or revert.

#### `--skip-verify` (dangerous)

Skip this step but print the following warning when `--skip-verify` was passed:

```text
!!! VERIFY-AGAINST-REPRO SKIPPED (--skip-verify) !!!
The fix passed gates and reviewers, but the original symptom was NOT
re-checked against the fixed code. The bug may persist in a way the
test suite does not capture.
Reason for skip: <user-supplied or "not provided">
```

Document the skip in the final report.
Apply only when the repro is genuinely expensive (multi-hour soak,
hardware-bound, requires live opponent) or impossible from the skill's
environment.

### Step 6 — Merge & report

Continue if verify passed (or was skipped):

1. Confirm changes are in the project tree (the delegated build skill
   already merged its worktree).
2. Run gates in main project as a final sanity check.
   Always emit the actual command + tail of output in the chat.
   Do NOT only state the result line in the final report — the user must
   see proof the gates ran. Format:
   ```bash
   $ <typecheck command>
   <last 1-3 lines of output>
   $ <lint command>
   <last 1-3 lines of output>
   $ <test command>
   <last 1-3 lines of output>
   ```
3. Restore stash if Step 0.4 created one.
4. Close issue if `--issue` given. Use `gh -R <owner>/<repo>` from inside
   the project directory (the workspace `dev/` root resolves to a different
   repo per `.claude/rules/windows-shell.md § gh / jq`).
   Add a comment containing the fix commit hash + a one-line
   "symptom-gone" confirmation from Step 5's verify-against-repro so a
   future LLM viewing the closed issue can verify the fix actually shipped.
   Use `--body-file` for multi-line comments.
5. Report:

```text
fix-bug complete
  Triage: quick | investigate-only
  Diagnosis confidence: high | medium | low (independently confirmed: yes | no | diverged)
  Files changed: N
  Regression test: <test path>
  Gates: typecheck OK, lint OK, test OK
  Delegated to: /build-step
  Delegated verdict: PASS (iteration N/M)
  Review: PASS | NEEDS WORK | skipped     (if --review code)
  Repro before/after: SYMPTOM GONE | SKIPPED (--skip-verify)
  Issue: #N closed
```

## Write-as-you-go

Bug investigation is the highest-risk scenario for context loss. Hypotheses formed and
ruled out, repro conditions confirmed, root cause narrowed — all of this lives in context,
none of it reaches disk until the fix ships (or at all if compaction fires mid-investigation).

bug-fix MUST write to `current.md` at 6 trigger points during execution.
Write at the moment of discovery — NOT at fix completion. The dead ends list IS the
investigation state.

**Path resolution (MUST use git root — never worktree-relative):**
```powershell
$gitRoot = (git rev-parse --show-toplevel).Trim()
$statePath = "$gitRoot/.claude/task-state/current.md"
```

### Trigger points

| # | Trigger | What to write to current.md |
|---|---------|------------------------------|
| 1 | Repro confirmed | MUST overwrite `WIP.Approach`: `"Repro confirmed: [conditions]"` |
| 2 | Any hypothesis formed | MUST append to `WIP`: hypothesis + evidence for it (one line) |
| 3 | Any hypothesis ruled out | MUST append to `Dead Ends`: hypothesis + why ruled out (with evidence) |
| 4 | Root cause identified | MUST overwrite `WIP`: `"Root cause: [description]"` |
| 5 | Fix design agreed | MUST append to `Critical Gotchas`: key constraint the fix must satisfy |
| 6 | Fix complete (build-step returns PASS) | MUST append to `Completed`: bug + root cause + fix commit SHA |

**Trigger 3 is the most critical.** Dead-end writes MUST happen at dismissal time —
immediately when the hypothesis is ruled out — not at the end of investigation.
If compaction fires mid-investigation, the next context reads the dead ends list and
continues from where investigation left off without repeating ruled-out paths.

### Write formats

**Dead Ends** (trigger 3 — MUST append immediately at dismissal):
```
- [hypothesis in 5-10 words]: [why ruled out — specific evidence, file:line if applicable]
```

**WIP.Approach** (triggers 1, 4 — overwrite):
```
**Approach:** Repro confirmed: [exact conditions]
```
or
```
**Approach:** Root cause: [description with file:line]
```

**Completed** (trigger 6 — append):
```
- [<sha>] bug-fix [bug description]: [root cause summary] — fixed
```

**Critical Gotchas** (trigger 5 — append):
```
- [fix constraint]: [why violating it would break the fix or cause regression]
```

### Schema reference

Full field definitions, overwrite/append rules, and lifecycle:
`.claude/references/task-state-schema.md`

---

## Constraints

Do not soften rules under pressure.
Note that if the skill's structure feels too verbose mid-task, that's the
bias firing — not a signal to skip steps.
Keep the verbosity; it is the mechanism.

## Stop-and-audit rule

Stop fixing one-at-a-time when you encounter a 3rd instance of the same
bug shape (producer/consumer drift, silent exception fallthrough in a
loop, hardcoded constant mismatch, schema-without-migration).
Grep for siblings.
Land one comprehensive fix.
See `/build-step` SKILL.md for the full rationale and examples.

## Limitations

- Worktree isolation only (no Docker option — use `/build-step --isolation
  docker` directly if you need clean-room).
- Step 5 (verify-against-repro) requires a deterministic repro. For flaky
  bugs, may need multiple runs to establish baseline rate before/after.
- Delegates to `/build-step`, so inherits its limitations.
