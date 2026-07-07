---
name: user-recap
description: Summarize the current working thread — problem, what we tried, what's left. Lightweight alternative to user-orient when you just need a quick reminder, not a full re-orientation.
user-invocable: true
---

Summarize our current working thread in plain text. Be concise. Cover exactly three things:

**1. Problem** — What are we trying to solve? One or two sentences max. Include the ticket/PR number if applicable.

**2. What we tried** — Bullets. Label each with outcome (`worked`, `didn't fix`, `confirmed`). Actions without outcomes don't count.

**3. Still to do** — What's unresolved or next? Bullet list. If nothing is left, say so.

Never start with preamble, the phrase "here's your recap", or closing remarks. Output just the three sections.

---

## When to use this vs `user-orient`

- **`user-recap`** (this skill): quick working-memory refresh; ~150 words, three sections, no autonomous lookups.
- **`user-orient`**: full re-orientation after a context gap. Six sections, verified-vs-unverified, manual checks, autonomous asides.

Default to `user-recap` for in-flow check-ins; reach for `user-orient` when returning fresh.
