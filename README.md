# lm-chart — 데이터 한 파일 → 표준 차트 한 장

데이터(csv·json)를 주면 **코드가 데이터 모양을 읽어 표준 차트 26종 중 하나를 고르고, inline SVG 로 그린 뒤 검사까지 하는** 에이전트 스킬입니다.
Claude Code·Claude Desktop 등 스킬을 읽는 에이전트 호스트에 그대로 넣어 씁니다.

- 외부 차트 라이브러리·CDN·캔버스를 쓰지 않습니다 — 산출물은 어디서나 열리는 HTML 한 장(inline SVG + 표)입니다.
- LLM 이 차트 유형을 고르지 않습니다 — 선택 규칙은 코드에 있고, 같은 입력이면 같은 그림입니다.
- 차트 위 '발견 한 줄'과 '근거' 줄은 데이터에서 계산한 문장입니다. 사람이 쓴 결론 줄의 숫자도 차트에 있는 값이어야 렌더됩니다.
- Python 3.10 이상, 표준 라이브러리만. 설치할 패키지·네트워크·API 키가 없습니다. MIT 라이선스.

## 설치

```bash
git clone https://github.com/ListeningMind-Daas/lm-chart-skill ~/.claude/skills/lm-chart
```

프로젝트 안에서만 쓰려면 `<프로젝트>/.claude/skills/lm-chart` 에 둡니다. 폴더 이름은 `lm-chart` 여야 합니다.

## 바로 써 보기

```bash
C=~/.claude/skills/lm-chart/scripts/chart.py
python3 $C auto my-data.csv --unit 건/월 --period 2025-09~2026-08          # 차트 고르고 그려서 my-data.viz.html
python3 $C auto my-data.csv --unit 건/월 --period 2025-09~2026-08 --compare   # 상위 3개 차트를 나란히
python3 $C auto my-data.csv --unit 건/월 --period 2025-09~2026-08 --theme executive   # 경영진 보고 스타일
python3 $C check my-data.viz.html                                           # 결과 페이지 검사
python3 $C reference --public --out chart-reference.html                    # 26종 레퍼런스 페이지(견본 데이터)
```

csv 는 머리행이 있어야 하고, 세로형(한 행 = 한 항목 또는 한 시점)이어야 합니다. json 은 행 목록 `[{…}]` 또는 viz-data 스펙(`references/viz-catalog.md` §2)입니다.

## 차트 26종

순위 가로 막대 · 증감 막대 · 묶음 막대 · 100% 구성 막대 · 도넛 · 추이선 · 스파크라인 묶음 · 성수기 달력 · 교차 히트맵 · 사분면 버블 · 순위 변동 ·
흐름 나무 · 표 · 그래픽 표 · 히트 표 · 맞댄 막대 · 쌍 전이 막대 · 양방향 나무 · 관계 표 · 레이더 · 퍼널 · 여정 지도(산키) · 수요 지도(트리맵) ·
지식 그래프 · 증감 다리(워터폴) · 지표 타일.

어떤 데이터 모양에 어떤 차트가 고르게 되는지, 각 차트가 지키는 규칙, 값이 없는 칸(결측·조회 안 함·기준 미달·미반환)을 어떻게 그리는지는
`references/viz-catalog.md` 에 있습니다. 짧은 표는 `references/quick-reference.md`.

## 에이전트가 따르는 절차

`SKILL.md` 가 에이전트용 설명서입니다 — 단위·기간을 확인하고, `auto` 를 한 번 부르고, 결과를 그대로 보고하고, 수정 요청은 옵션으로만 옮깁니다.

## 데이터는 어디서

이 스킬은 차트만 그립니다. 검색 데이터는 ListeningMind DaaS API 로 모으고, 시장을 읽는 분석 스킬은 공개 모음
[ListeningMind-Daas/lm-skills](https://github.com/ListeningMind-Daas/lm-skills) 에 있습니다. 두 저장소의 산출물(csv·json)을 이 스킬에 그대로 넣으면 됩니다.

## 라이선스

MIT — `LICENSE`. 견본 데이터는 모두 가짜 값이며 특정 브랜드·고객을 가리키지 않습니다.
