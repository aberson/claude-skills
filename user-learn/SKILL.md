---
name: user-learn
description: Scaffold a hands-on learning ramp for a topic using the applied-learning method (70% hands-on / 20% mentoring / 10% coursework). Given a topic, creates a self-contained folder with a knowledge base, runnable Jupyter notebooks (graphics included, self-validated by execution), standalone code examples, exercises, project-grounded seed ideas, and a progress tracker. Fans out one sub-agent per file. Use when the user wants to learn a concept by doing, not just reading. Invoke as "/user-learn <topic>".
---

# user-learn

Turn a topic into a self-contained, **hands-on** learning folder. The method is applied learning — **70% hands-on, 20% mentoring, 10% coursework** — and that ratio is made physical in the folder layout (`70-handson/`, `20-mentoring/`, `10-coursework/`).

Two phases: a short **interactive setup** (get topic, confirm scope, ground in the user's real projects), then **parallel authoring** (one background sub-agent per file; notebook agents author AND execute their own notebook until it runs clean).

Default output root is the `applied_learning/topics/<slug>/` repo. The skill is topic-agnostic and reusable for any future concept.

## When to use

- The user wants to ramp on a concept (an ML technique, an engineering pattern, a tool) by doing.
- The user wants runnable examples + a small reading list + ideas for applying it, not a one-shot explanation.

## When NOT to use

- A single specific question — just answer it.
- The topic already has a folder under `topics/` — point at it (or offer to extend it).

## Steps

### 1. Get the topic

Required argument. Derive a kebab-case slug. Confirm the output path (default `applied_learning/topics/<slug>/` relative to the dev workspace root).

**Existing-topic guard:** Before proceeding, check whether `applied_learning/topics/<slug>/` already exists. If it does, stop immediately: tell the user the folder exists, offer to extend it or open it, and do NOT recreate it.

### 2. Confirm scope

Show the user: the folder layout (below), the planned notebook list (3-5 titles), and the depth (default: knowledge base + 4 notebooks + examples + exercises + seed-ideas). Ask "Proceed?" and wait. (This skill is interactive/user-facing — a confirm here is expected; it is NOT a build-pipeline skill.)

Depth knob: `maximal` = full KB + 4-5 notebooks + standalone examples + full exercise set. `lite` = KB + 3 notebooks (skip standalone examples and full exercise set). Default `maximal`.

### 3. Ground

Before dispatching, gather the inputs the agents need:

- **Canonical-papers list.** Assemble a vetted list of real, well-known papers for the topic. Format: `Author, Year` only. Include an arXiv ID only if you are absolutely certain of it AND mark it explicitly as `(verified)` — e.g. `Kingma & Welling, 2013 (verified: arxiv:1312.6114)`. If uncertain, omit the ID entirely. The seminal-papers agent gets this verbatim so it never fabricates citations.
- **Project applications.** Read the `CLAUDE.md` of the user's active workspace projects relevant to the topic (e.g. Alpha4Gate, toybox, sandtable, void_furnace, b2_project_goblin). The seed-ideas agent gets these paths + your notes so applications are concrete and real.
- **Notebook plan.** Decide the 3-5 notebooks: order them toy/intuition (numpy-only, always runs) -> from-scratch -> realistic-but-tiny -> advanced concept. Write a one-line spec per notebook (what it shows, what graphic it produces, whether it needs torch).

### 4. Dispatch sub-agents in waves

One background sub-agent (`run_in_background: true`) per file, in waves of ~6-10 (a single mega-batch has triggered 529 cascades). One agent each for:

- every `10-coursework/*.md` and `20-mentoring/*.md` file (the seminal-papers + seed-ideas agents get the grounding from step 3),
- every notebook in `70-handson/notebooks/` (each authors + self-validates its own notebook — see the notebook template),
- every `70-handson/examples/*.py` and `exercises.md`.

Retry any agent that fails (529, timeout) as a fresh single dispatch.

### 5. Write README + progress

After agents complete, glob the folder to confirm every planned file exists. Then write `topics/<slug>/README.md` (index + suggested learning path, tier-ordered: skim coursework essentials -> work the notebooks in order -> do the exercises -> read seed-ideas) and `20-mentoring/progress.md` (a checklist derived from the ACTUAL notebooks + exercises produced).

### 6. Goblin hook

`applied_learning` is already a `b2_project_goblin` target (it has a `CLAUDE.md` + `plan.md`). End by noting `uv run goblin suggest applied_learning` (from the goblin repo) as the "what should I learn/do next" nudge — goblin ranks next steps grounded in the topic folders. Do not modify goblin's source.

### 7. Report

Files written, any agent retries, notebook execution results (all green?), and one suggested next action (open the README, run a notebook, run `goblin suggest`).

## Output layout

```text
topics/<slug>/
├── README.md
├── 10-coursework/
│   ├── essentials.md          # core concepts + math prereqs, intuition-first
│   ├── papers-seminal.md      # foundational papers (from the vetted list — no fabricated ids)
│   ├── papers-frontier.md     # interesting/applied/recent papers tuned to the user's projects
│   ├── related-topics.md      # adjacency map; each entry 2-3 line explainer + link
│   └── courses-resources.md   # courses, lectures, blogs, textbooks
├── 20-mentoring/
│   ├── seed-ideas.md          # concrete applications in the user's REAL projects (grounded)
│   ├── open-questions.md      # discussion prompts to work through with a mentor / Claude
│   └── progress.md            # self-tracking checklist (written by the orchestrator in step 5)
└── 70-handson/
    ├── notebooks/             # NN-*.ipynb, runnable, executed-in-place (graphics embedded)
    ├── examples/              # standalone runnable .py scripts
    └── exercises.md           # graded exercises with hints + solution pointers
```

## Sub-agent prompt templates

### Knowledge-base / mentoring file agent

**Every KB agent prompt must include the 300–700 word hard limit from the CONSTRAINTS block below. Do not abbreviate or omit it for any file in the batch.**

```text
Write ONE markdown file at <ABS-PATH>/<FILE>.

Topic: "<TOPIC>". This file is the <ROLE> (e.g. "essentials", "seminal papers", "seed ideas").

READ for grounding (don't invent): <repo CLAUDE.md; for seed-ideas, the listed project CLAUDE.md paths; for seminal-papers, USE THE VETTED LIST BELOW VERBATIM>.

<for papers-seminal.md: VETTED CANONICAL PAPERS (use these, do not add ids you are unsure of):
- <Author Year — Title — arxiv id if certain> ...>

<for seed-ideas.md: TARGET PROJECTS + ANGLE:
- <project>: <one-line of how the topic could apply, grounded in what you read> ...>

CONTENT: <what this specific file should contain — see Output layout comments>.

CONSTRAINTS:
- Terse, reference tone, written to be grepped later. **300–700 words (hard limit).**
- No emojis. No padding (one honest line beats a filler paragraph).
- No fabricated citations or arXiv ids. Author+year is always safe; link arxiv.org/abs/<id> only when certain.
- Markdown links relative from the file's location.

Write with the Write tool. Reply: "Wrote <FILE>" + notes.
```

### Notebook agent (authors AND self-validates)

**Every notebook agent prompt must include the full SELF-VALIDATE block below. Do not abbreviate or omit it for any notebook in the batch.**

```text
Author ONE Jupyter notebook at <ABS-PATH>/70-handson/notebooks/<NN>-<slug>.ipynb, then make it run clean.

Topic: "<TOPIC>". This notebook: <one-line spec — what it teaches + the graphic it produces>.

REQUIREMENTS:
- Valid nbformat v4 JSON. Most reliable: write a small builder script using `nbformat` (assemble markdown+code cells, then `nbf.write(...)`), run it, then delete it. If you use a builder or any temp file, give it a UNIQUE name that includes this notebook's `NN-` prefix (e.g. `_build_<NN>.py`) and delete it immediately after — parallel sibling notebook agents run concurrently in the SAME notebooks dir and collide on shared temp filenames. (Alternatively write the `.ipynb` directly via the Write tool or NotebookEdit.)
- Markdown cells explain the intuition before each code cell. Code cells are small and readable.
- MUST produce at least one matplotlib figure (the graphic).
- MUST run headless on CPU in seconds: tiny models (small nets, few epochs), dataset SUBSETS, set a seed. <if numpy-only: do NOT import torch>.
- ASCII only in any print()/string (Windows cp1252).
- Use only deps declared in the repo pyproject.toml (numpy, matplotlib, scikit-learn, torch CPU, torchvision). Datasets download under ./data (gitignored).

SELF-VALIDATE (required — do not reply until green):
  uv run --project <APPLIED-LEARNING-ROOT> jupyter nbconvert --to notebook --execute --inplace "<ABS-PATH-TO-NB>"
Run it. If it errors, fix the notebook and re-run until exit 0. Execution embeds the figures into the committed file.

Reply: "Wrote + executed <NN>-<slug>.ipynb (exit 0)" + wall-clock + any caveat. If you cannot get it green after reasonable effort, say so explicitly with the error — do NOT claim success.
```

### Example-script agent

```text
Write ONE standalone script at <ABS-PATH>/70-handson/examples/<name>.py — a minimal, self-contained, runnable distillation of the core idea of "<TOPIC>".

CONSTRAINTS: runs headless on CPU in seconds (tiny); ASCII-only print(); only declared deps; a top docstring saying what it does and how to run it (`uv run python <name>.py`). Validate by running it once (exit 0). Reply with the result.
```

## Constraints

- **Runnable code only** — no pseudocode in notebooks/examples. The execute-in-place gate is the proof.
- **No fabricated references.** Seed the seminal-papers agent with a vetted list; instruct author+year over uncertain ids.
- **Tiny + fast** — everything runs headless on CPU in seconds, or it doesn't ship.
- **70/20/10 layout** — always the numeric-prefix folders.
- **Ground seed-ideas in real projects** — read their CLAUDE.md; generic "you could use this for X" is the failure mode.
- **No emojis. Terse reference tone.**

## Limitations

- Dispatching all agents in one mega-message has hit 529 cascades — wave them (~6-10).
- Notebook agents that can't reach exit 0 must say so, not fake success — the orchestrator re-checks with `scripts/run_all_notebooks.sh`.
- Skipping the grounding step produces generic blog-post content and hand-wavy seed ideas.
- torch install must be done (`uv sync`) before notebook agents run, or every execute fails.
- Pre-fetch any SHARED dataset once (e.g. `torchvision.datasets.MNIST(...download=True)`) BEFORE dispatching notebook agents — concurrent first-downloads to the same dir race and corrupt. Point notebooks at a single repo-root `data/` dir (walk up to `pyproject.toml`), not a per-notebook copy.
