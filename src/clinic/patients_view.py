"""The Patients page (feature 019 slice 3a), rendered on the server from the design export (Patients,
PatientExercises, PatientDetails). Each change is a small form that forms.js posts as JSON; this module only
draws what the record says now. Everything the therapist typed or the patient wrote is escaped.
"""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import List, Optional

from src.clinic import nav, patients as rules, shell
from src.ptlog.models import Account, Patient, Plan

TABS = (("overview", "Overview", ""), ("exercises", "Exercises", "/exercises"), ("notes", "Session notes", "/notes"),
        ("ai", "AI settings", "/ai"), ("details", "Details", "/details"))


def nice_date(iso: str) -> str:
    """2026-09-03 as 3 Sep 2026."""
    return date.fromisoformat(iso[:10]).strftime("%-d %b %Y")


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def form(api: str, inner: str, button: str, confirm: str = "", cls: str = "stack", quiet: bool = False,
         result: bool = False) -> str:
    """A form forms.js posts as JSON to /therapist{api}. A confirm text asks first; a result area shows what the
    server hands back once (an access code) instead of reloading."""
    attrs = f' data-api="{_e(api)}"' + (f' data-confirm="{_e(confirm)}"' if confirm else "") + (
        ' data-result-once' if result else "")
    return (f'<form class="{cls}"{attrs} novalidate>{inner}<div class="rowflex">'
            f'<button class="btn{" quiet" if quiet else ""}" type="submit">{_e(button)}</button></div>'
            '<p class="error-text" role="alert" data-error hidden></p>'
            + ('<div class="notice info" role="status" data-result hidden></div>' if result else "") + "</form>")


def field(label: str, name: str, value="", kind: str = "text", hint: str = "", extra: str = "",
          cls: str = "") -> str:
    tag = (f'<textarea class="input" name="{name}"{extra}>{_e(value)}</textarea>' if kind == "textarea" else
           f'<input class="input" type="{kind}" name="{name}" value="{_e(value)}"{extra}>')
    return (f'<label class="field {cls}"><span>{_e(label)}</span>{tag}'
            + (f'<span class="hint">{_e(hint)}</span>' if hint else "") + "</label>")


def check(label: str, name: str, on: bool) -> str:
    return (f'<label class="check"><input type="checkbox" name="{name}"{" checked" if on else ""}> '
            f'<span>{_e(label)}</span></label>')


def select(label: str, name: str, options, chosen=None, cls: str = "", multiple: bool = False) -> str:
    opts = "".join(f'<option value="{_e(v)}"{" selected" if v == chosen else ""}>{_e(t)}</option>' for v, t in options)
    return (f'<label class="field {cls}"><span>{_e(label)}</span><select class="input" name="{name}"'
            f'{" multiple size=\"6\"" if multiple else ""}>{opts}</select></label>')


def section(title: str, body: str, aside: str = "") -> str:
    return (f'<section class="sec"><div class="sec-head"><h2>{_e(title)}</h2>{aside}</div>{body}</section>')


# ----------------------------------------------------------------------------- the list

def side(rows: List[rules.Row], current: Optional[str], show_discharged: bool) -> str:
    active = [r for r in rows if not r.discharged]
    gone = [r for r in rows if r.discharged]
    shown = active + (gone if show_discharged else [])

    def row(r: rules.Row) -> str:
        here = ' aria-current="true"' if r.patient_id == current else ""
        status = (f'<span class="l2 warn-text">{_e(r.status)}</span>' if r.warn else f'<span class="l2">{_e(r.status)}</span>')
        return (f'<a class="row" href="{_e(r.href)}"{here}><span></span><span><span class="l1">'
                f'<span class="code">{_e(r.patient_id)}</span><span class="small ellipsis">{_e(r.title)}</span></span>'
                f'{status}</span></a>')
    toggle = ""
    if gone:
        toggle = (f'<p class="small pad-top"><a href="/therapist/patients{"" if show_discharged else "?discharged=1"}">'
                  f'{"Hide" if show_discharged else "Show"} discharged ({len(gone)})</a></p>')
    return (f'<nav class="side" aria-label="Patients"><div class="side-head"><h2>Patients</h2>'
            f'<span class="small dim">{len(active)} on caseload</span></div>'
            '<div class="pad-x pad-bottom"><a class="btn full" href="/therapist/patients/new">Register a patient</a></div>'
            + ("".join(row(r) for r in shown) or '<p class="small dim pad-x">No patients yet.</p>') + toggle + "</nav>")


