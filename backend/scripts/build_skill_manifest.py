"""스킬 manifest 빌드 — SKILL.md frontmatter 파싱 → manifest.json 생성.

(temp/medireg-irb-drb-bundle/skill_registry.py 이식 — 기본 경로만 이 repo 로.)

런타임에 디렉터리를 스캔하지 않는다 — SOP(.md) 수정 시 한 번만 돌리고
manifest.json 을 함께 커밋한다. 갱신 누락은 tests/test_skills.py 의
매니페스트 최신성 테스트(게이트 1)가 잡는다.

    python scripts/build_skill_manifest.py                # 기본 번들
    python scripts/build_skill_manifest.py <bundle_dir>   # 명시 경로
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

DEFAULT_BUNDLE = Path(__file__).resolve().parents[1] / "src" / "skills" / "medireg_irb_drb"
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def _parse_frontmatter(text: str) -> dict:
    """SKILL.md 의 YAML frontmatter 파싱 — name/description 만 쓰므로 파서 없이.

    값에 콜론이 포함될 수 있으므로 첫 콜론에서만 분리한다.
    """
    m = FRONTMATTER.match(text)
    if not m:
        raise ValueError("frontmatter 없음")

    meta: dict[str, str] = {}
    key: str | None = None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if re.match(r"^\s", line) and key:          # 이어지는 줄
            meta[key] += " " + line.strip()
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        meta[key] = val.strip().strip('"').strip("'")
    return meta


def build(bundle_dir: Path) -> dict:
    skills = []
    for skill_dir in sorted(p for p in bundle_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        text = skill_md.read_text(encoding="utf-8")
        meta = _parse_frontmatter(text)
        name = meta.get("name") or skill_dir.name

        refs = sorted(
            str(p.relative_to(skill_dir)).replace("\\", "/")
            for p in skill_dir.rglob("*.md")
            if p.name != "SKILL.md"
        )

        # 스킬 전체(SKILL.md + 모든 references)의 내용 지문.
        # 조문 한 글자만 고쳐도 바뀐다 → rulepack_version 이 따라 바뀐다.
        # ⚠️ CRLF→LF 정규화 필수 — Windows 체크아웃(autocrlf)과 CI(LF)가
        # 같은 커밋에서 다른 버전을 계산해 최신성 테스트가 CI 에서만 깨졌다
        # (2026-08-21 실측: 로컬 2a288a15c63f vs CI 6b0512a2fc9a).
        h = hashlib.sha256()
        for rel in ["SKILL.md", *refs]:
            h.update(rel.encode())
            h.update((skill_dir / rel).read_bytes().replace(b"\r\n", b"\n"))

        skills.append({
            "name": name,
            "dir": skill_dir.name,
            "description": meta["description"],
            "body_chars": len(text) - len(FRONTMATTER.match(text).group(0)),
            "references": refs,
            "digest": h.hexdigest()[:16],
        })

    payload = {"version": None, "skills": skills}
    # 번들 내용이 바뀌면 version 이 바뀐다 → 판정 로그(rulepack_version)에 기록
    blob = json.dumps(payload["skills"], ensure_ascii=False, sort_keys=True)
    payload["version"] = hashlib.sha256(blob.encode()).hexdigest()[:12]
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", type=Path, nargs="?", default=DEFAULT_BUNDLE)
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="출력 경로(기본: <bundle>/manifest.json)")
    args = ap.parse_args()

    manifest = build(args.bundle)
    out = args.out or (args.bundle / "manifest.json")
    out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    total = sum(len(s["description"]) for s in manifest["skills"])
    print(f"{len(manifest['skills'])} skills  version={manifest['version']}")
    print(f"description 총 {total:,}자 (≈{total // 2:,} 토큰, 상시 비용)")


if __name__ == "__main__":
    main()
