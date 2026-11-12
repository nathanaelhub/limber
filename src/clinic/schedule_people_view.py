"""The Schedule and People pages (feature 019 slice 4), from the design export. Forms are posted by forms.js."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import List

from src.clinic import people as people_rules, shell
from src.clinic.patients_view import check, field, form, section, select
from src.ptlog.models import Account


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def _when(v: dict) -> str:
    return datetime.fromisoformat(v["starts_local"]).strftime("%a %-d %b, %H:%M")


def _who(v: dict) -> str:
    return (f'<a class="code" href="/therapist/patients/{_e(v["patient_id"])}">{_e(v["patient_id"])}</a>'
            + (f' · {_e(v["plan"])}' if v["plan"] else ""))


def schedule(groups: dict, zone: str) -> str:
    out = ['<div class="page-head"><div class="stack tight"><h1>Schedule</h1>'
           f'<p class="dim">Visits for your patients, in clinic time ({_e(zone)}). Add a visit on a patient\'s page.'
           '</p></div></div>']
    if groups["requests"]:
        cards = []
        for v in groups["requests"]:
            base = f"/api/patients/{v['patient_id']}/visits/{v['id']}"
            note = f'<blockquote class="bubble self-start">“{_e(v["request_note"])}”</blockquote>' if v["request_note"] else ""
            cards.append(f'<div class="card stack resched"><p>{_who(v)}</p><p class="dim">Booked {_e(_when(v))}, '
                         f'{v["minutes"]} minutes · asks to move it</p>{note}<div class="rowflex top-row">'
                         + form(f"{base}/move", '<div class="rowflex">' + field("Day", "date", v["date"], "date", cls="w-day")
                                + field("Time", "time", v["time"], "time", cls="w-time") + "</div>", "Offer this time")
                         + form(f"{base}/decline", field("Note to the patient (optional)", "note", "",
                                                        extra=' maxlength="300"'), f"Keep {_when(v)}", quiet=True)
                         + "</div></div>")
        out.append(section("Reschedule requests", "".join(cards),
                           f'<span class="count">{len(groups["requests"])}</span>'))

    def rows(visits: List[dict], past: bool) -> str:
        items = []
        for v in visits:
            state = ("Cancelled" if v["state"] == "cancelled" else "Past") if past else (
                "Reschedule asked" if v["reschedule_requested"] else "")
            when = (f'<span class="strike num w-when">{_e(_when(v))}</span>' if v["state"] == "cancelled"
                    else f'<span class="strong num w-when">{_e(_when(v))}</span>')
            items.append(f'<li>{when}<div class="stack tight grow-col"><span>{_who(v)}</span><span class="small dim">'
                         f'{v["minutes"]} minutes' + (f' · {_e(v["note"])}' if v["note"] else "") + '</span></div>'
                         + (f'<span class="tag ghost">{state}</span>' if state else "") + "</li>")
        return f'<ul class="lines">{"".join(items)}</ul>'

    out.append(section("Upcoming", rows(groups["upcoming"], False) if groups["upcoming"] else
                       '<p class="dim">No upcoming visits. Add one on a patient\'s page, under Overview.</p>'))
    if groups["rest"]:
        out.append(f'<details class="edit"><summary class="btn quiet small">Past and cancelled ({len(groups["rest"])})'
                   f'</summary>{rows(groups["rest"], True)}</details>')
    return "".join(out)


def people(me: Account, staff: List[dict], patients: List[dict], invites: List[dict], therapists: List[Account],
           patient_ids: List[tuple], now: datetime) -> str:
    waiting = len(invites)
    head = ('<div class="page-head"><div class="stack tight"><h1>People</h1>'
            f'<p class="dim">{len(staff)} staff account{"s" if len(staff) != 1 else ""} · {waiting} invite'
            f'{"s" if waiting != 1 else ""} waiting</p></div></div>')
    rows = []
    for s in staff:
        status = ('<span class="tag teal">Active</span>' if s["status"] == "active"
                  else '<span class="tag ghost">Disabled</span>')
        if s["you"]:
            action = '<span class="small dim">You can\'t disable yourself</span>'
        else:
            flip = "disabled" if s["status"] == "active" else "active"
            action = form(f"/api/people/accounts/{s['id']}/status", f'<input type="hidden" name="status" value="{flip}">',
                          "Disable" if flip == "disabled" else "Re-enable", cls="inline-form", quiet=True,
                          confirm=("Disable this account? It can't sign in until re-enabled. Its records stay."
                                   if flip == "disabled" else ""))
        rows.append(f'<tr><td class="strong">{_e(s["name"])}' + (' <span class="tag ghost">You</span>' if s["you"] else "")
                    + f'</td><td>{_e(s["username"])}</td><td>{_e(s["role"])}</td><td>{status}</td>'
                    f'<td class="r">{s["patients"] if s["patients"] is not None else "None"}</td><td>{action}</td></tr>')
    staff_html = ('<div class="scroll"><table class="table"><thead><tr><th scope="col">Name</th><th scope="col">Username'
                  '</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col" class="r">Patients</th>'
                  '<th scope="col"><span class="vh">Actions</span></th></tr></thead><tbody>' + "".join(rows)
                  + '</tbody></table></div><p class="hint">A disabled account can\'t sign in. Its records stay. '
                  'Its patients need a therapist: move them below.</p>')
    tlist = [(t.id, t.display_name or t.username) for t in therapists]
    invite = form("/api/people/invite",
                  '<div class="rowflex">' + select("Role", "role", [("therapist", "Therapist"), ("patient", "Patient"),
                                                                    ("admin", "Admin")], cls="w-day")
                  + select("Patient's therapist (for a patient)", "therapist_id", tlist, cls="w-wide")
                  + field("Patient code (for a patient)", "patient_id", "", extra=' maxlength="32" placeholder="P-031"',
                          cls="w-day") + "</div>"
                  + check("Also an admin (for a therapist)", "make_admin", False),
                  "Create invite link", result=True)
    inv_items = "".join(
        f'<li><div class="stack tight grow-col"><span class="strong">{_e(i["role"].capitalize())}'
        + (f' {_e(i["patient_id"])}, with {_e(i["therapist"])}' if i["patient_id"] else "")
        + f'</span><span class="small dim">Not used · {_e(people_rules.expires_words(i["expires"], now))}</span></div>'
        + form(f"/api/people/invites/{i['id']}/revoke", "", "Revoke", cls="inline-form", quiet=True,
               confirm="Revoke this invite? The link stops working.") + "</li>" for i in invites)
    invites_html = (f'<ul class="lines">{inv_items}</ul>' if inv_items else '<p class="dim">No invites waiting.</p>') + (
        '<details class="edit"><summary class="btn quiet small">Invite someone</summary>' + invite
        + '<p class="hint">The link is shown once, works once and lasts 7 days. Limber does not send it anywhere.</p>'
        + "</details>")
    pat_rows = "".join(f'<tr><td class="code">{_e(p["patient_id"])}</td><td>{_e(p["username"])}</td>'
                       f'<td>{_e(p["therapist"] or "nobody")}</td><td>{_e(p["status"].capitalize())}</td></tr>'
                       for p in patients)
    pat_html = ('<div class="scroll"><table class="table"><thead><tr><th scope="col">Patient</th><th scope="col">Username'
                '</th><th scope="col">Therapist</th><th scope="col">Status</th></tr></thead><tbody>' + pat_rows
                + '</tbody></table></div>') if patients else '<p class="dim">No patient has a username yet.</p>'
    move = ""
    if patient_ids and tlist:
        move = section("Move a patient to another therapist",
                       '<p class="small dim">The new therapist sees the patient\'s whole history; the old one no longer '
                       'sees any of it.</p>' + form("/api/people/reassign", '<div class="rowflex">'
                       + select("Patient", "patient_id", [(pid, f"{pid} (now {who})") for pid, who in patient_ids],
                                cls="w-wide") + select("To therapist", "therapist_id", tlist, cls="w-wide") + "</div>",
                       "Move patient", confirm="Move this patient? Only the new therapist will see them."))
    return (head + section("Staff", staff_html) + section("Invites waiting", invites_html)
            + section("Patients with a username", pat_html) + move)


def page(account: Account, classes: str, active: str, title: str, content: str) -> str:
    body = shell.top_bar(account, active) + f'<main class="page wide" id="main">{content}</main>'
    return shell.document(title, body, classes, scripts=("clinic.js", "forms.js"))
