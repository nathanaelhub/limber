// Limber messages page: shows the patient's own conversation and sends plain text. Text is always
// placed with textContent, never as markup.
(function () {
  "use strict";
  var list = document.getElementById("thread"), form = document.getElementById("compose");
  var box = document.getElementById("text"), warn = document.getElementById("warn");
  var anyway = document.getElementById("send-anyway"), error = document.getElementById("compose-error");
  var shown = 0;

  function bubble(m) {
    var li = document.createElement("li");
    li.className = "bubble " + (m.from === "you" ? "mine" : "theirs") + (m.removed ? " removed" : "");
    var text = document.createElement("p"); text.className = "bubble-text";
    text.textContent = m.removed ? "This message was removed." : m.text;
    var meta = document.createElement("p"); meta.className = "bubble-meta";
    meta.textContent = (m.from === "you" ? "You" : "Your therapist") + " · " + m.sent_at.replace("T", " ");
    li.appendChild(text); li.appendChild(meta);
    return li;
  }

  function load() {
    return fetch("/api/messages", { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) { window.location.href = "/"; return null; }
      return r.json();
    }).then(function (d) {
      if (!d) { return; }
      document.getElementById("messages-off").hidden = d.enabled;
      form.hidden = !d.enabled;
      if (d.messages.length !== shown) {
        while (list.firstChild) { list.removeChild(list.firstChild); }
        d.messages.forEach(function (m) { list.appendChild(bubble(m)); });
        shown = d.messages.length;
        if (list.lastChild) { list.lastChild.scrollIntoView({ block: "nearest" }); }
      }
    });
  }

  function send(confirm) {
    error.hidden = true;
    fetch("/api/messages", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
                             body: JSON.stringify({ text: box.value, confirm: confirm }) })
      .then(function (r) { return r.json().then(function (d) { return { status: r.status, data: d }; }); })
      .then(function (res) {
        if (res.status === 201) { box.value = ""; warn.hidden = true; anyway.hidden = true; return load(); }
        if (res.status === 409) { warn.textContent = res.data.error; warn.hidden = false; anyway.hidden = false; return null; }
        error.textContent = res.data.error || "The message could not be sent."; error.hidden = false;
        return null;
      })
      .catch(function () { error.textContent = "The service cannot be reached right now."; error.hidden = false; });
  }

  form.addEventListener("submit", function (event) { event.preventDefault(); send(false); });
  anyway.addEventListener("click", function () { send(true); });
  box.addEventListener("input", function () { warn.hidden = true; anyway.hidden = true; });
  load();
  window.setInterval(load, 30000);
}());
