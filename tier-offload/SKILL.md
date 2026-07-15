---
name: tier-offload
description: Scan your own .claude/skills/ to find which LLM-bearing sub-tasks are safe to offload to a local model, and emit both a human-readable offload inventory and a switchboard config the local_judge client can load. Fans out read-only Explore agents to classify each skill's roles (ORCH/AUTHOR/PLAN/JUDGES/GATE/MECH/SOLO), applies the difficulty-based routing rule (only a cheap fan-out judge/grader slice is local-safe), and writes the inventory + config. Discovery + config only — it never auto-wires a skill to local_judge. Run bare to scan + report + write the artifacts.
user-invocable: true
argument: "Optional flags: --skills-dir <path> (default: <innermost project>/.claude/skills); --out-dir <path> (default: ./offload-scan-out); --inventory-only (write the markdown inventory, skip the config); --dry-run (print the report, write nothing)"
---

# tier-offload

Reads every `SKILL.md` under your `.claude/skills/`, classifies each skill's LLM-bearing roles with a fixed taxonomy, then applies the Switchboard routing rule to decide which (and only which) sub-tasks are safe to run on a cheap **local** model instead of Claude. It emits two artifacts: a human-readable **inventory** (markdown, grouped by routing verdict) and a **switchboard config** (`enabled_call_sites` map) that the `switchboard` `local_judge` client loads directly.

This is the generic, contributable **scanner** half of Switchboard offload. It is **discovery + config only** — it identifies and configures the local-safe slices; the actual wiring of each skill to call `local_judge` stays a guided, per-user edit you make afterward. It never edits a skill.

## When to use

- You've adopted the `switchboard` local-offload core and want to know which of *your own* skills have a sub-task safe to route to the local model.
- You want to regenerate the offload inventory after adding or changing skills (the safe surface drifts as skills evolve).
- You want a config file the `local_judge` client can load, without hand-authoring the `enabled_call_sites` map and risking a shape mismatch.

## Background — the routing rule this skill encodes

The offload's one governing rule (Switchboard Decision 9 / the 3-tier judge split): **authorship, planning, orchestration, and any final/gating judgment stay on Claude; only a fan-out array of cheap judges/graders goes local; mechanically-checkable work goes to a script (no LLM).** The local model is **never on a correctness gate** — it advises, a Claude final judge decides.

### Taxonomy + classification protocol — shared reference

Classification follows [`_shared/skill-role-taxonomy.md`](../_shared/skill-role-taxonomy.md): its **§1 taxonomy** (the seven tags — ORCH / AUTHOR / PLAN / JUDGES / GATE / MECH / SOLO — plus the tag boundaries), its **§2 fan-out classification protocol**, and its **§3 output shape**. That reference is direction-neutral; this skill layers the down-direction (offload) rules on top: the four corrections below, the hard gate-precondition invariant, and the LOCAL / CLAUDE / SCRIPT verdict columns added in Phase 2.

### The four corrections (apply them — a naive "every fan-out → local" read is wrong)

