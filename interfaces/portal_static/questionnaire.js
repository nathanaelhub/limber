// Limber questionnaire page. Every item, choice, and rule comes from the server; this file draws
// them, keeps half-finished answers on the phone so a interruption costs nothing, and sends the set
// through the shared entry queue so it survives a lost connection.
(function () {
  "use strict";
  var current = null;
  var answers = {};
  var KEY = "limber.questionnaire";

  function el(id) { return document.getElementById(id); }
  function saveDraft() {
    try { localStorage.setItem(KEY, JSON.stringify({ instrument: current.instrument, answers: answers })); } catch (e) {}
  }
  function clearDraft() { try { localStorage.removeItem(KEY); } catch (e) {} }
  function draft(instrument) {
    try {
      var kept = JSON.parse(localStorage.getItem(KEY));
      return kept && kept.instrument === instrument && kept.answers ? kept.answers : {};
    } catch (e) { return {}; }
  }

  function progress() {
    var done = Object.keys(answers).length;
    el("progress").textContent = done + " of " + current.item_count + " answered"
      + (done < current.minimum_answered ? " (at least " + current.minimum_answered + " needed)" : "");
  }

  function draw(q) {
    current = q;
    answers = draft(q.instrument);
    el("title").textContent = q.name;
    el("lead").textContent = q.meaning + " There are " + q.item_count + " questions, " + q.how_often + ".";
    if (q.notice) { el("notice").textContent = q.notice; el("notice").hidden = false; }
    var list = el("items");
    q.items.forEach(function (item) {
      var li = document.createElement("li");
      var text = document.createElement("p"); text.className = "question"; text.textContent = item.text;
      var group = document.createElement("div");
      group.className = "levels"; group.setAttribute("role", "radiogroup"); group.setAttribute("aria-label", item.text);
      item.choices.forEach(function (choice) {
        var b = document.createElement("button");
        b.type = "button"; b.className = "level-btn"; b.textContent = choice.text;
        b.setAttribute("role", "radio"); b.setAttribute("data-value", String(choice.value));
        b.setAttribute("aria-checked", String(answers[item.key] === choice.value));
        b.addEventListener("click", function () {
          answers[item.key] = choice.value;
          Array.prototype.forEach.call(group.children, function (x) {
            x.setAttribute("aria-checked", String(x.getAttribute("data-value") === String(choice.value)));
          });
          el("warn").hidden = true;
          saveDraft(); progress();
        });
        group.appendChild(b);
      });
      li.appendChild(text); li.appendChild(group); list.appendChild(li);
    });
    progress();
    el("questionnaire").hidden = false;
  }

  function send() {
    el("error").hidden = true;
    var done = Object.keys(answers).length;
    if (done < current.minimum_answered) {
      el("warn").textContent = "Please answer at least " + current.minimum_answered + " of the "
        + current.item_count + " questions.";
      el("warn").hidden = false;
      return;
    }
    el("save").disabled = true;
    window.limber.sendEntry({
      kind: "questionnaire", client_id: window.limber.uuid(), phase: "standalone", session_id: null,
      recorded_at: window.limber.localIso(new Date()),
      data: { instrument: current.instrument, answers: answers }
    }).then(function (res) {
      if (res.queued) { finish(null, "Saved on this phone. It will be sent when you are back online."); return; }
      if (res.status === 201 || res.status === 200) { finish(res.data, null); return; }
      if (res.status === 401) { window.location.href = "/"; return; }
      el("save").disabled = false;
      el("error").textContent = (res.data && res.data.error) || "Those answers could not be sent.";
      el("error").hidden = false;
    });
  }

  function finish(data, message) {
    clearDraft();
    el("questionnaire").hidden = true;
    el("done").hidden = false;
    if (data && data.score !== null && data.score !== undefined) {
      el("done-total").textContent = data.score + " " + current.unit;
      el("done-meaning").textContent = current.meaning
        + (current.direction === "higher_is_better" ? " A higher score is better." : " A higher score is worse.");
    } else {
      el("done-total").textContent = "Answers saved";
      el("done-meaning").textContent = message || "";
    }
    el("done-next").textContent = "Your therapist will see this with your sessions.";
  }

  fetch("/api/questionnaires", { credentials: "same-origin" })
    .then(function (r) { if (r.status === 401) { window.location.href = "/"; return null; } return r.json(); })
    .then(function (d) {
      if (!d) { return; }
      var params = new URLSearchParams(window.location.search);
      var wanted = params.get("instrument");
      var pick = (d.due || []).concat(d.assigned || []).filter(function (q) {
        return !wanted || q.instrument === wanted;
      })[0];
      if (!pick) { el("none").hidden = false; return; }
      draw(pick);
    })
    .catch(function () { el("none").hidden = false; el("none").textContent =
      "Not connected. Please open this again when you are back online."; });

  el("questionnaire").addEventListener("submit", function (ev) { ev.preventDefault(); send(); });
}());
