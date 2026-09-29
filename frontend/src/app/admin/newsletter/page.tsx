"use client";

/**
 * Admin · 뉴스레터(2026-09-22) — backend `/admin/newsletters*`. 권한: '메일 발신'.
 *
 * - 작성·수정: 제목 + 본문(HTML 직접/파일 불러오기, 또는 평문 → 서비스 테마 템플릿)
 * - 미리보기: 모달 — 메일 앱처럼 보낸 사람·받는 사람·제목 머리 + 본문(sandbox iframe, 스크립트 없음).
 *   HTML/텍스트 버전 전환. 작성 화면을 넓게 쓰려고 인라인 칸을 없앴다(2026-09-22).
 * - 수신자: 기본은 가입 회원만(미가입 초대자는 옵션), 테스트 계정은 서버가 뺀다.
 *   미동의(수신거부·광고성 미동의)·탈퇴는 비활성 — 보이기만 하고 고를 수 없다. 서버도 발송 시 다시 거른다.
 *   마케팅 동의/미동의 묶음 선택 체크박스.
 * - 발송 이력: 회차별로 누구에게 나갔는지(성공/실패) + 제외된 주소와 사유.
 *
 * 저장 전 변경분이 있으면 발송을 막는다 — 화면에 보이는 것과 나가는 것이 달라지지 않게.
 */

import { SUPPORT_EMAIL } from "@/lib/site";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  createNewsletter,
  deleteNewsletter,
  getNewsletter,
  listNewsletterRecipients,
  listNewsletters,
  previewNewsletter,
  sendNewsletter,
  updateNewsletter,
  type Newsletter,
  type NewsletterDraft,
  type NewsletterMeta,
  type NewsletterRecipient,
  type NewsletterSendRun,
} from "@/lib/client/admin";
import { ErrorBanner, PillTab, Spinner, formatTime } from "@/components/admin/common";
import { useConfirm } from "@/components/admin/use-confirm";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

type Mode = "html" | "text";
type Tab = "compose" | "recipients" | "history";

const EMPTY: NewsletterDraft = {
  subject: "",
  body_html: "",
  body_text: "",
  marketing: false,
  reply_to: "",
  source_filename: null,
};

function errMsg(err: unknown): string {
  const body = (err as { body?: string })?.body;
  if (body) {
    try {
      const d = JSON.parse(body).detail;
      if (typeof d === "string") return d;
    } catch {
      /* 원문 */
    }
  }
  return err instanceof Error ? err.message : String(err);
}

