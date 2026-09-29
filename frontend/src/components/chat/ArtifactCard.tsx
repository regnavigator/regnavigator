"use client";

/**
 * ArtifactCard — 03 §5.3.
 *
 * 본 phase(P5+P6.1+P6.2+P6.3)에선 *시각만* — Turn 안에 자리 박는다. 클릭 동작
 * (`?docPath=` 셋)·Generating 배지·풀폭/max-w-md는 박지만, RightPanel ArtifactViewer는
 * P7. 본 phase 진행 데모용으로 path 클릭 시 URL만 셋한다.
 */

import { useCallback } from "react";
import type { Artifact } from "@/lib/store/types";
import { useRightPanel } from "@/lib/store/rightPanel";

type Props = {
  artifact: Artifact;
};

export function ArtifactCard({ artifact }: Props) {
  const { setDocPath, setOpen } = useRightPanel();

  const onClick = useCallback(() => {
    setDocPath(artifact.path);
    setOpen(true);
  }, [setDocPath, setOpen, artifact.path]);

  const icon = artifact.mime_type === "application/pdf" ? "description" : "article";
  const title = artifact.title || basename(artifact.path);

  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full max-w-md items-center gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-lowest px-3 py-2 text-left transition-colors duration-[var(--motion-fast)] hover:border-md-primary"
    >
      <span
        className="material-symbols-outlined text-[24px] text-md-on-surface-variant group-hover:text-md-primary"
        aria-hidden
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-body-sm font-semibold text-md-on-surface">
            {title}
          </span>
          {artifact.is_streaming ? (
            <span className="inline-flex items-center gap-1 rounded-pill bg-md-surface-container px-1.5 py-[1px] text-[10px] font-medium text-md-on-surface-variant">
              <span className="inline-block h-1.5 w-1.5 animate-md-pulse rounded-full bg-md-primary" />
              작성 중
            </span>
          ) : null}
        </div>
        <div className="text-[10px] text-md-on-surface-variant">
          {formatBytes(artifact.bytes)} · {formatTime(artifact.modified_at)}
        </div>
      </div>
    </button>
  );
}

function basename(path: string): string {
  const idx = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return idx >= 0 ? path.slice(idx + 1) : path;
}

function formatBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(ms: number): string {
  if (!ms) return "";
  const d = new Date(ms);
  return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}
