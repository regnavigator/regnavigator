/**
 * lawGraph — GET /law-graph 씬 클라이언트.
 *
 * 답변 인용(article_key)을 seed로 조문 인용 네트워크 서브그래프(노드+엣지)를
 * 받아온다. LawGraphDialog(3D 네트워크 시각화) 전용.
 *
 * backend: medi-back src/routes/law_graph.py — Neo4j CITES 서브그래프.
 * 503 = Neo4j 비활성 (호출측에서 안내 처리).
 */

import { apiFetch } from "@/lib/api/client";

export type LawGraphNode = {
  /** article_key (`{law_id}_{조문키}`) */
  id: string;
  /** 표시용 짧은 라벨 (예: "의료기기법 제6조") */
  label: string;
  law_id: string;
  law_title: string;
  jo?: string;
  gaji?: string;
  target_type?: string;
  enforcement_date?: string;
  is_seed: boolean;
};

export type LawGraphEdge = {
  source: string;
  target: string;
  type: string;
};

export type LawGraphResponse = {
  seeds: string[];
  nodes: LawGraphNode[];
  edges: LawGraphEdge[];
  node_count: number;
  edge_count: number;
  truncated: boolean;
};

const MAX_SEEDS = 20;

export async function fetchLawGraph(
  keys: string[],
  depth: 1 | 2 = 1,
): Promise<LawGraphResponse> {
  const params = new URLSearchParams({
    keys: keys.slice(0, MAX_SEEDS).join(","),
    depth: String(depth),
    rels: "CITES",
  });
  return apiFetch<LawGraphResponse>(`/law-graph?${params.toString()}`);
}
