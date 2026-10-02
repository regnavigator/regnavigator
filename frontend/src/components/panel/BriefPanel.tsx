"use client";

/**
 * BriefPanel — 서면·의견서 초안: 문단을 골라 그것만 고친다 (2026-10-01).
 *
 * 서식 패널은 **빈 칸**을 채우지만, 서면은 칸이 없는 산문이다. 그래서 진입점이
 * "이 항목 채우기" 가 아니라 **"이 문단 고치기"** 가 된다.
 *
 * 안전 규율 두 가지가 UI 에도 그대로 드러난다:
 *  - 수정 요청에는 화면에 보이는 **원문을 함께** 보낸다. 서버가 그 자리 내용이
 *    아직 같은지 확인하고, 다르면 409 로 거부한다. 그때는 목록을 다시 받는다 —
 *    조용히 다른 문단이 바뀌는 것이 최악이다.
 *  - 문서에 없는 인용 번호를 모델이 붙이면 서버가 떼어내고 알려 준다. 그 사실을
 *    토스트로 **반드시 보여 준다** — 근거가 사라진 걸 모르면 그대로 제출한다.
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  getBriefParagraphs,
  polishBrief,
  reviseBriefParagraph,
  type BriefParagraph,
} from "@/lib/client/documents";

type Props = {
  reportId: string;
  title?: string;
  onClose?: () => void;
};

export function BriefPanel({ reportId, title, onClose }: Props) {
  const [paras, setParas] = useState<BriefParagraph[] | null>(null);
  const [docTitle, setDocTitle] = useState(title ?? "");
  const [active, setActive] = useState<number | null>(null);
  const [instruction, setInstruction] = useState("");
  const [manual, setManual] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const d = await getBriefParagraphs(reportId);
    setParas(d.paragraphs);
    setDocTitle(d.title || title || "");
  }, [reportId, title]);

  useEffect(() => {
    void reload().catch(() => {
      toast.error("문서를 불러오지 못했습니다.");
      setParas([]);
    });
  }, [reload]);

  const target = paras?.find((p) => p.index === active) ?? null;

  const submit = useCallback(
    async (mode: "ai" | "manual") => {
      if (!target || busy) return;
      if (mode === "ai" && !instruction.trim()) return;
      if (mode === "manual" && !(manual ?? "").trim()) return;
      setBusy(true);
      try {
        const r = await reviseBriefParagraph(reportId, {
          index: target.index,
          original_text: target.text,
          ...(mode === "ai"
            ? { instruction: instruction.trim() }
            : { replacement: (manual ?? "").trim() }),
        });
        setParas(r.paragraphs);
        setActive(null);
        setInstruction("");
        setManual(null);
        if (r.dropped_citations.length) {
          // 조용히 넘어가면 사용자는 근거가 빠진 줄 모른 채 서면을 낸다.
          toast.warning(
            `문서에 없는 인용 ${r.dropped_citations
              .map((n) => `[${n}]`)
              .join(" ")} 을 제거했습니다.`,
            { description: "모델이 만들어 낸 번호입니다. 근거를 직접 확인하세요.", duration: 10000 },
          );
        } else {
          toast.success("문단을 수정했습니다.");
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : "";
        const status = (e as { status?: number })?.status;
        // 서버가 보낸 사유를 그대로 쓴다 — "설정 안 됨"과 "연결 실패"는 다른 조치다.
        let detail = "";
        try {
          const m = msg.match(/\{[\s\S]*\}$/);
          if (m) {
            const parsed = JSON.parse(m[0]) as { detail?: unknown };
            if (typeof parsed.detail === "string") detail = parsed.detail;
          }
        } catch {
          /* 본문이 JSON 이 아니면 기본 문구 */
        }
        if (status === 409 || /409/.test(msg)) {
          toast.error("그 사이 문단이 바뀌었습니다", {
            description: "최신 내용을 다시 불러왔습니다. 확인 후 다시 시도하세요.",
          });
          void reload();
          setActive(null);
        } else if (status === 503 || /503/.test(msg)) {
          toast.error(detail || "원내 작성 모델을 쓸 수 없습니다", {
            description: "아래 [직접 고치기]로 문장을 적어 넣을 수 있습니다.",
            duration: 9000,
          });
          setManual(target.text);
        } else {
          toast.error("문단을 고치지 못했습니다.");
        }
      } finally {
        setBusy(false);
      }
    },
    [target, busy, instruction, manual, reportId, reload],
  );

  if (!paras) {
    return (
      <div className="flex h-full items-center justify-center text-[13px] text-md-on-surface-variant">
        불러오는 중…
      </div>
    );
  }

  return (
    <section data-testid="brief-panel" className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-md-outline-variant px-4 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <span className="material-symbols-outlined text-[17px] text-md-primary" aria-hidden>
            draft
          </span>
          <h2 className="truncate text-[13.5px] font-bold">{docTitle || "의견서 초안"}</h2>
        </div>
        <button
          type="button"
          data-testid="brief-polish"
          disabled={busy}
          onClick={() => {
            if (busy) return;
            setBusy(true);
            const t = toast.loading("보고서체로 다듬는 중…");
            void polishBrief(reportId)
              .then((r) => {
                setParas(r.paragraphs);
                setActive(null);
                const extra = r.dropped_citations.length
                  ? ` · 없는 인용 ${r.dropped_citations.map((n) => `[${n}]`).join(" ")} 제거`
                  : "";
                toast.success(`${r.polished.length}개 절을 다듬었습니다${extra}`, {
                  id: t,
                  description: r.skipped.length
                    ? `원문 유지: ${r.skipped.join(" · ")}`
                    : undefined,
                  duration: 9000,
                });
              })
              .catch((e) => {
                const msg = e instanceof Error ? e.message : "";
                let detail = "";
                try {
                  const m = msg.match(/\{[\s\S]*\}$/);
                  if (m) {
                    const parsed = JSON.parse(m[0]) as { detail?: unknown };
                    if (typeof parsed.detail === "string") detail = parsed.detail;
                  }
                } catch {
                  /* 기본 문구 */
                }
                toast.error(detail || "다듬지 못했습니다", { id: t, duration: 8000 });
              })
              .finally(() => setBusy(false));
          }}
          title="주어진 내용을 논리 순서로 재배열하고 보고서체로 고쳐 씁니다 — 새 사실은 보태지 않습니다"
          className="inline-flex h-7 items-center gap-1 rounded-pill border border-md-outline-variant px-2.5 text-[11.5px] font-medium text-md-on-surface-variant transition-colors hover:border-md-primary hover:text-md-primary disabled:opacity-40"
        >
          <span className="material-symbols-outlined text-[14px]" aria-hidden>
            auto_fix_high
          </span>
          다듬기
        </button>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="material-symbols-outlined text-[18px] text-md-on-surface-variant hover:text-md-on-surface"
          >
            close
          </button>
        ) : null}
      </header>

      <p className="border-b border-md-outline-variant px-4 py-2 text-[11.5px] leading-[1.6] text-md-on-surface-variant">
        고치고 싶은 문단을 누르세요. 선택한 문단만 바뀝니다 — 나머지는 건드리지 않습니다.
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {paras.map((p) =>
          p.kind === "heading" ? (
            <h3
              key={p.index}
              className="mt-4 mb-1.5 text-[13px] font-bold text-md-on-surface first:mt-0"
            >
              {p.text.replace(/^#+\s*/, "")}
            </h3>
          ) : (
            <div key={p.index} className="mb-2">
              <button
                type="button"
                data-para={p.index}
                onClick={() => {
                  setActive(active === p.index ? null : p.index);
                  setInstruction("");
                  setManual(null);
                }}
                className={
                  "w-full whitespace-pre-wrap rounded-[8px] border px-3 py-2 text-left text-[13px] leading-[1.75] transition-colors " +
                  (active === p.index
                    ? "border-md-primary bg-md-primary-container/30"
                    : "border-transparent hover:border-md-outline-variant hover:bg-md-surface-container-low")
                }
              >
                {p.text}
              </button>

              {active === p.index ? (
                <div className="mt-1.5 rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest p-2.5">
                  {manual === null ? (
                    <>
                      <input
                        value={instruction}
                        onChange={(e) => setInstruction(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey) {
                            e.preventDefault();
                            void submit("ai");
                          }
                        }}
                        placeholder="예: 더 간결하게 / 제척기간 쟁점을 덧붙여"
                        data-testid="brief-instruction"
                        className="w-full rounded-[6px] border border-md-outline-variant bg-md-surface px-2.5 py-1.5 text-[12.5px] outline-none focus:border-md-primary"
                      />
                      <div className="mt-1.5 flex items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setManual(p.text)}
                          className="text-[11.5px] text-md-on-surface-variant underline underline-offset-2 hover:text-md-on-surface"
                        >
                          직접 고치기
                        </button>
                        <button
                          type="button"
                          onClick={() => void submit("ai")}
                          disabled={busy || !instruction.trim()}
                          className="rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
                        >
                          {busy ? "고치는 중…" : "이 문단 고치기"}
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <textarea
                        value={manual}
                        onChange={(e) => setManual(e.target.value)}
                        rows={4}
                        data-testid="brief-manual"
                        className="w-full resize-y rounded-[6px] border border-md-outline-variant bg-md-surface px-2.5 py-1.5 text-[12.5px] leading-[1.7] outline-none focus:border-md-primary"
                      />
                      <div className="mt-1.5 flex items-center justify-between gap-2">
                        <button
                          type="button"
                          onClick={() => setManual(null)}
                          className="text-[11.5px] text-md-on-surface-variant underline underline-offset-2 hover:text-md-on-surface"
                        >
                          AI 에게 시키기
                        </button>
                        <button
                          type="button"
                          onClick={() => void submit("manual")}
                          disabled={busy || !manual.trim()}
                          className="rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
                        >
                          {busy ? "저장 중…" : "이 내용으로 저장"}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
            </div>
          ),
        )}
      </div>
    </section>
  );
}
