/**
 * 내 설정(/me/prefs) — 이메일 수신(보고서 완료·서비스 안내) + 업데이트 팝업 확인 노트.
 */
import { apiFetch } from "@/lib/api/client";

export type MyPrefs = {
  report_email_opt_in: boolean;
  /** 서비스 안내 메일(기능 추가·변경 고지) 수신. 기본 ON. 2026-09-10 도입→철회→09-14 재도입.
   *  마케팅 동의(legal_consent scopes)와 별개 축 — 서비스 고지의 수신거부 수단. */
  notice_email_opt_in?: boolean;
  /** 마지막으로 닫은 업데이트 팝업 노트 id(2026-09-07) — 기기·브라우저 무관 1회 노출 */
  last_seen_announcement_id?: string | null;
};

export async function getMyPrefs(): Promise<MyPrefs> {
  return apiFetch("/me/prefs");
}

export async function setReportEmailOptIn(v: boolean): Promise<void> {
  await apiFetch("/me/prefs", {
    method: "PATCH",
    body: JSON.stringify({ report_email_opt_in: v }),
  });
}

/** 서비스 안내 메일 수신 on/off — 뉴스레터 푸터가 가리키는 그 설정. */
export async function setNoticeEmailOptIn(v: boolean): Promise<void> {
  await apiFetch("/me/prefs", {
    method: "PATCH",
    body: JSON.stringify({ notice_email_opt_in: v }),
  });
}

/** 업데이트 팝업을 닫은 노트 id 를 서버에 기록 — 다른 기기에서도 다시 안 뜨게. */
export async function setLastSeenAnnouncement(noteId: string): Promise<void> {
  await apiFetch("/me/prefs", {
    method: "PATCH",
    body: JSON.stringify({ last_seen_announcement_id: noteId }),
  });
}

/** 사용자별 앱 내 알림(2026-09-15) — 관리자가 지정한 사용자에게만, 최초 접속 1회. */
export type UserNotice = {
  id: string;
  date: string;
  title: string;
  items: string[];
  created_at: string;
  seen_at?: string | null;
};

export async function getMyPendingNotice(): Promise<UserNotice | null> {
  const r = await apiFetch<{ notice: UserNotice | null }>("/me/notices/pending");
  return r.notice ?? null;
}

export async function markNoticeSeen(noticeId: string): Promise<void> {
  await apiFetch(`/me/notices/${encodeURIComponent(noticeId)}/seen`, { method: "POST" });
}
