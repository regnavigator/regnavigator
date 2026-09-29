# 05 · DATA — 백엔드 인터페이스 (front consumption guide)

> v0.3 · 2026-04-28
> **권위 원천: `../medi-back/02_INTERFACE.md` v0.4** (canonical 단일 진실원천).
> 본 문서는 그 *프론트 측 소비 가이드* — 데이터 모양·이벤트 발행 규약·SDK 호출은 back 문서가 진실. 본 문서는 *프론트가 추가로 결정한 것*(Turn 파생 디테일·UI 매핑·Citation 시각)만 박는다.
> 결정 변경 필요 시 **back 갱신이 먼저**, 본 문서가 따라간다.

---

## 1. 권위 원천 매핑

본 문서를 읽기 전, 또는 의문이 생기면 다음을 본다:

| 무엇이 박혀 있나 | 위치 |
|---|---|
| **API 통합 명세 (사람용)** | `../medi-back/docs/contracts/API.md` — 두 서비스·인증·CORS·6 라우트(LangGraph)·4 라우트(Reports)·TS 의사코드·에러표 |
| **OpenAPI (기계용)** | `http://127.0.0.1:2024/openapi.json`(LangGraph) · `http://127.0.0.1:2025/openapi.json`(Reports) — Swagger UI는 각각 `/docs` |
| 통신 모델·헤더·`stream_mode` 조합 | back `02_INTERFACE §0`, `§1`, `§5` |
| StateType (`messages` / `files` / `steps`) + reducer | back `02_INTERFACE §2` |
| Step / Citation / FileEntry / Artifact / InterruptValue 타입 | back `02_INTERFACE §2.1`–`§2.5` |
| Message 정규화·시스템 도구 숨김 | back `02_INTERFACE §3` (특히 `§3.5` `HIDDEN_TOOLS`) |
| Sub-agent(`task` tool) 안 step 처리 | back `02_INTERFACE §4` |
| SDK 호출 매핑 (Thread CRUD, runs.stream, resume) | back `02_INTERFACE §6` |
| 인용 마커 컨벤션 (`[n]` 평문 + `\[` escape) | back `02_INTERFACE §7` |
| Turn 파생 규칙 (front-side derive) | back `02_INTERFACE §8` |
| 재연결·idempotent 복원 | back `02_INTERFACE §9` |
| 시간(ms epoch)·ID(백엔드 발행)·네이밍(snake_case) | back `02_INTERFACE §10` |
| 결정 사항 / 미정 / 예시 페이로드 / v2 hook | back `02_INTERFACE §11`–`§14` |
| Fast/Deep dispatch 패턴 + deep 트리거 메시지 | back `docs/dispatch_pattern.md` |
| Reports API 라우트·인증·에러 표 | back `docs/API.md §"Reports API"` |

**핵심 합의 (back v0.4)**:
- 진행 상태는 `state.steps` **단일 소스**. custom 이벤트 X. 별도 REST X.
- 필드 네이밍: **snake_case** (JSON 그대로). TS 타입에서 그대로 매핑.
- 시간: **Unix epoch ms (int)**.
- ID: **백엔드 발행** (`step_*`, `cite_*`, file path).
- stream: `streamMode: ["values", "messages-tuple"]` + `streamSubgraphs: true`.

---

## 2. 프론트 측 추가 결정 (back에 박혀있지 않은 것만)

### 2.1 Turn 파생 — 효율 규칙

back `§8`의 6단계 파생은 매 state 갱신마다 *전체 재계산*하지 않는다. **incremental update** 권장:

| 트리거 | front 처리 |
|---|---|
| 새 `human` 메시지 도착 | `Turn[]` 끝에 새 Turn append (`turn.id = human.id`) |
| `state.steps`에 새 id append | 마지막 Turn의 `steps[]`에 append |
| 기존 `step.id` patch (running → done) | 해당 Turn 안 step을 *id로 찾아 merge* |
| `state.files`에 새 path 또는 modified_at 갱신 | 현재 active Turn의 `artifacts`에 반영 |
| 마지막 AI 메시지 content 갱신 | 현재 Turn의 `answer.content` 갱신 |

