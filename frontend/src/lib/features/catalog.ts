/**
 * 기능 레지스트리 — 카드 정의의 **단일 출처** (2026-10-02).
 *
 * 종전엔 `EmptyHero.tsx` 안에 상수 배열로 박혀 있었다. 그래서 첫 화면이 사라지는
 * 순간(= 첫 질문 직후) 기능에 닿을 길이 없었다. 사용자 요구: "어떤 모드로든 질문이
 * 시작되고 나면 이 카드들이 스레드 안에서 자유롭게 선택돼야 한다".
 *
 * 그러려면 같은 정의를 **여러 표면**(첫 화면 리스트 · 스레드 내 격자 피커 · 맥락
 * 제안)이 함께 읽어야 하고, 복제하면 화면마다 다른 말을 하게 된다. 정의는 여기,
 * 실행은 `useRunFeature`, 렌더는 `FeatureCards` — 셋을 분리한다.
 *
 * 노출 조건(`availableWhen`)도 여기 모은다. 종전엔 `EmptyHero`·`ChatInput`·
 * `PageShell` 에 흩어져 있어 "전문가 모드만" 같은 규칙이 화면마다 어긋났다.
 */

import type { AppMode } from "@/lib/store/mode";

export type FeatureField = {
  key: string;
  label: string;
  placeholder: string;
};

/**
 * 기능이 일으키는 부수효과.
 *  - `confidential` : 기밀 모드를 켠다(사건 파일·의뢰인 정보)
 *  - `attach`       : 파일 선택창을 연다(첨부 시 기밀도 자동으로 켜진다)
 *  - `brief`        : 의견서 초안 패널을 연다
 *  - `watch`        : 관찰 목록·보고서·발송 창을 연다(모니터링 전용)
 */
export type FeatureEffect = "confidential" | "attach" | "brief" | "watch";

/** 노출 판정에 쓰는 현재 상황. */
export type FeatureContext = {
  mode: AppMode | null;
  /** 이 스레드에 이미 턴이 있는가 — 의견서 초안 등은 대화가 있어야 의미가 있다 */
  hasTurns: boolean;
};

export type Feature = {
  /**
   * 안정 식별자 — 조합(워크플로) 저장·복원의 키다 (2026-10-02).
   *
   * 종전엔 제목이 사실상의 키였다. 그러면 문구를 다듬는 순간 저장된 조합이
   * 끊긴다. 저장되는 값이므로 **한 번 정하면 바꾸지 않는다** — 제목은 자유롭게
   * 고쳐도 되지만 id 는 고치지 않는다.
   */
  id: string;
  /** 그룹 라벨 겸 뱃지 — 격자 피커가 이걸로 묶는다 */
  category: string;
  title: string;
  subtitle: string;
  /** 구조화 입력 폼 — 빈 칸은 `___(라벨)` 로 남아 그대로 템플릿이 된다 */
  form?: {
    intro: string;
    fields: FeatureField[];
    build: (v: Record<string, string>) => string;
  };
  /** 2열 전체 폭 카드 */
  featured?: boolean;
  /** 프롬프트만 채우는 게 아니라 **그 기능이 실제로 켜져야** 한다 */
  triggers?: FeatureEffect;
  /**
   * 효과가 얼마나 가는가.
   *  - `turn`   : 이 턴에만 (템플릿 프리필)
   *  - `thread` : 스레드 내내 (기밀 모드 — 한 번 켜지면 유지)
   * 이 구분이 없으면 "기밀 검토 카드를 골랐다가 다음 턴에 조용히 꺼지는" 일이 난다.
   */
  stickiness?: "turn" | "thread";
  /** 이 질문으로 답변에서 얻는 것 — 선택 모달 안내. 2~3개 */
  expects: string[];
  /** 지금 이 상황에서 쓸 수 있는가. 없으면 항상 노출. */
  availableWhen?: (ctx: FeatureContext) => boolean;
};

