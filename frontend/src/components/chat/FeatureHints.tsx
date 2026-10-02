"use client";

/**
 * FeatureHints — "이 대화에서 쓸 수 있는 기능" 안내 (2026-10-01).
 *
 * 기능을 전부 채팅 안에서 처리하기로 한 대가로, 사용자는 **무엇을 쓸 수 있는지
 * 알 길이 없다**. 버튼이 없으니 발견도 안 된다. 그래서 새 대화 화면에서 한 번
 * 명시적으로 보여 준다(사용자 요구, 2026-10-01).
 *
 * 안내만 한다 — 누르면 동작하는 버튼이 아니다. 각 기능은 질문 내용이나 첨부에
 * 따라 자동으로 붙는다(그게 "채팅 안에서 다 된다"의 의미다). 자동으로 켜지는
 * 보호 모드는 `auto` 로 표시해 예고한다.
 */

type Hint = {
  icon: string;
  title: string;
  desc: string;
  /** 자동으로 켜지는 기능 — 사용자가 고르지 않아도 적용된다 */
  auto?: string;
};

const PUBLIC_HINTS: Hint[] = [
  {
    icon: "checklist",
    title: "절차 경로 안내",
    desc: "무엇을 · 어디에 · 어떤 서류로 내는지 단계로 정리해 드립니다.",
  },
  {
    icon: "format_quote",
    title: "근거 조문 표시",
    desc: "답변의 문장마다 어떤 조문에서 나왔는지 번호로 확인할 수 있습니다.",
  },
  {
    icon: "shield_person",
    title: "개인정보 보호",
    desc: "질문에 이름 · 연락처 · 주민등록번호가 섞이면 가려서 처리합니다.",
    auto: "자동",
  },
];

const EXPERT_HINTS: Hint[] = [
  {
    icon: "checklist",
    title: "규제 경로 분해",
    desc: "신고 · 허가 · 보고 의무를 기한과 서식까지 체크리스트로 분해합니다.",
  },
  {
    icon: "description",
    title: "서식 · 별표 작성",
    desc: "조문에 딸린 서식을 이 화면에서 채우고 원본 형식으로 내려받습니다.",
  },
  {
    icon: "lock",
    title: "기밀 모드",
    desc: "사건 파일 · 의뢰인 사실관계는 원내 모델로만 처리하고 웹 검색을 쓰지 않습니다.",
    auto: "문서 첨부 · 서식 작성 시 자동",
  },
  {
    // 2026-10-01: 종전 "인용 네트워크 · 심층 보고서". 인용 네트워크는 진입점이
    // 꺼져 있다(TurnAnswer.LAW_GRAPH_ENABLED, 2026-08-03) — 안내에서 뺀다.
    // 없는 기능을 안내하면 첫 오류 1건으로 신뢰가 끝난다.
    icon: "auto_stories",
    title: "심층 보고서",
    desc: "쟁점별로 근거를 모아 보고서를 백그라운드로 작성합니다. 기다릴 필요 없이 대화를 이어가세요.",
  },
];

const MONITOR_HINTS: Hint[] = [
  {
    icon: "search",
    title: "대화로 규제 찾기",
    desc: "모니터링할 대상을 적으면 걸리는 법령 · 고시 · 조례를 찾아 드립니다.",
  },
  {
    icon: "visibility",
    title: "관찰 목록에 담기",
    desc: "찾은 근거 중 담을 것만 고르세요 — 자동으로 넣지 않습니다.",
    auto: "직접 선택",
  },
  {
    icon: "notifications",
    title: "변경 알람",
    desc: "폐지 · 개정예정 · 시행일 변경을 감지해 쌓습니다. 알람만 모아 볼 수 있습니다.",
  },
  {
    icon: "mail",
    title: "보고서 · 발송",
    desc: "변경을 짧은 보고서로 만들어 주소록에서 고른 사람에게 보냅니다.",
  },
];

export function FeatureHints({
  pro,
  monitor = false,
}: {
  pro: boolean;
  monitor?: boolean;
}) {
  const hints = monitor ? MONITOR_HINTS : pro ? EXPERT_HINTS : PUBLIC_HINTS;

  return (
    <section
      data-testid="feature-hints"
      className="w-full max-w-[560px] rounded-[12px] border border-md-outline-variant/70 bg-md-surface-container-lowest px-4 py-3.5"
    >
      <h2 className="flex items-center gap-1.5 text-[12.5px] font-semibold text-md-on-surface-variant">
        <span className="material-symbols-outlined text-[15px] text-md-primary" aria-hidden>
          auto_awesome
        </span>
        {monitor ? "이 대상에서 할 수 있는 일" : "이 대화에서 바로 쓸 수 있는 기능"}
      </h2>

      <ul className="mt-2.5 flex flex-col gap-2.5">
        {hints.map((h) => (
          <li key={h.title} className="flex gap-2.5">
            <span
              className="material-symbols-outlined mt-[1px] text-[16px] text-md-on-surface-variant/70"
              aria-hidden
            >
              {h.icon}
            </span>
            <span className="min-w-0">
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="text-[13px] font-medium text-md-on-surface">{h.title}</span>
                {h.auto ? (
                  <span className="rounded-[4px] bg-md-primary-container px-1.5 py-[1px] text-[10.5px] font-medium text-md-on-primary-container">
                    {h.auto}
                  </span>
                ) : null}
              </span>
              <span className="mt-0.5 block text-[12px] leading-[1.6] text-md-on-surface-variant">
                {h.desc}
              </span>
            </span>
          </li>
        ))}
      </ul>

      <p className="mt-3 border-t border-md-outline-variant/70 pt-2.5 text-[11.5px] leading-[1.6] text-md-on-surface-variant/80">
        {monitor
          ? "먼저 무엇을 모니터링할지 물어보세요. 찾은 근거를 담으면 추적이 시작됩니다."
          : "따로 켤 것은 없습니다 — 질문하시면 필요한 기능이 알아서 붙습니다."}
        {pro && !monitor ? " 보호 모드가 켜지면 입력창 위에 표시됩니다." : ""}
      </p>
    </section>
  );
}
