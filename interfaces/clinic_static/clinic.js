// Limber clinic app (feature 019): the few things the server-rendered pages need a script for.
// Every write is JSON to /therapist/api/..., and an ended sign-in sends the person to the sign-in page.
"use strict";

(function () {
  const BASE = "/therapist";

  async function api(path, body) {
    const options = body === undefined
      ? { credentials: "same-origin" }
      : { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body) };
    const response = await fetch(BASE + path, options);
    let data = {};
    try { data = await response.json(); } catch (_) { /* not JSON */ }
    if (response.status === 401 && data.signed_out) {
      const here = location.pathname + location.search;
      location.assign(BASE + "/signin?next=" + encodeURIComponent(here));
      throw new Error("signed out");
    }
    if (!response.ok) throw Object.assign(new Error(data.error || "That did not work. Try again."), { data });
    return data;
  }
  window.limber = { api };

  // Menus: only one open at a time, and Escape or a click elsewhere closes them.
  const drops = Array.from(document.querySelectorAll("details.drop"));
  drops.forEach((d) => d.addEventListener("toggle", () => {
    if (d.open) drops.forEach((o) => { if (o !== d) o.open = false; });
  }));
  document.addEventListener("click", (e) => {
    drops.forEach((d) => { if (d.open && !d.contains(e.target)) d.open = false; });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    drops.forEach((d) => { if (d.open) { d.open = false; d.querySelector("summary").focus(); } });
  });

  // Filters (the Dashboard's period, a patient) apply as soon as they change.
  document.querySelectorAll("select[data-submit-on-change]").forEach((sel) => {
    sel.addEventListener("change", () => sel.form.submit());
  });

  // Sign out.
  document.querySelectorAll("[data-signout]").forEach((b) => b.addEventListener("click", async () => {
    try { await api("/api/logout", {}); } catch (_) { /* already signed out */ }
    try { sessionStorage.clear(); } catch (_) { /* storage blocked */ }
    location.assign(BASE + "/signin");
  }));

  // My settings: each switch saves at once and the page changes straight away.
  const switches = Array.from(document.querySelectorAll("input[data-pref]"));
  const saved = document.querySelector("[data-saved]");
  const CLASSES = { larger_text: "lt", high_contrast: "hc", reduced_motion: "lm" };
  switches.forEach((s) => s.addEventListener("change", async () => {
    const prefs = {};
    switches.forEach((o) => { prefs[o.dataset.pref] = o.checked; });
    const root = document.querySelector(".lb");
    try {
      const data = await api("/api/me/preferences", prefs);
      Object.entries(CLASSES).forEach(([k, c]) => root.classList.toggle(c, data.prefs[k] === true));
      if (saved) {
        const label = s.closest("li").querySelector("h3").textContent;
        saved.querySelector("span").textContent = "Saved. " + label + " is " + (s.checked ? "on." : "off.");
        saved.hidden = false;
      }
    } catch (err) {
      s.checked = !s.checked;
      if (saved) { saved.querySelector("span").textContent = err.message; saved.hidden = false; }
    }
  }));

  // The sign-in screen.
  const form = document.querySelector("form[data-signin]");
  if (form) {
    const error = form.querySelector("[data-error]");
    try {
      if (sessionStorage.getItem("limber.keptReply")) form.querySelector("[data-kept]").hidden = false;
    } catch (_) { /* storage blocked */ }
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      error.hidden = true;
      const button = form.querySelector("button[type=submit]");
      button.disabled = true;
      try {
        const next = new URLSearchParams(location.search).get("next");
        const data = await api("/api/login", {
          username: form.elements.username.value.trim(),
          password: form.elements.password.value,
          next: next || undefined,
        });
        location.assign(data.redirect);
      } catch (err) {
        error.textContent = err.message;
        error.hidden = false;
        button.disabled = false;
        form.elements.password.value = "";
        form.elements.password.focus();
      }
    });
  }
})();
