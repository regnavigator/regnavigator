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
  /**
   * 턴 기본 검색 종별(2026-10-03). 종전엔 build 가 `doc_kinds=["prec"]` 를
   * 사용자 입력창에 평문으로 박았다 — 내부 파라미터 노출 + 지우면 기능이 조용히
   * 달라짐. 구조화 필드로 `POST /chat.doc_kinds` 에 실린다. 백엔드는 이 값을
   * 한계 고지(`legal.FEATURE_CAVEATS`) 키로도 쓴다.
   */
  docKinds?: string[];
  /**
   * 업무 단계(2026-10-06). 종전 세부 라벨("판례 검토"·"조문 변동"…)은 검색 종별 기준이라
   * "다음에 뭘 하지"를 말해 주지 않았다. 번호 붙은 4단계로 통일 — 타일·패널·연계 목록이
   * 같은 라벨을 쓰고, 순서가 곧 업무 흐름이다. 일반·모니터링 카드는 자유 문자열 유지.
   */
  category: Stage | string;
  /** Material Symbols 아이콘 — 기능별. 단계에 묶으면 같은 단계가 전부 같은 아이콘이 된다. */
  icon?: string;
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
  /**
   * 연계에서 **무엇을 받고 무엇을 내는가**(2026-10-06, 공백 채움용). 소수의 명사 어휘
   * (`Slot`)로 고정 — `fn` 처럼 저장·비교에 쓰이므로 한 번 정하면 바꾸지 않는다.
   * `needs` 의 한 원소가 배열이면 **그중 하나**면 된다(facts 또는 doc). 없으면 연계
   * 공백 판정 대상이 아니다(`life_*`·`mon_*`).
   */
  io?: { needs: (Slot | Slot[])[]; yields: Slot[] };
};

/** 연계 슬롯 어휘 — 기능 사이를 오가는 산출의 종류. 저장 어휘라 추가만 하고 바꾸지 않는다. */
export type Slot =
  | "facts"      // 사실관계
  | "issue"      // 쟁점
  | "subject"    // 규제 대상(사업·제품·행위)
  | "article"    // 조문
  | "precedent"  // 판례
  | "duty"       // 의무 목록
  | "form"       // 서식
  | "sanction"   // 제재
  | "doc"        // 첨부 문서
  | "analysis"   // 법리 검토 결과 (2026-10-06)
  | "evidence"   // 증거·입증 계획 (2026-10-06)
  | "deadline";  // 기한 (2026-10-06)

export const SLOT_LABEL: Record<Slot, string> = {
  facts: "사실관계", issue: "쟁점", subject: "규제 대상", article: "조문", precedent: "판례",
  duty: "의무 목록", form: "서식", sanction: "제재", doc: "첨부 문서",
  analysis: "법리 검토", evidence: "증거", deadline: "기한",
};

/** 전문가 업무 단계 — 번호가 곧 순서. 첫 화면 타일·패널·연계 목록이 같은 라벨을 쓴다. */
export type Stage = "1 파악" | "2 조사" | "3 분석" | "4 산출";
export const STAGES: Stage[] = ["1 파악", "2 조사", "3 분석", "4 산출"];

/**
 * 합병·이동된 기능 id → 지금 id (2026-10-06). 저장된 직무·조합이 끊기지 않게 `fromTemplate`
 * 가 조용히 승격한다. `fn` 은 저장 어휘라 여기서만 바꾼다.
 */
export const LEGACY_FN: Record<string, string> = {
  pending_watch: "article_diff",   // 같은 질문("이 조문 바뀌나"), 시점만 다름 → direction 선택지
  rule_gap: "doc_review",          // 관점 "내규↔법령 갭"
  mon_extract: "doc_review",       // 관점 "걸리는 규제 추출"
};

/** 빈 칸은 `___` 로 남긴다 — 프리필은 자동 전송되지 않으므로 그대로 템플릿이 된다. */
function slot(v: string | undefined, hint: string): string {
  const t = (v ?? "").trim();
  return t || `___(${hint})`;
}

