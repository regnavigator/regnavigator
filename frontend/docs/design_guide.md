# Medra Design Guide

> 출처: `https://jiyaehwang.github.io/medra/medra-landing_6.html`
> 이 문서는 위 랜딩페이지의 디자인 시스템을 다른 페이지/사이트에 그대로 이식하기 위한 명세입니다. CSS 변수와 컴포넌트 스니펫을 그대로 복사해서 사용하세요.

---

## 1. Tone & Direction

- **무드**: 웜 아이보리 배경 + 짙은 포레스트 그린 액센트. 종이 같은 따뜻함과 테크 미니멀의 결합.
- **컨셉**: 클로즈드 베타의 한정성, 개발자 친화적 터미널 미학, 한국어 본문 + 영문 키커.
- **시그니처**:
  - 헤드라인의 한 구절만 `<em>`으로 강조 (이탤릭 또는 그린 컬러)
  - 모든 섹션이 영문 키커(eyebrow) → 한글 H2 → 한 줄 설명 순서
  - 숫자 인덱싱(01/02/03/04)은 항상 JetBrains Mono
  - CTA 텍스트는 항상 `→` 화살표로 끝남

---

## 2. Foundation

### 2.1 Fonts

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

- **Sora** (sans-serif): 본문, 모든 헤드라인, 폼 인풋
- **JetBrains Mono** (monospace): eyebrow, 배지, 터미널, 숫자(01/02), 날짜 라벨, 푸터, `@feedback` 워터마크

### 2.2 Color Tokens (CSS Variables)

```css
:root {
  --bg:           #F4F2ED;            /* 페이지 배경 (웜 아이보리) */
  --bg2:          #ECEAE3;            /* 보조 배경 (호버, workflow 섹션) */
  --ink:          #1A1916;            /* 본문/제목, 다크 섹션 배경 */
  --ink2:         #5A5850;            /* 보조 텍스트 */
  --ink3:         #9A9890;            /* 비활성/캡션 */
  --accent:       #1D4D3A;            /* 메인 그린: CTA, 강조, beta 배경 */
  --accent-light: #2D7A5C;            /* 호버 그린 */
  --accent-pale:  #DFF0E8;            /* 배지/태그 배경 */
  --accent-mid:   #A8D4BE;            /* 보더, 다크 위 강조 */
  --gold:         #B8902A;            /* 터미널 시스템 라인 */
  --gold-pale:    #F5EDD4;
  --border:        rgba(26,25,22,0.12);
  --border-strong: rgba(26,25,22,0.22);
  --r:    4px;                         /* 작은 라운드: 버튼, 폼, 작은 카드 */
  --r-lg: 12px;                        /* 큰 라운드: 터미널, 큰 카드 */
}
```

**다크 섹션 전용 토큰** (검은 배경 위 사용):
- 배경: `var(--ink)` `#1A1916` 또는 터미널 바 `#2C2C2A`
- 표면: `rgba(255,255,255,0.05)` (카드), `rgba(255,255,255,0.07)` (강조 카드)
- 보더: `rgba(255,255,255,0.08)` ~ `rgba(255,255,255,0.15)`
- 텍스트: `#fff` / `rgba(255,255,255,0.7)` / `rgba(255,255,255,0.5)` / `rgba(255,255,255,0.3)`
- 다크 위 강조: `var(--accent-mid)` `#A8D4BE`

**터미널 전용 컬러**:
- 빨강 점: `#E24B4A` / 노랑 점: `#EF9F27` / 초록 점: `#1D9E75`
- 하이라이트 결과 텍스트: `#5DCAA5`
- 출력 텍스트: `#B4B2A9` / 사용자 입력: `#E8E4DA` / 시스템 메타: `#5A5850`

### 2.3 Reset & Base

```css
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: 'Sora', sans-serif;
  font-size: 16px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
```

---

## 3. Typography

### 3.1 Type Scale

