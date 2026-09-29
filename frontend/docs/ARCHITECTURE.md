# ARCHITECTURE — medi-front 현재 구현 상태

> 본 문서는 *코드에 실제로 박혀 있는 것*만 추적한다. 마지막 갱신: **2026-08-10**
> (직전 갱신 2026-04-29 판은 설계·구현 초기 스냅샷이라 langgraph SDK·port 2025
> sidecar·P0~P10 phase 표 등 현행과 어긋나 전면 재작성 — 옛 판은 git history).
>
> - **무엇을 해야 하나**(초기 결정) → 설계문 `00_PRINCIPLES` ~ `05_DATA`
> - **전송층 계약 정본** → medi-back [`docs/frontend_chat_v2.md`](../../medi-back/docs/contracts/frontend_chat_v2.md)
> - **최근 변경** → [`PATCHNOTE.md`](./PATCHNOTE.md) (날짜별 단일 타임라인)
> - **현재 무엇이 있나** → 본 문서

---

## 1. 스택

| 층 | 채택 |
|---|---|
| 프레임워크 | **Next.js 15.5 App Router** · React 19 · TypeScript strict |
| 스타일 | **Tailwind v4**(`@theme`) + `--md-*` CSS 변수 토큰 · Material Symbols · Pretendard/Inter/JetBrains Mono |
| UI 프리미티브 | shadcn 6종(button·dialog·popover·scroll-area·tooltip·confirm-dialog, Radix backed) — **lucide 미사용**(아이콘은 Material Symbols 단일 셋) |
| 인증 | **NextAuth**(Credentials + Email 매직링크) + **Prisma / PostgreSQL(`medi_auth`)** |
| URL 상태 | nuqs |
| 토스트 | sonner |
| 전송층 | **자체 SSE + fetch REST** (`@langchain/langgraph-sdk` 는 2026-07-14 ADR-0001 로 은퇴) |

## 2. 런타임 토폴로지

```
브라우저
   │  ① 로그인 — NextAuth (Credentials / Email 매직링크)
   │     세션 JWT 에 accessToken 동봉 → AuthProvider 가 in-memory store 로 sync
   ▼
medi-front (Next.js, GCP VM · docker compose · medi-net)   ※ Vercel 아님
   ├── Next 서버측: /api/auth/*(NextAuth) · signup-init · set-password · forgot-password
   │      └── Prisma → Postgres `medi_auth` (medi-back 과 같은 medi-postgres 인스턴스)
   └── 브라우저측: Authorization: Bearer <accessToken> 로 medi-back 직접 호출
                    ├── POST /chat            (SSE 스트리밍)
                    ├── POST /reports + 폴링   (심층 보고서)
                    └── REST (/article ·/law-graph ·/bookmarks ·/me/* ·/admin/* …)
```

- 배포: `main` push → GHA `Deploy medi-front`(self-hosted runner, `<runner-label>`) → `docker compose build/up`.
  기동 순서 보장: `medi-front-migrate`(prisma migrate deploy, 1회 실행 후 종료)가 성공해야 앱 컨테이너가 뜬다.
- `NEXT_PUBLIC_*` 는 **빌드 시 클라이언트 번들에 inline** — 값 바뀌면 `--no-cache` 재빌드 필요(deploy.yml 이 그렇게 함).
- 백엔드 base URL = `NEXT_PUBLIC_DEPLOYMENT_URL`(env-first) → SettingsDialog localStorage override(dev) 순.

## 3. 라우트 맵 (`src/app/`)

| 그룹 | 경로 | 내용 |
|---|---|---|
| `(chat)` | `/`, `/new` | 메인 채팅 셸(PageShell) — 인증 필요 |
| `(auth)` | `/login`, `/signup`, `/auth/set-password`, `/auth/verify`, `/auth/email-preview` | 로그인·가입·비번 설정·매직링크 발송 안내 |
| `admin` | `/admin`(→stats), `/admin/{stats,users,beta,feedback,pii,announcements,questions,threads,settings}` | 관리자 — 공통 `layout.tsx` 가 is_admin 가드 + 탭 nav. `pii`=마스킹 라벨링, `announcements`=패치노트 발행(2026-08-13) |
| `landing` | `/landing` + `/landing/{basic,regia,medra}` | 소개 페이지(본편 + 테마 시안 3종) |
| 법적/기타 | `/terms`, `/privacy`, `/maintenance` | 약관·방침(백엔드 `GET /legal/{doc}` 정본 렌더) · 점검 화면 |
| API(서버) | `/api/auth/[...nextauth]`, `/api/auth/{signup-init,set-password,forgot-password}`, `/api/admin/test-accounts` | NextAuth + 가입 부트스트랩 |

