// Limber clip page: pick or record a video, upload it in parts (resumable), show progress, list and
// delete the patient's own clips. The service decides what the file is and whether it is accepted.
(function () {
  "use strict";
  var CHUNK = 4 * 1024 * 1024;
  var file = null, upload = null, pending = null;
  function el(id) { return document.getElementById(id); }
  function show(id, on) { el(id).hidden = !on; }
  function fail(msg) { el("error").textContent = msg; show("error", true); el("send").disabled = !file; }

  function sha256(blob) {
    return blob.arrayBuffer().then(function (buf) { return window.crypto.subtle.digest("SHA-256", buf); })
      .then(function (d) { return Array.prototype.map.call(new Uint8Array(d), function (b) { return ("0" + b.toString(16)).slice(-2); }).join(""); });
  }
  function api(method, path, body, raw) {
    var opts = { method: method, credentials: "same-origin", headers: {} };
    if (body !== undefined) { opts.body = raw ? body : JSON.stringify(body); opts.headers["Content-Type"] = raw ? "application/octet-stream" : "application/json"; }
    return fetch(path, opts).then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; }); });
  }
  function progress(done, total) {
    show("progress-wrap", true); show("progress-text", true);
    el("progress-fill").style.width = Math.round(100 * done / total) + "%";
    el("progress-text").textContent = "Sending part " + done + " of " + total;
  }
  function sendParts(up) {
    var total = up.total_parts, todo = [];
    for (var i = 0; i < total; i++) { if (up.received.indexOf(i) < 0) { todo.push(i); } }
    var sent = total - todo.length;
    function next() {
      if (!todo.length) { return Promise.resolve(); }
      var n = todo.shift();
      var part = file.slice(n * up.chunk_bytes, Math.min(file.size, (n + 1) * up.chunk_bytes));
      return api("PUT", "/api/uploads/" + up.id + "/parts/" + n, part, true).then(function (res) {
        if (res.status !== 200) { throw new Error(res.data.error || "A part failed to send."); }
        progress(++sent, total); return next();
      });
    }
    return next();
  }
  function finish(confirm) {
    return api("POST", "/api/uploads/" + upload.id + "/finish", { caption: el("caption").value, confirm: confirm }).then(function (res) {
      if (res.status === 201) { done(); return; }
      if (res.status === 409 && res.data.reasons) { pending = true; el("warn").textContent = res.data.error; show("warn", true); show("send-anyway", true); el("send").disabled = false; return; }
      if (res.status === 409) { return api("GET", "/api/uploads/" + upload.id).then(function (st) { return sendParts(st.data).then(function () { return finish(confirm); }); }); }
      upload = null; fail(res.data.error || "The video was not accepted.");
    });
  }
  function start(confirm) {
    show("error", false); el("send").disabled = true;
    if (upload) { return finish(confirm); }
    return sha256(file).then(function (digest) {
      return api("POST", "/api/uploads", { kind: "clip", total_bytes: file.size, sha256: digest, chunk_bytes: CHUNK });
    }).then(function (res) {
      if (res.status !== 201) { throw new Error(res.data.error || "The upload could not start."); }
      upload = res.data; progress(0, upload.total_parts);
      return sendParts(upload);
    }).then(function () { return finish(confirm); }).catch(function (err) {
      // a dropped connection: keep `upload` so the next Send resumes the missing parts
      fail((err && err.message) || "The connection was lost. Press Send to resume.");
    });
  }
  function done() {
    el("saved").textContent = "Sent. Your therapist will see it."; show("saved", true);
    show("progress-wrap", false); show("progress-text", false); show("warn", false); show("send-anyway", false);
    file = null; upload = null; el("file").value = ""; el("caption").value = ""; show("preview", false); show("file-name", false);
    el("send").disabled = true; loadList();
  }
  function loadList() {
    api("GET", "/api/media").then(function (res) {
      if (res.status === 401) { window.location.href = "/"; return; }
      var list = el("clips"); while (list.firstChild) { list.removeChild(list.firstChild); }
      if (!res.data.media.length) { var li0 = document.createElement("li"); li0.className = "todo"; li0.textContent = "No videos yet."; list.appendChild(li0); return; }
      res.data.media.forEach(function (m) {
        var li = document.createElement("li"); li.className = m.deleted ? "todo" : "done";
        var name = document.createElement("span"); name.className = "name";
        name.textContent = m.created_at.replace("T", " ") + (m.caption ? " · " + m.caption : "") + " · " + Math.round(m.duration) + " s";
        li.appendChild(name);
        if (m.deleted) { var gone = document.createElement("span"); gone.className = "amount"; gone.textContent = "removed"; li.appendChild(gone); }
        else {
          var st = document.createElement("span"); st.className = "amount"; st.textContent = m.reviewed ? "seen by your therapist" : "waiting"; li.appendChild(st);
          var play = document.createElement("a"); play.href = "/api/media/" + m.id; play.textContent = "Play"; play.className = "link-button"; li.appendChild(play);
          var del = document.createElement("button"); del.type = "button"; del.className = "link"; del.textContent = "Delete";
          del.addEventListener("click", function () { api("DELETE", "/api/media/" + m.id).then(loadList); });
          li.appendChild(del);
        }
        list.appendChild(li);
      });
    });
  }
  el("file").addEventListener("change", function () {
    file = el("file").files[0] || null; upload = null; pending = null;
    show("warn", false); show("send-anyway", false); show("error", false); show("saved", false);
    if (!file) { el("send").disabled = true; return; }
    el("file-name").textContent = Math.round(file.size / 1024 / 1024 * 10) / 10 + " MB"; show("file-name", true);
    el("preview").src = URL.createObjectURL(file); show("preview", true);
    el("send").disabled = false;
  });
  el("clip-form").addEventListener("submit", function (ev) { ev.preventDefault(); if (file) { start(false); } });
  el("send-anyway").addEventListener("click", function () { if (upload) { finish(true); } });
  el("caption").addEventListener("input", function () { show("warn", false); show("send-anyway", false); });
  loadList();
}());
