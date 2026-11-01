// Limber messages page (features 008 and 017): one conversation per plan of care, with photos or a PDF.
// Rendering only; the server checks every file and refuses writes to an ended plan. Text is always placed
// with textContent, never as markup.
(function () {
  "use strict";
  var PHOTO_MAX = 15 * 1024 * 1024, PDF_MAX = 20 * 1024 * 1024, MAX_PHOTOS = 4;
  var $ = function (id) { return document.getElementById(id); };
  var list = $("thread"), form = $("compose"), box = $("text"), warn = $("warn"), error = $("compose-error");
  var switcher = $("plan-switcher"), tray = $("tray"), trayItems = $("tray-items"), sheet = $("add-sheet");
  var plans = [], current = null, shownKey = "", files = [], lastFocus = null;
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December"];
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }
  function getJson(path) {
    return fetch(path, { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) { window.location.href = "/"; return null; }
      return r.json().then(function (d) { return { status: r.status, data: d }; });
    });
  }
  function dayLabel(iso) {
    var d = new Date(iso.slice(0, 10) + "T12:00:00");
    var today = new Date(); today.setHours(12, 0, 0, 0);
    var diff = Math.round((today - d) / 86400000);
    if (diff === 0) { return "Today"; }
    if (diff === 1) { return "Yesterday"; }
    return DAYS[d.getDay()] + " " + d.getDate() + " " + MONTHS[d.getMonth()];
  }
  function longDate(iso) { var d = new Date(iso + "T12:00:00"); return d.getDate() + " " + MONTHS[d.getMonth()]; }
  function size(bytes) { return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB"; }

  // ---- plans ----
  function renderSwitcher() {
    while (switcher.firstChild) { switcher.removeChild(switcher.firstChild); }
    switcher.hidden = plans.length < 2;
    plans.forEach(function (p) {
      var b = el("button", "plan-chip");
      b.type = "button";
      b.setAttribute("aria-pressed", String(current && p.id === current.id));
      b.appendChild(el("span", "", p.title));
      if (p.read_only) { b.appendChild(el("span", "small", "· ended")); }
      if (p.unread) {
        var n = el("span", "cnt", String(p.unread));
        n.setAttribute("aria-label", p.unread + " new");
        b.appendChild(n);
      }
      b.addEventListener("click", function () { choose(p.id); });
      switcher.appendChild(b);
    });
  }
  function firstActive() { return plans.filter(function (p) { return !p.read_only; })[0]; }
  function choose(id) {
    current = plans.filter(function (p) { return p.id === id; })[0] || current;
    shownKey = "";
    clearTray(); box.value = ""; hideWarning(); error.hidden = true;
    try { history.replaceState(null, "", "/messages?plan=" + current.id); } catch (e) {}
    renderSwitcher();
    return loadThread();
  }
  function loadPlans() {
    return getJson("/api/plans").then(function (res) {
      if (!res) { return; }
      plans = res.data.plans || [];
      if (!current) {
        var wanted = Number(new URLSearchParams(window.location.search).get("plan"));
        current = plans.filter(function (p) { return p.id === wanted; })[0] ||
          plans.filter(function (p) { return !p.read_only && p.unread; })[0] || firstActive() || plans[0] || null;
      } else {
        current = plans.filter(function (p) { return p.id === current.id; })[0] || current;
      }
      renderSwitcher();
    });
  }

  // ---- the thread ----
  function attachmentsOf(m) {
    var wrap = el("div", "att");
    m.attachments.forEach(function (a, i) {
      if (a.deleted) { wrap.appendChild(el("span", "pdf small", a.kind === "photo" ? "Photo removed" : "PDF removed")); return; }
      var url = "/api/attachments/" + encodeURIComponent(a.id);
      if (a.kind === "photo") {
        var b = el("button", "thumb");
        b.type = "button";
        b.setAttribute("aria-label", "Open photo " + (i + 1) + " full size");
        var img = el("img"); img.src = url; img.alt = ""; img.loading = "lazy";
        b.appendChild(img);
        b.addEventListener("click", function () { openViewer(url, b); });
        wrap.appendChild(b);
      } else {
        var link = el("a", "pdf");
        link.href = url; link.target = "_blank"; link.rel = "noopener";
        link.appendChild(el("span", "fi", "PDF"));
        link.appendChild(el("span", "", "PDF · " + size(a.bytes)));
        wrap.appendChild(link);
      }
    });
    return wrap;
  }
  function render(d) {
    while (list.firstChild) { list.removeChild(list.firstChild); }
    var lastDay = "";
    d.messages.forEach(function (m) {
      var day = m.sent_at.slice(0, 10);
      if (day !== lastDay) { list.appendChild(el("li", "day", dayLabel(m.sent_at))); lastDay = day; }
      var mine = m.from === "you";
      var li = el("li", "msg-row " + (mine ? "me" : "them"));
      li.appendChild(el("span", "from", mine ? "You" : "Your therapist"));
      var bubble = el("div", "bubble " + (mine ? "mine" : "theirs") + (m.removed ? " removed" : ""));
      if (m.removed) {
        bubble.appendChild(el("p", "bubble-text", "This message was removed."));
      } else if (m.media_id) {                                 // a voice note the patient sent (feature 014)
        bubble.appendChild(el("p", "bubble-text", "Voice note"));
        var player = el("audio"); player.controls = true; player.preload = "none"; player.src = "/api/media/" + m.media_id;
        bubble.appendChild(player);
      } else if (m.text) {
        bubble.appendChild(el("p", "bubble-text", m.text));
      }
      if (bubble.childNodes.length) { li.appendChild(bubble); }
      if (!m.removed && m.attachments && m.attachments.length) { li.appendChild(attachmentsOf(m)); }
      li.appendChild(el("span", "meta", m.sent_at.slice(11, 16) + (mine && m.seen ? " · Seen" : "")));
      list.appendChild(li);
    });
    if (!d.messages.length) { list.appendChild(el("li", "day", "No messages in this plan yet.")); }
  }
  function loadThread() {
    if (!current) { $("messages-off").hidden = false; return Promise.resolve(); }
    return getJson("/api/plans/" + current.id + "/messages").then(function (res) {
      if (!res) { return; }
      if (res.status !== 200) { $("load-error").textContent = res.data.error || "Could not load this conversation."; $("load-error").hidden = false; return; }
      $("load-error").hidden = true;
      var d = res.data;
      $("messages-off").hidden = d.enabled;
      var ended = d.plan.read_only;
      form.hidden = !d.can_send;
      $("notice-alone").hidden = d.can_send;
      $("past-plan").hidden = !ended || !d.enabled;
      if (ended) {
        $("past-title").textContent = d.plan.end_date ? "This plan ended on " + longDate(d.plan.end_date) : "This plan has ended";
        var active = firstActive(), go = $("go-active");
        go.hidden = !active;
        if (active) { go.textContent = "Go to " + active.title; go.onclick = function () { choose(active.id); }; }
      }
      var key = current.id + ":" + d.messages.map(function (m) { return m.id + (m.seen ? "s" : "") + (m.removed ? "r" : ""); }).join(",");
      if (key !== shownKey) {
        render(d);
        shownKey = key;
        if (list.lastChild) { list.lastChild.scrollIntoView({ block: "nearest" }); }
      }
      if (current.unread) { current.unread = 0; renderSwitcher(); }  // opening it marked the therapist's messages read
    });
  }

  // ---- attachments tray ----
  function hasPdf() { return files.some(function (f) { return f.type === "application/pdf"; }); }
  function clearTray() {
    files.forEach(function (f) { if (f.preview) { URL.revokeObjectURL(f.preview); } });
    files = []; renderTray();
  }
  function renderTray() {
    while (trayItems.firstChild) { trayItems.removeChild(trayItems.firstChild); }
    tray.hidden = files.length === 0;
    var pdf = hasPdf(), photos = files.length;
    $("tray-count").textContent = pdf ? "1 PDF" : photos + " of " + MAX_PHOTOS + " photos";
    $("tray-more").textContent = pdf ? "" : (photos < MAX_PHOTOS ? "You can add " + (MAX_PHOTOS - photos) + " more" : "That's the most for one message");
    $("tray-rule").hidden = !pdf;
    var full = pdf || photos >= MAX_PHOTOS;
    $("add").disabled = full;
    $("add").setAttribute("aria-label", full ? (pdf ? "Add is off: one PDF per message" : "Add is off: 4 photos is the most")
                                            : "Add photos or a PDF");
    files.forEach(function (f, i) {
      var li = el("li", f.type === "application/pdf" ? "pdf" : "thumb");
      if (f.preview) { var img = el("img"); img.src = f.preview; img.alt = "Photo " + (i + 1); li.appendChild(img); }
      else if (f.type === "application/pdf") { li.appendChild(el("span", "fi", "PDF")); li.appendChild(el("span", "", f.name + " · " + size(f.size))); }
      else { li.appendChild(el("span", "heic", "Photo " + (i + 1))); }   // HEIC: browsers can't preview it; the host converts it
      var rm = el("button", "rm"); rm.type = "button";
      rm.setAttribute("aria-label", "Remove " + (f.preview ? "photo " + (i + 1) : f.name));
      rm.appendChild(el("span", "", "×"));
      rm.addEventListener("click", function () {
        if (f.preview) { URL.revokeObjectURL(f.preview); }
        files.splice(i, 1); renderTray(); box.focus();
      });
      li.appendChild(rm);
      trayItems.appendChild(li);
    });
  }
  function addFiles(chosen, kind) {
    error.hidden = true;
    var problem = null;
    Array.prototype.forEach.call(chosen, function (f) {
      if (problem) { return; }
      var isPdf = kind === "pdf";
      if (isPdf && files.length) { problem = "Attach one PDF on its own. Remove the photos first."; return; }
      if (!isPdf && hasPdf()) { problem = "One PDF per message. To add photos instead, remove the PDF."; return; }
      if (!isPdf && files.length >= MAX_PHOTOS) { problem = "You can attach up to 4 photos to a message."; return; }
      if (f.size > (isPdf ? PDF_MAX : PHOTO_MAX)) { problem = isPdf ? "A PDF can be up to 20 MB." : "Each photo can be up to 15 MB."; return; }
      var heic = /heic|heif/i.test(f.type) || /\.hei[cf]$/i.test(f.name);
      files.push({ file: f, name: f.name, size: f.size, type: isPdf ? "application/pdf" : (f.type || "image/heic"),
                   preview: isPdf || heic ? null : URL.createObjectURL(f) });
    });
    if (problem) { error.textContent = problem; error.hidden = false; }
    renderTray();
  }

  // ---- the add sheet and the photo viewer ----
  function openSheet(which, opener) { lastFocus = opener; which.hidden = false; var f = which.querySelector("label:not([hidden]), button"); if (f) { f.focus(); } }
  function closeSheet(which) { which.hidden = true; if (lastFocus) { lastFocus.focus(); } }
  function openViewer(url, opener) { $("viewer-img").src = url; openSheet($("viewer"), opener); $("viewer-close").focus(); }
  $("take-photo-row").hidden = !window.matchMedia("(pointer: coarse)").matches;   // a camera is offered on phones only
  $("add").addEventListener("click", function (e) { openSheet(sheet, e.currentTarget); });
  $("add-cancel").addEventListener("click", function () { closeSheet(sheet); });
  $("add-scrim").addEventListener("click", function () { closeSheet(sheet); });
  $("viewer-close").addEventListener("click", function () { closeSheet($("viewer")); });
  $("viewer-scrim").addEventListener("click", function () { closeSheet($("viewer")); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    if (!sheet.hidden) { closeSheet(sheet); } else if (!$("viewer").hidden) { closeSheet($("viewer")); }
  });
  [["take-photo", "photo"], ["pick-photos", "photo"], ["pick-pdf", "pdf"]].forEach(function (pair) {
    $(pair[0]).addEventListener("change", function (e) {
      addFiles(e.target.files, pair[1]); e.target.value = ""; closeSheet(sheet);
    });
  });

  // ---- sending ----
  function hideWarning() { warn.hidden = true; box.classList.remove("flagged"); }
  function send(confirm) {
    error.hidden = true;
    if (!box.value.trim() && !files.length) { error.textContent = "Write a message first."; error.hidden = false; return; }
    var options = { method: "POST", credentials: "same-origin" };
    if (files.length) {
      var data = new FormData();
      data.append("text", box.value);
      data.append("confirm", confirm ? "true" : "false");
      files.forEach(function (f) { data.append("files", f.file, f.name); });
      options.body = data;
    } else {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify({ text: box.value, confirm: confirm });
    }
    $("send").disabled = true;
    fetch("/api/plans/" + current.id + "/messages", options)
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; }); })
      .then(function (res) {
        $("send").disabled = false;
        if (res.status === 201) { box.value = ""; clearTray(); hideWarning(); return loadThread(); }
        if (res.status === 409 && res.data.archived) { return loadPlans().then(loadThread); }
        if (res.status === 409) {
          $("warn-text").textContent = res.data.error; warn.hidden = false; box.classList.add("flagged");
          $("send-anyway").focus();
          return null;
        }
        if (res.status === 401) { window.location.href = "/"; return null; }
        error.textContent = res.data.error || "The message could not be sent."; error.hidden = false;
        return null;
      })
      .catch(function () { $("send").disabled = false; error.textContent = "The service cannot be reached right now."; error.hidden = false; });
  }

  form.addEventListener("submit", function (event) { event.preventDefault(); send(false); });
  $("send-anyway").addEventListener("click", function () { send(true); });
  $("edit-message").addEventListener("click", function () { hideWarning(); box.focus(); });
  box.addEventListener("input", hideWarning);

  // From the coach's referral card (feature 018): the question is copied in, for the patient to change or send.
  function prefill() {
    var wanted = new URLSearchParams(window.location.search).get("text");
    if (!wanted || box.value) { return; }
    box.value = wanted.slice(0, 2000);
    try { history.replaceState(null, "", current ? "/messages?plan=" + current.id : "/messages"); } catch (e) {}
    if (!form.hidden) { box.focus(); }
  }

  loadPlans().then(loadThread).then(prefill);
  window.setInterval(function () { loadPlans().then(loadThread); }, 30000);
}());
