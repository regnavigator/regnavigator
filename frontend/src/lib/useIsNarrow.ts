"use client";

/**
 * 좁은 화면(모바일) 판별 훅 — 3-pane 레이아웃이 성립하지 않는 폭에서
 * 사이드바/우측 패널을 드로어·오버레이로 전환하기 위한 신호.
 *
 * SSR/첫 페인트에선 false(데스크톱 가정) — mount 후 matchMedia로 확정.
 * 767px 기준: Tailwind `md`(768px) 미만.
 */

import { useEffect, useState } from "react";

const QUERY = "(max-width: 767px)";

export function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    const update = () => setNarrow(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return narrow;
}
