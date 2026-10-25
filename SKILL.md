---
name: lm-chart
description: >-
  데이터(csv·json·표·API 응답을 펼친 행)를 표준 차트 26종 중 하나로 그리는 스킬 — 코드가 데이터 모양을 읽어 차트를 고르고
  inline SVG 로 그린 뒤 검사까지 한다. "차트 그려줘", "이 데이터 시각화해줘", "그래프로 보여줘", "어떤 차트가 맞아?",
  csv·json 파일을 첨부하며 차트·그래프·시각화를 요청할 때, 리포트 안 숫자 표를 그림으로 바꿔 달라고 할 때 켠다.
  외부 차트 라이브러리·CDN·캔버스를 쓰지 않고, LLM 이 차트 유형을 고르지 않는다. 선택 규칙·렌더러·검사·카탈로그 문서가 이 스킬 안에
  있어 혼자서 돈다(API 호출 없음 · 파이썬 표준 라이브러리만).
metadata:
  build: v0.2.0
  version: "0.2.0"
  author: Ascent AI
  category: rendering
  tags: 차트, 시각화, inline SVG, 카탈로그 26종
---

# lm-chart — 데이터 한 파일 → 표준 차트 한 장

**한 줄** — 사용자가 데이터와 "차트 그려줘"를 주면, 명령 하나로 코드가 차트를 고르고 그려 페이지로 낸다. 에이전트는 단위·기간·의도를
묻고, 결과(페이지 경로 · 1위 차트와 이유 · 대안)를 보고하고, 수정 요청을 옵션으로 옮기기만 한다.

**필요한 것**: Python 3.10 이상. 설치할 패키지·네트워크·API 키가 없다. 이 폴더만 있으면 된다.
**설치**: `git clone https://github.com/ListeningMind-Daas/lm-chart-skill ~/.claude/skills/lm-chart` (폴더 이름은 `lm-chart`).

| 파일 | 역할 |
|---|---|
| `scripts/chart.py` | 진입점 — 인자를 `scripts/viz.py` 에 그대로 넘긴다 |
| `scripts/viz.py` | 명령: catalog · select · render · check · gallery · reference · auto |
| `lib/viz.py` | 차트 26종의 조건·선택 규칙·렌더러·검사 |
| `lib/viz_samples.py` · `lib/palette_check.py` | 견본 26종(가짜 값) · 팔레트 계산 검증(OKLab · 색각 · 대비) |
| `references/viz-catalog.md` | 차트마다 쓰는 조건 · 그리는 규칙 · 값의 상태 · 발견 문장 틀 · 기본 선택 순서 |
| `references/quick-reference.md` | **생성 파일** — 차트 26종 이름·질문 · 의도 목록(`scripts/build_quick_reference.py` 로 다시 만든다) |

## 절차 — 호출 한 번

```bash
C=<이 폴더>/scripts/chart.py
python3 $C auto <데이터.csv|json> --unit <단위> --period <기간> [--title …] [--source …] [--intent …] [--compare] [--theme executive] [--json]
python3 $C check <페이지.html>          # 결과 페이지를 다시 검사(auto 가 그린 차트는 통과해야 한다)
```

1. **데이터와 두 값을 확인한다.** csv(머리행 있음) 또는 json(행 목록 `[{…}]` · viz-data 스펙). `--unit`(예: `건/월` · `%`)과 `--period`(예: `2025-09~2026-08`)가
   없으면 렌더하지 않는다(종료 코드 2) — 사용자 발화에 없으면 **사용자에게 묻는다**, 짐작하지 않는다. API 응답 원본이면 `data` 를 먼저 행으로 펼친다.
   가로형 csv(열 이름이 YYYY-MM)는 세로형(월 열 하나 + 값 열 하나)으로 바꿔 준다.
2. **의도는 발화에 있을 때만.** "추이"·"비교"·"구성"·"성수기"·"여정"·"증감 분해" 같은 말이 있으면 `--intent`(`references/quick-reference.md` 의 의도 표)를 준다.
   의도는 힌트다 — 데이터가 조건을 못 채우면 코드가 기본 선택으로 돌아가고 `intent_note` 에 이유를 남긴다. 사용자가 "어떤 차트가 맞는지 보여줘"라면 `--compare`(상위 3 모두 그림).
3. **`auto` 를 한 번 호출한다.** 결과: 페이지(`<데이터>.viz.html` 또는 `--out`) · 1위 차트와 선택 이유 · 다른 선택 2개와 이유 · 데이터에서 읽은 것(힌트).
4. **사용자에게 보고한다** — 페이지 경로, 1위 차트 이름과 이유, 대안 2개와 이유를 코드 출력 그대로. 이유를 다시 쓰거나 숫자를 보태지 않는다
   (차트 위 '발견 한 줄'은 코드가 데이터에서 계산한 문장이고, 그 아래 '근거' 줄이 계산식이다). 단위·기간·출처는 페이지 부제에 이미 있다.
