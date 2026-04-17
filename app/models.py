from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy.ext.associationproxy import association_proxy

db = SQLAlchemy()

ROLES = ("admin", "editor", "viewer")
FILE_CATEGORIES = ("documents", "scripts", "external_links", "videos", "images")
DAYS_OF_WEEK = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

meeting_reading_selections = db.Table(
    "meeting_reading_selections",
    db.Column("meeting_id", db.Integer, db.ForeignKey("meeting.id", ondelete="CASCADE"), primary_key=True),
    db.Column("reading_id", db.Integer, db.ForeignKey("reading.id", ondelete="CASCADE"), primary_key=True),
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
    role = db.Column(db.String(16), nullable=False, default="viewer")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def can_edit(self):
        return self.role in ("admin", "editor")

    def is_admin(self):
        return self.role == "admin"


class Meeting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    alert_message = db.Column(db.Text)
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
    schedules = db.relationship("MeetingSchedule", backref="meeting",
                                cascade="all, delete-orphan", lazy="select",
                                order_by="MeetingSchedule.day_of_week, MeetingSchedule.start_time")

    def files_by_category(self, category):
        return self.files.filter_by(category=category).order_by(MeetingFile.position, MeetingFile.id).all()

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
    intergroup_enabled = db.Column(db.Boolean, nullable=False, default=False)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    readings = db.relationship("Reading", backref="library", cascade="all, delete-orphan",
                               lazy="dynamic", order_by="Reading.position, Reading.id")
    meeting_assocs = db.relationship("MeetingLibrary", back_populates="library",
                                     cascade="all, delete-orphan")
    meetings = association_proxy("meeting_assocs", "meeting",
                                 creator=lambda m: MeetingLibrary(meeting=m))


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UrlRedirect(db.Model):
    __tablename__ = "url_redirect"
    id = db.Column(db.Integer, primary_key=True)
    source_path = db.Column(db.String(2000), unique=True, nullable=False, index=True)
    target_path = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
