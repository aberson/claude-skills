---
name: user-brainstorm
description: Brainstorm and investigate a topic end-to-end. Seeds 10 starter topics, gap-fills through 2-4 "what's missing?" rounds with the user, tiers by importance, then dispatches one background sub-agent per topic to write a templated reference file. Produces a navigable doc set under `docs/investigations/<topic>/` with a tier-organized README index. Use when the user wants to ideate comprehensively on a subject, build a reference catalog of considerations, or convert an open-ended question into a structured doc set. Invoke as "/user-brainstorm <topic>".
---

# user-brainstorm

Help the user explore and document an arbitrary topic — engineering pattern, architectural concern, product question, design space — by producing a tiered reference set.

The activity has two phases: **interactive ideation** (seed → gap-fill → tier, with the user in the loop) and **parallel investigation** (one background sub-agent per topic writes a templated reference file). The output is a self-contained, navigable doc set the user can grep later.

## When to use

- User wants to ideate comprehensively on a topic.
- User asks "what are the considerations for X" or similar open-ended exploration.
- User wants a reference doc set produced from a back-and-forth, not a one-shot answer.
- After running, the user has a folder of cross-referenced investigations they can refer back to.

## When NOT to use

- Single specific question with a single specific answer — just answer it.
- Topic is already covered by an existing doc set — point at that instead.
- Topic is too narrow (one concern, not a space of concerns).

## Steps

### 1. Get the topic

Required argument. If not provided, ask: "What topic do you want to brainstorm?" Derive a kebab-case slug from the topic. Confirm the output path with the user (default: `docs/investigations/<slug>/` relative to CWD).

### 2. Seed 10 topics

Generate **exactly 10** topics related to the subject. Each is a short noun phrase (3-8 words) describing a concern, pattern, failure mode, or design decision. Output as a numbered list. No commentary — let the user react.

### 3. Gap-fill loop

Ask the user: "Are there any topics not mentioned that are really important?" Take any user additions verbatim, then add 5-10 more topics that the user's additions imply or that round out coverage. Re-present the running list (or just the additions) and repeat the question.

Stop when:
- User says no new topics surface, or
- The next round produces only low-value / redundant additions.

Typical: **3-4 rounds total** (1 seed + 2-3 gap-fills). Do not loop indefinitely. If after round 3 the user is still adding meaningful topics, the topic was probably wider than expected — say so and ask whether to keep going or split into sub-topics.

### 4. Aggregate + tier

Combine all surfaced topics into one list. De-duplicate. Then organize into four tiers:

- **Tier 1 — Load-bearing.** Foundational; the system / approach breaks without these. Often includes a meta-principle that several other Tier 1 topics are special cases of.
- **Tier 2 — High-leverage.** Shape outcomes significantly. Calibration, integration, scope decisions.
- **Tier 3 — Optimization.** Matter at scale or in edge cases. Cost discipline, specialized lenses, performance refinements.
- **Tier 4 — Hygiene.** Worth doing but rarely the bottleneck. Long-term system health, polish.

Present the tiered list to the user and ask: "Tiering look right? Any topics to move, merge, or cut?" Adjust based on response.

### 5. Confirm structure

Before writing anything, show the user:
- The output path (e.g., `docs/investigations/<slug>/`).
- The file structure that will be created (see "Output layout" below).
- The total number of investigation files (one per surfaced topic).
- Approximate per-file size (350-600 words).

Ask: "Proceed?" Wait for explicit confirmation before any file write.

### 6. Write meta files

Write two meta files into the output directory before dispatching agents:

- **`topics.md`** — flat list of all topics, tier-organized, each line a markdown link to the eventual investigation file (`NN-<slug>.md`). Brief provenance note at top (how many rounds, how the set was assembled).
- **`plan.md`** — investigation methodology. Goal, scope, common template (verbatim), execution model (sub-agent-per-file dispatch), output structure, done criteria.

### 7. Dispatch sub-agents

One background sub-agent per investigation file. Each agent is briefed with:

- File path to write (`docs/investigations/<slug>/NN-<topic-slug>.md`).
- Topic title and tier.
- Workspace context files to read for grounding (see "Per-agent grounding" below).
- Topic-specific bullets (the angle, related workspace incidents, key references the agent should weave in — gathered during the ideation phase).
- Likely cross-references (slugs of related sibling investigations).
- The investigation file template (verbatim — see below).
- Constraints (length, tone, no invented references).

**Dispatch in waves of ~10-12 background agents per message.** A single mega-message dispatching all agents has been observed to trigger `529 Overloaded` cascades; waves keep concurrent load manageable. Use `run_in_background: true` so completions arrive as task-notifications.

If any agent fails (529, timeout, refusal), retry that single file in a fresh sub-agent dispatch.

### 8. Write README

After all agents have completed, glob the output directory to confirm every `NN-<slug>.md` exists. Then write `README.md`:

- Intro paragraph stating the topic and scope.
- Tier-organized list of links to each investigation file with a one-line hook per topic.
- Provenance section (how many rounds, how many topics, dispatch pattern).
- "See also" pointers to any workspace rules, memories, or skills the agents commonly referenced.

