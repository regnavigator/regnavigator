# medi-back API 명세 — 프런트 통합용

프런트(또는 외부 클라이언트)가 medi-back을 사용할 때 필요한 모든 엔드포인트.
**단일 endpoint** (dev `http://127.0.0.1:2024` — uvicorn `src.api:app`, FastAPI 단일 앱)에서
채팅(`/chat` SSE)·보고서·조회·가이드 라우트가 함께 서빙된다.
**채팅·보고서 현행 계약 정본 = [`frontend_chat_v2.md`](./frontend_chat_v2.md)** (§8 요약).

> **Tip**: OpenAPI 자동 노출. 인터랙티브 탐색은 브라우저에서:
> - Swagger: `http://127.0.0.1:2024/docs`
> - 원본 spec: `http://127.0.0.1:2024/openapi.json`
>
> TS 클라이언트 자동 생성: `npx openapi-typescript http://127.0.0.1:2024/openapi.json -o medi-back.d.ts`

---

## 목차

1. [단일 endpoint](#단일-endpoint)
2. [인증·CORS](#인증cors)
3. [~~LangGraph 라우트~~ — ⛔ **은퇴(2026-07-14)**, 역사 참고](#langgraph-라우트--agent-그래프-호출)
4. [커스텀 라우트 — 보고서·가이드 질문](#커스텀-라우트--보고서가이드-질문)
5. [공통 데이터 모양](#공통-데이터-모양)
6. [~~흐름 예시 (TS 의사코드)~~ — 구경로 기준, 현행은 frontend_chat_v2.md](#흐름-예시-ts-의사코드)
7. [에러 핸들링](#에러-핸들링)
8. [**신경로 (현행)** — POST /chat · POST /reports](#신경로-poc)

---

## 단일 endpoint

| 영역 | 라우트 | 인증 |
|---|---|---|
| **채팅 (현행, §8)** | `POST /chat`(SSE), `GET /chat/threads`, `GET /chat/{tid}/state`, `PATCH`·`DELETE /chat/{tid}`, `POST /chat/{tid}/auto-title` | NextAuth JWT (`AuthMiddleware`) |
| **보고서 (현행, §8)** | `POST /reports`, `GET /reports/runs/{idem}`, `GET /threads/{tid}/reports`, `GET /reports/{rid}`(+`/download`) | NextAuth JWT (+prod `API_TOKEN` Bearer — 조회 3종) |
| **커스텀 (가이드·모니터)** | `/healthz`, `/readyz`, `/load`, `/legal*`, `/suggestions` | 항상 공개 |
| ~~LangGraph 기본~~ | ~~`/info`, `/threads`, `/threads/{tid}/runs/stream`, `/threads/{tid}/state`, `/runs/{rid}`, ...~~ | ⛔ **은퇴(2026-07-14)** — §8 로 대체, 호출 시 404 |

서버 = uvicorn `src.api:app` 단일(FastAPI). ~~`langgraph.json` `http.app` 마운트~~ 구조는
2026-07-14 컷오버(ADR-0001 Phase 5)로 은퇴 — `langgraph dev` 런타임·sidecar 개념 자체가 없음.

**~~그래프 (assistant_id)~~ — ⛔ 은퇴(2026-07-14)**: `agent`(채팅)·`agent_report`(보고서)
그래프와 `assistant_id` 트리거는 langgraph 런타임과 함께 소멸. 채팅 = `POST /chat`,
보고서 = `POST /reports`(멱등키) — §8. 역사: `docs/spec/ADR-0001-*` + git history.

---

## 인증·CORS

### CORS

기본 허용 origin (env `API_CORS_ORIGINS` 미설정 시):
```
http://localhost:3000  http://127.0.0.1:3000  http://localhost:5173  http://127.0.0.1:5173
```

다른 origin이 필요하면 백엔드 `.env`에 콤마 구분으로 추가:
```bash
API_CORS_ORIGINS=http://localhost:3000,http://192.0.2.50:3000,https://medi.example.com
```

### 인증

- **기본 인증 = `AuthMiddleware` 단일**(NextAuth JWT, `NEXTAUTH_SECRET` medi-front 공유).
  `/chat`·`/reports` 계열 전부 `Authorization: Bearer <jwt>` 필수. dev(secret 미설정)=dev identity.
- **클로즈 베타 게이트**: `BETA_WHITELIST_EMAILS` 설정 시 목록 밖 사용자는 유효 JWT 여도 403.
- **thread 소유권은 서버 검사**: 남의 thread_id 로 POST /chat·/reports·조회 시 전부 **404**(존재 비노출).
- **보고서 조회 3종 추가 토큰**(레거시): prod 에서 `API_TOKEN=<강한토큰>` 설정 시
  `/threads/{tid}/reports`, `/reports/{rid}`, `/reports/{rid}/download` 에 해당 Bearer 검사
  (401 헤더 누락 / 403 불일치). dev 는 비워두면 통과.

`/healthz`, `/readyz`, `/load`, `/legal*`, `/suggestions`는 항상 공개.
(~~LangGraph 기본 라우트의 LangSmith key 인증~~ 은 2026-07-14 은퇴.)

---

## LangGraph 라우트 — agent 그래프 호출

> ⛔ **은퇴 (2026-07-14, ADR-0001 Phase 5 컷오버)** — 이 섹션의 라우트는 서버에서
> **삭제**됐다(호출 시 404). langgraph 런타임·그래프·checkpointer 와 함께 소멸.
> **현행 계약: [§8 신경로](#신경로-poc) + [`frontend_chat_v2.md`](./frontend_chat_v2.md)**
> (구경로→신경로 매핑표 포함). 아래 본문은 **역사 참고용**으로만 남긴다.

### 1) ~~`POST /threads`~~  — thread 생성

```http
POST /threads HTTP/1.1
Content-Type: application/json

{}
```

응답:
```json
{
  "thread_id": "9d6f...-...-...",
  "created_at": "2026-04-29T07:00:00Z",
  "status": "idle",
  ...
}
```

### 2) ~~`POST /threads/{thread_id}/runs/stream`~~  — 답변 스트리밍 (단일 thread)

```http
POST /threads/{thread_id}/runs/stream HTTP/1.1
Content-Type: application/json

{
  "assistant_id": "agent",
  "input": {
    "messages": [
      { "type": "human", "content": "<사용자 질문>" }
    ]
  },
  "stream_mode": ["values", "messages-tuple"],
  "stream_subgraphs": true
}
```

응답: **Server-Sent Events** (`text/event-stream`).

각 SSE chunk의 `data:` 부분은 JSON. 주요 이벤트:

| event | data 모양 | 무엇 |
|---|---|---|
| `values` | `{messages, files, steps}` 전체 state 스냅샷 | 도구 호출·tool result 거의 매 turn |
| `messages-tuple` | `[message, metadata]` | LLM 토큰 스트리밍 (시각적 답변 출력) |

**프런트 패턴**: `messages-tuple` 이벤트로 점진 표시 → 스트림 종료 시 `values`의 마지막 ai message가 최종 답변.

#### 2-1) `<next_steps>` 마커 — 추천 질문 카드 출력 계약 (엄수)

> ✅ 이 **마커 계약 자체는 현행 유지** — 전송 라우트만 은퇴했고, `POST /chat`(§8)의
> 답변 본문에 동일하게 적용된다(파서 무변경 재사용).

답변 본문 *끝*에 백엔드가 다음 마커 블록을 박는다. 프런트는 이걸 정규식
파싱해 추천 질문 카드로 렌더하고 **본문에서는 제거**한다 (현행
`lib/parse/nextSteps.ts` 가 이미 이 포맷):

```
[답변 본문 … 인라인 [n] 인용 포함]

<next_steps>
[
  {"title": "1~2단어 라벨(≤12자)", "prompt": "클릭 시 prefill될 한국어 한 줄 질문(≤60자)"},
  …
]
</next_steps>
```

- 시작/종료 태그 `<next_steps>`·`</next_steps>` 정확히. 안은 JSON 배열만.
- items **2~4개**, 각 `{"title": str, "prompt": str}`.
- 인사("ㅎㅇ" 등) turn: 고정 도입문 + 시작용 질문 마커가 옴.
- **writer 보고서 turn·ask_clarify turn 에는 마커 없음** — 그 turn은 본문만.
- 스트리밍 중 마커가 partial일 수 있음 → close 태그까지 도달 후 JSON 파싱
  (open만 도달 시 그 이후를 노출하지 말고 strip — 현행 파서가 처리).

> 회귀 주의: 2026-05-19 단일 thread 전환 때 이 계약이 백엔드 프롬프트에서
> 빠져 카드가 사라진 인시던트 있었음(`a5eb315`로 복원). 프런트 파서는 정상.

### 3) ~~심층 보고서 — 같은 thread + `assistant_id:"agent_report"`~~ (→ 현행 `POST /reports`, §8)

> **2026-05-19 변경**: fast/deep 분리·별도 deep thread·`parent_thread_id`·
> `[FAST_ANSWER]` 합성 페이로드·`agent_deep` 그래프 **전부 폐기**. 보고서는
> 별도 디스패치가 아니라, **현재 chat thread에서 agent가 한 턴 더 도는 것**.

#### 3-1) 트리거

> **현행 계약**: [`frontend_chat_v2.md`](./frontend_chat_v2.md) §4 (POST /reports + 멱등키 + 폴링).

보고서는 **같은 chat thread**에 `assistant_id: "agent_report"` 로 보낸다
(`agent` 가 아님 — 2026-05-20 분리). `config.configurable.idempotency_key`
(`rpt_<uuid>` 형식) 한 키만 추가하면 끝(§2 와 동일
`/threads/{thread_id}/runs/stream`, SSE). 보고서 주제는 *클릭한 next_steps
prompt 를 `input.messages` 의 human 메시지로* 실어 보내면 자연스레 잡힌다
— 별도 포인터(`target_message_id` 등) 불필요. supervisor LLM 미관여 —
`agent_report` 그래프 자체가 결정적 분기(entry_check → report_pipeline).
별도 thread 생성·`parent_thread_id`·합성 트리거 블록 **모두 불필요**.

- 사용자가 `<next_steps>` 의 보고서 항목(예: `{"prompt": "이 주제로 종합
  보고서 작성해줘"}`)을 클릭하거나 직접 보고서를 요청 → 그 텍스트가 그대로
  human 메시지로 §2 스트리밍에 실려 감.
- 단일 agent 가 **사용자 동의를 확인한 turn 에서만** writer 서브에이전트에
  위임 → writer 가 `save_report()` 호출 → 보고서 영속. 동의 없이는 안 만듦.
- 직전 대화(질문·답변·인용)가 *같은 thread 메시지에 이미 있으므로* fast
  컨텍스트를 따로 박아 보낼 필요 없음.

#### 3-2) 스트리밍 & 블로킹 (단일 thread 트레이드오프 — 프런트 필수 인지)

보고서 turn 은 §2 와 같은 SSE 스트림으로 진행(`messages-tuple` 로 진척
표시 가능). langgraph 는 **thread 당 단일 워커 큐** → 보고서 생성(수 분)
동안 같은 thread 의 다음 run 은 직렬화된다. 단일 thread 설계의 의도된
트레이드오프. **프런트 UX 결정(확정 2026-05-19): 차단 유지 + 새 thread
탈출구**:

- 보고서 turn 동안 같은 thread 입력창 **disable** + "보고서 생성 중…"
  진척 표시 (이 turn 의 SSE 를 그대로 따라감 — 백그라운드 fire-and-forget
  아님). 같은 thread 로 **큐잉하지 않음** — 보고서 뒤에 처리돼 대화 순서가
  꼬이는 패턴을 피함(기존 "생성 중 입력 차단" 결정과도 일치).
- 다른 주제를 동시에 묻고 싶으면 **"새 대화에서 질문하기"** 버튼으로
  새 thread 를 연다(thread 단위 격리는 그대로). = 차단의 탈출구.

#### 3-3) 결과 조회

보고서 완료는 §`GET /threads/{thread_id}/reports` 로 **같은 chat
thread_id** 조회 (별도 thread 아님). writer 의 `save_report()` 가
완료되면 그 목록에 `status: "done"` 으로 나타남.

### 4) ~~`GET /threads/{thread_id}/state`~~  — 현재 state 스냅샷 (→ 현행 `GET /chat/{tid}/state`)

```http
GET /threads/{thread_id}/state HTTP/1.1
```

응답:
```json
{
  "values": {
    "messages": [...],
    "files": { "/final_report.md": {...} },
    "steps": [...]
  },
  "next": [...],
  "tasks": [...]
}
```

### 5) ~~`GET /threads/{thread_id}/runs/{run_id}`~~  — run 상태 폴링 (→ 현행 `GET /reports/runs/{idem}`)

```http
GET /threads/{thread_id}/runs/{run_id} HTTP/1.1
```

응답:
```json
{
  "run_id": "...",
  "status": "running" | "success" | "error",
  ...
}
```

### 6) ~~`POST /threads/{thread_id}/runs/{run_id}/cancel`~~  — run 취소 (→ 현행: 채팅은 SSE abort)

deep 진행 중 사용자가 cancel 시.

---

## 커스텀 라우트 — 보고서·가이드 질문

> 같은 endpoint(`http://127.0.0.1:2024`)의 FastAPI 앱이 서빙. 이 섹션 라우트는
> **전부 현행**(채팅·보고서 트리거만 §8 신경로로 이동).

### 1) `GET /healthz`

```json
{ "status": "ok" }
```

### 2) `GET /suggestions` — 환영 메시지 + 가이드 질문 *(인증 X)*

새 채팅 시작 화면(Claude·Gemini-style)에 즉시 표시할 정적 데이터. LLM 호출 0회·즉시 응답.

```http
GET /suggestions HTTP/1.1
```

응답 (v2, 2026-05-01~):
```json
{
  "version": "2",
  "updated_at": "2026-05-01",
  "welcome_message": "안녕하세요. 의료 규제에 대해 무엇을 도와드릴까요?",
  "intro_hint": "조항·고시 번호, 제품 등급(예: Class III), 시점(예: 2026년 1월 개정 이후) 같은 단서가 있으면 더 정확한 답변을 드릴 수 있어요.",

  "examples": [
    {
      "id": "approval",
      "label": "허가·인증",
      "icon": "stamp",
      "prompt": "의료기기 등급별 허가·인증·신고 절차와 필요 자료 알려줘"
    },
    {
      "id": "advertising",
      "label": "광고·심의",
      "icon": "megaphone",
      "prompt": "의료기기 광고 사전심의 받으려면 어떻게 해야 하나요?"
    },
    {
      "id": "clinical",
      "label": "임상시험",
      "icon": "flask",
      "prompt": "Class III 의료기기 임상시험계획 승인 자료 요건과 IRB 절차는?"
    },
    {
      "id": "post_market",
      "label": "시판 후 안전",
      "icon": "alert-triangle",
      "prompt": "의료기기 부작용 보고 시한·리콜 절차·재심사 대상은?"
    }
  ],

  "categories": [
    { "id": "approval",     "label": "허가·인증",     "icon": "stamp",          "questions": [...] },
    { "id": "advertising",  "label": "광고·심의",     "icon": "megaphone",      "questions": [...] },
    { "id": "clinical",     "label": "임상시험",      "icon": "flask",          "questions": [...] },
    { "id": "post_market",  "label": "시판 후 안전",  "icon": "alert-triangle", "questions": [...] }
  ]
}
```

#### 프런트 사용 패턴 (Claude/Gemini-style)

**`examples` 필드** — 새 채팅 시작 화면 카드 4개. 클릭 시 `prompt` 문자열을 input에 prefill (또는 자동 전송).

```
┌──────────────────────────────────────────────┐
│         안녕하세요.                          │
│   의료 규제에 대해 무엇을 도와드릴까요?      │
│                                              │
│  [🏛️ 허가·인증]  [📢 광고·심의]             │
│  [🧪 임상시험]   [⚠️ 시판 후 안전]           │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ 무엇을 도와드릴까요?                ↑  │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

```ts
// 카드 클릭 → input prefill
function onExampleClick(ex: Example) {
  setChatInput(ex.prompt);
  // 또는 자동 전송: sendMessage(ex.prompt);
}
```

**`categories` 필드** — 사용자가 "다른 주제"로 expand하고 싶을 때 drill-down. 더 많은 질문 펼치기·아코디언 등.

#### 타입
```ts
type Suggestions = {
  version: string;
  updated_at: string;
  welcome_message: string;
  intro_hint: string;
  examples: Array<{
    id: string;
    label: string;          // 카드 짧은 라벨 (1~2 단어)
    icon: string;           // lucide-react 호환 키
    prompt: string;         // 클릭 시 input에 prefill될 한국어 질문
  }>;
  categories: Array<{
    id: string;
    label: string;
    icon: string;
    questions: string[];    // drill-down용
  }>;
};
```

내용 수정은 백엔드 `data/suggested_questions.json` 파일만 변경. 서버 재시작 불필요 (읽기 시점 로드).
`icon` 값은 lucide-react·heroicons 호환 키 — 프런트가 자유 매핑.

### 3) `GET /threads/{thread_id}/reports`

```http
GET /threads/{thread_id}/reports HTTP/1.1
Authorization: Bearer <API_TOKEN>     # prod만
```

응답:
```json
{
  "thread_id": "9d6f-...",
  "count": 3,
  "reports": [
    {
      "id": "43c35e44...",
      "thread_id": "9d6f-...",
      "run_id": null,
      "mode": "deep",
      "kind": "final",
      "status": "done",
      "blob_uri": "file:///.../43c35e44.md",
      "title": "final_report",
      "citations": [{ "n": 1, "title": "...", "publisher": "...", ... }, ...],
      "created_at": "2026-04-29T07:30:00Z",
      "completed_at": "2026-04-29T07:35:00Z",
      "error_message": null
    },
    ...
  ]
}
```

`status` 값: `"running" | "done" | "error"`. 프런트는 `done` 3건(`kind = final|rag|web`) 모이면 보고서 준비 완료.

### 4) `GET /reports/{report_id}` — 메타 1건

```json
{
  "id": "43c35e44...",
  "kind": "final",
  "status": "done",
  "title": "final_report",
  "citations": [...],
  "blob_uri": "file:///...",
  "download_url": "https://storage.googleapis.com/...?X-Goog-Signature=..."  // gcs 백엔드일 때만, ttl 1h
}
```

`download_url`이 있으면 그걸로 직접 GCS에서 받기. 없으면 (local dev) 다음 라우트 사용.

### 5) `POST /chat/{thread_id}/auto-title` — 사이드바 제목 자동 생성

첫 user message를 5~15자 한국어로 LLM 요약해 thread title에 박는다(threads_repo).
이미 title이 있으면 LLM 호출 없이 그대로 반환(idempotent).
~~`POST /threads/{tid}/auto-title`~~ 은 2026-07-14 은퇴 — 응답 shape 는 동일.

```http
POST /chat/{thread_id}/auto-title HTTP/1.1
Authorization: Bearer <jwt>
```

응답:
```json
{
  "thread_id": "9d6f-...",
  "title": "의료기기 광고 사전심의",
  "cached": false        // 새로 생성 / true = 기존 title 유지
}
```

에러:
| HTTP | 의미 |
|---|---|
| 404 | thread 또는 state 없음 |
| 409 | human message가 아직 없음 — fast turn 끝난 뒤 호출 권장 |
| 502 | LLM 실패 |

권장 호출 시점: **첫 답변 SSE 스트리밍이 종료된 직후 1회** (같은 thread).

모델 선택 우선순위: `TITLE_MODEL` env > `SUBAGENT_MODEL` env > `anthropic:claude-haiku-4-5-20251001`.

### 6) `GET /me/usage` — 본인 토큰 사용량

```http
GET /me/usage HTTP/1.1
Authorization: Bearer <jwt>
```

응답:
```json
{
  "user_id": "u-...",
  "email": "alice@example.com",
  "is_admin": false,
  "effective_daily_limit": 100000,
  "effective_monthly_limit": 2000000,
  "usage": {
    "daily_input_tokens": 23456,
    "daily_output_tokens": 5432,
    "daily_total_tokens": 28888,
    "daily_cost_usd": 0.124,
    "monthly_input_tokens": 234560,
    "monthly_output_tokens": 54320,
    "monthly_total_tokens": 288880,
    "monthly_cost_usd": 1.24
  }
}
```

또한 LLM 호출 라우트(`POST /chat`) 응답 헤더에 자동 포함:
```
X-Quota-Daily-Used: 28888
X-Quota-Daily-Limit: 100000
X-Quota-Monthly-Used: 288880
X-Quota-Monthly-Limit: 2000000
```

한도 초과 시 — 429 응답:
```json
{
  "detail": "오늘 사용량 한도(100,000 토큰)에 도달했습니다. 내일 다시 이용 가능합니다.",
  "period": "daily",
  "tokens_used": 100200,
  "tokens_limit": 100000
}
```

### 7) `POST /threads/{tid}/messages/{mid}/feedback` — 메시지 평가

```http
POST /threads/{tid}/messages/{mid}/feedback HTTP/1.1
Content-Type: application/json
Authorization: Bearer <jwt>

{
  "rating": "thumbs_up",       // "thumbs_down" | "canceled"(재클릭 취소)
  "comment": "정확합니다"        // optional, ≤2000자
}
```

응답: `{"feedback_id": "...", "rating": "thumbs_up"}`. 422 — 잘못된 rating.
저장은 append-only — 같은 (user, message) 의 **마지막 row 가 유효 평가**(last-wins).
`"canceled"` 는 직전 평가 취소를 뜻함(FE 👍/👎 재클릭).

### 8) `POST /reports/{rid}/feedback` — 보고서 평가

같은 형식. 응답에 보고서 메타도 events에 첨부됨. 404 — 없는 보고서.

### 9) Admin API (is_admin=true 만)

| 라우트 | 용도 |
|---|---|
| `GET /admin/users?limit=&offset=&q=` | 사용자 목록 + effective_*_limit + usage + **베타 접근 상태**(2026-08-02): 행마다 `created_at`(가입일)·`deleted_at`·`whitelisted`·`whitelist_source`(`admin`\|`env`\|`db`\|`domain:@x.com`\|null)·`can_access`. 응답 최상위에 `gate_active`. `q`=이메일 부분일치 DB 검색(2026-08-05 — 종전엔 프런트가 로드된 페이지만 걸러 51번째 이후는 검색 불가) |
| `PATCH /admin/users/{user_id}` | `daily_token_limit_override` / `monthly_token_limit_override` / `is_admin` / **`account_class`**(`staff`\|`test`\|`user`\|`auto`, 2026-09-21 — 실사용 집계 제외 여부). **JSON body 우선 + query fallback** 둘 다 수용(2026-05-19~, `a41b203`). `-1` = 시스템 기본값으로 리셋 — 단 영속층 COALESCE 라 override 를 *NULL 로 제거하지는 못함*: 현재 시스템 기본값을 *숫자로 박아* 리셋(재조회 시 override 가 그 숫자로 내려옴). 시스템 기본 한도 ×10: 일 `1,000,000` / 월 `20,000,000` (env `DEFAULT_*_TOKEN_LIMIT` 미설정 시; 운영은 `.env.docker` 우선) |
| `GET /admin/users/{user_id}/usage` | 사용량 상세 |
| `GET /admin/whitelist` · `POST`(단건 `entry` / 벌크 `entries` CSV·줄바꿈·배열) · `DELETE /admin/whitelist/{entry}` | 클로즈 베타 화이트리스트(env 읽기전용 ∪ DB). `BETA_GATE=1` 이면 목록 비어도 게이트 활성 |

**POST /admin/whitelist 응답 — 중복 사유 3종 구분**(2026-08-01)
```jsonc
{ "ok": true,
  "added":             ["new@x.com"],     // 실제로 새로 등록됨
  "duplicate":         ["old@x.com"],     // DB 에 이미 있음
  "already_in_env":    ["e@x.com"],       // BETA_WHITELIST_EMAILS 로 이미 허용(DB 추가 무의미)
  "covered_by_domain": ["kim@corp.com"],  // 등록된 @corp.com 이 이미 통과시킴
  "invalid":           ["쓰레기"] }        // 형식 오류
```
`added` 가 비면 실제 변경이 없으므로 게이트 캐시도 무효화하지 않는다.
종전에는 이미 있던 항목도 `added` 로 집계돼 벌크 100건에 "100건 추가"로 답했다.

**등록은 메일을 보내지 않는다**(2026-08-05). 초대는 아래 별도 엔드포인트로
**한 건씩** 보낸다 — 등록에 딸려 자동 발송하면 벌크 붙여넣기 한 번이 곧
되돌릴 수 없는 무더기 발송이 된다.

`GET /admin/whitelist` 의 `db_entries` 각 행에 발송 이력이 실린다:
```jsonc
{ "entry": "a@x.com", "added_by": "boss@x.com", "created_at": "…",
  "invited_at": null,        // null = 아직 미발송
  "invited_by": null,
  "joined_at": null }        // 값이 있으면 **이미 가입해 쓰고 있는 사용자**
```

### `POST /admin/whitelist/{entry}/invite` — 베타 초대 1건 발송

```jsonc
{ "ok": true, "entry": "a@x.com",
  "resent": false,                      // true = 이미 보낸 대상에 재발송
  "invited_at": "2026-08-05T…Z", "invited_by": "boss@x.com",
  "smtp_configured": true }
```
- 문구는 2026-08-03 베타 오픈 공지(`[MediReg AI] 베타 서비스를 시작합니다`)를
  그대로 쓴다. CTA 는 계정 생성(`/landing`).
- `404` 화이트리스트에 없는 항목 · `422` `@도메인`(수신자가 없다) ·
  **`409` 이미 가입한 사용자** · `502` 발송 실패.
- **기존 가입자 보호**: 계정이 있는 주소로는 기본적으로 나가지 않는다(409).
  초대 메일은 서비스 시작 안내라 사용 중인 분께는 어색하다. 정말 보내려면
  body `{"force": true}` — 응답 `forced_member: true` 로 남는다.
- 목록(`GET /admin/whitelist`)의 `joined_at` 이 가입 여부다. 화면은 이걸로
  `가입완료` 배지를 띄우고 미발송 목록에서 제외한다.
- **발송 실패 시 `invited_at` 을 찍지 않는다** — 안 간 메일을 '보냄'으로
  기록하면 화면이 거짓을 말하고 그 사람은 영영 초대받지 못한다.
- 이미 보낸 항목에도 다시 보낼 수 있다(관리자의 명시적 선택). `resent` 로 구분.
| `GET /admin/stats?days=&scope=` | 일별 집계(**한국시간 날짜**, 2026-09-21~) + `totals` + **`breakdown`**{`real`,`internal`,`all`}(같은 기간 3범위 지표, 전체 = 실사용 + 내부) + `metrics`(지표 정의) + `usage_capture` |
| `GET /admin/stats/weekly?weeks=12&include_prelaunch=false` | **주간 이용**(2026-09-21): 월~일(KST). 끝난 주는 app_settings `usage_weekly:v1:<월요일>` 저장본(없으면 계산·저장), 이번 주는 실시간(`partial`). 주마다 `scopes`{real,internal,all} 지표 · `stored` · `stale`(저장 후 계정 라벨이 바뀜) |
| `GET /admin/weekly-report/status` | 주간 보고서 메일(2026-09-21) — `{enabled, to, send_hour_kst, smtp_configured, next_run_at, last_week{week_start, sent}}` |
| `PATCH /admin/weekly-report/config` `{enabled?, to?, weekday?, hour?, reset?}` | 자동 발송 설정(관리자 화면) — app_settings `weekly_report_config` 가 env 기본값보다 우선, 준 항목만·`null`=그 항목 env 로·`reset`=전부. `to` 는 메일 형식 검증·최대 20명(422). 응답 = status(+`config.source`·`admin_email_options`) |
| `GET/POST /admin/report-notes` · `PATCH/DELETE /admin/report-notes/{id}` | 보고 노트(관리자 전용, 2026-09-21) — `{date, title, items[], feature, include}`. GET `since`·`until`(YYYY-MM-DD). 주간 보고 메일 '이번 주 업데이트'의 원천(포함분만) |
| `GET /admin/weekly-report/preview?week_start=` | 발송될 HTML 그대로(끝난 주만, 월요일) |
| `POST /admin/weekly-report/send` `{week_start?, to?}` | 지금 보내기 — `to` 는 보고서 수신자·관리자 메일만(422). 자동 발송 기록은 안 남김 |
| `POST /admin/stats/weekly/recompute` `{week_start?}` | 저장본 재계산 — `week_start`(월요일) 없으면 stale·누락 주 전부. 진행 중인 주·월요일 아님은 422 |
| `GET /admin/stats/search-laws?days=30&limit=30` | **이용자 검색 → 수집 법령 집계**(events.rag_search): 법령별 히트/검색 수 랭킹·종별 분포·최다 질의·검색 수·사용자 수. 채팅+보고서 수집 모두 적재(2026-07-19) |

### 10) `GET /reports/{report_id}/download` — 본문 (`?format=md|docx`)

```http
GET /reports/{report_id}/download?format=docx HTTP/1.1
```
- `format` (기본 `md`): `md` = 원본 Markdown, `docx` = Word 변환(pandoc).
- 변환 불가(pandoc 미설치) 시 **`.md` 로 자동 폴백**(200, `text/markdown`).
- 완료 이메일 첨부도 같은 변환 사용(기본 `REPORT_ATTACH_FORMAT=docx`).

응답 (md):
```http
HTTP/1.1 200 OK
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename="final_43c35e44.md"

# 의료기기법 제25조 ...
```
응답 (docx):
```http
HTTP/1.1 200 OK
Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
Content-Disposition: attachment; filename="final_43c35e44.docx"

PK... (zip 패키지)
```

브라우저에서 그대로 다운로드 트리거 가능.

### 11) 법령 조회 — citation 클릭 원문 모달 · 조문 즉답 · 별표

> 모두 `Authorization: Bearer <jwt>` 필요(공개 X).

**`GET /article?key=<article_key>`** — 조문 1건 본문+메타 (citation 클릭 시 원문 모달).
```jsonc
// 200
{
  "article_key": "009514_002500",
  "target_type": "law",          // law|admrul|ordin|treaty|prec|expc|decc|detc
  "law_id": "009514", "law_title": "의료기기법",
  "article_num": "제25조", "article_title": null,
  "display_title": "의료기기법 제25조",
  "full_text": "제25조(광고의 심의) ...",
  "body_source": "pg",           // pg|mongo (디버그)
  "is_body_complete": true,      // len≥200 휴리스틱 (FE 경고용)
  "department": "...", "enforce_date": "2021-06-24",
  "external_url": "https://www.law.go.kr/법령/의료기기법/제25조"
}
// 404 — article_key 미발견
```

**`GET /article/lookup?q=<자연어>`** *(신규 — Tier-0 즉답)* — "법령명 제N조"를 **LLM 없이** PG 직접조회로 해석해 `/article` 과 동일 페이로드 반환. 조문지정 질의를 FE가 감지해 채팅 대신 호출(즉답·저비용). 식별 실패 시 404 → FE는 일반 채팅으로 폴백.
```http
GET /article/lookup?q=의료기기법 제25조 인용해줘
```
```jsonc
// 404 — 식별 실패
{ "detail": { "message": "조문을 식별하지 못했습니다", "q": "...", "hint": "예: 의료기기법 제25조" } }
```

**`GET /annex?lawId=<id>&annexNum=<n>`** — 별표·서식 본문. `annexNum`은 `"19"`·`"19의2"` 표시형.
```jsonc
{ "law_id":"009740", "annex_num":"1", "attachment_key":"009740_000100E_attachment",
  "title":"...", "type":"별표", "markdown":"...", "download_url":null, "source_uri":null }
// 404 미발견 · 422 lawId/annexNum 누락
```
> 소스: Neo4j Attachment 우선, **미적재 시 PG fallback**(2026-07-10 — 현재 Neo4j 는
> Attachment 0건이라 실질 PG 서빙). PG 경로는 본문 완전하나 law.go.kr 다운로드
> 링크가 없어 `download_url=null` — HWP 다운로드 버튼은 Neo4j 적재 후 복원.

**`GET /annex/list?lawId=<id>`** — 법령 내 별표·서식 목록.
`{ "law_id": str, "count": int, "items": [{attachment_key, title, type("별표"|"서식"), annex_num("19"|"19의2")}] }`

**`GET /law/{lawId}/articles?limit=200`** — 법령에 속한 조문 목록.
`{ "law_id": str, "count": int, "items": [{article_key(PG 정준 7자리), article_num("제N조"|"제N조의M"), article_title}] }`

### 12) `GET /law-graph` — 법률 네트워크 서브그래프 *(신규 — 요구사항 ④)*

채팅 응답의 인용(article_key)을 seed 로 **조문 인용 네트워크**를 반환. 전문가가 노드를 보며 grounding 대상을 직접 선택 → 선택(`selected_law_keys`)은 **다음 `POST /chat` 요청 body 에 동봉**(비차단).
```http
GET /law-graph?keys=006364_000100,001275_000700&depth=1&rels=CITES&per_node_cap=25&max_nodes=80
```
- `keys` (필수, 콤마구분 ≤20) · `depth` 1~2 · `rels` (CITES·DELEGATES_TO·CITES_HISTORICAL·CORRESPONDS_TO·REGULATES_VIA) · `per_node_cap` 1~100 · `max_nodes` 1~300.
```jsonc
{
  "seeds": ["006364_000100"],
  "nodes": [{ "id","label","law_id","law_title","jo","gaji","target_type","enforcement_date","is_seed" }],
  "edges": [{ "source","target","type" }],
  "node_count": 0, "edge_count": 0, "truncated": false
}
// 422 seed 누락/과다·허용 안 된 rel · 503 Neo4j 비활성
```

### 13) `GET /readyz` — readiness 헬스체크 *(신규 · 인증 X · LB/모니터용)*

`/healthz`(liveness, 항상 200)와 달리 **외부 의존 6종을 병렬 probe**. critical(PG·search_api) 다운 시 **503**. DGX 가드레일·writer 는 non-critical(폴백 동작)이나 **다운 시 warning ops 알림**(PII NER 다운 = 마스킹 저하 = 컴플라이언스). LB 는 503 만 보고 트래픽 제외.
```jsonc
// 200(ok) 또는 503(degraded)
{ "status": "ok",
  "checks": { "postgres":      {"status":"ok","critical":true,"latency_ms":12},
              "search_api":    {"status":"down","critical":true,"latency_ms":4001,"detail":"timeout >4s"},
              "neo4j":         {"status":"ok","critical":false,"latency_ms":30},
              "pii_ner":       {"status":"ok","critical":false,"latency_ms":18},   // 다운→regex-only
              "intent":        {"status":"ok","critical":false,"latency_ms":21},   // 다운→휴리스틱
              "report_writer": {"status":"ok","critical":false,"latency_ms":9} } } // 다운→보고서만 영향
```

### 13-c) `GET /legal` — 법적 고지 정본 *(신규 · 인증 X · 상시 노출용)*

면책 문구를 **LLM 이 생성하지 않는다**(표현 흔들림·누락 방지) — 정본은 `src/legal.py`,
보고서엔 시스템이 결정적 부착. 프런트는 이 응답을 **푸터/배너로 상시 노출**한다
(세션당 1회 안내보다 법적으로 안전). `version` 변경 시 재동의를 받을 수 있다.
```jsonc
{ "version": "2026-07-09",
  "disclaimer_short": "본 답변은 AI가 법령 원문을 검색·요약한 참고 정보이며 …",
  "disclaimer_report": "## 법적 고지

본 보고서는 …",
  "key_points": ["AI가 생성한 참고 정보이며 법률자문이 아닙니다.", "… 국외 AI 서비스로 전송됩니다"],
  "docs": { "terms": "/docs/legal/terms.md", "privacy": "/docs/legal/privacy.md" } }
```
- 약관·개인정보처리방침 초안: [`docs/legal/`](../legal/) (⚠️변호사 검토 필요)

### 13-b) `GET /load` — 서버 부하/혼잡 *(신규 · 인증 X · 프런트 폴링용)*

검색 백프레셔·보고서 큐의 실시간 점유. 프런트가 폴링해 **'원활/혼잡' 배지**를 띄우면
느려도 사용자가 이해하고 사용. (채팅 스트림 중엔 혼잡 시 `tool_progress`로 "서버
혼잡 · 느릴 수 있어요"도 옴.)
```jsonc
{ "status": "ok" | "busy",                 // busy = 검색 대기 발생 또는 슬롯 만석
  "search":  { "active": 1, "waiting": 0, "limit": 2 },
  "reports": { "active": 0,
               "paused": false, "message": null,   // 기능 단위 일시 중단(2026-09-07, admin 토글) — true 면 POST /reports 503
               "writer_up": true },                 // DGX writer 프로브(30s 캐시) · null = 로컬 writer 미설정
  "maintenance": { "active": false },
  "features": {} }                                   // 중단된 기능만 {reports: {paused, message, since}}
```
- TS: `type LoadStatus = { status: "ok"|"busy"; search:{active:number;waiting:number;limit:number}; reports:{active:number} }`
- 권장 폴링 주기 ~5s. `busy` 지속 시 "지금 이용자가 많아 응답이 느릴 수 있어요" 안내.

### 13-e) `GET /legal/{terms|privacy}` — 법적 문서 **정본** *(인증 X)*

약관·개인정보처리방침의 단일 진실원. 프런트는 하드코딩 대신 **이걸 받아 렌더**한다
(과거 front 페이지와 back 문서가 두 벌이라 §3 보유기간·§5 이전받는 자가 어긋났음).
```jsonc
{ "doc": "privacy", "version": "2026-07-09", "format": "markdown", "content": "# 개인정보처리방침 …" }
```
- `terms`·`privacy` 외에는 404.

### 13-d) 정보주체 권리 — `GET/POST /me/consent` · `GET /me/data` · `POST /me/erase` *(인증 필요)*

개인정보보호법 이행. 방침에 적고 구현 안 하면 허위 고지가 되므로 **코드로 보장**한다.

| 엔드포인트 | 법 | 용도 |
|---|---|---|
| `GET /me/consent` | 제28조의8 | `{current_version, agreed_version, agreed_at, needs_consent}` — `needs_consent` 면 동의 화면 |
| `POST /me/consent` `{version, scopes[]}` | 제28조의8 | **동의 기록**(버전·시각·항목). 필수 `terms`+`transfer`(국외이전은 별도동의) 누락 시 400, 버전 불일치 409 |
| `GET /me/data` | 제35조 | 열람 — 보관 데이터·보존기간·국외이전 수령자 |
| `POST /me/erase` `{reason?}` | 제36·37조 | 삭제 요구 접수 → ops 알림 → 운영자가 `scripts/erase_user.py` 로 파기 |

> ⚠️ 동의는 `/legal/consent` 가 **아니다**. `/legal` 은 공개 prefix(인증 우회)라 그 아래
> 두면 `user_id` 가 안 박힌다.

### 14) 일반 피드백 — `POST /feedback/general`, `GET /admin/feedback`

`POST /feedback/general` — thread/메시지 없는 자유 코멘트(@feedback). body `{ "comment": str }`.
`GET /admin/feedback` *(admin)* — 누적 코멘트·평가 집계.

### 15) 내 계정 — prefs · profile · 탈퇴 *(인증 필요)*

| 엔드포인트 | 용도 |
|---|---|
| `GET /me/prefs` | `{report_email_opt_in}` — 보고서 완료 이메일 수신 여부 |
| `PATCH /me/prefs` `{report_email_opt_in: bool}` | 수신 여부 변경 |
| `GET /me/profile` | `{display_name, affiliation, job_role, completed}` — 온보딩 폼 초기값. `completed=false` 면 미입력 |
| `PUT /me/profile` `{display_name?, affiliation?, job_role?}` | 프로필 전체 저장(각 ≤80자, 빈 문자열=해제). 가입 draft 를 front `ProfileInit` 이 자동 제출 |
| `POST /me/withdraw` `{reason?}` | 회원탈퇴(소프트삭제 — `users.deleted_at`). 파기는 `/me/erase` 별도 절차. 관리자 복구: `POST /admin/users/{id}/restore` |

### 16) 인용 신고 — `POST /feedback/citation` *(인증 필요)*

body `{thread_id, message_id, citation_id, number?, title?, reason}` — 부적절 인용
신고. feedback repo + events(`citation_report`) 이중 기록 → admin 통계 집계.

### 17) 베타 게이트 사전 확인 — `POST /beta/check` *(인증 X)*

body `{email}` → `{allowed, gate_active}` — 가입 폼이 매직링크 발송 **전에** 화이트리스트
여부를 확인해 명시 에러를 보여주는 용도(발송 후 침묵 차단 방지). 목록은 비노출(boolean 만).

### 18) Admin 추가 라우트 *(admin)*

| 엔드포인트 | 용도 |
|---|---|
| `GET /admin/maintenance` | 점검 모드 상태 `{manual, message, schedule, updated_at?}` |
| `POST /admin/maintenance` `{on, message?}` / `{schedule: {enabled, start, end}, message?}` | 점검 즉시 on/off · 매일 반복 예약 |
| `POST /admin/maintenance` `{features: {reports: {paused, message?}}}` | **기능 단위 일시 중단**(2026-09-07) — 보고서·서류 작성 `POST /reports` 만 503(`X-Feature-Paused: reports`), 채팅 정상. GET 응답에 `features`·`feature_names`·`feature_default_messages`·`writer_up`(DGX writer 프로브) |
| `POST /admin/users/{id}/restore` | 탈퇴(소프트삭제) 계정 복구 |
| `GET /admin/pii-terms/context?term=` | PII 라벨링 문맥(2026-09-21) — 관측 대화(최근 5)에서 가림 표시가 든 질문의 앞뒤 `{before, mark, after, same_kind}` · `missing_threads`. 원문 아님(가린 상태로만 저장) |
| `GET /admin/stats/claim-audit?days=&scope=` | 무인용 사실 검증(환각 신호) 집계 — 이용조회 "사실 검증" 탭 |
| `GET /admin/review-queue?days=14&limit=50&random_pct=10&include_reviewed=0&scope=` | 답변 검수 큐 — 위험 신호 점수순 + 무작위 표본. item: `thread_id·message_id·lane(rag\|skill)·signals[]·priority·random_sample·verified_rate·citations_used/retrieved·claim_samples[]·searches[]`. 응답에 `verdicts[]`·`error_types[]`(폼 선택지) |
| `POST /admin/reviews` | 채점 저장 `{thread_id, message_id, verdict, error_types[], note?}` — 답변×검수자 upsert. verdict=correct 면 error_types 는 서버가 비움 |
| `GET /admin/reviews?thread_id=` | thread 의 채점 이력(원문 뷰어 배지용) |
| `GET /admin/reviews/archive?days=365&limit=200&verdict=` | **채점 내역**(2026-09-18) — 채점 시점의 `question_snapshot`·`answer_snapshot`(마스킹 저장본) 포함, `thread_alive` 로 원 대화 존재 여부. 대화 90일 삭제 뒤에도 근거 열람 |
| `GET /admin/reviews/stats?days=30&random_pct=10` | 판정·오류유형 분포 + `accuracy_random`(무작위 표본 정답률·Wilson CI — **이것만 서비스 정답률**) · `accuracy_all_reviewed`(참고, 편향) |
| `GET /admin/events/summary?days=&scope=` | 관측 이벤트 요약(model_ab·skill_verdict·unverified_contact·report_quality·report_download) — 카운트+샘플 |
| `GET /admin/questions?days=&limit=&scope=` | 이용자 질문 목록(마스킹본) + **작성자**(email·display_name·affiliation·job_role) |

### 18-b) PII 오탐 신고 — `POST /feedback/pii` *(인증 필요, 2026-08-13)*

body `{thread_id, term, placeholder?, message_id?, comment?}` — `pii_notice` 의
`masked_text` 로 짚어낸 **잘못 마스킹된 단어**를 신고. **선보고 후조치** —
신고 즉시 마스킹 제외(≤10s 반영, 재배포 불요) + events(`pii_report`).
구조적 PII 형식(주민번호·전화 등)은 422 로 거부.

**전수 수집 + 라벨링**: 신고와 무관하게 채팅에서 NER 마스킹된 모든 단어가
자동 등재된다(`pii_terms.observe_many`, chat_loop 배선). 관리자는 각 단어를
correct(정탐 — 마스킹 유지·복귀)/wrong(오탐 — 영구 제외) 로 라벨:

| 엔드포인트 | 용도 |
|---|---|
| `GET /admin/pii-terms?status=&reported_only=` | 개선리스트 — status: unlabeled(자동 수집)/reported(신고, 즉시 적용 중)/correct/wrong. reported_only=true 로 신고분만 |
| `POST /admin/pii-terms/{term}` `{label: correct\|wrong}` | correct=마스킹 유지·복귀 / wrong=마스킹 영구 제외 |
| `DELETE /admin/pii-terms/{term}` | 제거(wrong 이었다면 즉시 다시 마스킹 대상) |

신고 현황은 `POST /admin/feedback/digest` 요약에도 실린다(사후 검토 누락 방지).

### 18-c) 패치노트 — `GET /announcements/latest` *(공개, 2026-08-13 · 2026-09-02 공개 전환)*

`{announcement: null | {id, date, title, items[]}}` — 프런트 최초 접속 팝업 1회
(localStorage id 비교). **팝업 후보는 가장 최근 발행 1건뿐**(2026-09-18) — 그게 숨김이거나 `popup=false` 면 null, 이전 노트로
내려가지 않는다. `?seen=id,id` 에 그 id 가 있으면 null. admin `PATCH /admin/announcements/{id}` 는
`{hidden}`(게시판·팝업 모두 내림)·`{popup}`(팝업만, 게시판엔 남김) 독립. 발행 body 에 `popup?`(기본 true). 목록: `GET /announcements?limit=&q=` — **공개 라우트**
(랜딩 `/updates` 게시판이 비로그인으로 열람), 숨김(hidden) 제외, `q` 키워드
검색(공백 구분 AND, 제목+항목 부분 일치, 대소문자 무시), 최대 100건 보관.
admin: `GET /admin/announcements`(숨김 포함 전체) · 발행 `POST /admin/announcements`
`{title, items[], date?, version?, feature?}`(version ≤20자 'v0.8.0' 보조 표기 · **feature ≤30자 기능 영역**(2026-09-07, `announcements.FEATURES` 권장: 검색·답변/심층 보고서/IRB·DRB 심의 상담/서류 작성/개인정보 보호/계정·이용/화면·편의) — 게시판 탭·배지, 둘 다 검색 대상). 목록 `GET /announcements?feature=` 필터 + 응답 `features`(탭 순서). admin 목록 응답에 `feature_presets`. · 숨김 `PATCH …/{id}` `{hidden}` · 철회 `DELETE …/{id}`.

### 19) 법령 부가 조회

| 엔드포인트 | 용도 |
|---|---|
| `GET /annex/list?lawId=` | 법령의 별표·서식 목록 (개별 변환은 `GET /annex`) |
| `GET /law/{lawId}/articles` | 법령 조문 목록(우측 패널 법령 브라우즈) |

### 20) 서식 작성 (서류 초안 기입)

| 엔드포인트 | 용도 |
|---|---|
| `POST /documents/from-form` `{thread_id, article_key, title?}` | 별표·서식으로 기입 문서 즉시 생성 → `{report_id, title, fields, filled, remaining}` |
| `GET /documents` `?limit=50` | **내가 작성한 서식 목록**(2026-09-18) — `{documents:[{id,title,thread_id,thread_alive,created_at,field_count,filled_count,status(empty\|partial\|done),kept}]}`. 본인 것만·최신순, 값 자체는 미포함 |
| `PATCH /documents/{id}` `{alias}` | 서식 **별명**(≤60자, 빈 값=해제). 원 제목은 보존. 목록 응답에 `alias`·`thread_title` |
| `POST /documents/{id}/keep` `{kept}` | 서식 **보관** 토글 — 보관한 서식은 원 대화가 삭제·만료돼도 남는다(아니면 대화와 함께 삭제) |
| `GET /documents/state?thread_id=` | 스레드 최신 초안 상태 `{report_id, fields, filled, remaining, title}` (없으면 `{report_id:null}`) |
| `POST /documents/{id}/fill` `{field, hint?, value?}` | 항목 기입(직접 값 / AI 작성 / `*` 일괄) → `{filled, values, remaining}` |
| `POST /documents/{id}/chat` `{message, history?, attachment_text?}` | 작성 도우미 1턴(온프레미스) → `{reply, filled, values, remaining, corrected}`. 503=로컬 모델 미가용 |
| `GET /documents/{id}/original-form` | 원문 서식(.hwp/.hwpx)에 값만 기입해 반환(`X-File-Ext`). 404=원문 없음, 503=kordoc 미배포 |
| `DELETE /reports/{id}` | 서식 삭제(소유자만, 타인 404). 서류면 run 의 report_id 도 분리 |
| `DELETE /chat/{thread_id}` | 대화 삭제 시 그 대화의 서식도 함께 삭제 — 응답 `documents_deleted`·`documents_kept` |

기입값(`filled_values`)은 DB 에 `enc1:` Fernet 암호문으로 저장(`FILLED_VALUES_ENC_KEY`, 미설정 시 `NEXTAUTH_SECRET` 파생). API 응답에는 소유자 인증 뒤 평문 JSON 문자열로 실린다.

---

## 공통 데이터 모양

### Citation
```ts
type Citation = {
  id: string;            // "cite_doc_<chunk_id>" or "cite_web_<hash>"
  number: number;        // [n] — fast→deep 사이 보존
  source_kind: "doc" | "web";
  title: string;
  publisher?: string | null;
  date?: string | null;          // ISO date (web은 보통 null)
  url?: string;                  // web only
  doc_id?: string;               // doc only
  article?: string;              // doc only — 예: "제25조"
  page?: number | null;          // doc only
  snippet: string;               // ≤300 chars
  status: "active" | "amended_pending" | "revoked";

  // R1 — citation_verifier 통과 여부. 프런트는 ConfidenceBadge에 사용.
  // RAG는 큐레이션 코퍼스라 기본 true. web은 publisher 화이트리스트(정부·공공) 매칭 시 true.
  verified?: boolean;

  // R2 — 문서 분야. RAG는 target_type 매핑, web은 URL best-effort.
  //
  // ⚠️ **법령정보센터(law.go.kr) 분야 목록과 같지 않다.** 앞의 13종은 law.go.kr
  // 로 링크를 만들 수 있지만, "가이드라인"(식약처 가이드라인·안내서, 2026-07-24
  // 추가)은 **법령정보센터에 없는 문서**다. 프런트는 이 값을 law.go.kr URL
  // 카테고리로 그대로 쓰면 안 된다 — 존재하지 않는 링크가 만들어지고
  // "법령정보센터에서 보기" 가 붙는다(실제 사고 2026-08-04, medi-front
  // lawLink.ts 에서 `as LawCategory` 캐스트가 런타임을 못 막았다).
  //
  // 규칙: **backend 가 url 을 주지 않았다면 그 문서는 law.go.kr 링크 대상이
  // 아니다.** 프런트가 publisher·제목 휴리스틱으로 합성하지 말 것.
  doc_category?:
    // law.go.kr 링크 가능
    | "법령" | "영문법령" | "행정규칙" | "자치법규"
    | "학칙공단" | "조약" | "판례" | "헌재결정례"
    | "법령해석례" | "행정심판례"
    | "법령별표서식" | "행정규칙별표서식" | "자치법규별표서식"
    // law.go.kr 링크 **불가** — 외부 링크 없음(url 미제공)
    | "가이드라인";

  // R4 — 판례 인용 시. source_kind="case" (또는 "constitutional") + title에 법원명 매칭 시.
  court?: string;                // "대법원" | "고등법원" | "헌법재판소" 등
  instance?: 1 | 2 | 3;          // 심급 — 대법원/헌재 = 3, 고등 = 2, 지방·행정 = 1
};
```

### FileEntry (state.files[*])
```ts
type FileEntry = {
  content: string[];             // 줄 단위 원본
  created_at: number;            // unix ms
  modified_at: number;
  is_streaming: boolean;

  // R3 — save_*_report 가 만든 step.id. ArtifactViewer가 생성 step을 정확히 매핑.
  generated_by_step_id?: string;
};
```

### Step (state.steps[*])
```ts
type Step = {
  id: string;
  ts: number;                    // unix ms
  status: "running" | "done" | "error";
  label: string;                 // 한국어, 사용자 표시용
  tool_name: string;             // 내부 — 사용자 노출 금지
  input_preview?: string;
  output_preview?: string;
  error_message?: string;
  citations?: Citation[];

  // turn 매핑 (2026-05-01~) — 프런트가 ts 휴리스틱 없이 step↔turn 정확 매칭
  source_message_id?: string;    // 이 step을 트리거한 human message의 id
  turn_idx?: number;             // 같은 thread 안의 human 메시지 0-based 순번
};
```

프런트 사용 패턴:
```ts
// state.messages 안의 human message 별로 step 그룹핑
const stepsByTurn = new Map<string, Step[]>();
for (const step of state.steps) {
  const key = step.source_message_id ?? "_fallback_";
  if (!stepsByTurn.has(key)) stepsByTurn.set(key, []);
  stepsByTurn.get(key)!.push(step);
}
// 또는 turn_idx 사용
const turnsByIdx = new Map<number, Step[]>();
state.steps.forEach(s => {
  if (s.turn_idx == null) return;
  if (!turnsByIdx.has(s.turn_idx)) turnsByIdx.set(s.turn_idx, []);
  turnsByIdx.get(s.turn_idx)!.push(s);
});
```

ts 기반 imputeHumanTs / deriveTurns 휴리스틱은 더 이상 불필요 — id 매칭 한 줄로 충분.

### ReportMeta
```ts
type ReportMeta = {
  id: string;                    // uuid hex
  thread_id: string;
  run_id: string | null;
  mode: "fast" | "deep";
  kind: "final" | "rag" | "web";
  status: "running" | "done" | "error";
  blob_uri: string | null;
  title: string | null;
  citations: Citation[] | null;
  created_at: string;            // ISO 8601
  completed_at: string | null;
  error_message: string | null;
};
```

---

## 흐름 예시 (TS 의사코드)

> ⛔ **구경로(langgraph) 기준 — 은퇴(2026-07-14)**. 현행 흐름(POST /chat SSE →
> auto-title → POST /reports + 폴링)의 실측 payload·TS 타입은
> [`frontend_chat_v2.md`](./frontend_chat_v2.md) 참조. 아래는 역사 참고용.

```ts
const BASE = "http://127.0.0.1:2024";  // 단일 endpoint — 모든 라우트 같은 origin
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN ?? "";  // dev 비활성 시 빈 문자열

const authHeader = API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {};

// 0) 첫 화면 — 환영 메시지 + 가이드 질문 칩
const intro = await fetch(`${BASE}/suggestions`).then(r => r.json());
// intro.welcome_message → 헤더 인사
// intro.categories[*] → 칩·버튼 그리드. 클릭 시 그 질문을 input에 채움
// 사용자가 짧은 인사("ㅎㅇ" 등)만 보내거나 input이 너무 모호할 때도 다시 노출

// 1) thread 생성
const { thread_id } = await fetch(`${BASE}/threads`, {
  method: "POST", headers: {"Content-Type": "application/json"}, body: "{}",
}).then(r => r.json());

// 2) FAST — SSE 스트리밍
const fastBody = {
  assistant_id: "agent",
  input: { messages: [{ type: "human", content: userQuery }] },
  stream_mode: ["values", "messages-tuple"],
  stream_subgraphs: true,
};
const fastRes = await fetch(`${BASE}/threads/${thread_id}/runs/stream`, {
  method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(fastBody),
});
// fastRes.body 를 SSE 파서로 흘려 messages-tuple 이벤트로 점진 렌더

// 2.5) thread 자동 제목 — 사이드바 가독성. 첫 답변 끝난 직후 1회.
fetch(`${BASE}/threads/${thread_id}/auto-title`, { method: "POST", headers: authHeader })
  .then(r => r.json())
  .then(({ title }) => updateSidebarTitle(thread_id, title));

// 3) 심층 보고서 — 단일 thread. 별도 thread/agent_deep/parent_thread_id/
//    [FAST_ANSWER] 합성 없음. **같은 thread 에 일반 메시지 한 턴**일 뿐.
//    사용자가 <next_steps> 보고서 항목 클릭(또는 직접 요청) → 그 텍스트가
//    그대로 human 메시지. 직전 대화가 같은 thread 에 있어 컨텍스트 합성 불필요.
const reportBody = {
  assistant_id: "agent",          // ← 동일 그래프
  input: { messages: [{ type: "human", content: reportRequestText }] },
  stream_mode: ["values", "messages-tuple"],
  stream_subgraphs: true,
};
// 같은 thread 의 또 한 번의 stream. 수 분 소요 가능 → 진척 표시 +
// 이 thread 입력은 disable(큐잉 X) + "새 대화에서 질문하기" 버튼 노출.
// fire-and-forget 아님 — 이 stream 을 그대로 따라가며 진척 표시.
const repRes = await fetch(`${BASE}/threads/${thread_id}/runs/stream`, {
  method: "POST", headers: {"Content-Type": "application/json"},
  body: JSON.stringify(reportBody),
});
// repRes.body 를 SSE 로 따라가며 "보고서 생성 중…" 진척 표시.
// 동의 turn 에서 agent 가 writer 위임 → save_report() → 영속.

// 4) 보고서 조회 — 같은 chat thread_id (별도 thread 아님)
async function poll() {
  while (true) {
    const list = await fetch(`${BASE}/threads/${thread_id}/reports`, {headers: authHeader})
      .then(r => r.json());
    const done = list.reports.filter((r: ReportMeta) => r.status === "done");
    if (done.length >= 1) return done;
    await new Promise(r => setTimeout(r, 3000));
  }
}

const reports = await poll();
// 5) 다운로드 버튼 노출
const finalReport = reports.find((r: ReportMeta) => r.kind === "final") ?? reports[0];
const downloadUrl = `${BASE}/reports/${finalReport.id}/download`;
```

---

## 에러 핸들링

| 상황 | 응답 | 프런트 처리 |
|---|---|---|
| 채팅 턴 실행 중 모델 오류 | SSE `error` 이벤트 또는 step.status=error | 사용자에게 "잠시 후 재시도" 안내 |
| Reports API 401 | `{"detail":"Authorization header required"}` | 토큰 재발급/로그인 |
| Reports API 403 | `{"detail":"Invalid token"}` | 동일 |
| Reports API 404 (없는 report_id) | `{"detail":"report not found"}` | UI에서 "보고서 만료" 처리 |
| Reports API 409 (blob 없음) | `{"detail":"report has no blob (status='running')"}` | 보고서 아직 작성 중 — 폴링 계속 |
| 도구 호출 한도 초과 | step.status=error, message에 "[한도 초과]" | 정상 흐름 — 모델이 곧 답변 작성으로 전환 |
| CORS 막힘 | 브라우저 콘솔에 CORS 에러 | `.env`의 `API_CORS_ORIGINS`에 origin 추가 + 서버 재시작 |

---

## 사전 점검 명령

프런트 띄우기 전에 백엔드 측에서 한 줄로 확인:
```bash
python scripts/check_connection.py --origin http://localhost:3000
```

모든 [ok] 마커 통과해야 프런트 호출 가능. 심층 보고서 흐름은 §8(POST /reports +
폴링) 참조.

---

## 신경로 (현행) — POST /chat · POST /reports {#신경로-poc}

> **상태(2026-07-14)**: ADR-0001 Phase 5 **컷오버 완료** — 이것이 채팅·보고서의
> **유일한 경로**다(§3 구경로는 은퇴·삭제). 상세 계약 정본(실측 payload·TS 타입·
> 체크리스트): [`frontend_chat_v2.md`](./frontend_chat_v2.md).
> 결정·검증 로그: [`spec/ADR-0001-migration-plan.md`](../spec/ADR-0001-migration-plan.md).

### POST /chat — 채팅 (SSE)

```jsonc
// 요청
{
  "message": "질문 텍스트",                    // 필수, ≤8000자
  "thread_id": "t_...",                         // 선택 — 없으면 새 thread 생성(meta 이벤트로 반환)
  "selected_law_keys": ["009514_0006001"],      // 선택 — null=미변경, []=해제 (법률그래프 ④)
  "model": "anthropic:..."                      // 선택 — CHAT_MODEL_OVERRIDE_ALLOW=1 일 때만
}
```

응답 `text/event-stream`. `event: <type>` + `data: <json>`:

| type | payload | 비고 |
|---|---|---|
| `meta` | `{thread_id, human_message_id}` | 턴 시작 — 새 thread id 수령 |
| `token` | `{text}` | 답변 토큰 델타 |
| `tool_progress` | 기존 custom 채널과 **동일 스키마** (tool/phase/message, result 시 index/title/subtitle/url) | 파서 재사용 |
| `step_lifecycle` | `{phase:"start", step}` | 기존과 동일 |
| `steps` | `{steps:[Step]}` | 이번 턴 누적 steps(citations 포함) — 도구 완료·grounding 후 발행 |
| `clarify` | `{step_id, question, options?, allow_free_text}` | **턴 종료** — 다음 POST /chat 의 message 가 답변 (interrupt/resume 아님) |
| `error` | `{message}` | 사용자향 한국어 |
| `done` | `{thread_id, message_id, text, steps, clarify_pending?}` | 턴 끝 |

- 인용 번호·`<next_steps>` 마커·쿼터 헤더(`X-Quota-*`)·429 스키마: §5·§7 과 동일.
- 같은 thread 동시 요청은 서버가 직렬화(더블클릭 안전).

### POST /reports — 심층 보고서 트리거

```jsonc
{ "thread_id": "t_...", "idempotency_key": "rpt_<uuid>", "prompt": "..." }  // prompt 선택(보고서 주제 지시)
```

| 응답 | 의미 |
|---|---|
| `202 {status:"accepted"}` | 잡 수락(백그라운드) |
| `200 {status:"running"}` | 동일 키 이미 생성 중 |
| `200 {status:"completed", report_id}` | 이미 완료 — 재생성 없음 |
| `409` | 이전 실패 — **새 idempotency_key** 로 재요청 |
| `422` | thread_id/키 형식(`^rpt_`) 오류 |
| `429` | 잡 큐 초과(REPORT_JOB_MAX_PENDING) |

완료 시: 이메일 DOCX 첨부(설정 시) + reports 레코드(`summary` = 본문 `## 개요`).
전문·메타는 기존 `GET /threads/{tid}/reports`·`GET /reports/{rid}` 그대로.

> **⚠️ 계약 변경(2026-07-25) — 채팅↔보고서 완전 분리**
> 구 계약은 완료 시 `## 개요`를 thread 에 `kind:"report_overview"` AI 메시지로
> append 했으나 **더 이상 하지 않는다**. 대화록에 보고서 흔적이 남지 않는다.
> - 진행 step(`report_*`)에는 `source_message_id`/`turn_idx` 가 **없다** —
>   클라이언트는 채팅 턴 step 목록에서 `report_*` 를 배제해야 한다.
> - 완료 인지는 이 폴링 엔드포인트로. FE 는 토스트·브라우저 알림·사이드바 갱신.
> - 근거가 `REPORT_MIN_CITATIONS`(기본 6) 미달이면 1회 재수집 후에도 부족할 때
>   `status:"failed"` + 사유(`error`) 로 마감된다(얇은 보고서 미배달).
> 상세: [`frontend_chat_v2.md`](./frontend_chat_v2.md) §4.

### GET /reports/runs/{idempotency_key} — 잡 상태 폴링

`{status: running|completed|failed, report_id, thread_id, error}` (소유자만).

### 조회·관리 — 사이드바·리로드·제목 (구 langgraph /threads/* 대체)

| 라우트 | 대체 대상(은퇴) | 응답 |
|---|---|---|
| `GET /chat/threads` | langgraph threads 목록 | `{threads:[{thread_id,title,created_at,updated_at}]}` (본인 것만) |
| `GET /chat/{tid}/state` | `GET /threads/{tid}/state` | `{thread_id,title,messages,steps,selected_law_keys}` |
| `PATCH /chat/{tid}` `{title}` | threads.update(metadata.title) | `{ok,thread_id,title}` (제목 1~60자) |
| `DELETE /chat/{tid}` | `DELETE /threads/{tid}` | `{ok,thread_id}` (메시지·steps 포함 삭제) |
| `POST /chat/{tid}/auto-title` | `POST /threads/{tid}/auto-title` | `{thread_id,title}` (shape 동일, loopback 불요) |

- 소유자 아닌 thread 404(비노출). 조회 GET 은 쿼터 초과여도 허용.

> **프런트 전환 가이드(실측 payload 예시·TS 타입·체크리스트)**:
> [`frontend_chat_v2.md`](./frontend_chat_v2.md)


---

## 부록 — 2026-07-15~16 신규 엔드포인트

| 메서드·경로 | 설명 | 인증 |
|---|---|---|
| `GET /chat/search?q=` | 대화 **본문** 검색(제목 아님) — q 2자↑, 소유 thread 만 | 필요 |
| `POST /chat/{tid}/pin` `{pinned}` | 대화 상단 고정/해제 | 필요(소유자) |
| `POST /answers/export` `{content, citations?, format?}` | 답변 Word(docx) 내보내기 — pandoc, 불가 시 md 폴백 | 필요 |
| `POST /bookmarks` `{citation, note?, folder?, thread_id?}` | 근거 저장(멱등 — 같은 citation.id 무시) | 필요 |
| `GET /bookmarks` | 내 근거 라이브러리(최신순) | 필요 |
| `PATCH /bookmarks/{id}` `{folder}` | 폴더 지정/해제 | 필요(본인) |
| `DELETE /bookmarks/{id}` · `/bookmarks/by-citation/{cid}` | 삭제 / citation 토글 해제 | 필요(본인) |
| `GET /bookmarks/amendments` | 저장 근거의 개정 감지 — `kind`: repealed(폐지)·pending(개정예정, law.go.kr enrich)·amended(시행일 변경) | 필요 |
| `POST /files/extract` (multipart `file`) | **파일 업로드 v1(2026-08-05)** — PDF·DOCX·HWPX·TXT 텍스트 추출(원본·추출본 미저장, 상태는 FE 보관). 413/415/422 한국어 detail. 구형 HWP·스캔 PDF 거절. 계약: frontend_chat_v2.md §1-2 | 필요 |

**기존 엔드포인트 확장**:
- `POST /chat` body에 `style`("expert"\|"simple") — 답변 설명 수준(시스템 프롬프트 분기).
- `POST /chat` body에 `attachments`(`[{name,text}]`, 2026-08-05) — /files/extract 추출 텍스트. 개수 ≤3·파일당 ≤120,000자·본문+첨부 ≤150,000자(2026-09-14 상향, 초과 422). 서버가 `<attachment name="...">` 블록으로 합성 후 PII 게이트 통과.
- `POST /reports` body에 `purpose`("license_strategy"\|"reg_summary"\|"change_response") — 보고서 목적 템플릿.
- `GET /chat/threads` 응답에 `pinned` 필드.
- 검색 citation `status` 가 law.go.kr 개정상태(`amend_status`, ETL enrich) 우선 반영.

**관리자(2026-07-16 추가)**: `POST /admin/users/{id}/soft-delete`(비활성화) ·
`POST /admin/notify`(공지 이메일) · `POST /admin/feedback/digest`(피드백 취합 발송).

**POST /admin/notify — 공지 이메일**(계약 확정 2026-08-02)
```jsonc
// 요청
{ "subject": "…", "body": "…",          // 필수(body 는 평문)
  "body_html": "…",                     // 선택 — 직접 준 HTML 이 템플릿보다 우선
  "template": "branded",                // branded(기본, 서비스 테마 HTML) | plain
  "cta_url": "https://…",               // 선택 — 본문 아래 버튼(branded 만)
  "cta_label": "시작하기",
  "to": "all",                          // all | admins | whitelisted | beta_testers | [주소…]
  "send_at": "2026-08-05T00:00:00Z",    // 있으면 즉시 발송 대신 **예약**
  "dry_run": true,                      // true = 발송 없이 수신자만 확인
  "preview": true }                     // true = 렌더된 HTML 만 반환(발송·예약 안 함)
// 응답
{ "ok": true, "requested": 12, "sent": 12,
  "failed": [], "recipients": ["…"],
  "smtp_configured": true }             // ⚠️ false 면 sent 는 stub 로그 수(실발송 아님)
```
- `whitelisted` = 화이트리스트로 허용된 **가입 회원** · `beta_testers` = 화이트리스트
  항목 전체(미가입 초대자 포함, `@도메인` 항목은 개별 주소가 없어 제외).
- `reply_to`(또는 env `NOTICE_REPLY_TO`) — From 은 발송 도메인(noreply@…)이라
  **없으면 답장이 아무에게도 가지 않는다**. "메일로 문의" 안내가 있는 공지엔 필수.
- 본문 표기(`template:"branded"`): `## 소제목`(구분선 있는 섹션 제목) · `- 항목`(불릿) ·
  맨 URL 자동 링크. 평문 파트는 표식을 걷어낸 버전(`[ 소제목 ]`·`· 항목`)으로 나간다.
- 비활성(`deleted_at`) 회원 제외 · 대소문자 무시 중복 제거 · 개별 발송(주소 상호 비노출).
- 발송 전 `dry_run` 으로 명단과 `smtp_configured` 를 먼저 확인할 것.
- 구현: `src/notices.py`(수신자 해석·템플릿·예약 큐) — 라우트와 스케줄러가 공유.

**예약 발송**(2026-08-02)
| 라우트 | 용도 |
|---|---|
| `POST /admin/notify` + `send_at` | 예약 등록 → `{scheduled:true, notice:{id,…}}` |
| `GET /admin/notify/scheduled` | 예약·발송 이력(예정 시각 오름차순). `status`: pending\|sending\|sent\|skipped |
| `DELETE /admin/notify/scheduled/{id}` | 미발송 예약 취소(이미 발송 시 404) |

- 저장: `app_settings` KV 의 `admin.scheduled_notices`(JSON 배열). 발송 루프는
  `api._scheduled_notice_loop`(`NOTICE_SCHEDULER_INTERVAL_S`, 기본 60초).
- **워커 1개 전제**(CLAUDE.md §7) — 여러 프로세스면 같은 공지가 중복 발송된다.
- 발송 직전 `sending` 으로 못박고 저장 → 크래시해도 재발송 없음(중복이 미발송보다 나쁘다).
- 프리셋(`all` 등)은 **발송 시점에** 다시 해석 → 예약 뒤 추가된 테스터도 받는다.
  명단을 고정하려면 `to` 에 주소 배열로 넘길 것.

**관리자 기능별 권한**(2026-09-22) — 정본 `src/admin_perms.py`
- 루트 관리자(`ADMIN_EMAILS` ∪ 루트) = 전 권한. DB 관리자(`users.is_admin`)는 `users.admin_perms`
  (콤마 키, NULL = 전 권한 — 도입 전 관리자 하위호환)에 켜진 기능만.
- 키: `stats`·`threads`·`reports`·`users`·`beta`·`feedback`·`pii`·`mail`(메일 발신)·
  `announcements`(업데이트 등록)·`settings`.
- `require_admin` 이 라우트 템플릿으로 `_ROUTE_RULES` 를 찾아 검사 → 권한 없으면 403
  `"'메일 발신' 권한이 없습니다 — …"`. 매핑 없는 `/admin/*` 는 루트 전용(fail-closed),
  `tests/test_admin_perms.py` 가 등록된 전 라우트의 매핑을 검사.
- `GET /admin/me` → `{email, is_root, perms:[키], catalog:[{key,label,desc}]}` (관리자면 누구나).
- `PATCH /admin/users/{id}` 의 `is_admin`·`admin_perms`(키 배열 | null) 는 **루트만**(그 외 403).
  새로 관리자로 지정하면 권한 빈 목록에서 시작. `/admin/users` 행에 `is_root_admin`·
  `admin_perms_list`(적용 권한)·`admin_perms_all`.

**뉴스레터**(2026-09-22, 권한 `mail`) — 구현 `src/newsletters.py` + `src/routes/admin_newsletters.py`
| 라우트 | 용도 |
|---|---|
| `GET /admin/newsletters` | 목록(메타: subject·marketing·sent_count·send_runs·last_sent_at…) |
| `POST /admin/newsletters` | 작성 `{subject, body_html?, body_text?, marketing?, reply_to?, source_filename?}` — 둘 중 하나 필수 |
| `GET /admin/newsletters/{id}` | 본문 + `sends`(발송 이력, 최신 앞) |
| `PUT /admin/newsletters/{id}` | 수정(준 키만) |
| `DELETE /admin/newsletters/{id}` | 삭제 — 본 발송 이력 있으면 409(기록 보존) |
| `POST /admin/newsletters/preview` | 저장 없이 렌더 `{subject, html, text}` |
| `GET /admin/newsletters/recipients?marketing=&newsletter_id=` | 후보(회원 + 미가입 베타 초대자) + 자격 `eligible`/`reason` + `received_at` |
| `POST /admin/newsletters/{id}/send` | `{emails:[…]}` 발송 · `{test:true}` 요청자 본인 1통(`[테스트]`, 수신 기록 제외) |

- 자격(서버가 발송 시 다시 판정): 탈퇴 → `deleted` · 안내 메일 수신거부 → `notice_optout` ·
  광고성(`marketing:true`)인데 마케팅 미동의(미가입 초대자 포함) → `no_marketing_consent` ·
  후보 밖 주소 → `unknown`. 걸린 주소는 발송하지 않고 회차 `skipped` 에 사유와 함께 남긴다.
- 광고성은 제목 앞 `(광고)` 자동 부착(정보통신망법 §50④).
- HTML 이 있으면 그대로(평문 파트는 `body_text` 또는 HTML 자동 추출), 없으면 평문으로 브랜드 템플릿.
- 저장: `app_settings` KV — `newsletters.index`(메타) · `newsletter:{id}`(본문) ·
  `newsletter_sends:{id}`(회차별 `recipients:[{email, ok}]`·`skipped`·`sent`·`failed`·`by`·`at`).

### 9-1) 실사용/테스트 데이터 분리 (2026-08-03)

베타 오픈 **이전** 데이터는 개발·e2e 테스트가 만든 것이다. 섞어 집계하면
"LLM 72회" 같은 숫자가 이용자 지표로 읽힌다(초대 전날 72회는 전부 내부 테스트).

| | |
|---|---|
| 경계 | `2026-08-03T00:00+09:00` (env `SERVICE_LAUNCH_AT` 로 조정) |
| 조회 | `GET /admin/data-scope` → `{launch_at, default_scope}` |
| 파라미터 | `scope=real`(기본, 오픈 이후만) \| `scope=all`(테스트 포함) |

`scope` 를 받는 라우트: `/admin/stats` · `/admin/questions` ·
`/admin/stats/search-laws` · `/admin/stats/claim-audit` · `/admin/threads` ·
`/admin/users`(이쪽만 기본 `all` — 계정 관리는 테스트 계정도 보여야 한다).

- `real` 은 기간 계산 결과와 경계 중 **늦은 쪽**을 쓴다 — `days=30` 을 줘도
  테스트 구간으로 거슬러 올라가지 않는다.
- `/admin/users` 행에는 계정 구분이 붙는다(2026-09-21): `account_class`(`staff`\|`test`\|`user`,
  유효값) · `account_class_label` · `account_class_source`(`manual`\|`auto:admin`\|`auto:pre_launch`\|`auto:beta_invited`\|`auto`) ·
  `account_class_manual` · `is_internal`. `is_test_account` 는 하위호환(= `is_internal`).
- **`scope=real` 에서 빠지는 것** = 내부 계정(운영진·테스트) + 익명 + 내부 스레드(e2e·벤치·야간 회귀 접두).
  계정 판정 정본은 `src/account_class.py` — 관리자 라벨(`PATCH /admin/users/{id} {account_class}`)이
  자동 규칙(관리자 → 운영진, 오픈 전 가입 + 베타 초대 명단에 없음 → 테스트)을 덮는다. 2026-09-21 전에는 관리자만 뺐고
  (오픈 전 가입·팀원 개인 계정이 실사용으로 샘), 검수 큐만 따로 오픈 전 가입을 뺐다.

---

## 고객사 규제 모니터링 — `/monitor/*` (2026-10-01 신규)

로펌이 고객사별로 관심 조문을 모아 두고(= `bookmarks.folder`), 그 폴더의 **폐지·개정예정·
시행일 변경**을 주기적으로 감지해 지정 수신자에게 리포트를 보낸다. 전부 user 스코프.

판정은 `GET /bookmarks/amendments` 와 **같은 로직**(`src/amendments.py:detect`)을 쓴다 —
개인 조회와 고객사 리포트가 어긋나면 안 된다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/monitor/targets` | 내 설정 목록 + `watched`(폴더별 관찰 건수) + `next_run_at`, 그리고 선택 가능한 `folders` |
| `POST` | `/monitor/targets` | 생성. 같은 `folder` 재등록은 **갱신(멱등)**. 201 |
| `PATCH` | `/monitor/targets/{id}` | 부분 수정 |
| `DELETE` | `/monitor/targets/{id}` | 삭제. 204 |
| `GET` | `/monitor/targets/{id}/preview` | **발송하지 않고** 지금 시점 리포트 미리보기(영업 시연·검수) |
| `POST` | `/monitor/targets/{id}/send` | 수동 발송. body `{ to?: [email], force?: bool }` |

**body(생성·수정)**

| 필드 | 필수 | 설명 |
|---|---|---|
| `folder` | ✅ | 고객사 = 북마크 폴더명 |
| `recipients` | ✅ | 쉼표/줄바꿈 구분 문자열 또는 배열. 유효 이메일 1개 이상 |
| `label` | | 고객사 표시명(없으면 `folder`) |
| `cadence` | | `weekly`(기본) \| `monthly` |
| `send_weekday` | | 0=월 … 6=일 (weekly 전용, 기본 0) |
| `send_hour` | | 0~23 KST (기본 9) |
| `enabled` | | 기본 true |

**동작 규칙**

- **변경 0건이면 보내지 않는다**(기본). `MONITOR_REPORT_SEND_ON_NO_CHANGE=1` 로 변경.
  "변화 없음" 메일이 쌓이면 리포트를 안 읽게 된다.
- `last_sent_at` 은 **한 곳이라도 발송에 성공했을 때만** 갱신 — 전부 실패면 다음 점검에 재시도.
- 수동 발송(`/send`)은 `last_sent_at` 을 건드리지 않는다 — 정기 발송은 예정대로 나간다.
- 주기 루프는 `MONITOR_REPORT_CHECK_INTERVAL_S`(기본 900초, 0=끔). 부팅 3분 뒤 첫 점검.
- 판정과 기록은 **같은 시각**으로 묶인다(`run_due`) — 주기 경계에서 중복 발송 방지.
