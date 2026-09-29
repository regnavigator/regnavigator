/**
 * withViewTransition — ✨ View Transitions API 래퍼 (2026-07-16 킥).
 *
 * 지원 브라우저(Chrome/Edge 111+, Safari 18+)에선 DOM 변경을
 * document.startViewTransition으로 감싸 크로스페이드/shared-element morph.
 * 미지원·reduced-motion·SSR에선 그냥 실행 (폴백 무해).
 *
 * React state 변경은 startViewTransition 콜백 안에서 *동기 flush* 되어야
 * 스냅샷 전/후가 잡히므로 flushSync 사용. 이벤트 핸들러에서만 호출할 것
 * (렌더 중 flushSync는 React 경고).
 */

import { flushSync } from "react-dom";

/** startViewTransition 반환값 — 건너뛰어진 전환은 ready/finished 가 AbortError 로 reject. */
type ViewTransitionLike = {
  ready?: Promise<void>;
  finished?: Promise<void>;
  updateCallbackDone?: Promise<void>;
};

type DocWithVT = Document & {
  startViewTransition?: (cb: () => void) => ViewTransitionLike | undefined;
};

/**
 * 전환이 건너뛰어질 때(연타로 새 전환이 시작·탭 숨김·다른 전환과 충돌) 브라우저가
 * `ready`/`finished` 를 `AbortError: Transition was skipped` 로 reject 한다. 아무도 await
 * 하지 않으면 "Uncaught (in promise)" 콘솔 에러(2026-09-09 운영자 신고). 무해하므로 삼킨다.
 */
function swallowSkipped(vt: ViewTransitionLike | undefined): void {
  if (!vt) return;
  vt.ready?.catch(() => {});
  vt.finished?.catch(() => {});
  vt.updateCallbackDone?.catch(() => {});
}

/**
 * 비동기 커밋 대기 버전 — apply가 *간접적으로*(store 경유) React 상태를 바꿔
 * flushSync로 못 감쌀 때 사용. apply 실행 후 두 프레임을 기다려 React 커밋이
 * 스냅샷 안에 잡히게 한다 (예: 빈 화면→스레드 전환 시 입력창 슬라이딩 morph).
 */
export function withViewTransitionAsync(apply: () => void): void {
  if (typeof document === "undefined") {
    apply();
    return;
  }
  const doc = document as Document & {
    startViewTransition?: (
      cb: () => Promise<void> | void,
    ) => ViewTransitionLike | undefined;
  };
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (!doc.startViewTransition || reduced) {
    apply();
    return;
  }
  swallowSkipped(
    doc.startViewTransition(async () => {
      apply();
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      );
    }),
  );
}

export function withViewTransition(apply: () => void): void {
  if (typeof document === "undefined") {
    apply();
    return;
  }
  const doc = document as DocWithVT;
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (!doc.startViewTransition || reduced) {
    apply();
    return;
  }
  swallowSkipped(
    doc.startViewTransition(() => {
      flushSync(apply);
    }),
  );
}
