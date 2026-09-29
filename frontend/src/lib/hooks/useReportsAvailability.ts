"use client";

/**
 * useReportsAvailability — 보고서 기능 가용성 구독.
 *
 * 2026-09-07: writer(DGX vLLM)를 운영자가 다른 작업에 쓰는 동안 "보고서만 안 된다"를
 * 사용자에게 알리기 위해. 두 신호를 합친다.
 *  - paused   : 운영자 토글(기능 단위 일시 중단). POST /reports 는 503. 버튼 비활성 + 배너.
 *  - writerUp : writer 프로브(30s 캐시). false 면 토글 없이도 "지연·불가" 경고.
 *               null = 로컬 writer 미설정(폴백 모델이라 항상 가능).
 *
 * 2026-09-10: 폴링·상태를 `lib/store/reportsAvailability` 로 옮겼다. 훅 밖
 * (`triggerReport`)도 같은 store 를 보게 하기 위해서다 — 종전엔 이 훅이 마운트돼야만
 * 채워지는 모듈 변수를 읽어, 게이팅이 "ChatInput 이 떠 있는가"에 딸려 있었다.
 */

import { useSyncExternalStore } from "react";
import {
  getServerSnapshot,
  getSnapshot,
  subscribe,
  type ReportsAvailability,
} from "@/lib/store/reportsAvailability";

export type { ReportsAvailability };

export function useReportsAvailability(): ReportsAvailability {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
