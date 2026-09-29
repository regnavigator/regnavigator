/**
 * /me/usage + feedback + 429 한도 초과 처리.
 *
 * - getUsage: GET /me/usage — 폴링용
 * - postMessageFeedback: POST /threads/{tid}/messages/{mid}/feedback
 * - postReportFeedback: POST /reports/{rid}/feedback
 * - parseQuotaError: 429 응답 body → 한국어 사용자 안내
 *
 * 모두 authToken store의 JWT를 Authorization 헤더에 자동 박음.
 */

import { apiFetch } from "@/lib/api/client";

export type Usage = {
  user_id: string;
  email: string;
  is_admin: boolean;
  effective_daily_limit: number;
  effective_monthly_limit: number;
  usage: {
    daily_input_tokens: number;
    daily_output_tokens: number;
    daily_total_tokens: number;
    daily_cost_usd: number;
    monthly_input_tokens: number;
    monthly_output_tokens: number;
    monthly_total_tokens: number;
    monthly_cost_usd: number;
  };
};

export type FeedbackRating = "thumbs_up" | "thumbs_down" | "canceled";

export type FeedbackBody = {
  rating: FeedbackRating;
  comment?: string;
};

export type FeedbackResponse = {
  feedback_id: string;
  rating: FeedbackRating;
};

export type QuotaError = {
  detail: string;
  period: "daily" | "monthly";
  tokens_used: number;
  tokens_limit: number;
};

export type RateLimitError = {
  detail: string;
  scope: "IP" | "user_min" | "user_hour";
  retry_after_seconds: number;
};

export type LimitErrorKind =
  | { kind: "quota"; period: "daily" | "monthly"; message: string }
  | { kind: "rate_limit"; scope: string; retryAfterSec: number; message: string };

export async function getUsage(signal?: AbortSignal): Promise<Usage> {
  return apiFetch<Usage>("/me/usage", { method: "GET", signal });
}

