import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // dev를 Tailscale IP로 접속할 때 /_next/* 리소스(HMR·청크) cross-origin
  // 차단 방지 — 브라우저 "Failed to load resource" 원인(2026-07-16). prod 무관.
  // 접속 호스트는 `.env.local` 의 DEV_ALLOWED_ORIGINS(콤마)로 — 주소를 코드에 두지 않는다.
  allowedDevOrigins: (process.env.DEV_ALLOWED_ORIGINS ?? "").split(",").map((s) => s.trim()).filter(Boolean),
  // Docker 배포용 최소 번들 — `.next/standalone` + `.next/static` 만으로 동작
  output: "standalone",
  // `X-Powered-By: Next.js` 응답 헤더 제거 — 스택 정보 노출 차단.
  poweredByHeader: false,
  compiler: {
    // production 번들에서 console.* **전부** 제거(error 포함) — 브라우저 콘솔로
    // 내부 정보(API 에러 페이로드·경로) 노출 차단(2026-07-23 보안 하드닝).
    // 서버측 진단은 medi-back 서버 로그가 담당 — 브라우저 콘솔 디버깅이 필요하면
    // dev 빌드로 재현할 것.
    removeConsole: process.env.NODE_ENV === "production",
  },
};

export default nextConfig;
