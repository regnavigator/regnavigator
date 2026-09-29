"use client";

/**
 * UserMessage — 03 §3, P4.6.
 *
 * 오른쪽 정렬, max 70%. 12px radius (꼬리 br 0). 사용자 입력은 그대로 표시
 * (`whitespace-pre-wrap`). markdown 렌더 X.
 *
 * 첨부(파일 업로드 v1): 본문 속 `<attachment name="...">…</attachment>` 블록
 * (백엔드 `_compose_message` 형식)은 벽면 텍스트로 펼치지 않고 **칩으로 접어**
 * 렌더 — 클릭 시 전문 펼침. 형식 변경 시 backend routes/chat.py 와 동기.
 */

import { useState } from "react";

type Props = {
  content: string;
};

type ParsedAttachment = { name: string; text: string };

const ATT_RE = /\n*<attachment name="([^"]*)">\n([\s\S]*?)\n<\/attachment>/g;

function parseAttachments(content: string): { body: string; attachments: ParsedAttachment[] } {
  const attachments: ParsedAttachment[] = [];
  const body = content
    .replace(ATT_RE, (_m, name: string, text: string) => {
      attachments.push({ name, text });
      return "";
    })
    .trim();
  return { body, attachments };
}

export function UserMessage({ content }: Props) {
  const { body, attachments } = parseAttachments(content);
  return (
    <div className="flex w-full justify-end">
      <div className="flex max-w-[80%] flex-col items-end gap-1.5">
        {body ? (
          <div className="whitespace-pre-wrap break-words rounded-2xl bg-md-surface-container px-4 py-2.5 text-body-base text-md-on-surface">
            {body}
          </div>
        ) : null}
        {attachments.map((a, i) => (
          <AttachmentChip key={`${a.name}-${i}`} attachment={a} />
        ))}
      </div>
    </div>
  );
}

function AttachmentChip({ attachment }: { attachment: ParsedAttachment }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="max-w-full rounded-xl border border-md-outline-variant bg-md-surface-container-low">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-left text-[12px] text-md-on-surface transition-colors hover:bg-md-surface-container"
      >
        <span className="material-symbols-outlined text-[15px] text-md-on-surface-variant" aria-hidden>
          description
        </span>
        <span className="min-w-0 truncate font-medium">{attachment.name}</span>
        <span className="shrink-0 tabular-nums text-[10.5px] text-md-on-surface-variant">
          {attachment.text.length.toLocaleString()}자
        </span>
        <span className="material-symbols-outlined shrink-0 text-[15px] text-md-on-surface-variant" aria-hidden>
          {open ? "expand_less" : "expand_more"}
        </span>
      </button>
      {open ? (
        <pre
          className="max-h-[320px] overflow-y-auto whitespace-pre-wrap border-t border-md-outline-variant/60 px-3 py-2 text-[12px] leading-relaxed text-md-on-surface-variant"
          style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
        >
          {attachment.text}
        </pre>
      ) : null}
    </div>
  );
}
