---
name: session-wrap
description: Prepare for a clean context window transition. Reviews the current conversation, updates memory and docs if stale, and generates a self-contained copy-paste prompt for the next session. Use when approaching context limits or before ending a productive session.
user-invocable: true
---

# Context Window Transition Prep

**Goal: a clean, up-to-date transition.** The next session should open onto a clean working tree, a remote that matches local, and docs/memory that reflect what just shipped. Uncommitted work and unpushed commits are blockers, not optional cleanup — they leak this session's state into the next session's first ten minutes of orientation.

This skill does three things in order:
1. Reviews what happened in this conversation and the current project state
2. Updates memory and docs if anything is stale or missing, then **commits and pushes** so the transition lands on a clean tree
3. Generates a copy-paste ready prompt for the next context window

---

## Step 1: Review the conversation

Scan the full conversation and build an internal summary. Do not output this yet — use it
to drive Steps 2 and 3.

Capture:
- **Project:** Name and working directory
- **Accomplished this session:** Concrete things completed (files written, decisions made, reviews done)
- **Decisions made:** Key choices or direction changes that aren't obvious from the code
- **Current state:** Phase, step, branch, test counts if known
- **Next action:** The single most important thing to do next — specific and actionable
- **Blockers or open questions:** Anything unresolved the next session must know
- **Files created or significantly changed:** Key paths touched this session

### Friction Review

Scan the session for things that were harder than they should have been. Capture:
- **Failed commands or retries:** Commands that errored and had to be re-run or adjusted
- **Wrong assumptions:** Incorrect guesses about file locations, API patterns, build steps, or tool behavior
- **Missing context:** Information that took multiple steps to find but should have been documented
- **Clunky workflows:** Multi-step processes that felt manual or fragile

Skip one-off flukes (typos, transient network errors). Do not include retry counts
(e.g., "took 3 attempts") — describe the pattern, not the episode. Focus on patterns that
would slow down future sessions. If the session was clean with no friction, note that and
move on.

Friction items that are actionable should be saved as memory (feedback type) in Step 2 so
future sessions avoid the same friction.

---

## Step 2: Check memory and docs

### Memory

Read `~\.claude\projects\<project>\memory\MEMORY.md`.
**If the first Read returns a partial-load reminder** (`Only part of it was loaded`,
`truncated`, or similar truncation notice), issue follow-up Read calls with `offset`
until the full file is covered before claiming the read happened. Partial reads
silently corrupt the read-then-report discipline below — the prep summary cannot
honestly say "Read MEMORY.md" if only the first chunk loaded.

In the prep summary, the **Memory checked** bullet MUST follow this literal form
(read-then-report is non-optional, not stylistic):

  > Read MEMORY.md (X lines fully loaded). Existing entry for <topic-1> was
  > <current|stale>; existing entry for <topic-2> was <current|stale>; no
  > existing entry for <topic-3>. Then: <list of updates by name/topic>.

For EVERY MEMORY.md topic touched this session, one explicit
`Existing entry for <topic> was <current|stale>` (or
`no existing entry for <topic>`) clause MUST appear BEFORE any sentence that
describes a change. The Output format template at §Step 3 inherits this
requirement — the §Output format Memory-checked bullet template is a one-line
summary of this rule, not a permission to skip it.

**MEMORY.md soft cap: 200 lines / 200 chars per line.** If MEMORY.md exceeds 200
lines OR any line exceeds 200 chars, the prep summary surfaces an explicit
`**Maintenance:** MEMORY.md over budget (X lines / Y lines > 200 chars) —
recommend trimming index entries; detail belongs in topic files.` line. The
operator decides whether to trim; this skill does NOT auto-edit MEMORY.md content.
The warning is intentionally always-on while MEMORY.md remains over budget — it
quiets itself once the operator trims back under the cap.

Compare against what happened in this session. Write new memory entries for anything not
already captured:
- Project phase or status changes (e.g., "Phase 4 planning complete, not yet started")
- New user preferences or workflow feedback discovered this session
- Newly discovered gotchas or trip-wires not in any plan doc
- Key decisions that aren't obvious from reading the code or docs

