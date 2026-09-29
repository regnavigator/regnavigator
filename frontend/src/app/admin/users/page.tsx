"use client";

/**
 * Admin · 사용자 관리 — backend `/admin/users` 사용.
 *
 * - 목록 (페이지네이션)
 * - 행 클릭 → 한도 PATCH dialog
 * - is_admin 사용자만 접근 가능 (page-side guard, 일반 유저는 / 로 redirect)
 */

import { ROOT_ADMIN_EMAIL } from "@/lib/site";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ACCOUNT_CLASS_LABEL, getUserUsage, listUsersWithGate, patchUser, restoreUser, softDeleteUser, type AccountClass, type AdminPerm, type AdminUser } from "@/lib/client/admin";
import { useAdminPerms } from "@/components/admin/admin-perms";
import { AdminMemoCell } from "@/components/admin/AdminMemoCell";
import { AccountClassCell } from "@/components/admin/AccountClassCell";
import { NoticeComposer } from "@/components/admin/notice-composer";
import { UserNoticeComposer } from "@/components/admin/user-notice-composer";
import { ErrorBanner, PillTab, fmt } from "@/components/admin/common";
import { useConfirm } from "@/components/admin/use-confirm";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

const PAGE_SIZE = 50;

/* 액션 아이콘 — 텍스트 버튼이 좁은 열에서 세로로 꺾여 아이콘으로 압축(2026-08-28).
 * 라이브러리 미사용 프로젝트라 인라인 SVG. 의미는 title/aria-label 로 전달. */
