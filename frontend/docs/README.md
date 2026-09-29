# medi-front 문서 인덱스

> **정합성 원칙(2026-08-10 정리)**: 이 인덱스에 있는 문서만 현행. 완료된 설계기 task
> 목록·구계약·조사 기록은 [`archive/`](./archive/)로 옮기고 각 파일 상단에 사유 배너를
> 달았다. 날짜별 변경 서술은 [`PATCHNOTE.md`](./PATCHNOTE.md) 가 단일 타임라인이다.

## 현행 문서

| 문서 | 누구를 위한 | 핵심 내용 |
|---|---|---|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | 개발 | ⭐**현재 구현 상태 정본** — 스택·런타임 토폴로지·라우트 맵·인증 3층·전송층(SSE/REST)·상태 모듈·컴포넌트 인벤토리·데이터 흐름 |
| [`PATCHNOTE.md`](./PATCHNOTE.md) | 전원 | ⭐날짜별 변경 누적(최신이 위) — 기능·디자인·인증·버그 |
| [`FEATURES.md`](./FEATURES.md) | PM·개발 | 페이지·기능 인벤토리(수정 요청 시 영역 식별용) |
| [`USER_GUIDE.md`](./USER_GUIDE.md) | 사용자 | 의료 종사자 대상 사용법(개발 지식 불필요) |
| [`MAINTENANCE.md`](./MAINTENANCE.md) | 개발 | 코드 건강성·운영 가시성 개선 로드맵 + 적용 완료 기록 |
| [`BACKEND_REQUESTS.md`](./BACKEND_REQUESTS.md) | 프런트↔백 | medi-back 향 요구사항과 진행 상태 |
| [`LAW_GO_KR_LINKS.md`](./LAW_GO_KR_LINKS.md) | 프런트·백 공용 | 법령정보센터 13분야 deep-link URL 패턴(권위 원천) |
| [`design_guide.md`](./design_guide.md) | 디자인 | 랜딩 디자인 시스템(CSS 변수·컴포넌트 스니펫) |

## 설계 결정문 (초기 — `00`~`05`)

작성 시점(2026-04~05)의 **결정 기록**이다. 현재 코드와 어긋나면 `ARCHITECTURE.md` 가 이긴다.

| 문서 | 무엇이 박혀 있나 |
|---|---|
| [`00_PRINCIPLES.md`](./00_PRINCIPLES.md) | 멘탈 모델·사용자·비목표·성공 기준·범위 |
| [`01_COLOR.md`](./01_COLOR.md) | 팔레트·시맨틱 토큰·상태 색·라이트/다크 |
| [`02_LAYOUT.md`](./02_LAYOUT.md) | 페이지 셸·영역 폭/여백·RightPanel 두 모드·반응형 |
| [`03_COMPONENTS.md`](./03_COMPONENTS.md) | 1차 컴포넌트 사양 |
| [`04_ELEMENTS.md`](./04_ELEMENTS.md) | 타이포 스케일·아이콘·애니메이션·상태 표현 |
| [`05_DATA.md`](./05_DATA.md) | 백엔드 인터페이스 초안 — ⚠️ **현행 계약 정본은 medi-back [`docs/frontend_chat_v2.md`](../../medi-back/docs/contracts/frontend_chat_v2.md)** |

## 백엔드 쪽에서 봐야 하는 문서

| "나는 ..." | 읽을 것 |
|---|---|
| /chat SSE 이벤트 payload 를 정확히 알아야 | medi-back `docs/frontend_chat_v2.md` §2 |
| 보고서 트리거·폴링 계약 | medi-back `docs/frontend_chat_v2.md` §4 |
| 엔드포인트·에러 코드 전체 | medi-back `docs/API.md` |
| 시스템 전체 그림 | medi-back `docs/architecture.md` |
| 시스템을 남에게 설명해야 | medi-back [`docs/onboarding.md`](../../medi-back/docs/guide/onboarding.md) |

## 아카이브 ([`archive/`](./archive/))

완료된 설계기 문서·구계약·조사 기록. 각 파일 상단 배너에 아카이브 사유와 현행 대체 문서
링크가 있다. 이력 추적은 `git log -- docs/`.

| 파일 | 사유 |
|---|---|
| `IMPLEMENTATION.md` | P0~P10 task 목록 — 전 phase 종료 |
| `E2E_SCENARIOS.md` | phase1 검증 시나리오 — 구 deep 모델 기준 |
| `LEXDIFF_LEARNINGS.md` | 외부 프로젝트 조사(2026-04-29) |
| `auth_db_postgres_migration.md` | 인증 DB 이관 런북 — 2026-07-15 컷오버 완료 |
| `DEEP_PROGRESS.md` · `report_pipeline_step_emission.md` | 구 deep 진행 UI 계약 |
| `legal_draft.md` · `theme_preference_stats.md` | 초안·일회성 조사 |

> `TESTBED.local.md` 는 로컬 전용 메모(버전 관리 대상 아님).
