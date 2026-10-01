"use client";

/**
 * PageShell — 02 §1, §2, §11. P0~P7 누적.
 *
 * - Header (56px) + 3-pane Resizable (ThreadList | Chat | RightPanel).
 * - SettingsDialog 호스팅.
 * - useChatState를 *PageShell 레벨*에서 호출 — ChatColumn과 RightPanel이 같은 state 공유 (P7).
 * - RightPanel은 ?citation= 또는 ?docPath= 셋 시에만 마운트.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { usePathname, useRouter } from "next/navigation";
import { useQueryState } from "nuqs";
import { InlineErrorBanner } from "@/components/shell/InlineErrorBanner";
import { SettingsDialog } from "@/components/settings/SettingsDialog";
import { ThreadList } from "@/components/thread/ThreadList";
import { ChatInput } from "@/components/chat/ChatInput";
import { withViewTransitionAsync } from "@/lib/viewTransition";
import { ChatScroll } from "@/components/chat/ChatScroll";
import { Turn as TurnView } from "@/components/chat/Turn";
import { EmptyHero } from "@/components/chat/EmptyHero";
import { ThreadTitleHeader } from "@/components/chat/ThreadTitleHeader";
import { NotificationBell } from "@/components/shell/NotificationBell";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { FeatureTour } from "@/components/shell/FeatureTour";
import { TokenFeedbackPrompt } from "@/components/shell/TokenFeedbackPrompt";
import { PatchNotesPrompt } from "@/components/shell/PatchNotesPrompt";
import { UserNoticePrompt } from "@/components/shell/UserNoticePrompt";
import { RightPanel, useRightPanelMode } from "@/components/panel/RightPanel";
import { DocumentPanel } from "@/components/panel/DocumentPanel";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { RightPanelProvider, useRightPanel } from "@/lib/store/rightPanel";
import { SavedCitationsProvider } from "@/lib/store/savedCitations";
import {
  isConfigured,
  isDummyMode,
  SETTINGS_CHANGE_EVENT,
  SETTINGS_STORAGE_KEY,
} from "@/lib/store/settings";
import {
  createThread,
  THREAD_LIST_CHANGED_EVENT,
} from "@/lib/client/threads";
import { useChatState } from "@/lib/store/useChatState";
import { articleKeyFromCitation } from "@/lib/client/article";
import type { ChatAttachmentPayload } from "@/lib/store/turns";
import { useUsage } from "@/lib/store/useUsage";
import { useIsNarrow } from "@/lib/useIsNarrow";
import { useMode } from "@/components/providers/ModeProvider";
import type { ChatState } from "@/lib/store/types";

export function PageShell() {
  return (
    <RightPanelProvider>
      <SavedCitationsProvider>
        <PageShellInner />
      </SavedCitationsProvider>
    </RightPanelProvider>
  );
}

function PageShellInner() {
  const { showPro } = useMode();   // 일반 상담 모드에서는 서식 작성 진입을 막는다
  const isNarrow = useIsNarrow();
  const [threadsOpen, setThreadsOpen] = useState(true);
  const narrowInitRef = useRef(false);
  // delay-unmount용 — close 호출 시 200ms 동안 out 애니메이션 후 실제 unmount.
  const [threadsClosing, setThreadsClosing] = useState(false);
  const [rightClosing, setRightClosing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // 낙관적 init=true — useEffect의 isConfigured() 검증 *전*에 "설정 필요" flash 안 뜨도록.
  // 미설정 사용자는 mount 후 잠깐 늦게(1 frame) 안내 보임 (수용 가능).
  const [configured, setConfigured] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [shellError, setShellError] = useState<string | null>(null);
  const dummy = isDummyMode();

  const router = useRouter();
  const [threadId] = useQueryState("threadId");
  const {
    citation,
    docPath,
    open: rpOpen,
    setOpen: setRpOpen,
    setCitation,
    setDocPath,
    setDocumentId,
  } = useRightPanel();
  // 404 stale thread (backend 재시작·삭제) → `/new` 으로 이동 → EmptyHero로 복귀.
  const chat = useChatState(threadId, {
    onInvalidThread: useCallback(() => {
      router.push("/new");
      setShellError("이 대화는 더 이상 존재하지 않습니다. 새 대화를 시작해주세요.");
    }, [router]),
  });
  const rightMode = useRightPanelMode(chat.state, chat.isRunning, chat.reportRunning);

  // 스레드 전환 시 이전 대화에서 클릭한 citation/docPath 를 클리어. 안 그러면 스토어에
  // 남은 값 때문에 useRightPanelMode 가 "side" 를 반환해, 인용 없는 *새 대화*에서도
  // 우측 패널이 자동으로 열린다(사용자 리포트 2026-07-15).
  useEffect(() => {
    setCitation(null);
    setDocPath(null);
    setDocumentId(null);
  }, [threadId, setCitation, setDocPath, setDocumentId]);

  // ※ 서류의 자동 패널/모달 오픈은 전부 폐지(2026-08-27 재재설계) — 진행은
  //   입력창 위 컴팩트 pill(DocumentPill)이 보여주고, 모달은 사용자가 연다.
  //   예외 하나: [이 서식으로 작성] 직후는 사용자 의도가 명시적이라 즉시 오픈.

  // 좁은 화면 첫 진입 시 사이드바·우측 패널 기본 닫힘 — 3-pane 이 성립하지 않는
  // 폭에서 채팅이 가려지는 것 방지(narrow 우측 패널은 풀스크린 오버레이).
  useEffect(() => {
    if (isNarrow && !narrowInitRef.current) {
      narrowInitRef.current = true;
      setThreadsOpen(false);
      setRpOpen(false);
    }
  }, [isNarrow, setRpOpen]);

  // 새 mode 도착 시 자동 reopen — 사용자가 이전에 닫았어도 새 컨텐츠는 알림처럼 노출.
  // ※ 좁은 화면에선 우측 패널이 *전체 화면 오버레이*라 자동 오픈하면 채팅이
  //   통째로 가려진다(스레드 진입만 해도 보고서 폴링이 오버레이를 띄움 — 리뷰
  //   발견). narrow 에선 사용자가 토글로만 연다.
  useEffect(() => {
    if (isNarrow) return;
    if (rightMode && !rpOpen) setRpOpen(true);
    // rightMode 변경에만 반응 — rpOpen 의존성 넣으면 닫기 직후 즉시 다시 열림.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rightMode, isNarrow]);

  // ※ deep_dispatched_at·deep_progress 기반 패널 강제 오픈/전환 effect들은
  //   단일 thread 전환(2026-05-19)으로 폐기 — 해당 필드를 세팅하는 코드가 없어
  //   전부 도달 불가였다. 보고서 진행은 report_turn_ids가 RightPanel에 반영.

  // 별표·서식 인용에서 "이 서식으로 작성" — 서식을 고르면 **서식이 뜬다**.
  // 2026-08-26 최초 구현은 심층 보고서 파이프라인을 태워서, 서식을 눌렀는데
  // "심층 보고서 생성 중"이 뜨고 수십 분을 기다려야 했다(실사용 지적).
  // 기입 항목은 서식 자체에서 나오므로 LLM 없이 몇 초면 화면이 열린다.
  const handleUseAsForm = useCallback(
    (articleKey: string, title: string) => {
      void (async () => {
        const rid = await chat.openFormDocument(articleKey, title);
        // 버튼을 누른 직후는 의도가 명시적 — 바로 작성 모달을 연다.
        if (rid) setDocumentId(rid);
      })();
    },
    [chat, setDocumentId],
  );

  // 표시 여부 = mode가 있고 사용자가 닫지 않았을 때
  const showRightPanel = Boolean(rightMode) && rpOpen;

  // close 시 240ms out 슬라이드 후 실제 unmount (globals.css animate-md-panel-out-* 타이밍 정합).
  // **closing 도중 외부 신호(citation chip 클릭 등)로 패널 다시 열리면 timer cancel** —
  // 그래야 setTimeout이 stale하게 setRpOpen(false) 호출해서 방금 연 패널을 다시 닫는 버그 차단.
  const closeThreads = useCallback(() => setThreadsClosing(true), []);
  const openThreads = useCallback(() => {
    setThreadsOpen(true);
    setThreadsClosing(false);
  }, []);
  useEffect(() => {
    if (!threadsClosing) return;
    const t = window.setTimeout(() => {
      setThreadsOpen(false);
      setThreadsClosing(false);
    }, 240);
    return () => window.clearTimeout(t);
  }, [threadsClosing]);

  const toggleRight = useCallback(() => {
    if (showRightPanel) {
      setRightClosing(true);
    } else {
      setRpOpen(true);
      setRightClosing(false);
    }
  }, [showRightPanel, setRpOpen]);
  // closing 시작 → 240ms 후 setRpOpen(false). cleanup으로 timer cancel 가능.
  useEffect(() => {
    if (!rightClosing) return;
    const t = window.setTimeout(() => {
      setRpOpen(false);
      setRightClosing(false);
    }, 240);
    return () => window.clearTimeout(t);
  }, [rightClosing, setRpOpen]);
  // **closing 도중 새 citation/docPath 신호 들어오면 closing cancel** —
  // 사용자가 panel close 중 본문 chip 클릭 시 위 timer가 setRpOpen(false)로 방금
  // 박은 patel을 다시 닫는 stale 호출 차단. cleanup이 timer clear.
  useEffect(() => {
    if (rightClosing) setRightClosing(false);
    // citation/docPath 변경에만 반응 — rightClosing deps 넣으면 closing 시작 즉시 cancel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [citation, docPath]);

  // 첫 진입 시 config 자동 오픈 정책 (05 §3.1)
  useEffect(() => {
    if (dummy) {
      setConfigured(true);
      return;
    }
    const present = isConfigured();
    setConfigured(present);
    if (!present && process.env.NODE_ENV !== "production") {
      setSettingsOpen(true);
    }
    if (!present && process.env.NODE_ENV === "production") {
      setShellError(
        "백엔드 연결 정보가 없습니다. 관리자에게 문의하세요.",
      );
    }
  }, [dummy]);

  // settings 변경 → client 재생성 + 자식 fetch 재실행
  useEffect(() => {
    function onChanged() {
      if (dummy) {
        setConfigured(true);
      } else {
        setConfigured(isConfigured());
      }
      setRefreshKey((k) => k + 1);
      setShellError(null);
    }
    function onStorage(e: StorageEvent) {
      if (e.key === SETTINGS_STORAGE_KEY) onChanged();
    }
    window.addEventListener(SETTINGS_CHANGE_EVENT, onChanged);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(SETTINGS_CHANGE_EVENT, onChanged);
      window.removeEventListener("storage", onStorage);
    };
  }, [dummy]);

  // thread CRUD(create/rename/delete) 또는 자동 rename → 사이드바 재fetch
  useEffect(() => {
    function onListChanged() {
      setRefreshKey((k) => k + 1);
    }
    window.addEventListener(THREAD_LIST_CHANGED_EVENT, onListChanged);
    return () => {
      window.removeEventListener(THREAD_LIST_CHANGED_EVENT, onListChanged);
    };
  }, []);

  // Chat input의 center X를 CSS var로 노출 — Toaster가 이 값으로 정렬 (globals.css §sonner).
  // ResizeObserver + 사이드바·우측패널 토글 + window resize에 모두 반응.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const update = () => {
      const el = document.querySelector("[data-chat-input]") as HTMLElement | null;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      document.documentElement.style.setProperty("--toast-x", `${centerX}px`);
    };
    // ChatInput가 mount되기 전 일 수 있어 약간 delayed 첫 호출 + observer 등록.
    const t = window.setTimeout(update, 50);
    const ro = new ResizeObserver(update);
    const observe = () => {
      const el = document.querySelector("[data-chat-input]");
      if (el) ro.observe(el);
    };
    observe();
    window.addEventListener("resize", update);
    // sidebar/right panel 토글이 transition 끝나면 한 번 더 업데이트
    const t2 = window.setInterval(update, 500); // 가벼운 fallback
    return () => {
      window.clearTimeout(t);
      window.clearInterval(t2);
      ro.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [threadsOpen, showRightPanel, rightMode]);

  // ── 좁은 화면(모바일) 레이아웃 — 3-pane 대신 단일 컬럼 + 드로어/오버레이 ──
  // resizable PanelGroup 은 375px 폭에서 성립하지 않아(사이드바 16% ≈ 60px)
  // 사이드바는 좌측 드로어, 우측 패널은 전체 화면 오버레이로 전환. 임시완화 —
  // 전용 모바일 UX(스와이프 등)는 별도 스프린트.
  if (isNarrow) {
    return (
      <div data-medra-surface className="flex h-[100dvh] w-screen flex-col bg-md-surface text-md-on-surface">
        <div className="flex-1 overflow-hidden">
          <ChatColumn
            chat={chat}
            configured={configured}
            onUseAsForm={showPro ? handleUseAsForm : undefined}
            shellError={shellError}
            clearShellError={() => setShellError(null)}
            setShellError={setShellError}
            onMissingConfig={() => setSettingsOpen(true)}
            threadsOpen={false}
            onOpenThreads={() => setThreadsOpen(true)}
            rightPanelToggle={{
              open: showRightPanel,
              onToggle: () => setRpOpen(!rpOpen),
            }}
          />
        </div>

        {/* 좌측 드로어 — 사이드바 */}
        {threadsOpen ? (
          <div className="fixed inset-0 z-40">
            <div
              aria-hidden
              className="absolute inset-0 bg-black/40"
              onClick={() => setThreadsOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 w-[300px] max-w-[85vw] border-r border-md-outline-variant bg-md-surface-container-low shadow-xl">
              <ThreadList
                configured={configured}
                refreshKey={refreshKey}
                onError={setShellError}
                onCollapse={() => setThreadsOpen(false)}
                onOpenSettings={() => setSettingsOpen(true)}
                currentReports={chat.state.reports}
              />
            </div>
          </div>
        ) : null}

        {/* 우측 패널 — 전체 화면 오버레이 */}
        {showRightPanel && rightMode ? (
          <div className="fixed inset-0 z-40 flex flex-col bg-md-surface">
            <header className="flex h-11 shrink-0 items-center justify-between border-b border-md-outline-variant px-3">
              <span className="text-[12px] font-semibold text-md-on-surface-variant">
                출처·보고서
              </span>
              <button
                type="button"
                onClick={() => setRpOpen(false)}
                aria-label="패널 닫기"
                className="inline-flex h-8 w-8 items-center justify-center rounded text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface"
              >
                <span className="material-symbols-outlined text-[20px]" aria-hidden>
                  close
                </span>
              </button>
            </header>
            <div className="min-h-0 flex-1">
              <RightPanel state={chat.state} isRunning={chat.isRunning} reportRunning={chat.reportRunning} reportQueueAhead={chat.state.report_queue_ahead ?? null} reportProgress={chat.state.report_progress ?? null}
                onUseAsForm={showPro ? handleUseAsForm : undefined} />
            </div>
          </div>
        ) : null}

        <DocumentWorkModal document={chat.state.document} />
        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      </div>
    );
  }

  return (
    <div data-medra-surface className="flex h-[100dvh] w-screen flex-col bg-md-surface text-md-on-surface">
      <div className="flex-1 overflow-hidden">
        <PanelGroup
          direction="horizontal"
          // v2 — side 모드 default 폭 28%로 변경. autoSaveId 그대로 두면 localStorage에
          // 박힌 직전 20% 드래그 폭이 우선 적용돼 새 기본값 무효화. 한 번 reset 후 사용자가
          // 다시 드래그하면 그 값으로 persist.
          // 사용자 회신("답변 생성할때 오른쪽사이드 열렸다닫혔다 왔다갔다"): autoSaveId가
          // closed↔side-v3↔artifact-v2 사이를 토글하면 PanelGroup 자체가 remount되어
          // 깜빡임. 답변 도중 useRightPanelMode가 미세하게 null↔"side" 변동(폴링·deep
          // 신호 등)이면 그 시각이 그대로 노출됨. **autoSaveId를 closed 케이스에도
          // 동일 모드값으로 고정** — 닫힌 상태에선 어차피 우측 Panel을 mount 안 하므로
          // 폭 persist에 무관. group은 한 ID로 유지 → mode 토글 없이는 remount X.
          autoSaveId={`root-${rightMode === "artifact" ? "artifact-v2" : "side-v3"}`}
          className="h-full w-full"
        >
          {(threadsOpen || threadsClosing) && (
            <>
              {/* 좌측 사이드바 — 고정 너비. divider는 Panel 자체의 border-r로 박음 —
                  별도 element면 transform 거리(1px vs 16%)가 달라 "구분선이 나중에 따라오는"
                  시각 발생. border-r은 panel과 한 몸이라 완벽 동기. */}
              <Panel
                id="threads"
                order={1}
                defaultSize={16}
                minSize={16}
                maxSize={16}
                data-medra-sidebar
                className={
                  "border-r border-md-outline-variant bg-md-surface-container-low " +
                  (threadsClosing
                    ? "animate-md-panel-out-left"
                    : "animate-md-panel-in-left")
                }
              >
                <ThreadList
                  configured={configured}
                  refreshKey={refreshKey}
                  onError={setShellError}
                  onCollapse={closeThreads}
                  onOpenSettings={() => setSettingsOpen(true)}
                  currentReports={chat.state.reports}
                />
              </Panel>
            </>
          )}

          <Panel
            id="chat"
            order={2}
            defaultSize={
              !showRightPanel
                ? 84
                : rightMode === "artifact"
                  ? 56 // artifact: 우측 44%
                  : 64 // side(citation·reports·deep·split): 우측 36%
            }
            minSize={36}
          >
            <ChatColumn
              chat={chat}
              configured={configured}
              onUseAsForm={showPro ? handleUseAsForm : undefined}
              shellError={shellError}
              clearShellError={() => setShellError(null)}
              setShellError={setShellError}
              onMissingConfig={() => setSettingsOpen(true)}
              threadsOpen={threadsOpen}
              onOpenThreads={openThreads}
              rightPanelToggle={{
                open: showRightPanel,
                onToggle: toggleRight,
              }}
            />
          </Panel>

          {(showRightPanel || rightClosing) && (
            <>
              {/* resize handle은 *드래그 영역만* — 시각 divider는 Panel border-l로 일체화.
                  transparent + 넓은 hit area. handle 자체엔 animation X — panel과
                  한 몸이라 layout transform 받음. */}
              <PanelResizeHandle
                aria-label="우측 패널 폭 조정"
                className="group relative w-px bg-transparent outline-none"
              >
                <span className="absolute inset-y-0 -left-1 -right-1" aria-hidden />
              </PanelResizeHandle>
              <Panel
                id="right"
                order={3}
                defaultSize={rightMode === "artifact" ? 44 : 36}
                minSize={24}
                maxSize={55}
                className={
                  "border-l border-md-outline-variant transition-colors duration-[var(--motion-fast)] " +
                  (rightClosing
                    ? "animate-md-panel-out-right"
                    : "animate-md-panel-in-right")
                }
              >
                <RightPanel state={chat.state} isRunning={chat.isRunning} reportRunning={chat.reportRunning} reportQueueAhead={chat.state.report_queue_ahead ?? null} reportProgress={chat.state.report_progress ?? null}
                onUseAsForm={showPro ? handleUseAsForm : undefined} />
              </Panel>
            </>
          )}
        </PanelGroup>
      </div>

      <DocumentWorkModal document={chat.state.document} />
      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      {/* Ctrl/Cmd+K 커맨드 팔레트 — 대화 검색·새 대화·라이브러리 (S2-2) */}
      <CommandPalette />
      {/* 첫 방문 1회 코치마크 투어 + 재실행("이용 안내") */}
      <FeatureTour />
      {/* 월 누적 토큰 임계 초과 실사용자 피드백 모달(월 1회) */}
      <TokenFeedbackPrompt />
      {/* 패치노트 팝업 — 안 본 최신 노트만 1회(localStorage id 비교) */}
      <PatchNotesPrompt />
      {/* 사용자별 앱 내 알림 — 지정 수신자에게만, 서버 읽음 상태로 1회 */}
      <UserNoticePrompt />
    </div>
  );
}

