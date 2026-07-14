---
name: repo-sync
description: Sync GitHub issues to match a plan's structure (umbrellas + step issues), with rich bodies optimized for fresh-context LLM work. Detects letter-named phases, sub-phase notation, table-row step formats. Use after plan changes or to bring issue bodies up to current build-doc richness.
user-invocable: true
---

# Repo Sync

Bidirectional sync between a plan document and GitHub issues. Creates,
updates, closes, and **enriches** issues so GitHub mirrors the plan's
structure and any fresh-context LLM picking up a step has enough context
in the issue body to start work.

## Principle: optimize for LLM effectiveness, not human-noise reduction

Issue bodies should be substantive. A fresh-context model reading
`gh issue view #N` should understand:
- What to build (not just a name)
- Where in the codebase (specific files)
- How to know it's done (concrete acceptance)
- What it depends on (prior issues, blocked-by relationships)
- Build-phase flags (reviewers, isolation, **`--ui` when frontend is touched**)
- Where the canonical design lives (build doc + section anchor)
- **Whether the step can run in parallel with neighbors** (declared explicitly,
  not left for the operator to infer)

Lean bodies (just "What to build" and a footer) tax every future
session that picks up that issue. Treat enrichment as a first-class
output, not optional polish. Issue count and inbox tidiness are
human-experience costs the operator is fine paying — don't optimize for
them at the expense of the LLM-context-effectiveness above.

## Operator preference (HEAVY) — autonomous + bundled UI + parallel

This skill propagates the operator's strong workflow preference through every
issue it writes. Three dials, applied to every step body:

1. **Autonomous build readiness.** Step bodies must contain enough acceptance
   detail (`Done when`) for `/build-step` to verify PASS without asking the
   operator a follow-up. Bodies that force a human ping mid-build are a
   regression. When enriching, prioritize concrete acceptance over prose.

