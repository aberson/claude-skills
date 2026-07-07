---
name: context-slim
description: Audit all auto-loaded Claude Code context files (CLAUDE.md chain, .claude/rules/*.md, MEMORY.md) for a project and produce a prioritized progressive-disclosure improvement report — what to stub, extract, or prune to reduce per-turn token cost. Run bare for a report only; add --apply to implement high-confidence changes (rules stubbing, stale memory pruning) autonomously.
user-invocable: true
argument: Optional flags: --project <name-or-path> (default: innermost project with a CLAUDE.md); --apply (implement high-confidence changes after the report)
---

# context-slim

Measures every file that auto-loads on every Claude Code conversation turn for a project, classifies each section as always-needed vs task-specific vs stale, and produces a prioritized improvement plan. With `--apply`, implements the high-confidence mechanical changes without requiring judgment calls.

## When to use

- Sessions are burning 30-50%+ of the context window before substantive work begins.
- After a multi-phase project has accumulated months of CLAUDE.md narrative and stale memory blocks.
- Before starting a new build phase to ensure context overhead is lean.
- Periodic maintenance (monthly, or after any major phase ships).

## Phase 1 — Bootstrap: discover and measure

Parse args. Resolve `--project` to an absolute path: if it's a bare name (e.g. `void_furnace`), look for `<dev-root>/<name>/CLAUDE.md`; if it's a relative or absolute path, resolve directly. Default to the innermost ancestor directory of cwd that contains a `CLAUDE.md`.

Walk from the resolved project directory up to the `dev/` root (stop at the first directory whose parent has no `CLAUDE.md`). Collect:
- Every `CLAUDE.md` in the walk (project-level, then each parent up to dev/)
- Every `.claude/rules/*.md` at each level of the walk
- The project's memory index: glob `~\.claude\projects\*<project-basename>*\memory\MEMORY.md` and take the first match; if none, try the encoded form (`_` → `-`, `\` → `-`, `:\` → `--`, all lowercase).

For each collected file, record its **line count** (use the Read tool or PowerShell `(Get-Content <path>).Count`).

Also scan each collected CLAUDE.md for `.claude/rules/<filename>.md` link references (grep for `rules/.*\.md`). Verify each target file exists. Record any missing targets in the discovery table as `rules/<name>.md  (MISSING — referenced but not found)`.

Print the discovery table before any analysis:

```text
context-slim — <resolved project path>

Auto-loaded files:
  File                                   Lines
  ─────────────────────────────────────────────
  CLAUDE.md  (dev/)                        100
  CLAUDE.md  (void_furnace/)                72
  rules/code-quality.md (dev)               78
  rules/plan-and-issue-flow.md (dev)       115
  rules/windows-shell.md (dev)              58
  ... (all discovered rules files)
  MEMORY.md                                225
  ─────────────────────────────────────────────
  TOTAL                                   ~N lines  (~X est. tokens)
```

Estimated tokens = lines × 15 (rough average for dense prose/markdown).

## Phase 2 — Parallel analysis

Spawn three parallel subagents using the Agent tool. Each receives its target file(s) as a prompt with the full contents inline (use Read to fetch them first). Collect all three results before Phase 3.

**Optional local-classifier offload (switchboard, INERT BY DEFAULT).** This three-way file-classifier fan-out is the one role this skill may route to a local model (offload-scan task_class `context-slim-classifier`; Switchboard Decision 9 — a cheap, low-stakes parallel classification array). It is **off unless switchboard offload is enabled for this slice**. When offload is enabled, route each classifier's per-section judgment through the switchboard judge entrypoint (`python -m switchboard judge --site context-slim-classifier --prompt-file <section-prompt-file>`, prints one JSON object, always exits 0): use a **verdict** as the local classifier's advisory call, and on a **defer** (`{"defer": true, ...}`) fall back to the normal Claude classification subagent. When offload is OFF (the default), the entrypoint returns a defer immediately with NO network call, so this skill spawns the three Claude classifier subagents **exactly as before**. The KEEP/EXTRACT/COMPRESS classification is advisory only — Phase 3 synthesis and any `--apply` change stays on Claude.

### Agent A — CLAUDE.md chain

For each CLAUDE.md in the chain, classify every section:

- **KEEP** — structural facts, critical safety rules, always-needed orientation (stack, commands, core gotchas, governance invariants).
- **EXTRACT** — status narrative, phase history, large reference tables, content only needed for specific task types. For each EXTRACT, name the destination file (e.g. `.claude/phase-status.md`) and write the 1-3 line pointer that replaces it.
- **COMPRESS** — sections that repeat content already in rules files, or that could be a single sentence instead of a paragraph.

Produce a table: Section → Verdict → Destination (if EXTRACT) → Lines before → Lines after.
State the estimated slim line count for each file.

### Agent B — Rules files

For each rules file, classify:

- **KEEP AS-IS** — always-relevant safety or quality rules; small enough to justify full auto-load (under ~40 lines). Do not stub `code-quality.md` or `security.md` regardless of size.
- **STUB** — relevant on some turns but over-detailed; replace the rules file with a 3-8 line summary stub, move the full content to `.claude/references/<filename>`. Write the exact stub text.
- **MOVE OUT** — only needed on rare task types; remove from rules/ entirely, add a one-line pointer in the nearest CLAUDE.md. State the exact pointer line.

Produce a per-file table: File → Verdict → Lines → Est. tokens → Post-change est. tokens.
Include the full stub text for every STUB recommendation.
State the total token reduction.

### Agent C — Memory index (MEMORY.md)

Classify every section. Today's date is available from the system context (`currentDate`).

- **INDEX LINE** — one-liner pointer to a detail file. Keep as-is.
- **INLINE DETAIL** — multi-paragraph narrative that belongs in its referenced detail file, not the index. Recommend moving.
- **ACTIVE STATUS** — project status less than 3 days old. Keep.
- **STALE STATUS (ARCHIVE)** — dated more than 5 days ago, superseded by newer blocks, but contains hard facts (commit hashes, test counts, run IDs, cost figures) worth keeping for forensic use. Move to `MEMORY-ARCHIVE.md`.
- **STALE STATUS (DELETE)** — dated more than 5 days ago, pre-build planning sessions or intermediate checkpoints whose outcome is already captured in index entries. Delete outright.
- **COMPRESS** — a block that can be reduced to a single sentence without losing load-bearing facts.

Produce a table: Section (first line) → Date → Verdict → Reason → Lines.
State the projected MEMORY.md line count after all changes.
Flag if current MEMORY.md is at or above the 200-line truncation cap.

## Phase 3 — Report

Before writing the report, do two cross-reference passes using the collected agent results:

**Stub → MEMORY cross-reference:** For each file Agent B marks STUB, scan Agent C's INDEX LINE verdicts for MEMORY.md entries whose core rule is now directly expressed in the stub text. When the stub carries the behavioral directive ("run X before Y", "use Z not W"), the MEMORY.md pointer may add little recall value — it's a pointer-to-a-pointer. Mark these as **STUB-REDUNDANT (review)** — separate from Agent C's stale-status finds so the origin is clear. These are **NOT apply-safe** and always go in Needs-review: a MEMORY index line is the recall path to its topic file's long-form (the "why" + incident), which the always-loaded stub does not carry — deleting the index line orphans that long-form. The operator confirms each before deletion.

**Broken reference check:** For any `rules/<name>.md  (MISSING)` entries found in Phase 1, include them in the report under a dedicated "Broken rule references" section. These are never apply-safe (creating a new rules file requires correct content, not a placeholder); always go in Needs-review.

Synthesize all three agents' outputs into a single report. Print in full; do not truncate.

```markdown
## context-slim report — <project> — <date>

### Current auto-load cost
| File | Lines | Est. tokens |
|---|---|---|
| ... | ... | ... |
| TOTAL | N | ~X |

### Recommended changes (ranked by tokens saved, largest first)
| # | File | Action | Saves | Effort | Apply-safe? |
|---|---|---|---|---|---|
| 1 | rules/plan-and-issue-flow.md | STUB | ~1,900 tok | Low | Yes |
| 2 | rules/worktree-hygiene.md | STUB | ~1,350 tok | Low | Yes |
| 3 | MEMORY.md | Prune 9 stale blocks | ~1,100 tok | Low | Yes |

### Stub-redundant MEMORY.md index lines (cross-reference pass — Needs-review)
Entries whose rule is now directly in a stub. Surfaced for operator confirmation, NOT auto-deleted (the index line is the recall path to its topic file's long-form):
- MEMORY.md: "<entry text>" — rule now in <stub-file>.md stub
...
(Omit section if none found.)

### Broken rule references
| File referenced | In | Status |
|---|---|---|
| rules/python.md | dev/CLAUDE.md | MISSING — create to fix broken link |
(Omit section if none found.)

### High-confidence (--apply will implement these)
<bulleted list — STUBs, stale-status MEMORY deletes, COMPRESS blocks>

### Needs operator review (--apply skips these)
<bulleted list — CLAUDE.md splits; missing rules files (need correct content, not placeholder); stub-redundant MEMORY index-line deletions (each orphans a topic file's long-form — confirm first)>

### Projected savings
Before: N lines / ~X tokens per turn
After:  M lines / ~Y tokens per turn  (~Z% reduction)
```

End the report with this exact standalone line (no surrounding text):

`Run \`/context-slim --apply\``

(Omit this line if --apply was already passed.)

## Phase 4 — Apply (skip entirely if --apply was not passed)

Implement only the high-confidence changes. These are mechanical and fully reversible.

### H1 — Rules file changes

**For each STUB recommendation:**
1. `Glob` or confirm `.claude/references/` exists at the appropriate level; create it if not (PowerShell: `New-Item -ItemType Directory -Force <path>`).
2. Write the full original rules file content to `.claude/references/<filename>` (use the Write tool with the content read in Phase 2).
3. Replace the rules file with the stub text Agent B produced (use the Write tool).
4. Verify: stub is under 10 lines; references copy matches the original line count.

**For each MOVE OUT recommendation:**
1. Copy the file to `.claude/references/<filename>`.
2. Read the target CLAUDE.md; append a `## Topic-specific guidance` section (or add to an existing one) with the one-line pointer Agent B specified.
3. Delete the original from `.claude/rules/` (PowerShell: `Remove-Item <path>`).

### H2 — Memory pruning

Process Agent C's recommendations in order from bottom of file to top (so line numbers stay valid):

**DELETE blocks** (from Agent C's stale-status findings only): Remove those lines from MEMORY.md directly using the Edit tool. (Phase 3 stub-redundant cross-reference finds are NOT deleted here — they go to Needs-review for operator confirmation, since deleting an index line orphans its topic file's long-form.)

**ARCHIVE blocks:** 
1. Check if `MEMORY-ARCHIVE.md` exists in the same directory; if not, create it with a `# Archived status blocks` header.
2. Append the block content to `MEMORY-ARCHIVE.md` with a `## <original section heading>` separator.
3. Remove the block from MEMORY.md using the Edit tool.

**COMPRESS blocks:** Replace with the one-liner Agent C produced using the Edit tool.

After all pruning: read the new MEMORY.md line count. If still above 150, report which sections remain large and why they were not pruned (never auto-prune INDEX LINES or ACTIVE STATUS).

### H3 — Verify and report

Print a before/after summary:

```text
Applied changes:

  rules/plan-and-issue-flow.md   → stubbed (115 → 6 lines); full content at .claude/references/plan-and-issue-flow.md
  rules/worktree-hygiene.md      → stubbed (90 → 7 lines); full content at .claude/references/worktree-hygiene.md (existing — not overwritten)
  MEMORY.md                      → pruned (225 → 108 lines; 9 stale blocks removed, 3 archived)
  ...

  Total auto-load reduction: N lines / ~X tokens per turn  (was Y, now Z — A% smaller)

Files NOT changed (need operator review):
  CLAUDE.md (void_furnace/) — Phase OMR extract proposed; see report above
  ...
```

For each line: format is `rules/<file> → stubbed (N → M lines); full content at .claude/references/<file>`. If the references file already existed (conflict), add `(existing — not overwritten)` after the path.

## Limitations

- Only audits files that auto-load every turn; context loaded manually or via IDE settings is not analyzed.
- Does not commit changes — operator reviews and commits after `--apply`.

## Constraints

- Never stub or modify `code-quality.md` or `security.md` — these are always-load safety files regardless of size.
- Never auto-apply CLAUDE.md splits — those always go in Needs-review.
- Never delete MEMORY.md INDEX LINES or ACTIVE STATUS blocks. Stub-redundant index lines (rules now directly carried by a stub) are surfaced in Needs-review for operator confirmation, never auto-deleted — the index line is the recall path to its topic file's long-form.
- Never overwrite a `.claude/references/` file that already exists — report the conflict and skip.
- Missing rules files (referenced in CLAUDE.md but not found on disk) always go in Needs-review — creating them requires correct content, not a placeholder stub.
- If any Write or Edit fails, report the failure and continue with remaining changes; do not abort the whole apply run.
- Do not commit. Leave the changes in the working tree for operator review before committing.
