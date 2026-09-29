# 02 · LAYOUT — 페이지 셸과 영역

전제: `00_PRINCIPLES.md`. 색은 `01_COLOR.md`.

본 문서는 **영역 폭/여백/반응형 동작**을 픽셀 단위로 박는다.

---

## 1. 페이지 골격

```
┌─────────────────────────────────────────────────────────────────────┐
│ Header — h-14 (56px)                                                │
├──────┬─────────────────────────────────────┬────────────────────────┤
│      │                                     │                        │
│ Th   │                                     │   RightPanel           │
│ rea  │       Chat (max-w 720px center)     │   (조건부, 두 모드만)  │
│ ds   │       단계 카드 + 답변 + 인용·산출물 │     a) Citation        │
│      │       모두 인라인                    │     b) Artifact        │
│ List │                                     │                        │
│      │                                     │                        │
└──────┴─────────────────────────────────────┴────────────────────────┘
```

- **헤더 1줄(56px)** + **본문 1줄** = 화면 전체.
- 본문 = 좌(ThreadList) | 중(Chat) | 우(RightPanel).
- ThreadList: 헤더 토글 (열림/닫힘).
- **RightPanel: 기본 닫힘**. 사용자가 인용 칩 또는 산출물 카드를 클릭할 때만 열린다.
- 채팅 본문은 항상 보인다.

---

## 2. 영역 폭 (data-state별 비율)

`react-resizable-panels` 사용 가정. `autoSaveId`로 사용자 드래그 폭 보존.

기본은 RightPanel 닫힘. 인용 칩 / 산출물 카드 클릭 시 열린다.

| 모드 | ThreadList | Chat | RightPanel |
|---|---|---|---|
| **A. ThreadList + Chat (default)** | 25% (min 320px) | 75% | 0 (hidden) |
| **B. Chat only** | 0 | 100% | 0 (hidden) |
| **C. ThreadList + Chat + Citation** | 22% | 42% | 36% (min 360px) |
| **D. ThreadList + Chat + Artifact** | 22% | 30% | 48% (min 480px, max 60vw) |
| **E. Chat + Citation (TL 닫힘)** | 0 | 64% | 36% |
| **F. Chat + Artifact (TL 닫힘)** | 0 | 52% | 48% |

전환 트리거:
- ThreadList: 헤더 `Threads` 토글
- RightPanel:
  - **인용 칩 `[n]` 클릭** → C 또는 E 모드 (Citation 모드)
  - **산출물 카드 클릭** → D 또는 F 모드 (Artifact 모드)
  - 다른 모드 활성 중 트리거 시 **모드 swap** (예: Citation 보던 중 산출물 카드 클릭 → Artifact로 전환)
  - RightPanel 헤더의 ✕ → 닫힘 (A/B 복귀)
- 사용자 드래그 폭은 모드별로 저장.

---

## 3. Chat 콘텐츠 폭

- `max-width: 720px` (가독성 우선, 의료 보고서엔 충분).
- 좌우 패딩 `px-6` (24px).
- 한 줄 최대 약 80자 한국어 / 110자 영문.
- 입력창은 동일 max-width, 하단 sticky.

---

## 4. Right Panel 내부 레이아웃 (두 모드, 슬롯 공유)

기본 닫힘. 열렸을 때 **하나의 모드만** 표시한다 — 두 모드는 같은 슬롯을 공유.

### 4.1 Mode A — Citation Inspector (인용 칩 클릭 시)

```
┌─────────────────────────────────────────┐
│ ← Back · Citation [3] · ✕              │  h-12 (48px)
├─────────────────────────────────────────┤
│                                         │
│ 출처 메타                                │
│  · 문서 제목 / URL                       │
│  · 발행기관 / 일자                       │
│  · 조항·페이지 (RAG일 때)                │
│                                         │
│ ─────                                   │
│                                         │
│ 본문 스니펫 (markdown)                  │
│ "...광고 시 다음 사항을 표시해야..."     │
│                                         │
│ ─────                                   │
│                                         │
│ [📄 원문 열기] [↗ 외부 링크]            │
│                                         │
└─────────────────────────────────────────┘
```

