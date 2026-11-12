"""The Inbox page (feature 019 slice 2), rendered on the server from the design export (Main, InboxReply,
InboxWithheld, InboxReschedule, InboxArchived, InboxMessaging, InboxStates).

Patient text is always escaped: nothing a patient writes is ever markup. The page's script (inbox.js) does the
writes; this module only draws what the record says now.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import List, Optional

from src.clinic import inbox, nav, shell
from src.ptlog.models import Account, Message, Plan

I_WARN = ('<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2.5 20h19L12 3z"/>'
          '<path d="M12 10v4M12 17h.01"/></svg>')
I_CAL = ('<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/>'
         '<path d="M3 10h18M8 3v4M16 3v4"/></svg>')
I_PHOTO = ('<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/>'
           '<path d="m3 16 5-5 4 4 3-3 6 6"/></svg>')
I_DOC = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>'
I_CLIP = ('<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5 12 19.5a5 5 0 0 1-7-7l8.5-8.5'
          'a3.5 3.5 0 0 1 5 5L10 17.5a2 2 0 0 1-3-3l8-8"/></svg>')
DONE = ('<svg viewBox="0 0 48 48" width="48" height="48" aria-hidden="true"><circle cx="24" cy="24" r="21" '
        'fill="#E3EFED"/><path d="m15 24 6 6 12-13" fill="none" stroke="#0E6B64" stroke-width="3.5" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>')
AI_TAG = '<span class="ai-tag" aria-hidden="true">AI</span>'


def _e(text) -> str:
    return escape(str(text if text is not None else ""))


# ----------------------------------------------------------------------------- the left side

def _item_row(item: inbox.Item, now: datetime, current: Optional[tuple]) -> str:
    tags = {inbox.URGENT: f'<span class="tag urgent">{I_WARN}Urgent</span>',
            inbox.RESCHEDULE: f'<span class="tag ghost">{I_CAL}Reschedule</span>',
            inbox.UNREAD: f'<span class="tag new">{item.unread} new</span>'}
    unread = item.kind == inbox.UNREAD
    here = ' aria-current="true"' if current == (item.patient_id, item.plan_id) else ""
    line = item.plan_title + (" · " if item.plan_title and item.line else "") + item.line
    return (f'<a class="row{" unread" if unread else ""}" href="{_e(item.href)}"{here}>'
            f'<span{" class=\"dot\"" if unread else ""}></span>'
            f'<span><span class="l1"><span class="code">{_e(item.patient_id)}</span>{tags[item.kind]}'
            f'<span class="micro dim sp">{_e(inbox.when_label(item.at, now))}</span></span>'
            f'<span class="l2">{_e(line)}</span></span></a>')


def side(items: List[inbox.Item], conversations: List[dict], now: datetime, current: Optional[tuple]) -> str:
    rows = "".join(_item_row(i, now, current) for i in items) or '<p class="small dim pad-x">All clear.</p>'
    count = (f'<span class="count">{len(items)}<span class="vh"> need you</span></span>' if items
             else '<span class="tag ghost">0</span>')
    others = "".join(
        f'<a href="{_e(c["href"])}"{" aria-current=\"page\"" if current and current[0] == c["patient_id"] else ""}>'
        f'<span class="code">{_e(c["patient_id"])}</span>'
        f'<span class="dim ellipsis">{_e(c["summary"] or "No plan yet")}</span></a>'
        for c in conversations)
    return (f'<nav class="side" aria-label="Needs you"><div class="side-head"><h2>Needs you</h2>{count}</div>{rows}'
            f'<details class="convs"><summary class="small strong">All conversations ({len(conversations)})</summary>'
            f'<div class="sidelist">{others}</div></details></nav>')


def empty_pane() -> str:
    return (f'<main class="pane" id="main"><div class="empty">{DONE}<h2>Pick an item to open it</h2>'
            '<p>New messages, reschedule requests and urgent items are on the left. Opening this page marks '
            'nothing as read.</p></div></main>')


def all_clear_pane() -> str:
    return (f'<main class="pane" id="main"><div class="empty">{DONE}<h2>Nothing needs you right now</h2>'
            '<p>New messages, reschedule requests and urgent items will show here.</p></div></main>')


# ----------------------------------------------------------------------------- the open conversation

def _attachments(m: Message) -> str:
    live = [a for a in m.attachments if a.deleted_at is None]
    photos = [a for a in live if a.kind == "photo"]
    out = ""
    if photos:
        out += '<div class="thumbs">' + "".join(
            f'<a class="ph thumb" href="/therapist/files/{_e(m.patient_id)}/attachments/{_e(a.id)}" target="_blank" '
            f'rel="noopener"><img src="/therapist/files/{_e(m.patient_id)}/attachments/{_e(a.id)}" '
            f'alt="Photo {n} from {_e(m.patient_id)}" loading="lazy"></a>'
            for n, a in enumerate(photos, 1)) + "</div>"
    for a in live:
        if a.kind != "photo":
            out += (f'<a class="chip" href="/therapist/files/{_e(m.patient_id)}/attachments/{_e(a.id)}" '
                    f'download="document.pdf">{I_DOC}PDF · {max(1, a.bytes // 1024)} KB</a>')
    if len(live) < len(m.attachments):
        out += '<p class="micro dim">An attachment was removed.</p>'
    return out


def _voice(m: Message, media, job, transcripts: bool, can_act: bool) -> str:
    if media is None:
        return '<p class="bubble dim">This voice note is no longer in the record.</p>'
    head = (f'<p class="micro strong">Voice note · {media.duration:.0f} s · '
            f'{"heard" if media.reviewed_at else "not heard yet"}</p>')
    if media.deleted_at is not None:
        return f'<div class="voice-note">{head}<p class="bubble dim">The recording was removed.</p></div>'
    src = f'/therapist/files/{_e(m.patient_id)}/voice/{_e(media.id)}'
    note, text = inbox.voice_state(job, transcripts)
    transcript = (f'<div class="transcript"><p class="micro strong">{_e(note)}</p>'
                  + (f'<p class="pre">{_e(text)}</p>' if text is not None else "") + "</div>")
    actions = ""
    if can_act:
        buttons = []
        if media.reviewed_at is None:
            buttons.append(f'<button class="btn plain small" type="button" data-act="voice-heard" '
                           f'data-id="{_e(media.id)}">Mark heard</button>')
        buttons.append(f'<button class="btn plain small" type="button" data-act="voice-delete" data-id="{_e(media.id)}" '
                       'data-confirm="Delete this voice note? The recording and any text are removed; a marker stays.">'
                       'Delete</button>')
        if text is not None and job is not None and job.text:
            buttons.append(f'<button class="btn plain small" type="button" data-act="voice-text" data-id="{_e(media.id)}" '
                           'data-confirm="Remove the written-out text? The recording stays.">Remove the text</button>')
        actions = '<div class="rowflex">' + "".join(buttons) + "</div>"
    return (f'<div class="voice-note stack tight">{head}<audio controls preload="none" src="{src}"></audio>'
            f'{transcript}{actions}</div>')


def _message(m: Message, now: datetime, voices: dict, transcripts: bool, can_act: bool, new: bool) -> str:
    mine = m.sender == "therapist"
    who = "You" if mine else m.patient_id
    when = datetime.fromisoformat(m.sent_at[:19]).strftime("%-H:%M")
    extras = []
    if m.warned:
        extras.append("sent after a privacy warning")
    if mine and m.from_draft:
        extras.append(f"{AI_TAG}began as an AI draft")
    if mine and m.read_at:
        extras.append("seen")
    meta = (f'<p class="meta">{_e(who)} · {when}' + "".join(f" · {x}" for x in extras)
            + (' <span class="tag new">New</span>' if new else ""))
    if can_act and not m.removed and not m.media_id:
        meta += (f' <button class="btn plain small" type="button" data-act="remove" data-id="{m.id}" '
                 'data-confirm="Remove this message? Use it for one that holds identifying details. A marker stays.">'
                 'Remove</button>')
    meta += "</p>"
    if m.removed:
        body = '<p class="bubble dim">This message was removed.</p>'
    elif m.media_id:
        media, job = voices.get(m.media_id, (None, None))
        body = _voice(m, media, job, transcripts, can_act)
    else:
        body = (f'<p class="bubble pre">{_e(m.body)}</p>' if m.body else "") + _attachments(m)
    return f'<div class="msg{" me" if mine else ""}" id="m{m.id}">{body}{meta}</div>'


def thread_html(messages: List[Message], now: datetime, voices: dict, transcripts: bool, can_act: bool) -> str:
    if not messages:
        return '<p class="dim">No messages in this plan yet.</p>'
    out, last_day = [], None
    for m in messages:
        day = inbox.day_label(m.sent_at, now)
        if day != last_day:
            out.append(f'<p class="day">{_e(day)}</p>')
            last_day = day
        new = m.sender == "patient" and m.read_at is None
        out.append(_message(m, now, voices, transcripts, can_act, new))
    return "".join(out)


def _withheld(patient_id: str, flagged: List[Message], words: List[str], now: datetime) -> str:
    quoted = " and ".join(f"<b>“{_e(w)}”</b>" for w in words) or "words on the red-flag list"
    last = flagged[-1]
    return ('<div class="notice" role="alert"><div class="stack grow-col"><div class="stack tight">'
            '<h3>This message may need a direct response</h3>'
            f'<p>{_e(patient_id)} used words that can point to an injury: {quoted}. '
            'No reply was drafted. Please contact the patient directly.</p></div>'
            f'<blockquote class="quote">“{_e(inbox.first_line(last.body, 300))}”</blockquote>'
            f'<p class="small dim">Sent {_e(inbox.day_label(last.sent_at, now).lower())} at '
            f'{datetime.fromisoformat(last.sent_at[:19]).strftime("%-H:%M")}.</p>'
            '<div class="rowflex"><button class="btn" type="button" data-act="handled">Mark as handled by phone</button>'
            '</div></div></div>')


def _reschedule(patient_id: str, view: dict, request_note: str) -> str:
    when = datetime.fromisoformat(view["starts_local"]).strftime("%a %-d %b, %H:%M")
    note = f'<blockquote class="bubble self-start">“{_e(request_note)}”</blockquote>' if request_note else ""
    return (f'<section class="card stack resched" data-visit="{view["id"]}" aria-label="Reschedule request">'
            f'<div class="stack tight"><h2>{I_CAL} Reschedule request</h2>'
            f'<p class="dim">{_e(patient_id)} asks to move the visit booked for {_e(when)}, {view["minutes"]} minutes.</p>'
            f'</div>{note}<fieldset class="stack plain-set"><legend class="strong">Your answer</legend>'
            '<label class="check"><input type="radio" name="answer" value="move" checked> <span>Offer another time</span></label>'
            f'<div class="rowflex"><label class="field w-day"><span>Day</span><input class="input" type="date" '
            f'name="date" value="{_e(view["date"])}"></label><label class="field w-time"><span>Time</span>'
            f'<input class="input" type="time" name="time" value="{_e(view["time"])}"></label></div>'
            f'<label class="check"><input type="radio" name="answer" value="keep"> <span>Keep {_e(when)}</span></label>'
            '</fieldset><label class="field"><span>Note to the patient (optional)</span>'
            '<input class="input" type="text" name="note" maxlength="300"></label>'
            '<div class="rowflex"><button class="btn" type="button" data-act="answer">Send answer</button>'
            f'<span class="hint">{_e(patient_id)} sees the answer in the app as soon as you send.</span></div>'
            '<p class="error-text" role="alert" data-error hidden></p></section>')


def _reply_box(patient_id: str, assist: bool) -> str:
    draft = (f'<button class="btn quiet sp" type="button" data-act="draft">{AI_TAG}Draft a reply</button>'
             if assist else '<span class="sp"></span>')
    return (f'<form class="reply" data-reply novalidate><div class="reply-top" data-ai-top hidden>'
            f'<span class="ai-label">{AI_TAG}<span data-ai-text>AI-drafted — check before sending</span></span>'
            '<button class="btn plain small sp" type="button" data-act="discard">Discard draft</button></div>'
            f'<label class="vh" for="reply-text">Reply to {_e(patient_id)}</label>'
            f'<textarea id="reply-text" name="text" maxlength="2000" placeholder="Reply to {_e(patient_id)}"></textarea>'
            '<div class="attached" data-attached hidden></div>'
            '<div class="notice plain warn-box" role="alert" data-warn hidden><div class="stack tight">'
            '<h3>Check before you send</h3><p data-warn-text></p>'
            '<div class="rowflex"><button class="btn quiet small" type="button" data-act="send-anyway">Send anyway</button>'
            '<span class="hint">Or edit the reply and press Send.</span></div></div></div>'
            f'<div class="reply-bar"><label class="btn plain small file-pick">{I_CLIP}Attach'
            '<input type="file" name="files" accept="image/jpeg,image/png,image/heic,application/pdf" multiple '
            'class="vh" data-files></label><span class="hint" data-hint>Up to 4 photos or 1 PDF. Plain text, no names '
            f'or contact details.</span>{draft}<button class="btn" type="submit">Send</button></div>'
            '<p class="error-text pad-x" role="alert" data-error hidden></p></form>')


def conversation(patient_id: str, plan: Optional[Plan], plans: List[Plan], unread_by_plan: dict,
                 messages: List[Message], now: datetime, state: str, enabled: bool, assist: bool,
                 flagged: List[Message], words: List[str], voices: dict, transcripts: bool,
                 subtitle: str, requests: List[tuple]) -> str:
    title = f"{patient_id}" + (f" · {plan.title}" if plan else "")
    tabs = ""
    if len(plans) > 1:
        tabs = '<nav class="tabs" aria-label="Plans of care">' + "".join(
            f'<a href="{_e(inbox.conversation_href(patient_id, p.id))}"'
            + (' aria-current="page"' if plan and p.id == plan.id else "") + f'>{_e(p.title)}'
            + (" · archived" if p.read_only else "")
            + (f' <span class="tag new">{unread_by_plan[p.id]} new</span>' if unread_by_plan.get(p.id) else "")
            + "</a>" for p in plans) + "</nav>"
    toggle = (f'<button type="button" data-act="messaging" data-on="{"0" if enabled else "1"}">'
              f'Turn messaging {"off" if enabled else "on"} for {_e(patient_id)}</button>')
    head = (f'<div class="pane-head ruled"><div class="stack tight"><h1>{_e(title)}</h1>'
            f'<p class="dim">{_e(subtitle)}</p></div>'
            + (f'<a class="btn quiet small sp" href="/therapist/patients/{_e(patient_id)}">Open patient</a>'
               if nav.BY_KEY["patients"].online else '<span class="sp"></span>') +
            f'<details class="drop inline"><summary>More</summary><div class="menu">{toggle}</div></details>{tabs}</div>')
    can_act = state != "archived"
    body = "".join(_reschedule(patient_id, view, a.request_note) for a, view in requests)
    if flagged:
        body += _withheld(patient_id, flagged, words, now)
    body += thread_html(messages, now, voices, transcripts, can_act)
    if state == "open":
        foot = _reply_box(patient_id, assist and not flagged)
        if flagged and assist:
            foot = ('<p class="hint">Draft a reply is off for this message. After you mark it as handled, it leaves '
                    'Needs you.</p>') + foot
    elif state == "off":
        foot = ('<div class="notice plain"><div class="stack tight">'
                f'<h3>Messaging is off for {_e(patient_id)}</h3>'
                f'<p>{_e(patient_id)} can read past messages but cannot send new ones.</p>'
                f'<div class="rowflex"><button class="btn quiet small" type="button" data-act="messaging" data-on="1">'
                'Turn messaging on</button></div></div></div>')
    else:
        live = [p for p in plans if not p.read_only]
        other = (f' To write to {_e(patient_id)}, open <a href="{_e(inbox.conversation_href(patient_id, live[0].id))}">'
                 f'{_e(live[0].title)}</a>.' if state == "archived" and live else "")
        foot = (f'<div class="notice plain"><div class="stack tight"><h3>Read-only</h3>'
                f'<p>{_e(inbox.READ_ONLY_TEXT[state])}{other}</p></div></div>')
    data = (f' data-patient="{_e(patient_id)}" data-plan="{plan.id if plan else ""}"'
            f' data-mark-read="{"1" if any(m.sender == "patient" and m.read_at is None for m in messages) else "0"}"')
    return (f'<main class="pane" id="main"{data}>{head}<div class="pane-body" data-thread>{body}</div>'
            f'<div class="pane-foot"><p class="small" role="status" data-status hidden></p>{foot}'
            f'<p class="error-text" role="alert" data-page-error hidden></p></div></main>')


def page(account: Account, classes: str, side_html: str, pane_html: str, title: str = "Inbox") -> str:
    body = shell.top_bar(account, "inbox") + f'<div class="split">{side_html}{pane_html}</div>'
    return shell.document(title, body, classes, scripts=("clinic.js", "inbox.js"))
