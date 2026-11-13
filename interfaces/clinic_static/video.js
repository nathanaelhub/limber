// Limber clinic video analysis (feature 019 slice 6). The clip plays in this browser; MoveNet Lightning finds the
// body points every 1/15 s of clip time (as gate G2 measured); only those numbers are sent, in one request.
"use strict";

(function () {
  const form = document.querySelector("form[data-video]");
  if (!form) return;
  const video = document.querySelector("[data-clip]");
  const canvas = document.querySelector("[data-canvas]");
  const progress = form.querySelector("[data-progress]");
  const error = form.querySelector("[data-error]");
  const button = form.querySelector("button[type=submit]");
  const STEP = 1 / 15;
  const MAX_SECONDS = 15 * 60;
  let detector = null;

  function say(text) { progress.textContent = text; progress.hidden = !text; }
  function fail(text) { error.textContent = text; error.hidden = false; say(""); button.disabled = false; }

  async function ready() {
    if (detector) return detector;
    if (!window.tf || !window.poseDetection) throw new Error("The pose files are missing on this installation.");
    await tf.setBackend("webgl"); await tf.ready();
    detector = await poseDetection.createDetector(poseDetection.SupportedModels.MoveNet, {
      modelType: poseDetection.movenet.modelType.SINGLEPOSE_LIGHTNING,
      modelUrl: "/therapist/static/vendor/lightning/model.json", enableSmoothing: false });
    return detector;
  }

  function compact(kps) {
    return kps.flatMap(k => [Math.round(k.x * 10) / 10, Math.round(k.y * 10) / 10, Math.round(k.score * 100) / 100]);
  }

  async function points(file) {
    video.src = URL.createObjectURL(file);
    await new Promise((resolve, reject) => {
      video.addEventListener("loadeddata", resolve, { once: true });
      video.addEventListener("error", () => reject(new Error("This browser can't play that clip. Try an MP4.")), { once: true });
    });
    if (video.duration > MAX_SECONDS) throw new Error("This clip is longer than 15 minutes. Trim it and try again.");
    const det = await ready();
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    const frames = [];
    let next = 0;
    video.playbackRate = 0.5;            // slow enough for the model to keep up on a laptop
    await new Promise((resolve) => {
      const onFrame = async (_now, meta) => {
        if (meta.mediaTime + 1e-6 >= next) {
          ctx.drawImage(video, 0, 0);
          const poses = await det.estimatePoses(canvas, { flipHorizontal: false });
          const k = poses.length ? compact(poses[0].keypoints) : null;
          // Keep the 1/15 s timeline even if the player skipped ahead: the engine's timing depends on it.
          while (next <= meta.mediaTime + 1e-6) { frames.push(k); next += STEP; }
          say("Reading the clip: " + Math.min(99, Math.round(100 * meta.mediaTime / video.duration)) + "%");
        }
        if (!video.ended) video.requestVideoFrameCallback(onFrame);
      };
      video.addEventListener("ended", resolve, { once: true });
      video.requestVideoFrameCallback(onFrame);
      video.play();
    });
    URL.revokeObjectURL(video.src);
    return { w: video.videoWidth, h: video.videoHeight, frames };
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    error.hidden = true;
    const file = form.elements.clip.files[0];
    if (!file) { fail("Choose a clip first."); return; }
    button.disabled = true;
    const mode = (form.querySelector("input[name=mode]:checked") || form.elements.mode).value;
    if (mode === "yolo") {
      // A local install with the clinic model: the clip goes to this computer, is analysed, and is not kept.
      say("Analysing on this computer with the clinic model. A long clip can take a few minutes…");
      try {
        const data = new FormData();
        ["patient_id", "exercise", "label"].forEach((k) => data.append(k, form.elements[k].value));
        data.append("files", file);
        const r = await fetch("/therapist/api/video/yolo", { method: "POST", credentials: "same-origin", body: data });
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body.error || "The clip could not be analysed.");
        location.assign(body.redirect);
      } catch (err) { fail(err.message); }
      return;
    }
    say("Loading the pose model…");
    try {
      const found = await points(file);
      say("Counting reps and scoring form…");
      const target = form.elements.target_reps.value ? Number(form.elements.target_reps.value) : null;
      const data = await window.limber.api("/api/video", Object.assign({
        patient_id: form.elements.patient_id.value, exercise: form.elements.exercise.value,
        target_reps: target, label: form.elements.label.value, pose_model: "movenet-lightning-4" }, found));
      location.assign(data.redirect);
    } catch (err) {
      fail(err.message);
    }
  });
})();
