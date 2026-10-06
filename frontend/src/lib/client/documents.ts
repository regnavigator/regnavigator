/**
 * 서류 초안(document_draft) API — Phase ③ (2026-08-24).
 *
 * 문서 패널·전체화면 뷰가 쓰는 3종:
 *  - state: 스레드의 최신 초안 상태(항목·기입값) — 스레드 로드 시 복원
 *  - body: 원본 마크다운(`fill=0` — `[확인 필요:]` 마커 유지, 칩 렌더용)
 *  - fill: 항목 기입 (직접 입력값 저장 / ✨ AI 작성 / `*` 일괄)
 *
 * 다운로드(치환본)는 기존 `downloadReport`(`client/reports.ts`) 재사용 —
 * 백엔드가 `fill=1`(기본)로 기입값을 치환해 내보낸다.
 */

import { apiFetch, apiFetchBlobWithExt, apiFetchText } from "@/lib/api/client";

export type DocumentDraftState = {
  report_id: string | null;
  fields?: string[];
  filled?: Record<string, string>;
  remaining?: string[];
  /** 서식명 — 패널 제목. `from-form` 경로에서 항상 온다. */
  title?: string | null;
};

export type DocumentFillResult = {
  /** 이번 호출로 새로 채워진 항목만 */
  filled: Record<string, string>;
  /** 병합 후 전체 기입값 */
  values: Record<string, string>;
  remaining: string[];
};

export type DocumentListItem = {
  id: string;
  title: string | null;
  /** 사용자가 붙인 별명 — 같은 서식을 여러 건 쓸 때 구분용. 원 제목(title)은 그대로. */
  alias: string | null;
  thread_id: string;
  /** 서식을 만든 대화의 제목(대화가 없으면 null) */
  thread_title: string | null;
  /** 원 대화가 아직 있는지 — false 면 [대화로 가기] 불가(보관한 서식만 이 상태가 된다). */
  thread_alive: boolean;
  created_at: string | null;
  /** 서식의 전체 항목 수(0 = 본문을 못 읽음) · 채워진 항목 수 */
  field_count: number;
  filled_count: number;
  /** 작성 상태 — empty(미작성)·partial(작성 중)·done(완료) */
  status: "empty" | "partial" | "done";
  /** 보관(스크랩) — 보관한 서식은 원 대화가 삭제돼도 남는다. 아니면 대화와 함께 삭제. */
  kept: boolean;
};

/** 서식 별명 지정 — 빈 문자열이면 해제. 서버가 공백 정리·60자 제한. */
export async function setDocumentAlias(reportId: string, alias: string): Promise<string | null> {
  const r = await apiFetch<{ ok: boolean; alias: string | null }>(
    `/documents/${encodeURIComponent(reportId)}`,
    { method: "PATCH", body: JSON.stringify({ alias }) },
  );
  return r.alias ?? null;
}

