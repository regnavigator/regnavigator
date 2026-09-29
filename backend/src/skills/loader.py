"""스킬 로더 — progressive disclosure (temp/medireg-irb-drb-bundle 이식).

Level 1  manifest 의 description 카탈로그만 시스템 프롬프트에 상주 (~1.2k 토큰)
Level 2  load_skill(name)        → SKILL.md 본문
Level 3  read_skill_reference()  → references/*.md

원본 번들과의 차이(이식 시 추가):
- `seed()` / `sent_keys()`: 턴마다 인스턴스를 새로 만들므로, 히스토리에 이미
  실린 파일을 `_sent` 로 시드해 멀티턴 중복 적재를 막는다.
- `tool_defs()` 가 OpenAI function 포맷 — chat_loop.TOOL_SPECS 관례
  (bind_tools + LLM_FALLBACK OpenAI 폴백 호환).
지식 자산(SKILL.md·references)은 **코드에서 파싱하지 않는다** — 모델이 읽는
문서이며 로더로만 접근한다(번들 README §4-3 계약).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

VERDICT_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)

# load_skill / read_skill_reference 호출을 식별하는 도구 이름 (chat_loop 분기 공유)
SKILL_TOOL_NAMES = ("load_skill", "read_skill_reference")


class SkillError(Exception):
    pass


@dataclass
class SkillLoader:
    bundle_dir: Path
    manifest_path: Path
    # 세션(턴)당 이미 보낸 파일 — 같은 내용을 두 번 컨텍스트에 넣지 않는다
    _sent: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.bundle_dir = Path(self.bundle_dir).resolve()
        self.manifest = json.loads(
            Path(self.manifest_path).read_text(encoding="utf-8")
        )
        self._by_name = {s["name"]: s for s in self.manifest["skills"]}

    # ------------------------------------------------------------------ L1
    @property
    def version(self) -> str:
        """rulepack_version — 번들 내용 SHA-256 앞 12자리 (판정 로그 태깅용)."""
        return self.manifest["version"]

    @property
    def skill_names(self) -> list[str]:
        return list(self._by_name)

    def catalog(self) -> str:
        """시스템 프롬프트에 넣을 스킬 카탈로그(L1)."""
        lines = [
            "# 사용 가능한 내부 지침 스킬",
            "",
            "작업이 아래 스킬에 해당하면 `load_skill` 로 지침을 먼저 읽고 그대로 따른다.",
            "지침을 읽지 않고 기관 SOP 의 조문 번호·기한 일수·서식 번호를 기억으로 답하지 않는다.",
            "",
        ]
        for s in self.manifest["skills"]:
            lines.append(f"- **{s['name']}**: {s['description']}")
        return "\n".join(lines)

    # -------------------------------------------------------- 세션 dedup 시드
    def seed(self, keys: Iterable[str]) -> None:
        """히스토리에 이미 실린 파일 키('{skill}/{path}')를 중복 억제 대상으로 등록."""
        self._sent.update(keys)

    def sent_keys(self) -> list[str]:
        return sorted(self._sent)

    # ------------------------------------------------------------------ L2
    def load_skill(self, name: str) -> str:
        skill = self._by_name.get(name)
        if skill is None:
            raise SkillError(
                f"'{name}' 스킬 없음. 사용 가능: {', '.join(self._by_name)}"
            )

        key = f"{name}/SKILL.md"
        body = (self.bundle_dir / skill["dir"] / "SKILL.md").read_text(
            encoding="utf-8"
        )
        if key in self._sent:
            return (f"[이미 로드됨 — {key}. 위 대화의 내용을 그대로 사용하되, "
                    f"질문의 세부(소요기간·서류 목록·기한 등)가 본문에 없으면 "
                    f"read_skill_reference 로 해당 참조 파일을 읽어라.]")
        self._sent.add(key)

        refs = "\n".join(f"  - {r}" for r in skill["references"]) or "  (없음)"
        return (
            f"# 스킬: {name}\n\n{body}\n\n"
            f"---\n참조 파일 (필요할 때 read_skill_reference 로 읽는다):\n{refs}\n"
        )

    # ------------------------------------------------------------------ L3
    def read_reference(self, name: str, path: str) -> str:
        skill = self._by_name.get(name)
        if skill is None:
            raise SkillError(f"'{name}' 스킬 없음")
        if path not in skill["references"]:
            raise SkillError(
                f"'{path}' 없음. 사용 가능: {', '.join(skill['references'])}"
            )

        skill_root = (self.bundle_dir / skill["dir"]).resolve()
        target = (skill_root / path).resolve()
        # 경로 탈출 방지 — manifest 밖 경로는 위에서 이미 막히지만 이중 방어
        if not target.is_relative_to(skill_root):
            raise SkillError("잘못된 경로")

        key = f"{name}/{path}"
        if key in self._sent:
            return (f"[이미 로드됨 — {key}. 위 대화의 내용을 그대로 사용하되, "
                    f"질문의 세부(소요기간·서류 목록·기한 등)가 본문에 없으면 "
                    f"read_skill_reference 로 해당 참조 파일을 읽어라.]")
        self._sent.add(key)
        return f"# {key}\n\n{target.read_text(encoding='utf-8')}"

    # ---------------------------------------------------------------- tools
    def tool_defs(self) -> list[dict]:
        """OpenAI function 포맷 (chat_loop.TOOL_SPECS 관례) — bind_tools 용."""
        names = self.skill_names
        return [
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": (
                        "내부 지침 스킬의 상세 지침(SKILL.md)을 읽는다. 해당 스킬이 "
                        "다루는 작업을 시작하기 전에 반드시 먼저 호출한다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": names}
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_skill_reference",
                    "description": (
                        "스킬의 참조 파일을 읽는다. SKILL.md 가 특정 파일을 읽으라고 "
                        "지시할 때만 호출한다. 전부 읽지 않는다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill": {"type": "string", "enum": names},
                            "path": {
                                "type": "string",
                                "description": "예: references/irb-exemption.md",
                            },
                        },
                        "required": ["skill", "path"],
                    },
                },
            },
        ]

    def dispatch(self, tool_name: str, tool_input: dict) -> tuple[str, bool]:
        """(내용, is_error) 반환. 에러도 문자열로 돌려 모델이 복구하게 한다."""
        try:
            if tool_name == "load_skill":
                return self.load_skill(tool_input["name"]), False
            if tool_name == "read_skill_reference":
                return (
                    self.read_reference(tool_input["skill"], tool_input["path"]),
                    False,
                )
            return f"알 수 없는 도구: {tool_name}", True
        except (SkillError, KeyError, OSError) as e:
            return str(e), True


# --------------------------------------------------------------------- 로그
def extract_verdict(assistant_text: str) -> Optional[dict]:
    """응답 말미의 구조화 판정 블록(irb/drb 키 포함 JSON)을 뽑아낸다.

    실패해도 예외를 던지지 않는다 — 판정이 아닌 응답이 대부분이다.
    """
    for m in reversed(list(VERDICT_BLOCK.finditer(assistant_text))):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if "irb" in obj or "drb" in obj:
            return obj
    return None