const _ic = { width: 15, height: 15, viewBox: "0 0 24 24", fill: "none",
  stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" } as const;
function IconEye() {
  return (
    <svg {..._ic} aria-hidden>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function IconEdit() {
  return (
    <svg {..._ic} aria-hidden>
      <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
    </svg>
  );
}
function IconRestore() {
  return (
    <svg {..._ic} aria-hidden>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
    </svg>
  );
}
function IconBan() {
  return (
    <svg {..._ic} aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="m5.6 5.6 12.8 12.8" />
    </svg>
  );
}

/** 목록 필터 — 클라이언트 측(현재 로드된 페이지 기준). */
type Filter =
  | "all"
  | "real"
  | "test"
  | "whitelisted"
  | "not_whitelisted"
  | "admins"
  | "inactive"
  | "profile_missing";

const FILTER_LABEL: Record<Filter, string> = {
  all: "전체",
  real: "실사용자",
  test: "테스트",
  whitelisted: "화이트리스트",
  not_whitelisted: "미등록",
  profile_missing: "프로필 미입력",
  admins: "관리자",
  inactive: "비활성",
};

function matchesFilter(u: AdminUser, f: Filter): boolean {
  switch (f) {
    // 계정 구분(2026-09-21) — backend 유효 판정(관리자 라벨 > 자동). 통계의 "실사용"과 같은 집합.
    case "real":
      return accountClassOf(u) === "user";
    case "test":
      return accountClassOf(u) === "test";
    case "whitelisted":
      return !!u.whitelisted;
    case "not_whitelisted":
      return !u.whitelisted;
    case "admins":
      // 관리자 = 내부 계정(2026-09-22 운영진 통합) — 루트(ADMIN_EMAILS)도 포함
      return u.is_admin || !!u.is_root_admin || accountClassOf(u) === "staff";
    case "inactive":
      return !!u.deleted_at;
    case "profile_missing":
      return !u.display_name && !u.affiliation && !u.job_role && !u.deleted_at;
    default:
      return true;
  }
}

function accountClassOf(u: AdminUser): AccountClass {
  return u.account_class ?? (u.is_test_account ? "test" : "user");
}

/** 가입일 — "2026-08-02" + 상대(3일 전). ISO 파싱 실패 시 원문. */
function fmtJoined(iso?: string | null): { date: string; rel: string } {
  if (!iso) return { date: "—", rel: "" };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { date: String(iso).slice(0, 10), rel: "" };
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  const rel =
    days <= 0 ? "오늘" : days === 1 ? "어제" : days < 30 ? `${days}일 전`
      : days < 365 ? `${Math.floor(days / 30)}개월 전` : `${Math.floor(days / 365)}년 전`;
  return { date: d.toISOString().slice(0, 10), rel };
}

/** 최근 접속 — 상대시간 위주(오늘 안이면 시간 단위). updated_at 은 인증 미들웨어가
 *  매 요청 갱신하는 값(≈최종 접속. 관리자 편집도 갱신하므로 근사치). */
function fmtLastSeen(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const mins = Math.floor((Date.now() - d.getTime()) / 60_000);
  if (mins < 1) return "방금";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}일 전`;
  return d.toISOString().slice(0, 10);
}

/** 화이트리스트 출처 배지 문구 — backend 의 whitelist_source 를 사람 말로. */
function sourceLabel(src?: string | null): string | null {
  if (!src) return null;
  if (src === "admin") return "관리자";
  if (src === "env") return "env";
  if (src === "db") return "초대";
  if (src.startsWith("domain:")) return `도메인 ${src.slice(7)}`;
  return src;
}

export default function AdminUsersPage() {
  const { confirm, confirmDialog } = useConfirm();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [detailUser, setDetailUser] = useState<AdminUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gateActive, setGateActive] = useState<boolean | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  // 정렬(2026-09-08 요청 "최신순 정렬") — 기본 최근 접속 최신순. 로드된 목록 안에서 정렬.
  const [sort, setSort] = useState<{ key: "joined" | "seen"; dir: "asc" | "desc" }>({ key: "seen", dir: "desc" });
  // 서버측 검색어 — 타이핑 멈추고 350ms 뒤 DB 검색으로 재조회(전체 사용자 대상).
  // query 는 그동안 로드된 행에 즉시 필터(체감 반응성), debouncedQ 가 진실원.
  const [debouncedQ, setDebouncedQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(query.trim()), 350);
    return () => clearTimeout(t);
  }, [query]);
  // 선택 발송 — 체크한 사용자 id 집합(비활성 회원은 체크해도 발송에서 제외).
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { can, isRoot } = useAdminPerms();
  const [composing, setComposing] = useState(false);
  const [appNotice, setAppNotice] = useState(false);

  const reload = useCallback(async (reset: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const next = reset ? 0 : offset;
      const { users: list, gate_active } = await listUsersWithGate(PAGE_SIZE, next, "all", debouncedQ);
      setGateActive(gate_active);
      setUsers((prev) => (reset ? list : [...prev, ...list]));
      setHasMore(list.length === PAGE_SIZE);
      if (reset) setOffset(0);
    } catch (err) {
      console.error("[admin] list failed", err);
      setError("사용자 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [offset, debouncedQ]);

  // 최초 로드 + 검색어 확정 시 재조회.
  useEffect(() => {
    void reload(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ]);

  async function loadMore() {
    if (loading || !hasMore) return;
    const newOffset = offset + PAGE_SIZE;
    setOffset(newOffset);
    setLoading(true);
    try {
      const { users: list } = await listUsersWithGate(PAGE_SIZE, newOffset, "all", debouncedQ);
      setUsers((prev) => [...prev, ...list]);
      setHasMore(list.length === PAGE_SIZE);
    } catch (err) {
      console.error("[admin] loadMore failed", err);
      setError("더 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function applyPatch(userId: string, body: Parameters<typeof patchUser>[1]) {
    try {
      const updated = await patchUser(userId, body);
      // PATCH 응답은 `{ **as_dict, effective_* }` — list 행과 달리 `usage`
      // nested가 없음. 통째 교체하면 u.usage가 undefined가 되어 테이블
      // 렌더(u.usage.*)가 throw → 에러 바운더리. 변경 필드만 *머지*해
      // 기존 usage 보존.
      setUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, ...updated } : u)),
      );
      setEditing(null);
    } catch (err) {
      console.error("[admin] patch failed", err);
      setError("저장에 실패했습니다.");
    }
  }

  // 선택 사용자 구분 일괄 지정 — 한 명씩 PATCH(목록 크기가 작고 실패 행을 알 수 있게).
  const [bulkBusy, setBulkBusy] = useState(false);
  async function applyBulkClass(c: AccountClass | "auto") {
    const ids = users.filter((u) => selected.has(u.id)).map((u) => u.id);
    const label = c === "auto" ? "자동 판정" : ACCOUNT_CLASS_LABEL[c];
    const ok = await confirm({
      title: `${ids.length}명을 '${label}'(으)로 지정할까요?`,
      description:
        c === "staff"
          ? "관리자로 지정합니다(기능 권한 없음 — 필요하면 편집에서 켜세요). 실사용 통계에서 빠집니다. 이미 관리자인 계정은 그대로이며, 관리자의 테스트·실사용자 지정은 건너뜁니다."
          : c === "user" || c === "auto"
            ? "실사용 통계에 포함될 수 있습니다(관리자 계정은 건너뜀). 이미 저장된 주간 통계는 '다시 계산'해야 반영됩니다."
            : "실사용 통계·이용 조회·검수 큐에서 빠집니다(관리자 계정은 건너뜀). 이미 저장된 주간 통계는 '다시 계산'해야 반영됩니다.",
      confirmLabel: "지정",
    });
    if (!ok) return;
    setBulkBusy(true);
    try {
      for (const id of ids) {
        const u = users.find((x) => x.id === id);
        // 관리자는 구분이 권한으로 정해진다 — 테스트·실사용자 지정 대상에서 뺀다
        if (u && (u.is_admin || u.is_root_admin)) continue;
        await applyPatch(id, { account_class: c });
      }
    } finally {
      setBulkBusy(false);
    }
  }

  const q = query.trim().toLowerCase();
  // 클라 측 즉시 필터 — 이메일 + 프로필(이름·소속·직군)도 대상(서버 검색은 이메일만).
  const visible = users
    .filter(
      (u) =>
        matchesFilter(u, filter) &&
        (!q ||
          [u.email, u.display_name, u.affiliation, u.job_role].some((v) =>
            (v ?? "").toLowerCase().includes(q),
          )),
    )
    .sort((a, b) => {
      const ka = sort.key === "joined" ? a.created_at : a.updated_at;
      const kb = sort.key === "joined" ? b.created_at : b.updated_at;
      const ta = ka ? Date.parse(ka) : 0;
      const tb = kb ? Date.parse(kb) : 0;
      return sort.dir === "desc" ? tb - ta : ta - tb;
    });
  const toggleSort = (key: "joined" | "seen") =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }));
  const sortMark = (key: "joined" | "seen") =>
    sort.key === key ? (sort.dir === "desc" ? " ↓" : " ↑") : "";
  // 발송 대상 — 체크했더라도 비활성 계정은 뺀다(어차피 backend 도 거른다).
  const selectedEmails = users
    .filter((u) => selected.has(u.id) && !u.deleted_at && u.email)
    .map((u) => u.email);
  const allVisibleChecked =
    visible.length > 0 && visible.every((u) => selected.has(u.id));

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <main className="flex flex-col gap-6">
      <header>
        <h1 className="text-h1 text-md-on-surface">사용자 관리</h1>
        <p className="mt-1 text-body-sm text-md-on-surface-variant">
          {gateActive === null ? (
            "베타 게이트 확인 중…"
          ) : gateActive ? (
            <>클로즈 베타 <span className="font-semibold text-md-primary">활성</span> — 화이트리스트 회원만 이용 가능</>
          ) : (
            <>클로즈 베타 <span className="font-semibold text-md-error">비활성</span> — 전면 허용 중</>
          )}
        </p>
      </header>

      <ErrorBanner message={error} />

      {/* 필터: 로드된 행 기준 pill. 검색: 서버측(전체 사용자 대상, 디바운스). */}
      <div className="flex flex-wrap items-center gap-2">
        {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
          <PillTab
            key={f}
            active={filter === f}
            label={FILTER_LABEL[f]}
            count={users.filter((u) => matchesFilter(u, f)).length}
            onClick={() => setFilter(f)}
          />
        ))}
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="이메일 검색 (전체 사용자)"
          className="ml-auto h-8 w-56 rounded-input border border-md-outline-variant bg-md-surface px-3 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
        />
      </div>

      {/* 선택 발송 바 — 체크가 하나라도 있으면 뜬다. */}
      {selectedEmails.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3 rounded-card border border-md-primary bg-md-primary-container/30 px-4 py-2.5">
          <span className="text-body-sm font-semibold text-md-on-surface">
            {selectedEmails.length}명 선택됨
          </span>
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="text-[12px] text-md-on-surface-variant hover:text-md-on-surface"
          >
            선택 해제
          </button>
          {/* 계정 구분 일괄 지정(2026-09-21) — 관리자 지정(권한 없음에서 시작)은 루트만(2026-09-22) */}
          <span className="flex items-center gap-1 text-[12px] text-md-on-surface-variant">
            구분 지정
            {((isRoot ? ["staff", "test", "user", "auto"] : ["test", "user", "auto"]) as (AccountClass | "auto")[]).map((c) => (
              <button
                key={c}
                type="button"
                disabled={bulkBusy}
                onClick={() => void applyBulkClass(c)}
                className="rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11.5px] text-md-on-surface hover:bg-md-surface-container-high disabled:opacity-50"
              >
                {c === "auto" ? "자동" : ACCOUNT_CLASS_LABEL[c]}
              </button>
            ))}
          </span>
          {can("mail") ? (<>
          <button
            type="button"
            onClick={() => setAppNotice(true)}
            className="ml-auto rounded-pill border border-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-primary hover:bg-md-primary-container/40"
            title="선택한 사용자에게만 최초 접속 1회 팝업으로 표시"
          >
            앱 내 알림 보내기
          </button>
          <button
            type="button"
            onClick={() => setComposing(true)}
            className="rounded-pill bg-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-on-primary hover:bg-md-primary-container"
          >
            선택한 {selectedEmails.length}명에게 메일 보내기
          </button>
          </>) : null}
        </div>
      ) : null}

      {appNotice ? (
        <UserNoticeComposer
          userIds={users.filter((u) => selected.has(u.id) && !u.deleted_at).map((u) => u.id)}
          emails={selectedEmails}
          onDone={() => { setAppNotice(false); setSelected(new Set()); }}
          onClose={() => setAppNotice(false)}
        />
      ) : null}

      {composing ? (
        <Dialog open onOpenChange={(o) => (!o ? setComposing(false) : null)}>
          <DialogContent className="max-h-[88vh] overflow-y-auto border border-md-outline-variant bg-md-surface p-6 text-md-on-surface sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle className="text-[18px] font-semibold">선택 발송</DialogTitle>
              <p className="text-body-sm text-md-on-surface-variant">
                {selectedEmails.slice(0, 5).join(", ")}
                {selectedEmails.length > 5 ? ` 외 ${selectedEmails.length - 5}명` : ""}
              </p>
            </DialogHeader>
            <div className="mt-3">
              <NoticeComposer
                mode="explicit"
                emails={selectedEmails}
                onDone={() => { setComposing(false); setSelected(new Set()); }}
              />
            </div>
          </DialogContent>
        </Dialog>
      ) : null}

      <div className="rounded-card border border-md-outline-variant">
        {/* table-fixed: 열 폭 고정 + 사용자 열만 truncate — 가로 스크롤 없음 */}
        <table className="w-full table-fixed text-body-sm">
          <thead className="bg-md-surface-container-low text-[11px] font-semibold uppercase tracking-wide text-md-on-surface-variant">
            <tr>
              <th className="w-9 px-3 py-2 text-left">
                <input
                  type="checkbox"
                  aria-label="보이는 사용자 전체 선택"
                  checked={allVisibleChecked}
                  onChange={(e) =>
                    setSelected((prev) => {
                      const next = new Set(prev);
                      for (const u of visible) {
                        if (e.target.checked) next.add(u.id);
                        else next.delete(u.id);
                      }
                      return next;
                    })
                  }
                />
              </th>
              <th className="whitespace-nowrap px-2.5 py-2 text-left">사용자</th>
              <th className="w-[7.4rem] whitespace-nowrap px-2 py-2 text-left" title="관리자·테스트는 실사용 집계에서 빠집니다">구분</th>
              {/* 폭 확장(2026-09-08): 5.2/4.6rem 에 "2026-08-05 한달 전"이 안 들어가 옆 칸과 겹쳤다 */}
              <th className="w-[6.6rem] whitespace-nowrap px-2.5 py-2 text-left">
                <button type="button" onClick={() => toggleSort("joined")} className="hover:text-md-on-surface" title="가입일 정렬">
                  가입일{sortMark("joined")}
                </button>
              </th>
              <th className="w-[5.8rem] whitespace-nowrap px-2.5 py-2 text-left">
                <button type="button" onClick={() => toggleSort("seen")} className="hover:text-md-on-surface" title="최근 접속 정렬">
                  최근 접속{sortMark("seen")}
                </button>
              </th>
              <th className="w-[8.5rem] whitespace-nowrap px-2.5 py-2 text-left">상태</th>
              <th className="w-[9.5rem] whitespace-nowrap px-2.5 py-2 text-left">메일</th>
              <th className="w-[6.8rem] whitespace-nowrap px-2.5 py-2 text-right">일 사용/한도</th>
              <th className="w-[6.8rem] whitespace-nowrap px-2.5 py-2 text-right">월 사용/한도</th>
              <th className="w-[6.2rem] px-2.5 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((u) => (
              <tr
                key={u.id}
                className={`border-t border-md-outline-variant hover:bg-md-surface-container-low ${
                  u.deleted_at ? "opacity-55" : ""
                }`}
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`${u.email} 선택`}
                    checked={selected.has(u.id)}
                    disabled={!!u.deleted_at}
                    onChange={() => toggle(u.id)}
                  />
                </td>
                <td className="px-2.5 py-2 text-md-on-surface">
                  <div className="flex min-w-0 flex-col leading-tight">
                    <span className={`truncate ${u.deleted_at ? "line-through" : ""}`} title={u.email}>{u.email}</span>
                    {(u.display_name || u.affiliation || u.job_role) ? (
                      <span className="truncate text-[11px] text-md-on-surface-variant">
                        {[u.display_name, u.affiliation, u.job_role]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    ) : !u.deleted_at ? (
                      <span className="w-fit rounded bg-md-tertiary-fixed px-1 text-[10px] font-semibold text-[var(--md-on-tertiary-fixed-variant)]" title="가입 시 프로필(이름·소속·직군)을 입력하지 않음 — 메모로 식별">
                        프로필 미입력
                      </span>
                    ) : null}
                    {/* 관리자 식별 메모(2026-09-15) — 관리자 화면 전용 */}
                    <AdminMemoCell
                      value={u.admin_memo}
                      onSave={(memo) => applyPatch(u.id, { admin_memo: memo })}
                    />
                  </div>
                </td>
                <td className="px-2 py-2">
                  <AccountClassCell
                    user={u}
                    canMakeAdmin={isRoot}
                    onSave={(c) => applyPatch(u.id, { account_class: c })}
                  />
                </td>
                <td className="overflow-hidden text-ellipsis whitespace-nowrap px-2.5 py-2 text-md-on-surface-variant">
                  <span className="tabular-nums">{fmtJoined(u.created_at).date}</span>
                  {fmtJoined(u.created_at).rel ? (
                    <span className="ml-1 text-[10.5px] opacity-70">
                      {fmtJoined(u.created_at).rel}
                    </span>
                  ) : null}
                </td>
                <td
                  className="overflow-hidden text-ellipsis whitespace-nowrap px-2.5 py-2 tabular-nums text-md-on-surface-variant"
                  title={u.updated_at ? fmtJoined(u.updated_at).date : undefined}
                >
                  {fmtLastSeen(u.updated_at)}
                </td>
                <td className="overflow-hidden whitespace-nowrap px-2.5 py-2">
                  {u.deleted_at ? (
                    <span className="inline-flex items-center rounded-pill bg-md-error-container px-2 py-0.5 text-[10.5px] font-semibold text-md-on-error-container">
                      비활성
                    </span>
                  ) : u.whitelisted ? (
                    <span
                      className="inline-flex items-center rounded-pill bg-md-primary-container px-2 py-0.5 text-[10.5px] font-semibold text-md-on-primary-container"
                      title={`화이트리스트 출처: ${u.whitelist_source ?? ""}`}
                    >
                      베타 · {sourceLabel(u.whitelist_source)}
                    </span>
                  ) : (
                    <span
                      className="inline-flex items-center rounded-pill border border-md-outline-variant px-2 py-0.5 text-[10.5px] text-md-on-surface-variant"
                      title={
                        gateActive
                          ? "화이트리스트 미등록 — 게이트 활성이라 로그인해도 차단됩니다."
                          : "화이트리스트 미등록 (게이트 비활성이라 이용은 가능)"
                      }
                    >
                      {gateActive ? "차단" : "미등록"}
                    </span>
                  )}
                  {u.is_admin || u.is_root_admin ? (
                    <span
                      className="ml-1 inline-flex items-center rounded bg-md-tertiary-fixed px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-md-on-tertiary-fixed-variant"
                      title={
                        u.is_root_admin
                          ? "루트 관리자 — 전 권한"
                          : u.admin_perms_all
                            ? "관리자 — 전 권한(미지정)"
                            : `관리자 권한: ${(u.admin_perms_list ?? []).join(", ") || "없음"}`
                      }
                    >
                      {u.is_root_admin ? "Root" : "Admin"}
                      {!u.is_root_admin && !u.admin_perms_all ? (
                        <span className="ml-1 normal-case tracking-normal">{u.admin_perms_list?.length ?? 0}</span>
                      ) : null}
                    </span>
                  ) : null}
                </td>
                <td className="overflow-hidden whitespace-nowrap px-2.5 py-2">
                  {/* 마케팅 동의(최신 동의 기록) — 발송 전 대상 확인(2026-08-28) */}
                  <span
                    title={u.marketing_opt_in ? "마케팅 메일 동의" : "마케팅 메일 미동의"}
                    className={
                      "mr-1 inline-flex items-center rounded-pill px-1.5 py-0.5 text-[10.5px] font-medium " +
                      (u.marketing_opt_in
                        ? "bg-md-primary-container text-md-on-primary-container"
                        : "border border-md-outline-variant text-md-on-surface-variant")
                    }
                  >
                    광고 {u.marketing_opt_in ? "동의" : "—"}
                  </span>
                  <span
                    title={u.report_email_opt_in ? "보고서 완료 메일 수신" : "보고서 완료 메일 끔"}
                    className={
                      "inline-flex items-center rounded-pill px-1.5 py-0.5 text-[10.5px] font-medium " +
                      (u.report_email_opt_in
                        ? "bg-md-surface-container-high text-md-on-surface"
                        : "border border-md-outline-variant text-md-on-surface-variant")
                    }
                  >
                    보고서 {u.report_email_opt_in ? "ON" : "OFF"}
                  </span>
                </td>
                <td
                  className="whitespace-nowrap px-2.5 py-2 text-right tabular-nums"
                  title={
                    u.daily_token_limit_override != null &&
                    u.daily_token_limit_override >= 0
                      ? "일 한도: 개별 override 적용"
                      : undefined
                  }
                >
                  <span className="text-md-on-surface">{fmt(u.usage?.daily_total_tokens ?? 0)}</span>
                  <span className="text-md-on-surface-variant"> / {fmt(u.effective_daily_limit)}</span>
                  {u.daily_token_limit_override != null &&
                  u.daily_token_limit_override >= 0 ? (
                    <span className="ml-0.5 text-[10px] text-md-tertiary">*</span>
                  ) : null}
                </td>
                <td
                  className="whitespace-nowrap px-2.5 py-2 text-right tabular-nums"
                  title={
                    u.monthly_token_limit_override != null &&
                    u.monthly_token_limit_override >= 0
                      ? "월 한도: 개별 override 적용"
                      : undefined
                  }
                >
                  <span className="text-md-on-surface">{fmt(u.usage?.monthly_total_tokens ?? 0)}</span>
                  <span className="text-md-on-surface-variant"> / {fmt(u.effective_monthly_limit)}</span>
                  {u.monthly_token_limit_override != null &&
                  u.monthly_token_limit_override >= 0 ? (
                    <span className="ml-0.5 text-[10px] text-md-tertiary">*</span>
                  ) : null}
                </td>
                <td className="whitespace-nowrap px-2.5 py-2 text-right">
                  <div className="flex items-center justify-end gap-0.5">
                    <button
                      type="button"
                      onClick={() => setDetailUser(u)}
                      title="사용량 상세"
                      aria-label="사용량 상세"
                      className="rounded p-1.5 text-md-on-surface-variant hover:bg-md-surface-container hover:text-md-on-surface"
                    >
                      <IconEye />
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditing(u)}
                      title="한도 편집"
                      aria-label="한도 편집"
                      className="rounded p-1.5 text-md-on-surface-variant hover:bg-md-surface-container hover:text-md-on-surface"
                    >
                      <IconEdit />
                    </button>
                    {(u.email ?? "").toLowerCase() !== ROOT_ADMIN_EMAIL ? (
                      (u as { deleted_at?: string | null }).deleted_at ? (
                        <button
                          type="button"
                          onClick={() => void (async () => {
                            try {
                              await restoreUser(u.id);
                              toast.success("계정 복구됨");
                              setUsers((prev) => prev.map((x) => x.id === u.id ? { ...x, deleted_at: null } as AdminUser : x));
                            } catch { toast.error("복구 실패"); }
                          })()}
                          title="계정 복구"
                          aria-label="계정 복구"
                          className="rounded p-1.5 text-md-secondary hover:bg-md-surface-container"
                        >
                          <IconRestore />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => void (async () => {
                            const ok = await confirm({
                              title: "계정을 비활성화할까요?",
                              description: `${u.email} — 로그인이 즉시 차단됩니다. 복구 가능.`,
                              confirmLabel: "비활성화",
                              danger: true,
                            });
                            if (!ok) return;
                            try {
                              await softDeleteUser(u.id);
                              toast.success("계정 비활성화됨");
                              setUsers((prev) => prev.map((x) => x.id === u.id ? { ...x, deleted_at: new Date().toISOString() } as AdminUser : x));
                            } catch { toast.error("비활성화 실패"); }
                          })()}
                          title="계정 비활성화"
                          aria-label="계정 비활성화"
                          className="rounded p-1.5 text-md-error hover:bg-md-error/10"
                        >
                          <IconBan />
                        </button>
                      )
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
            {visible.length === 0 && !loading ? (
              <tr>
                <td
                  colSpan={9}
                  className="px-3 py-8 text-center text-md-on-surface-variant"
                >
                  {users.length === 0 ? "사용자가 없습니다." : "조건에 맞는 사용자가 없습니다."}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {hasMore ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loading}
            className="rounded border border-md-outline-variant px-4 py-1.5 text-body-sm text-md-on-surface-variant hover:bg-md-surface-container-low disabled:opacity-50"
          >
            {loading ? "불러오는 중..." : "더 보기"}
          </button>
        </div>
      ) : null}

      <EditUserDialog
        user={editing}
        onCancel={() => setEditing(null)}
        onSave={applyPatch}
      />

      <UserUsageDialog
        user={detailUser}
        onClose={() => setDetailUser(null)}
      />

      {confirmDialog}
    </main>
  );
}

/* ─────────────────── Usage detail dialog ─────────────────── */

function UserUsageDialog({
  user,
  onClose,
}: {
  user: AdminUser | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!user) {
      setDetail(null);
      return;
    }
    setLoading(true);
    void getUserUsage(user.id)
      .then((d) => setDetail(d))
      .catch((err) => {
        console.warn("[UserUsageDialog] fetch failed", err);
        setDetail(user); // fallback — list 응답 그대로
      })
      .finally(() => setLoading(false));
  }, [user]);

  if (!user) return null;
  // /usage 상세 응답엔 프로필(display_name 등)이 없다 — list 행 위에 머지해 보존.
  const u = detail ? { ...user, ...detail } : user;
  const dailyPct = u.effective_daily_limit
    ? Math.round((u.usage.daily_total_tokens / u.effective_daily_limit) * 100)
    : 0;
  const monthlyPct = u.effective_monthly_limit
    ? Math.round((u.usage.monthly_total_tokens / u.effective_monthly_limit) * 100)
    : 0;

  return (
    <Dialog open={!!user} onOpenChange={(o) => (!o ? onClose() : null)}>
      <DialogContent className="border border-md-outline-variant bg-md-surface p-7 text-md-on-surface shadow-xl sm:max-w-lg">
        <DialogHeader className="space-y-1">
          <span className="text-[11.5px] font-semibold uppercase tracking-[0.1em] text-md-primary">
            사용량 상세
          </span>
          <DialogTitle className="truncate text-[20px] font-semibold leading-tight tracking-tight text-md-on-surface">
            {u.email}
          </DialogTitle>
          {u.display_name || u.affiliation || u.job_role ? (
            <p className="text-body-sm text-md-on-surface-variant">
              {[u.display_name, u.affiliation, u.job_role]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ) : null}
        </DialogHeader>

        {loading && !detail ? (
          <div className="flex items-center justify-center py-8 text-md-on-surface-variant">
            <span
              className="material-symbols-outlined animate-spin text-[24px]"
              aria-hidden
            >
              progress_activity
            </span>
          </div>
        ) : (
          <div className="mt-4 flex flex-col gap-6">
            <PeriodCard
              label="오늘"
              used={u.usage.daily_total_tokens}
              input={u.usage.daily_input_tokens}
              output={u.usage.daily_output_tokens}
              cost={u.usage.daily_cost_usd}
              limit={u.effective_daily_limit}
              pct={dailyPct}
            />
            <PeriodCard
              label="이번 달"
              used={u.usage.monthly_total_tokens}
              input={u.usage.monthly_input_tokens}
              output={u.usage.monthly_output_tokens}
              cost={u.usage.monthly_cost_usd}
              limit={u.effective_monthly_limit}
              pct={monthlyPct}
            />
          </div>
        )}

        <DialogFooter className="mt-7 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-10 items-center rounded-full px-6 text-[13px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
          >
            닫기
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PeriodCard({
  label,
  used,
  input,
  output,
  cost,
  limit,
  pct,
}: {
  label: string;
  used: number;
  input: number;
  output: number;
  cost: number;
  limit: number;
  pct: number;
}) {
  const barColor = pct >= 95 ? "bg-md-error" : pct >= 80 ? "bg-md-tertiary" : "bg-md-primary";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12px] font-semibold uppercase tracking-[0.08em] text-md-on-surface-variant">
          {label}
        </span>
        <span className="text-[12px] tabular-nums text-md-on-surface-variant">
          {fmt(used)} / {fmt(limit)} ({pct}%)
        </span>
      </div>
      <span className="relative inline-block h-1.5 w-full overflow-hidden rounded bg-md-outline-variant">
        <span
          className={`absolute inset-y-0 left-0 ${barColor} rounded`}
          style={{ width: `${Math.min(100, pct)}%` }}
          aria-hidden
        />
      </span>
      <div className="grid grid-cols-3 gap-3 pt-1 text-[12px]">
        <div className="flex flex-col">
          <span className="text-md-on-surface-variant">입력</span>
          <span className="font-medium tabular-nums text-md-on-surface">
            {fmt(input)}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-md-on-surface-variant">출력</span>
          <span className="font-medium tabular-nums text-md-on-surface">
            {fmt(output)}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-md-on-surface-variant">비용 (USD)</span>
          <span className="font-medium tabular-nums text-md-on-surface">
            ${cost.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────── Edit dialog ─────────────────── */

function EditUserDialog({
  user,
  onCancel,
  onSave,
}: {
  user: AdminUser | null;
  onCancel: () => void;
  onSave: (
    userId: string,
    body: Parameters<typeof patchUser>[1],
  ) => Promise<void>;
}) {
  const [daily, setDaily] = useState<string>("");
  const [monthly, setMonthly] = useState<string>("");
  const [isAdmin, setIsAdmin] = useState(false);
  // 기능별 권한(2026-09-22) — 루트만 편집. allPerms = 권한 미지정(전 권한) 기존 관리자.
  const { me, isRoot, setPreviewPerms } = useAdminPerms();
  const catalog = me?.catalog ?? [];
  const [perms, setPerms] = useState<Set<AdminPerm>>(new Set());
  const [permsDirty, setPermsDirty] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!user) return;
    const d = user.daily_token_limit_override;
    const m = user.monthly_token_limit_override;
    setDaily(d != null && d >= 0 ? String(d) : "");
    setMonthly(m != null && m >= 0 ? String(m) : "");
    setIsAdmin(user.is_admin);
    setPerms(new Set(user.admin_perms_list ?? []));
    setPermsDirty(false);
  }, [user]);

  if (!user) return null;
  const targetRoot = !!user.is_root_admin;
  const togglePerm = (k: AdminPerm) => {
    setPermsDirty(true);
    setPerms((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  async function submit() {
    if (!user) return;
    setSubmitting(true);
    const body: Parameters<typeof patchUser>[1] = {};
    // 관리자 지정·권한은 루트만 바꿀 수 있다 — 바뀐 경우에만 보낸다(비루트의 한도 편집이
    // is_admin 동봉 때문에 403 나지 않게).
    if (isRoot && !targetRoot) {
      if (isAdmin !== user.is_admin) body.is_admin = isAdmin;
      if (isAdmin && (permsDirty || isAdmin !== user.is_admin)) {
        body.admin_perms = catalog.filter((c) => perms.has(c.key)).map((c) => c.key);
      }
    }
    body.daily_token_limit_override =
      daily.trim() === "" ? -1 : parseInt(daily, 10);
    body.monthly_token_limit_override =
      monthly.trim() === "" ? -1 : parseInt(monthly, 10);
    try {
      await onSave(user.id, body);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={!!user} onOpenChange={(o) => (!o ? onCancel() : null)}>
      <DialogContent className="border-md-outline-variant bg-md-surface text-md-on-surface sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-h2">사용자 한도·권한 편집</DialogTitle>
          <p className="text-body-sm text-md-on-surface-variant">
            {user.email}
          </p>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          <label className="flex flex-col gap-1 text-body-sm">
            <span className="text-md-on-surface-variant">
              일 한도 (빈 값 = 시스템 기본 100k)
            </span>
            <input
              type="number"
              inputMode="numeric"
              value={daily}
              onChange={(e) => setDaily(e.target.value)}
              placeholder="기본값"
              className="h-10 rounded border border-md-outline-variant bg-md-surface px-3 text-body-base outline-none focus:border-md-primary"
            />
          </label>
          <label className="flex flex-col gap-1 text-body-sm">
            <span className="text-md-on-surface-variant">
              월 한도 (빈 값 = 시스템 기본 2M)
            </span>
            <input
              type="number"
              inputMode="numeric"
              value={monthly}
              onChange={(e) => setMonthly(e.target.value)}
              placeholder="기본값"
              className="h-10 rounded border border-md-outline-variant bg-md-surface px-3 text-body-base outline-none focus:border-md-primary"
            />
          </label>
          {targetRoot ? (
            <p className="rounded border border-md-outline-variant bg-md-surface-container-low px-3 py-2 text-[12.5px] text-md-on-surface-variant">
              루트 관리자(ADMIN_EMAILS) — 항상 모든 권한을 가집니다.
            </p>
          ) : isRoot ? (
            <fieldset className="flex flex-col gap-2 rounded border border-md-outline-variant px-3 py-2.5">
              <label className="flex items-center gap-2 text-body-sm font-medium">
                <input
                  type="checkbox"
                  checked={isAdmin}
                  onChange={(e) => {
                    setIsAdmin(e.target.checked);
                    // 새로 지정하면 권한 없음에서 시작 — 필요한 기능만 켠다
                    if (e.target.checked && !user.is_admin) setPerms(new Set());
                  }}
                />
                <span>관리자로 지정</span>
              </label>
              {isAdmin ? (
                <div className="flex flex-col gap-1.5 pl-6">
                  <span className="flex items-center gap-2 text-[12px] text-md-on-surface-variant">
                    기능별 권한
                    <button
                      type="button"
                      className="underline underline-offset-2 hover:text-md-on-surface"
                      onClick={() => {
                        setPermsDirty(true);
                        setPerms(new Set(catalog.map((c) => c.key)));
                      }}
                    >
                      전체 선택
                    </button>
                    <button
                      type="button"
                      className="underline underline-offset-2 hover:text-md-on-surface"
                      onClick={() => {
                        setPermsDirty(true);
                        setPerms(new Set());
                      }}
                    >
                      모두 해제
                    </button>
                  </span>
                  {catalog.map((c) => (
                    <label key={c.key} className="flex items-start gap-2 text-body-sm" title={c.desc}>
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={perms.has(c.key)}
                        onChange={() => togglePerm(c.key)}
                      />
                      <span>
                        {c.label}
                        <span className="ml-1.5 text-[11.5px] text-md-on-surface-variant">{c.desc}</span>
                      </span>
                    </label>
                  ))}
                  {perms.size === 0 ? (
                    <p className="text-[11.5px] text-md-error">
                      켜진 권한이 없으면 관리자 화면에서 볼 수 있는 메뉴가 없습니다.
                    </p>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => {
                      setPreviewPerms(catalog.filter((c) => perms.has(c.key)).map((c) => c.key));
                      onCancel();
                    }}
                    className="mt-1 inline-flex w-fit items-center gap-1 rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] hover:bg-md-surface-container-low"
                    title="체크한 권한만 가진 관리자에게 보이는 화면으로 전환(저장과 무관)"
                  >
                    <span className="material-symbols-outlined text-[15px]" aria-hidden>
                      visibility
                    </span>
                    이 권한으로 화면 보기
                  </button>
                </div>
              ) : null}
            </fieldset>
          ) : user.is_admin ? (
            <p className="text-[12.5px] text-md-on-surface-variant">
              관리자 · 권한 {user.admin_perms_all ? "전체" : `${user.admin_perms_list?.length ?? 0}개`} — 권한 변경은
              루트 관리자만 할 수 있습니다.
            </p>
          ) : null}
        </div>
        <DialogFooter className="gap-2">
          <Button
            type="button"
            onClick={onCancel}
            className="h-9 rounded border border-md-outline-variant bg-transparent px-4 text-md-on-surface hover:bg-md-surface-container-low"
          >
            취소
          </Button>
          <Button
            type="button"
            onClick={() => void submit()}
            disabled={submitting}
            className="h-9 rounded bg-md-primary px-4 text-md-on-primary hover:bg-md-primary-container disabled:opacity-50"
          >
            {submitting ? "저장 중..." : "저장"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
