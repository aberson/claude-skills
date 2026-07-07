---
name: skill-eval-setup
description: Auto-generate an evaluation framework (evals.json + test_scenarios.json) for any skill by reading its SKILL.md, then output a ready-to-paste self-improvement loop prompt. Use as "/skill-eval-setup <skill-name-or-path>".
user-invocable: true
---

# Skill Eval Setup

Takes a skill name or path, reads its SKILL.md, and produces:
1. An `evals/` folder inside the skill directory
2. `evals/evals.json` — true/false assertions auto-derived from the SKILL.md
3. `evals/test_scenarios.json` — 2–3 synthetic scenarios to test the skill against
4. A copy-paste prompt the user runs in a fresh window to start the self-improvement loop

---

## Input

The user provides one of:
- A skill name (e.g., `session-wrap`) — resolved to `.claude/skills/<name>/SKILL.md`
- A relative or absolute path to a skill folder or SKILL.md

Optional flag:
- `--keep-scenarios` — when the target skill already has `evals/test_scenarios.json`, do NOT overwrite it. Regenerate only `evals.json`. Use this when regenerating the assertion set against a rebuilt eval bar while preserving hand-crafted, project-specific scenarios.

If the skill or SKILL.md cannot be found, report the error and stop.

---

## Step 1: Read and analyze the SKILL.md

Read the target SKILL.md completely. Extract every testable requirement:

### What to look for

| Signal | Example | Assertion type |
|---|---|---|
| **Required sections** | "Output two parts: X and Y" | Structure — output contains X and Y |
| **Format rules** | "wrapped in a code fence labeled `text`" | Structure — format matches |
| **Quantity constraints** | "4–8 lines", "2–5 files", "300–600 words" | Structure — count in range |
| **Content requirements** | "must be self-contained", "include the magic word" | Content — specific content present |
| **Specificity rules** | "concrete, not generic", "specific, actionable" | Content — no vague placeholders |
| **Process steps** | "Read MEMORY.md", "Check plan.md" | Process — step was performed |
| **Anti-patterns** | "do NOT duplicate", "skip one-off flukes" | Anti-pattern — bad thing absent |
| **Conditional behavior** | "if X exists, do Y; otherwise do Z" | Conditional — correct branch taken |

### Categorization

Group assertions into categories that match the skill's logical structure. Use the skill's
own section headings as category names when possible. Always include an "Anti-patterns"
category for negative assertions (things the skill must NOT do).

### Assertion format

Each assertion must be:
- A single declarative statement that can be judged TRUE or FALSE
- Testable by reading the skill's output alone (no access to internal state)
- Traceable to a specific line or section in the SKILL.md via the `source` field

---

## Step 1.5: Design discrimination assertions

For each rule extracted in Step 1, name the **defect type** that would violate
the rule. The defect type drives a discrimination assertion: "if the output
exhibits defect D, this assertion grades FALSE."

