"use client";

/**
 * CompositionPanel — "기능연계" 패널 (2026-10-05 재설계).
 *
 * 사용자 지침(2026-10-05): "간단한 기능은 첫 화면 타일에서 바로 시작한다(유지). 세션
 * 중간에도 기능을 골라 쓸 수 있어야 하고, 기능들을 **연계**해서도 쓸 수 있어야 한다.
 * 세션이 시작되면 이 기능이 오른쪽 패널에 고정되고, 하나를 골라 쓰거나 여러 개를
 * 연계한다. 기능 찾기도 된다."
 *
 * 그래서 종전의 두 표면 — 입력창 팝오버 피커(단일 실행)와 조합 패널(연계) — 를 이 한
 * 패널로 합쳤다. 흐름은 하나다:
 *
 *   타일(검색 가능) 클릭 → 입력·파일·기밀 채움 → [바로 실행] 또는 [연계에 추가]
 *
 * - 바로 실행: 보이는 턴 하나로 지금 보낸다.
 * - 연계에 추가: 아래 목록에 쌓인다. 2단계 이상이면 각 단계는 **숨은 턴**으로 돌고
 *   마지막에 종합 1건만 보인다(단계마다 답을 쏟으면 읽을 수 없는 대화가 된다).
 *   단계별 모드는 한 단계마다 멈춰 사람이 검토하고, 한번에 모드는 끝까지 간다.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { featuresFor, filterFeatures, type Feature } from "@/lib/features/catalog";
import {
  deleteStepFile,
  emptyStep,
  needsFiles,
  stepBlanks,
  stepReady,
  uploadStepFile,
  type Composition,
  type CompositionStep,
} from "@/lib/features/composition";
import type { AppMode } from "@/lib/store/mode";

type Props = {
  threadId: string | null;
  mode: AppMode | null;
  composition: Composition | null;
  running: boolean;
  onChange: (c: Composition | null) => void;
  onRun: (mode: "stepwise" | "auto") => void;
  /** 기능 하나를 보이는 턴으로 지금 보낸다. */
  onRunNow: (f: Feature, st: CompositionStep) => void;
  onStop: () => void;
};

const BLANK: Composition = {
  steps: [],
  cursor: 0,
  mode: "stepwise",
  status: "draft",
};

const CATEGORY_ICON: Record<string, string> = {
  "규제 경로 분해": "checklist",
  "서식 작성": "description",
  "기밀 검토": "lock",
  "문서 검토": "attach_file",
  "판례 검토": "balance",
  "조문 변동": "difference",
  "규정 점검": "rule",
  "의무 정리": "fact_check",
  "지역 비교": "map",
  유권해석: "quick_reference_all",
  "인용 검증": "verified",
  "제재 가늠": "scale",
  "개정 추적": "update",
  "영향 분석": "hub",
  "서면 작성": "draft",
  "대상 정의": "track_changes",
  "자료 검토": "upload_file",
  "변경 추적": "notifications_active",
};

