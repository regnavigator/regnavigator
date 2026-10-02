"use client";

/**
 * ModeProvider — 앱 모드를 트리 전체에 공급 (2026-10-01).
 *
 * localStorage 는 SSR 에서 못 읽으므로 첫 렌더는 `null`(=미정)로 시작하고
 * mount 뒤 채운다. 소비자는 `null` 을 "아직 모름"으로 다뤄야 한다 —
 * 전문가 전용 기능을 `null` 일 때 잠깐 보여줬다 숨기면 깜빡인다.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getConfidential,
  getMode,
  isAppMode,
  MODE_CHANGED_EVENT,
  setConfidential,
  setMode as persistMode,
  styleForMode,
  type AppMode,
} from "@/lib/store/mode";

type Ctx = {
  /** null = 아직 모름(mount 전) 또는 미선택 */
  mode: AppMode | null;
  ready: boolean;
  setMode: (m: AppMode) => void;
  /** 전문가 전용 기능 노출 여부 — ready 전엔 false(깜빡임 방지) */
  showPro: boolean;
  /** 채팅 answer style — 모드가 정한다 */
  answerStyle: "expert" | "simple" | null;
};

const ModeContext = createContext<Ctx>({
  mode: null,
  ready: false,
  setMode: () => {},
  showPro: false,
  answerStyle: null,
});

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<AppMode | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const m = getMode();
    setModeState(m);
    setReady(true);
    // 일반 경로에는 기밀 토글이 없다 — 전문가 경로에서 켠 채 모드를 바꾸면
    // 보이지도 않는 설정이 계속 원내 라우팅을 강제하고, 원내 모델이 미설정이면
    // 그 질문은 아예 거부된다(fail-closed). 끌 UI 가 없으니 여기서 정리한다.
    if (m === "public" && getConfidential(null)) setConfidential(false, null);
  }, []);

  // 같은 탭(사이드바 전환) + 다른 탭(storage) 양쪽 동기화.
  useEffect(() => {
    const onLocal = (e: Event) => {
      const v = (e as CustomEvent).detail;
      if (isAppMode(v)) setModeState(v);
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === "regnav_mode" && isAppMode(e.newValue)) setModeState(e.newValue);
    };
    window.addEventListener(MODE_CHANGED_EVENT, onLocal);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(MODE_CHANGED_EVENT, onLocal);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const setMode = useCallback((m: AppMode) => {
    persistMode(m);
    setModeState(m);
    if (m === "public") setConfidential(false, null);   // 위 mount 훅과 같은 이유
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      mode,
      ready,
      setMode,
      // ready 전엔 숨긴다 — 보였다 사라지는 깜빡임이 더 나쁘다.
      showPro: ready && mode !== "public",
      answerStyle: styleForMode(mode),
    }),
    [mode, ready, setMode],
  );

  return <ModeContext.Provider value={value}>{children}</ModeContext.Provider>;
}

export function useMode(): Ctx {
  return useContext(ModeContext);
}
