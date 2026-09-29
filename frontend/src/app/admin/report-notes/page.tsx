"use client";

/**
 * Admin · 보고 노트 — 관리자 전용 업데이트 기록 (2026-09-21).
 *
 * 주간 보고 메일의 "이번 주 업데이트"가 여기서 온다. 사용자 공지(패치노트·/updates)와 분리 —
 * 사용자에게는 보이지 않는다. 기능을 배포하면 개발 쪽이 노트를 올리고(scripts/report_note.py),
 * 운영자는 여기서 확인·수정하고 [포함]/[해제]로 보고 메일에 실을지 정한다.
 * 노트 날짜가 속한 주(월~일, 한국시간)의 보고 메일에 실린다. backend `src/report_notes.py`.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  addReportNote,
  deleteReportNote,
  listReportNotes,
  patchReportNote,
  type ReportNote,
} from "@/lib/client/admin";
import { ErrorBanner, Spinner } from "@/components/admin/common";
import { useConfirm } from "@/components/admin/use-confirm";

function todayKst(): string {
  return new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);
}

function mondayOf(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  const wd = (d.getUTCDay() + 6) % 7; // 0=월
  d.setUTCDate(d.getUTCDate() - wd);
  return d.toISOString().slice(0, 10);
}

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function md(day: string): string {
  const [, m, d] = day.split("-");
  const wd = "일월화수목금토"[new Date(`${day}T00:00:00Z`).getUTCDay()];
  return `${Number(m)}/${Number(d)}(${wd})`;
}

type Draft = { title: string; feature: string; date: string; items: string; include: boolean };

const EMPTY: () => Draft = () => ({ title: "", feature: "", date: todayKst(), items: "", include: true });

function NoteForm({
  initial,
  features,
  submitLabel,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: Draft;
  features: string[];
  submitLabel: string;
  busy: boolean;
  onSubmit: (d: Draft) => void;
  onCancel?: () => void;
}) {
  const [d, setD] = useState<Draft>(initial);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <input
          value={d.title}
          onChange={(e) => setD({ ...d, title: e.target.value })}
          maxLength={80}
          placeholder="무엇을 할 수 있게 됐는지(사용자 언어) — 예: 출처 종류를 색으로 구분해 보여줘요"
          className="h-9 min-w-0 flex-1 rounded-input border border-md-outline-variant bg-md-surface px-3 text-[13px] text-md-on-surface focus:border-md-primary focus:outline-none"
        />
        <select
          value={d.feature}
          onChange={(e) => setD({ ...d, feature: e.target.value })}
          className="h-9 rounded-input border border-md-outline-variant bg-md-surface px-2 text-[13px]"
        >
          <option value="">기능 영역</option>
          {features.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={d.date}
          onChange={(e) => setD({ ...d, date: e.target.value })}
          className="h-9 rounded-input border border-md-outline-variant bg-md-surface px-2 text-[13px]"
        />
      </div>
      <textarea
        value={d.items}
        onChange={(e) => setD({ ...d, items: e.target.value })}
        rows={3}
        placeholder="세부 항목 — 한 줄에 하나 (최대 8개)"
        className="rounded-input border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px] text-md-on-surface focus:border-md-primary focus:outline-none"
      />
      <div className="flex items-center gap-3">
        <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] text-md-on-surface">
          <input type="checkbox" checked={d.include} onChange={(e) => setD({ ...d, include: e.target.checked })} />
          보고 메일에 포함
        </label>
        <span className="ml-auto flex gap-2">
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-pill px-3 py-1 text-[12.5px] text-md-on-surface-variant hover:bg-md-surface-container-low"
            >
              취소
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy || !d.title.trim()}
            onClick={() => onSubmit(d)}
            className="rounded-pill bg-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-on-primary disabled:opacity-50"
          >
            {submitLabel}
          </button>
        </span>
      </div>
    </div>
  );
}

export default function AdminReportNotesPage() {
  const { confirm, confirmDialog } = useConfirm();
  const [notes, setNotes] = useState<ReportNote[]>([]);
  const [features, setFeatures] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listReportNotes(addDays(todayKst(), -7 * 16));
      setNotes(r.notes);
      setFeatures(r.features);
    } catch (err) {
      console.error("[admin/report-notes] load failed", err);
      setError("보고 노트를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);

  // 주(월요일) 단위로 묶기 — 최신 주가 위
  const weeks = useMemo(() => {
    const m = new Map<string, ReportNote[]>();
    for (const n of notes) {
      const k = mondayOf(n.date);
      m.set(k, [...(m.get(k) ?? []), n]);
    }
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [notes]);
  const thisWeek = mondayOf(todayKst());

  const toItems = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

  const add = async (d: Draft) => {
    setBusy(true);
    try {
      await addReportNote({ title: d.title.trim(), items: toItems(d.items), feature: d.feature || null, date: d.date, include: d.include });
      setAdding(false);
      toast.success("보고 노트를 추가했습니다");
      await reload();
    } catch (err) {
      console.error("[admin/report-notes] add failed", err);
      toast.error("추가하지 못했습니다 — 제목·날짜를 확인하세요");
    } finally {
      setBusy(false);
    }
  };

  const save = async (id: string, d: Draft) => {
    setBusy(true);
    try {
      await patchReportNote(id, { title: d.title.trim(), items: toItems(d.items), feature: d.feature || null, date: d.date, include: d.include });
      setEditing(null);
      await reload();
    } catch (err) {
      console.error("[admin/report-notes] save failed", err);
      toast.error("저장하지 못했습니다");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (n: ReportNote) => {
    // 낙관적 반영 — 실패하면 되돌린다
    setNotes((prev) => prev.map((x) => (x.id === n.id ? { ...x, include: !n.include } : x)));
    try {
      await patchReportNote(n.id, { include: !n.include });
    } catch (err) {
      console.error("[admin/report-notes] toggle failed", err);
      setNotes((prev) => prev.map((x) => (x.id === n.id ? { ...x, include: n.include } : x)));
      toast.error("변경하지 못했습니다");
    }
  };

  const remove = async (n: ReportNote) => {
    const ok = await confirm({
      title: "이 노트를 삭제할까요?",
      description: `${n.title} — 보고 메일에서 빼기만 하려면 [해제]를 쓰세요.`,
      confirmLabel: "삭제",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteReportNote(n.id);
      await reload();
    } catch (err) {
      console.error("[admin/report-notes] delete failed", err);
      toast.error("삭제하지 못했습니다");
    }
  };

  return (
    <main className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="text-h1 text-md-on-surface">보고 노트</h1>
          <p className="mt-1 text-body-sm text-md-on-surface-variant">
            관리자 전용 — 주간 보고 메일의 &lsquo;이번 주 업데이트&rsquo;에 실립니다. 사용자에게는 보이지 않습니다.
            <b className="font-semibold text-md-on-surface"> 포함</b>된 노트만 그 주 보고 메일에 들어갑니다.
          </p>
        </div>
        <span className="ml-auto flex items-center gap-2">
          {loading ? <Spinner /> : null}
          <button
            type="button"
            onClick={() => setAdding((v) => !v)}
            className="rounded-pill bg-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-on-primary"
          >
            {adding ? "추가 닫기" : "노트 추가"}
          </button>
        </span>
      </header>

      <ErrorBanner message={error} />

      {adding ? (
        <div className="rounded-card border border-md-primary/40 bg-md-surface p-4">
          <NoteForm initial={EMPTY()} features={features} submitLabel="추가" busy={busy} onSubmit={(d) => void add(d)} />
        </div>
      ) : null}

      {weeks.length === 0 && !loading ? (
        <p className="text-body-sm text-md-on-surface-variant">아직 보고 노트가 없습니다.</p>
      ) : null}

      {weeks.map(([monday, list]) => {
        const included = list.filter((n) => n.include).length;
        const sendDay = addDays(monday, 7);
        const status = monday === thisWeek ? `${md(sendDay)} 보고 메일에 실림` : monday > thisWeek ? "다음 주 이후" : `${md(sendDay)} 보고 메일 대상`;
        return (
          <section key={monday} className="flex flex-col gap-2">
            <h2 className="flex flex-wrap items-baseline gap-2 text-[14px] font-semibold text-md-on-surface">
              {md(monday)} ~ {md(addDays(monday, 6))}
              <span className="text-[12px] font-normal text-md-on-surface-variant">
                포함 {included} / 전체 {list.length} · {status}
              </span>
            </h2>
            <ul className="flex flex-col divide-y divide-md-outline-variant rounded-card border border-md-outline-variant bg-md-surface">
              {list.map((n) => (
                <li key={n.id} className={`flex flex-col gap-2 px-4 py-3 ${n.include ? "" : "opacity-60"}`}>
                  {editing === n.id ? (
                    <NoteForm
                      initial={{ title: n.title, feature: n.feature ?? "", date: n.date, items: n.items.join("\n"), include: n.include }}
                      features={features}
                      submitLabel="저장"
                      busy={busy}
                      onSubmit={(d) => void save(n.id, d)}
                      onCancel={() => setEditing(null)}
                    />
                  ) : (
                    <div className="flex items-start gap-3">
                      <button
                        type="button"
                        role="switch"
                        aria-checked={n.include}
                        onClick={() => void toggle(n)}
                        title={n.include ? "보고 메일에 포함 — 누르면 해제" : "해제됨 — 누르면 포함"}
                        className={`mt-0.5 shrink-0 rounded-pill px-2.5 py-0.5 text-[11.5px] font-semibold ${
                          n.include
                            ? "bg-md-primary text-md-on-primary"
                            : "border border-md-outline-variant text-md-on-surface-variant"
                        }`}
                      >
                        {n.include ? "포함" : "해제"}
                      </button>
                      <div className="min-w-0 flex-1">
                        <p className="text-[13.5px] font-medium text-md-on-surface">
                          {n.feature ? (
                            <span className="mr-1.5 rounded bg-md-surface-container-high px-1.5 py-0.5 text-[11px] font-normal text-md-on-surface-variant">
                              {n.feature}
                            </span>
                          ) : null}
                          {n.title}
                          <span className="ml-2 text-[11.5px] font-normal text-md-on-surface-variant">{md(n.date)}</span>
                        </p>
                        {n.items.length ? (
                          <ul className="mt-1 list-disc pl-5 text-[12.5px] text-md-on-surface-variant">
                            {n.items.map((it, i) => (
                              <li key={i}>{it}</li>
                            ))}
                          </ul>
                        ) : null}
                        <p className="mt-1 text-[11px] text-md-on-surface-variant/80">
                          {n.created_by ? `작성 ${n.created_by}` : ""}
                          {n.updated_by ? ` · 수정 ${n.updated_by}` : ""}
                          {n.refs?.length ? ` · 커밋 ${n.refs.join(", ")}` : ""}
                        </p>
                      </div>
                      <span className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          onClick={() => setEditing(n.id)}
                          className="rounded-pill px-2.5 py-1 text-[12px] text-md-on-surface-variant hover:bg-md-surface-container-low"
                        >
                          수정
                        </button>
                        <button
                          type="button"
                          onClick={() => void remove(n)}
                          className="rounded-pill px-2.5 py-1 text-[12px] text-md-error hover:bg-md-error/10"
                        >
                          삭제
                        </button>
                      </span>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      {confirmDialog}
    </main>
  );
}
