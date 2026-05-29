// SPDX-License-Identifier: AGPL-3.0-or-later
/* Reusable block editor.
   Usage:
     const editor = BlockEditor.mount(rootEl, {
       initial: [...sections],
       onSerialize: (json) => hiddenInput.value = json
     });
   The host form should serialize via onSerialize in its submit handler.
*/
(function () {
  const uid = () => Math.random().toString(36).slice(2, 10);

  const BLOCK_TYPES = [
    { type: 'paragraph',   label: 'Text', icon: '¶' },
    { type: 'heading',     label: 'Heading', icon: 'H' },
    { type: 'image',       label: 'Image', icon: '🖼' },
    { type: 'button',      label: 'Button', icon: '⏵' },
    { type: 'container',   label: 'Container', icon: '▦' },
    { type: 'video',       label: 'Video', icon: '▶' },
    { type: 'lottie',      label: 'Lottie', icon: '✦' },
    { type: 'intergroup_member', label: 'Officer', icon: '☻' },
    { type: 'intergroup_member_roster', label: 'Officer Roster', icon: '⚏' },
    { type: 'library',     label: 'Library', icon: '📚' },
    { type: 'blog_list',   label: 'Blog list', icon: '📰' },
    { type: 'code',        label: 'Code', icon: '</>' },
    { type: 'callout',     label: 'Callout', icon: '⚠' },
    { type: 'list',        label: 'List', icon: '•' },
    { type: 'separator',   label: 'Divider', icon: '—' },
    { type: 'toc_sidebar', label: 'Wiki sidebar', icon: '☰' },
    { type: 'icon',        label: 'Icon', icon: '★' },
    // Homepage section blocks — usable on any content page via the
    // same builder. `hero` embeds the site-wide hero (no per-block
    // config); `meetings` + `events` carry their own filter / display
    // settings, hydrated server-side per instance.
    { type: 'hero',        label: 'Hero', icon: '✦' },
    { type: 'meetings',    label: 'Meetings', icon: '🗓' },
    { type: 'events',      label: 'Events', icon: '📅' },
    { type: 'features',    label: 'Features', icon: '▦' },
    { type: 'faq',         label: 'FAQ', icon: '?' },
  ];

  // Default typography knobs every text-bearing block carries. Blank
  // values mean "inherit from theme / page" — the renderer only emits
  // an inline style when a value is non-empty, so unedited blocks
  // stay lightweight in HTML.
  const TYPO_DEFAULTS = {
    font_family: '',     // CSS font-family stack, blank = inherit
    font_size: '',       // CSS font-size (e.g. "1.125rem", "20px")
    font_weight: '',     // 400 | 500 | 600 | 700 | blank
    color: '',           // hex / blank
    align: '',           // left | center | right | blank
    line_height: '',     // CSS line-height value
  };

  function blankBlock(type) {
    const d = {
      paragraph: { md: '', ...TYPO_DEFAULTS },
      heading: { level: 3, text: '', ...TYPO_DEFAULTS },
      image: { src: '', alt: '', caption: '',
               max_width_pct: 100, align: '',
               caption_color: '', caption_size: '',
               // border_radius: 0-50 px (0 = sharp corners). shadow:
               // a preset key consumed by `_blocks.html` ('' = none,
               // 'sm' | 'md' | 'lg' | 'xl' for the four presets).
               border_radius: 0, shadow: '' },
      video: { src: '', poster: '' },
      // Lottie animation block. `src` is a JSON URL (uploaded file at
      // /pub/<filename>, or external CDN). `loop` / `autoplay` toggle
      // the lottie-web player options; `speed` is a 0.25..3 multiplier;
      // `max_width_pct` + `align` mirror the image block. `renderer`
      // chooses lottie-web's render mode (svg = sharp at any size,
      // canvas = better perf for very heavy animations).
      lottie: {
        src: '',
        loop: true,
        autoplay: true,
        speed: 1,
        max_width_pct: 100,
        align: 'center',
        bg_color: '',
        renderer: 'svg',
        // 'auto' = respect autoplay/loop directly. 'hover' = park at
        // frame 0, play forward on mouseenter, reverse back on
        // mouseleave (autoplay is implicitly false in hover mode).
        playback: 'auto',
      },
      // Intergroup member block — references one row from the
      // IntergroupOfficer table. The public renderer looks up the row
      // at request time so changes to officer info propagate without
      // re-saving every page that uses the block.
      intergroup_member: {
        officer_id: 0,
        show_role: true,
        show_name: true,
        show_phone: true,
        show_email: true,
      },
      // Officer roster — loops every IntergroupOfficer row into a card
      // grid. `columns` is 2 or 3; `gap` is any CSS length.
      intergroup_member_roster: {
        columns: 3,
        gap: '1rem',
        show_role: true,
        show_name: true,
        show_phone: true,
        show_email: true,
      },
      // Blog list — pulls a filtered list of BlogPost rows. Pick a
      // single category OR tag (or neither) to scope the block — that's
      // how a fellowship hosts multiple distinct frontend "blogs" out
      // of a single Posts table. ``style`` picks the visual treatment;
      // ``max_items`` caps the rendered list (0 = unlimited). Drafts
      // and archives are filtered server-side.
      blog_list: {
        category_id: 0,
        tag_id: 0,
        title: '',
        subtitle: '',
        style: 'cards',          // cards | list | headlines
        columns: 3,              // cards-only: 1..4
        gap: '1.25rem',
        max_items: 6,
        sort: 'newest',          // newest | oldest | title | random
        only_featured: false,
        only_pinned: false,
        show_image: true,
        show_summary: true,
        show_categories: true,
        show_date: true,
        show_more_link: true,
      },
      // Library — picks a Library row by id, renders its items.
      // `mode='all'` shows everything; `mode='granular'` shows only
      // the items whose ids are in `item_ids`. Style controls the
      // visual treatment.
      library: {
        library_id: 0,
        mode: 'all',
        item_ids: [],
        style: 'cards',
        columns: 2,
        gap: '1rem',
        show_description: true,
        show_thumbnails: true,
        show_categories: true,
        title: '',
        // Sort applied at render time. Default 'manual' preserves the
        // library's own position-based order so existing blocks keep
        // their look until an admin opts into a different sort.
        sort: 'manual',
        // Optional progressive disclosure: 0 = show every item; >0
        // shows the first N and renders a Load More button that
        // reveals the next batch on click.
        max_items: 0,
      },
      code: { lang: '', code: '' },
      callout: { variant: 'info', title: '', md: '' },
      list: { ordered: false, items: [''],
              bullet_style: '',  // disc | circle | square | decimal | blank
              display_style: '', // '' | 'cards' | 'checklist' | 'arrows' | 'pills'
              // Card-style overrides (only applied when display_style='cards')
              card_bg: '', card_bg_dark: '', card_bg_dark_mode: 'same',
              card_border_color: '', card_border_color_dark: '',
              card_border_color_dark_mode: 'same',
              card_border_radius: '',
              card_padding: '',
              card_gap: '',
              card_shadow: '',
              card_hover_lift: true,
              card_num_bg: '', card_num_bg_dark: '', card_num_bg_dark_mode: 'same',
              card_num_color: '', card_num_color_dark: '', card_num_color_dark_mode: 'same',
              ...TYPO_DEFAULTS },
      separator: {},
      button: {
        label: 'Click here',
        url: '',
        align: 'left',
        style: 'primary',     // primary | secondary | custom
        new_tab: false,
        // Custom-style colour overrides (hex). Blank values fall back
        // to the .fe-btn token recipe so a half-configured custom
        // button still renders sensibly.
        bg: '',
        hover_bg: '',
        text_color: '',
        hover_text: '',
        border: '',
        hover_border: '',
        shadow: '',
      },
      // Wiki sidebar — sticky on-page TOC built at render time from
      // the page's heading blocks. The block itself just carries
      // presentation knobs (title, max heading level to include,
      // whether it sticks to the viewport top).
      toc_sidebar: {
        title: 'On this page',
        max_level: 3,
        sticky: true,
        sticky_offset: 96,
      },
      // Icon block — single Lucide / custom icon. `name` is an icon
      // ref accepted by `icon()` server-side; `size` is rendered as
      // `font-size` on the wrapper since `.icon` is sized via 1em.
      // Dark-mode colour rides the standard color/_dark/_dark_mode
      // triplet so the same picker drives both modes.
      icon: {
        name: '',
        size: 32,
        color: '',
        color_dark: '',
        color_dark_mode: 'same',
        align: 'center',
        url: '',
        new_tab: false,
      },
      // Nested-container block. Holds a `blocks` array of child blocks
      // (recursively editable) plus a tonne of layout / visual / hover
      // controls. Defaults are deliberately UNSTYLED — a freshly-
      // dropped container behaves like a plain `<div>` until the
      // admin styles it. Layout primitives (display, direction, etc.)
      // keep their CSS-default values; padding / gap / max-width are
      // zeroed so containers don't impose visible chrome by default.
      container: {
        // Admin-only friendly label surfaced in the structure tree —
        // public render ignores it. Empty = use the default
        // "Container" / "N-column row" wording.
        label: '',
        // ── Layout ──────────────────────────────────────────────────
        display: 'flex',           // flex | grid
        direction: 'column',        // row | column | row-reverse | column-reverse
        // Per-viewport flex direction override. Blank = "use the
        // default mobile collapse to column" (existing behaviour).
        // Otherwise: row | column | row-reverse | column-reverse —
        // wins at <=720px so admins can keep a row, reverse its
        // order, or surface the bottom child first on phones.
        mobile_direction: '',
        justify: 'flex-start',      // justify-content
        align: 'stretch',           // align-items
        wrap: false,                // flex-wrap
        grid_columns: 'repeat(2, 1fr)',
        gap: '0',
        // ── Spacing + width ────────────────────────────────────────
        padding: '0',
        // Per-viewport padding override. Blank = "use the desktop
        // padding on mobile too". Accepts any CSS padding shorthand
        // (single value, `top bottom`, `top right bottom left`, etc.).
        padding_mobile: '',
        // Free-form CSS height + min-height. Both blank = auto-sizing.
        // `height` is for the common "fill parent" case (e.g. `100%`
        // inside a grid cell so `justify-content: space-between`
        // actually has room to distribute children); `min_height` is
        // for the "at least N tall, but can grow" use case.
        height: '',
        min_height: '',
        width_mode: 'full',         // boxed | full — full = no max-width
        max_width: 0,
        // ── Background + border ────────────────────────────────────
        bg_color: '',               // empty → transparent
        border_width: 0,
        // Per-side width overrides. Empty string = "inherit
        // `border_width`" so the uniform value drives every side that
        // hasn't been customised. Setting any of these to an explicit
        // integer (incl. 0) overrides that side only — the renderer
        // switches from `border: <w>px ...` shorthand to the 4-value
        // `border-width: T R B L` shorthand when the four sides
        // differ.
        border_w_top: '',
        border_w_right: '',
        border_w_bottom: '',
        border_w_left: '',
        border_style: 'solid',      // solid | dashed | dotted | double
        border_color: '',
        border_radius: 0,
        shadow: 'none',             // none | sm | md | lg | xl
        // ── Hover (each empty = no hover override) ─────────────────
        hover_bg_color: '',
        hover_border_color: '',
        // Hover border width (uniform across all sides). Empty = no
        // hover change (rest-state widths stay in effect on hover);
        // any integer 0-16 = swap to that width on hover. Pairs well
        // with `border_width: 0` at rest + non-zero on hover so a
        // border appears only on hover.
        hover_border_width: '',
        hover_shadow: '',           // none | sm | md | lg | xl
        hover_lift: false,          // adds translateY(-2px)
        // ── Children (recursive) ───────────────────────────────────
        blocks: [],
      },
      // Hero block — per-instance content + background config. Mirrors
      // the homepage hero's full surface (heading + subheading + tagline,
      // heading/sub typography, dynamic text, desktop+mobile heights, 7
      // background styles, particle overlay, rich CTA button list).
      // Every field is independent of SiteSetting so each page's hero
      // is fully customisable. Visual primitives (.fe-hero, .fe-btn,
      // particle / sinewave / dynbg shells) are reused from the site
      // hero so the rendered block matches the design system without
      // any new stylesheet.
      hero: {
        // ── Content ─────────────────────────────────────────────
        heading: 'New hero',
        subheading: '',
        eyebrow: '',
        tagline_enabled: true,
        // ── Typography ──────────────────────────────────────────
        heading_font: 'fraunces',    // fraunces | inter
        heading_size_pct: 100,       // 50..200
        heading_grad_start: '#0f172a',
        heading_grad_end: '#374151',
        subheading_font: 'inter',    // fraunces | inter
        subheading_size_pct: 100,
        subheading_color: '#475569',
        text_dynamic: false,
        // ── Height ──────────────────────────────────────────────
        height_vh_desktop: 0,        // 0 = auto (padding-derived)
        height_vh_mobile: 0,         // 0 = inherit desktop value
        // ── Background ──────────────────────────────────────────
        bg_style: 'solid',           // frosty | solid | gradient | image | sinewave | video | dynamic
        // Solid + gradient
        bg_color: '',
        bg_color_2: '',
        bg_gradient_angle: 180,
        // Image
        bg_image_src: '',            // /pub/<filename> when uploaded
        bg_image_mode: 'cover',      // cover | tile
        bg_image_scale: 100,
        // Frosty
        bg_hue: 225,
        bg_hue_2: 170,
        bg_blur: 80,
        bg_opacity: 45,
        bg_randomize: false,
        // Sinewave — up to 4 hex stops
        bg_sinewave_colors: ['#16c2ba', '#1883d5', '#5a1ce5', '#0a3eb5'],
        // Video
        bg_video_src: '',
        bg_video_speed: 100,
        // Dynbg — points at a catalog key from app/dynbg.py
        bg_dynamic_key: '',
        bg_dynbg_config_json: '',
        // ── Particle overlay ───────────────────────────────────
        particle_enabled: false,
        particle_effect: 'stars',    // network | stars | fireflies | bubbles | snow | waves | orbits | rain
        particle_speed: 100,
        particle_size: 100,
        // ── Buttons ────────────────────────────────────────────
        // Each: {id, label, url, style, open_in_new_tab,
        //        icon_before, icon_before_color, icon_before_size,
        //        icon_after, icon_after_color, icon_after_size,
        //        custom_bg_color, custom_text_color}
        // `style` is 'primary' | 'ghost' (matches the homepage).
        buttons: [],
      },
      // Meetings list — mirrors blocks.MEETINGS_DEFAULTS. Each block
      // instance carries its own filter / display config; the page
      // route resolves `meetings_groups` per instance at render time.
      meetings: {
        heading: 'Upcoming Meetings',
        intro: "A quick look at what's on the schedule.",
        filter: 'upcoming_today',   // today_all | upcoming_today | next_24h | next_7_days | this_week | all
        max_count: 6,
        group_by_day: false,
        show_type_chip: true,
        show_schedule: true,
        show_first_n: 3,
        empty_message: 'No meetings scheduled — check back soon.',
        animation: 'fade',         // fade | slide | none
        stagger_ms: 60,
      },
      // Upcoming events — mirrors blocks.EVENTS_DEFAULTS.
      events: {
        heading: 'Upcoming Events',
        intro: '',
        max_count: 6,
        empty_message: 'No upcoming events — check back soon.',
        animation: 'fade',
        stagger_ms: 60,
        show_image: true,
        show_summary: true,
        show_location: true,
      },
      // Features block — heading + subheading + an inline list of
      // {icon, icon_color, icon_size, title, body, href,
      // open_in_new_tab} cards. The dedicated `#page-features-edit-modal`
      // handles add/remove/reorder/edit; this blank just seeds the
      // shape so palette drops produce a valid payload.
      features: {
        heading: 'What we offer',
        subheading: 'Everything a fellowship needs to stay connected and welcoming.',
        items: [],
      },
      // FAQ block — heading + subheading + flat list of
      // {question, answer, icon, icon_size} accordion items.
      // Heading / subheading default to empty so the public partial's
      // fallbacks ("Frequently asked questions" / "Common questions
      // from people…") engage until the admin customises them.
      faq: {
        heading: '',
        subheading: '',
        items: [],
      },
    }[type] || {};
    return { id: uid(), type, data: d };
  }

  // ── Lucide catalog cache (icon block live preview) ────────────────
  // Single-shot fetch keyed off the icon-picker-modal's `data-catalog
  // -url` (the same URL the modal itself uses), so the icon block's
  // preview, the picker modal, and any future consumers all hit the
  // same JSON. Cached as a Promise so concurrent first-renders dedupe.
  let _blockEditorIconCatalog = null;
  let _blockEditorIconCatalogPromise = null;
  function loadBlockEditorIconCatalog() {
    if (_blockEditorIconCatalog) return Promise.resolve(_blockEditorIconCatalog);
    if (_blockEditorIconCatalogPromise) return _blockEditorIconCatalogPromise;
    const modalEl = document.getElementById('icon-picker-modal');
    const url = (modalEl && modalEl.getAttribute('data-catalog-url')) ||
                '/static/vendor/lucide/icons.json';
    _blockEditorIconCatalogPromise = fetch(url, { credentials: 'same-origin' })
      .then(r => r.json())
      .then(data => { _blockEditorIconCatalog = data || { categories: [] }; return _blockEditorIconCatalog; })
      .catch(() => { _blockEditorIconCatalog = { categories: [] }; return _blockEditorIconCatalog; });
    return _blockEditorIconCatalogPromise;
  }
  function findIconPathsInCatalog(catalog, name) {
    if (!catalog || !name) return null;
    for (const cat of catalog.categories || []) {
      for (const ic of cat.icons || []) {
        if (ic && ic.name === name) return ic.paths || null;
      }
    }
    return null;
  }

  function el(tag, attrs, children) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === 'class') n.className = attrs[k];
      else if (k === 'html') n.innerHTML = attrs[k];
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(c => {
      if (c == null) return;
      if (typeof c === 'string') n.appendChild(document.createTextNode(c));
      else n.appendChild(c);
    });
    return n;
  }

  // ── Dark-mode colour helper ──────────────────────────────────────
  // Derives a "good enough" dark-mode equivalent of a light hex by
  // converting to HSL and inverting lightness (keeps hue + saturation
  // intact). #1a1a1a → #e5e5e5, #4a90e2 → #4a90e2-ish (already mid-
  // lightness — small change), #ffffff → #000000. Returns '' when
  // the input isn't a valid hex.
  const _HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
  const _TOKEN_RE = /^token:([a-z0-9_]+)$/i;

  // ── Design-token picker (shared across every color input) ───────
  // The page-edit template surfaces every color token from
  // `Settings → Design → Colors` as `window.tspDesignColorTokens`
  // (key → resolved hex). `attachTokenPicker(textInput, swatchInput)`
  // adds a 🎨 button next to a color input cluster; clicking it
  // opens a single shared popover listing every token. Selecting a
  // token writes `token:<key>` to the text input (the storage format
  // the public renderer translates to `var(--fe-color-<key>)` via
  // the `css_color` filter) and updates the swatch to the resolved
  // hex so the admin sees the current visual.
  function _tokenMap() { return window.tspDesignColorTokens || {}; }
  function _resolveSwatchHex(value) {
    value = (value || '').trim();
    if (!value) return null;
    const m = value.match(_TOKEN_RE);
    if (m) return _tokenMap()[m[1]] || null;
    if (_HEX_RE.test(value)) {
      return value.length === 4
        ? '#' + value[1] + value[1] + value[2] + value[2] + value[3] + value[3]
        : value.toLowerCase();
    }
    return null;
  }

  let _tokenPopover = null;
  let _tokenPopoverActive = null;  // { textInput, swatchInput, anchorEl }
  function _ensureTokenPopover() {
    if (_tokenPopover) return _tokenPopover;
    const tokens = _tokenMap();
    const popover = document.createElement('div');
    popover.className = 'fe-page-bg-token-popover be-color-token-popover';
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-label', 'Design token picker');
    popover.hidden = true;
    let inner = '<div class="fe-page-bg-token-popover-head">'
              + '<h4>Design tokens</h4>'
              + '<button type="button" class="icon-btn" data-token-popover-close '
              + 'aria-label="Close">×</button></div>'
              + '<p class="muted smaller">Pick a token. Updates in '
              + '<b>Settings → Design</b> propagate everywhere it\'s used.</p>'
              + '<div class="fe-page-bg-token-grid">';
    Object.keys(tokens).forEach(key => {
      const hex = tokens[key] || '';
      const label = key.replace(/^color_/, '').replace(/_/g, ' ')
                       .replace(/\b\w/g, c => c.toUpperCase());
      inner += '<button type="button" class="fe-page-bg-token-tile" '
            +  'data-token-key="' + key + '" '
            +  'title="' + label + ' · ' + hex + '">'
            +  '<span class="fe-page-bg-token-swatch" style="background: ' + hex + ';"></span>'
            +  '<span class="fe-page-bg-token-meta">'
            +  '<span class="fe-page-bg-token-label">' + label + '</span>'
            +  '<span class="fe-page-bg-token-hex muted smaller">' + hex + '</span>'
            +  '</span></button>';
    });
    inner += '</div>';
    popover.innerHTML = inner;
    document.body.appendChild(popover);
    popover.addEventListener('click', e => {
      e.stopPropagation();
      if (e.target.closest('[data-token-popover-close]')) {
        _closeTokenPopover();
        return;
      }
      const tile = e.target.closest('[data-token-key]');
      if (!tile || !_tokenPopoverActive) return;
      const key = tile.dataset.tokenKey;
      const { textInput, swatchInput } = _tokenPopoverActive;
      if (textInput) {
        textInput.value = 'token:' + key;
        textInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (swatchInput) {
        const hex = _tokenMap()[key] || '#ffffff';
        swatchInput.value = hex;
      }
      _closeTokenPopover();
    });
    document.addEventListener('click', e => {
      if (!_tokenPopover || _tokenPopover.hidden) return;
      if (_tokenPopover.contains(e.target)) return;
      if (_tokenPopoverActive && _tokenPopoverActive.anchorEl
          && _tokenPopoverActive.anchorEl.contains(e.target)) return;
      _closeTokenPopover();
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && _tokenPopover && !_tokenPopover.hidden) {
        _closeTokenPopover();
      }
    });
    _tokenPopover = popover;
    return popover;
  }
  function _openTokenPopover(textInput, swatchInput, anchorEl) {
    const popover = _ensureTokenPopover();
    _tokenPopoverActive = { textInput, swatchInput, anchorEl };
    popover.hidden = false;
    const r = anchorEl.getBoundingClientRect();
    popover.style.top = (r.bottom + 6) + 'px';
    const left = Math.min(r.left, window.innerWidth - popover.offsetWidth - 16);
    popover.style.left = Math.max(8, left) + 'px';
  }
  function _closeTokenPopover() {
    if (!_tokenPopover) return;
    _tokenPopover.hidden = true;
    _tokenPopoverActive = null;
  }

  // Adds a 🎨 token button to a color cluster. The caller positions
  // it within their wrapper. `onPick(value)` runs after a token is
  // selected so the caller can sync any other state (e.g. commitNotify).
  function attachTokenButton(textInput, swatchInput, onPick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-sm be-token-btn';
    btn.title = 'Pick a design token';
    // Inline SVG palette icon — keeps the helper self-contained, no
    // dependency on the server-side icon() helper. Matches the size
    // of other small inline SVGs in the editor.
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" '
      + 'fill="none" stroke="currentColor" stroke-width="2" '
      + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<circle cx="13.5" cy="6.5" r="0.5" fill="currentColor"/>'
      + '<circle cx="17.5" cy="10.5" r="0.5" fill="currentColor"/>'
      + '<circle cx="8.5" cy="7.5" r="0.5" fill="currentColor"/>'
      + '<circle cx="6.5" cy="12.5" r="0.5" fill="currentColor"/>'
      + '<path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>'
      + '</svg>';
    btn.addEventListener('click', e => {
      e.preventDefault();
      e.stopPropagation();
      // Toggle: clicking again on the same anchor closes it.
      if (_tokenPopover && !_tokenPopover.hidden
          && _tokenPopoverActive && _tokenPopoverActive.anchorEl === btn) {
        _closeTokenPopover();
        return;
      }
      _openTokenPopover(textInput, swatchInput, btn);
    });
    if (onPick) {
      // Surface picks back to the caller via the text input's `input`
      // event (the popover dispatches one after writing). Caller can
      // listen there too — this is a convenience hook.
      textInput.addEventListener('input', () => onPick(textInput.value));
    }
    return btn;
  }

  function deriveDarkMode(hex) {
    if (!hex || !_HEX_RE.test(hex)) return '';
    let h = hex.slice(1);
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    let r = parseInt(h.substr(0, 2), 16) / 255;
    let g = parseInt(h.substr(2, 2), 16) / 255;
    let b = parseInt(h.substr(4, 2), 16) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let hue, sat, lt = (max + min) / 2;
    if (max === min) { hue = 0; sat = 0; }
    else {
      const d = max - min;
      sat = lt > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: hue = (g - b) / d + (g < b ? 6 : 0); break;
        case g: hue = (b - r) / d + 2; break;
        case b: hue = (r - g) / d + 4; break;
      }
      hue /= 6;
    }
    lt = 1 - lt;  // invert lightness
    function h2r(p, q, t) {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1/6) return p + (q - p) * 6 * t;
      if (t < 1/2) return q;
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
      return p;
    }
    const q = lt < 0.5 ? lt * (1 + sat) : lt + sat - lt * sat;
    const p = 2 * lt - q;
    r = Math.round(h2r(p, q, hue + 1/3) * 255);
    g = Math.round(h2r(p, q, hue) * 255);
    b = Math.round(h2r(p, q, hue - 1/3) * 255);
    return '#' + [r, g, b].map(n => n.toString(16).padStart(2, '0')).join('');
  }

  const ICON_PATHS = {
    'x': '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    'grip-vertical': '<circle cx="9" cy="5" r="1" fill="currentColor" stroke="none"/><circle cx="9" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="9" cy="19" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="5" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="19" r="1" fill="currentColor" stroke="none"/>',
  };
  function iconEl(name) {
    const wrap = document.createElement('span');
    wrap.innerHTML = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICON_PATHS[name] || '') + '</svg>';
    return wrap.firstChild;
  }

  function mount(root, opts) {
    opts = opts || {};
    const state = { sections: JSON.parse(JSON.stringify(opts.initial || [])) };
    if (!state.sections.length) state.sections.push({ id: uid(), title: 'New Section', blocks: [] });

    root.classList.add('be-root');
    root.innerHTML = '';

    // Dispatch a bubbling `input` event from the editor root so any
    // ancestor save-bar / dirty-tracker that listens for native input
    // events on its enclosing form picks up state changes that don't
    // come from a real <input>/<select> (toggle clicks, programmatic
    // hidden-input writes, color clears, etc.). Native field edits
    // already bubble; this just covers the click-only paths.
    function notifyChange() {
      try { root.dispatchEvent(new Event('input', { bubbles: true })); }
      catch (_) { /* very old browsers */ }
    }

    const sectionsEl = el('div', { class: 'be-sections' });
    root.appendChild(sectionsEl);

    const addSectionBtn = el('button', {
      type: 'button', class: 'btn be-add-section',
      onclick: () => {
        state.sections.push({ id: uid(), title: 'New Section', blocks: [] });
        render();
      }
    }, ['+ Add section']);
    root.appendChild(addSectionBtn);

    function render() {
      // Capture focus before wiping so a re-render triggered from
      // inside a focused block (e.g. flipping a container's display
      // from Flex to Grid) doesn't strand the editor in focus-mode
      // with no `.be-block-focused` element. Without this restore,
      // the .is-focus-mode CSS hides every block + section and the
      // modal looks empty.
      const prevFocused = sectionsEl.querySelector('.be-block-focused');
      const focusedId = prevFocused ? prevFocused.dataset.id : null;

      sectionsEl.innerHTML = '';
      state.sections.forEach((sec, idx) => sectionsEl.appendChild(renderSection(sec, idx)));
      // Sortable on sections
      Sortable.create(sectionsEl, {
        handle: '.be-section-drag',
        animation: 150,
        onEnd: (e) => {
          const [moved] = state.sections.splice(e.oldIndex, 1);
          state.sections.splice(e.newIndex, 0, moved);
          notifyChange();
        },
      });

      // Re-apply focus to the same block so .is-focus-mode keeps
      // showing the right subtree. Walks up `.be-block` / `.be-section`
      // ancestors stamping `.be-block-focused-path`, matching the
      // logic in frontend_page_edit.html's focusBlock helper.
      if (focusedId) {
        const target = sectionsEl.querySelector(
          '.be-block[data-id="' + (window.CSS && CSS.escape ? CSS.escape(focusedId) : focusedId) + '"]');
        if (target) {
          target.classList.add('be-block-focused');
          let node = target.parentElement;
          while (node && node !== sectionsEl) {
            if (node.classList && (node.classList.contains('be-block')
                                    || node.classList.contains('be-section'))) {
              node.classList.add('be-block-focused-path');
            }
            node = node.parentElement;
          }
        }
      }
    }

    // Locate the blocks-array (`sec.blocks` or a container's
    // `data.blocks`) by the parent's id. Sections and container blocks
    // both expose a unique `id` — the data-blocks-parent attribute on
    // the rendered `.be-blocks` div carries that id, so cross-parent
    // drags can resolve source + destination via this lookup.
    function findBlocksById(id) {
      for (const sec of state.sections) {
        if (sec.id === id) return sec.blocks;
        const found = findContainerBlocks(sec.blocks, id);
        if (found) return found;
      }
      return null;
    }
    function findContainerBlocks(blocks, id) {
      for (const b of blocks) {
        if (b.type === 'container' && b.data) {
          if (b.id === id) return b.data.blocks || (b.data.blocks = []);
          const nested = findContainerBlocks(b.data.blocks || [], id);
          if (nested) return nested;
        }
      }
      return null;
    }

    function renderSection(sec, idx) {
      const wrap = el('div', { class: 'be-section', 'data-id': sec.id });
      const head = el('div', { class: 'be-section-head' }, [
        el('span', { class: 'be-section-drag', title: 'Drag to reorder' }, [iconEl('grip-vertical')]),
        el('input', {
          type: 'text', class: 'be-section-title', value: sec.title || '',
          placeholder: 'Section title',
          oninput: (e) => { sec.title = e.target.value; },
        }),
        el('button', {
          type: 'button', class: 'icon-btn be-remove', title: 'Delete section',
          onclick: () => {
            if (!confirm('Delete this section and its blocks?')) return;
            state.sections.splice(idx, 1); render(); notifyChange();
          }
        }, [iconEl('x')]),
      ]);
      wrap.appendChild(head);
      // Section's blocks-list + +Add bar (shared with containers via
      // the renderBlocksList helper below).
      const list = renderBlocksList(sec.blocks, sec.id);
      wrap.appendChild(list.blocksEl);
      wrap.appendChild(list.addBar);
      return wrap;
    }

    // Shared renderer for any blocks-array — used by both sections and
    // containers. `parentId` matches a section's id or a container's id,
    // and is written into data-blocks-parent so Sortable's onAdd can
    // resolve the source / destination arrays via findBlocksById.
    function renderBlocksList(blocks, parentId) {
      const blocksEl = el('div', {
        class: 'be-blocks', 'data-blocks-parent': parentId,
      });
      blocks.forEach((b, bi) => blocksEl.appendChild(renderBlock(blocks, b, bi)));

      Sortable.create(blocksEl, {
        group: 'be-blocks',
        handle: '.be-block-drag',
        animation: 150,
        onAdd: (e) => moveBlockBetween(e),
        onEnd: (e) => {
          if (e.from === e.to) {
            const [moved] = blocks.splice(e.oldIndex, 1);
            blocks.splice(e.newIndex, 0, moved);
            notifyChange();
          }
        },
      });

      const addBar = el('div', { class: 'be-add-block-bar' });
      // Optional palette restriction. When the host passes
      // `allowedTypes: ['paragraph', 'image', ...]`, only those block
      // buttons are offered (used by the Popups editor to hide the
      // homepage-section blocks that need the page editor's dedicated
      // modals). Omitted/empty → the full BLOCK_TYPES catalog.
      const _allowed = Array.isArray(opts.allowedTypes) && opts.allowedTypes.length
        ? opts.allowedTypes : null;
      BLOCK_TYPES.filter(bt => !_allowed || _allowed.indexOf(bt.type) !== -1).forEach(bt => {
        addBar.appendChild(el('button', {
          type: 'button', class: 'btn btn-sm be-add-block', title: `Add ${bt.label}`,
          onclick: () => {
            blocks.push(blankBlock(bt.type));
            render();
            notifyChange();
          },
        }, [bt.icon + ' ' + bt.label]));
      });
      return { blocksEl, addBar };
    }

    function moveBlockBetween(e) {
      // Cross-parent drag (between sections, between containers, or
      // between a section and a nested container). The data-blocks-
      // parent attribute on each `.be-blocks` div carries the id we
      // resolve into a blocks array via findBlocksById.
      const fromEl = e.from;
      const toEl = e.to;
      const fromId = fromEl && fromEl.dataset && fromEl.dataset.blocksParent;
      const toId = toEl && toEl.dataset && toEl.dataset.blocksParent;
      const fromList = fromId && findBlocksById(fromId);
      const toList = toId && findBlocksById(toId);
      if (!fromList || !toList) return;
      const [moved] = fromList.splice(e.oldIndex, 1);
      toList.splice(e.newIndex, 0, moved);
      notifyChange();
    }

    function renderBlock(parentBlocks, b, bi) {
      const wrap = el('div', { class: 'be-block be-block-' + b.type, 'data-id': b.id });
      const head = el('div', { class: 'be-block-head' }, [
        el('span', { class: 'be-block-drag', title: 'Drag to reorder' }, [iconEl('grip-vertical')]),
        el('span', { class: 'be-block-type' }, [b.type]),
        el('button', {
          type: 'button', class: 'icon-btn be-remove', title: 'Remove block',
          onclick: () => removeBlock(parentBlocks, bi),
        }, [iconEl('x')]),
      ]);
      wrap.appendChild(head);
      wrap.appendChild(renderBlockBody(b));
      // Containers render their own children list + +Add bar after the
      // settings panels. The recursion happens in renderContainerBody,
      // not here — keeps the wrap shape consistent for every type.
      return wrap;
    }

    // Centralised block-removal so container deletions don't silently
    // lose their children. When the block being removed is a container
    // with non-empty `data.blocks`, the children are extracted before
    // the splice and shipped on a `blockremove` CustomEvent — the page
    // editor's structure-card listener then drops them into the
    // "Unplaced blocks" card so they survive the delete without a
    // refresh. Empty containers (and every other block type) just
    // splice straight out.
    function removeBlock(parentBlocks, bi) {
      const removed = parentBlocks[bi];
      let liftedChildren = [];
      if (removed && removed.type === 'container'
          && removed.data && Array.isArray(removed.data.blocks)
          && removed.data.blocks.length) {
        liftedChildren = removed.data.blocks.slice();
        const n = liftedChildren.length;
        const msg = `Delete this container?\n\n`
                  + `Its ${n} block${n === 1 ? '' : 's'} `
                  + `will move to "Unplaced blocks" so nothing is lost.`;
        if (!confirm(msg)) return;
      }
      parentBlocks.splice(bi, 1);
      render();
      notifyChange();
      try {
        root.dispatchEvent(new CustomEvent('blockremove', {
          bubbles: true,
          detail: {
            id: (removed && removed.id) || null,
            type: (removed && removed.type) || null,
            liftedChildren: liftedChildren,
          },
        }));
      } catch (_) {}
    }

    function ta(value, oninput, opts2) {
      return el('textarea', Object.assign({
        rows: (opts2 && opts2.rows) || 4,
        placeholder: (opts2 && opts2.placeholder) || '',
        oninput: (e) => oninput(e.target.value),
      }, opts2 && opts2.attrs || {}), [value || '']);
    }

    // ── Reusable colour picker with dark-mode mode toggle ──────────
    // Produces a 3-row block: light-mode swatch + hex + clear; mode
    // toggle [Same | Auto | Manual]; manual dark-mode swatch + hex +
    // clear (only visible when mode === 'manual'); a small "auto-
    // derived: #abcdef" preview chip (only visible when mode === 'auto').
    //
    // opts = {
    //   value:     string  (current light hex, '' = inherit),
    //   valueDark: string  (manual dark hex, '' = none — only used for 'manual' mode),
    //   mode:      'same' | 'auto' | 'manual',
    //   placeholder: string  (placeholder text for the light hex input),
    //   onChange:  (light, dark, mode) => void
    //                  Called on every change. `dark` is computed from
    //                  the current mode: '' for 'same', the auto-derived
    //                  hex for 'auto', or the picked hex for 'manual'.
    // }
    // Dynamic-background trigger — builds a button that opens the
    // global dynbg picker modal (shared with every other backend
    // surface that supports dynamic backgrounds). Returns a wrapper
    // element containing five hidden inputs (base key + overlay +
    // three custom colours) plus the trigger button. The hidden
    // inputs exist purely so the global modal handler can read/write
    // the selected values the same way it does on regular forms; we
    // listen to their `change` events to fire the caller's onChange
    // callback with the consolidated state.
    //
    // Signature accepts an opts object so callers can pre-populate
    // every dimension at once. Backwards-compatible: a string first
    // arg is treated as the base key for legacy call sites.
    let _dynbgTriggerSeq = 0;
    function dynbgTrigger(opts, legacyOnChange) {
      // Legacy positional form: `dynbgTrigger('key', cb)`.
      if (typeof opts === 'string' || opts == null) {
        opts = { key: opts || '', onChange: legacyOnChange };
      }
      const currentKey = opts.key || '';
      const currentOverlay = opts.overlay || '';
      const currentColors = (opts.colors || []).slice(0, 3);
      while (currentColors.length < 3) currentColors.push('');
      const currentScope = opts.scope || '';
      const currentNoiseSize = opts.noiseSize == null ? '' : String(opts.noiseSize);
      const currentNoiseIntensity = opts.noiseIntensity == null ? '' : String(opts.noiseIntensity);
      const currentRandomizeColors    = opts.randomizeColors ? '1' : '';
      const currentRandomizePositions = opts.randomizePositions ? '1' : '';
      const currentAnimateOff         = opts.animateOff ? '1' : '';
      const currentPastelLight        = opts.pastelLight ? '1' : '';
      // Per-preset knobs travel as one JSON blob (matches the macro's
      // `__knobs` hidden input contract). '' = no overrides.
      const currentKnobs = (opts.knobs && typeof opts.knobs === 'object'
        && Object.keys(opts.knobs).length) ? JSON.stringify(opts.knobs) : '';
      const onChange = opts.onChange || (() => {});

      const id = 'be-dynbg-trigger-' + (++_dynbgTriggerSeq);
      const wrap = el('div', { class: 'fe-dynbg-trigger-wrap' });
      const baseInput = el('input', {
        type: 'hidden', id: id + '-input', value: currentKey,
      });
      const overlayInput = el('input', {
        type: 'hidden', id: id + '-overlay', value: currentOverlay,
      });
      const c1Input = el('input', { type: 'hidden', id: id + '-c1', value: currentColors[0] });
      const c2Input = el('input', { type: 'hidden', id: id + '-c2', value: currentColors[1] });
      const c3Input = el('input', { type: 'hidden', id: id + '-c3', value: currentColors[2] });
      const scopeInput = el('input', { type: 'hidden', id: id + '-scope', value: currentScope });
      const sizeInput = el('input', { type: 'hidden', id: id + '-noise-size', value: currentNoiseSize });
      const intensityInput = el('input', { type: 'hidden', id: id + '-noise-intensity', value: currentNoiseIntensity });
      const randomizeColorsInput    = el('input', { type: 'hidden', id: id + '-randomize-colors',    value: currentRandomizeColors });
      const randomizePositionsInput = el('input', { type: 'hidden', id: id + '-randomize-positions', value: currentRandomizePositions });
      const animateOffInput         = el('input', { type: 'hidden', id: id + '-animate-off',        value: currentAnimateOff });
      const pastelLightInput        = el('input', { type: 'hidden', id: id + '-pastel-light',       value: currentPastelLight });
      const knobsInput              = el('input', { type: 'hidden', id: id + '-knobs',             value: currentKnobs });

      // Resolve the catalog row matching the current key by reading
      // the global modal's grid — that's the same source of truth as
      // every other admin surface, and it means new presets light up
      // here the moment they're added to the catalog.
      function entryFor(key) {
        if (!key) return null;
        const card = document.querySelector(
          '#dynbg-picker-modal-grid [data-dynbg-key="' + CSS.escape(key) + '"]');
        if (!card) return null;
        const name = card.querySelector('.fe-dynbg-picker-name');
        const thumb = card.querySelector('.fe-dynbg-picker-thumb');
        return {
          key,
          name: name ? name.textContent.trim() : key,
          thumbHtml: thumb ? thumb.innerHTML : '',
        };
      }
      function renderThumb(thumbEl, entry) {
        if (entry) {
          thumbEl.innerHTML = entry.thumbHtml;
        } else {
          const placeholder = el('span', {
            class: 'fe-dynbg-trigger-thumb-none',
            'aria-hidden': 'true',
          }, ['∅']);
          thumbEl.innerHTML = '';
          thumbEl.appendChild(placeholder);
        }
      }
      function statusText(entry, overlay, colors, randomizeColors, randomizePositions, animateOff) {
        const bits = [];
        bits.push(entry ? 'Click to change or clear' : 'No dynamic background — click to add');
        const extras = [];
        if (overlay) {
          // Pull the overlay's name from the modal's overlay grid so
          // the status reads "Noise grain overlay" instead of the
          // generic "overlay set". Same pattern as the base-key
          // entryFor() lookup above.
          const overlayCard = document.querySelector(
            '#dynbg-picker-modal-overlay-grid [data-dynbg-overlay-key="' + CSS.escape(overlay) + '"]');
          const overlayNameEl = overlayCard && overlayCard.querySelector('.fe-dynbg-picker-name');
          const overlayName = overlayNameEl ? overlayNameEl.textContent.trim() : overlay;
          extras.push(overlayName + ' overlay');
        }
        if (randomizeColors) {
          extras.push('random colours');
        } else {
          const filled = colors.filter(Boolean).length;
          if (filled) extras.push(filled + ' colour' + (filled === 1 ? '' : 's'));
        }
        if (randomizePositions) extras.push('random positions');
        if (animateOff) extras.push('static');
        if (extras.length) bits.push('· ' + extras.join(', '));
        return bits.join(' ');
      }

      const entry = entryFor(currentKey);
      const thumbEl = el('span', { class: 'fe-dynbg-trigger-thumb' });
      renderThumb(thumbEl, entry);
      const nameEl = el('span', { class: 'fe-dynbg-trigger-name' },
        [entry ? entry.name : 'Choose…']);
      const statusEl = el('span',
        { class: 'fe-dynbg-trigger-status muted smaller' },
        [statusText(entry, currentOverlay, currentColors,
                     !!currentRandomizeColors, !!currentRandomizePositions,
                     !!currentAnimateOff)]);
      const textEl = el('span', { class: 'fe-dynbg-trigger-text' }, [nameEl, statusEl]);
      const caret = el('span', { class: 'fe-dynbg-trigger-caret', 'aria-hidden': 'true' });
      caret.textContent = '›';
      const btn = el('button', {
        type: 'button', class: 'fe-dynbg-trigger', id,
        'data-dynbg-trigger': '',
        'data-dynbg-trigger-input':                  '#' + id + '-input',
        'data-dynbg-trigger-overlay-input':          '#' + id + '-overlay',
        'data-dynbg-trigger-c1-input':               '#' + id + '-c1',
        'data-dynbg-trigger-c2-input':               '#' + id + '-c2',
        'data-dynbg-trigger-c3-input':               '#' + id + '-c3',
        'data-dynbg-trigger-scope-input':            '#' + id + '-scope',
        'data-dynbg-trigger-noise-size-input':       '#' + id + '-noise-size',
        'data-dynbg-trigger-noise-intensity-input':       '#' + id + '-noise-intensity',
        'data-dynbg-trigger-randomize-colors-input':      '#' + id + '-randomize-colors',
        'data-dynbg-trigger-randomize-positions-input':   '#' + id + '-randomize-positions',
        'data-dynbg-trigger-animate-off-input':           '#' + id + '-animate-off',
        'data-dynbg-trigger-pastel-light-input':          '#' + id + '-pastel-light',
        'data-dynbg-trigger-knobs-input':                 '#' + id + '-knobs',
        'data-dynbg-current': currentKey,
        'data-dynbg-overlay': currentOverlay,
        'data-dynbg-c1': currentColors[0],
        'data-dynbg-c2': currentColors[1],
        'data-dynbg-c3': currentColors[2],
        'data-dynbg-scope': currentScope,
        'data-dynbg-noise-size': currentNoiseSize,
        'data-dynbg-noise-intensity': currentNoiseIntensity,
        'data-dynbg-randomize-colors': currentRandomizeColors,
        'data-dynbg-randomize-positions': currentRandomizePositions,
        'data-dynbg-animate-off': currentAnimateOff,
        'data-dynbg-pastel-light': currentPastelLight,
        'data-dynbg-knobs': currentKnobs,
      }, [thumbEl, textEl, caret]);

      // The global modal handler dispatches `change` events on every
      // hidden input after Save / Clear. We consolidate them into a
      // single callback fire so the block editor only re-serialises
      // once per modal save, not nine times.
      let scheduled = false;
      function notifyConsolidated() {
        if (scheduled) return;
        scheduled = true;
        // Microtask drain — by the time this fires, every input the
        // modal updated has already dispatched its change event.
        Promise.resolve().then(() => {
          scheduled = false;
          const k  = baseInput.value || '';
          const ov = overlayInput.value || '';
          const cs = [c1Input.value || '', c2Input.value || '', c3Input.value || ''];
          const sc  = scopeInput.value || '';
          const ns  = sizeInput.value || '';
          const ni  = intensityInput.value || '';
          const rc  = randomizeColorsInput.value === '1';
          const rp  = randomizePositionsInput.value === '1';
          const ao  = animateOffInput.value === '1';
          const pl  = pastelLightInput.value === '1';
          const kn  = knobsInput.value || '';
          btn.setAttribute('data-dynbg-current', k);
          btn.setAttribute('data-dynbg-overlay', ov);
          btn.setAttribute('data-dynbg-c1', cs[0]);
          btn.setAttribute('data-dynbg-c2', cs[1]);
          btn.setAttribute('data-dynbg-c3', cs[2]);
          btn.setAttribute('data-dynbg-scope', sc);
          btn.setAttribute('data-dynbg-noise-size', ns);
          btn.setAttribute('data-dynbg-noise-intensity', ni);
          btn.setAttribute('data-dynbg-randomize-colors',    rc ? '1' : '');
          btn.setAttribute('data-dynbg-randomize-positions', rp ? '1' : '');
          btn.setAttribute('data-dynbg-animate-off',         ao ? '1' : '');
          btn.setAttribute('data-dynbg-pastel-light',        pl ? '1' : '');
          btn.setAttribute('data-dynbg-knobs',               kn);
          const newEntry = entryFor(k);
          renderThumb(thumbEl, newEntry);
          nameEl.textContent = newEntry ? newEntry.name : 'Choose…';
          statusEl.textContent = statusText(newEntry, ov, cs, rc, rp, ao);
          onChange({
            key: k,
            overlay: ov,
            colors: cs.filter(Boolean),
            scope: sc,
            noiseSize: ns,
            noiseIntensity: ni,
            randomizeColors: rc,
            randomizePositions: rp,
            animateOff: ao,
            pastelLight: pl,
            knobs: kn,
          });
        });
      }
      const allInputs = [baseInput, overlayInput, c1Input, c2Input, c3Input,
                         scopeInput, sizeInput, intensityInput,
                         randomizeColorsInput, randomizePositionsInput,
                         animateOffInput, pastelLightInput, knobsInput];
      allInputs.forEach(inp => inp.addEventListener('change', notifyConsolidated));
      allInputs.forEach(i => wrap.appendChild(i));
      wrap.appendChild(btn);
      return wrap;
    }

    function colorPickerWithDarkMode(opts) {
      const onChange = opts.onChange || (() => {});
      let curLight = opts.value || '';
      let curManualDark = opts.valueDark || '';
      let curMode = ['same', 'auto', 'manual'].includes(opts.mode) ? opts.mode : 'same';

      function commitNotify() {
        const dark = curMode === 'manual'
          ? curManualDark
          : (curMode === 'auto' ? deriveDarkMode(curLight) : '');
        onChange(curLight, dark, curMode);
      }

      const wrap = el('div', { class: 'be-color-with-dm' });

      // Light swatch + hex + clear
      const lightSwatch = el('input', {
        type: 'color', value: curLight || '#0f172a',
      });
      const lightText = el('input', {
        type: 'text', class: 'be-container-color-text',
        maxlength: '7', spellcheck: 'false', autocomplete: 'off',
        placeholder: opts.placeholder || 'inherit',
        value: curLight,
      });
      const lightClear = el('button', {
        type: 'button', class: 'btn btn-sm',
      }, ['Clear']);
      function setLight(v) {
        curLight = v;
        const swatchHex = _resolveSwatchHex(v);
        if (swatchHex) lightSwatch.value = swatchHex;
        lightText.classList.remove('is-invalid');
        if (curMode === 'auto') updateAutoPreview();
        commitNotify();
      }
      lightSwatch.addEventListener('input', () => { setLight(lightSwatch.value); lightText.value = lightSwatch.value; });
      lightText.addEventListener('input', () => {
        let v = (lightText.value || '').trim();
        if (!v) { setLight(''); return; }
        // Tokens (`token:key`) bypass hex validation — they're a
        // valid storage form that the renderer translates to var(...).
        if (_TOKEN_RE.test(v)) { setLight(v); return; }
        if (!v.startsWith('#')) v = '#' + v;
        if (_HEX_RE.test(v)) {
          const expanded = v.length === 4
            ? '#' + v[1] + v[1] + v[2] + v[2] + v[3] + v[3] : v.toLowerCase();
          setLight(expanded);
        } else {
          lightText.classList.add('is-invalid');
        }
      });
      lightClear.addEventListener('click', () => { setLight(''); lightText.value = ''; });
      const lightTokenBtn = attachTokenButton(lightText, lightSwatch);
      const lightRow = el('span', { class: 'be-container-color' },
                         [lightSwatch, lightText, lightTokenBtn, lightClear]);
      wrap.appendChild(lightRow);

      // Mode toggle [Same | Auto | Manual]
      const modeLbl = el('span', { class: 'be-color-dm-label muted smaller' },
                         ['Dark mode']);
      const modeToggle = el('div', { class: 'view-toggle be-color-dm-mode' });
      const modeBtns = {};
      ['same', 'auto', 'manual'].forEach(m => {
        const btn = el('button', {
          type: 'button',
          class: 'btn btn-sm' + (curMode === m ? ' active' : ''),
          'data-mode': m,
        }, [m === 'same' ? 'Same' : m === 'auto' ? 'Auto' : 'Manual']);
        btn.addEventListener('click', () => {
          curMode = m;
          Object.values(modeBtns).forEach(b => b.classList.toggle('active', b === btn));
          darkRow.hidden = m !== 'manual';
          autoRow.hidden = m !== 'auto';
          if (m === 'auto') updateAutoPreview();
          commitNotify();
        });
        modeBtns[m] = btn;
        modeToggle.appendChild(btn);
      });
      const modeRow = el('div', { class: 'be-color-dm-mode-row' },
                         [modeLbl, modeToggle]);
      wrap.appendChild(modeRow);

      // Manual dark swatch + hex + clear
      const darkSwatch = el('input', {
        type: 'color', value: curManualDark || '#e6e8f0',
      });
      const darkText = el('input', {
        type: 'text', class: 'be-container-color-text',
        maxlength: '7', spellcheck: 'false', autocomplete: 'off',
        placeholder: 'pick a dark-mode colour',
        value: curManualDark,
      });
      const darkClear = el('button', {
        type: 'button', class: 'btn btn-sm',
      }, ['Clear']);
      function setManualDark(v) {
        curManualDark = v;
        const swatchHex = _resolveSwatchHex(v);
        if (swatchHex) darkSwatch.value = swatchHex;
        darkText.classList.remove('is-invalid');
        commitNotify();
      }
      darkSwatch.addEventListener('input', () => { setManualDark(darkSwatch.value); darkText.value = darkSwatch.value; });
      darkText.addEventListener('input', () => {
        let v = (darkText.value || '').trim();
        if (!v) { setManualDark(''); return; }
        if (_TOKEN_RE.test(v)) { setManualDark(v); return; }
        if (!v.startsWith('#')) v = '#' + v;
        if (_HEX_RE.test(v)) {
          const expanded = v.length === 4
            ? '#' + v[1] + v[1] + v[2] + v[2] + v[3] + v[3] : v.toLowerCase();
          setManualDark(expanded);
        } else {
          darkText.classList.add('is-invalid');
        }
      });
      darkClear.addEventListener('click', () => { setManualDark(''); darkText.value = ''; });
      const darkTokenBtn = attachTokenButton(darkText, darkSwatch);
      const darkRow = el('span', { class: 'be-container-color be-color-dm-row' },
                         [darkSwatch, darkText, darkTokenBtn, darkClear]);
      darkRow.hidden = curMode !== 'manual';
      wrap.appendChild(darkRow);

      // Auto preview chip
      const autoChip = el('span', { class: 'be-color-dm-auto-preview' }, []);
      const autoSwatch = el('span', { class: 'be-color-dm-auto-swatch' });
      function updateAutoPreview() {
        const auto = deriveDarkMode(curLight);
        autoChip.textContent = auto || '(set a light colour first)';
        autoSwatch.style.background = auto || 'transparent';
        autoSwatch.style.opacity = auto ? '1' : '0.3';
      }
      const autoRow = el('div', { class: 'be-color-dm-auto-row muted small' },
                         [el('span', {}, ['Auto-derived: ']), autoSwatch, autoChip]);
      autoRow.hidden = curMode !== 'auto';
      if (curMode === 'auto') updateAutoPreview();
      wrap.appendChild(autoRow);

      return wrap;
    }

    // Shared typography editor — collapsible panel of Family / Size /
    // Weight / Color / Alignment / Line height that mutates `d` in
    // place and notifies on change. Used by heading / paragraph / list
    // blocks. Each control commits to `d[key]` directly so the parent
    // editor's serialise picks up the override on next save.
    function renderTypographyPanel(d) {
      const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
      const panel = el('details', { class: 'be-container-panel be-typo-panel', open: 'open' }, [
        el('summary', {}, ['Typography']),
      ]);
      const body = el('div', { class: 'be-container-panel-body' });

      function row(label, control, hint) {
        const r = el('div', { class: 'be-container-row' });
        r.appendChild(el('span', { class: 'be-container-row-lbl' }, [label]));
        r.appendChild(control);
        if (hint) r.appendChild(el('div', { class: 'be-container-row-hint muted smaller' }, [hint]));
        return r;
      }
      // Font family — pulls from window.tspFonts (populated by the
      // page edit template at boot from the server's frontend_fonts()
      // helper). Falls back to a "Theme default" only.
      const fonts = (window.tspFonts || []);
      const fontSel = el('select', {
        onchange: e => { d.font_family = e.target.value; notifyChange(); }
      }, [
        (function(){
          const o = el('option', { value: '' }, ['Theme default']);
          if (!d.font_family) o.selected = true;
          return o;
        })(),
        ...fonts.map(f => {
          const o = el('option', { value: f.stack || f.key }, [f.name]);
          if (d.font_family === (f.stack || f.key)) o.selected = true;
          return o;
        }),
      ]);
      body.appendChild(row('Font family', fontSel));

      // Font size — free-text CSS value, with placeholder showing
      // theme default. Accepts 1.25rem, 20px, etc.
      body.appendChild(row('Font size',
        el('input', { type: 'text',
          value: d.font_size || '', placeholder: 'inherit (e.g. 1.25rem, 20px)',
          oninput: e => { d.font_size = e.target.value; notifyChange(); }
        })));

      // Weight — preset toggle.
      const weightSel = el('select', {
        onchange: e => { d.font_weight = e.target.value; notifyChange(); }
      }, [['', 'Theme default'], ['400', '400 — Regular'], ['500', '500 — Medium'],
          ['600', '600 — Semibold'], ['700', '700 — Bold'], ['800', '800 — Extrabold']]
         .map(([v, lbl]) => {
        const o = el('option', { value: v }, [lbl]);
        if ((d.font_weight || '') === v) o.selected = true;
        return o;
      }));
      body.appendChild(row('Weight', weightSel));

      // Colour — light + dark-mode aware. Light value lives in
      // d.color; dark behaviour lives in d.color_dark_mode (same/auto/
      // manual) and d.color_dark (the manual hex when mode='manual'
      // OR the auto-derived hex when mode='auto', so the renderer
      // doesn't need to know about the mode — just emit color_dark
      // as the dark-mode CSS variable when non-empty).
      const colorWrap = colorPickerWithDarkMode({
        value: d.color || '',
        valueDark: d.color_dark || '',
        mode: d.color_dark_mode || 'same',
        placeholder: 'inherit',
        onChange: (light, dark, mode) => {
          d.color = light;
          d.color_dark = dark;
          d.color_dark_mode = mode;
          notifyChange();
        },
      });
      body.appendChild(row('Colour', colorWrap));

      // Alignment — toggle of Auto / Left / Center / Right / Justify.
      const alignTog = el('div', { class: 'view-toggle be-typo-align' });
      [['', 'Auto'], ['left', 'Left'], ['center', 'Center'],
       ['right', 'Right'], ['justify', 'Justify']].forEach(([v, lbl]) => {
        alignTog.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + ((d.align || '') === v ? ' active' : ''),
          'data-align': v,
        }, [lbl]));
      });
      alignTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-align]');
        if (!btn) return;
        d.align = btn.dataset.align;
        alignTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        notifyChange();
      });
      body.appendChild(row('Alignment', alignTog));

      // Line height — free-text CSS value, with placeholder.
      body.appendChild(row('Line height',
        el('input', { type: 'text',
          value: d.line_height || '', placeholder: 'inherit (e.g. 1.5, 28px)',
          oninput: e => { d.line_height = e.target.value; notifyChange(); }
        })));

      panel.appendChild(body);
      return panel;
    }

    // ── Image browser modal (lazy-created) ─────────────────────────
    // Shared across every Image block on the page — built on first
    // open via `openImageBrowser`. Fetches /tspro/files/images.json
    // and renders a thumbnail grid; tile click fires a one-shot
    // selection callback. Inline upload via /tspro/files/upload.
    function imageBrowserCsrf() {
      // Pull the page-edit form's CSRF token; falls back to a blank
      // string so an unconfigured environment still gets a clear
      // server-side 400 instead of a silent client-side crash.
      const inp = document.querySelector('input[name="csrf_token"]');
      return inp ? inp.value : '';
    }
    let _imgPicker = null;
    function ensureImageBrowserModal() {
      if (_imgPicker) return _imgPicker;
      const modal = document.createElement('div');
      modal.className = 'modal fe-image-picker-modal';
      modal.id = 'be-image-picker';
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
      modal.querySelectorAll('[data-close]').forEach(el =>
        el.addEventListener('click', () => closeImageBrowser()));
      const grid = modal.querySelector('[data-grid]');
      const empty = modal.querySelector('.be-image-picker-empty');
      const search = modal.querySelector('.be-image-picker-search');
      const status = modal.querySelector('.be-image-picker-status');
      const fileInput = modal.querySelector('input[type=file]');
      const drop = modal.querySelector('.be-image-picker-drop');

      let pendingPick = null;
      let allItems = [];

      function render(filter) {
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
          tile.innerHTML =
            '<span class="be-image-picker-thumb">' +
              '<img src="' + (it.url || '') + '" alt="" loading="lazy">' +
            '</span>' +
            '<span class="be-image-picker-name">' +
              (it.original_filename || '').replace(/[<>"&]/g, '') +
            '</span>';
          tile.addEventListener('click', () => {
            if (pendingPick) pendingPick(it.url);
            closeImageBrowser();
          });
          grid.appendChild(tile);
        });
      }

      async function reload(q) {
        status.textContent = 'Loading…';
        try {
          const r = await fetch('/tspro/files/images.json' +
            (q ? '?q=' + encodeURIComponent(q) : ''),
            { credentials: 'same-origin' });
          const data = await r.json();
          allItems = (data && data.items) || [];
          render(search.value);
          status.textContent = allItems.length + ' image' + (allItems.length === 1 ? '' : 's') + ' in library';
        } catch (err) {
          status.textContent = 'Failed to load images';
          console.warn('image picker load failed', err);
        }
      }

      function uploadFiles(files) {
        const arr = Array.from(files || []);
        if (!arr.length) return;
        const csrf = imageBrowserCsrf();
        let done = 0; const total = arr.length;
        let firstUploaded = null;
        status.textContent = `Uploading ${total} file${total === 1 ? '' : 's'}…`;
        Promise.all(arr.map(file => {
          const fd = new FormData();
          fd.append('file', file);
          fd.append('csrf_token', csrf);
          return fetch('/tspro/files/upload', {
            method: 'POST', body: fd, credentials: 'same-origin',
          }).then(r => r.json()).then(data => {
            done++;
            if (data && data.item && !firstUploaded) firstUploaded = data.item;
            return data && data.item;
          }).catch(err => { console.warn('upload failed', err); return null; });
        })).then(results => {
          status.textContent = `Uploaded ${done}/${total}`;
          // Auto-select the first uploaded file when the picker was
          // opened with a pending callback — the admin's intent was
          // "I want THIS image", so dropping a new one straight in
          // is the lowest-friction path.
          reload().then(() => {
            if (firstUploaded && pendingPick) {
              const url = '/pub/' + firstUploaded.original_filename;
              pendingPick(url);
              closeImageBrowser();
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
        searchT = setTimeout(() => render(search.value), 100);
      });

      _imgPicker = {
        modal,
        open(cb) {
          pendingPick = cb;
          search.value = '';
          modal.classList.add('open');
          modal.setAttribute('aria-hidden', 'false');
          document.body.style.overflow = 'hidden';
          reload();
          setTimeout(() => search.focus(), 30);
        },
        close() {
          pendingPick = null;
          modal.classList.remove('open');
          modal.setAttribute('aria-hidden', 'true');
          document.body.style.overflow = '';
        },
      };
      return _imgPicker;
    }
    function openImageBrowser(onPick) {
      ensureImageBrowserModal().open(onPick);
    }
    function closeImageBrowser() {
      if (_imgPicker) _imgPicker.close();
    }
    function uploadImageFile(file, onSrc) {
      // Inline upload from the image block's "Upload new" button —
      // skips the picker grid; uploads, then immediately sets the
      // block's src to the new file's public URL.
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      fd.append('csrf_token', imageBrowserCsrf());
      fetch('/tspro/files/upload', {
        method: 'POST', body: fd, credentials: 'same-origin',
      }).then(r => r.json()).then(data => {
        if (data && data.item && data.item.original_filename) {
          onSrc('/pub/' + data.item.original_filename);
        }
      }).catch(err => console.warn('upload failed', err));
    }

    function renderBlockBody(b) {
      const d = b.data;
      if (b.type === 'paragraph') {
        return el('div', { class: 'be-body' }, [
          ta(d.md, v => d.md = v, { rows: 6,
            placeholder: 'Write your text here. Markdown is supported:\n  **bold**, *italic*, [link](https://example.com)\n  # Heading, > quote, - list, ```code```\nBlank lines start a new paragraph.' }),
          renderTypographyPanel(d),
        ]);
      }
      if (b.type === 'heading') {
        const lvlSel = el('select', {
          onchange: e => { d.level = parseInt(e.target.value, 10); notifyChange(); }
        }, [2,3,4,5,6].map(n => {
          const o = el('option', { value: n }, ['H'+n]);
          if ((d.level||3) === n) o.selected = true;
          return o;
        }));
        // Separate labeled rows for level + heading text. The previous
        // shape (select + input on a single .be-row) clashed with the
        // .be-body width:100% rule, squeezing the text input to invisibility.
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Level', lvlSel]),
          el('label', {}, ['Heading text',
            el('input', {
              type: 'text', placeholder: 'Heading text',
              value: d.text || '',
              oninput: e => { d.text = e.target.value; notifyChange(); }
            }),
          ]),
          renderTypographyPanel(d),
        ]);
      }
      if (b.type === 'image') {
        const alignTog = el('div', { class: 'view-toggle be-typo-align' });
        [['left', 'Left'], ['center', 'Center'], ['right', 'Right']].forEach(([v, lbl]) => {
          alignTog.appendChild(el('button', {
            type: 'button',
            class: 'btn btn-sm' + ((d.align || 'center') === v ? ' active' : ''),
            'data-align': v,
          }, [lbl]));
        });
        alignTog.addEventListener('click', e => {
          const btn = e.target.closest('button[data-align]');
          if (!btn) return;
          d.align = btn.dataset.align;
          alignTog.querySelectorAll('button').forEach(x =>
            x.classList.toggle('active', x === btn));
          notifyChange();
        });
        const widthOut = el('output', {}, [(d.max_width_pct == null ? 100 : d.max_width_pct) + '%']);
        const widthSlider = el('input', {
          type: 'range', min: '20', max: '100', step: '5',
          value: (d.max_width_pct == null ? 100 : d.max_width_pct),
          oninput: e => {
            d.max_width_pct = parseInt(e.target.value, 10) || 100;
            widthOut.textContent = d.max_width_pct + '%';
            notifyChange();
          },
        });
        // Corner roundness — px slider 0..50. The renderer mirrors the
        // value into `border-radius: <n>px` on the <img>. 0 = sharp.
        const radiusOut = el('output', {},
          [(d.border_radius == null ? 0 : d.border_radius) + 'px']);
        const radiusSlider = el('input', {
          type: 'range', min: '0', max: '50', step: '1',
          value: (d.border_radius == null ? 0 : d.border_radius),
          oninput: e => {
            d.border_radius = parseInt(e.target.value, 10) || 0;
            radiusOut.textContent = d.border_radius + 'px';
            previewImg.style.borderRadius = d.border_radius + 'px';
            notifyChange();
          },
        });
        // Box-shadow preset picker. Renderer maps the chosen key to a
        // pre-baked shadow recipe; '' (none) suppresses the rule.
        const SHADOW_OPTS = [
          ['', 'None'],
          ['sm', 'Subtle'],
          ['md', 'Soft'],
          ['lg', 'Pronounced'],
          ['xl', 'Dramatic'],
        ];
        const shadowSel = el('select', {
          onchange: e => {
            d.shadow = e.target.value;
            applyShadowPreview();
            notifyChange();
          },
        }, SHADOW_OPTS.map(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.shadow || '') === v) o.selected = true;
          return o;
        }));
        // Live shadow preview on the in-modal preview image. The
        // recipes here MUST match the public-side CSS in
        // `_blocks.html` so the modal preview reflects what the
        // saved block will actually render as.
        const SHADOW_RECIPES = {
          sm: '0 1px 2px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.10)',
          md: '0 4px 6px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.06)',
          lg: '0 10px 15px rgba(0, 0, 0, 0.10), 0 4px 6px rgba(0, 0, 0, 0.08)',
          xl: '0 20px 25px rgba(0, 0, 0, 0.15), 0 10px 10px rgba(0, 0, 0, 0.06)',
        };
        function applyShadowPreview() {
          previewImg.style.boxShadow = SHADOW_RECIPES[d.shadow] || '';
        }
        // Live preview img — refreshed when src changes via Browse / Upload.
        const previewImg = el('img', {
          class: 'be-preview',
          src: d.src || '',
          style: d.src ? '' : 'display: none',
        });
        // Apply the saved radius + shadow to the preview as soon as
        // the img element exists so the modal renders the current
        // configuration on open (not just after the admin nudges a
        // control).
        previewImg.style.borderRadius = (d.border_radius || 0) + 'px';
        applyShadowPreview();
        function setSrc(src) {
          d.src = src || '';
          srcInput.value = d.src;
          previewImg.src = d.src;
          previewImg.style.display = d.src ? '' : 'none';
          notifyChange();
        }
        const srcInput = el('input', { type: 'text', value: d.src || '',
          placeholder: '/pub/<filename> or external URL',
          oninput: e => { d.src = e.target.value;
                          previewImg.src = d.src;
                          previewImg.style.display = d.src ? '' : 'none';
                          notifyChange(); } });
        const browseBtn = el('button', {
          type: 'button', class: 'btn btn-sm be-image-browse',
          onclick: () => openImageBrowser(setSrc),
        }, ['📁 Browse library']);
        const uploadInput = el('input', {
          type: 'file', accept: 'image/*',
          style: 'display: none',
          onchange: e => uploadImageFile(e.target.files[0], setSrc),
        });
        const uploadBtn = el('button', {
          type: 'button', class: 'btn btn-sm be-image-upload',
          onclick: () => uploadInput.click(),
        }, ['⬆ Upload new']);
        const sourceRow = el('div', { class: 'be-image-source-row' }, [
          browseBtn, uploadBtn, uploadInput,
        ]);
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Image source', srcInput]),
          sourceRow,
          el('label', {}, ['Alt text',
            el('input', { type: 'text', value: d.alt || '',
              oninput: e => { d.alt = e.target.value; notifyChange(); } })]),
          el('label', {}, ['Caption',
            el('input', { type: 'text', value: d.caption || '',
              oninput: e => { d.caption = e.target.value; notifyChange(); } })]),
          el('label', {}, [el('span', {}, ['Width ', widthOut]), widthSlider]),
          el('label', {}, ['Alignment', alignTog]),
          el('label', {}, [el('span', {}, ['Corner roundness ', radiusOut]), radiusSlider]),
          el('label', {}, ['Drop shadow', shadowSel]),
          el('label', {}, ['Caption colour',
            el('input', { type: 'text', class: 'be-container-color-text',
              value: d.caption_color || '', placeholder: 'inherit (e.g. #6b7280)',
              maxlength: '7', spellcheck: 'false', autocomplete: 'off',
              oninput: e => { d.caption_color = e.target.value; notifyChange(); } })]),
          el('label', {}, ['Caption size',
            el('input', { type: 'text',
              value: d.caption_size || '', placeholder: 'inherit (e.g. 0.875rem)',
              oninput: e => { d.caption_size = e.target.value; notifyChange(); } })]),
          previewImg,
        ]);
      }
      if (b.type === 'video') {
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Video URL or /uploads/…',
            el('input', { type: 'text', value: d.src || '', oninput: e => d.src = e.target.value })]),
          el('label', {}, ['Poster (optional)',
            el('input', { type: 'text', value: d.poster || '', oninput: e => d.poster = e.target.value })]),
        ]);
      }
      if (b.type === 'lottie') {
        return renderLottieBody(b);
      }
      if (b.type === 'intergroup_member') {
        return renderIntergroupMemberBody(b);
      }
      if (b.type === 'intergroup_member_roster') {
        return renderIntergroupRosterBody(b);
      }
      if (b.type === 'library') {
        return renderLibraryBody(b);
      }
      if (b.type === 'blog_list') {
        return renderBlogListBody(b);
      }
      if (b.type === 'code') {
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Language',
            el('input', { type: 'text', value: d.lang || '', placeholder: 'e.g. python', oninput: e => d.lang = e.target.value })]),
          ta(d.code, v => d.code = v, { rows: 8, placeholder: 'Code…', attrs: { style: 'font-family: ui-monospace, Menlo, monospace;' } }),
        ]);
      }
      if (b.type === 'callout') {
        const vSel = el('select', { onchange: e => d.variant = e.target.value },
          ['info','warn','danger','success'].map(v => {
            const o = el('option', { value: v }, [v]);
            if ((d.variant||'info') === v) o.selected = true;
            return o;
          }));
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Variant', vSel]),
          el('label', {}, ['Title',
            el('input', { type: 'text', value: d.title || '', oninput: e => d.title = e.target.value })]),
          ta(d.md, v => d.md = v, { rows: 4, placeholder: 'Markdown body…' }),
        ]);
      }
      if (b.type === 'list') {
        const body = el('div', { class: 'be-body' });
        const orderedChk = el('label', { class: 'be-row' }, [
          el('input', {
            type: 'checkbox', checked: d.ordered ? 'checked' : null,
            onchange: e => { d.ordered = e.target.checked; notifyChange(); }
          }),
          el('span', {}, ['Ordered (numbered)'])
        ]);
        body.appendChild(orderedChk);
        // Display style — picks the overall presentation. 'plain'
        // (default) uses a standard ul/ol with the marker style
        // dropdown below; the others render the items as a richer
        // composition (numbered cards, ✓ checklist, → arrow list,
        // inline pill chips). The marker style is hidden when a
        // non-plain display style is selected since it doesn't
        // apply.
        const displayLabel = el('label', {}, ['Display style']);
        const displaySel = el('select', {}, [
          ['', 'Plain (bulleted / numbered)'],
          ['cards', 'Numbered cards'],
          ['checklist', 'Checklist (✓)'],
          ['arrows', 'Arrow list (→)'],
          ['pills', 'Inline pills'],
        ].map(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.display_style || '') === v) o.selected = true;
          return o;
        }));
        displayLabel.appendChild(displaySel);
        body.appendChild(displayLabel);
        // Bullet style — applied as CSS list-style-type. Only
        // meaningful when display_style is empty (plain mode).
        const bulletLabel = el('label', {}, ['Marker style']);
        const bulletSel = el('select', {
          onchange: e => { d.bullet_style = e.target.value; notifyChange(); }
        }, [['', 'Theme default'], ['disc', 'Disc •'], ['circle', 'Circle ◦'],
            ['square', 'Square ▪'], ['decimal', 'Numbered 1.'],
            ['lower-alpha', 'Lower-alpha a.'], ['upper-roman', 'Upper-roman I.']]
            .map(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.bullet_style || '') === v) o.selected = true;
          return o;
        }));
        bulletLabel.appendChild(bulletSel);
        bulletLabel.hidden = !!(d.display_style || '');
        body.appendChild(bulletLabel);

        // ── Card-style panel (only relevant when display_style='cards')
        // Mirrors the container settings panel UX — collapsible
        // <details>, opened by default per the always-expand rule,
        // showing only when the admin has selected the Numbered
        // cards display. Each control reads from / writes to a
        // `card_*` field on the list block; the renderer applies
        // them as inline styles + CSS custom properties on the
        // outer `.fe-pp-steps` and per-item `.fe-pp-step` elements.
        const cardPanel = el('details', {
          class: 'be-container-panel be-list-card-panel', open: 'open',
        }, [el('summary', {}, ['Card style'])]);
        const cardBody = el('div', { class: 'be-container-panel-body' });
        function cardRow(label, control, hint) {
          const r = el('div', { class: 'be-container-row' });
          r.appendChild(el('span', { class: 'be-container-row-lbl' }, [label]));
          r.appendChild(control);
          if (hint) r.appendChild(el('div', { class: 'be-container-row-hint muted smaller' }, [hint]));
          return r;
        }
        cardBody.appendChild(cardRow('Background',
          colorPickerWithDarkMode({
            value: d.card_bg || '', valueDark: d.card_bg_dark || '',
            mode: d.card_bg_dark_mode || 'same',
            placeholder: 'inherit theme',
            onChange: (light, dark, mode) => {
              d.card_bg = light; d.card_bg_dark = dark;
              d.card_bg_dark_mode = mode; notifyChange();
            },
          })));
        cardBody.appendChild(cardRow('Border colour',
          colorPickerWithDarkMode({
            value: d.card_border_color || '',
            valueDark: d.card_border_color_dark || '',
            mode: d.card_border_color_dark_mode || 'same',
            placeholder: 'theme accent',
            onChange: (light, dark, mode) => {
              d.card_border_color = light; d.card_border_color_dark = dark;
              d.card_border_color_dark_mode = mode; notifyChange();
            },
          })));
        cardBody.appendChild(cardRow('Border radius',
          el('input', { type: 'text', value: d.card_border_radius || '',
            placeholder: '16px',
            oninput: e => { d.card_border_radius = e.target.value; notifyChange(); } }),
          'CSS length, e.g. 16px, 0.5rem.'));
        cardBody.appendChild(cardRow('Padding',
          el('input', { type: 'text', value: d.card_padding || '',
            placeholder: '18px 22px',
            oninput: e => { d.card_padding = e.target.value; notifyChange(); } }),
          'CSS shorthand: 1rem, 18px 22px, 8px 12px 14px 12px.'));
        cardBody.appendChild(cardRow('Gap between cards',
          el('input', { type: 'text', value: d.card_gap || '',
            placeholder: '14px',
            oninput: e => { d.card_gap = e.target.value; notifyChange(); } })));
        cardBody.appendChild(cardRow('Shadow',
          (function () {
            const sel = el('select', {
              onchange: e => { d.card_shadow = e.target.value; notifyChange(); },
            });
            [['', 'Inherit (none)'], ['none', 'None'], ['sm', 'Subtle'],
             ['md', 'Medium'], ['lg', 'Large'], ['xl', 'Dramatic']]
              .forEach(([v, lbl]) => {
                const o = el('option', { value: v }, [lbl]);
                if ((d.card_shadow || '') === v) o.selected = true;
                sel.appendChild(o);
              });
            return sel;
          })()));
        cardBody.appendChild(cardRow('Hover lift',
          (function () {
            const wrap = el('label', { class: 'be-container-checkbox' });
            const cb = el('input', {
              type: 'checkbox',
              checked: d.card_hover_lift !== false ? 'checked' : null,
              onchange: e => { d.card_hover_lift = e.target.checked; notifyChange(); },
            });
            wrap.appendChild(cb);
            wrap.appendChild(el('span', {},
              ['Lift + shadow on hover']));
            return wrap;
          })()));
        cardBody.appendChild(cardRow('Number background',
          colorPickerWithDarkMode({
            value: d.card_num_bg || '', valueDark: d.card_num_bg_dark || '',
            mode: d.card_num_bg_dark_mode || 'same',
            placeholder: 'theme primary',
            onChange: (light, dark, mode) => {
              d.card_num_bg = light; d.card_num_bg_dark = dark;
              d.card_num_bg_dark_mode = mode; notifyChange();
            },
          })));
        cardBody.appendChild(cardRow('Number text colour',
          colorPickerWithDarkMode({
            value: d.card_num_color || '', valueDark: d.card_num_color_dark || '',
            mode: d.card_num_color_dark_mode || 'same',
            placeholder: 'inherit',
            onChange: (light, dark, mode) => {
              d.card_num_color = light; d.card_num_color_dark = dark;
              d.card_num_color_dark_mode = mode; notifyChange();
            },
          })));
        cardPanel.appendChild(cardBody);
        cardPanel.hidden = (d.display_style || '') !== 'cards';
        body.appendChild(cardPanel);

        // Wire the display-style change to also toggle marker-style
        // + card-style panel visibility.
        displaySel.addEventListener('change', e => {
          d.display_style = e.target.value;
          bulletLabel.hidden = !!(d.display_style || '');
          cardPanel.hidden = (d.display_style || '') !== 'cards';
          notifyChange();
        });
        const items = el('div', { class: 'be-list-items' });
        (d.items || []).forEach((it, ii) => {
          const row = el('div', { class: 'be-row' }, [
            el('input', {
              type: 'text', value: it,
              oninput: e => { d.items[ii] = e.target.value; notifyChange(); },
              placeholder: 'List item (supports markdown — e.g. [link](https://example.com))'
            }),
            el('button', { type: 'button', class: 'icon-btn', title: 'Remove',
              onclick: () => { d.items.splice(ii,1); render(); notifyChange(); } }, [iconEl('x')]),
          ]);
          items.appendChild(row);
        });
        body.appendChild(items);
        body.appendChild(el('button', {
          type: 'button', class: 'btn btn-sm',
          onclick: () => { d.items = d.items || []; d.items.push(''); render(); notifyChange(); }
        }, ['+ Add item']));
        body.appendChild(renderTypographyPanel(d));
        return body;
      }
      if (b.type === 'separator') {
        return el('div', { class: 'be-body muted small' }, ['Horizontal divider (no options)']);
      }
      if (b.type === 'toc_sidebar') {
        // Wiki sidebar — title + which heading levels to include +
        // sticky toggle + sticky offset. Public render walks the page's
        // heading blocks and emits a list of jump-links matching these
        // settings, so editing the title here updates the live page.
        const lvlSel = el('select', {
          onchange: e => { d.max_level = parseInt(e.target.value, 10); notifyChange(); }
        }, [2, 3, 4, 5, 6].map(n => {
          const o = el('option', { value: n }, ['H' + n]);
          if ((d.max_level || 3) === n) o.selected = true;
          return o;
        }));
        const stickyChk = el('input', {
          type: 'checkbox', checked: d.sticky ? 'checked' : null,
          onchange: e => { d.sticky = e.target.checked; notifyChange(); }
        });
        return el('div', { class: 'be-body' }, [
          el('label', {}, ['Sidebar title',
            el('input', { type: 'text', value: d.title || '',
              placeholder: 'On this page',
              oninput: e => d.title = e.target.value })]),
          el('label', {}, ['Include headings up to',
            lvlSel,
            el('small', { class: 'muted' }, [
              'Sidebar lists every <h2> (and deeper, up to this level) found in heading blocks across the page.'
            ])]),
          el('label', { class: 'be-row' }, [stickyChk,
            el('span', {}, ['Stick to viewport on scroll'])]),
          el('label', {}, ['Sticky top offset (px)',
            el('input', { type: 'number', min: '0', max: '400', step: '4',
              value: (d.sticky_offset == null ? 96 : d.sticky_offset),
              oninput: e => {
                const n = parseInt(e.target.value, 10);
                d.sticky_offset = isNaN(n) ? 0 : Math.max(0, Math.min(400, n));
                notifyChange();
              } })]),
        ]);
      }
      if (b.type === 'icon') {
        return renderIconBody(b);
      }
      if (b.type === 'button') {
        return renderButtonBody(b);
      }
      if (b.type === 'hero') {
        return renderHeroBody(b);
      }
      if (b.type === 'meetings') {
        return renderMeetingsBody(b);
      }
      if (b.type === 'events') {
        return renderEventsBody(b);
      }
      if (b.type === 'container') {
        return renderContainerBody(b);
      }
      return el('div', { class: 'be-body' }, ['Unknown block type: ' + b.type]);
    }

    // ── Icon block ────────────────────────────────────────────────
    // Wires into the shared icon-picker-modal (the same modal that
    // powers nav-link / footer / homepage icons): the picker writes to
    // the hidden `name`/`size` inputs by ID and dispatches input events,
    // which our oninput handlers catch to mirror the values onto
    // `b.data` and refresh the live preview.
    function renderIconBody(b) {
      const d = b.data;
      // Make sure each colour-mode field has a sane default so the
      // picker UI shows a coherent state on first open.
      if (d.color_dark_mode == null) d.color_dark_mode = 'same';
      if (d.size == null || d.size === '') d.size = 32;
      if (!d.align) d.align = 'center';
      const idBase = 'be-icon-' + (b.id || uid());
      const nameId = idBase + '-name';
      const sizeId = idBase + '-size';
      const colorSinkId = idBase + '-color-sink';

      // Live VISUAL preview — fetches the Lucide catalog (cached at
      // module level so subsequent icon blocks reuse the same data),
      // looks up the picked icon's SVG paths, and renders them inline
      // at the chosen size + colour. Custom icons (`custom:<id>`) point
      // at /pub/icon/<id>. Size is applied as `font-size` on the wrapper
      // because `.icon` is sized in 1em. Light colour is applied as a
      // direct CSS `color`; dark-mode colour is intentionally NOT shown
      // here — admins flip the page theme to see the dark variant in
      // place. Alignment + URL are styling concerns of the rendered
      // page, not the preview.
      const SVG_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
      const visualEl = el('div', { class: 'be-icon-visual' });
      const visualMeta = el('div', { class: 'be-icon-visual-meta muted smaller' });
      const previewCard = el('div', { class: 'be-icon-preview-card' },
        [visualEl, visualMeta]);

      function renderVisualPreview() {
        const name = d.name || '';
        const px = parseInt(d.size, 10) || 32;
        // Wrapper styles drive the icon size (font-size cascades into
        // `.icon { width: 1em; height: 1em }`) and colour. Strip prior
        // inline style so toggling Clear on the colour picker actually
        // resets to the default ink colour.
        const styles = ['font-size: ' + px + 'px'];
        if (d.color) styles.push('color: ' + d.color);
        visualEl.setAttribute('style', styles.join('; '));
        visualEl.innerHTML = '';
        if (!name) {
          visualEl.classList.add('is-empty');
          visualEl.textContent = 'Pick an icon to preview';
          visualMeta.textContent = (d.size || 32) + 'px · no icon';
          return;
        }
        visualEl.classList.remove('is-empty');
        visualMeta.textContent = name + ' · ' + px + 'px' +
          (d.color ? ' · ' + d.color : '');
        if (name.indexOf('custom:') === 0) {
          // Custom icon — server-side route serves the SVG/PNG bytes.
          // Use width/height of 1em so it follows font-size like the
          // Lucide SVGs do.
          const cid = name.split(':', 2)[1] || '';
          const img = document.createElement('img');
          img.className = 'icon icon-custom';
          img.setAttribute('alt', '');
          img.src = '/pub/icon/' + encodeURIComponent(cid);
          visualEl.appendChild(img);
          return;
        }
        // Lucide — load the catalog if not yet loaded, then look up
        // the matching paths. While the fetch is in flight, show the
        // ref name; if not found at all, fall through to an "unknown"
        // hint so the admin notices a stale icon ref.
        loadBlockEditorIconCatalog().then(catalog => {
          if ((d.name || '') !== name) return;  // stale callback
          const paths = findIconPathsInCatalog(catalog, name);
          if (paths) {
            visualEl.innerHTML = '<svg class="icon" ' + SVG_ATTRS + '>' + paths + '</svg>';
          } else {
            visualEl.classList.add('is-empty');
            visualEl.textContent = 'Unknown icon: ' + name;
          }
        });
      }

      const nameInput = el('input', {
        type: 'hidden', id: nameId, value: d.name || '',
        oninput: e => { d.name = e.target.value || ''; renderVisualPreview(); notifyChange(); },
      });
      const sizeInput = el('input', {
        type: 'hidden', id: sizeId, value: d.size == null ? '' : String(d.size),
        oninput: e => {
          const n = parseInt(e.target.value, 10);
          d.size = isNaN(n) ? 32 : Math.max(8, Math.min(256, n));
          renderVisualPreview(); notifyChange();
        },
      });
      // Sink for the picker's color-target — required by the picker
      // even though we ignore its value (block colour is driven by
      // the dark-mode picker further down).
      const colorSink = el('input', { type: 'hidden', id: colorSinkId, value: '' });

      const trigger = el('button', {
        type: 'button', class: 'btn icon-picker-trigger be-icon-picker-trigger',
        'data-open-icon-picker': '',
        'data-icon-target': '#' + nameId,
        'data-color-target': '#' + colorSinkId,
        'data-size-target': '#' + sizeId,
      }, ['Pick an icon…']);

      // Manual size override (slider) — separate from the modal's
      // size slider so the admin can tweak it after closing the
      // picker without re-opening it. Updates the same hidden input.
      const sizeOut = el('output', {}, [(d.size || 32) + 'px']);
      const sizeSlider = el('input', {
        type: 'range', min: '8', max: '256', step: '1',
        value: String(d.size || 32),
        oninput: e => {
          const n = parseInt(e.target.value, 10);
          d.size = isNaN(n) ? 32 : Math.max(8, Math.min(256, n));
          sizeOut.textContent = d.size + 'px';
          sizeInput.value = String(d.size);
          renderVisualPreview();
          notifyChange();
        },
      });

      // Alignment toggle (left / center / right) mirrors the image
      // block's pattern.
      const alignTog = el('div', { class: 'view-toggle be-typo-align' });
      [['left', 'Left'], ['center', 'Center'], ['right', 'Right']].forEach(([v, lbl]) => {
        alignTog.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + ((d.align || 'center') === v ? ' active' : ''),
          'data-align': v,
        }, [lbl]));
      });
      alignTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-align]');
        if (!btn) return;
        d.align = btn.dataset.align;
        alignTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        notifyChange();
      });

      const colorWrap = colorPickerWithDarkMode({
        value: d.color || '',
        valueDark: d.color_dark || '',
        mode: d.color_dark_mode || 'same',
        onChange: (v, dark, mode) => {
          d.color = v;
          d.color_dark = dark;
          d.color_dark_mode = mode;
          renderVisualPreview();
          notifyChange();
        },
      });

      // Optional click-through link.
      const urlInput = el('input', {
        type: 'text', value: d.url || '',
        placeholder: 'https://… (optional)',
        oninput: e => { d.url = e.target.value || ''; notifyChange(); },
      });
      const newTabChk = el('input', {
        type: 'checkbox', checked: d.new_tab ? 'checked' : null,
        onchange: e => { d.new_tab = e.target.checked; notifyChange(); },
      });

      // Kick off the initial render — for an existing block this
      // populates the preview with the stored icon at the stored
      // size + colour; for a fresh block it shows the empty state.
      renderVisualPreview();

      return el('div', { class: 'be-body' }, [
        el('label', {}, ['Icon', trigger]),
        nameInput, sizeInput, colorSink,
        previewCard,
        el('label', {}, [el('span', {}, ['Size ', sizeOut]), sizeSlider]),
        el('label', {}, ['Alignment', alignTog]),
        el('label', {}, ['Colour', colorWrap]),
        el('label', {}, ['Link URL', urlInput]),
        el('label', { class: 'be-row' }, [newTabChk,
          el('span', {}, ['Open link in new tab'])]),
      ]);
    }

    // ── Lottie block ──────────────────────────────────────────────
    // Settings UI for an embedded Lottie animation. Provides a URL
    // input + Upload button (the same /tspro/files/upload endpoint the
    // image block uses, accepting JSON), the standard alignment + width
    // controls, plus loop / autoplay / speed knobs.
    //
    // Live preview: lottie-web is loaded on-demand on first lottie-block
    // open; the preview stage itself is mounted into the modal so admins
    // see the actual animation before saving.
    let _lottieEditorLoader = null;
    function ensureLottieEditorLib() {
      if (window.lottie) return Promise.resolve(window.lottie);
      if (_lottieEditorLoader) return _lottieEditorLoader;
      _lottieEditorLoader = new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        // The page editor lives under the admin tree, so the asset
        // resolves relative to /static — mirroring the URL the public
        // page template uses via url_for. Hardcoded path is fine here:
        // both the editor template and frontend page template reference
        // the same vendored file, and the vendor dir doesn't move.
        s.src = '/static/vendor/lottie/lottie.min.js';
        s.async = true;
        s.onload = function () { resolve(window.lottie); };
        s.onerror = function () { reject(new Error('lottie load failed')); };
        document.head.appendChild(s);
      });
      return _lottieEditorLoader;
    }

    function renderLottieBody(b) {
      const d = b.data;
      // Defensive defaults — older blocks saved before these fields
      // existed get sensible values without forcing a migration.
      if (d.loop == null) d.loop = true;
      if (d.autoplay == null) d.autoplay = true;
      if (d.speed == null || d.speed === '') d.speed = 1;
      if (d.max_width_pct == null) d.max_width_pct = 100;
      if (!d.align) d.align = 'center';
      if (!d.renderer) d.renderer = 'svg';
      if (!d.playback) d.playback = 'auto';

      // Live preview — the stage where lottie-web mounts the SVG.
      // Recreated on every src/render-option change so we don't have to
      // reach into lottie-web's instance to update the renderer mid-flight.
      const stage = el('div', { class: 'be-lottie-stage' });
      const meta = el('div', { class: 'muted smaller be-lottie-meta' },
        ['Pick a Lottie JSON to preview']);
      let _anim = null;
      let _hoverHandlers = null;
      function teardownAnim() {
        if (_hoverHandlers) {
          stage.removeEventListener('mouseenter', _hoverHandlers.enter);
          stage.removeEventListener('mouseleave', _hoverHandlers.leave);
          _hoverHandlers = null;
        }
        if (_anim) { try { _anim.destroy(); } catch (e) { /* noop */ } }
        _anim = null;
        // Reset to fallback aspect-ratio so a freshly-loaded animation
        // re-stamps the var on its own DOMLoaded event.
        stage.style.removeProperty('--lottie-ratio');
        stage.innerHTML = '';
      }
      function attachHoverPreview(stageEl, anim) {
        var watcher = null;
        function clearWatcher() {
          if (watcher) {
            anim.removeEventListener('enterFrame', watcher);
            watcher = null;
          }
        }
        function enter() {
          clearWatcher();
          anim.setDirection(1); anim.play();
        }
        function leave() {
          clearWatcher();
          anim.setDirection(-1);
          watcher = function () {
            if (anim.currentFrame <= 0.5) {
              clearWatcher();
              anim.goToAndStop(0, true);
            }
          };
          anim.addEventListener('enterFrame', watcher);
          anim.play();
        }
        stageEl.addEventListener('mouseenter', enter);
        stageEl.addEventListener('mouseleave', leave);
        return { enter: enter, leave: leave };
      }
      function renderPreview() {
        teardownAnim();
        const src = (d.src || '').trim();
        if (!src) {
          meta.textContent = 'Pick a Lottie JSON to preview';
          stage.classList.add('is-empty');
          stage.textContent = 'No animation yet';
          return;
        }
        stage.classList.remove('is-empty');
        stage.textContent = '';
        const isHover = d.playback === 'hover';
        meta.textContent = src + ' · ' + (d.renderer || 'svg') +
          ' · ' + (isHover ? 'hover-play' : (d.autoplay ? 'autoplay' : 'manual')) +
          ' · ' + (d.loop ? 'loop' : 'no loop') +
          ' · ' + (d.speed || 1) + 'x';
        ensureLottieEditorLib().then(function (lottie) {
          if ((d.src || '').trim() !== src) return;  // stale callback
          _anim = lottie.loadAnimation({
            container: stage,
            renderer: d.renderer || 'svg',
            loop: !!d.loop,
            autoplay: !isHover && !!d.autoplay,
            path: src,
          });
          var sp = parseFloat(d.speed);
          if (!isNaN(sp) && sp > 0) _anim.setSpeed(sp);
          // Stamp aspect-ratio onto the stage so the preview matches the
          // animation's intrinsic shape (mirrors the public init script).
          _anim.addEventListener('DOMLoaded', function () {
            var ad = _anim && _anim.animationData;
            if (ad && ad.w && ad.h) {
              stage.style.setProperty('--lottie-ratio', ad.w + ' / ' + ad.h);
            }
            if (isHover) _anim.goToAndStop(0, true);
          });
          if (isHover) _hoverHandlers = attachHoverPreview(stage, _anim);
        }).catch(function (err) {
          stage.classList.add('is-empty');
          meta.textContent = 'Failed to load lottie-web: ' + (err.message || err);
        });
      }

      function setSrc(src) {
        d.src = src || '';
        srcInput.value = d.src;
        renderPreview();
        notifyChange();
      }

      const srcInput = el('input', {
        type: 'text', value: d.src || '',
        placeholder: '/pub/<filename>.json or external URL',
        oninput: e => { d.src = e.target.value; renderPreview(); notifyChange(); },
      });
      const uploadInput = el('input', {
        type: 'file', accept: '.json,.lottie,application/json',
        style: 'display: none',
        onchange: e => uploadLottieFile(e.target.files[0], setSrc),
      });
      const uploadBtn = el('button', {
        type: 'button', class: 'btn btn-sm be-image-upload',
        onclick: () => uploadInput.click(),
      }, ['⬆ Upload .json']);
      const sourceRow = el('div', { class: 'be-image-source-row' },
        [uploadBtn, uploadInput]);

      // Width slider mirrors the image block.
      const widthOut = el('output', {}, [(d.max_width_pct || 100) + '%']);
      const widthSlider = el('input', {
        type: 'range', min: '20', max: '100', step: '5',
        value: (d.max_width_pct || 100),
        oninput: e => {
          d.max_width_pct = parseInt(e.target.value, 10) || 100;
          widthOut.textContent = d.max_width_pct + '%';
          notifyChange();
        },
      });

      // Alignment toggle — same pattern as the image / icon blocks.
      const alignTog = el('div', { class: 'view-toggle be-typo-align' });
      [['left', 'Left'], ['center', 'Center'], ['right', 'Right']].forEach(([v, lbl]) => {
        alignTog.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + ((d.align || 'center') === v ? ' active' : ''),
          'data-align': v,
        }, [lbl]));
      });
      alignTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-align]');
        if (!btn) return;
        d.align = btn.dataset.align;
        alignTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        notifyChange();
      });

      // Playback mode — `auto` honours autoplay+loop directly; `hover`
      // parks the animation at frame 0 and plays forward only while
      // hovered, gracefully reversing back to frame 0 on leave. The
      // autoplay checkbox is hidden in hover mode since it's implicit.
      const playbackSel = el('select', {
        onchange: e => {
          d.playback = e.target.value;
          autoplayLabel.hidden = d.playback === 'hover';
          renderPreview(); notifyChange();
        },
      }, [['auto', 'Autoplay'], ['hover', 'Play on hover (reverse on leave)']]
        .map(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.playback || 'auto') === v) o.selected = true;
          return o;
        }));

      // Loop + autoplay checkboxes.
      const loopChk = el('input', {
        type: 'checkbox', checked: d.loop ? 'checked' : null,
        onchange: e => { d.loop = e.target.checked; renderPreview(); notifyChange(); },
      });
      const autoplayChk = el('input', {
        type: 'checkbox', checked: d.autoplay ? 'checked' : null,
        onchange: e => { d.autoplay = e.target.checked; renderPreview(); notifyChange(); },
      });
      const autoplayLabel = el('label', { class: 'be-row' },
        [autoplayChk, el('span', {}, ['Autoplay'])]);
      autoplayLabel.hidden = d.playback === 'hover';

      // Speed slider — 0.25x..3x in 0.25 steps. Output reads back the
      // current multiplier so admins can dial in slow / fast.
      const speedOut = el('output', {}, [(d.speed || 1) + 'x']);
      const speedSlider = el('input', {
        type: 'range', min: '0.25', max: '3', step: '0.25',
        value: String(d.speed || 1),
        oninput: e => {
          d.speed = parseFloat(e.target.value) || 1;
          speedOut.textContent = d.speed + 'x';
          if (_anim) _anim.setSpeed(d.speed);
          notifyChange();
        },
      });

      // Renderer toggle — svg (sharp, default) vs canvas (faster for
      // heavy animations). Changing the renderer rebuilds the preview.
      const rendererSel = el('select', {
        onchange: e => { d.renderer = e.target.value; renderPreview(); notifyChange(); },
      }, [['svg', 'SVG (sharp, default)'], ['canvas', 'Canvas (faster for heavy animations)']]
        .map(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.renderer || 'svg') === v) o.selected = true;
          return o;
        }));

      // Background colour — most lottie animations are transparent;
      // this paints the figure behind the stage so admins can sit a
      // light animation on a dark backing or vice versa.
      const bgInput = el('input', {
        type: 'text', class: 'be-container-color-text',
        value: d.bg_color || '', placeholder: 'transparent (e.g. #f8fafc)',
        maxlength: '7', spellcheck: 'false', autocomplete: 'off',
        oninput: e => { d.bg_color = e.target.value; notifyChange(); },
      });

      const previewCard = el('div', { class: 'be-lottie-preview-card' },
        [stage, meta]);

      // Initial render.
      renderPreview();

      return el('div', { class: 'be-body' }, [
        el('label', {}, ['Lottie source', srcInput]),
        sourceRow,
        previewCard,
        el('label', {}, [el('span', {}, ['Width ', widthOut]), widthSlider]),
        el('label', {}, ['Alignment', alignTog]),
        el('label', {}, ['Playback', playbackSel]),
        el('label', { class: 'be-row' }, [loopChk, el('span', {}, ['Loop'])]),
        autoplayLabel,
        el('label', {}, [el('span', {}, ['Speed ', speedOut]), speedSlider]),
        el('label', {}, ['Renderer', rendererSel]),
        el('label', {}, ['Background colour', bgInput]),
      ]);
    }

    // ── Intergroup member block ──────────────────────────────────
    // Settings UI: a dropdown of every officer (`window.tspIntergroup
    // Officers` injected by frontend_page_edit.html), plus four
    // checkboxes for which contact fields to render. Live preview
    // card mirrors the public render so admins see what visitors
    // will see before saving.
    function renderIntergroupMemberBody(b) {
      const d = b.data;
      if (d.officer_id == null) d.officer_id = 0;
      ['show_role', 'show_name', 'show_phone', 'show_email'].forEach(k => {
        if (d[k] == null) d[k] = true;
      });

      const officers = (window.tspIntergroupOfficers || []).slice();

      const wrap = el('div', { class: 'be-body be-officer-body' });

      if (!officers.length) {
        wrap.appendChild(el('p', { class: 'muted small' }, [
          'No officers yet. Add some under ',
          el('b', {}, ['Settings → Global → Intergroup Officers']),
          ' and reload the page editor.'
        ]));
        return wrap;
      }

      // Officer picker — the dropdown the user asked for. Lists every
      // officer by their position name first (the "row" identifier per
      // the spec), with the officer's name in parens for context. The
      // empty option lets admins clear the binding without removing
      // the block.
      const sel = el('select', {
        class: 'be-officer-select',
        onchange: e => {
          const v = parseInt(e.target.value, 10);
          d.officer_id = isNaN(v) ? 0 : v;
          updatePreview();
          notifyChange();
        },
      });
      sel.appendChild(el('option', { value: '0' }, ['— Select an officer —']));
      officers.forEach(o => {
        const lbl = (o.role || '(no position)') +
          (o.name ? '  ·  ' + o.name : '');
        const opt = el('option', { value: String(o.id) }, [lbl]);
        if (Number(d.officer_id) === o.id) opt.selected = true;
        sel.appendChild(opt);
      });

      // Field-toggle checkboxes — one per displayable column.
      function fieldToggle(key, lbl) {
        const cb = el('input', {
          type: 'checkbox', checked: d[key] ? 'checked' : null,
          onchange: e => { d[key] = e.target.checked; updatePreview(); notifyChange(); },
        });
        return el('label', { class: 'be-row' },
          [cb, el('span', {}, [lbl])]);
      }

      // Live preview card — same shape the public renderer emits, so
      // admins can see the chosen officer's contact info immediately.
      const preview = el('div', { class: 'be-officer-preview' });
      function updatePreview() {
        preview.innerHTML = '';
        const o = officers.find(x => x.id === Number(d.officer_id));
        if (!o) {
          preview.classList.add('is-empty');
          preview.textContent = 'Pick an officer to preview';
          return;
        }
        preview.classList.remove('is-empty');
        const inner = el('div', { class: 'be-officer-preview-card' });
        if (d.show_role && o.role) {
          inner.appendChild(el('div', { class: 'be-officer-role' }, [o.role]));
        }
        if (d.show_name && o.name) {
          inner.appendChild(el('div', { class: 'be-officer-name' }, [o.name]));
        }
        if (d.show_phone && o.phone) {
          inner.appendChild(el('div', { class: 'be-officer-phone' }, [o.phone]));
        }
        if (d.show_email && o.email) {
          inner.appendChild(el('div', { class: 'be-officer-email' }, [o.email]));
        }
        if (!inner.childNodes.length) {
          preview.classList.add('is-empty');
          preview.textContent = 'Toggle a field on to display contents.';
          return;
        }
        preview.appendChild(inner);
      }
      updatePreview();

      wrap.appendChild(el('label', {}, ['Officer (by position)', sel]));
      wrap.appendChild(el('div', { class: 'be-officer-fields' }, [
        el('div', { class: 'be-officer-fields-label muted smaller' },
          ['Fields to display']),
        fieldToggle('show_role', 'Position'),
        fieldToggle('show_name', 'Name'),
        fieldToggle('show_phone', 'Phone'),
        fieldToggle('show_email', 'Email'),
      ]));
      wrap.appendChild(el('div', { class: 'be-officer-preview-wrap' }, [
        el('div', { class: 'muted smaller' }, ['Preview']),
        preview,
      ]));

      return wrap;
    }

    // ── Officer roster block ─────────────────────────────────────
    // Settings UI: column-count toggle (2 / 3), gap input, and the
    // four field checkboxes shared with the single-member block. The
    // live preview renders the same card grid the public side will
    // emit, so admins see the layout before saving.
    function renderIntergroupRosterBody(b) {
      const d = b.data;
      if (!d.columns) d.columns = 3;
      if (!d.gap) d.gap = '1rem';
      ['show_role', 'show_name', 'show_phone', 'show_email'].forEach(k => {
        if (d[k] == null) d[k] = true;
      });
      const officers = (window.tspIntergroupOfficers || []).slice();

      const wrap = el('div', { class: 'be-body be-officer-body' });

      if (!officers.length) {
        wrap.appendChild(el('p', { class: 'muted small' }, [
          'No officers yet. Add some under ',
          el('b', {}, ['Settings → Global → Intergroup Officers']),
          ' and reload the page editor.'
        ]));
        return wrap;
      }

      // Column-count toggle (2 / 3) — segmented buttons.
      const colsTog = el('div', { class: 'view-toggle' });
      [2, 3].forEach(n => {
        colsTog.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + (Number(d.columns) === n ? ' active' : ''),
          'data-cols': String(n),
        }, [n + ' columns']));
      });
      colsTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-cols]');
        if (!btn) return;
        d.columns = parseInt(btn.dataset.cols, 10) || 3;
        colsTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        updatePreview();
        notifyChange();
      });

      // Gap input — accepts any CSS length token.
      const gapInp = el('input', {
        type: 'text', value: d.gap || '1rem',
        placeholder: 'e.g. 1rem, 24px, 0.75rem',
        oninput: e => {
          d.gap = (e.target.value || '').trim() || '1rem';
          updatePreview();
          notifyChange();
        },
      });

      // Field-toggle checkboxes — apply uniformly to every card.
      function fieldToggle(key, lbl) {
        const cb = el('input', {
          type: 'checkbox', checked: d[key] ? 'checked' : null,
          onchange: e => { d[key] = e.target.checked; updatePreview(); notifyChange(); },
        });
        return el('label', { class: 'be-row' },
          [cb, el('span', {}, [lbl])]);
      }

      // Live preview grid — one card per officer, mirrors the public
      // shape (.be-officer-roster-card with shadow + radius). Updates
      // on every column/gap/field change.
      const grid = el('div', { class: 'be-officer-roster-preview' });
      function updatePreview() {
        grid.style.gridTemplateColumns =
          'repeat(' + (Number(d.columns) || 3) + ', minmax(0, 1fr))';
        grid.style.gap = d.gap || '1rem';
        grid.innerHTML = '';
        officers.forEach(o => {
          const card = el('div', { class: 'be-officer-roster-card' });
          if (d.show_role && o.role) {
            card.appendChild(el('div', { class: 'be-officer-role' }, [o.role]));
          }
          if (d.show_name && o.name) {
            card.appendChild(el('div', { class: 'be-officer-name' }, [o.name]));
          }
          if (d.show_phone && o.phone) {
            card.appendChild(el('div', { class: 'be-officer-phone' }, [o.phone]));
          }
          if (d.show_email && o.email) {
            card.appendChild(el('div', { class: 'be-officer-email' }, [o.email]));
          }
          if (!card.childNodes.length) {
            card.classList.add('is-empty');
            card.textContent = '(no fields enabled)';
          }
          grid.appendChild(card);
        });
      }
      updatePreview();

      wrap.appendChild(el('label', {}, ['Columns', colsTog]));
      wrap.appendChild(el('label', {}, ['Gap', gapInp]));
      wrap.appendChild(el('div', { class: 'be-officer-fields' }, [
        el('div', { class: 'be-officer-fields-label muted smaller' },
          ['Fields to display on every card']),
        fieldToggle('show_role', 'Position'),
        fieldToggle('show_name', 'Name'),
        fieldToggle('show_phone', 'Phone'),
        fieldToggle('show_email', 'Email'),
      ]));
      wrap.appendChild(el('div', { class: 'be-officer-preview-wrap' }, [
        el('div', { class: 'muted smaller' },
          ['Preview · ' + officers.length + ' officer' + (officers.length === 1 ? '' : 's')]),
        grid,
      ]));

      return wrap;
    }

    // ── Library block ────────────────────────────────────────────
    // Settings UI: library picker + display style + mode (all vs.
    // granular). When granular is active, the panel reveals a
    // checklist of every item in the chosen library so admins can
    // hand-pick which to render. Cards style adds column count + gap
    // + thumbnail toggle. Field toggles (description, categories)
    // apply across all styles.
    function renderLibraryBody(b) {
      const d = b.data;
      if (!d.mode) d.mode = 'all';
      if (!d.style) d.style = 'cards';
      if (!d.columns) d.columns = 2;
      if (!d.gap) d.gap = '1rem';
      if (!d.sort) d.sort = 'manual';
      if (d.max_items == null) d.max_items = 0;
      if (!Array.isArray(d.item_ids)) d.item_ids = [];
      ['show_description', 'show_thumbnails', 'show_categories'].forEach(k => {
        if (d[k] == null) d[k] = true;
      });

      const libraries = (window.tspLibraries || []).slice();
      const wrap = el('div', { class: 'be-body be-library-body' });

      if (!libraries.length) {
        wrap.appendChild(el('p', { class: 'muted small' }, [
          'No libraries available. Create one under ',
          el('b', {}, ['Libraries']),
          ' first.'
        ]));
        return wrap;
      }

      // ── Library picker ────────────────────────────────────────
      const libSel = el('select', { class: 'be-library-select' });
      libSel.appendChild(el('option', { value: '0' }, ['— Select a library —']));
      libraries.forEach(lib => {
        const lbl = lib.name + (lib.public_visible ? '' : '  (private)');
        const opt = el('option', { value: String(lib.id) }, [lbl]);
        if (Number(d.library_id) === lib.id) opt.selected = true;
        libSel.appendChild(opt);
      });
      libSel.addEventListener('change', e => {
        const v = parseInt(e.target.value, 10);
        d.library_id = isNaN(v) ? 0 : v;
        // Switching libraries invalidates the granular selection —
        // item ids belong to the previous library and won't match.
        d.item_ids = [];
        renderGranularList();
        notifyChange();
      });

      // ── Title (optional heading rendered above the items) ──────
      const titleInp = el('input', {
        type: 'text', value: d.title || '',
        placeholder: 'Optional heading shown above the items',
        oninput: e => { d.title = e.target.value; notifyChange(); },
      });

      // ── Display style ─────────────────────────────────────────
      // Three options shown as a segmented toggle with concise hint
      // labels. Toggling "cards" reveals the columns + gap + thumbnail
      // controls below.
      const styleTog = el('div', { class: 'view-toggle' });
      [['bulleted', 'Bulleted'], ['list', 'Plain list'], ['cards', 'Cards']]
        .forEach(([v, lbl]) => {
          styleTog.appendChild(el('button', {
            type: 'button',
            class: 'btn btn-sm' + ((d.style || 'cards') === v ? ' active' : ''),
            'data-style': v,
          }, [lbl]));
        });
      styleTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-style]');
        if (!btn) return;
        d.style = btn.dataset.style;
        styleTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        cardsBox.style.display = (d.style === 'cards') ? '' : 'none';
        thumbsLabel.style.display = (d.style === 'cards') ? '' : 'none';
        notifyChange();
      });

      // ── Cards-only controls (columns + gap) ───────────────────
      const cardsBox = el('div', { class: 'be-library-cards-controls' });
      const colsTog = el('div', { class: 'view-toggle' });
      [1, 2, 3].forEach(n => {
        colsTog.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + (Number(d.columns) === n ? ' active' : ''),
          'data-cols': String(n),
        }, [n + ' col' + (n === 1 ? '' : 's')]));
      });
      colsTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-cols]');
        if (!btn) return;
        d.columns = parseInt(btn.dataset.cols, 10) || 2;
        colsTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        notifyChange();
      });
      const gapInp = el('input', {
        type: 'text', value: d.gap || '1rem',
        placeholder: 'e.g. 1rem, 24px',
        oninput: e => {
          d.gap = (e.target.value || '').trim() || '1rem';
          notifyChange();
        },
      });
      cardsBox.appendChild(el('label', {}, ['Columns', colsTog]));
      cardsBox.appendChild(el('label', {}, ['Gap', gapInp]));
      cardsBox.style.display = (d.style === 'cards') ? '' : 'none';

      // ── Mode + granular checklist ─────────────────────────────
      const modeTog = el('div', { class: 'view-toggle' });
      [['all', 'All items'], ['granular', 'Hand-pick items']]
        .forEach(([v, lbl]) => {
          modeTog.appendChild(el('button', {
            type: 'button',
            class: 'btn btn-sm' + ((d.mode || 'all') === v ? ' active' : ''),
            'data-mode': v,
          }, [lbl]));
        });
      modeTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-mode]');
        if (!btn) return;
        d.mode = btn.dataset.mode;
        modeTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        granularBox.style.display = (d.mode === 'granular') ? '' : 'none';
        notifyChange();
      });

      // Granular item checklist — rebuilt whenever the picker changes
      // or mode flips on. Each row is a checkbox + title + small
      // muted "kind" badge so admins know which items have files
      // attached vs. plain links/text.
      const granularBox = el('div', { class: 'be-library-granular' });
      function renderGranularList() {
        granularBox.innerHTML = '';
        const lib = libraries.find(l => l.id === Number(d.library_id));
        if (!lib) {
          granularBox.appendChild(el('p', { class: 'muted small' },
            ['Select a library above to choose specific items.']));
          return;
        }
        const items = lib.items || [];
        if (!items.length) {
          granularBox.appendChild(el('p', { class: 'muted small' },
            ['This library has no items yet.']));
          return;
        }
        // Quick-action row: select all / clear.
        const actions = el('div', { class: 'be-library-granular-actions' });
        actions.appendChild(el('button', {
          type: 'button', class: 'btn btn-sm',
          onclick: () => {
            d.item_ids = items.map(i => i.id);
            renderGranularList(); notifyChange();
          },
        }, ['Select all']));
        actions.appendChild(el('button', {
          type: 'button', class: 'btn btn-sm',
          onclick: () => {
            d.item_ids = [];
            renderGranularList(); notifyChange();
          },
        }, ['Clear']));
        granularBox.appendChild(actions);

        const list = el('div', { class: 'be-library-granular-list' });
        items.forEach(it => {
          const row = el('label', { class: 'be-library-granular-row' });
          const cb = el('input', {
            type: 'checkbox',
            checked: (d.item_ids || []).indexOf(it.id) >= 0 ? 'checked' : null,
            onchange: e => {
              const id = it.id;
              const set = new Set(d.item_ids || []);
              if (e.target.checked) set.add(id); else set.delete(id);
              d.item_ids = Array.from(set);
              notifyChange();
            },
          });
          row.appendChild(cb);
          row.appendChild(el('span', { class: 'be-library-granular-title' },
            [it.title || '(untitled)']));
          row.appendChild(el('span', { class: 'be-library-granular-kind muted smaller' },
            [it.kind]));
          list.appendChild(row);
        });
        granularBox.appendChild(list);
      }
      granularBox.style.display = (d.mode === 'granular') ? '' : 'none';
      renderGranularList();

      // ── Field toggles ────────────────────────────────────────
      function fieldToggle(key, lbl) {
        const cb = el('input', {
          type: 'checkbox', checked: d[key] ? 'checked' : null,
          onchange: e => { d[key] = e.target.checked; notifyChange(); },
        });
        return el('label', { class: 'be-row' },
          [cb, el('span', {}, [lbl])]);
      }
      const thumbsLabel = fieldToggle('show_thumbnails', 'Show thumbnails (cards style)');
      thumbsLabel.style.display = (d.style === 'cards') ? '' : 'none';

      // ── Sort selector ─────────────────────────────────────────
      // Manual stays the default so existing blocks keep their hand-
      // picked order. The other options are computed at render time
      // (in `library_block_data`) so an admin re-sorting on the
      // library page doesn't desync from what visitors see.
      const sortSel = el('select', { class: 'be-library-sort' });
      [['manual',    'Custom order (drag positions on the library page)'],
       ['name-asc',  'Name — A → Z'],
       ['name-desc', 'Name — Z → A'],
       ['date-desc', 'Date added — newest first'],
       ['date-asc',  'Date added — oldest first']].forEach(([v, lbl]) => {
        const opt = el('option', { value: v }, [lbl]);
        if ((d.sort || 'manual') === v) opt.selected = true;
        sortSel.appendChild(opt);
      });
      sortSel.addEventListener('change', e => {
        d.sort = e.target.value || 'manual';
        notifyChange();
      });

      // ── Max items + Load More ─────────────────────────────────
      // Positive integer → show the first N then render a Load More
      // button. Zero (or blank) disables the truncation entirely.
      const maxInp = el('input', {
        type: 'number', min: '0', step: '1',
        value: String(d.max_items || 0),
        placeholder: '0 = show every item',
        oninput: e => {
          const v = parseInt(e.target.value, 10);
          d.max_items = (isNaN(v) || v < 0) ? 0 : v;
          notifyChange();
        },
      });

      wrap.appendChild(el('label', {}, ['Library', libSel]));
      wrap.appendChild(el('label', {}, ['Title (optional)', titleInp]));
      wrap.appendChild(el('label', {}, ['Display style', styleTog]));
      wrap.appendChild(cardsBox);
      wrap.appendChild(el('label', {}, ['Items to include', modeTog]));
      wrap.appendChild(granularBox);
      wrap.appendChild(el('label', {}, ['Sort items by', sortSel]));
      wrap.appendChild(el('label', {}, [
        'Max items (Load More button shown when exceeded)',
        maxInp,
      ]));
      wrap.appendChild(el('div', { class: 'be-library-fields' }, [
        el('div', { class: 'muted smaller' }, ['Per-item controls']),
        fieldToggle('show_description', 'Show description / body excerpt'),
        thumbsLabel,
        fieldToggle('show_categories', 'Show category tags'),
      ]));
      return wrap;
    }

    // ── Blog list block ───────────────────────────────────────────
    // Picks a category OR tag (or neither) to scope the rendered list,
    // plus presentation knobs (style + columns + max + sort + which
    // metadata to surface). The frontend renderer reads these via
    // `blog_block_data` at request time so admin edits propagate to
    // every page that embeds a blog list.
    function renderBlogListBody(b) {
      const d = b.data;
      if (!d.style) d.style = 'cards';
      if (!d.columns) d.columns = 3;
      if (!d.gap) d.gap = '1.25rem';
      if (!d.sort) d.sort = 'newest';
      if (d.max_items == null) d.max_items = 6;
      ['show_image', 'show_summary', 'show_categories', 'show_date', 'show_more_link']
        .forEach(k => { if (d[k] == null) d[k] = true; });

      const cats = (window.tspBlogCategories || []).slice();
      const tags = (window.tspBlogTags || []).slice();
      const wrap = el('div', { class: 'be-body be-library-body' });

      // ── Filter scope ───────────────────────────────────────────
      const catSel = el('select', { class: 'be-library-select' });
      catSel.appendChild(el('option', { value: '0' }, ['— Any category —']));
      cats.forEach(c => {
        const opt = el('option', { value: String(c.id) }, [c.name]);
        if (Number(d.category_id) === c.id) opt.selected = true;
        catSel.appendChild(opt);
      });
      catSel.addEventListener('change', e => {
        const v = parseInt(e.target.value, 10);
        d.category_id = isNaN(v) ? 0 : v;
        notifyChange();
      });

      const tagSel = el('select', { class: 'be-library-select' });
      tagSel.appendChild(el('option', { value: '0' }, ['— Any tag —']));
      tags.forEach(t => {
        const opt = el('option', { value: String(t.id) }, ['#' + t.name]);
        if (Number(d.tag_id) === t.id) opt.selected = true;
        tagSel.appendChild(opt);
      });
      tagSel.addEventListener('change', e => {
        const v = parseInt(e.target.value, 10);
        d.tag_id = isNaN(v) ? 0 : v;
        notifyChange();
      });

      wrap.appendChild(el('div', { class: 'muted smaller', style: 'margin-bottom: 4px;' },
        ['Filter the rendered list by category and/or tag. Pick neither to show every published post.']));
      wrap.appendChild(el('label', {}, ['Category', catSel]));
      wrap.appendChild(el('label', {}, ['Tag', tagSel]));

      // ── Title + subtitle ───────────────────────────────────────
      wrap.appendChild(el('label', {}, ['Heading (optional)',
        el('input', {
          type: 'text', value: d.title || '',
          placeholder: 'Defaults to the category / tag name when set',
          oninput: e => { d.title = e.target.value; notifyChange(); },
        })]));
      wrap.appendChild(el('label', {}, ['Subheading (optional)',
        el('input', {
          type: 'text', value: d.subtitle || '',
          placeholder: 'A short caption shown beneath the heading',
          oninput: e => { d.subtitle = e.target.value; notifyChange(); },
        })]));

      // ── Style picker ──────────────────────────────────────────
      const styleTog = el('div', { class: 'view-toggle' });
      [['cards', 'Cards'], ['list', 'List'], ['headlines', 'Headlines']]
        .forEach(([v, lbl]) => {
          styleTog.appendChild(el('button', {
            type: 'button',
            class: 'btn btn-sm' + ((d.style || 'cards') === v ? ' active' : ''),
            'data-style': v,
          }, [lbl]));
        });
      styleTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-style]');
        if (!btn) return;
        d.style = btn.dataset.style;
        styleTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        cardsBox.style.display = (d.style === 'cards') ? '' : 'none';
        notifyChange();
      });
      wrap.appendChild(el('label', {}, ['Display style', styleTog]));

      // ── Cards-only controls ───────────────────────────────────
      const cardsBox = el('div', { class: 'be-library-cards-controls' });
      const colsTog = el('div', { class: 'view-toggle' });
      [1, 2, 3, 4].forEach(n => {
        colsTog.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + (Number(d.columns) === n ? ' active' : ''),
          'data-cols': String(n),
        }, [n + ' col' + (n === 1 ? '' : 's')]));
      });
      colsTog.addEventListener('click', e => {
        const btn = e.target.closest('button[data-cols]');
        if (!btn) return;
        d.columns = parseInt(btn.dataset.cols, 10) || 3;
        colsTog.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        notifyChange();
      });
      cardsBox.appendChild(el('label', {}, ['Columns', colsTog]));
      cardsBox.appendChild(el('label', {}, ['Gap',
        el('input', {
          type: 'text', value: d.gap || '1.25rem',
          placeholder: '1rem, 24px',
          oninput: e => { d.gap = (e.target.value || '').trim() || '1.25rem'; notifyChange(); },
        })]));
      cardsBox.style.display = (d.style === 'cards') ? '' : 'none';
      wrap.appendChild(cardsBox);

      // ── Max items ─────────────────────────────────────────────
      wrap.appendChild(el('label', {}, ['Max items (0 = unlimited)',
        el('input', {
          type: 'number', min: '0', max: '50', step: '1',
          value: String(d.max_items == null ? 6 : d.max_items),
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            d.max_items = isNaN(n) ? 0 : Math.max(0, Math.min(50, n));
            notifyChange();
          },
        })]));

      // ── Sort ──────────────────────────────────────────────────
      const sortSel = el('select', {
        onchange: e => { d.sort = e.target.value; notifyChange(); },
      });
      [['newest', 'Newest first'], ['oldest', 'Oldest first'],
       ['title', 'Title A → Z'], ['random', 'Random']]
        .forEach(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.sort || 'newest') === v) o.selected = true;
          sortSel.appendChild(o);
        });
      wrap.appendChild(el('label', {}, ['Sort', sortSel]));

      // ── Toggles ───────────────────────────────────────────────
      function fieldToggle(key, label) {
        const lbl = el('label', { class: 'be-row' });
        const cb = el('input', {
          type: 'checkbox',
          checked: d[key] !== false ? 'checked' : null,
          onchange: e => { d[key] = e.target.checked; notifyChange(); },
        });
        lbl.appendChild(cb);
        lbl.appendChild(el('span', {}, [label]));
        return lbl;
      }
      wrap.appendChild(el('div', { class: 'be-library-fields' }, [
        el('div', { class: 'muted smaller' }, ['Per-item display']),
        fieldToggle('show_image', 'Featured image'),
        fieldToggle('show_summary', 'Summary text'),
        fieldToggle('show_categories', 'Category chips'),
        fieldToggle('show_date', 'Date'),
      ]));
      wrap.appendChild(el('div', { class: 'be-library-fields' }, [
        el('div', { class: 'muted smaller' }, ['Filters']),
        fieldToggle('only_featured', 'Only featured posts'),
        fieldToggle('only_pinned', 'Only pinned posts'),
        fieldToggle('show_more_link', 'Show "View all posts" link below'),
      ]));

      return wrap;
    }

    function uploadLottieFile(file, onSrc) {
      // Inline upload — same /tspro/files/upload endpoint the image
      // block uses (no MIME filter on the server). On success we resolve
      // the public URL and hand it to the block via the onSrc callback.
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      fd.append('csrf_token', imageBrowserCsrf());
      fetch('/tspro/files/upload', {
        method: 'POST', body: fd, credentials: 'same-origin',
      }).then(r => r.json()).then(data => {
        if (data && data.item && data.item.original_filename) {
          onSrc('/pub/' + data.item.original_filename);
        }
      }).catch(err => console.warn('lottie upload failed', err));
    }

    // ── Hero block (per-instance config) ────────────────────────────
    // Mirrors the homepage's hero edit modal one-to-one — every text /
    // typography / background / particle / button control surfaces as
    // a JS-bound input on the block's `data` object. CSS class names
    // intentionally match the homepage admin's so the existing styles
    // (hero-section-grid, nav-megalink-*, hero-bg-panel, hero-typo-*)
    // apply without anything new.
    function renderHeroBody(b) {
      const d = b.data;
      // Backfill defaults for instances that predate any field.
      const DEFAULTS = {
        heading: '', subheading: '', eyebrow: '',
        tagline_enabled: true,
        heading_font: 'fraunces', heading_size_pct: 100,
        heading_grad_start: '#0f172a', heading_grad_end: '#374151',
        subheading_font: 'inter', subheading_size_pct: 100,
        subheading_color: '#475569',
        text_dynamic: false,
        height_vh_desktop: 0, height_vh_mobile: 0,
        bg_style: 'solid',
        bg_color: '', bg_color_2: '', bg_gradient_angle: 180,
        bg_image_src: '', bg_image_mode: 'cover', bg_image_scale: 100,
        bg_hue: 225, bg_hue_2: 170, bg_blur: 80, bg_opacity: 45,
        bg_randomize: false,
        bg_sinewave_colors: ['#16c2ba', '#1883d5', '#5a1ce5', '#0a3eb5'],
        bg_video_src: '', bg_video_speed: 100,
        bg_dynamic_key: '', bg_dynbg_config_json: '',
        particle_enabled: false, particle_effect: 'stars',
        particle_speed: 100, particle_size: 100,
        buttons: [],
      };
      Object.keys(DEFAULTS).forEach(k => { if (d[k] == null) d[k] = DEFAULTS[k]; });
      if (!Array.isArray(d.buttons)) d.buttons = [];
      if (!Array.isArray(d.bg_sinewave_colors)) {
        d.bg_sinewave_colors = DEFAULTS.bg_sinewave_colors.slice();
      }

      // ── DOM helpers — match the homepage admin's class names so the
      // existing CSS picks up our markup with zero new rules. Each
      // helper writes through `notifyChange()` so the save bar lights
      // up immediately. `oninput` is preferred over `onchange` for
      // text/number/range so the bar reflects every keystroke. ──────
      function field(lbl, inner, hintMd) {
        const wrap = el('div', { class: 'nav-megalink-field' });
        wrap.appendChild(el('span', { class: 'nav-megalink-field-lbl' }, [lbl]));
        wrap.appendChild(inner);
        if (hintMd) wrap.appendChild(el('p', { class: 'muted smaller' }, [hintMd]));
        return wrap;
      }
      function textInput(key, placeholder) {
        return el('input', { type: 'text', value: d[key] || '',
          placeholder: placeholder || '',
          oninput: e => { d[key] = e.target.value; notifyChange(); } });
      }
      function colorInput(key) {
        return el('input', { type: 'color',
          class: 'nav-megalink-color-input',
          value: d[key] || '#ffffff',
          oninput: e => { d[key] = e.target.value; notifyChange(); } });
      }
      function slider(key, min, max, step, suffix) {
        const fld = el('div', { class: 'nav-megalink-field hero-slider-field' });
        const out = el('output', {}, [String(d[key])]);
        fld.appendChild(el('span', { class: 'nav-megalink-field-lbl' },
          [arguments[5] || key, ' ', out, suffix || '']));
        const inp = el('input', { type: 'range',
          min: String(min), max: String(max), step: String(step),
          value: String(d[key]),
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            d[key] = isNaN(n) ? 0 : n;
            out.textContent = String(d[key]);
            notifyChange();
          } });
        fld.appendChild(inp);
        return fld;
      }
      function segmented(key, options) {
        // Radio-style segmented control. `options` = [['val','Label'], …]
        const seg = el('div', { class: 'nav-megalink-seg' });
        options.forEach(([v, lbl]) => {
          const opt = el('label', { class: 'nav-megalink-seg-opt' });
          const r = el('input', { type: 'radio', value: v,
            checked: (d[key] === v ? 'checked' : null),
            onchange: e => { if (e.target.checked) { d[key] = v; notifyChange(); refresh && refresh(); } } });
          r.name = 'be-hero-' + key + '-' + uid();   // unique-per-instance
          opt.appendChild(r);
          opt.appendChild(el('span', {}, [lbl]));
          seg.appendChild(opt);
        });
        return seg;
      }
      function checkRow(key, name, hint) {
        const row = el('li', { class: 'special-page-row',
          style: 'list-style:none; margin: 0.75rem 0;' });
        const info = el('div', { class: 'special-page-info' });
        info.appendChild(el('div', { class: 'u-name' }, [name]));
        if (hint) info.appendChild(el('p', { class: 'muted small' }, [hint]));
        row.appendChild(info);
        const lbl = el('label', { class: 'mode-toggle' });
        const cb = el('input', { type: 'checkbox',
          checked: d[key] ? 'checked' : null,
          onchange: e => { d[key] = e.target.checked; notifyChange(); } });
        lbl.appendChild(cb);
        lbl.appendChild(el('span', { class: 'mode-track' },
          [el('span', { class: 'mode-thumb' })]));
        row.appendChild(lbl);
        return row;
      }

      let refresh;  // recomputed each panel-show pass; assigned below

      // ── Root wrapper ────────────────────────────────────────────
      const wrap = el('div', { class: 'be-body hero-unified' });
      wrap.appendChild(el('p', { class: 'muted smaller', style: 'margin: 0 0 12px;' },
        ["Per-instance hero — every field is independent of the site-wide hero. Edits save with the page."]));

      // ── Live preview (simplified, isolated) ─────────────────────
      // Earlier versions reused the homepage's `.hero-full-preview-
      // clip` / `.hero-full-preview` / `.fe-hero` markup so the
      // preview looked photorealistic. In the page-edit modal
      // context that markup interacted badly with surrounding CSS
      // (the preview ended up rendered outside the modal). This
      // simplified version uses unique class names + inline styles
      // so its placement is fully under our control. Loses the
      // animated bits (frosty blobs, particles, sinewave canvas,
      // video) but shows heading / subhead / eyebrow / colours /
      // typography accurately enough to dial the design in. The
      // public renderer still uses the full `.fe-hero` chain.
      const previewWrap = el('div', { class: 'be-hero-preview',
        style: 'position: relative; height: 220px; margin: 0 0 16px; ' +
               'border: 1px dashed var(--border); border-radius: 12px; ' +
               'overflow: hidden; background: linear-gradient(180deg, #fff 0%, #f4f7fb 100%);' });
      const previewLabel = el('p', { class: 'muted smaller',
        style: 'position: absolute; top: 8px; left: 12px; z-index: 2; ' +
               'margin: 0; padding: 2px 8px; border-radius: 4px; ' +
               'background: rgba(255, 255, 255, 0.85); ' +
               'font-weight: 600; letter-spacing: .04em; ' +
               'text-transform: uppercase; pointer-events: none;' },
        ['Live preview']);
      previewWrap.appendChild(previewLabel);
      const previewInner = el('div', {
        style: 'position: absolute; inset: 0; display: flex; ' +
               'flex-direction: column; align-items: center; ' +
               'justify-content: center; gap: 6px; padding: 24px; ' +
               'text-align: center; pointer-events: none;' });
      const previewEyebrow = el('p', {
        style: 'margin: 0; padding: 4px 10px; border-radius: 999px; ' +
               'background: rgba(81, 100, 255, 0.10); color: #5164ff; ' +
               'font-weight: 600; font-size: 0.72rem; letter-spacing: 0.04em; ' +
               'text-transform: uppercase; display: none;' });
      const previewHeading = el('h1', {
        style: 'margin: 0; font-family: Fraunces, Inter, Georgia, serif; ' +
               'font-weight: 800; font-size: clamp(1.6rem, 3vw, 2.4rem); ' +
               'line-height: 1.15; letter-spacing: -0.025em; color: #0f172a;' });
      const previewSub = el('p', {
        style: 'margin: 0; font-family: Inter, sans-serif; ' +
               'font-size: clamp(0.875rem, 1.4vw, 1.0625rem); ' +
               'line-height: 1.5; color: #475569; max-width: 560px;' });
      const previewCta = el('div', {
        style: 'display: flex; gap: 8px; flex-wrap: wrap; ' +
               'justify-content: center; margin-top: 6px;' });
      previewInner.appendChild(previewEyebrow);
      previewInner.appendChild(previewHeading);
      previewInner.appendChild(previewSub);
      previewInner.appendChild(previewCta);
      previewWrap.appendChild(previewInner);
      wrap.appendChild(previewWrap);

      // Stubs kept so the rest of the code (refreshPreview, etc.)
      // can still call them harmlessly without a major rewrite.
      // Sinewave / video / particles drop to no-op in this simpler
      // preview; their controls still save correctly and the public
      // render uses the full pipeline.
      const previewBg = el('div', { hidden: true });
      const previewParticles = el('canvas', { hidden: true });
      const previewVideo = el('video', { hidden: true });
      const previewSection = previewWrap;   // alias so existing refs work
      function fitPreview() { /* no-op — fixed-size preview */ }
      let _partFx = null;
      function destroyPart() { _partFx = null; }
      function buildPart() { /* particles not in this preview */ }

      // ── Refresh helpers ─────────────────────────────────────────
      function hexLightness(h) {
        h = (h || '').replace('#', '');
        if (h.length === 3) h = h.split('').map(c => c + c).join('');
        if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
        const r = parseInt(h.slice(0, 2), 16) / 255;
        const g = parseInt(h.slice(2, 4), 16) / 255;
        const bv = parseInt(h.slice(4, 6), 16) / 255;
        return (Math.max(r, g, bv) + Math.min(r, g, bv)) / 2;
      }
      function avgLightness(values) {
        const v = values.filter(x => x != null);
        return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
      }

      function refreshPreview() {
        // Always try — even before the wrap is in the DOM, setting
        // textContent / styles on detached nodes is harmless and
        // means the preview is already painted when the BlockEditor
        // appends the wrap to the modal. Errors get logged but never
        // bubble so one bad input can't break the whole modal.
        try { _refreshPreviewInner(); }
        catch (err) { console.warn('[hero-block preview] refresh failed', err); }
      }
      function _refreshPreviewInner() {
        // ── Text ───────────────────────────────────────────────
        previewHeading.textContent = d.heading || 'Hero heading';
        previewSub.textContent = d.subheading || '';
        const eyeOn = d.tagline_enabled !== false;
        previewEyebrow.textContent = d.eyebrow || '';
        previewEyebrow.style.display = (eyeOn && (d.eyebrow || '').trim())
          ? 'inline-block' : 'none';

        // ── Typography (inline styles on the simple preview) ──
        const FAMILY = {
          fraunces: '"Fraunces", "Inter", Georgia, serif',
          inter:    '"Inter", "Fraunces", sans-serif',
        };
        previewHeading.style.fontFamily = FAMILY[d.heading_font] || FAMILY.fraunces;
        previewSub.style.fontFamily = FAMILY[d.subheading_font] || FAMILY.inter;
        // Size: blend the admin's % into the existing clamp() so the
        // preview scales without breaking the responsive cap.
        const hSize = (parseInt(d.heading_size_pct, 10) || 100) / 100;
        const sSize = (parseInt(d.subheading_size_pct, 10) || 100) / 100;
        previewHeading.style.fontSize = 'calc(clamp(1.4rem, 3vw, 2.4rem) * ' + hSize + ')';
        previewSub.style.fontSize = 'calc(clamp(0.875rem, 1.4vw, 1.0625rem) * ' + sSize + ')';
        // Heading color — average the gradient start + end into a
        // single colour for the simple preview. Skip the
        // background-clip:text dance to keep rendering robust in
        // the admin context.
        previewHeading.style.color = _avgHex(d.heading_grad_start, d.heading_grad_end) || '#0f172a';
        previewSub.style.color = d.subheading_color || '#475569';

        // ── Background ────────────────────────────────────────
        const style = d.bg_style || 'solid';
        // Reset all bg props before applying so a prior paint
        // doesn't bleed through. previewWrap's default light wash
        // is the fallback for styles without an explicit bg.
        previewWrap.style.background = '';
        previewWrap.style.backgroundImage = '';
        previewWrap.style.backgroundSize = '';
        previewWrap.style.backgroundRepeat = '';
        previewWrap.style.backgroundColor = '';

        if (style === 'solid' && d.bg_color) {
          previewWrap.style.background = d.bg_color;
        } else if (style === 'gradient') {
          const g1 = d.bg_color || '#ffffff';
          const g2 = d.bg_color_2 || '#e0e7ff';
          const ang = parseInt(d.bg_gradient_angle, 10) || 180;
          previewWrap.style.background = 'linear-gradient(' + ang + 'deg, ' + g1 + ', ' + g2 + ')';
        } else if (style === 'image' && d.bg_image_src) {
          if (d.bg_image_mode === 'tile') {
            const s = parseInt(d.bg_image_scale, 10) || 100;
            previewWrap.style.background = 'url("' + d.bg_image_src + '") repeat';
            previewWrap.style.backgroundSize = s + 'px ' + s + 'px';
          } else {
            previewWrap.style.background = 'url("' + d.bg_image_src + '") center/cover no-repeat';
          }
        } else if (style === 'sinewave') {
          // Show the first two stops as a vertical gradient in the
          // simple preview; the public render does the full canvas
          // sine-blend. Good enough for dialling colours in.
          const cs = (d.bg_sinewave_colors || []).filter(c =>
            /^#[0-9a-fA-F]{6}$/.test((c || '').trim()));
          if (cs.length >= 2) {
            previewWrap.style.background = 'linear-gradient(180deg, ' + cs.join(', ') + ')';
          } else if (cs.length === 1) {
            previewWrap.style.background = cs[0];
          } else {
            previewWrap.style.background = 'linear-gradient(180deg, #16c2ba, #5a1ce5)';
          }
        } else if (style === 'frosty') {
          // Show the two frosty hues as a soft gradient in the
          // simple preview (the public render adds animated blobs).
          const ha = parseInt(d.bg_hue, 10) || 225;
          const hb = parseInt(d.bg_hue_2, 10) || 170;
          previewWrap.style.background = 'linear-gradient(180deg, hsl(' + ha + ', 60%, 92%) 0%, hsl(' + hb + ', 60%, 90%) 100%)';
        }
        // 'video' and 'dynamic' styles intentionally show the
        // default light wash — they're hard to preview statically.

        // ── Dynamic-text contrast ──────────────────────────────
        // Auto-pick a contrasting text colour when the bg is dark.
        if (d.text_dynamic) {
          let l = 0.95;
          if (style === 'solid') {
            l = hexLightness(d.bg_color) ?? 0.95;
          } else if (style === 'gradient') {
            l = avgLightness([hexLightness(d.bg_color), hexLightness(d.bg_color_2)]) ?? 0.95;
          } else if (style === 'sinewave') {
            l = avgLightness((d.bg_sinewave_colors || []).map(hexLightness)) ?? 0.55;
          } else if (style === 'frosty') {
            l = 0.9;
          }
          if (l < 0.55) {
            previewHeading.style.color = '#ffffff';
            previewSub.style.color = 'rgba(255,255,255,0.85)';
          }
        }
      }
      // Helper: blend two hex colours by averaging RGB channels.
      // Used for the heading colour preview since the simple
      // renderer paints with a single fill instead of a gradient.
      function _avgHex(a, b) {
        function toRgb(h) {
          h = (h || '').replace('#', '');
          if (h.length === 3) h = h.split('').map(c => c + c).join('');
          if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
          return [parseInt(h.slice(0, 2), 16),
                  parseInt(h.slice(2, 4), 16),
                  parseInt(h.slice(4, 6), 16)];
        }
        const ra = toRgb(a), rb = toRgb(b);
        if (!ra && !rb) return null;
        if (!rb) return a;
        if (!ra) return b;
        function px(n) { return Math.round(n).toString(16).padStart(2, '0'); }
        return '#' + px((ra[0] + rb[0]) / 2) + px((ra[1] + rb[1]) / 2) + px((ra[2] + rb[2]) / 2);
      }

      // Schedule a single refresh per animation frame, coalescing
      // bursts of input events (e.g. dragging a slider) into one paint.
      let _refreshScheduled = false;
      function scheduleRefresh() {
        if (_refreshScheduled) return;
        _refreshScheduled = true;
        requestAnimationFrame(() => {
          _refreshScheduled = false;
          refreshPreview();
        });
      }
      // Catch every input / change anywhere in the editor — handlers
      // mutate `d` first, this listener re-renders the preview after.
      wrap.addEventListener('input', scheduleRefresh);
      wrap.addEventListener('change', scheduleRefresh);

      // Initial paint — synchronous so the preview shows content
      // the instant the BlockEditor mounts the wrap. The
      // ResizeObserver wired earlier handles the fit-to-clip pass
      // automatically once layout settles; we also schedule one
      // explicit fit on the next frame as a safety net for
      // browsers where the observer's first measurement is
      // delayed.
      refreshPreview();
      requestAnimationFrame(fitPreview);

      // ── 1. Text column ──────────────────────────────────────────
      const textGroup = el('div', { class: 'hero-text-col' });
      textGroup.appendChild(el('h3', { class: 'hero-sub-heading' }, ['Text']));

      textGroup.appendChild(el('label', {}, ['Heading',
        textInput('heading', 'You are not alone.')]));
      const subTa = el('textarea', { rows: '5', style: 'min-height: 120px;',
        placeholder: 'Find meetings, connect with your community…',
        oninput: e => { d.subheading = e.target.value; notifyChange(); } },
        [d.subheading || '']);
      textGroup.appendChild(el('label', {}, ['Subheading', subTa]));
      textGroup.appendChild(el('label', {}, [
        'Eyebrow ', el('span', { class: 'muted small' }, ['(small pill above the heading)']),
        textInput('eyebrow', 'A recovery fellowship portal.')]));
      textGroup.appendChild(checkRow('tagline_enabled', 'Show eyebrow above heading',
        'Toggle the eyebrow pill on or off without clearing the text.'));

      // Typography grid (heading + subheading groups, side by side)
      const typoGrid = el('div', { class: 'hero-typo-grid' });

      const hGroup = el('fieldset', { class: 'hero-typo-group' });
      hGroup.appendChild(el('legend', {}, ['Heading']));
      hGroup.appendChild(field('Font family',
        segmented('heading_font', [['fraunces', 'Fraunces · serif'], ['inter', 'Inter · sans']])));
      hGroup.appendChild(slider('heading_size_pct', 50, 200, 5, '%', 'Size'));
      const hColors = el('div', { class: 'hero-typo-color-row' });
      hColors.appendChild(field('Gradient start', colorInput('heading_grad_start')));
      hColors.appendChild(field('Gradient end', colorInput('heading_grad_end')));
      hGroup.appendChild(hColors);
      typoGrid.appendChild(hGroup);

      const sGroup = el('fieldset', { class: 'hero-typo-group' });
      sGroup.appendChild(el('legend', {}, ['Subheading']));
      sGroup.appendChild(field('Font family',
        segmented('subheading_font', [['fraunces', 'Fraunces · serif'], ['inter', 'Inter · sans']])));
      sGroup.appendChild(slider('subheading_size_pct', 50, 200, 5, '%', 'Size'));
      const sColors = el('div', { class: 'hero-typo-color-row' });
      sColors.appendChild(field('Text colour', colorInput('subheading_color')));
      sGroup.appendChild(sColors);
      typoGrid.appendChild(sGroup);

      textGroup.appendChild(typoGrid);

      textGroup.appendChild(checkRow('text_dynamic', 'Dynamic text colors',
        "Auto-pick contrasting heading + subheading colors based on the background's lightness. Overrides the gradient and subheading colour above when on."));

      // Heights
      const hGrid = el('div', { class: 'hero-heading-opts hero-heading-grad-row' });
      function heightField(key, lbl) {
        const fld = el('div', { class: 'nav-megalink-field hero-slider-field' });
        const out = el('output', {}, [d[key] ? d[key] + 'vh' : 'Auto']);
        fld.appendChild(el('span', { class: 'nav-megalink-field-lbl' }, [lbl, ' ', out]));
        fld.appendChild(el('input', { type: 'range', min: '0', max: '200', step: '5',
          value: String(d[key] || 0),
          oninput: e => {
            const n = parseInt(e.target.value, 10) || 0;
            d[key] = n;
            out.textContent = n ? n + 'vh' : 'Auto';
            notifyChange();
          } }));
        return fld;
      }
      hGrid.appendChild(heightField('height_vh_desktop', 'Desktop height'));
      hGrid.appendChild(heightField('height_vh_mobile', 'Mobile height'));
      textGroup.appendChild(hGrid);
      textGroup.appendChild(el('p', { class: 'muted smaller', style: 'margin: 4px 2px 0;' },
        ["Set 0 to keep the natural padding-based height. Higher values stretch the hero to that share of the viewport (50 = half-screen, 100 = full-screen). Mobile falls back to the desktop value when left at 0."]));

      wrap.appendChild(textGroup);

      // ── 2. Background column ────────────────────────────────────
      const bgGroup = el('div', { class: 'hero-bg-col' });
      bgGroup.appendChild(el('h3', { class: 'hero-sub-heading' }, ['Background']));
      bgGroup.appendChild(el('p', { class: 'muted smaller hero-sub-help' },
        ['Pick a style, tweak it, or upload an image.']));

      const bgStyleField = el('div', { class: 'nav-megalink-field' });
      bgStyleField.appendChild(el('span', { class: 'nav-megalink-field-lbl' }, ['Style']));
      const bgSeg = el('div', { class: 'nav-megalink-seg' });
      const BG_STYLES = [
        ['frosty', 'Frosty'], ['solid', 'Solid'], ['gradient', 'Gradient'],
        ['image', 'Image'], ['sinewave', 'Sinewave'], ['video', 'Video'],
        ['dynamic', 'Dynamic'],
      ];
      const bgRadioName = 'be-hero-bg-' + uid();
      BG_STYLES.forEach(([v, lbl]) => {
        const opt = el('label', { class: 'nav-megalink-seg-opt' });
        const r = el('input', { type: 'radio', name: bgRadioName, value: v,
          checked: (d.bg_style === v ? 'checked' : null),
          onchange: e => {
            if (!e.target.checked) return;
            d.bg_style = v;
            syncBgPanels();
            notifyChange();
          } });
        opt.appendChild(r);
        opt.appendChild(el('span', {}, [lbl]));
        bgSeg.appendChild(opt);
      });
      bgStyleField.appendChild(bgSeg);
      bgGroup.appendChild(bgStyleField);

      // Reserve a stable min-height across all bg panels so flipping
      // between Frosty (tallest — 4 sliders + a toggle) and Sinewave
      // (shortest — 4 colour pickers) doesn't make the modal body's
      // scroll height jump, which otherwise re-centers the modal
      // panel and pulls the sticky preview off-screen ("viewport
      // collapses up" symptom). Tuned to the tallest panel's natural
      // height so no panel needs to overflow to fit.
      const panels = el('div', { class: 'hero-bg-panels',
        style: 'min-height: 320px;' });

      // — Frosty panel —
      const pFrosty = el('div', { class: 'hero-bg-panel', 'data-bg-panel': 'frosty' });
      pFrosty.appendChild(el('p', { class: 'muted smaller' },
        ['Animated blurred colour blobs over a light wash — the original frosty look.']));
      const frostyGrid = el('div', { class: 'hero-bg-grid' });
      frostyGrid.appendChild(slider('bg_hue', 0, 360, 5, '°', 'Primary hue'));
      frostyGrid.appendChild(slider('bg_hue_2', 0, 360, 5, '°', 'Accent hue'));
      frostyGrid.appendChild(slider('bg_blur', 0, 200, 5, 'px', 'Blur'));
      frostyGrid.appendChild(slider('bg_opacity', 0, 100, 5, '%', 'Intensity'));
      pFrosty.appendChild(frostyGrid);
      pFrosty.appendChild(checkRow('bg_randomize', 'Randomize on every page load',
        'Picks fresh hues each time so the hero never looks the same twice.'));
      panels.appendChild(pFrosty);

      // — Solid panel —
      const pSolid = el('div', { class: 'hero-bg-panel', 'data-bg-panel': 'solid' });
      pSolid.appendChild(el('p', { class: 'muted smaller' },
        ['A single flat colour behind the hero.']));
      pSolid.appendChild(field('Background color', colorInput('bg_color')));
      panels.appendChild(pSolid);

      // — Gradient panel —
      const pGrad = el('div', { class: 'hero-bg-panel', 'data-bg-panel': 'gradient' });
      pGrad.appendChild(el('p', { class: 'muted smaller' },
        ['A two-colour linear gradient at a chosen angle.']));
      const gradGrid = el('div', { class: 'hero-bg-grid' });
      gradGrid.appendChild(field('Start color', colorInput('bg_color')));
      gradGrid.appendChild(field('End color', colorInput('bg_color_2')));
      gradGrid.appendChild(slider('bg_gradient_angle', 0, 360, 5, '°', 'Angle'));
      pGrad.appendChild(gradGrid);
      panels.appendChild(pGrad);

      // — Image panel —
      const pImg = el('div', { class: 'hero-bg-panel', 'data-bg-panel': 'image' });
      pImg.appendChild(el('p', { class: 'muted smaller' },
        ['Upload a photo, illustration, or SVG. Use Tile for repeating patterns and the scale slider to size a single repeat.']));
      const imgPreview = el('div', { class: 'hero-bg-image-preview' });
      function renderImgPreview() {
        imgPreview.innerHTML = '';
        if (d.bg_image_src) {
          imgPreview.appendChild(el('img', { src: d.bg_image_src, alt: '',
            style: 'max-width: 220px; max-height: 120px; border-radius: 6px;' }));
          const clr = el('button', { type: 'button', class: 'btn btn-sm',
            onclick: () => { d.bg_image_src = ''; renderImgPreview(); notifyChange(); } },
            ['Remove']);
          imgPreview.appendChild(clr);
        }
      }
      renderImgPreview();
      pImg.appendChild(imgPreview);
      const upWrap = el('label', {}, ['Upload image ',
        el('span', { class: 'muted small' }, ['(PNG, JPG, or SVG)'])]);
      const fileInp = el('input', { type: 'file', accept: 'image/*',
        onchange: e => {
          const f = e.target.files && e.target.files[0];
          if (!f) return;
          const fd = new FormData();
          fd.append('file', f);
          fd.append('csrf_token', imageBrowserCsrf());
          fetch('/tspro/files/upload', { method: 'POST', body: fd,
            credentials: 'same-origin' })
            .then(r => r.json()).then(data => {
              if (data && data.item && data.item.original_filename) {
                d.bg_image_src = '/pub/' + data.item.original_filename;
                renderImgPreview(); notifyChange();
              }
            }).catch(err => console.warn('hero bg upload failed', err));
        } });
      upWrap.appendChild(fileInp);
      pImg.appendChild(upWrap);
      const imgGrid = el('div', { class: 'hero-bg-grid' });
      imgGrid.appendChild(field('Display mode',
        segmented('bg_image_mode', [['cover', 'Cover'], ['tile', 'Tile']])));
      imgGrid.appendChild(slider('bg_image_scale', 10, 400, 5, '%', 'Scale'));
      pImg.appendChild(imgGrid);
      panels.appendChild(pImg);

      // — Sinewave panel —
      const pSine = el('div', { class: 'hero-bg-panel', 'data-bg-panel': 'sinewave' });
      pSine.appendChild(el('p', { class: 'muted smaller' },
        ['A flowing multi-color sine-wave gradient. Pick 2–4 colors below; leave a slot blank to drop it.']));
      const sineGrid = el('div', { class: 'hero-bg-grid' });
      for (let i = 0; i < 4; i++) {
        const fld = el('div', { class: 'nav-megalink-field' });
        fld.appendChild(el('span', { class: 'nav-megalink-field-lbl' }, ['Color ' + (i + 1)]));
        const inp = el('input', { type: 'color', class: 'nav-megalink-color-input',
          value: d.bg_sinewave_colors[i] || '#ffffff',
          oninput: e => { d.bg_sinewave_colors[i] = e.target.value; notifyChange(); } });
        fld.appendChild(inp);
        sineGrid.appendChild(fld);
      }
      pSine.appendChild(sineGrid);
      panels.appendChild(pSine);

      // — Video panel —
      const pVid = el('div', { class: 'hero-bg-panel', 'data-bg-panel': 'video' });
      pVid.appendChild(el('p', { class: 'muted smaller' },
        ['Upload a short MP4/WebM clip. The video plays muted, autoplays, and fills the hero edge-to-edge.']));
      const vidPreview = el('div', { class: 'hero-bg-image-preview' });
      function renderVidPreview() {
        vidPreview.innerHTML = '';
        if (d.bg_video_src) {
          vidPreview.appendChild(el('video', { src: d.bg_video_src,
            muted: 'muted', autoplay: 'autoplay', loop: 'loop', playsinline: 'playsinline',
            style: 'max-width: 220px; max-height: 120px; border-radius: 6px;' }));
          vidPreview.appendChild(el('button', { type: 'button', class: 'btn btn-sm',
            onclick: () => { d.bg_video_src = ''; renderVidPreview(); notifyChange(); } },
            ['Remove']));
        }
      }
      renderVidPreview();
      pVid.appendChild(vidPreview);
      const vidUp = el('label', {}, ['Upload video ',
        el('span', { class: 'muted small' }, ['(MP4 or WebM, ≤ 256 MB)'])]);
      const vidInp = el('input', { type: 'file',
        accept: 'video/mp4,video/webm,video/quicktime',
        onchange: e => {
          const f = e.target.files && e.target.files[0];
          if (!f) return;
          const fd = new FormData();
          fd.append('file', f);
          fd.append('csrf_token', imageBrowserCsrf());
          fetch('/tspro/files/upload', { method: 'POST', body: fd,
            credentials: 'same-origin' })
            .then(r => r.json()).then(data => {
              if (data && data.item && data.item.original_filename) {
                d.bg_video_src = '/pub/' + data.item.original_filename;
                renderVidPreview(); notifyChange();
              }
            }).catch(err => console.warn('hero bg video upload failed', err));
        } });
      vidUp.appendChild(vidInp);
      pVid.appendChild(vidUp);
      const vidGrid = el('div', { class: 'hero-bg-grid' });
      const vsel = el('select', {
        onchange: e => { d.bg_video_speed = parseInt(e.target.value, 10) || 100; notifyChange(); } });
      [[50, '0.5×'], [100, '1×'], [150, '1.5×'], [200, '2×'], [300, '3×']].forEach(([v, lbl]) => {
        const o = el('option', { value: String(v) }, [lbl]);
        if (Number(d.bg_video_speed) === v) o.selected = true;
        vsel.appendChild(o);
      });
      vidGrid.appendChild(field('Speed', vsel));
      pVid.appendChild(vidGrid);
      panels.appendChild(pVid);

      // — Dynamic panel (dynbg key, hand-typed; full picker UI lives
      //   in a separate macro that the BlockEditor doesn't surface
      //   here yet — admins paste a key or leave blank). —
      const pDyn = el('div', { class: 'hero-bg-panel', 'data-bg-panel': 'dynamic' });
      pDyn.appendChild(el('p', { class: 'muted smaller' },
        ['Pick a CSS-driven backdrop preset by key (e.g. ', el('code', {}, ['aurora-blobs']), ', ', el('code', {}, ['mesh-gradient']), ', ', el('code', {}, ['aurora-bands']), ', etc.). Available keys come from the dynbg catalog.']));
      pDyn.appendChild(field('Dynbg key', textInput('bg_dynamic_key', 'aurora')));
      panels.appendChild(pDyn);

      bgGroup.appendChild(panels);

      function syncBgPanels() {
        panels.querySelectorAll('[data-bg-panel]').forEach(p => {
          p.hidden = p.dataset.bgPanel !== d.bg_style;
        });
      }
      syncBgPanels();

      // — Particle overlay (any bg style) —
      bgGroup.appendChild(el('h3', { class: 'hero-sub-heading',
        style: 'margin-top: 1.5rem;' }, ['Particle overlay']));
      bgGroup.appendChild(checkRow('particle_enabled', 'Show particles',
        'Animated particle layer above the background.'));
      const partGrid = el('div', { class: 'hero-bg-grid' });
      const psel = el('select', {
        onchange: e => { d.particle_effect = e.target.value; notifyChange(); } });
      ['network', 'stars', 'fireflies', 'bubbles', 'snow', 'waves', 'orbits', 'rain']
        .forEach(eff => {
          const o = el('option', { value: eff }, [eff.charAt(0).toUpperCase() + eff.slice(1)]);
          if (d.particle_effect === eff) o.selected = true;
          psel.appendChild(o);
        });
      partGrid.appendChild(field('Effect', psel));
      partGrid.appendChild(slider('particle_speed', 10, 300, 5, '%', 'Speed'));
      partGrid.appendChild(slider('particle_size', 25, 400, 5, '%', 'Size'));
      bgGroup.appendChild(partGrid);

      wrap.appendChild(bgGroup);

      // ── 3. Buttons column ───────────────────────────────────────
      const btnGroup = el('div', { class: 'hero-buttons-col' });
      const btnHead = el('h3', { class: 'hero-sub-heading' }, ['Call-to-action buttons']);
      const addBtn = el('button', { type: 'button',
        class: 'btn btn-sm btn-primary hero-sub-add',
        onclick: () => {
          d.buttons.push({ id: uid(), label: 'Click here', url: '',
            style: 'primary', open_in_new_tab: false,
            icon_before: '', icon_before_color: '', icon_before_size: '',
            icon_after: '', icon_after_color: '', icon_after_size: '',
            custom_bg_color: '', custom_text_color: '' });
          renderButtons(); notifyChange();
        } }, ['+ Add button']);
      btnHead.appendChild(addBtn);
      btnGroup.appendChild(btnHead);
      btnGroup.appendChild(el('p', { class: 'muted small hero-sub-help' },
        ['Rendered under the hero subheading. Drag the handle ↕ to reorder.']));

      const btnList = el('div');
      function renderButtons() {
        btnList.innerHTML = '';
        if (!d.buttons.length) {
          btnList.appendChild(el('p', { class: 'muted smaller' },
            ['No buttons yet — click "+ Add button" above.']));
          return;
        }
        d.buttons.forEach((btn, idx) => {
          const row = el('div', {
            style: 'display: grid; gap: 8px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px;' });
          const head = el('div', { style: 'display: flex; gap: 6px; align-items: center;' }, [
            el('strong', { style: 'flex: 1;' }, ['Button ' + (idx + 1)]),
            el('button', { type: 'button', class: 'btn btn-sm', title: 'Move up',
              onclick: () => {
                if (idx > 0) {
                  const t = d.buttons[idx]; d.buttons[idx] = d.buttons[idx - 1];
                  d.buttons[idx - 1] = t; renderButtons(); notifyChange();
                }
              } }, ['↑']),
            el('button', { type: 'button', class: 'btn btn-sm', title: 'Move down',
              onclick: () => {
                if (idx < d.buttons.length - 1) {
                  const t = d.buttons[idx]; d.buttons[idx] = d.buttons[idx + 1];
                  d.buttons[idx + 1] = t; renderButtons(); notifyChange();
                }
              } }, ['↓']),
            el('button', { type: 'button', class: 'btn btn-sm', title: 'Remove',
              onclick: () => { d.buttons.splice(idx, 1); renderButtons(); notifyChange(); } },
              ['Remove']),
          ]);
          row.appendChild(head);
          const bind = (key, lbl, ph, type) => {
            const inp = el('input', { type: type || 'text',
              value: btn[key] != null ? String(btn[key]) : '',
              placeholder: ph || '',
              oninput: e => { btn[key] = e.target.value; notifyChange(); } });
            return el('label', {}, [lbl, inp]);
          };
          row.appendChild(bind('label', 'Label', 'Find a Meeting'));
          row.appendChild(bind('url', 'URL', '/meetings or https://…'));
          const styleSel = el('select', {
            onchange: e => { btn.style = e.target.value; notifyChange(); } });
          [['primary', 'Primary (filled)'], ['ghost', 'Ghost (outline)']].forEach(([v, lbl]) => {
            const o = el('option', { value: v }, [lbl]);
            if ((btn.style || 'primary') === v) o.selected = true;
            styleSel.appendChild(o);
          });
          row.appendChild(el('label', {}, ['Style', styleSel]));
          const newTabLbl = el('label', { class: 'be-row' });
          const newTabCb = el('input', { type: 'checkbox',
            checked: btn.open_in_new_tab ? 'checked' : null,
            onchange: e => { btn.open_in_new_tab = e.target.checked; notifyChange(); } });
          newTabLbl.appendChild(newTabCb);
          newTabLbl.appendChild(el('span', {}, ['Open in new tab']));
          row.appendChild(newTabLbl);

          // Optional icons + custom colors (collapsed by default to keep
          // the row compact — admins who only need a label + URL aren't
          // dazzled by ten extra inputs).
          const adv = el('details', {});
          adv.appendChild(el('summary', { class: 'muted smaller' },
            ['Advanced (icons, custom colours)']));
          adv.appendChild(bind('icon_before', 'Icon before', 'lucide name (e.g. calendar)'));
          adv.appendChild(bind('icon_before_color', 'Before-icon color', '#ffffff'));
          adv.appendChild(bind('icon_before_size', 'Before-icon size (px)', '24', 'number'));
          adv.appendChild(bind('icon_after', 'Icon after', 'lucide name (e.g. arrow-right)'));
          adv.appendChild(bind('icon_after_color', 'After-icon color', '#ffffff'));
          adv.appendChild(bind('icon_after_size', 'After-icon size (px)', '24', 'number'));
          adv.appendChild(bind('custom_bg_color', 'Custom bg (primary only)', '#1d4ed8'));
          adv.appendChild(bind('custom_text_color', 'Custom text (primary only)', '#ffffff'));
          row.appendChild(adv);
          btnList.appendChild(row);
        });
      }
      renderButtons();
      btnGroup.appendChild(btnList);

      wrap.appendChild(btnGroup);

      return wrap;
    }

    // ── Meetings list block (data-driven) ──────────────────────────
    // Per-instance copy of the homepage meetings card grid. Each
    // block carries its own filter / display config; the page route
    // calls `blocks.filtered_meetings(d)` per block and stamps the
    // resolved groups into the render context.
    function renderMeetingsBody(b) {
      const d = b.data;
      const wrap = el('div', { class: 'be-body be-library-body' });

      wrap.appendChild(el('div', { class: 'muted smaller', style: 'margin-bottom: 4px;' },
        ['Live meetings list filtered by your chosen window. Same configurable card grid the homepage uses; each block instance can carry its own filter + display settings.']));

      wrap.appendChild(el('label', {}, ['Heading',
        el('input', { type: 'text', value: d.heading || '',
          placeholder: 'Upcoming Meetings',
          oninput: e => { d.heading = e.target.value; notifyChange(); } })]));
      wrap.appendChild(el('label', {}, ['Intro (optional)',
        el('input', { type: 'text', value: d.intro || '',
          placeholder: "A quick look at what's on the schedule.",
          oninput: e => { d.intro = e.target.value; notifyChange(); } })]));

      const filterSel = el('select', {
        onchange: e => { d.filter = e.target.value; notifyChange(); },
      });
      [['today_all', 'Everything today'],
       ['upcoming_today', "Today's upcoming (drops past)"],
       ['next_24h', 'Next 24 hours'],
       ['next_7_days', 'Next 7 days'],
       ['this_week', 'This calendar week (Mon → Sun)'],
       ['all', 'All meetings (next occurrence)']].forEach(([v, lbl]) => {
        const o = el('option', { value: v }, [lbl]);
        if ((d.filter || 'upcoming_today') === v) o.selected = true;
        filterSel.appendChild(o);
      });
      wrap.appendChild(el('label', {}, ['Window filter', filterSel]));

      wrap.appendChild(el('label', {}, ['Max cards (1–24)',
        el('input', { type: 'number', min: '1', max: '24', step: '1',
          value: String(d.max_count == null ? 6 : d.max_count),
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            d.max_count = isNaN(n) ? 6 : Math.max(1, Math.min(24, n));
            notifyChange();
          } })]));

      wrap.appendChild(el('label', {}, ['Schedule lines per card',
        el('input', { type: 'number', min: '1', max: '7', step: '1',
          value: String(d.show_first_n == null ? 3 : d.show_first_n),
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            d.show_first_n = isNaN(n) ? 3 : Math.max(1, Math.min(7, n));
            notifyChange();
          } })]));

      const animSel = el('select', {
        onchange: e => { d.animation = e.target.value; notifyChange(); },
      });
      [['fade', 'Fade in'], ['slide', 'Slide up'], ['none', 'No animation']]
        .forEach(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.animation || 'fade') === v) o.selected = true;
          animSel.appendChild(o);
        });
      wrap.appendChild(el('label', {}, ['Card animation', animSel]));

      wrap.appendChild(el('label', {}, ['Stagger between cards (ms)',
        el('input', { type: 'number', min: '0', max: '500', step: '10',
          value: String(d.stagger_ms == null ? 60 : d.stagger_ms),
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            d.stagger_ms = isNaN(n) ? 60 : Math.max(0, Math.min(500, n));
            notifyChange();
          } })]));

      wrap.appendChild(el('label', {}, ['Empty-state message',
        el('input', { type: 'text', value: d.empty_message || '',
          placeholder: 'No meetings scheduled — check back soon.',
          oninput: e => { d.empty_message = e.target.value; notifyChange(); } })]));

      function toggle(key, label, dflt) {
        const lbl = el('label', { class: 'be-row' });
        const cb = el('input', { type: 'checkbox',
          checked: (d[key] == null ? dflt : d[key]) ? 'checked' : null,
          onchange: e => { d[key] = e.target.checked; notifyChange(); } });
        lbl.appendChild(cb);
        lbl.appendChild(el('span', {}, [label]));
        return lbl;
      }
      wrap.appendChild(el('div', { class: 'be-library-fields' }, [
        el('div', { class: 'muted smaller' }, ['Toggles']),
        toggle('group_by_day', 'Group by day (rows per Mon / Tue / …)', false),
        toggle('show_type_chip', 'Show in-person / online / hybrid chip', true),
        toggle('show_schedule', 'Show meeting schedule lines', true),
      ]));
      return wrap;
    }

    // ── Upcoming events block (data-driven) ────────────────────────
    // Per-instance copy of the homepage events list. Pulls Post rows
    // where is_event=True via `blocks.filtered_events(d)`; past events
    // drop off automatically (the auto-archive sweep flips them).
    function renderEventsBody(b) {
      const d = b.data;
      const wrap = el('div', { class: 'be-body be-library-body' });

      wrap.appendChild(el('div', { class: 'muted smaller', style: 'margin-bottom: 4px;' },
        ['Live upcoming-events list. Pulls from the Posts module — past events drop off automatically.']));

      wrap.appendChild(el('label', {}, ['Heading',
        el('input', { type: 'text', value: d.heading || '',
          placeholder: 'Upcoming Events',
          oninput: e => { d.heading = e.target.value; notifyChange(); } })]));
      wrap.appendChild(el('label', {}, ['Intro (optional)',
        el('input', { type: 'text', value: d.intro || '',
          placeholder: 'Mark your calendar',
          oninput: e => { d.intro = e.target.value; notifyChange(); } })]));

      wrap.appendChild(el('label', {}, ['Max rows (1–20)',
        el('input', { type: 'number', min: '1', max: '20', step: '1',
          value: String(d.max_count == null ? 6 : d.max_count),
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            d.max_count = isNaN(n) ? 6 : Math.max(1, Math.min(20, n));
            notifyChange();
          } })]));

      const animSel = el('select', {
        onchange: e => { d.animation = e.target.value; notifyChange(); },
      });
      [['fade', 'Fade in'], ['slide', 'Slide up'], ['none', 'No animation']]
        .forEach(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if ((d.animation || 'fade') === v) o.selected = true;
          animSel.appendChild(o);
        });
      wrap.appendChild(el('label', {}, ['Row animation', animSel]));

      wrap.appendChild(el('label', {}, ['Stagger between rows (ms)',
        el('input', { type: 'number', min: '0', max: '500', step: '10',
          value: String(d.stagger_ms == null ? 60 : d.stagger_ms),
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            d.stagger_ms = isNaN(n) ? 60 : Math.max(0, Math.min(500, n));
            notifyChange();
          } })]));

      wrap.appendChild(el('label', {}, ['Empty-state message',
        el('input', { type: 'text', value: d.empty_message || '',
          placeholder: 'No upcoming events — check back soon.',
          oninput: e => { d.empty_message = e.target.value; notifyChange(); } })]));

      function toggle(key, label, dflt) {
        const lbl = el('label', { class: 'be-row' });
        const cb = el('input', { type: 'checkbox',
          checked: (d[key] == null ? dflt : d[key]) ? 'checked' : null,
          onchange: e => { d[key] = e.target.checked; notifyChange(); } });
        lbl.appendChild(cb);
        lbl.appendChild(el('span', {}, [label]));
        return lbl;
      }
      wrap.appendChild(el('div', { class: 'be-library-fields' }, [
        el('div', { class: 'muted smaller' }, ['Per-row display']),
        toggle('show_image', 'Featured image', true),
        toggle('show_summary', 'Summary text', true),
        toggle('show_location', 'Location', true),
      ]));
      return wrap;
    }

    // ── Container block ───────────────────────────────────────────
    // Nested layout primitive: holds child blocks AND carries a deep
    // set of layout / visual / hover controls. The settings panels
    // are folded into <details> groups so the body stays compact even
    // when the admin is only adjusting one corner of the styling.
    function renderContainerBody(b) {
      const d = b.data;
      // Make sure the recursion target exists. Old container rows
      // saved before `data.blocks` was added would otherwise crash
      // findContainerBlocks.
      if (!Array.isArray(d.blocks)) d.blocks = [];

      const wrap = el('div', { class: 'be-body be-container-body' });

      // Helper: a single-row labelled control. Used by the panels below
      // so they all share alignment + spacing.
      function row(label, control, hint) {
        const r = el('div', { class: 'be-container-row' });
        r.appendChild(el('span', { class: 'be-container-row-lbl' }, [label]));
        r.appendChild(control);
        if (hint) r.appendChild(el('div', { class: 'be-container-row-hint muted smaller' }, [hint]));
        return r;
      }
      function selectInput(value, options, oninput) {
        const sel = el('select', { onchange: e => oninput(e.target.value) });
        options.forEach(([v, lbl]) => {
          const o = el('option', { value: v }, [lbl]);
          if (String(value) === String(v)) o.selected = true;
          sel.appendChild(o);
        });
        return sel;
      }
      function textInput(value, placeholder, oninput) {
        return el('input', {
          type: 'text', value: value == null ? '' : String(value),
          placeholder: placeholder || '',
          oninput: e => oninput(e.target.value),
        });
      }
      function numInput(value, min, max, oninput, suffix) {
        const inp = el('input', {
          type: 'number', value: value == null ? '' : String(value),
          min: String(min), max: String(max), step: '1',
          oninput: e => {
            const n = parseInt(e.target.value, 10);
            oninput(isNaN(n) ? 0 : n);
          },
        });
        return suffix ? el('span', { class: 'be-container-num-wrap' },
          [inp, el('span', { class: 'be-container-num-suffix muted smaller' }, [suffix])]) : inp;
      }
      function colorPair(value, oninput) {
        // <input type=color> + editable hex text + 🎨 token picker
        // + Clear, two-way bound. Accepts hex literals AND
        // `token:<key>` references (the public renderer translates
        // tokens to `var(--fe-color-<key>)` via the css_color filter).
        const wrapEl = el('span', { class: 'be-container-color' });
        const initialSwatch = _resolveSwatchHex(value) || '#5164ff';
        const swatch = el('input', { type: 'color', value: initialSwatch });
        const text = el('input', {
          type: 'text', class: 'be-container-color-text',
          maxlength: '64', spellcheck: 'false', autocomplete: 'off',
          placeholder: 'hex or token:color_brand', value: value || '',
        });
        function commit(v) {
          oninput(v);
          const swatchHex = _resolveSwatchHex(v);
          if (swatchHex) swatch.value = swatchHex;
          text.classList.remove('is-invalid');
        }
        swatch.addEventListener('input', () => {
          commit(swatch.value);
          text.value = swatch.value;
          notifyChange();
        });
        text.addEventListener('input', () => {
          let v = (text.value || '').trim();
          if (!v) { commit(''); notifyChange(); return; }
          if (_TOKEN_RE.test(v)) { commit(v); notifyChange(); return; }
          if (!v.startsWith('#')) v = '#' + v;
          if (_HEX_RE.test(v)) {
            const expanded = v.length === 4
              ? '#' + v[1] + v[1] + v[2] + v[2] + v[3] + v[3] : v.toLowerCase();
            commit(expanded);
            notifyChange();
          } else {
            text.classList.add('is-invalid');
          }
        });
        const tokenBtn = attachTokenButton(text, swatch);
        const clear = el('button', {
          type: 'button', class: 'btn btn-sm',
          onclick: () => { commit(''); text.value = ''; notifyChange(); }
        }, ['Clear']);
        wrapEl.appendChild(swatch);
        wrapEl.appendChild(text);
        wrapEl.appendChild(tokenBtn);
        wrapEl.appendChild(clear);
        return wrapEl;
      }

      // ── Label panel (admin-only) ──────────────────────────────────
      // Sits above Layout because it's the first thing an admin scans
      // when they open a container's settings: "what is this container
      // for?" Public render ignores the field; the structure tree uses
      // it as the row's primary heading when set, so admins can label
      // a container "Officers" or "Footer band" and see that label
      // immediately in the structure card.
      const labelPanel = el('details', { class: 'be-container-panel', open: 'open' }, [
        el('summary', {}, ['Label']),
      ]);
      const labelBody = el('div', { class: 'be-container-panel-body' });
      labelBody.appendChild(row('Label',
        textInput(d.label || '', 'Optional admin-only name (e.g. "Officers")',
          v => { d.label = v; notifyChange(); }),
        'Shows in the structure tree only — public visitors never see it.'));
      labelPanel.appendChild(labelBody);
      wrap.appendChild(labelPanel);

      // ── Card style panel ─────────────────────────────────────────
      // Opts the container into the site-wide Primary or Secondary
      // card design tokens. When set, the container picks up the
      // matching bg + border + shadow + hover lift centrally from
      // Design → Card styles, so every container with the same
      // setting updates together when the admin tweaks the tokens.
      // "None" leaves the per-container inline styles alone (admins
      // can still hand-tune bg / border / shadow on this same block).
      const cardStylePanel = el('details', { class: 'be-container-panel', open: 'open' }, [
        el('summary', {}, ['Card style']),
      ]);
      const cardStyleBody = el('div', { class: 'be-container-panel-body' });
      cardStyleBody.appendChild(row('Use card tokens',
        selectInput(d.card_style || '', [
          ['', 'None · custom (use the controls below)'],
          ['primary', 'Primary card · meeting-card look'],
          ['secondary', 'Secondary card · feature-card look'],
        ], v => {
          d.card_style = v || '';
          notifyChange();
        }),
        'Linking to a card token makes this container inherit the matching primary or secondary card visuals from Design → Card styles. Any per-container bg / border / shadow you set below still applies on top, so you can tweak this single container without losing the shared baseline.'));
      cardStylePanel.appendChild(cardStyleBody);
      wrap.appendChild(cardStylePanel);

      // ── Layout panel (display, flex/grid axes, gap) ──────────────
      const layoutPanel = el('details', { class: 'be-container-panel', open: 'open' }, [
        el('summary', {}, ['Layout']),
      ]);
      const layoutBody = el('div', { class: 'be-container-panel-body' });
      layoutBody.appendChild(row('Display',
        selectInput(d.display || 'flex', [
          ['flex', 'Flex'], ['grid', 'Grid'],
        ], v => { d.display = v; render(); notifyChange(); })));
      // Flex-only controls. Grid swaps in `grid-template-columns` below.
      const flexBox = el('div', { class: 'be-container-flex-controls' });
      flexBox.appendChild(row('Direction',
        selectInput(d.direction || 'column', [
          ['row', 'Row →'], ['column', 'Column ↓'],
          ['row-reverse', 'Row reverse ←'], ['column-reverse', 'Column reverse ↑'],
        ], v => { d.direction = v; notifyChange(); })));
      const _mobileDirRow = row('Mobile direction',
        selectInput(d.mobile_direction || '', [
          ['', 'Auto · stack as column (default)'],
          ['column', 'Column ↓'],
          ['column-reverse', 'Column reverse ↑ · bottom child first'],
          ['row', 'Row → · keep side-by-side'],
          ['row-reverse', 'Row reverse ← · keep side-by-side, swap order'],
        ], v => { d.mobile_direction = v; notifyChange(); }),
        'Applies at ≤720 px. Default collapses any row into a stacked column; column-reverse surfaces the bottom child first on phones.');
      _mobileDirRow.classList.add('be-container-row--mobile-section');
      flexBox.appendChild(_mobileDirRow);
      flexBox.appendChild(row('Wrap',
        (function () {
          const cb = el('input', {
            type: 'checkbox', checked: d.wrap ? 'checked' : null,
            onchange: e => { d.wrap = e.target.checked; notifyChange(); },
          });
          return el('label', { class: 'be-container-checkbox' }, [cb, el('span', {}, ['Wrap children to next line'])]);
        })()));
      flexBox.style.display = (d.display === 'grid') ? 'none' : '';
      layoutBody.appendChild(flexBox);

      // ── Grid controls (GUI-friendly column editor) ───────────────
      // The legacy single text input forced admins to type CSS like
      // `repeat(3, 1fr)`. The expanded UI gives a column-count stepper,
      // per-column track selectors with common presets (`1fr`, `2fr`,
      // `auto`, fixed px, percentages), a live proportion preview bar,
      // and an escape-hatch raw-CSS field for power users / values
      // that can't round-trip through the GUI parser.
      //
      // `d.grid_columns` stays a single CSS string (matching the
      // public renderer's contract). Round-tripping:
      //   • `repeat(N, X)`  → expanded to N copies of X
      //   • `1fr 2fr 1fr`    → split on whitespace
      //   • Anything containing parentheses (calc(), minmax(), etc.)
      //     pops the UI into Advanced mode automatically — round-
      //     tripping arbitrary CSS through chips would lose info.
      const TRACK_PRESETS = [
        { v: '1fr', label: '1fr · equal share' },
        { v: '2fr', label: '2fr · double share' },
        { v: '3fr', label: '3fr · triple share' },
        { v: 'auto', label: 'auto · size to content' },
        { v: 'min-content', label: 'min-content' },
        { v: 'max-content', label: 'max-content' },
        { v: '80px',  label: '80 px' },
        { v: '120px', label: '120 px' },
        { v: '160px', label: '160 px' },
        { v: '200px', label: '200 px' },
        { v: '240px', label: '240 px' },
        { v: '320px', label: '320 px' },
        { v: '25%', label: '25 %' },
        { v: '33%', label: '33 %' },
        { v: '50%', label: '50 %' },
        { v: '66%', label: '66 %' },
        { v: '75%', label: '75 %' },
      ];
      function parseTracks(s) {
        s = (s || '').trim();
        if (!s) return ['1fr', '1fr'];
        const m = s.match(/^repeat\(\s*(\d+)\s*,\s*(.+?)\s*\)$/);
        if (m) {
          const n = Math.max(1, Math.min(12, parseInt(m[1], 10)));
          return Array(n).fill(m[2].trim());
        }
        // Anything else with parens (calc / minmax / fit-content / …)
        // can't round-trip safely through track chips. Signal "complex"
        // so the UI falls back to advanced mode.
        if (s.includes('(') || s.includes(')')) return null;
        const parts = s.split(/\s+/).filter(Boolean);
        return parts.length ? parts : null;
      }
      function serializeTracks(tracks) {
        if (tracks.length > 1 && tracks.every(t => t === tracks[0])) {
          return 'repeat(' + tracks.length + ', ' + tracks[0] + ')';
        }
        return tracks.join(' ');
      }
      // Convert a track value to a relative weight for the preview bar.
      // `*fr` → fr value; `auto` / content keywords → 1; px → px/100; % → fraction.
      // Approximate but good enough for proportional visualisation.
      function trackWeight(t) {
        if (!t) return 1;
        if (/fr$/i.test(t)) return parseFloat(t) || 1;
        if (/^(auto|min-content|max-content)$/i.test(t)) return 1;
        if (/px$/i.test(t)) return Math.max(0.4, parseFloat(t) / 100);
        if (/%$/.test(t)) return Math.max(0.2, parseFloat(t) / 100);
        return 1;
      }

      const gridBox = el('div', { class: 'be-container-grid-controls' });
      // `forceAdvanced` lets the admin opt INTO the raw text input
      // even when the current value would round-trip cleanly. The
      // parser's `null` return is the AUTOMATIC trigger (calc/minmax/
      // etc. that the GUI can't represent); this flag is the manual
      // override. Both paths land in the same advanced branch below.
      let forceAdvanced = false;

      function renderGridBox() {
        gridBox.innerHTML = '';
        let tracks = parseTracks(d.grid_columns);
        const isAdvanced = forceAdvanced || tracks === null;
        if (isAdvanced) {
          gridBox.appendChild(row('Columns',
            textInput(d.grid_columns || 'repeat(2, 1fr)',
              'e.g. repeat(3, minmax(0, 1fr)) or calc(50% - 1rem) 1fr',
              v => { d.grid_columns = v; notifyChange(); }),
            'Raw CSS grid-template-columns — used for values the visual editor cannot round-trip (calc, minmax, fit-content, …).'));
          const visualBtn = el('button', {
            type: 'button', class: 'btn btn-sm be-grid-advanced-toggle',
            onclick: () => {
              const t = parseTracks(d.grid_columns);
              if (t) {
                // Round-trip cleanly back to the GUI.
                d.grid_columns = serializeTracks(t);
                forceAdvanced = false;
                renderGridBox();
                notifyChange();
              } else {
                // Value is too complex (calc / minmax / etc.) to
                // represent with chips. Reset to a known-good starting
                // point so the visual editor has somewhere to land,
                // and only commit that change when the admin OKs it.
                if (!confirm(
                  'The current value uses CSS the visual editor can\'t round-trip. ' +
                  'Reset to a 2-column layout (repeat(2, 1fr)) to use the visual editor?'
                )) return;
                d.grid_columns = 'repeat(2, 1fr)';
                forceAdvanced = false;
                renderGridBox();
                notifyChange();
              }
            },
          }, ['Switch to visual editor']);
          gridBox.appendChild(visualBtn);
          return;
        }

        // Column count stepper
        const stepper = el('div', { class: 'be-grid-stepper' });
        const minus = el('button', {
          type: 'button', class: 'btn btn-sm', 'aria-label': 'Remove column',
          onclick: () => {
            if (tracks.length > 1) {
              tracks.pop();
              d.grid_columns = serializeTracks(tracks);
              renderGridBox(); notifyChange();
            }
          },
        }, ['−']);
        const plus = el('button', {
          type: 'button', class: 'btn btn-sm', 'aria-label': 'Add column',
          onclick: () => {
            if (tracks.length < 12) {
              tracks.push('1fr');
              d.grid_columns = serializeTracks(tracks);
              renderGridBox(); notifyChange();
            }
          },
        }, ['+']);
        const countOut = el('span', { class: 'be-grid-count' },
          [String(tracks.length) + (tracks.length === 1 ? ' column' : ' columns')]);
        stepper.appendChild(minus);
        stepper.appendChild(countOut);
        stepper.appendChild(plus);
        gridBox.appendChild(row('Column count', stepper));

        // Equal-distribution quick presets — collapse to repeat(N, 1fr)
        // for the most common "I just want N evenly-spaced columns" path.
        const equalRow = el('div', { class: 'be-grid-presets' });
        [2, 3, 4].forEach(n => {
          const btn = el('button', {
            type: 'button',
            class: 'btn btn-sm' + (
              tracks.length === n && tracks.every(t => t === '1fr') ? ' active' : ''),
            onclick: () => {
              tracks = Array(n).fill('1fr');
              d.grid_columns = serializeTracks(tracks);
              renderGridBox(); notifyChange();
            },
          }, [String(n) + ' equal']);
          equalRow.appendChild(btn);
        });
        // Sidebar+main and main+sidebar shortcuts — common page recipes
        // that need a one-click setting rather than a 2-step (count → custom).
        const sidebars = [
          { tracks: ['260px', '1fr'], lbl: 'Sidebar + main' },
          { tracks: ['1fr', '260px'], lbl: 'Main + sidebar' },
          { tracks: ['1fr', '2fr'],   lbl: '1 : 2' },
          { tracks: ['2fr', '1fr'],   lbl: '2 : 1' },
        ];
        sidebars.forEach(p => {
          const isActive = tracks.length === p.tracks.length
                           && tracks.every((t, i) => t === p.tracks[i]);
          const btn = el('button', {
            type: 'button',
            class: 'btn btn-sm' + (isActive ? ' active' : ''),
            onclick: () => {
              tracks = p.tracks.slice();
              d.grid_columns = serializeTracks(tracks);
              renderGridBox(); notifyChange();
            },
          }, [p.lbl]);
          equalRow.appendChild(btn);
        });
        gridBox.appendChild(row('Quick presets', equalRow));

        // Per-track selectors — one row per column.
        const tracksWrap = el('div', { class: 'be-grid-tracks' });
        tracks.forEach((track, i) => {
          const trackRow = el('div', { class: 'be-grid-track-row' });
          trackRow.appendChild(el('span', { class: 'be-grid-track-label' },
            ['Col ' + (i + 1)]));
          const isPreset = TRACK_PRESETS.some(p => p.v === track);
          const sel = el('select', { class: 'be-grid-track-select' });
          TRACK_PRESETS.forEach(p => {
            const o = el('option', { value: p.v }, [p.label]);
            if (p.v === track) o.selected = true;
            sel.appendChild(o);
          });
          const customOpt = el('option', { value: '__custom' }, ['Custom value…']);
          if (!isPreset) customOpt.selected = true;
          sel.appendChild(customOpt);
          const customInp = el('input', {
            type: 'text', class: 'be-grid-track-custom',
            value: isPreset ? '' : track,
            placeholder: 'e.g. 180px or minmax(120px, 1fr)',
            oninput: e => {
              const v = (e.target.value || '').trim() || '1fr';
              tracks[i] = v;
              d.grid_columns = serializeTracks(tracks);
              updatePreview();
              notifyChange();
            },
          });
          customInp.style.display = isPreset ? 'none' : '';
          sel.addEventListener('change', e => {
            const v = e.target.value;
            if (v === '__custom') {
              customInp.style.display = '';
              customInp.focus();
              const cur = (customInp.value || '').trim() || '1fr';
              tracks[i] = cur;
            } else {
              customInp.style.display = 'none';
              tracks[i] = v;
            }
            d.grid_columns = serializeTracks(tracks);
            updatePreview();
            notifyChange();
          });
          trackRow.appendChild(sel);
          trackRow.appendChild(customInp);
          tracksWrap.appendChild(trackRow);
        });
        gridBox.appendChild(row('Track sizes', tracksWrap));

        // Live preview bar — segments scaled by track weight.
        const preview = el('div', { class: 'be-grid-preview' });
        function updatePreview() {
          preview.innerHTML = '';
          tracks.forEach(t => {
            const seg = el('div', { class: 'be-grid-preview-seg' });
            seg.style.flex = trackWeight(t) + ' 0 0';
            seg.appendChild(el('span', { class: 'be-grid-preview-label' }, [t]));
            preview.appendChild(seg);
          });
        }
        updatePreview();
        gridBox.appendChild(row('Preview', preview,
          'Approximate — `*fr` units fill remaining space at runtime; px/% sit at the size shown.'));

        // Advanced escape hatch — flips into raw-CSS mode without
        // touching the current value. Useful for `calc()`, `minmax()`,
        // `fit-content()`, named lines, etc.
        const advBtn = el('button', {
          type: 'button', class: 'btn btn-sm be-grid-advanced-toggle',
          onclick: () => {
            forceAdvanced = true;
            renderGridBox();
          },
        }, ['Edit raw CSS instead']);
        gridBox.appendChild(advBtn);
      }
      renderGridBox();
      gridBox.style.display = (d.display === 'grid') ? '' : 'none';
      layoutBody.appendChild(gridBox);

      layoutBody.appendChild(row('Justify',
        selectInput(d.justify || 'flex-start', [
          ['flex-start', 'Start'], ['center', 'Center'], ['flex-end', 'End'],
          ['space-between', 'Space between'], ['space-around', 'Space around'],
          ['space-evenly', 'Space evenly'],
        ], v => { d.justify = v; notifyChange(); })));
      layoutBody.appendChild(row('Align',
        selectInput(d.align || 'stretch', [
          ['stretch', 'Stretch'], ['flex-start', 'Start'],
          ['center', 'Center'], ['flex-end', 'End'], ['baseline', 'Baseline'],
        ], v => { d.align = v; notifyChange(); })));
      layoutBody.appendChild(row('Gap',
        textInput(d.gap || '1rem', 'e.g. 1rem, 16px, 0',
          v => { d.gap = v; notifyChange(); })));
      layoutPanel.appendChild(layoutBody);
      wrap.appendChild(layoutPanel);

      // ── Spacing + width panel ────────────────────────────────────
      const spacingPanel = el('details', { class: 'be-container-panel', open: 'open' }, [
        el('summary', {}, ['Spacing & width']),
      ]);
      const spacingBody = el('div', { class: 'be-container-panel-body' });

      // ── Padding (per-side box-style) ─────────────────────────────
      // Four numeric inputs (px) laid out around a centre label so
      // the admin can see at-a-glance which input drives which side.
      // Legacy `d.padding` (CSS shorthand) stays as a fallback in the
      // renderer when all four per-side fields are empty / 0; the
      // first time an admin touches these, we seed the per-side
      // fields by parsing the legacy shorthand so simple values
      // (`1rem`, `16px`, `24px 16px`) carry forward cleanly.
      function parseCssShorthand(raw) {
        // Returns [top, right, bottom, left] as CSS-value strings
        // ("16px", "1rem", "5%") preserving the original unit, or
        // null if the shorthand can't be parsed unambiguously.
        if (raw == null) return null;
        const s = String(raw).trim();
        if (!s) return null;
        const toCssVal = (tok) => {
          const m = tok.match(/^(-?\d+(?:\.\d+)?)(px|rem|em|vh|vw|%)?$/i);
          if (!m) return null;
          const unit = (m[2] || 'px').toLowerCase();
          return m[1] + unit;
        };
        const parts = s.split(/\s+/).map(toCssVal);
        if (parts.some(p => p == null)) return null;
        if (parts.length === 1) return [parts[0], parts[0], parts[0], parts[0]];
        if (parts.length === 2) return [parts[0], parts[1], parts[0], parts[1]];
        if (parts.length === 3) return [parts[0], parts[1], parts[2], parts[1]];
        if (parts.length === 4) return parts;
        return null;
      }
      // Seed per-side fields from the legacy `padding` shorthand on
      // first edit. Only runs when ALL four per-side fields are
      // undefined AND the legacy field parses cleanly — otherwise
      // the per-side fields stay empty so the legacy shorthand
      // keeps applying via the renderer's fallback.
      function seedPerSideFromLegacy(prefix, legacyKey) {
        const has = ['_top', '_right', '_bottom', '_left'].some(suf =>
          d[prefix + suf] !== undefined && d[prefix + suf] !== '');
        if (has) return;
        const parsed = parseCssShorthand(d[legacyKey]);
        if (!parsed) return;
        d[prefix + '_top']    = parsed[0];
        d[prefix + '_right']  = parsed[1];
        d[prefix + '_bottom'] = parsed[2];
        d[prefix + '_left']   = parsed[3];
      }
      seedPerSideFromLegacy('padding', 'padding');
      seedPerSideFromLegacy('padding_mobile', 'padding_mobile');

      // Each padding side stores a full CSS-value string ("16px",
      // "2rem", "5%", etc.) so admins can mix units freely. Legacy
      // saves carried bare integers (px); the splitter below treats
      // them as px so existing containers keep their look. Empty
      // string => unset; the renderer falls back to 0 / inherits.
      const PAD_UNITS = ['px', 'rem', 'em', 'vh', 'vw', '%'];
      function splitPaddingValue(value) {
        if (value === '' || value == null) return { num: '', unit: 'px' };
        if (typeof value === 'number') return { num: String(value), unit: 'px' };
        const s = String(value).trim();
        if (!s) return { num: '', unit: 'px' };
        const m = s.match(/^(-?\d+(?:\.\d+)?)(px|rem|em|vh|vw|%)?$/i);
        if (m) {
          const unit = (m[2] || 'px').toLowerCase();
          return {
            num: m[1],
            unit: PAD_UNITS.indexOf(unit) >= 0 ? unit : 'px',
          };
        }
        return { num: s, unit: 'px' };
      }
      function combinePaddingValue(num, unit) {
        const n = String(num == null ? '' : num).trim();
        if (n === '') return '';
        const u = PAD_UNITS.indexOf(unit) >= 0 ? unit : 'px';
        return n + u;
      }
      function sideInput(value, oninput) {
        const parts = splitPaddingValue(value);
        const inp = el('input', {
          type: 'number',
          value: parts.num,
          min: '0', max: '9999', step: '1',
          placeholder: '0',
          'aria-label': 'amount',
        });
        const sel = el('select', { 'aria-label': 'unit', class: 'be-pad-cell-unit-sel' });
        PAD_UNITS.forEach(u => {
          const o = el('option', { value: u }, [u]);
          if (u === parts.unit) o.selected = true;
          sel.appendChild(o);
        });
        function emit() {
          oninput(combinePaddingValue(inp.value, sel.value));
        }
        inp.addEventListener('input', emit);
        sel.addEventListener('change', emit);
        return el('span', { class: 'be-pad-cell-wrap' }, [inp, sel]);
      }
      function paddingBox(prefix, centerLabel) {
        // 3x3 grid: top row = top input, middle row = left | label |
        // right, bottom row = bottom input. Diagram + axis labels
        // around the box make it obvious which input is which side.
        const grid = el('div', { class: 'be-pad-box' });
        // Row 1: blank | "Top" label | blank
        grid.appendChild(el('div', { class: 'be-pad-box-axis be-pad-box-axis--top' }, ['Top']));
        // Row 2: top input
        grid.appendChild(el('div', { class: 'be-pad-box-cell be-pad-box-cell--top' },
          [sideInput(d[prefix + '_top'], v => { d[prefix + '_top'] = v; notifyChange(); })]));
        // Row 3: "Left" | center | "Right"
        grid.appendChild(el('div', { class: 'be-pad-box-axis be-pad-box-axis--left' }, ['Left']));
        grid.appendChild(el('div', { class: 'be-pad-box-cell be-pad-box-cell--left' },
          [sideInput(d[prefix + '_left'], v => { d[prefix + '_left'] = v; notifyChange(); })]));
        grid.appendChild(el('div', { class: 'be-pad-box-center' }, [centerLabel]));
        grid.appendChild(el('div', { class: 'be-pad-box-cell be-pad-box-cell--right' },
          [sideInput(d[prefix + '_right'], v => { d[prefix + '_right'] = v; notifyChange(); })]));
        grid.appendChild(el('div', { class: 'be-pad-box-axis be-pad-box-axis--right' }, ['Right']));
        // Row 4: bottom input
        grid.appendChild(el('div', { class: 'be-pad-box-cell be-pad-box-cell--bottom' },
          [sideInput(d[prefix + '_bottom'], v => { d[prefix + '_bottom'] = v; notifyChange(); })]));
        // Row 5: blank | "Bottom" label | blank
        grid.appendChild(el('div', { class: 'be-pad-box-axis be-pad-box-axis--bottom' }, ['Bottom']));
        return grid;
      }
      const padRow = el('div', { class: 'be-container-row be-container-row--pad-box' }, [
        el('span', { class: 'be-container-row-lbl' }, ['Padding']),
        paddingBox('padding', 'Padding'),
      ]);
      spacingBody.appendChild(padRow);
      const _mobilePadRow = el('div',
        { class: 'be-container-row be-container-row--pad-box be-container-row--mobile-section' }, [
          el('span', { class: 'be-container-row-lbl' }, ['Padding (mobile)']),
          paddingBox('padding_mobile', 'Mobile'),
          el('div', { class: 'be-container-row-hint muted smaller' },
            ['Leave any side blank to inherit the matching desktop value at ≤720 px.']),
        ]);
      spacingBody.appendChild(_mobilePadRow);
      spacingBody.appendChild(row('Width',
        (function () {
          const tog = el('div', { class: 'view-toggle be-container-width-toggle' });
          ['boxed', 'full'].forEach(m => {
            tog.appendChild(el('button', {
              type: 'button',
              class: 'btn btn-sm' + ((d.width_mode || 'boxed') === m ? ' active' : ''),
              'data-w': m,
            }, [m === 'boxed' ? 'Boxed' : 'Full width']));
          });
          tog.addEventListener('click', e => {
            const btn = e.target.closest('button[data-w]');
            if (!btn) return;
            d.width_mode = btn.dataset.w;
            tog.querySelectorAll('button').forEach(x =>
              x.classList.toggle('active', x === btn));
            maxWrap.style.display = (d.width_mode === 'boxed') ? '' : 'none';
            notifyChange();
          });
          return tog;
        })()));
      const maxWrap = el('div');
      maxWrap.appendChild(row('Max width',
        numInput(d.max_width == null ? 1160 : d.max_width, 320, 2400,
          v => { d.max_width = v; notifyChange(); }, 'px')));
      maxWrap.style.display = (d.width_mode || 'boxed') === 'boxed' ? '' : 'none';
      spacingBody.appendChild(maxWrap);
      spacingBody.appendChild(row('Height',
        textInput(d.height || '', 'auto — e.g. 100%, 400px',
          v => { d.height = v; notifyChange(); }),
        'Use 100% inside a grid cell so flex children can space-between to the bottom. Blank = auto-size to content.'));
      spacingBody.appendChild(row('Min height',
        textInput(d.min_height || '', 'none — e.g. 320px, 50vh',
          v => { d.min_height = v; notifyChange(); }),
        'Container will be at least this tall but can grow. Useful when content might be shorter than your visual target.'));
      spacingPanel.appendChild(spacingBody);
      wrap.appendChild(spacingPanel);

      // ── Background + border panel ────────────────────────────────
      const visualPanel = el('details', { class: 'be-container-panel', open: 'open' }, [
        el('summary', {}, ['Background & border']),
      ]);
      const visualBody = el('div', { class: 'be-container-panel-body' });
      visualBody.appendChild(row('Background',
        colorPickerWithDarkMode({
          value: d.bg_color || '',
          valueDark: d.bg_color_dark || '',
          mode: d.bg_color_dark_mode || 'same',
          placeholder: 'transparent',
          onChange: (light, dark, mode) => {
            d.bg_color = light; d.bg_color_dark = dark;
            d.bg_color_dark_mode = mode; notifyChange();
          },
        }),
        'Empty = transparent.'));
      visualBody.appendChild(row('Dynamic background',
        dynbgTrigger({
          key: d.bg_dynamic_key || '',
          overlay: d.bg_dynbg_overlay || '',
          colors: d.bg_dynbg_colors || [],
          scope: d.bg_dynbg_overlay_scope || '',
          noiseSize: d.bg_dynbg_overlay_size || '',
          noiseIntensity: d.bg_dynbg_overlay_intensity || '',
          // Legacy `bg_dynbg_randomize` (single flag) flows into both
          // new flags so older saved blocks keep the same behaviour
          // until the admin re-saves with the split toggles.
          randomizeColors:    !!(d.bg_dynbg_randomize_colors    || d.bg_dynbg_randomize),
          randomizePositions: !!(d.bg_dynbg_randomize_positions || d.bg_dynbg_randomize),
          // Opt-out flag — `animate: false` means "freeze movement".
          // Default is animated, so an empty/missing field means
          // "use the preset's keyframe animation".
          animateOff: d.bg_dynbg_animate === false,
          // Opt-in: when on, the saved palette pastelises only in
          // light mode. Dark mode keeps full-saturation values.
          pastelLight: !!d.bg_dynbg_pastel_light,
          // Per-preset knobs (dot size/gap, line angle/thickness, …).
          knobs: (d.bg_dynbg_knobs && typeof d.bg_dynbg_knobs === 'object') ? d.bg_dynbg_knobs : {},
          onChange: ({key, overlay, colors, scope, noiseSize, noiseIntensity,
                       randomizeColors, randomizePositions, animateOff,
                       pastelLight, knobs}) => {
            // Round-trip every dimension into the block data so the
            // serialised blocks_json carries the consolidated state.
            // Empty fields are stored as falsy values rather than
            // pruned so the block-data shape stays predictable.
            d.bg_dynamic_key = key || '';
            d.bg_dynbg_overlay = overlay || '';
            d.bg_dynbg_colors = colors || [];
            d.bg_dynbg_overlay_scope = scope || '';
            d.bg_dynbg_overlay_size = noiseSize || '';
            d.bg_dynbg_overlay_intensity = noiseIntensity || '';
            d.bg_dynbg_randomize_colors    = !!randomizeColors;
            d.bg_dynbg_randomize_positions = !!randomizePositions;
            // animate is opt-OUT — only persist `false` so the
            // common animated case stays absent from blocks_json.
            if (animateOff) {
              d.bg_dynbg_animate = false;
            } else {
              delete d.bg_dynbg_animate;
            }
            // pastel_light is opt-IN — only persist `true` so the
            // common (off) case stays absent from blocks_json.
            if (pastelLight) {
              d.bg_dynbg_pastel_light = true;
            } else {
              delete d.bg_dynbg_pastel_light;
            }
            // Per-preset knobs — opt-in; store the parsed object only
            // when non-empty so the common case stays absent from JSON.
            let _kn = null;
            if (knobs) {
              try { _kn = typeof knobs === 'string' ? JSON.parse(knobs) : knobs; }
              catch (_) { _kn = null; }
            }
            if (_kn && typeof _kn === 'object' && Object.keys(_kn).length) {
              d.bg_dynbg_knobs = _kn;
            } else {
              delete d.bg_dynbg_knobs;
            }
            // Keep the legacy single flag in sync — true when either
            // dimension is on — so old renderers that still read it
            // continue to work.
            d.bg_dynbg_randomize = !!(randomizeColors || randomizePositions);
            notifyChange();
          },
        }),
        'CSS-driven backdrop layered behind the bg colour. The picker also lets you pair an overlay (texture), override colours per container, randomise colours and/or positions on every load, or tune the noise grain size + intensity.'));
      visualBody.appendChild(row('Border width (all sides)',
        numInput(d.border_width == null ? 0 : d.border_width, 0, 16,
          v => { d.border_width = v; notifyChange(); }, 'px'),
        'Sets every side. Use the four overrides below to vary individual sides.'));
      // Per-side width overrides. Accept empty (= inherit the uniform
      // border width set above) or an integer (incl. 0 to remove the
      // border on that side only). When all four are blank, the
      // renderer emits the existing `border: <w>px <style> <color>`
      // shorthand — no change for containers that don't touch these.
      function emptyableNumInput(value, min, max, oninput, placeholder, suffix) {
        const inp = el('input', {
          type: 'number',
          value: (value === '' || value == null) ? '' : String(value),
          min: String(min), max: String(max), step: '1',
          placeholder: placeholder || '',
          oninput: e => {
            const raw = e.target.value.trim();
            if (raw === '') { oninput(''); return; }
            const n = parseInt(raw, 10);
            oninput(isNaN(n) ? '' : Math.max(min, Math.min(max, n)));
          },
        });
        return suffix ? el('span', { class: 'be-container-num-wrap' },
          [inp, el('span', { class: 'be-container-num-suffix muted smaller' }, [suffix])]) : inp;
      }
      visualBody.appendChild(row('Top width',
        emptyableNumInput(d.border_w_top, 0, 16,
          v => { d.border_w_top = v; notifyChange(); }, 'all sides', 'px')));
      visualBody.appendChild(row('Right width',
        emptyableNumInput(d.border_w_right, 0, 16,
          v => { d.border_w_right = v; notifyChange(); }, 'all sides', 'px')));
      visualBody.appendChild(row('Bottom width',
        emptyableNumInput(d.border_w_bottom, 0, 16,
          v => { d.border_w_bottom = v; notifyChange(); }, 'all sides', 'px')));
      visualBody.appendChild(row('Left width',
        emptyableNumInput(d.border_w_left, 0, 16,
          v => { d.border_w_left = v; notifyChange(); }, 'all sides', 'px')));
      visualBody.appendChild(row('Border style',
        selectInput(d.border_style || 'solid', [
          ['solid', 'Solid'], ['dashed', 'Dashed'], ['dotted', 'Dotted'],
          ['double', 'Double'], ['none', 'None'],
        ], v => { d.border_style = v; notifyChange(); })));
      visualBody.appendChild(row('Border color',
        colorPickerWithDarkMode({
          value: d.border_color || '',
          valueDark: d.border_color_dark || '',
          mode: d.border_color_dark_mode || 'same',
          placeholder: 'inherit',
          onChange: (light, dark, mode) => {
            d.border_color = light; d.border_color_dark = dark;
            d.border_color_dark_mode = mode; notifyChange();
          },
        })));
      visualBody.appendChild(row('Rounded corners',
        numInput(d.border_radius == null ? 0 : d.border_radius, 0, 64,
          v => { d.border_radius = v; notifyChange(); }, 'px')));
      visualBody.appendChild(row('Box shadow',
        selectInput(d.shadow || 'none', [
          ['none', 'None'], ['sm', 'Subtle'], ['md', 'Medium'],
          ['lg', 'Large'], ['xl', 'Dramatic'],
        ], v => { d.shadow = v; notifyChange(); })));
      visualPanel.appendChild(visualBody);
      wrap.appendChild(visualPanel);

      // ── Hover panel ──────────────────────────────────────────────
      const hoverPanel = el('details', { class: 'be-container-panel', open: 'open' }, [
        el('summary', {}, ['Hover']),
      ]);
      const hoverBody = el('div', { class: 'be-container-panel-body' });
      hoverBody.appendChild(row('Hover background',
        colorPair(d.hover_bg_color, v => { d.hover_bg_color = v; }),
        'Empty = no hover background change.'));
      hoverBody.appendChild(row('Hover border color',
        colorPair(d.hover_border_color, v => { d.hover_border_color = v; })));
      hoverBody.appendChild(row('Hover border width',
        emptyableNumInput(d.hover_border_width, 0, 16,
          v => { d.hover_border_width = v; notifyChange(); }, 'no change', 'px'),
        'Empty = no change on hover. Pair with rest-state width 0 to make a border appear only on hover.'));
      hoverBody.appendChild(row('Hover shadow',
        selectInput(d.hover_shadow || '', [
          ['', 'No change'], ['none', 'None'], ['sm', 'Subtle'],
          ['md', 'Medium'], ['lg', 'Large'], ['xl', 'Dramatic'],
        ], v => { d.hover_shadow = v; notifyChange(); })));
      hoverBody.appendChild(row('Hover lift',
        (function () {
          const cb = el('input', {
            type: 'checkbox', checked: d.hover_lift ? 'checked' : null,
            onchange: e => { d.hover_lift = e.target.checked; notifyChange(); },
          });
          return el('label', { class: 'be-container-checkbox' },
            [cb, el('span', {}, ['Translate up 2px on hover'])]);
        })()));
      hoverPanel.appendChild(hoverBody);
      wrap.appendChild(hoverPanel);

      // ── Children (recursive blocks list) ─────────────────────────
      const childrenPanel = el('div', { class: 'be-container-children' });
      childrenPanel.appendChild(el('div', { class: 'be-container-children-head' },
        [el('span', {}, ['Children'])]));
      const childList = renderBlocksList(d.blocks, b.id);
      childrenPanel.appendChild(childList.blocksEl);
      childrenPanel.appendChild(childList.addBar);
      wrap.appendChild(childrenPanel);

      return wrap;
    }

    // ── Button block ───────────────────────────────────────────────
    // A first-class CTA: label + url, primary/secondary/custom style.
    // The custom panel reveals once that style is picked so the colour
    // controls don't crowd a button that's just inheriting the theme.
    // Hover + shadow are paired pickers per state so it's clear which
    // colour fires when.
    function renderButtonBody(b) {
      const d = b.data;
      const wrap = el('div', { class: 'be-body be-button-body' });

      const row1 = el('div', { class: 'be-row' }, [
        el('input', {
          type: 'text', value: d.label || '', placeholder: 'Button label',
          oninput: e => d.label = e.target.value
        }),
      ]);
      wrap.appendChild(row1);

      const row2 = el('div', { class: 'be-row' }, [
        el('input', {
          type: 'text', value: d.url || '',
          placeholder: 'https://… or /relative/path',
          oninput: e => d.url = e.target.value
        }),
      ]);
      wrap.appendChild(row2);

      const newTab = el('label', { class: 'be-row be-checkbox-row' }, [
        el('input', {
          type: 'checkbox', checked: d.new_tab ? 'checked' : null,
          onchange: e => { d.new_tab = e.target.checked; }
        }),
        el('span', {}, ['Open in new tab']),
      ]);
      wrap.appendChild(newTab);

      // Style toggle (primary | secondary | custom). The toggle div
      // carries `view-toggle` so it picks up the existing
      // `.view-toggle .btn.active` styling (filled accent background) —
      // without that class the active state has no visual feedback and
      // the toggle looks unresponsive even when the click is firing.
      // Event delegation on the toggle div is also more robust than
      // per-button onclick closures: a single listener owns the state
      // and there's no chance of a stale `btn` reference if the row
      // ever gets re-rendered.
      const styleGroup = el('div', { class: 'be-row be-button-style-row' });
      styleGroup.appendChild(el('span', { class: 'be-button-style-lbl' }, ['Style']));
      const styleToggle = el('div', { class: 'view-toggle be-button-style-toggle' });
      ['primary', 'secondary', 'custom'].forEach(s => {
        styleToggle.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + ((d.style || 'primary') === s ? ' active' : ''),
          'data-bb-style': s,
        }, [s.charAt(0).toUpperCase() + s.slice(1)]));
      });
      styleToggle.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-bb-style]');
        if (!btn) return;
        const next = btn.dataset.bbStyle;
        d.style = next;
        styleToggle.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        customPanel.hidden = (next !== 'custom');
        notifyChange();
      });
      styleGroup.appendChild(styleToggle);
      wrap.appendChild(styleGroup);

      // Alignment toggle (left | center | right) — same pattern.
      const alignGroup = el('div', { class: 'be-row be-button-style-row' });
      alignGroup.appendChild(el('span', { class: 'be-button-style-lbl' }, ['Align']));
      const alignToggle = el('div', { class: 'view-toggle be-button-style-toggle' });
      ['left', 'center', 'right'].forEach(a => {
        alignToggle.appendChild(el('button', {
          type: 'button',
          class: 'btn btn-sm' + ((d.align || 'left') === a ? ' active' : ''),
          'data-bb-align': a,
        }, [a.charAt(0).toUpperCase() + a.slice(1)]));
      });
      alignToggle.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-bb-align]');
        if (!btn) return;
        d.align = btn.dataset.bbAlign;
        alignToggle.querySelectorAll('button').forEach(x =>
          x.classList.toggle('active', x === btn));
        notifyChange();
      });
      alignGroup.appendChild(alignToggle);
      wrap.appendChild(alignGroup);

      // Custom colour panel — revealed only when style === 'custom'.
      const customPanel = el('div', { class: 'be-button-custom-panel' });
      customPanel.hidden = (d.style !== 'custom');

      function colorRow(label, key) {
        const row = el('div', { class: 'be-button-color-row' });
        row.appendChild(el('span', { class: 'be-button-color-lbl' }, [label]));
        // Visual picker + editable hex input + clear button. Either
        // input commits to the data model (`d[key]`); the other side
        // mirrors back. The hex input accepts #rgb or #rrggbb (the
        // leading # is optional while typing and gets prepended on
        // validation). Invalid input flags the field but doesn't
        // clobber the stored value, so partial typing survives.
        const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
        const swatch = el('input', {
          type: 'color',
          value: d[key] || '#5164ff',
        });
        const text = el('input', {
          type: 'text', class: 'be-button-color-val',
          placeholder: 'inherit', maxlength: '7',
          spellcheck: 'false', autocomplete: 'off',
          value: d[key] || '',
        });
        function setStored(v) {
          d[key] = v;
          if (v) swatch.value = v;
          text.classList.remove('is-invalid');
        }
        swatch.addEventListener('input', () => {
          setStored(swatch.value);
          text.value = swatch.value;
        });
        text.addEventListener('input', () => {
          let v = (text.value || '').trim();
          if (!v) { d[key] = ''; text.classList.remove('is-invalid'); return; }
          if (!v.startsWith('#')) v = '#' + v;
          if (HEX_RE.test(v)) {
            const expanded = v.length === 4
              ? '#' + v[1] + v[1] + v[2] + v[2] + v[3] + v[3]
              : v.toLowerCase();
            setStored(expanded);
          } else {
            text.classList.add('is-invalid');
          }
        });
        text.addEventListener('blur', () => {
          // Snap back to the saved value so the field doesn't lie.
          text.value = d[key] || '';
          text.classList.remove('is-invalid');
        });
        const clear = el('button', {
          type: 'button', class: 'btn btn-sm',
          onclick: () => {
            d[key] = '';
            text.value = '';
            text.classList.remove('is-invalid');
            notifyChange();
          }
        }, ['Clear']);
        row.appendChild(swatch);
        row.appendChild(text);
        row.appendChild(clear);
        return row;
      }
      customPanel.appendChild(colorRow('Background', 'bg'));
      customPanel.appendChild(colorRow('Background (hover)', 'hover_bg'));
      customPanel.appendChild(colorRow('Text', 'text_color'));
      customPanel.appendChild(colorRow('Text (hover)', 'hover_text'));
      customPanel.appendChild(colorRow('Border', 'border'));
      customPanel.appendChild(colorRow('Border (hover)', 'hover_border'));
      customPanel.appendChild(colorRow('Shadow', 'shadow'));
      customPanel.appendChild(el('p', { class: 'muted small' }, [
        'Each colour is optional — leave blank to inherit the theme defaults. Borders render at 1px solid in the chosen colour. Shadow is the colour of the soft drop beneath the button.'
      ]));
      wrap.appendChild(customPanel);

      return wrap;
    }

    function serialize() {
      return JSON.stringify(state.sections);
    }

    render();
    return { serialize, getState: () => state.sections };
  }

  window.BlockEditor = { mount };
})();
