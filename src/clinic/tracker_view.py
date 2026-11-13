"""The Tracker page (feature 019 slice 5c), from the design export's Tracker screen."""

from __future__ import annotations

from html import escape
from typing import List, Optional

from src.clinic import shell
from src.clinic.patients_view import field, form
from src.clinic.review_view import _choose, _get_select, _table
from src.clinic.tracker import SECTIONS, SORTS, WARN_KINDS, adherence_footer_lines, item_href
from src.ptlog import views


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def frame(section: str, body: str) -> str:
    tabs = "".join(f'<a href="/therapist/tracker/{k}"{" aria-current=\"page\"" if k == section else ""}>{_e(t)}</a>'
                   for k, t in SECTIONS)
    return ('<div class="page-head"><div class="stack tight"><h1>Tracker</h1><p class="dim">Your caseload at a glance, '
            f'and everything waiting on you.</p></div></div><nav class="tabs" aria-label="Tracker sections">{tabs}</nav>'
            f'<div class="stack loose review-body">{body}</div>')


def roster(rows, sort: str, program: str, only: bool, programs: List[tuple]) -> str:
    only_box = (f'<label class="check"><input type="checkbox" name="only" value="1"{" checked" if only else ""} '
                'data-submit-on-change> <span>Needs attention only</span></label>')
    choose = _choose("/therapist/tracker/roster", _get_select("Sort", "sort", SORTS, sort)
                     + _get_select("Program", "program", programs, program, "w-wide") + only_box)
    if not rows:
        return choose + '<p class="dim">No active patients match.</p>'
    table_rows = []
    for r, t in zip(rows, views.roster_table_rows(rows)):
        table_rows.append([r.patient_id, t["label"], t["program"], t["program_status"], t["days_since_last"],
                           t["sessions_7d"], t["sessions_30d"], t["adherence"], t["pending_reviews"], t["open_flags"],
                           r.unread_messages, r.unreviewed_uploads + r.unreviewed_voice_notes, r.overdue_questionnaires,
                           t["practice_gap"], t["last_next_step"], t["needs_attention"]])
    cols = views.roster_columns()
    headers = [cols[k] for k in ("patient_id", "label", "program", "program_status", "days_since_last", "sessions_7d",
                                 "sessions_30d", "adherence", "pending_reviews", "open_flags")] + [
        "Unread messages (count)", "Clips and voice notes to review (count)", "Overdue questionnaires (count)",
        cols["practice_gap"], cols["last_next_step"], cols["needs_attention"]]
    return (choose + _table(headers, table_rows, (4, 5, 6, 8, 9, 10, 11, 12))
            + f'<p class="small dim">{len(rows)} active patient(s). {_e(views.metric_definition("adherence_pct"))}</p>')


def queue(result, threshold: int) -> str:
    head = (f'<p class="small dim">Adherence attention threshold: {threshold}% for the clinic (Settings); a patient\'s '
            'own value is set in Review, Goals and thresholds.</p>')
    if result.count == 0:
        return head + '<p class="rowflex">' + shell.CHECK + '<span>Caseload is up to date.</span></p>'
    out = [head]
    for kind, items in result.items.items():
        if not items:
            continue
        lis = "".join(
            f'<li><span class="code">{_e(it.patient_id)}</span><span class="grow-col">{_e(it.description)}</span>'
            + (f'<a class="sp" href="{_e(item_href(it))}">Open</a>' if item_href(it) else "") + "</li>" for it in items)
        tag = '<span class="tag urgent">Needs attention</span>' if kind in WARN_KINDS else ""
        out.append(f'<section class="sec"><div class="sec-head"><h2>{_e(views.QUEUE_LABELS[kind])}</h2>'
                   f'<span class="count">{len(items)}</span>{tag}</div><ul class="lines">{lis}</ul></section>')
    return "".join(out)


