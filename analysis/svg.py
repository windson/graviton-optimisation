"""Small helpers for writing the report's charts as SVG by hand.

The charts are plain SVG text with no script: they stay sharp at any size, and their
numbers remain selectable text. Styling uses classes prefixed with `gu-`, so that the
styles of several charts shown in one page cannot clash.
"""
from __future__ import annotations

import html
import math

# One colour per configuration, used in every chart.
COLORS = {
    "A": "#5b6770",  # Graviton2 baseline: slate
    "B": "#2a78d6",  # Graviton5, same size: blue
    "C": "#0d7a6e",  # Graviton5, right-sized: teal
}
INK = "#1c1f23"
MUTED = "#5d6673"
GRID = "#e6e8eb"
FONT = "system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"

STYLE = (
    f".gu-fig text{{font-family:{FONT};fill:{INK};font-size:13px}}"
    f".gu-fig .gu-title{{font-size:16px;font-weight:600}}"
    f".gu-fig .gu-sub{{fill:{MUTED};font-size:12.5px}}"
    f".gu-fig .gu-tick{{fill:{MUTED};font-size:12px;font-variant-numeric:tabular-nums}}"
    f".gu-fig .gu-axis{{fill:{MUTED};font-size:12px}}"
    f".gu-fig .gu-val{{font-size:12.5px;font-variant-numeric:tabular-nums}}"
    f".gu-fig .gu-note{{fill:{MUTED};font-size:11.5px}}"
    f".gu-fig .gu-grid{{stroke:{GRID};stroke-width:1}}"
    f".gu-fig .gu-base{{stroke:{MUTED};stroke-width:1}}"
)


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def fmt(value: float, digits: int = 1) -> str:
    """Formats a number with thousands separators and no trailing '.0'."""
    text = f"{value:,.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


class Linear:
    def __init__(self, lo: float, hi: float, a: float, b: float) -> None:
        self.lo, self.hi, self.a, self.b = lo, hi, a, b

    def __call__(self, value: float) -> float:
        return self.a + (value - self.lo) / (self.hi - self.lo) * (self.b - self.a)


class Log:
    def __init__(self, lo: float, hi: float, a: float, b: float) -> None:
        self.lo, self.hi, self.a, self.b = math.log10(lo), math.log10(hi), a, b

    def __call__(self, value: float) -> float:
        value = max(value, 10 ** self.lo)
        return self.a + (math.log10(value) - self.lo) / (self.hi - self.lo) * (self.b - self.a)


def nice_ticks(lo: float, hi: float, count: int = 5) -> list[float]:
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / count))
    for multiple in (1, 2, 2.5, 5, 10):
        if span / (step * multiple) <= count:
            step *= multiple
            break
    first = math.ceil(lo / step) * step
    ticks = []
    value = first
    while value <= hi + 1e-9:
        ticks.append(round(value, 10))
        value += step
    return ticks


class Figure:
    def __init__(self, width: int, height: int, title: str, subtitle: str, description: str, ident: str) -> None:
        self.width, self.height, self.ident = width, height, ident
        self.parts: list[str] = [
            f'<title id="{ident}-t">{esc(title)}</title>',
            f'<desc id="{ident}-d">{esc(description)}</desc>',
            f'<text class="gu-title" x="0" y="18">{esc(title)}</text>',
            f'<text class="gu-sub" x="0" y="37">{esc(subtitle)}</text>',
        ]

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def text(self, x: float, y: float, text: object, cls: str = "", anchor: str = "start", fill: str | None = None,
             weight: str | None = None) -> None:
        attrs = f' class="{cls}"' if cls else ""
        if anchor != "start":
            attrs += f' text-anchor="{anchor}"'
        if fill:
            attrs += f' style="fill:{fill}"' if not weight else f' style="fill:{fill};font-weight:{weight}"'
        elif weight:
            attrs += f' style="font-weight:{weight}"'
        self.parts.append(f'<text x="{x:.1f}" y="{y:.1f}"{attrs}>{esc(text)}</text>')

    def line(self, x1: float, y1: float, x2: float, y2: float, cls: str = "gu-grid", style: str = "") -> None:
        extra = f' style="{style}"' if style else ""
        self.parts.append(f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"{extra}/>')

    def rect(self, x: float, y: float, w: float, h: float, fill: str, opacity: float = 1.0, rx: float = 2,
             cls: str = "") -> None:
        attrs = f' class="{cls}"' if cls else ""
        if opacity != 1.0:
            attrs += f' fill-opacity="{opacity}"'
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{max(h, 0):.1f}" rx="{rx}" fill="{fill}"{attrs}/>')

    def circle(self, x: float, y: float, r: float, fill: str, stroke: str = "#fff") -> None:
        self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')

    def path(self, points: list[tuple[float, float]], stroke: str, width: float = 2.25, dash: str = "",
             cls: str = "") -> None:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points))
        attrs = f' stroke-dasharray="{dash}"' if dash else ""
        if cls:
            attrs += f' class="{cls}"'
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round" '
            f'stroke-linecap="round"{attrs}/>')

    def render(self, extra_style: str = "") -> str:
        body = "\n".join(self.parts)
        # A white ground, so that the figure reads the same on a dark page.
        ground = '<rect width="100%" height="100%" fill="#ffffff"/>'
        return (
            f'<svg class="gu-fig" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'role="img" aria-labelledby="{self.ident}-t {self.ident}-d" '
            f'style="display:block;width:100%;height:auto;max-width:{self.width}px">\n'
            f"<style>{STYLE}{extra_style}</style>\n{ground}\n{body}\n</svg>\n"
        )
