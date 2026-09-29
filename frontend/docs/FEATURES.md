# medi-front — 페이지·기능 인벤토리

> 사용자가 말로 수정 요청할 때 영역 식별 빨리 하려고 정리한 문서. 코드 구조와 1:1 매핑 안 함.
>
> ⚠️ **deep(보고서) 관련 옛 표현 주의** — `deep_progress`·`deep_dispatched_at`·
> `DeepProgressPanel`·`agent_deep`/`agent_report`·`deep_stream.jsonl` 은 전부 은퇴한
> 모델이다(assistant 디스패치는 2026-07-14 ADR-0001, 채팅 결합은 2026-07-25 분리).
> **현행**: 보고서는 `POST /reports` + `idempotency_key(^rpt_…)` 로 트리거되고 **채팅과
> 완전히 분리·병렬**로 돌며, 대화록에 아무것도 append 하지 않는다(사이드바·우측 패널·
> 이메일 첨부로만 전달). 구조는 [`ARCHITECTURE.md`](./ARCHITECTURE.md) §7, 계약은
> medi-back `docs/contracts/frontend_chat_v2.md` §4, 최신 변경은 [`PATCHNOTE.md`](./PATCHNOTE.md).

---

## 1. 라우팅

| URL | 화면 | 비고 |
|---|---|---|
| `/` | redirect | middleware가 `?threadId` 없으면 `/new`로 이동 |
| `/new` | 빈 채팅 (EmptyHero) | thread 생성 X — 첫 메시지 송신 시 lazy 생성 |
| `/?threadId=xxx` | 활성 thread 채팅 | (chat) layout이 PageShell 유지 |
| `/landing/basic` `/landing/medra` `/landing/regia` | 테마별 랜딩 | URL이 theme 고정 |
| `/login` `/signup` `/auth/verify` `/auth/set-password` `/auth/email-preview` | auth 동선 | NextAuth + EmailProvider + Credentials |
| `/admin/users` `/admin/feedback` | admin 전용 | is_admin 가드 |

**(chat) route group**:
```
app/(chat)/layout.tsx   ← PageShell 호스팅
app/(chat)/page.tsx     ← / 마커
app/(chat)/new/page.tsx ← /new 마커
```
두 라우트 간 전환 시 PageShell 유지 (Suspense 분리로 children suspend가 PageShell unmount 안 시킴).

---

## 2. 좌측 사이드바 (ThreadList)

### 상단
- **로고 (ThemeLogo)** + Beta 라벨 — 클릭 시 `/new`
- **사이드바 접기 토글** (`onCollapse`)
- **+ 새 대화** 버튼 — `router.push('/new')`, thread 생성 X

### 중단 — 심층 보고서 칸 (h-[200px] 고정)
- 보고서 done ≥1건 → 카드 리스트 (final kind만 노출)
- 카드 클릭 → ReportPreviewDialog 모달
- 0건 → "아직 생성된 보고서가 없어요"

### 중단 — 대화 목록
- "대화" 서브타이틀
- 시간별 그룹: 오늘 / 어제 / 지난 7일 / 지난 30일 / 이전
- 활성 thread 좌측 2px primary 보더
- hover 시 inline rename / delete 버튼
- 인터럽트 있으면 우측 빨강 점

### 하단 footer
- 사용자 아바타 + 이메일 + UsageBadge (일/월 사용량)
- admin 전용 — 🛡️ (사용자 관리) / 📋 (피드백 조회) 아이콘
- ⚙️ 설정 버튼 (SettingsDialog)
- 로그아웃 / 로그인

---

## 3. 채팅 영역 (ChatColumn)

### 3.1 ThreadTitleHeader (sticky 상단, turns ≥ 1일 때만)
- 좌: 사이드바 닫혀있으면 ≡ 펼침 토글
- 중: 현재 thread 제목 + ✏️ inline edit (Enter commit / Esc 취소)
- 우: **📋 보고서** 버튼 (보고서 done ≥1건일 때) + 우측 패널 토글 아이콘

### 3.2 EmptyHero (turns === 0일 때)
- 인삿말 (theme-grad-text)
- 4개 sample 카드 — 클릭 시 ChatInput prefill
- 안내문 (의료규제 전문 AI 에이전트)

