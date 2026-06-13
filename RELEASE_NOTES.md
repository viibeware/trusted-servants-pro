# Release Notes

User-friendly, scannable summary of every Trusted Servants Pro version
bump. The deeper, version-by-version implementation log lives in
[CHANGELOG.md](CHANGELOG.md).

The same content appears in-app under **Settings → About** with the
release notes expanded by default and the changelog collapsed.

## 2.14.2 — 2026-06-13 (latest) — Two-factor on/off polish

- **Turning two-factor off now clearly shows it's off.** The yellow notice and the red "Turn off two-factor" button disappear the moment you switch it off under **Settings → Your Access**.
- **Admins see the change right away.** If you turn your own two-factor on or off, the **Settings → Users** list updates that account's Two-factor toggle to match.
- **Clearer wording** on the setup screen — two-factor is described as "available for your account" rather than "required," since it's optional and you can skip it.

## 2.14.1 — 2026-06-13 — Turn two-factor on for any account, with a setup wizard

- **Admins can switch two-factor on or off for any account** from **Settings → Users** — there's a new **Two-factor** toggle on each user row (and in the Edit-user dialog). New admin accounts now have it on by default.
- **Two-factor works for every role now,** not just admins.
- **A friendly setup wizard greets people at login.** When an account is set to use two-factor but hasn't set it up yet, the next sign-in walks the user through scanning the QR code and confirming a code — then shows their recovery codes. They can **Skip for now** and set it up later if they prefer.
- **Anyone can manage their own two-factor under Settings → Your Access** — turn it on, see whether setup is still required, or turn it off (confirming their password first).

## 2.14.0 — 2026-06-13 — Two-factor authentication for admins

- **You can now turn on two-factor authentication (2FA) for your admin account.** Open **Settings → Security → Set up two-factor authentication**, scan the QR code with an authenticator app, and enter the 6-digit code to confirm. It works with any standard app — **2FAS**, Google Authenticator, Aegis, 1Password, and the rest.
- **It's optional and admin-only.** Each admin chooses whether to switch it on; other roles never see this step. Once enabled, you'll be asked for a code from your app after entering your password each time you sign in.
- **Recovery codes mean you can't get locked out.** When you enable 2FA you get ten one-time recovery codes — save them somewhere safe. If you ever lose your phone, any one of them gets you in. You can regenerate a fresh set anytime (you'll confirm your password first).
- **Turning it off is protected too.** Disabling 2FA or generating new recovery codes asks for your account password first, so nobody can quietly remove the extra protection from a logged-in screen.

## 2.13.2 — 2026-06-13 — Toasts no longer cover the topbar

- **Pop-up "Saved" and error messages now appear just below the top bar** instead of on top of it, so they no longer hide the buttons in the header while you're working.

## 2.13.1 — 2026-06-12 — A full search results page and a smarter search palette

- **There's now a full search results page.** When a search turns up more than the quick palette can show, click **"See all results"** to open a dedicated page listing everything — meetings, libraries and files, announcements and events, stories, blog posts, locations, users, pages, and more. Filter to a single type with one click and sort by Relevance, Name (A–Z / Z–A), or Recently updated.
- **Filtering and sorting are instant.** Clicking a type or changing the sort updates the results in place — no full page reload, your scroll position stays put, and the browser's Back/Forward buttons work as expected.
- **The search palette remembers your last search.** Open a result and come back, and the palette still shows what you searched for, so you can jump between results without retyping. A **Clear** button wipes it (and it clears on its own when you close the window). A new **"See all results"** button is pinned to the bottom of the palette.
- **Cleaner result previews.** Search snippets no longer show stray formatting tags from descriptions — just clean, readable text.

## 2.13.0 — 2026-06-12 — A cleaner post editor and a sticky, full-width header

- **The announcement / event editor is reorganized and de-cluttered.** Fields now flow in a logical order — what the post is (type, title, URL, and when it publishes) → its content → event details → links → images — with Links moved above Images. The old separate "Publishing" card was folded into the top card, the cramped monospaced fields now use the regular Inter font, and the spacing between sections is tighter.
- **Pick a featured image and see it right away.** Choosing an image now shows the thumbnail instantly, before you save. And clicking "Remove current image" hides the thumbnail on the spot so you can see the change before saving — the removal still only takes effect when you save.
- **The "Auto-archive this announcement" control looks like one tidy setting** — a single panel with the switch and the date picker together — matching the "Online event" toggle. "Remove current image" is now a clear red pill instead of a stray checkbox.
- **The page header bar now stays pinned to the top as you scroll** on every admin page, uses the same background as the sidebar, and looks right in dark mode. It also now stretches the full width of the screen to the right edge.
- **On phones, the header's buttons are swipeable.** Instead of wrapping onto several lines, the action buttons sit in a single row you can swipe left/right.

## 2.12.6 — 2026-06-11 — Shared-account sign-ups & a cleaner Libraries widget

- **The Trusted Servants sign-up widget now works for shared accounts.** If several people share one portal login, each can add themselves to the email list: the dashboard form always starts blank, never pre-fills or "remembers" the last person, and never offers to remove anyone. Every submission creates its own new entry. Editing and removing entries stays admin-only on the Email List page.
- **The Libraries dashboard widget no longer lists Intergroup libraries.** It now shows only the regular Libraries-module entries — matching the Libraries page itself. Intergroup-flagged libraries remain in their dedicated Intergroup sidebar section.

## 2.12.5 — 2026-06-10 — Schedule posts, a smarter search, and Users/editor polish

- **Schedule announcements & events for the future.** In the post editor, set the "Posted on / schedule for" field to a future date & time and Publish — the post stays hidden from the public site until then, then appears automatically. The admin list flags it with a teal "Scheduled · <date>" badge, and there's a one-click "Today" button on the date fields.
- **Exhaustive backend search.** Search now finds every post type and state (announcements, events — including drafts, archived, and pending), plus Stories, Blog posts, and page-builder Pages. It also jumps to sections: type "data" or "security" to open that Settings tab, or "branding"/"navigation" to open the matching Web Frontend page — all role-gated so people only see what they're allowed to.
- **Users tab: filter, sort, and multi-delete.** Type to filter the user list by name/username/email/phone/role, click any column header to sort, and use the new checkboxes to delete several users at once (you can never select yourself).
- **Set a custom URL while a post is still a draft.** A hand-picked URL now sticks through editing and publishing, so a draft goes live at the right address with no after-the-fact rename or redirect.
- **Download a rollback snapshot from Settings too.** The "Rollback snapshots" button now also lives on the Settings → Data staging-sync card (with the matching card icon), not just the Web Frontend overview.
- **Dashboard is now a button.** The sidebar Dashboard link moved into the fixed button cluster at the top, styled like the Notifications and Watchtower buttons.
- **No more sideways scrolling on the post editor on phones.** Long links and fields no longer overflow the screen.

## 2.12.4 — 2026-06-09 — Download a rollback snapshot to undo a sync

- **The Staging Sync card now has a "Rollback snapshots" button.** Every sync automatically saves a complete rollback bundle of your frontend (including recovery Stories) before it overwrites anything — this opens a popup listing those bundles, newest first, with the date, size, and a one-click **Download** for each.
- **Built-in restore instructions.** The popup explains exactly how to put a snapshot back: download the `.zip`, then go to **Settings → Data → Frontend bundle → Import frontend** and import it. The 10 most recent snapshots are kept automatically.

## 2.12.3 — 2026-06-09 — Pull/Push your Live site right from the Web Frontend overview

- **On your Staging copy, the Web Frontend overview now has Pull and Push buttons built into its Status card.** Once staging sync is set up, you can bring your Live site's frontend down to keep working on it, or send your changes up to Live, in one click — with a live "Connected / Unreachable" check and a last-pulled/pushed timestamp — without ever opening Settings. Each direction asks for a quick second-click confirmation before it overwrites anything.
- **It only appears on the Staging copy, never on the Live site** — the Live install is the receiver, so there's nothing for it to push or pull.

## 2.12.2 — 2026-06-09 — Staging sync asks which site is Live vs Staging

- **The wizard now starts by asking which install this is — your Live site or your Staging copy — and shows only the fields that side needs.** Pick *“This is my Live site”* and it just creates the shared token for you to copy; pick *“This is my Staging copy”* and it asks for the token, your Live site's address, then a connection test and the Pull/Push controls. No more guessing which boxes to fill on which install.
- **You're guided to set up the Live site first.** Choosing Staging reminds you to run the wizard on your Live site first and copy the token it generates — so the two installs always end up paired correctly, in the right order.
- **The whole setup now happens without the Settings window ever closing.** Generating the token, saving, testing, and syncing all complete in place — no page reloads, no being bounced out of Settings mid-step.
- **Where to find it:** **Settings → Data → Frontend staging sync.**

## 2.12.1 — 2026-06-09 — A guided setup wizard for frontend staging sync

