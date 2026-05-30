# Changelog

All notable changes to this project will be documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [2.9.5] — 2026-05-30

### Added

- **Guided Zoom Meeting launcher — a stepped, blur-backdrop wizard on the backend meeting detail page.** Online/hybrid meetings gain a **Launch Zoom Meeting (Guided)** button above the Zoom ID/passcode block that opens a modal walking a host through three steps: **Sign in** (warns hosting needs a Mac/Windows/Linux desktop — not iOS/Android/Chromebook — and shows the assigned account login + click-to-copy password with reveal), **Get code** (reminds the user to click *"Or alternatively, Verify via one-time passcode"* rather than "Allow on other devices", then retrieves the OTP — see below), and **Start the meeting** (a Launch button on the start URL plus Meeting ID/passcode to copy, and a caveat to sign out of any other Zoom account in the browser first). Each step carries an annotated screenshot that opens in a lightbox; the stepper circles at the top are clickable (and keyboard-accessible) to jump between steps.
- **Automatic OTP-code retrieval over IMAP (`app/otp_fetch.py`).** A new fetcher logs into the shared OTP inbox read-only (IMAP `EXAMINE` — never marks mail read), finds the freshest Zoom sign-in code, parses the 6-digit passcode, and returns it with the email's own timestamp. Stripping `<head>`/`<style>`/`<script>` first keeps embedded CSS/font-URL digits from polluting the search, and a hint-scored extractor (anchored on "expire", "passcode", "verification"…) isolates the real code over stray numbers (map coordinates, dates, phone numbers, zips). Backs the wizard's Step 2, an inline **Retrieve latest code** button on the meeting detail OTP Email section, and the OTP Email widget on the **Zoom Accounts** page — all sharing one `initOtpFetch()` handler via a `[data-otp-widget]` container, so seasoned hosts can pull a code in place without opening the wizard.
- **IMAP mailbox settings in Settings → Security → Zoom OTP Email.** The existing OTP-email credentials gained IMAP server / port / SSL / optional username / mailbox / optional app-password fields (encrypted via Fernet, additively migrated). Username/password fall back to the email + password above when left blank.
- **Location now resolves to its full address with an Open-in-Maps link.** The meeting detail Location card shows the saved Location's complete address (not just the name) plus an **Open in Maps** button (the record's `maps_url`, else a Google Maps search). Resolution moved to the route with tolerant matching (exact normalized match, then a difflib similarity ≥ 0.86 fallback) so a one-character typo in the meeting's free-text location still resolves.

### Changed

- **The "Retrieve latest code" button now polls the inbox for up to 3 minutes.** Zoom is slow to send the passcode email, so a single check usually came up empty. Clicking Retrieve now keeps checking every ~6 seconds (showing a spinner and "Checking for code…") until a code lands or 3 minutes elapse; it stops early on a configuration/login error. Backed by a new `retryable` flag on the fetch response (the "no email/code yet" and transient-network cases are retryable; config/login errors are terminal). Copy updated to "it may take up to a minute to retrieve a code".
- **OTP section renamed to "Zoom One-Time-Passcodes (OTP)"** everywhere it appears (meeting detail, Zoom Accounts page, Settings → Security), and on the meeting detail page it's wrapped in a `zg-card` panel matching the Schedule/Location cards.
- **Meeting detail page restyled into a balanced two-column card layout.** The Zoom section is wrapped in its own `data-card` (brand-accent panel) in the right column, the full-height vertical divider is gone, the logo moved into the left column so the Zoom card rises to the top, and the Schedule and Location sections sit in their own card-style containers. The 50/50 grid is preserved even for in-person meetings (the right column simply renders blank).
- **OTP code freshness window tightened to 10 minutes, and the newest code always wins** when several arrive in the window (ranked by Zoom-origin, then code confidence, then recency — so a genuine code can't be hijacked by a stray number in a newer non-code notice).
- **Click-to-copy chips render in Inter with normal letter spacing, and the "Click to copy" tooltip now has a green background.**

### Fixed

- **OTP search no longer misses codes near the UTC midnight boundary.** IMAP `SINCE` compares against each message's `INTERNALDATE` in the *mail server's* timezone (DreamHost is US-Pacific), so a code arriving just after UTC midnight was dated the previous day server-side and excluded. The `SINCE` window is widened by a day to absorb any server offset; the precise per-message UTC timestamp check still enforces the real freshness window.
- **`/api/live-meeting` (and any `/api/*` background poll) no longer skews visitor metrics.** The utility bar polls `/api/live-meeting` every 30s on every public visitor; those machine requests were being recorded as `VisitorEvent` rows and inflating totals and the top-paths list. `_should_skip` now drops all `/api/*` requests at record time, and a shared `_NO_API` clause excludes any historical `/api/*` rows from every aggregation (totals, daily series, uniques, top paths/referrers, device/browser/OS donuts, hourly distribution) — non-destructively, without deleting the rows.

## [2.9.4] — 2026-05-29

### Added

- **Dynamic-background picker reorganised into Background + Options tabs with a live preview.** The modal now leads with a fixed preview band (`.dynbg-modal-preview`, a sibling between `.modal-head` and the scroll body so it sits flush under the title bar and nothing scrolls above it) that re-renders on every settings change — preset, overlay, colours, pastel strength, randomize toggles, and per-preset knobs all repaint the sample in place. The **Options** tab merges the former Overlay + Colours panels and only shows the controls that apply to the active preset (driven by a new `PRESET_CAPS` capability spec stamped onto the panel as `data-dynbg-preset-caps` JSON), so admins never see a knob that does nothing for the chosen background.
- **Per-preset tuning knobs.** A generic `knobs` JSON dimension (validated/scoped by `dynbg.normalize_knobs` against `PRESET_CAPS`, stamped as CSS custom properties by `knobs_to_css_vars`) carries each preset's sliders without per-field plumbing. Dotted grid exposes Dot size / Spacing / **Rotation** / Opacity; diagonal lines exposes Angle / Spacing / Opacity / Thickness. Round-tripped end-to-end through `routes.py`, `frontend.py` template settings, the block editor, and the page-hero modal.
- **Size + Intensity on every texture overlay.** Previously only Noise grain was tunable; Scanlines, Linen, Vignette, Crosshatch, and Dot weave now each expose a Scale (`--fe-dynbg-ov-scale`) and Intensity (`--fe-dynbg-ov-opacity`) slider via the new `OVERLAY_KNOBS` spec, with per-overlay slider bounds set in the modal. Defaults of ×1 reproduce the original look so existing saves render unchanged.
- **Foreground/background colours for the pattern presets.** Dotted grid and diagonal lines are now two-colour presets labelled **Dots/Lines** + **Background** — Colour 1 (`--fe-dynbg-c1`) drives the dot/stroke colour and Colour 2 (`--fe-dynbg-c2`) the surface fill (light + dark). Custom colours now actually affect these patterns; leaving a slot blank falls through to the brand token.
- **Server-randomised picker thumbnails.** `dynbg.thumb_style()` seeds each catalog tile with a fresh random palette + random positions per page load, so the picker reads as a lively sample set rather than identical brand-default renders.
- **Animated mobile menu reveal (Recovery Blue).** Tapping the hamburger now slides the primary nav dropdown down with an eased fade (`@keyframes feMobileMenuDrop`, 280 ms `cubic-bezier(0.2, 0.8, 0.2, 1)`), and the mega-menu panel uses the SAME entrance on mobile (≤ 880 px) regardless of the desktop panel-fade toggle, so opening either reads as one consistent motion instead of a hard cut. Both replay on each open via their `.fe-nav-open` / `.open` class; gated by `prefers-reduced-motion`.

### Changed

- **Dynamic-background recipes extracted into a shared `app/static/css/dynbg.css`**, now linked by both the admin shell (`base.html`) and the public frontend templates so the picker's live preview and thumbnails render the real recipes. These rules are no longer duplicated in `frontend.css` — single source of truth.
- **Unset custom-colour slots display a ∅ null glyph** in the picker chips instead of the brand-default blue swatch, so an admin can tell at a glance which slots are overridden vs. falling through to the theme token.
- **Default randomize-on for the presets that have movable parts.** Aurora blobs / mesh / bands default the randomize-colours (and positions, where applicable) toggles on when first picked; the deliberate fg/bg pattern presets default them off.
- **Footer signed-in auth buttons are left-aligned and wrap.** The "Return to dashboard" + "Logout" pair in the `admin_login` footer block now sits left-aligned with a 1 rem gap (was pushed to opposite column edges via `justify-content: space-between` + `margin-left: auto`) and wraps to a second line when the block is too narrow.
- **More breathing room under the mobile hamburger dropdown.** The Recovery Blue mobile nav panel gained an extra 1 rem of bottom padding (`8px 20px calc(16px + 1rem)`) below its last button.

### Removed

- **Retired the Starfield, Noise paper, and Spotlight glow base backgrounds.** All of their catalog entries, CSS recipes, and supporting code were removed. The six texture *overlays* (Noise grain, Scanlines, Linen, Vignette, Crosshatch, Dot weave) are unaffected. Any surface previously set to one of the three retired presets falls back to "no dynamic background" (its solid colour / uploaded image still renders).

### Fixed

- **Dotted-grid rotation now tiles across the whole surface instead of a narrow band.** The dots layer was only oversized `inset: -30%` (≈1.6×), so on a wide/short (or tall/narrow) surface a near-90° rotation shrank the dotted region to a band the width of the *short* side — a per-axis-percentage limitation (`inset`/`width %` can't size off the *longer* dimension). `.fe-dynbg-dotted-grid` is now a CSS size query container and the dots layer is a centred square sized `200cqmax` (2× the host's longest side); a centred square of side 2·max always exceeds the host's diagonal, so the lattice fully covers at any angle and aspect ratio.
- **The pastel-strength slider now live-updates the picker preview.** Dragging it re-pastelises the in-modal sample immediately (the admin shell is light mode, so the preview applies the pastel directly to `--fe-dynbg-cN`) instead of only taking effect after save.
- **Recovery Blue header is now fully sticky on mobile.** The shared headroom script still slides the header up on scroll-down at desktop widths, but the transform is neutralised at ≤ 880 px (`.fe-header-recovery.fe-header-hidden { transform: none }`) so the helpline bar + hamburger stay pinned and reachable while scrolling instead of hiding.
- **Mobile utility bar no longer reveals a neighbouring item's pill at rest.** The horizontal swipe strip's snap "pages" were sizing to their content width — a percentage `flex-basis` collapses to content inside a horizontal scroll container — and the strip retained the header's inline side gutter, so each page was inset and the gutter exposed the adjacent item. Pages now pin to the full viewport via `min-width: 100%` (which resolves against the container's definite width), the strip is forced full-bleed with `padding: 0 !important` (beating the inline gutter, mirroring the existing `max-width: none !important`), and `overflow: hidden` clips any container wider than the viewport so nothing bleeds past a page edge.

## [2.9.3] — 2026-05-28

### Added

