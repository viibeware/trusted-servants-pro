# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.9.1] — 2026-05-13

### Fixed — Frontend export/import now produces a verbatim 1-to-1 copy (bundle v3 → v4)

Two gaps in the frontend bundle were silently dropping per-page customisation on every restore. Both fixed; bundle format version bumped 3 → 4 (v3 bundles still import — the new fields fall back to defaults).

- **Per-page spacing columns** — `pad_top`, `pad_bottom`, `pad_x`, `section_gap`, `block_margin_y` (added during the page-builder cycle, ~80/96/16/32/12 defaults). Previously NOT exported and NOT imported — every restored page reverted to the model's defaults. Both sides now carry them. The import side falls back to the same defaults via a local `_opt_int` helper when a v3 bundle predates the change, so older bundles continue to import without surprises.
- **Homepage designation** — `SiteSetting.homepage_page_id` is a Page FK, and page IDs aren't portable across installs. Export now resolves the FK → page slug as `settings.homepage_page_slug` in the payload. Import side runs after pages are restored, looks up the page by slug, and writes the new id back to `SiteSetting.homepage_page_id`. When the slug is missing (v3 bundle) or doesn't match any imported page, the destination keeps whatever its own `_seed_homepage_page` wrote — `/` stays 200 either way.

Manifest scope note rewritten to call out the v4 additions and the v3 backwards-compat path. Format version bumped in both `manifest.json` (the zip header) and the inner `frontend.json` payload's `format_version` constant.

**No code changes needed for** the rest of the v1.9.0 surface area that lives inside `blocks_json` — Container per-side borders, hover border-width, mobile direction / padding, height / min-height, dark-mode colours; Hero dark-mode gradient + sub colour; Features / FAQ heading + subheading + items list; Meetings / Events filter + display toggles. These all ride along byte-for-byte inside the TEXT `blocks_json` column. The whole-site bundle (verbatim SQLite copy) likewise needs no changes — the new `homepage_page_id` column rides along with the raw `.db` file.

Verified by round-trip test on the live install: tweaked a page's spacing to `42/137/7`, exported, cleared the destination state, re-imported with `confirm=REPLACE`, confirmed the page's spacing was restored verbatim and `SiteSetting.homepage_page_id` was correctly re-pointed at the new page row (id changed from 11 → 23 due to the wholesale delete/replace; the FK followed via slug).

## [1.9.0] — 2026-05-13

### Changed — Homepage is now a Page (the legacy homepage admin + public renderer are retired)

The public `/` root is now driven by whichever `Page` row the admin designates as the homepage. The legacy homepage admin editor (`/tspro/frontend/homepage`) and its custom render pipeline are gone — the homepage uses the same page-builder editor as every other content page, with the same modals, the same per-block data shape, and the same `frontend/page.html` public render.

**Schema:**

