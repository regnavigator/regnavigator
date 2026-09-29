"""모듈별 응집도·결합도 측정 (AST, 읽기 전용) — 재실행 가능하게 보관.

사용: python scripts/measure_modules.py
결과 해석·판정은 docs/reports/module_cohesion_coupling_2026-09-10.md 참조.

## 지표

**결합도**
- `Ce`(fan-out) 이 모듈이 의존하는 내부 모듈 수
- `Ca`(fan-in)  이 모듈에 의존하는 모듈 수
- `I = Ce/(Ca+Ce)`  불안정성(Martin). 0=안정(많이 의존받음) … 1=불안정(많이 의존함)
  - 라우트·엔트리포인트는 I 가 높은 게 정상. **낮은 계층(persistence·tools)이
    I 가 높으면** 이상 신호.
- `lazy%`  함수 안 import 비율. 높으면 파일 머리로 의존을 알 수 없다(은폐된 결합).

**응집도**
- `LCOM*` = 모듈 내부 그래프의 **연결 성분 수**.
  노드=최상위 함수/클래스, 간선=(A가 B를 호출) 또는 (A·B가 같은 모듈 전역을 참조).
  1 = 한 덩어리(응집), 2+ = 서로 무관한 덩어리가 한 파일에 공존.
  - 단, 공개 API 를 나열하는 파사드(`__init__`)는 성분이 여럿이어도 정상이다.
- `max_fn`  최대 함수 길이. 파일이 작아도 한 함수가 비대하면 응집도 문제다.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path("src")


def mod_name(p: Path) -> str:
    rel = p.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["src"] + parts)


files = sorted(p for p in ROOT.rglob("*.py") if "__pycache__" not in str(p))
mods = {mod_name(p): p for p in files}

loc, lcom, maxfn, ndefs = {}, {}, {}, {}
edges: dict[str, set[str]] = defaultdict(set)
lazy_n, top_n = defaultdict(int), defaultdict(int)


def resolve(name, level, cur):
    if level:
        base = cur.split(".")
        base = base[: len(base) - level] if level <= len(base) else []
        name = ".".join(base + ([name] if name else []))
    if not name or not name.startswith("src"):
        return None
    parts = name.split(".")
    while parts:
        c = ".".join(parts)
        if c in mods:
            return c
        parts.pop()
    return None


for m, p in mods.items():
    text = p.read_text(encoding="utf-8")
    loc[m] = sum(1 for ln in text.splitlines()
                 if ln.strip() and not ln.strip().startswith("#"))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        lcom[m], maxfn[m], ndefs[m] = 0, 0, 0
        continue

    # --- 결합도: import ---
    lazy_ids = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for n in ast.walk(fn):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    lazy_ids.add(id(n))
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            tgt = resolve(n.module, n.level or 0, m)
        elif isinstance(n, ast.Import):
            tgt = next((resolve(a.name, 0, m) for a in n.names
                        if resolve(a.name, 0, m)), None)
        else:
            continue
        if tgt and tgt != m:
            edges[m].add(tgt)
            (lazy_n if id(n) in lazy_ids else top_n)[m] += 1

    # --- 응집도: 내부 그래프 연결 성분 ---
    tops = [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    names = {n.name for n in tops}
    gvars = {t.id for n in tree.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name)}
    ndefs[m] = len(tops)
    # 함수만 — 클래스는 길어도 정상(리포지토리 등)이라 응집도 신호가 아니다.
    _fns = [n for n in tops if not isinstance(n, ast.ClassDef)]
    for _c in (n for n in tops if isinstance(n, ast.ClassDef)):
        _fns += [b for b in _c.body
                 if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))]
    maxfn[m] = max(((n.end_lineno or n.lineno) - n.lineno + 1 for n in _fns), default=0)

    uses: dict[str, set[str]] = {}
    for n in tops:
        u = set()
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and (sub.id in names or sub.id in gvars):
                u.add(sub.id)
            elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                if sub.value.id in names or sub.value.id in gvars:
                    u.add(sub.value.id)
        uses[n.name] = u - {n.name}

    parent = {n.name: n.name for n in tops}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_global: dict[str, list[str]] = defaultdict(list)
    for fn_name, u in uses.items():
        for used in u:
            if used in names:
                union(fn_name, used)
            else:
                by_global[used].append(fn_name)
    for _g, fns in by_global.items():
        for other in fns[1:]:
            union(fns[0], other)
    lcom[m] = len({find(n.name) for n in tops}) if tops else 0

fan_in = defaultdict(int)
for a, outs in edges.items():
    for b in outs:
        fan_in[b] += 1

# ── 기능 영역 분류 ────────────────────────────────────────────────────
AREAS = [
    ("진입/라우트", lambda m: m.startswith("src.routes") or m == "src.api"),
    ("채팅 엔진", lambda m: m in ("src.chat_loop", "src.coverage", "src.grounding",
                                  "src.steps", "src.skill_local")),
    ("보고서", lambda m: "report" in m),
    ("검색/인용", lambda m: m.startswith("src.retrieval") or m.startswith("src.tools")),
    ("가드레일", lambda m: m.startswith("src.guardrail")),
    ("스킬", lambda m: m.startswith("src.skills")),
    ("서식/문서", lambda m: m in ("src.doc_fill", "src.form_fill", "src.annex_view",
                                  "src.form_intake", "src.doc_kinds")),
    ("영속", lambda m: m.startswith("src.persistence")),
    ("미들웨어/인증", lambda m: m.startswith("src.middleware") or m == "src.whitelist"),
    ("관측/알림", lambda m: m.startswith("src.observability") or m == "src.notices"),
    ("프롬프트", lambda m: m.startswith("src.prompts")),
]


def area_of(m):
    for name, pred in AREAS:
        if pred(m):
            return name
    return "기타"


rows = []
for m in mods:
    ce, ca = len(edges[m]), fan_in[m]
    inst = ce / (ca + ce) if (ca + ce) else 0.0
    tot = lazy_n[m] + top_n[m]
    rows.append({
        "mod": m, "area": area_of(m), "loc": loc[m], "ce": ce, "ca": ca,
        "I": inst, "lazy": (lazy_n[m] / tot * 100) if tot else 0.0,
        "lcom": lcom[m], "maxfn": maxfn[m], "ndefs": ndefs[m],
    })

print("모듈별 응집도·결합도 (LOC 80 이상만; LCOM*=내부 연결 성분 수, I=불안정성)\n")
for area, _ in AREAS + [("기타", None)]:
    sel = [r for r in rows if r["area"] == area and r["loc"] >= 80]
    if not sel:
        continue
    print(f"■ {area}")
    print(f"  {'모듈':40} {'LOC':>5} {'Ce':>3} {'Ca':>3} {'I':>5} {'lazy%':>6} {'LCOM*':>6} {'maxfn':>6}")
    for r in sorted(sel, key=lambda x: -x["loc"]):
        print(f"  {r['mod']:40} {r['loc']:5} {r['ce']:3} {r['ca']:3} "
              f"{r['I']:5.2f} {r['lazy']:5.0f}% {r['lcom']:6} {r['maxfn']:6}")
    print()
