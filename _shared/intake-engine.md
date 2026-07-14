# Intake engine — the shared intake-ledger contract

Single source of truth for the **intake ledger**: the status table that `/user-gateway` seeds
when an operator vent is converted into routed work, that rail skills write re-route notes back
to (per the routing web's re-route contract), and that a `/goal` condition mechanically checks
each turn. Three consumer classes must agree on the ledger — the gateway (writes rows), the
rail skills (write back dispositions), and the `/goal` zero-open check — so the grammar, status
vocabulary, and check command live here **once** (per the workspace's `code-quality.md` § "One source of truth for
data-shape constants"). When any grammar below changes, grep
the gateway skill + the routing web + this file before landing.

**Sibling, not generalization.** This file is modeled on the workspace's `shakedown-engine.md`
and deliberately kept a **sibling with its own pinned grammar**: the two schemas are independent
and evolve independently (the shakedown grammar has three live consumers and its own executed
fixtures; sharing a table schema would couple them for no gain). The only reused element is the
slug rule (§1), taken by cross-reference.

Cited by: [`skill-pipeline.md § "Re-route contract"`](skill-pipeline.md) (write-back, step 3);
`user-gateway/SKILL.md`.

---

## 1. Ledger file contract

### Path formula

```
<git-root>/.claude/task-state/intake-<topic-slug>.md
```

`<git-root>` is ALWAYS resolved via `git rev-parse --show-toplevel` — **never** cwd-relative.
A ledger written from inside a worktree with a relative path is silently lost on worktree
cleanup (the workspace's task-state-schema gotcha) — and
rail skills writing back a re-route (§5) may be running anywhere.

### Topic slug (reused by cross-reference)

`<topic-slug>` is computed from the gateway's topic argument by the **deterministic
feature-slug rule** the workspace's `shakedown-engine.md` §1 owns (kebab-case: lowercase;
spaces/underscores → single hyphens; strip characters outside `[a-z0-9-]`; collapse repeated
hyphens; trim leading/trailing hyphens). Same rule for the same reason:
every writer — the gateway seeding rows, a rail skill writing back, the `/goal` evaluator —
must resolve the **same** file for the same topic, or a write-back silently lands in a second
ledger the check never sees.

### Locating the ledger for write-back

Every seed the gateway emits carries the ledger path (the gateway's closing block states it);
a rail skill that received its work through a gateway seed writes back to that path. A rail
skill invoked directly, merely suspecting a ledger exists: glob
`<git-root>/.claude/task-state/intake-*.md` and write back only on an unambiguous match — the
routing web's contract is *"when one exists"*, so no match (or an ambiguous one) means **skip
the write-back**, never guess.

---

## 2. Row schema (machine-checkable)

The ledger body is a single markdown table. One data row per operator fragment:

```
| id | fragment | route | status | disposition |
```

- **`id`** — `F<N>`, sequential from `F1` in seeding order. New rows appended later (a second
  gateway pass on the same topic) continue the sequence from the highest existing id.
- **`fragment`** — the operator's fragment, condensed to one line. Interior cell: must be
  pipe-free (render any literal `|` as `/`; a pipe that slips through makes the row count as
  open — the fail-safe direction, §3).
- **`route`** — the rail this fragment was routed onto, chosen from the routing web
  ([`skill-pipeline.md § "The 8 rails"`](skill-pipeline.md)); `-` until the row is routed.
  Deliberately **not pinned** by the grammar below: the routing web is the one owner of the
  rail vocabulary, and pinning rail names here would create a second owner that drifts when a
  rail is added. The check never needs it — closure is a **status** question, not a route
  question.
- **`status`** — exactly one of four words, pinned HERE (this file is the owner):
  - `open` — captured but not yet routed; still intake work.
  - `routed` — converted to a ready-to-paste seed on a rail — **terminal for the gateway**.
    The disposition holds the seed pointer, plus any later re-route note (§5). Whether the
    seeded work itself finishes is the receiving rail's business (its plan, issue, or
    shakedown ledger), not this ledger's.
  - `parked` — a decide-rail row: an operator-only choice, surfaced with the open question
    stated, awaiting the operator — never ground through autonomously. An operator decision
    resolves a parked row to `routed` (disposition gains the seed) or `done` (disposition
    records the decision).
  - `done` — the underlying work was closed (by the operator or a skill); the disposition
    records the closure evidence.
- **`disposition`** — the row's outcome record: the seed pointer for a `routed` row, the open
  question for a `parked` row, closure evidence for a `done` row, and any re-route note (§5).
  Never a bare status flip with an empty disposition. Stays **one line**: a short seed command
  inline when it fits, otherwise a one-line pointer/summary — the gateway's own output block
  owns paragraph-length seeds (e.g. `/plan-feature` text); the ledger never holds paragraphs.

### Pinned cell grammar

The status word stands **alone in its cell**, pipe-and-space delimited: the literal three-token
sequence `| open |` (pipe, space, word, space, pipe). This exact grammar is what makes the
zero-open check a deterministic grep that cannot be fooled by the word "open" appearing inside
fragment or disposition prose.

A **well-formed data row** matches, in full:

```
^\| *F[0-9]+ *\|[^|]*\|[^|]*\| *(open|routed|parked|done) *\|.*$
```

(row starts with an `F<n>` id, a fragment cell and a route cell each with no interior pipe, a
status cell holding exactly one of the four words, then the **disposition cell**.)

**What counts as a data row is decided structurally, never by the id**: every `^\|` table row
except the header (first cell literally `id`) and the all-dashes separator is a data row (§3
computes this as `ROWS − HEADER − SEP`), and each one must match this full grammar — `F<n>` id
included — or it counts as open. Anchoring data-row detection on the id itself would let a row
whose id cell got corrupted (`X9`, blank, lowercase `f1`) vanish from the count entirely — the
one corruption class that could silently close the goal.

The disposition is the **terminal** cell and may itself contain pipes — seed text routinely does
(`pytest -k export | tail -1`, `grep -E 'a|b'`) — so it is matched with `.*$`, never `[^|]*`.
Pinning it pipe-free would miscount a genuinely-`routed` row whose seed quotes a piped command
as malformed → `open`, which would make the zero-open `/goal` **unreachable** even on a clean
ledger.

A filled example row:

```
| F1 | export button 500s on an empty set | bug | routed | seed: `/user-debug --symptom 'export 500 on empty set'`; repro check `pytest -k export | tail -1` |
```

---

## 3. Zero-open check + well-formedness fail-safe

The `/goal` condition is agent-completable only because "zero open" is a deterministic check.
The check counts **open-status rows PLUS malformed data rows**, where *data row* is defined
**structurally** (every table row except the header and the separator — §2). A data row that
fails the full grammar — an unknown status word, a pipe in an interior cell, or a **corrupted
id cell** — is treated as `open` (fail-safe), so corruption can only ever make MORE work
visible, never hide it.

**The check fails loud, and ABORT ≠ zero-open.** The block's first lines are guards: a missing
ledger file, or a file with no ledger header, ABORTS with exit 1 instead of printing a count.
Without the guard, grep on a missing file arithmetics to `UNROUTED=0` and a `/goal` evaluator
reads *goal met* off a ledger that was never created (the workspace's `measurement-validity.md` § "Fail loud on fallback config"). An evaluator must treat any non-zero
exit as **goal NOT met**; only a printed `0` from a real ledger satisfies the condition. A
header-only ledger genuinely scores `0` — zero fragments captured is a closed intake — and the
guards are what distinguish *never created* (ABORT) from *created but empty* (`0`).

**`parked` does NOT count as open — deliberately.** The canonical goal is *"zero open items"*:
every fragment **converted or surfaced**, not every decision made. Decide rows are
operator-only by design (the routing web's decide rail: *surfaced, parked, never ground
through*), so an agent working under the `/goal` cannot legitimately close one — counting
`parked` would make the goal unreachable-by-agent, exactly the reachability failure the
goal-mode doctrine forbids (`/goal` only for finish lines the agent can drive). Parked
questions stay visibly waiting in the ledger; they are simply not intake work. `routed` and
`done` do not count, for the obvious reason.

```bash
LEDGER="$(git rev-parse --show-toplevel)/.claude/task-state/intake-<topic-slug>.md"
[ -f "$LEDGER" ] || { echo "ABORT: ledger not found: $LEDGER" >&2; exit 1; }          # fail loud — never a silent 0
grep -qE '^\| *id *\|' "$LEDGER" || { echo "ABORT: no ledger header in: $LEDGER" >&2; exit 1; }  # truncated/garbage file
STATUS='open|routed|parked|done'   # the four status words — canonical list, defined once, reused below

# data rows = every table row EXCEPT the header and the structural separator (id-agnostic:
# an id-corrupted row still lands in DATA, fails WELL below, and so counts as open)
ROWS=$(grep -cE '^\|' "$LEDGER")
HEADER=$(grep -cE '^\| *id *\|' "$LEDGER")
SEP=$(grep -cE '^\|[-:| ]*-[-:| ]*$' "$LEDGER")
DATA=$(( ROWS - HEADER - SEP ))
# well-formed rows = data rows matching the FULL grammar, F<n> id included.
# Disposition is the TERMINAL cell (matched `.*$`) so it may contain pipes — seed text does.
WELL=$(grep -cE "^\| *F[0-9]+ *\|[^|]*\|[^|]*\| *($STATUS) *\|.*$" "$LEDGER")
# open-status rows (status cell is exactly `open`)
OPEN=$(grep -cE '^\| *F[0-9]+ *\|[^|]*\|[^|]*\| *open *\|' "$LEDGER")

MALFORMED=$(( DATA - WELL ))
UNROUTED=$(( OPEN + MALFORMED ))
echo "$UNROUTED"     # 0 => every fragment converted or surfaced (goal satisfied); >0 => intake work remains
```

`UNROUTED == 0` (with exit 0) is the mechanical termination condition. Any malformed row —
including one whose id cell no longer reads `F<n>` — makes it non-zero even if no cell
literally says `open`, so a typo can never silently close the goal.

### Canonical /goal string

Defined here once; `/user-gateway` emits it in its closing block:

```
/goal "intake ledger for <topic-slug> has zero open items"
```

The condition is checkable every turn by running the block above and asserting `UNROUTED == 0`.

---

## 4. Seeding (idempotent — load before derive)

**If the ledger file already exists, LOAD it as-is before writing. Never re-seed, never
regenerate from memory.** The file on disk is the source of truth, not the transcript: a
second gateway pass on the same topic, or a rail skill writing back a re-route, appends or
updates rows in the loaded file (new rows continue the `F<N>` sequence), while regenerating
the table from conversation memory silently drops rows written by other sessions or skills.
Seed a fresh table **only when the file is absent**. The near-miss safety net keys on the
**topic slug, never on any-ledger-exists**: other topics' ledgers routinely coexist under
`intake-*.md`, and an existing ledger for a *different* topic must never block seeding a new
one. Before seeding, glob `<git-root>/.claude/task-state/intake-*.md` and load-instead-of-seed
only when an existing filename matches the computed topic slug or is an obvious near-miss of
it (one slug contains the other — two phrasings of the same topic); otherwise seed the new
ledger.

**One session writes a given ledger at a time** (the workspace's parallel-session rules
apply); a rail-skill write-back appends to its named row only — it never rewrites the table.

Rows are seeded by `/user-gateway`: one row per fragment from the vent's listening pass,
`status = open`, then flipped to `routed` / `parked` as each fragment is dispatched via the
routing web. How fragments are elicited and routes chosen is the gateway's contract, not this
file's.

---

## 5. Re-route write-back (contract owned elsewhere)

When a rail skill discovers mid-run that its work is on the wrong rail, the **re-route
contract** — the emit-line format, the seed for the correct rail, the stop rule — is owned by
[`skill-pipeline.md § "Re-route contract"`](skill-pipeline.md); this file owns only what the
write-back does to a row: **the row's status stays `routed`** (never a new status word, never
a flip back to `open`), **and the disposition gains a note recording the re-route** alongside
the original seed pointer. The ledger records where the fragment was sent and where it ended
up; the re-routed work itself lives on the new rail.

---

## 6. Calibration fixtures (run, not read)

Three frozen ledgers anchor the zero-open check per the workspace's `measurement-validity.md` § "Calibrate with anchors before
comparing candidates": a known-good
(all closed) that must score `0`, a known-garbage (one open) that must score `1`, and a
corruption fixture (one id-corrupted row + one status-corrupted row) that must score `2` —
the §3 fail-safe demonstrated, not assumed. Extract any fixture to a file and run the §3
check against it.

### Fixture A — all-closed (must yield `0`)

```
| id | fragment | route | status | disposition |
|----|----------|-------|--------|-------------|
| F1 | export button 500s on an empty set | bug | routed | seed: `/user-debug --symptom 'export 500 on empty set'`; repro check `pytest -k export | tail -1` |
| F2 | ship v2 as opt-in or default? | decide | parked | operator-only: opt-in vs default rollout — question surfaced, awaiting operator |
| F3 | rename the stale config key | do | done | closed via /goblin-do; scoped commit landed |
```

Fixture A carries both regression guards. `F1`'s disposition deliberately contains a pipe
(`| tail -1`) — a genuinely-`routed` row whose seed quotes a piped command; a check that pins
the disposition cell pipe-free would count it malformed → `open` and yield `1` (guard for the
terminal-cell `.*$` grammar in §2). `F2` is `parked` — a check that counted `parked` as open
would also yield `1` and make gateway closure impossible whenever a vent surfaces an
operator-only choice (guard for the §3 counting decision).

### Fixture B — one-open (must yield `1`)

```
| id | fragment | route | status | disposition |
|----|----------|-------|--------|-------------|
| F1 | export button 500s on an empty set | bug | routed | seed: `/user-debug --symptom 'export 500 on empty set'` |
| F2 | ship v2 as opt-in or default? | decide | parked | operator-only: opt-in vs default rollout |
| F3 | the plan docs feel bloated | - | open | not yet routed |
```

### Fixture C — corrupted (must yield `2`)

Fixture A plus two hand-corrupted rows: `X9` (id cell corrupted — the row must still count,
which only the structural data-row rule guarantees) and `F4` (status word not in the
vocabulary):

```
| id | fragment | route | status | disposition |
|----|----------|-------|--------|-------------|
| F1 | export button 500s on an empty set | bug | routed | seed: `/user-debug --symptom 'export 500 on empty set'`; repro check `pytest -k export | tail -1` |
| F2 | ship v2 as opt-in or default? | decide | parked | operator-only: opt-in vs default rollout — question surfaced, awaiting operator |
| F3 | rename the stale config key | do | done | closed via /goblin-do; scoped commit landed |
| X9 | id cell corrupted by a bad write | bug | routed | id no longer matches F<n> — must still count |
| F4 | stray thought about caching | do | in-progress | hand-edited status word not in the vocabulary |
```

Both corruptions land in `MALFORMED` → counted as open. An id-gated data-row rule would score
this fixture `1` — the `X9` row silently vanishing is exactly the "corruption hides work"
failure the structural rule exists to prevent.

### Executed evidence (2026-07-13, Git Bash on Windows)

Each fixture was extracted verbatim to a temp file, `LEDGER` pointed at it, and the §3 block
run unchanged; the harness line prints the block's intermediate counts plus the final integer:

```
fixture-a.md:      ROWS=5 HEADER=1 SEP=1 DATA=3 WELL=3 OPEN=0 MALFORMED=0 UNROUTED=0
fixture-b.md:      ROWS=5 HEADER=1 SEP=1 DATA=3 WELL=3 OPEN=1 MALFORMED=0 UNROUTED=1
fixture-c.md:      ROWS=7 HEADER=1 SEP=1 DATA=5 WELL=3 OPEN=0 MALFORMED=2 UNROUTED=2
header-only.md:    ROWS=2 HEADER=1 SEP=1 DATA=0 WELL=0 OPEN=0 MALFORMED=0 UNROUTED=0
missing file:      ABORT: ledger not found: .../intake-does-not-exist.md   (exit 1)
zero-byte file:    ABORT: no ledger header in: .../intake-truncated.md     (exit 1)
```

The header-only run is the *created but empty* case from §3 — a genuine `0` — while the
missing-file and truncated-file runs ABORT with exit 1 rather than printing a count. These
outputs were produced by executing the check, not by reading it.
