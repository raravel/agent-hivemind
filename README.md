# agent-hivemind

AI 코딩 에이전트를 위한 하네스 엔지니어링 툴킷.

프로젝트 초기화부터 태스크 실행, 피드백 수집까지 — AI 에이전트가 코드를 작성할 때 필요한 모든 컨텍스트를 구조화하고 관리합니다.

## 이게 뭔가요?

AI 코딩 에이전트(Claude Code 등)에게 "투두리스트 만들어줘"라고 하면, 에이전트는 바로 코드를 작성하기 시작합니다. 하지만 결과물은 대개 불완전합니다 — 아키텍처 설계 없이, 라이브러리 조사 없이, 완료 조건 없이 작업하기 때문입니다.

**agent-hivemind**은 이 문제를 해결합니다:

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

에이전트가 코드를 짜기 전에 **생각하게** 만드는 시스템입니다.

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

### 1. 초기화

```bash
hv init
```

이 명령어 하나로:
- `~/agent-hivemind-data/` 데이터 디렉토리 생성
- Claude Code 플러그인 설치 (`/hv:*` 스킬 8개)
- 모델 프로파일 설정 (quality/balanced/budget)

### 2. 프로젝트 연결

```bash
cd my-project
hv link
```

- 프로젝트를 hivemind 데이터 레포에 등록
- CLAUDE.md에 `/hv:clarify` 필수 규칙 주입
- 이후 구현 요청 시 자동으로 요구사항 검증 시작

### 3. 사용

Claude Code에서 자연어로 작업을 요청하면 됩니다:

```
"투두리스트 앱 만들어줘"
```

1. `/hv:clarify`가 자동 호출 — 7축 모호성 검증
2. `/hv:plan`으로 스펙 작성 + 태스크 분해
3. `/hv:task`로 태스크 순차 실행

또는 직접 스킬을 호출할 수도 있습니다:

```
/hv:plan 이 프로젝트를 계획해줘
/hv:task 다음 태스크 실행해줘
/hv:search "인증 관련 교훈"
```

## 데이터 구조

```
~/agent-hivemind-data/
├── projects/                    ← 프로젝트별 하네스 문서 (스펙)
│   └── {project}/
│       ├── architecture.md
│       ├── tech-stack.md
│       ├── build-verify.md
│       ├── rules.md
│       └── features/*.md
├── tasks/                       ← 이슈 트래커 (Linear 대체)
│   └── {project}/
│       ├── PRJ-001.md           ← 태스크 (frontmatter + body)
│       ├── PRJ-002.md
│       └── _reports/            ← 실행 리포트
├── level1/important.md          ← L1: 핵심 교훈 (자동 생성)
├── level2/                      ← L2: 구조화된 교훈
│   ├── frontend/
│   ├── backend/
│   ├── infra/
│   └── general/
├── level3/                      ← L3: 세션 로그
├── index.json                   ← BM25 검색 인덱스
└── .hivemind.json               ← 전역 설정
```

## Claude Code 플러그인 (`/hv:*`)

`hv init` 실행 시 Claude Code 플러그인으로 자동 설치됩니다.

| 스킬 | 설명 | 자동 호출 |
|------|------|-----------|
| `/hv:clarify` | 7축 모호성 검증 — 구현 요청 시 필수 | 구현 요청 시 자동 |
| `/hv:plan` | 하네스 문서 작성 + 태스크 분해 | — |
| `/hv:task` | 태스크 실행 파이프라인 (코딩→테스트→리뷰) | — |
| `/hv:feedback` | 세션 피드백 추출 → L2 저장 | — |
| `/hv:search` | BM25 지식 검색 + 히트카운트 | — |
| `/hv:important` | L1 승격/강등/재생성 | — |
| `/hv:audit` | 스펙-코드 드리프트 탐지 | — |
| `/hv:init` | 워크스페이스 초기화 오케스트레이션 | — |

### `/hv:clarify` — 요구사항 검증

구현 요청을 받으면 7개 축으로 모호성을 평가합니다:

| 축 | 핵심 질문 |
|----|----------|
| Purpose (Why) | 왜 만드는가? |
| Scope | 어디서 시작하고 끝나는가? |
| Technical Context (How) | 어떤 기술 스택? |
| Integration (Fit) | 기존 시스템과 충돌은? |
| User/IO (Who/What) | 누가 쓰고, 입출력은? |
| Done Criteria | 완료 must_haves는? |
| Constraints | 반드시 지킬/피할 것은? |

모든 축이 0.2 이하가 될 때까지 소크라테스식 질문을 반복합니다.

### `/hv:plan` — 계획 수립

1. **Phase 1**: 하네스 문서 작성 (라이브러리 조사 → 아키텍처 → 기능 스펙)
2. **Phase 2**: 태스크 분해 (완료 조건 + 스펙 참조 + 의존성)

### `/hv:task` — 태스크 실행

1. 다음 태스크 가져오기 (`hv run`)
2. 하네스 문서 읽기 (필수)
3. 코딩 에이전트 실행
4. 테스트 에이전트 실행
5. 코드 리뷰 에이전트 실행
6. 완료 처리 + 리포트 생성

## CLI 레퍼런스

### 프로젝트 관리

```bash
hv init [--path PATH] [--git]     # 워크스페이스 초기화
hv link [--name NAME]             # 현재 프로젝트 연결
hv push                           # 데이터 레포 원격 푸시
```

### 태스크 관리

```bash
hv task create -p <project> -t "<title>" [--type feat] [--priority high] [--depends ID]
hv task list [-p <project>] [-s pending] [--priority high]
hv task get <ID> [--format json]
hv task update <ID> [--status in_progress] [--priority high]
hv task next [-p <project>]
hv run [-p <project>] [-t <ID>] [--format json]
```

### 피드백 & 지식

```bash
hv feedback save -p <project> [--content FILE]    # L2 교훈 저장
hv search "<query>" [-p <project>]                # BM25 검색
hv important promote <path>                       # L1 승격
hv important demote "<query>"                     # L1 강등
hv important generate                             # important.md 재생성
```

### 감사 & 통계

```bash
hv audit -p <project> [--fix]                     # 스펙-코드 드리프트 탐지
hv stats -p <project> [--since DATE]              # 실행 메트릭 집계
```

### 설정

```bash
hv config                                         # 전체 설정 출력
hv config <key>                                   # 값 조회
hv config <key> <value>                           # 값 설정
hv config --profile balanced                      # 모델 프로파일 변경
```

## 모델 프로파일

에이전트 파이프라인에서 각 역할에 어떤 모델을 사용할지 설정합니다:

| 프로파일 | Planner | Executor | Reviewer |
|----------|---------|----------|----------|
| `quality` | opus | opus | opus |
| `balanced` | opus | sonnet | sonnet |
| `budget` | sonnet | sonnet | haiku |

```bash
hv config --profile balanced    # 기본값
```

## 영감

- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/)
- [Anthropic: Effective Harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Addy Osmani: Self-Improving Agents](https://addyosmani.com/blog/self-improving-agents/)

## License

MIT
