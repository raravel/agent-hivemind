---
description: "Initialize Agent Hivemind workspace. Use when setting up hivemind for the first time or linking a new project."
---

# /hv:init -- Initialize and link a project

Sets up the hivemind data directory (if needed) and links the current project.

## Execution

**Step 1.** Ensure hivemind is initialized:

```bash
hv init
```

This is idempotent — safe to run multiple times. Creates the data directory and installs the plugin if not already done.

**Step 2.** Link the current project:

```bash
hv link
```

This:
- Creates `.hivemind-link.json` in the project root
- Creates `projects/{name}/`, `tasks/{name}/`, `level3/{name}/` in the data directory
- Registers the project in `.hivemind.json`
- Sets up CLAUDE.md with the mandatory `/hv:clarify` rule

**Step 3.** Report what was done and suggest next steps:
- "Run `/hv:plan` to plan your project"

## Rules

- ALWAYS run both `hv init` and `hv link` in sequence.
- ALWAYS use Bash tool for `hv` commands.
- If already linked (`.hivemind-link.json` exists), `hv link` will skip automatically.
