# frontend v2 — 신경로(`/chat`·`/reports`) 전환 가이드 (ADR-0001 Phase 4)

medi-front 가 `@langchain/langgraph-sdk` 를 버리고 자체 SSE 로 갈아타기 위한
전체 계약. **이벤트 payload 는 전부 2026-07-13 실측 캡처** — 스키마 추정 아님.
상태: 백엔드 준비 완료(병행 서빙 중). 계획: [`spec/ADR-0001-migration-plan.md`](../spec/ADR-0001-migration-plan.md).

## 0. 전환 요약 — 무엇이 어디로 가나

| 하던 일 | 구경로 (langgraph SDK) | 신경로 |
|---|---|---|
| thread 생성 | `POST /threads` | 불요 — `POST /chat` 에 thread_id 생략 시 자동 생성(`meta` 이벤트로 수령) |
| 채팅 스트리밍 | `POST /threads/{tid}/runs/stream` (`values`+`messages-tuple`+custom) | **`POST /chat`** (SSE, 이벤트 8종(+조건부 pii_notice) — §2) |
| 대화 리로드 | `GET /threads/{tid}/state` → `values.messages/steps` | **`GET /chat/{tid}/state`** (§3) |
| 사이드바 목록 | langgraph threads 검색 + `metadata.title` | **`GET /chat/threads`** (§3) |
| 자동 제목 | `POST /threads/{tid}/auto-title` | **`POST /chat/{tid}/auto-title`** (응답 shape 동일) |
| 보고서 트리거 | 같은 thread 에 `assistant_id:"agent_report"` run | **`POST /reports`** + `GET /reports/runs/{idem}` 폴링 (§4) |
| run 취소 | `POST /threads/{tid}/runs/{rid}/cancel` | **SSE 연결 abort** — 서버가 턴 워커를 취소함(별도 API 없음) |
| clarify(HITL) | `interrupt` payload + `Command(resume=...)` | **`clarify` 이벤트 + 턴 종료** — 사용자의 답을 *다음 `POST /chat` message* 로 전송 (§2-4) |
| 인용·steps·next_steps·쿼터 | Step/Citation dict, `<next_steps>` 마커, `X-Quota-*` | **전부 동일** — 파서 무변경 재사용 |

바뀌지 않는 것: `<next_steps>` 파서(`lib/parse/nextSteps.ts`), citation 번호
규칙(thread 전역 단조·id dedup), Step/Citation 필드, 쿼터 헤더·429 스키마,
보고서 목록/다운로드(`GET /threads/{tid}/reports`·`GET /reports/{rid}` 등 커스텀 REST 전부).

## 1. 요청 — POST /chat

```ts
type ChatRequest = {
  message: string;                    // 필수, ≤32,000자 (2026-08-04 상향, 구 8,000)
  thread_id?: string;                 // 생략 → 새 thread (meta 이벤트로 수령)
  selected_law_keys?: string[] | null; // null/생략=미변경, []=해제 (법률그래프 ④)
  // 파일 업로드 v1 (2026-08-05) — §1-2. /files/extract 가 돌려준 추출 텍스트.
  attachments?: { name: string; text: string }[];
  // 스킬 명시 진입 (2026-08-21) — "irb_drb": IRB/DRB 버튼/카드에서 전송.
  // 백엔드 키워드 감지(프리게이트)가 놓쳐도 기관 심의 지침을 부착·강제한다.
  // 미지원 값·미설정은 무시(기존 키워드 감지만 동작). 스킬 화이트리스트
  // (SKILL_WHITELIST_EMAILS)는 이 필드로 우회되지 않는다.
  skill_hint?: "irb_drb" | null;
};
```

`Authorization: Bearer <NextAuth JWT>` — 기존과 동일(AuthMiddleware).
응답 헤더에 `X-Quota-Daily-Used` 등 4종(진입 시점 값).

### 1-1. 입력 길이 — 사용자가 문서를 붙여넣는다 (2026-08-04)

상한이 **8,000 → 32,000자**로 올랐다. 사용자가 규제 문서를 통째로 붙여넣는
사용이 실제로 확인됐고(리포트: "텍스트가 길다며 에러"), 서버측 PII 처리량이
해소돼 받을 수 있게 됐다.

초과 시 **422** + `{"detail": "<한국어 안내>"}`:

