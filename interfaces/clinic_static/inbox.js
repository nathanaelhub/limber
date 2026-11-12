// Limber clinic Inbox (feature 019 slice 2). The server draws the page; this script does the writes.
// Nothing is marked read until a conversation is open, and an AI draft is never sent on its own.
"use strict";

(function () {
  const pane = document.querySelector("main.pane[data-patient]");
  if (!pane) return;
  const api = window.limber.api;
  const pid = pane.dataset.patient;
  const planId = pane.dataset.plan ? Number(pane.dataset.plan) : null;
  const base = "/api/inbox/" + encodeURIComponent(pid);
  const status = pane.querySelector("[data-status]");
  const pageError = pane.querySelector("[data-page-error]");
  const KEPT = "limber.keptReply";

  function say(text) { status.textContent = text; status.hidden = !text; }
  function fail(err) { pageError.textContent = err.message; pageError.hidden = false; }

  // Opening a conversation is what marks it read (FR-007): the page asks once it is shown.
  if (pane.dataset.markRead === "1") {
    api(base + "/read", { plan_id: planId }).catch(() => { /* stays unread; harmless */ });
  }

  // Buttons in the thread, the warning and the More menu.
  pane.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b || b.closest("form[data-reply]")) return;
    const act = b.dataset.act;
    if (b.dataset.confirm && !window.confirm(b.dataset.confirm)) return;
    b.disabled = true;
    try {
      if (act === "remove") await api(base + "/messages/" + b.dataset.id + "/remove", {});
      else if (act === "voice-heard") await api(base + "/voice/" + encodeURIComponent(b.dataset.id) + "/heard", {});
      else if (act === "voice-delete") await api(base + "/voice/" + encodeURIComponent(b.dataset.id) + "/delete", {});
      else if (act === "voice-text") await api(base + "/voice/" + encodeURIComponent(b.dataset.id) + "/text", {});
      else if (act === "handled") await api(base + "/handled", { plan_id: planId });
      else if (act === "messaging") await api(base + "/messaging", { enabled: b.dataset.on === "1" });
      else if (act === "answer") await answerVisit(b.closest("[data-visit]"));
      else { b.disabled = false; return; }
      location.reload();
    } catch (err) {
      b.disabled = false;
      const own = b.closest("[data-visit]");
      if (own) { const box = own.querySelector("[data-error]"); box.textContent = err.message; box.hidden = false; }
      else fail(err);
    }
  });

  async function answerVisit(card) {
    const answer = card.querySelector("input[name=answer]:checked").value;
    await api(base + "/visits/" + card.dataset.visit + "/answer", {
      answer,
      date: card.querySelector("input[name=date]").value,
      time: card.querySelector("input[name=time]").value,
      note: card.querySelector("input[name=note]").value,
    });
  }

  // ---- the reply box
  const form = pane.querySelector("form[data-reply]");
  if (!form) return;
  const box = form.elements.text;
  const aiTop = form.querySelector("[data-ai-top]");
  const warn = form.querySelector("[data-warn]");
  const error = form.querySelector("[data-error]");
  const picker = form.querySelector("[data-files]");
  const attached = form.querySelector("[data-attached]");
  const send = form.querySelector("button[type=submit]");
  let drafted = null;        // the AI draft's text while it is in the box
  let warnedText = null;     // the text the privacy warning was about
  let chosen = [];

  // A typed reply survives a sign-in that ends: it is kept in this tab only, for this conversation.
  const here = location.pathname + location.search;
  try {
    const kept = JSON.parse(sessionStorage.getItem(KEPT) || "null");
    if (kept && kept.path === here && kept.text) box.value = kept.text;
  } catch (_) { /* storage blocked */ }
  function keep() {
    try {
      if (box.value.trim()) sessionStorage.setItem(KEPT, JSON.stringify({ path: here, text: box.value }));
      else sessionStorage.removeItem(KEPT);
    } catch (_) { /* storage blocked */ }
  }

  function showAI(on) {
    aiTop.hidden = !on;
    form.classList.toggle("ai", on);
  }

  box.addEventListener("input", () => {
    keep();
    if (warnedText !== null && box.value !== warnedText) { warn.hidden = true; warnedText = null; }
  });

  form.querySelector("[data-act=discard]").addEventListener("click", () => {
    box.value = ""; drafted = null; showAI(false); keep(); box.focus();
  });

  const draftButton = form.querySelector("[data-act=draft]");
  if (draftButton) draftButton.addEventListener("click", async () => {
    if (box.value.trim() && !window.confirm("Replace what you have typed with an AI draft?")) return;
    draftButton.disabled = true;
    say("Drafting a reply. This takes a few seconds. Nothing is sent until you press Send.");
    try {
      const data = await api(base + "/draft", { plan_id: planId });
      if (data.state === "ok") {
        box.value = data.text; drafted = data.text; showAI(true); keep(); say("");
        box.focus();
      } else {
        say(data.notice);
      }
    } catch (err) { say(""); fail(err); }
    draftButton.disabled = false;
  });

  picker.addEventListener("change", () => {
    chosen = chosen.concat(Array.from(picker.files));
    picker.value = "";
    drawAttached();
  });
  function drawAttached() {
    attached.textContent = "";
    chosen.forEach((f, i) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = (f.type === "application/pdf" ? "PDF" : "Photo") + " · " + Math.max(1, Math.round(f.size / 1024)) + " KB";
      const x = document.createElement("button");
      x.type = "button";
      x.setAttribute("aria-label", "Remove " + f.name);
      x.textContent = "×";
      x.addEventListener("click", () => { chosen.splice(i, 1); drawAttached(); });
      chip.appendChild(x);
      attached.appendChild(chip);
    });
    attached.hidden = chosen.length === 0;
  }

  async function sendReply(confirm) {
    error.hidden = true;
    send.disabled = true;
    const fields = { plan_id: planId, text: box.value, confirm, from_draft: drafted !== null };
    try {
      if (chosen.length) await sendWithFiles(fields);
      else await api(base + "/reply", fields);
      try { sessionStorage.removeItem(KEPT); } catch (_) { /* storage blocked */ }
      location.reload();
    } catch (err) {
      send.disabled = false;
      if (err.data && err.data.needs_confirm) {
        warnedText = box.value;
        warn.querySelector("[data-warn-text]").textContent =
          "This reply looks like it holds a " + err.data.reasons.join(" and a ") +
          ". Messages here should not carry personal details.";
        warn.hidden = false;
      } else {
        error.textContent = err.message;
        error.hidden = false;
      }
    }
  }

  async function sendWithFiles(fields) {
    // The hosted demo takes files straight into its bucket; a local install takes them with the reply.
    const declared = chosen.map((f) => ({ type: f.type, size: f.size }));
    let links = null;
    try {
      links = (await api(base + "/uploads", { files: declared })).uploads;
    } catch (err) {
      if (!(err.message || "").includes("on this installation")) throw err;
    }
    if (links) {
      for (let i = 0; i < links.length; i++) {
        const put = await fetch(links[i].url, { method: "PUT", headers: { "Content-Type": links[i].type }, body: chosen[i] });
        if (!put.ok) throw new Error("A file did not upload. Please try again.");
      }
      await api(base + "/reply", Object.assign({ uploaded: links.map((l) => l.key) }, fields));
      return;
    }
    const data = new FormData();
    Object.entries(fields).forEach(([k, v]) => data.append(k, v === null ? "" : String(v)));
    chosen.forEach((f) => data.append("files", f));
    const r = await fetch("/therapist" + base + "/reply", { method: "POST", credentials: "same-origin", body: data });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(body.error || "That did not send. Try again."), { data: body });
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); sendReply(false); });
  form.querySelector("[data-act=send-anyway]").addEventListener("click", () => {
    if (warnedText !== null && box.value === warnedText) sendReply(true);
  });
})();