export default function AdminNewsletterPage() {
  const [items, setItems] = useState<NewsletterMeta[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [current, setCurrent] = useState<Newsletter | null>(null);
  const [draft, setDraft] = useState<NewsletterDraft>(EMPTY);
  const [mode, setMode] = useState<Mode>("html");
  const [tab, setTab] = useState<Tab>("compose");
  const [saving, setSaving] = useState(false);
  const { confirm, confirmDialog } = useConfirm();

  const reloadList = useCallback(async () => {
    setLoadingList(true);
    try {
      setItems(await listNewsletters());
      setError(null);
    } catch (err) {
      console.error("[admin/newsletter] list failed", err);
      setError(`목록을 불러오지 못했습니다 — ${errMsg(err)}`);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    void reloadList();
  }, [reloadList]);

  const open = useCallback(async (id: string) => {
    try {
      const n = await getNewsletter(id);
      setSelectedId(id);
      setCurrent(n);
      setDraft({
        subject: n.subject,
        body_html: n.body_html,
        body_text: n.body_text,
        marketing: n.marketing,
        reply_to: n.reply_to ?? "",
        source_filename: n.source_filename,
      });
      setMode(n.body_html?.trim() ? "html" : "text");
    } catch (err) {
      toast.error(`불러오지 못했습니다 — ${errMsg(err)}`);
    }
  }, []);

  const startNew = () => {
    setSelectedId(null);
    setCurrent(null);
    setDraft(EMPTY);
    setMode("html");
    setTab("compose");
  };

  // 저장본과 다른가 — 다르면 발송 금지
  const dirty = useMemo(() => {
    const base = current
      ? {
          subject: current.subject,
          body_html: current.body_html,
          body_text: current.body_text,
          marketing: current.marketing,
          reply_to: current.reply_to ?? "",
        }
      : { subject: "", body_html: "", body_text: "", marketing: false, reply_to: "" };
    const now = {
      subject: draft.subject,
      body_html: mode === "html" ? draft.body_html ?? "" : "",
      body_text: draft.body_text ?? "",
      marketing: !!draft.marketing,
      reply_to: draft.reply_to ?? "",
    };
    return JSON.stringify(base) !== JSON.stringify(now);
  }, [current, draft, mode]);

  const payload = (): NewsletterDraft => ({
    subject: draft.subject.trim(),
    body_html: mode === "html" ? draft.body_html ?? "" : "",
    body_text: draft.body_text ?? "",
    marketing: !!draft.marketing,
    reply_to: (draft.reply_to ?? "").trim() || null,
    source_filename: mode === "html" ? draft.source_filename ?? null : null,
  });

  const save = async (): Promise<Newsletter | null> => {
    setSaving(true);
    try {
      const n = selectedId ? await updateNewsletter(selectedId, payload()) : await createNewsletter(payload());
      setSelectedId(n.id);
      setCurrent({ ...n, sends: current?.sends });
      toast.success("저장했습니다");
      void reloadList();
      return n;
    } catch (err) {
      toast.error(`저장하지 못했습니다 — ${errMsg(err)}`);
      return null;
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!selectedId) return;
    if (!(await confirm({ title: "이 뉴스레터를 삭제할까요?", description: "되돌릴 수 없습니다.", danger: true, confirmLabel: "삭제" })))
      return;
    try {
      await deleteNewsletter(selectedId);
      toast.success("삭제했습니다");
      startNew();
      void reloadList();
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  const duplicate = () => {
    setSelectedId(null);
    setCurrent(null);
    setDraft((d) => ({ ...d, subject: `${d.subject} (사본)` }));
    setTab("compose");
    toast.message("사본을 만들었습니다 — 저장하면 새 뉴스레터가 됩니다");
  };

  const refreshCurrent = async () => {
    if (selectedId) {
      const n = await getNewsletter(selectedId);
      setCurrent(n);
    }
    void reloadList();
  };

  return (
    <main className="flex flex-col gap-5">
      {confirmDialog}
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-h1 text-md-on-surface">뉴스레터</h1>
        <span className="text-[12.5px] text-md-on-surface-variant">
          작성 · 미리보기 · 수신자 선택 · 발송 이력
        </span>
      </header>

      <ErrorBanner message={error} />

      <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* 목록 */}
        <aside className="flex flex-col gap-2">
          <button
            type="button"
            onClick={startNew}
            className="inline-flex items-center justify-center gap-1 rounded-pill bg-md-primary px-4 py-2 text-[13px] font-semibold text-md-on-primary hover:bg-md-primary-container"
          >
            <span className="material-symbols-outlined text-[17px]" aria-hidden>
              add
            </span>
            새 뉴스레터
          </button>
          {loadingList ? <Spinner /> : null}
          <ul className="flex flex-col gap-1">
            {items.map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => void open(m.id)}
                  className={`flex w-full flex-col gap-0.5 rounded-card border px-3 py-2 text-left transition-colors ${
                    selectedId === m.id
                      ? "border-md-primary bg-md-surface-container-low"
                      : "border-md-outline-variant hover:bg-md-surface-container-low"
                  }`}
                >
                  <span className="line-clamp-2 text-[13px] font-medium text-md-on-surface">{m.subject}</span>
                  <span className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-md-on-surface-variant">
                    {m.send_runs ? (
                      <span className="rounded-pill bg-md-primary-container px-1.5 text-md-on-primary-container">
                        발송 {m.sent_count}명
                      </span>
                    ) : (
                      <span className="rounded-pill border border-md-outline-variant px-1.5">초안</span>
                    )}
                    {m.marketing ? <span className="rounded-pill border border-md-outline-variant px-1.5">광고</span> : null}
                    <span>{formatTime(m.last_sent_at ?? m.updated_at)}</span>
                  </span>
                </button>
              </li>
            ))}
            {!items.length && !loadingList ? (
              <li className="px-1 text-[12.5px] text-md-on-surface-variant">아직 작성한 뉴스레터가 없습니다.</li>
            ) : null}
          </ul>
        </aside>

        {/* 편집 영역 */}
        <section className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <PillTab active={tab === "compose"} label="작성" onClick={() => setTab("compose")} />
            <PillTab
              active={tab === "recipients"}
              label="수신자·발송"
              onClick={() => setTab("recipients")}
            />
            <PillTab
              active={tab === "history"}
              label={`발송 이력${current?.sends?.length ? ` (${current.sends.filter((r) => !r.test).length})` : ""}`}
              onClick={() => setTab("history")}
            />
            <span className="ml-auto flex items-center gap-2">
              {dirty ? <span className="text-[12px] text-md-error">저장 안 됨</span> : null}
              {selectedId ? (
                <>
                  <button type="button" onClick={duplicate} className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12.5px] hover:bg-md-surface-container-low">
                    사본
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove()}
                    disabled={!!current?.send_runs}
                    title={current?.send_runs ? "발송 이력이 있는 뉴스레터는 기록 보존을 위해 삭제할 수 없습니다" : undefined}
                    className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12.5px] text-md-error hover:bg-md-surface-container-low disabled:opacity-40"
                  >
                    삭제
                  </button>
                </>
              ) : null}
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving || !draft.subject.trim()}
                className="rounded-pill bg-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-on-primary hover:bg-md-primary-container disabled:opacity-50"
              >
                {saving ? "저장 중…" : "저장"}
              </button>
            </span>
          </div>

          {tab === "compose" ? (
            <Composer draft={draft} setDraft={setDraft} mode={mode} setMode={setMode} />
          ) : tab === "recipients" ? (
            selectedId && current ? (
              <Recipients
                newsletter={current}
                dirty={dirty}
                onSent={async () => {
                  await refreshCurrent();
                  setTab("history");
                }}
                confirm={confirm}
              />
            ) : (
              <Hint>먼저 작성 탭에서 저장하세요.</Hint>
            )
          ) : current ? (
            <History runs={current.sends ?? []} />
          ) : (
            <Hint>저장된 뉴스레터를 고르면 발송 이력이 보입니다.</Hint>
          )}
        </section>
      </div>
    </main>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-card border border-dashed border-md-outline-variant px-4 py-6 text-center text-body-sm text-md-on-surface-variant">
      {children}
    </p>
  );
}

