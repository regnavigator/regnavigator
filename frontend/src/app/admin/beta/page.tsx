"use client";

/**
 * Admin · 베타 관리 — 화이트리스트 + 테스트 계정 (2026-07-16).
 *
 * 1) 화이트리스트: backend `/admin/whitelist` (env=읽기전용 배지, DB=삭제 가능).
 *    CSV/줄바꿈 여러 건 한 번에 추가 (`entries` 벌크).
 * 2) 테스트 계정: `/api/admin/test-accounts` (front route, prisma) —
 *    매직링크 인증 생략 즉시 생성 + 화이트리스트 자동 등록 / 삭제.
 *
 * BETA_GATE=1 이면 화이트리스트 외 가입·사용 전면 차단(ADMIN 제외).
 */

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { apiFetch } from "@/lib/api/client";
import {
  getInviteTemplate,
  getWhitelist,
  previewInviteTemplate,
  testInviteTemplate,
  removeWhitelistEntry,
  resetInviteTemplate,
  saveInviteTemplate,
  sendWhitelistInvite,
  type InviteTemplate,
  type WhitelistEntry,
  type WhitelistState,
} from "@/lib/client/admin";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useConfirm } from "@/components/admin/use-confirm";

/** 도메인 항목(@company.com)은 수신자가 없어 초대를 보낼 수 없다. */
const isMailable = (entry: string) => entry.includes("@") && !entry.startsWith("@");

type InviteFilter = "all" | "pending" | "sent";

function fmtDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