2. **UI-bundle declaration.** If a step's `Files` touch `frontend/`, change a
   `/api/...` shape consumed by the dashboard, or modify WebSocket payloads,
   the issue body's `Flags (recommended)` line MUST include `--ui` and the
   `Done when` MUST reference UI evidence (Playwright screenshot, dashboard
   smoke, or any project-specific UI/dashboard smoke commands defined in
   the project's `CLAUDE.md`). Code-only acceptance on frontend-touching
   work is the gap repo-sync is here to close — flag any existing issue
   that violates this and propose enrichment.

3. **Parallelism declared explicitly.** If a step has no `Depends on` and
   shares no `Files` with another open step in the same phase, the body MUST
   note `**Parallel-safe with:** #M` (and the reciprocal noted on #M too).
   Sequential is fine, but `none — strictly sequential` MUST carry a one-line
   justification (e.g. "Step N+1 imports this module"); a bare
   "strictly sequential" without a reason is a defect — the parallelism
   choice must be visible in the issue, not hidden in the operator's head.

These dials are applied during CREATE, ENRICH, and UPDATE — not just on first
write. A pre-existing rich body that lacks the UI-bundle declaration on a
frontend-touching step still counts as needing ENRICH.

## When to use

- Plan steps were added, removed, or reworded after issues were created
- Existing issues have lean bodies that need richer context (`--enrich`)
- Cutting issues for a new phase from its build doc
- User says: "sync issues", "update GitHub issues", "enrich step issues",
  "issues are out of date"

## When NOT to use

- Closing a single issue after a step completes — just `gh issue close N`
- Bulk-closing issues from a deleted plan (use `gh issue list ... | xargs gh issue close`)

---

## Prerequisites

Run the plan pipeline in order. `/repo-sync` is step 4 of 5:

  1. `/plan-init` or `/plan-feature` — produce `plan.md`.
  2. `/plan-review` — gap-check before sync.
  3. `/plan-wrap` — clean-context check before sync.
  4. `/repo-sync` — mint or update issues from the plan.
  5. `/build-phase` — execute the steps.

Skipping `/plan-review` or `/plan-wrap` before sync is the
**N+1 rework trap**: one plan edit becomes N+1 edits — the plan
file plus every step issue body that needs the same fix.
`/repo-sync` mints fresh-context-LLM-targeted issue bodies
straight from the plan, so plan-only ambiguities (undefined IDs,
unexplained acronyms, lingering TBDs) bake into every issue.

For an autonomous pre-flight that runs the chain unattended,
use `/plan-expedite --plan <path>` — it chains
`plan-review --autofix → plan-wrap --autofix → repo-sync →
session-wrap` in one shot.

Canonical workspace-level statement of the chain lives in
`dev/.claude/rules/plan-and-issue-flow.md` § Order.

---

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--plan` | yes | -- | Path to plan/build-doc (e.g. `documentation/plans/phase-d-build-plan.md`) |
| `--phase` | no | inferred | Phase identifier (B, D, E, 6, 7, F, G, G.2, 9, etc.) — letters and numbers both supported. Inferred from filename if omitted. |
| `--scope` | no | both | `umbrella`, `steps`, or `both` |
| `--enrich` | no | false | Update existing-issue bodies if richer content is now in the plan |
| `--dry-run` | no | false | Print issue-change preview and exit without applying — for validation before commit |

---

## Phase identifier conventions

Phases can be:
- Numeric: `Phase 0`, `Phase 1`, ..., `Phase 9` — common for substrate/operational tracks
- Letter: `Phase A`, `Phase B`, `Phase D`, ..., `Phase G` — common for capability tracks
- Sub-phase: `Phase G.1`, `Phase G.2`, `Phase G.3` — for multi-step phases that fork

Numbering gaps are allowed and intentional (e.g. project skipped Phase C
during a merge; project may skip Phase 8 to align with pre-existing
issue titles). The skill honors the plan as-written — does NOT try to
fill gaps.

Step numbering within a phase uses dot notation in the build doc
(e.g. `D.1`, `D.2`, `7.1`, `G.2.1`) but issue titles use the friendlier
`Phase X Step N:` form.

Issue title patterns the skill recognizes:
- Umbrella: `Phase X — <name>`  (e.g. `Phase D — Build-order z-statistic`)
- Step: `Phase X Step N: <name>`  (e.g. `Phase D Step 1: Audit reward_rules.json`)
- Sub-phase umbrella: `Phase X.M: <name>`  (e.g. `Phase G.2: Zerg bot`)
- Sub-phase step: `Phase X.M Step N: <name>`

## Step-detection formats supported in plan docs

The skill scans the plan for any of:
- `### Step N: <name>` — heading style
- `### Phase X Step N: <name>` — explicit phase heading
- `#### Step N: <name>` — sub-heading style
- `- **Step N:** <name>` — list style
- `| X.N | <description> |` — table row in a Scope / Build-steps section

For table-row format, the description is the step title; richer body
content must be pulled from explicit per-step subsections OR the doc is
flagged as lean (see "Doc richness check").

---

## Flow

### Step 0 — Pre-flight: resolve and verify target repo

`gh` resolves the target repo from cwd by walking up to the nearest
`.git/`. The `dev/` workspace root is itself a git repo with its own
remote (`<your-org>/coding-root`), so running `gh` from `dev/` silently
lands on `<your-org>/coding-root` instead of the intended project
subdirectory. Resolve and echo the repo before any mutating call:

```bash
cd <absolute-project-dir>
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
echo "Target repo: $REPO"
```

Confirm the printed `Target repo:` matches the intended project. If it
does not, stop — the cwd is wrong.

For every subsequent `gh` call in the run, pass `-R <owner>/<repo>`
defensively so cwd-resolution cannot drift mid-run:

```bash
gh -R <your-org>/Alpha4Gate issue create ...
gh -R <your-org>/Alpha4Gate issue list ...
```

Equivalent fix: `cd` into the project subdirectory before invoking
`gh` (e.g., `cd Alpha4Gate && gh ...`). The `-R` flag is preferred
because it survives mid-run cwd changes.

### Step 1 — Read the plan and infer phase

Read `--plan`. If `--phase` not specified, infer from filename
(`phase-d-build-plan.md` → `D`; `phase-9-build-plan.md` → `9`;
`improve-bot-evolve-plan.md` → check `# Phase X ...` H1 in content).

Extract:
- **Umbrella metadata:** title (from `# <H1>`), goal, prerequisites,
  effort, kill criterion, validation
- **Step list:** every step matching one of the supported formats

For each step, capture from per-step subsections if present:
- `Problem` / `What to build`
- `Files` / `Files to modify` / `Files touched`
- `Existing context`
- `Done when` / `Acceptance`
- `Flags` (build-step flags like `--reviewers code --isolation worktree`)
- `Depends on`
- `Produces`

If steps are table-only (sparse), flag this and run the richness check
(below).

### Step 2 — Doc richness check (the LLM-effectiveness gate)

For each step, count populated rich-fields out of 6:
{Files, Done when, Flags, Existing context, Produces, Depends on}.

- **Rich step:** ≥ 3 fields populated
- **Lean step:** ≤ 2 fields populated

If >50% of steps are lean:

```text
WARNING: <plan> has N of M lean steps (only title + description).

Issues created from lean steps will be lean too. Every fresh-context
LLM session that opens those issues will need to drill into the build
doc or source code for context the issue body should have.

Per the LLM-effectiveness principle (memory:
feedback_optimize_for_llm_over_human_noise.md), the recommendation is:

  1. Enrich the build doc first with per-step Files / Done when /
     Flags / Existing context sections.
  2. Then re-run this skill (or run with --enrich for an existing
     issue set).

Continuing — issue bodies will reflect the plan's current shape.
Operator can re-run /repo-sync after enriching the plan if higher-
fidelity issues are needed.
```

Surfacing this cost is mandatory; the warning is a printed observability
note that proceeds automatically without prompting. The operator can
re-run `/repo-sync` after enriching the plan when richer issues are
needed — but no halt mid-sync.

### Step 3 — Fetch existing GitHub issues

```bash
# jq requires POSIX classes — no \d / \w / \s / \. (see Common mistakes § Perl-style regex escapes)
gh issue list --state all --limit 200 --json number,title,body,state \
  --jq '.[] | select(.title | test("^Phase [A-Z0-9]+([.][0-9]+)?( Step [0-9]+)?:|^Phase [A-Z0-9]+([.][0-9]+)? — "))'
```

This regex matches both umbrella titles (`Phase X — ...`) and step
titles (`Phase X Step N: ...`) across numeric, letter, and sub-phase
numbering. Falls through to the legacy `(Phase \d+ )?Step \d+:` if the
new pattern returns nothing (back-compat).

#### 3.1 — Cross-plan collision check

When a repo holds issues from multiple plans, step keys
(`Phase X Step N`) collide and a new plan's step may match a
stale issue belonging to an unrelated, possibly closed prior
plan.

The disambiguator is the body footer `/repo-sync` writes.
There are TWO footer shapes — both encode the source-plan
path and the parser must recognize both. In the rendered
issue body the plan path is a markdown link (square-bracket
label wrapping the path, parenthesis URL `../blob/master/`
plus that same path) so the path is clickable from the
GitHub issue — never a code-spanned path followed by a
parenthetical "linked to" phrase.

- Create path (see Body template — step):
  `*Synced from `<plan>` by /repo-sync at <git-short-sha>*`
  (with `<plan>` rendered as the markdown link described above).
- Enrich / update path (see Update / enrich):
  `*Enriched by /repo-sync from <build-doc-path> @
  <git-short-sha>*`

Long-lived issues that have been re-synced carry the second
shape; the parser must match both or every previously
enriched issue falls through as "footer missing" — exactly
the issues most likely to be cross-plan-colliding.

Regex shapes the parser must match:
- Create:  `Synced from \[(.*?)\]`
- Enrich:  `Enriched by /repo-sync from (.+?)( @ |$)`

Algorithm: for each issue that matched a plan step in the
Step 3 fetch above, parse the footer's plan path from the
issue body — from EITHER `Synced from [<plan>]` OR
`Enriched by /repo-sync from <build-doc-path>`. If that plan
path differs from the current `--plan` argument's path,
classify the match as a CROSS-PLAN COLLISION (the issue
belongs to a different plan; the step key collision is
incidental).

Action: emit a `WARN: cross-plan collision` line in the
Step 5 preview output for each collision. **No halt** —
autonomous default still executes; the operator sees the
warning in the preview but the run proceeds without
prompting. Collided issues are excluded from ENRICH /
REOPEN candidate lists (treat as stale w.r.t. this plan).

Example warning line in the preview:

```text
WARN: cross-plan collision — issue #123 "Phase D Step 3: foo"
  plan footer: documentation/old-plan.md
  --plan arg:  docs/archived-plans/repo-sync-improvements-plan.md
  classify as: stale (do not ENRICH, do not REOPEN)
```

Footer-absent issues (legacy or hand-authored) cannot be
classified by this check; fall through to the existing
title-prefix match behavior. Add `(footer missing)` to the
preview note so the operator knows the check could not run
on that issue.

**Always-surface contract.** The rendered Step 3.1 output
MUST state the two recognized footer shapes explicitly —
even when no existing issues were matched in Step 3. This
makes the parser's footer-aware classification visible and
auditable in every run, not only runs that exercise it.

Required Step 3.1 header line in the rendered output:

```text
Footer shapes recognized:
  Create:  Synced from [<plan>](...)
  Enrich:  Enriched by /repo-sync from <build-doc-path> @ <sha>
```

When no issues were matched, follow with `(no existing
issues to classify)`. When issues exist, list each with its
footer plan path or `(footer missing)` per the algorithm
above. Either way, neither footer shape is omitted from the
output, so enriched-path issues are never silently treated
as `footer missing`.

### Step 4 — Match and diff

Match plan entries to existing issues by title prefix:
- Umbrella: `Phase X — <anything>` matches plan's H1 phase
- Step: `Phase X Step N: <anything>` matches plan step `X.N` or `Step N`
  within the phase

Classify into buckets:

| Bucket | Condition | Default action |
|---|---|---|
| **CREATE umbrella** | Plan has phase, no umbrella issue | Create with full body |
| **CREATE step** | Plan step has no matching issue | Create with rich body |
| **ENRICH** | Issue exists, body is lean (≤2 sections), plan now has richer content | Update body (auto if `--enrich` OR if plan has clear new fields) |
| **UPDATE** | Issue exists but title or body changed substantively | Update |
| **CLOSE** | Issue exists, plan step removed | Close with comment |
| **NO-OP** | Issue exists, body is rich, no plan change | Skip |

### Step 5 — Preview

Print all proposed changes grouped by phase:

```text
repo-sync: documentation/plans/phase-d-build-plan.md (Phase D)

  Build doc richness: 3/8 steps rich, 5/8 lean

  CREATE umbrella  Phase D — Build-order z-statistic (reward refactor)
  CREATE step      Phase D Step 1: Audit reward_rules.json (rich body)
  CREATE step      Phase D Step 2: Define z schema (rich body)
  CREATE step      Phase D Step 3: build_order_reward.py (lean — Files missing)
  ENRICH           Phase D Step 5 (#168) — body lacks Done when + Files
  UPDATE           Phase D Step 7 (#170) — title changed
  CLOSE            (none)
  NO-OP            (none)
```

If `--dry-run` was specified, stop here and print:

```text
Dry-run complete. No changes applied.
```

Otherwise, proceed directly to Step 6 — print `Applying changes now...`
and execute. **Do not prompt for confirmation.** The preview is the
operator's read-out, not a halt point; autonomous orchestration
(`/build-phase`, `/plan-expedite`) depends on this.

#### --dry-run flag

When `/repo-sync --dry-run` is invoked, the preview above is printed but
no changes are applied. The skill exits cleanly with the message
`Dry-run complete. No changes applied.` Use this to validate plan→issue
mapping before committing to a sync.

### Step 6 — Execute (one tool call per gh action)

Process in this order:
1. Umbrella issues first (so step issues can reference them)
2. Step issue creates
3. Step issue enrichments + updates
4. Closes last

Each `gh issue create/edit/close` is its own Bash tool invocation, OR a
loop in one Bash with explicit per-iteration error handling. Do NOT
batch with `&&` — one failure must not break the chain.

#### Body delivery — always use `--body-file`

All `gh issue create/edit` calls in this skill MUST deliver bodies via `--body-file <path>`, never inline `--body "$(cat <<EOF ... EOF)"`. The inline heredoc form silently truncates or parser-tangles bodies that contain nested quote levels (code spans, quoted text, tables) — see `dev/.claude/rules/windows-shell.md` § gh / jq.

Use a Windows-safe temp path:
- Bash: `$LOCALAPPDATA/Temp/` (the Windows per-user temp dir, not `/tmp`)
- PowerShell: `$env:TEMP`

POSIX `/tmp/` is invisible to `gh.exe` on Windows (different temp roots).

The Create / Update / Close templates below all assume this delivery method.

#### Body template — umbrella

```markdown
**Umbrella:** #<master-plan-umbrella-issue-if-exists>
**Blocked by:** Phase <prerequisite-phase-if-any>
**Build doc:** `<build-doc-path>` (linked to `../blob/master/<build-doc-path>`)
**Track:** <track-from-plan>

## Goal

<goal paragraph from plan>

## Work (N steps)

- [ ] **#<step-1-issue>** Step 1: <name>
- [ ] **#<step-2-issue>** Step 2: <name>
...

(Step issue numbers populated after step creates — re-edit umbrella in Step 7.)

## Acceptance

<validation / acceptance from plan>

## Effort

<effort estimate from plan>

## Kill criterion

<kill criterion from plan>
```

#### Body template — step

```markdown
## Build step N of M — Phase <X> (umbrella #<umbrella-issue>)

**Build doc:** `<build-doc-path>` (linked to `../blob/master/<build-doc-path>`) §<section> Step <X.N>

### What to build
<full description from plan, not abbreviated>

### Existing context
<from plan's "Existing context" section if present, scoped to this step>
<otherwise: omit (will be flagged in summary)>

### Files to modify/create
<file list from plan if present>
<otherwise: omit (flagged in summary)>

### Done when
<acceptance from plan, specific not generic>
<otherwise: "All tests green, mypy strict + ruff clean. See umbrella for phase-level gate.">

### Flags (recommended)
<build-step flags from plan if present, e.g. `--reviewers code --isolation worktree`>
<if step touches frontend/, /api/ shapes, or WebSocket payloads: ALSO include `--ui`>

### Depends on
<previous step issue # if known, or "none">

### Parallel-safe with
<list any open step issue # in the same phase that shares no Files and no
Depends-on with this step. When no such peers exist, write
`none — strictly sequential (<one-line justification>)`. The justification
is REQUIRED — bare "strictly sequential" without a reason hides the
choice from the operator. Acceptable justifications: "Step N+1 imports
this module", "shares <Files entry> with #X", "soak gate after Step N
must finish first". When the plan is lean (no Depends on, no Files
declared), default to listing peers as parallel-safe rather than
collapsing to strictly sequential.>

### Produces
<list from plan if present>

### Operator workflow notes (autonomous + UI-bundle + parallel)
- This step is intended to run end-to-end via `/build-step` without
  mid-iteration check-ins; the `Done when` above is the verification gate.
- If `--ui` is in the Flags line above, UI evidence (Playwright screenshot,
  or any project-specific UI/dashboard smoke commands defined in the
  project's `CLAUDE.md`) is part of acceptance, not a follow-up.
- Parallel-safe pairs above can be dispatched in parallel worktrees by
  `/build-phase`.

---
*Synced from `<plan>` (linked to `../blob/master/<plan>`) by /repo-sync at <git-short-sha>*
```

The footer with the source path + SHA helps a future LLM verify whether
the issue body is current vs the build doc.

Sections without source content can be omitted, but **issues missing
>2 of {Existing context, Files, Done when, Flags, Produces} are flagged
in the summary** as candidates for follow-up enrichment.

#### Update / enrich

```bash
# Windows-safe temp path; POSIX /tmp/ is invisible to gh.exe.
BODY_FILE="$LOCALAPPDATA/Temp/repo-sync-issue-$NUMBER.md"
cat > "$BODY_FILE" << 'BODYEOF'
<full new body following template>

---
*Enriched by /repo-sync from <build-doc-path> @ <git-short-sha>*
BODYEOF
gh issue edit <NUMBER> --title "<title>" --body-file "$BODY_FILE"
rm "$BODY_FILE"
```

#### Close

```bash
gh issue close <NUMBER> --comment "Closed by /repo-sync — step removed from plan."
```

### Step 7 — Re-edit umbrellas with step references

After step issues are created, edit each phase's umbrella issue to
include the **Work** checklist with actual issue numbers:

```markdown
## Work (N steps)

- [ ] **#164** Step 1: Audit reward_rules.json
- [ ] **#165** Step 2: Define z schema
...
```

This creates bidirectional cross-refs that an LLM can follow either
direction. Without this, the umbrella has stale `<step-1-issue>`
placeholders or a generic `(steps will be cut by /repo-sync)` note,
which forces the LLM to do a separate `gh issue list` to find them.

### Step 8 — Report

The final line of the report MUST surface this skill's plan-pipeline
position — `step 4 of 5: after /plan-review + /plan-wrap, before
/build-phase` — so the operator and any fresh-context downstream LLM
see at a glance what runs next. The breadcrumb is non-optional.

```text
repo-sync complete for Phase D (umbrella #114)
Plan pipeline: /plan-review + /plan-wrap → /repo-sync (step 4 of 5) → /build-phase

  Created: 1 umbrella, 8 step issues (#164–#171)
  Enriched: 0
  Updated: 0
  Closed:  0

  Body richness: 3/8 issues fully rich; 5/8 missing Files/Existing-context
  Cross-refs: umbrella #114 updated with step issue links

  Recommendation: build-doc step richness was lean (5/8). Consider
  enriching documentation/plans/phase-d-build-plan.md with explicit
  per-step Files / Done when / Existing context sections, then
  re-run with --enrich to bring issues to richer state.
```

If new issues were created, the operator (or the orchestrator)
backfills the plan's `**Issue:**` lines so `/build-phase` can post
progress updates — e.g., via the pattern below. The skill itself
does not back-propagate; surfacing the pattern is enough for the
operator to run once after sync.

Copy-paste bulk-fill snippet (Python). Adapt the `ISSUE_MAP` from
the sync output's "Created" / "Enriched" mapping:

```python
# Backfill **Issue:** #N lines after /repo-sync.
# Save the sync output's "Created" or "Enriched" mapping as
# {step_number: issue_number}, e.g.:
ISSUE_MAP = {
    1: 164,   # Step 1 -> issue #164
    2: 165,
    # ...
}

import re, pathlib
# REPLACE <plan-file> with your plan's actual filename,
# e.g. "documentation/phase-rs-plan.md".
plan = pathlib.Path("documentation/<plan-file>")
text = plan.read_text(encoding="utf-8")
for step_n, issue_n in ISSUE_MAP.items():
    # Match Step N heading, then the immediately-following
    # **Issue:** line (which may be #N, TBD, or empty).
    # No re.DOTALL: `.` does not match newlines, so `.*?\n`
    # stays within a single line and the bullet-eater group
    # matches only consecutive single-line bullets. If a step
    # is missing its **Issue:** bullet entirely, the pattern
    # fails to match for that step and the script safely skips
    # it (no cross-step contamination).
    pattern = (
        rf"(### Step {step_n}:.*?\n(?:- \*\*[^*]+\*\*.*?\n)*?"
        rf"- \*\*Issue:\*\* )(#\d+|TBD|)"
    )
    text = re.sub(pattern, rf"\g<1>#{issue_n}", text)
plan.write_text(text, encoding="utf-8")
```

Verification — after a fully-populated backfill, the following
returns empty (no remaining `TBD` or blank `**Issue:**` values).
REPLACE `<plan-file>` with your plan's actual filename:

```bash
grep -nE "Issue:\*\*\s*(TBD\s*$|#\s*$|$)" documentation/<plan-file>
```

This pattern is one instance of the broader bulk-placeholder-fill
discipline (see `feedback_bulk_placeholder_fills.md`). Background
and rationale in investigation
`docs/investigations/skill-deep-dives/repo-sync/03-issue-blank-lines-kill-build-phase.md`.

---

## Matching rules (extended)

Issue matching is prefix-based on the step key. The skill normalizes:
- Whitespace
- Phase notation: `Phase D` ≡ `Phase D` (no normalization across letter/digit; B != 2; D != 4)
- Sub-phase: `Phase G.2 Step 1` matches plan `G.2.1` or `Step 1` within phase G.2

Manually renamed issue titles still match as long as the step prefix
(`Phase X Step N` or `Phase X.M Step N`) is preserved.

---

## Edge cases

- **Cross-plan step-key collision:** Step keys collide when a
  repo holds issues from multiple plans (`Phase D Step 3`
  exists in plan A and plan B). The Step 3.1 check (see Flow)
  flags these via the body footer's plan path. Workaround for
  new plans that share step keys with closed prior plans:
  bypass `/repo-sync` for the new plan and create issues
  manually with namespaced titles (`<feature> — Phase X Step
  N: <name>`); those manual issues will not be re-matched by
  future runs. See investigation
  `docs/investigations/skill-deep-dives/repo-sync/01-step-key-collision.md`.
- **Closed issue, step still in plan:** Show as `REOPEN?` in preview. Require explicit confirmation.
- **Multiple issues match same step key:** Warn and skip — user must resolve manually.
- **Plan has no umbrella H1, just steps:** Skip umbrella creation; only step issues.
- **No steps found:** Error: `No steps found in <path>. Expected "### Step N:", "### Phase X Step N:", or "| X.N | ... |" table row.`
- **No GitHub repo:** See Step 0 — Pre-flight. The resolve command halts early if no repo is found.
- **Numbering gaps:** If plan jumps from Phase 7 to Phase 9 (intentional), don't try to create Phase 8. Honor the plan as written.
- **Existing umbrella, plan adds new steps:** Create new step issues + re-edit umbrella to add their links.
- **Step issue exists but lean, build doc still lean:** ENRICH would be a no-op. Recommend doc enrichment in summary; do not edit issue.

---

## Common mistakes

**Batching gh calls in one shell command**
- Fix: One `gh issue create/edit/close` per call, separate Bash tool invocations OR a loop in one Bash with explicit per-iteration error handling.

**Halting mid-sync for confirmation**
- Fix: Preview-then-execute is the default; no `(y/n)` prompt. Operators who want preview-only behavior pass `--dry-run`. Autonomous orchestrators (`/build-phase`, `/plan-expedite`) depend on this — a mid-sync halt breaks them.

**Matching by issue number instead of title prefix**
- Fix: Issue numbers change. Always match by the step-key prefix in the title.

**Using Perl-style regex escapes in `--jq` filters**
- Fix: jq's regex engine does NOT accept `\d`, `\w`, `\s`, `\.`
  (and most other Perl-style shorthand). It silently rejects
  the filter or returns empty matches — failing the
  classification, which then surfaces as duplicate-issue
  CREATEs in Step 5 preview. Use POSIX classes or literal
  character sets:

  | Avoid | Use |
  |---|---|
  | `\d` | `[0-9]` |
  | `\w` | `[a-zA-Z0-9_]` |
  | `\s` | `[ \t\n\r]` (POSIX whitespace; or the named class with single-bracket pairs the engine supports) |
  | `\.` | `[.]` |

  Prefer regex-free forms when the prefix is fixed:
  `startswith("Phase D")` beats `test("^Phase D")` and
  sidesteps the escape limit entirely.

  Reference: `feedback_jq_regex_escape_limits.md` and
  investigation `docs/investigations/skill-deep-dives/repo-sync/13-jq-regex-escaping.md`.
  PowerShell-specific quoting issues for `gh -q` are
  documented in `dev/.claude/rules/windows-shell.md` § gh / jq.

**Lean bodies on creation**
- Fix: Run the doc richness check first. If steps are lean, propose enriching the build doc before creating issues. Don't normalize lean issues as the steady state.

**Forgetting umbrella back-references**
- Fix: After creating step issues, edit the umbrella to include the **Work** checklist with issue numbers. Bidirectional links matter.

**Ignoring sub-phase notation**
- Fix: Phase G.2 is its own phase, not "Phase G". Match titles accordingly.

**Skipping the doc-richness warning**
- Fix: A lean issue taxes future LLM sessions every time someone opens it. Surface this cost explicitly; default to enriching the doc first.

**Treating issue creation as one-shot**
- Fix: `--enrich` exists because issues drift behind build docs over time. Re-run the skill after each plan revision.