| 용도 | font-size | weight | letter-spacing | font-family |
|---|---|---|---|---|
| Hero H1 | `clamp(36px, 4.5vw, 52px)` | 700 (em은 800) | -0.02em | Sora |
| Section Title (H2) | `clamp(26px, 3vw, 36px)` | 700 | -0.02em | Sora |
| Beta Section H2 | 34px | 700 | -0.02em | Sora |
| Feedback Section H2 | `clamp(38px, 5vw, 60px)` | 800 | -0.03em | Sora |
| CTA Section H2 | `clamp(30px, 3.5vw, 44px)` | 700 | -0.02em | Sora |
| Card 제목 (h3) | 20px | 700 | -0.01em | Sora |
| Sub-card 제목 (h4) | 14–16px | 500–700 | -0.01em | Sora |
| 본문 large | 17px / line-height 1.7 | 400 | — | Sora |
| 본문 | 16px / line-height 1.6 | 400 | — | Sora |
| 본문 small | 13.5–14.5px / line-height 1.6 | 400 | — | Sora |
| Eyebrow / Badge | 11–12px | 500 | 0.08–0.14em + UPPERCASE | JetBrains Mono |
| 푸터 메타 | 12px | 400 | — | JetBrains Mono |

### 3.2 Emphasis Rule (시그니처)

헤드라인에서 **한 구절만** `<em>` 으로 감싸서 강조한다. 컨텍스트에 따라 두 가지 변형:

```css
/* 라이트 섹션 헤드라인 — 굵기로 강조 */
.hero h1 em,
.feedback-section h2 em /* 다크 섹션이지만 기본 italic 끔 */ {
  font-style: normal;
  font-weight: 800;
  color: var(--accent);          /* 다크 섹션은 var(--accent-mid) */
}

/* 베타/CTA 섹션 — 이탤릭 + 그린 */
.beta-section h2 em,
.cta-section h2 em {
  font-style: italic;
  color: var(--accent);          /* 다크 베타 섹션은 var(--accent-mid) */
}
```

### 3.3 Section Eyebrow Pattern

모든 주요 섹션은 다음 3단 구성을 따른다:

```html
<div class="section-eyebrow">Core Features</div>           <!-- 영문 mono 키커 -->
<h2 class="section-title">네 가지 핵심 기능</h2>            <!-- 한글 H2 -->
<p class="section-sub">복잡한 의료규제 문제를 다각도로...</p>  <!-- 1줄 설명 -->
```

```css
.section-eyebrow {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--accent);          /* 다크 섹션은 var(--accent-mid) */
  margin-bottom: 16px;
}
.section-title {
  font-family: 'Sora', sans-serif;
  font-size: clamp(26px, 3vw, 36px);
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin-bottom: 12px;
  line-height: 1.15;
}
.section-sub {
  font-size: 16px;
  color: var(--ink2);
  max-width: 520px;
  margin-bottom: 60px;
}
```

---

## 4. Layout

- **컨테이너 max-width**: `1100px`
- **수평 패딩**: `40px` (모바일 `20px`)
- **섹션 수직 패딩**: 라이트 섹션 `100px`, 다크/포인트 섹션 `120px`, 워크플로우 `80px`, 베타 배너 `64px`
- **그리드**:
  - Hero: `grid-template-columns: 1fr 420px; gap: 60px;`
  - Features: `grid-template-columns: 1fr 1fr; gap: 2px;` (gap이 디바이더로 보이도록 부모 배경 = `var(--border)`)
  - Account: `grid-template-columns: 1fr 1fr; gap: 80px;`
  - Beta inner: `grid-template-columns: 1fr auto; gap: 40px;`
  - Feedback top: `grid-template-columns: 1fr auto; gap: 60px;`
  - Feedback cards: `grid-template-columns: repeat(3, 1fr); gap: 16px;`

```css
.section-divider {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 40px;
  border-top: 1px solid var(--border);
}
```

---

## 5. Components

### 5.1 Nav (Fixed, Glass)

```css
nav {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  background: rgba(244,242,237,0.88);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 40px;
  height: 60px;
}
.nav-logo { font-size: 20px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.nav-links { display: flex; gap: 28px; align-items: center; }
.nav-links a { font-size: 13.5px; color: var(--ink2); transition: color 0.2s; }
.nav-links a:hover { color: var(--ink); }
.nav-cta {
  background: var(--accent); color: #fff;
  padding: 8px 18px; border-radius: var(--r);
  font-size: 13.5px; font-weight: 500;
  transition: background 0.2s, transform 0.15s;
}
.nav-cta:hover { background: var(--accent-light); transform: translateY(-1px); }
```

