# agent-hivemind

Harness engineering toolkit for AI coding agents.

## Installation

```bash
pip install agent-hivemind
```

## Quick Start

```bash
# Initialize a hivemind workspace
hv init

# Link an agent to the workspace
hv link

# Create a task
hv task create
```

## Features

- **Task Management** -- Create, assign, and track tasks across agents with `hv task`.
- **Feedback Loops** -- Structured feedback collection and L2-format reporting via `hv feedback`.
- **Search** -- BM25-powered semantic search across workspace documents with `hv search`.
- **Important Lessons** -- Capture and surface critical learnings with `hv important`.
- **Audit** -- Verify workspace integrity and agent compliance with `hv audit`.
- **Run Pipelines** -- Execute multi-stage agent pipelines with `hv run`.
- **Statistics** -- View workspace and agent metrics with `hv stats`.

## Claude Code Integration

agent-hivemind ships with built-in support for [Claude Code](https://docs.anthropic.com/en/docs/claude-code):

- **Skills** -- Slash-command skills (`/hv-task`, `/hv-feedback`, `/hv-search`, etc.) installed into `.claude/commands/`.
- **Hooks** -- Pre-commit hooks that enforce task workflow discipline.
- **Model Profiles** -- Preconfigured model settings for optimal agent behaviour.

Install integrations with:

```bash
hv link
```

## CLI Reference

| Command | Description |
|---|---|
| `hv init` | Initialize a hivemind workspace |
| `hv link` | Link an agent to the workspace |
| `hv push` | Push local changes to the remote |
| `hv task` | Manage tasks (create, list, show, update) |
| `hv run` | Execute an agent pipeline |
| `hv feedback` | Manage feedback (add, list, summarize) |
| `hv search` | Search workspace documents |
| `hv important` | Manage important lessons (add, list) |
| `hv audit` | Audit workspace integrity |
| `hv stats` | View workspace statistics |
| `hv log` | Manage agent logs (start, append, end) |
| `hv filter` | Filter content from a file |
| `hv index` | Manage search index (build, status) |
| `hv config` | View and set configuration |

## License

MIT