export default function AdminBetaPage() {
  const { confirm, confirmDialog } = useConfirm();
  const [wl, setWl] = useState<WhitelistState | null>(null);
  const [csv, setCsv] = useState("");
  const [busy, setBusy] = useState(false);
  const [inviteFilter, setInviteFilter] = useState<InviteFilter>("all");
  /** 발송 중인 항목 — 같은 버튼 연타로 두 통 나가는 걸 막는다. */
  const [inviting, setInviting] = useState<string | null>(null);
  // 초대 메일 내용 편집(2026-08-28) — 보내기 전에 내용을 보고 고칠 수 있어야 한다.
  const [tpl, setTpl] = useState<InviteTemplate | null>(null);
  const [tplOpen, setTplOpen] = useState(false);
  const [tplSubject, setTplSubject] = useState("");
  const [tplBody, setTplBody] = useState("");
  const [tplBusy, setTplBusy] = useState(false);
  /** 렌더된 메일 HTML — null 이면 편집 뷰. srcDoc iframe 으로 격리 표시. */
  const [tplPreview, setTplPreview] = useState<string | null>(null);

  const showPreview = async () => {
    if (tplPreview !== null) { setTplPreview(null); return; }
    try {
      const r = await previewInviteTemplate(tplSubject, tplBody);
      setTplPreview(r.html);
    } catch { toast.error("미리보기 생성 실패"); }
  };

  const sendTest = async () => {
    setTplBusy(true);
    try {
      const r = await testInviteTemplate(tplSubject, tplBody);
      toast.success(`${r.to} 로 테스트 발송됨 (제목에 [테스트] 표시)`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "테스트 발송 실패");
    } finally { setTplBusy(false); }
  };

  const openTpl = async () => {
    setTplOpen(true);
    setTplPreview(null);
    try {
      const t = await getInviteTemplate();
      setTpl(t); setTplSubject(t.subject); setTplBody(t.body);
    } catch { toast.error("초대 메일 내용을 불러오지 못했습니다."); }
  };

  const saveTpl = async () => {
    if (!tplSubject.trim() || !tplBody.trim()) {
      toast.error("제목과 본문을 모두 입력하세요."); return;
    }
    setTplBusy(true);
    try {
      const t = await saveInviteTemplate(tplSubject.trim(), tplBody.trim());
      setTpl(t); toast.success("저장됨 — 다음 발송부터 이 내용으로 나갑니다.");
      setTplOpen(false);
    } catch { toast.error("저장 실패"); } finally { setTplBusy(false); }
  };

  const resetTpl = async () => {
    const ok = await confirm({
      title: "기본 문구로 복원할까요?",
      description: "수정본을 폐기하고 기본 초대 문구로 되돌립니다.",
      confirmLabel: "복원",
    });
    if (!ok) return;
    setTplBusy(true);
    try {
      const t = await resetInviteTemplate();
      setTpl(t); setTplSubject(t.subject); setTplBody(t.body);
      toast.success("기본 문구로 복원됨");
    } catch { toast.error("복원 실패"); } finally { setTplBusy(false); }
  };
  // 테스트 계정 폼
  const [accEmail, setAccEmail] = useState("");
  const [accPw, setAccPw] = useState("");
  const [accName, setAccName] = useState("");

  const reload = useCallback(async () => {
    try {
      setWl(await getWhitelist());
    } catch (err) {
      console.error("[admin/beta] whitelist load failed", err);
      toast.error("화이트리스트를 불러오지 못했습니다.");
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);

  const addEntries = async () => {
    if (!csv.trim()) return;
    setBusy(true);
    try {
      // backend 가 중복 사유를 3종으로 구분해 준다(2026-08-01) — 종전엔 이미
      // 있던 항목도 added 로 와서 "100건 추가"처럼 실제 반영 수를 알 수 없었다.
      const res = await apiFetch<{
        added: string[];
        duplicate?: string[];
        already_in_env?: string[];
        covered_by_domain?: string[];
        invalid: string[];
      }>("/admin/whitelist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entries: csv }),
      });
      const skipped = [
        res.duplicate?.length ? `이미 등록 ${res.duplicate.length}건` : null,
        res.already_in_env?.length
          ? `.env 로 이미 허용 ${res.already_in_env.length}건`
          : null,
        res.covered_by_domain?.length
          ? `도메인이 이미 커버 ${res.covered_by_domain.length}건`
          : null,
        res.invalid.length ? `형식 오류 ${res.invalid.length}건` : null,
      ].filter(Boolean);
      toast.success(`${res.added.length}건 추가`, {
        description: skipped.length ? `건너뜀 — ${skipped.join(" · ")}` : undefined,
        duration: skipped.length ? 8000 : 4000,
      });
      setCsv("");
      await reload();
    } catch (err) {
      console.error("[admin/beta] add failed", err);
      toast.error("추가 실패 — 형식(a@b.com 또는 @domain.com)을 확인하세요.");
    } finally {
      setBusy(false);
    }
  };

  const sendInvite = async (row: WhitelistEntry) => {
    const already = !!row.invited_at;
    if (already) {
      const ok = await confirm({
        title: "초대를 다시 보낼까요?",
        description: `${row.entry} 에는 이미 초대를 보냈습니다 (${fmtDate(row.invited_at)}).`,
        confirmLabel: "재발송",
      });
      if (!ok) return;
    }
    setInviting(row.entry);
    try {
      const res = await sendWhitelistInvite(row.entry);
      toast.success(res.resent ? `${row.entry} 재발송 완료` : `${row.entry} 초대 발송`);
      await reload();
    } catch (err) {
      // 발송 실패는 502 로 올라오고 백엔드가 invited_at 을 찍지 않는다 —
      // 안 간 메일을 '발송완료'로 보이게 두면 그 사람은 영영 초대받지 못한다.
      console.error("[admin/beta] invite failed", err);
      toast.error(
        err instanceof Error ? `발송 실패 — ${err.message}` : "발송 실패",
        { duration: 8000 },
      );
    } finally {
      setInviting(null);
    }
  };

  const removeEntry = async (entry: string) => {
    const ok = await confirm({
      title: "화이트리스트에서 제거할까요?",
      description: `'${entry}' 은(는) 즉시 접근이 차단됩니다(기발급 JWT 포함).`,
      confirmLabel: "제거",
      danger: true,
    });
    if (!ok) return;
    try {
      await removeWhitelistEntry(entry);
      toast.success(`${entry} 제거됨`);
      await reload();
    } catch {
      toast.error("제거 실패");
    }
  };

  const createAccount = async () => {
    setBusy(true);
    try {
      const res = await fetch("/api/admin/test-accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: accEmail, password: accPw, name: accName }),
      });
      const data = (await res.json()) as { error?: string; whitelisted?: boolean };
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      toast.success(
        `계정 생성: ${accEmail}` +
          (data.whitelisted ? " (화이트리스트 자동 등록)" : ""),
      );
      setAccEmail("");
      setAccPw("");
      setAccName("");
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "계정 생성 실패");
    } finally {
      setBusy(false);
    }
  };

  const deleteAccount = async (email: string) => {
    const ok = await confirm({
      title: "계정을 삭제할까요?",
      description: `${email} — 로그인 불가 + 화이트리스트에서도 제거됩니다.`,
      confirmLabel: "삭제",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const res = await fetch("/api/admin/test-accounts", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      toast.success(`계정 삭제: ${email}`);
      await reload();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "계정 삭제 실패");
    } finally {
      setBusy(false);
    }
  };

  // 발송 대상은 이메일 항목뿐 — @도메인은 수신자가 없어 집계에서 뺀다.
  const rows = wl?.db_entries ?? [];
  const mailable = rows.filter((r) => isMailable(r.entry));
  const invited = mailable.filter((r) => !!r.invited_at);
  // "미발송" = 아직 보내야 할 사람. **이미 가입해 쓰고 있는 사람은 뺀다** —
  // 발송 이력이 없다는 이유로 작업 목록에 올라오면 결국 눌러서 보내게 된다
  // (이 화면이 생기기 전에 공지를 받은 사람이 여기 전부 들어온다).
  // 그들은 '전체'에서 가입완료 배지와 함께 보이고, 보내려면 확인을 거친다.
  const pending = mailable.filter((r) => !r.invited_at && !r.joined_at);
  const visibleRows =
    inviteFilter === "pending" ? pending : inviteFilter === "sent" ? invited : rows;

  return (
    <main className="flex max-w-[880px] flex-col">
      <h1 className="text-h1 text-md-on-surface">베타 초대</h1>
      <p className="mt-1 text-body-sm text-md-on-surface-variant">
        게이트 상태:{" "}
        {wl ? (
          wl.gate_active ? (
            <span className="font-semibold text-md-success">활성 — 화이트리스트만 가입/사용 가능</span>
          ) : (
            <span className="font-semibold text-md-error">비활성 — 전면 허용 중 (BETA_GATE 미설정)</span>
          )
        ) : (
          "확인 중…"
        )}
      </p>

      {/* ── 화이트리스트 ── */}
      <section className="mt-8">
        <h2 className="text-h3 text-md-on-surface">화이트리스트</h2>
        <p className="mt-1 text-body-sm text-md-on-surface-variant">
          이메일(a@b.com) 또는 도메인(@company.com). 쉼표·줄바꿈으로 여러 건 붙여넣기 가능.
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <textarea
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
            placeholder={"tester1@example.com, tester2@example.com\n@partner-company.com"}
            rows={3}
            className="min-w-0 flex-1 rounded-input border border-md-outline-variant bg-md-surface px-3 py-2 font-mono text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
          />
          <Button onClick={() => void addEntries()} disabled={busy || !csv.trim()}>
            추가
          </Button>
        </div>

        {/* 초대 발송 상태 필터 — 누구에게 아직 안 보냈는지가 한눈에 보여야
            빠뜨리지도, 중복으로 보내지도 않는다. env 항목은 DB 이력이 없으므로
            필터를 걸면 숨긴다. */}
        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="text-body-sm text-md-on-surface-variant">초대 메일</span>
          <button
            type="button"
            onClick={() => void openTpl()}
            className="rounded-pill border border-md-outline-variant px-3 py-1 text-[12px] text-md-on-surface-variant hover:bg-md-surface-container hover:text-md-on-surface"
          >
            내용 보기·수정{tpl?.is_custom ? " · 수정본 사용 중" : ""}
          </button>
          <div className="flex overflow-hidden rounded-pill border border-md-outline-variant">
            {(
              [
                ["all", `전체 ${mailable.length}`],
                ["pending", `미발송 ${pending.length}`],
                ["sent", `발송완료 ${invited.length}`],
              ] as [InviteFilter, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setInviteFilter(key)}
                aria-pressed={inviteFilter === key}
                className={`px-3 py-1 text-[12px] transition-colors ${
                  inviteFilter === key
                    ? "bg-md-primary text-md-on-primary"
                    : "bg-md-surface text-md-on-surface-variant hover:bg-md-surface-container"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <span className="text-[11.5px] text-md-on-surface-variant">
            — 한 건씩 보냅니다. 자동 발송은 없고, 이미 가입한 분은 미발송 목록에서 제외됩니다.
          </span>
        </div>

        <ul className="mt-3 divide-y divide-md-outline-variant rounded-card border border-md-outline-variant">
          {inviteFilter !== "all"
            ? null
            : wl?.env_entries.map((e) => (
                <li
                  key={`env-${e}`}
                  className="flex items-center gap-2 px-3 py-2 text-body-sm"
                >
                  <span className="min-w-0 flex-1 truncate font-mono">{e}</span>
                  <span className="rounded-pill bg-md-surface-container px-2 py-0.5 text-[10.5px] text-md-on-surface-variant">
                    env (읽기전용)
                  </span>
                </li>
              ))}
          {visibleRows.map((r) => {
            const canMail = isMailable(r.entry);   // 바깥 `mailable`(목록)과 구분
            const done = !!r.invited_at;
            return (
              <li key={r.entry} className="flex items-center gap-2 px-3 py-2 text-body-sm">
                <span className="min-w-0 flex-1 truncate font-mono">{r.entry}</span>

                {r.joined_at ? (
                  <span
                    title={`가입 ${fmtDate(r.joined_at)} — 이미 사용 중인 사용자`}
                    className="shrink-0 rounded-pill bg-md-success/15 px-2 py-0.5 text-[10.5px] text-md-success"
                  >
                    가입완료
                  </span>
                ) : null}
                {canMail ? (
                  done ? (
                    <span
                      title={`${fmtDate(r.invited_at)}${r.invited_by ? ` · ${r.invited_by}` : ""}`}
                      className="shrink-0 rounded-pill bg-md-primary-container px-2 py-0.5 text-[10.5px] text-md-on-primary-container"
                    >
                      발송완료
                    </span>
                  ) : (
                    <span className="shrink-0 rounded-pill bg-md-surface-container px-2 py-0.5 text-[10.5px] text-md-on-surface-variant">
                      미발송
                    </span>
                  )
                ) : (
                  <span className="shrink-0 rounded-pill bg-md-surface-container px-2 py-0.5 text-[10.5px] text-md-on-surface-variant">
                    도메인
                  </span>
                )}

                {r.added_by ? (
                  <span className="hidden text-[11px] text-md-on-surface-variant sm:inline">
                    by {r.added_by}
                  </span>
                ) : null}

                {canMail ? (
                  <button
                    type="button"
                    onClick={() => void sendInvite(r)}
                    disabled={inviting === r.entry}
                    className="shrink-0 rounded px-2 py-1 text-[12px] text-md-primary hover:bg-md-primary-container/40 disabled:opacity-50"
                  >
                    {inviting === r.entry ? "발송 중…" : done ? "재발송" : "초대 발송"}
                  </button>
                ) : null}

                <button
                  type="button"
                  onClick={() => void removeEntry(r.entry)}
                  className="shrink-0 rounded px-2 py-1 text-[12px] text-md-error hover:bg-md-error-container/40"
                >
                  삭제
                </button>
              </li>
            );
          })}
          {wl && wl.env_entries.length === 0 && wl.db_entries.length === 0 ? (
            <li className="px-3 py-4 text-center text-body-sm text-md-on-surface-variant">
              항목 없음 — 게이트 활성 상태면 관리자만 접근 가능합니다.
            </li>
          ) : visibleRows.length === 0 && inviteFilter !== "all" ? (
            <li className="px-3 py-4 text-center text-body-sm text-md-on-surface-variant">
              {inviteFilter === "pending"
                ? "미발송 항목이 없습니다 — 모두 초대를 보냈습니다."
                : "아직 초대를 보낸 항목이 없습니다."}
            </li>
          ) : null}
        </ul>
      </section>

      {/* ── 테스트 계정 ── */}
      <section className="mt-10">
        <h2 className="text-h3 text-md-on-surface">테스트 계정</h2>
        <p className="mt-1 text-body-sm text-md-on-surface-variant">
          이메일 인증(매직링크) 없이 즉시 생성 + 화이트리스트 자동 등록. 테스터의 실제
          이메일로 만들면 보고서 완료 메일도 그 주소로 갑니다. 같은 이메일로 다시 만들면
          비밀번호 재설정.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_auto_auto]">
          <input
            value={accEmail}
            onChange={(e) => setAccEmail(e.target.value)}
            placeholder="이메일 (테스터 실제 주소)"
            className="h-9 rounded-input border border-md-outline-variant bg-md-surface px-3 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
          />
          <input
            value={accPw}
            onChange={(e) => setAccPw(e.target.value)}
            placeholder="비밀번호 (8자 이상)"
            type="text"
            className="h-9 rounded-input border border-md-outline-variant bg-md-surface px-3 font-mono text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
          />
          <input
            value={accName}
            onChange={(e) => setAccName(e.target.value)}
            placeholder="이름(선택)"
            className="h-9 rounded-input border border-md-outline-variant bg-md-surface px-3 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
          />
          <Button
            onClick={() => void createAccount()}
            disabled={busy || !accEmail.includes("@") || accPw.length < 8}
          >
            생성
          </Button>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <input
            id="del-email"
            placeholder="삭제할 계정 이메일"
            className="h-9 min-w-0 flex-1 rounded-input border border-md-outline-variant bg-md-surface px-3 text-[13px] text-md-on-surface placeholder:text-md-on-surface-variant focus:border-md-primary focus:outline-none"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                const v = (e.target as HTMLInputElement).value.trim();
                if (v.includes("@")) void deleteAccount(v);
              }
            }}
          />
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              const el = document.getElementById("del-email") as HTMLInputElement | null;
              const v = el?.value.trim() ?? "";
              if (v.includes("@")) void deleteAccount(v);
            }}
          >
            계정 삭제
          </Button>
        </div>
      </section>

      {/* 초대 메일 내용 편집 — 발송 직전에 읽으므로 저장 즉시 반영 */}
      <Dialog open={tplOpen} onOpenChange={setTplOpen}>
        <DialogContent className="max-w-[640px]">
          <DialogHeader>
            <DialogTitle className="text-h2">초대 메일 내용</DialogTitle>
          </DialogHeader>
          {tpl ? (
            <div className="flex flex-col gap-3">
              <p className="text-body-sm text-md-on-surface-variant">
                {tpl.is_custom
                  ? `수정본 사용 중${tpl.updated_by ? ` — ${tpl.updated_by}` : ""}${tpl.updated_at ? ` · ${fmtDate(tpl.updated_at)}` : ""}`
                  : "기본 문구 사용 중 (2026-08-03 실발송본)"}
                {" · "}가입 버튼(계정 만들기)은 본문과 별개로 항상 붙습니다.
              </p>
              <label className="flex flex-col gap-1">
                <span className="text-[12px] font-medium text-md-on-surface-variant">제목</span>
                <input
                  value={tplSubject}
                  onChange={(e) => setTplSubject(e.target.value)}
                  maxLength={200}
                  className="rounded-input border border-md-outline-variant bg-md-surface px-3 py-2 text-body-sm text-md-on-surface focus:border-md-primary focus:outline-none"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[12px] font-medium text-md-on-surface-variant">
                  본문
                  <span className="ml-2 font-normal opacity-80">
                    {"`## 제목`"} → 소제목 · {"`- 항목`"} → 불릿으로 렌더링
                  </span>
                </span>
                {tplPreview !== null ? (
                  <iframe
                    title="초대 메일 미리보기"
                    sandbox=""
                    srcDoc={tplPreview}
                    className="h-[420px] w-full rounded-input border border-md-outline-variant bg-white"
                  />
                ) : (
                  <textarea
                    value={tplBody}
                    onChange={(e) => setTplBody(e.target.value)}
                    rows={16}
                    maxLength={8000}
                    className="rounded-input border border-md-outline-variant bg-md-surface px-3 py-2 font-mono text-[12.5px] leading-relaxed text-md-on-surface focus:border-md-primary focus:outline-none"
                  />
                )}
              </label>
            </div>
          ) : (
            <p className="py-6 text-center text-body-sm text-md-on-surface-variant">불러오는 중…</p>
          )}
          <DialogFooter className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => void resetTpl()}
              disabled={tplBusy || !tpl?.is_custom}
              className="text-[12px] text-md-on-surface-variant underline-offset-2 hover:underline disabled:opacity-40"
            >
              기본 문구로 복원
            </button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => void showPreview()} disabled={!tpl}>
                {tplPreview !== null ? "편집으로" : "미리보기"}
              </Button>
              <Button variant="outline" onClick={() => void sendTest()} disabled={tplBusy || !tpl}>
                내게 테스트 발송
              </Button>
              <Button variant="outline" onClick={() => setTplOpen(false)}>닫기</Button>
              <Button onClick={() => void saveTpl()} disabled={tplBusy || !tpl}>저장</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </main>
  );
}
