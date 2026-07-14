---
name: skill-iterate
description: Serial-iterate every scorable skill autonomously overnight via hill-climb. Default invocation drains all .claude/skills/*/evals-bearing skills (minus an embedded skip-list); per-skill budget capped by 1h wall-clock OR 12 iterations, whichever first. Carries autoresearch's NEVER-STOP-mid-loop discipline. Complementary to /skill-evolve (parallel A/B exploration); /skill-iterate is serial exploitation.
user-invocable: true
---

# /skill-iterate

This skill ports the serial hill-climb pattern from [`<workspace>/primatives/autoresearch/program.md`](../../../primatives/autoresearch/program.md) to skill iteration. Three load-bearing rules carry over verbatim:

- **NEVER STOP mid-loop**: no mid-run halts inside a per-skill iteration loop — the loop drains to its budget cap or crashes; nothing else.
- **Simplicity bias on ties**: a mutation that deletes code with a ≥0 score delta is a keep.
- **Wall-clock-bounded experiments**: every per-iteration scoring call has a hard timeout; every per-skill loop has a hard wall-clock cap.

Treat any deviation as a defect.

---

## When to use

- The operator has 1+ scorable skills (i.e. `evals/evals.json` + `evals/test_scenarios.json` exist) and wants overnight hill-climb iteration.
- Default invocation drains all scorable skills serially, one worktree per skill, budget-capped.
- Use after `/skill-eval-setup` has bootstrapped evals for the target.

## When NOT to use

- No evals present for the target skill — run `/skill-eval-setup <skill>` first.
- Skill is in the embedded skip-list below (output is side-effect-driven, not text-gradable).
- Skill is at a hill-climb plateau and needs radical exploration — use `/skill-evolve` (parallel A/B with operator-curated variants) instead.
- Single-skill interactive iteration where the operator wants to review each diff — use `/build-step` against a hand-edited SKILL.md instead.

---

## Defaults

| Flag | Default | Notes |
|---|---|---|
| `--project` | (workspace root) | Project repo whose `.claude/skills/` tree to iterate. Default preserves legacy behavior (the dev/ workspace root). See §Path resolution (`--project` root). |
| `--skill` | (all scorable skills) | Auto-discover `<project>/.claude/skills/*/evals/evals.json`, filter via skip-list. Use `--skill <name>` to scope to one. |
| `--queue` | (none) | Optional file path with one skill name per line; overrides auto-discovery. |
| `--per-skill-budget` | `1h` | Wall-clock cap per skill. |
| `--per-skill-iterations` | `12` | Iteration cap per skill. Whichever cap hits first ends that skill's loop. |
| `--skip-list` | `<embedded>` | Comma-separated skill names to exclude beyond the embedded list. |
| `--calibrate` | off | Run pre-flight adversarial-mutation calibration for each queued skill (see Phase 0 § Adversarial-mutation calibration). Skills whose grader catches `<70%` of injected defects are defect-parked before entering the iteration loop. Off by default to keep overnight runs fast. |
| `--dry-run` | off | Print resolved queue + budget plan + per-skill worktree paths, then exit. No work. |

Max overnight wall-clock: 12 skills x 1h = 12 hours. Queues longer than 12 items spill to a follow-up night.

---

## Path resolution (`--project` root)

Every path this document expresses relative to "the workspace root" (including every bare `.claude/skills/...` reference) is resolved relative to **`--project <path>`**. The default is the workspace root the skill is invoked from (`<workspace>`), so the default behavior is byte-for-byte the legacy behavior. Binding `--project` rebases ALL of the following onto that project's git repo, so the same hill-climb loop can iterate skills living in any repo (the dev/ workspace, `Alpha4Gate`, `void_furnace`, ...). This section is the single source of truth for the rebasing; the per-phase prose below is written workspace-root-relative and is governed by this table.

| Reference | Resolves to |
|---|---|
| Skill discovery glob | `<project>/.claude/skills/*/evals/evals.json` |
| `--skill <name>` / `--queue` skill folder | `<project>/.claude/skills/<name>/` |
| `evals/results.tsv` (cross-night filter + per-iteration append) | `<project>/.claude/skills/<name>/evals/results.tsv` |
| Lock file | `<project>/.skill-iterate.lock` |
| Kill-switch file | `<project>/.skill-iterate-killswitch` |
| `<PROJECT>` (Phase 3 git ops: `git -C <PROJECT>`, worktree create, squash-merge target) | `<project>` |
| Morning-summary dir | `<project>/docs/skill-iterate-runs/` |
| `.gitignore` `worktree_*/` rule | `<project>/.gitignore` |

**Script-home exception (the one thing `--project` does NOT rebase).** The deterministic helper scripts are always invoked from their canonical home in the dev/ workspace, regardless of `--project`, because they are version-controlled in the dev repo, not copied into each target project. Each takes the target skill / project paths as ARGUMENTS, so cross-tree use needs no copying:

- Queue discovery (Phase 1): `.claude/skills/skill-iterate/scripts/resolve_queue.py --project <project>`
- Structural metrics (Phase 2 Step D): `.claude/skills/skill-iterate/scripts/structural_metrics.py <skill_md>`
- Absolute aggregator (Phase 2 Step D): `.claude/skills/_shared/score_skill_absolute.py`
- Grader-prompt builder (Phase 2 Step D): `.claude/skills/_shared/grader_prompt.py::build_grader_prompt`
- Results append (Phase 2 Step G): `.claude/skills/skill-iterate/scripts/append_result.py <skill_path> ...`
- Morning summary (Phase 4): `.claude/skills/skill-iterate/scripts/morning_summary.py`

The worktree parent dir (`~/worktree_skill-iterate-*`) is unchanged by `--project`; only the git repo the worktree is added to changes (it is the `--project` repo, via `git -C <PROJECT> worktree add`).

---

## Embedded skip-list

- **Exclude** side-effect-driven skills whose output is not text-gradable in a fresh-context Claude session.
- **Extend** (not shrink) the embedded list via `--skip-list`; embedded entries always remain excluded.

- `verify` — runs the app and observes behavior (side-effect skill, no text artifact).
- `run` — launches the app.
- `loop` — recurring task runner (orchestration).
- `schedule` — remote agent scheduler (orchestration).
- `update-config` — `settings.json` edits (config side-effects, not text generation).
- `fewer-permission-prompts` — settings audit (transcript-driven, not scenario-driven).
- `claude-oauth-auth` — credential setup.

These skills become eligible only after per-skill side-effect harnesses exist (future work).

---

## Autonomy contract

Per [`.claude/rules/plan-and-issue-flow.md` § "Autonomous-by-default skills"](../../rules/plan-and-issue-flow.md) and [`.claude/rules/code-quality.md` § "Build-phase halt contract"](../../rules/code-quality.md):

This skill MUST default to autonomous execution. No mid-run `(y/n)` prompts. The only legitimate halts are:

1. **Pre-flight failure** — any of:
   - skill folder missing for an explicit `--skill <name>`
   - `evals/evals.json` missing for a discovered or explicit skill
   - kill-switch file (`.skill-iterate-killswitch`) already present at workspace root at launch
   - target skill in skip-list when `--skill <name>` is explicit
   - **concurrent /skill-iterate run detected** — see "Concurrent-run detection" below
2. **Worktree creation failure** — git error.
3. **3 consecutive iteration crashes on the same skill** — defect surface; park to a GitHub issue and move to next skill in queue (does not halt the whole run).
4. **Kill-switch file appears at workspace root mid-run** — graceful stop between skills, not mid-loop.

Carries autoresearch's `program.md` § "NEVER STOP" rule verbatim: once a per-skill loop enters its iteration phase, the loop runs to its budget cap or until clause 3 (3 consecutive crashes) trips. No `(y/n)` confirmations, no "should I continue?" gates, no asking the operator to review a diff mid-loop. The operator opted into autonomous execution by invoking the skill.

### Concurrent-run detection

Two-check pre-flight at launch:

1. **Lock file:** check for `.skill-iterate.lock` at workspace root. Schema: JSON `{"pid": <int>, "started_at": <iso8601>, "host": <hostname>}`. Behavior:
   - Lock missing → take the lock, proceed.
   - Lock exists + PID alive (cross-platform: `Get-Process -Id <pid>` on Windows, `kill -0 <pid>` on POSIX) → **halt** with message naming the running PID and start time.
   - Lock exists + PID dead → stale; emit `warning: stale lock from PID <N> at <date>; taking over`, overwrite with current PID, proceed.
2. **Worktree scan:** `git worktree list` matching the prefix `worktree_skill-iterate-*`. Behavior:
   - No matches → proceed.
   - Matches found + no live lock → emit `warning: orphaned worktrees from prior crash: <list>; consider cleanup per .claude/rules/worktree-hygiene.md #4`. Proceed (do not auto-clean; operator decides).
   - Matches found + live lock → halt (caught by check 1 already).

