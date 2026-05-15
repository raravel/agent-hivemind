# Tech Stack

## Language & Runtime

- **Python 3.11+** — Core CLI and all backend logic
- **JavaScript (Node.js)** — Claude Code hooks only (`hv-session-log.js`, `hv-pre-commit.js`)
- **Markdown** — Skill definitions, task files, harness documents, feedback docs

## Build System

- **hatchling** — PEP 517 build backend (configured in `pyproject.toml`)
- **pip** — Package installation (`pip install git+...` or `pip install -e .[dev]`)

## Dependencies

### Runtime

| Package | Version | Usage |
|---------|---------|-------|
| `click` | >= 8.1 | CLI framework — groups, commands, options, arguments |
| `rank-bm25` | >= 0.2.2 | BM25Okapi algorithm for L2 document search and similarity |
| `python-frontmatter` | >= 1.0.0 | Parse/write YAML frontmatter in Markdown files |
| `PyYAML` | >= 6.0 | YAML serialization (used by python-frontmatter) |

### Development

| Package | Version | Usage |
|---------|---------|-------|
| `ruff` | >= 0.4.0 | Linting and formatting |
| `mypy` | >= 1.10.0 | Type checking (strict mode) |
| `pytest` | >= 8.0.0 | Testing framework |
| `build` | >= 1.0.0 | PEP 517 package builder |

## External Dependencies

- **Claude Code CLI** — Required for plugin installation (`claude plugin marketplace add`, `claude plugin install`). Skills and hooks run inside Claude Code.
- **git** — Used by `hv audit` (`git ls-files`), `hv push` (commit), and auto-commit functionality. Optional — the tool works without git if `auto_commit` is disabled.

## Project Structure

```
agent-hivemind/
├── pyproject.toml                    # Package config, dependencies, tool settings
├── src/hivemind/
│   ├── __init__.py                   # Version: "2.0.0"
│   ├── __main__.py                   # CLI entry — Click group, command registration
│   ├── commands/                     # CLI command implementations
│   │   ├── init.py                   # hv init — data dir setup, plugin install
│   │   ├── link.py                   # hv link — project linking
│   │   ├── task.py                   # hv task create/list/get/update/next
│   │   ├── run.py                    # hv run — fetch task for pipeline
│   │   ├── feedback.py               # hv feedback save — L2 lesson extraction
│   │   ├── search.py                 # hv search, search-read, index rebuild
│   │   ├── important.py              # hv important promote/demote/generate
│   │   ├── audit.py                  # hv audit — spec-code drift detection
│   │   ├── config_cmd.py             # hv config — read/write .hivemind.json
│   │   ├── commit.py                 # hv push — git commit
│   │   ├── migrate.py                # V1->V2 migration
│   │   └── stats.py                  # hv stats — project statistics
│   ├── core/                         # Core business logic
│   │   ├── config.py                 # HivemindConfig — .hivemind.json CRUD
│   │   ├── parser.py                 # Task frontmatter parse/validate/write
│   │   ├── indexer.py                # BM25 tokenize, index, search
│   │   ├── similarity.py             # find_similar() — BM25 dedup wrapper
│   │   └── git.py                    # auto_commit() — conditional git commit
│   ├── installer/                    # First-run installation logic
│   │   ├── skills.py                 # Plugin copy + Claude Code registration
│   │   ├── hooks.py                  # JS hook copy + settings.json merge
│   │   └── profiles.py               # Model profile configuration
│   └── plugin/                       # Claude Code plugin (copied to ~/.claude/)
│       ├── .claude-plugin/
│       │   ├── plugin.json           # Plugin metadata (name, version, entry)
│       │   └── marketplace.json      # Local marketplace metadata
│       ├── skills/                   # 8 skill directories
│       │   ├── init/SKILL.md
│       │   ├── clarify/SKILL.md + references/
│       │   ├── plan/SKILL.md + references/
│       │   ├── task/SKILL.md + references/
│       │   ├── feedback/SKILL.md + references/
│       │   ├── search/SKILL.md
│       │   ├── important/SKILL.md
│       │   └── audit/SKILL.md
│       └── hooks/                    # JavaScript hooks
│           ├── hooks.json            # Hook registration metadata
│           ├── hv-session-log.js     # L3 auto-logging
│           └── hv-pre-commit.js      # Spec update reminder
└── tests/
    ├── unit/                         # Isolated unit tests (tmp_path fixtures)
    └── integration/                  # E2E workflow tests
```

## Usage Patterns

### Click CLI Pattern

```python
@click.group()
def cli() -> None:
    """hv - Agent Hivemind CLI (v2)."""

@cli.command()
@click.option("--project", "-p", required=True)
def subcommand(project: str) -> None:
    cfg, data_path = _find_config()   # Locate .hivemind.json
    # ... business logic ...
    auto_commit(data_path, "message")  # Optional git commit
```

### Frontmatter Parse/Write Pattern

```python
from hivemind.core.parser import parse_task, update_frontmatter, create_task_file

# Read
fm, body = parse_task(path)           # Returns (dict, str)

# Update specific fields
update_frontmatter(path, {"status": "done", "updated": "2025-01-15"})

# Create new
create_task_file(path, frontmatter_dict, body_text)
```

### BM25 Search Pattern

```python
from hivemind.core.indexer import build_index, search, save_index

index_data = build_index(data_path)   # Scan level2/*.md
results = search("query text", index_data, top_k=5)  # [(path, score), ...]
save_index(index_data, data_path / "index.json")
```

### Config Access Pattern

```python
from hivemind.core.config import HivemindConfig

cfg = HivemindConfig.load(path)
value = cfg.get("profiles.balanced.executor")  # Dot notation
cfg.set("model_profile", "quality")
cfg.save()
```

## Entry Points

```toml
[project.scripts]
hv = "hivemind.__main__:cli"
hivemind = "hivemind.__main__:cli"
```

Both `hv` and `hivemind` commands point to the same Click group.

## Type Checking

- mypy strict mode enabled globally
- `frontmatter` and `rank_bm25` modules have `ignore_missing_imports = true` overrides (no type stubs available)
- All functions have explicit return type annotations
- `from __future__ import annotations` used in every module for forward compatibility