### 5.2 Buttons

```css
.btn-primary {
  display: inline-block;
  background: var(--accent); color: #fff;
  padding: 14px 28px; border-radius: var(--r);
  font-size: 15px; font-weight: 500;
  transition: background 0.2s, transform 0.15s, box-shadow 0.2s;
}
.btn-primary:hover {
  background: var(--accent-light);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(29,77,58,0.25);
}

.btn-secondary {
  display: inline-block;
  background: transparent; color: var(--ink);
  padding: 13px 26px; border-radius: var(--r);
  font-size: 15px;
  border: 1px solid var(--border-strong);
  transition: background 0.2s, border-color 0.2s;
}
.btn-secondary:hover { background: var(--bg2); border-color: var(--ink2); }
```

CTA 텍스트 패턴: `"베타 시작하기 →"`, `"Medra 베타 이용하기 →"` — 항상 끝에 `→`.

### 5.3 Hero Badge (점 깜빡임)

```css
.hero-badge {
  display: inline-flex; align-items: center; gap: 8px;
  background: var(--accent-pale);
  border: 1px solid var(--accent-mid);
  color: var(--accent);
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 500;
  letter-spacing: 0.08em;
  padding: 6px 14px;
  border-radius: 2px;
  text-transform: uppercase;
}
.hero-badge::before {
  content: '';
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: blink 2s ease-in-out infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
```

### 5.4 Terminal Mockup

```css
.hero-terminal {
  background: var(--ink);
  border-radius: var(--r-lg);
  overflow: hidden;
  box-shadow: 0 24px 60px rgba(0,0,0,0.18);
}
.terminal-bar {
  background: #2C2C2A;
  padding: 12px 16px;
  display: flex; align-items: center; gap: 8px;
}
.t-dot { width: 10px; height: 10px; border-radius: 50%; }
.t-red { background: #E24B4A; }
.t-yel { background: #EF9F27; }
.t-grn { background: #1D9E75; }
.terminal-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #5A5850;
  margin-left: auto; margin-right: auto;
  letter-spacing: 0.05em;
}
.terminal-body { padding: 24px; }
.t-line {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.8;
  margin-bottom: 4px;
}
.t-prompt    { color: var(--accent-mid); }   /* user@medra */
.t-user      { color: #E8E4DA; }              /* 사용자 입력 */
.t-sys       { color: var(--gold); opacity: 0.8; font-size: 11px; } /* ▸ 시스템 라인 */
.t-out       { color: #B4B2A9; }              /* 일반 출력 */
.t-highlight { color: #5DCAA5; }              /* 결과 강조 */
.t-cursor {
  display: inline-block;
  width: 7px; height: 13px;
  background: var(--accent-mid);
  vertical-align: middle;
  animation: blink 1.2s step-end infinite;
}
```

**터미널 콘텐츠 패턴**: `프롬프트 → 사용자 질문 → ▸ 시스템 라인 3개(대기) → 결과 본문 → 하이라이트 ① ② ③ → 메타 푸터 + 커서`

### 5.5 Feature Card (그리드의 1px 디바이더 트릭)

```css
.features-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
  background: var(--border);   /* gap 사이로 보이는 색이 디바이더 */
  border-radius: var(--r-lg);
  overflow: hidden;
}
.feature-card {
  background: var(--bg);
  padding: 40px 36px;
  transition: background 0.2s;
}
.feature-card:hover { background: var(--bg2); }
.feature-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--ink3);
  letter-spacing: 0.08em;
  margin-bottom: 20px;
}
.feature-icon {
  width: 40px; height: 40px;
  background: var(--accent-pale);
  border: 1px solid var(--accent-mid);
  border-radius: var(--r);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 20px;
}
.feature-icon svg {
  width: 20px; height: 20px;
  stroke: var(--accent); fill: none; stroke-width: 1.5;
}
.feature-card h3 {
  font-size: 20px; font-weight: 700;
  letter-spacing: -0.01em;
  margin-bottom: 12px; line-height: 1.2;
}
.feature-card p {
  font-size: 14.5px; color: var(--ink2); line-height: 1.65;
}
```

