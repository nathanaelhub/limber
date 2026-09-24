// Limber medication and sleep log. The medication choices come from the therapist through
// /api/today; both forms go through the shared entry queue, so they survive a lost connection.
(function () {
  "use strict";
  var picked = { item: null, quality: null };

  function el(id) { return document.getElementById(id); }
  function radios(group, values, label, onPick) {
    values.forEach(function (v) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "level-btn"; b.textContent = label(v);
      b.setAttribute("role", "radio"); b.setAttribute("data-value", String(v)); b.setAttribute("aria-checked", "false");
      b.addEventListener("click", function () {
        onPick(v);
        Array.prototype.forEach.call(group.children, function (x) {
          x.setAttribute("aria-checked", String(x.getAttribute("data-value") === String(v)));
        });
      });
      group.appendChild(b);
    });
  }
  function dayChoices(select, daysBack, todayLabel) {
    var now = new Date();
    for (var back = 0; back <= daysBack; back++) {
      var when = new Date(now.getTime() - back * 86400000);
      var o = document.createElement("option");
      o.value = back === 0 ? "" : window.limber.localIso(when);
      o.textContent = back === 0 ? todayLabel : back === 1 ? "Yesterday" : when.toDateString();
      select.appendChild(o);
    }
  }

  function send(kind, data, when, ids, confirm) {
    el(ids.error).hidden = true;
    var entry = { kind: kind, client_id: window.limber.uuid(), phase: "standalone", data: data };
    if (when) { entry.recorded_at = when; } else { entry.recorded_at = window.limber.localIso(new Date()); }
    if (confirm) { entry.confirm = true; }
    window.limber.sendEntry(entry).then(function (res) {
      if (res.queued) { saved(ids, "Saved on this phone. It will be sent when you are back online."); return; }
      if (res.status === 201 || res.status === 200) { saved(ids, "Saved. Thank you."); return; }
      if (res.status === 409) { el(ids.warn).textContent = res.data.error; el(ids.warn).hidden = false; el(ids.anyway).hidden = false; return; }
      if (res.status === 401) { window.location.href = "/"; return; }
      el(ids.error).textContent = res.data.error || "That could not be saved."; el(ids.error).hidden = false;
    });
  }
  function saved(ids, message) {
    el(ids.saved).textContent = message; el(ids.saved).hidden = false;
    el(ids.anyway).hidden = true;
    window.setTimeout(function () { el(ids.saved).hidden = true; }, 4000);
  }

  var MED = { error: "med-error", warn: "med-warn", saved: "med-saved", anyway: "med-anyway" };
  var SLEEP = { error: "sleep-error", warn: "sleep-warn", saved: "sleep-saved", anyway: "sleep-anyway" };

  function draw(d) {
    var list = (d.logs && d.logs.medications) || [];
    if (!list.length) {
      el("medication-none").hidden = false;
    } else {
      el("medication").hidden = false;
      radios(el("items"), list, function (v) { return v; }, function (v) { picked.item = v; });
      dayChoices(el("med-when"), 7, "Just now");
    }
    radios(el("quality"), [1, 2, 3, 4, 5], function (v) { return String(v); }, function (v) { picked.quality = v; });
    dayChoices(el("night"), 7, "Last night");
  }

  fetch("/api/today", { credentials: "same-origin" })
    .then(function (r) { if (r.status === 401) { window.location.href = "/"; return null; } return r.json(); })
    .then(function (d) { if (d) { draw(d); } })
    .catch(function () { draw({}); });                    // offline: sleep can still be logged and queued

  el("medication").addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (picked.item === null) { el("med-error").textContent = "Pick what you took."; el("med-error").hidden = false; return; }
    send("medication", { item: picked.item, note: el("med-note").value }, el("med-when").value, MED, false);
  });
  el("med-anyway").addEventListener("click", function () {
    send("medication", { item: picked.item, note: el("med-note").value }, el("med-when").value, MED, true);
  });
  el("sleep").addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (picked.quality === null) { el("sleep-error").textContent = "Say how well you slept."; el("sleep-error").hidden = false; return; }
    send("sleep", { hours: parseFloat(el("hours").value), quality: picked.quality, note: el("sleep-note").value },
         el("night").value, SLEEP, false);
  });
  el("sleep-anyway").addEventListener("click", function () {
    send("sleep", { hours: parseFloat(el("hours").value), quality: picked.quality, note: el("sleep-note").value },
         el("night").value, SLEEP, true);
  });
  ["med-note", "sleep-note"].forEach(function (id) {
    el(id).addEventListener("input", function () {
      var ids = id === "med-note" ? MED : SLEEP;
      el(ids.warn).hidden = true; el(ids.anyway).hidden = true;
    });
  });
}());
