---
name: review-memories
description: Post-mortem-style review of recent feedback memories. Pick 3-5, walk through them one at a time asking "did I get this right? what's the next layer?", then surface latent principles that several memories point at but none articulate. Use when memories feel stale, when the same correction keeps recurring, or periodically to consolidate. Works from concrete recent evidence — not vibes.
user-invocable: true
---

# Review Memories

Goal: surface **latent principles** — patterns two or three memories point at
but none articulates alone. Requires re-reading specific recent feedback.

## When to use

- Periodic check-in (every ~10-20 sessions, or when the user asks)
- After a session where the user gave several corrections — the new feedback may
  rhyme with older feedback in a way worth naming
- When the same correction keeps recurring despite a memory existing for it
  (the memory may be capturing the symptom, not the cause)
- When memories feel cluttered or contradictory and need consolidation

## When NOT to use

- During active work on a task — this is reflective, not action-oriented
- Right after writing a memory — give it a few sessions to prove out first
- For `user`/`project`/`reference` types — those are facts, not patterns. This skill
  is specifically for `feedback`, where the "next layer" question is meaningful.

---

## Flow

### Step 1 — Locate the memory directory

Memory lives at a project-scoped path, e.g.
`~\.claude\projects\<slug>\memory\`. Read `MEMORY.md` to get the
ordered index, then `ls` the directory to confirm what's actually on disk.

If `MEMORY.md` and the file list disagree (orphan files, dead pointers), flag
that to the user before continuing — it's a separate problem to fix first.

### Step 2 — Select 3-5 feedback memories

Default: the **most recent feedback memories** by file mtime, capped at 5. Show
them as a numbered list with their one-line descriptions. Ask the user:

> Want me to walk through these 5, or swap any out? (e.g. "skip 3, add the
> attack-walking one")

Don't include `user`, `project`, or `reference` memories unless the user
explicitly asks — those don't have a "next layer" in the same way.

If a memory has fired recently in the current or prior session, prefer it —
fresh evidence beats stale evidence.

### Step 2.5 — Lineup theme scan (before any per-round work)

After the user confirms the lineup, **read all selected memory files
back-to-back** before writing the first round. Write a brief upfront
scan that names:

- Apparent thematic clusters (which memories may share a shape, even
  loosely)
- Memories that look isolated relative to the rest of the lineup
- Any memory pair that's so obviously linked it should be co-reviewed
  in a single round rather than as separate rounds

Why this matters: going strictly memory-by-memory makes it easy to
lock onto the first cluster you spot and miss other themes. A thematic
upfront scan surfaces candidates the per-round flow can build toward,
and it can rescue Round-5-feels-marginal situations where the memory
actually fits a pattern you'd already named.

Output the scan as a short bulleted list — not exhaustive, just the
themes that jump out. The user can confirm, push back, or add themes
before Step 3 starts. Keep proposed clusters honest: 2-3 specific
shared-shape memories beats vague gestures at "these all feel related."
When the third bullet fires, run one round covering both memories; cite both in section 1.

### Step 3 — Walk through one at a time

For each selected memory, do **one round at a time** (don't dump all 5 at once).
The user shouldn't have to do the analytical work — give them a structured
output with an honest recommendation they can approve, modify, or reject.

Each round outputs **all seven sections in order**, in this format:

#### 1. Memory under review
The file name, the rule (one sentence), the captured `**Why:**`, and the
captured `**How to apply:**`. Quote, don't paraphrase.

#### 2. Why we're reviewing it
Why this specific memory is in the lineup right now — what evidence,
tension, or pattern placed it here. If it was selected by recency only,
say that.

#### 3. Recent evidence
A specific moment in the current/recent session where this memory applied,
should have applied, or fired correctly. If you can't find one, say
"I don't have recent evidence — the memory may be dormant" and label the
round accordingly.

#### 4. Candidate change
**Draft a specific concrete modification — every round, no exceptions.**
Not a question, a proposal. Pick the most promising shape:

- A new clause to add to this memory (quote the exact text)
- A refined trigger condition or scope
- A sibling memory worth writing (draft the rule + why in one line each)
- A consolidation or deletion of redundant memories
- A counter-rule or exception worth naming

If after honest effort the best candidate is genuinely "do nothing" —
draft it anyway as the *next-best* alternative. Section 6 will defeat
or accept it through the checklist. "No change" is allowed as an
*outcome*; it is never allowed as a *starting position*.

Also state: which sibling memories (if any) does this candidate connect
to? Latent principles surface here in section 4 — do **not** defer them
to Step 4. If two memories in the lineup point at a shared principle,
draft the shared-principle memory body now (rule, why with sibling
citations, how to apply) — Step 4 becomes ratification, not first mention.

#### 5. My analysis
Don't punt to the user. Answer the section-4 candidate honestly: is it
worth doing, what's the case for it, what's the case against, what's
your honest verdict? State your read on whether this is adherence drift
vs. rule drift (see below). The user delegates the analytical heavy
lifting to you; they decide whether to accept the conclusions.

If the candidate from section 4 is a sibling-principle memory drawn
from this round + earlier rounds, write its proposed body here in full
(frontmatter + rule + **Why:** with sibling citations + **How to apply:**).
Step 4 of the overall flow will accept or reject the draft; this section
is where it gets written.

**Three failure categories.** State which one you suspect:
- (a) **Rule drift** — the rule itself is wrong/outdated → revise the
  rule.
- (b) **Adherence drift** — the rule is correct, you've quietly stopped
  following it → resume, do not revise.
- (c) **Body content rot** — the rule is correct and being followed,
  but the memory *body* contains stale claims, dangling action items,
  unresolved "we never confirmed X" speculations, or stale CLI/file
  paths that have aged out → resolve, escalate, or delete the rotted
  passage; leave the rule alone.

These look similar from the inside but need different fixes. Default
to (b) when the proposed change would make the rule easier on you.
Default to (c) when the rule reads fine but the body cites dates,
artifacts, or open questions older than ~2 weeks without resolution.

**Pick exactly one category — no hedging, no "none apply."** Even on a
dormant memory (Section 3 = no recent evidence) you must commit:
default to (c) if the body cites stale specifics, otherwise (b). The
diagnosis is required output — Section 6 check 3 depends on it.

#### 6. Recommendation (run through robustness checklist)
State a single concrete recommendation in one sentence — e.g. "Keep the
rule as written; the failure is adherence, not the rule." or "Add a new
clause: cite the *file path* in addition to the file name."

Then run it through this 5-item checklist and show pass/fail for each:

| # | Check | Pass criterion |
|---|---|---|
| 1 | **Performs better?** | Would this measurably improve LLM output, or only reduce effort/verbosity? Pass = improves output. |
| 2 | **Self-softening guard** | Does this make the rule easier on me? If yes, the burden of proof shifts to me to defend it — default-suspect. Pass = either not a softening, or has a defense that survives the performs-better check. |
| 3 | **Adherence vs. rule** | If the diagnosis is adherence drift, is the recommendation "resume" rather than "revise"? Pass = matches the diagnosis. |
| 4 | **Mechanism preserved** | Does the change preserve what made the rule work in the first place (externalization, forcing function, sequence)? Pass = mechanism intact or replaced with something equally load-bearing. |
| 5 | **Concrete enough to fire** | Would future-me actually trigger on this in a new session, or is it vague feel-good language ("be more careful", "remember to...")? Pass = has a specific trigger condition. |
| 6 | **Generates something new?** | Does this round produce a candidate (clause, sibling, refinement, deletion) the user couldn't have produced by reading the memory alone? If recommending "no change," is there a real opportunity drafted in section 4 that gets explicitly defeated here — and is that defeat principled, not reflexive? Pass = yes to one of those. **Default-fail** if there is no drafted alternative or the defeat is "well, no problem this session." |

If a recommendation fails any check, either revise it or report the
failure honestly and recommend the next-best alternative. A failed
checklist is more informative than a passed one with massaged answers
— never fudge the checks to push a recommendation through.

**"No change" is the outcome that triggers extra scrutiny, not the
default.** If you're recommending no change, item 6 MUST (a) name the
defeated alternative drafted in Section 4, and (b) enumerate the
specific numbered checklist items (1–5) it failed on, in the literal
form `failed check N because …` (and `check M because …` if more than
one) — citing at least one numbered check by digit. Free-form "why it
lost" prose, a single un-numbered defeat reason, or framings like "no
problem arose this session" / "nothing came up" do NOT satisfy check 6
and must be marked FAIL.

#### 7. Approval prompt
End with a single, explicit ask:

> **Approve / modify / reject?** (If modify, what would you change?)

Then **wait** for the user's answer before moving on. If they shrug or
accept as-is, fine — apply the recommendation in Step 5. If they push
back, fold their answer in and re-run from section 5.

### Step 4 — Look for latent principles

After all rounds, step back and ask:

> Across these N memories, do any 2-3 point at a shared principle that none of
> them articulates on its own?

Examples of what a latent principle looks like:
- Three memories about being too eager to act → latent: "default to confirming
  before acting on inferred intent."
- Two memories about citing sources + one about checking memory before acting
  → latent: "evidence-before-claim is the default; the cost of citing is lower
  than the cost of being wrong."

Propose at most 1-2 latent principles. **Only propose what the evidence
supports** — if nothing surfaces, say so. A clean review with no new principles
is a valid outcome; manufactured ones pollute the memory.

### Step 5 — Apply changes

For each agreed-on change, take the corresponding action:

- **New principle surfaced** → write a new feedback memory with `**Why:**`
  citing the 2-3 sibling memories that surfaced it (so future-you can trace it).
- **Memory was wrong / overcorrected** → update or delete the file; update
  `MEMORY.md` index.
- **Two memories should consolidate** → merge into one, delete the other,
  update the index.
- **Memory was right but the *why* was wrong** → keep the rule, rewrite the
  `**Why:**` line.
- **No change** → say so explicitly. Most rounds will land here; that's fine.

End with a one-line summary: `Reviewed N memories — wrote X, updated Y, deleted
Z, surfaced W new principles.`

---

## Principles

- **The user is the source of truth.** You surface candidates; they decide
  what's real.
- **Cite siblings when proposing a new principle** — a memory that names its
  sibling sources is more durable than one that appears decree-style.
- **Suspect yourself when the rule would get easier**
  (`feedback_llm_softening_bias.md`). The performs-better check is the
  disambiguator; surface the bias to the user when it fires.
