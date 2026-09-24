"""
The installable app (feature 010): the web app manifest and the list of shell files the service
worker may cache. Pure, so the list is generated from the static folder and never hand-maintained.
The worker itself (interfaces/portal_static/sw.js) caches only what is listed here and never the API.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

PAGES = ["/", "/today", "/checkin", "/progress", "/messages", "/session", "/diary", "/log"]
SHELL_SUFFIXES = (".css", ".js", ".svg", ".png")
NEVER = ("sw.js",)


def manifest() -> Dict[str, Any]:
    return {
        "name": "Limber", "short_name": "Limber", "description": "Physical therapy, between visits",
        "start_url": "/today", "scope": "/", "display": "standalone", "orientation": "portrait",
        "theme_color": "#0E6B64", "background_color": "#FAF8F4",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/apple-touch-icon.png", "sizes": "180x180", "type": "image/png", "purpose": "maskable"},
        ],
    }


def precache(static_dir: Path) -> List[Tuple[str, str]]:
    """(url, sha256) for every shell file and page. The hash makes the cache name change with content,
    so an update never leaves a phone on a stale shell. The pose bundle (vendor/) is left to the
    session page to fetch; it is large and only needed when a session starts."""
    static_dir = Path(static_dir)
    entries: List[Tuple[str, str]] = []
    for path in sorted(static_dir.iterdir()):
        if not path.is_file() or path.suffix not in SHELL_SUFFIXES or path.name in NEVER:
            continue
        entries.append((f"/static/{path.name}", hashlib.sha256(path.read_bytes()).hexdigest()))
    for page in PAGES:
        name = "index.html" if page == "/" else page.strip("/") + ".html"
        html = static_dir / name
        if html.is_file():
            entries.append((page, hashlib.sha256(html.read_bytes()).hexdigest()))
    return entries


def cache_name(entries: List[Tuple[str, str]]) -> str:
    digest = hashlib.sha256("".join(d for _, d in entries).encode()).hexdigest()[:12]
    return f"limber-shell-{digest}"


def service_worker(entries: List[Tuple[str, str]]) -> str:
    """The worker's source. No clinical logic: it only stores and serves the shell."""
    urls = ", ".join(f'"{u}"' for u, _ in entries)
    return (SW_TEMPLATE.replace("__CACHE_NAME__", cache_name(entries)).replace("__PRECACHE__", urls))


SW_TEMPLATE = r"""// Limber service worker. Caches the app shell so the installed app opens without a connection.
// It never caches anything under /api/ or the session WebSocket: those are network only, and the
// page scripts keep their own per-patient snapshot that is wiped on sign-out.
var CACHE_NAME = "__CACHE_NAME__";
var PRECACHE = [__PRECACHE__];   // the shell to precache on install

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE_NAME).then(function (cache) { return cache.addAll(PRECACHE); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (names) {
    return Promise.all(names.filter(function (n) { return n !== CACHE_NAME; }).map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});

function networkOnly(request) { return fetch(request); }

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET") { return; }
  if (url.pathname.indexOf("/api/") === 0 || url.pathname.indexOf("/ws/") === 0 || url.pathname === "/sw.js") {
    event.respondWith(networkOnly(event.request));                  // never cache the API
    return;
  }
  if (url.pathname.indexOf("/static/vendor/") === 0) {
    event.respondWith(caches.open("limber-pose").then(function (cache) {
      return cache.match(event.request).then(function (hit) {
        return hit || fetch(event.request).then(function (res) { if (res.ok) { cache.put(event.request, res.clone()); } return res; });
      });
    }));
    return;
  }
  // shell: network first so updates land, cache when offline
  event.respondWith(fetch(event.request).then(function (res) {
    if (res.ok && (res.type === "basic")) { var copy = res.clone(); caches.open(CACHE_NAME).then(function (c) { c.put(event.request, copy); }); }
    return res;
  }).catch(function () {
    return caches.match(event.request).then(function (hit) { return hit || caches.match("/today"); });
  }));
});
"""
