# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.ext.associationproxy import association_proxy

db = SQLAlchemy()

ROLES = ("admin", "editor", "intergroup_member", "viewer")

# Seed names for the two default Intergroup libraries that are auto-
# created when the umbrella module is first enabled. Membership in this
# tuple is no longer the gate — that's now ``Library.is_intergroup`` —
# but the names are still used by the migration backfill (to flag
# pre-existing rows on upgrade) and by the module-toggle seeder.
INTERGROUP_LIBRARY_NAMES = ("Intergroup Documents", "Intergroup Minutes")
FILE_CATEGORIES = ("documents", "scripts", "external_links", "videos", "images")
DAYS_OF_WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

meeting_reading_selections = db.Table(
    "meeting_reading_selections",
    db.Column("meeting_id", db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), primary_key=True),
    db.Column("reading_id", db.Integer, db.ForeignKey("reading.id", ondelete="CASCADE"), primary_key=True),
)

# Per-meeting per-reading visibility on the public web frontend. A reading
# present in this table is shown on the meeting's public detail page in the
# same place files-marked-public are listed. Independent from the granular-
# mode selection table above (which controls *which readings the meeting
# scopes itself to* on the backend).
meeting_reading_public = db.Table(
    "meeting_reading_public",
    db.Column("meeting_id", db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), primary_key=True),
    db.Column("reading_id", db.Integer, db.ForeignKey("reading.id", ondelete="CASCADE"), primary_key=True),
)

# Many-to-many link between a Reading and the LibraryCategory rows it's
# tagged with. Currently only used for Intergroup libraries — admins
# define an arbitrary list of categories per library and uploads must
# pick at least one — but the table is general so non-Intergroup
# libraries can opt in later without a schema change.
reading_categories = db.Table(
    "reading_categories",
    db.Column("reading_id", db.Integer, db.ForeignKey("reading.id", ondelete="CASCADE"), primary_key=True),
    db.Column("category_id", db.Integer, db.ForeignKey("library_category.id", ondelete="CASCADE"), primary_key=True),
)


class MeetingLibrary(db.Model):
    __tablename__ = "meeting_libraries"
    meeting_id = db.Column(db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey("library.id", ondelete="CASCADE"), primary_key=True)
    mode = db.Column(db.String(16), nullable=False, default="all")  # 'all' | 'granular'
    # Whole-library public toggle. When True AND mode='all', every item in
    # the library is shown on the public meeting page; ignored when mode
    # is 'granular' (per-item flags on `meeting_reading_public` win there).
    public_visible = db.Column(db.Boolean, nullable=False, default=False)

    meeting = db.relationship("Meeting", back_populates="library_assocs")
    library = db.relationship("Library", back_populates="meeting_assocs")


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="viewer")
    # Optional display name (first + last, or however the admin
    # chooses to address them). Distinct from ``username`` — username
    # is the login handle and stays in the form it was registered
    # with; ``name`` is the friendly form ("Jane D.") used wherever
    # the portal shows a person rather than an account, including
    # welcome emails, the Trusted Servants list pre-fill, and the
    # admin Users table.
    name = db.Column(db.String(120))
    # Optional contact number captured at user creation. Prefilled from
    # the matching access-request row when the admin clicks Create User
    # from the Access Requests page; editable on the Users panel later.
    phone = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    dash_show_stats = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_intergroup = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_meetings = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_libraries = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_files = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_server_metrics = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_online_users = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_access_requests = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_contact_form = db.Column(db.Boolean, nullable=False, default=True)
    # Per-user toggle for the unified Forms dashboard widget. Replaces
    # the standalone contact-form widget (whose column above is kept
    # for backwards-compat with existing rows but no longer surfaces
    # in the dashboard customize modal).
    dash_show_forms = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_deletions = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_currently_online = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_visitor_metrics = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_backups = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_trusted_servants = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_release_notes = db.Column(db.Boolean, nullable=False, default=True)
    # When True, the main app sidebar auto-collapses to a hamburger
    # menu while the user is inside the Web Frontend admin (/frontend/…).
    # The Web Frontend has its own sub-nav (fe-admin-subnav) so the
    # outer sidebar competes with editing canvas width on laptops; the
    # auto-collapse trades it for the existing mobile sidebar UX so
    # admins get the full content area back. Default on per the user
    # spec ("let the user access it when needed").
    fe_admin_autohide_sidebar = db.Column(db.Boolean, nullable=False, default=True)
    dash_order_json = db.Column(db.Text)

    # Web Frontend overview widget toggles + order. Mirrors the main
    # dashboard's dash_show_* / dash_order_json pair so the overview tab
    # at /tspro/frontend/ has the same per-user customise + drag-reorder
    # UX as the home dashboard.
    fe_dash_show_status = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_show_visitor_metrics = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_show_pages = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_show_redirects = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_show_navigation = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_show_forms = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_show_branding = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_show_header_footer = db.Column(db.Boolean, nullable=False, default=True)
    fe_dash_order_json = db.Column(db.Text)

    last_seen_at = db.Column(db.DateTime)
    # Current navigation location for the live "who's online" widget.
    # Updated by the same throttled before_request hook that maintains
    # last_seen_at, but cheap to skip for API polling / static asset
    # paths so the widget itself doesn't pin every viewer to /api/...
    # ``last_endpoint`` stores the Flask endpoint name ("main.meetings"),
    # ``last_path`` stores the URL path ("/tspro/meetings/12") so the
    # widget can show a clickable, human-readable destination.
    last_endpoint = db.Column(db.String(128))
    last_path = db.Column(db.String(500))
    # Per-user gate on the public Forgot Password flow. False blocks
    # the account from generating reset tokens so the user can't drive
    # their own password change — admins can still reset the password
    # via the Settings → Users modal regardless of this flag. Default
    # True preserves the historical behaviour for upgraded installs.
    password_reset_allowed = db.Column(db.Boolean, nullable=False, default=True)
    # Soft account disable. ``True`` blocks new sign-ins (login() refuses
    # the credentials) and invalidates any live session via the
    # user_loader returning None for disabled rows. The row itself is
    # preserved so re-enabling restores access without re-creating the
    # account or losing its history.
    disabled = db.Column(db.Boolean, nullable=False, default=False)

    @property
    def is_active(self):
        """Flask-Login hook: ``False`` causes ``login_user`` to refuse
        the sign-in. Combined with the user_loader's disabled-check,
        this means a disabled account can neither start a new session
        nor continue an existing one."""
        return not self.disabled

    def can_edit(self):
        """Broad editor gate: meetings, files, libraries, etc. Intergroup
        members inherit every Editor permission AND additionally pass
        the per-library Intergroup gate below."""
        return self.role in ("admin", "editor", "intergroup_member")

    def can_edit_frontend(self):
        """Authorized to edit the Web Frontend module and preview it
        while the public toggle is off. Admins only — the dedicated
        ``frontend_editor`` role was retired."""
        return self.role == "admin"

    def can_edit_intergroup_libraries(self):
        """True for admins and the dedicated `intergroup_member` role.
        Used by per-library edit gates on Intergroup-flagged libraries
        — regular editors are deliberately excluded so those libraries
        can be delegated to a narrow set of trusted servants."""
        return self.role in ("admin", "intergroup_member")

    def can_edit_library(self, library):
        """Effective edit permission for a single ``Library``. Libraries
        flagged ``is_intergroup`` are gated to admins + intergroup_members
        only; every other library uses the broad editor gate (which
        includes intergroup_members, since they inherit Editor)."""
        if library is not None and getattr(library, "is_intergroup", False):
            return self.can_edit_intergroup_libraries()
        return self.can_edit()

    def can_edit_library_item(self, item):
        """Per-item gate for renaming / editing an existing library
        item (title change, file replacement, body / URL / thumbnail
        swap, inline category re-tag). Editors are restricted to items
        whose creator was another Editor — mirrors
        ``can_delete_library_item`` so a single rule covers both
        rename and delete authority. Admin- and Intergroup-Member-
        uploaded items are protected. Admin / intergroup_member follow
        the broader ``can_edit_library`` gate; viewers fail at that gate."""
        if item is None:
            return False
        if not self.can_edit_library(item.library):
            return False
        if self.role == "editor":
            creator = item.creator
            if creator is None:
                return False
            return creator.role == "editor"
        return True

    # Legacy alias kept for one release while every caller is updated.
    can_edit_reading = can_edit_library_item

    def can_use_editor_tools(self):
        """Generic gate for utility endpoints used during editing
        (markdown preview, etc.). Aliased to ``can_edit`` since every
        role that has editor tools also passes the broad editor gate."""
        return self.can_edit()

    def can_create_meetings(self):
        """Authorized to provision new meetings or delete existing ones.
        Admins and Intergroup Members only — Editors keep their
        authority to edit, schedule, and attach files to existing
        meetings, but creating new entries and removing them is held
        back to the trusted-servant tier."""
        return self.role in ("admin", "intergroup_member")

    def can_rename_media(self, media):
        """Per-file gate for renaming a ``MediaItem`` in the file
        browser. Mirrors ``can_delete_reading``: Editors can rename a
        media item only when its uploader was another Editor. Admin-,
        Intergroup-Member-, and legacy (uploader-unknown) files are
        protected. Admins and Intergroup Members can rename any file.
        Viewers fail the broader ``can_edit`` gate on the route."""
        if media is None:
            return False
        if self.role == "admin":
            return True
        if self.role == "intergroup_member":
            return True
        if self.role == "editor":
            uploader = media.uploader
            if uploader is None:
                return False
            return uploader.role == "editor"
        return False

    def can_manage_libraries(self):
        """Authorized to create new libraries and edit existing
        library metadata (name, description, alert message, the
        Intergroup flag, the category list). Admins and Intergroup
        Members only. Editors can still add / edit / delete files
        inside existing libraries (subject to the per-row gates on
        individual readings), but library provisioning and settings
        changes are held back to the trusted-servant tier so the
        catalog of libraries stays coherent across the portal."""
        return self.role in ("admin", "intergroup_member")

    def can_bulk_edit_categories(self, item):
        """Per-item gate for the multi-select bulk-edit-categories
        action on the library detail page. Mirrors
        ``can_delete_library_item`` exactly: if the user is allowed
        to destroy an item, they're allowed to mass-tag it."""
        return self.can_delete_library_item(item)

    def can_delete_library_item(self, item):
        """Per-library-item deletion gate.

        - Admins: any item.
        - Intergroup members: any item inside a library they can edit
          (they have exclusive edit on Intergroup-flagged libraries; for
          everything else they inherit the broad editor gate).
        - Editors: only items whose creator was another Editor.
          Admin-, Intergroup-Member-, and legacy (creator=None) items
          are protected — Editors can't touch content uploaded by
          users who outrank them. This keeps authoritative content
          (admin uploads, Intergroup-Member uploads of trusted-servant
          material) safe from editor purges.
        - Viewers: never.

        ``item`` is the ``LibraryItem`` row about to be deleted;
        ``None`` is treated as a no-op deny."""
        if item is None:
            return False
        if self.role == "admin":
            return True
        if self.role == "intergroup_member":
            return self.can_edit_library(item.library)
        if self.role == "editor":
            creator = item.creator
            if creator is None:
                return False
            return creator.role == "editor"
        # viewer falls through to deny.
        return False

    # Legacy alias for the old method name. Kept for one release while
    # every caller is migrated to ``can_delete_library_item``.
    can_delete_reading = can_delete_library_item

    def is_admin(self):
        return self.role == "admin"


