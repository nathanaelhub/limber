// Limber clinic weekly summary (feature 019 slice 3b). The summary is drawn with textContent only: model text is
// never markup. Nothing is saved until the therapist presses Save, and the patient never sees it.
"use strict";

(function () {
  const box = document.querySelector("[data-summary]");
  if (!box) return;
  const api = window.limber.api;
  const pid = box.dataset.patient;
  const base = "/api/patients/" + encodeURIComponent(pid);
  const start = box.querySelector("[data-act=summarise]");
  const idle = box.querySelector("[data-idle]");
  const busy = box.querySelector("[data-busy]");
  const notice = box.querySelector("[data-notice]");
  const out = box.querySelector("[data-result]");

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function button(label, cls, onClick) {
    const b = el("button", cls, label);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }

  start.addEventListener("click", async () => {
    start.disabled = true; idle.hidden = true; notice.hidden = true; out.hidden = true; busy.hidden = false;
    try {
      const data = await api(base + "/summary", {});
      busy.hidden = true;
      if (data.state !== "ok") {
        notice.querySelector("[data-notice-title]").textContent = data.title;
        notice.querySelector("[data-notice-text]").textContent = data.text;
        notice.hidden = false;
        start.disabled = false;
        start.lastChild.textContent = "Try again";
        return;
      }
      draw(data);
    } catch (err) {
      busy.hidden = true;
      notice.querySelector("[data-notice-title]").textContent = "That did not work";
      notice.querySelector("[data-notice-text]").textContent = err.message;
      notice.hidden = false;
      start.disabled = false;
    }
  });

  function draw(data) {
    out.textContent = "";
    const label = el("span", "ai-label");
    label.append(el("span", "ai-tag", "AI"), document.createTextNode("AI-drafted — check before acting"));
    out.append(label, el("p", "small dim", data.window.from + " to " + data.window.to + " · from " +
                         data.record_count + " records"));
    const view = el("div", "stack");
    data.sections.forEach((s) => {
      const part = el("div", "stack tight");
      part.append(el("h3", "", s.heading), el("p", "pre", s.text), el("p", "micro dim", s.from));
      view.append(part);
    });
    if (data.next_steps.length) {
      const steps = el("div", "stack tight");
      steps.append(el("h3", "", "Suggested next steps"));
      data.next_steps.forEach((s, i) => {
        steps.append(el("p", "pre", (i + 1) + ". " + s.text), el("p", "micro dim", s.from));
      });
      view.append(steps);
    }
    if (data.dropped) {
      view.append(el("p", "small dim", data.dropped + " statement" + (data.dropped === 1 ? "" : "s") +
                     " left out because they did not point to a record."));
    }
    const editor = el("textarea", "input summary-edit");
    editor.value = data.note;
    editor.hidden = true;
    editor.setAttribute("aria-label", "Edit the summary before saving it");
    const error = el("p", "error-text");
    error.hidden = true;
    error.setAttribute("role", "alert");
    const actions = el("div", "rowflex");
    const save = button("Save as session note", "btn", async () => {
      save.disabled = true;
      const body = editor.hidden ? data.note : editor.value;
      try {
        await api(base + "/notes", { body, ai_drafted: true, original: data.note });
        out.textContent = "";
        const done = el("p", "rowflex", "Saved as a session note. It keeps the AI-drafted label.");
        const link = el("a", "", "Open session notes");
        link.href = "/therapist/patients/" + encodeURIComponent(pid) + "/notes";
        out.append(done, link);
        start.disabled = false;
        start.lastChild.textContent = "Summarise again";
      } catch (err) { error.textContent = err.message; error.hidden = false; save.disabled = false; }
    });
    const edit = button("Edit", "btn quiet", () => { view.hidden = true; editor.hidden = false; edit.hidden = true; editor.focus(); });
    const discard = button("Discard", "btn plain", () => {
      out.hidden = true; out.textContent = ""; idle.hidden = false; start.disabled = false;
    });
    actions.append(save, edit, discard, el("span", "hint sp", pid + " never sees this summary."));
    out.append(view, editor, actions, error);
    out.hidden = false;
  }
})();