### 3.3 Turn (한 turn 단위)
1. **UserMessage** — 사용자 입력 말풍선
2. **답변 대기 indicator** — running + 첫 chunk 전: 회전 스피너 + shimmer "답변을 기다리는 중입니다..."
3. **StepCarousel** — running step 자동 펼침, done step 자동 접힘
   - 헤더: 상태 아이콘 + label + (running 시) 라이브 progress_message + 소요시간 + nav 버튼
   - 본문 펼침: 도구 / 쿼리 / 진행 / 결과 / 발견한 출처 (citation 클릭 → 우측 패널)
4. **처리 과정 토글** (`<details>` 접힘 기본) — 직전 AI preamble 보존
5. **TurnAnswer** (turn.status === "done"일 때만 노출):
   - ConfidenceBadge ("신뢰도 높음 · 3/3")
   - MarkdownContent — citation chip [n] 클릭형, GFM 표/번호목록 렌더
   - CitationFootnotes — references 한-칸 carousel (선택)
   - ArtifactCard — 생성 파일 카드
   - FeedbackButtons — 👍/👎 + 코멘트 popover
6. **NextStepsCard** — 답변 본문의 `<next_steps>` 마커 파싱 → title + prompt 카드, 클릭 시 ChatInput prefill

### 3.4 ChatInput (sticky 하단)
- textarea 자동 grow 1~12줄
- Enter 전송 / Shift+Enter 줄바꿈 / Esc(running) 정지
- 좌측 toolbar:
  - 첨부 (disabled, 자리만)
  - **`@피드백` 토글 버튼** — 클릭 시 `@feedback ` prefix 박힘, 활성 시 primary-fixed 배경
- 우측: 전송 버튼 (running 시 stop 버튼)
- placeholder: "Medra에 메시지 보내기"

---

## 4. 우측 패널 (RightPanel)

### 모드 우선순위
1. **citation_split / reports_split** — citation/docPath URL + (deep 진행 또는 reports 강제) 동시 → 위/아래 분할
2. **deep_progress** — `state.deep_dispatched_at` set + `current_stage !== "done"` → DeepProgressPanel
3. **citation** — `?citation=<id>` → CitationInspector
4. **artifact** — `?docPath=<path>` → ArtifactViewer
5. **reports (강제)** — `panelOverride === "reports"` → ReportCardGroup
6. **none** — null (패널 unmount)

### 자동 노출
- citation/artifact 클릭 → panel open
- deep dispatch 시작 → panel 강제 open (DeepProgressPanel)
- deep 완료 → 패널 자동 닫힘 (현재 동작 — 변경 검토 중)

### 수동 토글
- ThreadTitleHeader의 우측 패널 토글 아이콘
- ThreadTitleHeader의 **📋 보고서** 버튼 (보고서 done 1건 이상 시 노출)
- citation chip 다시 클릭 → 같은 chip이면 토글 닫기

### 컴포넌트별 디자인
- **CitationInspector**: 제목 / 발행·일자·조항·페이지·문서ID 메타 / 본문 발췌 (whitespace-pre-wrap, 한글 word-break) / 원문 새 탭 링크 (본문 안)
- **ArtifactViewer**: 생성 파일 .md 미리보기 + 다운로드
- **DeepProgressPanel**: 헤더(스피너+shimmer "심층 보고서 생성 중"+(N/3)+진행 percent bar) / 3 stage 카드 (웹/법령/writer) / 검색 결과 + phase_message 라이브 / 슬라이드 진행바
- **ReportCardGroup**: final 보고서 카드 / 클릭 → ReportPreviewDialog / 다운로드 + 피드백

---

## 5. 입력 인터셉트

### `@feedback ...` / `@피드백 ...`
- 채팅 send 안 함
- POST `/feedback/general` (mock 모드면 fixture)
- 빈 코멘트 / 2000자 초과 → 에러 토스트
- 성공 → "피드백이 전송되었습니다. 감사합니다!" 토스트
- 토스트 위치: chat input 바로 위 + 좌우 input 중앙 정렬 (ResizeObserver)
- 토스트 디자인: theme `--md-surface` 배경 + `--md-primary` 보더, 좌측 색 스트립 X, 아이콘 X

---

## 6. 모달

| 모달 | 트리거 | 내용 |
|---|---|---|
| **SettingsDialog** | 사이드바 ⚙️ 클릭 | deployment_url / assistant_id / langsmith_key / user_jwt 입력 |
| **ReportPreviewDialog** | 보고서 카드 클릭 | .md 본문 마크다운 렌더 + 다운로드 버튼 |
| **DeleteConfirmDialog** | 사이드바 thread delete 클릭 | rounded-full 버튼, error 아이콘 중앙 |

---

## 7. 테마 (3종)

