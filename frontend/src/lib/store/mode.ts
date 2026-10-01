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
    href: "/monitor",
    desc: "관심 법령의 개정을 감지해 리포트로 보냅니다.",
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
