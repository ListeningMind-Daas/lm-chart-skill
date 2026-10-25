"""차트 팔레트 검사 — 눈으로 고르지 않고 계산한다 (API 호출 없음).

범주(계열) 팔레트가 다음 다섯 가지를 지키는지 잰다. 기준값은 Anthropic `dataviz` 스킬의 검증기(validate_palette)와 같게 두었고,
계산은 공개 공식으로 직접 구현했다(OKLab — Björn Ottosson 2020 · 색각 이상 시뮬레이션 — Machado·Oliveira·Fernandes 2009 심각도 1.0 ·
대비 — WCAG 2 상대 휘도).
  1. 명도 범위    OKLCH L 이 모드별 범위 안(라이트 0.43~0.77 · 다크 0.48~0.67)
  2. 채도 하한    OKLCH C ≥ 0.10 (아래면 회색으로 읽힌다)
  3. 색각 분리    이웃 슬롯끼리 protan·deutan 시뮬레이션 뒤 OKLab ΔE×100 ≥ 8 (6~8 은 직접 라벨·틈 같은 보조 인코딩이 있을 때만)
  4. 정상 시각    이웃 슬롯끼리 시뮬레이션 없이 ΔE×100 ≥ 15
  5. 바탕 대비    바탕색 대비 WCAG 3:1 이상
회색('기타' 전용)은 계열 슬롯이 아니므로 검사 대상에서 뺀다.
"""
from __future__ import annotations

import math

BAND = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}
CHROMA_FLOOR = 0.10
CVD_TARGET, CVD_FLOOR = 8.0, 6.0
NORMAL_FLOOR = 15.0
CONTRAST_MIN = 3.0
DIM_CONTRAST_MIN = 1.4                                  # 강조 바깥 회색: 읽히되 물러나야 한다(우리 기준 · 인쇄·투사는 사람이 확인)
DEFAULT_SURFACE = {"light": "#ffffff", "dark": "#161a22"}   # 우리 차트가 놓이는 패널색(viz.SURFACE 와 같은 값) — Anthropic 검증기 기본값(#fcfcfb·#1a1a19)과 다르다

MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def hex2rgb(h: str) -> tuple:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        raise ValueError(f"색 코드가 아님: {h!r}")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb2hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _cbrt(x: float) -> float:
    return math.copysign(abs(x) ** (1 / 3), x)


def srgb_to_oklab(rgb) -> tuple:
    r, g, b = (_lin(c) for c in rgb)
    return _lin_to_oklab((r, g, b))


