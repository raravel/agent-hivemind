# Feature: Plugin System (Skills & Hooks)

## Overview

Claude Code integration layer: 8 skills (Markdown-based) and 2 JavaScript hooks. Installed to `~/.claude/plugins/hv/` by `hv init`.

## Skills

Skills are Markdown files (`SKILL.md`) with YAML frontmatter that Claude Code loads as `/hv:*` commands.

### Skill Discovery & Registration

1. `hv init` calls `installer/skills.py:install_plugin()`
2. Plugin directory (`src/hivemind/plugin/`) is copied to `~/.claude/plugins/hv/`
3. `claude plugin marketplace add <path>` registers the local marketplace
4. `claude plugin install hv@hv-local --scope user` enables the plugin
5. Claude Code auto-discovers skills from `skills/*/SKILL.md`

### Skill List

| Skill | Trigger | Description |
|-------|---------|-------------|
| `/hv:init` | Manual | Initialize + link project |
| `/hv:clarify` | Auto on implementation requests | 7-axis ambiguity evaluation |
| `/hv:plan` | Manual | Write harness docs + decompose tasks |
| `/hv:task` | Manual | Execute task pipeline (10 stages) |
| `/hv:feedback` | Manual | Extract session lessons -> L2 |
| `/hv:search` | Manual | BM25 search with auto-read |
| `/hv:important` | Manual | L1 promotion/demotion |
| `/hv:audit` | Manual | Spec-code drift detection |

### Skill Anatomy

```markdown
---
name: skill-name
description: One line description
trigger: auto|manual
---

# /hv:skill-name -- Title

Description of when to use this skill.

## Execution

**Step 1.** Do something:
\`\`\`bash
hv some-command
\`\`\`

**Step 2.** Do something else...

## Rules

- ALWAYS do X
- NEVER do Y
```

### Key Skill Behaviors

**`/hv:clarify`** evaluates 7 axes:
- Purpose (Why), Scope, Technical Context (How), Integration (Fit), User/IO (Who/What), Done Criteria, Constraints
- Each axis scored 0.0–1.0
- Must pass: all axes <= 0.2
- Asks Socratic questions until passing

**`/hv:task`** pipeline has 10 stages:
1. Fetch task (`hv run`)
2. Mark `in_progress`
3. Load model profile from config
4. Read harness documents (MANDATORY)
5. Coding agent implementation
6. Test agent verification
7. Code review agent
8. Mark `done`
9. Record execution report
10. Extract feedback

## Hooks

JavaScript files that run automatically during Claude Code sessions.

### `hv-session-log.js`

- **Events**: `UserPromptSubmit`, `Stop`
- **Action**: Appends conversation messages to `level3/{project}/{date}_{session}.md`
- **Purpose**: L3 session log auto-capture

### `hv-pre-commit.js`

- **Event**: `PreToolUse` (matcher: `Bash`)
- **Action**: Detects `git commit` commands and reminds to update specs
- **Purpose**: Prevent spec-code drift

### Hook Installation

1. `hv init` calls `installer/hooks.py:install_hooks()`
2. JS files copied to `~/.claude/hooks/`
3. Hook entries merged into `~/.claude/settings.json` under `hooks.PreToolUse`
4. Duplicate detection: checks for existing `hv-` prefixed entries

### Hook Entry Format (settings.json)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/hooks/hv-pre-commit.js",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

## Model Profiles

Used by `/hv:task` pipeline to select models for each agent role:

| Profile | Planner | Executor | Reviewer |
|---------|---------|----------|----------|
| `quality` | opus | opus | opus |
| `balanced` | opus | sonnet | sonnet |
| `budget` | sonnet | sonnet | haiku |

Default: `balanced`. Change: `hv config --profile quality`.