/** 빈 칸은 `___` 로 남긴다 — 프리필은 자동 전송되지 않으므로 그대로 템플릿이 된다. */
function slot(v: string | undefined, hint: string): string {
  const t = (v ?? "").trim();
  return t || `___(${hint})`;
}

const EXPERT: Feature[] = [
  {
    id: "pathway",
    category: "규제 경로 분해",
    title: "인허가·신고 의무를 단계로 분해",
    subtitle: "무엇을 → 어디에 → 어떤 서식으로 → 언제까지",
    expects: [
      "단계별 체크리스트(접수처 · 서식 · 기한)",
      "단계마다 근거 조문 — 근거 없는 단계는 따로 표시",
      "빠뜨린 단계가 눈에 보이게",
    ],
    form: {
      intro: "대상을 적으면 그 사안의 절차를 단계로 분해합니다.",
      fields: [
        { key: "subject", label: "대상 (사업 · 제품 · 행위)", placeholder: "예: 체외진단 의료기기 수입 / 일반음식점 개업" },
        { key: "detail", label: "조건 (선택)", placeholder: "예: 2등급, 서울 마포구" },
      ],
      build: (v) =>
        `${slot(v.subject, "대상")}${v.detail?.trim() ? ` (${v.detail.trim()})` : ""} 와 관련해 밟아야 하는 ` +
        "인허가 · 신고 · 보고 의무를 단계별 절차로 분해해줘. " +
        "각 단계마다 어디에 접수하는지, 제출할 서식, 기한을 근거 조문과 함께 정리해줘.",
    },
  },
  {
    id: "form_find",
    category: "서식 작성",
    title: "제출 서식·별표를 찾아 바로 작성",
    subtitle: "서식 번호 · 근거 조문 · 첨부 서류",
    expects: [
      "근거 법령에 딸린 별지 서식 번호와 조문",
      "함께 내야 하는 첨부 서류 목록",
      "답변의 서식 인용에서 [이 서식으로 작성]으로 바로 기입",
    ],
    form: {
      intro: "무엇을 신청하는지 적으면 해당 서식을 찾아 작성 화면으로 연결합니다.",
      fields: [
        { key: "what", label: "신청 내용", placeholder: "예: 의료기기 제조업 허가 / 옥외광고물 표시 허가" },
        { key: "who", label: "신청인 (선택)", placeholder: "예: 법인, 수입업자" },
      ],
      build: (v) =>
        `${slot(v.what, "신청 내용")}${v.who?.trim() ? ` (${v.who.trim()})` : ""} 신청에 필요한 별지 서식·별표를 찾아줘. ` +
        "서식 번호와 근거 조문, 함께 제출할 첨부 서류 목록까지 정리해줘.",
    },
  },
  {
    id: "case_issues",
    category: "기밀 검토",
    stickiness: "thread",   // 한 번 켜지면 스레드 내내 유지된다
    title: "사건 파일로 적용 법령·쟁점 검토",
    subtitle: "원내 모델 전용 · 웹 검색 없음",
    triggers: "confidential",
    expects: [
      "사실관계에 적용되는 법령과 쟁점 정리",
      "이 대화는 원내(온프레미스) 모델로만 처리",
      "이어지는 질문도 같은 대화 안에서 맥락 유지",
    ],
    form: {
      intro: "기밀 모드가 켜집니다 — 입력 내용은 원내 모델로만 처리되고 외부로 나가지 않습니다.",
      fields: [
        { key: "facts", label: "사실관계 요약", placeholder: "예: 의뢰인이 2026-03 영업신고 없이 영업을 개시했고, 3개월 뒤 적발됨" },
        { key: "issue", label: "확인하려는 것 (선택)", placeholder: "예: 처분 수위와 감경 가능성" },
      ],
      build: (v) =>
        "다음 사안에 적용되는 법령과 쟁점을 정리해줘. 근거 조문을 함께 달아줘.\n\n" +
        `[사실관계]\n${slot(v.facts, "사실관계를 적어 주세요")}` +
        `\n\n[확인하려는 것]\n${slot(v.issue, "확인하려는 것")}`,
    },
  },
  {
    id: "doc_review",
    category: "문서 검토",
    stickiness: "thread",   // 첨부가 기밀을 켠다 — 역시 스레드 단위
    title: "계약서·내부 규정을 첨부해 검토",
    subtitle: "PDF · DOCX · HWPX · 기밀 모드 자동",
    triggers: "attach",
    expects: [
      "첨부 문서를 읽고 규제 적합성·누락 조항 검토",
      "첨부 즉시 기밀 모드가 켜져 외부로 나가지 않음",
      "지적마다 근거 조문 제시",
    ],
    form: {
      intro: "파일 선택창이 열립니다. 문서를 고르면 기밀 모드가 함께 켜집니다.",
      fields: [
        { key: "ask", label: "무엇을 봐 달라고 할까요", placeholder: "예: 개인정보 처리 조항이 현행법에 맞는지" },
      ],
      build: (v) =>
        `첨부한 문서를 검토해줘. ${slot(v.ask, "무엇을 봐 드릴까요")}. ` +
        "문제가 되는 부분은 근거 조문과 함께 짚어줘.",
    },
  },
  {
    id: "prec_issues",
    category: "판례 검토",
    title: "판례 검색 · 핵심 이슈 정리",
    subtitle: "법원 · 선고일 · 판시 요지를 표로",
    expects: [
      "쟁점에 관한 판례를 모아 사건별 판시 요지 정리",
      "비슷해 보이는 판례 사이의 **차이**를 짚어 줌",
      "법원·사건번호가 확인되는 것만 인용",
    ],
    form: {
      intro: "판례 종별로 검색합니다. 쟁점을 좁게 적을수록 결과가 또렷합니다.",
      fields: [
        { key: "issue", label: "쟁점", placeholder: "예: 영업신고 없이 영업한 경우 처분 수위" },
        { key: "scope", label: "범위 (선택)", placeholder: "예: 대법원 판결 위주 / 최근 10년" },
      ],
      build: (v) =>
        `판례를 찾아 핵심 쟁점을 정리해줘. 검색은 판례 종별(doc_kinds=["prec"])로 해줘.\n\n` +
        `[쟁점]\n${slot(v.issue, "쟁점을 적어 주세요")}` +
        `\n\n[범위]\n${slot(v.scope, "범위")}\n\n` +
        "사건마다 법원·선고일·판시 요지·결론을 표로 정리하고, 비슷해 보이는 " +
        "판례끼리는 결론이 갈린 이유를 짚어줘. 법원명과 사건번호가 확인되지 " +
        "않는 판례는 쓰지 마.",
    },
  },
  {
    id: "article_diff",
    category: "조문 변동",
    title: "조문 변동 대조",
    subtitle: "현행 ↔ 개정예정 · 기준 시점 이후 개정 여부",
    expects: [
      "현행 조문과 개정예정본이 있으면 나란히 대조",
      "기준 시점(예: 판결 선고일) 이후 개정이 있었는지 판정",
      "과거 조문 전문은 보유하지 않음 — 지어내지 않고 개정 시점만 제시",
    ],
    form: {
      intro:
        "현행 조문과 개정예정본을 대조합니다. 과거 시점의 조문 전문은 보유하고 " +
        "있지 않아, 그때 조문이 어땠는지는 개정 시점으로만 알려 드립니다.",
      fields: [
        { key: "article", label: "조문", placeholder: "예: 식품위생법 시행령 제25조" },
        { key: "asof", label: "기준 시점 (선택)", placeholder: "예: 2022-08-25 (판결 선고일)" },
      ],
      build: (v) =>
        `다음 조문의 변동을 대조해줘.\n\n[조문]\n${slot(v.article, "조문을 적어 주세요")}` +
        `\n\n[기준 시점]\n${slot(v.asof, "기준 시점")}\n\n` +
        "① 현행 조문을 제시하고, 시행 예정인 개정본이 검색되면 나란히 " +
        "대조해줘. ② 조문 본문에 붙은 개정 주석(<개정 …>, 삭제<…>)을 모아 " +
        "개정 시점을 열거해줘. ③ 기준 시점이 있으면 그 이후 개정이 있었는지, " +
        "그래서 그 시점 기준의 해석을 지금 그대로 쓸 수 있는지 판정해줘.\n\n" +
        "**없는 것은 없다고 적어라.** 과거 시점의 조문 전문은 이 시스템이 " +
        "보유하지 않는다 — 추측해 쓰지 말고 '과거 조문 전문 확인 불가'라고 " +
        "적고 개정 시점만 제시해줘. 현행 조문도 검색 결과가 발췌뿐이면 " +
        "발췌라고 밝히고, 뒷부분을 지어내지 마.",
    },
  },
  {
    id: "rule_gap",
    category: "규정 점검",
    title: "사내 규정 ↔ 법령 갭 점검",
    subtitle: "첨부한 내규가 현행 법령을 반영했는지",
    triggers: "attach",
    stickiness: "thread",
    expects: [
      "내규 조항별로 근거 법령을 짚고, 빠졌거나 어긋난 곳을 표로",
      "고쳐야 할 문구까지 제안",
      "기밀 모드 자동 — 내부 문서는 밖으로 내보내지 않는다",
    ],
    form: {
      intro: "사규·내규·업무지침을 첨부하세요. 조항 단위로 법령과 대조합니다.",
      fields: [
        { key: "scope", label: "점검 범위", placeholder: "예: 개인정보 처리 관련 조항" },
        { key: "asof", label: "기준 (선택)", placeholder: "예: 2026년 개정 반영 여부" },
      ],
      build: (v) =>
        `첨부한 내부 규정이 현행 법령을 반영하고 있는지 점검해줘.\n\n` +
        `[점검 범위]\n${slot(v.scope, "어디를 볼까요")}\n\n[기준]\n${slot(v.asof, "기준")}\n\n` +
        "규정 조항 ↔ 근거 법령 ↔ 상태(일치·미반영·충돌·근거없음)를 표로 정리하고, " +
        "미반영·충돌이면 고쳐야 할 문구를 제안해줘. 근거 조문을 못 찾은 항목은 " +
        "'근거 미확인'으로 남기고 추측하지 마.",
    },
  },
  {
    id: "duty_matrix",
    category: "의무 정리",
    title: "의무 주체 · 기한 · 제재 추출",
    subtitle: "누가 · 언제까지 · 안 하면 얼마",
    expects: [
      "의무마다 주체·행위·기한·제출처·근거조문·위반 제재를 표로",
      "자문 결론에 그대로 붙일 수 있는 형태",
    ],
    form: {
      intro: "자문 결론의 뼈대가 되는 표를 만듭니다.",
      fields: [
        { key: "subject", label: "대상", placeholder: "예: 온라인 식품판매 중개 플랫폼 입점 사업자" },
        { key: "scope", label: "범위 (선택)", placeholder: "예: 영업 개시 전 의무만" },
      ],
      build: (v) =>
        `다음 대상의 법적 의무를 표로 정리해줘.\n\n[대상]\n${slot(v.subject, "대상을 적어 주세요")}` +
        `\n\n[범위]\n${slot(v.scope, "범위")}\n\n` +
        "각 행에 ① 의무 주체 ② 해야 할 행위 ③ 기한 ④ 제출처·접수기관 ⑤ 근거 조문 " +
        "⑥ 위반 시 제재(과태료·벌칙 금액까지)를 넣어줘. 제재 금액이 조문에서 " +
        "확인되지 않으면 '조문 미확인'으로 적고 지어내지 마.",
    },
  },
  {
    id: "ordinance_compare",
    category: "지역 비교",
    title: "지자체별 조례 요건 비교",
    subtitle: "같은 사업, 지역마다 다른 요건",
    expects: [
      "지역별로 요건·수수료·처리기간 차이를 표로",
      "조례가 검색되지 않은 지역은 '확인 불가'로 명시",
    ],
    form: {
      intro: "조례는 지자체마다 다릅니다. 비교할 지역을 적어 주세요.",
      fields: [
        { key: "subject", label: "사업 · 행위", placeholder: "예: 일반음식점 영업신고" },
        { key: "regions", label: "비교할 지역", placeholder: "예: 서울 강남구, 경기 성남시, 부산 해운대구" },
      ],
      build: (v) =>
        `같은 사업에 대해 지자체별 조례 요건을 비교해줘. 검색은 자치법규 종별` +
        `(doc_kinds=["ordin"])을 포함해서 해줘.\n\n[사업·행위]\n${slot(v.subject, "무엇에 대한 비교인가요")}` +
        `\n\n[비교할 지역]\n${slot(v.regions, "지역을 적어 주세요")}\n\n` +
        "지역 × 요건(시설·면적·첨부서류·수수료·처리기간)을 표로 만들고, 상위 법령과 " +
        "달라지는 지점을 짚어줘. **조례가 검색되지 않은 지역은 '확인 불가'로 적고 " +
        "다른 지역 내용을 옮겨 쓰지 마.**",
    },
  },
  {
    id: "interpretation",
    category: "유권해석",
    title: "유권해석 · 행정해석 확인",
    subtitle: "조문만으론 안 나오는 집행 기준",
    expects: [
      "법령해석례·행정심판례에서 집행 기준 확인",
      "해석이 갈리면 그 이유까지",
    ],
    form: {
      intro: "조문 문언으로 결론이 안 나는 쟁점에 씁니다.",
      fields: [
        { key: "issue", label: "쟁점", placeholder: "예: 중개 플랫폼 입점자가 '영업자'에 해당하는지" },
        { key: "article", label: "관련 조문 (선택)", placeholder: "예: 식품위생법 제37조" },
      ],
      build: (v) =>
        `다음 쟁점에 관한 유권해석·행정해석을 찾아줘. 검색은 해석례 종별` +
        `(doc_kinds=["expc"])을 포함해서 해줘.\n\n[쟁점]\n${slot(v.issue, "쟁점을 적어 주세요")}` +
        `\n\n[관련 조문]\n${slot(v.article, "조문")}\n\n` +
        "해석기관·회신일자·결론을 표로 정리하고, 해석이 갈리는 부분이 있으면 " +
        "무엇 때문에 갈리는지 짚어줘. 기관과 일자가 확인되지 않는 해석은 쓰지 마.",
    },
  },
  {
    id: "cite_verify",
    category: "인용 검증",
    title: "인용된 조문 · 판례 검증",
    subtitle: "상대방 서면 · AI 산출물의 날조 판별",
    expects: [
      "인용마다 실재·내용 일치·현행 여부 판정",
      "확인 안 되는 인용은 '확인 불가'로 분리",
    ],
    form: {
      intro:
        "상대방 서면이나 AI가 쓴 글에서 인용 부분을 붙여 넣으세요. " +
        "존재하지 않는 판례를 제출해 제재받은 사례가 국내외에 있습니다.",
      fields: [
        { key: "cites", label: "검증할 인용", placeholder: "예: 대법원 2008도6829, 식품위생법 제37조 제4항 …" },
        { key: "claim", label: "그 인용으로 주장하는 내용 (선택)", placeholder: "예: 무허가 건물이면 영업신고가 무효라는 주장" },
      ],
      build: (v) =>
        `다음 인용이 실제로 존재하고 주장 내용과 맞는지 검증해줘.\n\n` +
        `[검증할 인용]\n${slot(v.cites, "검증할 인용을 붙여 넣어 주세요")}` +
        `\n\n[주장 내용]\n${slot(v.claim, "주장")}\n\n` +
        "인용마다 ① 실재 여부 ② 검색된 실제 제목·법원·사건번호 ③ 주장 내용과 " +
        "일치하는지 ④ 현행인지(폐지·개정 여부)를 표로 판정해줘. **검색으로 " +
        "확인되지 않은 인용은 '존재 확인 불가'로 분리하고, 비슷한 다른 것으로 " +
        "대체해 설명하지 마.**",
    },
  },
  {
    id: "sanction_level",
    category: "제재 가늠",
    title: "제재 수위 가늠",
    subtitle: "과태료 · 영업정지 실제 수위",
    expects: [
      "법정 상한과 실제 부과 기준(별표)을 함께",
      "감경·가중 사유와 판례상 수위",
    ],
    form: {
      intro: "법정형과 실제 운용 기준은 다릅니다. 둘 다 봅니다.",
      fields: [
        { key: "violation", label: "위반 행위", placeholder: "예: 영업신고 없이 영업" },
        { key: "context", label: "사정 (선택)", placeholder: "예: 초범, 3개월, 자진신고" },
      ],
      build: (v) =>
        `다음 위반의 제재 수위를 가늠해줘.\n\n[위반 행위]\n${slot(v.violation, "위반 행위를 적어 주세요")}` +
        `\n\n[사정]\n${slot(v.context, "사정")}\n\n` +
        "① 근거 조문의 법정 상한 ② 시행령·시행규칙 **별표**의 부과 기준(차수별 금액·" +
        "정지일수) ③ 감경·가중 사유 ④ 판례에서 실제 선고된 수위를 정리해줘. " +
        "별표가 검색되지 않으면 법정 상한만 제시하고 그렇게 밝혀줘.",
    },
  },
  {
    id: "pending_watch",
    category: "개정 추적",
    title: "개정 예정 · 시행 대기 확인",
    subtitle: "공포됐지만 아직 시행 전인 것",
    expects: [
      "시행예정 개정본과 시행일 확인",
      "유예기간·경과규정 정리",
      "입법예고 단계(공포 전)는 보유하지 않음 — 그렇게 밝힌다",
    ],
    form: {
      intro:
        "공포 후 시행 전인 개정을 찾습니다. 입법예고·국회 계류 단계 자료는 " +
        "아직 수집 범위가 아니라, 그 구간은 확인 불가로 답합니다.",
      fields: [
        { key: "subject", label: "대상", placeholder: "예: 식품위생법상 영업신고 의무" },
        { key: "horizon", label: "기간 (선택)", placeholder: "예: 1년 내 시행 예정" },
      ],
      build: (v) =>
        `다음 대상에 대해 시행 예정인 개정이 있는지 확인해줘.\n\n` +
        `[대상]\n${slot(v.subject, "대상을 적어 주세요")}\n\n[기간]\n${slot(v.horizon, "기간")}\n\n` +
        "① 시행예정 개정본이 검색되면 현행과 무엇이 달라지는지 ② 시행일과 " +
        "유예기간·경과규정 ③ 지금 해 둬야 할 일을 정리해줘.\n\n" +
        "**공포 전(입법예고·국회 계류) 자료는 이 시스템이 보유하지 않는다. " +
        "그 구간은 '확인 불가 — 입법예고 단계는 미수집'이라고 적고 추측하지 마.**",
    },
  },
  {
    id: "impact_graph",
    category: "영향 분석",
    title: "조문 개정 영향 범위",
    subtitle: "이 조문이 바뀌면 같이 흔들리는 곳",
    expects: [
      "그 조문을 인용·준용하는 다른 조문과 하위 법령",
      "실무에서 같이 고쳐야 할 서식·내규 지점",
    ],
    form: {
      intro:
        "한 조문을 건드렸을 때 번지는 범위를 봅니다. 조문 간 인용망 DB가 " +
        "연결되면 더 정확해집니다(현재는 검색 기반).",
      fields: [
        { key: "article", label: "조문", placeholder: "예: 식품위생법 제37조" },
        { key: "change", label: "예상 변경 (선택)", placeholder: "예: 신고 대상 업종 축소" },
      ],
      build: (v) =>
        `다음 조문이 개정되면 영향받는 범위를 분석해줘.\n\n` +
        `[조문]\n${slot(v.article, "조문을 적어 주세요")}\n\n[예상 변경]\n${slot(v.change, "변경")}\n\n` +
        "① 이 조문을 인용·준용하는 다른 조문(시행령·시행규칙·고시 포함) " +
        "② 연결된 별표·서식 ③ 실무에서 같이 고쳐야 할 지점을 정리해줘. " +
        "검색으로 확인된 것만 쓰고, 인용 관계가 확인되지 않으면 '관련 가능성' " +
        "으로만 적어 단정하지 마.",
    },
  },
];

