---
description: "Task planning and decomposition with grounded harness documents. Use when the user wants to plan a project, create tasks, decompose a request into multiple tasks, manage existing tasks, or re-ground (refresh tech-stack against actual manifests/artifacts)."
---

# /hv:plan -- Task planning and decomposition

Plans a project by creating harness documents (specs) first, then decomposing work into concrete tasks with completion criteria.

## When to use

- User describes work that should be planned and decomposed into tasks
- User says "plan this", "make a plan", "break this down", "add tasks"
- User wants to create, list, view, update, or pick the next task
- User runs `/hv:plan` explicitly
- User asks to "re-ground" the harness or says the tech stack docs are wrong/stale → run **Re-grounding mode** (see below)

## Mode selection

Resolve `{project}` from `cat hivemind/link.json` (fallback: `cat .hivemind-link.json`). Check whether `hivemind/docs/` already has harness files (v5 in-repo layout).

Decision tree:

1. **`hivemind/docs/` is empty or absent.** Also count source files via `git ls-files | wc -l` (excluding `.md`, lockfiles, generated dirs).
   - ≥ 5 source files → **Bootstrap mode** (the codebase exists; reverse-engineer specs from observed code).
   - < 5 source files → **Full planning mode** (greenfield: Phase 0 → Phase 1 → Phase 2 from the user's intent).
2. **`hivemind/docs/` has files** → ask the user (one question):
   - **(a)** plan a new feature on top of the existing harness (Phase 0 refreshes tech-stack; Phase 1 writes the *new* feature file only; Phase 2 creates tasks), OR
   - **(b)** re-ground only — run Phase 0 and rewrite **only** `tech-stack.md`. Do not touch `architecture.md`, `features/*.md`, `rules.md`, or `verify.md`. No tasks created. Report "re-grounded".

   Default for (a)/(b) is (a) when the user said "plan", default is (b) when the user said "reground" / "fix tech-stack" / similar.

## Bootstrap mode (existing codebase, no specs yet)

When `hivemind/docs/` is empty and the repo already has code, you reverse-engineer the harness from what's actually there. Do NOT create tasks in this mode — the user explicitly requests planning afterwards.

**B.0 — Run Phase 0 Grounding** (manifest + build-artifact scan, vendored/legacy classification — same as the regular Phase 0 below).

**B.1 — Codebase walk.** `git ls-files` and bucket directories:
- code dirs (`src/`, `app/`, `routes/`, `lib/`)
- test dirs (`tests/`, `__tests__/`, `spec/`)
- asset dirs (`views/`, `public/`, `static/`, `templates/`)
- build/config (`Dockerfile`, `scripts/`, `.github/`)

**B.2 — Feature detection.** Group by structure:
- Subdirectories with multiple related files (`routes/target/`, `views/admin/`) → one feature per directory.
- Same-prefix files in a flat dir (`models/user.py`, `models/order.py`) → entity-based features.
- Single-file modules are typically utilities, NOT features.

For each detected feature, pick 2–5 representative files to seed `## Implementation`.

**B.3 — Convention detection.** Sample 3–5 large source modules:
- Language idioms (sync vs async; framework helpers vs vanilla).
- Explicit preference comments ("prefer X over Y").
- Naming conventions.

These feed `rules.md` under a `Observed — please confirm` heading so the user can promote or remove each item.

**B.4 — Draft writes (every spec via `hv spec write`).** Prefix each file's first line with the marker `> AI-drafted from existing code; review before relying.`

```bash
hv spec write tech-stack    -p <project> <<'EOF' ... EOF
hv spec write architecture  -p <project> <<'EOF' ... EOF
hv spec write rules         -p <project> <<'EOF' ... EOF
hv spec write verify        -p <project> <<'EOF' ... EOF
# For each detected feature:
hv spec write features/<slug> -p <project> <<'EOF' ... EOF
```

**B.5 — Review gate.** Output to the user:

```
Bootstrapped: N features (<list>), M active deps, K legacy libs, J inferred rules.

Review hivemind/docs/ and edit. Then:
- /hv:plan again — to add a NEW feature on top of these
- /hv:audit -p <project> — to verify code↔spec mapping
- hv harness-score show -p <project> — to score the bootstrap quality
```

Exit. Bootstrap creates NO tasks.

## Planning a new project or feature (Batch task creation)

When decomposing a larger request into tasks, you MUST follow this order:

### Phase 0: Grounding (MANDATORY — must complete before Phase 1)

Before writing any harness prose, ground the planner in the **actual repository state**. The point: tech-stack content must be derivable from manifests and build artifacts, not from agent memory. Past planner runs have hallucinated wrong major versions (e.g. listing Tailwind v3 in a project running v4) and listed legacy/vendored libraries as if they were active stack — this step prevents that.

Run all four sub-steps. Use Bash + Read; no special tooling required.

**0.1 — Detect ecosystems.** Check for the presence of these manifest files at the project root (and one level down for monorepos):

```
package.json | pnpm-workspace.yaml | yarn.lock      # Node
pyproject.toml | requirements*.txt | setup.cfg      # Python
Cargo.toml | Cargo.lock                             # Rust
go.mod                                              # Go
Gemfile | Gemfile.lock                              # Ruby
composer.json                                       # PHP
pom.xml | build.gradle*                             # JVM
*.csproj | packages.config                          # .NET
```

Record every manifest found.

**0.2 — Extract active dependencies with pinned versions.** For each manifest, read it and list every direct dependency with its version constraint. Examples of acceptable forms: `^5.1.0`, `~1.2.3`, `1.2.3`, `>=2,<3`. Reject `latest` or `*` — note them as unpinned.

**0.3 — Scan build artifacts for version headers.** Many bundlers/compilers stamp version comments in their output. Check the first 5 lines of every `*.css` and `*.js` under directories named `dist/`, `build/`, `public/`, `static/`, or any `tailwind*.css`/`tailwind*.out.css`. Typical pattern: `/*! libname vX.Y.Z | LICENSE | url */`. Treat artifact versions as **ground truth** — if the manifest says one major version but the artifact header says another, the artifact wins.

**0.4 — Classify vendored / legacy assets.** Find script/style tags or files referencing libraries that are NOT in any manifest:

```bash
grep -rE '<script[^>]+src=' <views_or_templates_dir> 2>/dev/null
grep -rE '<link[^>]+rel="stylesheet"' <views_or_templates_dir> 2>/dev/null
```

Any library detected here but absent from manifests → classify `legacy/vendored`. If `rules.md` already exists and discourages this library (phrases like "prefer X over Y", "avoid jQuery", "vanilla JS only"), explicitly mark it `legacy` in the upcoming tech-stack.md.

**0.5 — Cross-check before writing.** Before proceeding to Phase 1, output a short grounding summary to the user:

```
Detected manifests: package.json
Active deps (15): express ^5.1.0, ejs ^3.1.10, ...
Build artifact versions: tailwindcss v4.1.18 (views/inc/css/tailwind.css)
Legacy / vendored: jquery 3.7.1 (views/inc/js/jquery-3.7.1.min.js)
Unresolved: <anything you couldn't categorize>
```

This summary must appear in the user-visible message before Phase 1 starts. If anything is ambiguous, ask before proceeding — do not guess.

### Phase 1: Harness Documents (MANDATORY before creating tasks)

Before creating ANY tasks, write harness documents to `hivemind/docs/` in the linked project repo (v5 layout). Phase 0's grounding output feeds directly into `tech-stack.md` below.

Research what you need (library docs, API specs, etc.) via web search BEFORE writing these documents. The documents must contain enough detail for an agent to implement each task without asking questions.

#### Decision Point Escalation Protocol (DPEP) — MANDATORY

The harness is the single source of truth: it must present one path, not a menu. **Never** leave multiple-choice content in `architecture.md`, `tech-stack.md`, `rules.md`, `verify.md`, `features/*.md`, or any task body. The moment a fork appears while drafting, stop and escalate.

**Trigger.** Halt drafting and run DPEP when any of these arise:

1. Two or more candidate libraries / patterns could satisfy the same role (Redis vs Memcached for cache, REST vs GraphQL for transport, polling vs SSE for live updates).
2. A policy value is unstated by the user (rate-limit threshold, retention window, page size, timeout, error wording shown to end-users).
3. Phase 0 evidence conflicts with the user's stated intent (manifest pins v3 but the conversation assumed v4).
4. Two competing conventions coexist in the codebase and Bootstrap mode B.3 cannot decide which to canonicalize.
5. A spec section would otherwise need the words "either", "or alternatively", "could be", "Option A/B", or "TBD — choose later".

**Escalation format.** Call `AskUserQuestion` with exactly this shape (do not fall back to plain text):

- `question`: one sentence, of the form `"Which X should the harness commit to?"`
- 2–4 `options`. The recommended option goes FIRST, with the literal suffix ` (Recommended)` appended to its `label`.
- Each option's `description` MUST be a single line in this format:
  `Pros: <1–2 short pros>. Cons: <1–2 short cons>. Recommendation: <★★★|★★☆|★☆☆> — <one-line reason>.`
- Use `preview` only when a diagram, schema, or code snippet meaningfully clarifies the choice. Keep previews under 12 lines.

Do not write any harness file before the user answers. Do not guess. Do not "pick the obvious one" silently.

**After the user answers — record the decision.** Immediately write an ADR-lite entry via the CLI (no Write/Edit on the file directly):

```bash
hv spec write decisions/<slug> -p <project> <<'EOF'
# Decision NN: <title>
- Date: YYYY-MM-DD
- Status: Accepted
- Context: <one short paragraph — what fork was hit, where in the plan>
- Considered:
  - <Option 1 label> — Pros: …. Cons: …. Recommendation: ★★★.
  - <Option 2 label> — Pros: …. Cons: …. Recommendation: ★★☆.
- Chosen: <label of the option the user picked>
- Rationale: <user's own reason, or the recommendation reason confirmed by the user>
- Impact: <list of harness files that will reflect this choice>
EOF
```

`decisions/` is auto-numbered (`hivemind/docs/decisions/NN_<slug>.md`) by `hv spec write`, the same way `features/` is.

**Write the harness body with the chosen path only.** The harness file must read as a single-path commitment. Reference the decision in exactly one footnote line:

```markdown
> Decision: see [[decisions/NN_<slug>]] — alternatives evaluated, not pursued.
```

The non-chosen options never appear in the harness. Their evaluation lives only in the decision file.



**Write every spec via the `hv spec write` CLI** — do NOT use Write/Edit tools on these files directly. The CLI resolves the v5 location, writes atomically, and prints the resolved path on stdout. Use a heredoc to pipe content:

```bash
hv spec write tech-stack -p <project> <<'EOF'
# ...content...
EOF
```

For per-feature files, the CLI auto-numbers `features/NN_<slug>.md`:

```bash
hv spec write features/<slug> -p <project> <<'EOF'
# ...feature spec...
EOF
```

After `hv spec write`, the stdout contains the resolved path. If you previously had the file via `@import`, re-read it with the Read tool — the in-context copy is now stale.

Spec files to produce (each via `hv spec write`):

1. **`architecture.md`** — System architecture, module boundaries, data flow
   - Component diagram using **Mermaid** (`graph TD`, `flowchart`, `C4Context`, etc.)
   - Dependency direction rules
   - Key design decisions and rationale

2. **`tech-stack.md`** — Technology choices grounded in Phase 0 output. **Required sections, in this order:**

   ````markdown
   # <Project> Tech Stack

   ## Active Dependencies
   <Every manifest-listed dependency with pinned version. Use `- name version — one-line role/rationale` format so the rubric counts it as a versioned library.>
   - express ^5.1.0 — HTTP server (middleware composability)
   - ejs ^3.1.10 — server-rendered templates (existing convention)

   ## Build Artifacts
   <Versions detected from compiled output headers in Phase 0.3. Ground truth for the running app — if this disagrees with Active Dependencies, the artifact wins.>
   - tailwindcss v4.1.18 (from `views/inc/css/tailwind.css` header)

   ## Legacy / Vendored
   <Libraries in the repo but NOT in any manifest. Treat as read-only unless `rules.md` explicitly permits new use.>
   - jquery 3.7.1 — vendored at `views/inc/js/jquery-3.7.1.min.js`; new code uses vanilla JS per rules.md

   ## Project Structure
   <Directory layout, key paths.>

   ## Rationale
   <At least one "why this, not X" — required for tech_stack rubric anchor 10.>
   ````

   Rules for this file:
   - Every entry in `## Active Dependencies` MUST appear in at least one detected manifest. If it doesn't, move it to `## Legacy / Vendored` with a note.
   - Pinned version is required (`^1.2.3`, `>=1,<2`, `1.2.3`). `latest` and `*` are not versions.
   - Do NOT carry over library names from a previous tech-stack.md without verifying they still exist. Re-derive from Phase 0 each time.

3. **`verify.md`** — Verification commands (language-agnostic)
   - **What the orchestrator runs to confirm a task is complete.**
   - Any executable command is fine: lint, type check, unit test, integration test, build, smoke test, schema validation, contract test, etc.
   - Group commands by stage (`lint`, `type`, `test`, `build`) when the project distinguishes them; otherwise one `check` stage is enough.
   - Each entry: the command string + what it proves (one sentence).
   - Examples:
     - Python project: `ruff check .` / `mypy src/` / `pytest -q`
     - Node project: `npm run lint` / `npm run typecheck` / `npm test`
     - Go project: `go vet ./...` / `go test ./...`
     - Any language: project-defined scripts like `make check`, `./scripts/verify.sh`
   - NEVER assume a language. The project's verify.md is the single source of truth for what "done" means operationally.
   - Legacy: `build-verify.md` is accepted as a fallback for v2 projects. New projects use `verify.md`.

4. **`rules.md`** — NEVER/ALWAYS rules, forbidden files, constraints
   - Security rules, coding conventions
   - Files that should not be modified

5. **`features/`** — One file per feature with detailed spec
   - `features/00_feature-name.md` — Inputs, outputs, UI flow, API endpoints, edge cases
   - Include **Mermaid** diagrams for data flow, sequence diagrams, state machines, ER diagrams where appropriate
   - Include enough detail that an agent can implement without ambiguity
   - Reference specific library APIs, data models, route paths
   - **Required `## Implementation` section** at the end of each feature file. Format:

     ````markdown
     ## Implementation
     - `views/target/js/assign.js` — primary UI + state management
     - `routes/target/assign.js` — backend length validation
     - external: `@plab/util` (mssql helper used by routes)
     ````

     This section is the code↔spec map that `hv audit` walks and `/hv:task` updates after each merge. On initial creation you may list only the paths you intend to use; tasks will refine this list as they run.

### Diagram Rules

Use **Mermaid** for all diagrams in harness documents:

- **Architecture / component relationships**: `graph TD` or `flowchart`
- **API / interaction flow**: `sequenceDiagram`
- **Data models / DB schema**: `erDiagram`
- **State machines / status transitions**: `stateDiagram-v2`
- **Task dependencies**: `graph LR` with `-->` edges

Example:
````markdown
```mermaid
graph TD
    A[Client] --> B[API Server]
    B --> C[Database]
    B --> D[Cache]
```
````

### Phase 2: Task Creation (Hierarchical)

After harness documents are written, create tasks using a hierarchy: **Epic → Story → Task**.

**Create in this order:**

```bash
# 1. Create the epic (top-level grouping)
hv task create -p <project> -t "Add deadlines" --type epic --priority high

# 2. Create stories under the epic
hv task create -p <project> -t "Backend API" --type story --parent <EPIC-ID> --priority high
hv task create -p <project> -t "Frontend UI" --type story --parent <EPIC-ID> --depends <STORY1-ID>

# 3. Create tasks under each story
hv task create -p <project> -t "Create deadline API" --type task --parent <STORY-ID> --priority high
hv task create -p <project> -t "Update deadline API" --type task --parent <STORY-ID> --depends <PREV-TASK-ID>
```

**Hierarchy rules:**
- `epic`: top-level grouping, no parent
- `story`: groups related tasks, parent must be an epic
- `task`/`bug`/`chore`: actual work items, parent must be a story

**DPEP also applies here.** Before writing a task body or completion criterion, run the same trigger check (see Phase 1). A completion criterion of the form "X works **or** Y works" is forbidden — escalate, record an ADR, then commit a single-path criterion.

**After creating each task via CLI, IMMEDIATELY write the body via `hv task body-set <id>`:**

```bash
hv task body-set <TASK-ID> <<'EOF'
## Description
What this task implements and why.

## Spec References
- [[architecture]] `../docs/architecture.md` — relevant section
- [[features/00_feature-name|00_feature-name]] `../docs/features/00_feature-name.md` — full feature spec

## Completion Criteria
- [ ] Criterion 1 (concrete, verifiable)
- [ ] Criterion 2 (concrete, verifiable)
- [ ] Build/lint passes
- [ ] Tests pass (if applicable)
EOF
```

**Link format.** Task files live at `hivemind/tasks/<TASK-ID>.md`, so spec references MUST be file-relative paths (one `..` to reach the `hivemind/` namespace, then `docs/...`). Each bullet in `## Spec References` pairs an Obsidian wikilink with a backtick relative path so the same line is clickable in Obsidian and resolves in code editors. Wikilink aliases (`[[features/01_auth|01_auth]]`) keep the visible label short while disambiguating identical stems across `features/` and `decisions/`. Do NOT write legacy `projects/{project}/...` or root-relative `hivemind/docs/...` paths — both break navigation from inside a task file. `hv migrate --to v5.1` rewrites existing task bodies if older content is present.

Use `hv task body-append <id>` to extend a body and `hv task criteria-add <id> "<text>"` / `hv task criteria-check <id> <n>` to manage completion criteria — never edit task `.md` files with Write/Edit.

**Completion criteria rules:**
- Each criterion must be objectively verifiable (not "works well" but "returns 200 on POST /api/todos")
- Include at least one build/lint criterion
- Include functional criteria (what the code must do)
- Include integration criteria if the task touches multiple modules

3. **Wire dependencies** — Use `--depends` for tasks that require previous tasks to be done first
4. **Present the full plan** — List all tasks with their IDs, dependencies, and priorities at the end
5. **Commit the plan as one git commit.** `hv task create` writes `.md` files under `hivemind/tasks/active/` and refreshes `hivemind/tasks/_index.json` — but `auto_commit` is OFF by default, so nothing lands in git yet. After every task in the plan is created, stage the new files and any harness doc updates (`hivemind/docs/...`) and commit them as a single user-facing commit:

   ```bash
   git -C <project_root> add hivemind/
   git -C <project_root> commit -m "plan: <short-summary>"
   ```

   This keeps `git log` to one line per plan instead of one line per task created.

## Managing existing tasks

### Listing tasks

```bash
hv task list
hv task list -p <project>
hv task list -p <project> -s pending
hv task list --priority high
```

### Getting task details

```bash
hv task get <TASK-ID>
hv task get <TASK-ID> --format json
```

### Updating a task

```bash
hv task update <TASK-ID> --status <pending|in_progress|done|blocked|cancelled>
hv task update <TASK-ID> --priority high
hv task update <TASK-ID> --title "New title"
```

### Getting the next task

```bash
hv task next
hv task next -p <project>
```

## Task file format

See [references/task-format.md](references/task-format.md) for the frontmatter schema.

## Important Rules

- **NEVER skip Phase 0.** Tech-stack content must be grounded in manifests + build artifacts, not agent memory. Past runs have hallucinated wrong major versions and the lesson is mandatory grounding.
- **NEVER create tasks before writing harness documents.** Phase 1 MUST complete before Phase 2.
- **NEVER create a task without a body.** Every task must have description, spec references, and completion criteria.
- **NEVER carry library names from a previous tech-stack.md without re-verifying** against the current manifests + artifacts (Phase 0).
- **NEVER write multi-option content into harness files or task bodies.** Banned phrasings: `Option A/B`, `either … or …`, `alternatively`, `could use`, `TBD — choose`, `pick later`. A harness must be a single path, not a menu.
- **NEVER pick between candidates silently.** When a fork is hit, invoke DPEP (Phase 1) — present options to the user via `AskUserQuestion` with pros/cons/recommendation and wait for their choice.
- **ALWAYS record decisions** via `hv spec write decisions/<slug>` immediately after the user answers, before drafting the harness body that depends on the choice.
- **ALWAYS reference a decision** from the affected harness section as a one-line footnote (`> Decision: see [[decisions/NN_<slug>]]`). The non-chosen options must not appear in the harness.
- **ALWAYS research before writing specs.** Use web search to get accurate library APIs, configuration formats, and best practices.
- **ALWAYS use the `hv task` / `hv spec` CLI** via Bash tool for creating, updating, and writing spec or task content. Direct Write/Edit on files under `hivemind/docs/` or `hivemind/tasks/` is forbidden.
- **ALWAYS include a `## Implementation` section in every feature file.** Even an initial intent-only list is fine — tasks will refine it.
- NEVER create a task without a `--project` flag.
- ALWAYS validate that the project exists (was linked via `hv link`) before creating tasks.
- NEVER write task/spec content in Korean. All content must be in English for BM25 consistency.
- When decomposing work, prefer smaller focused tasks over large monolithic ones.
