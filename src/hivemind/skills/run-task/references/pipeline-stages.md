# Pipeline Stages -- Detailed Description

The `/hv:run-task` pipeline executes tasks through a sequence of stages. Each stage has specific inputs, outputs, and success criteria.

## Overview

```
[Fetch Task] -> [Coding] -> [Testing] -> [Review] -> [Complete]
     |              |            |            |            |
     v              v            v            v            v
  hv run        Implement    Run tests    Review      hv task update
  --format json  changes     Fix if fail  changes     --status done
```

## Stage 0: Task Fetch

**Purpose:** Select and load the next task for execution.

**Command:**
```
hv run --format json -p <project>
```

**Output:** JSON object containing:
- `id`: Task identifier
- `frontmatter`: Full task metadata (status, priority, depends_on, etc.)
- `body`: Task description and requirements in markdown
- `path`: File path to the task file

**Success criteria:** A task is returned (exit code 0).

**Failure:** No tasks available (exit code 1) -- pipeline stops gracefully.

## Stage 1: Coding

**Purpose:** Implement the code changes described in the task.

**Model role:** `executor` (from active profile)

**Inputs:**
- Task body (requirements, acceptance criteria)
- L1 knowledge context (via `hv search`)
- Current codebase state

**Process:**
1. Parse the task body for requirements.
2. Search for relevant knowledge: `hv search "<keywords>"`.
3. Read relevant source files in the project.
4. Implement the changes.
5. Run `ruff check .` for linting.
6. Run `mypy .` for type checking (if applicable).

**Success criteria:**
- Code changes are implemented.
- Linting passes (or only pre-existing warnings).
- Type checking passes (or only pre-existing errors).

**Failure handling:** Follow error escalation (see error-handling.md).

## Stage 2: Testing

**Purpose:** Verify that the changes work correctly and don't break existing functionality.

**Model role:** `executor` (from active profile)

**Inputs:**
- Changes from Stage 1
- Project's test suite

**Process:**
1. Run the project's test suite (e.g., `pytest`, `npm test`).
2. Analyze results.
3. If tests fail due to the changes, fix and re-run (up to 2 retries).
4. If tests fail due to pre-existing issues, note but do not block.

**Success criteria:**
- All tests pass, or
- Only pre-existing test failures remain (not caused by this task's changes).

**Failure handling:** Follow error escalation (see error-handling.md).

## Stage 3: Code Review

**Purpose:** Quality gate to catch issues before completing the task.

**Model role:** `reviewer` (from active profile)

**Inputs:**
- All code changes from Stage 1 (diff)
- Task requirements
- Project conventions

**Process:**
1. Review all changed files.
2. Check correctness, quality, security, performance, testing, conventions.
3. If issues found: request changes with specific feedback.
4. Coding agent addresses feedback and re-submits (up to 1 round).
5. If review passes: approve.

**Success criteria:**
- Review approved (no blocking issues).

**Failure handling:** Follow error escalation (see error-handling.md).

## Stage 4: Completion

**Purpose:** Finalize the task and record execution metrics.

**Commands:**
```
hv task update <TASK-ID> --status done
```

**Report contents** (saved to `_reports/{TASK-ID}-report.md`):

```yaml
---
task_id: PRJ-001
completed_at: 2025-01-15T14:30:00Z
duration_minutes: 12
retries: 1
review_passed: true
lint_failed: false
---

## Summary
Brief description of what was implemented.

## Changes
- file1.py: Added authentication middleware
- file2.py: Updated route handlers

## Notes
Any additional observations or caveats.
```

## Stage 5: Feedback Extraction

**Purpose:** Capture lessons learned during execution for the knowledge base.

**Process:**
1. Review the execution for any notable patterns, gotchas, or reusable insights.
2. Invoke `/hv:feedback` to save lessons to L2 documents.
3. This step is optional -- only save feedback if there is genuinely useful knowledge.

## Pipeline State Machine

```
IDLE -> FETCHING -> CODING -> TESTING -> REVIEWING -> COMPLETING -> IDLE
                      |          |           |
                      v          v           v
                   RETRYING   RETRYING    RETRYING
                      |          |           |
                      v          v           v
                   FIXING     FIXING      FIXING
                      |          |           |
                      v          v           v
                  ESCALATING ESCALATING  ESCALATING -> BLOCKED
```
