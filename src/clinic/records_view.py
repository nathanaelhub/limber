"""The Dashboard, Sessions and Observation logs pages (feature 019 slice 5a), from the design export. Every
measure says its unit and what it means (FR-011); every chart has its numbers as a table (FR-010)."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import List, Optional

from src.clinic import charts, inbox as inbox_rules, shell
from src.clinic.inbox_view import NEW_ITEMS
from src.clinic.records import EXPORTS, PERIODS
from src.ptlog import views

FORM_DEF = "Form score runs from 0 to 100; higher is better. " + views.metric_definition("form_score")
ROM_DEF = "Range of motion is in degrees. " + views.metric_definition("rom")


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def _num(value, unit: str = "") -> str:
    return "Not measured" if value is None else f"{value:g}{unit}"


def _fact(label: str, value: str, detail: str = "", href: str = "") -> str:
    link = f'<a class="small" href="{_e(href)}">{_e(detail)}</a>' if href else f'<span class="small dim">{_e(detail)}</span>'
    return f'<div class="fact"><span class="lbl">{_e(label)}</span><span class="val">{value}</span>{link}</div>'


def dashboard(name: str, today: str, needs: List[inbox_rules.Item], visits: List[dict], attention: List,
              act: dict, days: int, recent: List[dict]) -> str:
    head = (f'<div class="page-head"><div class="stack tight"><h1>Dashboard</h1><p class="dim">{_e(today)} · '
            f'signed in as {_e(name)}</p></div></div>' + NEW_ITEMS)
    facts = ('<div class="facts">'
             + _fact("Needs you", f'{len(needs)}', "Open the Inbox", "/therapist/inbox")
             + _fact("Visits today", f'{len(visits)}', "Open the Schedule", "/therapist/schedule")
             + _fact("Patients to look at", f'{len(attention)}', "Open Patients", "/therapist/patients") + "</div>")
    need_items = "".join(
        f'<li><span class="code">{_e(i.patient_id)}</span><span class="tag {"urgent" if i.kind == "urgent" else "ghost" if i.kind == "reschedule" else "new"}">'
        f'{"Urgent" if i.kind == "urgent" else "Reschedule" if i.kind == "reschedule" else f"{i.unread} new"}</span>'
        f'<span class="grow-col ellipsis">{_e(i.plan_title)} · {_e(i.line)}</span>'
        f'<a class="sp" href="{_e(i.href)}">Open</a></li>' for i in needs[:5])
    need_html = (f'<ul class="lines">{need_items}</ul>' if need_items else '<p class="dim">Nothing needs you right now.</p>')
    visit_items = "".join(
        f'<li><span class="strong num w-time-col">{_e(v["time"])}</span><a class="code" href="/therapist/patients/'
        f'{_e(v["patient_id"])}">{_e(v["patient_id"])}</a><span class="grow-col">{_e(v["plan"])} · {v["minutes"]} minutes'
        + (f' · {_e(v["note"])}' if v["note"] else "") + "</span>"
        + ('<span class="tag ghost">Reschedule asked</span>' if v["reschedule_requested"] else "") + "</li>"
        for v in visits)
    visit_html = f'<ul class="lines">{visit_items}</ul>' if visit_items else '<p class="dim">No visits today.</p>'
    look_items = "".join(
        f'<li><a class="code" href="{_e(r.href)}">{_e(r.patient_id)}</a><span class="grow-col">{_e(r.title)}</span>'
        f'<span class="small strong warn-text">{_e(r.status)}</span></li>' for r in attention)
    look_html = f'<ul class="lines">{look_items}</ul>' if look_items else '<p class="dim">No patient needs a closer look.</p>'
    today_html = ('<div class="cols">'
                  + f'<section class="sec"><div class="sec-head"><h2>Needs you</h2><a class="sp" href="/therapist/inbox">Inbox</a></div>{need_html}</section>'
                  + f'<section class="sec"><div class="sec-head"><h2>Today\'s visits</h2><a class="sp" href="/therapist/schedule">Schedule</a></div>{visit_html}'
                  + f'<div class="sec-head pad-top-0"><h2>Patients to look at</h2></div>{look_html}</section></div>')
    options = "".join(f'<option value="{d}"{" selected" if d == days else ""}>{_e(t)}</option>' for d, t in PERIODS.items())
    picker = (f'<form class="rowflex sp" method="get" action="/therapist/dashboard"><label class="field inline-field">'
              f'<span>Period</span><select class="input" name="days" data-submit-on-change>{options}</select></label>'
              '<noscript><button class="btn quiet small" type="submit">Show</button></noscript></form>')
    sentence = (f'<p class="lede">In the {_e(PERIODS[days].lower())} your patients ran <b>{act["sessions"]} '
                f'session{"s" if act["sessions"] != 1 else ""}</b> with <b>{act["reps"]:,} reps</b>. Average form score '
                f'<b>{_num(act["form"])}</b> of 100; average range of motion <b>{_num(act["rom"], "°")}</b>.</p>'
                f'<p class="small dim">{_e(FORM_DEF)} {_e(ROM_DEF)}</p>')
    figs = ""
    if act["form_by_week"]:
        figs = ('<div class="cols">'
                + charts.render(charts.line_chart("Average form score by week, 0 to 100", act["form_by_week"]), "Week of")
                + charts.render(charts.line_chart("Average range of motion by week, degrees", act["rom_by_week"], unit="°"),
                                "Week of") + "</div>")
    rec = "".join(
        f'<tr><td>{_e(r["when"])}</td><td><a class="code" href="/therapist/patients/{_e(r["patient_id"])}">'
        f'{_e(r["patient_id"])}</a></td><td>{_e(r["exercises"])}</td><td>{"At home" if r["origin"] == "home" else "Clinic"}</td>'
        f'<td class="r">{r["reps"]}</td><td class="r">{_num(r["form"] and round(r["form"]))}</td>'
        f'<td><a href="/therapist/logs/{r["id"]}">Log</a></td></tr>' for r in recent)
    rec_html = (('<div class="scroll" tabindex="0" role="region" aria-label="Table, scrolls sideways when wide"><table class="table"><thead><tr><th scope="col">When</th><th scope="col">Patient</th>'
                 '<th scope="col">Exercise</th><th scope="col">Where</th><th scope="col" class="r">Reps</th>'
                 '<th scope="col" class="r">Form score, 0 to 100</th><th scope="col"><span class="vh">Open</span></th>'
                 f'</tr></thead><tbody>{rec}</tbody></table></div>') if rec else
                '<p class="dim">No sessions recorded yet. They appear here once a patient or therapist records one.</p>')
    return (head + facts + today_html
            + f'<section class="sec"><div class="sec-head"><h2>Activity</h2>{picker}</div>{sentence}{figs}</section>'
            + f'<section class="sec"><div class="sec-head"><h2>Recent sessions</h2><a class="sp" href="/therapist/sessions">'
              f'All sessions</a></div>{rec_html}</section>')


def _patient_filter(action: str, patients: List[str], chosen: Optional[str]) -> str:
    options = '<option value="">All patients</option>' + "".join(
        f'<option value="{_e(p)}"{" selected" if p == chosen else ""}>{_e(p)}</option>' for p in patients)
    return (f'<form class="rowflex" method="get" action="{_e(action)}"><label class="field inline-field"><span>Patient</span>'
            f'<select class="input" name="patient" data-submit-on-change>{options}</select></label>'
            '<noscript><button class="btn quiet small" type="submit">Show</button></noscript></form>')


def sessions(rows: List[dict], patients: List[str], chosen: Optional[str]) -> str:
    body = "".join(
        f'<tr><td>{_e(r["when"])}</td><td><a class="code" href="/therapist/patients/{_e(r["patient_id"])}">'
        f'{_e(r["patient_id"])}</a></td><td>{_e(r["exercises"])}</td><td>{_e(r["kind"])}, {_e(r["where"])}</td>'
        f'<td class="r">{r["reps"]}</td><td class="r">{_num(r["form"] and round(r["form"]))}</td>'
        f'<td>{"" if r["status"] == "completed" else _e(r["status"].capitalize())}</td>'
        f'<td><a href="/therapist/sessions/{r["id"]}">Open</a> · <a href="/therapist/logs/{r["id"]}">Log</a></td></tr>'
        for r in rows)
    table = (('<div class="scroll" tabindex="0" role="region" aria-label="Table, scrolls sideways when wide"><table class="table"><thead><tr><th scope="col">When</th><th scope="col">Patient</th>'
              '<th scope="col">Exercise</th><th scope="col">Type</th><th scope="col" class="r">Reps</th>'
              '<th scope="col" class="r">Form score, 0 to 100</th><th scope="col">Status</th>'
              f'<th scope="col"><span class="vh">Open</span></th></tr></thead><tbody>{body}</tbody></table></div>')
             if rows else '<p class="dim">No sessions recorded yet for this selection.</p>')
    return (f'<div class="page-head"><div class="stack tight"><h1>Sessions</h1><p class="dim">{len(rows)} session'
            f'{"s" if len(rows) != 1 else ""}{" for " + _e(chosen) if chosen else ""}, newest first</p></div></div>'
            + _patient_filter("/therapist/sessions", patients, chosen) + table
            + f'<p class="small dim">{_e(FORM_DEF)}</p>')


def session_detail(session, header: List[str], lines: List[str]) -> str:
    warn = ('<div class="notice" role="alert"><div class="stack tight"><h3>This session was interrupted</h3><p>The '
            'summary is worked out from the events recorded before the interruption.</p></div></div>'
            if session.status == "interrupted" else "")
    defs = "".join(f'<dt>{_e(views.metric_label(f))}</dt><dd>{_e(views.metric_definition(f))}</dd>'
                   for f in ("rom", "form_score", "duration_seconds", "avg_form_score", "avg_rom"))
    downloads = "".join(f'<a class="btn quiet small" href="/therapist/sessions/{session.id}/export/{fmt}" download>'
                        f'{_e(label)}</a>' for fmt, (_, _, label) in EXPORTS.items())
    return (f'<div class="page-head"><div class="stack tight"><h1>Session {session.id} · '
            f'<a class="code" href="/therapist/patients/{_e(session.patient_id)}">{_e(session.patient_id)}</a></h1>'
            + "".join(f'<p class="dim">{_e(h)}</p>' for h in header[:-1]) + '</div>'
            f'<a class="btn quiet small sp" href="/therapist/logs/{session.id}">Charts and reps</a></div>{warn}'
            f'<section class="sec"><h2>Event log</h2><pre class="log">{_e(chr(10).join(lines))}</pre></section>'
            f'<section class="sec"><h2>Export</h2><div class="rowflex">{downloads}</div></section>'
            f'<details class="edit"><summary class="small strong">What the measures mean</summary><dl class="kv">{defs}</dl></details>')


def log_side(rows: List[dict], current: Optional[int], patients: List[str], chosen: Optional[str]) -> str:
    items = "".join(
        f'<a class="row" href="/therapist/logs/{r["id"]}{"?patient=" + _e(chosen) if chosen else ""}"'
        f'{" aria-current=\"true\"" if r["id"] == current else ""}><span></span><span><span class="l1"><span class="code">'
        f'{_e(r["patient_id"])}</span><span class="small ellipsis">{_e(r["exercises"])}</span></span><span class="l2">'
        f'{_e(r["when"])} · {r["reps"]} reps</span></span></a>' for r in rows)
    return (f'<nav class="side" aria-label="Observation sessions"><div class="side-head"><h2>Observation logs</h2></div>'
            f'<div class="pad-x pad-bottom">{_patient_filter("/therapist/logs", patients, chosen)}</div>'
            + (items or '<p class="small dim pad-x">No sessions recorded yet.</p>') + "</nav>")


def log_pane(log: Optional[dict]) -> str:
    if log is None:
        return ('<main class="pane" id="main"><div class="empty"><h2>Pick a session</h2><p>Each session\'s reps, charts '
                'and events, worked out from the record.</p></div></main>')
    s, data, summary, reps = log["session"], log["data"], log["summary"], log["reps"]
    when = datetime.fromisoformat(s.start_time[:19]).strftime("%a %-d %b %Y, %H:%M")
    duration = data.get("duration_seconds")
    kind = "Video analysis" if s.source == "video" else "Live session"
    target = log["target"]
    facts = ('<div class="facts">'
             + _fact("Reps completed", f'{summary["total_reps"]}' + (f' <small>of {target}</small>' if target else ""),
                     f'{log["completion"]}% of the target' if log["completion"] is not None else "")
             + _fact("Average form score", f'{_num(summary["avg_form_score"])}<small> of 100</small>', "Higher is better")
             + _fact("Average range of motion", _num(summary["avg_rom"], "°"), "Degrees")
             + _fact("Events", f'{len(data["events"])}', "Every step the engine recorded") + "</div>")
    warnings = "".join(f'<li><span class="tag urgent">Note</span><span>{_e(w)}</span></li>' for w in summary["warnings"])
    parts = [facts]
    if warnings:
        parts.append(f'<section class="sec"><h2>Warnings</h2><ul class="lines">{warnings}</ul></section>')
    if reps:
        labels = [str(e["rep_number"]) for e in reps]
        figs = [charts.bar_chart("Form score per rep, 0 to 100", list(zip(labels, [e["form_score"] for e in reps])),
                                 low_below=60),
                charts.bar_chart("Range of motion per rep, degrees", list(zip(labels, [e["rom"] for e in reps])), unit="°"),
                charts.line_chart("Rep duration, seconds", list(zip(labels, [e["duration_seconds"] for e in reps])),
                                  unit=" s")]
        parts.append('<section class="sec"><div class="sec-head"><h2>Charts</h2><span class="small dim">A bar below 60 '
                     'is marked as needing attention.</span></div><div class="cols">'
                     + "".join(charts.render(f, "Rep") for f in figs) + "</div></section>")
        rows = "".join(f'<tr><td class="r">{e["rep_number"]}</td><td>{_e(e["exercise"])}</td><td class="r">{e["min_angle"]}</td>'
                       f'<td class="r">{e["max_angle"]}</td><td class="r">{e["rom"]}</td><td class="r">{e["duration_seconds"]}</td>'
                       f'<td class="r{" warn-text strong" if e["form_score"] < 60 else ""}">{e["form_score"]}</td></tr>'
                       for e in reps)
        parts.append('<section class="sec"><div class="sec-head"><h2>Rep by rep</h2>'
                     f'<a class="btn quiet small sp" href="/therapist/logs/{s.id}/reps.csv" download>Download reps (CSV)</a>'
                     '</div><div class="scroll" tabindex="0" role="region" aria-label="Table, scrolls sideways when wide"><table class="table"><thead><tr><th scope="col" class="r">Rep</th>'
                     '<th scope="col">Exercise</th><th scope="col" class="r">Smallest angle, °</th><th scope="col" class="r">'
                     'Largest angle, °</th><th scope="col" class="r">Range of motion, °</th><th scope="col" class="r">'
                     'Duration, s</th><th scope="col" class="r">Form score, 0 to 100</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></div><p class="small dim">{_e(FORM_DEF)} {_e(ROM_DEF)}</p></section>')
    else:
        parts.append('<p class="dim">No reps were recorded in this session.</p>')
    performed = summary.get("exercises_performed") or []
    if len(performed) > 1:
        rows = "".join(f'<tr><td>{_e(x["exercise"])}</td><td class="r">{x["reps"]}</td><td class="r">{x["avg_form_score"]}</td>'
                       f'<td class="r">{x["avg_rom"]}</td></tr>' for x in performed)
        parts.append('<section class="sec"><h2>By exercise</h2><div class="scroll" tabindex="0" role="region" aria-label="Table, scrolls sideways when wide"><table class="table"><thead><tr>'
                     '<th scope="col">Exercise</th><th scope="col" class="r">Reps</th><th scope="col" class="r">Average form, '
                     '0 to 100</th><th scope="col" class="r">Average range of motion, °</th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></div></section>')
    timeline = "".join(f'<li><span class="num dim w-time-col">{_e(t)}</span><span class="strong">{_e(label)}</span>'
                       f'<span class="grow-col">{_e(detail)}</span></li>' for t, label, detail in log["timeline"])
    parts.append(f'<details class="edit"><summary class="btn quiet small">Event timeline ({len(log["timeline"])})</summary>'
                 f'<ul class="lines">{timeline}</ul></details>')
    parts.append(f'<p><a class="btn quiet small" href="/therapist/logs/{s.id}/log.json" download>Download the full log (JSON)</a></p>')
    return (f'<main class="pane" id="main"><div class="pane-head ruled"><div class="stack tight"><h1>{_e(s.patient_id)} · '
            f'{_e(data.get("initial_exercise") or "Session")}</h1><p class="dim">{_e(kind)} · {_e(when)}'
            + (f' · {duration:g} s' if duration else "") + '</p></div>'
            f'<a class="btn quiet small sp" href="/therapist/sessions/{s.id}">Event log and exports</a></div>'
            f'<div class="pane-body roomy">{"".join(parts)}</div></main>')


def page(account, classes: str, active: str, title: str, content: str, split: bool = False) -> str:
    inner = f'<div class="split">{content}</div>' if split else f'<main class="page wide" id="main">{content}</main>'
    return shell.document(title, shell.top_bar(account, active) + inner, classes, scripts=("clinic.js",))
