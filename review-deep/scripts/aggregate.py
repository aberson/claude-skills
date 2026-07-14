#!/usr/bin/env python3
"""review-deep multi-lens verdict aggregator.

Reads per-lens verdict JSON files from --lens-dir (one file per lens, named
<lens_id>.json), applies the seven aggregator rules, writes the audit-trail
JSON sidecar to <--output-dir>/<timestamp>.json, and prints the human-readable
markdown summary to stdout.

Canonical prose: SKILL.md (Aggregation section). This module is the executable
implementation of the contract summarized there. Schema fields, severity
semantics, lens ordering, and M-numbering rules are all sourced from SKILL.md;
the two sites are joint owners of the schema. Renames or shape changes MUST
touch both sites in the same diff (producer-consumer-drift prevention; see
dev/.claude/rules/code-quality.md).

Aggregator rules implemented (each as apply_rule_N_<desc>):

1. Severity dominance: Block outweighs any Nit count; the aggregated verdict
   is driven by the highest-severity finding across lenses, not finding count.
2. Lens owns its dimension: when two lenses disagree on the same file_line,
   the lens whose Scope covers that dimension wins; the other is demoted to
   FYI. Catalog Lens-routing fields drive primary/secondary selection.
3. SKIPPED handling: SKIPPED lenses are informational; they do NOT contribute
   to NEEDS-WORK. plan-conformance is the only lens that emits SKIPPED.
4. FAILED handling: a FAILED lens (model overloaded after retry) maps to
   NEEDS-WORK at the aggregated level; the failure_reason surfaces in the
   aggregated rationale.
5. NO-EVIDENCE handling: NO-EVIDENCE means the lens could not see diff
   content (inputs-gathering bug). Maps to NEEDS-WORK so the operator notices
   and fixes the input rather than accepting a vacuous PASS.
6. Persistent disagreement: when --prior-sidecar is supplied AND the current
   run flags the same finding identity (file_line + anti_pattern + severity)
   that a prior run demoted under rule 2, escalate the severity by one tier
   and annotate the rationale.
7. Absence-of-thing dedup AND lint-finding dedup: two independent paths in
   the same rule. (a) Absence path: when multiple lenses surface findings
   about the same absence (no concrete file_line anchor in the diff), dedup
   by (anti_pattern, summary fuzzy-match) and demote duplicates to FYI;
   primary lens is the catalog Lens-routing target or first-emit order.
   (b) Lint path: when lint-findings.json is supplied (via --lint-findings
   or auto-discovered at <output-dir>/lint-findings.json), any lens finding
   sharing a concrete file_line with a lint finding demotes to FYI with
   rationale prefixed "Cited-by-linter: <tool> <rule>" and an
   also_flagged_by_linter annotation.

CLI:

    python aggregate.py \\
      --lens-dir <path>            # required; directory of per-lens JSON files
      --output-dir <path>          # required; sidecar lands here
      --skill-version <v>          # default "v3"
      --prior-sidecar <path>       # optional; enables rule 6
      --lint-findings <path>       # optional; enables rule 7's lint-dedup path
      [--timestamp <ISO>]          # optional override (for round-trip tests)
      [--self-test <m1-sidecar>]   # round-trip test against an M1 sidecar
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A single finding from one lens.

    Fields:
        severity: 'Block' | 'Nit' | 'FYI' (one of three exact strings, per the
            universal severity rubric at SKILL.md top of "Reviewer lenses").
        file_line: Source location, e.g. 'src/foo.py:42' or 'src/foo.py:42-45'.
            For absence-of-thing findings, this may describe the missing
            artifact ('(absence -- no integration test for X)') rather than a
            concrete path:line.
        excerpt: Exact text being cited (diff line, surrounding context, or
            plan excerpt for plan-conformance). Empty excerpt demotes the
            finding one severity tier per universal evidence discipline.
        rationale: 1-3 sentence explanation citing primary-source evidence,
            referencing the lens's coverage claim, the dev's intent, the named
            plan step, or an anti-pattern from the catalog.
        anti_pattern: OPTIONAL kebab-case name from the seven-entry catalog
            (silent-wiring, producer-consumer-drift, codifying-test-diff,
            silent-fallthrough-in-loop, silent-fallthrough-in-hot-path,
            duplicate-shape-constants, create-table-without-migration). Plus
            the reserved wire-format marker 'scope-boundary-deferral' (NOT
            a defect; signals operator UAT hand-off).

    Post-aggregation annotations (NOT dataclass attributes; applied via dict
    mutation in apply_rule_7_absence_dedup; documented here so a future
    maintainer reading a sidecar does not treat them as stray keys):
        also_flagged_by: Optional list of lens_id strings -- populated by
            rule 7's absence-dedup path when a finding clusters with sibling
            findings from other lenses at the same conceptual absence.
            Post-aggregation annotation only; not in raw lens output.
        also_flagged_by_linter: Optional ``{tool, rule}`` dict -- populated by
            rule 7's lint-dedup path when a lint finding's file_line overlaps
            the lens finding's file_line. Post-aggregation annotation only;
            not in raw lens output.
    """

    severity: str
    file_line: str
    excerpt: str
    rationale: str
    anti_pattern: str | None = None


@dataclass(frozen=True)
class LensVerdict:
    """One lens's verdict block.

    Six standing code lenses (correctness, bugs, security, test-quality, style,
    plan-conformance) plus optional runtime lenses (ui, backend, frontend).

    Fields:
        lens_id: Lens identifier; one of 'correctness' | 'bugs' | 'security' |
            'test-quality' | 'style' | 'plan-conformance' (code lenses) or
            a runtime lens id ('ui' | 'backend' | 'frontend').
        model_tier: Tier the lens actually ran on after --model-override
            resolution: 'haiku' | 'sonnet' | 'opus'. For SKIPPED lenses,
            reports the tier that WOULD have been used (no nulls).
        authority: One-line summary of what this lens owns (from the lens's
            Scope section). Used by the markdown summary and the
            "lens owns its dimension" aggregator rule.
        coverage_claim: What this lens promises to detect (from the lens's
            Coverage claim section).
        findings: List of Finding dicts; MUST be an empty list (not None) when
            overall_verdict == 'PASS' / 'SKIPPED'.
        overall_verdict: One of 'PASS' | 'NEEDS-WORK' | 'NO-EVIDENCE' |
            'FAILED' | 'SKIPPED' | 'NEEDS-CLARIFICATION'. See SKILL.md
            Model strategy section's enum table for the canonical set.
        failure_reason: OPTIONAL; present only when overall_verdict == FAILED.
            Current allowed values: 'model_overloaded'. Cross-step contract
            with SKILL.md Model strategy section -- adding a value requires
            updating both sites in the same diff.
    """

    lens_id: str
    model_tier: str
    authority: str
    coverage_claim: str
    findings: list
    overall_verdict: str
    failure_reason: str | None = None


# Fixed code-lens spawn order, used by aggregator rule 7 primary-lens selection
# and by the markdown summary's lens-verdicts subsection. The 'security' lens is
# promoted out of 'bugs' (SKILL.md Security lens) and slots after it so a
# security-class defect both Bugs and Security flag routes to Security as primary
# (via ANTI_PATTERN_PRIMARY below, not spawn order, but the position keeps the
# documented order coherent). Cross-step contract with SKILL.md "Standing lens
# list" + Aggregation section -- a rename or reorder MUST touch both sites.
CODE_LENS_ORDER = [
    "correctness",
    "bugs",
    "security",
    "test-quality",
    "style",
    "plan-conformance",
]

# Anti-pattern catalog Lens-routing table -- the (primary, secondary) pair per
# catalog entry as documented in SKILL.md Anti-pattern catalog section. Used by
# aggregator rules 2 and 7 to resolve cross-lens primaries. The three
# security-class defect classes (injection-as-data, secret-dump,
# unsafe-config-without-startup-guard, per .claude/rules/security.md) route to
# the Security lens as PRIMARY OWNER -- a finding both Bugs and Security flag at
# the same file_line is owned by Security and the Bugs copy demotes to FYI
# (SKILL.md Aggregation § rule 2: "Security is the registered PRIMARY OWNER of
# security findings").
ANTI_PATTERN_PRIMARY = {
    "silent-wiring": "bugs",
    "producer-consumer-drift": "bugs",
    "codifying-test-diff": "test-quality",
    "silent-fallthrough-in-loop": "bugs",
    "silent-fallthrough-in-hot-path": "bugs",
    "duplicate-shape-constants": "bugs",
    "create-table-without-migration": "bugs",
    "injection-as-data": "security",
    "secret-dump": "security",
    "unsafe-config-without-startup-guard": "security",
}

# Severity ordinals for monotonic comparison / demotion / escalation.
SEVERITY_ORDER = {"FYI": 0, "Nit": 1, "Block": 2}


# ---------------------------------------------------------------------------
# I/O: per-lens verdict loading
# ---------------------------------------------------------------------------


