"use client";

/**
 * CompositionPanel — 조합을 짜고 돌리는 화면 (2026-10-02).
 *
 * 왜 패널인가: 종전엔 입력창 위 팝오버에서 기능을 골랐다. 팝오버는 떴다 사라지고
 * 좁아서, **파일을 올리거나 단계별 기밀을 정할 자리가 없었다**. 조합은 짜다 말고
 * 돌아오는 작업이라 상주하는 화면이 맞다.
 *
 * 한 화면에서 끝낸다: 기능 선택 → 순서 → 단계별 입력·파일·기밀 → 실행.
 *
 * 실행은 두 가지다.
 *  - 단계별: 한 단계가 끝나면 다음 단계 입력을 **채워 놓고 멈춘다**. 사람이 보고
 *    고친 뒤 넘어간다.
 *  - 한번에: 채우고 바로 진행해 끝까지 간다.
 * 둘 다 중간 결과를 채팅에 쏟지 않는다 — 마지막에 종합 1건만 남는다.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { featuresFor, type Feature } from "@/lib/features/catalog";
import {
  deleteStepFile,
  emptyStep,
  needsFiles,
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
  onStop: () => void;
};

const BLANK: Composition = {
  steps: [],
  cursor: 0,
  mode: "stepwise",
  status: "draft",
};

export function CompositionPanel({
  threadId,
  mode,
  composition,
  running,
  onChange,
  onRun,
  onStop,
}: Props) {
  const c = composition ?? BLANK;
  const [picking, setPicking] = useState(c.steps.length === 0);
  const [q, setQ] = useState("");
  const [busyFile, setBusyFile] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const fileStepRef = useRef<number>(-1);

  const all = useMemo(
    () => featuresFor({ mode, hasTurns: true }),
    [mode],
  );
  const byId = useMemo(() => new Map(all.map((f) => [f.id, f])), [all]);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return all;
    return all.filter((f) =>
      [f.title, f.subtitle, f.category].join(" ").toLowerCase().includes(t),
    );
  }, [all, q]);

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

  const addStep = (f: Feature) => {
    if (c.steps.length >= 8) {
      toast.error("조합은 8단계까지입니다.");
      return;
    }
    patch({ steps: [...c.steps, emptyStep(f)] });
  };

  const removeStep = (i: number) =>
    patch({
      steps: c.steps.filter((_, k) => k !== i),
      cursor: Math.min(c.cursor, c.steps.length - 1),
    });

  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= c.steps.length) return;
    const steps = c.steps.slice();
    [steps[i], steps[j]] = [steps[j]!, steps[i]!];
    patch({ steps });
  };

  const pickFile = (i: number) => {
    if (!threadId) {
      toast.error("대화를 먼저 시작해 주세요.");
      return;
    }
    fileStepRef.current = i;
    fileRef.current?.click();
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    const i = fileStepRef.current;
    if (!file || !threadId || i < 0) return;
    setBusyFile(i);
    try {
      const f = await uploadStepFile(threadId, file);
      const st = c.steps[i]!;
      patchStep(i, { files: [...st.files, { id: f.id, name: f.name, chars: f.chars }] });
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

  const dropFile = async (i: number, fileId: string) => {
    if (!threadId) return;
    const st = c.steps[i]!;
    patchStep(i, { files: st.files.filter((f) => f.id !== fileId) });
    try {
      await deleteStepFile(threadId, fileId);
    } catch {
      /* 목록에서만 빠져도 실행은 막힌다 — 서버 정리는 best-effort */
    }
  };

  const blocked = c.steps.findIndex(
    (st) => !stepReady(byId.get(st.fn), st),
  );
  const canRun = c.steps.length > 0 && blocked < 0 && !!threadId;

  return (
    <section
      data-testid="composition-panel"
      className="flex h-full min-h-0 flex-col"
    >
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,.docx,.hwpx,.txt"
        onChange={(e) => void onFile(e)}
        className="hidden"
      />

      <div className="flex items-center gap-2 border-b border-md-outline-variant px-3 py-2">
        <span className="text-label-caps text-md-on-surface-variant">
          조합 {c.steps.length ? `${Math.min(c.cursor, c.steps.length)}/${c.steps.length}` : ""}
        </span>
        <button
          type="button"
          data-testid="composition-add"
          onClick={() => setPicking((v) => !v)}
          className="ml-auto rounded-pill border border-md-outline-variant px-2.5 py-0.5 text-[11.5px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary"
        >
          {picking ? "닫기" : "기능 추가"}
        </button>
        {c.steps.length ? (
          <button
            type="button"
            data-testid="composition-clear"
            onClick={() => onChange(null)}
            className="text-[11.5px] text-md-on-surface-variant underline underline-offset-2 hover:text-md-error"
          >
            비우기
          </button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {picking ? (
          <div className="mb-3">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="기능 찾기"
              data-testid="composition-search"
              className="mb-2 w-full rounded-[8px] border border-md-outline-variant bg-md-surface-container-lowest px-2.5 py-1.5 text-[12.5px] outline-none focus:border-md-primary"
            />
            <ul className="flex flex-col gap-1">
              {shown.map((f) => (
                <li key={f.id}>
                  <button
                    type="button"
                    data-add-feature={f.id}
                    onClick={() => addStep(f)}
                    className="w-full rounded-[8px] border border-md-outline-variant px-2.5 py-1.5 text-left transition-colors hover:border-md-primary hover:bg-md-surface-container-low"
                  >
                    <span className="block text-[12.5px] font-semibold text-md-on-surface">
                      {f.title}
                    </span>
                    <span className="block text-[11px] text-md-on-surface-variant">
                      {f.subtitle}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {c.steps.length === 0 ? (
          <p className="px-1 py-6 text-center text-[12.5px] leading-relaxed text-md-on-surface-variant">
            기능을 골라 순서를 만드세요.
            <br />
            단계마다 입력·파일·기밀을 따로 정할 수 있습니다.
          </p>
        ) : null}

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

                {f?.form ? (
                  <div className="mt-1.5 flex flex-col gap-1">
                    {f.form.fields.map((fd) => (
                      <input
                        key={fd.key}
                        value={st.values[fd.key] ?? ""}
                        data-field={`${i}:${fd.key}`}
                        onChange={(e) =>
                          patchStep(i, {
                            values: { ...st.values, [fd.key]: e.target.value },
                          })
                        }
                        placeholder={fd.placeholder || fd.label}
                        className="w-full rounded-[6px] border border-md-outline-variant bg-md-surface px-2 py-1 text-[12px] outline-none focus:border-md-primary"
                      />
                    ))}
                  </div>
                ) : null}

                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    data-add-file={i}
                    disabled={busyFile === i || st.files.length >= 3}
                    onClick={() => pickFile(i)}
                    className="rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant hover:border-md-primary hover:text-md-primary disabled:opacity-40"
                  >
                    파일 추가
                  </button>
                  <label className="inline-flex items-center gap-1 text-[11px] text-md-on-surface-variant">
                    <input
                      type="checkbox"
                      data-confidential={i}
                      checked={st.confidential}
                      onChange={(e) =>
                        patchStep(i, { confidential: e.target.checked })
                      }
                    />
                    기밀
                  </label>
                  {f && needsFiles(f) && st.files.length === 0 ? (
                    <span className="text-[11px] text-md-error">파일 필요</span>
                  ) : null}
                </div>

                {st.files.length ? (
                  <ul className="mt-1 flex flex-wrap gap-1">
                    {st.files.map((fl) => (
                      <li key={fl.id}>
                        <button
                          type="button"
                          onClick={() => void dropFile(i, fl.id)}
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

                {!ready && f ? (
                  <p className="mt-1 text-[11px] text-md-on-surface-variant">
                    파일을 올려야 이 단계를 실행할 수 있습니다.
                  </p>
                ) : null}
              </li>
            );
          })}
        </ol>
      </div>

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
          중간 결과는 채팅에 쌓지 않습니다 — 마지막에 한 번 종합해 보여 드립니다.
        </p>
      </div>
    </section>
  );
}
