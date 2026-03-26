# Error Handling -- 3-Level Escalation

When an error occurs during any pipeline stage (coding, testing, or review), follow this 3-level escalation procedure.

## Level 1: Retry

**Trigger:** First failure in any stage.

**Action:** Retry the failed operation with the same parameters.

- Coding stage: Re-attempt the implementation, fixing the specific error.
- Test stage: Analyze the test failure, fix the code, and re-run tests.
- Review stage: Address the reviewer's feedback and re-submit for review.

**Max retries:** 2 attempts per stage.

**Example:**
```
# Test failed -- retry
# (fix the code based on error output)
# Re-run tests
```

## Level 2: Fix

**Trigger:** Failure persists after all Level 1 retries.

**Action:** Attempt a different approach to fix the issue.

- Re-read the task requirements to check for misunderstanding.
- Search the knowledge base for relevant lessons:
  ```
  hv search "<error description keywords>"
  ```
- Try an alternative implementation strategy.
- If tests fail due to environment issues, check dependencies and configuration.

**Max attempts:** 1 alternative approach.

**Example:**
```
# All retries exhausted, try alternative approach
hv search "authentication timeout error"
# Apply lesson learned from search results
# Re-run the failed stage
```

## Level 3: Escalate

**Trigger:** Failure persists after Level 2 fix attempt.

**Action:** Mark the task as blocked and report to the user.

1. Mark the task as blocked:
   ```
   hv task update <TASK-ID> --status blocked
   ```

2. Save the error context as feedback for future reference:
   ```
   # Save the lesson learned from this failure
   # (invoke /hv:feedback with the error details)
   ```

3. Report to the user with:
   - Task ID and title
   - Which stage failed (coding/testing/review)
   - Error details
   - What was attempted (retries + alternative approach)
   - Suggested next steps for the user

## Summary Table

| Level | Action     | Max Attempts | Next if Fails |
|-------|-----------|-------------|---------------|
| 1     | Retry     | 2           | Level 2       |
| 2     | Fix       | 1           | Level 3       |
| 3     | Escalate  | -           | User action   |

## Error Report Format

When escalating (Level 3), include this information:

```
## Escalation Report
- Task: {TASK-ID} -- {title}
- Stage: {coding|testing|review}
- Error: {error message or description}
- Retries: {count}
- Alternative approach: {what was tried}
- Suggestion: {recommended next steps}
```
