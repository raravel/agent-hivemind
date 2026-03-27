# agent-hivemind

AI 코딩 에이전트를 위한 하네스 엔지니어링 툴킷.

에이전트가 코드를 짜기 전에 생각하게 만듭니다 — 구조화된 스펙, 태스크 파이프라인, 자기개선 피드백 루프.

> **[English](README.md)** documentation is also available.

![agent-hivemind overview](docs/images/overview.webp)

## 이게 뭔가요?

AI 코딩 에이전트에게 "투두리스트 만들어줘"라고 하면, 에이전트는 바로 코드를 작성합니다. 하지만 결과물은 대개 불완전합니다 — 아키텍처 설계 없이, 라이브러리 조사 없이, 완료 조건 없이 작업하기 때문입니다.

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

## 설치

```bash
pip install git+https://github.com/raravel/agent-hivemind.git
```

터미널에서 한 번만 실행:

```bash
hv init
```

이것으로:
- `~/agent-hivemind-data/` — 스펙, 태스크, 피드백용 데이터 디렉토리 생성
- Claude Code 플러그인 — `/hv:*` 스킬 자동 설치
- 모델 프로파일 — quality / balanced / budget 프리셋 설정

끝입니다. `hv init`이 직접 실행해야 하는 유일한 CLI 명령어입니다.

## 사용법

모든 작업은 **Claude Code** 안에서 `/hv:*` 스킬로 진행합니다. init 이후 CLI 명령어는 필요 없습니다.

### Step 1. 프로젝트 초기화 — `/hv:init`

Claude Code에서 프로젝트를 열고 실행:

```
/hv:init
```

현재 프로젝트를 hivemind에 연결하고, 프로젝트 데이터 디렉토리를 생성하며, CLAUDE.md에 프로젝트 정보를 추가합니다:

```markdown
# Hivemind Project
- project: my-app
- data_path: ~/agent-hivemind-data
```

이것이 전부입니다 — 규칙과 동작은 `/hv:*` 스킬이 알아서 처리합니다.

### Step 2. 계획 수립 — `/hv:plan`

```
/hv:plan React Router 7과 SQLite로 투두리스트 앱 만들어줘
```

에이전트가:
1. **조사** — 라이브러리 문서, API 스펙, 베스트 프랙티스를 웹 검색으로 조사
2. **하네스 문서 작성** — 아키텍처 (Mermaid 다이어그램), 기술 스택 (버전과 사용 패턴), 기능 스펙 (API 엔드포인트, 데이터 모델, 엣지 케이스), 빌드 명령, 프로젝트 규칙
3. **태스크 분해** — 각 태스크에 설명, 스펙 문서 참조, 구체적 완료 조건 체크리스트 포함

모든 스펙은 `~/agent-hivemind-data/projects/{name}/`에, 태스크는 `~/agent-hivemind-data/tasks/{name}/`에 저장됩니다.

### Step 3. 태스크 실행 — `/hv:task`

```
/hv:task
```

에이전트가:
1. 다음 태스크 선택 (의존성과 우선순위 고려)
2. 태스크가 참조하는 **하네스 문서 읽기**
3. 스펙 기반 코드 구현
4. 테스트 및 린트 실행
5. 코드 리뷰
6. 완료 처리 + 실행 리포트 생성

`/hv:task`를 반복하면 다음 태스크가 실행됩니다.

### Step 4. 피드백 저장 — `/hv:feedback`

세션이 끝날 때 (또는 주목할 만한 일이 있을 때):

```
/hv:feedback
```

에이전트가 세션 대화를 검토하고 교훈을 추출하여 L2 문서로 저장합니다. BM25 유사도로 중복 제거 — 비슷한 교훈이 이미 있으면 새로 만들지 않고 히트 카운터를 증가시킵니다.

### Step 5. 과거 지식 검색 — `/hv:search`

새 세션에서 작업 시작 전에:

```
/hv:search 인증 베스트 프랙티스
```

에이전트가:
1. 쿼리를 영어 키워드 조합으로 변환 (L2 문서는 영어 전용)
2. 여러 BM25 검색 실행
3. 고관련도 문서 (>= 70%) 자동으로 읽고 내용 제시
4. 중관련도 문서 (30-69%) 읽을지 확인
5. 저관련도 (< 30%) 건너뜀

