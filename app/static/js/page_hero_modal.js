// SPDX-License-Identifier: AGPL-3.0-or-later
/* Per-page hero edit modal — two-way binding between the modal's
   inputs (verbatim copy of the homepage hero modal markup) and the
   active Hero block's data inside the page-edit form's
   blocks_json hidden input.

   Flow:
     1. Admin clicks a Hero pill in the structure card. The pill
        carries `data-page-block-id` (the block's UUID) and
        `data-block-payload` (the block's current JSON).
     2. Existing `[data-open-modal]` handler opens
        `#page-hero-edit-modal`. Our `click` interceptor captures
        the block id, parses the payload, and writes every field
        into the matching `[data-hero-field]` input.
     3. Admin edits anything. Our `input`/`change` listener at the
        modal level reads every `[data-hero-field]`, rebuilds the
        block's data, walks the hidden input's blocks_json to
        replace the matching block, and writes back. Bubbling
        `input` event on the form/save-bar marks it dirty.

   Buttons + file uploads handled by their own helpers below.

   The IIFE body is wrapped in a DOMContentLoaded run-once because
   the page-edit template loads `page_hero_modal.js` BEFORE the
   `_page_hero_modal.html` include further down the document body,
   so an immediate `getElementById('page-hero-edit-modal')` returns
   null and the wiring silently bails. Deferring to DOMContentLoaded
   guarantees the modal element exists before we look it up.
*/
(function () {
  function init() {
    const modal = document.getElementById('page-hero-edit-modal');
    if (!modal) return;
    const hidden = document.getElementById('page-blocks-json');
    if (!hidden) return;
    const form = document.getElementById('page-edit-form');

    // ── Radio grouping fix ─────────────────────────────────────
    // The partial uses `data-hero-field` for our JS hook but
    // dropped the `name` attribute when copying the homepage's
    // markup. Without `name`, radios with the same data-hero-field
    // don't form a group → clicking Sinewave doesn't uncheck
    // Frosty, etc., so `:checked` queries return stale state and
    // the live preview never reflects the new selection. Stamp a
    // synthetic name on each radio to restore the grouping.
    modal.querySelectorAll('input[type="radio"][data-hero-field]').forEach(r => {
      if (!r.name) r.name = 'be-hero-' + r.dataset.heroField;
    });

    // ── Dynbg trigger field plumbing ───────────────────────────
    // The `dynbg_trigger` macro emits hidden inputs by NAME
    // (bg_dynamic_key + bg_dynbg_config_json__overlay / __c1 ..
    // __c3 / __scope / __noise_size / __noise_intensity /
    // __randomize_colors / __randomize_positions / __animate_off)
    // because the homepage-style admin save handler consumes them
    // by name. Per-block hero saves through blocks_json, so we
    // need to tag the key input with `data-hero-field` so readModal
    // picks it up, AND we need to fold the 9 config sub-inputs
    // into the single `bg_dynbg_config_json` string the public
    // renderer reads. The collection happens inside readDynbgFields
    // below; the dynbg picker already dispatches a bubbling
    // `change` event on the trigger inputs after Save, so our
    // document-level listener picks up the edit automatically.
    const dynKeyInp = modal.querySelector('input[name="bg_dynamic_key"]');
    if (dynKeyInp) dynKeyInp.setAttribute('data-hero-field', 'frontend_hero_bg_dynamic_key');

  // ── Active block tracking ─────────────────────────────────────
  let activeBlockId = null;
  // Per-block latest data, populated on every hero-modal edit.
  // The BlockEditor (in `#page-layout-edit-modal`) auto-mounts on
  // every pill click — even when the click opens OUR modal — and
  // its form-submit handler in `frontend_page_edit.html` writes
  // `editor.serialize()` over `hidden.value` right before submit.
  // For hero blocks that bypass the BlockEditor's UI entirely,
  // `editor.serialize()` returns stale data (the original
  // server-loaded values), wiping our edits. We track every hero
  // edit here and patch it back into `hidden.value` in a late-fire
  // submit listener (registered in init, runs after the inline
  // serializer because external scripts attach first / inline
  // scripts attach second).
  const heroEdits = new Map();   // blockId → latest data object

  // ── Field name mapping ────────────────────────────────────────
  // The modal's inputs carry `data-hero-field="<name>"` matching
  // the homepage's SiteSetting column names. Strip the
  // `frontend_hero_` / `frontend_tagline` prefix to land on the
  // block-data key. A handful of names don't follow the strip
  // pattern and live in the map below.
  const FIELD_OVERRIDES = {
    'frontend_tagline':         'eyebrow',
    'frontend_tagline_enabled': 'tagline_enabled',
    'heading':                  'heading',
    'subheading':               'subheading',
  };
  const SIZE_FIELDS = new Set([
    'frontend_hero_heading_size', 'frontend_hero_subheading_size',
  ]);
  const NUM_FIELDS = new Set([
    'frontend_hero_heading_size', 'frontend_hero_subheading_size',
    'frontend_hero_height_vh_desktop', 'frontend_hero_height_vh_mobile',
    'frontend_hero_bg_gradient_angle', 'frontend_hero_bg_image_scale',
    'frontend_hero_bg_hue', 'frontend_hero_bg_hue_2',
    'frontend_hero_bg_blur', 'frontend_hero_bg_opacity',
    'frontend_hero_bg_video_speed',
    'frontend_hero_particle_speed', 'frontend_hero_particle_size',
  ]);
  // Map from modal field name → block.data key.
  function blockKey(fieldName) {
    if (FIELD_OVERRIDES[fieldName]) return FIELD_OVERRIDES[fieldName];
    let k = fieldName;
    if (k.startsWith('frontend_hero_')) k = k.slice('frontend_hero_'.length);
    if (k.startsWith('frontend_')) k = k.slice('frontend_'.length);
    // Rename to match the block schema (which uses `_pct` suffix
    // for size %, no `frontend_` prefix, etc.).
    if (k === 'heading_size') return 'heading_size_pct';
    if (k === 'subheading_size') return 'subheading_size_pct';
    if (k === 'bg_image_filename') return 'bg_image_src';
    if (k === 'bg_video_filename') return 'bg_video_src';
    return k;
  }

  // ── Read all modal inputs into a block-data shape ─────────────
  function readModal() {
    const data = {};
    modal.querySelectorAll('[data-hero-field]').forEach(inp => {
      const name = inp.dataset.heroField;
      if (!name) return;
      const key = blockKey(name);
      if (inp.type === 'checkbox') {
        // Skip radio-like checkboxes; just plain on/off toggles here.
        data[key] = !!inp.checked;
      } else if (inp.type === 'radio') {
        if (inp.checked) data[key] = inp.value;
      } else if (inp.type === 'range' || inp.type === 'number'
                 || NUM_FIELDS.has(name)) {
        const n = parseInt(inp.value, 10);
        data[key] = isNaN(n) ? 0 : n;
      } else {
        data[key] = inp.value;
      }
    });
    // Dynbg config — combine the 9 hidden sub-inputs the picker
    // macro emits (`bg_dynbg_config_json__overlay` / `__c1..__c3` /
    // `__scope` / `__noise_size` / `__noise_intensity` /
    // `__randomize_colors` / `__randomize_positions` / `__animate_off`)
    // into the single JSON string the public renderer expects in
    // `bg_dynbg_config_json`. Mirrors `_dynbg_config_from_form` in
    // routes.py. Drops empty values so the JSON stays minimal.
    function _dyn(name) {
      const inp = modal.querySelector('input[name="bg_dynbg_config_json__' + name + '"]');
      return inp ? (inp.value || '').trim() : '';
    }
    const _dynCfg = {};
    const _dynOverlay = _dyn('overlay');
    if (_dynOverlay) _dynCfg.overlay = _dynOverlay;
    const _dynColors = [_dyn('c1'), _dyn('c2'), _dyn('c3')]
      .filter(c => /^#[0-9a-fA-F]{6}$/.test(c));
    if (_dynColors.length) _dynCfg.colors = _dynColors;
    const _dynScope = _dyn('scope');
    if (_dynScope && _dynScope !== 'all') _dynCfg.overlay_scope = _dynScope;
    const _dynNoiseSize = _dyn('noise_size');
    if (_dynNoiseSize) {
      const n = parseFloat(_dynNoiseSize);
      if (!isNaN(n)) _dynCfg.overlay_size = n;
    }
    const _dynNoiseInt = _dyn('noise_intensity');
    if (_dynNoiseInt) {
      const n = parseFloat(_dynNoiseInt);
      if (!isNaN(n)) _dynCfg.overlay_intensity = n;
    }
    if (_dyn('randomize_colors') === '1') _dynCfg.randomize_colors = true;
    if (_dyn('randomize_positions') === '1') _dynCfg.randomize_positions = true;
    if (_dyn('animate_off') === '1') _dynCfg.animate = false;
    if (_dyn('pastel_light') === '1') _dynCfg.pastel_light = true;
    // Per-preset knobs arrive as one JSON blob in the `__knobs` input.
    const _dynKnobs = _dyn('knobs');
    if (_dynKnobs) {
      try {
        const k = JSON.parse(_dynKnobs);
        if (k && typeof k === 'object' && Object.keys(k).length) _dynCfg.knobs = k;
      } catch (_) { /* malformed → ignore */ }
    }
    data.bg_dynbg_config_json = Object.keys(_dynCfg).length
      ? JSON.stringify(_dynCfg) : '';

    // Sinewave colours collapse 4 separate hex inputs into a single
    // array matching the block schema. Empty / invalid hexes are
    // dropped so the public renderer's fallback engages naturally.
    // The keys in `data` are `sinewave_c1`..`sinewave_c4` (blockKey
    // strips the `frontend_hero_` prefix from the input's
    // data-hero-field but leaves the rest of the name intact —
    // there's no `bg_` segment to strip). Earlier code looked for
    // `bg_sinewave_c1` and silently produced an empty array, which
    // made the public renderer skip its dynamic-text-lightness
    // computation for sinewave bgs (empty list is Python-falsy)
    // and fall back to `fe-hero-text-dark`, so the preview and the
    // frontend disagreed on heading colour. Match the actual key
    // names readModal produces.
    const sw = [];
    for (let i = 1; i <= 4; i++) {
      const k = 'sinewave_c' + i;
      const v = (data[k] || '').trim();
      delete data[k];
      if (/^#[0-9a-fA-F]{6}$/.test(v)) sw.push(v);
    }
    data.bg_sinewave_colors = sw;
    // Buttons live in their own JS-driven list; pull from the
    // current activeBlock if we have one — they don't ride
    // through [data-hero-field] inputs.
    const active = findActiveBlock();
    if (active) data.buttons = active.data.buttons || [];
    return data;
  }

  // ── Walk blocks_json + find / replace the active block ────────
  function readSections() {
    try { return JSON.parse(hidden.value || '[]') || []; }
    catch (_) { return []; }
  }
  function writeSections(sections) {
    hidden.value = JSON.stringify(sections);
    // Mirror the same triple-dispatch page_structure.js uses so the
    // save bar / form-level dirty trackers all light up.
    try { hidden.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
    if (form) {
      try { form.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
    }
    setTimeout(() => {
      const bar = document.getElementById('fe-save-bar');
      if (bar && bar.hasAttribute('hidden')) {
        bar.hidden = false;
        const m = bar.querySelector('.fe-save-bar-msg');
        if (m) m.textContent = 'Unsaved changes';
      }
    }, 50);
  }
  function walkBlocks(blocks, cb) {
    for (const b of (blocks || [])) {
      if (!b || typeof b !== 'object') continue;
      cb(b);
      if (b.type === 'container' && b.data && Array.isArray(b.data.blocks)) {
        walkBlocks(b.data.blocks, cb);
      }
    }
  }
  function findBlock(blockId) {
    const sections = readSections();
    let found = null;
    for (const sec of sections) {
      walkBlocks(sec.blocks || [], (b) => {
        if (!found && b.id === blockId) found = b;
      });
      if (found) break;
    }
    return found;
  }
  function findActiveBlock() {
    return activeBlockId ? findBlock(activeBlockId) : null;
  }
  // Mutate the hidden JSON in place — find the active block and
  // replace its `data` with the freshly-read modal values.
  function persistModalToBlock() {
    if (!activeBlockId) return;
    const modalData = readModal();
    // Record the latest edit so the submit-restore handler can
    // re-apply it even if the BlockEditor's submit serializer
    // overwrites `hidden.value` with stale state.
    heroEdits.set(activeBlockId, modalData);
    const sections = readSections();
    let touched = false;
    let touchedBlock = null;
    for (const sec of sections) {
      walkBlocks(sec.blocks || [], (b) => {
        if (b.id === activeBlockId) {
          b.data = Object.assign({}, b.data || {}, modalData);
          touched = true;
          touchedBlock = b;
        }
      });
    }
    if (touched) {
      writeSections(sections);
      // Mirror the new payload into the structure-card pill so a
      // later drag-drop (e.g. moving the hero out of a container)
      // doesn't rebuild sections from the stale pre-edit DOM
      // attribute and clobber the work.
      if (touchedBlock && typeof window.tspSyncStructurePayloadOne === 'function') {
        try { window.tspSyncStructurePayloadOne(activeBlockId, touchedBlock); }
        catch (_) {}
      }
    }
  }

  // ── Populate modal inputs from a block's data ─────────────────
  function populateModalFromBlock(block) {
    if (!block || !block.data) return;
    const data = block.data;
    modal.querySelectorAll('[data-hero-field]').forEach(inp => {
      const name = inp.dataset.heroField;
      if (!name) return;
      const key = blockKey(name);
      const v = data[key];
      if (inp.type === 'checkbox') {
        inp.checked = !!v;
      } else if (inp.type === 'radio') {
        inp.checked = (String(inp.value) === String(v));
      } else if (v != null) {
        inp.value = v;
      }
    });
    // Sinewave colours fan out from the array back into 4 inputs.
    const sw = Array.isArray(data.bg_sinewave_colors) ? data.bg_sinewave_colors : [];
    const swDefaults = ['#16c2ba', '#1883d5', '#5a1ce5', '#0a3eb5'];
    for (let i = 1; i <= 4; i++) {
      const inp = modal.querySelector('[data-hero-field="frontend_hero_sinewave_c' + i + '"]');
      if (inp) inp.value = sw[i - 1] || swDefaults[i - 1];
    }
    // Trigger the homepage's slider / panel / preview JS by
    // dispatching input/change events on each control so its
    // visible state (slider readouts, hidden bg-panels) reflects
    // the freshly-populated values.
    modal.querySelectorAll('[data-slider-input], [data-hero-height-input], [data-bg-style-radio]')
      .forEach(inp => {
        try { inp.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
        try { inp.dispatchEvent(new Event('change', { bubbles: true })); } catch (_) {}
      });
    // Buttons editor
    renderButtonsList(data.buttons || []);
    // Image / video previews
    syncImagePreview(data.bg_image_src || '');
    syncVideoPreview(data.bg_video_src || '');
    // Dynbg trigger — the partial server-renders the trigger ONCE
    // with the default proxy (empty key + config), so when the
    // admin opens a hero block that has a saved dynbg preset, the
    // trigger UI (button label, thumbnail, hidden inputs that the
    // picker modal reads on next open) still shows "Choose…" and
    // every config sub-field reads as empty. Reapply the saved
    // state through the picker's own update function so the
    // trigger reflects what's actually in the block.
    if (window.applyDynbgTrigger) {
      const dynTrigger = modal.querySelector('[data-dynbg-trigger]');
      if (dynTrigger) {
        let cfg = {};
        try { cfg = JSON.parse(data.bg_dynbg_config_json || '{}') || {}; }
        catch (_) { cfg = {}; }
        const colors = Array.isArray(cfg.colors) ? cfg.colors : [];
        window.applyDynbgTrigger(dynTrigger, {
          key: data.bg_dynamic_key || '',
          overlay: cfg.overlay || '',
          colors: [colors[0] || '', colors[1] || '', colors[2] || ''],
          scope: cfg.overlay_scope || '',
          noiseSize: cfg.overlay_size != null ? String(cfg.overlay_size) : '',
          noiseIntensity: cfg.overlay_intensity != null ? String(cfg.overlay_intensity) : '',
          randomizeColors: !!cfg.randomize_colors,
          randomizePositions: !!cfg.randomize_positions,
          animateOff: cfg.animate === false,
          pastelLight: !!cfg.pastel_light,
          knobs: (cfg.knobs && typeof cfg.knobs === 'object') ? cfg.knobs : {},
        });
      }
    }
    // Sync the live preview pane from the freshly-populated inputs.
    syncPreview();
  }

  // ── Preview synchronisation (ported from homepage heroFullPreview) ──
  // Reads CURRENT input values out of the modal and stamps them onto
  // the preview elements (#hero-preview-*). Called from
  // populateModalFromBlock (after inputs are set) AND on every
  // input/change event the admin makes, so the preview tracks edits
  // live without the admin needing to save first.
  const preview = {
    section: modal.querySelector('#hero-preview-section'),
    bg: modal.querySelector('#hero-preview-bg'),
    eyebrow: modal.querySelector('#hero-preview-eyebrow'),
    heading: modal.querySelector('#hero-preview-heading'),
    sub: modal.querySelector('#hero-preview-sub'),
    particles: modal.querySelector('#hero-preview-particles'),
    video: modal.querySelector('#hero-preview-video'),
    cta: modal.querySelector('#hero-preview-cta'),
  };
  function _val(name) {
    const inp = modal.querySelector('[data-hero-field="' + name + '"]');
    return inp ? inp.value : '';
  }
  function _checkedVal(name) {
    const inp = modal.querySelector('[data-hero-field="' + name + '"]:checked');
    return inp ? inp.value : '';
  }
  function _checkedBool(name) {
    const inp = modal.querySelector('[data-hero-field="' + name + '"]');
    return inp ? !!inp.checked : false;
  }
  function _hexLightness(h) {
    h = (h || '').replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
    const r = parseInt(h.slice(0, 2), 16) / 255;
    const g = parseInt(h.slice(2, 4), 16) / 255;
    const bv = parseInt(h.slice(4, 6), 16) / 255;
    return (Math.max(r, g, bv) + Math.min(r, g, bv)) / 2;
  }
  function _avgLightness(values) {
    const v = values.filter(x => x != null);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  }
  let _partFx = null;
  function _destroyPart() {
    if (_partFx) { try { _partFx.destroy(); } catch (_) {} _partFx = null; }
  }
  function _buildPart() {
    _destroyPart();
    if (!preview.particles || !window.initLoginFX) return;
    preview.particles.hidden = false;
    try {
      _partFx = window.initLoginFX(preview.particles, {
        effect: _val('frontend_hero_particle_effect') || 'stars',
        speed: parseInt(_val('frontend_hero_particle_speed'), 10) || 100,
        size: parseInt(_val('frontend_hero_particle_size'), 10) || 100,
      });
    } catch (_) { _partFx = null; }
  }

  function syncPreview() {
    try { _syncPreviewInner(); }
    catch (err) { console.warn('[page-hero-modal] syncPreview failed', err); }
  }
  function _syncPreviewInner() {
    if (!preview.section) return;
    // ── Text content ───────────────────────────────────────────
    const heading = _val('heading') || 'You are not alone.';
    const sub = _val('subheading') || 'Find meetings, connect with your community.';
    const eyebrowText = _val('frontend_tagline') || '';
    const eyebrowOn = _checkedBool('frontend_tagline_enabled');
    if (preview.heading) preview.heading.textContent = heading;
    if (preview.sub) preview.sub.textContent = sub;
    if (preview.eyebrow) {
      preview.eyebrow.textContent = eyebrowText;
      preview.eyebrow.hidden = !(eyebrowOn && eyebrowText.trim());
    }

    // ── Typography ─────────────────────────────────────────────
    const hFont = _checkedVal('frontend_hero_heading_font') || 'fraunces';
    const sFont = _checkedVal('frontend_hero_subheading_font') || 'inter';
    if (preview.heading) {
      preview.heading.classList.remove('fe-hero-heading-fraunces', 'fe-hero-heading-inter');
      preview.heading.classList.add('fe-hero-heading-' + hFont);
      const hSize = parseInt(_val('frontend_hero_heading_size'), 10) || 100;
      preview.heading.style.setProperty('--fe-hero-h-size', (hSize / 100).toString());
      preview.heading.style.setProperty('--fe-hero-h-grad-s', _val('frontend_hero_heading_grad_start') || '#0f172a');
      preview.heading.style.setProperty('--fe-hero-h-grad-e', _val('frontend_hero_heading_grad_end') || '#374151');
      // Dark-mode gradient — only visible in the preview when the admin
      // is editing under the dark theme. The rule still emits so a quick
      // theme toggle from elsewhere reflects the live colour without
      // re-opening the modal.
      const hGradSDark = _val('frontend_hero_heading_grad_start_dark');
      const hGradEDark = _val('frontend_hero_heading_grad_end_dark');
      if (hGradSDark) preview.heading.style.setProperty('--fe-hero-h-grad-s-dark', hGradSDark);
      else preview.heading.style.removeProperty('--fe-hero-h-grad-s-dark');
      if (hGradEDark) preview.heading.style.setProperty('--fe-hero-h-grad-e-dark', hGradEDark);
      else preview.heading.style.removeProperty('--fe-hero-h-grad-e-dark');
    }
    if (preview.sub) {
      preview.sub.classList.remove('fe-hero-sub-fraunces', 'fe-hero-sub-inter');
      preview.sub.classList.add('fe-hero-sub-' + sFont);
      const sSize = parseInt(_val('frontend_hero_subheading_size'), 10) || 100;
      preview.sub.style.setProperty('--fe-hero-sub-size', (sSize / 100).toString());
      const sColor = _val('frontend_hero_subheading_color');
      if (sColor) preview.sub.style.setProperty('--fe-hero-sub-color', sColor);
      else preview.sub.style.removeProperty('--fe-hero-sub-color');
      // Dark-mode sub colour — same flow as the heading gradient above.
      const sColorDark = _val('frontend_hero_subheading_color_dark');
      if (sColorDark) preview.sub.style.setProperty('--fe-hero-sub-color-dark', sColorDark);
      else preview.sub.style.removeProperty('--fe-hero-sub-color-dark');
    }

    // ── Background ─────────────────────────────────────────────
    const style = _checkedVal('frontend_hero_bg_style') || 'frosty';
    preview.section.classList.remove(
      'fe-hero-bg-frosty', 'fe-hero-bg-solid', 'fe-hero-bg-gradient',
      'fe-hero-bg-image', 'fe-hero-bg-sinewave', 'fe-hero-bg-video',
      'fe-hero-bg-dynamic');
    preview.section.classList.add('fe-hero-bg-' + style);
    preview.section.classList.toggle('fe-dynbg-host', style === 'dynamic');
    if (preview.bg) preview.bg.hidden = (style !== 'frosty');
    if (preview.video) preview.video.hidden = (style !== 'video');

    // Dynbg preview — clone the picker modal's card markup for the
    // active preset and inject it as the section's first child. The
    // picker's cards include the exact `<div class="fe-dynbg
    // fe-dynbg-<key>">…</div>` structure the public renderer emits
    // (via `frontend/_dynbg.html`), so the preset's CSS recipe
    // (animated blobs, conic gradients, etc.) paints automatically.
    // Saved palette colours land on `--fe-dynbg-c1/-c2/-c3`; random
    // positions stay at the preset's hand-tuned defaults for the
    // preview pane (the per-refresh randomisation only matters on
    // the public render and is impractical to mirror live in JS).
    (function applyDynbgPreview() {
      // Remove any existing injected dynbg from a prior sync.
      const stale = preview.section.querySelector(':scope > .fe-dynbg');
      if (stale) stale.remove();
      // Same for the overlay we may inject.
      const staleOverlay = preview.section.querySelector(':scope > .fe-dynbg-overlay');
      if (staleOverlay) staleOverlay.remove();
      if (style !== 'dynamic') return;
      const active = findActiveBlock();
      const blockData = (active && active.data) || {};
      const key = blockData.bg_dynamic_key || '';
      if (!key) return;
      const card = document.querySelector(
        '#dynbg-picker-modal [data-dynbg-modal-card][data-dynbg-key="' +
        CSS.escape(key) + '"]');
      if (!card) return;
      const cardDynbg = card.querySelector('.fe-dynbg-picker-thumb .fe-dynbg');
      if (!cardDynbg) return;
      const clone = cardDynbg.cloneNode(true);
      preview.section.insertBefore(clone, preview.section.firstChild);
      // Apply saved palette colours (when not randomised, or as a
      // representative seed when randomised — the user still sees a
      // realistic coloured preview, just not the exact per-refresh
      // shuffle).
      let cfg = {};
      try { cfg = JSON.parse(blockData.bg_dynbg_config_json || '{}') || {}; }
      catch (_) { cfg = {}; }
      const colors = Array.isArray(cfg.colors) ? cfg.colors : [];
      for (let i = 0; i < 3; i++) {
        if (colors[i]) {
          preview.section.style.setProperty('--fe-dynbg-c' + (i + 1), colors[i]);
        } else {
          preview.section.style.removeProperty('--fe-dynbg-c' + (i + 1));
        }
      }
      // Inject the overlay layer (noise-grain / scanlines / linen /
      // etc.) when the admin picked one. The overlay card holds the
      // exact markup the public renderer would emit.
      if (cfg.overlay) {
        const oCard = document.querySelector(
          '#dynbg-picker-modal [data-dynbg-modal-overlay-card][data-dynbg-overlay-key="' +
          CSS.escape(cfg.overlay) + '"]');
        if (oCard) {
          const oThumb = oCard.querySelector('.fe-dynbg-picker-thumb .fe-dynbg-overlay');
          if (oThumb) {
            const oClone = oThumb.cloneNode(true);
            preview.section.appendChild(oClone);
          }
        }
      }
    })();
    // Reset bg props before per-style application.
    preview.section.style.background = '';
    preview.section.style.backgroundImage = '';
    preview.section.style.backgroundSize = '';
    preview.section.style.backgroundRepeat = '';
    preview.section.style.backgroundColor = '';
    if (style === 'solid') {
      const c = _val('frontend_hero_bg_color');
      if (c) preview.section.style.background = c;
    } else if (style === 'gradient') {
      const g1 = _val('frontend_hero_bg_color') || '#ffffff';
      const g2 = _val('frontend_hero_bg_color_2') || '#e0e7ff';
      const ang = parseInt(_val('frontend_hero_bg_gradient_angle'), 10) || 180;
      preview.section.style.background = 'linear-gradient(' + ang + 'deg, ' + g1 + ', ' + g2 + ')';
    } else if (style === 'image') {
      const active = findActiveBlock();
      const src = (active && active.data && active.data.bg_image_src) || '';
      if (src) {
        const mode = _checkedVal('frontend_hero_bg_image_mode') || 'cover';
        if (mode === 'tile') {
          const sc = parseInt(_val('frontend_hero_bg_image_scale'), 10) || 100;
          preview.section.style.background = 'url("' + src + '") repeat';
          preview.section.style.backgroundSize = sc + 'px ' + sc + 'px';
        } else {
          preview.section.style.background = 'url("' + src + '") center/cover no-repeat';
        }
      }
    } else if (style === 'sinewave' && window.loginFxUtils) {
      const palette = [];
      for (let i = 1; i <= 4; i++) {
        const v = _val('frontend_hero_sinewave_c' + i);
        if (/^#[0-9a-fA-F]{6}$/.test((v || '').trim())) palette.push(v);
      }
      if (palette.length) {
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const adj = window.loginFxUtils.adjustPaletteForTheme(palette, isDark);
        window.loginFxUtils.applyBackground(preview.section, adj);
      }
    } else if (style === 'video' && preview.video) {
      const active = findActiveBlock();
      const src = (active && active.data && active.data.bg_video_src) || '';
      const cur = preview.video.querySelector('source');
      if (src) {
        if (!cur || cur.getAttribute('src') !== src) {
          preview.video.innerHTML = '<source src="' + src + '">';
          try { preview.video.load(); } catch (_) {}
        }
        const spd = parseInt(_val('frontend_hero_bg_video_speed'), 10) || 100;
        try { preview.video.playbackRate = spd / 100; } catch (_) {}
        preview.video.play().catch(() => {});
      }
    }

    // ── Frosty blob CSS vars ──────────────────────────────────
    if (style === 'frosty' && preview.bg) {
      preview.bg.style.setProperty('--fe-blob-hue-a', _val('frontend_hero_bg_hue') || '225');
      preview.bg.style.setProperty('--fe-blob-hue-b', _val('frontend_hero_bg_hue_2') || '170');
      preview.bg.style.setProperty('--fe-blob-blur', (_val('frontend_hero_bg_blur') || '80') + 'px');
      const op = parseInt(_val('frontend_hero_bg_opacity'), 10) || 45;
      preview.bg.style.setProperty('--fe-blob-op', (op / 100).toString());
    }

    // ── Dynamic-text contrast ─────────────────────────────────
    preview.section.classList.remove('fe-hero-text-light', 'fe-hero-text-dark');
    if (_checkedBool('frontend_hero_text_dynamic')) {
      let l = 0.95;
      if (style === 'solid') {
        l = _hexLightness(_val('frontend_hero_bg_color')) ?? 0.95;
      } else if (style === 'gradient') {
        l = _avgLightness([_hexLightness(_val('frontend_hero_bg_color')),
                          _hexLightness(_val('frontend_hero_bg_color_2'))]) ?? 0.95;
      } else if (style === 'sinewave') {
        const cs = [];
        for (let i = 1; i <= 4; i++) cs.push(_hexLightness(_val('frontend_hero_sinewave_c' + i)));
        l = _avgLightness(cs) ?? 0.55;
      }
      preview.section.classList.add(l < 0.55 ? 'fe-hero-text-light' : 'fe-hero-text-dark');
    }

    // ── CTA buttons ───────────────────────────────────────────
    // Mirror the public renderer's button markup so the preview is
    // a faithful representation of what `hero_block.html` will emit
    // when the page saves. Reads from the live block data (which
    // the right-column editor mutates in place via
    // updateActiveButtons) so add / remove / reorder updates show
    // immediately. Empty array → no buttons rendered in the
    // preview, matching what the public render would do.
    if (preview.cta) {
      preview.cta.innerHTML = '';
      const activeBlock = findActiveBlock();
      const buttons = (activeBlock && activeBlock.data && activeBlock.data.buttons) || [];
      buttons.forEach(btn => {
        const bstyle = (btn.style === 'ghost' || btn.style === 'yellow')
          ? btn.style : 'primary';
        const a = document.createElement('a');
        a.className = 'fe-btn fe-btn-' + bstyle;
        const vars = [];
        if (bstyle === 'primary') {
          if (btn.custom_bg_color) vars.push('--fe-btn-bg: ' + btn.custom_bg_color);
          if (btn.custom_text_color) vars.push('--fe-btn-text: ' + btn.custom_text_color);
        }
        if (vars.length) a.setAttribute('style', vars.join('; ') + ';');
        if (btn.icon_before) {
          const span = document.createElement('span');
          span.className = 'fe-btn-icon';
          // Icons are server-side; in the preview we just render the
          // ref name as small uppercase text so the admin can see
          // where it'll sit without inflating the JS bundle with a
          // Lucide catalog.
          span.textContent = '[' + btn.icon_before + ']';
          a.appendChild(span);
        }
        const label = document.createElement('span');
        label.textContent = btn.label || '';
        a.appendChild(label);
        if (btn.icon_after) {
          const span = document.createElement('span');
          span.className = 'fe-btn-icon';
          span.textContent = '[' + btn.icon_after + ']';
          a.appendChild(span);
        }
        preview.cta.appendChild(a);
      });
    }

    // ── Particle overlay ──────────────────────────────────────
    if (_checkedBool('frontend_hero_particle_enabled')) {
      const effect = _val('frontend_hero_particle_effect') || 'stars';
      if (!_partFx || _partFx._effect !== effect) {
        _buildPart();
        if (_partFx) _partFx._effect = effect;
      } else {
        const spd = parseInt(_val('frontend_hero_particle_speed'), 10) || 100;
        const sz = parseInt(_val('frontend_hero_particle_size'), 10) || 100;
        try { _partFx.setSpeed(spd); } catch (_) {}
        try { _partFx.setSize(sz); } catch (_) {}
      }
    } else {
      _destroyPart();
      if (preview.particles) preview.particles.hidden = true;
    }
  }

  // ── Buttons list editor ──────────────────────────────────────
  const buttonsList = modal.querySelector('#hero-buttons-list');
  function renderButtonsList(buttons) {
    if (!buttonsList) return;
    buttonsList.innerHTML = '';
    if (!buttons.length) {
      const empty = document.createElement('p');
      empty.className = 'be-hero-buttons-empty muted smaller';
      empty.textContent = 'No buttons yet — click "+ Add button" above.';
      buttonsList.appendChild(empty);
      return;
    }
    (buttons || []).forEach((btn, idx) => {
      const row = document.createElement('div');
      row.className = 'be-hero-button-row';

      // ── Row header: index chip + reorder + remove ──────────
      const head = document.createElement('div');
      head.className = 'be-hero-button-head';
      const idx_chip = document.createElement('span');
      idx_chip.className = 'be-hero-button-idx';
      idx_chip.textContent = String(idx + 1);
      const label_chip = document.createElement('span');
      label_chip.className = 'be-hero-button-name';
      label_chip.textContent = btn.label || '(unnamed)';
      label_chip.dataset.role = 'name';   // updated live on label-input
      head.appendChild(idx_chip);
      head.appendChild(label_chip);
      const head_actions = document.createElement('div');
      head_actions.className = 'be-hero-button-head-actions';
      const up = document.createElement('button');
      up.type = 'button'; up.className = 'icon-btn'; up.title = 'Move up';
      up.innerHTML = '↑';
      up.onclick = () => {
        if (idx > 0) {
          const t = buttons[idx]; buttons[idx] = buttons[idx - 1]; buttons[idx - 1] = t;
          updateActiveButtons(buttons);
        }
      };
      const down = document.createElement('button');
      down.type = 'button'; down.className = 'icon-btn'; down.title = 'Move down';
      down.innerHTML = '↓';
      down.onclick = () => {
        if (idx < buttons.length - 1) {
          const t = buttons[idx]; buttons[idx] = buttons[idx + 1]; buttons[idx + 1] = t;
          updateActiveButtons(buttons);
        }
      };
      const rm = document.createElement('button');
      rm.type = 'button'; rm.className = 'icon-btn be-hero-button-remove';
      rm.title = 'Remove this button';
      rm.innerHTML = '×';
      rm.onclick = () => {
        buttons.splice(idx, 1);
        updateActiveButtons(buttons);
      };
      head_actions.appendChild(up);
      head_actions.appendChild(down);
      head_actions.appendChild(rm);
      head.appendChild(head_actions);
      row.appendChild(head);

      // ── Field helpers ──────────────────────────────────────
      // `persistButtons` writes to blocks_json + refreshes the
      // preview WITHOUT re-rendering this list, so the input keeps
      // its focus + cursor position between keystrokes.
      function textField(key, lblText, ph, type) {
        const wrap = document.createElement('label');
        wrap.className = 'be-hero-button-field';
        const span = document.createElement('span');
        span.className = 'be-hero-button-field-lbl';
        span.textContent = lblText;
        const inp = document.createElement('input');
        inp.type = type || 'text';
        inp.value = btn[key] != null ? String(btn[key]) : '';
        inp.placeholder = ph || '';
        inp.oninput = () => {
          btn[key] = inp.value;
          // Live-update the row's header chip when editing the
          // button's label so the admin sees the name change
          // without the row losing focus.
          if (key === 'label') label_chip.textContent = inp.value || '(unnamed)';
          persistButtons(buttons);
        };
        wrap.appendChild(span);
        wrap.appendChild(inp);
        return wrap;
      }
      function selectField(key, lblText, options) {
        const wrap = document.createElement('label');
        wrap.className = 'be-hero-button-field';
        const span = document.createElement('span');
        span.className = 'be-hero-button-field-lbl';
        span.textContent = lblText;
        const sel = document.createElement('select');
        options.forEach(([v, l]) => {
          const o = document.createElement('option');
          o.value = v; o.textContent = l;
          if ((btn[key] || options[0][0]) === v) o.selected = true;
          sel.appendChild(o);
        });
        sel.onchange = () => {
          btn[key] = sel.value;
          persistButtons(buttons);
        };
        wrap.appendChild(span);
        wrap.appendChild(sel);
        return wrap;
      }
      function toggleField(key, lblText) {
        const wrap = document.createElement('label');
        wrap.className = 'be-hero-button-toggle';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!btn[key];
        cb.onchange = () => {
          btn[key] = cb.checked;
          persistButtons(buttons);
        };
        const span = document.createElement('span');
        span.textContent = lblText;
        wrap.appendChild(cb);
        wrap.appendChild(span);
        return wrap;
      }
      // Icon-picker trigger + hidden input + clear, styled like the
      // features-card icon trigger. The shared icon picker is a global
      // delegated handler (see app.js), wired via [data-open-icon-picker]
      // with `data-icon-target` pointing at the hidden input we mint
      // here. We listen for `input` on the hidden input — that's the
      // event the picker dispatches after writing — and use it to
      // update btn[key] + persist + repaint the preview.
      function iconField(key, lblText) {
        const wrap = document.createElement('div');
        wrap.className = 'be-hero-button-field be-hero-button-icon-field';
        wrap.dataset.iconField = '';
        if (btn[key]) wrap.classList.add('has-icon');
        const lbl = document.createElement('span');
        lbl.className = 'be-hero-button-field-lbl';
        lbl.textContent = lblText;
        wrap.appendChild(lbl);
        const row2 = document.createElement('div');
        row2.className = 'be-hero-button-icon-row';
        // Unique id so the picker's `data-icon-target` selector can
        // find the right hidden input when the trigger is clicked.
        const hiddenId = 'hero-btn-' + key + '-' + idx + '-' +
                          Math.floor(Math.random() * 1e9).toString(36);
        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.className = 'icon-picker-trigger be-hero-button-icon-trigger';
        trigger.setAttribute('data-open-icon-picker', '');
        trigger.setAttribute('data-icon-target', '#' + hiddenId);
        trigger.title = 'Choose icon';
        const preview = document.createElement('span');
        preview.className = 'icon-picker-preview';
        preview.setAttribute('data-icon-preview', '');
        if (btn[key] && window.tspRenderIconHtml) {
          preview.innerHTML = window.tspRenderIconHtml(btn[key]);
        }
        const empty = document.createElement('span');
        empty.className = 'icon-picker-trigger-empty';
        empty.setAttribute('data-icon-empty', '');
        empty.textContent = 'Choose…';
        trigger.appendChild(preview);
        trigger.appendChild(empty);
        const hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.id = hiddenId;
        hidden.value = btn[key] || '';
        hidden.setAttribute('data-icon-input', '');
        hidden.addEventListener('input', () => {
          btn[key] = hidden.value;
          if (hidden.value) {
            wrap.classList.add('has-icon');
            if (window.tspRenderIconHtml) {
              preview.innerHTML = window.tspRenderIconHtml(hidden.value);
            }
          } else {
            wrap.classList.remove('has-icon');
            preview.innerHTML = '';
          }
          persistButtons(buttons);
        });
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'icon-picker-clear be-hero-button-icon-clear';
        clear.setAttribute('data-icon-clear', '');
        clear.title = 'Clear icon';
        clear.innerHTML = '×';
        row2.appendChild(trigger);
        row2.appendChild(hidden);
        row2.appendChild(clear);
        wrap.appendChild(row2);
        return wrap;
      }
      // Colour cluster: native swatch + editable hex text input + the
      // auto-attached 🎨 token-palette button + read-only hex caption +
      // matched-token chip (the latter three come for free from the
      // global `_design_token_picker.html` MutationObserver — every
      // <input type="color"> in the DOM gets the chrome injected). Hex
      // text input ↔ swatch are two-way bound; persisting writes the
      // hex string into btn[key] on every input.
      function colorField(key, lblText, ph) {
        const wrap = document.createElement('div');
        wrap.className = 'be-hero-button-field be-hero-button-color-field';
        const lbl = document.createElement('span');
        lbl.className = 'be-hero-button-field-lbl';
        lbl.textContent = lblText;
        wrap.appendChild(lbl);
        const cluster = document.createElement('div');
        cluster.className = 'be-hero-button-color-cluster';
        const initial = btn[key] || '';
        const hex = document.createElement('input');
        hex.type = 'text';
        hex.className = 'be-hero-button-color-text';
        hex.value = initial;
        hex.placeholder = ph || '#000000';
        hex.maxLength = 9;
        hex.spellcheck = false;
        hex.autocomplete = 'off';
        const swatch = document.createElement('input');
        swatch.type = 'color';
        swatch.className = 'be-hero-button-color-swatch';
        // Native swatch needs a 6-digit hex; fall back to a sensible
        // default colour when btn[key] is empty so the dialog still
        // opens on a visible value.
        const HEX_RE = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
        function expand(v) {
          if (v && v.length === 4 && v[0] === '#') {
            return '#' + v[1] + v[1] + v[2] + v[2] + v[3] + v[3];
          }
          return v;
        }
        swatch.value = HEX_RE.test(initial) ? expand(initial).slice(0, 7) : '#000000';
        swatch.addEventListener('input', () => {
          hex.value = swatch.value;
          btn[key] = swatch.value;
          persistButtons(buttons);
        });
        hex.addEventListener('input', () => {
          let v = (hex.value || '').trim();
          if (!v) {
            btn[key] = '';
            persistButtons(buttons);
            return;
          }
          if (v[0] !== '#') v = '#' + v;
          if (HEX_RE.test(v)) {
            swatch.value = expand(v).slice(0, 7);
            btn[key] = v;
            persistButtons(buttons);
          }
          // Invalid hex → don't commit; admin can keep typing.
        });
        cluster.appendChild(hex);
        cluster.appendChild(swatch);
        wrap.appendChild(cluster);
        return wrap;
      }

      // ── Main grid: Label + URL side by side ─────────────────
      const main = document.createElement('div');
      main.className = 'be-hero-button-grid';
      main.appendChild(textField('label', 'Label', 'Find a Meeting'));
      main.appendChild(textField('url', 'URL', '/meetings or https://…'));
      row.appendChild(main);

      // ── Style + new-tab toggle row ─────────────────────────
      const opts = document.createElement('div');
      opts.className = 'be-hero-button-grid be-hero-button-grid--opts';
      opts.appendChild(selectField('style', 'Style', [
        ['primary', 'Primary (filled)'],
        ['ghost',   'Ghost (outline)'],
        ['yellow',  'Yellow (high-contrast)'],
      ]));
      opts.appendChild(toggleField('open_in_new_tab', 'Open in new tab'));
      row.appendChild(opts);

      // ── Advanced (collapsed): icons + custom colours ────────
      const adv = document.createElement('details');
      adv.className = 'be-hero-button-advanced';
      const sum = document.createElement('summary');
      sum.className = 'muted smaller';
      sum.textContent = 'Advanced — icons + custom colours';
      adv.appendChild(sum);
      const advGrid = document.createElement('div');
      advGrid.className = 'be-hero-button-grid';
      advGrid.appendChild(iconField('icon_before', 'Icon before'));
      advGrid.appendChild(colorField('icon_before_color', 'Before-icon colour', '#ffffff'));
      advGrid.appendChild(textField('icon_before_size', 'Before-icon size (px)', '20', 'number'));
      advGrid.appendChild(iconField('icon_after', 'Icon after'));
      advGrid.appendChild(colorField('icon_after_color', 'After-icon colour', '#ffffff'));
      advGrid.appendChild(textField('icon_after_size', 'After-icon size (px)', '20', 'number'));
      advGrid.appendChild(colorField('custom_bg_color', 'Background (primary only)', '#1d4ed8'));
      advGrid.appendChild(colorField('custom_text_color', 'Text colour (primary only)', '#ffffff'));
      adv.appendChild(advGrid);
      row.appendChild(adv);

      buttonsList.appendChild(row);
    });
  }
  // Persist + preview without rebuilding the editor list. Used by
  // text / URL / select / toggle field handlers — typing into a
  // text input MUST NOT re-render the row, otherwise the input
  // (and its DOM focus) gets destroyed between keystrokes and the
  // admin can only type one character at a time before being
  // booted out of the field.
  function persistButtons(buttons) {
    if (!activeBlockId) return;
    const prior = heroEdits.get(activeBlockId) || {};
    prior.buttons = buttons;
    heroEdits.set(activeBlockId, prior);
    const sections = readSections();
    let touched = false;
    for (const sec of sections) {
      walkBlocks(sec.blocks || [], (b) => {
        if (b.id === activeBlockId) {
          b.data = b.data || {};
          b.data.buttons = buttons;
          touched = true;
        }
      });
    }
    if (touched) writeSections(sections);
    syncPreview();
  }
  // Structural changes (add / remove / reorder) — persist AND
  // rebuild the editor list so the order + count match the data.
  function updateActiveButtons(buttons) {
    persistButtons(buttons);
    renderButtonsList(buttons);
  }
  const addBtn = modal.querySelector('#hero-button-add');
  if (addBtn) addBtn.addEventListener('click', () => {
    const active = findActiveBlock();
    if (!active) return;
    active.data = active.data || {};
    if (!Array.isArray(active.data.buttons)) active.data.buttons = [];
    active.data.buttons.push({
      id: Math.random().toString(36).slice(2, 10),
      label: 'Click here', url: '', style: 'primary', open_in_new_tab: false,
    });
    updateActiveButtons(active.data.buttons);
  });

  // ── Image + video upload ─────────────────────────────────────
  function csrfToken() {
    const inp = document.querySelector('input[name="csrf_token"]');
    return inp ? inp.value : '';
  }
  function syncImagePreview(url) {
    const wrap = modal.querySelector('#hero-image-preview');
    const img = modal.querySelector('#hero-image-preview-img');
    if (!wrap || !img) return;
    if (url) { img.src = url; wrap.hidden = false; }
    else { img.src = ''; wrap.hidden = true; }
  }
  function syncVideoPreview(url) {
    const wrap = modal.querySelector('#hero-video-preview');
    const vid = modal.querySelector('#hero-video-preview-video');
    if (!wrap || !vid) return;
    if (url) { vid.src = url; wrap.hidden = false; }
    else { vid.src = ''; wrap.hidden = true; }
  }
  function setActiveField(key, value) {
    const active = findActiveBlock();
    if (!active) return;
    const sections = readSections();
    let touched = false;
    for (const sec of sections) {
      walkBlocks(sec.blocks || [], (b) => {
        if (b.id === activeBlockId) {
          b.data = b.data || {};
          b.data[key] = value;
          touched = true;
        }
      });
    }
    if (touched) writeSections(sections);
  }
  const imgUpload = modal.querySelector('#hero-image-upload');
  if (imgUpload) imgUpload.addEventListener('change', () => {
    const f = imgUpload.files && imgUpload.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f);
    fd.append('csrf_token', csrfToken());
    fetch('/tspro/files/upload', { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(r => r.json()).then(data => {
        if (data && data.item && data.item.original_filename) {
          const url = '/pub/' + data.item.original_filename;
          setActiveField('bg_image_src', url);
          syncImagePreview(url);
        }
      }).catch(err => console.warn('hero bg upload failed', err));
  });
  const imgClear = modal.querySelector('#hero-image-clear');
  if (imgClear) imgClear.addEventListener('click', () => {
    setActiveField('bg_image_src', '');
    syncImagePreview('');
  });
  const vidUpload = modal.querySelector('#hero-video-upload');
  if (vidUpload) vidUpload.addEventListener('change', () => {
    const f = vidUpload.files && vidUpload.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f);
    fd.append('csrf_token', csrfToken());
    fetch('/tspro/files/upload', { method: 'POST', body: fd, credentials: 'same-origin' })
      .then(r => r.json()).then(data => {
        if (data && data.item && data.item.original_filename) {
          const url = '/pub/' + data.item.original_filename;
          setActiveField('bg_video_src', url);
          syncVideoPreview(url);
        }
      }).catch(err => console.warn('hero bg video upload failed', err));
  });
  const vidClear = modal.querySelector('#hero-video-clear');
  if (vidClear) vidClear.addEventListener('click', () => {
    setActiveField('bg_video_src', '');
    syncVideoPreview('');
  });

  // ── Pill click → populate + open ──────────────────────────────
  // Capture phase so we run BEFORE the generic [data-open-modal]
  // handler binds the modal-open animation; we just identify the
  // block to populate and let the open proceed normally.
  document.addEventListener('click', (e) => {
    const pill = e.target.closest('[data-block-type="hero"][data-page-block-id]');
    if (!pill) return;
    // Ignore clicks on the remove × button inside the pill — that
    // path should still work for delete.
    if (e.target.closest('[data-be-remove-block]')) return;
    activeBlockId = pill.dataset.pageBlockId;
    console.debug('[page-hero-modal] active block:', activeBlockId);
    let payload = null;
    try { payload = JSON.parse(pill.getAttribute('data-block-payload') || 'null'); }
    catch (_) {}
    if (!payload) payload = findBlock(activeBlockId);
    console.debug('[page-hero-modal] payload found:', !!payload, payload && Object.keys(payload.data || {}).length, 'keys');
    if (payload) populateModalFromBlock(payload);
  }, true);

  // ── Two-way binding: any input in the modal → persist ─────────
  // Document-level listener so we can't miss the event bubble even
  // if the modal element gets re-parented or restyled. Filtered to
  // events whose `target` is inside the modal so it only fires when
  // the admin is actually editing hero fields. Always dirty the
  // page-edit form regardless of whether `persistModalToBlock`
  // found the block — decouples user-visible feedback ("yes,
  // something changed") from the data-persistence path so edge
  // cases (fresh-drop race, missing block id, etc.) don't silently
  // swallow the dirty signal.
  function flagDirty() {
    if (form) {
      try { form.dispatchEvent(new Event('input', { bubbles: true })); } catch (_) {}
      try { form.dispatchEvent(new Event('change', { bubbles: true })); } catch (_) {}
    }
    const bar = document.getElementById('fe-save-bar');
    if (bar) {
      // Both attribute removal AND idl prop write — different code
      // paths read different forms, so cover both.
      bar.removeAttribute('hidden');
      bar.hidden = false;
      const m = bar.querySelector('.fe-save-bar-msg');
      if (m) m.textContent = 'Unsaved changes';
      document.body.classList.add('has-fe-save-bar');
    }
  }
  function isInModal(target) {
    return target && target.closest && target.closest('#page-hero-edit-modal');
  }
  document.addEventListener('input', (e) => {
    if (!isInModal(e.target)) return;
    persistModalToBlock();
    flagDirty();
    syncPreview();
  }, true);
  document.addEventListener('change', (e) => {
    if (!isInModal(e.target)) return;
    persistModalToBlock();
    flagDirty();
    syncPreview();
  }, true);

  // ── Late-fire submit listener ────────────────────────────────
  // Runs AFTER the inline submit handler in `frontend_page_edit.html`
  // (which writes `editor.serialize()` over hidden.value). We walk
  // the just-written JSON, find every hero block we've edited, and
  // patch its data back in. Belt-and-braces guard against the
  // BlockEditor's stale-state serialize wiping our work.
  if (form) {
    form.addEventListener('submit', () => {
      if (heroEdits.size === 0) return;
      let sections;
      try { sections = JSON.parse(hidden.value || '[]') || []; }
      catch (_) { return; }
      let touched = false;
      for (const sec of sections) {
        walkBlocks(sec.blocks || [], (b) => {
          if (heroEdits.has(b.id)) {
            b.data = Object.assign({}, b.data || {}, heroEdits.get(b.id));
            touched = true;
          }
        });
      }
      if (touched) hidden.value = JSON.stringify(sections);
    });
    // `formdata` fires when the browser actually builds the form
    // body for submit. Same patch — covers fetch-based saves
    // (the save-bar's POST uses `new FormData(form)`, which fires
    // formdata under the hood for our handler to capture).
    form.addEventListener('formdata', (e) => {
      if (heroEdits.size === 0) return;
      let sections;
      try { sections = JSON.parse(hidden.value || '[]') || []; }
      catch (_) { return; }
      let touched = false;
      for (const sec of sections) {
        walkBlocks(sec.blocks || [], (b) => {
          if (heroEdits.has(b.id)) {
            b.data = Object.assign({}, b.data || {}, heroEdits.get(b.id));
            touched = true;
          }
        });
      }
      if (touched) {
        const json = JSON.stringify(sections);
        hidden.value = json;
        try { e.formData.set('blocks_json', json); } catch (_) {}
      }
    });
  }
  }   // ── close init() ──

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
