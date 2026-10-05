"use client";

/**
 * 좁은 화면(모바일) 판별 훅 — 3-pane 레이아웃이 성립하지 않는 폭에서
 * 사이드바/우측 패널을 드로어·오버레이로 전환하기 위한 신호.
 *
 * SSR/첫 페인트에선 false(데스크톱 가정) — mount 후 matchMedia로 확정.
 * 1023px 기준: Tailwind `lg`(1024px) 미만.
 *
 * 왜 md(768)가 아니라 lg(1024)인가 (2026-10-05, 감사 F4): 768~1023px 에서 3-pane 을
 * 그리면 사이드바가 16% 고정(≈123px)이라 제목이 한 글자씩 잘리고, 우측 패널(≥24%)을
 * 열면 채팅 컬럼이 370px 아래로 떨어진다. 그 폭의 태블릿은 드로어 레이아웃이 맞다.
 */

import { useEffect, useState } from "react";

const QUERY = "(max-width: 1023px)";

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