def pick_pane() -> str:
    return ('<main class="pane" id="main"><div class="empty"><h2>Pick a patient</h2>'
            '<p>Patients are known only by a pseudonymous code. Choose one on the left, or register a new one.</p>'
            '</div></main>')


def register_pane() -> str:
    body = form("/api/patients", field("Pseudonymous ID", "patient_id", "", extra=' required maxlength="32" '
                                       'placeholder="P-031" autocomplete="off"', hint="1 to 32 letters, digits or hyphens.")
                + field("Label (optional)", "label", "", extra=' maxlength="60" placeholder="Post-op knee"',
                        hint="A short reminder for staff. Never a name, email or birth date.")
                + field("Notes (optional)", "notes", "", kind="textarea"), "Register")
    return ('<main class="pane" id="main"><div class="pane-head ruled"><div class="stack tight"><h1>Register a patient</h1>'
            '<p class="dim">The patient joins your caseload. Do not enter names, dates of birth or record numbers.</p>'
            f'</div></div><div class="pane-body narrow-body">{body}</div></main>')


# ----------------------------------------------------------------------------- one patient

def _tabs(pid: str, active: str, unread: int, ai: bool) -> str:
    """The patient's sections. AI settings is there only when this installation has a key (018 SC-003)."""
    links = [f'<a href="/therapist/patients/{_e(pid)}{suffix}"{" aria-current=\"page\"" if key == active else ""}>'
             f'{label}</a>' for key, label, suffix in TABS if ai or key != "ai"]
    count = f' <span class="count">{unread}<span class="vh"> new</span></span>' if unread else ""
    links.insert(2, f'<a href="/therapist/inbox/{_e(pid)}">Messages{count}</a>')
    return f'<nav class="tabs" aria-label="{_e(pid)}">' + "".join(links) + "</nav>"


def patient_pane(pid: str, subtitle: str, tab: str, unread: int, body: str, ai: bool = False) -> str:
    return (f'<main class="pane" id="main"><div class="pane-head"><div class="stack tight"><h1>{_e(pid)}</h1>'
            f'<p class="dim">{_e(subtitle)}</p></div><span class="sp"></span></div>{_tabs(pid, tab, unread, ai)}'
            f'<div class="pane-body roomy">{body}</div></main>')


def overview(pid: str, facts: dict, plans_html: str, visits_html: str, summary_html: str = "") -> str:
    pain = facts["pain"]
    if pain:
        trend = ""
        if pain["words"]:
            up = pain["change"] > 0
            trend = (f'<span class="small {"strong warn-text" if up else "dim"}">'
                     f'{"↑ " if up else "↓ " if pain["change"] < 0 else ""}{_e(pain["words"])}</span>')
        pain_html = f'<span class="val">{pain["score"]:g}<small>/10</small></span>{trend}'
    else:
        pain_html = '<span class="val">None <small>logged</small></span>'
    visit = facts["visit"]
    visit_html = (f'<span class="val">{_e(visit["when"])}</span><span class="small dim">{_e(visit["detail"])}</span>'
                  if visit else '<span class="val">None <small>booked</small></span>')
    return ('<div class="facts">'
            f'<div class="fact"><span class="lbl">Days done, last 7</span><span class="val">{facts["days_done"]} '
            '<small>of 7 days</small></span><span class="small dim">Days with a recorded session</span></div>'
            '<div class="fact"><span class="lbl">Pain, latest</span>' + pain_html +
            '<span class="small dim">The patient\'s own rating at check-in, 0 (none) to 10 (worst)</span></div>'
            f'<div class="fact"><span class="lbl">Next visit</span>{visit_html}</div></div>'
            f'{summary_html}{plans_html}{visits_html}')


