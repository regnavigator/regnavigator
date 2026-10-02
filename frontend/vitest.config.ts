import { defineConfig } from "vitest/config";
import path from "node:path";

// 프런트 테스트 러너(2026-10-03). 감사: 경합 보호 주석 23곳 = 과거 사고 23건이
// 테스트 없이 주석으로만 지켜지고 있었다. 순수 함수 경계(파서·턴 파생·PII 역추적)
// 부터 고정한다. 컴포넌트 테스트는 범위 밖(jsdom 미도입).
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
});
