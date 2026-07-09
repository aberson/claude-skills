# claude-skills

A collection of [Claude Code](https://docs.anthropic.com/claude-code) skills for planning, building,
reviewing, and shipping software with AI agents. These are the real workflow skills I use day to day,
lightly generalized for sharing.

> Extracted from a personal workspace. Paths and identifiers are generalized to placeholders
> (`<workspace>`, `<project>`, `<your-org>`). A few skills reference personal conventions — a
> workspace "control plane" and a file-based memory system — that you would adapt to your own setup.

## What's inside

| Area | Skills |
|------|--------|
| **Planning** | `plan-init` · `plan-feature` · `plan-review` · `plan-wrap` · `plan-merge` · `plan-trim` · `plan-expedite` |
| **Building** | `build-step` · `build-phase` · `build-queue` · `bug-fix` |
| **Review** | `review-deep` · `review-gauntlet` · `review-proof` · `review-memories` · `review-uat` |
| **Repo & docs** | `repo-init` · `repo-sync` · `repo-update` |
| **User & session** | `user-brainstorm` · `user-draft` · `user-learn` · `user-orient` · `user-pm` · `user-recap` · `user-shakedown` · `user-uat` · `user-walkthrough` · `session-wrap` · `task-handoff` · `context-slim` |
| **Meta / skill tooling** | `skill-eval-setup` · `skill-evolve` · `skill-iterate` · `test-prune` · `lesson-harvest` · `research-prospect` |
| **Auth** | `claude-oauth-auth` |

`_shared/` holds resources referenced by several skills.

The design idea across all of these: treat agent work as a **pipeline with quality gates** — plan,
build one step at a time, review with independent adversarial passes, and only then ship. Several
skills use multi-agent fan-out (parallel reviewers, judge panels, generate-then-grade loops).

**[WORKFLOWS.md](WORKFLOWS.md) maps how the skills chain together** — the core plan → build → ship
pipeline plus the supporting loops (UAT, overnight runs, session management, skill self-improvement),
each as a copy-pasteable command sequence.

## Install

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

## Adapt before use

- Replace placeholders (`<workspace>`, `<project>`, `<your-org>`) with your own values.
- Skills that reference a "control plane" or a memory index assume conventions from my workspace —
  read the `SKILL.md` and adjust, or skip those skills.
- No secrets or credentials are included.

## License

MIT — see [LICENSE](LICENSE). Built by Abraham Robison ([github.com/aberson](https://github.com/aberson)).
