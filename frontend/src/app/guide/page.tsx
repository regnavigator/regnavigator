/**
 * /guide — 서비스 이용 매뉴얼 (공개 라우트).
 *
 * 정본: medi-back `local/사용자매뉴얼_최종_20260821.docx` + 그 이후 추가 기능
 * (서류 작성·원본 서식 다운로드·보고서 분량 확대·급여기준 검색 — 2026-08-26).
 *
 * docx 매뉴얼은 배포마다 갱신이 늦고 사용자가 파일을 받아야 한다. 화면 안에서
 * 바로 읽히도록 페이지로 옮긴다. 사이드바 [이용 안내](FeatureTour)가 30초
 * 투어라면, 이 페이지는 **찾아보는 레퍼런스**다 — 목차·앵커로 특정 기능만
 * 바로 열람.
 *
 * theme 토큰만 사용(raw hex 금지).
 */

import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { SiteNav } from "@/components/shell/SiteNav";

export const metadata: Metadata = {
  title: "이용 안내 · RegNavigator",
  description:
    "RegNavigator 사용법 — 질문하기, IRB·DRB 심의 확인, 근거 확인, 심층 보고서, 서류 작성까지.",
};

type Section = {
  id: string;
  title: string;
  lead?: string;
  blocks: Block[];
};

type Block =
  | { kind: "steps"; items: { t: string; d: string }[] }
  | { kind: "list"; items: { t: string; d: string }[] }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "note"; tone: "info" | "warn"; text: string }
  | { kind: "shot"; src: string; alt: string; caption: string };

