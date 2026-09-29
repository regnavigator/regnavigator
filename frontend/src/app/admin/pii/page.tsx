"use client";

/**
 * Admin · PII 마스킹 라벨링 — backend `/admin/pii-terms` (2026-08-13).
 *
 * 채팅에서 NER 마스킹된 **모든 단어**가 자동 수집돼 여기 쌓인다(신고분은
 * reported 표시). 각 단어를 라벨링한다:
 * - 제대로 필터(correct): 진짜 개인정보 — 마스킹 유지, 신고로 풀려 있었다면 복귀
 * - 잘못 필터(wrong): 오탐 — 마스킹 영구 제외(검색에 그대로 들어감)
 *
 * ⚠️ 신고는 선보고 후조치 — reported 상태는 **이미 마스킹 제외 적용 중**이다.
 * 실명 오신고를 발견하면 즉시 correct 라벨로 되돌릴 것.
 */

import { useCallback, useEffect, useState } from "react";
import {
  labelPiiTerm,
  listPiiTerms,
  removePiiTerm,
  type PiiTermItem,
  type PiiTermStatus,
} from "@/lib/client/admin";
import { ErrorBanner, PillTab, formatTime } from "@/components/admin/common";
import { PiiContextPopover } from "@/components/admin/PiiContextPopover";

const STATUS_TABS: { key: PiiTermStatus | "all"; label: string }[] = [
  { key: "all", label: "전체" },
  { key: "reported", label: "신고됨 (적용 중)" },
  { key: "unlabeled", label: "미라벨 (자동 수집)" },
  { key: "wrong", label: "오탐 확정" },
  { key: "correct", label: "정탐 확정" },
];

const STATUS_BADGE: Record<PiiTermStatus, { label: string; cls: string }> = {
  reported: {
    label: "신고됨 · 마스킹 해제 중",
    cls: "bg-md-error-container text-md-on-error-container",
  },
  unlabeled: {
    label: "미라벨",
    cls: "bg-md-surface-container-low text-md-on-surface-variant",
  },
  wrong: {
    label: "오탐 (해제)",
    cls: "bg-md-primary-fixed text-md-on-primary-fixed-variant",
  },
  correct: {
    label: "정탐 (마스킹 유지)",
    cls: "bg-md-surface-container-high text-md-on-surface",
  },
};

