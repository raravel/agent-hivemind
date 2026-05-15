# Feature: CLI Core (`hv`)

## Overview

Python CLI built with Click that provides all project management, task tracking, knowledge base, and audit operations. Entry point: `hivemind.__main__:cli`.

## Commands

### `hv init [--path PATH] [--git]`
- Creates `~/agent-hivemind-data/` with full directory structure
- Installs Claude Code plugin via `installer/skills.py`
- Registers hooks via `installer/hooks.py`
- Configures model profiles via `installer/profiles.py`
- Idempotent — safe to run multiple times

### `hv link [--name NAME]`
- Creates `.hivemind-link.json` in project root
- Registers project in `.hivemind.json` with auto-generated prefix (first 3 chars of name, uppercase)
- Creates `projects/{name}/`, `tasks/{name}/`, `level3/{name}/` directories
- Appends project info to project's `CLAUDE.md`
- Skips if already linked

### `hv config [KEY] [VALUE] [--profile PROFILE]`
- Read: `hv config model_profile` -> `"balanced"`
- Write: `hv config model_profile quality`
- Dot notation: `hv config profiles.balanced.executor`
- Profile shortcut: `hv config --profile quality`

### `hv push`
- Runs `git add -A && git commit` in the data directory
- Only works if `auto_commit` is enabled

### `hv stats`
- Shows project statistics (task counts by status, etc.)

## Config Schema (`.hivemind.json`)

```json
{
  "version": "2.0.0",
  "data_path": "~/agent-hivemind-data",
  "git_enabled": false,
  "auto_commit": false,
  "model_profile": "balanced",
  "profiles": {
    "quality": { "planner": "opus", "executor": "opus", "reviewer": "opus" },
    "balanced": { "planner": "opus", "executor": "sonnet", "reviewer": "sonnet" },
    "budget": { "planner": "sonnet", "executor": "sonnet", "reviewer": "haiku" }
  },
  "projects": {
    "my-app": { "prefix": "MYA", "linked_path": "/path/to/my-app", "counter": 5 }
  },
  "filter_patterns": []
}
```

## `.hivemind-link.json` Schema

```json
{
  "project": "my-app",
  "data_path": "~/agent-hivemind-data"
}
```
