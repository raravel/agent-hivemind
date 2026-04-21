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
- Creates `.hivemind-link.json` in the project root (POSIX-normalized paths)
- Creates `projects/{name}/`, `tasks/{name}/`, `level3/{name}/` in the data directory
- Registers the project in `.hivemind.json`
- Appends a `# Hivemind Project` block to `CLAUDE.md` with native `@import`
  references to `architecture.md` and `rules.md` so Claude auto-loads them

**Step 3.** If this is an existing v2 installation, run the migration:

```bash
hv migrate --to v3
```

This normalizes any Windows-style paths in `.hivemind-link.json`, removes any
legacy `obsidian-import` line from `CLAUDE.md`, renames `build-verify.md` →
`verify.md`, archives old per-prompt L3 files, and reseeds model profile IDs
(`claude-opus-4-7` / `claude-sonnet-4-6` / `claude-haiku-4-5`) and the
pricing + parallel sections in `.hivemind.json`. Running twice is a no-op.

**Step 4.** Report what was done and suggest next steps:
- "Run `/hv:plan` to plan your project"

## Rules

- ALWAYS run both `hv init` and `hv link` in sequence.
- ALWAYS use Bash tool for `hv` commands.
- If already linked (`.hivemind-link.json` exists), `hv link` will skip automatically.
