"use client";

/**
 * TokenFeedbackPrompt — 일정 토큰 이상 사용한 실사용자에게 피드백 모달(사용자 결정
 * 2026-07-16). 월 누적 토큰이 임계(기본 10만)를 넘으면 **월 1회** 노출.
 * 제출/닫기 모두 그 달엔 재노출 안 함. 전송: POST /feedback/general.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useUsage } from "@/lib/store/useUsage";
import { postGeneralFeedback } from "@/lib/client/quota";

const THRESHOLD_TOKENS = 100_000; // 월 누적 — 이 정도면 실사용자

function monthKey(): string {
  const d = new Date();
  return `medi_fb_prompt_${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function TokenFeedbackPrompt() {
  const { usage } = useUsage();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!usage) return;
    const monthly = usage.usage?.monthly_total_tokens ?? 0;
    if (monthly < THRESHOLD_TOKENS) return;
    try {
      if (window.localStorage.getItem(monthKey())) return;
    } catch {
      return; // localStorage 불가 — 노출 안 함(반복 방지 불가하므로)
    }
    setOpen(true);
  }, [usage]);

  const dismiss = () => {
    try {
      window.localStorage.setItem(monthKey(), "1");
    } catch { /* 무시 */ }
    setOpen(false);
  };

  const submit = async () => {
    const comment = text.trim();
    if (!comment) return;
    setBusy(true);
    try {
      await postGeneralFeedback({
        comment,
        context: { source: "token-threshold-prompt" },
      });
      toast.success("의견 감사합니다! 서비스 개선에 반영하겠습니다.");
      dismiss();
    } catch {
      toast.error("전송 실패 — 잠시 후 다시 시도해주세요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && dismiss()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>잠깐, 의견을 들려주세요 🙏</DialogTitle>
          <DialogDescription>
            서비스를 많이 활용해 주시고 계시네요. 좋았던 점이나 아쉬운 점을
            한 줄이라도 남겨주시면 개선에 큰 도움이 됩니다.
          </DialogDescription>
        </DialogHeader>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          maxLength={2000}
          autoFocus
          placeholder="예: 별표 서식 다운로드가 편해요 / 판례 검색이 더 정확했으면…"
          className="mt-2 w-full resize-none rounded-input border border-md-outline-variant bg-md-surface px-2.5 py-2 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
        />
        <div className="mt-3 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={dismiss} disabled={busy}>
            다음에
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !text.trim()}>
            {busy ? "전송 중…" : "의견 보내기"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
