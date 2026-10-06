"use client";

/**
 * CompositionPanel — "기능연계" 패널 (2026-10-05 재설계 2차).
 *
 * 사용자 지침(2026-10-05):
 *  - 우측에 **따로** 선다 — 근거(인용) 패널과 동시에 열려야 한다. 폭은 근거 패널의 절반.
 *  - 위 2/3: 기능 찾기 + 타일을 **1열**로. 아래 1/3: 고른 기능의 입력.
 *  - 대화 중에 기능을 고르면 **대화 내용으로 입력이 먼저 채워져** 있어야 하고(고칠 수
 *    있게), 서식 작성은 파일을 올리라고 하지 말고 **대화에 나온 서식 목록**에서 고르거나
 *    더 찾게 한다.
 *  - 연계는 앞 기능의 결과가 다음 입력이 되므로, 따로 적을 게 없으면 **입력 없이도**
 *    이어져야 한다.
 *
 * 흐름: 타일 클릭 → (대화가 있으면 자동 채움) → [바로 실행] 또는 [연계에 추가].
 * 연계 1단계는 보통 턴, 2단계 이상은 숨은 턴 + 종합 1건(실행기는 PageShell).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { featuresFor, filterFeatures, type Feature } from "@/lib/features/catalog";
import {
  deleteStepFile,
  emptyStep,
  needsFiles,
  stepBlanks,
  stepReady,
  suggestValues,
  uploadStepFile,
  type Composition,
  type CompositionStep,
} from "@/lib/features/composition";
import type { TaskTemplate } from "@/lib/client/taskTemplates";
import type { PresetTask } from "@/lib/features/presetTasks";
import { STAGES, type Stage } from "@/lib/features/catalog";
import { findGaps } from "@/lib/features/gaps";
import type { AppMode } from "@/lib/store/mode";

/** 대화에 나온 서식 인용 — form_find 가 목록으로 보여 준다. */
export type FormCitation = { id: string; title: string; articleKey: string };

/** 연계 종점이 서식이면 PageShell 이 쏜다 — 패널은 서식 기능 초안을 열어 목록을 펼친다. */
export const OPEN_FORM_LIST_EVENT = "regnav:open-form-list";

type Props = {
  threadId: string | null;
  mode: AppMode | null;
  /** 대화에 턴이 있는가 — 있으면 입력을 대화로 채우고, 빈 칸을 막지 않는다. */
  hasTurns: boolean;
  composition: Composition | null;
  running: boolean;
  formCitations: FormCitation[];
  onChange: (c: Composition | null) => void;
  onRun: (mode: "stepwise" | "auto") => void;
  /** 기능 하나를 보이는 턴으로 지금 보낸다. */
  onRunNow: (f: Feature, st: CompositionStep) => void;
  /** 서식 인용 → 작성 모달(PageShell.handleUseAsForm). 미전달 시 목록 비노출 */
  onUseAsForm?: (articleKey: string, title: string) => void;
  onStop: () => void;
  /** 직무(task) 템플릿(2026-10-06) — 저장된 연계. 없으면 섹션 비노출 */
  templates: TaskTemplate[];
  /** 추천 직무(코드 동봉) — "내 직무" 아래 "추천 직무"로 */
  presets: PresetTask[];
  onSaveTemplate: (name: string) => Promise<void>;
  onLoadTemplate: (t: { steps: TaskTemplate["steps"] }) => void;
  onRenameTemplate: (t: TaskTemplate, name: string) => Promise<void>;
  onDeleteTemplate: (t: TaskTemplate) => Promise<void>;
};

const BLANK: Composition = { steps: [], cursor: 0, mode: "stepwise", status: "draft" };


/** 파일을 붙일 수 있는 기능 — 파일이 핵심이거나 기밀 검토일 때만. 서식 작성에 파일을
 *  올리라고 하던 것은 지침으로 폐지(2026-10-05). */
function canAttach(f: Feature): boolean {
  return f.triggers === "attach" || f.triggers === "confidential";
}

