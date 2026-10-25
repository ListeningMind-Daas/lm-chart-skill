"""표준 시각화 카탈로그 · 데이터 기반 차트 선택 · 결정론 inline SVG 렌더러 (API 호출 없음).

규칙 문서: references/viz-catalog.md (차트 id·조건·인코딩 규칙 — 이 파일의 CATALOG와 테스트가 맞춰 본다)

에이전트는 차트를 고르지 않는다. 데이터를 viz-data/v1 스펙으로 넘기면
  profile(spec)  → 데이터 모양(차원·측정값·시간·관계·구성비 여부)
  select(spec)   → 카탈로그에서 차트 하나 + 고른 이유 + 쓸 수 있었던 다른 차트 + 못 쓰는 차트와 이유
  render(spec)   → <figure class="viz" data-viz=…> (SVG·단위·기간·「전체 K개 중 N개」 캡션)
  check_html(t)  → 산출물에 들어간 차트가 카탈로그·캡션 규칙을 지켰는지
의도(intent)는 힌트일 뿐이다 — 데이터가 그 차트의 조건을 못 채우면 기본 선택으로 돌아가고 이유를 남긴다.
차트를 직접 지정(chart=…)해도 조건을 못 채우면 VizError로 멈춘다.

스펙 규약
- share·change 값은 비율(0.12 = 12%)로 넣는다 · index는 1.0 = 기준 · score는 0~100 · rank는 1 = 1위
- unit·period는 필수(차트마다 단위·기간)
- 값의 상태(viz-catalog.md §2b): 숫자 = 값(0도 값) · None = 결측(응답에 그 칸이 없음) ·
  {"state": "not_queried"} 조회 안 함 · {"state": "below_gate", "base": 12} 기저 미달 · {"state": "not_returned"} 미반환 ·
  options.incomplete_from = "YYYY-MM" 이후 시점은 미완결 · 스펙 not_returned = [요청했는데 응답에 없는 항목]
"""
from __future__ import annotations

import html
import math
import re
import statistics
from dataclasses import dataclass, field

SCHEMA = "viz-data/v1"

# 색 — 호스트 토큰이 있으면 따르고, 없으면 기본값. PAL 3슬롯 = 추이선 계열 상한 · MIXCOL 6슬롯 = 구성 조각(§6b)
PALETTE = {   # 계열 색 6슬롯 — lib/palette_check 로 검증(테스트가 지킨다) · 다크는 라이트 색상을 OKLab 명도 0.60 으로 옮긴 값
    "light": ['#2563eb', '#0d9488', '#d97706', '#db2777', '#65a30d', '#0891b2'],
    "dark": ['#3575fe', '#0d9488', '#c06500', '#de2b79', '#579400', '#008eaf'],
}
SURFACE = {"light": "#ffffff", "dark": "#161a22"}                 # 차트가 놓이는 패널색(검증 바탕)
STATUS = {"light": {"up": "#0d9488", "down": "#dc2626", "dim": "#cbd2dc"},
          "dark": {"up": "#0d9488", "down": "#e4312e", "dim": "#3b4252"}}


TYPE_SCALE = {"title": 16, "finding": 14, "body": 12, "tick": 10.5}   # 글자 크기 4단계(px) — 제목 · 발견 · 본문(부제·라벨) · 눈금


# 테마 — 토큰만 바꾼다(차트 선택·기하는 그대로). executive = 경영진 보고 스타일(2026-10-25 컨설팅 시각화 검토에서 채택):
# 강조 1색 네이비 · 나머지 회색 · 빨강은 감소·위험에만 · 제목 한 단계 크게. 네이비는 #15296B(참조 스킬 값)를 그대로 쓰지 않고
# 팔레트 검사의 명도 범위 안으로 옮긴 값(라이트 OKLab L 0.45 · 다크 0.60) — 검사가 지킨다
THEMES = {
    "default": {},
    "executive": {"light": {"viz-1": "#375196", "viz-dim": "#d1d5db", "down": "#b91c1c"},
                  "dark": {"viz-1": "#6f8fe0", "viz-dim": "#3b4252", "down": "#e4312e"},
                  "type": {"title": 18, "finding": 15}},
}


def css_tokens(mode: str, theme: str = "default") -> str:
    """페이지 CSS 토큰 한 줄 — 계열 6색 · 증가/감소 · 강조 바깥 회색 · 글자 크기 4단계(테마가 있으면 그 값으로 덮어씀)"""
    if theme not in THEMES:
        raise VizError(f"테마 '{theme}'는 없음 — {sorted(THEMES)}")
    th = THEMES[theme]
    pal = list(PALETTE[mode]); st = dict(STATUS[mode]); ts = dict(TYPE_SCALE)
    over = th.get(mode, {})
    if "viz-1" in over:
        pal[0] = over["viz-1"]
    st["dim"] = over.get("viz-dim", st["dim"]); st["down"] = over.get("down", st["down"])
    ts.update(th.get("type", {}))
    t = [f"--viz-{i + 1}:{c}" for i, c in enumerate(pal)]
    fs = [f"--viz-fs-{k}:{v}px" for k, v in ts.items()]
    return ";".join(t + [f"--up:{st['up']}", f"--down:{st['down']}", f"--viz-dim:{st['dim']}"] + fs)


def theme_palette(mode: str, theme: str) -> list:
    """테마가 적용된 계열 6색(팔레트 검사용)"""
    pal = list(PALETTE[mode]); over = THEMES[theme].get(mode, {})
    if "viz-1" in over:
        pal[0] = over["viz-1"]
    return pal


PAL = [f"var(--viz-{i + 1},{c})" for i, c in enumerate(PALETTE["light"][:3])]
INK, MUTED, LINE = "var(--ink,#1f2430)", "var(--muted,#6b7280)", "var(--line,#e5e7eb)"
UP, DOWN = "var(--up,#0d9488)", "var(--down,#dc2626)"
DIM = "var(--viz-dim,#cbd2dc)"                                     # 강조(emphasis) 바깥 계열 — 바탕에 가까운 회색
MIXCOL = [f"var(--viz-{i + 1},{c})" for i, c in enumerate(PALETTE["light"])]   # 구성 조각 6슬롯 · 7번째부터는 '기타'(회색)
MAX_PARTS = 6


def _series_color(name, j, emp):
    """강조 목록이 있으면 그 계열만 1번 색, 나머지는 회색 — 색이 '어느 것이 중요한가'를 나른다"""
    if emp:
        return PAL[0] if name in emp else DIM
    return PAL[j % len(PAL)]


REST_LABELS = ("기타", "그 외", "나머지 묶음")


def _emphasis(o, names) -> tuple:
    """강조 목록을 데이터에 있는 이름으로 좁힌다. 하나도 없으면 강조 없이 그리고 캡션에 그 사실을 적는다(거짓 캡션 방지)"""
    want = [x for x in (o.get("emphasis") or []) if x]
    if not want:
        return set(), ""
    hit = {x for x in want if x in names}
    if not hit:
        return set(), f"강조 항목({', '.join(map(str, want))})이 데이터에 없어 강조 없이 그림"
    missing = [x for x in want if x not in names]
    note = f"색 = 강조({', '.join(sorted(map(str, hit)))}) · 나머지 회색" + (f" · 데이터에 없는 강조 항목 {len(missing)}개 무시" if missing else "")
    return hit, note


def _fold_parts(parts, total_of):
    """조각이 6개를 넘으면 합계 상위 5개 + 묶음. (유지할 조각 목록, 묶인 조각 목록, 묶음 이름)
    묶음 이름은 데이터에 이미 있는 조각 이름과 겹치지 않게 고른다('기타'가 데이터에 있으면 '그 외')."""
    if len(parts) <= MAX_PARTS:
        return list(parts), [], None
    keep = sorted(parts, key=lambda b: (-total_of(b), str(b)))[: MAX_PARTS - 1]
    label = next((l for l in REST_LABELS if l not in parts), f"묶음({len(parts) - len(keep)})")
    return keep + [label], [b for b in parts if b not in keep], label


def _is_rest(part, label) -> bool:
    return part == label or part == "기타"
FONT = "font-family:inherit"

MEASURE_KINDS = ("count", "share", "index", "score", "rank", "change", "value")
INTENTS = {
    "kpi": ["kpi"],
    "compare": ["hbar", "grouped_bar", "diverging_bar"],
    "change": ["diverging_bar", "line"],
    "trend": ["line", "spark_grid"],
    "season": ["season_heatmap", "line"],
    "composition": ["stacked_100", "donut"],
    "relation": ["scatter_quadrant"],
    "matrix": ["heatmap", "heat_table"],
    "rank_change": ["bump"],
    "flow": ["flow_tree", "bidirectional_tree", "pair_bars"],
    "pair": ["back_to_back"],
    "rank_list": ["table_graphic"],
    "detail": ["table_graphic", "table"],
    "profile": ["radar", "grouped_bar"],
    "funnel": ["funnel", "hbar"],
    "journey": ["journey_map", "bidirectional_tree", "flow_tree"],
    "map": ["treemap", "hbar"],
    "network": ["knowledge_graph", "edge_table"],
    "bridge": ["waterfall", "diverging_bar"],
}


class VizError(ValueError):
    pass


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


# ── 데이터 모양 ───────────────────────────────────────────────────────────
_TIME_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
_KIND_HINTS = [("rank", re.compile(r"rank|순위")), ("share", re.compile(r"share|ratio|pct|비중|점유|비율")),
               ("change", re.compile(r"change|yoy|delta|growth|증감|성장")), ("score", re.compile(r"score|점수")),
               ("index", re.compile(r"index|lift|지수"))]


@dataclass
class Measure:
    field: str
    kind: str = "count"
    unit: str | None = None


@dataclass
class Profile:
    rows: list
    dims: list = field(default_factory=list)          # 시간 축 제외 범주 차원(순서 = 스펙 순서)
    measures: list = field(default_factory=list)      # [Measure]
    time: str | None = None
    points: list = field(default_factory=list)        # 시간 축 값(정렬)
    ordered_dim: str | None = None                    # 순서가 있는 차원(시간 점이 6개 미만이면 시간이 여기로)
    card: dict = field(default_factory=dict)          # 차원별 고유 값 수
    edges: list = field(default_factory=list)
    is_tree: bool = False
    part_of_whole: bool = False
    has_negative: bool = False
    completeness: float = 1.0
    states: dict = field(default_factory=dict)        # (id(행), 측정값) → 상태 dict — 행의 값은 숫자 또는 None 으로 바꿔 둔다
    incomplete_from: str | None = None
    series_fields: list = field(default_factory=list)  # 칸 값이 숫자 목록(표 속 스파크라인)
    mix_fields: list = field(default_factory=list)     # 칸 값이 {조각: 비율}(표 속 100% 구성 막대)
    paths: list = field(default_factory=list)          # 검색 경로 [[키워드, …], …]
    seed: str | None = None
    stats: dict = field(default_factory=dict)          # 측정값별 {n, min, max, spread(양수 최대/최소), top_share(최대/합)}
    ordered_guess: list = field(default_factory=list)  # 이름으로 보아 순서가 있는 범주(연령대·단계·월·구간)
    time_gaps: int = 0                                 # 시간 축(YYYY-MM) 안에서 빠진 달 수
    hints: list = field(default_factory=list)          # 프로파일에서 읽은 제안 문구(에이전트·사람용)
    opposite: bool = False                             # 두 값이 반대 방향(선호·회피 등)이라고 선언됨 — 맞댄 막대 기본 선택 조건
    nodes: list = field(default_factory=list)          # 연결의 항목 정보 [{id, class}] — 지식 그래프의 종류 색
    order: list = field(default_factory=list)          # options.order — 사람이 준 범주 순서(퍼널 단계 등)
    bridge: dict = field(default_factory=dict)         # options.bridge {start, end} — 워터폴의 시작·끝 행 이름

    @property
    def d1(self):
        return self.dims[0] if self.dims else None

    @property
    def d2(self):
        return self.dims[1] if len(self.dims) > 1 else None

    @property
    def series_count(self) -> int:
        if self.d1:
            return self.card[self.d1]
        return max(1, len(self.measures))

    def kinds(self) -> set:
        return {m.kind for m in self.measures}

    def summary(self) -> dict:
        return {"dims": {d: self.card[d] for d in self.dims}, "measures": {m.field: m.kind for m in self.measures},
                "time": self.time, "time_points": len(self.points), "ordered_dim": self.ordered_dim,
                "rows": len(self.rows), "edges": len(self.edges), "is_tree": self.is_tree,
                "part_of_whole": self.part_of_whole, "has_negative": self.has_negative, "completeness": self.completeness,
                "stats": self.stats, "ordered_guess": self.ordered_guess, "time_gaps": self.time_gaps}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))


def _guess_kind(name: str) -> str:
    low = name.lower()
    for kind, rx in _KIND_HINTS:
        if rx.search(low):
            return kind
    return "count"


def _measures(spec_fields, rows) -> list:
    ms = []
    for m in spec_fields:
        if isinstance(m, str):
            ms.append(Measure(m, _guess_kind(m)))
        else:
            kind = m.get("kind") or _guess_kind(m["field"])
            if kind not in MEASURE_KINDS:
                raise VizError(f"측정값 종류 '{kind}'는 없음 — {MEASURE_KINDS}")
            ms.append(Measure(m["field"], kind, m.get("unit")))
    return ms


def _tree(edges) -> bool:
    parents = {}
    for e in edges:
        if e["target"] in parents and parents[e["target"]] != e["source"]:
            return False
        parents[e["target"]] = e["source"]
    nodes = {e["source"] for e in edges} | {e["target"] for e in edges}
    roots = [n for n in nodes if n not in parents]
    if len(roots) != 1:
        return False
    for n in nodes:                                   # 순환 검사
        seen, cur = set(), n
        while cur in parents:
            if cur in seen:
                return False
            seen.add(cur); cur = parents[cur]
    return True


_ORD_RE = re.compile(r"^\s*\d+(\.\d+)?\s*(대|세|월|분기|단계|등급|위|년|일|주차|차|기|인치|만원|%)\s*(초반|중반|후반|이상|이하|미만)?\s*$"
                     r"|^\s*\d+\s*[~\-–]\s*\d+\s*(세|대|개월|만원|%)?\s*(이상|이하|미만)?\s*$"
                     r"|^\s*(초반|중반|후반)\s*$")


def _looks_ordered(values) -> bool:
    """이름만 보고 순서 있는 범주인지 — 숫자 뒤에 단위·구간 표식이 붙어 끝나는 이름(10대 · 20대 초반 · 50대 이상 · 20~24 · 3분기 · 2단계)만 센다.
    숫자로 시작해도 명목 이름(3M · 11번가 · 7일 배송 · 1+1 행사 · 2024년형 · 1리터 우유)은 순서가 아니다. 값이 모두(100%) 맞을 때만 순서로 본다"""
    vals = [str(v) for v in values if v is not None]
    return len(vals) >= 3 and all(_ORD_RE.search(v) for v in vals)


_SUB_ORDER = {"초반": 0, "중반": 1, "후반": 2, "이하": -1, "미만": -1, "이상": 3}


def _nat_key(v):
    """자연 정렬 — '5단계' < '10단계' · '20대 초반' < '20대 중반' < '20대 후반' < '20대 이상'"""
    sv = str(v)
    m = re.search(r"\d+(\.\d+)?", sv)
    sub = next((k for k in _SUB_ORDER if k in sv), None)
    return (float(m.group(0)) if m else float("inf"), _SUB_ORDER.get(sub, 0.5), sv)


def _month_gaps(points) -> int:
    ms = [x for x in points if re.match(r"^\d{4}-\d{2}$", str(x))]
    if len(ms) < 2:
        return 0
    idx = lambda t: int(t[:4]) * 12 + int(t[5:7])
    return idx(ms[-1]) - idx(ms[0]) + 1 - len(ms)


def _hints(p) -> list:
    """데이터에서 읽은 것 → 제안. 결정은 사람·호출한 코드가 한다"""
    h = []
    for m in p.measures:
        st = p.stats.get(m.field) or {}
        if m.kind == "count" and st.get("spread") and st["spread"] >= 1000:
            h.append(f"'{m.field}' 값이 {st['spread']:,.0f}배 범위로 퍼져 있음 — 산점도는 로그 눈금(자동) · 막대는 상위 N + 기타")
    if len(p.dims) == 1 and len(p.measures) == 1 and not p.time and p.card.get(p.d1, 0) >= 3:
        st = p.stats.get(p.measures[0].field) or {}
        if st.get("top_share") and st["top_share"] >= 0.5:
            top = max(p.rows, key=lambda r: r.get(p.measures[0].field) or 0).get(p.d1)
            h.append(f"'{top}' 하나가 전체의 {st['top_share'] * 100:.0f}% — 이야기가 그 항목이면 그것만 색을 주고 나머지는 회색(강조)")
    for d in p.ordered_guess:
        h.append(f"'{d}'은(는) 이름으로 보아 순서 있는 범주 — 열·막대 순서를 값 크기가 아니라 그 순서로 둔다(아니면 order 로 직접 지정)")
    if p.time_gaps:
        h.append(f"시간 축에 빠진 달 {p.time_gaps}개 — 추이선은 끊긴 선, 칸은 결측으로 표기")
    if p.completeness < 0.5:
        h.append(f"완성도 {p.completeness:.2f} — 차트 대신 표")
    return h


def profile(spec: dict) -> Profile:
    rows = list(spec.get("rows") or [])
    f = spec.get("fields") or {}
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    time = f.get("time")
    if time is None and "dims" not in f:
        time = next((k for k in keys if rows and all(isinstance(r.get(k), str) and _TIME_RE.match(r.get(k)) for r in rows if r.get(k) is not None)), None)
    if "measures" in f:
        measures = _measures(f["measures"], rows)
    else:
        measures = [Measure(k, _guess_kind(k)) for k in keys if k != time and rows and any(_num(r.get(k)) for r in rows)
                    and all(r.get(k) is None or _num(r.get(k)) or _is_state(r.get(k)) for r in rows)]
    mnames = {m.field for m in measures}
    series_f = list(f.get("series") or [k for k in keys if any(isinstance(r.get(k), list) for r in rows)
                                         and all(r.get(k) is None or isinstance(r.get(k), list) for r in rows)])
    mix_f = list(f.get("mix") or [k for k in keys if any(isinstance(r.get(k), dict) and not _is_state(r.get(k)) for r in rows)
                                  and all(r.get(k) is None or (isinstance(r.get(k), dict) and not _is_state(r.get(k))) for r in rows)])
    dims = list(f["dims"]) if "dims" in f else [k for k in keys if k != time and k not in mnames and k not in series_f and k not in mix_f]
    clean, states = [], {}
    for r in rows:                                     # 상태 dict 는 따로 두고 행의 값은 숫자 또는 None 으로
        r2 = dict(r)
        for m in measures:
            v = r2.get(m.field)
            if _is_state(v):
                states[(id(r2), m.field)] = v
                r2[m.field] = v.get("value") if _num(v.get("value")) else None
        clean.append(r2)
    rows = clean
    p = Profile(rows=rows, dims=dims, measures=measures, time=time, edges=list(spec.get("edges") or []), states=states)
    p.incomplete_from = (spec.get("options") or {}).get("incomplete_from")
    p.series_fields, p.mix_fields = series_f, mix_f
    p.paths = [list(x) for x in (spec.get("paths") or []) if x]
    p.seed = (spec.get("options") or {}).get("seed")
    p.nodes = [x for x in (spec.get("nodes") or []) if isinstance(x, dict) and x.get("id") is not None]
    p.order = list((spec.get("options") or {}).get("order") or [])
    p.bridge = dict((spec.get("options") or {}).get("bridge") or {})
    p.opposite = bool((spec.get("options") or {}).get("opposite"))
    p.completeness = float(spec.get("completeness", 1.0))
    p.card = {d: len(dict.fromkeys(r.get(d) for r in rows)) for d in dims}
    if time:
        p.points = sorted({r[time] for r in rows if r.get(time) is not None})
        if len(p.points) < 6:                          # 시점이 적으면 순서 있는 범주로 본다
            p.dims = dims + [time]
            p.card[time] = len(p.points)
            p.ordered_dim, p.time = time, None
    order = (spec.get("options") or {}).get("order")
    if order and not p.ordered_dim and p.d2:
        p.ordered_dim = p.d2
    if p.edges:
        p.is_tree = _tree(p.edges)
    vals = [r.get(m.field) for r in rows for m in measures]
    p.has_negative = any(_num(v) and v < 0 for v in vals)
    p.part_of_whole = _part_of_whole(p, spec)
    for m in measures:
        xs = [r.get(m.field) for r in rows if _num(r.get(m.field))]
        pos = [x for x in xs if x > 0]
        p.stats[m.field] = {"n": len(xs), "min": min(xs) if xs else None, "max": max(xs) if xs else None,
                            "spread": (max(pos) / min(pos)) if len(pos) >= 2 else None,
                            "top_share": (max(xs) / sum(xs)) if xs and sum(xs) > 0 and all(x >= 0 for x in xs) else None}
    p.ordered_guess = [d for d in p.dims if _looks_ordered(dict.fromkeys(r.get(d) for r in rows))]
    if not p.ordered_dim and p.ordered_guess:
        p.ordered_dim = p.ordered_guess[-1]
    if p.time:
        p.time_gaps = _month_gaps(p.points)
    p.hints = _hints(p)
    return p


def _part_of_whole(p: Profile, spec: dict) -> bool:
    if (spec.get("options") or {}).get("whole") is True:
        return True
    if len(p.measures) != 1 or p.measures[0].kind != "share" or not p.dims:
        return False
    m = p.measures[0].field
    groups = {}
    for r in p.rows:
        key = r.get(p.d1) if len(p.dims) > 1 else None
        if _num(r.get(m)):
            groups[key] = groups.get(key, 0) + r[m]
    return bool(groups) and all(0.97 <= s <= 1.03 for s in groups.values())