/* ─────────────────────────── ChatColumn ─────────────────────────── */

type ChatProps = ReturnType<typeof useChatState>;

type ChatColumnProps = {
  /** 서식 즉시 작성(2026-08-27) — next_steps 서류 초안 핸드오프용 */
  /** 일반 상담 모드에서는 undefined — 서식 작성 진입을 감춘다. */
  onUseAsForm?: (articleKey: string, title: string) => void;
  chat: ChatProps;
  configured: boolean;
  shellError: string | null;
  clearShellError: () => void;
  setShellError: (m: string) => void;
  onMissingConfig: () => void;
  /** 사이드바 닫혀있으면 false — 좌상단 floating 토글 노출 */
  threadsOpen: boolean;
  onOpenThreads: () => void;
  /** RightPanel 토글 가능 시 (mode 활성). null이면 토글 안 표시 */
  rightPanelToggle: { open: boolean; onToggle: () => void };
};

/**
 * "서식" 인용 수집(2026-08-27) — [서류 초안 작성] 핸드오프의 근거.
 *
 * 스레드에서 **서식이 마지막으로 등장한 step**(≈ 최신 답변의 검색 결과)의
 * 서식들을 등장 순서로 돌려준다. 한 답변이 여러 서식(업 허가 제1호 + 품목
 * 허가 제3호 등)을 인용했을 때 조용히 하나를 고르면 반은 오답이다 — 2건
 * 이상이면 호출자가 선택 다이얼로그를 띄운다.
 */
