---
name: plan-trim
description: Investigate a project's current state, propose plan items to cut or fold together, and execute the trim once confirmed. Use when a plan has accumulated cruft, the user asks to "tighten the plan", "what can we cut", "what's still relevant", or after a phase ships and the surrounding plan has drifted. Companion to user-pm (read-only snapshot); plan-trim writes.
---

# plan-trim

Investigate, propose cuts, confirm, then execute. Be terse. Don't ask clarifying questions before the proposal — investigate first.

## Phase 1: Investigate

Read primary sources, not just the plan index. The cuts only land if you can name the unexamined assumption inside each phase doc.

1. **Plan index.** Read `documentation/plan.md` (or `plan.md` / `README.md`). Note the status table and doc map.
2. **Recent git activity.** `git log --oneline -30`. Note the most recent shipped milestone — its scope often subsumes pending plan items.
3. **Open phase docs.** Read every phase doc not ✅ DONE or ARCHIVED. Hunt for: calendar gates, sub-goals met by another phase, de-facto-exercised UAT, dead cross-refs.
4. **Run-doc archive.** `ls documentation/runs/` (or equivalent). UAT pass docs are evidence ceremonial gates can close.
5. **Cross-reference grep.** For each doc you suspect is dead, `grep -r <doc-name>` — the result tells you whether deletion is safe or needs redirects first.

## Phase 2: Propose cuts

Output a single bulleted list. Each item names the **unexamined assumption** and **why it might not hold**, not just the item to cut. A cut without an assumption named is a guess; a user can't validate a guess.

- **Calendar gates that are vibes.** "≥N months of X before Y" — is N load-bearing or a round number? Replace with the real prereq (data volume, schema, capability).
- **Sub-goals shipped elsewhere.** A phase scoped A+B+C may have had B shipped under another phase. Split it; mark the overlap SUPERSEDED.
- **Ceremonial UAT gates.** A formal gate whose happy paths get exercised every operator session for months. Example: "Phase X UAT exercised in `runs/2026-04-15-soak.md` + `runs/2026-05-02-soak.md`". Edge cases unique to the script become optional checks.
- **Phases closed by adjacent work.** A planned UAT/operator-doc step de-facto completed during another phase's run — close it with a pointer to the run-doc.
- **Dead doc-map entries.** Archived plans should drop out of the navigation table; archive is for diffing, not browsing.
- **Stale eval/test scaffolds.** Fixtures or rubrics unrefreshed in N commits. Commit to a cadence or retire the prose (data + code stay).
- **Preemptive hardening phases.** "Phase X hardening" with no named failure mode. If you can't point to a real bug, drop the phase; let real failures motivate real work.
- **Duplicate documentation.** Doc that says "the canonical X is at `<code path>`" is by its own admission redundant. Promote the code, retire the doc.

Aim for 3–8 candidates per pass. Each one must be specific enough that the user can say "yes" or "no" without a follow-up question.

## Phase 3: Confirm

Stop. Show the candidate list to the user. Wait for explicit go-ahead — even when the answer is obvious, the user owns the plan.

Acceptable signals: "do all of these", "yes", "go ahead", "do 1, 2, 4". Anything else is a clarification.

## Phase 4: Execute

Apply the agreed cuts. Order matters — index/status first so the doc map is coherent before you start retiring individual files.

1. **Update the status table + doc map** in `plan.md`. Mark phases RETIRED / SUPERSEDED / ✅ COMPLETE with a one-line "why" pointing at evidence (commit, run-doc, adjacent phase).
2. **Add header notes to retired phase docs** — header + keep body is the DEFAULT for retirements; `git rm` is only for fully-duplicative content (step 5). The header explains the retirement reasoning so a future audit can reconstruct the call.
3. **For superseded sub-steps inside an active phase**, change the status line to SUPERSEDED with a date and pointer; preserve the original problem text as "Original (pre-supersede)".
4. **Update cross-references before deleting files.** Grep for the doc name, redirect each live reference to its new canonical home. Skip refs in closed-phase docs and `archive/` (frozen).
5. **Delete docs only when their content is duplicative or genuinely dead.** Use `git rm` so the deletion is staged. If the doc has unique narrative, fold it into the new canonical home.
6. **Don't touch code unless the cross-ref redirect requires it.** Comment refs like `// see foo.md` get updated; behavior doesn't.

## Execution rules

- **Preserve context, don't just delete.** Future you needs to know *why*. Header note + evidence pointer beats a clean delete.
- **Calendar gates retire to data gates, not to nothing.** Removing the prereq entirely is wrong; the prereq's *form* is what's wrong.
- **Active vs closed phase docs.** Closed docs (shipped) are historical — don't edit their cross-refs. Active docs get the redirect treatment.
- **Code references over doc references.** When a doc and a code module say the same thing, the code is canonical. Update the doc, not vice versa.
- **One commit per trim pass** is fine; the diff tells the story. Don't fragment retirement edits into separate commits.

## Companion skill

Use [user-pm](../user-pm/SKILL.md) first if you just want the read-only snapshot with cut suggestions in the response. plan-trim is when the user wants the cuts *applied*.
