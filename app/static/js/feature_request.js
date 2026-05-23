/* SPDX-License-Identifier: AGPL-3.0-or-later
 * Feature-request widget: open/close the modal, submit it over fetch (so the
 * page never reloads), and drive Cloudflare Turnstile via explicit render so
 * the widget behaves correctly inside a hidden dialog. Vanilla JS, no deps.
 */
(function () {
  "use strict";

  var modal = document.querySelector("[data-fr-modal]");
  if (!modal) return;                       // widget not configured on this page

  var form = modal.querySelector("[data-fr-form]");
  var msg = modal.querySelector("[data-fr-msg]");
  var done = modal.querySelector("[data-fr-done]");
  var submitBtn = modal.querySelector("[data-fr-submit]");
  var tsEl = modal.querySelector("[data-fr-turnstile]");
  var lastFocus = null;

  /* ── Turnstile (explicit render) ─────────────────────────────────────── */
  var tsId = null;
  function renderTS() {
    if (!tsEl || tsId !== null || !window.turnstile) return;
    try {
      tsId = window.turnstile.render(tsEl, { sitekey: tsEl.getAttribute("data-sitekey") });
    } catch (e) { /* already rendered or not ready */ }
  }
  function resetTS() {
    if (tsEl && window.turnstile && tsId !== null) {
      try { window.turnstile.reset(tsId); } catch (e) {}
    }
  }
  // api.js (loaded with ?onload=ppFrTurnstileReady) calls this when ready.
  window.ppFrTurnstileReady = function () {
    if (modal.classList.contains("open")) renderTS();
  };

  /* ── open / close ────────────────────────────────────────────────────── */
  function open() {
    lastFocus = document.activeElement;
    resetView();
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    renderTS();                              // in case api.js already loaded
    var first = form.querySelector("input[name=name], textarea[name=feature]");
    setTimeout(function () { if (first) first.focus(); }, 40);
  }
  function close() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  function resetView() {
    form.hidden = false;
    done.hidden = true;
    clearMsg();
    form.querySelectorAll(".pp-fr-invalid").forEach(function (el) { el.classList.remove("pp-fr-invalid"); });
  }

  document.querySelectorAll("[data-fr-open]").forEach(function (b) {
    b.addEventListener("click", open);
  });
  modal.querySelectorAll("[data-fr-close]").forEach(function (b) {
    b.addEventListener("click", close);
  });
  modal.addEventListener("click", function (e) { if (e.target === modal) close(); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && modal.classList.contains("open")) close();
  });

  /* ── messages / loading ──────────────────────────────────────────────── */
  function showErr(text) { msg.textContent = text; msg.classList.add("pp-fr-err"); }
  function clearMsg() { msg.textContent = ""; msg.classList.remove("pp-fr-err"); }
  function markInvalid(el) {
    el.classList.add("pp-fr-invalid");
    el.addEventListener("input", function once() { el.classList.remove("pp-fr-invalid"); el.removeEventListener("input", once); });
  }
  function setLoading(on) {
    submitBtn.disabled = on;
    submitBtn.querySelector(".pp-fr-submit-label").textContent = on ? "Sending…" : "Send request";
  }
  function showDone() { form.hidden = true; done.hidden = false; }

  /* ── submit ──────────────────────────────────────────────────────────── */
  var EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    clearMsg();

    var feature = form.feature.value.trim();
    if (!feature) {
      markInvalid(form.feature);
      showErr("Please describe the feature you’d like to see.");
      form.feature.focus();
      return;
    }
    var email = form.email.value.trim();
    if (email && !EMAIL_RE.test(email)) {
      markInvalid(form.email);
      showErr("That email address doesn’t look right.");
      form.email.focus();
      return;
    }

    setLoading(true);
    fetch("/feature-request", {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "fetch" },
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        return { ok: res.ok, data: data };
      });
    }).then(function (r) {
      if (r.ok && r.data.ok) {
        showDone();
      } else {
        showErr(r.data.error || "Something went wrong. Please try again.");
        resetTS();
      }
    }).catch(function () {
      showErr("Network error — please check your connection and try again.");
      resetTS();
    }).finally(function () {
      setLoading(false);
    });
  });
})();
