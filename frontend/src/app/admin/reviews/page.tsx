"use client";

/**
 * Admin · 답변 검수 — backend `/admin/review-queue` · `/admin/reviews`(2026-09-17).
 *
 * grounding·claim audit 은 "쓴 문장이 출처와 일치하나"까지만 잰다. 조문 오적용·핵심
 * 누락·시점 오류는 사람이 봐야 한다 — 그 채점을 남기는 화면.
 *
 * - 큐: 위험 신호 점수순 + 무작위 표본(🎲). **정답률은 무작위 표본 채점만으로** 계산된다
 *   (신호 표본은 편향). 그래서 🎲 턴은 신호가 없어도 채점해야 숫자가 쌓인다.
 * - 펼치면 그 턴의 질문·답변 전문·인용 목록을 `/admin/threads/{id}` 에서 읽어 보여준다.
 * - 채점 저장 시 큐에서 빠진다(검수자당 1행 — 다시 채점하면 덮어씀).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  getAdminThread,
  getReviewArchive,
  getReviewQueue,
  getReviewStats,
  saveReview,
  type AdminThreadDetail,
  type ReviewArchiveItem,
  type ReviewQueue,
  type ReviewQueueItem,
  type ReviewStats,
  type ReviewVerdict,
} from "@/lib/client/admin";
import {
  AdminUserLabel,
  ErrorBanner,
  PillTab,
  Spinner,
  StatCard,
  formatTime,
} from "@/components/admin/common";

const SIGNAL_LABEL: Record<string, string> = {
  citation_report: "인용 오류 신고",
  thumbs_down: "👎",
  identifier_mismatch: "서식·별표 번호 불일치",
  claim_contradicted: "출처와 모순",
  no_citation: "인용 없음",
  search_empty: "검색 0건",
  low_verified: "인용 검증률 낮음",
  claim_unverified: "미검증 사실",
  truncated: "답변 잘림",
};

const VERDICT_LABEL: Record<ReviewVerdict, string> = {
  correct: "정확",
  partial: "부분 정확",
  wrong: "오답",
  unratable: "판단 불가",
};

const ERROR_LABEL: Record<string, string> = {
  retrieval_miss: "검색 실패(맞는 조문이 안 나옴)",
  misapplied: "조문 오적용·오해석",
  fabricated: "출처에 없는 내용",
  outdated: "현행/시행예정·구법 혼동",
  incomplete: "핵심 조문·예외 누락",
  other: "기타",
};

type Lane = "all" | "rag" | "skill";

export default function AdminReviewsPage() {
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [days, setDays] = useState(14);
  const [lane, setLane] = useState<Lane>("rag");
  const [includeReviewed, setIncludeReviewed] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [q, s] = await Promise.all([
        getReviewQueue({ days, includeReviewed, limit: 200 }),
        getReviewStats(30),
      ]);
      setQueue(q);
      setStats(s);
    } catch (err) {
      console.error("[admin/reviews] load failed", err);
      setError("검수 큐를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [days, includeReviewed]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const items = useMemo(
    () => (queue?.items ?? []).filter((i) => lane === "all" || i.lane === lane),
    [queue, lane],
  );
  const laneCount = (l: Lane) =>
    (queue?.items ?? []).filter((i) => l === "all" || i.lane === l).length;

  function onSaved(messageId: string) {
    setOpenId(null);
    setQueue((q) =>
      q
        ? {
            ...q,
            items: includeReviewed
              ? q.items.map((i) => (i.message_id === messageId ? { ...i, reviewed: true } : i))
              : q.items.filter((i) => i.message_id !== messageId),
          }
        : q,
    );
    void getReviewStats(30).then(setStats).catch(() => {});
  }

  const acc = stats?.accuracy_random;

  return (
    <main className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-h1 text-md-on-surface">답변 검수</h1>
        <p className="text-body-sm text-md-on-surface-variant">
          자동 검증은 인용이 출처와 일치하는지만 봅니다. 답이 맞는지는 여기서 채점합니다.
          🎲 표시 턴은 무작위 표본입니다 — 정답률은 이 표본의 채점으로만 계산되니 신호가 없어도 채점해 주세요.
        </p>
      </header>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          icon="fact_check"
          label="정답률(무작위 표본)"
          value={acc?.strict != null ? `${Math.round(acc.strict * 100)}%` : "—"}
          sub={
            acc?.n
              ? `n=${acc.n} · 95% CI ${pct(acc.strict_ci95?.[0])}–${pct(acc.strict_ci95?.[1])}`
              : "채점된 표본 없음"
          }
        />
        <StatCard
          icon="rule"
          label="부분 정확 포함"
          value={acc?.lenient != null ? `${Math.round(acc.lenient * 100)}%` : "—"}
          sub={acc?.n ? `95% CI ${pct(acc.lenient_ci95?.[0])}–${pct(acc.lenient_ci95?.[1])}` : ""}
        />
        <StatCard
          icon="done_all"
          label="채점 완료(30일)"
          value={String(stats?.reviewed ?? 0)}
          sub={Object.entries(stats?.verdicts ?? {})
            .map(([k, v]) => `${VERDICT_LABEL[k as ReviewVerdict] ?? k} ${v}`)
            .join(" · ")}
        />
        <StatCard
          icon="pending_actions"
          label="검수 대기"
          value={String(queue?.queue_total ?? 0)}
          sub={queue ? `${queue.turns_scanned}턴 중` : ""}
          tone={queue && queue.queue_total > 0 ? "warn" : undefined}
        />
      </section>

      {stats && Object.keys(stats.error_types).length > 0 ? (
        <section className="rounded-card border border-md-outline-variant bg-md-surface p-4">
          <h2 className="mb-2 text-[12px] font-semibold uppercase tracking-[0.08em] text-md-on-surface-variant">
            오류 유형 분포 — 어디를 고칠지
          </h2>
          <ul className="flex flex-wrap gap-2">
            {Object.entries(stats.error_types)
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => (
                <li
                  key={k}
                  className="rounded-pill bg-md-surface-container-low px-3 py-1 text-[12.5px] text-md-on-surface"
                >
                  {ERROR_LABEL[k] ?? k} <span className="tabular-nums opacity-70">{v}</span>
                </li>
              ))}
          </ul>
        </section>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <PillTab active={lane === "rag"} label="규제 답변" count={laneCount("rag")} onClick={() => setLane("rag")} />
        <PillTab active={lane === "skill"} label="IRB/DRB 스킬" count={laneCount("skill")} onClick={() => setLane("skill")} />
        <PillTab active={lane === "all"} label="전체" count={laneCount("all")} onClick={() => setLane("all")} />
        <span className="mx-1 h-5 w-px bg-md-outline-variant" aria-hidden />
        {[7, 14, 30].map((d) => (
          <PillTab key={d} active={days === d} label={`${d}일`} onClick={() => setDays(d)} />
        ))}
        <label className="ml-auto flex items-center gap-1.5 text-[13px] text-md-on-surface-variant">
          <input
            type="checkbox"
            checked={includeReviewed}
            onChange={(e) => setIncludeReviewed(e.target.checked)}
          />
          채점한 것도 보기
        </label>
      </div>

      {lane === "skill" ? (
        <p className="rounded-card border border-md-outline-variant bg-md-surface-container-low px-3 py-2 text-body-sm text-md-on-surface-variant">
          스킬 턴은 설계상 [n] 인용을 달지 않습니다 — 인용 관련 신호는 적용되지 않고, 판정(심의 대상 여부)이 맞는지로 채점합니다.
        </p>
      ) : null}

      <ErrorBanner message={error} />
      {queue?.threads_capped ? (
        <ErrorBanner message="대화 수가 많아 일부만 스캔했습니다 — 기간을 줄여 주세요." />
      ) : null}

      {loading && !queue ? (
        <div className="flex justify-center py-10">
          <Spinner size={24} />
        </div>
      ) : null}

      <ul className="flex flex-col gap-3">
        {items.map((it) => (
          <QueueRow
            key={it.message_id}
            item={it}
            open={openId === it.message_id}
            onToggle={() => setOpenId((cur) => (cur === it.message_id ? null : it.message_id))}
            errorTypes={queue?.error_types ?? []}
            onSaved={() => onSaved(it.message_id)}
          />
        ))}
        {queue && items.length === 0 && !loading ? (
          <li className="rounded-card border border-md-outline-variant px-4 py-8 text-center text-md-on-surface-variant">
            검수할 답변이 없습니다.
          </li>
        ) : null}
      </ul>

      <ReviewArchive />
    </main>
  );
}

function pct(v: number | undefined | null): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function QueueRow({
  item,
  open,
  onToggle,
  errorTypes,
  onSaved,
}: {
  item: ReviewQueueItem;
  open: boolean;
  onToggle: () => void;
  errorTypes: string[];
  onSaved: () => void;
}) {
  return (
    <li className="rounded-card border border-md-outline-variant bg-md-surface">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full flex-col gap-2 px-4 py-3 text-left transition-colors hover:bg-md-surface-container-low"
      >
        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
          {item.random_sample ? (
            <span
              className="rounded-pill bg-md-primary-fixed px-2 py-0.5 font-semibold text-md-on-primary-fixed-variant"
              title="무작위 표본 — 정답률 계산에 쓰입니다"
            >
              🎲 표본
            </span>
          ) : null}
          {item.signals.map((s) => (
            <span
              key={s}
              className="rounded-pill bg-md-error-container px-2 py-0.5 font-semibold text-md-on-error-container"
            >
              {SIGNAL_LABEL[s] ?? s}
            </span>
          ))}
          {item.reviewed ? (
            <span className="rounded-pill bg-md-surface-container-low px-2 py-0.5 text-md-on-surface-variant">
              채점됨
            </span>
          ) : null}
          <span className="ml-auto font-mono text-md-on-surface-variant">
            {formatTime(item.started_at)}
          </span>
        </div>
        <p
          className="line-clamp-2 text-body-sm font-medium text-md-on-surface"
          style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
        >
          {item.question}
        </p>
        <div className="flex flex-wrap gap-3 text-[11.5px] tabular-nums text-md-on-surface-variant">
          <AdminUserLabel
            displayName={item.user_display_name}
            memo={item.user_admin_memo}
            email={item.user_email}
            userId={item.user_id}
          />
          {item.lane === "rag" ? (
            <>
              <span>
                인용 {item.citations_used}/{item.citations_retrieved}건 사용
              </span>
              {item.verified_rate != null ? (
                <span>검증률 {Math.round(item.verified_rate * 100)}%</span>
              ) : null}
            </>
          ) : (
            <span>IRB/DRB 스킬 턴</span>
          )}
        </div>
      </button>
      {open ? <TurnDetail item={item} errorTypes={errorTypes} onSaved={onSaved} /> : null}
    </li>
  );
}

type Citation = {
  number?: number;
  title?: string;
  url?: string | null;
  verified?: boolean;
  snippet?: string;
};

/** thread 전문에서 이 답변의 턴(질문·답변·인용)만 뽑는다. */
function extractTurn(detail: AdminThreadDetail, messageId: string) {
  const idx = detail.messages.findIndex((m) => m.id === messageId);
  if (idx < 0) return null;
  const human =
    detail.messages.slice(0, idx).reverse().find((m) => m.type === "human") ?? null;
  const answer = detail.messages[idx]?.content ?? "";
  const used = new Set(
    Array.from(answer.matchAll(/\[(\d{1,3})\]/g)).map((m) => Number(m[1])),
  );
  const cites: Citation[] = [];
  for (const st of detail.steps as { source_message_id?: string; citations?: Citation[] }[]) {
    if (human?.id && st?.source_message_id === human.id) cites.push(...(st.citations ?? []));
  }
  return {
    question: human?.content ?? "",
    answer,
    used: cites.filter((c) => c.number != null && used.has(c.number)),
    unusedCount: cites.filter((c) => c.number == null || !used.has(c.number)).length,
  };
}

