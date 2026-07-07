# _shared/

Scoring fragments and helpers shared across the `/skill-iterate` and
`/skill-eval-setup` pipeline. Each `.md` file here is a procedure doc the
orchestrator-LLM reads at runtime; each `.py` file is a thin wrapper that
exposes the same procedure programmatically for tests and Python callers.

Files in this directory are referenced from sibling skill SKILL.md files via
relative paths (e.g. `../_shared/score-skill.md`). The directory is NOT a
skill itself — it has no `SKILL.md`.

| File | Purpose | Consumer |
|---|---|---|
| `score-skill.md` | Composite skill-scoring procedure (structural + differential) | `/skill-iterate` Phase 2 Step D |
| `score_skill_composite.py` | Thin Python wrapper around the composite procedure for tests + non-LLM callers | `test_score_skill.py` + smoke runs |
| `test_score_skill.py` | Integration test for the composite scoring procedure | `pytest` |
