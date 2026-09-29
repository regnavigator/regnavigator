"use client";

/**
 * PII 라벨링 문맥 팝오버(2026-09-21) — "필터된 단어만 보고는 알 수 없다 → 주변 원문을 팝오버로".
 *
 * 대화는 가린 상태로만 저장된다(원문 미보존이 설계). 그래서 보여주는 것은 그 단어가 관측된 대화에서
 * 가림 표시(`[이름]` 등)가 들어간 질문의 앞뒤이고, 가림 자리를 강조해 "여기에 이 단어가 있었다"를 보인다.
 * 같은 질문에 같은 종류 가림이 여럿이면 어느 자리인지 특정하지 않는다. 열 때 한 번 조회(지연 로드).
 */
import { useState } from "react";
import { getPiiTermContext, type PiiTermContext } from "@/lib/client/admin";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatTime } from "@/components/admin/common";

export function PiiContextPopover({ term }: { term: string }) {
  const [data, setData] = useState<PiiTermContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (data || loading) return;
    setLoading(true);
    setError(null);
    try {
      setData(await getPiiTermContext(term));
    } catch (err) {
      console.error("[admin/pii] context failed", err);
      setError("문맥을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Popover onOpenChange={(o) => (o ? void load() : undefined)}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded border border-md-outline-variant px-2.5 py-1 text-[12px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low"
          title="이 단어가 가려진 질문의 앞뒤 보기"
        >
          <span className="material-symbols-outlined text-[15px]" aria-hidden>
            format_quote
          </span>
          문맥
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(92vw,460px)] p-0 text-[12.5px]">
        <div className="border-b border-md-outline-variant px-3.5 py-2.5">
          <p className="font-semibold text-md-on-surface">
            &lsquo;{term}&rsquo; 이 가려진 문맥
          </p>
          <p className="mt-0.5 text-[11.5px] text-md-on-surface-variant">
            대화는 가린 상태로만 저장돼 원문 대신 가림 자리
            {data?.placeholder ? <code className="mx-1 rounded bg-md-surface-container-high px-1">{data.placeholder}</code> : " "}
            주변을 보여줍니다.
          </p>
        </div>
        <div className="flex max-h-[340px] flex-col gap-2 overflow-y-auto px-3.5 py-3">
          {loading ? <p className="text-md-on-surface-variant">불러오는 중…</p> : null}
          {error ? <p className="text-md-error">{error}</p> : null}
          {data && data.contexts.length === 0 ? (
            <p className="text-md-on-surface-variant">
              {data.threads_known === 0
                ? "관측된 대화 기록이 없습니다(이 기능 이전에 수집된 단어일 수 있음)."
                : data.missing_threads
                  ? `관측된 대화 ${data.missing_threads}개가 이미 삭제됐습니다(보관기간 경과 등).`
                  : "가림 표시가 남은 질문을 찾지 못했습니다."}
            </p>
          ) : null}
          {data?.contexts.map((c, i) => (
            <div key={`${c.thread_id}-${i}`} className="rounded-md border border-md-outline-variant bg-md-surface-container-lowest px-3 py-2">
              <p className="whitespace-pre-wrap break-words leading-relaxed text-md-on-surface">
                {c.before}
                <mark
                  className="rounded bg-md-tertiary-fixed px-1 font-semibold text-[var(--md-on-tertiary-fixed-variant)]"
                  title={c.exact || c.same_kind === 1 ? `여기에 '${term}' 이 있었음` : "같은 종류 가림이 여러 곳 — 어느 자리인지 특정할 수 없음"}
                >
                  {c.mark}
                  {c.exact || c.same_kind === 1 ? ` ← ${term}` : ""}
                </mark>
                {c.after}
              </p>
              <p className="mt-1.5 flex flex-wrap gap-x-2 text-[11px] text-md-on-surface-variant">
                {c.created_at ? <span>{formatTime(c.created_at)}</span> : null}
                {c.exact ? (
                  <span className="text-md-primary">정확한 자리</span>
                ) : c.same_kind > 1 ? (
                  <span>같은 종류 가림 {c.same_kind}곳 — 자리 기록 전 수집분이라 특정 불가</span>
                ) : null}
                <a
                  href={`/admin/threads?thread=${encodeURIComponent(c.thread_id)}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-md-primary hover:underline"
                >
                  대화 원문 열기
                </a>
              </p>
            </div>
          ))}
          {data && data.siblings.length > 0 ? (
            <div className="rounded-md bg-md-surface-container-low px-3 py-2">
              <p className="text-[11.5px] font-medium text-md-on-surface">
                같은 질문에서 함께 {data.placeholder ?? ""}(으)로 가려진 단어 {data.siblings.length}개
              </p>
              <p className="mt-1 flex flex-wrap gap-1">
                {data.siblings.map((s) => (
                  <span key={s} className="rounded bg-md-surface px-1.5 py-0.5 text-[11.5px] text-md-on-surface">
                    {s}
                  </span>
                ))}
              </p>
              <p className="mt-1 text-[11px] text-md-on-surface-variant">
                자리는 특정할 수 없지만, 함께 가려진 단어들로 성격(예: 참고문헌 저자 목록)을 판단할 수 있습니다.
              </p>
            </div>
          ) : null}
          {data && data.contexts.length > 0 && data.missing_threads ? (
            <p className="text-[11px] text-md-on-surface-variant">그 밖에 삭제된 대화 {data.missing_threads}개</p>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