function TurnDetail({
  item,
  errorTypes,
  onSaved,
}: {
  item: ReviewQueueItem;
  errorTypes: string[];
  onSaved: () => void;
}) {
  const [detail, setDetail] = useState<AdminThreadDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<ReviewVerdict | null>(null);
  const [errs, setErrs] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getAdminThread(item.thread_id)
      .then((d) => alive && setDetail(d))
      .catch((err) => {
        console.error("[admin/reviews] thread load failed", err);
        if (alive) setLoadError("대화 원문을 불러오지 못했습니다.");
      });
    return () => {
      alive = false;
    };
  }, [item.thread_id]);

  const turn = useMemo(
    () => (detail ? extractTurn(detail, item.message_id) : null),
    [detail, item.message_id],
  );

  async function submit() {
    if (!verdict || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      await saveReview({
        thread_id: item.thread_id,
        message_id: item.message_id,
        verdict,
        error_types: verdict === "correct" ? [] : errs,
        note: note.trim() || undefined,
      });
      onSaved();
    } catch (err) {
      console.error("[admin/reviews] save failed", err);
      setSaveError("채점을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSaving(false);
    }
  }

  const ia = item.identifier_audit;
  const needsErrs = verdict === "partial" || verdict === "wrong";

  return (
    <div className="flex flex-col gap-4 border-t border-md-outline-variant px-4 py-4">
      <ErrorBanner message={loadError} />

      {ia && (ia.unsupported.length > 0 || ia.placeholders.length > 0) ? (
        <div className="rounded-card border border-md-error/40 bg-md-error-container px-3 py-2 text-body-sm text-md-on-error-container">
          답변의 <b>{[...ia.unsupported, ...ia.placeholders].join(", ")}</b> 은(는) 검색 근거에 없습니다.
          {ia.source_forms.length > 0 ? <> 근거에 있던 서식: {ia.source_forms.join(", ")}</> : null}
        </div>
      ) : null}

      {item.claim_samples.length > 0 ? (
        <div className="text-body-sm">
          <h3 className="mb-1 text-[12px] font-semibold text-md-on-surface-variant">
            자동 검증이 근거를 못 찾은 문장
          </h3>
          <ul className="flex flex-col gap-1">
            {item.claim_samples.map((c, i) => (
              <li key={i} className="text-md-on-surface">
                <span className="mr-1.5 rounded bg-md-surface-container-low px-1.5 py-0.5 text-[11px]">
                  {c.verdict === "contradicted" ? "모순" : "미검증"}
                </span>
                {c.claim}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!detail && !loadError ? (
        <div className="flex justify-center py-6">
          <Spinner />
        </div>
      ) : null}

      {turn ? (
        <>
          <Block title="질문">{turn.question}</Block>
          <Block title="답변">{turn.answer}</Block>
          {turn.used.length > 0 ? (
            <div>
              <h3 className="mb-1 text-[12px] font-semibold text-md-on-surface-variant">
                답변이 쓴 인용 {turn.used.length}건
                {turn.unusedCount > 0 ? ` (검색됐지만 안 쓴 것 ${turn.unusedCount}건)` : ""}
              </h3>
              <ul className="flex flex-col gap-1.5">
                {turn.used.map((c) => (
                  <li key={c.number} className="text-body-sm text-md-on-surface">
                    <span className="mr-1 font-mono text-[12px]">[{c.number}]</span>
                    <span
                      className="mr-1.5"
                      title={c.verified ? "인용 문장이 출처에서 확인됨" : "인용 문장을 출처에서 확인하지 못함"}
                    >
                      {c.verified ? "✓" : "✗"}
                    </span>
                    {c.url ? (
                      <a href={c.url} target="_blank" rel="noreferrer" className="underline">
                        {c.title}
                      </a>
                    ) : (
                      c.title
                    )}
                    {c.snippet ? (
                      <p className="mt-0.5 line-clamp-2 text-[12px] text-md-on-surface-variant">
                        {c.snippet}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : detail ? (
        <p className="text-body-sm text-md-on-surface-variant">이 답변을 대화에서 찾지 못했습니다.</p>
      ) : null}

      <div className="flex flex-col gap-3 rounded-card bg-md-surface-container-low p-3">
        <div className="flex flex-wrap items-center gap-2">
          {(Object.keys(VERDICT_LABEL) as ReviewVerdict[]).map((v) => (
            <PillTab key={v} active={verdict === v} label={VERDICT_LABEL[v]} onClick={() => setVerdict(v)} />
          ))}
          <Link
            href={`/admin/threads?thread=${encodeURIComponent(item.thread_id)}`}
            className="ml-auto text-[12px] text-md-on-surface-variant underline"
          >
            대화 전체 보기
          </Link>
        </div>
        {needsErrs ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {errorTypes.map((e) => (
              <label key={e} className="flex items-center gap-1.5 text-[13px] text-md-on-surface">
                <input
                  type="checkbox"
                  checked={errs.includes(e)}
                  onChange={(ev) =>
                    setErrs((cur) => (ev.target.checked ? [...cur, e] : cur.filter((x) => x !== e)))
                  }
                />
                {ERROR_LABEL[e] ?? e}
              </label>
            ))}
          </div>
        ) : null}
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="메모 (선택) — 무엇이 틀렸는지, 맞는 조문은 무엇인지"
          rows={2}
          maxLength={4000}
          className="w-full rounded border border-md-outline-variant bg-md-surface px-2 py-1.5 text-body-sm text-md-on-surface"
        />
        <ErrorBanner message={saveError} />
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!verdict || saving}
            className="rounded-pill bg-md-primary px-4 py-1.5 text-[13px] font-medium text-md-on-primary disabled:opacity-50"
          >
            {saving ? "저장 중..." : "채점 저장"}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * 채점 내역(2026-09-18) — 채점 시점의 질문·답변 스냅샷을 함께 보여 준다.
 * 대화는 90일 뒤 지워지지만 채점한 턴은 근거가 남아, 정답률을 나중에 되짚을 수 있다.
 */
function ReviewArchive() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ReviewArchiveItem[] | null>(null);
  const [verdict, setVerdict] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    getReviewArchive({ verdict: verdict || undefined })
      .then((r) => {
        if (!cancelled) setItems(r.items);
      })
      .catch(() => {
        if (!cancelled) setError("채점 내역을 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [open, verdict]);

  return (
    <section className="mt-8">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left text-[12px] font-semibold uppercase tracking-[0.08em] text-md-on-surface-variant"
      >
        <span className="material-symbols-outlined text-[16px]" aria-hidden>
          {open ? "expand_more" : "chevron_right"}
        </span>
        채점 내역 (질문·답변 보존)
      </button>
      {open ? (
        <div className="mt-3 flex flex-col gap-3">
          <p className="text-body-sm text-md-on-surface-variant">
            채점한 턴은 질문·답변을 채점 시점에 복사해 둡니다(개인정보가 가려진 저장본). 원 대화가 보존기간 90일로 지워져도 여기서 볼 수 있습니다.
          </p>
          <div className="flex flex-wrap gap-2">
            <PillTab active={verdict === ""} label="전체" onClick={() => setVerdict("")} />
            {(Object.keys(VERDICT_LABEL) as ReviewVerdict[]).map((v) => (
              <PillTab key={v} active={verdict === v} label={VERDICT_LABEL[v]} onClick={() => setVerdict(v)} />
            ))}
          </div>
          <ErrorBanner message={error} />
          {items === null && !error ? (
            <div className="flex justify-center py-6">
              <Spinner size={20} />
            </div>
          ) : null}
          <ul className="flex flex-col gap-2">
            {(items ?? []).map((it) => (
              <li key={it.id} className="rounded-card border border-md-outline-variant bg-md-surface-container-low">
                <button
                  type="button"
                  onClick={() => setOpenId((cur) => (cur === it.id ? null : it.id))}
                  className="flex w-full items-center gap-3 px-3 py-2 text-left"
                >
                  <span className="shrink-0 rounded-pill bg-md-surface-container-high px-2 py-0.5 text-[11px] font-medium text-md-on-surface">
                    {VERDICT_LABEL[it.verdict] ?? it.verdict}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-body-sm text-md-on-surface">
                    {it.question_snapshot ?? "(스냅샷 없음 — 보존 기능 도입 전 채점)"}
                  </span>
                  {!it.thread_alive ? (
                    <span className="shrink-0 text-[11px] text-md-on-surface-variant">원 대화 삭제됨</span>
                  ) : null}
                  <span className="shrink-0 text-[11px] tabular-nums text-md-on-surface-variant">
                    {formatTime(it.updated_at)}
                  </span>
                </button>
                {openId === it.id ? (
                  <div className="flex flex-col gap-3 border-t border-md-outline-variant px-3 py-3">
                    {it.question_snapshot ? <Block title="질문">{it.question_snapshot}</Block> : null}
                    {it.answer_snapshot ? <Block title="답변">{it.answer_snapshot}</Block> : null}
                    <p className="text-[12px] text-md-on-surface-variant">
                      검수자 {it.reviewer}
                      {it.error_types.length ? ` · ${it.error_types.map((e) => ERROR_LABEL[e] ?? e).join(", ")}` : ""}
                      {it.note ? ` · 메모: ${it.note}` : ""}
                    </p>
                  </div>
                ) : null}
              </li>
            ))}
            {items && items.length === 0 ? (
              <li className="rounded-card border border-md-outline-variant px-4 py-6 text-center text-md-on-surface-variant">
                채점 내역이 없습니다.
              </li>
            ) : null}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function Block({ title, children }: { title: string; children: string }) {
  return (
    <div>
      <h3 className="mb-1 text-[12px] font-semibold text-md-on-surface-variant">{title}</h3>
      <div
        className="max-h-[420px] overflow-y-auto whitespace-pre-wrap rounded-card border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm leading-relaxed text-md-on-surface"
        style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
      >
        {children}
      </div>
    </div>
  );
}
