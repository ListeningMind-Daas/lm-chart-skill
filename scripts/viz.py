#!/usr/bin/env python3
"""표준 시각화 CLI (viz-data/v1 · API 호출 없음) — 계약: lib/viz.py 머리말 · references/viz-catalog.md

에이전트는 데이터를 확인한 뒤 차트를 손으로 고르거나 그리지 않고 이 순서로 쓴다.
  1. python3 viz.py select <spec.json> [--intent compare]   # 데이터 모양 → 차트 + 이유 + 대안 + 못 쓰는 차트와 이유
  2. python3 viz.py render <spec.json> [--chart id] [--out f] [--with-table] # <figure class="viz"> 조각(리포트 코드가 넣는다 · --with-table 은 접힌 표 쌍둥이)
  3. python3 viz.py check <산출물.html>…                        # 차트가 카탈로그·단위·기간 규칙을 지켰나

기타
  python3 viz.py catalog [--json]            # 차트 목록(id·이름·답하는 질문·쓰임 예)
  python3 viz.py gallery --out <파일.html>    # 견본 데이터로 카탈로그 전 차트 렌더(개발 확인용)
  python3 viz.py reference --out <파일.html> [--public]  # 사람이 보는 차트 레퍼런스 한 장(견본 + viz-catalog.md 조건·규칙 · --public 은 내부 명령 제외)
  python3 viz.py auto <데이터.csv|json> --unit <단위> --period <기간> [--intent …] [--chart id] [--compare] [--out <페이지.html>] [--json]
      # 한 번에: 데이터 읽기 → 프로파일 → 추천 상위 3(점수·이유) → 1위(또는 지정) 렌더 + 표 쌍둥이 → 페이지. --compare 는 상위 3을 모두 그린다
종료 코드: 0 = 정상 · 2 = 스펙 오류(조건 미충족 차트 지정·단위/기간 누락) · 11 = check 실패
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lib import viz as V  # noqa: E402
from lib.viz_samples import SAMPLES  # noqa: E402


def _load(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf8"))


def _cast(v: str):
    t = (v or "").strip()
    if t == "":
        return None
    for conv in (int, float):
        try:
            return conv(t.replace(",", ""))
        except ValueError:
            pass
    return t


_YEAR_RE = re.compile(r"^(19|20)\d{2}$")
_YM_RE = re.compile(r"^\d{4}-\d{2}$")


def _fix_columns(rows: list) -> list:
    """연도 열(2023·2024…)은 범주(순서)로, '12%' 는 비율(0.12)로. 가로형(열 이름이 YYYY-MM)은 세로형으로 바꾸라고 멈춘다"""
    if not rows:
        return rows
    cols = list(rows[0])
    if sum(1 for c in cols if _YM_RE.match(str(c))) >= 3:
        raise V.VizError("가로형 csv(열 이름이 YYYY-MM) — 세로형(월 열 하나 + 값 열 하나)으로 바꿔 준다")
    for c in cols:
        vals = [r.get(c) for r in rows if r.get(c) is not None]
        if vals and all(isinstance(v, int) and not isinstance(v, bool) and _YEAR_RE.match(str(v)) for v in vals) and (re.search(r"연도|년도|year", str(c), re.I) or len(set(vals)) <= 10):
            for r in rows:
                if r.get(c) is not None:
                    r[c] = str(r[c])
        elif vals and all(isinstance(v, str) and re.match(r"^-?[0-9.,]+\s*%$", v) for v in vals):
            for r in rows:
                if r.get(c) is not None:
                    r[c] = float(str(r[c]).rstrip("% ").replace(",", "")) / 100
    return rows


def load_data(path: str) -> dict:
    """csv(머리행 있음) 또는 json(행 목록 · 스펙 dict)을 스펙 dict 로. 숫자는 숫자로, 빈칸은 결측(None)으로"""
    import csv
    p = Path(path)
    if p.suffix.lower() == ".csv":
        with p.open(encoding="utf-8-sig", newline="") as f:
            rows = [{k: _cast(v) for k, v in r.items()} for r in csv.DictReader(f)]
        return {"rows": _fix_columns(rows)}
    obj = json.loads(p.read_text(encoding="utf8"))
    if isinstance(obj, list):
        return {"rows": obj}
    if isinstance(obj, dict):
        if not any(k in obj for k in ("rows", "edges", "paths")):
            raise V.VizError(f"json dict 에 rows·edges·paths 가 없다(키: {', '.join(list(obj)[:6])}) — 행 목록([{{…}}])이나 viz-data 스펙을 준다. API 응답 원본이면 data 를 먼저 행으로 펼친다")
        return obj
    raise V.VizError("json 은 행 목록([{…}]) 또는 스펙(dict)이어야 한다")


def _card(fig: str) -> str:
    """차트 카드 한 장 — 표가 아닌 차트에는 좁은 화면용 '옆으로 밀어 보세요' 안내를 붙인다 (f-string 안 백슬래시를 피해 3.10 에서도 돈다)"""
    head = fig.split("<figcaption")[0].split("viz-twin")[0]
    swipe = "" if '<table class="viz-table"' in head else '<p class="swipe">← 차트를 옆으로 밀어 보세요</p>'
    return f'<section class="card">{swipe}{fig}</section>'


def auto_page(spec: dict, figs: list, choice, public: bool = False, theme: str = "default") -> str:
    """auto 결과 한 장 — 추천 순위·근거 · 데이터에서 읽은 것 · 차트(비교면 여러 장)"""
    ranked = "".join(f"<li><b>{V.esc(r['name'])}</b> <span class=\"en\">{V.esc(r['en'])}</span>"
                     + ("" if public else f" <code>{r['chart']}</code>") + f" — {V.esc(' · '.join(r['reasons']))}</li>" for r in choice.ranked)
    hints = "" if public else "".join(f"<li>{V.esc(h)}</li>" for h in choice.hints)
    title = spec.get("title") or "차트"
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{V.esc(title)}</title><style>{_ref_css(theme)}</style></head><body><main>"
            f"<h1>{V.esc(title)}</h1><p class=\"sub\">단위 {V.esc(spec['unit'])} · 기간 {V.esc(spec['period'])}" + (f" · {V.esc(spec['source'])}" if spec.get("source") else "") + "</p>"
            "<h2>어떤 차트가 맞나</h2><ol class=\"pick\">" + ranked + "</ol>"
            + (f"<p class=\"sub\">데이터에서 읽은 것</p><ul class=\"pick\">{hints}</ul>" if hints else "")
            + "".join(_card(fig) for fig in figs)
            + "</main></body></html>")


def gallery_html() -> str:
    parts = []
    for cid, c in V.CATALOG.items():
        fig, ch = V.render(SAMPLES[cid])
        parts.append(f'<section><h2>{V.esc(c.name)} <code>{cid}</code></h2><p class="q">{V.esc(c.question)} · 쓰임 예: {V.esc(c.examples)}</p>'
                     f'<p class="why">선택 이유: {V.esc(ch.reason)}</p>{fig}</section>')
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>표준 차트 카탈로그</title><style>:root{--ink:#1f2430;--muted:#6b7280;--line:#e5e7eb;--panel:#fff;--bg:#f7f7f8}"
            "@media (prefers-color-scheme:dark){:root{--ink:#e7e9ee;--muted:#9aa3b2;--line:#2c313c;--panel:#161a22;--bg:#0f1218}}"
            "body{background:var(--bg);color:var(--ink);font-family:-apple-system,'Apple SD Gothic Neo','Pretendard',sans-serif;margin:0 auto;max-width:860px;padding:24px 16px}"
            "section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin:16px 0}"
            "h2{font-size:17px;margin:0 0 4px}code{font-size:12px;color:var(--muted)}.q,.why{font-size:13px;color:var(--muted);margin:2px 0}</style></head>"
            "<body><h1>표준 차트 카탈로그</h1><p class=\"q\">견본 데이터(가짜 값) · lib/viz.py가 데이터 모양을 보고 고른 차트</p>"
            + "".join(parts) + "</body></html>")


DOC = HERE.parent / "references/viz-catalog.md"


def _strip_code(s: str) -> str:
    """공개판: 문구 속 옵션 이름(`log_x` 등)과 그 괄호를 뺀다 — 업무 독자에게 필요 없는 코드 이름"""
    s = re.sub(r"\(`[^`]*`[^()]*\)", "", s)                     # (`옵션`, 설명) 괄호째
    s = re.sub(r"\s*`[^`]*`", "", s)                                # 남은 코드 조각
    return re.sub(r"\(\s*\)", "", re.sub(r"  +", " ", s)).strip()


def _md_inline(s: str, public: bool = False) -> str:
    """문서 셀의 `코드`·**굵게**만 HTML로(나머지는 이스케이프)"""
    out = V.esc((_strip_code(s) if public else s).strip())
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)


def _doc_section(text: str, num: int) -> str:
    return text.split(f"\n## {num}.")[1].split("\n## ")[0]


def doc_rows() -> dict:
    """viz-catalog.md §4 표 → {id: {조건, 규칙, 쓰임 예}} — 페이지가 문서와 어긋나지 않게 문서에서 읽는다"""
    rows = {}
    for line in _doc_section(DOC.read_text(encoding="utf8"), 4).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) == 7 and cells[0] in V.CATALOG:
            rows[cells[0]] = {"en": cells[2], "cond": cells[4], "rules": cells[5], "examples": cells[6]}
    missing = set(V.CATALOG) - set(rows)
    if missing:
        raise V.VizError(f"viz-catalog.md §4 표에 없는 차트: {sorted(missing)}")
    return rows


def doc_selection() -> list:
    """viz-catalog.md §5 기본 선택 순서(번호 목록)"""
    items = [re.sub(r"^\d+\.\s*", "", l).strip() for l in _doc_section(DOC.read_text(encoding="utf8"), 5).splitlines() if re.match(r"^\d+\.", l)]
    ids = sorted(V.CATALOG, key=len, reverse=True)                     # edge_table 을 table 보다 먼저
    rx = re.compile(r"(?<![a-z_])(" + "|".join(ids) + r")(?![a-z_0-9])")
    return [rx.sub(lambda m: f"**{V.CATALOG[m.group(1)].name}**", it) for it in items]   # 사람이 읽는 페이지 — id 대신 이름


_REF_CSS_TPL = """
:root{--ink:#1f2430;--ink2:#3b4252;--muted:#6b7280;--line:#e5e7eb;--panel:#fff;--bg:#f6f7f9;--chip:#eef2ff;--accent:#2563eb;
{LIGHT_TOKENS}}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--ink:#e7e9ee;--ink2:#c9ced8;--muted:#9aa3b2;--line:#2c313c;--panel:#161a22;--bg:#0f1218;--chip:#1e2640;--accent:#7aa2ff;
{DARK_TOKENS}}}
:root[data-theme="dark"]{--ink:#e7e9ee;--ink2:#c9ced8;--muted:#9aa3b2;--line:#2c313c;--panel:#161a22;--bg:#0f1218;--chip:#1e2640;--accent:#7aa2ff;
{DARK_TOKENS}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Pretendard','Noto Sans KR',sans-serif;
margin:0;line-height:1.6;-webkit-text-size-adjust:100%}
main{max-width:880px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 8px;letter-spacing:-.01em}
.lead{font-size:16px;color:var(--ink2);margin:0 0 4px}
.sub{font-size:13.5px;color:var(--muted);margin:0}
h2{font-size:19px;margin:40px 0 12px}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0 0;padding:0;list-style:none}
.toc a{display:inline-block;font-size:13px;padding:4px 10px;border-radius:999px;background:var(--chip);color:var(--ink);text-decoration:none}
.toc a:hover{color:var(--accent)}
.pick{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 20px 12px 36px;margin:0;font-size:14px}
.pick li{margin:4px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;margin:16px 0;scroll-margin-top:16px}
.card h3{font-size:18px;margin:0;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.card h3 code{font-size:12px;color:var(--muted);font-weight:400}
.q{font-size:14.5px;color:var(--ink2);margin:4px 0 2px}
.ex{font-size:13px;color:var(--muted);margin:0}
.spec{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
.spec div{border-top:1px solid var(--line);padding-top:8px;font-size:13px;color:var(--ink2)}
.spec b{display:block;font-size:12px;color:var(--muted);font-weight:600;margin-bottom:2px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
figure.viz{overflow-x:auto;-webkit-overflow-scrolling:touch}
.swipe{display:none;font-size:12px;color:var(--muted);margin:8px 0 0}
@media (max-width:640px){figure.viz > svg{min-width:560px}.swipe{display:block}}
.states{border-collapse:collapse;font-size:13px;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:12px}.states td,.states th{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.states th{color:var(--muted);font-weight:600;font-size:12px}.states .sw{width:36px}
.card h3 .en{font-size:13px;font-weight:500;color:var(--muted)}
.names{border-collapse:collapse;font-size:12.5px;margin-top:8px}.names td,.names th{padding:3px 10px 3px 0;text-align:left;border-bottom:1px solid var(--line)}
details{margin-top:32px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 20px}
summary{cursor:pointer;font-weight:600}
details pre{white-space:pre-wrap;font-size:12.5px;color:var(--ink2)}
footer{margin-top:40px;font-size:12.5px;color:var(--muted)}
@media (max-width:640px){.spec{grid-template-columns:1fr}h1{font-size:24px}.card{padding:16px}}
@media print{body{background:#fff}.card,details{break-inside:avoid;border-color:#ccc}.toc{display:none}}
"""

def _ref_css(theme: str = "default") -> str:
    return _REF_CSS_TPL.replace("{LIGHT_TOKENS}", V.css_tokens("light", theme)).replace("{DARK_TOKENS}", V.css_tokens("dark", theme))


_REF_CSS = _ref_css()


def doc_states() -> list:
    """viz-catalog.md §2b 값의 상태 표 → [(상태, 뜻, 스펙, 화면)]"""
    sec = DOC.read_text(encoding="utf8").split("\n## 2b.")[1].split("\n## ")[0]
    out = []
    for line in sec.splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split(" | ")]
        if len(cells) == 4 and cells[0] not in ("상태", "---") and not cells[0].startswith("-"):
            out.append(tuple(cells))
    return out


_SWATCH = {"결측": "missing", "조회 안 함": "not_queried", "기저 미달": "below_gate"}


def _states_html(public: bool) -> str:
    rows = []
    for name, mean, spec_, screen in doc_states():
        kind = _SWATCH.get(name)
        sw = (f'<svg width="30" height="18" viewBox="0 0 30 18" aria-hidden="true">{V.HATCH if kind == "not_queried" else ""}'
              f'{V._state_cell(kind, 1, 1, 28, 16, show_text=False)}</svg>') if kind else ""
        spec_cell = "" if public else f"<td>{_md_inline(spec_)}</td>"
        rows.append(f"<tr><td class=\"sw\">{sw}</td><td><b>{V.esc(name)}</b></td><td>{_md_inline(mean)}</td>{spec_cell}<td>{_md_inline(screen)}</td></tr>")
    head = "<th></th><th>상태</th><th>뜻</th>" + ("" if public else "<th>데이터에 넣는 법</th>") + "<th>화면</th>"
    return f'<table class="states"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def reference_html(public: bool = False, theme: str = "default") -> str:
    """사람이 보는 차트 레퍼런스 한 장 — 견본 차트 + 문서 §4의 조건·규칙 + §5 선택 순서(문서·코드에서만 만든다).
    public=True 는 외부 공개판: 에이전트용 이름·내부 명령을 뺀다."""
    rows, picks = doc_rows(), doc_selection()
    toc = "".join(f'<li><a href="#{cid}">{V.esc(c.name)}</a></li>' for cid, c in V.CATALOG.items())
    cards = []
    for cid, c in V.CATALOG.items():
        spec = dict(SAMPLES[cid], source="견본 · 가짜 값")                # 잘라 공유해도 실측으로 읽히지 않게
        fig, ch = V.render(spec, with_table=True)
        r = rows[cid]
        alts = " · ".join(f"{i + 2}위 {V.esc(x['name'])}" + (f"({V.esc(x['reasons'][-1])})" if x["reasons"] else "") for i, x in enumerate(ch.ranked[1:3]))
        alt_html = f'<p class="ex">같은 데이터로 쓸 수 있는 다른 차트 · {alts}</p>' if alts else ""
        hint_html = "" if public or not ch.hints else f'<p class="ex">데이터에서 읽은 것 · {V.esc(" · ".join(ch.hints))}</p>'
        swipe = '<p class="swipe">← 차트를 옆으로 밀어 보세요</p>' if cid not in ("kpi", "table", "edge_table") else ""
        cards.append(f'<section class="card" id="{cid}"><h3>{V.esc(c.name)} <span class="en">{V.esc(r["en"])}</span></h3>'
                     f'<p class="q">{V.esc(c.question)}</p><p class="ex">쓰임 예 · {_md_inline(r["examples"], public)}</p>{alt_html}{hint_html}{swipe}{fig}'
                     f'<div class="spec"><div><b>쓰는 조건</b>{_md_inline(r["cond"], public)}</div><div><b>그리는 규칙</b>{_md_inline(r["rules"], public)}</div></div></section>')
    howto = ("python3 viz.py select <데이터.json>            # 데이터 모양 → 쓸 수 있는 차트와 이유\n"
             "python3 viz.py render <데이터.json> --chart <id>  # 고른 차트로 그리기(조건을 못 채우면 멈춤)\n"
             "python3 viz.py check <보고서.html>               # 차트에 단위·기간이 있는지, 목록 밖 차트가 없는지")
    names = "".join(f"<tr><td>{V.esc(c.name)}</td><td>{V.esc(rows[cid]['en'])}</td><td><code>{cid}</code></td></tr>" for cid, c in V.CATALOG.items())
    agent = "" if public else (f"<details><summary>에이전트에서 쓰는 법</summary><pre>{V.esc(howto)}</pre>"
                               "<p class=\"sub\">에이전트가 차트를 지정할 때 쓰는 코드 이름(<code>--chart</code> 값)입니다.</p>"
                               f"<table class=\"names\"><tr><th>이름</th><th>영문 이름</th><th>코드 이름</th></tr>{names}</table></details>")
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>차트 레퍼런스</title><meta name=\"description\" content=\"리스닝마인드 데이터를 시각화하는 차트 레퍼런스\">"
            f"<style>{_ref_css(theme)}</style></head><body><main>"
            "<h1>차트 레퍼런스</h1>"
            "<p class=\"lead\">리스닝마인드 데이터를 시각화하는 차트 레퍼런스입니다.</p>"
            "<p class=\"sub\">데이터 모양에 맞는 차트를 고르는 기준, 차트마다 쓰는 조건과 그리는 규칙을 견본과 함께 모았습니다. 견본의 값은 모두 가짜입니다.</p>"
            f"<ul class=\"toc\">{toc}</ul>"
            "<h2>어떤 차트를 쓸까</h2>"
            "<p class=\"sub\">보여 줄 의도가 따로 없을 때 위에서부터 처음 맞는 줄을 따릅니다. 카드의 '쓰는 조건'은 그 차트를 쓸 수 있는 범위라서, 이 순서와 다를 수 있습니다.</p>"
            "<ol class=\"pick\">" + "".join(f"<li>{_md_inline(p, public)}</li>" for p in picks) + "</ol>"
            "<h2>값이 없는 칸은 어떻게 보이나</h2>"
            "<p class=\"sub\">리스닝마인드 데이터에는 0과 다른 '값 없음'이 여럿 있습니다. 차트마다 같은 모양으로 구분해 보여 줍니다.</p>"
            + _states_html(public) +
            "<h2>차트</h2>" + "".join(cards) + agent +
            "<footer>모든 차트는 외부 차트 도구 없이 페이지 안에 직접 그립니다. 단위·기간은 차트 아래 설명에 붙습니다.</footer>"
            "</main></body></html>")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("catalog"); c.add_argument("--json", action="store_true")
    s = sub.add_parser("select"); s.add_argument("spec"); s.add_argument("--intent", choices=sorted(V.INTENTS))
    r = sub.add_parser("render"); r.add_argument("spec"); r.add_argument("--chart"); r.add_argument("--intent", choices=sorted(V.INTENTS)); r.add_argument("--out")
    r.add_argument("--with-table", action="store_true", help="같은 데이터의 접힌 표를 차트 아래 붙인다")
    k = sub.add_parser("check"); k.add_argument("html", nargs="+")
    g = sub.add_parser("gallery"); g.add_argument("--out", required=True)
    au = sub.add_parser("auto", help="데이터 파일(csv·json) 하나로 프로파일 → 추천 상위 3 → 렌더 → 페이지까지 한 번에")
    au.add_argument("data"); au.add_argument("--title"); au.add_argument("--unit"); au.add_argument("--period"); au.add_argument("--source")
    au.add_argument("--intent", choices=sorted(V.INTENTS)); au.add_argument("--chart", help="추천 대신 지정(조건을 못 채우면 멈춤)")
    au.add_argument("--compare", action="store_true", help="상위 3개를 모두 그려 나란히"); au.add_argument("--public", action="store_true", help="코드 이름 없는 공개판")
    au.add_argument("--out", help="페이지 파일(기본: <데이터>.viz.html)"); au.add_argument("--json", action="store_true", help="결과 요약을 JSON 으로")
    au.add_argument("--theme", choices=sorted(V.THEMES), default="default", help="페이지 토큰 테마(executive = 경영진 보고 스타일 · 차트 선택은 그대로)")
    rf = sub.add_parser("reference"); rf.add_argument("--out", required=True); rf.add_argument("--public", action="store_true", help="외부 공개판(에이전트용 이름·명령 제외)")
    rf.add_argument("--theme", choices=sorted(V.THEMES), default="default")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "catalog":
            rows = [{"id": cid, "name": ch.name, "en": ch.en, "question": ch.question, "examples": ch.examples} for cid, ch in V.CATALOG.items()]
            print(json.dumps(rows, ensure_ascii=False, indent=1) if a.json else "\n".join(f"{x['id']:<17} {x['name']} ({x['en']}) — {x['question']}" for x in rows))
        elif a.cmd == "select":
            print(json.dumps(V.select(_load(a.spec), a.intent).as_dict(), ensure_ascii=False, indent=1))
        elif a.cmd == "render":
            fig, ch = V.render(_load(a.spec), a.chart, a.intent, with_table=a.with_table)
            if a.out:
                Path(a.out).write_text(fig, encoding="utf8")
                print(json.dumps({"out": a.out, "chart": ch.chart, "reason": ch.reason, "intent_note": ch.intent_note}, ensure_ascii=False))
            else:
                print(fig)
        elif a.cmd == "check":
            bad = False
            for p in a.html:
                res = V.check_html(Path(p).read_text(encoding="utf8"))
                print(json.dumps({"file": p, **res}, ensure_ascii=False, indent=1))
                bad |= res["verdict"] == "fail"
            return 11 if bad else 0
        elif a.cmd == "auto":
            spec = load_data(a.data)
            for k in ("title", "unit", "period", "source"):
                if getattr(a, k):
                    spec[k] = getattr(a, k)
            missing = [k for k in ("unit", "period") if not str(spec.get(k) or "").strip()]
            if missing:
                raise V.VizError(f"{'·'.join(missing)}이 없다 — --unit(예: 건/월) --period(예: 2025-09~2026-08)를 준다(차트마다 단위·기간)")
            choice = V.select(spec, a.intent)
            first = a.chart or choice.chart
            figs = [V.render(spec, a.chart, a.intent, with_table=True)[0]]        # 지정이 없으면 선택 이유를 그대로 싣는다
            if a.compare:
                for r in choice.ranked:
                    if r["chart"] != first:
                        figs.append(V.render(spec, r["chart"], a.intent, reason=" · ".join(r["reasons"]))[0])
            out = Path(a.out) if a.out else Path(a.data).with_suffix(".viz.html")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(auto_page(spec, figs, choice, a.public, a.theme), encoding="utf8")
            summary = {"out": str(out), "chart": first, "reason": choice.reason if first == choice.chart else "지정",
                       "ranked": choice.ranked, "hints": choice.hints, "intent_note": choice.intent_note}
            if a.json:
                print(json.dumps(summary, ensure_ascii=False, indent=1))
            else:
                print(f"{out}\n1위 {choice.ranked[0]['name']} — {choice.reason}")
                for r in choice.ranked[1:]:
                    print(f"   다른 선택: {r['name']} — {' · '.join(r['reasons'])}")
                for h in choice.hints:
                    print(f"   읽은 것: {h}")
        elif a.cmd in ("gallery", "reference"):
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            Path(a.out).write_text(gallery_html() if a.cmd == "gallery" else reference_html(a.public, a.theme), encoding="utf8")
            print(a.out)
    except V.VizError as e:
        print(f"viz: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