/** 서식 보관(스크랩) 토글. */
export async function setDocumentKept(reportId: string, kept: boolean): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/documents/${encodeURIComponent(reportId)}/keep`, {
    method: "POST",
    body: JSON.stringify({ kept }),
  });
}

/**
 * 내가 작성한 서식 목록 — 스레드 무관, 최신순 (2026-09-18, 다시 보기·삭제).
 * 값 자체는 싣지 않는다(목록은 가볍게, 기입값은 패널에서만).
 */
export async function listDocuments(): Promise<DocumentListItem[]> {
  const res = await apiFetch<{ documents: DocumentListItem[] }>("/documents");
  return res.documents ?? [];
}

/** 사이드바 목록 ↔ 채팅 상태 동기용 window 이벤트 이름 (2026-09-18). */
export const DOCUMENTS_CHANGED_EVENT = "medi:documents-changed";
export const DOCUMENT_DELETED_EVENT = "medi:document-deleted";

/** 스레드의 최신 서류 초안 상태 — 없으면 `{report_id: null}`. */
export async function fetchDocumentState(
  threadId: string,
): Promise<DocumentDraftState> {
  return apiFetch<DocumentDraftState>(
    `/documents/state?thread_id=${encodeURIComponent(threadId)}`,
  );
}

/**
 * 선택한 별표·서식으로 **즉시** 기입 문서를 연다 (2026-08-27).
 *
 * 종전 [이 서식으로 작성]은 심층 보고서 파이프라인을 태워서, 서식을 골랐는데도
 * "심층 보고서 생성 중"이 뜨고 수십 분을 기다려야 항목이 나왔다. 항목은 서식
 * 자체에 있으므로 서버가 LLM 없이 몇 초 만에 만들어 준다.
 */
export async function createDocumentFromForm(body: {
  thread_id: string;
  article_key: string;
  title?: string;
}): Promise<DocumentDraftState> {
  return apiFetch<DocumentDraftState>("/documents/from-form", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export type DocumentChatResult = {
  /** 도우미의 안내 답변 */
  reply: string;
  /** 이번 턴에 새로 채워진 항목 */
  filled: Record<string, string>;
  /** 병합 후 전체 기입값 */
  values: Record<string, string>;
  remaining: string[];
  /** 이미 값이 있던 항목이 이번 턴에 고쳐진 것 */
  corrected: string[];
};

/**
 * 서식 작성 도우미 챗 한 턴 (2026-08-27) — 전용 모달용.
 *
 * 메시지는 채팅 스레드 밖에서 **온프레미스 모델로 직행**한다(개인정보를
 * 원문으로 칠 수 있는 유일한 대화 창구 — 저장 대화는 마스킹본이라 성명·연락처
 * 칸을 못 채우는 구조적 한계를 푼다). 서버는 대화를 저장하지 않는다.
 * 503 = 로컬 모델 미가용 — 직접 입력으로 안내.
 */
export async function chatFillDocument(
  reportId: string,
  body: { message: string; history?: string; attachment_text?: string },
): Promise<DocumentChatResult> {
  return apiFetch<DocumentChatResult>(
    `/documents/${encodeURIComponent(reportId)}/chat`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

/** 서류 화면 문제 신고(2026-08-27) — 파싱 오류·서식 아님·내용 불일치 기록. */
export async function reportDocumentIssue(body: {
  report_id: string;
  reason: string;
  comment?: string;
  article_key?: string;
  fields_count?: number;
}): Promise<void> {
  await apiFetch<{ ok: boolean }>("/feedback/document", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** 기입 레인 동시 요청 수 — 대기/지연 구분 표시용(2026-08-27). */
export async function getAssistLoad(): Promise<{ in_flight: number }> {
  return apiFetch<{ in_flight: number }>("/documents/assist/load");
}

/** 초안 원본 마크다운(마커 유지) — 패널 칩 렌더용. */
export async function fetchDocumentBody(reportId: string): Promise<string> {
  return apiFetchText(
    `/reports/${encodeURIComponent(reportId)}/download?format=md&fill=0`,
    { headers: { Accept: "text/markdown" } },
  );
}

/**
 * 항목 기입 — `value` 있으면 직접 저장(LLM 미경유), 없으면 ✨ AI 작성.
 * `field: "*"` = 미기입 전체 일괄 시도. 근거 부족 항목은 안 채워지고
 * `remaining` 에 남는다(날조 금지).
 */
export async function fillDocumentField(
  reportId: string,
  body: { field: string; hint?: string; value?: string },
): Promise<DocumentFillResult> {
  return apiFetch<DocumentFillResult>(
    `/documents/${encodeURIComponent(reportId)}/fill`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

/**
 * 관보 **원본 서식**(.hwpx) 기입 다운로드 — docx 변환본이 아니라 원래 파일형식.
 * 서버가 근거 인용의 law.go.kr 서식 원본에 기입값을 채워 돌려준다.
 *
 * 404 = 이 서류의 근거에 관보 서식 원본이 없음(기관 서식 등) — 호출자가 안내.
 * 503 = 서버에 서식 기입 도구 미배포.
 */
export async function downloadOriginalForm(reportId: string): Promise<string> {
  // 확장자는 서버가 알려준다(X-File-Ext) — patch 전환(2026-08-27) 후 산출물이
  // 원본 형식 그대로(.hwp)라 .hwpx 하드코딩이 틀린 이름을 붙였다.
  const { blob, ext } = await apiFetchBlobWithExt(
    `/documents/${encodeURIComponent(reportId)}/original-form`,
  );
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = `서식_${reportId.slice(0, 8)}.${ext}`;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  return ext;
}

// ── 서면·의견서 초안 (2026-10-01) ────────────────────────────────────────────

export type BriefParagraph = {
  index: number;
  text: string;
  kind: "heading" | "paragraph";
};

export type BriefDoc = {
  report_id: string;
  title: string;
  paragraphs: BriefParagraph[];
  citation_numbers: number[];
};

/** 대화에서 서면 초안을 만든다. 조문 본문 소스가 없어도 동작한다. */
export function createBrief(
  threadId: string,
  title?: string,
  kind?: string,
): Promise<BriefDoc> {
  return apiFetch<BriefDoc>("/documents/from-brief", {
    method: "POST",
    body: JSON.stringify({ thread_id: threadId, title, kind }),
  });
}

/** 현재 문단 목록 — 서버와 같은 쪼개기를 쓰려고 매번 서버에서 받는다. */
export function getBriefParagraphs(reportId: string): Promise<BriefDoc> {
  return apiFetch<BriefDoc>(
    `/documents/${encodeURIComponent(reportId)}/paragraphs`,
  );
}

export type ReviseResult = {
  ok: boolean;
  index: number;
  before: string;
  after: string;
  /** 문서에 없는 번호라 제거된 인용 — 사용자에게 알려야 한다 */
  dropped_citations: number[];
  paragraphs: BriefParagraph[];
};

/**
 * 문단 하나를 고친다.
 *
 * `instruction` = AI 에게 시키는 지시, `replacement` = 사용자가 직접 친 문장.
 * 후자는 원내 모델이 없어도 통과한다. `original_text` 는 낙관적 동시성 토큰이라
 * **반드시** 지금 화면에 보이는 그 텍스트여야 한다 — 어긋나면 409.
 */
export function reviseBriefParagraph(
  reportId: string,
  body: {
    index: number;
    original_text: string;
    instruction?: string;
    replacement?: string;
  },
): Promise<ReviseResult> {
  return apiFetch<ReviseResult>(
    `/documents/${encodeURIComponent(reportId)}/revise`,
    { method: "POST", body: JSON.stringify(body) },
  );
}

export type PolishResult = {
  ok: boolean;
  polished: string[];
  skipped: string[];
  dropped_citations: number[];
  paragraphs: BriefParagraph[];
};

/**
 * 초안을 보고서체로 다듬는다. **쓰기가 아니라 고쳐 쓰기** — 주어진 내용을
 * 논리 순서로 재배열하고 격식체로 바꿀 뿐이고, 새 인용 번호는 서버가 제거한다.
 */
export function polishBrief(
  reportId: string,
  sections?: string[],
): Promise<PolishResult> {
  return apiFetch<PolishResult>(
    `/documents/${encodeURIComponent(reportId)}/polish`,
    { method: "POST", body: JSON.stringify({ sections: sections ?? [] }) },
  );
}
