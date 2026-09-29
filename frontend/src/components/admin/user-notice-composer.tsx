"use client";

/**
 * 사용자별 앱 내 알림 작성(2026-09-15) — 선택한 사용자에게만 최초 접속 1회 팝업.
 * 전체 공지(패치노트)와 달리 수신자를 지정한다. 본문은 줄 단위로 항목이 된다.
 */
import { useState } from "react";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { sendUserNotices } from "@/lib/client/admin";

export function UserNoticeComposer({
  userIds,
  emails,
  onDone,
  onClose,
}: {
  userIds: string[];
  emails: string[];
  onDone: () => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<number | null>(null);
  const items = body
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const ready = !!title.trim() && items.length > 0 && userIds.length > 0;

  const submit = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await sendUserNotices({ user_ids: userIds, title: title.trim(), items });
      setSent(r.count);
    } catch (e) {
      setError(e instanceof Error ? e.message : "발송 실패");
    } finally {
      setBusy(false);
    }
  };

  const recipients =
    emails.slice(0, 5).join(", ") + (emails.length > 5 ? ` 외 ${emails.length - 5}명` : "");

  return (
    <Dialog open onOpenChange={(o) => (!o ? onClose() : null)}>
      <DialogContent className="max-h-[88vh] overflow-y-auto border border-md-outline-variant bg-md-surface p-6 text-md-on-surface sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-[18px] font-semibold">앱 내 알림 보내기</DialogTitle>
          <p className="text-body-sm text-md-on-surface-variant">
            {recipients} · 다음 접속 때 1회 팝업으로 표시됩니다(수신자 외에는 보이지 않음).
          </p>
        </DialogHeader>
        {sent !== null ? (
          <div className="mt-3 flex flex-col gap-3">
            <p className="text-body-sm">{sent}명에게 알림을 넣었습니다.</p>
            <button
              type="button"
              onClick={onDone}
              className="self-end rounded-pill bg-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-on-primary"
            >
              닫기
            </button>
          </div>
        ) : (
          <div className="mt-3 flex flex-col gap-3">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={120}
              placeholder="제목 (예: 보내주신 피드백이 반영되었습니다)"
              className="rounded border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm"
            />
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={6}
              placeholder="본문 — 줄마다 한 항목으로 표시됩니다 (최대 10줄, 줄당 300자)"
              className="rounded border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm"
            />
            {error ? <p className="text-[12px] text-md-error">{error}</p> : null}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-pill px-4 py-1.5 text-[12.5px] text-md-on-surface-variant hover:bg-md-surface-container-high"
              >
                취소
              </button>
              <button
                type="button"
                disabled={!ready || busy}
                onClick={() => void submit()}
                className="rounded-pill bg-md-primary px-4 py-1.5 text-[12.5px] font-semibold text-md-on-primary disabled:opacity-50"
              >
                {busy ? "보내는 중…" : `${userIds.length}명에게 보내기`}
              </button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
