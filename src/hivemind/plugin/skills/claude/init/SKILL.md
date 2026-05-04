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

Choose a runtime target when needed:

```bash
hv init --target claude
hv init --target codex
hv init --target both
```

**Step 2.** Link the current project:

```bash
hv link --target claude
```

This:
- Creates `.hivemind-link.json` (carries only `{project, prefix}` under v4)
- Creates `projects/{name}/`, `tasks/{name}/`, `level3/{name}/` in the data directory
- Registers the project's `linked_path` in `.hivemind.json`
- Writes a managed `AGENTS.md` block as the canonical shared instructions file
- For Claude targets, writes a managed `CLAUDE.md` shim with native `@import`
  references to `architecture.md` and `rules.md`
- For Codex targets, writes repo-local `.codex/hooks.json`

**Step 3.** If this is an existing v2 or v3 installation, run the migration:

```bash
hv migrate --to v4
```

`--to v4` drops the legacy `data_path` field from `.hivemind.json`, drains
each project's `prefix` into its `.hivemind-link.json`, splits `counter`
into `<data_path>/tasks/<project>/_counter.json`, and bumps the schema to
4.0.0. Running twice is a no-op. (`--to v3` is still available for older
v1/v2 workspaces and is also idempotent.)

**Step 4.** Report what was done and suggest next steps:
- "Run `/hv:plan` to plan your project"

## Rules

- ALWAYS run both `hv init` and `hv link` in sequence.
- ALWAYS use Bash tool for `hv` commands.
- If already linked (`.hivemind-link.json` exists), `hv link` will skip automatically.