**인증 경로 3층**
1. `src/middleware.ts` — `withAuth`: 미인증 → `/login`, `hasPassword=false` → `/auth/set-password` 강제(루프 방지 예외 포함). dev 우회는 `NEXT_PUBLIC_AUTH_BYPASS`/`DUMMY_MODE`(production 강제 OFF).
2. `AuthProvider` — SessionProvider + `session.accessToken` → `lib/client/authToken` in-memory store 동기(변경 시 이벤트 발화).
3. 백엔드 — 같은 JWT 를 medi-back `AuthMiddleware` 가 검증(`NEXTAUTH_SECRET` 공유). **권위 경계는 백엔드**(FE 라우트 하드블록은 락아웃 리스크로 제거, 메뉴 비노출은 UX 레벨).

가입 게이트: `lib/betaGate.ts` 가 백엔드 `POST /beta/check` 로 판정(진실원=백엔드 화이트리스트 env ∪ DB). 백엔드 실패 시 front env 폴백, 폴백 불가면 **fail-closed**.

## 4. 전송층 (`src/lib/client/`, `src/lib/api/`)

| 모듈 | 책임 |
|---|---|
| **`chatApi.ts`** | 채팅 SSE — `fetch` + `ReadableStream` 직접 파싱. 이벤트 8종: `meta` · `pii_notice`(+`masked_text` — 오탐 신고 토스트 재료, 2026-08-13) · `token` · `tool_progress` · `step_lifecycle` · `steps` · `clarify` · `error` · `done`. 계약 정본은 medi-back `frontend_chat_v2.md` §2 |
| **`api/client.ts`** | REST 단일 wrapper `apiFetch` — base URL·Bearer 자동 주입, DUMMY 모드 `mockFetch` 인터셉트, 에러 정합(`ApiError.status/body`) |
| `threads.ts` `article.ts` `annex.ts` `lawGraph.ts` `bookmarks.ts` `reports.ts` `files.ts` `legal.ts` `privacy.ts` `quota.ts` `prefs.ts` `admin.ts` | 도메인별 REST 호출 — 전부 `apiFetch` 재사용 |
| `authToken.ts` | in-memory 토큰 store(+변경 이벤트) |
| `mockFetch.ts` / `dummy.ts` | `NEXT_PUBLIC_DUMMY_MODE=true` — `public/mocks/*.json` 및 fake 스트림으로 백엔드 없이 UI 구동 |

**정지·재시도**: 정지는 SSE fetch abort(서버가 턴 워커 취소), clarify 응답은 별도 resume 프로토콜이 아니라 **일반 메시지 전송**(턴 종료형 신계약).

## 5. 상태 (`src/lib/store/`, `src/lib/parse/`)

| 모듈 | 책임 |
|---|---|
| `useChatState.ts` | 채팅 상태 훅 — send/stop/retry, 스레드 리로드(`GET /chat/{tid}/state`), 보고서 목록·폴링, 첨부 합성, 스트림 무응답 타임아웃 |
| `turns.ts` | SSE chunk 디스패처 — `applyMeta/applyMessageChunk/applyToolProgress/applyValues/applyError/applyInterrupt` + `settleAfterStream` |
| `derive.ts` | Turn **증분** 파생(human 새로 오면 Turn append, step.id 매칭으로 증분) — 매 chunk 전체 재계산 안 함 |
| `citation.ts` | 본문 `[n]` → Citation chip 토큰화(`\[1\]` escape 는 평문) |
| `nextSteps.ts` | 답변 말미 `<next_steps>` JSON 블록 파싱 → 추천질문 카드(**채널 분리** 계약) |
| `lawLink.ts` | 인용 → 법령정보센터 deep-link 도출(13분야 path 패턴, `LAW_GO_KR_LINKS.md` 가 권위 원천) |
| `rightPanel.tsx` | 우측 패널 ephemeral 상태(open/citation/docPath) — **URL 에 안 박음**(threadId 만 URL) |
| `savedCitations.tsx` | 북마크 citation_id 셋 공유(버튼 초기 상태 정확화) |
| `recentArticles.ts` | 최근 열람 조문 10건(localStorage) → 커맨드 팔레트 |
| `useUsage.ts` | `/me/usage` 30초 폴링(탭 inactive 시 중단, 실패는 silent) |
| `settings.ts` | env-first + localStorage override 머지 |
| `types/` | `chat.ts` `citation.ts` `deep.ts` `report.ts` `state.ts` — 전부 snake_case(백엔드 정합) |

