"use client";

/**
 * ThemeLogo — "RegNavigator" 텍스트 워드마크.
 *
 * 이전엔 /logo*.png 이미지 swap이었으나 브랜드 변경(RegNavigator, 2026-10-01)에 따라 텍스트
 * 워드마크로 단순화. 색은 theme 토큰(text-md-on-surface)으로 자동 따라가고
 * 폰트는 Sora — 모든 theme에서 동일 톤.
 *
 * className은 사용처 그대로 (h-7/h-9 등) — wrapper height만 잡고 텍스트는
 * 자기 line-height. alt prop은 호환을 위해 남겨두되 aria-label로 활용.
 */

type Props = {
  className?: string;
  alt?: string;
};

export function ThemeLogo({ className = "h-9 w-auto", alt = "RegNavigator" }: Props) {
  return (
    <span
      role="img"
      aria-label={alt}
      className={`inline-flex items-center whitespace-nowrap font-bold text-md-on-surface ${className}`}
      style={{
        fontFamily: "'Sora', 'Pretendard Variable', sans-serif",
        letterSpacing: "-0.02em",
        fontSize: "0.95em",
      }}
    >
      RegNavigator
    </span>
  );
}