const SECTIONS: Section[] = [
  {
    id: "start",
    title: "시작하기",
    lead: "가입부터 첫 질문까지 3분이면 됩니다.",
    blocks: [
      {
        kind: "steps",
        items: [
          {
            t: "회원가입",
            d: "초대 링크를 받은 이메일로 가입합니다. 이메일 인증 후 비밀번호를 설정하면 완료됩니다. 이름·직업·소속은 선택 입력입니다.",
          },
          {
            t: "로그인",
            d: "이메일과 비밀번호로 로그인합니다. 비밀번호 없이 이메일 링크로 로그인할 수도 있고, 잊었다면 재설정할 수 있습니다.",
          },
          {
            t: "새 대화 시작",
            d: "왼쪽 사이드바의 [새 대화]를 누르고 질문을 입력합니다. 이전 대화는 사이드바에 최근순으로 남고, 고정한 대화가 맨 위에 옵니다.",
          },
        ],
      },
      {
        kind: "shot",
        src: "/guide/signup.webp",
        alt: "회원가입 화면 — 이메일과 동의 항목 입력",
        caption: "회원가입 — 초대받은 이메일로 가입하고 약관에 동의합니다.",
      },
      {
        kind: "shot",
        src: "/guide/login.webp",
        alt: "로그인 화면 — 이메일·비밀번호 입력",
        caption: "로그인 — 비밀번호 없이 이메일 링크로도 들어올 수 있습니다.",
      },
      {
        kind: "note",
        tone: "info",
        text:
          "앱처럼 쓰기 — Chrome 주소창 우측의 설치 아이콘을 누르면 별도 설치 파일 없이 앱으로 사용할 수 있습니다(Mac·Windows 모두).",
      },
    ],
  },
  {
    id: "ask",
    title: "질문하기",
    lead: "전문 용어를 몰라도 됩니다. 평소 말하듯 물어보세요.",
    blocks: [
      {
        kind: "list",
        items: [
          {
            t: "자연어로 질문",
            d: "정확한 법령명이나 조문 번호를 몰라도 질문의 의도를 파악해 답합니다. 질문이 모호하면 AI가 먼저 되묻습니다.",
          },
          {
            t: "가이드 카드로 시작",
            d: "첫 화면의 예시 질문(품목허가·연구 심의 등)을 누르면 질문을 다듬는 창이 열립니다. 카드의 입력란은 선택 — [이 질문으로 시작]을 누르면 질문이 입력창에 채워지고, 확인 후 보내면 됩니다.",
          },
          {
            t: "이어서 질문",
            d: "답변 아래에 맥락에 맞는 후속 질문이 제안됩니다. 클릭하면 바로 이어서 물어봅니다.",
          },
          {
            t: "답변 수준 선택",
            d: "입력창 우측에서 기본 / 전문가 / 쉬움을 고를 수 있습니다. 전문가 모드는 조문 표현을 그대로 살려 RA·QA 실무에 맞춥니다.",
          },
          {
            t: "파일 첨부",
            d: "📎 버튼으로 문서를 붙여 질문할 수 있습니다. PDF(텍스트)·DOCX·HWPX·TXT·MD·CSV를 지원합니다(한 번에 3개, 파일당 15MB). 구형 HWP·DOC·스캔 PDF는 HWPX·DOCX·PDF로 저장한 뒤 올려 주세요.",
          },
          {
            t: "답변 복사·내보내기",
            d: "답변 아래 버튼으로 전문을 복사하거나, 인용 목록과 함께 Word 파일로 내려받습니다.",
          },
        ],
      },
      {
        kind: "shot",
        src: "/guide/chat.webp",
        alt: "채팅 화면 — 자연어 질문과 답변",
        caption: "채팅 화면 — 평소 말하듯 물으면 근거와 함께 답합니다.",
      },
      {
        kind: "note",
        tone: "info",
        text:
          "개인정보 자동 보호 — 질문에 이름·연락처·주소가 있으면 AI에 전달되기 전에 자동으로 가려집니다(예: [이름]). 가려진 항목은 화면에 알려드립니다.",
      },
    ],
  },
  {
    id: "irb",
    title: "연구 심의 (IRB·DRB)",
    lead:
      "내 연구가 심의 대상인지, 면제·신속·정규 중 어디인지 — 기관 지침 기준으로 예비판정하고 절차·서식까지 안내합니다.",
    blocks: [
      {
        kind: "steps",
        items: [
          {
            t: "진입",
            d: "첫 화면의 [연구 심의 대상인지 확인하기] 카드를 누르거나, 채팅에 연구 개요를 적으면 됩니다. 개요 입력은 선택 — 비워도 판정 기준부터 안내합니다.",
          },
          {
            t: "예비판정",
            d: "연구 설계(후향적/전향적, 대상, 데이터)를 바탕으로 심의면제 · 신속심의 · 정규심의 중 어디에 해당하는지 근거 조항과 함께 판정합니다.",
          },
          {
            t: "DRB(의료데이터 심의) 확인",
            d: "병원 의료데이터(EMR·검사결과·잔여검체)를 쓰는 연구는 IRB와 별도로 DRB 심의 대상 여부를 함께 확인합니다.",
          },
          {
            t: "절차·서류 안내",
            d: "해당 판정에 맞는 신청 절차, 제출 서류 목록, 유의사항을 안내합니다. 심의 의뢰서 등 제출 서류는 서류 작성 기능으로 이어서 완성할 수 있습니다.",
          },
        ],
      },
      {
        kind: "note",
        tone: "info",
        text:
          "판정 기준: 화순전남대학교병원 IRB·DRB 지침. 기관 내부 규정 원문은 그대로 노출하지 않고, 해당 조항 위치와 요지만 안내합니다.",
      },
      {
        kind: "note",
        tone: "warn",
        text:
          "AI의 예비판단입니다. 최종 심의 대상 여부와 유형은 소속 기관 IRB·DRB 사무국의 판단을 따릅니다.",
      },
    ],
  },
  {
    id: "evidence",
    title: "답변과 근거 읽기",
    lead: "모든 답변에는 근거가 붙고, 그 근거는 원문과 대조됩니다.",
    blocks: [
      {
        kind: "steps",
        items: [
          {
            t: "질문 분석",
            d: "개인정보를 가린 뒤, 규제 질문인지 일반 대화인지 판정합니다.",
          },
          {
            t: "근거 수집",
            d: "법령·고시·판례·해석례·가이드라인과 웹을 함께 검색합니다. 규제 질문이면 이 검색은 생략되지 않습니다.",
          },
          {
            t: "답변 작성",
            d: "수집한 근거로 답을 쓰면서 문장마다 [n] 인용을 붙입니다.",
          },
          {
            t: "근거 검증",
            d: "답변이 끝나면 각 인용을 법령 원문과 대조해 ✓ 표시를 붙이고, 통과 비율을 신뢰도 배지로 보여줍니다.",
          },
        ],
      },
      {
        kind: "table",
        head: ["신뢰도 배지", "의미", "권장 행동"],
        rows: [
          ["높음 (녹색)", "인용의 80% 이상이 법령 원문·공공기관 출처로 검증됨", "그대로 활용 가능"],
          ["보통 (황색)", "인용의 30~79%가 검증됨 — 일부 미검증이거나 민간 출처 포함", "핵심 내용은 원문 확인"],
          ["낮음 (적색)", "검증된 인용이 30% 미만 — 다수가 원문에서 직접 확인되지 않음", "반드시 원문 재확인"],
        ],
      },
      {
        kind: "list",
        items: [
          {
            t: "조문 시행 상태",
            d: "인용된 조문에 시행 예정(아직 효력 없음) · 개정 예정(곧 바뀜) · 구법/폐지 배지가 붙습니다.",
          },
          {
            t: "출처 상세 보기",
            d: "본문의 [n]을 클릭하면 오른쪽에 출처 패널이 열립니다. 원문 링크와 조문 본문을 함께 볼 수 있습니다.",
          },
          {
            t: "별표·서식 원본",
            d: "별표나 서식이 근거로 쓰이면 국가법령정보센터의 HWP 원본을 바로 내려받고, [이 서식으로 작성]으로 그 자리에서 채울 수도 있습니다.",
          },
          {
            t: "근거 저장·알림",
            d: "인용 옆 북마크 아이콘(근거 라이브러리에 저장)으로 조문·판례·서식을 저장합니다. 저장한 법령 조문이 개정·폐지되면 알림(🔔)과 목록의 개정 배지로 알려드립니다(판례·서식은 개정 알림 대상이 아닙니다) — 한 번 열람하면 배지가 '확인함'으로 바뀌고, 개정 상태가 또 바뀌면 다시 강조됩니다.",
          },
        ],
      },
      {
        kind: "shot",
        src: "/guide/answer.webp",
        alt: "답변 화면 — 신뢰도 배지와 인라인 출처 뱃지",
        caption: "답변 상단의 신뢰도 배지와 문장별 출처 뱃지.",
      },
      {
        kind: "shot",
        src: "/guide/citation-panel.webp",
        alt: "인용을 클릭해 열린 출처 상세 패널",
        caption: "인용 [n]을 클릭하면 오른쪽에 원문과 링크가 열립니다.",
      },
      {
        kind: "shot",
        src: "/guide/sources.webp",
        alt: "답변 하단 출처 목록과 피드백 아이콘",
        caption: "답변 하단 — 출처 목록과 만족도·신고 버튼.",
      },
    ],
  },
  {
    id: "report",
    title: "심층 보고서",
    lead:
      "한 주제로 여러 번 대화한 뒤, 그 대화 전체를 바탕으로 체계적인 보고서를 만듭니다.",
    blocks: [
      {
        kind: "list",
        items: [
          {
            t: "요청 방법",
            d: "대화를 진행한 뒤 입력창 아래 [심층 보고서]를 누르고 목적(종합·허가 전략·규제 요약·변경 대응)을 고릅니다. 근거 인용이 있는 답변이 한 번 이상 있어야 하고, 대화당 한 번에 하나씩 생성됩니다.",
          },
          {
            t: "구성",
            d: "개요 → 주제에 맞춘 본론 2~5개 → 결론 및 권고 순서로, 문장마다 인용이 붙습니다. 상단에 목차와 작성 기준일이 표시됩니다.",
          },
          {
            t: "생성 시간",
            d: "백그라운드에서 보통 5~20분, 길면 1시간 걸립니다. 그동안 질문을 계속할 수 있고, 진행 상황은 우측 패널에 표시됩니다.",
          },
          {
            t: "받아보기",
            d: "완료되면 알림과 함께 가입 이메일로 Word 파일이 첨부되어 옵니다([심층 보고서] 창의 “완료 시 이메일로 받기”로 끌 수 있음). 사이드바 [심층 보고서]와 우측 패널에서도 볼 수 있습니다 — 대화창에는 나오지 않습니다.",
          },
          {
            t: "삭제",
            d: "목록에서 보고서 카드에 마우스를 올리면 🗑 삭제 버튼이 나타납니다. 삭제하면 본문 파일까지 지워지며 복구되지 않습니다. 보고서는 만든 지 30일이 지나면 자동으로 삭제되니, 계속 쓸 보고서는 메일로 받은 Word 파일을 보관해 주세요.",
          },
        ],
      },
      {
        kind: "note",
        tone: "info",
        text:
          "진행 표시가 “대기 중”이면 다른 보고서가 먼저 작성되는 중입니다. 순서가 되면 자동으로 시작되니 기다리시면 됩니다.",
      },
      {
        kind: "note",
        tone: "warn",
        text:
          "근거가 충분하지 않으면 부정확한 보고서를 내지 않기 위해 생성이 중단될 수 있습니다. 질문을 조금 더 구체화해 다시 시도해 주세요.",
      },
      {
        kind: "shot",
        src: "/guide/report-start.webp",
        alt: "심층 보고서 생성 화면",
        caption: "보고서 요청 — 이어서 물어볼 만한 주제도 함께 제안됩니다.",
      },
      {
        kind: "shot",
        src: "/guide/report-body.webp",
        alt: "심층 보고서 본문 — 표와 인용 마커",
        caption: "완성된 보고서 — 표와 문장별 인용으로 정리됩니다.",
      },
    ],
  },
  {
    id: "document",
    title: "서류 작성",
    lead:
      "검색으로 찾은 관보 서식을 그 자리에서 채워, 원본 파일 그대로 내려받습니다.",
    blocks: [
      {
        kind: "steps",
        items: [
          {
            t: "서식 선택",
            d: "답변의 별표·서식 인용을 열고 [이 서식으로 작성]을 누르면, 확인한 바로 그 서식의 작성 화면이 몇 초 만에 열립니다.",
          },
          {
            t: "작성 화면",
            d: "왼쪽에는 서식의 기입 항목이, 오른쪽에는 작성 도우미 대화가 나란히 열립니다. 창 크기는 오른쪽 아래 모서리를 끌어 조절할 수 있습니다.",
          },
          {
            t: "도우미와 대화로 채우기",
            d: "도우미가 필요한 항목을 안내합니다. “대표자는 홍길동이고 연락처는 02-555-0100입니다”처럼 답하면 왼쪽 서식이 그 자리에서 채워집니다. 무엇을 써야 할지 모르면 물어보세요.",
          },
          {
            t: "직접 입력·자동 작성",
            d: "항목을 클릭하면 그 칸에서 바로 입력할 수 있고(Enter 저장), ✨ 버튼은 대화 내용을 근거로 AI가 채웁니다. 근거가 부족하면 지어내지 않고 비워 둡니다. 이미 채운 값도 대화로 고칠 수 있습니다.",
          },
          {
            t: "문서 첨부로 한 번에",
            d: "도우미 대화의 📎 버튼으로 사업자등록증·기존 신청서 같은 문서를 붙이면, 그 안의 값(상호·주소 등)을 추출해 해당 칸에 채워줍니다.",
          },
          {
            t: "원본 그대로 내보내기",
            d: "관보에 실린 원본 파일(.hwp 또는 .hwpx — 원본 형식 그대로)에 작성한 값만 채워 내려받습니다 — 모양·서식이 바뀌지 않은 제출용 파일입니다. 다 채우지 않아도 내보낼 수 있고, 빈 칸은 [확인 필요] 표시로 남습니다.",
          },
          {
            t: "다시 열기",
            d: "작성 중에 화면을 닫아도 값은 저장돼 있습니다. 채팅 입력창 위의 “작성 중인 서류” 표시나 사이드바 [작성한 서식]에서 언제든 이어서 작성합니다. [관리] 창에서 별명·보관·삭제를 할 수 있고, 대화를 지우면 그 대화의 서식도 함께 지워집니다 — 계속 쓸 서식은 [보관]해 두세요.",
          },
        ],
      },
      {
        kind: "note",
        tone: "info",
        text:
          "도우미와의 대화는 저장되지 않고, 이름·연락처 같은 개인정보는 외부 AI가 아닌 원내 서버의 AI만 처리합니다. 일반 채팅 기록에서는 개인정보가 가려진 채 보관됩니다.",
      },
      {
        kind: "note",
        tone: "warn",
        text:
          "AI가 채운 초안입니다. 제출 전에 반드시 담당자가 검토하세요. 기관 자체 서식(병원 내부 양식 등)은 관보 원본이 없어 화면의 내용을 참고해 작성해야 합니다.",
      },
    ],
  },
  {
    id: "coverage",
    title: "무엇을 찾을 수 있나",
    blocks: [
      {
        kind: "table",
        head: ["구분", "내용"],
        rows: [
          ["법령", "법·시행령·시행규칙 (현행본과 시행예정본을 함께 보관)"],
          ["행정규칙", "고시·훈령·예규"],
          ["급여기준·심사지침", "고시 본문이 아니라 첨부에만 있는 세부 기준까지"],
          ["별표·서식", "제출 서류 양식과 기준표 — HWP 원본 제공"],
          ["판례·해석례", "법원 판례와 법제처 유권해석"],
          ["가이드라인", "식약처 안내서·민원인 안내서"],
          ["웹", "공고·해외 규제 동향 등 최신 정보"],
        ],
      },
      {
        kind: "note",
        tone: "info",
        text:
          "법령 데이터는 매일 새벽 자동으로 갱신됩니다. 개정되면 그 내용이 반영되고, 저장해 둔 근거가 바뀌면 알림이 갑니다.",
      },
    ],
  },
  {
    id: "etc",
    title: "그 밖의 기능",
    blocks: [
      {
        kind: "list",
        items: [
          { t: "대화 검색", d: "사이드바 검색창에서 과거 대화를 제목·내용으로 찾습니다(내용은 2자 이상). 검색어가 든 문장까지 보려면 Ctrl+K를 쓰세요." },
          { t: "대화 고정", d: "대화 오른쪽 ⋮ 메뉴의 [상단 고정]으로 목록 맨 위에 고정합니다." },
          { t: "빠른 이동", d: "Ctrl+K(Mac ⌘K)로 대화 검색·새 대화·저장한 근거를 바로 열고, 최근 본 조문의 원문을 엽니다." },
          { t: "화면 테마", d: "우측 하단 버튼으로 화면 색상 테마를 바꿉니다." },
          { t: "만족도·피드백", d: "답변 아래 👍/👎로 품질을 평가하고, [피드백]으로 버그·요청을 보냅니다. 잘못된 인용은 본문의 [n] 번호를 눌러 뜨는 창의 [이 인용 신고]로 알려주세요." },
          { t: "업데이트 안내", d: "새 기능이 추가되면 접속 시 팝업으로 알려드립니다." },
        ],
      },
    ],
  },
];

