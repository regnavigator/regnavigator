"use client";

/**
 * AnnexModal — 별표/서식 인-앱 미리보기 (R5, back v9.x).
 *
 * - GET /annex?lawId&annexNum → markdown 본문 + download_url
 * - 외부 다운로드(law.go.kr presigned HWP)는 *직접 GET* — HEAD 요청 X (law.go.kr 거부)
 * - citation의 doc_category가 *별표서식*일 때 CitationInspector에서 트리거
 *
 * type 분기 (back 핸드오프):
 *   - "별표": markdown 본문 우선, download_url은 헤더 우상단 보조 버튼("HWP 다운로드")
 *   - "서식": HWP 다운로드가 주 용도 — 본문 상단에 prominent CTA("양식 다운로드") 카드,
 *            markdown은 미리보기 보조
 */

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getAnnex, type AnnexDetail } from "@/lib/client/annex";
import { formActionHint, formActionLabel } from "@/lib/formEntry";
import { getAnnexFillable, getAnnexViewHtml, type AnnexFillable } from "@/lib/client/annex";

type Props = {
  /** 활성 시 lawId + annexNum 둘 다 필수. null이면 모달 닫힘.
   *  `articleKey` 가 있으면 [이 서식으로 작성] 진입점이 붙는다(2026-08-27). */
  args: {
    lawId: string;
    annexNum: string;
    articleKey?: string;
    title?: string;
    isForm?: boolean;
    /** "별표" | "서식" — 같은 번호 공존 시 구분(2026-09-08) */
    type?: string | null;
  } | null;
  onClose: () => void;
  /** 별표·서식 → 기입 문서 열기. 없으면 버튼을 숨긴다. */
  onUseAsForm?: (articleKey: string, title: string) => void;
};

