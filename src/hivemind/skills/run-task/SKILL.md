# /hv:run-task -- Team agent pipeline orchestration

Orchestrates the full task execution pipeline: fetches the next task, runs a sequence of specialized agents (planner/coder, tester, code reviewer), manages status transitions, and records execution reports.

## When to use

- User says "run the next task", "execute task", "start working on tasks"
- User runs `/hv:run-task` explicitly
- Automated pipeline execution is needed

## Steps

### 1. Fetch the next task

Get the task to execute via `hv run`:
```
hv run --format json
```
Or for a specific project:
```
hv run -p <project> --format json
```
Or a specific task:
```
hv run -t <TASK-ID> --format json
```

The command returns JSON with `id`, `frontmatter`, `body`, and `path`. If it exits with code 1, there are no tasks available -- stop.

### 2. Mark task as in_progress

```
hv task update <TASK-ID> --status in_progress
```

### 3. Load model profile

Fetch the current model profile to determine which models to use for each agent role:
```
hv config model_profile
```
Then load the profile details:
```
hv config profiles.<profile_name>
```

This returns a JSON object like:
```json
{
  "planner": "opus",
  "executor": "sonnet",
  "reviewer": "sonnet"
}
```

See [references/agent-prompts.md](references/agent-prompts.md) for the prompt templates used for each role.

### 4. Stage 1 -- Coding Agent

Using the **executor** model from the profile, execute the task implementation:

- Read the task body for requirements and acceptance criteria
- Search for relevant L1 knowledge: `hv search "<task title keywords>"`
- Implement the code changes
- Run linting and type checks

If the coding stage fails, follow the error escalation procedure in [references/error-handling.md](references/error-handling.md).

### 5. Stage 2 -- Test Agent

Using the **executor** model from the profile:

- Run the project's test suite
- If tests fail, attempt to fix (up to 2 retries)
- If tests still fail after retries, escalate per [references/error-handling.md](references/error-handling.md)

### 6. Stage 3 -- Code Review Agent

Using the **reviewer** model from the profile:

- Review all changes made during the coding stage
- Check for code quality, security issues, and adherence to project conventions
- If review fails, send feedback to the coding agent for revision (up to 1 retry)
- If review passes, proceed to completion

### 7. Mark task as done

```
hv task update <TASK-ID> --status done
```

### 8. Record execution report

Save a report to `{data_path}/tasks/{project}/_reports/{TASK-ID}-report.md` with:
- Task ID, duration, retries count
- Whether review passed
- Whether lint failed
- Any error notes

### 9. Extract feedback

Invoke `/hv:feedback` to capture any lessons learned during execution.

See [references/pipeline-stages.md](references/pipeline-stages.md) for detailed stage descriptions.

## Important Rules

- ALWAYS use `hv run --format json` to get structured task data.
- ALWAYS mark the task as `in_progress` before starting work.
- ALWAYS mark the task as `done` only after all stages pass.
- ALWAYS use the model profile from `hv config` for agent model selection. Do NOT hardcode models.
- NEVER skip the code review stage.
- NEVER mark a task as `done` if tests are failing.
- If a task is blocked by failures after all retries, mark it as `blocked`:
  ```
  hv task update <TASK-ID> --status blocked
  ```
- ALWAYS use Bash tool to run `hv` CLI commands. Do NOT import Python modules directly.
- NEVER write reports or feedback in Korean. All content must be in English.
