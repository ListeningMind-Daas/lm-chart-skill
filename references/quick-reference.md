# lm-chart 빠른 참조 — 표준 차트 26종 · 의도 19가지

> 생성 파일 — 손으로 고치지 않는다. `python3 .claude/skills/lm-chart/scripts/build_quick_reference.py` 가
> `scripts/viz.py catalog --json` 과 `lib/viz.py` 의 `INTENTS` 에서 만든다.
> 조건·그리는 규칙·값의 상태는 `references/viz-catalog.md` 를 본다.

## 차트 — 코드가 데이터 모양으로 고른다(사람·LLM 이 고르지 않는다)

| 코드 이름(`--chart`) | 이름 | 영문 | 답하는 질문 |
|---|---|---|---|
| `kpi` | KPI·점수 카드 | KPI card | 핵심 값·점수·등급은 얼마인가 |
| `hbar` | 순위 가로 막대 | Horizontal bar chart | 어느 항목이 얼마나 큰가(순위) |
| `diverging_bar` | 증감 막대 | Diverging bar chart | 무엇이 늘고 줄었나 |
| `grouped_bar` | 묶음 막대 | Grouped bar chart | 같은 항목을 몇 개 조건으로 나눠 비교하면 |
| `stacked_100` | 100% 구성 막대 | 100% stacked bar chart | 그룹마다 무엇으로 구성되나 |
| `donut` | 도넛 | Donut chart | 전체가 몇 조각으로 나뉘나(5조각 이하) |
| `line` | 추이선 | Line chart | 언제 늘고 줄었나(계열 3개 이하) |
| `spark_grid` | 스파크라인 묶음 | Sparklines (small multiples) | 여러 항목의 추이를 한눈에 |
| `season_heatmap` | 성수기 달력 | Seasonality heatmap | 어느 달에 수요가 몰리나 |
| `heatmap` | 교차 히트맵 | Heatmap | 두 기준이 만나는 칸 중 어디가 진한가 |
| `scatter_quadrant` | 사분면 버블 | Bubble chart (quadrant) | 두 기준으로 나누면 어디에 있나(기회·경쟁) |
| `bump` | 순위 변동 | Bump chart | 순위가 시점·집단에 따라 어떻게 바뀌나 |
| `flow_tree` | 흐름 나무 | Tree diagram | 검색이 어디서 어디로 갈라지나 |
| `table` | 표 | Table | 정확한 값이 필요하다 · 차트 조건을 못 채운다 |
| `table_graphic` | 그래픽 표 | Table with in-cell graphics | 정확한 값과 크기·추이·구성을 행마다 함께 |
| `heat_table` | 히트 표 | Heat table | 글이 긴 두 기준의 교차 칸 중 어디가 진한가 |
| `back_to_back` | 맞댄 막대 | Back-to-back bar chart (butterfly chart) | 같은 항목의 반대 두 값(선호 대 회피 · 유입 대 이탈) |
| `pair_bars` | 쌍 전이 막대 | Pair transition bar list | 어디서 어디로 한 단계 많이 이동하나 |
| `bidirectional_tree` | 양방향 나무 | Bidirectional tree | 기준 검색어 앞에서 무엇을 찾다 오고, 뒤에 어디로 가나 |
| `edge_table` | 관계 표 | Edge list (network as table) | 나무 모양이 아닌 그물형 연결은 무엇과 무엇이 이어지나 |
| `radar` | 레이더 | Radar chart | 몇 개 축의 점수를 한 모양으로 견주면(계열 3개 이하) |
| `funnel` | 퍼널 | Funnel chart | 단계마다 얼마나 남고 얼마나 빠지나 |
| `journey_map` | 여정 지도 | Sankey diagram (journey map) | 검색이 단계를 거치며 어디서 어디로 흐르나 |
| `treemap` | 수요 지도 | Treemap (demand map) | 시장이 어떤 덩어리로 나뉘고 어느 덩어리가 큰가 |
| `knowledge_graph` | 지식 그래프 | Knowledge graph (network diagram) | 항목 종류가 다른 것들이 무엇과 무엇으로 이어지나 |
| `waterfall` | 증감 다리 | Waterfall chart (bridge) | 시작에서 끝까지 무엇이 얼마나 보태고 깎았나 |

## 의도(`--intent`) — 힌트이지 강제가 아니다

데이터가 조건을 못 채우면 기본 선택으로 돌아가고 결과의 `intent_note` 에 이유가 남는다.

| 의도 | 우선 차트(앞이 먼저) |
|---|---|
| `kpi` | KPI·점수 카드(`kpi`) |
| `compare` | 순위 가로 막대(`hbar`) → 묶음 막대(`grouped_bar`) → 증감 막대(`diverging_bar`) |
| `change` | 증감 막대(`diverging_bar`) → 추이선(`line`) |
| `trend` | 추이선(`line`) → 스파크라인 묶음(`spark_grid`) |
| `season` | 성수기 달력(`season_heatmap`) → 추이선(`line`) |
| `composition` | 100% 구성 막대(`stacked_100`) → 도넛(`donut`) |
| `relation` | 사분면 버블(`scatter_quadrant`) |
| `matrix` | 교차 히트맵(`heatmap`) → 히트 표(`heat_table`) |
| `rank_change` | 순위 변동(`bump`) |
| `flow` | 흐름 나무(`flow_tree`) → 양방향 나무(`bidirectional_tree`) → 쌍 전이 막대(`pair_bars`) |
| `pair` | 맞댄 막대(`back_to_back`) |
| `rank_list` | 그래픽 표(`table_graphic`) |
| `detail` | 그래픽 표(`table_graphic`) → 표(`table`) |
| `profile` | 레이더(`radar`) → 묶음 막대(`grouped_bar`) |
| `funnel` | 퍼널(`funnel`) → 순위 가로 막대(`hbar`) |
| `journey` | 여정 지도(`journey_map`) → 양방향 나무(`bidirectional_tree`) → 흐름 나무(`flow_tree`) |
| `map` | 수요 지도(`treemap`) → 순위 가로 막대(`hbar`) |
| `network` | 지식 그래프(`knowledge_graph`) → 관계 표(`edge_table`) |
| `bridge` | 증감 다리(`waterfall`) → 증감 막대(`diverging_bar`) |
