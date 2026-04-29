// SPDX-License-Identifier: AGPL-3.0-or-later
(function installCsrfFetch() {
  // Auto-attach X-CSRFToken header to all same-origin state-changing fetches.
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) return;
  const token = meta.content;
  const safe = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);
  const orig = window.fetch;
  window.fetch = function (input, init) {
    init = init || {};
    const method = String(init.method || (input && input.method) || "GET").toUpperCase();
    if (!safe.has(method)) {
      init.headers = new Headers(init.headers || {});
      if (!init.headers.has("X-CSRFToken")) init.headers.set("X-CSRFToken", token);
    }
    return orig.call(this, input, init);
  };
})();

(function () {
  const root = document.documentElement;
  const THEME_MODE = {
    "light": "light", "dark": "dark",
    "neobrutal-light": "light", "neobrutal-dark": "dark",
    "cyberpunk": "dark", "solarpunk": "light",
  };
  const stored = localStorage.getItem("tsp-theme");
  if (stored && THEME_MODE[stored]) root.setAttribute("data-theme", stored);

  function syncThemePicker() {
    const cur = root.getAttribute("data-theme") || "light";
    document.querySelectorAll(".theme-swatch").forEach(el => {
      el.setAttribute("aria-checked", el.dataset.themeValue === cur ? "true" : "false");
    });
  }
  function setTheme(next, {remember = true} = {}) {
    if (!THEME_MODE[next]) next = "light";
    root.setAttribute("data-theme", next);
    localStorage.setItem("tsp-theme", next);
    if (remember) localStorage.setItem("tsp-theme-last-" + THEME_MODE[next], next);
    syncThemePicker();
  }
  const THEME_PAIR = {
    "light": "dark", "dark": "light",
    "neobrutal-light": "neobrutal-dark", "neobrutal-dark": "neobrutal-light",
    "solarpunk": "cyberpunk", "cyberpunk": "solarpunk",
  };
  function toggleLightDark() {
    const cur = root.getAttribute("data-theme") || "light";
    setTheme(THEME_PAIR[cur] || "dark");
  }
  const sidebarToggle = document.getElementById("theme-toggle");
  if (sidebarToggle) sidebarToggle.addEventListener("click", toggleLightDark);
  document.querySelectorAll(".theme-swatch").forEach(el => {
    el.addEventListener("click", () => setTheme(el.dataset.themeValue));
  });
  // Seed "last" memory from current theme on first load
  const curInit = root.getAttribute("data-theme") || "light";
  const curMode = THEME_MODE[curInit] || "light";
  if (!localStorage.getItem("tsp-theme-last-" + curMode))
    localStorage.setItem("tsp-theme-last-" + curMode, curInit);
  syncThemePicker();

  const menu = document.getElementById("menu-toggle");
  const side = document.querySelector(".sidebar");
  if (menu && side) {
    menu.addEventListener("click", e => {
      e.stopPropagation();
      side.classList.toggle("open");
    });
    document.addEventListener("click", e => {
      if (!side.classList.contains("open")) return;
      if (side.contains(e.target) || (menu && menu.contains(e.target))) return;
      side.classList.remove("open");
    });
    side.querySelectorAll("nav a").forEach(a =>
      a.addEventListener("click", () => side.classList.remove("open")));
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".help-btn");
    const openEls = document.querySelectorAll(".heading-help.open");
    if (btn) {
      const wrap = btn.closest(".heading-help");
      const wasOpen = wrap.classList.contains("open");
      openEls.forEach(el => el.classList.remove("open"));
      if (!wasOpen) wrap.classList.add("open");
      e.stopPropagation();
    } else if (!e.target.closest(".help-tooltip")) {
      openEls.forEach(el => el.classList.remove("open"));
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.querySelectorAll(".heading-help.open").forEach(el => el.classList.remove("open"));
  });

  // Branding: live-preview footer logo width + selected file
  const bWidth = document.getElementById("branding-width-slider");
  const bValue = document.getElementById("branding-width-value");
  const bImg = document.getElementById("branding-preview-img");
  const bFile = document.getElementById("branding-file-input");
  if (bWidth && bImg && bValue) {
    const sync = () => {
      bImg.style.width = bWidth.value + "px";
      bValue.textContent = bWidth.value + "px";
    };
    bWidth.addEventListener("input", sync);
    sync();
  }
  if (bFile && bImg) {
    bFile.addEventListener("change", () => {
      const f = bFile.files && bFile.files[0];
      if (!f) return;
      const url = URL.createObjectURL(f);
      bImg.src = url;
      bImg.hidden = false;
      const emptyLabel = document.querySelector(".appearance-branding-form .branding-preview-empty");
      if (emptyLabel) emptyLabel.hidden = true;
    });
  }

  const bForm = document.querySelector("form.appearance-branding-form");
  if (bForm) {
    bForm.addEventListener("settings:saved", (e) => {
      const d = e.detail;
      if (!d) return;
      const sidebarImg = document.getElementById("sidebar-footer-logo");
      const sidebarLink = document.getElementById("sidebar-footer-link");
      if (sidebarImg) {
        sidebarImg.src = d.footer_logo_src || "";
        if (d.footer_logo_width) sidebarImg.style.width = d.footer_logo_width + "px";
      }
      if (sidebarLink) {
        sidebarLink.href = d.footer_logo_link || "#";
        sidebarLink.hidden = !d.has_custom_logo;
      }
      if (bImg) {
        bImg.src = d.footer_logo_src || "";
        bImg.hidden = !d.has_custom_logo;
      }
      const emptyLabel = bForm.querySelector(".branding-preview-empty");
      if (emptyLabel) emptyLabel.hidden = !!d.has_custom_logo;
      if (bFile) bFile.value = "";
      const clearLabel = bForm.querySelector(".branding-clear-label");
      if (clearLabel) {
        const cb = clearLabel.querySelector('input[name="clear_logo"]');
        if (cb) cb.checked = false;
        clearLabel.hidden = !d.has_custom_logo;
      }
    });
  }

  // Modal open/close
  function openModal(id) {
    const m = document.getElementById(id);
    if (!m) return;
    m.classList.add("open");
    m.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }
  function closeModal(m) {
    m.classList.remove("open");
    m.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }
  document.querySelectorAll("[data-open-modal]").forEach(el => {
    el.addEventListener("click", (e) => {
      // Allow data-settings-tab="<key>" alongside data-open-modal to
      // deep-link a specific tab inside the settings modal — e.g. the
      // dashboard role widget links to its full Your Access view.
      const targetId = el.dataset.openModal;
      const tab = el.dataset.settingsTab;
      if (tab && targetId === "settings-modal" && el.tagName === "A") {
        e.preventDefault();
      }
      openModal(targetId);
      if (tab && targetId === "settings-modal") {
        const modal = document.getElementById("settings-modal");
        const tabBtn = modal && modal.querySelector('.settings-tab[data-tab="' + tab + '"]');
        if (tabBtn) tabBtn.click();
      }
    });
  });

  // Upload / Paste content mode toggle on reading forms.
  document.querySelectorAll("[data-content-mode-toggle]").forEach(toggle => {
    const form = toggle.closest("form");
    if (!form) return;
    const hidden = toggle.querySelector("[data-content-mode-input]");
    const check = toggle.querySelector("[data-content-mode-check]");
    const labels = toggle.querySelectorAll("[data-content-mode-label]");
    const panels = form.querySelectorAll("[data-content-panel]");
    function apply(mode) {
      if (hidden) hidden.value = mode;
      if (check) check.checked = (mode === "paste");
      labels.forEach(l => l.classList.toggle("active", l.dataset.contentModeLabel === mode));
      panels.forEach(p => {
        const match = p.dataset.contentPanel === mode;
        p.hidden = !match;
        p.querySelectorAll("input, textarea, select").forEach(el => {
          el.disabled = !match;
        });
      });
    }
    if (check) check.addEventListener("change", () => apply(check.checked ? "paste" : "upload"));
    apply((hidden && hidden.value) || "upload");
  });

  // Markdown editor tab switcher + debounced live preview via /markdown-preview.
  document.querySelectorAll("[data-md-editor]").forEach(editor => {
    const tabs = editor.querySelectorAll(".md-editor-tab");
    const writePane = editor.querySelector(".md-editor-pane-write");
    const previewPane = editor.querySelector(".md-editor-pane-preview");
    const previewEl = editor.querySelector(".md-editor-preview");
    const textarea = editor.querySelector("textarea");
    if (!tabs.length || !writePane || !previewPane || !textarea) return;

    let lastRendered = null;
    let pending = null;
    async function renderPreview() {
      const content = textarea.value || "";
      if (content === lastRendered) return;
      if (!content.trim()) {
        previewEl.innerHTML = '<p class="muted smaller">Nothing to preview yet.</p>';
        lastRendered = content;
        return;
      }
      const fd = new FormData();
      fd.append("body", content);
      try {
        const r = await fetch("/tspro/markdown-preview", {
          method: "POST", body: fd, credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" },
        });
        if (!r.ok) return;
        const data = await r.json();
        previewEl.innerHTML = data.html || '<p class="muted smaller">(empty)</p>';
        lastRendered = content;
      } catch (_) {}
    }

    function activate(tabName) {
      tabs.forEach(t => t.classList.toggle("active", t.dataset.mdTab === tabName));
      writePane.classList.toggle("active", tabName === "write");
      previewPane.classList.toggle("active", tabName === "preview");
      if (tabName === "preview") renderPreview();
    }
    tabs.forEach(t => t.addEventListener("click", () => activate(t.dataset.mdTab)));

    textarea.addEventListener("input", () => {
      clearTimeout(pending);
      pending = setTimeout(() => {
        if (previewPane.classList.contains("active")) renderPreview();
      }, 250);
    });
  });

  // Reading lightbox: click on [data-reading-lightbox] shows the rendered
  // body content in a paper-styled modal, with a Download PDF button.
  (function initReadingLightbox(){
    const modal = document.getElementById("reading-lightbox");
    if (!modal) return;
    const titleEl = modal.querySelector("[data-reading-lightbox-title]");
    const docTitleEl = modal.querySelector("[data-reading-lightbox-doc-title]");
    const contentEl = modal.querySelector("[data-reading-lightbox-content]");
    const pdfLink = modal.querySelector("[data-reading-lightbox-pdf]");
    document.querySelectorAll("[data-reading-lightbox]").forEach(link => {
      link.addEventListener("click", e => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) return;
        e.preventDefault();
        const rid = link.dataset.readingLightbox;
        const title = link.dataset.readingTitle || "";
        const tmpl = document.querySelector(`template[data-reading-content="${rid}"]`);
        titleEl.textContent = title;
        docTitleEl.textContent = title;
        contentEl.innerHTML = tmpl ? tmpl.innerHTML : "";
        pdfLink.href = "/tspro/readings/" + rid + "/pdf";
        openModal("reading-lightbox");
        const body = modal.querySelector(".reading-lightbox-body");
        if (body) body.scrollTop = 0;
      });
    });
  })();

  // About pane: animated pale sine-wave gradient behind the grey hero.
  // Wave parameters and gradient angle are randomized on each page load, so
  // every visit gets a different polished look. Runs only while the canvas
  // is visible via IntersectionObserver so the settings modal being closed
  // or the About tab being inactive stops the loop.
  (function initAboutHeroBg(){
    const canvas = document.querySelector(".about-hero-bg");
    if (!canvas) return;
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const W = 200, H = 120;
    canvas.width = W; canvas.height = H;
    const cctx = canvas.getContext("2d");

    const hslToRgb = (h, s, l) => {
      h /= 360;
      const a = s * Math.min(l, 1 - l);
      const f = n => {
        const k = (n + h * 12) % 12;
        const v = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
        return Math.round(v * 255);
      };
      return [f(0), f(8), f(4)];
    };

    // Triadic palette: a random base hue plus the two other vertices of an
    // equilateral triangle on the color wheel (120° apart). Small per-stop
    // jitter and a randomized starting vertex keep runs visually distinct.
    const rand = (a, b) => a + Math.random() * (b - a);
    const hueBase = Math.random() * 360;
    const triad = [0, 120, 240].map(d => (hueBase + d + rand(-8, 8) + 360) % 360);
    // Shuffle so the ordering across the gradient axis varies.
    for (let i = triad.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [triad[i], triad[j]] = [triad[j], triad[i]];
    }
    const rgb = triad.map(h => hslToRgb(h, 1, 0.55));
    const n = rgb.length;

    // Randomize wave shape + drift speed (both slow).
    const freq1 = rand(2.2, 4.0);
    const freq2 = rand(5.0, 8.0);
    const amp1 = rand(0.16, 0.28);
    const amp2 = rand(0.06, 0.12);
    const phaseSpeed1 = rand(0.05, 0.12) * (Math.random() < 0.5 ? 1 : -1);
    const phaseSpeed2 = rand(0.06, 0.14) * (Math.random() < 0.5 ? 1 : -1);
    const phaseOffset = Math.random() * Math.PI * 2;

    // Randomize the gradient angle by rotating the sampling coordinates.
    const rotRad = Math.random() * Math.PI * 2;
    const cosR = Math.cos(rotRad), sinR = Math.sin(rotRad);
    const maxDim = Math.max(W, H);

    const img = cctx.createImageData(W, H);
    const d = img.data;
    let running = false;
    let start = 0;
    function frame(now){
      if (!running) return;
      const t = (now - start) / 1000;
      const p1 = t * phaseSpeed1;
      const p2 = t * phaseSpeed2 + phaseOffset;
      for (let y = 0; y < H; y++){
        for (let x = 0; x < W; x++){
          // Rotate coordinates around center so the gradient axis is at rotRad.
          const cx = x - W / 2, cy = y - H / 2;
          const rx = cx * cosR - cy * sinR;
          const ry = cx * sinR + cy * cosR;
          const nx = (rx + maxDim / 2) / maxDim;
          const ny = (ry + maxDim / 2) / maxDim;
          const wave = Math.sin(nx * freq1 + p1) * amp1
                     + Math.sin(nx * freq2 + p2 + 1.3) * amp2;
          let tt = ny + wave;
          if (tt < 0) tt = 0; else if (tt > 1) tt = 1;
          const p = tt * (n - 1);
          const i = Math.floor(p);
          const f = p - i;
          const u = f * f * (3 - 2 * f);
          const a = rgb[i], b = rgb[Math.min(n - 1, i + 1)];
          const idx = (y * W + x) * 4;
          d[idx]   = a[0] + (b[0] - a[0]) * u;
          d[idx+1] = a[1] + (b[1] - a[1]) * u;
          d[idx+2] = a[2] + (b[2] - a[2]) * u;
          d[idx+3] = 255;
        }
      }
      cctx.putImageData(img, 0, 0);
      requestAnimationFrame(frame);
    }
    function startLoop(){
      if (running) return;
      running = true; start = performance.now();
      requestAnimationFrame(frame);
    }
    function stopLoop(){ running = false; }
    const io = new IntersectionObserver(entries => {
      const visible = entries[0] && entries[0].isIntersecting && entries[0].intersectionRatio > 0;
      if (visible) startLoop(); else stopLoop();
    }, { threshold: 0.01 });
    io.observe(canvas);
  })();

  // Access Requests → Create User: open Settings → Users with the iframe
  // reloaded against query params so the Create User form arrives
  // pre-populated. Email seeds username + email; name and phone are
  // forwarded so the admin doesn't have to retype anything from the
  // request row they just clicked.
  document.querySelectorAll("[data-create-user-from-request]").forEach(btn => {
    btn.addEventListener("click", () => {
      const email = btn.dataset.email || "";
      const name = btn.dataset.name || "";
      const phone = btn.dataset.phone || "";
      const modal = document.getElementById("settings-modal");
      if (!modal) return;
      openModal("settings-modal");
      const usersTab = modal.querySelector('[data-tab="users"]');
      if (usersTab) usersTab.click();
      const pane = modal.querySelector('[data-pane="users"]');
      const iframe = pane && pane.querySelector("iframe.settings-frame");
      if (iframe) {
        const base = iframe.dataset.src || "";
        const params = new URLSearchParams();
        if (email) params.set("prefill", email);
        if (name)  params.set("prefill_name", name);
        if (phone) params.set("prefill_phone", phone);
        params.set("_", Date.now().toString());
        const sep = base.includes("?") ? "&" : "?";
        iframe.src = base + sep + params.toString();
      }
    });
  });
  document.querySelectorAll(".modal").forEach(m => {
    m.querySelectorAll("[data-close]").forEach(el =>
      el.addEventListener("click", () => closeModal(m)));
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal.open").forEach(closeModal);
    }
  });

  // Day-of-week checkbox toggles enable/disable of the row's fields
  function wireDayRow(row) {
    const toggle = row.querySelector(".day-toggle");
    const fields = row.querySelectorAll(".day-field, .day-hidden");
    if (!toggle) return;
    const sync = () => {
      fields.forEach(f => { f.disabled = !toggle.checked; });
      row.classList.toggle("on", toggle.checked);
    };
    toggle.addEventListener("change", sync);
    sync();
  }
  document.querySelectorAll(".day-row").forEach(wireDayRow);

  // Meeting form: type radios show/hide Zoom fields; location select toggles custom input
  document.querySelectorAll("[data-meeting-form]").forEach(form => {
    const radios = form.querySelectorAll(".meeting-type-radio");
    const applyType = () => {
      const val = (form.querySelector(".meeting-type-radio:checked") || {}).value || "in_person";
      form.classList.toggle("hide-zoom", val === "in_person");
    };
    radios.forEach(r => r.addEventListener("change", applyType));
    applyType();

    const sel = form.querySelector(".location-select");
    const wrap = form.querySelector(".location-custom-wrap");
    if (sel && wrap) {
      const syncLoc = () => { wrap.style.display = sel.value === "__custom__" ? "" : "none"; };
      sel.addEventListener("change", syncLoc);
      syncLoc();
    }
  });

  // Settings modal tabs (lazy-load iframes)
  const settingsModal = document.getElementById("settings-modal");
  if (settingsModal) {
    const tabs = settingsModal.querySelectorAll(".settings-tab");
    const panes = settingsModal.querySelectorAll(".settings-pane");
    const activate = name => {
      tabs.forEach(t => t.classList.toggle("active", t.dataset.tab === name));
      panes.forEach(p => {
        const on = p.dataset.pane === name;
        p.classList.toggle("active", on);
        if (on) {
          const f = p.querySelector("iframe.settings-frame");
          if (f && !f.src && f.dataset.src) f.src = f.dataset.src;
        }
      });
    };
    tabs.forEach(t => t.addEventListener("click", () => activate(t.dataset.tab)));

    // Submit top-level settings forms via fetch so the page never reloads.
    // Forms inside iframes are untouched (they already reload only the iframe).
    // Any form marked data-no-ajax="1" still performs a normal submit (e.g. data import).
    function showSettingsToast(msg, kind){
      let t = document.getElementById("settings-toast");
      if (!t){
        t = document.createElement("div");
        t.id = "settings-toast";
        t.className = "settings-toast";
        settingsModal.querySelector(".modal-panel").appendChild(t);
      }
      t.className = "settings-toast flash-" + (kind || "success") + " show";
      t.textContent = msg;
      clearTimeout(showSettingsToast._h);
      showSettingsToast._h = setTimeout(() => t.classList.remove("show"), 2200);
    }

    // Shared AJAX submit for any settings-modal form. Returns a promise
    // that resolves with the parsed JSON body (if any) on success and
    // rejects on HTTP/network failure. Always dispatches `settings:saved`
    // on success so downstream listeners (sidebar refresh) fire whether
    // the form was committed via Enter, the per-form submit handler, or
    // the batched save bar.
    async function submitSettingsForm(f) {
      const r = await fetch(f.action, {
        method: (f.method || "POST").toUpperCase(),
        body: new FormData(f),
        headers: { "X-Requested-With": "fetch" },
        credentials: "same-origin",
        redirect: "follow",
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      let data = null;
      const ct = r.headers.get("content-type") || "";
      if (ct.includes("application/json")) {
        try { data = await r.json(); } catch (_) {}
      }
      f.dispatchEvent(new CustomEvent("settings:saved", { bubbles: true, detail: data }));
      return data;
    }

    settingsModal.querySelectorAll("form").forEach(f => {
      if (f.closest(".settings-frame")) return;
      if (f.dataset.noAjax === "1") return;
      f.addEventListener("submit", async e => {
        e.preventDefault();
        const btn = f.querySelector('button[type="submit"], button:not([type])');
        const orig = btn ? btn.textContent : null;
        // Test buttons (e.g. Send Test on Email) hijack the verb so the
        // disabled-state text reads "Sending…" instead of "Saving…" — a
        // misleading label was a major part of the original bug report.
        const isTestForm = f.matches("[data-email-test-form]");
        const busyLabel = isTestForm ? "Sending…" : "Saving…";
        if (btn){ btn.disabled = true; btn.textContent = busyLabel; }
        try {
          // For the email-test form: if the SMTP settings form sitting
          // above it is dirty (admin typed new SMTP host/port/etc. but
          // hasn't clicked the yellow Save bar yet), persist that first
          // so the test runs against the values the admin just typed
          // rather than stale DB state. Without this the test can
          // succeed-or-fail based on settings the admin hasn't saved.
          if (isTestForm) {
            const smtpForm = settingsModal.querySelector(
              'form[action$="/settings/email-save"]'
            );
            if (smtpForm && sbDirty.has(smtpForm)) {
              await submitSettingsForm(smtpForm);
              sbDirty.delete(smtpForm);
              if (sbDirty.size === 0) {
                if (sbBar) sbBar.hidden = true;
              } else {
                sbShow();
              }
            }
          }
          const data = await submitSettingsForm(f);
          // If the endpoint returned JSON with a `message`, surface it
          // verbatim. ``ok: false`` is treated as a soft error and
          // shown via the danger toast even though the HTTP status
          // is 200 — matches the pattern used by email-test, where
          // an SMTP failure isn't an HTTP failure.
          if (data && typeof data.message === "string") {
            showSettingsToast(data.message, data.ok === false ? "danger" : "success");
          } else {
            showSettingsToast(isTestForm ? "Test sent" : "Saved");
          }
          if (f.dataset.reloadOnSave === "1") {
            setTimeout(() => window.location.reload(), 400);
          }
        } catch (err) {
          showSettingsToast(
            (isTestForm ? "Test failed: " : "Save failed: ") + err.message,
            "danger"
          );
        } finally {
          if (btn){ btn.disabled = false; btn.textContent = orig; }
        }
      });
    });

    // Rewire any element that does `this.form.submit()` on change — that
    // bypasses the submit event so our AJAX handler never sees it (the
    // modal would close on the resulting full-page redirect). Replace
    // with requestSubmit() which DOES fire the event. Covers both
    // checkboxes (toggles) and selects (the per-module role picker).
    settingsModal.querySelectorAll(
      'input[onchange*="this.form.submit()"], select[onchange*="this.form.submit()"]'
    ).forEach(el => {
      el.setAttribute("onchange", "this.form.requestSubmit()");
    });

    // Live sidebar refresh — forms tagged with data-refresh-sidebar
    // (module toggles, role pickers, and the sidebar-order form) trigger
    // a fetch of the rendered nav fragment after a successful save and
    // swap it into the live sidebar. The Sidebar tab's manual reorder
    // list is also swapped so its Main/Admin partitioning mirrors the
    // current role-based section placement. No reload, modal stays open.
    let _sidebarRefreshing = false;
    settingsModal.addEventListener("settings:saved", e => {
      const f = e.target;
      if (!f || !(f instanceof HTMLFormElement)) return;
      if (f.dataset.refreshSidebar !== "1") return;
      if (_sidebarRefreshing) return;
      _sidebarRefreshing = true;
      // Skip refreshing the manual section if THIS form IS the
      // sidebar-order form — replacing the very form the admin just
      // submitted would obliterate any in-flight UI state. The role-
      // based section placement still applies on the next load.
      const refreshManual = f.id !== "sidebar-order-form";
      Promise.all([
        fetch("/tspro/_sidebar/nav", {
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" },
        }).then(r => r.ok ? r.text() : Promise.reject(r))
          .then(html => {
            const nav = document.getElementById("sidebar-nav");
            if (nav) nav.innerHTML = html;
          }),
        refreshManual ? fetch("/tspro/_sidebar/order-manual", {
          credentials: "same-origin",
          headers: { "X-Requested-With": "fetch" },
        }).then(r => r.ok ? r.text() : null)
          .then(html => {
            if (!html) return;
            const wrap = document.querySelector("[data-sidebar-manual]");
            if (wrap) wrap.innerHTML = html;
          }) : Promise.resolve(),
      ]).catch(() => {}).finally(() => { _sidebarRefreshing = false; });
    });

    // ── Settings save bar ────────────────────────────────────────────
    // One yellow bar pinned to the bottom-left of the modal panel that
    // batches saves across every tracked top-level form. Shows when any
    // tracked form becomes dirty; click commits each dirty form via the
    // shared AJAX path. Per-form save buttons are hidden so the bar is
    // the canonical commit affordance — auto-submit toggles (modules
    // pane, role pickers) keep their existing on-change behavior since
    // they never had a save button to replace.
    //
    // sbDirty / sbBar / sbShow are declared at the settings-modal scope
    // so the per-form submit handler above (which runs for the email
    // Send Test button) can peek into the dirty set and auto-save the
    // SMTP form before issuing the test request.
    const sbBar = document.getElementById("settings-save-bar");
    const sbBtn = document.getElementById("settings-save-bar-btn");
    const sbMsg = sbBar && sbBar.querySelector(".fe-save-bar-msg");
    const sbDirty = new Set();
    function sbShow() {
      if (!sbBar || !sbMsg || !sbBtn) return;
      sbBar.hidden = false;
      sbBar.classList.remove("is-leaving");
      sbMsg.textContent = sbDirty.size > 1
        ? "Unsaved changes (" + sbDirty.size + " sections)"
        : "Unsaved changes";
      sbBtn.disabled = false;
      sbBtn.textContent = "Save";
    }
    if (sbBar && sbBtn) {

      function sbTrackable(form) {
        if (form.closest(".settings-frame")) return false;
        if (form.dataset.noAjax === "1") return false;
        if (form.dataset.savebarSkip === "1") return false;
        if (form.querySelector('[onchange*="this.form."]')) return false;
        // Require an explicit primary save button — that's what the bar
        // replaces. Forms without one (e.g. the "Send Test" email action
        // which uses `.btn`, not `.btn-primary`) keep their own button.
        return !!form.querySelector("button.btn-primary");
      }

      function sbHideAfterSave() {
        sbMsg.textContent = "Saved";
        sbBar.classList.add("is-leaving");
        setTimeout(() => {
          sbBar.hidden = true;
          sbBar.classList.remove("is-leaving");
          sbBar.style.width = "";  // release the locked width set on click
          sbDirty.clear();
        }, 320);
      }

      settingsModal.querySelectorAll("form").forEach(f => {
        if (!sbTrackable(f)) return;
        // Hide the form's primary save button (and its wrapper, if any)
        // so the bar becomes the only commit path. Wrappers handled:
        // .form-actions (most forms), .branding-save-row (logo form).
        // Bare buttons (e.g. inside .sidebar-order-head) hide themselves.
        f.querySelectorAll("button.btn-primary").forEach(b => {
          const wrap = b.closest(".form-actions, .branding-save-row");
          (wrap || b).classList.add("savebar-hidden");
        });
        const onChange = () => { sbDirty.add(f); sbShow(); };
        f.addEventListener("input", onChange);
        f.addEventListener("change", onChange);
      });

      sbBtn.addEventListener("click", async () => {
        if (!sbDirty.size) { sbBar.hidden = true; return; }
        // Pin the bar's current pixel width before changing the message
        // so it doesn't shrink leftward as text moves "Unsaved changes
        // (N sections)" → "Saving…" → "Saved". Width is released in
        // sbHideAfterSave so the next dirty cycle re-measures.
        sbBar.style.width = sbBar.offsetWidth + "px";
        sbBtn.disabled = true;
        sbBtn.textContent = "Saving…";
        sbMsg.textContent = "Saving…";
        const forms = [...sbDirty];
        const failures = [];
        for (const f of forms) {
          try { await submitSettingsForm(f); }
          catch (err) { failures.push(err); }
        }
        if (!failures.length) {
          sbHideAfterSave();
        } else {
          sbBtn.disabled = false;
          sbBtn.textContent = "Save";
          sbMsg.textContent = failures.length === 1
            ? "Save failed — try again"
            : "Some changes failed — try again";
        }
      });
    }
  }

  // Library picker in meeting modal: toggle expansion and granular readings
  document.querySelectorAll(".library-row").forEach(row => {
    const include = row.querySelector(".library-include");
    const detail = row.querySelector(".library-detail");
    const readings = row.querySelector(".library-readings");
    const syncInclude = () => { if (detail) detail.style.display = include.checked ? "" : "none"; };
    const modeSwitch = row.querySelector(".library-mode-switch");
    const syncMode = () => {
      const granular = !!(modeSwitch && modeSwitch.checked);
      if (readings) readings.style.display = granular ? "" : "none";
      row.classList.toggle("is-granular", granular);
    };
    if (include) include.addEventListener("change", syncInclude);
    if (modeSwitch) modeSwitch.addEventListener("change", syncMode);
    syncInclude(); syncMode();
  });

  // Location type toggle (show/hide address fields)
  document.querySelectorAll("[data-location-form]").forEach(form => {
    const fields = form.querySelector(".loc-in-person-fields");
    if (!fields) return;
    form.querySelectorAll(".loc-type-radio").forEach(r => {
      r.addEventListener("change", () => {
        const val = form.querySelector(".loc-type-radio:checked")?.value;
        fields.style.display = val === "online" ? "none" : "";
      });
    });
  });

  // File add inline accordion (animated)
  document.querySelectorAll("[data-file-add-toggle]").forEach(btn => {
    btn.addEventListener("click", () => {
      const f = document.getElementById(btn.dataset.fileAddToggle);
      if (!f) return;
      f.classList.toggle("collapsed");
    });
  });
  document.querySelectorAll("[data-file-add-cancel]").forEach(btn => {
    btn.addEventListener("click", () => {
      const f = document.getElementById(btn.dataset.fileAddCancel);
      if (f) { f.classList.add("collapsed"); f.reset(); }
    });
  });

  // Per-row "Public" toggle in the meeting modal's file list. Posts to a
  // JSON endpoint so the row can flip without closing the modal.
  document.querySelectorAll("[data-file-public-toggle]").forEach(input => {
    input.addEventListener("change", async () => {
      const fid = input.dataset.filePublicToggle;
      const fd = new FormData();
      fd.append("public_visible", input.checked ? "1" : "0");
      input.disabled = true;
      try {
        const r = await fetch(`/tspro/files/${fid}/public-toggle`, {
          method: "POST", body: fd, credentials: "same-origin",
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!r.ok) throw new Error("toggle failed");
        const data = await r.json();
        // Reflect the canonical value the server saw.
        input.checked = !!data.public_visible;
      } catch (err) {
        // Roll back the visual state if the request failed.
        input.checked = !input.checked;
        console.error(err);
      } finally {
        input.disabled = false;
      }
    });
  });

// Media library: upload input
  const mediaUploadInput = document.getElementById("media-upload-input");
  if (mediaUploadInput) {
    mediaUploadInput.addEventListener("change", async (e) => {
      const files = Array.from(e.target.files || []);
      for (const file of files) {
        const fd = new FormData();
        fd.append("file", file);
        try {
          const res = await fetch("/tspro/files/upload", {
            method: "POST", body: fd, credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          if (!res.ok) throw new Error("upload failed");
          const data = await res.json();
          if (window.parent !== window && window.parent.postMessage) {
            // inside picker: hand the item to parent
            window.parent.postMessage({ type: "media-uploaded", item: data.item }, window.location.origin);
          }
        } catch (err) { alert("Upload failed: " + err.message); }
      }
      // refresh listing
      window.location.reload();
    });
  }

  // Media library: rename
  document.querySelectorAll(".media-rename").forEach(btn => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("[data-media-id]");
      const id = row?.dataset.mediaId;
      const current = row?.dataset.original || "";
      const next = prompt("Rename file:", current);
      if (!next || next === current) return;
      const fd = new FormData();
      fd.append("name", next);
      const res = await fetch(`/tspro/files/${id}/rename`, {
        method: "POST", body: fd, credentials: "same-origin",
      });
      if (res.ok) {
        const data = await res.json();
        row.dataset.original = data.original_filename;
        const nameEl = row.querySelector(".media-name, strong");
        if (nameEl) { nameEl.textContent = data.original_filename; nameEl.title = data.original_filename; }
      }
    });
  });

  // Media library: select (inside picker iframe)
  document.querySelectorAll(".media-select").forEach(btn => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".media-card");
      const payload = {
        type: "media-selected",
        item: {
          id: card.dataset.mediaId,
          stored_filename: card.dataset.stored,
          original_filename: card.dataset.original,
        },
      };
      if (window.parent !== window) window.parent.postMessage(payload, window.location.origin);
    });
  });

  // Auto-dismiss flash toasts after 3s
  document.querySelectorAll(".flashes .flash").forEach(el => {
    setTimeout(() => {
      el.classList.add("flash-hide");
      el.addEventListener("animationend", () => el.remove(), { once: true });
    }, 3000);
  });

  // Live-update sidebar custom nav links when edited in Settings
  window.addEventListener("message", (e) => {
    if (e.origin !== window.location.origin) return;
    if (!e.data || e.data.type !== "nav-links-updated") return;
    const container = document.getElementById("sidebar-custom-nav");
    const divider = document.getElementById("sidebar-custom-nav-divider");
    if (!container) return;
    container.innerHTML = "";
    const links = e.data.links || [];
    links.forEach(n => {
      const a = document.createElement("a");
      a.href = n.url;
      a.target = "_blank";
      a.rel = "noopener";
      a.setAttribute("data-nav-custom", "");
      a.textContent = n.title + " ↗";
      container.appendChild(a);
    });
    if (divider) divider.hidden = links.length === 0;
  });

  // Media picker modal: open on [data-media-picker] buttons
  let currentMediaTarget = null;
  document.querySelectorAll("[data-media-picker]").forEach(btn => {
    btn.addEventListener("click", () => {
      currentMediaTarget = btn.dataset.mediaPicker;
      const frame = document.getElementById("media-picker-frame");
      if (frame && frame.src === "about:blank") frame.src = "/tspro/files?picker=1&embed=1";
      openModal("media-picker-modal");
    });
  });
  window.addEventListener("message", (e) => {
    if (e.origin !== window.location.origin) return;
    if (!e.data || e.data.type !== "media-selected") return;
    const item = e.data.item;
    if (!currentMediaTarget) return;
    const form = document.getElementById(currentMediaTarget);
    if (!form) return;
    let hidden = form.querySelector('input[name="media_id"]');
    if (!hidden) {
      hidden = document.createElement("input");
      hidden.type = "hidden"; hidden.name = "media_id";
      form.appendChild(hidden);
    }
    hidden.value = item.id;
    let label = form.querySelector(".media-picked-label");
    if (!label) {
      label = document.createElement("div");
      label.className = "media-picked-label muted small";
      form.insertBefore(label, form.querySelector(".form-actions") || null);
    }
    label.textContent = "Selected from library: " + item.original_filename;
    // Close modal
    const m = document.getElementById("media-picker-modal");
    if (m) closeModal(m);
  });

  // Drag-and-drop reorder for .file-list-sortable
  // Works with <ul><li>, <tbody><tr>, or any parent with direct-child
  // [data-item-id] elements. Detects horizontal vs. vertical layout
  // automatically so it can handle flex-row column editors.
  //
  // Save firing: the order snapshot from dragstart is compared against the
  // post-drag order on `dragend` and the save (or `reorder-changed` event)
  // fires whenever they differ. This used to live in `drop`, but `drop`
  // only fires when the user releases ON a valid drop target — releasing
  // in the gap between rows or just outside the list silently dropped the
  // reorder and snapped the row back on next refresh.
  function initSortable(list) {
    if (list.__tspSortableInit) return;
    list.__tspSortableInit = true;
    const url = list.dataset.reorderUrl;
    const category = list.dataset.reorderCategory || null;
    let dragging = null;
    let originalOrder = null;
    const isHorizontal = () => {
      const first = list.querySelector(":scope > [data-item-id]");
      const second = first?.nextElementSibling;
      if (!first || !second) return false;
      const a = first.getBoundingClientRect();
      const b = second.getBoundingClientRect();
      return Math.abs(b.left - a.left) > Math.abs(b.top - a.top);
    };
    const clearMarkers = () => {
      list.querySelectorAll(":scope > .drop-before, :scope > .drop-after, :scope > .drag-over")
        .forEach(x => x.classList.remove("drop-before", "drop-after", "drag-over"));
    };
    const snapshotOrder = () => Array.from(list.querySelectorAll(":scope > [data-item-id]"))
      .map(x => x.dataset.itemId);
    const orderEqual = (a, b) => a && b && a.length === b.length &&
      a.every((id, i) => id === b[i]);

    async function commitImmediate(order) {
      const payload = category ? { order, category } : { order };
      const label = list.dataset.reorderToast;
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
          body: JSON.stringify(payload),
        });
        if (res.ok) showToast(label ? (label + " saved") : "Order saved");
        else showToast("Save failed — retry", "error");
      } catch (_) {
        showToast("Save failed — retry", "error");
      }
    }

    const bindItem = (item) => {
      if (item.__tspSortableBound) return;
      item.__tspSortableBound = true;
      // Track whether the most recent mousedown started inside the drag
      // handle. We use this in dragstart to decide whether to allow the
      // drag — keeping the row draggable=true at all times so the browser
      // never decides not to start a drag because of stale state. Text
      // selection inside cells still works because dragstart preventDefault
      // bails out on non-handle drags.
      let mousedownOnHandle = false;
      item.addEventListener("mousedown", (e) => {
        mousedownOnHandle = !!e.target.closest?.(".drag-handle");
      });
      item.addEventListener("dragstart", (e) => {
        if (!mousedownOnHandle) {
          e.preventDefault();
          return;
        }
        dragging = item;
        item.classList.add("dragging");
        originalOrder = snapshotOrder();
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", item.dataset.itemId || ""); } catch (_) {}
      });
      item.addEventListener("dragend", () => {
        item.classList.remove("dragging");
        clearMarkers();
        const currentOrder = snapshotOrder();
        const changed = originalOrder && !orderEqual(originalOrder, currentOrder);
        dragging = null;
        mousedownOnHandle = false;
        const wasOriginal = originalOrder;
        originalOrder = null;
        if (!changed || !url) return;
        if (list.dataset.reorderManual === "1") {
          list.dispatchEvent(new CustomEvent("reorder-changed", { bubbles: true }));
        } else {
          commitImmediate(currentOrder);
        }
      });
      item.addEventListener("dragover", (e) => {
        if (!dragging || dragging === item) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const rect = item.getBoundingClientRect();
        const after = isHorizontal()
          ? (e.clientX - rect.left) > rect.width / 2
          : (e.clientY - rect.top) > rect.height / 2;
        // Tighten the drop indicator: show an inserting line on the
        // exact edge of the target instead of a full-row tint, so the
        // user can see precisely where the row will land.
        clearMarkers();
        item.classList.add(after ? "drop-after" : "drop-before");
        if (after) item.parentNode.insertBefore(dragging, item.nextSibling);
        else item.parentNode.insertBefore(dragging, item);
      });
      item.addEventListener("dragleave", () => {
        item.classList.remove("drop-before", "drop-after", "drag-over");
      });
      // `drop` is intentionally a no-op for the reorder save path — `dragend`
      // is the canonical commit point because it always fires regardless of
      // whether the cursor was over a valid target on release.
      item.addEventListener("drop", (e) => {
        e.preventDefault();
        clearMarkers();
      });
    };
    list.__tspBindItem = bindItem;
    list.querySelectorAll(":scope > [draggable='true'][data-item-id]").forEach(bindItem);
  }
  document.querySelectorAll(".file-list-sortable").forEach(initSortable);
  window.tspInitSortable = initSortable;

  // Minimal toast helper — one element reused for every save.
  function ensureToastHost() {
    let host = document.getElementById("tsp-toast-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "tsp-toast-host";
      host.className = "tsp-toast-host";
      document.body.appendChild(host);
    }
    return host;
  }
  function showToast(msg, kind) {
    const host = ensureToastHost();
    const el = document.createElement("div");
    el.className = "tsp-toast" + (kind === "error" ? " tsp-toast-error" : "");
    el.textContent = msg;
    host.appendChild(el);
    // Trigger transition next frame.
    requestAnimationFrame(() => el.classList.add("tsp-toast-in"));
    setTimeout(() => {
      el.classList.remove("tsp-toast-in");
      el.addEventListener("transitionend", () => el.remove(), { once: true });
      // Fallback cleanup in case transitionend doesn't fire.
      setTimeout(() => el.remove(), 500);
    }, 1600);
  }
  // Expose for manual "Save order" button and other callers.
  window.tspShowToast = showToast;

  // Manual "Save order" buttons for data-reorder-manual sortables.
  document.querySelectorAll("[data-save-reorder-for]").forEach(btn => {
    const sel = btn.dataset.saveReorderFor;
    const list = document.querySelector(sel);
    if (!list) return;
    btn.dataset.labelIdle = btn.textContent.trim();
    list.addEventListener("reorder-changed", () => {
      btn.classList.add("is-dirty");
      btn.textContent = "Save order *";
    });
    btn.addEventListener("click", async () => {
      const url = list.dataset.reorderUrl;
      if (!url) return;
      const order = Array.from(list.querySelectorAll(":scope > [data-item-id]"))
        .map(x => x.dataset.itemId);
      const category = list.dataset.reorderCategory || null;
      const payload = category ? { order, category } : { order };
      btn.disabled = true;
      const orig = btn.dataset.labelIdle;
      btn.textContent = "Saving…";
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("Save failed");
        btn.textContent = "Saved ✓";
        btn.classList.remove("is-dirty");
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1400);
      } catch (_) {
        btn.textContent = "Failed — retry";
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 1800);
      }
    });
  });

  // Yellow save-bar wireup for any data-reorder-manual + data-reorder-savebar
  // sortable list. Matches the Web Frontend admin's save-bar pattern: drag a
  // row, the bar fades in at the bottom-left of the viewport, click Save to
  // commit the order and reload so the rendered list matches the saved one.
  // Used on the library detail page so admins reorder readings without
  // each individual drop firing a save.
  (function reorderSaveBar(){
    const lists = document.querySelectorAll('[data-reorder-savebar="1"]');
    if (!lists.length) return;
    const bar = document.getElementById('library-reorder-save-bar');
    const btn = document.getElementById('library-reorder-save-btn');
    if (!bar || !btn) return;
    const msg = bar.querySelector('.fe-save-bar-msg');
    let dirtyList = null;

    lists.forEach(list => {
      list.addEventListener('reorder-changed', () => {
        dirtyList = list;
        bar.hidden = false;
        bar.classList.remove('is-leaving');
        if (msg) msg.textContent = 'Unsaved changes';
        btn.disabled = false;
        btn.textContent = 'Save';
      });
    });

    btn.addEventListener('click', async () => {
      if (!dirtyList) { bar.hidden = true; return; }
      const url = dirtyList.dataset.reorderUrl;
      if (!url) return;
      btn.disabled = true;
      btn.textContent = 'Saving…';
      const order = Array.from(dirtyList.querySelectorAll(':scope > [data-item-id]'))
        .map(x => x.dataset.itemId);
      const category = dirtyList.dataset.reorderCategory || null;
      const payload = category ? { order, category } : { order };
      try {
        const r = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'same-origin',
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error('save failed: ' + r.status);
        if (msg) msg.textContent = 'Saved';
        const reload = () => window.location.reload();
        bar.addEventListener('animationend', reload, { once: true });
        bar.classList.add('is-leaving');
        setTimeout(reload, 360);
      } catch (_) {
        btn.disabled = false;
        btn.textContent = 'Save';
        if (msg) msg.textContent = 'Save failed — try again';
      }
    });
  })();

  // Inline save for per-file edit accordions (keep modal open)
  document.querySelectorAll("form[data-inline-save]").forEach(form => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      try {
        const res = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        if (!res.ok) throw new Error("Save failed (" + res.status + ")");
        // Update the displayed title with the new value
        const li = form.closest("li");
        const fileMain = li?.querySelector(".file-main");
        const newTitle = form.querySelector('input[name="title"]')?.value?.trim();
        const titleLink = fileMain?.querySelector("a");
        if (titleLink && newTitle) titleLink.textContent = newTitle;
        // Update displayed filename if a new file was uploaded or removed
        const fileInput = form.querySelector('input[type="file"][name="file"]');
        const removeFile = form.querySelector('input[name="remove_file"]:checked');
        let subtitle = fileMain?.querySelector(".muted.smaller");
        if (fileInput?.files?.length) {
          const name = fileInput.files[0].name;
          if (!subtitle) {
            subtitle = document.createElement("div");
            subtitle.className = "muted smaller";
            fileMain.appendChild(subtitle);
          }
          subtitle.textContent = name;
        } else if (removeFile && subtitle) {
          subtitle.remove();
        }
        // Collapse the accordion
        form.classList.add("collapsed");
        // Show an inline success message in the row that auto-fades
        let msg = li.querySelector(".inline-save-msg");
        if (!msg) {
          msg = document.createElement("div");
          msg.className = "inline-save-msg flash flash-success";
          li.querySelector(".file-main").appendChild(msg);
        }
        msg.textContent = "Saved";
        clearTimeout(msg._t);
        msg._t = setTimeout(() => msg.remove(), 2500);
      } catch (err) {
        alert(err.message || "Save failed");
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  });

  // Password reveal toggles (auto-hide after 10s)
  document.querySelectorAll(".reveal-btn").forEach(btn => {
    let hideTimer = null;
    const hide = (pwEl) => {
      pwEl.textContent = "••••••••";
      pwEl.dataset.revealed = "0";
      btn.textContent = "Reveal";
      if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
    };
    btn.addEventListener("click", async () => {
      const pwEl = btn.parentElement.querySelector(".pw-field");
      if (!pwEl) return;
      if (pwEl.dataset.revealed === "1") { hide(pwEl); return; }
      let value = pwEl.dataset.pw || pwEl.dataset.copy;
      if (!value && btn.dataset.revealUrl) {
        try {
          const r = await fetch(btn.dataset.revealUrl);
          const j = await r.json();
          value = j.password || "";
          pwEl.dataset.copy = value;
        } catch (e) { return; }
      }
      if (!value) return;
      pwEl.textContent = value;
      pwEl.dataset.revealed = "1";
      btn.textContent = "Hide";
      if (hideTimer) clearTimeout(hideTimer);
      hideTimer = setTimeout(() => hide(pwEl), 10000);
    });
  });

  // Click-to-copy buttons
  document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      try {
        let value = btn.dataset.copy;
        if (!value && btn.dataset.copyUrl) {
          const r = await fetch(btn.dataset.copyUrl);
          const j = await r.json();
          value = j.password || j.value || "";
        }
        if (!value) throw new Error("empty");
        await navigator.clipboard.writeText(value);
        const original = btn.dataset.tip;
        btn.dataset.tip = "Copied!";
        btn.classList.add("copied");
        setTimeout(() => { btn.dataset.tip = original; btn.classList.remove("copied"); }, 1200);
      } catch (e) { btn.dataset.tip = "Copy failed"; }
    });
  });

  // Reveal Zoom password
  document.querySelectorAll("[data-reveal]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.reveal;
      const target = document.getElementById("pw-" + id);
      if (target.textContent) { target.textContent = ""; btn.textContent = "Show password"; return; }
      try {
        const r = await fetch(`/zoom-accounts/${id}/reveal`);
        const j = await r.json();
        target.textContent = j.password;
        btn.textContent = "Hide";
      } catch (e) { target.textContent = "(error)"; }
    });
  });

  // Clampable text with show-more toggle
  document.querySelectorAll("[data-clampable]").forEach(wrap => {
    const body = wrap.querySelector(".clamp-body");
    const btn = wrap.querySelector("[data-clamp-toggle]");
    if (!body || !btn) return;
    const overflows = body.scrollHeight > body.clientHeight + 1;
    if (!overflows) return;
    btn.hidden = false;
    btn.addEventListener("click", () => {
      const expanded = wrap.classList.toggle("expanded");
      btn.textContent = expanded ? "Show less" : "Show more…";
    });
  });

  // Copy-to-clipboard buttons: <button data-copy-url="/pub/...">
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(() => true).catch(() => fallbackCopy(text));
    }
    return Promise.resolve(fallbackCopy(text));
  }
  function fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:-9999px;top:-9999px;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch(e) {}
    document.body.removeChild(ta);
    return ok;
  }
  document.addEventListener("click", e => {
    const btn = e.target.closest("[data-copy-url]");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const url = new URL(btn.dataset.copyUrl, window.location.origin).href;
    copyText(url).then(ok => {
      const orig = btn.textContent;
      btn.textContent = ok ? "Copied!" : "Failed";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    });
  });

  // Dashboard widget drag-and-drop reorder
  (function initDashboardReorder(){
    const grid = document.querySelector("[data-dashboard-reorder]");
    if (!grid) return;
    const url = grid.dataset.orderUrl;
    let dragging = null;

    grid.querySelectorAll('.dash-widget[draggable="true"]').forEach(w => {
      w.addEventListener("dragstart", (e) => {
        if (e.target.closest("a, button, input, textarea, label, select, canvas")) {
          if (!e.target.classList.contains("dash-drag-handle")) {
            e.preventDefault();
            return;
          }
        }
        dragging = w;
        w.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", w.dataset.widgetKey || ""); } catch(_) {}
      });
      w.addEventListener("dragend", () => {
        w.classList.remove("dragging");
        grid.querySelectorAll(".dash-widget.drag-over").forEach(x => x.classList.remove("drag-over"));
        dragging = null;
      });
      w.addEventListener("dragover", (e) => {
        if (!dragging || dragging === w) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const rect = w.getBoundingClientRect();
        const after = (e.clientY - rect.top) > rect.height / 2;
        w.classList.add("drag-over");
        if (after) grid.insertBefore(dragging, w.nextSibling);
        else grid.insertBefore(dragging, w);
      });
      w.addEventListener("dragleave", () => w.classList.remove("drag-over"));
      w.addEventListener("drop", async (e) => {
        e.preventDefault();
        w.classList.remove("drag-over");
        if (!url) return;
        const order = Array.from(grid.querySelectorAll(".dash-widget[data-widget-key]"))
          .map(x => x.dataset.widgetKey);
        try {
          await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" },
            credentials: "same-origin",
            body: JSON.stringify({ order }),
          });
        } catch (_) {}
      });
    });
  })();

  // Server metrics widget
  (function initServerMetrics(){
    const widget = document.getElementById("server-metrics-widget");
    if (!widget) return;
    if (!widget.querySelector(".server-metrics-column")) return;
    const endpoint = widget.dataset.endpoint;
    const MAX_SAMPLES = 60;
    const series = { cpu: [], mem: [] };
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--brand").trim() || "#0b5cff";

    function fmtBytes(n) {
      if (!n || n < 0) return "0 B";
      const units = ["B","KB","MB","GB","TB"];
      let i = 0, v = n;
      while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
      return v.toFixed(v >= 10 ? 0 : 1) + " " + units[i];
    }
    function fmtUptime(sec) {
      if (sec < 60) return sec + "s";
      const days = Math.floor(sec / 86400); sec %= 86400;
      const hours = Math.floor(sec / 3600); sec %= 3600;
      const mins = Math.floor(sec / 60);
      if (days) return days + "d " + hours + "h";
      if (hours) return hours + "h " + mins + "m";
      return mins + "m";
    }

    function drawSpark(canvas, values) {
      const ctx = canvas.getContext("2d");
      const dpr = window.devicePixelRatio || 1;
      const cssW = canvas.clientWidth || canvas.width;
      const cssH = canvas.clientHeight || canvas.height;
      if (canvas.width !== cssW * dpr || canvas.height !== cssH * dpr) {
        canvas.width = cssW * dpr;
        canvas.height = cssH * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssW, cssH);
      if (!values.length) return;
      const n = values.length;
      const step = n > 1 ? cssW / (MAX_SAMPLES - 1) : 0;
      const startX = cssW - (n - 1) * step;
      const y = v => cssH - (Math.max(0, Math.min(100, v)) / 100) * cssH;
      const path = new Path2D();
      path.moveTo(startX, y(values[0]));
      for (let i = 1; i < n; i++) path.lineTo(startX + i * step, y(values[i]));
      const fill = new Path2D();
      fill.moveTo(startX, cssH);
      fill.lineTo(startX, y(values[0]));
      for (let i = 1; i < n; i++) fill.lineTo(startX + i * step, y(values[i]));
      fill.lineTo(startX + (n - 1) * step, cssH);
      fill.closePath();
      const grad = ctx.createLinearGradient(0, 0, 0, cssH);
      grad.addColorStop(0, accent + "40");
      grad.addColorStop(1, accent + "00");
      ctx.fillStyle = grad;
      ctx.fill(fill);
      ctx.strokeStyle = accent;
      ctx.lineWidth = 1.5;
      ctx.lineJoin = "round";
      ctx.stroke(path);
    }

    function setField(name, value) {
      widget.querySelectorAll('[data-field="' + name + '"]').forEach(el => { el.textContent = value; });
    }

    async function tick() {
      try {
        const r = await fetch(endpoint, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" }});
        if (!r.ok) return;
        const d = await r.json();
        series.cpu.push(d.cpu_percent);
        series.mem.push(d.memory_percent);
        if (series.cpu.length > MAX_SAMPLES) series.cpu.shift();
        if (series.mem.length > MAX_SAMPLES) series.mem.shift();
        setField("os", d.os + (d.host_mode ? "" : " (container)"));
        setField("cpu_percent", d.cpu_percent.toFixed(0));
        setField("memory_percent", d.memory_percent.toFixed(0));
        setField("memory_detail", fmtBytes(d.memory_used) + " / " + fmtBytes(d.memory_total));
        setField("load_avg", d.load_avg.map(n => n.toFixed(2)).join(" · "));
        setField("uptime", fmtUptime(d.uptime_seconds));
        setField("cpu_count", d.cpu_count + " core" + (d.cpu_count === 1 ? "" : "s") + " · " + d.hostname);
        widget.querySelectorAll(".metric-spark").forEach(c => {
          drawSpark(c, series[c.dataset.series] || []);
        });
      } catch (_) {}
    }

    tick();
    const h = setInterval(tick, 5000);
    window.addEventListener("beforeunload", () => clearInterval(h));
  })();

  (function initOnlineUsers(){
    const tile = document.getElementById("online-users-tile");
    if (!tile) return;
    const endpoint = tile.dataset.endpoint;
    const countEl = tile.querySelector('[data-field="online_count"]');
    const labelEl = tile.querySelector('[data-field="online_label"]');

    function render(count, users) {
      if (countEl) countEl.textContent = count;
      if (labelEl) labelEl.textContent = (count === 1 ? "user" : "users") + " · last 5 min";
      tile.title = users.length
        ? users.map(u => u.username + " (" + u.role + ")").join(", ")
        : "No one online right now.";
    }

    async function tick() {
      try {
        const r = await fetch(endpoint, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" }});
        if (!r.ok) return;
        const d = await r.json();
        render(d.count || 0, d.users || []);
      } catch (_) {}
    }

    const h = setInterval(tick, 30000);
    window.addEventListener("beforeunload", () => clearInterval(h));
  })();
})();

