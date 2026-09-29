# 03 · COMPONENTS — 1차 컴포넌트 사양

전제: `00_PRINCIPLES.md` (멘탈 모델 §2, 책임 경계 §3), `01_COLOR.md`, `02_LAYOUT.md`.

본 문서는 **1차 범위 컴포넌트의 구조·동작·데이터 모양**을 박는다.
React 코드 X. 데이터 props·상태 전이·시각 구조만.

> 데이터 모양은 백엔드가 보낼 페이로드 추정(예시) — 정확한 키/값은 `../medi-back/02_INTERFACE.md` 확정 시 동기화.

---

## 1. 컴포넌트 트리

```
PageShell
├── Header
├── ResizableGroup (horizontal, autoSaveId="root")
│   ├── ThreadList                          [optional]
│   ├── ChatColumn
│   │   ├── ChatScroll
│   │   │   ├── EmptyHero                   [messages=0]
│   │   │   ├── ThreadLoadingBanner         [loading existing]
│   │   │   └── Turn × N
│   │   │       ├── UserMessage
│   │   │       ├── StepCard × N            [인라인, 시간순 stack, 접힘/펼침]
│   │   │       └── TurnAnswer              [done]
│   │   │           ├── MarkdownContent     [citation chip 포함]
│   │   │           ├── CitationFootnotes   [References 박스]
│   │   │           └── ArtifactCard × N    [생성 파일 인라인]
│   │   └── ChatInput
│   └── RightPanel                          [조건부, 두 모드 슬롯 공유]
│       ├── CitationInspector               [?citation=… 일 때]
│       └── ArtifactViewer                  [?docPath=… 일 때]
└── Toaster (sonner)
```

폐기:
- SubAgentIndicator, SubAgentLiveStream, ThinkingBlock, ToolCallBox(채팅 사용분), ActivityChip, ActivityDetail
- **TurnStatus** (StepCard 인라인 stack으로 대체)
- **ActiveAgentCard, EventTimeline, DocsList** (우측 패널에서 제거 — 진행 timeline은 채팅 안 단계 카드 stack에서 봄)

---

## 2. Turn (채팅 본문 핵심 단위)

### 2.1 책임

한 턴 = (사용자 메시지) + (작업 상태) + (답변).
**내부 구조 노출 X**. `Turn`이 supervisor / sub-agent / tool 차이를 흡수한다.

### 2.2 입력 데이터 — `../medi-back/02_INTERFACE.md` v0.4 정합

권위 원천: back `§2`. 본 절은 *프론트가 derive·소비할* 모양만 박는다. 필드 네이밍은 **snake_case** (back `§10`).

```ts
// Turn은 front-derived (back §8) — state.steps + state.messages + state.files에서 만든다
type Turn = {
  id: string;                        // = human message id
  user_message: { id: string; content: string };
  status: 'running' | 'done' | 'error' | 'interrupted';
  started_at: number;                // ms epoch
  ended_at?: number;
  steps: Step[];                     // back state.steps 중 이 turn 범위
  interrupt?: InterruptValue;        // back §2.5
  answer?: {
    content: string;                 // 마지막 AI message content. 인용은 평문 [n] (back §7)
    citations: Citation[];           // [n] + step.citations 합집합 (id dedupe)
    artifacts: Artifact[];           // 이 turn에서 변경된 state.files[path] view
  };
};

// Step 상세는 §4.2 참조

type Citation = {                    // back §2.2 그대로
  id: string;                        // 클릭 시 RightPanel ?citation=<id>
  number: number;                    // 답변 본문 [n]
  source_kind: 'web' | 'doc';
  title: string;
  publisher?: string;
  date?: string;
  url?: string;                      // source_kind === 'web' 필수
  doc_id?: string;                   // source_kind === 'doc'
  article?: string;                  // "제45조"
  page?: number;
  snippet?: string;
  status?: 'active' | 'revoked' | 'amended_pending';   // 미지정 = active
};

type Artifact = {                    // front-derived from state.files[path] (back §2.4)
  path: string;                      // RightPanel ?docPath=<path>
  bytes: number;                     // = TextEncoder().encode(content.join('\n')).length
  modified_at: number;               // ms — from FileEntry
  is_streaming: boolean;              // from FileEntry
  title?: string;                    // markdown 첫 # 또는 path basename
  mime_type?: string;                // 확장자에서 추론
};
```