export function AnnexModal({ args, onClose, onUseAsForm }: Props) {
  const [detail, setDetail] = useState<AnnexDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 기입 가능 여부(2026-09-08 "입력 못하는 별표엔 입력 안내가 없어야"): undefined=조회 전,
  // null=판정 불가(서식이면 버튼 유지, 별표면 숨김), 객체=판정값.
  const [fillable, setFillable] = useState<AnnexFillable | null | undefined>(undefined);
  // 문서 뷰어(2026-09-08 "뷰어 형식으로 볼 수 없냐"): undefined=변환 중, null=불가(원본 링크로), string=HTML
  const [viewHtml, setViewHtml] = useState<string | null | undefined>(undefined);
  // 불가 사유(서버 reason) — HWPX 등 형식 문제와 서버 변환 오류를 구분해 안내(2026-09-09)
  const [viewReason, setViewReason] = useState<string | null>(null);

  useEffect(() => {
    const key = args?.articleKey ?? detail?.attachment_key;
    if (!key) {
      setViewHtml(undefined);
      return;
    }
    let alive = true;
    setViewHtml(undefined);
    setViewReason(null);
    void getAnnexViewHtml(key).then((v) => {
      if (!alive) return;
      setViewHtml(v.html);
      setViewReason(v.reason);
    });
    return () => {
      alive = false;
    };
  }, [args?.articleKey, detail?.attachment_key]);

  useEffect(() => {
    const key = args?.articleKey;
    if (!key) {
      setFillable(undefined);
      return;
    }
    let alive = true;
    setFillable(undefined);
    void getAnnexFillable(key).then((f) => {
      if (alive) setFillable(f);
    });
    return () => {
      alive = false;
    };
  }, [args?.articleKey]);

  useEffect(() => {
    if (!args) {
      setDetail(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    void getAnnex(args.lawId, args.annexNum, args.type ?? (args.isForm ? "서식" : undefined))
      .then((d) => setDetail(d))
      .catch((err) => {
        console.warn("[AnnexModal] fetch failed", err);
        setError("별표 본문을 불러오지 못했습니다.");
      })
      .finally(() => setLoading(false));
  }, [args]);

  if (!args) return null;

  // 종별 판정은 상세(type)를 우선하고, 없으면 호출자가 인용에서 판정한 값을 쓴다.
  const isForm = detail ? detail.type === "서식" : !!args?.isForm;
  const downloadLabel = isForm ? "양식 다운로드" : "HWP 다운로드";
  const headerSubLabel = detail?.type ?? "별표/서식";
  // [작성] 노출: 판정 확정 → fillable 값. 판정 불가 → 서식만(별표는 기준표일 확률이 높아 숨김).
  const canFill =
    fillable === undefined ? false : fillable === null ? isForm : fillable.fillable;
  const notFillable = fillable != null && !fillable.fillable;

  return (
    <Dialog open={!!args} onOpenChange={(o) => (!o ? onClose() : null)}>
      <DialogContent className="flex h-[88vh] w-[min(96vw,1120px)] max-w-none flex-col gap-0 border border-md-outline-variant bg-md-surface p-0 text-md-on-surface shadow-xl">
        <DialogHeader className="flex shrink-0 flex-row items-center gap-3 space-y-0 border-b border-md-outline-variant px-6 py-5">
          <span
            aria-hidden
            className="material-symbols-outlined text-[24px] text-md-primary"
          >
            {isForm ? "edit_document" : "description"}
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <DialogTitle
              className="truncate text-[18px] font-semibold leading-snug text-md-on-surface"
              style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
            >
              {detail?.title ?? `별표 ${args.annexNum}`}
            </DialogTitle>
            <span className="text-[12px] text-md-on-surface-variant">
              {headerSubLabel} · law {args.lawId}
            </span>
          </div>
          {/* 헤더 액션 — 내장 X 버튼(우상단)과 겹치지 않게 mr-9 는 묶음에 준다.
              버튼마다 주면 하나만 보일 때 간격이 어긋난다. */}
          <div className="mr-9 flex shrink-0 items-center gap-2">
          {/* 별표: 보조 버튼만. 서식: 본문 위 prominent CTA로 대체 → 헤더 버튼 X. */}
          {detail?.download_url && !isForm ? (
            <a
              href={detail.download_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[12.5px] font-medium text-md-on-surface transition-colors hover:border-md-on-surface hover:bg-md-surface-container-low"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                download
              </span>
              {downloadLabel}
            </a>
          ) : null}
          {/* 본문을 확인한 바로 그 자리에서 작성으로 넘어간다(2026-08-27).
              종전엔 인용 패널에만 있어서, 모달까지 열어 내용을 확인한 사용자가
              정작 여기서는 작성으로 못 갔다(막다른 길). */}
          {onUseAsForm && args.articleKey && canFill ? (
            <button
              type="button"
              onClick={() => {
                onUseAsForm(args.articleKey!, args.title ?? detail?.title ?? "");
                onClose();
              }}
              title={formActionHint(isForm ? "form" : "annex")}
              className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-md-primary px-4 text-[12.5px] font-semibold text-md-on-primary transition-colors hover:opacity-90"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                edit_document
              </span>
              {formActionLabel(isForm ? "form" : "annex")}
            </button>
          ) : null}
          </div>
          {/* DialogContent 내장 X 버튼이 우상단에 위치 — 수동 close 버튼 X */}
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading && !detail ? (
            <div className="flex items-center justify-center py-12 text-md-on-surface-variant">
              <span
                className="material-symbols-outlined animate-spin text-[24px]"
                aria-hidden
              >
                progress_activity
              </span>
            </div>
          ) : error ? (
            <div className="rounded border border-md-error bg-md-error-container px-3 py-2 text-body-sm text-md-on-error-container">
              {error}
            </div>
          ) : (
            <>
              {/* 서식 — 주 CTA: prominent 다운로드 카드를 본문 최상단에 배치 */}
              {isForm && detail?.download_url ? (
                <a
                  href={detail.download_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mb-5 flex items-center gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-3 text-md-on-surface transition-colors hover:bg-md-surface-container"
                >
                  <span
                    className="material-symbols-outlined text-[26px]"
                    aria-hidden
                  >
                    download
                  </span>
                  <span className="flex flex-col leading-tight">
                    <span className="text-[15px] font-semibold">
                      {downloadLabel}
                    </span>
                    <span className="text-[12px] opacity-80">
                      HWP 양식 — law.go.kr에서 다운로드
                    </span>
                  </span>
                  <span
                    aria-hidden
                    className="material-symbols-outlined ml-auto text-[18px] opacity-70"
                  >
                    north_east
                  </span>
                </a>
              ) : null}

              {notFillable ? (
                <div className="mb-4 flex items-start gap-2 rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-3 text-[13px] leading-relaxed text-md-on-surface-variant">
                  <span className="material-symbols-outlined mt-px text-[18px]" aria-hidden>
                    info
                  </span>
                  <span>
                    기입 항목이 없는 {isForm ? "서식" : "별표"}입니다. 기준·요건을 확인하는 참고용
                    자료라 작성 대상이 아닙니다.
                  </span>
                </div>
              ) : null}
              {/* 2026-09-08 "미리보기가 전부 깨진다 — 원문 링크로": 텍스트 변환본은 표 구조가
                  무너져 신뢰할 수 없다. 원본(HWP·법령정보센터)을 주 동선으로 두고, 텍스트는
                  접힌 보조 자료로만 남긴다. */}
              {!isForm ? (
                <div className="mb-4 flex flex-wrap gap-2">
                  {detail?.download_url ? (
                    <a
                      href={detail.download_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex h-10 items-center gap-2 rounded-button border border-md-outline-variant bg-md-surface px-4 text-[13.5px] font-medium text-md-on-surface hover:bg-md-surface-container-low"
                    >
                      <span className="material-symbols-outlined text-[18px]" aria-hidden>download</span>
                      원본 HWP 열기
                    </a>
                  ) : null}
                  <a
                    href={`https://www.law.go.kr/lsInfoP.do?lsId=${encodeURIComponent(args.lawId)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex h-10 items-center gap-2 rounded-button border border-md-outline-variant px-4 text-[13.5px] font-medium text-md-on-surface hover:bg-md-surface-container-low"
                  >
                    <span className="material-symbols-outlined text-[18px]" aria-hidden>open_in_new</span>
                    법령정보센터에서 보기
                  </a>
                </div>
              ) : (
                <a
                  href={`https://www.law.go.kr/lsInfoP.do?lsId=${encodeURIComponent(args.lawId)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mb-4 inline-flex h-9 items-center gap-1.5 text-[13px] text-md-on-surface-variant underline-offset-2 hover:underline"
                >
                  <span className="material-symbols-outlined text-[16px]" aria-hidden>open_in_new</span>
                  법령정보센터에서 보기
                </a>
              )}

              {/* 문서 뷰어 — 원본 HWP 를 HTML 로 렌더(법령정보센터 뷰어 방식). sandbox 로 스크립트 차단 */}
              {viewHtml === undefined ? (
                <div className="mb-4 flex items-center gap-2 rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-6 text-[13px] text-md-on-surface-variant">
                  <span className="material-symbols-outlined animate-spin text-[18px]" aria-hidden>
                    progress_activity
                  </span>
                  원본 문서를 뷰어로 여는 중…
                </div>
              ) : viewHtml ? (
                <iframe
                  title="문서 뷰어"
                  sandbox=""
                  srcDoc={viewHtml}
                  className="mb-4 h-[72vh] w-full rounded-card border border-md-outline-variant bg-[#f3f4f6]"
                />
              ) : (
                <div className="mb-4 flex items-start gap-2 rounded-card border border-md-outline-variant bg-md-surface-container-low px-4 py-3 text-[13px] leading-relaxed text-md-on-surface-variant">
                  <span className="material-symbols-outlined mt-px text-[18px]" aria-hidden>
                    info
                  </span>
                  <span>
                    {viewReason && /HWPX|HWPML|형식/.test(viewReason)
                      ? "이 파일은 뷰어로 열 수 없는 형식(HWPX 등)입니다. 위 원본 링크로 확인해 주세요."
                      : "지금은 문서 뷰어로 열 수 없습니다. 위 원본 링크로 확인해 주세요."}
                    {viewReason ? (
                      <span className="mt-1 block text-[11.5px] text-md-on-surface-variant/70">
                        사유: {viewReason.split("\n")[0]}
                      </span>
                    ) : null}
                  </span>
                </div>
              )}

            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