```json
{"detail": "입력이 너무 깁니다(45,120자). 한 번에 32,000자까지 보낼 수 있습니다. 문서는 핵심 부분만 나눠서 올려주세요."}
```

`detail` 은 **문자열**이다(Pydantic 검증 오류 배열이 아님) — 그대로 노출해도 된다.

> **FE 권장**: 전송 전 글자 수 카운터 + 초과 시 전송 차단. 지금은 클라이언트
> 가드가 없어 큰 붙여넣기가 서버까지 갔다가 튕긴다. 상한은 서버 노브
> (`CHAT_MAX_INPUT_CHARS`)라 하드코딩보다 초과 시 422 를 그대로 보여주는 편이 안전하다.

**소유권**: thread 는 최초 생성자에게 귀속 — 남의 thread_id 로 POST /chat·
/reports·조회 시 전부 **404**(존재 비노출, 구경로 `@auth.on.threads` 스코프와
동일 의미론). 잘못된/만료 JWT 는 401.

### 1-2. 파일 첨부 (파일 업로드 v1, 2026-08-05)

흐름: `POST /files/extract` (multipart, field `file`) → 추출 텍스트 수령 →
전송 시 `attachments` 로 되보냄. **서버는 업로드~전송 사이 상태를 들지 않는다**
(원본·추출본 모두 미저장 — 대화에 들어간 텍스트만 PII 마스킹돼 저장).

```ts
// POST /files/extract → 200
type ExtractResp = {
  name: string;            // 파일명 (≤200자로 잘림)
  kind: "pdf" | "docx" | "hwpx" | "txt";
  chars: number;
  truncated: boolean;      // FILE_MAX_EXTRACT_CHARS(기본 120,000자 — 계획서 50쪽 안팎) 초과로 잘렸는가
  text: string;
};
// 오류 — detail 은 사용자에게 그대로 보여줄 한국어 문자열:
//   413 크기 초과(기본 15MB) · 415 미지원 형식(구형 HWP/DOC 포함) ·
//   422 텍스트 없음(스캔 PDF)
```

- 지원: PDF(텍스트 레이어)·DOCX·HWPX·TXT/MD/CSV. **구형 HWP·DOC·스캔 PDF 는
  거절**(silent truncation 금지 — 잘린 문서를 전체라 믿게 하지 않는다).
- `/chat` 검증: 첨부 개수 ≤ `CHAT_MAX_ATTACHMENTS`(3) · 본문+첨부 합산 ≤
  `CHAT_MAX_TOTAL_INPUT_CHARS`(150,000자, 2026-09-14 상향 — 종전 60,000).
  초과 시 422 + 한국어 detail.
- 서버는 message 뒤에 `\n\n<attachment name="...">\n<텍스트>\n</attachment>`
  블록을 이어붙여 저장·처리한다 — **FE 는 human 메시지의 이 태그를 접힌 칩으로
  렌더**(UserMessage). 형식 변경 시 양쪽 동기 필수.

## 2. SSE 이벤트 — 실측 payload

`event: <type>` + `data: <json>` 프레임. 발생 순서(전형적 규제 질문 턴):
`meta` → `step_lifecycle(start)` → `tool_progress`×N → `steps` → `token`×N
→ `steps`(grounding 후 verified 갱신) → `done`.

### 2-1. `meta` — 턴 시작 (thread_id 수령)

```json
{"type": "meta", "thread_id": "t_8a05270e812a...", "human_message_id": "msg_330d54962ede"}
```

### 2-1b. `pii_notice` — 입력 개인정보 자동 제거 고지 (선택 발생)

입력에 개인정보(이름·주소·전화·주민번호 등)가 있어 `[이름]`/`[주소]` 등으로
마스킹된 턴에만 `meta` 직후 1회 발생. 프론트는 **가벼운 배지/토스트**로 고지하고,
답변은 정상 진행(특정 개인이 아닌 일반 질문으로 답변). categories 는 마스킹된 종류.

```json
{"type": "pii_notice", "thread_id": "t_8a05...", "human_message_id": "msg_330d...", "categories": ["이름", "phone"], "masked_text": "임상시험/영상분석 [이름] 프로토콜은 어떤 것들이 들어있어야 해?"}
```

