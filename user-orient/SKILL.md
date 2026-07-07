---
name: user-orient
description: Re-orient the user mid-session via a status snapshot (verified, not-verified, next steps) plus parallel asides. Use when the user asks "where are we", "what's the status", or "remind me what we were doing".
user-invocable: true
---

# User Re-Orientation

This skill produces a status snapshot for a user returning mid-session. Read-only by default; does not mutate memory, plans, or code.


---

## Steps

### Step 1: Run autonomous asides in parallel (BEFORE composing output)

Run all relevant tool calls in parallel in a single message. Do not output the findings yet — they feed Step 2. Pick the subset that fits the project:

- `git status --short` (working tree state)
- `git log --oneline origin/<main>..HEAD` (unpushed commits)
- `git log --oneline -5` (recent activity context)
- Tail (last 30 lines) of the most recently modified file in `logs/` if the project has one
- Read any current run-state JSON for active long-running processes this project tracks (e.g. `data/evolve_run_state.json` for Alpha4Gate)
- Read `MEMORY.md` from the project's auto-memory directory if not already in context

If a project has its own status conventions (e.g., a build-state file, a test-counts marker, a daemon health endpoint) and you know about them from earlier in the session, query those too.

Apply those findings to compose Step 2.

---

### Step 2: Compose the orientation

Write SIX sections in this fixed order: (1) Verified-working, (2) Not-yet-verified, (3) Manual checks, (4) Autonomous asides surfaced, (5) Near-term sequencing, (6) Most honest recommendation. Do NOT reorder — even when a Step 1 aside is dramatic (dead process, surprise origin commit), it stays in section 4. Leading with an aside breaks the reader's mental model. Skip any section that has nothing to report; do not promote it upward.

Default total target: ~250 words. If the session has > 4 hours of context or the user has been away > 24 hours, expand to ~600 words. If session has < 30 minutes of activity, output a compressed version (no headers, just the recommendation).

### 1. Verified-working

Write 3-7 bullets of concrete confirmations, each with citable evidence (commit SHA, `file:line`, log line, test count).

### 2. Not-yet-verified

Open assumptions the verified work depends on. Each item names the *risk* if the assumption is wrong. 1-4 bullets.

### 3. Manual checks (user can run in < 60s)

1-3 concrete USER commands that would convert "not verified" items to "verified". Skip this section if not-verified is empty or items can't be resolved user-side.

Write each as:
- **What to run:** exact command, copy-paste ready
- **What the answer tells us:** the specific signal we're looking for
- **Why it matters:** what LLM work it unblocks

Rank by impact (highest-leverage first). The criteria for inclusion: low cost (≤ 60s) and high LLM-unblock value.

### 4. Autonomous asides surfaced

If Step 1 turned up anything notable that the user might not know about (a new commit on origin, a process that died, a stale lock file), surface it briefly here. **OMIT this section entirely when Step 1 was unremarkable — do NOT include a placeholder like "nothing notable", "no findings", or "no new commits". Section absence IS the signal.**

### 5. Near-term sequencing

The next 2-5 concrete steps, each with rough effort estimate (e.g., "~30 min", "1-2 hr"). Distinguish user-side vs LLM-side steps when both are present.

### 6. Most honest recommendation

One paragraph. What to do RIGHT NOW. Why this over alternatives. If unsure between two paths, say so and explain the tradeoff.

---

## Constraints

- **READ-ONLY.** Do not write memory, edit files, commit, or push. FLAG stale memory or missing docs and offer a follow-up turn — do not auto-update.
- **Be specific.** "Things are mostly working" is useless. "The 8-hour soak from 23:10 PDT completed, 0 promotions, regression-rollback path exercised cleanly (commit ce8545f)" is useful.
- **Be honest about uncertainty.** Sections 2 and 3 carry the value. Do not minimize them to keep the output tidy.
- **Fresh session edge case.** If there is no prior work to orient on, respond with a brief "fresh session — what would you like to work on?" instead of empty sections.
- **Respect user-stated priorities.** Pull from `MEMORY.md` for project goals; don't propose actions that contradict known user preferences without flagging the conflict.

---

## Limitations

- Mid-debugging on a single thread; wants a quick working-memory refresh — use `user-recap` instead.
- Comprehensive handoff to a fresh context window — use `session-wrap`.
- Verify a document is self-contained — use `plan-wrap`.