class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    # Explicit URL slug for the public detail page. When NULL the public
    # site falls back to slugify(name). Editing this is gated to admins +
    # frontend editors. Changes are logged to EntitySlugHistory so old
    # links 301-redirect to the current slug.
    slug = db.Column(db.String(255))
    description = db.Column(db.Text)
    alert_message = db.Column(db.Text)         # admin-only — shown on the backend meeting list / detail page
    public_alert_message = db.Column(db.Text)  # rendered on the public meeting detail page
    # Optional auto-expiry for the public alert. When set, the alert
    # is shown to the public only until this timestamp; the next page
    # load past the cutoff also clears the message + expiry from the
    # DB so the field empties itself on the admin side too. NULL =
    # no expiry (the alert sticks until the admin clears it).
    public_alert_expires_at = db.Column(db.DateTime)
    day_of_week = db.Column(db.String(32))  # legacy, unused by new UI
    time = db.Column(db.String(32))         # legacy, unused by new UI
    location = db.Column(db.String(255))
    location_notes = db.Column(db.Text)  # admin-only context shown alongside the address
    # Optional extended-content section rendered on the public meeting
    # detail page below the schedule/zoom/files blocks. JSON list of
    # {title, body} dicts; body is Markdown. Gated by the boolean
    # toggle so admins can park draft content without exposing it.
    extended_content_enabled = db.Column(db.Boolean, nullable=False, default=False)
    extended_blocks_json = db.Column(db.Text)
    zoom_meeting_id = db.Column(db.String(64))
    zoom_passcode = db.Column(db.String(128))
    zoom_link = db.Column(db.String(1000))
    zoom_opens_time = db.Column(db.String(16))  # "HH:MM"
    meeting_type = db.Column(db.String(16), nullable=False, default="in_person")  # in_person|online|hybrid
    logo_filename = db.Column(db.String(500))
    zoom_account_id = db.Column(db.Integer, db.ForeignKey("zoom_account.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    archived_at = db.Column(db.DateTime)
    show_otp = db.Column(db.Boolean, nullable=False, default=True)

    zoom_account = db.relationship("ZoomAccount", foreign_keys=[zoom_account_id])
    files = db.relationship("MeetingFile", backref="meeting", cascade="all, delete-orphan", lazy="dynamic")
    library_assocs = db.relationship("MeetingLibrary", back_populates="meeting",
                                     cascade="all, delete-orphan")
    libraries = association_proxy("library_assocs", "library",
                                  creator=lambda lib: MeetingLibrary(library=lib))
    selected_library_items = db.relationship("LibraryItem", secondary=meeting_reading_selections)
    public_library_items = db.relationship("LibraryItem", secondary=meeting_reading_public)
    schedules = db.relationship("MeetingSchedule", backref="meeting",
                                cascade="all, delete-orphan", lazy="select",
                                order_by="MeetingSchedule.day_of_week, MeetingSchedule.start_time")

    def files_by_category(self, category):
        return self.files.filter_by(category=category).order_by(MeetingFile.position, MeetingFile.id).all()

    def public_files(self):
        """Return all files this meeting has marked publicly visible,
        sorted in admin-defined order. Used by the public meeting-detail
        templates to render the Files & Readings block."""
        return (self.files.filter_by(public_visible=True)
                          .order_by(MeetingFile.category,
                                    MeetingFile.position,
                                    MeetingFile.id).all())

    @property
    def public_slug(self):
        """Effective public-frontend slug. Explicit ``slug`` wins; otherwise
        derive from the meeting name. Both branches feed through the same
        ``slugify`` so '/MEETING/' URLs and stored slugs always normalise."""
        from .colors import slugify
        return slugify(self.slug) if self.slug else slugify(self.name)

    def library_mode(self, library):
        for a in self.library_assocs:
            if a.library_id == library.id:
                return a.mode
        return "all"

    def visible_library_items(self, library):
        if self.library_mode(library) == "granular":
            sel_ids = {r.id for r in self.selected_library_items}
            return [r for r in library.items if r.id in sel_ids]
        return library.items.all()

    def selected_ids_for_library(self, library):
        sel_ids = {r.id for r in self.selected_library_items}
        return [r.id for r in library.items if r.id in sel_ids]

    def extended_blocks(self):
        """Decode the per-meeting extended-content blocks. Returns a list
        of {title, body} dicts; non-list/malformed payloads collapse to
        an empty list. Empty entries (no title and no body) are
        filtered so the public renderer's "do we have anything?" check
        is just a truthiness test."""
        import json as _json
        raw = (self.extended_blocks_json or "").strip()
        if not raw:
            return []
        try:
            data = _json.loads(raw)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            body = (item.get("body") or "").strip()
            if not (title or body):
                continue
            out.append({"title": title, "body": body})
        return out

    def public_library_visible(self, library):
        """Whole-library public toggle for `library`. Only meaningful when
        the meeting's mode for that library is 'all' — granular mode falls
        back to the per-item flags on `meeting_reading_public`."""
        for a in self.library_assocs:
            if a.library_id == library.id:
                return bool(a.public_visible)
        return False

    def effective_public_library_items(self):
        """Resolved list of LibraryItems to show on the public meeting page.

        Combines:
          * granular per-item flags from `meeting_reading_public` (used in
            'granular' mode), plus
          * every item from libraries whose `MeetingLibrary.public_visible`
            is True AND whose mode is 'all' (whole-library opt-in).

        De-duplicated by id, ordered to follow each library's own
        `Library.items` sequence so the public page reads in the same
        order the librarian curated."""
        per_item_ids = {r.id for r in self.public_library_items}
        whole_library_ids = []
        for a in self.library_assocs:
            if a.public_visible and (a.mode or "all") == "all":
                whole_library_ids.append(a.library_id)
        if not per_item_ids and not whole_library_ids:
            return []
        # Walk the included libraries in order; within each library walk
        # the items in the library's own item ordering.
        out = []
        seen = set()
        for a in self.library_assocs:
            lib = a.library
            if not lib:
                continue
            if a.library_id in whole_library_ids:
                for r in lib.items:
                    if r.id not in seen:
                        seen.add(r.id)
                        out.append(r)
                continue
            # Granular case — pick only the per-item-flagged readings.
            for r in lib.items:
                if r.id in per_item_ids and r.id not in seen:
                    seen.add(r.id)
                    out.append(r)
        return out


class MeetingSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday..6=Sunday
    start_time = db.Column(db.String(8), nullable=False)  # "HH:MM"
    duration_minutes = db.Column(db.Integer, nullable=False, default=60)
    opens_time = db.Column(db.String(8))  # "HH:MM", optional per-day Zoom opens
    zoom_account_id = db.Column(db.Integer, db.ForeignKey("zoom_account.id", ondelete="SET NULL"))

    zoom_account = db.relationship("ZoomAccount", backref="schedules")

    @property
    def day_name(self):
        return DAYS_OF_WEEK[self.day_of_week] if 0 <= self.day_of_week < 7 else "?"

    def end_minutes(self):
        h, m = self.start_time.split(":")
        return int(h) * 60 + int(m) + int(self.duration_minutes or 0)

    def start_minutes(self):
        h, m = self.start_time.split(":")
        return int(h) * 60 + int(m)

    @property
    def end_time(self):
        total = self.end_minutes()
        return f"{(total // 60) % 24:02d}:{total % 60:02d}"


class MeetingScheduleChange(db.Model):
    """A pending future schedule swap for a Meeting.

    Stores a *complete* replacement schedule (one full week's worth)
    plus the date it goes live. Until ``effective_date`` arrives the
    row sits dormant — the meeting's existing ``schedules`` rows keep
    rendering. On or after ``effective_date`` the sweep helper
    (``_apply_meeting_schedule_changes`` in routes) replaces every
    ``MeetingSchedule`` row on the parent meeting with the contents
    of ``schedules_json`` and deletes this change row.

    ``schedules_json`` is the same shape ``_parse_schedule_form``
    produces: a list of ``{day, start_time, duration, opens_time,
    zoom_account_id}`` dicts so the activation step is a 1:1 swap."""
    __tablename__ = "meeting_schedule_change"
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer,
                           db.ForeignKey("meeting.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    # Site-local calendar date the swap goes live. Stored as a Date
    # (no time component) — the swap activates at the start of this
    # day in the site's configured timezone.
    effective_date = db.Column(db.Date, nullable=False, index=True)
    # Optional admin-authored note explaining what's changing and why.
    # Shown on the meeting modal next to the pending row.
    note = db.Column(db.String(500))
    # JSON list mirroring _parse_schedule_form's output shape.
    schedules_json = db.Column(db.Text, nullable=False, default="[]")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer,
                           db.ForeignKey("user.id", ondelete="SET NULL"))

    meeting = db.relationship(
        "Meeting",
        backref=db.backref("schedule_changes",
                           cascade="all, delete-orphan",
                           order_by="MeetingScheduleChange.effective_date"))


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    location_type = db.Column(db.String(16), nullable=False, default="in_person")
    # Legacy single-line address — kept for backward compat. New saves
    # populate the split fields below; legacy rows still read out of
    # `address` as a fallback. The combine helper rebuilds `address`
    # from the split fields on save so callers that read `address`
    # continue to see the canonical string.
    address = db.Column(db.String(500))
    street = db.Column(db.String(255))
    city = db.Column(db.String(120))
    state = db.Column(db.String(64))
    zip_code = db.Column(db.String(20))
    maps_url = db.Column(db.String(1000))
    website_url = db.Column(db.String(1000))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def address_lines(self):
        """Return the address as a 2-line list ([street], [city, ST zip])
        with empty parts dropped. Used by templates that want to show
        the address split across lines without doing the joining
        themselves. Falls back to the legacy single-line `address` when
        none of the split fields are populated — and applies a smart
        first-comma split so even legacy "1638 R St NW, Washington, DC
        20009" shapes render with city/state/zip on the second line
        instead of running together with the street."""
        if any((self.street, self.city, self.state, self.zip_code)):
            line1 = (self.street or "").strip()
            csz_parts = []
            if self.city: csz_parts.append(self.city.strip())
            tail = " ".join(p for p in [(self.state or "").strip(),
                                        (self.zip_code or "").strip()] if p)
            line2 = ", ".join([p for p in [", ".join(csz_parts), tail] if p]) \
                    if csz_parts and tail \
                    else (csz_parts[0] if csz_parts else tail)
            return [line for line in [line1, line2] if line]
        if self.address:
            # Honour explicit newlines in legacy data first.
            nl_lines = [line.strip() for line in self.address.splitlines() if line.strip()]
            if len(nl_lines) > 1:
                return nl_lines
            # Single-line legacy address: split on the first comma so
            # the street stays on line 1 and city/state/zip drops to
            # line 2 (e.g. "1638 R St NW, Washington, DC 20009" →
            # ["1638 R St NW", "Washington, DC 20009"]). Addresses
            # without any commas just render as a single line.
            text = nl_lines[0] if nl_lines else self.address.strip()
            head, sep, tail = text.partition(",")
            if sep and tail.strip():
                return [head.strip(), tail.strip()]
            return [text] if text else []
        return []


class NavLink(db.Model):
    """Custom sidebar navigation link to an external URL."""
    __tablename__ = "nav_link"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(1000), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SiteSetting(db.Model):
    """Singleton: portal-wide branding/customization."""
    __tablename__ = "site_setting"
    id = db.Column(db.Integer, primary_key=True)
    footer_logo_filename = db.Column(db.String(500))
    footer_logo_url = db.Column(db.String(1000))
    footer_logo_width = db.Column(db.Integer, default=32)
    # Canonical public URL for this portal. Used by emails and any other
    # outbound message that needs an absolute link — without this set,
    # `url_for(..., _external=True)` falls back to whatever Host header
    # the request carried (often a Docker bridge IP). Stored without a
    # trailing slash; helpers in app/routes.py normalize before use.
    site_url = db.Column(db.String(255))
    intergroup_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Umbrella "Intergroup" module: when on, the sidebar gets an Intergroup
    # subsection that surfaces the Intergroup Email page plus shortcuts to
    # the Intergroup Minutes and Intergroup Documents libraries. Independent
    # of ``intergroup_enabled`` (which still gates the Email page itself).
    intergroup_module_enabled = db.Column(db.Boolean, nullable=False, default=True)
    intergroup_module_required_role = db.Column(db.String(32), nullable=False, default="viewer")
    ig_intro = db.Column(db.Text)
    ig_webmail_url = db.Column(db.String(1000))
    ig_incoming_host = db.Column(db.String(255))
    ig_incoming_port = db.Column(db.String(16))
    ig_outgoing_host = db.Column(db.String(255))
    ig_outgoing_port = db.Column(db.String(16))
    ig_setup_notes = db.Column(db.Text)
    ig_learn_more_url = db.Column(db.String(1000))
    ig_page_title = db.Column(db.String(120))
    dash_show_stats = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_intergroup = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_meetings = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_libraries = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_files = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_pic = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_server_metrics = db.Column(db.Boolean, nullable=False, default=True)
    dash_order_json = db.Column(db.Text)  # JSON array of widget keys in display order
    pic_name = db.Column(db.String(200))
    pic_email = db.Column(db.String(255))
    pic_phone = db.Column(db.String(64))
    zoom_tech_enabled = db.Column(db.Boolean, nullable=False, default=False)
    zoom_tech_title = db.Column(db.String(120))
    zoom_tech_content = db.Column(db.Text)
    zoom_tech_blocks_json = db.Column(db.Text)
    zoom_tech_template = db.Column(db.String(16), nullable=False, default="standard")
    # Announcements & Events module toggle. Default True so existing
    # installs don't lose data the moment the column is added.
    posts_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # Per-module role gates. Each value is one of: viewer (any signed-in
    # user), editor (admin + editor), intergroup_member (admin +
    # intergroup_member), admin (admin only). Defaults preserve the
    # historical behavior — Posts admin-only, Intergroup/Zoom-Tech open
    # to all, Web Frontend reserved for admins.
    intergroup_required_role = db.Column(db.String(32), nullable=False, default="viewer")
    zoom_tech_required_role = db.Column(db.String(32), nullable=False, default="viewer")
    posts_required_role = db.Column(db.String(32), nullable=False, default="admin")
    frontend_module_required_role = db.Column(db.String(32), nullable=False, default="admin")
    # Sidebar ordering. Mode: auto-asc | auto-desc | manual. Auto modes
    # ignore the JSON and sort items alphabetically inside each section
    # (Main → External → Admin order is fixed). Manual mode reads
    # sidebar_order_json: {"sections": [...], "main": [...], "admin": [...]}.
    sidebar_sort_mode = db.Column(db.String(16), nullable=False, default="auto-asc")
    sidebar_order_json = db.Column(db.Text)
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer)
    smtp_username = db.Column(db.String(255))
    smtp_password_enc = db.Column(db.LargeBinary)
    smtp_from_email = db.Column(db.String(255))
    smtp_from_name = db.Column(db.String(200))
    smtp_security = db.Column(db.String(16), nullable=False, default="starttls")  # none|starttls|ssl
    access_request_to = db.Column(db.String(500))  # comma-separated recipients
    # Where to email new submissions made via the public /submissionform.
    # Comma-separated list, mirrors access_request_to. Falls back to
    # access_request_to when blank so installs that already configured
    # admin notifications get submissions for free.
    submission_to = db.Column(db.String(500))
    # Public submission form configuration. Settings live alongside
    # the recipient list above so the Forms admin page can read all
    # submission-form columns from one row. All admin-tunable copy
    # is admin-only — visitors only see what survives the renderer.
    submission_form_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # Optional override of the form's field set. Same shape as
    # ``CustomForm.blocks_json`` (a JSON list of field dicts produced
    # by the field builder UI). When NULL, the form renders its
    # built-in default field set; when set, the saved blocks drive
    # what's shown on the public form. Each module's POST handler
    # uses name heuristics to map submitted values back into the
    # row's structured columns (see _match_module_field_names).
    submission_form_blocks_json = db.Column(db.Text)
    # Customizable public URL slug. When set, the form is served at
    # ``/<slug>`` (in addition to its canonical ``/submissionform``);
    # admin-facing URL surfaces (forms registry, nav-link picker,
    # CTAs) prefer the customized slug so the public site reads it
    # the way the admin wants. NULL keeps the form on its built-in
    # path only.
    submission_form_slug = db.Column(db.String(120))
    # Stories submission form gate — same shape as
    # ``submission_form_enabled`` for announcements/events. When off,
    # the public ``/storyform`` endpoint 404s and the stories-list
    # CTA hides itself. Heading / subheading / success message
    # columns mirror the events/announcements submission form so the
    # Forms admin can render a single settings page for both.
    story_form_enabled = db.Column(db.Boolean, nullable=False, default=True)
    story_form_heading = db.Column(db.String(200))
    story_form_subheading = db.Column(db.String(500))
    story_form_intro = db.Column(db.Text)
    story_form_success_message = db.Column(db.String(500))
    story_form_submit_label = db.Column(db.String(100))
    story_form_to = db.Column(db.String(500))
    # Per-field labels / help text. Each falls back to a baked
    # default at render time so a fresh install renders the form
    # exactly like the original "Story Submission Form" custom
    # form the user had built — admins only need to touch these
    # when they want to deviate. Wired up via the Story Form
    # settings page; persisted as plain text so editors aren't
    # locked into a structured editor.
    story_form_name_label = db.Column(db.String(120))
    story_form_email_label = db.Column(db.String(120))
    story_form_email_required = db.Column(db.Boolean, nullable=False, default=False)
    story_form_story_label = db.Column(db.String(120))
    story_form_story_placeholder = db.Column(db.String(200))
    story_form_file_label = db.Column(db.String(120))
    story_form_file_help = db.Column(db.Text)
    story_form_terms_label = db.Column(db.String(120))
    story_form_terms_intro = db.Column(db.String(200))
    story_form_terms_text = db.Column(db.Text)
    story_form_terms_checkbox_label = db.Column(db.String(200))
    story_form_blocks_json = db.Column(db.Text)
    story_form_slug = db.Column(db.String(120))
    submission_form_heading = db.Column(db.String(200))
    submission_form_subheading = db.Column(db.String(500))
    submission_form_modal_heading = db.Column(db.String(200))
    submission_form_intro = db.Column(db.Text)
    submission_form_success_message = db.Column(db.String(500))
    # 'both' | 'announcements' | 'events' — drives which type
    # checkboxes the form exposes. 'both' shows both checkboxes
    # (default); 'announcements' or 'events' restricts to a single
    # type and skips the picker.
    submission_form_allowed_types = db.Column(db.String(16), nullable=False, default="both")
    submission_form_submit_label = db.Column(db.String(100))
    # Public /submissionform layout — picked from SUBMISSION_FORM_TEMPLATES
    # in app.frontend. Mirrors the pattern other templated public pages
    # use (template key + width / padding knobs + a standalone dynbg
    # fallback). Per-template font / size / colour overrides live in the
    # shared frontend_template_settings_json bucket under "submission_form".
    frontend_submission_form_template = db.Column(db.String(64), nullable=False, default="classic")
    frontend_submission_form_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_submission_form_max_width = db.Column(db.Integer, nullable=False, default=720)
    frontend_submission_form_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_submission_form_bg_dynamic_key = db.Column(db.String(64))
    frontend_submission_form_bg_dynbg_config_json = db.Column(db.Text)
    login_particle_effect = db.Column(db.String(32), nullable=False, default="stars")
    login_bg_color = db.Column(db.String(32))  # legacy single color
    login_bg_colors = db.Column(db.Text)  # JSON array of hex codes, 1..4, overrides login_bg_color
    login_particle_speed = db.Column(db.Integer, nullable=False, default=85)   # 10..300 percent
    login_particle_size = db.Column(db.Integer, nullable=False, default=185)  # 25..400 percent
    login_transition_enabled = db.Column(db.Boolean, nullable=False, default=True)
    turnstile_enabled = db.Column(db.Boolean, nullable=False, default=False)
    turnstile_site_key = db.Column(db.String(128))
    turnstile_secret_key_enc = db.Column(db.LargeBinary)
    # Backend (admin / /tspro) Open Graph metadata. When the public web
    # frontend module is enabled, these tags are emitted only on /tspro/*
    # URLs. Otherwise they apply site-wide.
    og_enabled = db.Column(db.Boolean, nullable=False, default=False)
    og_title = db.Column(db.String(200))
    og_description = db.Column(db.Text)
    og_image_filename = db.Column(db.String(500))
    # Frontend (public marketing site) Open Graph metadata. Independent of
    # the backend OG fields above so the link previews shown when /
    # /meeting/foo, /about, etc. are shared can differ from the previews
    # admins see when sharing /tspro URLs.
    frontend_og_enabled = db.Column(db.Boolean, nullable=False, default=False)
    frontend_og_title = db.Column(db.String(200))
    frontend_og_description = db.Column(db.Text)
    frontend_og_image_filename = db.Column(db.String(500))
    # Frontend-specific favicon. Independent of the admin /tspro favicon.
    # When None, the bundled static/img/favicon.png fallback is used.
    frontend_favicon_filename = db.Column(db.String(500))
    # iOS / iPadOS "Add to Home Screen" icon + display name for the
    # admin /tspro pages. When the filename is None, the bundled
    # static/img/apple-touch-icon_tspro.png fallback is used. When the
    # name is None, the browser uses the page <title> instead.
    apple_touch_icon_filename = db.Column(db.String(500))
    apple_touch_icon_name = db.Column(db.String(100))
    # iOS / iPadOS "Add to Home Screen" icon + display name for the
    # public web frontend. Independent of the admin equivalents above.
    frontend_apple_touch_icon_filename = db.Column(db.String(500))
    frontend_apple_touch_icon_name = db.Column(db.String(100))
    # Site-wide design overrides — JSON map of token_key → override
    # value. Layered on top of the active theme's defaults (see
    # app/design.py). Empty / unset means use the theme's value.
    frontend_design_json = db.Column(db.Text)
    # Customizable public 404. Headline, subheadline, optional uploaded
    # illustration, and a CTA button label + URL. All optional —
    # sensible defaults are emitted by the public template when blank.
    frontend_404_heading = db.Column(db.String(200))
    frontend_404_subheading = db.Column(db.Text)
    frontend_404_cta_label = db.Column(db.String(120))
    frontend_404_cta_url = db.Column(db.String(500))
    frontend_404_image_filename = db.Column(db.String(500))
    # Public-facing web frontend
    # Module gate: when False, hides Web Frontend from the sidebar entirely,
    # blocks the admin editor routes, and the public homepage won't serve.
    frontend_module_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # Which Page renders at the public `/` root. Nullable for the brief
    # window between column add and the auto-seed running; in normal
    # operation always points at a Page row. The Pages admin surfaces a
    # "Make Homepage" action that writes this column, and the sidebar's
    # "Homepage" link routes to that page's edit screen.
    homepage_page_id = db.Column(db.Integer, db.ForeignKey('page.id', ondelete='SET NULL'),
                                  nullable=True, index=True)
    # Public visibility: when False (but module is enabled), signed-in editors
    # and admins can still preview while the public root redirects to login.
    frontend_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # ── Cookie & privacy compliance (managed from Web Frontend → Cookie Compliance) ──
    # Module gate. When False, no banner is rendered and the public site
    # behaves as it did before the feature existed.
    cookie_compliance_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Prompt behaviour. Trade-off ladder:
    #   notice  — informational banner ("we use cookies"), one button to dismiss
    #   consent — opt-in by default (Accept / Reject non-essential) with an
    #             explicit choice required before the banner disappears
    #   strict  — opt-in, AND non-essential cookies are blocked entirely until
    #             accept is clicked. Closest to GDPR Article 7 (informed,
    #             unambiguous, freely-given consent)
    cookie_compliance_mode = db.Column(db.String(16), nullable=False, default="notice")
    # When True, the server uses Accept-Language + CDN country headers to
    # auto-pick a mode per visitor — EU/UK → strict, California (where
    # detectable) → consent, else → the configured `cookie_compliance_mode`.
    # The admin's choice is the floor: auto can only escalate, never relax.
    cookie_compliance_auto_region = db.Column(db.Boolean, nullable=False, default=True)
    # Banner copy. Defaults filled in at first load so admins see a sensible
    # banner immediately even before they customise.
    cookie_compliance_title = db.Column(db.String(200))
    cookie_compliance_body = db.Column(db.Text)
    cookie_compliance_accept_label = db.Column(db.String(60))
    cookie_compliance_reject_label = db.Column(db.String(60))
    cookie_compliance_more_label = db.Column(db.String(60))
    # Where the banner anchors on screen. Values: bottom-bar (full-width
    # strip), bottom-left, bottom-right, modal (centered backdrop).
    cookie_compliance_position = db.Column(db.String(16), nullable=False, default="bottom-bar")
    # Privacy policy link. Either an internal Page (preferred — admin can
    # generate one with a click) or an external URL. Both nullable; the
    # banner just hides the "More info" link when neither is set.
    cookie_compliance_policy_page_id = db.Column(
        db.Integer, db.ForeignKey('page.id', ondelete='SET NULL'),
        nullable=True, index=True)
    cookie_compliance_policy_external_url = db.Column(db.String(500))
    # How long a remembered choice survives in the visitor's browser
    # before they're prompted again. Default 365 days — long enough to
    # respect their answer without violating common practice (most
    # jurisdictions recommend re-prompting at least once a year).
    cookie_compliance_remember_days = db.Column(db.Integer, nullable=False, default=365)
    # ── Frontend asset caching (managed from Web Frontend → Caching) ──
    # Master switch. When on, image/static responses get long-lived
    # public Cache-Control so returning visitors serve them straight from
    # the browser/Cloudflare cache instead of re-downloading every visit.
    # Freshness is handled by a cache-bust token (?v=) appended to asset
    # URLs — see app/imgcache.py — so changes still appear immediately.
    media_cache_enabled = db.Column(db.Boolean, nullable=False, default=True)
    # max-age (seconds) for images. Default 7 days.
    media_cache_max_age = db.Column(db.Integer, nullable=False, default=604800)
    # Add `immutable` to image responses (skip revalidation entirely until
    # the URL token changes). Safe because every cached image URL carries
    # the bust token.
    media_cache_immutable = db.Column(db.Boolean, nullable=False, default=True)
    # Also long-cache /static CSS/JS/font assets. These are busted by the
    # app build-id (changes on every deploy), so it's always safe.
    media_cache_static_assets = db.Column(db.Boolean, nullable=False, default=True)
    # max-age (seconds) for /static assets. Default 30 days.
    media_cache_static_max_age = db.Column(db.Integer, nullable=False, default=2592000)
    # Auto-advance the bust token whenever an image is uploaded/replaced so
    # visitors pick up the change without waiting for the cache to expire.
    media_cache_autobump = db.Column(db.Boolean, nullable=False, default=True)
    # Monotonic cache-bust counter. Appended as ?v= to image URLs; bumped
    # on image change (when autobump on) and by the "Clear cache" button.
    media_cache_version = db.Column(db.Integer, nullable=False, default=1)
    # When the admin last cleared the cache (manual bump). Display only.
    media_cache_cleared_at = db.Column(db.DateTime)
    frontend_title = db.Column(db.String(200))
    frontend_tagline = db.Column(db.String(500))
    frontend_tagline_enabled = db.Column(db.Boolean, nullable=False, default=True)
    frontend_hero_heading = db.Column(db.String(200))
    frontend_hero_subheading = db.Column(db.String(500))
    # Hero heading typography
    frontend_hero_heading_font = db.Column(db.String(32), nullable=False, default="fraunces")  # 'fraunces' | 'inter'
    frontend_hero_heading_size = db.Column(db.Integer, nullable=False, default=100)  # percent of default
    frontend_hero_heading_grad_start = db.Column(db.String(16))  # hex; None = theme default
    frontend_hero_heading_grad_end = db.Column(db.String(16))
    # Hero subheading typography — independent of the heading so admins
    # can mix-and-match (e.g. serif heading + sans-serif subheading,
    # different sizes, different colours). Subheading uses a single
    # solid colour rather than a gradient since the body of the
    # subheading is usually short enough that a gradient looks busy.
    # Defaults preserve the legacy look (Inter, 100%, theme muted).
    frontend_hero_subheading_font = db.Column(db.String(32), nullable=False, default="inter")  # 'fraunces' | 'inter'
    frontend_hero_subheading_size = db.Column(db.Integer, nullable=False, default=100)  # percent of default
    frontend_hero_subheading_color = db.Column(db.String(16))   # hex; None = theme default
    # When on, heading + subheading colors auto-derive from the chosen
    # background's lightness so text stays readable on dark or light bgs.
    frontend_hero_text_dynamic = db.Column(db.Boolean, nullable=False, default=False)
    # Hero background generator
    frontend_hero_bg_style = db.Column(db.String(16), nullable=False, default="frosty")  # frosty | solid | gradient | image
    frontend_hero_bg_color = db.Column(db.String(16))            # solid color, or gradient start
    frontend_hero_bg_color_2 = db.Column(db.String(16))          # gradient end
    frontend_hero_bg_gradient_angle = db.Column(db.Integer, nullable=False, default=180)
    frontend_hero_bg_hue = db.Column(db.Integer, nullable=False, default=225)     # frosty primary hue
    frontend_hero_bg_hue_2 = db.Column(db.Integer, nullable=False, default=170)   # frosty accent hue
    frontend_hero_bg_blur = db.Column(db.Integer, nullable=False, default=80)     # frosty blob blur px
    frontend_hero_bg_opacity = db.Column(db.Integer, nullable=False, default=45)  # 0-100 (frosty)
    frontend_hero_bg_randomize = db.Column(db.Boolean, nullable=False, default=False)
    frontend_hero_bg_image_filename = db.Column(db.String(500))
    frontend_hero_bg_image_mode = db.Column(db.String(16), nullable=False, default="cover")  # cover | tile
    frontend_hero_bg_image_scale = db.Column(db.Integer, nullable=False, default=100)       # percent
    # Video bg: muted, autoplay, object-fit: cover (no letterboxing).
    # Optional dynamic-background catalog key for the hero. When set
    # (and `frontend_hero_bg_style == 'dynamic'`), the hero renders the
    # matching `app/dynbg.py` preset behind the heading + CTA. Stored
    # separately from the bg-style picker so the admin can flip back
    # and forth between dynamic and the other modes without losing
    # their preset selection.
    frontend_hero_bg_dynamic_key = db.Column(db.String(64))
    frontend_hero_bg_video_filename = db.Column(db.String(500))
    frontend_hero_bg_video_mode = db.Column(db.String(16), nullable=False, default="loop")  # loop | bounce
    frontend_hero_bg_video_speed = db.Column(db.Integer, nullable=False, default=100)       # percent (50/100/150/200/300)
    # Sinewave: JSON-encoded list of 1–4 hex colors painted as an animated
    # multi-color gradient (same generator as the login screen background).
    frontend_hero_sinewave_colors = db.Column(db.Text)
    # Particle overlay (optional, layers on top of any bg style)
    frontend_hero_particle_enabled = db.Column(db.Boolean, nullable=False, default=False)
    frontend_hero_particle_effect = db.Column(db.String(32), nullable=False, default="stars")
    frontend_hero_particle_speed = db.Column(db.Integer, nullable=False, default=100)
    frontend_hero_particle_size = db.Column(db.Integer, nullable=False, default=100)
    # Vertical height of the hero block, in vh. 0 means "auto" — fall
    # back to the existing padding-derived height so installs that
    # never visit the field keep their current look. Two columns so
    # the admin can dial desktop and mobile separately (a single shared
    # value makes it hard to keep a tall poster-hero on desktop AND a
    # phone-friendly compact hero on mobile).
    frontend_hero_height_vh_desktop = db.Column(db.Integer, nullable=False, default=0)
    frontend_hero_height_vh_mobile = db.Column(db.Integer, nullable=False, default=0)
    frontend_about_heading = db.Column(db.String(200))
    frontend_about_body = db.Column(db.Text)
    frontend_contact_heading = db.Column(db.String(200))
    frontend_contact_body = db.Column(db.Text)
    frontend_footer_text = db.Column(db.Text)
    # Header layout
    frontend_header_width_mode = db.Column(db.String(16), nullable=False, default="boxed")  # 'boxed' | 'full'
    frontend_header_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_header_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_header_height = db.Column(db.Integer, nullable=False, default=72)
    frontend_header_template = db.Column(db.String(64), nullable=False, default="classic")
    frontend_footer_template = db.Column(db.String(64), nullable=False, default="classic")
    frontend_homepage_template = db.Column(db.String(64), nullable=False, default="classic")
    frontend_megamenu_template = db.Column(db.String(64), nullable=False, default="recovery-blue")
    # Reusable templates for entity-detail pages. Unlike layouts (which are
    # tied to a specific page slug), these apply to every meeting / every
    # event detail page rendered from dynamic content. Pickers live on the
    # admin's "Templates" page.
    frontend_meeting_template = db.Column(db.String(64), nullable=False, default="classic")
    # Picks the layout for the public /meetings list page (filter sidebar
    # vs directory toolbar vs week-grid). See MEETINGS_LIST_TEMPLATES in
    # app/frontend.py for the catalog.
    frontend_meetings_list_template = db.Column(db.String(64), nullable=False, default="sidebar")
    # Picks the layout for the public /events list page (cards / calendar
    # / timeline / magazine). See EVENTS_LIST_TEMPLATES.
    frontend_events_list_template = db.Column(db.String(64), nullable=False, default="cards")
    frontend_events_list_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_events_list_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_events_list_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_events_list_heading = db.Column(db.String(200))
    frontend_events_list_subheading = db.Column(db.String(500))
    # Picks the layout for the public /announcements page. See
    # ANNOUNCEMENTS_LIST_TEMPLATES in app/frontend.py for the catalog.
    frontend_announcements_list_template = db.Column(db.String(64), nullable=False, default="omni")
    frontend_announcements_list_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_announcements_list_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_announcements_list_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_announcements_list_heading = db.Column(db.String(200))
    frontend_announcements_list_subheading = db.Column(db.String(500))
    # Archive (/archive) — layout picker + pagination strategy + initial
    # page size for the unified past-events + archived-announcements list.
    # `frontend_archive_template` chooses one of ARCHIVE_TEMPLATES
    # (year-sidebar / timeline / compact-list / magazine). Pagination
    # mode is 'infinite' (load next page_size cards on scroll-to-end) or
    # 'numbered' (page_size at a time with bottom-of-list page links).
    frontend_archive_template = db.Column(db.String(64), nullable=False, default="year-sidebar")
    frontend_archive_pagination_mode = db.Column(db.String(16), nullable=False, default="infinite")
    frontend_archive_page_size = db.Column(db.Integer, nullable=False, default=20)
    frontend_archive_bg_dynamic_key = db.Column(db.String(64))
    frontend_archive_bg_dynbg_config_json = db.Column(db.Text)
    # Fellowships Index (/fellowships) — public list of peer recovery
    # fellowships the admin curates from Settings → Global. Mirrors the
    # archive / library list shape: layout picker, container width
    # controls, optional heading + subheading, dynbg, and a default
    # client-side sort mode (name-asc / name-desc / country-asc).
    frontend_fellowships_enabled = db.Column(db.Boolean, nullable=False, default=False)
    frontend_fellowships_list_template = db.Column(db.String(64), nullable=False, default="sidebar")
    frontend_fellowships_list_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_fellowships_list_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_fellowships_list_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_fellowships_list_heading = db.Column(db.String(200))
    frontend_fellowships_list_subheading = db.Column(db.String(500))
    frontend_fellowships_list_sort_mode = db.Column(db.String(32), nullable=False, default="name-asc")
    frontend_fellowships_list_bg_dynamic_key = db.Column(db.String(64))
    frontend_fellowships_list_bg_dynbg_config_json = db.Column(db.Text)
    # Stories module — recovery-story long-form posts at /stories and
    # /stories/<slug>. Toggle hides the admin entry + 404s the public
    # routes; required role gates who in the admin area can create /
    # edit them. List + detail templates pick the public layout.
    stories_enabled = db.Column(db.Boolean, nullable=False, default=False)
    stories_required_role = db.Column(db.String(32), nullable=False, default="admin")
    # Trusted Servants Email List — admin-managed contact roster + blast
    # email surface. The dashboard widget invites signed-in users to add
    # themselves; admins manage the roster and send updates from the
    # /email-list page. Disabled by default so existing installs
    # don't surface a new sidebar entry without an admin opting in.
    trusted_servants_enabled = db.Column(db.Boolean, nullable=False, default=False)
    trusted_servants_required_role = db.Column(db.String(32), nullable=False, default="admin")
    frontend_stories_list_template = db.Column(db.String(64), nullable=False, default="paper-stack")
    frontend_stories_list_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_stories_list_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_stories_list_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_stories_list_heading = db.Column(db.String(200))
    frontend_stories_list_subheading = db.Column(db.String(500))
    # Optional "Submit a story" CTA on the public stories-list page.
    # ``_form`` is an identifier resolved to a URL at render time:
    #   "" / NULL     → no button shown (default)
    #   "submission"  → registry form, /submissionform
    #   "contact"     → registry form, /contact
    #   "custom:<id>" → CustomForm row, URL is /<slug> resolved live
    # Stored as id (not URL) so slug renames on the CustomForm don't
    # silently break the link. ``_label`` is the visible button text;
    # defaults to "Share your story" in the public render when null.
    frontend_stories_list_submit_form = db.Column(db.String(64))
    frontend_stories_list_submit_label = db.Column(db.String(100))
    frontend_story_template = db.Column(db.String(64), nullable=False, default="paper")
    # Blog module — long-form editorial posts at /blog and /blog/<slug>.
    # Same module-toggle + required-role plumbing as Stories. List +
    # detail templates pick the public layout. Categories and tags
    # power per-blog filtering on the page-block so a single posts
    # table can serve many distinct frontend "blogs" (one per group
    # or committee).
    blog_enabled = db.Column(db.Boolean, nullable=False, default=False)
    blog_required_role = db.Column(db.String(32), nullable=False, default="admin")
    frontend_blog_list_template = db.Column(db.String(64), nullable=False, default="magazine")
    frontend_blog_list_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_blog_list_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_blog_list_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_blog_list_heading = db.Column(db.String(200))
    frontend_blog_list_subheading = db.Column(db.String(500))
    frontend_blog_post_template = db.Column(db.String(64), nullable=False, default="modern")
    # Container width controls for the blog detail page (`/blog/<slug>`).
    # Same shape as the blog-list controls above: `boxed` caps the
    # content at `max_width` pixels and centres it with viewport-%
    # gutters; `full` lets the content span the viewport. Defaults
    # match the list page so the two read as a pair.
    frontend_blog_post_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_blog_post_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_blog_post_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    frontend_blog_list_bg_dynamic_key = db.Column(db.String(64))
    frontend_blog_list_bg_dynbg_config_json = db.Column(db.Text)
    frontend_blog_post_bg_dynamic_key = db.Column(db.String(64))
    frontend_blog_post_bg_dynbg_config_json = db.Column(db.Text)
    # Printlist (/printlist) — printable schedule. Subheading sits under
    # the page title; website appears in the header band; page_size
    # drives both the @page CSS rule and the on-screen paper aspect.
    frontend_printlist_subheading = db.Column(db.String(500))
    frontend_printlist_website = db.Column(db.String(200))
    frontend_printlist_page_size = db.Column(db.String(16), nullable=False, default="letter")
    # Literature Library (/library) — public-facing index of every
    # public-marked Library + its public-marked items. Single layout
    # today; the column gives the picker a place to land if a second
    # layout is added later.
    frontend_literature_library_template = db.Column(db.String(64), nullable=False, default="classic")
    # Container width for the /meetings page: 'boxed' uses the max-width
    # below to cap the content column; 'full' spans the viewport with the
    # padding % below applied to each side as `Nvw` gutters.
    frontend_meetings_list_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    frontend_meetings_list_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_meetings_list_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    # Customisable title + subheading for the public /meetings page;
    # rendered above the filter rail on every layout. Empty defaults
    # fall back to the layout-supplied copy in the templates.
    frontend_meetings_list_heading = db.Column(db.String(200))
    frontend_meetings_list_subheading = db.Column(db.String(500))
    # Per-section dynamic-background keys. Each is an optional reference
    # into app/dynbg.py CATALOG; None = no dynamic backdrop. Stored as
    # flat columns (rather than via the per-template settings JSON
    # bucket) because each list/index page renders one layout at a time
    # and the dynbg should follow the page, not the layout variant.
    frontend_meetings_list_bg_dynamic_key = db.Column(db.String(64))
    frontend_events_list_bg_dynamic_key = db.Column(db.String(64))
    frontend_announcements_list_bg_dynamic_key = db.Column(db.String(64))
    frontend_stories_list_bg_dynamic_key = db.Column(db.String(64))
    frontend_story_bg_dynamic_key = db.Column(db.String(64))
    frontend_literature_library_bg_dynamic_key = db.Column(db.String(64))
    frontend_printlist_bg_dynamic_key = db.Column(db.String(64))
    # ── Site Index — auto-populated /siteindex page that lists every
    #     public page (custom Pages + Meetings + Events + Announcements
    #     + Stories + Library items). Each section is independently
    #     toggleable so a fellowship that doesn't use Stories can hide
    #     that group without touching the module flag. Sort mode is
    #     'grouped' (sections by type, alphabetical within) or 'alpha'
    #     (single A-Z list, no grouping).
    frontend_site_index_enabled = db.Column(db.Boolean, nullable=False, default=False)
    frontend_site_index_template = db.Column(db.String(64), nullable=False, default="grouped")
    frontend_site_index_heading = db.Column(db.String(200))
    frontend_site_index_subheading = db.Column(db.String(500))
    frontend_site_index_sort_mode = db.Column(db.String(32), nullable=False, default="grouped")
    frontend_site_index_show_pages = db.Column(db.Boolean, nullable=False, default=True)
    frontend_site_index_show_meetings = db.Column(db.Boolean, nullable=False, default=True)
    frontend_site_index_show_events = db.Column(db.Boolean, nullable=False, default=True)
    frontend_site_index_show_announcements = db.Column(db.Boolean, nullable=False, default=True)
    frontend_site_index_show_stories = db.Column(db.Boolean, nullable=False, default=True)
    frontend_site_index_show_library = db.Column(db.Boolean, nullable=False, default=True)
    frontend_site_index_bg_dynamic_key = db.Column(db.String(64))
    frontend_site_index_bg_dynbg_config_json = db.Column(db.Text)
    # Sibling JSON config for each of the dynbg keys above (overlay +
    # custom colours). Same shape as Page.bg_dynbg_config_json.
    frontend_meetings_list_bg_dynbg_config_json = db.Column(db.Text)
    frontend_events_list_bg_dynbg_config_json = db.Column(db.Text)
    frontend_announcements_list_bg_dynbg_config_json = db.Column(db.Text)
    frontend_stories_list_bg_dynbg_config_json = db.Column(db.Text)
    frontend_story_bg_dynbg_config_json = db.Column(db.Text)
    frontend_literature_library_bg_dynbg_config_json = db.Column(db.Text)
    frontend_printlist_bg_dynbg_config_json = db.Column(db.Text)
    frontend_hero_bg_dynbg_config_json = db.Column(db.Text)
    # "Pro Tips" FAQ-style section rendered at the bottom of /meetings.
    # JSON blob with: enabled, heading, subheading, icon, icon_color,
    # bg_color, items[]. NULL = use defaults from
    # `meetings_list_protips_defaults()` in app/frontend.py.
    frontend_meetings_list_protips_json = db.Column(db.Text)
    # Admin-curated custom links rendered in the Sidebar template's
    # day-filter rail (below the days, under a divider). JSON list of
    # {label, url, link_type: "internal"|"external", open_in_new_tab}.
    # NULL / empty = no extra links. Resolved by
    # `meetings_list_sidebar_links_resolved()` in app/frontend.py.
    frontend_meetings_list_sidebar_links_json = db.Column(db.Text)
    frontend_event_template = db.Column(db.String(64), nullable=False, default="classic")
    # Per-template appearance overrides. JSON dict keyed by content type +
    # template key, e.g. {"meeting": {"card_stack": {"bg": "#fff", ...}}}.
    # Each leaf dict allows: bg (hex), heading_font (font key), body_font
    # (font key), heading_size (int %), body_size (int %).
    frontend_template_settings_json = db.Column(db.Text)
    # Global visual theme — applies to every section. The per-section
    # template_* fields above act as overrides when the user picks a layout
    # different from the active theme on a specific page.
    frontend_theme = db.Column(db.String(64), nullable=False, default="classic")
    # Per-theme saved state. JSON map of theme_key -> snapshot of the
    # theme-stateful SiteSetting fields (design tokens, fonts, default mode,
    # per-template settings, mega-menu colours). On theme switch the outgoing
    # theme's state is snapshotted here and the incoming theme's saved state
    # restored, so returning to a theme brings back how it was left. The
    # theme switcher modal exposes Reset-to-default and Return-to-last-state.
    frontend_theme_states_json = db.Column(db.Text)
    # Default appearance mode for first-time visitors: 'light', 'dark',
    # or 'system' (follows the visitor's OS preference). A returning
    # visitor's localStorage choice always wins over this default.
    frontend_default_theme = db.Column(db.String(16), nullable=False, default="system")
    # Footer container dimensions — mirrors header_width_mode pattern.
    frontend_footer_width_mode = db.Column(db.String(16), nullable=False, default="boxed")  # 'boxed' | 'full'
    frontend_footer_max_width = db.Column(db.Integer, nullable=False, default=1160)
    frontend_footer_padding_pct = db.Column(db.Integer, nullable=False, default=5)
    # Structured footer content. JSON-encoded dict of:
    #   {brand: {show: bool, show_logo: bool, tagline: str},
    #    columns: [{title, links: [{label, url, open_in_new_tab}]}],
    #    social:  [{icon, label, url}],   // small icon row
    #    secondary_nav: [{label, url}],   // optional bottom-row legal links
    #    copyright: str}                   // markdown supported
    frontend_footer_blocks_json = db.Column(db.Text)
    # Brand-block custom logo for the public footer. The brand block can
    # use either the header logo (`frontend_logo_filename`) or this
    # dedicated custom logo, toggled via the brand-block's `logo_source`
    # field stored inside `frontend_footer_blocks_json`.
    frontend_brand_logo_filename = db.Column(db.String(500))
    # Footer background mode. 'dark' (default) → footer always renders
    # against the dark palette regardless of the page-level light/dark
    # theme. 'light' → footer follows the page theme (light when page is
    # in light mode, dark when page is in dark mode). Picked from the
    # Footer admin's Background section.
    frontend_footer_bg_mode = db.Column(db.String(16), nullable=False, default="dark")
    # Minimum footer height in vh — admin-tunable so the footer can be a
    # punchy full-bleed band (e.g. 50vh) or stay tight to its content
    # (default 0 = no min-height; just whatever the content needs).
    frontend_footer_min_height_vh = db.Column(db.Integer, nullable=False, default=0)
    # Footer text scaling (50-200%) — desktop-first; child rules use
    # `em` so descendants automatically inherit the scaled base size.
    # Mobile media queries cap how high the scale can climb so a
    # 200% desktop setting doesn't blow out a phone viewport.
    frontend_footer_font_scale = db.Column(db.Integer, nullable=False, default=100)
    # Per-section font overrides. JSON dict like
    # {"display": "fraunces", "heading": "inter", "body": "inter"}.
    # Empty / missing keys fall back to the active theme's defaults.
    frontend_fonts_json = db.Column(db.Text)
    # Per-block content for the homepage builder. JSON-encoded dict:
    # { "features": [{icon,title,body}], "cta": {...}, "stats": [...],
    #   "testimonials": [...], "faq": [...], "quick_links": [...] }
    # Each block partial reads its own key with sensible defaults if blank.
    frontend_blocks_json = db.Column(db.Text)
    # Mega menu appearance
    frontend_mega_bg_color = db.Column(db.String(16), nullable=False, default="#0B5CFF")
    frontend_mega_text_color = db.Column(db.String(16), nullable=False, default="#ffffff")
    frontend_mega_radius_bl = db.Column(db.Integer, nullable=False, default=18)
    frontend_mega_radius_br = db.Column(db.Integer, nullable=False, default=18)
    # Optional dynamic background for the mega-menu panel (same dynbg system as
    # the hero / pages). When a key is set, the panel renders the animated
    # backdrop behind its links and the solid bg-colour above steps aside.
    frontend_mega_bg_dynamic_key = db.Column(db.String(64))
    frontend_mega_bg_dynbg_config_json = db.Column(db.Text)
    # Render the mega-menu dynamic background in its dark variant even when the
    # site is in light mode (so a dark panel sits behind light mega-menu text).
    frontend_mega_bg_dynbg_dark = db.Column(db.Boolean, nullable=False, default=False)
    # Independent dark-mode mega-menu colours. When unset, the renderer falls
    # back to a sensible dark surface + the auto dark_variant of the light text.
    frontend_mega_bg_color_dark = db.Column(db.String(16))
    frontend_mega_text_color_dark = db.Column(db.String(16))
    # Blend between the solid background colour (0) and the dynamic background
    # (100). Implemented as the dynbg layer's opacity over the solid colour, so
    # the admin can dial the effect from "just the colour" to "just the dynbg".
    frontend_mega_bg_dynbg_blend = db.Column(db.Integer, nullable=False, default=100)
    # Staggered reveal animation when the mega menu opens (titles/links/buttons
    # fade in one after the other with a small slide + rotate).
    frontend_megamenu_animate = db.Column(db.Boolean, nullable=False, default=True)
    # Duration of each block's reveal animation, in milliseconds.
    frontend_megamenu_animate_ms = db.Column(db.Integer, nullable=False, default=320)
    # Panel-level fade-in when the menu opens on hover. Independent
    # from the staggered link reveal above — admins can pair a
    # snappy panel show with a slow link stagger, or vice versa.
    # When False, the panel snaps in/out without a transition.
    frontend_megamenu_panel_fade = db.Column(db.Boolean, nullable=False, default=True)
    # Duration of the panel's opacity + slide-in transition, in
    # milliseconds. Reads through `--fe-mm-fade-ms` on the panel.
    frontend_megamenu_panel_fade_ms = db.Column(db.Integer, nullable=False, default=180)
    # Mobile-only overrides (apply under the @media (max-width: 720px)
    # breakpoint the rest of the megamenu styling uses). The animate
    # toggle lets admins suppress the staggered-link entrance on phones
    # where the choreography reads as jitter; the two _ms columns
    # carry independent speeds for the panel fade and link stagger so
    # the desktop tuning stays untouched. NULL on either _ms column
    # would fall through to the desktop value; storing NOT NULL +
    # default keeps the renderer logic simple.
    frontend_megamenu_animate_mobile = db.Column(db.Boolean, nullable=False, default=True)
    frontend_megamenu_animate_mobile_ms = db.Column(db.Integer, nullable=False, default=320)
    frontend_megamenu_panel_fade_mobile_ms = db.Column(db.Integer, nullable=False, default=180)
    # Optional size overrides for the mega-menu block-title heading and
    # the link rows below it, expressed as integer percentages where
    # 100 = the theme's baked default. Sliders run 50 – 200 (half-size
    # to double-size) with 100 in the middle. Nullable: when unset (or
    # set to exactly 100) the CSS falls back to each theme's baked
    # base — Recovery Blue's 2 rem heading + 1.2 rem link, Classic's
    # 0.875 rem heading + 0.9375 rem link — multiplied by 1.
    frontend_megamenu_heading_size = db.Column(db.Integer)
    frontend_megamenu_subheading_size = db.Column(db.Integer)
    frontend_logo_filename = db.Column(db.String(500))
    frontend_logo_width = db.Column(db.Integer, nullable=False, default=40)
    # Utility bar (above header). Sits at the very top of every public
    # page. ``utility_bar_left_json`` / ``utility_bar_right_json`` each
    # hold an ordered list of items: {kind: 'link'|'button'|'text'|'icon',
    # label, url, icon, open_in_new_tab}. Kind 'icon' renders just the
    # icon glyph; 'text' is plain text; 'link' is a styled anchor; and
    # 'button' is a pill button. ``utility_bar_enabled`` is a hard
    # off-switch — when False the bar is hidden site-wide regardless of
    # other settings. ``utility_bar_live_meetings`` toggles the centre
    # live-meeting badge — when a hybrid/online meeting is currently
    # running, the bar turns yellow and surfaces a Join button.
    utility_bar_enabled = db.Column(db.Boolean, nullable=False, default=True)
    utility_bar_bg_color = db.Column(db.String(16))
    utility_bar_text_color = db.Column(db.String(16))
    utility_bar_left_json = db.Column(db.Text)
    utility_bar_right_json = db.Column(db.Text)
    utility_bar_live_meetings = db.Column(db.Boolean, nullable=False, default=False)
    # Which item shows by default on mobile when the bar collapses to a
    # horizontal swipe strip. Format: "<side>:<index>" where side is
    # 'left' or 'right' and index is 0-based within that side's list
    # (e.g. 'right:0' for the first right-side item). Empty string =
    # let the renderer default to the first available item. When the
    # live-meeting bar is showing it always pins to the top of the
    # mobile bar regardless of this setting.
    utility_bar_mobile_default = db.Column(db.String(32))
    # Under-header alert bar
    header_alert_enabled = db.Column(db.Boolean, nullable=False, default=False)
    header_alert_message = db.Column(db.Text)
    header_alert_bg_color = db.Column(db.String(16))
    header_alert_text_color = db.Column(db.String(16))
    header_alert_icon = db.Column(db.String(32))
    header_alert_icon_position = db.Column(db.String(8), nullable=False, default="before")
    setup_complete = db.Column(db.Boolean, nullable=False, default=False)
    # IANA timezone name (e.g. "America/Los_Angeles"). Used to resolve
    # "today" / "now" for meetings display and other time-dependent
    # rendering, so what the server thinks is "right now" matches the
    # fellowship's wall clock regardless of where the host runs.
    timezone = db.Column(db.String(64), nullable=False, default="UTC")

    # ── Contact form (public /contact page) ────────────────────────
    # Independent of the existing /submissionform (which collects
    # announcements + events). The contact form is a generic "get in
    # touch" page whose submissions email the public information chair
    # and land in the admin's Contact Form section. Turnstile is
    # reused from the site-wide settings above.
    contact_form_enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Recipient(s) — comma-separated. Falls back to pic_email then
    # access_request_to so a fresh install still routes mail somewhere
    # sensible. The form's reply-to header is set to the visitor's
    # address so admins can reply directly from their inbox.
    contact_form_to = db.Column(db.String(500))
    contact_form_heading = db.Column(db.String(200))
    contact_form_subheading = db.Column(db.String(500))
    contact_form_intro = db.Column(db.Text)
    contact_form_success_message = db.Column(db.String(500))
    contact_form_submit_label = db.Column(db.String(100))
    contact_form_subject_required = db.Column(db.Boolean, nullable=False, default=False)
    contact_form_show_phone = db.Column(db.Boolean, nullable=False, default=True)
    contact_form_blocks_json = db.Column(db.Text)
    contact_form_slug = db.Column(db.String(120))
    # Per-channel toggles for the PIC contact panel rendered on the
    # /contact page aside. Each channel is shown only when (a) the
    # underlying SiteSetting field is populated AND (b) the matching
    # toggle below is on. Lets admins surface email-only / name-only
    # combinations without having to clear the dashboard PIC fields
    # they still want to use elsewhere in the portal.
    contact_form_show_pic_name = db.Column(db.Boolean, nullable=False, default=True)
    contact_form_show_pic_email = db.Column(db.Boolean, nullable=False, default=True)
    contact_form_show_pic_phone = db.Column(db.Boolean, nullable=False, default=True)

    # Container width for the public /contact page. Mirrors the same
    # boxed/full + max-width + side-padding shape every other list /
    # detail surface uses (events_list, announcements_list, etc.).
    # 'boxed' caps content at `max_width` px and centers; 'full' spans
    # the viewport with `padding_pct` % vw gutters.
    contact_form_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    contact_form_max_width = db.Column(db.Integer, nullable=False, default=1160)
    contact_form_padding_pct = db.Column(db.Integer, nullable=False, default=5)

    # ── Recovery Contacts module (public /contactlist page) ─────────────────
    # A public directory of names + phone/email that visitors submit
    # themselves; entries stay hidden until an admin approves them.
    # Module toggle + role gate mirror the other module pairs (Stories,
    # Blog, Trusted Servants). The page-config columns below drive the
    # public page chrome; per-entry rows live in ``RecoveryContact``.
    # Turnstile + the hidden honeypot guard the public submission form.
    recovery_contacts_enabled = db.Column(db.Boolean, nullable=False, default=False)
    recovery_contacts_required_role = db.Column(db.String(32), nullable=False, default="admin")
    recovery_contacts_heading = db.Column(db.String(200))
    recovery_contacts_subheading = db.Column(db.String(500))
    recovery_contacts_intro = db.Column(db.Text)
    recovery_contacts_success_message = db.Column(db.String(500))
    recovery_contacts_submit_label = db.Column(db.String(100))
    # Optional recipient(s) emailed when a new entry is submitted —
    # comma-separated, falls back to ``access_request_to`` so the admin
    # gets a heads-up that something's waiting to be approved.
    recovery_contacts_to = db.Column(db.String(500))
    # Admin email-alert toggles. New submissions always surface as a chip
    # in the admin panel; these decide whether an email is *also* sent.
    # ``email_alerts`` covers new entries + update requests; removal
    # alerts fire only after the submitter confirms via the emailed link.
    # Both default off so the portal stays quiet unless the admin opts in.
    recovery_contacts_email_alerts = db.Column(db.Boolean, nullable=False, default=False)
    recovery_contacts_removal_alerts = db.Column(db.Boolean, nullable=False, default=False)
    # Container width — same boxed/full + max-width + side-padding shape
    # every other public list surface uses (contact_form, events_list…).
    recovery_contacts_width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    recovery_contacts_max_width = db.Column(db.Integer, nullable=False, default=1160)
    recovery_contacts_padding_pct = db.Column(db.Integer, nullable=False, default=5)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IntergroupAccount(db.Model):
    __tablename__ = "intergroup_account"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class IntergroupOfficer(db.Model):
    """Repeatable contact rows surfaced under Settings → Global. Distinct
    from `IntergroupAccount` (which stores email-account credentials for
    the legacy /intergroupemail tooling): officer rows are public-facing
    contact metadata — position / name / phone / email — that admins
    edit through the Global tab and that page blocks pull at render time
    via the `intergroup_member` block. Stored separately so changes to
    the officer roster don't churn IMAP credentials and vice versa.
    """
    __tablename__ = "intergroup_officer"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(200), nullable=False)   # position name, e.g. "Chair"
    name = db.Column(db.String(200))
    phone = db.Column(db.String(64))
    email = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Fellowship(db.Model):
    """A single entry in the Fellowships Index — a peer recovery
    fellowship the admin chooses to surface to visitors (CMA, AA, NA,
    OA, etc.). Each row is either fully virtual (online-only, no
    geography) or regional (carries a country + state/province/region).
    Rendered publicly at /fellowships through a templates-page-picked
    layout and edited from Settings → Global as a repeatable row table.
    """
    __tablename__ = "fellowship"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    # True = virtual / online-only fellowship (country + state_region
    # ignored). False = regional / geography-bound.
    is_virtual = db.Column(db.Boolean, nullable=False, default=False)
    country = db.Column(db.String(120))           # display-only string
    state_region = db.Column(db.String(120))      # state / province / region — display-only
    url = db.Column(db.String(500))               # fellowship's public website
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ZoomOtpEmail(db.Model):
    """Singleton: credentials for the shared email inbox that receives Zoom OTP codes."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255))
    password_enc = db.Column(db.LargeBinary)
    login_url = db.Column(db.String(1000))
    # IMAP mailbox settings — let the app log in and pull OTP codes
    # directly instead of the user opening webmail. The IMAP login can
    # differ from the human-facing `email`/`password` (e.g. an app
    # password or a service login), so they're stored separately; when
    # blank, the fetcher falls back to `email` / `password_enc`.
    imap_host = db.Column(db.String(255))
    imap_port = db.Column(db.Integer, default=993)
    imap_ssl = db.Column(db.Boolean, nullable=False, default=True)
    imap_username = db.Column(db.String(255))
    imap_password_enc = db.Column(db.LargeBinary)
    imap_mailbox = db.Column(db.String(128), default="INBOX")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ZoomAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False, unique=True)
    username = db.Column(db.String(255), nullable=False)
    password_enc = db.Column(db.LargeBinary, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MeetingFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False)
    category = db.Column(db.String(32), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(1000))
    stored_filename = db.Column(db.String(500))
    original_filename = db.Column(db.String(500))
    body = db.Column(db.Text)
    position = db.Column(db.Integer, nullable=False, default=0)
    # Whether this file/link is shown on the public meeting detail page.
    # Off by default — admins explicitly opt files in via the meeting edit
    # screen. Each row toggles independently.
    public_visible = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def url_slug(self):
        """URL-safe display name for the public route. The route looks up
        by id, so this slug is purely decorative — but having it in the URL
        gives visitors a meaningful filename when they hover/right-click
        instead of just an opaque number."""
        from .colors import slugify
        if self.original_filename:
            # Preserve the extension when present so PDFs land as .pdf etc.
            name, dot, ext = self.original_filename.rpartition(".")
            if dot and ext and 1 <= len(ext) <= 10 and name:
                return f"{slugify(name)}.{slugify(ext)}"
        return slugify(self.title)


class MediaItem(db.Model):
    __tablename__ = "media_item"
    id = db.Column(db.Integer, primary_key=True)
    stored_filename = db.Column(db.String(500), nullable=False, unique=True)
    original_filename = db.Column(db.String(500), nullable=False)
    content_hash = db.Column(db.String(64), index=True)
    size_bytes = db.Column(db.Integer, default=0)
    mime_type = db.Column(db.String(128))
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploader = db.relationship("User", foreign_keys=[uploaded_by])


class Library(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text)
    alert_message = db.Column(db.Text)
    # Marks the library as Intergroup-restricted: edit access is limited
    # to admins + the ``intergroup_member`` role, the row is hidden from
    # the generic /libraries list, and it appears in the Intergroup
    # sidebar subsection. Toggling this flag is admin-only.
    is_intergroup = db.Column(db.Boolean, nullable=False, default=False)
    # Whole-library opt-in for the public Literature Library page
    # (/library). When True, this library and its items become eligible
    # to render on the public page; per-item visibility is then
    # controlled via ``LibraryItem.public_visible``. When False, the
    # library is invisible to the public page regardless of any
    # individual item flags.
    public_visible = db.Column(db.Boolean, nullable=False, default=False)
    # When True, uploads to this library must pick at least one
    # ``LibraryCategory``; when False, categories are still selectable
    # but optional. Surfaced on the library-edit modal as a toggle. Only
    # consulted on Intergroup libraries today, but the column is kept
    # general so non-Intergroup libraries can opt in later.
    categories_required = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("LibraryItem", backref="library", cascade="all, delete-orphan",
                            lazy="dynamic", order_by="LibraryItem.position, LibraryItem.id")

    @property
    def public_slug(self):
        """Slug-form name used in URLs. Same shape as ``Meeting.public_slug``
        — derived live from ``name`` so renaming a library moves its
        canonical URL automatically (no slug column, no history table)."""
        from .colors import slugify
        return slugify(self.name)
    meeting_assocs = db.relationship("MeetingLibrary", back_populates="library",
                                     cascade="all, delete-orphan")
    meetings = association_proxy("meeting_assocs", "meeting",
                                 creator=lambda m: MeetingLibrary(meeting=m))
    categories = db.relationship("LibraryCategory", back_populates="library",
                                 cascade="all, delete-orphan",
                                 order_by="LibraryCategory.position, LibraryCategory.id")


class LibraryCategory(db.Model):
    """Per-library tag definition. Admins manage the list on Intergroup
    libraries via the library-edit modal; uploads in those libraries
    must pick at least one category. Categories are scoped to a single
    library (no cross-library reuse) so renames don't ripple."""
    __tablename__ = "library_category"
    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey("library.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    library = db.relationship("Library", back_populates="categories")
    items = db.relationship("LibraryItem", secondary=reading_categories,
                            back_populates="categories")

    __table_args__ = (
        db.UniqueConstraint("library_id", "name", name="uq_library_category_name"),
    )


class AccessRequest(db.Model):
    __tablename__ = "access_request"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    roles_json = db.Column(db.Text)  # JSON array of selected role labels
    meeting_name = db.Column(db.String(255))
    status = db.Column(db.String(16), nullable=False, default="pending")  # pending|handled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    handled_at = db.Column(db.DateTime)
    # Soft-archive flag: handled rows that the admin no longer wants
    # cluttering the active list flip to archived. Independent of
    # status — an archived row keeps its handled/pending state for
    # historical context. Browse the archive via ?view=archived.
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    archived_at = db.Column(db.DateTime)

    @property
    def roles(self):
        """Decoded list of role labels for template rendering. Pure
        read-only property so the rendering path can't accidentally
        mutate the SQLAlchemy instance — earlier code assigned
        ``r.roles = json.loads(...)`` inside the view loop, which is
        functionally fine but conceptually fragile. A property keeps
        the decode in one place and makes the row immutable to the
        rendering layer."""
        import json as _json
        try:
            data = _json.loads(self.roles_json or "[]")
        except (ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []


class ContactSubmission(db.Model):
    """A single contact-form submission from the public /contact page.

    Email goes out to the public information chair at submission time
    with reply-to set to the visitor's email so the admin can reply
    straight from their inbox; the row persists here for audit / when
    the SMTP delivery fails. Mirrors AccessRequest's read/archive
    pattern so the admin UX stays consistent."""
    __tablename__ = "contact_submission"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(64))
    subject = db.Column(db.String(255))
    message = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.String(64))
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    archived_at = db.Column(db.DateTime)
    email_sent = db.Column(db.Boolean, nullable=False, default=False)
    email_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RecoveryContact(db.Model):
    """A single entry on the public Recovery Contacts directory.

    Visitors submit their name plus a phone number and/or email via the
    public ``/contactlist`` page. New rows land with ``approved=False`` and
    are invisible to the public until an admin approves them from the
    Recovery Contacts admin section. ``name`` always renders on the public list;
    ``show_phone`` / ``show_email`` give per-entry granular control over
    whether the phone, the email, or both are displayed — the submitter
    picks a starting preference on the form and the admin can override
    either one at any time. Mirrors ``ContactSubmission``'s audit shape
    (ip_address + created_at) plus an ``approved_at`` stamp."""
    __tablename__ = "recovery_contact"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    # Per-entry public display gates. Name is always shown; these decide
    # whether the matching contact field renders on the public list.
    show_phone = db.Column(db.Boolean, nullable=False, default=True)
    show_email = db.Column(db.Boolean, nullable=False, default=True)
    # When True, the entry advertises that the person is open to
    # sponsoring. Set on the public form (a checkbox) and editable by the
    # admin; rendered as a badge on the public list. No separate show
    # toggle — it's a yes/no attribute rather than contact info.
    available_to_sponsor = db.Column(db.Boolean, nullable=False, default=False)
    # "Contact me through the site" opt-in. When True (and an email is on
    # file), a Contact button shows on the public list; the visitor's
    # message is relayed to ``email`` server-side with Reply-To set to the
    # sender, so the address is never exposed. Lets people who hide their
    # phone/email stay reachable. ``contact_count`` tracks how many times
    # they've been contacted this way (shown as a chip in the admin).
    contact_enabled = db.Column(db.Boolean, nullable=False, default=False)
    contact_count = db.Column(db.Integer, nullable=False, default=0)
    # Approval workflow. False = pending review (hidden from public);
    # True = approved (rendered on the public directory).
    approved = db.Column(db.Boolean, nullable=False, default=False)
    # Update-request workflow. When the submitter ticks "I'm updating my
    # existing entry" on the public form, ``wants_update`` is set and the
    # submit handler cross-references the directory by email/phone. If a
    # match is found, ``matched_entry_id`` points at the existing
    # (approved) entry so the admin sees the submission is *both* a new
    # row AND a proposed update to an existing one, and can apply it.
    wants_update = db.Column(db.Boolean, nullable=False, default=False)
    # Set when the submitter ticks "Remove me from the list" — a pending
    # request (matched to the existing entry by name) that an admin
    # actions by deleting the matched entry. A confirmation email is sent
    # to the submitter when the request is filed.
    wants_removal = db.Column(db.Boolean, nullable=False, default=False)
    # Double opt-in for BOTH update and removal requests (kept on these
    # legacy ``removal_*`` columns). The token powers the confirmation
    # link emailed to the submitter; clicking it auto-applies the change
    # (update overwrites the matched entry / removal deletes it) — no
    # admin approval. ``removal_confirmed_at`` is stamped at that point.
    # Until then the request shows in the admin panel so an admin can
    # apply it by hand if the person never confirms.
    removal_token = db.Column(db.String(64))
    removal_confirmed_at = db.Column(db.DateTime)
    matched_entry_id = db.Column(db.Integer,
                                 db.ForeignKey("recovery_contact.id", ondelete="SET NULL"))
    # Admin-only note (e.g. why an entry was held). Never public.
    note = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)
    # Anti-abuse on the self-service update/removal flow.
    #  • ``last_update_request_at`` stamps when an update request was last
    #    filed against this listing; the public form rejects a second update
    #    within 24 h (and flags it) so a malicious actor can't spam the
    #    listing owner with confirmation emails.
    #  • ``requests_locked_until`` is set 7 days out when the listing owner
    #    clicks "I didn't submit this" in a confirmation email — while it's
    #    in the future the form refuses any update OR removal request for
    #    this listing.
    last_update_request_at = db.Column(db.DateTime)
    requests_locked_until = db.Column(db.DateTime)

    # Self-referential link to the existing entry a pending update matched.
    matched_entry = db.relationship("RecoveryContact", remote_side=[id],
                                    foreign_keys=[matched_entry_id])

    @property
    def public_phone(self):
        """Phone number to render publicly, or None when the entry has
        no phone or the admin hid it."""
        return self.phone if (self.phone and self.show_phone) else None

    @property
    def public_email(self):
        """Email to render publicly, or None when the entry has no email
        or the admin hid it."""
        return self.email if (self.email and self.show_email) else None