**오탐 신고 UX (2026-08-13)**: `masked_text` = 서버에 저장·표시되는 마스킹본
전문. 프론트는 방금 보낸 **원문(클라 메모리)** 과 대조해 어떤 단어가
`[이름]`/`[주소]` 로 치환됐는지 짚고, 경고 토스트에 노출한다 —
"'통합운영'이 개인정보로 감지되어 제외됐어요. 오류인가요? [오류 신고]".
사용자가 [오류 신고]를 누르면:

```
POST /feedback/pii
body: { thread_id, term: "통합운영",           // 치환된 원래 단어(원문에서 추출)
        placeholder: "[이름]",                  // 어떤 자리표시자였나 (optional)
        message_id: human_message_id,           // optional
        comment: "" }                           // optional ≤200자
→ 200 { ok, term, status: "reported", unmasked: true, report_count }
→ 422 주민번호·전화번호 등 구조적 개인정보 형식(신고 자체가 거부됨)
```

**선보고 후조치**: 신고 즉시 그 단어는 마스킹 제외된다(≤10s, 다음 질문부터
검색에 그대로 들어감) — 토스트 문구는 "신고했어요. 다음 질문부터 바로
반영됩니다" 톤으로. `unmasked: false` 로 오면 이미 관리자가 '진짜 개인정보
(correct)'로 라벨한 단어 — "검토 결과 개인정보로 확인된 단어예요"로 분기.

서버는 신고와 무관하게 **마스킹된 모든 단어를 자동 수집**해 관리자가
correct(정탐)/wrong(오탐) 라벨링한다 — admin: `GET/POST/DELETE /admin/pii-terms`.

### 2-2. `token` — 답변 텍스트 델타

```json
{"type": "token", "text": "네, **디지털 치료기기"}
```

본문 누적 → `<next_steps>` 마커는 기존 파서 그대로(닫힘 태그까지 buffer).

### 2-3. `tool_progress` / `step_lifecycle` — 기존 custom 채널과 동일

```json
{"type": "step_lifecycle", "phase": "start", "step": {"id": "s_0580344fb6", "ts": 1783922528758, "label": "법령 벡터 검색: 의료 규제 개요", "status": "running", "tool_name": "qdrant_search", "input_preview": "의료 규제 개요", "source_message_id": "msg_330d54962ede", "turn_idx": 0}}
```
```json
{"type": "tool_progress", "tool": "qdrant_search", "phase": "started", "message": "법령 벡터 검색 시작: 의료 규제 개요"}
{"type": "tool_progress", "tool": "qdrant_search", "phase": "result", "index": 1, "title": "규제자유특구 및 지역특화발전특구에 관한 규제특례법", "subtitle": "제42조", "url": "", "message": "[1] 규제자유특구... — 제42조"}
{"type": "tool_progress", "tool": "qdrant_search", "phase": "complete", "message": "8건 매칭"}
```

phase 값: `started`·`searching`·`busy`(혼잡 안내)·`result`·`complete`.
(보고서 writer 는 `queued`·`writing` 도 사용 — §4 폴링 화면에는 불필요.)

### 2-4. `clarify` — **턴 종료형 HITL** (구 interrupt 대체, 동작 변경!)

```json
{"type": "clarify", "step_id": "s_ab12cd34ef", "question": "어떤 제품군인가요?", "options": ["의료기기", "의약품"], "allow_free_text": true}
```

구경로와 다른 점: `Command(resume=...)` 재개가 **없다**. 이 이벤트 직후
`done`(`clarify_pending: true`) 이 오고 턴이 끝난다. 사용자가 고른/입력한
답을 **그냥 다음 `POST /chat` 의 `message`** 로 보내면 된다(같은 thread_id).

### 2-5. `steps` — 이번 턴 누적 steps (citations 포함)

```json
{"type": "steps", "steps": [{"id": "s_0580344fb6", "ts": 1783922528758, "label": "법령 벡터 검색: ...", "status": "done", "tool_name": "qdrant_search", "input_preview": "...", "source_message_id": "msg_330d54962ede", "turn_idx": 0, "ended_at": 1783922536018, "output_preview": "1건 매칭", "citations": [{"id": "cite_doc_009641_0042001", "number": 1, "source_kind": "doc", "title": "규제자유특구... 제42조", "publisher": "중소벤처기업부", "date": "2027-05-13", "doc_id": "009641", "article": "제42조", "snippet": "① 의료 관련...", "status": "active", "verified": false, "url": "..."}]}]}
```