End the activity with a summary message to the user: total files written, location, any agents that needed retry, and what to do next (browse the README, grep for keywords).

## Output layout

```text
docs/investigations/<topic-slug>/
├── README.md           # tier-organized index, links to every file
├── topics.md           # flat list with tier headers
├── plan.md             # methodology that produced this set
└── NN-<slug>.md        # one per topic, numbered 01..NN
```

## Investigation file template

Every investigation file uses this exact structure:

```markdown
# <Topic Title>

**Tier:** <1 | 2 | 3 | 4>
**Status:** Investigated
**Related:** [[other-slug]], [[other-slug]]

## What it is
<1–2 paragraphs. State the concept directly.>

## Why it matters
<Failure modes. Workspace incidents if applicable. What goes wrong without this.>

## When to apply
<Trigger conditions — bullet list when natural.>

## How to apply
<Concrete patterns, decisions, snippets, checklists.>

## References
<Pointers to actual files in the workspace. Only cite ones the agent verified by reading. Common shapes:
- Rule: `<file>.md § <section>` (relative path)
- Memory: `<memory-file>.md`
- Skill: `<skill-name>`
- Incident: <project> <phase or step>>

## Open questions
<What's not settled. What to investigate further.>
```

## Per-agent grounding

Each sub-agent's prompt instructs it to read (whatever exists in the workspace):

- Project root `CLAUDE.md` if present.
- Rule files under `.claude/rules/*.md` if the project has them.
- Workspace memory index (typically at `~/.claude/projects/<workspace-id>/memory/MEMORY.md`) and any `feedback_*.md` / `project_*.md` files it points to that look topic-relevant.
- `SKILL.md` files under `.claude/skills/<name>/` for skills clearly relevant to the topic.
- The `topics.md` file in the output directory (for the canonical cross-reference slug list).

Agents must only cite files they actually verified by reading. Inventing references defeats the point.

## Sub-agent prompt template

The orchestrator constructs each agent's prompt by filling this template:

```text
Write ONE markdown file at <ABSOLUTE-PATH>/<NN>-<SLUG>.md.

Topic: "<TITLE>" (Tier <N>). One of <TOTAL> reference files about <SUBJECT>.

READ for grounding (don't invent references):
- <list of workspace files relevant to the topic, per "Per-agent grounding">

TOPIC CONTEXT (build on these — don't regurgitate):
- <3-5 bullets surfaced during the ideation phase: the angle, workspace incidents that anchor the topic, key memories/rules to weave in>

LIKELY CROSS-REFERENCES: [[other-slug]], [[other-slug]], ...

TEMPLATE (exact structure):
<verbatim template from above>

CONSTRAINTS:
- 350-600 words.
- No emojis.
- Reference tone — terse, factual.
- Markdown links use relative paths from the file's location.
- Cross-references via [[slug]].
- No padding. Honest-line is fine ("No prior incident in this workspace; pattern recommended on first-principles grounds").
- No invented references.

Write the file with the Write tool. Reply: "Wrote <NN>-<SLUG>.md" plus any notes.
```

Topic-specific bullets come from the ideation phase: as the user surfaces topics and reacts, note any workspace incidents, related rules, or angles they mention. These become the per-topic grounding for the relevant agent.

## Constraints

- **350-600 words per investigation.** Concrete beats comprehensive.
- **No emojis.**
- **Reference tone** — terse, factual, written to be grepped later.
- **Cross-references via `[[slug]]`** — slug = the file's `<slug>` part (without the `NN-` prefix or `.md` extension).
- **No padding.** A section with nothing real says one honest line, not a paragraph of filler.
- **No invented references.** Agents only cite files they verified by reading.
- **No naming specific other skills or projects** unless the topic is explicitly about them. The skill itself is topic-agnostic; the investigation set produced should be.

## Limitations

- **Dispatching all agents in one mega-message.** Hit a 529 cascade once. Wave them in batches of ~10-12.
- **Skipping the tier confirmation.** Tiering decisions shape the README's organization and the user's mental model. Always confirm before writing.
- **Letting gap-fill loop forever.** Cap at 4 rounds. If the user keeps adding meaningful topics past that, the subject is too broad — surface this and ask to split.
- **Writing meta files before tier confirmation.** Cheap to revise verbally, expensive to revise after files exist.
- **Producing generic content because the agents weren't grounded.** Per-agent bullets and workspace context reads are what make the output useful. Skipping them produces hand-wavy reference docs that read like generic blog posts.

## End-of-activity report

Final message to the user includes:
- Output directory path.
- File count produced (and any that needed retry).
- Total topics by tier (e.g., "9 Tier 1, 12 Tier 2, 11 Tier 3, 3 Tier 4").
- Any notes the agents flagged in their completion replies (e.g., "agent 14 noted an existing inconsistency in <rule>; worth a follow-up").
- One suggested next action — usually "browse the README" or "grep for <topic-keyword>".

Keep it short. Two or three sentences plus the file count.