전체 재계산은 *재연결 시*만 (back `§9`).

### 2.2 UI 컴포넌트 매핑

| 백엔드 데이터 | 프론트 컴포넌트 | 참조 |
|---|---|---|
| `state.steps[]` (Turn 안 필터) | StepCard stack | `03 §4` |
| 마지막 `ai` message `content` | TurnAnswer · MarkdownContent | `03 §5.1` |
| 답변 본문 `[n]` + step.citations 합집합(id dedupe) | Citation chip + CitationFootnotes | `03 §5.2`, `§5.4` |
| `state.files[path]` (Turn 안 변경된 path) | ArtifactCard 인라인 + ArtifactViewer | `03 §5.3`, `§7.2` |
| `interrupt` payload | InterruptCard (마지막 StepCard 자리) | `03 §4.6` |
| 시스템 에러 (단절·인증 등) | InlineErrorBanner / 토스트 | `04 §4.3`, `§4.4` |

**StepCard 안 도구 노출 규칙** (back `§3.5` HIDDEN_TOOLS와 정합):
- `think_tool`, `write_todos`/`update_todo`/`delete_todo`, `read_file`/`ls`/`list_files` 등은 *애초에 백엔드가 step append를 안 함*. 프론트가 추가로 필터할 필요 X — 그냥 받은 step만 렌더.

### 2.X Citation 외부 원문 URL 도출

권위 원천: **`LAW_GO_KR_LINKS.md` v0.1** (13 분야 path 패턴).

| 우선 | 조건 | 결과 |
|---|---|---|
| 1 | `citation.url` 존재 | 그대로 사용 (백엔드가 결정한 deep-link — 가장 정확) |
| 2 | `source_kind === 'doc'` + 분야 검출 성공 | **path-based deep-link** 도출 — `https://www.law.go.kr/<분야>/<제목>[/<article>]` |
| 3 | `source_kind === 'doc'` + 한국 법령 같지만 분야 미검출 | **검색 페이지 fallback** — `https://www.law.go.kr/lsSc.do?query=<title>` |
| 4 | 그 외 | 외부 링크 없음 |

분야 검출 (heuristic — `LAW_GO_KR_LINKS §15`):

| 단서 | 분야 |
|---|---|
| publisher `헌법재판소` 또는 title `위헌소원/헌마/헌바/헌가` | **헌재결정례** |
| title `법령해석/해석례` | **법령해석례** |
| title `행정심판/심판청구` | **행정심판례** |
| publisher `대법원` 또는 title `판결/판례` | **판례** |
| title `조약/협정` | **조약** |
| title `조례/규칙` + publisher 지자체(서울특별시·강남구 등) | **자치법규** |
| title `고시/예규/훈령/규정/지침` | **행정규칙** |
| title 끝 `법률/시행령/시행규칙/법` 또는 `시행령/시행규칙` 포함 | **법령** |
| 위 외 정부 부처 publisher | **행정규칙** (fallback) |

조 단위 deep-link은 **법령·영문법령**에 한해 `/<제목>/<article>` 형태로 article 추가. 그 외 분야는 base path만.

**백엔드가 정확한 URL을 줄 수 있으면 항상 그것이 우선**. 본 도출은 *fallback*. 법령정보센터의 정확한 deep-link(예: `/법령/의료기기법시행규칙/제45조`)를 백엔드가 알면 그걸 `citation.url`에 넣어 보내주는 게 가장 좋다. *backend가 `Citation` 스키마에 `doc_category` 필드를 추가하면* heuristic 의존도를 낮출 수 있음 (`medi-back/02_INTERFACE.md` 측 결정).

