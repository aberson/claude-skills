---
name: well-structured-fixture
description: Sample SKILL.md that scores HIGH on all 8 structural metrics
---

# Well-structured fixture

A small SKILL.md demonstrating proper heading hierarchy, required sections,
clean code fences, no banned phrases, no broken links, and a healthy mix of
imperative rules and explanatory rationale.

## Steps

Run the skill end-to-end with these phases.

### Phase 1: Setup

Verify the workspace is clean before starting. Read the plan document first.

### Phase 2: Execute

Run the build step against the target file. Capture stdout to a log.

```bash
uv run python build.py target.md > run.log
```

## Constraints

Use only stdlib modules. Avoid adding new dependencies. Pin the model version
so reruns are reproducible. Verify the output matches the expected schema.

The rationale here is that deterministic tooling survives Anthropic model
updates that would otherwise invalidate cross-run comparisons. A small,
self-contained script is easier to audit than a transitive dependency tree
and keeps the bootstrap path short for fresh worktrees.

## Limitations

Do not run this skill against files larger than 50KB without chunking. Set
a timeout of 60 seconds per scenario. Skip the differential grader when no
baseline exists.

```python
TIMEOUT_SECONDS = 60
MAX_BYTES = 50 * 1024
```

The hard cap exists because the grader sub-agent's wall-clock cost is
quadratic in input size and overruns silently consume the per-skill budget.

## See also

Related fixture: [degraded](degraded.md) for the low-scoring counterpart.
