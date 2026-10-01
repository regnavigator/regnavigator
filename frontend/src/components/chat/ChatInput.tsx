"use client";

/**
 * ChatInput — 03 §6, P4.1·P4.2·P4.5·P4.7.
 *
 * - 자동 grow 1~12줄 (textarea scrollHeight 측정).
 * - Enter 전송 / Shift+Enter 줄바꿈 / Esc(running) 정지.
 * - running 중 전송 → destructive Stop 버튼으로 변경.
 * - 파일 첨부(v1, 2026-08-05): /files/extract 업로드 → 칩 → 전송 시 attachments.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { getAnswerStyle, setAnswerStyle } from "@/lib/store/turns";
import { useMode } from "@/components/providers/ModeProvider";
import { getMyPrefs, setReportEmailOptIn } from "@/lib/client/prefs";
import { extractFile, type ExtractedAttachment } from "@/lib/client/files";
import { toast } from "sonner";
import { DisclaimerHint } from "@/components/legal/DisclaimerHint";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { LoadBadge } from "@/components/shell/LoadBadge";
import { useReportsAvailability } from "@/lib/hooks/useReportsAvailability";

const MIN_ROWS = 1;
const MAX_ROWS = 12;
const LINE_HEIGHT_PX = 20; // text-body-base와 정합

// 백엔드 기본값과 정합(config.py) — CHAT_MAX_INPUT_CHARS·CHAT_MAX_ATTACHMENTS.
// 서버가 진실원이고 초과 시 한국어 422 를 돌려주지만, 전송 전에 미리 보여준다.
const MAX_INPUT_CHARS = 32_000;
const COUNTER_SHOW_AT = 24_000; // 75% 부터 카운터 노출
const MAX_ATTACHMENTS = 3;
const ACCEPT_EXT = ".pdf,.docx,.hwpx,.hwp,.txt,.md,.csv";

type Props = {
  /** running 중이면 Stop 버튼 노출 (P4.5). */
  running: boolean;
  /** 전송 가능 여부 (예: settings 미설정 / threadId 없음). */
  disabled?: boolean;
  /** 토큰 한도 초과 — *새 turn* 전송만 차단. running 중인 turn은 끝까지 보여줌
   *  (soft cap). 한도 리셋/조정 시 useUsage 폴링이 자동 해제. */
  overLimit?: boolean;
  /** 한도 초과 안내 문구(리셋 시점 포함) — overLimit 시 입력 카드 위 배너로 노출 */
  overLimitNotice?: string | null;
  /** 쿼터 80% 사전 경고 문구 — 초과 전(80~99%)에만 상위가 전달. 세션 내 dismiss 가능. */
  quotaWarning?: string | null;
  /** 심층 보고서 수동 트리거 — 대화가 있는 idle 상태에서 호스트가 전달.
   *  미전달 시 버튼 숨김(첫 화면·진행 중·한도 초과). */
  onManualReport?: (purpose?: string | null) => void;
  /** EmptyHero 칩 등에서 textarea에 prefill될 텍스트. 한 번 채운 뒤 호스트가 null로 cleared 해야 함. */
  prefill?: string | null;
  /** prefill 한 번 적용 후 호스트에 알림 (한 번만 채우게) */
  onPrefillConsumed?: () => void;
  /** 보내기. running=false 일 때만 호출됨. attachments = /files/extract 결과.
   *  skillHint = "irb_drb" — IRB/DRB 모드 켜진 상태로 전송(백엔드 명시 진입). */
  onSend: (
    text: string,
    attachments?: ExtractedAttachment[],
    skillHint?: string | null,
  ) => void;
  /** 정지. running=true 일 때 호출됨. */
  onStop: () => void;
};

const QUOTA_WARN_DISMISS_KEY = "quota-warn-banner-dismissed";

