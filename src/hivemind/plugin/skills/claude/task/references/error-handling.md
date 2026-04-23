# Error Handling -- Orchestrator Retry & Escalation

When an error occurs during the orchestrator pipeline, the orchestrator handles retries via **SendMessage** (continuing the same worker to preserve context) rather than spawning fresh agents.

## Error Types

The orchestrator distinguishes between two error categories:

### Worker Failure
The coding or review worker returns an error, crashes, or produces no useful output.
- **Recovery:** SendMessage to continue the worker, or spawn a fresh worker if the worker is unresponsive.

### Verification Failure
The worker returns "done" but the orchestrator's own verification finds problems:
- Completion criteria not met (post-coding check)
- Tests fail (orchestrator runs tests directly)
- Blocking review issues found (orchestrator judges review)
- **Recovery:** SendMessage to the worker with specific failure details.

## Retry Policy

| Stage | Max Retries | Method | What Orchestrator Sends |
|-------|-------------|--------|------------------------|
| VERIFY_CODE | 2 | SendMessage to coding worker | Specific `[FAIL]` criteria with file/line details |
| RUN_TESTS | 2 | SendMessage to coding worker | Full test output (stdout + stderr) |
| JUDGE_REVIEW | 1 | SendMessage to coding worker | Blocking issues from review |

### Why SendMessage over fresh Agent spawn

- **Context preservation:** The worker already read the harness docs, understands the task, and knows what it implemented. Starting fresh would waste tokens re-reading everything.
- **Targeted fixes:** The orchestrator sends exactly what failed, so the worker can make a focused fix.
- **Cost efficiency:** Continuing a worker costs ~1/3 of starting a new one.

**Exception:** If a worker is completely unresponsive or its context is corrupted (e.g., it starts hallucinating unrelated code), spawn a fresh worker. This should be rare.

## Escalation Flow

```
Failure detected by orchestrator
  │
  ├── Retry 1: SendMessage with specific failure details
  │   └── Orchestrator re-verifies
  │       ├── Pass → continue pipeline
  │       └── Fail → Retry 2
  │
  ├── Retry 2: SendMessage with updated failure details
  │   └── Orchestrator re-verifies
  │       ├── Pass → continue pipeline
  │       └── Fail → Escalate
  │
  └── Escalation:
      1. hv task update <TASK-ID> --status blocked
      2. Save feedback: /hv:feedback with error context
      3. Report to user
```

## SendMessage Templates

### After VERIFY_CODE failure

```
Your implementation has issues. The following completion criteria were not met:

{list of [FAIL] criteria with details}

The code changes I see in git diff:
{summary of what changed}

Please fix ONLY the failed criteria. Do not change things that are already working.
```

### After RUN_TESTS failure

```
Tests failed after your implementation. Here is the test output:

{full test output}

The test failures appear to be caused by: {orchestrator's analysis}

Please fix the code to make these tests pass. Do not modify the test files
unless the tests themselves are incorrect per the task spec.
```

### After JUDGE_REVIEW failure

```
Code review found blocking issues that must be fixed:

{list of [BLOCKING] issues with file, line, and suggested fix}

Please address each blocking issue. Advisory issues can be ignored:
{list of [ADVISORY] issues for reference}
```

## Escalation Report

When all retries are exhausted, the orchestrator:

1. Marks the task as blocked:
   ```bash
   hv task update <TASK-ID> --status blocked
   ```

2. Writes an execution report with failure details:
   ```markdown
   ---
   task_id: {TASK-ID}
   duration_minutes: {elapsed}
   coding_retries: {0-2}
   test_retries: {0-2}
   review_rounds: {0-1}
   review_passed: false
   lint_failed: {true|false}
   ---

   ## Summary
   Task blocked after exhausting retries.

   ## Failure
   - Stage: {VERIFY_CODE|RUN_TESTS|JUDGE_REVIEW}
   - Retries attempted: {count}
   - Last error: {description}

   ## What was tried
   {description of each retry attempt and what changed}

   ## Suggested next steps
   {orchestrator's recommendation for manual intervention}
   ```

3. Saves feedback via `/hv:feedback` with the failure context.

4. Reports to the user with the task ID, failed stage, and recommendation.