class RecoveryContactLog(db.Model):
    """Audit trail for the Recovery Contacts module: public submissions,
    update/removal requests + their confirmation emails, the email-link
    confirmations, relayed "Contact me" messages, and admin actions
    (approve, edit, apply, remove, …). ``entry_name`` is a snapshot so the
    log stays readable after the underlying entry is deleted."""
    __tablename__ = "recovery_contact_log"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    event = db.Column(db.String(40), nullable=False)   # machine key (drives the icon/colour)
    message = db.Column(db.Text, nullable=False)        # human-readable line
    entry_name = db.Column(db.String(200))             # snapshot of who it concerns
    actor = db.Column(db.String(120))                  # 'Visitor', 'admin: jdoe', 'System'
    ip_address = db.Column(db.String(64))


def log_recovery_contact(event, message, entry_name=None, actor=None, ip_address=None):
    """Append a Recovery Contacts audit-log row and commit. Best-effort —
    a logging failure must never break the action it's recording."""
    try:
        db.session.add(RecoveryContactLog(
            event=event, message=message,
            entry_name=(entry_name or None),
            actor=(actor or None),
            ip_address=(ip_address or None)))
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()


class RecoveryContactAbuse(db.Model):
    """A flagged, likely-malicious self-service request against a Recovery
    Contacts listing — surfaced in Watchtower so an admin can block the IP
    and deal with it. Two kinds:

      • ``rate_limited`` — a second update request hit the same listing
        within 24 h. The second request's data is discarded (not ingested).
      • ``disavowed``    — the listing owner clicked "I didn't submit this"
        in a confirmation email. The request is discarded and the listing
        is locked against further update/removal requests for 7 days
        (``locked_until`` snapshots that deadline).

    ``ip_address`` is the requestor's IP (the abuser), so the Watchtower
    panel can offer a one-click block. Repeat hits from the same kind +
    listing + IP bump ``attempt_count`` / ``last_attempt_at`` rather than
    piling up rows. ``resolved`` lets an admin clear it once handled."""
    __tablename__ = "recovery_contact_abuse"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    kind = db.Column(db.String(20), nullable=False)        # 'rate_limited' | 'disavowed'
    entry_id = db.Column(db.Integer,
                         db.ForeignKey("recovery_contact.id", ondelete="SET NULL"))
    entry_name = db.Column(db.String(200))                  # snapshot of the targeted listing
    entry_email = db.Column(db.String(255))                 # snapshot
    ip_address = db.Column(db.String(64))                   # requestor (abuser) IP
    detail = db.Column(db.Text)                             # human-readable line
    attempt_count = db.Column(db.Integer, nullable=False, default=1)
    last_attempt_at = db.Column(db.DateTime, default=datetime.utcnow)
    locked_until = db.Column(db.DateTime)                   # set for 'disavowed'
    resolved = db.Column(db.Boolean, nullable=False, default=False, index=True)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))


