"use client";

/**
 * WatchPanel — 모니터링 스레드의 **관찰 목록** (2026-10-02).
 *
 * 설계: `backend/docs/spec/monitor-threads-design.md`.
 *
 * 구성은 **등록된 것 먼저, 아직 안 된 것 아래**다(실사용 요청 2026-10-02).
 * 종전엔 후보를 보려면 [+ 조문 추가]를 눌러 별도 블록을 열어야 했는데, 그러면
 * "지금 무엇을 보고 있고 무엇을 더 담을 수 있는지"가 한 화면에 안 들어온다.
 *
 * 핵심 규율: **자동으로 넣지 않는다.** 검색 인용은 출처 적합성 필터를 거쳐도
 * 노이즈가 남는다. 관찰 목록이 오염되면 알람이 쓰레기가 되고, 그러면 사용자가
 * 알람을 안 보게 된다 — 그 순간 이 기능이 죽는다. 제안까지만 하고 승인은 사람이.
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  addWatch,
  detectNow,
  lawDbReady,
  listWatch,
  recommendWatch,
  removeWatch,
  suggestWatch,
  type Suggestion,
  type WatchItem,
} from "@/lib/client/monitorThreads";

/** 관찰 목록이 바뀌면 인용 패널의 [관찰] 버튼 상태도 따라와야 한다. */
export const WATCH_CHANGED_EVENT = "regnav-watch-changed";

