/**
 * Auth route group layout — login·signup·auth/* 공통 wrapper.
 *
 * 별도 theme 강제 X — 사용자가 켠 theme(brand·medra)을 그대로 respect.
 * 공통 layout 자리만 잡아둠 (배경/로고/푸터 같은 공통 요소를 추후 여기로 추출 가능).
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
