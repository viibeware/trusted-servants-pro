# Release Notes

User-friendly, scannable summary of every Trusted Servants Pro version
bump. The deeper, version-by-version implementation log lives in
[CHANGELOG.md](CHANGELOG.md).

The same content appears in-app under **Settings → About** with the
release notes expanded by default and the changelog collapsed.

## 1.10.5 — 2026-05-15 (latest) — Blog overhaul: visual block editor, redesigned editor sidebar, classic detail polish

A sweeping refresh of the blog module — the markdown textarea is gone, replaced by a delightful visual editor; the edit page got a metadata sidebar; the classic public template adopts the design-token primary card look; and a few admin-set knobs that quietly weren't responding (template background, mesh randomize, comments) are fixed or retired.

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
