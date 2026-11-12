"""The clinic app's page frame (feature 019, T007): the design's top bar and menus around a page's content.

Pages are rendered on the server with the signed-in person's display classes already on the `.lb` root, so
Larger text and Higher contrast are right on the first paint. No inline style or script: the policy blocks both.
"""

from __future__ import annotations

from html import escape
from typing import Iterable, Optional

from src.clinic import nav
from src.ptlog.models import Account

STATIC = "/therapist/static"

LOGO = ('<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M5 19C5 11 9 5 19 5" '
        'fill="none" stroke="#0E6B64" stroke-width="3.5" stroke-linecap="round"/>'
        '<circle cx="5" cy="19" r="3" fill="#F2684A"/></svg>')
CHECK = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>'


def _link(page: nav.Page, active: Optional[str]) -> str:
    current = ' aria-current="page"' if page.key == active else ""
    return f'<a href="{page.href}"{current}>{escape(page.label)}</a>'


def top_bar(account: Account, active: Optional[str] = None) -> str:
    main = "".join(_link(p, active) for p in nav.main_items(account))
    tools = nav.tools_items(account)
    tools_menu = ('<details class="drop"><summary>Tools</summary><div class="menu">'
                  + "".join(_link(p, active) for p in tools) + "</div></details>") if tools else ""
    me = "".join(_link(p, active) for p in nav.me_items(account))
    who = (f'<p class="who">Signed in as <b>{escape(account.display_name or account.username)}</b>'
           f' · {escape(nav.role_text(account))}</p>')
    return (f'<header class="top"><a class="brand" href="{nav.home(account)}">{LOGO}Limber</a>'
            f'<nav class="nav" aria-label="Main">{main}</nav>{tools_menu}'
            f'<details class="drop sp"><summary>Me</summary><div class="menu">{who}{me}'
            f'<button type="button" data-signout>Sign out</button></div></details></header>')


def document(title: str, body: str, classes: str = "", scripts: Iterable[str] = ("clinic.js",)) -> str:
    tags = "".join(f'<script src="{STATIC}/{escape(s)}" defer></script>' for s in scripts)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>Limber · {escape(title)}</title>'
            f'<link rel="icon" href="{STATIC}/favicon.png" type="image/png">'
            f'<link rel="stylesheet" href="{STATIC}/limber.css">{tags}</head>'
            f'<body><div class="lb app {escape(classes)}">{body}</div></body></html>')


def page(account: Account, title: str, content: str, classes: str = "", active: Optional[str] = None,
         width: str = "") -> str:
    main = f'<main class="page {escape(width)}" id="main">{content}</main>'
    return document(title, top_bar(account, active) + main, classes)


def not_online(account: Account, page_info: nav.Page, classes: str) -> str:
    """A page whose slice is not built yet: say so, and list what does work."""
    links = "".join(f'<a class="btn quiet" href="{p.href}">{escape(p.label)}</a>' for p in nav.online(account))
    content = (f'<div class="stack loose"><div class="stack tight"><h1>{escape(page_info.label)}</h1>'
               f'<p class="dim">This page is not online yet. The clinic app is moving here from the old '
               f'therapist app one part at a time.</p></div>'
               f'<div class="stack tight"><h2>Online so far</h2><div class="online-list">{links}</div></div></div>')
    return page(account, page_info.label, content, classes, active=page_info.key, width="mid")


def refused(account: Account, classes: str) -> str:
    content = ('<div class="stack tight"><h1>Not part of your role</h1>'
               '<p class="dim">This page is for therapists. An admin account manages people and sees no '
               'patient records.</p>'
               f'<p><a href="{nav.home(account)}">Back to your start page</a></p></div>')
    return page(account, "Not part of your role", content, classes, width="mid")