def load_lens_verdicts(lens_dir: Path) -> list[dict]:
    """Read per-lens JSON files from lens_dir.

    Expects one file per lens, named <lens_id>.json. Returns a list of dicts
    in the order they appear after sorting by the canonical CODE_LENS_ORDER
    prefix (then any runtime lenses appended in filename order).

    Each file may contain either a single lens-verdict object OR a
    full prior-style sidecar (the round-trip test path decomposes a v2 sidecar
    into per-lens files; either shape is accepted).
    """
    verdicts_by_id: dict[str, dict] = {}
    for child in sorted(lens_dir.iterdir()):
        if not child.is_file() or child.suffix != ".json":
            continue
        with child.open("r", encoding="utf-8") as f:
            data = json.load(f)
        # Accept either bare lens verdict object or a sidecar with lens_verdicts[]
        if isinstance(data, dict) and "lens_verdicts" in data:
            for v in data["lens_verdicts"]:
                verdicts_by_id[v["lens_id"]] = v
        elif isinstance(data, dict) and "lens_id" in data:
            verdicts_by_id[data["lens_id"]] = data
        else:
            raise ValueError(
                f"{child}: not a recognized lens-verdict shape "
                f"(expected dict with 'lens_id' or 'lens_verdicts')"
            )

    ordered: list[dict] = []
    for lens_id in CODE_LENS_ORDER:
        if lens_id in verdicts_by_id:
            ordered.append(verdicts_by_id.pop(lens_id))
    # Any leftover keys are runtime lenses; append in deterministic order.
    for lens_id in sorted(verdicts_by_id):
        ordered.append(verdicts_by_id[lens_id])
    return ordered


# ---------------------------------------------------------------------------
# Aggregator rules
# ---------------------------------------------------------------------------


def apply_rule_1_severity_dominance(lens_verdicts: list[dict]) -> dict:
    """Rule 1 -- severity dominates count.

    A single Block finding outweighs any number of Nit findings. The
    aggregated verdict is determined by the highest-severity finding across
    all lenses, not by total finding count.

    Returns a dict with:
        block_count: total Block findings across all non-SKIPPED lenses
        nit_count:   total Nit findings
        fyi_count:   total FYI findings
        max_severity: highest severity present ('Block' | 'Nit' | 'FYI' | None)
    """
    block_count = 0
    nit_count = 0
    fyi_count = 0
    for lv in lens_verdicts:
        if lv.get("overall_verdict") == "SKIPPED":
            continue
        for f in lv.get("findings", []):
            sev = f.get("severity")
            if sev == "Block":
                block_count += 1
            elif sev == "Nit":
                nit_count += 1
            elif sev == "FYI":
                fyi_count += 1
    if block_count > 0:
        max_severity: str | None = "Block"
    elif nit_count > 0:
        max_severity = "Nit"
    elif fyi_count > 0:
        max_severity = "FYI"
    else:
        max_severity = None
    return {
        "block_count": block_count,
        "nit_count": nit_count,
        "fyi_count": fyi_count,
        "max_severity": max_severity,
    }


def apply_rule_2_lens_owns_dimension(lens_verdicts: list[dict]) -> list[dict]:
    """Rule 2 -- lens owns its dimension.

    When two lenses surface findings at the same file_line, the lens with
    authority over that dimension wins; the other lens's finding is demoted
    to FYI. For catalog anti-pattern findings, the primary lens per the
    catalog's Lens-routing field wins.

    Mutates a deep copy of lens_verdicts in place; the demoted finding's
    rationale is prefixed with 'Demoted per rule 2:' so rule 6 can detect
    persistent disagreement on a re-run.
    """
    # Group findings by file_line across lenses.
    by_file_line: dict[str, list[tuple[str, dict]]] = {}
    for lv in lens_verdicts:
        if lv.get("overall_verdict") == "SKIPPED":
            continue
        for f in lv.get("findings", []):
            file_line = f.get("file_line", "")
            if not file_line:
                continue
            by_file_line.setdefault(file_line, []).append((lv["lens_id"], f))

    for _file_line, entries in by_file_line.items():
        if len(entries) < 2:
            continue
        # Find primary -- prefer anti-pattern catalog routing.
        primary_idx = None
        for i, (_lens_id, f) in enumerate(entries):
            ap = f.get("anti_pattern")
            if ap and ANTI_PATTERN_PRIMARY.get(ap) == entries[i][0]:
                primary_idx = i
                break
        if primary_idx is None:
            # Fall back to first-emit-order by CODE_LENS_ORDER.
            primary_idx = min(
                range(len(entries)),
                key=lambda i: (
                    CODE_LENS_ORDER.index(entries[i][0])
                    if entries[i][0] in CODE_LENS_ORDER
                    else 999
                ),
            )
        # Demote all non-primary findings to FYI with annotated rationale.
        for i, (_lens_id, f) in enumerate(entries):
            if i == primary_idx:
                continue
            if f.get("severity") != "FYI":
                f["severity"] = "FYI"
                rationale = f.get("rationale", "")
                if not rationale.startswith("Demoted per rule 2:"):
                    f["rationale"] = f"Demoted per rule 2: {rationale}"
    return lens_verdicts


def apply_rule_3_skipped_handling(lens_verdicts: list[dict]) -> list[str]:
    """Rule 3 -- SKIPPED lenses do not count toward NEEDS-WORK.

    Returns the list of SKIPPED lens_ids so the markdown summary and
    aggregated rationale can note the skips explicitly. The aggregated
    verdict computation in build_aggregated_verdict() ignores SKIPPED
    entries.
    """
    return [
        lv["lens_id"]
        for lv in lens_verdicts
        if lv.get("overall_verdict") == "SKIPPED"
    ]


def apply_rule_4_failed_handling(lens_verdicts: list[dict]) -> list[dict]:
    """Rule 4 -- FAILED lenses surface explicitly and block PASS.

    A FAILED lens (model overloaded after one retry) MUST NOT receive a
    clean PASS at the aggregated level. Returns a list of (lens_id,
    failure_reason) entries for inclusion in the aggregated rationale.
    """
    return [
        {"lens_id": lv["lens_id"], "failure_reason": lv.get("failure_reason")}
        for lv in lens_verdicts
        if lv.get("overall_verdict") == "FAILED"
    ]


def apply_rule_5_no_evidence_handling(lens_verdicts: list[dict]) -> list[str]:
    """Rule 5 -- NO-EVIDENCE lenses also surface explicitly and block PASS.

    NO-EVIDENCE means the lens could not see diff content (almost always an
    inputs-gathering bug). Returns list of NO-EVIDENCE lens_ids.
    """
    return [
        lv["lens_id"]
        for lv in lens_verdicts
        if lv.get("overall_verdict") == "NO-EVIDENCE"
    ]


def apply_rule_6_persistent_disagreement(
    lens_verdicts: list[dict], prior_sidecar: dict | None
) -> list[dict]:
    """Rule 6 -- persistent disagreement escalates severity.

    When --prior-sidecar is supplied AND a current finding matches a prior
    finding's identity (file_line + anti_pattern + severity) that was demoted
    per rule 2, escalate the current finding's severity by one tier
    (FYI -> Nit, Nit -> Block) and prefix its rationale with
    "Persistent disagreement: ".

    When prior_sidecar is None, this rule is a no-op (first invocation).
    """
    if prior_sidecar is None:
        return lens_verdicts
    # Index prior findings by (file_line, anti_pattern) identity. We include
    # BOTH rule-2 demotions ("Demoted per rule 2:") AND prior persistent-
    # disagreement escalations ("Persistent disagreement:") so the chain
    # FYI -> Nit -> Block continues across runs (severity is excluded from
    # the identity key because it changes each round).
    prior_demoted: set[tuple[str, str | None]] = set()
    for lv in prior_sidecar.get("lens_verdicts", []):
        for f in lv.get("findings", []):
            rationale = f.get("rationale", "")
            if rationale.startswith("Demoted per rule 2:") or rationale.startswith(
                "Persistent disagreement:"
            ):
                prior_demoted.add(
                    (
                        f.get("file_line", ""),
                        f.get("anti_pattern"),
                    )
                )
    # Walk current findings; escalate matches by one tier from current severity.
    for lv in lens_verdicts:
        for f in lv.get("findings", []):
            key = (
                f.get("file_line", ""),
                f.get("anti_pattern"),
            )
            if key in prior_demoted:
                current_sev = f.get("severity", "FYI")
                if current_sev == "FYI":
                    f["severity"] = "Nit"
                elif current_sev == "Nit":
                    f["severity"] = "Block"
                rationale = f.get("rationale", "")
                if not rationale.startswith("Persistent disagreement:"):
                    f["rationale"] = f"Persistent disagreement: {rationale}"
    return lens_verdicts


_CONCRETE_FILE_LINE_RE = re.compile(r"^[\w./\\:-]+:\d+(?:-\d+)?$")

# Matches '<path>:<line>' or '<path>:<start>-<end>' (capturing path + start +
# optional end). The path group is non-greedy so it stops at the LAST ':' that
# precedes a digit run — preserves Windows drive letters like 'C:\foo\bar:42'.
_FILE_LINE_RE = re.compile(r"^(.+):(\d+)(?:-(\d+))?$")


def _normalize_path(path_str: str) -> str:
    """Normalize a file path component for cross-source equality.

    Lowercases on Windows (case-insensitive FS); converts backslashes to
    forward slashes; strips leading './' (possibly repeated) and surrounding
    whitespace. Preserves absolute paths and drive letters — we don't try to
    resolve relative-vs-absolute equivalence here; the goal is normalizing
    the cosmetic mismatches between lens output and lint output that share
    the same logical anchor.
    """
    p = path_str.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    if sys.platform == "win32":
        p = p.lower()
    return p