### 5.6 Workflow Steps (가로 라인 + 원형 카운터)

```css
.workflow-steps {
  display: flex; gap: 0;
  margin-top: 48px;
  position: relative;
}
.workflow-steps::before {                  /* 가운데 관통 라인 */
  content: '';
  position: absolute;
  top: 28px; left: 28px; right: 28px;
  height: 1px;
  background: var(--border-strong);
}
.workflow-step {
  flex: 1;
  text-align: center;
  padding: 0 20px;
  position: relative;
}
.step-circle {
  width: 56px; height: 56px;
  background: var(--bg);
  border: 2px solid var(--accent);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 20px;
  position: relative; z-index: 1;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px; font-weight: 500;
  color: var(--accent);
  transition: background 0.2s, color 0.2s;
}
.workflow-step:hover .step-circle {
  background: var(--accent);
  color: #fff;
}
.step-arrow {
  position: absolute;
  top: 27px; right: -10px;
  color: var(--ink3); font-size: 16px; z-index: 2;
}
.step-tag {
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  background: var(--accent-pale);
  border: 1px solid var(--accent-mid);
  padding: 3px 8px;
  border-radius: 2px;
  margin-bottom: 10px;
}
.workflow-step h4 { font-size: 14px; font-weight: 500; margin-bottom: 6px; }
.workflow-step p  { font-size: 13px; color: var(--ink2); line-height: 1.55; }
```

### 5.7 Account Steps (좌측 번호 + 보더 리스트)

```css
.account-list { margin-top: 40px; }
.account-item {
  display: flex; gap: 16px;
  padding: 20px 0;
  border-bottom: 1px solid var(--border);
}
.account-item:last-child { border-bottom: none; }
.a-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--accent);
  font-weight: 500;
  width: 28px;
  flex-shrink: 0;
  padding-top: 1px;
}
.a-content h4 { font-size: 15px; font-weight: 500; margin-bottom: 4px; }
.a-content p  { font-size: 13.5px; color: var(--ink2); line-height: 1.6; }
```

### 5.8 Dark Form Card (계정 만들기 미리보기)

```css
.account-visual {
  background: var(--ink);
  border-radius: var(--r-lg);
  padding: 36px;
  box-shadow: 0 20px 50px rgba(0,0,0,0.15);
}
.form-title {
  font-size: 20px; font-weight: 700; color: #fff;
  margin-bottom: 28px; letter-spacing: -0.02em;
}
.form-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--accent-mid);
  margin-bottom: 6px;
}
.form-field {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: var(--r);
  padding: 11px 14px;
  margin-bottom: 16px;
  font-size: 13px;
  color: rgba(255,255,255,0.4);
  font-family: 'Sora', sans-serif;
  width: 100%;
}
.form-field.filled,
.form-field:focus {
  color: rgba(255,255,255,0.9);
  border-color: rgba(93,202,165,0.3);
  outline: none;
}
.form-btn {
  width: 100%;
  background: var(--accent); color: #fff;
  border: none; border-radius: var(--r);
  padding: 13px;
  font-size: 14px; font-weight: 500;
  cursor: pointer; margin-top: 4px;
  transition: background 0.2s;
}
.form-btn:hover { background: var(--accent-light); }
.form-note {
  font-size: 11px;
  color: rgba(255,255,255,0.3);
  text-align: center;
  margin-top: 12px;
  font-family: 'JetBrains Mono', monospace;
}
```

### 5.9 Feedback Card (다크 표면)

```css
.feedback-card {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--r-lg);
  padding: 28px 28px 24px;
}
.feedback-card-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--accent-mid);
  letter-spacing: 0.08em;
  margin-bottom: 16px;
}
.feedback-card h4 {
  font-size: 16px; font-weight: 700; color: #fff;
  margin-bottom: 10px; letter-spacing: -0.01em;
}
.feedback-card p {
  font-size: 13.5px; color: rgba(255,255,255,0.5); line-height: 1.65;
}
```