- 도구 완료 시마다 + **답변 후 grounding 검증 후 한 번 더**(같은 step id,
  citations[].verified 갱신) 발행 — id 기준 merge(구경로 reducer 와 동일).
- Step/Citation 필드 정의: [`API.md §5`](./API.md) 그대로.

### 2-6. `error` / `done`

**PII 검사 미완료로 인한 차단(2026-08-04)** — 이름·주소는 NER 이 유일한 방어선이라,
검사가 입력 전 구간을 덮지 못하면 답변을 만들지 않고 **차단**한다(fail-open 금지).
`message` 에 사유와 행동 안내가 담겨 오므로 그대로 노출할 것:

```json
{"type": "error", "message": "개인정보 검사를 끝내지 못했습니다. 잠시 후 다시 시도하거나 입력을 더 짧게 나눠서 보내주세요."}
```

일시적 과부하에서 발생하므로 **재시도 버튼**을 붙이면 대부분 해결된다.

```json
{"type": "error", "message": "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}
{"type": "done", "thread_id": "t_...", "message_id": "msg_...", "text": "<최종 답변 전문>", "steps": [...], "clarify_pending": true}
```

`done.text` = token 누적과 동일(최종 확정본으로 교체 렌더 가능). `error` 후에도
`done` 없이 스트림이 닫힐 수 있음 — 연결 종료를 턴 종료로 처리.

### TS 타입 (복붙용)

```ts
type ChatEvent =
  | { type: "meta"; thread_id: string; human_message_id: string }
  | { type: "pii_notice"; thread_id: string; human_message_id: string; categories: string[] }
  | { type: "token"; text: string }
  | { type: "tool_progress"; tool: string; phase: "started"|"searching"|"busy"|"result"|"complete"|"queued"|"writing";
      message: string; index?: number; title?: string; subtitle?: string; url?: string }
  | { type: "step_lifecycle"; phase: "start"; step: Step }
  | { type: "steps"; steps: Step[] }
  | { type: "clarify"; step_id: string; question: string; options?: string[]; allow_free_text: boolean }
  | { type: "error"; message: string }
  | { type: "skill_verdict"; thread_id: string; message_id: string | null;
      verdict: object; rulepack_version: string }   // §2-4 (스킬 판정 턴에만)
  | { type: "document_update"; report_id: string;               // §2-7 (서류 초안 스레드만)
      filled: { field: string; value: string }[]; remaining: string[] }
  | { type: "done"; thread_id: string; message_id: string | null; text: string;
      steps: Step[]; clarify_pending?: boolean };
// Step·Citation 은 기존 타입 그대로 (API.md §5 / src/schemas.py 정합)
```

### 2-7. `document_update` — 서류 초안 채팅 기입 (2026-08-24, done 뒤 trailing)

`purpose: "document_draft"` 보고서(서류 초안)가 완료된 스레드에서만 발생.
매 턴 done 뒤, 발화에 **명시된** 값이 초안의 `[확인 필요: 항목명]` 미기입
항목과 매칭되면 서버가 저장(`filled_values`) 후 이 이벤트를 1회 흘린다.

```json
{"type": "document_update", "report_id": "…",
 "filled": [{"field": "연구 기간", "value": "2026.10~2027.09"}],
 "remaining": ["연구책임자"]}
```

FE 는 우측 패널 문서 모드(DocumentPanel)에 병합·하이라이트. 매칭 없으면
이벤트 자체가 안 온다. 관련 REST:

- **`POST /documents/from-form`** — `{thread_id, article_key, title?}` →
  `{report_id, title, fields, filled, remaining}`. 사용자가 인용/별표 모달에서
  고른 별표·서식으로 **즉시**(0.1~0.6s, LLM 0회) 기입 문서를 만든다.
  [이 서식으로 작성] 버튼의 경로 — **보고서 트리거가 아니다**(2026-08-27).
  404 = 그 서식의 본문·원본 링크를 못 찾음. FE 는 응답을 `state.document` 에
  얹고 `rev` 를 올려 패널을 연다.
- `GET /documents/state?thread_id=` — 스레드의 최신 초안 상태
  `{report_id|null, title, fields, filled, remaining}` (스레드 로드 시 복원용)
- **`DELETE /reports/{report_id}`** — 보고서/서류 삭제(2026-08-27, 소유자만).
  blob 포함 확정 삭제, 복구 불가. 200 `{ok, report_id}`.
