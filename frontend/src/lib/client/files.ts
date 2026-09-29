/**
 * 파일 첨부 v1 — POST /files/extract (multipart).
 *
 * 서버는 원본을 저장하지 않고 추출 텍스트만 돌려준다. 프런트가 이 결과를
 * 들고 있다가 전송 시 POST /chat 의 `attachments` 로 보낸다.
 * apiFetch 는 Content-Type: application/json 을 강제하므로 여기선 직접 fetch
 * (multipart boundary 는 브라우저가 설정).
 */

import { getAuthToken } from "@/lib/client/authToken";
import { getEffectiveSettings } from "@/lib/store/settings";

export type ExtractedAttachment = {
  name: string;
  kind: "pdf" | "docx" | "hwpx" | "txt";
  chars: number;
  /** 추출 상한 초과로 뒷부분이 잘렸는가 — 칩에 경고 표시 */
  truncated: boolean;
  text: string;
};

export async function extractFile(file: File): Promise<ExtractedAttachment> {
  const base = getEffectiveSettings().deployment_url?.replace(/\/+$/, "");
  if (!base) throw new Error("backend URL 미설정");
  const fd = new FormData();
  fd.append("file", file);
  const token = getAuthToken();
  let res: Response;
  try {
    res = await fetch(`${base}/files/extract`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: fd,
    });
  } catch {
    // fetch 자체 실패(네트워크·CORS) — "Failed to fetch" 영문 노출 방지
    throw new Error("서버에 연결하지 못했습니다. 네트워크 확인 후 다시 시도해주세요.");
  }
  if (!res.ok) {
    // 백엔드 detail 은 사용자에게 그대로 보여줄 한국어 안내(413/415/422).
    let detail = "";
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? "";
    } catch {
      /* JSON 아님 — 아래 폴백 */
    }
    throw new Error(detail || `파일 처리 실패 (HTTP ${res.status})`);
  }
  return (await res.json()) as ExtractedAttachment;
}
