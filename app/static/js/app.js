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
    el.addEventListener("click", () => openModal(el.dataset.openModal));
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
  // reloaded against a ?prefill=<email> query param so the Create User form
  // arrives pre-populated.
  document.querySelectorAll("[data-create-user-from-request]").forEach(btn => {
    btn.addEventListener("click", () => {
      const email = btn.dataset.email || "";
      const modal = document.getElementById("settings-modal");
      if (!modal) return;
      openModal("settings-modal");
      const usersTab = modal.querySelector('[data-tab="users"]');
      if (usersTab) usersTab.click();
      const pane = modal.querySelector('[data-pane="users"]');
      const iframe = pane && pane.querySelector("iframe.settings-frame");
      if (iframe) {
        const base = iframe.dataset.src || "";
        const sep = base.includes("?") ? "&" : "?";
        iframe.src = base + sep + "prefill=" + encodeURIComponent(email) + "&_=" + Date.now();
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

    settingsModal.querySelectorAll("form").forEach(f => {
      if (f.closest(".settings-frame")) return;
      if (f.dataset.noAjax === "1") return;
      f.addEventListener("submit", e => {
        e.preventDefault();
        const btn = f.querySelector('button[type="submit"], button:not([type])');
        const orig = btn ? btn.textContent : null;
        if (btn){ btn.disabled = true; btn.textContent = "Saving…"; }
        fetch(f.action, {
          method: (f.method || "POST").toUpperCase(),
          body: new FormData(f),
          headers: { "X-Requested-With": "fetch" },
          credentials: "same-origin",
          redirect: "follow",
        }).then(async r => {
          if (!r.ok) throw new Error("HTTP " + r.status);
          let data = null;
          const ct = r.headers.get("content-type") || "";
          if (ct.includes("application/json")) {
            try { data = await r.json(); } catch (_) {}
          }
          showSettingsToast("Saved");
          f.dispatchEvent(new CustomEvent("settings:saved", { bubbles: true, detail: data }));
          if (f.dataset.reloadOnSave === "1") {
            // Brief delay so the "Saved" toast is visible before the reload.
            setTimeout(() => window.location.reload(), 400);
          }
        }).catch(err => {
          showSettingsToast("Save failed: " + err.message, "danger");
        }).finally(() => {
          if (btn){ btn.disabled = false; btn.textContent = orig; }
        });
      });
    });

    // Rewire checkbox toggle-on-change so it fires our submit handler (form.submit() does not).
    settingsModal.querySelectorAll('input[onchange*="this.form.submit()"]').forEach(inp => {
      inp.setAttribute("onchange", "this.form.requestSubmit()");
    });
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
  // Works with <ul><li>, <tbody><tr>, or any parent with direct-child [data-item-id] elements.
  // Detects horizontal vs. vertical layout automatically so it can handle flex-row column editors.
  function initSortable(list) {
    if (list.__tspSortableInit) return;
    list.__tspSortableInit = true;
    const url = list.dataset.reorderUrl;
    const category = list.dataset.reorderCategory || null;
    let dragging = null;
    const isHorizontal = () => {
      const first = list.querySelector(":scope > [data-item-id]");
      const second = first?.nextElementSibling;
      if (!first || !second) return false;
      const a = first.getBoundingClientRect();
      const b = second.getBoundingClientRect();
      return Math.abs(b.left - a.left) > Math.abs(b.top - a.top);
    };
    const bindItem = (item) => {
      if (item.__tspSortableBound) return;
      item.__tspSortableBound = true;
      // Only make the item draggable while the user is pressing on the drag
      // handle. Otherwise text selection inside nested inputs would get
      // hijacked by a container drag.
      item.addEventListener("mousedown", (e) => {
        item.draggable = !!e.target.closest?.(".drag-handle");
      });
      const restoreDraggable = () => { item.draggable = true; };
      item.addEventListener("mouseup", restoreDraggable);
      item.addEventListener("mouseleave", restoreDraggable);
      item.addEventListener("dragstart", (e) => {
        const handle = e.target.closest?.(".drag-handle");
        if (!handle) {
          e.preventDefault();
          return;
        }
        dragging = item;
        item.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", item.dataset.itemId || ""); } catch (_) {}
      });
      item.addEventListener("dragend", () => {
        item.classList.remove("dragging");
        list.querySelectorAll(":scope > .drag-over").forEach(x => x.classList.remove("drag-over"));
        dragging = null;
        item.draggable = true;
      });
      item.addEventListener("dragover", (e) => {
        if (!dragging || dragging === item) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const rect = item.getBoundingClientRect();
        const after = isHorizontal()
          ? (e.clientX - rect.left) > rect.width / 2
          : (e.clientY - rect.top) > rect.height / 2;
        item.classList.add("drag-over");
        if (after) item.parentNode.insertBefore(dragging, item.nextSibling);
        else item.parentNode.insertBefore(dragging, item);
      });
      item.addEventListener("dragleave", () => item.classList.remove("drag-over"));
      item.addEventListener("drop", async (e) => {
        e.preventDefault();
        item.classList.remove("drag-over");
        if (!url) return;
        if (list.dataset.reorderManual === "1") {
          list.dispatchEvent(new CustomEvent("reorder-changed", { bubbles: true }));
          return;
        }
        const order = Array.from(list.querySelectorAll(":scope > [data-item-id]"))
          .map(x => x.dataset.itemId);
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
