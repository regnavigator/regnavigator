/**
 * 업데이트 내역 프록시 — `GET /api/announcements?limit=&q=` → backend `GET /announcements`.
 *
 * /updates 는 공개 페이지라 비로그인 브라우저가 backend 를 직접 부르는데, 운영
 * backend 의 CORS 허용 출처는 운영 도메인뿐이다. 로컬(localhost:3000)·프리뷰 등
 * 다른 출처에서는 "목록을 불러오지 못했습니다"가 났다(2026-09-02). 서버 사이드에서
 * 대신 호출하면 출처 문제가 없고, backend 주소도 브라우저에 노출되지 않는다.
 * 인증 불필요(backend 공개 라우트). 캐시는 짧게(60s) — 발행 직후 반영 지연 최소화.
 */
import { NextResponse } from "next/server";

const BACKEND =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_DEPLOYMENT_URL ||
  "";

export async function GET(req: Request) {
  if (!BACKEND) {
    return NextResponse.json({ error: "backend URL 미설정" }, { status: 500 });
  }
  const url = new URL(req.url);
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 100) || 100, 1), 100);
  const q = (url.searchParams.get("q") ?? "").slice(0, 100);
  const qs = new URLSearchParams({ limit: String(limit) });
  if (q.trim()) qs.set("q", q.trim());

  const res = await fetch(`${BACKEND.replace(/\/$/, "")}/announcements?${qs.toString()}`, {
    headers: {
      Accept: "application/json",
      // Cloudflare 브라우저 무결성 검사가 기본 서버 UA 를 막는 경우가 있다(운영 실측).
      "User-Agent":
        "Mozilla/5.0 (medi-front server) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    },
    next: { revalidate: 60 },
  }).catch(() => null);

  if (!res || !res.ok) {
    return NextResponse.json(
      { error: "업데이트 목록을 불러오지 못했습니다", status: res?.status ?? 0 },
      { status: 502 },
    );
  }
  const data = await res.json();
  return NextResponse.json(data, {
    headers: { "Cache-Control": "public, max-age=60, stale-while-revalidate=300" },
  });
}