- **Setting up staging sync is now a step-by-step wizard.** The old single panel left it unclear which install you were on and which way your website would move. The new wizard walks you through it: an **Overview** that draws both sites with Push/Pull arrows, **Pair token**, **Peer address**, **Test**, and **Sync** — one step at a time, with a progress bar across the top you can click to jump around.
- **The shared token is easier to copy between the two sites.** Step 2 now shows the actual token in a box with a **Copy** button, so you can paste it into the other install at any time — not just in the one-time message when you first generate it. It also makes clear that both sites must end up with the same token, and that you can start the wizard on either one.
- **The Settings window no longer closes on you mid-setup.** Generating a token, saving, testing, or running a sync used to bounce you out of Settings and back to the page behind it. It now stays open on **Settings → Data**, right where you left off — so after you generate a token you're looking straight at it, Copy button ready.
- **Where to find it:** **Settings → Data → Frontend staging sync.**

## 2.12.0 — 2026-06-08 — Sync your website's frontend from a dev copy to your live site

- **You can now build your public website on a separate copy and push it to your live site over the network.** Run a second "staging" install to redesign the site — theme, colors, navigation and mega-menus, layouts, fonts, icons, and your page-builder Pages — then send the finished result to production with one click, instead of downloading a bundle and re-uploading it. It works both ways: **Pull** brings your live site's current frontend down to the staging copy to start from, and **Push** sends your changes back up when they're ready.
- **Only the frontend moves — nothing else.** The look-and-feel, navigation, and Pages (plus every image and file they reference) transfer. Your recovery Stories, users, meetings, libraries, and meeting uploads on the receiving site are left exactly as they were. (Stories are usually submitted or edited on the live site, so a push never touches them.)
- **Safe by default.** Before either site is overwritten, it automatically saves a complete rollback snapshot of its current frontend — if a sync isn't what you wanted, you can put it back from **Settings → Data → Frontend bundle**. Each install also has to opt in to being synced ("Allow inbound"), every request is protected by a shared secret token you set on both installs, and repeated bad attempts are rate-limited. Use an `https://` address between the two sites.
- **Where to find it:** **Settings → Data → Frontend staging sync.** Enter the other install's address, paste the same token on both, tick **Allow inbound** on whichever side should receive, then use **Test connection**, **Pull**, or **Push**.

## 2.11.1 — 2026-06-08 — Hour-of-day charts follow your portal's timezone

- **The "when do people visit" and failed-login charts now read in your timezone, not UTC.** The Web Frontend visitor metrics' **Hour of day** chart and Watchtower's **Failed logins · last 24 hours** chart used to bucket activity by UTC hour, so the busy-hour bars could sit hours off from your fellowship's actual clock. They now follow the timezone set in **Settings → Server Timezone**, and the charts are labelled with the active zone (e.g. `EDT`).

## 2.11.0 — 2026-06-07 — Recover a corrupted or locked-out portal from your backup server

- **You can now restore from your off-site backup server even when you can't get into the portal.** Until now, restoring a backup meant logging into the portal and importing it from the inside — no help at all on the day the portal's data is corrupted, or you're locked out and can't sign in. There's now an out-of-band path: from the **TS Pro Backup** server's own console (a separate machine you can still reach), pick a stored full backup, paste the site's private key, and it pushes the backup straight back into your portal, which restores itself — no portal login required. Your old data is set aside with a timestamp first, and login lockouts are cleared so you can sign back in right after.
- **It's off until you turn it on, per backup target.** Because this is a powerful recovery path, it stays disabled until you opt in. On the backup target for your TS Pro Backup server (**Settings → Off-site backups →** your target → **Edit**), tick **"Allow remote restore"** and fill in your portal's public URL. Save or test the connection and it pairs with the backup server automatically — after that, the backup server's console offers a **Remote restore** button on your full backups. Requires **TS Pro Backup 1.3.0 or later**.
- **Locked down by design.** A restore can only be applied if it arrives with both a secret token your portal shared with the backup server *and* the correct private key — the same key that already encrypts your backups. One without the other is rejected before anything is touched, so a leaked token alone can't be used to overwrite your portal. The backup server never sees your unencrypted data or your private key.

## 2.10.9 — 2026-06-05 — Live notification chips, and a more accurate "who's online"

- **The little number badges update on their own now.** The attention chips on the left sidebar (Watchtower, Notifications, and the per-section counts) and on your dashboard (Access Requests, Locked Accounts, Off-site Backups, Forms) used to only refresh when you reloaded the page. Now they update themselves every few seconds — when a new access request or form submission comes in, the count just appears and ticks up, and when you clear it, the badge disappears on its own. No more reloading to see what's waiting.
- **"Currently Online" is more accurate.** The dashboard's online count (and the live "who's online" view in the User Log) was sometimes counting people who'd actually left — a browser quietly refetching an icon in the background could keep someone showing as online, parked on a non-page address like `/site-branding/apple-touch-icon`. Now only real page views count, so the online list reflects who's actually using the portal.

## 2.10.8 — 2026-06-02 — Encrypted backups to Dropbox/FTP/SFTP now work on large portals

- **Fixed: encrypted off-site backups failing with a "server offline" error.** If you turned on archive encryption for an FTP, SFTP, or Dropbox backup, a larger portal could grind for a while and then show a "server offline" error — the encryption step was loading the whole backup into memory at once and running the server out of RAM. Encryption (and decryption on restore) now processes the backup in small pieces, so memory stays low no matter how big your portal is — a multi-gigabyte backup uses the same memory as a tiny one. Backups encrypted before this update still restore normally.
- **Fixed: a confusing "connection failed" message in the Dropbox setup wizard.** After clicking **Test connection** (which showed a green OK) and then **Continue to schedule**, you'd get a red "connection failed" error on the first click and have to click again. That's resolved — the wizard no longer re-uses the single-use Dropbox authorization code, so Continue works the first time.

## 2.10.7 — 2026-06-02 — See your disk space right on the dashboard

