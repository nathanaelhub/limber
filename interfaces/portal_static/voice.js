// Limber voice-note page: record with the phone's microphone (or choose a recording), upload it in
// parts so a dropped connection resumes, and list the patient's own notes. The service decides what the
// file is and whether it is accepted; nothing here inspects audio.
(function () {
  "use strict";
  var CHUNK = 1024 * 1024;
  var recorder = null, chunks = [], file = null, upload = null, started = 0, ticker = null, limit = 180;

  function el(id) { return document.getElementById(id); }
  function show(id, on) { el(id).hidden = !on; }
  function fail(msg) { el("error").textContent = msg; show("error", true); }
  function clock(seconds) {
    var m = Math.floor(seconds / 60), s = Math.floor(seconds % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }
  function api(method, path, body, raw) {
    var opts = { method: method, credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      opts.body = raw ? body : JSON.stringify(body);
      opts.headers["Content-Type"] = raw ? "application/octet-stream" : "application/json";
    }
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) { return { status: r.status, data: d }; });
    });
  }
  function sha256(blob) {
    return blob.arrayBuffer().then(function (buf) { return window.crypto.subtle.digest("SHA-256", buf); })
      .then(function (d) {
        return Array.prototype.map.call(new Uint8Array(d), function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
      });
  }

  // ------------------------------------------------------------------ recording

  function stopTicking() { if (ticker) { window.clearInterval(ticker); ticker = null; } }

  function ready(blob) {
    file = blob;
    el("preview").src = URL.createObjectURL(blob);
    show("preview", true); show("after", true); show("record", false); show("stop", false);
    el("hint").textContent = "Listen back, then send it, or record again.";
  }

  function record() {
    show("error", false); show("saved", false);
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      fail("This phone's browser cannot record here. Use “Or choose a recording” instead.");
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = function (e) { if (e.data && e.data.size) { chunks.push(e.data); } };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        stopTicking();
        ready(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.start();
      started = Date.now();
      show("record", false); show("stop", true); show("timer", true); show("preview", false); show("after", false);
      el("hint").textContent = "Recording. Tap Stop when you are done.";
      ticker = window.setInterval(function () {
        var seconds = (Date.now() - started) / 1000;
        el("timer").textContent = clock(seconds);
        if (seconds >= limit) { stop(); }
      }, 250);
    }).catch(function () {
      fail("Limber could not use the microphone. Allow it in your phone's settings, or choose a recording instead.");
    });
  }
  function stop() { if (recorder && recorder.state !== "inactive") { recorder.stop(); } }

  // ------------------------------------------------------------------ sending

  function progress(done, total) {
    show("bar", true);
    el("bar-fill").style.width = Math.round(100 * done / total) + "%";
    el("bar").setAttribute("aria-valuenow", String(Math.round(100 * done / total)));
  }
  function sendParts(up) {
    var todo = [];
    for (var i = 0; i < up.total_parts; i++) { if (up.received.indexOf(i) < 0) { todo.push(i); } }
    var sent = up.total_parts - todo.length;
    function next() {
      if (!todo.length) { return Promise.resolve(); }
      var n = todo.shift();
      var part = file.slice(n * up.chunk_bytes, Math.min(file.size, (n + 1) * up.chunk_bytes));
      return api("PUT", "/api/uploads/" + up.id + "/parts/" + n, part, true).then(function (res) {
        if (res.status !== 200) { throw new Error((res.data && res.data.error) || "A part failed to send."); }
        progress(++sent, up.total_parts);
        return next();
      });
    }
    return next();
  }
  function finish() {
    return api("POST", "/api/uploads/" + upload.id + "/finish", {}).then(function (res) {
      if (res.status === 201) {
        upload = null; file = null;
        el("saved").textContent = "Sent. Your therapist will hear it.";
        show("saved", true); show("after", false); show("bar", false); show("preview", false);
        show("record", true); el("hint").textContent = "";
        load();
        return;
      }
      if (res.status === 409 && String(res.data.error || "").indexOf("missing part") >= 0) {
        return api("GET", "/api/uploads/" + upload.id).then(function (st) {
          return sendParts(st.data).then(finish);
        });
      }
      if (res.status === 401) { window.location.href = "/"; return; }
      upload = null;
      fail(res.data.error || "The voice note was not accepted.");
      el("send").disabled = false;
    });
  }
  function send() {
    if (!file) { return; }
    show("error", false); el("send").disabled = true;
    var work = upload ? Promise.resolve() : sha256(file).then(function (digest) {
      return api("POST", "/api/uploads", { kind: "voice", total_bytes: file.size, sha256: digest, chunk_bytes: CHUNK })
        .then(function (res) {
          if (res.status !== 201) { throw new Error((res.data && res.data.error) || "The upload could not start."); }
          upload = res.data;
          progress(0, upload.total_parts);
          return sendParts(upload);
        });
    });
    work.then(finish).catch(function (err) {
      // the upload row is kept, so pressing Send again resumes from the last part that arrived
      fail((err && err.message) || "The connection was lost. Press Send to try again.");
      el("send").disabled = false;
    });
  }

  // ------------------------------------------------------------------ the patient's own notes

  function load() {
    api("GET", "/api/media").then(function (res) {
      if (res.status === 401) { window.location.href = "/"; return; }
      var notes = (res.data.media || []).filter(function (m) { return m.kind === "voice"; });
      var list = el("notes");
      list.textContent = "";
      show("none", notes.length === 0);
      notes.forEach(function (m) {
        var li = document.createElement("li");
        var name = document.createElement("span");
        name.className = "name";
        name.textContent = m.created_at.replace("T", " ") + " · " + Math.round(m.duration) + "s"
          + (m.deleted ? " · removed" : (m.reviewed ? " · heard by your therapist" : ""));
        li.appendChild(name);
        if (!m.deleted) {
          var player = document.createElement("audio");
          player.controls = true; player.preload = "none"; player.src = "/api/media/" + m.id;
          li.appendChild(player);
          var del = document.createElement("button");
          del.type = "button"; del.className = "link"; del.textContent = "Delete";
          del.addEventListener("click", function () {
            api("DELETE", "/api/media/" + m.id).then(function (r) { if (r.status === 200) { load(); } });
          });
          li.appendChild(del);
        }
        list.appendChild(li);
      });
    }).catch(function () { show("none", true); });
  }

  fetch("/api/today", { credentials: "same-origin" })
    .then(function (r) { if (r.status === 401) { window.location.href = "/"; return null; } return r.json(); })
    .then(function (d) {
      if (!d) { return; }
      var options = d.voice || {};
      if (options.notice) { el("notice").textContent = options.notice; }
      if (options.max_seconds) { limit = options.max_seconds; }
      if (options.enabled === false) {
        show("off", true); show("recorder", false);
        return;
      }
      load();
    })
    .catch(function () { load(); });

  el("record").addEventListener("click", record);
  el("stop").addEventListener("click", stop);
  el("again").addEventListener("click", function () {
    file = null; upload = null; show("preview", false); show("after", false); show("bar", false);
    show("saved", false); show("record", true); el("timer").textContent = "0:00";
    el("hint").textContent = "Your phone will ask for permission to use the microphone.";
  });
  el("send").addEventListener("click", send);
  el("pick").addEventListener("change", function (e) {
    var chosen = e.target.files && e.target.files[0];
    if (chosen) { upload = null; ready(chosen); }
  });
}());