/* ─────────────────── 작성·미리보기 ─────────────────── */

function Composer({
  draft,
  setDraft,
  mode,
  setMode,
}: {
  draft: NewsletterDraft;
  setDraft: React.Dispatch<React.SetStateAction<NewsletterDraft>>;
  mode: Mode;
  setMode: (m: Mode) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [showText, setShowText] = useState(false);

  const loadFile = (f: File | undefined) => {
    if (!f) return;
    if (f.size > 1_000_000) {
      toast.error("1MB 이하 HTML 만 불러올 수 있습니다");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const html = String(reader.result ?? "");
      // <title> 이 있고 제목이 비어 있으면 제목으로
      const title = /<title[^>]*>([^<]*)<\/title>/i.exec(html)?.[1]?.trim();
      setDraft((d) => ({
        ...d,
        body_html: html,
        source_filename: f.name,
        subject: d.subject.trim() ? d.subject : title ?? d.subject,
      }));
      setMode("html");
      toast.success(`${f.name} 불러옴`);
    };
    reader.onerror = () => toast.error("파일을 읽지 못했습니다");
    reader.readAsText(f, "utf-8");
  };

  const hasBody = mode === "html" ? !!draft.body_html?.trim() : !!draft.body_text?.trim();
  const openPreview = async () => {
    setPreviewing(true);
    try {
      setPreview(
        await previewNewsletter({
          subject: draft.subject,
          body_html: mode === "html" ? draft.body_html : "",
          body_text: draft.body_text,
          marketing: draft.marketing,
          reply_to: draft.reply_to,
        }),
      );
    } catch (err) {
      toast.error(`미리보기 실패 — ${errMsg(err)}`);
    } finally {
      setPreviewing(false);
    }
  };

  const input =
    "h-10 w-full rounded border border-md-outline-variant bg-md-surface px-3 text-body-sm text-md-on-surface outline-none focus:border-md-primary";

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[12.5px] text-md-on-surface-variant">받는 사람이 보게 될 모습은 미리보기로 확인하세요.</span>
        <button
          type="button"
          onClick={() => void openPreview()}
          disabled={!hasBody || previewing}
          className="ml-auto inline-flex items-center gap-1 rounded-pill border border-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-primary hover:bg-md-primary-container/40 disabled:opacity-50"
        >
          <span className="material-symbols-outlined text-[16px]" aria-hidden>
            visibility
          </span>
          {previewing ? "불러오는 중…" : "미리보기"}
        </button>
      </div>
      {preview ? <EmailPreviewModal data={preview} onClose={() => setPreview(null)} /> : null}
        <label className="flex flex-col gap-1 text-body-sm">
          <span className="text-md-on-surface-variant">제목</span>
          <input
            className={input}
            value={draft.subject}
            maxLength={200}
            onChange={(e) => setDraft((d) => ({ ...d, subject: e.target.value }))}
            placeholder="[MEDIREG AI] 이번 달 새 기능 안내"
          />
        </label>
        <label className="flex items-start gap-2 rounded border border-md-outline-variant px-3 py-2 text-body-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={!!draft.marketing}
            onChange={(e) => setDraft((d) => ({ ...d, marketing: e.target.checked }))}
          />
          <span>
            광고성 정보(홍보·이벤트)
            <span className="block text-[12px] text-md-on-surface-variant">
              켜면 마케팅 수신 동의자에게만 발송되고 제목 앞에 ‘(광고)’가 자동으로 붙습니다. 기능 안내 등
              서비스 고지는 끄세요(안내 메일 수신 거부자만 제외).
            </span>
          </span>
        </label>
        <label className="flex flex-col gap-1 text-body-sm">
          <span className="text-md-on-surface-variant">회신 주소(비우면 서버 기본값)</span>
          <input
            className={input}
            value={draft.reply_to ?? ""}
            onChange={(e) => setDraft((d) => ({ ...d, reply_to: e.target.value }))}
            placeholder={SUPPORT_EMAIL}
          />
        </label>

        <div className="flex flex-wrap items-center gap-2">
          <PillTab active={mode === "html"} label="HTML" onClick={() => setMode("html")} />
          <PillTab active={mode === "text"} label="평문 → 서비스 템플릿" onClick={() => setMode("text")} />
          {mode === "html" ? (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".html,.htm,text/html"
                className="hidden"
                onChange={(e) => {
                  loadFile(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="ml-auto inline-flex items-center gap-1 rounded-pill border border-md-outline-variant px-3 py-1 text-[12.5px] hover:bg-md-surface-container-low"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  upload_file
                </span>
                HTML 파일 불러오기
              </button>
            </>
          ) : null}
        </div>
        {mode === "html" ? (
          <>
            {draft.source_filename ? (
              <p className="text-[12px] text-md-on-surface-variant">불러온 파일: {draft.source_filename}</p>
            ) : null}
            <textarea
              value={draft.body_html ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, body_html: e.target.value }))}
              spellCheck={false}
              placeholder="<html>…</html> 붙여넣기 또는 파일 불러오기"
              className="min-h-[360px] w-full rounded border border-md-outline-variant bg-md-surface p-3 font-mono text-[12px] leading-relaxed text-md-on-surface outline-none focus:border-md-primary"
            />
            <details open={showText} onToggle={(e) => setShowText((e.target as HTMLDetailsElement).open)}>
              <summary className="cursor-pointer text-[12.5px] text-md-on-surface-variant">
                평문 본문(선택) — HTML 을 막아 둔 메일 앱에 보이는 버전. 비우면 HTML 에서 자동 추출
              </summary>
              <textarea
                value={draft.body_text ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, body_text: e.target.value }))}
                className="mt-2 min-h-[140px] w-full rounded border border-md-outline-variant bg-md-surface p-3 text-[12.5px] text-md-on-surface outline-none focus:border-md-primary"
              />
            </details>
          </>
        ) : (
          <>
            <p className="text-[12px] text-md-on-surface-variant">
              <code>## 소제목</code> · <code>- 항목</code> · 빈 줄 = 문단 · 맨 URL 은 자동 링크
            </p>
            <textarea
              value={draft.body_text ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, body_text: e.target.value }))}
              className="min-h-[360px] w-full rounded border border-md-outline-variant bg-md-surface p-3 text-body-sm leading-relaxed text-md-on-surface outline-none focus:border-md-primary"
              placeholder={"안녕하세요, MEDIREG AI 입니다.\n\n## 이번 달 새 기능\n- …"}
            />
          </>
        )}
    </div>
  );
}