// ── MEGA MENU AJAX (ADD BLOCK / ADD COLUMN / DELETE) ────────────────────────
// Keep the admin on the page so in-progress edits aren't lost. The server
// returns rendered HTML for add operations and {ok} for deletes; JS splices
// the DOM directly.
(function () {
  const toast = (msg, kind) => (window.tspShowToast || (() => {}))(msg, kind);

  async function postForm(form, extraHeaders) {
    const r = await fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      headers: Object.assign(
        { "X-Requested-With": "fetch", "Accept": "application/json" },
        extraHeaders || {}
      ),
      body: new FormData(form),
    });
    if (!r.ok) throw new Error("request failed");
    return r.json();
  }

  function htmlToNode(html) {
    const tmp = document.createElement("div");
    tmp.innerHTML = (html || "").trim();
    return tmp.firstElementChild;
  }

  // Rebind any .file-list-sortable containers introduced by a newly-added
  // column so drag-and-drop works on their nested items.
  function rebindSortable(root) {
    root.querySelectorAll?.(".file-list-sortable").forEach((list) => {
      if (list.__tspSortableHost) return;
      // Skip — handled by the DOMContentLoaded binder below. But for nodes
      // added after DOMContentLoaded, we simulate the same binding by
      // triggering our sortable init pass on this element.
    });
  }

  // Add block (+ Link / + Title / + Button / + Section)
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest?.("form[data-add-block-target]");
    if (!form) return;
    e.preventDefault();
    const target = document.querySelector(form.getAttribute("data-add-block-target"));
    if (!target) return;
    const btn = form.querySelector("button");
    if (btn) btn.disabled = true;
    try {
      const data = await postForm(form);
      const node = htmlToNode(data && data.html);
      if (!node) throw new Error("empty html");
      target.appendChild(node);
      if (typeof target.__tspBindItem === "function") target.__tspBindItem(node);
      node.scrollIntoView({ behavior: "smooth", block: "nearest" });
      const labelInput = node.querySelector('input[data-block-field="label"]');
      if (labelInput) { labelInput.focus(); labelInput.select(); }
    } catch (_) {
      toast("Could not add block — retry", "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // Add column
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest?.("form[data-add-column-form]");
    if (!form) return;
    e.preventDefault();
    const target = document.querySelector(form.getAttribute("data-target"));
    if (!target) return;
    const btn = form.querySelector("button");
    if (btn) btn.disabled = true;
    try {
      const data = await postForm(form);
      const node = htmlToNode(data && data.html);
      if (!node) throw new Error("empty html");
      target.appendChild(node);
      // Bind drag on the new column itself (sibling of existing columns)
      if (typeof target.__tspBindItem === "function") target.__tspBindItem(node);
      // The new column contains its own .file-list-sortable <ul> for blocks;
      // initialise it so future block adds / drags work.
      if (typeof window.tspInitSortable === "function") {
        node.querySelectorAll(".file-list-sortable").forEach(window.tspInitSortable);
      }
      rebindSortable(node);
      node.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (_) {
      toast("Could not add column — retry", "error");
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // Delete block / delete column (shared)
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest?.("form[data-delete-block-form], form[data-delete-column-form]");
    if (!form) return;
    e.preventDefault();
    // The existing inline onsubmit="return confirm(...)" was bypassed by our
    // preventDefault; ask here instead.
    const isCol = form.hasAttribute("data-delete-column-form");
    const msg = isCol ? "Delete this column and all its links?" : "Delete this block?";
    if (!window.confirm(msg)) return;
    const targetSel = form.getAttribute("data-target-item");
    const targetNode = targetSel ? document.querySelector(targetSel) : null;
    try {
      const r = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch", "Accept": "application/json" },
        body: new FormData(form),
      });
      if (!r.ok) throw new Error("delete failed");
      if (targetNode) targetNode.remove();
      toast(isCol ? "Column removed" : "Block removed", "success");
    } catch (_) {
      toast("Could not delete — retry", "error");
    }
  });
})();

