"""Session notes and the AI on a patient's page (feature 019 slice 3b, FR-008): the weekly summary's states, the
citation labels, the AI switches and the read-only coach log. Moved from the Streamlit page and tested without a
server. With no key on this installation there is no AI control anywhere (018 SC-003).

Model text is only ever put on the page as text (escaped here, textContent in summary.js), never as markup.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import List, Optional

RECORD_KINDS = {"S": "Session", "E": "Log", "M": "Message", "T": "Voice note"}

SUMMARY_NOTICES = {
    "no_records": ("No records this week", "{pid} has not logged exercises, pain or messages since {since}, so there "
                   "is nothing to summarise."),
    "cap": ("Today's AI requests are used up", "They reset tomorrow. The records are all in Review."),
    "unavailable": ("The assistant isn't available right now", "Your records are safe. Try again in a few minutes, "
                    "or read the logs directly."),
    "off": ("Weekly summaries are off for {pid}", "Turn them on under AI settings."),
}

COACH_OUTCOMES = {"answer": "Answered", "referral": "Sent to you", "emergency": "Emergency card shown",
                  "refusal": "Not about the program", "off": "Coach was off", "limit": "Daily limit",
                  "no_program": "No program", "unavailable": "Not available"}
COACH_SET_LINES = {"referral": "That's one for your therapist. {pid} was offered Message your therapist.",
                   "emergency": "Emergency card: call 911 or go to the nearest emergency room. No AI text was shown.",
                   "refusal": "Only answers about the program; {pid} was pointed to Messages.",
                   "off": "The coach is turned off — message your therapist instead.",
                   "limit": "Today's question limit was reached.",
                   "no_program": "No program to answer from yet.",
                   "unavailable": "The coach wasn't available; {pid} was pointed to Messages."}


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


def cited(record_ids: List[str]) -> str:
    """"From: Session S-12 · Log E-3", so every statement points to the record it came from."""
    return "From: " + " · ".join(f"{RECORD_KINDS.get(i.split('-')[0], 'Record')} {i}" for i in record_ids)


def summary_json(result, patient_id: str) -> dict:
    """What the page needs to draw a summary, or the notice for a state that isn't a summary."""
    if result.state != "ok":
        title, text = SUMMARY_NOTICES.get(result.state, SUMMARY_NOTICES["unavailable"])
        since = (result.window or {}).get("from", "a week ago")
        return {"state": result.state, "title": title.format(pid=patient_id),
                "text": text.format(pid=patient_id, since=since)}
    return {"state": "ok", "window": result.window, "record_count": result.record_count, "dropped": result.dropped,
            "sections": [{"heading": c.heading, "text": c.text, "from": cited(c.record_ids)} for c in result.sections],
            "next_steps": [{"text": c.text, "from": cited(c.record_ids)} for c in result.next_steps],
            "note": result.as_text()}


def note_is_edited(body: str, original: Optional[str]) -> bool:
    return original is not None and body.strip() != original.strip()


def coach_outcome(turns: List[dict]) -> str:
    counts: dict = {}
    for t in turns:
        counts[t["kind"]] = counts.get(t["kind"], 0) + 1
    return ", ".join(f"{n} {COACH_OUTCOMES[k].lower()}" for k, n in counts.items())


# ----------------------------------------------------------------------------- rendering

AI_TAG = '<span class="ai-tag" aria-hidden="true">AI</span>'


def summary_section(pid: str, available: bool, on: bool) -> str:
    """The weekly summary on Overview. Hidden entirely when no key is configured."""
    if not available:
        return ""
    if not on:
        body = (f'<p class="dim">Weekly summaries and drafts are off for {_e(pid)}. Turn them on under '
                f'<a href="/therapist/patients/{_e(pid)}/ai">AI settings</a>.</p>')
        return f'<section class="sec"><div class="sec-head"><h2>Weekly summary</h2></div>{body}</section>'
    return (f'<section class="sec" data-summary data-patient="{_e(pid)}"><div class="sec-head"><h2>Weekly summary</h2>'
            f'<button class="btn quiet sp" type="button" data-act="summarise">{AI_TAG}Summarise the last 7 days</button>'
            '</div><p class="dim" data-idle>Reads this week\'s check-ins, exercise log, questionnaires and messages, and '
            f'suggests next steps. Nothing is saved or sent until you choose. {_e(pid)} never sees it.</p>'
            '<p class="ai-label" role="status" data-busy hidden>' + AI_TAG +
            'Summarising the last 7 days. This can take up to 30 seconds.</p>'
            '<div class="notice plain" role="alert" data-notice hidden><div class="stack tight"><h3 data-notice-title></h3>'
            '<p data-notice-text></p></div></div><div class="ai-block" data-result hidden></div></section>')