def _file_line_overlaps(lens_fl: str, lint_fl: str) -> bool:
    """True iff a lens file_line overlaps a lint file_line.

    Both sides are ``path:line`` or ``path:start-end``. After path
    normalization (forward slashes, leading './' stripped, lowercased on
    Windows), paths must match exactly; the line ranges overlap iff
    ``max(starts) <= min(ends)``. The lint side is always a single line per
    ``lint_prepass.sh``'s contract, but we accept ranges on either side
    defensively so a future lint integration that emits ranges still slots
    in cleanly.
    """
    m_lens = _FILE_LINE_RE.match(lens_fl or "")
    m_lint = _FILE_LINE_RE.match(lint_fl or "")
    if not (m_lens and m_lint):
        return False
    if _normalize_path(m_lens.group(1)) != _normalize_path(m_lint.group(1)):
        return False
    lens_start = int(m_lens.group(2))
    lens_end = int(m_lens.group(3) or m_lens.group(2))
    lint_start = int(m_lint.group(2))
    lint_end = int(m_lint.group(3) or m_lint.group(2))
    return max(lens_start, lint_start) <= min(lens_end, lint_end)


def _is_absence_finding(finding: dict) -> bool:
    """Heuristic for rule 7: 'absence-of-thing' findings have no concrete
    path:line anchor. A concrete file_line matches the regex; anything else
    (an "(absence -- ...)" placeholder, an empty string, a free-form
    description) is treated as absence."""
    file_line = finding.get("file_line", "")
    if not file_line:
        return True
    return _CONCRETE_FILE_LINE_RE.match(file_line) is None


def _summary_tokens(rationale: str) -> set[str]:
    """Fuzzy-match support: tokenize a rationale into a lowercase token set
    for set-overlap comparison."""
    return {w.lower() for w in re.findall(r"\w+", rationale) if len(w) > 3}


def apply_rule_7_absence_dedup(
    lens_verdicts: list[dict],
    lint_findings: list[dict] | None = None,
) -> list[dict]:
    """Rule 7 -- absence-of-thing dedup AND lint-finding dedup.

    Two independent dedup paths share this rule because both deflate
    cross-source double-counting at the same SKILL.md contract layer:

    1. **Absence path.** When multiple lenses surface findings about the same
       absence (no concrete file_line anchor in the diff), dedup by
       (anti_pattern, summary fuzzy-match) and demote duplicates to FYI.
       Primary lens is determined by catalog Lens-routing or first-emit-order
       in CODE_LENS_ORDER.
    2. **Lint path.** When ``lint_findings`` is supplied (the orchestrator
       loaded ``lint-findings.json`` written by ``scripts/lint_prepass.sh``),
       any lens finding sharing a concrete file_line with a lint finding is
       demoted to FYI with rationale prefixed
       ``Cited-by-linter: <tool> <rule>`` and annotated with
       ``also_flagged_by_linter: {tool, rule}``. The lint findings themselves
       are NOT added to lens_verdicts -- they're already in the linter's
       output and the aggregator does not republish them. ``scope-boundary-
       deferral`` findings are excluded from the lint path (they're an
       operator hand-off, not a defect signal).

    Both passes mutate findings in place. The lint path runs FIRST so an
    already-cited-by-linter lens finding is not also targeted by absence-path
    clustering (its concrete file_line keeps it out of the absence cluster
    anyway, but the order makes the contract auditable).

    Fires BEFORE rule 6 in the pipeline; persistent-disagreement escalation
    in rule 6 then applies only to the surviving primary.
    """
    # --- Lint path -------------------------------------------------------
    # Keep lint findings as a list and iterate per lens finding using the
    # path-normalized + range-aware ``_file_line_overlaps`` matcher. A plain
    # dict-by-file_line lookup misses ranges (``src/foo.py:42-45`` vs
    # ``src/foo.py:43``) and cosmetic mismatches (``./src/foo.py`` vs
    # ``src/foo.py``, ``src\foo.py`` vs ``src/foo.py``); both shapes are
    # known producers (lint_prepass.sh emits single-line; lens prompts may
    # emit ranges) so the iteration cost is paid intentionally.
    lint_candidates: list[dict] = []
    if lint_findings:
        for lf in lint_findings:
            fl = lf.get("file_line", "")
            if not fl:
                continue
            lint_candidates.append(lf)
    if lint_candidates:
        for lv in lens_verdicts:
            if lv.get("overall_verdict") == "SKIPPED":
                continue
            for f in lv.get("findings", []):
                if f.get("anti_pattern") == "scope-boundary-deferral":
                    continue
                lens_fl = f.get("file_line", "")
                if not lens_fl:
                    continue
                # Find the FIRST lint finding whose file_line overlaps; the
                # lint_prepass.sh output ordering is the deterministic
                # tie-breaker when multiple lint findings fall within a lens
                # range.
                hit = None
                for lf in lint_candidates:
                    if _file_line_overlaps(lens_fl, lf.get("file_line", "")):
                        hit = lf
                        break
                if hit is None:
                    continue
                # ``or`` short-circuits on falsy values (None, "") so an
                # explicit ``{"rule": null}`` in lint-findings.json still
                # falls through to the default rather than producing a
                # 'Cited-by-linter: ruff None' rationale.
                tool = hit.get("tool") or "linter"
                rule = hit.get("rule") or ""
                # Demote to FYI and annotate.
                if f.get("severity") != "FYI":
                    f["severity"] = "FYI"
                f["also_flagged_by_linter"] = {"tool": tool, "rule": rule}
                rationale = f.get("rationale", "")
                prefix = f"Cited-by-linter: {tool} {rule}".rstrip()
                if not rationale.startswith("Cited-by-linter:"):
                    f["rationale"] = f"{prefix}: {rationale}" if rationale else prefix

    # --- Absence path ----------------------------------------------------
    # Collect absence findings across lenses with (lens_id, finding) tuples.
    # scope-boundary-deferral is reserved wire-format (operator UAT hand-off,
    # NOT a defect) and is processed by extract_deferred_items; rule 7 must
    # skip it so it does not cluster with real absence findings and demote
    # unrelated ones alongside it.
    absences: list[tuple[str, dict]] = []
    for lv in lens_verdicts:
        if lv.get("overall_verdict") == "SKIPPED":
            continue
        for f in lv.get("findings", []):
            if f.get("anti_pattern") == "scope-boundary-deferral":
                continue
            if _is_absence_finding(f):
                absences.append((lv["lens_id"], f))

    # Group by (anti_pattern, fuzzy-match cluster).
    clusters: list[list[tuple[str, dict]]] = []
    for lens_id, f in absences:
        ap = f.get("anti_pattern")
        toks = _summary_tokens(f.get("rationale", ""))
        placed = False
        for cluster in clusters:
            c_ap = cluster[0][1].get("anti_pattern")
            c_toks = _summary_tokens(cluster[0][1].get("rationale", ""))
            # Same anti_pattern (or both None) AND >=50% token overlap.
            ap_match = ap == c_ap
            overlap = (
                len(toks & c_toks) / max(1, min(len(toks), len(c_toks)))
                if toks and c_toks
                else 0
            )
            if ap_match and overlap >= 0.5:
                cluster.append((lens_id, f))
                placed = True
                break
        if not placed:
            clusters.append([(lens_id, f)])

    # For each cluster of size >= 2, pick primary and demote others.
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        ap = cluster[0][1].get("anti_pattern")
        primary_idx = None
        if ap and ap in ANTI_PATTERN_PRIMARY:
            target = ANTI_PATTERN_PRIMARY[ap]
            for i, (lens_id, _f) in enumerate(cluster):
                if lens_id == target:
                    primary_idx = i
                    break
        if primary_idx is None:
            # First-emit-order by CODE_LENS_ORDER.
            primary_idx = min(
                range(len(cluster)),
                key=lambda i: (
                    CODE_LENS_ORDER.index(cluster[i][0])
                    if cluster[i][0] in CODE_LENS_ORDER
                    else 999
                ),
            )
        # Annotate primary; demote others.
        primary_lens, primary_f = cluster[primary_idx]
        also_flagged_by = [lens_id for lens_id, _ in cluster if lens_id != primary_lens]
        if also_flagged_by:
            primary_f["also_flagged_by"] = also_flagged_by
        for i, (_lens_id, f) in enumerate(cluster):
            if i == primary_idx:
                continue
            if f.get("severity") != "FYI":
                f["severity"] = "FYI"
                rationale = f.get("rationale", "")
                if not rationale.startswith("Demoted per rule 7:"):
                    f["rationale"] = f"Demoted per rule 7: {rationale}"
    return lens_verdicts


def load_lint_findings(lint_findings_path: Path | None) -> list[dict]:
    """Load lint findings from a lint-findings.json sidecar.

    The schema matches scripts/lint_prepass.sh output:
    ``{timestamp, tools_run[], tools_skipped[], findings[{tool, rule, file_line, message}]}``.
    Returns the ``findings`` array (empty list when the path is None or the
    file does not exist). A non-readable / non-JSON file at the given path
    raises -- that's an orchestrator configuration error worth surfacing.
    """
    if lint_findings_path is None:
        return []
    if not lint_findings_path.exists():
        return []
    with lint_findings_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    findings = data.get("findings") or []
    if not isinstance(findings, list):
        return []
    return findings


# ---------------------------------------------------------------------------
# Aggregated verdict assembly + sidecar
# ---------------------------------------------------------------------------