def record_recovery_contact_abuse(kind, entry, ip_address, detail, locked_until=None):
    """Record (or bump) a Recovery Contacts abuse flag and commit. If an
    unresolved row of the same ``kind`` already exists for this listing +
    IP, increment its ``attempt_count`` instead of adding a duplicate.
    Returns the row, or None on failure (best-effort — never raises)."""
    try:
        name = getattr(entry, "name", None)
        email = getattr(entry, "email", None)
        eid = getattr(entry, "id", None)
        now = datetime.utcnow()
        row = (RecoveryContactAbuse.query
               .filter_by(kind=kind, entry_id=eid, ip_address=ip_address,
                          resolved=False)
               .first()) if eid is not None else None
        if row is not None:
            row.attempt_count = (row.attempt_count or 1) + 1
            row.last_attempt_at = now
            row.detail = detail or row.detail
            if locked_until is not None:
                row.locked_until = locked_until
        else:
            row = RecoveryContactAbuse(
                kind=kind, entry_id=eid, entry_name=name, entry_email=email,
                ip_address=ip_address, detail=detail,
                attempt_count=1, last_attempt_at=now, locked_until=locked_until)
            db.session.add(row)
        db.session.commit()
        return row
    except Exception:  # noqa: BLE001
        db.session.rollback()
        return None