실제로 읽은 문서만 히트 카운터가 증가합니다. 10회 이상 읽힌 문서는 L1 승격 제안 — `level1/important.md`에 핵심 교훈으로 등록됩니다.

### 보너스: 요구사항 검증 — `/hv:clarify`

구현 요청 ("X 만들어줘", "Y 추가해줘", "Z 리팩토링해줘") 시 `/hv:clarify`가 자동으로 7개 축으로 모호성을 평가합니다:

| 축 | 핵심 질문 |
|----|----------|
| Purpose (Why) | 왜 만드는가? |
| Scope | 어디서 시작하고 끝나는가? |
| Technical Context (How) | 어떤 기술 스택? |
| Integration (Fit) | 기존 시스템과 충돌은? |
| User/IO (Who/What) | 누가 쓰고, 입출력은? |
| Done Criteria | 완료 must_haves는? |
| Constraints | 반드시 지킬/피할 것은? |

모든 축이 0.2 이하가 될 때까지 소크라테스식 질문을 반복한 후, 확정된 스펙을 출력합니다. `/hv:plan` 전에 자동 실행되며, 아무 요청에나 직접 `/hv:clarify`를 호출해서 모호도를 측정할 수도 있습니다.

## 작동 원리

### 하네스 문서

에이전트가 구현 시 참조하는 프로젝트 스펙:

```
projects/my-app/
├── architecture.md      ← 시스템 구조, 모듈 경계 (Mermaid 다이어그램)
├── tech-stack.md        ← 기술 스택, 라이브러리 버전, 사용법
├── build-verify.md      ← 빌드/테스트 명령, CI 파이프라인
├── rules.md             ← NEVER/ALWAYS 규칙, 제약
└── features/
    ├── 00_auth.md       ← 인증 기능 상세 스펙
    ├── 01_todo-crud.md  ← 투두 CRUD API 명세
    └── 02_dashboard.md  ← 대시보드 UI 스펙
```

`/hv:plan`이 태스크 생성 **전에** 이 문서들을 작성합니다. `/hv:task`가 태스크를 실행할 때 이 문서를 먼저 읽습니다.

### 피드백 단계

```
L3 (세션 로그)  →  L2 (구조화된 교훈)  →  L1 (핵심 교훈)
   자동 저장           BM25 중복 제거          승격된 인사이트
   매 턴마다           카테고리 분류            important.md
```

- **L3**: 모든 사용자/AI 메시지가 훅으로 자동 저장 (별도 조작 불필요)
- **L2**: `/hv:feedback`이 교훈을 추출하고 유사도 중복 제거 후 저장
- **L1**: 10회 이상 읽힌 교훈이 `level1/important.md`로 승격

## 전체 스킬 목록

| 스킬 | 설명 | 트리거 |
|------|------|--------|
| `/hv:init` | 프로젝트 연결 + 워크스페이스 설정 | 수동 |
| `/hv:clarify` | 7축 모호성 검증 | 구현 요청 시 자동 |
| `/hv:plan` | 스펙 작성 + 태스크 분해 | 수동 |
| `/hv:task` | 태스크 실행 파이프라인 (코딩 → 테스트 → 리뷰) | 수동 |
| `/hv:feedback` | 세션 교훈 추출 → L2 저장 | 수동 |
| `/hv:search` | 과거 교훈 검색 + 자동 읽기 | 수동 |
| `/hv:important` | L1 교훈 승격/강등 | 수동 |
| `/hv:audit` | 스펙-코드 드리프트 탐지 | 수동 |

## 모델 프로파일

태스크 실행 파이프라인에서 역할별 모델 설정:

| 프로파일 | Planner | Executor | Reviewer |
|----------|---------|----------|----------|
| `quality` | opus | opus | opus |
| `balanced` | opus | sonnet | sonnet |
| `budget` | sonnet | sonnet | haiku |

기본값은 `balanced`. `hv config --profile quality`로 변경.

## 영감

- [OpenAI: Harness Engineering](https://openai.com/index/harness-engineering/)
- [Anthropic: Effective Harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Addy Osmani: Self-Improving Agents](https://addyosmani.com/blog/self-improving-agents/)

## License

MIT
