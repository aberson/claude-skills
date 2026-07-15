---
name: user-lavishify
description: Render the output you JUST sent to the screen as a Lavish annotatable HTML artifact for detailed, element-level review. Chat output stays the default; reach for this on demand when a just-delivered plan / comparison / diagram / table / long fix-list is easier to mark up by clicking elements than by quoting in chat. Invoke as "/user-lavishify [what to render]".
user-invocable: true
argument-hint: "[what to render — defaults to the last substantial output]"
---

# user-lavishify

Take the artifact-shaped content just delivered in this conversation and turn it into a **Lavish Editor** review surface: a self-contained HTML page opened in the operator's own browser, where they annotate elements / text ranges / Mermaid nodes and the feedback returns here structured. This is the **inverse** of building in Lavish from the start — normal delivery is plain chat; this escalates a specific output to Lavish only when spatial annotation beats typing.

`$ARGUMENTS`

If the argument is non-empty, render THAT (a named plan file, a section, "the comparison you just showed"). If empty, render the **last substantial assistant output** — a plan, comparison, table, diagram, report, or a list of proposed changes. If the last output was short or conversational, ask what to render instead of guessing.

## When to use vs. not

- **Use** when the just-delivered content is dense/structured and the operator would otherwise have to quote many things to fix — multi-step plans, option comparisons, diagrams, big tables, a long list of proposed edits, or a UI/design mock.
- **Don't** for short or conversational replies — chat is faster and zero context-switch (thinking-as-you-type is the default). Lavish costs a browser context-switch + artifact-authoring effort; only spend it when element-level annotation genuinely pays.

## Workflow

1. **Pick the content.** The last substantial output (or `$ARGUMENTS`). Keep the substance identical — this is a re-presentation, not a rewrite.
2. **Preflight.** Confirm `node --version` is ≥22. Every `lavish-axi` command in this skill MUST be prefixed with `LAVISH_AXI_TELEMETRY=0` (PowerShell: `$env:LAVISH_AXI_TELEMETRY='0';`). No global install — always `npx -y lavish-axi`.
3. **Consult playbooks.** Run `npx -y lavish-axi playbook <id>` for each matching type (`plan`, `comparison`, `diagram`, `table`, `code`, `input`, `slides`) and `npx -y lavish-axi design` for the DaisyUI+Tailwind CDN snippet, the Mermaid CDN snippet, and the copy-paste layout-safety CSS. Open every matching playbook before writing HTML.
4. **Author the artifact.** Write a self-contained HTML file to the session scratchpad under `.lavish/` (never into the repo tree). Design-system priority: (1) a look the operator named; (2) the *subject project's* design system if one exists; (3) the Lavish DaisyUI `luxury` fallback. Paste the layout-safety CSS. Use Mermaid for flow/architecture/dependency graphs, not hand-built div boxes. Prevent horizontal overflow at every nesting level.
5. **Open.** `npx -y lavish-axi <file>` — spawns the detached loopback server (127.0.0.1) and opens the operator's browser. Print the session URL.
6. **Poll (background).** `npx -y lavish-axi poll <file>` as a background task — it long-polls silently for annotations, queued prompts, and browser-reported `layout_warnings`; never kill it, and just re-run it if the harness kills it (queued feedback is never lost). Fix fresh error-severity `layout_warnings` and re-check before involving the operator; surface persistent/low-severity ones with a note.
7. **Loop.** Apply each element-pinned change to the artifact (the browser live-reloads), then `npx -y lavish-axi poll <file> --agent-reply "<message>"` to reply in the browser and keep waiting. Repeat until the operator ends the session.
8. **End + PROPAGATE.** On end, run `npx -y lavish-axi end <file>` then `npx -y lavish-axi stop`. Then do the step the loop does NOT do for you: **propagate the decisions back to the real source of truth** — the plan doc, the issues, the code — because the annotations landed on a throwaway artifact, not on canonical state. Grep every downstream consumer of a changed decision before claiming it's done, and file/​comment issues for any real delta. Summarize what changed and where.

## Guardrails (workspace-specific, non-negotiable)

- **Telemetry off** on every command (`LAVISH_AXI_TELEMETRY=0`) — the published CLI is opt-out and phones home to a third-party analytics host otherwise.
- **Loopback only** — never set `LAVISH_AXI_HOST` to a wildcard (`0.0.0.0`/`::`); the server is unauthenticated and would serve local files to the LAN.
- **Never run `lavish-axi share`** — it publishes the artifact to a third-party host (`ht-ml.app`), public by default. This is an outward egress action; do not invoke it, even if it looks convenient.
- **Never run `lavish-axi setup hooks`** — it writes SessionStart hooks into agent config dirs, bypassing this workspace's `update-config`-managed hooks and junction-based skills.
- **Artifacts live in the scratchpad**, never committed to a project tree.
- **Poll runs in the background** (the harness limits foreground command duration).
- **Windows note:** consumed via `npx -y` (Node ≥22, no install). The CLI's port self-heal is POSIX-only, so if port 4387 is stuck, set `LAVISH_AXI_PORT` or `npx -y lavish-axi stop` — don't expect it to reclaim the port itself.

## Notes

- lavish-axi is a third-party tool (register `--not-owned` if ever formalized in the observatory registry). It is invoked on demand via `npx`; nothing is installed into any project.
- The value is *spatial* feedback (click the wrong cell, select the wrong phrase, mark a Mermaid node). If the operator's feedback is naturally textual, staying in chat is the better call — say so rather than forcing the artifact.
