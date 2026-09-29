"""입력 PII 게이트 평가 — regex 1차(+NER 2차 설정 시) recall·오탐 측정.

라벨셋 `data/pii_eval_ko.jsonl` 각 줄:
  { "text": ..., "expect": [regex 카테고리…], "ner_expect": [NER placeholder 라벨…] }

측정:
- regex recall: expect 한 구조적 카테고리를 실제로 마스킹했는가.
- NER recall: PII_NER_API_URL 설정 시, ner_expect 라벨을 마스킹했는가.
- 오탐(false positive): expect·ner_expect 가 빈(법령·조문 등) 문장을 건드렸는가.

용법:
  python scripts/eval_pii.py                 # regex 만(서비스 미설정)
  PII_NER_API_URL=... PII_NER_API_KEY=... python scripts/eval_pii.py   # +NER
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.guardrail import ner_client  # noqa: E402
from src.guardrail.gate import scrub_input  # noqa: E402
from src.guardrail.pii import scrub as regex_scrub  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data" / "pii_eval_ko.jsonl"


def main() -> int:
    if not DATA.exists():
        print(f"라벨셋 없음: {DATA}")
        return 1
    rows = [json.loads(ln) for ln in DATA.read_text(encoding="utf-8").splitlines() if ln.strip()]

    ner_on = ner_client.is_available()
    print(f"평가셋 {len(rows)}문장 · NER 2차: {'ON' if ner_on else 'OFF(regex-only)'}\n")

    regex_hit = regex_tot = 0
    ner_hit = ner_tot = 0
    fp = 0
    for r in rows:
        text = r["text"]
        expect = r.get("expect") or []
        ner_expect = r.get("ner_expect") or []

        _, regex_cats = regex_scrub(text)
        scrubbed, all_cats = scrub_input(text)

        # regex recall
        for e in expect:
            regex_tot += 1
            if e in regex_cats:
                regex_hit += 1
            else:
                print(f"  [regex MISS] {e:14} | {text}")

        # NER recall (서비스 설정 시)
        if ner_on:
            ner_cats = [c for c in all_cats if c not in regex_cats]
            for e in ner_expect:
                ner_tot += 1
                if e in ner_cats:
                    ner_hit += 1
                else:
                    print(f"  [ner MISS]   {e:14} | {text}")

        # 오탐 — 기대 비어있는데 마스킹 발생
        if not expect and not (ner_on and ner_expect) and scrubbed != text:
            fp += 1
            print(f"  [FALSE POS]  {text}  ->  {scrubbed}")

    print("\n=== 결과 ===")
    print(f"regex recall : {regex_hit}/{regex_tot}"
          + (f" ({regex_hit/regex_tot:.2f})" if regex_tot else ""))
    if ner_on:
        print(f"NER   recall : {ner_hit}/{ner_tot}"
              + (f" ({ner_hit/ner_tot:.2f})" if ner_tot else ""))
    else:
        print("NER   recall : (서비스 미설정 — PII_NER_API_URL 로 활성)")
    print(f"오탐(FP)     : {fp}건 (0 이어야 검색 품질 보호)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
