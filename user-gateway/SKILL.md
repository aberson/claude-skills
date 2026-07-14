---
name: user-gateway
description: "Pre-work intake gateway — CONVERTS an operator vent into routed, ledger-backed work; it never proposes work of its own. Invoke when the operator dumps everything on their mind about a topic ('here's everything on my mind about X'), says a project 'doesn't feel right', wants rough observations made concrete ('take my rough observations and make them concrete'), or is venting half-formed worries. Runs a listening pass (gaps -> 3-5 targeted questions, ONE round max, never block), lands every voiced fragment as an intake-ledger row routed by consulting the routing web, emits a ready-to-paste seed per row, and closes with the ledger path + canonical /goal + QUICK COPY. Wanting IDEAS is /goblin-suggest's job; refining ONE prompt/goal is /user-draft's. Invoke as '/user-gateway <topic> <free-text vent>' (the vent may also follow in conversation)."
user-invocable: true
---

# user-gateway

A THIN converter for the pre-work moment. The operator has a head full of half-formed
observations about a topic — some broken things, some worries, some wishes, an undecided
question — and wants them made concrete without anything getting lost or invented. This
skill composes three existing contracts and owns NO routing table and NO ledger grammar
of its own:

- **Routing** — [`_shared/skill-pipeline.md`](../_shared/skill-pipeline.md)
  (the routing web) is the ONE owner of the rails, their entry conditions, the tiebreak
  rule, the re-route edges, and the re-route contract. The gateway CONSULTS it per
  fragment and cites it in output; per the web's own intro, no skill hardcodes its own
  routing table — reproducing the web's rail/entry-condition table in this file or in
  gateway output (verbatim or paraphrased) is a DEFECT.
- **Ledger** — [`_shared/intake-engine.md`](../_shared/intake-engine.md)
  owns the ledger path formula + topic-slug rule (§1 — which itself reuses the
  shakedown-engine §1 slug rule by cross-reference), the row grammar + `F<N>` ids +
  status vocabulary + one-line disposition rule (§2), the zero-open check + canonical
  `/goal` string (§3), and idempotent seeding (§4). Cite it; never restate it.
- **Listening** — [`../user-draft/SKILL.md`](../user-draft/SKILL.md) Step 2 + Principles
  own the discipline: find the gaps, ask 3-5 targeted questions in at most ONE round,
  never block.

**Pinned posture: CONVERT, DON'T PROPOSE.** Every ledger row and every seed traces to a
fragment the operator voiced (or to their answer to a clarifying question). The gateway
never invents work the operator didn't voice — generating improvement ideas is
`/goblin-suggest`'s job, and the boundary is hard: an
unprompted suggestion in gateway output ("while we're in there…", "you should also…") is
a DEFECT, not a bonus.

---

## When to use / when NOT to use

**Use** when the operator opens the intake valve: "here's everything on my mind about X",
"this project doesn't feel right", "take my rough observations and make them concrete",
or an unstructured vent about a topic.

**Do NOT use:**

- **A single, already-clear fragment** → go straight to its rail (one broken thing →
  `/user-debug`; one capability wish → `/plan-feature`; …). The gateway earns its
  overhead only when fragments are plural or tangled.
- **Wanting IDEAS** ("what should I improve?") → `/goblin-suggest`. The gateway converts
  what was said; it does not generate what wasn't.
- **Refining ONE prompt or goal** → `/user-draft`.

---

## Steps

### Step 0 — take topic + vent

Inputs: a **topic** and the **free-text vent**. Compute the topic slug per intake-engine
§1 (its cross-reference chain to shakedown-engine §1 owns the rule — never restate it).
No topic given → derive one from the vent's dominant subject and say so in the opening
line. **No vent given → ask for it.** That single ask is the skill's missing input, not
a block — the never-block rule (Step 1) governs refine questions, not the vent itself.

### Step 1 — listening pass (user-draft's discipline, cited)

Per user-draft Step 2: split the vent into its distinct fragments (echo the split so the
operator can correct it), find the gaps that would change a route or a seed, then ask
**3-5 targeted questions in ONE round max** — zero when the vent is already clear (say
so). **Never block:** when answers don't come, or only some do, proceed with what's there
and mark each assumption inline in the affected row/seed. No second round, ever.

Only ask questions that change the outcome: a repro-vs-distrust split, a constraint a
seed needs, which document a cruft-smell is about. Never ask for more work items — see
the pinned posture.

