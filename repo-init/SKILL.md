---
name: repo-init
description: >
  Use when a local project directory has no GitHub repo and needs to be
  published — initializing git, creating the remote repo, adding a README,
  and converting a plan document into GitHub issues.
---

# Repo Init

## Overview

Use this skill to take a bare local project directory all the way to a fully scaffolded GitHub repo with a README and issues.

**Core principle:** Read the plan first -> git init -> push -> README -> issues, in that order.

## Steps

### 1. Confirm inputs with the user

Confirm these inputs before any git or gh command runs:
- Repo visibility: **public or private?**
- Repo name (suggest the directory name as default)
- Target account/org (default: the authenticated `gh` user)

### 2. Check prerequisites

```bash
gh auth status          # must show active account with repo scope
ls -la <project-dir>    # confirm .git does NOT exist
```

If `.git` already exists, skip step 4 (git init + first commit) and jump to step 5
(create the GitHub repo and push). Do not re-run `git init` on an existing repo.

### 3. Read the plan document

Before writing any git commits or the README, read `plan.md` (or equivalent) in
the project directory. This is required — the README and issues are derived from it.

### 4. Initialize git and make the first commit

```bash
cd <project-dir>
git init
git add .
git commit -m "Initial commit: <project-name> project scaffold

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

### 5. Create the GitHub repo and push

```bash
gh repo create <repo-name> --private --source=. --remote=origin --push
# or --public if requested
```

### 6. Write the README

Generate `README.md` from the plan. A good README includes:
- One-paragraph description of what the project does
- Stack table (tool + why)
- Prerequisites
- Setup steps (numbered, runnable)
- Key design decisions (brief)
- Data store or project structure diagram (if relevant)

Do **not** duplicate the full plan — summarize and surface what a new contributor needs to get started.

Commit and push:
```bash
git add README.md
git commit -m "Add README

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
git push
```

### 7. Create GitHub issues from the build steps

Read the build order section of the plan. Create one issue per step using `gh issue create`.

The plan typically labels build steps under a "Build Order" or "Steps" heading;
if no such section exists, ask the user how to slice the work before any issues are filed.

**Issue body structure for each:**
- `## Build step N of M`
- `### Files` — list of files to produce
- `### What to build` — concrete description drawn from the plan
- `### Quality gates` — test/lint/typecheck commands
- `### Notes` — key constraints or gotchas from the plan

Create issues **one at a time** with separate `gh issue create` calls (not batched in a single shell command) to avoid quoting failures.

```bash
gh issue create --title "Step N: <title>" --body "<body>"
```

## Constraints

- Always confirm visibility, name, and account with the user before any `git` or `gh` command runs.
- Always read `plan.md` (or equivalent) before writing the README or creating issues; both are derived from it.
- Always call `gh issue create` once per issue; never stack multiple heredocs in one shell command.
- Always include a `Co-Authored-By: Claude` trailer in the scaffold commit and the README commit.
- Skip `git init` when `.git` already exists in the project directory.

## Limitations

- Handles initial repo creation only; updating issues, labels, or milestones later needs separate tooling.
- Requires the `gh` CLI authenticated with `repo` scope; org repos under restricted-policy may still reject the `gh repo create` call.
- Does not configure branch protection, default reviewers, labels, milestones, or GitHub Projects.
- Treats `plan.md` as the single source for README and issues; multi-plan or wiki-style sources are out of scope.

## Common Mistakes

**Batching issue creates in one shell command**
- Problem: Multi-heredoc quoting fails with EOF errors
- Fix: One `gh issue create` call per issue, separate Bash tool calls

**Writing the README before reading the plan**
- Problem: Generic README that misses key design decisions
- Fix: Always read plan.md first

**Skipping the inputs check**
- Problem: Creating a public repo when the user wanted private (or wrong account)
- Fix: Confirm visibility, name, and account before any git or gh commands
