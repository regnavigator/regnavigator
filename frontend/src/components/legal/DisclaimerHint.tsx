"use client";

/**
 * DisclaimerHint — 채팅 입력 아래 상시 노출되는 면책 문구.
 *
 * 정본은 백엔드(`GET /legal`.disclaimer_short, src/legal.py) — 프런트가 임의
 * 문구를 쓰면 법적 고지가 두 벌이 된다. 조회 실패 시에도 빈 줄 대신 보수적
 * 기본 문구를 노출(상시 노출이 법적으로 안전 — frontend_legal_handoff.md §3).
 */

import { useEffect, useState } from "react";
import { getLegalNoticeCached } from "@/lib/client/legal";

const FALLBACK =
  "AI가 생성한 참고 정보이며 법률자문이 아닙니다. 답변의 출처와 시행일을 한 번 더 확인하세요.";

export function DisclaimerHint() {
  const [text, setText] = useState(FALLBACK);

  useEffect(() => {
    let cancelled = false;
    getLegalNoticeCached()
      .then((n) => {
        // markdown 강조(**) 제거 — 이 줄은 플레인 텍스트 렌더
        if (!cancelled && n.disclaimer_short) {
          setText(n.disclaimer_short.replace(/\*\*/g, ""));
        }
      })
      .catch(() => {
        // fallback 유지
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 2줄 표기(2026-08-27 요청) — 문장 경계에서 줄을 나눈다. 서버 문구가
  // 한 문장이면 그대로 1줄.
  const sentences = text.split(/(?<=다\.)\s+/).filter(Boolean);
  const line1 = sentences[0] ?? text;
  const line2 = sentences.slice(1).join(" ");
  return (
    <p className="mt-4 pb-1 text-center text-[11.5px] leading-[1.8] text-md-on-surface-variant/80">
      {line1}
      {line2 ? (
        <>
          <br />
          {line2}
        </>
      ) : null}
    </p>
  );
}
