// Limber patient portal: sign-in and today's program. Rendering only; every rule lives on the server.
(function () {
  "use strict";
  var page = document.body.getAttribute("data-page");

  // ---- installable app (feature 010): shell caching, per-patient snapshot, offline queue ----
  var store = { get: function (k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
                set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
                del: function (k) { try { localStorage.removeItem(k); } catch (e) {} } };
  function wipeLocal() {                                  // sign-out or a refused request: nothing stays readable
    Object.keys(localStorage).forEach(function (k) { if (k.indexOf("limber.") === 0) { store.del(k); } });
  }
  function uuid() {
    if (window.crypto && window.crypto.randomUUID) { return window.crypto.randomUUID(); }
    return "x" + Date.now().toString(16) + Math.random().toString(16).slice(2);
  }
  function localIso(d) {
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }
  function post(path, body) {
    return fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; }); });
  }
  function sendEntry(entry) {
    if (!navigator.onLine) { queue(entry); return Promise.resolve({ queued: true }); }
    return post("/api/entries", entry).then(function (res) {
      if (res.status === 401) { wipeLocal(); window.location.href = "/"; }
      return res;
    }).catch(function () { queue(entry); offlineBanner(true); return { queued: true }; });
  }
  function queue(entry) { var q = store.get("limber.queue") || []; q.push(entry); store.set("limber.queue", q); }
  function replayQueue() {
    var q = store.get("limber.queue") || [];
    if (!q.length || !navigator.onLine) { return Promise.resolve(); }
    var rest = q.slice(1);
    return post("/api/entries", q[0]).then(function (res) {
      if (res.status === 200 || res.status === 201 || res.status === 400 || res.status === 409) {
        store.set("limber.queue", rest);                 // sent, already known, or unsendable: drop it and go on
        return replayQueue();
      }
      if (res.status === 401) { wipeLocal(); }
    }).catch(function () {});
  }
  function offlineBanner(force) { var b = document.getElementById("offline"); if (b) { b.hidden = navigator.onLine && !force; } }
  if ("serviceWorker" in navigator) { navigator.serviceWorker.register("/sw.js").catch(function () {}); }
  window.addEventListener("online", function () { offlineBanner(); replayQueue(); });
  window.addEventListener("offline", offlineBanner);
  offlineBanner(); replayQueue();
  window.limber = { uuid: uuid, localIso: localIso, sendEntry: sendEntry, replayQueue: replayQueue, wipeLocal: wipeLocal };

  function installHint() {
    var hint = document.getElementById("install-hint");
    if (!hint || store.get("limber.install-dismissed")) { return; }
    var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
    if (standalone) { return; }
    var ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
    var deferred = null;
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault(); deferred = e;
      document.getElementById("install-now").hidden = false;
    });
    document.getElementById(ios ? "install-steps-ios" : "install-steps-android").hidden = false;
    hint.hidden = false;
    document.getElementById("install-now").addEventListener("click", function () {
      if (deferred) { deferred.prompt(); deferred = null; }
      hint.hidden = true;
    });
    document.getElementById("install-dismiss").addEventListener("click", function () { store.set("limber.install-dismissed", true); hint.hidden = true; });
  }

  function api(path, options) {
    options = options || {};
    options.credentials = "same-origin";
    if (options.body) { options.headers = { "Content-Type": "application/json" }; }
    return fetch(path, options).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) { return { status: r.status, data: data }; });
    });
  }

  function text(id, value) { var el = document.getElementById(id); if (el) { el.textContent = value; } return el; }

  var signout = document.getElementById("signout");
  if (signout) {
    signout.addEventListener("click", function () {
      api("/api/logout", { method: "POST", body: "{}" }).then(function () { wipeLocal(); window.location.href = "/"; });
    });
  }

  if (page === "signin") {
    // two doors on one front page: the patient's access code, or the therapist's password
    var doors = { patient: document.getElementById("door-patient"), therapist: document.getElementById("door-therapist") };
    var panels = { patient: document.getElementById("signin"), therapist: document.getElementById("admin-signin") };
    var show = function (which) {
      Object.keys(doors).forEach(function (k) {
        doors[k].setAttribute("aria-selected", String(k === which));
        panels[k].hidden = k !== which;
      });
      document.getElementById("patient-notice").hidden = which !== "patient";
      (which === "patient" ? document.getElementById("code") : document.getElementById("password")).focus();
    };
    doors.patient.addEventListener("click", function () { show("patient"); });
    doors.therapist.addEventListener("click", function () { show("therapist"); });
    api("/api/health").then(function (res) {
      document.getElementById("admin-hint").hidden = res.data.therapist_sign_in !== false;
    });
    panels.therapist.addEventListener("submit", function (event) {
      event.preventDefault();
      var error = document.getElementById("admin-error");
      error.hidden = true;
      api("/api/admin/login", { method: "POST", body: JSON.stringify({ password: document.getElementById("password").value }) })
        .then(function (res) {
          if (res.status === 200 && res.data.redirect) { window.location.href = res.data.redirect; return; }
          error.textContent = res.data.error || "Sign-in is not available right now.";
          error.hidden = false;
        })
        .catch(function () { error.textContent = "The service cannot be reached right now."; error.hidden = false; });
    });
    document.getElementById("signin").addEventListener("submit", function (event) {
      event.preventDefault();
      var error = document.getElementById("error");
      error.hidden = true;
      var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
      api("/api/login", { method: "POST", body: JSON.stringify({ code: document.getElementById("code").value, device: standalone }) })
        .then(function (res) {
          if (res.status === 200) { window.location.href = "/today"; return; }
          error.textContent = res.data.error || "Sign-in is not available right now.";
          error.hidden = false;
        })
        .catch(function () { error.textContent = "The service cannot be reached right now."; error.hidden = false; });
    });
  }

  // the Messages link appears only when the therapist has turned messaging on for this patient
  function messagesLink(badge) {
    var link = document.getElementById("nav-messages"), count = document.getElementById("nav-unread");
    if (!link || !badge) { return; }
    link.hidden = !badge.enabled && page !== "messages";
    if (count) { count.hidden = !badge.unread; count.textContent = String(badge.unread); }
  }

  if (page === "session" || page === "progress" || page === "messages" || page === "clip" ||
      page === "diary" || page === "log") {
    api("/api/today").then(function (res) {
      if (res.status === 401) { window.location.href = "/"; return; }
      text("patient-id", res.data.patient_id);
      if (page !== "messages") { messagesLink(res.data.messages); }
    });
  }

  function renderToday(d) {
      text("patient-id", d.patient_id);
      messagesLink(d.messages);
      if (d.checkin && d.checkin.today) { var cd = text("checkin-done", "Check-ins today: " + d.checkin.today); cd.hidden = false; }
      if (d.diary) { document.getElementById("diary-link").hidden = !d.diary.enabled; }
      if (!d.program) { var m = text("message", d.message); m.hidden = false; return; }
      text("program-name", d.program.name);
      var done = d.exercises.filter(function (e) { return e.done_today; }).length;
      var total = d.exercises.length;
      if (total) {
        // width through the style object, not a style attribute, so the content security policy allows it
        document.getElementById("bar-fill").style.width = Math.round(done / total * 100) + "%";
        var bar = document.getElementById("bar");
        bar.setAttribute("aria-valuemax", String(total)); bar.setAttribute("aria-valuenow", String(done));
        text("complete", done + " of " + total + " complete");
        document.getElementById("plan").hidden = false;
      }
      text("week-done", d.week.done + " of " + d.week.planned);
      text("streak", String(d.streak_weeks));
      document.getElementById("week").hidden = false;
      var list = document.getElementById("exercises");
      var NS = "http://www.w3.org/2000/svg";
      d.exercises.forEach(function (e) {
        var li = document.createElement("li");
        li.className = e.done_today ? "done" : "todo";
        var check = document.createElement("span");
        check.className = "check";
        check.setAttribute("aria-label", e.done_today ? "Done today" : "To do");
        if (e.done_today) {
          var svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", "0 0 24 24");
          var tick = document.createElementNS(NS, "path");
          tick.setAttribute("d", "M5 12.5l4.5 4.5L19 7.5"); tick.setAttribute("fill", "none");
          tick.setAttribute("stroke", "#fff"); tick.setAttribute("stroke-width", "3");
          tick.setAttribute("stroke-linecap", "round"); tick.setAttribute("stroke-linejoin", "round");
          svg.appendChild(tick); check.appendChild(svg);
        }
        var name = document.createElement("span"); name.className = "name"; name.textContent = e.name;
        var amount = document.createElement("span"); amount.className = "amount"; amount.textContent = e.target_reps + " reps";
        li.appendChild(check); li.appendChild(name); li.appendChild(amount); list.appendChild(li);
      });
      (d.notes || []).forEach(function (n) {
        var li = document.createElement("li"); li.textContent = n; document.getElementById("notes").appendChild(li);
      });
      document.getElementById("start").hidden = d.exercises.length === 0;
      if (d.exercises.length) { document.getElementById("start").href = "/checkin?phase=before"; }
  }

  if (page === "today") {
    installHint();
    api("/api/today").then(function (res) {
      if (res.status === 401) { wipeLocal(); window.location.href = "/"; return; }
      store.set("limber.today", res.data);                 // the offline snapshot, this patient only
      renderToday(res.data);
    }).catch(function () {
      offlineBanner(true);                                  // the request itself failed: treat as offline
      var snap = store.get("limber.today");                // offline: show the plan as last seen
      if (snap) { renderToday(snap); } else { var m = text("message", "Not connected, and no plan saved on this phone yet."); m.hidden = false; }
    });
  }
}());