const PUBLIC: Feature[] = [
  {
    id: "life_lease",
    category: "생활·계약",
    title: "임대차 보증금·계약 문제",
    subtitle: "보증금 반환 · 계약 해지 · 수리 책임",
    expects: [
      "지금 할 수 있는 조치를 순서대로",
      "근거가 되는 법 조문",
      "전문가 상담이 필요한 시점",
    ],
  },
  {
    id: "life_work",
    category: "일터",
    title: "임금·해고·휴가 문제",
    subtitle: "체불 임금 · 해고 절차 · 연차",
    expects: [
      "어디에 어떻게 신고하는지",
      "근거 조문과 기한",
      "준비해야 할 자료",
    ],
  },
  {
    id: "life_biz",
    category: "창업·영업",
    title: "업종별 인허가와 영업신고",
    subtitle: "필요한 허가 · 순서 · 제출 서류",
    expects: [
      "무엇을 → 어디에 → 어떤 서류로 내는지",
      "인허가와 사업자등록의 선후",
      "관할 지자체에 확인할 항목",
    ],
    form: {
      intro: "업종을 적으면 더 정확한 절차를 안내받을 수 있습니다.",
      fields: [
        { key: "biz", label: "업종", placeholder: "예: 카페 / 온라인 쇼핑몰" },
        { key: "region", label: "지역 (선택)", placeholder: "예: 서울 마포구" },
      ],
      build: (v) =>
        v.biz
          ? `${v.biz}${v.region ? ` (${v.region})` : ""} 창업에 필요한 인허가와 영업신고 절차를 순서대로 알려줘. 어디에 어떤 서류를 내야 하는지도 알려줘.`
          : "창업에 필요한 인허가와 영업신고 절차를 순서대로 알려줘.",
    },
  },
  {
    id: "life_penalty",
    category: "행정처분",
    title: "과태료·행정처분을 받았을 때",
    subtitle: "이의신청 · 기한 · 감경 사유",
    expects: [
      "이의신청 방법과 기한",
      "감경·면제 사유가 있는지",
      "근거 조문",
    ],
  },
];

