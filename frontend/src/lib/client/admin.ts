/**
 * Admin API — backend `/admin/users` 라우트.
 *
 * - listUsers: GET /admin/users?limit=&offset=
 * - patchUser: PATCH /admin/users/{id} ( daily/monthly override · is_admin · -1 = 제거)
 *
 * 응답 schema는 backend docs에 명시 안 됨 — array 직접 반환 또는 { users: [...] } 둘 다 흡수.
 */

import { apiFetch, apiFetchText } from "@/lib/api/client";
import type { Usage } from "@/lib/client/quota";

/** 조회 범위 — "real"(기본): 베타 오픈(2026-08-03) 이후 실사용 데이터만.
 *  "all": 그 이전 개발·e2e 테스트 데이터까지 포함. 경계는 backend 가 정한다
 *  (env SERVICE_LAUNCH_AT). 섞어 보면 테스트 트래픽이 이용자 지표로 읽힌다. */
export type DataScope = "real" | "all";

export type DataScopeInfo = { launch_at: string; default_scope: DataScope };

export async function getDataScope(): Promise<DataScopeInfo> {
  return apiFetch<DataScopeInfo>("/admin/data-scope");
}


// backend `/admin/users`는 `{ **User.as_dict(), ... }` 를 반환 — User PK는 `id`
// (medi-back persistence/users_repo.py). `Usage.user_id`(=/me/usage 형태)와 다름.
// admin 식별자는 *항상 `id`* 사용 (user_id로 접근 시 undefined → /admin/users/
// undefined/usage 404).
export type AdminUser = Usage & {
  id: string;
  /** 마케팅 메일 동의(최신 legal_consent 기준, 2026-08-28) */
  marketing_opt_in?: boolean;
  /** 보고서 완료 메일 수신(개인 설정) */
  report_email_opt_in?: boolean;
  /** 프로필(온보딩 입력, 2026-08-10) — 미입력이면 null */
  display_name?: string | null;
  affiliation?: string | null;
  job_role?: string | null;
  /** 관리자 식별 메모(2026-09-15) — 관리자 화면 전용, 사용자에게 비노출 */
  admin_memo?: string | null;
  daily_token_limit_override?: number | null;
  monthly_token_limit_override?: number | null;
  /** 가입일(ISO) — backend User.created_at */
  created_at?: string | null;
  /** 최근 활동(ISO) — 인증 미들웨어가 매 요청 upsert 로 갱신(≈최종 접속).
   *  관리자 편집(한도·프로필)도 갱신하므로 초 단위 정밀도는 아님. */
  updated_at?: string | null;
  /** 비활성(소프트삭제) 시각 — null 이면 활성 */
  deleted_at?: string | null;
  /** 화이트리스트로 명시 허용된 회원인가 */
  whitelisted?: boolean;
  /** "admin" | "env" | "db" | "domain:@x.com" | null */
  whitelist_source?: string | null;
  /** 게이트·비활성 반영한 실제 이용 가능 여부 */
  can_access?: boolean;
  /** 내부 계정(관리자·테스트) — 하위호환 필드, is_internal 과 같은 뜻 */
  is_test_account?: boolean;
  /** 계정 구분(2026-09-21) — 유효값(자동 포함). 정본은 backend src/account_class.py */
  account_class?: AccountClass;
  account_class_label?: string;
  /** manual | auto:admin | auto:pre_launch | auto:beta_invited | auto */
  account_class_source?: string;
  /** 관리자가 직접 붙인 라벨(null = 자동) */
  account_class_manual?: AccountClass | null;
  /** true 면 실사용 집계에서 빠진다 */
  is_internal?: boolean;
  /** 관리자 기능별 권한(2026-09-22) — 저장값(콤마, null=전 권한) */
  admin_perms?: string | null;
  /** 실제 적용 권한(루트=전부, 관리자 아님=[]) */
  admin_perms_list?: AdminPerm[];
  /** 전 권한인가(루트 또는 권한 미지정 기존 관리자) */
  admin_perms_all?: boolean;
  /** 루트 관리자(ADMIN_EMAILS) — 권한 변경 불가, 항상 전 권한 */
  is_root_admin?: boolean;
};

/** 계정 구분 — staff(관리자 — is_admin 으로만 정해짐, 2026-09-22 운영진 통합)·test(테스트)·user(실사용자) */
export type AccountClass = "staff" | "test" | "user";
export const ACCOUNT_CLASS_LABEL: Record<AccountClass, string> = {
  staff: "관리자",
  test: "테스트",
  user: "실사용자",
};

export type AdminUserPatch = {
  daily_token_limit_override?: number;
  monthly_token_limit_override?: number;
  is_admin?: boolean;
  /** 관리자 기능별 권한(루트만) — null = 전 권한 */
  admin_perms?: AdminPerm[] | null;
  /** 관리자 식별 메모(빈 문자열 = 삭제) */
  admin_memo?: string;
  /** 계정 구분 라벨 — "auto" = 자동 판정으로 되돌림 */
  account_class?: AccountClass | "auto";
  /** 관리자가 대신 기입하는 프로필 — 준 키만 바뀜 */
  display_name?: string;
  affiliation?: string;
  job_role?: string;
};

/** 배포 식별(2026-09-15) — GET /admin/build. 이미지 빌드 시각·커밋·프로세스 기동 시각. */
export type AdminBuildInfo = {
  git_sha: string;
  built_at: string | null;
  started_at: string;
  prompt_version: string;
};

export async function getAdminBuild(): Promise<AdminBuildInfo> {
  return apiFetch("/admin/build");
}

export async function listUsers(
  limit = 50,
  offset = 0,
): Promise<AdminUser[]> {
  const data = await apiFetch<AdminUser[] | { users?: AdminUser[] }>(
    `/admin/users?limit=${limit}&offset=${offset}`,
  );
  if (Array.isArray(data)) return data;
  return data.users ?? [];
}

/** 목록 + 베타 게이트 상태(gate_active) 를 함께 필요로 할 때.
 *  `q`: 이메일 부분일치 — DB 서버측 검색(로드된 페이지만 거르는 게 아님). */
