"use client";

/**
 * ThemeToggle — 3-way 테마 사이클. UI 라벨은 각 테마 primary 색명.
 *
 * - medra  → Forest  (Deep Forest Green: primary #1D4D3A + 웜 아이보리 surface) — **기본**
 * - basic  → Emerald (Quiet Forest Suite: primary #0F6B4A)
 * - regia  → Indigo  (Indigo/Blue/Cyan 그라데이션: primary #6366F1)
 *
 * body[data-theme] 또는 body 자체로 globals.css 토큰 swap.
 * localStorage 영속 + flash 방지(layout 초기 inline script가 hydration 전에 박음).
 * 기본 테마 = Forest(medra) — 미설정 시 medra 로 시작.
 */

import { useEffect, useState } from "react";

type Theme = "basic" | "medra" | "regia" | "dark";

const STORAGE_KEY = "medi-front-theme";
const DEFAULT_THEME: Theme = "medra"; // Forest
const ORDER: Theme[] = ["medra", "basic", "regia", "dark"];

const META: Record<Theme, { label: string; dot: string }> = {
  medra: { label: "Forest", dot: "#1D4D3A" },
  basic: { label: "Emerald", dot: "var(--md-primary)" },
  regia: { label: "Indigo", dot: "#6366F1" },
  dark: { label: "Dark", dot: "#6FD3A8" },
};

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return DEFAULT_THEME;
  const v = window.localStorage.getItem(STORAGE_KEY);
  if (v === "medra" || v === "regia" || v === "basic" || v === "dark") return v;
  return DEFAULT_THEME; // 미설정 → Forest
}

function applyTheme(t: Theme) {
  if (typeof document === "undefined") return;
  if (t === "basic") {
    document.body.removeAttribute("data-theme");
  } else {
    document.body.setAttribute("data-theme", t);
  }
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(DEFAULT_THEME);

  useEffect(() => {
    const t = readStoredTheme();
    setTheme(t);
    applyTheme(t);
  }, []);

  function cycle() {
    const idx = ORDER.indexOf(theme);
    const next = ORDER[(idx + 1) % ORDER.length]!;
    setTheme(next);
    applyTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {}
  }

  const meta = META[theme];

  return (
    <button
      type="button"
      onClick={cycle}
      title={`테마 전환 — 다음: ${META[ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length]!].label}`}
      aria-label="테마 전환"
      className="inline-flex h-7 items-center gap-1.5 rounded-full border border-md-outline-variant bg-md-surface px-2.5 text-[10.5px] font-semibold text-md-on-surface-variant transition-all hover:border-md-on-surface hover:text-md-on-surface"
    >
      <span
        className="size-1.5 rounded-full"
        style={{ background: meta.dot }}
        aria-hidden
      />
      {meta.label}
    </button>
  );
}
