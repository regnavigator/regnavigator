"use client";

/**
 * 랜딩은 `<main>` 이 scroll-snap-y 내부 스크롤 컨테이너라, 브라우저 기본 해시
 * 스크롤(window 대상)이 안 먹는다. 마운트 시 `#id` 를 직접 scrollIntoView.
 * (예: /landing#trust — ConfidenceBadge·사이드바 "이용 안내" 진입점.)
 */

import { useEffect } from "react";

export function HashScroll() {
  useEffect(() => {
    const hash = decodeURIComponent(window.location.hash || "").replace(/^#/, "");
    if (!hash) return;
    // 레이아웃 안정 후 스크롤(스냅 컨테이너 초기 스냅과 경쟁 방지).
    const t = window.setTimeout(() => {
      document.getElementById(hash)?.scrollIntoView({ behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(t);
  }, []);
  return null;
}
