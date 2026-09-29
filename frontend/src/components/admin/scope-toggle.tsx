"use client";

/**
 * 실사용/전체 데이터 토글 — 관리자 통계·조회 화면 공용.
 *
 * 베타 오픈(2026-08-03) 이전 데이터는 개발·e2e 테스트가 만든 것이라, 섞어 집계하면
 * 테스트 트래픽이 이용자 지표로 읽힌다(초대 전날 LLM 72회는 전부 내부 테스트였다).
 * 기본은 "실사용만"이고, 과거 비교가 필요할 때만 "전체"로 넘긴다.
 * 2026-09-21: "실사용"에서 빠지는 계정 = 관리자·테스트 라벨(사용자 관리 › 구분, 자동 판정 포함).
 */

import { useEffect, useState } from "react";
import { getDataScope, type DataScope } from "@/lib/client/admin";

export function ScopeToggle({
  scope,
  onChange,
}: {
  scope: DataScope;
  onChange: (s: DataScope) => void;
}) {
  const [launchAt, setLaunchAt] = useState<string | null>(null);

  useEffect(() => {
    void getDataScope()
      .then((d) => setLaunchAt(d.launch_at))
      .catch(() => setLaunchAt(null));
  }, []);

  const label = launchAt
    ? new Date(launchAt).toLocaleDateString("ko-KR", {
        year: "numeric",
        month: "long",
        day: "numeric",
      })
    : null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex overflow-hidden rounded-pill border border-md-outline-variant">
        {(["real", "all"] as DataScope[]).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onChange(s)}
            className={`px-3 py-1 text-[12px] transition-colors ${
              scope === s
                ? "bg-md-primary text-md-on-primary"
                : "text-md-on-surface-variant hover:bg-md-surface-container-low"
            }`}
          >
            {s === "real" ? "실사용만" : "전체(관리자·테스트 포함)"}
          </button>
        ))}
      </div>
      <span className="text-[11.5px] text-md-on-surface-variant">
        {scope === "real" ? (
          <>
            {label ? `${label} 베타 오픈 이후 · ` : "베타 오픈 이후 · "}
            관리자·테스트 계정 제외 —{" "}
            <a href="/admin/users" className="underline underline-offset-2 hover:text-md-on-surface">
              사용자 관리 › 구분
            </a>
            에서 지정
          </>
        ) : (
          "개발·테스트 기간 + 관리자·테스트 계정까지 함께 집계됩니다"
        )}
      </span>
    </div>
  );
}
