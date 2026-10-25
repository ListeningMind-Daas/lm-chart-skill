#!/usr/bin/env python3
"""references/quick-reference.md 생성기 — 손으로 쓰지 않는다.

`viz.py catalog --json`(코드 이름·한글 이름·영문 이름·답하는 질문)과 `lib/viz.py` 의 INTENTS(의도 → 우선 차트)를
읽어 한 장으로 만든다. 카탈로그가 바뀌면 다시 돌린다; 회귀 테스트가 저장본과 생성본이 같은지 대조한다.

  python3 build_quick_reference.py            # references/quick-reference.md 에 쓴다
  python3 build_quick_reference.py --check    # 저장본과 같으면 0, 다르면 1(쓰지 않음)
  python3 build_quick_reference.py --stdout
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent          # 스킬 폴더
OUT = HERE.parent / "references/quick-reference.md"


def build() -> str:
    raw = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts/viz.py"), "catalog", "--json"],
                         check=True, capture_output=True, text=True).stdout
    rows = json.loads(raw)
    sys.path.insert(0, str(SKILL_ROOT))
    from lib import viz as V  # noqa: E402
    names = {r["id"]: r["name"] for r in rows}
    lines = [
        f"# lm-chart 빠른 참조 — 표준 차트 {len(rows)}종 · 의도 {len(V.INTENTS)}가지",
        "",
        "> 생성 파일 — 손으로 고치지 않는다. `python3 .claude/skills/lm-chart/scripts/build_quick_reference.py` 가",
        "> `scripts/viz.py catalog --json` 과 `lib/viz.py` 의 `INTENTS` 에서 만든다.",
        "> 조건·그리는 규칙·값의 상태는 `references/viz-catalog.md` 를 본다.",
        "",
        "## 차트 — 코드가 데이터 모양으로 고른다(사람·LLM 이 고르지 않는다)",
        "",
        "| 코드 이름(`--chart`) | 이름 | 영문 | 답하는 질문 |",
        "|---|---|---|---|",
    ]
    lines += [f"| `{r['id']}` | {r['name']} | {r['en']} | {r['question']} |" for r in rows]
    lines += [
        "",
        "## 의도(`--intent`) — 힌트이지 강제가 아니다",
        "",
        "데이터가 조건을 못 채우면 기본 선택으로 돌아가고 결과의 `intent_note` 에 이유가 남는다.",
        "",
        "| 의도 | 우선 차트(앞이 먼저) |",
        "|---|---|",
    ]
    for intent, charts in V.INTENTS.items():
        lines.append(f"| `{intent}` | " + " → ".join(f"{names[c]}(`{c}`)" for c in charts) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = build()
    if "--stdout" in argv:
        print(text, end="")
        return 0
    if "--check" in argv:
        same = OUT.is_file() and OUT.read_text(encoding="utf8") == text
        print("same" if same else f"stale: {OUT}")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf8")
    print(OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
