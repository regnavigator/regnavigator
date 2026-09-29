/**
 * mockFetch — DUMMY 모드에서 REST 응답을 `public/mocks/*.json`으로 차환.
 *
 * 호출 패턴:
 *   - `lib/client/quota.ts jsonFetch`  → /me/usage, /feedback/general, /admin/feedback 등
 *   - `lib/client/admin.ts jsonFetch`  → /admin/users, /admin/feedback
 *   - `lib/client/reports.ts`          → /threads/{tid}/reports, /reports/{rid}
 *
 * 본 모듈은 path → mock json 매핑만 담당. 호출자는 settings.js의 isDummyMode()로 분기.
 */

import { isDummyMode } from "@/lib/store/settings";

type MockMatcher = {
  test: (path: string, method: string) => boolean;
  fixture: string; // public/mocks 안의 파일명
};

const MATCHERS: MockMatcher[] = [
  // GET /me/usage
  { test: (p, m) => m === "GET" && /^\/me\/usage/.test(p), fixture: "me_usage.json" },
  // GET /threads/{tid}/reports
  {
    test: (p, m) => m === "GET" && /^\/threads\/[^/]+\/reports/.test(p),
    fixture: "reports_list.json",
  },
  // GET /reports/{rid} (단건)
  {
    test: (p, m) => m === "GET" && /^\/reports\/[^/]+$/.test(p),
    fixture: "report_detail.json",
  },
  // GET /reports/{rid}/download → markdown 본문 (텍스트). 별도 처리.
  // POST /feedback/general
  {
    test: (p, m) => m === "POST" && /^\/feedback\/general/.test(p),
    fixture: "feedback_general_response.json",
  },
  // GET /admin/feedback
  {
    test: (p, m) => m === "GET" && /^\/admin\/feedback/.test(p),
    fixture: "admin_feedback.json",
  },
  // GET /admin/stats/weekly — 주간 이용(2026-09-21). /admin/stats 보다 먼저 매칭.
  {
    test: (p, m) => m === "GET" && /^\/admin\/stats\/weekly(\?|$)/.test(p),
    fixture: "admin_stats_weekly.json",
  },
  // GET /admin/stats — 일별 + 실사용·내부·전체 비교
  {
    test: (p, m) => m === "GET" && /^\/admin\/stats(\?|$)/.test(p),
    fixture: "admin_stats.json",
  },
  // GET /admin/users
  {
    test: (p, m) => m === "GET" && /^\/admin\/users(\?|$)/.test(p),
    fixture: "admin_users.json",
  },
  // GET /suggestions
  {
    test: (p, m) => m === "GET" && /^\/suggestions/.test(p),
    fixture: "suggestions.json",
  },
  // POST /threads/{tid}/auto-title
  {
    test: (p, m) => m === "POST" && /^\/threads\/[^/]+\/auto-title/.test(p),
    fixture: "auto_title_response.json",
  },
  // POST /threads/{tid}/messages/{mid}/feedback (👍/👎)
  // POST /reports/{rid}/feedback — 단순 200 응답 흉내
  {
    test: (p, m) =>
      m === "POST" &&
      (/^\/threads\/[^/]+\/messages\/[^/]+\/feedback/.test(p) ||
        /^\/reports\/[^/]+\/feedback/.test(p)),
    fixture: "feedback_general_response.json",
  },
  // GET /article?key=
  {
    test: (p, m) => m === "GET" && /^\/article(\?|$)/.test(p),
    fixture: "article_detail.json",
  },
  // GET /law/{lawId}/articles
  {
    test: (p, m) => m === "GET" && /^\/law\/[^/]+\/articles/.test(p),
    fixture: "article_list.json",
  },
  // GET /annex?lawId&annexNum
  {
    test: (p, m) => m === "GET" && /^\/annex(\?|$)/.test(p),
    fixture: "annex_detail.json",
  },
  // GET /annex/list?lawId
  {
    test: (p, m) => m === "GET" && /^\/annex\/list/.test(p),
    fixture: "annex_list.json",
  },
  // GET /legal/{terms|privacy} — 정본 markdown (경로 우선: /legal 보다 먼저)
  {
    test: (p, m) => m === "GET" && /^\/legal\/terms$/.test(p),
    fixture: "legal_terms.json",
  },
  {
    test: (p, m) => m === "GET" && /^\/legal\/privacy$/.test(p),
    fixture: "legal_privacy.json",
  },
  // GET /legal — 면책·핵심 고지
  {
    test: (p, m) => m === "GET" && /^\/legal$/.test(p),
    fixture: "legal_notice.json",
  },
  // GET·POST /me/consent — 동의 상태·기록
  {
    test: (p, m) => m === "GET" && /^\/me\/consent$/.test(p),
    fixture: "me_consent.json",
  },
  {
    test: (p, m) => m === "POST" && /^\/me\/consent$/.test(p),
    fixture: "me_consent_ok.json",
  },
  // GET /me/data — 열람(법 제35조)
  {
    test: (p, m) => m === "GET" && /^\/me\/data$/.test(p),
    fixture: "me_data.json",
  },
  // POST /me/erase — 삭제 요구 접수
  {
    test: (p, m) => m === "POST" && /^\/me\/erase$/.test(p),
    fixture: "me_erase_ok.json",
  },
  // GET /load — 서버 혼잡 배지
  {
    test: (p, m) => m === "GET" && /^\/load$/.test(p),
    fixture: "load_status.json",
  },
];

const cache = new Map<string, unknown>();

async function loadFixture<T>(name: string): Promise<T> {
  if (cache.has(name)) return cache.get(name) as T;
  const res = await fetch(`/mocks/${name}`);
  if (!res.ok) throw new Error(`mock fixture not found: ${name}`);
  const json = (await res.json()) as T;
  cache.set(name, json);
  return json;
}

/**
 * dummy 모드에서 REST 호출을 인터셉트해 mock json 반환.
 * 매칭 안 되면 null 반환 → 호출자는 평소대로 진행.
 */
export async function maybeMockFetch<T>(
  path: string,
  method = "GET",
): Promise<T | null> {
  if (!isDummyMode()) return null;
  for (const m of MATCHERS) {
    if (m.test(path, method.toUpperCase())) {
      return (await loadFixture<T>(m.fixture)) as T;
    }
  }
  return null;
}

/** /reports/{rid}/download 전용 — markdown 평문 반환. */
export async function maybeMockReportDownload(
  path: string,
): Promise<string | null> {
  if (!isDummyMode()) return null;
  if (!/^\/reports\/[^/]+\/download/.test(path)) return null;
  // detail json에 body 풀텍스트가 있다면 거기서 추출, 아니면 더미 텍스트
  type ReportDetail = { body?: string; markdown?: string; content?: string };
  const detail = await loadFixture<ReportDetail>("report_detail.json");
  return (
    detail.body ??
    detail.markdown ??
    detail.content ??
    "# Mock 보고서\n\n본문 fixture가 비어있습니다."
  );
}