// ── MEGA MENU BULK SAVE ─────────────────────────────────────────────────────
// Gather all block inputs inside an editor and POST them as one JSON payload.
// Triggered by any button with [data-save-megamenu-for="<selector>"].
(function () {
  function collectBlocks(editor) {
    const out = [];
    editor.querySelectorAll("li.nav-megalink[data-item-id]").forEach((li) => {
      const id = li.getAttribute("data-item-id");
      const kind = li.getAttribute("data-block-kind") || "link";
      const block = { id, kind };
      li.querySelectorAll("[data-block-field]").forEach((el) => {
        const name = el.getAttribute("data-block-field");
        if (el.type === "checkbox") block[name] = el.checked;
        else if (el.type === "radio") {
          // Radios share a `data-block-field`; only record the checked one.
          if (el.checked) block[name] = el.value;
          else if (!(name in block)) block[name] = "";
        }
        else block[name] = el.value;
      });
      out.push(block);
    });
    return out;
  }

  async function save(btn) {
    const sel = btn.getAttribute("data-save-megamenu-for");
    const url = btn.getAttribute("data-save-url");
    const editor = sel && document.querySelector(sel);
    if (!editor || !url) return;
    const toast = window.tspShowToast || (() => {});
    const origLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ blocks: collectBlocks(editor) }),
      });
      if (!r.ok) throw new Error("save failed");
      editor.querySelectorAll(".nav-megalink.is-dirty").forEach((el) =>
        el.classList.remove("is-dirty"));
      btn.classList.remove("is-dirty");
      toast("Changes saved", "success");
    } catch (_) {
      toast("Save failed — retry", "error");
    } finally {
      btn.disabled = false;
      btn.textContent = origLabel;
    }
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-save-megamenu-for]");
    if (!btn) return;
    e.preventDefault();
    save(btn);
  });

  // Override-color toggle: enable/disable the color picker inline.
  document.addEventListener("change", (e) => {
    const toggle = e.target.closest("[data-color-override-toggle]");
    if (!toggle) return;
    const field = toggle.closest("[data-color-override-field]");
    if (!field) return;
    const picker = field.querySelector('input[type="color"][data-block-field="custom_color"]');
    field.classList.toggle("is-on", toggle.checked);
    if (picker) picker.disabled = !toggle.checked;
  });

  // Mark the editor + save button dirty on any field change, so the user has a
  // visible "unsaved changes" signal until they click Save.
  document.addEventListener("input", (e) => {
    const el = e.target.closest("[data-block-field]");
    if (!el) return;
    const li = el.closest("li.nav-megalink");
    if (li) li.classList.add("is-dirty");
    const editor = el.closest(".nav-megamenu-editor");
    if (!editor) return;
    const btn = document.querySelector(
      '[data-save-megamenu-for="#' + editor.id + '"]'
    );
    if (btn) btn.classList.add("is-dirty");
  });
  document.addEventListener("change", (e) => {
    const el = e.target.closest("[data-block-field]");
    if (!el) return;
    const li = el.closest("li.nav-megalink");
    if (li) li.classList.add("is-dirty");
    const editor = el.closest(".nav-megamenu-editor");
    if (!editor) return;
    const btn = document.querySelector(
      '[data-save-megamenu-for="#' + editor.id + '"]'
    );
    if (btn) btn.classList.add("is-dirty");
  });
})();