export function ChatInput({
  running,
  disabled,
  overLimit = false,
  overLimitNotice = null,
  quotaWarning = null,
  onManualReport,
  prefill,
  onPrefillConsumed,
  onSend,
  onStop,
}: Props) {
  // 보고서 기능 가용성(2026-09-07) — 일시 중단이면 버튼 비활성 + 배너, writer 다운이면 경고
  const { showPro } = useMode();   // 일반 상담 모드에서는 전문가 기능을 감춘다
  const reportsAvail = useReportsAvailability();
  const [value, setValue] = useState("");
  // IRB/DRB 모드 — AI 키워드 감지와 별개의 명시 진입 버튼(이중 접근, 2026-08-21).
  // 켜져 있는 동안 전송마다 skill_hint 로 동반. 사용자가 끌 때까지 유지.
  const [irbMode, setIrbMode] = useState(false);
  // 첨부 문서 — /files/extract 추출 결과를 전송 전까지 들고 있는다(서버 무상태).
  const [attachments, setAttachments] = useState<ExtractedAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  // 드래그&드롭 — dragenter/leave 는 자식 요소마다 발화하므로 카운터로 판정.
  const [dragOver, setDragOver] = useState(false);
  const dragDepthRef = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 카드 밖에 떨어뜨리면 브라우저가 파일을 열어버린다 — 전역에서 기본 동작 차단.
  useEffect(() => {
    const prevent = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
    };
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", prevent);
    };
  }, []);
  // 쿼터 80% 경고 — 세션 내 dismiss(sessionStorage). 탭 닫으면 리셋.
  const [quotaWarnDismissed, setQuotaWarnDismissed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return !!window.sessionStorage.getItem(QUOTA_WARN_DISMISS_KEY);
    } catch {
      return false;
    }
  });
  function dismissQuotaWarn() {
    setQuotaWarnDismissed(true);
    try {
      window.sessionStorage.setItem(QUOTA_WARN_DISMISS_KEY, "1");
    } catch {
      // private browsing 등 — state만으로 충분
    }
  }

  // P6.1.3 — EmptyHero 예시 칩·문서 패널 유도 → textarea prefill.
  // 채운 뒤 포커스 + 커서 끝(2026-08-27) — 문서 패널의 "채팅으로 알려주기"는
  // 문장을 이어서 치는 흐름이라, 포커스가 안 오면 프리필된 걸 알아채지 못한다.
  useEffect(() => {
    if (prefill && prefill.length > 0) {
      setValue(prefill);
      onPrefillConsumed?.();
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (el) {
          el.focus();
          el.setSelectionRange(el.value.length, el.value.length);
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 자동 grow — 매 입력마다 height 재계산 (P4.1)
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const max = LINE_HEIGHT_PX * MAX_ROWS;
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, [value]);

  // running(답변 생성) 중에는 입력 자체를 잠금 — 사용자 요구(2026-05-18):
  // "답변 생성 동안 입력 막아야". 전송은 원래도 trySend의 running 가드로 막혔지만
  // textarea 타이핑까지 차단해 중복 작성/오발송 여지를 없앤다. 정지는 Stop 버튼.
  // overLimit(토큰 한도 초과): *새 turn* 전송만 차단(soft cap). running 중이면
  //   그 turn은 그대로 진행돼 결과 끝까지 노출 — 중간 중단 X.
  const inputLocked = running || !!disabled || overLimit;

  function trySend() {
    let text = value.trim();
    if (running || disabled || overLimit || uploading) return;
    if (!text && attachments.length === 0) return;
    if (text.length > MAX_INPUT_CHARS) {
      toast.error(
        `입력이 너무 깁니다(${text.length.toLocaleString()}자 / 상한 ${MAX_INPUT_CHARS.toLocaleString()}자). 긴 문서는 파일로 첨부해 주세요.`,
        { duration: 6000 },
      );
      return;
    }
    // 첨부만 있고 질문이 없으면 기본 요청문 — 백엔드 message 는 비울 수 없다.
    if (!text) text = "첨부한 문서를 검토해 주세요.";
    onSend(
      text,
      attachments.length ? attachments : undefined,
      irbMode ? "irb_drb" : null,
    );
    setValue("");
    setAttachments([]);
  }

  function onDragEnter(e: React.DragEvent) {
    if (!e.dataTransfer.types.includes("Files")) return;
    dragDepthRef.current += 1;
    setDragOver(true);
  }

  function onDragLeave() {
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragOver(false);
  }

  function onDrop(e: React.DragEvent) {
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    dragDepthRef.current = 0;
    setDragOver(false);
    if (running || uploading) {
      toast.error(running ? "답변 생성 중에는 첨부할 수 없어요." : "파일을 읽는 중이에요 — 잠시만요.");
      return;
    }
    void handleFiles(e.dataTransfer.files);
  }

  async function handleFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    const files = Array.from(list);
    if (attachments.length + files.length > MAX_ATTACHMENTS) {
      toast.error(`첨부는 한 번에 ${MAX_ATTACHMENTS}개까지 가능합니다.`, { duration: 6000 });
      return;
    }
    setUploading(true);
    try {
      for (const f of files) {
        if (attachments.some((a) => a.name === f.name)) continue; // 같은 이름 중복 방지
        const r = await extractFile(f);
        setAttachments((prev) => [...prev, r]);
        if (r.truncated) {
          toast.info(
            `'${r.name}' 이(가) 길어 앞 ${r.chars.toLocaleString()}자만 첨부됩니다.`,
            { duration: 6000 },
          );
        }
      }
    } catch (err) {
      // extractFile 이 백엔드의 한국어 detail(413/415/422)을 그대로 던진다.
      toast.error(err instanceof Error ? err.message : "파일 처리 실패", { duration: 8000 });
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  // `@feedback` prefix 토글 — 클릭 시 prepend, 이미 박혀있으면 제거. 채팅 send 안 하고
  // 백엔드 /feedback/general 으로 자유 코멘트 전송 (PageShell.handleSend가 인터셉트).
  const hasFeedbackPrefix = /^@feedback\s/i.test(value);
  function toggleFeedback() {
    if (hasFeedbackPrefix) {
      setValue(value.replace(/^@feedback\s+/i, ""));
    } else {
      setValue(`@feedback ${value}`);
    }
    // textarea focus + 커서를 끝으로
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (el) {
        el.focus();
        el.selectionStart = el.selectionEnd = el.value.length;
      }
    });
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      trySend();
      return;
    }
    if (e.key === "Escape" && running) {
      e.preventDefault();
      onStop();
    }
  }

  const sendDisabled = running
    ? false
    : (!value.trim() && attachments.length === 0) || disabled || overLimit || uploading;
  const overChars = value.length > MAX_INPUT_CHARS;

  return (
    // 떠있는 카드 느낌 — sticky 컨테이너는 transparent 배경, 카드만 뜬 듯이 노출.
    // 페이지 본문이 카드 뒤로 자연스럽게 살짝 보이게 + 카드는 그림자로 부양감.
    // 답변 본문이 카드 위까지 자연스럽게 흐르도록 pt 거의 0. 카드는 그림자로만 부양.
    // 사용자 요구: "답변과 채팅입력 사이 칸 막힘" → padding 제거하여 floating 인접 배치.
    <div
      data-chat-input
      className="sticky bottom-0 w-full bg-transparent px-6 pb-4 pt-0"
    >
      <div className="mx-auto w-full max-w-[820px]">
        {/* 서버 혼잡 배지 — busy일 때만 노출 */}
        <LoadBadge />
        {/* 보고서 기능 일시 중단(운영자 토글) 또는 writer 다운 — 채팅은 정상이라는 점을 명시 */}
        {reportsAvail.paused ? (
          <div
            role="status"
            className="mx-auto mb-2 flex w-fit max-w-full items-start gap-1.5 rounded-[12px] border border-md-tertiary bg-md-tertiary-fixed px-3 py-1.5 text-[12px] font-medium leading-relaxed text-md-on-tertiary-fixed-variant"
          >
            <span className="material-symbols-outlined mt-px text-[14px]" aria-hidden>
              pause_circle
            </span>
            <span className="break-keep">
              {reportsAvail.message ?? "보고서 기능 점검 중입니다. 채팅·검색은 정상 이용 가능합니다."}
            </span>
          </div>
        ) : reportsAvail.writerUp === false ? (
          <div
            role="status"
            className="mx-auto mb-2 flex w-fit max-w-full items-start gap-1.5 rounded-[12px] border border-md-outline-variant bg-md-surface-container-low px-3 py-1.5 text-[12px] font-medium leading-relaxed text-md-on-surface-variant"
          >
            <span className="material-symbols-outlined mt-px text-[14px]" aria-hidden>
              warning
            </span>
            <span className="break-keep">
              보고서 서버 응답 없음 — 보고서 요청은 복구 후 처리됩니다. 채팅·검색은 정상입니다.
            </span>
          </div>
        ) : null}
        {/* 한도 초과 — placeholder만으론 리셋 시점을 알 수 없어 배너로 명시 */}
        {overLimit && overLimitNotice ? (
          <div
            role="status"
            className="mx-auto mb-2 flex w-fit items-center gap-1.5 rounded-full border border-md-error/50 bg-md-error-container/30 px-3 py-1 text-[12px] font-medium text-md-on-error-container"
          >
            <span className="material-symbols-outlined text-[14px]" aria-hidden>
              hourglass_disabled
            </span>
            {overLimitNotice}
          </div>
        ) : null}
        {/* 쿼터 80% 사전 경고 (UX 배치 #5) — 초과 배너와 중복 X (상위에서 배타 계산).
            세션 내 dismiss 가능한 얇은 배너. */}
        {!overLimit && quotaWarning && !quotaWarnDismissed ? (
          <div
            role="status"
            className="mx-auto mb-2 flex w-fit items-center gap-1.5 rounded-full border border-md-tertiary/50 bg-md-tertiary-fixed/40 px-3 py-1 text-[12px] font-medium text-md-on-surface"
          >
            <span className="material-symbols-outlined text-[14px]" aria-hidden>
              data_usage
            </span>
            {quotaWarning}
            <button
              type="button"
              onClick={dismissQuotaWarn}
              aria-label="사용량 경고 닫기"
              className="ml-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
            >
              <span className="material-symbols-outlined text-[13px]" aria-hidden>
                close
              </span>
            </button>
          </div>
        ) : null}
        {/* floating 카드 — 더 강한 그림자(부양감), 더 큰 둥근 모서리. focus·hover 단계 강조. */}
        <div
          data-tour="input"
          onDragEnter={onDragEnter}
          onDragLeave={onDragLeave}
          onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()}
          onDrop={onDrop}
          className={
            "group/input relative flex flex-col rounded-[28px] border bg-md-surface shadow-[0_12px_40px_-12px_rgba(0,0,0,0.18),0_2px_8px_-2px_rgba(0,0,0,0.08)] transition-all duration-[var(--motion-base)] hover:shadow-[0_16px_48px_-12px_rgba(0,0,0,0.22),0_2px_8px_-2px_rgba(0,0,0,0.10)] focus-within:border-md-primary focus-within:shadow-[0_20px_56px_-12px_rgba(0,0,0,0.26),0_4px_12px_-2px_rgba(0,0,0,0.12)] " +
            (dragOver
              ? "border-md-primary border-dashed"
              : "border-md-outline-variant/60 hover:border-md-outline-variant/80")
          }
        >
          {/* 드롭 안내 오버레이 */}
          {dragOver ? (
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-[28px] bg-md-primary-container/40">
              <span className="inline-flex items-center gap-2 rounded-pill bg-md-surface px-4 py-2 text-[13px] font-medium text-md-on-surface shadow-sm">
                <span className="material-symbols-outlined text-[18px] text-md-primary" aria-hidden>
                  upload_file
                </span>
                여기에 놓아 첨부 — PDF·DOCX·HWPX·TXT
              </span>
            </div>
          ) : null}
          {/* 첨부 칩 — 업로드된 문서. 전송하면 비워진다. */}
          {attachments.length > 0 || uploading ? (
            <div className="flex flex-wrap items-center gap-1.5 px-5 pb-0 pt-3.5">
              {attachments.map((a) => (
                <span
                  key={a.name}
                  className="inline-flex max-w-[260px] items-center gap-1.5 rounded-pill border border-md-outline-variant bg-md-surface-container-low py-1 pl-2.5 pr-1 text-[12px] text-md-on-surface"
                  title={`${a.name} · ${a.chars.toLocaleString()}자${a.truncated ? " (일부만 첨부됨)" : ""}`}
                >
                  <span className="material-symbols-outlined text-[14px] text-md-on-surface-variant" aria-hidden>
                    description
                  </span>
                  <span className="min-w-0 truncate">{a.name}</span>
                  <span className="shrink-0 tabular-nums text-[10.5px] text-md-on-surface-variant">
                    {a.truncated ? "일부 " : ""}{Math.round(a.chars / 1000)}k자
                  </span>
                  <button
                    type="button"
                    aria-label={`${a.name} 첨부 제거`}
                    onClick={() =>
                      setAttachments((prev) => prev.filter((x) => x.name !== a.name))
                    }
                    className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-md-on-surface-variant transition-colors hover:bg-md-surface-container-high hover:text-md-on-surface"
                  >
                    <span className="material-symbols-outlined text-[13px]" aria-hidden>
                      close
                    </span>
                  </button>
                </span>
              ))}
              {uploading ? (
                <span className="inline-flex items-center gap-1.5 rounded-pill border border-md-outline-variant/60 px-2.5 py-1 text-[12px] text-md-on-surface-variant">
                  <span className="material-symbols-outlined animate-spin text-[14px]" aria-hidden>
                    progress_activity
                  </span>
                  파일 읽는 중…
                </span>
              ) : null}
            </div>
          ) : null}
          {/* textarea 영역 — 우측에 floating 전송 버튼. 크기 키움(텍스트 15px, padding ↑). */}
          <div className="relative">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={inputLocked}
              placeholder={
                running
                  ? "답변 생성 중… 정지 버튼으로 중단"
                  : overLimit
                    ? "사용량 한도 초과 — 한도 리셋 후 다시 가능"
                    : disabled
                      ? "설정을 먼저 입력하세요"
                      : irbMode
                        ? "IRB/DRB 심의에 대해 물어보세요 — 심의 대상 판정·절차·서식 (화순전남대병원 기준)"
                        : "MEDIREG AI에 메시지 보내기"
              }
              rows={MIN_ROWS}
              className="block w-full resize-none border-0 bg-transparent px-6 pb-3 pr-16 pt-5 text-[15px] leading-[1.6] text-md-on-surface placeholder:text-md-on-surface-variant focus:outline-none disabled:cursor-not-allowed disabled:text-md-on-surface-variant"
            />
            {/* 전송/정지 버튼 — textarea 우측 상단 inline floating. 크기 키움 (h-10). */}
            <div className="absolute right-3 top-3">
              {running ? (
                <button
                  type="button"
                  onClick={onStop}
                  aria-label="정지 (Esc)"
                  title="정지 (Esc)"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-md-error text-md-on-error transition-opacity hover:opacity-90"
                >
                  <span className="material-symbols-outlined text-[22px]" aria-hidden>
                    stop
                  </span>
                </button>
              ) : (
                <button
                  type="button"
                  onClick={trySend}
                  disabled={sendDisabled}
                  aria-label="전송"
                  title="전송 (Enter)"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-md-primary text-md-on-primary transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:bg-md-surface-container-high disabled:text-md-on-surface-variant disabled:opacity-60"
                >
                  <span className="material-symbols-outlined text-[22px]" aria-hidden>
                    arrow_upward
                  </span>
                </button>
              )}
            </div>
          </div>

          {/* 하단 toolbar — 첨부·@피드백·심층 보고서. 좌측만 사용 (전송은 위로 이동). */}
          <div className="flex items-center gap-1 px-3 pb-3">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT_EXT}
              multiple
              className="hidden"
              onChange={(e) => void handleFiles(e.target.files)}
            />
            <button
              type="button"
              data-tour="attach"
              onClick={() => fileInputRef.current?.click()}
              disabled={running || uploading || attachments.length >= MAX_ATTACHMENTS}
              aria-label="파일 첨부 (PDF·DOCX·HWPX·TXT)"
              title={
                attachments.length >= MAX_ATTACHMENTS
                  ? `첨부는 ${MAX_ATTACHMENTS}개까지`
                  : "파일 첨부 — PDF·DOCX·HWPX·TXT (스캔 PDF·구형 HWP 제외)"
              }
              className="inline-flex h-9 w-9 items-center justify-center rounded-full text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low hover:text-md-on-surface disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden>
                attach_file
              </span>
            </button>
            {/* IRB/DRB 모드 — AI 키워드 감지와 별개의 명시 진입(이중 접근).
                켜면 화순전남대병원 심의 지침 기반으로 안내됨을 배지로 표시. */}
            <button
              type="button"
              data-tour="irb"
              onClick={() => setIrbMode((v) => !v)}
              aria-pressed={irbMode}
              aria-label={
                irbMode
                  ? "IRB/DRB 상담 모드 해제"
                  : "IRB/DRB 상담 모드 — 연구 심의(IRB)·의료데이터 심의(DRB) 전문 안내"
              }
              title={
                irbMode
                  ? "IRB/DRB 상담 모드 해제"
                  : "IRB/DRB 상담 — 연구 심의 대상 판정·절차·서식 안내 (화순전남대병원 기준)"
              }
              className={
                "inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors " +
                (irbMode
                  ? "bg-md-primary-fixed text-md-on-primary-fixed-variant shadow-sm"
                  : "text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface")
              }
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                clinical_notes
              </span>
              IRB/DRB
            </button>
            <button
              type="button"
              onClick={toggleFeedback}
              aria-pressed={hasFeedbackPrefix}
              aria-label={hasFeedbackPrefix ? "피드백 모드 해제" : "피드백 모드 (운영팀에 자유 의견 전송)"}
              title={hasFeedbackPrefix ? "피드백 모드 해제" : "피드백 모드 (운영팀에 자유 의견 전송)"}
              className={
                "inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors " +
                (hasFeedbackPrefix
                  ? "bg-md-primary-fixed text-md-on-primary-fixed-variant shadow-sm"
                  : "text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface")
              }
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                forum
              </span>
              피드백
            </button>
            {/* 심층 보고서 수동 트리거 — AI 제안(next_steps)에만 의존하던 발견성 개선.
                일반 상담 모드에서는 감춘다(2026-10-01 모드 분기). */}
            {onManualReport && showPro ? (
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    disabled={running || overLimit || reportsAvail.paused}
                    data-tour="report"
                    aria-label={
                      reportsAvail.paused
                        ? "심층 보고서 — 점검 중"
                        : "심층 보고서 생성 — 목적 선택 (약 5~20분 소요)"
                    }
                    title={
                      reportsAvail.paused
                        ? (reportsAvail.message ?? "보고서 기능 점검 중입니다.")
                        : "지금까지의 대화 내용으로 심층 보고서 생성 (약 5~20분 소요)"
                    }
                    className="inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low hover:text-md-on-surface disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <span className="material-symbols-outlined text-[16px]" aria-hidden>
                      lab_profile
                    </span>
                    심층 보고서
                  </button>
                </PopoverTrigger>
                <PopoverContent side="top" align="start" className="w-[260px] p-1.5">
                  <p className="px-2 pb-0.5 pt-0.5 text-[11px] font-semibold text-md-on-surface-variant">
                    보고서 목적
                  </p>
                  <p className="px-2 pb-1 text-[10.5px] leading-snug text-md-on-surface-variant/80">
                    보통 5~20분, 길면 <b>1시간</b>까지 걸립니다. 기다리지 않아도
                    돼요 — 완료되면 사이드바·우측 패널·<b>이메일</b>로 받아봅니다.
                  </p>
                  {[
                    { v: null, label: "종합 (기본)", desc: "전체 균형" },
                    { v: "license_strategy", label: "허가 전략", desc: "경로·요건·판단 포인트" },
                    { v: "reg_summary", label: "규제 요약", desc: "적용 규제 전체 지도" },
                    { v: "change_response", label: "변경 대응", desc: "개정 영향·대응 액션" },
                  ].map((o) => (
                    <button
                      key={o.label}
                      type="button"
                      onClick={() => onManualReport(o.v)}
                      className="flex w-full flex-col rounded px-2 py-1.5 text-left transition-colors hover:bg-md-surface-container"
                    >
                      <span className="text-[12.5px] font-medium text-md-on-surface">{o.label}</span>
                      <span className="text-[11px] text-md-on-surface-variant">{o.desc}</span>
                    </button>
                  ))}
                  <ReportEmailOptRow />
                </PopoverContent>
              </Popover>
            ) : null}
            <div className="ml-auto flex items-center gap-2">
              {/* 글자수 카운터 — 상한 75% 부터 노출, 초과 시 오류색(전송도 차단) */}
              {value.length >= COUNTER_SHOW_AT ? (
                <span
                  role="status"
                  className={
                    "tabular-nums text-[11px] " +
                    (overChars ? "font-semibold text-md-error" : "text-md-on-surface-variant")
                  }
                  title={overChars ? "상한 초과 — 긴 문서는 파일로 첨부해 주세요" : "입력 글자 수"}
                >
                  {value.length.toLocaleString()} / {MAX_INPUT_CHARS.toLocaleString()}자
                </span>
              ) : null}
              {showPro ? (
                <div data-tour="style">
                  <AnswerStyleToggle />
                </div>
              ) : null}
            </div>
          </div>
        </div>

        {/* 면책 상시 노출 — 정본은 GET /legal (백엔드 src/legal.py) */}
        <DisclaimerHint />
      </div>
    </div>
  );
}