코드: `src/lib/parse/lawLink.ts` — `deriveExternalUrl(citation)` / `externalUrlKind(citation, url)`.
UI: `CitationFootnotes`에서 *제목 자체를 외부 링크*로 + 우측에 ↗(웹) 또는 ⚖(law-portal) 아이콘 버튼.

### 2.3 Citation chip 시각 매핑 (`01 §2`)

`Citation.status` (back `§2.2`) 별 시각 — `01 §2 시맨틱 별칭`과 매핑:

| status | bg | text | 추가 |
|---|---|---|---|
| `active` (기본, 미지정 포함) | `--md-secondary-fixed` | `--md-on-secondary-fixed-variant` | — |
| `revoked` | `--md-error-container` | `--md-on-error-container` | **취소선** + 툴팁 "폐지된 근거" |
| `amended_pending` | `--md-tertiary-fixed` | `--md-on-tertiary-fixed-variant` | 툴팁 "곧 변경 예정" |

### 2.4 Artifact 파생 (back `§2.4` 그대로)

`state.files[path]` → 프론트 `Artifact` view:

```ts
// front-side derive
function toArtifact(path: string, entry: FileEntry): Artifact {
  const text = entry.content.join("\n");          // back §2.3 normalize
  const ext = path.split(".").pop()?.toLowerCase();
  return {
    path,
    bytes: new TextEncoder().encode(text).length,  // bytes는 derive
    modified_at: entry.modified_at,
    is_streaming: entry.is_streaming ?? false,
    title: extractTitle(text) ?? basename(path),    // markdown 첫 # 또는 path basename
    mime_type: mimeFromExt(ext),                    // ".md" → "text/markdown"
  };
}
```

`title` 추출 우선순위: markdown 본문의 첫 `# ` 헤딩 → 없으면 path basename.

### 2.5 Citation 본문 출처

`?citation=<id>` URL 진입 시(`02 §5`) 프론트는 별도 fetch 없이 **현재 thread state의 `state.steps[]`를 순회해 `id` 매칭** (back `§13.3`). RightPanel CitationInspector(`03 §7.1`)에 그대로 렌더.

---

## 3. Config → Client 생성

**Config 우선순위 (높음 → 낮음)**:
1. **환경변수** (production 권위) — `NEXT_PUBLIC_DEPLOYMENT_URL`, `NEXT_PUBLIC_ASSISTANT_ID`
2. **localStorage `medi-front-config`** — SettingsDialog로 입력된 dev override
3. **둘 다 없음** — dev 환경에선 SettingsDialog 자동 오픈, prod 환경에선 InlineErrorBanner

**더미 모드 (dev/QA 전용)**:
- `NEXT_PUBLIC_DUMMY_MODE=true` 시 *진짜 Client 생성 X* — `dummy.ts`의 fake client 반환.
- 사용자 흐름(질문 → StepCard → 답변·인용) 검증용. 백엔드 미배포 상태에서 UX 점검.
- production 빌드에 dummy 모드 끼워 넣지 X — 환경변수 분리 필수.

```ts
// src/lib/client/langgraph.ts (스펙)
import { Client } from "@langchain/langgraph-sdk";
import { createDummyClient } from "./dummy";

function readConfig() {
  if (process.env.NEXT_PUBLIC_DUMMY_MODE === "true") return null;  // dummy
  const env = {
    deployment_url: process.env.NEXT_PUBLIC_DEPLOYMENT_URL,
    assistant_id: process.env.NEXT_PUBLIC_ASSISTANT_ID,
  };
  const stored = readSettings();  // localStorage override
  return { ...env, ...stored };
}

export function getClient() {
  if (process.env.NEXT_PUBLIC_DUMMY_MODE === "true") return createDummyClient();
  const config = readConfig();
  if (!config?.deployment_url) return null;  // PageShell이 배너로 안내
  return new Client({
    apiUrl: config.deployment_url,
    apiKey: config.langsmith_key,
  });
}
```

**v2 hook**: `Authorization: Bearer ${user_jwt}` 추가 (back `§14`).

