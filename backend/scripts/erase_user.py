"""정보주체 삭제 요구 이행 — 사용자 데이터 파기(법 제36조) + 완료 통지.

`POST /me/erase`(내 데이터·개인정보 › [계정 삭제 요청])로 접수된 요청을 운영자가 실행한다.
되돌릴 수 없으므로 **기본 DRY_RUN**, `--apply` 로만 실삭제.

파기 범위(2026-09-23 현행 저장소 기준으로 재작성 — 종전 스크립트는 은퇴한 langgraph
체크포인트를 지우려 했고 대화(threads_repo)·서식·저장한 근거·보고서 행을 남겼다):
  1. 대화 — threads_repo 의 그 사용자 thread 전부(메시지·steps)
  2. 보고서·작성한 서식 — 행 + blob 파일(보관한 서식 포함)
  3. 저장한 근거(bookmarks) · 평가(feedback) · 보고서 실행 이력(report_runs, 요청 문구 포함)
  4. events — 감사 추적(`legal_consent`·`erasure_request`)은 `--keep-audit` 로 보존 가능
  5. users 행 + 초대 목록(DB) 항목 — 삭제 뒤 같은 계정으로 다시 쓰지 못하게
  6. 완료 통지 메일 — 모든 단계가 성공했을 때만 자동 발송(`--no-notify` 로 생략).
     하나라도 실패하면 보내지 않고 실패 단계를 출력한다(거짓 완료 통지 방지).

프런트 로그인 계정(NextAuth DB)은 이 스크립트 밖이다 — 초대 목록에서 빠지므로 로그인해도
이용할 수 없다.

usage:
  python scripts/erase_user.py <user_id>                  # 미리보기
  python scripts/erase_user.py <user_id> --apply          # 실삭제 + 완료 메일
  python scripts/erase_user.py <user_id> --apply --keep-audit --no-notify
운영: 컨테이너 안에서 실행(`docker compose exec -T medi-back python scripts/erase_user.py …`).
"""

from __future__ import annotations

import sys
from pathlib import Path

# `python scripts/erase_user.py` 로 실행하면 sys.path[0] 가 scripts/ 라 `import src` 가 깨진다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_AUDIT = ("legal_consent", "erasure_request")

NOTICE_SUBJECT = "[MEDIREG AI] 계정 삭제가 완료되었습니다"
NOTICE_BODY = """안녕하세요, MEDIREG AI입니다.

요청하신 계정 삭제를 처리했습니다. 대화, 심층 보고서, 작성한 서식, 저장한 근거와
계정 정보를 삭제했으며, 삭제한 정보는 되살릴 수 없습니다.
{audit_line}
다시 이용하시려면 운영팀({support_email})에 문의해 주세요.

MEDIREG AI 드림
"""


def main() -> int:
    # load_dotenv 는 실행 시에만 — 모듈 import 로 .env 가 테스트 프로세스에 새지 않게.
    from dotenv import load_dotenv
    load_dotenv()

    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print("usage: python scripts/erase_user.py <user_id> [--apply] [--keep-audit] [--no-notify]")
        return 1
    uid = sys.argv[1]
    return erase(uid, apply="--apply" in sys.argv, keep_audit="--keep-audit" in sys.argv,
                 notify="--no-notify" not in sys.argv)


def erase(uid: str, *, apply: bool, keep_audit: bool, notify: bool) -> int:
    from src.persistence import (
        get_blob_store, get_bookmarks_repo, get_events_repo, get_feedback_repo,
        get_report_runs_repo, get_reports_repo, get_users_repo,
    )
    from src.persistence.threads_repo import get_threads_repo

    users, events, threads_repo = get_users_repo(), get_events_repo(), get_threads_repo()
    reports, runs, store = get_reports_repo(), get_report_runs_repo(), get_blob_store()
    bookmarks, feedback = get_bookmarks_repo(), get_feedback_repo()

    user = users.get(uid)
    if user is None:
        print(f"user_id={uid} 없음")
        return 1
    email = (getattr(user, "email", None) or "").strip().lower()

    thread_ids = {t["id"]
                  for t in threads_repo.list_for_user(uid, limit=100000)}
    thread_ids |= {e.thread_id for e in events.list_for_user(uid, limit=100000) if e.thread_id}
    thread_ids.discard(None)
    report_ids = {m.id for tid in thread_ids for m in reports.list_for_thread(tid)}
    report_ids |= set(runs.report_ids_for_user(uid))   # 대화가 지워진 보관 서식 등
    marks = bookmarks.list_for_user(uid, limit=100000)

    print(f"[erase] user={uid} email={email or '-'}")
    print(f"  대화 {len(thread_ids)} · 보고서·서식 {len(report_ids)} · 저장한 근거 {len(marks)}")
    if not apply:
        print("[erase] DRY_RUN — 삭제 안 함. 실행: --apply")
        return 0

    failed: list[str] = []

    def step(name: str, fn) -> None:
        try:
            out = fn()
            print(f"  {name}: {out}")
        except Exception as e:  # noqa: BLE001 — 단계별로 모아 통지 여부를 정한다
            failed.append(name)
            print(f"  ⚠️ {name} 실패: {type(e).__name__}: {e}")

    def _reports() -> int:
        n = 0
        for rid in report_ids:
            meta = reports.get(rid)
            if meta is None:
                continue
            if meta.blob_uri:
                try:
                    store.delete(meta.blob_uri)
                except ValueError:
                    pass  # 다른 환경 경로(로컬 dev 가 운영 DB 에 쓴 행) — 파일 없음
            reports.delete(rid)
            n += 1
        return n

    def _threads() -> int:
        for tid in thread_ids:
            threads_repo.delete_thread(tid)
        return len(thread_ids)

    def _bookmarks() -> int:
        for b in marks:
            bookmarks.delete(uid, b.id)
        return len(marks)

    def _whitelist() -> str:
        if not email:
            return "이메일 없음"
        from src.persistence.whitelist_repo import get_whitelist_repo
        removed = get_whitelist_repo().remove(email)
        return "제거" if removed else "DB 항목 없음(도메인·env 로 허용됐다면 수동 확인)"

    step("보고서·서식", _reports)
    step("대화", _threads)
    step("저장한 근거", _bookmarks)
    step("평가", lambda: feedback.delete_for_user(uid))
    step("보고서 실행 이력", lambda: runs.delete_for_user(uid))
    step("이벤트", lambda: events.delete_for_user(uid, keep_types=_AUDIT if keep_audit else ()))
    step("초대 목록", _whitelist)
    step("계정", lambda: users.delete(uid) or "삭제")

    if failed:
        print(f"[erase] ⚠️ 실패 단계 {failed} — 완료 메일을 보내지 않았다. 원인 해결 후 다시 실행.")
        return 2
    if not notify:
        print("[erase] 완료(--no-notify: 메일 생략).")
        return 0
    if not email:
        print("[erase] 완료. ⚠️ 이메일이 없어 통지 메일을 보내지 못했다 — 다른 경로로 통지할 것.")
        return 0
    from src.observability.notifications import send_email
    from src.config import env_nonempty
    audit_line = ("\n동의·삭제 요청 기록은 처리 사실을 증명하기 위해 법령이 정한 기간 동안 보관합니다.\n"
                  if keep_audit else "")
    ok = send_email(to=email, subject=NOTICE_SUBJECT,
                    body_text=NOTICE_BODY.format(audit_line=audit_line, support_email=env_nonempty("SUPPORT_EMAIL")))
    print(f"[erase] 완료. 통지 메일 {'발송' if ok else '⚠️ 실패 — 직접 통지할 것'}: {email}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
