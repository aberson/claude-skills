#!/usr/bin/env bash
# lint_prepass.sh — review-deep deterministic linter pre-pass.
# Runs ruff/mypy/eslint on the diff BEFORE any LLM lens fires, writing a
# deterministic lint-findings.json the Bugs/Style/Test-quality lenses can
# cite in Step 4. Tools auto-selected by file extension; gracefully skipped
# when not installed / not configured. Contract: scripts/README.md.
# Exit 0 = wrote valid JSON (findings: [] is valid); exit 2 = usage error.

set -euo pipefail

usage() {
  echo "usage: bash lint_prepass.sh --output-dir <dir> [--diff-paths <comma-or-space-separated>]" >&2
}

output_dir=""; diff_paths_raw=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output-dir)  output_dir="${2:-}"; shift 2 ;;
    --diff-paths)  diff_paths_raw="${2:-}"; shift 2 ;;
    *) echo "lint_prepass.sh: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done
[ -z "$output_dir" ] && { usage; exit 2; }
mkdir -p "$output_dir"

# File list: from --diff-paths (commas and/or whitespace) or git diff HEAD.
declare -a files=()
if [ -n "$diff_paths_raw" ]; then
  normalized="${diff_paths_raw//,/ }"
  # shellcheck disable=SC2206
  files=( $normalized )
else
  while IFS= read -r f; do [ -n "$f" ] && files+=( "$f" ); done \
    < <(git diff --name-only HEAD 2>/dev/null || true)
fi

# Bucket by extension; missing files logged to stderr; unknown extensions
# silently ignored (no tools_run / tools_skipped entry — they're irrelevant).
declare -a py_files=() js_files=()
for f in "${files[@]:-}"; do
  [ -z "${f:-}" ] && continue
  if [ ! -f "$f" ]; then
    echo "lint_prepass.sh: skipping non-existent path: $f" >&2; continue
  fi
  case "$f" in
    *.py)                  py_files+=( "$f" ) ;;
    *.ts|*.tsx|*.js|*.jsx) js_files+=( "$f" ) ;;
  esac
done

# Walk cwd → git-root looking for $1 (glob); optional $2 = grep pattern that
# qualifies pyproject.toml. Echoes "1" on hit, "0" otherwise.
has_ancestor_config() {
  local glob="$1" section="${2:-}"
  local root; root="$(git rev-parse --show-toplevel 2>/dev/null || echo /)"
  local dir; dir="$(pwd)"
  while :; do
    for c in "$dir"/$glob; do [ -e "$c" ] && { echo 1; return; }; done
    if [ -n "$section" ] && [ -f "$dir/pyproject.toml" ] \
       && grep -q "$section" "$dir/pyproject.toml" 2>/dev/null; then
      echo 1; return
    fi
    [ "$dir" = "$root" ] || [ "$dir" = / ] && break
    local p; p="$(dirname "$dir")"; [ "$p" = "$dir" ] && break; dir="$p"
  done
  echo 0
}

# Accumulators. tools_skipped[] / findings[] entries are pre-built JSON
# objects; final assembly comma-joins. Avoids a jq dependency.
declare -a tools_run=() tools_skipped=() findings=()

# JSON-escape via Python (stdlib; universally available). Reads stdin, prints
# the escaped body WITHOUT surrounding quotes — callers wrap.
json_escape() {
  python -c 'import json,sys;sys.stdout.write(json.dumps(sys.stdin.read())[1:-1])'
}

emit_skipped() {
  local t r; t="$(printf %s "$1" | json_escape)"; r="$(printf %s "$2" | json_escape)"
  tools_skipped+=( "{\"tool\":\"$t\",\"reason\":\"$r\"}" )
}
emit_finding() {
  local et er ef em
  et="$(printf %s "$1" | json_escape)"; er="$(printf %s "$2" | json_escape)"
  ef="$(printf %s "$3" | json_escape)"; em="$(printf %s "$4" | json_escape)"
  findings+=( "{\"tool\":\"$et\",\"rule\":\"$er\",\"file_line\":\"$ef\",\"message\":\"$em\"}" )
}

# Parse tool output through a python adapter that emits TSV rule\tfile_line\tmessage,
# then push each row into findings via emit_finding. $1 = tool name (also drives
# adapter dispatch), $2 = raw tool output (may be empty).
parse_into_findings() {
  local tool="$1" raw="$2"
  while IFS=$'\t' read -r rule file_line message; do
    [ -z "$rule" ] && [ -z "$file_line" ] && continue
    emit_finding "$tool" "$rule" "$file_line" "$message"
  done < <(printf %s "$raw" | python - "$tool" <<'PY'
import json, sys
tool = sys.argv[1]
raw = sys.stdin.read()
rows = []
if tool == "ruff":
    try: items = json.loads(raw or "[]")
    except json.JSONDecodeError: items = []
    for it in items:
        rule = (it.get("code") or it.get("rule") or "").strip() or "ruff"
        fname = it.get("filename") or ""
        loc = it.get("location") or {}
        row = loc.get("row") or it.get("line") or ""
        if not fname: continue
        rows.append((rule, f"{fname}:{row}", it.get("message") or ""))
elif tool == "mypy":
    # mypy --output json emits NDJSON (one object per line), not an array.
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"): continue
        try: it = json.loads(line)
        except json.JSONDecodeError: continue
        rule = (it.get("code") or "mypy").strip()
        fname = it.get("file") or ""
        if not fname: continue
        rows.append((rule, f"{fname}:{it.get('line') or ''}", it.get("message") or ""))
elif tool == "eslint":
    try: files = json.loads(raw or "[]")
    except json.JSONDecodeError: files = []
    for f in files:
        fname = f.get("filePath") or ""
        if not fname: continue
        for m in f.get("messages") or []:
            rule = (m.get("ruleId") or "eslint").strip()
            rows.append((rule, f"{fname}:{m.get('line') or ''}", m.get("message") or ""))
for rule, fl, msg in rows:
    msg = msg.replace("\n", " ").replace("\t", " ").strip()
    sys.stdout.write(f"{rule}\t{fl}\t{msg}\n")
PY
  )
}

