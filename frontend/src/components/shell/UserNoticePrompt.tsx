"use client";

/**
 * 사용자별 앱 내 알림 팝업(2026-09-15) — 관리자가 **지정한 사용자에게만** 보낸 알림을
 * 로그인 후 최초 접속 시 1회 띄운다. 읽음 상태는 서버(`POST /me/notices/{id}/seen`)가
 * 갖는다 — 기기·브라우저 무관. 전체 공지(PatchNotesPrompt)와 별개 채널.
 *
 * 인증 게이팅은 PatchNotesPrompt 와 동일(usage 도착 후 조회).
 */
import { useEffect, useRef, useState } from "react";

import { useUsage } from "@/lib/store/useUsage";
import { PatchNotesList } from "@/components/shell/PatchNotesPrompt";
import {
  Dialog,
  DialogAction,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getMyPendingNotice, markNoticeSeen, type UserNotice } from "@/lib/client/prefs";

const SESSION_KEY = "medi_user_notice_shown";

export function UserNoticePrompt() {
  const { usage } = useUsage();
  const fetched = useRef(false);
  const [notice, setNotice] = useState<UserNotice | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!usage || fetched.current) return;
    fetched.current = true;
    let alive = true;
    void (async () => {
      try {
        const n = await getMyPendingNotice();
        if (!alive || !n) return;
        try {
          if (window.sessionStorage.getItem(SESSION_KEY) === n.id) return;
          window.sessionStorage.setItem(SESSION_KEY, n.id);
        } catch {
          /* 저장소 불가 — 서버 읽음 상태로 충분 */
        }
        setNotice(n);
        setOpen(true);
      } catch {
        // 조회 실패는 조용히 — 접속을 방해하지 않는다.
      }
    })();
    return () => {
      alive = false;
    };
  }, [usage]);

  const dismiss = () => {
    if (notice) {
      void markNoticeSeen(notice.id).catch(() => {
        /* 실패하면 다음 접속에 다시 뜬다 */
      });
    }
    setOpen(false);
  };

  if (!notice) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && dismiss()}>
      <DialogContent className="w-[min(92vw,640px)] max-w-none">
        <DialogHeader>
          <DialogTitle>{notice.title}</DialogTitle>
          <DialogDescription>{notice.date} — 회원님께 드리는 알림입니다.</DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[55vh] overflow-y-auto pr-1 text-md-on-surface">
          <PatchNotesList items={notice.items} />
        </DialogBody>
        <DialogFooter>
          <DialogAction onClick={dismiss}>확인</DialogAction>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
