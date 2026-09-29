"use client";

/**
 * DocumentPanel — 서류 초안(document_draft) 라이브 문서 뷰 (Phase ③, 2026-08-24).
 *
 * 초안 마크다운을 띄우고 `[확인 필요: 항목명]` 마커를 칩으로 렌더:
 *  - 미기입: 앰버 칩 — 클릭하면 하단 에디터(직접 입력 / ✨ AI 작성)
 *  - 기입됨: 값 하이라이트 — 채팅 SSE `document_update` 로 채워지면
 *    실시간 반영 + 잠깐 강조 애니메이션(채워지는 게 *보인다*)
 *
 * 채팅으로 말하면 백엔드 턴 대조 패스가 채우고(document_update), 이 패널은
 * `live`(ChatState.document) 병합만 한다. 전체화면(/documents/{id})에서는
 * live 없이 단독 동작 — 저장·AI 작성은 fill API 직접 호출.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import type { ChatState, Report } from "@/lib/store/types";
import {
  chatFillDocument,
  downloadOriginalForm,
  fetchDocumentBody,
  fillDocumentField,
  getAssistLoad,
  reportDocumentIssue,
} from "@/lib/client/documents";
import { downloadReport, getReport } from "@/lib/client/reports";
import { extractFile } from "@/lib/client/files";

/** 백엔드 doc_fill.UNFILLED_RE 와 동일 규격. */
const UNFILLED_RE = /\[확인 필요:\s*([^\]]+)\]/g;

function extractFields(body: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const m of body.matchAll(UNFILLED_RE)) {
    const f = (m[1] ?? "").trim();
    if (f && !seen.has(f)) {
      seen.add(f);
      out.push(f);
    }
  }
  return out;
}

type Props = {
  reportId: string;
  /** ChatState.document — 채팅 화면에서만. rev 변화가 라이브 병합 트리거. */
  live?: ChatState["document"] | null;
  /** 전체화면(/documents/{id}) — 본문 폭 확대, 패널 헤더 대신 페이지 헤더. */
  fullScreen?: boolean;
  /** 모달 호스트가 주는 닫기 — 있으면 헤더 오른쪽 끝에 닫기 버튼(내장 X 대체). */
  onClose?: () => void;
};