def not_found(account: Optional[Account], classes: str) -> str:
    content = ('<div class="stack tight"><h1>Not found</h1>'
               '<p class="dim">This is not on your caseload, or it was removed.</p>'
               f'<p><a href="{nav.home(account)}">Back to your start page</a></p></div>')
    if account is None:
        return document("Not found", f'<main class="page mid">{content}</main>', classes)
    return page(account, "Not found", content, classes, width="mid")


def settings(account: Account, prefs: dict, classes: str) -> str:
    from src.clinic.prefs import HINTS, LABELS
    rows = []
    for key, label in LABELS.items():
        checked = " checked" if prefs.get(key) else ""
        rows.append(f'<li class="setting"><div class="stack tight grow"><h3 id="s-{key}">{escape(label)}</h3>'
                    f'<p class="dim">{escape(HINTS[key])}</p></div>'
                    f'<label class="switch"><input type="checkbox" role="switch" aria-labelledby="s-{key}" '
                    f'data-pref="{key}"{checked}><span class="track"></span><span class="state"></span></label></li>')
    content = ('<div class="stack tight"><h1>My settings</h1>'
               '<p class="dim">These follow you to every device you sign in on.</p></div>'
               f'<ul class="lines">{"".join(rows)}</ul>'
               f'<p class="rowflex small" role="status" data-saved hidden>{CHECK}<span>Saved.</span></p>'
               '<section class="sec tight-top"><h2>Account</h2><dl class="kv">'
               f'<dt>Name shown</dt><dd>{escape(account.display_name or account.username)}</dd>'
               f'<dt>Username</dt><dd>{escape(account.username)}</dd>'
               f'<dt>Role</dt><dd>{escape(_role_sentence(account))}</dd></dl>'
               '<div class="rowflex"><button class="btn plain" type="button" data-signout>Sign out</button></div>'
               '</section>')
    return page(account, "My settings", content, classes, active="settings", width="narrow")


def _role_sentence(account: Account) -> str:
    if account.role == "therapist" and account.is_admin:
        return "Therapist and admin. You see your patients and manage people."
    if account.role == "therapist":
        return "Therapist. You see the patients on your caseload."
    return "Admin. You manage people and see no patient records."


def sign_in(configured: bool, username: str = "", note: str = "") -> str:
    """The clinic's own sign-in screen, or the setup message when no staff password exists yet."""
    if not configured:
        form = ('<div class="card signin stack loose">'
                f'<p class="brand">{LOGO}Limber</p><div class="stack tight"><h1>The clinic side is not set up</h1>'
                '<p class="dim">No staff password has been set yet. Someone with access to the clinic computer '
                'sets it from the command line:</p></div>'
                '<p><code class="code">python interfaces/cli.py portal admin set-password</code></p>'
                '<p class="hint">Then come back to this page and sign in.</p></div>')
        return document("Set up", f'<div class="signin-wrap">{form}</div>')
    form = ('<form class="card signin stack loose" data-signin novalidate>'
            f'<p class="brand">{LOGO}Limber</p><div class="stack tight"><h1>Sign in to carry on</h1>'
            f'<p class="dim">{escape(note or "Sign in with your clinic username and password.")}</p></div>'
            '<div class="notice info" data-kept hidden>' + CHECK +
            '<div class="stack tight"><h3>Your typed reply is kept</h3>'
            '<p>It has not been sent. It will be back in the reply box after you sign in.</p></div></div>'
            '<label class="field"><span>Username</span><input class="input" type="text" name="username" '
            f'autocomplete="username" value="{escape(username)}" required></label>'
            '<label class="field"><span>Password</span><input class="input" type="password" name="password" '
            'autocomplete="current-password" required></label>'
            '<p class="error-text" role="alert" data-error hidden></p>'
            '<div class="rowflex"><button class="btn" type="submit">Sign in</button></div>'
            '<p class="hint">Patients sign in on the front page, not here.</p></form>')
    return document("Sign in", f'<div class="signin-wrap">{form}</div>')