- **`POST /documents/{report_id}/chat`** — 작성 도우미 챗(전용 모달,
  2026-08-27). `{message, history?}` → `{reply, filled, values, remaining,
  corrected}`. 메시지는 채팅 스레드 밖·무저장·**온프레미스 모델 직행**(저장
  대화는 PII 마스킹본이라 개인정보 칸을 못 채우는 한계를 푸는 창구).
  503 = 로컬 모델 미가용 — FE 는 직접 입력으로 안내.
- `POST /documents/{report_id}/fill` — `{field, hint?, value?}`.
  `value` 있으면 직접 저장, 없으면 ✨ AI 작성(근거 부족 시 미기입),
  `field:"*"` 일괄. 응답 `{filled, values, remaining}`.
- `GET /reports/{id}/download?fill=0` — 마커 유지 원본(패널 렌더용).
  기본(`fill=1`)은 기입값 치환본(md·docx 다운로드).

### 2-4. 기관 내부 지침 스킬 (IRB/DRB — 2026-08-10, 조건부 기능)

`SKILL_BUNDLE_DIR` 설정 + 화이트리스트 사용자 + IRB/DRB 질의 스레드에서만
동작한다. 그 외에는 아래 이벤트·마커가 **절대 나오지 않는다**(기존과 동일).

- **step**: `tool_name` 에 `"load_skill"` / `"read_skill_reference"` 가 추가로
  올 수 있다. 기존 Step shape 그대로 — 라벨("내부 지침 확인: …")로 렌더하면 됨.
- **`<verdict>…</verdict>` 마커**: 판정 턴의 token 스트림 말미에 구조화 판정
  JSON 블록이 이 마커로 감싸여 온다. `<next_steps>` 와 같은 방식으로 **본문에서
  숨긴다**. `done.text` 에는 이미 제거되어 있다(토큰 누적과 달라지는 유일한 경우).
- **`skill_verdict` 이벤트**: done 직전 1회 — 판정 요약 배지/패널 렌더용.
  `verdict.irb.verdict` ∈ NOT_SUBJECT|EXEMPT|EXPEDITED|FULL_BOARD|HOLD (drb 동일).
  - (2026-09-15) 백엔드 가드가 판정을 강등한 턴은 `verdict.guard = { rule, original_verdict }`
    가 붙는다(예: `exempt_identifiable_contradiction`, EXEMPT→HOLD). 이때 `done.text` 는
    토큰 누적과 달라지는 **두 번째 경우** — 본문 말미(`<next_steps>` 앞)에 "판정 보류
    안내(자동 검토)" 문단이 추가된다. FE 는 done.text 로 교체 렌더하면 된다(이미 그렇게
    동작). 저장본에도 같은 문단이 반영되므로 새로고침 후 본문이 동일하다.

## 3. 조회 — 사이드바·리로드·제목

```
GET /chat/threads?limit=50
→ {"threads": [{"thread_id": "t_...", "title": "광고 사전심의", "created_at": "...", "updated_at": "..."}]}

GET /chat/{thread_id}/state          // 대화 리로드 (구 /threads/{tid}/state 대체)
→ {"thread_id", "title",
   "messages": [{"id", "type": "human"|"ai"|"tool", "content": "<텍스트>", "tool_calls?": ["qdrant_search"]}],
   "steps": [Step],                  // citations 포함 — 인용 패널 복원 재료
   "selected_law_keys": [...],
   "report_running": false}          // 이 thread 에 심층보고서 작성 중이면 true
                                     //   → 진행 배지 유지(채팅은 계속 가능=비차단)

POST /chat/{thread_id}/auto-title    // 응답 {thread_id, title} — 구경로와 동일 shape
```

- `messages` 는 전체 원장(체크포인트 values.messages 대응) — human/ai 렌더
  필터는 기존 FE 로직 그대로. `type:"tool"`·빈 content ai(도구 호출 턴)는 숨김.
- 소유자 아닌 thread 는 404(존재 비노출). 쿼터 초과여도 조회는 허용.

## 4. 보고서 — POST /reports + 폴링