**`Settings` 타입** (localStorage용 — dev override):
```ts
type Settings = {
  deployment_url?: string;    // env로 충족되면 비워둘 수 있음
  assistant_id?: string;
  langsmith_key?: string;
  user_jwt?: string;          // v2 hook
};
```

---

## 3.5 Fast / Deep 2단계 dispatch (`../medi-back/docs/dispatch_pattern.md`)

| 그래프 | assistant_id | 용도 | wall |
|---|---|---|---|
| **fast** | `agent` (env: `NEXT_PUBLIC_ASSISTANT_ID`) | 사용자 첫 응답 (단답 + 인용) | ~25s |
| **deep** | `agent_deep` (env: `NEXT_PUBLIC_ASSISTANT_ID_DEEP`) | 보고서 3종(rag·web·final) 백그라운드 생성 + 영속 저장 | ~5분 |

같은 `thread_id`로 두 그래프 호출 — state(messages·steps·files·citations) 공유.

**호출 순서** (프런트 책임):
1. 사용자 질의 → `client.runs.stream(threadId, "agent", { input, streamMode: ["values","messages-tuple"], streamSubgraphs: true })`
2. fast 완료 → 채팅 본문에 **DeepReportCTA**(`03 §11c`) 등장 — *사용자 클릭 시*에만 deep dispatch (자동 X — 인사 같은 비-실질 질의 보호).
3. 사용자 클릭 → **deep 비동기 dispatch** (`runs.create` 또는 비-streaming POST):
   ```ts
   void client.runs.create(threadId, "agent_deep", {
     input: { messages: [{ type: "human", content: deepTrigger }] },
   });
   ```
   `await` 하지 않음. UI는 즉시 "심층 보고서 준비 중..." 인디케이터 (`03 §12 ReportPreparingIndicator`).
3. 폴링 → Reports API(`§6`)의 `/threads/{tid}/reports`. `status: 'done'`이 3개(rag·web·final) 보이면 준비 완료.

**Deep 트리거 메시지** (그대로 권장):
> 위 답변을 기반으로 심층 보고서 3종을 작성해주세요. (/rag_report.md, /web_report.md, /final_report.md). fast 답변의 결론과 인용 번호를 그대로 유지하고 그 위에 detail·해외 비교·시행일·과거이력을 확장하세요. 모순이 발견되면 별도 '보완·정정' 섹션에 명시.

**정합성 가드** (백엔드 자동, 프런트 *공유 캐시* 가능):
- writer는 fast 답변의 `[n]` 번호를 *같은 doc/chunk*로 유지 — Citation 인스펙터 캐시 fast/deep 공유 가능.
- 새 인용은 다음 번호부터 append-only.
- fast 결론 부정 금지 — 모순은 본문 아닌 `## 보완·정정` 섹션.

**중복 dispatch 방지**: 동일 thread에 deep이 이미 진행 중이면 재호출 X — `reports` 폴링 결과로 status 확인.

---

## 4. Stream 구독 (단일 패턴)

```ts
const stream = client.runs.stream(threadId, assistantId, {
  input: { messages: [{ type: "human", content: userInput }] },
  streamMode: ["values", "messages-tuple"],
  streamSubgraphs: true,
});

for await (const chunk of stream) {
  if (chunk.event === "values")          handleValues(chunk.data);          // state 갱신 — Turn 파생
  if (chunk.event === "messages-tuple")  handleMessageChunk(chunk.data);    // AI 메시지 토큰 partial 렌더
  if (chunk.event === "interrupt")       handleInterrupt(chunk.data);       // back §13.2
  if (chunk.event === "error")           handleSystemError(chunk.data);
}
```

**`updates` / `events` / `custom` 모드는 사용하지 않음** (back `§5`).

---

## 6. Reports 라우트 — **LangGraph endpoint에 통합**

medi-back이 `langgraph.json`의 `http.app: "./src/api.py:app"`로 FastAPI를 마운트 →
**LangGraph 기본 라우트와 동일 포트(2024)에서 서빙**. 별도 sidecar(2025) 폐기.