# ── 카탈로그 · 조건 ───────────────────────────────────────────────────────
def _ok(cond, why):
    return (True, "") if cond else (False, why)


def _e_kpi(p):
    return _ok(p.measures and not p.time and (not p.dims or len(p.rows) <= 1) and len(p.measures) <= 6,
               "차원 없이 값 1~6개일 때만(행 1개)")


def _e_hbar(p):
    return _ok(len(p.dims) == 1 and p.measures and not p.time and p.card[p.d1] >= 2, "범주 1개 × 값, 항목 2개 이상")


def _signed_measure(p):
    """증감 막대가 그릴 측정값 — 증감 종류 또는 음수가 있는 첫 측정값. 없으면 None"""
    for m in p.measures:
        st = p.stats.get(m.field) or {}
        if m.kind == "change" or (st.get("min") is not None and st["min"] < 0):
            return m
    return None


def _e_diverging(p):
    return _ok(len(p.dims) == 1 and p.measures and not p.time and _signed_measure(p) is not None,
               "증감(change)이거나 음수가 있는 범주 1개 × 값")


def _e_donut(p):
    if not (len(p.dims) == 1 and len(p.measures) == 1 and p.part_of_whole and 2 <= p.card[p.d1] <= 5):
        return False, "합이 전체(100%)인 구성비, 조각 2~5개"
    vals = sorted((r.get(p.measures[0].field) or 0 for r in p.rows), reverse=True)
    if len(vals) >= 2 and vals[1] > 0 and vals[0] / vals[1] < 1.25:
        return False, "가장 큰 조각 ÷ 다음 조각 < 1.25 — 각도로는 비교되지 않아 막대로"
    return True, ""


def _e_stacked(p):
    return _ok(len(p.dims) == 2 and len(p.measures) == 1 and p.part_of_whole and p.card[p.d2] <= 7,
               "그룹마다 합이 100%인 구성비, 조각 7개 이하")


def _e_grouped(p):
    return _ok(len(p.dims) == 2 and len(p.measures) == 1 and p.card[p.d2] <= 4 and p.measures[0].kind != "rank",
               "범주 2개 × 값, 두 번째 범주 4개 이하")


def _e_heatmap(p):
    return _ok(len(p.dims) == 2 and len(p.measures) == 1 and p.card[p.d1] >= 2 and p.card[p.d2] >= 2
               and p.measures[0].kind != "rank", "범주 2개 × 값(교차 2×2 이상)")


def _e_line(p):
    return _ok(p.time and p.measures and len(p.points) >= 6 and p.series_count <= 3 and len(p.dims) <= 1 and p.measures[0].kind != "rank",
               "시점 6개 이상, 계열 3개 이하")


def _e_spark(p):
    return _ok(p.time and len(p.points) >= 6 and len(p.dims) == 1 and p.series_count >= 2, "시점 6개 이상, 계열 2개 이상")


def _e_season(p):
    monthly = p.time and all(len(t) == 7 for t in p.points)
    return _ok(monthly and len(p.points) >= 24 and len(p.dims) <= 1, "월 단위 24개월 이상")


def _e_scatter(p):
    return _ok(len(p.dims) == 1 and len(p.measures) >= 2 and not p.time and len(p.rows) >= 4,
               "항목 4개 이상 × 서로 다른 값 2~3개(x·y·크기)")


def _e_bump(p):
    axis = p.ordered_dim or (p.time if p.time else None)
    steps = p.card.get(axis) if axis in p.card else len(p.points)
    return _ok(p.measures and p.measures[0].kind == "rank" and axis and steps and steps >= 3 and p.d1 and p.d1 != axis,
               "순위(rank) × 순서 있는 축 3단계 이상")


def _e_flow(p):
    return _ok(bool(p.edges) and p.is_tree, "뿌리 하나인 나무 모양 관계(edges)")


def _e_table(p):
    return _ok(bool(p.rows), "행이 있어야 함")


def _avg_len(p, dim) -> float:
    vals = [str(r.get(dim) or "") for r in p.rows]
    return sum(map(len, vals)) / len(vals) if vals else 0.0


def _e_table_graphic(p):
    return _ok(len(p.dims) == 1 and not p.time and bool(p.rows) and bool(p.measures or p.series_fields or p.mix_fields),
               "범주 1개 × 값·추이 목록·구성 칸이 있는 행")


def _e_heat_table(p):
    return _e_heatmap(p)


def _e_back_to_back(p):
    return _ok(len(p.dims) == 1 and len(p.measures) == 2 and not p.time and not p.has_negative and len(p.rows) >= 2
               and p.measures[0].kind == p.measures[1].kind and p.measures[0].kind not in ("rank", "change"),
               "범주 1개 × 같은 종류의 값 2개(음수 없음) — 반대 방향 두 값")


def _e_pair_bars(p):
    return _ok(bool(p.paths) or (bool(p.edges) and any(_num(e.get("value")) for e in p.edges)),
               "경로(paths) 또는 값 있는 연결(edges)")


def _e_bidir(p):
    return _ok(bool(p.paths) and bool(p.seed) and any(p.seed in x for x in p.paths),
               "경로(paths)와 그 안에 나오는 기준 검색어(options.seed)")


def _e_edge_table(p):
    return _ok(bool(p.edges), "관계(edges)가 있어야 함")


def _vals_ok(p, m) -> bool:
    return all(_num(r.get(m.field)) and r[m.field] >= 0 for r in p.rows)


def _e_radar(p):
    return _ok(len(p.dims) == 2 and len(p.measures) == 1 and not p.time and p.measures[0].kind in ("score", "share", "index", "value")
               and 3 <= p.card.get(p.d2, 0) <= 8 and 1 <= p.card.get(p.d1, 0) <= 3 and _vals_ok(p, p.measures[0]),
               "범주 2개(계열 3개 이하 × 축 3~8개) × 같은 눈금의 점수·비율·지수 값(음수·결측 없음)")


def _funnel_order(p):
    if p.order:
        return [s for s in p.order if any(r.get(p.d1) == s for r in p.rows)]
    if _is_ordered(p, p.d1):
        return _cats(p, p.d1)
    return None


def _e_funnel(p):
    if not (len(p.dims) == 1 and len(p.measures) == 1 and not p.time and p.measures[0].kind in ("count", "value") and 3 <= len(p.rows) <= 8 and _vals_ok(p, p.measures[0])):
        return _ok(False, "범주 1개(단계 3~8개) × 건수 · 결측 없음 · 단계 순서(options.order 또는 순서 범주) · 단계마다 줄어드는 값")
    order = _funnel_order(p)
    if not order or len(order) != len(p.rows):
        return _ok(False, "단계 순서가 없음 — options.order 로 단계 순서를 준다")
    m = p.measures[0].field
    v = [next(r[m] for r in p.rows if r.get(p.d1) == s) for s in order]
    return _ok(all(a >= b for a, b in zip(v, v[1:])), "단계마다 값이 줄어야 함(늘어나는 단계가 있으면 순위 막대)")


def _e_journey(p):
    return _ok(len(p.paths) >= 5 and max((len(x) for x in p.paths), default=0) >= 3, "검색 경로 5개 이상 · 3단계 이상인 경로가 있어야 함")


def _e_treemap(p):
    return _ok(1 <= len(p.dims) <= 2 and len(p.measures) == 1 and not p.time and p.measures[0].kind in ("count", "value")
               and len(p.rows) >= 6 and _vals_ok(p, p.measures[0]), "범주 1~2개(그룹 → 항목) × 건수 · 항목 6개 이상 · 음수·결측 없음")


def _e_waterfall(p):
    b = p.bridge
    names = [r.get(p.d1) for r in p.rows] if p.d1 else []
    return _ok(len(p.dims) == 1 and len(p.measures) == 1 and not p.time and p.measures[0].kind in ("count", "value", "change")
               and 3 <= len(p.rows) <= 12 and bool(b.get("start")) and bool(b.get("end")) and b["start"] in names and b["end"] in names
               and all(_num(r.get(p.measures[0].field)) for r in p.rows),
               "범주 1개(3~12행) × 값 · options.bridge 의 start·end 가 행 이름에 있어야 함 · 결측 없음")


def _e_knowledge(p):
    nodes = {e["source"] for e in p.edges} | {e["target"] for e in p.edges}
    return _ok(bool(p.edges) and not p.is_tree and len(nodes) >= 4, "나무가 아닌 연결 · 항목 4개 이상(종류는 nodes[].class)")


@dataclass
class Chart:
    id: str
    name: str
    question: str
    eligible: object
    examples: str
    en: str = ""                                       # 데이터 시각화 일반 영문 이름


CATALOG: dict[str, Chart] = {c.id: c for c in [
    Chart("kpi", "KPI·점수 카드", "핵심 값·점수·등급은 얼마인가", _e_kpi, "진단 점수·등급 · 핵심 지표 요약", en="KPI card"),
    Chart("hbar", "순위 가로 막대", "어느 항목이 얼마나 큰가(순위)", _e_hbar, "상황별 검색량 · 카테고리 관심도 순위", en="Horizontal bar chart"),
    Chart("diverging_bar", "증감 막대", "무엇이 늘고 줄었나", _e_diverging, "카테고리별 전년 대비 증감", en="Diverging bar chart"),
    Chart("grouped_bar", "묶음 막대", "같은 항목을 몇 개 조건으로 나눠 비교하면", _e_grouped, "세그먼트 × 연도 검색량", en="Grouped bar chart"),
    Chart("stacked_100", "100% 구성 막대", "그룹마다 무엇으로 구성되나", _e_stacked, "상황별 성·연령 구성", en="100% stacked bar chart"),
    Chart("donut", "도넛", "전체가 몇 조각으로 나뉘나(5조각 이하)", _e_donut, "성별 구성 · 채널 비중", en="Donut chart"),
    Chart("line", "추이선", "언제 늘고 줄었나(계열 3개 이하)", _e_line, "월별 수요 추이 · 실측과 예측", en="Line chart"),
    Chart("spark_grid", "스파크라인 묶음", "여러 항목의 추이를 한눈에", _e_spark, "상황·키워드별 장기 추이", en="Sparklines (small multiples)"),
    Chart("season_heatmap", "성수기 달력", "어느 달에 수요가 몰리나", _e_season, "상황·카테고리별 성수기", en="Seasonality heatmap"),
    Chart("heatmap", "교차 히트맵", "두 기준이 만나는 칸 중 어디가 진한가", _e_heatmap, "상황 × 브랜드 점유 · 브랜드 × 세그먼트 지수 · 페이지 × 진단 분야 점수", en="Heatmap"),
    Chart("scatter_quadrant", "사분면 버블", "두 기준으로 나누면 어디에 있나(기회·경쟁)", _e_scatter, "성장 × 브랜드 연결 기회 지도 · 경쟁 집중도 × 규모", en="Bubble chart (quadrant)"),
    Chart("bump", "순위 변동", "순위가 시점·집단에 따라 어떻게 바뀌나", _e_bump, "세그먼트·시점별 브랜드 순위", en="Bump chart"),
    Chart("flow_tree", "흐름 나무", "검색이 어디서 어디로 갈라지나", _e_flow, "검색 여정 갈래", en="Tree diagram"),
    Chart("table", "표", "정확한 값이 필요하다 · 차트 조건을 못 채운다", _e_table, "근거 검색어 · 상세 값", en="Table"),
    Chart("table_graphic", "그래픽 표", "정확한 값과 크기·추이·구성을 행마다 함께", _e_table_graphic,
          "검색어 순위와 이유 · 키워드별 검색량·추이·연령 구성", en="Table with in-cell graphics"),
    Chart("heat_table", "히트 표", "글이 긴 두 기준의 교차 칸 중 어디가 진한가", _e_heat_table,
          "상황 × 브랜드 점유 표 · 페이지 × 진단 분야 점수 · 성수기 표", en="Heat table"),
    Chart("back_to_back", "맞댄 막대", "같은 항목의 반대 두 값(선호 대 회피 · 유입 대 이탈)", _e_back_to_back,
          "취향별 선호·회피 · 키워드별 유입·이탈 경로 수", en="Back-to-back bar chart (butterfly chart)"),
    Chart("pair_bars", "쌍 전이 막대", "어디서 어디로 한 단계 많이 이동하나", _e_pair_bars,
          "검색 목적 A → B 이동 · 키워드 다음 검색", en="Pair transition bar list"),
    Chart("bidirectional_tree", "양방향 나무", "기준 검색어 앞에서 무엇을 찾다 오고, 뒤에 어디로 가나", _e_bidir,
          "진입 상황의 직전·직후 검색 · 브랜드 검색 앞뒤", en="Bidirectional tree"),
    Chart("edge_table", "관계 표", "나무 모양이 아닌 그물형 연결은 무엇과 무엇이 이어지나", _e_edge_table, "키워드끼리의 연결 목록", en="Edge list (network as table)"),
    Chart("radar", "레이더", "몇 개 축의 점수를 한 모양으로 견주면(계열 3개 이하)", _e_radar, "쿠션 브랜드별 KBF(핵심 구매 요인) 점수 · 상황별 적합도 프로필", en="Radar chart"),
    Chart("funnel", "퍼널", "단계마다 얼마나 남고 얼마나 빠지나", _e_funnel, "연관 검색어를 의도 단계(인지·탐색·비교·구매)로 나눈 월 검색량 합", en="Funnel chart"),
    Chart("journey_map", "여정 지도", "검색이 단계를 거치며 어디서 어디로 흐르나", _e_journey, "검색 여정 흐름 · 경쟁 브랜드로 새는 지점", en="Sankey diagram (journey map)"),
    Chart("treemap", "수요 지도", "시장이 어떤 덩어리로 나뉘고 어느 덩어리가 큰가", _e_treemap, "카테고리 → 세그먼트 검색량 · 키워드 묶음별 크기", en="Treemap (demand map)"),
    Chart("knowledge_graph", "지식 그래프", "항목 종류가 다른 것들이 무엇과 무엇으로 이어지나", _e_knowledge, "브랜드·상황·성분·고민의 연결 · 키워드 연결 구조", en="Knowledge graph (network diagram)"),
    Chart("waterfall", "증감 다리", "시작에서 끝까지 무엇이 얼마나 보태고 깎았나", _e_waterfall, "작년 → 올해 검색량 변화의 세그먼트별 기여 · 점유 변화 분해", en="Waterfall chart (bridge)"),
]}


@dataclass
class Choice:
    chart: str
    reason: str
    eligible: list
    rejected: dict
    intent_note: str = ""
    profile: dict = field(default_factory=dict)
    ranked: list = field(default_factory=list)         # 상위 3 [{chart, name, en, score, reasons}] — 1위 = chart
    hints: list = field(default_factory=list)          # 프로파일 제안

    def as_dict(self):
        return {"chart": self.chart, "name": CATALOG[self.chart].name, "reason": self.reason, "intent_note": self.intent_note,
                "ranked": self.ranked, "hints": self.hints, "eligible": self.eligible, "rejected": self.rejected, "profile": self.profile}


def _bonus(p: Profile, cid: str) -> list:
    """차트별 적합 신호 — (점수, 이유). 점수는 순서를 정하는 데만 쓴다"""
    n = len(p.rows)
    long1 = bool(p.d1) and _avg_len(p, p.d1) > 14
    c1 = p.card.get(p.d1, 0) if p.d1 else 0
    c2 = p.card.get(p.d2, 0) if p.d2 else 0
    rules = {
        "hbar": (20, "순위와 크기 차이가 한눈에 보일 때") if 0 < c1 <= 12 else (5, "순위만 볼 때"),
        "table_graphic": (25, "이름·값·추이를 행마다 정확히 읽을 때") if (long1 or n > 30 or p.series_fields or p.mix_fields) else (5, "정확한 값까지 읽을 때"),
        "heat_table": (25, "행 이름이 길어도 교차 칸을 읽을 때") if (p.d1 and (_avg_len(p, p.d1) > 10 or c1 > 20)) else (5, "교차 칸을 표로 읽을 때"),
        "heatmap": (10, "두 기준이 만나는 칸 중 진한 곳을 찾을 때"),
        "donut": (15, "전체에서 몇 조각으로 나뉘는지만 볼 때"),
        "stacked_100": (15, "그룹마다 구성 비율을 견줄 때"),
        "grouped_bar": (10, "같은 항목을 조건별로 나란히 견줄 때") if 0 < c2 <= 3 else (3, "조건별로 견줄 때"),
        "line": (15, "언제 늘고 줄었는지 볼 때") if len(p.points) >= 12 else (5, "흐름을 볼 때"),
        "spark_grid": (15, "여러 항목의 흐름을 한눈에 훑을 때") if p.series_count >= 4 else (3, "여러 항목의 흐름을 볼 때"),
        "season_heatmap": (15, "어느 달에 몰리는지 볼 때") if len(p.points) >= 24 else (3, "달별 패턴을 볼 때"),
        "scatter_quadrant": (15, "두 기준에서의 자리를 함께 볼 때") if n >= 6 else (5, "두 값의 관계를 볼 때"),
        "bump": (20, "순위가 어떻게 바뀌는지 볼 때"), "flow_tree": (15, "어디서 어디로 갈라지는지 볼 때"), "bidirectional_tree": (20, "기준 검색어 앞뒤를 볼 때"),
        "pair_bars": (10, "어느 이동이 많은지 볼 때"), "back_to_back": (20, "반대 방향 두 값을 맞대어 볼 때") if p.opposite else (3, "두 값을 나란히 볼 때"),
        "kpi": (10, "숫자 하나가 곧 메시지일 때"), "diverging_bar": (15, "늘고 준 것을 가운데 선으로 가를 때"),
        "table": (2, "정확한 값이 필요할 때 — 언제나 가능"), "edge_table": (2, "연결을 목록으로 읽을 때"),
        "radar": (5, "몇 개 축의 점수를 한 모양으로 볼 때(값은 묶음 막대가 더 정확)"),
        "funnel": (20, "단계마다 얼마나 빠지는지 볼 때"), "journey_map": (15, "단계를 거치는 흐름을 한눈에 볼 때"),
        "treemap": (15, "덩어리의 크기를 한눈에 볼 때") if n >= 12 else (5, "크기를 면적으로 볼 때(길이가 더 정확)"),
        "knowledge_graph": (20, "종류가 다른 항목의 연결 구조를 볼 때") if p.nodes else (5, "연결 구조를 그림으로 볼 때"),
        "waterfall": (25, "시작과 끝 사이의 기여를 단계로 볼 때"),
    }
    return [rules[cid]] if cid in rules else []


def _rank(p: Profile, elig: list, default: str, intent) -> list:
    """쓸 수 있는 차트를 점수로 줄 세운 상위 3 — 1위는 언제나 select 의 결정과 같다(+100)"""
    out = []
    for cid in elig:
        score, why = 50, []
        if cid == default:
            score += 100; why.append("기본 선택")
        if intent and cid in INTENTS[intent]:
            k = INTENTS[intent].index(cid); score += (40, 30, 20)[min(k, 2)]; why.append(f"의도 '{intent}'에 맞음")
        for pts, text in _bonus(p, cid):
            score += pts; why.append(text)
        out.append((cid, score, why))
    out.sort(key=lambda x: (-x[1], list(CATALOG).index(x[0])))
    return [{"chart": c, "name": CATALOG[c].name, "en": CATALOG[c].en, "score": sc, "reasons": w} for c, sc, w in out[:3]]


def _default(p: Profile) -> tuple[str, str]:
    if not p.rows and not p.edges and not p.paths:
        raise VizError("rows·edges·paths가 모두 비었음 — 차트 대신 문장으로 쓴다")
    if p.completeness < 0.5:
        return ("table", f"완성도 {p.completeness:.2f} < 0.5 — 차트를 생략하고 표로") if p.rows else \
               ("edge_table", f"완성도 {p.completeness:.2f} < 0.5 — 표로")
    if p.paths:
        if _e_bidir(p)[0]:
            return "bidirectional_tree", f"경로 {len(p.paths)}개 · 기준 검색어 '{p.seed}' 앞뒤"
        if _e_journey(p)[0]:
            return "journey_map", f"경로 {len(p.paths)}개 — 기준 검색어가 없어 단계별 흐름으로"
        return "pair_bars", f"경로 {len(p.paths)}개 — 기준 검색어가 없고 경로가 적어 한 단계 이동 쌍으로"
    if p.edges:
        if p.is_tree:
            return "flow_tree", "연결이 뿌리 하나인 나무 모양"
        if p.nodes and _e_knowledge(p)[0]:
            return "knowledge_graph", "나무가 아닌 연결 · 항목 종류(nodes.class)가 선언됨"
        return ("pair_bars", "연결이 나무 모양이 아님 — 값 큰 쌍부터 막대로(그물형 그림은 탐색 화면)") if _e_pair_bars(p)[0] else \
               ("edge_table", "연결이 나무 모양이 아니고 값이 없음 — 표로(그물형 그림은 탐색 화면)")
    if (p.series_fields or p.mix_fields) and _e_table_graphic(p)[0]:
        return "table_graphic", "행마다 추이 목록·구성 칸이 있음"
    k = p.measures[0].kind if p.measures else None
    if not p.measures:
        return "table", "측정값이 없음"
    if k == "rank" and _e_bump(p)[0]:
        return "bump", "순위 값이 순서 있는 축을 따라 있음"
    if p.time:
        if len(p.dims) > 1:
            return "table", "시간 축 + 범주 2개 — 범주를 줄이거나 표로"
        if p.series_count <= 3:
            return "line", f"시점 {len(p.points)}개 · 계열 {p.series_count}개"
        return "spark_grid", f"시점 {len(p.points)}개 · 계열 {p.series_count}개(3개 초과)"
    if not p.dims or len(p.rows) <= 1:
        return ("kpi", "범주 없이 값만 있음") if _e_kpi(p)[0] else ("table", "값이 6개 초과")
    if len(p.dims) == 1:
        if p.bridge and _e_waterfall(p)[0]:
            return "waterfall", f"시작 '{p.bridge['start']}' → 끝 '{p.bridge['end']}' 사이의 기여(options.bridge)"
        if _e_back_to_back(p)[0] and p.opposite:
            return "back_to_back", "반대 방향 두 값이라고 선언됨 — 맞대어"
        if len(p.measures) >= 2:
            return ("scatter_quadrant", "항목마다 서로 다른 값 2개 이상") if _e_scatter(p)[0] else ("table_graphic", "값 2개 이상인데 항목 4개 미만 — 표에 막대로")
        if k == "change" or p.has_negative:
            return "diverging_bar", "증감 값(음수 포함)"
        if _e_donut(p)[0]:
            return "donut", f"구성비 {p.card[p.d1]}조각"
        if _e_funnel(p)[0]:
            return "funnel", f"순서 있는 단계 {len(p.rows)}개 · 단계마다 줄어드는 값"
        if _avg_len(p, p.d1) > 14:
            return "table_graphic", f"항목 이름이 길다(평균 {_avg_len(p, p.d1):.0f}자) — 표 속 막대로"
        return "hbar", f"범주 {p.card[p.d1]}개 × 값 1개"
    if len(p.dims) == 2 and len(p.measures) == 1:
        if _e_stacked(p)[0]:
            return "stacked_100", "그룹마다 합이 100%"
        cover = len(p.rows) / max(1, p.card[p.d1] * p.card[p.d2])
        if _e_treemap(p)[0] and len(p.rows) >= 12 and cover <= 0.5 and not _is_ordered(p, p.d2):
            return "treemap", f"그룹 → 항목 계층(교차 칸의 {cover * 100:.0f}%만 있음) · 항목 {len(p.rows)}개 — 면적으로"
        if _e_heatmap(p)[0] and (_avg_len(p, p.d1) > 10 or p.card[p.d1] > 20):
            return "heat_table", f"교차 {p.card[p.d1]} × {p.card[p.d2]} · 행 이름이 길거나(평균 {_avg_len(p, p.d1):.0f}자) 많음 — 표 형태"
        if _e_grouped(p)[0]:
            return "grouped_bar", f"두 번째 범주 {p.card[p.d2]}개(4개 이하)"
        if _e_heatmap(p)[0]:
            return "heatmap", f"교차 {p.card[p.d1]} × {p.card[p.d2]}"
    return "table", "카탈로그 차트 조건에 맞는 모양이 아님"


