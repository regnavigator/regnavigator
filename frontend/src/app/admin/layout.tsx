"use client";

/**
 * Admin 공통 레이아웃 — is_admin 가드 + 탭 네비게이션 + 페이지 shell.
 *
 * 종전에는 7개 페이지가 가드·헤더 nav 를 각자 복붙했다(링크 그래프가 비대칭이라
 * beta 는 막다른 길이었다). 여기 한 곳으로 흡수:
 * - 가드: session(ADMIN_EMAILS) 또는 usage(backend) 둘 다 admin 아니면 / 로 redirect
 * - nav: next/link (prefetch·새 탭 가능) + 현재 페이지 하이라이트
 * - 기능별 권한(2026-09-22): GET /admin/me 로 권한 없는 탭은 숨기고, 주소로 직접 들어오면
 *   '권한 없음' 안내. 실제 차단은 backend(require_admin) — 화면 가드는 편의.
 * - 권한 미리보기(루트만): 고른 권한만 가진 관리자에게 보이는 탭·버튼으로 화면을 바꿔 본다.
 *   화면만 흉내 — 요청은 루트 권한으로 나가므로 실제 403 동작까지는 재현하지 않는다.
 *   탭 전환에도 유지(sessionStorage), 상단 배너 [종료]로 끈다.
 */

import { type ReactNode, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useUsage } from "@/lib/store/useUsage";
import {
  getAdminBuild,
  getAdminMe,
  type AdminBuildInfo,
  type AdminMe,
  type AdminPerm,
} from "@/lib/client/admin";
import { AdminPermsProvider, NoPermission } from "@/components/admin/admin-perms";

const PREVIEW_KEY = "admin.previewPerms";