class NotificationDismissal(db.Model):
    """Per-user record that a derived notification has been cleared.

    The Notifications Center derives its items from live attention state
    (pending access requests, locked accounts, unread contact messages,
    submissions awaiting review) rather than from stored notification
    rows — so there's no event plumbing to maintain and items can never
    go stale. The only thing we persist is each user's *dismissals*,
    keyed by a stable string like ``access_request:42`` or
    ``locked_account:jdoe``. "Uncleared" = current attention items the
    user hasn't dismissed; clearing one inserts a row here. A dismissal
    whose underlying item later resolves is pruned, so if the same key
    recurs (e.g. an account locks again) it surfaces fresh."""
    __tablename__ = "notification_dismissal"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    key = db.Column(db.String(128), nullable=False)
    dismissed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint("user_id", "key", name="uq_notif_dismissal_user_key"),
    )


class WpFieldMapping(db.Model):
    """Reusable WordPress-importer custom-field → post-type mapping,
    keyed by source so re-importing the same site auto-loads the last
    mapping. ``site_key`` is ``rest:<host>`` for a REST connection or the
    sentinel ``csv`` for CSV uploads. ``mapping_json`` is the wizard's
    ``{target: {dest_field: wp_field_key}}`` dict. Editable every run —
    this is just the remembered default."""
    __tablename__ = "wp_field_mapping"
    id = db.Column(db.Integer, primary_key=True)
    site_key = db.Column(db.String(255), nullable=False, unique=True, index=True)
    mapping_json = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)


class LibraryItem(db.Model):
    """A single file / link / pasted-body entry inside a Library.

    Renamed from ``Reading`` in 1.8.x — the table name + column names
    stay as ``reading`` / ``library_id`` so the rename is purely a
    Python-identifier cleanup with no DB migration. Old reading-flavoured
    helper names live on as aliases below for one release while every
    caller is updated."""
    __tablename__ = "reading"
    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey("library.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    # Optional short blurb shown alongside the title in lists / link
    # previews. Plain text — no markdown rendering. Independent from
    # `body` (the paste-mode long-form content that opens as its own
    # document) so an admin can pin a one-liner on a file or link item
    # without using paste mode.
    summary = db.Column(db.Text)
    body = db.Column(db.Text)
    url = db.Column(db.String(1000))
    stored_filename = db.Column(db.String(500))
    original_filename = db.Column(db.String(500))
    thumbnail_filename = db.Column(db.String(500))
    position = db.Column(db.Integer, nullable=False, default=0)
    # Per-item visibility on the public Literature Library page. Default
    # is True (show) so an admin who flips a library to public sees every
    # item appear without having to click each one on; toggling False
    # hides this specific item even when its parent library is public.
    public_visible = db.Column(db.Boolean, nullable=False, default=True)
    # User who created the library item. Drives the per-item deletion
    # gate for the Editor role (Editors may only delete items whose
    # creator was an editor-tier user — admin-created content is
    # protected). Nullable so legacy rows survive the migration; legacy
    # items are treated as admin-created (uneditable to non-admins) by
    # the gate.
    created_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by])
    categories = db.relationship("LibraryCategory", secondary=reading_categories,
                                 back_populates="items",
                                 order_by="LibraryCategory.position, LibraryCategory.id")

    @property
    def url_slug(self):
        """See ``MeetingFile.url_slug`` — same purpose, same shape."""
        from .colors import slugify
        if self.original_filename:
            name, dot, ext = self.original_filename.rpartition(".")
            if dot and ext and 1 <= len(ext) <= 10 and name:
                return f"{slugify(name)}.{slugify(ext)}"
        return slugify(self.title)


