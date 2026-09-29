# 04 · ELEMENTS — 타이포·아이콘·애니메이션·상태

> v0.1 · 2026-04-28 · 초안
> 전제: `00_PRINCIPLES.md` v0.2, `01_COLOR.md` v0.2, `02_LAYOUT.md` v0.2.1, `03_COMPONENTS.md` v0.2.1.
> 본 문서는 *남은 디테일* — 글꼴 스케일, 아이콘 시스템, 모션, 비-컨텐츠 상태(empty / loading / error).

---

## 1. 타이포 스케일

원천: `../deep-agents-ui-custom/design/DESIGN.md` 그대로.

### 1.1 폰트 스택

| 용도 | 스택 |
|---|---|
| 본문/UI | `Inter, "Pretendard Variable", system-ui, -apple-system, sans-serif` |
| 모노 (코드·쿼리·타임스탬프) | `"JetBrains Mono", ui-monospace, "SF Mono", monospace` |

한국어는 Pretendard Variable 우선, 없으면 Inter 라틴 + 시스템 한글 fallback.

### 1.2 스케일 (값 박음)

| 토큰 | size | weight | line-height | letter-spacing | 사용 |
|---|---|---|---|---|---|
| `--text-h1` | 24 | 600 | 32 | -0.02em | 페이지 타이틀, EmptyHero 제목 |
| `--text-h2` | 18 | 600 | 24 | -0.01em | 섹션 헤더, 카드 타이틀 |
| `--text-body-base` | 14 | 400 | 20 | 0 | 본문 기본 (채팅·문서) |
| `--text-body-sm` | 13 | 400 | 18 | 0 | 보조·메타 |
| `--text-code` | 13 | 400 | 20 | 0 | 코드 블록·쿼리 (mono) |
| `--text-label-caps` | 11 | 700 | 16 | 0.05em (uppercase) | 카드 헤더 라벨, References 헤딩 |

채팅 본문은 `--text-body-base`, 한 줄 ≤ 72ch (`00 §5.2` 가독성).

### 1.3 가중치 사용 정책

- `400` — 본문 기본.
- `500` — 버튼, 활성 thread 제목, **StepCard 헤더 라벨**.
- `600` — 헤더(h1/h2), 카드 제목, `label-caps`.
- `700+` 사용 금지 (`00 §5.1` "calm control" 위반).

### 1.4 컬러 적용 (요지)

| 위계 | 색 |
|---|---|
| 본문 기본 | `--md-on-surface` |
| 보조/메타 | `--md-on-surface-variant` |
| 인용 링크 텍스트 | `--md-secondary` |
| 진행 dot 옆 라벨 | `--md-on-surface` (dot이 색을 책임짐) |
| 폐지 근거 텍스트 | `--md-on-error-container` + **취소선** (`01 §2 --md-revoked`) |

---

## 2. 아이콘 시스템

### 2.1 단일 시스템

**Material Symbols Outlined** 단일 사용. lucide-react·기타 셋 혼용 금지(`00 §5.1` 정합).

### 2.2 변형 (weight · grade · optical size · fill)

| 컨텍스트 | weight | grade | opsz | fill |
|---|---|---|---|---|
| 본문 인라인 (헤더 dot 옆 등) | 400 | 0 | 20 | 0 |
| 헤더·툴바 버튼 | 400 | 0 | 24 | 0 |
| 활성/선택 상태 | 400 | 0 | 24 | **1** (filled) |
| EmptyHero 큰 영역 | 300 | 0 | 48 | 0 |

### 2.3 핵심 아이콘 매핑

| 의미 | 이름 |
|---|---|
| 새 thread / 추가 | `add` |
| 첨부 | `attach_file` |
| 전송 | `arrow_upward` |
| 정지(running 시 전송 자리) | `stop` |
| 설정 | `settings` |
| 검색 | `search` |
| 닫기 | `close` |
| 뒤로 | `arrow_back` |
| 외부 링크(↗) | `north_east` |
| 문서 일반 | `article` |
| 문서 PDF/특수 | `description` |
| EmptyHero 도메인 | `medical_services` |
| 펼침 / 접힘 | `expand_more` / `expand_less` |
| 주의 | `warning_amber` |
| 에러 | `error` |
| 완료 체크 | `check_circle` |
| 진행 dot | (아이콘 X — CSS `border-radius: 9999px`) |

새 아이콘은 본 표를 갱신하지 않으면 사용 금지.

### 2.4 크기·여백

| 토큰 | px | 사용 |
|---|---|---|
| `icon-sm` | 16 | 인라인·칩 안 |
| `icon-md` | 20 | 버튼·헤더 토글 |
| `icon-lg` | 24 | 헤더 액션 |
| `icon-xl` | 48 | EmptyHero |

아이콘 + 텍스트 시 gap `0.5em`(=4–6px).

---

## 3. 애니메이션

### 3.1 원칙

- **모션은 의미 있을 때만.** 장식 애니메이션 금지.
- `prefers-reduced-motion: reduce` 시 모든 transition·pulse 정지(즉시 상태 변경).
- 이징 기본: `cubic-bezier(0.2, 0, 0, 1)` (Material standard, decelerate).

### 3.2 모션 토큰

