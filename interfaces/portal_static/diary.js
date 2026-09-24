// Limber "I did this without the camera" page. The options and every limit come from /api/today;
// this file only draws them and posts what the patient chose.
(function () {
  "use strict";
  var picked = { effort: null };
  var options = null;

  function el(id) { return document.getElementById(id); }
  function fail(message) { el("error").textContent = message; el("error").hidden = false; }

  function whenChoices(daysBack) {
    var select = el("done-at");
    var now = new Date();
    for (var back = 0; back <= daysBack; back++) {
      var when = new Date(now.getTime() - back * 86400000);
      var o = document.createElement("option");
      o.value = back === 0 ? "" : window.limber.localIso(when);      // today: let the server stamp it
      o.textContent = back === 0 ? "Just now" : back === 1 ? "Yesterday" : when.toDateString();
      select.appendChild(o);
    }
  }

  function draw(d) {
    options = d.diary;
    el("notice").textContent = options.notice;
    if (!options.enabled) {
      el("off").hidden = false; el("diary").hidden = true; return;
    }
    options.exercises.forEach(function (e) {
      var o = document.createElement("option");
      o.value = e.key; o.textContent = e.in_program ? e.name + " (in your program)" : e.name;
      el("exercise").appendChild(o);
    });
    options.effort.forEach(function (pair) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "level-btn"; b.textContent = pair[0] + " " + pair[1];
      b.setAttribute("role", "radio"); b.setAttribute("data-value", String(pair[0])); b.setAttribute("aria-checked", "false");
      b.addEventListener("click", function () {
        picked.effort = pair[0];
        Array.prototype.forEach.call(el("effort").children, function (x) {
          x.setAttribute("aria-checked", String(x.getAttribute("data-value") === String(pair[0])));
        });
      });
      el("effort").appendChild(b);
    });
    whenChoices(options.days_back);
  }

  function save(confirm) {
    el("error").hidden = true;
    if (picked.effort === null) { fail("Say how hard it felt."); return; }
    var body = { exercise: el("exercise").value, reps: parseInt(el("reps").value, 10),
                 sets: parseInt(el("sets").value, 10), effort: picked.effort, note: el("note").value };
    if (el("done-at").value) { body.done_at = el("done-at").value; }
    if (confirm) { body.confirm = true; }
    fetch("/api/diary", { method: "POST", headers: { "Content-Type": "application/json" },
                          credentials: "same-origin", body: JSON.stringify(body) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (data) { return { status: r.status, data: data }; }); })
      .then(function (res) {
        if (res.status === 201) {
          el("saved").textContent = "Logged: " + res.data.summary + ". " + options.marked_as + ".";
          el("saved").hidden = false; el("save").disabled = true; el("save-anyway").hidden = true;
          window.setTimeout(function () { window.location.href = "/today"; }, 1400);
          return;
        }
        if (res.status === 409) { el("warn").textContent = res.data.error; el("warn").hidden = false; el("save-anyway").hidden = false; return; }
        if (res.status === 401) { window.location.href = "/"; return; }
        fail(res.data.error || "That could not be logged.");
      })
      .catch(function () { fail("Not connected. Logging needs a connection; please try again later."); });
  }

  fetch("/api/today", { credentials: "same-origin" })
    .then(function (r) { if (r.status === 401) { window.location.href = "/"; return null; } return r.json(); })
    .then(function (d) { if (d) { draw(d); } })
    .catch(function () { fail("Not connected. Logging needs a connection; please try again later."); });

  el("diary").addEventListener("submit", function (ev) { ev.preventDefault(); save(false); });
  el("save-anyway").addEventListener("click", function () { save(true); });
  el("note").addEventListener("input", function () { el("warn").hidden = true; el("save-anyway").hidden = true; });
}());