type PreviewData = { subject: string; html: string; text: string; from?: string | null; reply_to?: string | null };

/** 메일 앱처럼 — 머리(보낸 사람·받는 사람·회신·제목·시각) + 본문. 본문은 sandbox iframe(스크립트 없음). */
function EmailPreviewModal({ data, onClose }: { data: PreviewData; onClose: () => void }) {
  const [view, setView] = useState<"html" | "text">("html");
  const now = new Date().toLocaleString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  const sender = data.from || "MEDIREG AI (서버 발신 주소)";
  const senderName = /^(.*?)\s*<[^>]+>$/.exec(sender)?.[1] || sender.split("@")[0];
  return (
    <Dialog open onOpenChange={(o) => (!o ? onClose() : null)}>
      <DialogContent className="flex h-[92vh] max-w-[min(960px,96vw)] flex-col gap-0 overflow-hidden border border-md-outline-variant bg-md-surface p-0 text-md-on-surface sm:max-w-[min(960px,96vw)]">
        {/* 메일 머리 */}
        <div className="flex flex-col gap-3 border-b border-md-outline-variant px-6 pb-4 pt-5">
          <DialogTitle className="pr-8 text-[20px] font-semibold leading-snug">
            {data.subject || "(제목 없음)"}
          </DialogTitle>
          <div className="flex items-start gap-3">
            <span
              className="flex size-10 shrink-0 items-center justify-center rounded-full bg-md-primary text-[16px] font-semibold text-md-on-primary"
              aria-hidden
            >
              {(senderName || "M").trim().charAt(0).toUpperCase()}
            </span>
            <div className="min-w-0 flex-1 text-[13px] leading-relaxed">
              <p className="truncate">
                <b className="font-semibold">{senderName}</b>{" "}
                <span className="text-md-on-surface-variant">&lt;{/<([^>]+)>/.exec(sender)?.[1] ?? sender}&gt;</span>
              </p>
              <p className="truncate text-md-on-surface-variant">받는 사람: 나 (수신자별 개별 발송 — 서로의 주소는 보이지 않음)</p>
              {data.reply_to ? (
                <p className="truncate text-md-on-surface-variant">회신: {data.reply_to}</p>
              ) : null}
            </div>
            <span className="shrink-0 text-[12px] text-md-on-surface-variant">{now}</span>
          </div>
          <div className="flex items-center gap-2">
            <PillTab active={view === "html"} label="HTML" onClick={() => setView("html")} />
            <PillTab active={view === "text"} label="텍스트 버전" onClick={() => setView("text")} />
            <span className="text-[11.5px] text-md-on-surface-variant">
              텍스트 버전 = HTML 을 막아 둔 메일 앱에 보이는 내용
            </span>
          </div>
        </div>
        {/* 본문 — 메일 앱 읽기 창처럼 회색 바탕 위 */}
        <div className="min-h-0 flex-1 overflow-auto bg-[#f1f3f4] p-4">
          {view === "html" ? (
            <iframe
              title="뉴스레터 미리보기"
              srcDoc={data.html}
              sandbox=""
              className="mx-auto block h-full min-h-[600px] w-full max-w-[800px] rounded bg-white shadow-sm"
            />
          ) : (
            <pre className="mx-auto max-w-[800px] whitespace-pre-wrap rounded bg-white p-6 font-sans text-[13.5px] leading-relaxed text-[#202124] shadow-sm">
              {data.text || "(비어 있음)"}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* ─────────────────── 수신자·발송 ─────────────────── */

function Recipients({
  newsletter,
  dirty,
  onSent,
  confirm,
}: {
  newsletter: Newsletter;
  dirty: boolean;
  onSent: () => Promise<void>;
  confirm: ReturnType<typeof useConfirm>["confirm"];
}) {
  const [rows, setRows] = useState<NewsletterRecipient[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [hideAdmins, setHideAdmins] = useState(false);
  const [showInvitees, setShowInvitees] = useState(false); // 미가입 초대자 — 기본 숨김
  const [hideReceived, setHideReceived] = useState(true);
  const [showBlocked, setShowBlocked] = useState(true);
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listNewsletterRecipients(newsletter.marketing, newsletter.id);
      setRows(r.recipients);
      setError(null);
    } catch (err) {
      setError(`수신자를 불러오지 못했습니다 — ${errMsg(err)}`);
    } finally {
      setLoading(false);
    }
  }, [newsletter.marketing, newsletter.id]);

  useEffect(() => {
    setPicked(new Set());
    void load();
  }, [load]);

  const visible = rows.filter((r) => {
    if (!showInvitees && !r.member) return false;
    if (hideAdmins && r.is_internal) return false;
    if (hideReceived && r.received_at) return false;
    if (!showBlocked && !r.eligible) return false;
    const k = q.trim().toLowerCase();
    if (!k) return true;
    return [r.email, r.display_name, r.affiliation, r.admin_memo].some((v) => (v ?? "").toLowerCase().includes(k));
  });
  const selectable = visible.filter((r) => r.eligible);
  const allPicked = selectable.length > 0 && selectable.every((r) => picked.has(r.email));
  // 마케팅 동의/미동의 묶음 — 보이는 선택 가능 대상 기준
  const mkYes = selectable.filter((r) => r.marketing_opt_in);
  const mkNo = selectable.filter((r) => !r.marketing_opt_in);
  const groupState = (g: NewsletterRecipient[]) =>
    g.length === 0 ? "none" : g.every((r) => picked.has(r.email)) ? "all" : g.some((r) => picked.has(r.email)) ? "some" : "none";
  const toggleGroup = (g: NewsletterRecipient[]) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (groupState(g) === "all") g.forEach((r) => next.delete(r.email));
      else g.forEach((r) => next.add(r.email));
      return next;
    });
  const blockedCount = rows.filter((r) => !r.eligible).length;
  const pickedList = rows.filter((r) => picked.has(r.email) && r.eligible);
  const pickedReceived = pickedList.filter((r) => r.received_at).length;

  const toggle = (email: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });

  const sendTest = async () => {
    const ok = await confirm({
      title: "나에게 테스트 메일을 보낼까요?",
      description:
        `제목: [테스트] ${newsletter.marketing ? "(광고) " : ""}${newsletter.subject}\n` +
        "로그인한 관리자 본인 주소로 1통만 나갑니다. 수신 기록에는 남지 않습니다.",
      confirmLabel: "테스트 발송",
    });
    if (!ok) return;
    setSending(true);
    try {
      await sendNewsletter(newsletter.id, { test: true });
      toast.success("테스트 메일을 내 주소로 보냈습니다");
      await onSent();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSending(false);
    }
  };

  const send = async () => {
    const n = pickedList.length;
    if (!n) return;
    // 발송 전 최종 확인 — 제목·유형·받는 사람 명단(앞 10명)·내부 계정·재수신을 한 번에 보여준다.
    const internal = pickedList.filter((r) => r.is_internal).length;
    const names = pickedList
      .slice(0, 10)
      .map((r) => `· ${r.email}${r.display_name ? ` (${r.display_name})` : ""}`)
      .join("\n");
    const ok = await confirm({
      title: `⚠️ ${n}명에게 실제로 발송합니다`,
      description:
        `제목: ${newsletter.marketing ? "(광고) " : ""}${newsletter.subject}\n` +
        `유형: ${newsletter.marketing ? "광고성(마케팅 동의자만)" : "서비스 안내"}\n\n` +
        `받는 사람:\n${names}${n > 10 ? `\n· 외 ${n - 10}명` : ""}\n\n` +
        (internal ? `관리자·테스트 계정 ${internal}명 포함.\n` : "") +
        (pickedReceived ? `이미 받은 ${pickedReceived}명은 한 번 더 받습니다.\n` : "") +
        "발송하면 되돌릴 수 없습니다. 테스트 발송으로 먼저 확인하셨나요?",
      confirmLabel: `${n}명에게 발송`,
      danger: true,
    });
    if (!ok) return;
    setSending(true);
    try {
      const run: NewsletterSendRun = await sendNewsletter(newsletter.id, { emails: pickedList.map((r) => r.email) });
      toast.success(
        `발송 ${run.sent}/${run.requested}` +
          (run.failed ? ` · 실패 ${run.failed}` : "") +
          (run.skipped.length ? ` · 제외 ${run.skipped.length}` : "") +
          (run.smtp_configured ? "" : " (SMTP 미설정 — 실제 발송 없음)"),
      );
      setPicked(new Set());
      await onSent();
    } catch (err) {
      toast.error(`발송하지 못했습니다 — ${errMsg(err)}`);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <ErrorBanner message={error} />
      <div className="rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-2.5 text-[12.5px] text-md-on-surface">
        {newsletter.marketing ? (
          <>광고성 뉴스레터 — <b>마케팅 수신 동의자</b>만 선택할 수 있습니다(미가입 초대자 제외).</>
        ) : (
          <>서비스 안내 — <b>안내 메일 수신 거부자</b>와 탈퇴 계정만 제외됩니다.</>
        )}{" "}
        선택할 수 없는 {blockedCount}명은 목록으로만 보입니다. 발송 시 서버가 한 번 더 확인합니다.
      </div>

      <div className="flex flex-wrap items-center gap-3 text-[12.5px]">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="이메일·이름·소속·메모 검색"
          className="h-9 w-60 rounded border border-md-outline-variant bg-md-surface px-3 text-body-sm outline-none focus:border-md-primary"
        />
        <label className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={hideReceived} onChange={(e) => setHideReceived(e.target.checked)} />
          이미 받은 사람 숨기기
        </label>
        <label className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={hideAdmins} onChange={(e) => setHideAdmins(e.target.checked)} />
          관리자 계정 숨기기
        </label>
        <label className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={showInvitees} onChange={(e) => setShowInvitees(e.target.checked)} />
          미가입 초대자도 보기
        </label>
        <label className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={showBlocked} onChange={(e) => setShowBlocked(e.target.checked)} />
          선택 불가 대상도 보기
        </label>
        {loading ? <Spinner size={15} /> : null}
      </div>

      {/* 묶음 선택 — 보이는 목록 중 선택 가능한 사람만 대상 */}
      <div className="flex flex-wrap items-center gap-4 rounded-card border border-md-outline-variant px-4 py-2 text-[12.5px]">
        <span className="text-md-on-surface-variant">묶음 선택</span>
        <GroupCheck label="마케팅 동의자" count={mkYes.length} state={groupState(mkYes)} onToggle={() => toggleGroup(mkYes)} />
        <GroupCheck label="마케팅 미동의자" count={mkNo.length} state={groupState(mkNo)} onToggle={() => toggleGroup(mkNo)} />
        {newsletter.marketing ? (
          <span className="text-[11.5px] text-md-on-surface-variant">광고성 뉴스레터라 미동의자는 선택할 수 없습니다.</span>
        ) : null}
      </div>

      <div className="overflow-x-auto rounded-card border border-md-outline-variant">
        <table className="min-w-full text-body-sm">
          <thead className="bg-md-surface-container-low text-[11.5px] font-semibold text-md-on-surface-variant">
            <tr>
              <th className="w-9 px-3 py-2 text-left">
                <input
                  type="checkbox"
                  aria-label="보이는 선택 가능 대상 전체 선택"
                  checked={allPicked}
                  disabled={!selectable.length}
                  onChange={() =>
                    setPicked((prev) => {
                      const next = new Set(prev);
                      if (allPicked) selectable.forEach((r) => next.delete(r.email));
                      else selectable.forEach((r) => next.add(r.email));
                      return next;
                    })
                  }
                />
              </th>
              <th className="px-3 py-2 text-left">수신자</th>
              <th className="px-3 py-2 text-left">구분</th>
              <th className="px-3 py-2 text-left">안내 메일</th>
              <th className="px-3 py-2 text-left">마케팅 동의</th>
              <th className="px-3 py-2 text-left">상태</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr
                key={r.email}
                className={`border-t border-md-outline-variant ${r.eligible ? "hover:bg-md-surface-container-low" : "opacity-55"}`}
              >
                <td className="px-3 py-1.5">
                  <input
                    type="checkbox"
                    aria-label={`${r.email} 선택`}
                    checked={r.eligible && picked.has(r.email)}
                    disabled={!r.eligible}
                    onChange={() => toggle(r.email)}
                  />
                </td>
                <td className="max-w-[320px] px-3 py-1.5">
                  <span className="block truncate text-md-on-surface">{r.email}</span>
                  {r.display_name || r.affiliation || r.admin_memo ? (
                    <span className="block truncate text-[11.5px] text-md-on-surface-variant">
                      {[r.display_name, r.affiliation, r.admin_memo && `메모: ${r.admin_memo}`].filter(Boolean).join(" · ")}
                    </span>
                  ) : null}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-md-on-surface-variant">{r.account_class_label}</td>
                <td className="whitespace-nowrap px-3 py-1.5">
                  <OptBadge on={r.notice_opt_in} onLabel="수신" offLabel="거부" />
                </td>
                <td className="whitespace-nowrap px-3 py-1.5">
                  <OptBadge on={r.marketing_opt_in} onLabel="동의" offLabel="미동의" />
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-[12px]">
                  {!r.eligible ? (
                    <span className="text-md-error">{r.reason_label}</span>
                  ) : r.received_at ? (
                    <span className="text-md-on-surface-variant">받음 {formatTime(r.received_at)}</span>
                  ) : (
                    <span className="text-md-on-surface-variant">—</span>
                  )}
                </td>
              </tr>
            ))}
            {!visible.length && !loading ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-md-on-surface-variant">
                  조건에 맞는 수신자가 없습니다.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="sticky bottom-0 flex flex-wrap items-center gap-3 rounded-card border border-md-outline-variant bg-md-surface px-4 py-3 shadow-sm">
        <span className="text-[13px] text-md-on-surface">
          선택 <b>{pickedList.length}</b>명
          {pickedReceived ? <span className="text-md-on-surface-variant"> (이미 받은 {pickedReceived}명 포함)</span> : null}
        </span>
        {dirty ? <span className="text-[12px] text-md-error">저장하지 않은 변경이 있습니다 — 저장 후 발송하세요.</span> : null}
        <button
          type="button"
          onClick={() => void sendTest()}
          disabled={sending || dirty}
          className="ml-auto rounded-pill border border-md-outline-variant px-4 py-1.5 text-[12.5px] hover:bg-md-surface-container-low disabled:opacity-50"
        >
          나에게 테스트 발송
        </button>
        <button
          type="button"
          onClick={() => void send()}
          disabled={sending || dirty || !pickedList.length}
          className="rounded-pill bg-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-on-primary hover:bg-md-primary-container disabled:opacity-50"
        >
          {sending ? "발송 중…" : `${pickedList.length}명에게 발송`}
        </button>
      </div>
    </div>
  );
}

