// SPDX-License-Identifier: AGPL-3.0-or-later
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
          const res = await fetch("/files/upload", {
            method: "POST", body: fd, credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          if (!res.ok) throw new Error("upload failed");
          const data = await res.json();
          if (window.parent !== window && window.parent.postMessage) {
            // inside picker: hand the item to parent
            window.parent.postMessage({ type: "media-uploaded", item: data.item }, "*");
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
      const res = await fetch(`/files/${id}/rename`, {
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
      if (window.parent !== window) window.parent.postMessage(payload, "*");
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
      if (frame && frame.src === "about:blank") frame.src = "/files?picker=1&embed=1";
      openModal("media-picker-modal");
    });
  });
  window.addEventListener("message", (e) => {
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
  document.querySelectorAll(".file-list-sortable").forEach(list => {
    const url = list.dataset.reorderUrl;
    const category = list.dataset.reorderCategory || null;
    let dragging = null;
    list.querySelectorAll("li[draggable='true']").forEach(li => {
      li.addEventListener("dragstart", (e) => {
        // Don't initiate drag when grabbing inside a form/button
        if (e.target.closest("form, button, input, textarea, a")) {
          if (!e.target.classList?.contains("drag-handle")) { e.preventDefault(); return; }
        }
        dragging = li;
        li.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", li.dataset.itemId || ""); } catch (_) {}
      });
      li.addEventListener("dragend", () => {
        li.classList.remove("dragging");
        list.querySelectorAll("li.drag-over").forEach(x => x.classList.remove("drag-over"));
        dragging = null;
      });
      li.addEventListener("dragover", (e) => {
        if (!dragging || dragging === li) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const rect = li.getBoundingClientRect();
        const after = (e.clientY - rect.top) > rect.height / 2;
        li.classList.add("drag-over");
        if (after) li.parentNode.insertBefore(dragging, li.nextSibling);
        else li.parentNode.insertBefore(dragging, li);
      });
      li.addEventListener("dragleave", () => li.classList.remove("drag-over"));
      li.addEventListener("drop", async (e) => {
        e.preventDefault();
        li.classList.remove("drag-over");
        if (!url) return;
        const order = Array.from(list.querySelectorAll("li[data-item-id]"))
          .map(x => x.dataset.itemId);
        const payload = category ? { order, category } : { order };
        try {
          await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
            credentials: "same-origin",
            body: JSON.stringify(payload),
          });
        } catch (_) {}
      });
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
})();
