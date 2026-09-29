# medi-front — 유지보수 / 확장 지침

> 코드 건강성·운영 가시성·사용자 경험 향상을 위한 우선순위별 로드맵.
> 이번 sprint에 즉시 적용한 항목은 본 문서 § "✓ 적용 완료"에 기록한다.

---

## 우선순위 매트릭스

| Tier | 기준 | 예상 작업량 |
|---|---|---|
| 🔴 P0 | 운영 가시성·기본 UX·기술 부채 | 즉시 (이번 sprint) |
| 🟡 P1 | 사용자 자주 요청 / 모바일 / 테스트 | 1~2 주 |
| 🟢 P2 | 차별화 / 협업 / 장기 인프라 | 1~2 달 |

---

## 🔴 P0 — 즉시 적용 (이번 sprint)

### 1. API 클라이언트 통합 — `lib/api/client.ts`

**현황**: `quota.ts`·`admin.ts`·`reports.ts`가 각자 `jsonFetch` 중복 구현. baseUrl·authHeaders·DUMMY 분기 모두 별도 코드.

**조치**: 단일 fetch wrapper로 통합. interceptor 패턴.
- auth 헤더 자동 주입
- 401 → `/login` redirect
- 429 → `parse429` 일괄 처리
- DUMMY 모드 mock fetch 자동 분기
- 에러 메시지 한국어 매핑

**적용 영향**: 향후 새 endpoint 추가 시 wrapper만 호출. 일관된 에러 보고.

### 2. Quota threshold 토스트

**현황**: 사용자가 한도 80%·95% 도달해도 모름 → 갑자기 429 막힘.

**조치**: `useUsage` 훅에 threshold 감지. 80% / 95% 도달 시 토스트 1회.
- 일·월 한도 각각 추적
- 같은 threshold 중복 알림 방지 (sessionStorage)

### 3. 메시지 hover toolbar — copy

**현황**: 답변 본문 복사하려면 드래그 + Ctrl+C. 불편.

**조치**: TurnAnswer hover 시 우상단에 copy 아이콘 노출. 클릭 시 markdown 본문 클립보드 + 토스트.

### 4. `prefers-reduced-motion` 글로벌

**현황**: 스피너·shimmer·typing-dot 등 애니메이션 다수. 접근성 사용자 부담.

**조치**: `@media (prefers-reduced-motion: reduce)` 글로벌 룰 — 모든 `animate-md-*` 정지.

### 5. 코드 분할 — `lib/store/types.ts` 도메인별

**현황**: 단일 파일 300+ 줄 — Citation·Step·Turn·Message·Report·DeepProgress·ChatState 모두.

**조치**: `types/` 디렉토리로 분할:
```
types/
  chat.ts       (Message·Step·Turn)
  citation.ts   (Citation·doc_category enum)
  deep.ts       (DeepProgress·DeepStage·DeepToolResult)
  report.ts     (Report)
  state.ts      (ChatState·InterruptValue)
```
기존 `types.ts`는 re-export로 남겨 backwards compat.

---

## 🟡 P1 — 1~2주 내

### 6. Sentry 통합

- 프런트 console.warn/error만 → 운영 에러 가시성 부족
- DSN env 받고 `@sentry/nextjs` 통합
- user_id·thread_id context 자동 첨부

### 7. Web Vitals telemetry

- Vercel Analytics 또는 PostHog (가벼움)
- 핵심 metric: TTFB / FCP / LCP / send latency / deep 완료 시간
- 운영 1주일 → base line 확보 → 회귀 감지 기준

### 8. 메시지 toolbar 확장

- **재생성 (regenerate)**: 같은 user 메시지로 재실행 — backend `runs.create` + checkpoint
- **편집 (edit)**: user 메시지 수정 → 그 시점부터 fork
- **공유 링크**: 단일 turn read-only URL

### 9. 테스트 인프라

- **단위** — Vitest + RTL:
  - `lib/parse/citation.ts` (마커 파싱)
  - `lib/parse/nextSteps.ts` (마커 파싱)
  - `lib/parse/deep.ts` (classifyStage)
  - `lib/parse/lawLink.ts` (deriveExternalUrl)
  - `lib/store/turns.ts` reducer들
- **E2E** — Playwright 로 핵심 흐름(로그인·채팅·보고서) 자동화
- CI: PR마다 자동 실행

### 10. 검색 기능

- 사이드바 thread 검색 (제목·본문 매칭) — backend FTS 필요
- 채팅 내 메시지 검색 (Ctrl+K)

### 11. 첨부파일 활성화

- backend OCR/parser 도입 후 가능
- drag&drop 영역 + Material Symbol 활성

---

## 🚫 Out of scope

- **모바일 레이아웃 (< 768px)** — 데스크탑 전용 UX. 별도 모바일 앱·반응형 작업 검토 안 함.

---

## 🟢 P2 — 1~2달 내

### 13. State 관리 — Zustand 검토