def plans_section(pid: str, plans: List[Plan]) -> str:
    items = []
    for p in plans:
        actions = rules.plan_actions(p)
        base = f"/api/patients/{pid}/plans/{p.id}"
        buttons = ""
        for act, label in (("complete", "Mark complete"), ("reopen", "Reopen"), ("archive", "Archive")):
            if act in actions:
                confirm = ("Archive this plan? It stays readable, and nothing new can be added to it."
                           if act == "archive" else "")
                buttons += form(f"{base}/{act}", "", label, confirm=confirm, cls="inline-form", quiet=True)
        edit = ""
        if "edit" in actions:
            edit = ('<details class="edit"><summary class="small strong">Edit</summary>'
                    + form(f"{base}/edit", field("Title", "title", p.title, extra=f' maxlength="{80}"')
                           + field("Diagnosis", "diagnosis", p.diagnosis, kind="textarea",
                                   hint="Your own words. Never a name or date of birth.")
                           + check(f"Show the diagnosis to {pid}", "diagnosis_visible", p.diagnosis_visible),
                           "Save plan") + "</details>")
        ended = f" · Ended {nice_date(p.end_date)}" if p.end_date else ""
        items.append(f'<li class="top"><div class="stack tight grow-col"><p class="rowflex"><span class="strong">'
                     f'{_e(p.title)}</span><span class="tag {"teal" if p.status == "active" else "ghost"}">'
                     f'{_e(rules.PLAN_STATUS[p.status])}</span><span class="small dim">Since {_e(nice_date(p.start_date))}'
                     f'{_e(ended)}</span></p>'
                     + (f'<p class="small">Diagnosis: {_e(p.diagnosis)}'
                        f'{" · shown to the patient" if p.diagnosis_visible else " · not shown to the patient"}</p>'
                        if p.diagnosis else "") + f'{edit}</div><div class="rowflex">{buttons}</div></li>')
    new = ('<details class="edit"' + ("" if plans else " open") + '><summary class="btn quiet small">Open a new plan'
           '</summary>' + form(f"/api/patients/{pid}/plans",
                               field("Title", "title", "", extra=' maxlength="80" placeholder="Right knee, post-op" required')
                               + field("Diagnosis", "diagnosis", "", kind="textarea",
                                       hint="Your own words. Never a name or date of birth.")
                               + check(f"Show the diagnosis to {pid}", "diagnosis_visible", False), "Open plan")
           + "</details>")
    body = (f'<ul class="lines">{"".join(items)}</ul>' if items else '<p class="dim">No plans of care yet.</p>') + new
    return section("Plans of care", body + '<p class="hint">Complete means the goals were met. Archive closes a plan '
                   'and makes it read-only. Neither deletes records.</p>')


def visits_section(pid: str, visits: List[dict], live_plans: List[Plan], zone: str, today: date) -> str:
    items = []
    for v in visits:
        when = datetime.fromisoformat(v["starts_local"]).strftime("%a %-d %b, %H:%M")
        detail = f"{v['minutes']} minutes" + (f" · {v['note']}" if v["note"] else "")
        tag = {"cancelled": "Cancelled", "past": "Past", "upcoming": ""}[v["state"]]
        tags = (f'<span class="tag ghost">{tag}</span>' if tag else "") + (
            '<span class="tag ghost">Reschedule asked</span>' if v["reschedule_requested"] else "")
        note = ""
        if v["reschedule_requested"]:
            note = (f'<p class="small warn-text">{_e(pid)} asked to reschedule'
                    + (f': “{_e(v["request_note"])}”' if v["request_note"] else ".") + "</p>")
        elif v["response_note"]:
            note = f'<p class="small dim">Your reply: {_e(v["response_note"])}</p>'
        actions = ""
        if v["state"] == "upcoming":
            base = f"/api/patients/{pid}/visits/{v['id']}"
            actions = ('<details class="edit"><summary class="small strong">Change</summary>'
                       + form(f"{base}/move", '<div class="rowflex">' + field("Day", "date", v["date"], "date", cls="w-day")
                              + field("Time", "time", v["time"], "time", cls="w-time") + "</div>", "Change time")
                       + (form(f"{base}/decline", field("Reply without moving it", "note", "", extra=' maxlength="300"'),
                               "Decline request", quiet=True) if v["reschedule_requested"] else "")
                       + form(f"{base}/cancel", "", "Cancel visit", quiet=True,
                              confirm="Cancel this visit? It stays on both calendars, struck through.")
                       + "</details>")
        label = f'<span class="strike">{_e(when)}</span>' if v["state"] == "cancelled" else f'<span class="strong">{_e(when)}</span>'
        items.append(f'<li class="top"><div class="stack tight grow-col">{label}<span class="small dim">'
                     f'{_e(detail)}</span>{note}{actions}</div><div class="rowflex">{tags}</div></li>')
    body = f'<ul class="lines">{"".join(items)}</ul>' if items else '<p class="dim">No visits yet.</p>'
    if live_plans:
        body += ('<details class="edit"' + ("" if items else " open") + '><summary class="btn quiet small">Add a visit'
                 '</summary>' + form(f"/api/patients/{pid}/visits",
                                     '<div class="rowflex">' + field("Day", "date", "", "date", cls="w-day", extra=" required")
                                     + field("Time", "time", "09:00", "time", cls="w-time")
                                     + field("Minutes", "minutes", "45", "number", cls="w-time",
                                             extra=' min="5" max="480" step="5"') + "</div>"
                                     + field("Short note (optional)", "note", "", extra=' maxlength="120" '
                                             'placeholder="Re-check range of motion"')
                                     + select("Plan of care", "plan_id", [(p.id, p.title) for p in live_plans]),
                                     "Add visit") + "</details>")
    else:
        body += '<p class="hint">Open a plan of care to add visits.</p>'
    return section("Visits", body + f'<p class="hint">Times are clinic time ({_e(zone)}).</p>')


