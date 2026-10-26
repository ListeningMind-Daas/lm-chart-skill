# lm-chart — 데이터 파일 한 장을 보고용 차트 한 장으로

csv·json 데이터를 주면 **데이터 모양에 맞는 차트를 골라 HTML 한 장으로 그려 주는** 에이전트 스킬입니다.
리포트에 바로 붙일 수 있고, 별도 프로그램 없이 어디서나 열립니다. Claude Code·Claude Desktop 등 스킬을 읽는 에이전트 호스트에 그대로 넣어 씁니다.

## 이런 분이 씁니다

검색 데이터·매출·조사 수치를 **표로 갖고 있고** "이걸 그림으로 보여줘"가 필요한 마케터·기획자·분석가.
데이터를 모으는 일은 이 스킬의 범위 밖입니다 — 아래 '다른 스킬과의 관계'를 보세요.

## 무엇이 나오나

- **차트 한 장 + 같은 데이터의 표**가 든 HTML 파일 한 개 (`<데이터 이름>.viz.html`). 그림이 HTML 안에 글자로 들어 있어(inline SVG) 파일 하나로 열리고, 글자가 남아 검사가 됩니다.
- 차트 위 **발견 한 줄**과 그 아래 **근거 줄** — 데이터에서 계산한 요약 문장과 계산식. 사람이 쓴 결론 줄의 숫자도 차트에 있는 값이어야 렌더됩니다.
- "경영진 보고 스타일" 옵션(`--theme executive`) — 강조 네이비·회색 맥락·감소는 빨강.

## 어떻게 쓰나 (Claude 앱에서)

1. 아래 설치 명령 한 줄.
2. 데이터 파일을 첨부하고 **"차트 그려줘"**.
3. 단위(예: 건/월)와 기간(예: 2025-09~2026-08)을 물으면 답합니다 — 이 둘이 없으면 그리지 않습니다(짐작하지 않습니다).
4. 원하는 차트가 있으면 말합니다 — "추이로", "도넛으로", "어떤 차트가 맞는지 보여줘"(상위 3개를 나란히).
   말이 없으면 데이터 모양에 맞춰 골라 주고, **같은 데이터면 늘 같은 그림**이 나옵니다.

차트 선택 규칙은 코드에 있어 에이전트가 감으로 고르지 않습니다. 원하는 차트가 데이터 조건에 맞지 않으면 이유를 알려 주고 다른 선택을 제안합니다.

## 설치

```bash
git clone https://github.com/ListeningMind-Daas/lm-chart-skill ~/.claude/skills/lm-chart
```

프로젝트 안에서만 쓰려면 `<프로젝트>/.claude/skills/lm-chart` 에 둡니다. **폴더 이름은 `lm-chart` 여야 합니다** — zip 으로 받았다면 풀린 폴더 이름을 `lm-chart` 로 바꿉니다.
필요한 것은 Python 3.10 이상뿐입니다. 설치할 패키지·네트워크·API 키가 없습니다.

## 바로 써 보기 (터미널)

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
지식 그래프 · 증감 다리(워터폴) · KPI·점수 카드.

어떤 데이터 모양에 어떤 차트가 고르게 되는지, 각 차트가 지키는 규칙, 값이 없는 칸(결측·조회 안 함·기준 미달·미반환)을 어떻게 그리는지는
`references/viz-catalog.md` 에 있습니다. 짧은 표는 `references/quick-reference.md`.

## 다른 스킬과의 관계

- **이 스킬은 그리기만 합니다.** 검색 데이터는 ListeningMind DaaS API 로 모으고, 시장을 읽는 분석 스킬은 공개 모음
  [ListeningMind-Daas/lm-skills](https://github.com/ListeningMind-Daas/lm-skills)(시장 분석 11종) 에 있습니다. 그 스킬들이 내는 csv·json 을 이 스킬에 그대로 넣으면 됩니다.
  순서: 시장 분석 스킬 → 산출물 파일 → lm-chart.
- 고객 배포본 [lima-universal-starter](https://github.com/ListeningMind-Daas/lima-universal-starter) 의 리포트도 **같은 차트 엔진**으로 그려집니다. 스타터 사용자는 리포트 밖에서 단발로 차트가 필요할 때만 이 스킬을 직접 부릅니다.
- 다른 코드 안에서 쓰려면 `lib/viz.py` 의 `auto(spec)` / `render(spec)` 를 직접 부릅니다 — 계약은 `references/viz-catalog.md` §1.

## 하지 않는 것

- 데이터 수집·API 호출(사용량 과금 없음) · 데이터 값 고치기(결측은 결측으로 표시).
- 외부 차트 라이브러리(Chart.js·D3 등)나 인터넷에서 받아오는 부품 — 산출물은 inline SVG 와 표뿐이라 어디서나 열립니다.
- 파이·이중 축·게이지·3D 처럼 읽기 어려운 차트 — 대신 같은 뜻의 표준 차트(예: 파이 → 도넛)를 제안합니다.

## 에이전트가 따르는 절차

`SKILL.md` 가 에이전트용 설명서입니다 — 단위·기간을 확인하고, `auto` 를 한 번 부르고, 결과를 그대로 보고하고, 수정 요청은 옵션으로만 옮깁니다.

## 라이선스

MIT — `LICENSE`. 견본 데이터는 모두 가짜 값이며 특정 브랜드·회사를 가리키지 않습니다.
