"use client";

/**
 * ArticleModal — 법령 원문 인-앱 모달.
 *
 * - GET /article?key={article_key} → markdown 본문 + 메타 + external_url
 * - 사용자가 citation chip에서 "본문 보기" 클릭 시 트리거
 * - 우상단 "law.go.kr에서 보기" 버튼 → external_url 새 탭
 */

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { MarkdownContent } from "@/components/chat/MarkdownContent";
import { getArticle, type Article } from "@/lib/client/article";
import { stripArticleNumPadding } from "@/lib/parse/citation";

const TARGET_LABEL: Record<string, string> = {
  law: "법령",
  admrul: "행정규칙",
  ordin: "자치법규",
  prec: "판례",
  expc: "법령해석례",
  detc: "헌재결정례",
  trty: "조약",
};

type Props = {
  /** 활성 시 article_key 필수. null이면 모달 닫힘 */
  articleKey: string | null;
  /** backend `/article` lookup 실패 시 fallback으로 쓸 외부 deep-link (law.go.kr 등) */
  externalUrlFallback?: string | null;
  onClose: () => void;
};

export function ArticleModal({ articleKey, externalUrlFallback, onClose }: Props) {
  const [article, setArticle] = useState<Article | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!articleKey) {
      setArticle(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    console.debug("[ArticleModal] fetching", { key: articleKey });
    void getArticle(articleKey)
      .then((d) => {
        console.debug("[ArticleModal] success", { key: articleKey, target: d.target_type });
        setArticle(d);
      })
      .catch((err) => {
        const status = (err as { status?: number }).status;
        const body = (err as { body?: string }).body;
        console.warn("[ArticleModal] fetch failed", { key: articleKey, status, body, err });
        const detail = status
          ? `(HTTP ${status}) ${body?.slice(0, 200) ?? ""}`
          : (err as Error).message;
        setError(`원문을 불러오지 못했습니다. ${detail}`);
      })
      .finally(() => setLoading(false));
  }, [articleKey]);

  if (!articleKey) return null;

  const title = article
    ? stripArticleNumPadding(
        `${article.law_title}${article.article_num ? ` ${article.article_num}` : ""}`,
      )
    : "원문 로딩 중...";
  const targetLabel = article?.target_type
    ? (TARGET_LABEL[article.target_type] ?? article.target_type)
    : "";

  return (
    <Dialog open={!!articleKey} onOpenChange={(o) => (!o ? onClose() : null)}>
      <DialogContent className="flex h-[80vh] max-w-[820px] flex-col gap-0 border border-md-outline-variant bg-md-surface p-0 text-md-on-surface shadow-xl">
        <DialogHeader className="flex shrink-0 flex-row items-center gap-3 space-y-0 border-b border-md-outline-variant px-6 py-5">
          <span
            aria-hidden
            className="material-symbols-outlined text-[24px] text-md-primary"
          >
            menu_book
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <DialogTitle
              className="truncate text-[18px] font-semibold leading-snug text-md-on-surface"
              style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
            >
              {title}
            </DialogTitle>
            <span className="text-[12px] text-md-on-surface-variant">
              {targetLabel}
              {article?.department ? ` · ${article.department}` : ""}
              {article?.enforce_date ? ` · 시행 ${article.enforce_date}` : ""}
            </span>
          </div>
          {article?.external_url ? (
            <a
              href={article.external_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mr-9 inline-flex h-9 items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[12.5px] font-medium text-md-on-surface transition-colors hover:border-md-on-surface hover:bg-md-surface-container-low"
            >
              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                gavel
              </span>
              law.go.kr에서 보기
            </a>
          ) : null}
          {/* DialogContent 내장 X 버튼이 우상단에 위치 — 수동 close 버튼 X */}
        </DialogHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading && !article ? (
            <div className="flex items-center justify-center py-12 text-md-on-surface-variant">
              <span
                className="material-symbols-outlined animate-spin text-[24px]"
                aria-hidden
              >
                progress_activity
              </span>
            </div>
          ) : error ? (
            <div className="flex flex-col gap-3">
              <div className="rounded border border-md-error bg-md-error-container px-3 py-2 text-body-sm text-md-on-error-container">
                {error}
              </div>
              {externalUrlFallback ? (
                <a
                  href={externalUrlFallback}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-body-sm text-md-secondary hover:underline"
                >
                  <span className="material-symbols-outlined text-[16px]" aria-hidden>
                    gavel
                  </span>
                  대신 법령정보센터에서 보기
                </a>
              ) : null}
            </div>
          ) : article?.full_text && article.full_text.trim().length > 0 ? (
            <MarkdownContent content={article.full_text} />
          ) : (
            <p className="text-body-sm italic text-md-on-surface-variant">
              본문 데이터가 없습니다.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
