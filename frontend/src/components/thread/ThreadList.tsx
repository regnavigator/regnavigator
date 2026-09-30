"use client";

/**
 * ThreadList — 03 §9, 02 §7, P3.1~P3.7.
 *
 * 사이드바: 새 대화 버튼 + thread 항목 list. 활성은 좌측 2px primary 보더.
 * 인터럽트 배지(`has_interrupt`)는 우측에 빨강 점.
 *
 * 항목 컨텍스트 메뉴 자리만 — P3 단계에선 hover 시 노출되는 inline 액션
 * (rename/delete) 두 개로 단순화.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQueryState } from "nuqs";
import { signOut, useSession } from "next-auth/react";
import { toast } from "sonner";
import {
  Dialog,
  DialogAction,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  deleteThread,
  renameThread,
  searchThreads,
  searchThreadsByContent,
  setThreadPinned,
  type Thread,
} from "@/lib/client/threads";
import { UsageBadge } from "@/components/shell/UsageBadge";
import { useUsage } from "@/lib/store/useUsage";
import { ReportPreviewDialog } from "@/components/chat/ReportPreviewDialog";
import { BookmarksDialog } from "@/components/chat/BookmarksDialog";
import type { Report } from "@/lib/store/types";
import { deleteReport, listReports } from "@/lib/client/reports";
import {
  DOCUMENT_DELETED_EVENT,
  DOCUMENTS_CHANGED_EVENT,
  listDocuments,
  type DocumentListItem,
} from "@/lib/client/documents";
import { useRightPanel } from "@/lib/store/rightPanel";
import { ThemeLogo } from "@/components/shell/ThemeLogo";
import { PrivacyDialog } from "@/components/settings/PrivacyDialog";
import { DocumentsDialog } from "@/components/panel/DocumentsDialog";

type Props = {
  /** Settings 미설정 시 sidebar에 안내. */
  configured: boolean;
  /** Settings 변경시 ThreadList 새로 fetch trigger. */
  refreshKey: number;
  /** 에러 발생 시 위쪽 호스트가 banner 표출하도록 위임. */
  onError: (message: string) => void;
  /** 패널 자체 접기 — 헤더에 ‹ 버튼으로 노출. 미전달 시 버튼 숨김 */
  onCollapse?: () => void;
  /** footer "설정" 버튼 클릭 시 — Header에서 분리, 사이드바 nav 통합 */
  onOpenSettings?: () => void;
  /** 현재 thread의 보고서 — 사이드바 "보고서" 섹션에 표시 */
  currentReports?: import("@/lib/store/types").Report[];
};

const PAGE_SIZE = 50;