1. **Authorship fan-outs are NOT offloadable.** `user-brainstorm` / `user-learn` / `repo-init` / `repo-update` fan out, but each agent *writes content* (AUTHOR), so it stays Claude. A fan-out is only local-safe if every arm is *judging*, not *producing*.
2. **Only the Style reviewer lens is cheap.** In a multi-lens reviewer (review-gauntlet / review-deep / build-step), the **Correctness** and **Bugs** lenses are deep-reasoning drift-catchers (`code-quality.md`) and stay Claude. Only the **Style** lens is the cheap local slice. (review-deep's Style lens already runs on Haiku — smallest lift.)
3. **A checklist "fan-out" that is really one Claude pass is NOT a drop-in.** `plan-review` / `plan-wrap` enumerate "sections" but run them as a single Claude pass today, not a real parallel array. Tag SOLO, route Claude; it's refactorable-to-local later, not offloadable now.
4. **Tool-using judge arms are never local-safe.** A JUDGES array whose arms require live tool use (WebFetch/browser, `gh`, substrate commands) cannot route to `local_judge` regardless of shape — the local endpoint is text-in/text-out. Verdict CLAUDE with a tier note (`sonnet`, low effort) naming the blocking tool. Canonical example: deep-research's 3-vote source-verification array — perfect JUDGES shape, blocked by its WebSearch/WebFetch requirement.

And the hard invariant: **offloading a JUDGES array is only safe if a Claude GATE consolidates its findings.** If a skill's reviewers gate *directly* today (build-step does), routing them local without first inserting a Claude final judge makes the weak model the gate — forbidden. Flag this in the inventory as a precondition (`gate-precondition: insert-claude-final-judge`), never as already-safe.

## Phase 1 — Bootstrap: discover the skill set

Parse args. Resolve `--skills-dir`:
- If given, resolve to an absolute path.
- Default: walk up from cwd to the innermost ancestor containing a `.claude/skills/` directory; use that.

Enumerate the skill set per the shared reference's §2 steps 1–2 (Glob discovery, skip non-skill entries, `ls` the matched filenames before quoting any into a sub-agent prompt).

Resolve `--out-dir` (default `./offload-scan-out`). Create it if absent (PowerShell: `New-Item -ItemType Directory -Force <path>`).

Print the discovery line before analysis: the resolved skills dir, the count of skills found, and the out dir.

## Phase 2 — Parallel classification (read-only Explore fan-out)

Run the shared reference's **§2 fan-out classification protocol** exactly (read-only Explore agents pinned `model: sonnet` per the reference §2, 6–8 skills per batch, all of a batch's agents dispatched in one message, the §1 taxonomy verbatim in every agent's prompt, read-only/classify-only discipline), with these down-direction additions:

- Each agent's prompt must include — besides the reference's §1 taxonomy verbatim, per the reference's own protocol — the **four corrections** verbatim (above). Every agent must apply the SAME rules, or the inventory drifts per-batch.
- Each agent extends the reference's §3 output shape with the down-direction verdict columns, returning per skill: `Skill | Roles (tags) | Verdict | Local slice (if LOCAL) | Note`, where **Verdict** is:
  - **LOCAL** — has a genuine JUDGES array (parallel cheap scoring), every arm judging not producing. Name the specific slice (e.g. "structural/rubric grader", "Style lens").
  - **CLAUDE** — only ORCH / AUTHOR / PLAN / GATE / SOLO roles (or a JUDGES array that fails a correction).
  - **SCRIPT** — only MECH roles; nothing to offload to an LLM.
- For each LOCAL verdict, require: the slice name, and whether a `gate-precondition` applies (does the skill's array gate directly today, needing a Claude final judge inserted first?).

Collect every agent's table before Phase 3.

## Phase 3 — Synthesize the inventory + config

Merge all agent tables into one inventory, grouped exactly like the Switchboard Appendix:

1. **The local surface** — the table of LOCAL skills only: `Skill | Local slice (small model) | Everything else → Claude | Note`. This is the load-bearing output.
2. **All-Claude** — bulleted list of CLAUDE-verdict skills (authorship / planning / single-pass reasoning / orchestration / final-gate).
3. **No LLM (scriptable / mechanical / doc)** — bulleted list of SCRIPT-verdict skills.

Write the inventory to `<out-dir>/inventory.md`. Lead it with a one-paragraph summary: N skills scanned, K local-safe slices found, and the date.

### Build the config (skip if `--inventory-only`)

For each LOCAL slice, mint a **task_class** name and add it to the `enabled_call_sites` map. The task_class is the call-site identifier the wired skill will pass to `local_judge(task_class=...)`. It MUST satisfy switchboard's name-safety rule — match `^[A-Za-z0-9._\-]+$` exactly (letters, digits, `.`, `_`, `-` only; **no spaces, no slashes, no `:` or other metacharacters**). Use a stable `<skill>-<slice>` slug, e.g. `skill-iterate-grader`, `review-gauntlet-style`, `context-slim-classifier`.

Map each task_class to:
- `true` — offload allowed, use switchboard's default model (the common case; the production deployment uses one model for all slices per switchboard D2).
- a model-name string — only if you deliberately pin a different model for that slice (must also match `^[A-Za-z0-9._\-]+$`). Default to `true`.

**Do NOT include a slice that has an unmet `gate-precondition`** as plain `true` — instead emit it as `false` (configured but disabled) and note in the inventory that it activates only after the Claude final-judge is inserted. This keeps an unsafe slice from silently becoming a live gate.

Write the config as JSON to `<out-dir>/offload-config.json` with exactly this shape (this is the integration contract — it must load into `switchboard.config.SwitchboardConfig`):

```json
{
  "less_token_mode": true,
  "enabled_call_sites": {
    "skill-iterate-grader": true,
    "skill-evolve-grader": true,
    "review-gauntlet-style": true,
    "review-deep-style": true,
    "goblin-suggest-judge": true,
    "context-slim-classifier": true,
    "build-step-style": false
  }
}
```

Shape rules (match `switchboard/config.py` exactly):
- Top-level keys are a subset of `SwitchboardConfig`'s fields: `less_token_mode` (bool), `enabled_call_sites` (object), optionally `effort` (object), and optionally `base_url` / `model` / `cold_timeout_s` / `warm_timeout_s` / `max_tokens`. Emit only `less_token_mode` + `enabled_call_sites` unless the user pinned endpoint values — let the rest default.
- `enabled_call_sites` is an **object** mapping each task_class **string** to a **bool or a model-name string**. No nested objects, no arrays, no nulls.
- `effort` (optional) is an **object** mapping a task_class **string** to a Claude-side reasoning-effort tier — one of `low` / `medium` / `high` / `xhigh` / `max`. HONEST SCOPE: this is a hint for **Claude-side sub-agent dispatch** (a Workflow/Agent `reasoning_effort` override when the slice's judges run on Claude); `local_judge` does NOT consume it. switchboard validates + round-trips it but acts on nothing — emit `effort` only to record a per-slice recommendation (e.g. `{"review-deep-style": "low"}`), never as a live local knob.
- Every task_class key AND every model-name value must match `^[A-Za-z0-9._\-]+$`.
- A slice that gates directly today (unmet `gate-precondition`) is emitted as `false`.

## Phase 4 — Report

Print a summary (do not truncate):

```text
tier-offload — <skills-dir>

Scanned:        N skills
Local-safe:     K slices  (M live / G gated-pending-final-judge)
All-Claude:     A skills
No-LLM:         S skills

Artifacts:
  inventory.md       — <out-dir>/inventory.md
  offload-config.json — <out-dir>/offload-config.json   (loads into SwitchboardConfig.enabled_call_sites)

Next (per-user, NOT done by this skill):
  Install the config so the switchboard client loads it: copy offload-config.json to
  ~/.switchboard/config.json (the home default, $HOME\.switchboard\config.json on Windows)
  OR set $env:SWITCHBOARD_CONFIG to its path, then verify with `python -m switchboard config`
  (offload_active:true means it is live). See switchboard/README.md "Turning offload on/off"
  for the full enable/disable flow + resolution order.
  For each live slice, wire the skill's sub-task to call local_judge(task_class="<key>").
  For each gated slice, first insert a Claude final-judge that consolidates, then flip the
  config entry from false → true.
```

End with the exact standalone line:

`tier-offload wrote the inventory + config — wiring each slice to local_judge stays a guided per-user edit (it was NOT auto-applied).`

## Constraints

- **Discovery + config only. Never auto-wire.** This skill never edits a `SKILL.md` to call `local_judge`. It writes the inventory and the config; the operator wires each slice.
- **Use read-only Explore agents for classification.** They cannot edit or write — the safe substrate for reading someone's skills.
- **Apply the four corrections.** Authorship fan-outs → Claude; only the Style reviewer lens is cheap; checklist single-passes are SOLO not LOCAL; tool-using judge arms are never local.
- **Never emit a directly-gating array as live (`true`).** Emit `false` + a `gate-precondition` note; it activates only after a Claude final-judge is inserted (Switchboard Decision 3 — the local model is never the gate).
- **The config must load.** Every task_class key and model-name value must match `^[A-Za-z0-9._\-]+$`. No spaces/slashes/colons. Values are bool or model-name string only. A mismatch here is the bug class `test_sample_config_loads.py` exists to catch — if unsure, validate against `switchboard/config.py` before writing.
- **Autonomous — no mid-run (y/n) prompts.** Run bare = scan + report + write inventory + config. `--dry-run` prints the report and writes nothing.
- Do not commit. Leave artifacts in the out dir for the operator.
