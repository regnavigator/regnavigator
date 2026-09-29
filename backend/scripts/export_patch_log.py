"""패치 로그 시트 export — git log → local/patch_log.csv (Drive/Sheets 수동 업로드용).

기본 범위: **재설계보고서 반영(725d5c6, 2026-07-23) 이후** 커밋만 최신순으로.
CSV 한 행씩: 일자 | 커밋 | 유형 | 범위 | 제목 | 파일수 | +라인 | -라인.
유형/범위는 conventional commit 제목(`feat(report): ...`)에서 파싱(없으면 공백).
UTF-8 BOM 으로 저장 — Google Sheets·Excel 양쪽에서 한글 안 깨짐.

사용: python scripts/export_patch_log.py          # 재설계 반영 이후만(기본)
      python scripts/export_patch_log.py --all    # 전체 히스토리
(재실행 시 덮어씀 — 갱신하고 다시 업로드)
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "local" / "patch_log.csv"
# ⚠️ 이 파일은 **커밋 단위 원본 기록**이다(개발 이력 보관용).
# 운영자 ToDo Matrix 시트는 **이슈 단위**라 형식이 다르다 — 그쪽 기록은
# `local/todo_matrix_append.py` 가 만든다. 여기 출력을 그 시트에 붙이면 안 된다.
# 재설계보고서 반영 1차 커밋 — 이 커밋부터(포함) 시트에 담는다.
SINCE_COMMIT = "725d5c6"

_SUBJECT_RE = re.compile(r"^(\w+)(?:\(([^)]+)\))?(?:!)?:\s*(.+)$")
# git log 레코드 구분자 — 본문에 안 나올 시퀀스.
_SEP = "\x1f"
_REC = "\x1e"


def main() -> None:
    rng = [] if "--all" in sys.argv else [f"{SINCE_COMMIT}^..HEAD"]
    raw = subprocess.run(
        ["git", "log", *rng, f"--pretty=format:%h{_SEP}%ad{_SEP}%s{_REC}",
         "--date=format:%Y-%m-%d %H:%M", "--shortstat"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    rows: list[list[str]] = []
    # 레코드: "hash␟date␟subject␞\n\n N files changed, X insertions(+), Y deletions(-)"
    # ␞ 뒤에 나오는 shortstat 은 *직전* 커밋의 것 — 다음 chunk 선두에 실려 온다.
    for chunk in raw.split(_REC):
        lines = chunk.strip("\n").splitlines()
        stat = "\n".join(ln for ln in lines if _SEP not in ln)
        if stat and rows and rows[-1][5] == "":
            sm = re.search(r"(\d+) files? changed", stat)
            pm = re.search(r"(\d+) insertions?\(\+\)", stat)
            dm = re.search(r"(\d+) deletions?\(-\)", stat)
            rows[-1][5] = sm.group(1) if sm else ""
            rows[-1][6] = pm.group(1) if pm else ""
            rows[-1][7] = dm.group(1) if dm else ""
        head = next((ln for ln in lines if _SEP in ln), None)
        if head is None:
            continue
        sha, date, subject = head.split(_SEP, 2)
        m = _SUBJECT_RE.match(subject)
        kind, scope, title = (m.group(1), m.group(2) or "", m.group(3)) if m \
            else ("", "", subject)
        rows.append([date, sha, kind, scope, title, "", "", ""])
    header = ["일자", "커밋", "유형", "범위", "제목", "파일수", "+라인", "-라인"]
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"OK: {OUT} ({len(rows)} rows)")

    # 시트 **직접 붙여넣기용** TSV — CSV 파일 임포트(파일>가져오기>구분자 지정)
    # 보다 단계가 적다: 전체 복사 → A1 클릭 → Ctrl+V 면 열이 그대로 나뉜다.
    # 제목에 콤마가 흔해 CSV 를 붙여넣으면 한 셀에 뭉치는 문제도 없다.
    tsv = OUT.with_suffix(".tsv")
    def _cell(v: object) -> str:
        # 탭·개행이 섞이면 열이 밀린다 — 공백으로 치환.
        return re.sub(r"[\t\r\n]+", " ", str(v))
    with tsv.open("w", newline="", encoding="utf-8-sig") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(_cell(c) for c in r) + "\n")
    print(f"OK: {tsv} (붙여넣기용)")

    # 클립보드에 바로 담아준다 — 파일을 열어 전체선택할 필요도 없앤다.
    # (실패해도 위 파일이 남으므로 흐름은 안 끊는다.)
    pasted = False
    try:
        import subprocess as _sp

        data = tsv.read_text(encoding="utf-8-sig")
        if sys.platform == "win32":
            _sp.run(["clip"], input=data.encode("utf-16-le"), check=True)
            pasted = True
    except Exception:  # noqa: BLE001 — 클립보드는 부가기능
        pass

    print()
    if pasted:
        print("  → 클립보드 복사됨(커밋 단위 원본 기록)")
    print("  ⚠️ 운영자 ToDo Matrix 시트에 이걸 그대로 붙이지 말 것.")
    print("     그 시트는 **이슈 단위**(헤더 7행·11열)이고 커밋 로그와 형식이 다르다.")
    print("     시트 기록은 `python local/todo_matrix_append.py` 로 만든다.")


if __name__ == "__main__":
    main()
