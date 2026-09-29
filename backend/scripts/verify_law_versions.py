"""법령 버전 분리(현행+시행예정) 완료 판정 — RFC LAW_VERSION_CURRENT_VS_PENDING §6.

openlaw-etl 이 백필(extract→parse→load)을 돌린 뒤 **한 번에** 검증한다. 종전엔
점검할 때마다 임시 스크립트를 썼는데, 이 검증은 ETL 이 파이프라인을 돌릴 때마다
반복되므로 재현 가능한 형태로 고정한다.

    PYTHONUTF8=1 python scripts/verify_law_versions.py

검사(6항목):
  1) 현행 슬롯(`_ef` 제외) 미래 시행일 건수 — **0 아니어도 즉시 결함은 아니다**:
     시행 전 신규 제정법은 현행본이 존재할 수 없다(2026-08-16 실측 60건 중 44건이
     이 정상 케이스). 진짜 결함(= law.go.kr 에 현행이 있는데 우리는 미래본 점유)
     판별은 `--classify` 로 law.go.kr 대조.
  2) 의료법 현행 슬롯 시행일이 과거(= 예정본이 점유하지 않음)
  3) `_ef` 접미 예정본 조문 행 > 0
  4) PG 버전 컬럼 존재(law_articles.version_status 등)
  5) /search 응답에 version_status 필드 노출
  6) include_pending=true 에서 pending 동반 hit 존재 + supersedes 연결 정합

종료코드 0=전부 통과. 하나라도 실패면 1(운영 확인 필요).
검색 품질 회귀는 별도: `python scripts/eval_retrieval.py` (현행 기준 hit@1 ≥ 0.62).
"""

from __future__ import annotations

import sys

PROBE_QUERIES = ("의료법 제57조 의료광고 심의", "의료기기 제조업 허가 요건")


def _pg_checks() -> list[tuple[str, bool, str]]:
    from src.retrieval import pg_client

    pool = pg_client._get_pool()
    if pool is None:
        return [("PG 접속(PG_HOST)", False, "미설정 — PG 검사 불가")]

    out: list[tuple[str, bool, str]] = []
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # ⚠️ 예정본은 `_ef{YYYYMMDD}` 접미 **별도 행**으로 적재된다(ETL 회신 R2).
            # 미래 시행일인 것이 정상이므로 현행 슬롯 카운트에서 제외해야 한다 —
            # 안 빼면 백필 성공 후 오히려 수치가 늘어 오판한다(2026-08-16 실측:
            # 88 → 718 로 보였으나 실제 현행 슬롯 결함은 60).
            cur.execute(
                r"SELECT COUNT(*) FILTER (WHERE enforce_date > CURRENT_DATE) AS future,"
                r" COUNT(*) AS total FROM law_metadata WHERE law_id NOT LIKE '%\_ef%'")
            row = dict(cur.fetchone())
            # 시행 전 신규 제정법은 현행본이 존재할 수 없다(정상) — 법령명으로
            # 구분이 안 되므로 여기선 경고만, 진짜 결함 판별은 §참고 스크립트로.
            out.append(("① 현행 슬롯 미래 시행일(신규 제정 포함)", row["future"] == 0,
                        f"future={row['future']} / total={row['total']} "
                        f"— 신규 제정법 포함 수치(0 아니어도 즉시 결함 아님)"))

            import datetime as _dt
            cur.execute(
                r"SELECT law_id, enforce_date FROM law_metadata "
                r"WHERE title = '의료법' AND law_id NOT LIKE '%\_ef%'")
            rows = [dict(r) for r in cur.fetchall()]
            if rows:
                ed = rows[0]["enforce_date"]
                ok = bool(ed) and ed <= _dt.date.today()
                out.append(("② 의료법 현행 슬롯이 시행중", ok,
                            f"law_id={rows[0]['law_id']} enforce_date={ed}"))
            else:
                out.append(("② 의료법 현행 슬롯이 시행중", False, "의료법 현행 행 없음"))

            cur.execute(
                r"SELECT COUNT(*) AS n FROM law_metadata WHERE law_id LIKE '%\_ef%'")
            n_pending_meta = dict(cur.fetchone())["n"]
            out.append(("②-b 예정본 메타 행 > 0", n_pending_meta > 0,
                        f"{n_pending_meta}행"))

            cur.execute(
                r"SELECT COUNT(*) AS n FROM law_articles "
                r"WHERE article_key LIKE '%\_ef2%'")
            n = dict(cur.fetchone())["n"]
            out.append(("③ 예정본 조문 행(_ef) > 0", n > 0, f"{n}행"))

            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'law_articles' AND column_name IN "
                "('version_status','base_law_id','base_article_key')")
            cols = sorted(dict(r)["column_name"] for r in cur.fetchall())
            out.append(("④ PG 버전 컬럼 존재", bool(cols), f"{cols or '없음'}"))
    return out