/**
 * 모니터링 경로 전용 (2026-10-02).
 *
 * 다른 경로의 카드가 "무엇을 물을까"라면, 여기는 "무엇을 관찰할까"다.
 * 대화로 규제를 찾아 관찰 목록에 담는 것이 이 모드의 전부다.
 */
const MONITOR: Feature[] = [
  {
    id: "mon_subject",
    category: "대상 정의",
    title: "관찰할 규제 찾기",
    subtitle: "대화로 찾고 → 관찰 목록에 담기",
    expects: [
      "이 대상에 걸리는 법령·고시·조례를 찾아 줍니다",
      "찾은 근거를 [관찰 목록]에 담으면 개정을 추적합니다",
      "담을 것은 직접 고릅니다 — 자동으로 넣지 않습니다",
    ],
    form: {
      intro: "무엇을 모니터링할지 적으면 관련 규제를 찾아 드립니다.",
      fields: [
        {
          key: "subject",
          label: "대상 (기업 · 사업 · 제품 · 이슈)",
          placeholder: "예: 의료기기 수입업 / 개인정보 처리 / 아크로제약",
        },
        { key: "scope", label: "범위 (선택)", placeholder: "예: 인허가와 사후관리" },
      ],
      build: (v) =>
        `${slot(v.subject, "모니터링 대상")}${v.scope?.trim() ? ` (${v.scope.trim()})` : ""} 에 ` +
        "적용되는 법령 · 행정규칙 · 조례를 찾아줘. 각각 무엇을 규율하는지 한 줄로 " +
        "요약하고 근거 조문을 달아줘.",
    },
  },
  {
    id: "mon_extract",
    category: "자료 검토",
    title: "내부 문서에서 규제 뽑기",
    subtitle: "계약서 · 내부 규정 · 인허가 서류 첨부",
    triggers: "attach",
    stickiness: "thread",
    expects: [
      "첨부 문서가 걸리는 규제를 짚어 줍니다",
      "첨부 즉시 기밀 모드가 켜져 외부로 나가지 않습니다",
      "찾은 규제를 그대로 관찰 목록에 담을 수 있습니다",
    ],
    form: {
      intro: "파일 선택창이 열립니다. 문서를 고르면 기밀 모드가 함께 켜집니다.",
      fields: [
        {
          key: "ask",
          label: "무엇을 봐 드릴까요",
          placeholder: "예: 이 계약서가 걸리는 인허가 의무",
        },
      ],
      build: (v) =>
        `첨부한 문서를 검토해, ${slot(v.ask, "무엇을 봐 드릴까요")}. ` +
        "관련 법령·조문을 근거와 함께 짚어줘.",
    },
  },
  {
    id: "mon_watch",
    category: "변경 추적",
    title: "관찰 목록 · 변경 확인",
    subtitle: "담은 조문 보기 · 지금 변경 확인 · 보고서",
    triggers: "watch",
    expects: [
      "이 대상이 관찰 중인 조문을 한눈에",
      "지금 변경이 있는지 확인 (법령 DB 연결 필요)",
      "변경을 모아 짧은 보고서로 만들고 메일 발송",
    ],
  },
];

