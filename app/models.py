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
    dash_show_deletions = db.Column(db.Boolean, nullable=False, default=True)
    dash_show_currently_online = db.Column(db.Boolean, nullable=False, default=True)
    dash_order_json = db.Column(db.Text)
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
    # Public visibility: when False (but module is enabled), signed-in editors
    # and admins can still preview while the public root redirects to login.
    frontend_enabled = db.Column(db.Boolean, nullable=False, default=False)
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
    # "Pro Tips" FAQ-style section rendered at the bottom of /meetings.
    # JSON blob with: enabled, heading, subheading, icon, icon_color,
    # bg_color, items[]. NULL = use defaults from
    # `meetings_list_protips_defaults()` in app/frontend.py.
    frontend_meetings_list_protips_json = db.Column(db.Text)
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
    # Staggered reveal animation when the mega menu opens (titles/links/buttons
    # fade in one after the other with a small slide + rotate).
    frontend_megamenu_animate = db.Column(db.Boolean, nullable=False, default=True)
    # Duration of each block's reveal animation, in milliseconds.
    frontend_megamenu_animate_ms = db.Column(db.Integer, nullable=False, default=320)
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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IntergroupAccount(db.Model):
    __tablename__ = "intergroup_account"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ZoomOtpEmail(db.Model):
    """Singleton: credentials for the shared email inbox that receives Zoom OTP codes."""
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255))
    password_enc = db.Column(db.LargeBinary)
    login_url = db.Column(db.String(1000))
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

    # Event location.
    is_online = db.Column(db.Boolean, nullable=False, default=False)
    location_name = db.Column(db.String(255))
    location_address = db.Column(db.Text)
    google_maps_url = db.Column(db.String(500))

    # Event website (free URL with a label so the link reads as the
    # admin wants it to read on the public site).
    website_url = db.Column(db.String(500))
    website_label = db.Column(db.String(120))

    # Zoom (announcements never have these; events do, when online).
    zoom_meeting_id = db.Column(db.String(64))
    zoom_passcode = db.Column(db.String(128))
    zoom_url = db.Column(db.String(500))

    # Contact.
    contact_name = db.Column(db.String(120))
    contact_phone = db.Column(db.String(64))
    contact_email = db.Column(db.String(255))

    # Lifecycle. Posts are in one of three states:
    #   draft    → is_draft=True  (edited in private; not on the public site)
    #   active   → both False     (live)
    #   archived → is_archived=True (hidden, kept for reference)
    is_draft = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))

    @property
    def public_slug(self):
        """Same shape as ``Meeting.public_slug`` — explicit slug if set,
        slugified title otherwise."""
        from .colors import slugify
        return slugify(self.slug) if self.slug else slugify(self.title)


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