def _search_checks() -> list[tuple[str, bool, str]]:
    from src.retrieval.search_api_client import search_articles

    out: list[tuple[str, bool, str]] = []
    saw_field = False
    pending: list[dict] = []
    keys: set[str] = set()
    for q in PROBE_QUERIES:
        hits = search_articles(q, top_k=10, include_pending=True)
        for h in hits:
            keys.add(h.get("article_key") or "")
            if "version_status" in h:
                saw_field = True
            if h.get("version_status") == "pending":
                pending.append(h)
    out.append(("⑤ /search version_status 노출", saw_field,
                "필드 있음" if saw_field else "필드 없음(서버 코드 미배포)"))
    out.append(("⑥ pending 동반 hit 존재", bool(pending),
                f"{len(pending)}건"))
    if pending:
        # 동반분은 현행본을 가리켜야 한다 — 짝이 없으면 '개정본' 안내가 성립 안 함.
        linked = [p for p in pending
                  if (p.get("supersedes_article_key") or "") in keys]
        out.append(("⑥-b supersedes 연결 정합", len(linked) == len(pending),
                    f"{len(linked)}/{len(pending)} 연결됨"))
    return out


def _classify_future_slots() -> int:
    """현행 슬롯이 미래인 법령을 law.go.kr 대조로 분류 — 결함 vs 정상(신규 제정).

    결함 = law.go.kr `target=law`(현행)에 시행 도래 버전이 있는데 코퍼스는 미래본을
    현행 슬롯에 두고 있는 것. 정상 = 현행 목록에 없고 `eflaw` 에 시행예정만 있는
    신규 제정법(현행본이 존재할 수 없음).
    """
    import datetime as dt
    import urllib.parse
    import urllib.request
    import xml.etree.ElementTree as ET

    import os

    oc = (os.getenv("MOLEG_API_KEY") or "").strip()
    if not oc:
        print("MOLEG_API_KEY 미설정 — law.go.kr 대조 불가")
        return 1

    from src.retrieval import pg_client

    pool = pg_client._get_pool()
    if pool is None:
        print("PG 미설정")
        return 1
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                r"SELECT title, law_id, enforce_date FROM law_metadata "
                r"WHERE law_id NOT LIKE '%\_ef%' AND enforce_date > CURRENT_DATE "
                r"ORDER BY enforce_date")
            rows = [dict(r) for r in cur.fetchall()]

    def _search(target: str, title: str):
        q = urllib.parse.urlencode({"OC": oc, "target": target, "type": "XML",
                                    "query": title, "search": 1, "display": 40})
        with urllib.request.urlopen(
                f"http://www.law.go.kr/DRF/lawSearch.do?{q}", timeout=20) as r:
            root = ET.fromstring(r.read())
        return [it for it in root
                if (it.findtext("법령명한글") or "").strip() == title]

    defect, legit, unknown = [], [], []
    for r in rows:
        title = r["title"]
        try:
            items = _search("law", title)
        except Exception:  # noqa: BLE001 — 개별 조회 실패는 그 건만 미분류
            unknown.append((title, "조회 실패"))
            continue
        if items:
            ef = items[0].findtext("시행일자") or ""
            if len(ef) == 8 and ef.isdigit():
                ef_d = dt.date(int(ef[:4]), int(ef[4:6]), int(ef[6:]))
                if ef_d <= dt.date.today():
                    defect.append((title, str(r["enforce_date"]), ef))
                    continue
        try:
            ef_items = _search("eflaw", title)
            codes = {(i.findtext("현행연혁코드") or "").strip() for i in ef_items}
            if ef_items and "현행" not in codes:
                legit.append((title, str(r["enforce_date"])))
                continue
        except Exception:  # noqa: BLE001
            pass
        unknown.append((title, "판별 불가"))

    print(f"현행 슬롯 미래 {len(rows)}건 분류")
    print(f"\n★ 결함 {len(defect)}건 (law.go.kr 에 현행 존재 — 재수집 대상)")
    for t, ours, real in defect:
        print(f"   {t}: 코퍼스={ours} / 실제 현행={real}")
    print(f"\n정상 {len(legit)}건 (시행 전 신규 제정 — 현행본 없음이 맞음)")
    print(f"판별 불가 {len(unknown)}건")
    for t, w in unknown:
        print(f"   {t}: {w}")
    return 1 if defect else 0


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    if "--classify" in sys.argv:
        return _classify_future_slots()
    results: list[tuple[str, bool, str]] = []
    try:
        results += _pg_checks()
    except Exception as e:  # noqa: BLE001 — 한쪽 실패가 나머지 검사를 막지 않게
        results.append(("PG 검사", False, f"{type(e).__name__}: {e}"))
    try:
        results += _search_checks()
    except Exception as e:  # noqa: BLE001
        results.append(("검색 검사", False, f"{type(e).__name__}: {e}"))

    print("=== 법령 버전 분리 검증 (RFC §6) ===")
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} — {detail}")
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"\n미완료 {len(failed)}건 — ETL 백필(extract→parse→load) 확인 필요.")
        return 1
    print("\n전부 통과. 이어서 `python scripts/eval_retrieval.py` 로 "
          "현행 기준 검색 품질 회귀(hit@1 ≥ 0.62) 확인 권장.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
