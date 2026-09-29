"use client";

/**
 * Admin 공용 조각 — 페이지마다 제각각이던 에러 배너·pill 토글·합계 카드·
 * 숫자/시각 포매터를 한 곳으로 (2026-08-05 UI 정리).
 */

/** 인라인 에러 배너 — admin 전 페이지 공통 스타일. message 없으면 렌더 안 함. */
export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className="rounded-card border border-md-error bg-md-error-container px-3 py-2 text-body-sm text-md-on-error-container"
    >
      {message}
    </div>
  );
}

/** pill 토글 버튼 — 탭·기간·필터 공용. count 는 옆에 흐리게. */
export function PillTab({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean;
  label: string;
  count?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-pill border px-3 py-1.5 text-[13px] font-medium transition-colors ${
        active
          ? "border-md-primary bg-md-primary text-md-on-primary"
          : "border-md-outline-variant text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface"
      }`}
    >
      {label}
      {count != null ? (
        <span className="ml-1 tabular-nums opacity-70">{count}</span>
      ) : null}
    </button>
  );
}

/** 합계 카드 — stats·questions(사실 검증) 공용. tone="warn" 은 경고색 숫자. */
export function StatCard({
  icon,
  label,
  value,
  sub,
  tone,
}: {
  icon?: string;
  label: string;
  value: string;
  sub?: string;
  tone?: "warn";
}) {
  return (
    <div
      className={`flex flex-col gap-1.5 rounded-card border bg-md-surface p-4 ${
        tone === "warn" ? "border-md-error/40" : "border-md-outline-variant"
      }`}
    >
      <div className="flex items-center gap-1.5 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-md-on-surface-variant">
        {icon ? (
          <span className="material-symbols-outlined text-[16px]" aria-hidden>
            {icon}
          </span>
        ) : null}
        {label}
      </div>
      <span
        className={`text-[24px] font-semibold tabular-nums leading-tight tracking-tight ${
          tone === "warn" ? "text-md-error" : "text-md-on-surface"
        }`}
      >
        {value}
      </span>
      {sub ? (
        <span className="text-[11.5px] tabular-nums text-md-on-surface-variant">
          {sub}
        </span>
      ) : null}
    </div>
  );
}

/** 로딩 스피너 (Material Symbols). */
export function Spinner({ size = 18 }: { size?: number }) {
  return (
    <span
      className="material-symbols-outlined animate-spin text-md-on-surface-variant"
      style={{ fontSize: size }}
      aria-hidden
    >
      progress_activity
    </span>
  );
}

/** 1234 → "1.2k" · 3400000 → "3.40M". */
export function fmt(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

/** ISO → "08. 05. 14:30" (ko-KR, 월·일·시·분). 파싱 실패 시 원문. */
export function formatTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}


/**
 * 관리자 화면 공용 사용자 표기(2026-09-18).
 *
 * 우선순위: 프로필 표시명 → 관리자 식별 메모 → 이메일 → id 조각. 메모로 표기할 때는 작은
 * "메모" 꼬리표를 붙여 본인이 입력한 이름과 구분한다. 이름·메모가 있으면 이메일을 옆에 흐리게.
 * 메모는 사용자 관리 화면에서 붙인다 — 프로필을 입력하지 않은 가입자를 알아보기 위한 것.
 */
export function AdminUserLabel({
  displayName,
  memo,
  email,
  userId,
  className = "",
}: {
  displayName?: string | null;
  memo?: string | null;
  email?: string | null;
  userId?: string | null;
  className?: string;
}) {
  const name = (displayName ?? "").trim();
  const note = (memo ?? "").trim();
  const primary = name || note || email || (userId ? `${userId.slice(0, 12)}…` : "익명");
  const fromMemo = !name && !!note;
  const showEmail = !!email && primary !== email;
  const tip = [name && `이름: ${name}`, note && `메모: ${note}`, email, userId].filter(Boolean).join(" · ");
  return (
    <span className={"inline-flex min-w-0 items-center gap-1 " + className} title={tip || undefined}>
      <span className="truncate font-medium text-md-on-surface">{primary}</span>
      {fromMemo ? (
        <span className="shrink-0 rounded-pill border border-md-outline-variant px-1 text-[9.5px] leading-[14px] text-md-on-surface-variant">
          메모
        </span>
      ) : name && note ? (
        <span className="min-w-0 truncate text-md-on-surface-variant">({note})</span>
      ) : null}
      {showEmail ? <span className="min-w-0 truncate text-md-on-surface-variant opacity-80">{email}</span> : null}
    </span>
  );
}
