---
name: degraded-fixture
description: Sample SKILL.md that scores LOW on multiple metrics
---

# Degraded fixture

As an AI assistant I think this skill should do many things and I cannot really explain why but it should work most of the time and you should trust it and you should check it and you should verify it and you should test it and you should validate it and you should review it and you should monitor it and you should always remember that you should keep going.

## Overview

This section is not in the required-sections list. Required sections are missing entirely.

#### Deeply nested heading under H2 with no H3

This H4 sits directly under an H2 with no intervening H3 — section depth consistency violation.

#### Another H4 under H2

Same violation again.

Here is a broken relative link: [missing](does-not-exist.md) and another [also missing](some/where/else.md).

Here is a code fence with no language tag and no closing fence:

```
print("hello")
def something():
    return 42

This line is way over one hundred and fifty characters long because we want to deliberately trigger the maximum-line-length violation and it just keeps going and going and going and going and going.

A second very-long line that should also count as a violation against the default 150-character limit for this metric because length matters here for readability and grading purposes.

Cross-reference to a nonexistent target: [[nonexistent-investigation-slug]].

And another bad crossref: [[also-not-real]].
