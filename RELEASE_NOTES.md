# Release Notes

User-friendly, scannable summary of every Trusted Servants Pro version
bump. The deeper, version-by-version implementation log lives in
[CHANGELOG.md](CHANGELOG.md).

The same content appears in-app under **Settings → About** with the
release notes expanded by default and the changelog collapsed.

## 2.1.10 — 2026-05-18 (latest) — Bundle encryption, Frontend overview, edit-in-place backups, card shadow colour

A grab-bag release focused on making the admin surface easier to live in and locking down the things that travel off-machine.

### Encrypt your full-portal export with a passphrase

The **Settings → Data → Export** card now offers an optional encryption passphrase. Leave it blank for a plain ``.zip`` like before; type one and the download becomes ``tsp-export-…-zip.enc`` — AES-256-GCM ciphertext that only your passphrase can decrypt. The Import side has a matching field and auto-detects encrypted bundles, so a destination install just needs the same passphrase to restore.

Don't want to invent a passphrase? Click **Generate strong passphrase** — the browser produces a 24-character one in the format ``Xk9p-Mw2N-jVqL-3Hbt-uR5z-PnAc``, drawn from an alphabet that excludes the visually-ambiguous ``I l O 0 1`` so it can be transcribed from a printed page without second-guessing. A yellow banner reminds you to save it (no recovery exists), and inline **Show** / **Copy** buttons keep the field usable.

Why bother? When the bundle travels through Cloudflare or any other reverse proxy, the edge sees plaintext during the upload. Encrypting client-side hands the edge ciphertext instead.

### Web Frontend Overview tab is now a customisable widget grid