| 토큰 | duration | 사용 |
|---|---|---|
| `--motion-instant` | 0ms | hover 색 변경 |
| `--motion-fast` | 120ms | 버튼·input 보더 색, opacity 미세 |
| `--motion-base` | 200ms | StepCard 접힘/펼침, 모드 swap fade |
| `--motion-slow` | 300ms | RightPanel 폭 변화·슬라이드인 |

이징은 모두 standard. 새 duration이 필요할 때만 토큰을 추가한다.

### 3.3 핵심 모션

| 위치 | 동작 |
|---|---|
| StepCard 접힘/펼침 (`03 §4`) | 높이 transition `--motion-base`, content opacity `--motion-fast` |
| RightPanel 모드 swap (`02 §4.3`) | 콘텐츠 cross-fade `--motion-base` + 폭 transition `--motion-slow` 동시 |
| RightPanel 슬라이드인 (`02 §5`) | translateX(100%→0) + opacity, `--motion-slow` |
| 진행 dot pulse | `1.6s ease-in-out infinite` · opacity 1↔0.4 |
| 스트리밍 caret | 800ms blink · opacity 1↔0 |
| 토스트 등장·소멸 | `--motion-base` · 위에서 슬라이드 + fade |

### 3.4 자동 동작 타이밍 (`03 §4.4`와 정합)

| 트리거 | 지연 |
|---|---|
| step `running` 시작 | 즉시 자동 펼침 |
| step `done` 도달 | **1500ms 후** 자동 접힘 |
| TurnAnswer 등장 | StepCard collapse 끝난 후 200ms fade-in |

---

## 4. 비-콘텐츠 상태 (empty · loading · error)

### 4.1 Empty

| 영역 | 표현 |
|---|---|
| 채팅 (`messages=0`) | `EmptyHero` (`03 §10`) — `medical_services` 아이콘 + 환영 카피 + 예시 칩 3개 |
| ThreadList 비어있음 | "아직 대화가 없습니다" `--text-body-sm` `--md-on-surface-variant`, 가운데 정렬 |
| CitationInspector 메타 일부 누락 | 누락 행 자체 **미렌더** — 빈 라벨 금지 |
| References (인용 0개) | 박스 자체 미렌더 |

### 4.2 Loading

| 영역 | 표현 |
|---|---|
| 첫 thread fetch | `ThreadLoadingBanner` — 상단 sticky 1줄, `--md-surface-container-low` 배경 + 16px 스피너 + "대화를 불러오는 중…" |
| StepCard `running` | 헤더 dot pulse + label, 펼침 본문에 `input_preview`만 (output_preview 비어있음) |
| ArtifactViewer 스트리밍 | 본문 + caret pulse + 헤더 `Generating` 배지 |
| 작은 백그라운드 작업 | sonner 기본 스피너 |
| **금지** | 풀화면 spinner overlay — `00 §6 F-S2` "공백 로딩 화면 금지" |

### 4.3 Error

| 영역 | 표현 |
|---|---|
| 시스템(네트워크·인증·스트림 끊김) | 채팅 상단 sticky `InlineErrorBanner` — `--md-error-container` 배경, `--md-on-error-container` 텍스트, 우측 [재시도] |
| StepCard `error` | 헤더 dot `--md-error`, 펼침 본문에 백엔드 에러 메시지, 자동 접힘 X |
| 폐지된 인용 (도메인 — `01 §2 --md-revoked`) | Citation chip 배경 `--md-error-container`, 텍스트 `--md-on-error-container`, **취소선** + 툴팁 "폐지된 근거" |
| ArtifactViewer 빈·누락 | "(파일 없음)" `--md-on-surface-variant`, 가운데 |
| 토스트 | sonner `error` variant — `--md-error-container` 배경 |

### 4.4 토스트 vs 인라인 정책

- **시스템 상태** (저장 완료·전송 실패·인증 만료) → 토스트.
- **턴 결과·콘텐츠 상태** (검색 0건·인용 폐지 등) → 토스트 X. 채팅 안 카드/칩으로 표시.

---

## 5. 포커스·접근성 (최소)

| 항목 | 값 |
|---|---|
| 포커스 링 | `outline: 2px solid var(--md-primary); outline-offset: 2px;` |
| 키보드 진입 가능 | 버튼·링크·input·**StepCard 토글**·**Citation chip**·**ArtifactCard**·thread 항목 |
| `aria-live` | StepCard stack = `polite`, 토스트 = `assertive` |
| reduced-motion | `§3.1`에 따라 transition·pulse 정지 |
| 색만으로 구분 금지 | 진행/완료/오류는 dot **+ 아이콘 형태**도 함께(`done`은 `check_circle`, `error`는 `error` 아이콘) |

> 키보드 단축키 전체 표·focus order 등 상세는 후속 `06_INTERACTION.md`(README) 참조 — 본 문서는 토큰/원칙만.

---

## 6. 변경 절차

1. 타이포·모션 토큰(`§1.2`, `§3.2`) 추가·변경 시 `01_COLOR`·`03_COMPONENTS` 영향 검토.
2. 아이콘 추가는 `§2.3` 매핑표 갱신 후에만.
3. 새 모션은 `§3.2` 토큰 재사용 우선, 정말 필요할 때만 토큰 추가.

---

## Changelog
- 2026-04-28 v0.1 — 초안. Inter 단일·Material Symbols Outlined 단일·4단계 모션 토큰·empty/loading/error 정책 박음.
