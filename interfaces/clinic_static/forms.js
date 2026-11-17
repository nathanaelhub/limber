// Limber clinic forms (feature 019 slice 3a). Every form with data-api is posted as JSON to /therapist{data-api}:
// text, dates and times as strings, numbers as numbers, a checkbox as true or false, a multiple select as a list.
// A confirm text asks first. On success the page reloads, goes where the server says, or (data-result-once) shows
// what the server hands back exactly once, such as a new access code. A form with a hidden "confirm" field asks
// before saving text the privacy check flagged (021 N1), or before accepting a visit time that overlaps (021 N2).
"use strict";

(function () {
  function values(form) {
    const out = {};
    Array.from(form.elements).forEach((el) => {
      if (!el.name || el.disabled) return;
      if (el.type === "checkbox") out[el.name] = el.checked;
      else if (el.type === "number") out[el.name] = el.value === "" ? null : Number(el.value);
      else if (el.tagName === "SELECT" && el.multiple) out[el.name] = Array.from(el.selectedOptions).map((o) => o.value);
      else out[el.name] = el.value;
    });
    return out;
  }

  document.querySelectorAll("form[data-api]").forEach((form) => {
    // A switch that saves as soon as it is flipped.
    if (form.hasAttribute("data-auto")) {
      form.addEventListener("change", () => form.requestSubmit());
    }
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const resend = form.querySelector("input[type=hidden][name=confirm]");
      // A resend after "anyway?" was already confirmed once; don't ask the form's own question again.
      if (form.dataset.confirm && !(resend && resend.value) && !window.confirm(form.dataset.confirm)) return;
      const error = form.querySelector("[data-error]");
      const button = form.querySelector("button[type=submit]");
      error.hidden = true;
      button.disabled = true;
      try {
        const data = await window.limber.api(form.dataset.api, values(form));
        if (data.notice) window.alert(data.notice);
        if (data.redirect) { location.assign(data.redirect); return; }
        if (form.hasAttribute("data-result-once") && data.show) {
          const box = form.querySelector("[data-result]");
          box.textContent = "";
          const p = document.createElement("p");
          p.textContent = data.note || "";
          const code = document.createElement("p");
          code.className = "code big-code";
          code.textContent = data.show;
          box.append(p, code);
          box.hidden = false;
          button.hidden = true;
          form.classList.add("wide");
          return;
        }
        location.reload();
      } catch (err) {
        button.disabled = false;
        // The privacy check (as for replies): say what it found, and save anyway only when the person agrees.
        const again = form.querySelector("input[type=hidden][name=confirm]");
        if (err.data && err.data.needs_confirm && again && !again.value) {
          if (window.confirm(err.message.endsWith("?") ? err.message : err.message + "\n\nSave anyway?")) {
            again.value = "yes";
            form.requestSubmit();
            again.value = "";
            return;
          }
        }
        error.textContent = err.message;
        error.hidden = false;
      }
    });
  });
})();