- `SiteSetting.homepage_page_id` — new nullable `Integer` FK to `Page.id` (`ON DELETE SET NULL` so deleting the page doesn't break the column). Migration added to `_migrate_sqlite`.
- New `_seed_homepage_page(app)` runs in the boot sequence after `_seed_page_layouts`. Idempotent — if `homepage_page_id` is already set to a valid Page, no-op. Otherwise: adopts an existing `slug='home'` Page if one exists, or creates a fresh "Home" page (`slug='home'`, single hero block with welcoming default copy — `"You are not alone."` / `"Find meetings, connect with your community…"` — `published=True`, `layout_key='page-blank'`) and writes the ID. Every install — fresh or existing — has a homepage Page after first boot following this release.

**Public render:**

- `frontend.py::index()` loads the homepage Page and renders it through the same pipeline as `page_detail`: parses `blocks_json`, collects heading TOC, hydrates per-instance meetings groups + events lists, and renders `frontend/page.html`. The legacy hero / blocks / homepage-template chain is gone. When `homepage_page_id` is null (shouldn't happen post-migration), `/` renders an empty placeholder page rather than 500.

**Admin UI:**

- **Sidebar** (`_frontend_subnav.html`) — "Homepage" link now routes to `/tspro/frontend/pages/<homepage_page_id>/edit` (falls back to the Pages list if the column is unset). Active-state highlight tracks whether the admin is on the homepage's edit screen specifically vs any other page.
- **Pages list** (`frontend_pages.html`) — the current homepage row picks up an `is-homepage` class (subtle brand-tinted row background), a `chip-homepage` badge next to the title (`{{ icon('home') }} Homepage`), its slug column shows `/` rather than `/<slug>`, the View link points at the public `/`, and both Delete and Make-Homepage actions are hidden for that row (can't delete the active homepage; can't make a page its own homepage). Every other row picks up a Make-homepage button.
- **Page-edit screen** (`frontend_page_edit.html`) — banner reads `"Editing homepage"` instead of `"Editing page"`, slug shows as `/`, and gets the `chip-homepage` badge. The Make-homepage button sits inline with the status pills for non-homepage pages.
- **New route** `POST /tspro/frontend/pages/<id>/set-homepage` (`frontend_page_set_homepage`) — flips `SiteSetting.homepage_page_id` and, in the same transaction, publishes the page if it wasn't already published (admins shouldn't have to flip status separately just to designate a homepage).
- **CSS** — new `.chip-homepage` rule + `.tbl tr.is-homepage td` row tint (both brand-tinted via `color-mix` against `--brand`).

**Legacy retirement (473 lines deleted from `routes.py`):**

- `frontend_save` (legacy homepage content POST)
- `frontend_hero_save` (legacy hero settings POST)
- `frontend_hero_button_new` / `_edit` / `_delete` / `_buttons_reorder` (legacy hero CTA CRUD)
- `frontend_homepage` (the admin editor view itself)
- `frontend_homepage_template_save` (legacy homepage layout picker POST)
- `site_hero_bg_image` / `site_hero_bg_video` (legacy public asset routes)

**Templates deleted:** `frontend_homepage.html` (1,400+ line legacy editor), `frontend/index.html` (legacy public render), `frontend/_hero.html`, `frontend/homepages/classic.html`, `frontend/homepages/recovery-blue.html`, `frontend/homepages/_custom.html`, and the now-empty `frontend/homepages/` directory.

**Updated `url_for` callers** in `frontend_dashboard.html` (Web Frontend dashboard's Homepage card now points at `frontend_page_edit` with the current `homepage_page_id`) and `frontend_templates.html` (the explanatory note about "layouts vs templates" no longer references the legacy Homepage URL).

**Data left in place** for forward / backward compatibility:

- `SiteSetting.frontend_hero_*` columns (~25), `frontend_blocks_json`, `frontend_homepage_template`, and the `FrontendHeroButton` table stay on disk. No code reads them now, so they're inert — but keeping them lets the export bundle continue to serialise pre-retirement values and lets a future tooling pass migrate any custom legacy homepage content into the new Page model.
- `CustomLayout(kind='homepage')` rows (the homepage's drag-drop layout presets) stay in the DB. Inert in the new world; the page builder uses `kind='page'` layouts. Same export-bundle reasoning.

Verified by test client on fresh boot: `/` → 200 rendering the seeded Home page, `/tspro/frontend/homepage` → 404, `SiteSetting.homepage_page_id` populated with the seeded page's ID, Pages admin shows the badge + Make-homepage forms on non-homepage rows, edit screen shows "Editing homepage" banner, sidebar Homepage link targets the right page.

### Added — Hero edit modal — dark-mode controls for the heading gradient + subheading text

Three new colour inputs in the modal's Typography column: **Gradient start (dark)** + **Gradient end (dark)** under the Heading group, and **Text colour (dark)** under the Subheading group. The existing inputs were relabelled "(light)" so the pairs read clearly. Defaults match the existing hardcoded dark hero CSS (`#ffffff → #94a3b8` gradient, `#94a3b8` sub colour), so unedited blocks render identically in dark mode to before the controls existed. `_hero_block_modal_proxy` carries the three keys (`frontend_hero_heading_grad_start_dark` / `_end_dark` / `frontend_hero_subheading_color_dark`); `hero_block.html` emits matching inline CSS vars `--fe-hero-h-grad-s-dark` / `--fe-hero-h-grad-e-dark` / `--fe-hero-sub-color-dark`. The existing `html[data-theme="dark"] .fe-hero-heading` and `.fe-hero-sub` rules now read those vars (with the historic hex colours as fallbacks).

`page_hero_modal.js::syncPreview` stamps the same dark vars on the preview heading + sub, so the live preview reflects the admin's dark-mode choice when the admin theme is set to dark.

**Two subsequent fixes for the same feature:**

- **Dark-mode wins over dynamic-text** — when "Dynamic text colors" was enabled on the block, the `.fe-hero-text-light/dark .fe-hero-heading { … !important }` rule hardcoded light-mode colours regardless of theme, so the dark vars set inline never resolved. Added `!important` to the new dark-mode rule (with higher specificity from `html[attr] .class`) so dark-mode wins over dynamic-text under dark theme. Light theme keeps the dynamic-text behaviour unchanged.
- **Glyph clipping preserved** — first cut of the dark-mode override used `background:` shorthand with `!important`, which reset `background-clip` to `border-box` (also `!important`) and made the heading paint as a solid gradient rectangle instead of clipping to glyph shapes. Switched to `background-image:` (the same trick the dynamic-text rule uses) so the base rule's `background-clip: text` stays in effect.

### Fixed — Inclusion-style list pills (`.fe-pp-list-pills`) didn't obey dark mode

The dark-mode rule for the page-builder `list` block's pill style only matched `html[data-theme="dark"]` and missed `body.fe-frontend-force-dark`; and worse, it computed its background via `color-mix(var(--fe-color-surface, …) 70%, …)` — `--fe-color-surface` is a *light-mode* design token (usually near-white), so the resulting fill landed on a light grey even in dark mode. Refactored to read `--fe-dm-surface` / `--fe-dm-border` / `--fe-dm-text` directly (the same tokens every other dark surface uses — FAQ, meeting cards, contact cards), and paired the selector with `body.fe-frontend-force-dark` so both system-driven and admin-locked dark modes engage. Pills now sit on the same dark-navy + dark-slate family as the rest of the page.

### Changed — Page-builder pages drop the auto-divider between adjacent `.fe-section` blocks

The site-wide rule `.fe-section + .fe-section { border-top: 1px solid var(--fe-border); }` added a hairline between consecutive section blocks — fine on the homepage (Features → divider → CTA → divider → FAQ), but a surprise on admin-composed page-builder pages where every block (FAQ, Features, Meetings, Events) emits its own `<section class="fe-section">`. Two adjacent blocks inside the same `.fe-pp-section` got an uncontrollable hairline that admins couldn't see in the editor and couldn't remove from the container settings. Suppressed inside `.fe-pp` via `.fe-pp .fe-section + .fe-section { border-top: 0 }`; the homepage (no `.fe-pp` wrapper) keeps the original behaviour. Container borders are now the only border driver on page-builder pages — wrap blocks in a container if you want a visible divider.

### Fixed — Mobile `.fe-pp` padding + section-gap now honour admin's per-page settings

Two hardcoded mobile overrides defeated the per-page spacing controls (`pad_top` / `pad_bottom` / `section_gap` from the page-edit form):

- `@media (max-width: 640px) .fe-pp { padding: 56px 0 72px }` discarded the inline `--fe-pp-pad-top` / `--fe-pp-pad-bottom` variables — an admin who set `pad_top: 0` from the page-settings panel still saw 56 px on phones. Rule now reads from the same custom properties as desktop with tighter fallback values (56 / 72) so unset pages keep the historic look but explicit `0` actually flushes to the header.
- `@media (max-width: 640px) .fe-pp-section { margin-top: 24px }` pinned every section after the first to 24 px regardless of the admin's `section_gap`. Removed — desktop's `var(--fe-pp-section-gap, 32px)` carries through, so `section_gap: 0` produces zero margin on mobile too.

### Fixed — Icon picker modal opens behind the hero / features / FAQ edit modals

Both modals lived at the default `.modal` z-index 100; whichever opened later won the DOM-order tiebreaker. Per-page edit modals are included AFTER the icon picker in `frontend_page_edit.html`, so the picker was getting layered behind. Bumped `.icon-picker-modal` to `z-index: 200` so it always stacks above the standard `.modal` chain — same approach the `.fe-save-bar` already uses for "stays above any open modal". Sits below the dynbg picker (max-int z-index) so the more-modal-than-modal hierarchy stays intact. Affects every consumer of `[data-open-icon-picker]`: hero CTA editor, features card editor, FAQ item editor, nav-megamenu link editor.

### Added — Hero / Meetings / Events blocks available in the page builder

Three homepage section types are now first-class blocks the admin can drop onto any content page from the floating "Add blocks" palette. Each one shows up alongside the existing primitives (heading, paragraph, image, container, …) with its own Lucide icon and a server-side preview popover.

- **Hero** — per-instance content + background block. Mirrors the homepage hero's full surface area (heading, subheading, eyebrow + tagline toggle, heading typography with font / size / gradient, subheading typography with font / size / colour, dynamic-text contrast, desktop + mobile height sliders, all 7 background styles — Frosty / Solid / Gradient / Image / Sinewave / Video / Dynamic — particle overlay with effect + speed + size, and a rich CTA-button list with per-button icons + custom colours). Every field is independent of `SiteSetting.frontend_hero_*` — each page's hero is fully customisable on its own.
- **Meetings list** — live filtered card grid. Carries its own filter (today / next 24h / next 7 days / this week / all) + max-count + display toggles (group by day, type chip, schedule lines) + animation + stagger + heading + intro. Hydrated server-side per block instance via `blocks.filtered_meetings(d)` and rendered through the existing `frontend/blocks/meetings.html` partial.
- **Upcoming events** — same shape as the meetings block, hydrated via `blocks.filtered_events(d, site=…)`, rendered through `frontend/blocks/events.html`. Per-row toggles for featured image / summary / location.

**Wiring**:
- **`app/routes.py`** — `_PAGE_LAYOUT_BLOCK_TYPES` gains `hero` / `meetings` / `events`; `_PAGE_BLOCK_CATALOG` gains catalog entries (icon + description, surfaced in the palette); `_block_preview` handlers emit meaningful hover-popover text per block ("Today's Meetings · upcoming_today · max 6 · grouped by day", etc.); new `_hero_block_modal_proxy(data)` helper builds a `SimpleNamespace` mirroring `SiteSetting.frontend_hero_*` so the page-hero modal partial can reuse the homepage's markup verbatim.
- **`app/static/js/block_editor.js`** — three new `BLOCK_TYPES` entries; `blankBlock` defaults for each (Hero defaults match the homepage shape, Meetings + Events copy `blocks.MEETINGS_DEFAULTS` / `EVENTS_DEFAULTS`); `renderHeroBody` / `renderMeetingsBody` / `renderEventsBody` editor builders; dispatch in `renderBlockBody`.
- **`app/static/js/page_structure.js`** — `BLANK_DATA` factories for the three types (mirrors `block_editor.js`'s defaults so palette drops produce identical payloads regardless of entry point); `tspBlockLabels` entries; `makePillEl` routes hero pills to the dedicated `#page-hero-edit-modal` instead of the generic BlockEditor modal.
- **`app/templates/_frontend_structure_card.html`** — `page_pill` macro routes `pill.t == 'hero'` to `page-hero-edit-modal` while every other block type keeps using the generic modal.
- **`app/templates/frontend_page_edit.html`** — adds `_PAGE_BLOCK_LABELS` + `_editable` entries for the three new types; includes the new `_page_hero_modal.html` partial; loads `login_fx.js` (powers the hero's particle / sinewave engines) + the new `page_hero_modal.js`.
- **`app/frontend.py::page_detail`** — recursively scans `sections` for `meetings` / `events` blocks (incl. nested under containers), pre-fetches each instance's data via `filtered_meetings` / `filtered_events` keyed by block id, passes both maps to the template.
- **`app/templates/frontend/page.html::pp_block`** — three new branches: hero includes `frontend/blocks/hero_block.html` (a per-block-data sibling of `_hero.html`); meetings + events use Jinja `{% with %}` to scope `block_content` + `meetings_groups` / `events_list` per block instance before including the homepage section partials.
- **`app/templates/frontend/blocks/hero_block.html`** — new partial. Drives the same `.fe-hero` CSS recipe the homepage hero uses but reads every value from block data (heading, subheading, eyebrow, fonts, sizes, gradient + solid + image + sinewave + video + dynamic backgrounds, particle overlay, per-button icons + custom colours) so the public render matches the homepage's visual fidelity.

### Added — Hero block edit modal — verbatim copy of the homepage modal, wired to per-page data

The Hero block opens a dedicated `#page-hero-edit-modal` (defined in **`app/templates/_page_hero_modal.html`**) whose markup is copy-paste of the homepage's hero edit modal — live preview pane at the top, three-column layout (Text / Background / Buttons), every original control. The only adaptations:

- reads from a Python `SimpleNamespace` proxy (`_hero_block_modal_proxy`) instead of `site` directly, so the same Jinja can drive either context;
- no `<form action>` (values save with the parent page-edit form via `blocks_json`);
- the FrontendHeroButton table is replaced with a JS-driven button-list editor (per-block buttons live inside `data.buttons`, not a separate DB table);
- the bg-image / bg-video CRUD hits `/files/upload` (the standard media endpoint) instead of the hero-specific save endpoint.

**Two-way data binding** lives in the new **`app/static/js/page_hero_modal.js`** (deferred to `DOMContentLoaded` because the partial includes after the script tag), with these behaviours:

- Pill click → captures the active block id, reads `data-block-payload`, populates every `[data-hero-field]` input from the block's data, renders the buttons list, syncs image / video previews, paints the live-preview pane.
- Document-level capture-phase `input` + `change` listeners → write back to `blocks_json` AND directly mark the save bar dirty (`#fe-save-bar.hidden = false` + dispatched `input` event on `#page-edit-form`), so the save-bar reveal is decoupled from the persistence path.
- Live-preview pane re-renders on every edit (`syncPreview` ported from the homepage's `heroFullPreview` IIFE — heading / subhead / eyebrow text, font class swap, size + colour CSS vars, bg-style class + per-style paint, frosty blob hue vars, dynamic-text contrast class, particle FX lifecycle via `initLoginFX`).
- Synthetic `name="be-hero-<field>"` stamped on every radio at init time — the verbatim copy dropped the homepage's `name="frontend_hero_…"` in favour of `data-hero-field`, but radios still need a `name` to form a group (otherwise clicking Sinewave doesn't uncheck Frosty and `:checked` queries return stale state).
- Submit-restore listener — the BlockEditor in `#page-layout-edit-modal` auto-mounts on every pill click (via `page_structure.js`), and its inline submit handler in `frontend_page_edit.html` overwrites `hidden.value` with `editor.serialize()` right before submit. That serializer only knows about server-loaded data, so hero edits would be wiped without intervention. Tracked in a `heroEdits` Map; a late-fire `submit` + `formdata` listener on the page-edit form walks the just-overwritten JSON and patches every hero block's data back in.

### Added — Per-page Meetings list edit modal (`#page-meetings-edit-modal`)

The meetings-list page-builder block now opens a dedicated modal that's a verbatim copy of the homepage's `editor_meetings()` macro markup (lines 903-989 of `frontend_homepage.html`). Same 11 fields the homepage exposes — Section heading, Intro line, Filter (6 options: today / upcoming-today / next 24h / next 7 days / this week / all), Max meetings (1-30 slider), Schedule lines per card (1-7 slider), Animation (fade / slide / none), Stagger (0-200ms slider), Group by day toggle, Show meeting type chip toggle, Show schedule lines toggle, Empty-state message — bound through `data-meetings-field="<key>"` instead of `name="meetings_<key>"` so values flow into `block.data` and save with the parent page-edit form via `blocks_json`. New `_meetings_block_modal_proxy(data)` in `routes.py` returns `{**MEETINGS_DEFAULTS, **block_data}` as a dict shim so the homepage macro's `_ms.<key>` access pattern works character-for-character. Pill routing in `_frontend_structure_card.html::page_pill` + `page_structure.js::makePillEl` opens `page-meetings-edit-modal` for `meetings` pills, sticky Done footer at the bottom of the scrolling panel. **`page_meetings_modal.js`** handles two-way binding: pill click → `populateModalFromBlock` reads `block.data` into the inputs (slider readouts refresh live); document-level capture-phase input/change listener walks `[data-meetings-field]`, rebuilds the data shape, replaces the active block inside `blocks_json`, and flags the save bar dirty. Late-fire submit + formdata listener patches `meetings_modal_edits` back over `editor.serialize()` output so the BlockEditor's stale-state serialize can't wipe modal edits.

### Added — Per-page Upcoming Events edit modal (`#page-events-edit-modal`)

Identical pattern to the meetings modal for the upcoming-events block. Same dedicated modal verbatim-copied from the homepage's `editor_events()` macro (lines 992-1058 of `frontend_homepage.html`). 9 fields — Section heading, Intro line, Max events (1-24 slider), Animation (fade / slide / none), Stagger (0-200ms slider), Show featured image toggle, Show summary text toggle, Show location / online tag toggle, Empty-state message — bound through `data-events-field="<key>"`. New `_events_block_modal_proxy(data)` returns `{**EVENTS_DEFAULTS, **block_data}`. Pill routing updated to send `events` pills to `page-events-edit-modal`. **`page_events_modal.js`** mirrors `page_meetings_modal.js` but with one extra wrinkle: the three visibility toggles (`show_image` / `show_summary` / `show_location`) default to `true` when undefined to mirror the homepage's `is not defined or` Jinja guard — `populateModalFromBlock` treats `null` as `true` for those keys specifically so a fresh events block doesn't appear to have everything off until the admin ticks the boxes.

### Added — Per-page Features cards block (`#page-features-edit-modal`)

Verbatim copy of the homepage Features section's editor surface AND public render. Modal markup mirrors `editor_features()` + `_feature_card_row()` macros (lines 629-735 of `frontend_homepage.html`) — heading + subheading at the top, drag-to-reorder list of up to 6 cards, each card carrying icon (via shared `[data-open-icon-picker]` trigger), title, Markdown body with side-by-side live-preview MD editor, optional URL + new-tab toggle. Each top-level field bound through `data-features-field`; each per-card field through `data-features-card-field`. **`page_features_modal.js`** clones the empty `<template data-features-card-template>` once per saved item on pill click (template's `__IDX__` placeholder gets a unique counter so the icon picker's `#feat-card-<idx>-icon` ID selectors stay collision-free); `tspInitMdEditors(node)` wires up the freshly-cloned card's markdown preview tabs. Add / remove / pointer-driven drag-reorder; on every change `readModal()` walks the DOM cards in order and rebuilds `block.data.items[]`. **Public render** in `frontend/page.html::pp_block` re-shapes the per-page block's data as `{'features': d}` and `{% include "frontend/blocks/features.html" %}` — the same partial the homepage uses — so the page-builder render is byte-for-byte identical (same `.fe-features-grid`, same on-brand icon colour, same markdown body rendering).

Icon-preview helper exposed: `window.tspRenderIconHtml(ref)` in `app.js` lets the features (and FAQ) modal repaint the icon preview from saved data — the picker only paints when it changes the input, so without this helper a card cloned from saved data would show a blank icon spot while the hidden input still carried the saved ref.

### Added — Per-page FAQ accordion block (`#page-faq-edit-modal`)

Verbatim copy of the homepage FAQ section's editor + public render. Modal mirrors `editor_faq()` + `_faq_item_row()` macros (lines 1075-1156 of `frontend_homepage.html`) — drag-to-reorder list of up to 20 accordion items, each carrying icon (with optional size override), question text, side-by-side Markdown answer editor. Per-item fields bound through `data-faq-card-field` (question / answer / icon / icon_size); the homepage version had no top-level heading or subheading override (its public partial carried a hardcoded section title "Frequently asked questions" + intro), so the page-builder version **adds heading + subheading inputs** at the top of the modal — empty values fall back to the homepage's hardcoded strings, so unedited blocks still produce a valid section-head. `frontend/blocks/faq.html` now reads from optional `block_content.faq_heading` / `block_content.faq_subheading` keys with the original strings as fallbacks; homepage doesn't pass those keys so its render is byte-identical. **`page_faq_modal.js`** mirrors the features modal — clone-template pattern, MD editor init, drag-reorder, late-fire submit/formdata patch — adapted for the simpler 4-key item schema. The accordion toggle handler in `frontend/base.html` is document-level (`[data-faq-toggle]`), so the per-page FAQ block's accordion animates exactly like the homepage's without any extra wiring.

### Added — Container — per-side border-width controls + hover border width

The container editor's Visual panel now exposes four "emptyable" number inputs — `border_w_top` / `border_w_right` / `border_w_bottom` / `border_w_left` (each 0-16, blank = inherit the uniform `border_width` set above). The existing "Border width" control was relabelled "Border width (all sides)" with a hint explaining the overrides below. Empty / 0 / explicit-number all carry distinct meanings: blank = inherit; 0 = explicit "no border on this side"; any positive int = explicit width. A new `emptyableNumInput()` helper inside `renderContainerBody` keeps the empty-vs-0 distinction (the existing `numInput()` coerced NaN to 0). When the four resolved widths are all equal, the renderer keeps the legacy `border: <w>px <style> <color>` shorthand (zero diff for containers that haven't customised the new fields). When they differ, it switches to `border-style: <style>` + `border-width: <T>px <R>px <B>px <L>px` four-value shorthand + `--block-cont-border-color: <colour>` variable (the colour is moved into a CSS variable so the existing `:hover` rules can swap it).

**Hover border width** added as a fifth control under the Hover panel — `hover_border_width` (0-16, blank = no hover change). Pairs with `border_width: 0` at rest + non-zero hover to make a border appear only on hover. Renderer emits `border-style: solid` + `border-width: 0px 0px 0px 0px` rest declarations even with zero rest-state widths (so the hover swap has a `border-style` to paint with — default `border-style: none` would keep the hover-width invisible). `border-width` itself joins the transition list (180 ms ease) so the rest→hover swap animates instead of jump-cutting. New `.block-container--hover-border-width:hover { border-width: var(--block-cont-hover-border-width); }` CSS rule.

### Changed — Container hover effects — variable-driven, win over inline rest state

The container's hover-bg / hover-border-colour / hover-shadow rules weren't applying because the rest state was emitted as **direct inline properties** (`background-color: #fff; border: 4px solid #000; box-shadow: var(--block-cont-shadow); …`), specificity 1,0,0,0, defeating the `.block-container--hover-*:hover` rules at 0,0,2,0. Refactored the renderer (both `_blocks.html` for the admin/editor preview and `frontend/page.html::pp_container_styles` for the public render) to emit those three properties as **inline CSS variables** only — `--block-cont-bg`, `--block-cont-border-color`, `--block-cont-shadow`, `--block-cont-border-width` — with a global `.block-container` rule consuming them for the rest state via `var(--block-cont-bg, transparent)` etc. The existing `:hover` rules now win on the cascade since inline no longer declares the property directly; admin's hover overrides (background / border colour / border width / shadow / lift) all visibly apply now. Existing dark-mode rules (`[style*="--tsp-bg-dm"]` + `!important`) keep working unchanged.

### Changed — Hero block edit modal — polish pass (sticky Done footer, symmetric padding, true-token preview, debug outline gone)

Four small refinements to the per-page hero edit modal added earlier in this release:

- **Sticky Done footer** — the unified action row now pins to the bottom of the scrolling panel with a frosted-glass background, top border, and soft drop-shadow so the Done button is reachable at any scroll depth, especially when the buttons list grows tall. Negative horizontal margins pull the footer through the card's 2 rem padding to span panel edge-to-edge; the negative bottom margin eats `padding-bottom` so the footer pins to the panel's true bottom edge (no empty strip below). Dark-mode variant tunes the panel mix + shadow for low-light surfaces.
- **Symmetric horizontal padding** — `.fe-page-edit-modal-panel > .card` was carrying a `padding-right: 56px` override left over from when the close button was `position: absolute` (it reserved room so the visibility toggle in `.card-head` wouldn't sit under the button). The close button has since switched to `position: sticky` with its own clearance, and `.card-head` carries its own `padding-right: 64px`, so the card-level override was creating an asymmetric body (32 px left / 56 px right) that made every input row look off-centre. Override removed; body content is now centred inside symmetric 2 rem horizontal padding, and the sticky-footer margins were retuned (`-2rem` on both sides) to match.
- **Live preview now resolves design tokens** — `.fe-btn-primary` reads through `var(--fe-color-btn-primary-bg, var(--fe-ink))`; those tokens are inlined as CSS custom properties on the public `<body>` style via `design_css_vars(site)`, but the admin context has none of them, so the preview button was falling through to the fallback (`var(--fe-ink)`, which is itself undefined in admin) and rendering a generic dark fill instead of the admin's chosen brand colour. Stamped the same `design_css_vars(site)` string onto the preview's `.frontend-body` wrapper in `_page_hero_modal.html` so the preview button, ghost button, and yellow button now resolve to the same colours, shadows, hover lifts, and radii the public render uses.
- **Debug outline removed** — the dashed `1px outline` I had stamped on `.hero-full-preview .fe-hero-inner` to visualise the 820 px max-width bound during development was still shipping; it read as a stray dotted rectangle inside the preview. Outline + dark-mode variant removed.

### Added — `/homepage-v2` — homepage cloned as a regular Page

Per-page hero / meetings / events blocks make it possible to recreate the homepage as a content Page that lives under the standard page editor. A one-shot script seeded `/homepage-v2` as a **draft** Page (id=11) by reading `SiteSetting.frontend_blocks_json` and translating each homepage section into Page-builder primitives:

- `features` (3 items) → section container → heading + subhead → 3-col grid of card-containers (icon + title + body + optional CTA each).
- `cta` → section container → heading + body + row-container holding primary + secondary buttons.
- `stats` (4 items) → 4-col grid of card-containers (big-number heading + label paragraph).
- `quick_links` (4 items) → 4-col grid of card-containers (glyph + title + body + Open button).
- `_meetings` / `_events` → placeholder containers documenting the carried-over config (filter, max_count, animation, etc.). Now that the live data-driven blocks exist, the admin can swap each placeholder for a real `meetings` / `events` block via the palette.
- `testimonials` (3) → 3-col grid of card-containers (quote + bold attribution, `space-between` justify so attribution pins to the bottom — uses the new container Height field).
- `faq` (4) → single column of Q+A pair-containers.
- `inclusion` → section container → icon + heading + body + pill-style list of 7 tag chips.

Every container that visually wants a "card" surface gets `height: 100%`, `shadow: sm`, `border_radius: 16`, and `bg_color_dark: var(--fe-color-card-dark)` so dark-mode just works. Each container also carries a friendly **Label** so the editor's structure tree reads as "Section · Features", "Quick links grid", etc. instead of a wall of unlabeled rows. Live homepage at `/` is untouched — `SiteSetting.frontend_blocks_json` is byte-for-byte identical.

Deferred to a follow-up: a `SiteSetting.homepage_page_id` column + route flip at `/` so the admin can promote a Page row to be the homepage once they're done iterating on it.

### Added — Container — Height + Min-height fields for stretching to fill grid cells

Two new free-form CSS length fields in the container's **Spacing & width** panel: **Height** and **Min height**. Both blank by default (auto-size to content, today's behaviour). The Height field unblocks the common pattern where a 3-column grid of cards uses `justify-content: space-between` on each card's flex column to pin a button to the bottom edge — the grid stretches every cell to the tallest sibling's height by default, but a nested container inside the cell still sizes to its own content unless it explicitly opts in. Setting Height to `100%` makes the inner container fill the cell, which gives `space-between` somewhere to distribute children.

- **`app/static/js/block_editor.js`** — `container` blank-block gains `height: ''` + `min_height: ''`. `renderContainerBody` appends two new rows under Max width: Height (placeholder `auto — e.g. 100%, 400px`) and Min height (placeholder `none — e.g. 320px, 50vh`). Both accept any CSS length so `min(50vh, 600px)` / `calc(...)` round-trip cleanly.
- **`app/templates/_blocks.html`** + **`app/templates/frontend/page.html`** — both container renderers append `height: <value>` / `min-height: <value>` to the inline style only when the field is non-empty, so unset fields don't paint a redundant `height: auto` rule.

Existing containers are unaffected (both fields default to blank).

### Added — Container — Mobile direction + mobile padding overrides (with visual divider in the editor)

Two new optional fields on every container that target the ≤720 px breakpoint:

- **Mobile direction** (Layout panel, flex-only) — overrides the historic "all flex containers collapse to column on mobile" default. Options: `Auto` (today's behaviour), `Column`, `Column reverse · bottom child first`, `Row · keep side-by-side`, `Row reverse · keep side-by-side, swap order`. Lets admins keep a row layout on phones, or surface the right/bottom child first when a row collapses.
- **Padding (mobile)** (Spacing panel) — free-form CSS-shorthand override applied at ≤720 px. Blank inherits the desktop padding so existing containers don't shift.

Mobile rows sit under a subtle dashed divider in the editor so the "desktop value / mobile override" pairs read as related controls rather than blending into the rest of the panel.

- **`app/static/js/block_editor.js`** — `container` blank-block gains `mobile_direction: ''` + `padding_mobile: ''`. New select + text rows added to the Layout (inside flexBox) and Spacing panels respectively; both rows pick up a new `be-container-row--mobile-section` modifier class.
- **`app/templates/_blocks.html`** + **`app/templates/frontend/page.html`** — padding now emits as a CSS custom property (`--block-cont-padding`) instead of a direct `padding:` rule so the mobile media query can override it without an inline-style specificity war. `--block-cont-padding-mobile` and `--block-cont-flex-dir-mobile` only emit when the admin set them; unset values fall back to today's behaviour.
- **`app/static/css/frontend.css`** — desktop reads `padding: var(--block-cont-padding, 1rem)`; the existing `@media (max-width: 720px)` block now reads `padding: var(--block-cont-padding-mobile, var(--block-cont-padding, 1rem))` and `flex-direction: var(--block-cont-flex-dir-mobile, column)`. Grid containers continue to collapse to a single column on mobile (unchanged).
- **`app/static/css/app.css`** — new `.be-container-row--mobile-section` rule (dashed `border-top` + extra top spacing) applied to both mobile-override rows for visual grouping.

Existing containers are unaffected — both new fields default to blank.

### Fixed — Uploaded SVGs with `width="100%" height="100%"` collapsed to 0×0 inside flex / grid items

Affinity Designer, Serif, and several other SVG editors export with `width="100%" height="100%"` on the root `<svg>` (only the `viewBox` carries the pixel size). When loaded through an `<img>`, such files have no intrinsic dimensions — only an aspect ratio — so placing them inside a flex item without a definite parent width collapses them to 0. 29 of 30 uploaded SVGs on the live deployment had this defect; the heart graphic in `/for-family-and-friends`'s right-hand container was the visible symptom.

- **`app/routes.py::_normalize_svg_dimensions`** — new helper next to `_sanitize_svg`. Conservative regex rewrite that only fires when the root `<svg>` has BOTH `width="100%"` AND `height="100%"` AND a parseable `viewBox`. Replaces the percentages with the viewBox's width + height values so the SVG carries real intrinsic pixels. Inner `<svg>` elements, partial-percent values, and pixel-valued files are left untouched. Whole-number values format without trailing `.0` to keep diffs minimal.
- **Upload paths wired in** — `_save_upload` (library + media via `_apply_file_upload`), `media_upload` (the `/files/upload` endpoint the page builder's image picker hits), and `frontend_custom_icon_upload` (which already runs `_sanitize_svg`). Normalization runs **before** the SHA-256 dedup hash so re-uploading the same broken SVG dedupes against the already-fixed copy rather than the pre-fix bytes.
- **One-shot backfill** — walked every `*.svg` in `UPLOAD_FOLDER` through the same helper; 29 files rewritten in place, 1 left alone (already had pixel dims).

### Fixed — Page-builder Save bar reloaded the page out from under any open modal

The yellow save bar's "stay open after save" branch only kicked in when every dirty form lived inside a modal — but the page-builder's BlockEditor lives inside `#page-layout-edit-modal` while the outer `#page-edit-form` is rendered in the main page chrome. Editing blocks inside the modal re-dispatches `input` events to the outer form (so the bar lights up), but hitting Save then reloaded the whole page, dismissing the modal mid-edit.

- **`app/static/js/app.js::feSaveBar`** — `stayOpen` now ALSO returns true when any `.modal.open` is currently visible, not just when the dirty form itself lives inside a modal. Matches the intent of the existing in-code comment ("the visitor opened the modal to edit one block and would be jarred by it disappearing on save"). On save, the bar animates out, the modal stays in front, and the BlockEditor keeps its in-memory state for the next round of edits.

### Added — `/for-family-and-friends` Page seeded via the content-page builder

New public Page at `/for-family-and-friends` carrying the verbatim copy from the matching page on dccma.com. Built entirely from existing block types (no new ones) and grouped via `container` blocks per the page-builder convention.

- **Page row** — title "For Family and Friends", `is_published=True`, `is_private=False`, `template=standard`, `layout_key=custom`. One section (no `sec.title` — content is grouped via containers per the project's "containers only, never section titles" rule).
- **Structure** — three top-level containers: an intro container (H2 "Is someone you care about suffering from addiction?" + 4 verbatim paragraphs), a mid container (H3 pull-quote heading + 2 verbatim paragraphs), and a Resources container (H2 + 3 paragraphs with **bold** leads via markdown for CM-Anon / Alanon / Nar-Anon).
- **No images** — text only, matching the request to skip image import.

Verified: `GET /for-family-and-friends` returns 200; all three headings render with the expected hierarchy (H2 / H3 / H2) and slug-anchor ids.

### Added — `/newcomer` Page seeded via the content-page builder

New public Page at `/newcomer` matching the structure of the original DC CMA newcomer landing page. Built entirely from the existing block library (no new block types) so the admin can refine every section through the standard page editor.

- **Page row** — title "New to CMA?", `is_published=True`, `is_private=False`, `bg_image_filename` set to the cloud-splash hero so the page sits over the same atmospheric backdrop as the source. 10 sections: New to CMA? (hero with parachute graphic + Find a Meeting + Helpline CTAs), What is CMA?, Anonymity · Love · Connection (cards-styled list), Am I an addict?, There is a solution, One day at a time, Ninety meetings in ninety days, People places and things, Together we can, and Newcomer Resources (3-column container with the PDF thumbnails). Each section uses some combination of `heading`, `image`, `paragraph`, `list`, `button`, and `container` blocks.
- **Assets** — 20 SVG / JPG image assets pulled from the source site into `/data/uploads` with UUID-prefixed stored filenames and registered as `MediaItem` rows (sha256, size, mime). Blocks reference them via the anonymous-readable `/pub/<original_filename>` route.
- **Body copy** — section headings, button labels, and links match the source page; body paragraphs are seeded with brief original framing copy the admin can replace through the rich-text editor with their preferred wording.

Verified: `GET /newcomer` returns 200 with all 10 sections rendered and every image asset resolving via `/pub/<filename>` (200 each).

### Added — Fellowships Index — admin-curated list of sister recovery fellowships, public `/fellowships` page, searchable

New top-to-bottom feature for surfacing peer recovery fellowships (Crystal Meth Anonymous, AA, NA, In The Rooms, etc.) on the public site. Edited from Settings → Global as a repeatable row table; rendered publicly at `/fellowships` through one of two admin-selectable layouts; auto-included on `/siteindex` and in the global `Cmd/Ctrl+K` search.

**Data model.** New `Fellowship` table — `name`, `is_virtual`, `country`, `state_region`, `url`, `sort_order`, timestamps. Virtual rows are online-only fellowships (no geography); regional rows carry a country + state/province/region. `db.create_all()` covers fresh installs; existing installs pick the table up on next boot too.

- **`app/models.py`** — new `Fellowship` model alongside `IntergroupOfficer`. Ten new `SiteSetting.frontend_fellowships_*` columns control the public surface: enable toggle, template key, container width / max-width / padding-%, heading + subheading, default sort mode (`name-asc` / `name-desc` / `country-asc` / `newest` / `oldest`), and dynbg key + config JSON.
- **`app/__init__.py::_migrate_sqlite`** — ALTER TABLE entries for every new `site_setting` column so existing deployments upgrade cleanly. The new `fellowship` table itself rides on the existing `db.create_all()` boot step (idempotent CREATE TABLE IF NOT EXISTS).

**Admin section (Settings → Global).** Repeatable row table mirroring the Intergroup Officers pattern (`app/templates/locations.html`). Each row: name (required), a Virtual/Regional `mode-toggle` switch, country, state/province/region, website URL, and a remove button. Toggling Virtual hides the country/region cells via JS and keeps a hidden `fellowship_is_virtual` input in lockstep with the visual checkbox — exactly one value per row, so the server-side parallel-array reconciliation never shifts when virtual/regional rows are mixed.

- **`app/templates/locations.html`** — new section card under Intergroup Officers, with `+ Add fellowship` / remove-row JS and the Virtual toggle's visibility sync. Hidden template row stays in the DOM for cloning; server-side blank-name drop guards against the stray empty row.
- **`app/routes.py::fellowships_save`** — POST handler at `/tspro/fellowships/save`. Reconciles parallel form arrays (`fellowship_id` / `_name` / `_is_virtual` / `_country` / `_state_region` / `_url`), drops blank-name rows, deletes existing ids that aren't in the submission, and wipes country/region on virtual rows so a toggle back to regional starts clean. Gated by the existing `_can_edit_locations()` permission.
- **`app/routes.py::locations`** — now also loads `Fellowship` rows ordered by `sort_order` and passes them through to the template.

**Frontend templates page.** New "Fellowships list (/fellowships)" card on `/tspro/frontend/templates` — same chrome as every other list template (Stories, Blog, Archive, Site Index).

- **`app/frontend.py`** — new `FELLOWSHIPS_LIST_TEMPLATES` catalog with two entries: `sidebar` (sticky rail with search + Virtual/Regional toggle + per-country pills + sort selector, default) and `compact` (top filter strip over a dense single-column list).
- **`app/routes.py`** — `frontend_templates` route imports the new catalog, passes it + the active key + the per-template settings (`template_settings(s, "fellowships_list", key)`) into the template; `_TEMPLATE_KINDS` + `catalog_map` in `frontend_template_settings_save` extended so the shared Customize panel (background, fonts, sizes, dynbg) works for fellowships too. New `/tspro/frontend/fellowships-list-template` POST handler persists layout / publish toggle / width mode + max-width + padding-% / heading + subheading / default sort mode / dynbg key + config.
- **`app/templates/frontend_templates.html`** — new card before the templates-page footer with a layout picker (thumb mocks for both variants), the standard `tpl_customize_panel`, a Page heading fieldset, the standard Container width fieldset, a Default sort fieldset (5 options), a Publish toggle (`/fellowships` 404s when off), and a Preview link that shows up only when published.

**Public `/fellowships` page.** `@bp.route("/fellowships")` in `app/frontend.py`, decorated with `@public_section("Fellowships", gate=…)` so it auto-appears on `/siteindex` and is searchable, with the same `frontend_fellowships_enabled` gate the route enforces.

- **`app/frontend.py::fellowships_list`** — pulls Fellowship rows ordered by `sort_order`, applies the configured initial sort, buckets by country (Virtual gets its own bucket), builds per-row punctuation-stripped search blobs, resolves the chosen layout partial + dynbg, and renders the dispatcher.
- **`app/templates/frontend/fellowships_list.html`** — dispatcher template. Ships the shared filter + sort engine (search input, country pills, type-toggle checkboxes, sort `<select>`) as a single inline `<script>` keyed off `data-fellowships-*` attributes, so any new layout that drops the same hooks gets the same UX for free. Keyboard `/` focuses the search input (matches `/archive`).
- **`app/templates/frontend/fellowships/sidebar.html`** — default layout. Sidebar rail (header, search, Show: Virtual/Regional checkboxes with counts, Sort dropdown, country-pill list) on the left; main column groups cards under country headings with a chip per row (`Virtual` chip is green-tinted, `Regional` is accent-tinted). Each card carries name, region line, and a "Visit website ↗" link when set.
- **`app/templates/frontend/fellowships/compact.html`** — second layout. Top filter strip (search + chips + sort) over a dense single-column list — one row per fellowship with the region line inline and the website link at the right edge.
- **`app/static/css/frontend.css`** — appended `.fe-fellowships-*` styles: card recipe with the same `translateY(-2px)` + `0 8px 28px` hover lift the rest of the meeting-shaped cards use, chip colours (regional = accent-tint, virtual = green-tint), `.fe-mlist-sort` styles for the sort selector, and the compact-list grid. Admin `.fellowships-tbl` row styles included.

**Search index + `/siteindex`.** Fellowships join every other public content type as a first-class search source.

- **`app/search.py`** — new `_fellowships_source` self-registers at module import; only emits items when `frontend_fellowships_enabled` is on. Each result anchors to `/fellowships#fellowship-<id>` so opening a result scrolls to the matching card.
- **`app/templates/frontend/base.html`** — `KIND_LABELS` / `KIND_ICON` / `KIND_ORDER` extended with the `fellowship` kind (Lucide-style two-figure icon, ordered between Pages and Sections). Modal hint copy updated to mention fellowships.
- **`/siteindex`** — already auto-picks the new public page up via the `@public_section` registry built in the prior `/siteindex` work; no template changes needed.

**Verified end-to-end on the live container**: `/fellowships` returns 200 with 7 cards across 5 country buckets (incl. Virtual) after the save-handler test seeded + re-saved data; `/api/search-index` now reports 7 `fellowship`-kind items; `/siteindex` renders a "Fellowships" entry in the Sections group when the publish toggle is on; the admin save handler correctly handles mixed virtual/regional rows, drops, renames, and inserts via the parallel-array reconciliation.

### Added — Auto-discovered top-level sections on `/siteindex` (Hyperlist, Archive, Blog filled in)

`/siteindex`'s Sections group is now driven by a `@public_section` decorator on each top-level template route, registered into a `_PUBLIC_SECTIONS` list. The previous hardcoded list was missing `/hyperlist`, `/archive`, and `/blog`; with the decorator on every top-level public surface (Home, Meetings, Hyperlist, Events, Archive, Announcements, Stories, Blog, Library, Print list, Submit, Contact) the index now lists all 12 and stays in sync automatically whenever a new top-level page is added.

- **`app/frontend.py`** — new `public_section(title, gate=...)` decorator + `_PUBLIC_SECTIONS` registry near the top of the file. Each top-level route carries the decorator under `@bp.route`, paired with the same feature-flag predicate the route uses for its own 404 (so the index never advertises a page that would 404). `_site_index_groups()` iterates over the registry instead of two hardcoded lists; `url_for` failures are caught quietly so a misregistered endpoint can't 500 the whole page.

### Added — Frontend-wide search now covers every public content type

The `Cmd/Ctrl+K` search modal previously only indexed meetings + upcoming events. It now indexes the entire public surface — live announcements, archived posts (past events + archived announcements together, the same union /archive renders), recovery stories, blog posts (incl. category + tag names), public libraries + their items, custom Pages (body content walked out of `blocks_json`), and every top-level section page from the `@public_section` registry above. Each result row routes to the correct detail URL (e.g. `_post_url` flips between `/event/<slug>` and `/archive/<slug>` based on archive state).

- **`app/search.py`** — seven new sources self-register at module import: `_announcements_source` (live announcements), `_archive_source` (past events + archived announcements), `_stories_source`, `_blog_source`, `_library_source`, `_pages_source`, `_sections_source` (reads `_PUBLIC_SECTIONS`). Each source mirrors the route's own feature-flag gate (`posts_enabled` / `stories_enabled` / `blog_enabled`) so the search results match the visible site. New helpers `_text_blob`, `_strip_html`, and `_blocks_text` build punctuation-stripped search blobs from titles / summaries / bodies / blocks JSON consistently across sources.
- **`app/templates/frontend/base.html`** — `KIND_LABELS` and `KIND_ICON` extended with friendly labels + Lucide-style SVGs for `announcement`, `archive`, `story`, `blog`, `library`, `page`, and `section`. New `KIND_ORDER` map controls group stacking order in the result list (meetings → events → announcements → archive → stories → blog → library → pages → sections); unknown kinds fall to the end via a fallback rank so a future source without a label entry still renders. Hint copy updated to reflect the broader scope.

### Added — `/api/search-index` gzip-compressed when the client accepts it

Follow-on to the search-index expansion above: indexing every public surface grew the response from ~22 items to ~400+, pushing the raw payload to ~377 KB. The endpoint now ships gzip when the client's `Accept-Encoding` advertises it. Browsers always do, so the typical wire payload lands at ~88 KB (a 76% reduction). The handler short-circuits to plain JSON when gzip isn't accepted so curl / older clients still work.

- **`app/frontend.py::api_search_index`** — uses stdlib `gzip.compress` on the JSON body; sets `Content-Encoding: gzip`, `Content-Length`, and `Vary: Accept-Encoding`. No new runtime dependency. Compression level 6 (the gzip default — best speed/ratio trade).

### Added — Per-item hover tooltips on the utility bar

Every leaf row (link / button / text / icon) in the utility-bar admin editor now carries a new **Tooltip** input (optional, capped at 200 chars). When set the public renderer stamps it as the rendered element's `title=` attribute so visitors see the admin-defined text on hover. For icon-only items the tooltip also takes precedence on `aria-label`, so screen readers get the richer hover text instead of just the icon name.

- **`app/utility_bar.py`** — `_coerce_leaf` accepts / strips / length-caps a `tooltip` field; `parse_form_items` legacy parser pulls `tooltip[]` for symmetry. Round-trips through `parse_items` / `serialise_items` because both call into `_coerce_item`.
- **`app/templates/_utility_bar_item_row.html`** — new `<label>` with `data-utility-field="tooltip"` placed under the URL row, gated to the same `data-utility-show-for` set so the field hides automatically when the admin flips an item to a singleton kind that doesn't need it.
- **`app/templates/_frontend_utility_bar_admin.html`** — `readLeaf` in the JSON-payload builder reads the `tooltip` field via the existing `get()` helper so the saved JSON carries it through.
- **`app/templates/frontend/_utility_bar.html`** — `render_leaf` macro emits `title="<tooltip>"` on every leaf kind when set; icon-only items additionally use it as the `aria-label` (with the existing label/icon-name as fallback).
- Singletons (`theme_toggle`, `search_trigger`, `gsr_summary`) keep their built-in `title=` attributes and are intentionally not admin-editable.

### Changed — Meeting-card hover signature unified across the public site

Every meeting-shaped card on the public site now lifts the same way on hover so the homepage, the `/meetings` list, the meeting detail grid, the Files & Readings panel, and the extended Files & Readings card all share one motion language. Single recipe applied:

```
transform:  translateY(-2px);
box-shadow: 0 8px 28px rgba(15, 23, 42, 0.10);
transition: 200ms ease (transform + box-shadow + border-color);
```

- **`.fe-meeting-card`** (homepage Upcoming Meetings tiles) — reference recipe; the rest of the selectors below were tuned to match it.
- **`.fe-mlist-card`** (every meeting card on the `/meetings` directory across sidebar / directory / weekboard / dense layouts) — hover lift bumped from `translateY(-1px)` + `0 6px 18px rgba(15, 23, 42, 0.08)` to the shared `-2px` + `0 8px 28px rgba(15, 23, 42, 0.10)`; transition lengthened from 160 ms → 200 ms. Border-color intentionally stays put on hover so the card doesn't visibly recolour under the cursor.
- **`.fe-meeting-detail-card`** (Schedule / Location / Zoom blocks on the Classic meeting detail template) — also flipped to a pure-white light-mode surface (`var(--fe-color-surface, #ffffff)`, was `var(--fe-panel-soft)`) with an accent border at rest (`1px solid var(--fe-accent)`, was `var(--fe-border)`). Redundant hover border-colour swap removed since rest is already accent.
- **`.fe-meeting-detail-grid > .fe-meeting-resources`** — the Files & Readings panel that drops into the Classic grid alongside the detail cards now matches their rest + hover recipe so the row reads as true siblings instead of one stylistic outlier.
- **`.fe-meeting-extended-card`** — the standalone Files & Readings card every non-Classic meeting template uses. Hover bumped from `translateY(-1px)` + `0 6px 18px rgba(15, 23, 42, 0.08)` to the unified `-2px` + `0 8px 28px rgba(15, 23, 42, 0.10)`; transition lengthened from 160 ms → 200 ms so the lift animates in lock-step with the cards above it.

Dark-mode rules underneath each selector (deep-navy surface, indigo hover border-tint) keep their existing behaviour — only the light-mode appearance and the shared hover transform/shadow were touched.

### Added — Container-width admin panel on the Contact Us template

`/tspro/frontend/templates` now ships a "Container width" fieldset inside the Contact (`/contact`) card with the same boxed/full + max-width + side-padding shape every other list/detail admin surface uses (Events list, Announcements list, Stories list, Blog list, Archive). Boxed caps the contact section at the configured max-width and centers; full-bleed spans the viewport with the configured padding-% as `vw` gutters.

- **New `SiteSetting` columns** — `contact_form_width_mode` (`VARCHAR(16) NOT NULL DEFAULT 'boxed'`), `contact_form_max_width` (`INTEGER NOT NULL DEFAULT 1160`), `contact_form_padding_pct` (`INTEGER NOT NULL DEFAULT 5`), with matching `_migrate_sqlite` entries so existing installs upgrade additively.
- **Save handler clamps inputs** — mode validated against `boxed`/`full`; max-width clamped to 640–2400 px; padding clamped to 0–20 vw. Out-of-range values fall through to the model default rather than blanking the column.
- **`frontend/contact.html` honors the settings** — the outer `<section>` now carries `fe-mlist--w-<mode>`; inner wrapper switches between `.fe-container` (boxed, inline `max-width: Npx`) and `.fe-mlist-fullwrap` (full, inline `padding-left/right: Nvw`). Default values (boxed/1160/5) match the legacy layout exactly so existing sites render identically until an admin opens the panel.

### Added — 80 / 100 vh floor on every public-detail surface

Every event / announcement / archive detail, meeting detail, story detail, blog detail, and the literature library list now floors at a generous fraction of the viewport less the header stack so short posts don't leave a strip of footer floating mid-page. Shared CSS rule near the top of `frontend.css`:

```
/* events: classic / timeline / minimal / poster */
.fe-event-detail, .fe-event-time, .fe-event-min, .fe-event-poster,
/* meetings: classic / minimal / card-stack / magazine */
.fe-meeting-detail, .fe-meeting-min, .fe-meeting-stack, .fe-meeting-mag,
/* stories: paper / anthology / letter / journal / magazine */
.fe-story-paper, .fe-story-anth, .fe-story-letter, .fe-story-journal, .fe-story-mag,
/* blog: all four detail templates share .fe-blog-post as the root */
.fe-blog-post {
  min-height: calc(80vh - var(--fe-header-full-h, 108px));
}
```

The literature library list (`.fe-mlist.fe-library`) floors at the **full** viewport less the header — it's the canonical public-literature landing surface, so a one-section result still fills the browser. Compound selector beats the generic `.fe-mlist { min-height: 50vh }` floor lower in the file on specificity (0,2,0 vs 0,1,0) without relying on source order. Header math reads `--fe-header-full-h` (the full header stack including utility bar + alert band, already maintained by the header chrome) so the calc subtracts the actual visible header — not just the brand row.

### Added — Web Frontend quick-jump buttons above the sidebar search bar

The admin sidebar now carries two pinned buttons directly above the Search bar so admins can hop into the Web Frontend without scrolling through the nav: **Web Frontend** (opens the admin panel at `main.frontend_dashboard`) and **View site** (opens the public `frontend.index` in a new tab). The canonical "Web Frontend" entry under the Admin section of the nav stays put — the quick-jump cluster is in addition to it, not a replacement.

- **Role-gated** with the same condition as the existing Web Frontend nav entry — `site.frontend_module_enabled` AND `current_user.can_edit_frontend()`. Viewers and non-frontend editors don't see the cluster at all.
- **Live status indicator** — a small dot on the Web Frontend button reflects `site.frontend_enabled`: **green with a gentle 2.4s pulse** when the public site is live to anonymous visitors, **muted grey** when it's in editor-only preview mode. Hover tooltip spells out which state ("Public site is LIVE — visible to everyone" vs. "Public site is OFF — visible only to signed-in admins and frontend editors"). Pulse animation respects `prefers-reduced-motion`.
- **Active-route highlighting** — the Web Frontend button picks up a brand-tinted background when the current route is anywhere under `main.frontend_*` (same prefix the canonical nav entry's active rule uses).
- Two-column grid layout (`grid-template-columns: 1fr 1fr`) so the cluster fits the sidebar's width without forcing a wider rail; long labels truncate with ellipsis on narrow viewports.

### Fixed — `/tspro/meetings` 500'd with `TypeError: 'function' object is not iterable`

The shared `_meeting_modal.html` partial (used by both the meetings list and the meeting-edit page) loops `{% for lib in all_libraries %}`. `all_libraries` is registered in `app/__init__.py` as a Jinja global pointing at the underlying `_all_libraries` **function** (not its return value), and the meeting-edit route happens to shadow that global with a real list via render context. The meetings list route never did — so when an admin opened `/tspro/meetings` the loop tried to iterate the bare function and raised a TypeError. Now passes `all_libraries=Library.query.order_by(Library.name).all()` alongside the existing `meetings` / `zoom_accounts` / `locations` context, matching the pattern the edit route uses.

### Fixed — Page-builder two-column block now stacks on phones

The page-builder's container block was rendering `style="grid-template-columns: 1fr 1fr; …"` (or whatever `grid_columns` the admin chose) as inline CSS, which beat every class-rule attempt to override it at smaller viewports. The `/chat` page in particular surfaced this — two side-by-side blocks squeezed into half-width strips on phones instead of stacking. Both renderers (`app/templates/_blocks.html::render_container_block` and `app/templates/frontend/page.html::pp_container_styles` — turns out there are two duplicate container renderers, one for admin previews / wiki pages and one for public pages) now emit `--block-cont-grid-cols: <value>` and `--block-cont-flex-dir: <value>` custom properties instead of writing the layout properties directly; new CSS rules in `frontend.css` consume the variables with `repeat(2, 1fr)` / `column` fallbacks and collapse to `1fr` / `column` at the `≤720px` mobile breakpoint. Row-direction flex containers stack the same way; column-direction containers and `flex-wrap: wrap` opt-ins are unaffected.

### Fixed — Design tokens page color rows overflowing

Each color tile on `/tspro/frontend/design` was packing six elements into a tight flex row (`[Override checkbox] [color picker] [🎨 button] [hex caption] [matches-token chip] [↺ reset]`) because the site-wide design-token picker (`_design_token_picker.html`, included once via `base.html`) auto-injects three of those elements (🎨 / hex / chip) next to every `<input type="color">` on every page. On the design tokens page itself the chip was also tautological (matching a "Brand" token to itself) and the elements collectively overflowed the 260px tile minimum.

- **Suppress shared auto-picker** on this page only — `data-no-token-picker` stamped on each color input opts out of the site-wide attachment pass without touching any other page that benefits from it.
- **Native hex caption** added inline after the swatch — reads the picker's current value live via the existing color-input listener, so admins still see the hex string at a glance without opening the colour-picker dialog.
- **"Override" label** wraps the gating checkbox so the toggle reads as a deliberate control instead of stray decoration.
- **Wider tiles + flex-wrap** — grid minmax bumped from 260px → 300px; field padding from 12×14 to 14×16; control row carries `flex-wrap: wrap` so on a narrow column the reset button drops to the next line gracefully instead of squeezing out. Swatch grew to 48×32 (was 36×28); reset button auto-anchors right via `margin-left: auto` so wide rows align consistently regardless of how many controls landed inline.

### Fixed — Story detail pages 500'd with `NameError: name 'tpl_dynbg_config' is not defined`

Every `/stories/<slug>` request was raising a `NameError` because `app/frontend.py:story_detail` was passing `tpl_dynbg_config=tpl_dynbg_config` into `render_template` without ever assigning the variable. The route only built `tpl_dynbg_overlay` / `tpl_dynbg_colors` from the decoded `_story_cfg`; the richer config dict the story templates iterate (`paper.html`, `journal.html`, `anthology.html`, `letter.html`, `magazine.html` — every one of them reads `tpl_dynbg_config` in the section's inline style + threads it through `frontend/_dynbg_apply.html`) was never materialised. Now built with the same shape `archive_detail` uses: flat `SiteSetting.frontend_story_bg_dynbg_config_json` wins per-dimension (overlay, scope, size, intensity, randomize-colors / randomize-positions, animate), falling through to per-template-settings leaf keys (`bg_dynbg_overlay_scope`, etc.) for anything not set on the flat picker. So the noise + motion knobs the admin saved actually take effect on the public story render.

### Added — WordPress importer auto-maps ACF custom fields onto event / announcement columns

The importer now pulls ACF (Advanced Custom Fields) data from every WP REST post and auto-maps recognised field names onto the matching Post columns (event start/end times, location, Google Maps link, event website, Zoom credentials, contact info, summary override). Announcement-targeted and event-targeted imports share the same column set — both lifecycle states live in one `Post` model and the public `/archive` mixes them in the same year sections, so a post should pick up every populated ACF field regardless of which side of the toggle it lands on.

- **ACF capture** — `_normalize_rest_post` reads the `acf` key off the standard `/wp/v2/posts` REST response (modern ACF ≥5.11 with `show_in_rest=true` on each field group exposes it by default). When the bulk endpoint returns no ACF on any post, `_acf_fallback_fetch` probes the legacy `/wp-json/acf/v3/posts/<id>` namespace once per post (so sites still running the standalone ACF-to-REST plugin work without admin intervention). CSV imports accept `acf_<name>`, `acf:<name>`, `meta:<name>` columns plus any bare column whose name matches the alias set.
- **Field aliasing** — `ACF_FIELD_ALIASES` lists 70+ candidate names per target column so `venue` / `event_location_name` / `place_name` all resolve to `location_name`; `event_website_url` / `register_url` / `rsvp_url` all resolve to `website_url`; `zoom_meeting_passcode` / `zoom_password` / `meeting_password` all resolve to `zoom_passcode`; etc.
- **Prefix-stripping index** — `_build_acf_index` also stamps every ACF key under its prefix-stripped form (`event_`, `announcement_`, `evt_`, `ann_`, `story_`, `post_`, `wp_`, `field_`). So a future site that namespaces every ACF field under `event_*` automatically resolves against the plain alias list without code changes — `event_contact_name` matches the `contact_name` alias, `event_address` matches `address`, etc.
- **Date + time composition** — `_resolve_event_datetime` builds a real `datetime` from whatever the site provides: full-datetime alias wins outright when present; otherwise composes a `datetime` from separate date alias + time alias via `datetime.combine`. Handles `YYYY-MM-DD HH:MM:SS`, `YYYYMMDD` (legacy ACF save format), Unix timestamps, ISO, `M/D/YYYY`, `B D, Y` for dates; `HH:MM:SS`, `I:M %p`, `6pm` shorthand for times. Date-only with no companion time defaults to midnight so the row still gets a real `event_starts_at`.
- **Boolean coercion** — `is_online` accepts `1` / `true` / `yes` / `online` / `virtual` truthy strings and `0` / `false` / `no` / `in-person` / `physical` falsy strings.
- **Summary override** — `announcement_summary` / `event_summary` / `summary` ACF fields beat the WP-rendered excerpt when present, so the rich admin-authored field is what surfaces on the public site instead of the auto-generated post-content snippet.
- **Length-capped string columns** — each Post column has a max length matching its schema column (`location_name` 255, `zoom_passcode` 128, `contact_name` 120, etc.) so an oversized ACF value can never blow up the insert.
- **Dry-run value preview** — each event/announcement row on the dry-run page renders an **ACF · N fields** disclosure under the title; clicking it expands a `column → value` table showing exactly what will land (`event_starts_at: Jan 27, 2026 8:30 PM`, `zoom_url: https://us02web.zoom.us/j/…`, etc.). Datetimes render in friendly format, long strings truncate at 80 chars. The Plan-summary counts card adds a purple "ACF fields" tile (`{N} across {M} posts`) so the global total is visible at a glance.
- **Stale-stash banner** — wizards opened against a pre-ACF token (post stash where every post has no `acf` payload) now surface a yellow alert on both the Map and Dry-run pages: "Stale wizard — ACF data not captured" with a one-click Reconnect button. Prevents reopening an old wizard URL from silently producing ACF-less imports, which was the original symptom that prompted the auto-mapping work.

### Added — Pagination on the public `/archive` page (infinite scroll or numbered pages)

The unified archive page now paginates its card list — default is infinite scroll, 20 cards per batch, loading the next batch when the visitor reaches the end. Admins can switch to numbered pagination (with ‹Prev / 1 / 2 / 3 / … / N / Next› controls) or adjust the page size (1–200) from the Templates admin page.

- **New `SiteSetting` columns** — `frontend_archive_pagination_mode` (`VARCHAR(16) NOT NULL DEFAULT 'infinite'`), `frontend_archive_page_size` (`INTEGER NOT NULL DEFAULT 20`), with matching `_migrate_sqlite` entries.
- **Client-side pagination** — every card renders into the DOM on first load (so the existing search / year / type filters keep working without a round-trip). The shared JS in `archive.html` slices the filtered set by current page (numbered) or current shown-count (infinite) and toggles `hidden` on every card. Year-section headings auto-collapse when no cards from that year remain on the current slice.
- **Infinite-scroll loader** uses `IntersectionObserver` with a 200px-rootMargin so the next batch starts loading just before the visitor scrolls into the sentinel. Newly revealed cards stagger-animate in via the existing `is-entering` class without restaging the already-visible ones.
- **Numbered paginator** renders a compact 1 / current±1 / last window with `…` ellipses, hides itself when the filtered set fits on one page, and scrolls the top of the results column into view on each page click.
- **Filter changes reset paging** — pill click, kind-toggle change, and search input all reset to page 1 / 20 shown so a filter never strands the visitor mid-list.

### Added — Archive page template picker (Year Sidebar / Timeline / Compact List / Magazine)

`/archive` now ships four selectable layouts, picked from a new card in the admin Templates page. The default (**Year Sidebar**) preserves the existing chrome — sticky left rail with search + type checkboxes + year pills, year-grouped card stack on the right. Three new layouts surface the same data through different visual languages:

- **Timeline** — vertical centerline spine with year markers stamped along it; cards alternate left/right of the spine; compact filter strip at the top instead of a sidebar. Collapses to a single left-aligned column on phones.
- **Compact List** — dense single-column rows (date block · kind chip · title · summary · arrow). No thumbnails. Top filter strip. Best for fellowships with many archived items.
- **Magazine** — 3-up grid of editorial tiles with the very first tile spanning two columns as a feature card; cover image + kind chip + date + title + summary per tile; hover lift + cover image scale on hover.

Architecturally `archive.html` is now a thin dispatcher: it resolves dynbg config, includes the chosen layout partial (`frontend/archive/<key>.html`), and owns the shared filter + pagination JS at the bottom. Every layout drops the same data-attribute hooks (`data-archive-rail`, `data-archive-results`, `data-archive-year-section`, `data-archive-search`, `data-archive-kind-toggle`, `data-archive-filter`, `data-archive-load-sentinel`, `data-archive-pagination`) so the same JS drives every variant. New `ARCHIVE_TEMPLATES` catalog in `app/frontend.py`; new `frontend_archive_template` column on `SiteSetting`; per-template appearance overrides ride through the existing `frontend_template_settings_json` JSON column under the `archive` kind (registered in `_TEMPLATE_KINDS` + `catalog_map`); per-page dynbg via `frontend_archive_bg_dynamic_key` / `frontend_archive_bg_dynbg_config_json`. Admin picker cards ship pure-CSS layout thumbnails in `app.css` (`fe-tplgrid-thumb-archive-*`).

### Fixed — Archive page year buckets / sort use `published_at`, not `created_at`

Imported announcements were piling up under the current month because the route was bucketing them by `Post.created_at` (the row-insert timestamp). The WP importer correctly stores the original WP publish date in `Post.published_at`, so the route now prefers that (`p.published_at or p.created_at`) for both the `sort_at` and the `year` of each announcement entry. Events were already correct (they use `event_starts_at`, which the importer sets from the original date). The announcement card's "Posted …" line also now uses `Post.display_posted` so the per-card date matches the year bucket it lives under.

### Added — Inline body image cleanup on post / story / blog delete

Deleting a post / story / blog row now retires the inline `<img src="/pub/…">` images embedded in the row's body, not just the featured image. WP-imported posts often carry several inline screenshots / photos; previously those copies stayed on disk + in the `MediaItem` catalog as orphans after the parent row was deleted.

- **`_extract_body_pub_originals(html)`** regex helper pulls every `/pub/<filename>` token out of a body HTML chunk (covers `<img src>`, `srcset`, `<a href>`, plain-text URLs).
- **`_collect_body_inline_stored(html)`** resolves those original filenames to current `MediaItem.stored_filename` values (de-duped) so callers pipe each through the existing `_cleanup_retired_asset` helper.
- **`_cleanup_retired_asset` reference-count extended** — the helper now also LIKE-scans `Post.body`, `Story.body`, and `BlogPost.body` for the file's `/pub/<original_filename>` token. So if you delete post A but post B's body still embeds the same inline image, the helper sees B's reference and keeps the file. Symmetric with the existing column-reference checks (`featured_image_filename`, MeetingFile, LibraryItem, etc.).
- **Wired into every delete path** — `post_delete` (single announcement/event), `post_bulk` delete branch, `story_delete`, `blog_delete`, `blog_bulk` delete branch. Order in each path: snapshot the body's inline stored filenames BEFORE the row is deleted (need the body text intact to scan), commit the delete, then run cleanup on each captured filename after commit (so the helper's body scan no longer sees the dying row's own body).

### Changed — Admin Templates section heading renamed to "Announcements / Events / Archive detail"

The detail-template card on `/tspro/frontend/templates` now reads **Announcements / Events / Archive detail** with the blurb mentioning `/archive/<slug>` so admins know the same template drives archived-post detail pages too — not just the live `/event/<slug>` and `/announcement/<slug>` URLs.

### Added — Site-wide design-palette colour picker with hex caption + token chip on every colour input

Every `<input type="color">` across the admin now sits next to a one-click 🎨 button that opens the same design-palette popover the content-page editor uses. The popover is rendered once in `base.html` (via the new `_design_token_picker.html` partial) and auto-attaches a picker, a live hex caption, and a token-match chip to every colour input on the page.

- **Shared partial** at `app/templates/_design_token_picker.html` renders the popover DOM, populates `window.tspDesignColorTokens` (key → hex) plus a new `window.tspDesignColorTokenLabels` (key → display name), and ships its own self-contained `<script>`/`<style>` so it's drop-in safe.
- **Auto-attach scan** wires every `<input type="color">` on the page with three siblings: the 🎨 button, a monospace hex caption (e.g. `#1f4e79`) that updates live on `input`/`change`, and a "Token: <Name>" chip that lights up the moment the input's value matches a palette colour. Selecting a token from the popover writes the resolved hex into the input and dispatches `input`/`change` so any live-preview JS picks up the change.
- **Skip rules** prevent double-wiring where richer token-aware controls already exist: inputs marked `data-no-token-picker`, wrappers carrying `data-token-pair` (content-page editor), and block-editor `.be-color-cluster` elements all keep their existing pickers.
- **Token-aware text fields** that store `token:<key>` get a stronger ◈ Bound: <Name> chip with a separate tooltip explaining that palette edits propagate live. The passive ◈ <Name> chip on plain hex inputs uses a clear tooltip so admins know the value is a frozen snapshot of the palette, not a live binding.
- **MutationObserver** rescans dynamically-injected colour inputs (modal content, lazy form sections) so the homepage hero modal, footer modal, and other on-demand surfaces pick up the picker without per-screen wiring.

### Added — Homepage hero subheading typography (font, size, colour) with mobile-aware scaling

The hero edit modal split the typography section into two side-by-side groups, **Heading** and **Subheading**, each with its own font (Fraunces serif / Inter sans), size (50–200% slider with live readout), and colour (gradient pair for the heading, single colour for the subheading). The subheading colour and font are independent of the heading so admins can mix-and-match without one overriding the other.

- **New `SiteSetting` columns** — `frontend_hero_subheading_font` (`VARCHAR(32) NOT NULL DEFAULT 'inter'`), `frontend_hero_subheading_size` (`INTEGER NOT NULL DEFAULT 100`), `frontend_hero_subheading_color` (`VARCHAR(16)`), with matching `_migrate_sqlite` entries so existing installs upgrade additively. Defaults preserve the legacy look exactly.
- **Modal layout** uses CSS grid with `repeat(auto-fit, minmax(min(100%, 320px), 1fr))` so the two groups sit side-by-side on desktop and stack to a single column on phones without any per-element media queries. Font-family pillgroups wrap to one pill per line at ≤540px viewport.
- **Mobile scaling** — both `.fe-hero-heading` and `.fe-hero-sub` now multiply a `clamp(min, fluid, max)` baseline by the admin's unitless `--fe-hero-h-size` / `--fe-hero-sub-size` factor. The same 150% setting reads as a smaller absolute size on phones and a larger one on desktops, so admins get sensible scaling on every device.
- **Live preview** at the top of the modal reflects font / size / colour edits in real time — font class swap, CSS variable updates, and reset-checkbox handling all wired through `input`/`change` listeners.
- **Save endpoint** clamps size to 50–200%, sanitises the colour via the existing `_sanitize_icon_color`, and honours a "Reset subheading colour to default" checkbox.

### Added — Lightbox-compatible images in blog detail templates

Every `<img>` in the four blog detail templates (Modern / Longform / Classic / Cover) is now zoomable — clicking opens a self-contained, dependency-free lightbox modal. Featured images and inline body images both work.

- **New shared partial** at `app/templates/frontend/_lightbox.html` ships the modal markup, CSS, and JS in one drop-in `{% include %}`. Auto-discovers every `<img>` inside a `data-lightbox-scope` container.
- **Click to open** with fade-in transition; multiple images get prev/next arrows; arrow-key + Escape navigation; click backdrop or × to close. Body scroll locked while open. Honours `prefers-reduced-motion`.
- **Caption** auto-fills from `alt` text when present.
- **`data-lightbox-src`** lets a thumbnail show small but expand to a full-resolution original — used on featured images so the hero shows a `?thumb=` thumb but the lightbox renders the unscaled `blog_post_featured_image`.
- **Smart skip** — images wrapped in `<a>` are intentionally excluded so card thumbnails still navigate. Per-image `data-lightbox-skip` opts out individually.
- **Wired into** all four blog detail templates: Modern, Longform, Classic on hero + body images; Cover on body images only (the hero is a CSS background with the title overlaid, which would conflict with the title link area). Inline body images use whatever `src` they were imported with, which after the WP importer's image rewriter is the local `/pub/<filename>` path.

### Removed — Summary rendering from blog detail templates

The post summary is no longer rendered as a deck/lede on the Blog Modern / Longform / Classic / Cover detail templates. The summary still appears in list cards and link previews — only the detail page no longer shows it. Existing CSS rules for the now-unused `.fe-blog-*-deck` classes are retained as dead code; trivial to clean up later.

### Added — WordPress importer rewrites inline body images to local copies

The importer now walks every `<img>` in the post body's HTML and downloads each unique `src` / `srcset` URL via the same image-download path the featured image uses, then rewrites the attribute values to point at `/pub/<filename>` so imported posts no longer depend on the source WordPress site staying online.

- **Sha256 content-hash dedupe** — re-importing the same image across many posts only stores one copy on disk (mirrors the featured-image behaviour).
- **`srcset` responsive variants** get rewritten in place with size descriptors (`300w`, `2x`, etc.) preserved.
- **Skip** for `data:`, `blob:`, `javascript:`, `#`, and already-local `/pub/…` URLs.
- **Per-batch URL cache** so two posts referencing the same image only hit the network once.
- **Failures are non-fatal** — original URL stays put (broken image vs. lost reference) and a per-row warning is surfaced so admins can chase 404s.
- **Wizard counts** — new "Inline images" tile (cyan) on the dry-run preview and Done page, plus an "Inline failed" tile if any downloads errored. The dry-run heuristic walks `src` + `srcset` the same way the commit phase does so the totals match.
- **Applies to all four import targets** — Stories, Announcements, Events, and Blog.
- **`image_cb` contract refactor** — `_download_image_full(url)` now returns `(stored_filename, original_filename)` so the inline rewriter can build public URLs while the featured-image path keeps using the stored filename. `download_image_to_uploads` is preserved as a single-string shim for the legacy callsite.

### Added — Bulk action toolbar in the Blog admin list

Per-row checkboxes + select-all on `/tspro/blog` with a sticky bulk action bar that surfaces only when something's checked. Status flips (Archive / Restore / Move to drafts / Publish / Feature / Unfeature / Pin / Unpin), per-category and per-tag bulk operations, and a delete action all routed through a single `/tspro/blog/bulk` endpoint.

- **Category ops** — pick a category from a dropdown, then `+ Cat` (add to existing), `− Cat` (remove that one), or `↦ Cat` (replace all categories with the picked one, with a destructive-action confirm).
- **Tag ops** — same pattern: `+ Tag` / `− Tag` after picking from a tag dropdown.
- **Bulk form layered correctly** — the bulk form lives standalone with the checkboxes wired via `form="blog-bulk-form"` so per-row action `<form>`s can stay inline without HTML's nesting prohibition.
- **Stale ids silently skipped** — if someone deletes a post in another tab, the rest of the batch still applies.
- **ActivityLog** entry per batch (`blog.bulk_<action>`).

### Added — Per-post archive override on WordPress import dry-run + bulk select-all

The WP importer no longer auto-archives by status — admins now flag each post for archiving directly on the dry-run preview screen via a checkbox in a new rightmost "Archive" column. Three bulk buttons in the section header:

- **All** — flip every visible row's checkbox on.
- **None** — clear all.
- **From WP status** — only flag rows whose original WP status was `trash` or contained `archive` (preserves the auto-detection behaviour as an opt-in shortcut).

A live counter under the IMPORT prompt shows "*N posts will land in the Archived tab*" so the admin knows what's about to happen before typing IMPORT. Selections survive a failed POST (e.g. forgot to type IMPORT) because they're persisted to the stash on submit and re-applied on re-render.

- **Auto-classifier simplified** — `_classify_wp_status` now only returns `is_draft` (for `draft` / `private` / `pending`); archived state is purely admin-driven via the dry-run checkboxes.
- **`apply_plan` accepts `archive_keys`** — a set of post keys to flag as archived. Threaded through all three target types (Story / BlogPost / Post).
- **Bug fix** — preview rows now carry the post `key`, so the form submission can correctly map archive checkboxes back to their source posts. Previously the missing key meant every archive checkbox submitted as `name="archive:"` (empty key) and the route couldn't match anything, causing an entire 300-post import to land active.
- **Dark-mode fix** — the WP import wizard templates (`wp_import_map.html`, `wp_import_dry_run.html`, `wp_import_done.html`) were using `var(--surface, …)` / `var(--surface-alt, …)` / `var(--text-soft, …)` token names that don't exist in this app's theme system, so the light fallback hex/rgba values leaked through in dark mode. Mapped to the real tokens (`--panel`, `--panel-2`, `--muted`) so post rows, category cards, filter bar, target pillgroup, post thumbnail, slug code, summary text, skipped-list, and the dry-run / done count cards all flip with the theme.

### Added — WordPress importer Blog target + category + tag preservation

The WP importer now supports the new Blog module as an import target alongside Stories / Announcements / Events. WordPress categories and tags carry over: matching ones (by slug first, case-insensitive name fallback) are reused; net-new rows are created on commit.

- **REST fetcher** harvests `/wp/v2/categories` with `{name, slug, description}` and a parallel `/wp/v2/tags` call (non-fatal if the site has tags disabled). Authenticated status list now includes `trash` with a fallback retry without it for older / hardened installs that reject the value.
- **CSV parser** separately recognises a `Tags` column when present; legacy "Tags as Categories" fallback preserved for old CSVs that store everything in one column.
- **`apply_plan`** routes WP categories → `BlogCategory` and WP tags → `BlogTag` via slug-first / case-insensitive-name fallback matching. Net-new rows added with auto-disambiguated slugs.
- **Counts** include `blog`, `blog_categories_created`, `blog_tags_created`, `blog_categories_matched`, `blog_tags_matched`.
- **Wizard UI** — Blog target pill (rose palette) on the map page hidden when the module is off (with an in-page hint pointing to Settings → Modules). Tag chips alongside category chips on each post row. Dry-run preview gets a "Categories & tags" column and a summary block (matched vs would-create). Done page gets a Blog count card linking to `/tspro/blog`, post-import created summary with deeplinks to the manage pages, and Edit → links for blog rows.
- **WP date preservation** — REST grabs the full ISO datetime (`date`/`date_gmt`). CSV preserves time when the Date column carries it. The full timestamp parses into `published_at` on every imported row (Story, BlogPost, Post), so a 2018 WP post lands showing "Mar 15, 2018, 2:30 PM" in the admin list instead of being stamped with today's date.

### Added — Blog module: long-form editorial posts with categories + tags + multiple frontend layouts

Full new module sitting alongside Stories and Announcements & Events. The same data table serves many distinct frontend "blogs" by filtering each page-block embed on a category or tag, so a fellowship can host one blog per committee or group without parallel tables.

- **Models** — `BlogPost` (title, slug, summary, body, featured_image, author byline, `published_at`, `is_featured`/`is_pinned`/`is_draft`/`is_archived`, `allow_comments`, `reading_minutes`), `BlogCategory` (name, slug, colour, position, description), `BlogTag` (name, slug), plus M2M `blog_post_categories` / `blog_post_tags`.
- **Migration** — all new `SiteSetting` columns (`blog_enabled`, `blog_required_role`, list/post template keys, width/padding, dynbg config) added to `_migrate_sqlite` so existing DBs upgrade cleanly.
- **Module gating** — `blog_enabled` toggle + `blog_required_role` dropdown in Settings → Modules (mirrors Stories). Sidebar entry shows when enabled and role passes; `_require_blog_enabled()` gates every admin route.
- **Backend** — CRUD for posts (filter by category/tag/status/search, sort by published/title/updated/author), categories, tags, plus duplicate / publish / unpublish / archive / unarchive / delete. Auto-create new tags inline from the post editor. `/blog-image/<id>` public endpoint with thumb support.
- **Admin templates** — `blog_list.html` with filter rail, `blog_edit.html` with category pill checkboxes + tag multi-select + free-text auto-create + featured image + author + publish date + reading time + pin/feature/comments toggles, `blog_categories.html` with inline edit form + colour picker, `blog_tags.html` with tag cloud + inline edit.
- **Frontend** — `/blog` and `/blog/<slug>` plus pretty-URL aliases `/blog/category/<slug>` and `/blog/tag/<slug>`. Slug history honoured for redirects.
- **Six list layouts** — Magazine (default, hero + grid), Cards (uniform 3-up), Gazette (newspaper broadsheet), Minimal (image-light single column), Mosaic (masonry CSS columns), Sidebar (main column + sticky filter rail).
- **Four detail layouts** — Modern (default), Longform (Medium-style with drop-cap), Classic (sidebar + related), Cover (full-bleed parallax hero).
- **Page block** `blog_list` — scopes by category OR tag, three styles (cards / list / headlines), per-block knobs for columns, sort, max items, only-featured/pinned, and which metadata to surface.
- **Templates admin** — new Blog list and Blog detail picker sections appear when the module is enabled, with width/heading controls and the same per-template Customize panel as the other modules.

### Added — Posted-on timestamp field across Posts / Blog / Stories with sort + WP date preservation

Every admin list page that surfaces posts now shows a "Posted" column with the editable timestamp, and clicking the column header sorts by it. WordPress imports preserve the original publish date.

- **Models** — `Post` and `Story` gained `published_at` DateTime columns (BlogPost already had one). All three carry a `display_posted` property that falls back to `created_at` for legacy rows so nothing renders blank.
- **Edit forms** — `post_edit.html` and `story_edit.html` got a "Posted on" `datetime-local` field. Empty input keeps the existing value; new posts default to `now()` if blank. `blog_edit.html` already had its "Publish date" field.
- **Admin lists** — Announcements/Events, Stories, and Blog all now show date + time in a sortable "Posted" column. Sort options include `posted_asc` / `posted_desc` and (for Stories) Title / Author / Story date / Posted.
- **WP importer** — REST grabs the full ISO datetime from `date`/`date_gmt`; CSV preserves time when the Date column carries it. The full timestamp parses into `published_at` on every imported row.

### Added — Bulk action toolbar + sorting + pagination on Announcements & Events admin

Per-row checkboxes + select-all on `/tspro/announcementsevents` with a sticky bulk action bar (Archive / Restore / Move to drafts / Publish / Delete — buttons hide when they wouldn't make sense for the current tab). Selected rows pick up a brand-tinted background. Single POST to `/announcementsevents/bulk` does the work; stale ids skipped silently.

- **Sortable column headers** — Title, Type, When (or Submitted on the pending tab), Posted, Edited. First click sets the default direction; second click flips it. Active column shows an arrow. Sort survives across pagination and tab changes.
- **Hard cap at 100 per page** with Prev / Next bookends, "Page N of M · 100 per page" footer, and "Showing 1–100 of N · sorted by …" toolbar caption.

### Added — Blog module page block for embedding filtered post lists

New `blog_list` block type for custom Pages. Scopes by category OR tag, picks a display style (cards / list / headlines), and surfaces presentation knobs (columns 1–4, gap, max items, sort, only-featured/pinned, per-item display: image / summary / categories / date).

- **Block editor JS** registers `blog_list` in the type catalog with sensible defaults.
- **Block renderer** at `app/templates/_blocks.html` walks the block data, queries via `blog_block_data` Jinja global, and renders the chosen style.
- **Server-side data helper** (`blog_block_data(category_id, tag_id, sort, max_items, only_featured, only_pinned)`) handles filtering / sorting / capping; mirrored `all_blog_categories` / `all_blog_tags` helpers expose the taxonomy lists to the block-editor picker dropdowns.
- **"View all → " link** auto-appends to each block, pointing at the matching category / tag landing page when scoped, or the main `/blog` index otherwise.

### Added — Hero block vertical-height (vh) controls for desktop + mobile, header-aware

The hero block on the homepage gained two new sliders in its edit modal — **Desktop height** and **Mobile height**, both 0–200 vh in steps of 5 — alongside a live readout that displays "Auto" at 0 and `<n>vh` otherwise. The sticky header is automatically subtracted from the calc so a `100 vh` setting fills *exactly* the visible viewport below the header instead of overshooting by a header's worth and forcing visitors to scroll to clear the hero.

- **New `SiteSetting` columns** — `frontend_hero_height_vh_desktop` and `frontend_hero_height_vh_mobile` (`INTEGER NOT NULL DEFAULT 0`) with matching `_migrate_sqlite` entries so existing installs upgrade additively. `0` = "auto" (the existing padding-derived height), keeping every untouched install rendering byte-for-byte the same.
- **Save route** — `frontend_hero_save` clamps both values to `0–200 vh` via `_clamp_int`.
- **CSS** — `.fe-hero` now reads `min-height: var(--fe-hero-min-h, auto)`, plus `display: flex; flex-direction: column; justify-content: center` so content sits in the middle when the section stretches. The mobile breakpoint reads `--fe-hero-min-h-mobile`, falling back to the desktop var, then to auto.
- **Header-subtraction calc** — the hero template emits `min-height: max(0px, calc(<N>vh - var(--fe-header-full-h, <configured-header-h>px)))`. `--fe-header-full-h` is already measured live in `frontend/base.html` (resize + scroll observer) and reflects the full sticky stack (utility bar + alert bar + header). The fallback uses the server-rendered header-height SiteSetting so the hero doesn't render too tall on first paint before JS measures the live value. `max(0px, …)` floors small admin values on tall-headered installs so the calc never goes negative.
- **Inline emission only when non-zero** — the template only writes the CSS custom properties when the admin has dialled a non-zero value, so installs that never visit the field stay on the original padding-based layout with zero diff.

### Added — Sticky title bar + close button inside every page-edit modal

Every block editor on the homepage admin (Hero + the eleven block-editor modals) now keeps its title strip and the X close button visibly anchored to the top of the modal panel as the form scrolls.

- `.fe-page-edit-modal-panel` is now `display: flex; flex-direction: column` so the close button can `align-self` to the right edge as a sticky child without restructuring existing markup.
- `.fe-page-edit-modal-panel > .card > .card-head` becomes `position: sticky; top: 0` with full-width bleed (`margin: 0 -2rem`) so the title strip stays anchored to the panel's visible top.
- `.fe-page-edit-modal-close` switched from `position: absolute` → `position: sticky; top: 12px`, with `margin-bottom: -44px` so the button doesn't reserve a 44px empty strip above the title. `z-index: 6` keeps it layered above the sticky head (`z-index: 4`).

### Changed — Save bar opts-in to modal forms + layers above modal backdrop + keeps modal open on save

The yellow save bar at the bottom-left of the Web Frontend admin now works for the homepage hero modal (and any other modal that opts in), surfaces above any open modal's backdrop blur instead of behind it, and no longer reloads the page when the dirty form lives inside a modal so the visitor isn't kicked back to the page each time they save.

- **Modal-form opt-in** — `feSaveBar`'s `trackable()` previously rejected any form inside a `.modal` outright. New rule: modal forms are opt-in via `data-fe-savebar`. The hero form (`<form id="hero-save-form">`) carries the attribute so the bar tracks its dirty state. Other modals across the admin (footer editors, user edit, settings, etc.) keep their existing skip behaviour because they don't carry the attribute.
- **Save bar moved out of `.fe-subnav`** — `.fe-subnav` is `position: sticky` which (per CSS spec) creates its own stacking context, trapping the save bar's `z-index: 110` inside the parent's local stack. Since `.modal` has explicit `z-index: 100` at root level, it always painted *above* the auto-z-indexed subnav's children. The save bar is now a sibling of the subnav (still inside `.fe-admin-layout`) so its `z-index: 110` competes directly with the modal's `100` at the root stacking context, lifting the bar above the backdrop's `backdrop-filter: blur(6px)` so it stays sharp AND clickable while a modal is on focus.
- **Save bar z-index bumped 50 → 110** — high enough to clear modals (`z-index: 100`).
- **No reload on modal save** — the save handler branches on whether every dirty form lives inside a `.modal`. If yes, the bar animates out, resets its label/button, and clears the dirty set without reloading; the modal stays in front and the visitor can keep editing. Subsequent field changes immediately re-arm the bar. Non-modal forms still reload (server-normalised values like clamps / sanitisation flow back into rendered fields, which the modal-stay path skips because the user can see their typed value already).

### Changed — Header utility bar item + container icon picker uses the shared icon-modal chooser

The leaf-row "Icon" `<select>` and the container "Collapsed icon" `<select>` on the Web Frontend → Header → Utility bar admin both became chooser buttons that open the same icon-picker modal the nav mega-menu and homepage feature-card editors already use. The legacy 24-icon whitelist (`utility_bar_icon_choices`) is no longer referenced — admins now have the full Lucide catalog plus their own Custom uploads available.

- **Saver contract preserved** — the hidden inputs still carry `data-utility-field="icon"` and `data-utility-field="collapsed_icon"` so the existing JSON payload shape is unchanged. No saver, validator, or public-renderer changes were needed; the public renderer's `icon()` helper already handles both Lucide names and `custom:NN` refs.
- **Picker generalised for unstable IDs** — utility-bar rows are cloned at runtime from a `<template>` so each row can't carry stable global IDs. `openPicker` now falls back to `[data-icon-input]` inside the `[data-icon-field]` wrapper when `data-icon-target` is absent. The clear handler uses the same fallback. This unblocks any future call site that wants the picker without minting per-instance IDs.
- **Icon-picker modal include** — added to `frontend_header.html` (it wasn't loaded on this page before), wiring the same Lucide catalog / custom-icon list / upload / delete URLs as the homepage and templates pages.
- **CSS** — new `.utility-bar-icon-field` rules wrap the trigger button + clear chip into the row's grid column, with `has-icon` toggling preview / placeholder / clear visibility consistently with the existing `.nav-megalink-icon-field` pattern.

### Added — 50vh floor + sidebar-style filter animation on every list page

The literature-library, meetings, events, announcements, and unified archive pages all now floor at `min-height: 50vh` so a sparsely-populated list still gives visitors a page-shaped surface instead of collapsing to a thin strip beneath the header. Beyond that, the smooth slide-in entrance animation that fires when the meetings-list rail filter changes is now consistent across every list page so filter clicks read as transitions, not jumps.

- **Min-height** — single CSS rule covering `.fe-mlist` (meetings + library + archive), `.fe-events-list-omni/cards/calendar/timeline/magazine`, and `.fe-announcements-list`.
- **Animation extended** — the existing `.fe-mlist-card.is-entering` keyframe / cubic-bezier was generalised to also cover `.fe-library-item`, `.fe-events-archive-card-wrap`, `.fe-events-card`, and `.fe-announcements-card`, with a matching reduced-motion override.
- **Library** (`literature_library.html`) — `applyFilter` gained an `animate` arg; pill clicks fire the animation, pure search keystrokes skip it (typing doesn't restage the list every character).
- **Archive** (`archive.html`) — same `animate` arg pattern; year-pill clicks AND Events/Announcements checkbox toggles fire the animation.
- **Events omni** (`events_list/omni.html`) — tab switches between Overview / Cards / Calendar / Timeline animate the cards in the new panel. Initial localStorage restore is silent.
- **Announcements omni** (`announcements_list/omni.html`) — same treatment for Cards ↔ GSR Summary tab switches; initial hash + localStorage restore is silent.

### Changed — Frontend export bundle covers pages, officers, stories, posts, slug history (format v3)

`/tspro/settings/frontend-export` is now content-complete for everything 1.8.x has added to the public-frontend authoring surface. Bundles bumped to `format_version: 3` and round-trip cleanly through the matching `/tspro/settings/frontend-import` ingest path.

- **Settings prefix selector broadened** — `submission_form_*` and `contact_form_*` columns now ride with the bundle (Forms admin copy / toggles / success messages). Recipient `*_to` columns are explicitly excluded as deployment routing — shipping them would silently re-route mail to the source's recipients on the destination.
- **Pages** — every `Page` row exports with `blocks_json`, `layout_key`, full background config (colour with light/dark/auto modes, image + tile / cover + scale, dynbg key + config JSON), width formatting (`width_mode` / `max_width` / `full_padding_pct`), and per-page hero typography overrides (`heading_color` / `heading_align` / `heading_font` / `subheading_*`). Import replaces by slug so an existing page on the destination is overwritten rather than duplicated.
- **IntergroupOfficer roster** — replaces wholesale on import with **source ids preserved**, so the `intergroup_member` and `officer_roster` page blocks (which store `officer_id` verbatim) keep working after the round-trip.
- **Stories** — `Story` rows including drafts and archives ride along. Author byline, sobriety / story dates, summary, body, featured image, and the `is_featured` flag are all carried.
- **Posts** — events + announcements, drafts + archives included. Pending submissions (`is_pending_review=True`) are skipped — the holding tank is per-deployment workflow state, not content. Source ids are preserved so the matching slug-history rows still resolve to the right entity.
- **Slug history** — `EntitySlugHistory` rows for `entity_type='post'` ride along so renamed posts keep their 301-redirects on the destination. Meeting slug history stays out of the frontend bundle (meetings live in the broader content scope this export deliberately avoids).
- **Asset collection extended** — page `bg_image_filename` + dynbg config JSON, story / post featured images, and embedded references inside page `blocks_json` and story / post markdown bodies are all scanned and bundled into `assets/`.

The whole-site export (`/tspro/settings/export`, the SQLite `VACUUM INTO` + `uploads/` + `zoom.key` archive) was already complete by definition — every new table since 1.8.6 is captured automatically — so no code change there, just verified the export still produces a healthy archive against the live data.

### Added — Library import wizard for bulk multi-file uploads

The library detail page gained an **Import Multiple** button (next to **+ Add File** in both the page header and the Files card foot) that opens a staging modal accepting any number of files at once. Drop them onto the dashed drop-zone or pick them via the inline label-wrapped picker; each file lands in a row with an editable title input pre-filled by the wizard's filename-to-title heuristic, the filetype badge, the original filename, and a per-row remove button. The footer shows a live "*N files ready to import*" count and keeps the **Import** button disabled until at least one file is staged. New backend route `POST /libraries/<slug>/readings/import` (`main.library_import`) consumes parallel `files`/`titles` arrays plus optional `category_ids`, creates one `LibraryItem` per file via `_save_upload` (so sha256 dedup applies — re-uploading identical bytes reuses the existing `MediaItem` row), and re-checks the Intergroup `categories_required` gate so a tampered POST can't bypass it.

- **Title derivation** — `_derive_title_from_filename` (Python) and the matching JS helper both strip the extension, replace `_-.` with spaces, split camelCase boundaries, collapse whitespace, and Title Case. Examples: `meeting_minutes_2024.pdf` → "Meeting Minutes 2024", `BigBook_PersonalStories.pdf` → "Big Book Personal Stories", `step-12-essay.pdf` → "Step 12 Essay". Empty filenames fall back to "Untitled". Server-side derivation is the fallback for any row whose title input was left blank.
- **Title row is nameless in the DOM** — only the live file input is `name="files"`; per-row title `<input type="text">` carries no name. On submit, the JS strips any prior `data-import-title-hidden` carriers and appends fresh hidden `<input name="titles">` elements in the same order as `picker.files`, so Flask's `request.files.getlist("files")` and `request.form.getlist("titles")` line up index-for-index.
- **DataTransfer-based file list** — `picker.files` is the live source of truth for what gets submitted; the wizard mirrors its `staged[]` JS state onto the input via a fresh `DataTransfer` on every add/remove so users can drop a batch, remove a wrong pick, drop more, and submit cleanly.
- **Soft de-dup** — same filename + size in the same wizard session is silently skipped client-side (defensive against double-clicking the picker); content-level dedup happens server-side via the existing sha256 check in `_save_upload`.
- **Modal-close reset** — closing the modal (× button, backdrop click, Cancel) clears the staged list so the next open starts fresh; without this the next session would replay stale `File` handles whose underlying disk content might have changed.

### Added — Library page block: max items + Load More + sort

The Library block gained two new controls in its settings panel: a **Sort items by** dropdown (Custom order · Name A→Z · Name Z→A · Date added newest · Date added oldest) and a **Max items** number input. When `max_items > 0` and the rendered count exceeds it, the renderer marks excess items with `block-library-hidden` and emits a centered pill-shaped **Load more (N more)** button below the items. Clicking it reveals the next batch (`data-lib-block-step` items, defaulting to `max_items`), updates the inline "(N more)" count, and removes itself once nothing's left to show. A single delegated click handler binds once per page (window-flag guard, IIFE) so multiple library blocks on the same page coexist without double-binding.

- **Sort plumbed through `library_block_data`** — accepts a fourth `sort` argument applied AFTER the granular hand-pick filter so curated subsets honour the chosen order. Recognised values: `manual` (default — library position then id), `name-asc`, `name-desc`, `date-desc` (newest first), `date-asc`. Unknown values fall back to manual.
- **Renderer integration** — all three styles (bulleted / list / cards) use Jinja's `loop.index0 >= _max_items` to mark hidden items. The wrapper carries `data-lib-block-max` and `data-lib-block-step` so the Load More handler knows the page step. CSS rule `.block-library .block-library-hidden { display: none !important }` beats the inline grid/flex declarations the wrapper rules emit.
- **Editor defaults preserved** — `sort: 'manual'` and `max_items: 0` are set as defaults, so existing library blocks keep their original look until an admin opts into a different sort or sets a non-zero max.
- **Mobile-aware Load More** — the button styling uses `color-mix(in srgb, var(--brand) 10%, var(--panel-2))` for the hover tint and rides design-token brand colours so it inherits the active theme. The `:active` state translates 1px down for tactile feedback.

### Added — Add to Calendar (.ics) downloads on meetings + events

Visitors can now save any meeting or event to their personal calendar with one click. New endpoints `GET /meetings/<slug>/calendar.ics` and `GET /event/<slug>/calendar.ics` emit RFC-5545 VCALENDAR payloads with proper line-folding (75-octet wrap), text escaping (`\,`, `\;`, `\\`, `\n`), and `Content-Disposition: attachment; filename="<slug>.ics"` so the file saves rather than opens in the browser.

- **Meetings** — one weekly-recurring `VEVENT` per `MeetingSchedule` row, joined by `RRULE:FREQ=WEEKLY;BYDAY=<MO|TU|WE|TH|FR|SA|SU>`. `DTSTART`/`DTEND` are computed from the next occurrence of the schedule's day + start time in the site's configured timezone, then converted to UTC for the serialised value. UID is stable per `(meeting_id, schedule_id)` so each weekly slot is its own calendar entry. `SUMMARY`/`DESCRIPTION`/`LOCATION` carry the meeting name, full body + Zoom join link / ID / passcode + canonical "Details:" URL, and a resolved address (matched through the `Location` table when available, falling back to raw text or `Zoom · <link>` for online-only).
- **Events** — single `VEVENT` (no `RRULE`) sourced from `event_starts_at` / `event_ends_at`. Stored datetimes are tz-naive but represent the site's local wall clock; the helper anchors them to the site timezone before UTC conversion so the wall-clock the admin typed survives DST shifts. Defaults to a 1-hour duration when `event_ends_at` is blank.
- **Buttons live under the schedule / When block** in every detail layout: meetings use `classic.html` / `magazine.html` / `card_stack.html` / `minimal.html`; events use `classic.html` / `minimal.html` / `poster.html` / `timeline.html`. The meetings list card (`_meeting_card.html`) gained a third pill alongside Join Zoom / Get Directions in both the 3-column day-grouped mode and the default directory/weekboard mode. Each link uses Lucide's `calendar-check` icon and the HTML5 `download` attribute so the file lands as `<slug>.ics` instead of opening in-browser.
- New module `app/calendar_export.py` exposes `meeting_to_ics(meeting, site, base_url)` and `event_to_ics(event, site, base_url)`. Both go through helpers `_escape`, `_fold`, `_fmt_utc`, `_next_occurrence` so future calendar exports (announcement series, classes, etc.) can reuse the same primitives.
- `Cache-Control: no-store` on both endpoints so an admin schedule edit propagates to the next download immediately.

### Added — Library page block

New **Library** block in the floating palette renders any Library's items in three configurable styles: **Bulleted** (UL with markers, title-only), **Plain list** (bordered card with hairline-separated rows; title + description excerpt + category chips), **Cards** (CSS Grid with rounded-corner cards, hover lift, optional 16:9 thumbnail strip, title + body excerpt + category chips). Cards mode adds column-count toggle (1/2/3) and gap input.

The block stores `library_id`, `mode` (`'all'` | `'granular'`), `item_ids[]`, `style`, `columns`, `gap`, plus three field toggles (`show_description`, `show_thumbnails`, `show_categories`) and an optional `title` heading. New `library_block_data(library_id, mode, item_ids)` Jinja global resolves to `(library, filtered_items)` at request time so admin edits to the library propagate to every page using it without re-saving. Granular mode exposes a checklist of every item in the chosen library with **Select all** / **Clear** quick actions; switching libraries invalidates the previous picks. Items with `stored_filename` link via `public.public_file`, items with `url` link externally, body-only items render as plain text. `window.tspLibraries` injected on the page-edit screen drives the editor's picker without an AJAX round-trip.

Mobile breakpoint at 720 px collapses the cards grid to a single column regardless of admin's chosen count.

### Added — Intergroup Officer roster + page blocks

New **Settings → Global → Intergroup Officers** section (the "Meeting Locations" tab was renamed **Global** since it's now the catch-all for site-wide rosters and singletons) hosts a repeatable contact table with position / name / phone / email columns. Add/remove rows inline, save persists; blank rows are silently dropped. Storage lives on a new `IntergroupOfficer` model (separate from the legacy `IntergroupAccount` which holds IMAP credentials, so officer roster edits don't churn email-server config).

Two new page blocks consume the roster:

- **Intergroup Member** — references one officer row by id and renders their contact card (position chip + name + phone link + email link) with four `show_*` toggles to gate which fields display. Editor dropdown lists every officer by their position name first, with the personal name in parens for context. Live preview card mirrors the public render. Renderer looks the row up at request time so officer edits propagate without re-saving consuming pages.
- **Officer Roster** — loops every officer into a configurable card grid. 2 or 3 column toggle, configurable gap, same four field toggles applied uniformly. Each card has shadow + rounded corners + hover lift. Mobile collapses to single column.

`intergroup_officers()` and `intergroup_officer(id)` Jinja globals expose the roster to templates; `window.tspIntergroupOfficers` carries the same data into the page editor for instant dropdown / live-preview without AJAX.

### Added — Lottie animation page block with hover playback

New **Lottie** block in the floating palette embeds Bodymovin / Lottie JSON animations. Vendored `lottie-web@5.12.2` lives at `app/static/vendor/lottie/lottie.min.js` (300 KB, self-hosted, no CDN dependency). The block stores `src` (URL or `/pub/<filename>` path), `loop`, `autoplay`, `speed` (0.25–3×), `max_width_pct`, `align`, `bg_color`, `renderer` (`svg` | `canvas`), and `playback` (`auto` | `hover`).

- **Editor settings panel** — file upload (accepts `.json` / `.lottie`) reuses the existing `/tspro/files/upload` endpoint. Live animated preview inside the modal uses lottie-web on-demand-loaded so admins see the actual animation playing while tweaking settings. Width slider, alignment toggle, playback dropdown (Autoplay / Play on hover), Loop checkbox, Autoplay checkbox (auto-hides in hover mode since it's implicit), speed slider, renderer dropdown (SVG sharp / Canvas faster), background-colour input.
- **Hover playback mode** — animation parks at frame 0; on `mouseenter` it plays forward, on `mouseleave` it reverses back to frame 0 with an `enterFrame` watcher that pauses on reaching frame 0 so it doesn't loop in reverse forever. A `click` handler toggles play/reverse for touch devices. CSS adds `cursor: pointer` and a subtle scale on hover to telegraph interactivity.
- **Aspect-ratio detection** — the public init script and editor preview both listen for lottie-web's `DOMLoaded` event, read `anim.animationData.w` / `.h`, and stamp `--lottie-ratio: <w>/<h>` onto the wrapper. The stage's CSS reads this var via `aspect-ratio: var(--lottie-ratio, 1 / 1)` so non-square animations get the right shape instead of being letterboxed inside a forced square.
- **Conditional script include** — `frontend/page.html` only loads `lottie.min.js` and the init script when at least one Lottie block exists on the page (detected server-side via the new `_sections_have_block_type` walker). Pages without Lottie content skip the 300 KB asset entirely.

### Added — Three-panel row primitive in the block palette

Companion to the existing **Two-panel row**: **Three-panel row** mints a 3-column grid container (`grid_columns: "1fr 1fr 1fr"`, `gap: 2rem`) with three inner containers ready to host child pills. The drop handler in `page_structure.js` was generalised to `splitCols = type === 'split' ? 2 : (type === 'split3' ? 3 : 0)` so adding a `split4` later is one ternary branch. Catalog tile uses the `layout-grid` Lucide icon to differentiate visually from the 2-panel `columns` icon.

### Added — Container labels (admin-only) editable from the structure tree

Containers gained a new `data.label` field surfaced exclusively in the page-edit structure card — public renders ignore it. The Settings panel's first group is now a **Label** input ("Optional admin-only name (e.g. 'Officers')"); typing in it shows up immediately in the structure tree row's title.

The structure card now renders the row's label as a normal-cased title (instead of the all-caps "CONTAINER" tag) and a small "container · single column" / "N-column container" subtitle for context. **Inline editing** — the row label area is a transparent `<input type="text">` that admins can click and edit directly without opening the modal; on input, `findContainerPayload(blockId).data.label` updates and `syncStateFromDom()` writes the new value to the hidden form input. Sortable's drag-handle filter excludes the label input so clicking it doesn't kick off a row reorder. The popover/modal flow round-trips: editing the label in the structure card updates the editor modal on next open (via `remountPageBlockEditor`), and editing it in the modal persists back through the standard form save.

### Added — Floating, collapsible block palette

The **Add blocks** palette is no longer a static card pinned at the bottom of the page tree. It floats in the lower-right corner of the page-edit screen as a collapsible FAB → panel:

- **Collapsed** state shows a pill-shaped **+ Add block** button with brand-colour fill, drop shadow, and a hover-lift. Clicking it scales the FAB out and slides the panel up from the same bottom-right anchor with a `cubic-bezier(0.2, 0.8, 0.2, 1)` ease (280 ms scale+translate, 220 ms opacity).
- **Expanded** state hosts the full tile grid in a rounded card with header + close × + drag-instruction copy. Click outside, hit `Escape`, or click × to collapse. Click-outside is suppressed while a tile is mid-drag (with a 100 ms grace window after `dragend` for the synthetic click some browsers fire after a drop) so the panel stays open across drops — admins can drag several blocks before manually collapsing.
- Drag-drop wiring is unchanged: tiles still carry `data-be-block-{type,name}` and the grid still has `data-be-palette` so the existing handlers attach without modification. The panel wrapper has `pointer-events: none` so its empty area doesn't block underlying clicks; children re-enable.

### Added — Page background colour with Light / Dark / Auto modes + design-token palette

Pages gained a **Background colour** section in the Page Settings card sitting between the Dynamic background and Background image sections. Three new columns on the `Page` model (`bg_color`, `bg_color_dark`, `bg_color_dark_mode`) — additive `_migrate_sqlite` entry so existing deployments survive the upgrade. The light value goes on `background-color`; the dark value rides `--tsp-bg-dm` which the existing `html[data-theme="dark"] [style*="--tsp-bg-dm"]` rule swaps in (same pattern containers use).

The dark-mode mode field gates how the dark variant resolves:

- **Same as light** — no `--tsp-bg-dm` emitted (light value applies in both modes).
- **Auto-derive dark variant** — the existing `derive_dark_color()` HLS helper produces a dark-mode-friendly variant from the light hex.
- **Manual** — admin sets `bg_color_dark` explicitly (with auto-derivation as a fallback when the field is left blank).

**Token-aware values** — `bg_color` / `bg_color_dark` accept either a hex literal (`#fef3c7`) OR a design-token reference (`token:color_brand`). Tokens stay live: the renderer emits `var(--fe-color-<key>)` so updating the token under Settings → Design retints every page using it without re-saving. Both inputs have a 🎨 **Tokens** button next to the existing swatch + hex pair; clicking opens a popover (`position: fixed`, anchored under the trigger, viewport-edge-clamped) listing every color token with its label + current resolved hex as a clickable swatch. Selecting a token writes `token:<key>` to the text input and updates the swatch to the resolved hex so the visual preview stays accurate. The `<input type="color">` always shows the resolved hex, even when the stored value is a token reference. Save endpoint validates `token:<key>` against `DESIGN_FIELDS_BY_KEY` so only real color tokens land in storage.

### Added — Token picker on every block-editor color input

The 🎨 token picker is now woven into every color UI in the block editor. New `attachTokenButton(textInput, swatchInput)` helper in `block_editor.js` adds the button to a color cluster and shares a single lazily-built popover (`_ensureTokenPopover` / `_openTokenPopover`) that any picker can trigger. Click-outside / Escape / × all dismiss; toggling the same anchor closes it.

- `colorPair` (used by container bg, border, button bg/hover/text/border, and several misc inputs) — gained the 🎨 button between text and Clear; text input now accepts `token:<key>` without flagging as invalid; swatch always shows the resolved hex (looked up from `window.tspDesignColorTokens`).
- `colorPickerWithDarkMode` (typography color, list card colors, icon block) — same upgrades on both Light and Manual-dark rows.

New `css_color` Jinja filter translates stored color values into CSS-emitable strings: `'#fef3c7'` → `#fef3c7`, `'token:color_brand'` → `var(--fe-color-brand)`, blank → empty string. Applied at every inline-style color emission point in `_blocks.html` and `frontend/page.html` (container bg/dark, container border + dark, container hover-bg / hover-border, list card bg / border / number bg + color, image bg, image caption color, icon color + dark, button bg / hover-bg / text / hover-text / border / hover-border / shadow, typography color + dark, page heading_color + subheading_color). `_norm_color` (page-edit save validator for heading/subheading) also accepts `token:<key>` for any registered color token.

### Added — Card Dark design token

New **Card Dark** color token (`color_card_dark`, default `#1f2937`) under Settings → Design → Colors. Emits as `--fe-color-card-dark` on `<body>` so any block or stylesheet can reference it via `var(--fe-color-card-dark)`. Theme defaults updated on both `classic` and `recovery-blue` themes; `design_css_vars()` includes the new key in its emission tuple.

### Added — Container removal: two-choice safety modal

When deleting a container that holds blocks, the structure tree now opens a custom modal instead of the bare `confirm()` that auto-parked everything to the orphan bin. Two card-style buttons: **Move blocks to "Unplaced blocks"** (neutral styling, current behavior — children survive in the bin) and **Remove everything** (red title + red hover, recursively flags every descendant id into `intentionallyRemovedIds` so the safety net doesn't sweep them back). Cancel / × / backdrop / Escape all dismiss. Empty-container removals stay a one-line `confirm()` (nothing to ferry).

### Added — GUI-friendly grid-column editor

When a container's Display flips to Grid, the Layout panel now exposes a column-count stepper (`[−] N columns [+]`, clamped 1–12), quick-preset chips (`2 equal`, `3 equal`, `4 equal`, `Sidebar + main`, `Main + sidebar`, `1:2`, `2:1` — active preset highlights in brand colour), per-column track selectors with common values (`1fr / 2fr / 3fr / auto / min-content / max-content / 80px–320px / 25–75% / Custom value…`), and a live preview bar where each segment scales to the track's relative weight (1fr → 1, 200px → 2, auto → 1, % → fraction).

An **Edit raw CSS instead** escape hatch flips the panel into a single text field for `calc()`, `minmax()`, `fit-content()`, named lines, etc. Round-tripping: `repeat(N, X)` ↔ N tracks of X; `1fr 2fr 1fr` ↔ three explicit tracks; anything containing `(` auto-flips to advanced mode so we never silently mangle a value. The serializer collapses N identical tracks back to `repeat(N, X)` for cleanliness on save.

### Changed — Settings tab "Meeting Locations" renamed to "Global"

The Settings modal tab now reads **Global** to reflect that it hosts every site-wide roster + singleton (Meeting Locations + the new Intergroup Officers section). The `data-tab="locations"` slug stayed the same so all existing wiring (the iframe loader, the footer admin's "Edit in Settings" deeplinks) keeps working.

### Changed — Page Settings card: Visibility fieldset removed

The Visibility radio fieldset (Draft / Published / Private) was redundant with the status pills at the top of the page-edit screen, which post directly to `/frontend/pages/<id>/status`. The fieldset is gone; a hidden `status` field reflecting the current state preserves visibility on a normal Save round-trip so the form doesn't accidentally drop a published page back to Draft.

### Changed — Container blocks: round-robin distribution + auto-fit / auto-fill detection

The structure-tree builder for grid containers had two issues that the **Officer grid** on `/intergroup` exposed: (1) overflow children (more items than columns) all dumped into the last cell because of the `cells[i % n_cols] if i < n_cols else cells[-1]` clause; (2) `repeat(auto-fit, minmax(260px, 1fr))` parsed as 3 columns by token-count even though the rendered count varies with viewport.

Fix: `_grid_col_count()` now treats any `auto-fit` / `auto-fill` grid as 1 column so the structure tree shows the children as a flat stack (the public render still flows them as a wrapping grid). The distribution loop simplified to `cells[i % n_cols]` for every child, mirroring CSS grid's default `grid-auto-flow: row` — a 3-column grid with 6 items now distributes 2/2/2 across columns instead of 0/0/6. Same auto-fit detection mirrored in `page_structure.js`'s `gridColCount` so client-side re-renders match.

### Changed — Edit modal opens at the top + drops the focused block's own head

`focusBlock` in the page-edit script now resets `modal-body.scrollTop = 0` instead of calling `target.scrollIntoView({ block: 'center' })` — with focus-mode hiding every sibling, centering the lone visible target only nudged the scroll a few pixels for no benefit. In `.is-focus-mode`, the focused block's own `.be-block-head` (drag handle, type label, × remove button) is now `display: none` and its outline / border / padding / background are zeroed out. The settings panels (Label, Layout, Spacing, etc.) start right at the top of the modal body — the modal reads as a clean settings sheet for the clicked block, not a floating draggable card.

### Changed — Grid controls row gap

Added `display: flex; flex-direction: column; gap: 0.5rem;` to `.be-container-grid-controls` so each row inside the grid editor (column count, quick presets, per-track selectors, preview, advanced toggle) sits with 0.5 rem of breathing room.

### Changed — `/intergroup` page: standard containers + admin labels

The seeded `/intergroup` page replicating dccma.com's content was rebuilt to use **only standard Container blocks** instead of section-titled wrappers (the latter weren't editable from the structure card). The whole page lives in one untitled section containing 9 labeled top-level Container blocks — each former section title became:

- the container's admin-only `label` (e.g. **Officers**, **Meeting Resources**) so the structure tree reads at a glance.
- a fully-editable `<h2>` heading block as the container's first child so the public-facing section title is still there.

Inner containers (the meeting card, meeting actions row, officer grid, individual officer cards) all carry their own labels too: "Meeting card", "Meeting actions", "Officer grid", "Officer · Chair", and so on.

### Fixed — Mass-delete container loses nested empty containers to orphan bin

When the user picked **Remove everything** on a container with nested containers + leaf blocks, the leaf ids were flagged but nested-container ids were not — the safety net then "rescued" the empty wrappers into the Unplaced bin. The walk now hits three sources: leaf-pill payloads (`data-block-payload`), every nested `[data-be-row-block-id]` row inside the container being removed, and the parent container's full payload tree from `findContainerPayload`. All descendant ids get flagged before the row is removed so the safety net leaves them alone.

### Fixed — Container Flex → Grid swap blanked the modal

Flipping a container's Display from Flex to Grid in the settings panel called the editor's top-level `render()`, which wiped `sectionsEl.innerHTML` and rebuilt the editor — but the focus-mode CSS hides every `.be-block` that doesn't have `.be-block-focused` (or an ancestor `.be-block-focused-path`). Class assignments live on DOM nodes, not data, so the rebuild dropped focus and the modal went blank.

`render()` now captures the currently focused block's `data-id` before clearing the DOM, then re-applies `.be-block-focused` to the new node and walks up its ancestors to re-stamp `.be-block-focused-path`. The logic mirrors `focusBlock` in `frontend_page_edit.html`. Same fix benefits any other in-place re-render (list item add/remove, section delete, etc.).

### Fixed — Update toast covered by the floating block palette

Bumped `.version-update-banner`'s `z-index` from `400` to `2147483647` (the CSS z-index ceiling — max signed 32-bit int) so it sits above the floating palette (`1000`), modals (`100`), the wp-fetch overlay (`9999`), and anything future code might add. Both elements still anchor to bottom-right; the toast now sits visually on top of the FAB instead of behind it.

### Fixed — Token popover not appearing (off-screen positioning)

The page-bg token popover was opening but landing off-screen because it was `position: absolute` with top/left computed in form-relative coords, while its nearest positioned ancestor was the section (since the section had `position: relative` set). Switched to `position: fixed` with viewport coords from `getBoundingClientRect()`, no offset math. Also added a right-edge clamp so the panel can't slip past the viewport on narrow windows. `z-index: 1100` so it sits above the floating block palette but stays below the update toast.

### Changed — Mega menu builder: "Override size" label clarified

The per-link size-override checkbox in the mega menu builder (`_nav_megalink.html`) was labelled simply **Override size**, which sat ambiguously next to the other size controls (icon size, image size, etc.). Renamed to **Override font size** so it's unmistakably the link-text scale, not anything geometric.

### Changed — Mega menu: external links swap chevron for an external-link glyph

The trailing icon next to each mega menu link now reflects whether the link leaves the site:

- **Internal links** (relative paths like `/meetings`, anchors like `#section`, etc.) keep the existing `chevron-right` glyph.
- **External links** (URL starts with `http://`, `https://`, `mailto:`, or `tel:`) render Lucide's `external-link` icon — the box-with-arrow-exiting-top-right shape — so visitors can tell at a glance which links open something off-site.

Detection is purely template-side via `link.url.startswith(...)` on the four prefixes above; no schema or model change. Same 20px sizing, same `currentColor` stroke, same hover slide. Both megamenu themes (Recovery Blue + Classic) get the swap, and a `--external` modifier class is stamped on the wrapper so future styling can differentiate further if needed.

### Changed — Mega menu chevrons: always visible, real chevron, sized + tinted to match label

Three small changes to the trailing arrow on each mega menu link, applied to both `recovery-blue.html` and `classic.html`:

- **Always visible.** The chevron used to be `opacity: 0` until hover, with a 6px slide-in animation — a "gotcha" affordance that hid the link's clickable nature on first view. Now the chevron sits at full `opacity: 1` at rest, with the slide compressed to a subtle 3px nudge on hover for a touch of motion.
- **Real chevron, not an arrow / glyph.** Recovery Blue was using `icon('arrow-right')` (a straight arrow), Classic was rendering a literal `→` text glyph. Both now use `icon('chevron-right')` — Lucide's actual chevron — so the visual matches the rest of the UI's chevrons (the dynbg-trigger caret, calendar nav, etc.) and renders cleanly at any DPI.
- **20px square + matches text colour.** Both chevron containers now declare `color: inherit` and `opacity: 1` so the SVG's `currentColor` stroke paints in exactly the link label's colour (white-on-blue on Recovery Blue, dark-on-light on Classic, or any per-link override). The icon itself was bumped from 16×16 to 20×20.

### Added — Image block: corner roundness + drop-shadow with mobile-aware scaling

The image block grew two style controls in the BlockEditor and a matching pair of inline-style outputs in every public renderer:

#### BlockEditor controls

- **Corner roundness** — a 0–50px slider live-updates the in-modal preview's `border-radius`. Default of 0 (sharp). The slider's px value is written into the block's `data.border_radius` and surfaced as a CSS custom property (see render-side details below).
- **Drop shadow** — a `<select>` with five presets: **None** / **Subtle** / **Soft** / **Pronounced** / **Dramatic**. Each preset maps to a pre-baked `box-shadow` recipe (e.g. `Soft` → `0 4px 6px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.06)`). The preview img inside the modal applies the recipe live so admins see the saved render before clicking Save.
- Both controls slot into the existing image-block form between Alignment and Caption colour, alongside the existing Width / Alignment / Caption fields.

#### Public render

- **Two renderers updated** so the new fields take effect everywhere the image block is used: `_blocks.html` (admin / Zoom Tech surfaces, generic block macro) AND `frontend/page.html` (the page-detail-specific image renderer). The latter is what `/<slug>` pages use; without updating it, settings appeared to save but didn't render — caught when corner roundness on `/marcma` had no visible effect.
- **Inline shadow recipes** are stamped directly on the `<img>` (`box-shadow: ...`) so the shadow tracks the actual visual bounds of the image rather than the surrounding `<figure>`. Recipes match the JS preview's `SHADOW_RECIPES` map exactly so the modal preview equals the live render.

#### Mobile-aware corner-radius scaling

A 32px corner radius reads cleanly on a desktop hero image but looks comically rounded on a 320px-wide phone screen. To get proportional softening without a second admin field, the renderer emits `--img-radius: <n>px` as a CSS custom property (instead of a hardcoded `border-radius` declaration), and `frontend.css` consumes it:

  ```css
  .fe-pp-figure img,
  .block-image img { border-radius: var(--img-radius, 0); }
  @media (max-width: 560px) {
    .fe-pp-figure img,
    .block-image img { border-radius: calc(var(--img-radius, 0) / 2); }
  }
  ```

  So 32px on desktop → 16px on phones, 24px → 12px, 8px → 4px, etc. The 560px breakpoint matches the convention used elsewhere in `frontend.css`.

  The existing `.block-image img` rule in `app.css` (admin / Zoom Tech surfaces) was migrated to `border-radius: var(--img-radius, 6px)` so legacy unedited blocks keep their 6px default while admin-set values override via the inline custom property.

### Fixed — Page editor: orphan × button now actually deletes

Two bugs were stacked on top of each other so that clicking × on an Unplaced-blocks pill did nothing useful — it either popped a blank Edit-layout modal or appeared to delete the block only for it to re-spawn on the next sync.

- **Modal-open click was beating the × handler.** Orphan pills carry `data-open-modal="page-layout-edit-modal"` for the click-to-edit flow. `app.js` binds a per-element bubble-phase click listener on every `[data-open-modal]` element that calls `openModal(...)` unconditionally — without checking for clicks on inner buttons. Clicking × bubbled through that listener BEFORE `page_structure.js`'s document-level remove handler ran, so the editor popped open empty and the confirm dialog appeared on top of it.
  - Fix: bind a click listener directly on every `[data-be-remove-block]` / `[data-be-remove-row]` element. Listeners on the target element fire BEFORE bubble-phase listeners on ancestors, so the parent pill's modal-open listener never sees the click. The handler does `stopImmediatePropagation` + runs the remove logic. A capture-phase document delegate stays as a fallback for dynamically-minted × buttons; a `MutationObserver` picks up new × buttons (palette drops, BlockEditor mutations) so they get the per-button binding too.
- **Safety net was rescuing deliberate deletes.** `syncStateFromDom` snapshots every block id before reconstructing from the DOM and re-stamps any "lost" ids into the Unplaced bin — meant to catch drag-drop reconstruction bugs. It couldn't tell a deliberate × delete apart from a dragged block that fell off the rails, so every orphan delete was undone in the same call: pill removed → safety net sees the id missing → safety net stamps a fresh pill back.
  - Fix: introduced an `intentionallyRemovedIds` set. `handleRemoveBlock` and `handleRemoveRow` register the deleted block's id (plus all descendant ids — a container delete cascades) before calling `syncStateFromDom`. The diff skips any id in the set, then the set is consumed at the end of each sync so future drag-drop bugs still trigger normal rescue behaviour.

### Changed — BlockEditor: deleting a container preserves its children + closes empty focus modal

Two related fixes to the modal-based block editor when removing a block that's the focus of the modal:

- **Container delete dumps children to Unplaced blocks (no refresh required).** The modal's × on a block did `parentBlocks.splice(bi, 1)` and re-rendered. For container blocks holding children in `data.blocks`, those children disappeared with the container — no rescue, no orphan rescue, just gone on save. Now the × handler detects a non-empty container, confirms with the count ("Its X blocks will move to 'Unplaced blocks' so nothing is lost"), splices the container out, and dispatches a `blockremove` CustomEvent carrying the children's payloads on `detail.liftedChildren`. `page_structure.js` listens for the event on `#page-editor-root`, stamps each child as a pill via the existing `makeNodeFromPayload` helper, appends to the orphans zone, removes the `is-empty` class, and re-syncs the hidden field — all without leaving the modal or reloading the page.
- **Empty modal after focused-block delete.** When the admin opened the modal focused on a block then clicked × inside, the block was deleted but the modal stayed open in focus mode showing a blank panel. Added a `blockremove` listener on the modal that checks for the absence of `.be-block-focused` and clicks the modal's `[data-close]` to dismiss it. Non-focused deletes (× on a sibling block while the modal is open in full-editor mode) leave the modal as-is.

### Changed — Pages list: 3-status visibility, sortable columns, multi-row bulk actions

Pages got a real Draft / Published / Private state machine and a backend list that lets admins flip multiple at once. The single-checkbox `is_published` toggle is gone; in its place a three-way visibility model:

- **Draft** — `is_published=False`. Hidden from public — anonymous visitors get 404, signed-in editors / admins can preview by visiting the URL.
- **Published** — `is_published=True`, `is_private=False`. Visible to everyone, listed on the Site Index.
- **Private** — `is_published=True`, `is_private=True`. Only signed-in editors / admins can open the URL — anonymous visitors get the same 404 they'd see for a draft. Hidden from the Site Index and any future public navigation.

#### Schema

- **New `Page.is_private` boolean column** (default `False`) with a `_migrate_sqlite` entry so existing deploys add the column without touching `is_published`. Combined with the existing `is_published` column to encode the three states above.

#### Public gating

- **`frontend.page_detail`** — gate widened: published-and-not-private for anonymous, published-and-anything for signed-in editors. The 404 path is identical for both Draft and Private viewed by anon, so a Private page's existence isn't leaked.
- **`frontend.site_index`** — Pages section now filters `is_published=True, is_private=False` (Site Index never advertises Private pages).

#### Admin: page edit screen

- **Visibility fieldset** replaces the single Published checkbox in `frontend_page_edit.html`. Three-way radio with a one-liner description for each state.
- **Status pill row** sits under the title banner — Draft / Publish / Make Private. Clicking a pill **selects the matching radio** in the page-settings form and dispatches a `change` so the shared save bar lights up "Unsaved changes". No auto-submit, no separate quick-action endpoint round-trip — same form lifecycle as editing any other field. Pills mirror the radio's state live; flipping the radio directly inside the fieldset keeps the pills in sync.
- **Status chip in the title banner** — Draft / Published / Private with the matching `.post-chip-*` colour.

#### Admin: pages list

- **Sortable columns** — Title, URL, Layout, Status, Updated. Click a header to sort; click again to reverse. Default sort is Title ascending. Sort is purely client-side: each `<tr>` carries `data-sort-*` keys the click handler reads, and the tbody re-orders in place. The Updated column carries an epoch-timestamp data attribute for proper numeric ordering.
- **Checkboxes per row + select-all** in the header. Selecting at least one row reveals a bulk-action toolbar above the table.
- **Bulk-action toolbar** — Draft / Publish / Private buttons posting to the new `frontend_pages_bulk` endpoint. Single commit applies the same status flip to every selected row.

#### Endpoints

- **`POST /tspro/frontend/pages/<id>/status`** — single-page quick-action endpoint (kept for direct callers, no longer used by the edit-screen pills since those go through the normal save flow now).
- **`POST /tspro/frontend/pages/bulk`** — multi-row bulk action. Accepts `page_ids[]` + `status`. Unknown ids are silently dropped; unknown statuses flash an error.
- **`frontend_page_save`** — accepts the new `status` field (draft / published / private) with a fallback to the legacy single-checkbox `is_published` + `is_private` form for older callers.
- **`frontend_page_create`** — accepts an initial `status` from the New-page modal (still defaults to `draft` if omitted, matching the existing modal flow).

#### CSS

- **`.post-chip-private`** — purple variant alongside the existing online / draft / announcement / event / warning chips, with a dark-mode parity rule.
- **`.fe-pages-list-card .tbl thead th.sortable`** — cursor + hover background + bidirectional arrow indicators (filled when active, faded when inactive).
- **`.fe-pages-bulk-bar`** — brand-tinted toolbar that animates in via the `[hidden]` attribute toggle, hosting the count + action buttons.
- **`.fe-page-status-fieldset`** + **`.fe-page-edit-status-actions`** — the edit-screen visibility fieldset and its companion pill row.

### Added — Site Index frontend template (`/siteindex`)

A new auto-populated table of contents page that lists every public surface on the site — pages, meetings, events, announcements, stories, library items — picked up automatically as content is added. Two layouts plus the same Customize machinery (Background / Fonts / Sizes / dynbg + overlays + custom colours + randomize) every other template gets.

#### Public render

- **`/siteindex`** (route lives in `app/frontend.py`) — gated by the `frontend_site_index_enabled` toggle so the URL 404s until an admin publishes it. Originally shipped at `/site-index`; renamed to `/siteindex` to match the existing flat-slug convention (`/submissionform`, `/printlist`, etc.).
- **Two layouts under `app/templates/frontend/site_index/`**:
  - **Grouped** — sections by content type with an eyebrow heading + count chip per group. Items inside each group sort alphabetically.
  - **Alphabet** — single A–Z list flattened across all kinds, each row tagged with a brand-tinted kind chip so admins still see what they're looking at without needing the group structure.
- **`_site_index_groups(site)` helper** — pulls from `Page` (published, non-private), `Meeting` (active), `Post` (published, non-archived events / announcements), `Story` (non-draft, non-archived), `Library` + `LibraryItem` (public-visible). Each item carries `{title, url, kind, subtitle, date}` so layouts can render flexibly.
- **Sections group at the top** — the Grouped layout's first section lists the top-level template pages: Home, Meetings, Events, Announcements, Stories, Library, Print list. Each entry is gated by its respective feature flag (events / announcements respect `posts_enabled`; stories respects `stories_enabled`) so the index never points at a 404.

#### Schema

- **13 new `SiteSetting` columns** with `_migrate_sqlite` entries: `frontend_site_index_enabled`, `_template`, `_heading`, `_subheading`, `_sort_mode`, six `_show_*` per-section toggles (pages / meetings / events / announcements / stories / library), `_bg_dynamic_key`, `_bg_dynbg_config_json`. Per-template style overrides reuse the existing `frontend_template_settings_json` JSON column keyed by `(kind, key)` — same shape every other template uses, no per-section column explosion.
- **`siteindex` reserved slug** — added to `frontend_page_create` and `frontend_page_save` slug-uniqueness sets so admins can't claim it as a Page slug and shadow the index route.

#### Admin

- **New section on `/tspro/frontend/templates`** — card grid for the two variants, the standard `tpl_customize_panel` (Background / Fonts / Sizes), heading / subheading inputs, sort-order radio (Grouped / A–Z), six per-section visibility toggles, and the Publish toggle that gates the public route. Posts to a new `frontend_site_index_template_save` endpoint. Bonus cleanup: removed a stray duplicate `if`/dead `from .frontend import _post_in_archive` line in `_site_index_groups()`.
- **`site_index` added to `_TEMPLATE_KINDS`** + the `catalog_map` in `frontend_template_settings_save` so per-template settings round-trip through the same dispatch table as every other kind.

#### CSS

- **`.fe-site-index*` classes in `frontend.css`** — page heading + blurb, group eyebrow + count chip, row pill recipe (brand-tinted hover background, arrow that translates on hover, `:focus-visible` outline), kind chip on the alphabet variant matching the meeting-card schedule pill recipe, dark-mode parity tweaks.
- **`.fe-tplgrid-thumb-site-index-*` classes in `app.css`** — picker thumbs for the two layouts (eyebrow bars + row stripes for grouped, centered title + flat row stack for alphabet).

### Changed — Templates admin: uniform Customize panel on every template card

Every template card on `/tspro/frontend/templates` now exposes the same Background / Fonts / Sizes 3-column Customize dropdown — no matter the section. Previously only Meeting / Event detail (which used the `tpl_section` macro) had this panel; every other section had its own bespoke controls and admins had to hunt for settings that were present on one card but missing on another.

#### Reusable customize-panel macro

- **Extracted `tpl_customize_panel(kind, active_key, settings, name, scope_label)`** from the existing `tpl_section` macro. Drops in below any section's style cards. Background fieldset always carries both an override-page-background-colour toggle AND the dynamic-background trigger; Fonts has heading + body font selects; Sizes has heading + body size sliders with override toggles.
- **Open by default** — `<details>` element now ships with the `open` attribute unconditionally, replacing the conditional `{% if settings.bg or … %}open{% endif %}` that previously expanded only when the section already had saved overrides. Admins land on the page with all panels visible so they don't have to discover the toggle.
- **`Customize ""` empty-quotes bug fixed** — `_active_name = ''` from `{% set %}` inside `{% for %}` (Jinja loop scope doesn't leak) replaced with `templates | selectattr('key', 'equalto', active_key) | list | first` which actually returns a value the surrounding template can read. Summary heading now renders e.g. `Customize Sidebar` instead of `Customize ""`.
- **Sections alphabetical** — both the cards within each section AND the section blocks themselves now sort alphabetically. The `frontend_templates` route wraps every catalog in a `_by_name()` sort before rendering; `tpl_customize_panel` is rendered the same way on every card so the on-page experience reads as a single shape.

#### List-section form split

Each list section's single form (cards + per-section settings + one Save button) is split into:

  - **Form 1** — cards-only with a `Save layout` button.
  - **Customize panel** — own form posting to `frontend_template_settings_save`.
  - **Form 2** — page-heading copy + container width + pro-tips + dynbg / per-section settings + `Save Section settings` button.

Both forms post to the same per-section URL. Each save handler was refactored to use field-presence checks (`if "<field>" in request.form:`) so a layout-only POST doesn't clobber the heading / subheading / max_width / padding / dynbg fields and vice versa. Refactor applied to: announcements list, events list, stories list, meetings list, story detail, literature library. Printlist (no card variants) gets the customize panel directly under the section heading; Contact us gets it between its single "Split — intro + form" card and the existing PIC-toggle form.

#### Schema + dispatch additions

- **`_TEMPLATE_KINDS` extended** to all ten kinds (`meeting / event / story / meetings_list / events_list / announcements_list / stories_list / literature_library / printlist / contact`). Single dispatch table in `frontend_template_settings_save` maps each kind to its catalog (or one-key sentinel `default` / `split` for the single-rendering sections).
- **No new columns** — every section reuses the existing `frontend_template_settings_json` JSON column, keyed by `(kind, key)`.
- **`template_settings()` pass-through** — earlier the function silently dropped every dynbg-related leaf key (`bg_dynamic_key`, `bg_dynbg_overlay`, `bg_dynbg_colors`, `bg_dynbg_overlay_scope/size/intensity`, `bg_dynbg_randomize_colors/positions`, `bg_dynbg_animate`), copying only `bg / heading_font / body_font / heading_size / body_size` out of the leaf — so saves succeeded but the customize panel re-opened with `Choose…` as if nothing was persisted. Fixed by passing every dynbg key through alongside the existing five.

#### Standalone dynbg fieldsets removed

Each list section's redundant standalone "Dynamic background" fieldset was stripped — the customize panel's Background column owns the dynbg picker now. Each list shell template was updated to read dynbg from the per-template settings JSON first (`template_settings(site, kind, key).get('bg_dynamic_key')`) and fall back to the flat-field columns for back-compat with installs that already saved through the old standalone control.

#### Render-side wiring for entity-detail templates

- **`tpl_dynbg_config` plumbed through every entity-detail render call** in `app/frontend.py` — meeting, event, story, archive event, archive announcement. Each route now builds a complete dict (`overlay`, `colors`, `overlay_scope`, `overlay_size`, `overlay_intensity`, `randomize_colors`, `randomize_positions`, `animate`) from the per-template settings leaf and passes it to the partial.
- **13 entity-detail partials updated** (4 meeting + 4 event + 5 story) — switched from a hand-built `{overlay, colors}` dict to `tpl_dynbg_config`, and the inline-CSS-vars stamp now goes through `dynbg_resolve_colors(...)` + `dynbg_resolve_positions(...)` so the randomize flags actually take effect per-render. Two consecutive reloads of the same meeting / event / story page now produce different `--fe-dynbg-c1` and `--fe-dynbg-blob-a-top` values when randomize is on.

#### `_dynbg_picker.html` pseudo-cfg fix

The customize-panel call site previously built `_tpl_pseudo_cfg = {'overlay': …, 'colors': …}` and passed it to the dynbg trigger. Every other dimension (randomize_colors, randomize_positions, scope, noise_size, noise_intensity, animate) was missing from the pseudo-cfg, so opening the modal showed those controls in their default state even when persisted in JSON, and Save would clobber them with the empty defaults. Fixed by carrying every dimension `template_settings()` exposes.

### Changed — Meetings-list cards: dark-mode dimmed background + uniform description colour

- **`.fe-mlist-card` had no dark-mode override** — kept its default `background: #ffffff` declaration and the cards rendered as either glaring white tiles or, when overridden upstream, fully transparent rectangles against the dark page. Added an explicit dark-mode rule with `background: rgba(5, 8, 15, 0.85)` (a few stops *below* the page bg so each card reads as a sunken/dimmed tile rather than a raised lighter one) plus matching `border-color: #1f2a44`. The 85% alpha lets any page-level dynamic background paint subtly through the cards instead of them reading as fully opaque blocks.
- **Description text matches title** — the meeting-card description renders with `<p class="fe-mlist-card-desc muted">`, and the global `.muted` utility paints text in `var(--muted)` (a dim grey). Result: title was bright, description faded out — a visual mismatch within the same card. Forced `.fe-mlist-card-desc` (incl. `.muted` variant) to `color: inherit` in dark mode so description copy reads at the same weight as the title.

### Added — Dynbg modal: overlays, custom colours, per-render randomize, noise tunables

A second pass on the dynamic-backgrounds primitive that promoted the inline picker to a popup modal and grew three new dimensions: a separate texture overlay layer, custom-colour overrides per surface, and per-render randomization for both colours and positions.

#### Modal-popup picker (replaces the inline grid)

- **One global modal in `templates/base.html`** (`#dynbg-picker-modal`) lives at body root on every admin page. The trigger macro emits a hidden `<input>` + a button; clicking the button opens the modal pre-populated with the trigger's saved state. Save writes the selection back via `change` events on the hidden inputs; Clear all wipes every dimension at once.
- **Tabs inside the modal** — `Background` / `Overlay` / `Colours`. Each tab is its own selection state; Save commits all three at once.
- **`dynbg_trigger(...)` macro in `templates/_dynbg_picker.html`** — drop-in form control for any admin form. Renders a hidden input + a button with the current preset's name + a small live thumbnail preview. The button's `data-dynbg-*` attributes carry every dimension's current value so the modal reads + writes them on open / save.
- **Lazy DOM lookup in the JS handler** — modal markup lives near the bottom of `<body>`, AFTER the `<script src="app.js">` tag, so caching DOM references at script-load time would resolve to null. Every reference is re-fetched inside the handlers so the IIFE is order-independent and survives templates moving the markup around.
- **Delegated trigger handler** so triggers added later in the page lifecycle (e.g. by the block editor when an admin opens a container's edit panel) pair up automatically.

#### Overlay layer

- **New `OVERLAYS` catalog in `app/dynbg.py`** — six presets at launch: `noise-grain` (the viibeware sandpaper recipe — SVG fractal-noise data-URL at 3% opacity, tiled), `scanlines` (2px horizontal stripes at 1.5% alpha), `linen` (two-direction stripe weave), `vignette` (radial darken from corners), `crosshatch` (diagonal stripe pair), `dot-weave` (tiny halftone lattice). Each has dark-mode parity and respects `prefers-reduced-motion`.
- **Render partial `templates/frontend/_dynbg_overlay.html`** — sister to the base `_dynbg.html`. Emits a `<div class="fe-dynbg-overlay fe-dynbg-overlay-<key>">` whose CSS rules paint the texture above the base dynbg AND above page content (`pointer-events: none`, `z-index: 10`). Compose with any base background or stand on their own.
- **Apply helper `templates/frontend/_dynbg_apply.html`** — single include any host can drop in to render base dynbg + overlay together. Reads the saved JSON config and threads overlay key / scope / noise size / intensity through the partials.
- **Stamping at the host** — every dynbg-using surface decodes the stored config, calls `dynbg_resolve_colors(cfg)` + `dynbg_resolve_positions(cfg, key)` to get the per-render CSS-vars string, and concatenates into the host element's inline `style="..."` so colours + positions ride alongside the existing base styles.

#### Scope toggle (per overlay)

- **`overlay_scope` config field** with two values: `all` (default — texture rides over backgrounds AND content, the viibeware feel) and `bg` (texture sits beneath cards / typography). The latter applies the `.fe-dynbg-overlay--bg-only` modifier which drops the overlay's `z-index` from 10 to 0 so the host's content (forced to `z-index: 1` by the host's `:where` rule) paints on top.
- **Modal UI** — radio pair under the Overlay tab → Scope fieldset.

#### Noise-grain knobs

- **Two admin-tunable parameters** for the noise-grain overlay: `overlay_size` (drives `feTurbulence baseFrequency`, range `0.1`–`2.0`, default `0.9`; lower = coarser film grain, higher = ultra-fine sand) and `overlay_intensity` (drives the SVG rect's `opacity`, range `0.005`–`0.5`, default `0.03`).
- **Server-side data-URL generation** — `dynbg.noise_grain_data_url(size, intensity)` bakes the chosen values directly into the SVG's `feTurbulence baseFrequency` and rect `opacity` attributes (the SVG can't read CSS variables — those parameters must be literal at parse time). The partial stamps the URL inline as `style="background-image: url('...')"` only when the values differ from the defaults; otherwise the static CSS class default takes over.
- **URL-encoded apostrophes (`%27`)** inside the SVG so they don't conflict with the surrounding `url('...')` wrapper after HTML decoding. Without this, the inner `'` from e.g. `viewBox='0 0 256 256'` would close the `url()` string early and the browser would discard the rest as invalid CSS — a previous regression where any custom-baked URL silently rendered as broken CSS (no noise visible).
- **Modal UI** — two range sliders + a "Reset to default" button, visible only when the noise-grain card is the active overlay.

#### Custom colours (3 slots per surface)

- **Up to three custom hexes** per surface override the brand-token colours each base preset uses. Each preset's CSS now defines `--_db-c1 / c2 / c3` shadow vars that resolve through `--fe-dynbg-c1 / c2 / c3` first (set by the host's inline-stamped style) and fall back to the brand accent / hand-tuned secondary mixes.
- **Modal UI** — Colours tab with three colour-picker rows (paired `<input type=color>` + hex text input + per-slot Clear button). Empty slots fall through to the brand default; filled slots take over instantly via the CSS-vars stamp on the host.
- **Server-side gating** via `dynbg.normalize_color()` (3/4/6/8-digit hex regex) so a tampered POST can't inject arbitrary CSS through the inline-style channel.

#### Two independent randomize toggles

- **`randomize_colors`** — when on, the saved colour slots are ignored and `dynbg.random_colors(3)` generates a fresh brand-friendly palette per render (HSL with random hue + capped medium saturation / lightness so the palette stays brand-friendly: no muddy browns, no eye-searing neons). Same surface re-tints on every visit.
- **`randomize_positions`** — when on, `dynbg.random_positions(key)` returns a dict of CSS-variable → value pairs that randomise the position-shaped properties of the active preset, stamped onto the host's inline style. Per-preset randomisation:
  - `aurora-blobs`: each blob's top / left / bottom / right corner anchor + size (220–460px)
  - `mesh-gradient`: each layer's conic origin (x / y) + starting angle
  - `aurora-bands`: each band's sweep angle (40–160°)
  - `spotlight`: each spot's corner anchor + width / height (50–100%)
  - Other presets (dotted-grid, diagonal-lines, noise-paper, starfield) ignore this flag — they have nothing positional to move.
- **CSS retrofit for the four randomization-supporting presets** — every position-shaped value reads through a `var(--fe-dynbg-...)` chain with the original hand-tuned value as the fallback, so when randomize-positions is off the surfaces look exactly as before.
- **Backwards-compat** — the legacy single `randomize` field maps to both flags during decode; `encode_config(... randomize=True)` still works for any older callers.
- **Modal UI** — Colours tab → Randomize on every page load fieldset, two checkboxes (Colours / Positions) that work independently.

#### Wired into every existing dynbg surface

The picker macro now carries nine hidden inputs (base key + overlay + 3 colours + scope + noise size + noise intensity + randomize_colors + randomize_positions). Every save handler routes them through the new `_dynbg_config_from_form(form, config_field)` helper which encodes them as a single JSON blob into the matching `<surface>_bg_dynbg_config_json` column.

- **Schema additions** — Page + 8 SiteSetting columns (`bg_dynbg_config_json` + `frontend_<surface>_bg_dynbg_config_json` × 8). All auto-migrate via `_migrate_sqlite`.
- **Per-template settings JSON (Meeting / Event detail)** absorbs the same dimensions as additional keys (`bg_dynbg_overlay`, `bg_dynbg_colors`, `bg_dynbg_overlay_scope`, `bg_dynbg_overlay_size`, `bg_dynbg_overlay_intensity`, `bg_dynbg_randomize_colors`, `bg_dynbg_randomize_positions`).
- **Container blocks (block editor)** — JS `dynbgTrigger({key, overlay, colors, scope, noiseSize, noiseIntensity, randomizeColors, randomizePositions, onChange})` builds nine hidden inputs dynamically, consolidates their `change` events into a single onChange callback (microtask drain — the editor only re-serialises once per modal save, not nine times), and round-trips every dimension into the block's data dict. Public-side `_blocks.html` and `frontend/page.html`'s `pp_block` macro stamp the colour + position vars onto the container's inline `style` and include the apply partial.
- **Layout-template normalizer (`_normalize_blocks`)** preserves all the new container fields through saves so a layout-template ship can carry pre-textured containers without losing the picks.

#### Bug fixes uncovered along the way

- **Modal not opening** — fixed `if (!modal) return` early-bail by switching to lazy DOM lookups; the script-load-time `getElementById` was returning null because the modal markup is in `<body>` after the script tag.
- **Overlay not saving** — call sites of `dynbg_trigger(...)` weren't passing `config_field`, so the hidden inputs were named `bg_dynbg_config_json__overlay` (the macro default) but each save handler was reading `frontend_<surface>_bg_dynbg_config_json__overlay`. Picker-macro call sites updated to thread the matching field name through.
- **Trigger button reverts to "Choose…" after save** — `{% set _entry = ... %}` inside a `{% for %}` loop doesn't leak outside the loop scope. Switched to `dynbg_catalog() | selectattr('key', 'equalto', current) | list | first` which returns a value the surrounding template can read.
- **Internal-server-error on dashboard load** — modal's overlay-card thumbnails included `_dynbg_overlay.html` without the new size / intensity / scope kwargs, and `is not none` tripped Jinja's StrictUndefined. Defaulted all three optional kwargs at the top of the partial via `|default(none, true)`.
- **Page-level dynbg invisible behind opaque section bgs** — `.fe-mlist { background: var(--fe-panel-soft); }` was painting on top of the dynbg. Added a CSS rule that forces the immediate child sections of `.fe-page-dynbg-host.fe-dynbg-host` to `background: transparent` so the dynbg shows through.

### Changed — Templates admin: alphabetical card + section ordering

- **Cards inside each section sort alphabetically by display name** — `frontend_templates` route wraps every catalog (Meeting / Event / Stories list / Stories detail / Events list / Meetings list / etc.) in `sorted(catalog, key=lambda t: (t.get("name") or "").lower())` before passing them into the template. The sort is admin-page-local; the underlying `*_TEMPLATES` lists keep their declared order so other call sites (lookups by key, "first available template" fallbacks) stay deterministic.
- **Section blocks themselves sort alphabetically by heading** — physically reordered the `<section>` blocks in `templates/frontend_templates.html` so admins now see Announcements / Events detail → Announcements list → Contact us → Events list → Literature Library → Meeting detail → Meetings list → Printlist → Stories list → Story detail. Previously Stories list / Story detail interrupted the alphabetical run between Announcements list and Events list.

### Added — Dynamic backgrounds library

A new visual primitive: a catalog of CSS-driven, optionally-animated backdrops that any frontend surface can opt into alongside its existing solid-colour / gradient / image options. Eight presets ship today; adding a ninth is one Python dict entry plus one CSS rule and every picker on the site lights it up automatically.

#### Catalog + render primitive

- **`app/dynbg.py`** — single source of truth for the catalog. Each entry is `{key, name, description}`. Helpers: `by_key(key)` for lookup, `normalize(key)` to coerce a possibly-tampered POST value to a known key or `None` (every server-side save path routes user input through this gate). Eight presets at launch: `aurora-blobs` (the original contact-page backdrop), `mesh-gradient`, `aurora-bands`, `starfield`, `dotted-grid`, `diagonal-lines`, `noise-paper`, `spotlight`.
- **`templates/frontend/_dynbg.html`** — render partial. Caller passes `dynbg_key` (via `with` block or render-context) and the partial emits a `<div class="fe-dynbg fe-dynbg-<key>" aria-hidden="true">` with the right inner spans / SVG nodes for that recipe. Unknown / blank keys produce no output, so consumers can include the partial unguarded.
- **CSS recipes in `static/css/frontend.css`** — every preset uses brand-design tokens (`--fe-accent`, `--fe-color-bg`, `--fe-color-surface`) so the same key produces a brand-coloured backdrop on every install. Animations honour `prefers-reduced-motion: reduce` globally. Each preset has explicit dark-mode rules (`html[data-theme="dark"]` + `body.fe-frontend-force-dark` selector pair) so the backdrop stays legible when the visitor flips the theme toggle.
- **`fe-dynbg-host` host class** — small CSS helper that gives a host element `position: relative; isolation: isolate;` plus promotes its non-dynbg children to `z-index: 1` so the dynbg paints under content. Consumers add this class alongside an `.fe-dynbg` child to host a dynamic backdrop without rewriting their existing stacking context.
- **Catalog as Jinja global** — `dynbg_catalog()` registered in `app/__init__.py::create_app` so any template can enumerate the available presets without importing Python.

#### Modal-popup admin picker (shared across every surface)

- **One global modal in `templates/base.html`** — `#dynbg-picker-modal` lives at body root on every admin page. It carries the full preset grid (rendered via the same `_dynbg.html` partial as the public site, so the thumbnails are live previews of what the visitor will see) plus Save / Clear / Cancel buttons.
- **`dynbg_trigger(field_name, current, button_id)` macro** in `templates/_dynbg_picker.html` — drop-in form control that any admin form uses to add a "Pick a dynamic background" affordance. Renders a hidden `<input>` (so a normal form POST submits the key) plus a button that opens the global modal pre-selected to the trigger's current value. Save writes back via `change` event on the hidden input + bubbles to listeners.
- **Delegated trigger handler in `static/js/app.js`** — clicks on `[data-dynbg-trigger]` are caught at the document level so triggers added later in the page lifecycle (e.g. by the block editor when an admin opens a container's edit panel) pair up automatically. One trigger is "active" at a time; the modal stashes a reference on open and consumes it on Save / Clear / Cancel.
- **Trigger button styling in `static/css/app.css`** — small thumbnail tile + display name + chevron, matches the rest of the admin's row-style controls. Hover lift + focus-visible outline.

#### Surfaces wired up

Every surface where a frontend background is definable now exposes the picker. Plumbing pattern is consistent across surfaces: column / JSON field on the model, `dynbg_trigger(...)` macro in the admin form, `fe-dynbg-host` + `_dynbg.html` include in the public render.

- **Pages (`/<slug>`)** — `Page.bg_dynamic_key` column added (auto-migrates via `_migrate_sqlite`). Saved by `frontend_page_save` (validated through `dynbg.normalize`). Picker rendered in the page-edit form's Background section. `frontend/page.html` adds `fe-dynbg-host` to the article wrapper and includes the partial when a key is set.
- **Hero (Homepage admin)** — `SiteSetting.frontend_hero_bg_dynamic_key` column. New `dynamic` mode added to `frontend_hero_bg_style` (joins the existing `frosty / solid / gradient / image / sinewave / video` set). Picker in a new "Dynamic" panel under Background → Style. Rendered in `frontend/_hero.html` when the active style is `dynamic`.
- **Container blocks (block editor)** — JS helper `dynbgTrigger(currentKey, onChange)` added to `static/js/block_editor.js` that builds a trigger button + hidden input dynamically inside the container's "Background & border" panel. `bg_dynamic_key` round-trips through `blocks_json` (Page block storage preserves arbitrary keys, no whitelist needed). Rendered by both `_blocks.html`'s `render_block` macro (for zoom-tech / shared block contexts) and `frontend/page.html`'s `pp_block` macro (for content pages) so the dynbg appears wherever containers paint.
- **Per-template customize panels (Templates admin)** — `bg_dynamic_key` stored alongside the existing per-template `bg` colour override inside `SiteSetting.frontend_template_settings_json`. Picker added to the customize panel's Background fieldset for every template kind (meeting / event / story). `tpl_dynbg_key` plumbed through every `render_template(...)` call site in `app/frontend.py`; each entity-detail partial adds `fe-dynbg-host` to its root `<section>` and includes the partial: 4 meeting templates (`classic`, `card_stack`, `magazine`, `minimal`), 4 event templates (`classic`, `poster`, `timeline`, `minimal`), 5 story templates (`anthology`, `journal`, `letter`, `magazine`, `paper`).
- **Contact page** — refactored to consume the same primitive from the start. Replaced ~50 lines of bespoke `.fe-contact-bg` / `.fe-contact-blob` CSS with `fe-dynbg-host` + `aurora-blobs` include. Proves the abstraction by deleting all the duplicated blob CSS.

### Added — Contact Us page (frontend) + Contact Form admin

A complete public `/contact` flow: visitor-facing page with a Cloudflare-Turnstile-protected form, server-side validation + email notification, and an admin inbox for the persisted submissions.

#### Public surface

- **`/contact` route in `app/frontend.py`** — gated on `SiteSetting.contact_form_enabled` (404s when off). Reuses the existing site-wide Turnstile config; no separate keys needed.
- **`/contact/submit` route** — validates required fields, runs the Turnstile check, persists a `ContactSubmission` row, and sends the message to the configured recipient. Recipient resolution falls through `contact_form_to` → `pic_email` → `access_request_to` so an install with only the dashboard PIC email set still routes mail somewhere sensible.
- **`Reply-To` header set to the visitor's email** — admins reply to the notification from their inbox and the reply goes straight to the form submitter without copy-pasting addresses. Implemented via `_send_with_reply_to()` (lightweight twin of `mail.send_mail` that supports custom Reply-To); falls back to `send_mail()` on transport error so a customised mail layer doesn't lose the email path.
- **Honeypot field** — hidden `name="website"` input. Non-empty submission silently redirects with the success flash (so bots can't tell their submission was rejected) and skips both the DB write and the email.
- **`templates/frontend/contact.html`** — two-column hero on desktop (eyebrow + heading + Markdown intro + auto-populated PIC contact channels on the left, glassy form card on the right). Single column on mobile. Reuses the `.fe-submission-form` field chrome so inputs stay visually consistent with `/submissionform`. Per-channel PIC visibility toggles let admins surface email-only / phone-only combinations without clearing the dashboard PIC fields they still want elsewhere in the portal.

#### Schema + migrations

- **`ContactSubmission` model** — `name`, `email`, `phone`, `subject`, `message`, `ip_address`, `is_read`, `is_archived`, `archived_at`, `email_sent`, `email_error`, `created_at`. Mirrors `AccessRequest`'s read/archive pattern so the admin UX feels familiar.
- **New `SiteSetting` columns** — `contact_form_enabled`, `contact_form_to`, `contact_form_heading`, `contact_form_subheading`, `contact_form_intro`, `contact_form_success_message`, `contact_form_submit_label`, `contact_form_subject_required`, `contact_form_show_phone`, plus three granular PIC visibility toggles (`contact_form_show_pic_name` / `_email` / `_phone`). All auto-migrate via `_migrate_sqlite`.
- **`/contact` added to the page-creation reserved-slug set** so an admin-authored Page can't shadow the public route.

#### Admin

- **Sidebar entry** — `Contact Form` under the Admin section (admin-only). Live unread count badge that mirrors the dashboard widget.
- **`/tspro/contact-form`** — Active / Archived tabs (matches Access Requests UX). Each row shows the message inline with mailto/tel links, email-delivery status badge, and Mark read/unread / Archive / Restore / Delete actions. Unread rows highlight with a brand-blue left edge.
- **Forms admin integration** — Contact Form registered in `app/forms_registry.py`. Settings page at `/tspro/frontend/forms/contact` (lives under Web Frontend → Forms alongside the existing Submission Form). Page heading / subheading / Markdown intro and granular PIC toggles moved to the Templates admin's Contact-us section so form mechanics (recipient, fields, success message, bot protection) and look-and-feel (page copy, PIC panel) live on their respective surfaces.

### Added — Sidebar unread badge + Contact Form dashboard widget

- **Live unread count in the global context-processor** — `unread_contact_count` computed once per request alongside `pending_access_count`. Sidebar badge in `_sidebar_nav.html` mirrors the Access Requests pattern (warn-tinted bubble with the count).
- **Dashboard widget `contact-form`** — list of up to 6 unread submissions with the `dash_show_contact_form` per-user toggle (default on). Quiet "No unread messages — inbox is clear" empty state when the inbox is empty; warn-tinted count badge in the heading when there's something to read.
- **`User.dash_show_contact_form` column** added (auto-migrates). `DASHBOARD_WIDGET_KEYS` extended to include the new key so drag-reorder honours it.

### Changed — Standardised dashboard widget chrome

- **New `templates/_dash_widget.html` macro** — single source of truth for the draggable card / `card-head` / "View all →" recipe used by every list-style dashboard widget. Caller does `{% call dash_widget(key='foo', title='Foo', view_all_url=…, badge_count=count) %} <ul class="list">…</ul> {% endcall %}` and the wrapper chrome is identical to every other widget. Optional kwargs: `view_all_label`, `badge_count` (warn-tinted nav-badge in the heading), `badge_title` (tooltip), `wide` (full-row variant).
- **Five widgets retrofitted** to use the macro: `meetings`, `libraries`, `files`, `deletions`, and the new `contact-form`. Three structurally-bespoke widgets (`server-metrics` 2-column panel, `currently-online` external partial, `access-requests` 2-block grid) deliberately stay on their own layouts; the macro doc-comment notes when to opt out.
- **Visual standardisation prevents future drift** — adding a new list-style widget now picks up the canonical chrome by construction. The contact-form widget originally invented its own bespoke `.contact-form-card` / `.contact-form-card-alert` classes; that CSS was deleted in favour of the macro so every widget reads as part of the same family at rest.

### Changed — Stories detail polish

- **Summary stripped from every detail template** — `paper`, `letter`, `journal`, `anthology`, and `magazine` no longer render `story.summary`. The summary stays scoped to list templates as the at-a-glance excerpt; detail pages now read title → byline → body without a redundant deck paragraph repeating what the body's first line already says.

#### Magazine detail — full restructure

- **Smooth hero gradient** — the previous bottom-anchored overlay panel left a visible seam where the gradient met the untouched image. Replaced it with a separate `<span class="fe-story-mag-hero-shade">` covering the *entire* hero with a multi-stop ramp (`rgba(0,0,0,0)` at 0–35% → `.15` at 55% → `.55` at 80% → `.85` at 100%). The upper image area is now genuinely transparent and the fade into dark is continuous rather than stepped.
- **Sidebar removed** — dropped `.fe-story-mag-aside` entirely. Body is a single 720px column for an editorial-magazine reading flow rather than a marketing-card layout. The author bio (when set) renders as an inline brand-blue-bordered `<aside>` near the bottom of the article.
- **"All stories" link moved into the body** — out of the hero overlay (where it sat on top of the photo) and into the top of `.fe-story-mag-room` styled in page text color. Reads as part of the article chrome, not overlaid signage.
- **Byline + published date moved into the hero** — under the title in `.fe-story-mag-hero-meta` (e.g. "By Joe S. · March 1, 2025"), with a subtle `text-shadow` so it stays legible over any featured image. The body's old meta-bar now only carries "Clean since" when present.
- **Hero image upgraded to thumb=1080** — uses the new thumbnail pipeline at the highest allowed size, so even the hero-bleed image is content-cached rather than the multi-MB original.

#### Stories list magazine

- **"Stories of recovery" eyebrow removed** from the page header — title stands on its own.
- **Hero card eyebrow** — `Now reading` → `Latest` for non-featured top stories. `Featured story` is still used when the row's `is_featured` is set.

### Added — Server-side thumbnail pipeline for story featured images

Pages that show story featured images in lists (admin stories table, public `paper-stack` / `manuscript` / `broadsheet` / `magazine` layouts) used to load the multi-MB hero original on every reload. Wired up a lazy-generation thumbnail pipeline so list views fetch fitted-into-`<size>x<size>` JPEGs / PNGs / WebPs instead.

#### `app/thumbnails.py`

- **`ensure_thumb(filename, size)`** — lazy-generates a thumbnail next to the source file in `UPLOAD_FOLDER` (filename convention: `<base>_thumb_<size>.<ext>`) and returns its path. Subsequent calls hit the cached file. Allowlisted sizes: `(120, 240, 400, 720, 1080)` so abusive query strings can't fill the disk with arbitrary sizes.
- **Pillow integration** — honors EXIF rotation via `ImageOps.exif_transpose` so portrait photos don't render sideways. Flattens RGBA / LA / palette-indexed sources onto white when re-encoding to JPEG. JPEG quality 82 progressive; WebP quality 82; PNG `compress_level=6`. SVG / GIF sources are skipped (caller falls back to the source).
- **`cleanup_for(filename)`** — deletes every cached thumb across all allowlisted sizes when a source image is retired. Wired into `_cleanup_retired_asset` in `routes.py` so replacing or deleting a featured image takes its thumbnails with it.
- **Threading** — a module-level `_LOCK` serialises generation across concurrent gunicorn workers so two requests for the same `(filename, size)` don't write the same file twice. Half-written thumb files are unlinked on exception so a poisoned cache doesn't defeat the file-existence check on the next request.
- **`Pillow==11.0.0`** added to `requirements.txt` (was previously available transitively via WeasyPrint, but pinning it explicit prevents a silent regression if a future dependency drops it).

#### Image route + template wiring

- **`/story-image/<sid>?thumb=<size>`** — the existing `public.story_featured_image` route now lazy-generates and serves a thumbnail when the query param matches the allowlist; falls back to the source for unknown sizes. Sets `Cache-Control: public, max-age=86400` since the (uuid-prefixed) source filename is content-addressed — any change to the featured image rolls the URL anyway.
- **Reference-counting** — `_cleanup_retired_asset` extended to count `Story.featured_image_filename` references too (was missing — would have eagerly deleted images still referenced by stories).
- **List templates** switched to thumb URLs:
  - admin `stories.html` row thumbs → `?thumb=120`
  - public `paper-stack.html` card images → `?thumb=400`
  - public `manuscript.html` floated thumbs → `?thumb=240`
  - public `magazine.html` hero → `?thumb=720`, grid cards → `?thumb=400`
  - public `broadsheet.html` hero → `?thumb=720`, column thumbs → `?thumb=400`
  - All also got `loading="lazy"` so off-screen images defer fetching.
- **Detail templates** keep using full-size sources — single hero per page, so the bandwidth cost is one image per visit, not N.

### Changed — Story edit also opens in the modal

- **Modal renamed** `story-new-modal` → `story-edit-modal`. One modal handles both creating and editing.
- **`openModal` extended** in `app.js` with optional `srcOverride` + `titleOverride` args (consumed from the trigger element's `data-modal-src` / `data-modal-title` attributes). The same `[data-open-modal]` handler now repoints a shared modal at per-trigger URLs, which means + New story and per-row Edit buttons all open the same iframe modal pointed at different URLs.
- **Iframe selector loosened** — `openModal` / `closeModal` previously matched `iframe[data-src]` for lazy-load, but the story modal repoints its iframe per-trigger via `data-modal-src` (no static `data-src` on the element). The selector is now `iframe` with a guard that only sets `src` when a target can be resolved (`srcOverride || data-src`); closeModal resets by id.
- **Stories list triggers** — `+ New story` / per-row `Edit` buttons / the title cell (now a `posts-title-btn` `<button>` styled as a hyperlink) all use `data-open-modal="story-edit-modal"` plus a per-row `data-modal-src` and `data-modal-title`.
- **Per-row state-change forms** — Publish / Unpublish / Archive / Restore / Delete forms inside the new-story modal pass through hidden `embed=1` inputs so the post-action redirect lands back inside the embed iframe rather than navigating the modal to the full admin chrome.
- **Routes** — `_story_embed()` / `_story_embed_kwargs()` helpers thread `embed=1` through every story state-change route. Delete from inside the modal renders a tiny `templates/story_modal_close.html` stub that auto-postMessages the parent so the modal closes cleanly even when there's no row left to redirect to.
- **postMessage type** renamed from `story-new-close` to `story-modal-close` (the parent listener still accepts the legacy type for in-flight iframes so the rename doesn't break already-loaded modals).

### Added — New-story popup modal

- **Modal in `stories.html`** — added `<div id="story-new-modal" class="modal modal-lg">` (later renamed to `story-edit-modal` once the same modal handled editing too) with an `<iframe class="settings-frame">` whose `data-src` points at `/tspro/stories/new?embed=1`. The iframe lazy-loads on first open and resets to `about:blank` on close so reopening always starts at a clean form.
- **Launch button** — `+ New story` switched from `<a href="/tspro/stories/new">` to `<button data-open-modal="story-new-modal">`. Modal panel uses `height: calc(100vh - 10vh); max-width: 1080px;` and the iframe takes `flex: 1 1 auto` so the form has room to render without the wrapper collapsing.
- **`story_edit.html` is embed-aware** — the entire `top_actions` block was moved into a content-resident `<div class="story-edit-header">` so the action buttons render in both standalone and embed modes. The header uses `position: sticky; top: 0;` so Save / Publish / Archive / Delete stay reachable while the form scrolls. In embed mode the `← All stories` link becomes a `Cancel` button with `data-story-close` that postMessages the parent.
- **Embed propagation in routes** — `story_new` / `story_edit` / `story_save` / `story_publish` / `story_unpublish` / `story_archive` / `story_unarchive` / `story_delete` all check the request's `embed=1` (URL or form body) and preserve it on every redirect. After save → redirect to the edit page in embed mode so the admin can keep iterating; after delete → render the `story_modal_close.html` stub that auto-postMessages the parent.
- **Parent-side handler in `app.js`** — new `message` listener catches the close type, closes the story modal, and reloads the underlying stories page so any saved/deleted row reflects in the list.
- **base.html embed detection widened** — was `request.args.get('embed') == '1'`, now also accepts `request.form.get('embed') == '1'` on POSTs since the dry-run commit (and now the story-save flow when it renders the next page directly) carries `embed=1` in the form body rather than the URL. Without this, post-save renders would have leaked the full admin chrome back into the iframe.

### Changed — WordPress importer is now a modal

A second pass on the importer that took it from a separate full-page wizard to a modal dialog launched from the Settings → Data tab, with a much more polished sticky-header / sticky-footer flow and a loading spinner on every long-running step. Backend logic is unchanged; this is a UX rework on top of the existing wizard.

#### Modal launch + embed mode

- **Modal in `base.html`** — added `<div id="wp-import-modal" class="modal modal-lg">` containing an `<iframe class="settings-frame" id="wp-import-frame">` whose `data-src` points at `/tspro/settings/wp-import?embed=1`. The iframe lazy-loads on first open and resets back to `about:blank` on close, so reopening always starts at step 1.
- **Launch button** — converted from `<a href="...">` to `<button data-open-modal="wp-import-modal" data-close-modal="settings-modal">`. Also added a generic `data-close-modal="<id>"` companion attribute to the existing `[data-open-modal]` click handler in `app.js` so any modal trigger can close a sibling modal first; used here to dismiss the Settings modal cleanly as the importer opens (otherwise they'd stack).
- **Modal sizing** — `#wp-import-modal .modal-panel { height: calc(100vh - 10vh); max-width: 1180px; }` and `#wp-import-frame { flex: 1 1 auto; ... }` so the iframe gets a tall canvas to render the wizard without the wrapper collapsing to its content height (the symptom that originally made the modal appear as a thin sliver).
- **`openModal` / `closeModal` extensions** in `app.js` — set iframe `src` from `data-src` on first open, blank `wp-import-frame` on close. Plus a new `postMessage` listener that catches `{type: 'wp-import-close'}` from inside the iframe and closes the modal — wired up by the Done page's primary button (`data-wp-close`) so finishing an import dismisses the modal cleanly.
- **Embed-mode propagation** — `_wp_embed_kwargs()` helper threads `embed=1` through every wizard redirect (Connect → Map → Dry-run → Done) so the chromeless render persists across the POST/302/GET dance. Each form also carries a hidden `<input type="hidden" name="embed" value="1">` and internal nav links append `embed=1` via `url_for(..., embed=1 if embed else None)`.
- **Embed detection in `base.html`** — widened from `request.args.get('embed') == '1'` to also accept `request.form.get('embed') == '1'` on POST requests, since the dry-run commit POSTs `embed=1` in the form body and renders `wp_import_done.html` directly (no redirect to a `?embed=1` URL). Without this, the Import-complete page would leak the full admin chrome (sidebar + header) back into the modal.

#### Sticky header

- **`.wp-wizard-header`** wraps the action bar (back / cancel / continue buttons) and the step indicator on every wizard step. Uses `position: sticky; top: 0; z-index: 20` with a panel background, hairline bottom border, and a soft shadow so it pins to the top of the iframe / page while the post list or preview table scrolls underneath.
- **Embed-mode bleed** — `body.embed .wp-wizard-header { margin: -20px -20px 1.25rem; padding-left: 20px; padding-right: 20px; padding-top: 20px; }` pulls the sticky header out to the iframe edges so its background covers the full top strip rather than leaving 20px gaps from `embed-content`'s padding.
- **Action bar relocation** — every wizard template's action bar moved out of the (chrome-only) `top_actions` block into a content-resident `.wp-actionbar` sitting inside the new sticky header, so the same buttons render in both standalone and embed modes.

#### Sticky footer (dry-run commit row)

- **`.wp-confirm-card`** is now `position: sticky; bottom: 0; z-index: 15` on the dry-run page, so the IMPORT confirmation field + Run-import button stay glued to the bottom of the iframe while the admin scrolls the preview table.
- **Embed-mode bleed** — `body.embed .wp-confirm-card { margin: 0 -20px; ... border-top: 4px solid var(--brand); }` pulls the sticky footer to the iframe edges, drops the side / bottom borders, and re-adds the brand accent as a top border (since the data-card's left-border accent isn't visible once the side borders go).
- **Inline confirm row** — the `<label>Type IMPORT to confirm</label>` now uses `display: flex; flex-direction: row; align-items: center; gap: .75rem;` so the prompt text sits flush left of the input on a single line. The form is a 2-column grid (input on the left, Run-import button on the right). Collapses to stacked at ≤640px.
- **Padding** — `.wp-confirm-card { padding-top: 2rem; padding-bottom: 1.1rem; }` and `.wp-confirm-card .data-card-head { margin-top: 2rem; }` give the sticky footer enough breathing room above the orange "Ready to import" header that it doesn't read as cramped.

#### Loading spinner on every long-running step

- **Shared partial** — overlay markup + JS extracted into `app/templates/_wp_fetch_overlay.html`. CSS lives in `app.css` (`.wp-fetch-overlay`, `.wp-fetch-overlay-card`, `.wp-fetch-spinner` with a `wp-fetch-spin` keyframe). Each wizard step that has a slow form includes the partial.
- **Per-mode messages** — forms opt in via `data-wp-fetch-form` and an optional `data-wp-fetch-mode` attribute; the JS picks a tailored title + message:
  - `mode="rest"` → "Connecting to WordPress…" with the parsed host inline
  - `mode="csv"` → "Parsing CSV…" with the chosen filename
  - `mode="map"` → "Compiling the import plan…" (Continue to dry run)
  - `mode="import"` → "Running the import…" with a "please don't close this window" hint
- **Submit-button locking** — disables both the submitting form's button and any external buttons that target it via `form="<id>"` (e.g. the sticky-header "Continue to dry run" button submits `wp-map-form` from outside the form), so a double-click doesn't fire two requests.

#### Skip pill colour

- **Active Skip pill is now sky-blue** (`#e0f2fe` / `#075985` light, `#0c2a45` / `#bae6fd` dark) instead of muted grey. Reads as a deliberate selection that matches the colour-coded target system instead of a disabled / muted state — distinct from the deep-blue Announcements pill.

#### Other polish

- **Plan summary tile font** — `.wp-count-num` switched from `Fraunces` (serif) to `Inter` (sans-serif) at `font-weight: 700`, `letter-spacing: -.02em`, with `font-variant-numeric: tabular-nums` so digits align across tiles. Applied on both the dry-run preview and the Done page.
- **Image status label** — chip text changed from "Would download" to "Will download" — after the IMPORT confirmation it really will, and the new wording removes the conditional ambiguity.
- **`.data-card` chrome generalised** — un-scoped from `.settings-pane[data-pane="data"]` so the same brand-blue-left-border / icon-header / lead-paragraph / actions-row pattern is reusable; the dry-run "Ready to import" card now uses it (with an orange `data-card-head` override since it's a destructive confirmation, not a routine action).
- **Activity log entry** — every commit logs `wp_import.commit` with a one-line summary of the counts (e.g. "Imported 14 stories, 3 announcement(s), 0 event(s) from rest").

### Removed — Legacy WP-CSV-to-Library importer

- Deleted the inline "WordPress posts → Library" form from the Settings → Data tab in `base.html` and its backing `data_wp_import_posts` route from `routes.py` (~130 lines of CSV parsing + attachment downloading + LibraryItem creation). The new wizard's CSV path covers the same use case via the broader Stories / Announcements / Events targets, so the dedicated Library-only path was orphaned. The `/tspro/settings/wp-import-posts` endpoint now returns 404.

### Changed — Settings → Data tab refactored into uniform cards

Every section of the Data tab now wraps in a `.data-card` (a `.card` plus a 4px brand-blue left border, Lucide icon header, lead paragraph, optional inner two-column grid, and a trailing actions row):

- **All data** (`{{ icon('database') }}`) — full-archive Import (file + REPLACE confirm + danger button) and Export (download button) side-by-side inside the card.
- **Frontend bundle** (`{{ icon('layout-grid') }}`) — frontend-scoped Import / Export side-by-side.
- **WordPress importer** (`{{ icon('globe') }}`) — copy + Launch importer button, opens the modal.
- **Database snapshots** (`{{ icon('save') }}`) — daily-snapshot list + Snapshot now button.

The two-column inner grid (`.data-card-grid` / `.data-card-col`) inherits the legacy `.data-grid`/`.data-col` shape but lives inside the card padding instead of fighting it. Removed all the old `<hr class="settings-rule">` separators since each card now stands on its own with `margin-bottom: 16px`. CSS for `.data-card*` lives in `app.css` (later un-scoped from `.settings-pane[data-pane="data"]` so the wizard could reuse it).

### Added — WordPress importer wizard

A guided multi-step importer that pulls posts out of an existing WordPress site or a CSV export and lands them in the right place — Stories, Announcements, or Events — with a dry-run preview before anything is created.

#### Backend (`app/wp_importer.py`)

- **REST fetcher** (`fetch_wp(site_url, user, app_password)`) — paginates `/wp-json/wp/v2/categories` and `/wp-json/wp/v2/posts?_embed=1` with a 500-post cap. HTTP Basic auth with WordPress **Application Passwords** is the recommended path; anonymous fetches return only public posts. Resolves featured images via `_embedded.wp:featuredmedia` and authors via `_embedded.author`. Surfaces concrete error strings (auth failure, 404, network) so the wizard can show them without a stack trace.
- **CSV parser** (`parse_csv(file_obj)`) — accepts WP All Export's column names (`Title`, `Categories`, `Content`, `Date`, `Featured Image`, `Author`, …) or raw WordPress columns (`post_title`, `post_content`, `post_category`, …). Splits multi-value categories on `|` / `;` / `,`, parses several date formats, decodes UTF-8 with BOM and Latin-1 fallback. Caps at 2000 rows.
- **Stable post shape** — both fetchers normalize to one dict: `{key, wp_id, title, slug, summary, body_html, categories, author_name, date, featured_image_url, is_draft, url}`. Body stays as the WP-rendered HTML — Stories / Announcements / Events all already pass body through the `markdown` Jinja filter, which routes HTML through bleach, so WP markup round-trips to the public site without a separate HTML-to-Markdown pass.
- **Stash store** — wizard state lives in `$TSP_DATA_DIR/wp_import/<token>.json`, where `token` is a uuid hex (validated with a strict regex on every read). `stash_purge_old()` drops files older than 24h on every wizard entry so abandoned sessions don't accumulate.
- **Plan compile + apply** — `compile_plan(posts, mapping)` walks each post, resolves the target table via the per-post mapping (with category-default fallback handled in the route), and reports per-target slug clashes. `apply_plan(actions, dry_run)` is the single code path for both the preview and the commit; `dry_run=True` returns the same `{counts, rows, warnings}` summary without touching the DB. Slug clashes auto-suffix `-2`, `-3`, … via an in-process `used_slugs` set so a single import batch can't write two rows with the same slug either.
- **Featured-image download** (`download_image_to_uploads`) — grabs the binary, sha256-hashes, and reuses the existing `MediaItem` row when the hash matches. Falls back to Content-Type when the URL has no usable extension. Failures are caught per post and reported in the result's `warnings` list rather than aborting the whole import.

#### Routes (`app/routes.py`)

- `GET /tspro/settings/wp-import` — step 1, source picker. Calls `stash_purge_old()` opportunistically.
- `POST /tspro/settings/wp-import/connect` — step 2a, REST fetch. On success persists the stash and redirects to the map page; on failure flashes the error and stays on step 1.
- `POST /tspro/settings/wp-import/upload-csv` — step 2b, CSV parse. Same redirect shape as `connect`.
- `GET/POST /tspro/settings/wp-import/<token>/map` — step 3. GET renders the map page (with a precomputed `cat_counts` dict so the template doesn't need Jinja list comprehensions). POST resolves the effective per-post mapping by combining the per-post overrides with the per-category defaults — explicit per-post value wins, otherwise the first non-skip category match wins, otherwise `skip`.
- `GET/POST /tspro/settings/wp-import/<token>/dry-run` — step 4. GET runs `apply_plan(dry_run=True)`. POST requires the literal `IMPORT` confirmation, runs `apply_plan(dry_run=False)` with the image download callback, logs to the activity feed, deletes the stash, and renders the done page.
- `POST /tspro/settings/wp-import/<token>/cancel` — wipes the stash and bounces back to step 1.

All five routes are admin-only. Breadcrumb labels added for `wp_import_start` / `_map` / `_dry_run` so the global breadcrumb resolver names them properly.

#### Wizard chrome

- **Stepper** — four-card horizontal progress indicator at the top of every wizard page: Source → Review &amp; map → Dry run → Import. Active step gets the primary-color treatment; completed steps get a green checkmark.
- **Source picker** (`wp_import_start.html`) — two side-by-side cards (`Connect to WordPress` / `Upload a CSV`) plus a four-step "How this works" explainer. Forms wired straight to the connect / upload-csv endpoints.
- **Map page** (`wp_import_map.html`) — three sections:
  1. **Map by category** — every WP category gets a row with post count + a target pillgroup (Story / Announcement / Event / Skip) styled with target-coded colors (gold / blue / green / grey).
  2. **Posts list** — one card per post: thumbnail, title with Draft chip, byline / date / "View on WP" link, summary excerpt, category chips, and a vertical pillgroup with `From category` (default, shows the resolved target as italic muted text that updates live) plus the four explicit targets.
  3. **Filter bar** — title/summary/category text search + category dropdown + count readout, plus four bulk-apply buttons (Map all visible to Story / Announcement / Event / Skip) that respect the active filter.
- **Dry run** (`wp_import_dry_run.html`) — large count cards for each target plus skipped / renamed / image-failed warning cards. Per-row table calls out renamed slugs with a chip and shows the image status (`Would download` / `—`). A collapsible `details` element groups all skipped posts. The commit form requires typing `IMPORT` (HTML5 `pattern="IMPORT"` on the input).
- **Done page** (`wp_import_done.html`) — same count chrome with the cards now linking into the destination admin pages (Stories / Posts). Per-row table with Edit links into each created row's edit screen so the admin can immediately tune anything that came across awkwardly.

#### Settings → Data

- New **WordPress importer** launcher card replaces the inline "WordPress posts → Library" form on the Data tab. Card chrome: blue-to-purple left accent bar, globe icon, two short paragraphs explaining the wizard, and a primary `Launch importer →` button. The original CSV-to-Library importer was renamed to "Quick CSV → Library" and kept below the launcher for the legacy use case (Intergroup Minutes archive).
- CSS (`app/static/css/app.css`) — `.data-wp-launch` rules add the accent bar, single-row layout (collapses to stacked at 720px), and primary CTA alignment.

### Added — Stories module

A full long-form recovery-story CMS, off by default, with its own admin section, public list + detail pages, and a catalog of paper / editorial layouts.

#### Model + module gating

- **`Story` model** (`app/models.py`) — `title`, `slug`, `summary`, `body` (Markdown), `featured_image_filename`, `author_name`, `author_bio`, `sobriety_date`, `story_date`, `is_featured`, `is_draft`, `is_archived`, plus timestamps and `created_by`. Has its own `public_slug` (explicit slug if set, else slugify(title)) and a `display_date` helper that prefers `story_date` and falls back to `created_at`.
- **`SiteSetting` columns** — `stories_enabled` (default off), `stories_required_role` (default `admin`), `frontend_stories_list_template` (default `paper-stack`), `frontend_stories_list_width_mode` / `_max_width` / `_padding_pct` / `_heading` / `_subheading`, and `frontend_story_template` (default `paper`). Both the new `story` table (via `db.create_all()`) and the SiteSetting columns (via `_migrate_sqlite`) are picked up on existing installs without a manual migration.
- **Settings → Modules toggle + role picker** — new row alongside Announcements & Events. The same `module_role_picker` macro and `_DYNAMIC_SECTION_ITEMS` map are extended so the sidebar entry's section (Main vs Admin) follows the configured required role.
- **`_require_stories_enabled()`** — the same shape as `_require_posts_enabled`: 404 when the toggle is off OR the user's role doesn't satisfy the configured requirement. Wraps every admin route.

#### Admin (`/tspro/stories`)

- **CRUD routes** — `stories` (list with active / drafts / archived tabs), `story_new`, `story_edit`, `story_save`, `story_publish`, `story_unpublish`, `story_archive`, `story_unarchive`, `story_delete`. Slug edits gated to admins + frontend editors and uniqueness-resolved via a new `_unique_story_slug` helper that mirrors `_unique_post_slug`. Slug renames append rows to `EntitySlugHistory` so the public detail route can 301 old URLs forward.
- **`stories.html`** — table view with thumbnail, title + summary, author, story date, and chip column for Draft / Archived / Featured states. Per-row actions: Edit, Publish/Move-to-Drafts, Archive/Restore, Delete.
- **`story_edit.html`** — blog-style form: Title, Public URL slug (admin-only), Summary, Markdown body (18 rows), Author byline + bio, Story date + Sobriety date (HTML5 date inputs), Featured-this-story checkbox, Featured image upload with the same clear / replace semantics as Posts. Top-of-page action bar carries Save-as-draft / Publish / Save / Move-to-Drafts / Archive / Restore / Delete depending on current state.
- **`public.story_featured_image`** route serves uploaded hero images so the public list + detail templates can render them without auth.
- **Sidebar entry** — added to `_MAIN_CATALOG` with `prefix:main.story` active-kind matching; visibility wired into `_is_visible` so it follows the same toggle + role gate as the routes.

#### Public site (`/stories`, `/stories/<slug>`)

- **`/stories`** — lists every published story (drafts + archives filtered out), featured stories first, then by `story_date` desc. Layout picked from `STORIES_LIST_TEMPLATES`; container width / heading / subheading configurable via the admin Templates page. Admin's chosen layout's built-in copy is used when the heading + subheading fields are empty.
- **`/stories/<slug>`** — single-story detail. Old slugs 301-redirect via `EntitySlugHistory`. Layout picked from `STORY_TEMPLATES`. Per-template appearance overrides flow through the existing `template_settings` / `template_css_vars` pipeline so the global Design tokens still cascade.

#### Six list-page layouts (all `frontend/stories_list/<key>.html`)

Serif-forward typography throughout; each layout ships its own scoped CSS with light + dark variants.

- **`paper-stack`** (default) — creased index-cards on a warm paper backdrop. Featured-image thumb on the left (or an ornament tile when no image is set), serif title + italic byline + summary on the right. Subtle per-card rotation, soft drop shadow, edge-fray, and a sepia-tinted image filter for an archive-of-letters feel. Featured stories get a vermilion "Featured" pin and a warmer card gradient.
- **`ledger`** — hand-bound ledger book aesthetic: cream paper sheet ruled with hairline blue lines, brown-banded spine on the left, marginalia-style date block (DD / MON / YYYY stack) per entry, roman-style entry numbers (`№ 1, № 2, …`), and double-rule masthead.
- **`manuscript`** — single column on textured cream stock inside a double-bordered sheet, drop-cap initial on each story preview (the first letter of the title, vermilion italic), italic byline, ❦ ornaments on the rules, and a small thumbnail floated right.
- **`broadsheet`** — two-column newspaper layout on aged newsprint with a halftone-style dot overlay. Big condensed serif headlines, double-rule masthead with vol / edition / date, a featured story spanning the top in a 1.5fr / 1fr grid, then a 3-column body (`column-count: 3`) with hairline column-rules. Featured images are grayscaled for that newsprint feel.
- **`minimal-serif`** — centered, generous whitespace, italic serif title, fine-print bylines, no images, no cards. Stories flow down the page like a literary index. Reads through `--tpl-bg` / `--tpl-heading-font` / `--tpl-body-font` so it inherits the global design tokens cleanly.
- **`magazine`** — modern editorial: featured story as a 1.2fr / 1fr hero card with a 16:11 cover image, then a 3-up grid of illustrated cards. Sans-serif chrome, serif headlines.

#### Five detail-page layouts (all `frontend/stories/<key>.html`)

- **`paper`** (default) — creased-paper sheet on a warm backdrop. Tipped-in featured-image plate (slightly rotated, with a caption), `— A Recovery Story —` eyebrow, italic serif title, italic deck, byline + display date + clean-since meta row, drop-cap on the first body paragraph, ❦ rule between the body and an "About the author" block.
- **`letter`** — typewriter / serif hand-typed letter on lined stock. Date in the upper-right, centered title in `Special Elite` / `Courier Prime`, "Dear reader," opener, indented body paragraphs, "Yours in fellowship," sign-off, the author's signature in `Caveat` (rotated −2deg in vermilion), and a dashed "Clean since DD MON YYYY" stamp rotated −3deg. No featured image — the focus is the writing.
- **`journal`** — ruled-paper journal page. Brown leather backdrop, two-column ruled margin (red verticals), 32px ruled body lines, big serif title, sobriety date as a hand-stamped triple-bordered seal in the upper-right (rotated 7deg), and a small Polaroid-style photo (rotated −1deg) when a featured image is set.
- **`anthology`** — literary anthology layout. Eyebrow line ("A Recovery Story · 2025"), centered italic serif title, thin rule, italic byline + meta row, single column of body copy with a drop-cap. Centered blockquotes; no featured image.
- **`magazine`** — full-bleed featured-image hero with the title overlaid in a dark gradient, then a meta-bar and a `1fr / 280px` two-column reading layout: body copy on the left, sticky `Author` card on the right with byline, Clean since / Story published facts, bio, and a "More stories →" link. Falls back to a no-hero header when there's no featured image.

#### Admin Templates page

- **Stories list picker** — same chrome as the Events / Announcements pickers. Six layout cards with thumbnails, page-heading copy override, and a container-width fieldset (boxed / full + max-width / side-padding). Saves via a new `frontend_stories_list_template_save` endpoint. Hidden when the Stories module is off so the page doesn't surface dead UI.
- **Story detail picker** — five layout cards (paper / letter / journal / anthology / magazine) with their own thumbnails, saves via `frontend_story_template_save`.
- The route still emits `STORIES_LIST_TEMPLATES` / `STORY_TEMPLATES` and the active keys to the template even when the module is off (just the markup hides), so flipping the toggle on resurfaces the picker without a refresh of the templates context.

### Added — Icon block

- **New block type `icon`** in the page builder — drag from the "Add blocks" palette like any other block. Registered in `_PAGE_LAYOUT_BLOCK_TYPES`, `_PAGE_BLOCK_CATALOG`, `_blank_page_block`, `_block_preview`, plus the JS counterparts in `block_editor.js`, `page_structure.js` BLANK_DATA, and the structure card's `_PAGE_BLOCK_LABELS` so it round-trips through layout presets, drag-drop, the orphan bin, and the structure tree like every other content block.
- **Edit modal fields** — Icon picker (opens the shared `icon-picker-modal` already used by nav-link / footer / homepage icons; full Lucide catalog + custom uploads + search), Size slider (8–256 px), Alignment toggle (Left / Center / Right), Colour picker with the standard Same / Auto / Manual dark-mode triplet, optional click-through Link URL + "Open in new tab" checkbox.
- **Live visual preview in the edit modal** — renders the actual SVG (or `<img>` for `custom:N` icons) at the chosen size + colour. Lazy-loads the Lucide catalog from `vendor/lucide/icons.json` (cached at module scope so multiple icon blocks share one fetch) and re-renders on every relevant change: picker save, size slider drag, picker modal's own size slider, colour picker save / clear / mode switch. Shows a checkered transparency backdrop so soft-coloured icons stay visible. Below the visual, a monospace meta line shows the exact stored values (`<icon-name> · <size>px · <color>`). Stale refs surface as "Unknown icon: …" so deleted custom icons don't render as a silent blank.
- **Public render** — both `_blocks.html` and `frontend/page.html` emit `<div class="block-icon block-icon--<align>">` with `font-size` + `color` + `--tsp-color-dm` inline styles. The icon's SVG inherits size from `1em` on `.icon`, so size scales correctly and the existing global dark-mode rule swaps in the dark variant under `html[data-theme="dark"]`.
- **Icon-picker modal embedded in the page-edit template** — the modal lives at the bottom of `frontend_page_edit.html` (was missing entirely) so the BlockEditor's "Pick an icon…" trigger has a target to open. Same `data-catalog-url` / `data-custom-list-url` / `data-custom-upload-url` / `data-custom-delete-url` wiring as the other 4 templates that already host their own copy.

### Added — Lucide catalog more than doubled (125 → 256 icons)

Eight new categories appended to `vendor/lucide/icons.json`, all using the same `viewBox="0 0 24 24"` + `currentColor` stroke convention as the existing set so they layer in seamlessly via `_load_catalog()` + the picker modal grid:

- **Technology (26)** — laptop, smartphone, tablet, monitor, server, cloud, cloud-upload, cloud-download, database, cpu, hard-drive, wifi, wifi-off, bluetooth, battery, battery-charging, power, plug, terminal, package, box, mouse, keyboard, printer, scan, qr-code.
- **Weather & Nature (17)** — cloud-rain, cloud-snow, cloud-lightning, cloud-sun, snowflake, umbrella, droplet, droplets, wind, thermometer, sunrise, sunset, leaf, flame, sparkles, tree-pine, mountain.
- **Travel & Transport (14)** — plane, plane-takeoff, plane-landing, train-front, car, bike, bus, ship, rocket, anchor, fuel, navigation, route, tent.
- **Food & Drink (10)** — coffee-cup, utensils, pizza, wine, beer, ice-cream, apple, cake, cookie, salad.
- **Editing & Format (17)** — bold, italic, underline, strikethrough, align-{left,center,right,justify}, list-ordered, indent, outdent, quote, scissors, rotate-cw, rotate-ccw, undo, redo.
- **Shapes & Symbols (15)** — triangle, hexagon, octagon, diamond, pentagon, asterisk, slash, percent, equal, divide, plus-circle, minus-circle, x-circle, hash, infinity.
- **Health & Activity (11)** — heart-pulse, pill, syringe, stethoscope, dna, activity, dumbbell, trophy, medal, footprints, running.
- **More UI (21)** — expand, shrink, maximize-2, minimize-2, trash-2, history, bookmark-plus, bookmark-check, lightbulb, sticker, ticket, puzzle, coins, wallet, hand-coins, calculator, calendar-clock, calendar-check, graduation-cap, school, newspaper.

The 6 "Content blocks" icons added in the prior pass (`heading`, `type`, `list`, `code`, `mouse-pointer-click`, `panel-left`) are also new — they were referenced by block-catalog entries but missing from the catalog, so the corresponding block tiles previously rendered blank.

### Added — New-page modal flow

- **"New page" button on `/frontend/pages` opens a modal in place** instead of navigating to a blank edit screen. Modal asks for the page title (required) + a starting layout (Custom by default, or any seeded preset / saved custom layout — same card grid the edit-screen layout picker uses). Submitting POSTs to a new `frontend_page_create` route which mints the row, stamps the chosen layout's blocks (or starts blank for Custom), generates a slug with the same RESERVED-set + uniqueness loop the save route uses, and redirects into `/frontend/pages/<id>/edit`. The active layout structure card is fully populated by the time the admin lands on the edit screen — no more "save first, then choose a layout" two-step flow.
- **Legacy `/frontend/pages/new` URL bounces back** to `/frontend/pages` so any old bookmark hits the modal flow.
- **`frontend_pages` route now passes `page_layouts`** to the template so the modal can render the layout-card grid.

### Fixed — New-page save 500 (`NOT NULL constraint failed: page.slug`)

- `frontend_page_save` was assigning `page.title` and `page.slug` AFTER its slug-uniqueness query, but `Page.query.filter(...)` triggers an SQLAlchemy autoflush BEFORE running. With a brand-new `Page()` already added to the session (via `db.session.add(page)`), the autoflush attempted to insert a row with NULL `slug` + NULL `title` and crashed on the NOT NULL constraint. Fix: assign `page.title` / `page.template` / `page.is_published` / `page.blocks_json` up front, then run the slug-uniqueness probe inside `db.session.no_autoflush:` (defense-in-depth so a future field addition can't re-introduce the race), assign `page.slug`, THEN add to the session. New pages now save cleanly on first submit.

### Added — Active layout structure card on new pages

- Removed the `{% if page %}` gate around the active-layout structure card, orphans card, and block palette in `frontend_page_edit.html` so they render on `/frontend/pages/new` too. Was originally moot because the New-page flow now uses a modal (above), but the change still benefits any admin reaching the legacy edit screen with an unsaved page.

### Added — Content Pages

A full content-page CMS, accessible via **Web Frontend → Pages** in the admin and served at `/<slug>` on the public frontend.

#### Page admin

- **`Page` model** (`app/models.py`) — `slug`, `title`, `blocks_json`, `template` (standard / wiki), `is_published`, plus the per-page settings listed below. Boot-time additive migrations cover existing installs.
- **CRUD admin** — list view, new-page form, edit form, delete with confirm. Slug auto-derives from title and is guarded against collisions with reserved frontend routes (`/meetings`, `/events`, `/library`, etc.).
- **Public render route** — catch-all `frontend.page_detail(slug)` resolves a published page and emits the showcase layout (or wiki layout with a TOC sidebar) via the shared `_blocks.html` macros.

#### Showcase rendering on `/<slug>`

- Two-column hero (image + title left, lead-paragraph card right) when the first section starts with an image; centered single-column hero otherwise.
- A new `regex_search` Jinja filter detects single-link paragraphs (`[text](url)`) and auto-promotes them to tokenized `.fe-btn-primary` CTA buttons — admins author CTAs as plain markdown.
- Unordered lists render as numbered step cards (`.fe-pp-steps`) with hover lift + accent-tinted border.
- Hero card is a flex column with a uniform `1rem` gap so lead → CTA → supporting copy reads at a consistent rhythm.

#### Per-page background

- Upload (PNG, JPG, WEBP, GIF, **SVG**) → served via `/pub/page-bg/<page_id>` (cache-busted by `updated_at`).
- **Cover** mode (full-bleed) and **Tile** mode with a 25-400 % scale slider — same 120 px base used in the live render and the admin live-preview pane so they read 1:1.
- Live preview with a checkered backdrop for transparent SVGs.
- Dark-mode dim — `.fe-pp-has-bg::after` paints a `rgba(0,0,0,0.55)` veil over cover backgrounds (`0.45` for tile) so admin-uploaded photos / patterns don't blow out the dark theme.

#### Per-page hero typography

- Main heading + sub-headings each take a color (color picker **with editable hex text input**, two-way bound, blank = inherit theme), alignment (Auto / Left / Center / Right), and font (any vendored or admin-uploaded `CustomFont`).
- Hex inputs accept `#rgb`, `#rrggbb`, or unprefixed forms — three-digit shorthand auto-expands; invalid input flags red without clobbering the saved value; blur snaps back so the field never lies.

#### Layout picker (homepage / footer pattern)

- Five seeded `kind='page'` layout presets — Blank, Article, Marketing landing, FAQ, Two-column showcase. Selecting a preset copies fresh blank content blocks of the preset's types into `page.blocks_json`.
- "Custom layout" tile opens the same drag-and-drop builder the homepage and footer use; reuses `frontend_custom_layout_save / update / delete`.
- **Active layout structure card** — pills for every block in the page's content, each opening the **Edit layout** modal scrolled to the matching block (block IDs propagated through `data-page-block-id`; clicked block flashes with a soft yellow halo via `.be-block-flash`).
- Page settings, Background, and Hero typography sit in their own cards below the structure card.

### Added — Block Editor

- **Button block** (`type: 'button'`) — first-class CTA with label, URL, "Open in new tab", alignment toggle, and a Style toggle (**Primary / Secondary / Custom**). Custom mode reveals a panel with bg / hover bg / text / hover text / border / hover border / shadow color pickers; partial configurations fall back to the theme's `.fe-btn` token recipe.
- **Container block** (`type: 'container'`) — recursive layout primitive holding nested children. Settings (collapsible `<details>` panels):
  - **Layout** — Display (Flex / Grid), Direction, Wrap, Grid columns (`grid-template-columns` syntax), Justify, Align, Gap.
  - **Spacing & width** — Padding (CSS shorthand), Width (Boxed / Full), Max width.
  - **Background & border** — Background color, Border width / style / color, Rounded corners, Box shadow preset (None / Subtle / Medium / Large / Dramatic).
  - **Hover** — Background, Border color, Shadow override, Hover lift. Each is opt-in via per-property classes (`block-container--hover-bg`, `--hover-border`, `--hover-shadow`, `--hover-lift`) so untouched hover values don't revert resting styles.
- **Recursive editor** — refactored `renderBlocksList(blocks, parentId)` shared between sections and containers; cross-parent drags resolved via `data-blocks-parent` IDs and a `findBlocksById` walker. Sortable groups blocks across the whole tree.

### Changed

- Block-editor toggles (button-block style/align, container width-mode, page heading-align, page bg-mode) now carry the existing `view-toggle` class so the active pill picks up the accent-filled visual feedback.
- Style / align / color-clear actions dispatch a bubbling synthetic `input` event from a relevant element so the sticky `#fe-save-bar` dirty-tracker (which listens for native `input`/`change` on the form) flips to "Unsaved changes" on click-only state mutations.
- Sticky save bar's `new FormData(form)` path now picks up the editor's serialized JSON via a `formdata` event listener — companion to the existing `submit` listener that handled the in-form Save button.

### Fixed

- **Color pickers were unclickable** on initial load — split into a hidden `name=` input (form payload) and a separate visual swatch + editable hex text input that stay clickable always; the visible inputs are never disabled.
- **Saving with the bg upload wiped page content** — the route only updates `blocks_json` when the form carries a non-empty, valid value; mount/serialize failures leave the existing column untouched and surface a `console.warn` so the path stays diagnosable.
- **Style / align toggles in button blocks weren't pressing** — class-toggling worked, but `.btn.active` only had visual styling inside `.view-toggle`. Toggle divs now carry that class and use event delegation for resilience after re-renders.
- **Hex var() fallbacks were invalid** — container hover styling now gates on per-property classes instead of empty `var(…, )` fallbacks, so unset hover values don't revert the resting style to `initial`.

### Internal

- New Jinja globals — `font_stack(key)` (resolves a font key to its full CSS family stack), `regex_search` filter (used by the showcase rendering's link-only-paragraph detection).
- Public `/pub/page-bg/<page_id>` route serves page backgrounds; `Page.is_published` gates access.
- Admin block-editor styles (`.be-button-*`, `.be-container-*`, `.page-bg-*`, `.page-typo-*`) live in `app.css`; public-facing showcase + container styles in `frontend.css`.

### Changed — Page admin polish

- **Pages list view** (`/tspro/frontend/pages`) — switched the `<table>` from the unstyled `data-table` class to the project's standard `.tbl` (sets `width: 100%`, gives every cell `12px 8px` padding with bottom borders, styles headers as small uppercase muted labels). Status pills now use `post-chip post-chip-online` (Published, teal) and `post-chip post-chip-draft` (Draft, slate) — the previous `pill` / `pill-success` classes had no CSS anywhere in the project, so everything was crammed flush-left as plain text. Layout column wrapped in `<span class="chip">`; URL slug + Updated cells get `nowrap`; date picks up `muted`. Removed the redundant inline `style="display:inline"` on the delete form (`.row-actions form` already handles it).
- **Page edit screen — title banner** above the first card so the admin always sees which page they're editing (eyebrow "Editing page" + title + slug code chip + Draft chip when unpublished). Eight backend tokens (`--panel`, `--text`, `--border`, `--muted`, `--panel-2`) so it adapts to dark mode automatically.
- **Hero typography card removed** — per-block typography lives on the heading / paragraph / container blocks themselves now; the redundant page-level color / alignment / font controls are gone, along with their JS handlers and CSS. The save route was also tightened to only touch `heading_color` / `subheading_color` / `heading_font` / `subheading_font` / `heading_align` columns when those fields are explicitly posted, so legacy values on existing pages survive a save round-trip from the slimmed-down form.
- **Active-layout structure card — graphical tree** (`structure_page_tree` macro in `_frontend_structure_card.html`) replaces the flat row of pills. A 2-column container in `page.blocks_json` renders as a real 2-column row with the per-column pills inside the right cell; a single-column container renders as a labeled "Container · single column" row with its child pills stacked; section titles render as soft uppercase dividers. Driven by `_page_active_tree(page)` in `routes.py`, which walks `blocks_json` and builds a `[{type:'columns'|'block'|'section_label', …}]` shape; `_container_columns` parses `grid-template-columns: repeat(N, …)` / whitespace-separated tracks and inlines one level of nested-container children so a 2-col outer container with two inner containers shows the inner blocks per column instead of opaque "Container" pills.
- **"Edit layout" button at top-right of the structure card** now opens the layout PICKER (the prebuilt grid + Custom-layout tile) instead of the drag-drop builder. The structure-card macro grew an optional `picker_modal_id` arg; when supplied, the button uses `data-open-modal` (the standard modal handler) instead of the `data-edit-layout` shortcut. Also added a dataset fallback in the layout-builder JS handler (`feLayoutBuilder` in `app.js`) so the standalone-button path works when no `.template-card` ancestor is present — matches the fallback the footer's handler already had.
- **Per-block focus modal** — clicking any pill in the structure card opens the BlockEditor modal in **focus mode**: only the clicked block (and its container ancestry) is visible, with a "← View all blocks" button in the modal head to escape back to the full layout editor. The bottom redundant "Edit layout" button is gone — pills cover the per-block path, the top-right button covers the layout-switching path. CSS-driven via `.fe-page-edit-modal.is-focus-mode` which hides every `.be-block` not on the focused-path; path containers drop their head + settings panels so the focused descendant is the only thing the admin sees.

### Changed — Layout system

- **Layout-apply is non-destructive AND idempotent.** `frontend_page_layout_save` now stamps each top-level layout entry as its OWN untitled section in the page (so a layout `[split, container]` produces two sections — a 2-column hero + a single-column block area). Existing UNTITLED (structural) sections at the top of the page are stripped and replaced with the fresh shell — re-clicking "Use this layout" yields the same shape, no more duplicating 2-column rows. TITLED sections (admin's content like "Chat Conduct Policy") are always preserved, ordered after the shell. Convention: untitled = layout/structural, titled = user content.
- **`split` block is a universal layout primitive** — added to `_PAGE_BLOCK_CATALOG` so the same Two-panel-row block the homepage offers is now in the page admin's layout-builder palette. When applied to a page, `split` expands into a real 2-column `container` (`display: grid`, `grid_columns: "1fr 1fr"`) holding two child containers, one per panel. New `_instantiate_preset_entry(entry)` helper in `routes.py` handles the expansion + recurses into `container` children so a layout authored with a Container holding e.g. a Heading + Paragraph stamps that exact tree onto the page.
- **Container is a real drop-zone in the layout builder** — drag any other block into it; the chrome shape mirrors split (head + drop-zone), one full-width drop area instead of two side-by-side panels. Serializer + hydrator round-trip the nested `blocks` array. `_normalize_blocks(allowed_types)` recurses into `container.blocks` with the same whitelist as the parent. Splits are blocked from being placed inside a container's drop-zone (keeps the tree shallow); container-inside-container is allowed.
- **Two-column showcase preset rebuilt** — was a flat `[image, paragraph, button, paragraph]` that relied on the (now-deleted) `pp_hero_split` renderer auto-magic to look like 2 columns. Now `[split{left:[image], right:[heading, paragraph, button]}, container{blocks:[heading, paragraph, list]}]` so it stamps a real 2-column hero + a single-column area underneath ready for a guidelines / cards / policy block.
- **Custom layout save accepts `kind=page`.** `frontend_custom_layout_save` and `_update` were rejecting page-kind layouts with "Unknown layout kind: page" because they only knew `homepage` / `footer`. Added a `page` branch + `_PAGE_LAYOUT_BLOCK_TYPES` whitelist; parameterised `_normalize_blocks(allowed_types=...)` so the same shape-recursing function serves all three.

### Changed — Public page renderer (`frontend/page.html`)

- **No more auto-injected page title.** Removed every site that auto-rendered `page.title` into the public page: the `pp_hero_split` macro (deleted), the wiki-mode header `<h1>` (deleted), the empty-page fallback `<h1>` (deleted). Page now renders ONLY the blocks the admin placed in the layout — every visible element traces back to a block in `blocks_json`. The page title remains in the `<title>` browser tab and the admin's edit screen.
- **No more auto-split-into-hero magic.** The `pp_hero_split` macro used to detect an image in the first untitled section and rewrite the section into a fake 2-column hero with auto-promoted lead paragraph + auto-injected `<h1>`. With the new layout system using explicit `container` blocks for columns, that auto-magic is redundant and confusing — the structure card couldn't see through it. Stripped along with the `_link_only_re` CTA-detection regex (paragraphs whose entire content was a single markdown link no longer auto-promote to primary buttons; admins use a Button block).
- **No more auto-numbered-step-card promotion.** Unordered list blocks used to render as a numbered `<ol class="fe-pp-steps">` with hover lift + accent-tinted border. Now they fall through to the standard `_blocks.html` renderer which honours `d.ordered` — `<ul>` for unordered, `<ol>` for ordered.
- `pp_section` is now a straightforward "render section title (if set) + blocks in order"; the `pp_block(b, is_lead=False)` parameter is gone.

### Fixed — Dark mode

- **15 sites in `app.css` referenced undefined CSS variables** (`var(--surface, #fff)`, `var(--surface-alt, #f8fafc)`, `var(--surface-2, #f8fafc)`, `var(--ink, #0f172a)`, `var(--ink-muted, #64748b)`) with hardcoded light-mode hex fallbacks — `--surface*` and `--ink*` are not defined in any theme, so the fallbacks always rendered, leaving the BlockEditor / focus modal / page-bg preview / button colour pickers / container colour pickers / meeting-list filters / location lines / etc. with light backgrounds + dark text under the dark theme. Replaced every instance with the real theme tokens (`--panel`, `--panel-2`, `--text`, `--muted`).
- **BlockEditor visual hierarchy reworked** so blocks read as elevated cards in both light + dark mode: `.be-section` uses `--panel-2` (slightly tinted from modal panel), `.be-block` uses `--panel` (clean elevated card), `.be-block-head` uses `--panel-2` (sub-zone tint). Inputs / textareas / selects in `.be-body` now explicitly set `--panel` background + `--text` color + `--border` border + 6px radius + 6/10px padding so they stop rendering with browser-default white-on-white in dark mode. `.be-section-title` becomes a proper inset input with the same chrome.
- **`is-invalid` colour states** (container colour text, button colour val) use `var(--danger)` with `color-mix(in srgb, var(--danger) 12%, transparent)` for the tint, instead of hardcoded `#ef4444` / `rgba(239, 68, 68, 0.08)` / `#b91c1c`.

### Added — Tooling

- `scripts/restore_chat_page.py` — one-shot recovery for the seeded `/chat` page if a destructive layout-apply (or any other event) wiped its content. Rebuilds `page.blocks_json` to match the showcase layout's stamped shape with the original WhatsApp content filled in: section 1 (untitled, 2-column hero) gets the WhatsApp logos image + intro paragraph + "Join us on WhatsApp" CTA + community-chats follow-up; section 2 (untitled, single-column container) gets the Chat Conduct Policy heading + intro + bulleted guidelines + closing paragraph with the privacy link. Mirrors `_blank_page_block("container")["data"]` so re-applying the showcase layout in the admin is a no-op for the structural shape. Idempotent. Run from the host: `python3 scripts/restore_chat_page.py`.

### Added — Page width formatting

- **Boxed / Full-width toggle on every page**, with a slider for max-width when boxed (640–1600 px) and a side-padding % when full-width (0–20% viewport gutter). Three new `Page` columns (`width_mode`, `max_width`, `full_padding_pct`) with matching `_migrate_sqlite` entries. The form lives in a new "Page width" card directly beneath Page settings; sliders show their live value via `<output>`; the inactive control's label hides when toggling so the panel stays focused. Public renderer applies the selected mode as inline style on `.fe-pp-shell` (max-width or padding-left/right vw). The hardcoded `max-width: 760px` on `.fe-pp-shell` was also removed — it was overriding the new inline style.

### Changed — Wiki mode is now a layout, not a page setting

- **Standard / Wiki layout-style toggle removed** from the page edit form. Every page is `template = 'standard'` — the column is kept for back-compat but the save route always writes that value. Public renderer's wiki branch deleted; `frontend/page.html` has a single render path now.
- **`toc_sidebar` block** — new universal block type that renders a sticky on-page table of contents, built at request time from every Heading block on the page (`_collect_page_headings` walks containers too). Settings on the block: title (default "On this page"), max heading level to include (h2..h6), sticky toggle, sticky top-offset px. Heading blocks now stamp `id="<slug>"` so the TOC links work; duplicate heading text gets `-2`/`-3` suffixes. Hides on viewports under 880 px to avoid sticky-on-mobile UX.
- **Wiki layout preset** (`page-wiki`) — seeded prebuilt: a `split` with two heading+paragraph pairs on the left and a `toc_sidebar` on the right. The legacy wiki-template path renders identically by selecting this preset.

### Added — Per-block typography

- **Shared typography panel** in the BlockEditor exposing Font family, Font size, Weight (Theme default / 400 / 500 / 600 / 700 / 800), Colour (swatch + hex + clear), Alignment (Auto / Left / Center / Right / Justify), Line height. Wired into Heading, Paragraph, and List blocks. Each setting saves to the block's `data` and renders as inline `style` on the public element — empty values short-circuit so unedited blocks stay clean HTML.
- **Heading levels expanded to H2..H6** (was H2..H5).
- **List block — Marker style** dropdown (Theme default / Disc / Circle / Square / Numbered 1. / Lower-alpha a. / Upper-roman I.) — applied as `list-style-type`. Plus the shared typography panel.
- **Image block — Width slider** (20%–100%), Alignment toggle (Left / Center / Right), Caption colour, Caption size. Caption styling applies as inline style on the `<figcaption>`.
- **Font dropdown options** are populated from `window.tspFonts`, injected by the page-edit template at boot from `frontend_fonts()` + `font_stack(key)` — new admin-uploaded `CustomFont` rows show up automatically.

### Added — Drag-drop composition in the main view

- **Block palette** (`structure_block_palette` macro) sits below the active layout structure card. Each tile (Two-panel, Container, Heading, Text, Image, Button, List, Callout, Video, Code, Divider, Wiki sidebar) is HTML5-draggable. Drop into any structure-card zone → mints a fresh block from the catalog's blank defaults with a new `id` and inserts it. The Two-panel tile expands into a 2-column grid container with two empty inner containers (matches the showcase preset's stamping logic).
- **Sortable.js zones throughout the structure card** — every column cell, single-block row, and the orphan bin is a drop target (single shared group `be-zone`). Drag any pill within a zone to reorder, between zones to move (column → orphan, orphan → column, column-A → column-B, etc.). On every drop, JS walks the DOM and reconstructs `sections[]` from each pill's `data-block-payload`, respecting which zone it landed in (round-tripping inner-container `data.blocks` per column for the showcase pattern). The new JSON writes to `#page-blocks-json` and dispatches an `input` event so the sticky save bar lights up.
- **Top-level drag-drop** — the rows container (`.fe-page-structure-rows`) is itself a drop target (`data-be-zone="root"`). Dropping a Container or Two-panel palette tile at the top level mints a new row at the cursor position; dropping a leaf-type tile creates a `row-single` section. Drop position is computed from `event.clientY` against existing rows so the new row lands above whichever row's midpoint is below the cursor (or appended if past the last row). An empty-state placeholder ("Drop a Container or Two-panel here…") appears when the active layout has no rows.
- **Row reorder** — separate Sortable instance on the root zone (group `be-rows`, `pull: false`, `put: false`) so pill drags never trigger row drags and vice versa. Drag handles: `.fe-page-structure-row-label` (multi-column rows) and a new `.fe-page-row-handle` grip (row-single rows). On drop, `syncStateFromDom` rebuilds `sections[]` in the new row order.
- **Hover preview popover** on every pill (active layout + orphan bin). Server-side `_block_preview(b)` produces a typed payload (`{kind: 'text'|'image'|'list'|'code', label, text, src, subtext}`) stamped onto each pill as `data-preview`. Floating fixed-position card renders text excerpts, image thumbnails, item counts, button label/URL — auto-positioned, viewport-clamped, auto-hides on mouseout/focusout.
- **Always-expanded settings panels** in BlockEditor — every `<details>` (Layout / Spacing & width / Background & border / Hover / Typography) opens by default so settings are visible without an extra click.
- **Container/2-col Settings buttons** in each row's label gutter — opens BlockEditor focused on that container so flex/grid/spacing/visual/hover panels are reachable in one click.

### Added — Orphan bin

- **Layout switch is now non-destructive of edited content**. When applying a new layout, blocks displaced from the previous layout's untitled (structural) sections aren't wiped — they're swept into a special `_orphans=true` section and surfaced in the editor as a separate "Unplaced blocks" card. The admin drags them back into the new layout's columns or rows when ready. `_block_has_content` filters out empty placeholders so the bin doesn't collect noise. Existing orphan-bin contents survive across multiple layout switches (orphans of orphans). Orphan sections never render publicly.

### Added — Remove buttons (with auto-orphan)

- **× delete on every pill** (subtle by default, fades in on pill hover/focus, turns red on its own hover). Click → `confirm("Remove this block?")` → DOM removal → `syncStateFromDom`. The pill markup changed from `<button>` to `<div>` so the × can be a real nested `<button>` (avoids invalid HTML), and a delegated click handler keeps the click-to-edit/modal-open path working for both server-rendered and dynamically-added pills.
- **Remove on container / 2-col rows** — sits in the row-label gutter alongside Settings. If the row holds child blocks, the confirmation message shows the count and the children move to the orphan bin (preserving full payloads, no data loss); if empty, simple confirm + remove. Row-single rows get a square × icon-button on the right.
- **Click forwarding** — page-edit IIFE exposes `window.focusPageBlock` + `window.remountPageBlockEditor`; `page_structure.js` calls them after every structural mutation so the modal-based BlockEditor always mounts against the latest tree on next open. Server-rendered pills stamp `data-pill-bound="1"` once their per-element handler is attached so the delegated fallback in `page_structure.js` doesn't double-fire.

### Internal — Structure tree wiring

- **`structure_page_tree` macro** consumes `_page_active_tree(page)` which now returns `{tree, orphans}`. `tree` entries: `{type:'block'|'columns'|'section_label', …}`. `orphans` entries: flat `{t, block_id}` pills. `_container_columns` parses `grid-template-columns: repeat(N, …)` / whitespace-separated tracks AND inlines one level of nested-container children so the visualisation matches the public render.
- **`structure_orphans_card` macro** renders the orphan bin (hidden when empty via `.is-empty`); JS toggles it as orphans come and go.
- **`structure_block_palette` macro** renders the always-on draggable source.
- Each pill carries `data-block-payload` (full JSON of the block) — `syncStateFromDom` walks the DOM and reconstructs `sections[]` purely from the pill payloads + zone context attributes (`data-be-zone`, `data-be-parent-block-id`, `data-be-col-index`, `data-be-row-block-id`).

### Changed — Layout picker polish

- **"Edit layout" button → "Change layout"** on the structure card — matches what it actually does (open the layout picker to switch layouts).
- **Custom layout is now a regular radio option** in the picker grid (top of the layout list), not a separate tile that opens the drag-drop builder modal. Selecting it submits with `layout_key=custom` → existing route records the choice without stamping → user is back on the edit page where the structure card's drag-drop + block palette let them build the layout in place. The drag-drop builder is still reachable via a smaller secondary "Build a reusable layout template…" button below the picker grid; helper text clarifies it's for designing saved templates that any page can pick from this list.
- **`(Customized)` badge on the structure card heading** — when the page's structural shape has been edited away from what the active prebuilt layout would stamp (added / removed / rearranged blocks, or anything in the orphan bin), the heading reads "Active layout — Two-column showcase (Customized)". `_page_is_customized(page, active_layout)` builds a structural-shape signature from both the page and a fresh stamp of the layout (ignoring user-content fields like text / md / src / items / IDs) and compares. Customized = structural-only changes; pure content edits don't trigger the badge.
- **Prebuilt layout templates can ship styling overrides** — `_instantiate_preset_entry` extended to merge a `data` dict from each entry on top of the type's blank defaults (containers, splits, leaves all supported). Splits also accept `data_left` / `data_right` for per-panel styling so a layout can independently style each column. Updated showcase + wiki seeds to ship structural choices (gap, grid_columns) as overrides; the user inherits these at apply time and can edit them via the block's settings panel.

### Added — Image block media browser

- **Browse library / Upload new buttons** next to the Image source URL input. Browse opens a dedicated picker modal showing a thumbnail grid of every image in the MediaItem catalog (PNG / JPG / WEBP / GIF / SVG / AVIF / BMP). Auto-loads from new `/tspro/files/images.json` endpoint (paginated 200 max, optional `?q=` substring filter against original filename). Click a tile → sets the block's `data.src` to `/pub/<filename>`, closes modal, live preview updates. Search field in the modal head filters client-side as the admin types.
- **Drop-zone uploader** at the top of the picker modal — accepts file-picker click OR drag-and-drop (multiple files supported). Streams to existing `/tspro/files/upload` endpoint with the page's CSRF token; on success the grid auto-refreshes. If the picker was opened with a pending pick callback (admin clicked Browse to choose), the FIRST uploaded file gets auto-selected and modal closes — zero extra clicks for the "I'm uploading something fresh" path.
- **Upload new** on the block bypasses the grid: pops the OS file picker, uploads, immediately sets `data.src` to the new file's URL.
- Modal lazy-creates on first open. Lives at `<body>` level so it stacks above the per-block focus modal.

### Fixed — Save bar reliability + edit-modal rendering

- **Newly-dragged blocks vanished on save.** The form's submit + formdata handlers were unconditionally writing to the hidden `blocks_json` input from BlockEditor's serialised state. When the modal-based BlockEditor was never mounted (admin only edited via the structure card's drag-drop), `serialise()` returned null and the handlers wiped the hidden input — silently discarding everything `syncStateFromDom` had written there. Made both handlers no-op when the editor isn't mounted, since the structure card already keeps the hidden input authoritative on every drop.
- **Edit modal had no controls for newly-dragged blocks.** The delegated click handler in `page_structure.js` opened the modal and called `focusPageBlock` but never called `ensureEditor()` to mount the BlockEditor — so the modal body was an empty div. Exposed `window.ensurePageBlockEditor = ensureEditor` from the page-edit IIFE; the delegated handler now calls it before focusing. Two `requestAnimationFrame` ticks (matching the per-element handler): first to mount, second to scroll-and-focus.
- **Save bar didn't appear for drag-drop changes.** `syncStateFromDom` now dispatches `input` THREE ways for reliability: on the hidden input (canonical bubbling path), on the form directly (guarantees the form's listener fires even when bubbling is interrupted), and as a defensive last resort directly toggles `#fe-save-bar.hidden = false` if it's still hidden a tick after the events fire.
- **Save bar didn't appear for changes inside a block's edit modal.** BlockEditor's `notifyChange()` fires `input` on `#page-editor-root`, but that root sits inside the focused-edit modal which is rendered OUTSIDE the page-edit form — so the bubble never reached the form-level listener. Added a capture-phase `input` listener on the modal element that re-dispatches an `input` event onto the page-edit form (which the save-bar IIFE picks up + adds the form to its `dirty` set).
- **"Settings" button on container rows opened a blank modal.** The Settings button carries `data-page-block-id` (it's the entry point for editing the container), but the click handler's overly-broad guard `if (e.target.closest('button')) return;` matched the button itself and bailed before mounting the editor. Tightened the guard to skip ONLY when the click landed on an inner remove button (`[data-be-remove-block]` / `[data-be-remove-row]`). Settings buttons now fall through to `ensureEditor()` + `focusBlock(id)`.
- **Heading block had no visible text input.** Recent dark-mode CSS added `width: 100%` to all inputs/selects inside `.be-body`. Inside the heading's `.be-row` flex container, the level select also got `width: 100%`, squeezing the text input. Restructured the heading editor to two separate labeled rows ("Level" + "Heading text") instead of cramming both into one `.be-row`. Also patched the underlying CSS so any future side-by-side layouts behave: `.be-body .be-row > select { width: auto; flex: 0 0 auto; }` and `.be-body .be-row > input[type=text] { flex: 1 1 0; min-width: 0; }`.

### Changed — No invisible chrome (page styling traces to block data)

- **Container + image defaults are now fully unstyled.** `_blank_page_block("container")` ships with `padding: "0", gap: "0", width_mode: "full", max_width: 0` (was `1rem`/`1rem`/`boxed`/`1160`). A freshly-dropped Container behaves like a plain `<div>` until the admin styles it. Same in JS BlockEditor + `page_structure.js` BLANK_DATA. Image defaults: `align: ""` (was `'center'`) — figure inherits its container's text-align rather than auto-centering.
- **Stripped CSS-imposed chrome on the public page renderer:**
  - `.fe-pp-figure img { border-radius: 18px; box-shadow: var(--fe-shadow-lg, ...); }` — every image got 18 px rounded corners + drop shadow regardless of block settings.
  - `.fe-pp-figure { margin: 36px 0 32px; text-align: center; }` — every figure got vertical margin + center alignment baked in.
  - `.fe-pp-section { margin-top: 64px; padding-top: 56px; border-top: 1px solid var(--fe-border); }` — top hairline + padding chrome between sections.
  - `.fe-pp-section .fe-pp-prose { max-width: 640px; margin-inline: auto; } p { text-align: center; }` — every paragraph in a section auto-centered + clamped to 640 px.
  - `.fe-pp-section-title { text-align: center; }` — section titles auto-centered.
  - `.fe-pp-figure figcaption { color: var(--fe-ink-soft); font-size: 0.9375rem; }` — caption auto-styled with muted colour + smaller font.
  - `.fe-pp-has-bg .fe-pp-section { background: var(--fe-color-surface); border: 1px solid var(--fe-border); border-radius: 22px; padding: 40px 44px; }` (light + dark variants + mobile media queries) — pages with a bg image auto-wrapped every section in a white card with border, radius, padding, and a 50px box-shadow on dark.
  - All matching dark-mode + media-query overrides removed too.
- **`pp_container_styles` `max-width: 0px` guard** — added `_mw > 0` check so a freshly-flipped container in boxed mode without `max_width` set doesn't render with `max-width: 0px` and collapse.
- Mirrored to `_blocks.html` so the shared block renderer applies the same minimal defaults.
- **Memory rule saved**: `feedback_no_invisible_chrome.md` indexed in `MEMORY.md` — every visible style on a frontend page must trace back to either a Page setting or an explicit block setting; CSS in `frontend.css` cannot auto-apply backgrounds, borders, shadows, border-radius, text-align, auto-margins, or padding chrome the admin can't see in any edit modal. Reading-comfort defaults (font-size, line-height, theme colour) are explicitly carved out as typography rather than visual chrome.

### Added — Recursive nested-container rendering

- **For two-column blocks: containers can be nested inside each column.** Refactored the structure tree to be fully recursive — every container at any depth becomes a `'columns'` node with its own `block_id`, drop zones, and Settings + Remove buttons. Cells contain other tree nodes recursively. A 2-col container holding two inner containers (each with their own children) renders as `columns(outer)` → 2 cells → each cell holds `columns(inner)` → that cell's content. Goes as deep as the data nests.
- **Macro recursion** — `structure_page_tree` split into a self-referencing `render_tree_node` macro called from cell contents, so server-rendered output mirrors the block tree exactly.
- **Client-side recursion** — `reconstructBlocksFromZone(zone)` walks a cell's direct children: pills become block payloads, nested `.fe-page-structure-row--split` rows become container payloads (rebuilt via `rebuildContainerFromRow`). New `makeNodeFromPayload(payload)` returns either a pill (leaf) or a row (container) so cell hydration recurses too. `bindZones()` runs after every drop so newly-added nested zones become Sortable + drop targets immediately.
- **Drop handler nesting** — when a Container or Two-panel is dropped INTO a column cell (`data-be-zone="container-col"`), the new element is a row (not a flat pill) inserted at the cursor's vertical position, matching what the server would render on next page load. Visual state stays consistent without re-render.
- **`makeRowSplit` two-pattern hydration:** showcase pattern (all direct children are containers, count matches `nCols`) maps each cell to one inner container; flat pattern distributes children round-robin. Single-column containers no longer auto-provision an inner-container wrapper — they hold direct children flat, matching what "I just dropped a Container here, it's empty" expects.
- **Self-reference bug fix** — original `rebuildContainerFromRow` showcase branch wrote `innerContainer.data.blocks = [innerContainer]` (the cell zone now contains the inner-container's row, which reconstructs to the inner container itself). Created circular reference → `JSON.stringify` threw → save bar never fired → next drag attempt infinite-looped through `findContainerPayload`. Rewrote so each cell's reconstructed contents ARE the parent's direct child slot (showcase detection: every cell holds exactly one container payload).

### Added — Auto / manual dark-mode toggle on color settings

- **Reusable `colorPickerWithDarkMode({value, valueDark, mode, onChange})` helper** in BlockEditor — renders three rows: light swatch + hex + Clear (existing pattern); mode toggle `[Same | Auto | Manual]`; manual dark swatch + hex + Clear (visible only in Manual mode); auto-derived preview chip with swatch dot (visible only in Auto mode). `onChange(light, dark, mode)` fires on every state change; `dark` is `''` for Same, the auto-derived hex for Auto, or the picked hex for Manual — renderer doesn't have to know about modes, just emits `dark` as a CSS variable when non-empty.
- **`deriveDarkMode(hex)` algorithm** — parses hex → HSL, inverts the lightness component (1 - L), keeps hue + saturation intact, converts back. `#1a1a1a` → `#e5e5e5`, `#4a90e2` → similar mid-luminance blue. Returns `''` for invalid input.
- **Wired into Typography Color** (heading / paragraph / list) — `d.color`, `d.color_dark`, `d.color_dark_mode`.
- **Wired into Container Background + Border colour** — `d.bg_color`/`d.bg_color_dark`/`d.bg_color_dark_mode` and `d.border_color`/`d.border_color_dark`/`d.border_color_dark_mode`.
- **Server defaults extended** — `_blank_page_block` adds `_dark` (`''`) and `_dark_mode` (`'same'`) for these three fields. Existing pages without them fall through cleanly via `dict.get()`.
- **Renderer emits CSS variables** — `typo_style` + `pp_typo_style` emit `--tsp-color-dm: <hex>` when `color_dark` is non-empty. Container styles emit `--tsp-bg-dm` and `--tsp-border-dm` similarly.
- **Three global dark-mode rules** — `html[data-theme="dark"] [style*="--tsp-<prop>-dm"] { <prop>: var(--tsp-<prop>-dm) !important; }` for color, background-color, and border-color. The `[style*="--tsp-…"]` attribute selector keeps each rule narrow; `!important` is needed because inline styles otherwise win over any cascade rule on the same property.

### Changed — Dark-mode `.fe-btn-primary` defaults

- **Background:** `#e2e8f0` → `#052566` (deep navy).
- **Text:** `#0b1026` → `#e2e8f0` (off-white).
- **Hover bg:** previously flashed to `#fff` → now `color-mix(in srgb, #052566 80%, #fff 20%)` so the hover stays in the same colour family.
- **Hover text:** kept at `#e2e8f0` so contrast doesn't flip mid-hover.
- The two scoped overrides (`.fe-meeting-card-actions .fe-btn-primary` uses `#1e3a8a`; `.fe-hero-cta .fe-btn-primary` derives from the admin's per-button colour pickers via `color-mix`) are explicit per-context choices and were left intact.

### Added — List block: display styles + per-card style settings

- **`display_style` field** on the list block with five options: Plain (default `<ul>`/`<ol>` with the existing Marker style dropdown), Numbered cards (the original `.fe-pp-steps` look — circular numeral + soft card per item), Checklist (`✓` mark in a brand-tinted pill), Arrow list (`→` mark in a neutral pill), Inline pills (rounded chips that flow horizontally + wrap). UI dropdown auto-hides the Marker style row when a non-plain display style is selected. Existing list blocks (no `display_style` field) render through the plain branch unchanged.
- **Card style settings panel** appears in the list editor when Numbered cards is selected. Exposes: card background (with auto / manual dark-mode toggle), border colour (with dark-mode toggle), border radius (px), padding (CSS shorthand), gap between cards (CSS gap value), shadow preset (None / Subtle / Medium / Large / Dramatic), Hover lift checkbox (toggles the lift + shadow on hover), number circle background colour (with dark-mode toggle), number circle text colour (with dark-mode toggle). Renderer emits inline styles + CSS custom properties on `.fe-pp-steps` (gap), `.fe-pp-step` (bg / border / radius / padding / shadow + hover-lift vars), and `.fe-pp-step-num` (bg / colour). Dark-mode counterparts ride along as `--tsp-bg-dm` / `--tsp-border-dm` / `--tsp-color-dm` so the existing global rules swap them under `html[data-theme="dark"]`.
- **List card border style now mirrors `.fe-meeting-card`** — `border: 1px solid var(--fe-accent)` + `border-radius: 16px` (was `1px solid var(--fe-border)` + 14 px) and the same hover lift recipe (`translateY(-2px)` + `0 8px 28px rgba(15,23,42,0.10)` shadow). Dark mode pairs both card families on `#131a33` / `#1f2a44`.
- **List cards flush against neighbours** — stripped the 28 px top margin baked into `.fe-pp-steps` and the auto-spacing rules between cards lists and adjacent prose blocks (`.fe-pp-steps + .fe-pp-prose { margin-top + muted color + smaller font + center }` and `.fe-pp-section .fe-pp-prose:has(+ .fe-pp-steps) { margin-bottom: 28px }`). Container `gap` is now the only source of inter-block spacing.
- **Hover lift toggle wired through CSS variables** — `.fe-pp-step:hover` now reads `var(--fe-pp-step-hover-lift, 1)` and `var(--fe-pp-step-hover-shadow, 0 8px 28px rgba(15,23,42,0.10))`. The card-style settings panel sets these to `0` and `none` respectively when the admin unchecks "Hover lift", so the lift + shadow are suppressed without touching the default rule.

### Added — Markdown enabled in list items + Text blocks

- **List items support markdown links** — added a `markdown_inline` Jinja filter that runs the same markdown + bleach pipeline as `markdown` but strips the single outer `<p>` wrapper for single-paragraph inputs. Multi-paragraph inputs keep all their tags. Switched all 10 `item|markdown` usages in `_blocks.html` + `frontend/page.html` to `item|markdown_inline` so list items can carry inline markdown (links, bold, italic, code spans) without the wrapping paragraph fighting parent inline elements (`.fe-pp-list-text` is a `<span>` — invalid to nest a `<p>` there). Editor placeholder updated: "List item (supports markdown — e.g. `[link](https://example.com)`)".
- **Paragraph (Text) blocks support full multi-line markdown** — switched paragraph rendering from `|markdown` (which required users to insert blank lines before lists/headings to be parsed) to `|markdown_block` (auto-inserts those blank lines via `_markdown_block_breaks`). Authors can now write `**bold**`, `*italic*`, `[link](url)`, `# heading`, `> quote`, `- list`, `` ```code``` ``, tables, etc. — Python-Markdown parses them all without the admin having to think about blank-line spacing rules. Editor placeholder rewritten with concrete examples; textarea bumped 5 → 6 rows.

### Fixed — Drag-drop reconstruction edge cases

- **Newly-dragged Container into a cell vanished on save** (regression after recursive nesting). `findContainerPayload(blockId)` only walked `sections` (the pre-drag state), so a brand-new container minted by a palette drop wasn't findable — the reconstruction's row branch did `if (!containerPayload) return;` and bailed without recursing into the new container's cell or pushing the container itself. The container was lost; blocks dragged INTO it were rescued to the orphan bin by the safety net but the container chrome was gone. Fix: maintain a `containerPayloadById` Map seeded from `sections` at boot AND populated by every code path that mints a fresh container payload (`makeRowFromPayload`, `makeNodeFromPayload`, the drop handler). `findContainerPayload` checks the map first (O(1) lookup), falls back to walking sections. Map gets re-seeded after each `syncStateFromDom` so deleted containers fall out and don't accumulate.
- **Self-reference circular bug fix in `rebuildContainerFromRow`.** The showcase-pattern branch was double-recursing — `innerContainers[idx].data.blocks = reconstructBlocksFromZone(zone)` produced `[innerContainer1Payload]` from a cell that contained the inner container's own row, so we were assigning `innerContainer.data.blocks = [innerContainer]`. `JSON.stringify` threw on the cycle, the hidden input never updated, save bar never fired, and `findContainerPayload` infinite-looped on subsequent drags. Rewrote: each cell's reconstructed contents ARE the parent's direct child slot (showcase detection: every cell holds exactly one container payload).
- **Lost-block safety net** in `syncStateFromDom`. Snapshots every block id present BEFORE the reconstruction; after, walks the new sections and any missing id gets pushed to the orphan bin (with the original payload) instead of being silently lost. Empty containers don't get rescued; leaf blocks and non-empty containers do. Container nesting is flattened on the way to the bin (a lost container becomes an empty wrapper) since its lost children would already have been rescued individually. Console-warns when it fires so the regression is visible. The orphan card auto-reveals + count badge updates so the admin sees the rescued blocks immediately.
- **Orphan bin always reachable.** Was `display: none` when empty (so admins couldn't drag blocks INTO an empty bin to park them). Now `opacity: 0.6` + a "Drop blocks here…" placeholder message that hides as soon as a pill lands. Bin is a stable drop target; the safety net's rescued blocks have a clear destination.

### Added — Recursive nested-container rendering

- **Containers can be nested inside cells** — `_block_node` (replaces `_container_columns`) recursively walks blocks: every container becomes a `'columns'` tree node (single- or multi-cell) with its own `block_id`, drop zones, Settings + Remove buttons. Cells contain other tree nodes recursively. A 2-col container holding two inner containers (each with their own children) renders as `columns(outer)` → 2 cells → each cell holds `columns(inner)` → that cell's content. Goes as deep as the data nests.
- **Macro recursion** — `structure_page_tree` split into a self-referencing `render_tree_node` macro called from cell contents.
- **Client-side recursion** — `reconstructBlocksFromZone(zone)` walks a cell's direct children (pills become block payloads, nested `.fe-page-structure-row--split` rows become container payloads via `rebuildContainerFromRow`). New `makeNodeFromPayload(payload)` returns either a pill (leaf) or a row (container) so cell hydration recurses too. `bindZones()` runs after every drop so newly-added nested zones become Sortable + drop targets immediately.
- **`makeRowSplit` two-pattern hydration** — showcase pattern (all direct children are containers, count matches `nCols`) maps each cell to one inner container; flat pattern distributes children round-robin across cells, with both pills and nested rows rendered via `makeNodeFromPayload`. Single-column containers no longer auto-provision an inner-container wrapper — they hold direct children flat.
- **Drop handler nesting** — when a Container or Two-panel is dropped INTO a column cell (`data-be-zone="container-col"`), the new element is a row (not a flat pill) inserted at the cursor's vertical position, matching what the server would render on next page load. Visual state stays consistent without re-render.

### Added — Auto / manual dark-mode toggle on color settings

- **Reusable `colorPickerWithDarkMode({value, valueDark, mode, onChange})` helper** in BlockEditor — renders three rows: light swatch + hex + Clear; mode toggle `[Same | Auto | Manual]`; manual dark swatch + hex + Clear (visible only in Manual mode); auto-derived preview chip with swatch dot (visible only in Auto mode). `onChange(light, dark, mode)` fires on every state change; `dark` is `''` for Same, the auto-derived hex for Auto, or the picked hex for Manual — renderer doesn't have to know about modes, just emits `dark` as a CSS variable when non-empty.
- **`deriveDarkMode(hex)` algorithm** — parses hex → HSL, inverts the lightness component (1 - L), keeps hue + saturation intact, converts back. `#1a1a1a` → `#e5e5e5`, `#4a90e2` → similar mid-luminance blue.
- **Wired into Typography Color** (heading / paragraph / list), **Container Background + Border colour**, and the new **list card style fields** (card bg, card border, number bg, number text).
- **Server defaults extended** — `_blank_page_block` adds `_dark` (`''`) and `_dark_mode` (`'same'`) for these fields. Existing pages without them fall through cleanly via `dict.get()`.
- **Renderer emits CSS variables** — `typo_style` + `pp_typo_style` emit `--tsp-color-dm: <hex>` when `color_dark` is non-empty. Container styles emit `--tsp-bg-dm` and `--tsp-border-dm` similarly. List cards emit `--tsp-bg-dm` / `--tsp-border-dm` on `.fe-pp-step` and `--tsp-bg-dm` / `--tsp-color-dm` on `.fe-pp-step-num`.
- **Three global dark-mode rules** in `frontend.css`:
  ```css
  html[data-theme="dark"] [style*="--tsp-color-dm"]  { color: var(--tsp-color-dm) !important; }
  html[data-theme="dark"] [style*="--tsp-bg-dm"]     { background-color: var(--tsp-bg-dm) !important; }
  html[data-theme="dark"] [style*="--tsp-border-dm"] { border-color: var(--tsp-border-dm) !important; }
  ```
  The `[style*="--tsp-…"]` attribute selector keeps each rule narrow; `!important` is needed because inline styles otherwise win over any cascade rule on the same property.

### Changed — Edit modal polish

- **Removed "← View all blocks" button** from the focused-edit modal head. The associated JS (focus-clear button reference, click listener, hidden-toggle calls inside `clearFocus` / `focusBlock`) is gone. `clearFocus()` now also runs whenever any close affordance fires (`×` icon, Done button, backdrop) so the next pill click lands in a fresh focus regardless.
- **1 rem gap between modal title and × close button** — `.fe-page-edit-modal .modal-head { gap: 1rem; }` plus `.fe-page-edit-modal .modal-head > .icon-btn[data-close] { margin-left: 1rem; }` for the belt-and-braces case where browser flex `gap` doesn't honour cleanly.

### Changed — Page edit form: three cards merged into one

- **Page settings + Page width + Background → single `.fe-page-settings-card`.** Three subsections separated by 1 px hairline + an inline `<h3>` sub-heading paired with the muted helper text. First subsection's border is suppressed via `:first-of-type`. Sub-heading uses `flex` so the muted helper sits inline on wide viewports and wraps below on narrow. All form input names (`title`, `slug`, `is_published`, `width_mode`, `max_width`, `full_padding_pct`, `bg_image`, `clear_bg`, `bg_mode`, `bg_tile_scale`) unchanged — the save route's form parsing keeps working without changes.

[Unreleased]: https://github.com/your-org/tspro/compare/v1.8.6...HEAD