> **재설계(2026-07-24) — 보고서는 채팅 턴 밖의 별도 트랙.**
> ① 트리거 prompt 는 대화록에 human 메시지로 **끼지 않는다**(서버 run 레코드에
>   저장 — supervisor 가 "답할 질문"으로 오독하던 오염 제거).
> ② FE 는 report 턴을 만들지 않는다 — 진행 표시는 `reportRunning`(트리거·
>   `GET /reports/runs/active` 복원) 단일 진실원.
> ③ 완료 개요는 서버가 `kind:"report_overview"`(+`report_id`) 태그의 단독 AI
>   메시지로 append — `GET /chat/{tid}/state` 응답 messages[].kind 로 노출,
>   FE 는 전용 완료 카드 턴으로 렌더(일반 답변에 흡수 금지).
> ④ 스레드당 동시 보고서 1개 — 진행 중 다른 키 트리거는 409 `report_in_progress`.

```
POST /reports {"thread_id": "...", "idempotency_key": "rpt_<uuid>"}   // 키 생성은 기존과 동일
  202 accepted | 200 running|completed | 409 실패이력(새 키로)·report_in_progress | 422 | 429 큐 초과

GET /reports/runs/active?thread_id=...   // 새로고침 복원용
  {"status": "running", "idempotency_key", "started_at", "queue_ahead"?} | {"status": "none"}

// 422 진입 허들 — 빈/인사만 오간 thread 로 보고서 생성 차단. detail 을 그대로 노출:
//   ① 실질 주제 없음(인사·재촉·필러 / 너무 짧음) → "…주제가 없습니다…"
//   ② 상담 근거(인용) 없음 → "…상담 근거가 없습니다…"
// FE: 규제 질문으로 상담을 한 번 진행(인용 답변 확보)한 뒤 보고서 버튼 활성 권장.

GET /reports/runs/{idempotency_key}
  {"status": "running|completed|failed", "report_id", "thread_id", "error"}
```

구경로의 "같은 thread SSE run + 입력창 차단" 대신: **비차단 백그라운드**.

### 채팅↔보고서 완전 분리 (2026-07-25 — 계약 변경)

보고서는 채팅과 **완전히 분리돼 병렬로** 돈다. 대화록에 보고서 흔적이 남지 않는다.

- **개요를 채팅 메시지로 append 하지 않는다**(구 계약 폐지). 구현은
  `kind:"report_overview"` AI 메시지를 붙였으나 제거 — 개요는 report 레코드의
  `summary`(+ 본문 `## 개요` 섹션)로만 존재한다.
  · front 는 **과거 thread 호환**을 위해 `report_overview` 턴 렌더를 유지하되,
    새 보고서에서는 그 메시지가 오지 않는다.
  · 부수 효과(의도됨): 구 구현은 append 순서 보존을 위해 per-thread 턴 락을
    잡아 보고서 잡이 채팅 턴을 기다렸다. 이제 그 결합이 없다.
- **진행 step 은 채팅 턴에 바인딩되지 않는다** — `report_*` step 에
  `source_message_id`/`turn_idx` 가 **없다**. front 는 채팅 턴 step 목록에서
  `tool_name.startsWith("report_")` 를 **배제**해야 한다(안 하면 ts fallback 이
  마지막 채팅 턴으로 빨아들인다 — `derive.ts:filterTurnSteps`).
- **대화 모델은 보고서 진행을 모른다** — 시스템 프롬프트에 주입하지 않는다
  (supervisor v16). "보고서 다 됐어?"엔 우측 패널 안내로만 답하고 단정하지 않는다.

**권장 UX** — 트리거 후 진행 배지 + 폴링(`GET /reports/runs/{key}`),
`completed` 시 ① 사이드바/우측 패널 `GET /threads/{tid}/reports` 갱신
② **채팅 밖 완료 신호**(토스트 + 탭 이탈 시 브라우저 알림). 이메일도 별도 발송.
진행 라벨은 state 의 `steps` 중 `report_decompose`/`report_gather`/`report_writer`
를 읽어 표시(채팅 타임라인엔 넣지 않고 우측 패널·노티스에만).

## 4b. 패치노트 팝업 — GET /announcements/latest (2026-08-13)

"매일 개선한다"를 보여주는 창구. 관리자가 배포 후 발행하면 프론트는 **로그인 후
최초 접속 시 1회** 팝업으로 보여준다.