/* ─────────────────── 렌더 ─────────────────── */

function NoteBox({ tone, text }: { tone: "info" | "warn"; text: string }) {
  const warn = tone === "warn";
  return (
    <div
      className={
        "mt-4 flex gap-2.5 rounded-card border p-3.5 " +
        (warn
          ? "border-md-tertiary/40 bg-md-tertiary-fixed/30"
          : "border-md-outline-variant bg-md-surface-container-low")
      }
    >
      <span
        className={
          "material-symbols-outlined shrink-0 text-[18px] " +
          (warn ? "text-md-tertiary" : "text-md-primary")
        }
        aria-hidden
      >
        {warn ? "warning" : "info"}
      </span>
      <p className="text-[13.5px] leading-relaxed text-md-on-surface-variant">
        {text}
      </p>
    </div>
  );
}

function Shot({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <figure className="mt-6">
      <div className="overflow-hidden rounded-card border border-md-outline-variant bg-md-surface-container-lowest">
        <Image
          src={src}
          alt={alt}
          width={1547}
          height={784}
          sizes="(max-width: 980px) 100vw, 980px"
          className="h-auto w-full"
        />
      </div>
      <figcaption className="mt-2 text-[12.5px] text-md-on-surface-variant">
        {caption}
      </figcaption>
    </figure>
  );
}