### 2.3 시각 구조

```
┌─ UserMessage (오른쪽 정렬, max 70%)
│
├─ StepCard #1   ── 접힘 한 줄 또는 펼침 본문 (§4)
├─ StepCard #2
├─ StepCard #3   ── 가장 최신 / 진행 중인 카드는 자동 펼침
│      ⋮
│
└─ TurnAnswer (turn.status === 'done')
    ├─ MarkdownContent (citation chip [1] 인라인)
    ├─ CitationFootnotes (References 박스)
    └─ ArtifactCard × N
```

진행 중에는 마지막 StepCard가 펼쳐져 있고, 답변 부분은 비어있다.
턴이 완료되면 모든 StepCard가 자동 접히고, TurnAnswer가 그 아래 등장한다.

---

## 3. UserMessage

| 항목 | 값 |
|---|---|
| 정렬 | 오른쪽 |
| 폭 | `max-w-[70%]` |
| 배경 | `--md-surface-container-low` |
| 보더 | 1px `--md-outline-variant` |
| radius | 12px (rounded-xl), `rounded-br-none` (꼬리 효과) |
| padding | `px-3 py-2` |
| typography | `text-body-base` (14px) |
| 색 | `--md-on-surface` |

빈 메시지 / 멀티라인 / 코드 — markdown 미적용 (사용자 입력 그대로 `whitespace-pre-wrap`).

---

## 4. StepCard (채팅 안 인라인, 단계별 1개씩)

### 4.1 책임

각 단계(검색·정리·작성 등)를 **하나의 카드**로 표시. 한 턴 동안 여러 카드가 시간순으로 stack.
Claude.ai 식 tool-call 확장과 동일한 멘탈 모델: 헤더 한 줄 + 클릭 시 그 자리에서 펼쳐 디테일.

### 4.2 입력 데이터 — `../medi-back/02_INTERFACE.md §2.1` 그대로

```ts
type Step = {
  id: string;                  // 백엔드 발행. unique
  ts: number;                  // 시작 시각 — ms epoch
  label: string;               // "웹 검색: 의료기기 광고" — 백엔드가 사람 향 가공
  status: 'running' | 'done' | 'error';
  ended_at?: number;           // status !== 'running' 시
  tool_name?: string;          // "tavily_search" — 펼침 디테일에서만
  input_preview?: string;      // 검색 쿼리 / 파일 경로 / 핵심 args
  output_preview?: string;     // "결과 5건" 같은 짧은 요약
  citations?: Citation[];      // 이 단계가 만든 출처
  error_message?: string;      // status === 'error' 시 사람 향 한국어
};
```

`state.steps` 단일 소스(back `§11 I1`). 같은 `id`로 두 번 update 시 reducer가 merge — 프론트도 *id 기준 dedupe*. 시스템 도구(`think_tool`/`write_todos`/`read_file` 등)는 백엔드가 step append를 안 함(back `§3.5`).

### 4.3 두 상태 — 접힘 / 펼침

**접힘 (collapsed)** — 기본

```
┌─ ● 웹 검색: 의료기기 광고 · 5건 ··············· 1.2s · ▾ ─┐
└──────────────────────────────────────────────────────────┘
```

한 줄: dot · label · 짧은 output_preview · 소요 시간 · chevron.

**펼침 (expanded)** — 클릭 시 그 자리에서 펼쳐짐