Do not duplicate existing entries. Update stale entries rather than appending.
Do not write memory for things already captured in plan.md or a phase prompt file.

**Multi-project sessions.** If this session touched files in more than one project
directory under `dev/` (e.g., both `Alpha4Gate/` and `toybox/` saw code edits),
check MEMORY.md for entries under EACH project's heading, not just CWD's project.
The prep summary's Memory line names each touched project's heading individually
(e.g., "Updated Alpha4Gate entry to note <X>. Updated toybox entry to note <Y>.")
so the next session sees both projects' status at a glance instead of having to
re-derive multi-project scope.

### Sync feedback memories with lessons-learned.md

Cross-project lessons live in two places that must stay in sync:

- **Source of truth (long form):** `<workspace>/docs/lessons-learned.md` —
  version-controlled in the dev/ repo, organized by topic with anchored sections.
- **Pointer (short form):** `~/.claude/projects/<project>/memory/feedback_*.md` —
  each `feedback_*.md` is a thin file with frontmatter + a link to the lessons-learned
  section + a one-line `**Why:**` + a one-line `**How to apply:**`.

Whenever a feedback memory is created, edited, or referenced this session, audit
both layers:

1. **If you wrote a NEW feedback memory in the step above:**
   - Add a corresponding section in `dev/docs/lessons-learned.md` under the right
     topic heading. Use the same `### Title` format as existing sections so the
     auto-generated anchor (`#title-in-kebab-case`) matches.
   - Add the section to the doc's table of contents.
   - Rewrite the `feedback_*.md` to be a thin pointer (frontmatter + link + one-line
     Why + one-line How to apply). Do NOT leave the long form duplicated in both
     files.
   - Add an entry to `MEMORY.md` under the appropriate heading.

2. **If you UPDATED an existing feedback memory (corrected Why, expanded How to
   apply, etc.):**
   - Find the matching section in `dev/docs/lessons-learned.md` (follow the link in
     the pointer file). Apply the same correction there.
   - If the pointer's `description:` frontmatter changed, update the matching line
     in `MEMORY.md`.

3. **If you only REFERENCED an existing feedback memory (no edit):** no sync needed.

4. **Drift check** — pick 2-3 feedback pointers touched in recent sessions and
   verify their lessons-learned section still exists and the pointer's `description:`
   summary matches the section's content. If you find drift, fix it.

The lessons-learned doc is the canonical long form. Pointer files exist only so
`MEMORY.md` can stay short and the per-feedback judgment context (Why + How) loads
into every conversation without pulling in the full long-form doc.

**What to skip:** project-scoped memories (`alpha4gate.md`, `pinchy-*.md`, etc.) do
NOT sync to `dev/docs/lessons-learned.md` — that doc is for cross-project lessons
only. Project-specific gotchas belong in the project's own wiki and are managed by
`/repo-update`, not here.

### Friction catalog staleness check

`<workspace>/docs/friction-catalog.md` is a derived artifact catalogued from
the `feedback_*.md` memories. It gets stale when new memories are added or existing
ones are edited.

Cheap check (no regeneration):

1. Get the catalog's mtime: `stat -c %Y <workspace>/docs/friction-catalog.md`
   (or read the `indexed YYYY-MM-DD` date on line 3).
2. Find any `feedback_*.md` under
   `~/.claude/projects/<project>/memory/` with mtime newer than the
   catalog OR newer than the indexed date.
