---
task_id: AGE-011
duration_minutes: 15
coding_retries: 0
test_retries: 0
review_rounds: 0
review_passed: true
lint_failed: false
---

## Summary
Added `_index.json` write-through cache for task scanning performance. The index stores task frontmatter fields (status, priority, type, parent, depends_on, title, updated) and is transparently updated on create/update.

## Changes
- `src/hivemind/commands/task.py`: +196 lines
  - 6 new functions: `_index_path`, `_load_task_index`, `_save_task_index`, `_fm_to_index_entry`, `_rebuild_task_index`, `_update_task_index_entry`
  - 2 extracted functions: `_scan_tasks_from_index`, `_scan_tasks_glob`
  - Modified: `_scan_tasks` (index-first with fallback), `create` (write-through), `update` (write-through), `_auto_complete_parents` (write-through)
- `tests/unit/test_task.py`: +236 lines, 14 new tests in `TestTaskIndex`

## Verification
- ruff check src/hivemind/commands/task.py: passed
- mypy src/: passed (strict, 27 files)
- pytest: 285 passed, 1 pre-existing failure
