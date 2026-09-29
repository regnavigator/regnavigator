"use client";

/**
 * DocumentsDialog — 작성한 서식 관리 모달 (2026-09-18).
 *
 * 가로로 넓은 표: 제목(별명) · 원 대화 · 작성일 · 작성 상태(미작성/작성 중/완료) · 보기 · 다운로드 ·
 * 보관 · 삭제. 탭은 [전체] / [보관함]. 같은 서식을 여러 건 쓸 때는 별명과 원 대화 제목으로 구분한다.
 *
 * 수명 규칙(백엔드 `form_docs`): 서식은 만든 대화에 딸려 있어 대화를 지우면 함께 지워진다.
 * **보관**한 서식만 독립 목록으로 남는다 — 그래서 보관함의 서식은 원 대화가 없을 수 있고,
 * 그때 [대화] 버튼은 꺼진다. 진입점은 사이드바 "작성한 서식" 섹션의 [관리].
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DOCUMENT_DELETED_EVENT,
  DOCUMENTS_CHANGED_EVENT,
  downloadOriginalForm,
  listDocuments,
  setDocumentAlias,
  setDocumentKept,
  type DocumentListItem,
} from "@/lib/client/documents";
import { deleteReport, downloadReport } from "@/lib/client/reports";
import { useRightPanel } from "@/lib/store/rightPanel";
import type { Report } from "@/lib/store/types";

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}.${m}.${day}`;
}

const STATUS: Record<DocumentListItem["status"], { label: string; cls: string }> = {
  empty: { label: "미작성", cls: "bg-md-surface-container-high text-md-on-surface-variant" },
  partial: { label: "작성 중", cls: "bg-md-secondary-fixed text-md-on-secondary-fixed-variant" },
  done: { label: "완료", cls: "bg-md-primary/15 text-md-primary" },
};

type Tab = "all" | "kept";

function IconBtn({
  icon,
  label,
  onClick,
  disabled,
  spinning,
  active,
  danger,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  spinning?: boolean;
  active?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-label={label}
      title={label}
      className={
        "inline-flex size-8 items-center justify-center rounded transition-colors disabled:cursor-not-allowed disabled:opacity-35 " +
        (danger
          ? "text-md-on-surface-variant hover:bg-md-error-container hover:text-md-on-error-container"
          : active
            ? "text-md-primary hover:bg-md-primary/10"
            : "text-md-on-surface-variant hover:bg-md-surface-container-high hover:text-md-on-surface")
      }
    >
      <span
        className={"material-symbols-outlined text-[19px]" + (spinning ? " animate-md-spin" : "")}
        style={active ? { fontVariationSettings: "'FILL' 1" } : undefined}
        aria-hidden
      >
        {spinning ? "progress_activity" : icon}
      </span>
    </button>
  );
}

export function DocumentsDialog({
  open,
  onOpenChange,
  previewItems,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** dev 미리보기(/auth/dialog-preview/documents) 전용 — 주면 서버를 부르지 않고
   *  이 목록을 보여 주며, 내려받기·보관·삭제는 화면 반응만 흉내 낸다. */
  previewItems?: DocumentListItem[];
}) {
  const preview = previewItems !== undefined;
  const router = useRouter();
  const { setDocumentId } = useRightPanel();
  const [docs, setDocs] = useState<DocumentListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null); // `${action}:${id}`
  const [tab, setTab] = useState<Tab>("all");
  const [dateDesc, setDateDesc] = useState(true); // 작성일 정렬 — 기본 최신순
  const [editingId, setEditingId] = useState<string | null>(null);
  const [aliasDraft, setAliasDraft] = useState("");

  const reload = useCallback(async () => {
    if (previewItems !== undefined) {
      setDocs(previewItems);
      return;
    }
    setLoading(true);
    try {
      setDocs(await listDocuments());
    } catch {
      toast.error("서식 목록을 불러오지 못했어요.");
    } finally {
      setLoading(false);
    }
  }, [previewItems]);

  useEffect(() => {
    if (open) void reload();
  }, [open, reload]);

  const shown = useMemo(() => {
    const list = tab === "kept" ? docs.filter((d) => d.kept) : [...docs];
    list.sort((a, b) => {
      const c = (a.created_at ?? "").localeCompare(b.created_at ?? "");
      return dateDesc ? -c : c;
    });
    return list;
  }, [docs, tab, dateDesc]);
  const keptCount = useMemo(() => docs.filter((d) => d.kept).length, [docs]);

  const openDoc = (d: DocumentListItem) => {
    onOpenChange(false);
    setDocumentId(d.id);
  };

  const goThread = (d: DocumentListItem) => {
    onOpenChange(false);
    router.replace(`/new?threadId=${encodeURIComponent(d.thread_id)}`);
  };

  const download = async (d: DocumentListItem) => {
    setBusy(`dl:${d.id}`);
    if (preview) {
      window.setTimeout(() => {
        setBusy(null);
        toast.success("서식 파일을 내려받았어요. (미리보기)");
      }, 700);
      return;
    }
    try {
      await downloadOriginalForm(d.id);
      toast.success("서식 파일을 내려받았어요.");
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 404) {
        try {
          await downloadReport(
            { id: d.id, kind: "doc", title: d.title ?? "서류_초안" } as Report,
            "docx",
          );
          toast.info("이 서식은 원문 파일이 없어 Word 파일로 내보냈어요.");
        } catch {
          toast.error("내보내기에 실패했어요. 잠시 후 다시 시도해 주세요.");
        }
      } else if (status === 503) {
        toast.error("서식 원본 기능이 아직 준비되지 않았어요.");
      } else {
        toast.error("서식 파일을 만들지 못했어요. 잠시 후 다시 시도해 주세요.");
      }
    } finally {
      setBusy(null);
    }
  };

  const startAlias = (d: DocumentListItem) => {
    setEditingId(d.id);
    setAliasDraft(d.alias ?? "");
  };

  const saveAlias = async (d: DocumentListItem) => {
    const next = aliasDraft.replace(/\s+/g, " ").trim().slice(0, 60);
    setEditingId(null);
    if (next === (d.alias ?? "")) return;
    try {
      const saved = preview ? next || null : await setDocumentAlias(d.id, next);
      setDocs((prev) => prev.map((x) => (x.id === d.id ? { ...x, alias: saved } : x)));
      if (!preview) window.dispatchEvent(new CustomEvent(DOCUMENTS_CHANGED_EVENT));
    } catch {
      toast.error("별명을 저장하지 못했어요.");
    }
  };

  const toggleKept = async (d: DocumentListItem) => {
    const next = !d.kept;
    setBusy(`kp:${d.id}`);
    try {
      if (!preview) await setDocumentKept(d.id, next);
      setDocs((prev) => prev.map((x) => (x.id === d.id ? { ...x, kept: next } : x)));
      toast.success(
        next ? "보관했어요. 원 대화를 지워도 이 서식은 남습니다." : "보관을 해제했어요. 원 대화를 지우면 함께 삭제됩니다.",
      );
    } catch {
      toast.error("보관 상태를 바꾸지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(null);
    }
  };

  const remove = async (d: DocumentListItem) => {
    if (!window.confirm(`'${d.title ?? "서식"}'을 삭제할까요?\n채운 내용도 함께 지워지며 되돌릴 수 없어요.`)) return;
    setBusy(`rm:${d.id}`);
    try {
      if (!preview) await deleteReport(d.id);
      setDocs((prev) => prev.filter((x) => x.id !== d.id));
      if (!preview) {
        window.dispatchEvent(new CustomEvent(DOCUMENT_DELETED_EVENT, { detail: { id: d.id } }));
        window.dispatchEvent(new CustomEvent(DOCUMENTS_CHANGED_EVENT));
      }
      toast.success("서식을 삭제했어요.");
    } catch {
      toast.error("삭제하지 못했어요. 잠시 후 다시 시도해 주세요.");
    } finally {
      setBusy(null);
    }
  };

  const th = "px-3 py-2 text-left text-[11.5px] font-semibold text-md-on-surface-variant whitespace-nowrap";
  const thC = th.replace("text-left", "text-center");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(1180px,calc(100vw-32px))] max-w-none">
        <DialogHeader>
          <DialogTitle>작성한 서식</DialogTitle>
          <DialogDescription className="text-[12px] leading-relaxed">
            대화를 지우면 그 대화의 서식도 삭제됩니다. 보관한 서식은 남습니다.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-1 flex items-center gap-1.5">
          {([
            ["all", `전체 ${docs.length}`],
            ["kept", `보관함 ${keptCount}`],
          ] as [Tab, string][]).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={
                "rounded-pill px-3 py-1 text-[12.5px] font-medium transition-colors " +
                (tab === id
                  ? "bg-md-primary text-md-on-primary"
                  : "bg-md-surface-container-high text-md-on-surface-variant hover:text-md-on-surface")
              }
            >
              {label}
            </button>
          ))}
        </div>

        {loading && docs.length === 0 ? (
          <p className="py-8 text-center text-[13px] text-md-on-surface-variant">불러오는 중…</p>
        ) : shown.length === 0 ? (
          <div className="py-8 text-center">
            <p className="text-[13px] text-md-on-surface-variant">
              {tab === "kept" ? "보관한 서식이 없어요." : "아직 작성한 서식이 없어요."}
            </p>
            <p className="mt-1 text-[12px] text-md-on-surface-variant opacity-70">
              {tab === "kept"
                ? "전체 탭에서 책갈피 아이콘을 누르면 보관됩니다."
                : "답변 아래 관련 서식 카드에서 [이 서식으로 작성]을 누르면 여기에 쌓입니다."}
            </p>
          </div>
        ) : (
          <div className="mt-1 max-h-[60vh] overflow-auto rounded-card border border-md-outline-variant">
            <table className="w-full min-w-[860px] border-collapse text-[13px]">
              <thead className="sticky top-0 z-10 bg-md-surface-container">
                <tr className="border-b border-md-outline-variant">
                  <th className={th}>제목</th>
                  <th className={th}>원 대화</th>
                  <th className={th} aria-sort={dateDesc ? "descending" : "ascending"}>
                    <button
                      type="button"
                      onClick={() => setDateDesc((v) => !v)}
                      title={dateDesc ? "최신순 — 눌러서 오래된순" : "오래된순 — 눌러서 최신순"}
                      className="inline-flex items-center gap-0.5 hover:text-md-on-surface"
                    >
                      작성일
                      <span className="material-symbols-outlined text-[15px]" aria-hidden>
                        {dateDesc ? "arrow_downward" : "arrow_upward"}
                      </span>
                    </button>
                  </th>
                  <th className={th}>작성 상태</th>
                  <th className={thC}>보기</th>
                  <th className={thC}>다운로드</th>
                  <th className={thC}>보관</th>
                  <th className={thC}>삭제</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((d) => {
                  const st = STATUS[d.status] ?? STATUS.partial;
                  return (
                    <tr
                      key={d.id}
                      className="border-b border-md-outline-variant/60 last:border-b-0 hover:bg-md-surface-container-low"
                    >
                      <td className="px-3 py-2">
                        {editingId === d.id ? (
                          <input
                            autoFocus
                            value={aliasDraft}
                            maxLength={60}
                            placeholder="별명 (비우면 해제)"
                            onChange={(e) => setAliasDraft(e.target.value)}
                            onBlur={() => void saveAlias(d)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") void saveAlias(d);
                              if (e.key === "Escape") setEditingId(null);
                            }}
                            className="w-full rounded border border-md-primary bg-transparent px-2 py-1 text-[13px] text-md-on-surface outline-none"
                          />
                        ) : (
                          <div className="group/title flex items-start gap-1">
                            <button
                              type="button"
                              onClick={() => openDoc(d)}
                              className="min-w-0 flex-1 text-left leading-snug hover:text-md-primary"
                              style={{ wordBreak: "keep-all", overflowWrap: "anywhere" }}
                            >
                              <span className="font-medium text-md-on-surface">{d.alias || d.title || "서식"}</span>
                              {d.alias ? (
                                <span className="mt-0.5 block text-[11.5px] text-md-on-surface-variant">
                                  {d.title ?? "서식"}
                                </span>
                              ) : null}
                            </button>
                            <button
                              type="button"
                              onClick={() => startAlias(d)}
                              aria-label="별명 붙이기"
                              title={d.alias ? "별명 고치기" : "별명 붙이기 — 같은 서식을 구분할 때"}
                              className="inline-flex size-6 shrink-0 items-center justify-center rounded text-md-on-surface-variant opacity-40 transition-opacity hover:bg-md-surface-container-high hover:text-md-on-surface hover:opacity-100 focus:opacity-100 group-hover/title:opacity-100"
                            >
                              <span className="material-symbols-outlined text-[15px]" aria-hidden>
                                edit
                              </span>
                            </button>
                          </div>
                        )}
                      </td>
                      <td className="max-w-[260px] px-3 py-2">
                        {d.thread_alive ? (
                          <button
                            type="button"
                            onClick={() => goThread(d)}
                            title="이 서식을 만든 대화로 가기"
                            className="flex w-full items-center gap-1 text-left text-[12.5px] text-md-on-surface-variant hover:text-md-primary"
                          >
                            <span className="material-symbols-outlined shrink-0 text-[15px]" aria-hidden>
                              forum
                            </span>
                            <span className="truncate">{d.thread_title || "제목 없는 대화"}</span>
                          </button>
                        ) : (
                          <span className="text-[12px] text-md-on-surface-variant opacity-60">삭제된 대화</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 tabular-nums text-md-on-surface-variant">
                        {fmtDate(d.created_at)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <span className="inline-flex items-center gap-2">
                          <span
                            className={
                              "inline-block w-[52px] rounded-pill py-0.5 text-center text-[11.5px] font-medium " + st.cls
                            }
                          >
                            {st.label}
                          </span>
                          <span className="inline-block w-[40px] text-right text-[11.5px] tabular-nums text-md-on-surface-variant">
                            {d.field_count > 0 ? `${d.filled_count}/${d.field_count}` : ""}
                          </span>
                        </span>
                      </td>
                      <td className="px-1 py-1 text-center">
                        <IconBtn icon="open_in_new" label="서식 열기 (이어서 작성)" onClick={() => openDoc(d)} />
                      </td>
                      <td className="px-1 py-1 text-center">
                        <IconBtn
                          icon="download"
                          label="서식 파일 내려받기"
                          disabled={!!busy}
                          spinning={busy === `dl:${d.id}`}
                          onClick={() => void download(d)}
                        />
                      </td>
                      <td className="px-1 py-1 text-center">
                        <IconBtn
                          icon="bookmark"
                          label={d.kept ? "보관 해제 (대화를 지우면 함께 삭제)" : "보관 (대화를 지워도 남김)"}
                          active={d.kept}
                          disabled={!!busy}
                          spinning={busy === `kp:${d.id}`}
                          onClick={() => void toggleKept(d)}
                        />
                      </td>
                      <td className="px-1 py-1 text-center">
                        <IconBtn
                          icon="delete"
                          label="서식 삭제 (복구 불가)"
                          danger
                          disabled={!!busy}
                          spinning={busy === `rm:${d.id}`}
                          onClick={() => void remove(d)}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