export async function listUsersWithGate(
  limit = 50,
  offset = 0,
  scope: DataScope = "all",
  q = "",
): Promise<{ users: AdminUser[]; gate_active: boolean }> {
  const qs = q.trim() ? `&q=${encodeURIComponent(q.trim())}` : "";
  const data = await apiFetch<AdminUser[] | { users?: AdminUser[]; gate_active?: boolean }>(
    `/admin/users?limit=${limit}&offset=${offset}&scope=${scope}${qs}`,
  );
  if (Array.isArray(data)) return { users: data, gate_active: false };
  return { users: data.users ?? [], gate_active: !!data.gate_active };
}

export async function patchUser(
  userId: string,
  body: AdminUserPatch,
): Promise<AdminUser> {
  // backend `admin_update_user`(medi-back a41b203~, 2026-05-19): JSON body
  // 우선 + query fallback 둘 다 수용 → 표준 JSON body로 정리(현행 계약).
  //
  // `-1` = **시스템 기본값으로 리셋** (override를 NULL로 제거하는 게 아님 —
  // 영속층 COALESCE 한계). 빈 칸 저장 후 재조회 시 override가 기본값 숫자
  // (예: 일 1,000,000)로 내려옴. "override 없음=빈 칸" UX는 별도 처리 필요
  // (프런트가 시스템 기본값을 모르는 한계 — backend가 응답에 노출 시 가능).
  return apiFetch<AdminUser>(
    `/admin/users/${encodeURIComponent(userId)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

/** 단일 사용자 사용량 상세 — list보다 더 자세한 breakdown (가능하면 시계열·비용 분리) */
export async function getUserUsage(userId: string): Promise<AdminUser> {
  return apiFetch<AdminUser>(
    `/admin/users/${encodeURIComponent(userId)}/usage`,
  );
}

/* ─────────────────── Admin · 피드백 조회 ─────────────────── */

export type AdminFeedbackKind = "user_feedback" | "feedback";

export type AdminFeedbackItem = {
  id: string;
  ts: string;
  user_id: string;
  thread_id?: string | null;
  message_id?: string | null;
  payload: Record<string, unknown>;
};

export type AdminFeedbackPage = {
  count: number;
  items: AdminFeedbackItem[];
};

export async function listAdminFeedback(opts: {
  kind?: AdminFeedbackKind;
  limit?: number;
  offset?: number;
  since?: string;
  until?: string;
}): Promise<AdminFeedbackPage> {
  const params = new URLSearchParams();
  params.set("kind", opts.kind ?? "user_feedback");
  params.set("limit", String(opts.limit ?? 100));
  params.set("offset", String(opts.offset ?? 0));
  if (opts.since) params.set("since", opts.since);
  if (opts.until) params.set("until", opts.until);
  return apiFetch<AdminFeedbackPage>(`/admin/feedback?${params.toString()}`);
}

/* ─────────────── 베타 화이트리스트 · 시스템 설정 (2026-07-14) ─────────────── */

export type WhitelistEntry = {
  entry: string;
  added_by: string | null;
  created_at: string | null;
  /** 베타 초대 메일 발송 시각. null = 아직 미발송 (2026-08-05). */
  invited_at?: string | null;
  invited_by?: string | null;
  /** 이 주소로 가입한 계정의 생성 시각. 있으면 이미 쓰고 있는 사용자. */
  joined_at?: string | null;
};

export type WhitelistState = {
  gate_active: boolean;
  env_entries: string[];       // .env 관리 — UI 읽기전용
  db_entries: WhitelistEntry[]; // admin 관리
};

export async function getWhitelist(): Promise<WhitelistState> {
  return apiFetch<WhitelistState>("/admin/whitelist");
}

export async function addWhitelistEntry(entry: string): Promise<void> {
  await apiFetch("/admin/whitelist", {
    method: "POST",
    body: JSON.stringify({ entry }),
  });
}

export async function removeWhitelistEntry(entry: string): Promise<void> {
  await apiFetch(`/admin/whitelist/${encodeURIComponent(entry)}`, {
    method: "DELETE",
  });
}

export type InviteResult = {
  entry: string;
  /** 이미 보낸 적 있는 대상에 다시 보냈는지 */
  resent: boolean;
  invited_at: string | null;
  invited_by: string | null;
  smtp_configured: boolean;
};

/**
 * 이 항목 한 건에 베타 초대 메일 발송 (2026-08-05).
 *
 * 등록에 딸려 자동 발송하지 않는 이유: 메일은 되돌릴 수 없고, 벌크 붙여넣기
 * 한 번이 곧 무더기 발송이 된다. 관리자가 한 건씩 명시적으로 보낸다.
 * 발송 실패는 502 로 올라오고 `invited_at` 은 기록되지 않는다.
 */
export async function sendWhitelistInvite(entry: string): Promise<InviteResult> {
  return apiFetch<InviteResult>(
    `/admin/whitelist/${encodeURIComponent(entry)}/invite`,
    { method: "POST" },
  );
}

/** 초대 메일 템플릿(2026-08-28) — 수정본 있으면 is_custom=true. */
export type InviteTemplate = {
  subject: string;
  body: string;
  is_custom: boolean;
  updated_at?: string | null;
  updated_by?: string | null;
};

/** 지금 발송하면 나갈 초대 메일 내용. */
export async function getInviteTemplate(): Promise<InviteTemplate> {
  return apiFetch<InviteTemplate>("/admin/invite-template");
}

/** 제목·본문 수정 — 다음 발송부터 즉시 적용. */
export async function saveInviteTemplate(subject: string, body: string): Promise<InviteTemplate> {
  return apiFetch<InviteTemplate>("/admin/invite-template", {
    method: "PUT",
    body: JSON.stringify({ subject, body }),
  });
}

/** 편집 중 내용의 실제 메일 HTML — 저장 없이 확인. */
export async function previewInviteTemplate(subject: string, body: string): Promise<{ html: string }> {
  return apiFetch<{ html: string }>("/admin/invite-template/preview", {
    method: "POST",
    body: JSON.stringify({ subject, body }),
  });
}

/** 관리자 본인 주소로 1통 테스트 발송(제목에 [테스트] 접두). */
export async function testInviteTemplate(subject: string, body: string): Promise<{ ok: boolean; to: string }> {
  return apiFetch<{ ok: boolean; to: string }>("/admin/invite-template/test", {
    method: "POST",
    body: JSON.stringify({ subject, body }),
  });
}

/** 수정본 폐기 — 기본 문구로 복원. */
export async function resetInviteTemplate(): Promise<InviteTemplate> {
  return apiFetch<InviteTemplate>("/admin/invite-template", { method: "DELETE" });
}

export type ConfigItem = {
  key: string;
  doc: string;
  default: string | null;
  secret: boolean;
  prod_required: boolean;
  is_set: boolean;
  value: string | null; // secret 이면 항상 null
};

export async function getAdminConfig(): Promise<Record<string, ConfigItem[]>> {
  const res = await apiFetch<{ groups: Record<string, ConfigItem[]> }>(
    "/admin/config",
  );
  return res.groups;
}

/* ─────────────────── Admin · 점검(유지보수) 모드 (2026-07-15) ─────────────────── */

export type MaintenanceSchedule = {
  enabled: boolean;
  /** "HH:MM" (tz 기준) */
  start: string;
  end: string;
  tz: string;
};

export type MaintenanceState = {
  /** effective — 수동 OR 예약 시간대 */
  active: boolean;
  /** "manual" | "schedule" | "" */
  source: string;
  /** 수동 점검 플래그(즉시 on/off) */
  manual: boolean;
  message: string;
  updated_by: string | null;
  since: string | null;
  schedule: MaintenanceSchedule | null;
  default_message: string;
  default_tz: string;
  /** 기능 단위 일시 중단(2026-09-07) — {reports: {paused, message, since, updated_by}} */
  features?: Record<string, { paused: boolean; message?: string; since?: string | null; updated_by?: string | null }>;
  feature_names?: string[];
  feature_default_messages?: Record<string, string>;
  /** writer(DGX vLLM) 프로브 — null = 로컬 writer 미설정 */
  writer_up?: boolean | null;
};

/** GET /admin/maintenance — 수동 플래그 + 예약(매일 반복) + effective active. */
export async function getMaintenance(): Promise<MaintenanceState> {
  return apiFetch<MaintenanceState>("/admin/maintenance");
}

/** POST — 수동 점검 on/off. active=true 면 비관리자 즉시 503. */
export async function setMaintenance(
  active: boolean,
  message?: string,
): Promise<MaintenanceState & { ok: boolean }> {
  return apiFetch<MaintenanceState & { ok: boolean }>("/admin/maintenance", {
    method: "POST",
    body: JSON.stringify({ active, message }),
  });
}

/** POST — 기능 단위 일시 중단(2026-09-07). name="reports": 보고서 POST 503 + 프런트 배너, 채팅은 정상. */
export async function setFeaturePause(
  name: string,
  paused: boolean,
  message?: string,
): Promise<MaintenanceState & { ok: boolean }> {
  return apiFetch<MaintenanceState & { ok: boolean }>("/admin/maintenance", {
    method: "POST",
    body: JSON.stringify({ features: { [name]: { paused, message } } }),
  });
}

/** POST — 매일 반복 점검 시간대 설정(크론 불필요, 서버가 자동 on/off). */
export async function setMaintenanceSchedule(
  enabled: boolean,
  start: string,
  end: string,
  message?: string,
): Promise<MaintenanceState & { ok: boolean }> {
  return apiFetch<MaintenanceState & { ok: boolean }>("/admin/maintenance", {
    method: "POST",
    body: JSON.stringify({ schedule: { enabled, start, end }, message }),
  });
}

/* ─────────────────── Admin · 사용 통계 (2026-07-15) ─────────────────── */

export type AdminDailyStat = {
  /** "YYYY-MM-DD" */
  day: string;
  llm_calls: number;
  active_users: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  quota_blocked: number;
  citation_reports: number;
};

export type AdminStats = {
  days: number;
  /** 최신순 */
  daily: AdminDailyStat[];
  totals: {
    llm_calls: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    quota_blocked: number;
    citation_reports: number;
  };
  /** 같은 기간의 실사용·내부·전체 비교(2026-09-21) — 집계 실패 시 null */
  breakdown?: Record<UsageScope, UsageMetrics> | null;
  metrics?: UsageMetricDef[];
};

/* ─────────────────── 주간 이용 집계 (2026-09-21) ─────────────────── */

export type UsageScope = "real" | "internal" | "all";
export type UsageMetricKey =
  | "active_users" | "returning_users" | "new_users" | "questions" | "threads"
  | "reports" | "reports_completed" | "documents" | "doc_fills" | "feedback"
  | "citation_reports" | "llm_calls" | "tokens" | "cost_usd";
export type UsageMetrics = Record<UsageMetricKey, number>;
export type UsageMetricDef = {
  key: UsageMetricKey;
  label: string;
  kind: "count" | "users" | "usd";
  desc: string;
};
export type UsageWeek = {
  /** 월요일(KST) YYYY-MM-DD */
  week_start: string;
  week_end: string;
  /** 진행 중인 주(실시간 계산, 저장 안 됨) */
  partial: boolean;
  stored: boolean;
  /** 저장 이후 계정 라벨이 바뀌어 재계산이 필요 */
  stale: boolean;
  computed_at?: string;
  scopes: Record<UsageScope, UsageMetrics>;
};
export type WeeklyStats = {
  /** 최신 주가 앞 */
  weeks: UsageWeek[];
  metrics: UsageMetricDef[];
  scopes: { key: UsageScope; label: string; desc: string }[];
};

export async function getWeeklyStats(weeks = 12): Promise<WeeklyStats> {
  return apiFetch<WeeklyStats>(`/admin/stats/weekly?weeks=${weeks}`);
}

/** 저장된 주간 집계 재계산 — weekStart 없으면 라벨 변경으로 어긋난(stale) 주 전부 */
export async function recomputeWeeklyStats(
  weekStart?: string,
): Promise<{ ok: boolean; recomputed: string[] }> {
  return apiFetch(`/admin/stats/weekly/recompute`, {
    method: "POST",
    body: JSON.stringify(weekStart ? { week_start: weekStart } : {}),
  });
}

/** GET /admin/stats?days=N — events 테이블 일별 집계 (backend 1~180일 clamp). */
export async function getAdminStats(
  days = 30,
  scope: DataScope = "real",
): Promise<AdminStats> {
  return apiFetch<AdminStats>(`/admin/stats?days=${days}&scope=${scope}`);
}


/* ─────────────────── Admin · 이용 조회 (질문·법령검색) ─────────────────── */

export type AdminQuestionItem = {
  ts: string;
  user_id: string | null;
  thread_id: string | null;
  /** PII 마스킹된 질문 본문 */
  question: string;
  forced_search?: boolean | null;
  /** 작성자 정보(backend users 조인, 2026-08-10) — 미가입/미상은 null */
  email?: string | null;
  display_name?: string | null;
  affiliation?: string | null;
  job_role?: string | null;
  /** 관리자가 붙인 식별 메모(프로필 미입력 가입자용) */
  admin_memo?: string | null;
};

/** 관리자 목록 행에 평평하게 붙는 사용자 표기 필드(2026-09-18) — 이메일·프로필·식별 메모. */
export type AdminUserFields = {
  user_email?: string | null;
  user_display_name?: string | null;
  user_affiliation?: string | null;
  user_job_role?: string | null;
  user_admin_memo?: string | null;
};

export type AdminQuestions = {
  days: number;
  /** 기간·scope 필터 후 전체 건수(페이지와 무관) */
  total: number;
  /** 이 페이지 건수 */
  count?: number;
  offset?: number;
  has_more?: boolean;
  unique_users: number;
  /** 최신순 */
  items: AdminQuestionItem[];
  top_questions: { question: string; count: number }[];
};

/** GET /admin/questions?days=&limit=&offset= — 이용자 질문 리스트(마스킹, 페이지) + 최다 질문. */
export async function getAdminQuestions(
  days = 30,
  limit = 200,
  scope: DataScope = "real",
  offset = 0,
): Promise<AdminQuestions> {
  return apiFetch<AdminQuestions>(
    `/admin/questions?days=${days}&limit=${limit}&offset=${offset}&scope=${scope}`,
  );
}

export type AdminSearchLawItem = {
  law_id: string;
  law_title: string;
  /** 검색 결과에 등장한 총 히트 수 */
  hits: number;
  /** 이 법령이 등장한 검색 횟수 */
  searches: number;
};

export type AdminSearchLaws = {
  days: number;
  total_searches: number;
  unique_users: number;
  top_laws: AdminSearchLawItem[];
  by_target_type: Record<string, number>;
  top_queries: { query: string; count: number }[];
};

/** GET /admin/stats/search-laws?days=&limit= — 검색된 법령 랭킹 + 최다 질의. */
export async function getAdminSearchLaws(
  days = 30,
  limit = 30,
  scope: DataScope = "real",
): Promise<AdminSearchLaws> {
  return apiFetch<AdminSearchLaws>(
    `/admin/stats/search-laws?days=${days}&limit=${limit}&scope=${scope}`,
  );
}

/* ─────────────────── Admin · 대화 원문 뷰어 ─────────────────── */

export type AdminThreadListItem = AdminUserFields & {
  thread_id: string;
  user_id: string | null;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminThreadList = {
  count: number;
  /** 필터(scope) 적용 후 전체 건수 — 페이지 수 계산용 */
  total: number;
  offset: number;
  has_more: boolean;
  threads: AdminThreadListItem[];
};

/** GET /admin/threads?limit=&offset= — 전체 사용자 대화 thread 목록(최근순, 페이지). */
export async function getAdminThreads(
  limit = 100,
  scope: DataScope = "real",
  offset = 0,
): Promise<AdminThreadList> {
  return apiFetch<AdminThreadList>(
    `/admin/threads?limit=${limit}&offset=${offset}&scope=${scope}`,
  );
}

// ── 보고서 요청·발송 조회 (2026-08-21) ─────────────────────────────
export type AdminReportRun = {
  idempotency_key: string;
  thread_id: string;
  user_id: string | null;
  user_email: string | null;
  user_display_name?: string | null;
  user_admin_memo?: string | null;
  /** running | completed | failed */
  status: string;
  error: string | null;
  prompt: string;
  purpose: string | null;
  report_id: string | null;
  report_title: string | null;
  report_status: string | null;
  /** sent | failed | null(발송 기록 없음 — 이벤트 도입 전 run 포함) */
  email_status: "sent" | "failed" | null;
  email_error: string | null;
  /** 어떤 모델이 썼나 — writer 교체가 잦아 품질 비교에 필요(2026-08-26) */
  writer_model: string | null;
  /** 본문 분량(자) */
  report_chars: number | null;
  /** 본문에 실제 인용된 출처 수 */
  cites_used: number | null;
  /** 생성 소요(초) — 분 단위 표시는 화면에서 */
  elapsed_s: number | null;
  /** 내부 트래픽(e2e·벤치·야간회귀) — scope=all 일 때만 목록에 나온다 */
  internal: boolean;
  started_at: string | null;
  finished_at: string | null;
};

export type AdminReportRunList = {
  count: number;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  runs: AdminReportRun[];
};

/** GET /admin/reports — 보고서 run 목록(최근 시작순): 상태·실패 사유·발송 결과. */
export async function getAdminReports(
  limit = 50,
  offset = 0,
  scope: "real" | "all" = "real",
  tab: "deep" | "doc" | "irb" | "all" = "deep",
): Promise<AdminReportRunList> {
  return apiFetch<AdminReportRunList>(
    `/admin/reports?limit=${limit}&offset=${offset}&scope=${scope}&tab=${tab}`,
  );
}

/** 보고서 본문(마크다운) + 인용 요약 — 관리자 화면에서 바로 읽기(2026-08-26). */
export type AdminReportContent = {
  report_id: string;
  thread_id: string;
  title: string | null;
  status: string;
  kind: string;
  created_at: string | null;
  chars: number;
  citation_count: number;
  citations: Array<{
    number: number | null;
    title: string | null;
    publisher: string | null;
    url: string | null;
    verified: boolean | null;
  }>;
  markdown: string;
};

export async function getAdminReportContent(
  reportId: string,
): Promise<AdminReportContent> {
  return apiFetch<AdminReportContent>(
    `/admin/reports/${encodeURIComponent(reportId)}/content`,
  );
}

export type AdminThreadMessage = {
  id: string | null;
  /** human | ai | tool */
  type: string | null;
  content: string;
  /** tool 호출 이름(있을 때) */
  tool_calls?: string[];
  /** 저장 시각(ISO) — 2026-09-15 */
  created_at?: string;
  /** 최종 AI 답변에만: 사용자 질문 저장 → 답변 완성까지 초 */
  elapsed_s?: number;
};

/** 턴 요약 — human 질문부터 최종 AI 답변까지 */
export type AdminThreadTurn = {
  human_id: string | null;
  ai_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  elapsed_s: number;
};

export type AdminThreadDetail = AdminUserFields & {
  thread_id: string;
  user_id: string | null;
  title: string | null;
  created_at: string | null;
  updated_at: string | null;
  messages: AdminThreadMessage[];
  /** 턴별 소요시간(백엔드 계산) — 구버전 응답엔 없음 */
  turns?: AdminThreadTurn[];
  steps: unknown[];
  selected_law_keys: string[];
};

/** GET /admin/threads/{id} — 특정 thread 전체 대화 원문(PII 마스킹본). */
export async function getAdminThread(
  threadId: string,
): Promise<AdminThreadDetail> {
  return apiFetch<AdminThreadDetail>(
    `/admin/threads/${encodeURIComponent(threadId)}`,
  );
}

/* ─────────────────── Admin · 무인용 사실 audit(환각률) ─────────────────── */

export type AdminClaimAuditSample = {
  ts: string;
  thread_id: string | null;
  /** supported | contradicted | unverified */
  verdict: string | null;
  claim: string | null;
};

export type AdminClaimAudit = {
  days: number;
  turns_audited: number;
  unique_users: number;
  total_claims: number;
  supported: number;
  contradicted: number;
  unverified: number;
  supported_rate: number | null;
  unsupported_rate: number | null;
  samples: AdminClaimAuditSample[];
};

/** GET /admin/stats/claim-audit?days= — 무인용 사실 검증 집계(환각률). */
export async function getAdminClaimAudit(
  days = 30,
  scope: DataScope = "real",
): Promise<AdminClaimAudit> {
  return apiFetch<AdminClaimAudit>(
    `/admin/stats/claim-audit?days=${days}&scope=${scope}`,
  );
}

/** 회원 비활성화(소프트삭제) — 접근 즉시 차단. 복구는 restoreUser. */
export async function softDeleteUser(userId: string): Promise<void> {
  await apiFetch(`/admin/users/${encodeURIComponent(userId)}/soft-delete`, {
    method: "POST",
  });
}

export async function restoreUser(userId: string): Promise<void> {
  await apiFetch(`/admin/users/${encodeURIComponent(userId)}/restore`, {
    method: "POST",
  });
}

/** 공지 메일 수신자 프리셋.
 *  - all: 활성 회원 전체 · admins: 관리자만(테스트 발송용)
 *  - whitelisted: 화이트리스트로 허용된 **가입 회원**
 *  - beta_testers: 화이트리스트 항목 전체(미가입 초대자 포함, @도메인 제외)
 */
export type NotifyAudience = "all" | "admins" | "whitelisted" | "beta_testers";

export type NotifyResult = {
  requested: number;
  sent: number;
  failed?: string[];
  recipients?: string[];
  dry_run?: boolean;
  /** false 면 backend SMTP 미설정 — sent 는 stub 로그 수일 뿐 실제 발송이 아님 */
  smtp_configured?: boolean;
};

export type NotifyPayload = {
  subject: string;
  body: string;
  body_html?: string;
  to?: NotifyAudience | string[];
  dry_run?: boolean;
  /** "branded"(기본, 서비스 테마 HTML) | "plain" */
  template?: "branded" | "plain";
  cta_url?: string;
  cta_label?: string;
  /** 회신 주소(Reply-To). 미지정 시 서버 NOTICE_REPLY_TO */
  reply_to?: string;
  /** ISO8601(UTC Z) — 주면 즉시 발송 대신 예약 */
  send_at?: string;
};

/** 공지 이메일. dry_run=true 면 발송 없이 수신자 목록만 확인(발송 전 필수 점검). */
export async function adminNotify(
  body: NotifyPayload,
): Promise<NotifyResult & { scheduled?: boolean; notice?: ScheduledNotice }> {
  return apiFetch(`/admin/notify`, { method: "POST", body: JSON.stringify(body) });
}

/** 발송·예약 없이 렌더된 HTML 만 — 템플릿 확인용. */
export async function previewNotice(body: {
  subject: string;
  body: string;
  cta_url?: string;
  cta_label?: string;
}): Promise<string> {
  const r = await apiFetch<{ html: string }>(`/admin/notify`, {
    method: "POST",
    body: JSON.stringify({ ...body, preview: true }),
  });
  return r.html;
}

export type ScheduledNotice = {
  id: string;
  subject: string;
  body: string;
  to: NotifyAudience | string[];
  send_at: string;
  /** pending | sending | sent | skipped */
  status: string;
  created_by: string | null;
  created_at: string;
  sent_at: string | null;
  result: { requested?: number; sent?: number; failed?: string[]; reason?: string } | null;
};

export async function listScheduledNotices(): Promise<ScheduledNotice[]> {
  const r = await apiFetch<{ items: ScheduledNotice[] }>("/admin/notify/scheduled");
  return r.items ?? [];
}

export async function cancelScheduledNotice(id: string): Promise<void> {
  await apiFetch(`/admin/notify/scheduled/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/* ─────────────── Admin · PII 마스킹 라벨링 (2026-08-13) ─────────────── */

/** 파생 상태 — unlabeled(자동 수집·미라벨) | reported(신고됨·즉시 적용 중)
 *  | correct(정탐 확정) | wrong(오탐 확정) */
export type PiiTermStatus = "unlabeled" | "reported" | "correct" | "wrong";

export type PiiTermItem = {
  term: string;
  status: PiiTermStatus;
  /** 현재 마스킹 제외 중인가 (wrong 또는 신고됨·미라벨) */
  unmasked: boolean;
  placeholder: string | null;
  /** 마스킹 관측 수(자동 수집) */
  count: number;
  reported: boolean;
  report_count: number;
  label: "correct" | "wrong" | null;
  comment: string | null;
  created_at: string | null;
  last_seen_at: string | null;
  labeled_at: string | null;
  labeled_by: string | null;
};

/** GET /admin/pii-terms — 마스킹 단어 개선리스트(최신 관측순). */
export async function listPiiTerms(opts?: {
  status?: PiiTermStatus;
  reportedOnly?: boolean;
}): Promise<{ count: number; items: PiiTermItem[] }> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.reportedOnly) params.set("reported_only", "true");
  const qs = params.toString();
  return apiFetch(`/admin/pii-terms${qs ? `?${qs}` : ""}`);
}