### 5.10 Footer

```css
footer {
  border-top: 1px solid var(--border);
  padding: 40px;
  max-width: 1100px;
  margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
}
.footer-logo { font-size: 18px; color: var(--ink); }
footer p { font-size: 12px; color: var(--ink3); font-family: 'JetBrains Mono', monospace; }
```

---

## 6. Section Patterns

### 6.1 Beta Banner (그린 배경 + 워터마크)

```css
.beta-section {
  background: var(--accent);
  padding: 64px 40px;
  position: relative;
  overflow: hidden;
}
.beta-section::before {
  content: 'BETA';
  position: absolute;
  right: -20px; top: 50%;
  transform: translateY(-50%) rotate(90deg);
  font-family: 'Sora', sans-serif;
  font-size: 120px;
  color: rgba(255,255,255,0.04);
  letter-spacing: -0.05em;
  pointer-events: none;
}
.beta-tag {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.5);
  margin-bottom: 16px;
}
.beta-tag::before {
  content: '';
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--accent-mid);
  animation: blink 2s ease-in-out infinite;
}
.beta-section h2 { color: #fff; font-size: 34px; }
.beta-section h2 em { font-style: italic; color: var(--accent-mid); }
.beta-section p { color: rgba(255,255,255,0.7); font-size: 15.5px; line-height: 1.7; }

.beta-date-card {
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: var(--r);
  padding: 12px 16px;
}
.beta-date-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--accent-mid);
  margin-bottom: 4px;
}
.beta-date-val { font-size: 14px; font-weight: 500; color: #fff; }
```

### 6.2 Feedback Section (블랙 배경 + `@feedback` 워터마크)

```css
.feedback-section {
  background: var(--ink);
  padding: 120px 40px;
  position: relative;
  overflow: hidden;
}
.feedback-section::before {
  content: '@feedback';
  position: absolute;
  right: -40px; bottom: -30px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 160px;
  font-weight: 700;
  color: rgba(255,255,255,0.03);
  letter-spacing: -0.04em;
  pointer-events: none;
  white-space: nowrap;
}
.feedback-section .section-eyebrow { color: var(--accent-mid); }
.feedback-section h2 {
  font-size: clamp(38px, 5vw, 60px);
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #fff;
  line-height: 1.08;
}
.feedback-section h2 em { font-style: normal; color: var(--accent-mid); }

.feedback-cmd-big {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: var(--r-lg);
  padding: 36px 48px;
  text-align: center;
  min-width: 300px;
}
.feedback-cmd-big-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 36px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.01em;
  margin-bottom: 12px;
}
```

### 6.3 CTA Section (가운데 정렬)

```css
.cta-section {
  padding: 120px 40px;
  text-align: center;
  max-width: 700px;
  margin: 0 auto;
}
.cta-section h2 {
  font-size: clamp(30px, 3.5vw, 44px);
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 20px;
  line-height: 1.15;
}
.cta-section h2 em { font-style: italic; color: var(--accent); }
.cta-section p {
  font-size: 16px;
  color: var(--ink2);
  margin-bottom: 40px;
  line-height: 1.7;
}
```

---

## 7. Animations

### 7.1 Fade-up Stagger (entry animation)

```css
.fade-up {
  opacity: 0;
  transform: translateY(24px);
  animation: fadeUp 0.6s ease forwards;
}
@keyframes fadeUp {
  to { opacity: 1; transform: translateY(0); }
}
.delay-1 { animation-delay: 0.1s; }
.delay-2 { animation-delay: 0.2s; }
.delay-3 { animation-delay: 0.3s; }
.delay-4 { animation-delay: 0.4s; }
```

### 7.2 Blink (status dot, terminal cursor)

위 5.3, 5.4 참고. `2s ease-in-out infinite` (점) / `1.2s step-end infinite` (커서).

### 7.3 Hover Transform

