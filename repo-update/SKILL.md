---
name: repo-update
description: End-to-end docs + git update after completing a phase or feature. Updates README, plan doc, runs plan-wrap, fixes gaps, updates memory, commits, creates a closed GitHub issue for posterity, and pushes. Use when asked to "update the docs", "update git", "wrap up this phase", or "push everything".
user-invocable: true
---

# Repo Update Skill (Generic Template)

Use the **project-level `repo-update`** skill at `<project>/.claude/skills/repo-update/SKILL.md` if present; else infer values from project structure.

---

## Project variables

Set these from a project-level override or infer at runtime:

| Variable | Description |
|---|---|
| `PROJECT_ROOT` | Absolute path to the project |
| `REPO_SLUG` | GitHub `owner/repo` |
| `README_PATH` | Path to README relative to project root |
| `PLAN_PATH` | Path to plan doc relative to project root |
| `MEMORY_FILE` | Absolute path to the project's memory file (if any) |
| `DEFAULT_BRANCH` | Branch to push to (e.g. `master`, `main`) |
| `STAGE_INCLUDE` | Files/globs to stage |
| `STAGE_EXCLUDE` | Files/globs to never stage |
| `TEST_CMD` | Command to get test count |
| `COMMIT_COAUTHOR` | Co-author line for commits |
| `WIKI_PATH` | Path to wiki directory (optional — see WIKI_PATH defaults below) |
| `WIKI_ARTIFACTS` | Glob patterns the wiki should cover (see WIKI_ARTIFACTS defaults below) |

**WIKI_PATH defaults.** If unset, auto-detect by checking `documentation/wiki/`, `docs/wiki/`, then `wiki/`. Skip the wiki check if none exist.

**WIKI_ARTIFACTS defaults.**
- `src/<pkg>/*.py` — top-level Python modules
- `frontend/src/components/*.tsx`, `frontend/src/hooks/*.ts`, `frontend/src/lib/*.ts`
- API endpoints from grep `@app\.(get|post|put|delete|websocket)`

---

## What this skill does

1. **Orient** — read current README, plan doc, recent git log, and memory to understand current state
2. **Gather** — ask the user what was completed (if not obvious from context)
3. **Update README** — build status, stack table, UI pages section (if applicable)
4. **Update plan doc** — add/update phase section documenting what was built
5. **Run drift checks** — `/plan-wrap` plus wiki coverage check (if `WIKI_PATH` is set)
6. **Fix plan doc and wiki** — address all blockers and gaps found by either check
7. **Refresh `CLAUDE.md`** — verify all seven sections are accurate against ground truth; create if missing
8. **Update memory** — project memory file with new phase status and test counts
9. **Commit** — stage relevant files, write a structured commit message
10. **Create + close GitHub issue** — for audit trail / posterity
11. **Push** — push to default branch

---

## Step 1 — Orient

Read the following before doing anything else:

```bash
cd $PROJECT_ROOT && git status --short
git log --oneline -5
git log --oneline origin/$DEFAULT_BRANCH..HEAD
```

Also read:
- `$README_PATH` — current build status block
- The last 50 lines of `$PLAN_PATH` — to find the most recent phase section
- `$MEMORY_FILE` (if it exists)

---

## Step 2 — Gather what was completed

If the user hasn't described what was completed, ask:

> "What was completed in this session? Please describe:
> 1. Phase name / label (e.g. 'Phase 4 — Audio Ingestion')
> 2. GitHub issue numbers closed (if any)
> 3. Final test count (run `$TEST_CMD` if unsure)
> 4. Any new routes, types, or files added that the plan doc doesn't document yet"

If the user provides this in their invocation message, use it directly — don't ask again.

---

## Step 3 — Update README

Edit `$README_PATH`:

- Replace the previous "Phase N complete" line in the build status block with the new one
- Format: `**Phase N complete** — issues #X–Y closed. <key deliverable>. <test count> tests passing, 0 type errors, 0 lint violations.`
- Always use the plural `issues #` token even with one closed (`issues #14 closed.`, never `issue #14`).
- If new UI pages were added, update the "UI pages" table
- If new stack entries were added, update the stack table

Do NOT rewrite sections that didn't change.

---

## Step 4 — Update plan doc

Add a new phase section at the end of `$PLAN_PATH` (before any existing appendices, or at the very end). Use this structure:

```markdown
---

## Phase N — <Phase Name>

**All N issues closed. M/M tests passing. Zero type errors. Zero lint violations.**

### What was built

[Bullet list of major deliverables — one line each]

### Files changed

| File | Change |
|---|---|
| `path/to/file` | Description of what changed |

### Fresh context notes for Phase N

| Issue | Detail |
|---|---|
| Any gotcha | What a fresh model needs to know |
```

