// SPDX-License-Identifier: AGPL-3.0-or-later
/* Page-edit screen: drag-drop block composition + hover preview.
   Drives the structure card, orphan bin, and block palette. Mutates
   the underlying `blocks_json` hidden input on every drop so the
   sticky save bar lights up; the existing form save round-trips it
   to the server, no separate endpoint needed.

   Source of truth:
     • Each pill in the DOM carries `data-block-payload` (full JSON
       of the block) AND `data-page-block-id` (the block's id).
     • Each `data-be-zone` element is a Sortable destination. Zones
       carry context attributes (parent block id, col index, etc.)
       so the JSON reconstruction knows which array each pill lives in.
     • On any drop, walk the structure tree DOM + orphans list and
       rebuild the page's sections JSON from each pill's payload,
       respecting which zone each pill ended up in.

   Cross-zone drags work between structure-tree zones (column cells,
   single-block rows, container drop areas) and the orphan bin via a
   single shared Sortable group ('be-zone'). Palette tiles are HTML5-
   draggable (not Sortable) and dropped into a Sortable zone create a
   new pill from the catalog's blank defaults. */
(function () {
  // ── Hover preview popover ───────────────────────────────────────
  // Lightweight, single-popover-element, follows the cursor on the
  // hovered pill. Reads `data-preview` JSON from each pill. No deps.
  function ensurePreviewEl() {
    let el = document.getElementById('fe-pill-preview');
    if (!el) {
      el = document.createElement('div');
      el.id = 'fe-pill-preview';
      el.className = 'fe-pill-preview';
      el.setAttribute('aria-hidden', 'true');
      document.body.appendChild(el);
    }
    return el;
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function renderPreviewBody(pv) {
    if (!pv) return '<div class="fe-pill-preview-text muted">(no preview)</div>';
    let html = '';
    if (pv.label) html += '<div class="fe-pill-preview-label">' + escapeHtml(pv.label) + '</div>';
    if (pv.kind === 'image' && pv.src) {
      html += '<img class="fe-pill-preview-img" src="' + escapeHtml(pv.src) + '" alt="' + escapeHtml(pv.alt || '') + '" loading="lazy">';
    }
    if (pv.text) {
      html += '<div class="fe-pill-preview-text">' + escapeHtml(pv.text) + '</div>';
    }
    if (pv.subtext) {
      html += '<div class="fe-pill-preview-sub muted smaller">' + escapeHtml(pv.subtext) + '</div>';
    }
    return html || '<div class="fe-pill-preview-text muted">(empty)</div>';
  }
  function showPreview(target, ev) {
    const raw = target.getAttribute('data-preview');
    if (!raw) return;
    let pv = null;
    try { pv = JSON.parse(raw); } catch (_) { return; }
    const el = ensurePreviewEl();
    el.innerHTML = renderPreviewBody(pv);
    el.classList.add('is-visible');
    positionPreview(el, ev || target);
  }
  function hidePreview() {
    const el = document.getElementById('fe-pill-preview');
    if (el) el.classList.remove('is-visible');
  }
  function positionPreview(el, refOrEvent) {
    // Anchor the popover BELOW the pill (not to the side) so it never
    // covers the pill's right-edge × delete button. Falls back to
    // above-the-pill when there's not enough room below; falls back
    // to the cursor when no rect is available (synthetic events).
    const rect = (refOrEvent && refOrEvent.getBoundingClientRect)
      ? refOrEvent.getBoundingClientRect()
      : null;
    const pw = el.offsetWidth || 280;
    const ph = el.offsetHeight || 120;
    let x, y;
    if (rect) {
      x = rect.left;
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;
      // Prefer below; flip above only when below would clip and
      // above has more room. Add a small 8px gap on whichever side.
      if (spaceBelow >= ph + 12 || spaceBelow >= spaceAbove) {
        y = rect.bottom + 8;
      } else {
        y = rect.top - ph - 8;
      }
    } else if (refOrEvent && refOrEvent.clientX != null) {
      x = refOrEvent.clientX + 16;
      y = refOrEvent.clientY + 16;
    } else {
      return;
    }
    // Clamp to viewport horizontally so a left-edge pill in a wide
    // popover doesn't push off-screen, and vertically as a final
    // safety net.
    if (x + pw > window.innerWidth - 8) x = Math.max(8, window.innerWidth - pw - 8);
    if (x < 8) x = 8;
    if (y + ph > window.innerHeight - 8) y = Math.max(8, window.innerHeight - ph - 8);
    if (y < 8) y = 8;
    el.style.left = x + 'px';
    el.style.top = y + 'px';
  }

  // Bind hover handlers on the document so dynamically-added pills
  // (drops, palette additions) automatically get preview behavior.
  // Hovering the × button hides the preview so the delete affordance
  // is never visually obscured — it's also a clearer affordance
  // (the popover competing with the × is busy chrome).
  document.addEventListener('mouseover', e => {
    if (e.target.closest('[data-be-remove-block], [data-be-remove-row]')) {
      hidePreview();
      return;
    }
    const pill = e.target.closest('.fe-page-structure-block[data-preview]');
    if (pill) showPreview(pill, pill);
  });
  document.addEventListener('mouseout', e => {
    const pill = e.target.closest('.fe-page-structure-block[data-preview]');
    if (pill && !pill.contains(e.relatedTarget)) hidePreview();
  });
  document.addEventListener('focusout', () => hidePreview());

  // ── Drag-drop composition ───────────────────────────────────────
  // Wait for Sortable to be available — it's loaded as a sibling
  // <script src="…/Sortable.min.js"> right before this file.
  if (typeof Sortable === 'undefined') {
    console.warn('[page_structure] Sortable not loaded — drag-drop disabled');
    return;
  }

  const hidden = document.getElementById('page-blocks-json');
  const editorRoot = document.getElementById('page-editor-root');
  if (!hidden) return;

  // Parse the page's initial sections JSON. This is the canonical
  // state the structure card mutates; the modal-based BlockEditor
  // re-mounts from this on each open so its view stays in sync with
  // structure-card edits.
  let sections = [];
  try {
    sections = JSON.parse((editorRoot && editorRoot.dataset.initial) || '[]') || [];
  } catch (_) { sections = []; }

  const tree = document.querySelector('[data-be-tree]');
  const orphansCard = document.querySelector('[data-be-orphans-card]');
  const orphansZone = document.querySelector('[data-be-zone="orphans"]');
  const orphansCount = document.querySelector('.fe-page-orphans-count');
  const palette = document.querySelector('[data-be-palette]');

  function uid() {
    return Math.random().toString(36).slice(2, 10);
  }

  // Default data for each block type the palette can drop. Mirrors
  // BlockEditor.js's blankBlock() — kept in sync by hand. Only types
  // valid for content pages are listed; if you add a new type to
  // _PAGE_BLOCK_CATALOG, add a default here.
  const TYPO = { font_family: '', font_size: '', font_weight: '',
                 color: '', align: '', line_height: '' };
  const BLANK_DATA = {
    paragraph: () => ({ md: '', ...TYPO }),
    heading:   () => ({ level: 3, text: '', ...TYPO }),
    image:     () => ({ src: '', alt: '', caption: '',
                        max_width_pct: 100, align: '',
                        caption_color: '', caption_size: '' }),
    button:    () => ({ label: 'Click here', url: '', align: 'left',
                        style: 'primary', new_tab: false,
                        bg: '', hover_bg: '', text_color: '', hover_text: '',
                        border: '', hover_border: '', shadow: '' }),
    list:      () => ({ ordered: false, items: [''], bullet_style: '', ...TYPO }),
    callout:   () => ({ variant: 'info', title: '', md: '' }),
    video:     () => ({ src: '', poster: '' }),
    // Lottie — mirrors block_editor.js's blankBlock('lottie') and the
    // server-side _blank_page_block defaults. Kept in sync by hand.
    lottie:    () => ({ src: '', loop: true, autoplay: true, speed: 1,
                        max_width_pct: 100, align: 'center',
                        bg_color: '', renderer: 'svg',
                        playback: 'auto' }),
    // Intergroup member — references one IntergroupOfficer row by id.
    // The four `show_*` flags toggle which contact fields render.
    intergroup_member: () => ({ officer_id: 0,
                                show_role: true, show_name: true,
                                show_phone: true, show_email: true }),
    // Officer roster — loops every IntergroupOfficer into a card grid.
    // 2 or 3 columns, configurable gap, same field toggles as the
    // single-member block.
    intergroup_member_roster: () => ({ columns: 3, gap: '1rem',
                                       show_role: true, show_name: true,
                                       show_phone: true, show_email: true }),
    // Library — references one Library row by id and renders its items
    // in the chosen style. Granular mode selects a subset by item id.
    library: () => ({ library_id: 0, mode: 'all', item_ids: [],
                      style: 'cards', columns: 2, gap: '1rem',
                      show_description: true, show_thumbnails: true,
                      show_categories: true, title: '' }),
    code:      () => ({ lang: '', code: '' }),
    separator: () => ({}),
    // Container — unstyled by default (transparent, no padding, no
    // gap, no max-width). Mirrors `_blank_page_block("container")` in
    // routes.py + the BlockEditor's blankBlock so all three sources
    // of new-container creation produce identical payloads.
    container: () => ({ label: '',
                        display: 'flex', direction: 'column',
                        justify: 'flex-start', align: 'stretch', wrap: false,
                        grid_columns: 'repeat(2, 1fr)', gap: '0',
                        padding: '0', width_mode: 'full', max_width: 0,
                        bg_color: '', border_width: 0, border_style: 'solid',
                        border_color: '', border_radius: 0, shadow: 'none',
                        hover_bg_color: '', hover_border_color: '',
                        hover_shadow: '', hover_lift: false, blocks: [] }),
    toc_sidebar: () => ({ title: 'On this page', max_level: 3,
                          sticky: true, sticky_offset: 96 }),
    icon:      () => ({ name: '', size: 32,
                        color: '', color_dark: '', color_dark_mode: 'same',
                        align: 'center', url: '', new_tab: false }),
    split:     () => ({ /* split is a layout primitive, not a block */ }),
    split3:    () => ({ /* three-column variant of split — same story */ }),
  };

  // ── Row factories ───────────────────────────────────────────────
  // When a Container / Two-panel / leaf is dropped on the root zone,
  // we mint a `.fe-page-structure-row` element matching the shape the
  // server-side `structure_page_tree` macro produces — so on the next
  // page load the server-rendered tree looks identical to what we
  // built client-side, and `syncStateFromDom` reads the new row via
  // the same selectors it already uses.
  function gridColCount(grid) {
    if (!grid) return 1;
    const s = String(grid);
    // Auto-flowing grids — column count varies with viewport at
    // render time, so the editor can't map cells to fixed slots.
    // Collapse to single-column so the structure tree shows the
    // children as a flat stack (the public render still flows them).
    if (s.includes('auto-fit') || s.includes('auto-fill')) return 1;
    const m = s.match(/^\s*repeat\(\s*(\d+)\s*,/);
    if (m) return parseInt(m[1], 10) || 1;
    const tracks = s.split(/\s+/).filter(Boolean);
    return tracks.length || 1;
  }
  function elFromHtml(html) {
    const tpl = document.createElement('template');
    tpl.innerHTML = html.trim();
    return tpl.content.firstChild;
  }
  function makeRowSingle(payload) {
    // Leaf type — wrap in a single-block row mirroring the macro's
    // `row--single` markup, including the drag handle on the left
    // and the × remove button on the right.
    const row = elFromHtml(
      '<div class="fe-page-structure-row fe-page-structure-row--single">' +
        '<div class="fe-page-row-handle" title="Drag to reorder">⋮⋮</div>' +
        '<div class="fe-page-structure-cols fe-page-structure-cols--1">' +
          '<div class="fe-page-structure-col">' +
            '<div class="fe-page-structure-block-list" data-be-zone="row-single"></div>' +
          '</div>' +
        '</div>' +
        '<button type="button" class="icon-btn fe-page-structure-row-remove fe-page-structure-row-remove--single"' +
        ' data-be-remove-row aria-label="Remove this row" title="Remove row">×</button>' +
      '</div>'
    );
    const zone = row.querySelector('[data-be-zone]');
    zone.appendChild(makePillEl(payload.type, payload));
    return row;
  }
  // Register any container payload (and its inner-container kids,
   // recursively) into the lookup map. Called whenever a brand-new
   // container row is minted so subsequent `findContainerPayload`
   // calls during the SAME tick can resolve it.
  function registerContainerPayload(payload) {
    if (!payload || payload.type !== 'container' || !payload.id) return;
    containerPayloadById.set(payload.id, payload);
    ((payload.data && payload.data.blocks) || []).forEach(c => {
      if (c && c.type === 'container') registerContainerPayload(c);
    });
  }

  function makeRowSplit(payload, nCols) {
    // Container row — single-column or N-column. Two patterns:
    //   • Showcase: all direct children are containers, one per
    //     column cell. Each cell hydrates from that inner
    //     container's blocks.
    //   • Flat: direct children are leaf blocks (or a mix). Children
    //     are distributed round-robin into the cells preserving
    //     order.
    // Multi-column containers AUTO-PROVISION inner-container
    // children when missing so the showcase pattern is the default
    // for new multi-column drops. Single-column containers do NOT
    // auto-provision — they hold their direct children flat (no
    // wrapper) which matches what the user expects from "I just
    // dropped a Container into this cell".
    if (!payload.data) payload.data = {};
    if (!Array.isArray(payload.data.blocks)) payload.data.blocks = [];
    if (nCols > 1) {
      while (payload.data.blocks.length < nCols) {
        payload.data.blocks.push({
          id: uid(), type: 'container', data: BLANK_DATA.container(),
        });
      }
    }
    const isSingle = nCols === 1;
    const colsClass = nCols >= 1 && nCols <= 4 ? nCols : 4;
    const userLabel = ((payload.data && payload.data.label) || '').trim();
    const placeholder = isSingle ? 'Container' : (nCols + '-column row');
    let html = '<div class="fe-page-structure-row fe-page-structure-row--split'
             + (isSingle ? ' fe-page-structure-row--single-container' : '')
             + '" data-be-row-block-id="' + payload.id + '">'
             + '<div class="fe-page-structure-row-label">';
    // Inline-editable label input — mirrors the server template's
    // markup so the bound handler in bindRowLabelInputs picks up
    // freshly-dropped rows the same way it picks up server-rendered ones.
    html += '<input type="text" '
          + 'class="fe-page-structure-row-label-input'
          + (userLabel ? ' is-labelled' : '') + '" '
          + 'value="' + escapeHtml(userLabel) + '" '
          + 'placeholder="' + escapeHtml(placeholder) + '" '
          + 'aria-label="Container label" '
          + 'data-be-row-label-input '
          + 'data-be-row-block-id="' + payload.id + '">'
          + '<span class="muted smaller">'
          + (isSingle ? 'container · single column' : (nCols + '-column container'))
          + '</span>';
    html += '<button type="button" class="btn btn-sm fe-page-structure-row-action"'
          + ' data-open-modal="page-layout-edit-modal"'
          + ' data-page-block-id="' + payload.id + '"'
          + ' title="Edit container settings">'
          + '<span class="icon-slot">⚙</span><span>Settings</span>'
          + '</button>'
          + '<button type="button" class="btn btn-sm fe-page-structure-row-action fe-page-structure-row-remove"'
          + ' data-be-remove-row aria-label="Remove this row"'
          + ' title="Remove row (any blocks inside go to Unplaced blocks)">'
          + '<span class="icon-slot">×</span><span>Remove</span>'
          + '</button>'
          + '</div>'
          + '<div class="fe-page-structure-cols fe-page-structure-cols--' + colsClass + '">';
    for (let i = 0; i < nCols; i++) {
      html += '<div class="fe-page-structure-col">';
      if (!isSingle) {
        html += '<div class="fe-page-structure-col-label muted smaller">Column ' + (i + 1) + '</div>';
      }
      html += '<div class="fe-page-structure-block-list" data-be-zone="container-col"'
            + ' data-be-parent-block-id="' + payload.id + '"'
            + ' data-be-col-index="' + i + '"></div>'
            + '</div>';
    }
    html += '</div></div>';
    const row = elFromHtml(html);
    const cellEls = Array.from(row.querySelectorAll('[data-be-zone="container-col"]'));
    const kids = payload.data.blocks;
    const allContainers = kids.length > 0 && kids.every(b => b && b.type === 'container');
    if (allContainers && kids.length === nCols) {
      // Showcase pattern — each cell maps to one inner container.
      kids.forEach((inner, idx) => {
        const cell = cellEls[idx];
        if (!cell) return;
        ((inner.data && inner.data.blocks) || []).forEach(child => {
          const node = makeNodeFromPayload(child);
          if (node) cell.appendChild(node);
        });
      });
    } else {
      // Flat — distribute children round-robin across cells.
      kids.forEach((child, i) => {
        const cellIdx = i % nCols;
        const cell = cellEls[cellIdx];
        if (!cell) return;
        const node = makeNodeFromPayload(child);
        if (node) cell.appendChild(node);
      });
    }
    return row;
  }
  function makeRowFromPayload(payload) {
    if (!payload || !payload.type) return null;
    if (payload.type === 'container') {
      registerContainerPayload(payload);
      const d = payload.data || {};
      const cols = d.display === 'grid' ? gridColCount(d.grid_columns) : 1;
      return makeRowSplit(payload, Math.max(1, cols));
    }
    return makeRowSingle(payload);
  }
  // Renders a payload AS the right kind of element for nesting in a
  // structure-card cell: containers become recursive sub-rows (with
  // their own column cells + drop zones); everything else becomes a
  // flat pill. Keeps the structure card visually faithful to the
  // block tree at every depth.
  function makeNodeFromPayload(payload) {
    if (!payload || !payload.type) return null;
    if (payload.type === 'container') {
      registerContainerPayload(payload);
      const d = payload.data || {};
      const cols = d.display === 'grid' ? gridColCount(d.grid_columns) : 1;
      return makeRowSplit(payload, Math.max(1, cols));
    }
    return makePillEl(payload.type, payload);
  }

  function makePillEl(type, payload) {
    const labels = window.tspBlockLabels || {};
    const meta = labels[type] || [type, 'square'];
    const tpl = document.querySelector(
      '.fe-page-structure-block--' + CSS.escape(type));
    // Clone the icon HTML from any existing pill of this type if
    // present, otherwise from a palette tile.
    let iconHtml = '';
    if (tpl) {
      const ic = tpl.querySelector('.fe-page-structure-block-icon');
      if (ic) iconHtml = ic.innerHTML;
    }
    if (!iconHtml) {
      const ptile = palette && palette.querySelector(
        '.fe-page-palette-tile[data-be-block-type="' + CSS.escape(type) + '"]');
      if (ptile) {
        const ic = ptile.querySelector('.fe-page-palette-icon');
        if (ic) iconHtml = ic.innerHTML;
      }
    }
    const wrap = document.createElement('div');
    wrap.className = 'fe-page-structure-block fe-page-structure-block--' + type
                  + ' is-clickable is-draggable';
    wrap.setAttribute('data-open-modal', 'page-layout-edit-modal');
    wrap.setAttribute('data-page-block-id', payload.id);
    wrap.setAttribute('data-block-type', type);
    wrap.setAttribute('data-block-payload', JSON.stringify(payload));
    wrap.setAttribute('data-preview', JSON.stringify(buildPreview(payload)));
    wrap.setAttribute('title', 'Edit ' + meta[0]);
    wrap.innerHTML =
      '<span class="fe-page-structure-block-icon">' + iconHtml + '</span>' +
      '<span class="fe-page-structure-block-name">' + escapeHtml(meta[0]) + '</span>' +
      '<span class="fe-page-structure-block-edit-hint" aria-hidden="true">Edit</span>' +
      '<button type="button" class="fe-page-structure-block-remove"' +
        ' data-be-remove-block aria-label="Remove this block"' +
        ' title="Remove block">×</button>';
    return wrap;
  }

  // Client-side mirror of `_block_preview` in routes.py for newly-
  // created blocks (palette drops). Server-rendered pills already
  // carry their own data-preview from the initial render.
  function buildPreview(b) {
    if (!b || !b.type) return { kind: 'empty' };
    const t = b.type, d = b.data || {};
    if (t === 'paragraph') return { kind: 'text', label: 'Text',
      text: ((d.md || '').trim()) || '(empty)' };
    if (t === 'heading') return { kind: 'text', label: 'Heading H' + (d.level || 3),
      text: ((d.text || '').trim()) || '(empty)' };
    if (t === 'image') return { kind: 'image', label: 'Image',
      src: d.src || '', alt: d.alt || '', text: d.caption || '' };
    if (t === 'button') return { kind: 'text', label: 'Button',
      text: (d.label || '').trim() || '(no label)',
      subtext: (d.url || '').trim() || '(no link)' };
    if (t === 'list') {
      const items = (d.items || []).map(s => String(s).trim()).filter(Boolean);
      return { kind: 'list',
        label: (d.ordered ? 'Numbered' : 'Bulleted') + ' list',
        text: items.slice(0, 5).join(' · ') + (items.length > 5 ? '…' : ''),
        subtext: items.length + ' item' + (items.length === 1 ? '' : 's') };
    }
    if (t === 'callout') return { kind: 'text',
      label: 'Callout · ' + (d.variant || 'info'),
      text: ((d.title || d.md || '').trim()).slice(0, 200) };
    if (t === 'video') return { kind: 'text', label: 'Video',
      text: (d.src || '').trim() || '(no source)' };
    if (t === 'lottie') {
      const flags = [];
      if (d.playback === 'hover') flags.push('hover-play');
      else if (d.autoplay) flags.push('autoplay');
      if (d.loop) flags.push('loop');
      flags.push((d.speed || 1) + 'x');
      return { kind: 'text', label: 'Lottie',
        text: (d.src || '').trim() || '(no source)',
        subtext: flags.join(' · ') };
    }
    if (t === 'intergroup_member') {
      const officers = window.tspIntergroupOfficers || [];
      const o = officers.find(x => x.id === d.officer_id) || null;
      const fields = [];
      if (d.show_role) fields.push('role');
      if (d.show_name) fields.push('name');
      if (d.show_phone) fields.push('phone');
      if (d.show_email) fields.push('email');
      return { kind: 'text', label: 'Intergroup Member',
        text: o ? ((o.role || '').trim() || '(unset)') : '(no officer selected)',
        subtext: o
          ? (o.name || '') + (fields.length ? '  ·  ' + fields.join(' · ') : '')
          : 'Pick a row from Settings → Global' };
    }
    if (t === 'intergroup_member_roster') {
      const n = (window.tspIntergroupOfficers || []).length;
      return { kind: 'text', label: 'Officer Roster',
        text: n + ' officer card' + (n === 1 ? '' : 's'),
        subtext: (d.columns || 3) + '-column grid' };
    }
    if (t === 'library') {
      const libs = window.tspLibraries || [];
      const lib = libs.find(l => l.id === d.library_id);
      if (!lib) return { kind: 'text', label: 'Library',
        text: '(no library selected)', subtext: 'Pick one in the editor' };
      let mode;
      if ((d.mode || 'all') === 'granular') {
        const n = (d.item_ids || []).length;
        mode = n + ' hand-picked';
      } else {
        mode = 'all ' + (lib.items || []).length + ' items';
      }
      return { kind: 'text', label: 'Library',
        text: lib.name,
        subtext: (d.style || 'cards') + '  ·  ' + mode };
    }
    if (t === 'code') return { kind: 'code',
      label: 'Code' + (d.lang ? ' · ' + d.lang : ''),
      text: ((d.code || '').trim()).slice(0, 200) || '(empty)' };
    if (t === 'container') {
      const kids = d.blocks || [];
      return { kind: 'text', label: 'Container',
        text: kids.length + ' child block' + (kids.length === 1 ? '' : 's'),
        subtext: (d.display || 'flex') +
          (d.display === 'grid' ? ' · ' + (d.grid_columns || '') : '') };
    }
    if (t === 'toc_sidebar') return { kind: 'text', label: 'Wiki sidebar',
      text: d.title || 'On this page',
      subtext: 'up to H' + (d.max_level || 3) };
    if (t === 'separator') return { kind: 'text', label: 'Divider', text: '—' };
    if (t === 'icon') return { kind: 'text', label: 'Icon',
      text: (d.name || '').trim() || '(none)',
      subtext: (d.size || 32) + 'px' };
    return { kind: 'text', label: t };
  }

  // ── State sync ──────────────────────────────────────────────────
  // Recompute `sections` from the DOM after every drop. The structure
  // tree is the canonical view; orphan-bin pills become a single
  // _orphans:true section appended to the sections list. Each row in
  // the structure tree becomes its own section (untitled). Container
  // rows reconstruct nested-container `data.blocks` arrays from each
  // column's pill list.
  function payloadOfPill(el) {
    try {
      return JSON.parse(el.getAttribute('data-block-payload') || 'null');
    } catch (_) { return null; }
  }

  // Recursive: gather a list of block payloads from a `.fe-page-
  // structure-block-list` zone. Cells can contain leaf pills AND
  // nested container rows; each nested row reconstructs into a
  // container payload whose own cells were walked the same way.
  // Used both for top-level row-single zones and any container's
  // column cell zones, so containers nest to arbitrary depth.
  function reconstructBlocksFromZone(zoneEl) {
    if (!zoneEl) return [];
    const out = [];
    Array.from(zoneEl.children).forEach(child => {
      if (child.classList.contains('fe-page-structure-block')) {
        const p = payloadOfPill(child);
        if (p) out.push(p);
        return;
      }
      if (child.classList.contains('fe-page-structure-row--split')) {
        const containerId = child.getAttribute('data-be-row-block-id');
        const containerPayload = findContainerPayload(containerId);
        if (!containerPayload) return;
        rebuildContainerFromRow(containerPayload, child);
        out.push(containerPayload);
        return;
      }
    });
    return out;
  }

  // Walk a `.fe-page-structure-row--split` row and rewrite the
  // container payload's `data.blocks` from each cell's contents.
  // The recursion in `reconstructBlocksFromZone` has already
  // rebuilt each nested container's own data.blocks by the time
  // we get here, so all this layer needs to do is re-flatten the
  // cells back into the outer container's direct child list.
  //
  // Two flatten patterns are detected:
  //   • Showcase: every cell holds exactly one container payload.
  //     Cells flatten in order so the outer's data.blocks =
  //     [innerContainer0, innerContainer1, …].
  //   • Round-robin: children of any type are distributed across
  //     cells. We interleave back so cell[0][0], cell[1][0],
  //     cell[0][1], cell[1][1], … reconstructs the original order.
  function rebuildContainerFromRow(containerPayload, rowEl) {
    if (!containerPayload || !containerPayload.data) return;
    const cellEls = Array.from(rowEl.querySelectorAll(
      ':scope > .fe-page-structure-cols > .fe-page-structure-col'));
    const buckets = cellEls.map(cell => {
      const zone = cell.querySelector(':scope > [data-be-zone]');
      return reconstructBlocksFromZone(zone);
    });
    const showcase = buckets.length > 1
      && buckets.every(b => b.length === 1 && b[0] && b[0].type === 'container');
    if (showcase) {
      containerPayload.data.blocks = buckets.flat();
      return;
    }
    const flat = [];
    const maxLen = buckets.reduce((m, b) => Math.max(m, b.length), 0);
    for (let i = 0; i < maxLen; i++) {
      buckets.forEach(b => { if (b[i] !== undefined) flat.push(b[i]); });
    }
    containerPayload.data.blocks = flat;
  }

  function reconstructSectionsFromDom() {
    const newSections = [];
    if (tree) {
      // Each direct child of `tree` is either a section_label, a
      // single-row (leaf block), or a multi-column row (container).
      tree.querySelectorAll(':scope > .fe-page-structure-row, :scope > .fe-page-structure-section-label')
        .forEach(node => {
          if (node.classList.contains('fe-page-structure-section-label')) {
            newSections.push({
              id: uid(), title: node.textContent.trim(), blocks: [],
            });
            return;
          }
          if (node.classList.contains('fe-page-structure-row--single')) {
            const zone = node.querySelector(':scope > .fe-page-structure-cols [data-be-zone="row-single"]')
                       || node.querySelector('[data-be-zone="row-single"]');
            const blocks = reconstructBlocksFromZone(zone);
            if (newSections.length && newSections[newSections.length - 1].title) {
              newSections[newSections.length - 1].blocks.push(...blocks);
            } else {
              blocks.forEach(b => newSections.push({
                id: uid(), title: '', blocks: [b],
              }));
              if (!blocks.length) {
                newSections.push({ id: uid(), title: '', blocks: [] });
              }
            }
            return;
          }
          if (node.classList.contains('fe-page-structure-row--split')) {
            const containerId = node.getAttribute('data-be-row-block-id');
            const containerPayload = findContainerPayload(containerId);
            if (!containerPayload) return;
            rebuildContainerFromRow(containerPayload, node);
            if (newSections.length && newSections[newSections.length - 1].title) {
              newSections[newSections.length - 1].blocks.push(containerPayload);
            } else {
              newSections.push({ id: uid(), title: '',
                                  blocks: [containerPayload] });
            }
          }
        });
    }
    // Append a trailing _orphans section if the bin holds anything.
    if (orphansZone) {
      const pills = Array.from(orphansZone.querySelectorAll(
        ':scope > .fe-page-structure-block'));
      const obs = pills.map(payloadOfPill).filter(Boolean);
      if (obs.length) {
        newSections.push({
          id: uid(), title: 'Unplaced blocks', _orphans: true,
          blocks: obs,
        });
      }
      if (orphansCard) {
        orphansCard.classList.toggle('is-empty', obs.length === 0);
      }
      if (orphansCount) orphansCount.textContent = '(' + obs.length + ')';
    }
    return newSections;
  }

  // Container payloads keyed by id. Seeded from `sections` at boot
  // and on every reconstruction; updated by the drop handlers when
  // a NEW container row is minted (palette drop), so `findContainerPayload`
  // can return its payload during the FIRST sync after a drop —
  // before the new container has made it into `sections`.
  const containerPayloadById = new Map();
  function indexContainersIn(secs) {
    function walk(arr) {
      for (const b of (arr || [])) {
        if (!b || b.type !== 'container' || !b.id) continue;
        containerPayloadById.set(b.id, b);
        walk((b.data && b.data.blocks) || []);
      }
    }
    for (const sec of (secs || [])) walk((sec && sec.blocks) || []);
  }
  // Initial population — sections already has whatever the server
  // rendered. Subsequent syncStateFromDom calls re-index after the
  // reconstruction so deleted containers fall out of the map.
  indexContainersIn(sections);

  function findContainerPayload(blockId) {
    if (!blockId) return null;
    // Map lookup is O(1) and includes both server-rendered + just-
    // minted JS containers. Containers that get removed (× delete or
    // dragged out of every container) stay in the map — they don't
    // hurt because the reconstruction only walks DOM rows, never
    // looks up dangling ids. The map gets re-seeded from each new
    // sections in syncStateFromDom so it doesn't grow unbounded.
    if (containerPayloadById.has(blockId)) {
      return containerPayloadById.get(blockId);
    }
    // Fallback — walk sections in case something added a container
    // without going through `containerPayloadById.set`. Shouldn't
    // happen but keeps the safety margin.
    function walk(arr) {
      for (const b of (arr || [])) {
        if (!b) continue;
        if (b.id === blockId) return b;
        if (b.type === 'container') {
          const found = walk((b.data && b.data.blocks) || []);
          if (found) return found;
        }
      }
      return null;
    }
    for (const sec of sections) {
      const found = walk(sec.blocks || []);
      if (found) return found;
    }
    return null;
  }

  // Walk a sections list and yield every block payload (recursing
  // into containers). Used by the lost-block safety net below to
  // diff pre- vs post-reconstruction.
  function* allBlocksIn(secs) {
    function* walk(blocks) {
      for (const b of (blocks || [])) {
        if (!b || typeof b !== 'object') continue;
        yield b;
        if (b.type === 'container') {
          yield* walk((b.data && b.data.blocks) || []);
        }
      }
    }
    for (const sec of (secs || [])) {
      if (sec && typeof sec === 'object') {
        yield* walk(sec.blocks || []);
      }
    }
  }

  // Block ids the admin has deliberately deleted via the × button.
  // The drag-drop safety net below sweeps blocks that disappear from
  // the DOM unexpectedly into the Unplaced bin, on the assumption that
  // a reconstruction bug must have eaten them. That heuristic is wrong
  // for deliberate deletes — without this allowlist, clicking × on an
  // orphan pill gets immediately undone (the pill is removed from DOM,
  // the safety net sees it as lost, stamps a new pill back into the
  // orphan zone). handleRemoveBlock / handleRemoveRow add to this set
  // before calling syncStateFromDom; the set is consumed (cleared) at
  // the end of each sync so it only suppresses one round of rescue.
  const intentionallyRemovedIds = new Set();

  function syncStateFromDom() {
    // Snapshot every block id present before the sync so we can
    // detect any that go missing during reconstruction. A block
    // disappearing during a drag is almost always a reconstruction
    // bug — the safety net below sweeps any orphans into the
    // Unplaced bin so the admin doesn't silently lose content,
    // even when the underlying logic fumbles.
    const beforeIds = new Set();
    const beforeById = new Map();
    for (const b of allBlocksIn(sections)) {
      if (b.id) {
        beforeIds.add(b.id);
        beforeById.set(b.id, b);
      }
    }

    sections = reconstructSectionsFromDom();

    // Diff: any block id that existed before but isn't reachable
    // in the new sections gets parked in an orphan bin section so
    // it survives the save. Find or create the orphan section.
    const afterIds = new Set();
    for (const b of allBlocksIn(sections)) {
      if (b.id) afterIds.add(b.id);
    }
    const lost = [];
    for (const id of beforeIds) {
      if (!afterIds.has(id)) {
        // Skip blocks the admin explicitly deleted — the × button
        // pre-registers them so the safety net doesn't undo the
        // delete. Container deletes also pre-register every
        // descendant id so a parent-with-children removal sticks.
        if (intentionallyRemovedIds.has(id)) continue;
        const payload = beforeById.get(id);
        // Only park leaf blocks + non-empty containers — empty
        // containers vanishing is fine (an empty wrapper isn't
        // worth recovering). For leaf containers that held
        // children whose ids ALSO went missing, those children
        // would already be parked individually by this same
        // pass, so dropping the empty wrapper is safe.
        if (!payload) continue;
        if (payload.type === 'container'
            && !((payload.data && payload.data.blocks) || []).length) {
          continue;
        }
        lost.push(payload);
      }
    }
    if (lost.length) {
      let orphanSec = sections.find(s => s && s._orphans);
      if (!orphanSec) {
        orphanSec = {
          id: uid(), title: 'Unplaced blocks', _orphans: true, blocks: [],
        };
        sections.push(orphanSec);
      }
      // Containers in `lost` may reference children that ALSO got
      // pushed individually. To avoid double-bookkeeping, strip
      // container nesting on the way to the bin: a lost container
      // becomes an empty wrapper (its lost children are individual
      // entries in `lost` already).
      lost.forEach(p => {
        if (p.type === 'container' && p.data) {
          const shallow = Object.assign({}, p, {
            data: Object.assign({}, p.data, { blocks: [] }),
          });
          orphanSec.blocks.push(shallow);
        } else {
          orphanSec.blocks.push(p);
        }
      });
      console.warn('[page_structure] safety net rescued '
                   + lost.length + ' block(s) into the Unplaced bin '
                   + '— this likely means the drag-drop reconstruction '
                   + 'has a bug.');
      // Surface the orphan card immediately so the admin can see the
      // rescued blocks and drag them back. The reconstruction-time
      // toggle in reconstructSectionsFromDom only sees the orphan
      // ZONE's DOM contents, not blocks added by this safety net to
      // the sections array; refresh the card state explicitly.
      if (orphansCard) orphansCard.classList.remove('is-empty');
      if (orphansCount) {
        orphansCount.textContent = '(' + (orphanSec.blocks.length) + ')';
      }
      // Also surface the rescued pills in the orphan ZONE so they're
      // visually present without waiting for a page reload. Each
      // rescued payload becomes a fresh pill DOM node in the bin.
      if (orphansZone) {
        lost.forEach(p => {
          const stamped = (p.type === 'container' && p.data)
            ? Object.assign({}, p, {
                data: Object.assign({}, p.data, { blocks: [] }),
              })
            : p;
          // Avoid duplicating pills if Sortable has already placed
          // the dragged element somewhere visible (rare race).
          if (!orphansZone.querySelector(
                '[data-page-block-id="' + (stamped.id || '__none__') + '"]')) {
            orphansZone.appendChild(makePillEl(stamped.type, stamped));
          }
        });
      }
    }

    // Re-seed the container lookup from the freshly-built sections
    // so containers removed by × delete or by being dragged into
    // an unreachable place don't leave stale entries in the map.
    // We don't `clear()` first so payloads pushed by registerContainerPayload
    // mid-tick (between the snapshot and the actual save) still
    // resolve — the next sync cleans them out if they're truly gone.
    containerPayloadById.clear();
    indexContainersIn(sections);

    // Consume the deliberate-deletion allowlist so a future drag-drop
    // bug still triggers the safety net normally. Each delete adds
    // its ids fresh just before calling syncStateFromDom.
    intentionallyRemovedIds.clear();

    const json = JSON.stringify(sections);
    hidden.value = json;
    if (editorRoot) editorRoot.dataset.initial = json;
    // Notify the save bar so it lights up "Unsaved changes". We
    // dispatch the input event THREE ways for reliability:
    //   1. On the hidden input itself — bubbles up to form-level
    //      listeners (the canonical native path).
    //   2. On the form directly — guarantees the form's `input`
    //      listener fires even when bubbling is interrupted by a
    //      stopPropagation higher up the tree, or when the form
    //      listener was instrumented after the hidden input was
    //      written to (we still need the form to land in the
    //      `dirty` set so clicking Save submits it).
    //   3. As a defensive last-resort, directly reveal the
    //      `#fe-save-bar` element if it's still hidden a tick
    //      after the events fire — covers any edge case where
    //      the IIFE's listener wasn't bound or the event was
    //      cancelled before reaching it.
    try { hidden.dispatchEvent(new Event('input', { bubbles: true })); }
    catch (_) {}
    const form = hidden.form
              || document.getElementById('page-edit-form');
    if (form) {
      try { form.dispatchEvent(new Event('input', { bubbles: true })); }
      catch (_) {}
    }
    setTimeout(() => {
      const bar = document.getElementById('fe-save-bar');
      if (bar && bar.hasAttribute('hidden')) {
        bar.hidden = false;
        const msg = bar.querySelector('.fe-save-bar-msg');
        if (msg) msg.textContent = 'Unsaved changes';
      }
    }, 0);
    // Force the modal-based BlockEditor to remount from the latest
    // state on next open. The structure card is now the canonical
    // composition view; the modal is just for editing one block's
    // content, and it should always reflect the latest tree.
    if (typeof window.remountPageBlockEditor === 'function') {
      window.remountPageBlockEditor();
    }
  }

  // ── Sortable wiring ─────────────────────────────────────────────
  // Every block-list zone joins a single shared group so cross-zone
  // drags (column → orphan, orphan → column, column-A → column-B,
  // etc.) work transparently.
  const SHARED_GROUP = 'be-zone';
  const sortableOpts = {
    group: SHARED_GROUP,
    animation: 140,
    ghostClass: 'is-drop-ghost',
    chosenClass: 'is-drop-chosen',
    dragClass:  'is-dragging',
    onSort: () => syncStateFromDom(),
    onAdd: () => syncStateFromDom(),
    onRemove: () => {/* paired with onAdd elsewhere — onSort fires too */},
  };
  // ── Click-to-edit handler (delegated) ───────────────────────────
  // Server-rendered pills get the existing per-element handler in
  // frontend_page_edit.html. Pills CREATED on the fly (palette drops,
  // row-factory output) miss that handler — this delegated listener
  // covers them. Both paths converge on the same mount-then-focus
  // flow, so the admin's experience is identical regardless of when
  // the pill was added. Skip when the click landed on a remove button
  // or any other inner button (Settings / Remove).
  document.addEventListener('click', e => {
    // Skip ONLY when the click is on an inner remove button — those
    // have their own delegated handlers further down. Settings
    // buttons (which carry data-page-block-id at the row-label
    // level) should fall through; the focus flow is exactly what
    // they're meant to trigger.
    if (e.target.closest('[data-be-remove-block], [data-be-remove-row]')) return;
    const pill = e.target.closest(
      '.fe-page-structure-block[data-page-block-id][data-open-modal]');
    if (!pill) return;
    // Don't double-fire when the server already bound this pill —
    // those binders set `data-pill-bound`.
    if (pill.dataset.pillBound === '1') return;
    const modalId = pill.getAttribute('data-open-modal');
    const blockId = pill.getAttribute('data-page-block-id');
    const m = document.getElementById(modalId);
    if (m) {
      m.classList.add('open');
      m.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
    }
    // Two rAFs so the modal-open transition has applied AND the
    // BlockEditor mount has rendered before we try to focus the
    // block. ensureEditor mounts from the LATEST `dataset.initial`
    // — which the structure card's syncStateFromDom keeps current
    // — so freshly-dragged blocks land in the editor with their
    // full settings UI rendered.
    requestAnimationFrame(() => {
      if (typeof window.ensurePageBlockEditor === 'function') {
        window.ensurePageBlockEditor();
      }
      requestAnimationFrame(() => {
        if (typeof window.focusPageBlock === 'function') {
          window.focusPageBlock(blockId);
        }
      });
    });
  });

  // ── Remove-button handlers (delegated) ──────────────────────────
  // BlockEditor (the modal) fires `blockremove` whenever a block is
  // deleted from inside the modal. When the deleted block was a
  // container holding children, the editor packages them up on
  // `detail.liftedChildren` so we can stamp pills into the structure
  // card's Unplaced-blocks zone. This is what makes the modal-driven
  // delete look exactly like the structure-card row × — children
  // dump straight into the orphan bin without the admin having to
  // refresh the page. The hidden field stays correct because we
  // run a sync after the mutation.
  if (editorRoot) {
    editorRoot.addEventListener('blockremove', e => {
      const kids = (e.detail && e.detail.liftedChildren) || [];
      if (!kids.length || !orphansZone) return;
      kids.forEach(child => {
        const pill = makeNodeFromPayload(child);
        if (!pill) return;
        // Containers nested inside a deleted container come through
        // this branch as full row payloads. The orphan bin holds
        // pills, not rows — so for nested-container children we drop
        // each grandchild into the bin (recursively flatten). For
        // anything else, makeNodeFromPayload already returned a pill
        // we can append directly.
        if (pill.classList && pill.classList.contains('fe-page-structure-row--split')) {
          ((child.data && child.data.blocks) || []).forEach(grand => {
            const gpill = makeNodeFromPayload(grand);
            if (gpill && gpill.classList.contains('fe-page-structure-block')) {
              orphansZone.appendChild(gpill);
            }
          });
        } else {
          orphansZone.appendChild(pill);
        }
      });
      if (orphansCard) orphansCard.classList.remove('is-empty');
      syncStateFromDom();
    });
  }

  // × on a pill removes the single block. × on a row removes the row;
  // if the row is a container holding child blocks, those children
  // get moved to the orphan bin first so the admin can drop them
  // back in.
  //
  // Two-layer interception so the modal-open click on the parent pill
  // never wins:
  //   1) Each × button gets its own click listener that handles the
  //      removal AND calls stopImmediatePropagation. Listeners on the
  //      target element fire BEFORE bubble-phase listeners on
  //      ancestors, so the parent pill's `data-open-modal` handler
  //      (registered by app.js) never sees the click.
  //   2) A capture-phase delegate on document catches × clicks that
  //      slip past the per-button binding (dynamically minted pills
  //      from palette drops, mutations from BlockEditor, etc.).
  //   A MutationObserver picks up newly-inserted × buttons so future
  //   pills get the per-button listener too.
  function bindRemoveButton(btn) {
    if (!btn || btn.__feRemoveBound) return;
    btn.__feRemoveBound = true;
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopImmediatePropagation();
      if (btn.matches('[data-be-remove-block]')) handleRemoveBlock(btn);
      else if (btn.matches('[data-be-remove-row]')) handleRemoveRow(btn);
    });
  }
  document.querySelectorAll('[data-be-remove-block], [data-be-remove-row]')
    .forEach(bindRemoveButton);
  if (window.MutationObserver) {
    const moRemove = new MutationObserver(records => {
      for (const r of records) {
        for (const n of r.addedNodes) {
          if (n.nodeType !== 1) continue;
          if (n.matches && (n.matches('[data-be-remove-block]')
                           || n.matches('[data-be-remove-row]'))) {
            bindRemoveButton(n);
          }
          if (n.querySelectorAll) {
            n.querySelectorAll('[data-be-remove-block], [data-be-remove-row]')
              .forEach(bindRemoveButton);
          }
        }
      }
    });
    moRemove.observe(document.body, { childList: true, subtree: true });
  }
  document.addEventListener('click', e => {
    const rb = e.target.closest('[data-be-remove-block]');
    if (rb) {
      e.preventDefault(); e.stopImmediatePropagation();
      handleRemoveBlock(rb);
      return;
    }
    const rr = e.target.closest('[data-be-remove-row]');
    if (rr) {
      e.preventDefault(); e.stopImmediatePropagation();
      handleRemoveRow(rr);
      return;
    }
  }, true);

  // Returns true if a block payload carries actual content the admin
  // would notice losing. Mirrors `_block_has_content` in routes.py
  // for symmetric "is this block worth orphaning instead of deleting?"
  // semantics. Empty placeholders (a fresh-from-palette paragraph,
  // a default Click-here button) report false.
  function pillHasContent(payload) {
    if (!payload || !payload.type) return false;
    const t = payload.type, d = payload.data || {};
    if (t === 'paragraph') return !!(d.md || '').trim();
    if (t === 'heading') return !!(d.text || '').trim();
    if (t === 'image') return !!(d.src || '').trim();
    if (t === 'button') {
      const label = (d.label || '').trim();
      const url = (d.url || '').trim();
      return !!(url || (label && label !== 'Click here'));
    }
    if (t === 'list') {
      return (d.items || []).some(s => String(s || '').trim());
    }
    if (t === 'callout') return !!((d.title || '').trim() || (d.md || '').trim());
    if (t === 'video') return !!(d.src || '').trim();
    if (t === 'code') return !!(d.code || '').trim();
    if (t === 'container') return (d.blocks || []).length > 0;
    if (t === 'toc_sidebar') return true;
    if (t === 'separator') return false;
    return false;
  }

  function handleRemoveBlock(btn) {
    const pill = btn.closest('.fe-page-structure-block[data-block-payload]');
    if (!pill) return;
    let payload = null;
    try { payload = JSON.parse(pill.getAttribute('data-block-payload') || 'null'); } catch (_) {}
    const hasContent = pillHasContent(payload);
    const inOrphans = !!pill.closest('[data-be-zone="orphans"]');
    let msg;
    if (!hasContent) {
      msg = 'Remove this empty block?';
    } else if (inOrphans) {
      // Orphan pills are already in the parking lot — the only path
      // out of here besides drag-back-to-layout is permanent
      // deletion. Make the warning explicit.
      msg = 'Permanently delete this block? It will be removed from the page entirely — this can’t be undone.';
    } else {
      // Active-layout pill with content. Warn about data loss AND
      // tell the admin they can park it instead of deleting.
      msg = 'Delete this block?\n\n'
          + 'It contains content that will be permanently removed. '
          + 'To keep it for later, drag the pill into the "Unplaced blocks" '
          + 'bin instead — anything in there survives layout switches.';
    }
    if (!confirm(msg)) return;
    // Pre-register the deleted block (and any descendants — a container
    // pill carries its kids in `data.blocks`) so the safety net in
    // syncStateFromDom doesn't see them as "lost" and rescue them
    // straight back into the orphan bin.
    if (payload && payload.id) intentionallyRemovedIds.add(payload.id);
    (function walk(p) {
      const kids = (p && p.data && p.data.blocks) || [];
      for (const k of kids) {
        if (k && k.id) intentionallyRemovedIds.add(k.id);
        walk(k);
      }
    })(payload);
    pill.remove();
    syncStateFromDom();
  }

  // ── Container-removal confirm modal ────────────────────────────
  // Shown when the admin clicks × on a container row that holds
  // blocks. Two destinations for the children:
  //   • "Move to Unplaced blocks" → safe path, content survives in the
  //     orphan bin, drag back any time.
  //   • "Remove everything" → permanent delete of the container AND
  //     every block inside (recursive — nested containers' kids included).
  // Built lazily on first need so multiple page-structure mounts don't
  // duplicate the markup. `onChoose` receives 'park' | 'all'; cancel
  // dismisses without callback.
  let _containerRemoveModal = null;
  function ensureContainerRemoveModal() {
    if (_containerRemoveModal) return _containerRemoveModal;
    const modal = document.createElement('div');
    modal.className = 'modal be-container-remove-modal';
    modal.id = 'be-container-remove-modal';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML =
      '<div class="modal-backdrop" data-close></div>' +
      '<div class="modal-panel" role="dialog" aria-modal="true" ' +
        'aria-labelledby="be-container-remove-title">' +
        '<div class="modal-head">' +
          '<h2 id="be-container-remove-title">Remove container</h2>' +
          '<button type="button" class="icon-btn" data-close aria-label="Cancel">×</button>' +
        '</div>' +
        '<div class="modal-body">' +
          '<p data-msg class="be-container-remove-msg"></p>' +
          '<div class="be-container-remove-choices">' +
            '<button type="button" class="be-container-remove-choice be-container-remove-park" data-choice="park">' +
              '<span class="be-container-remove-choice-title">Move blocks to "Unplaced blocks"</span>' +
              '<span class="be-container-remove-choice-desc">Keep them for later. Drag from the unused bin into any layout to use them again. <b>No content lost.</b></span>' +
            '</button>' +
            '<button type="button" class="be-container-remove-choice be-container-remove-all" data-choice="all">' +
              '<span class="be-container-remove-choice-title">Remove everything</span>' +
              '<span class="be-container-remove-choice-desc">Permanently delete the container <b>and every block inside</b>. Can\'t be undone.</span>' +
            '</button>' +
          '</div>' +
        '</div>' +
        '<div class="modal-foot">' +
          '<button type="button" class="btn" data-close>Cancel</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(modal);
    _containerRemoveModal = {
      el: modal,
      open(count, label, onChoose) {
        const msg = modal.querySelector('[data-msg]');
        const noun = count === 1 ? 'block' : 'blocks';
        const it   = count === 1 ? 'it' : 'them';
        msg.textContent =
          (label ? '"' + label + '" ' : 'This container ') +
          'has ' + count + ' ' + noun + ' inside. What should happen to ' + it + '?';
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        function close() {
          modal.classList.remove('open');
          modal.setAttribute('aria-hidden', 'true');
          document.body.style.overflow = '';
          modal.removeEventListener('click', onClick);
          document.removeEventListener('keydown', onEsc);
        }
        function onClick(e) {
          const choice = e.target.closest('[data-choice]');
          if (choice) {
            const v = choice.dataset.choice;
            close();
            onChoose(v);
            return;
          }
          if (e.target.closest('[data-close]')) {
            close();
          }
        }
        function onEsc(e) { if (e.key === 'Escape') close(); }
        modal.addEventListener('click', onClick);
        document.addEventListener('keydown', onEsc);
      },
    };
    return _containerRemoveModal;
  }

  function handleRemoveRow(btn) {
    const row = btn.closest('.fe-page-structure-row');
    if (!row) return;
    // Collect the row's child block pills so containerised content
    // doesn't disappear with the row chrome. Walks every cell zone
    // inside the row — for a row-single this is the lone pill, for
    // a row-split it's every pill across all column cells.
    const childPills = Array.from(row.querySelectorAll(
      '.fe-page-structure-block[data-block-payload]'));
    const isContainer = row.classList.contains('fe-page-structure-row--split');
    let moveCount = 0;
    if (isContainer) {
      const containerId = row.getAttribute('data-be-row-block-id');
      // Empty container → simple confirm + remove. No data to ferry.
      if (childPills.length === 0) {
        if (!confirm('Remove this empty container?')) return;
        if (containerId) intentionallyRemovedIds.add(containerId);
        row.remove();
        syncStateFromDom();
        return;
      }
      // Non-empty container → two-choice modal. Pull the container's
      // admin label (if any) so the prompt reads as "Officers has 10
      // blocks inside…" rather than the generic "This container".
      let label = '';
      try {
        const containerPayload = findContainerPayload(containerId);
        label = (containerPayload && containerPayload.data && containerPayload.data.label) || '';
      } catch (_) { label = ''; }
      ensureContainerRemoveModal().open(childPills.length, label, choice => {
        if (choice === 'park') {
          // Park path: ferry every child pill into the orphan bin.
          // Container payload itself goes onto the deliberate-removal
          // allowlist so the safety net doesn't rescue it back as an
          // empty wrapper. Kids stay in the DOM (now under orphansZone)
          // so they reconstruct normally on next sync.
          if (orphansZone) {
            childPills.forEach(p => {
              orphansZone.appendChild(p);
              moveCount++;
            });
          }
          if (containerId) intentionallyRemovedIds.add(containerId);
          row.remove();
          syncStateFromDom();
          if (moveCount && orphansCard) orphansCard.classList.remove('is-empty');
        } else if (choice === 'all') {
          // Remove-all path: flag EVERY descendant id (recursive) as
          // deliberately removed BEFORE wiping the row, so the safety
          // net doesn't sweep them into the orphan bin.
          //
          // Two sources of descendant ids — both must be walked:
          //   1. Pill payloads: leaf blocks rendered as `.fe-page-
          //      structure-block` elements with `data-block-payload`.
          //      Walk each pill's data.blocks tree so containers
          //      hidden inside leaf-pill payloads are caught.
          //   2. Nested container rows: rendered as `.fe-page-
          //      structure-row` elements (NOT pills) carrying
          //      `data-be-row-block-id`. The parent container's
          //      payload (from `findContainerPayload`) holds the
          //      authoritative data.blocks tree for these — walk
          //      that tree directly so nested-container ids get
          //      flagged regardless of which DOM elements they
          //      were rendered as.
          if (containerId) intentionallyRemovedIds.add(containerId);
          // Source 1 — every pill in the row's subtree.
          childPills.forEach(p => {
            let payload = null;
            try { payload = JSON.parse(p.getAttribute('data-block-payload') || 'null'); } catch (_) {}
            if (payload && payload.id) intentionallyRemovedIds.add(payload.id);
            (function walk(pl) {
              const kids = (pl && pl.data && pl.data.blocks) || [];
              for (const k of kids) {
                if (k && k.id) intentionallyRemovedIds.add(k.id);
                walk(k);
              }
            })(payload);
          });
          // Source 2 — every row inside the row being removed
          // (nested containers don't have data-block-payload).
          row.querySelectorAll('[data-be-row-block-id]').forEach(r => {
            const rid = r.getAttribute('data-be-row-block-id');
            if (rid) intentionallyRemovedIds.add(rid);
          });
          // Source 3 — walk the parent container payload's full
          // tree, flagging every id along the way. Belt-and-braces:
          // catches anything that wasn't rendered as a pill or row
          // (e.g. orphan-bin parking that never made it back into
          // the active tree but still has an id in containerPayloadById).
          try {
            const parentPayload = findContainerPayload(containerId);
            (function walkAll(pl) {
              if (!pl) return;
              if (pl.id) intentionallyRemovedIds.add(pl.id);
              const kids = (pl.data && pl.data.blocks) || [];
              for (const k of kids) walkAll(k);
            })(parentPayload);
          } catch (_) { /* defensive — payload lookup is optional */ }
          row.remove();
          syncStateFromDom();
        }
      });
      return;
    }
    {
      // Row-single: deleting the row also deletes its lone block.
      // Warn about data loss and suggest the orphan alternative when
      // the block carries actual content.
      const lone = childPills[0] || null;
      let payload = null;
      if (lone) {
        try { payload = JSON.parse(lone.getAttribute('data-block-payload') || 'null'); } catch (_) {}
      }
      const hasContent = pillHasContent(payload);
      let msg;
      if (!lone) {
        msg = 'Remove this empty row?';
      } else if (hasContent) {
        msg = 'Delete this row?\n\n'
            + 'The block inside contains content that will be permanently removed. '
            + 'To keep it for later, drag the pill into the "Unplaced blocks" bin first.';
      } else {
        msg = 'Remove this row? The empty block inside will go with it.';
      }
      if (!confirm(msg)) return;
      // Same allowlist registration as handleRemoveBlock — the lone
      // block (and any descendants if it's a container) need to be
      // flagged so the safety net doesn't put them back.
      if (payload && payload.id) intentionallyRemovedIds.add(payload.id);
      (function walk(p) {
        const kids = (p && p.data && p.data.blocks) || [];
        for (const k of kids) {
          if (k && k.id) intentionallyRemovedIds.add(k.id);
          walk(k);
        }
      })(payload);
    }
    row.remove();
    syncStateFromDom();
    if (moveCount && orphansCard) orphansCard.classList.remove('is-empty');
  }

  function bindZones() {
    document.querySelectorAll('[data-be-zone]').forEach(zone => {
      if (zone._sortable) return;
      // Root zone is special — its items are entire ROWS, not pills,
      // and it lives in its own group so pills don't try to drop into
      // the gap between rows. The drag handle is the row label so
      // grabbing a pill inside a row doesn't grab the row.
      if (zone.dataset.beZone === 'root') {
        zone._sortable = Sortable.create(zone, {
          group: { name: 'be-rows', pull: false, put: false },
          draggable: '.fe-page-structure-row',
          // Drag handles: the row-label area on multi-column rows
          // (which sits in the left gutter on desktop) AND the
          // dedicated `.fe-page-row-handle` grip on row-single rows.
          // Pill drags use the pill itself as their handle so they
          // never trigger row reordering.
          handle: '.fe-page-structure-row-label, .fe-page-row-handle',
          // Exclude the inline label input from drag-handle territory
          // so admins can click it to focus and type without kicking
          // off a row reorder. `preventOnFilter: false` lets the click
          // pass through to the input's native focus behaviour.
          filter: '.fe-page-structure-row-label-input',
          preventOnFilter: false,
          animation: 140,
          ghostClass: 'is-row-ghost',
          chosenClass: 'is-row-chosen',
          dragClass: 'is-row-dragging',
          onSort: () => syncStateFromDom(),
        });
        return;
      }
      zone._sortable = Sortable.create(zone, sortableOpts);
    });
  }
  bindZones();

  // ── Inline container labels ─────────────────────────────────────
  // The structure tree's row-label area carries a `[data-be-row-label
  // -input]` text field that's bound directly to the underlying
  // container payload. Editing it updates `payload.data.label`,
  // triggers a sync (so the hidden `blocks_json` reflects the new
  // label on the next form submit), and toggles the `is-labelled`
  // class so the placeholder-vs-labelled style swaps in/out live.
  // Delegated on document so newly-dropped rows pick this up without
  // needing per-row binding.
  document.addEventListener('input', e => {
    const input = e.target.closest('[data-be-row-label-input]');
    if (!input) return;
    const blockId = input.dataset.beRowBlockId;
    if (!blockId) return;
    const payload = findContainerPayload(blockId);
    if (!payload) return;
    payload.data = payload.data || {};
    const trimmed = (input.value || '').trim();
    payload.data.label = trimmed;
    input.classList.toggle('is-labelled', !!trimmed);
    syncStateFromDom();
    // syncStateFromDom updates `data-initial` on the editor root, but
    // the modal editor caches the parsed initial into a closure var
    // at IIFE startup. Calling `remountPageBlockEditor` resets that
    // cache so the next time the modal opens, the editor mounts with
    // the new label baked in. Safe to call here: the structure-card
    // input only receives input events when the modal is closed (the
    // modal overlay covers the structure tree), so we never destroy
    // an in-flight editor session.
    if (typeof window.remountPageBlockEditor === 'function') {
      window.remountPageBlockEditor();
    }
  });
  // `change` fires on blur; same logic, just one final commit so
  // syncStateFromDom doesn't drown in keystroke-by-keystroke writes
  // for very long labels. Input above already kept the payload + DOM
  // in step; this is a safety net for paste / autocomplete.
  document.addEventListener('change', e => {
    const input = e.target.closest('[data-be-row-label-input]');
    if (!input) return;
    syncStateFromDom();
  });
  // Sortable.js's filter handles most click→drag interception, but
  // some browsers still bubble the mousedown to the row's drag
  // tracker if pointer-capture flips inside the input. Stop the
  // bubble explicitly so the row never starts a drag from a label
  // click — typing UX wins over edge-case mobile drag-from-input.
  document.addEventListener('mousedown', e => {
    if (e.target.closest('[data-be-row-label-input]')) {
      e.stopPropagation();
    }
  }, true);

  // ── Palette drag → drop creates a new pill ──────────────────────
  // Uses HTML5 drag-and-drop (palette tiles can't reasonably be
  // Sortable items because they're not in any zone). On drop into a
  // Sortable zone, we mint a new block payload and call syncState.
  // ── Floating palette toggle ────────────────────────────────────
  // The palette lives in `[data-fe-palette-floating]` as a fixed-
  // position card with a FAB → panel collapse/expand. Clicking the
  // FAB or the close × flips the `is-open` class on the wrapper; CSS
  // animates the FAB out + the panel in. Clicks outside the wrapper
  // dismiss the panel as well — but only when no drag is in flight,
  // so dropping a tile into a structure zone doesn't immediately
  // collapse the palette before the next drop.
  let _palDragging = false;
  const palWrap = document.querySelector('[data-fe-palette-floating]');
  if (palWrap) {
    palWrap.addEventListener('click', e => {
      const toggle = e.target.closest('[data-fe-palette-toggle]');
      if (!toggle) return;
      e.preventDefault();
      const open = !palWrap.classList.contains('is-open');
      palWrap.classList.toggle('is-open', open);
      const fab = palWrap.querySelector('.fe-page-palette-fab');
      const panel = palWrap.querySelector('.fe-page-palette-panel');
      if (fab) fab.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (panel) panel.setAttribute('aria-hidden', open ? 'false' : 'true');
    });
    // Click-outside dismiss. Skipped while a tile is mid-drag so the
    // palette stays open until the drop completes (drop targets live
    // outside the palette wrapper and would otherwise count as
    // "outside" clicks during the implicit dragend tick).
    document.addEventListener('click', e => {
      if (!palWrap.classList.contains('is-open')) return;
      if (_palDragging) return;
      if (palWrap.contains(e.target)) return;
      palWrap.classList.remove('is-open');
      const fab = palWrap.querySelector('.fe-page-palette-fab');
      const panel = palWrap.querySelector('.fe-page-palette-panel');
      if (fab) fab.setAttribute('aria-expanded', 'false');
      if (panel) panel.setAttribute('aria-hidden', 'true');
    });
    // Escape key collapses an open palette — matches the modal-style
    // dismiss admins expect from any floating overlay.
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      if (!palWrap.classList.contains('is-open')) return;
      palWrap.classList.remove('is-open');
      const fab = palWrap.querySelector('.fe-page-palette-fab');
      const panel = palWrap.querySelector('.fe-page-palette-panel');
      if (fab) {
        fab.setAttribute('aria-expanded', 'false');
        fab.focus();
      }
      if (panel) panel.setAttribute('aria-hidden', 'true');
    });
  }

  if (palette) {
    palette.querySelectorAll('.fe-page-palette-tile').forEach(tile => {
      tile.addEventListener('dragstart', e => {
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('application/x-fe-page-block', tile.dataset.beBlockType);
        e.dataTransfer.setData('text/plain', tile.dataset.beBlockName || tile.dataset.beBlockType);
        tile.classList.add('is-dragging');
        _palDragging = true;
      });
      tile.addEventListener('dragend', () => {
        tile.classList.remove('is-dragging');
        // Defer clearing the drag-flag so the trailing click event
        // (some browsers synthesise one after a successful drop) is
        // still treated as "during a drag" and skips the dismiss.
        setTimeout(() => { _palDragging = false; }, 100);
      });
    });
  }
  // Listen on every zone for palette drops. Sortable's own drag
  // handlers run for pill→pill moves; HTML5 drop lands here only
  // when the source carries our custom mime type.
  document.addEventListener('dragover', e => {
    const zone = e.target.closest('[data-be-zone]');
    if (!zone) return;
    if (!Array.from(e.dataTransfer.types).includes('application/x-fe-page-block')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    zone.classList.add('is-drop-target');
  });
  document.addEventListener('dragleave', e => {
    const zone = e.target.closest('[data-be-zone]');
    if (zone) zone.classList.remove('is-drop-target');
  });
  document.addEventListener('drop', e => {
    const zone = e.target.closest('[data-be-zone]');
    if (!zone) return;
    const type = e.dataTransfer.getData('application/x-fe-page-block');
    if (!type) return;
    e.preventDefault();
    zone.classList.remove('is-drop-target');
    const factory = BLANK_DATA[type];
    if (!factory) return;

    // Build the block payload. Splits aren't a first-class block on
    // pages — they materialise as a multi-column grid container with
    // a matching number of inner containers ready to host child pills.
    // `split` = two columns, `split3` = three columns. The pattern
    // generalises if we ever add `split4` etc.
    let payload;
    const splitCols = type === 'split' ? 2 : (type === 'split3' ? 3 : 0);
    if (splitCols > 0) {
      const data = BLANK_DATA.container();
      data.display = 'grid';
      data.grid_columns = Array(splitCols).fill('1fr').join(' ');
      data.gap = '2rem'; data.padding = '0';
      data.blocks = Array.from({ length: splitCols }, () => (
        { id: uid(), type: 'container', data: BLANK_DATA.container() }
      ));
      payload = { id: uid(), type: 'container', data };
    } else {
      payload = { id: uid(), type, data: factory() };
    }
    // Register newly-minted container payloads up front so the
    // reconstruction that runs at the end of this drop handler can
    // resolve them via `findContainerPayload`. Without this,
    // `findContainerPayload` only knew about server-seeded
    // containers that lived in `sections` — a fresh palette drop
    // would slip through and the new container (plus anything
    // dragged into it) would be rescued to the orphan bin instead
    // of placed properly.
    if (payload.type === 'container') registerContainerPayload(payload);

    if (zone.dataset.beZone === 'root') {
      // Top-level drop — mint a new ROW. Container/split → row--split
      // (single- or multi-column). Anything else → row--single.
      // Insert at the cursor position relative to existing rows
      // (drop above the row whose midpoint is below the cursor;
      // append to the end if the cursor is past the last row).
      const row = makeRowFromPayload(payload);
      const existingRows = Array.from(zone.querySelectorAll(':scope > .fe-page-structure-row'));
      const after = existingRows.find(r => {
        const rect = r.getBoundingClientRect();
        return e.clientY < rect.top + rect.height / 2;
      });
      if (after) zone.insertBefore(row, after); else zone.appendChild(row);
      const empty = zone.querySelector('[data-be-root-empty]');
      if (empty) empty.remove();
      bindZones();
    } else if (payload.type === 'container'
               && zone.dataset.beZone === 'container-col') {
      // Nested container dropped INTO a column cell — render as a
      // sub-row (with its own column cells + drop zones) so the user
      // sees the nested structure in place. Insert at the cursor's
      // vertical position relative to existing pills/rows in this
      // cell; bindZones() picks up the new row's zones.
      const row = makeRowFromPayload(payload);
      const siblings = Array.from(zone.children).filter(
        c => c.classList && (c.classList.contains('fe-page-structure-block')
                            || c.classList.contains('fe-page-structure-row')));
      const after = siblings.find(r => {
        const rect = r.getBoundingClientRect();
        return e.clientY < rect.top + rect.height / 2;
      });
      if (after) zone.insertBefore(row, after); else zone.appendChild(row);
      bindZones();
    } else {
      // Leaf drop (paragraph, heading, image, button, list, etc.)
      // into any inner zone — create a flat pill.
      const pill = makePillEl(payload.type, payload);
      zone.appendChild(pill);
    }
    syncStateFromDom();
  });

  // ── Initial state push ──────────────────────────────────────────
  // Make sure the hidden input + data-initial reflect what's on the
  // page now, so the modal-based BlockEditor reads from a single
  // source of truth on first open.
  if (sections.length) {
    hidden.value = JSON.stringify(sections);
  }

  // Surface labels for client-side pill creation.
  window.tspBlockLabels = {
    paragraph:   ['Text',         'type'],
    heading:     ['Heading',      'heading'],
    image:       ['Image',        'image'],
    button:      ['Button',       'mouse-pointer-click'],
    container:   ['Container',    'layout-grid'],
    video:       ['Video',        'video'],
    lottie:      ['Lottie',       'play-circle'],
    intergroup_member: ['Intergroup Member', 'users'],
    intergroup_member_roster: ['Officer Roster', 'users'],
    library:     ['Library',        'book-open'],
    code:        ['Code',         'code'],
    callout:     ['Callout',      'alert-triangle'],
    list:        ['List',         'list'],
    separator:   ['Divider',      'minus'],
    toc_sidebar: ['Wiki sidebar', 'list'],
    split:       ['Two-panel',    'columns'],
    split3:      ['Three-panel',  'layout-grid'],
  };
})();
