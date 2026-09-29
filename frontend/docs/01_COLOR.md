# 01 · COLOR — 팔레트와 시맨틱 토큰

전제: `00_PRINCIPLES.md` §5 시각 정체성 차용. 출처: `../deep-agents-ui-custom/design/DESIGN.md` + `../deep-agents-ui-custom/design/code.html`.

본 문서는 **확정 hex값 + CSS 변수 이름 + 사용처** 박는다. 옵션 없음.

---

## 1. 팔레트 (Material — light mode)

### 1.1 Primary — Teal

| 토큰 | hex | 사용 |
|---|---|---|
| `--md-primary` | `#00685f` | primary 액션, 활성 상태, 진행 dot |
| `--md-on-primary` | `#ffffff` | primary 위 텍스트 |
| `--md-primary-container` | `#008378` | ActiveAgentCard 배경 |
| `--md-on-primary-container` | `#f4fffc` | container 위 텍스트 |
| `--md-primary-fixed` | `#89f5e7` | 강조 배지 배경 |
| `--md-primary-fixed-dim` | `#6bd8cb` | 보조 강조 |
| `--md-on-primary-fixed` | `#00201d` | fixed 위 텍스트 |
| `--md-on-primary-fixed-variant` | `#005049` | fixed-dim 위 텍스트 |
| `--md-inverse-primary` | `#6bd8cb` | 다크 표면 위 primary |
| `--md-surface-tint` | `#006a61` | 미세 tint 오버레이 |

### 1.2 Secondary — Indigo

| 토큰 | hex | 사용 |
|---|---|---|
| `--md-secondary` | `#4e45d5` | 보조 액션, 노드/링크 강조 |
| `--md-on-secondary` | `#ffffff` | |
| `--md-secondary-container` | `#6860ef` | secondary 배지 배경 |
| `--md-secondary-fixed` | `#e3dfff` | |
| `--md-secondary-fixed-dim` | `#c3c0ff` | |

### 1.3 Tertiary — Burnt orange (warning-ish 액센트)

| 토큰 | hex | 사용 |
|---|---|---|
| `--md-tertiary` | `#924628` | 도메인 강조, hot indicator |
| `--md-on-tertiary` | `#ffffff` | |
| `--md-tertiary-fixed` | `#ffdbce` | 따뜻한 배지 배경 |
| `--md-tertiary-fixed-dim` | `#ffb59a` | |

### 1.4 Surface (계층)

| 토큰 | hex | 사용 |
|---|---|---|
| `--md-surface` | `#faf8ff` | 페이지 본문 배경 |
| `--md-surface-dim` | `#d2d9f4` | 강조 surface |
| `--md-surface-bright` | `#faf8ff` | (= surface) |
| `--md-surface-container-lowest` | `#ffffff` | 카드(가장 밝음) |
| `--md-surface-container-low` | `#f2f3ff` | 카드 보조, 우측 패널 본문 |
| `--md-surface-container` | `#eaedff` | 헤더, 메타 영역 |
| `--md-surface-container-high` | `#e2e7ff` | hover 상태 카드 |
| `--md-surface-container-highest` | `#dae2fd` | 가장 진한 surface |
| `--md-surface-variant` | `#dae2fd` | 보조 표면 |

### 1.5 텍스트·outline

| 토큰 | hex | 사용 |
|---|---|---|
| `--md-on-surface` | `#131b2e` | 본문 텍스트 |
| `--md-on-surface-variant` | `#3d4947` | 보조 텍스트 / 라벨 |
| `--md-on-background` | `#131b2e` | (= on-surface) |
| `--md-outline` | `#6d7a77` | 진한 outline (강조 보더) |
| `--md-outline-variant` | `#bcc9c6` | 일반 카드 1px 보더 |
| `--md-inverse-surface` | `#283044` | 다크 인버스 표면 |
| `--md-inverse-on-surface` | `#eef0ff` | inverse 위 텍스트 |

### 1.6 Error

| 토큰 | hex | 사용 |
|---|---|---|
| `--md-error` | `#ba1a1a` | 에러 텍스트·아이콘 |
| `--md-on-error` | `#ffffff` | |
| `--md-error-container` | `#ffdad6` | 에러 배지 배경 |
| `--md-on-error-container` | `#93000a` | container 위 텍스트 |

---

## 2. 시맨틱 별칭 (앱 컨벤션)

success/warning/info는 Material 팔레트 안에서만 별칭으로 정의한다. **별도 hex 신설 없음** — `00_PRINCIPLES §5.1` "팔레트 그대로 차용" 원칙.

| 토큰 | 값 | 사용 |
|---|---|---|
| `--md-success` | `var(--md-primary)` | 완료 dot, 성공 토스트 (= teal) |
| `--md-warning` | `var(--md-tertiary)` | running dot, 주의 (= 테라코타) |
| `--md-info` | `var(--md-secondary)` | 정보성 배지 (= indigo) |
| `--md-revoked` | `var(--md-error)` | **폐지·상충·만료된 *근거*** (도메인 의미 — `00 §1.1`) |