class UrlRedirect(db.Model):
    __tablename__ = "url_redirect"
    id = db.Column(db.Integer, primary_key=True)
    source_path = db.Column(db.String(2000), unique=True, nullable=False, index=True)
    target_path = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FrontendNavItem(db.Model):
    """Top-level navigation item on the public header."""
    __tablename__ = "frontend_nav_item"
    id = db.Column(db.Integer, primary_key=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    style = db.Column(db.String(16), nullable=False, default="text")  # text | button | two-line
    label = db.Column(db.String(160))
    line1 = db.Column(db.String(120))
    line2 = db.Column(db.String(120))
    url = db.Column(db.String(500))
    has_megamenu = db.Column(db.Boolean, nullable=False, default=False)
    open_in_new_tab = db.Column(db.Boolean, nullable=False, default=False)
    # When set to a key registered in ``app/forms_registry.py``, clicking
    # this nav item opens the matching form modal instead of navigating
    # to ``url``. The URL still acts as a no-JS / right-click fallback,
    # so admins typically point it at the standalone form page.
    form_trigger = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    columns = db.relationship(
        "FrontendNavColumn",
        cascade="all, delete-orphan",
        order_by="FrontendNavColumn.position, FrontendNavColumn.id",
        backref="nav_item",
    )


class FrontendNavColumn(db.Model):
    __tablename__ = "frontend_nav_column"
    id = db.Column(db.Integer, primary_key=True)
    nav_item_id = db.Column(db.Integer, db.ForeignKey("frontend_nav_item.id", ondelete="CASCADE"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    heading = db.Column(db.String(160))
    links = db.relationship(
        "FrontendNavLink",
        cascade="all, delete-orphan",
        order_by="FrontendNavLink.position, FrontendNavLink.id",
        backref="column",
    )


class FrontendNavLink(db.Model):
    """A block inside a mega-menu column. Despite the legacy "link" name,
    this can be a title, link, button, or section divider — see `kind`."""
    __tablename__ = "frontend_nav_link"
    id = db.Column(db.Integer, primary_key=True)
    column_id = db.Column(db.Integer, db.ForeignKey("frontend_nav_column.id", ondelete="CASCADE"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    kind = db.Column(db.String(16), nullable=False, default="link")  # link | title | button | section
    label = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500))
    icon_before = db.Column(db.String(64))
    icon_after = db.Column(db.String(64))
    icon_before_color = db.Column(db.String(16))
    icon_after_color = db.Column(db.String(16))
    icon_before_size = db.Column(db.Integer)  # px; None = theme default
    icon_after_size = db.Column(db.Integer)
    link_size = db.Column(db.String(16))  # legacy (deprecated; replaced by link_size_pct)
    # Per-link override of the mega-menu link font size, expressed as
    # an integer percentage where 100 = the active theme's default.
    # NULL means "inherit the global Link font size slider in Mega menu
    # appearance"; a value scopes a custom scale to this one link via an
    # inline ``--fe-mm-link-scale`` on the rendered <a>, beating the
    # cascaded value from the megamenu root.
    link_size_pct = db.Column(db.Integer)
    override_color = db.Column(db.Boolean, nullable=False, default=False)
    custom_color = db.Column(db.String(16))
    button_style = db.Column(db.String(16), nullable=False, default="pill")  # pill | rounded
    open_in_new_tab = db.Column(db.Boolean, nullable=False, default=False)
    # When set to a key registered in ``app/forms_registry.py``, clicking
    # this mega-menu link opens the matching form modal instead of
    # navigating. URL still ships as a no-JS fallback.
    form_trigger = db.Column(db.String(64))


class FrontendHeroButton(db.Model):
    """A call-to-action button rendered under the hero subheading. The primary
    and ghost styles mirror the originals baked into the classic homepage; the
    custom style lets the admin override bg/text colors per button."""
    __tablename__ = "frontend_hero_button"
    id = db.Column(db.Integer, primary_key=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    label = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500))
    style = db.Column(db.String(16), nullable=False, default="primary")  # primary | ghost | custom
    custom_bg_color = db.Column(db.String(16))
    custom_text_color = db.Column(db.String(16))
    icon_before = db.Column(db.String(64))
    icon_after = db.Column(db.String(64))
    icon_before_color = db.Column(db.String(16))
    icon_after_color = db.Column(db.String(16))
    icon_before_size = db.Column(db.Integer)
    icon_after_size = db.Column(db.Integer)
    open_in_new_tab = db.Column(db.Boolean, nullable=False, default=False)


class CustomLayout(db.Model):
    """A page-layout preset built from a sequence of block types
    (hero, features, testimonials, etc.). The pre-built set is seeded
    on first boot; admins can also create new ones via the drag-and-drop
    builder. ``blocks_json`` is a JSON list of {"type": "<key>"} dicts;
    rendering iterates them in order through the block-iteration template."""
    __tablename__ = "custom_layout"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    blocks_json = db.Column(db.Text, nullable=False, default="[]")
    kind = db.Column(db.String(16), nullable=False, default="homepage")  # homepage | page
    is_prebuilt = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CustomIcon(db.Model):
    """User-uploaded icon (SVG or PNG) usable in mega-menu link icons alongside
    the built-in Lucide set. Reference form in FrontendNavLink.icon_before /
    icon_after: ``custom:<id>`` (e.g. ``custom:42``)."""
    __tablename__ = "custom_icon"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    stored_filename = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Post(db.Model):
    """Admin-authored announcement / event posts.

    A single Post can be tagged as an announcement, an event, or both
    (the two booleans are independent — neither set is treated as
    "draft"). Event posts pick up a starts/ends datetime, location
    fields, contact, optional Zoom credentials, and event-website URL.
    Posts are archived manually OR automatically the day after the
    event ends; the public site (when wired in) hides archived posts."""
    __tablename__ = "post"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    # Explicit URL slug for /event/<slug>. NULL → slugify(title). Editing
    # gated to admins + frontend editors; history tracked in
    # EntitySlugHistory so renames don't break existing links.
    slug = db.Column(db.String(255))
    summary = db.Column(db.Text)        # short blurb shown in lists / link previews
    body = db.Column(db.Text)           # full content (markdown supported)
    featured_image_filename = db.Column(db.String(500))

    # Type tags — independent so a single post can be both.
    is_announcement = db.Column(db.Boolean, nullable=False, default=False)
    is_event = db.Column(db.Boolean, nullable=False, default=False)

    # Event timing.
    event_starts_at = db.Column(db.DateTime)
    event_ends_at = db.Column(db.DateTime)

    # Optional auto-archive deadline for *announcements*. When set on a
    # post tagged is_announcement (events ignore this — they already
    # auto-archive past their event_ends_at), the auto-archive sweep
    # flips ``is_archived`` to True once this timestamp passes in the
    # site's local timezone. NULL = no auto-archive (admin clears the
    # post by hand). The edit UI hides this field whenever
    # is_announcement is unchecked so the operator only sees it in the
    # context it applies.
    announcement_auto_archive_at = db.Column(db.DateTime)

    # Event location.
    is_online = db.Column(db.Boolean, nullable=False, default=False)
    location_name = db.Column(db.String(255))
    location_address = db.Column(db.Text)
    google_maps_url = db.Column(db.String(500))

    # Event website (free URL with a label so the link reads as the
    # admin wants it to read on the public site). Retained for
    # backwards compat with older rows + import scripts; new edits
    # use the multi-row ``links_json`` column below, which falls back
    # to this pair when empty so existing posts keep their single
    # link without an explicit migration.
    website_url = db.Column(db.String(500))
    website_label = db.Column(db.String(120))
    # Multi-row "Links" list, replacing the single website_url/label
    # pair on the edit UI. Serialised as a JSON list of
    # ``{"url": str, "label": str, "new_tab": bool}`` dicts. The
    # ``event_links`` property below transparently falls back to the
    # legacy single-pair columns when this is unset so renderers can
    # iterate one consistent collection.
    links_json = db.Column(db.Text)
    # Image gallery — JSON list of up to 10 stored filenames (UUID-
    # prefixed under UPLOAD_FOLDER, same convention as
    # ``featured_image_filename``). Rendered on the public detail
    # page below the description with a lightbox, and editable from
    # the admin post-edit page (upload + File Browser picker). The
    # gallery is independent of the featured image — admins can
    # share or not share an image between the two.
    gallery_json = db.Column(db.Text)

    @property
    def gallery_filenames(self):
        """Decoded list of stored filenames for the post's gallery.

        Filters out non-string entries / blanks so a corrupted blob
        can't crash the renderer; tail-truncates to 10 since that's
        the hard cap the editor enforces. Returns ``[]`` when the
        column is empty so callers can iterate unconditionally."""
        if not self.gallery_json:
            return []
        try:
            import json as _json
            data = _json.loads(self.gallery_json)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for entry in data:
            if isinstance(entry, str) and entry.strip():
                out.append(entry.strip())
            if len(out) >= 6:
                break
        return out

    @property
    def event_links(self):
        """Return the resolved list of public links for this post.

        Each entry is a dict with ``url``, ``label``, and ``new_tab``
        keys; entries with no URL are filtered out. When
        ``links_json`` is empty (legacy rows + rows whose admin
        hasn't opened the new editor yet), the legacy
        ``website_url`` / ``website_label`` pair is wrapped into a
        single-item list so the public templates keep rendering the
        same link they always did."""
        import json
        out = []
        if self.links_json:
            try:
                parsed = json.loads(self.links_json)
                if isinstance(parsed, list):
                    for it in parsed:
                        if not isinstance(it, dict):
                            continue
                        url = (it.get("url") or "").strip()
                        if not url:
                            continue
                        # ``style`` picks the button chrome on
                        # templates that render links as buttons —
                        # ``primary`` = solid accent button,
                        # ``secondary`` = ghost / outline button.
                        # Unknown values fall back to ``primary`` so
                        # the link still renders prominently.
                        style = (it.get("style") or "").strip().lower()
                        if style not in ("primary", "secondary"):
                            style = "primary"
                        out.append({
                            "url": url,
                            "label": (it.get("label") or "").strip() or None,
                            "new_tab": bool(it.get("new_tab", True)),
                            "style": style,
                        })
            except (ValueError, TypeError):
                out = []
        if not out and self.website_url:
            out.append({
                "url": self.website_url,
                "label": self.website_label or None,
                # Legacy links always opened in a new tab on the
                # public templates, so mirror that default here.
                "new_tab": True,
                # Legacy single-link rendering always used the
                # primary (solid) button style on the classic +
                # poster templates, so default to that.
                "style": "primary",
            })
        return out

    # Zoom (announcements never have these; events do, when online).
    zoom_meeting_id = db.Column(db.String(64))
    zoom_passcode = db.Column(db.String(128))
    zoom_url = db.Column(db.String(500))

    # Contact.
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(64))
    contact_email = db.Column(db.String(255))

    # Lifecycle. Posts are in one of four states:
    #   pending  → is_pending_review=True (submitted via /submissionform,
    #              awaiting admin/editor review; NEVER public)
    #   draft    → is_draft=True  (edited in private; not on the public site)
    #   active   → all flags False (live)
    #   archived → is_archived=True (hidden, kept for reference)
    is_draft = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    # Submission holding tank. When True, the post was created via the
    # public /submissionform endpoint and hasn't been reviewed yet.
    # The public site filters these out alongside drafts; the admin
    # Posts page surfaces them under a dedicated "Pending review" tab.
    is_pending_review = db.Column(db.Boolean, nullable=False, default=False)
    # Submitter contact (separate from the post's own contact_* fields,
    # which the admin may want to keep distinct from whoever submitted
    # the request — e.g. a fellowship member submitting an event hosted
    # by someone else). The admin replies to submitter_email.
    submitter_name = db.Column(db.String(120))
    submitter_email = db.Column(db.String(255))
    submitter_phone = db.Column(db.String(64))
    submitter_notes = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime)
    # Public "posted" timestamp surfaced in admin lists + (eventually)
    # the public site's "Posted on …" line. Editable by the admin so a
    # post can be backdated; falls back to created_at when NULL so the
    # display layer always has something to show.
    published_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))

    @property
    def public_slug(self):
        """Same shape as ``Meeting.public_slug`` — explicit slug if set,
        slugified title otherwise."""
        from .colors import slugify
        return slugify(self.slug) if self.slug else slugify(self.title)

    @property
    def display_posted(self):
        """Datetime shown anywhere a "posted on" stamp belongs.
        Prefers the admin-set ``published_at``; falls back to
        ``created_at`` so legacy rows imported before the column
        existed still surface a date."""
        return self.published_at or self.created_at


class Story(db.Model):
    """Recovery story — long-form first-person post.

    Modeled loosely on Post but with blog-style metadata: an explicit
    author byline (often a first name + initial of last name, since
    these are recovery stories), an optional sobriety / clean date,
    and a story_date (the publish / "as of" date the public page shows
    instead of created_at). Drafts and archives behave the same way as
    Post — drafts hide from the public site, archives are kept around
    but hidden too. URLs live at /stories and /stories/<slug>."""
    __tablename__ = "story"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255))
    summary = db.Column(db.Text)
    body = db.Column(db.Text)
    featured_image_filename = db.Column(db.String(500))
    author_name = db.Column(db.String(120))
    author_bio = db.Column(db.Text)
    sobriety_date = db.Column(db.Date)
    story_date = db.Column(db.Date)
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    is_draft = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    # Editorial "posted on" timestamp — distinct from ``story_date``,
    # which is the in-story milestone date the admin enters (sobriety
    # anniversary, write-up date, etc.). ``published_at`` is purely
    # the publication timestamp; it falls back to created_at when
    # NULL so legacy rows still surface a date.
    published_at = db.Column(db.DateTime)
    # Public-submission holding tank. When True, the story was
    # submitted via the public ``/storyform`` endpoint and hasn't
    # been reviewed yet. The public site filters these out alongside
    # drafts; the admin Stories page surfaces them under a dedicated
    # "Pending review" tab so they can be approved (publish or move
    # to draft) or deleted. Same shape Post uses for its own
    # holding-tank flow.
    is_pending_review = db.Column(db.Boolean, nullable=False, default=False)
    submitter_name = db.Column(db.String(120))
    submitter_email = db.Column(db.String(255))
    submitter_phone = db.Column(db.String(64))
    submitter_notes = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime)
    # Optional file the submitter attached with their story (a
    # written draft document, audio recording, etc). Stored under
    # UPLOAD_FOLDER with a UUID-prefixed filename, same convention
    # the rest of the app uses. Admins download via the admin
    # pending-review row before transferring the content into the
    # story body. Preserved across approve / move-to-draft lifecycle
    # changes so admins can re-read the original submission later;
    # cleaned up when the story is deleted.
    submission_attachment_filename = db.Column(db.String(500))
    submission_attachment_original = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))

    @property
    def public_slug(self):
        from .colors import slugify
        return slugify(self.slug) if self.slug else slugify(self.title)

    @property
    def display_date(self):
        """Date the public page shows under the title. Prefers the
        admin-set story_date; falls back to created_at."""
        return self.story_date or (self.created_at.date() if self.created_at else None)

    @property
    def display_posted(self):
        """Datetime shown wherever a "posted on" stamp belongs. Prefers
        ``published_at`` (admin-set or imported); falls back to
        ``created_at``."""
        return self.published_at or self.created_at


# ─────────────────────────────────────────────────────────────────────────────
# Blog module — admin-authored long-form posts with categories and tags.
#
# Where Stories are first-person recovery accounts and Posts are
# announcements/events, BlogPost is the general-purpose blog entity:
# editorial articles, committee updates, group news. A single Blog
# table can serve many distinct front-end "blogs" (committee, group,
# meeting-host) by filtering the public list/block on a chosen
# category or tag — that way two committees can each own a separate
# /<page>/ that surfaces only their own posts without needing
# parallel data tables.
# ─────────────────────────────────────────────────────────────────────────────

# Many-to-many association tables — kept as plain Tables (not models)
# so simple .append() / list manipulation works directly on the post.
blog_post_categories = db.Table(
    "blog_post_categories",
    db.Column("post_id", db.Integer,
              db.ForeignKey("blog_post.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("category_id", db.Integer,
              db.ForeignKey("blog_category.id", ondelete="CASCADE"),
              primary_key=True),
)

blog_post_tags = db.Table(
    "blog_post_tags",
    db.Column("post_id", db.Integer,
              db.ForeignKey("blog_post.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("tag_id", db.Integer,
              db.ForeignKey("blog_tag.id", ondelete="CASCADE"),
              primary_key=True),
)


class BlogCategory(db.Model):
    """Editorial category — a top-level grouping a post can belong to.
    Multiple categories per post are allowed so a single article can
    surface under several committees / sections. The ``color`` field
    is an optional hex used by the public templates to colour-code
    chips. ``position`` lets admins re-order the category list."""
    __tablename__ = "blog_category"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(160), nullable=False, unique=True)
    description = db.Column(db.Text)
    color = db.Column(db.String(16))
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BlogTag(db.Model):
    """Free-form tag for cross-cutting topics — many tags per post,
    many posts per tag. Lighter-weight than categories: no colour, no
    description, just a label + slug used as a filter target on the
    public block + tag-archive routes."""
    __tablename__ = "blog_tag"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(120), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BlogPost(db.Model):
    """Long-form blog entry. Modeled on Story but with editorial
    metadata and many-to-many category / tag links so a single table
    can power multiple distinct frontend blogs (one per committee,
    group, meeting). Drafts hide from the public site, archives are
    kept around but hidden too. URLs live at /blog and /blog/<slug>."""
    __tablename__ = "blog_post"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255))
    summary = db.Column(db.Text)
    body = db.Column(db.Text)
    # Drag-and-drop block editor payload. JSON list of {type, data} dicts
    # (see `app/templates/_blog_blocks.html` for the schema). NULL or
    # empty list means "use the legacy markdown `body` column" so older
    # posts keep rendering identically until they're re-edited.
    body_blocks_json = db.Column(db.Text)
    featured_image_filename = db.Column(db.String(500))
    author_name = db.Column(db.String(120))
    author_bio = db.Column(db.Text)
    # Date the public page shows under the title. Doubles as the sort
    # key (newest published first). Falls back to created_at when blank.
    published_at = db.Column(db.DateTime)
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    is_pinned = db.Column(db.Boolean, nullable=False, default=False)
    is_draft = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    # Vestigial — the comments feature was removed from the editor and
    # frontend, but the underlying SQLite column was created with a
    # NOT NULL constraint on existing installs. SQLite can't drop a
    # column in-place, so we keep the attribute on the model purely to
    # satisfy the constraint on INSERT (default=True). No code reads
    # this value anywhere else. If a future migration rebuilds the
    # table, this attribute can be deleted in the same change.
    allow_comments = db.Column(db.Boolean, nullable=False, default=True)
    reading_minutes = db.Column(db.Integer)  # estimated; computed at save-time when blank
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))

    categories = db.relationship(
        "BlogCategory", secondary=blog_post_categories,
        order_by="BlogCategory.position, BlogCategory.name",
        backref=db.backref("posts", lazy="dynamic"))
    tags = db.relationship(
        "BlogTag", secondary=blog_post_tags,
        order_by="BlogTag.name",
        backref=db.backref("posts", lazy="dynamic"))

    @property
    def public_slug(self):
        from .colors import slugify
        return slugify(self.slug) if self.slug else slugify(self.title)

    @property
    def display_date(self):
        """Date the public page shows under the title. Prefers the
        admin-set published_at; falls back to created_at."""
        return self.published_at or self.created_at

    # Alias so admin-list / sort code can use a uniform property name
    # across Post / Story / BlogPost without branching by type.
    @property
    def display_posted(self):
        return self.published_at or self.created_at

    @property
    def body_blocks(self):
        """Decoded list-of-dicts version of ``body_blocks_json``. Returns
        an empty list when the column is NULL, blank, or doesn't decode
        to a JSON list — keeps the public render path branch-free."""
        raw = (self.body_blocks_json or "").strip()
        if not raw:
            return []
        try:
            import json
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []


class CustomFont(db.Model):
    """Admin-added font available alongside the vendored Inter/Fraunces in the
    Web Frontend font pickers. Source is either an uploaded font file
    (TTF/OTF/WOFF/WOFF2 served from /pub/font/<id>) or a Google Fonts CSS
    URL — in the Google case we fetch the CSS, download every referenced
    woff2 file locally, rewrite the URLs, and store the rewritten CSS so
    nothing is served by Google at runtime. Reference form anywhere a
    font key is stored: ``custom:<id>``."""
    __tablename__ = "custom_font"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    family = db.Column(db.String(120), nullable=False)
    source = db.Column(db.String(16), nullable=False, default="upload")  # upload | google
    # source=upload: the font binary itself (TTF/OTF/WOFF/WOFF2).
    # source=google: the rewritten CSS file (text/css) that @font-face's
    #   the local woff2 binaries listed in asset_files_json.
    stored_filename = db.Column(db.String(500))
    # Original Google Fonts URL (stored for the admin's reference only).
    google_url = db.Column(db.String(500))
    # JSON list of stored filenames for additional binary assets — used by
    # source=google to track every woff2 we downloaded so deletion can
    # clean them up.
    asset_files_json = db.Column(db.Text)
    mime_type = db.Column(db.String(100))
    size_bytes = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EntitySlugHistory(db.Model):
    """Append-only log of public-frontend slug changes for meetings and
    posts. Each row says: at ``changed_at``, the entity (``entity_type``,
    ``entity_id``) had its public-facing slug switch from ``old_slug`` to
    ``new_slug``. Drives both the visible history timeline in the admin
    edit screens and the request-time fallback that 301-redirects old
    URLs to the entity's current slug.

    No FK to meeting/post: cleanup-on-delete is handled explicitly in the
    delete handlers so the redirect log can also be retained when an
    entity is archived but kept around. ``entity_type`` is one of
    ``"meeting"`` | ``"post"``."""
    __tablename__ = "entity_slug_history"
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(16), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    old_slug = db.Column(db.String(255), nullable=False)
    new_slug = db.Column(db.String(255), nullable=False)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    changed_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    __table_args__ = (
        db.Index("ix_entity_slug_history_lookup", "entity_type", "old_slug"),
        db.Index("ix_entity_slug_history_entity", "entity_type", "entity_id"),
    )

    user = db.relationship("User", foreign_keys=[changed_by])


class LoginFailure(db.Model):
    """One row per failed login attempt. Used by the login rate limiter so
    the counter is shared across gunicorn workers and survives restarts."""
    __tablename__ = "login_failure"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(8), nullable=False)   # 'ip' or 'user'
    key = db.Column(db.String(255), nullable=False)  # IP string or lower(username)
    failed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        db.Index("ix_login_failure_kind_key_time", "kind", "key", "failed_at"),
    )


class IPBlock(db.Model):
    """Admin-managed IP block list. The Watchtower request hook rejects
    any inbound request whose source IP matches an unexpired row with a
    403, so a single ban click in the admin UI cuts off a misbehaving
    client at the door. ``expires_at`` is nullable — NULL means
    permanent. ``blocked_by`` references the admin who placed the ban
    so the dashboard can show who acted."""
    __tablename__ = "ip_block"
    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(64), nullable=False, unique=True, index=True)
    reason = db.Column(db.String(255))
    blocked_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    blocked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)
    expires_at = db.Column(db.DateTime)
    hit_count = db.Column(db.Integer, nullable=False, default=0)
    last_hit_at = db.Column(db.DateTime)

    blocked_by_user = db.relationship("User", foreign_keys=[blocked_by])


class ActivityLog(db.Model):
    """Append-only feed of user-driven write actions across the portal.

    Drives the User Log admin page. Each row captures who did what,
    against which entity, with a short human-readable summary and the
    request's source IP for audit. Reads are NOT logged — only saves
    / deletes / role-mutating actions and the auth events that bracket
    them. ``entity_type`` + ``entity_id`` are nullable for actions that
    don't bind to a specific record (e.g. login, settings save).

    Rows are never edited; they're inserted once and read by the user
    log UI. A small periodic cleanup (out of scope for the first cut)
    can prune rows older than the retention window if storage becomes
    a concern."""
    __tablename__ = "activity_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"),
                        index=True)
    # Short snake_case verb identifying the action (``login``,
    # ``meeting.update``, ``library.delete``, …). Free-form on
    # purpose — formatting / icon lookup is done on the rendering
    # side from a small mapping table, with sensible fallbacks for
    # unknown verbs so adding new instrumentation never breaks the UI.
    action = db.Column(db.String(64), nullable=False, index=True)
    entity_type = db.Column(db.String(32))   # 'meeting', 'library', 'user', etc.
    entity_id = db.Column(db.Integer)
    # One-line human-readable summary surfaced in the timeline. Avoid
    # leaking secrets here — admin-visible only, but still public to
    # every admin so credentials, tokens, etc. should not appear.
    summary = db.Column(db.String(500))
    ip = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)

    user = db.relationship("User", foreign_keys=[user_id])


class LoginSession(db.Model):
    """Single login session per row. Created on successful sign-in,
    closed (``ended_at`` + ``end_reason``) on logout / timeout / new
    sign-in from the same browser. The User Log surfaces the last 30
    days of these so admins can see who's actively using the portal
    and from where."""
    __tablename__ = "login_session"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    ip = db.Column(db.String(64))
    user_agent = db.Column(db.String(500))
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)
    last_activity_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    # 'logout' | 'replaced' | 'expired' | 'admin_reset' | 'forced'
    end_reason = db.Column(db.String(16))

    user = db.relationship("User", foreign_keys=[user_id])

    @property
    def is_active(self):
        return self.ended_at is None


class DeletedFile(db.Model):
    """Recycle bin row for soft-deleted file-bearing records.

    Deletes through the regular UI (Reading, MeetingFile, MediaItem)
    no longer hard-delete the underlying row + file in one motion;
    they snapshot the row's full state into this table, leave the
    file on disk, and remove the live record. Restoring rebuilds the
    original row from the snapshot at its captured position.

    Three ``source_type`` values today: ``reading`` (library file),
    ``meeting_file`` (meeting attachment), ``media_item`` (file-browser
    only entry, never bound to a reading or meeting). The
    ``parent_type`` / ``parent_id`` / ``parent_label`` columns are
    captured at delete time so the Delete Log can show *where* a file
    came from even if the parent library / meeting was renamed (or
    itself deleted) since.

    ``snapshot_json`` carries every field needed to rebuild the row:
    library_id, title, body, url, position, category ids,
    public_visible, created_by, etc. Stored as JSON so adding fields
    to the underlying model in a future release doesn't require a
    schema migration here.

    ``expires_at`` is the cutoff after which a periodic sweep
    permanently purges the row + on-disk file (subject to the
    no-live-references guard). Admins can also purge any row
    immediately from the Delete Log UI."""
    __tablename__ = "deleted_file"
    id = db.Column(db.Integer, primary_key=True)
    source_type = db.Column(db.String(32), nullable=False, index=True)
    source_id = db.Column(db.Integer)  # original row id, for traceability
    stored_filename = db.Column(db.String(500))
    original_filename = db.Column(db.String(500))
    title = db.Column(db.String(255))
    thumbnail_filename = db.Column(db.String(500))
    parent_type = db.Column(db.String(32))   # 'library' | 'meeting' | None
    parent_id = db.Column(db.Integer)
    parent_label = db.Column(db.String(255))
    snapshot_json = db.Column(db.Text)       # JSON blob of full row state
    deleted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    expires_at = db.Column(db.DateTime, nullable=False, index=True)

    deleter = db.relationship("User", foreign_keys=[deleted_by])


class PasswordResetToken(db.Model):
    """Single-use, time-limited token for the public forgot-password flow.

    Only the SHA-256 hash of the token is stored — the plaintext is
    sent to the user's inbox once and never re-derivable from the row.
    A row is consumed by setting ``used_at`` so the same link can't be
    replayed even within its expiry window. Cleanup of expired/used
    rows happens lazily when new tokens are issued."""
    __tablename__ = "password_reset_token"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    requested_ip = db.Column(db.String(64))

    user = db.relationship("User", foreign_keys=[user_id])

    def is_valid(self):
        if self.used_at is not None:
            return False
        return self.expires_at > datetime.utcnow()


class Page(db.Model):
    """Admin-authored content page rendered at /<slug> on the public
    frontend. Body lives in `blocks_json` using the same schema as the
    Zoom Tech editor (sections of typed blocks rendered through the
    shared `_blocks.html` macros)."""
    __tablename__ = "page"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    blocks_json = db.Column(db.Text)
    template = db.Column(db.String(16), nullable=False, default="standard")  # standard | wiki
    is_published = db.Column(db.Boolean, nullable=False, default=True)
    # Private pages are reachable only by signed-in editors/admins. The
    # public catch-all `/<slug>` route 404s anonymous visitors, and the
    # Site Index / public navigation hides private rows. Combined with
    # ``is_published`` the three states are: Draft (is_published=False),
    # Published (is_published=True, is_private=False), Private
    # (is_published=True, is_private=True).
    is_private = db.Column(db.Boolean, nullable=False, default=False)
    # Active layout preset. Mirrors how homepage tracks its layout via
    # `frontend_homepage_template` — points at a CustomLayout(kind='page')
    # row's `key`. Selecting a preset copies its blocks_json into
    # page.blocks_json so the admin can edit freely; layout_key just
    # tracks "what was last applied" for the picker UI.
    layout_key = db.Column(db.String(64), nullable=False, default="custom")
    # Page background. `bg_image_filename` is the UUID-prefixed name in
    # UPLOAD_FOLDER (None = no bg). `bg_mode` is 'cover' or 'tile'.
    # `bg_tile_scale` is a percent (25..400) applied to the tile's
    # natural size when mode='tile'.
    bg_image_filename = db.Column(db.String(500))
    bg_mode = db.Column(db.String(16), nullable=False, default="cover")
    bg_tile_scale = db.Column(db.Integer, nullable=False, default=100)
    # Optional solid background colour, with separate light + dark
    # mode values. Layers BENEATH the dynamic backdrop and uploaded
    # image (so admins can sit a colour-fill behind a tiled SVG, etc.).
    # `bg_color` is the light-mode hex (#rrggbb / #rgb / blank);
    # `bg_color_dark_mode` controls the dark-mode behaviour:
    #   • 'same'   → use the light value in both modes (no override)
    #   • 'auto'   → derive a dark-mode-friendly variant via
    #                design.derive_dark_color() at render time
    #   • 'manual' → use the value in `bg_color_dark` verbatim
    # Empty `bg_color` means "no colour fill" — the page falls
    # through to whatever the body / theme paints.
    bg_color = db.Column(db.String(16))
    bg_color_dark = db.Column(db.String(16))
    bg_color_dark_mode = db.Column(db.String(16), nullable=False, default="same")
    # Optional dynamic backdrop layered over the page bg. Stores a
    # catalog key from app/dynbg.py (None = no dynbg). When set, the
    # public renderer paints it as the bottom-most layer, with the
    # uploaded image (if any) and content stacking on top via
    # standard z-index. Mixes cleanly with `bg_image_filename` —
    # admins can pair a tile/cover image with a dynbg or use either
    # alone.
    bg_dynamic_key = db.Column(db.String(64))
    # Overlay + custom-colour config for the dynbg, persisted as a
    # JSON blob so the schema doesn't need to grow another column
    # every time a new dimension is added. Shape:
    #   {"overlay": "<key>", "colors": ["#hex", "#hex", "#hex"]}
    # Empty / omitted keys mean "fall through to brand defaults".
    bg_dynbg_config_json = db.Column(db.Text)
    # Page-wide width formatting. `width_mode` is 'boxed' (centered with
    # max_width) or 'full' (viewport-spanning with full_padding_pct as
    # left/right gutter). `max_width` only matters in boxed mode;
    # `full_padding_pct` only matters in full mode. Together they let
    # the admin choose whether the page hugs a content column or
    # bleeds wide with controllable air on the sides.
    width_mode = db.Column(db.String(16), nullable=False, default="boxed")
    max_width = db.Column(db.Integer, nullable=False, default=1160)
    full_padding_pct = db.Column(db.Integer, nullable=False, default=4)
    # Per-page page-shell spacing. Each is a pixel value the public
    # renderer stamps as a CSS custom property on the article so the
    # default `.fe-pp` / `.fe-pp-shell` / `.fe-pp-section` rules
    # consume them via `var(--fe-pp-pad-top, 80px)` etc. Defaults
    # match the legacy hard-coded values so existing pages render
    # unchanged. Set any to 0 for a fully flush page (e.g. a hero
    # that sits flush against the header with no top padding).
    pad_top = db.Column(db.Integer, nullable=False, default=80)
    pad_bottom = db.Column(db.Integer, nullable=False, default=96)
    pad_x = db.Column(db.Integer, nullable=False, default=16)
    section_gap = db.Column(db.Integer, nullable=False, default=32)
    # Vertical margin around `.block` elements (containers, blog
    # cards, etc.). The global `.block { margin: 12px 0 }` rule in
    # app.css is the source of inter-block whitespace; this column
    # overrides via a CSS custom property scoped to the article so
    # blocks can sit fully flush (e.g. a hero pinned to the header
    # with no gap above) when set to 0.
    block_margin_y = db.Column(db.Integer, nullable=False, default=12)
    # Per-page hero typography overrides. Each is optional — None / blank
    # falls back to the theme's design tokens (handled by CSS via
    # default values in `var(--fe-pp-*, …)`). `heading_align` is one of
    # 'auto' | 'left' | 'center' | 'right' where 'auto' means the
    # layout chooses (left for two-column, center otherwise).
    heading_color = db.Column(db.String(16))
    heading_align = db.Column(db.String(16), nullable=False, default="auto")
    heading_font = db.Column(db.String(64))
    subheading_color = db.Column(db.String(16))
    subheading_font = db.Column(db.String(64))
    # Per-page Open Graph overrides. Empty / unset values fall back to
    # the site-wide ``frontend_og_*`` defaults at render time (handled
    # in ``frontend.py::page_detail`` via the ``_page_og`` helper).
    # ``og_image_filename`` is the UUID-prefixed name in UPLOAD_FOLDER;
    # the public serve route is ``/page-og-image/<page_id>``.
    og_title = db.Column(db.String(200))
    og_description = db.Column(db.Text)
    og_image_filename = db.Column(db.String(500))
    # Pending-draft snapshot for already-published pages. When non-null,
    # `draft_json` holds a JSON object capturing every form field of an
    # in-progress edit (title, slug, blocks_json, layout, background,
    # padding, SEO, etc.) without touching the published columns. The
    # public site keeps rendering whatever's in the live columns; the
    # admin's edit screen loads from the draft snapshot when it exists.
    # `draft_saved_at` is the wall-clock of the last "Save as Draft"
    # click, surfaced in the editor banner ("Draft saved 3 minutes ago").
    # Publishing copies the snapshot back to the columns and clears both
    # fields atomically. Distinct from `is_published` (which controls
    # public visibility — a `Draft` visibility page has nothing to do
    # with this column).
    draft_json = db.Column(db.Text)
    draft_saved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)


class PageRevision(db.Model):
    """Append-only edit history for a Page. Every successful Save (whether
    draft or publish) writes a row here capturing the full page state at
    that moment — same shape as `Page.draft_json` (a JSON object keyed by
    column name). Lets the admin browse past states and Restore one back
    into the draft slot for review before re-publishing. Capped per page
    by `_trim_page_revisions()`; older entries fall off the tail."""
    __tablename__ = "page_revision"
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer,
                        db.ForeignKey("page.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    # Which save produced this row — 'draft' (Save Draft) or 'publish'
    # (Save & Publish). Surfaced as a chip in the History modal so the
    # admin can scan past activity at a glance.
    action = db.Column(db.String(16), nullable=False)
    # Full page snapshot at save time. JSON object whose keys mirror
    # Page columns (title, slug, blocks_json, bg_*, pad_*, og_*, etc.).
    # Restore deserialises this back into `Page.draft_json` so the
    # admin can review before publishing.
    snapshot_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, index=True)
    # User who triggered the save (nullable in case the request slipped
    # through without an authenticated user — defensive).
    created_by_id = db.Column(db.Integer,
                              db.ForeignKey("user.id"), nullable=True)
    page = db.relationship("Page", backref=db.backref(
        "revisions", lazy="dynamic", cascade="all, delete-orphan",
        order_by="PageRevision.created_at.desc()"))
    user = db.relationship("User")


