/**
 * Citation → 법령정보센터(law.go.kr) deep-link 도출.
 *
 * 권위 원천: `LAW_GO_KR_LINKS.md` v0.1 (13 분야 패턴).
 *
 * 우선순위:
 *  1) `citation.url` 있으면 그대로 사용 (백엔드 deep-link).
 *  2) `source_kind === 'doc'` + 분야 검출 성공 → `/<분야>/<제목>[/<article>]` path-based URL.
 *  3) `source_kind === 'doc'` + 한국 법령 패턴이지만 분야 미검출 → 검색 fallback (`lsSc.do?query=`).
 *  4) 그 외 null.
 *
 * 분야 검출은 heuristic. 백엔드가 `Citation` 스키마에 `doc_category` 필드를 추가하면
 * 그 값을 우선 신뢰하도록 본 모듈을 갱신하면 됨 (현재는 backend에 그 필드 없음).
 */

import type { Citation } from "@/lib/store/types";
import { normalizeMetaField } from "@/lib/parse/citation";

/** 13 분야 (LAW_GO_KR_LINKS §0). */
/** law.go.kr URL 로 만들 수 있는 분야 — **런타임 목록이 단일 진실원**.
 *
 * 예전엔 타입만 있었고 backend 값을 `as LawCategory` 로 캐스트했다. 캐스트는
 * 컴파일 타임에만 존재해서, backend 가 새 종별(`가이드라인`)을 보내기 시작하자
 * 그대로 통과해 존재하지 않는 law.go.kr 링크가 만들어졌다(2026-08-04).
 * 목록을 값으로 두고 `isLawCategory` 로 **런타임에** 거른다.
 */
const LAW_CATEGORIES = [
  "법령",
  "영문법령",
  "행정규칙",
  "자치법규",
  "학칙공단",
  "조약",
  "판례",
  "헌재결정례",
  "법령해석례",
  "행정심판례",
  "법령별표서식",
  "행정규칙별표서식",
  "자치법규별표서식",
] as const;

type LawCategory = (typeof LAW_CATEGORIES)[number];

/** 문자열이 law.go.kr 분야인가 — backend 가 보낸 값의 런타임 검증. */
function isLawCategory(v: string | undefined): v is LawCategory {
  return !!v && (LAW_CATEGORIES as readonly string[]).includes(v);
}

/** 학칙공단 패턴 — 학칙·공단·협회·협약서 등 자치 규약 */
const ACADEMIC_PATTERN = /(학칙|공단|협회|협약서|규약)/;

const BASE = "https://www.law.go.kr";

// 정부 부처 — lexdiff 참조해 의료/규제 도메인 외에도 폭 확장
// (조약·국제 협정·해외 비교 등에서 만날 수 있는 발행 기관 포함)
const GOV_PUBLISHERS = [
  "보건복지부",
  "식약처",
  "식품의약품안전처",
  "국무조정실",
  "국무총리실",
  "기획재정부",
  "행정안전부",
  "산업통상자원부",
  "과학기술정보통신부",
  "교육부",
  "법무부",
  "외교부",
  "통일부",
  "국방부",
  "환경부",
  "고용노동부",
  "여성가족부",
  "국토교통부",
  "농림축산식품부",
  "해양수산부",
  "중소벤처기업부",
  "문화체육관광부",
  "관세청",
  "국세청",
  "통계청",
  "검찰청",
  "경찰청",
  "특허청",
  "소방청",
  "방위사업청",
];

// 지자체 — 광역(특별시·광역시·특별자치시도) + 기초(시·군·구) 단계 모두
// 끝자(suffix) 매칭이 1순위, 시도명(prefix)이 2순위
const LOCAL_GOV_PATTERN =
  /(특별시|광역시|특별자치시|특별자치도|시|군|구|도)$|^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)/;

function isGovPublisher(publisher?: string): boolean {
  if (!publisher) return false;
  return GOV_PUBLISHERS.some((g) => publisher.includes(g));
}

function isLocalGov(publisher?: string): boolean {
  if (!publisher) return false;
  return LOCAL_GOV_PATTERN.test(publisher);
}

/**
 * 분야 검출 — `LAW_GO_KR_LINKS §15` heuristic. 더 구체적인 패턴이 먼저.
 * 결과 미검출이면 null → 호출자가 검색 fallback 사용.
 */