// ── VERSION WATCHER ─────────────────────────────────────────────────────────
// Polls /api/version once a minute. If the deployed APP_VERSION has moved
// past the version this page was served with, a non-blocking banner appears
// offering a reload. We never auto-reload — the user clicks Reload when
// they're at a safe stopping point.
(function () {
  const meta = document.querySelector('meta[name="app-version"]');
  const bootVersion = meta ? (meta.content || "").trim() : "";
  const bootBuildId = meta ? (meta.getAttribute("data-build-id") || "").trim() : "";
  const checkUrl = meta ? (meta.getAttribute("data-check-url") || "/api/version") : "/api/version";
  if (!bootVersion) return;

  const CHECK_INTERVAL_MS = 60 * 1000;
  const REPROMPT_AFTER_MS = 10 * 60 * 1000;
  let bannerShown = false;

  async function check() {
    if (bannerShown) return;
    try {
      const r = await fetch(checkUrl, { cache: "no-store", credentials: "same-origin" });
      if (!r.ok) return;
      const data = await r.json();
      const serverVersion = (data && data.version) || "";
      const serverBuildId = (data && data.build_id) || "";
      const versionChanged = serverVersion && serverVersion !== bootVersion;
      const buildChanged = serverBuildId && bootBuildId && serverBuildId !== bootBuildId;
      if (versionChanged || buildChanged) showBanner(serverVersion);
    } catch (_) { /* silent — try again next tick */ }
  }

  function showBanner(newVersion) {
    if (bannerShown) return;
    bannerShown = true;
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => (
      {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]
    ));
    const el = document.createElement("div");
    el.id = "tsp-version-banner";
    el.className = "version-update-banner";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.innerHTML =
      '<div class="version-update-banner-main">' +
        '<div class="version-update-banner-title">Update available — v' + esc(newVersion) + '</div>' +
        '<div class="version-update-banner-sub">Reload when you’re at a stopping point to pick up the latest changes.</div>' +
      '</div>' +
      '<div class="version-update-banner-actions">' +
        '<button type="button" class="btn btn-sm" data-version-dismiss>Later</button>' +
        '<button type="button" class="btn btn-sm btn-primary" data-version-reload>Reload now</button>' +
      '</div>';
    document.body.appendChild(el);
    el.querySelector("[data-version-dismiss]").addEventListener("click", () => {
      el.remove();
      setTimeout(() => { bannerShown = false; check(); }, REPROMPT_AFTER_MS);
    });
    el.querySelector("[data-version-reload]").addEventListener("click", () => {
      window.location.reload();
    });
  }

  setTimeout(check, 10000);
  setInterval(check, CHECK_INTERVAL_MS);
})();