5. **수정 요청은 옵션으로만 옮긴다.** json 스펙의 `options` 에 적고 다시 `auto`(또는 `render --chart`)를 돌린다. SVG 를 손으로 고치지 않는다.

| 사용자 말 | 옵션 |
|---|---|
| "우리 브랜드만 색으로" · "A 를 강조" | `options.emphasis: ["A"]` |
| "발견 문장 빼줘" · "이 문장으로" | `options.finding: "off"` 또는 문장(숫자는 차트 글자에 있는 것만 — 아니면 멈춤) |
| "제목을 결론으로" (경영진 보고) | `options.title_mode: "action"` — 코드가 계산한 발견 문장이 제목 자리에 |
| "차트 아래 결론 한 줄" | `options.takeaway: "…"` — 숫자는 차트 글자·근거 줄에 있는 것만(아니면 멈춤) |
| "연령 순서대로" · "단계 순서는 …" | `options.order: ["10대", "20대", …]` |
| "작년 → 올해 변화를 기여로 쪼개서" | `options.bridge: {"start": "2025-08", "end": "2026-08"}` (증감 다리 · 시작 + 기여 합 = 끝이어야 함) |
| "여정 단계를 5개로" | `options.steps: 5` (여정 지도) |
| "상위 8개만" | `options.top_n: 8` |
| "기준 검색어는 X" (양방향 나무) | `options.seed: "X"` |
| "로그 눈금으로" | `options.log_x` / `options.log_y: true` |
| "점마다 숫자를" (짧은 추이선) | `options.label_points: "all"` — 점 12개 이하에서만 |
| "예측 구간 표시" · "최신 달은 미완결" | `options.forecast_from` · `options.incomplete_from: "YYYY-MM"` |
| "그림 번호·각주·출처" | 스펙 `exhibit` · `footnotes`(2개까지) · `source` |
| "경영진 보고 스타일로" | `--theme executive` — 강조 네이비·회색 맥락·감소는 빨강·제목 한 단계 크게(차트 선택은 그대로) |
| "다른 차트로" | `--chart <코드 이름>` — 조건을 못 채우면 멈춘다(종료 코드 2). 조건을 바꾸지 말고 데이터를 다시 본다 |

옵션 전체·값의 상태(`null` · `{"state": "not_queried"}` · `below_gate` · `not_returned`)·측정값 종류(`kind`)는 `references/viz-catalog.md` §2·§2b.

## 하지 않는 것

- **SVG·HTML 차트를 직접 쓰지 않는다.** 차트는 `auto`/`render` 출력만 쓴다. 카탈로그에 없는 차트(파이·이중 축·워드클라우드·게이지·3D)는 만들지 않는다 — 필요하면 코드·문서·견본·테스트를 함께 바꾼다.
- **외부 차트 라이브러리·CDN·캔버스를 쓰지 않는다**(Chart.js·D3·Recharts·AntV 등). 산출물은 inline SVG 와 표뿐이라 어디서나 열리고, 글자가 그대로 남아 검사할 수 있다.
- **LLM 이 차트 유형을 고르지 않는다.** 선택은 `select` 의 결과다. 사용자가 유형을 지정하면 `--chart` 로 넘기고, 코드가 거절하면 그 이유를 전한다.
- **데이터 값을 고치거나 보태지 않는다.** 결측은 `null`, 조회하지 않은 칸·기준 미달은 상태로 적는다. 발견 문장·결론 줄의 숫자는 차트에 있는 값과 계산식에서만 나온다.
- 같은 입력이면 같은 그림이다(난수 없음). 다른 결과가 필요하면 데이터나 옵션을 바꾼다.

## 검사

- `auto` 가 만든 페이지는 `check` 를 통과해야 한다(카탈로그 밖 차트 · 단위/기간 누락 · 캔버스·라이브러리 흔적 · 발견/결론 문장의 숫자가 차트에 없음 → 종료 코드 11).
  통과하지 못하면 보고하지 말고 원인을 본다.
- 팔레트를 바꾸면 `python3 lib/palette_check.py "<hex,…>" --mode light|dark` 로 계산해 확인한다(눈으로 판정하지 않는다).

## 쓰임새

- "데이터가 손에 있고 차트만 필요한" 단발 요청용이다. 데이터를 모으는 일은 범위 밖 — 검색 데이터는 ListeningMind DaaS API 로 모으고,
  시장 분석 스킬은 공개 모음 [ListeningMind-Daas/lm-skills](https://github.com/ListeningMind-Daas/lm-skills) 를 쓴다. 그 산출물(csv·json)을 이 스킬에 넣는다.
- 다른 코드 안에서 쓰려면 `lib/viz.py` 의 `auto(spec)` / `render(spec)` 를 직접 부른다 — 계약은 `references/viz-catalog.md` §1.
- 빠른 참조가 카탈로그와 어긋나면 `python3 scripts/build_quick_reference.py` 로 다시 만든다(손으로 고치지 않는다 · `--check` 로 대조).
