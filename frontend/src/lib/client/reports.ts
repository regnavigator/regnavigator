/**
 * Reports API client — 계약: ../medi-back/docs/contracts/API.md · frontend_chat_v2.md §4.
 *
 * 보고서 라우트(`/threads/{tid}/reports`·`/reports/{rid}`·`/reports/runs/{key}`)는
 * 채팅과 **같은 medi-back origin**(`NEXT_PUBLIC_DEPLOYMENT_URL`)에서 서빙된다.
 * 옛 sidecar(별도 포트 2025)·langgraph 마운트 구성은 2026-07-14 ADR-0001 로 은퇴.
 *
 * 인증: `Authorization: Bearer <NextAuth accessToken>` 만 받는다(옛 `x-api-key` 폐기 — 401 원인).
 * 토큰은 AuthProvider 가 in-memory store 로 sync. 같은 패턴은 `lib/api/client.ts:authHeaders()`.
 */

import { apiFetch } from "@/lib/api/client";
import type { Report } from "@/lib/store/types";
import { getEffectiveSettings } from "@/lib/store/settings";
import { getAuthToken } from "@/lib/client/authToken";

function authHeaders(): HeadersInit {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Reports 라우트 base = LangGraph deployment URL과 동일. */
function getBase(): string | null {
  const { deployment_url } = getEffectiveSettings();
  if (!deployment_url) return null;
  return deployment_url.replace(/\/+$/, "");
}

/**
 * thread별 보고서 목록 (최신 우선). 빈 배열 가능.
 * 인증 실패는 throw — 호출자가 InlineErrorBanner 처리.
 */
export async function listReports(
  threadId: string,
  signal?: AbortSignal,
): Promise<Report[]> {
  // DUMMY 모드 — public/mocks/reports_list.json 우선 반환
  const { maybeMockFetch } = await import("@/lib/client/mockFetch");
  const mocked = await maybeMockFetch<{ count?: number; reports?: Report[] }>(
    `/threads/${threadId}/reports`,
    "GET",
  );
  if (mocked) return Array.isArray(mocked.reports) ? mocked.reports : [];
  const base = getBase();
  if (!base) return [];
  const res = await fetch(
    `${base}/threads/${encodeURIComponent(threadId)}/reports`,
    { headers: authHeaders(), signal },
  );
  if (!res.ok) {
    throw new Error(`Reports API ${res.status}: ${await safeText(res)}`);
  }
  const json = (await res.json()) as { count?: number; reports?: Report[] };
  return Array.isArray(json.reports) ? json.reports : [];
}

// ※ 단일 thread 전환(2026-05-19): 별도 deep dispatch(startDeepReport·
//   agent_deep·parent_thread_id) 전부 폐기. 보고서는 같은 chat thread의
//   일반 턴에서 통합 supervisor가 동의 시 writer 위임 → 같은 thread_id로
//   태깅. 프런트는 GET /threads/{id}/reports(listReports)를 useChatState의
//   startReportsRefresh가 짧게 조회해 ReportCardGroup에 반영.

/**
 * 단건 보고서 메타. gcs 백엔드일 때 `download_url`(presigned)이 채워짐.
 */
export async function getReport(
  reportId: string,
  signal?: AbortSignal,
): Promise<Report | null> {
  const base = getBase();
  if (!base) return null;
  const res = await fetch(
    `${base}/reports/${encodeURIComponent(reportId)}`,
    { headers: authHeaders(), signal },
  );
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`Reports API ${res.status}: ${await safeText(res)}`);
  }
  return (await res.json()) as Report;
}

export type ReportFormat = "md" | "docx";

/**
 * 전문(blob) 만료 여부 — 보고서 파일 보존 30일(개인정보처리방침 §3).
 * 만료 시 blob만 삭제되고 메타(제목·인용)는 남는다. 만료본 다운로드는 409.
 */
/** 보고서/서류 삭제 (2026-08-27) — 소유자만. 전문 blob 도 함께 지워진다. */
/** 진행 중 보고서 중단(2026-09-02) — 진행 카드 [중단] 버튼 전용. */
export async function cancelReportRun(idempotencyKey: string): Promise<void> {
  await apiFetch(`/reports/runs/${encodeURIComponent(idempotencyKey)}/cancel`, {
    method: "POST",
  });
}