Only include the "Fresh context notes" table if there are non-obvious facts.

---

## Step 5 — Run drift checks

Run two independent checks that look at different artifacts, then aggregate findings before fixing.

### Step 5a — plan-wrap on the plan doc

Run `/plan-wrap` on `$PLAN_PATH`.

Read the output carefully. Categorise findings as:
- **Blocker** — wrong routes, undefined types used in API contract, missing module entries for files that exist
- **Gap** — types used but not defined, missing files in project tree
- **Minor** — cosmetic or low-stakes

**`[drift]` spec↔code check (advisory — NEVER blocks the push, INV-1).** Folded into this same
plan-wrap pass (not a standalone sub-step). For each step marked `**Status:** DONE` in this
phase's `$PLAN_PATH`:
- Diff the step's shipped change against its `**Produces:**` / `**Problem:**`. If the committed
  diff touched files or behavior the plan does not reflect (code changed without the plan
  updated), surface a `[drift] Gap` (material divergence) or `[drift] Minor` (cosmetic) — same
  Blocker/Gap/Minor format as plan-wrap, prefixed `[drift]` (like `[wiki]` in 5b). `[drift]`
  findings are Gap/Minor only, never Blocker.
- If the step's `**Done when:**` embeds a runnable shell command AND is non-sentinel (not one of
  the `../../references/step-authoring.md` §3 placeholders), re-run it and report pass/fail as a
  `[drift]` line (a FAIL is a `[drift] Gap`). A prose-only or sentinel Done-when is skipped (no re-run).

These are one more advisory input to the interactive phase-wrap alongside the plan-wrap + `[wiki]`
findings; a `[drift] Gap` at most prompts a plan-doc/code fix in Step 6 (exactly like a plan-wrap
Gap). It introduces no block/halt path and the push proceeds regardless.

### Step 5b — Wiki coverage check

Resolve `$WIKI_PATH` from project override; else try `documentation/wiki/`, `docs/wiki/`, `wiki/` under `$PROJECT_ROOT`. Skip 5b if none exist.

Verify the wiki accurately reflects what exists in the codebase: wiki referencing things that no longer exist, and code with no wiki coverage.

Use `$WIKI_ARTIFACTS` to discover the artifacts the wiki should cover. If unset, default to:
- Top-level Python modules: `src/<pkg>/*.py` (one level deep, not recursive)
- Frontend components: `frontend/src/components/*.{tsx,jsx}`
- Frontend hooks: `frontend/src/hooks/*.{ts,tsx}`
- Frontend lib: `frontend/src/lib/*.{ts,tsx}`
- API endpoints: grep for `@app\.(get|post|put|delete|websocket)` in backend source — extract the route paths

Build two lists:
- **Code artifacts** — the set of components, modules, endpoints found in the codebase
- **Wiki references** — the set of names mentioned anywhere in `$WIKI_PATH/*.md`

**Compare both directions:**

1. **Stale wiki references** (Blocker/Gap) — wiki names a file/component/endpoint that no longer exists; grep for the stale name.

2. **Missing wiki coverage** (Gap) — code has a component/module/endpoint no wiki page names. Cross-reference Step 4's "files changed".

3. **Outdated counts and inventories** (Minor) — wiki tables that enumerate artifacts (e.g. "6 tabs", "11 components") drift as code is added.

**What NOT to flag:**
- Test files (`*.test.*`, `tests/*`) — wiki shouldn't enumerate tests
- Type-only files, generated files, build artifacts
- Internal helpers that intentionally aren't part of the public surface
- Wiki pages that intentionally describe planned-but-unbuilt features (rare — usually the plan doc covers this, not the wiki)

**Report findings** in the same Blocker/Gap/Minor format as plan-wrap, but prefixed with `[wiki]` so they're distinguishable. Example:
```text
[wiki] Blocker: documentation/wiki/frontend.md tab table lists 6 tabs but App.tsx has 9
[wiki] Gap: LoopStatus.tsx not mentioned in any wiki page
[wiki] Minor: documentation/wiki/architecture.md says "38 source files" but src/ has 42
```

---

## Step 6 — Fix plan doc and wiki blockers and gaps

For each blocker and gap from either drift check (5a or 5b):

**Before writing any fix, verify against source code.** Read source files to confirm routes, types, components, and module existence.

Apply targeted edits only. Do NOT rewrite sections that are already correct. Surgical edits only.

Apply plan doc fixes first (5a findings), then wiki fixes (5b findings). For gaps in existing pages, add a brief mention to the most relevant page.

**For wiki count/inventory updates** (5b type 3), update the numbers in place. Don't rewrite surrounding prose unless the structure is wrong.

**For uncovered components** (5b type 2), add them to the appropriate wiki page's inventory or component table; match existing one-line style.

