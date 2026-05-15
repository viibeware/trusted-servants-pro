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
        blocks = parsed.map(b => ({
          id: nextId(),
          type: b.type,
          data: b.data || {},
        }));
      }
    } catch (err) {
      console.warn('post body editor: malformed JSON, starting empty', err);
    }
  }

  function commit() {
    const payload = blocks.map(b => ({ type: b.type, data: b.data }));
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
  };

  const BLOCK_LABELS = {
    paragraph: 'Paragraph', heading:   'Heading',  image: 'Image',
    button:    'Button',    list:      'List',     quote: 'Quote',
    callout:   'Callout',   separator: 'Divider',  video: 'Video',
    code:      'Code',
  };

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
    const preview = el('div', { class: 'pbe-image-preview' });
    function repaintPreview() {
      preview.innerHTML = '';
      if (b.data.src) {
        preview.appendChild(el('img', { src: b.data.src, alt: b.data.alt || '' }));
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

  function renderBlock(b, index) {
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
    // Drag handle is the only draggable surface — the textareas /
    // inputs inside the block need to keep their native drag
    // behaviour (text selection). Wire the drag events from the
    // handle but stamp the *whole block* as the drag image so the
    // visual feedback matches what the user is reordering.
    handle.addEventListener('dragstart', e => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('application/x-pbe-move', b.id);
      // Use a slight offset on the drag image so it doesn't cover
      // the cursor entirely while dragging.
      try {
        e.dataTransfer.setDragImage(wrap, 20, 20);
      } catch (_) {}
      wrap.classList.add('is-dragging');
      document.body.classList.add('pbe-is-dragging');
    });
    handle.addEventListener('dragend', () => {
      wrap.classList.remove('is-dragging');
      document.body.classList.remove('pbe-is-dragging');
      // Clear any insert markers left over from the drop calc.
      canvas.querySelectorAll('.pbe-insert-marker').forEach(n => n.remove());
    });

    const typeChip = el('span', { class: 'pbe-block-type-chip' }, [BLOCK_LABELS[b.type] || b.type]);

    const upBtn = el('button', {
      type: 'button', class: 'pbe-block-action',
      title: 'Move up', 'aria-label': 'Move block up',
      onclick: () => { if (index > 0) { moveBlock(index, index - 1); } },
    });
    upBtn.innerHTML = svgIcon('chevron-up');
    if (index === 0) upBtn.disabled = true;

    const downBtn = el('button', {
      type: 'button', class: 'pbe-block-action',
      title: 'Move down', 'aria-label': 'Move block down',
      onclick: () => { if (index < blocks.length - 1) { moveBlock(index, index + 1); } },
    });
    downBtn.innerHTML = svgIcon('chevron-down');
    if (index === blocks.length - 1) downBtn.disabled = true;

    const dupBtn = el('button', {
      type: 'button', class: 'pbe-block-action',
      title: 'Duplicate', 'aria-label': 'Duplicate block',
      onclick: () => duplicateBlock(index),
    });
    dupBtn.innerHTML = svgIcon('copy');

    const delBtn = el('button', {
      type: 'button', class: 'pbe-block-action pbe-block-action--danger',
      title: 'Delete', 'aria-label': 'Delete block',
      onclick: () => deleteBlock(index),
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
    canvas.querySelectorAll('.pbe-block, .pbe-insert-marker').forEach(n => n.remove());
    const empty = canvas.querySelector('[data-pbe-empty]');
    if (blocks.length === 0) {
      if (empty) empty.style.display = '';
      commit();
      return;
    }
    if (empty) empty.style.display = 'none';
    blocks.forEach((b, i) => canvas.appendChild(renderBlock(b, i)));
    commit();
  }

  // ── Mutation helpers ────────────────────────────────────────────
  function appendBlock(type) {
    const factory = BLOCK_DEFAULTS[type];
    if (!factory) return;
    blocks.push({ id: nextId(), type, data: factory() });
    render();
    // Focus the first input of the newly-added block so the writer
    // can start typing without a follow-up click.
    setTimeout(() => {
      const last = canvas.querySelector('.pbe-block:last-of-type');
      if (last) {
        const inp = last.querySelector('input, textarea, select');
        if (inp) inp.focus();
        last.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 30);
  }

  function insertBlockAt(type, index) {
    const factory = BLOCK_DEFAULTS[type];
    if (!factory) return;
    const idx = Math.max(0, Math.min(blocks.length, index));
    blocks.splice(idx, 0, { id: nextId(), type, data: factory() });
    render();
  }

  function moveBlock(from, to) {
    if (from === to || from < 0 || to < 0 || from >= blocks.length || to >= blocks.length) return;
    const [b] = blocks.splice(from, 1);
    blocks.splice(to, 0, b);
    render();
  }

  function moveBlockById(id, toIdx) {
    const from = blocks.findIndex(b => b.id === id);
    if (from < 0) return;
    // The drop calc gives us the index BEFORE the move; if the
    // moved block was already above the target, the splice shifts
    // it by one. Correct that here so dragging "to the slot just
    // below" doesn't bounce the block back to its original place.
    let to = toIdx;
    if (from < to) to -= 1;
    to = Math.max(0, Math.min(blocks.length - 1, to));
    moveBlock(from, to);
  }

  function duplicateBlock(index) {
    const src = blocks[index];
    if (!src) return;
    const clone = { id: nextId(), type: src.type, data: deepClone(src.data) };
    blocks.splice(index + 1, 0, clone);
    render();
  }

  function deleteBlock(index) {
    const src = blocks[index];
    if (!src) return;
    // Confirmation only when the block has user-typed content; empty
    // blocks vanish silently so the trash icon isn't a nuisance for
    // mid-compose cleanup.
    if (hasContent(src) && !confirm('Delete this ' + (BLOCK_LABELS[src.type] || 'block') + ' block?')) {
      return;
    }
    blocks.splice(index, 1);
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
      default:          return false;
    }
  }

  function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj || {}));
  }

  // ── Drag & drop on the canvas ────────────────────────────────────
  // The canvas is one big drop zone. We compute an insert index
  // based on the cursor's Y position relative to the children and
  // either insert a fresh block (palette → drop) or reorder an
  // existing one (handle → drop).
  function indexFromY(clientY) {
    const children = Array.from(canvas.querySelectorAll('.pbe-block'));
    for (let i = 0; i < children.length; i++) {
      const rect = children[i].getBoundingClientRect();
      if (clientY < rect.top + rect.height / 2) {
        return i;
      }
    }
    return children.length;
  }

  function showInsertMarker(index) {
    canvas.querySelectorAll('.pbe-insert-marker').forEach(n => n.remove());
    const marker = el('div', { class: 'pbe-insert-marker' });
    const children = Array.from(canvas.querySelectorAll('.pbe-block'));
    if (children.length === 0) {
      canvas.appendChild(marker);
      return;
    }
    if (index >= children.length) {
      children[children.length - 1].after(marker);
    } else {
      children[index].before(marker);
    }
  }

  canvas.addEventListener('dragover', e => {
    // Accept either a palette drag (new block) or a handle drag
    // (reorder). `dragover` runs many times per second; only
    // recompute the marker when the index changes.
    const types = e.dataTransfer && e.dataTransfer.types;
    const hasNew = types && Array.from(types).includes('application/x-pbe-new');
    const hasMove = types && Array.from(types).includes('application/x-pbe-move');
    // Body-class fallback: some browsers (Firefox in particular)
    // hide custom MIME types from the types list during dragover
    // until the actual drop. The class set on dragstart bridges
    // that gap so we still recognise our own drags.
    const isPaletteDrag = hasNew ||
      document.body.classList.contains('pbe-is-palette-dragging');
    const isMoveDrag = hasMove ||
      document.body.classList.contains('pbe-is-dragging');
    if (!isPaletteDrag && !isMoveDrag) return;
    e.preventDefault();
    // `dropEffect` MUST match the drag source's `effectAllowed` or
    // the browser rejects the drop and `drop` never fires. Palette
    // tiles allow 'copy' (a fresh block is created); the in-canvas
    // drag handle allows 'move' (reorder). Picking the right one
    // here lets both flows work without an "all" sledgehammer.
    e.dataTransfer.dropEffect = isPaletteDrag ? 'copy' : 'move';
    const idx = indexFromY(e.clientY);
    if (canvas.dataset.dragIndex !== String(idx)) {
      canvas.dataset.dragIndex = String(idx);
      showInsertMarker(idx);
    }
  });

  canvas.addEventListener('dragleave', e => {
    // Only clear markers when leaving the canvas itself; child
    // dragleave events fire constantly during a drag and would
    // otherwise flicker the marker off.
    if (e.target === canvas) {
      canvas.querySelectorAll('.pbe-insert-marker').forEach(n => n.remove());
      delete canvas.dataset.dragIndex;
    }
  });

  canvas.addEventListener('drop', e => {
    e.preventDefault();
    const idx = indexFromY(e.clientY);
    canvas.querySelectorAll('.pbe-insert-marker').forEach(n => n.remove());
    delete canvas.dataset.dragIndex;
    const dt = e.dataTransfer;
    const newType = dt.getData('application/x-pbe-new');
    if (newType) {
      insertBlockAt(newType, idx);
      return;
    }
    const moveId = dt.getData('application/x-pbe-move');
    if (moveId) {
      moveBlockById(moveId, idx);
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