```
┌─ ● 웹 검색: 의료기기 광고 · 5건 ··············· 1.2s · ▴ ─┐
│                                                            │
│  도구  tavily_search                                       │
│  쿼리  "의료기기 광고 심의 기준 2024"                       │
│                                                            │
│  발견한 출처                                                │
│   [1] 식약처 의료기기 광고 가이드라인 (2024)                │
│   [2] 의료기기법 시행규칙 제45조                            │
│   [3] ...                                                   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 4.4 자동 동작

| 트리거 | 결과 |
|---|---|
| step 시작 (`status: running`) | **자동 펼침** — 진행 중 상세를 즉시 보임 |
| step 완료 (`status: done`) | **1.5s 후 자동 접힘** — 카드 헤더만 남김 |
| step 오류 (`status: error`) | **펼침 유지** — 사용자가 디테일 봐야 함 |
| 사용자가 토글 클릭 | 자동 동작 정지 — 이후 수동만 |

### 4.5 시각

| 영역 | 스타일 |
|---|---|
| 카드 컨테이너 | 1px `--md-outline-variant`, radius 8px, bg `--md-surface-container-lowest` |
| 카드 호버(접힘) | bg `--md-surface-container-low` |
| 헤더 dot | running: `--md-warning` pulse · done: `--md-success` · error: `--md-error` |
| 헤더 텍스트 | `text-body-sm` `--md-on-surface` |
| output_preview (헤더 안 부가) | `text-body-sm` `--md-on-surface-variant` |
| 소요 시간 | mono `text-[10px]` `--md-on-surface-variant` |
| 펼침 본문 | bg `--md-surface-container-low`, padding `card-padding/2` |
| 펼침 안 라벨(`도구`·`쿼리`·`발견한 출처`) | `text-label-caps` `--md-on-surface-variant` |
| 펼침 안 인용 항목 | 클릭 시 RightPanel Citation Inspector 열림 |

### 4.6 InterruptCard

`turn.interrupt`가 set 되어 있으면 **마지막 StepCard 자리에 별도 카드**로 렌더 (StepCard와 동일 폭).

| 형태 | 동작 |
|---|---|
| `type: "clarify"` | 질문 + 라디오 선택지(있으면) + 자유 텍스트 input + [전송] |
| `type: "approve_action"` | 액션 설명 + [수락] [거절] [수정] |

배경 `--md-tertiary-fixed`, on-text `--md-on-tertiary-fixed-variant`, 보더 `--md-tertiary`.

---

## 5. TurnAnswer

### 5.1 본문

`MarkdownContent`로 `answer.content` 렌더. 다음 인라인 마크업 지원 필요:
- 일반 markdown (h1~h6, list, code, table, quote, link)
- 인용 마크 `[1]` `[2]` 등 → 클릭/호버 시 `CitationFootnotes` 항목 강조
- 코드 블록 syntax highlight + 복사 버튼
- 표 (markdown table → 스크롤 가능 wrapper)

### 5.2 CitationFootnotes

답변 본문 아래 박스로 분리.

```
┌─ References ───────────────────────────────────┐
│ [1] 식약처 의료기기 광고 가이드라인 (2024)      │
│      ↗ www.mfds.go.kr/...  · "광고 시 다음을…" │
│                                                 │
│ [2] 의료기기법 시행규칙 제45조                  │
│      📄 의료기기법.pdf · p.32                   │
└────────────────────────────────────────────────┘
```

| 영역 | 스타일 |
|---|---|
| 박스 | `--md-surface-container-low` 배경, 1px `--md-outline-variant` 보더, radius 8px |
| 헤더 "References" | `text-label-caps` uppercase `--md-on-surface-variant` |
| 항목 | `text-body-sm`. 번호 강조 `--md-primary` |
| 링크 | hover `--md-primary` underline |
| 스니펫 | `--md-on-surface-variant`, `text-[11px]` |

### 5.3 ArtifactCard (인라인)

답변 끝 또는 별도 stack으로 생성된 파일 카드.

| 항목 | 값 |
|---|---|
| 폭 | 풀폭 또는 max-w-md |
| 배경 | `--md-surface-container-lowest` |
| 보더 | 1px `--md-outline-variant`, 호버 시 `--md-primary` |
| 아이콘 | Material Symbols `article` / `description` (확장자별, `04_ELEMENTS`) |
| 제목 | 파일명 truncate, `text-body-sm font-semibold` |
| 메타 | 사이즈, 수정 시각 (`text-[10px]` `--md-on-surface-variant`) |
| 동작 | 클릭 → `?docPath=` 설정 → RightPanel **Artifact Viewer 모드**로 슬라이드인 |
| 스트리밍 중 표시 | `Generating` 배지 (`--md-primary-fixed` 배경, 펄스 dot) |

### 5.4 Citation chip (markdown 인라인)

답변 본문 안 `[1]` 자리표시는 클릭 가능한 chip으로 렌더.

| 항목 | 값 |
|---|---|
| 마크업 | inline `<button>` (텍스트 흐름 안 inline-block) |
| 모양 | `[1]` 형태, 양옆 4px padding, radius 4px |
| 배경 | `--md-primary-fixed` |
| 텍스트 | `--md-on-primary-fixed-variant`, `text-[11px] font-semibold` |
| 호버 | 배경 `--md-primary`, 텍스트 `--md-on-primary` |
| 동작 | 클릭 → `?citation=<id>` 설정 → RightPanel **Citation Inspector 모드** |

---

## 6. ChatInput

### 6.1 구조

```
┌─────────────────────────────────────────────┐
│ [textarea — 자동 grow]                      │
│                                             │
├─────────────────────────────────────────────┤
│ [📎 첨부]              [⚙ 모드]    [↑ 전송] │
└─────────────────────────────────────────────┘
```

| 영역 | 스타일 |
|---|---|
| 컨테이너 | `--md-surface` 배경, 1px `--md-outline-variant` 보더, radius 12px |
| textarea | border 0, `font-inherit`, `text-body-base`, placeholder `--md-on-surface-variant`, autosize 1~12 lines |
| 첨부 버튼 | ghost icon, Material `attach_file` |
| 모드 버튼 | (선택) ghost icon, 미정 |
| 전송 버튼 | primary 채움. running 중엔 `Stop`(destructive)으로 변경 |
| 위치 | sticky bottom, max-w 720px |

### 6.2 키 동작

| 키 | 동작 |
|---|---|
| `Enter` | 전송 |
| `Shift+Enter` | 줄바꿈 |
| `Esc` | (running 시) Stop. 그 외 무시 |

### 6.3 비활성

`isLoading=true` 또는 `assistant=null` 시 textarea 사용 가능, 전송 버튼만 disable.

---

## 7. RightPanel — 두 모드 슬롯 공유

`02_LAYOUT.md §4` 그대로 — 기본 닫힘. 트리거에 따라 한 모드만 활성.

### 7.1 CitationInspector (Mode A)

`?citation=<id>` URL set 시 활성. 폭 36% (min 360px).

| 영역 | 스타일/동작 |
|---|---|
| 헤더 | h-12. ← Back · `Citation [n]` · ✕. 보더 1px `--md-outline-variant` 하단 |
| 본문 컨테이너 | `--md-surface-container-lowest`, padding `card-padding` |
| 출처 메타 영역 | 제목(`text-h2`), publisher·date(`text-body-sm` muted), URL/locator(mono) |
| 구분선 | 1px `--md-outline-variant`, margin `gutter` 위/아래 |
| 본문 스니펫 | `MarkdownContent`, `text-body-base`, 스니펫이 길면 `max-h-[60vh] overflow-y-auto` |
| 액션 버튼 | `[원문 열기]` (Mode B로 swap, 출처가 doc일 때만) · `[↗ 외부 링크]` (web일 때만) |
| 닫기 | ✕ → `setCitation(null)` |
| 모드 swap | 본문 안 산출물 카드 클릭 시 자동 Mode B로 (URL 키 swap) |
| 입력 데이터 | Citation 객체 1개 (백엔드가 id로 조회 가능하게 spec) |

### 7.2 ArtifactViewer (Mode B)

`?docPath=<path>` URL set 시 활성. 폭 48% (min 480px, max 60vw).

| 영역 | 스타일/동작 |
|---|---|
| 헤더 | h-12. ← Back · 📄 파일명 · `Generating` 배지(스트리밍 시) · ✕ |
| 본문 컨테이너 | `--md-surface-container-lowest`, padding `card-padding` |
| 본문 | `MarkdownContent(getFileText(file))` |
| 스트리밍 caret | 본문 끝 2px 사각형, primary 색, pulse |
| 자동 스크롤 | 스트리밍 중이고 사용자가 바닥에 있으면 ↓ 따라감. 사용자가 위로 스크롤하면 멈춤 |
| 빈 파일 | "(Empty file)" `--md-on-surface-variant` |
| 닫기 | ✕ → `setDocPath(null)` |
| 다운로드 | (있으면) export URL 받아 다운로드 — `../medi-back/01_CAPABILITIES.md` S3 의존 |

---

## 8. DocViewer (슬라이드인)

> **§8 통합됨** — Artifact Viewer는 `§7.2`로 흡수. Citation Inspector는 `§7.1`. 별도 절 없음.

---

## 9. ThreadList

### 9.1 헤더

| 영역 | 값 |
|---|---|
| 로고 + 부제 | `02_LAYOUT §7` |
| 새 thread 버튼 | primary 채움, 풀폭 |

### 9.2 항목

| 영역 | 스타일 |
|---|---|
| 컨테이너 | padding `px-3 py-2`, hover `--md-surface-container-low` |
| 활성 thread | 좌측 2px primary 보더, 배경 `--md-surface-container-lowest` |
| 제목 | truncate, `text-body-base` |
| 메타 (시간) | `text-[10px]` `--md-on-surface-variant` |
| 인터럽트 배지 | 우측, 빨강 배경 카운트 |

### 9.3 푸터 (옵션)

Settings · Docs 링크 (Material 아이콘 + 텍스트, `text-body-sm`).

---

## 10. EmptyHero

| 영역 | 값 |
|---|---|
| 위치 | 채팅 영역 중앙(`min-h-[60vh]`), `flex items-center justify-center` |
| 아이콘 | `medical_services` 아이콘 (Material), `--md-primary` 배경 박스 12×12 |
| 제목 | "의료 규제 상담을 시작해보세요" `text-h1` |
| 설명 | 1줄 (`text-body-base`, `--md-on-surface-variant`) |
| 예시 칩 | 3개 max, 클릭 시 textarea에 prefill |

---

## 11c. DeepReportCTA (P8 후속 — 자동 dispatch 폐기)

deep 그래프(`agent_deep`)는 **사용자 명시 액션**으로만 dispatch. 이전엔 fast 응답 직후 자동 dispatch했으나 인사 같은 비-실질 질의에도 5분 보고서를 강제 → 폐기.

| 영역 | 값 |
|---|---|
| 위치 | ChatColumn 마지막 turn 아래 (ReportPreparingIndicator 자리) |
| 조건 | 마지막 turn `status === 'done'` AND `state.deep_dispatched_at` 미설정 AND `!isRunning` |
| 시각 | 1px outline 카드, `--md-surface-container-low` 배경, `article` 아이콘 + 제목 + 부제 + primary 버튼 |
| 동작 | 클릭 → `useChatState.triggerDeepReport()` → `dispatchDeepAndPoll` → CTA 사라짐 + ReportPreparingIndicator 등장 |

향후: backend가 `state.metadata.needs_deep` 같은 신호 줄 수 있으면 *추천 highlight*로 발전 가능 (auto-dispatch는 여전히 X).

## 11a. ReportPreparingIndicator (P8 신규)

`05_DATA §3.5` Fast/Deep 패턴 — fast 응답 직후 deep 비동기 dispatch한 시점부터 *보고서 3종(rag·web·final) 모두 status=done* 이 될 때까지 표시.

| 영역 | 값 |
|---|---|
| 위치 | TurnAnswer 본문 *바로 아래* (CitationFootnotes / ArtifactCard와 같은 stack) |
| 시각 | 1px `--md-outline-variant` 보더, `--md-surface-container-low` 배경, radius 8, padding 12 |
| 헤더 | Material `pending_actions` 아이콘(pulse) + "심층 보고서 준비 중" `text-body-sm font-medium` |
| 진행 표시 | `{ready}/3` 카운터 + 작은 progress dot 3개(완료된 만큼 `--md-success`) |
| 시간 메시지 | "보고서 작성에 평균 3~5분 소요" — `text-[11px]` `--md-on-surface-variant` |
| 완료 시 동작 | 컴포넌트 자체를 *제거*하고 ArtifactCard들(또는 ReportDownloadButton)이 그 자리 차지 |
| 에러 | deep 호출 실패 또는 폴링 3회 연속 실패 → 메시지 빨강 + [재시도] |

데이터 의존: `Report[]` (Reports API, `05 §6`).

## 11b. ReportDownloadButton (P8 신규)

`Report.status === 'done'` 항목을 사용자가 .md로 다운로드.

| 영역 | 값 |
|---|---|
| 시각 | outline 버튼, Material `download` 아이콘 + 파일명 |
| 위치 | (1) TurnAnswer 본문 아래 보고서 인디케이터 자리 (2) ArtifactViewer 행 푸터 |
| 동작 | `GET /reports/{report_id}/download` → 브라우저 다운로드 (`a[download]` 트릭 또는 `URL.createObjectURL`) |
| 인증 | `Authorization: Bearer <API_TOKEN>` 헤더 (`05 §6`) |

## 11. SettingsDialog

| 영역 | 값 |
|---|---|
| 트리거 | 헤더 ⚙ |
| 용도 | **개발자 override만** — production 배포는 환경변수(`NEXT_PUBLIC_DEPLOYMENT_URL`, `NEXT_PUBLIC_ASSISTANT_ID`)가 권위. 일반 사용자에겐 운영상 노출되지 않는 영역(자동 오픈 X) |
| 폼 필드 | Deployment URL · Assistant ID · LangSmith API Key |
| 저장 동작 | localStorage `medi-front-config` (env 값 위에 덮어씀 — dev 환경에서 백엔드 스위칭) |
| 첫 진입 시 | env 충족이면 미오픈. env 미충족 + dev 환경(`NODE_ENV !== 'production'`)에서만 자동 오픈 |
| 더미 모드 | `NEXT_PUBLIC_DUMMY_MODE=true` 시 SettingsDialog 자체 비활성(연결 대상이 없음) |

(코드 명세는 별도 — 본 문서는 컴포넌트 윤곽만.)

---

## 12. 컴포넌트 X 데이터 의존 매트릭스

| 컴포넌트 | 백엔드 페이로드 의존 | 어디 정의 |
|---|---|---|
| Turn | messages + 단계 평탄화 + classification | `02_INTERFACE` (백) |
| StepCard | step (id, label, status, tool_name, input_preview, output_preview, citations) | back `§2.1` |
| TurnAnswer | answer.content + citations[] | `02_INTERFACE` |
| Citation chip / CitationInspector | Citation 메타 (id, source_kind, url, title, publisher, date, locator, snippet) | `02_INTERFACE` |
| ArtifactCard / ArtifactViewer | state.files[path] (content, modified_at, is_streaming) | back `§2.3`,`§2.4` |
| InterruptCard | interrupt.value (`type`, fields) | `02_INTERFACE` |

→ 정확한 키/값은 백엔드 spec 작성 시 양쪽 묶음 PR.

---

## 13. 폐기 컴포넌트

`../deep-agents-ui-custom/`에 있던:
- `SubAgentIndicator`, `SubAgentLiveStream`, `ThinkingBlock`
- 채팅 안 `ToolCallBox` 사용
- **`TurnStatus`** (StepCard 인라인 stack으로 대체)
- **`ActiveAgentCard` / `EventTimeline` / `DocsList` / `DocCard`** (우측 패널 단일 컬럼 모델 폐기)
- `ActivityChip`, `ActivityDetail`
- `LiveActivityStrip`
- `classifyMessages`, `useToolActivities` (Turn 파생으로 대체)

본 medi-front 코드베이스 시작 시 처음부터 만들지 않는다.

---

## 14. 변경 절차

- 컴포넌트 추가/제거: 본 문서 §1 트리 + 해당 절 갱신.
- 데이터 모양 변경: 백엔드 `02_INTERFACE.md`와 묶어 PR.
- 시각 변경: `01_COLOR` / `02_LAYOUT` / `04_ELEMENTS` 영향 시 같이 갱신.

---

## Changelog
- 2026-04-27 v0.1 — 초안. Turn 기반 모델 정착, 14 컴포넌트 윤곽.
- 2026-04-28 v0.2 — `00_PRINCIPLES v0.2` 반영. **TurnStatus 폐기 → StepCard 인라인 stack** (Claude.ai 식 collapsible). RightPanel 두 모드(CitationInspector / ArtifactViewer) 슬롯 공유로 재구성, ActiveAgentCard·EventTimeline·DocsList 폐기. Citation chip 인라인 spec 추가. 데이터 의존 매트릭스 갱신.
- 2026-04-28 v0.2.1 — §7.2 ArtifactViewer에서 ArtifactCard 잔재 3행(제목·스트리밍 배지·클릭) 제거(중복). 다운로드 경로 표기 정정.
- 2026-04-28 v0.3 — `../medi-back/02_INTERFACE.md` v0.4 + `05_DATA.md` v0.3과 정합. §2.2·§4.2의 Turn/Step/Citation/Artifact 타입을 **snake_case로 통일** (`endedAt`/`toolName`/`inputPreview`/`outputPreview`/`errorMessage`/`modifiedAt`/`isStreaming` → `ended_at`/`tool_name`/`input_preview`/`output_preview`/`error_message`/`modified_at`/`is_streaming`). `Citation.locator` → `doc_id`/`article`/`page` 분리. Artifact는 front-derived from `state.files[path]`로 재정의(`bytes` derive 명시).
- 2026-04-29 v0.3.1 — §11 SettingsDialog 용도 재정의: **production은 env vars(`NEXT_PUBLIC_DEPLOYMENT_URL/ASSISTANT_ID`) 권위, SettingsDialog는 dev override만**. 자동 오픈은 dev 환경 + env 미충족 시에만. `NEXT_PUBLIC_DUMMY_MODE=true` 시 비활성.
- 2026-04-29 **v0.4** — Fast/Deep 2단계 dispatch + Reports API 흡수. §11a `ReportPreparingIndicator`(보고서 준비 중) + §11b `ReportDownloadButton`(.md 다운로드) 신규 박음. `05_DATA §3.5`/`§6`과 정합.
- 2026-04-29 v0.4.1 — §4 StepCard 모델 변경: stack(여러 카드 누적) → **StepCarousel(단일 카드 + `< / >` nav)**. autoFollow=true 기본 + 사용자 nav 시 sticky off + 카운터 클릭으로 재활성. 채팅창 공간 절약 + 단계 탐색 명시. (StepCard.tsx 삭제, 모든 step 본문은 StepCarousel 안에서 렌더). §11b 다운로드 버튼 *fallback* — Reports API 매칭 없으면 `state.files[path].content`를 메모리 Blob으로 다운로드(`local` 배지).