export function DocumentPanel({ reportId, live, fullScreen = false, onClose }: Props) {
  const [body, setBody] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filled, setFilled] = useState<Record<string, string>>({});
  // 방금 채워진 항목 — 하이라이트 애니메이션(2.5s 후 해제).
  const [justFilled, setJustFilled] = useState<Set<string>>(new Set());
  const [activeField, setActiveField] = useState<string | null>(null);
  const [editorText, setEditorText] = useState("");
  const [busy, setBusy] = useState<string | null>(null); // field | "*" | "download"
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastLiveRev = useRef(0);

  // 초기 로드 — 원본 본문(fill=0, 마커 유지) + 메타(filled_values·title).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setBody(null);
    setFilled({});
    setActiveField(null);
    lastLiveRev.current = 0;
    void (async () => {
      try {
        const [md, meta] = await Promise.all([
          fetchDocumentBody(reportId),
          getReport(reportId).catch(() => null),
        ]);
        if (cancelled) return;
        setBody(md);
        setTitle(meta?.title ?? null);
        try {
          setFilled(JSON.parse(meta?.filled_values || "{}"));
        } catch {
          setFilled({});
        }
      } catch {
        if (!cancelled) setError("문서를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  const markJustFilled = useCallback((names: string[]) => {
    if (!names.length) return;
    setJustFilled((prev) => new Set([...prev, ...names]));
    if (highlightTimer.current) clearTimeout(highlightTimer.current);
    highlightTimer.current = setTimeout(() => setJustFilled(new Set()), 2500);
  }, []);
  useEffect(
    () => () => {
      if (highlightTimer.current) clearTimeout(highlightTimer.current);
    },
    [],
  );

  // 라이브 병합 — 채팅 턴이 채운 항목(document_update)을 반영 + 강조.
  //
  // 두 입력 경로가 한 화면에 있으므로 충돌을 두 군데서 다룬다(2026-08-27):
  //  ① 편집 중인 항목을 채팅이 건드리면 → 에디터를 닫고 알린다. 그대로 두면
  //     사용자가 [저장]을 눌러 방금 채팅으로 들어온 값을 되돌린다.
  //  ② 채팅이 **이미 있던 값을 고친** 경우 → 새로 채운 것과 구분해 알린다.
  //     조용히 바뀌면 사용자는 자기가 넣은 값이 살아 있다고 믿는다.
  useEffect(() => {
    if (!live || live.report_id !== reportId) return;
    if (live.rev <= lastLiveRev.current) return;
    lastLiveRev.current = live.rev;
    setFilled((prev) => ({ ...prev, ...live.filled }));
    markJustFilled(live.last_filled ?? []);

    const corrected = live.last_corrected ?? [];
    if (corrected.length) {
      toast.info(`${corrected.length}개 항목을 대화 내용으로 고쳤어요`, {
        description: corrected.join(", ") + " — 되돌리려면 항목을 눌러 수정하세요.",
      });
    }
    if (activeField && (live.last_filled ?? []).includes(activeField)) {
      setActiveField(null);
      toast.info(`'${activeField}' 은 대화로 채워졌어요`, {
        description: "작성 중이던 입력은 반영하지 않았습니다. 필요하면 다시 눌러 고치세요.",
      });
    }
    // activeField 는 의도적으로 deps 에서 제외 — 넣으면 에디터를 열 때마다
    // 이 effect 가 재실행돼 같은 rev 를 다시 처리하려 든다(rev 가드로 막히지만
    // 토스트 타이밍이 어긋난다).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, reportId, markJustFilled]);

  const fields = useMemo(() => (body ? extractFields(body) : []), [body]);
  const filledCount = fields.filter((f) => filled[f]).length;
  const remainingCount = fields.length - filledCount;
  // 서식 뼈대(from-form) 판정 — build_skeleton 이 만드는 시그니처 헤더.
  // 뼈대면 마크다운 대신 항목 행 뷰로 그린다("서식처럼 안 보임" 지적).
  const isSkeleton = !!body && body.includes("## 기입 항목");
  // 추출 저품질(2026-08-27) — 복잡한 별표(여러 표·작성방법류)는 셀 파싱이
  // "구분" 하나만 건지기도 한다(실사용 사례: 국제표준화기술문서 작성방법).
  // 조용히 빈 서식을 내밀지 않고, 한계를 말하고 신고를 유도한다.
  const lowExtraction = isSkeleton && fields.length > 0 && fields.length < 3;

  const openEditor = useCallback(
    (field: string) => {
      setActiveField(field);
      setEditorText(filled[field] ?? "");
    },
    [filled],
  );

  const applyFillResult = useCallback(
    (res: { filled: Record<string, string> }, opts?: { silentEmpty?: boolean }) => {
      const names = Object.keys(res.filled);
      if (names.length) {
        setFilled((prev) => ({ ...prev, ...res.filled }));
        markJustFilled(names);
      } else if (!opts?.silentEmpty) {
        toast.info("근거가 부족해 자동 작성하지 못했어요.", {
          description: "직접 입력하거나, 채팅으로 내용을 알려주시면 채워져요.",
        });
      }
      return names.length;
    },
    [markJustFilled],
  );

  const saveField = useCallback(async () => {
    if (!activeField) return;
    const value = editorText.trim();
    if (!value) return;
    setBusy(activeField);
    try {
      const res = await fillDocumentField(reportId, { field: activeField, value });
      applyFillResult(res, { silentEmpty: true });
      setActiveField(null);
    } catch {
      toast.error("저장에 실패했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(null);
    }
  }, [activeField, editorText, reportId, applyFillResult]);

  const aiFillField = useCallback(async () => {
    if (!activeField) return;
    setBusy(activeField);
    try {
      const res = await fillDocumentField(reportId, {
        field: activeField,
        hint: editorText.trim() || undefined,
      });
      if (applyFillResult(res) > 0) setActiveField(null);
    } catch {
      toast.error("AI 작성에 실패했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(null);
    }
  }, [activeField, editorText, reportId, applyFillResult]);

  // 작성 도우미 — 모달 **안에** 상시 표시(2026-08-27 재재설계).
  // "모달의 모달이 아니라, 옆에 서식 띄워놓고 챗으로 채우는 구조" — 좌측
  // 서식 행이 우측 챗 입력에 실시간으로 반응한다. 메시지는 채팅 스레드 밖
  // · 무저장 · 온프레미스 직행(개인정보 원문 허용의 근거).
  const [chatMsgs, setChatMsgs] = useState<{ role: "ai" | "user"; text: string }[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const chatSeeded = useRef(false);
  // 문제 신고(2026-08-27) — 추출 오류·내용 불일치를 기록해 개선 우선순위 근거로.
  const [reporting, setReporting] = useState(false);
  const [reportReason, setReportReason] = useState("항목 추출 오류");
  const [reportComment, setReportComment] = useState("");
  const submitReport = useCallback(async () => {
    try {
      await reportDocumentIssue({
        report_id: reportId,
        reason: reportReason,
        comment: reportComment.trim() || undefined,
        fields_count: fields.length,
      });
      setReporting(false);
      setReportComment("");
      toast.success("신고가 접수됐어요. 확인 후 개선하겠습니다.");
    } catch {
      toast.error("신고 접수에 실패했어요. 잠시 후 다시 시도해 주세요.");
    }
  }, [reportId, reportReason, reportComment, fields.length]);

  // 본문 로드 후 1회 — 도우미 인사(남은 항목 안내)로 시작.
  useEffect(() => {
    if (!body || chatSeeded.current) return;
    chatSeeded.current = true;
    const rem = extractFields(body).filter((f) => !filled[f]);
    const head = rem.slice(0, 4).join(", ");
    const lowQ = extractFields(body).length < 3;
    setChatMsgs([
      {
        role: "ai",
        text: lowQ
          ? "이 문서에서는 기입 항목을 충분히 추출하지 못했어요. 기준표·작성방법류 문서일 수 있습니다 — 원본을 내려받아 참고하시고, 추출이 잘못됐다면 오른쪽 위 🚩 신고로 알려주세요."
          : rem.length
          ? `안녕하세요, 서류 작성을 도와드릴게요. 다음 정보를 알려주세요: ${head}${
              rem.length > 4 ? ` 외 ${rem.length - 4}개` : ""
            }. 아는 값부터 편하게 적어주시면 왼쪽 서식에 바로 채워져요.`
          : "모든 항목이 작성돼 있어요. 고칠 값이 있으면 알려주세요.",
      },
    ]);
    // filled 는 첫 로드 값만 필요 — 이후 변화에 재인사하지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body]);

  /** 도우미 전송 공통부 — 텍스트/첨부 모두 이 경로.
   *  로컬 AI 가 붐빌 때(장시간 무응답) 지연 안내를 챗에 띄우고, 창을 닫아도
   *  진행·저장됨을 알린다("병목 경고 + 펜딩 UX" — 2026-08-27 요청). */
  const runAssist = useCallback(
    async (userLabel: string, message: string, attachmentText?: string) => {
      if (chatBusy) return;
      setChatMsgs((prev) => [...prev, { role: "user", text: userLabel }]);
      setChatBusy(true);
      // 대기/지연 구분 안내(2026-08-27) — 서버의 기입 레인 동시 요청 수
      // (/documents/assist/load, 단일 인스턴스라 정확)를 3초 간격으로 조회:
      //   in_flight >= 2  → 내 앞/옆에 다른 요청 → "대기 중" (즉시 안내)
      //   in_flight == 1 & 15s 경과 → 내 것 하나뿐인데 느림 → "생성 지연"
      // 상태 버블은 하나를 갱신한다(메시지 누적 방지). 한계: 빌린 장비를
      // 우리 서비스 밖에서 쓰는 부하는 안 보인다 — 그래서 단정 없이 관측
      // 사실만 말한다.
      const startedAt = Date.now();
      let statusIdx: number | null = null;
      const setStatus = (text: string) => {
        setChatMsgs((prev) => {
          const next = [...prev];
          if (statusIdx !== null && next[statusIdx]?.role === "ai") {
            next[statusIdx] = { role: "ai", text };
          } else {
            statusIdx = next.length;
            next.push({ role: "ai", text });
          }
          return next;
        });
      };
      const loadPoll = window.setInterval(() => {
        void (async () => {
          const elapsed = Date.now() - startedAt;
          let inFlight = 1;
          try {
            inFlight = (await getAssistLoad()).in_flight;
          } catch {
            /* 조회 실패 = 시간 기준만 사용 */
          }
          if (inFlight >= 2) {
            setStatus(
              "앞에 다른 작성 요청이 처리되고 있어요 — 순서가 되면 바로 이어집니다. 창을 닫아도 값은 저장되며, '작성 중인 서류'에서 언제든 이어서 작성할 수 있어요.",
            );
          } else if (elapsed >= 15000) {
            setStatus(
              "응답 생성이 평소보다 오래 걸리고 있어요(첨부가 길거나 항목이 많으면 그럴 수 있어요). 창을 닫아도 진행되며, 값은 저장됩니다.",
            );
          }
        })();
      }, 3000);
      try {
        const history = chatMsgs
          .slice(-6)
          .map((m) => (m.role === "user" ? "사용자: " : "도우미: ") + m.text)
          .join("\n");
        const res = await chatFillDocument(reportId, {
          message,
          history,
          attachment_text: attachmentText,
        });
        window.clearInterval(loadPoll);
        applyFillResult({ filled: res.filled }, { silentEmpty: true });
        setChatMsgs((prev) => [...prev, { role: "ai", text: res.reply }]);
      } catch (e) {
        window.clearInterval(loadPoll);
        const status = (e as { status?: number }).status;
        setChatMsgs((prev) => [
          ...prev,
          {
            role: "ai",
            text:
              status === 503
                ? "죄송해요, 지금은 작성 도우미를 사용할 수 없어요. 문서의 항목을 눌러 직접 입력해 주세요."
                : "응답을 받지 못했어요. 잠시 후 다시 보내주세요 — 지금까지 입력한 값은 저장되어 있습니다.",
          },
        ]);
      } finally {
        setChatBusy(false);
      }
    },
    [chatBusy, chatMsgs, reportId, applyFillResult],
  );

  const sendAssist = useCallback(async () => {
    const msg = chatInput.trim();
    if (!msg) return;
    setChatInput("");
    await runAssist(msg, msg);
  }, [chatInput, runAssist]);

  /** 📎 문서 첨부 — 사업자등록증·기존 신청서 등에서 값을 추출해 채운다.
   *  추출 텍스트는 이 온프레미스 전용 창구로만 간다(독립 레인 정책 유지). */
  const [attachBusy, setAttachBusy] = useState(false);
  const attachInputRef = useRef<HTMLInputElement | null>(null);
  const onAttachFile = useCallback(
    async (file: File) => {
      setAttachBusy(true);
      try {
        const ext = await extractFile(file);
        await runAssist(
          `📎 ${ext.name} — 이 문서에서 서류 항목 값을 추출해줘`,
          "첨부한 문서에서 서류 항목에 해당하는 값을 추출해 채워줘.",
          ext.text,
        );
      } catch (e) {
        toast.error("파일에서 텍스트를 추출하지 못했어요.", {
          description: (e as Error).message || "다른 형식으로 시도해 주세요.",
        });
      } finally {
        setAttachBusy(false);
      }
    },
    [runAssist],
  );

  // 새 메시지 시 스크롤 하단 고정
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ block: "end" });
  }, [chatMsgs, chatBusy]);

  /** 행의 ✨ — 모달 없이 그 항목만 대화 근거로 작성(2026-08-27). */
  const aiFillDirect = useCallback(
    async (field: string) => {
      setBusy(field);
      try {
        const res = await fillDocumentField(reportId, { field });
        if (applyFillResult(res, { silentEmpty: true }) === 0) {
          toast.info(`'${field}' 은 아직 근거가 없어요`, {
            description: "작성 도우미에게 알려주거나 항목을 눌러 직접 입력해 주세요.",
          });
        }
      } catch {
        toast.error("AI 작성에 실패했어요. 잠시 후 다시 시도해 주세요.");
      } finally {
        setBusy(null);
      }
    },
    [reportId, applyFillResult],
  );

  const aiFillAll = useCallback(async () => {
    setBusy("*");
    // "아무것도 반응 없는데" — 버튼 아이콘 스핀만으론 안 보인다. 진행을
    // 토스트로 띄우고, 같은 id 로 결과 토스트가 교체된다.
    const t = toast.loading("대화 내용을 근거로 항목을 작성하고 있어요…");
    try {
      const res = await fillDocumentField(reportId, { field: "*" });
      const n = applyFillResult(res, { silentEmpty: true });
      if (n > 0) {
        toast.success(`${n}개 항목을 자동 작성했어요.`, {
          id: t,
          description: res.remaining.length
            ? `${res.remaining.length}개는 근거가 부족해요 — 채팅으로 알려주시거나 직접 입력해 주세요.`
            : "모든 항목이 채워졌어요. 내려받기 전 내용을 검토해 주세요.",
        });
      } else {
        toast.info("자동 작성할 수 있는 항목이 없었어요.", {
          id: t,
          description: "오른쪽 도우미 대화에 알려주시면 바로 채워져요.",
        });
      }
    } catch {
      toast.error("일괄 작성에 실패했어요. 잠시 후 다시 시도해 주세요.", { id: t });
    } finally {
      setBusy(null);
    }
  }, [reportId, applyFillResult]);

  const downloadForm = useCallback(async () => {
    setBusy("form");
    try {
      const ext = await downloadOriginalForm(reportId);
      // 무엇을 받았는지 말해 준다 — 파일만 떨어지면 부분 작성본인지 알 수 없다.
      // 확장자는 원본을 따른다(.hwp 또는 .hwpx) — 하드코딩하면 틀린 형식을 안내한다.
      toast.success(`서식을 내보냈어요 (.${ext})`, {
        description: remainingCount > 0
          ? `미기입 ${remainingCount}개는 [확인 필요] 표시로 남아 있어요. 제출 전 채워 주세요.`
          : "모든 항목이 채워진 제출본이에요. 내용을 검토한 뒤 제출하세요.",
      });
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 404) {
        // 기관 자체 서식(관보 원본 없음) — Word 로 자동 폴백(2026-08-28).
        // "화면 참고" 안내만 하던 것은 8/23 피드백("복붙 불편, 파일로 달라")의
        // 퇴행이었다 — 기관 서식엔 Word 가 유일한 파일 출구다.
        try {
          await downloadReport(
            { id: reportId, kind: "doc", title: title ?? "서류_초안" } as Report,
            "docx",
          );
          toast.info("이 서식은 관보 원본이 없어 Word 파일로 내보냈어요.", {
            description: remainingCount > 0
              ? `기관 자체 서식입니다. 미기입 ${remainingCount}개는 [확인 필요] 표시로 남아 있어요.`
              : "기관 자체 서식입니다. 내용을 검토한 뒤 기관 양식에 옮겨 제출하세요.",
          });
        } catch {
          toast.error("내보내기에 실패했어요. 잠시 후 다시 시도해 주세요.");
        }
      } else if (status === 503) {
        toast.error("서식 원본 기능이 아직 준비되지 않았어요.");
      } else {
        toast.error("서식 원본을 만들지 못했어요. 잠시 후 다시 시도해 주세요.");
      }
    } finally {
      setBusy(null);
    }
  }, [reportId, remainingCount]);

  // ※ Word 내보내기 제거(2026-08-27 승인) — 마크다운 변환본이라 원본
  //   서식을 보장할 수 없다. 산출물은 원본 patch(.hwp) 한 가지.

  /* ── 마커 → 칩 렌더 ── */
  const renderText = useCallback(
    (text: string): ReactNode => {
      if (!text.includes("[확인 필요:")) return text;
      const nodes: ReactNode[] = [];
      let last = 0;
      let i = 0;
      for (const m of text.matchAll(UNFILLED_RE)) {
        const idx = m.index ?? 0;
        if (idx > last) nodes.push(<span key={`t${i++}`}>{text.slice(last, idx)}</span>);
        const field = (m[1] ?? "").trim();
        const value = filled[field];
        nodes.push(
          value ? (
            <FilledValue
              key={`f${i++}`}
              field={field}
              value={value}
              highlighted={justFilled.has(field)}
              onClick={() => openEditor(field)}
            />
          ) : (
            <UnfilledChip key={`u${i++}`} field={field} onClick={() => openEditor(field)} />
          ),
        );
        last = idx + m[0].length;
      }
      if (last < text.length) nodes.push(<span key={`t${i++}`}>{text.slice(last)}</span>);
      return nodes;
    },
    [filled, justFilled, openEditor],
  );

  const wrap = useCallback(
    (children: ReactNode): ReactNode => {
      if (typeof children === "string") return renderText(children);
      if (Array.isArray(children)) {
        return children.map((c, i) =>
          typeof c === "string" ? <span key={i}>{renderText(c)}</span> : c,
        );
      }
      return children;
    },
    [renderText],
  );

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-body-sm text-md-on-surface-variant">
        <span className="inline-block size-4 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin" aria-hidden />
        문서 불러오는 중…
      </div>
    );
  }
  if (error || body === null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-body-sm text-md-error">
        {error ?? "문서를 불러오지 못했어요."}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-md-surface-container-lowest">
      {/* ── 헤더 — 제목·진행률 ── */}
      <div className="shrink-0 border-b border-md-outline-variant px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold text-md-on-surface">
              {title ?? "서류 초안"}
            </p>
            <p className="text-[11px] text-md-on-surface-variant">
              {fields.length > 0
                ? remainingCount > 0
                  ? `${filledCount}/${fields.length} 항목 작성됨`
                  : "모든 항목 작성 완료 · 내려받기 전 검토해 주세요"
                : "확인 필요 항목 없음"}
            </p>
          </div>
          {remainingCount > 0 ? (
            <button
              type="button"
              onClick={() => void aiFillAll()}
              disabled={busy !== null}
              title="지금까지의 대화 내용을 근거로 남은 항목을 채워봐요"
              className="inline-flex h-7 shrink-0 items-center gap-1 rounded-button border border-md-outline-variant bg-md-surface px-2.5 text-[12px] font-medium text-md-on-surface transition-colors hover:bg-md-surface-container-low disabled:opacity-50"
            >
              {busy === "*" ? (
                <span className="inline-block size-3 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin" aria-hidden />
              ) : (
                <span aria-hidden>✨</span>
              )}
              {busy === "*" ? "작성 중…" : "전체 자동 작성"}
            </button>
          ) : null}
          {!fullScreen ? (
            <a
              href={`/documents/${encodeURIComponent(reportId)}`}
              target="_blank"
              rel="noopener noreferrer"
              title="전체화면으로 열기"
              aria-label="전체화면으로 열기"
              className="inline-flex size-7 items-center justify-center rounded text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden>
                open_in_new
              </span>
            </a>
          ) : null}
          <button
            type="button"
            onClick={() => setReporting(true)}
            aria-label="문제 신고"
            title="이 문서의 문제 신고 (항목 추출 오류·내용 불일치 등)"
            className="inline-flex size-7 items-center justify-center rounded text-md-on-surface-variant transition-colors hover:bg-md-error-container hover:text-md-on-error-container"
          >
            <span className="material-symbols-outlined text-[17px]" aria-hidden>
              flag
            </span>
          </button>
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              title="닫기"
              className="inline-flex size-7 items-center justify-center rounded text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
            >
              <span className="material-symbols-outlined text-[18px]" aria-hidden>
                close
              </span>
            </button>
          ) : null}
        </div>
        {fields.length > 0 ? (
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-md-outline-variant" aria-hidden>
            <div
              className="h-full rounded-full bg-md-primary transition-[width] duration-700 ease-out"
              style={{ width: `${Math.round((filledCount / fields.length) * 100)}%` }}
            />
          </div>
        ) : null}
      </div>

      {/* ── 본문 2열: 좌 서식 / 우 도우미 챗 (나란히 — 중첩 모달 아님) ── */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {/* 좌: 서식 */}
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {isSkeleton ? (
              <div className="mx-auto max-w-[560px]">
                {lowExtraction ? (
                  <div className="mb-3 flex items-start gap-2 rounded-card border border-md-tertiary/40 bg-md-tertiary/10 px-3 py-2.5 text-[12px] leading-relaxed text-md-on-surface">
                    <span className="material-symbols-outlined mt-0.5 text-[16px] text-md-tertiary" aria-hidden>
                      info
                    </span>
                    <span>
                      항목을 충분히 추출하지 못했어요 — 이 문서는 기준표·작성방법류일 수
                      있습니다. 원본을 참고하시고, 추출이 잘못됐다면 오른쪽 위 🚩로
                      신고해 주세요.
                    </span>
                  </div>
                ) : null}
                <div className="overflow-hidden rounded-card border border-md-outline-variant bg-md-surface">
                  {fields.map((f, i) => {
                    const v = filled[f];
                    const editing = activeField === f;
                    return (
                      <div
                        key={f}
                        className={
                          "flex min-h-[42px] items-center gap-2 px-3 py-1.5 " +
                          (i > 0 ? "border-t border-md-outline-variant/70 " : "") +
                          (justFilled.has(f)
                            ? "bg-md-primary-container/40"
                            : editing
                              ? "bg-md-surface-container-low"
                              : "")
                        }
                      >
                        <span className="w-[38%] min-w-0 shrink-0 text-[12px] font-medium leading-snug text-md-on-surface-variant">
                          {f}
                        </span>
                        {editing ? (
                          <>
                            {/* 직접 입력 — 행 안에서 바로(모달 없음). Enter 저장/Esc 취소 */}
                            <input
                              value={editorText}
                              onChange={(e) => setEditorText(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && editorText.trim()) {
                                  e.preventDefault();
                                  void saveField();
                                } else if (e.key === "Escape") {
                                  setActiveField(null);
                                }
                              }}
                              autoFocus
                              placeholder="값 입력 후 Enter"
                              className="h-8 min-w-0 flex-1 rounded-input border border-md-primary bg-md-surface px-2 text-[12.5px] text-md-on-surface focus:outline-none"
                            />
                            <button
                              type="button"
                              onClick={() => void saveField()}
                              disabled={busy !== null || !editorText.trim()}
                              className="inline-flex h-8 shrink-0 items-center rounded-button bg-md-primary px-2.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
                            >
                              저장
                            </button>
                            <button
                              type="button"
                              onClick={() => setActiveField(null)}
                              aria-label="입력 취소"
                              className="inline-flex size-8 shrink-0 items-center justify-center rounded text-md-on-surface-variant hover:bg-md-surface-container"
                            >
                              <span className="material-symbols-outlined text-[16px]" aria-hidden>
                                close
                              </span>
                            </button>
                          </>
                        ) : v ? (
                          <button
                            type="button"
                            onClick={() => openEditor(f)}
                            title="클릭해 수정"
                            className="min-w-0 flex-1 truncate rounded px-1 py-0.5 text-left text-[12.5px] font-medium text-md-on-surface underline decoration-md-primary/40 decoration-dotted underline-offset-2 transition-colors hover:bg-md-primary-container/50"
                          >
                            {v}
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => openEditor(f)}
                            className="flex-1 rounded border border-dashed border-md-outline px-2 py-1 text-left text-[12px] text-md-on-surface-variant/70 transition-colors hover:border-md-primary hover:text-md-on-surface"
                          >
                            입력하기
                          </button>
                        )}
                        {!editing ? (
                          <button
                            type="button"
                            onClick={() => void aiFillDirect(f)}
                            disabled={busy !== null}
                            title="대화 내용을 근거로 이 항목을 작성"
                            className="inline-flex size-7 shrink-0 items-center justify-center rounded text-[13px] transition-colors hover:bg-md-surface-container disabled:opacity-40"
                          >
                            {busy === f ? (
                              <span className="inline-block size-3 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin" aria-hidden />
                            ) : (
                              <span aria-hidden>✨</span>
                            )}
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                <p className="mt-3 text-center text-[11.5px] leading-relaxed text-md-on-surface-variant">
                  오른쪽 도우미에게 말하면 자동으로 채워져요 · 값을 누르면 수정
                </p>
              </div>
            ) : (
              <div
                className={
                  (fullScreen
                    ? "text-body-base [&>p]:my-4 "
                    : "text-[12.5px] leading-[1.7] [&>p]:my-3 ") +
                  "mx-auto max-w-[760px] text-md-on-surface [&_th]:px-2 [&_th]:py-1.5 [&_td]:px-2 [&_td]:py-1.5 [&_th]:text-left [&_th]:font-semibold [&_td]:align-top [&_strong]:font-semibold"
                }
                style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
              >
                <ReactMarkdown
                  remarkPlugins={[[remarkGfm, { singleTilde: false }]]}
                  components={{
                    p: ({ children }) => <p className="leading-[1.75]">{wrap(children)}</p>,
                    li: ({ children }) => <li className="leading-[1.7]">{wrap(children)}</li>,
                    td: ({ children }) => <td className="leading-[1.6]">{wrap(children)}</td>,
                    th: ({ children }) => <th>{wrap(children)}</th>,
                    h1: ({ children }) => (
                      <h1 className="mt-6 mb-3 text-[17px] font-bold leading-tight first:mt-0">{wrap(children)}</h1>
                    ),
                    h2: ({ children }) => (
                      <h2 className="mt-6 mb-2.5 text-[15px] font-bold leading-tight first:mt-0">{wrap(children)}</h2>
                    ),
                    h3: ({ children }) => (
                      <h3 className="mt-5 mb-2 text-[13.5px] font-semibold leading-snug first:mt-0">{wrap(children)}</h3>
                    ),
                    table: ({ children }) => (
                      <div className="my-3 max-w-full overflow-x-auto rounded border border-md-outline-variant">
                        <table className="min-w-full text-body-sm">{children}</table>
                      </div>
                    ),
                    thead: ({ children }) => (
                      <thead className="bg-md-surface-container-low">{children}</thead>
                    ),
                    ul: ({ children }) => (
                      <ul className="my-3 list-disc space-y-1.5 pl-5 marker:text-md-on-surface-variant">{children}</ul>
                    ),
                    ol: ({ children }) => (
                      <ol className="my-3 list-decimal space-y-1.5 pl-5 marker:text-md-on-surface-variant">{children}</ol>
                    ),
                    blockquote: ({ children }) => (
                      <blockquote className="my-4 border-l-[3px] border-md-outline pl-3 text-md-on-surface-variant">{children}</blockquote>
                    ),
                    hr: () => <hr className="my-5 border-md-outline-variant" />,
                  }}
                >
                  {body}
                </ReactMarkdown>
                {/* 문장형 초안(writer)의 인라인 편집 바 — 칩 클릭 시 */}
                {activeField ? (
                  <div className="sticky bottom-0 mt-3 rounded-card border border-md-outline-variant bg-md-surface-container-low p-2.5">
                    <p className="mb-1.5 text-[11.5px] font-semibold text-md-on-surface">{activeField}</p>
                    <div className="flex items-center gap-1.5">
                      <input
                        value={editorText}
                        onChange={(e) => setEditorText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && editorText.trim()) {
                            e.preventDefault();
                            void saveField();
                          } else if (e.key === "Escape") setActiveField(null);
                        }}
                        autoFocus
                        placeholder="값을 직접 입력 (Enter 저장)"
                        className="h-8 min-w-0 flex-1 rounded-input border border-md-primary bg-md-surface px-2 text-[12.5px] focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => void saveField()}
                        disabled={busy !== null || !editorText.trim()}
                        className="h-8 rounded-button bg-md-primary px-2.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
                      >
                        저장
                      </button>
                      <button
                        type="button"
                        onClick={() => void aiFillField()}
                        disabled={busy !== null}
                        className="h-8 rounded-button border border-md-outline-variant bg-md-surface px-2 text-[12px]"
                      >
                        ✨
                      </button>
                      <button
                        type="button"
                        onClick={() => setActiveField(null)}
                        aria-label="닫기"
                        className="inline-flex size-8 items-center justify-center rounded text-md-on-surface-variant hover:bg-md-surface-container"
                      >
                        <span className="material-symbols-outlined text-[16px]" aria-hidden>close</span>
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            )}
          </div>

          {/* 내보내기 — 좌측 하단 고정. 부분 작성도 가능함을 명시. */}
          <div className="shrink-0 border-t border-md-outline-variant bg-md-surface-container-lowest px-4 py-2.5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
              <p className="min-w-0 flex-1 text-[11px] leading-snug text-md-on-surface-variant">
                {remainingCount > 0
                  ? `지금 내보내도 됩니다 — 미기입 ${remainingCount}개는 [확인 필요] 표시로 남아요.`
                  : "모든 항목이 채워졌어요. 제출 전 검토해 주세요."}
              </p>
              <button
                type="button"
                onClick={() => void downloadForm()}
                disabled={busy !== null}
                title="관보에 실린 원본 서식 파일에 작성 내용을 채워 내려받아요"
                className="inline-flex h-8 items-center gap-1.5 rounded-button bg-md-primary px-3 text-[12px] font-semibold text-md-on-primary transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                <span
                  className={
                    "material-symbols-outlined text-[15px]" +
                    (busy === "form" ? " animate-md-spin" : "")
                  }
                  aria-hidden
                >
                  {busy === "form" ? "progress_activity" : "draft"}
                </span>
                서식 그대로 내보내기
              </button>

            </div>
          </div>
        </section>

        {/* 우: 작성 도우미 챗 — 상시 표시(같은 모달 안, 나란히) */}
        <aside className="flex h-[42%] min-h-[200px] shrink-0 flex-col border-t border-md-outline-variant md:h-auto md:w-[320px] md:border-l md:border-t-0">
          <div className="shrink-0 border-b border-md-outline-variant px-3.5 py-2.5">
            <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-md-on-surface">
              <span className="material-symbols-outlined text-[16px] text-md-primary" aria-hidden>
                support_agent
              </span>
              작성 도우미
            </p>
            <p className="text-[10.5px] text-md-on-surface-variant">
              이 대화는 저장되지 않아요
            </p>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2.5">
            {chatMsgs.map((m, i) =>
              m.role === "ai" ? (
                <div key={i} className="mb-2 flex items-start gap-1.5">
                  <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-md-primary-container text-[11px]" aria-hidden>
                    🖊️
                  </span>
                  <p className="max-w-[88%] rounded-[10px_10px_10px_3px] bg-md-surface-container-low px-2.5 py-1.5 text-[12px] leading-relaxed">
                    {m.text}
                  </p>
                </div>
              ) : (
                <div key={i} className="mb-2 flex justify-end">
                  <p className="max-w-[88%] rounded-[10px_10px_3px_10px] bg-md-primary-container/60 px-2.5 py-1.5 text-[12px] leading-relaxed">
                    {m.text}
                  </p>
                </div>
              ),
            )}
            {chatBusy ? (
              <div className="mb-2 flex items-start gap-1.5">
                <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-md-primary-container text-[11px]" aria-hidden>
                  🖊️
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-[10px_10px_10px_3px] bg-md-surface-container-low px-2.5 py-2">
                  <span className="inline-block size-2.5 rounded-full border-2 border-md-outline-variant border-t-md-primary animate-md-spin" aria-hidden />
                  <span className="text-[11px] text-md-on-surface-variant">확인하는 중…</span>
                </span>
              </div>
            ) : null}
            <div ref={chatEndRef} />
          </div>
          <div className="shrink-0 border-t border-md-outline-variant px-3 py-2.5">
            <div className="flex items-end gap-1.5">
              <input
                ref={attachInputRef}
                type="file"
                accept=".pdf,.docx,.hwpx,.txt,.md,.csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) void onAttachFile(f);
                }}
              />
              <button
                type="button"
                onClick={() => attachInputRef.current?.click()}
                disabled={chatBusy || attachBusy}
                title="문서를 첨부하면 값이 자동으로 추출돼요 (PDF·DOCX·HWPX 등)"
                aria-label="문서 첨부"
                className="inline-flex size-8 shrink-0 items-center justify-center rounded-button border border-md-outline-variant bg-md-surface text-md-on-surface-variant transition-colors hover:bg-md-surface-container disabled:opacity-40"
              >
                <span
                  className={
                    "material-symbols-outlined text-[16px]" +
                    (attachBusy ? " animate-md-spin" : "")
                  }
                  aria-hidden
                >
                  {attachBusy ? "progress_activity" : "attach_file"}
                </span>
              </button>
              <textarea
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendAssist();
                  }
                }}
                rows={2}
                placeholder="예: 대표자는 홍길동입니다"
                className="min-w-0 flex-1 resize-none rounded-input border border-md-outline-variant bg-md-surface px-2.5 py-1.5 text-[12px] text-md-on-surface placeholder:text-md-on-surface-variant/60 focus:border-md-primary focus:outline-none"
              />
              <button
                type="button"
                onClick={() => void sendAssist()}
                disabled={chatBusy || !chatInput.trim()}
                aria-label="보내기"
                className="inline-flex size-8 shrink-0 items-center justify-center rounded-button bg-md-primary text-md-on-primary transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <span className="material-symbols-outlined text-[16px]" aria-hidden>
                  send
                </span>
              </button>
            </div>
          </div>
        </aside>
      </div>

      {/* 문제 신고 다이얼로그 */}
      {reporting ? (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/30 p-6">
          <div className="w-full max-w-[380px] rounded-card border border-md-outline-variant bg-md-surface p-5 shadow-xl">
            <p className="text-[14px] font-semibold text-md-on-surface">문제 신고</p>
            <p className="mt-1 text-[11.5px] text-md-on-surface-variant">
              이 문서의 어떤 점이 문제인가요? 기록을 남겨 개선에 사용합니다.
            </p>
            <div className="mt-3 flex flex-col gap-1.5">
              {["항목 추출 오류", "서식이 아님(기준표·작성방법)", "내용 불일치", "기타"].map((r) => (
                <label key={r} className="flex cursor-pointer items-center gap-2 text-[12.5px] text-md-on-surface">
                  <input
                    type="radio"
                    name="doc-report-reason"
                    checked={reportReason === r}
                    onChange={() => setReportReason(r)}
                    className="accent-md-primary"
                  />
                  {r}
                </label>
              ))}
            </div>
            <textarea
              value={reportComment}
              onChange={(e) => setReportComment(e.target.value)}
              rows={2}
              placeholder="상세 내용 (선택)"
              className="mt-3 w-full resize-none rounded-input border border-md-outline-variant bg-md-surface-container-lowest px-2.5 py-2 text-[12.5px] focus:border-md-primary focus:outline-none"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setReporting(false)}
                className="h-8 rounded-button px-3 text-[12.5px] text-md-on-surface-variant hover:bg-md-surface-container"
              >
                취소
              </button>
              <button
                type="button"
                onClick={() => void submitReport()}
                className="h-8 rounded-button bg-md-primary px-3.5 text-[12.5px] font-semibold text-md-on-primary hover:opacity-90"
              >
                신고
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ─────────────────── 칩 ─────────────────── */

function UnfilledChip({ field, onClick }: { field: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`'${field}' 입력하기`}
      aria-label={`미기입 항목 ${field} — 클릭해 입력`}
      className="mx-[1px] inline-flex items-center gap-[3px] rounded-pill border border-dashed border-md-tertiary/60 bg-md-tertiary-fixed/40 px-1.5 py-[1px] align-baseline text-[11px] font-semibold text-md-tertiary transition-colors hover:bg-md-tertiary-fixed"
    >
      <span className="material-symbols-outlined text-[12px] leading-none" aria-hidden>
        edit
      </span>
      {field}
    </button>
  );
}

function FilledValue({
  field,
  value,
  highlighted,
  onClick,
}: {
  field: string;
  value: string;
  highlighted: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`${field}: ${value} (클릭해 수정)`}
      aria-label={`${field} 작성됨: ${value}`}
      className={
        "mx-[1px] inline rounded-[3px] px-0.5 align-baseline font-semibold text-md-primary underline decoration-md-primary/40 decoration-dotted underline-offset-2 transition-colors duration-700 ease-out hover:bg-md-primary-container/50 " +
        (highlighted ? "bg-md-primary-container/80" : "bg-transparent")
      }
    >
      {value}
    </button>
  );
}
