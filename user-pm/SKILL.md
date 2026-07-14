---
name: user-pm
description: Tight PM-lens overview of a project — what shipped, what's planned, what we could do next, and what could be cut. Default mode emits a four-section snapshot; a topic flag (`--uat` / `--test` / `--build` / `--decide` / `--overnight` / `--goal` / `--other` / `--cut` / `--history` / `--outstanding`) drills into one topic with context + what-it-unblocks + the work. Use when the user asks for a project overview, status snapshot, "where are we / what's next", or wants to challenge plan assumptions.
---

# user-pm

Write a scannable project overview. **Be terse.** Bullets only, one line each, no narration.

Use one of two modes:

- **Default (no flag).** Four-section snapshot — see the "Default output format" section below.
- **Topic-focused (one of `--uat` / `--test` / `--build` / `--decide` / `--overnight` / `--goal` / `--other` / `--cut` / `--history` / `--outstanding`).** Three-part deep dive on that topic only — see the "Topic-focused mode" section below. `--uat` is an alias for `--test`.

If multiple topic flags are passed, use the first and note the others were ignored in one line. If an unknown flag is passed, fall back to default mode and note the unrecognized flag in one line.

## Steps

1. **Read the plan.** Try in order: `documentation/plan.md`, `plan.md`, `README.md`. Skim the status table or equivalent.
2. **Read recent git activity.** `git log --oneline -30`. Note the most recent shipped milestone.
3. **Check archived/done markers.** Phases marked ✅, ARCHIVED, or COMPLETE in the plan, plus any in `**/archive/`.
4. **Output the sections for the chosen mode.** No preamble, no closing summary.

## Default output format

```markdown
# <project> — at a glance

**What it is:** <one sentence — the elevator pitch from the plan>

## History (shipped)
- **Phase/milestone X** ✅ <date> — <one-line outcome>
- ...

## Outstanding (on the plan, not done)
- **Item** — <one-line scope + why it's still open>
- ...

## Possible next moves

Group each move under one of the five category headers below. Order moves by overall leverage; within a category, order by leverage too. Skip a category header entirely if it has no moves — don't print empty headers. Aim for 3–6 moves total across all categories.

### Test (operator runs a check)
- **<Move>** — <one-line rationale>
  - **Setup:** <copy-paste commands to start the test environment, in the user's shell — PowerShell on Windows>
  - **What to verify:** <pass/fail criteria; one row per check, table form if more than 2>

### Build (run a command to build)
- **<Move>** — <one-line rationale>
  - **Run:** <a slash command or shell command>
  - <if more than one step, list them tersely; if the move needs a plan first, say which `/plan-*` skill to invoke and what to seed it with>

### Decide (need plan-level input from user)
- **<Move>** — <one-line rationale + open questions>
  - <question 1>
  - <question 2>
  - **Once decided:** <the next concrete action — usually a doc edit + `/repo-sync` or similar>

### Overnight (autonomous /build-phase candidate)
- **<Move>** — <why this is autonomous-safe in one line>
  - Plan: [`<path>`](<path>) § <section>
  - Prereqs: <e.g., `/plan-review` pending; `/repo-sync` to fill blank `**Issue:** #` lines; frontend touches need `--ui`>
  - Run: `/build-phase --plan <path> [--phase N] [--steps a,b,c]`

### Other (no code, no command — board hygiene, real-use, deferred decisions)
- **<Move>** — <one-line rationale>
  - **Steps:** <copy-paste commands OR a short explanation of the manual flow>