function findRecentFormCitations(
  state: ChatState,
): { key: string; title: string; article: string }[] {
  const cats = new Set(["법령별표서식", "행정규칙별표서식", "자치법규별표서식"]);
  let lastGroup: { key: string; title: string; article: string }[] = [];
  for (const step of state.steps ?? []) {
    const forms: { key: string; title: string; article: string }[] = [];
    const seen = new Set<string>();
    for (const c of step.citations ?? []) {
      if (!c.doc_category || !cats.has(c.doc_category)) continue;
      const label = `${c.article ?? ""} ${c.title ?? ""}`;
      if (!label.includes("서식")) continue;
      const key = articleKeyFromCitation(c);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      forms.push({ key, title: c.title ?? "", article: c.article ?? "" });
    }
    if (forms.length) lastGroup = forms; // 서식이 등장한 마지막 step 채택
  }
  return lastGroup;
}

function ChatColumn({
  chat,
  configured,
  onUseAsForm,
  shellError,
  clearShellError,
  setShellError,
  onMissingConfig,
  threadsOpen,
  onOpenThreads,
  rightPanelToggle,
}: ChatColumnProps) {
  const { mode } = useMode();
  const router = useRouter();
  const pathname = usePathname();
  const [threadId, setThreadIdQuery] = useQueryState("threadId");
  const [draftPrefill, setDraftPrefill] = useState<string | null>(null);
  // 서류 초안 서식 선택(2026-08-27) — 최신 답변이 서식을 2개 이상 인용했을 때.
  const [formChoices, setFormChoices] = useState<
    { key: string; title: string; article: string }[] | null
  >(null);
  // ※ 문서→메인채팅 프리필(2026-08-27 오전)은 같은 날 폐기 — 서식 작성은
  //   전용 도우미 모달(DocumentPanel)로 이동. 저장 대화가 PII 마스킹본이라
  //   메인 채팅 경유로는 개인정보 칸을 채울 수 없다는 지적이 결정타.
  // 기본 주소(no threadId)에서 입력한 첫 메시지 — 자동 thread 생성 후 새 threadId가 박히면 송신
  const [pendingFirstMessage, setPendingFirstMessage] = useState<{
    text: string;
    attachments?: ChatAttachmentPayload[];
    skillHint?: string | null;
  } | null>(null);
  const creatingThreadRef = useRef(false);
  const { state, isRunning, streamComplete, reportRunning, threadLoading, send, triggerReport, stop, resume, retry, setError } = chat;
  // 텍스트 확정(done) 후 grounding 위해 스트림은 잠깐 더 열려 있지만(isRunning=true),
  // 턴 렌더·입력 잠금은 즉시 해제 — 인용/태그 노출, "생성중" 해제, 입력 가능.
  const chatActive = isRunning && !streamComplete;

  // 토큰 한도 초과 시 *새 turn* 전송만 차단(soft cap). running 중인 turn은
  // 그대로 진행돼 결과 끝까지 노출 — 사용자 요구(2026-05-20). 한도 0 이하면
  // "무제한"으로 간주(false). useUsage 30s 폴링이라 리셋/조정 시 자동 해제.
  const { usage } = useUsage();
  const dailyOver = !!(
    usage &&
    usage.effective_daily_limit > 0 &&
    usage.usage.daily_total_tokens >= usage.effective_daily_limit
  );
  const monthlyOver = !!(
    usage &&
    usage.effective_monthly_limit > 0 &&
    usage.usage.monthly_total_tokens >= usage.effective_monthly_limit
  );
  const overLimit = dailyOver || monthlyOver;
  // 한도 초과 시 *언제 풀리는지* 명시 — placeholder 만으론 리셋 시점을 알 수 없어
  // 사용자가 무의미하게 재시도하거나 이탈했다(UX 감사 #6).
  const overLimitNotice = overLimit
    ? dailyOver
      ? "오늘 사용량 한도에 도달했습니다. 자정에 초기화됩니다."
      : "이번 달 사용량 한도에 도달했습니다. 다음 달 1일에 초기화됩니다."
    : null;

  // 쿼터 80% 사전 경고 (UX 배치 #5) — 일/월 중 높은 쪽이 80% 이상 100% 미만이면
  // 입력창 위 얇은 배너. 초과 배너(overLimitNotice)와 중복 노출 X.
  const dailyPct =
    usage && usage.effective_daily_limit > 0
      ? usage.usage.daily_total_tokens / usage.effective_daily_limit
      : 0;
  const monthlyPct =
    usage && usage.effective_monthly_limit > 0
      ? usage.usage.monthly_total_tokens / usage.effective_monthly_limit
      : 0;
  const warnPct = Math.max(dailyPct, monthlyPct);
  const quotaWarning =
    !overLimit && warnPct >= 0.8 && warnPct < 1
      ? dailyPct >= monthlyPct
        ? `오늘 사용량의 ${Math.round(dailyPct * 100)}% 사용 — 한도 도달 시 자정에 초기화됩니다.`
        : `이번 달 사용량의 ${Math.round(monthlyPct * 100)}% 사용 — 한도 도달 시 다음 달 1일에 초기화됩니다.`
      : null;

  // 심층 보고서 수동 트리거 — 기존엔 AI가 next_steps 로 제안할 때만 생성 가능해
  // 핵심 기능의 발견성이 낮았다(UX 감사 #7). 대화가 있고 idle 일 때 활성.
  const canManualReport =
    !!threadId && state.turns.length > 0 && !isRunning && !overLimit;
  const handleManualReport = useCallback((purpose?: string | null) => {
    if (!canManualReport) return;
    void triggerReport(
      "지금까지의 대화 내용을 종합하여 심층 보고서를 작성해주세요.",
      { purpose: purpose ?? null },
    );
  }, [canManualReport, triggerReport]);

  // threadLoading 은 useChatState 가 실제 fetch 수명으로 제공(고정 300ms 타이머
  // 제거 — fetch 완료 전에 꺼져 새 대화 화면이 깜빡이던 원인, 2026-07-24).

  // 새 대화 권장 넛지(2026-07-24 피드백) — 스레드가 길어지거나 보고서 완료 후에도
  // 대화를 이어가면 새 대화 시작을 권고(비차단·스레드별 1회 닫기 기억).
  // 근거: 긴 스레드는 요약 압축으로 맥락 손실 + 응답 지연↑, 보고서 후 새 주제는
  // 새 스레드가 검색·보고서 품질에 유리.
  const [nudgeDismissed, setNudgeDismissed] = useState(false);
  useEffect(() => {
    setNudgeDismissed(
      typeof window !== "undefined" &&
        window.sessionStorage.getItem(`medi-newchat-nudge-${threadId}`) === "1",
    );
  }, [threadId]);
  const dismissNudge = useCallback(() => {
    setNudgeDismissed(true);
    try {
      window.sessionStorage.setItem(`medi-newchat-nudge-${threadId}`, "1");
    } catch {
      /* storage 불가 — 세션 내 state 로만 */
    }
  }, [threadId]);
  const hasDoneReport = (state.reports ?? []).some(
    (r) => r.status === "done" && r.kind === "final",
  );
  const recommendNewChat =
    !!threadId &&
    !nudgeDismissed &&
    !chatActive &&
    (state.turns.length >= 12 || (hasDoneReport && state.turns.length >= 8));

  const handleSend = useCallback(
    async (
      text: string,
      attachments?: ChatAttachmentPayload[],
      skillHint?: string | null,
    ) => {
      // `@feedback ...` 인터셉트 — 채팅 send 안 함, /feedback/general POST.
      const fbMatch = text.match(/^@feedback\s+/i);
      if (fbMatch) {
        const comment = text.slice(fbMatch[0].length).trim();
        if (!comment) {
          const { toast } = await import("sonner");
          // error 토스트는 사용자가 읽고 행동(수정·재시도)해야 하므로 default 3.5s는 짧음.
          toast.error("피드백 내용을 입력해주세요.", { duration: 6000 });
          return;
        }
        if (comment.length > 2000) {
          const { toast } = await import("sonner");
          toast.error("피드백은 2000자 이내로 입력해주세요.", { duration: 6000 });
          return;
        }
        try {
          const lastAiId = state.turns
            .slice()
            .reverse()
            .find((t) => t.answer?.id)?.answer?.id;
          const { postGeneralFeedback } = await import("@/lib/client/quota");
          await postGeneralFeedback({
            comment,
            context: {
              thread_id: threadId ?? undefined,
              last_message_id: lastAiId,
            },
          });
          const { toast } = await import("sonner");
          toast.success("피드백이 전송되었습니다. 감사합니다!");
        } catch (err) {
          console.warn("[handleSend] @feedback failed", err);
          const { toast } = await import("sonner");
          toast.error("피드백 전송 실패. 잠시 후 다시 시도해주세요.", { duration: 6000 });
        }
        return;
      }

      if (!configured || !isConfigured()) {
        onMissingConfig();
        return;
      }
      clearShellError();
      if (!threadId) {
        // 자동 thread 생성 + 첫 메시지 pending → 새 threadId 박히면 effect가 send 트리거
        if (creatingThreadRef.current) return;
        creatingThreadRef.current = true;
        try {
          const t = await createThread();
          setPendingFirstMessage({ text, attachments, skillHint });
          // `/new`에서 송신 시 path도 `/`로 전환 — `/new?threadId=xxx` 어색 URL 방지.
          // (chat) layout이 PageShell을 감싸므로 router.replace 해도 PageShell 유지(언마운트 X).
          if (pathname === "/new") {
            router.replace(`/new?threadId=${t.id}`);
          } else {
            void setThreadIdQuery(t.id);
          }
          window.dispatchEvent(new Event(THREAD_LIST_CHANGED_EVENT));
        } catch (err) {
          console.error("[ChatColumn] auto-create thread failed", err);
          setShellError("새 thread 생성 실패.");
        } finally {
          creatingThreadRef.current = false;
        }
        return;
      }
      await send(text, { attachments, skillHint });
    },
    [configured, threadId, send, state.turns, onMissingConfig, setShellError, clearShellError, setThreadIdQuery, pathname, router],
  );

  // 새 threadId가 박혔고 pending 메시지가 있으면 송신 (next tick — useChatState reset/getState 우선)
  useEffect(() => {
    if (!threadId || !pendingFirstMessage) return;
    const pending = pendingFirstMessage;
    setPendingFirstMessage(null);
    const t = window.setTimeout(
      () =>
        void send(pending.text, {
          attachments: pending.attachments,
          skillHint: pending.skillHint ?? null,
        }),
      0,
    );
    return () => window.clearTimeout(t);
  }, [threadId, pendingFirstMessage, send]);

  const errorBanner = shellError ?? state.error?.message ?? null;
  const followKey = `${state.turns.length}-${state.turns.at(-1)?.steps.length ?? 0}-${
    state.turns.at(-1)?.answer?.content.length ?? 0
  }`;

  return (
    <section
      data-medra-surface
      aria-label="Chat"
      className="relative flex h-full w-full flex-col bg-md-surface"
    >
      {/* 본문 상단 통합 헤더 — *모든 상태*에서 동일한 sticky 헤더 한 줄.
          turns ≥ 1: ThreadTitleHeader (제목 + 양 토글)
          turns = 0: 동일 높이의 미니 헤더 (양 토글만) — floating 버튼이 우측 패널 영역과
                    겹치는 문제 방지. */}
      {threadId && state.turns.length > 0 ? (
        <ThreadTitleHeader
          threadId={threadId}
          threadsOpen={threadsOpen}
          onOpenThreads={onOpenThreads}
          rightPanelToggle={rightPanelToggle}
        />
      ) : (
        <header className="sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 bg-md-surface px-3">
          {!threadsOpen ? (
            <button
              type="button"
              onClick={onOpenThreads}
              aria-label="Threads 패널 열기"
              title="Threads 패널 열기"
              data-touch-target
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low hover:text-md-on-surface"
            >
              <span className="material-symbols-outlined text-[20px]" aria-hidden>
                left_panel_open
              </span>
            </button>
          ) : null}
          <div className="min-w-0 flex-1" />
          <NotificationBell />
          <button
            type="button"
            onClick={rightPanelToggle.onToggle}
            aria-pressed={rightPanelToggle.open}
            aria-label={rightPanelToggle.open ? "오른쪽 패널 닫기" : "오른쪽 패널 열기"}
            title={rightPanelToggle.open ? "오른쪽 패널 닫기" : "오른쪽 패널 열기"}
            data-touch-target
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-md-on-surface-variant transition-colors duration-[var(--motion-fast)] hover:bg-md-surface-container-low hover:text-md-on-surface data-[on=true]:text-md-on-surface"
            data-on={rightPanelToggle.open}
          >
            <span className="material-symbols-outlined text-[20px]" aria-hidden>
              {rightPanelToggle.open ? "right_panel_close" : "right_panel_open"}
            </span>
          </button>
        </header>
      )}

      {/* 일반 상담 모드 고지 — 정보형 서비스임을 상시 밝힌다(2026-10-01). */}
      {mode === "public" ? (
        <div
          data-testid="public-notice"
          className="shrink-0 border-b border-md-outline-variant bg-md-surface-container-low px-4 py-1.5 text-[11.5px] leading-snug text-md-on-surface-variant"
        >
          <span className="material-symbols-outlined mr-1 align-[-3px] text-[14px]" aria-hidden>
            info
          </span>
          법령·절차를 안내하는 서비스이며 <b>법률 자문이 아닙니다.</b> 구체적인 사안은 담당
          전문가에게 확인하십시오.
        </div>
      ) : null}

      {errorBanner ? (
        <InlineErrorBanner
          message={errorBanner}
          retriable={state.error?.retriable ?? true}
          onRetry={() => {
            setError(null);
            clearShellError();
            retry();
          }}
          onDismiss={() => {
            setError(null);
            clearShellError();
          }}
        />
      ) : null}

      {/* empty 상태(첫 화면) — EmptyHero + ChatInput을 세로 중앙으로.
          첫 메시지 보내면 turns ≥ 1 → 일반 layout(하단 ChatInput)으로 전환. */}
      {threadId && threadLoading && state.turns.length === 0 ? (
        /* 기존 대화 로딩 중 — EmptyHero(첫 화면)가 깜빡 떴다가 내용으로 바뀌는
           혼란 방지(실측 피드백 2026-07-24): 로딩 화면을 대신 표시. */
        <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-6">
          <span
            className="inline-block size-8 rounded-full border-[3px] border-md-outline-variant border-t-md-primary animate-md-spin"
            aria-hidden
          />
          <p
            role="status"
            aria-live="polite"
            className="animate-md-shimmer text-body-sm font-medium text-md-on-surface-variant"
          >
            대화를 불러오는 중…
          </p>
        </div>
      ) : !threadId || state.turns.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-6 py-6">
          <EmptyHero
            configured={configured}
            onPickPrompt={(p) => setDraftPrefill(p)}
          />
          {/* vt-chat-input: 첫 메시지 전송 시 스레드 하단 입력창과 shared-element
              morph — 중앙→하단으로 스무스 슬라이딩(View Transitions). */}
          <div className="vt-chat-input mt-8 w-full max-w-[792px]">
            <ChatInput
              running={chatActive}
              disabled={!configured}
              overLimit={overLimit}
              overLimitNotice={overLimitNotice}
              quotaWarning={quotaWarning}
              prefill={draftPrefill}
              onPrefillConsumed={() => setDraftPrefill(null)}
              onSend={(t, atts, hint) =>
                withViewTransitionAsync(() => void handleSend(t, atts, hint))
              }
              onStop={stop}
            />
          </div>
        </div>
      ) : (
        <>
          <ChatScroll followKey={followKey} jumpKey={state.turns.at(-1)?.id}>
            <div className="mx-auto flex w-full max-w-[792px] flex-col gap-stack-gap px-6 py-6">
              {state.turns.map((t, i) => {
                // 재설계(2026-07-24): 보고서는 턴 타임라인에 없음 — 활성 판정은
                // 채팅 스트림만. 보고서 진행은 입력창 위 노티스+우측 패널.
                const isLast = i === state.turns.length - 1;
                const turnActive = isLast && chatActive;
                return (
                  <TurnView
                    key={t.id}
                    turn={t}
                    onPickNextStep={(p) => setDraftPrefill(p)}
                    onTriggerReport={(p, purpose) => {
                      // overLimit이면 dispatch 차단(soft cap과 동일 정책).
                      if (overLimit) return;
                      // 서류 초안(2026-08-27 핸드오프): 답변이 이미 서식을
                      // 인용했다면 5~40분 writer 파이프라인이 아니라 **그
                      // 서식의 즉시 작성 모달**로 보낸다("이거 어떻게 넘길래"
                      // — 버튼이 구식 경로로 가던 단절). 서식 인용이 없을
                      // 때만(기관 자체 양식 등) 종전 writer 초안으로 폴백.
                      if (purpose === "document_draft") {
                        const forms = findRecentFormCitations(state);
                        const only = forms[0];
                        if (forms.length === 1 && only && onUseAsForm) {
                          onUseAsForm(only.key, only.title);
                          return;
                        }
                        if (forms.length > 1) {
                          // 여러 서식 — 조용히 고르지 않고 사용자가 선택.
                          setFormChoices(forms);
                          return;
                        }
                      }
                      void triggerReport(p, purpose ? { purpose } : undefined);
                    }}
                    onResume={(v) => void resume(v)}
                    onUseAsForm={onUseAsForm}
                    // 마지막(활성) turn은 스트림이 실제 끝날 때까지 streaming 취급 —
                    // turn.status가 transient하게 done이어도 본문 확정 전 인용문서/근거
                    // 깜빡임 차단. 과거 turn은 이미 settled이므로 영향 없음.
                    streamingActive={turnActive}
                    // 활성 chat turn에만 라이브 진행 한 줄(검색 진행 메시지) 전달.
                    liveProgress={turnActive ? state.live_progress ?? null : null}
                    // 검색 중 도착하는 결과 1건씩 라이브 카드 — 활성 turn에만.
                    liveResults={turnActive ? state.live_results ?? null : null}
                  />
                );
              })}
              {/* 심층 보고서 진행 + 결과는 우측 RightPanel(ReportCardGroup)로
                  이동 — chat 영역엔 표시 X. */}
            </div>
          </ChatScroll>

          {reportRunning ? (
            <div className="mx-auto w-full max-w-[792px] px-6 pb-2">
              <ReportPendingNoticeBar
                queueAhead={state.report_queue_ahead ?? null}
                progress={state.report_progress ?? null}
                isDraft={state.report_purpose === "document_draft"}
              />
            </div>
          ) : null}
          {state.document?.report_id ? (
            <div className="mx-auto w-full max-w-[792px] px-6 pb-2">
              <DocumentPill document={state.document} />
            </div>
          ) : null}
          {/* 서식 선택 — 답변이 여러 서식을 인용한 경우(예: 업 허가 제1호 vs
              품목 허가 제3호). 잘못 고르면 엉뚱한 신청서를 준비하게 되므로
              시스템이 대신 고르지 않는다. */}
          <Dialog
            open={!!formChoices}
            onOpenChange={(o) => {
              if (!o) setFormChoices(null);
            }}
          >
            <DialogContent className="max-w-[440px] gap-0 border border-md-outline-variant bg-md-surface p-0 text-md-on-surface">
              <DialogTitle className="border-b border-md-outline-variant px-5 py-4 text-[14px] font-semibold">
                어떤 서식으로 작성할까요?
              </DialogTitle>
              <div className="flex flex-col gap-2 p-4">
                <p className="text-[12px] leading-relaxed text-md-on-surface-variant">
                  이 답변에서 서식이 여러 개 확인됐어요. 절차가 다르면 서식도
                  다릅니다 — 해당하는 것을 골라주세요.
                </p>
                {(formChoices ?? []).map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    onClick={() => {
                      setFormChoices(null);
                      onUseAsForm?.(f.key, f.title);
                    }}
                    className="flex items-start gap-2.5 rounded-card border border-md-outline-variant bg-md-surface-container-lowest px-3.5 py-3 text-left transition-colors hover:border-md-primary hover:bg-md-primary-container/30"
                  >
                    <span
                      className="material-symbols-outlined mt-0.5 text-[18px] text-md-primary"
                      aria-hidden
                    >
                      edit_document
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-semibold leading-snug text-md-on-surface">
                        {f.title || f.article || "서식"}
                      </span>
                      {f.article ? (
                        <span className="mt-0.5 block text-[11.5px] text-md-on-surface-variant">
                          {f.article}
                        </span>
                      ) : null}
                    </span>
                  </button>
                ))}
              </div>
            </DialogContent>
          </Dialog>
          {recommendNewChat ? (
            <div className="mx-auto w-full max-w-[792px] px-6 pb-2">
              <div
                role="status"
                className="flex items-center gap-2.5 rounded-card border border-md-outline-variant bg-md-surface-container-lowest px-3 py-2"
              >
                <span
                  className="material-symbols-outlined shrink-0 text-[16px] text-md-tertiary"
                  aria-hidden
                >
                  lightbulb
                </span>
                <p className="min-w-0 flex-1 text-[12px] leading-snug text-md-on-surface-variant">
                  {hasDoneReport
                    ? "보고서가 완성된 대화예요. 새 주제는 새 대화에서 시작하면 답변 품질과 속도가 좋아져요."
                    : "대화가 길어졌어요. 새 주제는 새 대화에서 시작하면 답변 품질과 속도가 좋아져요."}
                </p>
                <button
                  type="button"
                  onClick={() => router.push("/new")}
                  className="shrink-0 rounded-button px-2.5 py-1 text-[12px] font-semibold text-md-primary transition-colors hover:bg-md-surface-container"
                >
                  새 대화 시작
                </button>
                <button
                  type="button"
                  onClick={dismissNudge}
                  aria-label="이 안내 닫기"
                  className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-md-on-surface-variant transition-colors hover:bg-md-surface-container"
                >
                  <span className="material-symbols-outlined text-[14px]" aria-hidden>
                    close
                  </span>
                </button>
              </div>
            </div>
          ) : null}
          <div className="vt-chat-input">
            <ChatInput
              running={chatActive}
              disabled={!configured}
              overLimit={overLimit}
              overLimitNotice={overLimitNotice}
              quotaWarning={quotaWarning}
              prefill={draftPrefill}
              onPrefillConsumed={() => setDraftPrefill(null)}
              onSend={(t, atts, hint) => void handleSend(t, atts, hint)}
              onStop={stop}
              onManualReport={canManualReport ? handleManualReport : undefined}
            />
          </div>
        </>
      )}
    </section>
  );
}