export async function deleteReport(reportId: string): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/reports/${encodeURIComponent(reportId)}`, {
    method: "DELETE",
  });
}

export function isReportExpired(report: Report): boolean {
  return report.status === "done" && !report.blob_uri && !report.download_url;
}

/** Report → 다운로드 시 사용할 파일명 도출. */
function reportFilename(report: Report, ext: string): string {
  const stem =
    report.title && report.title.length > 0
      ? report.title.replace(/\.(md|docx)$/i, "")
      : `${report.kind}_${report.id.slice(0, 8)}`;
  return `${stem}.${ext}`;
}

/** `Content-Disposition: attachment; filename="..."`에서 확장자 추출. */
function extFromResponse(res: Response, fallback: string): string {
  const cd = res.headers.get("content-disposition") ?? "";
  const m = cd.match(/filename="[^"]*\.(\w+)"/);
  if (m?.[1]) return m[1].toLowerCase();
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("wordprocessingml")) return "docx";
  if (ct.includes("markdown")) return "md";
  return fallback;
}

/**
 * 보고서 다운로드 — `<a download>` 트릭으로 브라우저 다운로드 트리거.
 * `format`: `md`(기본) | `docx` — 백엔드 `?format=` 쿼리(pandoc 변환).
 *
 * - md: presigned URL(gcs)이 있으면 직접 — 인증 헤더 불필요.
 * - docx: 서버 변환이 필요하므로 항상 `/reports/{id}/download` 엔드포인트.
 *   변환 불가 시 서버가 .md로 폴백(200)하므로 **응답 헤더의 실제 포맷을 신뢰**
 *   (확장자 하드코딩 금지 — docs/contracts/API.md §10).
 * - blob 만료(30일 경과)면 409 — `err.status === 409`로 호출자가 안내 처리.
 */
export async function downloadReport(
  report: Report,
  format: ReportFormat = "md",
): Promise<void> {
  const base = getBase();
  if (!base) throw new Error("Reports API base가 설정되지 않음.");

  if (format === "md") {
    // (1) 즉시 presigned URL 있으면 그대로
    if (report.download_url) {
      triggerDownload(report.download_url, reportFilename(report, "md"));
      return;
    }
    // (2) 단건 메타에 있을 수 있음 (목록 응답엔 보통 없음, 단건 응답엔 있을 수 있음)
    try {
      const fresh = await getReport(report.id);
      if (fresh?.download_url) {
        triggerDownload(fresh.download_url, reportFilename(report, "md"));
        return;
      }
    } catch {
      // 404 또는 fetch 실패 — 다음 fallback
    }
  }

  // (3) 다운로드 엔드포인트 — Bearer 첨부 필요 → Blob.
  const res = await fetch(
    `${base}/reports/${encodeURIComponent(report.id)}/download?format=${format}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    const err = new Error(
      res.status === 409
        ? "보고서 전문 보관기간(30일)이 지나 다운로드할 수 없습니다."
        : `download ${res.status}: ${await safeText(res)}`,
    ) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  const ext = extFromResponse(res, format);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    triggerDownload(url, reportFilename(report, ext));
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

function triggerDownload(href: string, filename: string): void {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Reports API 매칭이 없거나 dev에서 sidecar가 안 켜져 있을 때 fallback —
 * `state.files[path].content`를 직접 Blob으로 만들어 다운로드.
 *
 * mime은 확장자 기반(.md → text/markdown). filename은 path basename.
 */
export function downloadFromMemory(path: string, content: string): void {
  const filename = path.replace(/^\/+/, "").split("/").pop() ?? "artifact";
  const ext = filename.split(".").pop()?.toLowerCase();
  const mime =
    ext === "md"
      ? "text/markdown;charset=utf-8"
      : ext === "csv"
        ? "text/csv;charset=utf-8"
        : ext === "json"
          ? "application/json;charset=utf-8"
          : "text/plain;charset=utf-8";
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  try {
    triggerDownload(url, filename);
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

async function safeText(res: Response): Promise<string> {
  try {
    return await res.text();
  } catch {
    return "(no body)";
  }
}

// ※ pollReports(3s 폴링 헬퍼)·checkReportsHealth는 useChatState의 자체
//   인터벌 폴링(startReportsRefresh)으로 대체된 뒤 호출처가 없어 제거(2026-07-10).