def _lin_to_oklab(lin) -> tuple:
    r, g, b = lin
    l = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def oklab_to_srgb(lab) -> tuple:
    L, a, b = lab
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (_gam(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            _gam(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            _gam(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s))


def oklch(hex_: str) -> tuple:
    L, a, b = srgb_to_oklab(hex2rgb(hex_))
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def cvd(hex_: str, kind: str) -> tuple:
    """색각 이상 시뮬레이션 — 선형 RGB 에 Machado 행렬을 곱한 뒤 OKLab"""
    lin = [_lin(c) for c in hex2rgb(hex_)]
    M = MACHADO[kind]
    sim = [sum(M[i][j] * lin[j] for j in range(3)) for i in range(3)]
    return _lin_to_oklab(tuple(max(0.0, min(1.0, c)) for c in sim))


def delta_e(lab1, lab2) -> float:
    return 100 * math.dist(lab1, lab2)


def luminance(hex_: str) -> float:
    r, g, b = (_lin(c) for c in hex2rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(c1: str, c2: str) -> float:
    a, b = sorted((luminance(c1), luminance(c2)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def validate(palette: list, mode: str, surface: str, pairs: str = "adjacent") -> dict:
    """{ok, findings[(이름, 통과, 설명)]} — 이웃 쌍 기준(산점도·버블·지도처럼 모든 색이 맞닿으면 pairs='all')"""
    lo, hi = BAND[mode]
    f = []
    off = [(c, round(oklch(c)[0], 3)) for c in palette if not lo <= oklch(c)[0] <= hi]
    f.append(("명도 범위", not off, f"{len(palette)}색 모두 L {lo}~{hi} 안" if not off else f"범위 밖: {off}"))
    gray = [(c, round(oklch(c)[1], 3)) for c in palette if oklch(c)[1] < CHROMA_FLOOR]
    f.append(("채도 하한", not gray, "모두 ≥ 0.10" if not gray else f"회색으로 읽힘: {gray}"))
    idx = [(i, i + 1) for i in range(len(palette) - 1)] if pairs == "adjacent" else \
          [(i, j) for i in range(len(palette)) for j in range(i + 1, len(palette))]
    worst_cvd, worst_norm, warn = (None, 99.0), (None, 99.0), []
    for i, j in idx:
        d = min(delta_e(cvd(palette[i], k), cvd(palette[j], k)) for k in ("protan", "deutan"))
        n = delta_e(srgb_to_oklab(hex2rgb(palette[i])), srgb_to_oklab(hex2rgb(palette[j])))
        if d < worst_cvd[1]:
            worst_cvd = ((palette[i], palette[j]), d)
        if n < worst_norm[1]:
            worst_norm = ((palette[i], palette[j]), n)
        if CVD_FLOOR <= d < CVD_TARGET:
            warn.append((palette[i], palette[j], round(d, 1)))
    cvd_ok = worst_cvd[1] >= CVD_FLOOR if idx else True
    f.append(("색각 분리", cvd_ok, f"가장 가까운 이웃 {worst_cvd[0]} ΔE {worst_cvd[1]:.1f}" + (f" · 6~8 경계(보조 인코딩 필요): {warn}" if warn else "")))
    f.append(("정상 시각", worst_norm[1] >= NORMAL_FLOOR if idx else True, f"가장 가까운 이웃 {worst_norm[0]} ΔE {worst_norm[1]:.1f}"))
    low = [(c, round(contrast(c, surface), 2)) for c in palette if contrast(c, surface) < CONTRAST_MIN]
    f.append(("바탕 대비", not low, f"모두 ≥ {CONTRAST_MIN}:1 (바탕 {surface})" if not low else f"3:1 미만: {low}"))
    return {"ok": all(ok for _, ok, _ in f), "findings": f, "warn_cvd": warn}


def restep(hex_: str, target_L: float) -> str:
    """같은 색상(a·b 방향)을 유지한 채 OKLab 명도만 target_L 로 옮겨 sRGB 안에 들어오게 채도를 줄인다"""
    L, a, b = srgb_to_oklab(hex2rgb(hex_))
    scale = 1.0
    while scale > 0.05:
        rgb = oklab_to_srgb((target_L, a * scale, b * scale))
        back = srgb_to_oklab(rgb)
        if abs(back[0] - target_L) < 0.01 and math.hypot(back[1] - a * scale, back[2] - b * scale) < 0.01:
            return rgb2hex(rgb)
        scale -= 0.05
    return rgb2hex(oklab_to_srgb((target_L, a * scale, b * scale)))


def report(palette: list, mode: str, surface: str, pairs: str = "adjacent") -> str:
    r = validate(palette, mode, surface, pairs)
    lines = [f"팔레트({mode} · 바탕 {surface} · {len(palette)}색)"] + [f"  [{'통과' if ok else '실패'}] {n:6} {d}" for n, ok, d in r["findings"]]
    return "\n".join(lines + ["  → " + ("모두 통과" if r["ok"] else "실패한 항목을 고친다")])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("palette", help='"#hex,#hex,…"')
    ap.add_argument("--mode", choices=["light", "dark"], default="light")
    ap.add_argument("--surface", default=None)
    ap.add_argument("--pairs", choices=["adjacent", "all"], default="adjacent")
    a = ap.parse_args()
    pal = [c.strip() for c in a.palette.split(",") if c.strip()]
    surf = a.surface or DEFAULT_SURFACE[a.mode]
    print(report(pal, a.mode, surf, a.pairs))
    raise SystemExit(0 if validate(pal, a.mode, surf, a.pairs)["ok"] else 1)
