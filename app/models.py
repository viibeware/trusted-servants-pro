# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.ext.associationproxy import association_proxy

db = SQLAlchemy()

ROLES = ("admin", "editor", "frontend_editor", "intergroup_member", "viewer")

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
    dash_order_json = db.Column(db.Text)
    last_seen_at = db.Column(db.DateTime)

    def can_edit(self):
        """Broad editor gate: meetings, files, libraries, etc. Intergroup
        members inherit every Editor permission AND additionally pass
        the per-library Intergroup gate below."""
        return self.role in ("admin", "editor", "frontend_editor", "intergroup_member")

    def can_edit_frontend(self):
        """Authorized to edit the Web Frontend module and preview it while
        the public toggle is off. Includes admins and the dedicated
        frontend_editor role; regular editors are excluded."""
        return self.role in ("admin", "frontend_editor")

    def can_edit_intergroup_libraries(self):
        """True for admins and the dedicated `intergroup_member` role.
        Used by per-library edit gates on the Intergroup Documents and
        Intergroup Minutes libraries — regular editors and frontend
        editors are deliberately excluded so those libraries can be
        delegated to a narrow set of trusted servants."""
        return self.role in ("admin", "intergroup_member")

    def can_edit_library(self, library):
        """Effective edit permission for a single ``Library``. Libraries
        flagged ``is_intergroup`` are gated to admins + intergroup_members
        only; every other library uses the broad editor gate (which
        includes intergroup_members, since they inherit Editor)."""
        if library is not None and getattr(library, "is_intergroup", False):
            return self.can_edit_intergroup_libraries()
        return self.can_edit()

    def can_edit_reading(self, reading):
        """Per-reading gate for renaming / editing an existing reading
        (title change, file replacement, body / URL / thumbnail swap,
        inline category re-tag). Editors are restricted to readings
        whose creator was an editor-tier user — mirrors
        ``can_delete_reading`` so a single rule covers both rename and
        delete authority. Admin / intergroup_member / frontend_editor
        follow the broader ``can_edit_library`` gate; viewers fail at
        that gate."""
        if reading is None:
            return False
        if not self.can_edit_library(reading.library):
            return False
        if self.role == "editor":
            creator = reading.creator
            if creator is None:
                return False
            return creator.role in ("editor", "frontend_editor", "intergroup_member")
        return True

    def can_use_editor_tools(self):
        """Generic gate for utility endpoints used during editing
        (markdown preview, etc.). Aliased to ``can_edit`` since every
        role that has editor tools also passes the broad editor gate."""
        return self.can_edit()

    def can_bulk_edit_categories(self, reading):
        """Per-reading gate for the multi-select bulk-edit-categories
        action on the library detail page. Mirrors
        ``can_delete_reading`` exactly: if the user is allowed to
        destroy a reading, they're allowed to mass-tag it. This
        intentionally pulls frontend_editors out of the bulk surface
        too — they can edit individual readings but per the
        role-permission spec they have no authority over library-file
        deletion, and we want a single 'destructive enough' authority
        to gate both bulk operations."""
        return self.can_delete_reading(reading)

    def can_delete_reading(self, reading):
        """Per-reading deletion gate.

        - Admins: any reading.
        - Intergroup members: any reading inside a library they can edit
          (they have exclusive edit on Intergroup Documents/Minutes; for
          everything else they inherit the broad editor gate).
        - Editors: only readings whose creator was an editor-tier user
          (editor / frontend_editor / intergroup_member). Admin-created
          and legacy (creator=None) readings are protected — an admin
          must remove those. This stops a regular editor from purging
          authoritative content the admin maintains.
        - Frontend editors and viewers: never. Frontend editors inherit
          Editor for everything else but library-file deletion is held
          back per the role-permission spec.

        ``reading`` is the ``Reading`` row about to be deleted; ``None``
        is treated as a no-op deny."""
        if reading is None:
            return False
        if self.role == "admin":
            return True
        if self.role == "intergroup_member":
            return self.can_edit_library(reading.library)
        if self.role == "editor":
            creator = reading.creator
            if creator is None:
                return False
            return creator.role in ("editor", "frontend_editor", "intergroup_member")
        # frontend_editor + viewer fall through to deny.
        return False

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
    selected_readings = db.relationship("Reading", secondary=meeting_reading_selections)
    public_readings = db.relationship("Reading", secondary=meeting_reading_public)
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

    def visible_readings(self, library):
        if self.library_mode(library) == "granular":
            sel_ids = {r.id for r in self.selected_readings}
            return [r for r in library.readings if r.id in sel_ids]
        return library.readings.all()

    def selected_ids_for_library(self, library):
        sel_ids = {r.id for r in self.selected_readings}
        return [r.id for r in library.readings if r.id in sel_ids]


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
    address = db.Column(db.String(500))
    maps_url = db.Column(db.String(1000))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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
    # user), editor (admin + editor), frontend_editor (admin + frontend
    # editor), admin (admin only). Defaults preserve the historical
    # behavior — Posts admin-only, Intergroup/Zoom-Tech open to all,
    # Web Frontend reserved for admins + frontend editors.
    intergroup_required_role = db.Column(db.String(32), nullable=False, default="viewer")
    zoom_tech_required_role = db.Column(db.String(32), nullable=False, default="viewer")
    posts_required_role = db.Column(db.String(32), nullable=False, default="admin")
    frontend_module_required_role = db.Column(db.String(32), nullable=False, default="frontend_editor")
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
    frontend_logo_filename = db.Column(db.String(500))
    frontend_logo_width = db.Column(db.Integer, nullable=False, default=40)
    # Top alert bar (above header)
    top_alert_enabled = db.Column(db.Boolean, nullable=False, default=False)
    top_alert_message = db.Column(db.Text)
    top_alert_bg_color = db.Column(db.String(16))
    top_alert_text_color = db.Column(db.String(16))
    top_alert_icon = db.Column(db.String(32))
    top_alert_icon_position = db.Column(db.String(8), nullable=False, default="before")  # 'before' | 'after'
    # Under-header alert bar
    header_alert_enabled = db.Column(db.Boolean, nullable=False, default=False)
    header_alert_message = db.Column(db.Text)
    header_alert_bg_color = db.Column(db.String(16))
    header_alert_text_color = db.Column(db.String(16))
    header_alert_icon = db.Column(db.String(32))
    header_alert_icon_position = db.Column(db.String(8), nullable=False, default="before")
    setup_complete = db.Column(db.Boolean, nullable=False, default=False)
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
    # When True, uploads to this library must pick at least one
    # ``LibraryCategory``; when False, categories are still selectable
    # but optional. Surfaced on the library-edit modal as a toggle. Only
    # consulted on Intergroup libraries today, but the column is kept
    # general so non-Intergroup libraries can opt in later.
    categories_required = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    readings = db.relationship("Reading", backref="library", cascade="all, delete-orphan",
                               lazy="dynamic", order_by="Reading.position, Reading.id")
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
    readings = db.relationship("Reading", secondary=reading_categories,
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


class Reading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey("library.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text)
    url = db.Column(db.String(1000))
    stored_filename = db.Column(db.String(500))
    original_filename = db.Column(db.String(500))
    thumbnail_filename = db.Column(db.String(500))
    position = db.Column(db.Integer, nullable=False, default=0)
    # User who created the reading. Drives the per-reading deletion gate
    # for the Editor role (Editors may only delete readings whose creator
    # was an editor-tier user — admin-created content is protected).
    # Nullable so legacy rows survive the migration; legacy readings are
    # treated as admin-created (uneditable to non-admins) by the gate.
    created_by = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User", foreign_keys=[created_by])
    categories = db.relationship("LibraryCategory", secondary=reading_categories,
                                 back_populates="readings",
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
    link_size = db.Column(db.String(16))  # 'small' | 'large' | None (template default)
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