**권위 원천**:
- 사람용 명세: `../medi-back/docs/contracts/API.md` (canonical)
- 기계용 OpenAPI: `${DEPLOYMENT_URL}/openapi.json` (Swagger UI: `/docs`)
- TS 타입 자동 생성(선택): `npx openapi-typescript ${DEPLOYMENT_URL}/openapi.json -o api.d.ts`

**연결 방식 (front)**:
- `NEXT_PUBLIC_DEPLOYMENT_URL` 한 군데로 모든 호출 (LangGraph 기본 + Reports + Suggestions).
- 인증: `x-api-key` 헤더(LangSmith key) 한 종류로 통일.
- Front 측 프록시 라우트(`/api/reports/*`) **삭제됨** — 단일 endpoint라 CORS 우회 불필요.

### 6.1 라우트 (LangGraph 통합 endpoint)

| 메서드 · 경로 | 응답 | 용도 |
|---|---|---|
| `GET /healthz` | `{ status: "ok" }` | liveness |
| `GET /suggestions` | (back §X — 활용 시) | 추천 질의 (front 미사용, 향후 EmptyHero 등에 활용 가능) |
| `GET /threads/{thread_id}/reports` | `{ thread_id, count, reports: Report[] }` | 목록 (최신 우선) |
| `GET /reports/{report_id}` | `Report` 메타 + (gcs 경우) `download_url` presigned | 단건 |
| `GET /reports/{report_id}/download` | `text/markdown` 첨부 | .md 본문 다운로드 |

위 외에 LangGraph 기본 라우트(`/threads`, `/threads/{tid}/runs/stream` 등)도 같은 base.

### 6.2 `Report` 타입 — `API.md §"공통 데이터 모양 — ReportMeta"`

```ts
type Report = {
  id: string;                          // uuid hex
  thread_id: string;
  run_id: string | null;
  mode: "fast" | "deep";
  kind: "final" | "rag" | "web";
  status: "running" | "done" | "error";
  blob_uri: string | null;             // local: file:// , prod: gs://
  title: string | null;                // 표시 이름 (예: "final_report")
  citations: Citation[] | null;
  created_at: string;                  // ISO 8601 ※ Step.ts(ms)와 다름 — back 표기 차이
  completed_at: string | null;
  error_message: string | null;
  download_url?: string;               // 단건 GET 응답에만 (gcs presigned)
};
```

`state.files[/{kind}_report.md]` ↔ `Report` 매칭 (front-side): **파일명 패턴 `^(rag|web|final)_report\\.md$` → `kind`** (`ArtifactViewer.findMatchingReport`). 다른 파일은 매칭 X.

> 응답 모양 변경은 `medi-back/docs/contracts/API.md` 갱신이 먼저 → `05_DATA.md`·코드 동기화. 양 측 PR 묶음 머지.

### 6.X Thread 제목 책임 경계 — *backend 단독*

**Thread.metadata.title 생성은 backend 책임이고 front는 *읽기만* 한다.** (결합도 최소화)

- backend가 LLM 기반 요약 제목을 metadata.title에 박는 것이 정공.
- front는 자동 rename·자동 patch 호출 X — `client.threads.update`는 *사용자 수동 rename*(ThreadList 더블클릭) 한 곳에서만 호출.
- title이 비어있으면 ThreadList는 `FALLBACK_TITLE`(예: "(제목 없음)") 그대로 표시 — 사용자가 수동 rename 가능.
- backend가 추후 title 박으면 ThreadList 다음 search에서 자동 반영.

> ※ `deriveTitleFromQuery()` 헬퍼는 *수동 rename UX 유틸*로 남아있을 수 있으나, 자동 호출 경로는 없다.

### 6.3 폴링 정책 (front)

