# review-deep / scripts

Deterministic mechanical helpers extracted from `SKILL.md`. Each script is a small, single-purpose tool that the skill's prose references but doesn't need to inline — keeping them here reduces the SKILL.md context cost while preserving auditable behavior.

The canonical prose for each helper lives in `SKILL.md`; this directory holds the executable contract.

## `auth_gate_probe.sh`

Detects whether `--url` is auth-gated so the orchestrator can downgrade runtime lenses to code-only. Canonical prose: `SKILL.md` § `### Auth-gated runtime downgrade`.

**Usage:**

```bash
bash auth_gate_probe.sh --url <url>
```

**Trigger conditions** (any fires → downgrade):

1. HTTP status `401` — reason `status_401`.
2. HTTP `301`/`302`/`303`/`307`/`308` redirect whose `Location` URL **path segment** matches `/login|/signin|/auth|/sso` (case-insensitive; anchored to the path, not the hostname, query string, or path prefixes like `/loginstuff.pdf`) — reason `redirect_to_login:<full-Location-URL>`.
3. HTTP `200` whose body contains a multi-line-aware `<form>` element with `type=password`, `name=password`, or `name=pin` (quote-style tolerant: matches double-quoted, single-quoted, and unquoted HTML attribute values) — reason `login_form_in_200_body`.
4. Probe timeout (10s total budget, covers connect-timeout and total-transaction-time) — reason `timeout`.

**Exit codes:**

- `0` — downgrade signaled. Stdout = the reason token (one of `status_401`, `redirect_to_login:<url>`, `login_form_in_200_body`, `timeout`). No surrounding prose; the orchestrator captures stdout and threads it into the sidecar's `invocation.runtime_downgrade_reason`.
- `1` — no trigger fired; runtime lenses may proceed.
- `2` — usage error (missing or empty `--url`).

**Dependencies:** `bash`, `curl`, `mktemp`, `grep`, `awk`. No `jq`, no Python.

## `aggregate.py`

Multi-lens verdict aggregator. Reads per-lens JSON verdicts from `--lens-dir`, applies aggregator rules 1-7 (severity dominance, lens-owns-dimension, SKIPPED handling, FAILED handling, NO-EVIDENCE handling, persistent-disagreement via `--prior-sidecar`, absence-of-thing dedup), writes the audit-trail sidecar to `<--output-dir>/<timestamp>.json`, and prints the human-readable markdown summary to stdout. Canonical prose: `SKILL.md` § Aggregation (contract-summary section). Rule semantics and dataclass schemas (`LensVerdict`, `Finding`) live in `aggregate.py`'s module docstring + per-function docstrings; renames touch both sites in the same diff (producer-consumer-drift prevention).

**Usage:**

```bash
python aggregate.py --lens-dir <dir> --output-dir <dir> [--skill-version v3] [--prior-sidecar <path>]
```

Plus a `--self-test <m1-sidecar>` mode that round-trips a baseline sidecar through the aggregator and reports any structural diff vs the input (legitimate v1→v3 rule-2/rule-7 demotions are surfaced separately from real failures).

A `--unit-test` mode runs in-process unit tests for the aggregator rules Step 4 builds on (rule 6 escalation chain, rule 7 dedup-demote, rule 7 `scope-boundary-deferral` exclusion, empty-`--lens-dir` → `NEEDS-WORK` guardrail, and a `render_markdown` Unicode + markdown-metacharacter smoke). On success the command prints `UNIT TESTS PASSED` and exits 0; on the first assertion failure it prints `UNIT TEST FAILED: <reason>` and exits non-zero.

```bash
python aggregate.py --unit-test
```

**Dependencies:** Python ≥3.10 stdlib only (`dataclasses`, `json`, `pathlib`, `argparse`, `datetime`, `re`, `typing`). No third-party packages.

## `lint_prepass.sh`

Pre-pass linter run that produces a deterministic finding list before any LLM lens fires. Auto-detects file extensions in the diff to decide which tools to invoke. Canonical prose: `SKILL.md` § `## Tools`.

**Usage:**

```bash
bash lint_prepass.sh --output-dir <dir> [--diff-paths <comma-or-space-separated>]
```

Invoke from the project root (cwd), NOT from the script's own directory — the config-file ancestry probe and the default `git diff --name-only HEAD` are both cwd-relative. When `--diff-paths` is omitted, the script falls back to `git diff --name-only HEAD` (the current uncommitted changes against HEAD).

**Auto-detected tools:**

| File extensions | Tools (when installed AND configured) |
|---|---|
| `.py` | `ruff check --output-format=json`, `mypy --output json` (requires `mypy.ini` or `pyproject.toml[tool.mypy]` in cwd or any ancestor up to git root) |
| `.ts`, `.tsx`, `.js`, `.jsx` | `eslint -f json` (requires `.eslintrc*` in cwd or any ancestor up to git root) |

Files whose extension isn't recognized are silently skipped (no entry in `tools_run`, no entry in `tools_skipped` — they're irrelevant). Files that don't exist (e.g., a stale `--diff-paths` entry) are logged to stderr and skipped without failing the script.

**Output schema** (`<output-dir>/lint-findings.json`):

```json
{
  "timestamp": "<ISO-8601, filesystem-safe: YYYY-MM-DDTHH-MM-SS>",
  "tools_run": ["ruff", "mypy"],
  "tools_skipped": [{"tool": "eslint", "reason": "no .eslintrc found"}],
  "findings": [{"tool": "ruff", "rule": "F401", "file_line": "src/foo.py:12", "message": "..."}]
}
```

`tools_run[]` lists every tool that successfully executed (regardless of whether it produced findings). `tools_skipped[]` lists every tool that was applicable to the file set but not invoked — each entry's `reason` is one of `"not installed"`, `"no mypy.ini or pyproject.toml[tool.mypy] found"`, or `"no .eslintrc found"`. `findings[]` is the union of all tools' results, normalized to the unified `{tool, rule, file_line, message}` shape (mypy's NDJSON output and ruff's JSON-array output and eslint's per-file `messages[]` are all flattened). An empty `findings: []` is valid and explicit — it means the tools that ran found nothing, NOT that the script failed.

**Exit codes:**

- `0` — wrote a valid `lint-findings.json` (even if every tool was skipped or `findings: []`).
- `2` — usage error (missing `--output-dir`, unknown flag).

**Dependencies:** `bash`, `git` (for the default file list and the ancestor-config walk), `python` (used internally for JSON-string escaping and adapter parsing of ruff/mypy/eslint output — no third-party packages). Optionally `ruff` / `mypy` / `eslint` (gracefully skipped when missing). **No `jq` dependency** — the workspace's prevailing convention but `jq` is not universally installed on fresh Windows + Git Bash, so the script does its own JSON assembly via python.

## Other scripts

No further scripts arrive in subsequent steps of the review-deep v3 plan; this section is retained as a stub in case a future plan revision adds one.
