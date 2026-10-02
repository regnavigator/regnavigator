"use client";

/**
 * RelatedFormsCard — 답변이 근거로 든 법령의 **서식**(별지 양식)을 답변 아래에 추천.
 *
 * 배경(2026-09-08 요청 "답변에 맞는 서식을 찾아 줄 수 있음?"): 서식은 빈 양식이라
 * 벡터 색인에서 제외돼(ETL 정책) 답변 인용에 거의 안 잡힌다. 대신 법령별 별표·서식
 * 목록(`GET /annex/list?lawId=`)이 있으므로, 인용된 법령 id 로 목록을 받아 서식만
 * 거르고 질문·답변 소제목 낱말과 제목 겹침으로 순위를 매긴다. 백엔드 변경 없음.
 *
 * - 답변 본문은 건드리지 않는다(References 채널 분리 원칙). 카드는 출처 목록 아래.
 * - [이 서식으로 작성] = 기존 서식 즉시 작성 모달(openFormDocument) 그대로.
 * - 법령당 목록은 모듈 캐시 — 같은 법령이 여러 턴에 나와도 한 번만 조회.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { listAnnex, parseAttachmentKey, type AnnexListItem } from "@/lib/client/annex";
import { getAnnex } from "@/lib/client/annex";
import { AnnexModal } from "@/components/chat/AnnexModal";
import type { Citation } from "@/lib/store/types";
import { articleKeyFromCitation } from "@/lib/client/article";
import { formDocKindOf } from "@/lib/formEntry";

type FormHit = {
  key: string;
  title: string;
  lawId: string;
  lawTitle: string;
  annexNum: string | null;
  score: number;
};


const LAW_CATS = new Set(["법령", "행정규칙", "법령별표서식", "행정규칙별표서식"]);
const MAX_LAWS = 5;
const SHOW = 4;
const cache = new Map<string, Promise<AnnexListItem[]>>();

function fetchForms(lawId: string): Promise<AnnexListItem[]> {
  let p = cache.get(lawId);
  if (!p) {
    p = listAnnex(lawId)
      .then((r) =>
        (r.items ?? []).filter(
          (it) =>
            (it.type ?? "").includes("서식") ||
            parseAttachmentKey(it.attachment_key).type === "서식" ||
            /서식|별지/.test(it.title ?? ""),
        ),
      )
      .catch(() => [] as AnnexListItem[]);
    cache.set(lawId, p);
  }
  return p;
}

const STOP = new Set(["절차", "방법", "관련", "기준", "대해", "대한", "경우", "알려줘", "정리", "함께", "의료기기", "제출", "서식", "별표", "서류", "필요", "단계별", "단계"]);

function tokens(text: string): string[] {
  const src = text.replace(/[^\p{L}\p{N}\s]/gu, " ");
  return [...new Set(src.split(/\s+/).map((t) => t.trim()).filter((t) => t.length >= 2 && !STOP.has(t)))];
}

/** 순위 재료(2026-09-08 실측 조정): 질문·소제목 토큰(가중 2) + 본문 전체 토큰(가중 1) + 본문. */
function keywords(question: string, answer: string): { strong: string[]; weak: string[]; body: string } {
  const heads = answer
    .split("\n")
    .filter((l) => /^#{1,4}\s|^\*\*.+\*\*$/.test(l.trim()))
    .join(" ");
  const strong = tokens(`${question} ${heads}`);
  const weak = tokens(answer).filter((t) => !strong.includes(t));
  return { strong, weak, body: answer.replace(/\s+/g, "") };
}

function score(title: string, kws: { strong: string[]; weak: string[]; body: string }): number {
  let s = 0;
  const core = title.replace(/\(.*?\)/g, "").replace(/\s+/g, "");
  // 답변 본문이 서식 제목을 그대로 언급하면 최우선("별지 제3호 서식: 의료기기 제조(수입) 허가신청서")
  if (core.length >= 6 && kws.body.includes(core)) s += 8;
  for (const k of kws.strong) if (title.includes(k)) s += k.length >= 3 ? 2 : 1;
  for (const k of kws.weak) if (title.includes(k)) s += 0.5;
  // 신청·신고서는 사용자가 채우는 서식 → 가산. 허가증·신고증·등록증은 관청이 발급하는 문서 → 감점.
  if (/신청서|신고서|계획서|보고서/.test(title)) s += 0.5;
  if (/허가증|신고증|등록증|지정서|증명서|확인서$/.test(title)) s -= 2;
  // "지정·변경" 류 기관 지정 서식은 일반 인허가 질문에선 뒤로
  if (/심사기관|시험기관|지정기관/.test(title)) s -= 1;
  return s;
}

const ANNEX_CATS = new Set(["법령별표서식", "행정규칙별표서식", "자치법규별표서식"]);

/**
 * 이번 턴이 **이미 수집한 인용** 중 서식을 추린다 (2026-10-01).
 *
 * 원래 경로는 `/annex/list?lawId=` 지만 그건 별표 DB(Neo4j/PG)가 붙어 있어야
 * 하고, 미연결이면 `count: 0` 만 돌아온다 — 그래서 카드가 통째로 안 보였다
 * (실사용 신고: "검색은 됐는데 서식 작성이 안 열려").
 *
 * 그런데 검색 결과에는 서식 청크가 이미 들어와 있다. 모델이 본문에서 그 인용을
 * 안 썼을 뿐이다. DB 없이도 여기서 바로 꺼낼 수 있다.
 */
function formsFromCitations(citations: Citation[], kws: ReturnType<typeof keywords>): FormHit[] {
  const out: FormHit[] = [];
  const seen = new Set<string>();
  for (const c of citations) {
    if (!c.doc_category || !ANNEX_CATS.has(c.doc_category)) continue;
    if (formDocKindOf(c) !== "form") continue;      // 기준표(별표)는 기입 대상이 아니다
    const key = articleKeyFromCitation(c);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const full = (c.title ?? "").trim();
    // "공중위생관리법 시행규칙 별표: 영업신고서" → 법령명 / 서식명 분리
    const m = full.match(/^(.*?)\s*(?:별표|별지)\s*:\s*(.+)$/);
    const lawTitle = (m?.[1] ?? full).trim();
    const title = (m?.[2] ?? full).trim();
    out.push({
      key,
      title,
      lawId: c.doc_id ?? "",
      lawTitle,
      annexNum: parseAttachmentKey(key).annexNum,
      score: score(title, kws),
    });
  }
  return out;
}

export function RelatedFormsCard({
  question,
  answer,
  citations,
  poolCitations,
  onUseAsForm,
}: {
  question: string;
  answer: string;
  /** 답변 본문이 실제로 인용한 것 — 법령 id 추출용 */
  citations: Citation[];
  /**
   * 이 턴이 **수집한 전체** 인용(step.citations, 2026-10-01).
   *
   * `citations` 는 본문에 `[n]` 으로 쓰인 것만이다(References 신뢰성 원칙).
   * 그런데 서식은 모델이 본문에서 거의 인용하지 않는다 — 조문을 인용하고
   * "별지 제1호서식입니다" 라고 쓴다. 그래서 추천 카드는 수집분까지 본다.
   * 이건 References 가 아니라 **제안**이므로 그 원칙과 충돌하지 않는다.
   */
  poolCitations?: Citation[];
  onUseAsForm: (articleKey: string, title: string) => void;
}) {
  const pool = poolCitations?.length ? poolCitations : citations;
  const laws = useMemo(() => {
    const out: { id: string; title: string }[] = [];
    const seen = new Set<string>();
    for (const c of citations) {
      if (c.source_kind !== "doc" || !c.doc_id) continue;
      if (c.doc_category && !LAW_CATS.has(c.doc_category)) continue;
      if (seen.has(c.doc_id)) continue;
      seen.add(c.doc_id);
      // 인용 제목은 "의료기기법 제25조" 꼴 — 법령명만 남긴다
      // 인용 제목 "의료기기법 시행규칙 별표: …" / "… 제25조" → 법령명만
      out.push({ id: c.doc_id, title: (c.title ?? "").replace(/\s*(제?\d+조|별표|별지|\[).*$/, "").trim() || c.doc_id });
      if (out.length >= MAX_LAWS) break;
    }
    return out;
  }, [citations]);

  const [hits, setHits] = useState<FormHit[] | null>(null);
  // 목록 제약(2026-09-08 "더 보기가 전부 아래로 나열"): 4건 → [10건 더 보기]로 단계 확장,
  // 8건 넘게 펼치면 380px 스크롤 박스. 80건짜리 법령은 제목 필터로 좁힌다.
  const [shownCount, setShownCount] = useState(SHOW);
  const [filter, setFilter] = useState("");
  // [더 보기] 직후 새로 붙은 첫 행 인덱스(2026-09-21 "스크롤도 안 바뀌고 추가됐는지 모르겠다").
  // 그 행부터 슬라이드인 + 잠깐 강조, 목록은 그 행이 보이게 부드럽게 스크롤한다.
  const [revealFrom, setRevealFrom] = useState<number | null>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const showMore = (from: number) => {
    setRevealFrom(from);
    setShownCount((n) => n + 10);
  };
  // [원본 보기](2026-09-08 "미리보기가 깨지니 원문 링크로"): 텍스트 변환본 대신 원본을 새 탭에.
  // 팝업 차단을 피하려 클릭 동기 시점에 탭을 열고, 상세 조회 뒤 주소를 넣는다.
  const [preview, setPreview] = useState<FormHit | null>(null);
  const openOriginal = (h: FormHit) => {
    const win = window.open("", "_blank");
    const fallback = `https://www.law.go.kr/lsInfoP.do?lsId=${encodeURIComponent(h.lawId)}`;
    void (h.annexNum ? getAnnex(h.lawId, h.annexNum, "서식") : Promise.reject(new Error("no num")))
      .then((d) => {
        const url = d.download_url || fallback;
        if (win) win.location.href = url;
        else window.open(url, "_blank");
      })
      .catch(() => {
        if (win) win.location.href = fallback;
        else window.open(fallback, "_blank");
      });
  };

  useEffect(() => {
    const kws = keywords(question, answer);
    if (!laws.length) {
      // 법령 id 를 못 뽑아도 인용에 서식이 있으면 보여 준다.
      setHits(formsFromCitations(pool, kws).sort((a, b) => b.score - a.score));
      return;
    }
    let alive = true;
    void Promise.all(laws.map((l) => fetchForms(l.id).then((items) => ({ l, items })))).then(
      (groups) => {
        if (!alive) return;
        const seen = new Set<string>();
        const all: FormHit[] = [];
        for (const { l, items } of groups) {
          for (const it of items) {
            if (!it.attachment_key || seen.has(it.attachment_key)) continue;
            seen.add(it.attachment_key);
            all.push({
              key: it.attachment_key,
              title: it.title || it.attachment_key,
              lawId: l.id,
              lawTitle: l.title,
              annexNum: it.annex_num ?? parseAttachmentKey(it.attachment_key).annexNum,
              score: score(it.title || "", kws),
            });
          }
        }
        // 답변이 **실제로 인용한 법령**의 서식을 앞세운다(2026-10-01). 토큰 겹침만
        // 보면 `지방세기본법 시행규칙: 공중위생영업 신고에 관한 자료` 가
        // `공중위생관리법 시행규칙: 영업신고서` 를 제치는 일이 생긴다(실측).
        const citedLawIds = new Set(citations.map((c) => c.doc_id).filter(Boolean));
        for (const h of all) if (h.lawId && citedLawIds.has(h.lawId)) h.score += 3;
        // 인용에서 뽑은 서식을 합친다 — 같은 key 는 목록 쪽(별표 메타가 풍부)을 남긴다.
        for (const h of formsFromCitations(pool, kws)) {
          if (seen.has(h.key)) continue;
          seen.add(h.key);
          if (h.lawId && citedLawIds.has(h.lawId)) h.score += 3;
          all.push(h);
        }
        all.sort((a, b) => b.score - a.score || a.title.localeCompare(b.title, "ko"));
        setHits(all);
      },
    );
    return () => {
      alive = false;
    };
  }, [laws, pool, citations, question, answer]);

  useEffect(() => {
    if (revealFrom === null) return;
    const ul = listRef.current;
    const row = ul?.querySelector<HTMLElement>(`[data-row="${revealFrom}"]`);
    if (!ul || !row) return;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const behavior: ScrollBehavior = smooth ? "smooth" : "auto";
    if (ul.scrollHeight > ul.clientHeight) {
      // 스크롤 박스 안(ul 이 relative 라 offsetTop 은 ul 기준) — 새 첫 행을 박스 위쪽으로(바로 앞 행 절반이 보이게 해 이어짐을 알린다)
      ul.scrollTo({ top: Math.max(0, row.offsetTop - 24), behavior });
      // 박스 자체가 화면 아래로 잘려 있으면 대화 스크롤도 박스가 보이게
      ul.scrollIntoView({ block: "nearest", behavior });
    } else {
      row.scrollIntoView({ block: "nearest", behavior });
    }
  }, [revealFrom, shownCount]);

  if (!hits || hits.length === 0) return null;
  const q = filter.trim();
  const filtered = q ? hits.filter((h) => h.title.includes(q)) : hits;
  const shown = filtered.slice(0, shownCount);
  const scrollBox = shownCount > 8;

  return (
    <section aria-label="관련 서식" className="mt-3 border-y border-md-outline-variant">
      <div className="flex items-center gap-2 px-1 py-2">
        <span className="material-symbols-outlined text-[14px] text-md-on-surface-variant" aria-hidden>
          edit_document
        </span>
        <span className="text-label-caps text-md-on-surface-variant">
          관련 서식 {hits.length}건
        </span>
        <span className="text-[11px] text-md-on-surface-variant/70">
          답변이 근거로 든 법령의 서식 — 바로 작성할 수 있습니다
        </span>
      </div>
      {hits.length > 8 ? (
        <div className="flex items-center gap-2 border-t border-md-outline-variant px-3 py-2">
          <span className="material-symbols-outlined text-[16px] text-md-on-surface-variant" aria-hidden>
            search
          </span>
          <input
            type="search"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setShownCount(SHOW);
              setRevealFrom(null);
            }}
            placeholder={`서식 제목으로 찾기 (${hits.length}건)`}
            aria-label="관련 서식 제목 검색"
            className="h-8 min-w-0 flex-1 bg-transparent text-[13px] text-md-on-surface outline-none placeholder:text-md-on-surface-variant/60"
          />
        </div>
      ) : null}
      <ul
        ref={listRef}
        className={
          "relative divide-y divide-md-outline-variant border-t border-md-outline-variant" +
          (scrollBox ? " max-h-[380px] overflow-y-auto" : "")
        }
      >
        {shown.map((h, i) => (
          <li
            key={h.key}
            data-row={i}
            className={
              "flex items-center gap-3 px-3 py-2.5" +
              (revealFrom !== null && i >= revealFrom ? " form-row-in" : "")
            }
            style={
              revealFrom !== null && i >= revealFrom
                ? { animationDelay: `${Math.min(i - revealFrom, 9) * 35}ms, 0ms` }
                : undefined
            }
          >
            <button
              type="button"
              onClick={() => (h.annexNum ? setPreview(h) : openOriginal(h))}
              title="문서 뷰어로 보기"
              className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
            >
              <span className="truncate text-[13.5px] font-medium text-md-on-surface underline-offset-2 hover:underline">
                {h.title}
              </span>
              <span className="truncate text-[12px] text-md-on-surface-variant">{h.lawTitle}</span>
            </button>
            <button
              type="button"
              onClick={() => setPreview(h)}
              disabled={!h.annexNum}
              className="inline-flex h-8 shrink-0 items-center gap-1 rounded-button px-2.5 text-[12.5px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low hover:text-md-on-surface disabled:opacity-40"
            >
              <span className="material-symbols-outlined text-[15px]" aria-hidden>
                visibility
              </span>
              미리보기
            </button>
            <button
              type="button"
              onClick={() => openOriginal(h)}
              title="원본 HWP 새 탭"
              className="inline-flex h-8 shrink-0 items-center gap-1 rounded-button px-2.5 text-[12.5px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low hover:text-md-on-surface"
            >
              <span className="material-symbols-outlined text-[15px]" aria-hidden>
                open_in_new
              </span>
              원본
            </button>
            <button
              type="button"
              onClick={() => onUseAsForm(h.key, h.title)}
              className="inline-flex h-8 shrink-0 items-center gap-1 rounded-button border border-md-outline-variant px-3 text-[12.5px] font-medium text-md-on-surface transition-colors hover:bg-md-surface-container-low"
            >
              <span className="material-symbols-outlined text-[15px]" aria-hidden>
                edit_square
              </span>
              이 서식으로 작성
            </button>
          </li>
        ))}
      </ul>
      {filtered.length === 0 ? (
        <p className="px-3 py-3 text-[12.5px] text-md-on-surface-variant">일치하는 서식이 없습니다.</p>
      ) : null}
      {filtered.length > SHOW ? (
        <div className="flex items-center justify-between px-3 py-2 text-[12px] text-md-on-surface-variant">
          <span>
            {Math.min(shownCount, filtered.length)} / {filtered.length}건
          </span>
          <span className="flex gap-3">
            {shownCount < filtered.length ? (
              <button
                type="button"
                onClick={() => showMore(shown.length)}
                className="inline-flex items-center gap-0.5 font-medium text-md-primary hover:underline"
              >
                {Math.min(10, filtered.length - shown.length)}건 더 보기
                <span className="material-symbols-outlined text-[15px]" aria-hidden>
                  expand_more
                </span>
              </button>
            ) : null}
            {shownCount > SHOW ? (
              <button
                type="button"
                onClick={() => {
                  setShownCount(SHOW);
                  setRevealFrom(null);
                  listRef.current?.scrollTo({ top: 0 });
                }}
                className="hover:text-md-on-surface"
              >
                접기
              </button>
            ) : null}
          </span>
        </div>
      ) : null}
      <AnnexModal
        args={
          preview && preview.annexNum
            ? { lawId: preview.lawId, annexNum: preview.annexNum, articleKey: preview.key, title: preview.title, isForm: true, type: "서식" }
            : null
        }
        onClose={() => setPreview(null)}
        onUseAsForm={(k, t) => {
          setPreview(null);
          onUseAsForm(k, t);
        }}
      />
    </section>
  );
}