export function ThreadList({ configured, refreshKey, onError, onCollapse, onOpenSettings, currentReports }: Props) {
  const { data: session } = useSession();
  const { usage } = useUsage();
  const router = useRouter();
  const userEmail = (session?.user as { email?: string | null } | undefined)?.email ?? null;
  // admin 판별 — NextAuth session(ADMIN_EMAILS env 매칭) 또는 backend usage 응답 둘 중 하나면 OK.
  // backend가 is_admin 안 보내도 ADMIN_EMAILS만 박혀있으면 UI 노출됨.
  const sessionIsAdmin = !!(session?.user as { isAdmin?: boolean } | undefined)?.isAdmin;
  const isAdmin = sessionIsAdmin || !!usage?.is_admin;
  const [threadId] = useQueryState("threadId");
  const [threads, setThreads] = useState<Thread[]>([]);
  // 전체 보고서 — 채팅 선택 없이 좌측에서 전부 노출(사용자 회신 "채팅 안눌러도
  //   전부 볼수있게"). 로드된 thread들에 listReports 병렬 호출 후 합침. LangGraph
  //   custom auth(@auth.on.threads owner filter)가 본인 thread만 반환하므로 user
  //   scope 자동 보장. backend 전역 endpoint 없어 client-side aggregation.
  const [allReports, setAllReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState("");
  // thread 검색 (UX 배치 #10) — 클라이언트 사이드 title 부분일치. 목록 8개 미만이면 입력 숨김.
  const [threadFilter, setThreadFilter] = useState("");
  const [bookmarksOpen, setBookmarksOpen] = useState(false);
  // 본문 검색 매치(백엔드) — 제목 매치와 병합. 검색어 2자↑에서 디바운스 조회.
  const [contentMatches, setContentMatches] = useState<Thread[]>([]);
  useEffect(() => {
    const q = threadFilter.trim();
    if (q.length < 2) {
      setContentMatches([]);
      return;
    }
    const ac = new AbortController();
    const t = window.setTimeout(() => {
      void searchThreadsByContent(q, { signal: ac.signal }).then(setContentMatches);
    }, 300);
    return () => {
      window.clearTimeout(t);
      ac.abort();
    };
  }, [threadFilter]);
  const [pendingDelete, setPendingDelete] = useState<Thread | null>(null);
  const [previewReport, setPreviewReport] = useState<Report | null>(null);
  // 상대 시간 자동 갱신 — 1분 단위. 더 짧으면 렌더 부담, 더 길면 "방금"이 굳음.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setNowTick((n) => n + 1), 60_000);
    return () => window.clearInterval(id);
  }, []);

  // 전체 보고서 aggregation — 로드된 thread들에 listReports 병렬 호출 → done만
  //   합쳐 created_at desc. threads 갱신(목록 로드·더 보기) 시 재계산. 동시성은
  //   thread 수만큼이라 보통 수십 개 수준 — 과하면 추후 청크 제한. refreshKey로
  //   외부 invalidate(새 thread·제목 변경 등)에도 재조회.
  useEffect(() => {
    if (threads.length === 0) {
      setAllReports([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      const lists = await Promise.all(
        threads.map((t) =>
          listReports(t.id).catch(() => [] as Report[]),
        ),
      );
      if (cancelled) return;
      const merged = lists.flat().filter((r) => r.status === "done");
      setAllReports(merged);
    })();
    return () => {
      cancelled = true;
    };
  }, [threads, refreshKey]);

  // 좌측 노출용 — 전체(allReports) + 현재 thread 실시간(currentReports) merge.
  //   현재 대화에서 막 생성된 보고서가 aggregation 캐시보다 fresh하므로 우선.
  //   id dedup 후 created_at desc.
  const displayReports = useMemo(() => {
    const byId = new Map<string, Report>();
    for (const r of allReports) byId.set(r.id, r);
    for (const r of currentReports ?? []) {
      if (r.status === "done") byId.set(r.id, r);
    }
    return [...byId.values()].sort((a, b) =>
      (b.created_at ?? "").localeCompare(a.created_at ?? ""),
    );
  }, [allReports, currentReports]);

  // thread 검색 필터 — title 부분일치 (대소문자 무시).
  // 새 대화는 첫 메시지 전엔 서버 미존재라 목록 재로드(refreshKey)에 안 잡힌다.
  // 활성 threadId 가 로드된 목록에 없으면 낙관적 "새 대화" 항목을 맨 위에 끼워
  // *즉시* 노출 — 전송·persist 후 재로드 시 실제 항목이 같은 id 로 대체(dedup).
  const threadsWithActive = useMemo(() => {
    if (threadId && !threads.some((t) => t.id === threadId)) {
      const now = Date.now();
      const optimistic: Thread = {
        id: threadId,
        title: "새 대화",
        created_at: now,
        updated_at: now,
        has_interrupt: false,
      };
      return [optimistic, ...threads];
    }
    return threads;
  }, [threads, threadId]);

  const filteredThreads = useMemo(() => {
    const q = threadFilter.trim().toLowerCase();
    if (!q) return threadsWithActive;
    // 제목 매치(로드된 목록) + 본문 매치(백엔드) 병합 — id dedup. 본문 매치는
    // 로드 목록 밖 옛 대화도 포함하므로 검색 범위를 넓힌다.
    const titleMatches = threadsWithActive.filter((t) =>
      (t.title ?? "").toLowerCase().includes(q),
    );
    const byId = new Map<string, Thread>();
    for (const t of titleMatches) byId.set(t.id, t);
    for (const t of contentMatches) if (!byId.has(t.id)) byId.set(t.id, t);
    return [...byId.values()];
  }, [threadsWithActive, threadFilter, contentMatches]);

  /** 목록 fetch (P3.2). */
  const reload = useCallback(
    async (resetOffset: boolean) => {
      if (!configured) {
        setThreads([]);
        setHasMore(false);
        return;
      }
      setLoading(true);
      try {
        const nextOffset = resetOffset ? 0 : offset;
        const list = await searchThreads({ limit: PAGE_SIZE, offset: nextOffset });
        setThreads((prev) => (resetOffset ? list : [...prev, ...list]));
        setHasMore(list.length === PAGE_SIZE);
        if (resetOffset) setOffset(0);
      } catch (err) {
        console.error("[ThreadList] search failed", err);
        onError("Thread 목록을 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    },
    [configured, offset, onError],
  );

  // configured/refreshKey 변경 시 첫 페이지 reload
  useEffect(() => {
    void reload(true);
    // reload는 offset에도 의존 — 첫 페이지만 reload 하므로 offset deps 의도적 제외
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configured, refreshKey]);

  async function loadMore() {
    if (!configured || loading || !hasMore) return;
    setLoading(true);
    try {
      const newOffset = offset + PAGE_SIZE;
      const list = await searchThreads({ limit: PAGE_SIZE, offset: newOffset });
      setThreads((prev) => [...prev, ...list]);
      setOffset(newOffset);
      setHasMore(list.length === PAGE_SIZE);
    } catch (err) {
      console.error("[ThreadList] loadMore failed", err);
      onError("Thread 목록을 더 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function handleNewThread() {
    if (!configured) {
      onError("먼저 설정에서 배포 URL과 Assistant ID를 입력하세요.");
      return;
    }
    // thread는 첫 메시지 송신 시 lazy 생성 (PageShell.handleSend). 여기선 URL만 /new로 리셋.
    router.push("/new");
  }

  function handleSelect(id: string) {
    // path도 항상 `/`로 정합 — `/new?threadId=` 같은 어색 URL 방지.
    router.replace(`/new?threadId=${id}`);
  }

  function startRename(t: Thread) {
    setEditingId(t.id);
    setEditingDraft(t.title);
  }

  async function togglePin(t: Thread) {
    const next = !t.pinned;
    // 낙관적: 목록 상태의 pinned 갱신(파생 filteredThreads가 고정 그룹 재계산).
    setThreads((prev) =>
      prev.map((x) => (x.id === t.id ? { ...x, pinned: next } : x)),
    );
    try {
      await setThreadPinned(t.id, next);
    } catch (err) {
      console.warn("[ThreadList] pin toggle failed", err);
      setThreads((prev) =>
        prev.map((x) => (x.id === t.id ? { ...x, pinned: t.pinned } : x)),
      );
      onError("고정 변경에 실패했습니다.");
    }
  }

  async function commitRename() {
    if (!editingId) return;
    const next = editingDraft.trim();
    const id = editingId;
    setEditingId(null);
    if (!next) return;
    const before = threads.find((t) => t.id === id)?.title;
    if (before === next) return;
    setThreads((prev) => prev.map((t) => (t.id === id ? { ...t, title: next } : t)));
    try {
      await renameThread(id, next);
    } catch (err) {
      console.error("[ThreadList] rename failed", err);
      onError("이름 변경 실패.");
      // rollback
      if (before !== undefined) {
        setThreads((prev) =>
          prev.map((t) => (t.id === id ? { ...t, title: before } : t)),
        );
      }
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const target = pendingDelete;
    setPendingDelete(null);
    try {
      await deleteThread(target.id);
      setThreads((prev) => {
        const next = prev.filter((t) => t.id !== target.id);
        // 삭제 대상이 활성 thread면 첫 thread로 이동 (P3.6) — 없으면 `/new`로.
        if (threadId === target.id) {
          if (next[0]) {
            router.replace(`/new?threadId=${next[0].id}`);
          } else {
            router.push("/new");
          }
        }
        return next;
      });
    } catch (err) {
      console.error("[ThreadList] delete failed", err);
      const status = (err as { status?: number; response?: { status?: number } })
        .status ?? (err as { response?: { status?: number } }).response?.status;
      const detail = (err as Error).message ?? String(err);
      const reason =
        status === 404
          ? "thread를 찾을 수 없음"
          : status === 401 || status === 403
            ? "권한 없음 (재로그인 필요)"
            : status === 409 || status === 423
              ? "진행 중인 run이 있어 삭제 불가 — 잠시 후 재시도"
              : status === 500
                ? "백엔드 내부 오류"
                : detail.slice(0, 100);
      onError(`삭제 실패 — ${reason}`);
    }
  }

  return (
    <aside
      aria-label="Threads"
      className="flex h-full w-full flex-col gap-4 overflow-x-hidden px-4 py-4"
    >
      {/* 상단 — 로고 + 새 대화 (auto height). 하단 선 — 심층보고서 섹션과 구분. */}
      <div className="flex shrink-0 flex-col gap-3 border-b border-md-outline-variant/60 pb-3">
      <div className="flex items-center justify-between gap-2 px-1">
        <button
          type="button"
          onClick={() => router.push("/landing")}
          aria-label="메인 페이지로"
          title="메인 페이지로"
          className="group inline-flex items-center gap-2 px-1 py-1 text-left transition-colors"
        >
          <ThemeLogo className="h-7 w-auto group-hover:opacity-80" />
          <span
            className="text-[10.5px] font-medium text-md-on-surface-variant"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            Beta
          </span>
        </button>
        {onCollapse ? (
          <button
            type="button"
            onClick={onCollapse}
            aria-label="Threads 패널 접기"
            title="패널 접기"
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container hover:text-md-on-surface"
          >
            <span className="material-symbols-outlined text-[18px]" aria-hidden>
              left_panel_close
            </span>
          </button>
        ) : null}
      </div>

      <button
        type="button"
        onClick={handleNewThread}
        disabled={!configured}
        className="group flex w-full items-center gap-3 px-2 py-2.5 text-left transition-colors duration-150 ease-out hover:bg-md-surface-container active:bg-md-surface-container-high disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
      >
        <span
          className="material-symbols-outlined text-[22px] text-md-on-surface transition-colors group-hover:text-md-primary"
          aria-hidden
        >
          edit_square
        </span>
        <span className="text-[15px] font-medium text-md-on-surface">
          새 대화
        </span>
      </button>
      </div>

      {/* 보고서 칸 — 내용 기반 높이 + 상한 200px (구 고정 200px 은 화면 높이가
          낮을 때 보고서 빈 칸이 과점해 대화 목록이 좁은 스크롤이 되던 문제 —
          실측 피드백 2026-07-24). 넘치면 섹션 내부 스크롤. */}
      <div className="flex max-h-[200px] min-h-[64px] shrink-0 flex-col overflow-hidden pb-2">
        <ReportsSection
          reports={displayReports}
          onPreview={(r) => setPreviewReport(r)}
        />
      </div>

      {/* 작성한 서식 — 다시 열기·삭제(2026-09-18). 없으면 섹션 자체를 숨겨
          대화 목록 공간을 뺏지 않는다. */}
      <DocumentsSection refreshKey={refreshKey} />


      {/* 채팅 목록 — 남은 공간 (flex-1) */}
      <div className="flex flex-1 min-h-0 flex-col">
        <h3 className="px-3 pb-2 text-[11px] font-semibold text-md-on-surface-variant">
          대화
        </h3>
        {/* thread 검색 — 제목 즉시 필터 + 본문 검색(2자↑). 항상 노출(구: 8개
            미만이면 숨김 → 스레드가 줄면 검색이 "사라진" 것처럼 보였음, 2026-07-24). */}
        {configured && threads.length > 0 ? (
          <div className="relative mb-2 px-2">
            <span
              className="material-symbols-outlined pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[16px] text-md-on-surface-variant"
              aria-hidden
            >
              search
            </span>
            <input
              type="text"
              value={threadFilter}
              onChange={(e) => setThreadFilter(e.target.value)}
              placeholder="대화 검색 (제목·내용)"
              aria-label="대화 제목·내용 검색"
              className="h-8 w-full rounded-md border border-md-outline-variant bg-md-surface px-8 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant outline-none transition-colors focus:border-md-primary"
            />
            {threadFilter ? (
              <button
                type="button"
                onClick={() => setThreadFilter("")}
                aria-label="검색어 지우기"
                className="absolute right-3.5 top-1/2 inline-flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
              >
                <span
                  className="material-symbols-outlined text-[14px]"
                  aria-hidden
                >
                  close
                </span>
              </button>
            ) : null}
          </div>
        ) : null}
        <div className="flex-1 overflow-y-auto">
        {!configured ? (
          <EmptyState text="설정을 먼저 입력해주세요." />
        ) : threads.length === 0 && !loading ? (
          <EmptyState text="아직 대화가 없습니다." />
        ) : filteredThreads.length === 0 && threadFilter.trim() ? (
          <EmptyState text="검색 결과가 없습니다." />
        ) : (
          <div className="flex flex-col">
            {(() => {
              // 평면 리스트 — 그룹 헤더("고정됨"·시간 그룹) 전부 제거(피드백
              // 2026-07-24: 세로 공간 절약, 고정은 행의 핀 하이라이트로 판별).
              // 정렬: 고정 먼저, 이후 최근순.
              const flat = [
                ...filteredThreads.filter((t) => t.pinned),
                ...filteredThreads.filter((t) => !t.pinned),
              ];
              return (
                <ul className="flex flex-col">
                  {flat.map((t) => (
                    <ThreadRow
                      key={t.id}
                      thread={t}
                      active={threadId === t.id}
                      editing={editingId === t.id}
                      editingDraft={editingDraft}
                      onSelect={() => handleSelect(t.id)}
                      onStartRename={() => startRename(t)}
                      onCancelRename={() => setEditingId(null)}
                      onChangeDraft={setEditingDraft}
                      onCommitRename={() => void commitRename()}
                      onRequestDelete={() => setPendingDelete(t)}
                      onTogglePin={() => void togglePin(t)}
                    />
                  ))}
                </ul>
              );
            })()}
          </div>
        )}
        {hasMore ? (
          <button
            type="button"
            onClick={() => void loadMore()}
            disabled={loading}
            className="mt-2 w-full rounded px-2 py-1 text-body-sm text-md-on-surface-variant hover:bg-md-surface-container-low disabled:opacity-50"
          >
            {loading ? "불러오는 중..." : "더 보기"}
          </button>
        ) : null}
        </div>
      </div>

      <DeleteConfirmDialog
        target={pendingDelete}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
      />

      <ReportPreviewDialog
        report={previewReport}
        onClose={() => setPreviewReport(null)}
      />

      {/* footer — Claude web 스타일: UsageBadge 위, user pill(avatar+email+▾) 아래.
          user pill 클릭 → popup 메뉴(설정 / [admin] 관리자 / 로그아웃). 아이콘
          나열 X — 정보 노이즈 제거. */}
      <footer className="shrink-0 border-t border-md-outline-variant/60 px-2 py-2">
        {/* 저장한 근거(개인 근거 라이브러리) 진입 — 답변 인용의 북마크 아이콘으로 저장한 것. */}
        <button
          type="button"
          data-tour="bookmarks"
          onClick={() => setBookmarksOpen(true)}
          className="mb-1 flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-[12px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
        >
          <span className="material-symbols-outlined text-[15px]" aria-hidden>
            bookmarks
          </span>
          저장한 근거
        </button>
        {/* 고객사 규제 모니터링 — 저장한 근거를 폴더(고객사)별로 묶어 개정 감지·정기 리포트. */}
        <Link
          href="/monitor"
          title="고객사별 규제 모니터링 — 개정 감지 리포트 설정"
          className="mb-1 flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-[12px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
        >
          <span className="material-symbols-outlined text-[15px]" aria-hidden>
            monitoring
          </span>
          고객사 모니터링
        </Link>
        {/* 이용 안내 — 한 칸(2026-08-27 요청). 행 클릭=매뉴얼(/guide),
            오른쪽 나침반 아이콘=30초 화면 투어. */}
        {/* hover 는 각자 — 행 전체 배경을 걸면 둘러보기에 올렸는데 이용
            안내 칸까지 물드는 간섭(2026-08-27 지적). */}
        <div className="mb-1 flex w-full items-center">
          <Link
            href="/guide"
            target="_blank"
            rel="noopener noreferrer"
            title="이용 매뉴얼 — 기능별 자세한 안내"
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded px-2 py-1.5 text-[12px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
          >
            <span className="material-symbols-outlined text-[15px]" aria-hidden>
              menu_book
            </span>
            이용 안내
          </Link>
          <button
            type="button"
            onClick={() => window.dispatchEvent(new Event("medi-open-tour"))}
            title="30초 화면 둘러보기"
            className="mr-1 inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-1 text-[11px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-high hover:text-md-on-surface"
          >
            <span className="material-symbols-outlined text-[13px]" aria-hidden>
              explore
            </span>
            둘러보기
          </button>
        </div>
        <div className="px-1 pb-2">
          <UsageBadge />
        </div>
        {userEmail ? (
          <UserMenu
            email={userEmail}
            isAdmin={isAdmin}
            onOpenSettings={() => onOpenSettings?.()}
          />
        ) : (
          <Link
            href="/login"
            className="group flex w-full items-center gap-2.5 rounded-md px-2 py-2 transition-colors hover:bg-md-surface-container"
          >
            <span
              aria-hidden
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-md-surface-container text-md-on-surface-variant transition-colors group-hover:text-md-primary"
            >
              <span className="material-symbols-outlined text-[16px]">login</span>
            </span>
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-md-on-surface-variant group-hover:text-md-on-surface">
              로그인
            </span>
          </Link>
        )}

        {/* 약관·개인정보 — 로그인 후 앱 내부에서도 접근 가능하게 footer 최하단에
            작은 링크 줄. landing/login/signup footer와 동일 진입로. */}
        <nav className="mt-2 flex items-center justify-center gap-2 text-[10.5px] text-md-on-surface-variant">
          <Link href="/terms" className="hover:text-md-on-surface">
            이용약관
          </Link>
          <span aria-hidden>·</span>
          <Link href="/privacy" className="hover:text-md-on-surface">
            개인정보처리방침
          </Link>
        </nav>
      </footer>
      <BookmarksDialog open={bookmarksOpen} onOpenChange={setBookmarksOpen} />
    </aside>
  );
}

/* ────────────────────────── footer UserMenu ────────────────────────── */

/**
 * 사이드바 footer의 사용자 영역 — Claude web 스타일 popup 메뉴.
 * 한 줄: avatar + email + ▾. 클릭하면 위로 펼쳐지는 menu(설정/관리자/로그아웃).
 *
 * 외부 클릭·Esc로 닫힘. Tab 키로 메뉴 항목 순회 가능.
 */
function UserMenu({
  email,
  isAdmin,
  onOpenSettings,
}: {
  email: string;
  isAdmin: boolean;
  onOpenSettings: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // 키보드 접근성 — 열리면 첫 항목으로 포커스 이동, ↑/↓ 로 항목 순회.
  // (기존엔 role="menu" 인데 포커스가 메뉴로 안 들어가 키보드 사용 불가였음.)
  useEffect(() => {
    if (!open) return;
    menuRef.current
      ?.querySelector<HTMLElement>('[role="menuitem"]')
      ?.focus();
  }, [open]);

  function onMenuKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    );
    if (items.length === 0) return;
    e.preventDefault();
    const idx = items.indexOf(document.activeElement as HTMLElement);
    const next =
      e.key === "ArrowDown"
        ? (idx + 1) % items.length
        : (idx - 1 + items.length) % items.length;
    items[next]?.focus();
  }

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const initial = (email[0] ?? "?").toUpperCase();

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container data-[on=true]:bg-md-surface-container"
        data-on={open}
      >
        <span
          aria-hidden
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-md-primary-fixed text-[12px] font-bold uppercase text-md-on-primary-fixed-variant"
        >
          {initial}
        </span>
        <span className="flex min-w-0 flex-1 flex-col leading-tight">
          <span
            className="truncate text-[13px] font-medium text-md-on-surface"
            title={email}
          >
            {email}
          </span>
          {isAdmin ? (
            <span className="text-[10.5px] text-md-on-surface-variant">
              관리자
            </span>
          ) : null}
        </span>
        <span
          className={
            "material-symbols-outlined shrink-0 text-[18px] text-md-on-surface-variant transition-transform duration-[var(--motion-fast)] " +
            (open ? "rotate-180" : "")
          }
          aria-hidden
        >
          expand_less
        </span>
      </button>

      {open ? (
        <div
          ref={menuRef}
          role="menu"
          onKeyDown={onMenuKeyDown}
          className="absolute bottom-full left-0 right-0 z-20 mb-2 overflow-hidden rounded-md border border-md-outline-variant bg-md-surface shadow-lg"
        >
          {/* "설정"은 deployment URL/Assistant ID/LangSmith key 같은 *개발자
              override* 폼이라 일반 사용자에게 노출 X — admin만 보임. 운영은
              env가 권위이며 일반 사용자는 손댈 필요가 없다. (이전엔 모두에게
              노출돼 API 키·URL이 새고, assistant_id에 자동완성 이메일이 박혀
              runs.stream 실패의 원인이 됐음.) */}
          {isAdmin ? (
            <MenuItem
              icon="settings"
              label="설정"
              onClick={() => {
                setOpen(false);
                onOpenSettings();
              }}
            />
          ) : null}
          {isAdmin ? (
            <>
              <MenuSectionLabel>관리자</MenuSectionLabel>
              <MenuLink
                href="/admin/users"
                icon="group"
                label="사용자 관리"
                onSelect={() => setOpen(false)}
              />
              <MenuLink
                href="/admin/feedback"
                icon="reviews"
                label="피드백 조회"
                onSelect={() => setOpen(false)}
              />
              <MenuLink
                href="/admin/beta"
                icon="how_to_reg"
                label="베타 관리 (화이트리스트·테스트 계정)"
                onSelect={() => setOpen(false)}
              />
            </>
          ) : null}
          {/* 정보주체 권리(열람·삭제) — 모든 사용자에게 노출. 개인정보처리방침이
              약속한 "열람·삭제·동의 철회"의 실제 진입점. */}
          <MenuItem
            icon="privacy_tip"
            label="내 데이터·개인정보"
            onClick={() => {
              setOpen(false);
              setPrivacyOpen(true);
            }}
          />
          <MenuDivider />
          <MenuItem
            icon="logout"
            label="로그아웃"
            danger
            onClick={() => {
              setOpen(false);
              void signOut({ callbackUrl: "/login" });
            }}
          />
        </div>
      ) : null}
      <PrivacyDialog open={privacyOpen} onOpenChange={setPrivacyOpen} />
    </div>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  danger = false,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      role="menuitem"
      type="button"
      onClick={onClick}
      className={
        "flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors duration-[var(--motion-fast)] " +
        (danger
          ? "text-md-error hover:bg-md-error-container/30"
          : "text-md-on-surface hover:bg-md-surface-container-low")
      }
    >
      <span
        className={
          "material-symbols-outlined shrink-0 text-[18px] " +
          (danger ? "text-md-error" : "text-md-on-surface-variant")
        }
        aria-hidden
      >
        {icon}
      </span>
      <span className="flex-1 truncate">{label}</span>
    </button>
  );
}

function MenuLink({
  href,
  icon,
  label,
  onSelect,
}: {
  href: string;
  icon: string;
  label: string;
  onSelect: () => void;
}) {
  return (
    <Link
      role="menuitem"
      href={href}
      onClick={onSelect}
      className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-[13px] text-md-on-surface transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low"
    >
      <span
        className="material-symbols-outlined shrink-0 text-[18px] text-md-on-surface-variant"
        aria-hidden
      >
        {icon}
      </span>
      <span className="flex-1 truncate">{label}</span>
    </Link>
  );
}

function MenuSectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3 pb-1 pt-2 text-[10.5px] font-semibold text-md-on-surface-variant">
      {children}
    </div>
  );
}

function MenuDivider() {
  return <div className="my-1 border-t border-md-outline-variant/60" />;
}

/**
 * Claude/ChatGPT 스타일 시간 그룹핑.
 *  - 오늘 / 어제 / 지난 7일 / 지난 30일 / 이전
 *  - 각 그룹 안에서는 updated_at desc 유지 (입력은 이미 정렬됨)
 *  - 빈 그룹은 출력 X
 */
// (groupThreadsByTime 은 2026-07-24 제거 — "오늘/어제/지난 7일" 서브타이틀이
//  세로 공간만 차지한다는 피드백. 최근순 평면 리스트 + 행별 상대시간으로 대체.)

/**
 * 사이드바 "보고서" 섹션 — 현재 thread의 done 보고서 빠른 다운로드.
 * 빈 thread / 보고서 0개면 미렌더.
 *
 * web/rag 보고서는 *중간 산출물* (검색 결과를 답변 생성에 쓰기 위한 정리 문서) —
 * 사용자에게 노출되는 *최종 산출물*은 final 하나뿐. 사이드바에서는 final만 표시.
 */
/**
 * 작성한 서식 목록 (2026-09-18) — 사용자가 채운 서식을 다시 열고 삭제한다.
 *
 * 왜 별도 섹션인가: 서류(kind=doc)는 8/27 책임 분리 이후 보고서 목록·카드에서
 * 제외됐고, 진입점이 "작성 중인 서류" pill(현재 스레드의 최신 1건)뿐이라 이전
 * 서식은 UI 에서 닿을 수 없었다. 목록은 `GET /documents`(본인 것만, 최신순).
 * 갱신 신호: 새 서식 생성(DOCUMENTS_CHANGED_EVENT) · 패널 닫힘(기입 수 변동) ·
 * 상위 refreshKey.
 */
function DocumentsSection({ refreshKey }: { refreshKey: number }) {
  const { documentId, setDocumentId } = useRightPanel();
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [tick, setTick] = useState(0);
  const [manageOpen, setManageOpen] = useState(false);

  useEffect(() => {
    const bump = () => setTick((n) => n + 1);
    window.addEventListener(DOCUMENTS_CHANGED_EVENT, bump);
    return () => window.removeEventListener(DOCUMENTS_CHANGED_EVENT, bump);
  }, []);

  // 패널이 닫힐 때(documentId → null) 재조회 — 채운 항목 수가 바뀌었을 수 있다.
  useEffect(() => {
    if (documentId) return;
    let cancelled = false;
    void listDocuments()
      .then((list) => {
        if (!cancelled) setDocs(list);
      })
      .catch(() => {
        /* 목록 실패는 조용히 — 사이드바가 깨질 일은 아니다 */
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId, refreshKey, tick]);

  const handleDelete = async (d: DocumentListItem) => {
    if (!window.confirm(`'${d.title ?? "서식"}'을 삭제할까요?\n채운 내용도 함께 지워지며 되돌릴 수 없어요.`)) return;
    try {
      await deleteReport(d.id);
      setDocs((prev) => prev.filter((x) => x.id !== d.id));
      if (documentId === d.id) setDocumentId(null);
      window.dispatchEvent(new CustomEvent(DOCUMENT_DELETED_EVENT, { detail: { id: d.id } }));
      toast.success("서식을 삭제했어요.");
    } catch {
      toast.error("삭제하지 못했어요. 잠시 후 다시 시도해 주세요.");
    }
  };

  if (!loaded) return null;

  return (
    <div className="flex max-h-[160px] shrink-0 flex-col overflow-hidden pb-2">
      <DocumentsDialog open={manageOpen} onOpenChange={setManageOpen} />
      <h3 className="flex items-center px-3 pb-1 pt-1 text-[11px] font-semibold text-md-on-surface-variant">
        <span className="flex-1">작성한 서식 ({docs.length})</span>
        <button
          type="button"
          onClick={() => setManageOpen(true)}
          className="rounded px-1 text-[10.5px] font-medium text-md-primary hover:bg-md-primary/10"
        >
          관리
        </button>
      </h3>
      {docs.length === 0 ? (
        <p className="px-3 pb-1 text-[11.5px] leading-relaxed text-md-on-surface-variant opacity-60">
          아직 작성한 서식이 없어요.
        </p>
      ) : null}
      <ul className="flex flex-1 flex-col overflow-y-auto">
        {docs.map((d) => (
          <li key={d.id}>
            <button
              type="button"
              onClick={() => setDocumentId(d.id)}
              title={d.filled_count > 0 ? `채운 항목 ${d.filled_count}개 · 눌러서 열기` : "눌러서 열기"}
              className="group/sb-doc flex w-full items-center gap-2 px-3 py-2 text-left transition-colors duration-200 ease-out hover:bg-md-surface-container-low"
            >
              <span
                className="material-symbols-outlined shrink-0 text-[14px] text-md-on-surface-variant transition-colors duration-200 ease-out group-hover/sb-doc:text-md-primary"
                aria-hidden
              >
                edit_document
              </span>
              <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-md-on-surface transition-colors duration-200 ease-out group-hover/sb-doc:text-md-primary">
                {d.alias || d.title || "서식"}
              </span>
              {d.filled_count > 0 ? (
                <span className="shrink-0 text-[10.5px] text-md-on-surface-variant group-hover/sb-doc:hidden">
                  {d.filled_count}칸
                </span>
              ) : null}
              <span
                role="button"
                tabIndex={0}
                aria-label="서식 삭제"
                title="서식 삭제 (복구 불가)"
                onClick={(e) => {
                  e.stopPropagation();
                  void handleDelete(d);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    void handleDelete(d);
                  }
                }}
                className="inline-flex size-6 shrink-0 items-center justify-center rounded text-md-on-surface-variant opacity-0 transition-opacity duration-200 ease-out hover:bg-md-error-container hover:text-md-on-error-container group-hover/sb-doc:opacity-100"
              >
                <span className="material-symbols-outlined text-[14px]" aria-hidden>
                  delete
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportsSection({
  reports,
  onPreview,
}: {
  reports: import("@/lib/store/types").Report[];
  onPreview: (r: import("@/lib/store/types").Report) => void;
}) {
  // 삭제 낙관 반영(2026-08-27) — 우측 패널 카드와 동일한 삭제를 사이드바에도.
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const done = reports.filter(
    (r) => r.status === "done" && r.kind === "final" && !deletedIds.has(r.id));

  const handleDelete = async (r: import("@/lib/store/types").Report) => {
    if (!window.confirm(`'${r.title ?? "보고서"}'를 삭제할까요?\n삭제하면 되돌릴 수 없어요.`)) return;
    try {
      await deleteReport(r.id);
      setDeletedIds((prev) => new Set([...prev, r.id]));
      toast.success("보고서를 삭제했어요.");
    } catch {
      toast.error("삭제하지 못했어요. 잠시 후 다시 시도해 주세요.");
    }
  };

  const KIND_LABEL: Record<string, string> = {
    final: "종합 보고서",
  };

  if (done.length === 0) {
    return (
      <div className="flex h-full flex-col">
        <h3 className="px-3 pb-2 text-[11px] font-semibold text-md-on-surface-variant">
          심층 보고서
        </h3>
        <div className="flex flex-1 items-start justify-center px-2 pt-1 text-center">
          <p className="text-[11.5px] leading-relaxed text-md-on-surface-variant opacity-60">
            아직 생성된 보고서가 없어요.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <h3 className="px-3 pb-1 pt-1 text-[11px] font-semibold text-md-on-surface-variant">
        심층 보고서 ({done.length})
      </h3>
      <ul className="flex flex-1 flex-col overflow-y-auto">
        {done.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onPreview(r)}
              className="group/sb-report flex w-full items-center gap-2 px-3 py-2 text-left transition-colors duration-200 ease-out hover:bg-md-surface-container-low"
            >
              <span
                className="material-symbols-outlined shrink-0 text-[14px] text-md-on-surface-variant transition-colors duration-200 ease-out group-hover/sb-report:text-md-primary"
                aria-hidden
              >
                {r.kind === "final" ? "summarize" : r.kind === "rag" ? "menu_book" : "public"}
              </span>
              <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-md-on-surface transition-colors duration-200 ease-out group-hover/sb-report:text-md-primary">
                {r.title ?? KIND_LABEL[r.kind] ?? r.kind}
              </span>
              {/* 삭제 — hover 시 노출. button 중첩 금지라 span+키보드 처리. */}
              <span
                role="button"
                tabIndex={0}
                aria-label="보고서 삭제"
                title="보고서 삭제 (복구 불가)"
                onClick={(e) => {
                  e.stopPropagation();
                  void handleDelete(r);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.stopPropagation();
                    void handleDelete(r);
                  }
                }}
                className="inline-flex size-6 shrink-0 items-center justify-center rounded text-md-on-surface-variant opacity-0 transition-opacity duration-200 ease-out hover:bg-md-error-container hover:text-md-on-error-container group-hover/sb-report:opacity-100"
              >
                <span className="material-symbols-outlined text-[14px]" aria-hidden>
                  delete
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-2 px-2 py-12 text-center text-md-on-surface-variant">
      <span
        className="material-symbols-outlined text-[28px] opacity-40"
        aria-hidden
      >
        chat_bubble_outline
      </span>
      <p className="text-[12px]">{text}</p>
    </div>
  );
}

type RowProps = {
  thread: Thread;
  active: boolean;
  editing: boolean;
  editingDraft: string;
  onSelect: () => void;
  onStartRename: () => void;
  onCancelRename: () => void;
  onChangeDraft: (v: string) => void;
  onCommitRename: () => void;
  onRequestDelete: () => void;
  onTogglePin: () => void;
};

function ThreadRow({
  thread,
  active,
  editing,
  editingDraft,
  onSelect,
  onStartRename,
  onCancelRename,
  onChangeDraft,
  onCommitRename,
  onRequestDelete,
  onTogglePin,
}: RowProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  return (
    <li
      // 툴팁은 **행(박스) 전체** 대상 — 제목 글자에 정확히 올려야만 전문이
      // 보이던 문제(피드백 2026-07-24).
      title={thread.title}
      className={
        // 컬럼: [본문(제목+시간·고정배지)][케밥] 2개 고정 — 전 행 동일 폭.
        // 핀은 컬럼이 아니라 메타 줄 안의 배지(2026-07-25). 케밥은 self-stretch
        // 로 행 전체 높이.
        "group relative flex items-stretch gap-0.5 px-3 py-2 transition-colors duration-[var(--motion-fast)] " +
        (active
          ? "bg-md-surface-container-low"
          : "hover:bg-md-surface-container-lowest")
      }
    >
      {editing ? (
        <input
          ref={inputRef}
          type="text"
          value={editingDraft}
          onChange={(e) => onChangeDraft(e.target.value)}
          onBlur={onCommitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onCommitRename();
            } else if (e.key === "Escape") {
              e.preventDefault();
              onCancelRename();
            }
          }}
          className="h-7 w-full rounded border border-md-outline-variant bg-md-surface px-2 text-[12.5px] text-md-on-surface outline-none focus:border-md-primary"
        />
      ) : (
        <button
          type="button"
          onClick={onSelect}
          onDoubleClick={onStartRename}
          className="flex min-w-0 flex-1 flex-col items-start text-left"
        >
          <span
            className={
              // 한 줄 truncate — 줄바꿈 금지(피드백 2026-07-24). 전문 툴팁은 행(li)에.
              "w-full truncate text-[12.5px] leading-snug text-md-on-surface " +
              (active ? "font-semibold" : "font-normal")
            }
          >
            {thread.title}
          </span>
          <span
            className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-md-on-surface-variant"
            title={new Date(thread.updated_at).toLocaleString("ko-KR")}
          >
            {/* 고정 표시 — 메타 줄 맨 앞(피드백 2026-07-25: 우측 self-stretch
                버튼은 2줄 행의 세로 중앙 = 제목과 시간 "사이"에 떠 보였음).
                여기가 이미 상태 배지 슬롯(has_interrupt 점)이고, 고정 행은
                목록 상단에 연속 배치되므로 메타 줄끼리 정렬이 맞는다.
                토글은 케밥 메뉴로 일원화 — 이건 표시 전용(오클릭 해제 방지). */}
            {thread.pinned ? (
              <span
                className="material-symbols-outlined shrink-0 text-[11px] leading-none text-md-primary"
                style={{ fontVariationSettings: "'FILL' 1" }}
                aria-label="상단 고정됨"
                role="img"
              >
                keep
              </span>
            ) : null}
            {formatRelativeTime(thread.updated_at)}
            {thread.has_interrupt ? (
              <span
                aria-label="응답 대기 중"
                className="inline-flex h-1.5 w-1.5 shrink-0 rounded-full bg-md-error"
              />
            ) : null}
          </span>
        </button>
      )}

      {/* 우측 열은 케밥 하나뿐 — 핀 버튼(구 w-6)이 고정 행에만 렌더돼 행마다
          제목 truncate 폭이 24px씩 달랐던 문제도 함께 해소(2026-07-25). */}
      {!editing ? (
        <RowMenu
          pinned={thread.pinned}
          onTogglePin={onTogglePin}
          onStartRename={onStartRename}
          onRequestDelete={onRequestDelete}
        />
      ) : null}
    </li>
  );
}

// (RowAction 은 2026-07-24 케밥 메뉴(RowMenu) 통합으로 제거)

/**
 * RowMenu — 대화 행 우측 ⋮(케밥) 메뉴(2026-07-24 UX 결정: 고정/이름 변경/삭제
 * 아이콘 3개 나열 → 메뉴 1개 통합. hover 노이즈↓, 행 폭 확보).
 * 외부 클릭·Esc 로 닫힘.
 */
function RowMenu({
  pinned,
  onTogglePin,
  onStartRename,
  onRequestDelete,
}: {
  pinned?: boolean;
  onTogglePin: () => void;
  onStartRename: () => void;
  onRequestDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const item = (
    icon: string,
    label: string,
    fn: () => void,
    danger = false,
  ) => (
    <button
      type="button"
      role="menuitem"
      onClick={(e) => {
        e.stopPropagation();
        setOpen(false);
        fn();
      }}
      className={
        "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] transition-colors hover:bg-md-surface-container " +
        (danger ? "text-md-error" : "text-md-on-surface")
      }
    >
      <span className="material-symbols-outlined text-[14px]" aria-hidden>
        {icon}
      </span>
      {label}
    </button>
  );
  return (
    // self-stretch + h-full — 트리거가 행(칸) **전체 높이**를 차지
    // (피드백 2026-07-24: 아래칸만 차지하던 문제).
    <div ref={ref} className="relative flex shrink-0 self-stretch">
      <button
        type="button"
        aria-label="대화 메뉴"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className={
          "inline-flex h-full w-6 items-center justify-center rounded text-md-on-surface-variant transition-all duration-[var(--motion-fast)] hover:bg-md-surface-container-high " +
          (open
            ? "opacity-100"
            : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100")
        }
      >
        <span className="material-symbols-outlined text-[15px]" aria-hidden>
          more_vert
        </span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-20 w-32 overflow-hidden rounded-card border border-md-outline-variant bg-md-surface py-1 shadow-[var(--shadow-popover)]"
        >
          {item("keep", pinned ? "고정 해제" : "상단 고정", onTogglePin)}
          {item("edit", "이름 변경", onStartRename)}
          {item("delete", "삭제", onRequestDelete, true)}
        </div>
      ) : null}
    </div>
  );
}

function DeleteConfirmDialog({
  target,
  onCancel,
  onConfirm,
}: {
  target: Thread | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={!!target} onOpenChange={(o) => (!o ? onCancel() : null)}>
      <DialogContent className="max-w-[420px]">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-md-error-container text-md-error"
            >
              <span className="material-symbols-outlined text-[20px]">delete</span>
            </span>
            <DialogTitle>대화 삭제</DialogTitle>
          </div>
          {target ? (
            <div className="mt-2.5 space-y-1 text-body-sm leading-[1.6] text-md-on-surface-variant">
              <p>
                <span className="font-medium text-md-on-surface">
                  &ldquo;{target.title}&rdquo;
                </span>
                을(를) 삭제합니다.
              </p>
              <p>이 작업은 되돌릴 수 없습니다.</p>
              <p>이 대화에서 작성한 서식도 함께 삭제됩니다. 남기려면 [작성한 서식 › 관리]에서 먼저 보관하세요.</p>
            </div>
          ) : null}
        </DialogHeader>
        <DialogFooter>
          <DialogAction variant="secondary" onClick={onCancel}>
            취소
          </DialogAction>
          <DialogAction variant="destructive" onClick={onConfirm}>
            삭제
          </DialogAction>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function formatRelativeTime(ms: number): string {
  if (!ms) return "";
  const diff = Date.now() - ms;
  if (diff < 60_000) return "방금";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}분 전`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}시간 전`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}일 전`;
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}
