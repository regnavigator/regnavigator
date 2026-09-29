"use client";

/**
 * SettingsDialog — 03 §11 v0.3.1, 05 §3.1.
 *
 * **용도 변경**: 본 다이얼로그는 *개발자 override*만. production 배포는
 * 환경변수(`NEXT_PUBLIC_DEPLOYMENT_URL`, `NEXT_PUBLIC_ASSISTANT_ID`)가 권위.
 *
 *  - 자동 오픈은 dev 환경 + env 미충족 시에만 (PageShell 책임).
 *  - 사용자는 헤더 ⚙ 클릭으로 항상 수동 오픈 가능 (dev convenience).
 *  - `NEXT_PUBLIC_DUMMY_MODE=true` 일 때 폼 자체를 비활성하고 안내 메시지.
 *
 * 폼 row는 `field` 배열 기반 — v2에서 `user_jwt` 등 추가가 한 행 추가로 끝나도록
 * 구조화 (00 §8 H6 foreclose 금지).
 */

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogAction,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  emptySettings,
  isDummyMode,
  notifySettingsChanged,
  readStoredOverride,
  writeSettings,
  type Settings,
} from "@/lib/store/settings";

type FieldKey = keyof Settings;

type FieldDef = {
  key: FieldKey;
  label: string;
  type: "text" | "password";
  placeholder: string;
  required: boolean;
  hint?: string;
};

/**
 * 폼 필드 — 새 인증 필드는 본 배열에 한 행 추가로 끝남 (P2.6).
 * production은 env가 권위이므로 *required 표시는 시각만* — 폼 저장은 빈값도 허용
 * (env가 채울 수 있음).
 */
const FIELDS: FieldDef[] = [
  {
    key: "deployment_url",
    label: "백엔드 API URL",
    type: "text",
    placeholder: "https://<your-deployment>.langgraph.app",
    required: false,
    hint: "medi-back 주소 (예: http://<dev 호스트>:2024). 비우면 기본값 사용",
  },
    ];

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function SettingsDialog({ open, onOpenChange }: Props) {
  const dummy = isDummyMode();
  const [draft, setDraft] = useState<Settings>(() => readStoredOverride() ?? emptySettings());

  // 다이얼로그가 열릴 때마다 최신 *override 원본*만 로드 (env 값은 폼에 안 들어감)
  useEffect(() => {
    if (open) setDraft(readStoredOverride() ?? emptySettings());
  }, [open]);

  function handleSave() {
    if (dummy) return;
    writeSettings(draft);
    notifySettingsChanged();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="border-md-outline-variant bg-md-surface text-md-on-surface sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>설정</DialogTitle>
          <DialogDescription>
            백엔드(medi-back) 연결 정보 — dev override 전용. 운영 배포는 빌드 env 로 주입됩니다.
          </DialogDescription>
        </DialogHeader>

        {/* dev override 안내 — 03 §11 */}
        <div className="rounded-card border border-md-outline-variant bg-md-surface-container-low p-3 text-body-sm text-md-on-surface-variant">
          이 설정은 <strong className="text-md-on-surface">개발자용 override</strong>입니다.
          운영 환경에서는 서버 설정값이 권위이며, 여기 입력하면 같은 브라우저에서만 그 값 위에 덮어쓰입니다.
        </div>

        {dummy ? (
          <div
            role="status"
            className="rounded-card border border-md-tertiary bg-md-tertiary-fixed p-3 text-body-sm text-md-on-tertiary-fixed-variant"
          >
            더미 모드 활성 — 실제 백엔드 연결 X. 운영자에게 문의해 더미 모드를 해제하면 본 폼이 활성화됩니다.
          </div>
        ) : null}

        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            handleSave();
          }}
        >
          {FIELDS.map((f) => (
            <label key={f.key} className="flex flex-col gap-1">
              <span className="text-label-caps text-md-on-surface-variant">
                {f.label}
              </span>
              <input
                type={f.type}
                value={(draft[f.key] as string | undefined) ?? ""}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, [f.key]: e.target.value }))
                }
                placeholder={f.placeholder}
                disabled={dummy}
                autoComplete="off"
                spellCheck={false}
                className="h-10 rounded-input border border-md-outline-variant bg-md-surface-container-lowest px-3 text-body-base text-md-on-surface outline-none transition-colors duration-[var(--motion-fast)] placeholder:text-md-on-surface-variant focus:border-md-primary disabled:opacity-50"
              />
              {f.hint ? (
                <span className="text-body-sm text-md-on-surface-variant">{f.hint}</span>
              ) : null}
            </label>
          ))}

          <DialogFooter>
            <DialogAction type="submit" disabled={dummy}>
              저장
            </DialogAction>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