function detectCategory(citation: Citation): LawCategory | null {
  const title = normalizeMetaField(citation.title);
  const publisher = normalizeMetaField(citation.publisher);

  // 별표·서식 (특정 단서가 title에 있을 때만 — 우리 도메인에선 거의 article 필드에 들어옴)
  if (/(별표|서식)\s*\d/.test(title)) {
    if (/(고시|예규|훈령|규정|지침)/.test(title)) return "행정규칙별표서식";
    if (/(조례|규칙)/.test(title) && isLocalGov(publisher)) return "자치법규별표서식";
    return "법령별표서식";
  }

  // 판례·결정례·심판례·해석례 — 대법원·헌법재판소 등
  if (/헌법재판소/.test(publisher) || /(위헌소원|위헌제청|헌마|헌바|헌가)/.test(title))
    return "헌재결정례";
  if (/(법령해석|해석례)/.test(title)) return "법령해석례";
  if (/(행정심판|심판청구)/.test(title)) return "행정심판례";
  if (/대법원/.test(publisher) || /(판결|판례)/.test(title)) return "판례";

  // 조약
  if (/(조약|협정)/.test(title)) return "조약";

  // 자치법규 — 조례·규칙 + 지자체 publisher
  if (/(조례|규칙)/.test(title) && isLocalGov(publisher)) return "자치법규";

  // 학칙공단 — 학칙·협약서·규약 등
  if (ACADEMIC_PATTERN.test(title)) return "학칙공단";

  // 행정규칙 — 고시·예규·훈령·규정·지침
  if (/(고시|예규|훈령|규정|지침)/.test(title)) return "행정규칙";

  // 법령 — 법·시행령·시행규칙·법률
  if (/(법률|시행령|시행규칙|법)$/.test(title.trim()) || /(시행령|시행규칙)/.test(title))
    return "법령";

  // gov publisher fallback — 정부 부처 발행이면 행정규칙 가능성 높음
  if (isGovPublisher(publisher)) return "행정규칙";

  return null;
}

/**
 * title에서 article·부가 annotation·별표 표기를 떼어내 *순수 법령명* 반환.
 *
 * 변환 예:
 *   "의료기기법 시행규칙 제45조" + article="제45조" → "의료기기법 시행규칙"
 *   "의료기기법 제25조 (광고의 사전심의)" + article="제25조" → "의료기기법"
 *   "의료기기 광고 자율심의 통합기준 (2026년 1월 개정)" → "의료기기 광고 자율심의 통합기준"
 *   "의료기기법 시행규칙 별표 7" + article="별표 7" → "의료기기법 시행규칙"
 */
function nameOnly(title: string, article?: string): string {
  let name = title;
  if (article && name.includes(article)) {
    name = name.replace(article, "");
  }
  // 끝 또는 중간의 (...)괄호 부가설명 제거. 한 단어 이상의 annotation일 때만.
  // 예: "(광고의 사전심의)", "(2026년 1월 개정)", "(법률 제16121호)"
  name = name.replace(/\s*\([^)]+\)\s*/g, " ");
  // 별표/서식 표기 잔여 제거 — "별표 7", "서식 12", 그리고 *번호 없는 단일 별표*
  // ("…규정 별표")까지. 숫자부를 옵셔널로 둬야 번호 없는 별표도 부모 법령명만 남아
  // isValidLawName 통과 → 올바른 행정규칙/법령 deep-link 생성.
  name = name.replace(/\s*(?:별표|서식)(?:\s*제?\s*\d+(?:의\d+)?)?\s*/g, " ");
  return name.replace(/\s+/g, " ").trim();
}

/**
 * "정제된 이름"이 *법령 이름 형태*인지 검증. 한국 법령은 거의 항상 다음 접미사로 끝남:
 *   법·률·령·규칙·조례·규정·지침·예규·고시·훈령·기준·협약·학칙·규약·공단·헌법
 *
 * backend가 title에 *조항 제목만* 박는 케이스(예: title="제조허가의 절차", article="제5조")
 * 에서 cleanedName이 "제조허가의 절차"가 되어 `/법령/제조허가의 절차/제5조` 같은
 * 잘못된 deep link이 만들어지는 것을 차단.
 */
function isValidLawName(name: string): boolean {
  if (!name || name.trim().length < 2) return false;
  return /(법|률|령|규칙|조례|규정|지침|예규|고시|훈령|기준|협약|학칙|규약|공단|헌법)$/.test(
    name.trim(),
  );
}

/**
 * `/<category>/<encoded name>[/<encoded article>]` path 구성.
 * 별표서식 분야는 `(<args>)` 패턴이라 별도 helper.
 */
