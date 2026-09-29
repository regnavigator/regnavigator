"use client";

/**
 * Admin · 설정 — 서버 점검 모드 + 시스템 설정 가시화 + 공지·다이제스트.
 *
 * - 화이트리스트 관리는 /admin/beta 로 일원화(2026-08-05) — 종전엔 여기와
 *   beta 페이지가 같은 데이터를 두 UI 로 중복 구현했다.
 * - 시스템 설정: backend ENV_REGISTRY(단일 진실원) 읽기전용 뷰 — secret 은
 *   설정 여부만. 변경은 .env(.docker)+재기동(운영 절차 docs/startup.md).
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  getAdminConfig,
  getMaintenance,
  setMaintenance,
  setMaintenanceSchedule,
  setFeaturePause,
  type ConfigItem,
  type MaintenanceState,
  cancelScheduledNotice,
  feedbackDigest,
  listScheduledNotices,
  type FeedbackDigest,
  type ScheduledNotice,
} from "@/lib/client/admin";
import { AUDIENCE_LABEL, NoticeComposer } from "@/components/admin/notice-composer";
import { Button } from "@/components/ui/button";
import {
  ConfirmDialog,
  type ConfirmOptions,
} from "@/components/ui/confirm-dialog";
import { ErrorBanner } from "@/components/admin/common";
import { useConfirm } from "@/components/admin/use-confirm";
import { useAdminPerms } from "@/components/admin/admin-perms";

const GROUP_LABELS: Record<string, string> = {
  auth: "인증·베타",
  llm: "LLM 모델",
  chatloop: "채팅 루프",
  search: "RAG 검색",
  guardrail: "가드레일",
  datastore: "데이터스토어",
  notify: "이메일 알림",
  cache: "캐시",
  report: "보고서",
  ops: "관측·알림",
  web: "웹 검색",
};

export default function AdminSettingsPage() {
  const { can } = useAdminPerms();
  const [config, setConfig] = useState<Record<string, ConfigItem[]> | null>(null);
  const [maint, setMaint] = useState<MaintenanceState | null>(null);
  const [maintMsg, setMaintMsg] = useState("");
  const [maintBusy, setMaintBusy] = useState(false);
  const [reportsMsg, setReportsMsg] = useState("");
  const [schedStart, setSchedStart] = useState("04:00");
  const [schedEnd, setSchedEnd] = useState("04:20");
  const [error, setError] = useState<string | null>(null);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set(["auth"]));
  const [confirm, setConfirm] = useState<{
    options: ConfirmOptions;
    onOk: () => void;
  } | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const [c, m] = await Promise.all([
        getAdminConfig(),
        getMaintenance(),
      ]);
      setConfig(c);
      setMaint(m);
      setMaintMsg(m.message || "");
      setReportsMsg(m.features?.reports?.message || "");
      if (m.schedule) {
        setSchedStart(m.schedule.start);
        setSchedEnd(m.schedule.end);
      }
    } catch (err) {
      console.error("[admin/settings] load failed", err);
      setError("설정을 불러오지 못했습니다. (admin 권한 확인)");
    }
  }, []);

  function handleToggleMaintenance(next: boolean) {
    if (maintBusy) return;
    // 켜기는 파괴적(사용자 차단) → 확인. 끄기는 즉시.
    if (next) {
      setConfirm({
        options: {
          title: "서버를 점검 모드로 전환할까요?",
          description:
            "일반 사용자는 즉시 이용이 차단(503)되고, 관리자만 접근 가능합니다.",
          confirmLabel: "점검 시작",
          danger: true,
        },
        onOk: () => void doToggleMaintenance(true),
      });
      return;
    }
    void doToggleMaintenance(false);
  }

  async function doToggleMaintenance(next: boolean) {
    setMaintBusy(true);
    setError(null);
    try {
      const res = await setMaintenance(next, next ? maintMsg.trim() || undefined : undefined);
      setMaint(res);
      setMaintMsg(res.message || "");
      toast.success(next ? "점검 모드 ON — 사용자 차단 중" : "점검 모드 해제됨");
    } catch {
      setError("점검 모드 변경에 실패했습니다.");
    } finally {
      setMaintBusy(false);
    }
  }

  async function doToggleReports(next: boolean) {
    if (maintBusy) return;
    setMaintBusy(true);
    setError(null);
    try {
      const res = await setFeaturePause("reports", next, reportsMsg.trim() || undefined);
      setMaint(res);
      setReportsMsg(res.features?.reports?.message || "");
      toast.success(next ? "보고서 기능 일시 중단 — 채팅은 정상" : "보고서 기능 재개");
    } catch {
      setError("보고서 기능 상태 변경에 실패했습니다.");
    } finally {
      setMaintBusy(false);
    }
  }

  async function handleSaveSchedule(enabled: boolean) {
    if (maintBusy) return;
    setMaintBusy(true);
    setError(null);
    try {
      const res = await setMaintenanceSchedule(
        enabled,
        schedStart,
        schedEnd,
        maintMsg.trim() || undefined,
      );
      setMaint(res);
      toast.success(
        enabled
          ? `예약 설정됨 — 매일 ${schedStart}~${schedEnd}`
          : "반복 예약 해제됨",
      );
    } catch (err) {
      const status = (err as { status?: number }).status;
      setError(
        status === 422
          ? "시간 형식 오류 — HH:MM (예: 04:00) 으로 입력하세요."
          : "예약 설정에 실패했습니다.",
      );
    } finally {
      setMaintBusy(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [reload]);

  function toggleGroup(g: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });
  }

  return (
    <main className="flex flex-col gap-6">
      <header>
        <h1 className="text-h1 text-md-on-surface">설정</h1>
      </header>

      <ErrorBanner message={error} />

      {/* ── 서버 점검(유지보수) 모드 ─────────────────────────────── */}
      <section
        className={`rounded-card border p-6 ${
          maint?.active
            ? "border-md-tertiary bg-md-tertiary-fixed/40"
            : "border-md-outline-variant bg-md-surface"
        }`}
      >
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-h2 text-md-on-surface">
            <span className="material-symbols-outlined text-[20px]" aria-hidden>
              engineering
            </span>
            서버 점검
          </h2>
          <span
            className={`rounded-full px-3 py-1 text-label ${
              maint?.active
                ? "bg-md-tertiary text-md-on-tertiary"
                : "bg-md-surface-variant text-md-on-surface-variant"
            }`}
          >
            {maint == null
              ? "…"
              : maint.active
                ? "점검 중 — 일반 사용자 차단"
                : "정상 서비스"}
          </span>
        </div>
        <p className="mt-2 text-body-sm text-md-on-surface-variant">
          점검을 켜면 일반 사용자는 즉시 <b>이용이 차단(503)</b>되고 점검 화면을 보게 됩니다.
          관리자는 계속 접근 가능합니다. 매일 04:00 데이터 갱신 등 정비 시 사용하세요.
          상태는 재기동 후에도 유지됩니다.
          {maint?.active && maint.since ? (
            <>
              {" "}시작: <span className="text-md-on-surface">{maint.since.slice(0, 19).replace("T", " ")} UTC</span>
              {maint.updated_by ? ` · ${maint.updated_by}` : ""}
            </>
          ) : null}
        </p>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex-1">
            <span className="text-label-caps text-md-on-surface-variant">
              사용자 안내 문구 (비우면 기본 문구)
            </span>
            <input
              value={maintMsg}
              onChange={(e) => setMaintMsg(e.target.value)}
              placeholder={maint?.default_message ?? "데이터 갱신 중입니다. 잠시 후 다시 이용해 주세요."}
              disabled={maintBusy}
              className="mt-1 w-full rounded-lg border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
            />
          </label>
          {maint?.manual ? (
            <>
              {/* 점검 ON 중 문구만 고칠 때 — 종전엔 저장 경로가 없어 입력이
                  버려졌다(2026-08-11 발견). 점검 상태 유지 + 문구만 재전송. */}
              <Button
                onClick={() => void doToggleMaintenance(true)}
                disabled={maintBusy || (maintMsg.trim() || "") === (maint?.message || "")}
                className="bg-md-surface-container-high text-md-on-surface hover:bg-md-surface-container-highest"
              >
                문구 저장
              </Button>
              <Button
                onClick={() => void handleToggleMaintenance(false)}
                disabled={maintBusy}
              >
                점검 해제
              </Button>
            </>
          ) : (
            <Button
              onClick={() => void handleToggleMaintenance(true)}
              disabled={maintBusy}
              className="bg-md-tertiary text-md-on-tertiary hover:bg-md-tertiary/90"
            >
              점검 시작(즉시)
            </Button>
          )}
        </div>

        {/* 매일 반복 예약 — 크론 불필요, 서버가 그 시간에 자동 on/off */}
        <div className="mt-5 rounded-xl border border-md-outline-variant/60 p-4">
          <div className="flex items-center justify-between">
            <p className="text-body font-medium text-md-on-surface">
              매일 반복 예약
              {maint?.schedule?.enabled ? (
                <span className="ml-2 rounded-full bg-md-primary-container px-2 py-0.5 text-[12px] text-md-on-primary-container">
                  ON — 매일 {maint.schedule.start}~{maint.schedule.end} ({maint.schedule.tz})
                </span>
              ) : (
                <span className="ml-2 rounded-full bg-md-surface-variant px-2 py-0.5 text-[12px] text-md-on-surface-variant">
                  OFF
                </span>
              )}
            </p>
          </div>
          <p className="mt-1 text-body-sm text-md-on-surface-variant">
            설정한 시간대에 서버가 <b>매일 자동으로</b> 점검을 켜고 끕니다(크론 불필요).
            시간은 KST 기준. 매일 04:00 데이터 갱신에 맞춰 예: 04:00~04:20.
          </p>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <label className="text-body-sm">
              <span className="text-label-caps text-md-on-surface-variant">시작</span>
              <input
                type="time"
                value={schedStart}
                onChange={(e) => setSchedStart(e.target.value)}
                disabled={maintBusy}
                className="mt-1 block rounded-lg border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm text-md-on-surface focus:border-md-primary focus:outline-none"
              />
            </label>
            <label className="text-body-sm">
              <span className="text-label-caps text-md-on-surface-variant">종료</span>
              <input
                type="time"
                value={schedEnd}
                onChange={(e) => setSchedEnd(e.target.value)}
                disabled={maintBusy}
                className="mt-1 block rounded-lg border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm text-md-on-surface focus:border-md-primary focus:outline-none"
              />
            </label>
            <Button onClick={() => void handleSaveSchedule(true)} disabled={maintBusy}>
              {maint?.schedule?.enabled ? "예약 갱신" : "예약 켜기"}
            </Button>
            {maint?.schedule?.enabled ? (
              <button
                type="button"
                onClick={() => void handleSaveSchedule(false)}
                disabled={maintBusy}
                className="text-body-sm text-md-error hover:underline"
              >
                예약 끄기
              </button>
            ) : null}
          </div>
        </div>
      </section>

      {/* ── 보고서 기능 일시 중단(기능 단위, 2026-09-07) ───────────── */}
      {(() => {
        const rp = maint?.features?.reports;
        const paused = !!rp?.paused;
        const writerUp = maint?.writer_up;
        return (
          <section
            className={`rounded-card border p-6 ${
              paused ? "border-md-tertiary bg-md-tertiary-fixed/40" : "border-md-outline-variant bg-md-surface"
            }`}
          >
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-h2 text-md-on-surface">
                <span className="material-symbols-outlined text-[20px]" aria-hidden>
                  lab_profile
                </span>
                보고서 기능 일시 중단
              </h2>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-full px-3 py-1 text-label ${
                    writerUp === false
                      ? "bg-md-error-container text-md-on-error-container"
                      : "bg-md-surface-variant text-md-on-surface-variant"
                  }`}
                  title="REPORT_WRITER_BASE_URL /models 프로브(30s 캐시)"
                >
                  {maint == null
                    ? "…"
                    : writerUp === null || writerUp === undefined
                      ? "writer: 로컬 미설정(폴백)"
                      : writerUp
                        ? "writer: 응답 중"
                        : "writer: 응답 없음"}
                </span>
                <span
                  className={`rounded-full px-3 py-1 text-label ${
                    paused ? "bg-md-tertiary text-md-on-tertiary" : "bg-md-surface-variant text-md-on-surface-variant"
                  }`}
                >
                  {maint == null ? "…" : paused ? "중단 중 — 보고서만 차단" : "정상"}
                </span>
              </div>
            </div>
            <p className="mt-2 text-body-sm text-md-on-surface-variant">
              보고서 writer(DGX vLLM)를 다른 작업에 쓰는 동안 켜 두세요. 심층 보고서·서류 작성
              요청만 <b>503 으로 거절</b>되고 채팅 입력창에 안내 배너가 뜹니다. 채팅·검색은
              그대로 동작합니다. 켜지 않아도 writer 가 응답하지 않으면 사용자에게 &ldquo;대기&rdquo;
              경고가 표시되지만, 요청 자체는 접수돼 최대 45분 대기 후 실패하므로 계획된
              작업이면 여기서 명시적으로 중단하는 편이 낫습니다.
              {paused && rp?.since ? (
                <>
                  {" "}시작: <span className="text-md-on-surface">{rp.since.slice(0, 19).replace("T", " ")} UTC</span>
                  {rp.updated_by ? ` · ${rp.updated_by}` : ""}
                </>
              ) : null}
            </p>
            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
              <label className="flex-1">
                <span className="text-label-caps text-md-on-surface-variant">
                  사용자 안내 문구 (비우면 기본 문구)
                </span>
                <input
                  value={reportsMsg}
                  onChange={(e) => setReportsMsg(e.target.value)}
                  placeholder={maint?.feature_default_messages?.reports ?? "보고서 기능 점검 중입니다."}
                  disabled={maintBusy}
                  className="mt-1 w-full rounded-lg border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
                />
              </label>
              {paused ? (
                <>
                  <Button
                    onClick={() => void doToggleReports(true)}
                    disabled={maintBusy || (reportsMsg.trim() || "") === (rp?.message || "")}
                    className="bg-md-surface-container-high text-md-on-surface hover:bg-md-surface-container-highest"
                  >
                    문구 저장
                  </Button>
                  <Button onClick={() => void doToggleReports(false)} disabled={maintBusy}>
                    보고서 재개
                  </Button>
                </>
              ) : (
                <Button
                  onClick={() => void doToggleReports(true)}
                  disabled={maintBusy}
                  className="bg-md-tertiary text-md-on-tertiary hover:bg-md-tertiary/90"
                >
                  보고서 중단(즉시)
                </Button>
              )}
            </div>
          </section>
        );
      })()}

      {/* ── 화이트리스트는 베타 초대 페이지로 일원화 ──────────────── */}
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-md-outline-variant bg-md-surface p-6">
        <div>
          <h2 className="text-h2 text-md-on-surface">클로즈 베타 화이트리스트</h2>
          <p className="mt-1 text-body-sm text-md-on-surface-variant">
            등록·삭제·초대 메일 발송은 <b>베타 초대</b> 페이지에서 관리합니다.
          </p>
        </div>
        <Link
          href="/admin/beta"
          className="rounded-pill bg-md-primary px-4 py-1.5 text-[13px] font-semibold text-md-on-primary hover:bg-md-primary-container"
        >
          베타 초대로 이동 →
        </Link>
      </section>

      {/* ── 시스템 설정 (읽기전용) ───────────────────────────────── */}
      <section className="rounded-card border border-md-outline-variant bg-md-surface p-6">
        <h2 className="text-h2 text-md-on-surface">시스템 설정</h2>
        <p className="mt-2 text-body-sm text-md-on-surface-variant">
          backend <code>ENV_REGISTRY</code> 읽기전용 뷰 — 값 변경은{" "}
          <code>.env(.docker)</code> 수정 + 재기동(절차: medi-back docs/startup.md).
          시크릿은 설정 여부만 표시됩니다.
        </p>

        {config
          ? Object.entries(config).map(([group, items]) => (
              <div key={group} className="mt-4 rounded-xl border border-md-outline-variant/60">
                <button
                  type="button"
                  onClick={() => toggleGroup(group)}
                  className="flex w-full items-center justify-between px-4 py-3 text-left"
                >
                  <span className="text-body font-medium text-md-on-surface">
                    {GROUP_LABELS[group] ?? group}
                    <span className="ml-2 text-body-sm text-md-on-surface-variant">
                      {items.length}개
                    </span>
                  </span>
                  <span className="text-md-on-surface-variant">
                    {openGroups.has(group) ? "▾" : "▸"}
                  </span>
                </button>
                {openGroups.has(group) ? (
                  <div className="overflow-x-auto border-t border-md-outline-variant/60">
                  <table className="w-full min-w-[560px] text-left text-body-sm">
                    <tbody>
                      {items.map((it) => (
                        <tr key={it.key} className="border-b border-md-outline-variant/40 last:border-0">
                          <td className="w-[280px] px-4 py-2 align-top">
                            <code className="text-md-on-surface">{it.key}</code>
                            {it.prod_required ? (
                              <span className="ml-2 rounded bg-md-error-container px-1.5 py-0.5 text-[11px] text-md-on-error-container">
                                prod 필수
                              </span>
                            ) : null}
                          </td>
                          <td className="w-[220px] px-2 py-2 align-top">
                            {it.secret ? (
                              <span
                                className={`rounded-full px-2 py-0.5 text-[12px] ${
                                  it.is_set
                                    ? "bg-md-primary-container text-md-on-primary-container"
                                    : "bg-md-surface-variant text-md-on-surface-variant"
                                }`}
                              >
                                {it.is_set ? "설정됨 (시크릿)" : "미설정"}
                              </span>
                            ) : (
                              <code className="break-all text-md-on-surface-variant">
                                {it.is_set ? it.value : (it.default ?? "미설정")}
                                {!it.is_set && it.default != null ? " (기본값)" : ""}
                              </code>
                            )}
                          </td>
                          <td className="px-2 py-2 align-top text-md-on-surface-variant">
                            {it.doc}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  </div>
                ) : null}
              </div>
            ))
          : (
            <p className="mt-4 text-body-sm text-md-on-surface-variant">불러오는 중…</p>
          )}
      </section>

      <ConfirmDialog
        open={confirm !== null}
        options={confirm?.options ?? null}
        busy={maintBusy}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          const ok = confirm?.onOk;
          setConfirm(null);
          ok?.();
        }}
      />
      {can("mail") ? <NotifySection /> : null}
      {can("feedback") ? <DigestSection /> : null}
    </main>
  );
}

/* ── 공지 이메일 (POST /admin/notify) ─────────────────────────── */

function NotifySection() {
  const [scheduled, setScheduled] = useState<ScheduledNotice[]>([]);
  const { confirm: askConfirm, confirmDialog } = useConfirm();

  const reload = useCallback(async () => {
    try {
      setScheduled(await listScheduledNotices());
    } catch (err) {
      console.warn("[admin] 예약 공지 조회 실패", err);
    }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  return (
    <section className="mt-8 rounded-card border border-md-outline-variant bg-md-surface-container-lowest p-5">
      <h2 className="text-[15px] font-semibold text-md-on-surface">공지 이메일</h2>
      <p className="mt-1 text-[12px] text-md-on-surface-variant">
        개별 발송(주소 상호 비노출) · 비활성 회원 제외. 발송 전
        <strong> 수신자 확인</strong>으로 명단을, <strong>메일 미리보기</strong>로 모양을
        점검하세요. 특정 인원만 고르려면 <strong>사용자 관리</strong>에서 체크 후 선택 발송.
      </p>
      <div className="mt-3">
        <NoticeComposer mode="audience" onDone={() => void reload()} />
      </div>

      {scheduled.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-[13px] font-semibold text-md-on-surface">예약·발송 이력</h3>
          <ul className="mt-2 divide-y divide-md-outline-variant rounded-card border border-md-outline-variant">
            {scheduled.map((n) => (
              <li key={n.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[12.5px]">
                <span className="min-w-0 flex-1 truncate text-md-on-surface">{n.subject}</span>
                <span className="text-[11.5px] text-md-on-surface-variant">
                  {new Date(n.send_at).toLocaleString("ko-KR")}
                </span>
                <span className="text-[11.5px] text-md-on-surface-variant">
                  {Array.isArray(n.to) ? `${n.to.length}명 지정` : AUDIENCE_LABEL[n.to]}
                </span>
                <span
                  className={`rounded-pill px-2 py-0.5 text-[10.5px] font-semibold ${
                    n.status === "sent"
                      ? "bg-md-primary-container text-md-on-primary-container"
                      : n.status === "pending"
                        ? "border border-md-outline-variant text-md-on-surface-variant"
                        : "bg-md-error-container text-md-on-error-container"
                  }`}
                >
                  {n.status === "sent"
                    ? `발송 ${n.result?.sent ?? 0}/${n.result?.requested ?? 0}`
                    : n.status === "pending" ? "예약됨" : n.status}
                </span>
                {n.status === "pending" ? (
                  <button
                    type="button"
                    onClick={() => void (async () => {
                      const ok = await askConfirm({
                        title: "예약 발송을 취소할까요?",
                        description: `"${n.subject}"`,
                        confirmLabel: "예약 취소",
                        danger: true,
                      });
                      if (!ok) return;
                      try {
                        await cancelScheduledNotice(n.id);
                        toast.success("예약 취소됨");
                        await reload();
                      } catch { toast.error("취소 실패"); }
                    })()}
                    className="rounded px-2 py-1 text-[12px] text-md-error hover:bg-md-error-container/40"
                  >
                    취소
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {confirmDialog}
    </section>
  );
}

/* ── 피드백 요약 digest (POST /admin/feedback/digest) ─────────── */
function DigestSection() {
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<FeedbackDigest | null>(null);
  return (
    <section className="mt-6 rounded-card border border-md-outline-variant bg-md-surface-container-lowest p-5">
      <h2 className="text-[15px] font-semibold text-md-on-surface">피드백 요약</h2>
      <p className="mt-1 text-[12px] text-md-on-surface-variant">
        기간 내 평가·자유 코멘트·인용 신고를 취합해 내 이메일로 발송하고 아래에 표시합니다.
      </p>
      <div className="mt-3 flex items-center gap-2">
        <input
          type="number" min={1} max={90}
          value={days}
          onChange={(e) => setDays(Math.max(1, Math.min(90, Number(e.target.value) || 7)))}
          className="h-9 w-20 rounded-input border border-md-outline-variant bg-md-surface px-2 text-[13px] text-md-on-surface focus:border-md-primary focus:outline-none"
        />
        <span className="text-[12px] text-md-on-surface-variant">일</span>
        <Button
          disabled={busy}
          onClick={() => void (async () => {
            setBusy(true);
            try {
              const r = await feedbackDigest(days);
              setResult(r);
              toast.success(r.sent ? `요약을 ${r.to}로 발송했습니다` : "요약 생성됨(이메일 미발송 — SMTP 미설정)");
            } catch { toast.error("요약 생성 실패"); }
            finally { setBusy(false); }
          })()}
        >
          {busy ? "생성 중…" : "요약 생성·발송"}
        </Button>
      </div>
      {result ? (
        <div className="mt-3 rounded border border-md-outline-variant bg-md-surface p-3">
          <p className="text-[12px] text-md-on-surface-variant">
            👍 {result.counts.thumbs_up} · 👎 {result.counts.thumbs_down} · 신고 {result.counts.citation_reports} · 코멘트 {result.counts.comments}
          </p>
          <pre className="mt-2 max-h-[240px] overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-md-on-surface">{result.summary}</pre>
        </div>
      ) : null}
    </section>
  );
}
