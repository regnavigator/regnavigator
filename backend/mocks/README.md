# Mock Fixtures — frontend dummy 모드용

> 백엔드 미실행 상태에서 medi-front 개발·UX 검증용. 실제 백엔드 응답·SSE 흐름과 정합.

## 파일 목록

| 파일 | 용도 |
|---|---|
| `fast_stream.jsonl` | fast 그래프 SSE 이벤트 시퀀스 (1줄 1이벤트) |
| `deep_stream.jsonl` | deep 그래프 SSE 이벤트 시퀀스 |
| `reports_list.json` | `GET /threads/{tid}/reports` 응답 (summary 필드 포함) |
| `report_detail.json` | `GET /reports/{rid}` 응답 |
| `me_usage.json` | `GET /me/usage` 응답 |
| `suggestions.json` | `GET /suggestions` 응답 (Claude/Gemini-style 카드) |
| `feedback_general_response.json` | `POST /feedback/general` 응답 |
| `admin_feedback.json` | `GET /admin/feedback` 응답 |
| `admin_users.json` | `GET /admin/users` 응답 |
| `auto_title_response.json` | `POST /threads/{tid}/auto-title` 응답 |

## 사용법

### A. 정적 import (Next.js)

```ts
import fastStreamJson from "@/mocks/fast_stream.jsonl?raw";
import reportsJson from "@/mocks/reports_list.json";

// SSE jsonl을 라인 단위로 파싱
const events = fastStreamJson.trim().split("\n").map(line => JSON.parse(line));
```

### B. fetch 인터셉트 (msw 또는 자체 구현)

```ts
// dummy 모드일 때 fetch가 mock 응답 반환
if (path === "/feedback/general") {
  return mockResponse(await loadJson("feedback_general_response.json"));
}
```

### C. dummy.ts SSE generator 확장

기존 `lib/client/dummy.ts scenarioA` → `fast_stream.jsonl` 라인 차례로 yield.

## 이벤트 형식 — SSE jsonl

각 줄은 `{event, data, run_id?}` JSON. 예:

```jsonl
{"event": "values", "data": {"messages": [...], "steps": [...]}}
{"event": "messages-tuple", "data": [{"id": "...", "type": "AIMessageChunk", "content": "..."}, {}]}
{"event": "custom", "data": {"type": "tool_progress", "tool": "qdrant_search", "phase": "embedding", "message": "..."}}
```

## 정합성

본 fixture는 다음 백엔드 동작과 **정합**:
- `supervisor_fast.py` v9_v4_alignment — 답변 본문 + `<next_steps>` 마커
- `tool_progress` custom event — qdrant/tavily/read_report 진행 phase
- `reports.summary` 필드 — final 보고서 요약
- `report.title` 자동 추출 — 본문 첫 H1

백엔드 변경 시 본 fixture도 함께 업데이트 필요.

## 갱신

실제 백엔드 응답을 캡처해 fixture에 반영:

```bash
# 1. 실제 호출
curl -N -X POST http://127.0.0.1:2024/threads/{tid}/runs/stream \
  -d '...' > captured_stream.txt

# 2. SSE → jsonl 변환 (event/data만 추출)
python scripts/sse_to_jsonl.py captured_stream.txt > mocks/fast_stream.jsonl
```

(스크립트 미존재 시 수동 변환)
