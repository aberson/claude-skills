# claude-skills

A collection of [Claude Code](https://docs.anthropic.com/claude-code) skills for planning, building,
reviewing, and shipping software with AI agents. These are the real workflow skills I use day to day,
lightly generalized for sharing.

> Extracted from a personal workspace. Paths and identifiers are generalized to placeholders
> (`<workspace>`, `<project>`, `<your-org>`). A few skills reference personal conventions — a
> workspace "control plane" and a file-based memory system — that you would adapt to your own setup.

## What's inside

Each skill name links to its `SKILL.md`.

**Core pipeline** — plan → build → review → ship:

| Stage | Skills |
|------|--------|
| **Planning** | [plan-init](plan-init/SKILL.md) · [plan-feature](plan-feature/SKILL.md) · [plan-review](plan-review/SKILL.md) · [plan-wrap](plan-wrap/SKILL.md) · [plan-merge](plan-merge/SKILL.md) · [plan-trim](plan-trim/SKILL.md) · [plan-expedite](plan-expedite/SKILL.md) |
| **Building** | [build-step](build-step/SKILL.md) · [build-phase](build-phase/SKILL.md) · [build-queue](build-queue/SKILL.md) |
| **Review** | [review-deep](review-deep/SKILL.md) · [review-gauntlet](review-gauntlet/SKILL.md) · [review-proof](review-proof/SKILL.md) · [review-uat](review-uat/SKILL.md) |
| **Repo & docs** | [repo-init](repo-init/SKILL.md) · [repo-sync](repo-sync/SKILL.md) · [repo-update](repo-update/SKILL.md) |

**Supporting**:

| Area | Skills |
|------|--------|
| **User & session** | [user-fix](user-fix/SKILL.md) · [user-brainstorm](user-brainstorm/SKILL.md) · [user-draft](user-draft/SKILL.md) · [user-learn](user-learn/SKILL.md) · [user-orient](user-orient/SKILL.md) · [user-pm](user-pm/SKILL.md) · [user-recap](user-recap/SKILL.md) · [user-shakedown](user-shakedown/SKILL.md) · [user-uat](user-uat/SKILL.md) · [user-walkthrough](user-walkthrough/SKILL.md) · [session-wrap](session-wrap/SKILL.md) · [task-handoff](task-handoff/SKILL.md) · [research-prospect](research-prospect/SKILL.md) |
| **Skill tooling** | [skill-eval-setup](skill-eval-setup/SKILL.md) · [skill-evolve](skill-evolve/SKILL.md) · [skill-iterate](skill-iterate/SKILL.md) |
| **Maintenance & hygiene** | [test-prune](test-prune/SKILL.md) · [lesson-harvest](lesson-harvest/SKILL.md) · [memory-distill](memory-distill/SKILL.md) · [context-slim](context-slim/SKILL.md) |
| **Reference** | [claude-oauth-auth](claude-oauth-auth/SKILL.md) |

`_shared/` holds resources referenced by several skills.

The design idea across all of these: treat agent work as a **pipeline with quality gates** — plan,
build one step at a time, review with independent adversarial passes, and only then ship. Several
skills use multi-agent fan-out (parallel reviewers, judge panels, generate-then-grade loops).

## Workflows

The tables above list what each skill *is*; this section maps how they **chain together** in
practice. Every sequence below is a workflow I actually run — commands are copy-pasteable. The
detailed write-ups are collapsed; click a heading to expand it.

Two notes on reading the maps:

- `/goal`, `/loop`, `/schedule`, and `/deep-research` are built-in Claude Code commands, not skills
  in this repo — several skills emit or arm them.
- Pipeline skills are **autonomous by default**: no mid-run "(y/n)?" prompts. Conversational skills
  (`plan-init`, `plan-feature`, `plan-merge`, `plan-trim`, the `user-*` ideation skills) stop and ask
  by design.

### The core pipeline

Plan → sync → build → ship. Everything else supports this spine.

```mermaid
flowchart TD
    subgraph PLAN["PLAN"]
        direction LR
        A["plan-init (new)<br>plan-feature (existing)"] --> B["plan-review"] --> C["plan-wrap"]
    end
    subgraph SYNC["SYNC TO GITHUB"]
        direction LR
        D["repo-sync<br>(first time: repo-init)"]
    end
    subgraph BUILD["BUILD"]
        direction LR
        E["build-phase"] --> F["build-step &times; N"] --> G["review gates<br>(review-gauntlet / review-deep)"]
    end
    subgraph SHIP["SHIP"]
        direction LR
        H["acceptance UAT<br>(review-uat/user-uat,<br>walkthrough/shakedown)"] --> I["repo-update"]
    end
    PLAN --> SYNC --> BUILD --> SHIP
```

`plan-expedite` collapses the middle — `plan-review → plan-wrap → repo-sync → handoff` — into one
autonomous command, and ends by printing the exact `/goal` + `/build-phase` pair to paste next.

Ordering matters in two places:

- **plan-review before repo-sync.** A gap caught *after* issues are minted means editing the plan
  plus N issue bodies (the "N+1 edit" trap).
- **repo-sync before build-phase.** build-phase posts live progress to the issues repo-sync
  created; blank `Issue:` lines kill the audit trail.

### Pick your entry point

| Situation | Start with |
|---|---|
| Brand-new project, no code yet | `/plan-init` — §1 |
| Add a feature to an existing project | `/plan-feature` — §2 |
| One well-scoped change, no plan needed | `/build-step` — §3 |
| Stuck in a loop on a bug with the agent | `/user-fix` — §4 |
| Review a diff or PR | `/review-gauntlet` or `/review-deep` — §5 |
| A feature just built needs human acceptance | §6 |
| Several phases ready; run them overnight | `/build-queue` — §7 |
| "Where were we?" / context filling up | §8 |
| Plan drifted, or survey what to do next | §9 |
| Improve the skills or the workspace's memory | §10 |
| Explore an idea or learn a topic | §11 |

<details>
<summary><strong>1. New project → shipped v1</strong></summary>

```
/plan-init                          # structured conversation → plan.md
/repo-init                          # first time only: git init, GitHub repo, README, plan → issues
/plan-expedite --plan plan.md       # autonomous: plan-review → plan-wrap → repo-sync → handoff
```

`plan-expedite` finishes by printing a ready-to-paste pair — arm the goal, then build:

```
/goal "<completion condition it emitted>"
/build-phase --plan plan.md
```

Then wrap the phase:

```
/repo-update                        # README, plan doc, memory, commit, posterity issue, push
```

- `plan-init` is gated to greenfield: if the project has *any* commit it stops and redirects to
  `plan-feature`.
- `build-phase` reads `### Step N:` blocks from the plan, spawns one `build-step` per code step,
  posts progress to the GitHub issues, and only halts for five legitimate reasons (quality-gate
  hard fail, wait-type step, merge conflict, bad conditional predicate, stop-and-audit).

</details>

<details>
<summary><strong>2. Feature on an existing project</strong></summary>

Same spine, different front door:

```
/plan-feature <one-liner>                                   # reads the codebase, asks about the delta
/plan-expedite --plan documentation/<feature>-plan.md
/goal "<emitted condition>"
/build-phase --plan documentation/<feature>-plan.md
/repo-update
```

Prefer the à-la-carte version when you want to inspect between stages:

```
/plan-review documentation/<feature>-plan.md    # technical gaps, risks (autofix on by default)
/plan-wrap documentation/<feature>-plan.md      # self-containment for a fresh-context model
/repo-sync --plan documentation/<feature>-plan.md
/build-phase --plan documentation/<feature>-plan.md
```

- `plan-review` and `plan-wrap` check different things: review finds *technical* gaps; wrap checks
  the doc is *self-contained* for a model with zero conversation history (issue bodies and
  autonomous builds depend on that).

</details>

<details>
<summary><strong>3. One-off change, no plan</strong></summary>

```
/build-step --problem "<what to build or fix>" [--issue N]
```

One skill, three independent knobs:

- `--isolation worktree|docker` — where the developer agent works (worktree default).
- `--reviewers auto|code|runtime|full` — `auto` = quality gates only; `code` = 4 parallel
  review-gauntlet agents; `runtime` = 3 evidence-based reviewers; `full` = all seven.
- `--ui --start-cmd "<cmd>" --url <url>` — Playwright evidence capture for frontend steps.

</details>

<details>
<summary><strong>4. Getting unstuck on a bug (user-fix)</strong></summary>

```
/user-fix --symptom '<exact error / log line / misbehavior>'
```

- Reach for it when a bug keeps **circling between you and the agent** — command-paste back-and-forth
  that isn't converging. It forces primary-source investigation and an **independent reproduction
  before any code change**, then delegates the fix to `build-step` and re-runs the original repro to
  prove the symptom is gone.
- It's operator-invoked when *you're* stuck, not a plan-driven step — which is why it lives with the
  `user-*` skills rather than the `build-*` pipeline. (It still writes real code via `build-step`.)
- `--triage investigate-only` stops after the diagnosis block — root cause without the fix.

</details>

<details>
<summary><strong>5. Reviewing a diff on its own</strong></summary>

Both review skills also run standalone, outside `build-step`:

```
/review-gauntlet                     # routine diffs: 4 parallel lenses (correctness, bugs, tests, style)
/review-deep --prompt '<intent>' --diff <PR# | git diff | paste>    # high-stakes: 5 lenses + JSON audit trail
```

- Reach for `review-deep` on substrate/schema/key-shape changes and producer→consumer chains;
  `--plan-step <plan>:<step>` adds a plan-conformance lens.
- `review-proof` is the cross-cutting discipline both lean on: findings must cite `file:line` or
  be dropped. Invoke it directly for "are you sure?" moments — audits, debugging, architecture
  claims.

</details>

<details>
<summary><strong>6. Acceptance testing (UAT)</strong></summary>

After a build, human-facing verification splits by whether a test script exists.

**A script exists** (a plan M-step, a commands+expectations table):

```
/review-uat plan.md#step-M          # refine: explicit prereqs, observable pass criteria, agent/human split
/user-uat plan.md#step-M            # execute: agent runs the mechanical tier, auto-judges with evidence
```

**No script — explore the built thing directly:**

```
/user-walkthrough <feature>         # attended: you drive, agent answers from source, fixes small things live
/user-shakedown <feature>           # autonomous: closes every open ledger item (verify / quick-fix / log)
```

- Walkthrough and shakedown share one ledger, so you can explore attended and then hand the
  remainder to shakedown, armed under a mechanically checkable goal:
  `/goal "shakedown ledger for <slug> has zero open items"`.
- Anything needing human judgment is escalated with evidence, never guessed.
- Finish with `/repo-update` to commit the fixes and file the logged issues.

</details>

<details>
<summary><strong>7. Unattended overnight runs</strong></summary>

```
/build-queue --queue <path>         # one line per phase plan
```

- For each queue item it runs `plan-expedite` then `build-phase`, each phase in its own worktree,
  strictly sequential.
- Any halt is **parked** — a GitHub issue with halt context — and the queue moves on; nothing
  retries at 3am. A kill-switch file (`.build-queue-killswitch`) is the only mid-run control.
- You get a morning summary; run `/repo-update` per shipped phase over coffee.

</details>

<details>
<summary><strong>8. Session &amp; context management</strong></summary>

```
/user-recap                         # ~150-word thread refresh: problem / tried / still to do
/user-orient                        # full re-orientation: verified vs not, asides, recommendation (read-only)
/user-draft <rough thoughts>        # polish a rough idea into a reusable prompt or a /goal condition
/task-handoff --loop                # durable checkpoint mid-task (~5s)
/task-handoff --next-task <label>   # save + push at a task boundary, keep working
/task-handoff                       # bare = --resume: orientation block from the last checkpoint
/session-wrap                       # true session end: memory + docs + clean tree + next-window prompt
/context-slim [--apply]             # audit auto-loaded context files; prune per-turn token cost
```

- The doctrine is *native context management first*: auto-compaction and goal-arming handle most
  sessions, so the default is to keep working in one window. `task-handoff` covers in-window
  transitions; `session-wrap` is only for real endings (`--end` delegates to it).
- `user-draft` is the authoring helper — it turns rough thoughts into a clean prompt or a
  checkable `/goal` string and checkpoints via `task-handoff --loop` so a window pivot loses nothing.

</details>

<details>
<summary><strong>9. Plan &amp; portfolio maintenance</strong></summary>

```
/user-pm [--cut|--goal|--overnight|...]   # read-only PM snapshot: shipped / outstanding / next / cuttable
/plan-trim                                # the write path: propose 3-8 cuts, execute on confirm
/plan-merge <plan-1> <plan-2>             # reconcile overlapping plans into one spine
/research-prospect                        # survey all active projects → menu of /deep-research topics to farm out
```

- `user-pm` prescribes, never executes — its Build/Overnight moves print the ready
  `/plan-*` or `/build-phase` command with prerequisites. `plan-trim` is its writing companion.
- `research-prospect` is the cross-project sibling of `user-pm`: read-only, it surveys every active
  project and emits a prioritized menu of research topics to farm out to other windows.
- After a merge, re-run `/plan-review` + `/plan-wrap` on the merged plan and `/repo-sync` to
  re-cut issues. Originals are archived, never deleted.

</details>

<details>
<summary><strong>10. Improving the skills (and the workspace's memory)</strong></summary>

Two independent tracks operate on the skills themselves and on the workspace's feedback memory.

```mermaid
flowchart TD
    subgraph IMPROVE["IMPROVE A SKILL"]
        direction LR
        A["user-brainstorm<br>(candidate strategies)"] --> B["skill-eval-setup<br>(bootstrap evals)"] --> C["skill-evolve<br>(parallel A/B variants)"] --> D["skill-iterate<br>(serial hill-climb)"]
    end
    subgraph CODIFY["CODIFY A LESSON"]
        direction LR
        E["lesson-harvest<br>(draft PR)"] --> F["memory-distill<br>(human gate)"]
    end
    IMPROVE ~~~ CODIFY
```

```
# improve a skill
/user-brainstorm <skill or problem>              # candidate strategies / framings to try
/skill-eval-setup <skill>                        # bootstrap evals.json + scenarios + golden corpus
/skill-evolve --skill <name> --variants <file>   # A/B N variants in parallel; pushes winner, prints gh pr create
/skill-iterate                                   # overnight serial hill-climb (1h or 12 iters per skill)

# codify a lesson
/lesson-harvest --dry-run                        # scan git history + run logs for un-codified regressions → draft PR
/memory-distill                                  # human gate: distill drafts into durable principles (the only memory writer)
```

- The improve track is explore-then-exploit: brainstorm framings, A/B them with `skill-evolve`, then
  hill-climb the winner with `skill-iterate`. (In steady state the two loop — `skill-iterate` runs
  nightly and hands plateaued skills back to `skill-evolve`; see each `SKILL.md`.)
- `skill-evolve` and `skill-iterate` both require the evals folder `skill-eval-setup` creates.
- Nothing self-approves: `skill-evolve` prints the PR command instead of opening it, `lesson-harvest`
  only drafts, and `memory-distill` keeps a human at the write gate.

</details>

<details>
<summary><strong>11. Ideation &amp; learning</strong></summary>

```
/user-brainstorm <topic>            # 10 seed topics + gap-fill rounds → tiered doc set under docs/investigations/
/user-learn <topic>                 # hands-on learning ramp: runnable notebooks, exercises, tracker
```

These are deliberately conversational — they keep you in the loop instead of running the pipeline.

</details>

---

*The through-line: treat agent work as a pipeline with quality gates. Plans are reviewed before
they become issues, every build step is gated by independent reviewers, acceptance is evidence-based,
and even the skills that improve the skills keep a human at the merge gate.*

## Install

<details>
<summary><strong>How to point Claude Code at these skills</strong></summary>

Each top-level folder is one skill. Point Claude Code at them by copying the folders into your skills
directory, or by linking this repo in:

```bash
# copy individual skills
cp -r plan-review ~/.claude/skills/

# or link the whole collection (macOS/Linux)
ln -s "$(pwd)" ~/.claude/skills-shared
```

On Windows, use a directory junction:

```
mklink /J "%USERPROFILE%\.claude\skills-shared" "%CD%"
```

Then invoke a skill in Claude Code, e.g. `/plan-review` or `/build-step`.

</details>

## Adapt before use

- Replace placeholders (`<workspace>`, `<project>`, `<your-org>`) with your own values.
- Skills that reference a "control plane" or a memory index assume conventions from my workspace —
  read the `SKILL.md` and adjust, or skip those skills.
- No secrets or credentials are included.

## License

MIT — see [LICENSE](LICENSE). Built by Abraham Robison ([github.com/aberson](https://github.com/aberson)).