/** 라벨링 — correct(진짜 개인정보, 마스킹 유지·복귀) / wrong(오탐, 영구 제외). */
export async function labelPiiTerm(
  term: string,
  label: "correct" | "wrong",
): Promise<PiiTermItem & { ok: boolean }> {
  return apiFetch(`/admin/pii-terms/${encodeURIComponent(term)}`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

/** 목록에서 제거 — wrong 이었다면 즉시 다시 마스킹 대상. */
export async function removePiiTerm(term: string): Promise<void> {
  await apiFetch(`/admin/pii-terms/${encodeURIComponent(term)}`, {
    method: "DELETE",
  });
}

/* ─────────────── Admin · 패치노트 공지 (2026-08-13) ─────────────── */

export type Announcement = {
  id: string;
  /** 표기용 배포일 "YYYY-MM-DD" */
  date: string;
  title: string;
  /** 릴리스 표기(선택) — "v0.8.0" */
  version?: string | null;
  /** 기능 영역(선택) — 게시판 탭·배지 */
  feature?: string | null;
  items: string[];
  created_at: string | null;
  created_by: string | null;
  /** 숨김(2026-08-28) — 게시판·팝업 모두에서 내림(기록은 남음). */
  hidden?: boolean;
  /** 팝업 노출(2026-09-18) — false 면 게시판에만 쌓고 로그인 팝업은 안 띄운다. 미지정=true */
  popup?: boolean;
};

/** 발행 — GET /announcements/latest 가 바뀌고 사용자 최초 접속 팝업에 노출. */
export async function publishAnnouncement(body: {
  title: string;
  items: string[];
  date?: string;
  /** 릴리스 표기(선택, ≤20자) — "v0.8.0" */
  version?: string;
  /** 기능 영역(선택, ≤30자) — ANNOUNCEMENT_FEATURES 권장 */
  feature?: string;
  /** false = 게시판 전용(팝업 없음) */
  popup?: boolean;
}): Promise<Announcement> {
  const r = await apiFetch<{ ok: boolean; announcement: Announcement }>(
    "/admin/announcements",
    { method: "POST", body: JSON.stringify(body) },
  );
  return r.announcement;
}

/** 발행 이력 전체(최신순, 숨김 포함, 최대 100) — GET /admin/announcements.
 *  사용자 라우트 GET /announcements 는 2026-09-02 부터 공개+숨김 제외라 admin 은 못 쓴다. */
export async function listAnnouncements(
  limit = 100,
): Promise<Announcement[]> {
  const r = await apiFetch<{ count: number; items: Announcement[] }>(
    `/admin/announcements?limit=${limit}`,
  );
  return r.items ?? [];
}

/** 노출 금지/재노출 — 삭제와 구분되는 철회 옵션. */
export async function setAnnouncementHidden(noteId: string, hidden: boolean): Promise<void> {
  await apiFetch(`/admin/announcements/${encodeURIComponent(noteId)}`, {
    method: "PATCH",
    body: JSON.stringify({ hidden }),
  });
}

/** 팝업만 켜고 끈다 — 게시판 노출(hidden)과 독립. */
export async function setAnnouncementPopup(noteId: string, popup: boolean): Promise<void> {
  await apiFetch(`/admin/announcements/${encodeURIComponent(noteId)}`, {
    method: "PATCH",
    body: JSON.stringify({ popup }),
  });
}

export async function deleteAnnouncement(noteId: string): Promise<void> {
  await apiFetch(`/admin/announcements/${encodeURIComponent(noteId)}`, {
    method: "DELETE",
  });
}

export type FeedbackDigest = {
  days: number;
  to: string | null;
  sent: boolean;
  counts: { thumbs_up: number; thumbs_down: number; citation_reports: number; comments: number };
  summary: string;
};

/** 기간 피드백 취합 → 이메일 발송(+요약 반환). */
export async function feedbackDigest(days = 7, to?: string): Promise<FeedbackDigest> {
  return apiFetch(`/admin/feedback/digest`, {
    method: "POST",
    body: JSON.stringify({ days, ...(to ? { to } : {}) }),
  });
}

/** 사용자별 앱 내 알림 발송(2026-09-15) — POST /admin/notices. 최초 접속 1회 팝업으로 수신자에게만. */
export async function sendUserNotices(body: {
  user_ids: string[];
  title: string;
  items: string[];
  date?: string;
}): Promise<{ ok: boolean; count: number }> {
  return apiFetch("/admin/notices", { method: "POST", body: JSON.stringify(body) });
}

/* ─────────────────── Admin · 답변 검수(2026-09-17) ─────────────────── */

export type ReviewVerdict = "correct" | "partial" | "wrong" | "unratable";

export type ReviewQueueItem = AdminUserFields & {
  thread_id: string;
  user_id: string | null;
  thread_title: string | null;
  message_id: string;
  started_at: string | null;
  question: string;
  answer_preview: string;
  /** rag | skill(기관 지침 스킬 — 인용 축 미적용) */
  lane: "rag" | "skill";
  signals: string[];
  priority: number;
  /** 신호와 무관하게 해시로 뽑힌 표본 — 이 집합의 채점만 정답률 추정에 쓰인다 */
  random_sample: boolean;
  reviewed: boolean;
  citations_retrieved: number;
  citations_used: number;
  verified_rate: number | null;
  claim_samples: { claim?: string; verdict?: string }[];
  identifier_audit: {
    unsupported: string[];
    placeholders: string[];
    source_forms: string[];
  } | null;
  searches: { query: string | null; hit_count: number | null }[];
};

export type ReviewQueue = {
  days: number;
  random_pct: number;
  threads_scanned: number;
  threads_capped: boolean;
  turns_scanned: number;
  queue_total: number;
  signal_counts: Record<string, number>;
  items: ReviewQueueItem[];
  verdicts: ReviewVerdict[];
  error_types: string[];
};

/** GET /admin/review-queue — 위험 신호 점수순 + 무작위 표본. */
export async function getReviewQueue(opts: {
  days?: number;
  limit?: number;
  includeReviewed?: boolean;
  scope?: DataScope;
}): Promise<ReviewQueue> {
  const q = new URLSearchParams({
    days: String(opts.days ?? 14),
    limit: String(opts.limit ?? 100),
    include_reviewed: opts.includeReviewed ? "true" : "false",
    scope: opts.scope ?? "real",
  });
  return apiFetch<ReviewQueue>(`/admin/review-queue?${q}`);
}

/** POST /admin/reviews — 답변 1건 × 검수자 1행(재채점은 덮어씀). */
export async function saveReview(body: {
  thread_id: string;
  message_id: string;
  verdict: ReviewVerdict;
  error_types: string[];
  note?: string;
}): Promise<{ ok: boolean; review_id: string }> {
  return apiFetch("/admin/reviews", { method: "POST", body: JSON.stringify(body) });
}

export type ReviewAccuracy = {
  n: number;
  strict: number | null;
  strict_ci95: [number, number] | null;
  lenient: number | null;
  lenient_ci95: [number, number] | null;
};

export type ReviewStats = {
  days: number;
  reviewed: number;
  verdicts: Record<string, number>;
  error_types: Record<string, number>;
  /** 무작위 표본만 — 이것만이 서비스 정답률 추정치 */
  accuracy_random: ReviewAccuracy;
  /** 참고(신호 표본이 섞여 실제보다 낮게 나온다) */
  accuracy_all_reviewed: ReviewAccuracy;
};

export type ReviewArchiveItem = {
  id: string;
  thread_id: string;
  message_id: string;
  reviewer: string;
  verdict: ReviewVerdict;
  error_types: string[];
  note: string | null;
  /** 채점 시점의 질문·답변(마스킹 저장본) — 원 대화가 90일 뒤 지워져도 남는다. */
  question_snapshot: string | null;
  answer_snapshot: string | null;
  updated_at: string;
  /** 원 대화가 아직 있는지 — false 면 스냅샷이 유일한 근거. */
  thread_alive: boolean;
};

/** GET /admin/reviews/archive — 채점 내역(스냅샷 포함). */
export async function getReviewArchive(opts: { days?: number; limit?: number; verdict?: string } = {}): Promise<{
  total: number;
  items: ReviewArchiveItem[];
}> {
  const q = new URLSearchParams({ days: String(opts.days ?? 365), limit: String(opts.limit ?? 200) });
  if (opts.verdict) q.set("verdict", opts.verdict);
  return apiFetch(`/admin/reviews/archive?${q}`);
}

/** GET /admin/reviews/stats */
export async function getReviewStats(days = 30): Promise<ReviewStats> {
  return apiFetch<ReviewStats>(`/admin/reviews/stats?days=${days}`);
}

/* ─────────────────── 주간 이용 보고서 메일 (2026-09-21) ─────────────────── */

export type WeeklyReportConfig = {
  enabled: boolean;
  to: string[];
  /** 0=월 … 6=일 */
  weekday: number;
  hour: number;
  /** 항목별 출처 — admin(관리자 화면 저장값) | env(서버 기본값) */
  source: Record<"enabled" | "to" | "weekday" | "hour", "admin" | "env">;
  updated_by?: string | null;
  updated_at?: string | null;
};

export type WeeklyReportStatus = {
  enabled: boolean;
  to: string[];
  send_hour_kst: number;
  send_weekday: number;
  config: WeeklyReportConfig;
  /** 수신자로 고를 수 있는 관리자 메일 */
  admin_email_options: string[];
  smtp_configured: boolean;
  /** 다음 자동 발송 예정(KST ISO) */
  next_run_at: string;
  last_week: { week_start: string; sent: { at: string; to: string[] } | null };
};

export type WeeklyReportSendResult = {
  week_start: string;
  sent: string[];
  failed: string[];
  smtp_configured: boolean;
  subject: string;
  feedback: number;
  attachments: string[];
};

export async function getWeeklyReportStatus(): Promise<WeeklyReportStatus> {
  return apiFetch<WeeklyReportStatus>("/admin/weekly-report/status");
}

/** 발송될 HTML 그대로 — 새 탭 미리보기용 */
export async function getWeeklyReportPreview(weekStart?: string): Promise<string> {
  return apiFetchText(
    `/admin/weekly-report/preview${weekStart ? `?week_start=${weekStart}` : ""}`,
  );
}

/** 지금 보내기(수동) — 자동 발송 기록은 건드리지 않음 */
export async function sendWeeklyReportNow(weekStart?: string): Promise<WeeklyReportSendResult> {
  return apiFetch<WeeklyReportSendResult>("/admin/weekly-report/send", {
    method: "POST",
    body: JSON.stringify(weekStart ? { week_start: weekStart } : {}),
  });
}

/** 자동 발송 설정 저장 — 준 항목만, null = 그 항목 서버 기본값으로, reset = 전부 기본값 */
export async function patchWeeklyReportConfig(body: {
  enabled?: boolean | null;
  to?: string[] | null;
  weekday?: number | null;
  hour?: number | null;
  reset?: boolean;
}): Promise<WeeklyReportStatus> {
  return apiFetch<WeeklyReportStatus>("/admin/weekly-report/config", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/* ─────────────────── 보고 노트 — 관리자 전용 (2026-09-21) ─────────────────── */

/** 주간 보고 메일 "이번 주 업데이트"의 원천. 사용자 공지(/updates)와 분리 — 사용자에게 안 보인다. */
export type ReportNote = {
  id: string;
  /** 업데이트 날짜(KST, YYYY-MM-DD) — 이 날짜가 속한 주의 보고 메일에 실림 */
  date: string;
  title: string;
  items: string[];
  feature: string | null;
  /** false = 보고 메일에서 뺌(노트는 남음) */
  include: boolean;
  refs?: string[];
  created_by?: string | null;
  created_at?: string;
  updated_at?: string | null;
  updated_by?: string | null;
};

export async function listReportNotes(since?: string, until?: string): Promise<{ notes: ReportNote[]; features: string[] }> {
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  if (until) qs.set("until", until);
  const q = qs.toString();
  return apiFetch(`/admin/report-notes${q ? `?${q}` : ""}`);
}

export async function addReportNote(body: {
  title: string;
  items: string[];
  feature?: string | null;
  date?: string;
  include?: boolean;
}): Promise<ReportNote> {
  return apiFetch<ReportNote>("/admin/report-notes", { method: "POST", body: JSON.stringify(body) });
}

export async function patchReportNote(
  id: string,
  body: Partial<Pick<ReportNote, "title" | "items" | "feature" | "date" | "include">>,
): Promise<ReportNote> {
  return apiFetch<ReportNote>(`/admin/report-notes/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteReportNote(id: string): Promise<{ ok: boolean }> {
  return apiFetch(`/admin/report-notes/${encodeURIComponent(id)}`, { method: "DELETE" });
}

/** PII 라벨링 문맥(2026-09-21) — 가린 질문의 앞뒤. 원문은 저장되지 않아 가림 자리 주변만 보인다. */
export type PiiTermContext = {
  term: string;
  placeholder: string | null;
  contexts: {
    thread_id: string;
    message_id: string | null;
    created_at: string | null;
    before: string;
    mark: string;
    after: string;
    /** 같은 질문 안 같은 종류 가림 수 — 2 이상이면 어느 자리인지 특정 불가(exact=false 일 때) */
    same_kind: number;
    /** true = 마스킹 시점에 찾아 둔 이 단어의 정확한 자리(2026-09-21 이후 관측분) */
    exact: boolean;
  }[];
  /** 자리 미기록 옛 항목 — 같은 질문에서 같은 종류로 함께 가려진 다른 단어 */
  siblings: string[];
  /** 기록된 대화 중 이미 지워진 수(90일 정리 등) */
  missing_threads: number;
  threads_known: number;
};

export async function getPiiTermContext(term: string): Promise<PiiTermContext> {
  return apiFetch<PiiTermContext>(`/admin/pii-terms/context?term=${encodeURIComponent(term)}`);
}

/* ─────────────── Admin · 기능별 권한 (2026-09-22) ─────────────── */

/** 권한 키 — 정본은 backend `src/admin_perms.py:PERMS`(라벨·설명은 /admin/me 의 catalog). */
export type AdminPerm =
  | "stats"
  | "threads"
  | "reports"
  | "users"
  | "beta"
  | "feedback"
  | "pii"
  | "mail"
  | "announcements"
  | "settings";

export type AdminPermDef = { key: AdminPerm; label: string; desc: string };

export type AdminMe = {
  email: string;
  /** 루트 관리자(ADMIN_EMAILS) — 전 권한 + 다른 관리자 권한 지정 */
  is_root: boolean;
  perms: AdminPerm[];
  catalog: AdminPermDef[];
};

export async function getAdminMe(): Promise<AdminMe> {
  return apiFetch<AdminMe>("/admin/me");
}

/** 관리자 지정·권한 변경(루트만). perms=null → 전 권한. */
export async function setAdminPerms(
  userId: string,
  body: { is_admin?: boolean; admin_perms?: AdminPerm[] | null },
): Promise<AdminUser> {
  return apiFetch<AdminUser>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/* ─────────────── Admin · 뉴스레터 (2026-09-22) ─────────────── */

export type NewsletterMeta = {
  id: string;
  subject: string;
  marketing: boolean;
  created_by: string | null;
  created_at: string;
  updated_by: string | null;
  updated_at: string;
  last_sent_at: string | null;
  /** 성공 수신자 수(테스트 제외, 중복 제거) */
  sent_count: number;
  /** 본 발송 회차 수 */
  send_runs: number;
  source_filename: string | null;
};

export type NewsletterSendRun = {
  id: string;
  at: string;
  by: string | null;
  test: boolean;
  subject: string;
  marketing: boolean;
  requested: number;
  sent: number;
  failed: number;
  smtp_configured: boolean;
  recipients: { email: string; ok: boolean }[];
  skipped: { email: string; reason: string; reason_label: string }[];
};

export type Newsletter = NewsletterMeta & {
  body_html: string;
  body_text: string;
  reply_to: string | null;
  sends?: NewsletterSendRun[];
};

export type NewsletterDraft = {
  subject: string;
  body_html?: string;
  body_text?: string;
  marketing?: boolean;
  reply_to?: string | null;
  source_filename?: string | null;
};

export type NewsletterRecipient = {
  email: string;
  user_id: string | null;
  /** false = 미가입 베타 초대자 */
  member: boolean;
  display_name: string | null;
  affiliation: string | null;
  admin_memo: string | null;
  account_class: AccountClass | null;
  account_class_label: string;
  is_internal: boolean;
  notice_opt_in: boolean;
  marketing_opt_in: boolean;
  /** false 면 선택 불가(목록만) — 서버도 발송 시 다시 거른다 */
  eligible: boolean;
  reason: string | null;
  reason_label: string | null;
  /** 이 뉴스레터를 이미 받은 시각(newsletter_id 를 줬을 때) */
  received_at: string | null;
};

export async function listNewsletters(): Promise<NewsletterMeta[]> {
  const r = await apiFetch<{ items: NewsletterMeta[] }>("/admin/newsletters");
  return r.items ?? [];
}

export async function getNewsletter(id: string): Promise<Newsletter> {
  return apiFetch<Newsletter>(`/admin/newsletters/${encodeURIComponent(id)}`);
}

export async function createNewsletter(body: NewsletterDraft): Promise<Newsletter> {
  const r = await apiFetch<{ newsletter: Newsletter }>("/admin/newsletters", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return r.newsletter;
}

export async function updateNewsletter(id: string, body: NewsletterDraft): Promise<Newsletter> {
  const r = await apiFetch<{ newsletter: Newsletter }>(
    `/admin/newsletters/${encodeURIComponent(id)}`,
    { method: "PUT", body: JSON.stringify(body) },
  );
  return r.newsletter;
}

export async function deleteNewsletter(id: string): Promise<void> {
  await apiFetch(`/admin/newsletters/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function previewNewsletter(
  body: NewsletterDraft,
): Promise<{ subject: string; html: string; text: string; from: string | null; reply_to: string | null }> {
  return apiFetch("/admin/newsletters/preview", { method: "POST", body: JSON.stringify(body) });
}

export async function listNewsletterRecipients(
  marketing: boolean,
  newsletterId?: string,
): Promise<{ count: number; eligible: number; recipients: NewsletterRecipient[] }> {
  const qs = new URLSearchParams({ marketing: String(marketing) });
  if (newsletterId) qs.set("newsletter_id", newsletterId);
  return apiFetch(`/admin/newsletters/recipients?${qs.toString()}`);
}

export async function sendNewsletter(
  id: string,
  body: { emails: string[] } | { test: true },
): Promise<NewsletterSendRun> {
  const r = await apiFetch<{ run: NewsletterSendRun }>(
    `/admin/newsletters/${encodeURIComponent(id)}/send`,
    { method: "POST", body: JSON.stringify(body) },
  );
  return r.run;
}


/** 운영진 기능 설명서(2026-09-23) — 원본 docs/product/ops_feature_manual.md. 모든 관리자. */
export async function getOpsManual(): Promise<{ markdown: string; updated_at: string }> {
  return apiFetch("/admin/ops-manual");
}
