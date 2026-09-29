"use client";

/**
 * 주간 이용 보고서 메일 패널(2026-09-21) — 자동 발송 상태·설정 + 미리보기·지금 보내기.
 *
 * 서버 안의 주기 작업이 지정 요일·시각(KST) 이후 첫 점검에 직전 주 보고서를 보낸다
 * (HTML 본문 + .html·.csv 첨부, 실사용 기준, LLM 요약 없음, 피드백은 자유 의견만). 본체는 backend `src/weekly_report.py`.
 * 설정(켜기/끄기·요일·시각·수신자)은 여기서 저장 → 재시작 없이 다음 점검부터 반영.
 * 서버 env 값은 기본값이고, 여기서 저장한 값이 우선한다. 수신자는 주소를 직접 추가·삭제(형식 검증).
 * '이번 주 업데이트'는 관리자 › 보고 노트에서 '포함'한 노트.
 */
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  getWeeklyReportPreview,
  getWeeklyReportStatus,
  patchWeeklyReportConfig,
  sendWeeklyReportNow,
  type WeeklyReportStatus,
} from "@/lib/client/admin";
import { useConfirm } from "@/components/admin/use-confirm";

const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

function kstLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type Draft = { enabled: boolean; weekday: number; hour: number; to: string[] };

export function WeeklyReportPanel() {
  const { confirm, confirmDialog } = useConfirm();
  const [st, setSt] = useState<WeeklyReportStatus | null>(null);
  const [busy, setBusy] = useState<"preview" | "send" | "save" | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [newTo, setNewTo] = useState("");

  // 수신자 추가(2026-09-21 — 관리자 메일 제한 해제, 형식만 확인. 서버도 같은 검증)
  const addRecipient = (raw: string) => {
    if (!draft) return;
    const em = raw.trim().toLowerCase();
    if (!/^[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(em)) {
      toast.error("메일 주소 형식을 확인하세요");
      return;
    }
    if (draft.to.includes(em)) {
      setNewTo("");
      return;
    }
    if (draft.to.length >= 20) {
      toast.error("수신자는 최대 20명입니다");
      return;
    }
    setDraft({ ...draft, to: [...draft.to, em] });
    setNewTo("");
  };

  const load = useCallback(async () => {
    try {
      setSt(await getWeeklyReportStatus());
    } catch (err) {
      console.error("[admin/stats] weekly report status failed", err);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const openEditor = () => {
    if (!st) return;
    setDraft({ enabled: st.config.enabled, weekday: st.config.weekday, hour: st.config.hour, to: [...st.config.to] });
    setEditing(true);
  };

  const save = async () => {
    if (!draft) return;
    if (!draft.to.length) {
      toast.error("수신자를 한 명 이상 추가하세요");
      return;
    }
    setBusy("save");
    try {
      setSt(await patchWeeklyReportConfig(draft));
      setEditing(false);
      toast.success("주간 보고서 설정을 저장했습니다");
    } catch (err) {
      console.error("[admin/stats] weekly report config failed", err);
      toast.error("저장하지 못했습니다");
    } finally {
      setBusy(null);
    }
  };

  const resetToDefault = async () => {
    const ok = await confirm({
      title: "서버 기본값으로 되돌릴까요?",
      description: "관리자 화면에서 저장한 설정을 지우고 서버 설정(env)을 따릅니다.",
      confirmLabel: "되돌리기",
    });
    if (!ok) return;
    setBusy("save");
    try {
      setSt(await patchWeeklyReportConfig({ reset: true }));
      setEditing(false);
      toast.success("서버 기본값으로 되돌렸습니다");
    } catch (err) {
      console.error("[admin/stats] weekly report reset failed", err);
      toast.error("되돌리지 못했습니다");
    } finally {
      setBusy(null);
    }
  };

  const preview = async () => {
    // 팝업 차단 회피 — 클릭 시점에 창을 열고 내용은 받은 뒤 채운다.
    const win = window.open("", "_blank");
    setBusy("preview");
    try {
      const html = await getWeeklyReportPreview();
      if (win) {
        win.document.open();
        win.document.write(html);
        win.document.close();
      }
    } catch (err) {
      console.error("[admin/stats] weekly report preview failed", err);
      win?.close();
      toast.error("미리보기를 만들지 못했습니다");
    } finally {
      setBusy(null);
    }
  };

  const sendNow = async () => {
    const ok = await confirm({
      title: "지난주 보고서를 지금 보낼까요?",
      description: `${(st?.to ?? []).join(", ")} 으로 발송합니다. 예약된 자동 발송은 그대로 진행됩니다.`,
      confirmLabel: "보내기",
    });
    if (!ok) return;
    setBusy("send");
    try {
      const r = await sendWeeklyReportNow();
      if (!r.smtp_configured) toast.warning("메일 서버가 설정되지 않아 실제로 발송되지 않았습니다");
      else if (r.sent.length) toast.success(`보냈습니다 — ${r.sent.join(", ")} (자유 의견 ${r.feedback}건 포함)`);
      else toast.error(`발송 실패 — ${r.failed.join(", ")}`);
    } catch (err) {
      console.error("[admin/stats] weekly report send failed", err);
      toast.error("보고서를 보내지 못했습니다");
    } finally {
      setBusy(null);
    }
  };

  const last = st?.last_week;
  const schedule = st ? `매주 ${WEEKDAYS[st.send_weekday]}요일 ${String(st.send_hour_kst).padStart(2, "0")}:00` : "";
  const fromAdmin = st ? Object.values(st.config.source).some((v) => v === "admin") : false;

  return (
    <div className="flex flex-col gap-3 rounded-card border border-md-outline-variant bg-md-surface px-4 py-3 text-[12.5px]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="inline-flex items-center gap-1.5 font-semibold text-md-on-surface">
          <span className="material-symbols-outlined text-[18px] text-md-on-surface-variant" aria-hidden>
            forward_to_inbox
          </span>
          주간 보고서 메일
        </span>
        {st ? (
          <span className="text-md-on-surface-variant">
            {st.enabled ? (
              <>
                {schedule} · 다음 {kstLabel(st.next_run_at)} · {st.to.join(", ")}
                {last ? (
                  <>
                    {" "}· 지난주({weekRange(last.week_start)}){" "}
                    {last.sent ? `발송됨 ${kstLabel(last.sent.at)}` : "아직 안 보냄"}
                  </>
                ) : null}
              </>
            ) : (
              <span className="font-medium text-md-error">자동 발송 꺼짐</span>
            )}
            {!st.smtp_configured ? " · ⚠ 메일 서버 미설정" : ""}
          </span>
        ) : (
          <span className="text-md-on-surface-variant">상태 확인 중…</span>
        )}
        <span className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={() => (editing ? setEditing(false) : openEditor())}
            disabled={!st || busy !== null}
            className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface hover:bg-md-surface-container-low disabled:opacity-50"
          >
            {editing ? "설정 닫기" : "설정"}
          </button>
          <button
            type="button"
            onClick={() => void preview()}
            disabled={busy !== null}
            className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface hover:bg-md-surface-container-low disabled:opacity-50"
          >
            {busy === "preview" ? "만드는 중…" : "지난주 미리보기"}
          </button>
          <button
            type="button"
            onClick={() => void sendNow()}
            disabled={busy !== null || !st}
            className="rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary disabled:opacity-50"
          >
            {busy === "send" ? "보내는 중…" : "지금 보내기"}
          </button>
        </span>
      </div>

      {editing && draft && st ? (
        <div className="flex flex-col gap-3 border-t border-md-outline-variant pt-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <label className="inline-flex cursor-pointer items-center gap-2 text-md-on-surface">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
              />
              자동 발송
            </label>
            <label className="inline-flex items-center gap-2 text-md-on-surface">
              요일
              <select
                value={draft.weekday}
                onChange={(e) => setDraft({ ...draft, weekday: Number(e.target.value) })}
                className="h-7 rounded border border-md-outline-variant bg-md-surface px-1.5 text-[12px]"
              >
                {WEEKDAYS.map((w, i) => (
                  <option key={w} value={i}>
                    {w}요일
                  </option>
                ))}
              </select>
            </label>
            <label className="inline-flex items-center gap-2 text-md-on-surface">
              시각(KST)
              <select
                value={draft.hour}
                onChange={(e) => setDraft({ ...draft, hour: Number(e.target.value) })}
                className="h-7 rounded border border-md-outline-variant bg-md-surface px-1.5 text-[12px]"
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </label>
          </div>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-md-on-surface">수신자 — 추가·삭제</legend>
            <div className="flex flex-wrap gap-1.5">
              {draft.to.map((em) => (
                <span
                  key={em}
                  className="inline-flex items-center gap-1 rounded-pill bg-md-surface-container-high py-0.5 pl-2.5 pr-1 text-[12px] text-md-on-surface"
                >
                  {em}
                  <button
                    type="button"
                    aria-label={`${em} 삭제`}
                    onClick={() => setDraft({ ...draft, to: draft.to.filter((x) => x !== em) })}
                    className="inline-flex size-5 items-center justify-center rounded-full text-md-on-surface-variant hover:bg-md-surface-container-highest hover:text-md-on-surface"
                  >
                    <span className="material-symbols-outlined text-[14px]" aria-hidden>
                      close
                    </span>
                  </button>
                </span>
              ))}
              {draft.to.length === 0 ? (
                <span className="text-[12px] text-md-error">수신자가 없습니다 — 한 명 이상 추가하세요</span>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="email"
                value={newTo}
                onChange={(e) => setNewTo(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addRecipient(newTo);
                  }
                }}
                placeholder="메일 주소 입력 후 Enter"
                className="h-8 w-64 rounded-input border border-md-outline-variant bg-md-surface px-2.5 text-[12.5px] text-md-on-surface focus:border-md-primary focus:outline-none"
              />
              <button
                type="button"
                onClick={() => addRecipient(newTo)}
                className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface hover:bg-md-surface-container-low"
              >
                추가
              </button>
              {st.admin_email_options.filter((em) => !draft.to.includes(em)).map((em) => (
                <button
                  key={em}
                  type="button"
                  onClick={() => addRecipient(em)}
                  title="관리자 메일 빠른 추가"
                  className="rounded-pill border border-dashed border-md-outline-variant px-2.5 py-0.5 text-[11.5px] text-md-on-surface-variant hover:text-md-on-surface"
                >
                  + {em}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-md-on-surface-variant">
              보고 메일에는 이용 수치와 사용자 자유 의견 원문이 들어갑니다 — 외부 주소는 신중히 추가하세요.
            </p>
          </fieldset>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11.5px] text-md-on-surface-variant">
              {fromAdmin && st.config.updated_by
                ? `마지막 변경: ${st.config.updated_by}${st.config.updated_at ? ` · ${kstLabel(st.config.updated_at)}` : ""}`
                : "지금은 서버 기본값을 따릅니다"}
              {" "}· 저장하면 재시작 없이 다음 점검(15분 이내)부터 반영
            </span>
            <span className="ml-auto flex gap-2">
              {fromAdmin ? (
                <button
                  type="button"
                  onClick={() => void resetToDefault()}
                  disabled={busy !== null}
                  className="rounded-pill px-3 py-1 text-[12px] text-md-on-surface-variant hover:bg-md-surface-container-low disabled:opacity-50"
                >
                  서버 기본값으로
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => void save()}
                disabled={busy !== null}
                className="rounded-pill bg-md-primary px-4 py-1 text-[12px] font-semibold text-md-on-primary disabled:opacity-50"
              >
                {busy === "save" ? "저장 중…" : "저장"}
              </button>
            </span>
          </div>
        </div>
      ) : null}
      {confirmDialog}
    </div>
  );
}


/** "2026-09-14" → "09/14~09/20" (주 = 월~일, 끝 = 시작 + 6일). 시작일만 쓰면 어느 주인지 헷갈린다. */
function weekRange(start: string): string {
  const d = new Date(`${start}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return `${start}~`;
  const e = new Date(d.getTime() + 6 * 86400000);
  const md = (x: Date) => `${String(x.getUTCMonth() + 1).padStart(2, "0")}/${String(x.getUTCDate()).padStart(2, "0")}`;
  return `${md(d)}~${md(e)}`;
}