- deep dispatch 직후 시작.
- 간격: **3초** (back `API.md §"흐름 예시"` 권장).
- 멈춤 조건: `done` 카운트 ≥ 3. 또는 사용자 thread 전환 시.
- 에러: 3회 연속 실패 → 폴링 자동 종료 + 콘솔 경고 (사용자 향 알림 자제 — best-effort).

---

## 5. 폐기 — 이전 v0.1·v0.2의 결정 (back v0.4 이후 무효)

`02_INTERFACE` 합의 이전 본 문서가 단독으로 박았던 것들:

| 폐기 | 대체 |
|---|---|
| 8 custom 이벤트 (`turn.start`/`step.add`/`step.update`/`citation.add`/`artifact.update`/`interrupt`/`turn.end`/`error`) | `state.steps` 단일 소스 + `values` 모드 자동 emit (back `§5`, `§11 I1`) |
| `stream_mode=['updates','messages','custom']` | `["values","messages-tuple"]` + `streamSubgraphs: true` (back `§5`) |
| camelCase 필드 (`endedAt`, `toolName`, `inputPreview`, `outputPreview`, `errorMessage`, `isStreaming`, `modifiedAt`, `freeText`, `allowFreeText`, `hasInterrupt`, `ownerId` ...) | snake_case 통일 (back `§10 I11`) |
| `turnId`/`stepId` event-level 키 | state.steps의 `id` 단일 (id reducer merge — back `§2`) |
| `Citation.locator` 단일 필드 | `doc_id` / `article` / `page` 분리 (back `§2.2`) |
| `Artifact.bytes` 백엔드 발행 | `state.files[path].content: string[]`에서 front-derive (back `§2.4`) |
| 부록 A 8 이벤트 예시 JSON | back `§13`의 state-기반 예시 (`§13.1` 단일 턴, `§13.2` interrupt 흐름) |
| `SystemError.code` 대문자 (`STREAM_DISCONNECTED` 등) | (back에 명시 안 됨 — `§14`의 v2 hook은 `auth_expired` 소문자 snake_case. 본 코드는 그 컨벤션 따름) |

---

## 6. 카스케이드 영향 (별도 PR 필요)

본 문서 갱신과 *동시에* 다음 파일도 snake_case·state-only 모델로 갱신해야 정합:

| 파일 | 영향 | 우선도 |
|---|---|---|
| `03_COMPONENTS.md §2.2`, `§4.2` | Turn / Step 타입 필드 camelCase → snake_case (`endedAt`→`ended_at`, `toolName`→`tool_name`, `inputPreview`→`input_preview`, `outputPreview`→`output_preview`, `errorMessage`→`error_message`, `modifiedAt`→`modified_at`, `isStreaming`→`is_streaming`) | 높음 |
| `.claude/skills/medi-front-data-contract/SKILL.md` | "8 이벤트" 모델 전면 폐기, state-only로 재작성 | 높음 |
| `.claude/skills/medi-front-step-card/SKILL.md` | Step 필드 snake_case 갱신, "step.add/step.update" 표현 → "state.steps에 id로 merge" | 중 |
| `.claude/skills/medi-front-spec/SKILL.md` | 변경 미미 — back 문서 참조 한 줄 추가 | 낮음 |
| `IMPLEMENTATION.md` P5 ("8 custom event dispatcher") | "values 모드 핸들러 + Turn incremental derive"로 재작성 | 높음 |

본 변경 PR에 위 5건을 묶어 머지할 것 (`README.md` 변경 절차).

---