function GroupCheck({
  label,
  count,
  state,
  onToggle,
}: {
  label: string;
  count: number;
  state: "all" | "some" | "none";
  onToggle: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  }, [state]);
  return (
    <label className={`inline-flex items-center gap-1.5 ${count ? "" : "opacity-50"}`}>
      <input ref={ref} type="checkbox" checked={state === "all"} disabled={!count} onChange={onToggle} />
      {label} <span className="tabular-nums text-md-on-surface-variant">({count})</span>
    </label>
  );
}

function OptBadge({ on, onLabel, offLabel }: { on: boolean; onLabel: string; offLabel: string }) {
  return (
    <span
      className={
        "inline-flex items-center rounded-pill px-1.5 py-0.5 text-[11px] font-medium " +
        (on ? "bg-md-primary-container text-md-on-primary-container" : "border border-md-outline-variant text-md-on-surface-variant")
      }
    >
      {on ? onLabel : offLabel}
    </span>
  );
}

/* ─────────────────── 발송 이력 ─────────────────── */

function History({ runs }: { runs: NewsletterSendRun[] }) {
  const [openId, setOpenId] = useState<string | null>(runs[0]?.id ?? null);
  if (!runs.length) return <Hint>아직 발송하지 않았습니다.</Hint>;
  return (
    <ul className="flex flex-col gap-2">
      {runs.map((r) => {
        const open = openId === r.id;
        return (
          <li key={r.id} className="rounded-card border border-md-outline-variant">
            <button
              type="button"
              onClick={() => setOpenId(open ? null : r.id)}
              className="flex w-full flex-wrap items-center gap-2 px-4 py-2.5 text-left hover:bg-md-surface-container-low"
              aria-expanded={open}
            >
              <span className="material-symbols-outlined text-[18px] text-md-on-surface-variant" aria-hidden>
                {open ? "expand_less" : "expand_more"}
              </span>
              <span className="text-[13px] font-medium tabular-nums text-md-on-surface">{formatTime(r.at)}</span>
              {r.test ? (
                <span className="rounded-pill border border-md-outline-variant px-1.5 text-[11px] text-md-on-surface-variant">테스트</span>
              ) : null}
              <span className="text-[12.5px] text-md-on-surface">
                성공 {r.sent}
                {r.failed ? <span className="text-md-error"> · 실패 {r.failed}</span> : null}
                {r.skipped.length ? <span className="text-md-on-surface-variant"> · 제외 {r.skipped.length}</span> : null}
              </span>
              {!r.smtp_configured ? <span className="text-[11.5px] text-md-error">SMTP 미설정(실제 발송 없음)</span> : null}
              <span className="ml-auto truncate text-[12px] text-md-on-surface-variant">{r.by ?? ""}</span>
            </button>
            {open ? (
              <div className="flex flex-col gap-3 border-t border-md-outline-variant px-4 py-3">
                <p className="text-[12px] text-md-on-surface-variant">제목: {r.subject}</p>
                <div>
                  <h3 className="mb-1 text-[12.5px] font-semibold text-md-on-surface">받은 사람 ({r.recipients.length})</h3>
                  <ul className="grid gap-x-4 gap-y-0.5 text-[12.5px] sm:grid-cols-2">
                    {r.recipients.map((x) => (
                      <li key={x.email} className="flex items-center gap-1.5">
                        <span
                          className={`material-symbols-outlined text-[15px] ${x.ok ? "text-md-success" : "text-md-error"}`}
                          aria-label={x.ok ? "성공" : "실패"}
                        >
                          {x.ok ? "check_circle" : "error"}
                        </span>
                        <span className="truncate">{x.email}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                {r.skipped.length ? (
                  <div>
                    <h3 className="mb-1 text-[12.5px] font-semibold text-md-on-surface">제외 ({r.skipped.length})</h3>
                    <ul className="text-[12.5px] text-md-on-surface-variant">
                      {r.skipped.map((x) => (
                        <li key={x.email}>
                          {x.email} — {x.reason_label}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
