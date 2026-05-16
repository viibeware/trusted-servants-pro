/* Blog post body — visual drag-and-drop block editor.
 *
 * Self-contained module bound to the markup in `templates/blog_edit.html`.
 * State lives in a single `blocks` array (a list of {id, type, data}
 * objects). Every mutation re-renders the canvas; every render seeds
 * the form's hidden `body_blocks_json` input via the `commit()` helper,
 * so a normal form submit round-trips the latest tree without any
 * "did the editor flush?" race.
 *
 * Drag-and-drop is split across two DataTransfer payloads:
 *   • "application/x-pbe-new" — fired by palette tiles. Drop creates
 *     a fresh block at the insertion index.
 *   • "application/x-pbe-move" — fired by an existing block's drag
 *     handle. Drop reorders the block to the insertion index.
 * A single drop handler on the canvas dispatches on whichever
 * payload the event carries.
 */
(function () {
  'use strict';

  const canvas = document.getElementById('pbe-canvas');
  const hidden = document.getElementById('pbe-blocks-json');
  const legacyBody = document.getElementById('pbe-legacy-body');
  const palette = document.querySelector('[data-pbe-palette]');
  if (!canvas || !hidden || !palette) return;

  // ── State ────────────────────────────────────────────────────────
  // `blocks` is the source of truth; every render walks it. IDs are
  // ephemeral (assigned client-side) so reorder / duplicate / delete
  // don't need to round-trip through the server. Persistence is via
  // the hidden form input which holds `{type, data}` only (the IDs
  // are stripped on serialise).
  let blocks = [];
  let idSeq = 1;
  const nextId = () => 'b' + (idSeq++);

  function loadInitial() {
    const raw = (hidden.value || '').trim();
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        blocks = parsed.map(b => assignIds(b));
      }
    } catch (err) {
      console.warn('post body editor: malformed JSON, starting empty', err);
    }
  }

  // Recursively stamp a fresh ephemeral id on every block + every
  // child of a Section. Storage doesn't carry ids — they're only
  // for the editor's drag-and-drop / move bookkeeping — so the loader
  // mints fresh ones on every page load.
  function assignIds(b) {
    const data = b.data || {};
    const out = { id: nextId(), type: b.type, data: data };
    if (b.type === 'section' && Array.isArray(data.blocks)) {
      out.data = Object.assign({}, data, {
        blocks: data.blocks.map(child => assignIds(child)),
      });
    }
    return out;
  }

  // Serialise a block stripped of its ephemeral id (and recursively
  // for Sections). Only `type` + `data` are persisted.
  function stripBlock(b) {
    const data = b.data || {};
    if (b.type === 'section' && Array.isArray(data.blocks)) {
      return {
        type: b.type,
        data: Object.assign({}, data, {
          blocks: data.blocks.map(stripBlock),
        }),
      };
    }
    return { type: b.type, data: data };
  }

  function commit() {
    const payload = blocks.map(stripBlock);
    hidden.value = JSON.stringify(payload);
    // The legacy markdown body stays in the hidden `body` field, but
    // once the editor has any blocks at all the public render reads
    // blocks first — so clear `body` to avoid stale Markdown poking
    // through if the post is ever rolled back to legacy mode.
    if (legacyBody && blocks.length > 0) {
      legacyBody.value = '';
    }
  }

  // ── Block templates ──────────────────────────────────────────────
  // Each entry shapes the default `data` for a fresh block of that
  // type. Keep in sync with `_sanitize_blog_block_data` in routes.py
  // so client defaults survive the round-trip.
  const BLOCK_DEFAULTS = {
    paragraph: () => ({ md: '' }),
    heading:   () => ({ level: 2, text: '' }),
    image:     () => ({ src: '', alt: '', caption: '', align: 'center', width_pct: 100 }),
    button:    () => ({ label: 'Click here', url: '', style: 'primary', align: 'left', new_tab: false }),
    list:      () => ({ ordered: false, items: [''] }),
    quote:     () => ({ text: '', author: '' }),
    callout:   () => ({ variant: 'info', title: '', md: '' }),
    separator: () => ({}),
    video:     () => ({ url: '', caption: '' }),
    code:      () => ({ lang: '', code: '' }),
    section:   () => ({ margin_top: 3, margin_bottom: 3, blocks: [] }),
  };

  const BLOCK_LABELS = {
    paragraph: 'Paragraph', heading:   'Heading',  image: 'Image',
    button:    'Button',    list:      'List',     quote: 'Quote',
    callout:   'Callout',   separator: 'Divider',  video: 'Video',
    code:      'Code',      section:   'Section',
  };

  // Section can hold nested blocks but the schema is intentionally
  // flat after that — a Section can't contain another Section. The
  // server sanitizer enforces the same cap; this client check keeps
  // the palette from offering Section drops inside an existing
  // section so the UI matches storage.
  function canHostSections(host) {
    return host === blocks;
  }

  // ── Element helpers ──────────────────────────────────────────────
  // `el()` is a tiny hyperscript so the per-block render functions
  // read top-down without a wall of `document.createElement` noise.
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        const v = attrs[k];
        if (v == null || v === false) continue;
        if (k === 'class') node.className = v;
        else if (k === 'html') node.innerHTML = v;
        else if (k.startsWith('on') && typeof v === 'function') {
          node.addEventListener(k.slice(2).toLowerCase(), v);
        } else if (k === 'dataset' && typeof v === 'object') {
          for (const dk in v) node.dataset[dk] = v[dk];
        } else {
          node.setAttribute(k, v === true ? '' : v);
        }
      }
    }
    if (children == null) return node;
    const arr = Array.isArray(children) ? children : [children];
    for (const c of arr) {
      if (c == null || c === false) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  // CSRF for the upload endpoint — pulled out of the post form's
  // hidden input so we don't have to refetch it per upload.
  function csrfToken() {
    const inp = document.querySelector('#blog-edit-form input[name="csrf_token"]');
    return inp ? inp.value : '';
  }

  // Vendored lucide icon strings (compact subset matching the icons
  // already loaded by base.html). Each value is the SVG path content
  // wrapped by `svgIcon()`. Avoids round-tripping through Jinja each
  // time the user adds a block.
  const ICON_PATHS = {
    'grip-vertical':
      '<circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle cx="9" cy="19" r="1"/>' +
      '<circle cx="15" cy="12" r="1"/><circle cx="15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/>',
    'trash-2':
      '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>' +
      '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
    'copy':
      '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    'chevron-up':   '<polyline points="18 15 12 9 6 15"/>',
    'chevron-down': '<polyline points="6 9 12 15 18 9"/>',
    'upload':       '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    'folder':       '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    'plus':         '<path d="M12 5v14"/><path d="M5 12h14"/>',
    'x':            '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  };
  function svgIcon(name) {
    const paths = ICON_PATHS[name] || '';
    return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  }

  // ── Per-block editor bodies ──────────────────────────────────────
  // Each function returns the *contents* of a block (everything
  // between the chrome and the toolbar). They mutate `b.data` in
  // place and call `commit()` after each input event so save-on-blur
  // isn't needed — the form's hidden field always reflects the live
  // state.

  function bindInput(input, onValue) {
    input.addEventListener('input', e => { onValue(e.target.value); commit(); });
  }

  function renderParagraph(b) {
    return el('div', { class: 'pbe-block-body' }, [
      (() => {
        const ta = el('textarea', {
          class: 'pbe-input pbe-textarea pbe-paragraph-input',
          rows: 4,
          placeholder: 'Write your text here. **Bold**, *italic*, [link](https://example.com), and other Markdown work inline.',
        });
        ta.value = b.data.md || '';
        autosize(ta);
        bindInput(ta, v => b.data.md = v);
        return ta;
      })(),
    ]);
  }

  function renderHeading(b) {
    const sel = el('select', { class: 'pbe-input pbe-select pbe-heading-level' });
    [2, 3, 4].forEach(n => {
      const opt = el('option', { value: n }, ['Heading ' + n]);
      if ((b.data.level || 2) === n) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener('change', e => {
      b.data.level = parseInt(e.target.value, 10) || 2;
      commit();
      // Live-restyle the placeholder so the writer sees H2 vs H3 size
      // immediately rather than waiting on a re-render.
      const input = sel.parentElement.querySelector('.pbe-heading-input');
      if (input) input.dataset.level = b.data.level;
    });

    const input = el('input', {
      type: 'text',
      class: 'pbe-input pbe-heading-input',
      placeholder: 'Section heading…',
      dataset: { level: String(b.data.level || 2) },
    });
    input.value = b.data.text || '';
    bindInput(input, v => b.data.text = v);

    return el('div', { class: 'pbe-block-body pbe-heading-body' }, [sel, input]);
  }

  function renderImage(b) {
    if (typeof b.data.shadow !== 'string') b.data.shadow = '';
    // Box-shadow recipes mirror `_blog_blocks.html` so the preview
    // matches the public render exactly.
    const SHADOW_RECIPES = {
      sm: '0 1px 2px rgba(0,0,0,.06), 0 1px 3px rgba(0,0,0,.10)',
      md: '0 4px 6px rgba(0,0,0,.08), 0 2px 4px rgba(0,0,0,.06)',
      lg: '0 10px 15px rgba(0,0,0,.10), 0 4px 6px rgba(0,0,0,.08)',
      xl: '0 20px 25px rgba(0,0,0,.15), 0 10px 10px rgba(0,0,0,.06)',
    };

    const preview = el('div', { class: 'pbe-image-preview' });
    function repaintPreview() {
      preview.innerHTML = '';
      if (b.data.src) {
        const img = el('img', { src: b.data.src, alt: b.data.alt || '' });
        img.style.boxShadow = SHADOW_RECIPES[b.data.shadow] || '';
        preview.appendChild(img);
      } else {
        preview.appendChild(el('div', { class: 'pbe-image-empty' }, ['No image yet — upload or paste a URL below.']));
      }
    }
    repaintPreview();

    const srcInput = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'https://example.com/photo.jpg  or  /pub/photo.jpg',
    });
    srcInput.value = b.data.src || '';
    bindInput(srcInput, v => { b.data.src = v; repaintPreview(); });

    const hiddenFile = el('input', {
      type: 'file', accept: 'image/*',
      style: 'display: none',
    });
    hiddenFile.addEventListener('change', e => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      uploadImage(file, url => {
        b.data.src = url;
        srcInput.value = url;
        commit();
        repaintPreview();
      });
    });

    const uploadBtn = el('button', {
      type: 'button',
      class: 'btn btn-sm pbe-upload-btn',
      onclick: () => hiddenFile.click(),
      title: 'Upload an image from your computer',
    });
    uploadBtn.innerHTML = svgIcon('upload') + '<span>Upload</span>';

    const browseBtn = el('button', {
      type: 'button',
      class: 'btn btn-sm pbe-browse-btn',
      onclick: () => openImageBrowser(item => {
        // Picker now hands back the full MediaItem dict; the image
        // block only needs the public URL.
        b.data.src = item.url || ('/pub/' + (item.original_filename || ''));
        srcInput.value = b.data.src;
        commit();
        repaintPreview();
      }),
      title: 'Pick from images already uploaded to this site',
    });
    browseBtn.innerHTML = svgIcon('folder') + '<span>Browse</span>';

    const altInput = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'Alt text (describe the image for screen readers)',
    });
    altInput.value = b.data.alt || '';
    bindInput(altInput, v => b.data.alt = v);

    const capInput = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'Caption (optional)',
    });
    capInput.value = b.data.caption || '';
    bindInput(capInput, v => b.data.caption = v);

    const alignGroup = renderSegmented(['left', 'center', 'right'],
      b.data.align || 'center', v => { b.data.align = v; commit(); });

    const widthInput = el('input', {
      type: 'range', min: '20', max: '100', step: '5',
      class: 'pbe-range',
    });
    widthInput.value = String(b.data.width_pct || 100);
    const widthValue = el('span', { class: 'pbe-range-value' }, [(b.data.width_pct || 100) + '%']);
    widthInput.addEventListener('input', e => {
      const v = parseInt(e.target.value, 10) || 100;
      b.data.width_pct = v;
      widthValue.textContent = v + '%';
      commit();
    });

    // Box-shadow tier — None plus four intensities matching the
    // `_blog_blocks.html` recipes. `repaintPreview` reads
    // `b.data.shadow` on every rebuild so picking a tier just needs
    // to mutate the field and re-repaint; a fresh `<img>` after a
    // src / library pick also inherits the current shadow for free.
    const shadowGroup = renderSegmented(
      [['', 'None'], ['sm', 'Small'], ['md', 'Medium'],
       ['lg', 'Large'], ['xl', 'X-Large']],
      b.data.shadow || '',
      v => { b.data.shadow = v; commit(); repaintPreview(); }
    );

    // Top + bottom margin (rem) — defaults to 1.5 to preserve the
    // longstanding `.bb-image` CSS spacing so existing posts keep
    // their familiar rhythm until the writer dials it. Same input
    // shape + sanitiser as the Section block's margin controls,
    // so the two read as siblings.
    if (typeof b.data.margin_top    !== 'number') b.data.margin_top    = 1.5;
    if (typeof b.data.margin_bottom !== 'number') b.data.margin_bottom = 1.5;
    function imageMarginInput(key, label) {
      const inp = el('input', {
        type: 'number', class: 'pbe-input pbe-section-margin-input',
        min: '0', max: '20', step: '0.25',
        'aria-label': label,
      });
      inp.value = String(b.data[key]);
      inp.addEventListener('input', e => {
        const n = parseFloat(e.target.value);
        if (!isFinite(n)) return;
        b.data[key] = Math.max(0, Math.min(20, n));
        commit();
      });
      return el('label', { class: 'pbe-mini-label pbe-section-margin-label' }, [
        label,
        el('span', { class: 'pbe-section-margin-row' }, [
          inp,
          el('span', { class: 'pbe-section-margin-unit muted smaller' }, ['rem']),
        ]),
      ]);
    }

    return el('div', { class: 'pbe-block-body pbe-image-body' }, [
      preview,
      el('div', { class: 'pbe-row pbe-image-row' }, [
        srcInput, hiddenFile, browseBtn, uploadBtn,
      ]),
      altInput,
      capInput,
      el('div', { class: 'pbe-row pbe-image-controls' }, [
        el('label', { class: 'pbe-mini-label' }, ['Align', alignGroup]),
        el('label', { class: 'pbe-mini-label pbe-range-label' }, [
          'Width', widthInput, widthValue,
        ]),
      ]),
      el('div', { class: 'pbe-row pbe-image-controls' }, [
        el('label', { class: 'pbe-mini-label' }, ['Shadow', shadowGroup]),
        imageMarginInput('margin_top', 'Top margin'),
        imageMarginInput('margin_bottom', 'Bottom margin'),
      ]),
    ]);
  }

  function uploadImage(file, onUrl) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('csrf_token', csrfToken());
    fetch('/tspro/files/upload', {
      method: 'POST', body: fd, credentials: 'same-origin',
    }).then(r => r.json()).then(data => {
      if (data && data.item && data.item.original_filename) {
        onUrl('/pub/' + data.item.original_filename);
      } else {
        alert('Upload failed — please try again.');
      }
    }).catch(err => {
      console.warn('upload failed', err);
      alert('Upload failed — please try again.');
    });
  }

  // ── Image library picker ─────────────────────────────────────────
  // Lazy-instantiated modal that lists every image already in the
  // site's media library via `/tspro/files/images.json`. Reuses the
  // `fe-image-picker-modal` / `be-image-picker-*` CSS classes from
  // the page builder's picker so the chrome is visually identical
  // without dragging in `block_editor.js`.
  //
  // The modal also lets the admin upload fresh images on the spot
  // (drop or click); the first newly-uploaded file is auto-selected
  // and the modal closes — same one-shot UX as the page builder.
  let _imgPicker = null;
  function ensureImagePicker() {
    if (_imgPicker) return _imgPicker;
    const modal = document.createElement('div');
    modal.className = 'modal fe-image-picker-modal pbe-image-picker';
    modal.setAttribute('aria-hidden', 'true');
    modal.innerHTML =
      '<div class="modal-backdrop" data-close></div>' +
      '<div class="modal-panel" role="dialog" aria-modal="true">' +
        '<div class="modal-head">' +
          '<h2>Image library</h2>' +
          '<input type="search" class="be-image-picker-search" ' +
            'placeholder="Search filenames…" autocomplete="off">' +
          '<button type="button" class="icon-btn" data-close ' +
            'aria-label="Close">×</button>' +
        '</div>' +
        '<div class="modal-body">' +
          '<div class="be-image-picker-uploader">' +
            '<label class="be-image-picker-drop">' +
              '<input type="file" accept="image/*" multiple>' +
              '<span class="be-image-picker-drop-label">' +
                '<b>Drop images here</b> or click to upload' +
              '</span>' +
            '</label>' +
            '<div class="be-image-picker-status muted small"></div>' +
          '</div>' +
          '<div class="be-image-picker-grid" data-grid></div>' +
          '<div class="be-image-picker-empty muted small" hidden>' +
            'No images yet. Upload one to get started.' +
          '</div>' +
        '</div>' +
      '</div>';
    document.body.appendChild(modal);

    const grid = modal.querySelector('[data-grid]');
    const empty = modal.querySelector('.be-image-picker-empty');
    const search = modal.querySelector('.be-image-picker-search');
    const status = modal.querySelector('.be-image-picker-status');
    const fileInput = modal.querySelector('input[type=file]');
    const drop = modal.querySelector('.be-image-picker-drop');

    let pendingPick = null;
    let allItems = [];

    function renderGrid(filter) {
      const q = (filter || '').toLowerCase();
      grid.innerHTML = '';
      const matches = q
        ? allItems.filter(it => (it.original_filename || '').toLowerCase().includes(q))
        : allItems;
      empty.hidden = matches.length > 0;
      matches.forEach(it => {
        const tile = document.createElement('button');
        tile.type = 'button';
        tile.className = 'be-image-picker-tile';
        tile.title = it.original_filename;
        // Inline thumb + filename. Same markup the page-builder's
        // picker emits so the shared CSS lines up tile-for-tile.
        tile.innerHTML =
          '<span class="be-image-picker-thumb">' +
            '<img src="' + (it.url || '') + '" alt="" loading="lazy">' +
          '</span>' +
          '<span class="be-image-picker-name">' +
            (it.original_filename || '').replace(/[<>"&]/g, '') +
          '</span>';
        tile.addEventListener('click', () => {
          // Hand the entire item dict back to the caller so a host
          // that needs the MediaItem id (e.g. the featured-image
          // picker) gets more than just the public URL.
          if (pendingPick) pendingPick(it);
          close();
        });
        grid.appendChild(tile);
      });
    }

    function reload() {
      status.textContent = 'Loading…';
      return fetch('/tspro/files/images.json', { credentials: 'same-origin' })
        .then(r => r.json())
        .then(data => {
          allItems = (data && data.items) || [];
          renderGrid(search.value);
          status.textContent = allItems.length + ' image' +
            (allItems.length === 1 ? '' : 's') + ' in library';
        })
        .catch(err => {
          status.textContent = 'Failed to load images';
          console.warn('image picker load failed', err);
        });
    }

    function uploadFiles(files) {
      const arr = Array.from(files || []);
      if (!arr.length) return;
      let done = 0;
      const total = arr.length;
      let firstUploaded = null;
      status.textContent = 'Uploading ' + total + ' file' + (total === 1 ? '' : 's') + '…';
      Promise.all(arr.map(file => {
        const fd = new FormData();
        fd.append('file', file);
        fd.append('csrf_token', csrfToken());
        return fetch('/tspro/files/upload', {
          method: 'POST', body: fd, credentials: 'same-origin',
        }).then(r => r.json()).then(data => {
          done++;
          if (data && data.item && !firstUploaded) firstUploaded = data.item;
          return data && data.item;
        }).catch(err => { console.warn('upload failed', err); return null; });
      })).then(() => {
        status.textContent = 'Uploaded ' + done + '/' + total;
        reload().then(() => {
          // Auto-select the first newly-uploaded file: the writer
          // dropped it INTO the picker, so they obviously meant
          // "pick this one". Saves a follow-up click on the grid.
          if (firstUploaded && pendingPick) {
            // Hand back a dict shaped like the list-grid items so
            // the callback sees the same payload either way.
            pendingPick({
              ...firstUploaded,
              url: '/pub/' + firstUploaded.original_filename,
            });
            close();
          }
        });
      });
    }

    fileInput.addEventListener('change', e => {
      uploadFiles(e.target.files);
      fileInput.value = '';
    });
    drop.addEventListener('dragover', e => {
      e.preventDefault();
      drop.classList.add('is-drop-target');
    });
    drop.addEventListener('dragleave', () => drop.classList.remove('is-drop-target'));
    drop.addEventListener('drop', e => {
      e.preventDefault();
      drop.classList.remove('is-drop-target');
      uploadFiles(e.dataTransfer.files);
    });

    let searchT = null;
    search.addEventListener('input', () => {
      clearTimeout(searchT);
      searchT = setTimeout(() => renderGrid(search.value), 100);
    });

    modal.querySelectorAll('[data-close]').forEach(elm =>
      elm.addEventListener('click', () => close()));
    // Esc closes the picker — only while it's open, so we don't
    // collide with the global "Esc closes the palette" handler.
    function onKey(e) {
      if (e.key === 'Escape' && modal.classList.contains('open')) {
        close();
      }
    }

    function open(cb) {
      pendingPick = cb || null;
      search.value = '';
      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      document.addEventListener('keydown', onKey);
      reload();
      setTimeout(() => search.focus(), 30);
    }
    function close() {
      pendingPick = null;
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
    }

    _imgPicker = { open, close };
    return _imgPicker;
  }
  function openImageBrowser(onPick) {
    ensureImagePicker().open(onPick);
  }
  // Expose the picker so adjacent template scripts (e.g. the
  // featured-image control in `blog_edit.html`) can reuse it
  // without re-implementing the modal. Callback receives the
  // full MediaItem dict: { id, stored_filename, original_filename,
  // mime_type, type, url }.
  window.pbeOpenImageBrowser = openImageBrowser;

  function renderButton(b) {
    const label = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'Button label (e.g. "Read the full guide")',
    });
    label.value = b.data.label || '';
    bindInput(label, v => b.data.label = v);

    const url = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'https://example.com  or  /relative/path',
    });
    url.value = b.data.url || '';
    bindInput(url, v => b.data.url = v);

    const styleGroup = renderSegmented(
      [['primary', 'Primary'], ['secondary', 'Secondary']],
      b.data.style || 'primary',
      v => { b.data.style = v; commit(); }
    );
    const alignGroup = renderSegmented(['left', 'center', 'right'],
      b.data.align || 'left', v => { b.data.align = v; commit(); });

    const newTab = el('label', { class: 'pbe-check' }, [
      (() => {
        const cb = el('input', { type: 'checkbox' });
        cb.checked = !!b.data.new_tab;
        cb.addEventListener('change', e => { b.data.new_tab = e.target.checked; commit(); });
        return cb;
      })(),
      el('span', {}, ['Open in new tab']),
    ]);

    return el('div', { class: 'pbe-block-body pbe-button-body' }, [
      label, url,
      el('div', { class: 'pbe-row pbe-button-controls' }, [
        el('label', { class: 'pbe-mini-label' }, ['Style', styleGroup]),
        el('label', { class: 'pbe-mini-label' }, ['Align', alignGroup]),
        newTab,
      ]),
    ]);
  }

  function renderList(b) {
    if (!Array.isArray(b.data.items)) b.data.items = [''];

    const orderedToggle = renderSegmented(
      [['false', 'Bulleted'], ['true', 'Numbered']],
      b.data.ordered ? 'true' : 'false',
      v => { b.data.ordered = (v === 'true'); commit(); rerenderItems(); }
    );

    const itemsList = el('ul', { class: 'pbe-list-items' });
    function rerenderItems() {
      itemsList.className = 'pbe-list-items' + (b.data.ordered ? ' is-ordered' : '');
      itemsList.innerHTML = '';
      b.data.items.forEach((item, idx) => {
        const input = el('input', {
          type: 'text', class: 'pbe-input pbe-list-item-input',
          placeholder: 'List item — Markdown OK',
        });
        input.value = item || '';
        input.addEventListener('input', e => { b.data.items[idx] = e.target.value; commit(); });
        // Enter at end of last item creates a fresh row; Backspace
        // on an empty item removes it (and focuses the previous).
        input.addEventListener('keydown', e => {
          if (e.key === 'Enter') {
            e.preventDefault();
            b.data.items.splice(idx + 1, 0, '');
            commit(); rerenderItems();
            const inputs = itemsList.querySelectorAll('.pbe-list-item-input');
            if (inputs[idx + 1]) inputs[idx + 1].focus();
          } else if (e.key === 'Backspace' && !input.value && b.data.items.length > 1) {
            e.preventDefault();
            b.data.items.splice(idx, 1);
            commit(); rerenderItems();
            const inputs = itemsList.querySelectorAll('.pbe-list-item-input');
            const focusIdx = Math.max(0, idx - 1);
            if (inputs[focusIdx]) {
              inputs[focusIdx].focus();
              const v = inputs[focusIdx].value;
              inputs[focusIdx].setSelectionRange(v.length, v.length);
            }
          }
        });
        const remove = el('button', {
          type: 'button', class: 'pbe-list-item-remove',
          title: 'Remove item', 'aria-label': 'Remove list item',
          onclick: () => {
            if (b.data.items.length <= 1) {
              b.data.items[0] = '';
              input.value = '';
            } else {
              b.data.items.splice(idx, 1);
            }
            commit(); rerenderItems();
          },
        });
        remove.innerHTML = svgIcon('x');
        itemsList.appendChild(el('li', { class: 'pbe-list-item' }, [input, remove]));
      });
    }
    rerenderItems();

    const addBtn = el('button', {
      type: 'button', class: 'btn btn-sm pbe-list-add',
      onclick: () => { b.data.items.push(''); commit(); rerenderItems(); },
    });
    addBtn.innerHTML = svgIcon('plus') + '<span>Add item</span>';

    return el('div', { class: 'pbe-block-body pbe-list-body' }, [
      el('div', { class: 'pbe-row' }, [
        el('label', { class: 'pbe-mini-label' }, ['Style', orderedToggle]),
      ]),
      itemsList,
      addBtn,
    ]);
  }

  function renderQuote(b) {
    const text = el('textarea', {
      class: 'pbe-input pbe-textarea',
      rows: 3,
      placeholder: 'The quoted text…',
    });
    text.value = b.data.text || '';
    autosize(text);
    bindInput(text, v => b.data.text = v);

    const author = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'Attribution — name or source (optional)',
    });
    author.value = b.data.author || '';
    bindInput(author, v => b.data.author = v);

    return el('div', { class: 'pbe-block-body pbe-quote-body' }, [text, author]);
  }

  function renderCallout(b) {
    const variantGroup = renderSegmented(
      [['info', 'Info'], ['success', 'Success'], ['warn', 'Warn'], ['danger', 'Danger']],
      b.data.variant || 'info',
      v => {
        b.data.variant = v; commit();
        // Re-color the host wrapper so the writer sees the variant
        // they're choosing without waiting on a full re-render.
        const wrap = variantGroup.closest('.pbe-block');
        if (wrap) {
          wrap.dataset.calloutVariant = v;
        }
      }
    );

    const title = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'Title (optional)',
    });
    title.value = b.data.title || '';
    bindInput(title, v => b.data.title = v);

    const body = el('textarea', {
      class: 'pbe-input pbe-textarea',
      rows: 3,
      placeholder: 'Note body — Markdown supported.',
    });
    body.value = b.data.md || '';
    autosize(body);
    bindInput(body, v => b.data.md = v);

    return el('div', { class: 'pbe-block-body pbe-callout-body' }, [
      el('div', { class: 'pbe-row' }, [
        el('label', { class: 'pbe-mini-label' }, ['Variant', variantGroup]),
      ]),
      title, body,
    ]);
  }

  function renderSeparator(b) {
    return el('div', { class: 'pbe-block-body pbe-separator-body' }, [
      el('div', { class: 'pbe-sep-preview' }, [el('hr')]),
      el('p', { class: 'pbe-mini-help muted' }, [
        'A simple horizontal rule. Drag to reorder; no settings.',
      ]),
    ]);
  }

  function renderVideo(b) {
    const url = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'YouTube / Vimeo URL or a self-hosted MP4 link',
    });
    url.value = b.data.url || '';
    bindInput(url, v => { b.data.url = v; repaintPreview(); });

    const caption = el('input', {
      type: 'text', class: 'pbe-input',
      placeholder: 'Caption (optional)',
    });
    caption.value = b.data.caption || '';
    bindInput(caption, v => b.data.caption = v);

    const preview = el('div', { class: 'pbe-video-preview' });
    function repaintPreview() {
      preview.innerHTML = '';
      const u = (b.data.url || '').trim();
      if (!u) {
        preview.appendChild(el('div', { class: 'pbe-image-empty' }, ['Paste a video URL above to preview.']));
        return;
      }
      const embed = videoEmbed(u);
      if (embed.kind === 'iframe') {
        preview.appendChild(el('iframe', {
          src: embed.url, allow: 'accelerometer; encrypted-media; picture-in-picture',
          allowfullscreen: '', loading: 'lazy',
        }));
      } else {
        const v = el('video', { controls: '', preload: 'metadata' }, []);
        v.appendChild(el('source', { src: u }));
        preview.appendChild(v);
      }
    }
    repaintPreview();

    return el('div', { class: 'pbe-block-body pbe-video-body' }, [
      preview, url, caption,
    ]);
  }

  function videoEmbed(u) {
    if (u.includes('youtube.com/watch')) {
      const id = u.split('v=')[1].split('&')[0];
      return { kind: 'iframe', url: 'https://www.youtube-nocookie.com/embed/' + id };
    }
    if (u.includes('youtu.be/')) {
      const id = u.split('youtu.be/')[1].split('?')[0];
      return { kind: 'iframe', url: 'https://www.youtube-nocookie.com/embed/' + id };
    }
    if (u.includes('vimeo.com/')) {
      const id = u.split('vimeo.com/')[1].split('?')[0].split('/')[0];
      return { kind: 'iframe', url: 'https://player.vimeo.com/video/' + id };
    }
    return { kind: 'video', url: u };
  }

  function renderCode(b) {
    const lang = el('input', {
      type: 'text', class: 'pbe-input pbe-code-lang',
      placeholder: 'Language (e.g. python, js, sql) — optional',
    });
    lang.value = b.data.lang || '';
    bindInput(lang, v => b.data.lang = v);

    const code = el('textarea', {
      class: 'pbe-input pbe-textarea pbe-code-input',
      rows: 6, spellcheck: 'false',
      placeholder: '// paste your code here',
    });
    code.value = b.data.code || '';
    autosize(code);
    bindInput(code, v => b.data.code = v);

    return el('div', { class: 'pbe-block-body pbe-code-body' }, [lang, code]);
  }

  function renderSection(b) {
    // Margin controls — top + bottom, in rem. Stored as numbers so
    // the sanitiser can clamp; the renderer slaps "rem" on it.
    if (typeof b.data.margin_top    !== 'number') b.data.margin_top    = 3;
    if (typeof b.data.margin_bottom !== 'number') b.data.margin_bottom = 3;

    function marginInput(key, label) {
      const inp = el('input', {
        type: 'number', class: 'pbe-input pbe-section-margin-input',
        min: '0', max: '20', step: '0.25',
        'aria-label': label,
      });
      inp.value = String(b.data[key]);
      inp.addEventListener('input', e => {
        const n = parseFloat(e.target.value);
        if (!isFinite(n)) return;
        b.data[key] = Math.max(0, Math.min(20, n));
        commit();
      });
      return el('label', { class: 'pbe-mini-label pbe-section-margin-label' }, [
        label,
        el('span', { class: 'pbe-section-margin-row' }, [
          inp,
          el('span', { class: 'pbe-section-margin-unit muted smaller' }, ['rem']),
        ]),
      ]);
    }

    const controls = el('div', { class: 'pbe-section-controls' }, [
      marginInput('margin_top', 'Top margin'),
      marginInput('margin_bottom', 'Bottom margin'),
    ]);

    const inner = renderSectionCanvas(b, b.data.blocks);

    return el('div', { class: 'pbe-block-body pbe-section-body' }, [
      controls,
      inner,
    ]);
  }

  const RENDERERS = {
    paragraph: renderParagraph,
    heading:   renderHeading,
    image:     renderImage,
    button:    renderButton,
    list:      renderList,
    quote:     renderQuote,
    callout:   renderCallout,
    separator: renderSeparator,
    video:     renderVideo,
    code:      renderCode,
    section:   renderSection,
  };

  // ── Shared widgets ───────────────────────────────────────────────

  // Segmented control. `options` accepts either ["a","b","c"] or
  // [["a","Label A"], ["b","Label B"]] so the value/label split is
  // explicit for things like style/variant pickers where the value
  // doesn't match the user-facing label.
  function renderSegmented(options, current, onChoose) {
    const wrap = el('div', { class: 'pbe-segmented', role: 'radiogroup' });
    options.forEach(opt => {
      const value = Array.isArray(opt) ? opt[0] : opt;
      const label = Array.isArray(opt) ? opt[1] : (opt.charAt(0).toUpperCase() + opt.slice(1));
      const btn = el('button', {
        type: 'button',
        class: 'pbe-segmented-btn' + (String(current) === String(value) ? ' is-active' : ''),
        'data-value': value, role: 'radio',
        'aria-checked': String(current) === String(value) ? 'true' : 'false',
        onclick: () => {
          wrap.querySelectorAll('.pbe-segmented-btn').forEach(b => {
            const active = b.dataset.value === value;
            b.classList.toggle('is-active', active);
            b.setAttribute('aria-checked', active ? 'true' : 'false');
          });
          onChoose(value);
        },
      }, [label]);
      wrap.appendChild(btn);
    });
    return wrap;
  }

  // Auto-grow a textarea as the user types. Set once on init, then
  // every input event resizes the host. Keeps the editor visually
  // tight — short paragraphs don't waste vertical real estate.
  function autosize(textarea) {
    function fit() {
      textarea.style.height = 'auto';
      textarea.style.height = Math.max(textarea.scrollHeight, 60) + 'px';
    }
    textarea.addEventListener('input', fit);
    // Defer one tick so the textarea has its computed style by the
    // time we measure scrollHeight (otherwise the first paint sets
    // an artificially small height on freshly-added blocks).
    setTimeout(fit, 0);
  }

  // ── Render ───────────────────────────────────────────────────────
  //
  // Block rendering threads a `host` array reference through every
  // call so mutations operate on the right list — top-level `blocks`
  // OR a section's `data.blocks`. Drag-and-drop uses a WeakMap keyed
  // by zone DOM element to look the host back up after a drop.
  //
  // The canvas-bound drag handlers are registered once on the
  // outer canvas and delegate to whichever `[data-pbe-zone]` the
  // event is happening inside — so adding a section spawns a fresh
  // working drop zone for free.

  // Zone → host array map. Rebuilt on every render() so stale
  // section refs from a previous tree don't survive.
  const zoneHostMap = new WeakMap();

  // Source-of-current-drag bookkeeping. The drag handle's dragstart
  // stamps this; drop reads it to splice the block out of the
  // correct host array regardless of where the user drops it.
  let _dragSource = null;

  function renderBlock(b, index, host) {
    const wrap = el('div', {
      class: 'pbe-block pbe-block--' + b.type,
      'data-block-id': b.id,
      'data-block-type': b.type,
      tabindex: '-1',
    });
    if (b.type === 'callout') wrap.dataset.calloutVariant = b.data.variant || 'info';

    // ── Chrome ─────────────────────────────────────────────────
    const handle = el('div', {
      class: 'pbe-block-handle',
      title: 'Drag to reorder',
      'aria-label': 'Drag to reorder',
      draggable: 'true',
    });
    handle.innerHTML = svgIcon('grip-vertical');
    handle.addEventListener('dragstart', e => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('application/x-pbe-move', b.id);
      try { e.dataTransfer.setDragImage(wrap, 20, 20); } catch (_) {}
      wrap.classList.add('is-dragging');
      document.body.classList.add('pbe-is-dragging');
      // Capture the source host so the drop handler knows which
      // array to splice the block out of — critical for moves
      // across zones (top-level ↔ section children).
      _dragSource = { id: b.id, host: host, type: b.type };
    });
    handle.addEventListener('dragend', () => {
      wrap.classList.remove('is-dragging');
      document.body.classList.remove('pbe-is-dragging');
      _dragSource = null;
      clearInsertMarkers();
    });

    const typeChip = el('span', { class: 'pbe-block-type-chip' }, [BLOCK_LABELS[b.type] || b.type]);

    const upBtn = el('button', {
      type: 'button', class: 'pbe-block-action',
      title: 'Move up', 'aria-label': 'Move block up',
      onclick: () => { if (index > 0) moveBlock(host, index, index - 1); },
    });
    upBtn.innerHTML = svgIcon('chevron-up');
    if (index === 0) upBtn.disabled = true;

    const downBtn = el('button', {
      type: 'button', class: 'pbe-block-action',
      title: 'Move down', 'aria-label': 'Move block down',
      onclick: () => { if (index < host.length - 1) moveBlock(host, index, index + 1); },
    });
    downBtn.innerHTML = svgIcon('chevron-down');
    if (index === host.length - 1) downBtn.disabled = true;

    const dupBtn = el('button', {
      type: 'button', class: 'pbe-block-action',
      title: 'Duplicate', 'aria-label': 'Duplicate block',
      onclick: () => duplicateBlock(host, index),
    });
    dupBtn.innerHTML = svgIcon('copy');

    const delBtn = el('button', {
      type: 'button', class: 'pbe-block-action pbe-block-action--danger',
      title: 'Delete', 'aria-label': 'Delete block',
      onclick: () => deleteBlock(host, index),
    });
    delBtn.innerHTML = svgIcon('trash-2');

    const toolbar = el('div', { class: 'pbe-block-toolbar' }, [
      typeChip, upBtn, downBtn, dupBtn, delBtn,
    ]);

    const body = (RENDERERS[b.type] || renderParagraph)(b);

    wrap.appendChild(handle);
    wrap.appendChild(toolbar);
    wrap.appendChild(body);
    return wrap;
  }

  function render() {
    // Wipe the outer canvas children but keep the empty-state placeholder.
    Array.from(canvas.querySelectorAll(':scope > .pbe-block, :scope > .pbe-insert-marker'))
      .forEach(n => n.remove());
    const empty = canvas.querySelector('[data-pbe-empty]');
    // Top-level canvas is itself a zone.
    canvas.dataset.pbeZone = 'root';
    zoneHostMap.set(canvas, blocks);
    if (blocks.length === 0) {
      if (empty) empty.style.display = '';
      commit();
      return;
    }
    if (empty) empty.style.display = 'none';
    blocks.forEach((b, i) => canvas.appendChild(renderBlock(b, i, blocks)));
    commit();
  }

  // Recursively render the blocks of a section into its own inner
  // canvas. Each call registers the inner canvas as a zone so the
  // outer drop handler routes inserts/moves to the right host.
  function renderSectionCanvas(b, host) {
    if (!Array.isArray(b.data.blocks)) b.data.blocks = [];
    const inner = el('div', {
      class: 'pbe-section-canvas',
      'data-pbe-zone': 'section',
    });
    zoneHostMap.set(inner, b.data.blocks);
    if (b.data.blocks.length === 0) {
      inner.appendChild(el('div', { class: 'pbe-section-empty' }, [
        'Empty section — drag blocks from the “Add block” palette here, or click a tile to drop one in.',
      ]));
    }
    b.data.blocks.forEach((child, i) => {
      inner.appendChild(renderBlock(child, i, b.data.blocks));
    });
    return inner;
  }

  // ── Mutation helpers ────────────────────────────────────────────
  // Every mutator takes `host` so the same logic services the
  // top-level blocks AND any section's children. `appendBlock`
  // still targets the top-level canvas — palette clicks land at
  // the end of the main body unless the writer drags onto a
  // section explicitly.
  function appendBlock(type) {
    const factory = BLOCK_DEFAULTS[type];
    if (!factory) return;
    blocks.push({ id: nextId(), type, data: factory() });
    render();
    setTimeout(() => {
      const last = canvas.querySelector(':scope > .pbe-block:last-of-type');
      if (last) {
        const inp = last.querySelector('input, textarea, select');
        if (inp) inp.focus();
        last.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 30);
  }

  function insertBlockAt(type, index, host) {
    const factory = BLOCK_DEFAULTS[type];
    if (!factory) return;
    // Sections aren't allowed inside other sections — sanitiser
    // strips them server-side, but blocking the drop here keeps
    // the editor honest.
    if (type === 'section' && !canHostSections(host)) return;
    const target = host || blocks;
    const idx = Math.max(0, Math.min(target.length, index));
    target.splice(idx, 0, { id: nextId(), type, data: factory() });
    render();
  }

  function moveBlock(host, from, to) {
    if (from === to || from < 0 || to < 0 || from >= host.length || to >= host.length) return;
    const [b] = host.splice(from, 1);
    host.splice(to, 0, b);
    render();
  }

  // Move a block from its source host (captured at dragstart) into a
  // target zone's host at the given index. Handles same-zone reorder
  // AND cross-zone moves (top-level ↔ section children). The index
  // is from the drop calc BEFORE the splice — so for same-zone moves
  // where the source sat above the target we have to compensate by
  // 1, otherwise the moved block bounces back to its original slot.
  function moveBlockToZone(id, targetHost, toIdx) {
    if (!_dragSource || _dragSource.id !== id) {
      // No captured source (rare — maybe the user manipulated
      // the DOM via dev tools). Fall back to a global search.
      const found = findBlockHost(id);
      if (!found) return;
      _dragSource = found;
    }
    const sourceHost = _dragSource.host;
    const sourceType = _dragSource.type;
    // Refuse cross-zone moves that would land a section inside
    // another section.
    if (sourceType === 'section' && !canHostSections(targetHost)) return;
    const from = sourceHost.indexOf(sourceHost.find(b => b.id === id));
    if (from < 0) return;
    let to = toIdx;
    if (sourceHost === targetHost && from < to) to -= 1;
    to = Math.max(0, Math.min(targetHost.length, to));
    const [block] = sourceHost.splice(from, 1);
    targetHost.splice(to, 0, block);
    render();
  }

  // Walk the entire tree looking for the block with the given id;
  // returns the host array + index, or null. Only invoked as a
  // safety net when `_dragSource` is missing.
  function findBlockHost(id) {
    function walk(arr) {
      for (let i = 0; i < arr.length; i++) {
        if (arr[i].id === id) return { id, host: arr, type: arr[i].type };
        if (arr[i].type === 'section' && Array.isArray(arr[i].data.blocks)) {
          const inner = walk(arr[i].data.blocks);
          if (inner) return inner;
        }
      }
      return null;
    }
    return walk(blocks);
  }

  function duplicateBlock(host, index) {
    const src = host[index];
    if (!src) return;
    const clone = assignIds(stripBlock(src));
    host.splice(index + 1, 0, clone);
    render();
  }

  function deleteBlock(host, index) {
    const src = host[index];
    if (!src) return;
    if (hasContent(src) && !confirm('Delete this ' + (BLOCK_LABELS[src.type] || 'block') + ' block?')) {
      return;
    }
    host.splice(index, 1);
    render();
  }

  function hasContent(b) {
    const d = b.data || {};
    switch (b.type) {
      case 'paragraph': return !!(d.md && d.md.trim());
      case 'heading':   return !!(d.text && d.text.trim());
      case 'image':     return !!(d.src && d.src.trim());
      case 'button':    return !!((d.label && d.label.trim()) || (d.url && d.url.trim()));
      case 'list':      return (d.items || []).some(it => it && it.trim());
      case 'quote':     return !!(d.text && d.text.trim());
      case 'callout':   return !!((d.title && d.title.trim()) || (d.md && d.md.trim()));
      case 'video':     return !!(d.url && d.url.trim());
      case 'code':      return !!(d.code && d.code.trim());
      case 'section':   return (d.blocks || []).length > 0;
      default:          return false;
    }
  }

  function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj || {}));
  }

  // ── Drag & drop ──────────────────────────────────────────────────
  // Listeners are bound to the outer canvas but delegate to whichever
  // `[data-pbe-zone]` the event is inside — so the same logic powers
  // drops onto the top-level body AND drops onto a section's inner
  // canvas. The closest-zone walk lets a section's canvas claim a
  // drop even though the listener lives on its ancestor.
  function zoneFromEvent(e) {
    const t = e.target;
    if (!t || !t.closest) return null;
    return t.closest('[data-pbe-zone]');
  }

  function indexFromYInZone(zone, clientY) {
    const children = Array.from(zone.querySelectorAll(':scope > .pbe-block'));
    for (let i = 0; i < children.length; i++) {
      const rect = children[i].getBoundingClientRect();
      if (clientY < rect.top + rect.height / 2) return i;
    }
    return children.length;
  }

  function showInsertMarkerIn(zone, index) {
    clearInsertMarkers();
    const marker = el('div', { class: 'pbe-insert-marker' });
    // Marker is `position: absolute` so the canvas DOESN'T reflow as
    // the cursor moves between insert positions during a drag — that
    // reflow was the source of the disorienting page-jump bug. We
    // compute the marker's `top` from neighbouring block offsets so
    // it still reads as "between block N-1 and block N".
    zone.appendChild(marker);
    const children = Array.from(zone.querySelectorAll(':scope > .pbe-block'));
    let top;
    if (children.length === 0) {
      top = 14; // canvas padding-top
    } else if (index <= 0) {
      // Above the first block.
      top = children[0].offsetTop - 8;
    } else if (index >= children.length) {
      // Below the last block.
      const last = children[children.length - 1];
      top = last.offsetTop + last.offsetHeight + 6;
    } else {
      // Centred in the gap between block[index-1] and block[index].
      const prev = children[index - 1];
      const next = children[index];
      const prevBottom = prev.offsetTop + prev.offsetHeight;
      top = (prevBottom + next.offsetTop) / 2 - 2;
    }
    marker.style.top = top + 'px';
  }

  function clearInsertMarkers() {
    canvas.querySelectorAll('.pbe-insert-marker').forEach(n => n.remove());
  }

  canvas.addEventListener('dragover', e => {
    const types = e.dataTransfer && e.dataTransfer.types;
    const hasNew = types && Array.from(types).includes('application/x-pbe-new');
    const hasMove = types && Array.from(types).includes('application/x-pbe-move');
    const isPaletteDrag = hasNew ||
      document.body.classList.contains('pbe-is-palette-dragging');
    const isMoveDrag = hasMove ||
      document.body.classList.contains('pbe-is-dragging');
    if (!isPaletteDrag && !isMoveDrag) return;
    const zone = zoneFromEvent(e);
    if (!zone) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = isPaletteDrag ? 'copy' : 'move';
    const idx = indexFromYInZone(zone, e.clientY);
    const key = (zone.dataset.pbeZone || '') + ':' + idx;
    if (canvas.dataset.dragKey !== key) {
      canvas.dataset.dragKey = key;
      showInsertMarkerIn(zone, idx);
    }
  });

  canvas.addEventListener('dragleave', e => {
    // Only clear markers when leaving the outer canvas itself —
    // child dragleave fires constantly during a drag and would
    // flicker the marker off.
    if (e.target === canvas) {
      clearInsertMarkers();
      delete canvas.dataset.dragKey;
    }
  });

  canvas.addEventListener('drop', e => {
    const zone = zoneFromEvent(e);
    if (!zone) return;
    e.preventDefault();
    const idx = indexFromYInZone(zone, e.clientY);
    clearInsertMarkers();
    delete canvas.dataset.dragKey;
    const targetHost = zoneHostMap.get(zone);
    if (!targetHost) return;
    const dt = e.dataTransfer;
    const newType = dt.getData('application/x-pbe-new');
    if (newType) {
      insertBlockAt(newType, idx, targetHost);
      return;
    }
    const moveId = dt.getData('application/x-pbe-move');
    if (moveId) {
      moveBlockToZone(moveId, targetHost, idx);
      return;
    }
  });

  // ── Palette tiles ────────────────────────────────────────────────
  // Each tile is draggable (drop onto canvas) AND clickable (append
  // to the end). The body class flag mirrors the data-transfer types
  // workaround above so the canvas dragover doesn't no-op when the
  // browser hides custom payload types.
  palette.querySelectorAll('[data-pbe-block-type]').forEach(tile => {
    const type = tile.dataset.pbeBlockType;
    tile.addEventListener('dragstart', e => {
      e.dataTransfer.effectAllowed = 'copy';
      e.dataTransfer.setData('application/x-pbe-new', type);
      tile.classList.add('is-dragging');
      document.body.classList.add('pbe-is-palette-dragging');
    });
    tile.addEventListener('dragend', () => {
      tile.classList.remove('is-dragging');
      document.body.classList.remove('pbe-is-palette-dragging');
      canvas.querySelectorAll('.pbe-insert-marker').forEach(n => n.remove());
    });
    tile.addEventListener('click', () => {
      appendBlock(type);
      // Keep the palette open after a click so the writer can drop
      // several blocks in a row without re-clicking the FAB.
    });
    tile.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        appendBlock(type);
      }
    });
  });

  // ── Palette open/close ──────────────────────────────────────────
  // Toggle handlers + click-outside-to-close + Esc-to-close. We
  // intentionally don't auto-close on tile click — see the comment
  // above — but click-outside dismiss is suppressed during a drag
  // so the panel doesn't yank shut mid-drop.
  function setPaletteOpen(open) {
    palette.classList.toggle('is-open', open);
    const fab = palette.querySelector('.fe-page-palette-fab');
    const panel = palette.querySelector('.fe-page-palette-panel');
    if (fab) fab.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (panel) panel.setAttribute('aria-hidden', open ? 'false' : 'true');
  }
  palette.querySelectorAll('[data-pbe-palette-toggle]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      setPaletteOpen(!palette.classList.contains('is-open'));
    });
  });
  document.addEventListener('click', e => {
    if (!palette.classList.contains('is-open')) return;
    if (palette.contains(e.target)) return;
    if (document.body.classList.contains('pbe-is-palette-dragging')) return;
    setPaletteOpen(false);
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && palette.classList.contains('is-open')) {
      setPaletteOpen(false);
    }
  });

  // ── Boot ────────────────────────────────────────────────────────
  // Pull the initial state off the hidden input. If the post has
  // legacy markdown in `body` but no blocks, we don't auto-migrate —
  // the old content stays as-is until the writer opts in by adding
  // a first block via the palette. This avoids a destructive
  // conversion of carefully-tuned Markdown.
  loadInitial();
  render();
})();