- **Per-template "Card body preview" setting on the announcements_list and events_list customize panels.** New radio + character-count input on `tpl_customize_panel` (gated on `kind in ('announcements_list', 'events_list')`) stores `card_body_mode` (`'full' | 'truncated'`) and `card_body_max_chars` (clamped 50..2000, default 200) into the per-template settings leaf via `frontend_template_settings_save`. The character input is `disabled` until the truncated radio is selected; an inline IIFE re-gates it on the fly. `frontend.py::template_settings` was extended to include the two new keys in its passthrough allowlist — without this the loader silently dropped the keys and persisted saves wouldn't apply on the public render. **(Fixed in same commit.)**
- **`_announcement_card.html` reads the mode + char cap from `_announcements_list_tpl`** (the dispatcher template's scoped variable). Truncated mode slices `ann.body` via Jinja's `truncate(N, True, '…')` BEFORE piping through `markdown_block`, so the trailing ellipsis lands inside the rendered paragraph. Default mode = `full` — preserves the legacy render for sites that haven't touched the setting.
- **`_event_card.html` adds a new `.fe-events-card-body-preview` block** rendering `ev.body` under the existing `ev.summary` line, controlled by the same mode + cap pair read from `_events_list_tpl`. Default mode = `truncated` at 200 chars — events historically rendered only `summary`, so an unbounded body would balloon every card; the opinionated default keeps cards compact while letting admins flip to full for long-form previews. The Magazine "More events" tiles force-compact via the include's `compact=true` and bypass the new block entirely.
- **"Read more ›" link on every list card.** Renders unconditionally at the bottom of `.fe-announcements-card-body` and `.fe-events-card-body` (and on the Timeline layout's `.fe-events-tl-card`), independent of body length or truncation setting. Targets the post's detail URL via `post_url(...)`. New `.fe-card-read-more` CSS class — accent-coloured weight 600 text with a `›` chevron that slides 3px on `:hover` / `:focus-visible` (motion gated by `prefers-reduced-motion`). Timeline variant carries `position: relative; z-index: 2` so the visible link's pointer events win over the card's absolute `.fe-events-tl-card-link` overlay.

## [2.9.2] — 2026-05-28

### Added

- **Pastel-strength slider on the dynamic-background picker.** Replaces the previous binary "Use pastels in light mode only" checkbox with an integer 0-100 slider + live numeric readout. `dynbg.normalize_pastel_strength()` accepts and coerces legacy booleans (`True` → 100, `False` → 0), ints, and numeric strings; `pastelize(hex_str, strength=100)` lerps between the source HSL values and the full pastel target so intermediate slider positions produce intermediate paleness. `encode_config()` persists the int (omits when 0); `decode_config()` returns the int (legacy boolean records resolve to 100). `colors_to_css_vars()` and the per-template settings JSON leaf (`bg_dynbg_pastel_light`) carry the strength end-to-end. Form-parse paths in `routes.py` now pass the raw form value through and let `encode_config` clamp.
- **Themed featured-image elevation on detail pages.** New CSS rule on `.fe-event-detail-cover` (Classic) and `.fe-event-time-cover` (Timeline) emits an `lg` shadow at rest, expanding to `xl` on `:hover` / `:focus-visible` / `:focus-within`, with the colour driven by new `--fe-color-card-primary-shadow` + `--fe-color-card-primary-shadow-dark` CSS variables emitted from `design.py::card_chrome_css_vars`. Light/dark variants composed via `color-mix(in oklab, var(--…) <alpha>%, transparent)`. Transition is a flat `box-shadow 200ms ease` (no theme-token indirection so the timing stays predictable across themes). Border on the Classic cover stripped (`border: 0`) and the legacy `translateY(-3px)` hover lift overridden with `transform: none` — elevation now reads as pure shadow expansion, no jumping.

### Changed

- **Detail-page hero is now a 33 % / 66 % split** between the featured-image column and the body column (previously a fixed 427 px / 1fr). The fixed `height: 320px` on `.fe-event-detail-cover` was also dropped so the cover scales with the column width via its `aspect-ratio: 4/3` instead.
- **Pastel target at strength 100 is now ~50 % paler than the previous all-or-nothing pastel band.** The legacy full-pastel target (`min(sat, 0.339)`, lightness 0.69–0.75) is now halved on saturation and pushed halfway toward pure white on lightness, landing in cream / blush / mint territory. `#ff0000` at strength 100 now resolves to `#ded0d0` (was `#ca9595`).
- **Meeting detail logo bumped to 240 px on desktop** across all four meeting-detail layouts. Both the classic-specific `.fe-meeting-detail-head-logo .fe-meeting-logo` rule and the shared base `.fe-meeting-logo` rule updated; the `max-width: 600px` mobile override (140 px) is preserved.

## [2.9.1] — 2026-05-28

### Fixed

- **Dynamic Background picker rendered BEHIND the template-edit modal that triggered it.** Both modals had `z-index: 100`; same-z-index siblings stack by DOM order. The `#dynbg-picker-modal` lives in `base.html` (early DOM), but the per-template settings modal on `frontend_templates.html` is built dynamically via JS and `document.body.appendChild`'d at runtime — landing AFTER the picker in the DOM, so the picker painted under it. Bumped `#dynbg-picker-modal`, `#media-picker-modal`, and `#icon-picker-modal` to `z-index: 105` (above content modals at 100, below the sticky save bar at 110). Future global pickers should join the same selector.
- **Authenticated users with a public tab open showed as "persistently online on `/api/live-meeting`".** The utility bar's poller fetches `/api/live-meeting` every 30 s (and on every visibility change) when the LIVE-badge toggle is on, and `_track_last_seen` in `routes.py` only skipped `main.api_*` endpoints — but the live-meeting endpoint lives on the **frontend** blueprint as `frontend.api_live_meeting`, so each poll rewrote `last_path` to `/api/live-meeting` and refreshed `last_seen_at`, keeping the user warm forever. Added a path-based skip (`request.path.startswith("/api/")`) so background polls on any blueprint's `/api/*` route are excluded from location tracking. Match by path (not endpoint name) so future API routes on any blueprint inherit the skip automatically.

## [2.9.0] — 2026-05-28

### Added

- **Page draft slot for already-published pages.** New `Page.draft_json` (TEXT) + `Page.draft_saved_at` (DATETIME) columns capture an in-flight snapshot of every editable field (title, slug, blocks_json, layout, background, padding, SEO, colors, fonts) without touching the live row. `frontend_page_save` reads a `save_action` form field (`publish` | `draft`); the `draft` branch writes a typed snapshot dict to `draft_json` and clears it on the next publish, while the `publish` branch keeps the existing column writes and now also nulls out the draft slot atomically. Uploaded draft assets (bg / og images) still land on disk so a Publish later can reference them; un-published draft uploads are picked up by the daily orphan-cleanup pass. `frontend_page_edit` detects a stashed draft, deserialises it, expunges the Page from the session, and overlays the draft values onto the in-memory object so autoflushes during the rest of the view can't accidentally persist draft values to the live row. New `frontend_page_discard_draft` endpoint clears the slot.
- **Edit history for pages with one-click restore.** New `PageRevision` model — `page_id` FK with cascade delete, `action` ('draft' | 'publish'), `snapshot_json` (same shape as `draft_json`), `created_at`, `created_by_id` (FK to User). `_record_page_revision()` is called from both save branches; `_PAGE_REVISION_LIMIT = 50` per page, older rows trimmed in the same transaction. New `frontend_page_revisions` endpoint returns a JSON list for the editor modal; `frontend_page_revision_restore` writes the chosen snapshot into `draft_json` (non-destructive — the live row is untouched until the admin Publishes) and logs the restore as its own draft revision for audit. New `History` button + `#page-history-modal` in the editor renders the list with Draft/Published chips, local-time timestamps, author, and a Restore form per row.
- **Live-update preview window via opener polling.** `frontend/page.html` injects a poller (in `preview_mode` only) that reads `window.opener.document.getElementById('page-blocks-json').value`, debounces to 500ms ticks, and silently re-POSTs to `/_preview/page/<id>` when the JSON changes. The fetched HTML replaces `document.body.innerHTML` in place — inline scripts are cloned+replaced so lottie / dynbg / copy-script init code re-runs. Poller state lives on `window.__tspPreviewState` so it survives the body swap; an immediate post-fetch re-poll catches keystrokes that landed during the in-flight fetch. Scroll position snapshotted across each swap. Editor side just opens the named preview window once and never re-submits — the preview pulls instead of the editor pushing.
- **Throttled BlockEditor → hidden-input sync.** `editModal` input/change listeners now `editor.serialize()` and write to `#page-blocks-json` on a leading-edge + trailing-edge 150 ms throttle so continuous typing in a heading / paragraph keeps the hidden field fresh (and therefore the preview poller's reads accurate). Pure debounce previously only flushed on a typing pause; a long sentence typed without breaks left the preview stuck at the pre-typing value.
- **Yellow save bar reskinned for the page editor.** The page-edit IIFE relabels `#fe-save-bar-btn` to "Publish", injects a sibling "Save Draft" button (ghost-style, text + border tinted with the Publish button's fill `#422006` for a matched-pair look), and wires both to flip `#page-save-action` before triggering the shared `feSaveBar` save loop. A `__tspViaDraft` flag short-circuits the capture-phase reset so the draft proxy click doesn't get overwritten back to publish.
- **Top-level "Publish draft" shortcut.** Conditionally rendered in `top_actions` when `draft_active` is true — same submission path as the yellow bar's Publish button, but visible without needing a dirty edit to expose the save bar. Lets admins publish a stashed draft exactly as-is.

### Fixed

- **Two-column container scrambled child blocks on save when the cells had different lengths.** The save path round-robin-flattened cells into `data.blocks` and the load path round-robin-redistributed them, so `left=[A,B]` + `right=[C,D,E]` round-tripped to `left=[A,B,E]` + `right=[C,D]`. CSS grid's `auto-flow: row` can't express unequal columns; the fix persists cell membership explicitly as `data.cell_lengths: [2, 3]` (concat-by-cell flat list + per-cell counts). All four touchpoints updated: `page_structure.js::rebuildContainerFromRow` writes `cell_lengths`, `makeRowSplit` slices by it on initial draw, `routes.py::_page_active_tree` uses it for the structure card render, and the public `templates/frontend/page.html` + `templates/_blocks.html` container blocks emit a `.fe-pp-grid-cell` flex-column sub-wrapper per cell carrying `grid-column: N` so the actual page renders the layout as built. Legacy data without `cell_lengths` falls through to the previous round-robin distribution on every path, so existing pages are unaffected until their first save.
- **Unplaced blocks bin pills had no background / chrome and blended into the bin.** Base `.fe-page-structure .fe-page-structure-block` styles are scoped to the structure card, but the orphan bin renders inside a separate `.fe-page-orphans` section (siblings, not nested), so orphan pills inherited none of the base flex / padding / border / brand-soft bg styling — only my earlier padding override. Added dedicated `.fe-page-orphans-list .fe-page-structure-block` rules mirroring the structure card's pill chrome with `var(--panel)` background so pills read as discrete cards against the bin's `var(--panel-2)` bg, plus an explicit `gap: 8px` on the list container.
- **Status chips on the Pages list collided when a row had both a visibility chip and an "Unpublished changes" chip.** Wrapped them in `.fe-page-status-pills` (`display: flex; gap: 6px; flex-wrap: wrap`).

## [2.8.3] — 2026-05-28

### Added

- **Content-page Preview live-updates.** The Preview button on the page editor (`frontend_page_edit.html`) now opens the preview into a fixed, named window (`tsp-page-preview-<page_id>`) and the editor re-POSTs the current `blocks_json` to that window on every change to the edit form, debounced 700 ms. The structure card already dispatches `input` events from the hidden `#page-blocks-json` field whenever pills are dragged / removed / edited, so the live-update wiring just listens for those at the form level. Live-update only fires when the preview window is still open (`win.closed` check) so editing without an open preview costs nothing. Scroll position is preserved across reloads by a small companion script injected into `frontend/page.html` (preview-mode only) that stashes `window.scrollY` in `sessionStorage` on `beforeunload` and restores it on next load.

### Fixed

- **Markdown lists in admin-authored post / meeting bodies didn't render unless the author left a blank line before the dash.** The detail templates piped these fields through the `markdown` Jinja filter, which is bare Python-Markdown with no preprocessing — Python-Markdown requires a blank line before a list / heading / blockquote when it follows a paragraph, so `intro⏎- item` rendered inline. Switched to the existing `markdown_block` filter, which inserts the required blank line for the user before any list / heading / blockquote that directly follows non-blank content. Affects all four meeting-detail templates (`frontend/meetings/classic.html`, `card_stack.html`, `magazine.html`, `minimal.html`) for `meeting.description` and all four event-detail templates (`frontend/events/classic.html`, `minimal.html`, `poster.html`, `timeline.html`) for `event.body`. Event templates are reused by `/announcement/<slug>` (see `frontend.announcement_detail`), so this covers announcement bodies too.
- **SVG image blocks rendered at the SVG's intrinsic width instead of the admin-chosen `max_width_pct`** when the block sat inside a flex container with `align-items: center`. Block-level `<figure>` children of a centered flex parent only stretch when given an explicit width — `max-width` alone has nothing to clamp because the figure shrink-wraps to the SVG's intrinsic dimensions (e.g. `<svg width="452">`). The image-block renderer in both `templates/frontend/page.html` and `templates/_blocks.html` now appends `width: <pct>%` to the figure's inline styles when the src ends in `.svg` (case-insensitive, query/fragment stripped), and `width: 100%; height: auto` to the img, so SVGs scale to fill the chosen percentage regardless of their source dimensions. Raster images keep the existing `max-width: 100%` semantics so a small image in a wide figure doesn't get upscaled.
- **Unplaced blocks bin on the page builder wrapped pills horizontally with a different background**, making mixed-length labels jumble. The `.fe-page-orphans-list` zone now stacks pills vertically (`flex-direction: column; gap: 6px`) matching the structure tree, the `background: var(--panel)` per-pill override was dropped so orphan pills inherit the same `var(--brand-soft)` tint as placed pills, pill padding bumped to `10px 12px` with radius `10px`, and the bin container's radius bumped to `12px`.

## [2.8.2] — 2026-05-26

### Added

- **CSV export on Watchtower → Visitors.** New **Export CSV** button in the tab's top actions downloads the current window's metrics — daily traffic, top paths, top referrers, devices/browsers/OS — as a single CSV. Server-side aggregation reuses the same `visitor_metrics` helpers the page renders from, and the export honours the active **Unique visitors / Hits** mode so the export numbers match what was on screen.

### Fixed

- **Events auto-archive sweep was running on the server's UTC clock instead of the site-configured timezone.** `event_ends_at` is stored as naive site-local (parsed straight from the admin's HTML5 `datetime-local` input), but `_auto_archive_events` was building its cutoff from `datetime.utcnow().date()` — so an event ending at 9 pm Pacific would be flagged "past" any time after 1 am UTC the same day, and conversely a 2 am Eastern end-time wouldn't sweep until UTC midnight rolled past it. Cutoff is now `now_local_naive(site).date()`. Same fix applied to the four other places that gate on "is this event past?": `frontend._post_in_archive`, the `events_list` route, the `archive` route, `blocks.filtered_events`, and `search._events_source` + `search._archive_source`. Watchtower / visitor-metrics callers also use `datetime.utcnow().date()` but compare against UTC-stamped system rows so they're correct as-is and not touched.
- **Watchtower → Visitors daily-traffic chart polish:** legend back on the right, donut grid lines up at all viewport widths, and hover tooltips now show the exact count + date on the daily chart and the full slice breakdown on the donuts.

### Internal

- **Video Streamer module parked under `archive/video_streamer/`** — full implementation (Flask routes, `flask-sock` WebSocket ingest, ffmpeg `StreamManager`, admin UI, public HLS viewer with `hls.js`, sidebar entry, file-upload source, browser-camera source) preserved as a self-contained archive plus an `integration.patch` capturing the seven touchpoints. Not on the active code path; the archive's README documents the restore recipe (`git apply` + four `mv`s) for a future release. SiteSetting columns and the `video_stream` table left in `_migrate_sqlite` history so an upgraded DB stays compatible if the module is reinstated.

## [2.8.1] — 2026-05-26

### Added

- **Source IPs visible on Watchtower → 404s with one-click blocking.** Every row in **Top missing URLs** now has an **IPs** chevron button (route icon) that lazily fetches and inlines a panel listing the distinct IPs hitting that URL in the current window — IP, hit count, last-seen timestamp, and a per-IP **Block IP** button. Already-blocked IPs render as a red "Blocked" chip instead. The **Recent 404s** table gained a **Source IP** column plus a per-row **Block** button. Blocking from either surface reuses the existing `/watchtower/ban-ip` endpoint and returns the admin to the 404s tab; the ban reason is auto-populated with the 404 path. Powered by a new `not_found_ips_for_path()` aggregator + `GET /watchtower/not-found/path-ips` HTML-fragment endpoint; one batched `IPBlock` lookup populates the "Blocked vs Block" state per page load so there are no N+1 queries. New `NotFoundEvent.ip` column (`VARCHAR(45)`, indexed) captures source IP on every public 404 going forward — existing rows display "—" since they predate the column.

## [2.8.0] — 2026-05-26

### Added

- **Cookie Compliance module** — new "Cookie Compliance" entry under **Web Frontend → Setup** that runs a privacy/cookie banner on the public site. Module-level on/off toggle. Three prompt modes: **Notice** (informational, single dismiss), **Consent** (Accept / Reject equally prominent), and **Strict opt-in** (GDPR-compliant — non-essential cookies blocked until accept). Three regional quick-start presets (GDPR/UK GDPR, CCPA/CPRA, Generic) apply best-practice defaults — mode, copy, position — in one click. Auto-region inference (Cloudflare/Fastly/Vercel country headers + `Accept-Language` fallback) escalates EU/UK visitors to strict and California visitors to consent regardless of the configured mode (auto can only escalate, never relax). Banner copy is fully customizable (title, body, accept/reject/more labels, position: bottom-bar / bottom-left / bottom-right / modal). Visitor choice persists in a first-party `tsp_cookie_consent` cookie for a configurable lifetime (default 365 days, max 730, `SameSite=Lax`, `Secure` on HTTPS). Three **starter privacy policy generators** (GDPR / CCPA / Generic) create a fully-seeded Page and link it as the policy with one click — admin just fills in placeholder fields (organisation name, contact email, retention periods). 13 new `cookie_compliance_*` columns on `SiteSetting` with matching `_migrate_sqlite` entries; new module `app/cookie_compliance.py` owns region inference + presets + templates.
- **Privacy & cookies footer block** — draggable from the footer builder palette. Renders a "Privacy policy" pill linking to whatever's configured under Cookie Compliance plus a "Cookie settings" pill that clears the consent cookie and re-prompts the banner so visitors can change their mind later. Both pills only render when the corresponding piece is configured — the block gracefully no-ops if dragged in before Cookie Compliance is set up.
- **Unique visitors / Hits toggle** on the Watchtower **Visitors** tab and (then-renamed) Web Frontend Metrics page. Default emphasis switched from hits to **unique visitors** — the more meaningful number for "how many real people". Segmented pill toggle with a `?` tooltip explaining each mode; preference persists in `localStorage` and is restored before paint so the page never flashes the wrong side. Both sets pre-render server-side so the toggle flips instantly. KPI tiles, daily traffic chart, top paths, top referrers, devices, browsers, OS, and hour-of-day all swap their counts (and re-rank where applicable) when toggled.
- **"Manage redirects" button** on the Watchtower **404s** tab top actions, links straight to `/tspro/frontend/redirects` so the admin can hop from spotting a 404 to managing redirects without navigating.

### Changed

- **Web Frontend Visitor Metrics page is now the Watchtower Visitors tab.** All panels (rich daily-traffic chart with hover tooltips, hour-of-day strip, Devices/Browsers/Operating systems donuts, expandable Top paths / Top referrers lists, summary KPI tiles) live in one place. `/tspro/frontend/metrics` 301-redirects to `/tspro/watchtower/visitors` with the query string preserved. The Web Frontend admin subnav's "Visitor Metrics" entry, the main `/tspro` dashboard widget's "Open metrics" button, and the Web Frontend dashboard widget's "Full metrics" button all link to the new home. Both dashboard widgets now show **unique visitors** as the headline (sub-line still surfaces hits + hits/visitor ratio); the sparkline in the Web Frontend widget switched from hits to uniques to match.

### Fixed

- **Sidebar quicknav pills (Web / View / Watchtower) no longer get an underline on hover.** They inherited an underline from the global `a:hover { text-decoration: underline }` rule because `.sidebar-quicknav-btn:hover` was setting bg/color/border but not `text-decoration`. Added the explicit override.

## [2.7.5] — 2026-05-26

### Added

- **Create a redirect from any 404 in one click** — every row in the **Top missing URLs** and **Recent 404s** sections of Watchtower → 404s now has a **Redirect** button. Clicking it opens a modal pre-filled with the source path; type the target, save, and a 301 is added to the `UrlRedirect` table without taking you off the page. The row in-place swaps to a "redirected" chip so you can immediately spot which URLs you've handled and keep going through the list. New JSON endpoint `POST /watchtower/not-found/redirect` (CSRF-protected via the global `X-CSRFToken` fetch wrapper); validation mirrors the full Redirects admin page.
- **Wildcard redirects** — source paths ending in `/*` (e.g. `/swag/*`) now match every URL under that prefix and land them all on the literal target. Exact-match rules always win over wildcards; among wildcards the longest prefix wins, and the `/` boundary keeps `/swag/*` from accidentally catching `/swagger`. The Watchtower modal grew a **Use `/*`** helper button that converts the clicked 404 path into a parent-prefix wildcard, and the Redirects admin page (`/tspro/frontend/redirects`) explains the syntax. Validation rejects `*` anywhere other than a trailing `/*`, a bare `/*`, `*` in the target, and self-loops where the target falls under the wildcard prefix.
- **Expandable Top missing URLs / Top paths / Top referrers cards** on both the Watchtower **404s** and **Visitors** tabs. Each card shows 30 rows initially and a **Show 30 more** button below the list reveals the next batch with a quick fade/slide-down keyframe (220 ms cubic-bezier, ~8 ms per-row stagger; respects `prefers-reduced-motion`). The card-head meta updates live to "showing X of Y" and the button hides itself when the pool is exhausted. Server now fetches up to 300 rows for these lists so most expand sessions don't need another round-trip. The expander lives in `app/static/js/app.js` and matches any `[data-wt-expand]` / `[data-wt-expand-btn]` pair.

### Fixed

- **Watchtower → Visitors "Hour of day" chart was rendering as 24 flat 1-px ticks** even with thousands of views in the window. Root cause: `.wt-hourly` was using `align-items: flex-end`, which sized each column to its tiny tick label instead of stretching to the 140 px container; the inner `flex: 1` track then collapsed to ~1 px, leaving the bars' percentage heights with no reference. Changed to `align-items: stretch` (with `min-height: 0` on the column + track for safe flex shrinking); tracks keep their own internal `align-items: flex-end` so bars still bottom-align. Hour labels now show under **every** column (was every 4th).

## [2.7.4] — 2026-05-26

### Added

- **Recovery Contacts page template on Web Frontend → Templates** — the public `/contactlist` page now has its own card in the Templates list, modelled on the Contact page template and uniform with every other template: a "Directory + form" style card, the shared Customize panel (background / fonts / sizes), and page-level controls for the heading / subheading / Markdown intro plus container width. These appearance settings moved here out of the Forms admin (new `frontend_recovery_contacts_template_save` route; `recovery_contacts` registered as a template kind). The Forms page keeps the form mechanics (visibility, admin alerts + recipient, submit-button label, success message, bot protection) and links up to the new section — and no longer writes the moved fields, so saving it can't clobber them. No schema changes: reuses the existing `recovery_contacts_*` columns + `frontend_template_settings_json`.

### Changed

- **Template Edit modals show a single save bar.** Editing inside a template modal previously surfaced two "Unsaved changes" bars — the global yellow bar pinned to the page *and* a second one in the modal footer. The redundant in-modal bar is gone; modal edits now commit through the one global save bar (`#fe-save-bar`), which already stacks above the modal, batches every dirty section, and keeps the modal open after saving. Inline per-section Save buttons stay hidden inside the modal and a stray Enter routes through the global Save instead of a full-page reload.
- **More breathing room between paragraphs** in the body text of announcement cards on the `/announcements` list (cards view) — `1.1em` paragraph margins, with the first/last paragraph still flush to the card edges.

### Fixed

- **"Contact us" button on the Recovery Contacts page no longer shows an underline on hover.** Being an `<a>` styled as a button, it was inheriting the generic frontend link-hover underline (`.fe-page a:hover`); a higher-specificity rule now suppresses it. (The Contact page's submit is a `<button>`, so it was never affected.)

## [2.7.3] — 2026-05-25

### Added

- **Phone numbers are formatted for display** on the public Recovery Contacts directory + PDF (stored values are untouched). North American numbers are hyphenated — `202-555-0100`, or `1-202-555-0100` with a leading 1 — and numbers carrying any other country code are rendered in that country's standard international style via libphonenumber (e.g. `+44 20 7946 0958`), even when the `+` was omitted. Unparseable/partial numbers show exactly as entered. New dependency: `phonenumbers` (`app/phone.py`, registered as the `phone_fmt` Jinja filter).
- **"Contact us" call-to-action on the Recovery Contacts page** — a divider-topped section showing the Contact page's subheading and a button through to the public contact form. On desktop it sits under the directory cards; on mobile it moves to the bottom of the page, below the form. Only shown when the contact form is enabled.

### Fixed

- **Utility-bar button labels no longer wrap on mobile** — items like "Print List" / "Contact List" stay on one line (the bar is already a horizontal swipe strip), via `white-space: nowrap` on the utility-bar leaf items.

## [2.7.2] — 2026-05-25

### Changed

- **Signed-in admin button renamed to "Return to dashboard"** (was "Back to TS Pro dashboard") across all three mega-menu variants (`classic`, `recovery-blue`, `themed`) and the footer admin block. The admin nav-link editor help text was updated to match.
- **Recovery Contacts form settings** — added a 1 rem gap between the two toggle rows in the "Admin email alerts" section, and clarified the removal-alerts toggle copy to make explicit that the admin is emailed **only after** the person clicks the confirmation link (so you're never asked to remove someone who hasn't confirmed they want off the list — no behaviour change from 2.7.1).

## [2.7.1] — 2026-05-25

### Added — Recovery Contacts: anti-abuse on self-service update/removal

Hardens the public update/removal flow against malicious requests aimed at a listing's owner, and surfaces what it catches in Watchtower.

- **24-hour update rate-limit** — a second update request against the same listing within 24 h is rejected with a "wait 24 hours" message; the second submission's data is **never ingested**, and the attempt is flagged. Tracked via `RecoveryContact.last_update_request_at`. The "I'm updating my existing entry" block now states the once-per-24h limit.
- **"I didn't submit this" link** — every update/removal confirmation email now carries a second link beside the confirm link. Clicking it discards the pending request and **locks the listing against any update/removal request for 7 days** (`RecoveryContact.requests_locked_until`); the confirmation page reports the request was discarded. While locked, both update and removal requests are refused.
- **Watchtower panel + attention chip** — a "Recovery Contacts · flagged requests" panel on the Watchtower **Overview** tab lists each flagged request (rate-limited 2nd update or owner-disavowed) with the requestor's IP, a one-click **Block IP** (reusing the IP blocklist), and **Resolve**. Unresolved flags drive a red attention chip on the Watchtower sidebar quicknav and an anomaly callout. Listings with flags/locks also show **Flagged** / **Locked until …** badges in the Recovery Contacts admin table.
- **Data model** — new `RecoveryContactAbuse` table (kind, targeted listing snapshot, requestor IP, attempt count, lock deadline, resolved state) + a `record_recovery_contact_abuse()` helper that bumps an existing unresolved row instead of duplicating. New `recovery_contact` columns patched in via `_migrate_sqlite()`; the abuse table is created by `db.create_all()`. New audit-log events: `update_rate_limited`, `disavowed`, `request_blocked`.

### Added — Recovery Contacts form & directory refinements

- **"Contact me by email through the site" is on by default**, and is **force-checked + locked** whenever a member hides both their phone and email — so there's always a way to reach them.
- **"Need help?" link** at the foot of the form, pointing to the public `/contact` page.
- The **"available to sponsor"** checkbox now sits below the "contact me by email" option.

### Changed — Recovery Contacts polish

- **Directory cards adopt the Primary card design tokens** (`--fe-color-card-primary-bg/border`, plus the `-dark` variants) and join the shared `.fe-card-primary` shadow/hover aggregator, so they match meeting/submission cards in every theme and dark mode.
- **Pale-green tint** on the "I'm updating my existing entry" block (mirrors the pale-pink removal block); checking **"Remove me from the list"** now greys out and disables every other field except Name + Email.
- **PDF**: contact-only listings (phone + email both hidden) now print **"Contact through the site — <site>/contactlist"** as a clickable link — the visible text drops the `https://` while the link still targets the full `https://` URL.
- Removal-block copy now ends "Use the email from your listing."

### Fixed — Recovery Contacts live search

- Typing in the directory search now actually **hides non-matching cards** until the box is cleared — the card's `display: flex` had been overriding the `[hidden]` attribute, so excluded entries stayed visible.

## [2.7.0] — 2026-05-25

### Added — Recovery Contacts module

A new self-service member directory: visitors add themselves (name + phone + email), pick exactly what shows publicly, and reach each other directly. Public page served at **`/contactlist`**; admin management lives at **TS Pro → Recovery Contacts**; settings live under **Web Frontend → Forms → Recovery Contacts**. Off by default and 404s when disabled, like every other module surface.

- **Public directory + submission form** (`app/frontend.py`, `templates/frontend/recovery_contacts.html`). Two-column layout inside the shared dynbg section so themes + dark mode flow through automatically: the member list (with header chip/title/subheading) on the left, the submission form on the right. Email is required; phone is optional. Entries appear only after an admin approves them.
- **Per-entry display control** — each member chooses to show their phone, email, both, or neither (`show_phone` / `show_email`, surfaced via the `public_phone` / `public_email` model properties). An admin can adjust visibility per row afterward.
- **"Available to sponsor"** opt-in adds a red-heart badge to the listing so members seeking a sponsor can spot them.
- **Private "Contact me" relay** — opting into *Let people contact me by email through the site* adds a **Contact me** button that opens a modal; the message is emailed to the member with **Reply-To set to the sender** so their address is never exposed (`_send_with_reply_to`). Honeypot + Turnstile protected. The backend shows a contact-count chip per member. This box is **checked by default**, and is **forced on + locked** whenever the member hides both phone and email — so there's always a way to reach them.
- **Double opt-in update & removal** — checking *I'm updating my existing entry* or *Remove me from the list* matches the member **by email** and sends a confirmation link. Clicking the link **applies the change automatically** (update overwrites the matched entry; removal deletes it) with **no admin approval** (`/contactlist/confirm/<token>`). Unconfirmed requests still surface to the admin to action manually. The removal block greys out and disables every other field except Name + Email; the update block is tinted pale green, the removal block pale pink.
- **Live search** filters the directory as you type (name / phone / email, plus the keyword **"sponsor"**) and hides non-matching cards until cleared.
- **Branded PDF** of the directory via WeasyPrint at **`/contactlist.pdf`** — honours the active `?q=` filter, stacks the logo over the public URL, centres the title, and downloads as `<Site-Name>-Recovery-Contacts_<yyyymmdd>.pdf`. Listings reachable only through the site (phone + email both hidden) note **"Contact through the site — https://<site>/contactlist"** in place of empty phone/email cells.
- **Admin backend** (`app/routes.py`, `templates/recovery_contacts.html`): pending-review table with per-request match panels (Apply update / Approve as new / Remove / Dismiss), a published table with inline visibility toggles + per-row edit, a **manual add** modal, and an **Activity log** (audit trail) of submissions, email confirmations, relayed contacts, and every admin action — each row carrying the actor (visitor vs named admin), timestamp, and IP.
- **Integrations** — sidebar entry with a pending-count badge, inclusion in the dashboard **Forms** widget, an entry in **Web Frontend → Forms** (`app/forms_registry.py`), and **admin email alerts** (toggleable for new entries and for removals).
- **Data model** (`app/models.py`) — new `RecoveryContact` table (display flags, sponsor/contact opt-ins, contact count, shared confirmation token for update+removal, self-referential `matched_entry_id`) and `RecoveryContactLog` table for the audit log, plus a `log_recovery_contact()` helper. New `recovery_contacts_*` columns on `SiteSetting`. Tables are created by `db.create_all()`; all additive columns are patched in via `_migrate_sqlite()` (race-tolerant for the 2-worker gunicorn setup). Legacy `/phonelist` 302-redirects to `/contactlist`.

### Changed — Directory cards adopt the Primary card design tokens

The Recovery Contacts list cards now read surface + border from the Primary card tokens (`--fe-color-card-primary-bg` / `--fe-color-card-primary-border`, with the `-dark` variants) and join the shared `.fe-card-primary` shadow/hover/transition aggregator, so they match meeting/submission cards in every theme and dark mode.

## [2.6.1] — 2026-05-24

### Added — Neobrutal theme

A seventh frontend theme: **neobrutalism** — colourful flat surfaces (yellow / pink / cyan / lime), thick black borders, hard offset drop-shadows (no blur), chunky Archivo Black headings, and controls that "press" on click (translate + shadow shrink). Styles every region — header, mega menu, homepage, footer, list/detail pages — in both light and dark; in dark mode the canvas goes near-black while the bright blocks stay colourful with their text pinned to ink for legibility (`app/static/css/themes/neobrutal.css`).

- **Geometric hero backdrop** — a faint graph grid plus bold black-outlined shapes (circles + a tilted square) scattered to the corners, drawn entirely in CSS on the hero's `::before` / `::after`.
- **Randomised on each load** — `neobrutal_hero_css_vars(site)` (`app/design.py`, registered as a Jinja global and injected onto `<body>` in `frontend/base.html`) emits fresh random positions per request, so the primitives re-scatter on every refresh. Each shape roams a generous region within its own corner so the centred headline always stays clear; the square's rotation randomises too. No JavaScript — server-rendered, so no flash.
- Newly vendored font: **Archivo Black** (`app/static/fonts/archivo-black/`). Registered in the font catalog + theme registries (`fonts.py`, `frontend.py`) with full design tokens (`design.py`, default light mode).

### Fixed

- Neobrutal footer location cards no longer darken to near-black on hover (the shared force-dark hover rule was burying the black card text) — the hover now re-asserts the bright surface; its feedback is the lift + larger hard shadow.

## [2.6.0] — 2026-05-24

### Added — Four new frontend themes (Modern Dark, Cyberpunk, Sanctuary, Terminal)

Beyond Classic and Recovery Blue, the Web Frontend now ships four complete themes, each styling every public region — header, mega menu, homepage, footer, and all list/detail pages — in both light and dark mode:

- **Modern Dark** — deep-indigo "mission control" canvas with a diffuse aurora, film grain, teal→cyan gradient buttons, Fraunces display over Inter.
- **Cyberpunk** — near-black neon-grid HUD with scanlines, cyan/magenta, sharp zero-radius edges, and Orbitron/Chakra Petch type.
- **Sanctuary** — warm sand/cream canvas, sage-green + clay accents, Lora humanist serif, soft rounded cards.
- **Terminal** — utilitarian command line: phosphor-green on near-black, all-monospace, flat boxy panels, prompt-prefixed headings + a blinking cursor.

Themes apply non-destructively via theme-scoped CSS (`app/static/css/themes/<key>.css`) loaded only for the active theme — switching never rewrites page/block content. Shared `frontend/headers/themed.html` + `frontend/megamenus/themed.html` partials drive every alternate theme. Newly vendored fonts: Orbitron, Chakra Petch, Lora.

### Added — Per-theme saved state

Switching themes auto-saves the outgoing theme's appearance fields (design tokens, fonts, default mode, per-template settings, mega-menu colours) into the new `SiteSetting.frontend_theme_states_json` and restores the incoming theme's last state, so returning to a theme brings it back exactly as left. The theme switcher modal gained a **When applying** chooser — *Return to last saved state* / *Reset to default* — pinned as a fixed band so it and the Apply button stay visible as the theme grid scrolls.

### Added — Mega-menu dynamic backgrounds, dark-mode colours, and blend

- **Dynamic background** picker for the mega-menu panel (the same `dynbg` system the hero/pages use), rendered behind the links via an `fe-dynbg-host` panel and clipped to its rounded corners.
- **Render dark in light mode** toggle — forces the dynbg's dark variant in light mode so a dark panel sits behind light text.
- **Independent light/dark colour pickers** — separate background + text colours per mode.
- **Background ↔ dynamic blend** slider — the dynbg layer's opacity over the solid colour (0 = colour only, 100 = dynbg only).
- Mega-menu **headings, links, and buttons** (including the admin "Back to TS Pro dashboard" button) now obey the configured Text colour; the Logout pill keeps its distinct amber. Dark mode auto-lightens the text colour for legibility.

New additive `SiteSetting` columns (all via `_migrate_sqlite`): `frontend_mega_bg_dynamic_key`, `frontend_mega_bg_dynbg_config_json`, `frontend_mega_bg_dynbg_dark`, `frontend_mega_bg_color_dark`, `frontend_mega_text_color_dark`, `frontend_mega_bg_dynbg_blend`.

### Added — "Text — Darkmode" design token

A new Colors token controls dark-mode text site-wide: anywhere the **Text** token is used, this value takes over in dark mode (body, headings, card/event titles, page-builder content). Hardcoded neutral dark-text colours (`#e2e8f0` / `#f1f5f9` / `#cbd5e1`) are routed through a `--fe-text-dark-active` channel defined only in dark mode, so light mode is untouched.

### Changed — Recovery Blue: frosted-glass header + footer cards

The Recovery Blue header is now a translucent frosted-glass bar (`backdrop-filter: blur + saturate`), and the footer location cards use a light frosted-glass surface — both light and dark. The desktop nav no longer draws a dark navy box behind its links (scoped to the mobile dropdown).

### Fixed — Dark-mode token connections + Modern Dark polish

- Hardcoded recovery-blue dark values now resolve through the active theme's dark tokens: card hover borders → `--fe-dm-border-hover`, the Files & Readings panel + events/announcements active tab + section dividers + meeting-type badges.
- The derived dark primary-button colour is re-resolved on `<body>` so it tracks the theme instead of falling back to blue.
- Themed-header nav links default to the dark-mode text colour (no more dark-on-dark).
- Modern Dark: fresh teal/violet hero scene (dropping leftover recovery-blue particles), rebuilt footer, and removed the white box around the "What is CMA" / "Additional Resources" sections in light mode.
- The Design page's per-token **Reset** now dispatches input/change events so the unsaved-changes save bar appears.

### Backup

Every new frontend setting scopes into the frontend export/import automatically (the field list is prefix-derived from `SiteSetting` columns); the `color_text_dark` token rides inside the exported `frontend_design_json`.

## [2.5.1] — 2026-05-23

### Changed — "Powered by" footer block links to gettspro.com

The footer builder's **Powered by** attribution block now links to `https://gettspro.com` instead of the project's GitHub repo (`templates/frontend/footers/blocks/_powered_by.html`). The block's description in the footer builder palette was updated to match (`app/frontend.py`).

## [2.5.0] — 2026-05-22

### Added — Popups: site-wide modal popups built with the page builder

A new **Popups** section under **Web Frontend → Content** lets admins author modal popups using the same drag-and-drop block builder as content pages, fired from `#name` anchor selectors anywhere on the public site.

- **New `Popup` model** (`app/models.py`) — `name` (the trigger handle / `#` selector, unique + slugified), `title`, `blocks_json` (same section/block schema as `Page`), an `is_enabled` toggle, plus the popup's own chrome: `width` + `max_width_pct`, `height_mode` (auto/fixed) + `height`, `padding`, `bg_color` (+ optional `bg_color_dark`), `border_radius`, `shadow`, overlay (`overlay_enabled` / `overlay_color` / `overlay_opacity`), `position` (centre/top/bottom), per-device visibility (`show_desktop` / `show_mobile` / `mobile_full_width`), and behaviour (`close_on_overlay`, `show_close_button`, `auto_open` + `auto_open_delay`). The new table is created by `db.create_all()` on upgrade — no migration needed.
- **Admin CRUD** (`app/routes.py`): list / create / edit / save / enable-disable / delete under `/tspro/frontend/popups`, plus a **Popups** entry in the Web Frontend subnav (`_frontend_subnav.html`).
- **Builder reuses the page builder verbatim** — the editor renders the shared structure card with draggable block pills, the blue "Add block" floating palette, and the BlockEditor modal, driven by the same `page_structure.js` and `_frontend_structure_card.html` macros content pages use. `block_editor.js` gained an optional `allowedTypes` mount option so the popup palette is scoped to content blocks (the homepage-section blocks — hero / meetings / events / features / faq — and the wiki TOC are excluded).
- **Triggers** (`templates/frontend/_popups.html`, included site-wide in `frontend/base.html`): any link to `#name`, any element with `data-popup="name"`, and a matching URL hash on load / `hashchange` open the popup; it closes via the × button, a backdrop click (when enabled), or Escape. Popups are surfaced to every public template by a `frontend` blueprint context processor; content renders through the shared `render_sections` macro so popups inherit every block style the site already ships.
- **Editor-only preview** route (`/_preview/popup/<id>`) force-opens a popup on a neutral page so admins can preview drafts before enabling them.

### Fixed — Public homepage no longer 500s when no homepage is configured

`frontend/page.html` built its page-shell inline style from `page.*` even in `index()`'s no-homepage fallback (which renders with `page=None`), so the public `/` returned a 500 (`'None' has no attribute 'pad_top'`) during the brief pre-seed window on a fresh install or if the designated homepage page was deleted. The template now guards every `page.*` access and renders a friendly "no homepage configured yet" placeholder (with a *Set a homepage in Pages* shortcut for signed-in editors) instead of crashing.

## [2.4.0] — 2026-05-21

### Added — Live meeting bar updates without a page refresh

The utility-bar "LIVE: <meeting>" badge now appears, updates, and clears on its own as online/hybrid meetings open and close — visitors no longer have to reload to see it.

- **New endpoint** `GET /api/live-meeting` (`app/frontend.py`) returns the current live-meeting state as JSON (`{"live": …, "name": …, "join_url": …}`), reusing the exact `current_live_meeting()` logic the server render uses so a poll always matches a refresh. Public, gated on the admin's live-badge toggle, uncached.
- **Poller in the utility bar** (`_utility_bar.html`) fetches that endpoint every 30s (and on tab refocus) and updates the bar in place: inserts/updates/clears the LIVE badge + Join CTA and toggles the bar's `is-live` styling (clearing the idle inline colours so the yellow shows). The server-rendered state still paints the correct bar on first load; the poller just keeps it fresh. When a site uses the badge but has no other bar items, the bar is rendered `hidden` so the poller has a target and reveals it only when a meeting is live.
- **Container collapse is now CSS-driven.** Containers with a `collapsed_icon` (e.g. a Helpline pill) always emit both the collapsed icon and the full container; which one shows is decided by the bar's `.is-live` class + viewport. This fixes the collapse so it works whether the bar was rendered live OR flipped live by the poller (previously the collapse was gated on the server-render live state and didn't trigger on the dynamic path).

## [2.3.3] — 2026-05-21

### Changed — Web Frontend quick-nav visible to non-admins (read-only)

The sidebar Web/View quick-nav previously rendered only for admins. Signed-in non-admins (viewer / editor / intergroup_member) now see it too when the Web Frontend module is enabled:

- **Web** renders as a non-clickable status indicator (a `<span aria-disabled="true">`, not a link) that still shows the live dot — so non-admins can see at a glance whether the public site is live, but can't open the admin panel they aren't authorized for. The icon/label are muted to read as a status chip; the live dot keeps full strength.
- **View** opens the public site in a new tab — shown to non-admins when the site is live (admins keep it always, since they get the editor preview even while the public toggle is off, and a non-admin would otherwise be bounced straight back).
- Admins are unaffected: clickable Web link + View + Watchtower as before. A lone Web button (non-admin, site off) spans the full quick-nav width.

## [2.3.2] — 2026-05-21

### Fixed — Redirects match with or without a trailing slash

The redirect handler (`_url_redirect_handler`) matched the incoming path against `UrlRedirect.source_path` exactly, so a rule stored as `/donate` 404'd for visitors hitting `/donate/` (and vice versa). The lookup now checks both slash variants in a single indexed query (`source_path IN ('/donate', '/donate/')`), preferring an exact match when both a slashed and unslashed rule exist. Root `/` is matched as-is. Still one query per request, so no added per-request cost.

## [2.3.1] — 2026-05-21

### Fixed — Dark-mode form & contact-page text contrast

Several frontend form surfaces rendered text in near-black against a dark background in dark mode.

- **Submission / story form labels + legends** (`.fe-submission-form label` / `fieldset legend`): these carry an explicit light-mode colour (`var(--fe-color-text)`) that overrode the card's inherited dark-mode text colour, so on the dark submission card (`/submissionform`, `/storyform`, submission modals) every field label and the fieldset legend were nearly invisible. Flipped to the dark-mode text tokens (`--fe-dm-text` / `--fe-dm-text-strong`).
- **Contact card stayed white in dark mode**: its dark override referenced `var(--fe-color-surface, #111827)`, but the design token is defined (light) and never flipped, so the fallback never applied — leaving a white card (with dark inputs) on the dark page. Now uses the real dark surface tokens (`--fe-dm-surface` / `--fe-dm-border`) plus a light base text colour, mirroring `.fe-submission-card`. The contact form's own labels now follow the same dark-mode rule (the earlier `:not(.fe-contact-form)` carve-out was removed once the card itself went dark).
- **Contact aside text** (`.fe-contact-title` "Get in touch", `.fe-contact-intro`, the public-information-chair name and other channel values, and channel labels) sits on the dark page rather than the card and had no dark override, so it rendered near-black. Lifted the heading to `--fe-dm-text-strong`, intro/values to `--fe-dm-text`, and labels to `--fe-dm-text-muted`.

Verified with a headless browser in dark mode: `/submissionform` and `/contact` now render all labels, headings, and contact values at readable contrast against their dark surfaces.

## [2.3.0] — 2026-05-21

### Added — Frontend image & asset caching control panel

A new **Web Frontend → Setup → Caching** admin page that makes returning visitors stop re-downloading images on every page view, while keeping changes instant.

- **Root cause fixed**: the `_security_headers` after-request hook forced `Cache-Control: no-store` on every path except `/static/` and `/pub/`, *overwriting* the `max-age` that image routes (`/story-image`, `/blog-image`, `/post-gallery-image`, `/site-branding/*`, …) set themselves. So most frontend images were re-fetched on every visit. Caching is now centralized in `app/imgcache.py::apply_cache_headers`, wired into the same hook (it owns image/static responses; everything else still gets `no-store`).
- **Cache-busting without template surgery**: a `?v=<token>` is auto-appended to all ~121 image URLs and every `/static` URL via Flask's `url_defaults` hook (`imgcache.inject_bust`) — no per-call-site edits. Images use a monotonic `SiteSetting.media_cache_version` token (read live, request-cached in `g`); `/static` uses `version.__build_id__` (a content hash of the `app/` tree), so each deploy busts CSS/JS/fonts automatically.
- **Instant freshness on change**: `imgcache.note_image_change()` advances the version token whenever an image is uploaded/replaced. Wired into the central `_save_upload` (image extensions only) plus the three direct-`.save()` image routes (custom icon, page background, brand logo). A change → new URL → immediate refetch; unchanged images stay cached for the full lifetime with zero requests.
- **The panel** (`frontend_caching.html`): master image-caching toggle, cache lifetime (1h–1yr presets, default 7 days), auto-refresh-on-change toggle, `immutable` toggle; a separate static-assets toggle + lifetime (default 30 days); and a Maintenance card showing cache version, last-cleared time, and on-disk thumbnail count/size, with **Clear image cache now** (bumps the token for all visitors) and **Rebuild thumbnails** (deletes generated `_thumb_` files, regenerated lazily) actions.
- **Admin-uploaded fonts** (the `site_custom_font_asset` route) are cached aggressively too, but treated as self-busting (their URLs embed a UUID filename) so they don't churn on the image token.
- **Schema**: 8 additive `media_cache_*` columns on `SiteSetting` (enabled, max-age, immutable, static toggle + max-age, autobump, version, cleared-at), with matching `_migrate_sqlite` entries. Defaults: image + static caching **on**.
- **Untouched**: HTML pages, API/JSON, admin pages, and document downloads stay `no-store` / Flask defaults, so dynamic surfaces like the live-meeting utility bar remain per-request fresh. Verified end-to-end with a headless browser against sandboxed copies of the DB (migration on real data; static `public, max-age=2592000, immutable` + build-id token; image `public, max-age=604800, immutable` + version token; toggle-off → `no-store`; upload/clear bump the token immediately).

## [2.2.2] — 2026-05-21

### Fixed — Frontend export now carries per-page OG overrides + story dates

The scoped frontend bundle serialises `Page` / `Story` rows with explicit field lists that had drifted from the models, silently dropping two admin-editable, public-facing fields on export/import:

- **`Page.og_title` / `og_description` / `og_image_filename`** — per-page Open Graph (social-share) overrides set in the page editor. The OG image is now also collected so it ships in the bundle's `assets/`.
- **`Story.published_at`** — the public "posted on" timestamp; without it, imported stories reset their date to the import time.

Both are now exported and restored. Bundle `format_version` bumped 4 → 5; older bundles still import (the new fields fall back to model defaults). Also corrected the asset-collection comment to match actual behaviour (every ref is kept; the zip step skips names with no file on disk, so regex false-positives never ship and real refs never drop) and simplified the now-redundant `final_assets` loop. Verified with an isolated export → fresh-install import round-trip: pages (incl. OG), stories (incl. `published_at`), settings, and referenced assets reproduce verbatim. The whole-site export was already drift-proof (full DB via `VACUUM INTO`).

### Changed — Dashboard + sidebar polish

- **Dashboard drag handles**: the three macro opt-out widgets (Your role / server metrics, Currently online, Access requests) rendered their handle as an absolute top-left chip, a different size/offset/position from every other widget. They now render the handle inline at the start of their own title row (`.dash-drag-handle--in-head`), reproducing the macro handle exactly (in-flow, 22px brand grip). Removed the dead "inset for absolute chip" padding rules.
- **Sidebar**: Watchtower quicknav icon bumped to 16px (Web/View stay 14px); Notifications & Search button gap tightened 10px → 8px; the Web button's live-status dot now reuses the Currently-online widget's emerald pulsing ping to signal "frontend module enabled and public".

## [2.2.1] — 2026-05-20

### Changed — Footer builder converged onto the page block builder

The Footer admin now uses the same inline structure-builder flow as content pages, replacing its bespoke form + separate layout-builder modal.

- **Inline structure card** (`frontend_footer.html`): footer blocks arrange into drag-drop rows/columns (Sortable), click-to-edit pills opening the existing per-type content modals, an "Add block" palette + "Add row" (1–4 col) controls, and a **sticky save bar** in place of the "Save Footer" button. All block editors render unconditionally now (any block addable from the palette).
- **Self-contained `footer_builder.js`** owns the drag/palette/remove/save-bar and serialises the arrangement into a hidden `footer_layout_json` (rows/columns of block types) — **no changes to the shared page-builder JS or macros**, so the page editor is untouched.
- **Save** (`frontend_footer_save`): the posted arrangement upserts the active footer `CustomLayout` (promoting a prebuilt to an editable custom layout when needed); block **content** still saves via the unchanged `parse_footer`. **Public render is unchanged** — `_custom.html` + the 11 footer block partials already consume `CustomLayout` rows + the content dict, so live footers are byte-identical until edited.
- **Converters** (`blocks.py`): added lossless `footer_blocks_from_content` / `footer_content_from_blocks` / `footer_layout_to_blocks` / `footer_blocks_to_layout_rows` (round-trip tested) bridging the content dict, the block-list, and layout rows.

## [2.2.0] — 2026-05-20

### Added — Preview frontend pages (and homepage) before publishing

An editor-only preview surface for content pages and the homepage, so changes can be checked before they go live.

- **Preview route:** ``frontend.page_preview`` (``/_preview/page/<id>``, GET + POST) renders a Page through the same pipeline as the public site, gated to signed-in frontend editors (``can_edit_frontend``) — never the public. **GET** renders the saved content (so DRAFT/unpublished pages, which ``page_detail`` hides even from editors, can finally be previewed); **POST** renders the ``blocks_json`` posted from the structure editor — the current *unsaved* edits — with page-level settings (background, layout, SEO) taken from the saved row.
- **Shared render path:** extracted ``frontend._render_page(page, site, sections=…, preview=…, unsaved=…)`` from the duplicated tails of ``index`` and ``page_detail`` (TOC, lottie detection, meetings/events hydration, OG tags, context); all three now render through it, so the preview is byte-for-byte the public render.
- **Editor button:** a **Preview ↗** action in the page editor builds the live block JSON via ``new FormData(form)`` (firing the editor's existing serialize hook) and POSTs it to the preview route in a new tab — no save required.
- **Pages list:** a **Preview** link per row (works for drafts).
- **Banner:** ``frontend/page.html`` shows a fixed preview banner (only when ``preview_mode``) with accurate wording for unsaved-changes / draft / plain-preview.
- No schema change and no change to save/publish semantics — purely additive (the live page already only changes on Save).

## [2.1.35] — 2026-05-20

### Added — WordPress importer: universal custom-field mapping

A new **Map fields** wizard step (step 3 of 5) discovers the custom fields present on the connected site and maps them, per post type, onto destination columns.

- **Discovery:** ``wp_importer.discover_fields`` aggregates every scalar custom field across the fetched posts (from the already-captured flattened ``acf`` payload) with sample values + post counts.
- **Registry:** ``TARGET_FIELDS`` is the single extension point — per-target destination fields (key, label, type, aliases). Adding a future post type is one entry here plus a row-construction branch.
- **Suggestion:** ``suggest_mapping`` pre-fills smart defaults from field-name detection (reusing the legacy alias table + date-field aliases); the admin overrides any of them.
- **Apply:** ``_extract_target_fields`` resolves each target's mapping with type coercion (text/url/datetime/date/bool — incl. an ``YYYYMMDD`` date→datetime fix), applied to **all** post types (events/announcements, stories, blog) — previously only events/announcements got custom-field mapping. Falls back to the legacy alias auto-detect when no mapping exists.
- **Saved per site:** new ``WpFieldMapping`` table (keyed by host, sentinel ``csv`` for uploads) remembers the last mapping so re-imports auto-load it. New route ``wp_import_fields`` + ``wp_import_fields.html``.

### Added — Chunked import for large WordPress sites

The 500-post fetch cap is removed and the commit runs in batches so large sites can't hit the request timeout.

- ``MAX_FETCH_POSTS`` (3,000) ceilings the single connect fetch; the connect step warns when the ceiling is hit.
- ``COMMIT_CHUNK_SIZE`` (200) bounds each commit request. The dry-run commit now processes one chunk per request, accumulating counts/warnings in the stash and rendering an auto-advancing ``wp_import_progress.html`` (progress bar, running counts, pause/stop) until done. Slug uniqueness stays correct across chunks (each batch re-reads existing rows). Small sites (≤ chunk size) commit in one pass as before.
- ``apply_plan`` gains ``count_inline``; the dry-run preview skips per-post inline-image counting on large sets (> 400 posts) to stay responsive.

### Changed — dry-run "Ready to import" is a sticky footer

The confirm block is no longer a ``.card``/``.data-card`` — it's a full-bleed sticky footer bar (``.wp-confirm-bar``) anchored to the bottom of the wizard modal, so the IMPORT field + Run-import button stay reachable while scrolling the preview. Shows the batch count for chunked imports.

## [2.1.34] — 2026-05-20

### Added — Notifications Center

A sidebar **Notifications** button (with a live uncleared-count chip) that opens a popup modal of everything needing the user's attention; each item deep-links to its section and can be cleared individually or all at once.

- **Derived, not event-sourced.** ``app/notifications.py`` walks the same attention sources the sidebar badges use (pending access requests, locked accounts, unread contact messages, posts/stories awaiting review) and turns each into a notification keyed by a stable string (``access_request:42``, ``locked_account:jdoe`` …). The only thing persisted is each user's *dismissals* — new ``NotificationDismissal`` table (auto-created by ``db.create_all``). "Uncleared" = current attention items minus dismissals; a dismissal whose item resolves is pruned so a recurring key resurfaces. No event plumbing to maintain, nothing to go stale.
- **Role-scoped.** Admins see access/security/contact items; editors and up see submissions awaiting review (gated by the relevant module being on). Viewers get no button.
- **Endpoints.** ``GET /tspro/notifications`` (HTML fragment), ``POST /tspro/notifications/clear`` (one key), ``POST /tspro/notifications/clear-all`` — the clear endpoints return the new count so the chip updates live. ``notifications_count`` is injected via the existing context processor.
- **UI.** Sidebar button mirrors the Search button chrome with a ``nav-badge`` chip; ``_notifications_modal.html`` (self-contained markup + JS, fetches the list on open) and ``_notifications_list.html`` fragment; ``.notif-*`` styles in ``app.css``. The modal is included before ``app.js`` so its ``data-close`` / ``data-open-modal`` handlers bind at init (guarded with ``is_authenticated`` since that spot also renders on the login page).

### Fixed — sidebar quicknav spacing

The sidebar is a flex column (margins don't collapse), so ``.sidebar-quicknav``'s bottom margin stacked with the Notifications button's top margin into a 14px gap. Dropped the quicknav bottom margin so quicknav → Notifications → Search share a uniform 8px rhythm.

## [2.1.33] — 2026-05-20

### Added — Watchtower 404s tab

A new ``/tspro/watchtower/not-found`` tab surfacing the public-site 404s visitors hit.

- **Model:** new ``NotFoundEvent`` table (created via ``db.create_all`` — no ``_migrate_sqlite`` entry needed for a new table). Stores ``created_at``/``day``, ``path``, the full ``referrer`` (kept in full — for internal broken links the referrer is our own site, which ``VisitorEvent`` deliberately discards) plus ``referrer_host``, parsed device/browser/os, and a daily-rotating ``visitor_hash``.
- **Recording:** ``visitor_metrics.record_404`` reuses the existing bot/asset/UA/hash helpers; called from the global 404 errorhandler in ``app/__init__.py`` only on the public-frontend branch (admin ``/tspro`` paths and signed-in users are excluded). Fully defensive — a logging failure can never turn a 404 into a 500.
- **Aggregation:** ``watchtower.py`` gains ``not_found_summary`` / ``not_found_daily`` / ``top_missing_paths`` / ``top_404_referrers`` / ``recent_404s`` / ``clear_404s``.
- **UI:** ``watchtower/not_found.html`` mirrors the Visitors tab (KPI tiles, amber trend chart, two ranked lists, recent-hits table) with a window selector and a Clear-log action. Tab added to ``watchtower/_tabs.html``; ``_ENDPOINT_LABELS`` entry added.

### Added — GSR Summary modal

The utility-bar **GSR** button now opens the GSR Summary in a modal instead of linking to ``/announcements#gsr``.

- **Shared partial:** the GSR "paper" markup was extracted from ``announcements_list/omni.html`` into ``frontend/_gsr_summary.html``, included by both the announcements page and the modal so they never drift.
- **Fragment endpoint:** ``GET /announcements/gsr-summary`` renders just that partial. The announcements query was refactored into ``frontend._active_announcements`` and is shared by the list route and the fragment. The GSR button is global but the data only lives here, so the modal fetches the fragment on first open.
- **Modal:** self-contained ``frontend/_gsr_modal.html`` (markup + style + JS, like ``_lightbox.html``), included once in ``frontend/base.html``. Centred popup on desktop; full-screen sheet covering the header on mobile (≤540px, z-index 1300 > header). Footer "Go to Announcements" button; close via X / backdrop / Esc; body scroll-lock. The GSR button keeps its ``/announcements#gsr`` href as a no-JS fallback (``data-fe-gsr-trigger``).
- **Surface:** the modal is one uniform card surface (``--fe-panel`` / ``--fe-dm-surface``); inside the modal the paper drops its sheet background + shadow (override scoped to ``.fe-gsr-modal`` and theme-qualified so it beats the shared dark paper rule), keeping only the typography.

### Changed — Utility-bar live collapse is desktop-only

When the live-meeting bar is active, a container with a ``collapsed_icon`` collapsed to its icon on every viewport. It now collapses **only on desktop** (to free centre room for the LIVE banner); at ≤720px — where the bar is a horizontal swipe strip — the full container is shown instead. ``_utility_bar.html`` emits both variants and ``frontend.css`` shows the right one per width (``.fe-utility-container--live-expanded``).

## [2.1.32] — 2026-05-20

### Added — "What's New" release-notes dashboard widget

A new dashboard widget (key ``release-notes``) renders the latest release note plus a compact history of the previous three versions, with a CTA into Settings → About.

- **Data source:** reuses ``app/about_docs.py::load_release_notes`` (exposed as the ``app_release_notes()`` Jinja global) — the same parsed ``RELEASE_NOTES.md`` the About tab reads, so the widget adds no new data plumbing.
- **Template:** rendered in ``templates/index.html`` via the existing ``dash_widget`` macro (``sparkles`` head icon, title "What's New"). Leads with a brand-tinted hero panel for the latest entry (version + ``Latest`` pill + date + headline + rendered Markdown body, clamped with a soft ``mask-image`` fade), followed by an "Earlier releases" list and a right-aligned **View all release notes** CTA.
- **Deep link:** the CTA is an ``<a data-open-modal="settings-modal" data-settings-tab="about">`` — it reuses the existing ``app.js`` handler that opens the Settings modal and activates a named tab, so it lands on Settings → About with the release-notes list expanded.
- **Per-user toggle + ordering:** new ``User.dash_show_release_notes`` column (default ``True``, all roles) with a matching ``_migrate_sqlite`` entry; ``release-notes`` registered in ``DASHBOARD_WIDGET_KEYS`` (after ``trusted-servants``) so it joins drag-reorder and the Customize modal. Persisted in ``/dashboard/customize``.
- **Styling:** new ``.dash-relnotes-*`` rules in ``app.css`` — theme-aware via ``color-mix`` against ``--brand``; the CTA sits ``align-self: flex-end`` (content-width, right-aligned).

## [2.1.31] — 2026-05-20

### Changed — Frontend → Templates page index polish

Follow-up refinements to the 2.1.29 list-of-modals refactor:

- **Active-template pill** now renders the brand colour at 18% opacity (``color-mix(in srgb, var(--brand) 18%, transparent)``) with brand-coloured text, instead of the neutral panel fill.
- **(/url) suffix** in each row title is split into its own pill chip styled like a secondary (outline) button — transparent fill, neutral border, monospace URL text.
- **Sort A→Z / Z→A toggle** moved to the far right of the toolbar (``justify-content: flex-end``).
- **1rem gap** between the stacked elements inside each index card and between cards in the list.
- **Index rows** now match the standard backend ``.card`` chrome (same border, ``var(--radius)``, ``var(--shadow)``) — the frontend-style hover lift / brand-border treatment is dropped.

### Fixed — Templates page card flash + stray collapse carrot

- The first-paint hide rule that keeps template cards invisible until the JS lifts them into modals lived in a ``<style>`` at the bottom of the content block, so the cards (and one stray modal section) briefly flashed before the rule was parsed. Moved the critical ``visibility: hidden`` rule to the top of the content block so it applies from the first paint.
- The global ``feCollapsibleCards()`` helper (which adds a chevron toggle to every ``.card`` in ``.fe-admin-main`` across FE-admin pages) was decorating cards on the Templates page too. Added a ``data-no-collapse`` opt-out — the helper early-returns for those cards and the index JS strips any chevron / collapsed state from cards as they're lifted into modals.

### Removed — "Reusable templates" intro card

The standalone intro card is gone; its explanatory copy now lives in the Templates page title's ``?`` tooltip (``heading_help``) so the legend is available without consuming a card slot.

## [2.1.30] — 2026-05-20

### Fixed — Frontend → Templates per-template modal layout

Per-template modals on the Frontend → Templates page now reflow cleanly. The customize-panel fieldset grid (Background / Fonts / Sidebar widgets / Sizes) used to inherit ``grid-template-columns: repeat(auto-fit, minmax(240px, 1fr))`` from the standalone page; inside the narrower modal width that squeezed all four fieldsets into a single row, and their heavy ``.fieldset { padding: 2rem; gap: 2rem }`` chrome overflowed into neighbours. Inside ``.modal.tpl-modal`` the grid is now capped at two columns (single column under 720px), fieldset padding is trimmed to ``1rem 1.25rem`` with ``gap: .75rem``, and the picker thumbnail grid is tightened to ``minmax(180px, 1fr)`` so wide thumbs don't push the modal body past its parent panel.

Section content inside each modal also reflows as a vertical flex stack with a 1.25rem gap so the picker form, the customize ``<details>``, and any follow-up settings form don't sit flush or appear to overlap.

## [2.1.29] — 2026-05-20

### Added — Announcement / event post galleries

Posts grow an image gallery (up to 6 images) that renders in a 3-column grid alongside the featured image on the public detail page with a click-to-zoom lightbox.

- **Model**: new ``Post.gallery_json`` (JSON list of stored filenames); ``Post.gallery_filenames`` property decodes, validates, and tail-truncates to 6. ``_cleanup_retired_asset`` reference-counts the new column via a JSON-content scan so an image referenced by another post's gallery survives a delete.
- **Admin** (``post_edit.html``): new Gallery card after the Featured image card with a thumbnail grid (auto-fill 120px min, ``object-fit: cover``), per-tile remove, multi-select upload, and File Browser picker. The picker opens in a new multi-select mode (``?multi=1``) — sticky bottom bar tallies selected items and posts them in one batch. Server save handler rebuilds the gallery list from three parallel streams (kept-existing, new uploads, picked media-ids) and routes removed files through ``_cleanup_retired_asset``.
- **Public route**: ``GET /post-gallery-image/<pid>/<idx>`` (public blueprint) with ``?thumb=<size>`` (120/240/400/720/1080) via the existing ``thumbnails.ensure_thumb`` helper. Cached thumbs ship with ``Cache-Control: public, max-age=86400`` and clean up automatically when the source retires.
- **Frontend**: shared ``frontend/events/_gallery.html`` partial included by all four event detail templates (classic, minimal, poster, timeline). 3-column grid with responsive ``srcset`` (240w / 400w / 720w). Width matches the featured image per template — inside ``.fe-event-detail-cover-col`` and ``.fe-event-time-main`` for the templates with an inline featured image; capped at ``max-width: 480px`` centred for poster + minimal. Uses the existing ``_lightbox.html`` partial via the ``data-lightbox-scope`` convention.

### Added — File Browser multi-select picker mode

The File Browser modal grows a ``?multi=1`` opt-in for batch selection — used by the post gallery picker, available to any future caller that wants to grab several files in one trip.

- New ``picker_multi`` flag on the route + a ``data-media-multi-bar`` sticky bottom action bar inside ``media.html`` with running count, Clear, and Add N items.
- Per-item Select clicks toggle into a running ``selected`` Set instead of immediately posting; the host card / row flips into a brand-tinted ``is-selected`` state with the button label flipping to "Selected ✓".
- ``Add N items`` button posts a single ``media-selected-batch`` ``postMessage`` back with the full items array.

### Fixed — File Browser list-view Select did nothing

The picker iframe's ``.media-select`` click handler walked up the DOM via ``closest('.media-card')`` to fetch the data attributes — that selector only matched grid cards. List-view rows are ``<tr>`` with the same ``data-media-id`` / ``data-stored`` / ``data-original`` attributes but no ``.media-card`` ancestor, so ``closest`` returned null and the click no-op'd. Switched to ``closest('[data-media-id]')`` so both views hit the same code path.

### Changed — Frontend → Templates page is now a sortable index of modals

The Templates page used to render every template-type configurator (Meetings list, Events list, Story detail, etc.) as a long stack of cards. Refactored into a sortable index of rows with per-template modals:

- All 16+ ``<section class="card fe-tplgrid-section">`` blocks are auto-discovered by JS and lifted into modal shells; an Edit button per row opens the matching modal.
- An A→Z / Z→A sort toggle above the list (default A→Z) persists per browser via localStorage.
- Forms inside each modal use the yellow save-bar pattern: dirty triggers the bar, the bar's Save button POSTs every dirty form via fetch, animates "Saved" with the existing ``fe-save-leave`` keyframe, then resets — the modal stays open until the operator clicks the X.
- Inline primary Save buttons inside each section are hidden in the modal so the save bar is the canonical commit affordance.

## [2.1.28] — 2026-05-19

### Added — Trailing-slash tolerance app-wide

Flipped ``app.url_map.strict_slashes = False`` in ``create_app`` so any route resolves with or without a trailing slash. External links / typos like ``/contact/`` now reach the same handler as ``/contact``; previously Werkzeug 404'd on the mismatched form depending on how the route was declared.

### Changed — Form-builder field cards expand on whole-card click + 200ms animation

The custom-form (and per-module form) field builder used to require clicking a dedicated Edit button to expand a field card. Replaced with a whole-card click target: ``data-field-edit`` button removed; clicking anywhere on a card (except the drag handle, delete button, or a raw input/select/textarea/button/link) toggles the body. Each card gets a chevron indicator on the right that rotates 180° on open. The body now animates open/close over 200ms via ``max-height`` + ``opacity`` + ``padding`` + ``border-top-width`` transitions on the ``is-open`` class.

### Changed — Module form list pages get a Manage form button

Stories, Announcements & Events, and Contact Form admin list pages now carry a **Manage form** button (settings icon) in the top action area linking to the matching form's settings page.

### Changed — Templates page section cards remember collapsed state

Every ``<section class="card">`` on ``/tspro/frontend/templates`` starts collapsed by default and persists per-card expansion state in localStorage. Heading is the clickable toggle; chevron indicator rotates on open. *(Superseded by the 2.1.29 index-of-modals refactor.)*

### Changed — Posts admin defaults to Posted newest-first; sort persisted

``/tspro/announcementsevents`` default sort is now ``posted_desc`` (newest at top by Posted date) for the active / drafts / archived tabs (pending keeps its ``submitted_desc`` default). The chosen sort persists per browser via the ``view-posts-sort`` cookie.

### Changed — Forms widget pending counts replace lifetime totals

Dashboard Forms widget rows used to show ``{subtitle} · {total} submissions · last {date}``. The total is redundant with the attention badge on the right; subhead now reads just the unreviewed count ("3 pending review") and falls back to "all caught up" when nothing's waiting on the admin.

### Changed — "Form Submissions" sidebar → "Custom Form Submissions"

Sidebar entry renamed to match the page heading; the page itself gains a **Manage forms** button up top linking back to ``/tspro/frontend/forms``.

## [2.1.27] — 2026-05-19

### Added — File-type restrictions on form file uploads

File-type form fields in the form builder grow an **Accepted file types** input — comma-separated extensions or MIME types (``.pdf,.docx`` or ``image/*``). The HTML5 ``accept`` attribute drives the picker; a new server-side ``_accept_matches`` helper enforces the same rule on submit so a tampered POST can't smuggle a disallowed type through. The accept input auto-hides on non-file cards and toggles when the type changes.

## [2.1.26] — 2026-05-19

### Changed — Module form URLs

- Each module form's Preview button on the settings page now points to the form's current public URL — the admin-set custom slug when one is configured, the canonical path otherwise.
- The canonical paths (``/submissionform``, ``/storyform``, ``/contact``) 302-redirect to the custom slug when set so only one URL serves the form at a time.

## [2.1.25] — 2026-05-19

### Added — Story submission pipeline

Story submissions land in the Stories admin pending-review tab instead of Form Submissions. New public ``/storyform`` route (renders through the shared Submission Form template chrome — Classic / Minimal / Split) with optional file attachment + an Accept Terms checkbox. Admins approve to drafts, reject, or download the attached file for offline review. A one-shot importer on the Form Submission detail page migrates legacy custom-form story submissions into the new flow.

### Added — Form builder integrated into all three module forms

The custom-form field builder is now embedded in all three module-form settings pages (Announcements/Events, Story, Contact). Admins drag/edit/add/remove fields with the same UI custom forms use; each form ships with a default block set matching its built-in layout. Per-field labels, placeholders, help text, and options are editable inline inside the builder.

### Added — Configurable public URL per module form

Each module form gains a configurable public URL slug — the built-in path keeps working and the catch-all dispatcher serves the form at the admin-picked slug as well. Settings page shows the canonical URL pre-populated so it's always visible.

### Changed — Forms admin polish

Custom forms get a Visibility card with an on/off toggle matching the module-form pattern. "Submission Form" is renamed to "Announcements/Events Form" throughout the UI. Submission Form template card is renamed "Forms Template" since it now drives the chrome of every public form.

## [2.1.24] — 2026-05-19

### Changed — Post edit page polish

- Top **Save post** / **Save draft** primary buttons replaced by the yellow save bar pattern. State transitions (Publish, Move to Drafts) stay in the top action area as explicit lifecycle actions.
- Summary field renamed to **GSR Summary** with an updated subhead.
- Headline card gets 1rem of breathing room between groupings.
- Event checkbox subhead changed to "Shows up in event feeds."
- Event details card hides entirely when the Event checkbox is off and toggles live without a save.
- Links card sits above Event details in the layout order.

## [2.1.23] — 2026-05-19

### Added — Multi-row Links section on posts

The Event website field becomes a top-level **Links** section that applies to announcements and events alike. Each row carries a URL, a label, a Primary (solid) / Secondary (outline) button style dropdown, and an "open in new tab" checkbox. **+ Add another link** stacks as many call-to-action buttons as needed; rows with a blank URL are silently dropped at save time. Frontend event detail templates (classic, poster) honour the per-link button style; minimal + timeline keep their inline text-link rendering.

## [2.1.22] — 2026-05-19

### Added — Announcement auto-archive

Post edit gains an announcement-only "auto-archive after date/time" toggle (hidden when Event is checked — events already auto-archive via ``event_ends_at``). The auto-archive sweep handles announcements past their deadline and runs on the public list + detail routes so the public side stays in sync without an admin visit.

### Fixed — Posted on field

Edit form now populates from ``display_posted`` so legacy rows show their stored timestamp.

### Changed — Event details consolidated

Event website + Event contact fold into the main Event details card as subheaded sections.

### Changed — Meeting modal Queue-schedule-change submit is inline

Fetch-driven save with the existing yellow save bar flipping to **Saved** and animating out instead of closing the modal.

## [2.1.21] — 2026-05-19

### Added — Public alert expiry + future schedule swaps

The meeting edit modal grows two scheduling helpers:

- **Public Alert Message** gets a toggle + datetime-local picker that auto-hides the alert after the chosen moment and wipes it from the field on the next page load.
- New **Scheduled changes** fieldset under Day & Times — queue a full future schedule swap with an effective date; the next page load past that date replaces the current days + times with the queued set and deletes the queued row.

### Changed — Public meeting alert presentation

The public meeting alert background is solid amber (no more transparent wash) and the alert now also renders on the meetings list cards above the description across all three layouts.

## [2.1.20] — 2026-05-19

### Added — Featured-image File Browser picker on post edit

Announcements & Events edit page gains a **Choose from File Browser** button next to the featured-image upload input. Opens the existing media picker modal; selecting an item swaps the inline preview, stashes the MediaItem id in a hidden input, and clears any pending file upload so the browser pick is what saves. Upload, picker, and the existing "Remove current image" checkbox are processed in priority order on the server.

## [2.1.19] — 2026-05-18

### Added — Pending-submissions chip + unified Forms dashboard widget

- **Sidebar chip** on the Announcements & Events entry shows the number of visitor-submitted posts awaiting review.
- **Dashboard Forms widget** replaces the old standalone Contact Form widget, rolling up every form on the system (Submission Form, Contact Form, plus every CustomForm row) with submission counts, last activity, and warn-tinted attention badges. New custom forms surface automatically.

## [2.1.18] — 2026-05-18

### Changed — Form Submissions list: card layout with per-row submitter preview

The Form Submissions index used to render each row as a thin "Form name · timestamp · IP · View details →" strip. Replaced with a card-per-row layout that surfaces who submitted, how to reach them, and what they wrote, so an operator can triage at a glance without opening every row.

- **New ``_summarise_form_submission(sub)`` helper** in ``routes.py`` walks the parent CustomForm's ``blocks_json`` to identify fields by type + name heuristics (since the operator types free-form labels): NAME_HINTS = ``full_name`` / ``your_name`` / ``submitter_name`` / ``name`` / ``contact_name``; phone hints = ``phone`` / ``tel`` / ``mobile``; subject hints = ``subject`` / ``title`` / ``topic``; body hints = ``message`` / ``comments`` / ``body`` / ``details`` / ``description`` / ``notes``. Returns ``display_name`` (with email-localpart and "Anonymous" fallbacks), ``email``, ``phone``, ``headline`` (140-char trimmed), ``field_count`` (non-empty answers), ``file_count``.
- **``frontend_form_submissions``** route precomputes a ``{sub.id: preview}`` dict and threads it into the template so the Jinja loop stays declarative (no payload JSON parsing in the template).
- **``frontend_form_submissions.html``** renders each submission as a card with:
  - a brand-blue avatar circle with the submitter's first initial (muted grey when "Anonymous")
  - bold submitter name + form pill + site-local timestamp on the head row
  - 2-line clamped headline below
  - chips for email, phone, field count, file count (when present), and IP (muted, mono)
  - right-side chevron with a hover slide on the card
- **CSS** replaced the old ``.fe-submission-row`` flat strip with the new ``.fe-submission-card`` system — hover lifts the border to brand-blue with a soft shadow, mobile breakpoint at 640px drops the chevron and stacks the timestamp.

### Changed — Zoom Accounts calendar shows 12-hour times

The grid's ``cal-time`` cells used to render ``18:45–20:00``. Now ``6:45 PM–8:00 PM`` via the existing ``|fmt12h`` filter — matches the rest of the app's time displays.

### Changed — Sidebar Intergroup section: "+ Add Library" → "+ Add IG Library"

The admin-only action pinned to the bottom of the Intergroup subsection used to read "+ Add Library" — easy to confuse with the standalone "+ New Library" button on the main libraries page (which creates a regular non-Intergroup library). Renamed to "+ Add IG Library" so the operator sees at a glance that this entry creates a library scoped to the Intergroup module.

### Changed — Currently Online widget no longer shows the viewing admin

A small UX nit: the widget surfaced the admin who was viewing it, which added noise (the admin already knows they're signed in) and inflated the header count. ``/api/online-users`` now drops the viewing admin from ``users`` and recomputes the active ``count`` from the filtered list. The dashboard's server-metrics tile and its tooltip-names list got the same treatment so the count + names stay in sync between the two surfaces.

## [2.1.17] — 2026-05-18

### Added — Custom forms support Cloudflare Turnstile

The events-submission form, the contact form, and the admin login all already gate POST through Cloudflare Turnstile when ``SiteSetting.turnstile_enabled`` is on. Custom forms were the only public POST surface left without the same protection — bots could (theoretically) target an admin-authored form's URL directly.

- **``frontend/_custom_form_body.html``** renders the standard ``<div class="cf-turnstile">`` widget (same chrome the contact + submission forms use) when ``site.turnstile_enabled && site.turnstile_site_key``. Picks up the Turnstile script for free — the wrapping ``frontend/submission.html`` dispatcher already loads it conditionally; no extra JS hop on the custom-form path.
- **``frontend.py::custom_form_submit``** runs ``_verify_turnstile`` against ``cf-turnstile-response`` before any storage / email work when ``turnstile_enabled``. Failed verification builds a replay dict from the incoming form (proper checkbox multi-value handling so multi-select state survives) and re-renders the form with a new ``__turnstile__`` form-level error + HTTP 400. The visitor doesn't lose their typing.
- **Form-level error banner** in ``_custom_form_body.html`` — keyed on ``cform_errors['__turnstile__']`` so the rejection copy sits above the fields rather than associating with any single input. New ``.fe-custom-form-banner`` / ``.fe-custom-form-banner--error`` CSS (light + dark mode variants).

Verified end-to-end with Cloudflare's always-passes test sitekey + a no-token POST against a custom form: widget renders, JS loaded, server rejects untokened POST with HTTP 400 + banner shown + typed values preserved.

## [2.1.16] — 2026-05-18

### Changed — Off-site backup datetimes now render in the site's configured timezone

Every backup datetime display path was hard-coded to UTC even though admins set their tz on Settings → Timezone. Promoted everything to render in the site's local zone with a tz abbreviation suffix (e.g. ``May 18, 03:00 PDT``) instead of ``May 18, 03:00 UTC``:

- New ``|fmt_site_local`` Jinja filter (``app/__init__.py``) that attaches UTC to a naive datetime, converts to ``site_timezone(SiteSetting)``, and formats with ``%Z`` so the abbreviation lands on the end. Already-aware datetimes are converted directly rather than double-stamped.
- ``backups_list.html`` (per-row last/next run + recent-activity rows), ``backups_runs.html`` (run history detail), ``index.html`` Backups dashboard widget (Last successful / Next scheduled run + Recent activity rows), and the wizard step-5 finalize flash all now run through the new filter.
- **Cron expression itself is interpreted in the site's timezone**, not UTC. ``compute_next_run`` in ``app/backup_scheduler.py`` attaches the site's zone to the base datetime before handing it to croniter, computes the next firing in local time, then converts back to naive-UTC for storage. So ``0 3 * * *`` now means 3 AM local (matching what the admin sees on the wall clock) — not 3 AM UTC. Falls back to UTC when no app context is available so the scheduler boot path stays robust. Both the wizard's step-3 schedule hint and the edit page's hint now read "*interpreted in the site's timezone — set on Settings → Timezone*".

### Changed — Currently Online widget keeps idle users visible for an hour

The widget used to drop a user the moment their ``last_seen_at`` aged past 5 minutes — handy for "who's working in the portal RIGHT NOW", but lost track of admins who'd been around recently and hadn't yet been seen by another. Lift the list cap from 5 min to **1 hour** while keeping the 5-minute window as the "active" threshold:

- New ``IDLE_WINDOW = timedelta(hours=1)`` in ``app/routes.py``. ``_online_users()`` now returns ``(active_count, users)`` where ``users`` is everyone within the 1-hour idle window (newest-first) and ``active_count`` is the within-5-min subset — what the dashboard's server-metrics tile + the widget header still reports as "currently online".
- ``/api/online-users`` adds an ``is_idle`` boolean per user (``last_seen_at`` past 5 min but within 1 hour).
- ``_online_widget.html`` adds ``fmtIdle(iso)`` returning "*no activity in X mins*" with pluralisation, renders idle rows with an ``is-idle`` class + ``data-idle="1"`` attribute, and the per-second tick-updater picks ``fmtIdle`` vs ``fmtAgo`` based on the row's idle flag.
- CSS for ``.online-row.is-idle`` drops opacity to 0.55, mutes the avatar and location-link colors, and skips the just-moved flash so idle rows don't pulse.
- Empty-state copy changed from "*Nobody is currently signed in.*" to "*No users active.*" — fires only when nobody's been seen at all in the past hour.
- The dashboard's server-metrics tile tooltip continues to list only the active subset, so the count and the names match.

### Fixed — Newly-logged-in user shows up in the Currently Online widget immediately

``User.last_seen_at`` was only ever set by the request-tracker's before_request hook on a non-skipped GET. If a fresh login's post-redirect GET happened to be skip-listed (an asset request, an API ping) or the visitor closed the tab before the redirect resolved, the user wouldn't appear in the widget on the next 5-second poll. ``auth.login`` now stamps ``user.last_seen_at = utcnow()`` at the moment ``login_user()`` returns, so the row enters the widget regardless of what the redirect lands on.

## [2.1.15] — 2026-05-18

### Changed — Form Submissions moved out of the Web Frontend admin into the main app sidebar

The Form Submissions admin used to live as a Web Frontend subnav entry under **Structure**, alongside the form builder. Reaching the inbox from anywhere outside the Web Frontend admin meant clicking into the FE area first — an awkward extra step for a destination admins consult independently of the FE editing surface. Promoted it to a first-class sidebar entry in the **Admin** section of the main app sidebar.

**Sidebar (``app/sidebar.py``):**

- New ``form_submissions`` entry in ``_ADMIN_CATALOG`` with ``endpoint="main.frontend_form_submissions"`` and an ``active_kind="prefix:main.frontend_form_submission"`` so the link lights up both on the list and on the per-submission detail page.
- ``_is_visible`` returns ``True`` only for admins (``user.is_admin()``) — the link never enters the rendered HTML for non-admin sessions.
- Picks up the existing ``admin_reorder_catalog`` walk automatically, so the item appears in **Settings → Sidebar** drag-reorder UI without further code changes.

**Removed from Web Frontend admin (``_frontend_subnav.html``):**

- Subnav link under Structure is gone (both the desktop nav `<a>` and the mobile picker `<option>`).

**Submissions admin pages now render standalone:**

- ``frontend_form_submissions.html`` + ``frontend_form_submission_detail.html`` dropped their ``.fe-admin-layout`` wrapper and ``_frontend_subnav.html`` include. They now render as plain admin pages (extending ``base.html`` directly), matching the layout pattern of ``contact_form.html``.
- Submissions-list page's old "← Back to forms" top_actions link removed (the sidebar is now the canonical entry point).
- Detail page keeps its "← Back to submissions" top_actions link — that's natural list↔detail navigation, not Web-Frontend-specific chrome.

## [2.1.14] — 2026-05-18

### Fixed — Custom form submit 500'd when building the recipient-email subject

After the CSRF fix in 2.1.13, posting a valid CustomForm submission hit ``AttributeError: 'SiteSetting' object has no attribute 'frontend_site_name'`` while building the recipient-email subject line. The brand-name column is ``frontend_title``, not ``frontend_site_name`` — I'd guessed at the column name from memory rather than grepping the model. Fixed in ``frontend.py::custom_form_submit``; also added the standard ``if site else None`` guard so a never-configured install doesn't trip on the attribute access either.

## [2.1.13] — 2026-05-18

### Fixed — Custom form submit returned "CSRF token is missing"

Every public CustomForm POST was rejected with HTTP 400 ``The CSRF token is missing.`` because the form body partial omitted the hidden CSRF input. Flask-WTF's app-wide ``CSRFProtect`` requires a token on every POST; the legacy events-submission and contact public forms both include one. Added ``<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`` to ``frontend/_custom_form_body.html``, matching the shape the other two public forms use.

## [2.1.12] — 2026-05-18

### Added — Custom forms with a drag-and-drop field builder

A whole new admin-authored forms system: build any form from the Web Frontend admin, give it its own URL, collect submissions in a unified admin inbox. Lives alongside the existing events/announcements Submission Form and the dedicated Contact Form — those keep their specialised business logic untouched.

**Models** (new tables, auto-created via ``db.create_all()`` on boot, no ``_migrate_sqlite`` needed):

- ``CustomForm`` — ``slug`` (unique-indexed, drives the public URL), ``title``, ``description`` (markdown-supported intro), ``blocks_json`` (the ordered field set), ``recipients_csv``, ``redirect_url`` / ``thank_you_message`` (one wins on submit), ``enabled``, ``created_at`` / ``updated_at``.
- ``FormSubmission`` — ``form_id`` FK (cascade delete), ``payload_json`` (``{"fields": {…}, "files": {name → {stored, original}}}``), ``ip``, ``created_at``.

**Admin index (``Web Frontend → Forms``)** — same page as the registry-form list, with a new **Custom forms** section. Single **+ Add form** button creates a disabled-by-default stub (``Untitled form`` / ``untitled-form[-N]``) and drops the operator onto the edit page with the title input autofocused + selected.

**Edit page (``/tspro/frontend/forms/custom/<id>/edit``)** — settings card on top (title, slug with reserved-route + Page-slug + CustomForm collision guards, description, recipients CSV, redirect URL / thank-you message, enabled toggle), field builder below. Eight field types: ``text``, ``email``, ``phone``, ``textarea``, ``select``, ``radio``, ``checkboxes``, ``file``. Per-field config: label, name (auto-snake-case from label, unique-suffixed on collision), required toggle, placeholder, help text, options (one-per-line for select/radio/checkboxes). HTML5 drag & drop reorder via the ``⋮⋮`` handle on each card; cards start ``draggable="false"`` so cursor placement + drag-highlight in the field's textareas work normally — the handle's ``mousedown`` flips the card draggable for the duration of the gesture, ``dragend`` / window-``mouseup`` resets.

**Public render** routes through the shared "Forms" template — the same ``frontend/submission.html`` dispatcher the events/announcements submission form uses, with the operator's currently-selected template variant (Classic / Minimal / Split), dynamic background, width mode, and padding. CustomForm-specific overrides (``heading_override`` = title, ``intro_override`` = description piped through ``|markdown_block``) sit in place of the SiteSetting defaults; a new ``form_body_partial`` parameter on each variant swaps the events form body for ``frontend/_custom_form_body.html``. Contact form unchanged — kept on its own template per product spec. The ``- list`` markdown shape works without the operator needing a blank line above (``markdown_block`` auto-inserts it).

**Submit handler** validates fields against the form's blocks (``required``, basic email format), stores a ``FormSubmission`` row, optionally emails recipients (one address per submission with Reply-To set to the submitter's email field when one exists), then either redirects to ``redirect_url`` or renders the thank-you message inline. File uploads land under ``UPLOAD_FOLDER`` with UUID-prefixed filenames; payload JSON stores the filename + the operator-uploaded original. Validation failures re-render with field-level errors AND previously-typed values so the visitor doesn't lose their typing.

**Form Submissions admin** — new sidebar entry under **Structure** in the Web Frontend subnav. List page at ``/tspro/frontend/forms/submissions`` shows the 200 most recent submissions across all custom forms, filterable by form via a dropdown. Per-submission detail at ``/forms/submissions/<id>`` pairs each value with its field label (from the form's blocks_json), surfaces file attachments as download links, handles deleted-form edge case by falling back to a raw JSON payload view. Delete action with confirm.

**Checkboxes help — multi-line + markdown.** The help-text input under a ``checkboxes`` field is a 4-row ``<textarea>`` with a 2000-char ceiling and a "Markdown supported" hint. Renders publicly through ``|markdown_block`` inside a block-level ``<div>`` so multi-paragraph help, lists, links, emphasis all work. Other field types keep their existing single-line ``<input>`` + plain-text render.

**Markdown description.** The form's ``description`` field on the edit page now advertises "Markdown supported" and renders through ``|markdown_block`` on the public page, sitting in place of the variant's intro slot.

### Added — Stories list "Submit a story" call-to-action

The public ``/stories`` page can now carry an opt-in CTA button under its title + subheading that links to any form on the site. Two new SiteSetting columns (``frontend_stories_list_submit_form``, ``frontend_stories_list_submit_label``) drive it. Admin Templates page picks the target form from a single grouped dropdown — **Built-in forms** optgroup for the registry entries, **Custom forms** optgroup for every CustomForm row (disabled forms show ``(disabled)`` next to their name). Identifier is stored as a registry-key (``submission`` / ``contact``) or ``custom:<id>``, resolved to a URL at render time so a CustomForm slug rename or deletion doesn't leave a dangling link. Empty / invalid / deleted-form identifiers cleanly hide the button. New shared partial ``frontend/_stories_submit_cta.html`` included from each of the six variants (paper-stack, ledger, manuscript, broadsheet, minimal-serif, magazine) right after their heading area so the CTA sits at the top of the page where visitors look first.

## [2.1.11] — 2026-05-18

### Fixed — Dropbox backup target no longer expires every 4 hours

The Dropbox backup wizard collected a raw access token from the Dropbox developer console's "Generate access token" button. Since Dropbox's Sept-2021 auth change those tokens are **short-lived (4-hour lifetime)**, so the scheduler's daily 3 AM run worked once and then failed every subsequent morning with ``AuthError('expired_access_token', None)``. Dev mode is unrelated — the token lifetime is the same on dev and published apps.

Switched the Dropbox path to the OAuth-with-refresh-token flow:

- **Three new ``BackupTarget`` columns** (``app_key``, ``app_secret_enc``, ``refresh_token_enc``) + matching ``_migrate_sqlite`` entries. The legacy ``oauth_token_enc`` column stays so pre-2.1.11 targets keep working until they're migrated; the backend falls back to it when the refresh trio is empty.
- **``DropboxBackend.open()``** prefers ``dropbox.Dropbox(oauth2_refresh_token=…, app_key=…, app_secret=…)`` when those three are present — the SDK auto-mints a fresh short-lived access token on every call. Falls back to the legacy raw-token constructor when only ``oauth_token_enc`` is set; raises a clear error message when neither is set.
- **New shared template partial ``_backups_dropbox_fields.html``** — App key + App secret + Authorization code fields, plus a JS-driven "Open Dropbox authorization page" link that fills in the OAuth URL (``https://www.dropbox.com/oauth2/authorize?client_id=<key>&response_type=code&token_access_type=offline``) so the operator gets back a *refresh* token rather than another short-lived access token. Reused by both the wizard step 2 and the edit page so future changes land in one place.
- **New helper ``_exchange_dropbox_auth_code()``** — POSTs to ``https://api.dropboxapi.com/oauth2/token`` to swap the operator's one-time authorization code for a refresh token at save time. Maps ``invalid_grant`` / ``invalid_client`` / missing-refresh-token / network errors to actionable flash messages.
- **Both POST handlers** (``backups_wizard_step2_post`` + ``backups_edit_post``) run the exchange when ``auth_code`` is present, persist the encrypted refresh token, and clear ``oauth_token_enc`` so the backend stops falling back to the (now-expired) legacy token.
- **Yellow banner on ``backups_list.html``** for any Dropbox target that still has only the legacy ``oauth_token_enc``, with a direct link to Edit so the operator can finish the OAuth dance in one click.

## [2.1.10] — 2026-05-18

### Added — Edit an off-site backup target after it's been added

Off-site backup targets were create-only — once a target was through the 5-step wizard, the only ways to change anything were Remove + recreate (loses run history) or hand-edit the row. New per-row **Edit** action on the backups list opens a single consolidated page with connection, schedule, and encryption sections stacked on one form. One Save button writes all three groups in one POST and redirects back to the list.

- **New routes:** ``GET /settings/backups/<id>/edit`` (renders the edit page) and ``POST /settings/backups/<id>/edit`` (consolidated save). Field-write logic mirrors the wizard's step 2 / 3 / 4 POST handlers exactly so a future refactor can lift them into one helper.
- **Schedule re-seeds ``next_run_at``** when the target is currently enabled so a cron change takes effect on the next scheduler tick, not the next restart.
- **Encryption gating** preserves leave-blank-to-keep-current for the passphrase and only requires the "I've saved it" acknowledgment on first turn-on or rotation — toggling an already-stored passphrase off doesn't re-prompt.
- **Test connection** posts connection-only fields to the wizard's step-2 endpoint (which skips encryption validation) so a half-typed passphrase doesn't block the network test.
- **Read-only:** ``kind`` (FTP / SFTP / Dropbox). Switching backends mid-life would orphan the existing remote archives — make a new target instead.

### Added — Admin-tunable shadow colour for primary + secondary card styles (light + dark mode)

Four new ``Card styles`` design fields on the Web Frontend Design page — **Primary card — shadow color**, **Primary card — shadow color (dark mode)**, **Secondary card — shadow color**, **Secondary card — shadow color (dark mode)** — let admins recolour the box-shadow under their primary and secondary card surfaces from the historic neutral charcoal to anything (brand-tinted glow on hero cards, warm amber on feature cards, a cool cyan glow that only shows in dark mode, etc.).

**How it works**

A new ``SHADOW_SCALE_COMPONENTS`` table in ``app/design.py`` mirrors ``SHADOW_SCALE`` but splits each preset into ``(offset+blur, alpha)``. The new helper ``shadow_with_color(scale_key, hex_color)`` composes a fresh ``box-shadow`` value by combining the chosen size scale's offset+blur with rgba derived from the operator's hex (alpha preserved from the scale). ``design_css_vars`` now uses the helper to emit **two pairs** of vars per card style — light (``--fe-card-primary-shadow`` / ``--fe-card-primary-hover-shadow``) and dark (``-shadow-dark`` / ``-hover-shadow-dark``). Each card style's resting and hover shadow share the same tint within a mode so the surface stays visually coherent. Invalid hex inputs gracefully fall back to the canonical ``SHADOW_SCALE`` string so a bad override never silently drops the shadow.

**Dark-mode handoff** is done in ``frontend.css`` via ``html[data-theme="dark"]`` selector rules that redirect every primary / secondary card consumer (``.fe-card-primary``, ``.fe-meeting-card``, ``.fe-feature-card``, …) to the ``-dark`` variant, with ``var(…, var(…))`` fallback to the light value so an install that hasn't customised the dark colour renders identically across modes.

**Defaults**

All four fields default to ``#0f172a`` (rgba 15, 23, 42) in every theme — the exact charcoal the old hardcoded ``SHADOW_SCALE`` baked in — so existing installs render byte-identical until an admin opts in.

**Admin UX**

Picks up the existing ``kind="color"`` rendering automatically — color picker + hex chip + override toggle + reset button — and slots into the existing "Card styles" two-column layout (Primary card column on the left, Secondary card column on the right) right after the resting and hover shadow scale dropdowns.

### Changed — Web Frontend Overview tab refactored to a draggable widget grid

The Web Frontend Overview tab (``/tspro/frontend/``) was just two toggles + a "Pick a section on the left to edit" placeholder list. Replaced with a customisable widget grid that mirrors the home dashboard's recipe end-to-end — same ``.dash-grid`` + ``[data-dashboard-reorder]`` chrome, same ``_dash_widget.html`` macro, same drag-to-reorder JS, same Customize-modal pattern. Operators can hide widgets they don't care about and reorder the rest; preferences persist per-user.

**New widgets** (default order):

- **fe-status** — public-frontend on/off toggle + the per-user sidebar auto-hide pref (the two existing toggles, kept as a widget so they can be reordered / hidden).
- **fe-visitor-metrics** — wide widget that lifts the five-tile overview bar straight out of ``visitor_metrics.html`` (Views · 30d / Unique visitors / Today / Yesterday / Last 7 days), backed by the same ``visitor_metrics.summary`` + ``daily_series`` aggregators the full metrics page uses. Header links through to ``/tspro/frontend/metrics``.
- **fe-pages** — last 6 updated content pages with a badge showing total page count.
- **fe-redirects** — total redirect count + the 5 most recent ``source → target`` pairs.
- **fe-navigation** — header nav-item count + one-click into the navigation editor.
- **fe-forms** — every entry in ``forms_registry.all_forms()`` (Submission, Contact) with its live/off state.
- **fe-branding** — active theme name + logo-present indicator + shortcut to branding settings.
- **fe-header-footer** — pair of quick links to the Header and Footer editors.

**Persistence:** new ``User.fe_dash_show_*`` boolean columns (one per widget, defaults True) + ``User.fe_dash_order_json`` text column for the per-user order. Matching ``_migrate_sqlite`` entries so existing installs pick them up additively.

**Routes:** new ``POST /tspro/frontend/customize`` (toggles) and ``POST /tspro/frontend/order`` (JSON drag-reorder) mirror ``dashboard_customize`` / ``dashboard_order_save`` exactly — same shape, same auth, same payload contract — so the existing dashboard-reorder JS in ``app.js`` works on either grid unchanged (selector matches ``[data-dashboard-reorder]`` on whichever page is rendered).

**Removed:** the "Pick a section on the left to edit" copy + the bulleted Header / Footer / Homepage / Pages list. Those links now live in the Header & Footer widget, the Pages widget, and the subnav.

### Added — Optional passphrase encryption for full-portal bundles (AES-256-GCM)

Bundles contain the entire SQLite DB + every upload + ``zoom.key`` (the Fernet seed that decrypts stored Zoom / OTP / Turnstile credentials). When transmitted through a TLS-terminating proxy like Cloudflare, the edge sees the bundle in plaintext during the upload — same exposure as any other HTTPS upload through CF, but it's worth options. Operators can now encrypt the bundle with a passphrase so only ciphertext ever leaves the source host.

**New module ``app/bundle_crypto.py``:** streaming AES-256-GCM with a 32-byte key derived from the passphrase via PBKDF2-HMAC-SHA256 (600 000 iterations) and a fresh 16-byte random salt per export. Binary format is ``[magic 'TSPENC01' 8B][salt 16B][nonce 12B][ciphertext …][tag 16B]``. Encrypt and decrypt both walk the input in 1 MiB blocks via ``cryptography``'s low-level ``Cipher.update / finalize`` API so multi-GB bundles cost O(1) memory. GCM auth tag covers the entire ciphertext — wrong passphrase or any byte tampering raises ``BundleDecryptError`` at finalize time.

**Export (``data_export`` → POST):** the form on Settings → Data → Export is now a POST form with an optional **Encryption passphrase** field. Empty → plain ``.zip`` (legacy GET path still works for scripted callers); non-empty → server stream-encrypts after building the bundle and serves ``tsp-export-…-zip.enc`` with ``application/octet-stream``. Passphrase rides in the POST body, never the URL, so it can't leak via Referer / server logs / browser history.

**Import (``data_import`` direct + ``data_import_finalize``):** both routes now accept an optional ``passphrase`` form field. New helper ``_decrypt_if_encrypted(zip_path, passphrase)`` runs after the file is assembled on disk: detects the ``TSPENC01`` magic, decrypts to a fresh tempfile under the supplied passphrase, hands the decrypted path to the shared ``_perform_data_import`` helper. Bundles without the magic skip decryption (passphrase is ignored with a "warning" flash so the operator catches a mismatched bundle before it overwrites the destination). Wrong passphrase / corrupted ciphertext → red flash with a clear explanation; no partial import. Cleanup unlinks the decrypted tempfile in the finally even when the import errors.

**Browser (``base.html``):** the Import form has a new password field — placeholder "Required only for encrypted bundles", autofill suppressed via ``autocomplete="off"``. The chunked-upload JS reads the field and includes it in the synthetic finalize POST so the existing 90 MiB chunk flow works for ``.zip.enc`` bundles unchanged — chunks are just ciphertext bytes on the wire, Cloudflare's edge sees nothing recognizable. File picker now accepts ``.enc`` alongside ``.zip``.

**Passphrase generator on the export form.** Operators don't have to invent a strong passphrase: a **Generate strong passphrase** button (visible by default) produces a 24-character passphrase formatted as 6 groups of 4 (e.g. ``Xk9p-Mw2N-jVqL-3Hbt-uR5z-PnAc``) drawn from a 54-character alphabet that excludes the visually-ambiguous ``I l O 0 1`` so it can be transcribed from a printed page without second-guessing. ~138 bits of entropy. Inline **Show/Hide** toggle + **Copy to clipboard** button appear once the field has a value (clipboard falls back to a "Press Ctrl+C" selection state on older browsers / non-secure contexts where ``navigator.clipboard`` isn't available). Generated client-side via ``crypto.getRandomValues()`` so the server never sees the passphrase until the encrypted bundle download is requested.

**Save-this-passphrase warning.** A yellow ``.flash.flash-warning`` banner appears the moment the passphrase field has any value (typed or generated): *"Save this passphrase before exporting. Store it somewhere safe — a password manager, encrypted notes app, or a printed page in a vault. Without it the encrypted bundle cannot be decrypted."* No recovery channel exists; if the operator loses the passphrase the bundle is permanently undecryptable.

**Settings save-bar opt-out.** The export form carries ``data-no-ajax="1"`` so the Settings modal's save-bar tracker doesn't hide the primary submit button (the tracker normally hides ``.btn-primary`` so the floating yellow Save bar owns the commit path — the right behaviour for "save these settings" forms, wrong for "trigger this download" forms).

## [2.1.9] — 2026-05-18

### Added — Chunked bundle restore so imports work behind a 100 MiB proxy cap (Cloudflare Free)

Cloudflare's Free plan caps proxied request bodies at 100 MiB, so any non-trivial restore bundle (DB + uploads dir in one zip) hit a 413 at the edge before the request even reached the app — no spinner, no flash, the user just got a Cloudflare error page. The Import form now slices the chosen archive into ~90 MiB pieces in the browser and uploads them as separate requests, then triggers the restore once every chunk has landed. No proxy config change, no operator paperwork — pick the file, type REPLACE, click Import, watch the progress bar.

**Server (``app/routes.py``):**

- New ``POST /settings/import/chunk`` — accepts one chunk keyed by a per-upload UUID (``upload_id``), ``chunk_index``, and ``total_chunks``. Saves the chunk to ``<data_dir>/import-chunks/<upload_id>/<chunk_index:08d>.bin``. Admin-only, validates the upload_id against a strict UUID regex (no path traversal), runs an idempotent sweep that removes abandoned chunk dirs older than 24 h on every chunk POST.
- New ``POST /settings/import/finalize`` — concatenates the chunks in order into a single ``tsp-import-chunked-*.zip`` in the data dir, then hands the assembled path to the shared ``_perform_data_import`` helper that the direct-upload route already uses. Re-checks the REPLACE confirmation, verifies the chunk count matches the browser's ``expected_chunks`` (bails with a clear flash on mismatch + cleans the staging dir), cleans up after itself on both success and failure paths.
- Extracted the existing ``/settings/import`` body into ``_perform_data_import(zip_path) -> (ok, redirect_url)`` so both the direct-upload (no-JS fallback) and the chunked-upload finalize call the exact same import logic. The direct route stays in place for clients that don't run JS or scripted callers that want a single-shot upload.

**Browser (``base.html`` + ``app.css``):**

- Form's submit handler intercepts on browsers with ``fetch`` + ``File.prototype.slice`` + ``crypto.randomUUID`` (with a v4 polyfill fallback for older Safari). Slices the selected file at the 90 MiB boundary (under the 100 MiB cap with envelope room), POSTs each chunk via ``fetch``, then synthesises a hidden form POST to ``/finalize`` so the browser follows the server's redirect-to-logout natively (preserving the flashed status). On feature-test miss, the native form POST stays in place — the no-JS path still works for bundles small enough to pass the proxy.
- New progress overlay (reuses the existing ``.backup-busy`` chrome) shows a brand-coloured progress bar with "Uploading bundle… — Chunk N of M — 270 MB of 1.2 GB", flips to "Reassembling and restoring…" once the final chunk lands, and surfaces an inline error message on a failed chunk so the operator knows to retry rather than being left staring at a hung spinner.
- Card now carries a one-liner above the form explaining the 90 MB chunking behaviour, so operators behind a proxy understand why it works without them having to read the changelog.

## [2.1.8] — 2026-05-18

### Fixed — Bundle restore: recycle gunicorn workers so sibling workers see the new DB

After a full-portal import, only the worker that ran the restore disposes its SQLAlchemy engine — sibling sync workers continue serving from connection-pool handles to the **pre-restore** SQLite file. Linux keeps the moved file readable through the open fd even after ``shutil.move``, so the symptom is intermittent: subsequent requests pick a worker round-robin, and the ones that land on the stale pool render the pre-restore DB (missing rows, 404s on uploaded media that the new DB does reference, occasional CSRF mismatches). Misdiagnosed as a cookie-collision issue on same-host dev/test pairs — the per-secret SESSION_COOKIE_NAME suffix already handles that cleanly.

``data_import`` now signals ``SIGHUP`` to the gunicorn master after the file swap. Gunicorn's HUP handler spawns fresh workers, waits until they're ready, then gracefully shuts down the old ones — the current worker finishes serving its redirect-to-logout before honouring the shutdown, so the user's response still ships. Guarded by a parent-cmdline check so it's a no-op under ``python run.py`` (debug, single process) — sending SIGHUP to bash would close the terminal.

## [2.1.7] — 2026-05-18

### Fixed — Bundle restore: auto-disable Turnstile on host change + clear login lockouts

Restoring a prod bundle with Turnstile enabled into an install on a different host (e.g. local dev / test VM) was a silent lockout: the Cloudflare sitekey is domain-bound, the widget either fails to render or fails to issue a token at the new host, and ``_verify_turnstile`` (which runs **before** the password check in ``app/auth.py``) rejects every attempt with "Security check failed" — easy to misread as bad credentials, and each attempt counts toward the per-IP / per-username rate-limit lockout.

Two-sided fix so both the source and destination cooperate:

- **Export (``app/backup.py``)** bumps manifest ``format_version`` to ``2`` and adds two context fields: ``source_host`` (the request host the export was triggered from, best-effort — scheduled background snapshots can't see one and write ``null``) and ``turnstile_enabled_at_export`` (so the importer doesn't need to peek at the restored DB to know whether to bother). The note in the manifest now also calls out the auto-disable behaviour.
- **Import (``data_import`` in ``app/routes.py``)** reads ``source_host`` from the bundle's manifest, compares to the current request host, and if they differ — or either is missing (pre-v2 bundles default to scrub) — flips ``site_setting.turnstile_enabled`` off and flashes a clear warning that names both hosts and points the admin at Settings → Security to re-enable once the sitekey matches the new host. Sitekey + encrypted secret are preserved on the row so a same-host re-import only costs one toggle flip. The importer also wipes ``login_failure`` so any lockout the admin accumulated bouncing off Turnstile mid-restore doesn't wedge them out on the new install.

## [2.1.6] — 2026-05-17

### Added — Restore bundle: busy spinner while the upload is in flight

The Settings → Data → Import form now mounts a full-viewport ``.backup-busy`` overlay (re-using the spinner already styled for the backup wizard) on submit, with **"Restoring bundle…"** / "Uploading the archive and replacing data. Don't close this tab." copy. The submit button flips to ``Restoring…`` and is disabled so the operator can't double-post. Resolves the silent-click confusion on multi-hundred-MB bundles where the browser shows no progress for tens of seconds while the upload streams.

### Fixed — Full-portal Import: lift 256 MiB upload cap + friendly 413 page

The Settings → Data → Import form was silently failing on any prod restore bundle bigger than 256 MiB. Flask's ``MAX_CONTENT_LENGTH`` (hard-coded at ``256 * 1024 * 1024``) short-circuits the request with HTTP 413 before ``data_import`` even runs, so the browser navigated to a bare error body that rendered as a blank page — no flash, no clue. After back-button the app still worked, but no data had imported. Triggered as soon as the source install accumulated a couple hundred MB of media — the uploads dir alone is part of the bundle.

Two changes in ``app/__init__.py``:

- **Default cap raised to 4 GiB and made env-configurable** via new ``TSP_MAX_UPLOAD_MB`` (megabytes; default ``4096``, falls back to ``4096`` on a bad value). Headroom for whole-portal restore archives without committing to "unlimited" — installs that need a tighter ceiling can dial it down.
- **413 errorhandler** flashes ``"Upload too large — exceeds the N MB limit. Raise TSP_MAX_UPLOAD_MB on the server and restart, then retry."`` and redirects to the Referer (same-host validated against ``request.host`` to avoid open-redirect; falls back to ``main.index``). The user lands back on the form they submitted instead of staring at a blank page.

CLAUDE.md updated to document the new default + env var.

### Fixed — Meeting edit modal: page behind reloads after a successful save

The meeting edit modal intercepts submit via ``fetch()`` to keep the modal open after a save (so the operator can keep editing), but the host page behind the modal was still rendering pre-save data once the modal was dismissed. The save handler in ``_meeting_modal.html`` now sets ``modal.dataset.reloadOnClose = '1'`` on a successful save, and a ``MutationObserver`` on the modal's ``aria-hidden`` attribute fires ``window.location.reload()`` the moment the modal closes by any path (Cancel button, X, Esc, or backdrop click). The keep-open-after-save UX is preserved — the reload only fires when the operator actually dismisses the modal, and saving twice before closing still results in exactly one reload.

## [2.1.5] — 2026-05-17

### Added — Audience controls on the email-list blast (Full list / Granular)

The Send-an-update page now opens with a full **Audience** card above Compose. Two radio modes, same shape MeetingLibrary uses for its all/granular reading selection:

- **Full list** *(default)* — fans out to every subscriber + every user with the ``intergroup_member`` role + every editor / viewer account. A static summary line under the radio reads ``X subscribers + Y intergroup + Z app users · TOTAL total (before email-dedupe)`` so the admin can see the spread before sending. Group toggles collapse via ``.ts-aud-groups[hidden] { display: none }`` (the bare HTML ``hidden`` attribute was being outranked by the block's ``display: flex``).
- **Granular** — reveals three group checkboxes (Subscribers / Intergroup members / App users). Inside Subscribers, a further "All subscribers" / "Pick which subscribers" radio reveals a scrollable checkbox list of every subscriber with Select all / Clear controls. A live summary line under the Granular radio updates on every audience-input change — group toggles, subs sub-mode flip, per-subscriber checkboxes, the bulk Select all / Clear — showing the same group + total counts the Full-list summary shows, recomputed from the current selection.

The send handler now validates ``audience_mode`` to ``all`` / ``granular``, in ``all`` forces every group + the subs sub-mode on so a stale form posts cleanly, and in ``granular`` reads the per-group toggles + the ``subscriber_ids`` checkbox whitelist (coerced to ints, only known rows allowed). Combined recipient list is **deduped by lowercased email** so a person in two groups gets one copy; the personalization ``{name}`` token uses the row's own name (subscriber.name or ``user.name or user.username``) so each recipient still sees their own. The ``recipient_count`` on the resulting BlastRun row reflects the deduped count, not the raw group sum.

### Added — Auto-hide app sidebar inside the Web Frontend admin

New ``User.fe_admin_autohide_sidebar`` boolean column (default True, ``ALTER TABLE ADD COLUMN`` migration). When on, the main app sidebar collapses to a hamburger button while the user is on a ``/frontend/…`` route — the Web Frontend has its own sub-nav (``.fe-admin-subnav``) so the outer sidebar competes with editing canvas width on laptops. ``body.fe-admin-autohide`` is set from ``base.html`` only when both conditions match; a new CSS ruleset under the existing ``@media (max-width: 900px)`` block mirrors its selectors at every viewport width so ``.sidebar`` becomes ``position: fixed; transform: translateX(-100%)`` and ``.menu-btn { display: grid }``. The existing menu-toggle handler drives ``.sidebar.open`` unchanged.

A new toggle row on the Web Frontend overview page lets the admin flip the pref off; the form carries ``data-fe-auto-submit`` so the FE save-bar tracker's ``trackable()`` check skips it (same opt-out the existing public-frontend toggle uses), avoiding a spurious "Unsaved changes" flash.

### Added — Name field on User accounts

``User.name`` — new optional ``String(120)`` column with a matching ``_migrate_sqlite ALTER TABLE`` entry. Distinct from ``username`` (the login handle): ``name`` is the friendly display form ("Jane D."). Surfaced everywhere User contact info shows up:

- Create User card has a Name input between Username and Email.
- All-users table has a Name column.
- Edit user modal has a Name input alongside Username / Email / Phone.
- ``users_create`` reads + persists ``name``; ``users_update`` honours an ``if "name" in request.form`` clause so submit-blank clears, omit-key leaves the row alone.

The email-list blast falls back to ``user.name or user.username`` when building the ``{name}`` personalization token from the IG-members or app-users groups, so blast recipients see their friendly name even if they never set up a TrustedServantSubscriber row.

### Changed — Sidebar links that leave the Web Frontend keep the sidebar open

Click handler in ``app.js`` now checks ``body.fe-admin-autohide``: when the click target's ``href`` doesn't include ``/frontend/``, the sidebar stays open through the navigation. The destination page doesn't carry the auto-hide body class so its sidebar renders statically visible — the previous unconditional ``classList.remove('open')`` produced a distracting slide-out + reflow + slide-in. In-Web-Frontend links still close the slide-in sidebar as before, and the mobile-breakpoint behaviour on non-FE pages is unchanged.

### Changed — Email-list cards drop the right border + the brand-blue left accent

Scoped CSS rule ``.ts-page-wrap .card.data-card { border-right: 0; border-left: 1px solid var(--border) }`` runs only inside the email-list admin pages (``/email-list`` + ``/email-list/blast``). The cards now sit with shadow + top + bottom + faint 1 px left/no right hairlines — the brand-blue accent reads as redundant chrome against ``.content``'s gutter on these wide-table pages. Every other consumer of ``.data-card`` (Settings panes, backups admin modal, email-list import wizard) keeps the full four-sided border + brand-blue accent.

### Changed — Email-list page title

The ``/email-list`` page heading was set to "Trusted Servants Email List" (the full module name) while the sidebar link stays as the shorter "Email List". The ``.ts-page-wrap`` outer wrap dropped its narrowing ``max-width: 1080px; margin: 0 auto`` constraint so the page sits flush in ``main.content`` like every other admin page; the wrap keeps just the flex-column + 1 rem gap shape.

## [2.1.4] — 2026-05-17

### Changed — Trusted Servants dashboard widget always shows when enabled

The widget no longer auto-hides itself after a user subscribes. The visibility gate in ``index.html`` dropped the ``and not trusted_servants_subscription`` condition; the widget now renders whenever ``trusted_servants_enabled`` is True and the user has ``dash_show_trusted_servants`` checked. Two render modes inside the widget body:

- **Not yet subscribed** — title "Join the Trusted Servants list", fields pre-fill from the ``User`` account (username / email / phone), primary action **Join the list**.
- **Already subscribed** — title "Your Trusted Servants info", fields pre-fill from the existing ``TrustedServantSubscriber`` row so the values shown match what admins see in the roster, primary action **Save changes**, plus a secondary **Remove me from the list** action below a thin divider. The secondary action POSTs to the existing ``/email-list/unsubscribe`` endpoint and is danger-tinted but transparent (text + hover background only — gentler than ``btn-danger`` since the user is removing themselves, not destroying data).

The ``/email-list/subscribe`` endpoint was already upsert-shaped (creates a new row when the user has no subscription, updates the existing one otherwise) so the form action stays the same for both modes — no route change needed.

## [2.1.3] — 2026-05-17

### Added — Trusted Servants Email List module

A self-contained admin-managed contact roster + mass-email surface, scoped to the public-facing URL ``/email-list``. Two new tables back it — ``TrustedServantSubscriber`` (one row per entry; ``user_id`` FK is nullable + unique so portal-user self-subscriptions and admin-added external contacts share the same table without duplicate constraints) and ``TrustedServantBlast`` (per-send history with subject + markdown body + recipient / sent / failed counts + started/finished timestamps + sender FK). Two new ``SiteSetting`` columns — ``trusted_servants_enabled`` / ``trusted_servants_required_role`` — drive the Modules-tab toggle and the role gate; a new ``dash_show_trusted_servants`` column on ``User`` controls the dashboard widget. All four schema additions ship with matching ``_migrate_sqlite`` ALTER entries.

Three entry points:

- **Dashboard sign-up widget** (``index.html`` widget block keyed ``trusted-servants``) — visible to every signed-in user until they've added themselves. Form pre-fills name from the user's username, email from ``User.email``, phone from ``User.phone``; submits to ``/email-list/subscribe`` which upserts the subscription. The widget auto-retires once the user is on the list. Dashboard's Customize modal carries a matching toggle row.
- **Admin manage page** at ``/email-list`` — table of subscribers with per-row Edit / Delete actions, an "Add manually" modal for external contacts (creates rows with ``user_id = NULL``), an "Import CSV" wizard (see below), a "Send an update" CTA, and a send-history card showing the last 25 blasts.
- **Mass-email compose** at ``/email-list/blast`` — subject + Markdown body. Submit fires one SMTP send per recipient (via the existing ``mail.send_mail``) so the body can be personalized with a ``{name}`` token; failures don't abort the loop — each recipient is tried independently and the ``BlastRun`` row records sent vs failed counts. A full-screen busy overlay blocks the page while the synchronous loop runs.

### Added — CSV import wizard (multi-step iframe modal) for the email list

``/email-list/import`` is now a three-step wizard that lives inside an iframe modal (same pattern as the off-site backup wizard). Step 1 takes the upload; step 2 renders the auto-detected column mapping + a live dry-run summary + the first 20 sample rows; step 3 commits and auto-closes. The whole flow stays inside the same modal until completion — no full-page redirects.

Column auto-detection normalizes each header to lowercase-no-punct and matches against alias sets:

- **Name** — ``Name``, ``Full Name``, ``Display Name``, ``Contact Name``, ``Subscriber Name``, or a ``First Name`` + ``Last Name`` pair concatenated at write time.
- **Email** *(required)* — ``Email``, ``Email Address``, ``Mail``, ``Mail Address``, ``Contact Email``, ``Email ID``.
- **Phone** *(optional)* — ``Phone``, ``Phone Number``, ``Mobile``, ``Cell``, ``Tel``, ``Telephone``, ``Contact Phone``.

Any column whose header doesn't match (Status, Role, Notes, internal IDs, etc.) is dropped — extra columns can't break the import. Encoding auto-detect: UTF-8 with BOM stripping → UTF-8 with replacement → latin-1 fallback. Delimiter detection: ``csv.Sniffer`` probes for comma / semicolon / tab / pipe with comma as the default. The parsed CSV is stashed on disk as JSON under ``<DATA_DIR>/ts_import/<token>.json`` so the file uploads once and the mapping form can re-preview without re-uploading; a 24h sweep runs on every upload to purge abandoned imports.

Each mapping ``<select>`` lists every header in the CSV plus an explicit "— none —" option. Changing any dropdown auto-re-renders the preview via a GET that preserves the token + embed flag + every other select's value, so the dry-run tally + sample table stay in sync without an explicit "re-run" click. Sticky footer pinned to the iframe viewport bottom keeps **Cancel / ← Back / Import N rows** reachable while the admin scrolls through a long mapping or sample.

Row filtering: blank rows skipped, rows missing name or email skipped, rows with malformed email (no ``@`` or no dot in the domain) skipped, duplicate emails (case-insensitive, against existing rows + earlier rows in the same CSV) skipped. 5000-row cap per upload so a misclicked huge file can't hang the request.

### Added — Watchtower quicknav button + Web Frontend "Web" / "View" relabel

A new pinned button cluster sits above the sidebar search bar and below the brand block. Row 1 carries **Web** (admin panel, with the live/off status dot) and **View** (public site, opens in a new tab) — both labels were shortened from "Web Frontend" / "View site" so they fit the half-width quicknav grid cells without ellipsis truncation. Row 2 (every admin) is a full-width **Watchtower** button with a ``shield`` icon and up to two right-aligned attention chips: an amber ``nav-badge-warn`` for pending access requests (``pending_access_count``, already in the context processor), and a brand-blue chip for currently-locked accounts (``locked_accounts_count``, added to ``inject_globals`` — one query against ``LoginFailure`` only for admin viewers). When neither count is > 0 the chip slot collapses so the button reads as a clean "Watchtower" with no decoration.

Both ``watchtower`` and ``web_frontend`` entries are now hidden from the Admin-section catalog in ``app/sidebar.py`` (``_is_visible`` returns False) — exactly one entry point per surface. ``contact_form`` stays in the catalog since it isn't part of Watchtower.

### Changed — Dashboard widgets adopt data-card chrome (without the brand left accent)

Every dashboard widget — both the seven macro-driven ones (Recent Meetings, Libraries, Recent Files, Visitor Metrics, Off-site Backups, Recent Deletions, Contact Form, Trusted Servants sign-up) and the three structurally-unique ones (Server Metrics, Currently Online, Access Requests) — now renders inside a ``.card.data-card`` section. The macro head row is now a ``.data-card-head`` flex line: **[≡ drag handle (inline)] [icon] [Title] [optional badge] [View all →]**. Each call site passes a ``head_icon`` Lucide key (``calendar`` for Meetings, ``book-open`` for Libraries, ``file-text`` for Files, ``bar-chart`` for Visitor Metrics, ``cloud-upload`` for Backups, ``trash-2`` for Deletions, ``mail`` for Contact Form, ``user-plus`` for Trusted Servants / Access Requests, ``users`` for Currently Online).

Two specific behaviors:

- **Drag handle inlined in the head row**. Previously absolutely positioned at ``top: 10px; left: 10px`` with a ``.dash-widget .card-head { padding-left: 38px }`` rule clearing space for it. The new macro structure embeds the handle inside ``.data-card-head`` directly, so it lives in the flex flow and the ``.data-card-head { gap: .6rem }`` spacing handles separation. ``.dash-widget-head .dash-drag-handle { position: static }`` overrides the global absolute placement; the chip's hover styling continues to come from ``.dash-drag-handle:hover``.
- **Brand-blue left accent suppressed in the dashboard context**. The standard ``.data-card { border-left: 4px solid var(--brand) }`` reads as visual noise next to the dashboard's tight masonry, so a scoped ``.dash-grid .card.data-card { border-left: 1px solid var(--border) }`` rule restores a uniform 1 px edge inside ``.dash-grid``. Settings panes, embed-mode admin iframes (backups admin, email-list import wizard), and every other consumer of ``.data-card`` keep the accent.

The macro's ``icon`` parameter was renamed to ``head_icon`` so it doesn't shadow the global ``icon()`` Jinja helper used to render the SVG inside the macro body.

### Changed — Public URL renamed from ``/trusted-servants`` to ``/email-list``

All 13 public paths under the module moved from ``/trusted-servants…`` to ``/email-list…``. Endpoint function names (``trusted_servants_list``, ``trusted_servants_import_confirm``, etc.) and the SQLAlchemy table names (``trusted_servant_subscriber``, ``trusted_servant_blast``) stayed put so every ``url_for("main.trusted_servants_*")`` reference + the sidebar's ``active_kind="prefix:main.trusted_servants"`` keep matching. The admin toggle at ``/settings/trusted-servants-toggle`` is a different path prefix and was deliberately left alone. The page heading was set to "Trusted Servants Email List" (the full module name) while the sidebar link stays as the shorter "Email List". The page wrap dropped its ``max-width: 1080px; margin: 0 auto`` since the outer ``main.content`` already caps width at 1400 px — the old wrap centered the page inside a narrower band and produced a visibly oversized left margin compared to every other admin page.

## [2.1.2] — 2026-05-17

### Added — Submission form template system (Classic / Minimal / Split)

The public ``/submissionform`` page is now templated. Three layouts ship at launch in a new ``SUBMISSION_FORM_TEMPLATES`` registry in ``app/frontend.py``: **Classic** (centered single-column card on a tinted surface — bit-for-bit identical to what previously rendered), **Minimal** (borderless, serif heading on a thin rule, intro flows into the body, no card chrome), and **Split** (sticky rail on the left with heading + subheading + intro markdown, form card on the right; collapses to one column below 880 px). The route picks the active variant via ``SiteSetting.frontend_submission_form_template`` and dispatches to a partial under ``app/templates/frontend/submission/<key>.html``; adding a future layout is one partial + one entry in the registry.

The new admin surface lives under Web Frontend → Templates → **Submission form (/submissionform)**. Each variant gets a picker card with a rendered thumbnail silhouette (classic = card-with-rows, minimal = serif-title + rule + flat lines, split = two-column side/main grid) plus the full ``tpl_customize_panel`` macro the rest of the templated sections use — per-template background colour with dark-mode pairing, dynbg key + overlay + palette config, heading font, body font, heading-size override, body-size override, all routed through the shared ``frontend_template_settings_json`` JSON bucket keyed under ``submission_form``. A Boxed / Full width radio drives ``frontend_submission_form_width_mode`` with companion max-width (480–2400 px) and side-padding (0–20 %) knobs.

New ``SiteSetting`` columns: ``frontend_submission_form_template`` (default ``"classic"``), ``frontend_submission_form_width_mode``, ``frontend_submission_form_max_width`` (default 720), ``frontend_submission_form_padding_pct`` (default 5), ``frontend_submission_form_bg_dynamic_key``, ``frontend_submission_form_bg_dynbg_config_json``. All six get matching ``_migrate_sqlite`` entries so existing installs pick up the columns additively. A new ``frontend_submission_form_template_save`` route persists the picker + layout knobs; ``submission_form`` was appended to ``_TEMPLATE_KINDS`` and the catalog-dispatch map in ``frontend_template_settings_save`` so the shared customize-panel POST endpoint also accepts the kind. Heading / subheading / intro copy and form behaviour (allowed types, submit label, success message) continue to live on the existing Forms admin surface — this release only adds the appearance dimension.

### Changed — Submission form card opts into the Primary-card design tokens

``.fe-submission-card`` no longer carries its own hard-coded ``#ffffff`` background, ``var(--fe-accent)`` border colour, custom 16 px shadow recipe, or 160 ms transition. It now pulls ``background: var(--fe-color-card-primary-bg)``, ``border: var(--fe-card-primary-border-width) solid var(--fe-color-card-primary-border)``, and inherits shadow / transition / hover lift / hover border colour from the shared Primary-card aggregator block at the bottom of ``frontend.css`` (``.fe-submission-card`` was added to both the shape-class list and the hover-class list). Dark-mode override added alongside ``.fe-mlist-card``'s rule so the card flips to ``--fe-color-card-primary-bg-dark`` / ``--fe-color-card-primary-border-dark`` in dark mode. Net effect: Site → Design → Card styles → Primary card now re-tints the submission form's card uniformly with every other primary card on the public site (meetings list, events list, fellowships, library items, etc.). Border radius stays at 16 px and padding stays at the 2 rem / 2.25 rem inset — those weren't tokenised at the site level so they remain on the card's own rule.

## [2.1.1] — 2026-05-17

### Changed — Settings modal tabs unified on a single data-card chrome

Six settings tabs (Appearance, Users, Global, Domain / Email, Timezone, Security, Sidebar) now share the same `<section class="card data-card">` chrome the Data tab introduced — brand-blue left accent, soft shadow, icon-led head with a `data-card-head` Lucide icon + title, optional `data-card-lead` description, optional right-aligned `data-card-head-actions` slot for primary buttons. Every tab is now a single-column vertical stack of these cards. Tab-specific pane CSS converged on `padding: 20px 24px; gap: 8px; flex-direction: column` with a `.data-card > .form { margin: 0; padding: 0; gap: 14px }` rule per tab so forms inside cards adopt the card's spacing instead of the global `.form { gap: 2rem }`. Dead chrome — `.appearance-pane`, `.appearance-grid`, `.appearance-theme`, `.security-grid`, `.security-col`, `.users-top-grid > .card`, `.sidebar-order-head`, `.sidebar-order-title`, every `<hr class="settings-sep">` separator inside refactored panes — is gone.

The Users tab is the one exception to "one card per section" — Create User and Roles & permissions stay side-by-side inside a single "Add a user" data-card. The permissions list reads as guidance for picking the right role on the form, not a disconnected reference, so collapsing them into one card with two `<h3 class="users-subhead">` sub-headings matches the user's expectation. All other refactored tabs render one stacked card per logical section.

### Changed — Locations card hosts the "+ New Location" button in its head

The Global tab's Locations section moved its primary action from a standalone bar at the top of the iframe (`embed-actions` div + `top_actions` block) into a new right-aligned slot inside the `data-card-head`. The slot is exposed as `.data-card-head-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; font-weight: 400 }` so any future card can use the same pattern. Companion rule `.data-card-head .btn .icon { color: currentColor }` overrides the brand-blue tint the head applies to its leading title icon so the "+" inside a `.btn-primary` doesn't render invisible against the brand-blue button background.

### Changed — Email tab renamed to "Domain / Email"; Public Domain moved there

The tab label `data-tab="email"` is now "Domain / Email" and the **Public Domain** section migrated from the Appearance tab into a new top card on this tab. Form action (`main.site_url_save`) is unchanged. The Access Request Notifications recipient field collapsed into the SMTP Server card as a single labeled input below the From-email row, eliminating the in-form `<hr class="settings-sep">` divider and the redundant inner `.u-name` sub-heading; one Save button now commits SMTP credentials + access-request recipient together. Test-email form moved to its own third data-card.

### Changed — Embed-mode data-cards keep their brand accent + shadow

`body.embed .card.data-card { ... }` restores `border-left: 4px solid var(--brand)`, `border-radius: var(--radius)`, `box-shadow: var(--shadow)`, `padding: 2rem`, `margin: 0 0 16px` inside iframe-embedded pages (Global tab, Backups admin modal, etc.). The generic `body.embed .card` rule from before this release stripped all of those for plain list cards to keep them flush inside iframes; data-cards rely on those declarations for their visual identity, so they needed an explicit override.

### Changed — Release-notes formatting: 2 rem above headings, paragraphs as bullets

In the About tab's "Release notes" `<details>`, every `<h3>` / `<h4>` subsection heading inside `.release-notes > li` now gets `margin-top: 2rem` (with a smaller `.75rem` for the very first heading in the entry so the date line + first section don't push off the top). Paragraphs that follow a heading — selected via the `h3 ~ p` sibling combinator — render as brand-bulleted list items via a `::before` content `"•"` on `padding-left: 1.15rem`. Intro paragraphs before the first heading stay as flowing prose; only body paragraphs within a subsection bullet.

### Changed — Backups dashboard widget Open Graph icon reuse

When the user opens the Manage Backups iframe modal, the existing iframe lazy-load path correctly restores `data-src` → `src` on next open even after the close handler blanks it out. Added `backups-frame` to the close-time blank list alongside `wp-import-frame`, `story-edit-frame`, `backup-wizard-frame`. (Item from 2.1.0 development log retroactively documented — the line was already in code but missing from CHANGELOG.)

### Added — Sidebar tab "Save sidebar order" button in card head

The Save button moved from inside the form body (where it sat above the description paragraph in a `sidebar-order-head` flex row) into the `data-card-head-actions` slot — clicking save no longer requires scrolling past the manual-reorder list to find it. Same right-aligned slot pattern used by the Locations card.

## [2.1.0] — 2026-05-17

### Added — Automated off-site backups (FTP / FTPS / SFTP / Dropbox)

Two new tables — `BackupTarget` (per-destination config) and `BackupRun` (per-attempt history) — back a complete off-site backup subsystem. The archive payload reuses the existing `tsp-export-<stamp>.zip` builder (DB via `VACUUM INTO` + `uploads/` + `zoom.key` + `manifest.json`), now extracted from `routes.data_export` into a shared `app.backup.build_export_archive(app)` so the manual export route and the scheduled runs produce byte-identical archives. Three backends sit behind a uniform `open/put/list/delete/fetch/close` surface in `app/backup_backends.py`: `FTPBackend` (stdlib `ftplib`, FTPS by default with a plain-FTP opt-out), `SFTPBackend` (`paramiko`, password and/or private-key auth, supports Ed25519/ECDSA/RSA/DSA key formats), and `DropboxBackend` (Dropbox SDK with chunked-upload session for >150 MB archives). All credentials are Fernet-encrypted via the existing `app/crypto.py` helpers; every delete/list path refuses non-export filenames so a misconfigured `remote_path` cannot sweep unrelated files.

`app/backup_scheduler.py` adds a single daemon thread started from `create_app()`. The thread is gated by a non-blocking `flock` on `<DATA_DIR>/.backup-scheduler.lock` so only one of the two gunicorn workers drives the loop; the loser sleeps harmlessly. `croniter` parses `BackupTarget.schedule_cron` and `compute_next_run()` writes the next firing into `BackupTarget.next_run_at` after every run. `run_target(app, target_id)` is synchronous and used by both the scheduler and the "Run now" route — it builds the archive, optionally encrypts it (PBKDF2-HMAC-SHA256 → Fernet over a passphrase, with a 21-byte `TSPB`-tagged header so the format is self-identifying), uploads, prunes remote retention only after a successful put so a botched upload cannot remove the prior good copy, writes the `BackupRun` row, updates the target's `last_status` mirror, and emails the admin via the existing SMTP path on ok→failed transitions only (no storm on consecutive failures).

The Dropbox backend wraps every API call in a `_prefer_ipv4()` context manager that temporarily overrides `urllib3.util.connection.allowed_gai_family` to return `AF_INET`. Docker's default bridge network is IPv4-only; without the override, `getaddrinfo` returns AAAA records (e.g. `2620:100:601c:19::a27d:613` for `api.dropboxapi.com`) that urllib3 tries first and the kernel can't route, producing `ENETUNREACH` (errno 101). The patch is scoped to Dropbox calls so the WordPress importer or any other `requests` consumer keeps its IPv6 capability if it needs it.

### Added — 5-step backup setup wizard as an iframe modal

Wizard pages (`backups_wizard_step1.html` through `_step5.html` + `_done.html`) match the existing WordPress importer's `wp-wizard-stepper` chrome and embed-mode pattern. Steps: **Destination** (radio cards for FTP / SFTP / Dropbox) → **Connect** (kind-specific credentials with an AJAX "Test connection" probe that round-trips a 1-byte sentinel file) → **Schedule** (preset chips + custom cron + retention count) → **Encryption** (opt-in passphrase with a "I've saved this" acknowledgement gate) → **Review** (summary + optional run-now). New `#backup-wizard-modal` lives in `base.html` with a lazy-loaded iframe pointing at `/settings/backups/new?embed=1`; the close handler blanks the iframe `src` so reopening starts a fresh wizard. In embed mode, every step's form carries a hidden `embed=1` input, the "Cancel" / "Back" links postMessage the parent (`backups-modal-close`) to dismiss the modal, and the final step renders `backups_wizard_done.html` which auto-closes after 1.2 s on success or waits for the Done click on failure.

### Added — Backups admin iframe modal (stacks above settings)

New `#backups-modal` hosts `backups_list.html`, `backups_runs.html`, and `backups_restore.html` in embed mode so the user can manage targets without leaving the settings overlay. The `backups_list` / `_runs` / `_restore` routes all accept `?embed=1` and propagate it through every redirect target (`backups_delete`, `backups_restore_post`, etc.) via a new `_backup_embed_kwargs()` helper. Inside the embedded admin, "Add backup target" postMessages the parent (`backups-open-wizard`) so the wizard modal stacks on top instead of replacing the iframe. The wizard's `backups-modal-close` handler now checks whether the admin modal is open: if so it reloads just the `backups-frame` iframe; otherwise it reloads the whole page so the Data-tab chip refreshes. The `backups-frame` iframe is added to the close-time blank list alongside `wp-import-frame`, `story-edit-frame`, and `backup-wizard-frame` so reopening any of them starts a clean session.

### Added — Off-site Backups dashboard widget

A new admin-only widget keyed `backups` joins `DASHBOARD_WIDGET_KEYS` and the `_dashboard_order` rotation, gated by `User.dash_show_backups` (defaulting True, with a matching `_migrate_sqlite` column add). The widget renders four stat tiles — Healthy / Failing / Paused (or Never run, if nothing's paused) / Total — plus the last successful backup's timestamp + target name, the soonest next scheduled run, and the four most recent `BackupRun` rows with status pills. The Failing tile flips red whenever count > 0 and the widget's title row picks up a warn-tinted nav-badge with the same count so "needs attention" reads from the dashboard at a glance. The whole interior is a single button — clicking anywhere opens the `backups-modal`. Empty state shows a "Set up your first backup" CTA that opens the wizard modal directly. The customize modal in `index.html` gained a matching "Off-site Backups" toggle row and `dashboard_customize` saves it under the existing admin-only branch.

### Added — Settings → Data tab "Off-site backups" card

New `<section class="card data-card">` block between the "WordPress importer" and "Database snapshots" sections, mirroring the existing data-card chrome (brand-blue left accent + icon-led head + lead paragraph). Renders zero or more configured targets with status pills + last-run timestamp + per-row "Manage" button; a footer row carries a primary "Set up off-site backup →" (or "Add another backup" when targets already exist) that opens `#backup-wizard-modal`, plus a secondary "Manage backups" that opens `#backups-modal`. Neither button closes the parent settings modal so the user can stack admin surfaces above the Settings overlay. A new `backup_targets()` Jinja global mirrors the existing `db_snapshots()` pattern.

### Added — Busy spinner while a backup runs

`.backup-busy` overlay (fixed inset, CSS-only ring spinner, brief explanatory copy, blocks pointer events while shown) is mounted inside the embedded backups list and on the wizard's step 5 page. It appears when any `[data-backup-runnow-form]` submits or when the wizard's "Enable target" form posts. Synchronous server-side backup can run for seconds to minutes depending on archive size and remote speed; the overlay both reassures the user the request hasn't hung and prevents double-submit.

### Changed — Inline SVG icons carry intrinsic `width`/`height` to eliminate FOUC

`_SVG_ATTRS` in `app/icons.py` gained `width="24" height="24"`. Before this, an inline `<svg class="icon">` with no dimension attributes stretched to fill its parent container during the brief window before `app.css` loaded the `.icon { width: 1em; height: 1em }` rule — visible inside any iframe (most prominent: the `cloud-upload` icon in the backups list rendering at full modal width before settling to 1em). CSS specificity still wins once the stylesheet parses, so existing sizing is preserved; the attributes only matter during the FOUC window. Affects every Lucide icon site-wide.

### Changed — Appearance settings tab refactored to single-column data-card stack

Six sections — Theme, Sidebar Footer Logo, Login Screen, Open Graph / Link Previews, Home Screen Icon, Public Domain — are each wrapped in `<section class="card data-card">` with a `data-card-head` (Lucide icon + title) and `data-card-lead` description, matching the chrome the Data tab already used. The two-column `.appearance-grid` and `<hr class="settings-sep">` separators are gone; the cards stack vertically with each card's brand-blue left accent + shadow providing the visual separator. All form actions, file inputs, IDs, and JS hooks (theme picker, login FX preview, OG image preview, Apple-touch icon preview, login transition toggle) are preserved — behavior is unchanged. Dead CSS (`.appearance-pane`, `.appearance-theme`, `.appearance-grid` two-col rules, and their media-query overrides) was removed; a small ruleset normalizes forms inside the new data-cards to a 10 px gap so the card head + lead paragraph carry the visual spacing instead of the form's default 2 rem `gap`.

### Changed — Backups modal uses 2 rem inset chrome with full-width children on desktop

`.backups-wrap` now wraps all three embedded pages (list / runs / restore). In embed mode the `.embed-content` shell's default 20 px padding is zeroed (via `:has(> .backups-wrap)`) and `.backups-wrap` owns the full 2 rem padding on desktop, scaling back to 1 rem below 720 px. The previous `max-width: 960px` constraint is dropped in embed mode so target rows / activity rows fill the panel width — read directly inside the modal without an awkward narrow inset.

### Fixed — Dropbox backend ENETUNREACH on Docker bridge networks

Symptom: "Dropbox connect failed: HTTPSConnectionPool(host='api.dropboxapi.com', port=443): … Network is unreachable" on a Docker container with the default bridge network. Cause: `getaddrinfo` returned both A and AAAA records; urllib3's connection pool tried the AAAA address first and the kernel had no route. Fixed by scoping a `_prefer_ipv4()` context manager around every `DropboxBackend` SDK call. See the Added section above for full details on why the patch is scoped (other parts of the app that legitimately use IPv6 are untouched).

## [2.0.4] — 2026-05-17

### Fixed — Macro-rendered dashboard widgets were missing drag handles + draggable attribute

Three dashboard widgets (Recent Deletions, Frontend Visitor Metrics, Contact Form) rendered without `draggable="true"` and without the `dash-drag-handle` span. The macro in `templates/_dash_widget.html` gated both on `{% if can_reorder %}`, but `can_reorder` was being set with `{% set can_reorder = true %}` inside `{% block content %}` in `templates/index.html` — Jinja's `with context` import does not reliably surface block-scoped `{% set %}` variables into the imported macro, so the gate evaluated as falsy and silently dropped both pieces of markup. The inline widgets (server-metrics, currently-online, access-requests) worked fine because they reference `can_reorder` from inside the block where it was set. The macro is dashboard-only and every dashboard widget is meant to be reorderable, so the gate is gone — `draggable="true"` and the handle span now render unconditionally inside the macro.

### Changed — Dashboard widget grid is now a CSS-Grid pseudo-masonry layout

`.dash-grid` switched from `grid-template-columns: 1fr 1fr; align-items: start` (which left awkward vertical gaps whenever the two columns' widgets had divergent heights) to a fine 8 px `grid-auto-rows` track with `grid-auto-flow: row dense` and a companion JS layout pass (`initDashboardMasonry` in `app/static/js/app.js`). The JS measures each widget's rendered `getBoundingClientRect().height`, computes `span = ceil((height + 16) / 8)` (the 16 px visual gap between widgets is folded into the span — actual `row-gap` is 0 because a real row-gap would multiply across every fine row track and explode the layout), and writes the result to `widget.style.gridRowEnd`. `dense` flow then back-fills earlier vacant tracks with later, shorter widgets so the dashboard packs tight. Recompute triggers: deferred initial run via `requestAnimationFrame`, `window.load` (covers late-loading fonts / icons), debounced `window.resize`, `ResizeObserver` per widget (covers live polling widgets whose content height changes), and after every drag-reorder commit (the reorder handler now calls `window.__tspDashLayout()`). Below the 720 px breakpoint the grid collapses to a single column with normal `row-gap: 16px` and the JS skips span assignment. `.dash-widget` carries a `grid-row-end: span 40` placeholder for first paint (uses the longhand so the JS-set `gridRowEnd` cleanly overrides — the shorthand `grid-row: span 40` expands to `grid-row-start: span 40; grid-row-end: auto` and would conflict).

### Changed — Dashboard widget drag handle: always visible chip, top-left of widget

`.dash-drag-handle` moved from absolute `top: 10px; right: 12px` at `opacity: 0.55` (revealed to 1 only on widget hover) to `top: 10px; left: 10px` at full opacity at rest, with a `var(--panel-2)` background, `var(--border)` border, and 6 px radius. Old placement disappeared behind right-aligned "View all" links and right-aligned `card-head` metadata text on most widgets, so even when the icon was rendered it was effectively invisible. Hover/active states still tighten the visual cue (brand-tinted bg, brand-tinted border) but the resting state is now a first-class affordance instead of a near-invisible ghost icon. To avoid the chip overlapping titles: `.dash-widget .card-head { padding-left: 38px; }` insets every `card-head` title; two widgets without a `card-head` get targeted padding (`.access-requests-card .ar-title` gets `padding-left: 38px`; `.server-metrics .role-panel` gets `padding-top: 18px` to clear the chip on the left column only — the right server-stats column stays at its natural top).

## [2.0.3] — 2026-05-16

### Fixed — Watchtower logged docker-bridge IPs instead of real client IPs

Production deploys (install.sh) front gunicorn with Caddy, which sets `X-Forwarded-For`, but the Flask app wasn't wrapped in `ProxyFix` — so `request.remote_addr` returned the Caddy container's bridge address (typically `172.x.x.x`) on every request. Every downstream consumer (`__init__._ip_block_gate`, `__init__._block_known_probes`, `activity._client_ip`, `auth.login` ip captures, `frontend` turnstile + contact form ip captures) inherited the wrong value, so Watchtower's Access / Visitors / Requests panels and the IP-blocklist all keyed off the proxy IP. `create_app` now wraps `app.wsgi_app` in `werkzeug.middleware.proxy_fix.ProxyFix` with `x_for=x_proto=x_host` set from a new `TSP_TRUSTED_PROXIES` env var (default 1 hop, matching the Caddy → gunicorn topology; set to 0 to disable for direct-bind deploys that don't want to trust spoofable forwarding headers). `visitor_metrics._client_ip` lost its hand-rolled XFF parser since `request.remote_addr` is now correct everywhere. Operator note: any pre-existing `IPBlock` rows that captured docker-bridge addresses are now dead — they no longer match real client traffic and should be cleared from the Watchtower IP-block panel.

### Fixed — Library item thumbnails 404'd for logged-out visitors

`reading_thumbnail` (`/readings/<rid>/thumbnail`) carried a blanket `@login_required` decorator, so the public Literature Library page (`frontend/literature_library.html`) and any page-block referencing a library item thumbnail (`_blocks.html`) rendered broken images to anonymous visitors. The route now serves the file when the user is authenticated **or** when both `LibraryItem.public_visible` and the parent `Library.public_visible` are True — matching the visibility gate the Literature Library page itself already enforces. Private libraries and admin-hidden items continue to 404 to anonymous traffic.

## [2.0.2] — 2026-05-16

### Added — Dynbg "Use pastels in light mode only" toggle

A new boolean field `pastel_light` joins the dynbg config dict (encoded/decoded by `dynbg.encode_config` / `dynbg.decode_config`, persisted into the existing `bg_dynbg_config_json` column with opt-in semantics — only `True` survives the encode so the column stays minimal). The dynbg-picker modal's Colours panel grew a new checkbox **Use pastels in light mode only**; the trigger button partial (`_dynbg_picker.html`) carries the hidden input + `data-dynbg-pastel-light` / `-input` attrs so the modal's get/set/open/save/clear flows all round-trip the value. The per-template Customize panel's pseudo-cfg (`frontend_templates.html`) and every per-page picker include the new field. The page-hero modal's client-side JSON builder, the block-editor's `dynbgTrigger` helper, and the page hero's trigger-populate path were all updated to thread `pastelLight` through.

New `pastelize(hex)` helper in `dynbg.py` produces a soft variant via HLS — preserves hue, caps saturation, and lifts lightness into a tunable band. `colors_to_css_vars(colors, cfg)` now emits a companion `--fe-dynbg-cN-light` for every colour when `cfg.pastel_light` is True. Special case: when `pastel_light` is on but the admin hasn't picked custom colours, three hardcoded pale tints (cool / warm / mint) are emitted as the light-mode fallback so the surface still softens instead of falling through to the preset's vivid brand-derived defaults. Three CSS rules under `html:not([data-theme="dark"]) [style*="--fe-dynbg-cN-light"]` re-bind `--fe-dynbg-cN` to the companion in light mode — `!important` is required because the canonical `--fe-dynbg-cN` is set inline on the same element and inline custom-property declarations otherwise outrank stylesheet rules.

15 frontend detail / list templates (meetings, events, stories, blog detail + list, archive, fellowships, literature library, printlist, announcements, site index variants) were converted from a hand-rolled inline `{% for _c in _resolved %}--fe-dynbg-cN: …{% endfor %}` loop to the canonical `dynbg_colors_css(dynbg_resolve_colors(cfg), cfg)` helper call so they emit the pastel companion vars uniformly with the list-page templates already using the helper. 9 list-template runtime cfg dicts (`meetings_list`, `events_list`, `blog_list`, `fellowships_list`, `archive`, `literature_library`, `printlist`, `stories_list`, `announcements_list`) gained a `'pastel_light': X.get('bg_dynbg_pastel_light', False)` entry. The template-level pastel band currently sits at saturation cap 0.339 and lightness 0.69–0.75 — produces confident dusty tints (cornflower, blush, sage, terracotta, ochre) rather than near-white washes.

### Added — Library item summary field + Add modal redesign + lightbox + external-link marker

A new optional plain-text `summary` column on `LibraryItem` (Text, additive migration) shown as a 3-row textarea in both the Add and Edit modals plus the standalone `reading_form.html`. The label notes the 500-character cap and a live `<N>/500 remaining` counter beneath the textarea ticks down on input — counter goes red + bold when remaining hits 0. Counter is wired generically: any textarea with `[data-summary-input]` paired with a sibling `[data-summary-counter]` (containing `[data-summary-count]`) gets the live readout.

The Add modal swaps the old two-mode Upload / Paste toggle for a three-way segmented control (`.content-mode-seg`) — **Upload file / file browser**, **Paste / type content**, **External link** — with each option owning exactly one content slot. Switching modes hides the others (`hidden` attribute + `disabled` inputs so the browser doesn't submit them); saving in a given mode clears the slots it doesn't use. The modal trigger button, header, and submit button all rename from *Add File* / *Upload* to **Add Item** / **Add item**. The Edit modal got the same treatment — header renamed to **Edit Item**, default mode derived from existing data (file → upload, body → paste, url → link, empty → upload). Updated `_apply_reading_form` enforces single-channel content per item; empty/legacy submissions still fall back to the old permissive shape so historical posts keep working.

Frontend library list (`templates/frontend/literature_library.html`) now renders the summary directly under the filename / external link URL via a new `.fe-library-item-summary` paragraph (0.875rem, `white-space: pre-wrap` so multi-line summaries preserve line breaks). External-link cards (no in-house file takes precedence) carry a small `external-link` Lucide icon in the top-right corner via a new `.fe-library-item--external` modifier — visually telegraphs the click leaves the site. The entire card became clickable via a stretched-link `::after` overlay on the title anchor; the thumbnail wrapper lifts above the overlay (`z-index: 2`) and opts into the existing `frontend/_lightbox.html` partial via `data-lightbox-scope` so clicking the thumbnail opens the image viewer instead of navigating with the title link.

### Changed — `_apply_reading_form` enforces single-channel content per item

The library-item save handler in `routes.py` was reworked so each mode owns exactly one content slot — `upload` clears body + url, `paste` clears file + url, `link` clears file + body. Empty/legacy submissions without a `content_mode` flag still fall back to the old permissive shape so historical posts keep working. New items can never accidentally carry both a file and a URL the way some legacy rows could.

### Changed — Sinewave background reads more organic

`renderSineGradient` in `login_fx.js` gained a third sine component (`f3Mul` / `amp3` / `phase3`) plus a slow y-axis modulation (`yMod` / `yAmp`) that shifts each scan-line slightly from the one above. Pure left-right symmetry breaks; the bands bend more like a real fluid surface. `randomWaveParams()` widened the per-component range and adds the new keys so randomised waves get noticeably varied shapes between renders. Existing stored waves missing the new keys fall through to the new defaults — same generator, richer canonical look. Applies anywhere the sinewave style is used (page hero, footer background).

### Changed — Footer chip hover keeps inherited text colour

`.fe-footer-location-directions:hover`, `.fe-footer-admin-login:hover`, and `.fe-footer-block-powered-by a:hover` now use `color: inherit` instead of swapping to the brand link colour — only the surface tint deepens on hover, text stays white (or whatever the footer chrome's resting text colour is). The `--logout` modifier (yellow background, black text) sets its own colour further down and is unaffected.

### Changed — Meeting card title weight on the homepage

`.fe-meeting-card-link` (the `<a>` inside the `<h3>` for each meeting tile in the homepage Meetings block) now explicitly sets `font-weight: 600`. Previously the weight was inherited from the wrapping `<h3>` (typically 700) which read heavier than other card titles on the same page.

### Fixed — `<fieldset class="fieldset" hidden>` was still rendering

The base `.fieldset` rule in `app.css` set `display: flex; flex-direction: column; …`, which beat the user-agent stylesheet's `[hidden] { display: none }` and kept hidden fieldsets visible. Added `.fieldset[hidden] { display: none; }` so any panel toggled via the `hidden` attribute (library content-mode picker, future toggled fieldsets) actually disappears.

### Added — Mobile-specific mega-menu animation + fade controls

Three new `SiteSetting` columns + admin UI under *Web Frontend → Navigation → Mega menu appearance → Mobile (≤ 720 px)*: `frontend_megamenu_animate_mobile` (bool, default True; toggles the staggered link entrance under the mobile breakpoint independently of the desktop toggle), `frontend_megamenu_animate_mobile_ms` (int, default 320; mobile-only stagger speed slider, 100–1500 ms), and `frontend_megamenu_panel_fade_mobile_ms` (int, default 180; mobile-only panel-fade speed slider, 0–1500 ms). All three are clamped to the same ranges as their desktop counterparts in the save handler, and additive `_migrate_sqlite` entries land them on existing installs. Renderers (`frontend/megamenus/classic.html` + `frontend/megamenus/recovery-blue.html`) stamp `--fe-mm-fade-ms-mobile` and (recovery-blue only) `--fe-mm-reveal-ms-mobile` in the panel's inline style and add a `fe-megamenu-animate-mobile-off` class when the toggle is off. One new `@media (max-width: 720px)` block in `frontend.css` re-binds `--fe-mm-fade-ms` / `--fe-mm-reveal-ms` to the mobile variants so every existing consumer (panel fade transition, recovery-blue reveal keyframes) swaps automatically, and the off-class zeroes the stagger keyframes under the same breakpoint. Admin form's `wireSpeed` helper now tolerates null toggle/row selectors so a standalone slider (the mobile fade speed has no companion toggle — the desktop *Show on hover fade* toggle still gates whether the fade runs at all) wires only the live readout.

### Added — Floating "Edit post" affordance on every blog detail template

A new `templates/frontend/_blog_edit_button.html` partial stamps a fixed-position chip in the bottom-right of `/blog/<slug>` for signed-in editors. Gated on `current_user.is_authenticated and current_user.can_edit() and not is_preview` — suppressed when the existing draft / archived preview banner already carries an edit link, so signed-in editors visiting a draft don't see two stacked edit affordances. Includes a pencil icon + "Edit post" label that collapses to icon-only below 640 px so the chip doesn't crowd the reading column on mobile. Dark-mode flip swaps the dark-on-light pill for a light-on-dark variant. Included in all four detail templates (classic / modern / cover / longform) right after the preview-banner include.

### Added — `admin_login` mega-menu link kind with auth-aware Login / Dashboard + Logout button row

A new `kind="admin_login"` value joins `link | title | button | section | search` in `FrontendNavLink._NAV_BLOCK_KINDS`, with a default label of `"Login"` baked into `_NAV_DEFAULT_LABEL`. The per-column add-row in `_nav_megacol.html` now includes a `+ Admin login` button so admins can drop one into any mega-menu column. In the editor (`_nav_megalink.html`), the kind suppresses the editable label + URL inputs (both are managed by the renderer) and replaces them with an explanatory note; it keeps every other styling field a regular `link` kind exposes (icon before / after, per-link size slider via `link_size_pct`, color override, open-in-new-tab) AND adopts the `button` kind's Style picker (Pill / Rounded). Form-trigger is hidden because the auto-managed href would always win.

Both megamenu renderers (`frontend/megamenus/classic.html` + `frontend/megamenus/recovery-blue.html`) grew a dedicated `elif _k == 'admin_login'` branch so the kind renders as a button (not a link). Anonymous visitors see a single **Login** chip → `url_for('auth.login')`. Authenticated users see a flex row with two chips: **Back to TS Pro dashboard** → `url_for('main.index')` on the left and **Logout** pushed to the far right via `justify-content: space-between`. The row wrapper (`.fe-megamenu-classic-block-authrow` / `.fe-megamenu-block-authrow`) bundles `--i` (existing animation index) and `--fe-mm-link-scale` (per-link size override) into one inline `style=""` so the entire pair scales together when the admin moves the size slider. Default icons (`log-in` on Login, `layout-grid` on Dashboard, `log-out` on Logout) auto-render when the admin hasn't picked an icon, matching the footer admin_login block's hardcoded icons.

### Added — Footer admin_login block flips to a Dashboard + Logout pair on sign-in

`templates/frontend/footers/blocks/_admin_login.html` now branches on `current_user.is_authenticated`. Signed-out visitors see the existing single **Login** pill. Signed-in users see a new `.fe-footer-admin-login-row` flex container with two pills — **Back to TS Pro dashboard** (`layout-grid` icon) on the left and **Logout** (`log-out` icon, `--logout` modifier) on the far right via `margin-left: auto`. Both pills reuse the existing `.fe-footer-admin-login` recipe so surface / border / hover stay consistent with the meeting-locations block.

### Added — `auth.logout` honours a validated `?next=` redirect target

`auth.logout` now reads `?next=` from the query string and redirects there when the value is path-only (`/...`) and not protocol-relative (`//...`). Invalid or missing `next` falls back to the historical `auth.login` redirect, so admin-side logout links keep their old behaviour. All three frontend logout links (mega-menu classic + recovery-blue, footer block) now pass `next=url_for('frontend.index')` so signing out from a public page returns the visitor to the homepage instead of the admin sign-in screen. The path validation closes any open-redirect smuggle — `?next=//evil.example.com/x` falls through to the login screen.

### Changed — Mega-menu button-styled kinds (admin_login, kind=button) honour the per-link size slider

`.fe-megamenu-classic-block-btn` and `.fe-megamenu-block-btn` now compute `font-size: calc(0.875rem * var(--fe-mm-link-scale, 1))` (or `0.9375rem` for the recovery-blue variant). Previously the size slider in the admin editor only affected `link`-kind anchors; button-styled kinds ignored it entirely. The default scale of 1 keeps existing button rendering byte-identical when the admin hasn't toggled the override.

### Changed — admin_login mega-menu chips inherit the base button look + carry a Logout yellow modifier

`.fe-megamenu-classic-block-btn--admin-auth` / `.fe-megamenu-block-btn--admin-auth` is a layout-only marker class — 7 px top/bottom padding and `width: auto; align-self: flex-start` (with `.fe-megamenu-recovery-blue` prefix so it beats the existing `width: 100%` rule for recovery-blue buttons). Background, border, text-color, and hover are all left to the underlying `.fe-megamenu-*-block-btn` base recipe so the chips match the existing `kind="button"` rendering — solid accent surface in classic, translucent-white in recovery-blue. Pill / rounded shape still comes from the admin-picked `-pill` / `-rounded` modifier so the editor's Style dropdown isn't a no-op. The `.fe-megamenu-classic-block-btn--logout` / `.fe-megamenu-block-btn--logout` modifier paints the Logout chip in opaque amber-yellow (`#facc15`) with black text in both themes; hover deepens to `#eab308`. A parallel `.fe-footer-admin-login--logout` modifier carries the same amber palette in the footer.

### Changed — Sidebar admin section keeps Contact Form alongside Watchtower

`_ADMIN_CATALOG` in `sidebar.py` lost the legacy `access_requests`, `user_log`, and `delete_log` rows when Watchtower absorbed them in 2.0.0; this release also drops their visibility checks from `_is_visible` since the catalog entries no longer exist. (Their POST action endpoints had already moved under `/watchtower/...` namespaced endpoints.)

## [2.0.1] — 2026-05-16

### Fixed — Meetings-list cards no longer render translucent in dark mode

Cards on the public meetings list (`.fe-mlist-card`) had two stacked dark-mode rules in `frontend.css`. The earlier one painted them at `rgba(5, 8, 15, 0.85)`, the later one at `rgba(255, 255, 255, 0.03)` — and the later rule won, producing a 3% white wash that read as transparent over the page surface. Both rules are now consolidated and point at the Primary-card design tokens: `background: var(--fe-color-card-primary-bg-dark, #131a33)` and `border-color: var(--fe-color-card-primary-border-dark, #1f2a44)`. Cards are now solid and re-tint when the admin edits *Site → Design → Card styles → Primary card → Background (dark)*. Light mode is unchanged.

### Changed — Pro Tips cards adopt the Primary-card design-token recipe

Each `.fe-faq-item` inside the standalone Pro Tips section (`_protips.html`) and the inline Pro Tips block on the sidebar meetings-list layout (`meetings_list/sidebar.html`) now carries an `fe-card-primary` opt-in class. The class is the canonical Primary-card surface (background / border / border-radius in light + dark, plus the shared `.fe-card-primary:hover` aggregator's lift + shadow + hover-border transition), so a single tunable point — *Site → Design → Card styles → Primary card* — drives meetings-list cards AND Pro Tips cards together. Three CSS rule blocks that were duplicating or fighting the recipe were removed: the hardcoded `.fe-mlist-protips-inline .fe-faq-item` light-mode bg + border, its `:hover` block, and the dark-mode override that pinned the Pro Tips bg to a translucent white. Kept the `.fe-mlist-protips-inline .fe-faq-item.is-open` accent-border rule since the hover aggregator doesn't address the open state.

## [2.0.0] — 2026-05-16

### Added — Watchtower: unified admin security + observability console

A new top-level admin module at `/tspro/watchtower` that consolidates four pre-existing surfaces (User Log, Delete Log, Access Requests, Visitor Metrics) into a single five-tab dashboard and layers new security primitives on top. **Overview** tab carries seven KPI tiles (views today / uniques today / online now / failed logins 24h / blocked IPs / pending requests / files in trash), a system-health card (CPU / memory / load / uptime, each with progress bars), a 30-day visitor SVG line+area chart, a 24-hour failed-login bar chart with red/amber/grey heat colouring, a rule-based anomaly banner (`brute-force attempt in progress` / `elevated failed-login volume` / `concentrated attack from <IP>`), a top suspicious-IPs leaderboard with one-click Block/Unblock, a recent-activity feed, an active-sessions table with force-end actions, and the live IP blocklist. **Visitors** mirrors the old visitor-metrics page inside the new shell. **Access** ships a failed-login leaderboard (Block / Unblock / Clear per IP), a manual IP-ban form (permanent or 1h / 24h / 7d / 30d), the active blocklist with hit counters, account-scoped activity feed (truncated to 20 rows with an inline expand button; the infinite-scroll sentinel only un-hides after expansion so collapsed feeds don't trigger API pages), and the login-sessions table with force-end. **Deletes** carries the same recycle-bin restore/purge workflow as before. **Requests** carries pending password resets, 30-day reset history, and the active/archived access-request inbox with Create User / Mark Handled / Archive / Delete actions.

The data layer lives in a new `app/watchtower.py` (helpers for KPI counts, daily/hourly time series, anomaly rules, top failed-login IPs joined against the IPBlock table, active-session listing, recent admin activity, IP ban/unban, login-failure clearing, session force-end, system snapshot passthrough). Templates live under `app/templates/watchtower/` with a shared tab strip partial. The five view routes plus four state-mutating action endpoints (`watchtower_ban_ip`, `watchtower_unban_ip`, `watchtower_end_session`, `watchtower_clear_failures`) and the six relocated action endpoints (`watchtower_delete_restore` / `…_purge`, `watchtower_request_handled` / `…_archive` / `…_unarchive` / `…_delete`) are all `@admin_required` and write to `ActivityLog` so every ban / unban / end-session / clear / restore / purge / request-mutation is auditable. Sidebar `_ADMIN_CATALOG` was condensed — User Log, Delete Log, and Access Requests entries are removed in favour of a single **Watchtower** row that carries the pending-access-request badge.

### Added — IP blocklist with admin-managed request gate

New `IPBlock` model (`ip`, `reason`, `blocked_by` → User FK, `blocked_at`, `expires_at`, `hit_count`, `last_hit_at`) plus a new app-level `before_request` hook that resolves the request's `REMOTE_ADDR` against the table on every inbound request, returns a flat 403 with `Cache-Control: no-store` for an unexpired match, and stamps `hit_count` + `last_hit_at` on the matching row so the dashboard can see whether a ban is actually being exercised. Expired rows get lazily deleted on the request that would have matched them so the blocklist self-cleans without a separate cron. The hook is the first `before_request` in the chain (ahead of the probe-blocker) so a banned IP gets cut off even on asset requests. `db.create_all()` handles the new table on fresh installs; no migration entry needed.

### Changed — Watchtower replaces the three legacy admin surfaces (User Log, Delete Log, Access Requests)

The standalone `GET /tspro/user-log`, `GET /tspro/delete-log`, and `GET /tspro/access-requests` routes are removed (now 404). Their templates (`user_log.html`, `delete_log.html`, `access_requests.html`) are removed too. The six action POST endpoints were renamed in place under the Watchtower namespace: `delete_log_restore` → `watchtower_delete_restore` (`/watchtower/deletes/<rid>/restore`), `delete_log_purge` → `watchtower_delete_purge`, `access_request_handled` → `watchtower_request_handled`, `access_request_archive` → `watchtower_request_archive`, `access_request_unarchive` → `watchtower_request_unarchive`, `access_request_delete` → `watchtower_request_delete`. Every internal `url_for(...)` reference was migrated — `_ENDPOINT_LABELS` (the global label dict used by the omnibar / breadcrumb resolver), the dashboard's Recent Deletions + Access Requests + Online Users tiles, the `_ulog_event.html` partial's user-deep-link, and the global-search Users section. The `GET /tspro/api/user-log-events` endpoint is preserved unchanged — it backs the activity-feed infinite scroll on the Access tab. Legacy sidebar visibility keys (`access_requests`, `user_log`, `delete_log`) were dropped from `_is_visible` since their catalog entries no longer exist.

### Added — Light/dark page background override on per-template customize panel

The *Web Frontend → Templates* customize panel's **Override page background color** control now carries a **Dark mode** dropdown next to the light-mode swatch with three options: **Same as light** (no override; default), **Auto (Surface — Darkmode token)** (emits `var(--fe-color-surface-dark)` so the dark variant tracks the site's Design palette), and **Manual** (reveals a dark-mode colour swatch that ships an arbitrary hex). `template_css_vars` (`app/frontend.py`) emits `--tpl-bg-dark` alongside `--tpl-bg`; a single new rule in `frontend.css` — `html[data-theme="dark"] [style*="--tpl-bg-dark"] { --tpl-bg: var(--tpl-bg-dark) !important; }` — swaps the live variable so every existing `var(--tpl-bg, …)` consumer (blog detail, hyperlist, stories, list pages, etc.) flips automatically with no per-template CSS. Data rides the existing `SiteSetting.frontend_template_settings_json` (no schema migration); `template_settings` loader pass-through was extended to whitelist the new `bg_dark_mode` / `bg_dark` keys so they survive the round-trip from JSON back into the renderer. `frontend_template_settings_save` drops the implicit `'same'` mode from JSON to keep the leaf lean.

### Fixed — Hover border-color flicker on classic blog detail's reading surface

`.fe-blog-cls-main` / `.fe-blog-cls-widget` / `.fe-blog-cls-bio` carry `.fe-card-primary`, so they inherited the global card hover token (`--fe-color-card-primary-hover-border`) — visible as a border colour shift on hover even though the existing suppression rule tried to neutralise it. Two fixes: `border-color` is dropped from the transition list on these three elements (no animation runs even if a hover token leaks through), and a parallel `[data-theme="dark"]` suppression rule resets to `--fe-color-card-primary-border-dark` instead of the light-mode token (the old rule restored the light border value in dark mode, producing a perceptible flicker on hover).

## [1.10.5] — 2026-05-15

### Added — Section block (nested container) inside the blog body editor

A new `section` block type ships in the body editor's palette — the first block that holds other blocks. State storage gains a recursive child list (`data.blocks`) plus two numeric margin controls (`data.margin_top` / `data.margin_bottom`, in rem; default 3 / 3, range 0–20, step 0.25). The renderer in `_blog_blocks.html` emits `<section class="bb-section" style="margin-top: Nrem; margin-bottom: Nrem;">` and recursively renders children through the same `render_blog_block` macro so a Section with nested paragraphs / headings / callouts / etc. produces the same markup it would at the top level. The new `bb-section` CSS in `frontend.css` zeroes first / last child margins so the inline section margin wins without margin-collapse weirdness.

Editor JS got a substantial drag-and-drop refactor to support nesting. Mutation helpers (`moveBlock`, `duplicateBlock`, `deleteBlock`, `insertBlockAt`) now thread a `host` array reference so they operate on the right list — top-level `blocks` OR a section's `data.blocks`. Each section's inner canvas is a `[data-pbe-zone]` element tracked in a `WeakMap` keyed to its host array; the outer canvas's drag handlers delegate to whichever zone the cursor is in, so adding a section instantly spawns a working drop zone without extra listener wiring. A `_dragSource` closure variable captures the source host at dragstart, letting cross-zone moves splice the block out of the right array regardless of where the user drops it. Reading-time estimation recurses into section children so prose inside sections still counts toward the auto-computed minutes.

Server-side `_sanitize_blog_body_blocks` was split into a list-walking helper (`_sanitize_blog_block_list`) so the section's recursive children get the same field coercion + length caps. Nesting is hard-capped at depth 1 — a Section can't contain another Section. The 200-block-per-list ceiling applies at every level. A new `margin_rem(value, default)` helper coerces the rem inputs to floats, clamps to 0–20, and rounds to 2 dp so the JSON column doesn't accumulate input-rounding noise.

### Added — Container width control on the blog detail page (`/blog/<slug>`)

Three new columns on `SiteSetting` mirror the existing blog-list shape: `frontend_blog_post_width_mode` (`boxed` / `full`, default `boxed`), `frontend_blog_post_max_width` (px, 640–2400, default 1160), `frontend_blog_post_padding_pct` (vw, 0–20, default 5). Additive `_migrate_sqlite` entries land them on existing installs. A new "Container width" fieldset in *Web Frontend → Templates → Blog detail* — same two-radio + max-width + padding-pct shape as the Blog list controls — posts to the existing `frontend_blog_post_template_save` route, which now reads and clamps all three values. All four detail templates (classic, modern, cover, longform) apply the chosen width through the shell wrapper: boxed mode swaps in the `.fe-container` class with `style="max-width: Npx;"`; full mode uses a per-template `*-shell--full` modifier and `padding-left/right: Nvw;` viewport gutters. Longform's hardcoded narrow-essay 680px shell is overridden via inline `max-width: none` in full mode so the admin's setting actually lands.

### Added — Draft / archived blog posts are previewable on the public URL when signed in

`blog_post_detail` was filtering candidates through `_blog_visible_query()`, so signed-in editors hitting `/blog/<draft-slug>` got a 404 — they had to publish first to verify how a post would actually render. The view now bypasses the visibility filter when `current_user.can_edit()` is True, walking the full query in those cases (still ordered by pinned + published-at desc). Anonymous visitors still get the 404 path — nothing about the public surface changed for them. A new `templates/frontend/_blog_preview_banner.html` partial is included at the top of all four blog detail templates (classic / cover / modern / longform) and stamps an amber banner with a "Draft preview" or "Archived preview" tag, a short explanation of why a regular visitor wouldn't see this page, and a one-click "Edit post →" link straight to `/tspro/blog/<id>`. Visible only when `is_preview` is True (the view sets it for any unpublished state when `can_preview` resolved to True), so published posts get zero extra chrome.

The View on Frontend admin button in `blog_edit.html` used to be hidden whenever `_p.is_draft` or `_p.is_archived` was True (the link would have 404'd). Now it always shows when the Web Frontend module is on, and the label flips to **Preview draft ↗** / **Preview archived ↗** / **View on Frontend ↗** based on state so the editor knows what they're about to open.

### Changed — Hyperlist permanently dark + week starts Sunday

`templates/frontend/hyperlist.html` was a light-by-default template with a `@media (prefers-color-scheme: dark)` block flipping it to a near-black palette under the OS preference. The whole `@media` block was removed and every light-mode declaration in the base stylesheet was rewritten to the dark palette (body bg `#0a0a0a`, ink `#f5f5f5`, cards `#131313`, links `#8ab4ff`, focus rings `#ffd700`, live region `#2a2400 / #ffd700`). The template is now decoupled from the site's light/dark toggle AND from the visitor's OS preference — it's deliberately, permanently black. The header doc comment was updated to match.

The week ordering was rotated so Sunday renders first. The underlying `MeetingSchedule.day_of_week` enum stays the project-wide 0=Mon..6=Sun convention; only the rendered section order changes. After per-day buckets are populated and sorted, `day_buckets = [day_buckets[6]] + day_buckets[:6]` shifts Sunday to the front so the template renders Sunday → Saturday — same ordering pattern the `meetings_list` view already uses.

Also: the search-hint text "Filter is optional — without JavaScript every meeting stays visible." was removed from the search row. The `/`-key and Escape-key shortcuts are still documented inline.

### Added — Visual drag-and-drop blog post body editor

The blog admin's body field flipped from a single Markdown textarea to a visual block editor mounted in `app/templates/blog_edit.html` and powered by a new `app/static/js/post_body_editor.js` (~700 lines). State lives in a `blocks` array of `{id, type, data}` dicts; every mutation re-renders the canvas and writes the JSON-serialised tree (sans ephemeral ids) to a hidden `body_blocks_json` input via the `commit()` helper, so a normal form submit round-trips the latest state without any "did the editor flush?" race. Ten block types ship out of the gate — paragraph, heading (H2/H3/H4), image, button, list (bulleted / numbered with Enter-to-add + Backspace-to-remove), quote, callout (info / success / warn / danger), separator, video (YouTube / Vimeo URL → auto-detected iframe embed, or self-hosted MP4 → `<video>`), and code. Each block carries a left drag handle (HTML5 native DnD), a top toolbar (type chip + move-up/down/duplicate/delete), and a per-type editor body. The floating "Add block" pill reuses the existing `.fe-page-palette-floating` chrome from the page builder — same FAB → expanding panel animation, click-to-append OR drag-to-position semantics, animated insert-marker that shows the exact drop slot. The legacy Markdown `body` column stays on `BlogPost` as a fallback so unconverted posts keep rendering identically until the writer re-saves with blocks; the public render path in the four blog detail templates (classic / cover / modern / longform) now branches on `post.body_blocks` and falls back to `(post.body or '')|markdown`. Storage is a new `body_blocks_json TEXT` column on `blog_post` (additive migration in `_migrate_sqlite`), sanitised on save through `_sanitize_blog_body_blocks` in `app/routes.py` — unknown block types are dropped, string fields are length-capped, and the list is hard-capped at 200 blocks so a forged form post can't smuggle arbitrary HTML or oversized payloads into storage. Output renders through a new `app/templates/_blog_blocks.html` partial that emits `.bb-*`-scoped markup with frontend CSS styles appended to `frontend.css`. The image block carries an inline file-library picker — the same `/tspro/files/images.json` modal as the page-builder image block — so writers can drop an existing upload into a block without re-uploading; the picker callback now hands the entire `MediaItem` dict back to consumers so both the body image block AND the new featured-image picker (see below) can pull the id when they need it.

### Added — Refactored blog edit page — two-column layout with merged settings sidebar

The edit page split into a flex grid: a main column (Post + Body cards) that expands to fill every pixel between the app sidebar and the metadata column, and a metadata column (~280–340px) that holds publish state + author + taxonomy + featured image in one merged "Post settings" card. The metadata column collects four sub-sections separated by hairline dividers + section headings so the four groups feel discrete without fragmenting into separate cards. Categories ditched the pill UI for a vertical checklist (one row per category, color swatch on the left, scrollable when the list gets long, brand-tinted highlight when checked); tags got the same treatment so the two taxonomy widgets read as siblings. Both ship with an inline "Add" affordance — a text input + button row that POSTs to new `blog_category_quick_add` / `blog_tag_quick_add` JSON endpoints, which mint (or dedupe by case-insensitive name) the row and return the new id/name; the JS appends a pre-checked row to the list and clears the input so the writer can stack several new categories / tags in a row without leaving the editor. Author input flipped from a free-form text field to a `<select>` whose options come from the IntergroupOfficer roster (Settings → Global) — each option renders "Name — Role" so two members with the same first name stay distinguishable. The stored value remains the resolved name string (compatible with `BlogPost.author_name`), so legacy posts and the public templates need zero changes; posts whose `author_name` doesn't match a current officer surface a "(legacy)" option in the dropdown so a Save round-trip doesn't silently drop the previously-saved byline. The author bio textarea was removed (column stays so legacy posts keep their bios). Featured-image control gained a "Browse library" button next to "Upload" — opens the same `pbeOpenImageBrowser` modal the body image block uses, stamps the chosen `MediaItem.id` into a hidden `featured_image_media_id` field, and shows a "Will use: <filename>" indicator until save; the server reads the id only when no fresh file upload is present and reuses the existing `stored_filename` (no disk duplication). A new "View on Frontend ↗" button in the top action bar mirrors the announcement / event editor — opens the public `/blog/<slug>` URL in a new tab whenever the Web Frontend module is enabled and the post isn't a draft or archived. Live title → slug sync was ported from the post editor: typing the title rewrites the slug field in real time with the same `_normalize_slug` rules the server uses, with a brand-tinted highlight on each keystroke. A defensive form-level Enter guard intercepts Enter on every single-line text input *except* the title so pressing Enter inside the tag / category / new-tag fields no longer accidentally publishes (the title still submits on Enter for muscle memory).

### Removed — Blog post comments feature

The `allow_comments` checkbox is gone from the post editor, the `BlogPost.allow_comments` form-read in `blog_save` and the `allow_comments=src.allow_comments` carry in `blog_duplicate` are gone, and no UI, public renderer, or downstream consumer references the value anywhere. The underlying SQLite column is preserved as a vestigial NOT-NULL-defaulted attribute on the model (a comment in `app/models.py` flags it as inert) because SQLite can't drop a column in-place without rebuilding the table — a destructive op that the safety rule rightly blocks. A future schema migration that rebuilds `blog_post` can delete the model attribute in the same change.

### Changed — Classic blog detail template — Primary card chrome + featured-image hero + configurable rail

The main post card, the two sidebar widgets (Related / Categories), and the author-bio aside now carry the `fe-card-primary` design-token class, so their bg / border / border-radius / shadow / transition timing / hover lift + accent border swap all come from the central token aggregator in `frontend.css` instead of per-instance overrides; the template's inline CSS keeps only the layout-specific bits (padding, flex, etc.). The featured image now leads the post card (above the category chips, title, and byline) and bleeds to the card's left / right / top edges via negative margins matching the card's `clamp(1.5rem, 4vw, 3rem)` responsive padding — same edge-to-edge look the blog-list cards have. The card's own `overflow: hidden` clips the image to the rounded top corners; `box-shadow` paints outside the box and isn't affected, so the hover lift still reads cleanly. Two new toggles in the customize panel (gated to `blog_post` → `classic`) — Show *Related* widget / Show *Categories* widget — let admins turn off either or both. When both are off the entire `<aside>` is omitted and the grid switches to a single full-width track so the post body expands to the container width. Saved as explicit `False` values in `frontend_template_settings_json`; missing keys mean "shown" so the JSON stays lean and legacy installs default to the original look.

### Fixed — Template background settings now apply on the classic blog detail

The `.fe-blog-post-classic` article was painting its own background from `--blog-bg`, which never read `--tpl-bg` (the variable that carries the admin-chosen template background through `tpl_style`). Chained `--blog-bg` through `--tpl-bg` first in both light and dark mode so the admin's solid colour / gradient / image setting flows in; the existing surface-token fallback kicks in only when nothing's set. For dynamic animated backgrounds the article now renders transparent so the canvas shows through — the inner card still has its own solid surface so the prose stays readable.

### Fixed — Mesh-gradient randomize toggles now actually randomize on the classic blog detail

`tpl_dynbg_config` was being passed to `frontend/_dynbg_apply.html` (which emits the dynbg children) but the host element's `style` attribute never received the CSS variables that `--fe-dynbg-mesh-*-x/-y/-angle` consume. Resolved `dynbg_resolve_colors` + `dynbg_resolve_positions` into the inline CSS var string at the top of `classic.html` and stamped it onto the host alongside `tpl_style` — same pattern `meetings_list.html` uses. The "randomize colors" + "randomize positions" toggles now repaint the palette / mesh anchor + angle on every page load.

### Changed — Blog list cards (cards / sidebar / magazine / mosaic layouts) inherit `.fe-card-primary` tokens

Added `fe-card-primary` to the card root in `app/templates/frontend/blog_list/{cards,sidebar,magazine,mosaic}.html` and stripped each layout's hardcoded `background` / `border` / `border-radius` / `transition` + per-card `:hover` declarations so the design-token surface + the shared token-aggregator hover (lift + accent border swap) take over. Only structural rules survive per-layout — `overflow: hidden` for the bleeding featured image, `break-inside: avoid` for mosaic's masonry columns, and the `is-pinned` / `is-featured` accent overrides. Gazette + minimal layouts are text-row layouts with no card chrome, intentionally left alone.

## [1.10.4] — 2026-05-15

### Fixed — Visitor recorder now respects the frontend gate (no more phantom traffic when the public site is disabled)

`_record_visitor_event` in `app/frontend.py` is mounted as a `before_request` on the `frontend` blueprint. Flask runs blueprint `before_request` hooks BEFORE the route handler itself runs — which means a request to `/`, `/meetings`, `/events`, etc. would write a `VisitorEvent` row *before* the route's `_frontend_gate(site)` call had a chance to return a 302 to login. With `frontend_enabled` off, scanner / crawler hits at common frontend paths were getting redirected to login as designed but still appearing in the dashboard's Visitor Metrics widget as "real" page views. The recorder already filtered authenticated users (admin/editor previews) and obvious bot UAs, but anything with a plausible browser UA that didn't match the `_BOT_TOKENS` list slipped through.

`visitor_metrics.record_visit()` now reads the `SiteSetting` row up front and short-circuits when `frontend_module_enabled` is False OR `frontend_enabled` is False — same precondition the route handlers' `_frontend_gate` enforces. Verified end-to-end via a `unittest.mock.patch` against the SiteSetting query: gate-off → recorder writes zero rows; gate-on → recorder writes one row per legitimate visit. Login-page traffic was never affected (login lives on the `auth` blueprint, which the recorder hook isn't wired into).

Historical rows from before this fix are left intact — there's no audit log of when `frontend_enabled` was toggled, and any retroactive scrub would have to guess at which rows were legitimate.

## [1.10.3] — 2026-05-15

### Added — Defensive 404 short-circuit for known attacker probe paths

Production was seeing the usual scanner traffic (`.env`, `.env.backup`, `.git/config`, `wp-admin/`, `phpmyadmin/`, `xmlrpc.php`, `.aws/credentials`, `credentials.json`, `backup.zip`, etc.) hitting the heavy 404 template — a ~25 KB render that reflects site branding back at the scanner. New `_block_known_probes` `before_request` handler in `app/__init__.py` matches paths against a suffix tuple (filenames) and prefix tuple (directories) of well-known recon targets, returns `("", 404, {"Cache-Control": "no-store"})` — zero body, no template render — and emits a single `app.logger.info("probe-block %s from %s", path, ip)` line so operators see attack patterns without filling logs with full request dumps. Fast structural pre-filter (`/.` / `/wp-` / `phpmyadmin` / etc. substring check) keeps the per-request cost of the more expensive tuple scan off the legitimate-traffic hot path. Confirmed: `/.env`, `/.env.backup`, `/.git/config`, `/wp-admin/setup-config.php`, `/phpmyadmin/`, `/xmlrpc.php`, `/server-status`, `/.aws/credentials`, `/.ssh/authorized_keys`, `/credentials.json`, `/backup.zip` all return `HTTP 404 size=0` after the patch.

### Changed — `request.referrer` fallbacks now route through a same-origin validator

Every flash-and-bounce handler in `app/routes.py` used to fall back to `request.referrer` when no explicit target was set (`redirect(request.referrer or url_for("main.index"))` — 85 occurrences across the file). `Referer` is browser-set and steerable by an attacker hosting a page that links into a protected route: a victim clicking that link would get permission-denied and then redirected off to `https://attacker.example/`, opening a phishing pivot. Added a small helper `_safe_referrer()` near the top of `app/routes.py` that returns `request.referrer` only when its parsed netloc matches `request.host_url`'s netloc (so cross-origin Referer values fall through to `None`, and callers land on whatever explicit `url_for(...)` they intended). Bulk replaced all 85 call sites — three multi-line ones patched individually. No other Python files use `request.referrer`, so the audit is complete.

### Added — SVG `<script>` / `on*=` / `javascript:` sanitization on every upload, not just custom icons

`_save_upload()` in `app/routes.py` already ran SVG dimension normalisation but never the existing `_sanitize_svg()` regex stripper — that was wired only into the Custom Icons admin path. SVG uploads are admin-only (`ADMIN_ONLY_UPLOAD_EXTENSIONS = {".svg"}`) so the practical risk is low, but defence-in-depth is cheap: an admin uploading a vector logo handed off by a designer shouldn't become a vector for stored XSS against other admins / visitors who later navigate to the file directly (browsers execute inline `<script>` in standalone SVGs). `_save_upload` now calls `_sanitize_svg(data)` before `_normalize_svg_dimensions(data)` for `.svg` uploads. Test confirms `<script>...</script>` and `onclick=...` are stripped from the persisted bytes.

### Changed — Fernet decrypt failures now log a warning instead of silently returning `""`

`app/crypto.py::decrypt()` used to swallow all exceptions and return an empty string. The intent was graceful degradation — a stored encrypted column that fails to decrypt (key rotation, corrupted bytes) wouldn't crash the request — but the failure mode is hostile to operators: rotating `TSP_SECRET_KEY` or replacing `zoom.key` makes every Zoom / OTP password disappear from the UI with no clue in the logs. Replaced the bare `except Exception: return ""` with a logged warning ("Fernet decrypt failed — encrypted column unreadable. Most likely cause: TSP_SECRET_KEY or zoom.key was rotated after this value was stored. Re-enter the affected credential to re-encrypt under the current key.") behind a nested try so a missing app context can't bubble out of `decrypt()`. Still returns `""` to callers (preserves the no-crash contract); the difference is the operator now sees one warning per affected column in container logs.

### Changed — Refuse to seed `admin/admin` in production

`_seed_admin()` in `app/__init__.py` defaulted `TSP_ADMIN_PASSWORD` to literal `"admin"` when the env var was unset. The bundled installer always supplied a value, but anyone bringing the image up manually (hand-written compose, ad-hoc `docker run`) silently got `admin/admin` on a public-internet `/tspro/auth/login` — a takeover in one request. Now: if `TSP_ADMIN_PASSWORD` is empty AND `TSP_DEBUG` is unset, `_seed_admin` raises `RuntimeError("TSP_ADMIN_PASSWORD is required on first boot. …")` and the container fails to start. `TSP_DEBUG=1` falls through to a warning + the legacy `admin/admin` for local dev. Same pattern `_seed_admin` already used for `TSP_SECRET_KEY`. `docker-compose.deploy.yml` and the installer's embedded compose template both flip `${TSP_ADMIN_PASSWORD:-admin}` → `${TSP_ADMIN_PASSWORD:?TSP_ADMIN_PASSWORD must be set in .env (used only on first boot to seed the admin account)}` so the compose layer also short-circuits.

### Changed — Installer generates a random admin password instead of defaulting to `admin`

`install.sh` previously defaulted `ADMIN_PASSWORD="${TSP_ADMIN_PASSWORD:-admin}"`. Same logic as the new `TSP_SECRET_KEY` generation: when the operator doesn't supply a value, `openssl rand -base64 24 | tr -d '\n/+=' | cut -c1-24` produces a strong random password, persists it to `${INSTALL_DIR}/.env` (`chmod 600`), and the end-of-install banner prints it once. Reruns read the existing password back from `.env` so the banner still surfaces the correct credential after a re-install. Combined with the previous change, this closes the path where a fresh install ships with publicly-guessable credentials.

### Added — Cross-Origin-Opener-Policy + Cross-Origin-Resource-Policy headers

`@app.after_request` `_security_headers` now sets `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Resource-Policy: same-origin` on every response. COOP keeps any window we open (or that opens us) in a separate browsing-context group so `window.opener` attacks can't reach across origins; CORP blocks other origins from embedding our responses as resources (image hot-linking, external `<link rel="stylesheet">`, etc.). Both scoped to our own origin — Caddy, Cloudflare, and our `/pub/` asset URLs all live on the same host so nothing legitimate breaks. Pairs with the existing CSP `frame-ancestors 'self'`.

## [1.10.2] — 2026-05-14

### Added — Per-page Open Graph on every public detail page + a Page-level OG section

The public site now emits per-entity Open Graph / Twitter Card metadata on every detail surface: `/meetings/<slug>` uses `Meeting.name` + `Meeting.description` + `Meeting.logo_filename` (served via the existing `public.public_meeting_logo` route); `/event/<slug>`, `/announcement/<slug>`, and `/archive/<slug>` use `Post.title` + `Post.summary or Post.body` + `Post.featured_image_filename` (`public.post_featured_image`); `/stories/<slug>` uses the corresponding Story columns (`public.story_featured_image`); `/blog/<slug>` uses BlogPost (`public.blog_post_featured_image`). New `Page` columns `og_title` / `og_description` / `og_image_filename` (with `_migrate_sqlite` entries) — set them from a new **Open Graph / Link Previews** section on the page-edit form, sitting under Background image. A `og_present` hidden marker gates the assignment so partial sub-form submits can't wipe values. Page OG image is served on `/pub/page-og-image/<page_id>` with a 1-day public cache header. Anything left blank — per-entity AND per-page — falls back to the site-wide `frontend_og_*` defaults set under Web Frontend → Branding & SEO; the site-wide `frontend_og_enabled` master toggle still gates the entire block.

Implementation: a new `frontend.py::_page_og(site, title, description, image_url)` helper produces the `page_og_title` / `page_og_description` / `page_og_image_url` triplet that `frontend/base.html` consumes. Descriptions are HTML-stripped, whitespace-collapsed, and clipped to 280 characters with a Unicode ellipsis — comfortably under Facebook's 300-char hard ceiling and a hair above Twitter's classic 200-char sweet spot. Image URLs are emitted as absolute (`_external=True`) because crawlers (Slack / iMessage / Facebook) skip relative-path previews. Every detail route was updated to splat `_page_og(...)` into `render_template(...)` alongside the existing context, including the homepage `index()` (which already renders a Page).

### Added — Apple Home Screen icon + display name for admin (/tspro) and public site

Two new SiteSetting column pairs: `apple_touch_icon_filename` / `apple_touch_icon_name` (backend) and `frontend_apple_touch_icon_filename` / `frontend_apple_touch_icon_name` (frontend), all additively migrated. Two new public serve routes — `/site-branding/apple-touch-icon` and `/site-branding/frontend-apple-touch-icon` — so iOS can fetch the icon anonymously when a visitor taps "Add to Home Screen." `base.html` and `frontend/base.html` swap their hardcoded static `apple-touch-icon_tspro.png` / `apple-touch-icon_dccma.png` links for the uploaded version when one is set (falling back to the bundled static asset otherwise), and emit `<meta name="apple-mobile-web-app-title">` when a display name is configured. The backend control sits in **Settings → Appearance**, paired in the right column of the same grid row as Open Graph; the frontend control lives under **Web Frontend → Branding & SEO** as its own card. Both panels carry a live icon + label preview that updates as the admin edits, with the same `?v={{ app_build_id }}` cache-busting suffix the favicon already uses so iOS picks up new artwork on the next home-screen add.

### Changed — Event / announcement / archive detail cards switched to Primary card tokens

`.fe-event-detail-card` (Schedule / Location / Online / Contact panels on the public event, announcement, and archive detail pages) used to read from the Secondary card design tokens — the soft panel surface used by feature cards and FAQ items. Switched to Primary card tokens (the elevated meeting-card style) so the detail panels read as a coherent card family with the meeting-detail cards. Standalone rule's `background` / `border` / `border-width` declarations swapped to `--fe-color-card-primary-*`; the per-card `:hover` block was removed in favour of the shared primary aggregator selector at the bottom of the file (which now includes `.fe-event-detail-card`); the Secondary aggregator no longer references it. (Dark-mode overrides at `html[data-theme="dark"] .fe-event-detail-card` still read from the Secondary dark tokens — pending a follow-up.)

### Added — View on Frontend ↗ button on the post-edit page

The announcements / events admin edit page (`/tspro/announcementsevents/<id>`) gains a `View on Frontend ↗` button in the top-action row. Uses the existing `post_url` Jinja global so the link routes to the right public URL (`/event/<slug>`, `/announcement/<slug>`, or `/archive/<slug>`) based on the post's state. Gated on `frontend_module_enabled`; hidden on pending-review submissions, drafts, and brand-new unsaved posts.

### Changed — Announcements list cards drop the "View details ↗" CTA; GSR titles become links

The announcement card partial used to render a separate `View details ↗` link at the bottom. Removed — the card title was already a link to the same URL. The card title's `:hover` now underlines (was no underline at any state) so the click affordance is still clear. On the GSR Summary view, each title is now wrapped in an `<a href="{{ post_url(ann) }}">` so the printed-digest layout is also navigable; styled to inherit the surrounding text colour (no link blue, no underline at rest) with a subtle hover underline so the printed-digest aesthetic stays intact.

### Changed — Meetings + Events blocks: mobile self-padding restored

Earlier removing the inner `.fe-container` wrapper from `frontend/blocks/meetings.html` and `frontend/blocks/events.html` (so they wouldn't double-pad inside page-builder containers on desktop) accidentally left those blocks flush on mobile when their parent container carried explicit `0 0 0 0` mobile padding. Added a `@media (max-width: 768px)` self-padding rule reading `--fe-container-pad-mobile` (default `5vw`) — same `.fe-faq--bare` pattern. Desktop is untouched (parent container still controls), so the admin's homepage layout doesn't gain a double gutter.

### Changed — Events Magazine "More events" grid: cover image at the top, max 3 per row

The secondary tiles inside the More events grid (rendered on the events Magazine layout + Omni layout's Magazine panel) now show their featured image above the title (was previously hidden via `display: none`). Tile layout reshaped via `grid-template-areas` so the cover bleeds to the card edges with a 16/9 aspect ratio + rounded top corners, the date drops to a small inline chip, and the body sits below. Grid switched from `repeat(auto-fill, minmax(280px, 1fr))` to a fixed `repeat(3, minmax(0, 1fr))` cap (drops to 2 columns at ≤1024 px and 1 column at ≤640 px) so each tile stays wide enough to host a thumbnail at a sensible size.

## [1.10.1] — 2026-05-14

### Changed — Announcements + Events list templates now sort by post date (newest first)

Both `/announcements` and `/events` list pages used to order by `Post.created_at` (announcements) or `Post.event_starts_at` ascending (events, via the shared `filtered_events` helper). Switched both to `coalesce(published_at, created_at) desc` so the cards land newest-published first regardless of when each event runs. Back-dated posts surface in the right slot; rows with NULL `published_at` (legacy imports) still sort sensibly via creation time. The events list keeps its "upcoming only" filter (past events go to /archive); the homepage Upcoming Events block still uses `filtered_events` with chronological ordering — that helper is unchanged. The GSR Summary panel inside the announcements omni layout is a sub-render of the same `all_announcements` list, so it picks up the new sort automatically. GSR Summary subheading trimmed to "Fellowship news, in brief."

### Changed — Event website URL field accepts relative paths

The post-edit page's Event website URL input was `<input type="url">`, which the browser validated against the URL spec — rejecting relative paths like `/about-us`. Switched to `<input type="text" inputmode="url">` (mobile URL keyboard preserved) so admins can point at internal pages on the same domain as well as full external URLs. Placeholder + label updated to hint both shapes (`https://example.org/event or /page-slug`). No server-side / render-side changes needed: the save endpoint already only length-bounds the value, and browsers resolve relative `href`s against the current domain.

### Changed — Frontend meeting detail: description column caps at 75% above 1024 px

The description prose on the public meeting-detail page used to stretch the full container width on every viewport, producing uncomfortable line lengths on widescreen monitors. New `max-width: 75%` cap above 1024 px (and `max-width: 100%` at 1024 px and under, so tablets / landscape phones / split-screen still get the full width). Applied across all four detail templates (Classic, Minimal, Card Stack, Magazine) via their respective description-container classes (`.fe-meeting-detail-desc`, `.fe-meeting-min-desc`, `.fe-meeting-stack-prose`, `.fe-meeting-mag-prose`) so the column reads consistently regardless of which template is selected.

### Changed — Frontend export bundle: posts excluded, verbatim coverage tightened

The frontend bundle is now strictly look-and-feel (settings, navigation, layouts, fonts, icons, design tokens, pages, stories, intergroup officers, media). Three coordinated changes:

- **Posts dropped from export.** The `posts` collection (every `Post` row) and the `slug_history` collection (which only carried `post` entries) no longer appear in the payload. Per-post asset scan removed. The import side keeps its backwards-compat path so old bundles that DO contain posts still restore them; new bundles produced by this function omit them. Posts are per-deployment editorial content — shipping them silently overwrote the destination's editorial state.
- **Homepage padding bug fixed on import.** Found the cause of "frontend export keeps resetting the side padding on the homepage": the page-import path used `int(p.get("pad_x") or 16)` which silently rewrote any explicit `0` to the default (because `0 or 16 == 16` in Python). Switched every integer column on Page (`pad_x`, `pad_top`, `pad_bottom`, `section_gap`, `block_margin_y`, `max_width`, `full_padding_pct`, `bg_tile_scale`) to the existing `_opt_int` helper, which only falls back to the default when the key is missing or non-numeric. Full-bleed pages with `full_padding_pct: 0` now round-trip verbatim.
- **Setting scope widened for module gates.** Added `posts_`, `stories_`, `blog_` to the prefix list in `_frontend_setting_keys`, capturing the 6 module-gate columns (`*_enabled` + `*_required_role`) that control whether the public Events / Announcements / Stories / Blog surfaces serve at all. They're frontend behaviour even though they don't carry a `frontend_` prefix in the schema.

### Fixed — Auto-stamped Post / Story `published_at` honours the site timezone

`Post.published_at` (and `Story.published_at`) is stored as a naive datetime that the form parser (`_parse_post_dt`) reads as the admin's local wall-clock time, and that the display layer renders straight through `.strftime()` — so the storage convention is "naive = site-local". But the auto-stamp paths used `datetime.utcnow()`, writing UTC into the same column. Display then rendered UTC as if it were local, producing wrong wall-clock times offset by the admin's tz from UTC (e.g. 5 PM PDT showing as 12 AM next day).

New helper `app/timezone.py::now_local_naive(site)` returns the current site-local datetime with `tzinfo` stripped. Wired into:
- `post_save` route — the draft → publish stamp + the default `published_at` for newly created posts.
- `post_publish` route — the inline draft → publish flip from the list page.
- `story_save` route — same pattern, fixed prophylactically so the same bug doesn't surface on stories.

Form-entered values were already correct (naive site-local). Existing rows with UTC-stamped `published_at` will keep showing at the wrong time until republished — re-saving the post writes a fresh local-naive value into the column.

### Fixed — Publish / Move-to-Drafts buttons on the post-edit page now save in-progress edits

The `Publish` button on a draft (and the `Move to Drafts` button on a published post) used to POST to the dedicated `post_publish` / `post_unpublish` state-flip routes, which never saw the post-edit form's fields — so clicking either without first clicking `Save draft` / `Save post` threw away every edit the admin had made. Both buttons now submit the post-edit form with `action=publish` / `action=draft`. `post_save` already handled both values to flip `is_draft` AND save the form fields AND (with the recent draft → publish change) stamp `published_at = now`, so the buttons now do exactly what the labels suggest. The standalone `post_publish` route stays in place for the per-row inline `Publish` button on the list page where there's no form to save.

### Changed — Drafts and pending submissions don't log URL redirects on slug changes

Renaming a draft used to insert a row in `EntitySlugHistory` for every slug change, polluting the redirect table with mappings from URLs the public never saw. Captured `_was_public = (not creating) and (not is_draft) and (not is_pending_review)` before mutating the post and gated the `EntitySlugHistory` insert on it.

- Editing a draft and renaming it → no redirect (URL was never public).
- Publishing a draft (with or without a slug change during the same save) → no redirect from the old draft slug; the post starts its public life cleanly at the new URL.
- Renaming a published post → redirect logged as before.
- Moving a published post back to drafts → no new redirect; subsequent slug changes don't log either until the post is republished.

### Added — Live title → slug sync on the post-edit page with highlight pulse

Every keystroke in the **Title** field now rewrites the URL field client-side using the same `_normalize_slug` rules the server runs on save (lowercase, non-alphanumeric runs collapse to `-`, leading/trailing hyphens stripped, 200-char cap). The URL row picks up an accent-tinted background + brand-coloured border + a soft brand-coloured ring; the slug text shifts to the brand colour. Highlight fades out ~1.4 s after the last edit (animation restarts on each keystroke so it stays visible while typing).

### Changed — Draft → publish transition stamps `published_at` with the current time

Both publish paths (the dedicated `post_publish` route AND `post_save` when the form's `action=publish` button is clicked) now overwrite `published_at` with `datetime.utcnow()` whenever the post was actually a draft on the way in. Matches the principle that "Posted on …" should reset to "now" the first time a piece of content actually goes live, regardless of whatever date the admin had keyed into the form for back-dating earlier. No-op when the post is already published or when the save doesn't flip draft status.

### Changed — Post slug auto-derives from title when the title changes

`post_save` previously trusted the slug input regardless of whether the editor touched it — and the slug input is pre-populated from the database, so renaming a post left the public URL pinned to the old title. Reworked the slug-resolution branch:

- **Title changed** (or creating a new post) → re-derive the slug from the new title and ignore the slug input. The existing `_unique_post_slug` sweep appends `-2` / `-3` / … on collision; flash message surfaces the suffix when it had to disambiguate ("URL auto-derived to "test-event-2" to avoid collision with another post").
- **Title unchanged** → respect the editor's explicit slug input (existing behavior preserved). Editors can still rename the URL without touching the title.

Slug-history redirect logging continues to fire on any `public_slug` change, so the previous URL keeps working via the existing 301 fallback even when the title-driven auto-derive flips the slug.

### Added — Announcements & Events admin: Duplicate button surfaced

The `post_duplicate` route already existed (clones a post into a fresh Draft with a `(copy)` title suffix, redirects to the Drafts tab) but the UI didn't expose it — the Drafts empty-state message even read "Duplicate an active post to start one" without offering anywhere to do so. Surfaced the action in two places:

- **List page (`/tspro/announcementsevents`)** — every row gets a `Duplicate` button between `Edit` and `Publish` / `Drafts`. Hidden on pending-review submissions.
- **Edit page (`/tspro/announcementsevents/<pid>`)** — top-action row gets a `Duplicate` button between Archive/Restore and Delete. Hidden on brand-new posts and pending-review submissions.

Featured-image filename is shared on the duplicate (uploads are content-addressed, so two rows pointing at the same stored file is fine — the cleanup helper sees the reference).

### Changed — Homepage Meetings + Events blocks: dropped inner `.fe-container` wrapper

The `frontend/blocks/meetings.html` and `frontend/blocks/events.html` partials wrapped their content in `<div class="fe-container">`. After flipping `--fe-container-pad-desktop` to `5vw`, that token padding was being added on top of whatever the page-builder container providing the block also set — squeezing the meeting cards grid into too-narrow columns at intermediate desktop viewports and crushing the events list. Both partials now skip the `.fe-container` wrapper entirely so the surrounding page-builder container is the sole source of width + horizontal padding.

- Both blocks are page-builder-only (only included from `frontend/page.html` after the 1.9.0 homepage retirement), so dropping the wrapper has no other consumers to worry about.
- Width clamping moves to the parent container (admins set `max-width` per container as part of the page-builder); blocks render at 100 % of the surrounding container's content width.

### Changed — Container padding desktop default flipped to 5vw

`container_pad_desktop` shipped at `0` in 1.10.0 on the assumption that the boxed `max-width: 1160px` cap would always provide a desktop gutter — but at intermediate viewport widths (~768–1160 px) the cap doesn't engage and content runs to the viewport edge. Theme defaults flipped to `5vw` (matches mobile), so every block that wraps in `.fe-container` (meeting detail, event detail, meetings list in boxed mode, hero/CTA/inclusion blocks) now carries a visible left/right gutter at all desktop widths. Admin can still override per-deployment under Site → Design → Layout.

### Added — Meetings list (Sidebar template) — location name + address in column 3 for in-person / hybrid

The 3-column expanded meeting card on the Sidebar layout now renders a location pane at the top of column 3 — above the Zoom credentials, Get Directions, and Add to Calendar buttons. Bold location name + muted address lines (street, then city/state/zip) when the meeting's free-text location resolves against a saved Location row; falls back to the bare free-text string for custom locations that don't match.

- Server-side resolver batches the `Location.query.all()` lookup once per page request, builds a `meeting_locations` dict keyed by meeting id, and passes it to the template — no N+1 follow-ups.
- Online-only meetings skip the pane entirely.
- The Directory and Week-board layouts already render location info in column 2; this change only affects the Sidebar 3-column render.

### Added — Meetings list (Sidebar template) — admin-curated custom links rail

A new "Sidebar custom links" fieldset under **Frontend → Templates → Meetings list** lets admins add internal or external links that render below the day filters under a divider line in the Sidebar layout's rail. Internal links get a chevron-right at the far right; external links get an external-link icon and an optional "Open in new tab" toggle.

- Per row: Label, URL, Internal/External chip-style toggle, Open-in-new-tab checkbox.
- Storage: new `SiteSetting.frontend_meetings_list_sidebar_links_json` column (TEXT, nullable, additive migration).
- Resolver `meetings_list_sidebar_links_resolved(site)` clamps unknown link types to `internal` and drops rows missing label OR URL.
- Public links inherit the rail's text colour at every state (no link-blue, no underline) and only the background tints on hover.

### Changed — Backend meeting detail: View on Frontend button gate + placement

The "View on Frontend ↗" button on `/tspro/meetings/<slug>` was gated on `frontend_enabled` (public visibility) so it disappeared whenever public access was off — even though signed-in editors can preview the page either way. Switched to the `frontend_module_enabled` gate (module on/off). Also reordered so Edit comes first and View on Frontend sits immediately to its right at the top of the action row, ahead of Archive/Restore + Delete.

### Changed — Frontend meeting detail Files & Readings: drop file description text

`_resources.html` no longer renders the muted `<span>` carrying `f.description` beneath each link. Each row is now just the title + the trailing `↗` arrow, applied across all four meeting templates (Classic, Magazine, Card Stack, Minimal) since they share the same partial.

### Added — Settings → About: Release notes section above the Changelog

A new release-notes data source ships alongside the changelog, displayed first in the About tab inside an open `<details>` (changelog moves into a closed `<details>` underneath). New file `app/templates/_release_notes.html` (HTML partial) + `RELEASE_NOTES.md` (markdown mirror) at the repo root. Friendly per-version summaries cover every version bump from 1.0 → 1.10.0 — patch versions grouped under their parent (e.g. "1.7.0 – 1.7.17") to keep the section scannable.

- Both `<details>` blocks get a tinted card chrome with a custom rotating chevron caret.
- About-pane outer `padding: 24px` removed (`padding: 0`) so the new chrome sits flush against the modal panel edges.

## [1.10.0] — 2026-05-14

### Added — Hero block buttons: icon picker + design-token colour pickers

The hero block edit modal's per-button "Advanced — icons + custom colours" panel rewired to use the same shared chrome the rest of the admin uses. The two icon fields (`icon_before`, `icon_after`) are now icon-picker triggers — click the dashed tile to open the global Lucide / custom-uploads picker (search, size slider, the lot); the trigger fills with a live SVG preview and a small `×` clear button. Wired through `[data-open-icon-picker]` + `data-icon-target` against per-row hidden inputs minted with random unique IDs so multiple button rows in the same modal don't collide.

The four colour fields (`icon_before_color`, `icon_after_color`, `custom_bg_color`, `custom_text_color`) gained the full colour-cluster UI — editable hex text input + native `<input type="color">` swatch + auto-attached 🎨 design-token-palette button + read-only hex caption + matched-token chip (◈ Brand). The 🎨 button comes for free from the global `_design_token_picker.html` MutationObserver — every dynamically-injected `<input type="color">` picks up the chrome on insert. Two-way binding everywhere: editing hex syncs the swatch, picking a swatch updates the hex, picking a token writes both.

### Changed — Dynamic background modal "Save" → "Done"

The footer button on `#dynbg-picker-modal` (Choose a dynamic background) said **Save**, but the modal doesn't actually save — it commits the chosen preset back to the parent form's hidden inputs and the parent form is what eventually saves on its own submit. Renamed the button text to **Done** so the verb matches what the click actually does.

### Added — Hover-background tokens for primary + secondary buttons

Two more colour tokens — `color_btn_primary_hover_bg` and `color_btn_secondary_hover_bg` — drive the background colour applied on `:hover`. Rendered in their respective Buttons admin column right between bg and text, so admins can tune the hover wash from one place. Defaults approximate the previous `color-mix(in srgb, <bg> 88/92%, black)` auto-darken (`#0a51e0` / `#e4e6e8` for Classic; `#0a51e0` / `#e0e3e7` for Recovery Blue), so existing button hover visuals stay essentially the same. The CSS keeps the `color-mix` recipe as a fallback inside the new `var(...)` so unstyled environments still get auto-darken behaviour. Live preview button repaints hover bg in real time.

### Added — Surface — Darkmode token + per-style button border tokens (8 new)

A new colour token **Surface — Darkmode** (default `#0b1026`) under Site → Design → Colors becomes the source of truth for the dark-mode page background. Wired by replacing the hard-coded value in `--fe-dm-page-bg` with `var(--fe-color-surface-dark, #0b1026)` so every consumer that reads `--fe-dm-page-bg` (body bg, force-dark footer, etc.) tracks the token.

The Buttons section gains **eight per-style border tokens** — for each of Primary and Secondary: border colour, border width, hover border colour, hover border width. Border widths flow through the existing `BORDER_WIDTH_SCALE` (0/1/2/3/4 px); colour fields use the standard hex picker. Defaults preserve current visuals: primary borders match the bg colour (visually invisible until the admin picks a contrasting value), secondary uses `color_border` at rest and `color_btn_secondary_text` on hover (the legacy `.fe-btn-ghost` recipe).

- `.fe-btn-primary` / `.fe-btn-ghost` switched from shorthand `border:` declarations to longhand `border-width` + `border-style` + `border-color` so each can read its own token without fighting cascade order. Hover rules read the hover token with the resting token as fallback (so half-configured borders don't flicker between widths).
- The four new fields per kind render in their respective Buttons column (Primary on the left, Secondary on the right) right after `bg` + `text`, and the live preview button stamps `--fe-btn-<kind>-border-width` + `--fe-color-btn-<kind>-border` (resting + hover) so the preview repaints in real time as the admin edits any field.
- Existing dark-mode hardcoded `.fe-btn-ghost` border overrides (e.g. `border-color: #334155`) remain at higher specificity — these light-mode tokens drive light mode only.

### Added — Buttons section: two-column layout with per-style live preview

Mirrors the Card styles layout. Buttons now lays out as Primary on the left, Secondary on the right, each column carrying its own preview button at the top followed by the settings stack underneath. Drops to single column under 900 px. Shared structural settings (radius, padding-x, padding-y, weight, text-transform, decoration) live in a dedicated **Shared button settings** block below both columns with a one-liner clarifying they apply to every button regardless of style.

- Each preview button is a self-contained `.fe-btn-style-preview-button` that re-implements just enough of the public `.fe-btn` recipe to render on the admin page (admin chrome doesn't load `frontend.css`). Reads the same `--fe-btn-*` + `--fe-color-btn-*` custom properties so the live JS can stamp tokens directly on the element.
- New live preview JS block listens on form `input` / `change` and resolves every Buttons token (radius scale, padding text values, on/off effect toggles for `btn_shadow` / `btn_hover_transform` / `btn_hover_glow`) through the same recipes the Python emitter uses, so the preview matches the public render exactly.
- Three primary-only effect tokens (`btn_shadow`, `btn_hover_transform`, `btn_hover_glow`) render only inside the Primary column.

### Added — Card styles: two-column layout + per-card hover-border tokens

The Card styles tab restructured into two side-by-side columns matching the new Buttons layout: Primary on the left, Secondary on the right, each with its preview card directly above its full settings stack so the visual + the controls that drive it stay grouped. Drops to single column under 900 px. The shared `data-card-preview` attribute moved to the wrapper so the existing live-preview JS still finds both target cards in one query.

Two new colour tokens — `color_card_primary_hover_border` and `color_card_secondary_hover_border` — control the border colour applied on `:hover`. Defaults preserve current visuals: secondary cards (feature, FAQ, quick-link, inclusion, etc.) keep accent-on-hover, primary cards default to their resting border colour (no visual shift unless the admin overrides). Wired into the shared `.fe-card-primary:hover` / `.fe-card-secondary:hover` rules so every primary or secondary card surface picks them up. The legacy hardcoded `.fe-feature-card:hover` accent border now also reads the secondary token. Mirrored in each column with the existing colour-token mirror system; the live preview repaints hover-border in real time.

### Changed — Button padding tokens wired through to `.fe-btn`

`btn_padding_x` and `btn_padding_y` existed in the schema and emitted CSS variables but no rule consumed them — `.fe-btn` had a hardcoded `padding: 14px 28px`. Rewrote the `.fe-btn` rule to read `var(--fe-btn-padding-y, 14px) var(--fe-btn-padding-x, 28px)`, switched the field type from a fixed scale (`xs/sm/md/lg/xl`) to a free-form text input so admins get pixel-precise control, and updated theme defaults to `"14px"` / `"28px"` so existing button visuals are preserved bit-for-bit. Labels reworded to "Vertical padding (top/bottom)" / "Horizontal padding (left/right)" so the role of each axis is unambiguous; placeholder hints suggest legal CSS lengths (`14px`, `0.875rem`, `1vw`).

### Added — Container padding design tokens (`container_pad_desktop` / `container_pad_mobile`)

A 1.8.4-era CSS rule — `@media (max-width: 560px) { .frontend-body .fe-container { padding: 0 5vw; } }` — was lost in a later refactor, leaving every block that wraps in `.fe-container` sitting flush against the viewport on phones. Restored as two free-form text design tokens under Site → Design → Layout: **Container padding — desktop** (default `0`) and **Container padding — mobile** (default `5vw`, applied at ≤768 px). Accept any CSS length: `0`, `24px`, `2rem`, `5%`, `5vw`. Wired into `.fe-container` (used by hero/cta/inclusion/etc. blocks) and the page-builder shell `.fe-pp-shell`, with the per-page `pad_x` setting still winning on desktop and the mobile token acting as a single global lever at ≤768 px.

Page-builder full-bleed pages emit their `full_padding_pct` as a `--fe-pp-pad-x-full` custom property instead of inline `padding-left/right`, so the mobile media query can override without an inline-style war. The bare FAQ block (`.fe-faq--bare`, used inside page-builder containers that drop the `.fe-section` + `.fe-container` chrome) gets a surgical mobile-only horizontal padding rule that reads the same token, so FAQ accordions inside zero-padding containers still get a phone-friendly gutter without forcing a margin around the whole page.

### Changed — Frontend Features block: per-card buttons + section CTA + cleaner hover

The features block stopped wrapping each card in an `<a>`. Cards are always `<article>` now; when a card has a link, it renders an inline `.fe-btn` (Primary or Secondary, admin-selectable) inside the card with an editable label (defaults to "Learn more" if blank). Removes the global `.fe-page a:hover` underline that was being applied to the card title + body whenever the whole card was the link target.

- Two new per-card fields in the Features modal (`button_label`, `button_style`); modal layout adds a "Button label / Style" row beneath the existing link URL row. JS extends the default item shape so missing inputs still serialise cleanly. `_normalize_features` carries the new keys and clamps `button_style` to the allowlist (`primary`/`ghost`).
- A section-level bottom CTA (`cta_label` / `cta_url` / `cta_style` / `cta_new_tab`) renders as a single centred `.fe-btn` under the cards when both label + URL are filled — matches the `.fe-events-foot` / `.fe-meetings-foot` pattern. `4rem` of space above the button at desktop widths (`@media (min-width: 768px)`); mobile keeps the tighter `28px` shared rule.
- Card now uses flex column + `margin-top: auto` on the actions row so per-card CTAs align across rows even when bodies differ in length. Dead `.fe-feature-card--linked` selector + `cursor: pointer` rule removed (no longer needed).

### Added — Container padding: per-side fields with unit selector

The container block's Padding control used to be a single free-form text input accepting CSS shorthand (`1rem`, `24px 16px`, etc.) — readable only if you already think in CSS. Replaced with a box-style diagram: four numeric inputs positioned around a centre "Padding" tag, labelled **Top / Right / Bottom / Left** on the outer ring so the role of each input is unambiguous. Each input is a chip combining a `<input type="number">` with a `<select>` dropdown for the unit — admins can pick **px / rem / em / vh / vw / %** per side independently. Same layout repeats for the mobile-override row (centre tag reads "Mobile"; any side left blank inherits the matching desktop value at ≤720 px).

- Storage shifts from a bare integer to a full CSS-value string (`"16px"`, `"2rem"`, `"5%"`). The first time a saved container with the legacy `padding` shorthand is opened, a one-shot parser seeds the four per-side fields with the equivalent values *preserving the original unit* — so a saved `padding: "1.5rem"` becomes four `1.5rem` fields, not a px equivalent.
- Renderers (`_blocks.html`, `frontend/page.html`) read the new fields through a `_pad_side(v)` helper: empty/null → `0`, integer → `<n>px` (legacy compat), string → unchanged. The four sides assemble into `--block-cont-padding: T R B L`. When all four are empty, the legacy `d.padding` CSS shorthand still applies, so containers saved before the per-side editor split keep their look.
- CSS for the box: 3×5 grid with axis labels on the outer ring + four input chips on the inner cross + a dashed-border "Padding" tag in the centre. Native number-input spinner suppressed; unit `<select>` borderless and muted so it reads as secondary chrome.

### Added — Card styles design-token group + per-container card option

A new **Card styles** tab under Frontend → Design houses every knob that drives the look of card surfaces site-wide. The eight existing colour tokens for primary + secondary cards (bg/border light + dark) are mirrored into this tab; the canonical inputs still live on the Colors tab, with bidirectional JS sync (dashed border + "Synced" badge on the mirror so admins know editing either copy updates both). On top of the colour tokens, ten new structural tokens — five per card kind — control **border width**, **shadow**, **hover shadow**, **transition**, and **hover transform**. Three new scales back the new fields: `BORDER_WIDTH_SCALE` (0 / 1 / 2 / 3 / 4 px), `TRANSITION_SCALE` (none / fast 120 ms / normal 200 ms / slow 320 ms), `TRANSFORM_SCALE` (none / lift-sm -1 px / lift-md -2 px / lift-lg -4 px), all on a custom cubic-bezier easing.

- **Live preview pane** at the top of the tab — two sample cards (primary, secondary) styled by the current form values. Inline CSS custom properties are stamped onto each preview card on every form input / change, so the swatch + border-width + shadow + lift + timing update instantly without a save round-trip. Hover the cards to see the configured `hover_shadow` + `hover_transform`.
- **Aggregator CSS** appended to `frontend.css` wires every existing card class (`.fe-meeting-card`, `.fe-meeting-detail-card`, `.fe-meeting-extended-card`, `.fe-recovery-threeup-card` — primary; `.fe-feature-card`, `.fe-quick-card`, `.fe-faq-item`, `.fe-inclusion-card`, `.fe-meeting-mag-side-card`, `.fe-event-detail-card` — secondary) to the new tokens for shadow / transition / hover behaviour. Border-width is patched on each card's own `border:` declaration (so the shorthand still wins over inline overrides), border-colour comes from the existing colour tokens.
- **Opt-in classes** — `.fe-card-primary` / `.fe-card-secondary` turn any block into a card surface using the same tokens (bg + border + shadow + hover lift, in both light and dark modes).
- **Container builder option** — every container block gains a new "Card style" panel in its settings modal with a select (`None / Primary card · meeting-card look / Secondary card · feature-card look`). The selection writes `d.card_style` onto the block; the public renderer (`_blocks.html`) emits the matching `fe-card-primary` / `fe-card-secondary` class on the rendered `<div>`. Per-block inline styles (bg / border / shadow) still layer on top, so admins can fine-tune one container without unlinking it from the global card style.
- **Editable hex chip** — the colour-token rows (both Colors and Card styles tabs) replace the read-only `<code>` hex caption with an `<input type="text">`. Type or paste a hex value and the swatch updates, the Override checkbox ticks itself, the field gets the overridden styling, and the save bar lights up — same effect as opening the native colour dialog. Invalid input shows a red border (via `:invalid:not(:placeholder-shown)`) and rolls back to the picker's current colour on blur.

### Added — Secondary card colour tokens (feature-block style propagated site-wide)

Four new colour design tokens — `color_card_secondary_bg`, `color_card_secondary_bg_dark`, `color_card_secondary_border`, `color_card_secondary_border_dark` — with defaults derived from the homepage features-block visual (Classic: `#f4f7fb` panel-soft / `#e2e8f0` border / `#131a33` dark bg; Recovery-blue: `#f1f5f9` / `#cbd5e1` / `#131a33`). Every card matching that style — `.fe-feature-card` (the source), `.fe-quick-card`, `.fe-faq-item`, `.fe-inclusion-card`, `.fe-meeting-mag-side-card`, `.fe-event-detail-card` — now resolves its bg + border through the new tokens in both light and dark mode, with the previous hard-coded value retained as the fallback so existing installs render identically until the admin overrides anything. Tweak a secondary-card colour once and the homepage features block, quick-access cards, FAQ items, inclusion block, meeting-magazine sidebar, and event-detail panels all update uniformly.

### Added — Primary card colour tokens (meeting-card style propagated site-wide)

Four new colour design tokens — `color_card_primary_bg`, `color_card_primary_bg_dark`, `color_card_primary_border`, `color_card_primary_border_dark` — with defaults derived from the existing meeting card visual (`#ffffff` bg in light / `#131a33` dark; theme-accent border in light / `#1f2a44` dark). Applied to every card that shares the meeting-card style: `.fe-meeting-card` (the source), `.fe-meeting-detail-card`, `.fe-recovery-threeup-card`, `.fe-meeting-extended-card`. The previously-named `color_card_dark` token (which only fed the fellowships card dark surface + sort `<select>` background + `<option>` background) was removed and its three sites converted to `--fe-color-card-primary-bg-dark` — one token for "dark elevated card surface" instead of two redundant ones. Saved overrides for the removed key are silently ignored on load by `resolve_design`'s unknown-key guard, so no migration is needed.

### Fixed — Block payloads no longer reset when moved between containers

Dragging a heading (or any block) out of a nested container in the page builder was silently losing its text and other in-modal edits. Each structure-card pill stored its block data in a `data-block-payload` attribute set once at server render. When the user opened the modal block editor and edited a heading's text, that change lived only in the BlockEditor's internal `state.sections` — the pill's DOM attribute stayed stale. Then when the user dragged the block out of its container, `syncStateFromDom` rebuilt the hidden `blocks_json` field by reading those stale pill payloads, quietly clobbering the modal edits.

Fix: keep pill payloads in sync with editor edits in real time. Two new helpers exposed from `page_structure.js`:

- `window.tspSyncStructurePayloadsFromState(stateSections)` — walks an entire BlockEditor state, refreshing every matching pill's `data-block-payload` + `data-preview` and merging container settings into the live `containerPayloadById` map (preserving each container's `.data.blocks` since the structure card stays canonical for composition). Called from the editor modal's `input` listener on every keystroke.
- `window.tspSyncStructurePayloadOne(id, payload)` — single-block variant for the dedicated modals (hero / meetings / events / features / FAQ). Called from each modal's `persistModalToBlock` after writing to `blocks_json`, so the in-session view also reflects edits without waiting for a save round-trip.

Drag a heading out of a container after editing it in the modal — the text + every other setting now travel with the pill.

### Added — Block + container duplication in the page builder

Every block pill gains a `⧉` icon button next to the existing `×`, and every container row gains a "Duplicate" action alongside Settings + Remove. Clicking duplicate deep-clones the payload (re-uid'd top to bottom — nested container children get fresh ids too) and inserts the copy immediately after the original.

- Top-level leaf pills are wrapped in a `.fe-page-structure-row--single`; duplicating them produces a fresh row at the same level rather than a sibling pill that would collide inside the original's single-block zone. Nested + orphan pills duplicate as straight sibling pills in the same drop zone.
- Container duplication uses `makeRowFromPayload(clone)` so a duplicated container renders as a full row (with its own column cells, drop zones, and recursive children).
- Wired through `bindRemoveButton` + the existing MutationObserver + delegated click handler so duplicate buttons on freshly-minted pills (palette drops, row-factory output, the duplicate itself) pick up the same behaviour automatically. The "open editor modal" pill-click guards now skip clicks on the duplicate buttons too, so duplicate doesn't double-fire as an edit.

### Changed — Flex containers render as single-zone flow in builder

Flex containers in the page builder used to split into N column cells (one per child) whenever `direction: row` — which misrepresented how flexbox actually works: children are siblings inside one container, not isolated tracks. Now every flex container renders as a single drop zone in the structure card, regardless of `direction`. The zone gets a flex-flow class (`fe-page-structure-block-list--flex-{row|column|row-reverse|column-reverse}`) that matches the configured direction, so pills inside lay out exactly how they will on the public site. Grid containers keep the N-cell visualisation (the public CSS Grid layout actually does map children to discrete tracks).

- **Wording** — flex containers now label themselves "Flex row container" / "Flex column container" (matching the configured `direction`) in both the inline-edit placeholder and the chip below. Grid containers keep the existing "N-column container" wording.
- **Column flow pills stretch full-width** — `align-items: stretch` on `.fe-page-structure-block-list--flex-column` + `width: 100%` on each pill, so vertical-flow containers read as a stack of equal-width pills (the way they'll render on the public site).
- **Row flow pills size to content** — `width: auto; flex: 0 0 auto`, so several pills can sit side-by-side in a horizontal row.
- **Auto-provisioning** — the showcase pattern (one inner-container shell per cell) only applies to multi-column GRID containers now. Flex containers hold their direct children flat.

### Fixed — Nested container layout adapts on narrow viewports

When containers were nested inside other containers, the inner row's 130-px label gutter (which holds the row-num chip + Settings + Remove + Duplicate buttons) at ≥720 px was eating the drop zone — three deep the zone collapsed to nothing at typical admin viewports. Nested rows (any `.fe-page-structure-row` inside a parent's `.fe-page-structure-col`) now always stack the label + action buttons above their columns grid, with the label laid out as a horizontal strip (input + chip + Settings + Duplicate + Remove) so the gutter stays compact above the full-width drop zone. Top-level rows are unaffected.

### Changed — Block pills hover-expand so edit/delete stay reachable

In narrow nested cells, the "Edit" hint chip + × remove button at the right edge of clickable pills used to clip against the cell border, making them unreachable. On hover (or keyboard focus-within), the pill now grows to `min-width: max-content` and lifts above neighbouring content with `position: relative; z-index: 5` + a soft drop shadow — so every control is visible and clickable no matter how tight the column. Cells aren't `overflow: hidden`, so the pill simply paints beyond its column without disturbing the surrounding layout.

### Added — Collapsible sidebar sections

The labelled sections in the main admin sidebar (Intergroup / External / Admin) collapse + expand independently. Each section's divider is now a `<button>` with an aria-expanded toggle + a chevron that rotates -90° when collapsed; the items wrapper hides via `[hidden]`. Per-section state persists in `localStorage` under the `tsp-sidebar-collapsed` key, and is re-applied after the AJAX nav refresh triggered by Settings saves so collapse state survives module-toggle round-trips. The unlabelled "main" section (top items) stays always-visible.

### Changed — File browser: thumbnails, grid view, pagination, lightbox prev/next

The File Browser (`/tspro/files`) is now a usable visual library instead of an opaque table:

- **List view** — every row leads with a 48×48 thumbnail. Images render the actual file (lazy-loaded, `object-fit: cover`); PDFs / docs / video / audio render a typed icon + extension badge fallback. Clicking the thumbnail (or filename link, as before) opens the lightbox for previewable types.
- **Grid view** — toggle in the top actions switches to a responsive `auto-fill, minmax(180px, …)` card grid with square thumbnail surfaces and filename + size below. Each card has hover-lift + brand-coloured border. The toggle's "List" / "Grid" preference persists in the existing `view-media` cookie alongside sort + direction.
- **Lightbox** — collects every previewable item on the page and lets you step prev/next via on-screen chevron buttons or ← / → arrow keys, with a "3 / 17" counter in the header. Works for both views and the picker preview button. Image and PDF previews unchanged from before; other types fall back to opening in a new tab.
- **Server-side pagination** — `/tspro/files` now paginates at **100 records per page**. The route builds a single SQL query that pushes the hidden-filename + pending-uploads + search filters and the chosen sort (with a SQL `CASE` for the `type` bucket so it groups by extension globally) before `.offset().limit()`, returning exactly one page's worth of rows regardless of catalog size. A pagination footer below the list/grid shows "Showing X–Y of N" + First / Prev / Page / Next / Last buttons (disabled at the ends).

### Fixed — Frontend FAQ block fills its container in the page builder

The shared FAQ partial (`frontend/blocks/faq.html`) always wrapped itself in `<section class="fe-section"><div class="fe-container">` — which on the page-builder render path was capping the accordion to the partial's own 1160-px `.fe-container` regardless of the surrounding builder container's width. New `faq_no_chrome` flag, passed from `frontend/page.html`'s FAQ branch, drops both wrappers in builder context and forces the inner `.fe-faq-list` to its full-width mode. The accordion now fills whatever container width the admin set on the parent. New `.fe-faq--bare` class zeroes section padding and the auto-centring margin (only horizontal — vertical rhythm on the list + section head is preserved); only kicks in on the builder path, so the homepage's full-section FAQ is unchanged.

### Changed — Removed hidden 28 px / 5 vw padding on `.fe-container`

The `.frontend-body .fe-container` selector had a baked-in `padding: 0 28px` (and `padding: 0 5vw` at ≤560 px) that admins couldn't see or override from the page-builder. The container now enforces only `max-width: var(--fe-container-max)` + horizontal centring; every gutter / horizontal padding decision lives in the per-section / per-container builder settings.

### Added — Stories admin bulk actions

The `/tspro/stories` admin page gains the same multi-select / bulk-action UI the Posts admin has had since 1.8: a row of checkboxes (per row + select-all in the header), a hidden pill-shaped action bar that slides in once you've selected at least one story, and one POST handler that processes the whole batch in a single transaction.

- New `story_bulk` route (`POST /tspro/stories/bulk`) accepts `action` ∈ `{archive | unarchive | draft | publish | delete}` and a repeated `ids` field. Mirrors `post_bulk`'s shape exactly — id-parse with silent skip on stale ids, single `Story.id.in_(...)` lookup, action-specific commit. Delete path snapshots featured-image filenames + inline `/pub/` body image paths *before* row removal so `_cleanup_retired_asset` can run after commit with the row no longer pointing at the files (otherwise the residual-reference check would keep the asset alive forever).
- Activity log writes a single `story.bulk_<action>` row per batch with the count and label, so the User Log shows "Bulk archived 12 stories" rather than 12 separate events.
- Bulk-action bar adapts to the current tab — no `Archive` button while viewing Archived (would be a no-op), no `Move to drafts` on Drafts, no `Publish` on Published. `Delete` and `Clear` are always present.
- Per-row action buttons (Edit / Publish / Drafts / Archive / Delete) now reference sibling `<form id="single-story-...">` stubs via `form="..."` so a row's individual archive/delete button can sit inside the bulk form without nested-form warnings.
- Selected rows pick up a subtle brand-tinted background via `tr[data-story-row]:has(input:checked)` so it's obvious at a glance which rows are about to be bulk-actioned.
- Inline JS (same shape as `posts.html`): row-check listeners refresh the counter and reveal the bar, select-all toggles every visible checkbox with proper indeterminate state when partially selected, each `[data-bulk]` button writes its action name into the hidden field and submits with an optional confirm prompt (count interpolated into the message — "Delete 7 selected stories permanently?").
- Toolbar + bulk-bar styles (`.posts-toolbar`, `.posts-bulkbar`, `.posts-bulkbar-count`, `.posts-th-check`, `.posts-check-wrap`) were previously defined inline in `posts.html` and `blog_list.html`. Lifted into `stories.html` so the bulk pill chrome renders correctly on this page. `margin-bottom: 1rem` on the stories toolbar gives the "Showing N stories" line breathing room above the table — Posts and Blog keep their existing 0.85rem.

### Added — FAQ block: 1/2-column layout, boxed/full-width, side-padding control

The per-page FAQ block (page-builder modal `#page-faq-edit-modal`) gains three layout knobs above the items list. All three default to the historic single-column / boxed / no-extra-padding render, so unedited FAQ blocks are byte-for-byte identical post-upgrade.

- **Columns** — `1` (default) or `2`. The 2-column variant splits items into two independent flex stacks at template render time (`ceil(N/2)` on the left, the remainder on the right) so each column is its own stacking context. Critical: a single CSS Grid would share row heights between columns, so a taller card on one side would push the other side's items down by inflating the shared row — separate stacks mean the right column's heights can never reach across and affect the left's. Both columns sit flush to the top of the FAQ list; items pack to the top of each column via the flex column's natural flow.
- **Width** — `boxed` (default, 760px column on 1-col / 1080px on 2-col) or `full` (lifts the cap so the accordion bleeds to the parent container's edge — useful when paired with a wide page or the 2-column layout).
- **Side padding** — integer-pixel slider (0..200px) that adds inner horizontal padding on the FAQ block's `.fe-container`. Lets the admin tuck the accordion inside a gutter without nesting it in a wrapper container block.
- **Storage** — three new optional keys on the FAQ block's `data`: `columns`, `width_mode`, `pad_x`. Modal inputs carry `data-faq-field="<key>"` so the existing two-way binding in `page_faq_modal.js` picks them up alongside heading/subheading — generalised `readModal()` / `populateModalFromBlock()` so the JS walks every `[data-faq-field]` element rather than hardcoding each key.
- **Pill preview** — the block-list pill's subtext now shows `N items · 2 col · full-width` (or `· 1 col` for the default) so you can see the layout at a glance without opening the modal.

Public render lives in `frontend/blocks/faq.html`: applies `.fe-faq-cols-{1|2}` + `.fe-faq-w-{boxed|full}` classes; injects inline `padding-left/right` on `.fe-container` when `pad_x > 0`. The 2-column markup is two `.fe-faq-col` divs wrapping the item lists; CSS lays them out as a flex row with `align-items: flex-start` so each column sizes to its own content (grid's default `align-items: normal` was resolving to `stretch` in some browsers and stretching the shorter column, leaving its cards visually centered in the column). On phones (≤720px) the row wraps to a single-column stack.

### Fixed — Nested page-builder containers were inheriting the parent container's shadow / bg / border / hover

CSS custom properties inherit by default. When the outer container's inline style set `--block-cont-shadow: <value>`, that variable cascaded to every descendant — and any nested `.block-container` read it through `box-shadow: var(--block-cont-shadow, none)`, with the inherited value winning over the `none` fallback (which only applies when the variable is truly unset, not when inherited). Same latent leak affected `--block-cont-bg`, `--block-cont-border-color`, `--block-cont-border-width`, every `--block-cont-hover-*`, and the grid/flex layout vars.

Fix: reset every container-scoped variable to its default at the top of the `.block-container` rule. Inline styles on the same element still win (specificity 1,0,0,0 > 0,0,1,0), so a container that DOES declare its own values keeps them intact — but inherited values from ancestors no longer leak through. Each container now starts from a clean slate, so a nested container with no shadow configured stays shadow-free even if its parent has one.

### Added — Frontend visitor metrics (anonymous page-view analytics for the public site)

A new admin-only analytics surface that tracks real human traffic to the public web frontend. Signed-in users (admins, editors, intergroup members, viewers) are excluded from every count — the metrics page reflects actual visitors only.

**Schema:**

- New `VisitorEvent` model (`app/models.py`) — one row per anonymous page view. Columns: `created_at`, `day` (UTC `YYYY-MM-DD` for cheap date-bucketed aggregations), `path`, `endpoint`, `referrer_host` (origin only — full referer URLs never persisted), `device` (`mobile`/`tablet`/`desktop`/`other`), `browser`, `os`, `visitor_hash`. Indexed on `(day, path)` and `(day, visitor_hash)` so the metrics-page rollups scan a small slice rather than the whole table.
- **Privacy:** no IP, no User-Agent string, no full Referer URL is ever stored. `visitor_hash` is a daily-rotating BLAKE2b of `(SECRET_KEY, UTC date, IP, UA)` — the salt rotates at midnight UTC, so a hash is a stable identifier within a single day but a different hash the next day. Uniques are estimated from `COUNT(DISTINCT visitor_hash)` per day.
- New `User.dash_show_visitor_metrics` boolean column (default true, migration entry added to `_migrate_sqlite`) — drives the per-user dashboard customize toggle.

**Recording pipeline (`app/visitor_metrics.py`):**

- Mounted as a `before_request` hook on the `frontend` blueprint so admin-portal traffic is never recorded.
- Drops requests that are: authenticated (`current_user.is_authenticated`), non-GET, asset fetches (any of `/static/`, `/pub/`, `/site-branding/`, `/favicon` or extension `.png|jpg|jpeg|gif|webp|avif|svg|ico|css|js|woff|woff2|ttf|otf|eot|mp4|webm|mp3|ogg|m4a|pdf|zip|json|xml|txt|map`), browser prefetches (`Sec-Purpose: prefetch`, `Purpose: prefetch`), empty UA, or bot UA (~30-token allowlist covering Googlebot, Bingbot, Facebook/Twitter/LinkedIn link previews, Discord/Telegram/WhatsApp previews, Yandex/Baidu/DuckDuck, SEO crawlers Ahrefs/Semrush/MJ12/Petal, monitoring bots Pingdom/UptimeRobot, headless Chrome / Lighthouse / PageSpeed, and common HTTP libraries curl/wget/requests/axios/okhttp/go-http-client).
- Cross-blueprint guard: even if a future change accidentally registers the hook elsewhere, the recorder bails when `request.endpoint` doesn't start with `frontend.` — admin-portal traffic can never leak into the table.
- User-Agent parsing is a small dependency-free lookup (`_BROWSER_PATTERNS` / `_OS_PATTERNS`). Edge/Brave/Vivaldi/Opera are matched before Chrome (they all carry "chrome" in the UA); iPads masquerading as Macs are routed to `tablet` via the touch-event tiebreaker.
- Defensive at every step — any exception in the recorder is swallowed (with a session rollback) so a flaky write can't break the public page render.

**Admin metrics page** (`/tspro/frontend/metrics`, admin-only, inside the Web Frontend subnav under Overview):

- Five top-line summary tiles — Views in window (with inline 14-day sparkline), Unique visitors in window (+ derived views-per-visitor), Today (with `↑/↓` delta vs yesterday), Yesterday, Last 7 days.
- Full-width inline-SVG time-series chart — filled area for total views (brand gradient) overlaid with a dashed purple→cyan stroke for unique visitors. Horizontal grid lines + tick labels on the Y axis; adaptive X-axis label density (every 1/3/7 days depending on window length). One `circle` per day wires up a hover tooltip that shows the day + both counts.
- Hour-of-day distribution — 24 vertical bars showing average traffic per hour (UTC, last 30 days).
- Three donut charts — Devices, Browsers, Operating systems. Each donut renders as concentric `circle` arcs with `stroke-dasharray` slices (no external chart library), centered with the total view count, alongside a legend list with swatch / label / count.
- Two top-N tables — Top pages (links to the public URL, opens in new tab) and Top referrers (`Direct / bookmark` for null referrers, external link icon otherwise). Each row carries an inline bar gauge showing its share of the top result.
- Window selector top-right (`7 / 14 / 30 / 90 days`); the route's `_resolve_metrics_window` only accepts those four values so hand-crafted query strings can't widen the scan.
- Page renders inside `fe-admin-layout` with `_frontend_subnav.html` so the Visitor Metrics entry highlights as active and the page reads as part of the Web Frontend module.

**Dashboard widget** (admin-only, draggable, "Frontend Visitor Metrics"):

- Three stat tiles — Today, Last 7 days, Unique · 30d — with the Today tile in brand-tinted accent style.
- Inline-SVG 14-day sparkline (filled area + stroke). When there's no traffic yet, shows a friendly "No visits yet — once the public site sees real traffic, the chart will populate." message instead of a flat line.
- "Open metrics →" link in the card header navigates to the full metrics page.
- Widget participates in the existing dashboard drag-drop reorder; per-user toggle in the Customize Dashboard modal (admin-only section, default on).
- New JSON endpoint `/tspro/frontend/api/visitor-metrics/summary` returns the summary numbers + sparkline series — wired for future polling refresh, currently used as the canonical shape definition.

**Sidebar wiring:**

- The Web Frontend subnav (`_frontend_subnav.html`) gains a "Visitor Metrics" entry right under "Overview" (Lucide `bar-chart` icon). Active-state highlight matches when `request.endpoint == 'main.visitor_metrics_page'`.
- No entry in the top-level admin sidebar — the page is conceptually part of the Web Frontend module and lives entirely within its URL space (`/tspro/frontend/metrics`) and its admin layout.

**CSS** — ~200 lines added under `/* ===== Visitor metrics admin page ===== */`. Tile grid responsive 5→3→2→1 columns; chart hover dots animate radius on `:hover`; donut slices animate `stroke-width` on container hover; tooltip uses absolute-positioned `position: absolute` inside the chart wrapper so SVG↔HTML coordinates line up; dark-mode-aware trend arrows (`#16a34a` light / `#4ade80` dark for up; `#dc2626` / `#f87171` for down).

Verified end-to-end on the live install: hit the public site as Chrome/macOS, Safari/iOS, Firefox/Windows, Chrome/Android — all four recorded with correct device/browser/OS parsing; Googlebot UA and `/static/*` asset hits correctly skipped; admin metrics page and dashboard widget both render with live data including the chart, donuts, and top-pages tables.

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