```
GET /announcements/latest   (JWT)
→ 200 { announcement: null | {
    id: "note_ab12cd34ef56",   // 팝업 표시 여부의 기준 키
    date: "2026-08-13",        // 표기용 배포일
    title: "보고서 중단 버튼 · 업데이트 내역 게시판",   // 시기가 아니라 주요 변경
    version: "v0.8.0" | null,  // 릴리스 표기(2026-09-02, 선택 — 보조)
    feature: "심층 보고서" | null,  // 기능 영역(2026-09-07, 선택) — 게시판 탭·배지
    items: ["PII 오탐 신고 기능 추가", "검색 품질 개선"] } }

GET /announcements?limit=100&q=&feature=  → { count, items: [...], q, feature, features: [탭 순서] }
   // 2026-09-02: 공개 라우트(무인증) · 숨김 제외 · q = 키워드 검색(공백 AND, 제목+기능+항목)
   // 2026-09-07: feature = 기능 영역 정확 일치 필터. features = 노트가 있는 영역만 FEATURES 순
```

**업데이트 내역 게시판(2026-09-02, 사용자 피드백)**: `/updates`(공개) — 랜딩 nav·footer
에서 연결, 키워드 검색(로컬 필터 + `?q=` URL 동기화, 매치 `<mark>` 강조), 카드 id =
note id 라 팝업 [업데이트 목록 보기] → `/updates#<id>` 로 그 노트 위치에 착지.
제목은 시기가 아니라 **주요 변경**을 담는다(발행 화면 안내) — 목록·검색의 첫 줄.

**기능 단위 전환(2026-09-07, 사용자 지적 "버전별 릴리스 노트는 사용자 대상이 아니다·
알 필요 없는 내용도 있다")**: 노트 하나 = 기능 하나의 변화. `feature` 로 기능 영역을
달고 게시판 상단에 기능 탭(전체 + 노트가 있는 영역, `?f=` URL 동기화), 카드 첫 줄은
기능 배지(클릭 = 그 영역만), 버전은 보조 표기. 제목은 "무엇을 할 수 있게 됐는지",
본문은 어디서 어떻게 쓰는지 2~4줄. 내부 수정·버그 픽스·디자인 정리·성능 수치는 싣지
않는다. 기존 버전별 노트 7건은 숨김(백필 `local/04_공지메일/publish_feature_notes.py`).

**프론트 로직**: 앱 진입 시 latest 조회 → `announcement.id` 가 localStorage 의
`last_seen_announcement_id` 와 다르면 모달 팝업(제목 + 불릿 목록) → 닫으면 id
저장. 서버는 사용자별 읽음 상태를 저장하지 않는다(발행: `POST /admin/announcements`).

## 5. 마이그레이션 체크리스트 (front 작업 목록)

1. 전송층: SDK client → `fetch` + SSE 파서(`eventsource-parser` 류). §2 타입 적용.
2. thread 수명주기: 생성 호출 제거, `meta` 이벤트에서 thread_id 채택.
3. 리로드·사이드바·auto-title 을 §3 으로 교체.
4. clarify: resume 호출 제거 → 답변을 일반 메시지로 전송(§2-4).
5. 보고서: `agent_report` run → §4 (기존 15분 타임아웃·완료 카드 로직 재사용).
6. 취소: runs/cancel → SSE abort.
7. e2e: 채팅 스트림·후속 턴 인용 연속·clarify·보고서 완료·리로드·쿼터 429.


---

## 부록 — 계약 델타 (2026-07-15~16)

- **POST /chat**: `style?: "expert"|"simple"` 추가(설명 수준). 미지정=기본.
- **POST /reports**: `purpose?: "license_strategy"|"reg_summary"|"change_response"` 추가.
- **GET /chat/threads**: 항목에 `pinned: boolean`. 고정 토글은 `POST /chat/{tid}/pin`.
- **본문 검색**: `GET /chat/search?q=` (2자↑) — 사이드바 검색이 제목+본문 병합.
- **북마크**: `/bookmarks` CRUD + `/bookmarks/amendments`(kind: repealed/pending/amended).
- **내보내기**: `POST /answers/export` → docx(또는 md 폴백) blob.
- **Citation**: `status` 가 law.go.kr 개정상태 기반(폐지→`revoked`, 개명/이관→`amended_pending`).
- **done 순서**: 텍스트 완료 즉시 `done` emit → grounding 은 done *후* trailing `steps`
  (verified 갱신). FE 는 done 에서 턴 settle.
