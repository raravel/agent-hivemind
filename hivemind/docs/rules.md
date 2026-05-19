# Rules

## NEVER

- NEVER add runtime dependencies beyond `click`, `rank-bm25`, `python-frontmatter`, `PyYAML` without explicit approval
- NEVER modify `~/.claude/settings.json` outside of the installer module (`installer/hooks.py`)
- NEVER store secrets, API keys, or credentials in the data directory
- NEVER break the YAML frontmatter format for task files — all parsers depend on it
- NEVER delete L2/L3 feedback documents — they are append-only; only L1 can be regenerated
- NEVER use interactive CLI prompts (`input()`, `click.prompt()`) in commands — all input via arguments/options/stdin
- NEVER skip type annotations on function signatures
- NEVER import from `commands/` inside `core/` — core modules must have no CLI dependencies
- NEVER modify the data directory schema version without a migration path in `commands/migrate.py`
- NEVER use `git push --force` in auto-commit or push commands
- NEVER force `auto_commit=True` in `_init_git` or any other code path — the default stays `False`; users opt in with `hv config set auto_commit true`
- NEVER create a `.md` file directly under `hivemind/tasks/` for a registered project — task files belong in `active/`, `done/`, or `archive/{YYYY-MM}/`

## ALWAYS

- ALWAYS use `from __future__ import annotations` in every Python module
- ALWAYS validate task status against `VALID_STATUSES` before writing (`pending`, `in_progress`, `in_review`, `rejected`, `done`)
- ALWAYS validate task type against the hierarchy rules (epic has no parent, story parent must be epic, task/bug/chore parent must be story/feature)
- ALWAYS call `auto_commit()` after data mutations if git integration is enabled
- ALWAYS use `encoding="utf-8"` when reading/writing files
- ALWAYS rebuild the BM25 index (`index.json`) after modifying L2 documents
- ALWAYS use `frontmatter.load()` / `frontmatter.dumps()` for parsing Markdown with YAML frontmatter — never manual string manipulation
- ALWAYS handle `FileNotFoundError` gracefully in core modules
- ALWAYS keep skills as Markdown files (`SKILL.md`) — no Python skill implementations
- ALWAYS preserve backward compatibility for `.hivemind.json` config reads (use `cfg.get()` which returns `None` for missing keys)
- ALWAYS write new tasks to `hivemind/tasks/active/<id>.md` and let `hv task update --status done` move them to `done/`; `hv task archive` is the only path into `archive/{YYYY-MM}/`
- ALWAYS pass the `path` keyword to `_update_task_index_entry` (or rely on its preservation of the existing path) when mutating a task — `_index.json` v2 records each task's location relative to `tasks_dir` so resolution skips directory scans
- ALWAYS bundle `hivemind/` changes (task state moves, reports, harness sync) into the same git commit as the related code change in skills/orchestrators — lesson saves are the documented exception

## Conventions

- Task IDs: `{PREFIX}-{NNN}` (e.g., `AGE-001`)
- L2 filenames: slugified title, max 60 chars, in category subdirectory
- Session log filenames: `{YYYYMMDD}_{short_session_id}.md`
- Feature spec filenames: `{NN}_{feature-name}.md`
- Config access: dot notation via `HivemindConfig.get("profiles.balanced.executor")`
- CLI output: `click.echo()` for normal output, `click.echo(..., err=True)` for errors
- Error handling: `raise click.ClickException(msg)` for CLI-level errors
