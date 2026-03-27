# agent-hivemind

A harness engineering toolkit for AI coding agents.

Structures and manages all the context an AI agent needs — from project initialization to task execution to feedback collection.

> **[한국어](README_ko.md)** 문서도 제공됩니다.

![agent-hivemind overview](docs/images/overview.webp)

## What is this?

When you tell an AI coding agent (like Claude Code) to "build me a todo app", it starts writing code immediately. But the result is usually incomplete — no architecture design, no library research, no completion criteria.

**agent-hivemind** fixes this by making the agent **think before it codes**:

```
"Build me a todo app"
        ↓
  /hv:clarify    ← 7-axis ambiguity check (what, why, how?)
        ↓
  /hv:plan       ← Write harness docs (architecture, tech stack, API specs)
                   + Decompose into tasks (with completion criteria)
        ↓
  /hv:task       ← Execute each task (read specs → code → test → review)
        ↓
  /hv:feedback   ← Save lessons learned from the session
```

## How it works

### Core concept: Harness Documents

Harness documents are project specs that agents reference during implementation. They live in `~/agent-hivemind-data/projects/{name}/`:

```
projects/my-app/
├── architecture.md      ← System structure, module boundaries (Mermaid diagrams)
├── tech-stack.md        ← Tech stack, library versions, usage patterns
├── build-verify.md      ← Build/test commands, CI pipeline
├── rules.md             ← NEVER/ALWAYS rules, constraints
└── features/
    ├── 00_auth.md       ← Auth feature detailed spec
    ├── 01_todo-crud.md  ← Todo CRUD API spec
    └── 02_dashboard.md  ← Dashboard UI spec
```

`/hv:plan` writes these documents **first**, then creates tasks. When the agent executes a task, it reads these docs and implements accurately.

### Feedback loop

Lessons learned by agents are managed in 3 tiers:

```
L3 (session logs)  →  L2 (structured lessons)  →  L1 (critical lessons)
   every conversation      BM25 dedup               promoted key insights
   auto-saved              categorized              important.md
```

- `hv search "query"` — searches past lessons, auto-increments hit count
- Lessons searched 3+ times get an L1 promotion suggestion
- Agents learn from past mistakes instead of repeating them

## Installation

```bash
pip install git+https://github.com/raravel/agent-hivemind.git
```

## Getting Started

### 1. Initialize

```bash
hv init
```

This single command:
- Creates `~/agent-hivemind-data/` data directory
- Installs the Claude Code plugin (8 `/hv:*` skills)
- Sets up model profiles (quality/balanced/budget)

### 2. Link a project

```bash
cd my-project
hv link
```

- Registers the project with the hivemind data repo
- Injects the mandatory `/hv:clarify` rule into CLAUDE.md
- All subsequent implementation requests trigger automatic requirement verification

### 3. Use

Just ask in natural language in Claude Code:

```
"Build me a todo app"
```

1. `/hv:clarify` auto-triggers — 7-axis ambiguity check
2. `/hv:plan` writes specs + decomposes into tasks
3. `/hv:task` executes tasks sequentially

Or invoke skills directly:

```
/hv:plan Plan this project
/hv:task Run the next task
/hv:search "auth lessons"
```

## Data Structure

```
~/agent-hivemind-data/
├── projects/                    ← Harness docs per project (specs)
│   └── {project}/
│       ├── architecture.md
│       ├── tech-stack.md
│       ├── build-verify.md
│       ├── rules.md
│       └── features/*.md
├── tasks/                       ← Issue tracker (replaces Linear)
│   └── {project}/
│       ├── PRJ-001.md           ← Task (frontmatter + body)
│       ├── PRJ-002.md
│       └── _reports/            ← Execution reports
├── level1/important.md          ← L1: Critical lessons (auto-generated)
├── level2/                      ← L2: Structured lessons
│   ├── frontend/
│   ├── backend/
│   ├── infra/
│   └── general/
├── level3/                      ← L3: Session logs
├── index.json                   ← BM25 search index
└── .hivemind.json               ← Global config
```

## Claude Code Plugin (`/hv:*`)

Automatically installed as a Claude Code plugin when you run `hv init`.

| Skill | Description | Auto-trigger |
|-------|-------------|--------------|
| `/hv:clarify` | 7-axis ambiguity check — mandatory before implementation | On implementation requests |
| `/hv:plan` | Write harness docs + decompose into tasks | — |
| `/hv:task` | Task execution pipeline (code → test → review) | — |
| `/hv:feedback` | Extract session feedback → save as L2 | — |
| `/hv:search` | BM25 knowledge search + hit counting | — |
| `/hv:important` | L1 promote/demote/regenerate | — |
| `/hv:audit` | Spec-code drift detection | — |
| `/hv:init` | Workspace initialization orchestration | — |

### `/hv:clarify` — Requirement Verification

Evaluates implementation requests across 7 ambiguity axes:

| Axis | Core Question |
|------|---------------|
| Purpose (Why) | Why build this? What problem does it solve? |
| Scope | Where does it start and end? |
| Technical Context (How) | What tech stack, environment, project? |
| Integration (Fit) | How does it fit with existing systems? Conflicts? |
| User/IO (Who/What) | Who uses it? What are inputs and outputs? |
| Done Criteria | What are the must_haves (truths, artifacts, key_links)? |
| Constraints | What must be followed or avoided? |

Asks Socratic questions until all axes score <= 0.2.

### `/hv:plan` — Planning

1. **Phase 1**: Write harness documents (research libraries → architecture → feature specs with Mermaid diagrams)
2. **Phase 2**: Decompose into tasks (completion criteria + spec references + dependencies)

### `/hv:task` — Task Execution

1. Fetch the next task (`hv run`)
2. Read harness documents (mandatory)
3. Run coding agent
4. Run test agent
5. Run code review agent
6. Mark complete + generate report

## CLI Reference

### Project Management

```bash
hv init [--path PATH] [--git]     # Initialize workspace
hv link [--name NAME]             # Link current project
hv push                           # Push data repo to remote
```

### Task Management

```bash
hv task create -p <project> -t "<title>" [--type feat] [--priority high] [--depends ID]
hv task list [-p <project>] [-s pending] [--priority high]
hv task get <ID> [--format json]
hv task update <ID> [--status in_progress] [--priority high]
hv task next [-p <project>]
hv run [-p <project>] [-t <ID>] [--format json]
```

### Feedback & Knowledge

```bash
hv feedback save -p <project> [--content FILE]    # Save L2 lesson
hv search "<query>" [-p <project>]                # BM25 search
hv important promote <path>                       # Promote to L1
hv important demote "<query>"                     # Demote from L1
hv important generate                             # Regenerate important.md
```

### Audit & Stats

```bash
hv audit -p <project> [--fix]                     # Spec-code drift detection
hv stats -p <project> [--since DATE]              # Execution metrics
```

### Configuration

```bash
hv config                                         # Show all config
hv config <key>                                   # Get value
hv config <key> <value>                           # Set value
hv config --profile balanced                      # Switch model profile
```

## Model Profiles

Configure which models to use for each agent role in the pipeline:

| Profile | Planner | Executor | Reviewer |
|---------|---------|----------|----------|
| `quality` | opus | opus | opus |
| `balanced` | opus | sonnet | sonnet |
| `budget` | sonnet | sonnet | haiku |

```bash
hv config --profile balanced    # default
```

## Inspiration

- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/)
- [Anthropic: Effective Harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Addy Osmani: Self-Improving Agents](https://addyosmani.com/blog/self-improving-agents/)

## License

MIT