// perm: null = 기능 권한과 무관하게 모든 관리자(운영 매뉴얼 — 2026-09-23).
const TABS: { href: string; label: string; perm: AdminPerm | null }[] = [
  { href: "/admin/stats", label: "통계", perm: "stats" },
  { href: "/admin/questions", label: "이용 조회", perm: "stats" },
  { href: "/admin/threads", label: "대화 원문", perm: "threads" },
  { href: "/admin/reviews", label: "답변 검수", perm: "threads" },
  { href: "/admin/reports", label: "보고서", perm: "reports" },
  { href: "/admin/users", label: "사용자", perm: "users" },
  { href: "/admin/beta", label: "베타 초대", perm: "beta" },
  { href: "/admin/feedback", label: "피드백", perm: "feedback" },
  { href: "/admin/pii", label: "PII 필터", perm: "pii" },
  { href: "/admin/newsletter", label: "뉴스레터", perm: "mail" },
  { href: "/admin/announcements", label: "패치노트", perm: "announcements" },
  { href: "/admin/report-notes", label: "보고 노트", perm: "announcements" },
  { href: "/admin/manual", label: "운영 매뉴얼", perm: null },
  { href: "/admin/settings", label: "설정", perm: "settings" },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { data: session } = useSession();
  const { usage } = useUsage();

  // is_admin 가드 — session 도착 전엔 대기, usage 로 비관리자 확정 시 redirect.
  useEffect(() => {
    if (!session) return;
    const sessionAdmin = !!(session.user as { isAdmin?: boolean }).isAdmin;
    if (sessionAdmin) return;
    if (usage && !usage.is_admin) router.replace("/");
  }, [session, usage, router]);

  // 배포 식별(2026-09-15, "배포 시기 헷갈림") — 헤더에 최종 배포 시각·커밋 표시.
  const [build, setBuild] = useState<AdminBuildInfo | null>(null);
  useEffect(() => {
    if (!usage?.is_admin) return;
    let alive = true;
    getAdminBuild()
      .then((b) => alive && setBuild(b))
      .catch(() => { /* 표시 전용 — 실패해도 관리자 화면은 뜬다 */ });
    return () => {
      alive = false;
    };
  }, [usage?.is_admin]);

  // 기능별 권한 — 실패하면 전 권한으로 간주(서버가 어차피 403 으로 막는다).
  const [me, setMe] = useState<AdminMe | null>(null);
  const [meLoaded, setMeLoaded] = useState(false);
  useEffect(() => {
    if (!usage?.is_admin) return;
    let alive = true;
    getAdminMe()
      .then((m) => alive && setMe(m))
      .catch(() => { /* 구버전 backend — 전 권한 간주 */ })
      .finally(() => alive && setMeLoaded(true));
    return () => {
      alive = false;
    };
  }, [usage?.is_admin]);
  const [previewPerms, setPreviewPermsState] = useState<AdminPerm[] | null>(null);
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(PREVIEW_KEY);
      if (raw) setPreviewPermsState(JSON.parse(raw) as AdminPerm[]);
    } catch {
      /* 무시 */
    }
  }, []);
  const setPreviewPerms = (p: AdminPerm[] | null) => {
    setPreviewPermsState(p);
    try {
      if (p) sessionStorage.setItem(PREVIEW_KEY, JSON.stringify(p));
      else sessionStorage.removeItem(PREVIEW_KEY);
    } catch {
      /* 무시 */
    }
  };
  // 미리보기는 루트만 — 루트가 아니면 저장값이 있어도 무시
  const previewing = !!me?.is_root && previewPerms !== null;
  const effectivePerms = previewing ? previewPerms! : me?.perms;
  const can = (p: AdminPerm | null) =>
    p === null || (effectivePerms ? effectivePerms.includes(p) : true);
  const [pickerOpen, setPickerOpen] = useState(false);
  const tabs = TABS.filter((t) => can(t.perm));
  const current = TABS.find((t) => pathname === t.href || pathname.startsWith(`${t.href}/`));

  // /admin 루트 → 권한 있는 첫 탭으로(기본 /admin/stats 가 막힌 관리자용)
  const blockedHere = !!current && !can(current.perm);
  const firstHref = tabs[0]?.href;
  useEffect(() => {
    if (!meLoaded || !me) return;
    if (blockedHere && firstHref && pathname === "/admin/stats") router.replace(firstHref);
  }, [meLoaded, me, blockedHere, firstHref, pathname, router]);

  if (usage && !usage.is_admin) return null; // redirect 대기

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1200px] flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
      <nav
        aria-label="관리자 메뉴"
        className="flex flex-wrap items-center gap-1.5 border-b border-md-outline-variant pb-3"
      >
        <span className="mr-2 text-label-caps text-md-on-surface-variant">
          Admin
        </span>
        {tabs.map((t) => {
          const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
          return (
            <Link
              key={t.href}
              href={t.href}
              aria-current={active ? "page" : undefined}
              className={`rounded-pill px-3 py-1.5 text-[13px] font-medium transition-colors ${
                active
                  ? "bg-md-primary text-md-on-primary"
                  : "text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
        <Link
          href="/"
          className="ml-auto rounded-pill px-3 py-1.5 text-[13px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container-low hover:text-md-on-surface"
        >
          ← 채팅으로
        </Link>
        {build ? (
          <span
            className="w-full pt-1 text-[11px] text-md-on-surface-variant"
            title={`이미지 빌드 ${build.built_at ?? "unknown"} · 프로세스 기동 ${build.started_at} · 프롬프트 ${build.prompt_version}`}
          >
            최종 배포 {fmtBuild(build.built_at ?? build.started_at)} · 커밋{" "}
            <code className="font-mono">{build.git_sha}</code> · 프롬프트 {build.prompt_version}
          </span>
        ) : null}
      </nav>
      {me?.is_root ? (
        <PreviewBar
          catalog={me.catalog}
          previewPerms={previewing ? previewPerms : null}
          open={pickerOpen}
          setOpen={setPickerOpen}
          onApply={(p) => {
            setPreviewPerms(p);
            setPickerOpen(false);
          }}
        />
      ) : null}
      <AdminPermsProvider
        value={{
          me,
          loaded: meLoaded,
          can,
          isRoot: !!me?.is_root && !previewing,
          previewPerms: previewing ? previewPerms : null,
          setPreviewPerms,
        }}
      >
        {current && !can(current.perm) ? (
          <NoPermission
            label={me?.catalog.find((c) => c.key === current.perm)?.label ?? current.label}
          />
        ) : (
          children
        )}
      </AdminPermsProvider>
    </div>
  );
}


/** ISO → "2026-09-15 14:02 KST" (표시 전용) */
function fmtBuild(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const kst = new Date(d.getTime() + 9 * 3600 * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${kst.getUTCFullYear()}-${p(kst.getUTCMonth() + 1)}-${p(kst.getUTCDate())} ${p(kst.getUTCHours())}:${p(kst.getUTCMinutes())} KST`;
}


/** 권한 미리보기 막대(루트만) — 꺼져 있으면 작은 버튼, 켜져 있으면 눈에 띄는 배너. */
function PreviewBar({
  catalog,
  previewPerms,
  open,
  setOpen,
  onApply,
}: {
  catalog: AdminMe["catalog"];
  previewPerms: AdminPerm[] | null;
  open: boolean;
  setOpen: (v: boolean) => void;
  onApply: (p: AdminPerm[] | null) => void;
}) {
  const [draft, setDraft] = useState<Set<AdminPerm>>(new Set(previewPerms ?? []));
  useEffect(() => {
    if (open) setDraft(new Set(previewPerms ?? []));
  }, [open, previewPerms]);
  const labels = (previewPerms ?? []).map((k) => catalog.find((c) => c.key === k)?.label ?? k);

  return (
    <div className="-mt-3 flex flex-col gap-2">
      {previewPerms ? (
        <div
          role="status"
          className="flex flex-wrap items-center gap-2 rounded-card border-2 border-dashed border-md-primary bg-md-primary-fixed px-4 py-2 text-[12.5px] text-md-on-surface"
        >
          <span className="material-symbols-outlined text-[18px] text-md-primary" aria-hidden>
            visibility
          </span>
          <b className="font-semibold">권한 미리보기</b>
          <span>{labels.length ? labels.join(" · ") : "권한 없음"} — 이 권한만 받은 관리자에게 보이는 화면입니다.</span>
          <span className="text-md-on-surface-variant">(화면만 흉내 · 요청은 루트 권한으로 나감)</span>
          <span className="ml-auto flex gap-2">
            <button
              type="button"
              onClick={() => setOpen(!open)}
              className="rounded-pill border border-md-outline-variant bg-md-surface px-3 py-1 text-[12px] hover:bg-md-surface-container-low"
            >
              권한 바꾸기
            </button>
            <button
              type="button"
              onClick={() => onApply(null)}
              className="rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary"
            >
              미리보기 종료
            </button>
          </span>
        </div>
      ) : (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="inline-flex items-center gap-1 rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface-variant hover:bg-md-surface-container-low hover:text-md-on-surface"
            title="특정 권한만 받은 관리자에게 관리자 페이지가 어떻게 보이는지 확인"
          >
            <span className="material-symbols-outlined text-[15px]" aria-hidden>
              visibility
            </span>
            권한별 화면 미리보기
          </button>
        </div>
      )}
      {open ? (
        <div className="flex flex-col gap-2 rounded-card border border-md-outline-variant bg-md-surface px-4 py-3">
          <p className="text-[12.5px] text-md-on-surface-variant">볼 권한을 고르세요(아무것도 안 고르면 ‘권한 없음’ 관리자 화면).</p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {catalog.map((c) => (
              <label key={c.key} className="flex items-start gap-2 text-body-sm" title={c.desc}>
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={draft.has(c.key)}
                  onChange={() =>
                    setDraft((prev) => {
                      const next = new Set(prev);
                      if (next.has(c.key)) next.delete(c.key);
                      else next.add(c.key);
                      return next;
                    })
                  }
                />
                <span>
                  {c.label}
                  <span className="ml-1.5 text-[11.5px] text-md-on-surface-variant">{c.desc}</span>
                </span>
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] hover:bg-md-surface-container-low"
            >
              취소
            </button>
            <button
              type="button"
              onClick={() => onApply(catalog.filter((c) => draft.has(c.key)).map((c) => c.key))}
              className="rounded-pill bg-md-primary px-3 py-1 text-[12px] font-semibold text-md-on-primary"
            >
              이 권한으로 보기
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
