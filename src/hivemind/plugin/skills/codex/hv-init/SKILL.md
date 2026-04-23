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
- Creates `.hivemind-link.json` in the project root (POSIX-normalized paths)
- Creates `projects/{name}/`, `tasks/{name}/`, `level3/{name}/` in the data directory
- Registers the project in `.hivemind.json`
- Writes a managed `AGENTS.md` block as the canonical shared instructions file
- Writes repo-local `.codex/hooks.json`
- Updates `.hivemind-link.json` targets to include `codex`

**Step 3.** If this is an existing v2 installation, run the migration:

```bash
hv migrate --to v3
```

This normalizes any Windows-style paths in `.hivemind-link.json`, removes any
legacy `obsidian-import` line from `CLAUDE.md`, renames `build-verify.md` →
`verify.md`, archives old per-prompt L3 files, and reseeds model profile IDs
for both runtimes, plus pricing + parallel sections in `.hivemind.json`.
Running twice is a no-op.

**Step 4.** Report what was done and suggest next steps:
- "Use the hv plugin to plan the project next."

## Rules

- ALWAYS run both `hv init` and `hv link` in sequence.
- ALWAYS use Bash tool for `hv` commands.
- If already linked (`.hivemind-link.json` exists), `hv link` refreshes the managed files.
