// Limbr patient portal: sign-in and today's program. Rendering only; every rule lives on the server.
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
    });
  }
}());