def notes_tab(pid: str, notes: List[dict]) -> str:
    add = ('<form class="stack" data-api="/api/patients/' + _e(pid) + '/notes" novalidate>'
           '<label class="field"><span>New note</span><textarea class="input" name="body" maxlength="4000" '
           'placeholder="What happened, and what comes next"></textarea><span class="hint">Only staff can see notes. '
           'No names, dates of birth or record numbers.</span></label>'
           '<div class="rowflex"><button class="btn" type="submit">Add note</button></div>'
           '<p class="error-text" role="alert" data-error hidden></p></form>')
    items = []
    for n in notes:
        when = datetime.fromisoformat(n["created_at"][:19]).strftime("%a %-d %b %Y, %H:%M")
        label = (f'<span class="ai-label">{AI_TAG}AI-drafted{", then edited" if n["edited"] else ""}</span>'
                 if n["ai_drafted"] else "")
        items.append(f'<li class="top"><div class="stack tight grow-col"><p class="rowflex"><span class="strong">'
                     f'{_e(when)}</span>{label}</p><p class="pre">{_e(n["body"])}</p></div></li>')
    listing = (f'<ul class="lines">{"".join(items)}</ul>' if items else
               '<p class="dim">No session notes yet. A saved weekly summary appears here too.</p>')
    return (f'<section class="sec"><div class="sec-head"><h2>Session notes</h2><span class="small dim">Only staff can '
            f'see these</span></div>{add}</section>{listing}')


def ai_tab(pid: str, switches: dict, since: dict, notices: dict, days: List[dict]) -> str:
    blurbs = {
        "summaries": ("Weekly summaries and drafts",
                      f"Lets you make AI summaries of the last 7 days and AI-drafted replies in the Inbox. You read and "
                      f"edit each one. Nothing reaches {pid} unless you send it."),
        "coach": ("Patient exercise coach",
                  f"{pid} can ask an AI assistant about their own program, on Today and Messages. It answers only from "
                  f"the program and sends worse pain, new symptoms, medicine and program changes to you. Red flags get "
                  f"the emergency card without calling the AI."),
    }
    out = [f'<p class="lede">Both are off for every new patient. Turn them on only after you have told {_e(pid)}. '
           f'Everything the assistant writes is labelled {AI_TAG}.</p>']
    for which, (title, blurb) in blurbs.items():
        on = bool(switches.get(which))
        when = ""
        if on and since.get(which):
            when = (f'<p class="small dim">On since '
                    f'{datetime.fromisoformat(since[which][:10]).strftime("%-d %B %Y")}.</p>')
        switch = (f'<form class="sp" data-api="/api/patients/{_e(pid)}/ai" data-auto novalidate>'
                  f'<input type="hidden" name="which" value="{which}">'
                  f'<label class="switch"><input type="checkbox" role="switch" name="on" aria-label="{_e(title)}"'
                  f'{" checked" if on else ""}><span class="track"></span><span class="state"></span></label>'
                  '<button class="vh" type="submit">Save</button>'
                  '<p class="error-text" role="alert" data-error hidden></p></form>')
        out.append(f'<section class="sec"><div class="sec-head"><h2>{_e(title)}</h2>{switch}</div>'
                   f'<p>{"" if on else "Off. "}{_e(blurb)}</p><div class="stack tight"><p class="small strong">'
                   f'What {_e(pid)} is shown</p><blockquote class="bubble">“{_e(notices[which])}”</blockquote></div>'
                   f'{when}</section>')
    out.append(coach_log(pid, days))
    return "".join(out)


def coach_log(pid: str, days: List[dict]) -> str:
    if not days:
        body = f'<p class="dim">{_e(pid)} hasn\'t asked the coach anything yet.</p>'
    else:
        blocks = []
        for i, d in enumerate(days):
            kinds = {t["kind"] for t in d["turns"]}
            day = datetime.fromisoformat(d["day"]).strftime("%a %-d %b")
            n = len(d["turns"])
            title = (f'{day} · {n} question{"s" if n != 1 else ""} · {coach_outcome(d["turns"])}'
                     + (" · emergency card" if "emergency" in kinds else ""))
            turns = []
            for t in d["turns"]:
                turns.append(f'<div class="msg"><p class="bubble pre">{_e(t["question"])}</p>'
                             f'<p class="meta">{_e(pid)} · {_e(t["asked_at"][11:16])}</p></div>')
                if t["kind"] == "answer":
                    ex = f" · {t['exercise']}" if t.get("exercise") else ""
                    turns.append(f'<div class="msg me"><p class="ai-label">{AI_TAG}AI assistant{_e(ex)}</p>'
                                 f'<p class="bubble pre">{_e(t["answer"] or "")}</p></div>')
                else:
                    turns.append(f'<div class="msg me"><p class="meta">Set message · '
                                 f'{_e(COACH_OUTCOMES[t["kind"]])}</p><p class="bubble">'
                                 f'{_e(COACH_SET_LINES[t["kind"]].format(pid=pid))}</p></div>')
            blocks.append(f'<details class="edit day-log"{" open" if i == 0 else ""}><summary class="strong">'
                          f'{_e(title)}</summary><div class="stack thread">{"".join(turns)}</div></details>')
        body = "".join(blocks)
    return (f'<section class="sec"><div class="sec-head"><h2>Coach conversations</h2><span class="tag ghost">'
            f'Read-only</span></div>{body}<p class="hint">Answered: the coach replied about an assigned exercise. '
            'Sent to you: it did not answer and pointed the patient to Messages. Emergency card shown: it stopped and '
            'showed emergency help without calling the AI.</p></section>')