- 버튼 primary: `translateY(-2px)` + 그린 그림자 `0 8px 24px rgba(29,77,58,0.25)`
- 버튼 nav-cta: `translateY(-1px)`
- Workflow circle: 채움 색 반전 (transparent → accent)
- Feature card: `--bg` → `--bg2` 배경만 살짝

---

## 8. Signature Details (꼭 지킬 것)

1. **헤드라인 줄바꿈 + `<em>` 한 구절 강조**
   ```html
   <h1>의료규제,<br><em>놓치는 것 없이</em><br>파악하세요</h1>
   ```
2. **영문 키커 → 한글 H2 → 1줄 설명** 3단 구성을 모든 섹션에 적용
3. **숫자 인덱스(01/02/03/04)** 는 항상 JetBrains Mono, 11–13px, `--ink3` 또는 `--accent-mid`
4. **CTA 텍스트는 항상 `→`로 종료**
5. **다크 섹션 우측 하단에 거대한 워터마크 텍스트** (`opacity 0.03~0.04`, 120–160px)
6. **상태 점**(•) 옆에 `blink 2s` — Closed Beta 라벨에 사용
7. **Workflow는 가로 1px 라인 + 원형 56px 카운터**
8. **Features 그리드는 `gap: 2px` + 부모 `background: var(--border)`** 로 디바이더 효과
9. **다크 폼 카드**: 배경 `--ink`, 인풋은 `rgba(255,255,255,0.06)` + 1px 보더, 라벨은 mono uppercase
10. **컨테이너 max-width 1100px** 절대 고정

---

## 9. Responsive

```css
@media (max-width: 768px) {
  nav { padding: 0 20px; }
  .hero { grid-template-columns: 1fr; padding: 100px 20px 60px; gap: 40px; }
  .features-grid { grid-template-columns: 1fr; }
  .account-section { grid-template-columns: 1fr; padding: 60px 20px; gap: 40px; }
  .beta-inner, .feedback-inner { grid-template-columns: 1fr; }
  .workflow-steps { flex-direction: column; gap: 20px; }
  .workflow-steps::before { display: none; }
  .step-arrow { display: none; }
  footer { flex-direction: column; gap: 16px; text-align: center; }
}
```

---

## 10. Do / Don't

**DO**
- 컬러는 항상 CSS 변수로 참조. 하드코딩 금지.
- 새 섹션 추가 시 eyebrow → title → sub 3단 패턴 유지.
- 헤드라인 강조는 한 줄에 한 구절만, `<em>` 태그로.
- 카운터/태그/날짜 라벨은 무조건 JetBrains Mono.
- 라이트 섹션 사이는 `border-top: 1px solid var(--border)` 디바이더 사용.

**DON'T**
- Sora / JetBrains Mono 외 다른 폰트 사용 금지.
- 그라데이션, 화려한 색상(보라/주황/파랑) 추가 금지. 액센트는 그린 한 줄기로 통일.
- 보더 라디우스를 토큰 외 값(예: 8px, 16px, 20px)으로 임의 사용 금지. `--r` 또는 `--r-lg`만.
- 헤드라인에 두 구절 이상을 동시에 강조하지 않는다.
- 다크 섹션에서 순수 검정(#000) 사용 금지. 항상 `var(--ink)` (#1A1916).

---

## 11. Quick Start Snippet

새 페이지 시작용 최소 보일러플레이트:

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Medra — [페이지 제목]</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/styles/medra.css">
</head>
<body>
  <nav> ... </nav>

  <section class="hero">
    <div>
      <div class="hero-badge fade-up">Closed Beta · 2026</div>
      <h1 class="fade-up delay-1">
        [Lead-in],<br>
        <em>[강조 구절]</em><br>
        [마무리]
      </h1>
      <p class="hero-sub fade-up delay-2">[1–2줄 설명]</p>
      <div class="hero-actions fade-up delay-3">
        <a href="#" class="btn-primary">[메인 CTA] →</a>
        <a href="#" class="btn-secondary">[보조 CTA]</a>
      </div>
    </div>
    <!-- 우측 비주얼 (terminal / form / illustration) -->
  </section>

  <!-- 섹션 추가 시: eyebrow → h2 → sub 패턴 유지 -->
</body>
</html>
```
