---
name: skill-evolve
description: A/B-test N variant mutations of a skill in parallel. Takes --skill <name> and either --variants <file> (one strategy per line) or no variants (brainstorm mode — LLM proposes a candidate list and exits for operator curation, no worktrees created). When variants are supplied, creates N worktrees, dispatches N parallel agents that each apply their strategy and run the existing produce-grade loop, then produces a comparison table. The winner's branch is pushed and a `gh pr create` command is printed for operator review (no auto-PR). Loser-analysis is written under docs/investigations/skill-evolve/ for the next generation. Invoke as "/skill-evolve --skill <name> [--variants <path-or-inline>]".
user-invocable: true
---

# Skill Evolve

`/skill-evolve` runs N parallel A/B variants of a skill's SKILL.md against the skill's existing eval suite and reports which variant won. Built on top of the produce-grade loop documented in [`skill-eval-setup`](../skill-eval-setup/SKILL.md). The skill's whole reason to exist is to compress what would be N sequential `/skill-eval-setup` self-improvement runs into one parallel fanout.

---

## Execution model — autonomous, parallel-fanout, no auto-PR (HEAVY)

This skill exists so the operator can test 3-5 candidate prompt mutations in one shot instead of running them sequentially over days. The whole point is parallel evaluation with honest reporting. Therefore:

1. **Parallel by default, via the scoring workflow.** Variants are evaluated by the shared workflow at [`../_shared/score_skill.workflow.js`](../_shared/score_skill.workflow.js), which fans out all variants — and within each variant, all scenarios — concurrently. Sequential variant runs defeat the whole purpose. If the Workflow tool is unavailable in this environment, halt with a clear error rather than silently falling back to a single self-grading agent (the defect this skill was rebuilt to avoid — see #6).

2. **No auto-PR.** Per workspace convention (never push without explicit ask, direct-to-master is the norm), this skill DOES NOT run `gh pr create`. It pushes the winner's branch to remote and PRINTS the `gh pr create` command for the operator to run after reviewing the diff locally. Auto-opening PRs from an LLM judgment call would short-circuit the human review the workspace expects.

3. **Single trial is honest about being single trial.** Default `--trials 1`. The comparison table includes a "single-trial; treat deltas <5pp as noise" caveat in the header. If the operator wants tight CIs, they pass `--trials 3` or higher; each trial multiplies cost linearly. Do NOT silently inflate confidence claims when only one trial ran.

4. **No mid-run confirmations.** No `(y/n)` gates. No "ready to dispatch variants?". The operator opted into the parallel run by invoking `/skill-evolve`. Halts are reserved for: pre-flight failures, agent crashes that prevent producing a score, or genuine ambiguity in the variant strategy that needs operator judgment (which should be rare — variant strategies are operator-authored, not LLM-generated).

5. **Loser-analysis is the next-generation seed.** Every variant — winners AND losers — produces a captured analysis with: full SKILL.md diff, score breakdown per assertion, the agent's own analysis of why the strategy did or did not move the score. The loser analyses are filed under `docs/investigations/skill-evolve/<skill>/<timestamp>/` so the next round can read them and propose better strategies.

6. **Produce and grade are different agents — always.** No agent grades output it produced. The workflow spawns a RENDER agent and a SEPARATE GRADER agent per scenario; the mutator agent only mutates. This is non-negotiable: a grader biased by having authored the artifact is exactly the failure the 2026-05-27 consolidated render+grade incident surfaced (see [`../_shared/score-skill.md`](../_shared/score-skill.md) § Absolute grading). Agent nesting is depth-1, so this split MUST live in the workflow (or an orchestrator that is itself the main loop) — never inside a spawned variant agent, which cannot fan out further and would be forced to self-grade.

This is by strong operator preference; treat any deviation as a defect.

---

## When to use

- 3+ candidate mutations are on the table for one skill and the operator wants to know which (if any) actually move the score.
- A skill's current score has a clear ceiling (e.g., stuck at 76% over multiple iterations) and the operator wants to try fundamentally different approaches in parallel rather than tweak one variable at a time.
- Pre-existing `evals/evals.json` + `evals/test_scenarios.json` exist for the target skill (per [`skill-eval-setup`](../skill-eval-setup/SKILL.md)).

## When NOT to use

- The skill has no `evals/` folder yet — run `/skill-eval-setup <skill>` first.
- The mutation is mechanical (rename a section, fix a typo, add a missing field) — just edit the SKILL.md directly.
- The operator wants to evolve eval assertions or scenarios themselves, not the SKILL.md — that's a different workflow (the `evals.json` is the ground truth A/B variants are scored against; mutating it invalidates the comparison).
- The skill is already at 100% on its current eval suite — there's nothing to evolve toward without first sharpening the assertions.

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--skill` | yes | -- | Skill name (resolved to `.claude/skills/<name>/SKILL.md`) or absolute path to a SKILL.md |
| `--variants` | no | brainstorm | Either an absolute path to a variants file (one strategy per line, format below) OR an inline semicolon-separated string of strategies. If omitted, the skill enters **brainstorm mode** (see § Variant sourcing — brainstorm mode): LLM proposes a candidate list, writes it to a file, and exits before any worktrees are created. |
| `--trials` | no | 1 | Number of independent agent trials per variant (more = tighter CI, linear cost increase) |
| `--baseline-from-results` | no | -- | Skip the baseline agent; read the latest score from `evals/results.tsv` instead. Faster but uses a potentially stale baseline. |
| `--dry-run` | no | -- | Print the resolved variant list + worktree plan + cost estimate, then exit. No worktrees created, no agents dispatched. |

---

## Variants file format

Plain text. One variant per non-blank, non-comment line. Each line must start with a bracketed short ID, then the strategy prose. The ID is used for the variant's mutated-copy filename, the winner's branch name, and the comparison-table row.

```text
# Each line: [<short-id>] <strategy prose>
# Short IDs must match [a-z0-9-]{1,30}. They become git refs.

[aggressive-parallel] Wherever the SKILL.md tells the executor to call tools sequentially, identify opportunities to batch independent calls in a single message. Add explicit "dispatch in parallel" guidance to any step with 2+ independent reads.
[scratchpad] Add an explicit chain-of-thought scratchpad section the executor uses to plan before producing the final output. Prose-only, no JSON.
[compress-30] Compress the SKILL.md by ~30% by removing redundant prose, collapsing examples to single lines, and tightening lists. Preserve every assertion-load-bearing instruction; remove only verbiage.
[example-rich] Add 1-2 concrete worked examples per major step. Examples should be small enough to read in 3-5 lines but specific enough that an executor can pattern-match.
```

Parse rules:

- Lines starting with `#` are comments; ignored.
- Blank lines ignored.
- Each line MUST start with `[<id>]` then whitespace then strategy prose. Lines not matching this shape are pre-flight errors.
- IDs must be unique within the file. Duplicates are pre-flight errors.
- Inline form (`--variants "[id1] strategy 1;[id2] strategy 2"`) splits on `;` and applies the same per-line rules.

Practical N: 2-5 variants per run is the sweet spot. 6+ burns parallel-agent budget and bloats the comparison table; 1 variant defeats the A/B purpose (just run `skill-eval-setup`'s loop directly).

---

## Variant sourcing — brainstorm mode

If `--variants` is omitted, the orchestrator enters **brainstorm mode**: it proposes 10–15 candidate strategies, writes them to a file, prints them inline, and exits before any worktrees are created. The operator then curates the file and re-invokes with `--variants <path>`.

This is a deliberate pre-dispatch exit, NOT a mid-run halt or a `(y/n)` gate. The operator opted into the brainstorm flow by omitting `--variants`; the autonomous-no-confirmations contract (§ Execution model #4) still holds for variant-supplied runs. Auto-running LLM-generated variants without operator curation would drift toward "Claude-pleasing" patterns rather than testing real hypotheses (see Limitations).

### Brainstorm procedure

1. **Resolve and verify target skill** (same as Step 0 pre-flight #1). If missing, halt with the standard pre-flight error — brainstorm mode does not paper over a missing skill.

2. **Read the target SKILL.md.** Full read.

3. **Read prior loser analyses** under `docs/investigations/skill-evolve/<skill>/*/` (if the directory exists). Goal: do not re-propose strategies that already lost. If the directory exists, list the variant IDs and one-line strategy from each prior run's `00-comparison.md`; treat them as exclusions.

3a. **Read operator-seeded proposals** at `docs/investigations/skill-evolve/<skill>/_proposed.md` (if the file exists). Each non-comment line in variants-file format (`[<id>] <strategy>`) is a SEED — include it verbatim in the candidate list with priority placement (top of the list). Seeds are operator-curated hypotheses captured between runs; do not discard them in favor of LLM-generated alternatives. Skip any seed whose `<id>` collides with a prior-run loser ID (the exclusion list from step 3 wins on conflict — re-proposing a known loser requires the operator to either rename or explicitly remove the loser analysis first). The `_proposed.md` file is NOT a timestamped run dir (the leading underscore distinguishes it); leave it in place after the brainstorm — the operator manages its lifecycle (delete entries once tried).

4. **Read recent `evals/results.tsv`** (last 5 rows, if present) to see which assertions have been stuck at FALSE across iterations. Strategies that plausibly move those specific assertions get priority placement in the list.

5. **Generate 10–15 axis-spanning candidate strategies.** Each candidate is `[<short-id>] <one-sentence strategy>` followed (on the next line, after a `# ` comment marker so it's ignored on re-invocation) by a one-sentence rationale. Span axes, not minor wording tweaks:
   - Structural changes (compress / expand / reorder / split into sub-skills)
   - Process changes (parallel-dispatch / serial / scratchpad / two-stage produce-then-grade)
   - Output-format changes (single-artifact / multi-file / inline-only / file-only)
   - Content-source changes (verbatim-quote / paraphrase / cite-line / cite-section)
   - Scenario emphasis (adversarial / happy-path / grounded-in-real-fixtures)
   - Extraction order (anti-pattern-first / positive-rule-first)
   - Termination / scoring (strict TRUE/FALSE / confidence-weighted / tiered must-vs-should)

   IDs must match `[a-z0-9-]{1,30}` and be unique. Do not include strategies from the loser-analysis exclusion list.

6. **Write `docs/investigations/skill-evolve/<skill>/<timestamp>/proposed-variants.txt`** containing all candidates, uncommented (ready to consume as-is). Use absolute path. Path format: `<dev-root>/docs/investigations/skill-evolve/<skill>/<YYYYMMDD-HHMMSS>/proposed-variants.txt`.

7. **Print the list inline** so the operator can see it without opening the file.

8. **Exit with this exact follow-up block** (no other output after it):

   ```text
   Brainstorm mode — no worktrees created, no agents dispatched.

   Proposed variants written to:
     <abs-path-to-proposed-variants.txt>

   To run ALL proposed variants as-is:
     /skill-evolve --skill <skill> --variants <abs-path>

   To run a SUBSET: open the file, delete or `#`-comment lines to drop, then re-invoke with the same path.

   Practical N reminder: 2–5 variants is the sweet spot. Trim before re-invoking.
   ```

Brainstorm mode never creates worktrees, never dispatches agents, never pushes branches. The only side effect is one file under `docs/investigations/skill-evolve/`.

---

## Steps

### Step 0: Pre-flight

Before creating any worktrees or dispatching any agents, all of:

1. **Resolve and verify target skill.** `<skill>` → `<dev-root>/.claude/skills/<skill>/SKILL.md`. Confirm SKILL.md, `evals/evals.json`, and `evals/test_scenarios.json` all exist. Missing any → halt with the missing-path list.

2. **Resolve variants source.**
   - If `--variants` was provided: parse per the rules in § Variants file format. Collect ALL malformed lines / duplicate IDs and report at once; do not halt after the first.
   - If `--variants` was omitted: switch to **brainstorm mode** (see § Variant sourcing — brainstorm mode). Generate candidates, write the file, print the list, and exit. Skip the remaining pre-flight steps (working-tree-clean check is not required for a no-side-effect brainstorm exit) and skip Steps 1–6 entirely.

3. **Working tree clean check.** `git status --porcelain` in the main repo. If non-empty, halt: "Working tree dirty — stash or commit before running /skill-evolve." This is a real constraint: variants are mutations OF the live `SKILL.md` and the winner's branch is cut from HEAD, so uncommitted edits would confound the baseline and could land unintended changes on the winner branch.

4. **Disk space check (advisory, not gating).** The single winner worktree (Step 4) pulls roughly `du -sh .` of the main tree; losers use temp files under `work_dir`, not worktrees. Print the estimate; do not halt — the operator owns the disk decision.

5. **Cost estimate (advisory).** `N variants × K trials × M scenarios = X agent runs.` Print before proceeding. Per the autonomous-by-default contract, do not ask for confirmation; the operator opted in.

6. **Dry-run exit.** If `--dry-run`, print the resolved variant list + work-dir plan + cost estimate + exit. No side effects.

### Step 1: Prepare the scoring run

All mutate + produce + grade work is delegated to the shared scoring workflow at
[`../_shared/score_skill.workflow.js`](../_shared/score_skill.workflow.js). That workflow is the orchestration
level: per variant it spawns a MUTATOR agent (applies the strategy to a fresh SKILL.md copy), then a RENDER
agent and a SEPARATE GRADER agent per scenario. The grader only reads a file the render agent wrote — it never
grades output it produced.

This is the fix for the original defect: a single variant sub-agent used to both simulate the skill output AND
grade itself. A sub-agent cannot spawn its own producer/grader sub-agents (agent nesting is depth-1), so it was
forced to self-grade. Moving the fan-out into a workflow flattens it — every agent is a sibling of the script.
See § Execution model.

**Optional local-grader offload (switchboard, INERT BY DEFAULT).** The per-scenario GRADER fan-out is the one role this skill may route to a local model (offload-scan task_class `skill-evolve-grader`; Switchboard Decision 9 — a cheap parallel scoring array). It is **off unless switchboard offload is enabled for this slice**. When a grader sub-task is about to score a rendered output, first call the switchboard judge entrypoint with the grading prompt:

```bash
python -m switchboard judge --site skill-evolve-grader --prompt-file <grading-prompt-file>
```

It prints one JSON object and always exits 0. On a **verdict** (`{"verdict": ...}`), use it as the grader's advisory score. On a **defer** (`{"defer": true, ...}`) — which is ALWAYS returned when offload is off, the slice is disabled, or the model is down/slow/wrong-shaped — fall back to the normal Claude grader path. When offload is OFF (the default), this returns a defer immediately with no network call, so the workflow grades on Claude **exactly as before**. The local model only advises a per-scenario score; the winner/keep gate stays on Claude.

Create a temp work dir for this run, then assemble the workflow `args`:

- `shared_dir` — absolute path to `.claude/skills/_shared`.
- `work_dir` — a fresh temp dir, e.g. `C:/Users/<user>/AppData/Local/Temp/skill-evolve-<skill>-<epoch>`. Create it first; agents write mutated copies, renders, verdicts, and payloads here. (Use `AppData/Local/Temp`, not `/tmp` — see `.claude/rules/windows-shell.md`.)
- `evals_dir` — `<skill-folder>/evals` (the UNMUTATED eval suite; every variant is scored against the same assertions, held constant per § Limitations).
- `trials` — the `--trials` value (default 1). On `--trials N`, each scenario is graded N times and the aggregator collapses by per-(scenario, assertion) majority vote (ties → False).
- `variants` — one object per parsed `[<id>] <strategy>` line: `{ id, label: id, strategy, base_skill_md_path: <abs path to the skill's real SKILL.md> }`.
- Unless `--baseline-from-results` was passed, append a baseline entry to `variants`: `{ id: "BASELINE", label: "BASELINE", strategy: "BASELINE — reproduce the SKILL.md verbatim with no change", base_skill_md_path: <same abs path> }`. Scoring the baseline through the identical produce/grade path is what makes it a valid reference point.

### Step 2: Run the workflow

Invoke the Workflow tool once (it fans out all variants — and within each variant, all scenarios — concurrently):

```
Workflow({
  scriptPath: "<dev-root>/.claude/skills/_shared/score_skill.workflow.js",
  args: <the args assembled in Step 1>
})
```

It returns one result object per variant (and BASELINE):
`{ id, label, skill_md_path, score, passed, total, status, failed_assertions, passing_pairs }`.
`score` is the composite in `[0.0, 1.0]`; `skill_md_path` points at the mutated copy under `work_dir` (Step 4 reads
the winner's copy from there). No per-variant worktrees are created — the only git side effect is Step 4's single
winner branch.

If `--baseline-from-results`: omit the BASELINE entry; instead open `evals/results.tsv`, take the last
KEEP / KEPT / PASS / BASELINE row's `score_pct` as the baseline, and flag the staleness in the report header.

### Step 3: Collect results and produce comparison

The workflow's return array IS the result set — no per-agent JSON to parse. A variant whose scoring errored comes
back with `status: "harness-error"` and `score: null` (mark it `FAILED`); the others are still valid data. Compute
each variant's delta against the baseline in percentage points: `(score - baseline_score) * 100`.

**Echo each variant's result object verbatim to stdout, under a `## Variant results` heading, BEFORE the
comparison table**, so the per-variant contract is auditable. The key set on every object is exactly:
`id`, `label`, `skill_md_path`, `score`, `passed`, `total`, `status`, `failed_assertions`, `passing_pairs`.

Produce a comparison table. Markdown. Example:

```markdown
# /skill-evolve report — <skill> — <timestamp>

Baseline: <baseline_score> (<source: workflow BASELINE | results.tsv stale from <commit>>)
Trials per variant: <K>
Caveat: <if K==1: "Single-trial run; treat deltas <5pp as noise.">

| Variant | Score | Δ vs baseline | Status | Verdict |
|---|---|---|---|---|
| BASELINE | 0.760 | — | ok | reference |
| [aggressive-parallel] | 0.790 | +3.0pp | ok | NOISE (single-trial, Δ<5pp) |
| [scratchpad] | 0.850 | +9.0pp | ok | WINNER |
| [compress-30] | 0.710 | -5.0pp | ok | REGRESSION |
| [example-rich] | — | — | harness-error | FAILED |

## Winner: [scratchpad]
- Mutated copy: <work_dir>/variant_scratchpad.SKILL.md
- Δ: +9.0pp
- Top remaining failures: <first 1-2 `failed_assertions` statements, if any>
```

Verdict rules (thresholds unchanged from prior versions; `score` is in `[0,1]`, deltas in pp):
- `WINNER`: highest `score` AND Δ ≥ 5pp vs baseline (a tighter threshold is allowed at K ≥ 3).
- `NOISE`: 0 < Δ < 5pp at K=1.
- `REGRESSION`: Δ < 0.
- `NO WINNER`: no variant cleared the 5pp threshold. The report still ships; the operator decides whether to iterate.
- `FAILED`: `status != "ok"`.

Ties on `score`: prefer the variant whose mutated copy is the smaller diff vs baseline (Occam's). Document the tiebreak inline.

### Step 4: Winner handling

If there is a `WINNER`:

1. **Materialize the winner on a branch.** Create ONE worktree, for the winner only:
   `git -C <main-repo> worktree add <dev-root>/../worktree_skill-evolve_<skill>_<winner-id>/ -b skill-evolve/<skill>-<winner-id>` (off current HEAD). Copy the winner's mutated SKILL.md from `<work_dir>/variant_<winner-id>.SKILL.md` over the worktree's `.claude/skills/<skill>/SKILL.md`, then commit:
   `git -C <worktree> add .claude/skills/<skill>/SKILL.md && git -C <worktree> commit -m "skill-evolve <skill> [<winner-id>]: <one-line strategy summary>"`. See [`.claude/rules/worktree-hygiene.md`](../../rules/worktree-hygiene.md).

2. **Push the winner's branch.** `git -C <main-repo> push -u origin skill-evolve/<skill>-<winner-id>` (unless `SKILL_EVOLVE_NO_PUSH=1` — then print the local branch name and a `git push` command instead). Branch pushes are routine; PR opens are operator decisions.

3. **Print the gh pr create command** for the operator to paste:
   ```bash
   gh -R <repo-from-gh-remote> pr create \
     --base master \
     --head skill-evolve/<skill>-<winner-id> \
     --title "skill-evolve(<skill>): [<winner-id>] +<delta>pp" \
     --body-file <abs-path-to-loser-analysis-dir>/00-comparison.md
   ```
   Use `--body-file` (workspace rule — never inline body for non-trivial PRs).

4. **Leave the winner's worktree in place** for inspection. The path is in the report.

If `NO WINNER`: skip the worktree, the push, and the PR command. Print "No variant cleared the threshold; iterate with new strategies." 

### Step 5: Loser handling

For every NON-winner (REGRESSION, NOISE, NO-WINNER, FAILED):

1. **Capture analysis.** Write `docs/investigations/skill-evolve/<skill>/<timestamp>/<variant-id>.md` with:
   - Strategy verbatim.
   - `score`, Δ vs baseline, `status`.
   - The SKILL.md diff: `git -C <main-repo> diff --no-index -- .claude/skills/<skill>/SKILL.md <work_dir>/variant_<variant-id>.SKILL.md` (the mutated copy vs the live baseline). `--no-index` exits 1 when the files differ — that is expected, not an error.
   - The variant's top `failed_assertions` (statement + grader_reason) — the next round's targeting signal.
   - Orchestrator's classification (NOISE / REGRESSION / NO-WINNER / FAILED).

2. **Write the comparison summary.** `docs/investigations/skill-evolve/<skill>/<timestamp>/00-comparison.md` is the same markdown table as the stdout report. This is the file `--body-file` references for the PR.

No per-variant worktrees exist to clean up — losers leave only their mutated copy under `work_dir` (a temp dir) plus their analysis file. Optionally delete `work_dir` once every analysis is written; it holds no git state, so there is no unmerged-work risk (contrast the old per-variant-worktree cleanup, which `.claude/rules/worktree-hygiene.md` §2-§4 flag as a recurring Windows file-lock hazard).

### Step 6: Final stdout output

Emit, in order:
- The comparison table (Step 3).
- The winner's gh pr create command (if WINNER) or the "iterate" message (if NO WINNER).
- The path to the investigations directory: `Analyses written to docs/investigations/skill-evolve/<skill>/<timestamp>/`
- The winner's worktree path (if any), and the `work_dir` temp path (safe to delete once analyses are written).

---

## Halts

The 4 conditions under which this skill halts mid-run. Anything else is a defect.

1. **Pre-flight failure.** Skill / evals missing, variants file malformed, working tree dirty. Halt before creating any worktrees.
2. **Workflow unavailable.** The Workflow tool cannot run in this environment. Halt rather than fall back to a single self-grading agent (defeats the skill's purpose and reintroduces the original defect).
3. **All variants failed.** Every variant came back `status != "ok"` (score null). Halt with the workflow output — there's nothing to report.
4. **Operator killswitch.** If `.skill-evolve-killswitch` exists in the main repo root, halt at the next safe point (after a result returns) and write a partial report. (Less critical than `/build-queue`'s killswitch because runs are typically 10-30 min, not 8 hours, but still useful.)

Note specifically: a single variant crashing is NOT a halt. The other variants are still data.

---

## Relationship to other skills

| Skill | Role |
|---|---|
| `/skill-eval-setup` | Sets up the `evals/` folder this skill A/B-tests against. Must be run on the target skill before `/skill-evolve` can operate. |
| `/build-queue` | Different shape — drains a queue of distinct plans. `/skill-evolve` runs N parallel variants of ONE skill. |
| `/user-draft` | Single-skill iterative refinement, no A/B. Use when you have ONE candidate change to a skill and want to refine it; use `/skill-evolve` when you have N candidates and want to know which wins. |
| `/loop` | Different shape — sequential repeats of one prompt on an interval. |

## Limitations

- **LLM grading is noisy.** Single-trial deltas under 5pp are statistical noise, not signal. The verdict logic enforces this; reports surface it visibly. If you need tight CIs, pass `--trials 5+` and accept the cost.
- **Strategies are operator-authored OR operator-curated, never LLM-auto-executed.** When `--variants` is supplied, the operator authored them. When `--variants` is omitted (brainstorm mode), the LLM proposes a list but exits before dispatching — the operator curates the file and re-invokes. Auto-running LLM-generated variants would drift toward "Claude-pleasing" patterns rather than testing real hypotheses; the operator-decision step (authorship or curation) preserves the contract. If a run produces NO WINNER, the next move is operator-side: read the loser analyses, propose or brainstorm new strategies.
- **The `evals.json` is held constant.** Mutating both the SKILL.md and the eval suite in the same run would invalidate the A/B. If the eval suite itself is suspect (e.g., assertions are stuck at borderline-judgment), fix the evals first via `/skill-eval-setup` or manual edit, then re-run `/skill-evolve`.
- **No cross-skill parallelism.** This skill A/B-tests variants of ONE target skill. Running multiple `/skill-evolve` invocations on different skills concurrently has undefined behavior (worktree-name collisions if two runs target the same skill, disk pressure across the board). If you want concurrent skill evolution, run them in separate Claude sessions, separate target skills, separate timestamps.
- **Branch-push side effect.** Step 4 pushes the winner's branch. The PR is NOT opened — only the command is printed. If the workspace's "no push without explicit ask" rule should also apply to skill-evolve/* branches, set `SKILL_EVOLVE_NO_PUSH=1` in env to suppress (orchestrator checks this; if set, prints the local branch name and a `git push` command for the operator).
- **Worktree pollution is largely eliminated by the workflow rewire.** Variants are scored from temp-file copies, not per-variant worktrees, so the only worktree created is the winner's (Step 4) — left in place deliberately for inspection. The recurring Windows file-lock cleanup hazard (worktree-hygiene §2-§4) no longer applies to losers; `work_dir` is a plain temp dir.
- **The mutation step is an LLM judgment call.** "Compress by 30%" is interpreted by the agent; another agent might produce a different mutation from the same strategy. Single-shot mutation comparison; if reproducibility matters, log the mutated SKILL.md content in the analysis (which Step 5 already does via the diff).