`--md-revoked`는 *근거 자체가 무효*임을 표시하는 도메인 의미층. 일반 시스템 에러(네트워크·인증)에는 `--md-error`를 그대로 쓴다.

---

## 3. 상태 색 (UI 컴포넌트 매핑)

`03_COMPONENTS.md` / `04_ELEMENTS.md` 사용 시 표준.

| 상태 | dot | text | bg(배지 시) |
|---|---|---|---|
| **running** | `--md-warning` (pulse) | `--md-on-surface` | `--md-tertiary-fixed` |
| **done** | `--md-success` | `--md-on-surface` | `--md-primary-fixed` |
| **error** | `--md-error` | `--md-error` | `--md-error-container` |
| **interrupted** | `--md-tertiary` (pulse) | `--md-on-surface` | `--md-tertiary-fixed` |
| **streaming** | `--md-secondary` (pulse) | `--md-on-surface` | `--md-secondary-fixed` |
| **idle / pending** | `--md-outline` | `--md-on-surface-variant` | `--md-surface-container` |
| **active selection** | `--md-primary` | `--md-on-surface` | `--md-surface-container-lowest` + `--md-primary` 보더 |

---

## 4. shadcn HSL 매핑 (호환 레이어)

기존 shadcn 컴포넌트(Button, Dialog 등) 호환. CSS 변수 동일 raw 값 가리키게.

| shadcn 변수 | HSL | 가리키는 Material |
|---|---|---|
| `--background` | `252 100% 98%` | `--md-surface` (`#faf8ff`) |
| `--foreground` | `224 39% 13%` | `--md-on-surface` |
| `--card` | `0 0% 100%` | `--md-surface-container-lowest` |
| `--popover` | `0 0% 100%` | 동 |
| `--primary` | `174 100% 20%` | `--md-primary` (`#00685f`) |
| `--primary-foreground` | `0 0% 100%` | `--md-on-primary` |
| `--secondary` | `244 65% 55%` | `--md-secondary` |
| `--secondary-foreground` | `0 0% 100%` | `--md-on-secondary` |
| `--muted` | `240 100% 96%` | `--md-surface-container-low` |
| `--muted-foreground` | `174 9% 27%` | `--md-on-surface-variant` |
| `--accent` | `240 100% 92%` | `--md-surface-container-high` |
| `--destructive` | `0 75% 42%` | `--md-error` |
| `--border` | `169 14% 76%` | `--md-outline-variant` |
| `--ring` | `174 100% 20%` | `--md-primary` |
| `--sidebar` | `240 100% 96%` | `--md-surface-container-low` |

---

## 5. 그림자

`00_PRINCIPLES §5` "그림자 최소" 원칙 — outline + tonal layer 우선. 그림자는 오버레이/팝오버에만.

| 토큰 | 값 |
|---|---|
| `--shadow-popover` | `0 4px 12px rgba(0, 0, 0, 0.05)` |
| `--shadow-card` | `none` (1px outline로 분리) |
| `--shadow-card-active` | `0 2px 6px rgba(0, 0, 0, 0.05)` (선택된 카드) |

---

## 6. 다크 모드

**1차 미적용**. 시스템 `prefers-color-scheme: dark`일 때 현행 값 유지(보기 가능, 정밀 조정 안 함).

다크 토큰 정밀 정의는 v1.1 별도 문서.

---

## 7. 사용 금지 / 폐기

- `tailwind.config.mjs`에 정의되지 않은 변수 참조 금지 (`var(--bg-primary)` 같은 dangling)
- 핫핑크·네온 등 팔레트 외 색 금지 (강조 필요 시 `--md-tertiary` 사용)
- `--color-user-message-bg` 같은 도메인 특수 토큰 신규 추가 금지 — Material 토큰 재사용

---

## 8. 라이트 정의 위치

- 모든 `--md-*` 변수는 `globals.css :root` 한 곳에서 정의.
- shadcn HSL은 동일 `:root` 안에서 `--md-*` 와 정합되게 정의.
- Tailwind 클래스 별칭(`bg-md-primary` 등)은 `tailwind.config.mjs` `extend.colors`에서 매핑.

---

## Changelog
- 2026-04-27 v0.1 — 팔레트 hex 확정, shadcn HSL 매핑.
- 2026-04-28 v0.2 — `../design/` 경로 정정. `--md-success`(emerald `#10b981`)·`--md-warning`(amber `#f59e0b`) 신규 hex 제거 → Material 토큰 별칭(`--md-primary`/`--md-tertiary`)으로 회수. 도메인 의미 토큰 `--md-revoked`(=`--md-error`) 추가.