function buildPath(category: LawCategory, name: string, article?: string): string {
  const segments = [category, encodeURIComponent(name)];
  // 조 단위 deep-link 지원: 법령·영문법령에 한해 article 추가 (가이드 §1-3, §2-2)
  if (article && (category === "법령" || category === "영문법령")) {
    segments.push(encodeURIComponent(article));
  }
  return `/${segments.join("/")}`;
}

/**
 * 법령 별표서식 path — `/법령별표서식/(법령명,별표X)`.
 * 가이드 §11. comma는 *literal*로 두고 양옆 segment만 percent-encode.
 */
function buildLawSchedulePath(parentName: string, schedule: string): string {
  return `/법령별표서식/(${encodeURIComponent(parentName)},${encodeURIComponent(schedule)})`;
}

/**
 * 행정규칙 별표서식 path — `/행정규칙별표서식/(행정규칙명,발행번호,별표X)`.
 * 발행번호 미상이면 행정규칙 본문 path로 fallback (별표 deep-link 안 됨).
 * 가이드 §12.
 */
function buildAdmrulSchedulePath(
  parentName: string,
  schedule: string,
  decreeNo?: string,
): string {
  if (!decreeNo) return buildPath("행정규칙", parentName);
  return `/행정규칙별표서식/(${encodeURIComponent(parentName)},${encodeURIComponent(decreeNo)},${encodeURIComponent(schedule)})`;
}

/**
 * 자치법규 별표서식 path — `/자치법규별표서식/(자치법규명,공포번호,별표X)`.
 * 공포번호 미상이면 자치법규 본문 path로 fallback.
 * 가이드 §13.
 */
function buildOrdinSchedulePath(
  parentName: string,
  schedule: string,
  decreeNo?: string,
): string {
  if (!decreeNo) return buildPath("자치법규", parentName);
  return `/자치법규별표서식/(${encodeURIComponent(parentName)},${encodeURIComponent(decreeNo)},${encodeURIComponent(schedule)})`;
}

/**
 * 검색 페이지 fallback URL — 분야 검출 실패 시.
 */
function searchFallbackUrl(query: string): string {
  return `${BASE}/lsSc.do?query=${encodeURIComponent(query)}`;
}

/**
 * law.go.kr URL 끝의 *번호 없는 별표/서식* 세그먼트 제거 → 부모 문서 URL.
 *
 * 예: `.../행정규칙/의료기기 제조 및 품질관리 기준/별표` (404)
 *   → `.../행정규칙/의료기기 제조 및 품질관리 기준`
 *
 * 번호 없는 단일 별표는 law.go.kr에 deep-link가 없어 마지막 "별표"/"서식"
 * 세그먼트가 그대로 붙으면 404. 번호 있는 별표 deep-link
 * (`/법령별표서식/(법령명,별표7)`)는 끝 세그먼트가 "별표"가 아니라 영향 X.
 * citation.url(backend) · article.external_url(backend) · heuristic 경로 모두에
 * 적용하기 위해 export.
 */
export function stripBareAnnexSegment(url: string): string {
  if (!url || !url.includes("law.go.kr")) return url;
  const segs = url.split("/");
  const last = segs[segs.length - 1] ?? "";
  let decoded = last;
  try {
    decoded = decodeURIComponent(last);
  } catch {
    // 인코딩 깨진 입력 — raw 비교로 진행
  }
  if (/^\s*(?:별표|서식)\s*$/.test(decoded)) {
    segs.pop();
    return segs.join("/");
  }
  return url;
}

/**
 * 외부 링크 도출. 우선순위:
 *  1) `citation.url` 그대로 (백엔드가 결정한 deep-link)
 *  2) `citation.doc_category` 명시 — backend가 박은 분야 신뢰 (R2)
 *  3) heuristic 검출 fallback
 *  4) 검색 fallback
 *  5) null
 */