## Candidates to cut
- **<Item>** — <the unexamined assumption, and why it might not hold>
- ...
```

## How to pick the category for each move

- **Test** — there's existing code in master that needs a human to confirm it works. Operator-led smoke gates, iPad UAT, "verify X is wired", spot-checking real data. The deliverable is a run-doc or a PASS verdict, not a diff.
- **Build** — there's identified work to do, but it's not yet on a runnable plan. Includes "write the plan first then run /build-phase" cases — those go under Build, not Overnight, until the plan exists.
- **Decide** — the move is blocked on a plan-level choice only the user can make (hardware purchase, scope cut, threshold change, whether to deprecate X). Surface the open questions and the next action after the decision lands.
- **Overnight** — moves that meet ALL the rigor criteria below. If a move would qualify *after* a plan is written, it goes under Build now and migrates to Overnight on the next user-pm pass.
- **Other** — everything else. Board hygiene (close shipped-but-open issues), passive-use accumulation, "wait for X to happen", "deprecate this manually". These often shouldn't appear in the snapshot at all — only include them if the user has a real action to take.

If a single move plausibly fits two categories, pick the one that describes the *user's next concrete action*. Example: "ship Phase J" — the code is in master, the next action is operator UAT → that's Test, not Build.

## Overnight category — qualification rubric

Check the Overnight rubric: a move qualifies only if `/build-phase` could run it unattended through morning without a human in the loop. Apply ALL of:

- **Plan format ready.** Steps already use `### Step N` + `**Problem:**` + `**Type:**` + `**Issue:** #<n>` + `**Flags:**` headers (or are trivially extendable). Table-only or bullet-only plans don't qualify until extended — surface them under Build instead.
- **Issues synced.** No blank `**Issue:** #` lines — they kill the build-phase audit trail. If missing, the prereq line in the candidate should say `/repo-sync` first.
- **No manual gates inside the run.** Operator UAT, soak observation, "operator runs M2", `Type: operator`, `Type: wait`, conditional steps — any of these halts overnight progress. Steps gated on a 4–8h soak don't fit either; surface those under Test as next-day work.
- **Reviewer flags match step shape.** `--reviewers full` requires `--start-cmd` + `--url`. Backend-only / unit-test-only steps must be `code`. Mismatch = build-phase aborts.
- **Frontend touches need `--ui`.** Any step changing `frontend/`, `/api/...` shapes, or WebSocket payloads must have `--ui` in `**Flags:**`. Code-only review on UI work is the known gap.
- **Worktree-safe.** Multiple steps editing the same shared file (routes module, central config) overwrite each other on merge. If two candidate steps both rewrite the same file end-to-end, surface ONE per night, not both in parallel.
- **No external dependencies a human has to set up overnight** (game client, paid API quota refresh, hardware reboot).

Prefer substrate moves (foundational layer, not a single capability) over capability moves at equal effort — substrate compounds across future work.

Skip the Overnight header entirely if nothing in the plan currently meets the bar. Do not say "Nothing autonomous-ready" as a placeholder — just skip the section.

## The "Candidates to cut" section is the point

Most overviews just regurgitate the plan. This skill earns its keep by **challenging unexamined gates and scope**. For each candidate, name the assumption out loud:

- **Time/data gates** ("≥1 month of telemetry before X") — is that number load-bearing or vibes? Could you start with what you have?
- **Sub-goals already met elsewhere** — a phase scoped to do A+B may have had B shipped under a different phase. Split it.
- **UAT gates that got de-facto validated** — if later phases exercised the same code paths and passed, the gate may be ceremony.
- **Archived plan docs still referenced** — once a path is dead, the archive entry shouldn't be in the doc map.
- **"Polish" / "hardening" phases without a concrete failure mode** — if you can't name what breaks today, the phase is preemptive.
- **Eval scaffolds nobody runs** — fixtures rot. If they haven't been touched in N commits, they're not load-bearing.

Default to 3–6 candidates. Each one should be specific enough that the user can say "yes cut it" or "no, here's why it stays" without asking a follow-up.

## Topic-focused mode

When invoked with one of `--uat` / `--test` / `--build` / `--decide` / `--overnight` / `--goal` / `--other` / `--cut` / `--history` / `--outstanding`, replace the four-section snapshot with a deep dive on that one topic. The qualification rules and assumption-challenging stance from the default mode still apply.

### Shared three-part shape

```markdown
# <project> — <topic>

## Context (what's already shipped that informs this)
- <bullets — only the shipped work that matters to this topic, not the whole history>

## What this unblocks
- <bullets — concrete downstream effects: phases that gate on this, decisions that depend on it, candidates-to-cut that become safe-to-cut once this lands>

## The work
<topic-specific format — see below>
```