type Draft = {
  f: Feature;
  st: CompositionStep;
  /** 목록의 단계를 고치는 중이면 그 index. 없으면 새 단계 */
  idx?: number;
  filling: boolean;
  filled: boolean;
};

export function CompositionPanel({
  threadId,
  mode,
  hasTurns,
  composition,
  running,
  formCitations,
  onChange,
  onRun,
  onRunNow,
  onUseAsForm,
  onStop,
  templates,
  presets,
  onSaveTemplate,
  onLoadTemplate,
  onRenameTemplate,
  onDeleteTemplate,
}: Props) {
  const c = composition ?? BLANK;
  const [q, setQ] = useState("");
  /** "직무로 저장" 인라인 이름 입력 — null 이면 닫힘 */
  const [saveName, setSaveName] = useState<string | null>(null);
  const [savingT, setSavingT] = useState(false);
  /** 이름 변경 중인 템플릿 id */
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [moreForms, setMoreForms] = useState(false);
  const [busyFile, setBusyFile] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const fillSeq = useRef(0);

  // 관찰 목록(watch)은 턴으로 보낼 문장이 없다 — 입력창 전용 버튼으로 연다. 서면(brief)은
  // 2026-10-06 부터 연계의 **종점 단계**로 패널에 선다(바로 실행 = 모달, 연계 = 종합 뒤 모달).
  const all = useMemo(
    () => featuresFor({ mode, hasTurns: true }).filter((f) => f.triggers !== "watch"),
    [mode],
  );
  const byId = useMemo(() => new Map(all.map((f) => [f.id, f])), [all]);
  const shown = useMemo(() => filterFeatures(all, q), [all, q]);
  // 연계 공백(2026-10-06) — 결정적. 제안일 뿐 자동 삽입하지 않는다.
  const gaps = useMemo(
    () => findGaps(c.steps, byId, {
      hasTurns,
      hasFormCitations: formCitations.length > 0,
      hasAttachments: c.steps.some((st) => st.files.length > 0),
    }, all),
    [c.steps, byId, hasTurns, formCitations.length, all],
  );
  const insertStep = (at: number, f: Feature) => {
    if (c.steps.length >= 8) { toast.error("연계는 8단계까지입니다."); return; }
    const steps = c.steps.slice();
    steps.splice(at, 0, emptyStep(f));
    patch({ steps, cursor: c.status === "done" ? 0 : c.cursor,
            status: c.status === "done" ? "draft" : c.status });
  };

  const patch = useCallback(
    (next: Partial<Composition>) => onChange({ ...c, ...next }),
    [c, onChange],
  );
  const patchDraft = (next: Partial<CompositionStep>) =>
    setDraft((d) => (d ? { ...d, st: { ...d.st, ...next } } : d));

  /**
   * 타일 클릭 → 초안. 대화가 있으면 **대화 내용으로 먼저 채운다**(지침). 제안이 늦게
   * 와도 사용자가 그새 친 값은 덮지 않는다.
   */
  const startDraft = useCallback(
    (f: Feature, st?: CompositionStep, idx?: number) => {
      const base = st ?? emptyStep(f);
      const willFill = !st && hasTurns && !!threadId && !!f.form;
      setMoreForms(false);
      setDraft({ f, st: base, idx, filling: willFill, filled: false });
      if (!willFill || !f.form) return;
      const seq = ++fillSeq.current;
      void suggestValues(
        threadId!, f.title,
        f.form.fields.map((fd) => ({ key: fd.key, label: fd.label, placeholder: fd.placeholder })),
      ).then((vals) => {
        if (seq !== fillSeq.current) return;
        setDraft((d) => {
          if (!d || d.f.id !== f.id) return d;
          const merged = { ...vals, ...Object.fromEntries(
            Object.entries(d.st.values).filter(([, v]) => (v ?? "").trim()),
          ) };
          return { ...d, filling: false, filled: Object.keys(vals).length > 0,
                   st: { ...d.st, values: merged } };
        });
      });
    },
    [hasTurns, threadId],
  );

  const closeDraft = () => { fillSeq.current++; setDraft(null); };

  const addDraft = () => {
    if (!draft) return;
    // 서면은 연계의 **마지막**에만(2026-10-06) — 종합이 곧 서면의 재료라 뒤에 단계가 올 수 없다.
    const hasBrief = c.steps.some((st, i) => byId.get(st.fn)?.triggers === "brief" && i !== draft.idx);
    if (draft.f.triggers === "brief" && draft.idx !== undefined && draft.idx !== c.steps.length - 1) {
      toast.error("서면 초안은 연계의 마지막 단계여야 합니다.");
      return;
    }
    if (hasBrief && draft.idx === undefined) {
      toast.error("서면 초안 뒤에는 단계를 더할 수 없습니다 — 서면을 빼거나 그 앞에 넣어 주세요.");
      return;
    }
    if (draft.idx !== undefined) {
      const steps = c.steps.slice();
      steps[draft.idx] = draft.st;
      patch({ steps });
    } else {
      if (c.steps.length >= 8) { toast.error("연계는 8단계까지입니다."); return; }
      // 끝난 연계(status done, cursor=끝)에 단계를 더하면 **새 연계**다 — 종전엔
      // cursor 가 그대로 남아 실행기가 "이미 다 돌았다"고 보고 아무것도 보내지 않았다
      // (2026-10-05 실측: 버튼을 눌러도 턴이 안 나감).
      const fresh = c.status === "done";
      patch({
        steps: fresh ? [draft.st] : [...c.steps, draft.st],
        cursor: fresh ? 0 : c.cursor,
        status: fresh ? "draft" : c.status,
      });
    }
    closeDraft();
  };

  const runDraftNow = () => {
    if (!draft) return;
    onRunNow(draft.f, draft.st);
    closeDraft();
  };

  const removeStep = (i: number) => {
    const steps = c.steps.filter((_, k) => k !== i);
    patch({
      steps,
      cursor: c.status === "done" ? 0 : Math.min(c.cursor, Math.max(0, steps.length - 1)),
      status: c.status === "done" ? "draft" : c.status,
    });
    if (draft?.idx === i) closeDraft();
  };

  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= c.steps.length) return;
    const steps = c.steps.slice();
    [steps[i], steps[j]] = [steps[j]!, steps[i]!];
    patch({ steps });
  };

  const pickFile = () => {
    if (!threadId) { toast.error("대화를 먼저 시작해 주세요."); return; }
    fileRef.current?.click();
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !threadId || !draft) return;
    setBusyFile(true);
    try {
      const f = await uploadStepFile(threadId, file);
      const meta = { id: f.id, name: f.name, chars: f.chars };
      setDraft((d) => (d ? { ...d, st: { ...d.st, files: [...d.st.files, meta] } } : d));
      if (f.truncated) {
        toast.warning(`${f.name} 은 일부만 읽었습니다.`, { description: "문서가 길어 앞부분만 사용합니다." });
      }
    } catch {
      toast.error("파일을 올리지 못했습니다.");
    } finally {
      setBusyFile(false);
    }
  };

  const dropFile = async (fileId: string) => {
    setDraft((d) => (d ? { ...d, st: { ...d.st, files: d.st.files.filter((x) => x.id !== fileId) } } : d));
    if (!threadId) return;
    try { await deleteStepFile(threadId, fileId); } catch { /* best-effort */ }
  };

  // 실행 가능 — 파일은 모든 단계가 갖춰야 하고, 빈 칸은 **대화도 앞 단계도 없는 첫
  // 단계**만 막는다. 그 외 빈 칸은 앞 단계·앞 대화 결과를 가리키는 말로 치환돼 나간다.
  const cursor = Math.min(c.cursor, Math.max(0, c.steps.length - 1));
  const blocked = c.steps.findIndex((st, i) => {
    const f = byId.get(st.fn);
    if (!stepReady(f, st)) return true;
    return i === cursor && cursor === 0 && !hasTurns && !!f && stepBlanks(f, st);
  });
  const canRun = c.steps.length > 0 && blocked < 0 && !!threadId;
  const draftBlank = draft ? stepBlanks(draft.f, draft.st) : false;
  const draftFilesOk = draft ? stepReady(draft.f, draft.st) : false;
  const draftRunnable = !!draft && draftFilesOk && (!draftBlank || hasTurns) && !!threadId;

  // Esc 로 초안 닫기
  useEffect(() => {
    if (!draft) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") closeDraft(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!draft]);

  const tile = (f: Feature) => {
    const active = draft?.f.id === f.id && draft.idx === undefined;
    return (
      <li key={f.id} className="mb-1">
        <button
          type="button"
          data-add-feature={f.id}
          aria-pressed={active}
          onClick={() => startDraft(f)}
          title={f.expects.join("\n")}
          className={
            "flex w-full items-start gap-2 rounded-[8px] border p-2 text-left transition-colors " +
            (active
              ? "border-md-primary bg-md-primary-container/40"
              : "border-md-outline-variant bg-md-surface-container-lowest hover:border-md-primary hover:bg-md-surface-container-low")
          }
        >
          <span className="material-symbols-outlined mt-[1px] text-[16px] text-md-primary" aria-hidden>
            {f.icon ?? "bolt"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[12px] font-semibold leading-snug text-md-on-surface">
              {f.title}
            </span>
            <span className="block truncate text-[10.5px] leading-snug text-md-on-surface-variant">
              {f.subtitle}
            </span>
          </span>
        </button>
      </li>
    );
  };

  useEffect(() => {
    const open = () => { const f = byId.get("form_find"); if (f) startDraft(f); };
    window.addEventListener(OPEN_FORM_LIST_EVENT, open);
    return () => window.removeEventListener(OPEN_FORM_LIST_EVENT, open);
  }, [byId, startDraft]);

  const isFormFind = draft?.f.id === "form_find";
  const showFormList = isFormFind && !!onUseAsForm && formCitations.length > 0;

  return (
    <section data-testid="composition-panel" className="flex h-full min-h-0 flex-col">
      <input ref={fileRef} type="file" accept=".pdf,.docx,.hwpx,.txt"
             onChange={(e) => void onFile(e)} className="hidden" />

      {/* ───────── 위 2/3 — 찾기 + 타일(1열) ───────── */}
      <div className="flex min-h-0 flex-[2] flex-col">
        <div className="px-2.5 pt-2">
          <div className="relative">
            <span className="material-symbols-outlined pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[15px] text-md-on-surface-variant" aria-hidden>
              search
            </span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="기능 찾기"
              data-testid="composition-search"
              className="w-full rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest py-1.5 pl-7 pr-2 text-[12px] outline-none focus:border-md-primary"
            />
          </div>
        </div>
        <ul className="mt-1.5 min-h-0 flex-1 overflow-y-auto px-2.5 pb-2" data-testid="composition-grid">
          {templates.length && !q.trim() ? (
            <li className="mb-2" data-testid="composition-templates">
              <div className="mb-1 flex items-center gap-1 text-[10.5px] font-semibold text-md-on-surface-variant">
                <span className="material-symbols-outlined text-[13px] text-md-primary" aria-hidden>account_tree</span>
                내 직무
              </div>
              <ul>
                {templates.map((t) => (
                  <li key={t.id} className="mb-1">
                    {renaming?.id === t.id ? (
                      <form
                        className="flex items-center gap-1"
                        onSubmit={(e) => {
                          e.preventDefault();
                          const n = renaming.name.trim();
                          if (!n) return;
                          void onRenameTemplate(t, n).finally(() => setRenaming(null));
                        }}
                      >
                        <input autoFocus value={renaming.name}
                               onChange={(e) => setRenaming({ id: t.id, name: e.target.value })}
                               onKeyDown={(e) => { if (e.key === "Escape") setRenaming(null); }}
                               maxLength={80}
                               className="min-w-0 flex-1 rounded-[6px] border border-md-primary bg-md-surface px-2 py-1 text-[12px] outline-none" />
                        <button type="submit" className="text-[11px] font-medium text-md-primary">저장</button>
                      </form>
                    ) : (
                      <div className="group flex items-start gap-1.5 rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest p-2 hover:border-md-primary">
                        <button type="button" data-template={t.id} onClick={() => onLoadTemplate(t)}
                                title={t.steps.map((s) => byId.get(s.fn)?.title ?? s.fn).join(" → ")}
                                className="min-w-0 flex-1 text-left">
                          <span className="block truncate text-[12px] font-semibold leading-snug text-md-on-surface">{t.name}</span>
                          <span className="block truncate text-[10.5px] leading-snug text-md-on-surface-variant">
                            {t.steps.length}단계 · {t.steps.map((s) => byId.get(s.fn)?.title ?? s.fn).join(" → ")}
                          </span>
                        </button>
                        <button type="button" title="이름 변경" aria-label="이름 변경"
                                onClick={() => setRenaming({ id: t.id, name: t.name })}
                                className="material-symbols-outlined text-[14px] text-md-on-surface-variant opacity-0 hover:text-md-primary group-hover:opacity-100 focus:opacity-100">
                          edit
                        </button>
                        <button type="button" title="삭제" aria-label="삭제" data-template-delete={t.id}
                                onClick={() => void onDeleteTemplate(t)}
                                className="material-symbols-outlined text-[14px] text-md-on-surface-variant opacity-0 hover:text-md-error group-hover:opacity-100 focus:opacity-100">
                          close
                        </button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
          {presets.length && !q.trim() ? (
            <li className="mb-2" data-testid="composition-presets">
              <div className="mb-1 flex items-center gap-1 text-[10.5px] font-semibold text-md-on-surface-variant">
                <span className="material-symbols-outlined text-[13px] text-md-primary" aria-hidden>auto_awesome</span>
                추천 직무
              </div>
              <ul>
                {presets.map((t) => (
                  <li key={t.id} className="mb-1">
                    <button type="button" data-preset={t.id} onClick={() => onLoadTemplate(t)}
                            title={t.steps.map((x) => byId.get(x.fn)?.title ?? x.fn).join(" → ")}
                            className="flex w-full flex-col rounded-[8px] border border-dashed border-md-outline-variant bg-md-surface-container-lowest p-2 text-left hover:border-md-primary">
                      <span className="block truncate text-[12px] font-semibold leading-snug text-md-on-surface">{t.name}</span>
                      <span className="block truncate text-[10.5px] leading-snug text-md-on-surface-variant">
                        {t.steps.length}단계 · {t.about}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          ) : null}
          {shown.length ? shown.flatMap((f, idx) => {
            // 단계 머리글(2026-10-06) — 카테고리가 바뀌는 자리에. 검색 중엔 생략.
            const prev = idx > 0 ? shown[idx - 1]!.category : null;
            const head = !q.trim() && f.category !== prev && (STAGES as string[]).includes(f.category)
              ? [<li key={`stage-${f.category}`} data-stage={f.category}
                    className="mb-1 mt-2 first:mt-0 text-[10.5px] font-semibold text-md-on-surface-variant">
                  {f.category as Stage}
                </li>]
              : [];
            return [...head, tile(f)];
          }) : (
            <li className="px-1 py-4 text-center text-[12px] text-md-on-surface-variant">
              해당하는 기능이 없습니다.
            </li>
          )}
        </ul>
      </div>

      {/* ───────── 아래 1/3 — 고른 기능의 입력 / 연계 목록 ───────── */}
      <div className="flex min-h-0 flex-1 flex-col border-t border-md-outline-variant bg-md-surface-container-low/40">
        {draft ? (
          <>
            <div className="flex items-center gap-1.5 px-2.5 pt-2">
              <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-md-on-surface">
                {draft.idx !== undefined ? `${draft.idx + 1}단계 · ` : ""}{draft.f.title}
              </span>
              {draft.filling ? (
                <span className="text-[10.5px] text-md-on-surface-variant">대화에서 채우는 중…</span>
              ) : draft.filled ? (
                <span className="text-[10.5px] text-md-primary" data-testid="composition-filled">대화 내용으로 채움</span>
              ) : null}
              <button type="button" onClick={closeDraft} aria-label="닫기"
                      className="material-symbols-outlined text-[16px] text-md-on-surface-variant hover:text-md-primary">
                close
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-2.5 py-1.5" data-testid="composition-draft">
              {showFormList ? (
                <>
                  <p className="text-[11px] text-md-on-surface-variant">대화에 나온 서식 — 골라서 바로 작성합니다.</p>
                  <ul className="mt-1 flex flex-col gap-1" data-testid="composition-form-list">
                    {formCitations.map((fc) => (
                      <li key={fc.id}>
                        <button
                          type="button"
                          data-form-citation={fc.articleKey}
                          onClick={() => { onUseAsForm!(fc.articleKey, fc.title); closeDraft(); }}
                          className="flex w-full items-center gap-1.5 rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest px-2 py-1.5 text-left hover:border-md-primary"
                        >
                          <span className="material-symbols-outlined text-[14px] text-md-primary" aria-hidden>description</span>
                          <span className="min-w-0 flex-1 truncate text-[11.5px] text-md-on-surface">{fc.title}</span>
                          <span className="shrink-0 text-[10.5px] font-medium text-md-primary">작성</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <button type="button" onClick={() => setMoreForms((v) => !v)}
                          className="mt-1.5 text-[11px] text-md-on-surface-variant underline underline-offset-2 hover:text-md-primary">
                    {moreForms ? "접기" : "다른 서식 찾기"}
                  </button>
                </>
              ) : null}

              {(!showFormList || moreForms) && draft.f.form ? (
                <div className={"flex flex-col gap-1.5 " + (showFormList ? "mt-1.5" : "")}>
                  {!showFormList && draft.f.form.intro ? (
                    <p className="text-[11px] leading-snug text-md-on-surface-variant">{draft.f.form.intro}</p>
                  ) : null}
                  {draft.f.form.fields.map((fd) => (
                    <label key={fd.key} className="flex flex-col gap-0.5">
                      <span className="text-[10.5px] text-md-on-surface-variant">{fd.label}</span>
                      <input
                        value={draft.st.values[fd.key] ?? ""}
                        data-field={fd.key}
                        onChange={(e) => patchDraft({ values: { ...draft.st.values, [fd.key]: e.target.value } })}
                        placeholder={fd.placeholder}
                        className="w-full rounded-[6px] border border-md-outline-variant bg-md-surface px-2 py-1 text-[12px] outline-none focus:border-md-primary"
                      />
                    </label>
                  ))}
                </div>
              ) : null}
              {!draft.f.form && !showFormList ? (
                <p className="text-[11px] leading-snug text-md-on-surface-variant">{draft.f.subtitle}</p>
              ) : null}

              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {canAttach(draft.f) ? (
                  <button type="button" data-add-file disabled={busyFile || draft.st.files.length >= 3 || !threadId}
                          onClick={pickFile}
                          className="rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary disabled:opacity-40">
                    파일 추가
                  </button>
                ) : null}
                <label className="inline-flex items-center gap-1 text-[11px] text-md-on-surface-variant">
                  <input type="checkbox" data-confidential checked={draft.st.confidential}
                         onChange={(e) => patchDraft({ confidential: e.target.checked })} />
                  기밀
                </label>
                {needsFiles(draft.f) && draft.st.files.length === 0 ? (
                  <span className="text-[11px] text-md-error">파일 필요</span>
                ) : null}
              </div>
              {draft.st.files.length ? (
                <ul className="mt-1 flex flex-wrap gap-1">
                  {draft.st.files.map((fl) => (
                    <li key={fl.id}>
                      <button type="button" onClick={() => void dropFile(fl.id)} title="빼기"
                              className="inline-flex items-center gap-1 rounded-pill bg-md-surface-container px-2 py-0.5 text-[10.5px] text-md-on-surface-variant hover:text-md-error">
                        {fl.name}<span className="material-symbols-outlined text-[11px]" aria-hidden>close</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
              {draftBlank && !hasTurns && !showFormList ? (
                <p className="mt-1.5 text-[11px] text-md-on-surface-variant">
                  빈 칸을 채우면 실행할 수 있습니다. 연계 2단계부터는 앞 단계 결과로 채워집니다.
                </p>
              ) : null}
            </div>

            {!showFormList || moreForms ? (
              <div className="flex gap-1.5 px-2.5 pb-2 pt-1">
                {draft.idx !== undefined ? (
                  <>
                    <button type="button" data-testid="composition-save" onClick={addDraft}
                            className="flex-1 rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary">
                      저장
                    </button>
                    <button type="button" onClick={() => removeStep(draft.idx!)}
                            className="rounded-pill border border-md-outline-variant px-3 py-1.5 text-[12px] text-md-on-surface-variant hover:border-md-error hover:text-md-error">
                      빼기
                    </button>
                  </>
                ) : (
                  <>
                    <button type="button" data-testid="composition-run-now" disabled={!draftRunnable || running}
                            onClick={runDraftNow}
                            className="flex-1 rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40">
                      바로 실행
                    </button>
                    <button type="button" data-testid="composition-add"
                            disabled={needsFiles(draft.f) && draft.st.files.length === 0}
                            onClick={addDraft}
                            className="flex-1 rounded-pill border border-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-primary disabled:opacity-40">
                      연계에 추가
                    </button>
                  </>
                )}
              </div>
            ) : null}
          </>
        ) : c.steps.length === 0 ? (
          <p className="px-3 py-4 text-center text-[11.5px] leading-relaxed text-md-on-surface-variant">
            기능을 고르면 여기에 입력이 열립니다.<br />
            {hasTurns ? "대화 내용으로 먼저 채워 드립니다." : "여러 기능을 연계하면 순서대로 돌립니다."}
          </p>
        ) : (
          <>
            <div className="flex items-center gap-2 px-2.5 pt-2">
              <span className="text-[11px] font-semibold text-md-on-surface-variant">
                연계 {Math.min(c.cursor, c.steps.length)}/{c.steps.length}
              </span>
              {c.steps.length >= 1 && !running ? (
                <button type="button" data-testid="composition-save-template"
                        onClick={() => setSaveName((v) => (v === null ? "" : null))}
                        className="ml-auto text-[11px] text-md-primary underline underline-offset-2">
                  직무로 저장
                </button>
              ) : null}
              <button type="button" data-testid="composition-clear" onClick={() => onChange(null)}
                      className={(c.steps.length >= 1 && !running ? "" : "ml-auto ") + "text-[11px] text-md-on-surface-variant underline underline-offset-2 hover:text-md-error"}>
                비우기
              </button>
            </div>
            {saveName !== null ? (
              <form
                className="flex items-center gap-1 px-2.5 pt-1.5"
                data-testid="composition-save-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  const n = saveName.trim();
                  if (!n || savingT) return;
                  setSavingT(true);
                  void onSaveTemplate(n).then(() => setSaveName(null)).finally(() => setSavingT(false));
                }}
              >
                <input autoFocus value={saveName} onChange={(e) => setSaveName(e.target.value)}
                       onKeyDown={(e) => { if (e.key === "Escape") setSaveName(null); }}
                       placeholder="직무 이름 (예: 사건 검토 → 판례 → 의견서)" maxLength={80}
                       data-testid="composition-save-name"
                       className="min-w-0 flex-1 rounded-[6px] border border-md-primary bg-md-surface px-2 py-1 text-[12px] outline-none" />
                <button type="submit" disabled={!saveName.trim() || savingT}
                        className="rounded-pill bg-md-primary px-2.5 py-1 text-[11px] font-semibold text-md-on-primary disabled:opacity-40">
                  저장
                </button>
              </form>
            ) : null}
            <ol className="min-h-0 flex-1 overflow-y-auto px-2.5 py-1.5">
              {c.steps.map((st, i) => {
                const f = byId.get(st.fn);
                const done = i < c.cursor;
                const ready = stepReady(f, st);
                return (
                  <li key={`${st.fn}-${i}`} data-step={st.fn}
                      data-state={done ? "done" : i === c.cursor ? "now" : "todo"}
                      className={"mb-1 flex items-center gap-1.5 rounded-[8px] border px-2 py-1.5 " +
                        (done ? "border-md-outline-variant/60 opacity-60" : "border-md-outline-variant bg-md-surface-container-lowest")}>
                    <span className="w-3 text-[11px] font-bold text-md-primary">{done ? "✓" : i + 1}</span>
                    <button type="button" onClick={() => f && startDraft(f, st, i)} disabled={!f}
                            className="min-w-0 flex-1 truncate text-left text-[11.5px] text-md-on-surface hover:text-md-primary">
                      {f ? f.title : `(없는 기능: ${st.fn})`}
                      {!ready && f ? <span className="ml-1 text-[10px] text-md-error">파일 필요</span> : null}
                    </button>
                    <button type="button" title="위로" onClick={() => move(i, -1)} className="text-[11px] text-md-on-surface-variant hover:text-md-primary">↑</button>
                    <button type="button" title="아래로" onClick={() => move(i, 1)} className="text-[11px] text-md-on-surface-variant hover:text-md-primary">↓</button>
                    <button type="button" title="빼기" data-remove-step={i} onClick={() => removeStep(i)} className="text-[11px] text-md-on-surface-variant hover:text-md-error">✕</button>
                  </li>
                );
              }).flatMap((li, i) => {
                // 공백 제안 — 그 단계 **앞에** 끼운다. 후보 첫 2개만 버튼으로.
                const gapsHere = i < c.cursor ? [] : gaps.filter((g) => g.at === i);
                if (!gapsHere.length) return [li];
                return [
                  <li key={`gap-${i}`} data-gap={i} className="mb-1 rounded-[8px] border border-dashed border-md-primary/50 bg-md-primary-container/20 px-2 py-1.5">
                    {gapsHere.map((g) => (
                      <div key={g.slot} className="flex flex-wrap items-center gap-1 text-[11px]">
                        <span className="material-symbols-outlined text-[13px] text-md-primary" aria-hidden>add_circle</span>
                        <span className="text-md-on-surface-variant">빠진 단계 — {g.label}:</span>
                        {g.candidates.slice(0, 2).map((cand) => (
                          <button key={cand.id} type="button" data-gap-insert={cand.id}
                                  onClick={() => insertStep(i, cand)}
                                  className="rounded-pill border border-md-primary px-2 py-0.5 text-[10.5px] font-medium text-md-primary hover:bg-md-primary hover:text-md-on-primary">
                            {cand.title} 넣기
                          </button>
                        ))}
                      </div>
                    ))}
                  </li>,
                  li,
                ];
              })}
            </ol>
            <div className="px-2.5 pb-2">
              {running ? (
                <button type="button" data-testid="composition-stop" onClick={onStop}
                        className="w-full rounded-pill border border-md-error px-3 py-1.5 text-[12px] font-semibold text-md-error">
                  중단
                </button>
              ) : c.status === "done" ? ( // 구버전 저장분 — 지금은 끝나면 비운다
                <button type="button" data-testid="composition-run-auto" disabled={!canRun} onClick={() => onRun("auto")}
                        className="w-full rounded-pill border border-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-primary disabled:opacity-40">
                  다시 실행
                </button>
              ) : c.steps.length === 1 ? (
                <button type="button" data-testid="composition-run-auto" disabled={!canRun} onClick={() => onRun("auto")}
                        className="w-full rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40">
                  실행
                </button>
              ) : (
                <div className="flex gap-1.5">
                  <button type="button" data-testid="composition-run-stepwise" disabled={!canRun} onClick={() => onRun("stepwise")}
                          className="flex-1 rounded-pill border border-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-primary disabled:opacity-40">
                    단계별
                  </button>
                  <button type="button" data-testid="composition-run-auto" disabled={!canRun} onClick={() => onRun("auto")}
                          className="flex-1 rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40">
                    한번에
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
