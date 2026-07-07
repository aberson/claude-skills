---
name: research-prospect
description: Scan active projects and surface /deep-research topic strings per project. Reads MEMORY.md to enumerate projects, fans out parallel Explore agents (one per project) to identify 2-3 high-value research topics each, then renders a grouped copy-pasteable menu. Use when you want token-rich research tasks to hand off to separate windows, or when you want to understand what research would most improve each project.
user-invocable: true
---

# research-prospect

Scan each active project for research gaps and produce a ready-to-run `/deep-research` menu, grouped by project.

## When to use

- You want high-token tasks to distribute across multiple windows.
- You want to understand what research would most improve each project before starting a deep-work session.
- You need a menu of specific, grounded research questions rather than a brainstorm.

## When NOT to use

- You already know the topic — skip straight to `/deep-research "<topic>"`.
- You want a deep investigation of one specific project — ask for that directly instead.
- MEMORY.md "Active projects" is known to be stale — run `/session-wrap` first to update it.

## Arguments

| Arg | Required | Default | Description |
|---|---|---|---|
| `--projects <list>` | no | all active projects from MEMORY.md | Comma-separated project names or directory paths. Example: `--projects Alpha4Gate,toybox` |
| `--session-wrap` | no | off | After rendering the menu, invoke `/session-wrap` with all topics listed as next-step options. |

---

## Steps

### Step 1: Resolve project list

**If `--projects` was provided:** parse it as a comma-separated list. Each item is either a project name (look up under `<workspace>/<name>/`) or an absolute path.

**If `--projects` was not provided:** read `MEMORY.md` from `~/.claude/projects/<project>/memory/MEMORY.md`. Locate the "Active projects" section. Extract every project name listed there. For each, derive its directory: check `<workspace>/<name>/` (case-insensitive). Capture the one-line MEMORY.md entry for each project — this feeds the agent as background context.

Warn and skip any project whose directory cannot be resolved. Do not halt.

Emit one line before Step 2: `Scanning N projects: <names>.`

---

### Step 2: Fan out parallel Explore agents

Dispatch **all agents in a single parallel message** — one Explore agent per project. Do not wait for one to finish before dispatching others. Parallel dispatch is the primary throughput gain of this skill; sequential dispatch is a defect.

Each agent receives the following prompt (fill in the bracketed fields):

```
Investigate <PROJECT_NAME> at <PROJECT_DIR> to identify 2-3 specific /deep-research topics that would meaningfully improve the project.

Background from workspace memory: <MEMORY_LINE — the one-line MEMORY.md entry, or "not in memory" if absent>

Read in this order (stop when you have enough context):
1. <PROJECT_DIR>/CLAUDE.md — stack, commands, known gotchas
2. <PROJECT_DIR>/documentation/master_plan.md or plan.md — current phase/step status
3. git -C "<PROJECT_DIR>" log --oneline -15 — recent work
4. Any open investigation docs under <PROJECT_DIR>/documentation/investigations/

Focus on: algorithmic gaps, known plateaus, open architectural questions, techniques the plan defers to "future phases", quality or accuracy limitations surfaced in UAT, or infrastructure decisions where research would inform a go/no-go gate.

Return ONLY a JSON object (no prose before or after it):

{
  "project": "<PROJECT_NAME>",
  "current_state": "<one sentence: what is built and where it is stuck>",
  "research_topics": [
    {
      "title": "<research question phrased as a /deep-research argument — 12-25 words, specific and searchable>",
      "why": "<1-2 sentences citing a specific gap in the codebase, plan, or recent git history>",
      "depth": "high|medium"
    }
  ]
}

Rules:
- 2 topics minimum, 3 maximum.
- Titles must work as /deep-research arguments: specific, concrete, not generic phrases like "improve performance" or "better algorithms."
- "why" must cite something observed in the code, plan doc, or git log — not general best-practices reasoning.
- If the directory does not exist or has no readable files, return: {"project": "<name>", "error": "directory not found or empty"}.
```

Collect all results. Projects that return `"error"` are logged under a `Skipped` line in the output but do not halt rendering.

---

### Step 3: Render the menu

For each project with valid results, render a group:

```
## <PROJECT_NAME> — <current_state>

  X1: /deep-research "<title>"
      Why: <why>

  X2: /deep-research "<title>"
      Why: <why>

  X3: /deep-research "<title>"   (if present)
      Why: <why>
```

Where `X` is a single-letter prefix: first letter of the first word of the project name, uppercased. If two projects share the same letter, use a two-letter prefix for the second (e.g., `VO` for void_furnace if `VF` was already used).

After all groups, emit a flat "QUICK COPY" block:

```
--- QUICK COPY (one per window) ---
/deep-research "<A1 title>"
/deep-research "<A2 title>"
...
```

The quick-copy block is **mandatory** regardless of topic count — it lets the user grab a single line per window without stripping the "Why" annotations.

---

### Step 4 (only if `--session-wrap` flag passed)

Immediately invoke `/session-wrap` after Step 3 output. Pass the full topic list (all `/deep-research "..."` invocations, grouped by project) as the next-step options argument. One-sentence transition max before the skill call — do not emit verdict prose summarizing what was found.

---

## Output format

- Target: 20–70 lines for the full menu.
- Do not truncate topics to hit a word count. Accuracy over brevity.
- The QUICK COPY block always appears at the end, even if only one project was scanned.

---

## Constraints

- **Parallel dispatch required.** All Explore agents in one message. Sequential dispatch is a defect.
- **JSON only from agents.** Agents returning prose instead of JSON are treated as parse failures. Log the project as skipped with a note; do not try to extract topics from prose.
- **"why" must be grounded.** If an agent's "why" reads as generic best-practice advice with no codebase anchor, mark it `(unverified — no specific gap cited)` rather than presenting it as a confirmed finding.
- **Title phrasing discipline.** Reject titles that are generic. A usable title names the technique, the constraint, and the domain: "SPRT early-stopping thresholds for small-n win-rate gates in game-playing bot evolution" not "statistical testing for bot evaluation."
- **No invented projects.** Only scan projects listed in MEMORY.md or explicitly named via `--projects`.

---

## Limitations

- **MEMORY.md must be current.** Projects not listed under "Active projects" are invisible to this skill unless named via `--projects`. If MEMORY.md is stale, run `/session-wrap` first.
- **Explore agents read excerpts, not whole files.** On large plan.md files (>2000 lines), agents see early sections first. Open investigations buried deep in the plan may be missed. Use `--projects <name>` with a more focused prompt if a specific project needs deeper coverage.
- **Directory name must match MEMORY.md entry exactly.** If a project is listed as `b2_project_goblin` but the directory is `goblin/`, resolution will fail. Fix MEMORY.md or use `--projects <workspace>/goblin`.
- **Agent JSON format is best-effort.** Explore agents are not constrained-output models. If an agent returns valid JSON with the right keys, use it. If it returns close-enough JSON (minor key differences), parse it gracefully. Only escalate to "skipped" if the output is unparseable.
