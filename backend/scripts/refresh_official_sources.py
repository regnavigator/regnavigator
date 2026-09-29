"""공식 창구 레지스트리 자동 유지보수 — 후보 채굴 → 실접속 검증 → 등재/비활성.

본문 URL 강제(2026-08-19) 이후 **레지스트리 커버리지 = 링크 커버리지**가 됐다.
코드 상수만 쓰면 창구 하나 늘 때마다 사람이 배포해야 하므로, PII 오탐 신고
루프와 같은 형태로 자동화한다:

    events(url_enforced) 에서 제거된 URL 채굴
      → 공공·협회 도메인만 후보로(AUTO_TLD_SUFFIXES)
      → 반복 등장(AUTO_MIN_HITS) 만 대상
      → https 루트 실접속 확인(200/3xx)
      → 자동 등재(active) · 실패는 후보로만 남김
    기존 등재분 헬스체크 → 연속 실패면 자동 비활성 + ops 알림

사용:
    python scripts/refresh_official_sources.py            # 채굴 + 헬스체크
    python scripts/refresh_official_sources.py --dry-run  # 변경 없이 결과만
    python scripts/refresh_official_sources.py --at 04:30 # 운영 주기(medi-cron)

⚠️ 자동 등재는 **틀린 주소를 '검증됨'으로 굳힐 수 있다** — 강제 도입 전보다
나쁜 상태다. 그래서 조건을 좁게 잡고(공공 도메인·루트·반복·실접속), 상용
도메인은 관리자 수동 승인으로만 들어오게 한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

_log = logging.getLogger("refresh_official_sources")
_KST = timezone(timedelta(hours=9))

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
FAIL_THRESHOLD = 2      # 연속 실패 이 횟수부터 비활성


def probe(url: str, timeout: float = 12.0) -> tuple[bool, str, str]:
    """(살아있나, 사유, 페이지 제목). 403 은 '살아있음'으로 본다 — 봇 차단일 뿐
    도메인은 존재한다(실측: adv.kmdia.or.kr 루트 200, /ADV 403)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(4096).decode("utf-8", "ignore")
            m = _TITLE_RE.search(body)
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""
            return True, f"HTTP {r.status}", title
    except urllib.error.HTTPError as e:
        # 4xx 중 403/405 는 접근 제한(존재함), 404/410 은 없는 주소.
        if e.code in (401, 403, 405, 429):
            return True, f"HTTP {e.code}(접근 제한 — 존재)", ""
        return False, f"HTTP {e.code}", ""
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}", ""


def mine_candidates(days: int = 30) -> Counter:
    """events(url_enforced) 에서 제거된 URL 의 호스트 빈도."""
    from src.official_sources_store import host_of
    from src.persistence import get_events_repo

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ")
    hosts: Counter = Counter()
    for e in get_events_repo().list_by_type("url_enforced", since=since, limit=2000):
        try:
            payload = json.loads(e.payload_json or "{}")
        except ValueError:
            continue
        for item in payload.get("items", []):
            h = host_of(str(item))
            if h:
                hosts[h] += 1
    return hosts


def run(*, dry_run: bool = False, days: int = 30) -> int:
    from src.official_sources import OFFICIAL_SOURCES, _host_of
    from src.official_sources_store import (
        AUTO_MIN_HITS,
        active_entries,
        all_entries,
        is_auto_registrable,
        set_active,
        upsert,
    )

    seeded = {_host_of(s["url"]) for s in OFFICIAL_SOURCES if s.get("url")}
    known = {e["host"] for e in all_entries()} | seeded

    # ── 1) 후보 채굴 ────────────────────────────────────────────────────
    hosts = mine_candidates(days)
    print(f"[mine] 최근 {days}일 제거된 URL 호스트 {len(hosts)}종")
    registered, skipped = 0, []
    for host, hits in hosts.most_common():
        if host in known:
            continue
        url = f"https://{host}"
        if not is_auto_registrable(url):
            skipped.append((host, hits, "상용 도메인 — 수동 승인 대상"))
            continue
        if hits < AUTO_MIN_HITS:
            skipped.append((host, hits, f"등장 {hits}회 < {AUTO_MIN_HITS}"))
            continue
        ok, why, title = probe(url)
        if not ok:
            skipped.append((host, hits, f"접속 실패 {why}"))
            continue
        print(f"  + 등재 {host} (등장 {hits}회 · {why} · {title[:40]!r})")
        registered += 1
        if not dry_run:
            upsert(url=url, name=title or host,
                   note=f"자동 등재 — 답변에서 {hits}회 사용, {why}", source="auto")

    if skipped:
        print(f"[mine] 미등재 {len(skipped)}종(사유):")
        for h, n, why in skipped[:10]:
            print(f"    {h} ({n}회) — {why}")

    # ── 2) 헬스체크 ────────────────────────────────────────────────────
    entries = active_entries()
    print(f"\n[health] 동적 등재 {len(entries)}종 점검")
    dead = []
    for e in entries:
        ok, why, _ = probe(e["url"])
        if ok:
            if not dry_run:
                set_active(e["host"], True, reason=why)
            continue
        fails = int(e.get("fail_count", 0)) + 1
        print(f"  ! 실패 {e['host']} — {why} (연속 {fails})")
        if fails >= FAIL_THRESHOLD:
            dead.append((e["host"], why))
        if not dry_run:
            set_active(e["host"], False, reason=why)

    # 시드(코드 상수)도 확인 — 죽으면 사람이 고쳐야 하므로 알림만.
    print("[health] 코드 시드 점검")
    seed_dead = []
    for s in OFFICIAL_SOURCES:
        u = (s.get("url") or "").strip()
        if not u:
            continue
        ok, why, _ = probe(u)
        if not ok:
            seed_dead.append((s["name"], u, why))
            print(f"  ! 시드 실패 {s['name']} {u} — {why}")

    if (dead or seed_dead) and not dry_run:
        from src.observability.alerts import send_ops_alert

        lines = [f"동적 비활성: {h} ({w})" for h, w in dead]
        lines += [f"시드 점검 실패(코드 수정 필요): {n} {u} ({w})"
                  for n, u, w in seed_dead]
        send_ops_alert("공식 창구 레지스트리 점검 실패", "\n".join(lines),
                       dedup_key="official_sources_health")

    print(f"\n요약: 신규 등재 {registered} · 비활성 {len(dead)} · "
          f"시드 실패 {len(seed_dead)}{' (dry-run)' if dry_run else ''}")
    return 0


def _next_delay(now_kst: datetime, at: str) -> float:
    hh, mm = (int(x) for x in at.split(":"))
    t = now_kst.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t <= now_kst:
        t += timedelta(days=1)
    return (t - now_kst).total_seconds()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--at", metavar="HH:MM", help="KST 지정 시각까지 대기 후 1회")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from dotenv import load_dotenv

    load_dotenv()
    if args.at:
        d = _next_delay(datetime.now(_KST), args.at)
        print(f"[sources] 다음 실행 KST {args.at} — {d / 3600:.1f}h 대기", flush=True)
        time.sleep(d)
    return run(dry_run=args.dry_run, days=args.days)


if __name__ == "__main__":
    sys.exit(main())