This is the difference between an eval that catches things and an eval that
just describes things. A shape-checking assertion ("output contains two parts")
passes any well-formed output but cannot tell you whether the assertion is
*useful*. A discrimination assertion ("if either 'Part 1' or 'Part 2' heading
is absent, this assertion grades FALSE") is testable against a deliberately-
broken output corpus.

### Rule → defect type → discrimination assertion

| Rule pattern | Defect type | Discrimination assertion shape |
|---|---|---|
| "Output two parts X and Y" | structural — missing required part | "Output contains both X heading AND Y heading" |
| "wrapped in `text` code fence" | format — wrong fence label | "Output's outer fence label is exactly `text`" |
| "4-8 lines per entry" | quantity-constraint violation | "Every entry has line count in [4, 8]" |
| "must be self-contained" | content — external dependency | "Output references no file path outside the listed Key files set" |
| "do NOT duplicate" | anti-pattern — content-filter | "Output does not contain a memory entry already present in the target memory file" |
| "skip one-off flukes" | anti-pattern — content-filter | "Friction items do not include language matching /typo\|retry\|transient\|attempt/i" |
| "NEVER use triple-backtick fences inside X" | anti-pattern — explicit-rule | "X section contains no occurrences of '```' beyond the outer fence" |
| Fixed-form required bullet ("FIRST bullet must be: <literal>") | required-content — wrong form | "First bullet of `<section>` starts with the literal string `<fixed-form prefix>`" |
| Required fixed string in named section ("the magic word for this project is X") | required-content — fixed-string missing | "`<named section>` contains the literal string `<fixed value>`" |
| Cross-part claim ("Part 1's `<field>` bullet says YES → Part 2 must not reference prior conversation") | internal-inconsistency — cross-part contradiction | "If Part 1's `<field>` bullet contains `<positive value>`, Part 2 contains no occurrences of `/<contradicting pattern>/`" |
| Conditional behavior ("IF multi-project session, THEN use `/` per-repo separator in Git line") | conditional-behavior — rule not applied | "When `<observable signal of condition>` is present in the output, `<observable signal of required behavior>` is also present" |

### Pattern derivation guide — patterns most likely to be missed

The example rows above cover structural and anti-pattern rules well. The four
patterns below get systematically missed by template-following and need
explicit derivation.

**1. Fixed-form content.** When the target SKILL.md says "the first X must be
in this exact form" or "must start with the literal string Y", derive an
assertion that checks for the **literal string**, not just that X exists.
Generic "X is present" assertions pass any well-formed X.

**2. Required fixed strings in named sections.** When the SKILL.md names a
specific section ("Required context") AND specifies that a particular literal
string must appear there ("the magic word X"), derive an assertion that
checks for the literal string **inside the named section**.

**3. Cross-part consistency.** When the SKILL.md output has multiple parts
and one part makes a claim about another (e.g., Part 1's `Self-contained:`
bullet asserts whether Part 2 has external dependencies), derive a cross-part
assertion: read the claim in Part 1, then check Part 2 for content that would
contradict it. The assertion's `source:` field must reference BOTH the
part-making-the-claim AND the part-being-claimed-about. Cross-part assertions
are the hardest pattern for template-following to produce — be explicit about
deriving at least one.

**4. Conditional behavior (IF/THEN rules).** Scan the target SKILL.md for
every "If X, …" / "Multi-X sessions: …" / "When X happens, do Y" pattern.
For each, derive an assertion of the form "if `<observable signal of X>` in
the output, then `<observable signal of Y>` in the output."

### Pair each assertion with a target-skill-section reference

Each assertion's `source:` field must point to the specific lines in the
target SKILL.md that define the violated rule.

**Sourcing precision rule.** For every NEVER / NOT / IF / MUST / "fixed in
form" rule in the target SKILL.md, at least one produced assertion's
`source:` field must name the **specific line** that defines the rule —
either as a standalone number, or as one endpoint of a tight range (≤15
lines wide). A wide line range that brackets but doesn't single out the
rule's line does NOT satisfy this — a reader must be able to locate the
rule from the source string alone.

**Section-heading coverage rule.** Separately from the per-rule precision
above, the produced `source:` fields collectively must reference at least
one line within 10 lines of each major numbered section heading in the
target SKILL.md (Step 1, Step 2, Step 3, etc.). Pure rule-line precision
tends to cluster source citations around sub-rules, leaving section
headings uncovered — derive at least one assertion per major section
whose source field cites the heading line or a line within 10 of it.

### Discrimination quota

Of the assertions in the produced evals.json, **at least 40% must be
discrimination-style** (assertions whose statement names what would make them
grade FALSE, not just what would make them grade TRUE). Shape-only assertions
are still allowed but they are sanity checks, not the primary signal.

Additionally, **at least one of each of the four "patterns most likely to be
missed"** above should appear in the produced evals.json when the target
SKILL.md contains the corresponding rule type. If a pattern type doesn't
apply to a particular target (e.g., target has no multi-part output → no
cross-part consistency assertion possible), note its absence in Part 1
Summary with a one-line "(no X-pattern rules in target — N/A for this skill)".

---

## Step 2: Generate test scenarios

Create 2–3 synthetic test scenarios that exercise different paths through the skill.

### Scenario design principles

- **Cover the main path:** At least one scenario that exercises the skill's primary flow
- **Cover edge cases:** At least one scenario that triggers conditional behavior (e.g., "if
  plan.md is absent", "if the session was clean with no friction")
- **Be self-contained:** Each scenario must include all the context the skill needs to
  produce output — simulated conversation history, file states, user actions
- **Be concrete:** Use realistic project names, file paths, and actions — not "project X"

### Scenario format

```json
{
  "id": "scenario_1",
  "name": "Descriptive name",
  "description": "What this scenario tests",
  "context": "The simulated conversation/environment state the skill sees",
  "expected_assertions": [1, 2, 3, ...]
}
```

The `expected_assertions` field lists which assertion IDs should pass for this scenario.
Typically all assertions apply to all scenarios, but some conditional assertions may only
apply to specific scenarios.

---

## Step 3: Write the eval files

### evals.json

```json
{
  "skill": "<skill-name>",
  "version": "1.0",
  "description": "True/false evaluation for the <skill-name> skill.",
  "passing_threshold": "<N-2>/<N>",
  "categories": [
    {
      "name": "Category Name",
      "evals": [
        {
          "id": 1,
          "statement": "The output does X.",
          "source": "SKILL.md, lines NN-MM",
          "defect_type": "<one of: structural, format, quantity, content, anti-pattern, required-content, internal-inconsistency, conditional-behavior, n/a-sanity, n/a-coverage>",
          "result": null
        }
      ]
    }
  ]
}
```

Rules:
- Set `passing_threshold` to `(total - 2) / total` — allows 2 failures before the skill
  is considered broken
- Number assertions sequentially starting at 1
- The `result` field is always `null` in the template — the loop fills it in
- The `source` field must reference actual line numbers in the SKILL.md (per the
  Sourcing precision and Section-heading coverage rules in Step 1.5)
- The `defect_type` field categorizes the assertion. Use `n/a-sanity` for pure
  structural sanity checks (valid JSON, sequential ids, etc.) and `n/a-coverage`
  for assertions that aggregate over the target SKILL.md rather than testing a
  specific defect.

### test_scenarios.json

```json
{
  "skill": "<skill-name>",
  "version": "1.0",
  "scenarios": [
    {
      "id": "scenario_1",
      "name": "...",
      "description": "...",
      "context": "...",
      "expected_assertions": [1, 2, 3]
    }
  ]
}
```

Write both files to `<skill-folder>/evals/`.

### `--keep-scenarios` behavior

When `--keep-scenarios` is passed AND `<skill-folder>/evals/test_scenarios.json` already exists:
1. Do NOT overwrite `test_scenarios.json`.
2. Read the existing scenarios and use their `id` values when assigning `expected_assertions` references in the new `evals.json`. If the new assertion set has IDs the old scenarios don't reference (or vice-versa), this is expected — the scenarios stay as-is; only the assertion list is rebuilt.
3. In Part 2 of the output, list `test_scenarios.json` with a `(preserved — N scenarios)` suffix instead of as a written file.

When `--keep-scenarios` is passed BUT no existing `test_scenarios.json` is found, fall through to normal behavior (generate fresh scenarios) and note this in Part 1 Summary.

---

## Step 4: Generate the self-improvement loop prompt

Output the following prompt, customized for the target skill. Present it in a code fence
labeled `text` so the user can copy-paste it into a fresh window.

The prompt must include:
1. The skill name and the **absolute** path to the evals folder (e.g., `.claude/skills/<skill-name>/evals/`) — every `<skill-path>` and `<skill-name>` placeholder in the template must be replaced with concrete absolute values
2. Instructions to read the evals.json and test_scenarios.json
3. The produce-then-grade loop: for each scenario, simulate the skill's behavior following
   the SKILL.md instructions, produce the output, then grade every assertion TRUE/FALSE
4. Score calculation: pass count / total assertions across all scenarios
5. If any assertions fail: propose ONE targeted change to SKILL.md, apply it, re-run all
   scenarios, and compare scores
6. Keep/revert logic: keep if score improved, `git reset` if not
7. Iteration logging: number, score, keep/discard, what was tried
8. Termination: perfect score or user interrupt
9. Git commit on each kept change with a message like:
   `<skill-name> eval: iteration N — <what changed>`

### Prompt template

```text
Run a self-improvement loop on the skill at `<skill-path>`.

## Setup
- Read `<skill-path>/SKILL.md` (the skill definition)
- Read `<skill-path>/evals/evals.json` (the assertions)
- Read `<skill-path>/evals/test_scenarios.json` (the test scenarios)

## Loop (repeat until perfect score or interrupted)

### Produce
For each scenario in test_scenarios.json:
1. Simulate the environment described in the scenario's `context` field
2. Follow the SKILL.md instructions exactly as if you were executing the skill
3. Produce the full output the skill would generate

### Grade
For each assertion in evals.json, judge the produced output:
- TRUE if the assertion holds for the output
- FALSE if it does not
- When in doubt, grade FALSE (strict grading prevents false passes)

Calculate score: (total TRUE across all scenarios) / (total assertions x number of scenarios)

### Improve
If score < 100%:
1. Identify the root cause of the lowest-confidence FALSE assertions
2. Propose ONE targeted change to SKILL.md that would fix them without breaking passing assertions
3. Apply the change
4. Re-run Produce + Grade for all scenarios
5. If score improved: `git add <skill-path>/SKILL.md && git commit -m "<skill-name> eval: iteration N — <description>"`
6. If score did not improve: `git checkout -- <skill-path>/SKILL.md`

### Log
Append to `<skill-path>/evals/iteration_log.md` using this format:

    ## Iteration N
    - Score: X/Y (Z%)
    - Result: KEPT / DISCARDED
    - Change: <one-line description of what was tried>
    - Failures: <list of assertion IDs that failed>

## Rules
- Do NOT stop to ask questions. Run autonomously.
- Do NOT make more than ONE change per iteration.
- Do NOT modify evals.json or test_scenarios.json.
- If you hit 3 consecutive DISCARDED iterations with no progress, try a fundamentally
  different approach rather than tweaking the same area.
```

Replace all `<skill-path>` and `<skill-name>` placeholders with actual values.

---

## Step 5: Generate the golden bad-example corpus

`/skill-iterate`'s composite scoring (see `_shared/score-skill.md`) requires
a per-skill **golden corpus**: one `good.md` plus one `bad_<defect-slug>.md`
per discrimination assertion. The corpus is the gradient signal hill-climbing
optimizes against — without it, shape-only assertions pass 100% on any
well-formed output and the loop has no gradient.

Hand-writing the corpus does not scale (27 evaluable skills × 5–9 defect
types ≈ 130–240 files). This step documents the LLM-driven generation
procedure and the script that automates it.

Run the generator after Step 4 finishes. The generator consumes the
`evals.json` produced by Step 3 and emits the corpus into
`<skill-dir>/evals/golden/`.

### Per-skill golden directory layout

```
.claude/skills/<skill-name>/evals/golden/
    good.md                       <- one well-formed reference output
    bad_<defect-slug-1>.md        <- one per discrimination assertion
    bad_<defect-slug-2>.md
    ...
    manifest.json                 <- per-bad metadata index
```

The corpus is **self-contained per skill** (plan §6 D5) — every skill ships
with its own goldens; there is no central corpus directory. `/skill-iterate`
discovers a skill's corpus by reading `<skill-dir>/evals/golden/manifest.json`.

### Slug derivation rule

Map each assertion's `defect_type` field to a filesystem-safe slug:

1. Lowercase the `defect_type`.
2. Replace every run of non-alphanumeric characters with a single `_`.
3. Strip leading and trailing `_`.
4. Truncate at 60 characters.

| `defect_type` | Derived slug | Filename |
|---|---|---|
| `structural — missing required output part` | `structural_missing_required_output_part` | `bad_structural_missing_required_output_part.md` |
| `anti-pattern — explicit-rule violation` | `anti_pattern_explicit_rule_violation` | `bad_anti_pattern_explicit_rule_violation.md` |
| `quantity-constraint violation` | `quantity_constraint_violation` | `bad_quantity_constraint_violation.md` |
| `required-content — fixed-string missing` | `required_content_fixed_string_missing` | `bad_required_content_fixed_string_missing.md` |

When two assertions share the same `defect_type` (and therefore the same
raw slug), the script appends a numeric suffix: `bad_duplicate_constants.md`,
`bad_duplicate_constants_2.md`, `bad_duplicate_constants_3.md`. The suffix
preserves the 60-char total length cap by trimming the base portion first.

### Per-assertion mapping

One bad file per **discrimination assertion**, where "discrimination" means
`defect_type` is NOT in `{n/a-sanity, n/a-coverage}`. Sanity-shape and coverage
assertions are excluded because they do not name a planted defect to target.

The mapping is 1:1:1 — one assertion → one defect_type → one slug → one
`bad_<slug>.md` file. If `evals.json` contains 8 discrimination assertions
across all categories, the corpus has 8 `bad_*.md` files.

### Generator sub-agent contract

The script dispatches one LLM sub-agent per assertion with these inputs:

| Input | Source |
|---|---|
| Assertion text + `defect_type` | from `evals.json` |
| `good.md` content | from `<skill-dir>/evals/golden/good.md` if hand-crafted, else auto-generated stub |
| Target `SKILL.md` content | from `<skill-dir>/SKILL.md` |
| Subtlety instruction | `"subtle"` (default) or `"obvious"` |

The sub-agent is instructed to:
1. Modify the GOOD output minimally so it violates **exactly** the named
   `defect_type` (prefer a single-line diff against `good.md`).
2. Keep every other SKILL.md rule satisfied (only one defect planted).
3. Stay in the **subtle zone** by default — preserve surface plausibility,
   violate only the underlying rule. A sycophantic grader doing a substring
   or paraphrase-tolerant check should still mistakenly pass the output;
   only a strict assertion tied to the named defect_type should catch it.
   (Per investigation file `11-bad-example-difficulty-calibration.md`, LLMs
   default to obvious-bad — the explicit subtle instruction is what produces
   real pressure-test material.)
4. Prepend an HTML comment header naming the defect and the SKILL.md line
   range it violates. Example:

   ```
   <!-- BAD OUTPUT — DEFECT: <one-line defect summary> -->
   <!-- Violates SKILL.md lines <N-M>: "<quoted rule fragment>" -->
   ```

The sub-agent returns ONLY the bad.md content (header + body). No surrounding
prose, no JSON envelope.

### `manifest.json` schema (v2 — post Step 9 verification gate)

```json
{
  "manifest_version": 2,
  "skill": "<skill-name>",
  "generated_at": "<ISO-8601 timestamp, UTC, second precision>",
  "good_source": "auto-generated" | "hand-crafted",
  "verification_summary": {
    "accepted": <int>,
    "inert": <int>,
    "total": <int>
  },
  "bads": [
    {
      "file": "bad_<slug>.md",
      "defect_type": "<from assertion>",
      "assertion_id": "<from evals.json if present, else null>",
      "verified_fails": true | false,
      "regen_attempts": 1 | 2 | 3
    }
  ]
}
```

Schema notes (populated by the Step 9 §Verification gate below):

- `manifest_version` is `2` for every manifest written by a Step-9-or-newer
  generator. Prior generators wrote no `manifest_version` field and used
  `verified_fails: null` / `regen_attempts: 0` placeholders — those manifests
  remain readable but should be regenerated to pick up real verification.
- `verification_summary` is a fleet-scannable tally: `accepted` counts bads
  with `verified_fails: true`, `inert` counts bads with `verified_fails:
  false`, and `total` is their sum.
- Per-bad `verified_fails` is `true` (grader correctly distinguished bad from
  good — gate accepted), or `false` (grader did NOT distinguish after the
  retry budget was exhausted — bad is INERT). Never `null` post-Step-9.
- Per-bad `regen_attempts` is the total number of dispatches consumed
  (`1` accepted on first try, `2` on first retry, `3` on second retry or
  INERT-after-final).

### CLI interface

The generator script lives at `scripts/generate_bad_examples.py` (relative
to the skill root: `.claude/skills/skill-eval-setup/scripts/`). Three
operator entry points:

| Command | Effect |
|---|---|
| `python generate_bad_examples.py <skill-name>` | Regenerate one skill's goldens. |
| `python generate_bad_examples.py --fleet` | Regenerate every auto-discovered scorable skill (parallel batches; default batch size 3). |
| `python generate_bad_examples.py --skill <name> --dry-run` | Preview what would be generated without dispatching any sub-agent or writing any files. |

Additional flags:
- `--batch-size N` — override the fleet batch size (default 3).
- `--subtlety {subtle,obvious}` — pick the difficulty tier (default `subtle`).
- `--max-regen-attempts N` — verification-gate retry budget (default `3`).
  See §Verification gate below.
- `--verify-only` — re-score existing on-disk bads against the current
  grader without regenerating. See §Verification gate below.

JSON summary is written to stdout (machine-consumable by orchestrators);
human-readable progress to stderr.

Auto-discovery (the `--fleet` set) finds every `.claude/skills/<name>/`
directory that contains an `evals/evals.json` file, excluding entries
beginning with `_` (shared fragments).

### Worked example — slug derivation for the session-wrap corpus

Applying the rule to the session-wrap `evals.json` discrimination assertions
yields these filenames (matching the hand-crafted corpus already on disk):

| Assertion `defect_type` | Slug | Filename |
|---|---|---|
| `structural — missing required output part` | `structural_missing_required_output_part` | `bad_structural_missing_required_output_part.md` |
| `anti-pattern — explicit-rule violation` | `anti_pattern_explicit_rule_violation` | `bad_anti_pattern_explicit_rule_violation.md` |
| `required-content — fixed-form bullet missing` | `required_content_fixed_form_bullet_missing` | `bad_required_content_fixed_form_bullet_missing.md` |
| `quantity-constraint violation` | `quantity_constraint_violation` | `bad_quantity_constraint_violation.md` |
| `anti-pattern — content-filter violation` | `anti_pattern_content_filter_violation` | `bad_anti_pattern_content_filter_violation.md` |
| `required-content — fixed-string missing` | `required_content_fixed_string_missing` | `bad_required_content_fixed_string_missing.md` |
| `internal-inconsistency — cross-part contradiction` | `internal_inconsistency_cross_part_contradiction` | `bad_internal_inconsistency_cross_part_contradiction.md` |
| `conditional-behavior — multi-project rule not applied` | `conditional_behavior_multi_project_rule_not_applied` | `bad_conditional_behavior_multi_project_rule_not_applied.md` |

(The existing session-wrap hand-crafted corpus uses shorter operator-chosen
names — `bad_one_part.md`, `bad_nested_fence.md`, etc. The generator's
defect-type-derived slugs are longer but mechanical, so a regen is
non-destructive: hand-crafted bads stay where they are; generated bads use
the longer slugs and live alongside.)

### Verification gate

Each generated bad is immediately scored against the current grader before
being accepted into the corpus. The gate exists because inert bad examples
(defects the grader does not actually catch) add noise without value —
investigation file 03 anchors this as the meta-principle for the
hill-climbing Tier 1 mechanisms.

#### Accept criterion

A bad is **accepted** when its grader score is **strictly lower** than the
good's grader score on the same scoring procedure. Ties count as
not-distinguishing (the grader cannot tell bad-from-good with this fixture
pair) and trigger a regenerate.

The grader is the composite scoring procedure from `_shared/score-skill.md`
(implementation: `_shared/score_skill_composite.py`). The gate calls the
grader once with the good content as input and once with the bad content as
input; if `bad_score < good_score` the verdict is `fails` (gate accepts);
otherwise `passes` (gate rejects). A scorer exception or invalid return
shape yields verdict `indeterminate`, which the gate treats as `passes` for
safety — an unverifiable bad is regenerated, not accepted.

#### Retry policy

| Attempt | Prompt change | Outcome on `fails` | Outcome on `passes` |
|---|---|---|---|
| 1 | base generator prompt | accept (`verified_fails: true, regen_attempts: 1`) | escalate to attempt 2 |
| 2 | base + "Previous attempt was too obvious; try a SUBTLER defect" | accept (`verified_fails: true, regen_attempts: 2`) | escalate to attempt 3 |
| 3 | base + "FINAL retry; make this attempt MORE SUBTLE than the last" | accept (`verified_fails: true, regen_attempts: 3`) | mark INERT (`verified_fails: false, regen_attempts: 3`) |

The retry-prompt augmentation is mechanical: a helper
`build_retry_prompt(original_prompt, attempt)` appends the attempt-specific
directive. The retry budget is configurable via `--max-regen-attempts N`
(default `3`).

#### INERT marker

After `max_regen_attempts` consecutive grader-passes, the bad is marked
INERT in the manifest with `verified_fails: false`. The most recent
generated content is still written to disk so the operator can inspect what
the generator produced and decide whether to:

1. Hand-craft a discriminating bad (the generator's planted defects were
   all in the grader's blind spot for this assertion).
2. Tighten the corresponding assertion in `evals.json` (the assertion as
   written cannot distinguish the failure modes the generator considers
   subtle).
3. Accept the gap and revisit during the next adversarial calibration
   pass (Step 13 of the SIHC plan).

`verification_summary` in `manifest.json` exposes the `accepted` / `inert`
/ `total` tally so a fleet-wide regeneration can be scanned with a single
jq query for problematic skills (`inert > 0`).

#### CLI flags

- `--max-regen-attempts N` — override the retry budget (default `3`).
- `--verify-only` — re-verify the existing on-disk corpus WITHOUT
  regenerating. Useful after a grader change: each `bad_<slug>.md` on disk
  is re-scored against the new grader and its `verified_fails` field is
  updated in place. The generator sub-agent dispatcher is never called in
  this mode (no token spend, no wall-clock waiting on retries).

#### Forward references

Step 12 of the SIHC plan wires this corpus (now annotated with
verified-fails verdicts) into `/skill-iterate`'s per-iteration scoring
loop so the keep/revert decision pulls signal only from verified-failing
bads. Step 13 adds the adversarial-mutation calibration pass that lets the
INERT pool stop being a backlog: each INERT bad becomes input to a stricter
assertion derivation pass.

---

## Output format

Output three clearly separated parts:

### Part 1 — Summary

A short paragraph (3–5 lines) confirming:
- How many assertions were generated and in how many categories, AND of those, how many
  are discrimination-style (named `defect_type` other than `n/a-*`)
- How many test scenarios were created and what they cover
- The passing threshold

### Part 2 — Files created

List every file written, one per line, using its full **absolute** path (e.g., `.claude/skills/<skill-name>/evals/evals.json`). Do not use relative paths.

### Part 3 — Self-improvement prompt

The copy-paste prompt in a `text` code fence.

---

## What NOT to do

- Do not generate assertions that require access to internal state (tool calls made, files
  read) — only test observable output
- Do not generate more than 25 assertions — focus on the most important requirements
- Do not create scenarios that are trivially identical — each must exercise a different path
- Do not hardcode model names in the self-improvement prompt — keep it model-agnostic
- Do not modify the target SKILL.md — this skill only reads it
- Do not write vague-judgment assertions ("the output is well-structured", "the prompt feels
  clear"). Every assertion must name a specific observable property whose presence or
  absence can be checked mechanically by reading the output alone.
- Do not write assertions whose `statement` only describes positive presence when the
  SKILL.md prose explicitly forbids something. For "NEVER do X" rules, the assertion must
  name X and check for its absence directly — not a surrounding positive property that
  happens to imply X's absence.