// ── LAYOUT BUILDER (drag-and-drop block composer) ─────────────────────────
// Library blocks are drag-sources; the canvas is the drop-zone. Canvas
// blocks themselves are re-orderable via the same dragstart/dragover
// handlers. Save POSTs the resulting block sequence to the backend.
(function feLayoutBuilder() {
  document.querySelectorAll(".fe-layout-builder-modal").forEach(modal => {
    const canvas = modal.querySelector("[data-builder-canvas]");
    const library = modal.querySelector("[data-builder-library]");
    const saveBtn = modal.querySelector("[data-builder-save]");
    const nameInp = modal.querySelector("[data-builder-name]");
    const titleEl = modal.querySelector("[data-builder-title]");
    const saveUrl = modal.dataset.saveLayoutUrl;
    const updateUrlTpl = modal.dataset.updateLayoutUrl;     // contains __KEY__
    const deleteUrlTpl = modal.dataset.deleteLayoutUrl;     // contains __KEY__
    const activateUrl = modal.dataset.activateUrl;
    const activateField = modal.dataset.activateField;
    const csrf = modal.dataset.csrfToken;
    if (!canvas || !library || !saveBtn) return;

    const SVG_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true";';

    function refreshEmpty() {
      const hasBlocks = !!canvas.querySelector(".fe-builder-canvas-block");
      let empty = canvas.querySelector(".fe-builder-empty");
      if (!hasBlocks && !empty) {
        empty = document.createElement("div");
        empty.className = "fe-builder-empty muted small";
        empty.textContent = "Drag a block here to start.";
        canvas.appendChild(empty);
      } else if (hasBlocks && empty) {
        empty.remove();
      }
    }
    function makeCanvasBlock(type, name, iconHtml, opts) {
      const el = document.createElement("div");
      el.draggable = true;
      el.dataset.blockType = type;
      // Preserve split-level settings (width / margin / padding) on the
      // DOM node so the round-trip through the builder doesn't blow away
      // values the homepage admin's split settings card has written. The
      // builder itself doesn't expose UI for these — they're stored, not
      // shown — but they MUST survive serialize → save unchanged.
      if (type === "split" && opts) {
        if (opts.width)   el.dataset.splitWidth   = opts.width;
        if (opts.margin)  el.dataset.splitMargin  = opts.margin;
        if (opts.padding) el.dataset.splitPadding = opts.padding;
      }
      if (type === "split") {
        el.className = "fe-builder-canvas-block fe-builder-split";
        el.innerHTML =
          '<div class="fe-builder-split-head">' +
            '<div class="fe-builder-block-icon">' + (iconHtml || '') + '</div>' +
            '<div class="fe-builder-block-meta"><div class="fe-builder-block-name">' +
            escapeHtml(name) + '</div><div class="fe-builder-block-desc muted smaller">' +
            'Two side-by-side panels — drag blocks into each.</div></div>' +
            '<button type="button" class="fe-builder-canvas-remove" title="Remove">&times;</button>' +
          '</div>' +
          '<div class="fe-builder-split-cols">' +
            '<div class="fe-builder-split-col" data-split-side="left">' +
              '<div class="fe-builder-empty muted smaller">Left panel</div>' +
            '</div>' +
            '<div class="fe-builder-split-col" data-split-side="right">' +
              '<div class="fe-builder-empty muted smaller">Right panel</div>' +
            '</div>' +
          '</div>';
      } else {
        el.className = "fe-builder-canvas-block";
        el.innerHTML =
          '<div class="fe-builder-block-icon">' + (iconHtml || '') + '</div>' +
          '<div class="fe-builder-block-meta"><div class="fe-builder-block-name">' +
          escapeHtml(name) + '</div></div>' +
          '<button type="button" class="fe-builder-canvas-remove" title="Remove">&times;</button>';
      }
      return el;
    }
    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[c]));
    }

    // Library blocks: drag → set type, on drop in canvas → append.
    library.querySelectorAll(".fe-builder-block").forEach(block => {
      block.addEventListener("dragstart", e => {
        e.dataTransfer.effectAllowed = "copy";
        e.dataTransfer.setData("application/x-fe-block-type", block.dataset.blockType);
        e.dataTransfer.setData("application/x-fe-block-name", block.dataset.blockName);
        e.dataTransfer.setData("text/plain", block.dataset.blockName);
      });
    });

    // Canvas drag handlers: accept new blocks from library, reorder existing.
    // Both the top-level canvas AND each .fe-builder-split-col panel are
    // valid drop zones; we look up the closest such zone on dragover/drop.
    let dragging = null;
    function dropZoneFor(target) {
      return target.closest(".fe-builder-split-col") || target.closest("[data-builder-canvas]");
    }
    function handleDragOver(e) {
      const zone = dropZoneFor(e.target);
      if (!zone) return;
      e.preventDefault();
      e.stopPropagation();
      // Highlight only the active zone.
      modal.querySelectorAll(".is-drop-target").forEach(el => el.classList.remove("is-drop-target"));
      zone.classList.add("is-drop-target");
      if (dragging) {
        // Don't allow nesting splits inside splits — too much complexity.
        if (dragging.dataset.blockType === "split" && zone.classList.contains("fe-builder-split-col")) return;
        const after = [...zone.querySelectorAll(":scope > .fe-builder-canvas-block:not(.dragging)")]
          .find(b => e.clientY < b.getBoundingClientRect().top + b.offsetHeight / 2);
        if (after) zone.insertBefore(dragging, after);
        else zone.appendChild(dragging);
      }
    }
    function handleDrop(e) {
      const zone = dropZoneFor(e.target);
      if (!zone) return;
      e.preventDefault();
      e.stopPropagation();
      modal.querySelectorAll(".is-drop-target").forEach(el => el.classList.remove("is-drop-target"));
      if (dragging) { return; }   // reorder case is handled by dragover
      const type = e.dataTransfer.getData("application/x-fe-block-type");
      const name = e.dataTransfer.getData("application/x-fe-block-name");
      if (!type) return;
      // Block split from being placed inside another split's panel.
      if (type === "split" && zone.classList.contains("fe-builder-split-col")) return;
      const libBlock = library.querySelector(
        '.fe-builder-block[data-block-type="' + CSS.escape(type) + '"]');
      const iconHtml = libBlock ? libBlock.querySelector(".fe-builder-block-icon").innerHTML : '';
      // Drop the placeholder if present.
      zone.querySelectorAll(":scope > .fe-builder-empty").forEach(el => el.remove());
      zone.appendChild(makeCanvasBlock(type, name, iconHtml));
      refreshEmpty();
    }
    canvas.addEventListener("dragover", handleDragOver);
    canvas.addEventListener("dragleave", e => {
      const zone = dropZoneFor(e.target);
      if (zone) zone.classList.remove("is-drop-target");
    });
    canvas.addEventListener("drop", handleDrop);

    canvas.addEventListener("dragstart", e => {
      const block = e.target.closest(".fe-builder-canvas-block");
      if (!block) return;
      dragging = block;
      block.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    canvas.addEventListener("dragend", () => {
      if (dragging) dragging.classList.remove("dragging");
      dragging = null;
      modal.querySelectorAll(".is-drop-target").forEach(el => el.classList.remove("is-drop-target"));
      refreshEmpty();
    });
    canvas.addEventListener("click", e => {
      const rm = e.target.closest(".fe-builder-canvas-remove");
      if (!rm) return;
      const block = rm.closest(".fe-builder-canvas-block");
      if (block) block.remove();
      refreshEmpty();
    });

    function serializeBlocks(zone) {
      // Walk direct children of `zone` and capture nested split panels.
      return [...zone.querySelectorAll(":scope > .fe-builder-canvas-block")].map(b => {
        const t = b.dataset.blockType;
        if (t === "split") {
          const left = b.querySelector('.fe-builder-split-col[data-split-side="left"]');
          const right = b.querySelector('.fe-builder-split-col[data-split-side="right"]');
          const out = {
            type: "split",
            left: left ? serializeBlocks(left) : [],
            right: right ? serializeBlocks(right) : [],
          };
          // Round-trip width / margin / padding stashed in the dataset
          // when this block was hydrated from an existing layout, so
          // editing the structure doesn't drop spacing settings the
          // homepage admin's split card has written.
          if (b.dataset.splitWidth)   out.width   = b.dataset.splitWidth;
          if (b.dataset.splitMargin)  out.margin  = b.dataset.splitMargin;
          if (b.dataset.splitPadding) out.padding = b.dataset.splitPadding;
          return out;
        }
        return { type: t };
      });
    }

    // Restore the canvas to its empty state (drop placeholder only).
    function clearCanvas() {
      canvas.innerHTML = '<div class="fe-builder-empty muted small">Drag a block here to start.</div>';
    }

    // Inverse of serializeBlocks: takes a [{type, left?, right?}, …] list
    // and rebuilds DOM nodes inside the given drop-zone. Used for Edit
    // mode so the canvas reflects the layout being modified.
    function blockNameForType(type) {
      const lib = library.querySelector(
        '.fe-builder-block[data-block-type="' + CSS.escape(type) + '"]');
      return lib ? lib.dataset.blockName : type;
    }
    function blockIconForType(type) {
      const lib = library.querySelector(
        '.fe-builder-block[data-block-type="' + CSS.escape(type) + '"]');
      return lib ? lib.querySelector(".fe-builder-block-icon").innerHTML : '';
    }
    function hydrateZone(zone, blocks) {
      zone.querySelectorAll(":scope > .fe-builder-empty").forEach(el => el.remove());
      (blocks || []).forEach(b => {
        const t = b && b.type;
        if (!t) return;
        const splitOpts = (t === "split")
          ? { width: b.width, margin: b.margin, padding: b.padding }
          : null;
        const node = makeCanvasBlock(t, blockNameForType(t), blockIconForType(t), splitOpts);
        zone.appendChild(node);
        if (t === "split") {
          const left = node.querySelector('.fe-builder-split-col[data-split-side="left"]');
          const right = node.querySelector('.fe-builder-split-col[data-split-side="right"]');
          if (left) {
            left.querySelectorAll(":scope > .fe-builder-empty").forEach(el => el.remove());
            hydrateZone(left, b.left || []);
          }
          if (right) {
            right.querySelectorAll(":scope > .fe-builder-empty").forEach(el => el.remove());
            hydrateZone(right, b.right || []);
          }
          // Re-add empty placeholders if a side ended up empty.
          [left, right].forEach(side => {
            if (side && !side.querySelector(":scope > .fe-builder-canvas-block")) {
              const ph = document.createElement("div");
              ph.className = "fe-builder-empty muted smaller";
              ph.textContent = side.dataset.splitSide === "left" ? "Left panel" : "Right panel";
              side.appendChild(ph);
            }
          });
        }
      });
      refreshEmpty();
    }

    // Edit mode is signaled by setting modal.dataset.editKey before opening.
    // The picker macro stores the layout's blocks JSON + name on each card;
    // the click handler below copies them into the modal before opening.
    function enterCreateMode() {
      delete modal.dataset.editKey;
      if (titleEl) titleEl.textContent = "Build a custom layout";
      if (nameInp) nameInp.value = "";
      saveBtn.textContent = "Save layout";
      clearCanvas();
    }
    function enterEditMode(key, name, blocks) {
      modal.dataset.editKey = key;
      if (titleEl) titleEl.textContent = "Edit layout";
      if (nameInp) nameInp.value = name || "";
      saveBtn.textContent = "Save changes";
      clearCanvas();
      hydrateZone(canvas, blocks);
    }

    // Wire the edit / delete icon buttons on each non-prebuilt layout card
    // in the picker grid (not inside the modal — these live in the picker
    // modal that opens this builder modal). We use document-level
    // delegation so only the builder modal whose data-builder-modal id
    // matches reacts.
    const builderModalId = modal.id;
    document.addEventListener("click", async (e) => {
      const editBtn = e.target.closest("[data-edit-layout]");
      if (editBtn && editBtn.getAttribute("data-builder-modal") === builderModalId) {
        e.preventDefault(); e.stopPropagation();
        const card = editBtn.closest(".template-card");
        if (!card) return;
        let blocks = [];
        try { blocks = JSON.parse(card.dataset.layoutBlocks || "[]"); } catch (_) {}
        enterEditMode(card.dataset.layoutKey, card.dataset.layoutName, blocks);
        // Close the picker modal and open the builder modal.
        const pickerModal = card.closest(".fe-layout-picker-modal");
        if (pickerModal) {
          pickerModal.classList.remove("open");
          pickerModal.setAttribute("aria-hidden", "true");
        }
        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
        return;
      }
      const delBtn = e.target.closest("[data-delete-layout]");
      if (delBtn) {
        // Only the matching modal should handle this — but since there's
        // typically just one builder modal per page, all instances will
        // see the click. Guard by checking the URL template exists.
        if (!deleteUrlTpl) return;
        e.preventDefault(); e.stopPropagation();
        const key = delBtn.getAttribute("data-delete-layout");
        const card = delBtn.closest(".template-card");
        if (!confirm("Delete this layout? Any page currently using it will fall back to the Classic layout.")) return;
        try {
          const url = deleteUrlTpl.replace("__KEY__", encodeURIComponent(key));
          const fd = new FormData(); fd.append("csrf_token", csrf);
          const r = await fetch(url, { method: "POST", credentials: "same-origin", body: fd });
          const data = await r.json();
          if (!r.ok || !data.ok) throw new Error(data.error || "Delete failed");
          if (card && card.classList.contains("active")) {
            // The active layout was deleted; reload so the picker reflects
            // the fallback the server picked (classic).
            window.location.reload();
          } else if (card) {
            card.remove();
          }
        } catch (err) {
          (window.tspShowToast || alert)("Could not delete layout: " + (err.message || ""));
        }
        return;
      }
      const newBtn = e.target.closest("[data-builder-mode-create]");
      if (newBtn && newBtn.getAttribute("data-open-modal") === builderModalId) {
        // Reset to create mode every time the "+ Custom layout" tile is
        // clicked, so editing then bailing then creating doesn't smuggle
        // the prior layout's state into a new save.
        enterCreateMode();
      }
    });

    saveBtn.addEventListener("click", async () => {
      const blocks = serializeBlocks(canvas);
      if (!blocks.length) {
        (window.tspShowToast || alert)("Add at least one block before saving.");
        return;
      }
      const name = (nameInp && nameInp.value.trim()) || "Custom layout";
      const editKey = modal.dataset.editKey;
      saveBtn.disabled = true;
      const orig = saveBtn.textContent;
      saveBtn.textContent = "Saving…";
      try {
        const url = editKey
          ? updateUrlTpl.replace("__KEY__", encodeURIComponent(editKey))
          : saveUrl;
        const r = await fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({ name, blocks }),
        });
        const data = await r.json();
        if (!r.ok || !data.ok) throw new Error(data.error || "Save failed");
        // Auto-activate: tell the picker form to use the saved layout for
        // this page. Skip when editing the layout that's already active
        // (a re-POST of the same value would just be a no-op).
        if (activateUrl && activateField && data.key) {
          const fd = new FormData();
          fd.append("csrf_token", csrf);
          fd.append(activateField, data.key);
          await fetch(activateUrl, {
            method: "POST", credentials: "same-origin", body: fd,
          }).catch(() => {});
        }
        window.location.reload();
      } catch (e) {
        saveBtn.disabled = false;
        saveBtn.textContent = orig;
        (window.tspShowToast || alert)("Could not save layout: " + (e.message || ""));
      }
    });
  });
})();

