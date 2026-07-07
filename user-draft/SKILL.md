---
name: user-draft
description: "Refine rough thoughts into a polished, ready-to-use artifact — either an improved prompt or a copy-pasteable /goal \"<condition>\". NL-detects which you want, runs a gaps→questions→polish pass, and checkpoints current state (task-handoff --loop) so a window pivot loses nothing. Invoke as /user-draft <your rough thoughts>."
user-invocable: true
---

# user-draft

Turn a rough idea into a finished artifact you can use immediately:

- **prompt** — a precise prompt/instruction for a model or agent
- **goal** — a copy-pasteable `/goal "<condition>"` that keeps a session working until a checkable condition is met

One NL front door for both. `user-draft` figures out which you want, refines it through the same
discipline, and emits an artifact that self-orients the window you paste it into.

Deeper, eval-backed prompt-only audit lives in `/review-prompt`. `user-draft` is the fast everyday
front door; reach for `/review-prompt` when you want an exhaustive prompt critique.

---

## Step 0 — detect intent (goal vs prompt)

Read the user's free-text thoughts and classify:

| Signal | → branch |
|---|---|
| "write/make a goal", "set a goal", "keep working until", "don't stop until", "objective", "until X is done", "/goal" | **GOAL** |
| "write/refine a prompt", "improve this", "make this clearer", "task for an agent", "ask the model to", "instruction" | **PROMPT** |

If no explicit keyword: classify by **what the thought describes**.
- Describes *what "done" looks like* (a stopping/completion state) → **GOAL**
- Describes *what to do* (an instruction/task) → **PROMPT**

If still genuinely ambiguous, ask exactly one disambiguating question — never guess silently,
never ask more than one. Then proceed.

Emit a one-line notice: `user-draft: detected GOAL` / `user-draft: detected PROMPT` so the user can correct.

---

## Step 1 — checkpoint current state (cheap, gated)

The artifact you're about to produce may be pasted into a fresh window, where a stale
`current.md` would mis-orient it. So freshen it **first** — but only when there's real state
to preserve:

- **If** `<git-root>/.claude/task-state/current.md` exists and represents active in-flight work
  → invoke `task-handoff --loop` (Skill tool). ~5s, local commit, **no push**.
- **Else** (fresh session, no active task, or nothing changed since last checkpoint)
  → skip silently. Do not write or commit a checkpoint for a clean slate.

This is the "do proper task-handoff activities before starting work" step. It is the only
thing that makes the baked preamble (Step 4) non-hollow — without a fresh checkpoint the
preamble points at stale state.

---

## Step 2 — refine (shared flow)

Both branches run the same pass:

1. **Find the gaps.** Ambiguities, missing constraints (format, scope, audience, edge cases),
   assumed context, contradictions, weak verbs ("handle", "process", "deal with").
2. **Ask targeted questions.** 3–5 focused questions, only the ones that meaningfully change the
   output. Skip entirely if the input is already clear. Do not ask obvious questions.
3. **Polish** per the branch below, after the user answers (or directly if no questions needed).

Preserve the user's voice and intent — refine, don't rewrite into a template.

---

## Step 3a — PROMPT branch

Produce the improved prompt with:

- **Concrete verbs** replacing vague ones ("return" not "handle", "reject" not "deal with")
- **Explicit constraints** filled in from the answers (format, scope, audience)
- **Scope boundary** — what's in and out, stated explicitly
- **One literal example pair** — an actual input → actual output, not a description of one
- **Negative examples** where they prevent a known failure mode ("do NOT …")

Return the prompt in a fenced code block (see Step 4 for the preamble). Follow it with a 2–4 line
`## Changes` summary of what you tightened and why.

## Step 3b — GOAL branch

Produce a `/goal "<condition>"` where the **condition is a good stop criterion**:

- **Binary and checkable every turn** by a fast model with tool access.
- **Names concrete artifacts/criteria** — "tests green", "PR #N merged", "file X exists",
  "count == N", "`<cmd>` exits 0". Not "the bot is better" or "code is clean" (unmeasurable →
  the goal never resolves).
- **Carries guardrails** if the work needs them ("…without touching the public API").

Reject your own first draft if the condition isn't externally verifiable — rewrite until it is.
Return it in a copy block (see Step 4), then a one-line note on *how the harness will check it*.

---

## Step 4 — bake a self-orienting preamble (gated)

Make the artifact orient whatever window it lands in — **only if** Step 1 actually checkpointed
active state. For a clean-slate draft, emit the bare artifact with no preamble (never tell a
fresh window to read a `current.md` that doesn't apply).

**PROMPT branch** — prepend one line inside the block:

```text
Orient first: run /task-handoff --resume (reads .claude/task-state/current.md), then:

<the refined prompt>
```

**GOAL branch** — emit the resume line as a separate command *above* the goal (a slash command
can't carry a prose preamble), so the user runs them in order:

```text
/task-handoff --resume
/goal "<condition>"
```

For same-window use the resume line is harmless to skip — note that inline.

---

## Principles

- **Shorter is better.** Every line of the artifact earns its place.
- **Specificity over generality.** "return a JSON array" beats "return structured results";
  "tests green and PR #196 merged" beats "the feature is done".
- **Show, don't tell.** A literal example beats a description of one.
- **One artifact, one job.** If the input bundles several asks, say so and offer to split.
- **Never block.** At most one disambiguation question (Step 0) or one round of refine questions
  (Step 2). Otherwise make the best call and note it inline.