- **Disk space is now on your dashboard.** The Server panel on the dashboard (which already shows CPU, memory, uptime, and who's online) now includes a **Disk** tile — how full your server's disk is, with the space used and total (e.g. "92 GB / 196 GB"). It tracks the disk that holds your data, uploads, and backups. The tile turns amber when it crosses 85% full — the same point at which the low-space warning kicks in — so you can keep an eye on it at a glance without leaving the dashboard. Shown to admins only.

## 2.10.6 — 2026-06-02 — A real guarantee against a full disk, plus a heads-up before it happens

- **Your server now actively keeps its own disk tidy.** A small daily housekeeper automatically clears out old, unused Docker images and build leftovers — the stuff that quietly piled up and filled disks before. Unlike the previous auto-cleanup (which only tidied up after automatic updates), this one cleans up *everything* unused, no matter how it got left behind, so the disk stays under control on its own.
- **You'll get a warning before the disk is ever full.** When the server's disk passes 85% full, admins now see a clear **"Low disk space"** banner at the top of every admin page *and* a matching alert in the Notification Center — with how much space is left and what to do about it. That gives you plenty of runway to act before backups, uploads, or updates could fail. The warning is shown to admins only, and disappears on its own once space is freed.
- **Already running an older install?** Re-run the installer to adopt the new housekeeper (your data and settings are preserved) — see the README's **"Keeping disk usage in check"** section.

## 2.10.5 — 2026-06-02 — Keep your server from filling its own disk

- **Your server won't quietly fill its own disk anymore.** Over many months, an unattended portal could slowly use up all its disk space in two ways — automatic updates kept piling up old, unused copies of the app, and the behind-the-scenes activity logs grew without limit. Once the disk filled, things like off-site backups (and even installing updates) would start failing with "disk full" errors. New installs now automatically clean up old images after each update and keep logs trimmed, so this won't happen.
- **Already running an older install?** If your disk is filling up, you can clean it up and adopt the new safeguards without reinstalling — the README's new **"Keeping disk usage in check"** section walks you through it (a couple of `docker` cleanup commands, then re-running the installer to refresh your setup). Your data and settings are preserved.
- This release changes only the deployment setup and documentation — the app itself is unchanged from 2.10.4.

## 2.10.4 — 2026-06-02 — Fix: off-site backups failing with "disk is full"

- **Fixed: off-site backups failing with a "database or disk is full" error.** On some servers, clicking **Run Now** (or a scheduled run) on any off-site backup — TS Pro Backup, Dropbox, FTP, or SFTP — could fail with an internal server error mentioning "database or disk is full," even though the server had plenty of room. The cause was that the app built each backup in the system's small scratch area (`/tmp`) rather than next to your actual data; once a site's backup grew past what that scratch area could hold, the backup couldn't be assembled. Backups are now built on the same disk that holds your data — which always has the space — so this no longer happens. Advanced operators can point the scratch space at a dedicated disk with the new `TSP_TMP_DIR` setting.

## 2.10.3 — 2026-06-02 — Configurable page backgrounds + clearer, friendlier backups

- **Pick the background for your Contact and Recovery Contacts pages.** These two pages used to have a fixed animated background baked in. Now they use the same **Dynamic Background** picker as the rest of your site — open **Settings → Web Frontend → Templates**, find the Contact or Recovery Contacts page, and choose any pattern, colours, or texture in its **Customize** panel. They look exactly as before until you change them, so nothing moves unless you want it to. (The Join the Chat page was already adjustable this way.)
- **See at a glance what each backup is.** On **Off-site Backups → Manage**, every configured destination now wears a clear, colour-coded label — **TS Pro Backup**, **SFTP**, **FTP/FTPS**, or **Dropbox** — right next to its status, instead of a tiny grey code.
- **A cleaner, friendlier backup-connection editor.** Editing a backup destination now opens with a bold banner showing exactly what kind of connection it is, and the fields are larger and fill the width so long addresses and keys are easy to read and edit.
- **Fixed: backups that were stuck saying "Running" forever.** If the app restarted while a backup was mid-upload — for example during an update, or partway through an overnight scheduled run — that backup could keep showing "Running" even though nothing was actually happening. The app now tidies these up automatically on startup, marking the interrupted backup as failed so your status is always accurate.
- **Tidy-up:** the WordPress importer moved to the bottom of **Settings → Data**, below the everyday backup and export tools, since it's a one-time setup helper.

## 2.10.2 — 2026-06-01 — End-to-end-encrypted off-site backups + clearer Watchtower

- **A new, private off-site backup option: TS Pro Backup.** Alongside FTP/FTPS, SFTP, and Dropbox, you can now send your backups to a dedicated TS Pro Backup server — and they're **end-to-end encrypted**. Each backup is scrambled *on your portal*, using a key the backup server hands out, **before** it ever leaves; the backup server only ever holds a locked copy it can't open. You keep the matching **private key** (shown once when your site is created in the backup server's console), and it's the only thing that can unlock a backup — so even the backup host can't read your data. The setup wizard walks you through it: paste the server address and your site's API key, click **Test connection**, and it shows a short "fingerprint" of your encryption key so you can confirm it matches what the backup server displays.
- **Restoring is just as private.** On a TS Pro Backup target's **Restore** page you paste your private key to unlock and restore an archive — the key is used right there and never uploaded. And if you ever need to recover the hard way, you can download the encrypted file from the backup server and import it directly under **Settings → Import** by pasting the same private key. Your existing passphrase-based encrypted backups keep working exactly as before.
- **Fixed: "Run now" (and the wizard's first backup) no longer shows an error after a successful run.** A timing issue could make a backup that actually succeeded report a server error instead of its real result. It now reports the true outcome every time.

## 2.10.2 — Watchtower also tells you which tab needs attention

- **The Watchtower attention count now points you to the right place.** The shield button in the sidebar has long shown a little number when something needs a look — flagged Recovery Contacts requests, pending access requests, or locked-out accounts — but once you opened Watchtower it didn't say *which* section that number was about. Now each of Watchtower's tabs carries its own coloured chip (red on **Overview** for flagged Recovery Contacts, amber on **Requests** for pending access requests, blue on **Access** for locked accounts), so you can see at a glance where to go.
- **A new "Needs attention" panel at the top of the Watchtower Overview.** It lists each thing that needs you — with a short description and a count — and every row is a link that takes you straight to the section that handles it. When there's nothing outstanding it simply says "All clear."

## 2.10.1 — 2026-05-31 — Know at a glance whether your email relay is connected

- **A connection check for the API relay, right where you set it up.** Under **Settings → Domain / Email**, the API-relay option now shows a status pill — **Connected**, **Not connected**, or **Not tested** — next to a **Test connection** button. Click it after pasting in your relay's address and API key and the portal checks, *without sending an email*, that the relay is reachable and that the key is accepted — so you can confirm everything's right **before** you save. If something's off, it tells you why (a rejected key, an unreachable address, and so on). Each time you open the tab it re-checks, so the pill always reflects the live connection.
- **For the full check, update the companion relay to v0.1.1 or newer** (pull `viibeware/tspro-relay:latest`). On an older relay the portal still validates your API key — it just notes that the relay should be updated to report its own status.

## 2.10.0 — 2026-05-30 — Send email even where outbound SMTP is blocked

- **A new "API relay" sending option, alongside the existing direct-SMTP path.** Some hosts — DigitalOcean droplets are the classic example — block the outbound ports email normally uses, so the portal simply couldn't send mail there. Now it can: under **Settings → Domain / Email**, switch **Sending method** to **API relay (HTTPS)**, paste in your relay's address and API key, and the portal hands each message to a small companion service over the web, which does the actual sending. Your mail-server password lives only on the relay, never copied into the app. Prefer the old way? **Direct SMTP** is still right there and unchanged — the SMTP fields even tuck away when you're in relay mode so the screen only shows what you need. A **Send Test** button confirms whichever method you picked.
- **The companion relay is its own one-click install.** It's published separately as `viibeware/tspro-relay` and comes with its own simple sign-in dashboard where you set the mail-server details, copy the API key, watch a log of everything sent, and optionally turn on a bot challenge for its login.
- **Seamless upgrade.** Existing sites that send over SMTP keep working exactly as before — the new settings are added automatically on first start, and you only see the relay option if you go looking for it.

## 2.9.5 — 2026-05-30 — Guided Zoom launcher + automatic OTP-code retrieval

- **A step-by-step "Launch Zoom Meeting (Guided)" wizard on the meeting detail page.** New to hosting? Online and hybrid meetings now have a guided launcher (a focused, blur-the-background popup) that walks a trusted servant through opening Zoom: **(1) Sign in** — reminds you to host from a Mac/Windows/Linux computer (not a phone, tablet, or Chromebook) and shows the assigned Zoom account's login with one-click copy; **(2) Get the code** — reminds you to choose *"Verify via one-time passcode"* (not "Allow on other devices") and fetches the latest sign-in code for you (see below); **(3) Start** — a big Launch button plus the Meeting ID and passcode to copy, and a reminder to sign out of any other Zoom account in your browser first. Each step has a screenshot you can click to enlarge, and you can jump between steps with the numbered circles at the top.
- **The app can now retrieve the Zoom one-time passcode for you, automatically.** Add your OTP inbox's IMAP details once under **Settings → Security → Zoom One-Time-Passcodes (OTP)**, and a **Retrieve latest code** button appears in the wizard, on the meeting's passcode section, and on the **Zoom Accounts** page. Click it and the system keeps checking the inbox for up to 3 minutes (with a spinner) until the code arrives — it may take up to a minute for Zoom to send it. The newest code is shown with a timestamp and a **live countdown to expiry** (Zoom codes last 10 minutes from when they're sent), so you can see at a glance how long you have to enter it. Only codes from the last 10 minutes count, and if several arrive you always get the newest. (Your webmail login is still shown as a fallback.)
- **Meeting detail page tidied up.** The Zoom details now live in their own card on the right, the Schedule and Location each sit in a clean card, and the Location shows the full address with an **Open in Maps** button (it even matches a saved location through a small typo).
- **Fixed: the live-meeting badge's background poller no longer skews your visitor metrics.** The `/api/live-meeting` check the public site makes every 30 seconds was being counted as page views, padding your totals and showing up in Top Paths. It's now excluded from visitor metrics entirely — both new hits and any already-recorded ones — so your numbers reflect real visits.

## 2.9.4 — 2026-05-29 — Dynamic-background picker overhaul + mobile polish

- **The Dynamic Background picker is reorganised into Background + Options tabs with a live preview** that repaints as you change presets, overlays, colours, and pastel strength — so you can see exactly what you'll get before saving. Each preset only shows the knobs that apply to it.
- **More control over backgrounds:** per-preset sliders (dot size/spacing/rotation, line angle/thickness, etc.), a Scale + Intensity slider on every texture overlay, and real foreground/background colours for the dotted-grid and diagonal-lines patterns.
- **Retired the Starfield, Noise paper, and Spotlight glow base backgrounds** (the six texture overlays are unaffected; any surface using a retired preset falls back to its solid colour / image).
- **Mobile polish (Recovery Blue):** the header now stays fully sticky on phones, the hamburger menu slides open with a smooth animation, the swipe utility bar no longer peeks the next item at rest, and the signed-in footer auth buttons left-align and wrap cleanly.

## 2.9.3 — 2026-05-28 — Card body preview controls + "Read more" links on list templates

- **New setting on the announcements and events list templates: pick how much of each post's body shows on the card.** Web Frontend → Templates → Customize panel on either list template now has a **Card body preview** control with two modes: **Full body** (renders the entire body on each card) or **Truncated body** capped at a character count you set (50–2000, default 200). The character input is greyed out unless truncated is selected. Announcements default to full (no change for existing sites); events default to truncated 200 chars (events now show their body alongside the existing summary line, capped so cards stay compact).
- **"Read more ›" link added to every announcement and event card.** Every card in the announcements list and every card-shaped event card (Cards layout, Magazine "More events" tiles, Timeline cards) now ships with a Read more link pointing at the post's detail page. The link is shown regardless of body length or truncation setting — the title is still the primary affordance, this is the explicit secondary call-to-action. Magazine hero events keep their existing "View event" primary button; Calendar view has no cards (chips + list) so it's unchanged.

## 2.9.2 — 2026-05-28 — Pastel strength slider, themed image elevation, detail-page polish

- **Dynamic background pastel intensity is now a slider, not a toggle.** Pull the slider in the Dynamic Background picker between 0 and 100 to dial how soft your light-mode palette gets — at 0 the colours stay fully saturated, at 100 they land in true cream / blush / mint pastels. Old saves that had the checkbox on still load with full strength. The strength-100 endpoint was also rebalanced to be visibly paler than the previous all-or-nothing setting, so even a maxed slider reads as a soft wash rather than a punchy tinted block.
- **Featured images on announcement, event, and archive detail pages now elevate with a themed shadow.** A clearly visible `lg` shadow sits behind the image at rest and expands to an `xl` shadow on hover, with the shadow colour automatically following whatever you set under **Design → Card shadow colour** — change the theme tint and the image shadow retints to match. The border that used to outline the image is gone, the hover lift is dropped (the shadow alone does the work, no jumping), and the transition runs a flat 200 ms.
- **Detail-page layout reshaped for better balance.** The featured-image column on announcement / event / archive detail pages (Classic layout) is now 33 % of the page width and the body column is 66 %, with the image height following the column width instead of being pinned to a fixed pixel value. Reads cleaner on wide screens where the previous fixed-width cover used to feel cramped next to a long body.
- **Meeting detail logo bumped to 240 px on desktop** (was 180 px) across all four meeting-detail layouts (classic, card stack, magazine, minimal). Mobile keeps the existing narrower size so it still fits below 600 px wide.

## 2.9.1 — 2026-05-28 — Dynamic-background picker layering + phantom "online" users fix

- **Fixed: the Dynamic Background picker opened behind the modal that launched it** on the frontend templates page. The picker is a shared body-level dialog and was getting stacked under the template-edit modal (which is appended at runtime). The picker (along with the global media + icon pickers) now layers cleanly on top of any content modal that triggered it.
- **Fixed: users appeared "persistently online" on `/api/live-meeting`.** The utility bar polls that endpoint every 30 seconds when the live-meeting badge is enabled, and the online-users tracker was treating each poll as a real page view — pinning the user's last-seen location to `/api/live-meeting` forever. Background polls on any `/api/*` endpoint are now skipped, so the Currently Online widget reflects actual navigation again. After deploying, lingering phantom-online users should drop off within your usual idle cutoff.

## 2.9.0 — 2026-05-28 — Page drafts, edit history, and a live-updating preview

- **Save pages as drafts without publishing.** Already-published pages can now stash in-progress edits in a draft slot without touching the live page. The yellow save bar in the page editor now has two buttons — **Save Draft** and **Publish** — so it's always clear what's about to happen, and an amber banner appears at the top whenever you're editing draft content. When a draft is loaded, a top-of-screen **Publish draft** button lets you push it live without having to make a fake edit first to expose the save bar. The pages list shows an "Unpublished changes" chip on any row that has a stashed draft.
- **Full edit history with one-click rollback.** Every Save Draft and Publish is recorded — up to the last 50 entries per page. A new **History** button on the page editor opens a chronological list (newest first) with Draft / Published chips, timestamps, and the author of each save. Clicking **Restore** loads any past revision back into a draft for review; your live page stays unchanged until you click Publish, so rollbacks are always safe to preview before committing.
- **Live preview that actually updates as you type.** The Preview window on the page editor now updates itself silently as you keep editing — no new popup, no focus stealing, no flicker. Open Preview once and keep editing; the preview tab quietly re-renders in place every ~700ms (with scroll position preserved across each update) so you can watch your changes flow through in near real time.
- **Fixed: two-column containers used to scramble blocks across columns on save.** A common report — putting two blocks in the left column and three in the right of a two-column container, hitting Save, and watching the last right-column block jump to the left — is gone. Columns now save exactly the way you arranged them in the editor, even when the two sides have different numbers of blocks.
- **Unplaced blocks bin is readable again.** Block pills parked in the Unplaced bin on the page builder now have proper cards with their own background, icon, and a clear gap between them, so the bin reads as a stack of distinct items instead of a wall of text.
- **Polish.** Status chips on the Pages list no longer collide when a row has both a visibility chip and an "Unpublished changes" chip — they wrap with breathing room. The Save Draft button in the yellow save bar now uses the same brown as the Publish button for its text and outline, so the two read as a matched pair.

## 2.8.3 — 2026-05-28 — Live-update content-page preview + markdown lists + SVG image scaling

- **Content-page Preview now updates live.** Open the preview tab once and keep editing — the preview reloads automatically (debounced) every time you change a block, no need to keep clicking Preview. The preview window remembers your scroll position across reloads so you stay in the spot you were inspecting. Nothing gets saved to the live page until you hit Save — the preview is purely a render of your current, in-progress edits.
- **Markdown lists in announcement and meeting bodies render properly.** Typing `intro line` ⏎ `- item` directly under a paragraph now renders as a real bulleted list on the public site (announcement detail pages, event detail pages, and all four meeting-detail templates). Previously you had to remember to leave a blank line before the `-` for the list to render; the field now handles that for you.
- **SVG image blocks now respect the width setting.** An SVG dropped into an image block was sometimes capping at its source file's intrinsic size instead of scaling up to the chosen width — particularly inside flex containers with centered alignment. SVGs now scale up to fill the percentage you picked (50%, 80%, 100%, etc.) regardless of the source file's pixel dimensions, while raster images keep their existing "don't upscale past natural size" behaviour.
- **Unplaced blocks bin reads more cleanly.** Pills in the Unplaced bin on the page builder now stack vertically with the same tint and spacing as placed blocks, instead of wrapping into a horizontal row with a different background — easier to scan and to drag back into the active layout.

## 2.8.2 — 2026-05-26 — Visitor metrics export + timezone fix for events

- **Export visitor metrics to CSV.** A new **Export CSV** button on **Watchtower → Visitors** downloads everything in the current window — daily traffic, top paths, top referrers, devices/browsers/OS breakdowns — in one spreadsheet-friendly file. The export respects whichever **Unique visitors / Hits** mode you have selected so the numbers match what's on the page.
- **Tooltips and chart polish on Watchtower → Visitors.** Hovering any bar in the daily-traffic chart now shows the exact count and date in a small tooltip. The legend on the chart is back to the right side, the Devices/Browsers/Operating systems donut grid lines up cleanly on every screen width, and hover states on the donut slices show the full breakdown.
- **Fixed: events were sometimes auto-archiving on the wrong day.** The "cut off past events" sweep was using server-clock UTC instead of your fellowship's configured timezone, so an event ending at, say, 9 pm Pacific would either disappear early (UTC was already on the next day) or hang around in the live list past midnight local. The sweep now compares against site-local time, so events drop off at midnight in your timezone — same as you'd expect.

## 2.8.1 — 2026-05-26 — See who's hitting 404s and block them in one click

- **The 404s tab now shows who's actually hitting each dead URL.** Every row in **Top missing URLs** has a small "route" icon that opens an inline panel listing the IP addresses hitting that URL, how many times each, and when they last tried. The **Recent 404s** table got a **Source IP** column too.
- **One-click block.** Beside each IP — both in the inline panel and in the Recent 404s table — there's a **Block** button that adds the IP to your Watchtower blocklist permanently. The ban reason auto-fills with the 404 path so it's obvious in the log later why you blocked them. Already-blocked IPs show a red "Blocked" chip instead of the button.
- New 404s capture the IP automatically — older entries (from before this update) show "—" in the IP column.

## 2.8.0 — 2026-05-26 — Cookie Compliance + unified Watchtower visitor metrics

- **New: Cookie Compliance module** under **Web Frontend → Setup**. Turn it on with a single toggle and the public site shows a privacy banner until visitors make a choice — their answer is remembered in their browser for a year by default.
  - Three quick-start presets you can apply with one click: **GDPR / UK GDPR**, **CCPA / CPRA (California)**, or **Generic notice** — each one sets best-practice defaults for the prompt mode, wording, and position.
  - Three prompt modes to choose: **Notice** (just a heads-up), **Consent** (Accept / Reject buttons), or **Strict opt-in** (the GDPR-compliant version).
  - **Auto-adapt to visitor region.** When on, EU/UK visitors automatically see the strict GDPR flow and California visitors see the CCPA flow — your chosen mode is the minimum; auto only escalates.
  - **Generate a starter privacy policy in one click.** Pick GDPR, CCPA, or Generic and a fresh policy page is created and linked as your privacy policy — you just need to fill in a few placeholders (organisation name, contact email, retention periods) before publishing.
  - Banner copy is fully editable: title, body, button labels, position (bottom bar, corner, or modal).
- **New: Privacy & cookies footer block** — drag it into your footer from the builder palette. It adds a "Privacy policy" link plus a "Cookie settings" button visitors can click any time to revisit their cookie choice.
- **Visitor metrics moved to Watchtower.** The Web Frontend "Visitor Metrics" page has been folded into the **Watchtower → Visitors** tab — same charts, same data, one place. The old URL still works (it just redirects), and every link that used to point there now goes to Watchtower.
- **Unique visitors is now the default headline number** on the visitor metrics tab, with a clear pill toggle to flip to "Hits" (every page load). The choice sticks in your browser. The dashboard widgets that show traffic also lead with unique visitors now — more useful for "how many real people".
- **Fixed:** the Web / View / Watchtower pills at the top of the sidebar no longer get an underline when you hover them.

## 2.7.5 — 2026-05-26 — Turn 404s into redirects without leaving the page

- **The 404s tab can now create redirects in one click.** Beside every row in **Top missing URLs** and **Recent 404s**, a **Redirect** button opens a small dialog already filled in with the missing URL — just type the destination and save. The row instantly shows a green "redirected" chip so you know which ones you've handled, and you can keep working through the list without ever leaving the page.
- **Wildcard redirects.** Source paths ending in `/*` (e.g. `/swag/*`) now match every URL under that prefix and land them all on the same target. Exact-match rules always win, and the matcher is boundary-safe (so `/swag/*` doesn't accidentally catch `/swagger`). The dialog has a **Use `/*`** helper that turns the clicked 404 into a parent-prefix wildcard for you.
- **Show more 404s at once.** The **Top missing URLs** and **Top referrers** cards (on both the 404s and Visitors tabs) now show 30 rows by default and have a **Show 30 more** button to keep expanding — handy when you've got a long tail of broken links to triage.
- **Fixed:** the **Hour of day** chart on Watchtower → Visitors was rendering as 24 flat lines even when there was real traffic — it now shows the actual bar heights again. Hour labels now appear under every column, not just every fourth.

## 2.7.4 — 2026-05-26 — Recovery Contacts page styling + save-bar tidy-up

- **Style the Recovery Contacts page from the Templates screen.** The public `/contactlist` page now shows up in **Web Frontend → Templates** like every other page, with its own appearance controls: heading, subheading, intro, container width, and the background/fonts/sizes Customize panel. These moved out of the Forms settings, which now focus on the form's plumbing — on/off, email alerts, button label, confirmation message, and bot protection.
- **One save bar, not two.** Editing a template in its pop-up no longer shows a duplicate "Unsaved changes" bar inside the dialog — you'll just see the usual yellow save bar at the bottom of the screen, and the dialog stays open after you save.
- **Fixed:** the "Contact us" button on the Recovery Contacts page no longer gets underlined when you hover over it.
- **Tidied:** a little more space between paragraphs in the announcement cards on the Announcements page.

## 2.7.3 — 2026-05-25 — Phone formatting + a contact call-to-action

- **Phone numbers look tidy automatically.** On the Recovery Contacts directory (and its PDF), numbers are formatted as you'd expect — `202-555-0100` for US/Canada (or `1-202-555-0100`), and the correct international style for numbers from other countries. People can still type however they like; only the display is cleaned up.
- **A "Contact us" prompt on the Recovery Contacts page** — a short line (pulled from your Contact page settings) and a button that takes visitors to your contact form. On phones it appears neatly at the bottom of the page, below the sign-up form.
- **Fixed:** on phones, the utility-bar buttons (like "Print List" and "Contact List") no longer wrap onto two lines.

## 2.7.2 — 2026-05-25 — Small refinements

- The signed-in admin button in your menus and footer now reads **"Return to dashboard"** (instead of "Back to TS Pro dashboard").
- Tidier spacing between the two email-alert switches on the **Recovery Contacts** form settings, and clearer wording confirming the admin is emailed about a removal **only after** the person clicks their confirmation link — so a bad actor can never get someone taken off the list.

## 2.7.1 — 2026-05-25 — Recovery Contacts: abuse protection + polish

Builds on the new **Recovery Contacts** directory with protection against malicious "update" and "remove" requests, plus a round of refinements.

- **No more spammed listing owners.** Someone can only request an update to a listing **once every 24 hours** — a second attempt is turned away and never applied. The form now tells people about this limit.
- **"I didn't submit this."** Every update/removal confirmation email now has a second link for the listing's owner to click if they didn't make the request. One click throws the request away and **locks that listing against any changes for 7 days**.
- **A new Watchtower view.** Flagged requests show up on the Watchtower **Overview** with the requestor's IP address and one-click **Block IP** + **Resolve** buttons, a red alert badge on the Watchtower button so you notice right away, and **Flagged / Locked** markers on the affected listings in the Recovery Contacts page.
- **Form refinements:** the "let people contact me by email through the site" option is now on by default (and stays on automatically if someone hides both their phone and email), a **"Need help?"** link sits at the bottom of the form, and the layout/copy got small clarity tweaks.
- **PDF:** listings reachable only through the site now print a tidy, clickable link to your contact page (the printed text drops the `https://` but the link still works).
- **Fixed:** the directory's live search now properly hides the entries that don't match what you've typed.

## 2.7.0 — 2026-05-25 — Recovery Contacts: a self-service member directory

A new **Recovery Contacts** module lets members add themselves to a shared directory and reach each other directly — turn it on under **Web Frontend → Forms → Recovery Contacts**. Once enabled, your public page lives at **`/contactlist`** and you manage entries under **Recovery Contacts** in the dashboard.

- **Members add themselves.** A simple form takes their name, phone, and email, and they choose exactly what shows publicly — phone, email, both, or neither. You approve each entry before it appears, and can adjust anyone's visibility later.
- **"Available to sponsor"** puts a red-heart badge on a listing so people looking for a sponsor can find them at a glance.
- **Stay reachable without exposing your details.** Members can switch on a **Contact me** button — visitors send them a message through the site and the email is relayed privately (the member's address is never shown, and they can just hit reply). It's on by default, and it's kept on automatically for anyone who hides both their phone and email, so there's always a way to reach them.
- **Self-service updates and removals.** When a member updates their listing or asks to be removed, we email them a confirmation link; one click applies the change automatically — no admin action needed. (You can still action requests yourself from the dashboard if someone never clicks.)
- **Find anyone fast.** Live search filters the list as you type — by name, phone, or email — and you can type **"sponsor"** to show only members available to sponsor.
- **Print or share a PDF.** One click downloads a clean, branded PDF of the directory (it respects whatever you've searched for). Members who are reachable only through the site show a note pointing to your `/contactlist` page instead of a blank phone/email.
- **A full activity log.** The dashboard keeps an audit trail of everything — new entries, confirmed updates and removals, relayed "Contact me" messages, and every admin action — each with who did it and when.
- Plus: a pending-count badge in the sidebar, an entry in your dashboard Forms widget, optional **email alerts** when someone joins or asks to be removed, and built-in bot protection (Turnstile).

## 2.6.1 — 2026-05-24 — Neobrutal theme

A bold new **Neobrutal** theme joins the lineup under **Web Frontend → Design → Theme**.

- **Neobrutalism**, done properly: colourful flat blocks (yellow, pink, cyan, lime), thick black borders, chunky **hard drop-shadows**, big **Archivo Black** headings, and buttons that visibly **press in** when you click them.
- It styles your whole site — header, menus, homepage, footer, every page — in both light and dark. In dark mode the page goes near-black while the bright cards keep popping.
- The **hero gets a geometric backdrop** — a faint grid with bold outlined shapes — and those shapes **re-scatter to new spots on every page refresh**, so the homepage feels alive without ever covering your headline.

Also fixed: the Neobrutal footer's location cards no longer turn black on hover.

## 2.6.0 — 2026-05-24 — New site themes + a deeper dark-mode toolkit

Your public site gains **four new ready-made themes** plus much finer control over dark mode and the mega menu.

- **Four new themes** under **Web Frontend → Design → Theme**, alongside Classic and Recovery Blue — each styles your whole site (header, menus, homepage, footer, every page) in both light and dark:
  - **Modern Dark** — a sleek deep-indigo "mission control" look with a soft aurora glow and teal/cyan buttons.
  - **Cyberpunk** — a neon-grid, near-black look in cyan/magenta with sharp edges and a techno typeface.
  - **Sanctuary** — a warm, calm sand-and-sage palette with a friendly serif.
  - **Terminal** — a green-on-black, all-monospace "command line" look with a blinking cursor.
- **Themes remember their settings.** When you switch themes, the one you're leaving is saved automatically and the one you return to comes back exactly how you left it. The theme switcher now lets you choose **Return to last saved state** or **Reset to default** before applying — and those buttons stay visible no matter how far you scroll the theme list.
- **The mega menu, leveled up** (Web Frontend → Navigation → Mega menu appearance):
  - Give it a **dynamic background** — the same animated backdrops you can already use on the hero and pages.
  - Set **separate background and text colours for light and dark mode**.
  - A **blend slider** mixes between your background colour and the dynamic background.
  - A **“Render dark in light mode”** switch keeps a dark panel behind light text.
  - Its **headings, links, and buttons** now all follow your chosen text colour.
- **New “Text — Darkmode” colour** on the Design page sets your site's dark-mode text everywhere at once.
- **Recovery Blue** now has a **frosted-glass header** and frosted footer cards.
- Plus a long list of dark-mode polish so colours stay consistent across cards, menus, buttons, and the homepage in every theme.

## 2.5.0 — 2026-05-22 — Popups you build like a page

You can now create **popups** — modal windows that appear over your public site — using the **same drag-and-drop builder you already use for pages**.

- Find them under **Web Frontend → Popups**. Click **New popup**, give it a name, and you land in the familiar builder: the same **draggable blocks** and the blue **“Add block”** button as the page editor. Drop in text, headings, images, buttons, columns, and more.
- **Style each popup**: width and max width, auto or fixed height, padding, background colour (with a separate dark-mode colour), corner radius, and shadow. Dim the page behind it with an adjustable backdrop, and place it in the centre, at the top, or at the bottom.
- **Control where it shows**: turn it on or off for desktop and mobile independently, and let it fill the screen width on phones.
- **Open it from anywhere**: point any link or button at **`#yourpopupname`** — a navigation link, a button on a page, or even a shared URL ending in `#yourpopupname`. You can also have a popup **open automatically** a few seconds after the page loads.
- **Preview before going live**: each popup has a Preview button that opens it for you even while it's disabled, so you can get it right before anyone else sees it. Visitors can close it with the × button, by clicking the dimmed background, or by pressing Escape.

Also fixed: the public home page no longer shows an error in the rare case where no homepage has been chosen yet — it now shows a friendly placeholder (and a shortcut to pick a homepage if you're signed in).

## 2.4.0 — 2026-05-21 — Live meeting bar updates on its own

The **LIVE meeting badge** at the top of your public site now appears and disappears **automatically, without anyone needing to refresh the page**.

- When an online or hybrid meeting reaches its start (or Zoom-opens) time, the yellow **LIVE: <meeting>** badge — with its **Join Zoom Meeting** button — slides in for everyone currently on the site, and clears itself when the meeting ends. Previously a visitor only saw it if they happened to load the page during the meeting.
- It checks for changes every 30 seconds (and the moment someone switches back to your tab), so the bar always reflects what's live right now.
- On desktop, any "Helpline"-style grouped item still tucks into its compact icon while a meeting is live to give the live message room — now correctly, whether the meeting was already live when the page loaded or went live while the visitor was reading.

No setup needed beyond the existing utility-bar settings: keep the bar enabled and the live-meeting badge turned on.

## 2.3.0 — 2026-05-21 — Image & asset caching for a faster public site

Your public site now lets returning visitors **keep images and styling in their browser cache** instead of re-downloading everything on every visit — so pages load noticeably faster the second time around — without ever showing stale content.

- **New Caching panel** under **Web Frontend → Caching**. Turn image caching on/off, choose how long browsers may keep images (default 7 days), and manage everything from one place.
- **Edits still appear instantly.** Every image has a hidden version stamp; when you upload or replace an image, the stamp changes and visitors get the new image right away — no waiting for the cache to expire.
- **Your CSS/JavaScript are cached too**, and refresh automatically on every update you deploy, so visitors are never stuck on old styling.
- **One-click controls**: *Clear image cache now* forces every visitor to refetch images on their next visit (handy after a bulk change), and *Rebuild thumbnails* clears the generated thumbnail files. The panel also shows the current cache version, when it was last cleared, and how much thumbnail data is on disk.
- **Nothing dynamic is affected** — pages, the live-meeting bar, forms, search, and the admin area always render fresh. Only images and static styling are cached.
- Caching is **on by default**, so you get the speed-up immediately; flip the toggle off any time if you'd rather not cache.

## 2.2.2 — 2026-05-21 — Frontend backups capture more, dashboard polish

Two improvements:

- **Frontend backups are now complete.** A frontend bundle now includes each page's **social-share settings** (the Open Graph title, description, and image you set per page) and each story's **publication date**. Previously these were quietly left out, so importing a bundle on another install lost the social cards and reset story dates to the import day. Importing an older bundle still works — the new fields just fall back to defaults. (The full-site backup already captured everything.)
- **Dashboard & sidebar polish.** The drag handles on the *Your role*, *Currently online*, and *Access requests* widgets now match the size, spacing, and position of every other widget's handle. In the sidebar, the Watchtower icon is slightly larger, the Notifications/Search spacing is tidied, and the **Web** button now shows the same green pulsing dot as the *Currently online* panel when your public site is live.

## 2.2.1 — 2026-05-20 — Footer builder now matches the page builder

The Footer admin has been rebuilt to work exactly like the content-page / homepage builder, instead of its own separate interface:

- A **Footer structure** card lets you arrange footer blocks into rows and columns with **drag-and-drop**, **click any block to edit its content**, add blocks from a **palette**, and add rows (1–4 columns) — the same flow you already use for pages.
- The bespoke "Save Footer" button is replaced by the familiar **sticky save bar** that appears when you have unsaved changes.
- Everything you could put in the footer before is still here (brand, link columns, social icons, secondary nav, copyright, meeting locations, contact section, dividers, etc.) — just edited consistently with the rest of the site.

## 2.2.0 — 2026-05-20 — Preview frontend pages before publishing

You can now **preview content pages and the homepage before they go live**:

- In the page editor, a new **Preview ↗** button opens a new tab showing your **current, unsaved changes** exactly as the public site would render them — so you can check your work before hitting Save. The live page doesn't change until you Save.
- In **Frontend → Pages**, every page now has a **Preview** link. This works for **draft pages too**, which previously couldn't be viewed at all until published.
- Previews are visible only to signed-in admins/editors (never the public) and carry a clear banner so you always know you're looking at a preview, not the live page.

## 2.1.35 — 2026-05-20 — WordPress importer: custom-field mapping + large-site chunked import

Two big upgrades to the WordPress importer, plus a small polish:

- **Map your custom fields to any post type.** A new **Map fields** step in the import wizard discovers the custom fields actually present on the WordPress site you connect to, then lets you map each one onto the matching field for every post type you're importing into — events/announcements (start & end times, location, contact, Zoom, website), stories (author, bio, story date, clean/sobriety date), and blog. Smart defaults are pre-filled from field-name detection, and your mapping is **saved per site** so re-imports remember it. Custom-field mapping now works for *every* post type, not just events.
- **Import sites with more than 500 posts.** The old 500-post cap is gone. Large sites now import **in chunks** automatically — a progress bar advances through the batches so the import can't time out, and posts already imported are safe even if you close the tab. The initial fetch tops out at 3,000 posts; for more, narrow by date on the WordPress side and run again.
- The dry-run **"Ready to import"** bar is now a sticky footer pinned to the bottom of the window, so the Run-import button stays in reach while you scroll the preview.

## 2.1.34 — 2026-05-20 — Notifications Center

A new **Notifications** button in the sidebar (just above Search) gathers everything that needs your attention into one place, with a live count chip:

- Click it to open a popup listing your notifications — pending access requests, locked accounts, unread contact messages, and submissions awaiting review (announcements/events and stories). Each one links straight to the section that needs attention.
- **Clear** items one at a time with the × button, or **Clear all** at once. The count chip updates instantly as you clear them.
- You only ever see notifications for sections you can act on — admins see everything; editors see submissions awaiting review.

## 2.1.33 — 2026-05-20 — Watchtower 404s, GSR Summary popup, smarter utility-bar collapse

Three improvements landed together:

- **Watchtower → 404s.** A new tab tracks the dead URLs visitors hit on the public site — broken inbound links, mistyped addresses, and pages that moved without a redirect. It shows totals over a time window, a trend chart, a ranked "Top missing URLs" list (with where each came from), and a recent-hits table. There's a **Clear log** button when you want to reset it. Admin pages and signed-in staff are never counted — these are real visitor misses.
- **GSR Summary popup.** The **GSR** button in the utility bar now opens the GSR Summary in a popup instead of jumping to the announcements page. It shows the exact same summary, styled to match. On phones it opens full-screen; on desktop it's a centred popup. A **Go to Announcements** button at the bottom takes you to the full page when you want it.
- **Utility-bar containers stay open on mobile.** When a live meeting is showing, a utility-bar group set to collapse to an icon (e.g. the helpline) still collapses on desktop to make room for the LIVE banner — but on mobile it now stays fully expanded, since the swipe strip has plenty of room and there's no need to hide its links behind an icon.

## 2.1.32 — 2026-05-20 — "What's New" release-notes dashboard widget

A new **What's New** widget on the main dashboard surfaces the latest release at a glance:

- The dashboard now leads with the newest version — its number, a **Latest** badge, the date, the headline, and the release note itself (rendered from the same notes you're reading right now).
- Below that, an **Earlier releases** list shows the previous few versions so you can catch up on recent changes without leaving the dashboard.
- A **View all release notes** button (bottom-right of the card) jumps straight to **Settings → About**, where the full version history lives.
- Like every other dashboard card you can drag it to reorder or hide it under **Customize**. It's on by default for everyone.

## 2.1.31 — 2026-05-20 — Templates page index polish

More refinement to the **Frontend → Templates** page now that each template configurator opens as a modal:

- The standalone **Reusable templates** intro card is removed — its explanation moved into the `?` tooltip next to the page title.
- Each row's URL (e.g. `/blog/<slug>`) shows as a tidy outline chip beside the template name; the "currently active" template shows in a soft brand-tinted pill.
- The **A→Z / Z→A** sort toggle sits at the far right of the toolbar.
- Rows now use the same flat card styling as the rest of the admin (no frontend-style hover lift).
- Fixed a brief flash of the old stacked-card layout on page load, and removed a stray collapse carrot that the global card-collapse feature was adding to this page.

## 2.1.30 — 2026-05-20 — Templates page modal layout fixes

Per-template modals on the **Frontend → Templates** page now reflow cleanly. Customize-panel cards (Background, Fonts, Sidebar widgets, Sizes) used to squeeze into one row inside the modal width and the content overflowed into adjacent neighbours; the grid is now capped at two columns inside modals (single column under 720px) so every card has full breathing room.

## 2.1.29 — 2026-05-20 — Post galleries, multi-select file picker, refactored Templates page

### Announcement / event posts get an image gallery (up to 6)

Edit any post to attach up to 6 images via upload or the File Browser. On the public detail page the gallery renders as a 3-column grid alongside the featured image with a click-to-zoom lightbox (keyboard navigation, swipe on mobile, ESC to close). Thumbnails are lazily generated so the page stays light.

### File Browser opens in multi-select mode when picking gallery images

When the gallery picker opens the File Browser, the modal switches into multi-select mode — checkboxes-style selection on every card / row, a sticky bottom action bar that counts your selection and adds them all in one click. The list-view Select button used to silently do nothing; that bug is also fixed.

### Frontend → Templates page is now a sortable list of modals

The Templates page used to render every template configurator (Meetings list, Story detail, Blog detail, etc.) as a long stack of cards. It's now a sortable list — A→Z / Z→A toggle persists per browser — with an **Edit** button per row that opens a centred modal. Forms inside each modal use the yellow save bar; the modal stays open after Save so you can keep iterating, and only the X (or Esc / backdrop click) dismisses.

## 2.1.28 — 2026-05-19 — Trailing-slash tolerance + form builder UX polish

### URLs with or without a trailing slash both work now

Visiting ``/contact/`` or ``/storyform/`` no longer 404s — every route resolves with or without the trailing slash. Fixes a class of "I copied the URL wrong" bug.

### Form-builder field cards expand on whole-card click

The **Edit** button on each field card in the form builder is gone. Click anywhere on a card (heading, type pill, chevron, dead space) to expand its editor; click any control inside an open card to interact with it normally. The card animates open/close over 200ms with a chevron indicator that rotates.

### Posts admin defaults to Posted newest-first; remembers your sort

The Announcements & Events list now defaults to **Posted** descending. Click any column header to override; your choice persists across visits via a cookie. The Pending tab keeps its own freshest-first default.

### Smaller polish

- **Custom Forms** sidebar entry renamed to **Custom Form Submissions** with a **Manage forms** button up top.
- Dashboard Forms widget rows now show just the pending count (e.g. "3 pending review") instead of the lifetime total — quieter and more actionable.
- Stories / Announcements & Events / Contact Form list pages gain a **Manage form** button up top linking to the matching form's settings page.

## 2.1.27 — 2026-05-19 — File-type restrictions on form uploads

Every file-type field in the form builder gains an **Accepted file types** input — comma-separated extensions or MIME types (``.pdf,.docx`` or ``image/*``). The picker on the public form filters accordingly; the server enforces the same rule on submit so a tampered POST can't sneak a disallowed file through.

## 2.1.26 — 2026-05-19 — Module form URLs & active-URL switch

The **Preview** button on each form's settings page (Announcements/Events, Story, Contact) now reflects the form's current public URL — the custom slug when one is configured, the canonical path otherwise. When you set a custom slug, the canonical path (``/submissionform``, ``/storyform``, ``/contact``) auto-redirects to the new URL so only one URL serves the form at a time.

## 2.1.25 — 2026-05-19 — Story submission pipeline + module-form builder

### Story submissions now have their own holding tank

Recovery story submissions used to land in the generic Form Submissions inbox. They now go to a dedicated **Pending review** tab on the Stories admin page — same flow announcement / event submissions already use. Each pending row shows the submitter's contact info, a download link for any attached file, and an **Approve to drafts** button that lands you on the story edit page. A new public ``/storyform`` page renders the form through the shared Submission Form chrome (Classic / Minimal / Split layouts).

### Form builder is now embedded in every module form's settings page

The same drag-and-drop field builder you use for custom forms is now layered onto all three module forms — Announcements/Events, Story, Contact. Each one ships with a default block set matching its built-in layout, so you can drag/edit/add/remove fields without losing the existing fields. Per-field labels, placeholders, help text, and options are editable inline inside the builder.

### Configurable public URL per module form

Each module form now has a customizable public URL slug. Type your preferred URL into the **Public URL** card on the form's settings page and visitors reach the form at ``/<your-slug>`` instead of the canonical path. The settings page pre-populates the input with the current URL so it's always visible.

### Other polish

- Custom forms get a **Visibility** toggle matching the module-form pattern.
- "Submission Form" is renamed **Announcements/Events Form** throughout the admin.
- The "Submission Form" template card on the Templates page is renamed **Forms Template** since it now drives the chrome of every public form.

## 2.1.24 — 2026-05-19 — Post edit page polish

The top **Save post** / **Save draft** primary buttons are replaced by a yellow save bar at the bottom of the page that only appears when you've made changes — same pattern the meeting modal uses. Lifecycle actions (Publish, Move to Drafts) stay in the top action area as explicit choices.

Other smaller tweaks:
- **Summary** field renamed to **GSR Summary**.
- The Event details card hides entirely when the Event checkbox is off — toggles live without a save.
- Links card now sits above Event details in the layout order.
- Headline card has 1rem of breathing room between each grouping.

## 2.1.23 — 2026-05-19 — Multi-row Links on posts

The single Event website field on posts grows into a **Links** section that applies to announcements and events alike. Each row carries a URL, a label, a button-style picker (**Primary** solid or **Secondary** outline), and an "open in new tab" checkbox. Add as many call-to-action buttons as you need — the public detail page renders each one in your chosen style.

## 2.1.22 — 2026-05-19 — Announcement auto-archive + other polish

### Auto-archive announcements on a schedule

The post edit page grows an **Auto-archive after date/time** toggle — visible only when the Announcement checkbox is checked (events already auto-archive via their event end date). Once the deadline passes, the announcement quietly moves to the archive without an admin visit.

### Posted on field now populates from any source

The Posted on field used to render blank for legacy posts even though the list table showed a date. It now falls back to the same value the list uses, so it's always populated.

### Event website + Event contact folded into Event details

Two cards on the post edit page collapsed into the main Event details card as subheaded sections.

### Meeting "Queue schedule change" submit is now inline

Clicking Queue schedule change inside the meeting edit modal no longer closes the modal — the yellow save bar flips to **Saved** and animates out instead, the same way the main meeting save works.

## 2.1.21 — 2026-05-19 — Public alert expiry + future schedule swaps

### Auto-hide public alerts on a schedule

The meeting edit modal's **Public Alert Message** gets a toggle + datetime picker. Flip it on, pick a moment, and the alert hides from the public site at that time and clears itself from the field — so admins don't have to remember to remove a one-off announcement.

### Queue a future schedule swap for a meeting

Directly under Day & Times, a new **Scheduled changes** fieldset lets you build the meeting's *next* schedule (full week's worth of days + times) and pick the date it goes live. Until then the meeting keeps its current schedule; on the effective date the queued set replaces it automatically.

### Better-looking public meeting alerts

The public meeting alert had a transparent amber wash that washed out on busy backgrounds. It's now a solid amber tile (light + dark themes), and the alert also surfaces on the meetings list cards above the description so visitors see it earlier in their journey.

## 2.1.20 — 2026-05-19 — Featured-image File Browser picker

The announcements / events edit page gains a **Choose from File Browser** button next to the featured-image upload input. Click it to pick from existing uploads instead of re-uploading; the preview swaps live and the existing upload + "Remove current image" affordances keep working unchanged.

## 2.1.19 — 2026-05-18 — Pending-submission chip + unified Forms dashboard widget

### Sidebar shows submissions awaiting review

The **Announcements & Events** sidebar entry carries a number chip when there are visitor-submitted posts in the holding tank — same shape the Watchtower / Contact Form chips already use.

### Dashboard Forms widget

The old Contact Form dashboard widget is replaced by a single **Forms** widget that lists every form on the system (Submission Form, Contact Form, plus every custom form you've built) with submission counts, last-activity dates, and warn-tinted attention badges. New custom forms appear automatically as they're created.

## 2.1.18 — 2026-05-18 — Form Submissions redesign, 12-hour Zoom calendar, small UX polish

A grab-bag release focused on making admin pages scan faster.

### Form Submissions page is now a card layout with submitter previews

The Form Submissions inbox used to render each row as a thin "Form name · timestamp · IP" strip — fine for one row, hard to scan for thirty. Replaced with a card layout that surfaces, per row:

- **Avatar circle** with the submitter's first initial (muted grey when nobody can be identified).
- **Submitter name** in bold, pulled from name-type fields in the form (or the email's local-part / "Anonymous" as fallbacks).
- **Form pill** showing which form they used, plus a local-time timestamp.
- **2-line headline** taken from the first subject or message field — see what they actually wrote without opening the detail.
- **Meta chips**: email, phone, field count, file-attachment count (when any), submitter IP.

Hover any card and it lifts toward brand-blue with a soft shadow + chevron slide. Mobile drops the chevron and stacks the timestamp.

### Zoom Accounts calendar shows 12-hour times

The grid used to render `18:45–20:00`. Now `6:45 PM–8:00 PM` — matches every other time display in the app.

### Sidebar Intergroup section: "+ Add Library" → "+ Add IG Library"

Disambiguates it from the **+ New Library** button on the main libraries page, which creates a regular non-Intergroup library.

### Currently Online widget no longer shows you

The widget used to surface the viewing admin's own row, which inflated the count and added noise — you already know you're signed in. Filtered out everywhere: the widget's list, the widget's header count, the dashboard tile's "X users · last 5 min" number, and the tile's tooltip names. Now they all show *other* people on the portal.

## 2.1.17 — 2026-05-18 — Custom forms now support Cloudflare Turnstile

If you have **Cloudflare Turnstile** turned on in **Settings → Security**, custom forms now show the Turnstile widget right above the Submit button — same as the events-submission form and the contact form already do. Visitors complete the challenge as part of filling out the form; the server verifies the token before storing the submission. If the challenge fails, the page re-renders with a red banner above the form explaining what happened, with everything the visitor typed still in place so they don't have to start over.

No action needed beyond keeping Turnstile enabled — every existing custom form picks up the protection automatically.

## 2.1.16 — 2026-05-18 — Local-time backups, idle Currently-Online rows, instant post-login appearance

Three admin-experience polishes around dates, the dashboard widget, and login UX.

### Off-site backup times now show in your local timezone

Every backup timestamp in the admin — last successful run on the dashboard widget, next scheduled run, the per-row last/next on the **Off-site Backups** list, the recent-activity rows, the run-history page — now renders in the timezone you set on **Settings → Timezone**, with the proper tz abbreviation on the end (e.g. `May 18, 03:00 PDT` instead of `May 18, 10:00 UTC`).

The cron expression itself is also interpreted in your local timezone now. If you type `0 3 * * *`, you get 3 AM **local** every day — matching what the rest of the admin shows on the wall clock — not 3 AM UTC. The schedule fieldset hints on the wizard and the edit page were updated to say so.

### Currently Online widget keeps idle users visible

The Currently Online widget used to drop a user the moment they hadn't navigated in 5 minutes. Now it keeps them in the list for up to an hour, but renders them greyed-out with "*no activity in X mins*" instead of an "Xs ago" timestamp. After an hour of silence the row drops off.

The header count ("X users") still reflects only the currently-active users (within the 5-minute window), so the number matches what the dashboard tile's "X users · last 5 min" shows. Empty-state copy changed from "Nobody is currently signed in" to "**No users active**" — fires only when nobody has been seen at all in the past hour.

### Newly-logged-in user shows up in the widget right away

A small reliability fix: a user who just logged in now appears in the widget on the very next 5-second poll regardless of what page their post-login redirect lands on. (Previously the widget waited for the first non-asset GET to fire its tracker, which was 99% of the time the next page they loaded but had occasional misses.)

## 2.1.15 — 2026-05-18 — Form Submissions now lives in the main app sidebar

The **Form Submissions** inbox moved out of the Web Frontend admin and into the main app sidebar's **Admin** section, right next to **Contact Form**. Visible only to admins. One click from anywhere in the portal opens the submissions list. The submissions list and detail pages also picked up a small cleanup: they render as standalone admin pages now, without the Web Frontend admin's two-column subnav chrome.

## 2.1.14 — 2026-05-18 — Fix: custom form submit 500'd while sending recipient email

After the CSRF fix shipped in 2.1.13, posting a valid submission to a custom form returned an Internal Server Error. The handler tried to read a column on SiteSetting that doesn't exist (`frontend_site_name` instead of `frontend_title`) while building the email subject. Fixed; submissions now go through cleanly. If you saw this error in 2.1.13, update to 2.1.14 and retry — nothing on your forms or stored submissions changes.

## 2.1.13 — 2026-05-18 — Fix: custom form submissions blocked with "CSRF token is missing"

Submitting a custom form on the public site returned **Bad Request — The CSRF token is missing**. The form's hidden CSRF input was omitted from the template — fixed. If you saw this error in 2.1.12, update to 2.1.13 and retry; nothing on your forms or their submissions changes.

## 2.1.12 — 2026-05-18 — Build your own forms, link them from the stories page

Two big additions that finally close the loop on letting visitors submit things to your site without writing code.

### Build any form you want, drag-and-drop

There's a new **Custom forms** section under **Web Frontend → Forms**. Click **+ Add form** to create one. The edit page is split in two:

- **Settings** — title, the URL slug (visitors reach the form at `/<slug>`), an optional description rendered above the form (Markdown supported — `**bold**`, `*italic*`, `[links](https://example.com)`, `-` lists), comma-separated recipient emails, and what happens after submit (redirect to a URL **or** show a thank-you message inline).
- **Fields** — drag-and-drop builder. Pick a type from the dropdown, click **+ Add field**, fill in the label. Eight field types: text, email, phone, textarea, select, radio, checkboxes, file. Each field has a label, optional placeholder + help text, required toggle, and (for select / radio / checkboxes) a one-per-line list of options. Drag the **⋮⋮** handle to reorder; click **Edit** to open a card's body; click the red trash button to delete with confirm.

The public form uses the same template chrome (Classic / Minimal / Split) as the Submission Form — pick once in **Web Frontend → Structure → Templates**, every custom form picks up the same look. On submit, each visitor's answers land in a new admin page, and each address you listed in recipients gets an email with the full field values. File uploads work and arrive as proper links in the admin detail view.

**Checkboxes** get a special treatment: their help text is a multi-line box that supports Markdown so you can write longer instructions, embed links, use `-` lists, etc.

### Form Submissions inbox

New **Form Submissions** entry in the Web Frontend admin's sidebar (under Structure). Lists every submission across every custom form, newest first, filterable by which form it came in on. Click any row for the detail view — field labels + values + file attachments. Delete button on the detail page (with confirm) if you want to clear something out.

### "Share your story" button on the stories page

The **Stories list** template on **Web Frontend → Structure → Templates** has two new fields under a **"Submit a story" button** section:

- **Form to link to** — a single dropdown with two groups: **Built-in forms** (Submission Form, Contact Form) and **Custom forms** (every custom form you've built; disabled ones show *(disabled)*). Pick one to surface a button on `/stories` that visitors can click to submit their own stories. Leave it set to *— None —* to hide the button entirely.
- **Button label** — optional. If blank, the button uses the linked form's own title (e.g. *Share Your Story*).

The button sits right under the page heading + subheading on whichever stories-list variant you've picked (paper-stack, ledger, manuscript, broadsheet, minimal-serif, magazine) — so it's where visitors expect to find a call to action.

### A few small touches

- A grumpy 500 error when opening a custom form's edit page is gone (a stray Jinja-syntax token sat inside a JavaScript comment).
- Drag-highlighting text inside a field card's textareas works again — previously the parent's `draggable="true"` hijacked the cursor; now the card only goes draggable while you're holding the **⋮⋮** handle.
- The **+ Add form** button on the forms index sits at its natural width (was stretching across the card on the first cut).

## 2.1.11 — 2026-05-18 — Dropbox backups stop expiring every 4 hours

If you were using Dropbox as an off-site backup destination, the access token Dropbox's "Generate access token" button gives you is only valid for **4 hours** — so the scheduler worked once the day you set it up, then failed every subsequent morning with `expired_access_token` and you had to keep generating new tokens. (Dev mode wasn't the cause — the token lifetime is the same on dev and published apps.)

Switched to Dropbox's proper OAuth refresh-token flow so the connection stays live indefinitely. Here's what changes for you:

- The Dropbox backup wizard now asks for **App key**, **App secret**, and a one-time **authorization code** instead of an access token. The App key and App secret come from your Dropbox app's **Settings** tab; the authorization code comes from clicking the new **Open Dropbox authorization page** button on the form — Dropbox shows you a code, you paste it back in, and we exchange it for a long-lived refresh token at save time.
- The Dropbox SDK then auto-mints a fresh short-lived access token on every backup call. No more daily expiry. The refresh token doesn't expire until you manually revoke the app's access from your Dropbox account settings.
- **Migrating an existing Dropbox target:** open **Off-site Backups** in Settings — your existing target will show a yellow banner reading "Legacy short-lived token" with a link straight into the Edit page. Fill in the three fields (App key, App secret, fresh authorization code from the auth page) and Save. Same Dropbox app, same remote path, same schedule — just upgraded auth.

The legacy raw-token path is still supported in code (so a pre-2.1.11 target keeps working until you upgrade it), but it'll continue to expire every 4 hours and the banner will keep nagging you to upgrade.

## 2.1.10 — 2026-05-18 — Bundle encryption, Frontend overview, edit-in-place backups, card shadow colour

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
