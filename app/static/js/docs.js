/* SPDX-License-Identifier: AGPL-3.0-or-later
 * Documentation site behaviour: client-side search, mobile sidebar drawer,
 * and table-of-contents scrollspy. Vanilla JS, no dependencies. Degrades to a
 * plain (still navigable) docs site if anything here fails.
 */
(function () {
  "use strict";

  /* ── search ─────────────────────────────────────────────────────────── */
  var modal = document.querySelector("[data-docs-modal]");
  var input = document.getElementById("docsSearchInput");
  var results = document.getElementById("docsSearchResults");
  var index = null;        // lazy-loaded array from /docs/search.json
  var loading = false;
  var active = -1;         // keyboard-highlighted result row

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function loadIndex() {
    if (index || loading) return;
    loading = true;
    fetch("/docs/search.json")
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; render(input.value); })
      .catch(function () { loading = false; });
  }

  function openModal() {
    if (!modal) return;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    loadIndex();
    setTimeout(function () { input.focus(); input.select(); }, 30);
    render(input.value);
  }
  function closeModal() {
    if (!modal) return;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  function highlight(text, terms) {
    var out = esc(text);
    terms.forEach(function (t) {
      if (!t) return;
      var re = new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
      out = out.replace(re, "<mark>$1</mark>");
    });
    return out;
  }

  function snippet(text, terms) {
    var lower = text.toLowerCase();
    var at = -1;
    for (var i = 0; i < terms.length; i++) {
      var p = lower.indexOf(terms[i]);
      if (p !== -1 && (at === -1 || p < at)) at = p;
    }
    if (at === -1) at = 0;
    var start = Math.max(0, at - 60);
    var slice = text.slice(start, start + 200).trim();
    return (start > 0 ? "… " : "") + highlight(slice, terms) + " …";
  }

  function score(item, terms) {
    var t = item.title.toLowerCase();
    var s = (item.summary || "").toLowerCase();
    var h = item.headings.map(function (x) { return x.name.toLowerCase(); }).join(" ");
    var body = item.text.toLowerCase();
    var total = 0;
    for (var i = 0; i < terms.length; i++) {
      var term = terms[i], hit = 0;
      if (t.indexOf(term) !== -1) hit += 6;
      if (h.indexOf(term) !== -1) hit += 3;
      if (s.indexOf(term) !== -1) hit += 2;
      var idx = body.indexOf(term);
      if (idx !== -1) hit += 1;
      if (hit === 0) return 0;   // every term must appear somewhere (AND)
      total += hit;
    }
    return total;
  }

  function bestHeadingId(item, terms) {
    for (var i = 0; i < item.headings.length; i++) {
      var name = item.headings[i].name.toLowerCase();
      for (var j = 0; j < terms.length; j++) {
        if (name.indexOf(terms[j]) !== -1) return item.headings[i].id;
      }
    }
    return null;
  }

  function render(q) {
    if (!results) return;
    active = -1;
    q = (q || "").trim().toLowerCase();
    if (!index) {
      results.innerHTML = '<div class="pp-docs-empty">Loading…</div>';
      return;
    }
    if (!q) {
      results.innerHTML = '<div class="pp-docs-empty">Type to search the guides.</div>';
      return;
    }
    var terms = q.split(/\s+/).filter(Boolean);
    var scored = index.map(function (it) { return { it: it, sc: score(it, terms) }; })
      .filter(function (x) { return x.sc > 0; })
      .sort(function (a, b) { return b.sc - a.sc; })
      .slice(0, 12);

    if (!scored.length) {
      results.innerHTML = '<div class="pp-docs-empty">No results for “' + esc(q) + '”.</div>';
      return;
    }
    results.innerHTML = scored.map(function (x) {
      var it = x.it;
      var hid = bestHeadingId(it, terms);
      var href = it.url + (hid ? "#" + hid : "");
      return '<a class="pp-docs-result" href="' + href + '">' +
        '<span class="pp-docs-result-top">' +
        '<span class="pp-docs-result-t">' + highlight(it.title, terms) + "</span>" +
        '<span class="pp-docs-result-cat">' + esc(it.category) + "</span>" +
        "</span>" +
        '<span class="pp-docs-result-snip">' + snippet(it.text, terms) + "</span>" +
        "</a>";
    }).join("");
  }

  function rows() { return results ? results.querySelectorAll(".pp-docs-result") : []; }
  function setActive(n) {
    var r = rows();
    if (!r.length) return;
    active = (n + r.length) % r.length;
    r.forEach(function (el, i) { el.classList.toggle("pp-on", i === active); });
    r[active].scrollIntoView({ block: "nearest" });
  }

  if (input) {
    input.addEventListener("input", function () { render(input.value); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Enter") {
        var r = rows();
        if (r.length) { e.preventDefault(); (r[active] || r[0]).click(); }
      }
    });
  }

  document.querySelectorAll("[data-docs-search]").forEach(function (btn) {
    btn.addEventListener("click", openModal);
  });
  if (modal) {
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeModal();
    });
  }

  document.addEventListener("keydown", function (e) {
    var open = modal && modal.classList.contains("open");
    if (e.key === "Escape" && open) { closeModal(); return; }
    if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
      e.preventDefault(); open ? closeModal() : openModal(); return;
    }
    // "/" opens search unless the user is typing in a field
    if (e.key === "/" && !open) {
      var tag = (document.activeElement && document.activeElement.tagName) || "";
      if (tag !== "INPUT" && tag !== "TEXTAREA") { e.preventDefault(); openModal(); }
    }
  });

  /* ── mobile sidebar drawer ──────────────────────────────────────────── */
  var side = document.querySelector("[data-docs-side]");
  var scrim = document.querySelector("[data-docs-scrim]");
  function openSide() { if (side) { side.classList.add("open"); scrim && scrim.classList.add("open"); } }
  function closeSide() { if (side) { side.classList.remove("open"); scrim && scrim.classList.remove("open"); } }
  document.querySelectorAll("[data-docs-menu]").forEach(function (b) {
    b.addEventListener("click", openSide);
  });
  if (scrim) scrim.addEventListener("click", closeSide);
  // close the drawer after tapping a link inside it
  if (side) side.addEventListener("click", function (e) {
    if (e.target.closest("a")) closeSide();
  });

  /* ── table-of-contents scrollspy ────────────────────────────────────── */
  var toc = document.querySelector("[data-toc]");
  if (toc) {
    var links = Array.prototype.slice.call(toc.querySelectorAll("[data-toc-link]"));
    var heads = links.map(function (a) { return document.getElementById(a.getAttribute("data-toc-link")); })
      .filter(Boolean);
    var ticking = false;
    function spy() {
      ticking = false;
      var offset = 120, current = heads[0];
      for (var i = 0; i < heads.length; i++) {
        if (heads[i].getBoundingClientRect().top <= offset) current = heads[i];
      }
      links.forEach(function (a) {
        a.classList.toggle("pp-on", current && a.getAttribute("data-toc-link") === current.id);
      });
    }
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(spy); }
    }, { passive: true });
    spy();
  }
})();
