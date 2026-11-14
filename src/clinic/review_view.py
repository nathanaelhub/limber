"""The Review page (feature 019 slice 5b): a patient's sessions over time, from the design export's Review screen.
Choices (period, exercise, sessions, scope) are plain GET forms; changes are forms.js JSON posts. Every measure has
its unit and meaning (FR-011) and every chart its table (FR-010)."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import List, Optional

from src.clinic import charts, shell
from src.clinic.patients_view import field, form, select
from src.clinic.review import SECTIONS, WHOLE_PATIENT
from src.ptlog import views
from src.ptlog.models import NEXT_STEPS, PERIODS

SCROLL = '<div class="scroll" tabindex="0" role="region" aria-label="Table, scrolls sideways when wide">'


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def _table(headers: List[str], rows: List[List], right: tuple = ()) -> str:
    head = "".join(f'<th scope="col"{" class=\"r\"" if i in right else ""}>{_e(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td{" class=\"r\"" if i in right else ""}>{_e(c)}</td>' for i, c in enumerate(r))
                   + "</tr>" for r in rows)
    return f'{SCROLL}<table class="table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _note(text: str, kind: str = "plain", title: str = "") -> str:
    head = f"<h3>{_e(title)}</h3>" if title else ""
    return f'<div class="notice {kind}"><div class="stack tight">{head}<p>{_e(text)}</p></div></div>'


def _choose(action: str, controls: str) -> str:
    """A GET form of choices that applies as soon as one changes (clinic.js), with a button for no-script use."""
    return (f'<form class="rowflex top-row" method="get" action="{_e(action)}">{controls}'
            '<button class="btn quiet small" type="submit">Show</button></form>')


def _get_select(label: str, name: str, options, chosen, cls: str = "w-day") -> str:
    opts = "".join(f'<option value="{_e(v)}"{" selected" if str(v) == str(chosen) else ""}>{_e(t)}</option>'
                   for v, t in options)
    return (f'<label class="field {cls}"><span>{_e(label)}</span><select class="input" name="{name}" '
            f'data-submit-on-change>{opts}</select></label>')


def _period(chosen: str) -> str:
    return _get_select("Period", "period", [(p, views.PERIOD_LABELS[p].capitalize()) for p in PERIODS], chosen)


# ----------------------------------------------------------------------------- frame

def picker(patients: List[str]) -> str:
    links = "".join(f'<a class="btn quiet small" href="/therapist/review/{_e(p)}/trends">{_e(p)}</a>' for p in patients)
    return ('<div class="page-head"><div class="stack tight"><h1>Review</h1><p class="dim">A patient\'s sessions over '
            'time: trends, flags, comparisons, reviews, what they reported, goals and exports.</p></div></div>'
            + (f'<div class="online-list">{links}</div>' if links else '<p class="dim">No patients on your caseload yet.</p>'))


def frame(pid: str, section: str, header: str, body: str) -> str:
    tabs = "".join(f'<a href="/therapist/review/{_e(pid)}/{key}"{" aria-current=\"page\"" if key == section else ""}>'
                   f'{_e(label)}</a>' for key, label in SECTIONS)
    return (f'<div class="page-head"><div class="stack tight"><h1>Review · <a class="code" href="/therapist/patients/'
            f'{_e(pid)}">{_e(pid)}</a></h1><p class="dim">{_e(header)}</p></div>'
            f'<div class="rowflex sp"><a class="btn quiet small" href="/therapist/review/{_e(pid)}/report">'
            'Progress report</a>'
            f'<a class="btn quiet small" href="/therapist/sessions?patient={_e(pid)}">Sessions</a></div></div>'
            f'<nav class="tabs" aria-label="Review sections">{tabs}</nav><div class="stack loose review-body">{body}</div>')


# ----------------------------------------------------------------------------- sections

def trends(pid: str, names: List[str], exercise: Optional[str], period: str, trend, logged: int) -> str:
    if not names:
        return f'<p class="dim">No sessions recorded for {_e(pid)} yet.</p>'
    picker_html = _choose(f"/therapist/review/{pid}/trends",
                          _get_select("Exercise", "exercise", [(n, n) for n in names], exercise, "w-wide") + _period(period))
    if not trend.points:
        extra = (f" The patient logged {logged} session(s) of it without the camera, which carry no range of motion "
                 "or form; they are under From the patient." if logged else "")
        return picker_html + f'<p class="dim">No measured sessions of {_e(exercise)} in this period.{_e(extra)}</p>'
    rows = views.trend_table_rows(trend)
    labels = [datetime.fromisoformat(p.start_time[:19]).strftime("%-d %b") for p in trend.points]
    rom = charts.line_chart(views.metric_label("avg_rom"), list(zip(labels, [p.avg_rom for p in trend.points])), unit="°")
    form_c = charts.line_chart(views.metric_label("avg_form"), list(zip(labels, [p.avg_form for p in trend.points])))
    table = _table(["Date", "Session", views.metric_label("reps_completed"), views.metric_label("avg_form"),
                    views.metric_label("avg_rom"), views.metric_label("avg_duration"), views.metric_label("tempo_sd"),
                    views.metric_label("partial_share"), "Status", "Recorded"],
                   [[r["date"], r["session_id"], r["reps"], r["avg_form"], r["avg_rom"], r["avg_duration"],
                     r["tempo_sd"], r["partial_share"], r["status"], "at home" if r["origin"] == "home" else "in the clinic"]
                    for r in rows])
    mixed = len({r["origin"] for r in rows}) > 1
    summary = "".join(f'<p>{_e(line)}</p>' for line in views.trend_summary_lines(trend))
    return (picker_html + '<div class="cols">' + charts.render(rom, "Session") + charts.render(form_c, "Session") + "</div>"
            + f'<p class="small dim">{_e(views.metric_definition("avg_rom"))} {_e(views.metric_definition("avg_form"))}</p>'
            + (f'<p class="small strong">{_e(views.ORIGIN_NOTE)}</p>' if mixed else "")
            + table + f'<section class="sec"><h2>First to latest</h2>{summary}</section>')


def flags(pid: str, period: str, result) -> str:
    out = _choose(f"/therapist/review/{pid}/flags", _period(period))
    if not result.flags:
        out += '<p class="rowflex">' + shell.CHECK + '<span>Nothing needs attention.</span></p>'
    out += "".join(_note(f.message, "", f.rule.replace("_", " ").capitalize()) for f in result.flags)
    if result.not_evaluated:
        out += ('<section class="sec"><h2>Not evaluated yet</h2><ul class="lines">' + "".join(
            f'<li>{_e(n.rule.replace("_", " ").capitalize())}{" for " + _e(n.exercise) if n.exercise else ""}: needs '
            f'{n.needed} sessions, has {n.have}</li>' for n in result.not_evaluated) + "</ul></section>")
    return out


def compare(pid: str, choices, a: Optional[int], b: Optional[int], shared: List[str], exercise: Optional[str],
            comparison, error: Optional[str]) -> str:
    if len(choices) < 2:
        return '<p class="dim">Two recorded sessions are needed for a comparison.</p>'
    controls = (_get_select("Session A (earlier)", "a", choices, a, "w-wide")
                + _get_select("Session B (later)", "b", choices, b, "w-wide")
                + (_get_select("Exercise", "exercise", [(n, n) for n in shared], exercise, "w-day") if len(shared) > 1 else ""))
    out = _choose(f"/therapist/review/{pid}/compare", controls)
    if error:
        return out + _note(error, "plain", "These sessions can't be compared")
    rows = views.comparison_rows(comparison)
    return (out + f'<p class="strong">{_e(comparison.exercise)} · session {a} to session {b}</p>'
            + _table(["Measure", f"Session {a}", f"Session {b}", "Change", "% change", "Better when"],
                     [[r["measure"], r["a"], r["b"], r["change"], r["pct_change"], r["better"]] for r in rows], (1, 2, 3, 4)))


def session(pid: str, choices, sid: Optional[int], view) -> str:
    if not choices:
        return f'<p class="dim">No sessions recorded for {_e(pid)} yet.</p>'
    out = _choose(f"/therapist/review/{pid}/session", _get_select("Session", "session", choices, sid, "w-full"))
    header = "".join(f'<p class="dim">{_e(h)}</p>' for h in views.session_header_lines(view["session"])[:-1])
    measures = _table(["Exercise", views.metric_label("reps_completed"), views.metric_label("avg_form"),
                       views.metric_label("avg_rom"), views.metric_label("avg_duration"), views.metric_label("tempo_sd"),
                       views.metric_label("partial_share")],
                      [[name, views.fmt_measure("reps_completed", m.reps_completed, m.target_reps),
                        views.fmt_measure("avg_form", m.avg_form), views.fmt_measure("avg_rom", m.avg_rom),
                        views.fmt_measure("avg_duration", m.avg_duration), views.fmt_measure("tempo_sd", m.tempo_sd),
                        views.fmt_measure("partial_share", m.partial_share)] for name, m in view["measures"].items()])
    summary = view["summary"] or {}
    key_flags = summary.get("key_flags") or []
    flags_html = "".join(_note(f.get("message", ""), "" if str(f.get("severity", "")).lower() in
                               ("warning", "high", "critical", "stop") else "info", str(f.get("severity", "info")).capitalize())
                         for f in key_flags) or '<p class="dim">No flags within this session.</p>'
    text = f'<pre class="log">{_e(summary["summary_text"])}</pre>' if summary.get("summary_text") else ""
    review = view["review"]
    steps = [(s, s.capitalize()) for s in NEXT_STEPS]
    reviewed = form(f"/api/review/{pid}/sessions/{sid}/review",
                    select("Next step", "next_step", steps, review.next_step if review else steps[0][0], cls="w-day")
                    + field("Clinical notes", "notes", (review.notes or "") if review else "", kind="textarea",
                            hint="No names, dates of birth or record numbers."),
                    "Mark reviewed" if review is None else "Update review")
    return (out + header + f'<section class="sec"><h2>Measures</h2>{measures}</section>'
            f'<section class="sec"><h2>Per-session summary</h2>{flags_html}{text}</section>'
            f'<section class="sec"><h2>Review</h2><p class="strong">{_e(views.review_status_line(review))}</p>{reviewed}</section>')


def goals(pid: str, scopes: List[str], scope: str, rows: List[dict], changes, goals_list, names: List[str]) -> str:
    exercise = None if scope == WHOLE_PATIENT else scope
    choose = _choose(f"/therapist/review/{pid}/goals", _get_select("Thresholds apply to", "scope",
                                                                     [(s, s) for s in scopes], scope, "w-wide"))
    table = _table(["Threshold", "Value", "Comes from", "Without this override", "Meaning"],
                   [[r["name"], f"{r['value']} {r['unit']}", r["origin"], f"{r['default']} {r['unit']}", r["meaning"]]
                    for r in rows])
    inputs = '<div class="rowflex top-row">' + "".join(
        field(f"{r['name']} ({r['unit']})", r["key"], int(r["value"]), "number", cls="w-day",
              extra=f' min="{r["minimum"]}" max="{r["maximum"]}" step="1"') for r in rows) + "</div>"
    scope_value = f'<input type="hidden" name="scope" value="{_e(scope)}">'
    save = form(f"/api/review/{pid}/thresholds", scope_value + inputs, "Save thresholds")
    reset_label = f"Reset {exercise} to the patient's values" if exercise else "Reset all to the defaults"
    reset = form(f"/api/review/{pid}/thresholds/reset", scope_value, reset_label, quiet=True,
                 confirm="Remove these overrides? The inherited values apply again.")
    history = (_table(["When", "Applies to", "Threshold", "Change"],
                      [[h["when"], h["applies_to"], h["threshold"], h["change"]] for h in views.history_rows(changes)])
               if changes else '<p class="dim">No threshold changes recorded.</p>')
    goal_rows = _table(["Exercise", "Target range of motion (degrees)", "Target reps (count)", "Set"],
                       [[g.exercise_name, g.target_rom or "", g.target_reps or "", views.date_minute(g.set_at)]
                        for g in goals_list], (1, 2)) if goals_list else '<p class="dim">No goals set.</p>'
    goal_form = (form(f"/api/review/{pid}/goals",
                      '<div class="rowflex top-row">' + select("Exercise", "exercise", [(n, n) for n in names], cls="w-wide")
                      + field("Target range of motion, degrees (0 = none)", "target_rom", "0", "number", cls="w-day",
                              extra=' min="0" max="180"')
                      + field("Target reps (0 = none)", "target_reps", "0", "number", cls="w-day",
                              extra=' min="0" max="200"') + "</div>", "Save goal")
                 if names else '<p class="dim">Record a session before setting goals.</p>')
    return (choose + f'<section class="sec"><h2>Attention thresholds</h2>{table}<p class="small dim">Comes from: exercise '
            '= set for this exercise; patient = set for this patient; installation = this clinic\'s value; default = '
            f'built in. Flags, the roster and exports use these values.</p>{save}{reset}</section>'
            f'<details class="edit"><summary class="small strong">Change history</summary>{history}</details>'
            f'<section class="sec"><h2>Goals</h2>{goal_rows}{goal_form}<p class="hint">Saving both targets at 0 '
            'removes the goal.</p></section>')


def from_patient(pid: str, clips, questionnaires: List[dict], chosen_answers, answer_rows, diary: List[dict],
                 diary_on: bool, meds, offered: List[str], nights: List[dict], pain_flags, checkins, pain_series) -> str:
    from src.ptlog import entries as entry_rules
    out = []
    # Clips
    live = [m for m in clips if m.deleted_at is None]
    removed = [m for m in clips if m.deleted_at is not None]
    clip_html = ""
    for m in live:
        state = "reviewed " + m.reviewed_at[:10] if m.reviewed_at else "waiting for review"
        mime = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}.get(m.ext, "video/mp4")
        acts = ("" if m.reviewed_at else form(f"/api/review/{pid}/clips/{m.id}/reviewed", "", "Mark reviewed",
                                              cls="inline-form")) + form(
            f"/api/review/{pid}/clips/{m.id}/delete", "", "Delete", cls="inline-form", quiet=True,
            confirm="Delete this video? The file is removed; a marker stays.")
        clip_html += (f'<li class="top"><div class="stack tight grow-col"><span class="strong">'
                      f'{_e(m.created_at[:16].replace("T", " "))} · {round(m.duration)} s · {_e(state)}'
                      f'{" · caption sent after a privacy warning" if m.warned else ""}</span>'
                      + (f'<p class="pre">{_e(m.caption)}</p>' if m.caption else "")
                      + f'<video controls preload="none" class="clip"><source src="/therapist/files/{_e(pid)}/clips/'
                      f'{_e(m.id)}" type="{mime}"></video><div class="rowflex">{acts}</div></div></li>')
    out.append('<section class="sec"><h2>Videos from the patient</h2>'
               + (f'<ul class="lines">{clip_html}</ul>' if clip_html else
                  '<p class="dim">No videos yet. Patients send them from Today in Limber.</p>')
               + (f'<p class="small dim">{len(removed)} removed: ' + ", ".join(
                   f"{m.created_at[:10]} ({m.deleted_by})" for m in removed) + "</p>" if removed else "") + "</section>")
    # Questionnaires
    q_html = ""
    for g in questionnaires:
        headers = ["When", "Total", "Missing"] + g["subscale_names"]
        rows = [[r["when"], r["total"], r["missing"]] + [v for _, v in r["subscales"]] for r in g["rows"]]
        chart = (charts.render(charts.line_chart(f"{g['name']} total, {g['unit']}", g["series"]), "Answered")
                 if len(g["series"]) >= 2 else "")
        pick = _choose(f"/therapist/review/{pid}/from-patient",
                       _get_select(f"Answers to look at ({g['name']})", f"answers_{g['key']}",
                                   [(r["id"], r["when"]) for r in g["rows"]], chosen_answers.get(g["key"]), "w-wide"))
        detail = answer_rows.get(g["key"]) or []
        detail_html = (_table(list(detail[0].keys()), [list(r.values()) for r in detail]) if detail else "")
        q_html += (f'<div class="stack tight"><h3>{_e(g["name"])} · {len(g["rows"])} answered</h3>'
                   f'<p class="small dim">{_e(g["meaning"])} Score in {_e(g["unit"])}; {_e(g["direction"])}.</p>'
                   + (f'<p class="small warn-text">{_e(g["notice"])}</p>' if g["notice"] else "")
                   + (f'<p class="small dim">{_e(g["version_note"])}</p>' if g["version_note"] else "")
                   + _table(headers, rows, (1, 2)) + (f'<p class="small">{_e(g["change"])}</p>' if g["change"] else "")
                   + chart + pick + detail_html + '<p class="small dim">Value: what the answer scored, after any reversal.'
                   '</p></div>')
    out.append('<section class="sec"><h2>Questionnaires</h2>' + (q_html or '<p class="dim">None answered yet. Assign one '
               'on the patient\'s Exercises tab and it appears on their Today.</p>') + "</section>")
    # Diary
    diary_html = (_table(["When", "Exercise", "Reported", "Total reps", "Effort, 1 to 5", "Note"],
                         [[r["when"], r["exercise"], r["reported"], r["total"], r["effort"], r["note"]] for r in diary], (3,))
                  if diary else '<p class="dim">Nothing logged yet.</p>')
    out.append('<section class="sec"><h2>Logged without the camera</h2>'
               + ("" if diary_on else '<p class="small dim">Logging is turned off for this patient. What they logged '
                  'before stays here.</p>') + diary_html + '<p class="small dim">These count as practice, adherence and '
               'the streak, and carry no measured range of motion or form.</p></section>')
    # Medication and sleep
    med_rows = [[e.recorded_at[:16].replace("T", " ") + (" (time adjusted)" if e.time_adjusted else ""),
                 e.payload.get("item", ""), ("(note removed)" if e.note_removed else (e.payload.get("note") or ""))
                 + (" · sent after a privacy warning" if e.warned else "")] for e in meds]
    out.append('<section class="sec"><h2>Medication taken</h2>'
               + ("" if offered else '<p class="small dim">No medication list is set, so the patient is not offered '
                  'the medication log. Set one on the patient\'s Details tab.</p>')
               + (_table(["When", "Medicine", "Note"], med_rows) if med_rows else '<p class="dim">Nothing logged yet.</p>')
               + "</section>")
    sleep_defs = entry_rules.definitions("sleep")
    sleep_chart = (charts.render(charts.line_chart("Sleep, hours", [(datetime.fromisoformat(n["night"][:10]).strftime("%-d %b"), n["hours"])
                                                                   for n in reversed(nights)],
                                                   unit=" h"), "Night") if len(nights) > 1 else "")
    out.append('<section class="sec"><h2>Sleep</h2>' + (
        _table(["Night", "Hours", "Quality", "Note", "Corrected"],
               [[n["night"], n["hours"], n["quality"], n["note"], "yes" if n["corrected"] else ""] for n in nights], (1,))
        + sleep_chart + f'<p class="small dim">Hours ({_e(sleep_defs["hours"]["unit"])}): '
        f'{_e(sleep_defs["hours"]["meaning"])}</p>' if nights else '<p class="dim">Nothing logged yet.</p>') + "</section>")
    # Pain
    defs = entry_rules.definitions("checkin")
    pain_html = "".join(_note(f.message, "", f.rule.replace("_", " ").capitalize()) for f in pain_flags)
    if checkins:
        from src.clinic.review import around
        pain_chart = charts.render(charts.line_chart("Pain at check-in, 0 to 10", [
            (datetime.fromisoformat(t[:19]).strftime("%-d %b"), s) for t, s, _ in pain_series]), "When")
        rows = [[e.recorded_at[:16].replace("T", " ") + (" (time adjusted)" if e.time_adjusted else ""), around(e),
                 int(e.score) if e.score is not None else "", e.payload.get("area", ""), e.payload.get("stiffness", ""),
                 e.payload.get("swelling", ""), ("(note removed)" if e.note_removed else (e.payload.get("note") or ""))
                 + (" · sent after a privacy warning" if e.warned else "")] for e in checkins]
        notes = [e for e in checkins if e.payload.get("note") and not e.note_removed][:20]
        removable = "".join(
            f'<li><span class="grow-col pre">{_e(e.recorded_at[:16].replace("T", " "))}: {_e(e.payload["note"])}</span>'
            + form(f"/api/review/{pid}/checkins/{e.id}/remove-note", "", "Remove", cls="inline-form", quiet=True,
                   confirm="Remove this note? Use it for one that holds identifying details. A marker stays.") + "</li>"
            for e in notes)
        pain_html += (pain_chart + f'<p class="small dim">Pain ({_e(defs["pain"]["unit"])}): {_e(defs["pain"]["meaning"])}</p>'
                      + _table(["When", "Around", "Pain, 0 to 10", "Where", "Stiffness", "Swelling", "Note"], rows, (2,))
                      + (f'<details class="edit"><summary class="small strong">Remove a note</summary><ul class="lines">'
                         f'{removable}</ul></details>' if removable else ""))
    else:
        pain_html += '<p class="dim">No check-ins yet.</p>'
    out.append(f'<section class="sec"><h2>Pain and symptom check-ins</h2>{pain_html}</section>')
    return "".join(out)


def export(pid: str, period: str, has_questionnaires: bool, report: str) -> str:
    links = (f'<a class="btn quiet small" href="/therapist/review/{_e(pid)}/export/report?period={period}" download>'
             'Review report (text)</a>'
             f'<a class="btn quiet small" href="/therapist/review/{_e(pid)}/export/csv?period={period}" download>'
             'Review data (CSV)</a>'
             + (f'<a class="btn quiet small" href="/therapist/review/{_e(pid)}/export/questionnaires?period={period}" '
                'download>Questionnaire scores (CSV)</a>' if has_questionnaires else ""))
    return (_choose(f"/therapist/review/{pid}/export", _period(period)) + f'<div class="rowflex">{links}</div>'
            + f'<pre class="log">{_e(report)}</pre>')


def page(account, classes: str, title: str, content: str) -> str:
    body = shell.top_bar(account, "review") + f'<main class="page wide" id="main">{content}</main>'
    return shell.document(title, body, classes, scripts=("clinic.js", "forms.js"))
