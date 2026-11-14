"""The progress report page (feature 021 N3): one printable page. The browser's "Save as PDF" makes the file, so it
works the same locally and on the hosted demo with nothing installed. Every chart prints with its table open, every
measure carries its unit and meaning, and a section with nothing in it says so in one line."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Dict, List

from src.clinic import charts, shell
from src.clinic.assist_view import AI_TAG
from src.clinic.report import PERIODS
from src.ptlog import views


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def _table(headers: List[str], rows: List[List], right: tuple = ()) -> str:
    head = "".join(f'<th scope="col"{" class=\"r\"" if i in right else ""}>{_e(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td{" class=\"r\"" if i in right else ""}>{_e(c)}</td>' for i, c in enumerate(r))
                   + "</tr>" for r in rows)
    return f'<table class="table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _section(title: str, body: str) -> str:
    return f'<section class="sec report-sec"><h2>{_e(title)}</h2>{body}</section>'


def _empty(text: str) -> str:
    return f'<p class="dim">{_e(text)}</p>'


def _day(stamp: str) -> str:
    return datetime.fromisoformat(stamp[:19]).strftime("%-d %b")


# ----------------------------------------------------------------------------- sections

def plan(data: Dict[str, Any]) -> str:
    p = data["plan"]
    if p is None:
        return _section("Plan of care", _empty("No plan of care."))
    span = f"from {p.start_date[:10]}" + (f" to {p.end_date[:10]}" if p.end_date else ", ongoing")
    return _section("Plan of care", f'<p><span class="strong">{_e(p.title)}</span> · {_e(span)} · {_e(p.status)}</p>')


def program(data: Dict[str, Any]) -> str:
    a = data["assignment"]
    if a is None or not data["program"]:
        return _section("Program", _empty("No program assigned."))
    lead = f'<p>{_e(a.program_name)} · {a.sessions_per_week} sessions a week, from {_e(a.start_date)}</p>'
    return _section("Program", lead + _table(["Exercise", "Target reps per set"],
                                             [[p["name"], p["target_reps"]] for p in data["program"]], (1,)))


def trends(data: Dict[str, Any]) -> str:
    if not data["trends"]:
        return _section("Trends", _empty("No sessions in this period."))
    out = (f'<p class="small dim">{_e(views.metric_definition("avg_rom"))} '
           f'{_e(views.metric_definition("avg_form"))}</p>')
    for t in data["trends"]:
        labels = [_day(p.start_time) for p in t.points]
        rom = charts.line_chart(f'{t.exercise}: {views.metric_label("avg_rom")}',
                                list(zip(labels, [p.avg_rom for p in t.points])), unit="°",
                                goal=t.goal.target_rom if t.goal and t.goal.target_rom else None)
        form_c = charts.line_chart(f'{t.exercise}: {views.metric_label("avg_form")}',
                                   list(zip(labels, [p.avg_form for p in t.points])))
        rows = views.trend_table_rows(t)
        table = _table(["Date", views.metric_label("reps_completed"), views.metric_label("avg_form"),
                        views.metric_label("avg_rom"), "Recorded"],
                       [[r["date"], r["reps"], r["avg_form"], r["avg_rom"],
                         "at home" if r["origin"] == "home" else "in the clinic"] for r in rows], (1, 2, 3))
        summary = "".join(f'<p class="small">{_e(line)}</p>' for line in views.trend_summary_lines(t))
        out += (f'<div class="stack tight report-block"><h3>{_e(t.exercise)}</h3>'
                f'<div class="cols">{charts.render(rom, "Session")}{charts.render(form_c, "Session")}</div>'
                f'{table}'
                + f'<div class="stack tight">{summary}</div></div>')
    return _section("Trends", out)


def pain(data: Dict[str, Any]) -> str:
    series = data["pain"]
    if not series:
        return _section("Pain", _empty("No pain scores in this period."))
    chart = charts.line_chart("Pain at check-in, 0 to 10", [(_day(t), s) for t, s, _ in series])
    return _section("Pain", charts.render(chart, "When", open_table=True)
                    + '<p class="small dim">Pain: 0 is no pain and 10 the worst imaginable, as the patient scored it '
                    'at each check-in.</p>')


def goals(data: Dict[str, Any]) -> str:
    if not data["goals"]:
        return _section("Goals", _empty("No goals set."))
    rows = []
    for g in data["goals"]:
        goal = g["goal"]
        rows.append([goal.exercise_name,
                     f"{goal.target_rom:g}°" if goal.target_rom else "—",
                     f"{g['latest_rom']:.1f}°" if g["latest_rom"] is not None else "—",
                     f"{g['progress_pct']}%" if g["progress_pct"] is not None else "—",
                     goal.target_reps or "—", g["latest_reps"] if g["latest_reps"] is not None else "—"])
    return _section("Goals", _table(["Exercise", "Target range of motion", "Latest average range of motion",
                                     "Progress to the range goal", "Target reps", "Latest reps"], rows, (1, 2, 3, 4, 5))
                    + '<p class="small dim">Progress is the latest average range of motion as a share of the goal, '
                      'capped at 100%.</p>')


def adherence(data: Dict[str, Any]) -> str:
    adh = data["adherence"]
    if adh.assignment is None:
        return _section("Adherence", _empty("No program assigned, so no adherence."))
    rows = views.adherence_table_rows(adh)
    lead = (f"<p>{adh.percentage}% of planned sessions over the complete weeks.</p>" if adh.percentage is not None
            else "<p>Adherence is worked out after the first complete week.</p>")
    table = _table(["Week", "From", "To", "Sessions", "Status"],
                   [[r["week"], r["from"], r["to"], r["recorded"], r["status"]] for r in rows], (0, 3)) if rows else ""
    return _section("Adherence", lead + table + f'<p class="small dim">{_e(views.metric_definition("adherence_pct"))}</p>')


def questionnaires(groups: List[dict]) -> str:
    if not groups:
        return _section("Questionnaires", _empty("No questionnaires answered in this period."))
    out = ""
    for g in groups:
        chart = (charts.render(charts.line_chart(f"{g['name']} total, {g['unit']}",
                                                 [(_day(d), v) for d, v in g["series"]]), "Answered")
                 if len(g["series"]) >= 2 else "")
        table = _table(["When", "Total", "Missing answers"] + g["subscale_names"],
                       [[r["when"], r["total"], r["missing"]] + [v for _, v in r["subscales"]] for r in g["rows"]],
                       (1, 2))
        out += (f'<div class="stack tight report-block"><h3>{_e(g["name"])}</h3>'
                f'<p class="small dim">{_e(g["meaning"])} Score in {_e(g["unit"])}; {_e(g["direction"])}.</p>'
                + (f'<p>{_e(g["change"])}</p>' if g["change"] else "") + chart + table
                + (f'<p class="small dim">{_e(g["version_note"])}</p>' if g["version_note"] else "") + "</div>")
    return _section("Questionnaires", out)


def notes(data: Dict[str, Any]) -> str:
    if not data["notes"]:
        return _section("Notes", _empty("No saved notes in this period."))
    items = []
    for n in data["notes"]:
        when = datetime.fromisoformat(n["created_at"][:19]).strftime("%-d %b %Y")
        label = (f'<span class="ai-label">{AI_TAG}AI-drafted{", then edited" if n["edited"] else ""}, checked and '
                 f'saved by staff</span>' if n["ai_drafted"] else "")
        items.append(f'<li class="top"><div class="stack tight grow-col"><p class="rowflex"><span class="strong">'
                     f'{_e(when)} · {_e(n["author"])}</span>{label}</p><p class="pre">{_e(n["body"])}</p></div></li>')
    return _section("Notes", f'<ul class="lines">{"".join(items)}</ul>')


# ----------------------------------------------------------------------------- page

def content(data: Dict[str, Any]) -> str:
    pid = data["patient_id"]
    opts = "".join(f'<option value="{k}"{" selected" if k == data["period"] else ""}>{_e(label)}</option>'
                   for k, label, _ in PERIODS)
    controls = (f'<div class="rowflex no-print"><form class="rowflex top-row" method="get" '
                f'action="/therapist/review/{_e(pid)}/report"><label class="field w-day"><span>Period</span>'
                f'<select class="input" name="period" data-submit-on-change>{opts}</select></label>'
                '<button class="btn quiet small" type="submit">Show</button></form>'
                '<button class="btn" type="button" data-print>Print or save as PDF</button>'
                f'<a class="btn quiet small" href="/therapist/review/{_e(pid)}/trends">Back to Review</a></div>')
    span = f"since {data['since']}" if data["since"] else "all records"
    head = (f'<div class="page-head report-head"><div class="stack tight"><h1>Progress report · '
            f'<span class="code">{_e(pid)}</span></h1><p class="dim">{_e(data["period_label"])} ({_e(span)}) · '
            f'made {_e(data["generated"])} · Limber</p></div></div>')
    sections = (plan(data) + program(data) + trends(data) + pain(data) + goals(data) + adherence(data)
                + questionnaires(data["questionnaires"]) + notes(data))
    foot = ('<p class="small dim report-foot">Patients appear by code only. Measures come from Limber\'s session '
            'record; range of motion measured in the browser is shown apart from the clinic model\'s. '
            'This report leaves out what the patient wrote in their own words.</p>')
    return controls + head + f'<div class="stack loose">{sections}</div>' + foot


def page(account, classes: str, data: Dict[str, Any]) -> str:
    body = (shell.top_bar(account, "review")
            + f'<main class="page wide report" id="main">{content(data)}</main>')
    return shell.document(f"Progress report · {data['patient_id']}", body, (classes + " report-page").strip(),
                          scripts=("clinic.js",))
