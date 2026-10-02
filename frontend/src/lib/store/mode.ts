/**
 * 앱 모드 — 진입 경로 3종 (2026-10-01).
 *
 * `/start` 에서 한 번 고르면 브라우저에 기억되고, 사이드바에서 언제든 바꾼다.
 * 모드는 **프런트 상태**다 — 백엔드 계약은 그대로이고, 채팅 어투만 기존
 * `style` 파라미터(`expert`|`simple`)로 매핑해 보낸다.
 *
 * 저장은 localStorage. 서버(미들웨어)는 모드를 모르므로 `/` 는 항상 `/start` 로
 * 보내고, `/start` 가 클라이언트에서 저장값을 보고 각 경로로 넘긴다.
 */

export type AppMode = "public" | "expert" | "monitor";

const KEY = "regnav_mode";

/** 모드 변경 브로드캐스트 — 같은 탭의 다른 컴포넌트 동기화용. */
export const MODE_CHANGED_EVENT = "regnav-mode-changed";

export const MODE_META: Record<
  AppMode,
  { label: string; short: string; icon: string; href: string; desc: string }
> = {
  public: {
    label: "일반 상담",
    short: "일반",
    icon: "diversity_3",
    href: "/new",
    desc: "쉬운 말로 절차와 근거를 안내합니다.",
  },
  expert: {
    label: "전문가 업무",
    short: "전문가",
    icon: "gavel",
    href: "/new",
    desc: "조문 중심 분석과 서류 작성까지 지원합니다.",
  },
  monitor: {
    label: "규제 모니터링",
    short: "모니터링",
    icon: "monitoring",
    // 채팅 셸로 보낸다(2026-10-02). 모니터링은 **스레드**다 — 대화로 대상을
    // 정의하고 관찰 목록을 고친다. 구 `/monitor`(폴더 기반 배송 설정)는
    // 사이드바에서 따로 연다.
    href: "/new",
    desc: "대화로 규제를 모아 두면 개정을 감지해 알려 줍니다.",
  },
};

export const ALL_MODES: AppMode[] = ["public", "expert", "monitor"];

export function isAppMode(v: unknown): v is AppMode {
  return v === "public" || v === "expert" || v === "monitor";
}

export function getMode(): AppMode | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(KEY);
    return isAppMode(v) ? v : null;
  } catch {
    return null;
  }
}

export function setMode(mode: AppMode): void {
  try {
    window.localStorage.setItem(KEY, mode);
  } catch {
    /* 무시 — 사생활 보호 모드 등 */
  }
  try {
    window.dispatchEvent(new CustomEvent(MODE_CHANGED_EVENT, { detail: mode }));
  } catch {
    /* 무시 */
  }
}

/** 모드 → 채팅 답변 어투. 모니터링은 채팅을 쓰지 않는다. */
export function styleForMode(mode: AppMode | null): "expert" | "simple" | null {
  if (mode === "public") return "simple";
  if (mode === "expert") return "expert";
  return null;
}

/** 전문가 전용 기능인가 — 심층 보고서·법률 네트워크·서식 작성·모니터링 진입. */
export function isProFeatureVisible(mode: AppMode | null): boolean {
  return mode !== "public";
}


// ── 기밀 모드 ───────────────────────────────────────────────────────────────
//
// 전문가 경로에서 사건 파일·의뢰인 사실관계를 다룰 때 켠다. 켜지면 그 대화는
// 온프레미스 모델로만 처리되고 웹 검색 도구가 부여되지 않는다(백엔드 보장).
// 전문가 모드에서만 의미가 있다.

const CONF_KEY = "regnav_confidential";

export const CONFIDENTIAL_CHANGED_EVENT = "regnav-confidential-changed";

/**
 * 기밀은 **스레드 단위**다 (2026-10-03).
 *
 * 종전엔 브라우저 전역 플래그 하나였다 — 사건 파일 스레드에서 켜면 다른 스레드도
 * 원내 모델로 조용히 저하됐고, 그쪽에서 끄면(경고도 안 뜬다) 돌아와서 기밀 내용이
 * 통째로 드롭됐다. 보호 단위(스레드)와 토글 단위(브라우저)가 어긋났다.
 *
 * 키: `regnav_confidential:<threadId>`. 스레드가 아직 없으면(`/new`) 전역 키를 쓰고,
 * 첫 전송에서 스레드가 생기면 `adoptConfidential` 이 그 스레드로 옮긴다.
 */
function confKey(threadId: string | null | undefined): string {
  return threadId ? `${CONF_KEY}:${threadId}` : CONF_KEY;
}

export function getConfidential(threadId?: string | null): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(confKey(threadId)) === "1";
  } catch {
    return false;
  }
}

export function setConfidential(on: boolean, threadId?: string | null): void {
  try {
    if (on) window.localStorage.setItem(confKey(threadId), "1");
    else window.localStorage.removeItem(confKey(threadId));
  } catch {
    /* 무시 */
  }
  try {
    window.dispatchEvent(
      new CustomEvent(CONFIDENTIAL_CHANGED_EVENT, { detail: { on, threadId: threadId ?? null } }),
    );
  } catch {
    /* 무시 */
  }
}

/** `/new` 에서 켠 기밀을 방금 생긴 스레드로 옮긴다 — 전역 키는 비운다. */
export function adoptConfidential(threadId: string): void {
  if (!getConfidential(null)) return;
  setConfidential(true, threadId);
  setConfidential(false, null);
}

/**
 * 기능 사용에 따라 기밀 모드를 **자동으로** 켠다(2026-10-01 사용자 요구).
 *
 * 켤 조건을 기능 쪽에서 판단하게 하지 않는다 — 전문가 경로가 아니거나 이미 켜져
 * 있으면 아무 일도 하지 않고 `false` 를 돌려준다. 호출부는 `true` 일 때만 안내를
 * 띄우면 된다(같은 대화에서 안내가 두 번 뜨지 않는다).
 */
export function autoEnableConfidential(
  mode: AppMode | null,
  threadId?: string | null,
): boolean {
  if (mode === "public") return false; // 일반 경로엔 원내 모델 개념이 없다
  if (getConfidential(threadId)) return false;
  setConfidential(true, threadId);
  return true;
}

/**
 * 첨부 파일 선택창 열기 요청(2026-10-01).
 *
 * 첫 화면의 "문서 검토" 카드가 입력창의 파일 input 을 열어야 하는데, 둘은 형제도
 * 아니다. ref 를 PageShell 까지 끌어올리는 대신 이벤트 하나로 끝낸다 —
 * `CONFIDENTIAL_CHANGED_EVENT` 와 같은 방식이다.
 */
export const OPEN_ATTACH_EVENT = "regnav-open-attach";

/** 의견서 초안 패널 열기 요청(2026-10-01) — `OPEN_ATTACH_EVENT` 와 같은 이유. */
export const OPEN_BRIEF_EVENT = "regnav-open-brief";

/** 관찰 목록 패널 열기(2026-10-02) — 모니터링 스레드 전용. */
export const OPEN_WATCH_EVENT = "regnav-open-watch";