폭: 36% (min 360px). 사용자 드래그 가능.

### 4.2 Mode B — Artifact Viewer (산출물 카드 클릭 시)

```
┌─────────────────────────────────────────┐
│ ← Back · 📄 file.md · ⏳ Generating · ✕ │  h-12 (48px)
├─────────────────────────────────────────┤
│                                         │
│ Markdown 본문 (풀뷰)                     │
│ # 보고서 제목                            │
│ ## 1. 개요                               │
│ ...                                     │
│ (스트리밍 중이면 partial + caret)        │
│                                         │
└─────────────────────────────────────────┘
```

폭: 48% (min 480px, max 60vw). Mode A보다 넓다 — 보고서 가독성 우선.

### 4.3 모드 전환

- 닫힘 상태에서 인용 칩 클릭 → Mode A로 슬라이드인
- 닫힘 상태에서 산출물 카드 클릭 → Mode B로 슬라이드인
- Mode A 활성 중 다른 인용 칩 클릭 → 같은 슬롯에서 콘텐츠 교체
- Mode A 활성 중 산출물 카드 클릭 → Mode B로 swap (폭 36% → 48% transition)
- Mode B 활성 중 다른 산출물 카드 클릭 → 같은 슬롯에서 콘텐츠 교체
- Mode B 활성 중 인용 칩 클릭 → Mode A로 swap (폭 48% → 36% transition)
- ✕ 또는 ← Back → 닫힘 (Chat이 풀폭 복귀)

### 4.4 진행 timeline 위치

**우측 패널에 두지 않는다** (`00_PRINCIPLES §2`).
진행 단계는 **채팅 본문 안 인라인 단계 카드**(`03_COMPONENTS §4`)로만 본다.

---

## 5. URL 상태 매핑

| URL 키 | 값 | RightPanel 모드 |
|---|---|---|
| (없음) | — | 닫힘 (A/B 모드) |
| `?citation=<id>` | citation id 또는 `{turnId}:{number}` | A — Citation Inspector |
| `?docPath=<path>` | 산출물 경로 | B — Artifact Viewer |

두 키는 **상호 배타** — 둘 중 하나만 set. 새 모드 트리거 시 다른 키 자동 clear.

슬라이드 transition: 300ms ease-out (폭 변화 + 콘텐츠 cross-fade).

---

## 6. 헤더 (h-14, 56px)

```
[Logo · Threads🔘]              [Assistant: name · ⚙ · ＋ New Thread]
```

| 좌측 | 우측 |
|---|---|
| 앱 제목 (`text-h2`) | Assistant 이름 (`text-body-sm` muted) |
| Threads 토글 (**항상 표시** — 열림/닫힘 상태를 `aria-pressed`로 노출) | Settings 버튼 (⚙ 아이콘) |
|   | New Thread 버튼 (primary 색) |

- Work 토글 없음 — RightPanel은 사용자 인터랙션(인용/산출물 클릭)으로만 열린다.
- 헤더 하단 1px `--md-outline-variant` 보더.
- 좌우 padding `px-6`.
- 토글은 outline 버튼 (눌리면 secondary fill).

---

## 7. 사이드바 (ThreadList)

좌측 패널 안 구조:

```
┌──────────────────┐
│ Logo + 부제      │  pad 16
│                  │
│ [+ 새 thread]    │  primary 버튼
├──────────────────┤
│ 검색 input       │  optional v1.1
├──────────────────┤
│                  │
│ Recent Threads   │  caps label
│   · Thread 1     │
│   · Thread 2     │
│                  │
├──────────────────┤
│ Settings  Docs   │  하단 footer 링크
└──────────────────┘
```