def exercises(pid: str, programs, exercise_names: List[tuple], history: List[dict], questionnaires: List[dict],
              choices: List[tuple], interval_options: List[tuple], problems: List[str], today: date) -> str:
    options = [(p.id, p.name) for p in programs] + [("custom", "Custom: choose the exercises")]
    assign = form(f"/api/patients/{pid}/program",
                  '<div class="rowflex">' + select("Program", "program", options, cls="w-wide")
                  + field("Sessions per week", "per_week", "3", "number", cls="w-time", extra=' min="1" max="14"')
                  + field("Start", "start", today.isoformat(), "date", cls="w-day")
                  + field("End (optional)", "end", "", "date", cls="w-day") + "</div>"
                  + select("Exercises, for a custom program (hold Cmd or Ctrl to pick several)", "keys",
                           exercise_names, multiple=True),
                  "Assign program",
                  confirm="Assign this program? It replaces the current one from its start date.")
    if history:
        rows = "".join(f'<tr><td>{_e(h["name"])}</td><td>{_e(h["from"])}</td><td>{_e(h["to"])}</td>'
                       f'<td>{_e(h["status"].capitalize())}</td><td class="r">{h["per_week"]}</td><td>{_e(h["exercises"])}</td></tr>'
                       for h in history)
        table = ('<div class="scroll"><table class="table"><thead><tr><th scope="col">Program</th><th scope="col">From</th>'
                 '<th scope="col">To</th><th scope="col">Status</th><th scope="col" class="r">Sessions per week</th>'
                 f'<th scope="col">Exercises</th></tr></thead><tbody>{rows}</tbody></table></div>')
    else:
        table = '<p class="dim">No program assigned yet.</p>'
    program = section("Program", table + '<details class="edit"><summary class="btn quiet small">Assign a program'
                      '</summary>' + assign + "</details>")
    items = []
    for q in questionnaires:
        items.append(f'<li><div class="stack tight grow-col"><span class="strong">{_e(q["name"])}</span>'
                     f'<span class="small dim">{_e(q["how_often"].capitalize())} · Last answered {_e(q["last"])} · '
                     f'Next due {_e(q["next"])}</span>'
                     + ('<span class="small strong warn-text">Overdue</span>' if q["overdue"] else "")
                     + (f'<span class="small dim">{_e(q["notice"])}</span>' if q["notice"] else "") + "</div>"
                     + form(f"/api/patients/{pid}/questionnaires/{q['id']}/end", "", "End", cls="inline-form", quiet=True,
                            confirm=f"Stop sending {q['name']}? Past answers are kept.") + "</li>")
    warn = "".join(f'<p class="small warn-text">{_e(p)}</p>' for p in problems)
    body = warn + (f'<ul class="lines">{"".join(items)}</ul>' if items else
                   '<p class="dim">None assigned. The patient is offered a questionnaire on Today once you assign one.</p>')
    if choices:
        body += ('<details class="edit"><summary class="btn quiet small">Send a questionnaire</summary>'
                 + form(f"/api/patients/{pid}/questionnaires",
                        '<div class="rowflex">' + select("Questionnaire", "instrument", choices, cls="w-wide")
                        + select("How often", "interval", interval_options, chosen="fortnightly", cls="w-day") + "</div>",
                        "Assign") + "</details>")
    elif not items:
        body += ('<p class="hint">No questionnaires are installed. Add one as a YAML file in the instruments '
                 'folder; no code change is needed.</p>')
    return program + section("Questionnaires", body)


