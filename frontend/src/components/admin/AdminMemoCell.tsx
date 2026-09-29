"use client";

/**
 * 관리자 식별 메모(2026-09-15) — 프로필을 입력하지 않은 기존 가입자를 관리자가
 * 알아볼 수 있게 관리자 화면에서만 기입·표시. 클릭 → 입력 → Enter/블러 저장.
 */
import { useEffect, useState } from "react";

export function AdminMemoCell({
  value,
  onSave,
}: {
  value: string | null | undefined;
  onSave: (memo: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!editing) setDraft(value ?? "");
  }, [value, editing]);

  const commit = async () => {
    if (busy) return;
    const next = draft.trim();
    if (next === (value ?? "").trim()) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      await onSave(next);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        maxLength={500}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === "Enter") void commit();
          if (e.key === "Escape") {
            setDraft(value ?? "");
            setEditing(false);
          }
        }}
        placeholder="관리자만 보는 식별 메모"
        className="w-full rounded border border-md-primary bg-md-surface px-1.5 py-0.5 text-[11.5px] text-md-on-surface"
      />
    );
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title="관리자 식별 메모 — 사용자에게는 보이지 않음. 클릭해 기입"
      className={`block w-full truncate rounded px-1.5 py-0.5 text-left text-[11.5px] hover:bg-md-surface-container-high ${
        value ? "text-md-on-surface" : "italic text-md-on-surface-variant opacity-60"
      }`}
    >
      {value || "메모 기입…"}
    </button>
  );
}
