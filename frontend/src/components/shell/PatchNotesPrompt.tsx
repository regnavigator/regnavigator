"use client";

/**
 * PatchNotesPrompt — 패치노트 팝업 (2026-08-13, "매일 개선한다" 가시화).
 *
 * 로그인 후 최초 접속 시 `GET /announcements/latest` 를 조회해, 노트 id 가
 * localStorage 의 마지막 확인 id 와 다르면 모달을 1회 띄운다. 닫으면 id 저장 —
 * 같은 노트는 다시 안 나온다(서버는 사용자별 읽음 상태를 저장하지 않는다).
 * 발행: admin /admin/announcements.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
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
import { useUsage } from "@/lib/store/useUsage";
import { getMyPrefs, setLastSeenAnnouncement } from "@/lib/client/prefs";
import {
  getLatestAnnouncement,
  type AnnouncementNote,
} from "@/lib/client/quota";

const SEEN_KEY = "medi_last_seen_announcement_id";

export function PatchNotesList({ items }: { items: string[] }) {
  return (
    <ul className="flex flex-col gap-3">
      {items.map((it, i) => (
        <li key={i} className="flex gap-3 text-[15.5px] leading-[1.75] text-md-on-surface">
          <span
            aria-hidden
            className="mt-[0.55em] h-1.5 w-1.5 shrink-0 rounded-full bg-md-primary"
          />
          <span className="min-w-0 break-keep text-pretty [overflow-wrap:anywhere]">{it}</span>
        </li>
      ))}
    </ul>
  );
}

export function PatchNotesPrompt() {
  // ⚠️ 인증 토큰은 NextAuth 세션 동기화 **후** 메모리에 실린다 — 마운트 직후
  // 바로 조회하면 무토큰 401 로 조용히 실패해 팝업이 영영 안 뜬다(2026-08-13
  // /new 페이지 실측). usage 도착 = 인증 완료 신호를 기다린다
  // (TokenFeedbackPrompt 와 같은 게이팅).
  const { usage } = useUsage();
  const router = useRouter();
  const fetched = useRef(false);
  const [note, setNote] = useState<AnnouncementNote | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!usage || fetched.current) return;
    fetched.current = true;
    let alive = true;
    void (async () => {
      try {
        // 이미 본 노트 id 를 서버에도 넘긴다 — 서버가 같은 판단을 한 번 더 한다.
        let knownSeen: string[] = [];
        try {
          knownSeen = [
            window.localStorage.getItem(SEEN_KEY) ?? "",
            window.sessionStorage.getItem(SEEN_KEY) ?? "",
          ].filter(Boolean);
        } catch { /* 저장소 불가 */ }
        const latest = await getLatestAnnouncement(knownSeen);
        if (!alive || !latest) return;
        // 확인 여부는 세 곳 OR(2026-09-07, "한 번 끄면 계속 뜬다" 신고): 서버(/me/prefs,
        // 기기·브라우저 무관) · localStorage · sessionStorage(이번 탭). 어느 하나라도
        // 이 노트를 봤다고 하면 안 띄운다. 종전엔 localStorage 하나뿐이라 브라우저를
        // 바꾸거나 저장이 막힌 환경(시크릿·저장소 차단)에서 접속마다 다시 떴다.
        let seen: string | null = null;
        let sessionSeen: string | null = null;
        try {
          seen = window.localStorage.getItem(SEEN_KEY);
          sessionSeen = window.sessionStorage.getItem(SEEN_KEY);
        } catch { /* 저장소 불가 — 서버 값으로 판단 */ }
        let serverSeen: string | null = null;
        try {
          serverSeen = (await getMyPrefs()).last_seen_announcement_id ?? null;
        } catch { /* 조회 실패 — 로컬 값으로 판단 */ }
        if (!alive) return;
        if (serverSeen === latest.id && seen !== latest.id) {
          // 서버가 봤다고 하면 로컬도 맞춰 둔다(다음 접속에 서버 왕복 없이 판단).
          try { window.localStorage.setItem(SEEN_KEY, latest.id); } catch { /* 무시 */ }
        }
        if (seen === latest.id || sessionSeen === latest.id || serverSeen === latest.id) return;
        // 첫 방문 충돌 방지(2026-08-28 긴급): 투어(전면 오버레이 z-80)가 곧
        // 자동 시작되는 상태면 이번 접속엔 팝업을 미룬다 — 동시에 뜨면 투어
        // 오버레이가 이 모달의 버튼을 덮어 "창이 안 닫히는" 사고. id 를
        // 저장하지 않으므로 다음 접속(투어 완료 후)에 정상 노출된다.
        try {
          if (!window.localStorage.getItem("medi_feature_tour_v2")) return;
        } catch { /* 판단 불가면 그대로 진행 */ }
        // 띄우는 순간 이번 탭엔 "봤음" 표시 — 닫기 경로가 어떻게 끝나든(새로고침·
        // 이동·닫기 실패) 같은 탭에서 두 번 뜨지 않는다.
        try { window.sessionStorage.setItem(SEEN_KEY, latest.id); } catch { /* 무시 */ }
        setNote(latest);
        setOpen(true);
      } catch {
        // 조회 실패는 조용히 — 팝업은 부가 기능, 접속을 방해하면 안 된다.
      }
    })();
    return () => {
      alive = false;
    };
  }, [usage]);

  const dismiss = () => {
    if (note) {
      try {
        window.localStorage.setItem(SEEN_KEY, note.id);
      } catch { /* 무시 */ }
      // 서버에도 기록 — 다른 브라우저·기기에서도 다시 안 뜬다(2026-09-07).
      void setLastSeenAnnouncement(note.id).catch(() => { /* 실패해도 로컬로 막힌다 */ });
    }
    setOpen(false);
  };

  // [업데이트 목록 보기](2026-09-02 피드백) — 이번 노트만이 아니라 지금까지의
  // 업데이트를 훑어 놓친 것·기다리던 기능이 들어왔는지 확인. 닫음 처리(id 저장)
  // 후 게시판의 이 노트 위치로.
  const goList = () => {
    const id = note?.id;
    dismiss();
    router.push(id ? `/updates#${id}` : "/updates");
  };

  if (!note) return null;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && dismiss()}>
      <DialogContent className="w-[min(92vw,760px)] max-w-none">
        <DialogHeader>
          <DialogTitle>{note.title}</DialogTitle>
          <DialogDescription>
            {note.feature ? (
              <span className="mr-2 inline-flex items-center rounded-full bg-md-primary-container px-2 py-0.5 text-[11px] font-semibold text-md-on-primary-container">
                {note.feature}
              </span>
            ) : null}
            {note.version ? (
              <span className="mr-2 inline-flex items-center rounded-full bg-md-surface-container-high px-2 py-0.5 font-mono text-[11px] font-semibold text-md-on-surface">
                {note.version}
              </span>
            ) : null}
            {note.date} — 이런 점이 좋아졌어요.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[55vh] overflow-y-auto pr-1 text-md-on-surface">
          <PatchNotesList items={note.items} />
        </DialogBody>
        <DialogFooter className="justify-between">
          <DialogAction variant="secondary" onClick={goList}>
            업데이트 목록 보기
          </DialogAction>
          <DialogAction onClick={dismiss}>확인</DialogAction>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