The Overview tab at **/tspro/frontend/** used to be two toggles + a "Pick a section on the left" placeholder. It's now a draggable grid of widgets that mirrors the home dashboard:

- **Status** — the existing public on/off and sidebar auto-hide toggles, kept as a widget so they can be hidden or reordered.
- **Visitor metrics** — the full five-tile traffic overview (Views / Unique visitors / Today / Yesterday / Last 7 days) lifted from the Visitor Metrics page so you don't have to click into a second page to see the numbers.
- **Pages**, **Redirects**, **Navigation**, **Forms**, **Branding & theme**, **Header & Footer** — section-specific cards with counts and one-click access.

Drag any widget to reorder it; preferences are saved per-user. Click **Customize** in the top actions to hide widgets you don't care about. Same recipe as the home dashboard — same drag-handle, same Customize modal, same persistence.

### Edit an off-site backup target without removing + recreating

Off-site backup targets used to be create-only — once a target was through the setup wizard, the only way to change credentials, schedule, or encryption was to remove it (which loses the run history) and add a new one from scratch. Each row on **Settings → Off-site Backups** now has an **Edit** button that opens a single page with connection / schedule / encryption all in one form. One Save button, one round-trip, and the next scheduler tick picks up your new cron immediately. The backend kind (FTP / SFTP / Dropbox) stays read-only — switching backends mid-life would orphan the existing remote archives.

### Custom shadow colour for primary and secondary cards (light + dark mode)

Two new colour pickers per card style on **Web Frontend → Design**: a shadow colour for light mode and one for dark mode. Pick a brand-tinted glow for hero cards, warm amber on feature cards, or a cool cyan that only shows in dark mode. The size (shadow scale) still drives the offset and blur; the colour just supplies the tint, with alpha preserved from the scale so a saturated brand colour still reads as a soft glow rather than an opaque block. Defaults match the historic charcoal in every theme — existing installs render byte-identical until you opt in.

## 2.1.9 — 2026-05-18 — Restore bundles work behind Cloudflare's 100 MB upload cap

Restoring a full-portal bundle now works even when your app sits behind Cloudflare (Free plan caps proxied uploads at 100 MB) or another tight-upload proxy. No config change, no operator workaround — pick the file, type **REPLACE**, watch the progress bar.

### What you'll see

The **Settings → Data → Import** form now opens with a one-line note explaining the chunking behaviour. After you click **Import & Replace All Data**:

- A progress overlay appears immediately with a brand-coloured bar.
- The sub-line counts chunks as they upload: *"Uploading bundle… — Chunk 3 of 12 — 270 MB of 1.2 GB"*.
- Once the final chunk lands, the overlay flips to *"Reassembling and restoring…"* with the spinner while the server stitches the pieces back together and runs the restore.
- On success you're signed out (same as before) and land on the login page with your restored data.

### How it works (you don't need to do anything)

The browser slices the bundle into ~90 MB pieces (under Cloudflare's 100 MB cap with envelope room) and uploads them as separate POSTs to a new chunk endpoint. A finalize call then assembles them on disk and runs the existing import flow. If your browser somehow can't slice files (very old versions), the form falls back to a single direct POST — same behaviour as before.

If you close the tab mid-upload, the partial chunks auto-clean themselves up on the server after 24 hours so nothing accumulates.

## 2.1.8 — 2026-05-18 — Restore reliability: images load correctly right after a restore

Fixed an intermittent "some images load on this reload, others don't" problem that could appear right after restoring a bundle on a multi-worker deployment. The server now gracefully recycles its workers after the import so every worker reads from the restored database — no more flaky-images / occasional 404s while you're verifying the import.

You shouldn't notice anything other than the restored portal "just working" immediately after sign-in.

## 2.1.7 — 2026-05-18 — Restore safety: Turnstile auto-disables when the host changes

Cloudflare Turnstile sitekeys are bound to the domain you registered them under. Restoring a prod bundle (with Turnstile enabled) onto a different host — a local dev VM, a staging machine, anything — would otherwise lock you out at login: the widget can't issue a valid token for the new domain, so every sign-in attempt fails the security check before the password is even checked.

The Import now detects this and:

- **Auto-disables Turnstile** on the destination when the source's host doesn't match where you imported (and flashes a clear warning naming both hosts so you know why).
- **Keeps your sitekey and secret** on the row — once you've verified the sitekey is valid for the new domain, one toggle in **Settings → Security** turns Turnstile back on.
- **Clears any login lockouts** the importer admin may have racked up bouncing off Turnstile, so you can sign back in cleanly.

If you're restoring back to the same host (disaster-recovery scenario), Turnstile stays on.

## 2.1.6 — 2026-05-17 — Bundle restore upload reliability + meeting-modal post-save refresh

A trio of polish fixes around the Data tab and the meeting edit modal.

### Full-portal Import: bigger upload ceiling + a friendly error when you hit it

The Import form was silently failing on prod bundles bigger than 256 MB — the server returned a tiny error response that the browser rendered as a blank page, and back-button left you with no data imported and no flash explaining what happened. Two fixes:

- The default upload cap is now **4 GiB** (configurable via `TSP_MAX_UPLOAD_MB` if you need it tighter). Whole-portal bundles with non-trivial uploads dirs go through cleanly without surprises.
- If you ever do exceed the cap, the page no longer goes blank — a clear red flash names the limit and points at the env var, and the form is right there waiting when you back-button.

### A spinner during the upload so you know it's working

Multi-hundred-MB bundles can take tens of seconds to upload before the server even starts the restore. The Import button now flips to **"Restoring…"** and a full-viewport overlay with a spinner appears immediately on click, so you don't sit staring at a hung page wondering if you double-clicked.

### Meeting edit modal: page behind refreshes after a save

Saving an edit from the meeting modal updates the database but didn't refresh the page behind it — the title, description, schedule etc. underneath kept showing the old values until you reloaded. Now, when you close the modal after a successful save (Cancel, X, Esc, or backdrop click), the page automatically reloads to show your edits. Saving twice before closing still results in one reload, not two.

## 2.1.5 — 2026-05-17 — Email-list audience controls + Web Frontend sidebar auto-hide

A few focused additions to the Trusted Servants module and the Web Frontend admin.

### Audience controls when sending an email-list update

The Send-an-update page now leads with an **Audience** card. Two modes:

- **Full list** *(the new default)* — sends to every subscriber + every intergroup member + every app user (editor / viewer accounts). A summary line under the radio shows the count in each group so you know the spread before sending. Duplicate emails across groups only get one copy.
- **Granular** — pick exactly which groups, and inside the subscribers group, pick exactly which subscribers via a scrollable checkbox list with Select all / Clear shortcuts. A live count under the Granular radio updates as you tick / untick, including the per-group breakdown and the total.

Either way, the message is sent one SMTP send per recipient with `{name}` personalization, and duplicates across groups are merged so nobody gets two copies.

### Web Frontend admin: auto-hide the app sidebar

When you're inside the Web Frontend admin pages, the main left-edge app sidebar now collapses to a hamburger button so the content area can use the full viewport width. Tap the menu icon (top-left) to slide the sidebar in when needed; tap outside or pick a link and it slides back out. The Web Frontend has its own sub-nav so two sidebars side-by-side ate into editing canvas space on laptops. A toggle on the **Web Frontend → Overview** card lets you flip the auto-hide off if you'd rather keep both visible.

Smarter sidebar behaviour: when you click a sidebar link that leaves the Web Frontend (e.g., Meetings, Settings), the sidebar **stays visible through the navigation** instead of sliding away and then re-appearing on the next page — that flash was distracting.

### Name field on user accounts

Every user account now has an optional **Name** field (e.g. "Jane D."), separate from the login username. It's editable from **Settings → Users** in both the Create form and the per-row Edit modal, and it shows up in the users table. The email-list blast uses it for `{name}` personalization when the recipient comes from the intergroup-members or app-users group, so the friendly name lands in their inbox even if they've never added themselves to the Trusted Servants list.

### Minor polish

- The email-list cards (the roster + the send-update pages) lost their right border and brand-blue left accent — the shadow + top/bottom hairlines define the cards without the redundant verticals against the page gutter on these wide-table pages. Other Settings cards keep the brand-blue accent.
- Page heading on /email-list reads "Trusted Servants Email List" (the full module name) instead of just "Email List"; sidebar link stays as the shorter "Email List".

## 2.1.4 — 2026-05-17 — Trusted Servants widget stays put

Small follow-up to 2.1.3. The **Join the Trusted Servants list** widget on the dashboard no longer disappears once you've joined — it stays visible whenever the module is on and the dashboard toggle is checked. Once you're on the list, the widget switches to **Your Trusted Servants info**: name / email / phone are pre-filled with the values admins actually see on the roster, the button reads **Save changes** instead of Join, and a discreet **Remove me from the list** action appears below a thin divider for when you want to come off entirely.

Why: a few users mentioned they wanted to see and tweak their listed contact info from the dashboard without digging through any admin surface. The previous self-retiring widget hid this option behind "you can't get back to it." Now the widget is the canonical edit point for your own row.

## 2.1.3 — 2026-05-17 — Trusted Servants Email List, Watchtower quicknav, dashboard widget refresh

Three substantial changes in one release.

### New: Trusted Servants Email List module

A complete contact roster + mass-email surface for fellowship-business updates, available at the new public URL **/email-list** once an admin turns it on in **Settings → Modules → Trusted Servants Email List**.