export function deriveExternalUrl(citation: Citation): string | null {
  // citation.url 우선 — 단 *legacy lsInfoP.do?lsiSeq=...* 형식은 거부.
  // 사연: openlaw-etl의 law_id와 law.go.kr의 lsiSeq는 다른 ID 체계 (같은 숫자라도
  // 다른 법령 가리킴, 예: 009514 → openlaw 의료기기법 vs law.go.kr 폐지 국토이용관리법).
  // backend가 path 형식(`/법령/{명}/{조문}`)으로 전환됐지만 *과거 캐시·재인덱싱 미반영
  // citation*에 legacy URL이 남아 있을 수 있어 클라이언트에서도 한 번 더 거름.
  if (citation.url && !/lsInfoP\.do\?lsiSeq=/i.test(citation.url)) {
    return stripBareAnnexSegment(citation.url);
  }
  if (citation.source_kind !== "doc") return null;
  const title = normalizeMetaField(citation.title);
  if (!title) return null;
  const article = normalizeMetaField(citation.article);
  const publisher = normalizeMetaField(citation.publisher);

  // 법령이 **아닌** 문서(가이드라인·안내서 등)에는 법령정보센터 링크를 붙이지 않는다.
  //
  // 사연(2026-08-04 긴급): backend 가 guide 문서에 `doc_category: "가이드라인"` 을
  // 박는데(식약처 가이드라인·안내서, docs_kure_v1), 아래 캐스트는 **컴파일 타임에만**
  // 존재해 런타임엔 그 값이 그대로 흘렀다. LawCategory 13종에 없으므로 lawLike 도
  // 아니어서 `buildPath("가이드라인", …)` 이 `law.go.kr/가이드라인/…` 를 합성했고,
  // externalUrlKind 가 그 URL 을 보고 **"법령정보센터에서 보기"** 를 띄웠다.
  // 법령정보센터에 있지도 않은 문서를 거기서 볼 수 있는 것처럼 보이게 한 것 —
  // 규제 상담에서 출처 신뢰를 직접 깎는다.
  //
  // backend 가 종별을 명시했는데 그게 법령군이 **아니면** 여기서 끝낸다.
  // detectCategory·검색 fallback 으로도 내려보내지 않는다 — 그쪽은 publisher 가
  // 정부기관(식약처)이면 lsSc.do 검색 링크를 만들어 같은 문제가 재발한다.
  const declared = normalizeMetaField(citation.doc_category);
  if (declared && !isLawCategory(declared)) return null;

  // R2 — backend가 명시한 doc_category가 있으면 heuristic 거치지 않고 바로 사용.
  const category = (declared as LawCategory | undefined) || detectCategory(citation);

  if (category) {
    const cleanedName = nameOnly(title, article);
    const isAnnex = /^\s*(?:별표|서식)\s*제?\s*\d/.test(article);

    // 일반 법령군에서 cleanedName이 *법령명 형태가 아니면* (backend가 title에 조항 제목만
    // 박은 케이스) 잘못된 path 만들지 X — 아래 검색 fallback으로 위임.
    const lawLikeCategory =
      category === "법령" ||
      category === "영문법령" ||
      category === "행정규칙" ||
      category === "자치법규" ||
      category === "학칙공단";
    if (lawLikeCategory && !isValidLawName(cleanedName)) {
      // category 매칭됐지만 name 신뢰 X — fall through to search
    } else {
      let path: string;
      if (category === "법령별표서식" && isAnnex) {
        path = buildLawSchedulePath(cleanedName, article.trim());
      } else if (category === "행정규칙별표서식" && isAnnex) {
        // backend가 발령번호(decreeNo) 메타 박지 않으면 행정규칙 본문으로 fallback
        path = buildAdmrulSchedulePath(cleanedName, article.trim());
      } else if (category === "자치법규별표서식" && isAnnex) {
        path = buildOrdinSchedulePath(cleanedName, article.trim());
      } else {
        path = buildPath(category, cleanedName, article || undefined);
      }
      return stripBareAnnexSegment(`${BASE}${path}`);
    }
  }

  // 한국 법령 같으나 분야 미검출 — 검색 fallback
  const looksKorean =
    /(법|령|규|규정|규칙|고시|예규|훈령|조례|판결|소원|심판|해석)/.test(title) ||
    isGovPublisher(publisher) ||
    isLocalGov(publisher);
  if (looksKorean) {
    const queryParts = [title];
    if (article && !title.includes(article)) {
      queryParts.push(article);
    }
    return searchFallbackUrl(queryParts.filter(Boolean).join(" "));
  }

  return null;
}

/** 외부 링크의 *출처 종류* — UI 아이콘/툴팁 분기용. */
export function externalUrlKind(_citation: Citation, url: string): "web" | "law-portal" | null {
  if (!url) return null;
  if (url.includes("law.go.kr")) return "law-portal";
  return "web";
}

/** 테스트·디버깅용 export. UI 코드에선 사용 X. */
export const __internal = {
  detectCategory,
  nameOnly,
  buildPath,
  buildLawSchedulePath,
  buildAdmrulSchedulePath,
  buildOrdinSchedulePath,
};
