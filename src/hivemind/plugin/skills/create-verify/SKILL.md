---
description: "Create or regenerate verify.md for the linked project. Use when hv doctor reports 'neither verify.md nor build-verify.md', or when the user wants to define/update verification commands. Args: brief description of the tech stack or verification approach (e.g. 'Node.js, jest, eslint, tsc')."
---

# /hv:create-verify — Generate verify.md for a project

Creates `verify.md` in the project's harness spec directory. This file is the single source of truth for what "done" means operationally — `/hv:task` reads it to run verification after every task.

## When to use

- `hv doctor` reports missing `verify.md`
- User runs `/hv:create-verify` explicitly (with or without args)
- User asks to update/regenerate verification commands

## Steps

### 1. Find the project

Read `.hivemind-link.json` in cwd:

```bash
cat .hivemind-link.json
```

Extract `project` (name) and `data_path`. If the file is missing, ask the user to run `/hv:init` first.

Construct the target path:
```
{data_path}/projects/{project}/verify.md
```

### 2. Gather tech stack context

Read these files (skip if missing — do not fail):

- `{data_path}/projects/{project}/tech-stack.md` — primary source
- `{data_path}/projects/{project}/architecture.md` — secondary hints
- The user's args (passed when invoking this skill) — highest priority

If none of the above provide usable information, scan the project root for well-known config files to infer the stack:

| File present | Likely stack |
|---|---|
| `pyproject.toml` / `setup.py` | Python |
| `package.json` + no `tsconfig.json` | Node.js / JavaScript |
| `package.json` + `tsconfig.json` | TypeScript / Node.js |
| `go.mod` | Go |
| `Cargo.toml` | Rust |
| `pom.xml` / `build.gradle` | Java / Kotlin |
| `Makefile` only | Language-agnostic Make |

If still unclear, ask the user one question: "What language/toolchain does this project use?"

### 3. Draft the verify.md content

Write sections appropriate for the detected stack. Use the templates below as starting points — adapt commands to match what the project actually uses.

**Always include these sections (rename/omit if genuinely inapplicable):**

- `## lint` — static analysis / style
- `## type` — type checking (omit if dynamic language with no type annotations)
- `## test` — test runner
- `## build` — artifact build or packaging verification
- `## completion` — done criteria (always required)

#### Python template

```markdown
# Verification commands

Commands the `/hv:task` orchestrator runs to confirm a task is complete.
Each stage is independent; run in any order.

## lint

Static analysis. Fails on any reported issue.

\`\`\`bash
python3 -m ruff check src/ tests/
\`\`\`

## type

Type-checks the implementation (not tests — tests are intentionally loose).

\`\`\`bash
python3 -m mypy src/
\`\`\`

## test

Full test suite (unit + integration). Must fully pass.

\`\`\`bash
python3 -m pytest
\`\`\`

## build

Wheel build verification. Catches packaging regressions.

\`\`\`bash
python3 -m build --wheel
\`\`\`

## completion

A task is considered done when:

- all stages above pass on the current branch
- the task's completion criteria checklist is fully `[x]`
- the 4-axis review rubric has `correctness >= 7`, `spec_compliance >= 7`, `safety >= 8`
- `hv harness-score show -p {project} --if-fresh 7d` either exits 0
  (cached score is fresh) or the task explicitly refreshed the score
```

#### TypeScript / Node.js template

```markdown
# Verification commands

Commands the `/hv:task` orchestrator runs to confirm a task is complete.
Each stage is independent; run in any order.

## lint

\`\`\`bash
npx eslint src/
\`\`\`

## type

\`\`\`bash
npx tsc --noEmit
\`\`\`

## test

\`\`\`bash
npx jest --passWithNoTests
\`\`\`

## build

\`\`\`bash
npm run build
\`\`\`

## completion

A task is considered done when:

- all stages above pass on the current branch
- the task's completion criteria checklist is fully `[x]`
- the 4-axis review rubric has `correctness >= 7`, `spec_compliance >= 7`, `safety >= 8`
- `hv harness-score show -p {project} --if-fresh 7d` either exits 0
  (cached score is fresh) or the task explicitly refreshed the score
```

#### Go template

```markdown
# Verification commands

## lint

\`\`\`bash
golangci-lint run ./...
\`\`\`

## type

Go is statically typed — `go build` covers this.

\`\`\`bash
go build ./...
\`\`\`

## test

\`\`\`bash
go test ./...
\`\`\`

## build

\`\`\`bash
go build -o /dev/null ./cmd/...
\`\`\`

## completion

A task is considered done when:

- all stages above pass on the current branch
- the task's completion criteria checklist is fully `[x]`
- the 4-axis review rubric has `correctness >= 7`, `spec_compliance >= 7`, `safety >= 8`
- `hv harness-score show -p {project} --if-fresh 7d` either exits 0
  (cached score is fresh) or the task explicitly refreshed the score
```

#### Make / language-agnostic template

```markdown
# Verification commands

## lint

\`\`\`bash
make lint
\`\`\`

## test

\`\`\`bash
make test
\`\`\`

## build

\`\`\`bash
make build
\`\`\`

## completion

A task is considered done when:

- all stages above pass on the current branch
- the task's completion criteria checklist is fully `[x]`
- the 4-axis review rubric has `correctness >= 7`, `spec_compliance >= 7`, `safety >= 8`
- `hv harness-score show -p {project} --if-fresh 7d` either exits 0
  (cached score is fresh) or the task explicitly refreshed the score
```

### 4. Write the file

Replace `{project}` in the `## completion` section with the actual project name from step 1.

Write the result to `{data_path}/projects/{project}/verify.md` using the Write tool.

If `build-verify.md` exists at the same path, leave it — do NOT delete it. Instead, note that `hv migrate --to v3` will clean it up.

### 5. Verify with doctor

```bash
hv doctor
```

Confirm "Project verify.md" is now OK (green). If it still shows XX, report the exact error to the user.

### 6. Report to the user

Show:
- The path where `verify.md` was written
- A brief summary of the stages it covers
- If any stage needs a tool not yet installed (e.g. `golangci-lint`, `ruff`), call that out explicitly

## Rules

- NEVER hardcode language-specific tools for a project whose stack is clearly different. E.g. do not write `pytest` for a Go project.
- ALWAYS include the `## completion` section with the harness-score freshness check.
- ALWAYS substitute the real project name into the `## completion` section.
- Do NOT modify any other harness documents (`architecture.md`, `rules.md`, etc.) — this skill only touches `verify.md`.
- If the user provides explicit commands in their args (e.g. `/hv:create-verify make lint && make test`), use those as-is in the relevant sections. Don't second-guess the user's commands.