- **Dashboard widget**: every signed-in user (admin or not) sees a "Join the Trusted Servants list" widget on their dashboard until they've submitted their info. Name pre-fills from username, email + phone pre-fill from the user's account. Click join — the widget self-retires until they want to update their entry.
- **Admin manage page** at /email-list: full subscriber table with per-row edit / delete, **Add manually** modal for adding external contacts who don't have portal accounts, **Import CSV** wizard (see below), **Send an update** button.
- **Send-an-update flow**: type a subject, write a Markdown body. Use `{name}` in either to personalize per recipient. Submit fires one SMTP message per recipient (no BCC pile-ups), records what was sent, surfaces sent / failed counts in the history card at the bottom of the manage page. Spinner overlay while it runs.
- **CSV import wizard** (multi-step modal): upload a spreadsheet, the importer auto-detects which columns are name / email / phone, you review the mapping + a dry-run preview of what will be added (and why anything is being skipped — duplicates, missing fields, blank rows), then commit. Columns you don't care about are ignored automatically. Encoding + delimiter are auto-detected; the same CSV from Excel, Google Sheets, or Numbers all work without futzing.

### Watchtower button on the sidebar, with notification chips

The Watchtower link moved out of the Admin section into its own pinned button above the sidebar search bar (under the Web Frontend pair). The button uses a shield icon and carries up to two **attention chips** so you can see what needs eyes without opening the page:

- An **amber chip** for pending access requests
- A **brand-blue chip** for currently-locked accounts

