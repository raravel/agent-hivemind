---
description: "Task planning and decomposition. Use when the user wants to create, list, update, or manage tasks, or decompose a request into multiple tasks."
---

# /hv:plan -- Task planning and decomposition

Decomposes complex requests into concrete tasks, manages task CRUD (create, list, view, update, next) via the `hv task` CLI command group.

## When to use

- User wants to create, list, view, update, or pick the next task
- User says "add a task", "what's next", "show tasks", "update task status"
- User runs `/hv:task` explicitly
- User describes work that should be decomposed into tasks

## Steps

### Creating a task

1. **Gather task details.** If the user provides a vague request, invoke `/hv:clarify` to decompose it into concrete tasks with clear titles, priorities, and dependencies.

2. **Create the task.** Run:
   ```
   hv task create -p <project> -t "<title>" --priority <high|medium|low> --type <task|bug|feature|chore>
   ```
   To add dependencies:
   ```
   hv task create -p <project> -t "<title>" --depends <TASK-ID> --depends <TASK-ID>
   ```

3. **Report the created task ID and file path.**

### Listing tasks

1. **List all tasks or filter:**
   ```
   hv task list
   hv task list -p <project>
   hv task list -p <project> -s pending
   hv task list --priority high
   ```

### Getting task details

1. **Get a specific task by ID:**
   ```
   hv task get <TASK-ID>
   hv task get <TASK-ID> --format json
   ```

### Updating a task

1. **Update status, priority, or title:**
   ```
   hv task update <TASK-ID> --status <pending|in_progress|done|blocked|cancelled>
   hv task update <TASK-ID> --priority high
   hv task update <TASK-ID> --title "New title"
   ```
   Multiple fields can be updated at once:
   ```
   hv task update <TASK-ID> --status in_progress --priority high
   ```

### Getting the next task

1. **Get the highest-priority actionable task:**
   ```
   hv task next
   hv task next -p <project>
   ```
   This returns the highest-priority pending task whose dependencies are all done.

### Batch task creation

When decomposing a larger request into multiple tasks:

1. Invoke `/clarify` to understand the full scope.
2. Create tasks in dependency order (independent tasks first, dependent tasks after).
3. Use `--depends` to wire up the dependency chain.
4. List all created tasks at the end to confirm the plan.

## Task file format

See [references/task-format.md](references/task-format.md) for the frontmatter format used in task markdown files.

## Important Rules

- ALWAYS use the `hv task` CLI via Bash tool. Do NOT edit task files manually.
- NEVER create a task without a `--project` flag.
- ALWAYS validate that the project exists (was linked via `hv link`) before creating tasks.
- Valid statuses: `pending`, `in_progress`, `done`, `blocked`, `cancelled`.
- Valid priorities: `high`, `medium`, `low`.
- NEVER write task content in Korean. All task titles and descriptions must be in English.
- When decomposing work, prefer smaller focused tasks over large monolithic ones.