export default function AdminPiiPage() {
  const [tab, setTab] = useState<PiiTermStatus | "all">("all");
  const [items, setItems] = useState<PiiTermItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null); // 처리 중인 term
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (which: PiiTermStatus | "all") => {
    setLoading(true);
    setError(null);
    try {
      const page = await listPiiTerms(
        which === "all" ? undefined : { status: which },
      );
      setItems(page.items);
    } catch (err) {
      console.error("[admin/pii] list failed", err);
      setError("목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload(tab);
  }, [tab, reload]);

  async function onLabel(term: string, label: "correct" | "wrong") {
    setBusy(term);
    setError(null);
    try {
      await labelPiiTerm(term, label);
      await reload(tab);
    } catch (err) {
      console.error("[admin/pii] label failed", err);
      setError(
        label === "wrong"
          ? "라벨 실패 — 개인정보 형식(주민번호·전화 등)은 해제할 수 없습니다."
          : "라벨을 저장하지 못했습니다.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function onRemove(term: string) {
    if (!window.confirm(`'${term}' 항목을 목록에서 삭제할까요?\n(오탐 해제였다면 다시 마스킹 대상이 됩니다)`)) {
      return;
    }
    setBusy(term);
    try {
      await removePiiTerm(term);
      await reload(tab);
    } catch (err) {
      console.error("[admin/pii] remove failed", err);
      setError("삭제하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  }

  const reportedCount = items.filter((i) => i.status === "reported").length;

  return (
    <main className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-h1 text-md-on-surface">PII 필터 라벨링</h1>
        <p className="text-body-sm text-md-on-surface-variant">
          채팅에서 개인정보로 감지·마스킹된 단어 전체입니다. 제대로 걸렀는지
          라벨링하세요 — <b>신고됨</b> 상태는 이미 마스킹이 풀려 있으니(선보고
          후조치) 실명이면 즉시 &lsquo;정탐&rsquo;으로 되돌리세요.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        {STATUS_TABS.map((t) => (
          <PillTab
            key={t.key}
            active={tab === t.key}
            label={t.label}
            onClick={() => setTab(t.key)}
          />
        ))}
        <span className="ml-auto text-body-sm text-md-on-surface-variant">
          {items.length}건{reportedCount ? ` · 신고 ${reportedCount}건 검토 대기` : ""}
        </span>
      </div>

      <ErrorBanner message={error} />

      <ul className="flex flex-col gap-2">
        {items.map((it) => (
          <li
            key={it.term}
            className="flex flex-wrap items-center gap-3 rounded-card border border-md-outline-variant bg-md-surface px-4 py-3"
          >
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-body font-semibold text-md-on-surface">
                  {it.term}
                </span>
                {it.placeholder ? (
                  <code className="rounded bg-md-surface-container-low px-1.5 py-0.5 font-mono text-[10.5px] text-md-on-surface-variant">
                    {it.placeholder}
                  </code>
                ) : null}
                <span
                  className={`inline-flex items-center rounded-pill px-2 py-0.5 text-[11px] font-semibold ${STATUS_BADGE[it.status].cls}`}
                >
                  {STATUS_BADGE[it.status].label}
                </span>
              </div>
              <div className="flex flex-wrap gap-3 text-[11.5px] text-md-on-surface-variant">
                <span>관측 {it.count}회</span>
                {it.reported ? <span>신고 {it.report_count}회</span> : null}
                {it.last_seen_at ? (
                  <span>최근 {formatTime(it.last_seen_at)}</span>
                ) : null}
                {it.labeled_by ? <span>라벨: {it.labeled_by}</span> : null}
                {it.comment ? <span className="truncate">“{it.comment}”</span> : null}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {/* 문맥 팝오버(2026-09-21) — 단어만으로 판단이 어려울 때 가린 질문의 앞뒤 */}
              <PiiContextPopover term={it.term} />
              <button
                type="button"
                disabled={busy === it.term || it.label === "correct"}
                onClick={() => void onLabel(it.term, "correct")}
                className="rounded border border-md-outline-variant px-2.5 py-1 text-[12px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low disabled:opacity-40"
                title="진짜 개인정보 — 마스킹 유지(신고로 풀려 있었다면 복귀)"
              >
                제대로 필터
              </button>
              <button
                type="button"
                disabled={busy === it.term || it.label === "wrong"}
                onClick={() => void onLabel(it.term, "wrong")}
                className="rounded border border-md-outline-variant px-2.5 py-1 text-[12px] font-medium text-md-primary transition-colors hover:bg-md-surface-container-low disabled:opacity-40"
                title="오탐 — 마스킹 영구 제외(검색에 그대로 들어감)"
              >
                잘못 필터
              </button>
              <button
                type="button"
                disabled={busy === it.term}
                onClick={() => void onRemove(it.term)}
                className="rounded px-2 py-1 text-[12px] text-md-on-surface-variant transition-colors hover:bg-md-error-container hover:text-md-on-error-container disabled:opacity-40"
                title="목록에서 삭제"
              >
                삭제
              </button>
            </div>
          </li>
        ))}
        {items.length === 0 && !loading ? (
          <li className="rounded-card border border-md-outline-variant px-4 py-8 text-center text-md-on-surface-variant">
            {tab === "all"
              ? "수집된 단어가 없습니다."
              : "이 상태의 단어가 없습니다."}
          </li>
        ) : null}
      </ul>
      {loading ? (
        <p className="text-center text-body-sm text-md-on-surface-variant">
          불러오는 중...
        </p>
      ) : null}
    </main>
  );
}
