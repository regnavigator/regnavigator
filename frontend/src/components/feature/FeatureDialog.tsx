"use client";

/**
 * FeatureDialog — 기능 카드를 고른 뒤의 템플릿 입력 (2026-10-02).
 *
 * `EmptyHero` 안에 있던 다이얼로그를 그대로 꺼내 공용으로 만들었다. 첫 화면과
 * 스레드 내 피커가 같은 모달을 써야 "화면마다 다른 말" 이 생기지 않는다.
 *
 * 빈 칸은 `___(라벨)` 로 남는다 — 프리필은 자동 전송되지 않으므로 그 자체가
 * 채워 넣을 템플릿이 된다(사용자 요구: "템플릿으로 나와서").
 */

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Feature } from "@/lib/features/catalog";

export function FeatureDialog({
  feature,
  onClose,
  onRun,
}: {
  feature: Feature | null;
  onClose: () => void;
  onRun: (feature: Feature, values: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});

  // 카드를 바꿔 열면 앞 카드의 입력이 남아 있으면 안 된다.
  useEffect(() => {
    setValues({});
  }, [feature]);

  const preview = feature?.form
    ? feature.form.build(
        Object.fromEntries(
          Object.entries(values).map(([k, v]) => [k, v.trim()]),
        ),
      )
    : null;

  return (
    <Dialog open={!!feature} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        data-testid="feature-dialog"
        className="max-w-[560px] border border-md-outline-variant bg-md-surface text-md-on-surface"
      >
        {feature ? (
          <>
            <DialogHeader>
              <DialogTitle className="text-[16px] font-bold">{feature.title}</DialogTitle>
              <DialogDescription className="text-[12.5px] text-md-on-surface-variant">
                {feature.form?.intro ?? feature.subtitle}
              </DialogDescription>
            </DialogHeader>

            <section>
              <p className="text-[12px] font-semibold text-md-on-surface-variant">
                이 기능으로 할 수 있는 것
              </p>
              <ul className="mt-1.5 flex flex-col gap-1">
                {feature.expects.map((e) => (
                  <li key={e} className="flex gap-1.5 text-[12.5px] text-md-on-surface-variant">
                    <span className="material-symbols-outlined mt-[1px] text-[14px] text-md-primary" aria-hidden>
                      check
                    </span>
                    <span>{e}</span>
                  </li>
                ))}
              </ul>
            </section>

            {feature.form ? (
              <section>
                <p className="text-[12px] font-semibold text-md-on-surface-variant">
                  더 정확한 답을 위해(선택)
                </p>
                <div className="mt-1.5 grid gap-2 sm:grid-cols-2">
                  {feature.form.fields.map((f, i) => (
                    <label
                      key={f.key}
                      className={`flex flex-col gap-1 ${i === 0 ? "sm:col-span-2" : ""}`}
                    >
                      <span className="text-[11.5px] text-md-on-surface-variant">{f.label}</span>
                      <input
                        value={values[f.key] ?? ""}
                        onChange={(e) =>
                          setValues((prev) => ({ ...prev, [f.key]: e.target.value }))
                        }
                        placeholder={f.placeholder}
                        className="rounded-[10px] border border-md-outline-variant bg-md-surface-container-lowest px-2.5 py-1.5 text-[12.5px] outline-none focus:border-md-primary"
                      />
                    </label>
                  ))}
                </div>
              </section>
            ) : null}

            {preview ? (
              <section>
                <p className="text-[12px] font-semibold text-md-on-surface-variant">
                  이렇게 물어봅니다
                </p>
                <p
                  data-testid="feature-preview"
                  className="mt-1 whitespace-pre-wrap rounded-[10px] bg-md-surface-container-low px-3 py-2 text-[12.5px] leading-[1.7]"
                >
                  {preview}
                </p>
                <p className="mt-1.5 text-[12px] text-md-on-surface-variant">
                  입력창에 들어갑니다 — 보내기 전에 고칠 수 있습니다.
                </p>
              </section>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                취소
              </Button>
              <Button
                onClick={() => {
                  onRun(feature, values);
                  onClose();
                }}
              >
                {feature.triggers === "attach"
                  ? "문서 선택하기"
                  : feature.triggers === "brief"
                    ? "초안 열기"
                    : "이 질문으로 시작"}
              </Button>
            </div>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
