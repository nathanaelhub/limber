// Limber check-in page. Draws the form from the server's definitions, saves online, or queues
// offline and lets portal.js replay the queue. No scoring or rules live here.
(function () {
  "use strict";
  var AREAS = ["neck", "shoulder", "elbow", "wrist or hand", "back", "hip", "knee", "ankle or foot", "other"];
  var LEVELS = ["none", "mild", "moderate", "severe"];
  var params = new URLSearchParams(window.location.search);
  var phase = params.get("phase") === "before" || params.get("phase") === "after" ? params.get("phase") : "standalone";
  var sessionId = params.get("session") ? parseInt(params.get("session"), 10) : null;
  var picked = { pain: null, stiffness: "none", swelling: "none" };

  function el(id) { return document.getElementById(id); }
  function pick(group, key, value) {
    picked[key] = value;
    Array.prototype.forEach.call(group.children, function (b) { b.setAttribute("aria-checked", String(b.getAttribute("data-value") === String(value))); });
  }
  function buttons(group, values, key, cls) {
    values.forEach(function (v) {
      var b = document.createElement("button"); b.type = "button"; b.className = cls; b.textContent = v;
      b.setAttribute("role", "radio"); b.setAttribute("data-value", String(v)); b.setAttribute("aria-checked", "false");
      b.addEventListener("click", function () { pick(group, key, v); });
      group.appendChild(b);
    });
  }
  if (phase === "before") { el("checkin-title").textContent = "Before you start"; }
  if (phase === "after") { el("checkin-title").textContent = "How was that?"; el("checkin-lead").textContent = "One more check-in, then you are done."; }
  buttons(el("pain-scale"), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "pain", "scale-btn");
  AREAS.forEach(function (a) { var o = document.createElement("option"); o.value = a; o.textContent = a; el("area").appendChild(o); });
  buttons(el("stiffness"), LEVELS, "stiffness", "level-btn"); pick(el("stiffness"), "stiffness", "none");
  buttons(el("swelling"), LEVELS, "swelling", "level-btn"); pick(el("swelling"), "swelling", "none");

  function entry() {
    return { kind: "checkin", client_id: window.limber.uuid(), phase: phase, session_id: sessionId,
             recorded_at: window.limber.localIso(new Date()),
             data: { pain: picked.pain, area: el("area").value, stiffness: picked.stiffness, swelling: picked.swelling, note: el("note").value } };
  }

  function save(confirm) {
    el("error").hidden = true;
    if (picked.pain === null) { el("error").textContent = "Pick a pain score first."; el("error").hidden = false; return; }
    var e = entry(); if (confirm) { e.confirm = true; }
    window.limber.sendEntry(e).then(function (res) {
      if (res.queued) { done("Saved on this phone. It will be sent when you are back online."); return; }
      if (res.status === 201 || res.status === 200) { done("Saved. Thank you."); return; }
      if (res.status === 409) { el("warn").textContent = res.data.error; el("warn").hidden = false; el("save-anyway").hidden = false; return; }
      el("error").textContent = res.data.error || "The check-in could not be saved."; el("error").hidden = false;
    });
  }
  function done(message) {
    el("saved").textContent = message; el("saved").hidden = false;
    el("save").disabled = true; el("save-anyway").hidden = true;
    window.setTimeout(function () { window.location.href = phase === "before" && sessionId === null ? "/session" : "/today"; }, 1200);
  }
  el("checkin").addEventListener("submit", function (ev) { ev.preventDefault(); save(false); });
  el("save-anyway").addEventListener("click", function () { save(true); });
  el("note").addEventListener("input", function () { el("warn").hidden = true; el("save-anyway").hidden = true; });
}());