On clean exit (including kill-switch stop), remove `.skill-iterate.lock`. On unclean exit, the lock is stale and check (1) handles takeover on next run.

### Iteration outcome taxonomy

Three distinct outcomes per iteration, distinguished for the autonomy contract's clause-3 crash count:

| Outcome | Definition | Counts as crash? | results.tsv status |
|---|---|---|---|
| **keep** | Score improved (delta > 0) | No | `keep` |
| **revert** | Score did not improve (delta <= 0) OR target skill output was unparseable OR a test scenario errored. The mutation produced bad output, which is the loop working as intended; `git reset --hard HEAD~1`. | No | `revert` |
| **crash** | Scoring harness threw an unhandled exception, OR score-extraction returned no number, OR per-iteration timeout (10 min hard cap, per Step 3) fired, OR git commit/branch op failed, OR the optional pre-flight adversarial calibration returned `grader-broken-for-skill` (adversarial-mutation calibration catch rate below threshold; grader cannot discriminate defective from baseline). | Yes | `crash` |

Three consecutive `crash` outcomes (no intervening keep/revert) on the same skill triggers autonomy-contract clause 3 — park the skill via a GitHub issue with crash logs, move on to the next in queue.

The `grader-broken-for-skill` sub-class (SIHC Step 13) is the runtime/adversarial-mutation counterpart to the storage-time goldens check. The adversarial-calibration pass (run by Phase 0 only when `--calibrate` is set — off by default) injects N known defects into SKILL.md copies, scores each, and computes the catch rate (fraction whose score dropped strictly below baseline). A catch rate below the configured threshold (default 70%) means the grader cannot reliably discriminate defective from baseline content for this skill; the iteration loop would produce no useful gradient. Phase 0 halts before entering Phase 1 — the skill is defect-parked the same way clause-3 handles 3-consecutive-crash, not retried within the run. See [`scripts/adversarial_calibration.py`](scripts/adversarial_calibration.py) and [`../../../docs/investigations/skill-iterate-hill-climbing/06-adversarial-mutation-grader-discrimination-tests.md`](../../../docs/investigations/skill-iterate-hill-climbing/06-adversarial-mutation-grader-discrimination-tests.md) for the procedure and rationale.

---

## Scoring

Per-iteration scoring follows the shared procedure in [`../_shared/score-skill.md`](../_shared/score-skill.md). Default mode is `composite`: a weighted mean of deterministic structural metrics (40%) and LLM-driven absolute_weighted grading (60%), per SIHC.2 Option A (the prior pair-comparison mode replaced by absolute grading; goldens-verify unwired from the loop body). The procedure also supports `structural`-only and `absolute_weighted`-only modes — see the fragment for inputs, mode semantics, and the brace-safe-substitution requirement for the grader prompt template. Legacy spec-compliance scoring (pre-SIHC) is no longer in scope; all per-iteration scoring now goes through `_shared/score-skill.md` composite/structural/absolute_weighted modes.

A thin Python wrapper at [`../_shared/score_skill_composite.py`](../_shared/score_skill_composite.py) exposes the same procedure programmatically (for tests, smoke checks, and non-LLM callers). Each scoring call returns a single-trial JSON shape:

```
{"score": <float>, "passed": <int>, "total": <int>, "status": "ok" | "unparseable" | "harness-error"}
```

The loop reads `score` to decide keep vs revert. `status != "ok"` is a crash per the taxonomy above.

#### Optional: offload the LLM grader to a local model (switchboard, INERT BY DEFAULT)

The `absolute_weighted` LLM grading slice is a cheap fan-out scoring call — the one role this skill is permitted to route to a local model instead of Claude (offload-scan task_class `skill-iterate-grader`; Switchboard Decision 9). It is **off unless switchboard offload is enabled for this slice**. When you reach the LLM grading sub-call:

1. Check whether offload is enabled for this slice by calling the switchboard judge entrypoint with the grading prompt (run from the switchboard package dir):
   ```bash
   python -m switchboard judge --site skill-iterate-grader --prompt-file <grading-prompt-file>
   ```
   It prints one JSON object to stdout and always exits 0.
2. If the JSON is a **verdict** (`{"verdict": "pass"|"flag", ...}`), use it as the local grader's advisory result and continue.
3. If the JSON is a **defer** (`{"defer": true, ...}`) — which is ALWAYS the case when offload is off, the slice is disabled, or the local model is down/slow/wrong-shaped — fall back to the normal Claude grading path below and proceed exactly as before.

When switchboard offload is OFF (the default), step 1 returns a defer immediately with no network call, so this skill does **exactly** what it did before: run the LLM grader on Claude via `_shared/score-skill.md`. The local model only ever *advises* a score; it is never the keep/revert gate.

---

## Flow

### Phase 0 — Pre-flight

Six checks run before the queue is built. Any failure here halts under §Autonomy contract clause 1; the lock file is NOT taken until all six pass.

#### Concurrent-run detection

Run the lock-file + worktree-scan procedure documented in §Autonomy contract → Concurrent-run detection. The full two-check logic lives there; this phase invokes it as a pre-flight gate. Action on detection:

- **Live lock detected** (lock file exists, PID alive) — halt with the message naming the running PID and start time. Do not write any state; do not touch the lock file.
- **Stale lock detected** (lock file exists, PID dead) — emit the `warning: stale lock from PID <N> at <date>; taking over` warning, then continue pre-flight. The lock file is overwritten in step "Take the lock file" below.
- **Orphan worktrees only** (no lock, but `worktree_skill-iterate-*` dirs match `git worktree list`) — emit `warning: orphaned worktrees from prior crash: <list>; consider cleanup per .claude/rules/worktree-hygiene.md #4` and proceed. Do not auto-clean; the operator decides whether to remove them.

#### Kill-switch absence check

Confirm `.skill-iterate-killswitch` is ABSENT at workspace root at launch. If present, halt with:

```
kill-switch is set at <abs-path>; remove the file to proceed
```

Mid-run kill-switch polling is handled in Phase 3 (between skills); this check is the launch-time gate.

#### Skip-list resolution

The effective skip-list at this phase is the union of:

- The embedded skip-list (per §Embedded skip-list — 7 entries by default).
- Any `--skip-list <comma-separated>` extension passed by the operator. Operators can EXTEND (not shrink) the embedded list.

The merged set is what auto-discovery filters against in Phase 1 and what `--skill <name>` validates against below.

#### Explicit --skill / --queue handling

When `--skill <name>` is passed:

- Verify `.claude/skills/<name>/` exists. If not, halt — pre-flight failure per §Autonomy contract clause 1.
- Verify both `.claude/skills/<name>/evals/evals.json` AND `.claude/skills/<name>/evals/test_scenarios.json` exist. If either is missing, halt with the message `evals not bootstrapped for <name>; run /skill-eval-setup <name> first`.
- If `<name>` appears in the merged skip-list, halt with an explicit `explicit-bypass: <name> is in the skip-list; remove --skill flag or extend skip-list semantics to proceed`. (A future `--force-skip-list-bypass` flag may be added; for now an explicit-skill collision with the skip-list is a halt, not a warning.)

When `--queue <path>` is passed:

- Read the file: one skill name per line. Parsing rules — stated explicitly so operator hand-edits do not 4AM-halt on benign whitespace or inline comments:
  - Strip leading AND trailing whitespace from every line before processing.
  - Blank lines (empty after stripping) are ignored.
  - Lines starting with `#` (after leading-whitespace strip) are whole-line comments and ignored.
  - Inline comments are supported: a `#` anywhere on a non-comment line introduces a trailing comment — split on the FIRST `#` and take the left side, then re-strip trailing whitespace. Example: `session-wrap   # known winner overnight` parses as `session-wrap`.
  - Skill names containing `#` are not permitted (no skill name in `.claude/skills/*/` contains `#`, so this is a non-collision in practice).
- For each parsed skill name, run the same three checks as `--skill` (folder + evals/evals.json + evals/test_scenarios.json + skip-list collision). Halt on the FIRST failure rather than silently skipping — `--queue` is an explicit operator-curated list, and silent skips would mask typos.

#### Take the lock file

After all pre-flight checks above pass, write `.skill-iterate.lock` at workspace root with JSON:

```json
{"pid": <int>, "started_at": <iso8601>, "host": <hostname>}
```

**The write MUST use atomic exclusive-create**, not a check-then-write sequence. The implementation:

- Python: `open(path, 'x')` mode, OR `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)`.
- On `FileExistsError`: another process owns the lock — fall through to the stale-PID branch documented in §Autonomy contract → Concurrent-run detection. Read the existing lock's PID, check `Get-Process -Id <pid>` on Windows or `kill -0 <pid>` on POSIX:
  - PID alive → halt per §Autonomy contract clause 1 (live lock).
  - PID dead → unlink the stale lock, retry the exclusive-create ONCE. If the retry also raises `FileExistsError` (a third process raced in between unlink and retry), halt defensively rather than overwriting blindly.

The atomic exclusive-create is what makes the concurrent-run halt actually exclusive; check-then-write would race. The §Autonomy contract → Concurrent-run detection section above describes the contract (the WHAT — "lock file exists + PID alive → halt"); this subsection specifies the implementation contract (the HOW — atomic exclusive-create, not check-then-write). Do not split the check and the write into two filesystem ops.

Schema and takeover semantics per §Autonomy contract → Concurrent-run detection. The lock is held until clean exit (Phase 3 final cleanup) or kill-switch stop (Phase 3 mid-queue check). Unclean exit (Python exception, signal) leaves the lock stale; the next run takes over per the §Autonomy contract takeover rule.

#### Adversarial-mutation calibration (opt-in via `--calibrate`)

OFF by default. When `--calibrate` is set, after the queue is resolved (Phase 1) but BEFORE the per-skill iterate loop (Phase 2) begins, run [`scripts/adversarial_calibration.py`](scripts/adversarial_calibration.py) for each queued skill:

```python
from adversarial_calibration import calibrate_skill, GRADER_BROKEN_CRASH_CLASS
result = calibrate_skill(skill_dir, score_fn, num_mutations=10, threshold=0.70)
if result["verdict"] == GRADER_BROKEN_CRASH_CLASS:
    # defect-park this skill BEFORE entering Phase 2
    ...
```

The procedure injects 10 known defects into copies of the skill's SKILL.md (mutation kinds: delete required bullet, paraphrase heading, remove code fence, swap MUST with should, delete section, duplicate paragraph, remove leading imperative, remove constraint line, add trailing garbage, shuffle steps), scores each via the same scoring function Phase 2 will use, and computes the catch rate (fraction whose score dropped strictly below baseline). Verdicts:

- `verdict == "ok"` — catch rate `>= 70%` (configurable via the CLI `--threshold` flag). Skill proceeds into Phase 2 normally.
- `verdict == "grader-broken-for-skill"` — catch rate `< 70%`. The grader cannot reliably tell defective from baseline content on this skill; the iteration loop would produce no useful gradient. Defect-park BEFORE Phase 1 enters Phase 2:
  - File a GitHub issue using the same `gh issue create` flow Phase 3 uses for clause-3 defect-park, with title `skill-iterate: <skill> grader-broken-for-skill (calibration catch rate <N>%)`. The issue body MUST include the full `calibrate_skill` result dict (mutation kinds, per-mutation scores, baseline score, threshold) so the operator can see exactly which defect classes the grader is missing.
  - On `gh issue create` failure, write the same body to `docs/skill-iterate-runs/calibration-broken-<skill>-<epoch>.md` (mirroring the Phase 3 local-fallback path documented in [§Per-skill ship gate → Ship decision § defect-park](#per-skill-ship-gate)).
  - Skip this skill; advance to the next in the queue.
  - This does NOT count toward the consecutive-crash defect-park counter — calibration runs once per skill at pre-flight, before any iteration has happened.

Calibration is off by default because (a) it adds N+1 scoring calls per skill at pre-flight which is meaningful overhead for overnight runs, and (b) it has the cross-night-resume problem the iteration loop solves with its 24h freshness filter — re-running calibration nightly produces near-identical verdicts. Recommended cadence: weekly (passed explicitly on Monday-morning runs) OR after any grader-prompt / grader-model change OR after a material SKILL.md rewrite. See [`../../../docs/investigations/skill-iterate-hill-climbing/06-adversarial-mutation-grader-discrimination-tests.md`](../../../docs/investigations/skill-iterate-hill-climbing/06-adversarial-mutation-grader-discrimination-tests.md) § When to apply.

#### Pre-flight failure modes

Restated for the developer agent — these are the five conditions under which Phase 0 halts (calibration defect-park is per-skill, not whole-run, so it is not in this list):

1. Skill folder missing (for an explicit `--skill <name>` or any name in `--queue <path>`).
2. `evals/evals.json` or `evals/test_scenarios.json` missing for an explicit skill.
3. Kill-switch file (`.skill-iterate-killswitch`) present at workspace root at launch.
4. Skill in the merged skip-list when passed explicitly via `--skill <name>` or `--queue <path>`.
5. Concurrent run detected (live lock file with a running PID).

All five map to §Autonomy contract clause 1; none of them count toward the consecutive-crash defect-park counter.

### Phase 1 — Discover queue

Six sub-steps resolve the queue. The output of this phase is an ordered list of skill names to iterate, plus (under `--dry-run`) a printed plan with the worktree paths and budget per skill.

#### Auto-discovery procedure

Glob `<project>/.claude/skills/*/evals/evals.json` (per §Path resolution; `<project>` defaults to the workspace root). The candidate skill list is the set of parent-parent directory names (i.e. for `<project>/.claude/skills/session-wrap/evals/evals.json`, the candidate is `session-wrap`).

The deterministic implementation of this entire Phase 1 resolution (discovery + skip-list filter + 24h freshness filter + alphabetical order, plus the `--dry-run` plan text) is `scripts/resolve_queue.py --project <project>`, invoked from its dev/ home per §Path resolution. The orchestrator SHOULD call it and parse its JSON output (or `--dry-run` text) rather than re-deriving the glob by hand — this keeps the cross-tree `--project` rebasing in one tested place.

For each candidate, verify BOTH `evals/evals.json` AND `evals/test_scenarios.json` exist. Candidates missing `test_scenarios.json` are dropped SILENTLY — half-bootstrapped skills (eval suite started but not finished by `/skill-eval-setup`) are not ready for iteration, and surfacing them as warnings would noise the overnight run with operator-known incomplete work.

Skip auto-discovery entirely when `--skill <name>` or `--queue <path>` was passed. In those cases, the queue is the operator's explicit list (already validated in Phase 0), filtered only by the cross-night-resume filter below.

#### Skip-list filtering

Remove candidates whose name is in the merged skip-list from Phase 0. The `--skip-list` extension applies to BOTH auto-discovery AND `--queue`-driven runs (operators who extend the skip-list want that extension respected even when they hand-curated a queue file; in practice an operator wanting to override the skip-list per-run would edit the `--queue` file directly rather than passing `--skip-list`).

Explicit `--skill <name>` was already validated against the skip-list in Phase 0 and would have halted there — so by Phase 1, an explicit `--skill` is either in-list (halted) or not-in-list (proceeds unfiltered).

#### Cross-night-resume filter (24h freshness)

For each remaining candidate: if `.claude/skills/<name>/evals/results.tsv` exists AND its mtime is within the last 24 hours (UTC), SKIP it silently. This deduplicates back-to-back overnight runs against the same fleet.

Comparison uses `time.time() - st_mtime < 86400` (epoch-seconds, platform-portable; `st_mtime` is UTC epoch on all platforms — no timezone conversion required).

Three caveats apply:

- **Hard 24h cliff.** A skill that ran 23h ago is filtered; a skill that ran 26h ago is eligible. Manual `touch .claude/skills/<name>/evals/results.tsv` resets the window if the operator wants to force re-iteration.
- **No round-robin preservation.** The filter is strictly mtime-based — there is no rotation that prefers skills not run recently.
- **Acceptable for default.** Operators wanting different semantics (run all every night, run only N skills in rotation) use `--queue <file>` to override; the default's role is to drain stale skills serially.

#### Queue ordering

Alphabetical by skill name. This is deterministic and reproducible — the morning summary in Phase 4 can be cross-referenced run-over-run with predictable ordering, and a partial-run kill-switch stop leaves a predictable "what was processed" boundary.

#### --dry-run handling

When `--dry-run` is set, after the queue is resolved, print to stdout:

1. The resolved queue (one skill name per line, in queue order).
2. For each skill in queue: the worktree path that WOULD be created — `~/worktree_skill-iterate-<skill>-<epoch>` (with a placeholder `<epoch>` so the operator sees the path shape).
3. Per-skill budget plan: `<budget>` wall-clock cap (default `1h`), `<iterations>` iteration cap (default `12`).
4. Skills excluded by skip-list (one per line, with reason `skip-list: <embedded|--skip-list extension>`).
5. Skills excluded by the cross-night-resume filter (one per line, with the `results.tsv` mtime).

Literal example output for a 2-skill auto-discovered queue (session-wrap eligible, user-debug fresh-skipped, skill-evolve skip-listed) — used by integration tests as a string-equality target. ASCII hyphens throughout (no em-dashes per `.claude/rules/windows-shell.md` § Shell args):

```
Resolved queue (1 skill):
  session-wrap

Per-skill worktrees:
  session-wrap -> ~/worktree_skill-iterate-session-wrap-<epoch>

Per-skill budget:
  budget=1h iterations=12

Excluded by skip-list:
  skill-evolve  (skip-list: --skip-list extension)

Excluded by cross-night-resume filter:
  user-debug  (results.tsv mtime: 2026-05-23T22:15:04Z)
```

Then EXIT 0 without entering Phase 2 or taking the lock file. `--dry-run` does NOT touch the lock; it is a pure inspect-and-exit mode per [`.claude/rules/plan-and-issue-flow.md` § "Autonomous-by-default skills"](../../rules/plan-and-issue-flow.md) (preview behavior uses an opt-in flag, never an after-the-fact prompt).

#### Empty queue handling

If the resolved queue is empty after all filtering (everything skip-listed or cross-night-skipped), print:

```
Queue empty -- nothing to iterate. All scorable skills were either skip-listed or have results.tsv mtime within the last 24h.
```

Then exit 0. This is a clean exit, not a defect — it means the prior overnight run drained the fleet and this run has nothing to do.

### Phase 2 — Per-skill iterate loop

For each skill in the resolved queue, run the steps below in order. The loop is the heart of this skill; every other phase exists to set it up or wrap it up. The loop NEVER halts mid-iteration for operator input — see §Autonomy contract.

#### Per-skill pre-flight

Before entering the loop, confirm the following for the current skill (the orchestrator-level pre-flight in Phase 0 already ran; this is the per-skill repeat for late-discovered defects):

- Skill folder exists at `.claude/skills/<name>/`.
- Both `evals/evals.json` and `evals/test_scenarios.json` exist.
- Skill name is not in the embedded skip-list (or `--skill <name>` was passed with the explicit-bypass warning per §Defaults).
- Cross-night-resume filter: either `evals/results.tsv` is absent, or its mtime is older than 24h. Skills with a fresher results.tsv are skipped silently (deduplicated overnight runs).
- The orchestrator-level concurrent-run detection from §Autonomy contract already ran in Phase 0; do NOT re-check the lock file or worktree scan here.

Any pre-flight failure here removes this skill from the queue and advances to the next; it does NOT halt the whole run.

#### Worktree setup

- Worktree path: `~/worktree_skill-iterate-<skill>-<epoch>` (note: workspace-root parent dir, NOT inside `dev/`). Same parent-dir convention as `/skill-evolve`'s worktrees, with a distinct `skill-iterate` namespace.
- Branch name: `skill-iterate/<skill>-<epoch>`.
- The `skill-iterate/*` branch namespace is deliberately distinct from autoresearch's `autoresearch/*` namespace to avoid sibling collision in this workspace.
- After creating the worktree, follow `.claude/rules/worktree-hygiene.md` #1: fresh worktrees do NOT inherit dependencies. For a prose-skill workspace there is typically nothing to install, but if a future scoring fragment depends on tooling, this is where it runs.

#### Baseline score capture

The first iteration is the baseline; it makes no edit. Procedure:

1. Run the scoring procedure against the unmodified SKILL.md per [`../_shared/score-skill.md`](../_shared/score-skill.md). For the baseline, pass the unmodified SKILL.md as BOTH `baseline_skill_md` AND `modified_skill_md` so the differential axis returns its self-vs-self neutral (0.5); the structural axis runs normally. The composite score is the baseline against which Phase 2 Step F's keep/revert decision is measured.
2. Append a row to `.claude/skills/<name>/evals/results.tsv` with `status=baseline`, `description=initial baseline`, `wall_seconds=<elapsed>`. The results.tsv schema (columns: `commit\tscore\tstatus\tdescription\twall_seconds`) is finalized in Step 4 of this plan; for now reference the schema as fixed.
3. Record the baseline score in memory for the per-iteration keep/revert decision.

#### Per-iteration loop body

Repeat steps A through H until the budget cap fires (see Step H). Steps A through G are one logical "iteration"; the iteration counter increments on each cycle (baseline does NOT count).

**Step A — brainstorm one hypothesis.** Dispatch ONE sub-agent given (a) the current SKILL.md, and (b) the most recent absolute-grader aggregate from [`../_shared/score-skill.md`](../_shared/score-skill.md) §Absolute grading. The aggregate's `failed_assertions` list (already sorted by `-category_weight, assertion_id` per the aggregator in `score_skill_absolute.aggregate()`) selects which branch of the prompt fires. Design source: [`../../../docs/investigations/skill-iterate-hill-climbing/07-failed-assertion-targeted-brainstorm-prompts.md`](../../../docs/investigations/skill-iterate-hill-climbing/07-failed-assertion-targeted-brainstorm-prompts.md).

**A.1 — Targeted mode** (when `failed_assertions` is non-empty). The sub-agent prompt contains:

- The current SKILL.md (the working copy in the per-skill worktree).
- The top-ranked failure (`failed_assertions[0]`) — passed in full, with every field visible: `assertion_id`, `category_name`, `category_weight`, `statement` (the assertion text the grader applied), `source` (the `file:line` reference into the eval source doc), `defect_type` (e.g. "structural — missing required output part", "format — wrong fence label"), `grader_reason` (the grader sub-agent's reason for marking this assertion false).
- The remaining failures (`failed_assertions[1:]`) in compact form — `assertion_id`, `statement`, `category_weight` only — so the sub-agent knows what else needs fixing without burning context on full records. If only one failure exists, `remaining_failures_compact` is empty; the orchestrator omits the "Other failures" block from the substituted prompt.
- The full `passing_pairs` list — every `(assertion_id, scenario_id)` tuple currently grading TRUE, serialized as the JSON-array shape returned by `score_skill_absolute.aggregate()` (list of `{assertion_id: int, scenario_id: str}` objects, lex-sorted by `(assertion_id, scenario_id)`). This is the "do not break" anchor. If `passing_pairs` is empty (typical only on iteration 1 of a deeply-failing skill), the sub-agent emits the literal substitute string per the template; the "do not break" contract is vacuously satisfied.

The sub-agent is instructed to:

- Propose ONE minimal, named edit to SKILL.md that targets the top-ranked failure.
- Cite at least one passing pair in its rationale — proves it considered side-effects.
- Return the edit as `{description, old_string, new_string}` for Step B to apply.
- NOT propose unrelated mutations or whole-section rewrites.

The literal prompt template the orchestrator hands to the Step A sub-agent (via the Agent tool's `prompt` param) — `{{placeholder}}` syntax marks fields substituted at dispatch time:

```text
You are a strict editor. Propose ONE minimal, named edit to a SKILL.md to make the
top-ranked failing assertion grade TRUE on the next scoring pass — without breaking
any currently-passing (assertion, scenario) pair.

Current SKILL.md:
{{current_skill_md_body}}

Top-ranked failure (anchor your edit on this one):
  assertion_id:     {{top_failure.assertion_id}}
  category:         {{top_failure.category_name}} (weight={{top_failure.category_weight}})
  statement:        {{top_failure.statement}}
  source:           {{top_failure.source}}
  defect_type:      {{top_failure.defect_type}}
  grader_reason:    {{top_failure.grader_reason}}

Other failures (compact — for context only, do NOT target):
{{remaining_failures_compact}}
  (each line: "  id={{id}}  weight={{weight}}  statement: {{statement}}")
  (omit this entire block if remaining_failures is empty)

Passing pairs (the "do not break" anchor — your edit MUST NOT regress any of these):
{{passing_pairs_json}}
  (rendered as a JSON array of {assertion_id, scenario_id} objects, lex-sorted by
  (assertion_id, scenario_id) per score_skill_absolute aggregator output)
  (if empty: emit the literal text "(no passing pairs — first iteration on a deeply-failing skill)")

Return a JSON object with exactly three keys:
  {
    "description": "one-line summary of the edit, in present tense",
    "old_string":  "exact text to be replaced in SKILL.md (must be unique in the file)",
    "new_string":  "replacement text"
  }

In `description`, cite at least one passing pair you considered (by assertion_id) and
explain why your edit does not regress it. If passing_pairs is empty, cite "(none —
deeply-failing baseline)" verbatim instead. Failure to cite is a violation of the
"do not break" contract.

Do NOT propose unrelated mutations, whole-section rewrites (unless radical mode is on),
or edits that touch other files.
```

Anchoring on `failed_assertions[0]` follows operator D2 (2026-05-26): "highest category weight first." The remaining failures are context, not targets.

**A.2 — Simplification mode** (when `failed_assertions` is empty AND the most recent aggregate reports all-pass — see "Multi-trial fallback" below for what "most recent" means). The sub-agent prompt contains:

- The current SKILL.md.
- The full `passing_pairs` list — every assertion currently protected, serialized as the same JSON-array shape as A.1 (`score_skill_absolute.aggregate()` output: list of `{assertion_id: int, scenario_id: str}` objects, lex-sorted by `(assertion_id, scenario_id)`).

The sub-agent is instructed to:

- Propose ONE minimal SIMPLIFICATION — delete a redundant section, fold two near-duplicate rules, remove an example that adds no discrimination, tighten verbose prose.
- NOT propose behavioral mutations — no rule changes, no new sections, no example additions.
- Explicitly note in rationale: "this is a simplification-mode edit; no failing assertion to target."
- Return the edit as `{description, old_string, new_string}`.

The literal prompt template the orchestrator hands to the Step A sub-agent in simplification mode (via the Agent tool's `prompt` param):

```text
You are a strict editor. The SKILL.md below currently passes all grader assertions
(verified via N=3 median saturation per /skill-iterate Phase 2 Step D's saturation
handler). Your job is to SIMPLIFY — delete a redundant section, fold two near-duplicate
rules, remove an example that adds no discrimination, or tighten verbose prose.

DO NOT propose a behavioral mutation: no rule changes, no new sections, no example
additions. There is no failing-assertion signal to optimize against; behavioral
changes would be unguided and likely score-neutral or score-negative.

Current SKILL.md:
{{current_skill_md_body}}

Passing pairs (every assertion currently grades TRUE — do not regress any of these):
{{passing_pairs_json}}
  (rendered as a JSON array of {assertion_id, scenario_id} objects)

Return a JSON object with exactly three keys:
  {
    "description": "one-line summary of the simplification, must include the phrase
                    'this is a simplification-mode edit; no failing assertion to target.'",
    "old_string":  "exact text to be deleted/replaced (must be unique in the file)",
    "new_string":  "replacement text (often shorter; '' for pure deletion)"
  }
```

**Multi-trial fallback.** If `failed_assertions` is empty under the N=1 trial, the simplification branch is NOT yet dispatched — Step D's saturation handler (landed by SIHC.2 Step 5; see `_shared/score-skill.md` §Absolute grading § N=3 median trigger) runs 2 additional trials of the same single-trial pipeline and re-evaluates `failed_assertions` from the per-(scenario, assertion) median. Only after median confirmation does Step A fire with either branch — targeted mode if the median surfaces failures, simplification mode if the median confirms all-pass. The N=3 median wiring lives in Step D's saturation handler (cross-link: §Step D → Saturation handler block below). Brainstorm is gated on median-confirmed signal: noisy single-trial all-pass should not trigger simplification.

**Radical-mode integration.** The 3-consecutive-`revert` trigger from prior Step A is preserved across both branches. After 3 consecutive reverts on the targeted branch, the prompt explicitly invites larger restructures — delete a whole section, rewrite a section, swap orderings — while still anchored on the top-ranked failure. After 3 consecutive reverts on the simplification branch, the prompt invites more aggressive simplification — merge two sections, not just delete a paragraph. The consecutive-revert counter is **shared** between branches; a switch from targeted to simplification (or vice versa) does NOT reset it. A keep on either branch resets the counter to 0 and the next iteration's Step A reverts to the default minimal-edit prompt. The threshold of 3 mirrors autoresearch's anti-stagnation pattern.

**Step B — apply edit.** Apply the proposed edit in-place to `.claude/skills/<name>/SKILL.md` inside the per-skill worktree (via the Edit tool, or by dispatching a sub-agent to do so). The edit MUST be in-place; the sub-agent does NOT refactor unrelated sections, reflow whitespace, or touch other files.

**Step C — git commit.** In the per-skill worktree, `git -C <worktree-path> add .claude/skills/<name>/SKILL.md && git -C <worktree-path> commit -m "<one-line edit description>"`. Capture the resulting commit SHA (7-char short form). Per `.claude/rules/worktree-hygiene.md` #5, prefer `git -C` over `cd`-then-git to avoid silent no-ops in the wrong worktree.

**Step D — run scoring with 10-min hard timeout.** Score the modified SKILL.md via the composite procedure documented at [`../_shared/score-skill.md`](../_shared/score-skill.md) (default mode: `composite`). Per Step 3 of SIHC.2, the composite is the absolute-grader-based mix: structural metrics + `absolute_weighted`, weights `0.4 / 0.6`. The procedure produces the single-trial JSON in the existing `append_result` schema (`{"score": <float>, "passed": <int>, "total": <int>, "status": ...}`). **Hard wall-clock timeout: 10 minutes per iteration**, per `primatives/autoresearch/program.md:108-110`. On timeout, kill the scoring subprocess (or interrupt the scoring sub-agent dispatch), and classify the outcome as `crash` per the §Autonomy contract iteration outcome taxonomy. The timeout enforcement is the caller's responsibility — the shared scoring fragment does NOT enforce it internally.

The single-trial scoring is delegated to the shared scoring workflow at [`../_shared/score_skill.workflow.js`](../_shared/score_skill.workflow.js), which performs the render/grade split for you: a RENDER agent produces each scenario's output, a SEPARATE GRADER agent grades it (no agent grades its own output; the grader prompt is built from `_shared/grader_prompt.py::build_grader_prompt` inside the workflow), then it aggregates via `score_skill_composite.py` + `score_skill_absolute.py`. Invoke the Workflow tool:

```
Workflow({
  scriptPath: ".claude/skills/_shared/score_skill.workflow.js",
  args: {
    shared_dir: ".claude/skills/_shared",
    work_dir:   "<per-skill worktree path>",
    evals_dir:  "<worktree>/.claude/skills/<name>/evals",
    trials:     1,
    versions:   [{ id: "iter<N>", label: "<name>", skill_md_path: "<worktree>/.claude/skills/<name>/SKILL.md" }]
  }
})
```

It returns a one-element array `[{ score, passed, total, status, failed_assertions, passing_pairs }]`. `score` is the composite for Step F's keep/revert decision; `failed_assertions` (already ranked by category weight) is Step A's brainstorm anchor; `passing_pairs` is the "do not break" list. `status != "ok"` is a `crash` per the §Autonomy contract taxonomy. Keeping render and grade as separate agents is non-negotiable — the 2026-05-27 M2 launch showed consolidated render+grade graders misgrade vacuous-true assertions (see [`../_shared/score-skill.md`](../_shared/score-skill.md) §Absolute grading). The numbered per-scenario dispatch contract the workflow implements internally is documented in that fragment's § Orchestrator-LLM as dispatcher.

A failed single-trial dispatch — a grader sub-agent crashes mid-run, the Agent tool returns no output, the render step raises — classifies the iteration as `crash` per the §Autonomy contract iteration outcome taxonomy. A successful N=1 aggregate with non-empty `failed_assertions` proceeds directly to Step F's keep/revert decision on the N=1 `weighted_score` (no saturation handler — the failure list is already the brainstorm signal for the next iteration). A successful N=1 aggregate with empty `failed_assertions` (apparent all-pass) invokes the **Saturation handler** below BEFORE Step F's decision.

**Saturation handler.** When N=1 reports all-pass, the orchestrator must median-confirm the saturation before treating the iteration as a true all-pass. Procedure:

1. Re-invoke the scoring workflow with `trials: 3`. The workflow renders each scenario ONCE and grades it 3× on that fixed render (it reuses the single render per scenario), so the N=3 median measures grader stability on the same input, not render-side variance — re-rendering per trial would triple LLM cost with no statistical benefit. For a 3-scenario skill this is 9 grade agents over 3 renders.
2. The `trials: 3` workflow run assembles the combined 3-trial payload and aggregates it internally; its returned `score` is the median-confirmed composite and its `failed_assertions` reflect the median (per-(scenario, assertion) majority vote across the 3 trials, ties → `False`).
3. Note the N=3 median `score` is NOT `mean(trial1, trial2, trial3)`: the aggregator collapses per-(scenario, assertion) verdicts via majority vote (ties → False) THEN computes one canonical float from the collapsed verdicts. See `_shared/score-skill.md` §Absolute grading § N=3 median trigger for the underlying contract.
4. Interpret the combined `failed_assertions`:
   - **Empty** — saturation confirmed. Step A.2 simplification mode fires for the NEXT iteration; Step F treats the current iteration's score as the N=3 median `weighted_score`.
   - **Non-empty** — saturation rejected; the original N=1 all-pass was noise. Step A.1 targeted mode fires for the NEXT iteration using the median's `failed_assertions[0]` as the anchor; Step F treats the current iteration's score as the N=3 median `weighted_score`.
5. Both branches use the N=3 median `weighted_score` (not the original N=1 score) for Step F's keep/revert decision against the baseline / most-recent-kept score.
6. The 10-min hard timeout is per ITERATION (Step D's existing budget) and COVERS the whole saturation handler — N=1 dispatch + 2 additional trials + aggregator collapse all share the same 10-min envelope. The saturation handler is NOT a separate timeout budget. If the timeout fires mid-saturation, the orchestrator classifies the iteration as `crash` per the §Autonomy contract.
7. Any grader sub-agent error during the saturation handler — non-timeout crash, malformed verdict JSON that exhausts the §Malformed grader output retry budget, etc. — classifies the WHOLE iteration as `crash` per the §Autonomy contract iteration outcome taxonomy. The partial N=2 or N=1 result is discarded; no median is computed from incomplete trials.
8. Cost bound: the saturation handler runs at most once per iteration. For a 5-iter skill, worst case is 5 saturated iters × 9 sub-agents = 45 sub-agents; normal case is 5 iters × 3 sub-agents = 15. The saturation case is bounded — the 3× sub-agent cost is paid only on iters that first cross into apparent all-pass, not on every iter.

Reference cross-link: `_shared/score-skill.md` §Absolute grading § N=3 median trigger — the underlying contract.

NOTE: Goldens-verification handling (per SIHC.1 Step 12) is unwired from this loop body as of SIHC.2 (Option A); see `_shared/score-skill.md` § Goldens verification for the standalone-callable function. Direct invocation by future callers remains supported.

**Step E — extract score.** Parse the scoring sub-agent's returned JSON. Extract `score` as a float in `[0.0, 1.0]` per the single-trial contract in `docs/investigations/skill-iterate-step1-notes.md`. The median-vs-single-trial origin is determined upstream by Step D; Step E treats the float as the iteration's single canonical score regardless. Classify in this order (per `docs/investigations/skill-iterate-step1-notes.md` lines 94-104, which specify that the AMBIGUOUS sentinel returns `{"score": null, "analysis": "AMBIGUOUS: <reason>"}` and the caller maps it to `revert`, NOT `crash`):

1. If `analysis` begins with `AMBIGUOUS:` (regardless of `score` value, including null), classify the iteration as `revert` — the sub-agent could not produce a target output for some scenarios; the mutation produced bad output, not a harness failure.
2. Else if `score` is missing, null, or non-numeric, classify as `crash` per the taxonomy (reserved for harness-side failures only).
3. Else, proceed to Step F's delta comparison with the numeric `score`.

**Step F — decide keep / revert / crash, append results.tsv row, then apply git op.** Apply the iteration outcome taxonomy from §Autonomy contract. For each outcome, append the results.tsv row FIRST (Step G), THEN run any git side-effect — this preserves the commit SHA in the audit trail before a revert orphans it:

- **keep** — score improved (delta > 0): advance the branch (the commit from Step C already exists). Reset the consecutive-revert counter to 0. Reset the consecutive-crash counter to 0. Append results.tsv row. No further git op needed.
- **simplicity-bias on ties** — if the candidate edit shrank the SKILL.md (net negative line count delta) AND the score delta is `>= 0`, classify as `keep` per `primatives/autoresearch/program.md:37` ("removing something and getting equal or better results is a great outcome — that's a simplification win"). This explicit override prevents the loop from rejecting deletion-only simplifications.
- **revert** — score delta `<= 0` (and not a simplicity-bias keep), OR unparseable scoring output, OR AMBIGUOUS-sentinel from the scorer: Append results.tsv row with the Step C commit SHA FIRST, THEN `git -C <worktree-path> reset --hard HEAD~1`. The TSV-before-reset ordering ensures the audit trail row exists before the SHA is removed from branch history. Increment the consecutive-revert counter (feeds the Step A radical-mode threshold). Reset the consecutive-crash counter to 0.
- **crash** — scoring exception, unhandled error, 10-min timeout, or git op failure: Append results.tsv row (the commit may or may not exist; record whatever Step C captured). Increment the per-skill consecutive-crash counter. Do NOT touch the consecutive-revert counter. Three consecutive crashes triggers §Autonomy contract clause 3 — park the skill via a GitHub issue and advance to the next skill in queue (handled by Phase 3, not this loop body).

The keep/revert decision compares against the **most recent kept score** (baseline on iteration 1, then the running high-water mark), not the immediate-prior iteration's score — revert iterations don't change the comparison anchor. When the saturation handler fired upstream in Step D, the iteration's score is the N=3 median `weighted_score`; when it didn't, the iteration's score is the single N=1 `weighted_score`. Step F's keep/revert logic is identical in both cases.

**Step G — append results.tsv row.** Invoke `python .claude/skills/skill-iterate/scripts/append_result.py <skill_path> <commit> <score|NULL> <status> <description> <wall_seconds>` to append. The script writes the TSV header on first call and appends one row per subsequent call; it formats `score` to 6 decimals (or literal `NULL` if the iteration was unscorable), sanitizes tabs/newlines in `description` to single spaces, and formats `wall_seconds` to 3 decimals. This append happens BEFORE the revert-path `git reset --hard HEAD~1` in Step F, so the row's commit SHA references a SHA that existed in branch history at the time of writing (even if revert subsequently orphans it from the branch tip). The file is append-only and gitignored per autoresearch convention (the `.gitignore` wiring is set up by Step 4 of this plan; the writer module also lands in Step 4).

**Step H — check budget caps.** Exit the per-skill loop when ANY of:

- Wall-clock elapsed >= `--per-skill-budget` (default 1h).
- Iteration count >= `--per-skill-iterations` (default 12).
- Consecutive-crash counter >= 3 (triggers §Autonomy contract clause 3; Phase 3 handles the parking).

Otherwise, return to Step A for the next iteration. No other exit condition is permitted — no mid-loop operator prompts, no "should I continue?" gates, no kill-switch polling within the loop (kill-switch is polled BETWEEN skills in Phase 3, per §Autonomy contract clause 4 — "graceful stop between skills, not mid-loop").

**Per-skill wall-clock total.** Per-iteration `wall_seconds` rows in `evals/results.tsv` are not aggregated by this loop. M1 (manual validation per the plan) needs "wall time per skill within ±25% of 30 min budget"; the per-skill total = `sum(wall_seconds)` across that skill's results.tsv rows. The morning summary in Phase 4 will surface this aggregate per skill — see Step 6 of the plan for the aggregator implementation.

**Coverage note — non-scenario-coverable branches.** Step 7's evals are scenario-based, but three branches of this loop are NOT coverable by static scenarios and require non-static fixtures: (1) the AMBIGUOUS-revert branch (Step E classification 1) requires a live LLM that actually returns the `AMBIGUOUS:` sentinel for a constructed-ambiguous SKILL.md; (2) the 10-min-timeout crash branch (Step D) requires a deliberately-slow sub-agent or a stub that sleeps past the cap; (3) the 3-consecutive-crash defect-park branch (Step H) requires deliberately-broken `evals/` to force three sequential harness failures. These are integration-test territory, not scenario-coverable. Step 7 of this plan (or a follow-up step) is expected to add fixture-based integration tests for these three branches; surfaced here as a known scope item for the future invocation.

#### Smoke test (operator-runnable)

The Step 3 done-when criterion is validated by running:

```
/skill-iterate --skill session-wrap --per-skill-iterations 2 --per-skill-budget 10m
```

This invocation must produce 2+ entries in `.claude/skills/session-wrap/evals/results.tsv` (one baseline + at least one iteration). The smoke test itself is run as M1 in this plan's Manual section — NOT as part of this build step.

### Phase 3 — Per-skill ship gate

After each per-skill Phase 2 exits (budget cap hit, iteration cap hit, OR 3-consecutive-crash defect-park triggered), Phase 3 runs the ship decision, the worktree cleanup, the between-skill kill-switch poll, and (at queue end) the lock release.

#### Ship decision

**Pre-ship clean-master check.** BEFORE any merge/branch op, run `git -C <PROJECT> status --porcelain --untracked-files=no`. If the output is non-empty, master is dirty — sibling sessions in this workspace may be actively committing (workspace `CLAUDE.md` § "Parallel session safety" warns about this exact case). Do NOT merge: a `git merge --squash` against a dirty master would sweep sibling work into the skill-iterate squash commit. Instead, take the **dirty-master-skip** path documented below. The pre-ship check runs once per skill, immediately before the merge call. The `--untracked-files=no` flag prevents the m2-launcher's own log directory (untracked, written mid-run) from triggering false dirty-master-skips.

**Line-count measurement protocol.** `total_lines_baseline` = `wc -l` of `.claude/skills/<skill>/SKILL.md` at the per-skill iteration loop's baseline commit (the master HEAD captured at Phase 1 worktree creation; recover via `git -C <worktree> show <baseline-sha>:.claude/skills/<skill>/SKILL.md | wc -l`). `total_lines_final` = `wc -l` of the same path in the worktree's working tree after the final keep/revert resolves, immediately before the Phase 3 ship gate runs. `lines_delta = total_lines_final - total_lines_baseline` (negative = simplification). The line count covers SKILL.md only (not adjacent eval files or scripts/). The composite scoring procedure that produces `final_score` and `baseline_score` is defined in [`../_shared/score-skill.md`](../_shared/score-skill.md); the ship gate combines those scores with `total_lines_baseline` / `total_lines_final` via the SHIP-when rule below.

**Ship-gate rule (composite).** Per the hill-climbing plan's §6 D4 ([`docs/skill-iterate-hill-climbing-plan.md`](../../../docs/skill-iterate-hill-climbing-plan.md)), the ship gate is a **composite of score and line-count** so it stays aligned with the per-iteration simplicity-bias keep classification at §Phase 2 — Per-skill iterate loop > Per-iteration loop body, Step F's `simplicity-bias on ties` bullet (mirroring `primatives/autoresearch/program.md`). Without this alignment, a per-iteration `keep` produced by a line-reducing edit that tied on score would still be discarded at merge — silently nullifying the simplicity-bias philosophy.

> **SHIP when** `(final_score > baseline_score) OR (final_score >= baseline_score AND total_lines_final < total_lines_baseline)`
>
> **no-improvement when** `(final_score < baseline_score) OR (final_score == baseline_score AND total_lines_final >= total_lines_baseline)`

The two clauses of the SHIP condition correspond to (1) any strict score improvement, regardless of line count, and (2) a simplification win — equal score AND fewer lines — which mirrors the Step F simplicity-bias keep at §Phase 2 — Per-skill iterate loop > Per-iteration loop body. Any drop in score blocks shipping (clause 1 disqualifies it; clause 2 cannot rescue it because clause 2 requires `final >= baseline`), so a line-reducing edit that also regresses the score is correctly classified as no-improvement and never reaches master.

Expected outcomes by `(final_score, baseline_score, lines_delta)`:

| Score relation | lines_delta | Ship status | Why |
|---|---|---|---|
| `final > baseline` | any | **SHIP** | Strict improvement always ships (clause 1). |
| `final == baseline` | `< 0` (fewer lines) | **SHIP** | Simplicity-bias preserved — tie with deletion is a simplification win (clause 2). |
| `final == baseline` | `>= 0` (no change or more lines) | **DISCARD (no-improvement)** | No score gain and no line reduction — nothing earned. (Includes the `lines_delta == 0` boundary: a strict-less-than win is required for simplification-bias.) |
| `final < baseline` | any | **DISCARD (no-improvement)** | Regression; line deletion cannot rescue a score drop. |

The pre-ship `git status --porcelain --untracked-files=no` clean-master check applies on top: a branch that satisfies the SHIP condition but lands on a dirty master takes the **dirty-master-skip** path documented below, not the merge.

Four outcomes, gated by Phase 2's exit condition AND the pre-ship clean-master check:

- **keep (merge to master)** when the composite SHIP condition above is satisfied AND `git status --porcelain --untracked-files=no` is empty — i.e. `(final > baseline) OR (final >= baseline AND total_lines_final < total_lines_baseline)`, with clean master. Procedure: do NOT cd into the per-skill worktree (it is about to be removed and the orchestrator never holds cwd there — see worktree cleanup below). From the project root, run `git -C <PROJECT> merge --squash skill-iterate/<skill>-<epoch>` (squash to keep master history clean — each successful per-skill loop becomes ONE squashed commit, not N keep-commits per iteration). Then `git -C <PROJECT> commit -m "skill-iterate: <skill>: baseline N.NN -> final N.NN over K iterations (lines_delta=<+/-N>)"`. The squash-commit message format is canonical so the morning summary in Phase 4 can cross-reference master history, and `lines_delta` is included so simplification-win merges are distinguishable from strict-score-improvement merges at a glance.
- **no-improvement (delete the branch without merging)** when the composite SHIP condition is NOT satisfied — i.e. `(final < baseline) OR (final == baseline AND total_lines_final >= total_lines_baseline)`. The per-skill loop's commits stay on the branch until cleanup; nothing lands on master. Branch deletion is part of worktree cleanup below.
- **defect-park** when Phase 2's Step H exited on the 3-consecutive-crash counter (autonomy contract clause 3). Procedure:
  - File a GitHub issue via `gh issue create` with title `skill-iterate: <skill> parked after N consecutive crashes`. The issue body uses this template:

    ```markdown
    ## skill-iterate: <skill> parked (3 consecutive crashes)

    **Skill:** <name>
    **Crash count:** <N>
    **Last-3 iteration descriptions:**
    1. <desc>
    2. <desc>
    3. <desc>

    **Worktree:** <path>

    **results.tsv contents:**
    ```
    <tsv content here>
    ```
    ```

  - **gh failure fallback.** Wrap the `gh issue create` invocation in try/except (Python `subprocess.CalledProcessError` or non-zero exit). On failure (gh unreachable, auth expired, network out): write the same issue body to `docs/skill-iterate-runs/parked-<skill>-<epoch>.md` (local fallback path; mkdir parents if absent). Print a warning naming the failure mode and the local fallback path, e.g. `warning: gh issue create failed (<exit-code>); parked locally at <path>`. Continue to the next skill — clause 3's "park-and-continue" semantics are still satisfied. The morning summary in Phase 4 reads from both GH and the local fallback directory.
  - Do NOT delete the worktree. Do NOT delete the branch. The operator inspects, decides whether the harness is broken or the skill has hit a hard plateau, and cleans up manually.
  - Advance to the next skill in the queue. The defect-park does NOT halt the whole run; this is the autonomy contract's explicit carve-out for clause 3 (per §Autonomy contract).
- **dirty-master-skip** when the composite SHIP condition is satisfied — `(final > baseline) OR (final >= baseline AND total_lines_final < total_lines_baseline)` — BUT `git status --porcelain --untracked-files=no` is non-empty at pre-ship time. The mutation earned a merge (either a strict score improvement or a simplification win); only the ship environment blocks it. Procedure:
  - Do NOT merge. Do NOT delete the branch. Do NOT delete the per-skill worktree (preserved so the operator can manually merge after resolving the dirty state).
  - Log `ship_status=skipped (dirty-master)` with the list of dirty files (the `git status --porcelain --untracked-files=no` output, capped to first 20 entries) to the morning summary's per-skill section.
  - This is NOT a defect-park (clause 3 is reserved for 3-consecutive-crash). Dirty-master-skip is the **4th legitimate non-halt outcome** of Phase 3 — it counts toward neither the consecutive-crash defect-park counter nor any halt clause. The per-skill loop completed successfully; only the ship gate skipped.
  - Advance to the next skill in the queue.

#### Worktree cleanup

Cleanup runs immediately after the ship decision lands. Per [`.claude/rules/worktree-hygiene.md`](../../rules/worktree-hygiene.md) #2, the orchestrator must NOT cd into the worktree before removing it (Windows file-lock risk — Python processes holding `.pyc` handles or a shell cwd inside the worktree both block removal):

- **On keep (merge):** `git -C <PROJECT> worktree remove --force ~/worktree_skill-iterate-<skill>-<epoch>`, then `git -C <PROJECT> branch -D skill-iterate/<skill>-<epoch>`. The orchestrator never `cd`'d into the per-skill worktree (Phase 2 used `git -C <worktree>` for all in-worktree ops, per worktree-hygiene #5), so one cause of the file-lock failure mode is sidestepped — but not all causes (see retry below).
- **On no-improvement:** same worktree-remove invocation, plus the `git -C <PROJECT> branch -D skill-iterate/<skill>-<epoch>` branch delete (since the ship decision was already "delete without merging").
- **On defect-park:** skip both. Leave the worktree and branch for operator inspection — the GitHub issue references the worktree path.
- **On dirty-master-skip:** skip both. Leave the worktree and branch for operator's manual merge after resolving the dirty state. The morning summary's `ship_status=skipped (dirty-master)` log line points the operator to the preserved worktree path.

**Windows file-lock recovery.** Even with `--force`, `git worktree remove` can fail on Windows when AV scans hold file handles or Python `.pyc` handles linger — the no-cd discipline addresses only one cause (per worktree-hygiene #2). Recovery procedure:

1. First attempt: `git -C <PROJECT> worktree remove --force <path>`.
2. On failure: sleep 2 seconds (gives AV / GC time to release handles), then retry once.
3. On second failure: print `warning: worktree at <path> could not be removed; leaving for manual cleanup` and continue to the next skill. Do NOT halt the orchestrator — orphaned worktree directories are recoverable (Phase 0's worktree-scan in the next run will re-warn), but a halted overnight queue costs the operator the morning's results.

After removal, do NOT verify with `git worktree list` mid-queue (the verification only matters for the morning summary). Per worktree-hygiene #4, an `.gitignore` rule for `worktree_*/` at workspace root prevents accidental `git status` noise if a removal silently failed.

#### Kill-switch poll BETWEEN skills

After each skill's ship decision (whether merge, delete, or park) AND its worktree cleanup, check for `.skill-iterate-killswitch` at workspace root. If present:

1. Hand off to Phase 4's morning-summary writer with the partial queue (skills processed so far + their ship outcomes). The Phase 4 writer must handle the partial case — forward-pointer; Step 6 of the plan owns the writer.
2. Release the `.skill-iterate.lock` file at workspace root (unlink it).
3. Print `Kill-switch detected; graceful stop after <N> of <total> skills.` to stdout.
4. Exit 0.

Do NOT check the kill-switch within Phase 2's iteration loop. Autonomy contract clause 4 mandates BETWEEN-skill polling only; within-loop polling is mid-loop halting, which violates the NEVER-STOP discipline carried over from autoresearch's `program.md`.

#### Lock release on clean queue completion

After the last skill in the queue completes ship + cleanup (no kill-switch hit), remove the `.skill-iterate.lock` file at workspace root. Then proceed to Phase 4 for the morning summary.

**Defensive lock release on exception paths.** The implementation wraps the entire orchestrator loop (Phase 0's lock-taken-point through Phase 4's summary) in `try/finally`. The `finally` block unlinks `.skill-iterate.lock` unconditionally — regardless of whether the loop exited cleanly, raised an uncaught exception, or hit a signal. A secondary `atexit.register(<unlink-lock>)` handler is registered immediately after the lock is taken; this covers `SIGINT` (Ctrl+C) and clean interpreter shutdown paths that `try/finally` alone does not cover when the exception path bypasses normal scope unwinding (e.g. `os._exit` or fatal signals; `atexit` catches the clean-shutdown subset). The combination minimizes the stale-lock window to OS-crash-only.

On unclean exit that bypasses both `try/finally` and `atexit` (OS crash, SIGKILL, power loss), the lock file is left stale. The next `/skill-iterate` invocation's Phase 0 concurrent-run detection handles the takeover per §Autonomy contract — the stale-lock branch overwrites with a warning rather than halting, so a single crashed run does not block the next night's queue.

### Phase 4 — Morning summary

**Trigger.** Phase 4 runs once at the tail of every orchestrator invocation, on three paths: (1) clean queue completion after the last skill ships, (2) kill-switch graceful stop between skills (per Phase 3's contract), and (3) the exception path via the `try/finally` block that wraps the orchestrator loop. Path (3) ensures a partial summary always lands even if Phase 2 raises — the `finally` clause invokes the writer with whatever `SkillResult` records the orchestrator has accumulated up to the failure point.

**Output path.** The writer emits a single markdown file at `docs/skill-iterate-runs/YYYY-MM-DD.md` where `YYYY-MM-DD` is the date in UTC at orchestrator start. The writer auto-disambiguates filenames per the workspace memory `feedback_auto_disambiguate_filenames`: if the target filename already exists (an earlier run today, or a manual stash), the writer appends `b`, then `c`, then `d`, ... up through `z` to find a non-existing path and writes there instead. The actual written path is returned to the orchestrator and printed on stdout for the operator's morning glance.

**Writer invocation.** The orchestrator-LLM collects one `SkillResult` per processed skill across the Phase 2/Phase 3 loop and invokes the writer once at the very end via `python .claude/skills/skill-iterate/scripts/morning_summary.py <runs_dir> --input <payload.json> [--date YYYY-MM-DD] [--partial] [--started-at <iso8601>] [--ended-at <iso8601>]`. The JSON payload has a `skill_results` list (one entry per skill with the eight `SkillResult` fields) plus optional `skipped_by_skip_list` and `skipped_by_cross_night` arrays. The writer is deterministic and stdlib-only — no flakiness contributes to the morning summary itself.

**Partial-summary handling.** When the orchestrator hits the kill-switch between skills (Phase 3 path) OR exits via the exception `finally`, it invokes the writer with `--partial`. The output gets a header line directly under the H1 reading `(partial -- kill-switch hit at <iso8601>)` so the operator can distinguish a complete drain from a graceful-stopped one at a glance. The `SkillResult` list passed in is whatever subset completed before the stop signal — the writer does not re-shape it.

**Per-skill total wall time.** `wall_seconds_total` in each `SkillResult` is the sum of the `wall_seconds` column across that skill's `evals/results.tsv` rows (baseline row included). The orchestrator computes this per skill before passing to the writer; it is NOT recomputed inside the writer. This is the answer to the Step 3 forward-pointer on how the morning summary surfaces the per-iteration wall_seconds rows that `append_result.py` emits during Phase 2.

**Skills with delta < 1%.** Per-skill delta below 1% (`final_score - baseline_score < 0.01`) indicates the hill-climb plateaued — Phase 2's serial exploitation has run out of low-hanging mutations. Such skills are candidates for `/skill-evolve` next session, which dispatches parallel A/B exploration with operator-curated variants instead of serial hill-climb. The morning summary table makes these visible in the `delta` column; the operator can scan for `+0.00`, `0.00`, or single-digit-thousandths deltas and queue those skills for the next overnight via `/skill-evolve --skill <name>`.

---

## Limitations

- **Precondition:** `/skill-eval-setup` must have run for the target skill — no `evals/evals.json` means no scoring, means the skill is silently skipped from auto-discovery (and halted on if passed explicitly via `--skill`).
- **Skip-list skills require per-skill side-effect harnesses** (future work). The 7 skills listed under "Embedded skip-list" produce side-effects rather than text artifacts; the current scoring procedure cannot grade them.
- **Wall-clock OR iteration cap, whichever first.** A skill that produces fast iterations may hit the 12-iteration cap well under 1h; a skill with slow scoring may hit the 1h wall-clock cap on iteration 3. Both are accepted exit conditions.
- **Cross-night-resume is a hard 24h cliff** on `evals/results.tsv` mtime. Manual `touch` resets the window; no round-robin preservation. Acceptable for default.
- **No mid-loop halts.** This is by design — see "Autonomy contract" above. If a per-skill loop needs an operator decision, the right tool is `/skill-evolve` (parallel A/B with curated variants), not `/skill-iterate`.
- **One concurrent run per workspace.** The lock file + worktree scan enforces this; a second concurrent invocation halts at pre-flight rather than racing for worktrees and commits.
- **Scoring composes structural + absolute_weighted axes.** The per-iteration scoring shape is documented above; the procedure itself lives at [`../_shared/score-skill.md`](../_shared/score-skill.md) with a Python wrapper at [`../_shared/score_skill_composite.py`](../_shared/score_skill_composite.py). Composite mode (the default) weights structural metrics at 0.4 and absolute_weighted at 0.6 per SIHC.2 Option A (goldens-verify unwired; the prior pair-comparison mode replaced by absolute grading); weights are configurable via two top-of-procedure constants. Structural-only and absolute_weighted-only modes are available via the `mode` argument for skills that need them. Legacy spec-compliance scoring (pre-SIHC) is no longer in scope; all per-iteration scoring now goes through `_shared/score-skill.md` composite/structural/absolute_weighted modes.
