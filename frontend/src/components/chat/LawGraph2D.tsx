"use client";

/**
 * LawGraph2D — 근거 법령 네트워크 2D 렌더러 (v3).
 *
 * v2 피드백(2026-07-16): 라벨 겹침 + 밋밋함 → 개선:
 *  - 노드 간 반발력·링크 거리 확대(d3Force) — 라벨 겹침 해소.
 *  - 시뮬레이션 안정 후 zoomToFit — 전체 구도가 항상 프레임 안에.
 *  - seed 소프트 글로우(shadowBlur) + 링크 방향 파티클(테마 primary, 얇게)
 *    + 호버 링 하이라이트 — 서비스 톤 유지한 생동감.
 *
 * 색은 테마 CSS 토큰 실값(라이트/다크 자동). next/dynamic(ssr:false) 전용.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import type { LawGraphResponse, LawGraphNode } from "@/lib/client/lawGraph";

type GraphNode = LawGraphNode & {
  kind: "seed" | "same" | "other";
  x?: number;
  y?: number;
};

type Props = {
  data: LawGraphResponse;
  width: number;
  height: number;
};

/** 현재 테마의 --md-* 토큰 실값 (canvas는 CSS var를 못 읽음) */
function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string, fallback: string) =>
    cs.getPropertyValue(name).trim() || fallback;
  return {
    primary: v("--md-primary", "#0F6B4A"),
    onSurface: v("--md-on-surface", "#1c1b1f"),
    onSurfaceVariant: v("--md-on-surface-variant", "#49454f"),
    outlineVariant: v("--md-outline-variant", "#cac4d0"),
    surface: v("--md-surface", "#ffffff"),
  };
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function LawGraph2D({ data, width, height }: Props) {
  const fgRef = useRef<ForceGraphMethods<GraphNode> | undefined>(undefined);
  const [hoverId, setHoverId] = useState<string | null>(null);
  // 색은 마운트 시점 테마 기준 — 패널을 다시 열면 새 테마 반영.
  const colors = useMemo(() => themeColors(), []);

  const graphData = useMemo(() => {
    const seedLawIds = new Set(
      data.nodes.filter((n) => n.is_seed).map((n) => n.law_id),
    );
    const nodes: GraphNode[] = data.nodes.map((n) => ({
      ...n,
      kind: n.is_seed ? "seed" : seedLawIds.has(n.law_id) ? "same" : "other",
    }));
    return { nodes, links: data.edges.map((e) => ({ ...e })) };
  }, [data]);

  // 라벨 겹침 해소 — 반발력·링크 거리를 라벨 폭 기준으로 넉넉히.
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength(-220);
    const linkForce = fg.d3Force("link") as
      | { distance?: (d: number) => unknown }
      | undefined;
    linkForce?.distance?.(85);
    fg.d3ReheatSimulation();
  }, [graphData]);

  // 노드 = 원 + 라벨 직접 드로잉. seed는 글로우 + 항상 라벨.
  const drawNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const isSeed = node.kind === "seed";
      const isHover = node.id === hoverId;
      const r = isSeed ? 5.5 : 3.5;
      const x = node.x ?? 0;
      const y = node.y ?? 0;

      // seed 소프트 글로우 — 은은하게 (네온 아님)
      ctx.save();
      if (isSeed || isHover) {
        ctx.shadowColor = colors.primary;
        ctx.shadowBlur = isHover ? 18 : 10;
      }
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle =
        node.kind === "seed"
          ? colors.primary
          : node.kind === "same"
            ? colors.primary + "80"
            : colors.onSurfaceVariant + "66";
      ctx.fill();
      ctx.restore();

      // 호버 링
      if (isHover) {
        ctx.beginPath();
        ctx.arc(x, y, r + 3, 0, 2 * Math.PI);
        ctx.strokeStyle = colors.primary + "88";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      } else if (isSeed) {
        ctx.beginPath();
        ctx.arc(x, y, r + 2.5, 0, 2 * Math.PI);
        ctx.strokeStyle = colors.primary + "33";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // 라벨 — seed·호버는 항상, 나머지는 살짝만 확대해도 표시.
      const showLabel = isSeed || isHover || scale > 0.9;
      if (showLabel) {
        const fontPx = Math.max(isSeed ? 11 : 10, 12 / scale);
        ctx.font = `${isSeed || isHover ? "600 " : ""}${fontPx}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        const label = truncate(node.label || node.law_title || node.id, 20);
        const tw = ctx.measureText(label).width;
        // 가독용 배경판 (surface 반투명) — 겹치는 선 위에서도 읽히게
        ctx.fillStyle = colors.surface + "d9";
        ctx.fillRect(x - tw / 2 - 3, y + r + 3, tw + 6, fontPx + 4);
        ctx.fillStyle =
          isSeed || isHover ? colors.onSurface : colors.onSurfaceVariant;
        ctx.fillText(label, x, y + r + 5);
      }
    },
    [colors, hoverId],
  );

  const handleNodeClick = useCallback((node: GraphNode) => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.centerAt(node.x ?? 0, node.y ?? 0, 500);
    fg.zoom(2.5, 500);
  }, []);

  return (
    <ForceGraph2D
      ref={fgRef as React.MutableRefObject<ForceGraphMethods<GraphNode> | undefined>}
      width={width}
      height={height}
      graphData={graphData}
      backgroundColor="rgba(0,0,0,0)"
      nodeCanvasObject={(n, ctx, scale) => drawNode(n as GraphNode, ctx, scale)}
      nodePointerAreaPaint={(n, color, ctx) => {
        const node = n as GraphNode;
        ctx.beginPath();
        ctx.arc(node.x ?? 0, node.y ?? 0, 9, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();
      }}
      nodeLabel={(n) => {
        const node = n as GraphNode;
        const bits = [node.law_title];
        if (node.enforcement_date) bits.push(`시행 ${node.enforcement_date}`);
        if (node.is_seed) bits.push("이 답변이 인용한 조문");
        return bits.filter(Boolean).join(" · ");
      }}
      onNodeHover={(n) => setHoverId((n as GraphNode | null)?.id ?? null)}
      onNodeClick={(n) => handleNodeClick(n as GraphNode)}
      linkColor={() => colors.outlineVariant}
      linkWidth={1}
      linkDirectionalArrowLength={4}
      linkDirectionalArrowRelPos={0.9}
      linkDirectionalParticles={1}
      linkDirectionalParticleWidth={1.6}
      linkDirectionalParticleSpeed={0.004}
      linkDirectionalParticleColor={() => colors.primary}
      cooldownTime={4000}
      onEngineStop={() => fgRef.current?.zoomToFit(400, 48)}
      minZoom={0.4}
      maxZoom={8}
    />
  );
}

export default LawGraph2D;
