---
description: "Initialize Agent Hivemind for Codex. Use when setting up the shared data repo, linking the current project, or repairing Codex-side project instructions and hooks."
---

# hv-init -- Initialize and link a project for Codex

Sets up the hivemind data directory for Codex and links the current project.

## Execution

**Step 1.** Ensure hivemind is initialized:

```bash
hv init --target codex
```

This is idempotent — safe to run multiple times. Creates the data directory,
installs the Codex plugin, and updates the personal Codex marketplace entry.

**Step 2.** Link the current project:

```bash
hv link --target codex
```

This:
- Creates `.hivemind-link.json` (carries only `{project, prefix}` under v4)
- Creates `projects/{name}/`, `tasks/{name}/`, `level3/{name}/` in the data directory
- Registers the project's `linked_path` in `.hivemind.json`
- Writes a managed `AGENTS.md` block as the canonical shared instructions file
- Writes repo-local `.codex/hooks.json`
- Adds `codex` to `runtime.enabled_targets` in the global config

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
- "Use the hv plugin to plan the project next."

## Rules

- ALWAYS run both `hv init` and `hv link` in sequence.
- ALWAYS use Bash tool for `hv` commands.
- If already linked (`.hivemind-link.json` exists), `hv link` refreshes the managed files.