/**
 * 의견서 초안 — 대화가 있어야 의미가 있다(근거를 대화의 인용에서 가져온다).
 * 다른 카드와 달리 프롬프트를 채우지 않고 **패널을 바로 연다**.
 */
const BRIEF: Feature = {
  id: "brief",
  category: "서면 작성",
  title: "의견서 초안 만들기",
  subtitle: "사실관계 · 쟁점 · 검토 · 결론 골격 + 근거 목록",
  triggers: "brief",
  expects: [
    "지금까지의 대화와 그 인용으로 서면 골격 생성",
    "문단을 눌러 그 문단만 고쳐 쓰기",
    "문서에 없는 인용 번호는 자동으로 제거",
  ],
  availableWhen: (ctx) => ctx.mode !== "public" && ctx.hasTurns,
};

/** 현재 상황에서 고를 수 있는 기능 — 모든 표면이 이 함수를 쓴다. */
export function featuresFor(ctx: FeatureContext): Feature[] {
  const base =
    ctx.mode === "public"
      ? PUBLIC
      : ctx.mode === "monitor"
        ? MONITOR
        : [...EXPERT, BRIEF];
  return base.filter((f) => !f.availableWhen || f.availableWhen(ctx));
}

/** 격자 피커용 — 카테고리별 묶음(정의 순서 유지). */
export function groupFeatures(list: Feature[]): { group: string; items: Feature[] }[] {
  const out: { group: string; items: Feature[] }[] = [];
  for (const f of list) {
    const row = out.find((g) => g.group === f.category);
    if (row) row.items.push(f);
    else out.push({ group: f.category, items: [f] });
  }
  return out;
}

/** 제목·부제·카테고리 부분일치 — 기능이 늘어도 찾을 수 있게. */
export function filterFeatures(list: Feature[], q: string): Feature[] {
  const t = q.trim().toLowerCase();
  if (!t) return list;
  return list.filter((f) =>
    [f.title, f.subtitle, f.category].some((s) => s.toLowerCase().includes(t)),
  );
}
