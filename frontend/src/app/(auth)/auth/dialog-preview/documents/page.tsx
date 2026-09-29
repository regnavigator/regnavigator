"use client";

/**
 * 서식 관리 모달 미리보기 (dev only) — /auth/dialog-preview/documents
 *
 * 로그인·백엔드 없이 샘플 데이터로 `DocumentsDialog` 를 띄운다. 내려받기·삭제는
 * 화면 반응만 흉내 낸다. production 은 middleware 가 /login 으로 redirect.
 */

import { useState } from "react";
import { Toaster } from "sonner";
import { DocumentsDialog } from "@/components/panel/DocumentsDialog";
import type { DocumentListItem } from "@/lib/client/documents";
import { Button } from "@/components/ui/button";

const SAMPLE: DocumentListItem[] = [
  { id: "doc_sample_0001", title: "의료기기 제조업 허가신청서 (별지 제1호서식)", alias: "A사 1차 제출", thread_id: "t1", thread_title: "체외진단기기 제조업 허가 요건 상담", thread_alive: true, created_at: "2026-09-18T02:10:00Z", field_count: 12, filled_count: 5, status: "partial", kept: false },
  { id: "doc_sample_0002", title: "의료기기 제조(수입) 허가 신청서 (별지 제3호서식)", alias: null, thread_id: "t2", thread_title: "수입 허가 절차와 제출 서류", thread_alive: true, created_at: "2026-09-16T07:42:00Z", field_count: 12, filled_count: 12, status: "done", kept: true },
  { id: "doc_sample_0003", title: "임상시험계획 승인신청서", alias: null, thread_id: "t3", thread_title: "2상 임상시험계획 승인 신청 준비", thread_alive: true, created_at: "2026-09-11T01:05:00Z", field_count: 18, filled_count: 0, status: "empty", kept: false },
  // 원 대화가 삭제된 보관 서식 — [대화] 버튼이 꺼진다.
  { id: "doc_sample_0004", title: "의료기기 변경허가(인증) 신청서 — 제목이 아주 길어서 한 줄에 다 들어가지 않는 경우의 말줄임 확인용", alias: "B사 변경허가", thread_id: "t4", thread_title: null, thread_alive: false, created_at: "2026-09-02T09:30:00Z", field_count: 9, filled_count: 9, status: "done", kept: true },
];

export default function DocumentsDialogPreviewPage() {
  const [open, setOpen] = useState(true);
  const [empty, setEmpty] = useState(false);
  return (
    <div className="min-h-screen bg-md-surface-container-low px-6 py-10">
      <Toaster position="top-center" />
      <div className="mx-auto max-w-xl space-y-4">
        <p className="text-label-caps text-md-on-surface-variant">dev · dialog preview</p>
        <h1 className="text-h1 text-md-on-surface">서식 관리 모달</h1>
        <p className="text-body-sm text-md-on-surface-variant">
          샘플 데이터입니다. 실제 화면에서는 사이드바 &ldquo;작성한 서식&rdquo; 섹션의 [관리]로 엽니다. 네 번째 행은 원 대화가 삭제된 보관 서식입니다.
        </p>
        <div className="flex gap-2">
          <Button onClick={() => { setEmpty(false); setOpen(true); }}>목록 있는 상태</Button>
          <Button variant="outline" onClick={() => { setEmpty(true); setOpen(true); }}>빈 상태</Button>
        </div>
      </div>
      <DocumentsDialog
        key={empty ? "empty" : "list"}
        open={open}
        onOpenChange={setOpen}
        previewItems={empty ? [] : SAMPLE}
      />
    </div>
  );
}
