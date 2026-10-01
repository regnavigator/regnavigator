# QA 리포트 — RegNavigator 모드 분기 (2026-10-01)

대상 localhost:3000 (frontend) + :2024 (backend, dev 인증 우회)
브랜치 `feat/monitor-reports` · 도구 gstack browse

## 결과 요약

| # | 시나리오 | 결과 |
|---|---|---|
| S1 | `/` → `/start`, 카드 3개 | ✅ |
| S2 | 일반 모드 — 고지 **있음** / 보고서·어투토글·모니터링 **없음** | ✅ (5/5) |
| S3 | 전문가 모드 — 고지 **없음** / 어투토글·모니터링 **있음** | ✅ (4/5, 1건 미검증) |
| S4 | 모니터링 모드 → `/monitor` | ✅ |
| S5 | 사이드바 전환 → `/start?pick=1`, "현재" 배지 | ✅ |
| S6 | 모드 유지 — `/` 재방문 시 자동 이동 | ✅ |
| S7 | 콘솔 에러 | ✅ 0건 (NextAuth 500 해결) |
| S8 | 모니터링 미리보기 · degraded 배너 | ✅ |
| S9 | 채팅 어투 비교 | 🔴 **차단** — 법령 검색 API 키 401 |

## 측정값

- 백엔드 테스트 **1325 pass / 13 skip / 0 fail**
- `tsc --noEmit` 통과 · `next build` 통과 · 신규 파일 린트 지적 0

## 미검증 2건

1. **전문가 모드 심층 보고서 버튼** — 대화가 1턴 이상 있어야 렌더된다. 채팅이 막혀 미검증.
2. **S9 모드별 답변 어투** — `RAG_SEARCH_API_KEY` 가 401(`invalid_api_key`). 규제 질의는
   법령 검색이 강제되므로 어떤 질문도 턴을 완성하지 못한다.

## 알려진 비에러 로그 2종

- `WARNING: Missing resize handle for PanelGroup` — react-resizable-panels, 기존부터 발생
- `Blocked script execution in 'about:srcdoc'` — 리포트 미리보기 iframe 의 `sandbox=""` 가
  의도대로 스크립트를 차단한 것. 보안 장치가 동작한 기록이라 완화하지 않는다.

## 외부 의존성 상태

| 의존 | 상태 |
|---|---|
| Anthropic API | ✅ |
| Tavily 웹 검색 | ✅ |
| 법령 검색 API (DGX :8080) | 🔴 도달 가능하나 **API 키 401** |
| openlaw PG | 🔴 미설정 |
| SMTP | 🔴 미설정 (미리보기는 무관) |