### Step 2 — one ledger row per fragment

Seed the ledger per intake-engine (path + slug: §1; load-before-derive idempotence: §4 —
an existing ledger for this topic is LOADED and appended, new rows continuing the `F<N>`
sequence). Every fragment from Step 1 becomes exactly one row (§2 grammar; one-line
disposition).

Choose each row's route by CONSULTING the routing web — read its rails and entry
conditions, apply its tiebreak rule. Cite it in the output; do not reproduce its table.
Rows flip `open` → `routed` (or `parked`) as Step 3 dispatches them; **no row stays
`open` at close** — a fragment the gateway cannot safely route parks with the routing
question stated (that is an operator-only call), never a "will route later" leftover.

### Step 3 — per-row ready-to-paste seed

Each routed row gets a seed the operator can paste unchanged. Seed shapes by rail (this
is the gateway's OUTPUT contract — which rail a fragment belongs on stays the web's
call):

- **bug** → one complete `/user-debug --symptom '<one-line symptom>'` line (plus the
  repro when one was voiced).
- **plan** → the FULL `/plan-feature` seed paragraph in the gateway output (problem +
  voiced constraints, scope strictly as voiced); the ledger disposition keeps only the
  one-line form (intake-engine §2 owns that rule — the ledger never holds paragraphs).
- **investigate** → external/multi-source: a deep-research charter dispatched via
  `/deep-research` (adapt to your workspace's dispatch convention); codebase-local: a scoped Explore-agent framing
  (what to sweep, what a finding looks like).
- **verify** → the applicable invocation among the verify rail's four modes —
  `/review-uat` / `/user-uat` / `/user-shakedown` / `/user-walkthrough` — chosen per the
  web's verify-rail detail section.
- **trim** → a `/plan-trim` invocation naming the plan document. (Cruft-smell that is
  NOT about a plan document is not trim's — the web's trim note routes it
  investigate-first.)
- **do** → the two-step pair matching the do rail's real mechanics: `1.` a
  `/goblin-suggest --small <project>` line (persists the atom — the voiced task text
  guides which atom to pick, or confirms it appears), then `2.` a
  `/goblin-do <matching atom id or fuzzy text>` line. `/goblin-do` resolves persisted
  atoms only — a bare `/goblin-do` on a freshly-voiced task fails to resolve.
- **draft** → a `/user-draft <the operator's rough thoughts>` line.
- **decide** → NOT a seed: the row parks with the open question stated verbatim in its
  disposition. Never answer it, never pick a side, never convert it into work — parked
  rows wait for the operator (intake-engine §2/§3 own parked semantics; deciding is the
  one thing the gateway must never do for them).

### Step 4 — closing block

Three elements, always:

1. **Ledger path** — absolute, per the intake-engine §1 formula.
2. **The canonical `/goal` line** for this topic slug — the string is defined ONCE in
   intake-engine §3; emit it exactly, never author a variant. (Arming it is the
   operator's choice.)
3. **QUICK COPY** — every routed row's seed, one paste-able line each (the plan rail's
   line invokes `/plan-feature` with a compact form, the full paragraph staying above;
   the do rail contributes its two-step pair as two lines). Parked rows are questions,
   not seeds — they appear above with their open question, never in QUICK COPY.

---

## After the gateway

Rows may later re-route: a rail skill that discovers wrong-rail work mid-run follows the
web's re-route contract and writes back to this ledger per intake-engine §5. The gateway
plays no part in that — it ends at the closing block.

---

## Maintenance

The `evals/` suite targets THIS gateway contract (created 2026-07-13, #313): **10 assertions** across **3 categories** in `evals/evals.json` (passing threshold
**8/10**), **2 scenarios** in `evals/test_scenarios.json` (one multi-rail vent, one clear
three-fragment vent), and a golden corpus of **2 goods + 10 single-defect bads** under
`evals/golden/` (manifest.json maps each bad to the one assertion it trips). Any edit
that changes an output contract here (listening pass, ledger seeding, seed shapes,
closing block) must update the affected assertions and goldens in the same diff, keeping
this footer's numbers equal to `evals.json`'s. The rails + entry conditions + tiebreak +
re-route contract stay owned by `skill-pipeline.md`, and the ledger grammar + statuses +
zero-open check + canonical `/goal` stay owned by `intake-engine.md` — when either
changes, re-check the citation-consistency assertions here instead of duplicating the
contract.