**For stale references** (5b type 1), remove or replace the stale name. In a narrative paragraph (not a table), reword rather than delete.

**Escalate to the user** if any of these come up — don't auto-fix:
- A wiki page describes a feature that was deliberately removed (might still want a note about why)
- Multiple wiki pages are in scope for the same coverage gap (which page should host the new content?)
- A new wiki page would need to be created (`/repo-update` doesn't author new wiki pages)

---

## Step 7 — Refresh `CLAUDE.md`

A project's `CLAUDE.md` is what every future session reads first. After shipping a phase, verify it still matches reality.

Create `CLAUDE.md` at project root if absent (pull values from `$PLAN_PATH`, `$README_PATH`, `pyproject.toml`/`package.json`). All seven sections:

1. **Project overview** — one or two sentences (from plan or README).
2. **Stack summary** — current stack table.
3. **Key commands** — install / run / test / lint / typecheck (real commands, not placeholders).
4. **Directory layout** — annotated tree.
5. **Architecture summary** — layers / patterns / key modules.
6. **Current state** — "Phase N complete — <one-line capability>".
7. **Environment requirements** — OS, runtimes, external services, anything that blocks a fresh clone from running.

Walk all seven sections explicitly when `CLAUDE.md` exists. Confirm each section is accurate or update it; report a one-line status per section.

Common refresh targets after a phase:
- "Current state" line — update to the new phase + capability.
- "Stack summary" — add new deps if the phase introduced any (database, queue, framework).
- "Directory layout" — add any new top-level modules or sub-packages.
- "Key commands" — update if `package.json` scripts or `pyproject.toml` entrypoints changed.

Do NOT rewrite sections that are still accurate. Surgical edits.

---

## Step 8 — Update memory

Edit `$MEMORY_FILE` (if one exists):

- Update the build status section with the new phase
- Add new issue entries with their descriptions
- Update the final test count line
- Add any new discrepancies found in Step 6
- Update the footer with current phase status

---

## Step 9 — Commit

Add files matching `$STAGE_INCLUDE`. Do NOT stage anything matching `$STAGE_EXCLUDE`.

Commit message format:

```text
Phase N — <short description>: <comma-separated key deliverables>

<Bullet points for major changes — one per logical group>
- Group A: what changed
- Group B: what changed

M/M tests passing. Zero type errors. Zero lint violations.

$COMMIT_COAUTHOR
```

Use a heredoc for the commit body to avoid quoting issues.

---

## Step 10 — Create and close GitHub issue

Create one issue per phase (or per logical chunk of work if not phase-based):

```bash
gh issue create \
  --title "<Phase N — short description>" \
  --body "$(cat <<'EOF'
## Summary

<3–5 bullet points of what was delivered>

## Test results

M/M tests passing. Zero type errors. Zero lint violations. Commit: <hash>

## Issues closed

#X, #Y, #Z
EOF
)"
```

Immediately close it:

```bash
gh issue close <NUMBER> --comment "Delivered in commit <hash>."
```

---

## Step 11 — Push

```bash
git push origin $DEFAULT_BRANCH
```

Confirm the push succeeded and report the final commit hash and number of commits pushed.

---

## Final report to user

After completing all steps, report:

```text
Done.

Commits pushed: N (origin/$DEFAULT_BRANCH is now at <hash>)
README: build status updated to Phase N
Plan doc: Phase N section added, N clean-context fixes applied
Wiki: K stale references fixed, J coverage gaps filled (or "no wiki check — WIKI_PATH unset")
CLAUDE.md: <created | refreshed: sections X, Y updated | no changes needed>
Memory: updated to Phase N complete
GitHub: issue #N created and closed

Quality gates: M/M tests · 0 type errors · 0 lint violations
```

---

## What NOT to do

- Do not create separate issues for each doc fix — one issue per phase is enough
- Do not stage secrets, debug screenshots, server logs, or lock files from other projects
- Do not run `git add -A` or `git add .` — stage files explicitly
- Do not amend previous commits — always create a new commit
- Do not push until the commit exists and has been verified
- Do not skip the plan-wrap — it catches drift between code and docs that will trip up future work
- Do not skip the wiki check if `WIKI_PATH` is set — drift between wiki and code accumulates silently and is much cheaper to fix one phase at a time
- Do not author new wiki pages from `/repo-update` — surface the need to the user instead
- Do not flag test files, generated files, or internal helpers as wiki coverage gaps


---

## dev-observatory hook (additive; see [`.claude/rules/descriptor-contract.md`](../../rules/descriptor-contract.md))

At phase-wrap, refresh the control plane:

```
uv run --project dev-observatory observatory sync
```

This re-derives verbs/ports from the current `CLAUDE.md` + plan and regenerates the `dev.code-workspace` tasks. Keep README/CLAUDE.md command + port mentions scrapable.