# Tool runners. Each appends to tools_run / tools_skipped and parses any
# output through parse_into_findings.
# Tool exit-code policy: ruff and mypy exit non-zero when findings exist;
# eslint exits non-zero when problems exist. So "non-zero exit" is NOT a
# tool error — it's an expected lint signal. We treat tool exit codes >=2
# (ruff/eslint) or "command failed to run at all" as actual tool errors and
# route those to tools_skipped with a "tool errored" reason; otherwise the
# tool is added to tools_run only after we know it produced parseable output.
run_tool() {
  # Args: tool_name <cmd> [arg ...]
  # Stdout: tool output (passed to parse_into_findings on success).
  # Side effects: appends to tools_run on parseable success, tools_skipped on
  # error. Always returns 0 so set -e doesn't kill the script.
  local tool="$1"; shift
  local raw
  local rc=0
  raw="$("$@" 2>/dev/null)" || rc=$?
  # ruff exits 1 on findings, 0 on clean. mypy exits 1 on findings, 0 on clean.
  # eslint exits 1 on warnings, 2 on errors. Treat 0/1 as parseable; anything
  # else (or empty output for ruff/eslint that ALWAYS emit valid JSON arrays)
  # is a tool error.
  if [ "$rc" -gt 1 ]; then
    echo "lint_prepass.sh: $tool errored (exit $rc); skipping" >&2
    emit_skipped "$tool" "tool errored (exit $rc)"
    return 0
  fi
  tools_run+=( "$tool" )
  parse_into_findings "$tool" "$raw"
}

if [ "${#py_files[@]}" -gt 0 ]; then
  if command -v ruff >/dev/null 2>&1; then
    run_tool "ruff" ruff check --output-format=json "${py_files[@]}"
  else
    echo "lint_prepass.sh: ruff not installed; skipping" >&2
    emit_skipped "ruff" "not installed"
  fi
  if [ "$(has_ancestor_config "mypy.ini" "^\[tool\.mypy\]")" != "1" ]; then
    emit_skipped "mypy" "no mypy.ini or pyproject.toml[tool.mypy] found"
  elif ! command -v mypy >/dev/null 2>&1; then
    echo "lint_prepass.sh: mypy not installed; skipping" >&2
    emit_skipped "mypy" "not installed"
  else
    run_tool "mypy" mypy --output json "${py_files[@]}"
  fi
fi
if [ "${#js_files[@]}" -gt 0 ]; then
  if [ "$(has_ancestor_config ".eslintrc*")" != "1" ]; then
    emit_skipped "eslint" "no .eslintrc found"
  elif ! command -v eslint >/dev/null 2>&1; then
    echo "lint_prepass.sh: eslint not installed; skipping" >&2
    emit_skipped "eslint" "not installed"
  else
    run_tool "eslint" eslint -f json "${js_files[@]}"
  fi
fi

# Assemble JSON. Quote a string array as a JSON string-array body.
join_csv() { local IFS=,; echo "$*"; }
quote_strs() {
  local -a q=(); local s
  for s in "$@"; do q+=( "\"$(printf %s "$s" | json_escape)\"" ); done
  join_csv "${q[@]:-}"
}
tools_run_json=""; [ "${#tools_run[@]}" -gt 0 ] && tools_run_json="$(quote_strs "${tools_run[@]}")"
tools_skipped_json=""; [ "${#tools_skipped[@]}" -gt 0 ] && tools_skipped_json="$(join_csv "${tools_skipped[@]}")"
findings_json=""; [ "${#findings[@]}" -gt 0 ] && findings_json="$(join_csv "${findings[@]}")"

# Filesystem-safe ISO-8601 (matches aggregator sidecar shape: YYYY-MM-DDTHH-MM-SS).
timestamp="$(date -u +%Y-%m-%dT%H-%M-%S)"
{
  printf '{\n'
  printf '  "timestamp": "%s",\n' "$timestamp"
  printf '  "tools_run": [%s],\n' "$tools_run_json"
  printf '  "tools_skipped": [%s],\n' "$tools_skipped_json"
  printf '  "findings": [%s]\n' "$findings_json"
  printf '}\n'
} > "$output_dir/lint-findings.json"

exit 0