def details(patient: Patient, discharge, diary_on: bool, medications: List[str], access_line: str,
            access_active: bool, history: List[tuple]) -> str:
    pid = patient.id
    base = f"/api/patients/{pid}"
    logs = form(f"{base}/logging", check("Let this patient log exercise done without the camera", "diary", diary_on)
                + '<p class="hint">Logged sessions count towards practice, adherence and the streak, and are marked as '
                'logged. They carry no measured range of motion or form.</p>'
                + field("Medication list, one per line", "medications", "\n".join(medications), kind="textarea",
                        hint="As the patient should see it, for example \"ibuprofen 400 mg\". The patient ticks from "
                             "this list and never types a name. Empty means no medication log. Up to 20 of 60 characters."),
                "Save", quiet=True)
    issue = form(f"{base}/access/issue", "", "Issue a new code" if access_line.startswith(("Access", "The")) else
                 "Issue an access code", result=True, cls="inline-form",
                 confirm="Issue a new code? It replaces any earlier one and signs the patient out." if access_active else "")
    revoke = (form(f"{base}/access/revoke", "", "Revoke", cls="inline-form", quiet=True,
                   confirm="Revoke home access? The patient is signed out of the app.") if access_active else "")
    audit = ""
    if history:
        audit = ('<details class="edit"><summary class="small strong">Access history</summary><div class="scroll">'
                 '<table class="table"><thead><tr><th scope="col">When</th><th scope="col">Event</th><th scope="col">'
                 'Detail</th></tr></thead><tbody>' + "".join(
                     f'<tr><td>{_e(w)}</td><td>{_e(ev)}</td><td>{_e(d)}</td></tr>' for w, ev, d in history)
                 + "</tbody></table></div></details>")
    access = (f'<ul class="lines"><li><div class="stack tight grow-col"><span class="strong">{_e(access_line)}</span>'
              '<span class="small dim">For demo and study use only.</span></div><div class="rowflex">'
              f'{issue}{revoke}</div></li></ul>{audit}'
              '<p class="hint">A code is shown once, when you issue it. Issuing a new code stops the old one. Revoking '
              'signs the patient out of the app.</p>')
    if discharge is not None:
        status = (f'<ul class="lines"><li><div class="stack tight grow-col"><span class="strong">Discharged</span>'
                  f'<span class="small dim">On {_e(discharge.discharged_on)}'
                  + (f" · {_e(discharge.reason)}" if discharge.reason else "")
                  + ' · Records are kept, the app is read-only for the patient</span></div>'
                  + form(f"{base}/reactivate", "", "Reactivate", cls="inline-form", quiet=True) + "</li></ul>")
    else:
        status = ('<ul class="lines"><li><div class="stack tight grow-col"><span class="strong">On your caseload</span>'
                  '</div></li></ul><details class="edit"><summary class="btn quiet small">Discharge</summary>'
                  + form(f"{base}/discharge", '<div class="rowflex">'
                         + field("Discharge date", "on", date.today().isoformat(), "date", cls="w-day")
                         + field("Reason (optional)", "reason", "", extra=' maxlength="200"', cls="w-wide",
                                 hint="No names, dates of birth or record numbers.") + "</div>",
                         "Discharge patient", confirm="Discharge this patient? Records are kept and messaging closes.")
                  + "</details>")
    label = form(f"{base}/details", field("Label", "label", patient.label or "", extra=' maxlength="60"',
                                          hint="A short reminder for staff. Do not use a name, email or birth date.")
                 + field("Notes", "notes", patient.notes or "", kind="textarea"), "Save", quiet=True)
    delete = form(f"{base}/delete", field(f"Type {pid} to confirm", "confirm", "", extra=' autocomplete="off"'),
                  f"Delete {pid} and every record", cls="stack danger-zone",
                  confirm=f"Permanently delete {pid} and its {patient.session_count} sessions? This cannot be undone.")
    return (section(f"What {pid} can log", logs) + section("Home access", access) + section("Caseload status", status)
            + section("Label and notes", label)
            + section(f"Delete {pid}", f'<p class="small dim">Removes the patient, their {patient.session_count} '
                      'sessions, messages, files and logs. It cannot be undone.</p>' + delete))


def page(account: Account, classes: str, side_html: str, pane_html: str, title: str = "Patients") -> str:
    body = shell.top_bar(account, "patients") + f'<div class="split">{side_html}{pane_html}</div>'
    return shell.document(title, body, classes, scripts=("clinic.js", "forms.js", "summary.js"))
