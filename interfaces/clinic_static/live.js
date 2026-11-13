// Limber clinic live session (feature 019 slice 7). The camera and MoveNet run here; only the 17 body points per
// frame are sent, 15 times a second. Counting, form and the record all happen on the service.
"use strict";

(function () {
  const setup = document.querySelector("form[data-live-setup]");
  if (!setup) return;
  const RATE = 15, MODEL = "movenet-lightning-4";
  const EDGES = [[5, 7], [7, 9], [6, 8], [8, 10], [5, 6], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];
  const NOTICES = { low_rate: "This computer is running slowly; counting may lag.",
                    no_person: "No one in view. The patient's whole body should be in the picture." };
  const q = (s) => document.querySelector(s);
  const liveBox = q("[data-live]"), done = q("[data-done]"), error = setup.querySelector("[data-error]");
  const video = q("[data-cam]"), overlay = q("[data-overlay]"), ctx = overlay.getContext("2d");
  let detector = null, socket = null, running = false, busy = false, lastSent = 0, points = null;
  let patient = null, sessionId = null;

  function fail(text) { error.textContent = text; error.hidden = false; setup.querySelector("button").disabled = false; }

  function render(s) {
    sessionId = s.session_id || sessionId;
    q("[data-exercise]").textContent = s.exercise;
    q("[data-reps]").textContent = String(s.rep_count);
    q("[data-target]").textContent = s.target_reps ? String(s.target_reps) : "—";
    q("[data-angle]").textContent = s.angle == null ? "—" : s.angle + "°";
    q("[data-phase]").textContent = s.set_complete ? "Target reached" : (s.feedback || s.phase || "");
    q("[data-form]").textContent = s.form_status ? "Form: " + s.form_status : "";
    const list = q("[data-messages]");
    list.textContent = "";
    (s.form_messages || []).forEach((m) => { const li = document.createElement("li"); li.textContent = m; list.append(li); });
    const notice = q("[data-notice]");
    notice.hidden = !s.notice;
    notice.textContent = s.notice ? (NOTICES[s.notice] || "") : "";
  }

  function draw() {
    overlay.width = video.videoWidth; overlay.height = video.videoHeight;
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!points) return;
    ctx.lineWidth = Math.max(3, overlay.width / 160); ctx.lineCap = "round"; ctx.strokeStyle = "#FFFFFF";
    EDGES.forEach(([i, j]) => {
      const a = points[i], b = points[j];
      if (a.score > 0.3 && b.score > 0.3) { ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); }
    });
    ctx.fillStyle = "#F2684A";
    points.forEach((p) => { if (p.score > 0.3) { ctx.beginPath(); ctx.arc(p.x, p.y, Math.max(4, overlay.width / 110), 0, Math.PI * 2); ctx.fill(); } });
  }

  function loop(now) {
    if (!running) return;
    requestAnimationFrame(loop);
    if (busy || now - lastSent < 1000 / RATE || video.readyState < 2) return;
    busy = true; lastSent = now;
    detector.estimatePoses(video, { flipHorizontal: false }).then((poses) => {   // never flip: left stays left
      points = poses.length ? poses[0].keypoints : null;
      const k = points ? points.flatMap((p) => [p.x, p.y, p.score == null ? 0 : p.score]) : null;
      if (socket && socket.readyState === 1) {
        socket.send(JSON.stringify({ type: "frame", k, w: video.videoWidth, h: video.videoHeight }));
      }
      draw();
    }).catch(() => { points = null; }).then(() => { busy = false; });
  }

  function finish(message) {
    running = false;
    if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
    const s = message.summary || { exercises: [], total_reps: 0 };
    q("[data-done-lead]").textContent = s.total_reps + " reps recorded" +
      (s.avg_form_score != null ? " · average form " + Math.round(s.avg_form_score) + " of 100" : "");
    const list = q("[data-summary]");
    s.exercises.forEach((e) => { const li = document.createElement("li"); li.textContent = e.name + ": " + e.reps + " reps"; list.append(li); });
    q("[data-log]").href = "/therapist/logs/" + (message.session_id || sessionId);
    liveBox.hidden = true; done.hidden = false;
  }

  // A hosted service may end a connection after a few minutes (feature 020). It says "segment" first, between
  // reps; the page reconnects and resumes the same session.
  function connect(first) {
    const scheme = location.protocol === "https:" ? "wss://" : "ws://";
    let segment = null;
    socket = new WebSocket(scheme + location.host + "/therapist/ws/live");
    socket.onopen = () => socket.send(JSON.stringify(first));
    socket.onmessage = (event) => {
      const m = JSON.parse(event.data);
      if (m.type === "state") {
        if (!running) { running = true; setup.hidden = true; liveBox.hidden = false; requestAnimationFrame(loop); }
        render(m);
      } else if (m.type === "segment") { segment = m.session_id; }
      else if (m.type === "ended") { finish(m); }
      else if (m.type === "refused") { running = false; fail(m.message || "The session could not start."); }
    };
    socket.onclose = () => {
      if (segment && running) { connect({ type: "resume", patient_id: patient, session_id: segment, pose_model: MODEL }); return; }
      if (running) { running = false; fail("The connection was lost. What was recorded is saved; start again to continue."); setup.hidden = false; liveBox.hidden = true; }
    };
  }

  function send(message) { if (socket && socket.readyState === 1) socket.send(JSON.stringify(message)); }

  setup.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    setup.querySelector("button").disabled = true;
    patient = setup.elements.patient_id.value;
    try {
      if (!window.tf || !window.poseDetection) throw new Error("The pose files are missing on this installation.");
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: setup.elements.camera.value,
        width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
      video.srcObject = stream; await video.play();
      await tf.setBackend("webgl"); await tf.ready();
      detector = detector || await poseDetection.createDetector(poseDetection.SupportedModels.MoveNet, {
        modelType: poseDetection.movenet.modelType.SINGLEPOSE_LIGHTNING,
        modelUrl: "/therapist/static/vendor/lightning/model.json", enableSmoothing: false });
      const target = setup.elements.target_reps.value ? Number(setup.elements.target_reps.value) : null;
      connect({ type: "start", patient_id: patient, exercise: setup.elements.exercise.value, target_reps: target,
                pose_model: MODEL });
    } catch (err) {
      fail(err && err.name === "NotAllowedError" ? "Camera access was not allowed. Allow it for this page and try again."
                                                   : (err.message || "The camera could not start."));
    }
  });

  liveBox.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const act = b.dataset.act;
    if (act === "switch") send({ type: "switch", exercise: q("[name=switch_to]").value });
    else if (act === "reset") send({ type: "reset" });
    else if (act === "target") { const n = Number(q("[name=new_target]").value); if (n) send({ type: "target", target_reps: n }); }
    else if (act === "stop") send({ type: "stop" });
    else if (act === "shot") {
      const shot = document.createElement("canvas");
      shot.width = video.videoWidth; shot.height = video.videoHeight;
      const c = shot.getContext("2d"); c.drawImage(video, 0, 0); c.drawImage(overlay, 0, 0);
      shot.toBlob((blob) => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "limber-live-" + patient + "-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".png";
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      }, "image/png");
    }
  });
})();
