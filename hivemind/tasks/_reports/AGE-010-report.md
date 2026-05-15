---
task_id: AGE-010
duration_minutes: 3
retries: 0
review_passed: true
lint_failed: false
---

## Summary
Added `blocked` and `cancelled` to `VALID_STATUSES` in `src/hivemind/core/parser.py`.
Added 4 new test cases in `tests/unit/test_parser.py` covering the new statuses.

## Changes
- `src/hivemind/core/parser.py`: Added 2 entries to `VALID_STATUSES` list
- `tests/unit/test_parser.py`: Added `test_blocked_status_is_valid`, `test_cancelled_status_is_valid`, `test_update_to_blocked_succeeds`, `test_update_to_cancelled_succeeds`

## Verification
- ruff check: passed (changed files)
- mypy src/: passed (strict mode, 27 files)
- pytest: 271 passed, 1 pre-existing failure (test_e2e.py type="feat" issue)

## Notes
- Pre-existing lint warnings (unused pytest imports) in 5 other test files — not addressed as out of scope
- Pre-existing integration test failure (test_full_task_lifecycle uses invalid type "feat") — not addressed as out of scope