3. If any newer memories exist, include one line in the Prep summary:
   `Friction catalog: STALE (indexed YYYY-MM-DD; N newer memories). Consider regenerating.`
   If catalog is current: `Friction catalog: current.` (one line, omit entirely if
   the catalog file does not exist — it's optional infrastructure).

Do NOT auto-regenerate. The catalog gen is a multi-file read pass (~80 memories) —
too expensive for every session-wrap. Surface the staleness, let the operator
decide when to re-run.

### Plan and session docs

Check whether the project has a `plan.md` or equivalent and a session prompt file
(e.g., `phase4-prompt.md`, `phase3-prompt.md`).

For each, quickly assess:
- Does it reflect the work done this session?
- If docs were updated this session (as they were in this conversation), confirm they are current.
- Note any remaining divergence between files — do not silently leave a stale file.

If a session prompt file is up to date and self-contained, the transition prompt can point
to it rather than repeating its contents. If it is stale or absent, the transition prompt
must include the detail inline.

### Git status check

If the working directory is a git repository, **the default outcome is a clean tree pushed to origin.** Surface the state, recommend the commit + push explicitly, and only skip if the user says no.

**Multi-project sessions.** Multi-project signal = the Step 1 `Accomplished this
session` bullets reference **2 or more distinct project directory names** (e.g.,
both `Alpha4Gate` and `toybox`, OR a project repo like `toybox` **plus** any
workspace-root file under `dev/` such as `dev/docs/lessons-learned.md`,
`dev/CLAUDE.md`, or `dev/.claude/...` — the `dev/` workspace root is itself a
distinct repo with its own `.git/`, so editing a file there counts as a second
touched repo). When that signal is present you **MUST**:

1. Repeat the status + ahead/behind checks (§1–§4 below) in EACH affected repo,
   including the `dev/` workspace root when any workspace-root file was edited.
2. Render the prep summary's `Git:` bullet as a single line that lists each
   touched repo's status individually, using ` / ` (space-slash-space) as the
   per-repo separator. Each segment must name the repo and its own branch +
   ahead-count + dirty-files state. Example:

     > Git: toybox `master` clean, up to date with remote / dev `master` 2 unpushed, 1 dirty file.

   A single prose paragraph that mentions one repo's status and only references
   another repo as a push target is **non-conforming** — every touched repo gets
   its own ` / `-delimited segment with its own ahead-count and dirty state.
3. List each repo's `HEAD @ <short-sha>` on its own line in the transition
   prompt's `Current state` section (one line per repo, per-repo SHA — not a
   single combined SHA) so §6's verify check can be run per-repo (extends the
   single-repo SHA rule from Step 2 of Phase SW).

If the signal is absent (single project, no workspace-root edits), use the
standard single-repo Git bullet — do not invent a multi-project format.

1. Run `git status` to check for uncommitted changes (staged, unstaged, and untracked files).
2. Run `git log --oneline -1` and compare against `git log --oneline origin/HEAD -1` to check
   if the local branch is ahead of the remote.

   **Multi-branch scan procedure.** Branches other than the current one are easy to miss.
   Scan the conversation for these four verbs to enumerate every branch this session touched:
   `git checkout <branch>`, `git worktree add ... <branch>`, `git merge <branch>`, `git push origin <branch>`.
   For each branch that appeared, run:

       git log --oneline origin/<branch>..<branch>

   Any output means that branch is ahead of remote — surface it under **Git** and recommend
   pushing. A clean output (no lines printed) means the branch is at or behind origin; report
   it as up-to-date.

   Worktree branches deserve extra care: `git worktree remove` un-registers a worktree but
   may leave its branch with unmerged commits if the worktree shipped a code step. See
   [`dev/.claude/rules/worktree-hygiene.md`](<workspace>/.claude/rules/worktree-hygiene.md)
   § "Check unmerged commits before `git worktree remove --force`" before destroying any
   worktree branch.