// ── COLLAPSIBLE CARDS (Web Frontend admin) ─────────────────────────────────
// Adds a chevron toggle to every .card inside .fe-admin-main. Clicking the
// chevron OR anywhere on the .card-head (excluding nested buttons / links /
// inputs) toggles the .is-collapsed class. State is remembered per-page in
// localStorage so cards stay collapsed across reloads.
(function feCollapsibleCards() {
  const main = document.querySelector(".fe-admin-main");
  if (!main) return;

  const STORAGE_KEY = "fe-card-collapse:" + window.location.pathname;
  let stored = {};
  try { stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch (_) {}

  // Each card needs a stable id so we can persist its state across reloads.
  // Use the heading text as the key; it's stable per-page.
  function cardKey(card) {
    const h = card.querySelector(".card-head h2");
    return h ? h.textContent.trim() : null;
  }
  function persist() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(stored)); } catch (_) {}
  }

  // Lucide chevron-up SVG paths; matches the rest of the icon set.
  const CHEVRON_SVG =
    '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="m18 15-6-6-6 6"/></svg>';

  function decorate(card) {
    if (card.__feCollapseInit) return;
    card.__feCollapseInit = true;
    const head = card.querySelector(".card-head");
    if (!head) return;

    // Inject the chevron toggle button at the end of card-head.
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "fe-card-toggle";
    btn.setAttribute("aria-label", "Toggle section");
    btn.innerHTML = CHEVRON_SVG;
    head.appendChild(btn);

    // Restore persisted state.
    const key = cardKey(card);
    if (key && stored[key]) card.classList.add("is-collapsed");
    btn.setAttribute("aria-expanded", card.classList.contains("is-collapsed") ? "false" : "true");

    function toggle() {
      card.classList.toggle("is-collapsed");
      const isCollapsed = card.classList.contains("is-collapsed");
      btn.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
      const k = cardKey(card);
      if (k) {
        if (isCollapsed) stored[k] = 1; else delete stored[k];
        persist();
      }
    }

    // Click handler bound to the card itself so the entire card surface is
    // clickable when collapsed. When expanded the click zone extends from
    // the top of the card down through the heading's bottom edge — the
    // strip of padding above the heading is included so the title row
    // doesn't have a dead zone above it. Clicks inside the body still
    // interact with form fields normally instead of collapsing the card.
    card.addEventListener("click", (e) => {
      const interactive = e.target.closest("button, a, input, select, textarea, label, .row-actions");
      if (interactive && interactive !== btn) return;
      const isCollapsed = card.classList.contains("is-collapsed");
      if (isCollapsed) { toggle(); return; }
      // Expanded: only toggle if the click is at or above the heading's
      // bottom edge (i.e. inside the head row OR in the card padding
      // above it).
      const headRect = head.getBoundingClientRect();
      if (e.clientY <= headRect.bottom) toggle();
    });
  }

  main.querySelectorAll(".card").forEach(decorate);

  // Pick up cards added later (modal-rendered, fetch-injected, etc).
  const mo = new MutationObserver(records => {
    for (const r of records) {
      r.addedNodes.forEach(n => {
        if (n.nodeType !== 1) return;
        if (n.classList && n.classList.contains("card")) decorate(n);
        n.querySelectorAll && n.querySelectorAll(".card").forEach(decorate);
      });
    }
  });
  mo.observe(main, { childList: true, subtree: true });
})();