When neither count is above zero, the button is clean with no decoration. The Web Frontend pair also got a label-fit fix: previously the labels truncated to "We..." in the narrow grid cells — now they read **Web** (admin panel) and **View** (public site, new tab).

### Dashboard widgets visual refresh

Every dashboard widget now uses the icon-led card style introduced for the Settings panes — same drop shadow, same soft border, but with a **leading icon next to each widget's title** so they're easier to scan at a glance. The drag handle moved into the title row as an inline chip (it's still in the top-left, just no longer floating absolutely on top of the title — so widget titles never have to be padded to avoid it).

Specifically: Recent Meetings has a calendar icon, Libraries has a book, Recent Files has a document icon, Visitor Metrics has a bar chart, Off-site Backups has a cloud, Recent Deletions has a trash icon, Contact Form has a mail icon, the Trusted Servants sign-up has a user-plus icon, Currently Online has a users icon, Access Requests has a user-plus icon, and the Server / Your Role widget keeps its existing layout.

The brand-blue left accent that other data-cards have was deliberately left off in the dashboard context — it read as visual noise next to the masonry layout. Everywhere else (Settings panes, the backup admin modal, the email-list import wizard) the accent stays.

## 2.1.2 — 2026-05-17 — Templated submission form + primary-card alignment

The public ``/submissionform`` page (the one visitors use to submit an event or announcement for admin review) is now templated like the rest of the public site — pick from three different layouts and tune background, fonts, and sizing per layout.

### Three layouts to choose from

Open **Web Frontend → Templates → Submission form (/submissionform)** and you'll see three picker cards:

- **Classic** *(default — matches what the page looked like before this release)*. Centered single-column page with a heading, subheading, and a soft-shadowed card containing the form.
- **Minimal**. Borderless, no card. Serif heading on a thin rule, intro flows into the body, fields sit directly on the page. Maximum focus on the writing.
- **Split**. Two-column desktop layout: heading + subheading + intro stay sticky on the left as you scroll; the form card sits on the right. Collapses to one column on mobile.

Each layout shows a thumbnail of its silhouette in the picker so you can compare at a glance before saving.

### The same per-template controls every other page gets

Each layout has its own customize panel — background colour with optional dark-mode pairing, dynamic background (gradient / overlay / palette), heading font, body font, heading-size override, body-size override. Boxed vs. full width, max-width, and side-padding controls match every other templated page.

### Form card now follows your Primary-card design

The form's card now uses the **Primary card** design tokens from Site → Design → Card styles. Whatever background, border colour, border width, shadow, and hover treatment you've set for primary cards site-wide (meetings list, events, fellowships, library items, etc.) the submission form's card now matches automatically — light mode and dark mode. Pre-2.1.2 the card was hard-coded to white with a brand-blue border; that's gone.

## 2.1.1 — 2026-05-17 — Settings tabs unified, Locations + Sidebar buttons in card heads

A polish release focused entirely on Settings. Seven tabs (**Appearance, Users, Global, Domain / Email, Timezone, Security, Sidebar**) now share the same card chrome the Data tab introduced: a brand-blue accent on the left edge, a soft drop shadow, an icon next to each section title, and a clean single-column stack instead of the previous mix of two-column grids and horizontal-rule dividers. The Settings modal now reads as one consistent visual language.

### Tab-by-tab changes

- **Email** renamed to **Domain / Email**. The **Public Domain** section moved here from Appearance, and the Access Request Notifications recipient field tucked into the SMTP card as one combined save — one fewer button to remember to click.
- **Global** (Locations / Officers / Fellowships): the "+ New Location" button moved into the Locations card's title bar so it's always visible at the top, no longer a separate floating action above the card.
- **Sidebar**: the "Save sidebar order" button now sits in the card's title bar too — you don't have to scroll past the long manual-reorder list to find it.
- **Users**: Create User and Roles & permissions stay side-by-side inside a single "Add a user" card so the permissions reference reads as guidance for picking the right role on the form. The full users table and the Public Information Chair section each get their own card below.
- **Timezone**, **Security**: each section is now a self-contained card. The two-column "OTP Email / Bot Protection" grid on Security is gone — the cards stack vertically with their own visual separation instead.

### Release notes display in About tab

When you open **Settings → About → Release notes**, each subsection heading now has 2 rem of breathing room above it (so headings don't crash into the prose of the previous section), and the paragraphs under each heading render as **brand-color bulleted list items**. Intro paragraphs at the top of each entry (like this one) stay as flowing prose — only the body paragraphs inside subsections get bulleted. Easier to scan when skimming "what changed" between versions.

### Other polish

- **Locations "+" button** is now full size and the "+" inside it shows up in white instead of being painted brand-blue (the same blue as the button background, which made it disappear).

## 2.1.0 — 2026-05-17 — Automated off-site backups + Appearance tab refactor

Big release. Three things landed together: a complete off-site backup system, a new dashboard widget to keep an eye on it, and a visual refresh for the Appearance tab in Settings.

### Automated off-site backups (FTP, SFTP, Dropbox)

The daily SQLite snapshot we've always taken locally is good for accidents — accidental deletes, broken migrations — but it lives on the same disk as the app. A real disaster (drive dies, VM is wiped) takes the snapshots with it. **Off-site backups solve that.**

Open **Settings → Data → Off-site backups → Set up off-site backup →** to walk through the 5-step setup wizard:

1. **Destination** — pick FTP, FTPS, SFTP (SSH), or Dropbox.
2. **Connect** — enter credentials. A "Test connection" button round-trips a tiny sentinel file so you find out the credentials work before leaving the wizard.
3. **Schedule** — pick a preset (Daily at 03:00 UTC, Weekly Sunday, Hourly, Monthly) or write a custom cron expression. Also pick how many old archives to keep on the remote.
4. **Encryption (optional)** — turn on archive encryption to wrap every backup in a passphrase before it's uploaded. Even if your Dropbox token leaks or your FTP host is compromised, the archives stay sealed. **There's no recovery for a lost passphrase** — the wizard makes you tick a box confirming you've saved it before proceeding.
5. **Review** — last chance to look it over, then optionally run a first backup right now so you can confirm it works end-to-end.

Each backup archive is a complete app snapshot — the SQLite database, every uploaded file, and the encryption key for stored credentials — exactly the same `.zip` the existing **Settings → Data → Export data** button produces. Restore is symmetric: download an archive from the remote, then import it via the existing **Settings → Data → Import data** flow.

You can configure **multiple targets** — e.g. an FTP daily and a Dropbox weekly — and each runs independently with its own schedule, retention, and encryption setting. A built-in scheduler thread checks once a minute for due jobs, runs them, and emails admins via your configured SMTP host if a backup that was previously working starts to fail. The "Manage backups" modal shows status, run history, and a "Run now" button for any target, and the new dashboard widget surfaces health at a glance.

### New "Off-site Backups" dashboard widget

Admins get a new draggable widget on the main dashboard. Four stat tiles up top show Healthy / Failing / Paused / Total target counts; the Failing tile turns red whenever something's broken and a warn badge appears in the widget title. Below that: when the last successful backup ran (and which target wrote it), when the next scheduled run is due, and the four most-recent backup attempts with their pass/fail pills. The entire widget is clickable — opens the "Manage backups" modal directly. Toggle it on/off from the dashboard's **Customize** button.

### Appearance tab in Settings — visual refresh

The Appearance tab in Settings has been redesigned to match the card style we use in the Data tab — every section (Theme, Sidebar Footer Logo, Login Screen, Open Graph link previews, Home Screen Icon, Public Domain) is now its own card with a brand-blue accent on the left, an icon next to the title, and a clean drop shadow. The two-column layout is gone; cards stack vertically so each one has room to breathe on every screen size. Nothing changed about what the settings do, only how they're laid out.

### Smaller polish

- **No more cloud-icon flash** when opening the backups modal or any iframe-based settings panel — inline SVG icons now carry intrinsic dimensions, so they render at the right size from the very first frame instead of briefly stretching to fill the container.
- **Busy spinner** while a backup is being taken — the "Run now" button on the Manage modal and the "Enable target" button at the end of the wizard now show a clear "Backing up…" overlay until the upload finishes, so you can't accidentally double-click.
- **Modals stack instead of replace** — opening the Manage backups modal no longer closes the Settings modal underneath it; same for the wizard. You can dismiss whichever you're done with and the one below is still where you left it.

## 2.0.4 — 2026-05-17 — Dashboard widgets: every widget has a visible grab handle, no more awkward gaps

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