- 폭 22% (min 320px).
- 내부 ScrollArea (Recent Threads).
- Active thread는 좌측 2px primary 보더 + bg `--md-surface-container-lowest`.

---

## 8. 스페이싱 토큰 (4px 베이스라인)

`tailwind.config.mjs` extend.spacing:

| 토큰 | 값 | 용도 |
|---|---|---|
| `unit` | 4px | 가장 작은 단위 |
| `gutter` | 16px | 영역 간 |
| `card-padding` | 20px | 카드 내부 |
| `margin-container` | 32px | 섹션 사이 큰 여백 |
| `stack-gap` | 12px | 카드 stack 간 |

기본 padding 매트릭스 (Tailwind 단위로):

| 영역 | padding |
|---|---|
| 헤더 좌우 | `px-6` (24) |
| 채팅 본문 좌우 | `px-6` |
| 우측 패널 좌우 | `px-3` (12) |
| 카드 내부 | `p-card-padding` (20) |
| 입력창 내부 | `px-[18px] py-[14px]` |

---

## 9. Z-index 레이어

| 레이어 | z |
|---|---|
| 본문 | 0 |
| Sticky 배너 (thread loading 등) | 1 |
| Header | 10 |
| Toast (sonner) | 50 |
| Dialog overlay | 100 |
| Dialog | 110 |
| Tooltip | 200 |

---

## 10. 라운드 / 보더

| 컨텍스트 | radius | 보더 |
|---|---|---|
| 카드 | 8px (rounded-lg) | 1px `--md-outline-variant` |
| 카드 호버 | 8px | 1px `--md-primary` |
| 카드 액티브 | 8px | 1px `--md-primary` + bg `--md-surface-container-lowest` |
| 버튼 (default) | 4px (rounded) | 보더 없음 (배경 색만) |
| 버튼 (outline) | 4px | 1px `--md-outline-variant` |
| 칩/배지 | 9999px (rounded-full) | 1px `--md-outline-variant` (선택 시 primary) |
| 입력창 | 12px (rounded-xl) | 1px `--md-outline-variant`, focus 시 `--md-primary` |
| 다이얼로그 | 8px | 1px `--md-outline-variant` |

---

## 11. 반응형 (1차 범위)

| 너비 | 동작 |
|---|---|
| **>= 1280px** | A 모드 default (3-pane). |
| **1024px ~ 1280px** | A 가능하되 ThreadList min-width 부족 시 자동 B 모드. |
| **< 1024px** | ThreadList는 드로워(오버레이)로 전환, RightPanel은 모달 시트. (1차 범위 — 단순 구현, 정밀 모바일은 v2.) |
| **< 768px** | 1차 범위 밖 — 안내 페이지로 폴백 가능 (선택). |

---

## 12. 변경 절차

레이아웃 비율 / 폭 / 패딩 변경 시:
1. 본 문서 갱신
2. `03_COMPONENTS.md`에서 영향 받는 컴포넌트 재검토
3. 사용자 드래그 비율 저장 키(`autoSaveId`) 변경 시 마이그레이션 노트 추가

---

## Changelog
- 2026-04-27 v0.1 — 3-pane Resizable + 단일 컬럼 RightPanel + 문서 뷰어 슬라이드인 모드 확정.
- 2026-04-27 v0.2 — `00_PRINCIPLES v0.2` 반영. RightPanel = 두 모드(Citation / Artifact) 슬롯 공유, 기본 닫힘. Timeline 우측 패널 제거. 헤더 Work 토글 제거. URL 키 `?citation` 추가, `?docPath`와 상호 배타.
- 2026-04-28 v0.2.1 — §9 Z-index에서 `Sticky ActiveAgentCard` 잔재 제거.
- 2026-04-28 v0.2.2 — §6 Header — Threads 토글을 *항상 표시*로 수정(이전 "닫혀있을 때만 보임"은 사용자가 사이드바를 닫을 방법이 모호함). `aria-pressed`로 상태 노출. P1 구현과 정합.
