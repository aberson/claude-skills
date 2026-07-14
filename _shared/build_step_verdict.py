#!/usr/bin/env python3
"""Single source of truth for the build-step -> build-phase verdict contract.

`/build-step` Step 7 ("Aggregate verdict") emits a small sidecar file at
`<worktree>/.build-step/verdict.json`. `/build-phase` §2c ("Capture result")
reads it and decides whether to ADVANCE to the next step or treat the step as
BLOCKED. This module is the ONE place the consume rule lives so the SKILL.md
prose and the test suite cannot drift apart (per
`dev/.claude/rules/code-quality.md` -- "one source of truth for data-shape
constants" / "grep all downstream consumers when changing a key/id shape").

Pure stdlib (json, pathlib). No LLM, no third-party deps.

verdict.json schema
-------------------
::

    {
      "timestamp": str,                  # ISO-8601, when build-step wrote the verdict
      "result":    "PASS" | "NEEDS-WORK" | "DEFERRED-TO-UAT",
      "halt":      "POST_MERGE_HALT" | "SHIP_GATE_HALT" | null,
      "summary":   str                   # one-line human-readable rationale
    }

The `result` enum MIRRORS (but does NOT import or adopt) review-deep's
`aggregate.py` `aggregated_verdict.result` enum (PASS | NEEDS-WORK |
DEFERRED-TO-UAT). build-step emits DEFERRED-TO-UAT only on the `--reviewers
deep` lane (review-deep's aggregated verdict passes through); the other lanes
never emit it. build-phase's consume rule handles it as an ADVANCE.

The `halt` field carries build-step's in-band BLOCKED sentinels (Step 7
normalization table) stripped of their trailing colon: `POST_MERGE_HALT:` ->
`"POST_MERGE_HALT"`, `SHIP_GATE_HALT:` -> `"SHIP_GATE_HALT"`. A non-null halt
means the merge mechanics / ship gate broke (NOT a developer-fix scenario) and
the orchestrator must surface it to the operator -- so any non-null halt forces
BLOCKED regardless of `result`.

Consume rule (DEFAULT-DENY / FAIL-CLOSED)
-----------------------------------------
`classify_verdict` returns exactly `"ADVANCE"` or `"BLOCKED"`. It NEVER raises;
anything it cannot positively confirm as a clean pass fails closed to
`"BLOCKED"` (== NEEDS-WORK). ADVANCE happens ONLY when the file exists, parses,
carries a known passing `result`, AND has no halt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# The two literal results classify_verdict / build-phase distinguish.
ADVANCE = "ADVANCE"
BLOCKED = "BLOCKED"

# Schema enums (single source of truth; mirrored in both SKILL.md docs).
VALID_RESULTS = {"PASS", "NEEDS-WORK", "DEFERRED-TO-UAT"}
VALID_HALTS = {"POST_MERGE_HALT", "SHIP_GATE_HALT"}

# Results that clear the gate (when halt is null). NEEDS-WORK is intentionally
# excluded: it is the explicit "developer must iterate" signal.
ADVANCING_RESULTS = {"PASS", "DEFERRED-TO-UAT"}


def classify_verdict(verdict_path: str | Path) -> str:
    """Apply the default-deny consume rule to a verdict.json file.

    Returns the literal string ``"ADVANCE"`` or ``"BLOCKED"`` -- never raises.

    Fail-closed decision ladder (first match wins):

    * file missing / unreadable / not valid JSON / not a JSON object -> BLOCKED
    * ``halt`` present and non-null (any value)                          -> BLOCKED
    * ``result`` not in :data:`VALID_RESULTS` (unknown / missing)        -> BLOCKED
    * ``result`` == ``"NEEDS-WORK"``                                     -> BLOCKED
    * ``result`` in {PASS, DEFERRED-TO-UAT} AND ``halt`` is null         -> ADVANCE

    Accepts a ``str`` path or a :class:`pathlib.Path`.
    """
    path = Path(verdict_path)

    # --- File-level fail-closed: missing / unreadable / malformed JSON ---
    try:
        # utf-8-sig transparently strips a leading BOM (build-step's verdict.json
        # is often written via PowerShell, which emits one) and is identical to
        # utf-8 when no BOM is present -- without it, json.loads would reject the
        # BOM and FALSE-BLOCK an otherwise-valid PASS verdict.
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        # Missing file, permission error, is-a-directory, or bytes that are
        # not valid UTF-8/UTF-8-BOM (UnicodeDecodeError is a ValueError, NOT
        # an OSError -- without this clause a garbled-encoding verdict.json
        # would raise instead of failing closed).
        return BLOCKED
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        # Empty file, truncated/malformed JSON.
        return BLOCKED
    if not isinstance(data, dict):
        # A bare list / string / number is not a verdict object.
        return BLOCKED

    # --- halt fail-closed: any non-null halt blocks (regardless of result) ---
    halt = data.get("halt")
    if halt is not None:
        # Any non-null halt (valid or not) forces BLOCKED -- fail closed at
        # CONSUME time. Halt-sentinel validation lives at EMIT time in
        # translate_build_step_verdict, not here.
        return BLOCKED

    # --- result fail-closed: unknown / missing / non-string -> BLOCKED ---
    result = data.get("result")
    if not isinstance(result, str):
        # A non-string result (list/object/number) must fail closed; an
        # unhashable value would raise TypeError on the set-membership check.
        return BLOCKED
    if result not in VALID_RESULTS:
        return BLOCKED
    if result == "NEEDS-WORK":
        return BLOCKED

    # result in {PASS, DEFERRED-TO-UAT} and halt is null.
    return ADVANCE


def translate_build_step_verdict(
    terminal: str,
    halt: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """Translate build-step's Step 7 terminal strings into a verdict.json dict.

    This encodes the EMIT-side translator (the thin mapping documented in
    build-step SKILL.md Step 7). It is a translation, NOT adoption of
    review-deep's aggregate.py.

    Terminal-string -> ``result`` mapping:

    * ``"PASS"``      / ``"APPROVED"``  -> ``"PASS"``
    * ``"NEEDS WORK"`` (a SPACE) / ``"REJECTED"`` -> ``"NEEDS-WORK"`` (a HYPHEN)
    * ``"DEFERRED-TO-UAT"`` (emitted only by the ``--reviewers deep`` lane,
      passing review-deep's aggregated verdict through) passes through unchanged.

    ``halt`` is carried through after validation: a non-null halt that is not in
    :data:`VALID_HALTS` raises ``ValueError`` (caught at EMIT time, not at
    consume time -- the consumer's job is to fail closed, the producer's job is
    to emit a well-formed sentinel).

    Returns a dict missing only ``timestamp`` (the caller stamps that), e.g.::

        {"result": "PASS", "halt": None, "summary": "..."}
    """
    mapping = {
        "PASS": "PASS",
        "APPROVED": "PASS",
        "NEEDS WORK": "NEEDS-WORK",  # space -> hyphen
        "REJECTED": "NEEDS-WORK",
        "DEFERRED-TO-UAT": "DEFERRED-TO-UAT",
    }
    key = (terminal or "").strip()
    if key not in mapping:
        raise ValueError(
            f"unknown build-step terminal string {terminal!r}; "
            f"expected one of {sorted(mapping)}"
        )
    result = mapping[key]

    if halt is not None and halt not in VALID_HALTS:
        raise ValueError(
            f"unknown halt sentinel {halt!r}; expected one of {sorted(VALID_HALTS)} "
            f"or None"
        )

    return {"result": result, "halt": halt, "summary": summary}