**우상단 ThemeToggle** — landing path에선 자동 숨김:
- **basic**: 흰 배경 + 그린 #00965E + Pretendard
- **medra**: 아이보리 #F4F2ED + 포레스트 #1D4D3A + Sora 폰트
- **regia**: 흰 배경 + 인디고/블루/시안 그라데이션
- 순환 토글 + localStorage `medi-front-theme` 영속 + body[data-theme] 박힘

**ThemeLogo** — `/logo.png` (basic) / `/logo-medra.png` / `/logo-regia.png` 자동 swap. 파일 없으면 hue-rotate filter fallback.

토큰 var() cascading — 토스트·CTA·카드·로고·토글 모두 자동 매칭.

---

## 8. 인증·미들웨어

- NextAuth v4 + EmailProvider (매직링크) + CredentialsProvider + PrismaAdapter
- middleware 흐름: 미인증 → `/login`, hasPassword=false → `/auth/set-password`
- `/` (no threadId) → `/new` redirect
- `NEXT_PUBLIC_AUTH_BYPASS=true` 또는 `NEXT_PUBLIC_DUMMY_MODE=true` → 인증 우회 (production 강제 OFF)
- JWT: jose HS256, backend가 NEXTAUTH_SECRET으로 verify

---

## 9. Admin 페이지

### `/admin/users`
- mock 또는 실 backend의 사용자 리스트 (페이지네이션)
- 각 사용자: 이메일·권한·일/월 한도·사용량
- 상세 → UserUsageDialog (period card + 입력/출력/비용 breakdown)
- 편집 → EditUserDialog (한도 override + admin 부여)

### `/admin/feedback`
- kind 토글: 자유 피드백 (`user_feedback`) / 평가 (`feedback`)
- 카드 리스트: 시간 / user_id / 코멘트 본문 / thread·msg id / rating(평가 모드)
- 페이지네이션 (50건씩)

---

## 10. State 관리

### useChatState (per thread)
- ChatState — `messages` / `files` / `steps` / `turns` / `reports` / `deep_progress` / `deep_dispatched_at` / `error`
- runs.stream 소비 (`values` / `messages-tuple` / `custom` 채널)
- 5 reducer — `applyValues` / `applyMessageChunk` / `applyToolProgress` / `applyDeepStep` / `applyDeepToolProgress`
- pollReports — Reports API 폴링 (3s 간격), final done / error / 5분 timeout 시 정지
- `dispatchedDeepStepIds` ref — 무한 deep 발화 차단

### RightPanelProvider (Context, 메모리만)
- `open`: boolean (패널 열림/닫힘)
- `panelOverride`: `"reports"` | `null` (강제 모드)

---

## 11. Mock 모드

`npm run dev:mock` (= `NEXT_PUBLIC_DUMMY_MODE=true` + `NEXT_PUBLIC_AUTH_BYPASS=true`):
- LangGraph SDK → `dummy.ts` fake client (메모리 thread store + jsonl 시나리오)
- runs.stream → `public/mocks/fast_stream.jsonl` / `deep_stream.jsonl` (150ms 간격 yield)
- REST 호출 → `mockFetch` 인터셉트 → `public/mocks/*.json` fixture
- 매 stream session마다 unique 접미사 — id 충돌 방지

### Fixture 파일
| 파일 | 매핑 |
|---|---|
| `fast_stream.jsonl` | runs.stream (assistantId가 일반) |
| `deep_stream.jsonl` | runs.stream (assistantId가 agent_deep 또는 deep trigger msg id) |
| `me_usage.json` | GET `/me/usage` |
| `reports_list.json` | GET `/threads/{tid}/reports` |
| `report_detail.json` | GET `/reports/{rid}`, GET `/reports/{rid}/download` |
| `feedback_general_response.json` | POST `/feedback/general`, 메시지·보고서 feedback |
| `admin_feedback.json` | GET `/admin/feedback` |
| `admin_users.json` | GET `/admin/users` |
| `suggestions.json` | GET `/suggestions` |
| `auto_title_response.json` | POST `/threads/{tid}/auto-title` |

---

## 12. 알려진 한계 / TODO

- mock 모드에서 답변 본문은 fixture 정적 — 어떤 질문에도 같은 답변
- Deep stream의 LLM 토큰 라이브 표시(messages-tuple) 미구현 (v1)
- 페이지 재진입 시 deep stream 재구독 X (폴링이 결과 fallback)
- `tool_progress phase=="result"`의 `index/title/subtitle/url` 필드는 backend가 emit해야 search_results 카드에 채워짐
