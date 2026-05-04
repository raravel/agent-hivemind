---
description: "Run a drift scan between code and harness specs. Use when checking for spec-code inconsistencies."
---

# hv-audit -- Project drift scan orchestration

> **Worker-mode guard.** If you were spawned as a sub-worker by another orchestrator (for example via `codex:codex-rescue` from inside `hv-task`), do NOT engage this skill. Read the orchestrator's prompt literally and execute exactly what it asks. The hv-* skills are for direct user invocation, not nested execution. Signals you are a sub-worker: the prompt starts with `--fresh` or `--resume`, or contains explicit instructions like "Step A:", "Step B:", "Review only", "Implement <TASK-ID>", or "Edit only inside the current working directory".

Runs a full drift audit for a project, detecting mismatches between code files, harness specs, and task state. Presents findings and offers to fix detected issues.

## When to use

- User wants to check if specs are in sync with code
- User says "audit the project", "check for drift", "are specs up to date"
- User invokes `hv-audit` explicitly
- Periodically after significant code changes
- Before starting a new batch of tasks, to ensure the baseline is clean

## Steps

### 1. Run the audit

```
hv audit -p <project>
```

To also get fix suggestions:
```
hv audit -p <project> --fix
```

### 2. Review the drift report

The audit checks three categories:

**Code without spec:**
- Files tracked in git that are not referenced in any harness spec document.
- These represent undocumented code.

**Spec without code:**
- References in spec documents that point to files not found in the git repo.
- These represent stale or broken spec references.

**Stale tasks:**
- Tasks marked as `done` more than 30 days ago with no recent activity.
- These may need archiving or re-evaluation.

### 3. Present findings

Show the user the report with issue counts. Example output:
```
=== Drift Report: my-project ===

Code without spec:
  - src/new_module.py
  - src/utils/helper.py

Spec without code:
  - api-spec.md -> referenced module not found: src/old_module.py

Stale tasks:
  - PRJ-005 (done 45 days ago, no recent activity)

Total: 4 issues found
```

### 4. Offer to fix

If the `--fix` flag was used, the report includes fix suggestions. Present these to the user and offer to take action:

- **Code without spec:** Offer to create spec documentation for undocumented files.
- **Spec without code:** Offer to update spec files to remove or correct stale references.
- **Stale tasks:** Offer to archive old tasks or reopen them if still relevant:
  ```
  hv task update <TASK-ID> --status cancelled
  ```

### 5. Re-run after fixes

After applying fixes, re-run the audit to confirm the issues are resolved:
```
hv audit -p <project>
```

## Important Rules

- ALWAYS specify the `--project` / `-p` flag. The audit requires a project name.
- ALWAYS present the full report to the user before taking any fix actions.
- NEVER auto-fix issues without user confirmation.
- NEVER delete spec files or code files during a fix. Only update references or task statuses.
- ALWAYS use Bash tool to run `hv` CLI commands. Do NOT import Python modules directly.
- The project must be linked (`hv link`) and have a `linked_path` in `.hivemind.json` for the code-vs-spec check to work.
- If no issues are found, report "No issues found. Code and specs are in sync."
