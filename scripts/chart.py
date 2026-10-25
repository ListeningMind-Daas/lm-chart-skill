#!/usr/bin/env python3
"""lm-chart 진입점 — 받은 인자를 이 스킬의 `scripts/viz.py`(catalog · select · render · check · gallery · reference · auto)에
그대로 넘기고 종료 코드를 돌려준다(0 정상 · 2 스펙 오류 · 11 check 실패). API 호출 없음.

  python3 chart.py auto <데이터.csv|json> --unit <단위> --period <기간> [--intent …] [--compare] [--json]
  python3 chart.py check <페이지.html>
  python3 chart.py --where        # 명령 파일 경로만 출력

선택 규칙·렌더러·검사·카탈로그 문서가 모두 이 폴더 안에 있다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent          # 스킬 폴더
VIZ_CLI = SKILL_ROOT / "scripts/viz.py"


def cli_path() -> Path:
    if not VIZ_CLI.is_file():
        raise FileNotFoundError(f"CLI 가 없다: {VIZ_CLI} — 스킬 폴더가 통째로 설치돼야 한다")
    return VIZ_CLI


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--where"]:
        print(cli_path())
        return 0
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    try:
        cli = cli_path()
    except FileNotFoundError as e:
        print(f"lm-chart: {e}", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(cli), *argv], env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


if __name__ == "__main__":
    sys.exit(main())
