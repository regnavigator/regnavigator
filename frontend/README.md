# MEDIREG AI — 프론트엔드

**MEDIREG AI** — 법령·고시·해석례·판례를 벡터 DB와 웹 검색으로 통합 조회하는 의료·규제
전문 AI 에이전트의 프론트엔드. Next.js 15 App Router + **자체 SSE**(medi-back `/chat`·
`/reports`; langgraph SDK 는 2026-07-14 ADR-0001 로 은퇴). 사용자 향 **단일 에이전트** 모델.

> **단계: 운영(클로즈 베타) — v0.2.0** · `main` push → GHA self-hosted runner 자동배포
> (medi-back 과 같은 GCP VM, docker compose).

## 어디부터 보나

| 나는 ... | 문서 |
|---|---|
| 📚 **문서 전체 지도** | **[`docs/README.md`](./docs/README.md)** ← 인덱스(현행/설계문/아카이브 구분) |
| 🛠 코드를 고치러 왔다 | [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — 현재 구현 상태 정본 |
| 🆕 최근 뭐가 바뀌었나 | [`docs/PATCHNOTE.md`](./docs/PATCHNOTE.md) — 날짜별 단일 타임라인 |
| 👤 앱을 *사용*한다 | [`docs/USER_GUIDE.md`](./docs/USER_GUIDE.md) — 개발 지식 불필요 |
| 🔌 백엔드 계약이 궁금 | medi-back [`docs/frontend_chat_v2.md`](../medi-back/docs/contracts/frontend_chat_v2.md) · [`docs/API.md`](../medi-back/docs/contracts/API.md) |
| 🎨 디자인 규칙 | [`docs/01_COLOR.md`](./docs/01_COLOR.md) ~ [`docs/04_ELEMENTS.md`](./docs/04_ELEMENTS.md) · [`docs/design_guide.md`](./docs/design_guide.md) |

## 개발

```bash
npm install
cp .env.example .env.local        # NEXT_PUBLIC_DEPLOYMENT_URL·NEXTAUTH_SECRET·DATABASE_URL 등
npx prisma migrate dev            # 인증 DB(Postgres medi_auth)
npm run dev                       # http://localhost:3000

npm run lint && npx tsc --noEmit && npm run build   # CI 와 동일 게이트
```

- **백엔드 없이 UI 만** 보려면 `NEXT_PUBLIC_DUMMY_MODE=true` (public/mocks 로 REST 차환 + fake 스트림).
- `NEXT_PUBLIC_*` 는 빌드 시 번들에 inline — 값 바꾸면 재빌드해야 반영된다.

## 규율 (코드 리뷰에서 강제)

- **단일 에이전트 멘탈 모델** — supervisor / sub-agent / tool 노드 이름을 UI 에 노출하지 않는다.
- **디자인 토큰만** — `globals.css` 밖 raw hex 금지. 아이콘은 Material Symbols 단일 셋(lucide 미사용).
- **snake_case 필드** — 백엔드 payload 를 camelCase 로 바꾸지 않는다.
- **채널 분리** — References·다음 단계는 본문 텍스트가 아니라 전용 UI(`<next_steps>` 파싱).
- 스킬 가이드: `.claude/skills/medi-front-{spec,step-card,data-contract}/SKILL.md`,
  테마는 `.claude/skills/medi-front-theme-{regia,medra}/SKILL.md`.

## 문서 갱신 규칙

- **설계 결정**(색·레이아웃·컴포넌트 사양)이 바뀌면 → 설계문(`00`~`05`)을 먼저 고친다.
- **구현 현황**이 바뀌면 → [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) 를 고친다(코드가 진실).
- **날짜별 변경 서술**은 전부 [`docs/PATCHNOTE.md`](./docs/PATCHNOTE.md) 한 곳에만 쌓는다.

---

*작성 시작: 2026-04-27 · v0.2.0 릴리스: 2026-07-21(프런트·백 동시 태깅) · 문서 정리: 2026-08-10.*
