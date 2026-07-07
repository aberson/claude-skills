#!/usr/bin/env bash
# auth_gate_probe.sh — review-deep auth-gate detector
#
# Probes --url with a 10s budget and reports whether runtime lenses should be
# downgraded to code-only because the URL is auth-gated. Four trigger
# conditions: HTTP 401, 3xx redirect to /login|/signin|/auth|/sso, HTTP 200
# whose body contains a login-shaped <form>, or probe timeout. Canonical
# prose lives at SKILL.md "### Auth-gated runtime downgrade".
#
# Exit-code contract:
#   0 = downgrade signaled; stdout = the reason token (one of
#       status_401, redirect_to_login:<url>, login_form_in_200_body, timeout)
#   1 = no downgrade (no trigger fired)
#   2 = usage error

set -u

probe_url=""
while [ $# -gt 0 ]; do
  case "$1" in
    --url)
      probe_url="${2:-}"
      shift 2
      ;;
    *)
      echo "auth_gate_probe.sh: unknown argument: $1" >&2
      echo "usage: bash auth_gate_probe.sh --url <url>" >&2
      exit 2
      ;;
  esac
done

if [ -z "$probe_url" ]; then
  echo "usage: bash auth_gate_probe.sh --url <url>" >&2
  exit 2
fi

timeout_seconds=10
probe_body="$(mktemp -t review-deep-probe-XXXXXX)"
trap 'rm -f "$probe_body"' EXIT

response=$(curl -sS --connect-timeout 2 --max-time "$timeout_seconds" -o "$probe_body" -w "%{http_code} %{redirect_url}" "$probe_url" 2>&1) || {
  echo "timeout"
  exit 0
}

status_code="$(echo "$response" | awk '{print $1}')"
redirect_url="$(echo "$response" | awk '{print $2}')"

reason=""
case "$status_code" in
  401)
    reason="status_401"
    ;;
  301|302|303|307|308)
    # Path-anchored: only match /login|/signin|/auth|/sso as a path segment of the
    # redirect URL (not inside hostname like login.example.com, not in query
    # strings like ?next=/login, not in path prefixes like /loginstuff.pdf).
    if echo "$redirect_url" | grep -iE '^[a-z]+://[^/]+/(login|signin|auth|sso)([/?#]|$)' >/dev/null; then
      reason="redirect_to_login:$redirect_url"
    fi
    ;;
  200)
    # -z: null-delimited input so .* can cross newlines for multi-line login HTML.
    # Quote-tolerant: matches type=password, type='password', and type="password"
    # (and the same for name="password" / name="pin"). Real HTML uses all three.
    form_pattern=$'<form[^>]*>.*(type=["\']?password["\']?|name=["\']?password["\']?|name=["\']?pin["\']?)'
    if grep -izE "$form_pattern" "$probe_body" >/dev/null 2>&1; then
      reason="login_form_in_200_body"
    fi
    ;;
esac

if [ -n "$reason" ]; then
  echo "$reason"
  exit 0
fi

exit 1
