---
name: claude-oauth-auth
description: How to authenticate with Claude using a subscription OAuth token instead of an API key. Use when setting up Claude Code sessions, building tools that invoke the claude CLI, or when a user has a Claude subscription but no API key.
user-invokable: false
---

# Claude OAuth Authentication (no API key needed)

**Requirement:** the user must have an active Claude subscription (Pro, Max, or Team) for this method to work. With a subscription, the `claude` CLI supports authentication via `CLAUDE_CODE_OAUTH_TOKEN` instead of `ANTHROPIC_API_KEY` — no API key is required.

## Usage

Set the environment variable and invoke `claude` normally — no API key required:

```bash
CLAUDE_CODE_OAUTH_TOKEN=<token> claude -p "your prompt"
```

In Docker/containers, pass it as an `-e` flag:

```bash
docker run -e CLAUDE_CODE_OAUTH_TOKEN=<token> <image> claude -p "your prompt"
```

In a tmux session, inject via `tmux set-environment` then load with:

```bash
eval "$(tmux show-environment -s)" && claude
```

## Priority

If both `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` are present, Claude Code prefers the OAuth token.

## Notes

- The CLI handles token validation and refresh internally — do not manage the OAuth flow yourself.
- Store the token as a file at `~/.config/<yourapp>/.secrets/CLAUDE_CODE_OAUTH_TOKEN` and load it at runtime to avoid hardcoding.
- Never log or expose the token value.