def select(spec: dict, intent: str | None = None) -> Choice:
    p = profile(spec)
    intent = intent or spec.get("intent")
    if intent and intent not in INTENTS:
        raise VizError(f"의도 '{intent}'는 없음 — {sorted(INTENTS)}")
    elig, rej = [], {}
    for cid, c in CATALOG.items():
        ok, why = c.eligible(p)
        if ok and p.completeness < 0.5 and cid not in ("table", "edge_table"):
            ok, why = False, f"완성도 {p.completeness:.2f} < 0.5 — 차트 생략"
        (elig.append(cid) if ok else rej.__setitem__(cid, why))
    chart, reason = _default(p)
    note = ""
    if intent:
        pick = next((c for c in INTENTS[intent] if c in elig), None)
        if pick and pick != chart:
            chart, reason = pick, f"의도 '{intent}' — 이 의도의 차트 중 데이터 조건을 채우는 첫 번째"
        elif not pick:
            note = (f"의도 '{intent}'의 차트가 데이터 조건을 못 채워 기본 선택을 씀 — "
                    + " · ".join(f"{c}: {rej.get(c, '')}" for c in INTENTS[intent]))
    return Choice(chart, reason, elig, rej, note, p.summary(), _rank(p, elig, chart, intent), p.hints)


# ── 값의 상태 ─────────────────────────────────────────────────────────────
STATE_LABEL = {"missing": "결측", "not_queried": "조회 안 함", "below_gate": "기저 미달", "not_returned": "미반환", "incomplete": "미완결"}


def _is_state(v) -> bool:
    return isinstance(v, dict) and v.get("state") in STATE_LABEL


def state_label(st: dict | None) -> str:
    """상태 dict → 화면 문구. None 이면 결측."""
    if not st:
        return STATE_LABEL["missing"]
    if st.get("state") == "below_gate" and _num(st.get("base")):
        return f"기저 {st['base']:,.0f}건 · 기준 미달"
    return STATE_LABEL.get(st.get("state"), STATE_LABEL["missing"])


def _st(p, r, field_) -> dict | None:
    return p.states.get((id(r), field_))


def _kind_of(p, r, field_) -> str | None:
    """값이 없을 때 그 칸의 상태 종류(missing·not_queried·below_gate·not_returned). 값이 있으면 None"""
    if r.get(field_) is not None:
        return None
    st = _st(p, r, field_)
    return st.get("state") if st else "missing"


def _lbl(p, r, field_, kind) -> str:
    v = r.get(field_)
    return fmt(v, kind) if v is not None else state_label(_st(p, r, field_))


HATCH = ('<defs><pattern id="viz-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
         f'<line x1="0" y1="0" x2="0" y2="6" stroke="{MUTED}" stroke-width="1.6"/></pattern></defs>')


def _state_cell(kind, x, y, w, h, show_text=True) -> str:
    """값이 없는 칸 — 상태마다 모양이 다르다(범례도 같은 함수로 그린다)"""
    cx, ty = x + w / 2, y + h / 2 + 4
    if kind == "not_queried":
        return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="url(#viz-hatch)" stroke="{MUTED}" stroke-width=".8"/>'
                + (f'<rect x="{cx - 17:.1f}" y="{ty - 11:.1f}" width="34" height="14" rx="3" fill="var(--panel,#fff)"/>' + _t(cx, ty, "안 함", 9.5, MUTED, "middle") if show_text else ""))
    if kind == "below_gate":
        return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{MUTED}" fill-opacity=".22"/>'
                + (_t(cx, ty, "미달", 9.5, MUTED, "middle") if show_text else ""))
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="none" stroke="{MUTED}" stroke-dasharray="3 2"/>'
            + (_t(cx, ty, "–", 10, MUTED, "middle") if show_text else ""))


def _state_legend(kinds, x, y) -> tuple[list, int]:
    """화면에 있는 상태만 범례로 — 칸과 같은 모양"""
    order = [k for k in ("missing", "not_queried", "below_gate", "not_returned") if k in kinds]
    parts, cx = [], x
    for k in order:
        parts.append(_state_cell(k, cx, y, 22, 14, show_text=False) + _t(cx + 28, y + 11, STATE_LABEL[k], 10.5, MUTED))
        cx += 40 + 12 * len(STATE_LABEL[k])
    return parts, (22 if order else 0)


# ── 숫자 형식 ─────────────────────────────────────────────────────────────
def fmt(v, kind="count") -> str:
    if _is_state(v):
        return state_label(v)
    if v is None:
        return "결측"
    if kind in ("share",):
        return f"{v * 100:.1f}%"
    if kind == "change":
        return f"{v * 100:+.1f}%"
    if kind == "index":
        return f"{v:.2f}"
    if kind == "rank":
        return f"{int(v)}위"
    if kind == "score":
        return f"{v:.0f}"
    if abs(v) >= 100 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def _short(s, n=14) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _t(x, y, s, size=11, fill=MUTED, anchor="start", weight=None, full=None):
    w = f' font-weight="{weight}"' if weight else ""
    tip = f"<title>{esc(full)}</title>" if full and full != s else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{w}>{tip}{esc(s)}</text>'


def _svg(w, h, label, body) -> str:
    inner = "".join(body)
    defs = HATCH if "url(#viz-hatch)" in inner else ""
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{esc(label)}" style="{FONT};max-width:{w}px">'
            f'{defs}{inner}</svg>')


def _label(spec, name) -> str:
    return (spec.get("labels") or {}).get(name, name)


def _bar_d(x, y, w, h, side=1, r=4.0) -> str:
    """막대 경로 d — 기준선(x)에서 side 방향으로 w 만큼. 데이터 끝만 r 둥글게, 기준선 쪽은 각지게(마크 규격)"""
    if w <= 0:
        return ""
    r = min(r, w / 2, h / 2)
    if side > 0:
        return (f"M{x:.1f},{y:.1f} h{w - r:.1f} a{r:.1f},{r:.1f} 0 0 1 {r:.1f},{r:.1f} v{h - 2 * r:.1f} "
                f"a{r:.1f},{r:.1f} 0 0 1 -{r:.1f},{r:.1f} h-{w - r:.1f} z")
    return (f"M{x:.1f},{y:.1f} h-{w - r:.1f} a{r:.1f},{r:.1f} 0 0 0 -{r:.1f},{r:.1f} v{h - 2 * r:.1f} "
            f"a{r:.1f},{r:.1f} 0 0 0 {r:.1f},{r:.1f} h{w - r:.1f} z")


def _bar(x, y, w, h, fill, side=1, r=4.0, title=None) -> str:
    d = _bar_d(x, y, w, h, side, r)
    if not d:
        return ""
    t = f"<title>{esc(title)}</title>" if title else ""
    return f'<path d="{d}" fill="{fill}">{t}</path>' if t else f'<path d="{d}" fill="{fill}"/>'


def _compact(v, kind="count") -> str:
    """눈금용 압축 표기 — 검색량(count)은 천·만·억으로 줄인다(1,000 미만은 그대로). 값 라벨은 fmt 를 쓴다"""
    if kind != "count" or v is None or _is_state(v) or abs(v) < 1000:
        return fmt(v, kind)
    for unit, word in ((1e8, "억"), (1e4, "만"), (1e3, "천")):
        if abs(v) >= unit:
            return f"{v / unit:g}{word}"
    return fmt(v, kind)


def _spread(ys, gap=12.0) -> list:
    """라벨 y 좌표가 gap 보다 가까우면 아래로 밀어 겹치지 않게"""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = list(ys)
    for a, b in zip(order, order[1:]):
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


def _pct(a, b) -> str:
    return f"{a / b * 100:.0f}%" if b else "–"


# ── 렌더러 ────────────────────────────────────────────────────────────────
def _top(items, n, additive, rest_label="기타"):
    """상위 n개 + (더할 수 있는 값이면) '기타' 롤업. 반환: (표시 항목, 전체 개수)"""
    k = len(items)
    if k <= n:
        return items, k
    head, tail = items[:n], items[n:]
    if additive:
        head = head + [(f"{rest_label} {len(tail)}개", sum(v for _, v in tail if v is not None), True)]
    return head, k


def r_kpi(spec, p, o):
    """지표 타일 — 라벨 → 값(32px · hero 48px) → ▲증감 + 비교 기준 → 추이. 증감은 바로 앞 값에 붙는 change 종류 값,
    추이는 options.spark {값 이름: [숫자…]}(스펙 데이터 — 밖에서 가져오지 않는다)"""
    r = p.rows[0] if p.rows else {}
    spark = o.get("spark") or {}
    hero = o.get("hero")
    tiles, notes = [], []
    for m in p.measures:
        if m.kind == "change" and tiles:
            v = r.get(m.field)
            lab = esc(_label(spec, m.field))
            if v is None:
                d = f'<span style="color:{MUTED}">{esc(_lbl(p, r, m.field, m.kind))}</span> <span style="color:{MUTED}">{lab}</span>'
            else:
                c = UP if v > 0 else DOWN if v < 0 else MUTED
                arrow = "▲" if v > 0 else "▼" if v < 0 else "±"
                d = f'<span style="color:{c};font-weight:650">{arrow} {esc(fmt(abs(v), "change").lstrip("+"))}</span> <span style="color:{MUTED}">{lab}</span>'
            tiles[-1]["delta"] = f'<div class="viz-kpi-delta" style="font-size:var(--viz-fs-body,12px);margin-top:2px">{d}</div>'
            continue
        big = 48 if (hero is True and not tiles) or hero == m.field else 32
        tiles.append({"m": m, "size": big, "delta": "",
                      "spark": _mini_spark(spark[m.field], end_dot=True) if isinstance(spark.get(m.field), list) else ""})
    if spark:
        used = [k for k in spark if any(t["m"].field == k for t in tiles)]
        notes.append(f"추이 = 스펙 options.spark({', '.join(f'{k} {len(spark[k])}개' for k in used)} · 0 기준)" if used else "options.spark 의 이름이 값과 맞지 않아 추이를 그리지 않음")
    cards = []
    for t in tiles:
        m = t["m"]
        cards.append(f'<div class="viz-kpi" style="border:1px solid {LINE};border-radius:12px;padding:14px 18px;min-width:200px">'
                     f'<div style="font-size:var(--viz-fs-body,12px);color:{MUTED}">{esc(_label(spec, m.field))}</div>'
                     f'<div style="font-size:{t["size"]}px;font-weight:650;letter-spacing:-.02em;line-height:1.15;color:{INK};margin:4px 0 2px">{esc(_lbl(p, r, m.field, m.kind) if p.rows else "결측")}</div>'
                     + t["delta"] + (f'<div style="margin-top:8px">{t["spark"]}</div>' if t["spark"] else "") + "</div>")
    return f'<div style="display:flex;flex-wrap:wrap;gap:10px">{"".join(cards)}</div>', len(tiles), len(tiles), " · ".join(notes)


def _bars(spec, p, o, signed=False):
    m = (_signed_measure(p) or p.measures[0]) if signed else p.measures[0]
    data = [(r.get(p.d1), r.get(m.field)) for r in p.rows]
    nolab = {r.get(p.d1): state_label(_st(p, r, m.field)) for r in p.rows if r.get(m.field) is None}
    data.sort(key=lambda x: (x[1] is None, -(x[1] or 0), str(x[0])))       # 큰 값부터 · 미측정은 끝 · 동률은 이름순
    shown, k = _top(data, o.get("top_n", 12), m.kind in ("count",) and not signed)
    vmax = max((abs(v) for _, v, *_ in shown if v is not None), default=0) or 1
    W, lw, rh, bh = 720, 170, 30, 18                                    # 행 30 · 막대 18(가는 막대)
    H = 14 + rh * len(shown) + (12 if not signed else 0)
    body = []
    if not signed:                                                       # 0 기준선을 그리고 '0'을 적는다 — 독자가 기준을 확인한다(컨설팅 차트 규칙)
        body.append(f'<line x1="{lw}" y1="6" x2="{lw}" y2="{H - 14}" stroke="{LINE}"/>')
        body.append(_t(lw, H - 3, "0", 9.5, MUTED, "middle"))
    if signed:
        x0, half = lw + (W - lw - 70) / 2, (W - lw - 70) / 2
        body.append(f'<line x1="{x0:.1f}" y1="6" x2="{x0:.1f}" y2="{H - 4}" stroke="{MUTED}"/>')
    emp, emp_note = _emphasis(o, {lab for lab, *_ in data})
    lead = None if (emp or signed) else next((lab for lab, v, *rest in shown if v is not None and not rest), None)   # 강조 지정이 없으면 1위만 색
    for i, (lab, v, *rest) in enumerate(shown):
        y = 10 + i * rh
        strong = lab in emp or lab == lead
        body.append(_t(lw - 8, y + 16, _short(lab, 16), 12, INK if not rest else MUTED, "end", weight=650 if strong else None, full=lab))
        if v is None:
            body.append(_t(lw + 4, y + 16, nolab.get(lab, "결측"), 11, MUTED))
            continue
        if signed:
            w = abs(v) / vmax * half
            body.append(_bar(x0, y + 6, w, bh, UP if v >= 0 else DOWN, 1 if v >= 0 else -1))
            tx = x0 + w + 6 if v >= 0 else x0 - w - 6
            body.append(_t(tx, y + 16, fmt(v, m.kind), 11, INK, "start" if v >= 0 else "end"))
        else:
            w = v / vmax * (W - lw - 80)
            fill = DIM if rest else (_series_color(lab, 0, emp) if emp else (PAL[0] if lab == lead else DIM))
            body.append(_bar(lw, y + 6, max(w, 0), bh, fill))
            body.append(_t(lw + w + 6, y + 16, fmt(v, m.kind), 11, INK, weight=650 if strong else None))
    note = ("막대 길이 = 값(0 기준)" + (" · 색 = 1위" if lead else "")) if not signed else "가운데 선 = 0 · 오른쪽 증가 · 왼쪽 감소"
    rest = [r for r in shown if len(r) > 2]
    n_ind = len(shown) - len(rest)
    cap = (f"상위 {n_ind}개 + 기타 {k - n_ind}개(전체 {k}개)" if rest else f"전체 {k}개 중 상위 {n_ind}개" if k > n_ind else "")
    if len(p.measures) > 1:
        cap = " · ".join(x for x in (cap, f"값 = {_label(spec, m.field)}") if x)
    cap = " · ".join(x for x in (cap, emp_note) if x)
    return _svg(W, H, f"{spec.get('title', '')} — {note}", body), n_ind, k, cap, _bars_finding(data, m, signed)


def _bars_finding(data, m, signed):
    """발견 한 줄 — 순위 막대: 1위 집중도(더할 수 있는 값) 또는 1·2위 값 · 증감 막대: 가장 늘고 준 항목과 개수. (문장, 근거)"""
    vals = [(lab, v) for lab, v in data if v is not None]
    if not vals:
        return None
    if signed:
        ups = [(l, v) for l, v in vals if v > 0]; downs = [(l, v) for l, v in vals if v < 0]
        parts = []
        if ups:
            l, v = max(ups, key=lambda x: x[1]); parts.append(f"가장 늘어난 '{l}' {fmt(v, m.kind)}")
        if downs:
            l, v = min(downs, key=lambda x: x[1]); parts.append(f"가장 줄어든 '{l}' {fmt(v, m.kind)}")
        text = " · ".join(parts) + f" · 늘어난 {len(ups)}개 / 줄어든 {len(downs)}개"
        basis = f"값 있는 {len(vals)}개 중 늘어난 {len(ups)}개 · 줄어든 {len(downs)}개 · 0 {len(vals) - len(ups) - len(downs)}개"
        return text, basis
    vals.sort(key=lambda x: (-x[1], str(x[0])))
    top, tv = vals[0]
    if m.kind in ("count", "share") and all(v >= 0 for _, v in vals):
        tot = sum(v for _, v in vals)
        if tot <= 0:
            return None
        text = f"'{top}' 하나가 전체의 {_pct(tv, tot)}"
        basis = f"{fmt(tv, m.kind)} / 전체 {fmt(tot, m.kind)} = {_pct(tv, tot)}"
        if len(vals) >= 4:
            s3 = sum(v for _, v in vals[:3])
            text += f" — 상위 3개가 {_pct(s3, tot)}"
            basis += f" · 상위 3개 ({'+'.join(fmt(v, m.kind) for _, v in vals[:3])}) = {fmt(s3, m.kind)} / {fmt(tot, m.kind)} = {_pct(s3, tot)}"
        return text, basis + f" · 값 있는 {len(vals)}개 기준"
    text = f"1위 '{top}' {fmt(tv, m.kind)}"
    if len(vals) > 1:
        text += f" · 2위 '{vals[1][0]}' {fmt(vals[1][1], m.kind)}"
    return text, f"값 큰 순 · 값 있는 {len(vals)}개 기준"


def r_hbar(spec, p, o):
    return _bars(spec, p, o)


def r_diverging_bar(spec, p, o):
    return _bars(spec, p, o, signed=True)


def _is_ordered(p, dim) -> bool:
    return dim is not None and (dim == p.ordered_dim or dim in p.ordered_guess)


def _cats(p, dim):
    vals = list(dict.fromkeys(r.get(dim) for r in p.rows))
    return sorted(vals, key=_nat_key) if _is_ordered(p, dim) and all(isinstance(v, str) for v in vals) else vals


def r_grouped_bar(spec, p, o):
    m = p.measures[0]
    g1, g2 = _cats(p, p.d1), _cats(p, p.d2)
    val = {(r.get(p.d1), r.get(p.d2)): r.get(m.field) for r in p.rows}
    nolab = {(r.get(p.d1), r.get(p.d2)): state_label(_st(p, r, m.field)) for r in p.rows if r.get(m.field) is None}
    tot = {a: sum(val.get((a, b)) or 0 for b in g2) for a in g1}
    if not _is_ordered(p, p.d1):
        g1.sort(key=lambda a: (-tot[a], str(a)))
    shown = g1[: o.get("top_n", 12)]
    vmax = max((v for v in val.values() if v is not None), default=0) or 1     # 전 계열 최대값 기준
    W, lw, bh = 720, 170, 12
    gh = bh * len(g2) + 12
    H = 30 + gh * len(shown)
    colors = PAL + [MUTED]
    body = [f'<rect x="{lw + i * 120}" y="4" width="10" height="10" fill="{colors[i]}"/>' + _t(lw + i * 120 + 14, 13, _short(b, 12), 11, INK, full=b)
            for i, b in enumerate(g2)]
    for i, a in enumerate(shown):
        y0 = 26 + i * gh
        body.append(_t(lw - 8, y0 + gh / 2, _short(a, 16), 12, INK, "end", full=a))
        for j, b in enumerate(g2):
            v = val.get((a, b)); y = y0 + j * bh
            if v is None:
                body.append(_t(lw + 4, y + 10, nolab.get((a, b), "결측"), 9.5, MUTED)); continue
            w = v / vmax * (W - lw - 80)
            body.append(_bar(lw, y, w, bh - 2, colors[j], r=3) + _t(lw + w + 4, y + 9.5, fmt(v, m.kind), 9.5, INK))
    return _svg(W, H, f"{spec.get('title', '')} — 막대 길이 = 값(0 기준 · 전체 최대값 기준)", body), len(shown), len(g1)


