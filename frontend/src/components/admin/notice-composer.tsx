"use client";

/**
 * 공지 메일 작성기 — 관리자 설정 페이지와 사용자 관리(선택 발송) 공용.
 *
 * 두 모드:
 *  - audience: 수신자를 프리셋으로 고름(전체/화이트리스트/베타 초대자/관리자).
 *    발송 전 "수신자 확인"(dry_run)으로 명단을 눈으로 본다.
 *  - explicit: 호출자가 준 주소 목록으로 고정(사용자 목록에서 체크한 사람들).
 *    명단이 이미 확정이라 dry_run 이 필요 없다.
 *
 * 예약: `send_at`(ISO Z)을 실으면 backend 가 큐에 넣고 스케줄러가 발송한다.
 * 미리보기: `preview` 로 렌더된 HTML 을 받아 iframe 에 띄운다(발송 안 함).
 */

import { APP_URL } from "@/lib/site";
import { useState } from "react";
import { toast } from "sonner";
import {
  adminNotify,
  previewNotice,
  type NotifyAudience,
  type NotifyResult,
} from "@/lib/client/admin";
import { Button } from "@/components/ui/button";

export const AUDIENCE_LABEL: Record<NotifyAudience, string> = {
  all: "전체 회원",
  whitelisted: "화이트리스트 회원",
  beta_testers: "베타 초대자 전체 (미가입 포함)",
  admins: "관리자만 (테스트)",
};

export const BETA_OPEN_TEMPLATE = {
  subject: "[MEDIREG] 클로즈 베타를 시작합니다",
  body: `안녕하세요, MEDIREG입니다.

의료기기 인허가·규제 상담 서비스 MEDIREG의 클로즈 베타를 시작합니다.
초대해 주신 이메일 주소로 바로 로그인하실 수 있습니다.

· 로그인: 초대받은 이메일 주소로 가입/로그인
· 사용 가능 기능: 규제·법령 질의응답(근거 조문 인용), 심층 보고서 생성

베타 기간 중에는 응답 속도·정확도를 계속 개선합니다.
답변 하단의 평가 버튼이나 회신으로 의견 주시면 큰 도움이 됩니다.

감사합니다.
MEDIREG 드림`,
  cta_url: APP_URL,
  cta_label: "MEDIREG 시작하기",
};

/** datetime-local("2026-08-05T09:00") → ISO Z. 로컬 시각 입력을 UTC 로 넘긴다. */
function toIsoZ(local: string): string {
  return new Date(local).toISOString();
}