def adherence(patients: List[str], chosen: Optional[str], adh, threshold_line: str) -> str:
    choose = _choose("/therapist/tracker/adherence", _get_select("Patient", "patient", [(p, p) for p in patients],
                                                                 chosen, "w-day"))
    if chosen is None:
        return choose + '<p class="dim">No patients on your caseload yet.</p>'
    if adh.assignment is None:
        return choose + (f'<p class="dim">No program assigned to {_e(chosen)}. Assign one on the patient\'s '
                         f'<a href="/therapist/patients/{_e(chosen)}/exercises">Exercises tab</a>.</p>')
    table = (_table(["Week", "From", "To", "Recorded / planned (count)", "Status", "Exercises performed",
                     "Exercises missing"], [[w["week"], w["from"], w["to"], w["recorded"], w["status"], w["performed"],
                                             w["missing"]] for w in views.adherence_table_rows(adh)], (0, 3))
             if adh.weeks else "")
    foot = "".join(f"<p>{_e(line)}</p>" for line in adherence_footer_lines(views.adherence_lines(adh)))
    return (choose + f'<p class="strong">{_e(views.assignment_line(adh))}</p>{table}{foot}'
            f'<p class="strong">{_e(threshold_line)}</p><p class="small dim">{_e(views.metric_definition("adherence_pct"))}</p>')


def discharged(rows) -> str:
    if not rows:
        return '<p class="dim">No discharged patients.</p>'
    items = "".join(
        f'<li><span class="code">{_e(p.id)}</span><span class="grow-col">{_e(p.label or "")} · discharged '
        f'{_e(d.discharged_on)}{" · " + _e(d.reason) if d.reason else ""}</span>'
        + form(f"/api/patients/{p.id}/reactivate", "", "Reactivate", cls="inline-form", quiet=True) + "</li>"
        for p, d in rows)
    return f'<ul class="lines">{items}</ul>'


def export(count: int) -> str:
    return ('<div class="rowflex"><a class="btn quiet small" href="/therapist/tracker/export/roster.csv" download>'
            f'Roster (CSV)</a></div><p class="small dim">{count} active patient(s); the export always includes every '
            'active patient on your caseload.</p>')


def settings(rows: List[dict], changes, can_change: bool) -> str:
    table = _table(["Threshold", "Value", "Comes from", "Built-in default", "Meaning"],
                   [[r["name"], f"{r['value']} {r['unit']}", r["origin"], f"{r['default']} {r['unit']}", r["meaning"]]
                    for r in rows])
    history = (_table(["When", "Applies to", "Threshold", "Change"],
                      [[h["when"], h["applies_to"], h["threshold"], h["change"]] for h in views.history_rows(changes)])
               if changes else '<p class="dim">No threshold changes recorded.</p>')
    edit = ""
    if can_change:
        inputs = '<div class="rowflex top-row">' + "".join(
            field(f"{r['name']} ({r['unit']})", r["key"], int(r["value"]), "number", cls="w-day",
                  extra=f' min="{r["minimum"]}" max="{r["maximum"]}" step="1"') for r in rows) + "</div>"
        edit = (form("/api/tracker/thresholds", inputs, "Save clinic thresholds")
                + form("/api/tracker/thresholds/restore", "", "Restore built-in defaults", quiet=True,
                       confirm="Restore every clinic threshold to its built-in default?"))
    else:
        edit = '<p class="small dim">Only an admin can change these: they apply to every therapist\'s patients.</p>'
    return (f'<section class="sec"><h2>Clinic attention thresholds</h2>{table}<p class="small dim">Patients with their '
            f'own value (Review, Goals and thresholds) are not affected by changes here.</p>{edit}</section>'
            f'<details class="edit"><summary class="small strong">Change history</summary>{history}</details>')


def page(account, classes: str, content: str) -> str:
    body = shell.top_bar(account, "tracker") + f'<main class="page wide" id="main">{content}</main>'
    return shell.document("Tracker", body, classes, scripts=("clinic.js", "forms.js"))