## Changelog
- 2026-04-28 v0.1 — 초안. 6 핵심 타입 + 8 스트림 이벤트 + 6 REST + v2 hook.
- 2026-04-28 v0.2 — G1~G5 박음(LangGraph SDK 경계, state→event 매핑 규약, 인증 와이어, 인용 마커, 예시 페이로드).
- 2026-04-28 **v0.3** — **`../medi-back/02_INTERFACE.md` v0.4와 정합**. 본 문서는 *consumption guide*로 축약 — back이 canonical 단일 진실원천. 8 custom 이벤트 모델·camelCase 필드·`updates+custom` stream mode·`turnId`/`stepId` event 키·`Citation.locator` 단일 필드·`Artifact.bytes` 백엔드 발행·부록 A 8 이벤트 예시 *모두 폐기*. front-측 추가 결정(Turn 파생 incremental·UI 매핑·Citation 시각·Artifact derive·Settings 폼)만 §2~§4에 박음. 카스케이드 영향 5건 §6에 명시 — 별도 PR로 정합 갱신 필요.
- 2026-04-29 v0.3.1 — §3 Config → Client: **env vars 우선** (production), localStorage override (dev), `NEXT_PUBLIC_DUMMY_MODE` (dev/QA fake client). SettingsDialog는 dev override 도구로 격하 (`03 §11`). `Settings` 타입의 모든 필드를 optional로 변경.
- 2026-04-29 v0.3.2 — §2.X Citation 외부 원문 URL 도출 정책 박음. (a) `citation.url` 존재 시 그대로, (b) doc + 한국 법령 패턴이면 **법령정보센터 검색 URL 자동 도출**, (c) 그 외 링크 없음. `src/lib/parse/lawLink.ts` 헬퍼 + `CitationFootnotes`에 외부 링크 UI(↗·⚖) 추가.
- 2026-04-29 v0.3.3 — §2.X 도출을 **path-based deep-link 우선 + 검색 fallback** 으로 격상. 13 분야(법령·영문법령·행정규칙·자치법규·학칙공단·조약·판례·헌재결정례·법령해석례·행정심판례·법령별표서식·행정규칙별표서식·자치법규별표서식) 매핑 — 권위 원천은 `LAW_GO_KR_LINKS.md` v0.1. lawLink.ts 분야 검출 heuristic 박음. backend의 `doc_category` 필드 추가 권장사항 명시.
- 2026-04-29 **v0.4** — **Fast/Deep 2단계 dispatch + Reports API sidecar** 박음. §3.5에 fast(`agent`) → deep(`agent_deep`) 비동기 dispatch + 한국어 트리거 메시지 + 정합성 가드 룰. 새 §6에 Reports API(port 2025) 라우트 4종 + Bearer token 인증 + Report 타입 + 폴링 정책. 권위 원천은 `../medi-back/docs/dispatch_pattern.md`와 `src/api.py`.
- 2026-04-29 **v0.4.1** — `../medi-back/docs/contracts/API.md` canonical 명세 흡수. §1 권위 원천 매핑에 OpenAPI(2024·2025 `/docs`·`/openapi.json`)와 `API.md` 추가. §6 Report 타입 정합화: `report_id`→`id`, `filename`→`title|null`, `bytes`/`updated_at` 제거, 누락 필드(`mode`/`run_id`/`blob_uri`/`citations`/`completed_at`/`error_message`) 추가. Status enum에서 `pending` 제거(running/done/error 3개). `created_at`은 ISO 문자열 (Step.ts ms와 다름 — back 표기 차이 명시). 폴링 4s→3s. §6 Thread 제목 책임 — backend 단독, front 자동 rename 제거(결합도 ↓). file↔report 매칭은 `^(rag|web|final)_report\.md$` → `kind`로 명시.
- 2026-04-29 **v0.5** — **Reports를 LangGraph endpoint에 통합**(medi-back `langgraph.json` `http.app`로 FastAPI 마운트). 별도 sidecar(2025) 폐기. front 측: `/api/reports/*` 프록시 라우트 삭제, `NEXT_PUBLIC_REPORTS_API_BASE`/`REPORTS_API_TOKEN` env 제거, `Settings.reports_api_*` 필드 제거. SettingsDialog에서 Reports 관련 2 row 제거. `reports.ts` getBase()는 `deployment_url` 그대로 사용, authHeaders는 `x-api-key` 단일. 단일 endpoint, 단일 인증, 단일 origin → CORS 우회 불필요.
