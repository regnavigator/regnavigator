"use client";

/**
 * Admin · 패치노트 발행 — backend `/admin/announcements` (2026-08-13).
 *
 * 발행하면 GET /announcements/latest 가 바뀌고, 사용자는 로그인 후 최초 접속 시
 * 안 본 노트만 팝업 1회로 본다("매일 개선한다"를 보여주는 창구). 배포 불필요 —
 * DB 기반이라 즉시 반영. 최근 20건 보관, 철회하면 이전 노트가 latest 로 복귀.
 */

import { useCallback, useEffect, useState } from "react";
import {
  deleteAnnouncement,
  setAnnouncementHidden,
  setAnnouncementPopup,
  listAnnouncements,
  publishAnnouncement,
  type Announcement,
} from "@/lib/client/admin";
import { ErrorBanner, formatTime } from "@/components/admin/common";
import { ANNOUNCEMENT_FEATURES } from "@/lib/client/quota";

export default function AdminAnnouncementsPage() {
  const [notes, setNotes] = useState<Announcement[]>([]);
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("");
  const [feature, setFeature] = useState("");
  // 로그인 팝업으로도 알릴지 — 끄면 게시판(/updates)에만 쌓인다(2026-09-18).
  const [withPopup, setWithPopup] = useState(true);
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setNotes(await listAnnouncements());
    } catch (err) {
      console.error("[admin/announcements] list failed", err);
      setError("목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function onPublish() {
    const items = body
      .split("\n")
      .map((l) => l.replace(/^[-•]\s*/, "").trim())
      .filter(Boolean);
    if (!title.trim() || !items.length) {
      setError("제목과 개선사항(줄바꿈으로 구분)을 입력해 주세요.");
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      await publishAnnouncement({
        title: title.trim(),
        items,
        version: version.trim() || undefined,
        feature: feature.trim() || undefined,
        popup: withPopup,
      });
      setTitle("");
      setVersion("");
      setFeature("");
      setBody("");
      await reload();
    } catch (err) {
      console.error("[admin/announcements] publish failed", err);
      setError("발행하지 못했습니다.");
    } finally {
      setPublishing(false);
    }
  }

  async function onTogglePopup(id: string, popup: boolean) {
    try {
      await setAnnouncementPopup(id, popup);
      await reload();
    } catch {
      setError("팝업 설정을 바꾸지 못했습니다.");
    }
  }

  async function onToggleHidden(id: string, hidden: boolean) {
    try {
      await setAnnouncementHidden(id, hidden);
      await reload();
    } catch (err) {
      console.error("[admin/announcements] hide failed", err);
      setError(hidden ? "숨기지 못했습니다." : "재노출하지 못했습니다.");
    }
  }

  async function onDelete(id: string) {
    if (!window.confirm("이 패치노트를 영구 삭제할까요? 잠깐 내리려면 [숨김]을 쓰세요.")) return;
    try {
      await deleteAnnouncement(id);
      await reload();
    } catch (err) {
      console.error("[admin/announcements] delete failed", err);
      setError("삭제하지 못했습니다.");
    }
  }

  return (
    <main className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-h1 text-md-on-surface">패치노트</h1>
        <p className="text-body-sm text-md-on-surface-variant">
          발행하면 사용자가 다음 접속 때 팝업으로 한 번 보고, 이후엔{" "}
          <a href="/updates" target="_blank" rel="noreferrer" className="underline">
            업데이트 내역
          </a>
          (공개 게시판, 키워드 검색)에 남습니다. 배포 후 그날 개선사항을 짧게 남기세요.
        </p>
      </header>

      <ErrorBanner message={error} />

      {/* 발행 폼 */}
      <section className="flex flex-col gap-3 rounded-card border border-md-outline-variant bg-md-surface p-4">
        <div className="flex gap-2">
          {/* 기능 영역(2026-09-07): 게시판은 기능 단위로 읽힌다 — 노트 하나 = 기능 하나의 변화 */}
          <select
            value={feature}
            onChange={(e) => setFeature(e.target.value)}
            aria-label="기능 영역"
            className="w-44 shrink-0 rounded border border-md-outline-variant bg-transparent px-2 py-2 text-body-sm text-md-on-surface focus:border-md-primary focus:outline-none"
          >
            <option value="">기능 영역 선택</option>
            {ANNOUNCEMENT_FEATURES.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          {/* 버전(선택, 2026-09-02): 주요 업데이트를 버전별로 남긴다 — 게시판·팝업 배지 */}
          <input
            type="text"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="버전(선택) 예: v0.8.0"
            maxLength={20}
            className="w-40 shrink-0 rounded border border-md-outline-variant bg-transparent px-3 py-2 font-mono text-body-sm text-md-on-surface placeholder:text-md-on-surface-variant/60 focus:border-md-primary focus:outline-none"
          />
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="제목 — 사용자가 할 수 있게 된 일. 예: 진행 중인 보고서를 중단할 수 있습니다"
            maxLength={120}
            className="min-w-0 flex-1 rounded border border-md-outline-variant bg-transparent px-3 py-2 text-body text-md-on-surface placeholder:text-md-on-surface-variant/60 focus:border-md-primary focus:outline-none"
          />
        </div>
        {/* 2026-09-02 사용자 피드백: "8월 4주 업데이트" 식 제목은 목록에서 내용을 알 수 없다.
            제목이 /updates 게시판·팝업의 첫 줄이자 검색 대상이므로 핵심 변경 1~3개를 담는다. */}
        <p className="-mt-1 text-[12px] leading-relaxed text-md-on-surface-variant">
          게시판(/updates)은 <b>기능 단위</b>로 읽힙니다(2026-09-07). 노트 하나에 기능 하나의
          변화만 담고, 기능 영역을 고르고, 제목은 &ldquo;무엇을 할 수 있게 됐는지&rdquo;를
          사용자 말로 적으세요. 본문은 어디서 어떻게 쓰는지 2~4줄. 내부 수정·디자인 정리·
          버그 픽스처럼 사용자가 알 필요 없는 내용은 적지 않습니다. 버전은 주요 릴리스만.
        </p>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          placeholder={[
            "어디서 어떻게 쓰는지 한 줄에 하나씩 —",
            "우측 패널의 진행 중 보고서 카드에 [중단] 버튼이 있습니다.",
            "중단한 보고서는 목록에서 삭제할 수 있습니다.",
          ].join("\n")}
          rows={5}
          className="rounded border border-md-outline-variant bg-transparent px-3 py-2 text-body-sm leading-relaxed text-md-on-surface placeholder:text-md-on-surface-variant/60 focus:border-md-primary focus:outline-none"
        />
        <div className="flex items-center justify-end gap-3">
          <label className="flex items-center gap-1.5 text-[12.5px] text-md-on-surface-variant">
            <input type="checkbox" checked={withPopup} onChange={(e) => setWithPopup(e.target.checked)} />
            로그인 팝업으로도 알림
          </label>
          <button
            type="button"
            onClick={() => void onPublish()}
            disabled={publishing}
            className="rounded-pill bg-md-primary px-4 py-1.5 text-[13px] font-medium text-md-on-primary transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {publishing ? "발행 중..." : "발행"}
          </button>
        </div>
      </section>

      {/* 발행 이력 */}
      <ul className="flex flex-col gap-3">
        {notes.map((n, idx) => (
          <li
            key={n.id}
            className="rounded-card border border-md-outline-variant bg-md-surface px-4 py-3"
          >
            <header className="mb-1.5 flex flex-wrap items-center gap-2">
              {n.feature ? (
                <span className="inline-flex items-center rounded-pill bg-md-primary-container px-2 py-0.5 text-[11px] font-semibold text-md-on-primary-container">
                  {n.feature}
                </span>
              ) : null}
              {n.version ? (
                <span className="inline-flex items-center rounded-pill bg-md-surface-container-high px-2 py-0.5 font-mono text-[11px] font-semibold text-md-on-surface">
                  {n.version}
                </span>
              ) : null}
              <span className="text-body font-semibold text-md-on-surface">
                {n.title}
              </span>
              {/* 팝업 후보는 **맨 위(가장 최근 발행) 1건뿐** — 숨김·팝업 끔이면 팝업 자체가 없다.
                  이전 노트로 내려가지 않는다(2026-09-18: 최신을 숨기자 옛 노트가 팝업된 사고). */}
              {idx === 0 && !n.hidden && n.popup !== false ? (
                <span className="inline-flex items-center rounded-pill bg-md-primary-fixed px-2 py-0.5 text-[11px] font-semibold text-md-on-primary-fixed-variant">
                  팝업 노출 중
                </span>
              ) : null}
              {n.hidden ? (
                <span className="inline-flex items-center rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant">
                  숨김 — 게시판·팝업 모두 안 보임
                </span>
              ) : n.popup === false ? (
                <span className="inline-flex items-center rounded-pill border border-md-outline-variant px-2 py-0.5 text-[11px] text-md-on-surface-variant">
                  게시판 전용
                </span>
              ) : null}
              <span className="text-[11.5px] text-md-on-surface-variant">
                {n.date}
                {n.created_at ? ` · ${formatTime(n.created_at)}` : ""}
                {n.created_by ? ` · ${n.created_by}` : ""}
              </span>
              <div className="ml-auto flex items-center gap-1">
                {!n.hidden ? (
                  <button
                    type="button"
                    onClick={() => void onTogglePopup(n.id, n.popup === false)}
                    title={n.popup === false ? "로그인 팝업으로도 알림(맨 위 노트일 때만 뜸)" : "팝업만 끄고 게시판에는 남김"}
                    className="rounded px-2 py-0.5 text-[12px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
                  >
                    {n.popup === false ? "팝업 켜기" : "팝업 끄기"}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => void onToggleHidden(n.id, !n.hidden)}
                  title={n.hidden ? "게시판에 다시 노출" : "게시판·팝업 모두에서 내림(기록은 남음)"}
                  className="rounded px-2 py-0.5 text-[12px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
                >
                  {n.hidden ? "재노출" : "숨김"}
                </button>
                <button
                  type="button"
                  onClick={() => void onDelete(n.id)}
                  title="영구 삭제 — 잠깐 내리려면 [숨김]"
                  className="rounded px-2 py-0.5 text-[12px] text-md-on-surface-variant transition-colors hover:bg-md-error-container hover:text-md-on-error-container"
                >
                  삭제
                </button>
              </div>
            </header>
            <ul className="list-disc pl-5 text-body-sm leading-relaxed text-md-on-surface">
              {n.items.map((it, i) => (
                <li key={i}>{it}</li>
              ))}
            </ul>
          </li>
        ))}
        {notes.length === 0 && !loading ? (
          <li className="rounded-card border border-md-outline-variant px-4 py-8 text-center text-md-on-surface-variant">
            발행된 패치노트가 없습니다.
          </li>
        ) : null}
      </ul>
    </main>
  );
}