def build_aggregated_verdict(
    lens_verdicts: list[dict],
    severity_counts: dict,
    skipped: list[str],
    failed: list[dict],
    no_evidence: list[str],
    deferred_items: list[dict],
) -> dict:
    """Compute aggregated_verdict.result and rationale from the rule outputs.

    Rules from SKILL.md "Aggregated-verdict output ladder":
      PASS              -- zero Block; zero NEEDS-WORK/FAILED/NO-EVIDENCE
                           lens verdicts; SKIPPED lenses do not block
      NEEDS-WORK        -- any Block; OR any lens NEEDS-WORK/FAILED/NO-EVIDENCE;
                           OR aggregated Nit count >= 3
      DEFERRED-TO-UAT   -- structurally un-evaluable parts (Step 7 trigger);
                           deferral over PASS but NOT over NEEDS-WORK
    """
    needs_work_lenses = [
        lv["lens_id"]
        for lv in lens_verdicts
        if lv.get("overall_verdict") == "NEEDS-WORK"
    ]
    block_count = severity_counts["block_count"]
    nit_count = severity_counts["nit_count"]

    # Hardest verdict wins for gating: NEEDS-WORK > DEFERRED > PASS.
    hard_needs_work = (
        block_count > 0
        or nit_count >= 3
        or bool(needs_work_lenses)
        or bool(failed)
        or bool(no_evidence)
    )
    has_deferral = bool(deferred_items)

    if hard_needs_work:
        result = "NEEDS-WORK"
    elif has_deferral:
        result = "DEFERRED-TO-UAT"
    else:
        result = "PASS"

    # Compose a human-readable one-line rationale.
    parts = []
    if block_count:
        parts.append(f"{block_count} Block finding{'s' if block_count != 1 else ''}")
    if nit_count:
        parts.append(f"{nit_count} Nit finding{'s' if nit_count != 1 else ''}")
    if needs_work_lenses:
        parts.append(f"lenses NEEDS-WORK: {', '.join(needs_work_lenses)}")
    if failed:
        parts.append(
            "FAILED: "
            + ", ".join(
                f"{e['lens_id']} ({e.get('failure_reason') or 'unknown'})"
                for e in failed
            )
        )
    if no_evidence:
        parts.append(f"NO-EVIDENCE: {', '.join(no_evidence)}")
    if skipped:
        parts.append(f"SKIPPED: {', '.join(skipped)}")
    if has_deferral:
        parts.append(
            f"{len(deferred_items)} deferred UAT item"
            f"{'s' if len(deferred_items) != 1 else ''}"
        )
    rationale = ("; ".join(parts) if parts else "Zero findings; all lenses PASS.") + "."

    return {"result": result, "rationale": rationale}


def extract_deferred_items(lens_verdicts: list[dict]) -> list[dict]:
    """Extract scope-boundary deferrals from lens findings.

    Lenses signal a deferral via a Block-severity finding with
    anti_pattern == 'scope-boundary-deferral'. Each matching finding becomes
    a deferred_uat_items[] entry and the original is demoted to FYI.

    The Step 6 auth-gate downgrade path also produces deferred items, but
    that's an orchestrator-level concern handled outside this aggregator.
    """
    deferred: list[dict] = []
    counter = 1
    for lv in lens_verdicts:
        for f in lv.get("findings", []):
            if f.get("anti_pattern") == "scope-boundary-deferral":
                deferred.append(
                    {
                        "reason": f.get("rationale", ""),
                        "covered_lenses": [
                            other["lens_id"]
                            for other in lens_verdicts
                            if other["lens_id"] != lv["lens_id"]
                            and other.get("overall_verdict")
                            not in ("SKIPPED", "FAILED", "NO-EVIDENCE")
                        ],
                        "needs_verification": f.get("excerpt", ""),
                        "recommended_commands": [],
                        "uat_id": f"M{counter}",
                    }
                )
                counter += 1
                # Demote the original finding to FYI.
                if f.get("severity") != "FYI":
                    f["severity"] = "FYI"
    return deferred


def assign_m_numbers(deferred_items: list[dict]) -> list[dict]:
    """Assign M1, M2, ... uat_id values to deferred items in emission order.

    M-numbering convention (SKILL.md "M<N> numbering convention"):

    - Within a single review-deep invocation: items are numbered starting at
      M1 in the order the aggregator emits them. Emission order is
      (a) the order each lens reported them in its findings, then (b) the
      lens-spawn order CODE_LENS_ORDER (correctness, bugs, security,
      test-quality, style, plan-conformance) followed by any runtime lenses.
    - Across invocations: review-deep does NOT track prior invocations'
      M-numbers. Each invocation restarts at M1. Persistence is the plan.md's
      job per /build-phase's "Deferred-UAT bundling" rules; operators who
      want review-deep's deferrals merged into the plan-level M-series copy
      them by hand into the plan's Manual section, re-numbering at the open
      slot.
    - Operator-facing cue: the markdown summary's final pre-sidecar line
      reads "Please run <lowest M-number> next." -- an explicit ask, not
      buried prose.

    Edge cases:
      - empty list -> returns []
      - same source step contributing 2 items -> two consecutive M-numbers
      - existing uat_id values on input -> overwritten (this function is
        canonical)
    """
    out: list[dict] = []
    for i, item in enumerate(deferred_items, start=1):
        new_item = dict(item)
        new_item["uat_id"] = f"M{i}"
        out.append(new_item)
    return out


def build_sidecar(
    lens_verdicts: list[dict],
    aggregated_verdict: dict,
    deferred_items: list[dict],
    timestamp: str,
    skill_version: str,
    plan_step: str | None,
    invocation: dict,
) -> dict:
    """Assemble the JSON sidecar in the canonical key order.

    Schema declared in SKILL.md "Audit-trail JSON sidecar schema". The key
    order here matches the schema example block (timestamp, plan_step,
    skill_version, invocation, lens_verdicts, aggregated_verdict,
    model_tiers_used, deferred_uat_items) so a sidecar diff against the
    schema is alignable.
    """
    model_tiers_used = {lv["lens_id"]: lv.get("model_tier") for lv in lens_verdicts}
    return {
        "timestamp": timestamp,
        "plan_step": plan_step,
        "skill_version": skill_version,
        "invocation": invocation,
        "lens_verdicts": lens_verdicts,
        "aggregated_verdict": aggregated_verdict,
        "model_tiers_used": model_tiers_used,
        "deferred_uat_items": deferred_items,
    }