## 6. 컴포넌트 인벤토리 (`src/components/`)

| 디렉터리 | 구성 |
|---|---|
| `shell/` | PageShell(3-pane) · CommandPalette(Ctrl+K) · MaintenanceGate · LoadBadge(`/load` 혼잡) · UsageBadge · NotificationBell · FeatureTour · ThemeToggle/ThemeLogo · InlineErrorBanner · TokenFeedbackPrompt |
| `chat/` | Turn · UserMessage · **StepCarousel**(한 턴의 step 단일 카드 탐색) · TurnAnswer · MarkdownContent · CitationFootnotes · **ConfidenceBadge**(verified 비율 배지) · CitationEvidenceTooltip · CiteHighlightContext · NextStepsCard · ReportCardGroup / ReportPreviewDialog · ArticleModal / AnnexModal · LawGraph2D / LawGraphPanel · BookmarkButton / BookmarksDialog · ProcedureTimeline · LiveSearchGlass · FeedbackButtons · ChatInput(첨부·드래그&드롭·글자수) · ChatScroll · EmptyHero · ThreadTitleHeader · ThreadLoadingBanner · InterruptCard · ArtifactCard |
| `panel/` | RightPanel(모드 분기) · CitationInspector · ArtifactViewer |
| `thread/` | ThreadList(검색·핀·이름변경·삭제·페이지네이션) |
| `admin/` | common(ErrorBanner·PillTab·StatCard·Spinner) · use-confirm · scope-toggle · notice-composer |
| `legal/` | ConsentGate(동의 서버 영속) · LegalShell / LegalDocPage · DisclaimerHint |
| `settings/` | SettingsDialog · PrivacyDialog |
| `providers/` | AuthProvider |

## 7. 데이터 흐름 (fast 한 턴)

```
ChatInput(Enter)
   └─► useChatState.send()  ── POST /chat (SSE, Bearer)
            │
            ▼  chatApi.ts: fetch + ReadableStream 파싱
       meta → pii_notice → tool_progress* → step_lifecycle/steps* → token* → done
            │
            ▼  turns.ts 디스패처(채널별 apply*)
            ▼  derive.ts 증분 파생 → Turn[]
            │
   ┌────────┼──────────────┬─────────────────┐
   ▼        ▼              ▼                 ▼
UserMessage StepCarousel  TurnAnswer        RightPanel
                          ├ MarkdownContent(+[n] chip)
                          ├ CitationFootnotes / ConfidenceBadge
                          └ NextStepsCard
```

**deep(보고서)**: `POST /reports` + `idempotency_key(^rpt_…)` → `GET /reports/runs/{key}` 폴링(대기 순번 `queue_ahead`) → 완료 시 토스트·사이드바·우측 패널. **채팅 스트림과 무관하게 병렬**(2026-07-25 백엔드 분리) — 대화록에 보고서가 append 되지 않는다.

## 8. URL 상태 (nuqs)

| 키 | 의미 |
|---|---|
| `?threadId=<id>` | 활성 thread (유일하게 URL 에 남는 상태) |

인용 인스펙터·산출물 뷰어는 URL 이 아니라 `rightPanel` Context 로 관리(새로고침 시 자연히 닫힘).

## 9. 스타일

`src/styles/globals.css` — `--md-*` Material 토큰(라이트/다크) + `@theme` 매핑으로 `bg-md-*`/`text-md-*` 자동 생성 + 시맨틱 별칭(success·warning·info·revoked) + 모션 토큰 + `prefers-reduced-motion` 정지 + focus-visible 링. 랜딩 테마 변종은 `.theme-cta-bg`·`.theme-grad-text` 유틸과 `.claude/skills/medi-front-theme-*` 가이드.

## 10. 검증

```bash
npx tsc --noEmit          # 타입
npm run lint              # eslint
npm run build             # prisma generate + next build
```
CI(`.github/workflows/ci.yml`)가 lint+typecheck / build 두 잡으로 강제.

내부 규약 grep(0건 유지): 내부 노드명 노출(`web-analyst|rag-analyst|main-planner|writer-agent`) · camelCase 필드(`toolName|inputPreview|…`) · globals.css 밖 raw hex.

## 11. 본 문서 갱신 규칙

- 컴포넌트/모듈 추가 → §5·§6 표에 행 추가.
- 라우트 추가 → §3 표에 행 추가.
- **코드와 어긋나면 본 문서를 고친다**(설계문이 아니라 현재 상태 기록).
- 날짜별 변경 서술은 여기 쌓지 말고 `PATCHNOTE.md` 로.
