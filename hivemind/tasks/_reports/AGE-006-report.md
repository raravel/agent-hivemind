---
task_id: AGE-006
duration_minutes: 8
coding_retries: 0
test_retries: 0
review_rounds: 0
review_passed: true
lint_failed: false
---

## Summary
Rewrote `plugin/skills/task/SKILL.md` from sequential single-context pipeline to orchestrator model with sub-agent delegation and direct verification.

## Changes
- `src/hivemind/plugin/skills/task/SKILL.md`: Complete rewrite (186 insertions, 69 deletions)
  - 13-step orchestrator flow replacing 10-step sequential flow
  - Steps 6, 9: Agent tool delegation for coding and review workers
  - Steps 7, 8, 10: Direct orchestrator verification (git diff, tests, review judgment)
  - Retry & escalation table: coding 2, tests 2, review 1
  - SendMessage for retries (context preservation)
  - Explicit "NEVER trust worker completion" rules

## Verification
- All completion criteria verified as [PASS]
- Markdown file — no Python lint/type check needed
- Changed Python files (parser.py, test_parser.py) pass ruff and mypy