// ── TEMPLATE-PICKER LIVE HIGHLIGHT ─────────────────────────────────────────
// When the user picks a different template radio inside a .template-library
// -grid the visual .active class needs to follow so they can confirm which
// card will be submitted. Server only marks the originally-active one.
(function () {
  document.addEventListener("change", (e) => {
    const inp = e.target;
    if (!inp || inp.type !== "radio") return;
    const grid = inp.closest(".template-library-grid");
    if (!grid) return;
    const newCard = inp.closest(".template-card");
    grid.querySelectorAll(".template-card.active").forEach(c => c.classList.remove("active"));
    if (newCard) newCard.classList.add("active");
  });
})();

// ── FRONTEND-ADMIN SAVE BAR ────────────────────────────────────────────────
// One yellow bar pinned to the sidebar that batches saves across every
// tracked form on the page. Show + bounce when anything becomes dirty;
// click to POST every dirty form sequentially, then reload so the freshly
// rendered admin sees its own values.
(function feSaveBar(){
  const bar = document.getElementById('fe-save-bar');
  const main = document.querySelector('.fe-admin-main');
  if (!bar || !main) return;
  const btn = document.getElementById('fe-save-bar-btn');
  const msg = bar.querySelector('.fe-save-bar-msg');
  const dirty = new Set();

  document.body.classList.add('has-fe-save-bar');

  function show() {
    bar.hidden = false;
    msg.textContent = dirty.size > 1
      ? 'Unsaved changes (' + dirty.size + ' sections)'
      : 'Unsaved changes';
  }
  function hide() {
    bar.hidden = true;
    dirty.clear();
  }

  function trackable(form) {
    if (!form.method || form.method.toLowerCase() !== 'post') return false;
    if (form.closest('.modal')) return false;             // skip in-modal forms
    if (form.matches('[data-fe-skip-save-bar]')) return false;
    // Skip the dashboard's auto-submitting toggle (clicking it navigates the
    // page itself; nothing for us to track).
    if (form.matches('[data-fe-auto-submit]')) return false;
    return true;
  }

  function instrument(form) {
    if (form.__feSaveBound) return;
    form.__feSaveBound = true;
    const onChange = () => { dirty.add(form); show(); };
    form.addEventListener('input', onChange);
    form.addEventListener('change', onChange);
  }
  main.querySelectorAll('form').forEach(f => { if (trackable(f)) instrument(f); });

  // Some forms are spliced in later (e.g. mega menu blocks via fetch); pick
  // them up via a MutationObserver so they participate too.
  const mo = new MutationObserver(records => {
    for (const r of records) {
      r.addedNodes.forEach(n => {
        if (n.nodeType !== 1) return;
        if (n.tagName === 'FORM' && trackable(n)) instrument(n);
        n.querySelectorAll && n.querySelectorAll('form').forEach(f => {
          if (trackable(f)) instrument(f);
        });
      });
    }
  });
  mo.observe(main, { childList: true, subtree: true });

  btn && btn.addEventListener('click', async () => {
    if (!dirty.size) { hide(); return; }
    btn.disabled = true;
    const origLabel = btn.textContent;
    btn.textContent = 'Saving…';
    const forms = [...dirty];
    try {
      for (const f of forms) {
        const fd = new FormData(f);
        const r = await fetch(f.action || window.location.href, {
          method: 'POST',
          credentials: 'same-origin',
          body: fd,
        });
        if (!r.ok) throw new Error('save failed: ' + r.status);
      }
      // Animate the bar dropping out of view, then reload so the freshly
      // saved values are reflected in the form fields.
      msg.textContent = 'Saved';
      const reload = () => window.location.reload();
      bar.addEventListener('animationend', reload, { once: true });
      bar.classList.add('is-leaving');
      // Safety net: if the animationend doesn't fire (reduced-motion etc.)
      // reload anyway after the keyframe duration.
      setTimeout(reload, 360);
    } catch (_) {
      btn.disabled = false;
      btn.textContent = origLabel;
      msg.textContent = 'Save failed — try again';
    }
  });
})();