/** 단계 하나의 입력 편집기 — 새 단계 구성과 목록 안 편집이 같은 UI 를 쓴다. */
function StepEditor({
  f,
  st,
  idx,
  busyFile,
  canUpload,
  onPatch,
  onPickFile,
  onDropFile,
}: {
  f: Feature;
  st: CompositionStep;
  idx: number;
  busyFile: boolean;
  canUpload: boolean;
  onPatch: (next: Partial<CompositionStep>) => void;
  onPickFile: () => void;
  onDropFile: (fileId: string) => void;
}) {
  return (
    <>
      {f.form ? (
        <div className="mt-1.5 flex flex-col gap-1.5">
          {f.form.fields.map((fd) => (
            <label key={fd.key} className="flex flex-col gap-0.5">
              <span className="text-[10.5px] text-md-on-surface-variant">{fd.label}</span>
              <input
                value={st.values[fd.key] ?? ""}
                data-field={`${idx}:${fd.key}`}
                onChange={(e) =>
                  onPatch({ values: { ...st.values, [fd.key]: e.target.value } })
                }
                placeholder={fd.placeholder}
                className="w-full rounded-[6px] border border-md-outline-variant bg-md-surface px-2 py-1 text-[12px] outline-none focus:border-md-primary"
              />
            </label>
          ))}
        </div>
      ) : null}

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          data-add-file={idx}
          disabled={busyFile || st.files.length >= 3 || !canUpload}
          onClick={onPickFile}
          title={canUpload ? undefined : "대화를 먼저 시작해야 파일을 올릴 수 있습니다"}
          className="rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary disabled:opacity-40"
        >
          파일 추가
        </button>
        <label className="inline-flex items-center gap-1 text-[11px] text-md-on-surface-variant">
          <input
            type="checkbox"
            data-confidential={idx}
            checked={st.confidential}
            onChange={(e) => onPatch({ confidential: e.target.checked })}
          />
          기밀
        </label>
        {needsFiles(f) && st.files.length === 0 ? (
          <span className="text-[11px] text-md-error">파일 필요</span>
        ) : null}
      </div>

      {st.files.length ? (
        <ul className="mt-1 flex flex-wrap gap-1">
          {st.files.map((fl) => (
            <li key={fl.id}>
              <button
                type="button"
                onClick={() => onDropFile(fl.id)}
                title="빼기"
                className="inline-flex items-center gap-1 rounded-pill bg-md-surface-container px-2 py-0.5 text-[10.5px] text-md-on-surface-variant hover:text-md-error"
              >
                {fl.name}
                <span className="material-symbols-outlined text-[11px]" aria-hidden>
                  close
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

export function CompositionPanel({
  threadId,
  mode,
  composition,
  running,
  onChange,
  onRun,
  onRunNow,
  onStop,
}: Props) {
  const c = composition ?? BLANK;
  const [q, setQ] = useState("");
  /** 타일을 눌러 구성 중인 단계(아직 목록에 없음). */
  const [draft, setDraft] = useState<{ f: Feature; st: CompositionStep } | null>(null);
  /** 연계가 있을 때 타일 격자를 접어 둔다 — 목록이 밀려 내려가면 안 된다. */
  const [gridOpen, setGridOpen] = useState(true);
  const [busyFile, setBusyFile] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  // -1 = 구성 중인 초안, 0.. = 목록의 단계
  const fileTargetRef = useRef<number>(-2);

  // 패널을 여는 기능(brief·watch)은 턴으로 보낼 문장이 없다 — 입력창의 전용
  // 버튼(의견서 초안·관찰 목록)으로 연다. 여기서는 뺀다.
  const all = useMemo(
    () => featuresFor({ mode, hasTurns: true }).filter(
      (f) => f.triggers !== "brief" && f.triggers !== "watch",
    ),
    [mode],
  );
  const byId = useMemo(() => new Map(all.map((f) => [f.id, f])), [all]);
  const shown = useMemo(() => filterFeatures(all, q), [all, q]);

  const patch = useCallback(
    (next: Partial<Composition>) => onChange({ ...c, ...next }),
    [c, onChange],
  );
  const patchStep = useCallback(
    (i: number, next: Partial<CompositionStep>) => {
      const steps = c.steps.slice();
      steps[i] = { ...steps[i]!, ...next };
      patch({ steps });
    },
    [c.steps, patch],
  );
  const patchDraft = (next: Partial<CompositionStep>) =>
    setDraft((d) => (d ? { ...d, st: { ...d.st, ...next } } : d));

  const startDraft = (f: Feature) => setDraft({ f, st: emptyStep(f) });

  const addDraft = () => {
    if (!draft) return;
    if (c.steps.length >= 8) {
      toast.error("연계는 8단계까지입니다.");
      return;
    }
    patch({ steps: [...c.steps, draft.st] });
    setDraft(null);
    setGridOpen(false);
  };

  const runDraftNow = () => {
    if (!draft) return;
    onRunNow(draft.f, draft.st);
    setDraft(null);
  };

  const removeStep = (i: number) =>
    patch({
      steps: c.steps.filter((_, k) => k !== i),
      cursor: Math.min(c.cursor, Math.max(0, c.steps.length - 2)),
    });

  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= c.steps.length) return;
    const steps = c.steps.slice();
    [steps[i], steps[j]] = [steps[j]!, steps[i]!];
    patch({ steps });
  };

  const pickFile = (target: number) => {
    if (!threadId) {
      toast.error("대화를 먼저 시작해 주세요.");
      return;
    }
    fileTargetRef.current = target;
    fileRef.current?.click();
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    const target = fileTargetRef.current;
    if (!file || !threadId || target < -1) return;
    setBusyFile(target);
    try {
      const f = await uploadStepFile(threadId, file);
      const meta = { id: f.id, name: f.name, chars: f.chars };
      if (target === -1) {
        setDraft((d) => (d ? { ...d, st: { ...d.st, files: [...d.st.files, meta] } } : d));
      } else {
        const st = c.steps[target]!;
        patchStep(target, { files: [...st.files, meta] });
      }
      if (f.truncated) {
        toast.warning(`${f.name} 은 일부만 읽었습니다.`, {
          description: "문서가 길어 앞부분만 사용합니다.",
        });
      }
    } catch {
      toast.error("파일을 올리지 못했습니다.");
    } finally {
      setBusyFile(null);
    }
  };

  const dropFile = async (target: number, fileId: string) => {
    if (target === -1) {
      setDraft((d) => (d ? { ...d, st: { ...d.st, files: d.st.files.filter((x) => x.id !== fileId) } } : d));
    } else {
      const st = c.steps[target]!;
      patchStep(target, { files: st.files.filter((x) => x.id !== fileId) });
    }
    if (!threadId) return;
    try {
      await deleteStepFile(threadId, fileId);
    } catch {
      /* 목록에서만 빠져도 실행은 막힌다 — 서버 정리는 best-effort */
    }
  };

  // 실행 가능 판정 — 파일은 모든 단계, 빈 칸은 **지금 돌 단계**만 본다. 뒤 단계의
  // 빈 칸은 앞 단계 결과로 채워지므로 미리 막으면 연계를 못 시작한다.
  const cursor = Math.min(c.cursor, Math.max(0, c.steps.length - 1));
  const blocked = c.steps.findIndex((st, i) => {
    const f = byId.get(st.fn);
    if (!stepReady(f, st)) return true;
    return i === cursor && !!f && stepBlanks(f, st);
  });
  const canRun = c.steps.length > 0 && blocked < 0 && !!threadId;
  const draftBlank = draft ? stepBlanks(draft.f, draft.st) : false;
  const draftReady = draft ? stepReady(draft.f, draft.st) && !draftBlank : false;

  return (
    <section data-testid="composition-panel" className="flex h-full min-h-0 flex-col">
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.hwpx,.txt"
        onChange={(e) => void onFile(e)}
        className="hidden"
      />

      {/* ── 구성 중인 단계 — 타일을 눌렀을 때 ── */}
      {draft ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-md-outline-variant px-3 py-2">
            <button
              type="button"
              onClick={() => setDraft(null)}
              aria-label="뒤로"
              className="material-symbols-outlined text-[18px] text-md-on-surface-variant hover:text-md-primary"
            >
              arrow_back
            </button>
            <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-md-on-surface">
              {draft.f.title}
            </span>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2" data-testid="composition-draft">
            <p className="text-[11.5px] leading-snug text-md-on-surface-variant">
              {draft.f.form?.intro ?? draft.f.subtitle}
            </p>
            {draft.f.expects.length ? (
              <ul className="mt-1.5 flex flex-col gap-0.5">
                {draft.f.expects.map((e) => (
                  <li key={e} className="flex gap-1 text-[11px] text-md-on-surface-variant">
                    <span className="material-symbols-outlined mt-[1px] text-[12px] text-md-primary" aria-hidden>
                      check
                    </span>
                    <span>{e}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            <StepEditor
              f={draft.f}
              st={draft.st}
              idx={-1}
              busyFile={busyFile === -1}
              canUpload={!!threadId}
              onPatch={patchDraft}
              onPickFile={() => pickFile(-1)}
              onDropFile={(id) => void dropFile(-1, id)}
            />
            {draftBlank ? (
              <p className="mt-2 text-[11px] text-md-on-surface-variant">
                빈 칸을 채우면 바로 실행할 수 있습니다. 연계에 넣으면 앞 단계 결과로 채울 수 있습니다.
              </p>
            ) : null}
          </div>
          <div className="flex gap-1.5 border-t border-md-outline-variant px-3 py-2.5">
            <button
              type="button"
              data-testid="composition-run-now"
              disabled={!draftReady || running}
              onClick={runDraftNow}
              className="flex-1 rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
            >
              바로 실행
            </button>
            <button
              type="button"
              data-testid="composition-add"
              disabled={!stepReady(draft.f, draft.st) && needsFiles(draft.f)}
              onClick={addDraft}
              className="flex-1 rounded-pill border border-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-primary disabled:opacity-40"
            >
              연계에 추가
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* ── 타일 + 검색 ── */}
          <div className="border-b border-md-outline-variant px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-label-caps text-md-on-surface-variant">기능연계</span>
              {c.steps.length ? (
                <button
                  type="button"
                  data-testid="composition-grid-toggle"
                  onClick={() => setGridOpen((v) => !v)}
                  className="ml-auto rounded-pill border border-md-outline-variant px-2.5 py-0.5 text-[11.5px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary"
                >
                  {gridOpen ? "목록 접기" : "기능 추가"}
                </button>
              ) : null}
            </div>
            {gridOpen || !c.steps.length ? (
              <div className="relative mt-2">
                <span
                  className="material-symbols-outlined pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-[15px] text-md-on-surface-variant"
                  aria-hidden
                >
                  search
                </span>
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="기능 찾기 (이름 · 설명 · 분류)"
                  data-testid="composition-search"
                  className="w-full rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest py-1.5 pl-7 pr-2.5 text-[12px] outline-none focus:border-md-primary"
                />
              </div>
            ) : null}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
            {gridOpen || !c.steps.length ? (
              shown.length ? (
                <ul className="mb-3 grid grid-cols-2 gap-1.5" data-testid="composition-grid">
                  {shown.map((f) => (
                    <li key={f.id}>
                      <button
                        type="button"
                        data-add-feature={f.id}
                        onClick={() => startDraft(f)}
                        title={f.expects.join("\n")}
                        className="flex h-full w-full flex-col gap-0.5 rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest p-2 text-left transition-colors hover:border-md-primary hover:bg-md-surface-container-low"
                      >
                        <span className="flex items-center gap-1 text-[10px] text-md-on-surface-variant">
                          <span className="material-symbols-outlined text-[13px] text-md-primary" aria-hidden>
                            {CATEGORY_ICON[f.category] ?? "bolt"}
                          </span>
                          <span className="truncate">{f.category}</span>
                        </span>
                        <span className="text-[12px] font-semibold leading-snug text-md-on-surface">
                          {f.title}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mb-3 px-1 py-4 text-center text-[12px] text-md-on-surface-variant">
                  해당하는 기능이 없습니다.
                </p>
              )
            ) : null}

            {c.steps.length === 0 ? (
              <p className="px-1 pb-2 text-center text-[11.5px] leading-relaxed text-md-on-surface-variant">
                기능을 골라 바로 실행하거나, 여러 기능을 연계해 순서대로 돌릴 수 있습니다.
              </p>
            ) : (
              <>
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="text-[11px] font-semibold text-md-on-surface-variant">
                    연계 {Math.min(c.cursor, c.steps.length)}/{c.steps.length}
                  </span>
                  <button
                    type="button"
                    data-testid="composition-clear"
                    onClick={() => onChange(null)}
                    className="ml-auto text-[11px] text-md-on-surface-variant underline underline-offset-2 hover:text-md-error"
                  >
                    비우기
                  </button>
                </div>
                <ol className="flex flex-col gap-2">
                  {c.steps.map((st, i) => {
                    const f = byId.get(st.fn);
                    const done = i < c.cursor;
                    const ready = stepReady(f, st);
                    return (
                      <li
                        key={`${st.fn}-${i}`}
                        data-step={st.fn}
                        data-state={done ? "done" : i === c.cursor ? "now" : "todo"}
                        className={
                          "rounded-[10px] border p-2.5 " +
                          (done
                            ? "border-md-outline-variant/60 bg-md-surface-container-lowest opacity-70"
                            : "border-md-outline-variant bg-md-surface-container-lowest")
                        }
                      >
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] font-bold text-md-primary">
                            {done ? "✓" : i + 1}
                          </span>
                          <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-md-on-surface">
                            {f ? f.title : `(없는 기능: ${st.fn})`}
                          </span>
                          <button type="button" title="위로" onClick={() => move(i, -1)}
                            className="text-[11px] text-md-on-surface-variant hover:text-md-primary">↑</button>
                          <button type="button" title="아래로" onClick={() => move(i, 1)}
                            className="text-[11px] text-md-on-surface-variant hover:text-md-primary">↓</button>
                          <button type="button" title="빼기" data-remove-step={i}
                            onClick={() => removeStep(i)}
                            className="text-[11px] text-md-on-surface-variant hover:text-md-error">✕</button>
                        </div>
                        {f ? (
                          <StepEditor
                            f={f}
                            st={st}
                            idx={i}
                            busyFile={busyFile === i}
                            canUpload={!!threadId}
                            onPatch={(next) => patchStep(i, next)}
                            onPickFile={() => pickFile(i)}
                            onDropFile={(id) => void dropFile(i, id)}
                          />
                        ) : null}
                        {!ready && f ? (
                          <p className="mt-1 text-[11px] text-md-on-surface-variant">
                            파일을 올려야 이 단계를 실행할 수 있습니다.
                          </p>
                        ) : null}
                      </li>
                    );
                  })}
                </ol>
              </>
            )}
          </div>

          {c.steps.length ? (
            <div className="border-t border-md-outline-variant px-3 py-2.5">
              {running ? (
                <button
                  type="button"
                  data-testid="composition-stop"
                  onClick={onStop}
                  className="w-full rounded-pill border border-md-error px-3 py-1.5 text-[12px] font-semibold text-md-error"
                >
                  중단
                </button>
              ) : c.steps.length === 1 ? (
                <button
                  type="button"
                  data-testid="composition-run-auto"
                  disabled={!canRun}
                  onClick={() => onRun("auto")}
                  className="w-full rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
                >
                  실행
                </button>
              ) : (
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    data-testid="composition-run-stepwise"
                    disabled={!canRun}
                    onClick={() => onRun("stepwise")}
                    className="flex-1 rounded-pill border border-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-primary disabled:opacity-40"
                  >
                    단계별 실행
                  </button>
                  <button
                    type="button"
                    data-testid="composition-run-auto"
                    disabled={!canRun}
                    onClick={() => onRun("auto")}
                    className="flex-1 rounded-pill bg-md-primary px-3 py-1.5 text-[12px] font-semibold text-md-on-primary disabled:opacity-40"
                  >
                    한번에 실행
                  </button>
                </div>
              )}
              <p className="mt-1.5 text-[11px] leading-snug text-md-on-surface-variant">
                {c.steps.length === 1
                  ? "한 단계는 보통 질문처럼 바로 답합니다."
                  : "중간 결과는 채팅에 쌓지 않습니다 — 마지막에 한 번 종합해 보여 드립니다."}
              </p>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
