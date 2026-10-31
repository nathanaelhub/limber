// Limber visits page (feature 017): upcoming and earlier appointments, a month view, and a request to
// reschedule. Times arrive already in the clinic's time zone; this page never converts them.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December"];
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var appts = [], shown = null, asking = null, opener = null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }
  function day(a) { return new Date(a.date + "T12:00:00"); }
  function clock(t) { return t.charAt(0) === "0" ? t.slice(1) : t; }
  function when(a) { var d = day(a); return DAYS[d.getDay()] + " " + d.getDate() + " " + MONTHS[d.getMonth()] + ", " + clock(a.time); }
  function short(a) { var d = day(a); return DAYS[d.getDay()].slice(0, 3) + " " + d.getDate() + " " + MONTHS[d.getMonth()].slice(0, 3) + ", " + clock(a.time); }

  function tag(text, kind) { return el("span", "tag " + kind, text); }
  function row(a, isNext) {
    var li = el("li", "appt " + a.state + (a.state === "cancelled" ? " cx" : ""));
    var d = day(a), tile = el("div", "dt");
    tile.setAttribute("aria-hidden", "true");
    tile.appendChild(el("span", "m", MONTHS[d.getMonth()].slice(0, 3).toUpperCase()));
    tile.appendChild(el("span", "n", String(d.getDate())));
    li.appendChild(tile);
    var body = el("div", "grow");
    var title = el("p", "b", short(a) + " · " + a.minutes + " min");
    title.setAttribute("aria-label", when(a) + ", " + a.minutes + " minutes" + (a.state === "cancelled" ? ", cancelled" : ""));
    body.appendChild(title);
    if (a.note) { body.appendChild(el("p", "small", a.note)); }
    var tags = el("p", "tags");
    if (a.state === "cancelled") { tags.appendChild(tag("Cancelled", "bd-x")); }
    else if (a.state === "past") { tags.appendChild(tag("Past", "bd-past")); }
    else if (isNext) { tags.appendChild(tag("Next", "bd-ok")); }
    if (a.reschedule_requested) { tags.appendChild(tag("Reschedule requested", "bd-req")); }
    if (tags.childNodes.length) { body.appendChild(tags); }
    if (a.reschedule_requested && a.request_note) { body.appendChild(el("p", "small", "You asked: “" + a.request_note + "”")); }
    if (!a.reschedule_requested && a.response_note) { body.appendChild(el("p", "small", "Your therapist: “" + a.response_note + "”")); }
    if (a.state === "upcoming" && !a.reschedule_requested) {
      var ask = el("button", "secondary small-button", "Ask to reschedule");
      ask.type = "button";
      ask.setAttribute("aria-label", "Ask to reschedule " + when(a));
      ask.addEventListener("click", function () { openSheet(a, ask); });
      body.appendChild(ask);
    }
    li.appendChild(body);
    return li;
  }
  function renderList() {
    var up = $("upcoming"), past = $("past");
    [up, past].forEach(function (l) { while (l.firstChild) { l.removeChild(l.firstChild); } });
    var future = appts.filter(function (a) { return a.state !== "past" && !(a.state === "cancelled" && a.date < today()); });
    var earlier = appts.filter(function (a) { return future.indexOf(a) < 0; }).reverse();
    var next = future.filter(function (a) { return a.state === "upcoming"; })[0];
    future.forEach(function (a) { up.appendChild(row(a, a === next)); });
    earlier.forEach(function (a) { past.appendChild(row(a, false)); });
    $("none").hidden = future.length > 0;
    $("past-heading").hidden = earlier.length === 0;
  }
  function today() {
    var t = new Date(), pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return t.getFullYear() + "-" + pad(t.getMonth() + 1) + "-" + pad(t.getDate());
  }
  function renderMonth() {
    var grid = $("month");
    while (grid.firstChild) { grid.removeChild(grid.firstChild); }
    $("month-title").textContent = MONTHS[shown.getMonth()] + " " + shown.getFullYear();
    ["S", "M", "T", "W", "T", "F", "S"].forEach(function (h, i) {
      var c = el("span", "h", h); c.setAttribute("role", "columnheader"); c.setAttribute("aria-label", DAYS[i]); grid.appendChild(c);
    });
    var first = new Date(shown.getFullYear(), shown.getMonth(), 1);
    var days = new Date(shown.getFullYear(), shown.getMonth() + 1, 0).getDate();
    for (var i = 0; i < first.getDay(); i++) { grid.appendChild(el("span", "d o")); }
    var t = today();
    for (var n = 1; n <= days; n++) {
      var iso = shown.getFullYear() + "-" + (shown.getMonth() < 9 ? "0" : "") + (shown.getMonth() + 1) + "-" + (n < 10 ? "0" : "") + n;
      var here = appts.filter(function (a) { return a.date === iso; });
      var live = here.filter(function (a) { return a.state !== "cancelled"; })[0];
      var cls = "d" + (iso === t ? " tdy" : "") + (iso < t ? " pd" : "");
      var label = DAYS[new Date(iso + "T12:00:00").getDay()] + " " + n + " " + MONTHS[shown.getMonth()];
      if (live) { cls += live.state === "past" ? " was" : " ap"; label += ", visit at " + clock(live.time); }
      else if (here.length) { cls += " cn"; label += ", visit cancelled"; }
      var cell = el("span", cls);
      cell.setAttribute("role", "gridcell"); cell.setAttribute("aria-label", label);
      cell.appendChild(el("span", "", String(n)));
      if (live) { cell.appendChild(el("small", "", clock(live.time))); }
      else if (here.length) { cell.appendChild(el("small", "", "Off")); }
      grid.appendChild(cell);
    }
  }
  function show(month) {
    $("list-view").hidden = month; $("month-view").hidden = !month;
    $("show-list").setAttribute("aria-pressed", String(!month)); $("show-month").setAttribute("aria-pressed", String(month));
    if (month) { renderMonth(); }
  }

  function openSheet(a, from) {
    asking = a; opener = from;
    $("reschedule-when").textContent = when(a) + " · " + a.minutes + " min";
    $("reschedule-note").value = ""; $("reschedule-error").hidden = true;
    $("reschedule-send").disabled = false; $("reschedule-send").textContent = "Send request";
    $("reschedule-sheet").hidden = false; $("reschedule-note").focus();
  }
  function closeSheet() { $("reschedule-sheet").hidden = true; if (opener && document.body.contains(opener)) { opener.focus(); } }
  $("reschedule-cancel").addEventListener("click", closeSheet);
  $("reschedule-scrim").addEventListener("click", closeSheet);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("reschedule-sheet").hidden) { closeSheet(); } });
  $("reschedule-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var send = $("reschedule-send"), err = $("reschedule-error");
    send.disabled = true; send.textContent = "Sending…"; err.hidden = true;
    fetch("/api/appointments/" + asking.id + "/reschedule", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note: $("reschedule-note").value }) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; }); })
      .then(function (res) {
        if (res.status === 200) {
          var status = $("status");
          status.textContent = "Request sent for " + when(asking) + ". Your therapist will change the time or reply in Messages.";
          status.hidden = false;
          $("reschedule-sheet").hidden = true;
          return load().then(function () { status.focus(); });
        }
        if (res.status === 401) { window.location.href = "/"; return null; }
        send.disabled = false; send.textContent = "Send request";
        err.textContent = res.data.error || "The request could not be sent."; err.hidden = false;
        return null;
      })
      .catch(function () { send.disabled = false; send.textContent = "Send request"; err.textContent = "The service cannot be reached right now."; err.hidden = false; });
  });

  $("show-list").addEventListener("click", function () { show(false); });
  $("show-month").addEventListener("click", function () { show(true); });
  $("prev-month").addEventListener("click", function () { shown = new Date(shown.getFullYear(), shown.getMonth() - 1, 1); renderMonth(); });
  $("next-month").addEventListener("click", function () { shown = new Date(shown.getFullYear(), shown.getMonth() + 1, 1); renderMonth(); });
  $("status").tabIndex = -1;

  function load() {
    return fetch("/api/appointments", { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) { window.location.href = "/"; return null; }
      return r.json();
    }).then(function (d) {
      if (!d) { return; }
      appts = d.appointments || [];
      $("zone").textContent = "Times are clinic time (" + d.time_zone.replace(/_/g, " ") + ").";
      if (!shown) {
        var next = appts.filter(function (a) { return a.state === "upcoming"; })[0];
        var base = next ? day(next) : new Date();
        shown = new Date(base.getFullYear(), base.getMonth(), 1);
      }
      renderList();
      if (!$("month-view").hidden) { renderMonth(); }
    });
  }
  load();
}());
