"""기능 단위 구성 맵 — 기능 → (엔드포인트, 백엔드 모듈, 프런트 파일).

모듈 단위 표는 이미 있다. 여기서는 **하나의 사용자 기능이 몇 개 모듈에 걸쳐
있는지**(= 기능 응집도)를 본다. 한 기능을 고치려고 여러 파일을 열어야 하면
모듈 경계가 기능 경계와 어긋난 것이다.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BACK = Path("src")
FRONT = Path(r"<workspace>\medi-front\src")

# 기능 → (백엔드 모듈 prefix/이름, 프런트 경로 조각)
FEATURES = {
    "채팅(fast)": (
        ["chat_loop", "routes/chat", "coverage", "grounding", "steps",
         "prompts/supervisor", "text/normalize"],
        ["store/useChatState", "store/turns", "client/chatApi", "chat/Turn",
         "chat/TurnAnswer", "chat/ChatInput", "chat/MarkdownContent"],
    ),
    "검색·인용": (
        ["tools/search", "tools/citations", "retrieval/", "official_sources"],
        ["chat/CitationFootnotes", "panel/CitationInspector", "parse/citation",
         "chat/CitationEvidenceTooltip", "chat/LiveSearchGlass"],
    ),
    "심층 보고서": (
        ["report_pipeline", "report_runner", "report_sections", "reports_convert",
         "routes/reports", "tools/reports", "persistence/reports_repo",
         "persistence/report_runs_repo"],
        ["panel/RightPanel", "chat/ReportCardGroup", "chat/ReportPreviewDialog",
         "client/reports"],
    ),
    "서식 작성": (
        ["doc_fill", "form_fill", "form_intake", "annex_view", "routes/articles"],
        ["panel/DocumentPanel", "chat/AnnexModal", "chat/RelatedFormsCard",
         "client/annex", "client/documents", "formEntry"],
    ),
    "IRB/DRB 스킬": (
        ["skills/", "skill_local"],
        ["chat/ChatInput"],
    ),
    "가드레일(PII·의도)": (
        ["guardrail/", "middleware/pii_gate"],
        ["chat/Turn"],
    ),
    "인증·베타게이트": (
        ["middleware/auth", "whitelist", "persistence/whitelist_repo", "routes/beta"],
        ["client/authToken", "betaGate", "(auth)/login"],
    ),
    "관리자": (
        ["routes/admin", "notices", "announcements", "maintenance",
         "persistence/settings_repo"],
        ["app/admin/"],
    ),
    "개인정보·법적": (
        ["routes/privacy", "legal", "persistence/users_repo"],
        ["settings/PrivacyDialog", "legal/", "app/privacy", "app/terms"],
    ),
    "관측·한도": (
        ["observability/", "llm_limits", "middleware/quota", "middleware/rate_limit",
         "routes/health"],
        ["shell/LoadBadge", "hooks/useReportsAvailability", "store/reportsAvailability",
         "client/quota"],
    ),
}


def back_mods(pats):
    out = []
    for p in BACK.rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        rel = str(p.relative_to(BACK)).replace("\\", "/")
        for pat in pats:
            if rel.startswith(pat) or rel == pat + ".py" or rel.startswith(pat + "/"):
                loc = sum(1 for ln in p.read_text(encoding="utf-8").splitlines()
                          if ln.strip() and not ln.strip().startswith("#"))
                out.append((rel, loc))
                break
    return sorted(set(out))


def front_files(pats):
    out = []
    for p in FRONT.rglob("*.ts*"):
        rel = str(p.relative_to(FRONT)).replace("\\", "/")
        for pat in pats:
            if pat in rel:
                loc = sum(1 for ln in p.read_text(encoding="utf-8", errors="replace").splitlines()
                          if ln.strip() and not ln.strip().startswith(("//", "*", "/*")))
                out.append((rel, loc))
                break
    return sorted(set(out))


routes_by_file: dict[str, list[str]] = {}
for p in (BACK / "routes").glob("*.py"):
    txt = p.read_text(encoding="utf-8")
    eps = re.findall(r'@router\.(get|post|patch|put|delete)\("([^"]+)"', txt)
    if eps:
        routes_by_file[p.name] = [f"{m.upper()} {u}" for m, u in eps]

print(f"{'기능':20} {'백엔드':>6} {'LOC':>7} {'프런트':>6} {'LOC':>7}  총 LOC")
print("-" * 68)
rows = []
for feat, (bp, fp) in FEATURES.items():
    b, f = back_mods(bp), front_files(fp)
    bl, fl = sum(x[1] for x in b), sum(x[1] for x in f)
    rows.append((feat, b, f, bl, fl))
    print(f"{feat:20} {len(b):6} {bl:7} {len(f):6} {fl:7}  {bl+fl:7}")

print("\n\n=== 기능별 구성 ===")
for feat, b, f, bl, fl in rows:
    print(f"\n■ {feat}   (백 {len(b)}모듈 {bl} LOC / 프런트 {len(f)}파일 {fl} LOC)")
    for rel, loc in sorted(b, key=lambda x: -x[1])[:8]:
        eps = routes_by_file.get(rel.split("/")[-1], []) if rel.startswith("routes/") else []
        tail = f"   [{len(eps)} endpoints]" if eps else ""
        print(f"    back  {rel:42} {loc:5}{tail}")
    for rel, loc in sorted(f, key=lambda x: -x[1])[:6]:
        print(f"    front {rel:42} {loc:5}")