export function WatchPanel({
  threadId,
  onChanged,
}: {
  threadId: string;
  onChanged?: () => void;
}) {
  const [items, setItems] = useState<WatchItem[] | null>(null);
  const [sugs, setSugs] = useState<Suggestion[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  /** 발췌를 펼친 후보 — 기본은 3줄로 잘라 목록이 길어지지 않게 한다. */
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  /** 추천 {조문키: 사유} — 자동으로 담지는 않는다. */
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [recState, setRecState] = useState<"idle" | "running" | "done" | "skipped">(
    "idle",
  );
  const [busy, setBusy] = useState(false);
  /** 법령 DB 연결 — null=확인 전, true=가능, false=미연결(감지 불가) */
  const [lawDbUp, setLawDbUp] = useState<boolean | null>(null);

  useEffect(() => {
    void lawDbReady().then(setLawDbUp);
  }, []);

  /** 등록분과 후보를 **같이** 읽는다 — 두 목록이 한 화면에 있어야 한다. */
  const reload = useCallback(async () => {
    const [w, s] = await Promise.all([
      listWatch(threadId),
      suggestWatch(threadId).catch(() => ({ suggestions: [], watching: 0 })),
    ]);
    setItems(w.items);
    setSugs(s.suggestions.filter((x) => !x.already));
    setPicked(new Set());
    onChanged?.();
  }, [threadId, onChanged]);

  /** 여기서 바꿨으면 인용 패널의 [관찰] 버튼도 따라와야 한다(양방향 동기화). */
  const reloadAndBroadcast = useCallback(async () => {
    await reload();
    window.dispatchEvent(new CustomEvent(WATCH_CHANGED_EVENT));
  }, [reload]);

  useEffect(() => {
    void reload().catch(() => setItems([]));
  }, [reload]);

  // 인용 패널에서 담아도 이 목록이 즉시 따라오게 한다.
  useEffect(() => {
    const h = () => void reload().catch(() => undefined);
    window.addEventListener(WATCH_CHANGED_EVENT, h);
    return () => window.removeEventListener(WATCH_CHANGED_EVENT, h);
  }, [reload]);

  const runRecommend = useCallback(async () => {
    setRecState("running");
    try {
      const r = await recommendWatch(threadId);
      setPicks(r.picks);
      setRecState(r.skipped === "confidential" ? "skipped" : "done");
      if (!r.skipped && !Object.keys(r.picks).length) {
        toast.info("담을 만한 조문을 찾지 못했습니다.", {
          description: "후보를 직접 보고 골라 주세요.",
        });
      }
    } catch {
      setRecState("idle");
      toast.error("추천을 받지 못했습니다.");
    }
  }, [threadId]);

  const commit = useCallback(async () => {
    const chosen = sugs.filter((s) => picked.has(s.article_key));
    if (!chosen.length) return;
    setBusy(true);
    try {
      const r = await addWatch(threadId, chosen.map((s) => s.citation), "ai");
      toast.success(`${r.added.length}건을 관찰 목록에 넣었습니다.`, {
        description: r.skipped.length
          ? `관찰할 수 없는 항목 ${r.skipped.length}건은 제외했습니다(조문 키 없음).`
          : undefined,
      });
      await reloadAndBroadcast();
    } catch {
      toast.error("추가하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }, [sugs, picked, threadId, reloadAndBroadcast]);

  const drop = useCallback(
    async (ak: string) => {
      try {
        await removeWatch(threadId, ak);
        await reloadAndBroadcast();
      } catch {
        toast.error("빼지 못했습니다.");
      }
    },
    [threadId, reloadAndBroadcast],
  );

  const check = useCallback(async () => {
    setBusy(true);
    const t = toast.loading("변경을 확인하는 중…");
    try {
      const r = await detectNow(threadId);
      if (!r.complete) {
        // "변경 없음"과 "확인 못 함"을 섞으면 안 된다 — 이게 이 도구의 핵심이다.
        toast.warning("확인하지 못했습니다", {
          id: t,
          description:
            "법령 DB를 조회할 수 없어 알람을 만들지 않았습니다. 변경이 없다는 뜻이 아닙니다.",
          duration: 9000,
        });
      } else if (r.created) {
        toast.success(`새 변경 ${r.created}건을 찾았습니다.`, { id: t });
        onChanged?.();
      } else {
        toast.success(`관찰 ${r.checked}건 — 새 변경 없음`, { id: t });
      }
    } catch {
      toast.error("확인하지 못했습니다.", { id: t });
    } finally {
      setBusy(false);
    }
  }, [threadId, onChanged]);

  // 추천된 것이 위로 — 사유가 붙은 항목을 먼저 보게 한다.
  const sorted = [...sugs].sort(
    (a, b) => (picks[b.article_key] ? 1 : 0) - (picks[a.article_key] ? 1 : 0),
  );

  if (!items) {
    return (
      <p className="px-3 py-4 text-[12px] text-md-on-surface-variant">불러오는 중…</p>
    );
  }

  return (
    <section data-testid="watch-panel" className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-md-outline-variant px-3 py-2">
        <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>
          visibility
        </span>
        <h3 className="flex-1 text-[12.5px] font-bold">
          관찰 목록 <span className="text-md-on-surface-variant">{items.length}</span>
        </h3>
        <button
          type="button"
          data-testid="watch-check"
          disabled={busy || !items.length}
          onClick={() => void check()}
          className="rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary disabled:opacity-40"
        >
          변경 확인
        </button>
      </header>

      {lawDbUp === false ? (
        <p
          data-testid="lawdb-down"
          className="flex items-start gap-1.5 border-b border-md-outline-variant bg-md-error-container/40 px-3 py-2 text-[11px] leading-[1.55] text-md-on-surface"
        >
          <span className="material-symbols-outlined mt-[1px] text-[13px] text-md-error" aria-hidden>
            error
          </span>
          <span>
            <b>법령 DB 미연결 — 변경을 감지할 수 없습니다.</b> 관찰 목록은 저장되지만
            개정·폐지 알람은 생성되지 않습니다. 변경이 없다는 뜻이 아닙니다.
            <span className="block opacity-70">설정: backend <code>PG_*</code></span>
          </span>
        </p>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* ── 등록된 것 먼저 ───────────────────────────────────────── */}
        <h4 className="sticky top-0 z-10 bg-md-surface px-3 py-1.5 text-[10.5px] font-semibold tracking-[0.02em] text-md-on-surface-variant">
          관찰 중 {items.length}
        </h4>
        {items.length === 0 ? (
          <p className="px-3 pb-3 text-[11.5px] leading-relaxed text-md-on-surface-variant">
            아직 담은 조문이 없습니다. 아래에서 고르거나, 답변의 인용을 열어
            <b> 관찰</b>을 누르세요.
          </p>
        ) : (
          <ul>
            {items.map((w) => (
              <li
                key={w.article_key}
                data-watch={w.article_key}
                className="group flex items-start gap-2 border-b border-md-outline-variant/60 px-3 py-2"
              >
                <span
                  className="material-symbols-outlined mt-[1px] shrink-0 text-[14px] text-md-primary"
                  aria-hidden
                >
                  check_circle
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[12px] leading-snug text-md-on-surface">
                    {w.title}
                  </span>
                  <span className="text-[10.5px] text-md-on-surface-variant">
                    {w.added_by === "ai"
                      ? "대화에서 추가"
                      : w.added_by === "file"
                        ? "자료에서 추출"
                        : "직접 추가"}
                  </span>
                  {/* 담은 것도 무엇이었는지 바로 보이게 — 제목만으론 기억이 안 난다. */}
                  {w.citation?.snippet ? (
                    <span className="mt-1 block line-clamp-2 whitespace-pre-wrap text-[11px] leading-[1.55] text-md-on-surface-variant/80">
                      {w.citation.snippet}
                    </span>
                  ) : null}
                </span>
                <button
                  type="button"
                  aria-label="관찰에서 빼기"
                  onClick={() => void drop(w.article_key)}
                  className="material-symbols-outlined shrink-0 text-[15px] text-md-on-surface-variant opacity-0 transition-opacity hover:text-md-error focus-visible:opacity-100 group-hover:opacity-100"
                >
                  close
                </button>
              </li>
            ))}
          </ul>
        )}

        {/* ── 아직 안 담은 것 ──────────────────────────────────────── */}
        <div className="sticky top-0 z-10 mt-2 flex items-center gap-2 bg-md-surface px-3 py-1.5">
          <h4 className="flex-1 text-[10.5px] font-semibold tracking-[0.02em] text-md-on-surface-variant">
            이 대화에서 찾은 규제 {sugs.length}
          </h4>
          {sugs.length > 0 ? (
            <button
              type="button"
              data-testid="watch-recommend"
              disabled={recState === "running"}
              onClick={() => void runRecommend()}
              title="담을 만한 조문을 골라 이유와 함께 보여 줍니다 — 자동으로 담지는 않습니다"
              className="inline-flex items-center gap-1 rounded-pill border border-md-outline-variant px-2 py-0.5 text-[10.5px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary disabled:opacity-40"
            >
              <span className="material-symbols-outlined text-[12px]" aria-hidden>
                auto_awesome
              </span>
              {recState === "running" ? "고르는 중…" : "추천 받기"}
            </button>
          ) : null}
        </div>
        {recState === "skipped" ? (
          <p className="px-3 pb-1 text-[10.5px] leading-snug text-md-on-surface-variant">
            기밀 대화라 추천을 건너뛰었습니다 — 대화 주제를 외부 모델로 보내지
            않습니다.
          </p>
        ) : null}
        {recState === "done" && Object.keys(picks).length > 0 ? (
          <div className="flex items-center justify-between gap-2 px-3 pb-1">
            <p className="text-[10.5px] text-md-on-surface-variant">
              {Object.keys(picks).length}건을 추천했습니다. 사유를 보고 고르세요.
            </p>
            <button
              type="button"
              data-testid="watch-pick-recommended"
              onClick={() =>
                setPicked(
                  new Set(
                    sugs
                      .filter((x) => picks[x.article_key])
                      .map((x) => x.article_key),
                  ),
                )
              }
              className="shrink-0 text-[10.5px] font-medium text-md-primary underline underline-offset-2"
            >
              추천 전부 선택
            </button>
          </div>
        ) : null}
        {sugs.length === 0 ? (
          <p className="px-3 pb-3 text-[11.5px] leading-relaxed text-md-on-surface-variant">
            더 담을 조문이 없습니다. 질문을 더 하면 근거가 쌓이고, 그중에서 고를 수
            있습니다.
          </p>
        ) : (
          <>
            <p className="px-3 pb-1 text-[10.5px] leading-snug text-md-on-surface-variant/80">
              담을 것만 고르세요 — 자동으로 넣지 않습니다.
            </p>
            <ul data-testid="watch-candidates">
              {sorted.map((s) => (
                <li key={s.article_key} className="border-b border-md-outline-variant/60">
                  <label
                    data-candidate={s.article_key}
                    className="flex cursor-pointer items-start gap-2 px-3 py-2 text-[12px] hover:bg-md-surface-container-low"
                  >
                    <input
                      type="checkbox"
                      checked={picked.has(s.article_key)}
                      onChange={(e) =>
                        setPicked((prev) => {
                          const n = new Set(prev);
                          if (e.target.checked) n.add(s.article_key);
                          else n.delete(s.article_key);
                          return n;
                        })
                      }
                      className="mt-[3px] shrink-0"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block leading-snug text-md-on-surface">
                        {picks[s.article_key] ? (
                          <span className="mr-1 inline-flex items-center gap-0.5 rounded-[4px] bg-md-primary-container px-1 py-[1px] align-[1px] text-[9.5px] font-semibold text-md-on-primary-container">
                            <span
                              className="material-symbols-outlined text-[10px]"
                              aria-hidden
                            >
                              auto_awesome
                            </span>
                            추천
                          </span>
                        ) : null}
                        {s.title ?? s.article_key}
                      </span>
                      {/* 왜 담아야 하는지(2026-10-02) — 추천만 하고 이유를 안 주면
                          고를 근거가 없다(실사용 요청). */}
                      {picks[s.article_key] ? (
                        <span
                          data-pick-reason={s.article_key}
                          className="mt-0.5 flex gap-1 text-[10.5px] leading-[1.5] text-md-primary"
                        >
                          <span
                            className="material-symbols-outlined mt-[1px] text-[11px]"
                            aria-hidden
                          >
                            arrow_right
                          </span>
                          {picks[s.article_key]}
                        </span>
                      ) : null}
                      {s.doc_category ? (
                        <span className="text-[10.5px] text-md-on-surface-variant">
                          {s.doc_category}
                        </span>
                      ) : null}
                      {/* 본문 발췌(2026-10-02) — 제목만 주고 고르라는 건 외워서
                          고르라는 말이다(실사용 지적). 기본 3줄, 길면 펼친다. */}
                      {s.citation?.snippet ? (
                        <>
                          <span
                            data-snippet={s.article_key}
                            className={
                              "mt-1 block whitespace-pre-wrap rounded-[6px] bg-md-surface-container-low px-2 py-1 text-[11px] leading-[1.6] text-md-on-surface-variant " +
                              (expanded.has(s.article_key) ? "" : "line-clamp-3")
                            }
                          >
                            {s.citation.snippet}
                          </span>
                          {(s.citation.snippet ?? "").length > 110 ? (
                            <button
                              type="button"
                              data-snippet-toggle={s.article_key}
                              onClick={(e) => {
                                // label 안이라 막지 않으면 체크박스가 같이 눌린다.
                                e.preventDefault();
                                e.stopPropagation();
                                setExpanded((prev) => {
                                  const n = new Set(prev);
                                  if (n.has(s.article_key)) n.delete(s.article_key);
                                  else n.add(s.article_key);
                                  return n;
                                });
                              }}
                              className="mt-0.5 text-[10.5px] text-md-primary underline underline-offset-2"
                            >
                              {expanded.has(s.article_key) ? "접기" : "더 보기"}
                            </button>
                          ) : null}
                        </>
                      ) : null}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {picked.size > 0 ? (
        <div className="flex items-center justify-between gap-2 border-t border-md-outline-variant bg-md-surface-container-lowest px-3 py-2">
          <button
            type="button"
            onClick={() => setPicked(new Set())}
            className="text-[11.5px] text-md-on-surface-variant underline underline-offset-2"
          >
            선택 해제
          </button>
          <button
            type="button"
            data-testid="watch-commit"
            disabled={busy}
            onClick={() => void commit()}
            className="rounded-pill bg-md-primary px-3 py-1 text-[11.5px] font-semibold text-md-on-primary disabled:opacity-40"
          >
            {picked.size}건 관찰 목록에 담기
          </button>
        </div>
      ) : null}
    </section>
  );
}
