---
description: "Initialize Agent Hivemind workspace. Use when setting up hivemind for the first time or linking a new project."
---

# /hv:init -- Initialize Agent Hivemind workspace

## Execution

Run:

```bash
hv init
```

This single command does everything:
1. Creates `~/agent-hivemind-data/` with all required directories
2. Installs the Claude Code plugin (skills, hooks, profiles)
3. Links the current project (creates `.hivemind-link.json`, registers in config)
4. Sets up CLAUDE.md with `/hv:clarify` mandatory rule

If the user wants git tracking: `hv init --git`
If the user wants a custom path: `hv init --path /custom/path`

After init, report what was created and suggest next steps:
- "Run `/hv:plan` to plan your project"

## Rules

- ALWAYS use Bash tool to run `hv init`.
- If data directory already exists, `hv init` is idempotent.
- Do NOT run `hv link` separately — `hv init` handles it automatically.