Be honest in **What this unblocks**. If completing this topic doesn't unblock anything load-bearing, say so in one line — that's a signal the topic is itself a cut candidate, and the user should see it.

### Per-topic specifics for "The work"

- **`--uat` (alias) / `--test`** — every operator-led validation worth running now, ordered by leverage. Per move:
  - **Setup:** copy-paste commands in the user's shell (PowerShell on Windows).
  - **What to verify:** pass/fail criteria in table form when there's more than 2 rows.
  - **If it fails:** the one next action (file an issue at `<repo>` with these reproduction steps, roll back commit `<sha>`, etc.).

- **`--build`** — code work that's identified but not yet on a runnable plan. Per move:
  - **Why now:** one-line rationale tied to **What this unblocks**.
  - **Run:** either a `/plan-feature` invocation (with the seed text to paste in) if no plan exists yet, or the slash command sequence if it does.
  - **Risks:** anything from [code-quality.md](../../rules/code-quality.md) or [worktree-hygiene.md](../../rules/worktree-hygiene.md) that this move could trip.

- **`--decide`** — plan-level choices blocking forward motion. Per move:
  - **Open questions:** the actual fork(s) in the road, phrased so the user can answer "A" or "B" without restating context.
  - **Once decided:** the next concrete action — usually a doc edit + `/repo-sync`, or which `/plan-*` skill to invoke.
  - **Cost of waiting:** what slips or stays ambiguous while the decision is open (often this is what **What this unblocks** points at).

- **`--overnight`** — moves that pass the Overnight qualification rubric (see earlier section). Per move:
  - **Plan:** `[path](path)` § section.
  - **Prereqs:** explicit list — `/plan-review` pending, `/repo-sync` to fill blank `**Issue:** #`, `--ui` flag needs adding, etc.
  - **Run:** `/build-phase --plan <path> [--phase N] [--steps a,b,c]`.
  - If nothing currently qualifies, say so in one line and point to the closest-to-ready candidate plus what it'd take to qualify (usually `/plan-review` + `/repo-sync`). Don't pad with capability moves dressed up as Overnight.

- **`--goal`** — work items a fresh window can drive to a **binary, checkable stop condition** under `/goal`, each rendered as a single ready-to-paste line. Distinct from `--overnight`: `--goal` needs no plan format, no synced issues, no `/build-phase` rail — just a condition a fast model can verify each turn. The harness's `/goal` Stop hook keeps the session grinding across turns and auto-compactions until the condition resolves. Reach for it when "done" is nameable but a full build-phase plan is overkill: get a suite green, close issue #N, lift an eval score past a threshold, finish a bounded bug fix. For this mode, **Context** = the shipped substrate that makes these goals runnable now; **What this unblocks** = what each met goal clears downstream. Per candidate under **The work**:
  - **Stop condition:** one binary, externally-checkable criterion — `pytest` exits 0, PR #N merged, `<file>` exists, count == N. Hold it to user-draft's GOAL bar (its Step 3b): reject anything unmeasurable ("bot is better", "code is clean") and rewrite until a fast model could check it every turn. Fold in guardrails inline when the work needs them ("…without touching the public API").
  - **Open:** if one point of the condition can't be pinned down in a single pass (which suite counts as "green", what threshold, which of two files), name it declaratively in one line — no question mark, no waiting. Omit this sub-bullet entirely when the condition is unambiguous. user-pm surfaces the gap as data, the way `### Decide` does, and never blocks on it; resolving it is the one job handed to `/user-draft`.
  - **Ready to paste:** exactly one line per candidate. With **no Open point**, emit the fresh-window pair in a fenced block — `/task-handoff --resume` then `/goal "<condition>"` (the resume line self-orients the new window; droppable for same-window use). With an **Open point**, emit instead `/user-draft <seed>`, where the seed carries the candidate + draft condition + the open point — so the new window starts by clarifying and user-draft's GOAL branch ends by emitting the finished `/goal` line. This is why user-pm inlines user-draft's standard rather than invoking it per candidate: it stays one-pass, and the interactive clarify happens in the window the user chooses to open.
  - **Skip** any item blocked on operator action, hardware, or an external dependency a fresh window can't satisfy — those aren't goal-drivable; route them to `--test` or `--decide` instead.
  - Close **The work** with a mandatory `QUICK COPY (one per window)` block — the single paste-line for each candidate (`/goal "<condition>"` for ready ones, `/user-draft <seed>` for ones with an Open point), one per line — so each new window either starts the goal or starts the clarify-then-goal pass.
  - If nothing currently has a checkable stop condition, say so in one line and name the closest candidate plus the criterion it'd need. Don't dress a fuzzy task up as a goal.

