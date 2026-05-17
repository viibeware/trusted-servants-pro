# Release Notes

User-friendly, scannable summary of every Trusted Servants Pro version
bump. The deeper, version-by-version implementation log lives in
[CHANGELOG.md](CHANGELOG.md).

The same content appears in-app under **Settings → About** with the
release notes expanded by default and the changelog collapsed.

## 2.0.4 — 2026-05-17 (latest) — Dashboard widgets: every widget has a visible grab handle, no more awkward gaps

Two paired fixes for the admin dashboard.

### Every widget now shows a visible grab handle

Three widgets — **Recent Deletions**, **Frontend Visitor Metrics**, and **Contact Form** — were silently missing their drag handle and the underlying `draggable="true"` attribute, so you couldn't reorder them at all. They share a common macro with the rest of the dashboard widgets; a Jinja scoping quirk was causing the macro to skip both pieces of markup. Fixed at the source: every dashboard widget now consistently carries the grab handle and is draggable.

The handle itself was also redesigned. It moved from the top-right (where it disappeared behind every widget's "View all" link and right-aligned metadata) to a **clearly visible chip in the top-left of each widget**, always at full opacity, with a subtle background + border so it reads as a deliberate UI control rather than a faint hover-only icon. Hover and active states still tighten the visual cue.

### Widgets now pack tightly with no awkward vertical gaps

The dashboard grid was a straight two-column layout, which meant whenever one column held a tall widget (e.g. Recent Meetings with many rows) and the other column held a short widget (e.g. Currently Online with one user), the short column would leave a large empty gap waiting for the tall column to finish before the next widget could appear.

The grid is now a **masonry layout**: shorter widgets slide up to fill those gaps automatically. DOM order is still the preferred order — the masonry only back-fills empty space; reorder via the grab handle still does exactly what you expect. Below 720 px the dashboard collapses to a single stacked column with normal spacing.

The layout recomputes itself whenever something changes — window resize, drag-reorder, the **Currently Online** widget's user count changing, the **Frontend Visitor Metrics** sparkline animating in — so the packing stays tight as widget heights flex.

## 2.0.3 — 2026-05-16 — Real client IPs in Watchtower, public library thumbnails

Two fixes that were each producing wrong-looking results in production:

### Watchtower now logs real client IPs

If you've been running behind the bundled Caddy reverse proxy (the default `install.sh` setup), every IP shown in **Watchtower** — Access, Visitors, Requests, the IP-blocklist — was the Caddy container's docker-bridge address (typically `172.x.x.x`), not the real visitor's IP. The Flask app wasn't reading the `X-Forwarded-For` header Caddy was already setting.

This release wires in the standard `ProxyFix` middleware so `request.remote_addr` reflects the real client across the whole app: probe-block log lines, login records, contact-form submissions, Turnstile verification, and the IP-block gate that powers the blocklist.

> **One cleanup step:** any rows you previously added to the **Watchtower → IP blocklist** that captured docker-bridge addresses (e.g. `172.17.0.1`) won't match real client traffic anymore. Open the blocklist panel and clear those out.

If you run the app *without* a reverse proxy in front (bound directly to a public interface), set `TSP_TRUSTED_PROXIES=0` in your `.env` to keep the app from trusting forwarded-IP headers that nothing legitimate is setting.

### Library item thumbnails now load for the public

Library item thumbnails on the public **Literature Library** page (and any homepage / page block that surfaces a library item) were silently 404'ing to anonymous visitors — the route was login-gated. Logged-in admins saw the thumbnails fine; the public saw broken images.

Thumbnails now render publicly whenever the parent library and the item are both flagged as public-visible (the same gate the Literature Library page itself already uses). Private libraries and admin-hidden items continue to 404 to anonymous traffic.

## 2.0.2 — 2026-05-16 — Frontend admin tools: blog edit chip, auth-aware menu/footer, library item summaries

A round of frontend polish focused on giving signed-in admins fast tools on the public site, and making library authoring more flexible.

### Edit any blog post from the public page

Signed-in editors now see a floating **Edit post** chip in the bottom-right corner of every `/blog/<slug>` page. One click lands you in the admin editor. Hidden on mobile labels (icon-only below 640 px) so it doesn't crowd the reading column. Anonymous visitors see nothing. The existing draft / archived preview banner still carries its own edit link, so drafts don't show two stacked affordances.

### Auth-aware Login / Dashboard / Logout in the mega menu and footer

A new **Admin login** block type joins the mega-menu builder under *Web Frontend → Navigation*. Drag it into any column and it renders as a styled button (pill or rounded, your pick) that auto-swaps based on visitor state:

- **Anonymous:** a single **Login** button → the sign-in page.
- **Signed in:** a button row — **Back to TS Pro dashboard** on the left, a yellow **Logout** button on the far right.

The footer's existing Login pill got the same treatment automatically — flips to a Dashboard + Logout pair when an admin is viewing the site. Both surfaces share one visual language (icons, padding, hover) and respect the per-link size slider. **Logout** on the public site now returns visitors to the homepage, not the admin sign-in screen.

### Library Add modal: pick how the item gets its content

The **Add Item** modal (renamed from *Add File*) replaces the old two-mode Upload / Paste toggle with a three-way picker:

- **Upload file / file browser** — same as before; pick a file or grab one from the File Browser.
- **Paste / type content** — Markdown-supported body that opens as its own document.
- **External link** — a URL field for items that live elsewhere.

Each option owns its own content slot: switching tabs hides the others, and saving in a given mode clears the slots it doesn't use. An optional **Summary** field (multi-line, up to 500 chars) sits above the picker for a short blurb that shows alongside the title in lists. The Edit modal got the same treatment — opens in whichever mode matches the existing data.

### Mobile-only mega-menu animation + fade controls

The *Web Frontend → Navigation → Mega menu appearance* page grew a **Mobile (≤ 720 px)** subsection with three new knobs that only kick in on small viewports:

- **Staggered link entrance · mobile** — turn the staggered reveal off on phones where it can read as flicker.
- **Stagger speed · mobile** — independent ms slider.
- **Fade speed · mobile** — independent ms slider for the panel fade-in.

Desktop tuning is untouched. The desktop *Show on hover fade* toggle still gates whether the panel fades at all on every viewport.

### Polish

- **Meeting card titles** on the homepage now render at weight 600 instead of inheriting the heavier 700 from their wrapping heading.
- **Hidden fieldsets actually hide** — a CSS rule was overriding the user-agent's `[hidden] { display: none }` for `.fieldset` elements, so any toggled fieldset (like the library content-mode panels) kept rendering. One-line fix.

### Under the hood

- New `LibraryItem.summary` column (additive migration; existing data untouched).
- `auth.logout` now accepts a validated `?next=` redirect target. Strict path-only validation — open-redirect smuggles get bounced.
- The library save handler enforces single-channel content per item — a row can never carry both a file and a URL the way some legacy rows could. Existing data is preserved until you next edit + save.

## 2.0.1 — 2026-05-16 — Meetings-list + Pro Tips cards now ride the Primary-card design tokens

Two small but visible polish fixes for the public meetings page in dark mode:

- **Meetings-list cards are solid again.** A stale CSS rule was painting them at 3% white — close to invisible — over the page background. They now read on a solid Primary-card-dark surface and pick up your *Site → Design → Card styles → Primary card → Background (dark)* token. Light mode is unchanged.
- **Pro Tips cards match the meeting cards.** Each tip in the Pro Tips accordion (both the standalone block at the bottom of the directory + weekboard layouts and the inline block on the sidebar layout) now adopts the canonical Primary-card recipe — background, border, border-radius, hover lift, hover shadow, dark-mode swap — instead of its own hardcoded colours. Editing the Primary card design tokens once now re-tints the meeting cards and the Pro Tips cards together.

No data changes, no admin action needed.

## 2.0.0 — 2026-05-16 — Watchtower: one place to watch the door

This is a major release. **Watchtower** is a new top-level admin module that replaces three older admin pages (User Log, Delete Log, Access Requests) with a single, security-focused dashboard — and adds real teeth: anomaly detection, an IP blocklist that actually blocks at the door, force-end on sessions, and a failed-login leaderboard with one-click bans. It's the new home for everything you'd want to know about who's signed in, who tried to sign in, what they did, what got deleted, and who's asking for an account.

### Where to find it

Sidebar → **Admin → Watchtower** (admin-only). The old **Access Requests**, **User Log**, and **Delete Log** items are gone — their data lives inside Watchtower now. Anyone deep-linking the old URLs (`/user-log`, `/delete-log`, `/access-requests`) will see a 404 — please update bookmarks to `/watchtower`.

### What's in it

- **Overview tab.** Seven KPI tiles at a glance — views today, unique visitors, who's online right now, failed login attempts in the last 24 hours, blocked IPs, pending access requests, and files in the recycle bin. A system-health card with live CPU, memory, load average, and uptime. A 30-day visitor traffic chart, a 24-hour failed-login bar chart that colours hot hours red, a banner that fires when something looks off ("brute-force attempt in progress", "concentrated attack from 1.2.3.4"), a top suspicious-IPs table with one-click **Block**, a recent admin-activity feed, an active-sessions list with **End session**, and the live IP blocklist.

- **Visitors tab.** Everything from the old Visitor Metrics page — KPI strip, traffic chart, top paths, top referrers, device breakdown, hour-of-day distribution — now inside the Watchtower shell.

- **Access tab.** The new security operations centre. A failed-login leaderboard for the last 7 days with **Block**, **Unblock**, and **Clear** on every row; a manual ban form (permanent, or 1 hour / 24 hours / 7 days / 30 days); the active blocklist with hit counters so you can see whether each ban is actually being hit. Below that, **Login sessions** at the top of the audit-log area (the answer to "who's signed in?" is the first thing you see), followed by the activity feed — now showing the most recent 20 entries with an inline **Show N more** button to expand the rest without leaving the page.

- **Deletes tab.** The recycle bin with **Restore** / **Purge now** on each row. Files are restorable for 30 days; the auto-purge runs on every page load.

- **Requests tab.** Active and archived access requests with **Create User**, **Mark Handled**, **Archive**, **Delete**. Pending password resets and the 30-day reset history sit alongside.

### Block an IP at the door

Watchtower ships a real IP blocklist. When you click **Block** anywhere — on the Overview, on the suspicious-IPs table, or via the manual form — the IP is added to a database table. From that moment on, *every* request from that address gets a 403 before the page renders, before assets are served, before anything else runs. A hit counter on each row tells you whether the ban is actually catching traffic. Temporary bans expire automatically; permanent bans stay until you click **Unblock**.

Every ban, unban, session-end, and failure-clear is written to the activity log, so you can always answer "who did this and when".

### Polish

- **Page background colour** in *Web Frontend → Templates → Customize* now supports a dark-mode variant — pick **Same as light**, **Auto** (uses the *Surface — Darkmode* design token, so it tracks your site palette), or **Manual** (set your own hex). Every existing frontend template picks up the swap automatically.
- **Classic blog detail** no longer shows a subtle border-colour flash when you hover over the article body or its sidebar cards.

### Migration notes

- The new `ip_block` table is created automatically on first boot.
- Three legacy URLs were removed (`/user-log`, `/delete-log`, `/access-requests`). All POST action endpoints that used to live under those paths now live under `/watchtower/...` — internal links were updated.
- No data migration; everything historic (activity log entries, login sessions, deleted files, access requests, visitor events) shows up in Watchtower untouched.

## 1.10.5 — 2026-05-15 — Blog overhaul: visual block editor, redesigned editor sidebar, classic detail polish

A sweeping refresh of the blog module — the markdown textarea is gone, replaced by a delightful visual editor; the edit page got a metadata sidebar; the classic public template adopts the design-token primary card look; and a few admin-set knobs that quietly weren't responding (template background, mesh randomize, comments) are fixed or retired.

### Section block: group blocks with controllable spacing

The body editor's palette gained a new **Section** block — a container that wraps other blocks with adjustable top and bottom margin (rem, default 3 / 3). Drag it from the palette like any other block; once it's on the canvas, drag more blocks straight into its inner drop zone, or drag existing blocks from the top level into the section (or back out). Each section gets its own zone with the same insert-marker affordance. Sections can hold any block type *except* another section.

### Container width control on the blog detail page

*Web Frontend → Templates → Blog detail* now has a **Container width** fieldset that matches the Blog list one: pick **Boxed** (capped max-width, default 1160 px, range 640–2400) or **Full width** (spans the viewport with side padding as a viewport-% gutter, default 5%). Applies to all four detail templates — classic, modern, cover, and longform. Longform's narrow-essay default still kicks in by default, but the admin's chosen width wins when set.

### Preview unpublished posts on the public URL

Signed-in editors can now visit `/blog/<slug>` for any **draft** or **archived** post and see it rendered exactly as it would publish — with an amber **Draft preview** / **Archived preview** banner at the top reminding them why a regular visitor wouldn't see this page. The banner carries a one-click **Edit post →** link back to the admin form. Anonymous visitors still get a clean 404 on unpublished URLs.

The action-bar **View on Frontend ↗** button on the blog edit page also shows for drafts and archives now — its label flips to **Preview draft ↗** / **Preview archived ↗** so you know what you're opening.

### Hyperlist is now permanently dark + starts the week on Sunday

The accessibility-first Hyperlist (`/hyperlist`) used to follow the OS preference for light vs dark — that meant the page looked different depending on the visitor's system. It now ships a permanent near-black palette, decoupled from both the site theme and the OS preference. The brutalist white-on-black look is part of the template's identity.

The day sections also reorder to **Sunday → Saturday** to match the calendars folks read in everyday life. The "Filter is optional — without JavaScript every meeting stays visible." sentence in the search hint was removed.

### Writing a post

- **Visual drag-and-drop body editor.** The body is now a stack of block cards — paragraph, heading (H2 / H3 / H4), image, button, list (bulleted or numbered), quote, callout (info / success / warn / danger), divider, video (YouTube / Vimeo URL → auto-embed, or self-hosted MP4), and code. Click the floating **+ Add block** pill in the bottom-right (same chrome as the page builder) to drop a fresh block, or drag any tile from the palette right into the canvas at the exact insert point — an animated marker shows where the block will land.
- **Each block edits inline.** No modals. Drag handle on the left of every block to reorder; toolbar on top to duplicate, move up / down, or delete. Lists handle `Enter` (add row) and `Backspace` (remove the empty row + jump to the previous).
- **Image blocks have a file-library picker.** Click **Browse** to pick from images you've already uploaded — same modal as the page builder, with search by filename and inline drag-to-upload. Or just paste a URL.
- **Markdown still works inline.** Paragraph, list, quote, and callout bodies all support `**bold**`, `*italic*`, `[link](https://…)` so prose-style writers don't lose anything.
- **Older posts keep their Markdown body** until you re-save with blocks. Nothing migrates automatically.

### Edit page layout

- **Two-column layout.** The main column (Post + Body) fills the available width; a new ~320px metadata column on the right holds everything else — publication, author, categories & tags, and featured image — merged into one card with section headings.
- **Categories as a checkmark list** (not pills any more) with an **Add new category** field below it. Type a name, click Add (or press Enter), and the new category appears pre-checked. Same UX for tags now — checkmark list of every tag plus inline `Add new tag`. Pressing Enter in either field used to accidentally publish the post; that's fixed (a form-level guard now intercepts Enter on every text input *except* the title, where it still submits for muscle memory).
- **Author picker is now an Intergroup roster dropdown.** Lists every member from *Settings → Global*, labelled `Name — Role` so two members with the same first name stay distinguishable. Existing posts whose `author_name` doesn't match a current roster entry surface a "(legacy)" option so a Save doesn't silently drop the previously-saved byline. The free-form bio textarea is gone (the column stays so existing public templates that show a bio still work).
- **Featured image gets a Browse Library button** next to Upload — same library modal as the body image blocks. Picking a tile sets the post's featured image to the chosen file (no duplicate on disk) and shows a "Will use: <filename>" indicator until save.
- **Live title → slug** — typing the title rewrites the URL field as you type, with a brand-tinted highlight (same as the announcement / event editor).
- **View on Frontend ↗** button in the top action bar — opens the public `/blog/<slug>` URL in a new tab whenever the Web Frontend module is on and the post isn't a draft or archived.

### Comments feature removed

The **Allow comments** checkbox in the publication section is gone, along with the comments feature entirely — no UI, no public render path, no downstream consumer. The underlying database column is preserved (SQLite can't drop a column in-place without rebuilding the table, which the safety rule rightly blocks) but nothing reads it.

### Classic blog detail template polish

- **Primary card surface, hover lift, and accent border** now apply to the main post card, the Related / Categories sidebar widgets, and the author bio aside. Adjust the look site-wide from *Web Frontend → Design → Card styles → Primary card*.
- **Featured image now leads the post card** — sits above the category chips, title, and byline, and bleeds edge-to-edge across the card's top with rounded corners that match the card. Same look as the list-view cards.
- **Sidebar widgets are toggleable per-template** — *Web Frontend → Templates → Blog detail → Classic → Customize* now exposes Show *Related* widget / Show *Categories* widget. Turn one off and only the other shows; turn both off and the right rail disappears entirely, letting the post expand to the full container width.

### Fixed

- **Template background settings now apply on the classic blog detail.** The article was painting its own surface from a variable that never read the admin-chosen background — the static colour / gradient / image picker now flows through. For dynamic animated backgrounds (mesh / aurora / etc.) the article renders transparent so the animated canvas shows behind the post card.
- **Mesh-gradient randomize toggles actually randomize on the classic blog detail.** Selecting *random colors* + *random positions* on a mesh background now repaints the palette + mesh anchor / angle on every page load (the host element was missing the CSS variables the mesh CSS consumes). Other surfaces that already worked are unchanged.

### Blog list cards

- **All card-shaped list layouts** (Cards / Sidebar / Magazine / Mosaic) now inherit the Primary card design-token surface — same bg / border / border-radius / shadow / hover lift / hover accent border as the rest of the project. Gazette and Minimal are text-row layouts so they're untouched.

## 1.10.4 — 2026-05-15 — Visitor metrics: no more phantom traffic when the public site is off

A small follow-up to 1.10.3. When the web frontend was disabled, the Visitor Metrics widget was still counting scanner / crawler hits to public-site URLs (`/`, `/meetings`, `/events`, etc.) — those requests get redirected to the login screen as designed, but the recorder was already writing the row before the redirect kicked in.

- **The visitor recorder now respects the frontend gate.** When `Web Frontend → Enable public site` is off, page hits stop registering as visits. Login-page traffic was never affected.
- Historical rows are left alone — going forward the counts will only include traffic that actually saw a public page.

## 1.10.3 — 2026-05-15 — Security hardening sweep

A defensive security pass triggered by production probe traffic for `.env` and friends. The portal was already safe (Caddy doesn't serve files from disk; `.env` isn't in the Docker image) but this release tightens a handful of best-practice gaps that a careful audit surfaced.

- **Attacker probe paths return a bare 404** — requests for `/.env`, `/.env.backup`, `/.git/config`, `/wp-admin/`, `/phpmyadmin/`, `/xmlrpc.php`, `/.aws/credentials`, `/credentials.json`, `/backup.zip`, and dozens more well-known recon targets now short-circuit before the 404 template renders. Zero body, no branding reflected back to scanners, one log line per probe so you can see attack patterns.
- **Open-redirect class fixed** — every "bounce the user back where they came from" handler now validates `Referer` is same-origin before honouring it. Previously an attacker could host a page that linked into a protected route and bounce the victim off to an external site on the permission-denied flash.
- **SVG uploads sanitized in every code path** — `<script>` tags, `on*=` handlers, and `javascript:` URLs are now stripped on the way in for *every* SVG upload (was only the Custom Icons admin path). SVG remains admin-only.
- **Default `admin/admin` eliminated** — the bundled installer now generates a strong random admin password automatically and prints it once at the end of the install. Production refuses to start without `TSP_ADMIN_PASSWORD` set. Local dev (`TSP_DEBUG=1`) still falls back to `admin/admin` for convenience.
- **Encrypted-credential failures now logged** — rotating `TSP_SECRET_KEY` or replacing the Fernet key used to make stored Zoom / OTP passwords silently disappear from the UI. The decrypt path now logs a warning per affected column so the breakage surfaces in container logs.
- **Two more cross-origin hardening headers** — `Cross-Origin-Opener-Policy: same-origin` (blocks `window.opener` attacks) and `Cross-Origin-Resource-Policy: same-origin` (blocks external sites from hot-linking our responses) are emitted on every response.

## 1.10.2 — 2026-05-14 — Per-page link previews, Home Screen icons, detail-card style + announcements/events polish

Layered on top of 1.10.1 — every public detail page now ships its own Open Graph preview (so a meeting / event / story / blog link pasted into Slack or iMessage shows that entity's logo + title + summary instead of the site-wide fallback), separate iOS Home Screen icon + name for the admin portal and the public site, detail cards swapped to the meeting-card visual family, View on Frontend on the post editor, cleaner announcement cards + linkable GSR titles, mobile padding restored on homepage Meetings + Events blocks, and a redesigned More events grid.

- **Per-page Open Graph link previews** — meeting / event / announcement / story / blog detail pages now emit their own `og:title`, `og:description`, and `og:image`. Meetings use the **meeting logo**; events / announcements / stories / blog posts use their **featured image**. Anything missing falls back to the site-wide values under *Web Frontend → Branding & SEO*. (Make sure the **Enable link previews** toggle there is on.)
- **Content pages** get a new **Open Graph / Link Previews** section on the page-edit screen — set a custom title, description, and preview image per page; any field left blank falls back to the site-wide defaults.
- **iOS Home Screen icon + display name** — separate controls for the admin portal (*Settings → Appearance*) and the public site (*Web Frontend → Branding & SEO*). Visitors who "Add to Home Screen" on iPhone / iPad now see the icon and label you upload here instead of the bundled defaults. 180×180 PNG with an opaque background works best — iOS rounds the corners.
- **Event / announcement / archive detail cards** (Schedule / Location / Online / Contact panels) now use the **Primary card** design tokens, matching the elevated meeting-detail card look. Adjust them site-wide from *Site → Design → Card styles → Primary card*.
- **View on Frontend ↗** button on the announcement / event admin edit page — opens the matching public URL (event / announcement / archive) in a new tab.
- **Announcements list cards** dropped the redundant *View details ↗* CTA. The card title is the link now (with a hover underline).
- **GSR Summary titles** are now navigable — each title links to the announcement detail page, styled to read as plain text with a hover underline so the printed-digest aesthetic stays intact.
- **Homepage Meetings + Events blocks** regained their mobile gutter. Desktop is unchanged — the parent page-builder container still controls width and padding there.
- **Events Magazine "More events" grid**: featured images now show above each tile's title; grid caps at 3 cards per row (drops to 2 on tablets, 1 on phones) so each tile stays wide enough to host a thumbnail.

## 1.10.1 — 2026-05-14 — Polish pass: meetings list, About tab, post / event editor flow, container gutter

Quick refinements layered on top of 1.10.0 — a release-notes pane in the About tab, the missing desktop gutter restored, several meeting-page touches, and a stack of editorial-flow fixes for the announcements / events module.

- **Settings → About** now leads with a friendly **Release notes** pane (open by default) and tucks the dense Changelog underneath in a collapsed toggle.
- **Container padding — desktop** default flipped to `5vw` (was `0`) so every block that uses `.fe-container` carries a visible left/right gutter at all desktop widths.
- **Meetings list (Sidebar template)**: in-person and hybrid meetings show the location **name + address** at the top of the actions column.
- **Meetings list (Sidebar template)**: admin-curated **custom links** in the rail under the day filters — chevron-right for internal, external-link icon (with new-tab toggle) for external.
- **Backend meeting detail**: *View on Frontend ↗* button now appears whenever the Web Frontend module is enabled (was gated on public visibility), positioned right next to *Edit*.
- **Frontend meeting detail**: Files & Readings panel drops the file-description text under each link — just the title + arrow.
- **Homepage Meetings + Events blocks** dropped the inner `.fe-container` wrapper so their width / gutter is now controlled solely by the surrounding page-builder container — fixes the cards grid getting crushed when site-wide container padding adds on top of the parent's own gutter.
- **Announcements & Events admin**: every row + the post-edit page now have a **Duplicate** button — clones the post into a fresh Draft (title gets a "(copy)" suffix) so you can spin up next month's announcement / event using last month's fields as the seed.
- **Post slug auto-derives from the title when the title changes** on save (with `-2`/`-3`/… suffixes on collision). The slug input still wins when the title is unchanged, so you can rename the URL without touching the title.
- **Live title → slug preview**: typing in the Title field on the post-edit page now rewrites the URL field as you type, with a brief brand-tinted highlight so you can see the URL changing alongside the title.
- **Draft → publish stamps "Posted on" with the current time**: the first time a draft actually goes live, "Published on …" resets to "now" — no more relying on whatever back-date the admin keyed in earlier.
- **Publish + Move-to-Drafts on the post-edit page now save your in-progress edits**. Previously they only flipped the draft state and lost any unsaved changes — you'd have to click Save first, then Publish.
- **Drafts no longer pollute the URL-redirect history**: renaming a draft (or a pending submission) doesn't add a row to `EntitySlugHistory`. Only published posts log a redirect when their URL changes.
- **Auto-stamped post / story published-on times now honour the site timezone**. Previously the auto-stamp wrote UTC and the display rendered it as if local, so a draft published at 5 PM in California would show as 12 AM the next day. Re-save any affected posts (or click Publish again) to refresh the stored value.
- **Frontend export bundle no longer carries Posts** (announcements + events) — those are per-deployment editorial content, not look-and-feel. Pages, stories, navigation, layouts, fonts, icons, design tokens, and media still ride along as before.
- **Homepage side padding survives a frontend export round-trip**. The import path was silently rewriting any page integer column set to `0` (e.g. `full_padding_pct: 0` on a full-bleed page) back to the model's default — so the homepage's gutter reset to 4 % every time. All integer columns on Page now round-trip verbatim.
- **Meeting detail page: description prose caps at 75 % column width above 1024 px** for comfortable line length on wide monitors; tablets / landscape phones / split-screen (≤1024 px) still get the full width. Applied across all four detail templates (Classic, Minimal, Card Stack, Magazine).
- **Event website URL field accepts relative paths** (e.g. `/about-us`) so admins can point an event at a page on the same site without needing the full domain. Full URLs still work; the mobile URL keyboard still comes up.
- **Announcements + Events list pages sort by post date** — newest published at the top, descending. Applies to the Cards view, the GSR Summary view, and the events list. The homepage Upcoming Events block keeps its chronological "next event first" ordering.
- **GSR Summary subheading trimmed** to "Fellowship news, in brief."

## 1.10.0 — 2026-05-14 — Design tokens overhaul + hero button picker chrome

The deepest pass on the design tokens system to date — buttons and cards each split into two-column admin views with live previews above each column, and the hero block's button editor finally gets the same icon picker + colour cluster the rest of the admin uses.

- New **Surface — Darkmode** token controls the dark-mode page background site-wide.
- New per-button border / hover-border / hover-background tokens (8 colours + widths) for both Primary and Secondary styles, with live previews that repaint as you edit.
- New per-card hover-border tokens (Primary + Secondary) — the feature-card accent on hover is now admin-tunable.
- New Container padding tokens (desktop + mobile) — restored the lost 5% mobile gutter site-wide.
- Frontend Features block: each card now gets an inline button (Primary or Secondary, with editable label) instead of the whole card being a link, plus an optional section-level CTA.
- Hero modal button rows: icon picker for the before/after icons, full design-token colour clusters for every colour field.
- Custom links in the meetings sidebar: add internal or external links below the day filters with chevron / external-link icons + open-in-new-tab toggle.

## 1.9.1 — May 2026 — Frontend bundle is now a verbatim copy

Fixes two gaps in the frontend export/import where pages were silently reverting to model defaults on restore. Per-page spacing settings and the homepage designation now ride along correctly.

## 1.9.0 — May 2026 — Homepage is a Page now

The legacy homepage admin is retired. The public `/` root is now driven by whichever Page row you designate as the homepage, with the same page-builder editor you use for every other content page.

- Pick any Page as the homepage from the Pages list — one click flips the designation and publishes.
- Hero block edit modal gains dark-mode controls for the heading gradient and subheading colour.
- Container blocks: per-side border widths, hover border width, variable-driven hover effects.
- New per-page Features and FAQ blocks (verbatim copies of the homepage editors).
- New per-page Meetings list and Upcoming Events blocks.

## 1.8.6 – 1.8.8 — May 2026 — Library import wizard, frontend export coverage, public submission form

Frontend export bundle expanded to cover the full content surface (custom layouts, fonts, icons, hero buttons, media, every frontend SiteSetting). Library import wizard streamlines bringing existing material into a new install. Visitors can submit events and announcements at `/submissionform` for admin review.

## 1.8.5 — May 2026 — Cross-instance cookie isolation

Two TSP instances on the same hostname no longer step on each other's CSRF cookies, fixing a logout-loop scenario when running multiple deployments behind one domain.

## 1.8.4 — April 2026 — Literature Library, Printlist, Hyperlist, frontend search

Three new public surfaces and a global search modal land in one cycle.

- **/library** — public-facing Literature Library with per-item visibility toggles and admin Templates integration.
- **/printlist** + **/printlist.pdf** — branded, print-optimised meeting schedule.
- **/hyperlist** — accessibility-first plain-HTML index of every active meeting (no chrome, no JS, single small payload).
- Frontend-wide search modal — Cmd/Ctrl+K from anywhere, draggable trigger in the utility bar, extensible source registry covering meetings + events out of the box.
- Past-events archive at **/events/archive** with sidebar filter rail.

## 1.8.3 — April 2026 — Footer locations, Pro Tips, Inclusion block

Long polish cycle covering the meetings list, footer location cards, design-token expansion, and several dark-mode fixes.

- "Pro Tips" accordion at the bottom of **/meetings** with a GUI editor (icon picker on every row).
- Statement of Inclusion block for the homepage.
- Meeting Locations: split address fields, location notes, website URL, opened to frontend editors.
- Footer meeting-locations block: frosted-glass cards with first-class location features.
- Default appearance control (light / dark / follow system).
- Recovery Blue primary buttons adopt the meeting-page Zoom-button recipe by default.

## 1.8.0 – 1.8.2 — March 2026 — Meetings list, Live Meetings Bar, Utility Bar admin

The **/meetings** page becomes a three-template picker (Sidebar with day-filter rail, Directory with sticky toolbar, Week board with seven Mon→Sun columns). The Live Meetings Bar replaces the legacy Top Alert Bar, with admin grouping and mobile-aware swipe rails.

- Per-meeting Extended Content section — admin-tunable Markdown blocks below the schedule.
- Public meeting + event detail pages get an Edit shortcut for logged-in editors.
- Click-to-copy chips with a green "Copied!" tooltip.
- Settings → Timezone tab for explicit site-wide timezone control.
- Footer "Powered by Trusted Servants Pro" pill block.

## 1.7.0 – 1.7.17 — February 2026 — Announcements & Events, Design tokens, custom fonts/icons

The Announcements & Events module ships alongside a site-wide Design tokens system, custom font and icon libraries, daily SQLite snapshots, and reusable detail-page Templates.

- New **Upcoming Events** block on the homepage and a dedicated **/events** listing.
- Site-wide Design tokens — Brand, Accent, Surface, Text, Card, Buttons, Links — flow into every region of the public site.
- Recovery Blue theme rename + per-template appearance overrides.
- Custom fonts and custom icons libraries — upload your own and pick them from the same dropdowns as built-ins.
- Customizable public 404 + playful admin 404 page.
- Two-panel split block for side-by-side homepage sections with per-side padding.
- Per-module role permissions and the new Frontend editor role.
- Frontend favicon, OG fields, and meta-tag split (separate from the admin chrome).
- Daily SQLite snapshots saved to `/data/snapshots` with retention.

## 1.6.0 – 1.6.2 — January 2026 — Web Frontend module

The **Web Frontend** module lands — a swappable public marketing site driven by registry-defined templates, with mega menus, alert bars, full nav editor, and a module gate that splits enabled-vs-publicly-visible.

- Swappable templates per region (header, footer, homepage, meeting detail, etc.).
- Full navigation editor with mega menus, search, and admin-only preview banner.
- Frontend bundle import/export for portable site copies.
- Public-asset blueprint and pasted-font pipeline.
- Settings modal "Web Frontend" pane with refresh-on-save hook.
- Update-available banner notices same-version redeploys (image content hash).

## 1.4.0 — December 2025 — File Browser picker rebuild

The File Browser picker is rebuilt with sort + direction controls, preview-before-select, and URL-state preservation so deep-linked picker views survive a refresh.

## 1.3.7 – 1.3.13 — November 2025 — Security hardening + library authoring + lockouts

A long stretch of security hardening (CSRF, secure cookies, XSS, brute-force protection) lands alongside library reading authoring, per-username login lockouts, and an Access Requests redesign.

- CSRF protection, secure cookies, security headers, login brute-force protection.
- Library reading authoring — paste content as an alternative to file upload, with a Markdown editor + paper-styled lightbox.
- On-the-fly PDF download for any pasted reading.
- Per-username login lockout with a DB-backed state and admin-visible chips.
- Access Requests widget redesign + Customize Dashboard toggle.
- Mobile sidebar footer always visible; create user from an access request in one click.

## 1.3.0 – 1.3.6 — October 2025 — AGPLv3, drag-and-drop dashboard, OG previews

The project goes open source under AGPLv3. The dashboard becomes drag-and-drop with per-user widget customisation. Open Graph link previews ship for every share-worthy URL. Server Stats and Server Metrics widgets land for editors and admins.

- Open-source under AGPLv3 with attribution credit on the About page.
- Drag-and-drop dashboard with per-user customisation.
- Universal SVG icons + light mode default on fresh installs.
- Server Stats card with Online Now tile + per-role visibility.
- First-run setup wizard for fresh installs.
- Guided tour for viewers and editors.
- File Browser lightbox for previewing images and PDFs in place.
- Legacy WordPress redirects honoured automatically.

## 1.2 — September 2025 — Rebrand to Trusted Servants Pro

Project renamed from the early working title to Trusted Servants Pro. Third-party branding unbundled; sidebar logo now appears on the login screen.

## 1.1 — September 2025 — Login bot protection + unattended installer

Cloudflare Turnstile gates the login and access-request forms. The installer ships an unattended mode for one-line VPS deploys. HTTP cache headers tightened on auth-sensitive routes.

## 1.0 — August 2025 — First public release

The first public release — a complete portal for fellowship trusted servants covering meetings, libraries, file storage, accounts, Zoom credentials, intergroup info, and tech training.

- Meetings, Libraries & Readings, File Browser, Copy Link buttons.
- Roles & Access (admin / editor / viewer), Request Access flow.
- Zoom Accounts (encrypted credential storage) + Zoom Tech Training playbook.
- Themes (light, dark, neobrutal, cyberpunk, solarpunk) with a 3D login transition.
- Email / SMTP, data export / import, configurable session length.
- Responsive design from day one — every view ships dedicated mobile layouts.
