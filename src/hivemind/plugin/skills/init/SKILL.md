---
description: "Initialize Agent Hivemind workspace. Use when setting up hivemind for the first time or linking a new project."
---

# /hv:init -- Initialize Agent Hivemind workspace

Orchestrates the full initialization of an Agent Hivemind workspace: creates the data directory structure, installs Claude Code integrations (skills, hooks, profiles), and links the current project.

## When to use

- User says "set up hivemind", "initialize hivemind", "start a new workspace"
- User runs `/hv:init` explicitly
- First time using Agent Hivemind in a project

## Steps

1. **Optionally clarify project requirements.** If the user has not specified a clear project scope, invoke `/hv:clarify` first to gather requirements before proceeding.

2. **Initialize the hivemind data directory.** Run:
   ```
   hv init
   ```
   If the user wants git tracking for the data directory, add `--git`:
   ```
   hv init --git
   ```
   If the user specifies a custom path:
   ```
   hv init --path /custom/path
   ```

3. **Review the output.** Confirm the following were created or already exist:
   - `projects/`, `tasks/`, `level1/`, `level2/`, `level3/` directories
   - `level2/frontend/`, `level2/backend/`, `level2/infra/`, `level2/general/` subdirectories
   - `level1/important.md`
   - `index.json`
   - `.hivemind.json` config file

4. **Install Claude Code integrations.** The `hv init` command automatically installs skills, hooks, and default profiles. Check the output to confirm:
   - Skills: installed to `~/.claude/skills/hv/`
   - Hooks: installed
   - Profiles: default profiles (`quality`, `balanced`, `budget`) added

5. **Link the current project.** If the user is running this from within a project directory:
   ```
   hv link
   ```
   Or with an explicit name:
   ```
   hv link --name my-project
   ```
   This creates `.hivemind-link.json` in the project root and registers the project in `.hivemind.json`.

6. **Report results.** Summarize what was initialized and linked. Show the user:
   - Data directory location
   - Project name and prefix
   - Next steps (e.g., "Create tasks with `/hv:task`" or "Run `hv task create ...`")

## Important Rules

- NEVER run `hv init` with `--path` unless the user explicitly requests a custom location. Default is `~/agent-hivemind-data`.
- NEVER skip the `hv link` step if the user is inside a project directory.
- ALWAYS check `hv init` output for errors before proceeding to `hv link`.
- ALWAYS use Bash tool to run `hv` CLI commands. Do NOT import Python modules directly.
- If the data directory already exists, `hv init` is idempotent -- it only creates missing items.
