# agent-hivemind

A harness engineering toolkit for AI coding agents.

Structures and manages all the context an AI agent needs — from project initialization to task execution to feedback collection.

> **[한국어](#한국어)** 문서는 아래에 있습니다.

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

---

# 한국어

AI 코딩 에이전트를 위한 하네스 엔지니어링 툴킷.

## 이게 뭔가요?

AI 코딩 에이전트(Claude Code 등)에게 "투두리스트 만들어줘"라고 하면, 에이전트는 바로 코드를 작성하기 시작합니다. 하지만 결과물은 대개 불완전합니다 — 아키텍처 설계 없이, 라이브러리 조사 없이, 완료 조건 없이 작업하기 때문입니다.

**agent-hivemind**은 에이전트가 코드를 짜기 전에 **생각하게** 만드는 시스템입니다:

```
"투두리스트 만들어줘"
        ↓
  /hv:clarify    ← 7축 모호성 검증 (무엇을, 왜, 어떻게?)
        ↓
  /hv:plan       ← 하네스 문서 작성 (아키텍처, 기술 스택, API 명세)
                   + 태스크 분해 (완료 조건 포함)
        ↓
  /hv:task       ← 태스크별 실행 (스펙 읽기 → 코딩 → 테스트 → 리뷰)
        ↓
  /hv:feedback   ← 세션에서 배운 교훈 저장
```

## 어떻게 작동하나요?

### 핵심 개념: 하네스 문서

하네스 문서는 에이전트가 작업할 때 참조하는 프로젝트 스펙입니다. `~/agent-hivemind-data/projects/{name}/`에 저장됩니다:

```
projects/my-app/
├── architecture.md      ← 시스템 구조, 모듈 경계 (Mermaid 다이어그램)
├── tech-stack.md        ← 기술 스택, 라이브러리 버전, 사용법
├── build-verify.md      ← 빌드/테스트 명령어, CI 파이프라인
├── rules.md             ← NEVER/ALWAYS 규칙, 금지 사항
└── features/
    ├── 00_auth.md       ← 인증 기능 상세 스펙
    ├── 01_todo-crud.md  ← 투두 CRUD API 명세
    └── 02_dashboard.md  ← 대시보드 UI 스펙
```

`/hv:plan`이 이 문서들을 **먼저** 작성하고, 그 다음에 태스크를 만듭니다. 에이전트가 태스크를 실행할 때 이 문서를 읽고 정확한 구현을 합니다.

### 피드백 루프

에이전트가 작업하면서 배운 교훈을 3단계로 관리합니다:

```
L3 (세션 로그)  →  L2 (구조화된 교훈)  →  L1 (핵심 교훈)
   모든 대화           BM25 중복 제거          승격된 중요 교훈
   자동 저장           카테고리 분류            important.md
```

- `hv search "query"` — 과거 교훈을 검색하면 히트 카운트 자동 증가
- 3회 이상 검색된 교훈은 L1 승격 제안
- 에이전트가 같은 실수를 반복하지 않도록 학습

## 설치

```bash
pip install git+https://github.com/raravel/agent-hivemind.git
```

## 시작하기

```bash
# 1. 초기화 — 데이터 폴더 + 플러그인 설치
hv init

# 2. 프로젝트 연결 — CLAUDE.md에 규칙 주입
cd my-project
hv link

# 3. 사용 — 자연어로 요청
# Claude Code에서: "투두리스트 앱 만들어줘"
# → /hv:clarify 자동 호출 → /hv:plan → /hv:task
```

## 스킬 목록

| 스킬 | 설명 |
|------|------|
| `/hv:clarify` | 7축 모호성 검증 — 구현 요청 시 자동 호출 |
| `/hv:plan` | 하네스 문서 작성 + 태스크 분해 |
| `/hv:task` | 태스크 실행 파이프라인 (코딩 → 테스트 → 리뷰) |
| `/hv:feedback` | 세션 피드백 → L2 저장 |
| `/hv:search` | BM25 지식 검색 + 히트카운트 |
| `/hv:important` | L1 핵심 교훈 승격/강등 |
| `/hv:audit` | 스펙-코드 드리프트 탐지 |
| `/hv:init` | 워크스페이스 초기화 |

전체 CLI 레퍼런스는 위의 [CLI Reference](#cli-reference) 섹션을 참조하세요.

## License

MIT