def r_stacked_100(spec, p, o):
    m = p.measures[0]
    g1, g2 = _cats(p, p.d1), _cats(p, p.d2)
    raw = {(r.get(p.d1), r.get(p.d2)): r for r in p.rows}
    val = {k: (r.get(m.field) or 0) for k, r in raw.items()}
    gap = {a: sorted({state_label(_st(p, raw[(a, b)], m.field)) if (a, b) in raw else "결측"
                      for b in g2 if (a, b) not in raw or raw[(a, b)].get(m.field) is None}) for a in g1}
    shown = g1[: o.get("top_n", 12)]
    g2, folded, rest_label = _fold_parts(g2, lambda b: sum(val.get((a, b), 0) for a in g1))
    if folded:
        for a in g1:
            val[(a, rest_label)] = sum(val.pop((a, b), 0) for b in folded)
    W, lw, rh = 720, 170, 28
    H = 34 + rh * len(shown)
    colors = [MUTED if _is_rest(b, rest_label) else MIXCOL[j % len(MIXCOL)] for j, b in enumerate(g2)]
    body = [f'<rect x="{lw + i * 78}" y="4" width="10" height="10" fill="{colors[i]}"/>' + _t(lw + i * 78 + 14, 13, _short(b, 8), 10.5, INK, full=b)
            for i, b in enumerate(g2)]
    span = W - lw - 20
    for i, a in enumerate(shown):
        y = 26 + i * rh; tot = sum(val.get((a, b), 0) for b in g2) or 1; x = lw
        body.append(_t(lw - 8, y + 14, _short(a, 16), 12, INK, "end", full=a))
        if gap[a]:
            body.append(_t(lw + 4, y + 14, f"값 없는 조각이 있어 막대를 그리지 않음({' · '.join(gap[a])})", 11, MUTED))
            continue
        for j, b in enumerate(g2):
            w = val.get((a, b), 0) / tot * span
            body.append(f'<rect x="{x + 1:.1f}" y="{y + 3}" width="{max(w - 2, 0):.1f}" height="{rh - 9}" fill="{colors[j]}"><title>{esc(b)} {val.get((a, b), 0) / tot * 100:.1f}%</title></rect>')   # 조각 사이 2px 바탕 틈
            if w > 34:
                body.append(_t(x + w / 2, y + 16, f"{val.get((a, b), 0) / tot * 100:.0f}%", 10, "#fff", "middle"))
            x += w
    note = f"조각 {len(folded)}개를 '{rest_label}'로 묶음(색 6개까지)" if folded else ""
    return _svg(W, H, f"{spec.get('title', '')} — 막대 하나 = 100%", body), len(shown), len(g1), note


def r_donut(spec, p, o):
    m = p.measures[0]
    gone = [f"{r.get(p.d1)}({state_label(_st(p, r, m.field))})" for r in p.rows if r.get(m.field) is None]
    data = sorted(((r.get(p.d1), r.get(m.field)) for r in p.rows if r.get(m.field) is not None), key=lambda x: (-x[1], str(x[0])))
    tot = sum(v for _, v in data) or 1
    colors = MIXCOL
    cx, cy, R, r0 = 110, 110, 90, 54
    body, a0 = [], -math.pi / 2
    for i, (lab, v) in enumerate(data):
        a1 = a0 + v / tot * 2 * math.pi
        large = 1 if a1 - a0 > math.pi else 0
        pts = [(cx + R * math.cos(a0), cy + R * math.sin(a0)), (cx + R * math.cos(a1), cy + R * math.sin(a1)),
               (cx + r0 * math.cos(a1), cy + r0 * math.sin(a1)), (cx + r0 * math.cos(a0), cy + r0 * math.sin(a0))]
        d = (f"M{pts[0][0]:.1f},{pts[0][1]:.1f} A{R},{R} 0 {large} 1 {pts[1][0]:.1f},{pts[1][1]:.1f} "
             f"L{pts[2][0]:.1f},{pts[2][1]:.1f} A{r0},{r0} 0 {large} 0 {pts[3][0]:.1f},{pts[3][1]:.1f}Z")
        body.append(f'<path d="{d}" fill="{colors[i]}" stroke="var(--panel,#fff)" stroke-width="2"><title>{esc(lab)} {v / tot * 100:.1f}%</title></path>')
        body.append(f'<rect x="240" y="{28 + i * 26}" width="11" height="11" fill="{colors[i]}"/>'
                    + _t(258, 38 + i * 26, f"{_short(lab, 18)} · {v / tot * 100:.1f}%", 12, INK, full=lab))
        a0 = a1
    note = f"값 없는 조각 {len(gone)}개 제외: {', '.join(gone)}" if gone else ""
    finding = None
    if data:
        lab, v = data[0]
        finding = (f"가장 큰 조각 '{lab}' {_pct(v, tot)}", f"{fmt(v, m.kind)} / 합 {fmt(tot, m.kind)} = {_pct(v, tot)}")   # 조사(이/가)를 붙이지 않는다 — 받침에 따라 틀린다
        if len(data) >= 3:
            s2 = data[0][1] + data[1][1]
            finding = (finding[0] + f" — 상위 2개가 {_pct(s2, tot)}", finding[1] + f" · 상위 2개 {fmt(s2, m.kind)} / {fmt(tot, m.kind)} = {_pct(s2, tot)}")
    return _svg(520, 220, f"{spec.get('title', '')} — 조각 각도 = 비중", body), len(data), len(data) + len(gone), note, finding


def _series(p):
    """시간 축 차트의 계열: {이름: {시점: 값}}"""
    out = {}
    if p.d1:
        m = p.measures[0].field
        for r in p.rows:
            out.setdefault(r.get(p.d1), {})[r[p.time]] = r.get(m)
    else:
        for mm in p.measures:
            out[mm.field] = {r[p.time]: r.get(mm.field) for r in p.rows}
    return out


def _yticks(vmax, n=4):
    if vmax <= 0:
        return [0, 1]
    raw = vmax / n; mag = 10 ** math.floor(math.log10(raw)); step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    return [step * i for i in range(n + 1) if step * i <= vmax + step * 0.999][: n + 2]


def _runs(pts, s, ff=None, inc=None):
    """시점 순으로 이어진 구간 — 결측(None)에서 끊고, 실측·미완결·예측 구간을 나눈다. 다음 구간은 앞 구간의 마지막 점에서 잇는다"""
    def mode(t):
        return "forecast" if ff and t >= ff else "incomplete" if inc and t >= inc else "actual"
    out, cur, cur_mode, prev = [], [], None, None
    for i, t in enumerate(pts):
        v = s.get(t)
        if v is None:
            if cur:
                out.append((cur, cur_mode))
            cur, cur_mode, prev = [], None, None
            continue
        md = mode(t)
        if cur and md != cur_mode:
            out.append((cur, cur_mode))
            cur = [prev]                                   # 경계는 이어서(점선·흐린 구간이 마지막 실측점에서 시작)
        cur.append((i, v)); cur_mode = md; prev = (i, v)
    if cur:
        out.append((cur, cur_mode))
    return out