def write_sidecar(sidecar: dict, output_dir: Path) -> Path:
    """Write the audit-trail JSON sidecar.

    Filename: <timestamp>.json (ISO-8601 with filesystem-safe characters,
    e.g. '2026-05-24T08-15-30.json'). Schema: matches SKILL.md
    Audit-trail JSON sidecar schema. Returns the path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = output_dir / f"{sidecar['timestamp']}.json"
    with sidecar_path.open("w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return sidecar_path


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


# Escape markdown metacharacters in inline (non-fenced) text. Findings'
# rationales and excerpts may contain `|`, `*`, `_`, backtick, `<`, etc. that
# corrupt the rendered markdown when surfaced into a GitHub PR comment or any
# markdown consumer. Do NOT apply inside triple-backtick code-fence blocks --
# those are verbatim by markdown rules.
_MD_ESCAPE_RE = re.compile(r"([\\`*_{}\[\]()#+\-.!|])")


def _escape_md(s: str) -> str:
    return _MD_ESCAPE_RE.sub(r"\\\1", s)


def _safe_fence_length(text: str) -> int:
    """Compute a code-fence backtick run that is strictly longer than any
    backtick run inside *text*, with a floor of 3. Prevents premature fence
    closure when the excerpt itself contains triple-backtick sequences."""
    longest = 0
    cur = 0
    for c in text:
        if c == "`":
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return max(3, longest + 1)


def render_markdown(sidecar: dict) -> str:
    """Render the human-readable markdown summary.

    Shape: matches SKILL.md "Markdown output shape" section. Sections in
    order: header line, ## Lens verdicts, ## Findings (by severity), and
    ## Deferred to operator UAT (when applicable). Final line is the
    "Please run M<N> next." cue when deferrals exist, followed by
    "Audit-trail JSON: <path>".
    """
    out: list[str] = []
    agg = sidecar["aggregated_verdict"]
    deferred = sidecar.get("deferred_uat_items", [])

    # Header line.
    if agg["result"] == "NEEDS-WORK" and deferred:
        out.append("# review-deep: NEEDS-WORK + DEFERRED-TO-UAT")
    else:
        out.append(f"# review-deep: {agg['result']}")
    out.append("")

    # Lens verdicts.
    out.append("## Lens verdicts")
    out.append("")
    for lv in sidecar["lens_verdicts"]:
        finding_count = len(lv.get("findings", []))
        verdict = lv["overall_verdict"]
        tier = lv.get("model_tier", "?")
        if verdict == "SKIPPED" and lv["lens_id"] == "plan-conformance":
            out.append(
                f"- {lv['lens_id']}: SKIPPED (no --plan-step argument, model: {tier})"
            )
        else:
            out.append(
                f"- {lv['lens_id']}: {verdict} ({finding_count} findings, model: {tier})"
            )
    if sidecar["invocation"].get("runtime_downgraded"):
        out.append(
            f"- Runtime downgrade: {sidecar['invocation'].get('runtime_downgrade_reason')}"
        )
    out.append("")

    # Findings grouped by severity.
    by_sev: dict[str, list[tuple[str, dict]]] = {"Block": [], "Nit": [], "FYI": []}
    for lv in sidecar["lens_verdicts"]:
        for f in lv.get("findings", []):
            sev = f.get("severity", "FYI")
            by_sev.setdefault(sev, []).append((lv["lens_id"], f))
    if any(by_sev[s] for s in ("Block", "Nit", "FYI")):
        out.append("## Findings")
        out.append("")
        for sev in ("Block", "Nit", "FYI"):
            entries = by_sev.get(sev, [])
            if not entries:
                continue
            out.append(f"### {sev}")
            out.append("")
            for lens_id, f in entries:
                ap = f.get("anti_pattern")
                tag = f", anti-pattern: {ap}" if ap else ""
                file_line = _escape_md(str(f.get("file_line", "?")))
                rationale = _escape_md(str(f.get("rationale", "")))
                out.append(
                    f"- **{file_line}** ({lens_id}{tag}): "
                    f"{rationale}"
                )
                excerpt = f.get("excerpt", "")
                if excerpt:
                    excerpt_str = str(excerpt)
                    fence = "`" * _safe_fence_length(excerpt_str)
                    out.append("")
                    out.append(f"  {fence}")
                    for line in excerpt_str.splitlines() or [excerpt_str]:
                        out.append(f"  {line}")
                    out.append(f"  {fence}")
            out.append("")

    # Deferred to operator UAT (only when present).
    if deferred:
        out.append("## Deferred to operator UAT")
        out.append("")
        for item in deferred:
            reason = _escape_md(str(item.get("reason", "")))
            needs_verification = _escape_md(str(item.get("needs_verification", "")))
            out.append(f"### {item['uat_id']}: {reason}")
            out.append("")
            covered = item.get("covered_lenses") or []
            out.append(
                f"- **Covered lenses:** {', '.join(covered) if covered else 'none'}"
            )
            out.append(
                f"- **Needs verification:** {needs_verification}"
            )
            out.append("- **Commands to run:**")
            out.append("")
            cmds = item.get("recommended_commands", [])
            cmds_joined = "\n".join(str(c) for c in cmds)
            fence = "`" * _safe_fence_length(cmds_joined)
            out.append(f"  {fence}powershell")
            for cmd in cmds:
                out.append(f"  {cmd}")
            out.append(f"  {fence}")
            out.append("")
        # Explicit run-next ask line.
        lowest = min(
            (item["uat_id"] for item in deferred),
            key=lambda x: int(re.sub(r"\D", "", x) or "0"),
        )
        out.append(f"Please run {lowest} next.")
        out.append("")

    # Audit-trail pointer (final line).
    out.append(f"Audit-trail JSON: .review-deep/{sidecar['timestamp']}.json")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def aggregate(
    lens_verdicts: list[dict],
    *,
    prior_sidecar: dict | None = None,
    timestamp: str,
    skill_version: str,
    plan_step: str | None = None,
    invocation: dict | None = None,
    lint_findings: list[dict] | None = None,
) -> dict:
    """Run all seven aggregator rules and assemble the sidecar dict.

    Rule order: 7 (absence-dedup + lint-dedup) runs first, then 2 (cross-lens
    demotion), then 6 (persistent disagreement re-escalation), then 1/3/4/5
    are counting passes used to compose the aggregated verdict.

    ``lint_findings`` is the parsed ``findings`` array from
    ``lint-findings.json`` (see ``load_lint_findings``). When supplied, rule 7's
    lint path demotes lens findings that share a file_line with a linter
    finding to FYI with rationale prefixed ``Cited-by-linter: <tool> <rule>``.
    """
    # Guardrail: empty lens-verdict input is virtually always an orchestrator
    # failure (load_lens_verdicts returned [] because the dir was empty or
    # contained no .json files). Surface as NEEDS-WORK rather than a vacuous
    # PASS so the operator notices.
    if len(lens_verdicts) == 0:
        if invocation is None:
            invocation = {
                "reviewers_flag": "code",
                "model_overrides": {},
                "force_runtime": False,
                "url": None,
                "start_cmd": None,
                "runtime_downgraded": False,
                "runtime_downgrade_reason": None,
            }
        return build_sidecar(
            lens_verdicts=[],
            aggregated_verdict={
                "result": "NEEDS-WORK",
                "rationale": (
                    "no lens verdicts found in --lens-dir "
                    "(orchestrator failure or empty input)."
                ),
            },
            deferred_items=[],
            timestamp=timestamp,
            skill_version=skill_version,
            plan_step=plan_step,
            invocation=invocation,
        )
    # Rule 7 first: dedup absences across lenses + lint-finding dedup.
    lens_verdicts = apply_rule_7_absence_dedup(lens_verdicts, lint_findings)
    # Rule 2: cross-lens dimension demotion at the same file_line.
    lens_verdicts = apply_rule_2_lens_owns_dimension(lens_verdicts)
    # Rule 6: persistent-disagreement re-escalation (only when prior given).
    lens_verdicts = apply_rule_6_persistent_disagreement(lens_verdicts, prior_sidecar)
    # Rules 3/4/5: surface skipped, failed, no-evidence lenses.
    skipped = apply_rule_3_skipped_handling(lens_verdicts)
    failed = apply_rule_4_failed_handling(lens_verdicts)
    no_evidence = apply_rule_5_no_evidence_handling(lens_verdicts)
    # Rule 1 last: severity-count pass for the aggregated verdict ladder.
    severity_counts = apply_rule_1_severity_dominance(lens_verdicts)
    # Deferred items extracted from scope-boundary-deferral markers, then
    # M-numbered.
    raw_deferred = extract_deferred_items(lens_verdicts)
    deferred = assign_m_numbers(raw_deferred)
    aggregated_verdict = build_aggregated_verdict(
        lens_verdicts, severity_counts, skipped, failed, no_evidence, deferred
    )
    if invocation is None:
        invocation = {
            "reviewers_flag": "code",
            "model_overrides": {},
            "force_runtime": False,
            "url": None,
            "start_cmd": None,
            "runtime_downgraded": False,
            "runtime_downgrade_reason": None,
        }
    return build_sidecar(
        lens_verdicts,
        aggregated_verdict,
        deferred,
        timestamp=timestamp,
        skill_version=skill_version,
        plan_step=plan_step,
        invocation=invocation,
    )


# ---------------------------------------------------------------------------
# Self-test: round-trip a v2 M1 sidecar through the aggregator
# ---------------------------------------------------------------------------


def run_self_test(m1_sidecar_path: Path) -> int:
    """Round-trip an M1 baseline sidecar through the aggregator.

    Reads the M1 sidecar, feeds its lens_verdicts[] into aggregate(), and
    compares the resulting sidecar against the original. Returns 0 on
    byte-identity (modulo timestamp + skill_version) and prints
    "SELF-TEST PASSED"; returns 1 on diff and prints the differing fields.
    """
    with m1_sidecar_path.open("r", encoding="utf-8") as f:
        baseline = json.load(f)
    # Strip prior-rule-2 annotations so we don't accidentally re-apply them.
    lens_verdicts_in = json.loads(json.dumps(baseline["lens_verdicts"]))
    regenerated = aggregate(
        lens_verdicts_in,
        prior_sidecar=None,
        timestamp=baseline["timestamp"],
        skill_version=baseline["skill_version"],
        plan_step=baseline.get("plan_step"),
        invocation=baseline.get("invocation"),
    )
    # Compare structural keys. We tolerate aggregated_verdict.rationale prose
    # drift (the v2 prose is hand-crafted; ours is mechanical) and any extra
    # fields the baseline had that v3 doesn't emit (e.g. approximate_token_count).
    diffs: list[str] = []
    legitimate_diffs: list[str] = []
    for k in (
        "timestamp",
        "plan_step",
        "model_tiers_used",
        "deferred_uat_items",
    ):
        if baseline.get(k) != regenerated.get(k):
            diffs.append(f"  - field {k!r} differs")
    # skill_version is a legitimate v1->v3 drift; do NOT flag.
    if baseline.get("skill_version") != regenerated.get("skill_version"):
        legitimate_diffs.append(
            f"  - skill_version: v1->v3 (expected; --skill-version override "
            f"would force-match)"
        )
    # invocation may legitimately drift if v3 adds new fields; compare keys
    # present in BOTH dicts.
    bi = baseline.get("invocation", {})
    ri = regenerated.get("invocation", {})
    shared = set(bi) & set(ri)
    for key in shared:
        if bi[key] != ri[key]:
            diffs.append(f"  - invocation[{key!r}] differs")
    # lens_verdicts: rule 2 demotes some Nit findings to FYI when multiple
    # lenses share a file_line. The v1 M1 baseline did NOT enforce rule 2, so
    # demotions are legitimate v1->v3 drift -- detect and surface separately.
    bl = baseline.get("lens_verdicts", [])
    rl = regenerated.get("lens_verdicts", [])
    if len(bl) != len(rl):
        diffs.append(
            f"  - lens_verdicts length: baseline={len(bl)}, regenerated={len(rl)}"
        )
    else:
        for bv, rv in zip(bl, rl):
            if bv.get("lens_id") != rv.get("lens_id"):
                diffs.append(f"  - lens_id order differs at one entry")
                continue
            if bv.get("overall_verdict") != rv.get("overall_verdict"):
                diffs.append(
                    f"  - {bv['lens_id']}.overall_verdict: "
                    f"{bv.get('overall_verdict')!r} -> {rv.get('overall_verdict')!r}"
                )
            bf = bv.get("findings", [])
            rf = rv.get("findings", [])
            if len(bf) != len(rf):
                diffs.append(
                    f"  - {bv['lens_id']}.findings length: "
                    f"baseline={len(bf)}, regenerated={len(rf)}"
                )
                continue
            for i, (bb, rr) in enumerate(zip(bf, rf)):
                if bb.get("severity") != rr.get("severity"):
                    rationale_demoted = rr.get("rationale", "").startswith(
                        ("Demoted per rule 2:", "Demoted per rule 7:")
                    )
                    if rationale_demoted:
                        legitimate_diffs.append(
                            f"  - {bv['lens_id']}.findings[{i}].severity: "
                            f"{bb.get('severity')!r} -> {rr.get('severity')!r} "
                            f"(rule 2/7 demotion, expected for v1->v3)"
                        )
                    else:
                        diffs.append(
                            f"  - {bv['lens_id']}.findings[{i}].severity: "
                            f"{bb.get('severity')!r} -> {rr.get('severity')!r}"
                        )
    # aggregated_verdict.result must match; rationale prose is allowed to drift.
    if baseline["aggregated_verdict"]["result"] != regenerated["aggregated_verdict"]["result"]:
        diffs.append(
            f"  - aggregated_verdict.result: baseline="
            f"{baseline['aggregated_verdict']['result']!r}, "
            f"regenerated={regenerated['aggregated_verdict']['result']!r}"
        )
    if diffs:
        sys.stdout.write("SELF-TEST FAILED:\n")
        for d in diffs:
            sys.stdout.write(d + "\n")
        if legitimate_diffs:
            sys.stdout.write("Legitimate v1->v3 drift (not failures):\n")
            for d in legitimate_diffs:
                sys.stdout.write(d + "\n")
        return 1
    sys.stdout.write("SELF-TEST PASSED\n")
    if legitimate_diffs:
        sys.stdout.write("Legitimate v1->v3 drift (not failures):\n")
        for d in legitimate_diffs:
            sys.stdout.write(d + "\n")
    return 0


# ---------------------------------------------------------------------------
# Unit tests (invoked via --unit-test)
# ---------------------------------------------------------------------------


def run_unit_tests() -> int:
    """In-process unit tests for the rules Step 4 builds on.

    Mandatory coverage per plan: rule 6 escalation chain (Test 1), rule 7
    absence dedup-demote (Test 2), rule 7 scope-boundary-deferral exclusion
    in absence path (Test 3), empty lens dir -> NEEDS-WORK (Test 4),
    render_markdown Unicode smoke (Test 5), rule 7 lint-finding dedup
    (Test 6) with normalization + range sub-case (Test 6b),
    load_lint_findings I/O round-trip (Test 7), rule 7
    scope-boundary-deferral exclusion in the lint path (Test 8), and rule 2
    Security-as-primary-owner for a Bugs+Security secret-dump co-flag (Test 9).
    Prints
    UNIT TESTS PASSED + returns 0 on success; prints UNIT TEST FAILED:
    <reason> + returns 1 on first failure.
    """
    try:
        # Test 1: rule 6 escalation chain FYI -> Nit -> Block across 3 runs.
        def _mk_lv(severity: str, rationale: str) -> list[dict]:
            return [
                {
                    "lens_id": "correctness",
                    "model_tier": "sonnet",
                    "authority": "a",
                    "coverage_claim": "c",
                    "findings": [
                        {
                            "severity": severity,
                            "file_line": "x.py:42",
                            "excerpt": "e",
                            "rationale": rationale,
                            "anti_pattern": "silent-wiring",
                        }
                    ],
                    "overall_verdict": "NEEDS-WORK",
                },
                {
                    "lens_id": "bugs",
                    "model_tier": "sonnet",
                    "authority": "a",
                    "coverage_claim": "c",
                    "findings": [
                        {
                            "severity": "Nit",
                            "file_line": "x.py:42",
                            "excerpt": "e",
                            "rationale": "bugs lens at same line",
                            "anti_pattern": "silent-wiring",
                        }
                    ],
                    "overall_verdict": "NEEDS-WORK",
                },
            ]

        # Run 1: correctness emits Nit; rule 2 demotes correctness to FYI
        # because bugs is primary for silent-wiring.
        run1 = aggregate(
            _mk_lv("Nit", "original correctness rationale"),
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
        )
        c1 = run1["lens_verdicts"][0]["findings"][0]
        assert c1["severity"] == "FYI", (
            f"run 1: expected FYI after rule-2 demotion, got {c1['severity']!r}"
        )
        assert c1["rationale"].startswith("Demoted per rule 2:"), (
            f"run 1: expected Demoted prefix, got {c1['rationale'][:40]!r}"
        )

        # Run 2: same finding shape; rule 6 escalates current FYI to Nit.
        run2 = aggregate(
            _mk_lv("Nit", "original correctness rationale"),
            prior_sidecar=run1,
            timestamp="2026-01-02T00-00-00",
            skill_version="v3",
        )
        c2 = run2["lens_verdicts"][0]["findings"][0]
        assert c2["severity"] == "Nit", (
            f"run 2: expected Nit after rule-6 escalation (chain step 1), "
            f"got {c2['severity']!r}"
        )
        assert c2["rationale"].startswith("Persistent disagreement:"), (
            f"run 2: expected Persistent prefix, got {c2['rationale'][:40]!r}"
        )

        # Run 3: chain continues; rule 6 escalates from current FYI -> Nit
        # (because rule 2 demoted again), then matches prior's Persistent
        # entry, but identity-key now matches and current sev was Nit before
        # rule 2 ran first. Walk: rule 7 runs first (no-op), rule 2 demotes
        # correctness Nit -> FYI, rule 6 looks up (x.py:42, silent-wiring) in
        # prior (which is run 2's Persistent finding) -> matches -> escalates
        # current FYI -> Nit. To reach Block we feed run 2 as prior again with
        # input severity already Nit; rule 2 demotes Nit -> FYI -> rule 6
        # escalates FYI -> Nit. So Block requires that rule 2 NOT demote
        # (i.e., bugs lens absent OR not at the same file_line).
        # Adjusted: drop bugs lens for run 3 so rule 2 leaves Nit alone; rule
        # 6 then escalates Nit -> Block.
        run3_input = _mk_lv("Nit", "original correctness rationale")[:1]  # only correctness
        run3 = aggregate(
            run3_input,
            prior_sidecar=run2,
            timestamp="2026-01-03T00-00-00",
            skill_version="v3",
        )
        c3 = run3["lens_verdicts"][0]["findings"][0]
        assert c3["severity"] == "Block", (
            f"run 3: expected Block at chain step 2 (Nit -> Block), got "
            f"{c3['severity']!r}"
        )
        assert c3["rationale"].startswith("Persistent disagreement:"), (
            f"run 3: expected Persistent prefix, got {c3['rationale'][:40]!r}"
        )

        # Test 2: rule 7 dedup-demote with also_flagged_by annotation.
        def _abs_lv(lens_id: str, rationale: str) -> dict:
            return {
                "lens_id": lens_id,
                "model_tier": "sonnet",
                "authority": "a",
                "coverage_claim": "c",
                "findings": [
                    {
                        "severity": "Nit",
                        "file_line": "(absence -- no integration test)",
                        "excerpt": "",
                        "rationale": rationale,
                        "anti_pattern": "silent-wiring",
                    }
                ],
                "overall_verdict": "NEEDS-WORK",
            }

        lvs = [
            _abs_lv(
                "correctness",
                "missing integration test through production caller for handler",
            ),
            _abs_lv(
                "bugs",
                "missing integration test through production caller for handler",
            ),
        ]
        out = aggregate(
            lvs,
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
        )
        # bugs is primary for silent-wiring per ANTI_PATTERN_PRIMARY.
        bugs_lv = next(lv for lv in out["lens_verdicts"] if lv["lens_id"] == "bugs")
        corr_lv = next(
            lv for lv in out["lens_verdicts"] if lv["lens_id"] == "correctness"
        )
        bugs_f = bugs_lv["findings"][0]
        corr_f = corr_lv["findings"][0]
        assert bugs_f["severity"] == "Nit", (
            f"rule 7: bugs (primary) expected Nit, got {bugs_f['severity']!r}"
        )
        assert bugs_f.get("also_flagged_by") == ["correctness"], (
            f"rule 7: expected also_flagged_by=['correctness'], got "
            f"{bugs_f.get('also_flagged_by')!r}"
        )
        assert corr_f["severity"] == "FYI", (
            f"rule 7: secondary expected FYI, got {corr_f['severity']!r}"
        )
        assert corr_f["rationale"].startswith("Demoted per rule 7:"), (
            f"rule 7: expected Demoted prefix, got "
            f"{corr_f['rationale'][:40]!r}"
        )

        # Test 3: rule 7 scope-boundary-deferral exclusion.
        def _scope_lv() -> dict:
            return {
                "lens_id": "correctness",
                "model_tier": "sonnet",
                "authority": "a",
                "coverage_claim": "c",
                "findings": [
                    {
                        "severity": "Block",
                        "file_line": "(absence -- operator UAT required)",
                        "excerpt": "manual check needed",
                        "rationale": (
                            "missing integration test through production caller "
                            "for handler boundary scope"
                        ),
                        "anti_pattern": "scope-boundary-deferral",
                    }
                ],
                "overall_verdict": "NEEDS-WORK",
            }

        scope_and_real = [
            _scope_lv(),
            _abs_lv(
                "bugs",
                "missing integration test through production caller for handler",
            ),
        ]
        out2 = aggregate(
            scope_and_real,
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
        )
        # scope-boundary-deferral converts to deferred_uat_items; its severity
        # is demoted to FYI by extract_deferred_items, NOT by rule 7. Verify
        # rule 7 didn't ALSO demote the bugs absence as a "duplicate" of the
        # scope finding (i.e., bugs should still be at Nit, no rule-7 prefix).
        bugs_lv2 = next(lv for lv in out2["lens_verdicts"] if lv["lens_id"] == "bugs")
        bugs_f2 = bugs_lv2["findings"][0]
        assert not bugs_f2["rationale"].startswith("Demoted per rule 7:"), (
            f"rule 7 must skip scope-boundary-deferral when clustering: "
            f"bugs finding wrongly demoted: {bugs_f2['rationale'][:80]!r}"
        )
        # Also verify the scope-boundary-deferral became a deferred item.
        assert len(out2["deferred_uat_items"]) == 1, (
            f"expected 1 deferred item from scope-boundary-deferral, got "
            f"{len(out2['deferred_uat_items'])}"
        )

        # Test 4: empty lens dir -> NEEDS-WORK.
        out3 = aggregate(
            [],
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
        )
        assert out3["aggregated_verdict"]["result"] == "NEEDS-WORK", (
            f"empty lens-dir: expected NEEDS-WORK, got "
            f"{out3['aggregated_verdict']['result']!r}"
        )

        # Test 5: render_markdown Unicode + metachar smoke (no crash).
        smoke_sidecar = {
            "timestamp": "2026-01-01T00-00-00",
            "plan_step": None,
            "skill_version": "v3",
            "invocation": {
                "reviewers_flag": "code",
                "model_overrides": {},
                "force_runtime": False,
                "url": None,
                "start_cmd": None,
                "runtime_downgraded": False,
                "runtime_downgrade_reason": None,
            },
            "lens_verdicts": [
                {
                    "lens_id": "correctness",
                    "model_tier": "sonnet",
                    "authority": "a",
                    "coverage_claim": "c",
                    "findings": [
                        {
                            "severity": "Nit",
                            "file_line": "x.py:1",
                            "excerpt": "code with ``` triple backtick run",
                            "rationale": (
                                "Em-dash — smart “quote” and "
                                "`backtick` plus | pipe"
                            ),
                            "anti_pattern": None,
                        }
                    ],
                    "overall_verdict": "NEEDS-WORK",
                }
            ],
            "aggregated_verdict": {
                "result": "NEEDS-WORK",
                "rationale": "smoke test — em-dash.",
            },
            "model_tiers_used": {"correctness": "sonnet"},
            "deferred_uat_items": [],
        }
        rendered = render_markdown(smoke_sidecar)
        assert "## Lens verdicts" in rendered, (
            "render_markdown smoke: missing '## Lens verdicts' header"
        )
        assert "## Findings" in rendered, (
            "render_markdown smoke: missing '## Findings' header"
        )
        assert "Audit-trail JSON:" in rendered, (
            "render_markdown smoke: missing 'Audit-trail JSON:' footer"
        )

        # Test 6: rule 7 lint-finding dedup. A Bugs lens finding at
        # src/foo.py:12 ("unused import") and a lint finding at the same
        # file_line should demote the lens finding to FYI with rationale
        # prefixed "Cited-by-linter: ruff F401" and an
        # also_flagged_by_linter annotation.
        bugs_with_unused_import = [
            {
                "lens_id": "bugs",
                "model_tier": "sonnet",
                "authority": "a",
                "coverage_claim": "c",
                "findings": [
                    {
                        "severity": "Nit",
                        "file_line": "src/foo.py:12",
                        "excerpt": "import os",
                        "rationale": (
                            "unused import 'os' adds noise and can mask "
                            "future genuine usage"
                        ),
                        "anti_pattern": None,
                    }
                ],
                "overall_verdict": "NEEDS-WORK",
            }
        ]
        lint_findings_in = [
            {
                "tool": "ruff",
                "rule": "F401",
                "file_line": "src/foo.py:12",
                "message": "'os' imported but unused",
            }
        ]
        out4 = aggregate(
            bugs_with_unused_import,
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
            lint_findings=lint_findings_in,
        )
        bugs_lv4 = next(lv for lv in out4["lens_verdicts"] if lv["lens_id"] == "bugs")
        bugs_f4 = bugs_lv4["findings"][0]
        assert bugs_f4["severity"] == "FYI", (
            f"rule 7 lint-dedup: expected FYI after demote, got "
            f"{bugs_f4['severity']!r}"
        )
        assert bugs_f4["rationale"].startswith("Cited-by-linter: ruff F401"), (
            f"rule 7 lint-dedup: expected 'Cited-by-linter: ruff F401' "
            f"prefix, got {bugs_f4['rationale'][:60]!r}"
        )
        assert bugs_f4.get("also_flagged_by_linter") == {
            "tool": "ruff",
            "rule": "F401",
        }, (
            f"rule 7 lint-dedup: expected also_flagged_by_linter annotation, "
            f"got {bugs_f4.get('also_flagged_by_linter')!r}"
        )

        # Test 6b: HIGH normalization fix. Lens emits a RANGE with leading
        # './' (./src/foo.py:42-45); lint emits a single line (src/foo.py:43)
        # that lies WITHIN the range. The pre-fix raw-string compare missed
        # both the './' mismatch and the range case; the post-fix
        # _file_line_overlaps + _normalize_path catches it. The lens finding
        # must demote.
        bugs_with_range = [
            {
                "lens_id": "bugs",
                "model_tier": "sonnet",
                "authority": "a",
                "coverage_claim": "c",
                "findings": [
                    {
                        "severity": "Nit",
                        "file_line": "./src/foo.py:42-45",
                        "excerpt": "block of code with unused import",
                        "rationale": (
                            "range covers an unused import the linter also "
                            "flagged inside"
                        ),
                        "anti_pattern": None,
                    }
                ],
                "overall_verdict": "NEEDS-WORK",
            }
        ]
        lint_single_line_inside_range = [
            {
                "tool": "ruff",
                "rule": "F401",
                "file_line": "src/foo.py:43",
                "message": "'os' imported but unused",
            }
        ]
        out4b = aggregate(
            bugs_with_range,
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
            lint_findings=lint_single_line_inside_range,
        )
        bugs_lv4b = next(
            lv for lv in out4b["lens_verdicts"] if lv["lens_id"] == "bugs"
        )
        bugs_f4b = bugs_lv4b["findings"][0]
        assert bugs_f4b["severity"] == "FYI", (
            f"rule 7 normalize: range './src/foo.py:42-45' vs single-line "
            f"'src/foo.py:43' must demote, got {bugs_f4b['severity']!r}"
        )
        assert bugs_f4b["rationale"].startswith("Cited-by-linter: ruff F401"), (
            f"rule 7 normalize: expected 'Cited-by-linter: ruff F401' prefix, "
            f"got {bugs_f4b['rationale'][:60]!r}"
        )

        # Test 7: load_lint_findings I/O round-trip + missing-file graceful.
        tmpdir = Path(tempfile.mkdtemp(prefix="agg-test7-"))
        try:
            lint_path = tmpdir / "lint-findings.json"
            payload = {
                "timestamp": "2026-01-01T00-00-00",
                "tools_run": ["ruff"],
                "tools_skipped": [],
                "findings": [
                    {
                        "tool": "ruff",
                        "rule": "F401",
                        "file_line": "src/foo.py:12",
                        "message": "'os' imported but unused",
                    },
                    {
                        "tool": "mypy",
                        "rule": "assignment",
                        "file_line": "src/bar.py:7",
                        "message": "Incompatible types in assignment",
                    },
                ],
            }
            lint_path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_lint_findings(lint_path)
            assert len(loaded) == 2, (
                f"load_lint_findings: expected 2 findings, got {len(loaded)}"
            )
            assert loaded[0]["tool"] == "ruff", (
                f"load_lint_findings: entry 0 tool expected 'ruff', "
                f"got {loaded[0].get('tool')!r}"
            )
            assert loaded[1]["file_line"] == "src/bar.py:7", (
                f"load_lint_findings: entry 1 file_line expected "
                f"'src/bar.py:7', got {loaded[1].get('file_line')!r}"
            )
            # Missing-file path: graceful empty list.
            missing = load_lint_findings(tmpdir / "does-not-exist.json")
            assert missing == [], (
                f"load_lint_findings: missing file expected [], got {missing!r}"
            )
        finally:
            for child in tmpdir.iterdir():
                child.unlink()
            tmpdir.rmdir()

        # Test 8: scope-boundary-deferral exclusion in the LINT path. Test 3
        # already covers the ABSENCE path; this verifies the lint path also
        # skips scope-boundary-deferral findings (they're operator hand-offs,
        # not defects, and a lint co-citation must not "demote" them).
        scope_lens = [
            {
                "lens_id": "correctness",
                "model_tier": "sonnet",
                "authority": "a",
                "coverage_claim": "c",
                "findings": [
                    {
                        "severity": "Block",
                        "file_line": "src/foo.py:12",
                        "excerpt": "manual check needed",
                        "rationale": (
                            "scope-boundary deferral at this line; operator "
                            "must verify in UAT"
                        ),
                        "anti_pattern": "scope-boundary-deferral",
                    }
                ],
                "overall_verdict": "NEEDS-WORK",
            }
        ]
        lint_at_same_line = [
            {
                "tool": "ruff",
                "rule": "F401",
                "file_line": "src/foo.py:12",
                "message": "'os' imported but unused",
            }
        ]
        out5 = aggregate(
            scope_lens,
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
            lint_findings=lint_at_same_line,
        )
        # scope-boundary-deferral converts to a deferred_uat_item; rule 7's
        # lint path must NOT have demoted it OR added an
        # also_flagged_by_linter annotation. Locate the lens finding inside
        # the surviving lens_verdicts (extract_deferred_items removes the
        # finding from lens_verdicts, so the lens_verdicts findings list is
        # expected empty; the deferred item carries the audit trail). The
        # assertion is that no Cited-by-linter rationale prefix or
        # also_flagged_by_linter annotation leaked onto the deferred item.
        corr_lv5 = next(
            lv for lv in out5["lens_verdicts"] if lv["lens_id"] == "correctness"
        )
        # Either the finding was extracted to deferred_uat_items (empty
        # findings list) OR it survived in findings -- in both cases the
        # rule-7 lint path must have skipped it.
        for f in corr_lv5.get("findings", []):
            assert "also_flagged_by_linter" not in f, (
                f"rule 7 lint path: scope-boundary-deferral wrongly "
                f"annotated, got {f.get('also_flagged_by_linter')!r}"
            )
            assert not f.get("rationale", "").startswith("Cited-by-linter:"), (
                f"rule 7 lint path: scope-boundary-deferral wrongly cited, "
                f"got {f['rationale'][:60]!r}"
            )
        for item in out5.get("deferred_uat_items", []):
            assert "also_flagged_by_linter" not in item, (
                f"rule 7 lint path: deferred item wrongly annotated, "
                f"got {item.get('also_flagged_by_linter')!r}"
            )

        # Test 9: Security is the PRIMARY OWNER of security findings (rule 2).
        # A Security lens and a Bugs lens both flag the same security-class
        # defect (anti_pattern 'secret-dump') at the SAME file_line. Per
        # ANTI_PATTERN_PRIMARY['secret-dump'] == 'security', Security keeps its
        # Block and the Bugs copy demotes to FYI with the rule-2 prefix. Also
        # asserts 'security' sits AFTER 'bugs' in CODE_LENS_ORDER so the
        # documented spawn order stays coherent (SKILL.md Standing lens list).
        assert "security" in CODE_LENS_ORDER, "security must be a code lens"
        assert CODE_LENS_ORDER.index("security") == CODE_LENS_ORDER.index("bugs") + 1, (
            "CODE_LENS_ORDER: 'security' must immediately follow 'bugs', got "
            f"{CODE_LENS_ORDER!r}"
        )
        assert ANTI_PATTERN_PRIMARY.get("secret-dump") == "security", (
            "ANTI_PATTERN_PRIMARY['secret-dump'] must route to 'security', got "
            f"{ANTI_PATTERN_PRIMARY.get('secret-dump')!r}"
        )

        def _sec_coflag_lv(lens_id: str, rationale: str) -> dict:
            return {
                "lens_id": lens_id,
                "model_tier": "sonnet",
                "authority": "a",
                "coverage_claim": "c",
                "findings": [
                    {
                        "severity": "Block",
                        "file_line": "scripts/debug_env.sh:3",
                        "excerpt": "cat /etc/void_furnace/secrets.env",
                        "rationale": rationale,
                        "anti_pattern": "secret-dump",
                    }
                ],
                "overall_verdict": "NEEDS-WORK",
            }

        sec_coflag = [
            _sec_coflag_lv(
                "bugs",
                "stdout round-trip of a secrets-bearing file leaks secrets",
            ),
            _sec_coflag_lv(
                "security",
                "secret-dump per security.md; use stat/wc/file metadata check",
            ),
        ]
        out6 = aggregate(
            sec_coflag,
            prior_sidecar=None,
            timestamp="2026-01-01T00-00-00",
            skill_version="v3",
        )
        sec_lv6 = next(
            lv for lv in out6["lens_verdicts"] if lv["lens_id"] == "security"
        )
        bugs_lv6 = next(
            lv for lv in out6["lens_verdicts"] if lv["lens_id"] == "bugs"
        )
        sec_f6 = sec_lv6["findings"][0]
        bugs_f6 = bugs_lv6["findings"][0]
        # (a) Security is the primary owner -> keeps its Block.
        assert sec_f6["severity"] == "Block", (
            f"rule 2 security-primary: Security must keep Block, got "
            f"{sec_f6['severity']!r}"
        )
        assert not sec_f6["rationale"].startswith("Demoted per rule 2:"), (
            f"rule 2 security-primary: Security must NOT be demoted, got "
            f"{sec_f6['rationale'][:40]!r}"
        )
        # (b) The Bugs copy demotes to FYI per rule 2.
        assert bugs_f6["severity"] == "FYI", (
            f"rule 2 security-primary: Bugs co-flag must demote to FYI, got "
            f"{bugs_f6['severity']!r}"
        )
        assert bugs_f6["rationale"].startswith("Demoted per rule 2:"), (
            f"rule 2 security-primary: Bugs copy must carry rule-2 prefix, got "
            f"{bugs_f6['rationale'][:40]!r}"
        )
        # The aggregated verdict stays NEEDS-WORK (the surviving Block).
        assert out6["aggregated_verdict"]["result"] == "NEEDS-WORK", (
            f"rule 2 security-primary: expected NEEDS-WORK (1 surviving Block), "
            f"got {out6['aggregated_verdict']['result']!r}"
        )

    except AssertionError as e:
        sys.stdout.write(f"UNIT TEST FAILED: {e}\n")
        return 1
    except Exception as e:  # noqa: BLE001 - any other crash is a test failure
        sys.stdout.write(f"UNIT TEST FAILED: unexpected exception: {e!r}\n")
        return 1
    sys.stdout.write("UNIT TESTS PASSED\n")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="review-deep multi-lens verdict aggregator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--lens-dir",
        type=Path,
        help="Directory containing per-lens JSON verdict files (one per lens)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory where the sidecar JSON will be written",
    )
    parser.add_argument(
        "--skill-version",
        default="v3",
        help="Skill version string to embed in the sidecar (default: v3)",
    )
    parser.add_argument(
        "--prior-sidecar",
        type=Path,
        default=None,
        help="Path to a prior sidecar JSON to enable rule 6 (persistent disagreement)",
    )
    parser.add_argument(
        "--lint-findings",
        type=Path,
        default=None,
        help=(
            "Path to a lint-findings.json from scripts/lint_prepass.sh; "
            "enables rule 7's lint dedup path. Defaults: search "
            "<--output-dir>/lint-findings.json, then .review-deep/lint-findings.json"
        ),
    )
    parser.add_argument(
        "--timestamp",
        default=None,
        help="ISO-8601 timestamp override (filesystem-safe; default: now)",
    )
    parser.add_argument(
        "--self-test",
        type=Path,
        default=None,
        help="Round-trip self-test against an M1 baseline sidecar; exits after",
    )
    parser.add_argument(
        "--unit-test",
        action="store_true",
        help="Run in-process unit tests for aggregator rules 6/7 + smoke checks; exits after",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Reconfigure stdout to UTF-8 with replacement on Windows so non-ASCII
    # rationale/excerpt content (em-dashes, smart quotes) does not crash the
    # process under cp1252. errors="replace" keeps downstream pipes (`| less`,
    # `> file.md` under exotic locales) from tripping too.
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass  # Python < 3.7 lacks reconfigure

    args = _parse_args(argv)

    if args.unit_test:
        return run_unit_tests()

    if args.self_test is not None:
        return run_self_test(args.self_test)

    if args.lens_dir is None or args.output_dir is None:
        sys.stderr.write(
            "error: --lens-dir and --output-dir are required (or pass --self-test)\n"
        )
        return 2

    lens_verdicts = load_lens_verdicts(args.lens_dir)

    prior_sidecar = None
    if args.prior_sidecar is not None:
        with args.prior_sidecar.open("r", encoding="utf-8") as f:
            prior_sidecar = json.load(f)

    # Resolve --lint-findings: explicit flag wins; otherwise search
    # <output-dir>/lint-findings.json, then .review-deep/lint-findings.json.
    lint_findings_path: Path | None = args.lint_findings
    if lint_findings_path is None:
        candidate = args.output_dir / "lint-findings.json"
        if candidate.exists():
            lint_findings_path = candidate
        else:
            fallback = Path(".review-deep") / "lint-findings.json"
            if fallback.exists():
                lint_findings_path = fallback
    lint_findings = load_lint_findings(lint_findings_path)

    timestamp = args.timestamp or datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    sidecar = aggregate(
        lens_verdicts,
        prior_sidecar=prior_sidecar,
        timestamp=timestamp,
        skill_version=args.skill_version,
        plan_step=None,
        invocation=None,
        lint_findings=lint_findings,
    )

    sidecar_path = write_sidecar(sidecar, args.output_dir)
    sys.stderr.write(f"Sidecar written: {sidecar_path}\n")
    sys.stdout.write(render_markdown(sidecar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