export async function postMessageFeedback(
  threadId: string,
  messageId: string,
  body: FeedbackBody,
): Promise<FeedbackResponse> {
  return apiFetch<FeedbackResponse>(
    `/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageId)}/feedback`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export async function postReportFeedback(
  reportId: string,
  body: FeedbackBody,
): Promise<FeedbackResponse> {
  return apiFetch<FeedbackResponse>(
    `/reports/${encodeURIComponent(reportId)}/feedback`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

/**
 * `@feedback` 자유 코멘트 — 채팅 input에 `@feedback ...` 입력 시 전송.
 *
 * - comment ≤2000자 (백엔드 422)
 * - context는 옵션 — thread_id, last_message_id, page 등 자유 필드
 * - 401·403은 jsonFetch가 throw
 */
export type GeneralFeedbackBody = {
  comment: string;
  context?: Record<string, unknown>;
};

export type GeneralFeedbackResponse = { feedback_id: string; ts: string };

export async function postGeneralFeedback(
  body: GeneralFeedbackBody,
): Promise<GeneralFeedbackResponse> {
  return apiFetch<GeneralFeedbackResponse>("/feedback/general", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * 인용 단위 오류 신고 — citation 팝오버의 [이 인용 신고] 버튼.
 * backend `POST /feedback/citation` (retrieval 품질 라벨 수집).
 */
export type CitationReportBody = {
  messageId?: string;
  citationId: string;
  citationNumber?: number;
  citationTitle?: string;
  reason?: string;
};

export async function reportCitation(
  threadId: string,
  body: CitationReportBody,
): Promise<{ ok: boolean; feedback_id: string }> {
  return apiFetch<{ ok: boolean; feedback_id: string }>("/feedback/citation", {
    method: "POST",
    body: JSON.stringify({
      thread_id: threadId,
      message_id: body.messageId,
      citation_id: body.citationId,
      citation_number: body.citationNumber,
      citation_title: body.citationTitle,
      reason: body.reason,
    }),
  });
}

/**
 * PII 오탐 신고 — pii_notice 토스트의 [오류 신고] 버튼 (2026-08-13).
 * backend `POST /feedback/pii` — **선보고 후조치**: 신고 즉시 그 단어는 마스킹
 * 제외(≤10s), 관리자가 사후 라벨링(correct 면 다시 마스킹). 주민번호·전화번호
 * 등 구조적 개인정보 형식은 422 로 거부된다.
 */
export type PiiReportResponse = {
  ok: boolean;
  term: string;
  /** unlabeled | reported | correct | wrong */
  status: string;
  /** false = 이미 '진짜 개인정보(correct)' 라벨된 단어 — 풀리지 않음 */
  unmasked: boolean;
  report_count: number;
};

export async function reportPiiTerm(
  threadId: string,
  body: { term: string; placeholder?: string; messageId?: string },
): Promise<PiiReportResponse> {
  return apiFetch<PiiReportResponse>("/feedback/pii", {
    method: "POST",
    body: JSON.stringify({
      thread_id: threadId,
      term: body.term,
      placeholder: body.placeholder,
      message_id: body.messageId,
    }),
  });
}

/**
 * 최신 패치노트 — 로그인 후 최초 접속 팝업(2026-08-13).
 * backend `GET /announcements/latest`. id 를 localStorage 와 비교해 안 본
 * 노트만 1회 노출(서버는 사용자별 읽음 상태를 저장하지 않는다).
 */
export type AnnouncementNote = {
  id: string;
  /** 표기용 배포일 "YYYY-MM-DD" */
  date: string;
  title: string;
  /** 릴리스 표기(선택) — "v0.8.0". 게시판·팝업 배지 */
  version?: string | null;
  /** 기능 영역(선택) — "심층 보고서" 등. 게시판 탭·배지(2026-09-07) */
  feature?: string | null;
  items: string[];
};

export async function getLatestAnnouncement(seenIds: string[] = []): Promise<AnnouncementNote | null> {
  const seen = seenIds.filter(Boolean).slice(0, 10).join(",");
  const r = await apiFetch<{ announcement: AnnouncementNote | null }>(
    seen ? `/announcements/latest?seen=${encodeURIComponent(seen)}` : "/announcements/latest",
  );
  return r.announcement ?? null;
}

/**
 * 업데이트 내역 목록(공개, 숨김 제외, 최신순) — `/updates` 게시판(2026-09-02).
 * `q` 는 서버 검색(공백 구분 AND) — 게시판은 전체를 받아 로컬 필터하므로 보통 비움.
 */
export async function listPublicAnnouncements(q = "", limit = 100): Promise<AnnouncementNote[]> {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (q.trim()) qs.set("q", q.trim());
  // same-origin 프록시(/api/announcements) — 비로그인·타 출처(localhost 등)에서 backend
  // CORS 에 막히던 문제(2026-09-02). 서버가 대신 backend 공개 라우트를 부른다.
  const res = await fetch(`/api/announcements?${qs.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const r = (await res.json()) as { count: number; items: AnnouncementNote[]; features?: string[] };
  return r.items ?? [];
}

/** 게시판 기능 탭 순서(backend announcements.FEATURES 와 동일). 목록 밖 값은 뒤에 붙인다. */
export const ANNOUNCEMENT_FEATURES = [
  "검색·답변",
  "심층 보고서",
  "IRB·DRB 심의 상담",
  "서류 작성",
  "개인정보 보호",
  "계정·이용",
  "화면·편의",
] as const;

/**
 * 429 응답 → quota 또는 rate_limit 분기.
 *
 * - period 키 있음 → 토큰 한도 초과 (QuotaMiddleware). reset = 자정/월초 의미적
 * - scope 키 있음 → 요청 빈도 초과 (RateLimitMiddleware). retry_after_seconds 후 재시도
 *
 * detail은 backend가 한국어로 박아서 보냄 — 그대로 노출.
 */
export function parse429(err: unknown): LimitErrorKind | null {
  const e = err as { status?: number; body?: string; message?: string };
  if (e?.status !== 429) return null;
  const raw = e.body ?? e.message ?? "";
  let parsed: Partial<QuotaError & RateLimitError> = {};
  try {
    parsed = JSON.parse(raw) as Partial<QuotaError & RateLimitError>;
  } catch {
    // body 파싱 실패 — 일반 안내
    return {
      kind: "quota",
      period: "daily",
      message: "사용량 한도에 도달했습니다.",
    };
  }
  const detail = parsed.detail ?? "사용량 한도에 도달했습니다.";
  if (parsed.period) {
    return {
      kind: "quota",
      period: parsed.period,
      message: detail,
    };
  }
  if (parsed.scope) {
    const sec = parsed.retry_after_seconds ?? 30;
    return {
      kind: "rate_limit",
      scope: parsed.scope,
      retryAfterSec: sec,
      message: detail,
    };
  }
  return { kind: "quota", period: "daily", message: detail };
}

/** Deprecated alias — useChatState가 이미 import 중. parse429 결과를 단순 메시지로 변환. */
export function parseQuotaError(err: unknown): { message: string } | null {
  const r = parse429(err);
  return r ? { message: r.message } : null;
}