const EXPERT: Feature[] = [
  {
    id: "facts_timeline",
    io: { needs: [["doc", "facts"]], yields: ["facts", "issue"] },
    category: "1 파악",
    icon: "timeline",
    title: "사실관계·타임라인 정리",
    subtitle: "일시 · 당사자 · 행위 · 증거를 시간순으로",
    triggers: "confidential",
    stickiness: "thread",
    expects: [
      "시간순 표 — 다툼 있는 사실과 없는 사실을 구분",
      "법적 평가는 하지 않는다 — 다음 단계(쟁점 검토)의 재료",
      "사건 자료라 기밀 모드가 켜진다",
    ],
    form: {
      intro: "메모·파일 내용을 붙여 넣거나 첨부하면 사실관계를 시간순으로 정리합니다.",
      fields: [
        { key: "source", label: "자료 (붙여 넣기 · 선택)", placeholder: "첨부가 있으면 비워 두세요" },
        { key: "focus", label: "특히 볼 것 (선택)", placeholder: "예: 계약 체결부터 해지 통보까지" },
      ],
      build: (v) =>
        "다음 자료에서 사실관계를 시간순으로 정리해줘.\n\n" +
        `[자료]\n${slot(v.source, "자료")}` +
        `\n\n[특히 볼 것]\n${slot(v.focus, "특히 볼 것")}\n\n` +
        "일시 · 당사자 · 행위 · 근거 자료를 표로 만들고, **다툼이 있는 사실과 없는 사실을 " +
        "구분**해줘. 법적 평가나 결론은 적지 마 — 사실만. 자료에 없는 것은 지어내지 말고 " +
        "'확인 필요'로 남겨.",
    },
  },
  {
    id: "question_list",
    io: { needs: [["facts", "doc"]], yields: ["facts"] },
    category: "1 파악",
    icon: "help_center",
    title: "확인 질문 목록",
    subtitle: "의뢰인 · 상대 · 기관에 물을 것",
    expects: [
      "비어 있거나 다툼 있는 사실마다 '왜 필요한가(어느 요건)'와 함께 질문",
      "대상별(의뢰인 / 상대방 / 기관) 묶음",
    ],
    form: {
      intro: "사실관계에서 빠진 것을 질문 목록으로 바꿉니다. 앞 단계 결과를 그대로 씁니다.",
      fields: [
        { key: "target", label: "누구에게 (선택)", placeholder: "예: 의뢰인 / 상대방 / 관할 기관" },
      ],
      build: (v) =>
        "지금까지 정리된 사실관계에서 **비어 있거나 다툼이 있는 부분**을 확인 질문으로 만들어줘.\n\n" +
        `[누구에게]\n${slot(v.target, "누구에게")}\n\n` +
        "질문마다 왜 필요한지(어느 법적 요건과 연결되는지)를 한 줄로 달고, 의뢰인·상대방·" +
        "기관별로 묶어줘. 이미 확인된 사실은 묻지 마.",
    },
  },
  {
    id: "case_issues",
    io: { needs: [["facts", "doc"]], yields: ["issue", "article"] },
    category: "1 파악",
    icon: "folder_open",
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
    io: { needs: ["doc"], yields: ["issue", "article", "duty"] },
    category: "1 파악",
    icon: "attach_file",
    stickiness: "thread",   // 첨부가 기밀을 켠다 — 역시 스레드 단위
    title: "문서 첨부해 검토",
    subtitle: "적합성 · 내규↔법령 갭 · 규제 추출 · 위험 조항 — 관점 선택",
    triggers: "attach",
    expects: [
      "관점에 따라 적합성 검토 / 내규 조항별 갭 표 / 걸리는 규제 목록 / 위험 조항 지적",
      "첨부 즉시 기밀 모드가 켜져 외부로 나가지 않음",
      "지적마다 근거 조문 제시",
    ],
    form: {
      intro: "파일 선택창이 열립니다. 문서를 고르면 기밀 모드가 함께 켜집니다.",
      fields: [
        {
          key: "perspective",
          label: "관점 (선택)",
          placeholder: "적합성 검토(기본) / 내규↔법령 갭 / 규제 추출 / 위험 조항",
        },
        { key: "ask", label: "특히 볼 것 (선택)", placeholder: "예: 개인정보 처리 조항이 현행법에 맞는지" },
      ],
      build: (v) => {
        const p = (v.perspective ?? "").trim();
        const ask = v.ask?.trim() ? ` 특히: ${v.ask.trim()}.` : "";
        if (/갭|내규/.test(p)) {
          return "첨부한 내부 규정이 현행 법령을 반영하고 있는지 점검해줘." + ask + "\n\n" +
            "규정 조항 ↔ 근거 법령 ↔ 상태(일치·미반영·충돌·근거없음)를 표로 정리하고, " +
            "미반영·충돌이면 고쳐야 할 문구를 제안해줘. 근거 조문을 못 찾은 항목은 " +
            "'근거 미확인'으로 남기고 추측하지 마.";
        }
        if (/추출|걸리는|규제/.test(p)) {
          return "첨부한 문서가 걸리는 법령·행정규칙·조례를 뽑아줘." + ask + "\n\n" +
            "문서의 어느 부분이 어느 조문에 걸리는지 짝지어 표로 만들고, 각 규제가 무엇을 " +
            "요구하는지 한 줄로 요약해줘. 근거 조문을 함께 달아줘.";
        }
        if (/위험|리스크/.test(p)) {
          return "첨부한 문서에서 법적 위험이 있는 조항을 짚어줘." + ask + "\n\n" +
            "조항별로 위험의 내용·근거 조문·완화 방안을 표로 정리해줘. 근거 없는 조항은 " +
            "'근거 미확인'으로 남겨.";
        }
        return `첨부한 문서를 검토해줘.${ask || " 규제 적합성과 누락 조항을 봐줘."} ` +
          "문제가 되는 부분은 근거 조문과 함께 짚어줘.";
      },
    },
  },
  {
    id: "prec_issues",
    io: { needs: ["issue"], yields: ["precedent"] },
    docKinds: ["prec"],
    category: "2 조사",
    icon: "balance",
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
        `판례를 찾아 핵심 쟁점을 정리해줘.\n\n` +
        `[쟁점]\n${slot(v.issue, "쟁점을 적어 주세요")}` +
        `\n\n[범위]\n${slot(v.scope, "범위")}\n\n` +
        "사건마다 법원·선고일·판시 요지·결론을 표로 정리하고, 비슷해 보이는 " +
        "판례끼리는 결론이 갈린 이유를 짚어줘. 법원명과 사건번호가 확인되지 " +
        "않는 판례는 쓰지 마.",
    },
  },
  {
    id: "interpretation",
    io: { needs: [["issue", "article"]], yields: ["article"] },
    docKinds: ["expc"],
    category: "2 조사",
    icon: "quick_reference_all",
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
        `다음 쟁점에 관한 유권해석·행정해석을 찾아줘.\n\n[쟁점]\n${slot(v.issue, "쟁점을 적어 주세요")}` +
        `\n\n[관련 조문]\n${slot(v.article, "조문")}\n\n` +
        "해석기관·회신일자·결론을 표로 정리하고, 해석이 갈리는 부분이 있으면 " +
        "무엇 때문에 갈리는지 짚어줘. 기관과 일자가 확인되지 않는 해석은 쓰지 마.",
    },
  },
  {
    id: "article_diff",
    io: { needs: ["article"], yields: ["article"] },
    category: "2 조사",
    icon: "difference",
    title: "조문 변동 대조",
    subtitle: "과거 개정 · 시행 예정 · 기준 시점 이후 개정 여부",
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
        {
          key: "direction",
          label: "방향 (선택)",
          placeholder: "과거 개정 확인 / 시행 예정 확인 / 둘 다(기본)",
        },
        { key: "asof", label: "기준 시점 (선택)", placeholder: "예: 2022-08-25 (판결 선고일)" },
      ],
      build: (v) => {
        const d = (v.direction ?? "").trim();
        const past = !d || /과거|둘 다|모두/.test(d);
        const future = !d || /예정|시행|둘 다|모두/.test(d);
        return `다음 조문의 변동을 대조해줘.\n\n[조문]\n${slot(v.article, "조문을 적어 주세요")}` +
        `\n\n[기준 시점]\n${slot(v.asof, "기준 시점")}\n\n` +
        "① 현행 조문을 제시해줘. " +
        (future ? "시행 예정인 개정본이 검색되면 나란히 대조하고, 시행일·유예기간·경과규정과 " +
                  "지금 해 둬야 할 일을 정리해줘. **공포 전(입법예고·국회 계류) 자료는 이 시스템이 " +
                  "보유하지 않는다 — 그 구간은 '확인 불가'로 적어라.** " : "") +
        (past ? "② 조문 본문에 붙은 개정 주석(<개정 …>, 삭제<…>)을 모아 개정 시점을 열거해줘. " +
                "③ 기준 시점이 있으면 그 이후 개정이 있었는지, 그래서 그 시점 기준의 해석을 지금 " +
                "그대로 쓸 수 있는지 판정해줘. " : "") + "\n\n" +
        "**없는 것은 없다고 적어라.** 과거 시점의 조문 전문은 이 시스템이 " +
        "보유하지 않는다 — 추측해 쓰지 말고 '과거 조문 전문 확인 불가'라고 " +
        "적고 개정 시점만 제시해줘. 현행 조문도 검색 결과가 발췌뿐이면 " +
        "발췌라고 밝히고, 뒷부분을 지어내지 마.";
      },
    },
  },
  {
    id: "ordinance_compare",
    io: { needs: [["subject", "facts"]], yields: ["article"] },
    docKinds: ["ordin"],
    category: "2 조사",
    icon: "map",
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
        `같은 사업에 대해 지자체별 조례 요건을 비교해줘.\n\n[사업·행위]\n${slot(v.subject, "무엇에 대한 비교인가요")}` +
        `\n\n[비교할 지역]\n${slot(v.regions, "지역을 적어 주세요")}\n\n` +
        "지역 × 요건(시설·면적·첨부서류·수수료·처리기간)을 표로 만들고, 상위 법령과 " +
        "달라지는 지점을 짚어줘. **조례가 검색되지 않은 지역은 '확인 불가'로 적고 " +
        "다른 지역 내용을 옮겨 쓰지 마.**",
    },
  },
  {
    id: "legal_memo",
    io: { needs: ["issue", ["article", "precedent"]], yields: ["analysis"] },
    category: "3 분석",
    icon: "gavel",
    title: "쟁점별 법리 검토",
    subtitle: "요건 → 사실 포섭 → 결론",
    expects: [
      "쟁점마다 ① 조문 요건 ② 사실 포섭 ③ 판례 기준 ④ 결론과 불확실성",
      "결론이 갈릴 수 있으면 양쪽을 다 적는다",
      "요건별 근거 번호",
    ],
    form: {
      intro: "앞 단계에서 정리된 쟁점·조문·판례를 적용해 결론을 냅니다.",
      fields: [
        { key: "issue", label: "쟁점 (선택)", placeholder: "앞 단계 결과가 있으면 비워 두세요" },
        { key: "position", label: "우리 측 입장 (선택)", placeholder: "예: 원고 / 피신청인 / 자문 의뢰인" },
      ],
      build: (v) =>
        "다음 쟁점에 대해 법리 검토를 해줘.\n\n" +
        `[쟁점]\n${slot(v.issue, "쟁점")}` +
        `\n\n[우리 측 입장]\n${slot(v.position, "입장")}\n\n` +
        "쟁점마다 ① 적용 조문의 요건 ② 사실관계의 요건 포섭 ③ 판례가 세운 기준 ④ 결론과 " +
        "남는 불확실성을 순서대로 적어줘. 요건마다 근거 번호를 달고, 결론이 갈릴 수 있으면 " +
        "양쪽 논거를 다 써. 근거가 확인되지 않는 요건은 '근거 미확인'으로 남겨.",
    },
  },
  {
    id: "precedent_compare",
    io: { needs: ["facts", "precedent"], yields: ["analysis"] },
    category: "3 분석",
    icon: "compare",
    title: "판례 적용 비교",
    subtitle: "우리 사실관계 ↔ 선례 — 같은 점 · 다른 점 · 구별 논거",
    expects: [
      "선례마다 요건별 사실 대조 표",
      "적용 가능 / 구별(distinguish) 판정과 그 논거",
    ],
    form: {
      intro: "앞 단계에서 찾은 판례를 우리 사실관계에 대조합니다.",
      fields: [
        { key: "focus", label: "특히 볼 요건 (선택)", placeholder: "예: 고의 여부 / 손해 발생 시점" },
      ],
      build: (v) =>
        "앞에서 찾은 판례들을 우리 사실관계와 대조해줘.\n\n" +
        `[특히 볼 요건]\n${slot(v.focus, "요건")}\n\n` +
        "선례마다 요건별로 선례의 사실 ↔ 우리 사실을 표로 나란히 놓고, 같은 점·다른 점을 " +
        "짚은 뒤 '적용 가능' 또는 '구별됨'으로 판정하고 논거를 적어줘. 사건번호가 확인되지 " +
        "않는 판례는 쓰지 마.",
    },
  },
  {
    id: "evidence_map",
    io: { needs: [["facts", "doc"], "issue"], yields: ["evidence"] },
    category: "3 분석",
    icon: "inventory",
    title: "증거·입증 계획",
    subtitle: "요건사실 ↔ 보유 증거 ↔ 부족한 증거",
    triggers: "confidential",
    stickiness: "thread",
    expects: [
      "쟁점·요건사실별 입증책임 → 보유 증거 → 부족한 증거와 확보 방법",
      "증거의 가치 평가는 하지 않는다",
    ],
    form: {
      intro: "쟁점별로 무엇을 입증해야 하고 무엇이 부족한지 표로 만듭니다.",
      fields: [
        { key: "have", label: "보유 증거 (선택)", placeholder: "예: 계약서, 문자 내역, 입금 기록" },
      ],
      build: (v) =>
        "쟁점별 입증 계획을 세워줘.\n\n" +
        `[보유 증거]\n${slot(v.have, "보유 증거")}\n\n` +
        "쟁점 → 요건사실 → 입증책임(누가) → 보유 증거 → **부족한 증거와 확보 방법**(문서제출명령·" +
        "사실조회·증인 등)을 표로 정리해줘. 증거의 증명력 평가는 하지 말고, 요건사실의 근거 " +
        "조문을 달아줘.",
    },
  },
  {
    id: "counter_argument",
    // 상대 서면을 쪼개면 그 안의 사실 주장·인용 조문·판례가 다음 단계 재료가 된다.
    io: { needs: [["doc", "facts"]], yields: ["facts", "issue", "article", "precedent", "analysis"] },
    category: "3 분석",
    icon: "swords",
    title: "상대방 주장 분석",
    subtitle: "약점 · 반박 포인트 · 추가로 확인할 것",
    triggers: "confidential",
    stickiness: "thread",
    expects: [
      "주장을 쟁점별로 쪼개 ① 근거 실재 ② 논리 비약 ③ 우리가 확인할 사실 ④ 반박 근거",
      "상대 서면의 문장을 그대로 옮기지 않는다",
    ],
    form: {
      intro: "상대방 서면·주장을 붙여 넣거나 첨부하면 쟁점별 반박 포인트를 정리합니다.",
      fields: [
        { key: "claim", label: "상대 주장 요지 (선택)", placeholder: "첨부가 있으면 비워 두세요" },
      ],
      build: (v) =>
        "상대방의 주장을 분석해줘.\n\n" +
        `[상대 주장]\n${slot(v.claim, "상대 주장")}\n\n` +
        "주장을 쟁점별로 쪼개고, 각각 ① 인용한 근거가 실재하고 내용이 맞는지 ② 논리 비약이나 " +
        "빠진 요건 ③ 우리가 추가로 확인해야 할 사실 ④ 반박에 쓸 수 있는 조문·판례를 표로 " +
        "정리해줘. 상대 서면 문장을 복사하지 말고, 확인되지 않는 것은 '확인 불가'로 남겨.",
    },
  },
  {
    id: "duty_matrix",
    io: { needs: ["subject"], yields: ["duty", "article", "sanction"] },
    category: "3 분석",
    icon: "fact_check",
    title: "의무 주체 · 기한 · 제재 추출",
    subtitle: "누가 · 언제까지 · 안 하면 얼마",
    expects: [
      "의무마다 주체·행위·기한·제출처·근거조문을 표로",
      "제재는 형사벌·과태료·과징금·행정처분을 **구분**해 별도 표로 — 뭉치지 않음",
      "조문 간 연결(위반→벌칙)은 원문이 명시한 것만, 아니면 '연결 미확인'",
    ],
    form: {
      intro:
        "자문 결론의 뼈대가 되는 표를 만듭니다. 제재 금액·벌칙 연결은 조문 원문이 " +
        "명시한 것만 넣으며, 검증 없이 의견서에 옮기면 안 됩니다.",
      fields: [
        { key: "subject", label: "대상", placeholder: "예: 온라인 식품판매 중개 플랫폼 입점 사업자" },
        { key: "scope", label: "범위 (선택)", placeholder: "예: 영업 개시 전 의무만" },
      ],
      build: (v) =>
        `다음 대상의 법적 의무를 표로 정리해줘.\n\n[대상]\n${slot(v.subject, "대상을 적어 주세요")}` +
        `\n\n[범위]\n${slot(v.scope, "범위")}\n\n` +
        "표 1(의무): ① 의무 주체 ② 해야 할 행위 ③ 기한 ④ 제출처·접수기관 ⑤ 근거 조문.\n" +
        "표 2(제재): 의무별로 형사벌·과태료·과징금·행정처분을 **각각 다른 열**에 적어줘 — " +
        "한 칸에 뭉치지 마. 금액·일수는 조문 원문이 명시한 것만 쓰고, 'A조 위반 → B조 " +
        "벌칙' 연결은 검색 원문이 그 연결을 명시할 때만 적어. 아니면 그 칸은 " +
        "'연결 미확인'으로 비워 두고 추측하지 마.",
    },
  },
  {
    id: "pathway",
    io: { needs: ["subject"], yields: ["duty", "article", "form"] },
    category: "3 분석",
    icon: "checklist",
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
    id: "sanction_level",
    io: { needs: [["duty", "article", "facts"]], yields: ["sanction"] },
    docKinds: ["admrul_attach", "prec"],
    category: "3 분석",
    icon: "scale",
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
    id: "cite_verify",
    io: { needs: [["article", "precedent"]], yields: ["article", "precedent"] },
    category: "3 분석",
    icon: "verified",
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
    id: "deadline_calendar",
    io: { needs: [["duty", "facts", "article"]], yields: ["deadline"] },
    docKinds: ["deadline"],
    category: "4 산출",
    icon: "event",
    title: "기한·절차 일정표",
    subtitle: "언제까지 · 누가 · 어디에 · 근거",
    expects: [
      "기준일부터 계산한 날짜 표 — 기한 · 행위 · 주체 · 제출처 · 근거 조문 · 계산 근거",
      "기산점이 조문에 없으면 '기산점 확인 필요'",
      "기한 계산은 참고용 — 초일·공휴일 규정을 반드시 확인",
    ],
    form: {
      intro: "앞 단계의 의무·사실관계에서 기한을 뽑아 기준일 기준 일정표로 만듭니다.",
      fields: [
        { key: "anchor", label: "기준일 (선택)", placeholder: "예: 2026-10-01 (처분 송달일)" },
      ],
      build: (v) =>
        "기한·절차 일정표를 만들어줘.\n\n" +
        `[기준일]\n${slot(v.anchor, "기준일")}\n\n` +
        "기준일부터 계산한 날짜 · 해야 할 행위 · 주체 · 제출처 · 근거 조문 · 기한 계산 근거(기산점·" +
        "기간)를 표로 정리해줘. 기산점이 조문에 명시되지 않으면 '기산점 확인 필요'로 적고, " +
        "초일 불산입·공휴일 규정이 적용되면 그 조문을 밝혀줘. 날짜를 추정해 채우지 마.",
    },
  },
  {
    id: "form_find",
    io: { needs: ["subject"], yields: ["form", "article"] },
    category: "4 산출",
    icon: "description",
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
    id: "client_brief",
    io: { needs: [["analysis", "issue"]], yields: [] },
    docKinds: ["client"],
    category: "4 산출",
    icon: "record_voice_over",
    title: "의뢰인용 쉬운 설명",
    subtitle: "결론 · 선택지 · 다음 할 일을 비전문가 문장으로",
    expects: [
      "법률 용어를 풀어 쓰고, 선택지별 장단점·비용·기간",
      "다음 할 일 3개",
      "단정적 승패 예측은 하지 않는다 — 변호사가 검토·수정한 뒤 전달하는 초안",
    ],
    form: {
      intro: "앞 단계의 법리 검토 결과를 의뢰인에게 설명할 문장으로 바꿉니다.",
      fields: [
        { key: "tone", label: "형식 (선택)", placeholder: "예: 메일 / 구두 설명 / 문자" },
      ],
      build: (v) =>
        "지금까지의 검토 결과를 의뢰인에게 설명하는 글로 바꿔줘.\n\n" +
        `[형식]\n${slot(v.tone, "형식")}\n\n` +
        "법률 용어는 풀어 쓰고, 가능한 선택지마다 장단점·예상 비용·기간을 적고, 다음 할 일 " +
        "3개로 끝내줘. 승패를 단정하지 말고 '~할 가능성이 있다' 수준으로, 불확실한 부분은 " +
        "불확실하다고 써. 변호사가 검토해 전달할 초안이다.",
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
      "관련 법령이 정한 절차와 기한",
      "근거가 되는 법 조문",
      "변호사·분쟁조정위 등 도움받을 곳",
    ],
    form: {
      intro: "어떤 문제인지 고르면 그 절차와 기한을 안내받을 수 있습니다.",
      fields: [
        {
          key: "issue",
          label: "문제 유형",
          placeholder: "예: 보증금 반환 / 계약 해지 / 수리 책임 / 월세 인상",
        },
        { key: "kind", label: "주택·상가 (선택)", placeholder: "예: 주택 / 상가" },
      ],
      build: (v) =>
        v.issue
          ? `${v.kind ? `${v.kind} ` : ""}임대차에서 "${v.issue}" 문제가 생겼을 때 법령이 정한 절차와 기한, 근거 조문, 도움받을 수 있는 곳을 알려줘.`
          : "임대차 보증금·계약 문제에서 법령이 정한 절차와 기한, 근거 조문, 도움받을 수 있는 곳을 알려줘.",
    },
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
    form: {
      intro: "어떤 문제인지 고르면 신고 절차와 준비 자료를 안내받을 수 있습니다.",
      fields: [
        {
          key: "issue",
          label: "문제 유형",
          placeholder: "예: 임금 체불 / 해고 / 연차·휴가 / 퇴직금",
        },
      ],
      build: (v) =>
        v.issue
          ? `직장에서 "${v.issue}" 문제가 생겼을 때 어디에 어떻게 신고하는지, 근거 조문과 기한, 준비해야 할 자료를 알려줘.`
          : "임금·해고·휴가 문제가 생겼을 때 어디에 어떻게 신고하는지, 근거 조문과 기한, 준비해야 할 자료를 알려줘.",
    },
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
      "이의신청 절차와 법정 기한",
      "법령이 정한 감경·면제 사유 목록(해당 여부는 판단하지 않음)",
      "근거 조문",
    ],
    form: {
      intro: "어떤 처분인지 적으면 이의신청 절차와 기한을 안내받을 수 있습니다.",
      fields: [
        {
          key: "sanction",
          label: "처분 종류",
          placeholder: "예: 과태료 / 영업정지 / 과징금 / 시정명령",
        },
        { key: "field", label: "분야 (선택)", placeholder: "예: 식품 / 교통 / 건축" },
      ],
      build: (v) =>
        v.sanction
          ? `${v.field ? `${v.field} 분야 ` : ""}${v.sanction} 처분을 받았을 때 이의신청 절차와 법정 기한, 법령이 정한 감경·면제 사유 목록, 근거 조문을 알려줘.`
          : "과태료·행정처분을 받았을 때 이의신청 절차와 법정 기한, 법령이 정한 감경·면제 사유 목록, 근거 조문을 알려줘.",
    },
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
    icon: "track_changes",
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
    id: "doc_review",  // 모니터링 모드 — 관점 기본값 "규제 추출"
    io: { needs: ["doc"], yields: ["issue", "article", "duty"] },
    category: "자료 검토",
    icon: "attach_file",
    stickiness: "thread",   // 첨부가 기밀을 켠다 — 역시 스레드 단위
    title: "문서 첨부해 검토",
    subtitle: "적합성 · 내규↔법령 갭 · 규제 추출 · 위험 조항 — 관점 선택",
    triggers: "attach",
    expects: [
      "관점에 따라 적합성 검토 / 내규 조항별 갭 표 / 걸리는 규제 목록 / 위험 조항 지적",
      "첨부 즉시 기밀 모드가 켜져 외부로 나가지 않음",
      "지적마다 근거 조문 제시",
    ],
    form: {
      intro: "파일 선택창이 열립니다. 문서를 고르면 기밀 모드가 함께 켜집니다.",
      fields: [
        {
          key: "perspective",
          label: "관점 (선택)",
          placeholder: "규제 추출(기본) / 적합성 검토 / 내규↔법령 갭 / 위험 조항",
        },
        { key: "ask", label: "특히 볼 것 (선택)", placeholder: "예: 개인정보 처리 조항이 현행법에 맞는지" },
      ],
      build: (v) => {
        const p = (v.perspective ?? "").trim() || "규제 추출";
        const ask = v.ask?.trim() ? ` 특히: ${v.ask.trim()}.` : "";
        if (/갭|내규/.test(p)) {
          return "첨부한 내부 규정이 현행 법령을 반영하고 있는지 점검해줘." + ask + "\n\n" +
            "규정 조항 ↔ 근거 법령 ↔ 상태(일치·미반영·충돌·근거없음)를 표로 정리하고, " +
            "미반영·충돌이면 고쳐야 할 문구를 제안해줘. 근거 조문을 못 찾은 항목은 " +
            "'근거 미확인'으로 남기고 추측하지 마.";
        }
        if (/추출|걸리는|규제/.test(p)) {
          return "첨부한 문서가 걸리는 법령·행정규칙·조례를 뽑아줘." + ask + "\n\n" +
            "문서의 어느 부분이 어느 조문에 걸리는지 짝지어 표로 만들고, 각 규제가 무엇을 " +
            "요구하는지 한 줄로 요약해줘. 근거 조문을 함께 달아줘.";
        }
        if (/위험|리스크/.test(p)) {
          return "첨부한 문서에서 법적 위험이 있는 조항을 짚어줘." + ask + "\n\n" +
            "조항별로 위험의 내용·근거 조문·완화 방안을 표로 정리해줘. 근거 없는 조항은 " +
            "'근거 미확인'으로 남겨.";
        }
        return `첨부한 문서를 검토해줘.${ask || " 규제 적합성과 누락 조항을 봐줘."} ` +
          "문제가 되는 부분은 근거 조문과 함께 짚어줘.";
      },
    },
  },
  {
    id: "impact_graph",
    io: { needs: ["article"], yields: ["article"] },
    docKinds: ["impact"],
    category: "영향 분석",
    icon: "hub",
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
  {
    id: "mon_watch",
    category: "변경 추적",
    icon: "notifications_active",
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
  io: { needs: [["issue", "analysis"], "article"], yields: [] },
  category: "4 산출",
  icon: "draft",
  title: "서면 초안 만들기",
  subtitle: "의견서 · 검토 보고 · 내용증명 · 답변서 · 질의서",
  triggers: "brief",
  expects: [
    "지금까지의 대화와 그 인용으로 서면 골격 생성 — 종류별 구성",
    "문단을 눌러 그 문단만 고쳐 쓰기",
    "연계에서는 **마지막 단계**로만 — 종합이 곧 서면의 재료",
  ],
  form: {
    intro: "서면 종류를 고르면 그 구성으로 초안을 엽니다. 연계의 마지막 단계로 넣을 수 있습니다.",
    fields: [
      { key: "kind", label: "서면 종류 (선택)", placeholder: "의견서(기본) / 검토 보고 / 내용증명 / 답변서 / 질의서" },
    ],
    // 패널의 '바로 실행'·연계 종점은 턴을 보내지 않고 OPEN_BRIEF_EVENT 를 쏜다(PageShell).
    build: (v) => `서면 초안(${(v.kind ?? "").trim() || "의견서"})`,
  },
  availableWhen: (ctx) => ctx.mode !== "public" && ctx.hasTurns,
};

export type BriefKind = "opinion" | "review" | "demand" | "answer" | "inquiry";

/** 서면 종류 — 폼 입력(자유 문자열)을 백엔드 `BRIEF_KINDS` 키로. */
export function briefKindOf(v: string | undefined): BriefKind {
  const t = (v ?? "").trim();
  if (/검토|보고/.test(t)) return "review";
  if (/내용증명|통지|최고/.test(t)) return "demand";
  if (/답변|반박|준비서면/.test(t)) return "answer";
  if (/질의|문의/.test(t)) return "inquiry";
  return "opinion";
}

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
    [f.title, f.subtitle, f.category, ...(f.expects ?? [])].some((s) => s.toLowerCase().includes(t)),
  );
}