class Popup(db.Model):
    """Admin-authored modal popup rendered site-wide on the public
    frontend. Triggered by anchor-style ``#<name>`` selectors: any link
    with ``href="#newsletter"`` (or an element carrying
    ``data-popup="newsletter"``), and any page load / hashchange to the
    matching URL hash, opens the popup whose ``name`` is ``newsletter``.

    Body lives in ``blocks_json`` using the exact same schema as
    :class:`Page` — a JSON list of sections of typed blocks rendered
    through the shared ``_blocks.html`` macros — so the page-builder
    drag-and-drop editor and its block palette are reused verbatim. The
    remaining columns are the popup's own chrome: size, padding,
    background, overlay, position, per-device visibility, and trigger
    behaviour.
    """
    __tablename__ = "popup"
    id = db.Column(db.Integer, primary_key=True)
    # Trigger handle. Slugified to ``[a-z0-9-]`` and unique so a given
    # ``#hash`` maps to exactly one popup. This IS the selector — a popup
    # named "newsletter" opens from ``#newsletter``.
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    # Admin-facing label (list table, editor title, accessible name).
    title = db.Column(db.String(200), nullable=False)
    blocks_json = db.Column(db.Text)
    # Master on/off. Disabled popups are not emitted on the public site
    # (but editors can still preview them via the preview route).
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)

    # ── Sizing ──────────────────────────────────────────────────────
    width = db.Column(db.Integer, nullable=False, default=480)         # px
    # Viewport-relative cap so a wide popup still fits small screens.
    max_width_pct = db.Column(db.Integer, nullable=False, default=92)  # % of viewport
    # 'auto' grows to fit content (up to the viewport); 'fixed' pins the
    # panel to ``height`` px (content scrolls inside).
    height_mode = db.Column(db.String(16), nullable=False, default="auto")
    height = db.Column(db.Integer, nullable=False, default=420)        # px (fixed mode)
    padding = db.Column(db.Integer, nullable=False, default=32)        # px, inside the panel

    # ── Appearance ──────────────────────────────────────────────────
    bg_color = db.Column(db.String(16), nullable=False, default="#ffffff")
    # Optional dark-mode override; None = reuse the light value in dark.
    bg_color_dark = db.Column(db.String(16))
    border_radius = db.Column(db.Integer, nullable=False, default=16)  # px
    shadow = db.Column(db.String(8), nullable=False, default="xl")     # none|sm|md|lg|xl

    # ── Overlay (dimmed backdrop behind the panel) ──────────────────
    overlay_enabled = db.Column(db.Boolean, nullable=False, default=True)
    overlay_color = db.Column(db.String(16), nullable=False, default="#0f172a")
    overlay_opacity = db.Column(db.Integer, nullable=False, default=60)  # 0..100

    # ── Position within the viewport ────────────────────────────────
    position = db.Column(db.String(16), nullable=False, default="center")  # center|top|bottom

    # ── Responsiveness ──────────────────────────────────────────────
    show_desktop = db.Column(db.Boolean, nullable=False, default=True)
    show_mobile = db.Column(db.Boolean, nullable=False, default=True)
    # On phones, ignore ``width`` and fill the viewport (minus a small
    # gutter) so narrow screens get a comfortable, full-width sheet.
    mobile_full_width = db.Column(db.Boolean, nullable=False, default=True)

    # ── Behaviour ───────────────────────────────────────────────────
    close_on_overlay = db.Column(db.Boolean, nullable=False, default=True)
    show_close_button = db.Column(db.Boolean, nullable=False, default=True)
    # Optional: open automatically on page load (in addition to the
    # ``#name`` selector trigger), after ``auto_open_delay`` ms.
    auto_open = db.Column(db.Boolean, nullable=False, default=False)
    auto_open_delay = db.Column(db.Integer, nullable=False, default=0)  # ms

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def sections(self):
        """Decode ``blocks_json`` into the section list the shared
        ``render_sections`` macro consumes. Malformed / non-list
        payloads collapse to an empty list so the renderer's truthiness
        check ("does this popup have content?") just works."""
        import json as _json
        raw = (self.blocks_json or "").strip()
        if not raw:
            return []
        try:
            data = _json.loads(raw)
        except (ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []

    @property
    def overlay_rgba(self):
        """``overlay_color`` + ``overlay_opacity`` as a CSS ``rgba(...)``
        string for the backdrop fill."""
        hexv = (self.overlay_color or "#0f172a").lstrip("#")
        if len(hexv) == 3:
            hexv = "".join(c * 2 for c in hexv)
        try:
            r, g, b = int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16)
        except (ValueError, IndexError):
            r, g, b = 15, 23, 42
        opa = self.overlay_opacity if self.overlay_opacity is not None else 60
        a = max(0, min(100, opa)) / 100.0
        return f"rgba({r}, {g}, {b}, {a:.2f})"


class VisitorEvent(db.Model):
    """One row per anonymous page view on the public frontend.

    Logged-in users (anyone authenticated through the admin portal) are
    excluded from this table — these are visitor metrics, not staff
    metrics. The recording hook also skips asset requests, prefetches,
    obvious bot traffic, and HEAD/OPTIONS pings, so the row count tracks
    real human navigations on the public site.

    `visitor_hash` is a daily-rotating one-way hash of (IP, UA, salt) used
    to approximate "unique visitors" without storing the IP itself. The
    salt rotates each UTC day so the same hash can't be linked back to a
    person across days — the column is a privacy-preserving cardinality
    estimator, not a stable identifier.
    """
    __tablename__ = "visitor_event"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)
    # The path the visitor landed on (e.g. "/meetings", "/blog/foo"). Capped
    # at 500 chars to match the rest of the codebase's path columns.
    path = db.Column(db.String(500), nullable=False, index=True)
    # Flask endpoint name when resolvable (e.g. "frontend.meeting_detail").
    # Lets the metrics page bucket views by section without re-parsing the
    # path. Nullable for catch-all routes the router couldn't resolve.
    endpoint = db.Column(db.String(128), index=True)
    # The Referer header trimmed to its origin (scheme + host). Full URLs
    # would carry referral search terms / query strings we don't want to
    # store; the origin is enough for "where did this visitor come from"
    # reporting. None = direct / no referer.
    referrer_host = db.Column(db.String(255))
    # Parsed device class — one of "mobile" | "tablet" | "desktop" | "bot"
    # | "other". The bot bucket is mostly a backstop; the recording hook
    # already drops obvious crawlers before insert.
    device = db.Column(db.String(16), index=True)
    # Parsed browser family (e.g. "Chrome", "Safari", "Firefox", "Edge").
    browser = db.Column(db.String(32), index=True)
    # Parsed OS family (e.g. "macOS", "Windows", "iOS", "Android", "Linux").
    os = db.Column(db.String(32), index=True)
    # Daily-rotating one-way hash for unique-visitor approximation. Same
    # visitor on the same UTC day → same hash; same visitor the next day
    # → different hash. See VisitorEvent docstring above.
    visitor_hash = db.Column(db.String(32), index=True)
    # Stored separately from `created_at`'s indexed timestamp so the
    # metrics query can compute "today" / "yesterday" / "7d" buckets in
    # SQLite without a Python-side date conversion per row. Date-only,
    # UTC, format YYYY-MM-DD.
    day = db.Column(db.String(10), nullable=False, index=True)

    __table_args__ = (
        db.Index("ix_visitor_event_day_path", "day", "path"),
        db.Index("ix_visitor_event_day_visitor", "day", "visitor_hash"),
    )


class NotFoundEvent(db.Model):
    """One row per public-frontend 404 — a URL a visitor requested that
    resolved to nothing (an unmatched route or a handler that aborted
    404). Powers Watchtower's "404s" tab so admins can spot broken
    inbound links, mistyped URLs, and pages that were renamed/removed
    without a redirect.

    Recorded from the global 404 errorhandler, but only for public-site
    paths (admin ``/tspro`` 404s are excluded) and only while the public
    frontend is enabled. Asset fetches and obvious bots are dropped
    before insert, mirroring ``VisitorEvent``.

    Unlike VisitorEvent, this table keeps the *full* referrer URL: the
    whole point of the tab is "which page links to this dead URL", and
    for internal broken links the referrer is our own site (which
    VisitorEvent deliberately discards). It's operational data, not
    cross-site tracking.
    """
    __tablename__ = "not_found_event"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           index=True)
    # The 404'd path (e.g. "/old-page", "/blog/deleted-post"). Capped at
    # 500 chars to match the rest of the codebase's path columns.
    path = db.Column(db.String(500), nullable=False, index=True)
    # Full Referer header (the page that linked here), truncated to 500.
    # None = direct hit / no referer.
    referrer = db.Column(db.String(500))
    # Referrer origin (scheme+host) for grouping external sources; None
    # for direct hits and same-host (internal) referrers.
    referrer_host = db.Column(db.String(255))
    # Parsed UA classification — same buckets as VisitorEvent.
    device = db.Column(db.String(16), index=True)
    browser = db.Column(db.String(32))
    os = db.Column(db.String(32))
    # Daily-rotating one-way hash for unique-visitor approximation. Same
    # privacy properties as VisitorEvent.visitor_hash.
    visitor_hash = db.Column(db.String(32), index=True)
    # Source IP. Unlike VisitorEvent we DO persist the IP for 404s —
    # 404 logs are an abuse-investigation surface (scanner traffic,
    # vulnerability probes, link-rot from a specific source). Same
    # justification as LoginFailure.ip and ActivityLog.ip. Admin-only
    # surface; index keeps the "all 404s from this IP" lookup cheap.
    ip = db.Column(db.String(45), index=True)
    # Date-only UTC bucket (YYYY-MM-DD) so the tab's today/7d/window
    # rollups run in SQLite without a per-row date conversion.
    day = db.Column(db.String(10), nullable=False, index=True)

    __table_args__ = (
        db.Index("ix_not_found_event_day_path", "day", "path"),
        db.Index("ix_not_found_event_path_ip", "path", "ip"),
    )


BACKUP_KINDS = ("ftp", "sftp", "dropbox")
BACKUP_STATUS = ("ok", "failed", "running", "never_run")


class BackupTarget(db.Model):
    """An off-site destination for full app backups.

    The archive being uploaded is the same `tsp-export-<stamp>.zip` the
    Data tab's manual export produces (DB + uploads/ + zoom.key). Each
    target has its own schedule + retention; multiple targets can coexist
    so an admin can mirror to e.g. an FTP server daily and Dropbox weekly.
    """
    __tablename__ = "backup_target"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    kind = db.Column(db.String(16), nullable=False)  # ftp | sftp | dropbox
    enabled = db.Column(db.Boolean, nullable=False, default=False)

    # Connection — FTP/SFTP use host/port/username/password_enc; SFTP can
    # alternatively use private_key_enc.
    #
    # Dropbox: ``oauth_token_enc`` holds a legacy short-lived access
    # token (4-hour lifetime since Dropbox's Sept-2021 auth change) and
    # is kept only for backward compat with pre-2.1.11 targets. New
    # targets store a long-lived OAuth refresh token in
    # ``refresh_token_enc`` plus the app's ``app_key`` (plaintext —
    # half of a public OAuth client id) and ``app_secret_enc``
    # (encrypted) so the SDK can mint a fresh access token on every
    # call. ``DropboxBackend`` prefers the refresh-token path and
    # falls back to the legacy token when the refresh trio is empty.
    host = db.Column(db.String(255))
    port = db.Column(db.Integer)
    username = db.Column(db.String(255))
    password_enc = db.Column(db.LargeBinary)
    private_key_enc = db.Column(db.LargeBinary)
    oauth_token_enc = db.Column(db.LargeBinary)
    app_key = db.Column(db.String(64))
    app_secret_enc = db.Column(db.LargeBinary)
    refresh_token_enc = db.Column(db.LargeBinary)

    # FTPS toggle (FTP only). When false, plain FTP — surface a warning
    # in the wizard so the admin opts in deliberately.
    use_tls = db.Column(db.Boolean, nullable=False, default=True)

    # Remote target path. For FTP/SFTP this is a directory; for Dropbox
    # it's an app-folder-relative path that always starts with "/".
    remote_path = db.Column(db.String(500), default="/")

    # Schedule. Stored as a 5-field cron expression so we can present
    # presets in the wizard but accept custom values too.
    schedule_cron = db.Column(db.String(64), nullable=False, default="0 3 * * *")
    retain_count = db.Column(db.Integer, nullable=False, default=14)

    # Optional client-side archive encryption with a passphrase. When on,
    # we derive a Fernet key from the passphrase via PBKDF2 and wrap the
    # zip before upload. Passphrase itself is stored Fernet-encrypted so
    # the scheduler can use it unattended; losing the zoom.key means the
    # remote archives are unrecoverable, which is exactly what we want.
    encrypt_archive = db.Column(db.Boolean, nullable=False, default=False)
    archive_passphrase_enc = db.Column(db.LargeBinary)

    # Last-run status mirror for fast UI rendering without a join.
    last_run_at = db.Column(db.DateTime)
    last_status = db.Column(db.String(16), default="never_run")
    last_error = db.Column(db.Text)
    next_run_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    runs = db.relationship(
        "BackupRun",
        backref="target",
        cascade="all, delete-orphan",
        order_by="BackupRun.started_at.desc()",
    )


class BackupRun(db.Model):
    """One execution attempt of a BackupTarget — success or failure."""
    __tablename__ = "backup_run"
    id = db.Column(db.Integer, primary_key=True)
    target_id = db.Column(db.Integer, db.ForeignKey("backup_target.id", ondelete="CASCADE"), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    finished_at = db.Column(db.DateTime)
    status = db.Column(db.String(16), nullable=False, default="running")  # running|ok|failed
    archive_name = db.Column(db.String(255))
    bytes_uploaded = db.Column(db.BigInteger)
    error_message = db.Column(db.Text)
    triggered_by = db.Column(db.String(16), default="schedule")  # schedule|manual


class TrustedServantSubscriber(db.Model):
    """One row per entry on the Trusted Servants email list. Two paths
    create rows:

      1. A signed-in user clicks "Join the list" on the dashboard
         widget — ``user_id`` is set and the user can edit/remove their
         own entry via the widget on subsequent visits.
      2. An admin uses the manual-entry modal on /email-list to
         add an external contact who doesn't have a portal account —
         ``user_id`` is NULL; the row is admin-managed only.

    ``user_id`` is unique when set so a single user can't accumulate
    duplicate subscriptions, but multiple NULL rows are allowed (SQLite
    treats NULLs as distinct under UNIQUE). Contact details are stored
    separately from User.email / User.phone so a trusted servant can
    list a different preferred phone or email for fellowship-business
    contact than the one tied to their portal login."""
    __tablename__ = "trusted_servant_subscriber"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
                        nullable=True, unique=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(64))
    email = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text)  # admin-only annotations
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("trusted_servant_subscription",
                                                       uselist=False,
                                                       cascade="all, delete-orphan"))


class TrustedServantBlast(db.Model):
    """One row per mass email sent to the Trusted Servants list. Records
    who sent, what was sent, how many recipients it went to, and how
    many failed. Failures don't roll back the row — partial sends are
    surfaced via ``failed_count`` so an admin can see the outcome in the
    history list."""
    __tablename__ = "trusted_servant_blast"
    id = db.Column(db.Integer, primary_key=True)
    sent_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    subject = db.Column(db.String(500), nullable=False)
    body_md = db.Column(db.Text, nullable=False)
    recipient_count = db.Column(db.Integer, nullable=False, default=0)
    sent_count = db.Column(db.Integer, nullable=False, default=0)
    failed_count = db.Column(db.Integer, nullable=False, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    finished_at = db.Column(db.DateTime)

    sent_by = db.relationship("User")


class CustomForm(db.Model):
    """Admin-authored public form. Schema is the same shape as Page:
    an admin-visible ``title`` for the form list + a public-facing
    ``slug`` that turns into the form's URL on the public site
    (``/<slug>``). The field set lives in ``blocks_json`` as an ordered
    list of typed field blocks rendered by the Phase 2 builder; before
    Phase 2 ships the column is just empty / NULL.

    Submission flow: a public POST to the form's URL deposits a row in
    ``FormSubmission`` and emails the addresses in ``recipients_csv``;
    the operator sees the result in the Form Submissions admin page.

    The legacy events/announcements submission form and the dedicated
    contact form keep their own settings columns on ``SiteSetting`` —
    they pre-date CustomForm and have specialized backend behaviour
    (events-submission creates draft rows, contact-form persists in
    ``ContactSubmission``). CustomForm is for everything new.
    """
    __tablename__ = "custom_form"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    blocks_json = db.Column(db.Text)
    # Comma-separated recipient list. Each address gets one email per
    # submission; addresses are de-duped (lowercased) at send time.
    recipients_csv = db.Column(db.String(2000))
    # Two success behaviours, only one applies. ``redirect_url`` wins
    # when set; otherwise we render ``thank_you_message`` inline.
    redirect_url = db.Column(db.String(500))
    thank_you_message = db.Column(db.Text)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    submissions = db.relationship(
        "FormSubmission",
        backref="form",
        cascade="all, delete-orphan",
        order_by="FormSubmission.created_at.desc()",
    )


class FormSubmission(db.Model):
    """One row per public submission to a ``CustomForm``. Payload is a
    JSON blob of ``{field_name: value}`` keyed by the field's ``name``
    in the form's ``blocks_json``. File-typed fields store the saved
    filename (UUID-prefixed under ``UPLOAD_FOLDER``) rather than the
    binary content. ``ip`` is captured for spam triage (the same
    ProxyFix-aware request.remote_addr the rest of the app uses)."""
    __tablename__ = "form_submission"
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey("custom_form.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    payload_json = db.Column(db.Text)
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
