// PT Assist patient portal: sign-in and today's program. Rendering only; every rule lives on the server.
(function () {
  "use strict";
  var page = document.body.getAttribute("data-page");

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
      api("/api/logout", { method: "POST", body: "{}" }).then(function () { window.location.href = "/"; });
    });
  }

  if (page === "signin") {
    document.getElementById("signin").addEventListener("submit", function (event) {
      event.preventDefault();
      var error = document.getElementById("error");
      error.hidden = true;
      api("/api/login", { method: "POST", body: JSON.stringify({ code: document.getElementById("code").value }) })
        .then(function (res) {
          if (res.status === 200) { window.location.href = "/today"; return; }
          error.textContent = res.data.error || "Sign-in is not available right now.";
          error.hidden = false;
        })
        .catch(function () { error.textContent = "The service cannot be reached right now."; error.hidden = false; });
    });
  }

  if (page === "today") {
    api("/api/today").then(function (res) {
      if (res.status === 401) { window.location.href = "/"; return; }
      var d = res.data;
      text("patient-id", d.patient_id);
      if (!d.program) { var m = text("message", d.message); m.hidden = false; return; }
      text("program-name", d.program.name);
      text("week-done", d.week.done + " of " + d.week.planned);
      text("streak", String(d.streak_weeks));
      document.getElementById("week").hidden = false;
      var list = document.getElementById("exercises");
      d.exercises.forEach(function (e) {
        var li = document.createElement("li");
        var name = document.createElement("span");
        name.textContent = e.name + " · " + e.target_reps + " reps";
        var state = document.createElement("span");
        state.className = e.done_today ? "done" : "todo";
        state.textContent = e.done_today ? "Done today" : "To do";
        li.appendChild(name); li.appendChild(state); list.appendChild(li);
      });
      (d.notes || []).forEach(function (n) {
        var li = document.createElement("li"); li.textContent = n; document.getElementById("notes").appendChild(li);
      });
      document.getElementById("start").hidden = d.exercises.length === 0;
    });
  }
}());
