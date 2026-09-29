"use client";

/**
 * PrivacyDialog — 정보주체 권리 화면 (개인정보보호법 제35·36·37조).
 *
 * - 내 데이터 보기: `GET /me/data` — 보관 데이터·보유기간·국외이전 수령자
 * - 계정 삭제 요청: `POST /me/erase` — 접수 후 운영자 파기(즉시 파기 아님),
 *   완료 시 이메일 통지. 2단계 확인(펼침 → 확정)으로 오클릭 방지.
 *
 * 개인정보처리방침이 약속한 "열람·삭제·동의 철회"의 실제 진입점 — UI 없이
 * 방침에만 적으면 허위 고지가 된다. 연동: medi-back `docs/frontend_legal_handoff.md` §5.
 */

import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { signOut } from "next-auth/react";
import {
  getMyData,
  requestErasure,
  withdrawAccount,
  type MyData,
  getConsentStatus,
  giveConsent,
} from "@/lib/client/privacy";
import { getMyProfile, putMyProfile } from "@/lib/client/profile";
import { getMyPrefs, setNoticeEmailOptIn } from "@/lib/client/prefs";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function PrivacyDialog({ open, onOpenChange }: Props) {
  const [data, setData] = useState<MyData | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [eraseOpen, setEraseOpen] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // 프로필 편집(2026-08-14) — 8/10 이전 가입자는 온보딩 자동 제출을 못 거쳐
  // 프로필이 비어 있다. 여기가 기존 가입자의 유일한 입력 경로.
  const [profile, setProfile] = useState({
    display_name: "",
    affiliation: "",
    job_role: "",
  });
  const [profileSaving, setProfileSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setData(null);
    setLoadError(false);
    setEraseOpen(false);
    setWithdrawOpen(false);
    setReason("");
    getMyData()
      .then(setData)
      .catch((err) => {
        console.error("[privacy] 내 데이터 조회 실패", err);
        setLoadError(true);
      });
    getMyProfile()
      .then((p) =>
        setProfile({
          display_name: p.display_name ?? "",
          affiliation: p.affiliation ?? "",
          job_role: p.job_role ?? "",
        }),
      )
      .catch((err) => console.warn("[privacy] 프로필 조회 실패", err));
  }, [open]);

  async function onSaveProfile() {
    if (profileSaving) return;
    setProfileSaving(true);
    try {
      await putMyProfile({
        display_name: profile.display_name.trim() || null,
        affiliation: profile.affiliation.trim() || null,
        job_role: profile.job_role.trim() || null,
      });
      toast.success("프로필이 저장됐습니다");
    } catch (err) {
      console.error("[privacy] 프로필 저장 실패", err);
      toast.error("프로필 저장에 실패했습니다", {
        description: "잠시 후 다시 시도해주세요.",
      });
    } finally {
      setProfileSaving(false);
    }
  }

  async function onErase() {
    if (submitting) return;
    setSubmitting(true);
    try {
      const res = await requestErasure(reason.trim() || undefined);
      toast.success("삭제 요청이 접수되었습니다", { description: res.note });
      onOpenChange(false);
    } catch (err) {
      console.error("[privacy] 삭제 요청 실패", err);
      toast.error("삭제 요청 처리에 실패했습니다", {
        description: "잠시 후 다시 시도해주세요.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function onWithdraw() {
    if (submitting) return;
    setSubmitting(true);
    try {
      await withdrawAccount(reason.trim() || undefined);
      toast.success("탈퇴 처리됐습니다", { description: "로그아웃됩니다." });
      // 소프트삭제 즉시 반영 — 세션 종료. 재로그인 시 백엔드가 403 차단.
      await signOut({ callbackUrl: "/landing" });
    } catch (err) {
      console.error("[privacy] 회원탈퇴 실패", err);
      toast.error("회원탈퇴 처리에 실패했습니다", {
        description: "잠시 후 다시 시도해주세요.",
      });
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto border-md-outline-variant bg-md-surface text-md-on-surface sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-h2 text-md-on-surface">
            내 데이터·개인정보
          </DialogTitle>
          <DialogDescription className="text-body-sm text-md-on-surface-variant">
            보관 중인 내 데이터를 확인하고, 삭제(동의 철회)를 요청할 수 있습니다.
          </DialogDescription>
        </DialogHeader>

        {loadError ? (
          <div className="rounded-card border border-md-outline-variant bg-md-surface-container-low p-4 text-body-sm text-md-on-surface-variant">
            데이터를 불러오지 못했습니다. 잠시 후 다시 열어주세요.
          </div>
        ) : !data ? (
          <div className="flex items-center gap-2 py-6 text-body-sm text-md-on-surface-variant">
            <span
              className="material-symbols-outlined animate-spin text-[18px]"
              aria-hidden
            >
              progress_activity
            </span>
            불러오는 중…
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            {/* 계정 */}
            <section className="flex flex-col gap-1.5">
              <h3 className="text-label-caps text-md-on-surface-variant">계정</h3>
              <div className="rounded-card border border-md-outline-variant px-4 py-3 text-[13px] leading-relaxed">
                <p className="font-medium text-md-on-surface">
                  {data.user.email ?? data.user.id}
                </p>
                {data.user.created_at ? (
                  <p className="text-md-on-surface-variant">
                    가입일 {data.user.created_at.slice(0, 10)}
                  </p>
                ) : null}
                {data.consent?.agreed_at ? (
                  <p className="text-md-on-surface-variant">
                    동의 {data.consent.version ?? "-"} 버전 ·{" "}
                    {data.consent.agreed_at.slice(0, 10)} ·{" "}
                    {data.consent.scopes.join(", ")}
                  </p>
                ) : (
                  <p className="text-md-on-surface-variant">동의 기록 없음</p>
                )}
              </div>
            </section>

            {/* 메일 수신(2026-08-28) — 마케팅 동의를 가입 후에도 켜고 끌 수
                있는 유일한 화면("추후 설정하는 화면 있음?" — 없었다). 동의
                기록은 legal_consent 이벤트로 추가 적재(최신 기록이 정본). */}
            <section className="flex flex-col gap-1.5">
              <h3 className="text-label-caps text-md-on-surface-variant">메일 수신</h3>
              <div className="flex flex-col gap-3 rounded-card border border-md-outline-variant px-4 py-3">
                <NoticeMailOptRow />
                <div className="border-t border-md-outline-variant/60 pt-3">
                  <MarketingOptRow />
                </div>
              </div>
            </section>

            {/* 프로필 — 표시명·소속·직군 (admin 이용조회 표시·맞춤 서비스 재료) */}
            <section className="flex flex-col gap-1.5">
              <h3 className="text-label-caps text-md-on-surface-variant">프로필</h3>
              <div className="flex flex-col gap-2.5 rounded-card border border-md-outline-variant px-4 py-3">
                {(
                  [
                    ["display_name", "이름", "예: 홍길동"],
                    ["affiliation", "소속", "예: ○○병원 / ○○메디컬"],
                    ["job_role", "직군", "예: 의사 / RA·QA / 컨설턴트"],
                  ] as const
                ).map(([key, label, ph]) => (
                  <label key={key} className="flex items-center gap-3 text-[13px]">
                    <span className="w-[48px] shrink-0 text-md-on-surface-variant">
                      {label}
                    </span>
                    <input
                      type="text"
                      value={profile[key]}
                      maxLength={60}
                      onChange={(e) =>
                        setProfile((p) => ({ ...p, [key]: e.target.value }))
                      }
                      placeholder={ph}
                      className="h-8 min-w-0 flex-1 rounded-input border border-md-outline-variant bg-md-surface px-2.5 text-[13px] text-md-on-surface outline-none placeholder:text-md-on-surface-variant/60 focus:border-md-primary"
                    />
                  </label>
                ))}
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => void onSaveProfile()}
                    disabled={profileSaving}
                    className="inline-flex h-8 items-center rounded-full bg-md-primary px-4 text-[12.5px] font-medium text-md-on-primary transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    {profileSaving ? "저장 중…" : "프로필 저장"}
                  </button>
                </div>
              </div>
            </section>

            {/* 보유기간 */}
            <section className="flex flex-col gap-1.5">
              <h3 className="text-label-caps text-md-on-surface-variant">
                데이터 보유기간
              </h3>
              <dl className="flex flex-col divide-y divide-md-outline-variant rounded-card border border-md-outline-variant text-[13px]">
                {Object.entries(data.retention ?? {}).map(([k, v]) => (
                  <div key={k} className="flex flex-col gap-0.5 px-4 py-2.5 sm:flex-row sm:gap-3">
                    <dt className="shrink-0 font-medium text-md-on-surface sm:w-[140px]">
                      {k}
                    </dt>
                    <dd className="text-md-on-surface-variant">{v}</dd>
                  </div>
                ))}
              </dl>
            </section>

            {/* 국외이전 */}
            <section className="flex flex-col gap-1.5">
              <h3 className="text-label-caps text-md-on-surface-variant">
                국외 이전 수령자
              </h3>
              <p className="text-[13px] leading-relaxed text-md-on-surface-variant">
                AI 답변 생성을 위해 질의 내용이 다음 사업자에게 전송될 수 있습니다:{" "}
                <span className="text-md-on-surface">
                  {(data.국외이전 ?? []).join(" · ")}
                </span>
                <br />
                상세는{" "}
                <a
                  href="/privacy"
                  target="_blank"
                  className="font-medium text-md-primary underline-offset-2 hover:underline"
                >
                  개인정보처리방침
                </a>
                을 참조하세요.
              </p>
            </section>

            {/* 회원탈퇴 — 소프트삭제(즉시 로그아웃, 데이터는 보존 정책대로) */}
            <section className="flex flex-col gap-2 border-t border-md-outline-variant pt-4">
              <h3 className="text-label-caps text-md-on-surface-variant">회원탈퇴</h3>
              {!withdrawOpen ? (
                <button
                  type="button"
                  onClick={() => setWithdrawOpen(true)}
                  className="inline-flex h-9 w-fit items-center gap-1.5 rounded-full border border-md-outline-variant px-4 text-[13px] font-medium text-md-on-surface-variant transition-colors hover:bg-md-surface-container hover:text-md-on-surface"
                >
                  <span className="material-symbols-outlined text-[16px]" aria-hidden>
                    logout
                  </span>
                  회원탈퇴
                </button>
              ) : (
                <div className="flex flex-col gap-3 rounded-card border border-md-outline-variant bg-md-surface-container-low p-4">
                  <p className="text-[13px] leading-relaxed text-md-on-surface">
                    탈퇴하면 <strong>즉시 로그아웃되고 계정 이용이 중단</strong>됩니다.
                    대화·보고서 데이터는 보유기간 동안 보관되며(위 안내 참조), 재로그인은
                    제한됩니다. 다시 이용하려면 운영팀에 문의해주세요. 데이터의{" "}
                    <strong>완전 파기</strong>를 원하시면 아래 “계정 삭제 요청”을 이용하세요.
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void onWithdraw()}
                      disabled={submitting}
                      className="inline-flex h-9 items-center gap-1.5 rounded-full bg-md-on-surface px-4 text-[13px] font-semibold text-md-surface transition-opacity disabled:opacity-50"
                    >
                      {submitting ? (
                        <span
                          className="material-symbols-outlined animate-spin text-[15px]"
                          aria-hidden
                        >
                          progress_activity
                        </span>
                      ) : null}
                      탈퇴하기
                    </button>
                    <button
                      type="button"
                      onClick={() => setWithdrawOpen(false)}
                      disabled={submitting}
                      className="inline-flex h-9 items-center rounded-full border border-md-outline-variant px-4 text-[13px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container"
                    >
                      취소
                    </button>
                  </div>
                </div>
              )}
            </section>

            {/* 삭제 요청 — danger zone */}
            <section className="flex flex-col gap-2 border-t border-md-outline-variant pt-4">
              <h3 className="text-label-caps text-md-error">계정 삭제</h3>
              {!eraseOpen ? (
                <button
                  type="button"
                  onClick={() => setEraseOpen(true)}
                  className="inline-flex h-9 w-fit items-center gap-1.5 rounded-full border border-md-error px-4 text-[13px] font-medium text-md-error transition-colors hover:bg-md-error-container/30"
                >
                  <span className="material-symbols-outlined text-[16px]" aria-hidden>
                    delete_forever
                  </span>
                  계정 삭제 요청
                </button>
              ) : (
                <div className="flex flex-col gap-3 rounded-card border border-md-error/40 bg-md-error-container/20 p-4">
                  <p className="text-[13px] leading-relaxed text-md-on-surface">
                    삭제를 요청하면 대화·보고서·계정 정보의 파기가 접수됩니다.
                    <strong> 즉시 삭제되지 않으며</strong>, 지체 없이 처리 후 완료 시
                    이메일로 통지됩니다. 이 작업은 되돌릴 수 없습니다.
                  </p>
                  <textarea
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="사유 (선택)"
                    rows={2}
                    className="rounded-input border border-md-outline-variant bg-md-surface px-3 py-2 text-[13px] text-md-on-surface outline-none placeholder:text-md-on-surface-variant focus:border-md-primary"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void onErase()}
                      disabled={submitting}
                      className="inline-flex h-9 items-center gap-1.5 rounded-full bg-md-error px-4 text-[13px] font-semibold text-md-on-error transition-opacity disabled:opacity-50"
                    >
                      {submitting ? (
                        <span
                          className="material-symbols-outlined animate-spin text-[15px]"
                          aria-hidden
                        >
                          progress_activity
                        </span>
                      ) : null}
                      삭제 요청 확정
                    </button>
                    <button
                      type="button"
                      onClick={() => setEraseOpen(false)}
                      disabled={submitting}
                      className="inline-flex h-9 items-center rounded-full border border-md-outline-variant px-4 text-[13px] text-md-on-surface-variant transition-colors hover:bg-md-surface-container"
                    >
                      취소
                    </button>
                  </div>
                </div>
              )}
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}


/** 서비스 안내 메일 수신 토글(2026-09-10 도입→철회→09-14 재도입).
 *
 * 왜 필요한가: 안내 메일(기능 추가 고지 등)의 푸터가 "설정에서 변경"이라 안내하는데
 * 이 토글이 없으면 그대로 따라해도 끌 수 없다 — 허위 안내이자 정보통신망법 §50④
 * (수신거부 방법 제공) 문제. 발송 경로(`/admin/notify`)가 이 값을 실제로 존중한다
 * (`notices.filter_notice_optout`).
 */
function NoticeMailOptRow() {
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => {
    void getMyPrefs()
      .then((p) => setOn(p.notice_email_opt_in ?? true))
      .catch(() => setOn(null));
  }, []);
  if (on === null) {
    return (
      <p className="text-[12.5px] text-md-on-surface-variant">
        수신 설정을 불러오지 못했어요.
      </p>
    );
  }
  return (
    <label className="flex cursor-pointer items-start gap-2.5">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => {
          const v = e.target.checked;
          setOn(v);
          void setNoticeEmailOptIn(v)
            .then(() =>
              toast.success(
                v
                  ? "서비스 안내 메일을 받습니다"
                  : "서비스 안내 메일 수신을 끕니다",
              ),
            )
            .catch(() => {
              setOn(!v);
              toast.error("설정 저장에 실패했어요.");
            });
        }}
        className="mt-0.5 size-4 shrink-0 accent-md-primary"
      />
      <span className="text-[12.5px] leading-relaxed text-md-on-surface-variant">
        <b className="text-md-on-surface">서비스 안내 메일</b> — 새 기능·변경 사항
        안내를 받습니다. 끄면 안내 메일이 발송되지 않습니다(보안·장애 등 필수
        운영 공지는 계속 발송됩니다).
      </span>
    </label>
  );
}

/** 마케팅(제품 소식·업데이트) 수신 토글 — /me/consent 재적재로 변경. */
function MarketingOptRow() {
  const [state, setState] = useState<{
    on: boolean;
    version: string;
    scopes: string[];
  } | null>(null);
  useEffect(() => {
    void getConsentStatus()
      .then((c) =>
        setState({
          on: c.agreed_scopes.includes("marketing"),
          version: c.current_version,
          scopes: c.agreed_scopes,
        }),
      )
      .catch(() => setState(null));
  }, []);
  if (!state) {
    return (
      <p className="text-[12.5px] text-md-on-surface-variant">
        동의 정보를 불러오지 못했어요.
      </p>
    );
  }
  return (
    <label className="flex cursor-pointer items-start gap-2.5">
      <input
        type="checkbox"
        checked={state.on}
        onChange={(e) => {
          const v = e.target.checked;
          const base = state.scopes.filter((sc) => sc !== "marketing");
          const next = v ? [...base, "marketing"] : base;
          setState({ ...state, on: v });
          void giveConsent(next as ("terms" | "transfer" | "marketing")[], state.version)
            .then(() =>
              toast.success(
                v ? "제품 소식·업데이트 메일을 받습니다" : "마케팅 메일 수신을 끕니다",
              ),
            )
            .catch(() => {
              setState({ ...state, on: !v });
              toast.error("설정 저장에 실패했어요.");
            });
        }}
        className="mt-0.5 size-4 shrink-0 accent-md-primary"
      />
      <span className="text-[12.5px] leading-relaxed text-md-on-surface-variant">
        <b className="text-md-on-surface">[선택]</b> 제품 소식·업데이트 등 마케팅
        메일 수신에 동의합니다. 서비스 이용 안내(보고서 완료·보안 공지 등)는 이
        설정과 무관하게 발송됩니다.
      </span>
    </label>
  );
}
