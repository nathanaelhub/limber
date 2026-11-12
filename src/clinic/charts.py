"""Charts for the clinic app (feature 019, FR-011, FR-012): plain SVG drawn on the server, in the design's markup.

Every chart has a text description for screen readers and its numbers as a table, and a missing value is drawn
as a gap, never as zero. Text is sized by the stylesheet, so Larger text makes chart labels bigger too.

    figure = line_chart("Range of motion, degrees", [("14 Oct", 70), ("21 Oct", 78)], unit="°", goal=110)
    html = render(figure)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from html import escape
from typing import List, Optional, Sequence, Tuple

WIDTH, HEIGHT = 480, 170
LEFT, RIGHT, TOP, BOTTOM = 40, 460, 20, 140

Point = Tuple[str, Optional[float]]


@dataclass
class Chart:
    title: str
    kind: str                       # "line" or "bar"
    points: List[Point]
    svg: str
    description: str
    unit: str = ""
    goal: Optional[float] = None
    goal_label: str = "Goal"
    rows: List[Tuple[str, str]] = field(default_factory=list)


def _fmt(value: Optional[float], unit: str = "") -> str:
    if value is None:
        return "none"
    text = f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"
    return text + unit


def _scale(values: Sequence[float], goal: Optional[float], floor_zero: bool) -> Tuple[float, float]:
    present = [v for v in values if v is not None] + ([goal] if goal is not None else [])
    if not present:
        return 0.0, 1.0
    lo, hi = min(present), max(present)
    if floor_zero:
        lo = min(0.0, lo)
    if hi == lo:
        hi = lo + 1
    step = _nice_step((hi - lo) / 3)
    return math.floor(lo / step) * step, math.ceil(hi / step) * step


def _nice_step(raw: float) -> float:
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * magnitude:
            return m * magnitude
    return 10 * magnitude


def _y(value: float, lo: float, hi: float) -> float:
    return round(BOTTOM - (value - lo) / (hi - lo) * (BOTTOM - TOP), 1)


def _x(i: int, n: int) -> float:
    if n == 1:
        return (LEFT + RIGHT) / 2
    pad = (RIGHT - LEFT) / (n * 2)
    return round(LEFT + pad + i * (RIGHT - LEFT - 2 * pad) / (n - 1), 1)


def _frame(lo: float, hi: float, unit: str) -> List[str]:
    ticks = [lo + (hi - lo) * k / 3 for k in range(4)]
    grid = "".join(f"M{LEFT} {_y(t, lo, hi)}H{RIGHT}" for t in ticks[1:])
    parts = [f'<path class="grid" d="{grid}"/>', f'<path class="axis" d="M{LEFT} {BOTTOM}H{RIGHT}"/>']
    parts += [f'<text x="{LEFT - 8}" y="{_y(t, lo, hi) + 4}" text-anchor="end">{escape(_fmt(t, unit))}</text>'
              for t in ticks]
    return parts


def _goal(goal: Optional[float], label: str, lo: float, hi: float, unit: str) -> List[str]:
    if goal is None:
        return []
    y = _y(goal, lo, hi)
    return [f'<path class="goal" d="M{LEFT} {y}H{RIGHT}"/>',
            f'<text x="{RIGHT - 4}" y="{y - 6}" text-anchor="end">{escape(label)} {escape(_fmt(goal, unit))}</text>']


def _svg(parts: List[str], description: str) -> str:
    return (f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(description)}">'
            + "".join(parts) + "</svg>")


def _describe(kind: str, title: str, points: List[Point], unit: str, goal: Optional[float], goal_label: str) -> str:
    present = [(label, v) for label, v in points if v is not None]
    if not present:
        return f"{kind.capitalize()} chart of {title}. No values yet."
    text = (f"{kind.capitalize()} chart of {title}. "
            + ", ".join(f"{label}: {_fmt(v, unit)}" for label, v in points) + ".")
    if goal is not None:
        text += f" {goal_label} {_fmt(goal, unit)}."
    return text


def line_chart(title: str, points: Sequence[Point], unit: str = "", goal: Optional[float] = None,
               goal_label: str = "Goal") -> Chart:
    """A line through the values in order; a missing value breaks the line."""
    points = list(points)
    lo, hi = _scale([v for _, v in points], goal, floor_zero=False)
    parts = _frame(lo, hi, unit) + _goal(goal, goal_label, lo, hi, unit)
    runs, current = [], []
    for i, (_, v) in enumerate(points):
        if v is None:
            if current:
                runs.append(current)
            current = []
        else:
            current.append((_x(i, len(points)), _y(v, lo, hi)))
    if current:
        runs.append(current)
    for run in runs:
        if len(run) > 1:
            parts.append('<path class="s1" d="M' + " ".join(f"{x} {y}" for x, y in run) + '"/>')
    parts += [f'<circle class="pt" cx="{x}" cy="{y}" r="4"/>' for run in runs for x, y in run]
    parts += [f'<text x="{_x(i, len(points))}" y="162" text-anchor="middle">{escape(label)}</text>'
              for i, (label, _) in enumerate(points)]
    description = _describe("line", title, points, unit, goal, goal_label)
    return Chart(title, "line", points, _svg(parts, description), description, unit, goal, goal_label,
                 _rows(points, unit, goal, goal_label))


def bar_chart(title: str, points: Sequence[Point], unit: str = "", goal: Optional[float] = None,
              goal_label: str = "Goal", low_below: Optional[float] = None) -> Chart:
    """One bar per value from zero, each labelled with its number; a missing value says "none"."""
    points = list(points)
    lo, hi = _scale([v for _, v in points], goal, floor_zero=True)
    parts = _frame(lo, hi, unit) + _goal(goal, goal_label, lo, hi, unit)
    n = max(1, len(points))
    width = min(30.0, round((RIGHT - LEFT) / n * 0.6, 1))
    for i, (label, v) in enumerate(points):
        cx = _x(i, n)
        if v is None:
            parts.append(f'<text x="{cx}" y="{BOTTOM - 6}" text-anchor="middle">none</text>')
            continue
        top, base = _y(max(v, lo), lo, hi), _y(max(lo, 0.0), lo, hi)
        low = " low" if low_below is not None and v < low_below else ""
        parts.append(f'<rect class="bar{low}" x="{round(cx - width / 2, 1)}" y="{min(top, base)}" '
                     f'width="{width}" height="{round(abs(base - top), 1)}"/>')
        parts.append(f'<text x="{cx}" y="{min(top, base) - 6}" text-anchor="middle">{escape(_fmt(v, unit))}</text>')
    parts += [f'<text x="{_x(i, n)}" y="162" text-anchor="middle">{escape(label)}</text>'
              for i, (label, _) in enumerate(points)]
    description = _describe("bar", title, points, unit, goal, goal_label)
    return Chart(title, "bar", points, _svg(parts, description), description, unit, goal, goal_label,
                 _rows(points, unit, goal, goal_label))


def _rows(points: List[Point], unit: str, goal: Optional[float], goal_label: str) -> List[Tuple[str, str]]:
    rows = [(label, _fmt(v, unit)) for label, v in points]
    if goal is not None:
        rows.append((goal_label, _fmt(goal, unit)))
    return rows


def render(chart: Chart, first_column: str = "Session", open_table: bool = False) -> str:
    """The figure: its title, the drawing, and the same numbers as a table."""
    body = "".join(f'<tr><td>{escape(a)}</td><td class="r">{escape(b)}</td></tr>' for a, b in chart.rows)
    return (f'<figure class="chart"><h3>{escape(chart.title)}</h3>{chart.svg}'
            f'<details class="astable"{" open" if open_table else ""}><summary>Show as table</summary>'
            f'<table class="table"><thead><tr><th scope="col">{escape(first_column)}</th>'
            f'<th scope="col" class="r">{escape(chart.title)}</th></tr></thead><tbody>{body}</tbody></table>'
            f'</details></figure>')