- React Context (`RightPanelProvider`)는 하위 컴포넌트 모두 re-render
- selector 기반 부분 구독 필요 시 Zustand 도입
- 현재 규모로는 Context 충분

### 14. Mock 모드 — MSW 통합

- `mockFetch.ts` (REST) + `dummy.ts` (LangGraph SDK) 분산 → MSW 단일 인터셉터
- fixture 자동 sync 스크립트 (`scripts/sync_mocks.sh`)

### 15. 출처 / 인용 강화

- citation hover preview (모달 안 띄우고 풍선)
- 출처 그룹 탭 (법령 / 판례 / 웹)
- 신뢰도 시각화 (`verified=true` 강조)

### 16. Deep 보고서 강화

- PDF·DOCX export
- 보고서 비교 (diff)
- 이메일 발송

### 17. 알림 / 푸시

- 브라우저 desktop notification (Notification API) — deep 완료
- 다른 탭에 있어도 알림

### 18. 협업

- thread 공유 (read-only / 댓글)
- 워크스페이스 (팀별 thread + member 관리)
- 역할 기반 권한 (admin / editor / viewer)

### 19. 개인화

- 직업·소속 기반 답변 톤 (signup에서 받음)
- prompt 템플릿
- 자주 본 법령 추천

### 20. i18n

- `next-intl` 도입 — 영어·일본어 등
- backend 응답도 locale 파라미터

---

## Tooling 권장 (장기)

| 항목 | 현재 | 권장 |
|---|---|---|
| Type check | tsc strict | ✓ 유지 |
| Lint | next lint (deprecated) | Next 16에서 ESLint CLI로 마이그 |
| Test | 없음 | Vitest + RTL + Playwright |
| Storybook | 없음 | 디자이너·QA 협업 시 도입 |
| Bundle 분석 | 없음 | `@next/bundle-analyzer` 분기별 1회 |
| Pre-commit | 없음 | husky + lint-staged |
| 의존성 update | manual | Dependabot / Renovate |
| Secret scan | 없음 | gitleaks pre-commit |
| Feature flag | 없음 | Vercel Edge Config / GrowthBook |
| CI/CD | 없음 | GitHub Actions: lint → tsc → test → build → deploy |

---

## 코드 베이스 관찰

### 잘 된 부분

- 토큰 `var()` cascading — 테마 추가 비용 최소
- per-thread `useChatState` — thread 전환 시 state 자동 정리
- (chat) route group + layout 공유 — PageShell 유지
- 명확한 reducer 패턴 (`applyValues` / `applyDeepStep` 등)
- 백엔드 contract 명시 (`02_INTERFACE.md` 참조 주석)

### 기술 부채

- `lib/store/types.ts` 비대 (분할 권장 → P0)
- `useChatState.ts` 600+ 줄 (send / dispatchDeep / pollReports 분리 가능)
- middleware의 dev bypass + production 차단 분기 — 단일 함수로 정리 가능
- `dummy.ts`의 fixture id rewrite 로직 — 별도 utility로 추출

---

## 작업 진행 규칙

1. P0는 이번 sprint 안에 모두 처리 (아래 § "✓ 적용 완료" 기록)
2. P1은 회의에서 우선순위 정해 jiver/issue로 트래킹
3. P2는 backlog. 사용자 요청 들어올 때마다 끌어올림
4. 새 기능 추가 전 반드시 § P0의 코드 분할/통합이 박혀있는지 확인 (그 위에 쌓아야 부채 안 늘림)

---

## ✓ 적용 완료 (2026-05-07)

본 sprint에서 P0 5개 항목 모두 박혔다.

- [x] **1. API 클라이언트 통합** — `lib/api/client.ts` (`apiFetch` / `apiFetchText` / `apiFetchBlob`).
      `quota.ts`·`admin.ts`의 중복 `jsonFetch` 제거. DUMMY 모드 + auth 헤더 + 에러 정합 단일 처리.
- [x] **2. Quota threshold 토스트** — `useUsage`에 `maybeWarnQuota` 추가. 일·월 80%/95% 도달 시
      sessionStorage 키로 1회 발화 보장. 95%는 error 토스트, 80%는 info 토스트.
- [x] **3. 메시지 hover toolbar — copy 버튼** — `TurnAnswer`에 hover 토글 copy 아이콘.
      클릭 시 markdown 본문 클립보드 + 토스트.
- [x] **4. `prefers-reduced-motion` 글로벌** — `globals.css`에 이미 박혀있음 확인 (modify X).
- [x] **5. 타입 분할** — `lib/store/types/` 디렉토리:
      `citation.ts` / `chat.ts` / `deep.ts` / `report.ts` / `state.ts`.
      기존 `types.ts`는 barrel re-export로 유지 → 21개 import 모두 무수정 작동.

**검증**:
- `tsc --noEmit` 0 errors
- `next lint` 0 warnings/errors
- `next build` 성공 (admin 번들 -4kB · 코드 정리 효과)
- 21개 `import { ... } from "@/lib/store/types"` 호환성 유지