// ── ICON PICKER MODAL ───────────────────────────────────────────────────────
// Triggered by any button with [data-open-icon-picker]. The trigger stores
// selector strings pointing at the hidden icon-name, color, and size inputs
// it should write back into. Two sources feed the grid: the Lucide catalog
// JSON (bundled, fetched once and cached) and the user's Custom icons
// (server-backed list plus upload/delete endpoints).
(function () {
  const modal = document.getElementById("icon-picker-modal");
  if (!modal) return;

  const DEFAULT_COLOR = "#747474";
  const DEFAULT_SIZE = 20;
  const SVG_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';

  let catalog = null;             // Lucide JSON
  let catalogPromise = null;
  let customIcons = [];           // array of {id, name, url, ref}
  let customPromise = null;

  let activeTrigger = null;
  let activeField = null;
  let activeIconInput = null;
  let activeColorInput = null;
  let activeSizeInput = null;
  let activePreview = null;
  let pendingRef = "";   // deferred-commit: icon ref currently highlighted in the grid

  const catalogUrl = modal.getAttribute("data-catalog-url");
  const customListUrl = modal.getAttribute("data-custom-list-url");
  const customUploadUrl = modal.getAttribute("data-custom-upload-url");
  const customDeleteUrlTpl = modal.getAttribute("data-custom-delete-url"); // ends with /0/delete
  const csrfToken = modal.getAttribute("data-csrf-token");

  const searchEl = modal.querySelector("[data-icon-search]");
  const catalogEl = modal.querySelector("[data-icon-catalog]");
  const modalColorEl = modal.querySelector("[data-icon-modal-color]");
  const modalSizeEl = modal.querySelector("[data-icon-modal-size]");
  const modalSizeOut = modal.querySelector("[data-icon-size-out]");
  const uploadInput = modal.querySelector("[data-icon-upload]");
  const removeBtn = modal.querySelector("[data-icon-picker-remove]");
  const saveBtn = modal.querySelector("[data-icon-picker-save]");

  function renderSvg(paths) {
    return '<svg class="icon" ' + SVG_ATTRS + '>' + paths + '</svg>';
  }
  function renderCustom(ci) {
    return '<img class="icon icon-custom" src="' + escapeAttr(ci.url) +
           '" alt="' + escapeAttr(ci.name) + '">';
  }

  function loadCatalog() {
    if (catalog) return Promise.resolve(catalog);
    if (catalogPromise) return catalogPromise;
    catalogPromise = fetch(catalogUrl, { credentials: "same-origin" })
      .then(r => r.json())
      .then(data => { catalog = data; return data; })
      .catch(() => null);
    return catalogPromise;
  }

  function loadCustom() {
    if (customPromise) return customPromise;
    customPromise = fetch(customListUrl, { credentials: "same-origin" })
      .then(r => r.json())
      .then(data => { customIcons = data.icons || []; return customIcons; })
      .catch(() => { customIcons = []; return customIcons; });
    return customPromise;
  }

  function findIcon(ref) {
    if (!ref) return null;
    if (ref.indexOf("custom:") === 0) {
      const ci = customIcons.find(x => x.ref === ref);
      return ci ? { kind: "custom", data: ci } : null;
    }
    for (const cat of (catalog && catalog.categories) || []) {
      for (const ic of cat.icons || []) {
        if (ic.name === ref) return { kind: "lucide", data: ic };
      }
    }
    return null;
  }

  function renderIconHtml(found) {
    if (!found) return "";
    return found.kind === "custom" ? renderCustom(found.data) : renderSvg(found.data.paths);
  }

  function buildGrid(filter) {
    const q = (filter || "").trim().toLowerCase();
    const html = [];

    function cellSelectedCls(ref) {
      return ref && ref === pendingRef ? " is-selected" : "";
    }

    // Custom icons first (so uploads are easy to find).
    const customMatching = customIcons.filter(ic =>
      !q || ic.name.toLowerCase().indexOf(q) !== -1);
    if (customMatching.length) {
      html.push('<div class="icon-picker-group">');
      html.push('<div class="icon-picker-group-title">Your uploads</div>');
      html.push('<div class="icon-picker-grid">');
      for (const ci of customMatching) {
        html.push(
          '<div class="icon-picker-cell is-custom' + cellSelectedCls(ci.ref) +
          '" data-icon-ref="' + escapeAttr(ci.ref) +
          '" title="' + escapeAttr(ci.name) + '">' +
          '<button type="button" class="icon-picker-cell-del" data-custom-delete="' +
          ci.id + '" title="Delete">&times;</button>' +
          renderCustom(ci) +
          '<span class="icon-picker-cell-label">' + escapeHtml(ci.name) + '</span>' +
          '</div>'
        );
      }
      html.push('</div></div>');
    }

    // Built-in Lucide icons by category.
    for (const cat of (catalog && catalog.categories) || []) {
      const matching = [];
      for (const ic of (cat.icons || [])) {
        const hay = (ic.name + " " + (ic.keywords || "")).toLowerCase();
        if (!q || hay.indexOf(q) !== -1) matching.push(ic);
      }
      if (!matching.length) continue;
      html.push('<div class="icon-picker-group">');
      html.push('<div class="icon-picker-group-title">' + escapeHtml(cat.name) + '</div>');
      html.push('<div class="icon-picker-grid">');
      for (const ic of matching) {
        html.push(
          '<button type="button" class="icon-picker-cell' + cellSelectedCls(ic.name) +
          '" data-icon-ref="' +
          escapeAttr(ic.name) + '" title="' + escapeAttr(ic.name) + '">' +
          renderSvg(ic.paths) +
          '<span class="icon-picker-cell-label">' + escapeHtml(ic.name) + '</span>' +
          '</button>'
        );
      }
      html.push('</div></div>');
    }

    if (!html.length) {
      catalogEl.innerHTML = '<p class="muted smaller" style="padding: 16px;">No icons match “' +
        escapeHtml(q) + '”.</p>';
    } else {
      catalogEl.innerHTML = html.join("");
    }
    applyModalColor();
    applyModalSize();
  }

  function applyModalColor() {
    const c = modalColorEl && modalColorEl.value;
    if (!c) return;
    catalogEl.style.color = c;
  }

  function applyModalSize() {
    const s = modalSizeEl && parseInt(modalSizeEl.value, 10);
    if (modalSizeOut) modalSizeOut.textContent = s || DEFAULT_SIZE;
    if (!catalogEl) return;
    catalogEl.style.setProperty("--icon-size", (s || DEFAULT_SIZE) + "px");
  }

  function refreshSelectedCell(newRef) {
    // Update cell highlight in the grid without rebuilding the whole thing.
    catalogEl.querySelectorAll(".icon-picker-cell.is-selected").forEach(el =>
      el.classList.remove("is-selected"));
    if (newRef) {
      const cell = catalogEl.querySelector(
        '.icon-picker-cell[data-icon-ref="' + CSS.escape(newRef) + '"]');
      if (cell) cell.classList.add("is-selected");
    }
    pendingRef = newRef || "";
    if (saveBtn) saveBtn.disabled = !pendingRef;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }

  function openPicker(trigger) {
    activeTrigger = trigger;
    activeField = trigger.closest("[data-icon-field]");
    activeIconInput = document.querySelector(trigger.getAttribute("data-icon-target"));
    activeColorInput = document.querySelector(trigger.getAttribute("data-color-target"));
    const sizeSel = trigger.getAttribute("data-size-target");
    activeSizeInput = sizeSel && document.querySelector(sizeSel);
    activePreview = trigger.querySelector("[data-icon-preview]");

    modalColorEl.value = (activeColorInput && activeColorInput.value) || DEFAULT_COLOR;
    const storedSize = activeSizeInput && parseInt(activeSizeInput.value, 10);
    modalSizeEl.value = (storedSize && storedSize > 0) ? storedSize : DEFAULT_SIZE;
    pendingRef = (activeIconInput && activeIconInput.value) || "";
    if (saveBtn) saveBtn.disabled = !pendingRef;
    applyModalColor();
    applyModalSize();
    searchEl.value = "";

    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    searchEl.focus();

    Promise.all([loadCatalog(), loadCustom()]).then(() => buildGrid(""));
  }

  function closePicker() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    activeTrigger = null;
    activeField = null;
    activeIconInput = null;
    activeColorInput = null;
    activeSizeInput = null;
    activePreview = null;
  }

  function dispatchChange(el) {
    if (!el) return;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function applyIconSelection(ref, found, opts) {
    opts = opts || {};
    if (activeIconInput) {
      activeIconInput.value = ref || "";
      dispatchChange(activeIconInput);
    }
    if (activeColorInput) {
      if (opts.clear || !ref) {
        activeColorInput.value = "";
      } else {
        activeColorInput.value = (modalColorEl && modalColorEl.value) || DEFAULT_COLOR;
      }
      dispatchChange(activeColorInput);
    }
    if (activeSizeInput) {
      if (opts.clear || !ref) {
        activeSizeInput.value = "";
      } else {
        activeSizeInput.value = (modalSizeEl && modalSizeEl.value) || DEFAULT_SIZE;
      }
      dispatchChange(activeSizeInput);
    }
    if (activePreview) {
      activePreview.innerHTML = ref ? renderIconHtml(found) : "";
      const storedColor = activeColorInput && activeColorInput.value;
      activePreview.style.color = storedColor || "";
      const storedSize = activeSizeInput && activeSizeInput.value;
      if (storedSize) activePreview.style.setProperty("--icon-size", storedSize + "px");
      else activePreview.style.removeProperty("--icon-size");
    }
    if (activeField) {
      activeField.classList.toggle("has-icon", !!ref);
    }
  }

  // Wire triggers (event delegation so templates added via AJAX still work).
  document.addEventListener("click", (e) => {
    const trigger = e.target.closest("[data-open-icon-picker]");
    if (trigger) { e.preventDefault(); openPicker(trigger); return; }
    const clear = e.target.closest("[data-icon-clear]");
    if (clear) {
      e.preventDefault();
      const fieldWrap = clear.closest("[data-icon-field]");
      if (!fieldWrap) return;
      const iconHidden = fieldWrap.querySelector('input[type="hidden"][data-block-field="icon_before"], input[type="hidden"][data-block-field="icon_after"]');
      const colorHidden = fieldWrap.querySelector('input[type="hidden"][data-block-field$="_color"]');
      const sizeHidden = fieldWrap.querySelector('input[type="hidden"][data-block-field$="_size"]');
      const preview = fieldWrap.querySelector("[data-icon-preview]");
      if (iconHidden) { iconHidden.value = ""; dispatchChange(iconHidden); }
      if (colorHidden) { colorHidden.value = ""; dispatchChange(colorHidden); }
      if (sizeHidden) { sizeHidden.value = ""; dispatchChange(sizeHidden); }
      if (preview) {
        preview.innerHTML = "";
        preview.style.color = "";
        preview.style.removeProperty("--icon-size");
      }
      fieldWrap.classList.remove("has-icon");
      return;
    }
  });

  // Modal internals.
  catalogEl.addEventListener("click", async (e) => {
    const delBtn = e.target.closest("[data-custom-delete]");
    if (delBtn) {
      e.preventDefault();
      e.stopPropagation();
      const cid = delBtn.getAttribute("data-custom-delete");
      if (!confirm("Delete this custom icon? It will be removed from every link that uses it.")) return;
      const url = customDeleteUrlTpl.replace(/\/0\/delete$/, "/" + cid + "/delete");
      try {
        const r = await fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": csrfToken },
        });
        if (!r.ok) throw new Error("delete failed");
        customIcons = customIcons.filter(ci => String(ci.id) !== String(cid));
        buildGrid(searchEl.value);
      } catch (_) {
        (window.tspShowToast || alert)("Could not delete icon");
      }
      return;
    }
    const cell = e.target.closest("[data-icon-ref]");
    if (!cell) return;
    // Deferred commit: clicking a cell only highlights it. The color and size
    // sliders update the grid preview live but don't touch the nav-link field
    // until the user clicks Save.
    refreshSelectedCell(cell.getAttribute("data-icon-ref"));
  });

  searchEl.addEventListener("input", () => buildGrid(searchEl.value));
  modalColorEl.addEventListener("input", () => applyModalColor());
  modalSizeEl.addEventListener("input", () => applyModalSize());

  // Upload flow — POST the chosen file, splice into `customIcons`, redraw grid.
  uploadInput.addEventListener("change", async () => {
    const file = uploadInput.files && uploadInput.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("icon", file);
    fd.append("csrf_token", csrfToken);
    try {
      const r = await fetch(customUploadUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
        body: fd,
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        (window.tspShowToast || alert)(data.error || "Upload failed");
      } else {
        customIcons.unshift(data.icon);
        buildGrid(searchEl.value);
        // Broadcast so pages that show the icon library (e.g. Fonts & Icons)
        // can refresh their tile grid without depending on this module's state.
        document.dispatchEvent(new CustomEvent("frontend-icon:uploaded", { detail: data.icon }));
      }
    } catch (_) {
      (window.tspShowToast || alert)("Upload failed");
    } finally {
      uploadInput.value = "";
    }
  });

  removeBtn.addEventListener("click", () => {
    applyIconSelection("", null, { clear: true });
    closePicker();
  });

  if (saveBtn) saveBtn.addEventListener("click", () => {
    if (!pendingRef) return;
    applyIconSelection(pendingRef, findIcon(pendingRef));
    closePicker();
  });

  modal.querySelectorAll("[data-close]").forEach(el =>
    el.addEventListener("click", closePicker));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("open")) {
      closePicker();
    }
  });
})();


// ── SIDEBAR ORDER (Settings → Appearance) ────────────────────────────
// Mode radio toggles the manual drag-drop panel's visibility. Inside
// manual mode, two drag scopes: sections (whole groups) and items
// inside Main/Admin. After every drop, serialize the current order
// into the hidden JSON input so the form save persists exactly what
// the admin sees.
(function feSidebarOrder() {
  const form = document.getElementById("sidebar-order-form");
  if (!form) return;

  const manualWrap = form.querySelector("[data-sidebar-manual]");
  const sectionList = form.querySelector("[data-sidebar-section-list]");
  const orderInput = form.querySelector("[data-sidebar-order-json]");
  if (!manualWrap || !sectionList || !orderInput) return;

  // Mode radios — show/hide the manual panel.
  form.querySelectorAll('input[name="sidebar_sort_mode"]').forEach(r => {
    r.addEventListener("change", () => {
      manualWrap.hidden = r.value !== "manual";
    });
  });

  // Helpers ----------------------------------------------------------
  // Seed pass writes the canonical JSON shape into the hidden input
  // without dispatching an event, so the settings modal's save bar
  // doesn't latch dirty before any user interaction. Subsequent calls
  // (after dragstart/dragover/drop) DO dispatch when the value moves.
  let _seeded = false;
  function serialize() {
    const sections = [...sectionList.querySelectorAll(":scope > .sidebar-order-section")]
      .map(sec => sec.getAttribute("data-section-key"));
    const out = { sections };
    ["main", "intergroup", "admin"].forEach(scope => {
      const ul = sectionList.querySelector('[data-section-items="' + scope + '"]');
      if (!ul) return;
      out[scope] = [...ul.querySelectorAll(':scope > .sidebar-order-item')]
        .map(li => li.getAttribute("data-item-key"));
    });
    const next = JSON.stringify(out);
    if (orderInput.value !== next) {
      orderInput.value = next;
      // Programmatic value writes don't fire input/change — dispatch one
      // so the settings modal's save bar picks up the new dirty state.
      // Skipped on the initial seed: the rendered hidden value rarely
      // matches what serialize() rebuilds from the DOM (different key
      // ordering / missing keys), so dispatching on the seed would
      // make the bar appear the moment the modal opens.
      if (_seeded) {
        orderInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  }
  // Seed once on load so the hidden input is in sync with the rendered
  // list even before the admin drags anything.
  serialize();
  _seeded = true;

  // Generic drag-drop wiring for sections + items. Browsers won't let
  // you mix two scopes by default; here `dragging` carries the active
  // scope so we know which targets accept the drop.
  let dragging = null;
  function within(el, selector) { return el.closest(selector); }

  sectionList.addEventListener("dragstart", e => {
    const item = within(e.target, ".sidebar-order-item");
    const sec = within(e.target, ".sidebar-order-section");
    if (item) {
      dragging = { kind: "item", el: item, scope: item.parentElement.getAttribute("data-section-items") };
      item.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "item:" + item.getAttribute("data-item-key"));
    } else if (sec) {
      dragging = { kind: "section", el: sec };
      sec.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", "section:" + sec.getAttribute("data-section-key"));
    }
  });

  sectionList.addEventListener("dragend", () => {
    if (dragging && dragging.el) dragging.el.classList.remove("dragging");
    dragging = null;
    serialize();
  });

  sectionList.addEventListener("dragover", e => {
    if (!dragging) return;
    if (dragging.kind === "item") {
      const ul = within(e.target, '[data-section-items="' + dragging.scope + '"]');
      if (!ul) return;
      e.preventDefault();
      const after = [...ul.querySelectorAll(':scope > .sidebar-order-item:not(.dragging)')]
        .find(li => e.clientY < li.getBoundingClientRect().top + li.offsetHeight / 2);
      if (after) ul.insertBefore(dragging.el, after);
      else ul.appendChild(dragging.el);
    } else if (dragging.kind === "section") {
      // Section-level drag: the only valid drop targets are other
      // sections at the top level of the section list.
      const sec = within(e.target, ".sidebar-order-section");
      if (!sec || sec === dragging.el) return;
      e.preventDefault();
      const after = e.clientY < sec.getBoundingClientRect().top + sec.offsetHeight / 2;
      if (after) sectionList.insertBefore(dragging.el, sec);
      else sectionList.insertBefore(dragging.el, sec.nextSibling);
    }
  });

  sectionList.addEventListener("drop", e => {
    if (!dragging) return;
    e.preventDefault();
    serialize();
  });

  // Re-serialize on every input event in case the admin uses keyboard
  // reordering in a future iteration; harmless either way.
  form.addEventListener("submit", serialize);
})();