export function NoticeComposer({
  mode,
  emails,
  onDone,
}: {
  mode: "audience" | "explicit";
  /** mode="explicit" 일 때 수신자 */
  emails?: string[];
  onDone?: () => void;
}) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [ctaUrl, setCtaUrl] = useState(BETA_OPEN_TEMPLATE.cta_url);
  const [ctaLabel, setCtaLabel] = useState(BETA_OPEN_TEMPLATE.cta_label);
  // 회신 주소 — 비우면 서버 기본(NOTICE_REPLY_TO). From 은 noreply 라 이게 없으면
  // "메일로 문의하세요" 안내가 무의미해진다.
  const [replyTo, setReplyTo] = useState("");
  const [to, setTo] = useState<NotifyAudience>("admins");
  const [sendAt, setSendAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<NotifyResult | null>(null);
  const [html, setHtml] = useState<string | null>(null);

  const explicit = mode === "explicit";
  const recipients = explicit ? (emails ?? []) : undefined;
  const ready = !!subject.trim() && !!body.trim() && (!explicit || (recipients?.length ?? 0) > 0);

  const payload = () => ({
    subject: subject.trim(),
    body: body.trim(),
    to: (explicit ? recipients! : to) as NotifyAudience | string[],
    ...(ctaUrl.trim() ? { cta_url: ctaUrl.trim(), cta_label: ctaLabel.trim() || undefined } : {}),
    ...(replyTo.trim() ? { reply_to: replyTo.trim() } : {}),
  });

  const run = async (kind: "dry" | "send") => {
    setBusy(true);
    try {
      const scheduled = kind === "send" && sendAt.trim();
      const r = await adminNotify({
        ...payload(),
        dry_run: kind === "dry",
        ...(scheduled ? { send_at: toIsoZ(sendAt) } : {}),
      });
      if (kind === "dry") {
        setPreview(r);
        if (r.smtp_configured === false) {
          toast.error("SMTP 미설정 — 지금 발송하면 실제 메일이 나가지 않습니다(로그만).", { duration: 10000 });
        } else {
          toast.success(`수신자 ${r.requested}명 확인 — 발송하지 않았습니다`);
        }
        return;
      }
      if (r.scheduled) {
        toast.success(
          `예약됨 — ${new Date(r.notice!.send_at).toLocaleString("ko-KR")} · 예상 ${r.requested}명`,
          { duration: 8000 },
        );
      } else if (r.smtp_configured === false) {
        toast.error(`실제 발송 안 됨 — SMTP 미설정(대상 ${r.requested}명)`, { duration: 10000 });
        return; // 작성 내용 보존 — 설정 고친 뒤 다시 눌러야 함
      } else if ((r.failed?.length ?? 0) > 0) {
        toast.error(
          `발송 ${r.sent}/${r.requested} — 실패 ${r.failed!.length}건 (${r.failed!.slice(0, 3).join(", ")})`,
          { duration: 10000 },
        );
      } else {
        toast.success(`발송 완료 — ${r.sent}/${r.requested}명`);
      }
      setSubject("");
      setBody("");
      setSendAt("");
      setPreview(null);
      onDone?.();
    } catch {
      toast.error(kind === "dry" ? "수신자 확인 실패" : "발송 실패");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {explicit ? (
          <span className="rounded-pill bg-md-primary-container px-3 py-1 text-[12px] font-semibold text-md-on-primary-container">
            선택한 {recipients!.length}명에게 발송
          </span>
        ) : (
          <select
            value={to}
            onChange={(e) => { setTo(e.target.value as NotifyAudience); setPreview(null); }}
            className="h-9 rounded-input border border-md-outline-variant bg-md-surface px-2 text-[13px] text-md-on-surface focus:border-md-primary focus:outline-none"
          >
            {(Object.keys(AUDIENCE_LABEL) as NotifyAudience[]).map((a) => (
              <option key={a} value={a}>{AUDIENCE_LABEL[a]}</option>
            ))}
          </select>
        )}
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="제목"
          className="h-9 w-full min-w-0 flex-1 rounded-input border border-md-outline-variant bg-md-surface px-2.5 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
        />
        <button
          type="button"
          onClick={() => {
            setSubject(BETA_OPEN_TEMPLATE.subject);
            setBody(BETA_OPEN_TEMPLATE.body);
            setCtaUrl(BETA_OPEN_TEMPLATE.cta_url);
            setCtaLabel(BETA_OPEN_TEMPLATE.cta_label);
            setPreview(null);
          }}
          className="h-9 whitespace-nowrap rounded-input border border-md-outline-variant px-3 text-[12px] text-md-on-surface-variant hover:bg-md-surface-container"
        >
          클로즈 베타 템플릿
        </button>
      </div>

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={8}
        placeholder="본문 (평문 — 빈 줄로 문단 구분. 서비스 테마 HTML 로 감싸 발송됩니다)"
        className="w-full resize-y rounded-input border border-md-outline-variant bg-md-surface px-2.5 py-2 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
      />

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={ctaUrl}
          onChange={(e) => setCtaUrl(e.target.value)}
          placeholder="버튼 링크(비우면 버튼 없음)"
          className="h-9 min-w-0 flex-1 rounded-input border border-md-outline-variant bg-md-surface px-2.5 text-[12.5px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
        />
        <input
          value={ctaLabel}
          onChange={(e) => setCtaLabel(e.target.value)}
          placeholder="버튼 문구"
          className="h-9 w-40 rounded-input border border-md-outline-variant bg-md-surface px-2.5 text-[12.5px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
        />
        <input
          value={replyTo}
          onChange={(e) => setReplyTo(e.target.value)}
          placeholder="회신 주소(비우면 기본값)"
          className="h-9 w-56 rounded-input border border-md-outline-variant bg-md-surface px-2.5 text-[12.5px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
        />
      </div>

      <label className="flex flex-wrap items-center gap-2 text-[12px] text-md-on-surface-variant">
        예약 발송
        <input
          type="datetime-local"
          value={sendAt}
          onChange={(e) => setSendAt(e.target.value)}
          className="h-9 rounded-input border border-md-outline-variant bg-md-surface px-2 text-[12.5px] text-md-on-surface focus:border-md-primary focus:outline-none"
        />
        {sendAt ? (
          <button type="button" onClick={() => setSendAt("")} className="text-[12px] text-md-error">
            즉시 발송으로
          </button>
        ) : (
          <span className="text-[11.5px] opacity-70">비우면 즉시 발송</span>
        )}
      </label>

      {preview ? (
        <div className="rounded-card border border-md-outline-variant bg-md-surface p-3">
          <p className="text-[12px] font-semibold text-md-on-surface">
            수신자 {preview.requested}명 — 아직 발송하지 않았습니다
          </p>
          <ul className="mt-2 max-h-40 overflow-y-auto font-mono text-[11.5px] text-md-on-surface-variant">
            {preview.recipients?.map((e) => <li key={e}>{e}</li>)}
          </ul>
        </div>
      ) : null}

      {html ? (
        <div className="rounded-card border border-md-outline-variant bg-md-surface p-2">
          <div className="flex items-center justify-between px-1 pb-2">
            <span className="text-[12px] font-semibold text-md-on-surface">메일 미리보기</span>
            <button type="button" onClick={() => setHtml(null)} className="text-[12px] text-md-on-surface-variant">
              닫기
            </button>
          </div>
          <iframe
            title="메일 미리보기"
            srcDoc={html}
            sandbox=""
            className="h-[420px] w-full rounded border border-md-outline-variant bg-white"
          />
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          disabled={busy || !subject.trim() || !body.trim()}
          onClick={() => void (async () => {
            try {
              setHtml(await previewNotice({
                subject: subject.trim(), body: body.trim(),
                ...(ctaUrl.trim() ? { cta_url: ctaUrl.trim(), cta_label: ctaLabel.trim() } : {}),
              }));
            } catch { toast.error("미리보기 실패"); }
          })()}
        >
          메일 미리보기
        </Button>
        {!explicit ? (
          <Button variant="ghost" disabled={busy || !ready} onClick={() => void run("dry")}>
            수신자 확인 (발송 안 함)
          </Button>
        ) : null}
        <Button
          disabled={busy || !ready}
          onClick={() => void (async () => {
            const who = explicit
              ? `선택한 ${recipients!.length}명`
              : preview ? `수신자 ${preview.requested}명` : `${AUDIENCE_LABEL[to]}(명단 미확인)`;
            const when = sendAt ? `\n예약: ${new Date(sendAt).toLocaleString("ko-KR")}` : "";
            if (!window.confirm(`${who}에게 공지를 ${sendAt ? "예약" : "발송"}할까요?${when}`)) return;
            await run("send");
          })()}
        >
          {busy ? "처리 중…" : sendAt ? "예약" : "발송"}
        </Button>
      </div>
    </div>
  );
}