// ChatState 타입 누락 import 방지(사용처 없음 — 미사용 경고 방지를 위해 명시 export 안 함)
export type { ChatState };

/**
 * ReportPendingNoticeBar — 입력창 위 고정 슬롯의 보고서 진행 노티스(재설계
 * 2026-07-24). 턴 타임라인 밖에서 reportRunning 만 구독 — 마지막 턴 여부·
 * 새로고침과 무관하게 정확. "채팅 계속 가능" 명시 + 우측 패널 열기.
 */
/**
 * 서류 작성 모달(2026-08-27 재재설계) — PageShell 이 호스팅한다.
 * 우측 패널과 독립: 패널이 닫혀 있어도 뜨고, 문서가 사이드를 점유하지 않는다.
 * 내부는 좌 서식 / 우 도우미 챗 2열(DocumentPanel) — 중첩 모달 없음.
 */
const DOC_MODAL_SIZE_KEY = "medi.docmodal.size";

function DocumentWorkModal({ document }: { document: ChatState["document"] }) {
  const { documentId, setDocumentId } = useRightPanel();
  // 크기 조절(2026-08-27 지적: "기본 사이즈 바꾸고 수정할 수 있게") —
  // 기본 1200×(88vh 상당), 우하단 핸들 드래그로 조절, localStorage 기억.
  const [size, setSize] = useState<{ w: number; h: number } | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const raw = window.localStorage.getItem(DOC_MODAL_SIZE_KEY);
      if (!raw) return null;
      const v = JSON.parse(raw) as { w?: number; h?: number };
      if (typeof v.w === "number" && typeof v.h === "number") return { w: v.w, h: v.h };
    } catch {
      /* 손상값 무시 */
    }
    return null;
  });
  const dragRef = useRef<{ sx: number; sy: number; w: number; h: number } | null>(null);

  const onResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const el = (e.currentTarget as HTMLElement).parentElement;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      dragRef.current = { sx: e.clientX, sy: e.clientY, w: rect.width, h: rect.height };
      const onMove = (ev: MouseEvent) => {
        const d = dragRef.current;
        if (!d) return;
        // 가운데 고정(translate -50%) 모달이라 커서 이동량의 2배가 체감 크기 변화.
        const w = Math.min(
          window.innerWidth * 0.98,
          Math.max(720, d.w + (ev.clientX - d.sx) * 2),
        );
        const h = Math.min(
          window.innerHeight * 0.96,
          Math.max(480, d.h + (ev.clientY - d.sy) * 2),
        );
        setSize({ w: Math.round(w), h: Math.round(h) });
      };
      const onUp = () => {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        setSize((v) => {
          if (v) {
            try {
              window.localStorage.setItem(DOC_MODAL_SIZE_KEY, JSON.stringify(v));
            } catch {
              /* quota 등 — 기억만 포기 */
            }
          }
          return v;
        });
        dragRef.current = null;
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    },
    [],
  );

  return (
    <Dialog
      open={!!documentId}
      onOpenChange={(o) => {
        if (!o) setDocumentId(null);
      }}
    >
      <DialogContent
        hideClose
        // 바깥 클릭으로 닫히지 않는다(2026-08-27) — 작성·자동 기입 중 오클릭
        // 한 번에 화면이 사라지는 사고 방지. 닫기는 헤더 X 또는 ESC 로만.
        // (닫혀도 기입값은 서버에 저장돼 있어 pill 로 재진입하면 그대로다.)
        onInteractOutside={(e) => e.preventDefault()}
        // ⚠️ `relative` 금지 — twMerge 가 베이스의 `fixed` 와 position 충돌로
        //    fixed 를 떨어뜨려 모달이 문서 흐름에 박혔다(2026-08-27 실사용).
        //    fixed 요소는 그 자체가 absolute 자식(리사이즈 핸들)의 기준이다.
        className="flex max-w-none flex-col gap-0 overflow-hidden border border-md-outline-variant bg-md-surface p-0 text-md-on-surface"
        style={{
          width: size ? `${size.w}px` : "min(94vw, 1200px)",
          height: size ? `${size.h}px` : "min(88vh, 860px)",
          maxWidth: "98vw",
          maxHeight: "96vh",
        }}
      >
        <DialogTitle className="sr-only">서류 작성</DialogTitle>
        {documentId ? (
          <DocumentPanel
            reportId={documentId}
            live={document}
            onClose={() => setDocumentId(null)}
          />
        ) : null}
        {/* 우하단 리사이즈 핸들 */}
        <div
          onMouseDown={onResizeStart}
          title="드래그해서 크기 조절"
          aria-hidden
          className="absolute bottom-0 right-0 z-10 flex size-5 cursor-nwse-resize items-end justify-end p-0.5 text-md-on-surface-variant/60 hover:text-md-on-surface"
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor">
            <path d="M9 1v8H1z" opacity=".35" />
          </svg>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * 입력창 위 컴팩트 서류 pill — 작성 중인 서류의 상시 진입점.
 * 사이드 패널을 점유하지 않으면서도 진행(채워진 개수)이 항상 보인다.
 */
function DocumentPill({ document }: { document: ChatState["document"] }) {
  const { setDocumentId } = useRightPanel();
  if (!document?.report_id) return null;
  const total = document.fields.length;
  const done = total - document.remaining.length;
  return (
    <button
      type="button"
      onClick={() => setDocumentId(document.report_id)}
      className="flex w-full items-center gap-2 rounded-card border border-md-outline-variant bg-md-surface-container-lowest px-3 py-1.5 text-left transition-colors hover:border-md-primary/50 hover:bg-md-surface-container-low"
    >
      <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>
        edit_document
      </span>
      <span className="min-w-0 flex-1 truncate text-[12px] text-md-on-surface">
        <span className="font-semibold">작성 중인 서류</span>
        <span className="text-md-on-surface-variant">
          {" "}· {total > 0 ? `${done}/${total} 항목` : "초안"} · 눌러서 열기
        </span>
      </span>
      <span className="material-symbols-outlined text-[15px] text-md-on-surface-variant" aria-hidden>
        open_in_new
      </span>
    </button>
  );
}

function ReportPendingNoticeBar({
  queueAhead = null,
  progress = null,
  isDraft = false,
}: {
  queueAhead?: number | null;
  progress?: string | null;
  /** 서류 초안 — 같은 파이프라인이지만 사용자에겐 다른 작업이다(2026-08-27) */
  isDraft?: boolean;
}) {
  const { setOpen } = useRightPanel();
  const noun = isDraft ? "서류 초안" : "심층 보고서";
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-2.5 rounded-card border border-md-primary/30 bg-md-surface-container-lowest px-3 py-2.5"
    >
      <span
        className="inline-block size-3.5 shrink-0 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin"
        aria-hidden
      />
      <p className="min-w-0 flex-1 text-[12.5px] leading-snug text-md-on-surface-variant">
        {/* 대기와 생성을 구분한다(2026-08-26) — GPU 를 다른 보고서가 쓰는
            동안에도 "생성 중"이라고 떠서, 실제로는 순서를 기다리는 중인데
            내 보고서가 작성되고 있다고 오해하게 만들었다. */}
        <span className="font-medium text-md-on-surface">
          {typeof queueAhead === "number" && queueAhead > 0
            ? `${noun} 대기 중`
            : progress && progress.includes("대기")
              ? `${noun} 대기 중`
              : `${noun} 작성 중`}
        </span>
        {typeof queueAhead === "number" && queueAhead > 0
          ? ` · 앞에 ${queueAhead}건 · 순서가 되면 자동 시작`
          : progress
            ? ` · ${progress}`
            : ""}
        {" — "}
        <span className="text-md-primary">채팅 계속 가능 · 완료 시 이메일로도 도착</span>
      </p>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="shrink-0 rounded-button px-2 py-1 text-[12px] font-medium text-md-secondary hover:bg-md-surface-container"
      >
        진행 보기 →
      </button>
    </div>
  );
}

