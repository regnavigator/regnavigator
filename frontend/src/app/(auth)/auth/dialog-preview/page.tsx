"use client";

/**
 * Dialog preview — `dialog.tsx` 레이아웃 점검용 (dev only).
 *
 * 접근: /auth/dialog-preview
 * production: middleware 가 /login 으로 redirect.
 */

import { useState } from "react";
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
import { PatchNotesList } from "@/components/shell/PatchNotesPrompt";
import { Button } from "@/components/ui/button";

type Variant = "confirm" | "settings" | "delete" | "update";

const VARIANTS: { id: Variant; label: string; width: string }[] = [
  { id: "confirm", label: "확인", width: "max-w-sm" },
  { id: "settings", label: "설정형", width: "max-w-lg" },
  { id: "delete", label: "삭제", width: "max-w-[420px]" },
  { id: "update", label: "업데이트", width: "max-w-xl" },
];

const SAMPLE_PATCH_ITEMS = [
  "보고서 미리보기에서 참고문헌을 번호 순으로 정렬해 표시합니다.",
  "별표·서식 모달에서 HWP 다운로드와 본문 미리보기를 한 화면에서 볼 수 있습니다.",
  "대화 삭제 확인 문구가 긴 제목에서도 자연스럽게 줄바꿈되도록 개선했습니다.",
  "IRB/DRB 상담 모드 안내와 입력창 레이아웃을 다듬었습니다.",
];

const SAMPLE_LONG_TITLE =
  "IRB 심의 일정 및 연구계획서 제출 관련 문의 (2026년 상반기 임상시험)";

export default function DialogPreviewPage() {
  const [open, setOpen] = useState(true);
  const [variant, setVariant] = useState<Variant>("confirm");

  const active = VARIANTS.find((v) => v.id === variant)!;

  return (
    <div className="min-h-screen bg-md-surface-container-low px-6 py-10">
      <div className="mx-auto max-w-xl space-y-5">
        <div>
          <p className="text-label-caps text-md-on-surface-variant">dev · dialog preview</p>
          <h1 className="mt-1 text-h1 text-md-on-surface">모달 레이아웃 미리보기</h1>
          <p className="mt-2 text-body-sm text-md-on-surface-variant">
            <code className="text-code">src/components/ui/dialog.tsx</code> 저장 시 HMR로 즉시
            반영됩니다. 배경은 앱과 구분용이며 모달 스타일과 무관합니다.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {VARIANTS.map((v) => (
            <Button
              key={v.id}
              type="button"
              variant={variant === v.id ? "default" : "outline"}
              onClick={() => {
                setVariant(v.id);
                setOpen(true);
              }}
            >
              {v.label}
            </Button>
          ))}
          <Button type="button" variant="ghost" onClick={() => setOpen(true)}>
            다시 열기
          </Button>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className={active.width}>
          {variant === "confirm" ? (
            <>
              <DialogHeader>
                <DialogTitle>대화를 삭제할까요?</DialogTitle>
                <DialogDescription>
                  이 작업은 되돌릴 수 없습니다. 계속하시겠습니까?
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogAction variant="secondary" onClick={() => setOpen(false)}>
                  취소
                </DialogAction>
                <DialogAction onClick={() => setOpen(false)}>확인</DialogAction>
              </DialogFooter>
            </>
          ) : null}

          {variant === "settings" ? (
            <>
              <DialogHeader>
                <DialogTitle>설정</DialogTitle>
                <DialogDescription>
                  백엔드(medi-back) 연결 정보 — dev override 전용. 운영 배포는 빌드 env 로
                  주입됩니다.
                </DialogDescription>
              </DialogHeader>
              <DialogBody className="rounded-[10px] bg-md-surface-container-low/50 p-4 text-md-on-surface-variant">
                본문 영역 — 폼·리스트·안내 박스 등이 들어가는 자리입니다.
              </DialogBody>
              <DialogFooter>
                <DialogAction onClick={() => setOpen(false)}>저장</DialogAction>
              </DialogFooter>
            </>
          ) : null}

          {variant === "delete" ? (
            <>
              <DialogHeader>
                <div className="flex items-center gap-3">
                  <span
                    aria-hidden
                    className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-md-error-container text-md-error"
                  >
                    <span className="material-symbols-outlined text-[20px]">delete</span>
                  </span>
                  <DialogTitle>대화 삭제</DialogTitle>
                </div>
                <div className="mt-2.5 space-y-1 text-body-sm leading-[1.6] text-md-on-surface-variant">
                  <p>
                    <span className="font-medium text-md-on-surface">
                      &ldquo;{SAMPLE_LONG_TITLE}&rdquo;
                    </span>
                    을(를) 삭제합니다.
                  </p>
                  <p>이 작업은 되돌릴 수 없습니다.</p>
                </div>
              </DialogHeader>
              <DialogFooter>
                <DialogAction variant="secondary" onClick={() => setOpen(false)}>
                  취소
                </DialogAction>
                <DialogAction variant="destructive" onClick={() => setOpen(false)}>
                  삭제
                </DialogAction>
              </DialogFooter>
            </>
          ) : null}

          {variant === "update" ? (
            <>
              <DialogHeader>
                <DialogTitle>오늘의 업데이트</DialogTitle>
                <DialogDescription>2026-09-02 — 이런 점이 좋아졌어요.</DialogDescription>
              </DialogHeader>
              <DialogBody className="max-h-[55vh] overflow-y-auto pr-1 text-md-on-surface">
                <PatchNotesList items={SAMPLE_PATCH_ITEMS} />
              </DialogBody>
              <DialogFooter>
                <DialogAction onClick={() => setOpen(false)}>확인</DialogAction>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
