"use client";

/**
 * ChatScroll — 03 §1, P6.1.2.
 *
 * Turn 목록 + 자동 스크롤. 두 가지 동작:
 *  1) **follow** (`followKey`): 바닥 근처에 있을 때만 새 chunk 도착 시 scrollTo(bottom).
 *     사용자가 위로 스크롤하면 그 의지를 존중해 따라가지 않는다(skill step-card §4).
 *  2) **jump-once** (`jumpKey`): 새 턴(=답변 생성 시작)이 시작되면 *현재 위치 무관*
 *     하단으로 단 1회 점프. 위로 올려둔 상태에서 새 답변이 생성돼도 그 답변 위치로
 *     데려간다. 점프 후 계속 붙잡지 않음(이후 사용자가 위로 올리면 follow가 멈춤).
 */

import { useEffect, useRef, type ReactNode } from "react";

const NEAR_BOTTOM_PX = 96;

type Props = {
  /** 새 chunk 도착 신호용 — 변경되면 (바닥 근처일 때만) 자동 스크롤 시도 */
  followKey?: unknown;
  /** 답변 생성 시작 신호용(예: 활성 turn id) — 변경되면 위치 무관 1회 하단 점프 */
  jumpKey?: unknown;
  children: ReactNode;
};

export function ChatScroll({ followKey, jumpKey, children }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const followingRef = useRef(true);

  // 사용자 스크롤 → 바닥 근처면 follow=true, 떨어지면 false
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const fromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      followingRef.current = fromBottom <= NEAR_BOTTOM_PX;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  // followKey 변경 시 자동 스크롤 (followingRef.current === true 일 때만)
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (followingRef.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [followKey]);

  // jumpKey 변경(새 턴 시작) 시 위치 무관 1회 하단 점프. 초기 마운트(스레드 로드)엔
  // 점프하지 않음 — *새* 생성에만 반응. 점프로 바닥에 닿으면 follow도 재개(붙잡진 X).
  const firstJumpRef = useRef(true);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (firstJumpRef.current) {
      firstJumpRef.current = false;
      return;
    }
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    followingRef.current = true;
  }, [jumpKey]);

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto">
      {children}
    </div>
  );
}
