"use client";

/**
 * LawGraphPanel — 근거 법령 네트워크 패널 (v3).
 *
 * 기본 = **센터 대형 카드**(우하단 PIP는 "너무 작아 안 보인다" 피드백,
 * 2026-07-16) + 헤더 토글로 PIP(우하단 소형)로 축소해 채팅과 병행 가능.
 * 센터 모드는 옅은 딤 배경(클릭 시 닫힘), PIP 모드는 비모달. ESC 닫기 공통.
 * 서비스 테마 토큰만 사용. 그래프 렌더러는 열 때만 dynamic import.
 */

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { fetchLawGraph, type LawGraphResponse } from "@/lib/client/lawGraph";

const LawGraph2D = dynamic(() => import("@/components/chat/LawGraph2D"), {
  ssr: false,
  loading: () => <PanelSpinner label="렌더러 로딩 중…" />,
});

type Props = {
  seeds: string[];
  onClose: () => void;
};

export function LawGraphPanel({ seeds, onClose }: Props) {
  const [data, setData] = useState<LawGraphResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // "center" = 센터 대형(기본) · "pip" = 우하단 소형(채팅 병행)
  const [mode, setMode] = useState<"center" | "pip">("center");
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    fetchLawGraph(seeds)
      .then((res) => {
        if (!alive) return;
        if (res.nodes.length === 0) {
          setError("이 인용들의 인용 관계 데이터가 아직 없습니다.");
        } else {
          setData(res);
        }
      })
      .catch((err: unknown) => {
        if (!alive) return;
        console.warn("[LawGraphPanel] fetch failed", err);
        setError("법령 네트워크를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.");
      });
    return () => {
      alive = false;
    };
  }, [seeds]);

  // 캔버스 실측 — 확대 토글 시에도 ResizeObserver가 따라감.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isCenter = mode === "center";
  const card = (
    <section
      role={isCenter ? "dialog" : "complementary"}
      aria-label="근거 법령 네트워크"
      className={
        "flex flex-col overflow-hidden rounded-card border border-md-outline-variant bg-md-surface shadow-xl animate-md-fade-in " +
        (isCenter
          ? "h-[min(78vh,760px)] w-[min(1080px,94vw)]"
          : "fixed right-3 bottom-3 z-[70] h-[320px] w-[calc(100vw-24px)] sm:right-4 sm:bottom-4 sm:w-[460px]")
      }
    >
      <header className="flex shrink-0 items-center gap-2 border-b border-md-outline-variant px-3 py-2">
        <span
          className="material-symbols-outlined text-[17px] text-md-primary"
          aria-hidden
        >
          hub
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[13px] font-semibold text-md-on-surface">
            근거 법령 네트워크
          </h2>
          <p className="truncate text-[10.5px] text-md-on-surface-variant">
            {data
              ? `조문 ${data.node_count} · 인용 ${data.edge_count}${data.truncated ? " · 일부" : ""} — 초록 = 이 답변의 인용`
              : "인용 조문 간 인용 관계"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setMode((m) => (m === "center" ? "pip" : "center"))}
          aria-label={isCenter ? "작은 창으로 (채팅 병행)" : "크게 보기"}
          title={isCenter ? "작은 창으로 — 채팅을 계속하면서 보기" : "크게 보기"}
          className="inline-flex h-7 w-7 items-center justify-center rounded text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
        >
          <span className="material-symbols-outlined text-[17px]" aria-hidden>
            {isCenter ? "picture_in_picture_alt" : "open_in_full"}
          </span>
        </button>
        <button
          type="button"
          onClick={onClose}
          aria-label="닫기"
          className="inline-flex h-7 w-7 items-center justify-center rounded text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
        >
          <span className="material-symbols-outlined text-[17px]" aria-hidden>
            close
          </span>
        </button>
      </header>

      <div ref={wrapRef} className="relative min-h-0 flex-1 bg-md-surface-container-lowest">
        {error ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-5 text-center">
            <p className="text-[12px] leading-relaxed text-md-on-surface-variant">
              {error}
            </p>
          </div>
        ) : data && size.w > 0 && size.h > 0 ? (
          <LawGraph2D data={data} width={size.w} height={size.h} />
        ) : (
          <PanelSpinner label="인용 네트워크 불러오는 중…" />
        )}
      </div>
    </section>
  );

  if (isCenter) {
    return (
      <div
        className="fixed inset-0 z-[70] flex items-center justify-center bg-black/35 p-4"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        {card}
      </div>
    );
  }
  return card;
}

function PanelSpinner({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center gap-2.5">
      <span
        className="inline-block size-4 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin"
        aria-hidden
      />
      <span className="text-[12px] text-md-on-surface-variant">{label}</span>
    </div>
  );
}