function BlockView({ block }: { block: Block }) {
  if (block.kind === "shot") {
    return <Shot src={block.src} alt={block.alt} caption={block.caption} />;
  }
  if (block.kind === "note") {
    return <NoteBox tone={block.tone} text={block.text} />;
  }
  if (block.kind === "table") {
    return (
      <div className="mt-5 overflow-x-auto rounded-card border border-md-outline-variant">
        <table className="min-w-full text-left text-[13.5px]">
          <thead className="bg-md-surface-container-low text-[12px] uppercase tracking-wide text-md-on-surface-variant">
            <tr>
              {block.head.map((h) => (
                <th key={h} className="whitespace-nowrap px-4 py-2.5 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((r, i) => (
              <tr key={i} className="border-t border-md-outline-variant align-top">
                {r.map((cell, j) => (
                  <td
                    key={j}
                    className={
                      "px-4 py-3 leading-relaxed " +
                      (j === 0
                        ? "whitespace-nowrap font-medium text-md-on-surface"
                        : "text-md-on-surface-variant")
                    }
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  const numbered = block.kind === "steps";
  return (
    <ol className="mt-6 space-y-0 divide-y divide-md-outline-variant/50">
      {block.items.map((it, i) => (
        <li key={it.t} className="flex gap-3.5 py-4 first:pt-0 last:pb-0">
          <span
            className={
              "flex size-7 shrink-0 items-center justify-center rounded-full text-[12.5px] font-bold " +
              (numbered
                ? "bg-md-primary text-md-on-primary"
                : "bg-md-surface-container text-md-primary")
            }
            aria-hidden
          >
            {numbered ? i + 1 : "•"}
          </span>
          <div className="min-w-0">
            <p className="text-[14.5px] font-semibold text-md-on-surface">{it.t}</p>
            <p className="mt-1 text-[13.5px] leading-relaxed text-md-on-surface-variant">
              {it.d}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function GuidePage() {
  return (
    <main className="min-h-screen bg-md-surface text-md-on-surface">
      {/* 상단 nav — 공개 페이지 공통(SiteNav, sticky h-16). 아래 목차 sticky 는
          이 높이 아래(top-16)에 붙는다. */}
      <SiteNav />

      <div className="mx-auto max-w-[980px] px-6 py-12">
        <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-md-on-surface-variant">
          User Guide
        </p>
        <h1
          className="mt-3 text-[34px] font-bold leading-tight sm:text-[42px]"
          style={{ letterSpacing: "-0.025em" }}
        >
          이용 안내
        </h1>
        <p className="mt-4 max-w-[640px] text-[15px] leading-relaxed text-md-on-surface-variant">
          질문하는 법부터 연구 심의(IRB·DRB), 근거 확인, 심층 보고서, 서류 작성까지 —
          필요한 기능만 골라 보세요.
        </p>

        {/* 목차 — sticky(2026-08-27): 스크롤 중에도 상단에 붙어 어느
            챕터든 바로 이동. hover 시 강조. */}
        <nav
          aria-label="목차"
          // 일자 한 줄(줄바꿈 없이 가로 스크롤) + 불투명 배경(2026-08-27 지적:
          // 줄바꿈된 칩 뭉치 + 반투명 배경이 어색). -mx-6 = 컨테이너 px-6 를
          // 상쇄해 배경이 가장자리까지 찬다. 스크롤바는 숨김(칩 잘림이 힌트).
          className="sticky top-16 z-20 -mx-6 mt-8 flex flex-nowrap items-center gap-2 overflow-x-auto border-b border-md-outline-variant bg-md-surface px-6 py-3 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {SECTIONS.map((s, i) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="shrink-0 whitespace-nowrap rounded-pill border border-md-outline-variant bg-md-surface-container-low px-3 py-1 text-[12.5px] font-medium text-md-on-surface transition-colors hover:border-md-primary hover:bg-md-primary-container/40 hover:text-md-primary"
            >
              {i + 1}. {s.title}
            </a>
          ))}
        </nav>

        {/* 본문 — 챕터를 카드로 분리(2026-08-27 "다닥다닥" 지적): 배경·테두리
            로 경계를 만들고, 제목 아래 구분선·블록 간 여백을 넉넉히. */}
        <div className="mt-14 space-y-10">
          {SECTIONS.map((s, i) => (
            <section
              key={s.id}
              id={s.id}
              className="scroll-mt-32 rounded-card border border-md-outline-variant bg-md-surface-container-lowest p-6 sm:p-8"
            >
              <div className="flex items-baseline gap-3 border-b border-md-outline-variant pb-4">
                <span className="text-[13px] font-bold tabular-nums text-md-primary">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h2
                  className="text-[24px] font-bold leading-snug"
                  style={{ letterSpacing: "-0.02em" }}
                >
                  {s.title}
                </h2>
              </div>
              {s.lead ? (
                <p className="mt-4 text-[14.5px] leading-relaxed text-md-on-surface-variant">
                  {s.lead}
                </p>
              ) : null}
              <div className="space-y-7">
                {s.blocks.map((b, j) => (
                  <BlockView key={j} block={b} />
                ))}
              </div>
            </section>
          ))}
        </div>

        {/* 푸터 */}
        <footer className="mt-20 border-t border-md-outline-variant pt-8">
          <p className="text-[13.5px] leading-relaxed text-md-on-surface-variant">
            RegNavigator는 규제 조사를 돕는 도구입니다. 최종 판단과 제출 책임은
            이용자에게 있으며, 중요한 사안은 반드시 원문과 관할 기관 안내를
            확인하세요.
          </p>
          <div className="mt-5 flex flex-wrap gap-4 text-[13px]">
            <Link href="/landing" className="text-md-primary hover:underline">
              서비스 소개
            </Link>
            <Link href="/terms" className="text-md-primary hover:underline">
              이용약관
            </Link>
            <Link href="/privacy" className="text-md-primary hover:underline">
              개인정보처리방침
            </Link>
          </div>
        </footer>
      </div>
    </main>
  );
}