3. If there are uncommitted changes to plan docs, memory-adjacent files, or other files
   modified/created this session:
   - List them under a **Git** heading.
   - **Recommend committing and pushing**, framed as the default. Phrase the ask as "Commit and push? (recommended for clean handoff)" — not a neutral "do you want to?". The clean-tree goal is the load-bearing reason; surface it.
   - Draft a descriptive commit message covering the session's work (see commit guidelines in the host system prompt). Include all session-modified files in the commit; never leave session work split across "this commit" + "still unstaged" — that's exactly the leakage the skill exists to prevent.
   - If the user confirms, commit AND push in the same turn (don't stop after commit).
4. If any branch is ahead of its remote (committed but not pushed) — including pre-existing commits unrelated to this session — recommend pushing. Old unpushed commits are sediment that confuses the next session's `git log`; clear them now.

**CRITICAL: Resolve all git state BEFORE generating the transition prompt.** If the user
confirms a commit or push, execute it in the same turn and re-read git state afterward,
so the transition prompt reflects the final post-push state (branches pushed, remote SHAs
up to date, "Git: clean, up to date with remote"). Generating the prompt first and pushing
afterward forces the user to re-run session-wrap to get an accurate handoff — defeats the
purpose. If the user declines to push, still generate the prompt in the same turn but with
an explicit "unpushed commits on X, Y" note so the next session knows to check.

Do NOT commit or push without asking — but DO frame the ask as a recommendation, not a neutral surfacing. The user invoked session-wrap because they want a clean handoff; honor that intent.

### Post-build-phase cleanup

Scan the conversation for signs that a `/build-phase` ran this session (checkpoint commits,
step completion comments, the final build-phase report table). If detected, run these
additional checks and **act on them automatically** — do not ask for confirmation on each
item. These are safe, non-destructive cleanup actions that should always happen after a
build-phase completes.

1. **Push** — if local is ahead of remote, push. Build-phase generates many checkpoint
   commits that should not sit unpushed.

2. **Close completed issues** — read the plan doc for steps marked `Status: DONE` that have
   an `Issue: #N` field. Check each with `gh issue view N --json state -q .state`. Close
   any that are still open with a brief completion comment.

3. **Plan doc Current State freshness** — the "Current State" or "What exists" / "What's
   missing" section in the plan doc is almost certainly stale after a full phase. Read it
   and update to reflect what was just built. Remove "missing" items that Phase N delivered.
   Add new deliverables to "What exists."

4. **Worktree cleanup** — check for leftover `.claude/worktrees/agent-*` directories.
   Remove with `git worktree remove <path> --force` and delete the corresponding
   `worktree-agent-*` branches.

5. **Phase status** — if all steps in the phase are marked DONE, ensure the phase-level
   status line is also marked DONE with the date and final test count.

Report what was done in the prep summary under a **Post-build-phase cleanup** heading.

---

## Step 3: Generate the transition prompt

Write a copy-paste ready block (wrapped in a markdown code fence labeled `text`) that the
user can paste as the first message in a fresh context window.

The transition prompt must be **completely self-contained** — assume the new context has
zero knowledge of this conversation.

### CRITICAL formatting rule — no nested code fences

The transition prompt lives inside a ` ```text ` code fence. Any triple-backtick inside it
(` ```bash `, ` ```shell `, ` ``` `) will **terminate the outer fence** and break the output.

**NEVER use triple-backtick code fences anywhere inside the transition prompt.** Instead:
- For shell commands: list them as plain indented text lines (2-space indent)
- For file paths or inline code: use single backticks
- For multi-line code snippets: indent with 4 spaces (no fence)

This applies to ALL sections, not just Verification commands.

### Required sections in the transition prompt

**1. Project identity** (2–3 lines)
- Name, working directory path, one-sentence description of what it is

**2. What was accomplished this session** (bullet list)
- Concrete, specific — what files were written or changed, what decisions were made
- 3–8 bullets; skip anything trivial

**3. Current state** (1 short paragraph or bullet list)
- Phase/step, test counts, any known failures or open issues
- What is and isn't built yet
- **Current SHA — required:** include `git rev-parse --short HEAD` output verbatim (e.g., `HEAD @ 4e0c14d`). This anchors §6's first-bullet verify check; omitting it makes the verify bullet ungrounded.

**4. Next action** (1–3 lines, very specific)
- The exact first thing to do — command, skill invocation, or file to read
- If a session prompt file exists and is current, say: "Start by reading [path]"
- **If the next action is gated on human review of findings** (i.e. the intent is
  "investigate and report back before proceeding"), split it into two clearly
  labelled sub-blocks — never co-locate a gate and an action in the same prose
  block, because a fresh zero-context session reads a single block as a sequential
  task list and executes everything autonomously:

  > **Investigate:** [what to read or run] — end with: "Post your findings here
  > and STOP. Wait for user response before proceeding."
  >
  > **After user approval:** [downstream command or skill] — prefix with: "DO NOT
  > run this until the user responds to your findings above."

**5. Key files to read first** (ordered list)
- 2–5 files, most important first
- One-phrase note on why each is needed

**6. Critical warnings** (bullet list, ≤5 items)

The FIRST bullet is required and fixed in form — it is the next-session
git-verification anchor that pairs with §3's Current SHA:

> **First action — verify git state matches this prompt:** run `git log --oneline -5`
> and `git rev-parse --short HEAD`. If HEAD does not match the SHA stated above under
> "Current state", the prompt is stale — re-orient against actual git state before
> doing any work.

Then add ≤4 more bullets covering project-specific risks:
- Things that will cause failures if the new context gets them wrong
- Only include what is NOT obvious from reading the listed docs
- Prefer high-signal, specific warnings over general reminders

Why the first-bullet rule: saved prompts freeze a pre-execution view of the project; parallel windows may have committed since this prompt was written. The verify bullet pairs with [`feedback_verify_state_vs_session_prompt.md`](~/.claude/projects/<project>/memory/feedback_verify_state_vs_session_prompt.md) — Alpha4Gate stale-prompt incident cost ~15 min before the rule existed.

**7. Verification commands** (plain indented lines, 2-space indent)
- Shell commands to confirm the project is in the expected state
- Typically: typecheck, lint, test

**8. Required context** (1–3 lines)
- Magic words, CLAUDE.md requirements, or hook behaviours the new context must know
- The magic word for this project is AmaRocket (include if the project has a CLAUDE.md)

---

## Output format

Output two clearly separated parts:

---

### Part 1 — Prep summary

A bullet list of 4–8 items (one item per line, each on its own line) for the user confirming:
- **Memory checked:** "Read MEMORY.md." then list what entries were written or updated (by name/topic). If any feedback memory was created or updated, also note the corresponding `dev/docs/lessons-learned.md` section that was added/edited (or "lessons-learned.md unchanged — no feedback edits this session")
- **Docs status:** Status of plan.md and any session prompt file (current / stale / absent)
- **Git:** Uncommitted changes, unpushed commits, or "clean, up to date with remote"
- **Issues:** Any issues noticed that need attention before the new session starts
- **Self-contained:** Whether the transition prompt is fully self-contained or relies on an external file
- **Post-build-phase cleanup:** (only if build-phase detected) What was pushed, issues closed, docs updated, worktrees cleaned. Or "N/A — no build-phase this session."
- **Friction found:** List any friction items discovered, or "None — clean session"
  - For each item saved as feedback memory, note the memory file name
  - Do NOT mention one-off flukes (typos, transient errors) even to say they were excluded

---

### Part 2 — Transition prompt

A single code fence labeled `text` containing the full transition prompt.
The user copies everything inside the fence and pastes it as the first message.

---

## Length and tone guidelines

- Transition prompt target: 300–600 words inside the fence. **The 300-word minimum is a hard
  floor** — if your draft is under 300 words, expand Critical warnings and Key files with
  more detail until you reach at least 300
- Omit anything the new context can derive by reading the docs listed under "Key files"
- One precise warning beats three vague ones
- If a well-maintained session prompt file exists (like `phase4-prompt.md`), keep the
  transition prompt short and direct the new context to read that file — do not duplicate it
- The prep summary should feel like a quick handoff note, not a report

---

## Maintenance

This skill ships with an eval framework at [`evals/`](evals/). Before editing SKILL.md, read [`evals/iteration_log.md`](evals/iteration_log.md) — 4 of the first 8 iterations were DISCARD because a fix to one assertion regressed another. After any change, run the full produce-then-grade suite (canonical procedure: [`~/.claude/skills/skill-eval-setup/SKILL.md`](../skill-eval-setup/SKILL.md) § "Self-improvement prompt template"; smaller model produces, sonnet grades strict, borderline = FALSE). The current contract is **23 assertions × 4 scenarios = 92 assertion-evaluations** with `passing_threshold: 21/23` per the (N−2)/N skill-eval-setup convention. Discard any change that regresses a prior-passing assertion even if it improves others. Append iteration rows to [`evals/iteration_log.md`](evals/iteration_log.md) in the existing Markdown table format (`| Iteration | Score | Result | Change Attempted |`); do not switch to a bulleted format — continuity with iterations 1–13 matters for trace readability. When adding or removing assertions, update both the count cited here AND `passing_threshold` in [`evals/evals.json`](evals/evals.json) in the same diff.
