"use client";

/**
 * 고객사 규제 모니터링 — 배송 설정 · 미리보기 · 수동 발송 (2026-10-01).
 *
 * 저장해 둔 근거(북마크)를 고객사(=폴더)별로 묶어, 그 조문의 폐지·개정예정·
 * 시행일 변경을 주기적으로 감지해 지정 수신자에게 리포트를 보낸다.
 * 백엔드 계약: backend `routes/monitor.py` · `docs/contracts/API.md`.
 *
 * 미리보기는 서버가 만든 리포트 HTML 을 sandbox iframe(srcDoc)에 그대로 띄운다 —
 * 메일로 나갈 것과 화면에서 보는 것이 같아야 한다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorBanner, Spinner } from "@/components/admin/common";
import { Button } from "@/components/ui/button";
import {
  createMonitorTarget,
  deleteMonitorTarget,
  KIND_LABEL,
  listMonitorTargets,
  previewMonitorTarget,
  sendMonitorTarget,
  updateMonitorTarget,
  WEEKDAY_LABEL,
  type MonitorPreview,
  type MonitorTarget,
  type MonitorTargetInput,
} from "@/lib/client/monitor";

const EMPTY_FORM: MonitorTargetInput = {
  folder: "",
  recipients: "",
  label: "",
  cadence: "weekly",
  send_weekday: 0,
  send_hour: 9,
  enabled: true,
};

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? String(iso)
    : d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

export default function MonitorPage() {
  const [targets, setTargets] = useState<MonitorTarget[]>([]);
  const [folders, setFolders] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [form, setForm] = useState<MonitorTargetInput>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);

  const [preview, setPreview] = useState<MonitorPreview | null>(null);
  const [previewFor, setPreviewFor] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listMonitorTargets();
      setTargets(res.targets ?? []);
      setFolders(res.folders ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const unusedFolders = useMemo(() => {
    const taken = new Set(targets.map((t) => t.folder));
    return folders.filter((f) => !taken.has(f) || f === form.folder);
  }, [folders, targets, form.folder]);

  const resetForm = () => {
    setForm(EMPTY_FORM);
    setEditingId(null);
  };

  const onSubmit = async () => {
    if (!form.folder.trim()) {
      toast.error("고객사(폴더)를 선택하거나 입력해 주세요.");
      return;
    }
    if (!form.recipients.trim()) {
      toast.error("수신 이메일을 1개 이상 입력해 주세요.");
      return;
    }
    setBusy("save");
    try {
      if (editingId) {
        await updateMonitorTarget(editingId, form);
        toast.success("설정을 수정했습니다.");
      } else {
        await createMonitorTarget(form);
        toast.success("고객사를 등록했습니다.");
      }
      resetForm();
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "저장하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const onEdit = (t: MonitorTarget) => {
    setEditingId(t.id);
    setForm({
      folder: t.folder,
      recipients: t.recipients.join(", "),
      label: t.label ?? "",
      cadence: t.cadence,
      send_weekday: t.send_weekday,
      send_hour: t.send_hour,
      enabled: t.enabled,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const onToggle = async (t: MonitorTarget) => {
    setBusy(t.id);
    try {
      await updateMonitorTarget(t.id, { enabled: !t.enabled });
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "변경하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const onDelete = async (t: MonitorTarget) => {
    if (!window.confirm(`“${t.display_name}” 모니터링 설정을 삭제할까요?`)) return;
    setBusy(t.id);
    try {
      await deleteMonitorTarget(t.id);
      if (previewFor === t.id) {
        setPreview(null);
        setPreviewFor(null);
      }
      toast.success("삭제했습니다.");
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "삭제하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const onPreview = async (t: MonitorTarget) => {
    setBusy(t.id);
    try {
      const p = await previewMonitorTarget(t.id);
      setPreview(p);
      setPreviewFor(t.id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "미리보기를 만들지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const onSend = async (t: MonitorTarget, force: boolean) => {
    setBusy(t.id);
    try {
      const r = await sendMonitorTarget(t.id, { force });
      if (r.skipped === "no_change") {
        toast.info("변경이 없어 보내지 않았습니다. (‘변경 없어도 보내기’로 강제 발송)");
      } else if (r.skipped === "degraded") {
        toast.error("법령 DB 조회가 불완전해 보류했습니다. 잠시 후 다시 시도해 주세요.");
      } else if (r.sent.length) {
        toast.success(
          r.smtp_configured
            ? `${r.sent.length}명에게 보냈습니다.`
            : `발송 경로가 없어 실제로는 나가지 않았습니다(SMTP 미설정). 대상 ${r.sent.length}명`,
        );
      } else {
        toast.error("발송에 실패했습니다.");
      }
      await reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "발송하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <main className="mx-auto w-full max-w-[1100px] px-6 py-8">
      <header className="mb-6">
        <h1 className="text-[22px] font-bold text-md-primary">고객사 규제 모니터링</h1>
        <p className="mt-1 text-[13px] text-md-on-surface-variant">
          저장해 둔 근거를 고객사별로 묶어, 그 조문의{" "}
          <b>폐지 · 개정예정 · 시행일 변경</b>을 감지해 정기 리포트로 보냅니다.
          고객사 구분은 <b>근거 저장 시 지정한 폴더</b>를 씁니다.
        </p>
      </header>

      <ErrorBanner message={error} />

      {/* ── 등록/수정 폼 ─────────────────────────────────────────── */}
      <section className="mb-8 rounded-[8px] border border-md-outline-variant bg-md-surface-container-low p-5">
        <h2 className="mb-4 text-[15px] font-bold">
          {editingId ? "설정 수정" : "고객사 등록"}
        </h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium">고객사 폴더 *</span>
            <input
              list="monitor-folders"
              value={form.folder}
              onChange={(e) => setForm({ ...form, folder: e.target.value })}
              placeholder="근거 저장 시 지정한 폴더명"
              className="rounded-[6px] border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px]"
            />
            <datalist id="monitor-folders">
              {unusedFolders.map((f) => (
                <option key={f} value={f} />
              ))}
            </datalist>
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium">고객사 표시명</span>
            <input
              value={form.label ?? ""}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="비우면 폴더명을 씁니다"
              className="rounded-[6px] border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px]"
            />
          </label>

          <label className="flex flex-col gap-1.5 md:col-span-2">
            <span className="text-[12px] font-medium">수신 이메일 *</span>
            <input
              value={form.recipients}
              onChange={(e) => setForm({ ...form, recipients: e.target.value })}
              placeholder="쉼표로 구분 — a@example.com, b@example.com"
              className="rounded-[6px] border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px]"
            />
          </label>

          <div className="flex gap-3">
            <label className="flex flex-1 flex-col gap-1.5">
              <span className="text-[12px] font-medium">주기</span>
              <select
                value={form.cadence}
                onChange={(e) =>
                  setForm({ ...form, cadence: e.target.value as "weekly" | "monthly" })
                }
                className="rounded-[6px] border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px]"
              >
                <option value="weekly">매주</option>
                <option value="monthly">매월 1일</option>
              </select>
            </label>

            {form.cadence === "weekly" && (
              <label className="flex flex-col gap-1.5">
                <span className="text-[12px] font-medium">요일</span>
                <select
                  value={form.send_weekday}
                  onChange={(e) =>
                    setForm({ ...form, send_weekday: Number(e.target.value) })
                  }
                  className="rounded-[6px] border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px]"
                >
                  {WEEKDAY_LABEL.map((w, i) => (
                    <option key={w} value={i}>
                      {w}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <label className="flex flex-col gap-1.5">
              <span className="text-[12px] font-medium">시각(KST)</span>
              <select
                value={form.send_hour}
                onChange={(e) => setForm({ ...form, send_hour: Number(e.target.value) })}
                className="rounded-[6px] border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px]"
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="flex items-end gap-2">
            <Button onClick={onSubmit} disabled={busy === "save"}>
              {busy === "save" ? "저장 중…" : editingId ? "수정" : "등록"}
            </Button>
            {editingId && (
              <Button variant="outline" onClick={resetForm}>
                취소
              </Button>
            )}
          </div>
        </div>
      </section>

      {/* ── 목록 ─────────────────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-[15px] font-bold">
          등록된 고객사 {targets.length > 0 && `(${targets.length})`}
        </h2>

        {loading ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : targets.length === 0 ? (
          <p className="rounded-[8px] border border-dashed border-md-outline-variant px-4 py-10 text-center text-[13px] text-md-on-surface-variant">
            아직 등록된 고객사가 없습니다. 먼저 답변의 근거를 북마크하고 폴더를 지정한 뒤,
            위에서 등록해 주세요.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-[8px] border border-md-outline-variant">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="bg-md-surface-container">
                  {["고객사", "관찰", "수신자", "주기", "다음 발송", "최근 발송", ""].map(
                    (h) => (
                      <th
                        key={h}
                        className="whitespace-nowrap border-b border-md-outline-variant px-3 py-2 text-left font-bold"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {targets.map((t) => (
                  <tr key={t.id} className="border-b border-md-outline-variant last:border-0">
                    <td className="px-3 py-2.5">
                      <div className="font-medium">{t.display_name}</div>
                      {t.label && (
                        <div className="text-[11px] text-md-on-surface-variant">
                          폴더 · {t.folder}
                        </div>
                      )}
                      {!t.enabled && (
                        <span className="mt-1 inline-block rounded-[4px] bg-md-surface-container-high px-1.5 py-0.5 text-[10px] text-md-on-surface-variant">
                          중지됨
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 tabular-nums">{t.watched}건</td>
                    <td className="max-w-[220px] px-3 py-2.5 text-[12px] text-md-on-surface-variant">
                      {t.recipients.join(", ")}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      {t.cadence === "weekly"
                        ? `매주 ${WEEKDAY_LABEL[t.send_weekday]} ${String(t.send_hour).padStart(2, "0")}시`
                        : `매월 1일 ${String(t.send_hour).padStart(2, "0")}시`}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap text-[12px]">
                      {t.enabled ? fmt(t.next_run_at) : "—"}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap text-[12px] text-md-on-surface-variant">
                      {fmt(t.last_sent_at)}
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy === t.id}
                          onClick={() => onPreview(t)}
                        >
                          미리보기
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy === t.id}
                          onClick={() => onSend(t, false)}
                        >
                          지금 발송
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy === t.id}
                          onClick={() => onSend(t, true)}
                          title="변경이 없어도 강제로 보냅니다 (시연용)"
                        >
                          강제
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy === t.id}
                          onClick={() => onToggle(t)}
                        >
                          {t.enabled ? "중지" : "재개"}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy === t.id}
                          onClick={() => onEdit(t)}
                        >
                          수정
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy === t.id}
                          onClick={() => onDelete(t)}
                        >
                          삭제
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── 미리보기 ─────────────────────────────────────────────── */}
      {preview && (
        <section className="mt-8">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-[15px] font-bold">리포트 미리보기</h2>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setPreview(null);
                setPreviewFor(null);
              }}
            >
              닫기
            </Button>
          </div>

          <div className="mb-2 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="rounded-[4px] bg-md-surface-container px-2 py-1">
              제목 · {preview.subject}
            </span>
            <span className="text-md-on-surface-variant">관찰 {preview.watched}건</span>
            {(Object.keys(KIND_LABEL) as (keyof typeof KIND_LABEL)[])
              .filter((k) => preview.counts?.[k])
              .map((k) => (
                <span key={k} className="rounded-[4px] bg-md-surface-container px-2 py-1">
                  {KIND_LABEL[k]} {preview.counts[k]}건
                </span>
              ))}
            {preview.degraded && (
              <span className="rounded-[4px] bg-md-error-container px-2 py-1 text-md-on-error-container">
                일부 확인 불가 — 법령 DB 조회 실패
              </span>
            )}
          </div>

          {/* 메일로 나갈 HTML 그대로. 스크립트 차단(sandbox 비허용). */}
          <iframe
            title="리포트 미리보기"
            sandbox=""
            srcDoc={preview.html}
            className="h-[520px] w-full rounded-[8px] border border-md-outline-variant bg-white"
          />
        </section>
      )}
    </main>
  );
}
