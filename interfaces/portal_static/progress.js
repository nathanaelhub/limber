// Limber progress page: draws what /api/progress returns. Home and clinic sessions are separate series.
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var LABEL = { clinic: "In the clinic", home: "At home" };

  function node(tag, cls, text) { var e = document.createElement(tag); if (cls) { e.className = cls; } if (text != null) { e.textContent = text; } return e; }
  function svg(tag, attrs) { var e = document.createElementNS(NS, tag); Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); }); return e; }

  function chart(points, goal) {
    var W = 320, H = 120, pad = 14;
    var values = points.map(function (p) { return p.avg_rom; }).filter(function (v) { return v != null; });
    if (goal) { values.push(goal); }
    var lo = Math.min.apply(null, values) - 5, hi = Math.max.apply(null, values) + 5;
    var x = function (i) { return points.length === 1 ? W / 2 : pad + i * (W - 2 * pad) / (points.length - 1); };
    var y = function (v) { return H - pad - (v - lo) * (H - 2 * pad) / (hi - lo || 1); };
    var root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Range of motion by session", "class": "chart" });
    if (goal) {
      root.appendChild(svg("line", { x1: pad, x2: W - pad, y1: y(goal), y2: y(goal), stroke: "#F2684A", "stroke-width": 2, "stroke-dasharray": "5 5" }));
    }
    var path = "";
    points.forEach(function (p, i) { if (p.avg_rom != null) { path += (path ? " L" : "M") + x(i) + " " + y(p.avg_rom); } });
    root.appendChild(svg("path", { d: path, fill: "none", stroke: "#0E6B64", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" }));
    points.forEach(function (p, i) { if (p.avg_rom != null) { root.appendChild(svg("circle", { cx: x(i), cy: y(p.avg_rom), r: 4.5, fill: "#0E6B64" })); } });
    return root;
  }

  function signed(v, unit) { return (v > 0 ? "+" : "") + v + unit; }

  fetch("/api/progress", { credentials: "same-origin" }).then(function (r) {
    if (r.status === 401) { window.location.href = "/"; return null; }
    return r.json();
  }).then(function (d) {
    if (!d) { return; }
    if (d.message) { var m = document.getElementById("progress-message"); m.textContent = d.message; m.hidden = false; }
    var host = document.getElementById("progress");
    d.exercises.forEach(function (e) {
      var box = node("section", "progress-exercise");
      box.appendChild(node("h2", null, e.name));
      if (e.goal) { box.appendChild(node("p", "goal", e.goal.sentence + " · " + e.goal.percent + "% (" + LABEL[e.goal.recorded].toLowerCase() + ")")); }
      Object.keys(e.series).forEach(function (origin) {
        var points = e.series[origin], latest = points[points.length - 1];
        box.appendChild(node("h3", null, LABEL[origin] + " · " + points.length + (points.length === 1 ? " session" : " sessions")));
        box.appendChild(chart(points, e.goal && e.goal.recorded === origin ? e.goal.target_rom : null));
        var line = "Latest: " + (latest.avg_rom != null ? latest.avg_rom + "° range of motion, " : "") +
                   (latest.avg_form != null ? "form " + Math.round(latest.avg_form) + " out of 100" : "");
        var change = e.change[origin];
        if (change) { line += " · since your first: " + signed(change.avg_rom, "°") + ", form " + signed(change.avg_form, ""); }
        box.appendChild(node("p", "muted", line));
      });
      if (e.message) { box.appendChild(node("p", "small", e.message)); }
      host.appendChild(box);
    });
    if (d.pain && d.pain.series.length) {
      var box = node("section", "progress-exercise");
      box.appendChild(node("h2", null, "Pain"));
      var pts = d.pain.series.map(function (p) { return { avg_rom: p.pain }; });
      var W = 320, H = 120, pad = 14;
      var x = function (i) { return pts.length === 1 ? W / 2 : pad + i * (W - 2 * pad) / (pts.length - 1); };
      var y = function (v) { return H - pad - v * (H - 2 * pad) / 10; };
      var root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Pain by check-in, 0 to 10", "class": "chart" });
      var path = "";
      pts.forEach(function (p, i) { path += (path ? " L" : "M") + x(i) + " " + y(p.avg_rom); });
      root.appendChild(svg("path", { d: path, fill: "none", stroke: "#F2684A", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" }));
      pts.forEach(function (p, i) { root.appendChild(svg("circle", { cx: x(i), cy: y(p.avg_rom), r: 4.5, fill: "#F2684A" })); });
      box.appendChild(node("h3", null, d.pain.series.length + (d.pain.series.length === 1 ? " check-in" : " check-ins")));
      box.appendChild(root);
      var last = d.pain.series[d.pain.series.length - 1];
      box.appendChild(node("p", "muted", "Latest: " + last.pain + " out of 10 on " + last.date));
      box.appendChild(node("p", "small", d.pain.definition.name + " (" + d.pain.definition.unit + "): " + d.pain.definition.meaning));
      host.appendChild(box);
    }
    if (d.exercises.length) { document.getElementById("progress-note").textContent = d.note; }
    var defs = document.getElementById("definitions");
    Object.keys(d.definitions).forEach(function (k) {
      var def = d.definitions[k];
      defs.appendChild(node("dt", null, def.name + " (" + def.unit + ")"));
      defs.appendChild(node("dd", null, def.meaning));
    });
  });
}());
