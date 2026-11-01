// Limber exercise coach (feature 018 slice B): questions answered from the patient's own program.
// Rendering only. The server screens for red flags before anything else, and every card except an AI answer is
// set clinic text. Text is always placed with textContent, never as markup.
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var thread = $("thread"), form = $("ask"), box = $("question"), send = $("send"), error = $("ask-error");
  var erUrl = "", busy = false;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined) { e.textContent = text; }
    return e;
  }
  function api(path, options) {
    options = options || {};
    options.credentials = "same-origin";
    options.headers = { "Content-Type": "application/json" };
    return fetch(path, options).then(function (r) {
      if (r.status === 401) { window.location.href = "/"; return null; }
      return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; });
    });
  }
  function aiLabel() {
    var s = el("span", "from ai");
    var mark = el("span", "ai-mark", "AI"); mark.setAttribute("aria-hidden", "true");
    s.appendChild(mark); s.appendChild(document.createTextNode("AI assistant"));
    return s;
  }
  function mine(question) {
    var li = el("li", "msg-row me");
    li.appendChild(el("span", "from", "You"));
    var b = el("div", "bubble mine"); b.appendChild(el("p", "bubble-text", question));
    li.appendChild(b);
    thread.appendChild(li);
  }
  function answer(t) {
    var li = el("li", "msg-row them");
    li.appendChild(aiLabel());
    var b = el("div", "bubble aib");
    var cut = t.text.indexOf(". ");
    var p = el("p", "bubble-text");
    if (cut > 0) { p.appendChild(el("span", "b", t.text.slice(0, cut + 1))); p.appendChild(document.createTextNode(t.text.slice(cut + 1))); }
    else { p.textContent = t.text; }
    b.appendChild(p);
    if (t.exercise) { b.appendChild(el("p", "src", "From your program: " + t.exercise)); }
    li.appendChild(b);
    if (t.at) { li.appendChild(el("span", "meta", t.at.slice(11, 16))); }
    thread.appendChild(li);
  }
  function card(id) { return document.getElementById(id).content.firstElementChild.cloneNode(true); }
  function emergency() {
    var c = card("emergency-card");
    c.querySelector(".er-link").href = erUrl;
    thread.appendChild(c);
  }
  function referral(question) {
    var c = card("referral-card");
    c.querySelector(".message-link").href = "/messages?text=" + encodeURIComponent(question);
    thread.appendChild(c);
  }
  function setText(t) {
    var li = el("li", "msg-row them");
    li.appendChild(el("span", "from", "Set message from your clinic"));
    var b = el("div", "bubble aib"); b.appendChild(el("p", "bubble-text", t.text));
    if (t.kind === "off" || t.kind === "unavailable" || t.kind === "no_program") {
      var a = el("a", "plan-link", "Go to Messages"); a.href = "/messages"; b.appendChild(a);
    }
    li.appendChild(b);
    thread.appendChild(li);
  }
  function show(t) {
    mine(t.question);
    if (t.kind === "answer") { answer(t); }
    else if (t.kind === "emergency") { emergency(); }
    else if (t.kind === "referral") { referral(t.question); }
    else if (t.kind === "limit") { $("limit").hidden = false; }
    else { setText(t); }
  }
  function thinking() {
    var li = el("li", "msg-row them thinking");
    li.appendChild(aiLabel());
    var b = el("div", "bubble aib"); b.setAttribute("role", "status");
    var row = el("p", "think-row");
    var dots = el("span", "dots"); dots.setAttribute("aria-hidden", "true");
    dots.appendChild(el("i")); dots.appendChild(el("i")); dots.appendChild(el("i"));
    row.appendChild(dots); row.appendChild(el("span", "b", "Checking your program"));
    b.appendChild(row); b.appendChild(el("p", "xs", "This can take a few seconds."));
    li.appendChild(b);
    thread.appendChild(li);
    return li;
  }
  function limitReached(left) {
    $("limit").hidden = left > 0;
    form.hidden = left <= 0;
  }
  function refresh() { send.disabled = busy || !box.value.trim(); }

  function ask(question) {
    question = question.trim();
    if (!question || busy) { return; }
    busy = true; refresh(); error.hidden = true;
    $("empty").hidden = true;
    mine(question);
    var wait = thinking();
    wait.scrollIntoView({ block: "end" });
    api("/api/coach", { method: "POST", body: JSON.stringify({ question: question }) }).then(function (res) {
      thread.removeChild(wait);
      busy = false;
      if (!res) { return; }
      if (res.status !== 200) {
        thread.removeChild(thread.lastChild);
        error.textContent = res.data.error || "That didn't send. Try again."; error.hidden = false;
        refresh(); return;
      }
      box.value = "";
      var t = res.data; t.question = question;
      thread.removeChild(thread.lastChild);            // show() adds the question again with its answer
      show(t);
      if (t.kind === "off") { form.hidden = true; }
      limitReached(t.kind === "limit" ? 0 : t.left);
      refresh();
      thread.lastChild.scrollIntoView({ block: "end" });
    }).catch(function () {
      if (wait.parentNode) { thread.removeChild(wait); }
      busy = false;
      error.textContent = "The service cannot be reached right now."; error.hidden = false; refresh();
    });
  }

  box.addEventListener("input", refresh);
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(box.value); }
  });
  form.addEventListener("submit", function (e) { e.preventDefault(); ask(box.value); });

  api("/api/coach").then(function (res) {
    if (!res) { return; }
    var d = res.data;
    erUrl = d.er_url || "";
    $("coach-plan").textContent = d.plan || "";
    if (d.state !== "on") { $("coach-off").hidden = false; return; }
    $("coach-on").hidden = false;
    (d.turns || []).forEach(show);
    var empty = !(d.turns || []).length;
    $("empty").hidden = !empty;
    var list = $("suggestions");
    (d.suggestions || []).forEach(function (q) {
      var b = el("button", "secondary", q); b.type = "button"; b.setAttribute("role", "listitem");
      b.addEventListener("click", function () { ask(q); });
      list.appendChild(b);
    });
    limitReached(d.left);
    refresh();
  }).catch(function () {
    var e = $("load-error"); e.textContent = "The service cannot be reached right now."; e.hidden = false;
  });
})();
