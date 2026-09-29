/**
 * Citation — back §2.1 (canonical, snake_case).
 * RightPanel `?citation=<id>`로 lookup. 13 분야 enum은 `lawLink`가 deep-link 도출에 사용.
 */

export type Citation = {
  /** 백엔드 발행 unique id */
  id: string;
  /** 답변 본문 [n] 매핑 (turn 안 1부터, unique) */
  number: number;
  source_kind: "web" | "doc";
  title: string;
  publisher?: string;
  date?: string;
  /** source_kind === "web" 필수 */
  url?: string;
  /** source_kind === "doc" */
  doc_id?: string;
  /** "제45조" */
  article?: string;
  page?: number;
  /** 본문 인용 (markdown 가능) */
  snippet?: string;
  /** 미지정 = "active" */
  status?: "active" | "revoked" | "amended_pending";
  /** 시행 상태 원본 라벨(back 2026-08-16) — status 보다 정밀.
   *  "미시행" = 공포됐으나 시행일 미도래(= 아직 효력 없음, 폐지와 다름).
   *  배지 문구를 이 값으로 분기한다. */
  effective_status?: "시행중" | "미시행" | "구법" | "확인필요";
  /** false = 시행일 미도래. date(시행일)와 함께 "N월 시행 예정" 표기에 쓴다. */
  enforced?: boolean;
  /** 버전 축(back 2026-08-16, ETL RFC R3). "pending" = 같은 결과에 현행본이
   *  함께 있는 **개정 예정본** — 단독 미시행("아직 효력 없음")과 의미가 다르다. */
  version_status?: "current" | "pending";
  /** pending 인용이 개정하는 현행 조문의 article_key. */
  supersedes_article_key?: string;
  /** R1 — citation_verifier 통과 여부. RAG=true 기본, web=화이트리스트 매칭.
   *  보고서(report grounding)에선 claim↔원문 문장 매칭 검증 결과 — false면
   *  "근거 확인 필요" 표시. */
  verified?: boolean;
  /** 보고서 grounding(`_ground_citations`)이 부착하는 *검증된 원문 span*.
   *  backend가 본문(text)에서 substring 검증 통과한 문장. FE는 verified=true일 때
   *  본문에서 이 문장을 하이라이트(NotebookLM-lite) + 검증 근거 박스로 노출.
   *  일반 chat citation엔 없음(보고서 전용). */
  supporting_quote?: string;
  /** R2 — backend가 명시한 13 분야. lawLink가 heuristic 대신 이걸 우선 신뢰 */
  doc_category?:
    | "법령"
    | "영문법령"
    | "행정규칙"
    | "자치법규"
    | "학칙공단"
    | "조약"
    | "판례"
    | "헌재결정례"
    | "법령해석례"
    | "행정심판례"
    | "법령별표서식"
    | "행정규칙별표서식"
    | "자치법규별표서식"
    | "가이드라인";
  /** R4 — 판례 인용 시 발행 법원 */
  court?: string;
  /** R4 — 심급 (1=1심, 2=2심, 3=3심/최종) */
  instance?: 1 | 2 | 3;
  /** 별표/서식 HWP·PDF 다운로드 (law.go.kr). source_kind=doc + doc_category가 *별표서식*일 때만 박힘 */
  download_url?: string;
};
