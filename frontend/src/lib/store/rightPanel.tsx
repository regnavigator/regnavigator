"use client";

/**
 * RightPanel UI state Context.
 *
 * 모든 패널 관련 ephemeral 상태(open / citation / docPath / documentId)를 메모리 관리.
 * URL에 박지 않음 — 깔끔 + 새로고침 시 자연스럽게 닫힘.
 *
 * thread/threadId만 URL에 남는다.
 *
 * ※ panelOverride("reports" 강제 모드)는 deep 진행 UI 폐기(단일 thread 전환)와
 *   함께 소비처가 사라져 제거 — 보고서 노출은 RightPanel이 state.reports로 자동.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import { withViewTransition } from "@/lib/viewTransition";

type RightPanelCtx = {
  open: boolean;
  setOpen: (v: boolean) => void;
  toggle: () => void;
  citation: string;
  docPath: string;
  /** 서류 초안(document_draft) 라이브 문서 모드 — report_id (Phase ③). */
  documentId: string;
  /** 세 키는 상호 배타 — 새로 set할 때 다른 키 자동 clear. */
  setCitation: (id: string | null) => void;
  setDocPath: (path: string | null) => void;
  setDocumentId: (id: string | null) => void;
};

const Ctx = createContext<RightPanelCtx | null>(null);

export function RightPanelProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [open, setOpenState] = useState(true);
  const [citation, setCitationState] = useState("");
  const [docPath, setDocPathState] = useState("");
  const [documentId, setDocumentIdState] = useState("");
  // ✨ 패널 열림/인용 전환을 View Transition으로 감쌈 — 지원 브라우저에서
  // 크로스페이드·morph(vt-citation-card), 미지원/reduced-motion은 즉시 적용.
  const setOpen = useCallback((v: boolean) => {
    withViewTransition(() => setOpenState(v));
  }, []);
  const toggle = useCallback(() => {
    withViewTransition(() => setOpenState((v) => !v));
  }, []);
  const setCitation = useCallback((id: string | null) => {
    withViewTransition(() => {
      setCitationState(id ?? "");
      if (id) {
        setDocPathState(""); // 상호 배타
        setDocumentIdState("");
      }
    });
  }, []);
  const setDocPath = useCallback((path: string | null) => {
    withViewTransition(() => {
      setDocPathState(path ?? "");
      if (path) {
        setCitationState(""); // 상호 배타
        setDocumentIdState("");
      }
    });
  }, []);
  const setDocumentId = useCallback((id: string | null) => {
    withViewTransition(() => {
      setDocumentIdState(id ?? "");
      if (id) {
        setCitationState(""); // 상호 배타
        setDocPathState("");
      }
    });
  }, []);
  const value = useMemo(
    () => ({
      open,
      setOpen,
      toggle,
      citation,
      docPath,
      documentId,
      setCitation,
      setDocPath,
      setDocumentId,
    }),
    [open, setOpen, toggle, citation, docPath, documentId,
     setCitation, setDocPath, setDocumentId],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRightPanel(): RightPanelCtx {
  const ctx = useContext(Ctx);
  if (!ctx) {
    return {
      open: true,
      setOpen: () => {},
      toggle: () => {},
      citation: "",
      docPath: "",
      documentId: "",
      setCitation: () => {},
      setDocPath: () => {},
      setDocumentId: () => {},
    };
  }
  return ctx;
}