def _draw_run(seg, mode, X, Y, c, sw):
    pts_ = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in seg)
    if mode == "forecast":
        return [f'<polyline points="{pts_}" fill="none" stroke="{c}" stroke-width="{sw}" stroke-dasharray="6 4"/>'] if len(seg) >= 2 else []
    if mode == "incomplete":
        out = [f'<polyline points="{pts_}" fill="none" stroke="{c}" stroke-width="{sw}" stroke-opacity=".35"/>'] if len(seg) >= 2 else []
        return out + [f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3" fill="var(--panel,#fff)" stroke="{c}"/>' for i, v in seg[1:] or seg]
    if len(seg) >= 2:
        return [f'<polyline points="{pts_}" fill="none" stroke="{c}" stroke-width="{sw}"/>']
    i, v = seg[0]                                          # 앞뒤가 결측인 외딴 점
    return [f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="2.4" fill="{c}"/>']


def r_line(spec, p, o):
    ser = _series(p)
    months = o.get("months", 24)
    pts = p.points[-months:] if months and len(p.points) > months else p.points
    cut = len(p.points) - len(pts)
    kind = p.measures[0].kind
    band = o.get("band")
    vals = [v for s in ser.values() for t, v in s.items() if t in pts and v is not None]
    if band:
        vals += [r.get(band[1]) for r in p.rows if r.get(band[1]) is not None and r[p.time] in pts]
    vmax = max(vals, default=0) or 1
    ticks = _yticks(vmax); top = ticks[-1] if ticks[-1] >= vmax else vmax
    ff = o.get("forecast_from")
    inc = p.incomplete_from
    series = list(ser.items())[:3]
    emp, emp_note = _emphasis(o, {name for name, _ in series})
    has_gap = any(s.get(t) is None for _, s in series for t in pts)
    has_inc = bool(inc) and any(t >= inc and s.get(t) is not None for _, s in series for t in pts)
    # 범례 — 계열·예측·예측 범위·미완결·결측을 앞 항목 너비만큼 이어 놓고, 넘치면 다음 줄(겹치지 않게)
    W, L, R_, B = 760, 60, 76, 40                                   # 오른쪽 여백 = 최신값 직접 라벨 자리
    items = [("series", j, _short(_label(spec, name), 18), name) for j, (name, _) in enumerate(series)]
    if ff:
        items.append(("forecast", 0, "예측", None))
        if band:
            items.append(("band", 0, "예측 범위", None))
    if has_inc:
        items.append(("incomplete", 0, "미완결", None))
    if has_gap:
        items.append(("gap", 0, "끊김 = 결측", None))
    legend, lx, ly = [], L, 12
    for kind_, j, text, full in items:
        w = 30 + 11.5 * len(text)
        if lx + w > W - R_ and lx > L:
            lx, ly = L, ly + 18
        c = _series_color(full, j, emp) if kind_ == "series" else PAL[j]
        sw = {"series": f'<line x1="{lx}" y1="{ly}" x2="{lx + 18}" y2="{ly}" stroke="{c}" stroke-width="2.4"/>',
              "forecast": f'<line x1="{lx}" y1="{ly}" x2="{lx + 18}" y2="{ly}" stroke="{PAL[0]}" stroke-width="2.2" stroke-dasharray="6 4"/>',
              "band": f'<rect x="{lx}" y="{ly - 6}" width="18" height="12" fill="{PAL[0]}" opacity=".12"/>',
              "incomplete": f'<line x1="{lx}" y1="{ly}" x2="{lx + 18}" y2="{ly}" stroke="{PAL[0]}" stroke-width="2.2" stroke-opacity=".35"/><circle cx="{lx + 9}" cy="{ly}" r="3" fill="var(--panel,#fff)" stroke="{PAL[0]}"/>',
              "gap": f'<line x1="{lx}" y1="{ly}" x2="{lx + 6}" y2="{ly}" stroke="{MUTED}" stroke-width="2"/><line x1="{lx + 12}" y1="{ly}" x2="{lx + 18}" y2="{ly}" stroke="{MUTED}" stroke-width="2"/>'}[kind_]
        legend.append(sw + _t(lx + 24, ly + 4, text, 11, INK, full=full))
        lx += w
    T = ly + 18
    H = T + 210 + B
    X = lambda i: L + i / max(1, len(pts) - 1) * (W - L - R_)
    Y = lambda v: T + (1 - v / top) * (H - T - B)                # 0 기준
    body = list(legend)
    for tv in ticks:
        body.append(f'<line x1="{L}" y1="{Y(tv):.1f}" x2="{W - R_}" y2="{Y(tv):.1f}" stroke="{LINE}"/>' + _t(L - 6, Y(tv) + 4, _compact(tv, kind if kind != "rank" else "count"), 10.5, MUTED, "end"))
    step = max(1, len(pts) // 8)
    for i, t in enumerate(pts):
        if i % step == 0 or i == len(pts) - 1:
            body.append(_t(X(i), H - B + 16, t, 10, MUTED, "middle"))
    if band:
        lo = {r[p.time]: r.get(band[0]) for r in p.rows}; hi = {r[p.time]: r.get(band[1]) for r in p.rows}
        idx = [i for i, t in enumerate(pts) if lo.get(t) is not None and hi.get(t) is not None]
        if idx:
            poly = [f"{X(i):.1f},{Y(hi[pts[i]]):.1f}" for i in idx] + [f"{X(i):.1f},{Y(lo[pts[i]]):.1f}" for i in reversed(idx)]
            body.append(f'<polygon points="{" ".join(poly)}" fill="{PAL[0]}" opacity=".12"/>')
    actual = lambda s: [(i, s[t]) for i, t in enumerate(pts) if s.get(t) is not None and not (ff and t >= ff) and not (inc and t >= inc)]
    if len(series) == 1:                                            # 면 워시 — 계열 하나일 때만(겹치면 못 읽는다)
        act = actual(series[0][1])
        if len(act) >= 2:
            poly = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in act)
            body.append(f'<polygon points="{X(act[0][0]):.1f},{Y(0):.1f} {poly} {X(act[-1][0]):.1f},{Y(0):.1f}" fill="{_series_color(series[0][0], 0, emp)}" opacity=".08"/>')
    for j, (name, s) in enumerate(series):
        for seg, mode in _runs(pts, s, ff, inc):
            body += _draw_run(seg, mode, X, Y, _series_color(name, j, emp), 2.2 if (not emp or name in emp) else 1.4)
    # 직접 라벨 — 계열마다 최신 실측값(오른쪽), 계열 하나면 최고점도. 모든 점에 숫자를 붙이지 않는다
    # (예외: options.label_points = "all" — 경영진 보고용 짧은 계열. 점이 12개를 넘으면 멈춘다)
    if o.get("label_points") == "all":
        total = sum(len(actual(s)) for _, s in series)
        if total > 12:
            raise VizError(f"모든 점에 숫자를 붙이려면 점이 12개 이하여야 함(지금 {total}개) — 끝점·극값 라벨로 둔다")
        for j, (name, s) in enumerate(series):
            for i, v in actual(s)[:-1]:
                body.append(_t(X(i), Y(v) - 8, fmt(v, kind), 10.5, INK, "middle", weight=600))
    ends = [(j, name, actual(s)[-1]) for j, (name, s) in enumerate(series) if actual(s)]
    ys = _spread([Y(v) for _, _, (_, v) in ends])
    for (j, name, (i, v)), yy in zip(ends, ys):
        c = _series_color(name, j, emp)
        body.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" fill="{c}" stroke="var(--panel,#fff)" stroke-width="2"/>')
        body.append(_t(X(i) + 9, yy + 4, fmt(v, kind), 12 if len(series) == 1 else 11, INK, weight=650 if (not emp or name in emp) else None, full=f"{name} · {pts[i]} {fmt(v, kind)}"))
    if len(series) == 1 and actual(series[0][1]):
        act = actual(series[0][1])
        i, v = max(act, key=lambda x: x[1])
        if i != act[-1][0]:
            c = _series_color(series[0][0], 0, emp)
            body.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" fill="{c}" stroke="var(--panel,#fff)" stroke-width="2"/>')
            above = Y(v) - 10 > T + 10
            body.append(_t(X(i), Y(v) - 10 if above else Y(v) + 18, f"최고 {fmt(v, kind)} · {pts[i]}", 11, INK, "middle", weight=600))
    sub = f"최근 {len(pts)}개 시점만 표시(전체 {p.points[0]}~{p.points[-1]} {len(p.points)}개 중)" if cut else ""
    if inc:
        sub = f"{sub} · {inc} 이후 미완결" if sub else f"{inc} 이후 미완결"
    sub = " · ".join(x for x in (sub, emp_note) if x)
    if ff and ff in p.points:
        i_ff = p.points.index(ff)
        span = f"실측 ~{p.points[i_ff - 1]} · 예측 {ff}~{p.points[-1]}" if i_ff > 0 else f"예측 {ff}~{p.points[-1]}"
        sub = f"{sub} · {span}" if sub else span
    return _svg(W, H, f"{spec.get('title', '')} — y축 0 기준 {sub}", body), len(ser), len(ser), sub, _line_finding(series, p, pts, ff, inc, kind, emp)


def _line_finding(series, p, pts, ff, inc, kind, emp):
    """발견 한 줄 — 계열 하나(또는 강조 계열 하나)의 실측 구간에서: 월 15개 이상이면 최근 3개월 대 전년 같은 3개월, 아니면 최고점과 최신값"""
    focus = [(n, s) for n, s in series if not emp or n in emp]
    if len(focus) != 1 or kind == "rank":
        return None
    name, s = focus[0]
    full = [t for t in p.points if s.get(t) is not None and not (ff and t >= ff) and not (inc and t >= inc)]   # 표시 구간이 아니라 전체 실측
    if len(full) < 2:
        return None
    monthly = all(_TIME_RE.match(str(t)) and len(str(t)) == 7 for t in full)
    if monthly and len(full) >= 15 and p.time_gaps == 0:
        cur, prev = full[-3:], full[-15:-12]
        y1, y0 = sum(s[t] for t in cur), sum(s[t] for t in prev)
        if y0 > 0:
            d = (y1 - y0) / y0 * 100
            return (f"최근 3개월은 전년 같은 기간보다 {d:+.0f}%",
                    f"최근 3개월 {cur[0]}~{cur[-1]} 합 {fmt(y1, kind)} / 전년 같은 3개월 {prev[0]}~{prev[-1]} 합 {fmt(y0, kind)} = {d:+.0f}% · 실측 구간만(예측·미완결 제외)")
    tmax = max(full, key=lambda t: s[t]); tl = full[-1]
    return (f"최고 {fmt(s[tmax], kind)}({tmax}) · 최신 {fmt(s[tl], kind)}({tl})",
            f"실측 {len(full)}개 시점 중 최대·마지막 값(예측·미완결 제외)")


def r_spark_grid(spec, p, o):
    ser = _series(p)
    order = sorted(ser, key=lambda n: (-sum(v or 0 for v in ser[n].values()), str(n)))
    shown = order[: o.get("top_n", 24)]
    cols, cw, ch = 3, 250, 74
    rows_n = math.ceil(len(shown) / cols)
    body = []
    for i, name in enumerate(shown):
        x0, y0 = (i % cols) * cw, (i // cols) * ch
        s = ser[name]; vs = [s.get(t) for t in p.points]
        vmax = max((v for v in vs if v is not None), default=0) or 1
        X = lambda k: x0 + 8 + k / max(1, len(vs) - 1) * (cw - 24)
        Y = lambda v: y0 + 64 - v / vmax * 36                         # 칸마다 0 기준 · 자기 최대값
        sd = {t: s.get(t) for t in p.points}
        body.append(_t(x0 + 8, y0 + 16, _short(name, 16), 11.5, INK, weight=650, full=name) + _t(x0 + cw - 16, y0 + 16, f"최대 {fmt(vmax, p.measures[0].kind)}", 10, MUTED, "end"))
        body.append(f'<line x1="{x0 + 8}" y1="{y0 + 64}" x2="{x0 + cw - 16}" y2="{y0 + 64}" stroke="{LINE}"/>')
        for seg, mode in _runs(p.points, sd, None, p.incomplete_from):
            body += _draw_run(seg, mode, X, Y, PAL[0], 1.6)
    H = rows_n * ch + 8
    note = f"끊긴 곳 = 결측{' · ' + p.incomplete_from + ' 이후 흐린 구간·빈 점 = 미완결' if p.incomplete_from else ''}"
    return _svg(cols * cw, H, f"{spec.get('title', '')} — 칸마다 0 기준·자기 최대값 기준({p.points[0]}~{p.points[-1]})", body), len(shown), len(order), note


def season_index(series: dict, exclude_from: str | None = None) -> list:
    """달력월 지수 = 달력월 중앙값 ÷ 12개월 중앙값의 평균 (1.0 = 평월). 값이 없는 달은 None · exclude_from 이후(미완결)는 계산에서 뺀다"""
    by_m = {m: [] for m in range(1, 13)}
    for t, v in series.items():
        if v is not None and not (exclude_from and t >= exclude_from):
            by_m[int(t[5:7])].append(v)
    med = {m: statistics.median(vs) if vs else None for m, vs in by_m.items()}
    known = [v for v in med.values() if v is not None]
    avg = sum(known) / len(known) if known else 0
    return [(med[m] / avg if avg and med[m] is not None else None) for m in range(1, 13)]


def _heat(fill_val, vmin, vmax):
    a = 0.06 + 0.84 * ((fill_val - vmin) / (vmax - vmin) if vmax > vmin else 0.5)
    return a, ("#fff" if a > 0.55 else INK)


def r_season_heatmap(spec, p, o):
    ser = _series(p)
    order = sorted(ser, key=lambda n: (-sum(v or 0 for v in ser[n].values()), str(n)))[: o.get("top_n", 20)]
    idx = {n: season_index(ser[n], p.incomplete_from) for n in order}
    allv = [v for vs in idx.values() for v in vs if v is not None]
    vmin, vmax = (min(allv), max(allv)) if allv else (0, 1)             # 전역 정규화
    lw, cw, rh = 170, 46, 24
    body = [_t(lw + (m - 0.5) * cw, 14, f"{m}월", 10.5, MUTED, "middle") for m in range(1, 13)]
    for i, n in enumerate(order):
        y = 22 + i * rh
        body.append(_t(lw - 8, y + 16, _short(n, 16), 11.5, INK, "end", full=n))
        for m, v in enumerate(idx[n], 1):
            x = lw + (m - 1) * cw
            if v is None:
                body.append(_state_cell("missing", x + 1, y + 1, cw - 2, rh - 2))
                continue
            a, tc = _heat(v, vmin, vmax)
            body.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{rh - 2}" fill="{PAL[0]}" opacity="{a:.2f}"/>' + _t(x + cw / 2, y + 16, f"{v:.2f}", 10, tc, "middle"))
    H = 30 + rh * len(order)
    leg, lh = _state_legend({"missing"} if any(x is None for vs in idx.values() for x in vs) else set(), lw + 1, H + 2)
    body += leg; H += lh
    note = f"{p.incomplete_from} 이후(미완결)는 지수 계산에서 뺌" if p.incomplete_from else ""
    return _svg(lw + 12 * cw + 10, H, f"{spec.get('title', '')} — 칸 = 달력월 지수(1.0 = 평월) · 색은 표 전체 기준" + (" · 점선 칸 = 결측" if lh else ""), body), len(order), len(ser), note


def r_heatmap(spec, p, o):
    m = p.measures[0]
    g1, g2 = _cats(p, p.d1), _cats(p, p.d2)
    val = {(r.get(p.d1), r.get(p.d2)): r.get(m.field) for r in p.rows}
    skind = {(r.get(p.d1), r.get(p.d2)): _kind_of(p, r, m.field) for r in p.rows if r.get(m.field) is None}
    if not _is_ordered(p, p.d1):
        g1.sort(key=lambda a: (-sum(val.get((a, b)) or 0 for b in g2), str(a)))
    shown1, shown2 = g1[: o.get("top_n", 20)], g2[: o.get("top_cols", 10)]
    allv = [v for v in val.values() if v is not None]
    dom = o.get("domain") or ([0, 100] if m.kind == "score" else [min(allv), max(allv)] if allv else [0, 1])   # 전역 정규화 · 점수는 고정 범위
    lw, cw, rh = 170, max(56, min(90, 560 // max(1, len(shown2)))), 26
    body = [_t(lw + (j + 0.5) * cw, 16, _short(b, 8), 10.5, MUTED, "middle", full=b) for j, b in enumerate(shown2)]
    for i, a in enumerate(shown1):
        y = 24 + i * rh
        body.append(_t(lw - 8, y + 17, _short(a, 16), 11.5, INK, "end", full=a))
        for j, b in enumerate(shown2):
            v = val.get((a, b)); x = lw + j * cw
            if v is None:
                body.append(_state_cell(skind.get((a, b), "missing"), x + 1, y + 1, cw - 2, rh - 2))
                continue
            a_, tc = _heat(v, dom[0], dom[1])
            body.append(f'<rect x="{x + 1}" y="{y + 1}" width="{cw - 2}" height="{rh - 2}" fill="{PAL[0]}" opacity="{a_:.2f}"/>' + _t(x + cw / 2, y + 17, fmt(v, m.kind), 10, tc, "middle"))
    H = 32 + rh * len(shown1)
    kinds = {skind.get((a, b), "missing") for a in shown1 for b in shown2 if val.get((a, b)) is None}
    leg, lh = _state_legend(kinds, lw + 1, H)
    body += leg; H += lh
    scale = "점수 0~100 고정" if m.kind == "score" else "표 전체 최소~최대 기준"
    return _svg(lw + cw * len(shown2) + 10, H, f"{spec.get('title', '')} — 색 진하기 = 값({scale}) · 값 없는 칸은 상태별 모양(범례)", body), len(shown1), len(g1)


def bubble_r(v, vmax, rmax=30.0):
    """면적 비례(r ∝ √값)"""
    return 0.0 if not vmax or not v or v <= 0 else rmax * (v / vmax) ** 0.5


def _log_wanted(p, m, o, key) -> bool:
    """로그 축: 옵션이 있으면 따르고, 없으면 검색량(count)이 1,000배 이상 퍼졌을 때 켠다"""
    if key in o:
        return bool(o[key])
    if m.kind != "count":
        return False
    pos = [r[m.field] for r in p.rows if _num(r.get(m.field)) and r[m.field] > 0]
    return len(pos) >= 2 and max(pos) / min(pos) >= 1000


QCOL = {"tl": PAL[2], "tr": PAL[0], "bl": MUTED, "br": PAL[1]}   # 사분면 분류 색 3 + 회색 — 모든 쌍 기준으로 검증(산점도는 색이 전부 맞닿는다)


def r_scatter_quadrant(spec, p, o):
    xm, ym = p.measures[0], p.measures[1]
    sm = p.measures[2] if len(p.measures) > 2 else None
    notes = []
    if sm and sm.field in (xm.field, ym.field):
        raise VizError("원 크기와 축이 같은 값 — 서로 다른 값을 나타내야 함")
    if sm and (sm.kind == "change" or (p.stats.get(sm.field, {}).get("min") or 0) < 0):
        notes.append(f"원 크기 없음 — '{_label(spec, sm.field)}'은(는) 부호 있는 값이라 면적으로 못 나타냄")
        sm = None
    lx, lyg = _log_wanted(p, xm, o, "log_x"), _log_wanted(p, ym, o, "log_y")
    ok = lambda r, m, lg: r.get(m.field) is not None and (not lg or r[m.field] > 0)
    pts = [r for r in p.rows if ok(r, xm, lx) and ok(r, ym, lyg)]
    outside = [r for r in p.rows if r not in pts]
    if len(pts) < 2:
        raise VizError("그릴 수 있는 점이 2개 미만 — 표로 쓴다")
    tx = (lambda v: math.log10(v)) if lx else (lambda v: v)
    ty = (lambda v: math.log10(v)) if lyg else (lambda v: v)
    xs, ys = [tx(r[xm.field]) for r in pts], [ty(r[ym.field]) for r in pts]
    xt_raw, yt_raw = o.get("x_threshold"), o.get("y_threshold")
    x_ok = xt_raw is not None and (not lx or xt_raw > 0)
    y_ok = yt_raw is not None and (not lyg or yt_raw > 0)
    xt = tx(xt_raw) if x_ok else statistics.median(xs)
    yt = ty(yt_raw) if y_ok else statistics.median(ys)
    if xt_raw is not None and not x_ok:
        notes.append(f"x 기준 {fmt(xt_raw, xm.kind)}은 로그 눈금에 놓을 수 없어 중앙값으로")
    if yt_raw is not None and not y_ok:
        notes.append(f"y 기준 {fmt(yt_raw, ym.kind)}은 로그 눈금에 놓을 수 없어 중앙값으로")
    xlab = (o.get("x_threshold_label") if x_ok else None) or ("중앙값" if not x_ok else fmt(xt_raw, xm.kind))
    ylab = (o.get("y_threshold_label") if y_ok else None) or ("중앙값" if not y_ok else fmt(yt_raw, ym.kind))
    pad = lambda a, b: (b - a) * 0.18 or 1                         # 가장 큰 원·이름이 틀 밖으로 나가지 않게
    xlo, xhi = min(xs + [xt]), max(xs + [xt]); xlo, xhi = xlo - pad(xlo, xhi), xhi + pad(xlo, xhi)
    ylo, yhi = min(ys + [yt]), max(ys + [yt]); ylo, yhi = ylo - pad(ylo, yhi), yhi + pad(ylo, yhi)
    if not lx and xm.kind == "share":                                 # 비율 축은 0~100% 밖으로 넓히지 않는다
        xlo, xhi = max(xlo, 0.0), min(xhi, 1.0)
    if not lyg and ym.kind == "share":
        ylo, yhi = max(ylo, 0.0), min(yhi, 1.0)
    if not lx and xm.kind in ("share", "change"):                     # 비율 축 끝은 10% 단위로
        xlo, xhi = math.floor(xlo * 10) / 10, math.ceil(xhi * 10) / 10
    if not lyg and ym.kind in ("share", "change"):
        ylo, yhi = math.floor(ylo * 10) / 10, math.ceil(yhi * 10) / 10
    ends = o.get("axis_ends") or {}
    ql = o.get("quadrant_labels") or {}
    class_color = bool(o.get("class_color")) and len(ql) == 4
    if o.get("class_color") and not class_color:
        notes.append("분류 색은 사분면 이름 4개가 있어야 켜진다 — 한 가지 색으로 그림")
    W, T, PW, PH = 760, 30, 0, 300
    L = 110 if ends.get("y") else 70
    PW = W - L - 30
    H = T + PH + 70 + (20 if class_color else 0)
    X = lambda v: L + (v - xlo) / (xhi - xlo) * PW
    Y = lambda v: T + (1 - (v - ylo) / (yhi - ylo)) * PH
    body = [f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T + PH}" stroke="{LINE}"/>',             # 틀 대신 축 두 선(데이터 잉크)
            f'<line x1="{L}" y1="{T + PH}" x2="{L + PW}" y2="{T + PH}" stroke="{LINE}"/>']
    shade = o.get("quadrant_shade") or []
    qrect = {"tl": (L, T, X(xt) - L, Y(yt) - T), "tr": (X(xt), T, L + PW - X(xt), Y(yt) - T),
             "bl": (L, Y(yt), X(xt) - L, T + PH - Y(yt)), "br": (X(xt), Y(yt), L + PW - X(xt), T + PH - Y(yt))}
    for q in shade:
        if q in qrect:
            x0, y0, w0, h0 = qrect[q]
            body.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w0:.1f}" height="{h0:.1f}" fill="{QCOL[q] if class_color else PAL[0]}" fill-opacity=".07"/>')
    body += [f'<line x1="{X(xt):.1f}" y1="{T}" x2="{X(xt):.1f}" y2="{T + PH}" stroke="{MUTED}" stroke-dasharray="4 4"/>',
             f'<line x1="{L}" y1="{Y(yt):.1f}" x2="{L + PW}" y2="{Y(yt):.1f}" stroke="{MUTED}" stroke-dasharray="4 4"/>']
    for key, (x, y, a) in {"tl": (L + 6, T + 14, "start"), "tr": (L + PW - 6, T + 14, "end"),
                           "bl": (L + 6, T + PH - 8, "start"), "br": (L + PW - 6, T + PH - 8, "end")}.items():
        if ql.get(key):
            body.append(_t(x, y, ql[key], 11, QCOL[key] if class_color else MUTED, a, weight=650 if class_color else None))
    # 눈금: 로그 축은 10의 거듭제곱, 아니면 양 끝 값
    if lx:
        dec = range(math.ceil(xlo), math.floor(xhi) + 1)
        for k_ in dec:
            body.append(f'<line x1="{X(k_):.1f}" y1="{T + PH}" x2="{X(k_):.1f}" y2="{T + PH + 4}" stroke="{MUTED}"/>' + _t(X(k_), T + PH + 16, fmt(10 ** k_, xm.kind), 10, MUTED, "middle"))
        if len(dec) < 2:                                              # 10배 안쪽이면 거듭제곱 눈금이 모자라 양 끝 값도
            body += [_t(L, T + PH + 16, fmt(10 ** xlo, xm.kind), 10, MUTED), _t(L + PW, T + PH + 16, fmt(10 ** xhi, xm.kind), 10, MUTED, "end")]
    else:
        body += [_t(L, T + PH + 16, fmt(xlo, xm.kind), 10, MUTED), _t(L + PW, T + PH + 16, fmt(xhi, xm.kind), 10, MUTED, "end")]
    if lyg:
        dec = range(math.ceil(ylo), math.floor(yhi) + 1)
        for k_ in dec:
            body.append(f'<line x1="{L - 4}" y1="{Y(k_):.1f}" x2="{L}" y2="{Y(k_):.1f}" stroke="{MUTED}"/>' + _t(L - 6, Y(k_) + 4, fmt(10 ** k_, ym.kind), 10, MUTED, "end"))
        if len(dec) < 2:
            body += [_t(L - 6, T + 10, fmt(10 ** yhi, ym.kind), 10, MUTED, "end"), _t(L - 6, T + PH, fmt(10 ** ylo, ym.kind), 10, MUTED, "end")]
    else:
        body += [_t(L - 6, T + 10, fmt(yhi, ym.kind), 10, MUTED, "end"), _t(L - 6, T + PH, fmt(ylo, ym.kind), 10, MUTED, "end")]
    if ends.get("x"):
        body += [_t(L, T + PH + 30, f"← {ends['x'][0]}", 10.5, INK), _t(L + PW, T + PH + 30, f"{ends['x'][1]} →", 10.5, INK, "end")]
    if ends.get("y"):
        body += [_t(L - 8, T + 26, f"↑ {ends['y'][1]}", 10.5, INK, "end"), _t(L - 8, T + PH - 12, f"↓ {ends['y'][0]}", 10.5, INK, "end")]
    smax = max((r.get(sm.field) or 0 for r in pts), default=0) if sm else 0
    quad = lambda xv, yv: ("t" if yv >= yt else "b") + ("r" if xv >= xt else "l")
    for r in sorted(pts, key=lambda r: -(r.get(sm.field) or 0) if sm else 0):
        xv, yv = tx(r[xm.field]), ty(r[ym.field])
        x, y = X(xv), Y(yv)
        rr = max(bubble_r(r.get(sm.field), smax), 4) if sm else 5
        c = QCOL[quad(xv, yv)] if class_color else PAL[0]            # 분류 색은 사분면을 다시 나타낼 때만(중복 인코딩)
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rr:.1f}" fill="{c}" fill-opacity=".2" stroke="{c}" stroke-width="1.6">'
                    f'<title>{esc(r.get(p.d1))} · {esc(_label(spec, xm.field))} {fmt(r[xm.field], xm.kind)} · {esc(_label(spec, ym.field))} {fmt(r[ym.field], ym.kind)}</title></circle>')
        lyy = y - rr - 4 if y - rr - 4 > T + 12 else y + rr + 13
        body.append(_t(x, lyy, _short(r.get(p.d1), 12), 10.5, INK, "middle", full=r.get(p.d1)))
    yb = T + PH + (46 if ends.get("x") else 34)
    body += [_t(L + PW / 2, yb, f"x = {_label(spec, xm.field)}{' (로그 눈금)' if lx else ''} · 세로 점선 = 기준 {xlab}", 11, MUTED, "middle"),
             _t(L, T - 8, f"↑ {_label(spec, ym.field)}{' (로그 눈금)' if lyg else ''}", 11, MUTED),
             _t(L + PW / 2, yb + 15, f"y = {_label(spec, ym.field)}{' (로그 눈금)' if lyg else ''} · 가로 점선 = 기준 {ylab}", 11, MUTED, "middle")]
    cy_ = yb + 15                                                     # 아래 줄들은 차례로 쌓는다(겹치지 않게)
    if class_color:
        cy_ += 20
        lx_ = L
        for q in ("tl", "tr", "bl", "br"):
            body.append(f'<circle cx="{lx_ + 5}" cy="{cy_ - 4}" r="5" fill="{QCOL[q]}" fill-opacity=".25" stroke="{QCOL[q]}"/>' + _t(lx_ + 14, cy_, ql[q], 10.5, INK))
            lx_ += 30 + 11 * len(ql[q])
        body.append(_t(L + PW, cy_, "색 = 사분면 구분", 10.5, MUTED, "end"))
    if sm:
        cy_ += 18
        body.append(_t(L, cy_, f"원 면적 = {_label(spec, sm.field)} (가장 큰 원 {fmt(smax, sm.kind)})", 10.5, MUTED))
    if outside:
        def why(r):
            for m_, lg in ((xm, lx), (ym, lyg)):
                if r.get(m_.field) is None:
                    return state_label(_st(p, r, m_.field))
                if lg and r[m_.field] <= 0:
                    return "로그 축에 0·음수"
            return "결측"
        cy_ += 18
        more = f" 외 {len(outside) - 4}개" if len(outside) > 4 else ""
        body.append(_t(L, cy_, f"그리지 않은 {len(outside)}개: {', '.join(f'{_short(r.get(p.d1), 8)}({why(r)})' for r in outside[:4])}{more}", 10.5, MUTED))
    H = cy_ + 10
    note = " · ".join([x for x in ("x 로그 눈금" if lx else "", "y 로그 눈금" if lyg else "") if x] + notes)
    qn = {q: 0 for q in ("tr", "tl", "br", "bl")}
    for r in pts:
        qn[quad(tx(r[xm.field]), ty(r[ym.field]))] += 1
    qname = {"tr": "오른쪽 위", "tl": "왼쪽 위", "br": "오른쪽 아래", "bl": "왼쪽 아래"}
    finding = (" · ".join(f"{ql.get(q) or qname[q]} {qn[q]}개" for q in ("tr", "tl", "br", "bl") if qn[q]),
               " · ".join(f"{qname[q]} {qn[q]}개" for q in ("tr", "tl", "br", "bl")) + f" = 그린 점 {len(pts)}개 · 기준 x {xlab} · y {ylab}(기준선 위·오른쪽은 포함)")
    return _svg(W, H + 6, f"{spec.get('title', '')} — 사분면(축 정의는 아래 설명)", body), len(pts), len(p.rows), note, finding


def r_bump(spec, p, o):
    m = p.measures[0]
    axis = p.ordered_dim or p.time
    steps = sorted({r.get(axis) for r in p.rows}, key=_nat_key) if axis == p.time or axis == p.ordered_dim else _cats(p, axis)
    if o.get("order"):
        steps = list(o["order"])
    ent = {}
    for r in p.rows:
        ent.setdefault(r.get(p.d1), {})[r.get(axis)] = r.get(m.field)
    last = steps[-1]
    order = sorted(ent, key=lambda e: (ent[e].get(last) or 1e9, min(v for v in ent[e].values() if v is not None) if any(v is not None for v in ent[e].values()) else 1e9, str(e)))
    shown = order[: o.get("top_n", 10)]
    rmax = int(max((v for e in shown for v in ent[e].values() if v is not None), default=1))
    W, L, R_, T = 760, 150, 150, 34
    H = T + rmax * 26 + 20
    X = lambda i: L + i / max(1, len(steps) - 1) * (W - L - R_)
    Y = lambda rk: T + (rk - 1) * 26 + 10
    body = [_t(X(i), 18, _short(s, 10), 11, MUTED, "middle", full=s) for i, s in enumerate(steps)]
    emp, emp_note = _emphasis(o, set(shown))
    for k, e in enumerate(shown):
        strong = (e in emp) if emp else (k < 3)
        c = (_series_color(e, 0, emp)) if emp else (PAL[k] if k < 3 else MUTED)
        seq = [(i, ent[e].get(s)) for i, s in enumerate(steps)]
        pts = [(i, v) for i, v in seq if v is not None]
        if len(pts) >= 2:
            body.append(f'<polyline points="{" ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in pts)}" fill="none" stroke="{c}" stroke-width="{2.4 if strong else 1.4}"/>')
        body += [f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4" fill="{c}"/>' for i, v in pts]
        if seq[0][1] is not None:
            body.append(_t(X(0) - 10, Y(seq[0][1]) + 4, f"{_short(e, 10)} {int(seq[0][1])}", 11, INK, "end", full=e))
        if seq[-1][1] is not None:
            body.append(_t(X(len(steps) - 1) + 10, Y(seq[-1][1]) + 4, f"{int(seq[-1][1])} {_short(e, 10)}", 11, INK, full=e))
    return _svg(W, H, f"{spec.get('title', '')} — 위가 1위 · 빈 칸 = 그 단계 순위 밖", body), len(shown), len(ent), emp_note


def r_flow_tree(spec, p, o):
    kids, val = {}, {}
    for e in p.edges:
        kids.setdefault(e["source"], []).append(e["target"]); val[e["target"]] = e.get("value")
    targets = {e["target"] for e in p.edges}
    root = next(e["source"] for e in p.edges if e["source"] not in targets)
    topc, maxd = o.get("top_children", 5), o.get("max_depth", 4)
    nodes, leaves = [], [0]

    def walk(n, d):
        ch = sorted(kids.get(n, []), key=lambda c: (-(val.get(c) or 0), str(c))) if d < maxd else []
        rest = ch[topc:]
        ch = ch[:topc]
        me = {"id": n, "d": d, "v": val.get(n, o.get("root_value")), "kids": []}
        for c in ch:
            me["kids"].append(walk(c, d + 1))
        if rest:
            me["kids"].append({"id": f"기타 {len(rest)}개", "d": d + 1, "v": sum(val.get(c) or 0 for c in rest), "kids": [], "rest": True})
            me["kids"][-1]["y"] = leaves[0]; leaves[0] += 1
        if not me["kids"]:
            me["y"] = leaves[0]; leaves[0] += 1
        else:
            for k in me["kids"]:
                if "y" not in k:
                    k["y"] = leaves[0]; leaves[0] += 1
            me["y"] = sum(k["y"] for k in me["kids"]) / len(me["kids"])
        nodes.append(me)
        return me

    tree = walk(root, 0)
    depth = max(n["d"] for n in nodes)
    vmax = max((n["v"] or 0 for n in nodes if n["d"] > 0), default=0) or 1
    colw, rh = 190, 30
    W, H = 30 + (depth + 1) * colw, 20 + leaves[0] * rh
    X = lambda d: 14 + d * colw
    Y = lambda y: 18 + y * rh
    body = []

    def draw(n):
        for k in n["kids"]:
            sw = max(1.0, 12 * (k["v"] or 0) / vmax)                 # 이동량에 비례 · 최소 굵기 1
            x1, y1, x2, y2 = X(n["d"]) + 150, Y(n["y"]), X(k["d"]), Y(k["y"])
            body.append(f'<path d="M{x1:.1f},{y1:.1f} C{(x1 + x2) / 2:.1f},{y1:.1f} {(x1 + x2) / 2:.1f},{y2:.1f} {x2:.1f},{y2:.1f}" fill="none" stroke="{MUTED if k.get("rest") else PAL[0]}" stroke-opacity=".45" stroke-width="{sw:.1f}"/>')
            draw(k)
        lab = f"{_short(n['id'], 13)}" + (f" {fmt(n['v'])}" if n.get("v") is not None else "")
        body.append(f'<rect x="{X(n["d"]):.1f}" y="{Y(n["y"]) - 11:.1f}" width="150" height="22" rx="5" fill="var(--panel,#fff)" stroke="{LINE}"/>'
                    + _t(X(n["d"]) + 6, Y(n["y"]) + 4, lab, 11, MUTED if n.get("rest") else INK, full=n["id"]))

    draw(tree)
    total = len({e['target'] for e in p.edges}) + 1
    ind = sum(1 for nd in nodes if not nd.get("rest"))
    cap = f"검색어 {ind}개 + 기타로 묶은 {total - ind}개(전체 {total}개)" if total > ind else ""
    return _svg(W, H, f"{spec.get('title', '')} — 선 굵기 = 값(경로 데이터면 경로 수) · 갈래마다 상위 {topc}개 + 기타", body), ind, total, cap


def _table_html(headers, rows):
    th = "".join(f'<th style="text-align:left;padding:4px 8px;border-bottom:1px solid {LINE};color:{MUTED};font-weight:600">{esc(h)}</th>' for h in headers)
    trs = "".join("<tr>" + "".join(f'<td style="padding:4px 8px;border-bottom:1px solid {LINE}">{esc(c)}</td>' for c in r) + "</tr>" for r in rows)
    return f'<table class="viz-table" style="border-collapse:collapse;font-size:12.5px;width:100%"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'


def r_table(spec, p, o):
    cols = p.dims + ([p.time] if p.time else []) + [m.field for m in p.measures]
    kinds = {m.field: m.kind for m in p.measures}
    n = o.get("top_n", 50)
    rows = [[_lbl(p, r, c, kinds[c]) if c in kinds else r.get(c, "") for c in cols] for r in p.rows[:n]]
    return _table_html([_label(spec, c) for c in cols], rows), len(rows), len(p.rows)


def r_edge_table(spec, p, o):
    es = sorted(p.edges, key=lambda e: (-(e.get("value") or 0), str(e["source"]), str(e["target"])))[: o.get("top_n", 50)]
    rows = [[e["source"], e["target"], fmt(e.get("value")) if e.get("value") is not None else ""] for e in es]
    return _table_html(["출발", "도착", (spec.get("labels") or {}).get("value", "값")], rows), len(rows), len(p.edges)



# ── 표 속 그래픽 · 히트 표 · 맞댄 막대 · 쌍 전이 막대 · 양방향 나무 ──
_TD_CSS = f"padding:5px 8px;border-bottom:1px solid {LINE};vertical-align:middle"
_TH_CSS = f"padding:5px 8px;border-bottom:1px solid {LINE};color:{MUTED};font-weight:600;text-align:left;white-space:nowrap"


def _td(extra: str = "") -> str:
    """칸 style 속성은 하나로 — 두 번 쓰면 브라우저가 뒤의 것을 버린다"""
    return f'style="{_TD_CSS};{extra}"' if extra else f'style="{_TD_CSS}"'


def _th(extra: str = "") -> str:
    return f'style="{_TH_CSS};{extra}"' if extra else f'style="{_TH_CSS}"'


def _mini_spark(vals, inc_idx=None, end_dot=False) -> str:
    """칸 속 추이선. end_dot 이면 타일용 — 선은 회색, 마지막 값에 표식"""
    vs = [v if _num(v) else None for v in vals]
    known = [v for v in vs if v is not None]
    if len(known) < 2:
        return f'<span style="color:{MUTED}" title="값이 2개 미만 — 추이를 그리지 않음">–</span>'
    vmin = min(0, min(known))                                     # 음수가 있으면 최솟값부터
    vmax = max(known)
    span_ = (vmax - vmin) or 1
    W_, H_ = (160, 36) if end_dot else (96, 24)
    X = lambda k: 3 + k / max(1, len(vs) - 1) * (W_ - 6)
    Y = lambda v: H_ - 3 - (v - vmin) / span_ * (H_ - 8)           # 칸마다 0(또는 최솟값) 기준·자기 최대값
    sd = {i: v for i, v in enumerate(vs)}
    body = []
    for seg, mode in _runs(list(range(len(vs))), sd, None, inc_idx):
        body += _draw_run(seg, mode, X, Y, DIM if end_dot else PAL[0], 2 if end_dot else 1.4)
    if end_dot:
        last = max(i for i, v in enumerate(vs) if v is not None)
        body.append(f'<circle cx="{X(last):.1f}" cy="{Y(vs[last]):.1f}" r="4" fill="{PAL[0]}" stroke="var(--panel,#fff)" stroke-width="2"/>')
    return (f'<svg viewBox="0 0 {W_} {H_}" width="{W_}" height="{H_}" role="img" aria-label="추이(칸마다 0 기준) · 최대 {fmt(vmax)}" style="vertical-align:middle">'
            + "".join(body) + "</svg>")


def _mini_mix(d: dict, parts: list, rest_label=None) -> str:
    tot = sum(v for v in d.values() if _num(v)) or 1
    x, out = 0.0, []
    for j, part in enumerate(parts):
        v = d.get(part) or 0
        w = v / tot * 120
        out.append(f'<rect x="{x + 1:.1f}" y="0" width="{max(w - 2, 0):.1f}" height="12" fill="{MUTED if _is_rest(part, rest_label) else MIXCOL[j % len(MIXCOL)]}"><title>{esc(part)} {v / tot * 100:.0f}%</title></rect>')
        x += w
    return f'<svg viewBox="0 0 120 12" width="120" height="12" role="img" aria-label="구성(막대 하나 = 100%)" style="vertical-align:middle">{"".join(out)}</svg>'


def r_table_graphic(spec, p, o):
    m0 = p.measures[0] if p.measures else None
    rows = list(p.rows)
    if m0:
        rows.sort(key=lambda r: (r.get(m0.field) is None, -(r.get(m0.field) or 0), str(r.get(p.d1))))
    shown = rows[: o.get("top_n", 30)]
    bars = o.get("bars") or ([m0.field] if m0 else [])
    vmax = {f_: max((abs(r[f_]) for r in p.rows if _num(r.get(f_))), default=0) or 1 for f_ in bars}
    badge = o.get("badge")
    parts, folded_parts, rest_labels = {}, {}, {}
    for f_ in p.mix_fields:
        all_parts = list(dict.fromkeys(k for r in p.rows for k in (r.get(f_) or {})))
        parts[f_], folded_parts[f_], rest_labels[f_] = _fold_parts(all_parts, lambda b, f_=f_: sum((r.get(f_) or {}).get(b) or 0 for r in p.rows))
    head = [f"<th {_th()}>{esc(_label(spec, p.d1))}</th>"]
    head += [f"<th {_th()}>{esc(_label(spec, m.field))}</th>" for m in p.measures]
    head += [f"<th {_th()}>{esc(_label(spec, f_))}</th>" for f_ in p.series_fields]
    for f_ in p.mix_fields:
        leg = " ".join(f'<span style="white-space:nowrap"><i style="display:inline-block;width:8px;height:8px;background:{MUTED if _is_rest(pt, rest_labels[f_]) else MIXCOL[j % len(MIXCOL)]};margin-right:3px"></i>{esc(pt)}</span>' for j, pt in enumerate(parts[f_]))
        head.append(f'<th {_th()}>{esc(_label(spec, f_))}<div style="font-weight:400;font-size:11px">{leg}</div></th>')
    trs = []
    for r in shown:
        lab = esc(r.get(p.d1))
        if badge and r.get(badge):
            lab += f' <span style="font-size:11px;padding:1px 6px;border-radius:999px;border:1px solid {LINE};color:{MUTED};white-space:nowrap">{esc(r.get(badge))}</span>'
        tds = [f"<td {_td('min-width:9em')}>{lab}</td>"]
        for m in p.measures:
            v = r.get(m.field)
            txt = esc(_lbl(p, r, m.field, m.kind))
            if m.field in bars and v is not None:
                w = abs(v) / vmax[m.field] * 90
                tds.append(f'<td {_td("white-space:nowrap")}><span style="display:inline-block;height:10px;width:{w:.0f}px;background:{DOWN if v < 0 else PAL[0]};border-radius:2px;vertical-align:middle;margin-right:6px"></span>{txt}</td>')
            else:
                tds.append(f'<td {_td(f"color:{INK if v is not None else MUTED}")}>{txt}</td>')
        for f_ in p.series_fields:
            vals = r.get(f_) or []
            inc = o.get("incomplete_last") and len(vals) - 1
            tds.append(f"<td {_td()}>{_mini_spark(vals, inc if inc else None)}</td>")
        for f_ in p.mix_fields:
            d = r.get(f_)
            if d and folded_parts[f_]:
                d = {**{k: v for k, v in d.items() if k not in folded_parts[f_]}, rest_labels[f_]: sum(d.get(b) or 0 for b in folded_parts[f_])}
            tds.append(f"<td {_td()}>{_mini_mix(d, parts[f_], rest_labels[f_]) if d else esc('결측')}</td>")
        trs.append("<tr>" + "".join(tds) + "</tr>")
    html_ = (f'<table class="viz-table" style="border-collapse:collapse;font-size:12.5px;width:100%"><thead><tr>{"".join(head)}</tr></thead>'
             f'<tbody>{"".join(trs)}</tbody></table>')
    notes = []
    if bars:
        notes.append("막대 길이 = 값(열마다 최대값 기준)")
    if p.series_fields:
        notes.append("추이 = 칸마다 0 기준·자기 최대값" + (" · 마지막 점 미완결" if o.get("incomplete_last") else ""))
    if p.mix_fields:
        notes.append("구성 막대 하나 = 100%")
    k = len(rows)
    if k > len(shown):
        notes.insert(0, f"전체 {k}개 중 상위 {len(shown)}개")
    return html_, len(shown), k, " · ".join(notes)


def _hatch_css():
    return f"repeating-linear-gradient(45deg,{MUTED} 0 1px,transparent 1px 5px)"


def r_heat_table(spec, p, o):
    m = p.measures[0]
    g1, g2 = _cats(p, p.d1), _cats(p, p.d2)
    val = {(r.get(p.d1), r.get(p.d2)): r.get(m.field) for r in p.rows}
    skind = {(r.get(p.d1), r.get(p.d2)): _kind_of(p, r, m.field) for r in p.rows if r.get(m.field) is None}
    if not _is_ordered(p, p.d1):
        g1.sort(key=lambda a: (-sum(val.get((a, b)) or 0 for b in g2), str(a)))
    shown1, shown2 = g1[: o.get("top_n", 30)], g2[: o.get("top_cols", 12)]
    allv = [v for v in val.values() if v is not None]
    steps = o.get("scale") == "steps"
    base = o.get("baseline", 1.0)
    band = o.get("band") or [base * 0.8, base * 1.2]
    dom = o.get("domain") or ([0, 100] if m.kind == "score" else [min(allv), max(allv)] if allv else [0, 1])
    hl = o.get("highlight") or {}
    def hit(v):
        return v is not None and (("below" in hl and v < hl["below"]) or ("above" in hl and v > hl["above"]))
    head = f"<th {_th()}></th>" + "".join(f'<th {_th("text-align:center")}>{esc(b)}</th>' for b in shown2)
    trs, kinds, any_hl = [], set(), False
    for a in shown1:
        tds = [f"<td {_td('min-width:11em')}>{esc(a)}</td>"]
        for b in shown2:
            v = val.get((a, b))
            if v is None:
                kd = skind.get((a, b), "missing"); kinds.add(kd)
                if kd == "not_queried":
                    st = f"background:{_hatch_css()};color:{MUTED}"; txt = "안 함"
                elif kd == "below_gate":
                    st = f"background:color-mix(in srgb,{MUTED} 22%,transparent);color:{MUTED}"; txt = "미달"
                else:
                    st = f"outline:1px dashed {MUTED};outline-offset:-3px;color:{MUTED}"; txt = "–"
                tds.append(f'<td {_td(f"text-align:center;{st}")}>{txt}</td>')
                continue
            if steps:
                lvl = "hi" if v >= band[1] else "lo" if v <= band[0] else "mid"
                bg = {"hi": f"color-mix(in srgb,{PAL[0]} 30%,transparent)", "lo": f"color-mix(in srgb,{MUTED} 18%,transparent)", "mid": "transparent"}[lvl]
                tc = INK
            else:
                a_, tc = _heat(v, dom[0], dom[1])
                bg = f"color-mix(in srgb,{PAL[0]} {a_ * 100:.0f}%,transparent)"
            extra = ""
            if hit(v):
                any_hl = True
                extra = f";outline:2px solid {INK};outline-offset:-2px;font-weight:700"
            tds.append(f'<td {_td(f"text-align:center;background:{bg};color:{tc}{extra}")}>{esc(fmt(v, m.kind))}</td>')
        trs.append("<tr>" + "".join(tds) + "</tr>")
    legend = []
    if steps:
        legend.append(f'칸 색 = 기준 {fmt(base, m.kind)} 대비 3단계: <span style="background:color-mix(in srgb,{PAL[0]} 30%,transparent);padding:0 6px">높음 ≥ {fmt(band[1], m.kind)}</span> · 보통 · '
                      f'<span style="background:color-mix(in srgb,{MUTED} 18%,transparent);padding:0 6px">낮음 ≤ {fmt(band[0], m.kind)}</span>')
    else:
        legend.append("칸 색 진하기 = 값(" + ("점수 0~100 고정" if m.kind == "score" else "표 전체 최소~최대 기준") + ")")
    if any_hl:
        cond = " · ".join(f"{'<' if k_ == 'below' else '>'} {fmt(v_, m.kind)}" for k_, v_ in hl.items() if k_ in ("below", "above"))
        legend.append(f'<span style="outline:2px solid {INK};outline-offset:-2px;padding:0 6px;font-weight:700">강조</span> = {esc(hl.get("label") or cond)}')
    for kd in ("missing", "not_returned", "not_queried", "below_gate"):
        if kd in kinds:
            sample = {"missing": f"outline:1px dashed {MUTED};outline-offset:-2px", "not_returned": f"outline:1px dashed {MUTED};outline-offset:-2px",
                      "not_queried": f"background:{_hatch_css()}", "below_gate": f"background:color-mix(in srgb,{MUTED} 22%,transparent)"}[kd]
            legend.append(f'<span style="{sample};padding:0 10px;margin-right:3px"></span>{STATE_LABEL[kd]}')
    html_ = (f'<table class="viz-table" style="border-collapse:collapse;font-size:12.5px;width:100%"><thead><tr>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'
             f'<div style="font-size:11.5px;color:{MUTED};margin-top:6px">{" · ".join(legend)}</div>')
    note = f"열 전체 {len(g2)}개 중 {len(shown2)}개" if len(g2) > len(shown2) else ""
    return html_, len(shown1), len(g1), note


def r_back_to_back(spec, p, o):
    lm, rm = p.measures[0], p.measures[1]
    rows = list(p.rows)
    key = {"left": lambda r: -(r.get(lm.field) or 0), "sum": lambda r: -((r.get(lm.field) or 0) + (r.get(rm.field) or 0))}.get(o.get("sort"), lambda r: -(r.get(rm.field) or 0))
    rows.sort(key=lambda r: (key(r), str(r.get(p.d1))))
    shown = rows[: o.get("top_n", 15)]
    vmax = max((r.get(f_) or 0 for r in p.rows for f_ in (lm.field, rm.field)), default=0) or 1   # 양쪽 같은 눈금
    W, rh, cw = 720, 26, 170
    cx = W / 2
    half = cx - cw / 2 - 56
    H = 34 + rh * len(shown)
    cl, cr = PAL[2], PAL[0]
    body = [f'<rect x="{cx - cw / 2 - 18}" y="6" width="10" height="10" fill="{cl}"/>' + _t(cx - cw / 2 - 22, 15, _label(spec, lm.field), 11.5, INK, "end"),
            f'<rect x="{cx + cw / 2 + 8}" y="6" width="10" height="10" fill="{cr}"/>' + _t(cx + cw / 2 + 22, 15, _label(spec, rm.field), 11.5, INK)]
    for i, r in enumerate(shown):
        y = 26 + i * rh
        body.append(_t(cx, y + 14, _short(r.get(p.d1), 14), 12, INK, "middle", full=r.get(p.d1)))
        for m_, side in ((lm, -1), (rm, 1)):
            v = r.get(m_.field)
            x0 = cx - cw / 2 if side < 0 else cx + cw / 2
            if v is None:
                body.append(_t(x0 + side * 6, y + 14, state_label(_st(p, r, m_.field)), 10.5, MUTED, "end" if side < 0 else "start"))
                continue
            w = v / vmax * half
            body.append(_bar(x0, y + 4, w, rh - 10, cl if side < 0 else cr, side))
            body.append(_t(x0 + side * (w + 5), y + 14, fmt(v, m_.kind), 10.5, INK, "end" if side < 0 else "start"))
    k = len(rows)
    note = " · ".join(x for x in (f"전체 {k}개 중 {len(shown)}개" if k > len(shown) else "", "막대 길이 = 값(양쪽 같은 눈금)") if x)
    return _svg(W, H, f"{spec.get('title', '')} — 왼쪽 {_label(spec, lm.field)} · 오른쪽 {_label(spec, rm.field)} · 막대 길이 = 값(양쪽 같은 눈금)", body), len(shown), k, note


def _pairs(p) -> tuple[list, str]:
    if p.paths:
        cnt = {}
        for path in p.paths:
            for a, b in dict.fromkeys(zip(path, path[1:])):           # 한 경로 안 같은 쌍은 1번
                if a != b:
                    cnt[(a, b)] = cnt.get((a, b), 0) + 1
        return [(a, b, v) for (a, b), v in cnt.items()], "값 = 그 이동이 나온 경로 수(한 경로 안 같은 쌍은 1번 · 검색 건수 아님)"
    return [(e["source"], e["target"], e.get("value")) for e in p.edges if _num(e.get("value"))], ""


def r_pair_bars(spec, p, o):
    pairs, how = _pairs(p)
    pairs.sort(key=lambda x: (-x[2], str(x[0]), str(x[1])))
    shown = pairs[: o.get("top_n", 15)]
    vmax = max((v for *_, v in shown), default=0) or 1
    W, lw, rh = 720, 330, 24
    H = 10 + rh * len(shown)
    body = []
    for i, (a, b, v) in enumerate(shown):
        y = 8 + i * rh
        body.append(_t(lw - 10, y + 13, f"{_short(a, 11)} → {_short(b, 11)}", 11.5, INK, "end", full=f"{a} → {b}"))
        w = v / vmax * (W - lw - 60)
        body.append(_bar(lw, y + 3, w, rh - 9, PAL[0]) + _t(lw + w + 6, y + 13, fmt(v), 11, INK))
    k = len(pairs)
    notes = [f"전체 {k}쌍 중 상위 {len(shown)}쌍" if k > len(shown) else "", how]
    return _svg(W, H, f"{spec.get('title', '')} — 한 단계 이동 쌍 · 막대 길이 = 값", body), len(shown), k, " · ".join(x for x in notes if x)


def _trie(seqs, topc):
    root = {"name": None, "count": 0, "kids": {}}
    for seq in seqs:
        node = root
        for kw in seq:
            node = node["kids"].setdefault(kw, {"name": kw, "count": 0, "kids": {}})
            node["count"] += 1

    def prune(node):
        kids = sorted(node["kids"].values(), key=lambda n: (-n["count"], str(n["name"])))
        keep, rest = kids[:topc], kids[topc:]
        node["list"] = [prune(k) for k in keep]
        if rest:
            node["list"].append({"name": f"기타 {len(rest)}개", "count": sum(k["count"] for k in rest), "list": [], "rest": True})
        return node
    return prune(root)


def r_bidirectional_tree(spec, p, o):
    seed, depth, topc = p.seed, o.get("depth", 2), o.get("top_children", 5)
    after, before, used, no_before, no_after = [], [], 0, 0, 0
    for path in p.paths:
        if seed not in path:
            continue
        used += 1                                                    # 한 경로는 한 번만 센다(첫 번째로 나온 자리 기준)
        i = path.index(seed)
        nxt = path[i + 1:]
        if seed in nxt:                                              # 다음에 기준 검색어가 다시 나오면 거기서 끊는다
            nxt = nxt[: nxt.index(seed)]
        a_ = nxt[:depth]
        b_ = list(reversed(path[max(0, i - depth): i]))             # 가까운 것부터(첫 자리라 앞에는 기준 검색어가 없다)
        after.append(a_); before.append(b_)
        no_after += not a_; no_before += not b_
    tb, ta = _trie([x for x in before if x], topc), _trie([x for x in after if x], topc)

    def leaves(n):
        return max(1, sum(leaves(k) for k in n["list"])) if n["list"] else 1
    rh, colw, bw = 30, 175, 140
    nl, nr = (leaves(tb) if tb["list"] else 0), (leaves(ta) if ta["list"] else 0)
    rows_ = max(nl, nr, 1)
    W = 2 * depth * colw + bw + 40
    H = 40 + rows_ * rh
    cx, cy = W / 2, 30 + rows_ * rh / 2
    vmax = max([n["count"] for t in (tb, ta) for n in t["list"]] or [1])
    body = [_t(14, 16, "직전 검색", 11.5, MUTED), _t(W - 14, 16, "직후 검색", 11.5, MUTED, "end")]
    names_drawn = set()

    def place(node, d, side, y0, span):
        """node 의 자식들을 [y0, y0+span] 높이 안에 잎 수 비율로 배치하고 그린다"""
        tot = sum(leaves(k) for k in node["list"]) or 1
        y = y0
        out = []
        for k in node["list"]:
            h = span * leaves(k) / tot
            ky = y + h / 2
            kx = cx + side * (bw / 2 + 30 + (d - 1) * colw) + (0 if side > 0 else -bw)
            out.append((k, kx, ky, h, y))
            y += h
        return out

    def draw(node, d, side, px, py, y0, span):
        for k, kx, ky, h, ys in place(node, d, side, y0, span):
            sw = max(1.0, 12 * k["count"] / vmax)
            x1 = px
            x2 = kx if side > 0 else kx + bw
            body.append(f'<path d="M{x1:.1f},{py:.1f} C{(x1 + x2) / 2:.1f},{py:.1f} {(x1 + x2) / 2:.1f},{ky:.1f} {x2:.1f},{ky:.1f}" fill="none" '
                        f'stroke="{MUTED if k.get("rest") else PAL[0]}" stroke-opacity=".45" stroke-width="{sw:.1f}"/>')
            body.append(f'<rect x="{kx:.1f}" y="{ky - 11:.1f}" width="{bw}" height="22" rx="5" fill="var(--panel,#fff)" stroke="{LINE}"/>'
                        + _t(kx + 6, ky + 4, f"{_short(k['name'], 12 - len(fmt(k['count'])))} {fmt(k['count'])}", 11, MUTED if k.get("rest") else INK, full=k["name"]))
            if not k.get("rest"):
                names_drawn.add(k["name"])                               # 개수 = 그린 서로 다른 검색어 수('기타' 상자 제외)
            if d < depth and k["list"]:
                draw(k, d + 1, side, (kx + bw) if side > 0 else kx, ky, ys, h)
    span_all = rows_ * rh
    if tb["list"]:
        draw(tb, 1, -1, cx - bw / 2, cy, cy - span_all / 2, span_all)
    if ta["list"]:
        draw(ta, 1, 1, cx + bw / 2, cy, cy - span_all / 2, span_all)
    body.append(f'<rect x="{cx - bw / 2:.1f}" y="{cy - 14:.1f}" width="{bw}" height="28" rx="14" fill="{PAL[0]}" fill-opacity=".12" stroke="{PAL[0]}"/>'
                + _t(cx, cy + 4, _short(seed, 12), 12, INK, "middle", weight=700, full=seed))
    kws = {kw for x in before + after for kw in x}
    miss = " · ".join(x for x in (f"앞 검색 없음 {no_before}개" if no_before else "", f"뒤 검색 없음 {no_after}개" if no_after else "") if x)
    note = f"기준 검색어가 나온 경로 {used}개{' (' + miss + ')' if miss else ''} · 선 굵기 = 경로 수(같은 세션에서 이어진 검색 · 검색 건수 아님) · 갈래마다 상위 {topc}개 + 기타"
    return _svg(W, H, f"{spec.get('title', '')} — 왼쪽 직전 검색 · 가운데 기준 검색어 · 오른쪽 직후 검색", body), len(names_drawn), len(kws), note

def r_radar(spec, p, o):
    m = p.measures[0]
    axes, series = _cats(p, p.d2), _cats(p, p.d1)[:3]
    val = {(r.get(p.d1), r.get(p.d2)): r.get(m.field) for r in p.rows}
    top = 100.0 if m.kind == "score" else 1.0 if m.kind == "share" else (_yticks(max(val.values()) or 1)[-1] or 1)
    cx, cy, R = 190, 190, 130
    W, H = 600, 380
    ang = lambda i: -math.pi / 2 + 2 * math.pi * i / len(axes)
    pt = lambda i, v: (cx + R * (v / top) * math.cos(ang(i)), cy + R * (v / top) * math.sin(ang(i)))
    body = []
    for lv in (0.25, 0.5, 0.75, 1.0):                                  # 고리 4개 — 가는 실선 한 톤
        ring = " ".join(f"{cx + R * lv * math.cos(ang(i)):.1f},{cy + R * lv * math.sin(ang(i)):.1f}" for i in range(len(axes)))
        body.append(f'<polygon points="{ring}" fill="none" stroke="{LINE}"/>')
        body.append(_t(cx + 4, cy - R * lv + 11, fmt(top * lv, m.kind), 9.5, MUTED))
    for i, a in enumerate(axes):
        x, y = pt(i, top); lx, ly = pt(i, top * 1.14)
        body.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{LINE}"/>')
        anchor = "middle" if abs(math.cos(ang(i))) < 0.3 else ("start" if math.cos(ang(i)) > 0 else "end")
        body.append(_t(lx, ly + 4, _short(a, 10), 11, INK, anchor, full=a))
    emp, emp_note = _emphasis(o, set(series))
    skipped = []
    for j, s in enumerate(series):
        vs = [val.get((s, a)) for a in axes]
        if any(v is None for v in vs):
            skipped.append(s); continue
        c = _series_color(s, j, emp)
        poly = " ".join(f"{pt(i, v)[0]:.1f},{pt(i, v)[1]:.1f}" for i, v in enumerate(vs))
        body.append(f'<polygon points="{poly}" fill="{c}" fill-opacity=".12" stroke="{c}" stroke-width="2" stroke-linejoin="round"/>')
        body += [f'<circle cx="{pt(i, v)[0]:.1f}" cy="{pt(i, v)[1]:.1f}" r="3" fill="{c}"><title>{esc(s)} · {esc(a)} {fmt(v, m.kind)}</title></circle>' for i, (a, v) in enumerate(zip(axes, vs))]
        body.append(f'<line x1="400" y1="{40 + j * 22}" x2="418" y2="{40 + j * 22}" stroke="{c}" stroke-width="2.4"/>' + _t(424, 44 + j * 22, _short(_label(spec, s), 16), 11.5, INK, full=s))
    notes = [f"축 {len(axes)}개 · 눈금 0~{fmt(top, m.kind)}(모든 축 같은 눈금) · 모양은 축 순서에 따라 달라짐 — 값은 표로 확인"]
    if skipped:
        notes.append(f"값 없는 축이 있어 그리지 않음: {', '.join(skipped)}")
    if emp_note:
        notes.append(emp_note)
    finding = None
    drawn = [x for x in series if x not in skipped]
    if len(drawn) == 1:
        s = drawn[0]
        vs = sorted(((val[(s, a)], a) for a in axes), key=lambda x: (-x[0], str(x[1])))
        finding = (f"'{s}' 가장 높은 축 '{vs[0][1]}' {fmt(vs[0][0], m.kind)} · 가장 낮은 축 '{vs[-1][1]}' {fmt(vs[-1][0], m.kind)}", f"축 {len(axes)}개 값 중 최대·최소")
    elif len(drawn) >= 2:                                              # 축마다 앞선 계열의 수 — 모양이 아니라 값으로 말한다
        lead, why = {s: 0 for s in drawn}, []
        for a in axes:
            best = max(val[(s, a)] for s in drawn)
            tops = [s for s in drawn if val[(s, a)] == best]
            if len(tops) == 1:
                lead[tops[0]] += 1
            why.append(f"{a} " + "·".join(f"{s} {fmt(val[(s, a)], m.kind)}" for s in drawn))
        finding = (" · ".join(f"'{s}'가 앞선 축 {k}개" for s, k in sorted(lead.items(), key=lambda kv: (-kv[1], str(kv[0])))) + f"(축 {len(axes)}개)",
                   " · ".join(f"{s} {k}개" for s, k in lead.items()) + f" / 축 {len(axes)}개 — " + " · ".join(why) + (" · 같은 값인 축은 세지 않음" if sum(lead.values()) < len(axes) else ""))
    return _svg(W, H, f"{spec.get('title', '')} — 레이더(축 {len(axes)}개 · 같은 눈금)", body), len(series) - len(skipped), p.card[p.d1], " · ".join(notes), finding


def r_funnel(spec, p, o):
    m = p.measures[0]
    order = _funnel_order(p)
    vals = [(s, next(r[m.field] for r in p.rows if r.get(p.d1) == s)) for s in order]
    first = vals[0][1] or 1
    W, rh, bw = 720, 46, 400
    cx = 190 + bw / 2
    H = 14 + rh * len(vals)
    body = []
    worst = None
    for i, (s, v) in enumerate(vals):
        y = 10 + i * rh
        w = v / first * bw
        body.append(_t(176, y + 18, _short(s, 14), 12, INK, "end", weight=650 if i == 0 else None, full=s))
        body.append(_bar(cx - w / 2, y + 4, w, 22, PAL[0] if i == 0 else DIM, title=f"{s} {fmt(v, m.kind)}"))   # 가운데 정렬 — 기준선 없음, 양 끝 둥글게
        body.append(_t(cx + bw / 2 + 14, y + 18, f"{fmt(v, m.kind)} · {_pct(v, first)}", 11.5, INK, weight=650 if i == 0 else None))
        if i > 0:
            pv = vals[i - 1][1]
            rate = v / pv if pv else 0
            body.append(_t(cx, y + 1, f"↓ {rate * 100:.0f}%", 10, MUTED, "middle"))
            if worst is None or rate < worst[2]:
                worst = (vals[i - 1][0], s, rate)
    last = vals[-1][1]
    finding = (f"첫 단계 대비 마지막 단계 {_pct(last, first)}" + (f" · 가장 크게 줄어든 단계 '{worst[0]} → {worst[1]}' ({worst[2] * 100:.0f}%만 남음)" if worst else ""),
               f"{fmt(last, m.kind)} / {fmt(first, m.kind)} = {_pct(last, first)}" + (f" · {worst[0]} {fmt(dict(vals)[worst[0]], m.kind)} → {worst[1]} {fmt(dict(vals)[worst[1]], m.kind)} = {worst[2] * 100:.0f}%" if worst else ""))
    return _svg(W, H, f"{spec.get('title', '')} — 퍼널(막대 길이 = 첫 단계 대비 · 단계 사이 ↓ = 앞 단계 대비 남은 비율)", body), len(vals), len(vals), "막대 길이 = 첫 단계 대비 비율 · 단계 사이 ↓ = 앞 단계 대비 남은 비율 · 검색 단계 사이는 같은 사람의 이동이 아니라 집계 비교", finding


def _journey_columns(paths, steps, topc):
    """경로 → 단계별 상위 키워드와 단계 사이 이동 수. 단계 = 경로 안 순서(1단계 = 첫 검색). 반환 (cols[[(kw, n)]], links{(i, a, b): n})"""
    cols = []
    for i in range(steps):
        cnt = {}
        for x in paths:
            if len(x) > i:
                cnt[x[i]] = cnt.get(x[i], 0) + 1
        keep = sorted(cnt, key=lambda k: (-cnt[k], str(k)))[:topc]
        rest = sum(v for k, v in cnt.items() if k not in keep)
        cols.append([(k, cnt[k]) for k in keep] + ([("기타", rest)] if rest else []))
    kept = [{k for k, _ in c if k != "기타"} for c in cols]
    links = {}
    for x in paths:
        for i in range(min(steps - 1, len(x) - 1)):
            a = x[i] if x[i] in kept[i] else "기타"
            b = x[i + 1] if x[i + 1] in kept[i + 1] else "기타"
            links[(i, a, b)] = links.get((i, a, b), 0) + 1
    return cols, links


def r_journey_map(spec, p, o):
    steps = max(2, min(int(o.get("steps", 4)), 6))
    cols, links = _journey_columns(p.paths, steps, o.get("top_children", 6))
    W, T, H, L, R_, NW, GAP = 760, 30, 380, 150, 150, 12, 8
    PH = H - T - 20
    colmax = max(sum(v for _, v in c) for c in cols)
    X = lambda i: L + i / (steps - 1) * (W - L - R_ - NW)
    pos = {}                                                           # (i, kw) → (y, h)
    body = [_t(X(i) + NW / 2, 16, f"{i + 1}단계", 11, MUTED, "middle") for i in range(steps)]
    for i, c in enumerate(cols):
        y = T
        for k, v in c:
            h = v / colmax * (PH - GAP * (len(c) - 1))
            pos[(i, k)] = (y, h)
            fill = MUTED if k == "기타" else PAL[0]
            body.append(f'<rect x="{X(i):.1f}" y="{y:.1f}" width="{NW}" height="{max(h, 1):.1f}" rx="2" fill="{fill}"><title>{esc(k)} · {v}개 경로</title></rect>')
            side = -1 if i == 0 else 1
            tx = X(i) - 6 if side < 0 else X(i) + NW + 6
            body.append(_t(tx, y + h / 2 + 4, f"{_short(k, 12)} {v}", 10.5, INK if k != "기타" else MUTED, "end" if side < 0 else "start", full=k))
            y += h + GAP
    off_out, off_in = {}, {}
    for (i, a, b), v in sorted(links.items(), key=lambda kv: (kv[0][0], -kv[1], str(kv[0][1]), str(kv[0][2]))):
        ya, ha = pos[(i, a)]; yb, hb = pos[(i + 1, b)]
        la = sum(x for (ii, aa, _), x in links.items() if ii == i and aa == a) or 1
        lb = sum(x for (ii, _, bb), x in links.items() if ii == i and bb == b) or 1
        h0 = v / la * ha; h1 = v / lb * hb
        y0 = ya + off_out.get((i, a), 0); y1 = yb + off_in.get((i + 1, b), 0)
        off_out[(i, a)] = off_out.get((i, a), 0) + h0; off_in[(i + 1, b)] = off_in.get((i + 1, b), 0) + h1
        x0, x1 = X(i) + NW, X(i + 1)
        mx = (x0 + x1) / 2
        d = (f"M{x0:.1f},{y0:.1f} C{mx:.1f},{y0:.1f} {mx:.1f},{y1:.1f} {x1:.1f},{y1:.1f} v{h1:.1f} "
             f"C{mx:.1f},{y1 + h1:.1f} {mx:.1f},{y0 + h0:.1f} {x0:.1f},{y0 + h0:.1f} z")
        c = MUTED if "기타" in (a, b) else PAL[0]
        body.append(f'<path d="{d}" fill="{c}" fill-opacity=".22"><title>{esc(a)} → {esc(b)} · {v}개 경로</title></path>')
    top = max(((k, v) for k, v in links.items() if k[0] == 0 and "기타" not in k[1:]), key=lambda kv: (kv[1], str(kv[0])), default=None)
    finding = (f"1→2단계 가장 많은 이동 '{top[0][1]} → {top[0][2]}' {top[1]}개 경로", f"{top[1]} / 전체 경로 {len(p.paths)}개 = {_pct(top[1], len(p.paths))} · 경로 안 순서 기준") if top else None
    note = (f"단계 = 경로 안 순서(1단계 = 첫 검색) · 세로 길이·띠 굵기 = 경로 수(검색 건수 아님) · 단계마다 상위 {o.get('top_children', 6)} + 기타 · "
            f"{steps}단계까지(더 긴 경로는 잘라 셈) · 같은 세션에서 이어진 검색이지 한 사람의 여정이 아님")
    return _svg(W, H, f"{spec.get('title', '')} — 여정 지도(단계별 흐름 · 띠 굵기 = 경로 수)", body), len(p.paths), len(p.paths), note, finding


def _squarify(items, x, y, w, h):
    """정사각형에 가깝게 채우는 트리맵 배치(Bruls 2000) — 입력 순서가 같으면 같은 배치. items = [(키, 값)] 값 큰 순"""
    out = []
    total = sum(v for _, v in items if v > 0)
    if total <= 0 or w <= 0 or h <= 0:
        return out
    items = [(k, v * w * h / total) for k, v in items if v > 0]
    while items:
        vert = w >= h
        side = h if vert else w
        def worst(row):
            s = sum(a for _, a in row); mx = max(a for _, a in row); mn = min(a for _, a in row)
            return max(side * side * mx / (s * s), s * s / (side * side * mn)) if s else 1e9
        row, i = [items[0]], 1
        while i < len(items) and worst(row + [items[i]]) <= worst(row):
            row.append(items[i]); i += 1
        thick = sum(a for _, a in row) / side
        off = 0.0
        for k, a in row:
            ln = a / thick
            out.append((k, x, y + off, thick, ln) if vert else (k, x + off, y, ln, thick))
            off += ln
        if vert:
            x += thick; w -= thick
        else:
            y += thick; h -= thick
        items = items[i:]
    return out


def r_treemap(spec, p, o):
    m = p.measures[0]
    two = len(p.dims) == 2
    W, H = 720, 420
    body = []
    if two:
        gtot = {}
        for r in p.rows:
            gtot[r.get(p.d1)] = gtot.get(r.get(p.d1), 0) + r[m.field]
        groups, folded, rest_label = _fold_parts(list(gtot), lambda g: gtot.get(g, 0))
        if folded:
            gtot[rest_label] = sum(gtot.pop(g) for g in folded)
        total = sum(gtot.values()) or 1
        gitems = sorted(gtot.items(), key=lambda kv: (-kv[1], str(kv[0])))
        leaves_of = {g: [] for g in gtot}
        for r in p.rows:
            g = r.get(p.d1) if r.get(p.d1) in leaves_of else rest_label
            leaves_of[g].append((r.get(p.d2) if g != rest_label else f"{r.get(p.d1)} · {r.get(p.d2)}", r[m.field]))
        color = {g: (MUTED if _is_rest(g, rest_label) else MIXCOL[j % len(MIXCOL)]) for j, g in enumerate(gitems and [g for g, _ in gitems])}
        for g, gx, gy, gw, gh in _squarify(gitems, 0, 0, W, H):
            body.append(f'<rect x="{gx + 1:.1f}" y="{gy + 1:.1f}" width="{max(gw - 2, 0):.1f}" height="{max(gh - 2, 0):.1f}" fill="{color[g]}" fill-opacity=".10"/>')
            if gw > 60 and gh > 16:
                body.append(_t(gx + 6, gy + 13, f"{_short(g, 14)} {_pct(gtot[g], total)}", 11, INK, weight=650, full=g))
            ly = 18 if (gw > 60 and gh > 34) else 0
            leaves = sorted(leaves_of[g], key=lambda kv: (-kv[1], str(kv[0])))
            keep, tail = leaves[:12], leaves[12:]
            if tail:
                keep.append((f"그 외 {len(tail)}개", sum(v for _, v in tail)))
            for k, lx, lyy, lw, lh in _squarify(keep, gx + 3, gy + ly + 3, gw - 6, gh - ly - 6):
                body.append(f'<rect x="{lx + 1:.1f}" y="{lyy + 1:.1f}" width="{max(lw - 2, 0):.1f}" height="{max(lh - 2, 0):.1f}" fill="{color[g]}" fill-opacity=".55"><title>{esc(g)} · {esc(k)} {fmt(dict(keep)[k], m.kind)}</title></rect>')
                if lw > 44 and lh > 16:
                    body.append(_t(lx + 5, lyy + 13, _short(k, max(3, int(lw / 7))), 10, INK, full=k))
                    if lh > 30:
                        body.append(_t(lx + 5, lyy + 26, fmt(dict(keep)[k], m.kind), 9.5, MUTED))
        g0 = gitems[0]
        s3 = sum(v for _, v in gitems[:3])
        finding = (f"'{g0[0]}' 그룹이 전체의 {_pct(g0[1], total)}" + (f" — 상위 3개 그룹이 {_pct(s3, total)}" if len(gitems) >= 4 else ""),
                   f"{fmt(g0[1], m.kind)} / 전체 {fmt(total, m.kind)} = {_pct(g0[1], total)}" + (f" · 상위 3개 그룹 {fmt(s3, m.kind)} / {fmt(total, m.kind)} = {_pct(s3, total)}" if len(gitems) >= 4 else ""))
        note = f"면적 = 값 · 그룹 {len(gitems)}개(" + (f"{len(folded)}개를 '{rest_label}'로 묶음 · " if folded else "") + "그룹마다 상위 12 + 그 외) · 면적 비교는 길이보다 부정확 — 정확한 값은 표로"
        return _svg(W, H, f"{spec.get('title', '')} — 수요 지도(면적 = 값)", body), len(p.rows), len(p.rows), note, finding
    items = sorted(((r.get(p.d1), r[m.field]) for r in p.rows), key=lambda kv: (-kv[1], str(kv[0])))
    total = sum(v for _, v in items) or 1
    keep, tail = items[:24], items[24:]
    if tail:
        keep.append((f"그 외 {len(tail)}개", sum(v for _, v in tail)))
    emp, emp_note = _emphasis(o, {k for k, _ in items})
    lead = None if emp else keep[0][0]
    for k, x, y, w, h in _squarify(keep, 0, 0, W, H):
        c = MUTED if k.startswith("그 외 ") else (_series_color(k, 0, emp) if emp else (PAL[0] if k == lead else DIM))
        body.append(f'<rect x="{x + 1:.1f}" y="{y + 1:.1f}" width="{max(w - 2, 0):.1f}" height="{max(h - 2, 0):.1f}" fill="{c}"><title>{esc(k)} {fmt(dict(keep)[k], m.kind)}</title></rect>')
        if w > 44 and h > 16:
            body.append(_t(x + 5, y + 13, _short(k, max(3, int(w / 7))), 10.5, "#fff" if (k == lead or k in emp) else INK, weight=650 if (k == lead or k in emp) else None, full=k))
            if h > 30:
                body.append(_t(x + 5, y + 26, fmt(dict(keep)[k], m.kind), 9.5, "#fff" if (k == lead or k in emp) else MUTED))
    f0 = _bars_finding(items, m, False)
    note = " · ".join(x for x in ("면적 = 값 · 상위 24 + 그 외 · 면적 비교는 길이보다 부정확 — 정확한 값은 표로", emp_note) if x)
    return _svg(W, H, f"{spec.get('title', '')} — 수요 지도(면적 = 값)", body), min(len(items), 24), len(items), note, f0


def _force_layout(nodes, edges, W, H, iters=150):
    """힘 배치(Fruchterman·Reingold 1991) — 처음 자리를 원 둘레에 순서대로 놓으므로 같은 입력이면 같은 그림(난수 없음)"""
    n = len(nodes)
    idx = {v: i for i, v in enumerate(nodes)}
    pos = [[W / 2 + min(W, H) * 0.38 * math.cos(2 * math.pi * i / n), H / 2 + min(W, H) * 0.38 * math.sin(2 * math.pi * i / n)] for i in range(n)]
    k = math.sqrt(W * H / n) * 0.7
    wmax = max((w for _, _, w in edges), default=1) or 1
    t = W / 8
    for _ in range(iters):
        disp = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
                d = max(math.hypot(dx, dy), 0.01)
                f = k * k / d
                disp[i][0] += dx / d * f; disp[i][1] += dy / d * f
                disp[j][0] -= dx / d * f; disp[j][1] -= dy / d * f
        for a, b, w in edges:
            i, j = idx[a], idx[b]
            dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
            d = max(math.hypot(dx, dy), 0.01)
            f = d * d / k * (0.6 + 0.8 * w / wmax)
            disp[i][0] -= dx / d * f; disp[i][1] -= dy / d * f
            disp[j][0] += dx / d * f; disp[j][1] += dy / d * f
        for i in range(n):
            d = max(math.hypot(*disp[i]), 0.01)
            pos[i][0] += disp[i][0] / d * min(d, t); pos[i][1] += disp[i][1] / d * min(d, t)
        t *= 0.96
    xs, ys = [x for x, _ in pos], [y for _, y in pos]
    sx, sy = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
    return {v: ((pos[i][0] - min(xs)) / sx, (pos[i][1] - min(ys)) / sy) for v, i in idx.items()}


def r_knowledge_graph(spec, p, o):
    es = [(e["source"], e["target"], float(e.get("value")) if _num(e.get("value")) else 1.0) for e in p.edges if e["source"] != e["target"]]
    deg = {}
    for a, b, w in es:
        deg[a] = deg.get(a, 0) + w; deg[b] = deg.get(b, 0) + w
    keep = sorted(deg, key=lambda v: (-deg[v], str(v)))[: o.get("top_n", 40)]
    kset = set(keep)
    es = [(a, b, w) for a, b, w in es if a in kset and b in kset]
    cls = {x["id"]: x.get("class") for x in p.nodes if x.get("class")}
    classes = sorted({cls[v] for v in keep if v in cls}, key=lambda c: (-sum(1 for v in keep if cls.get(v) == c), str(c)))
    ccol = {c: MIXCOL[i] for i, c in enumerate(classes[:MAX_PARTS])}
    W, T, H = 760, 30 if classes else 10, 500
    pos = _force_layout(keep, es, W - 80, H - T - 40)
    XY = lambda v: (40 + pos[v][0] * (W - 80), T + 20 + pos[v][1] * (H - T - 40))
    dmax = max(deg[v] for v in keep) or 1
    wmax = max((w for _, _, w in es), default=1) or 1
    body = []
    for i, c in enumerate(classes):
        x = 20 + i * 110
        body.append(f'<circle cx="{x + 5}" cy="14" r="5" fill="{ccol.get(c, MUTED)}"/>' + _t(x + 14, 18, _short(c, 8), 10.5, INK, full=c))
    if len(classes) > MAX_PARTS:
        body.append(_t(20 + len(classes) * 110, 18, f"나머지 종류 {len(classes) - MAX_PARTS}개 = 회색", 10.5, MUTED))
    for a, b, w in sorted(es, key=lambda e: (-e[2], str(e[0]), str(e[1]))):
        (x0, y0), (x1, y1) = XY(a), XY(b)
        body.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="{MUTED}" stroke-opacity=".35" stroke-width="{0.6 + 2.4 * w / wmax:.1f}"><title>{esc(a)} — {esc(b)}{(" " + fmt(w)) if wmax != 1 or w != 1 else ""}</title></line>')
    for v in keep:
        x, y = XY(v)
        r = 4 + 8 * math.sqrt(deg[v] / dmax)
        c = ccol.get(cls.get(v), MUTED if classes else PAL[0])
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{c}" stroke="var(--panel,#fff)" stroke-width="1.5"><title>{esc(v)} · 연결 {fmt(deg[v])}</title></circle>')
        body.append(_t(x + r + 3, y + 4, _short(v, 12), 10, INK, full=v))
    top = keep[0]
    nk = len(deg)
    finding = (f"연결이 가장 많은 '{top}' (연결 {fmt(deg[top])})", f"항목 {nk}개 · 연결 {len(p.edges)}개 중 그린 항목 {len(keep)}개 · 연결 = 값 합(값 없으면 개수)")
    note = (f"원 크기 = 연결 합 · 선 굵기 = 연결 값 · 자리와 거리는 연결 구조만 반영(뜻 없음) · 같은 입력이면 같은 그림" + (f" · 종류 색 = nodes.class" if classes else "")
            + (f" · 연결 많은 상위 {len(keep)}개만(전체 {nk}개)" if nk > len(keep) else ""))
    return _svg(W, H, f"{spec.get('title', '')} — 지식 그래프(원 = 항목 · 선 = 연결)", body), len(keep), nk, note, finding


def r_waterfall(spec, p, o):
    """증감 다리 — 시작 막대(회색) → 기여 막대(증가/감소 색, 떠 있음) → 끝 막대(강조색). 시작 + Σ기여 = 끝이 아니면 멈춘다"""
    m = p.measures[0]
    b = p.bridge
    rows = list(p.rows)
    start = next(r for r in rows if r.get(p.d1) == b["start"]); end = next(r for r in rows if r.get(p.d1) == b["end"])
    mids = [r for r in rows if r is not start and r is not end]
    if o.get("order"):
        mids.sort(key=lambda r: o["order"].index(r.get(p.d1)) if r.get(p.d1) in o["order"] else 1e9)
    sv, ev = start[m.field], end[m.field]
    total = sv + sum(r[m.field] for r in mids)
    tol = max(abs(ev) * 0.005, 0.5)
    if abs(total - ev) > tol:
        raise VizError(f"시작 {fmt(sv, m.kind)} + 기여 합 {fmt(sum(r[m.field] for r in mids), m.kind)} = {fmt(total, m.kind)} ≠ 끝 {fmt(ev, m.kind)} — 기여가 빠졌거나 값이 틀렸다")
    seq = [(b["start"], 0, sv, "start")]
    run = sv
    for r in mids:
        seq.append((r.get(p.d1), run, run + r[m.field], "delta")); run += r[m.field]
    seq.append((b["end"], 0, ev, "end"))
    W, L, R_, T, B = 720, 60, 20, 24, 48
    PH = 300
    n_ = len(seq)
    slot = (W - L - R_) / n_
    bw = min(88, slot * 0.62)
    lo = min(0, min(min(a, c) for _, a, c, _ in seq)); hi = max(max(a, c) for _, a, c, _ in seq)
    ticks = _yticks(hi)
    top = max(ticks[-1], hi) or 1
    Y = lambda v: T + (1 - (v - lo) / (top - lo)) * PH
    body = [f'<line x1="{L}" y1="{Y(0):.1f}" x2="{W - R_}" y2="{Y(0):.1f}" stroke="{MUTED}"/>', _t(L - 6, Y(0) + 4, "0", 9.5, MUTED, "end")]
    prev = None
    for i, (lab, a, c, kind_) in enumerate(seq):
        x = L + slot * i + (slot - bw) / 2
        y0, y1 = Y(max(a, c)), Y(min(a, c))
        d = c - a
        fill = DIM if kind_ == "start" else PAL[0] if kind_ == "end" else (UP if d >= 0 else DOWN)
        body.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw:.1f}" height="{max(y1 - y0, 1):.1f}" fill="{fill}"><title>{esc(lab)} {fmt(d if kind_ == "delta" else c, "change" if (kind_ == "delta" and m.kind == "change") else m.kind)}</title></rect>')
        if prev is not None:                                              # 연결선 — 앞 막대의 끝 높이를 다음 막대로 잇는다
            body.append(f'<line x1="{prev[0]:.1f}" y1="{prev[1]:.1f}" x2="{x:.1f}" y2="{prev[1]:.1f}" stroke="{LINE}"/>')
        prev = (x + bw, Y(c))
        val = fmt(c, m.kind) if kind_ != "delta" else (("+" if d >= 0 else "−") + fmt(abs(d), m.kind))
        body.append(_t(x + bw / 2, y0 - 6, val, 11, INK, "middle", weight=650 if kind_ != "delta" else None))
        body.append(_t(x + bw / 2, T + PH + 16, _short(lab, max(4, int(slot / 7))), 10.5, INK if kind_ != "delta" else MUTED, "middle", full=lab))
    H = T + PH + B
    pct = (ev - sv) / sv * 100 if sv else None
    big = max(mids, key=lambda r: abs(r[m.field]), default=None)
    text = f"'{b['start']}' {fmt(sv, m.kind)} → '{b['end']}' {fmt(ev, m.kind)}" + (f" ({pct:+.0f}%)" if pct is not None else "")
    if big is not None:
        text += f" · 가장 큰 기여 '{big.get(p.d1)}' {('+' if big[m.field] >= 0 else '−')}{fmt(abs(big[m.field]), m.kind)}"
    basis = f"{fmt(sv, m.kind)} + ({' '.join(('+' if r[m.field] >= 0 else '−') + fmt(abs(r[m.field]), m.kind) for r in mids)}) = {fmt(ev, m.kind)}" + (f" · ({fmt(ev, m.kind)} − {fmt(sv, m.kind)}) / {fmt(sv, m.kind)} = {pct:+.0f}%" if pct is not None else "")
    note = f"떠 있는 막대 = 기여(증가 {UP_WORD} · 감소 {DOWN_WORD}) · 시작·끝은 0부터 · 시작 + 기여 합 = 끝(검산 통과) · 기여 {len(mids)}개"
    return _svg(W, H, f"{spec.get('title', '')} — 증감 다리(시작 → 기여 → 끝)", body), n_, n_, note, (text, basis)


UP_WORD, DOWN_WORD = "청록", "빨강"

RENDER = {"waterfall": r_waterfall, "radar": r_radar, "funnel": r_funnel, "journey_map": r_journey_map, "treemap": r_treemap, "knowledge_graph": r_knowledge_graph,
          "table_graphic": r_table_graphic, "heat_table": r_heat_table, "back_to_back": r_back_to_back,
          "pair_bars": r_pair_bars, "bidirectional_tree": r_bidirectional_tree, "kpi": r_kpi, "hbar": r_hbar, "diverging_bar": r_diverging_bar, "grouped_bar": r_grouped_bar,
          "stacked_100": r_stacked_100, "donut": r_donut, "line": r_line, "spark_grid": r_spark_grid,
          "season_heatmap": r_season_heatmap, "heatmap": r_heatmap, "scatter_quadrant": r_scatter_quadrant,
          "bump": r_bump, "flow_tree": r_flow_tree, "table": r_table, "edge_table": r_edge_table}


def table_twin(spec: dict, p: Profile) -> str:
    """차트와 같은 데이터를 접힌 표로 — 값을 색·길이로만 읽지 않게(접근성 · 숫자 대조)"""
    cap_n = 500
    if p.rows:
        tb, total = r_table(spec, p, {"top_n": cap_n})[0], len(p.rows)
    elif p.paths:
        tb, total = _table_html(["검색 경로(같은 세션에서 이어진 검색)", "단계"], [[" → ".join(x), len(x)] for x in p.paths[:cap_n]]), len(p.paths)
    elif p.edges:
        tb, total = r_edge_table(spec, p, {"top_n": cap_n})[0], len(p.edges)
    else:
        return ""
    head = f"표로 보기 — 전체 {total:,}행 중 {cap_n}행" if total > cap_n else "표로 보기 — 같은 데이터"
    return (f'<details class="viz-twin" style="margin-top:8px"><summary style="font-size:12px;color:{MUTED};cursor:pointer">{head}</summary>'
            f'<div style="overflow-x:auto;margin-top:6px">{tb}</div></details>')


def render(spec: dict, chart: str | None = None, intent: str | None = None, with_table: bool = False, reason: str | None = None) -> tuple[str, Choice]:
    """스펙 → (<figure> HTML, 선택). unit·period가 없으면 멈춘다. with_table 이면 같은 데이터의 접힌 표를 붙인다."""
    for k in ("unit", "period"):
        if not str(spec.get(k) or "").strip():
            raise VizError(f"'{k}'가 없음 — 차트마다 단위·기간을 적는다")
    choice = select(spec, intent)
    if chart:
        if chart not in CATALOG:
            raise VizError(f"카탈로그에 없는 차트 '{chart}' — {list(CATALOG)}")
        if chart not in choice.eligible:
            raise VizError(f"'{chart}'는 이 데이터에 못 씀: {choice.rejected.get(chart)} (데이터에 맞는 차트: {choice.eligible})")
        choice = Choice(chart, reason or "지정 — 데이터 조건 충족", choice.eligible, choice.rejected, "", choice.profile, choice.ranked, choice.hints)
    p = profile(spec)
    o = spec.get("options") or {}
    out = RENDER[choice.chart](spec, p, o)
    body, n, k = out[:3]
    note = out[3] if len(out) > 3 else ""
    auto_f = out[4] if len(out) > 4 else None
    # 헤더 — 제목 → 부제(단위·기간·범위·기준월·수집·채널·시장 주석) → 발견 한 줄(+근거). 읽는 순서를 만든다
    sub = [f"단위 {esc(spec['unit'])}", f"기간 {esc(spec['period'])}"]
    if k > n and "전체" not in note:
        sub.append(f"전체 {k:,}개 중 {n:,}개 표시")
    if note:
        sub.append(esc(note))
    for key, name in (("base_month", "기준월"), ("collected_at", "수집"), ("channel", "채널")):
        if spec.get(key):
            sub.append(f"{name} {esc(spec[key])}")
    if spec.get("market_note"):
        sub.append(esc(spec["market_note"]))
    want = o.get("finding", "auto")
    if want in (None, False, "off"):
        finding, basis, src = None, "", ""
    elif isinstance(want, str) and want != "auto":
        finding, basis, src = want.strip(), "", "manual"
        miss = finding_gaps(finding, _visible_text(body), "")
        if miss:
            raise VizError(f"발견 문장 속 {', '.join(miss)} 이(가) 차트에 없음 — 직접 쓴 발견은 차트에 있는 숫자만 쓴다")
    elif auto_f:
        finding, basis, src = auto_f[0], auto_f[1], "auto"
    else:
        finding, basis, src = None, "", ""
    # 액션 타이틀(options.title_mode = "action" — 경영진 보고 스타일): 발견 문장이 제목 자리에, 설명 제목은 부제 첫머리로.
    # 발견이 없으면(틀 없는 차트) 보통 제목으로 돌아가고 그 사실을 부제에 적는다 — 제목을 지어내지 않는다
    action = o.get("title_mode") == "action"
    title_text = spec.get("title", "")
    if action and finding:
        title_text, sub = finding, ([esc(spec["title"])] if spec.get("title") else []) + sub
    elif action:
        sub.append("발견 문장 틀이 없는 차트라 설명 제목을 씀")
    head = []
    if spec.get("exhibit"):
        head.append(f'<div class="viz-kicker" style="font-size:11px;letter-spacing:.06em;color:{MUTED};text-transform:uppercase">{esc(spec["exhibit"])}</div>')
    if title_text:
        head.append(f'<div class="viz-title" style="font-size:var(--viz-fs-title,16px);font-weight:650;letter-spacing:-.01em;color:{INK}">{esc(title_text)}</div>')
    head.append(f'<div class="viz-sub" style="font-size:var(--viz-fs-body,12px);color:{MUTED};margin-top:2px">{" · ".join(sub)}</div>')
    if finding and not (action and finding):
        head.append(f'<p class="viz-finding" style="font-size:var(--viz-fs-finding,14px);font-weight:600;color:{INK};margin:10px 0 0;padding:6px 12px;'
                    f'border-left:3px solid {PAL[0]};border-radius:0 8px 8px 0;background:color-mix(in srgb,{PAL[0]} 6%,transparent)">{esc(finding)}</p>')
    if finding and basis:
        head.append(f'<div class="viz-basis" style="font-size:11px;color:{MUTED};margin:3px 0 0 {"0" if action else "15px"}">근거 {esc(basis)}</div>')
    # 결론 줄(options.takeaway) — 차트 아래 강조색 한 줄. 사람이 쓰는 문장이라 숫자는 차트 글자·근거에 있는 것만
    takeaway = (o.get("takeaway") or "").strip()
    if takeaway:
        miss = finding_gaps(takeaway, _visible_text(body), basis)
        if miss:
            raise VizError(f"결론 줄 속 {', '.join(miss)} 이(가) 차트·근거에 없음 — 결론은 차트에 있는 숫자로만 쓴다")
    take_html = f'<p class="viz-takeaway" style="font-size:var(--viz-fs-finding,14px);font-weight:600;color:{PAL[0]};margin:8px 0 0">{esc(takeaway)}</p>' if takeaway else ""
    cap = []
    nr = spec.get("not_returned") or []
    if nr:
        cap.append(f"미반환 {len(nr)}개: {esc(', '.join(map(str, nr[:5])))}{' 외' if len(nr) > 5 else ''}")
    notes = [str(x) for x in (spec.get("footnotes") or [])][:2]           # 각주 2개까지 ¹ ² — 더 많으면 본문으로
    if len(spec.get("footnotes") or []) > 2:
        raise VizError("각주는 2개까지 — 더 많으면 본문 문장으로 옮긴다")
    for i, note_ in enumerate(notes):
        cap.append(f"{'¹²'[i]} {esc(note_)}")
    if spec.get("source"):
        cap.append(esc(spec["source"]))
    twin = table_twin(spec, p) if with_table and choice.chart not in ("table", "table_graphic", "edge_table", "heat_table") else ""
    fattr = f' data-viz-finding="{esc(finding)}" data-viz-finding-src="{src}" data-viz-basis="{esc(basis)}"' if finding else ""
    fattr += f' data-viz-takeaway="{esc(takeaway)}"' if takeaway else ""
    fattr += ' data-viz-title="action"' if (action and finding) else ""
    twin_attr = ' data-viz-twin="1"' if twin else ""                      # f-string 안에 백슬래시를 두지 않는다(3.10·3.11 호환)
    fig = (f'<figure class="viz" data-viz="{choice.chart}" data-viz-reason="{esc(choice.reason)}" data-viz-unit="{esc(spec["unit"])}" '
           f'data-viz-period="{esc(spec["period"])}" data-viz-n="{n}" data-viz-k="{k}"{twin_attr}{fattr} style="margin:16px 0">'
           f'<header class="viz-head" style="margin:0 0 10px">{"".join(head)}</header>'
           f'{body}{take_html}{twin}' + (f'<figcaption style="font-size:12px;color:{MUTED};margin-top:6px">{" · ".join(cap)}</figcaption>' if cap else "") + '</figure>')
    return fig, choice


_NUM_TOK = re.compile(r"[+\-−]?\d[\d,]*(?:\.\d+)?(?:%|개월|개|위|배)?")
_TAG = re.compile(r"<[^>]+>")
_HEAD = re.compile(r"<header class=\"viz-head\".*?</header>|<p class=\"viz-takeaway\".*?</p>", re.S)


def _visible_text(html_: str) -> str:
    return html.unescape(_TAG.sub(" ", html_))


def finding_gaps(finding: str, figure_text: str, basis: str) -> list:
    """발견 문장 속 숫자 토큰 중 차트 글자·근거 어디에도 없는 것(문구 속 숫자는 계산값과 대조)"""
    have = set(_NUM_TOK.findall(figure_text)) | set(_NUM_TOK.findall(basis))
    have |= {t.replace("−", "-") for t in have}
    return [t for t in dict.fromkeys(_NUM_TOK.findall(finding)) if t not in have and t.replace("−", "-") not in have]


def auto(spec: dict, intent: str | None = None, chart: str | None = None, with_table: bool = True) -> tuple[str, Choice]:
    """코드용 한 번 호출 — 프로파일 → 추천 → 렌더(기본 표 쌍둥이 포함). 반환 (figure HTML, Choice: ranked·hints 포함)"""
    return render(spec, chart, intent, with_table=with_table)


# ── 산출물 검사 ───────────────────────────────────────────────────────────
_FIG = re.compile(r"<figure\b([^>]*\bclass=\"[^\"]*\bviz\b[^\"]*\"[^>]*)>(.*?)</figure>", re.S)
_ATTR = re.compile(r'data-viz((?:-[a-z]+)*)="([^"]*)"')
_BANNED = re.compile(r"<canvas\b|new Chart\(|chart\.umd|cdn\.jsdelivr\.net/npm/(chart|d3)|d3\.v\d", re.I)


def check_html(text: str) -> dict:
    """산출물 HTML의 차트가 카탈로그·캡션 규칙을 지켰는지.
    verdict: pass · fail(카탈로그 밖 차트·단위·기간 누락·캔버스/차트 라이브러리) · legacy(표준 차트가 하나도 없음 — 이 카탈로그 이전에 만든 페이지)"""
    findings, charts = [], {}
    figs = _FIG.findall(text)
    for attrs, inner in figs:
        a = {(k or ""): v for k, v in _ATTR.findall(attrs)}
        cid = a.get("")
        charts[cid] = charts.get(cid, 0) + 1
        if cid not in CATALOG:
            findings.append({"severity": "BLOCK", "issue": f"카탈로그에 없는 차트 '{cid}'"})
        for key, name in (("-unit", "단위"), ("-period", "기간")):
            if not a.get(key, "").strip():
                findings.append({"severity": "BLOCK", "issue": f"'{cid}' 차트에 {name} 없음"})
        if not a.get("-reason", "").strip():
            findings.append({"severity": "WARN", "issue": f"'{cid}' 차트에 선택 이유 없음(viz.render를 거치지 않은 차트)"})
        if a.get("-finding"):
            ftxt = html.unescape(a["-finding"])
            basis = html.unescape(a.get("-basis", "")) if a.get("-finding-src") == "auto" else ""
            miss = finding_gaps(ftxt, _visible_text(_HEAD.sub("", inner)), basis)
            if miss:
                findings.append({"severity": "BLOCK", "issue": f"'{cid}' 발견 문장 속 {', '.join(miss)} 이(가) 차트·근거에 없음"})
        if a.get("-takeaway"):
            basis = html.unescape(a.get("-basis", "")) if a.get("-finding-src") == "auto" else ""
            miss = finding_gaps(html.unescape(a["-takeaway"]), _visible_text(_HEAD.sub("", inner)), basis)
            if miss:
                findings.append({"severity": "BLOCK", "issue": f"'{cid}' 결론 줄 속 {', '.join(miss)} 이(가) 차트·근거에 없음"})
    stripped = _FIG.sub("", text)
    for mt in _BANNED.finditer(text):
        findings.append({"severity": "BLOCK", "issue": f"캔버스·차트 라이브러리 흔적 '{mt.group(0)}'"})
    untracked = len(re.findall(r"<svg\b[^>]*role=\"img\"", stripped))
    if any(f["severity"] == "BLOCK" for f in findings):
        verdict = "fail"
    elif not figs:
        verdict = "legacy"
    else:
        verdict = "pass"
    if figs and untracked:
        findings.append({"severity": "NOTE", "issue": f"표준 카탈로그를 거치지 않은 차트 SVG {untracked}개(이관 대상)"})
    return {"verdict": verdict, "figures": len(figs), "charts": charts, "untracked_svg": untracked, "findings": findings}
