// Limber guided session. The camera and the pose model run here, on the patient's device; only the 17
// body points per frame are sent. Rep counting, form feedback, exercise order, and targets all come
// from the service: this file only captures, sends, and draws.
(function () {
  "use strict";
  var RATE = 15;                                   // frames per second sent to the service
  var MODEL = "movenet-lightning-4";
  var EDGES = [[5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];
  var NOTICES = {
    low_rate: "Your device is running slowly. Close other apps if you can.",
    no_person: "I can't see you. Step back so your whole body is in view."
  };
  var video = document.getElementById("video"), canvas = document.getElementById("overlay");
  var ctx = canvas.getContext("2d");
  var detector = null, socket = null, running = false, busy = false, lastSent = 0, points = null;

  function el(id) { return document.getElementById(id); }
  function show(id) { ["intro", "live", "done"].forEach(function (s) { el(s).hidden = s !== id; }); }
  function fail(message) { var p = el("setup"); p.textContent = message; p.hidden = false; el("begin").disabled = false; }

  function render(state) {
    el("exercise").textContent = state.exercise;
    el("step").textContent = "Exercise " + state.index + " of " + state.total;
    el("reps").textContent = String(state.rep_count);
    el("target").textContent = String(state.target_reps);
    var form = el("form");
    form.hidden = !state.form_status;
    if (state.form_status) { form.textContent = "Form: " + state.form_status; form.className = "chip " + state.form_status; }
    var list = el("messages");
    while (list.firstChild) { list.removeChild(list.firstChild); }
    (state.form_messages || []).forEach(function (m) { var li = document.createElement("li"); li.textContent = m; list.appendChild(li); });
    el("feedback").textContent = state.set_complete ? "Target reached. Move on when you are ready." : (state.feedback || "");
    var notice = el("notice");
    notice.hidden = !state.notice;
    if (state.notice) { notice.textContent = NOTICES[state.notice] || ""; }
    el("next").hidden = state.index >= state.total;
  }

  function finish(message) {
    running = false;
    if (video.srcObject) { video.srcObject.getTracks().forEach(function (t) { t.stop(); }); }
    var s = message.summary || { exercises: [], total_reps: 0 };
    el("done-lead").textContent = s.total_reps + " reps recorded" +
      (s.avg_form_score != null ? " · average form " + Math.round(s.avg_form_score) + " out of 100" : "");
    var list = el("summary");
    s.exercises.forEach(function (e) {
      var li = document.createElement("li"); li.className = "done";
      var name = document.createElement("span"); name.className = "name"; name.textContent = e.name;
      var reps = document.createElement("span"); reps.className = "amount"; reps.textContent = e.reps + " reps";
      li.appendChild(name); li.appendChild(reps); list.appendChild(li);
    });
    show("done");
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!points) { return; }
    ctx.lineWidth = Math.max(3, canvas.width / 160); ctx.lineCap = "round"; ctx.strokeStyle = "#FFFFFF";
    EDGES.forEach(function (e) {
      var a = points[e[0]], b = points[e[1]];
      if (a.score > 0.3 && b.score > 0.3) { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
    });
    ctx.fillStyle = "#F2684A";
    points.forEach(function (p) {
      if (p.score > 0.3) { ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(4, canvas.width / 110), 0, Math.PI * 2); ctx.fill(); }
    });
  }

  function loop(now) {
    if (!running) { return; }
    window.requestAnimationFrame(loop);
    if (busy || now - lastSent < 1000 / RATE || video.readyState < 2) { return; }
    busy = true; lastSent = now;
    detector.estimatePoses(video, { flipHorizontal: false }).then(function (poses) {   // never flip: left must stay left
      points = poses.length ? poses[0].keypoints : null;
      var k = null;
      if (points) { k = []; points.forEach(function (p) { k.push(p.x, p.y, p.score == null ? 0 : p.score); }); }
      if (socket && socket.readyState === 1) {
        socket.send(JSON.stringify({ type: "frame", k: k, w: video.videoWidth, h: video.videoHeight }));
      }
      draw();
    }).catch(function () { points = null; }).then(function () { busy = false; });
  }

  function connect() {
    var scheme = window.location.protocol === "https:" ? "wss://" : "ws://";
    socket = new WebSocket(scheme + window.location.host + "/ws/session");
    socket.onopen = function () { socket.send(JSON.stringify({ type: "start", pose_model: MODEL })); };
    socket.onmessage = function (event) {
      var message = JSON.parse(event.data);
      if (message.type === "state") { if (!running) { running = true; show("live"); window.requestAnimationFrame(loop); } render(message); }
      else if (message.type === "ended") { finish(message); }
      else if (message.type === "refused") { running = false; show("intro"); fail(message.message || "A session cannot start right now."); }
    };
    socket.onclose = function () {
      if (running) { running = false; show("intro"); fail("The connection was lost. What you did so far is saved. You can start again."); }
    };
  }

  el("begin").addEventListener("click", function () {
    el("begin").disabled = true; el("setup").hidden = true;
    if (!window.poseDetection || !window.tf) { fail("Setup is incomplete on the Limber service (pose files are missing). Please tell your therapist."); return; }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { fail("This browser cannot use the camera here. Open Limber over a secure (https) address."); return; }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
      .then(function (stream) { video.srcObject = stream; return video.play(); })
      .then(function () {
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        return window.tf.setBackend("webgl").then(function () { return window.tf.ready(); });
      })
      .then(function () {
        return window.poseDetection.createDetector(window.poseDetection.SupportedModels.MoveNet, {
          modelType: window.poseDetection.movenet.modelType.SINGLEPOSE_LIGHTNING,
          modelUrl: "/static/vendor/lightning/model.json", enableSmoothing: false });
      })
      .then(function (d) { detector = d; connect(); })
      .catch(function (err) {
        fail(err && err.name === "NotAllowedError" ? "Camera access was not allowed. Allow the camera for this page and try again."
                                                   : "The camera or the pose model could not start on this device.");
      });
  });
  el("next").addEventListener("click", function () { if (socket) { socket.send(JSON.stringify({ type: "next" })); } });
  el("stop").addEventListener("click", function () { if (socket) { socket.send(JSON.stringify({ type: "stop" })); } });
  window.addEventListener("pagehide", function () { if (socket) { socket.close(); } });
}());