/** 답변 설명 수준 토글 — 기본/전문가/쉬움. localStorage 저장, 매 전송에 style 로 동반. */
function AnswerStyleToggle() {
  const [style, setStyle] = useState<"expert" | "simple" | null>(() => getAnswerStyle());
  const pick = (v: "expert" | "simple" | null) => {
    setAnswerStyle(v);
    setStyle(v);
  };
  const OPTIONS: Array<{ v: "expert" | "simple" | null; label: string; title: string }> = [
    { v: null, label: "기본", title: "기본 설명 수준" },
    { v: "expert", label: "전문가", title: "RA/QA 대상 — 조문 중심, 간결" },
    { v: "simple", label: "쉬움", title: "비전문가 대상 — 쉬운 용어·한 줄 해설" },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="답변 설명 수준"
      className="inline-flex items-center rounded-pill bg-md-surface-container p-0.5"
    >
      {OPTIONS.map((o) => (
        <button
          key={o.label}
          type="button"
          role="radio"
          aria-checked={style === o.v}
          title={o.title}
          onClick={() => pick(o.v)}
          className={
            "rounded-pill px-2.5 py-1 text-[11px] font-medium transition-colors " +
            (style === o.v
              ? "bg-md-surface text-md-on-surface shadow-sm"
              : "text-md-on-surface-variant hover:text-md-on-surface")
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}


/** 보고서 완료 이메일 수신 토글 — 서버 설정(/me/prefs)과 동기. */
function ReportEmailOptRow() {
  const [optIn, setOptIn] = useState<boolean | null>(null);
  useEffect(() => {
    void getMyPrefs()
      .then((p) => setOptIn(p.report_email_opt_in))
      .catch(() => setOptIn(true));
  }, []);
  if (optIn === null) return null;
  return (
    <label className="mt-1 flex cursor-pointer items-center gap-2 border-t border-md-outline-variant/60 px-2 pb-1 pt-2">
      <input
        type="checkbox"
        checked={optIn}
        onChange={(e) => {
          const v = e.target.checked;
          setOptIn(v);
          void setReportEmailOptIn(v)
            .then(() => toast.success(v ? "완료 시 이메일로 보내드릴게요" : "이메일 수신을 끕니다"))
            .catch(() => {
              setOptIn(!v);
              toast.error("설정 저장 실패");
            });
        }}
        className="size-3.5 accent-[var(--md-primary)]"
      />
      <span className="text-[11.5px] text-md-on-surface-variant">
        완료 시 <b className="text-md-on-surface">이메일</b>로 받기 (Word 첨부)
      </span>
    </label>
  );
}