- **`--other`** — board hygiene, deferred passive-use accumulation, real-world wait states. Per move:
  - **Steps:** the manual flow or copy-paste commands.
  - Be ruthless: if the move has no real user action (just "wait"), drop it. Same bar as default mode's Other category.

- **`--cut`** — the assumption-challenging core of the skill. Per candidate:
  - **The candidate:** plan section/phase/gate by name.
  - **The unexamined assumption:** name it out loud (load-bearing number? sub-goal already met? ceremony gate? preemptive hardening?).
  - **What survives the cut:** what's left of the surrounding scope if this is dropped.
  - **What you'd be wrong about if you cut it:** the strongest reason to keep it. If you can't articulate one, say so — that's a strong cut signal.
  - **What this unblocks** in this mode is "focus / time / which next move becomes top-of-stack", not a downstream phase.

- **`--history`** — fuller breakdown of shipped milestones than the default's one-line bullets. Per milestone:
  - **Date + ✅ + name.**
  - **Outcome:** what changed in the product, not what the commits did.
  - **Notable surprises:** anything that came in as a bonus or got descoped during execution.
  - Cap at the last ~10 milestones; older items collapse to a one-line "earlier: ...".
  - **What this unblocks** in this mode is "remind the user what foundation they're standing on" — keep it short.

- **`--outstanding`** — fuller breakdown of open plan items than the default's one-line bullets. Per item:
  - **Item name + status marker (planned / blocked / in-progress).**
  - **Scope:** one or two lines.
  - **What's blocking it now:** if anything (decision, prereq, drift, just hasn't been picked up).
  - **Closest path forward:** which mode/flag would move it next (`--uat`, `--build`, `--decide`).
  - Skip items that are trivially done-but-unmarked — surface those under board hygiene in default mode instead.

## Tone

- No emojis unless the plan uses them. ✅ for shipped status is fine since most plans use it.
- File/line references use `[path](path)` markdown links.
- Don't recommend skill invocations gratuitously. **Exceptions:** the `Build` and `Overnight` sub-categories under "Possible next moves" explicitly propose slash commands or `/build-phase` invocations — that's their whole job; `--goal` mode emits `/goal`, `/task-handoff --resume`, and `/user-draft` lines as its deliverable. `Test` and `Other` use shell commands when commands apply.
- Don't ask clarifying questions. If the plan is missing or ambiguous, say so in one line and proceed with what you have.

## Constraints

- Read-only — never edit plan docs, issues, or code while producing the snapshot.
- Don't invent moves not derivable from the plan + git log + archive markers.
- One-pass — no follow-up iterations after emitting the snapshot.

## Limitations

- Plan must exist at `documentation/plan.md`, `plan.md`, or `README.md`; otherwise the snapshot will be sparse.
- Stale plan docs produce stale snapshots — this skill does not re-read git log to second-guess plan-marked status.
- Overnight qualification is a heuristic, not a guarantee — the rubric catches common misroutes but cannot detect every silent precondition.


---

## dev-observatory hook (additive; see [`.claude/rules/descriptor-contract.md`](../../rules/descriptor-contract.md))

**`--json` output mode (additive).** When invoked with `--json`, emit the snapshot as ONE structured JSON object instead of prose, so a tool (e.g. dev-observatory's on-demand goal-vs-reality review) can render it: each default section (`history`, `outstanding`, `possible_next`, `cut_candidates`) and any topic-mode payload becomes a top-level key; prose bullets become arrays of objects. The prose modes are unchanged when `--json` is absent.
